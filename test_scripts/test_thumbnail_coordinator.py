"""R4.3 — hybrid async thumbnail rasterization on a QThread worker.

Large, overlay-free thumbnail rebuilds are offloaded to a background `_ThumbnailWorker`
that renders pages off the R4.2 worker-snapshot bytes (never the live, non-thread-safe
`fitz.Document`) and marshals QImages back through `_ThumbnailBridge` to the GUI thread,
which converts them to QPixmaps. Watermarked sessions (view overlays) and small ranges
fall back to the existing synchronous batch path, so output is unchanged.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import fitz
from PySide6.QtGui import QImage, QPixmap

from controller.pdf_controller import PDFController
from controller.thumbnail_coordinator import (
    THUMB_ASYNC_MIN_PAGES,
    ThumbnailCoordinator,
    _ThumbnailBridge,
    _ThumbnailWorker,
)
from model.pdf_model import PDFModel


def _make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), f"page {i + 1}", fontsize=12, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def _snapshot_bytes(tmp: str, pages: int) -> bytes:
    pdf = Path(tmp) / "src.pdf"
    _make_pdf(pdf, pages)
    m = PDFModel()
    try:
        m.open_pdf(str(pdf))
        return m.capture_worker_snapshot_bytes()
    finally:
        m.close()


def _coord_controller(*, page_count: int, watermarks: list, sid: str = "sid-1", connect: bool = True):
    controller = PDFController.__new__(PDFController)
    model = MagicMock()
    model.doc = MagicMock()
    model.doc.__len__ = lambda self=None: page_count
    model.get_active_session_id = MagicMock(return_value=sid)
    model.capture_worker_snapshot_bytes = MagicMock(return_value=b"")
    model.get_thumbnail = MagicMock()
    controller.model = model
    controller.view = MagicMock()
    controller._thumb_gen_by_session = {sid: 3}
    controller._worker_snapshot_cache = None
    controller._render_revision_by_session = {}
    controller.get_watermarks = MagicMock(return_value=watermarks)
    controller._resolve_session_profile = MagicMock(return_value="srgb")
    coord = ThumbnailCoordinator(controller)
    controller._thumbnail_coordinator = coord
    if connect:
        # Parent on None in tests (the production parent is the QObject view).
        coord._bridge = _ThumbnailBridge(None)
        coord._bridge.batch_ready.connect(coord._on_batch_ready)
        coord._bridge.finished.connect(coord._on_finished)
    return controller, coord


# ── worker (runs synchronously; no thread needed) ───────────────────────────


def test_worker_renders_all_pages_in_batches() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        snap = _snapshot_bytes(tmp, 5)

    worker = _ThumbnailWorker(snap, 0, 5, 0.2, "srgb", 7, batch_size=2)
    batches: list[tuple] = []
    finished: list[int] = []
    worker.batch_ready.connect(lambda g, s, imgs: batches.append((g, s, imgs)))
    worker.finished.connect(lambda g: finished.append(g))

    worker.run()

    assert [b[1] for b in batches] == [0, 2, 4]
    assert sum(len(b[2]) for b in batches) == 5
    assert all(b[0] == 7 for b in batches)
    assert all(isinstance(im, QImage) and not im.isNull() for b in batches for im in b[2])
    assert finished == [7]


def test_worker_stops_when_cancelled_before_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        snap = _snapshot_bytes(tmp, 6)

    worker = _ThumbnailWorker(snap, 0, 6, 0.2, "srgb", 1, batch_size=2)
    batches: list[tuple] = []
    finished: list[int] = []
    worker.batch_ready.connect(lambda g, s, imgs: batches.append((g, s, imgs)))
    worker.finished.connect(lambda g: finished.append(g))

    worker.request_cancel()
    worker.run()

    assert batches == []
    assert finished == [1], "finished must always fire for thread teardown"


# ── eligibility (deterministic; no thread) ──────────────────────────────────


def test_should_async_false_when_watermarks_present() -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[{"id": "w1"}])
    assert coord._should_async(0, "sid-1", None) is False


def test_should_async_false_for_small_range() -> None:
    controller, coord = _coord_controller(page_count=THUMB_ASYNC_MIN_PAGES - 1, watermarks=[])
    assert coord._should_async(0, "sid-1", None) is False


def test_should_async_false_when_bridge_not_connected() -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[], connect=False)
    assert coord._should_async(0, "sid-1", None) is False


def test_should_async_true_for_large_overlay_free_range() -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[])
    assert coord._should_async(0, "sid-1", None) is True


def test_should_async_false_for_stale_session() -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[])
    assert coord._should_async(0, "other-sid", None) is False


# ── GUI-side painting + staleness guard (deterministic) ─────────────────────


def test_on_batch_ready_paints_fresh_gen(qapp) -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[])
    coord._session_id = "sid-1"
    img = QImage(8, 8, QImage.Format_RGB888)
    img.fill(0)

    coord._on_batch_ready(3, 4, [img, img])  # gen 3 == current thumb gen

    controller.view.update_thumbnail_batch.assert_called_once()
    start_index, pixmaps = controller.view.update_thumbnail_batch.call_args[0]
    assert start_index == 4
    assert all(isinstance(p, QPixmap) for p in pixmaps)


def test_on_batch_ready_drops_stale_gen() -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[])
    coord._session_id = "sid-1"
    img = QImage(8, 8, QImage.Format_RGB888)

    coord._on_batch_ready(1, 0, [img])  # gen 1 != current thumb gen 3

    controller.view.update_thumbnail_batch.assert_not_called()


# NOTE: a real-thread end-to-end test (try_start -> QThread -> bridge -> paint) was
# intentionally NOT committed. The QThread wiring here is byte-identical to the proven
# SearchCoordinator/OcrCoordinator, and a live cross-thread render test exhibits the same
# Qt/COM event-loop instability the suite already documents for the async search test
# (it passes in isolation but hangs/crashes when interleaved). The off-thread render is
# verified deterministically by test_worker_renders_all_pages_in_batches (worker.run), the
# decision by _should_async, and the GUI marshalling by the _on_batch_ready tests.


# ── scheduler delegation (the integration seam) ─────────────────────────────


def test_schedule_thumbnail_batch_delegates_to_coordinator_when_async() -> None:
    controller, coord = _coord_controller(page_count=200, watermarks=[])
    coord.try_start = MagicMock(return_value=True)

    controller._schedule_thumbnail_batch(0, "sid-1", 3)

    coord.try_start.assert_called_once_with(0, "sid-1", 3, None)
    # Async took over -> the synchronous per-page render must be skipped.
    controller.model.get_thumbnail.assert_not_called()


def test_schedule_thumbnail_batch_runs_sync_when_coordinator_declines(qapp) -> None:
    controller, coord = _coord_controller(page_count=3, watermarks=[])
    coord.try_start = MagicMock(return_value=False)
    controller._fitz_colorspace_for_session = MagicMock(return_value=None)

    # Use a real tiny pixmap so pixmap_to_qpixmap works on the sync fallback.
    doc = fitz.open()
    doc.new_page(width=40, height=40)
    controller.model.get_thumbnail = MagicMock(return_value=doc[0].get_pixmap())

    controller._schedule_thumbnail_batch(0, "sid-1", 3)

    coord.try_start.assert_called_once()
    controller.model.get_thumbnail.assert_called()  # sync path rendered
    controller.view.update_thumbnail_batch.assert_called_once()
    doc.close()
