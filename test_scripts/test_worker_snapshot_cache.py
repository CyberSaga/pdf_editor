"""R4.2 — controller-owned, revision-keyed worker snapshot-bytes cache.

`model.capture_worker_snapshot_bytes()` does a full `doc.tobytes()`; search, OCR and
print each capture it independently (GUI thread, before `QThread.start()`), so
overlapping jobs on an unedited doc re-serialize identical bytes. The controller caches
the bytes keyed on `(active_session_id, render_revision)` — the same token the page
render cache trusts.

The subtle correctness hazard (and the reason this is a 3-model item): OCR injects
INVISIBLE text (`render_mode=3`) via `apply_ocr_spans`, which changes `doc.tobytes()`
(searchable!) but is pixel-identical and so does NOT bump `_render_revision`. A naive
`(sid, revision)` cache would serve pre-OCR bytes to a later search → it misses the
OCR'd text, a silent regression vs the current always-fresh call. The OCR coordinator
must therefore drop the snapshot cache after applying spans.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from controller.ocr_coordinator import OcrCoordinator
from controller.pdf_controller import PDFController


def _counter_bytes():
    """Distinct bytes per call so a cache hit is observable by identity."""
    state = {"n": 0}

    def _make() -> bytes:
        state["n"] += 1
        return f"snapshot-{state['n']}".encode()

    return _make


def _minimal_controller(sid: str | None = "sid-1") -> PDFController:
    controller = PDFController.__new__(PDFController)
    model = MagicMock()
    model.get_active_session_id = MagicMock(return_value=sid)
    model.capture_worker_snapshot_bytes = MagicMock(side_effect=_counter_bytes())
    controller.model = model
    # State the cache method + _bump_render_revision touch.
    controller._worker_snapshot_cache = None
    controller._render_revision_by_session = {}
    controller._page_render_quality_by_session = {}
    controller._render_cache = {}
    controller._render_cache_total_bytes = 0
    return controller


def test_cache_hit_on_unedited_doc_serializes_once() -> None:
    controller = _minimal_controller()

    first = controller.capture_worker_snapshot_bytes()
    second = controller.capture_worker_snapshot_bytes()

    assert first == second
    assert first is second, "unedited doc must return the cached bytes object"
    assert controller.model.capture_worker_snapshot_bytes.call_count == 1


def test_render_revision_bump_invalidates_cache() -> None:
    controller = _minimal_controller()

    first = controller.capture_worker_snapshot_bytes()
    controller._bump_render_revision("sid-1")  # an edit / mutation
    second = controller.capture_worker_snapshot_bytes()

    assert first != second, "a render-revision bump must force a fresh serialization"
    assert controller.model.capture_worker_snapshot_bytes.call_count == 2


def test_no_active_session_bypasses_cache() -> None:
    controller = _minimal_controller(sid=None)

    first = controller.capture_worker_snapshot_bytes()
    second = controller.capture_worker_snapshot_bytes()

    # No session id -> never cached -> fresh each call.
    assert first != second
    assert controller.model.capture_worker_snapshot_bytes.call_count == 2
    assert controller._worker_snapshot_cache is None


def test_ocr_apply_invalidates_worker_snapshot_cache() -> None:
    """The regression guard: OCR injects invisible (searchable) text without bumping
    render_revision, so applying spans MUST drop the snapshot cache — otherwise a
    later search reads stale pre-OCR bytes and misses the recognized text."""
    controller = _minimal_controller()
    controller.model.apply_ocr_spans = MagicMock(return_value=1)
    coord = OcrCoordinator(controller)
    controller._ocr_coordinator = coord
    coord._ocr_gen = 7
    coord._ocr_session_id = "sid-1"

    # The OCR worker primes the cache when it captures its input snapshot.
    primed = controller.capture_worker_snapshot_bytes()
    assert controller._worker_snapshot_cache is not None

    # A page of OCR completes: invisible text injected, render_revision unchanged.
    coord._on_ocr_page_done(7, 1, [object()])
    controller.model.apply_ocr_spans.assert_called_once()

    assert controller._worker_snapshot_cache is None, (
        "apply_ocr_spans changes doc.tobytes() without a render bump — the snapshot "
        "cache must be invalidated or a later search serves stale pre-OCR bytes"
    )
    # And the next capture is genuinely fresh (would contain the OCR text).
    fresh = controller.capture_worker_snapshot_bytes()
    assert fresh != primed
