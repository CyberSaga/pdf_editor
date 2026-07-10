"""Codex F6 (B3) — bound the lifetime of decrypted bytes held by in-flight workers.

`cancel_ocr` / `_cancel_search` are non-blocking by design: they bump a generation token
and set the worker's cancel flag, then return. The worker keeps running until its next
checkpoint. Until now it also kept `self._doc_bytes` — a decrypted snapshot of the
document — for its whole object lifetime, which extends past `run()` until Qt actually
processes the pending `deleteLater()`. Closing a password-protected tab therefore left
plaintext reachable in the heap for an unbounded time.

The fix is race-free by construction: **the worker clears its own payload, on its own
thread.** Nothing on the GUI thread ever writes `_doc_bytes`; `request_cancel()` only
flips a bool. So there is no window to lose:

  * the search worker drops the reference immediately after `fitz.open()` — PyMuPDF keeps
    its own reference to the buffer, so the `Document` stays fully usable;
  * both workers clear it in `run()`'s `finally`, so a cancelled worker releases at its
    next checkpoint without the UI thread blocking on a join.

Irreducible residual (documented, not fixed): between `request_cancel()` and the worker
reaching that checkpoint, the in-flight page still has the bytes, and the live document is
decrypted in RAM regardless. See TODOS.md and docs/PITFALLS.md.
"""

from __future__ import annotations

import fitz

from controller.ocr_coordinator import _OcrWorker
from controller.search_coordinator import _SearchWorker


def _doc_bytes(text: str = "SECRET SEARCHABLE TEXT") -> bytes:
    doc = fitz.open()
    doc.new_page(width=200, height=200).insert_text((20, 40), text, fontsize=12, fontname="helv")
    try:
        return doc.tobytes()
    finally:
        doc.close()


def _worker_attrs_holding(worker: object, payload: bytes) -> list[str]:
    """Attribute names on `worker` that still reference `payload`.

    Refcounting is unusable here — `bytes` is a variable-size type so it cannot be
    weak-referenced even via a subclass, and pytest's assertion rewriting keeps its own
    temporaries alive in the frame. Inspecting the worker's own `__dict__` tests the
    property we actually care about: the worker retains no path to the decrypted snapshot.
    """
    return [name for name, value in vars(worker).items() if value is payload]


class _SearchTool:
    def __init__(self) -> None:
        self.pages_searched: list[int] = []

    def search_page_in_doc(self, doc, page_num, query):
        self.pages_searched.append(page_num)
        return list(doc[page_num - 1].search_for(query))


class _OcrTool:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def ocr_pages(self, page_nums, languages=None, device=None, doc=None):
        self.calls.extend(page_nums)
        return {page_nums[0]: []}


# ── search worker ───────────────────────────────────────────────────────────


def test_search_worker_releases_doc_bytes_after_completing(qapp) -> None:
    tool = _SearchTool()
    worker = _SearchWorker(tool, "SECRET", 1, gen=0, doc_bytes=_doc_bytes())

    hits: list = []
    worker.hits_found.connect(lambda _g, _p, h: hits.append(h))
    worker.run()

    assert tool.pages_searched == [1], "the search must still run"
    assert hits, "the search must still find its hit"
    assert worker._doc_bytes is None, "worker must not retain decrypted bytes after run()"


def test_cancelled_search_worker_releases_doc_bytes(qapp) -> None:
    tool = _SearchTool()
    worker = _SearchWorker(tool, "SECRET", 5, gen=0, doc_bytes=_doc_bytes())

    failures: list = []
    worker.failed.connect(lambda _g, exc: failures.append(exc))

    worker.request_cancel()  # non-blocking cancel, exactly as the coordinator issues it
    worker.run()

    assert failures == [], f"cancelled run must not raise: {failures}"
    assert tool.pages_searched == [], "cancel must stop before the first page"
    assert worker._doc_bytes is None


def test_search_worker_holds_no_reference_to_payload_after_run(qapp) -> None:
    """No strong reference to the decrypted snapshot survives inside the worker."""
    payload = _doc_bytes()

    worker = _SearchWorker(_SearchTool(), "SECRET", 1, gen=0, doc_bytes=payload)
    assert _worker_attrs_holding(worker, payload) == ["_doc_bytes"], "held before run"

    worker.run()

    assert worker._doc_bytes is None
    assert _worker_attrs_holding(worker, payload) == [], (
        "the decrypted snapshot is still reachable from the worker after it finished"
    )


def test_search_worker_with_no_doc_bytes_does_not_crash(qapp) -> None:
    """Regression: `doc` is None on the empty-bytes path, and `finally: doc.close()` raised."""

    class _FallbackTool:
        def __init__(self) -> None:
            self.pages: list[int] = []

        def search_page(self, page_num, query):
            self.pages.append(page_num)
            return []

    tool = _FallbackTool()
    worker = _SearchWorker(tool, "SECRET", 2, gen=0, doc_bytes=b"")

    failures: list = []
    worker.failed.connect(lambda _g, exc: failures.append(exc))
    worker.run()

    assert failures == [], f"empty doc_bytes must use the fallback, not raise: {failures}"
    assert tool.pages == [1, 2]


# ── OCR worker ──────────────────────────────────────────────────────────────


def test_cancelled_ocr_worker_releases_doc_bytes(qapp) -> None:
    tool = _OcrTool()
    worker = _OcrWorker(tool, [1, 2, 3], ["en"], "cpu", doc_bytes=_doc_bytes(), gen=0)

    worker.request_cancel()
    worker.run()

    assert tool.calls == [], "cancel must stop before the first page is OCR'd"
    assert worker._doc_bytes is None, "cancelled worker must drop its decrypted snapshot"


def test_completed_ocr_worker_releases_doc_bytes(qapp) -> None:
    tool = _OcrTool()
    worker = _OcrWorker(tool, [1], ["en"], "cpu", doc_bytes=_doc_bytes(), gen=0)
    worker.run()

    assert tool.calls == [1], "the OCR must still run"
    assert worker._doc_bytes is None


def test_ocr_worker_holds_no_reference_to_payload_after_cancel(qapp) -> None:
    payload = _doc_bytes()

    worker = _OcrWorker(_OcrTool(), [1, 2], ["en"], "cpu", doc_bytes=payload, gen=0)
    assert _worker_attrs_holding(worker, payload) == ["_doc_bytes"], "held before run"

    worker.request_cancel()
    worker.run()

    assert worker._doc_bytes is None
    assert _worker_attrs_holding(worker, payload) == [], (
        "the decrypted snapshot is still reachable from the worker after cancel"
    )


def test_ocr_worker_still_receives_doc_bytes_for_every_page(qapp) -> None:
    """The early clear must not starve a multi-page run: bytes survive the whole loop."""
    seen: list[bytes | None] = []

    class _RecordingTool:
        def ocr_pages(self, page_nums, languages=None, device=None, doc=None):
            seen.append(doc)
            return {page_nums[0]: []}

    payload = _doc_bytes()
    worker = _OcrWorker(_RecordingTool(), [1, 2, 3], ["en"], "cpu", doc_bytes=payload, gen=0)
    worker.run()

    assert len(seen) == 3
    assert all(d == payload for d in seen), "every page must get the document bytes"
    assert worker._doc_bytes is None
