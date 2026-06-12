from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread

from controller.pdf_controller import _OcrBridge, _OcrWorker
from model.tools.ocr_types import OcrAvailability, OcrRequest, OcrSpan


class _FakeTool:
    def __init__(self, per_page_spans: dict[int, list[OcrSpan]], delay: float = 0.0) -> None:
        self._per_page = per_page_spans
        self._delay = delay
        self.calls: list[tuple[list[int], list[str], str]] = []
        self.thread_ids: list[int] = []

    def ocr_pages(self, pages, languages, *, device="auto", on_progress=None, doc=None):
        self.calls.append((list(pages), list(languages), device))
        self.thread_ids.append(threading.get_ident())
        self.doc_ids = getattr(self, "doc_ids", [])
        self.doc_ids.append(id(doc))
        if self._delay:
            time.sleep(self._delay)
        result = {}
        for p in pages:
            spans = self._per_page.get(p, [])
            result[p] = list(spans)
            if on_progress:
                on_progress(p, len(result), len(pages))
        return result

    def availability(self) -> OcrAvailability:
        return OcrAvailability(available=True)


def _sample_doc_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page(width=100, height=100)
    data = doc.tobytes()
    doc.close()
    return data


def _drive_worker(worker: _OcrWorker, qapp) -> None:
    """Run the worker on a real QThread and pump events until `finished` fires."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    done = {"finished": False}

    def _mark_done():
        done["finished"] = True

    worker.finished.connect(_mark_done)
    worker.finished.connect(thread.quit)
    thread.start()

    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    # Guard against hangs: abort the loop after 5 seconds.
    from PySide6.QtCore import QTimer

    safety = QTimer()
    safety.setSingleShot(True)
    safety.timeout.connect(loop.quit)
    safety.start(5000)
    loop.exec()
    thread.wait(2000)


def test_worker_emits_page_done_and_progress(qapp):
    spans_page1 = [OcrSpan((0, 0, 10, 10), "a", 0.9)]
    spans_page2 = [OcrSpan((5, 5, 20, 20), "b", 0.8)]
    tool = _FakeTool({1: spans_page1, 2: spans_page2})

    worker = _OcrWorker(tool, page_nums=[1, 2], languages=["en"], device="auto", doc_bytes=_sample_doc_bytes())
    progress_events: list[tuple[int, int, int]] = []
    page_events: list[tuple[int, list]] = []
    worker.progress.connect(lambda g, p, d, t: progress_events.append((p, d, t)))
    worker.page_done.connect(lambda g, p, spans: page_events.append((p, list(spans))))

    _drive_worker(worker, qapp)

    assert progress_events == [(1, 1, 2), (2, 2, 2)]
    assert [p[0] for p in page_events] == [1, 2]
    assert page_events[0][1] == spans_page1
    assert page_events[1][1] == spans_page2


def test_worker_runs_on_non_gui_thread(qapp):
    tool = _FakeTool({1: [OcrSpan((0, 0, 10, 10), "a", 0.9)]})
    worker = _OcrWorker(tool, page_nums=[1], languages=["en"], device="auto", doc_bytes=_sample_doc_bytes())
    _drive_worker(worker, qapp)

    gui_thread_id = threading.get_ident()
    assert tool.thread_ids, "tool was never invoked"
    assert all(tid != gui_thread_id for tid in tool.thread_ids)


def test_worker_respects_cancel_between_pages(qapp):
    tool = _FakeTool(
        {p: [OcrSpan((0, 0, 5, 5), f"p{p}", 0.9)] for p in range(1, 6)},
        delay=0.05,
    )
    worker = _OcrWorker(tool, page_nums=[1, 2, 3, 4, 5], languages=["en"], device="auto", doc_bytes=_sample_doc_bytes())

    # Request cancel after the first page completes.
    page_events: list[int] = []

    def _on_page_done(_gen, page_num, _spans):
        page_events.append(page_num)
        if page_num == 1:
            worker.request_cancel()

    worker.page_done.connect(_on_page_done)
    _drive_worker(worker, qapp)

    assert 1 in page_events
    assert len(page_events) < 5


def test_worker_emits_failed_on_tool_exception(qapp):
    class _BoomTool:
        def ocr_pages(self, *args, **kwargs):
            raise RuntimeError("boom")

    worker = _OcrWorker(_BoomTool(), page_nums=[1], languages=["en"], device="auto", doc_bytes=_sample_doc_bytes())
    failures: list = []
    worker.failed.connect(lambda gen, exc: failures.append(exc))
    _drive_worker(worker, qapp)

    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)


def test_worker_forwards_device_and_languages(qapp):
    tool = _FakeTool({1: []})
    worker = _OcrWorker(tool, page_nums=[1], languages=["en", "zh-Hant"], device="cuda", doc_bytes=_sample_doc_bytes())
    _drive_worker(worker, qapp)
    assert tool.calls == [([1], ["en", "zh-Hant"], "cuda")]


def test_ocr_bridge_forwards_signals(qapp):
    bridge = _OcrBridge()
    progress_seen: list = []
    page_seen: list = []
    failed_seen: list = []
    thread_finished_seen: list = []
    bridge.progress.connect(lambda g, p, d, t: progress_seen.append((g, p, d, t)))
    bridge.page_done.connect(lambda g, p, spans: page_seen.append((g, p, list(spans))))
    bridge.failed.connect(lambda g, exc: failed_seen.append(exc))
    bridge.thread_finished.connect(lambda: thread_finished_seen.append(True))

    bridge.forward_progress(7, 1, 2, 3)
    bridge.forward_page_done(7, 1, [OcrSpan((0, 0, 1, 1), "x", 0.5)])
    bridge.forward_failed(7, RuntimeError("nope"))
    bridge.notify_thread_finished()
    QCoreApplication.processEvents()

    assert progress_seen == [(7, 1, 2, 3)]
    assert page_seen[0][:2] == (7, 1)
    assert isinstance(failed_seen[0], RuntimeError)
    assert thread_finished_seen == [True]


def test_controller_start_ocr_refuses_when_surya_missing(qapp, monkeypatch):
    from controller import pdf_controller

    shown: list[str] = []
    monkeypatch.setattr(pdf_controller, "show_error", lambda parent, msg: shown.append(msg))

    controller = _build_minimal_controller(monkeypatch, available=False)
    request = OcrRequest(page_indices=(0,), languages=("en",), device="auto")
    controller.start_ocr(request)
    assert shown, "expected error dialog"
    assert controller._ocr_thread is None


def test_controller_start_ocr_applies_spans_per_page(qapp, monkeypatch):
    controller = _build_minimal_controller(
        monkeypatch,
        available=True,
        per_page={1: [OcrSpan((0, 0, 10, 10), "one", 0.9)], 2: [OcrSpan((0, 0, 10, 10), "two", 0.8)]},
    )
    request = OcrRequest(page_indices=(0, 1), languages=("en",), device="auto")
    controller.start_ocr(request)

    # Wait for the worker thread to finish.
    _wait_for_ocr_finish(controller, qapp)

    apply = controller.model.apply_ocr_spans
    assert apply.call_count == 2
    calls = [c.args for c in apply.call_args_list]
    assert calls[0][0] == 1
    assert calls[1][0] == 2
    assert isinstance(calls[0][1], list)
    assert controller.model.tools.ocr.doc_ids == [id(controller.model.capture_worker_snapshot_bytes.return_value)] * 2


def test_controller_ocr_ignores_stale_session_page_done(qapp, monkeypatch):
    controller = _build_minimal_controller(
        monkeypatch,
        available=True,
        per_page={1: [OcrSpan((0, 0, 10, 10), "one", 0.9)]},
    )
    controller.model.get_active_session_id = MagicMock(return_value="sid-2")
    controller._ocr_session_id = "sid-1"
    controller._ocr_gen = 5
    controller._ocr_thread = None
    controller._ocr_worker = None

    # gen matches (5) so this isolates the session guard.
    controller._on_ocr_page_done(5, 1, [OcrSpan((0, 0, 10, 10), "one", 0.9)])

    controller.model.apply_ocr_spans.assert_not_called()


def test_controller_cancel_ocr_sets_worker_flag(qapp, monkeypatch):
    controller = _build_minimal_controller(monkeypatch, available=True, per_page={1: [], 2: []}, delay=0.3)
    request = OcrRequest(page_indices=(0, 1), languages=("en",), device="auto")
    controller.start_ocr(request)
    # Cancel immediately
    controller.cancel_ocr()
    _wait_for_ocr_finish(controller, qapp)
    assert controller._ocr_worker is None or controller._ocr_thread is None


def test_controller_ocr_drops_stale_gen_page_done(qapp, monkeypatch):
    """A queued page_done from a previous (cancelled) run carries an old gen
    and must be dropped even when the session still matches."""
    controller = _build_minimal_controller(
        monkeypatch,
        available=True,
        per_page={1: [OcrSpan((0, 0, 10, 10), "one", 0.9)]},
    )
    controller.model.get_active_session_id = MagicMock(return_value="sid-1")
    controller._ocr_session_id = "sid-1"
    controller._ocr_gen = 5

    controller._on_ocr_page_done(4, 1, [OcrSpan((0, 0, 10, 10), "one", 0.9)])

    controller.model.apply_ocr_spans.assert_not_called()


def test_controller_cancel_ocr_invalidates_generation(qapp, monkeypatch):
    """cancel_ocr must bump the gen token so late queued signals are dropped."""
    controller = _build_minimal_controller(monkeypatch, available=True, per_page={1: []}, delay=0.3)
    request = OcrRequest(page_indices=(0,), languages=("en",), device="auto")
    controller.start_ocr(request)
    gen_at_start = controller._ocr_gen
    controller.cancel_ocr()
    assert controller._ocr_gen > gen_at_start
    _wait_for_ocr_finish(controller, qapp)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _build_minimal_controller(monkeypatch, *, available: bool, per_page: dict | None = None, delay: float = 0.0):
    """Create a PDFController with its view replaced by a stub and model mocked."""
    from controller.pdf_controller import PDFController

    model = MagicMock()
    model.doc = MagicMock()
    model.doc.__len__ = lambda self=None: 10
    model.apply_ocr_spans = MagicMock(return_value=1)
    model.capture_worker_snapshot_bytes = MagicMock(return_value=b"snapshot-bytes")

    tool = _FakeTool(per_page or {}, delay=delay)

    def _fake_availability():
        return OcrAvailability(available=True) if available else OcrAvailability(
            available=False, reason="surya missing", install_hint="pip install surya-ocr"
        )

    tool.availability = _fake_availability  # type: ignore[assignment]
    model.tools = MagicMock()
    model.tools.ocr = tool

    view = MagicMock()
    view.thread = lambda: QCoreApplication.instance().thread()

    controller = PDFController.__new__(PDFController)
    controller.model = model
    controller.view = view
    controller._ocr_thread = None
    controller._ocr_worker = None
    controller._ocr_worker_bridge = _OcrBridge(None)
    controller._ocr_progress_dialog = None
    controller._ocr_gen = 0
    controller._ocr_session_id = None
    # Wire bridge to controller handlers (mirrors activate()).
    controller._ocr_worker_bridge.page_done.connect(controller._on_ocr_page_done)
    controller._ocr_worker_bridge.progress.connect(controller._on_ocr_progress)
    controller._ocr_worker_bridge.failed.connect(controller._on_ocr_failed)
    controller._ocr_worker_bridge.thread_finished.connect(controller._on_ocr_thread_finished)
    return controller


def _wait_for_ocr_finish(controller, qapp, timeout_ms: int = 4000) -> None:
    loop = QEventLoop()
    from PySide6.QtCore import QTimer

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    def _check():
        if controller._ocr_thread is None:
            loop.quit()
        else:
            QTimer.singleShot(20, _check)

    QTimer.singleShot(0, _check)
    loop.exec()
