"""Hybrid async thumbnail coordinator (R4.3 performance deferral).

Large, overlay-free thumbnail rebuilds are the one remaining synchronous rasterization
on the Qt main thread (`_schedule_thumbnail_batch` rendered `model.get_thumbnail` inline
inside a `QTimer` chain). This coordinator offloads them to a background `_ThumbnailWorker`
that renders pages off the R4.2 worker-snapshot bytes — never the live, non-thread-safe
`fitz.Document` — and marshals detached `QImage`s back through `_ThumbnailBridge` onto the
GUI thread, which converts them to `QPixmap`s (a GUI-thread-only type) and paints them.

Behavior-preserving by construction: the async path is taken ONLY when the session has no
view overlays (watermarks compose at render time and are absent from the snapshot bytes,
so a worker render would drop them) and the range is large enough to amortize the thread.
Otherwise the caller falls back to the existing synchronous path, byte-for-byte unchanged.

The thumbnail generation token (`controller._thumb_gen_by_session`) is the cancellation /
staleness guard: a tab switch or a fresh invalidation bumps it, and stale batches that
arrive afterwards are dropped before painting (a cancelled tab must not paint over a new
one). The QThread lifecycle mirrors `SearchCoordinator`/`OcrCoordinator`: controller refs
are dropped on `thread.finished` (never `worker.finished`), so the C++ thread object is
never freed while still running.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from model.color_profile import safe_to_fitz_colorspace
from utils.helpers import pixmap_to_qimage

if TYPE_CHECKING:
    from controller.pdf_controller import PDFController

logger = logging.getLogger(__name__)

# Below this many pages a thread (spawn + snapshot capture) costs more than it saves;
# small affected-page invalidations (rotate/move) stay on the cheap synchronous path.
THUMB_ASYNC_MIN_PAGES = 24

# Mirror the on-screen thumbnail render (model.get_thumbnail -> get_page_pixmap scale=0.2).
THUMB_RENDER_SCALE = 0.2
THUMB_WORKER_BATCH_SIZE = 10


class _ThumbnailWorker(QObject):
    """Renders thumbnail pages from snapshot bytes on a background thread.

    Emits one ``batch_ready`` per chunk so the sidebar fills progressively. Every signal
    carries the generation token so the GUI side can drop a cancelled tab's late batches.
    """

    batch_ready = Signal(int, int, list)  # gen, start_index, list[QImage]
    finished = Signal(int)  # gen

    def __init__(
        self,
        doc_bytes: bytes,
        start: int,
        end_n: int,
        scale: float,
        profile: str,
        gen: int,
        batch_size: int = THUMB_WORKER_BATCH_SIZE,
    ) -> None:
        super().__init__()
        self._doc_bytes = doc_bytes
        self._start = int(start)
        self._end_n = int(end_n)
        self._scale = float(scale)
        self._profile = profile
        self._gen = gen
        self._batch_size = max(1, int(batch_size))
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        # Local import avoids a model<->controller import cycle at module load and keeps the
        # central MediaBox clamp identical to the synchronous render path.
        from model.pdf_model import _safe_render_scale  # noqa: PLC0415

        try:
            doc = fitz.open("pdf", self._doc_bytes) if self._doc_bytes else None
            if doc is None:
                return
            try:
                colorspace = safe_to_fitz_colorspace(self._profile)
                i = self._start
                while i < self._end_n:
                    if self._cancel_requested:
                        break
                    images: list[QImage] = []
                    j = i
                    while j < min(i + self._batch_size, self._end_n):
                        if self._cancel_requested:
                            break
                        page = doc[j]
                        scale = _safe_render_scale(page, self._scale)
                        matrix = fitz.Matrix(scale, scale)
                        pix = page.get_pixmap(matrix=matrix, annots=True, colorspace=colorspace)
                        images.append(pixmap_to_qimage(pix))
                        j += 1
                    if images and not self._cancel_requested:
                        self.batch_ready.emit(self._gen, i, images)
                    i = j
            finally:
                doc.close()
        except Exception as exc:
            logger.exception("Thumbnail worker failed: %s", exc)
        finally:
            self.finished.emit(self._gen)


class _ThumbnailBridge(QObject):
    """GUI-thread bridge: re-emits worker signals so handlers run on the GUI thread."""

    batch_ready = Signal(int, int, list)
    finished = Signal(int)

    @Slot(int, int, list)
    def forward_batch_ready(self, gen: int, start_index: int, images) -> None:
        self.batch_ready.emit(gen, start_index, images)

    @Slot(int)
    def forward_finished(self, gen: int) -> None:
        self.finished.emit(gen)


class ThumbnailCoordinator:
    """Owns the async-thumbnail runtime for one PDFController.

    The controller holds exactly one of these (`self._thumbnail_coordinator`);
    `_schedule_thumbnail_batch` asks `try_start(...)` to offload a large overlay-free
    rebuild and only renders synchronously when it declines.
    """

    def __init__(self, controller: PDFController) -> None:
        self._c = controller
        self._thread: QThread | None = None
        self._worker: _ThumbnailWorker | None = None
        self._bridge: _ThumbnailBridge | None = None
        self._session_id: str | None = None

    def connect_bridge(self) -> None:
        """Lazy-init the GUI-thread bridge and wire it to the handlers (from activate())."""
        if self._bridge is None:
            self._bridge = _ThumbnailBridge(self._c.view)
            self._bridge.batch_ready.connect(self._on_batch_ready)
            self._bridge.finished.connect(self._on_finished)

    def _should_async(self, start: int, session_id: str, end_limit: int | None) -> bool:
        """True iff this thumbnail range should be rendered off-thread.

        Off-thread is only safe/correct when: the bridge is wired (post-activate); the
        session is still active; the doc exists; the range is large enough to amortize the
        thread; and the session has NO view overlays (watermarks are absent from the
        snapshot bytes the worker renders, so a worker render would silently drop them).
        """
        if self._bridge is None:
            return False
        if not self._c.model.doc or self._c.model.get_active_session_id() != session_id:
            return False
        n = end_limit if end_limit is not None else len(self._c.model.doc)
        if n - start < THUMB_ASYNC_MIN_PAGES:
            return False
        if self._c.get_watermarks():
            return False
        return True

    def try_start(self, start: int, session_id: str, gen: int, end_limit: int | None) -> bool:
        """Start an async render for ``[start, n)`` and return True, or False to fall back.

        Returning True means the caller must NOT render synchronously — this coordinator
        owns the whole range from ``start`` onward.
        """
        if not self._should_async(start, session_id, end_limit):
            return False

        self.cancel()
        n = end_limit if end_limit is not None else len(self._c.model.doc)
        profile = self._c._resolve_session_profile(session_id)
        doc_bytes = self._c.capture_worker_snapshot_bytes()

        thread = QThread()
        worker = _ThumbnailWorker(doc_bytes, start, n, THUMB_RENDER_SCALE, profile, gen)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if self._bridge is not None:
            worker.batch_ready.connect(self._bridge.forward_batch_ready)
            worker.finished.connect(self._bridge.forward_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Drop refs only once the THREAD finished (not the worker): releasing the Python
        # QThread wrapper while the thread still runs lets GC destroy the C++ object and
        # hard-crash the process.
        thread.finished.connect(lambda t=thread: self._release(t))

        self._thread = thread
        self._worker = worker
        self._session_id = session_id
        thread.start()
        return True

    def _release(self, thread) -> None:
        if self._thread is thread:
            self._thread = None
            self._worker = None

    def cancel(self) -> None:
        """Cancel any in-flight thumbnail worker (quit() is thread-safe)."""
        worker = self._worker
        thread = self._thread
        self._worker = None
        self._thread = None
        if worker is not None:
            worker.request_cancel()
        if thread is not None and thread.isRunning():
            thread.quit()

    @Slot(int, int, list)
    def _on_batch_ready(self, gen: int, start_index: int, images) -> None:
        sid = self._session_id
        # Drop a cancelled tab's late batch (tab switch) or a superseded generation
        # (a fresh invalidation bumped _thumb_gen_by_session) before it paints.
        if sid is None or self._c.model.get_active_session_id() != sid:
            return
        if self._c._thumb_gen_by_session.get(sid) != gen:
            return
        pixmaps = [QPixmap.fromImage(img) for img in images]
        self._c.view.update_thumbnail_batch(start_index, pixmaps)

    @Slot(int)
    def _on_finished(self, gen: int) -> None:
        return None
