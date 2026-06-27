from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from typing import Callable

import fitz
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from model.color_profile import safe_to_fitz_colorspace
from utils.helpers import pixmap_to_qimage


@dataclass(frozen=True)
class ThumbnailFileSource:
    """Immutable identity and authentication data for a clean PDF on disk."""

    path: str
    size: int
    mtime_ns: int
    password: str | None


@dataclass(frozen=True)
class ThumbnailRequest:
    token: str
    session_id: str
    generation: int
    start: int
    end: int
    color_profile: str


class _ThumbnailWorker(QObject):
    batch_ready = Signal(str, str, int, int, object)
    failed = Signal(str, str, int, object)
    finished = Signal(str, str, int, bool)

    def __init__(self, request: ThumbnailRequest, source: ThumbnailFileSource) -> None:
        super().__init__()
        self._request = request
        self._source = source
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        doc: fitz.Document | None = None
        succeeded = False
        try:
            stat = os.stat(self._source.path)
            if stat.st_size != self._source.size or stat.st_mtime_ns != self._source.mtime_ns:
                raise RuntimeError("thumbnail source changed after dispatch")
            doc = fitz.open(self._source.path)
            if doc.needs_pass:
                password = self._source.password
                if password is None or doc.authenticate(password) == 0:
                    raise RuntimeError("thumbnail source authentication failed")
            colorspace = safe_to_fitz_colorspace(self._request.color_profile)
            end = min(self._request.end, len(doc))
            for page_index in range(self._request.start, end):
                if self._cancelled.is_set() or QThread.currentThread().isInterruptionRequested():
                    break
                pixmap = doc[page_index].get_pixmap(matrix=fitz.Matrix(0.2, 0.2), colorspace=colorspace)
                image = pixmap_to_qimage(pixmap)
                if self._cancelled.is_set() or QThread.currentThread().isInterruptionRequested():
                    break
                self.batch_ready.emit(
                    self._request.token,
                    self._request.session_id,
                    self._request.generation,
                    page_index,
                    [image],
                )
            succeeded = not self._cancelled.is_set()
        except Exception as exc:  # worker failures are handed back to the GUI fallback
            self.failed.emit(
                self._request.token,
                self._request.session_id,
                self._request.generation,
                exc,
            )
        finally:
            if doc is not None:
                doc.close()
            self.finished.emit(
                self._request.token,
                self._request.session_id,
                self._request.generation,
                succeeded,
            )


class ThumbnailCoordinator(QObject):
    """Select a file worker or a one-page-per-turn live thumbnail renderer."""

    def __init__(
        self,
        *,
        source_resolver: Callable[[ThumbnailRequest], ThumbnailFileSource | None],
        live_renderer: Callable[[int, str], QImage],
        batch_consumer: Callable[[int, list[QImage]], None],
        identity_matches: Callable[[str, int], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_resolver = source_resolver
        self._live_renderer = live_renderer
        self._batch_consumer = batch_consumer
        self._identity_matches = identity_matches
        self._active: ThumbnailRequest | None = None
        self._threads: dict[str, tuple[QThread, _ThumbnailWorker]] = {}

    @property
    def has_active_job(self) -> bool:
        return self._active is not None

    def request(
        self,
        session_id: str,
        generation: int,
        start: int,
        end: int,
        color_profile: str,
    ) -> str:
        # Cancellation deliberately precedes source selection. A synchronous fallback
        # can therefore never leave the superseded file worker running as an owner.
        self.cancel()
        request = ThumbnailRequest(
            token=str(uuid.uuid4()),
            session_id=session_id,
            generation=generation,
            start=start,
            end=max(start, end),
            color_profile=color_profile,
        )
        source = self._source_resolver(request)
        self._active = request
        if source is None:
            QTimer.singleShot(0, lambda req=request: self._render_live_page(req, req.start))
        else:
            self._start_worker(request, source)
        return request.token

    def cancel(self, session_id: str | None = None) -> None:
        active = self._active
        if session_id is not None and active is not None and active.session_id != session_id:
            return
        self._active = None
        for thread, worker in list(self._threads.values()):
            worker.cancel()
            thread.requestInterruption()

    def wait_for_done(self, timeout_ms: int = 3000) -> bool:
        stopped = True
        for thread, _worker in list(self._threads.values()):
            thread.quit()
            stopped = thread.wait(timeout_ms) and stopped
        return stopped

    def _start_worker(self, request: ThumbnailRequest, source: ThumbnailFileSource) -> None:
        thread = QThread(self)
        worker = _ThumbnailWorker(request, source)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.batch_ready.connect(self._accept_batch)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._worker_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda token=request.token: QTimer.singleShot(0, lambda: self._thread_finished(token))
        )
        thread.finished.connect(thread.deleteLater)
        self._threads[request.token] = (thread, worker)
        thread.start()

    def _is_current(self, token: str, session_id: str, generation: int) -> bool:
        active = self._active
        return bool(
            active is not None
            and active.token == token
            and active.session_id == session_id
            and active.generation == generation
            and self._identity_matches(session_id, generation)
        )

    @Slot(str, str, int, int, object)
    def _accept_batch(
        self,
        token: str,
        session_id: str,
        generation: int,
        start: int,
        images: list[QImage],
    ) -> None:
        if not self._is_current(token, session_id, generation):
            return
        self._batch_consumer(start, images)

    def _render_live_page(self, request: ThumbnailRequest, page_index: int) -> None:
        if not self._is_current(request.token, request.session_id, request.generation):
            return
        if page_index >= request.end:
            self._active = None
            return
        image = self._live_renderer(page_index, request.color_profile)
        self._accept_batch(
            request.token,
            request.session_id,
            request.generation,
            page_index,
            [image],
        )
        # Exactly one MuPDF render occurs per callback. The next page is handed to
        # Qt so input and painting events get an event-loop turn between pages.
        QTimer.singleShot(0, lambda req=request, page=page_index + 1: self._render_live_page(req, page))

    @Slot(str, str, int, object)
    def _worker_failed(self, token: str, session_id: str, generation: int, _exc: Exception) -> None:
        if not self._is_current(token, session_id, generation):
            return
        request = self._active
        if request is not None:
            QTimer.singleShot(0, lambda req=request: self._render_live_page(req, req.start))

    @Slot(str, str, int, bool)
    def _worker_finished(
        self,
        token: str,
        session_id: str,
        generation: int,
        succeeded: bool,
    ) -> None:
        if succeeded and self._is_current(token, session_id, generation):
            self._active = None

    def _thread_finished(self, token: str) -> None:
        self._threads.pop(token, None)
