"""Session-scoped QThread coordinator for the exact plan-backed preview.

Modeled on ``controller/page_render_coordinator.py`` (immutable work
requests, one worker, signal-only thread crossing, staleness guards), but
session-scoped: one worker thread lives for a whole inline-edit session
and owns one ``PlanPreviewRenderer`` (one scratch document), so a
keystroke never re-snapshots or re-opens the document.

Staleness contract: a result is delivered only when (a) its session is
still the active session, (b) its generation is the newest requested one,
and (c) the injected ``identity_matches`` callback accepts it.  At most
one request is in flight; a newer request replaces any queued one
(latest-wins).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal, Slot

from model.edit_requests import StyleOverrides
from model.text_commit.preview import (
    PlanPreviewRenderer,
    PlanPreviewRequest,
    PlanPreviewResult,
    PreviewSessionInput,
)


@dataclass(frozen=True)
class PlanPreviewIdentity:
    token: str
    session_key: str
    generation: int


class _PlanPreviewWorker(QObject):
    """Lives on the worker thread; owns the session's scratch renderer."""

    resulted = Signal(object, object)  # (PlanPreviewIdentity, PlanPreviewResult)
    failed = Signal(object, object)  # (PlanPreviewIdentity, Exception)

    def __init__(self, session: PreviewSessionInput) -> None:
        super().__init__()
        self._session = session
        self._renderer: PlanPreviewRenderer | None = None

    @Slot(object, object)
    def render(self, identity: PlanPreviewIdentity,
               request: PlanPreviewRequest) -> None:
        try:
            if self._renderer is None:
                # Lazily created here so the scratch document belongs to
                # this thread for its entire lifetime.
                self._renderer = PlanPreviewRenderer(self._session)
            result = self._renderer.render(request)
        except Exception as exc:
            self.failed.emit(identity, exc)
            return
        self.resulted.emit(identity, result)

    @Slot()
    def shutdown(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        thread = QThread.currentThread()
        if thread is not None:
            thread.quit()


class TextCommitPreviewCoordinator(QObject):
    """Own one preview thread per edit session; deliver only fresh results."""

    _dispatch = Signal(object, object)  # queued into the worker thread
    _shutdown = Signal()  # queued into the worker thread

    def __init__(
        self,
        *,
        result_consumer: Callable[[PlanPreviewIdentity, PlanPreviewResult], None],
        failure_consumer: Callable[[PlanPreviewIdentity, Exception], None],
        identity_matches: Callable[[PlanPreviewIdentity], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._result_consumer = result_consumer
        self._failure_consumer = failure_consumer
        self._identity_matches = identity_matches
        self._session: PreviewSessionInput | None = None
        self._thread: QThread | None = None
        self._worker: _PlanPreviewWorker | None = None
        # Retired (thread, worker) pairs stay referenced until the thread has
        # finished: dropping the last Python reference to an unparented
        # QObject destroys its C++ object immediately — from the WRONG
        # thread, while queued events may still be in flight (crash).
        self._retired: list[tuple[QThread, _PlanPreviewWorker]] = []
        self._inflight: PlanPreviewIdentity | None = None
        self._pending: tuple[PlanPreviewIdentity, PlanPreviewRequest] | None = None
        self._latest_generation: int | None = None

    # ---------------------------------------------------------- lifecycle

    @property
    def has_active_session(self) -> bool:
        return self._session is not None

    @property
    def session_key(self) -> str | None:
        return self._session.session_key if self._session is not None else None

    @property
    def has_active_job(self) -> bool:
        return self._inflight is not None or self._pending is not None

    def begin_session(self, session: PreviewSessionInput) -> None:
        if self._session is not None:
            self.end_session()
        self._session = session
        self._latest_generation = None
        self._purge_finished_retirees()
        thread = QThread(self)
        worker = _PlanPreviewWorker(session)
        worker.moveToThread(thread)
        # Cross-thread delivery is automatic (queued) because the emitting
        # thread differs from the receiver's thread affinity.
        self._dispatch.connect(worker.render)
        self._shutdown.connect(worker.shutdown)
        worker.resulted.connect(self._accept_result)
        worker.failed.connect(self._accept_failure)
        self._thread = thread
        self._worker = worker
        thread.start()

    def end_session(self) -> None:
        """Stop accepting work; late results for this session are dropped."""
        if self._session is None:
            return
        self._pending = None
        self._session = None
        self._latest_generation = None
        self._inflight = None
        worker = self._worker
        thread = self._thread
        self._worker = None
        self._thread = None
        if worker is not None and thread is not None:
            self._dispatch.disconnect(worker.render)
            # Queued behind any in-flight render on the worker thread: close
            # the renderer there, then quit the thread's event loop.  The
            # already-posted metacall survives the disconnect below.
            self._shutdown.emit()
            self._shutdown.disconnect(worker.shutdown)
            self._retired.append((thread, worker))

    def wait_for_done(self, timeout_ms: int = 1000) -> bool:
        self.end_session()
        stopped = True
        for thread, _worker in self._retired:
            stopped = thread.wait(timeout_ms) and stopped
        self._purge_finished_retirees()
        return stopped

    def _purge_finished_retirees(self) -> None:
        self._retired = [
            (t, w) for (t, w) in self._retired if not t.isFinished()
        ]

    # ------------------------------------------------------------ request

    def request(
        self,
        *,
        generation: int,
        target_text: str,
        replacement_text: str,
        expected_origin: tuple[float, float] | None,
        target_bbox: tuple[float, float, float, float] | None,
        clip_rect: tuple[float, float, float, float],
        render_scale: float,
        style_overrides: StyleOverrides | None = None,
        new_rect: tuple[float, float, float, float] | None = None,
        whitespace_reconstructed: bool = False,
    ) -> str | None:
        session = self._session
        if session is None:
            return None
        identity = PlanPreviewIdentity(
            token=str(uuid.uuid4()),
            session_key=session.session_key,
            generation=int(generation),
        )
        work = PlanPreviewRequest(
            session_key=session.session_key,
            generation=int(generation),
            target_text=target_text,
            replacement_text=replacement_text,
            expected_origin=expected_origin,
            target_bbox=target_bbox,
            clip_rect=tuple(float(v) for v in clip_rect),  # type: ignore[arg-type]
            render_scale=float(render_scale),
            style_overrides=style_overrides,
            new_rect=new_rect,
            whitespace_reconstructed=bool(whitespace_reconstructed),
        )
        self._latest_generation = identity.generation
        if self._inflight is not None:
            self._pending = (identity, work)  # latest-wins
        else:
            self._inflight = identity
            self._dispatch.emit(identity, work)
        return identity.token

    # ------------------------------------------------------------ results

    def _is_current(self, identity: PlanPreviewIdentity) -> bool:
        session = self._session
        return bool(
            session is not None
            and identity.session_key == session.session_key
            and identity.generation == self._latest_generation
            and self._identity_matches(identity)
        )

    def _finish_one(self, identity: PlanPreviewIdentity) -> bool:
        """Free the in-flight slot (same session only) and start queued work."""
        inflight = self._inflight
        if inflight is None or inflight.token != identity.token:
            # A retired session's late result: never touches the new
            # session's in-flight slot.
            return False
        current = self._is_current(identity)
        self._inflight = None
        pending = self._pending
        self._pending = None
        if pending is not None and self._session is not None:
            self._inflight = pending[0]
            self._dispatch.emit(*pending)
        return current

    @Slot(object, object)
    def _accept_result(self, identity: PlanPreviewIdentity,
                       result: PlanPreviewResult) -> None:
        if self._finish_one(identity):
            self._result_consumer(identity, result)

    @Slot(object, object)
    def _accept_failure(self, identity: PlanPreviewIdentity,
                        exc: Exception) -> None:
        if self._finish_one(identity):
            self._failure_consumer(identity, exc)
