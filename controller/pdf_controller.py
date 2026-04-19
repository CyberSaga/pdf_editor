from __future__ import annotations

import difflib
import io
import logging
import tempfile
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QProgressDialog

from model.edit_commands import AddTextboxCommand, EditTextCommand, EditTextResult, SnapshotCommand
from model.object_requests import (
    BatchDeleteObjectsRequest,
    BatchMoveObjectsRequest,
    DeleteObjectRequest,
    InsertImageObjectRequest,
    MoveObjectRequest,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from model.pdf_model import PDFModel
from utils.helpers import pixmap_to_qpixmap, show_error
from view.pdf_view import EditTextRequest, MoveTextRequest, OptimizePdfDialog, PDFView, ViewportAnchor

THUMB_BATCH_SIZE = 10
THUMB_BATCH_INTERVAL_MS = 30
INDEX_BATCH_SIZE = 5
INDEX_BATCH_INTERVAL_MS = 50
FIRST_PAGE_PREVIEW_SCALE = 0.25
VISIBLE_PREFETCH_PAGES = 1
VISIBLE_RENDER_BATCH_SIZE = 2
LOW_RES_RENDER_SCALE = 0.5
RENDER_CACHE_BUDGET_BYTES = 96 * 1024 * 1024

from src.printing import PrintDispatcher, PrintHelperTerminatedError, PrintingError
from src.printing.helper_protocol import PrintHelperJob
from src.printing.messages import (
    PRINT_CLOSING_MESSAGE as CLEAN_PRINT_CLOSING_MESSAGE,
)
from src.printing.messages import (
    PRINT_PREPARING_MESSAGE as CLEAN_PRINT_PREPARING_MESSAGE,
)
from src.printing.messages import (
    PRINT_STALLED_MESSAGE as CLEAN_PRINT_STALLED_MESSAGE,
)
from src.printing.messages import (
    PRINT_STATUS_MESSAGE as CLEAN_PRINT_STATUS_MESSAGE,
)
from src.printing.messages import (
    PRINT_SUBMITTING_MESSAGE as CLEAN_PRINT_SUBMITTING_MESSAGE,
)
from src.printing.messages import (
    PRINT_TERMINATE_BUTTON_TEXT as CLEAN_PRINT_TERMINATE_BUTTON_TEXT,
)
from src.printing.messages import (
    PRINT_TERMINATING_MESSAGE as CLEAN_PRINT_TERMINATING_MESSAGE,
)
from src.printing.print_dialog import UnifiedPrintDialog
from src.printing.subprocess_runner import PrintSubprocessRunner

OPEN_BACKGROUND_FALLBACK_MS = 250

logger = logging.getLogger(__name__)

PRINT_STATUS_MESSAGE = "列印中..."
PRINT_PREPARING_MESSAGE = "正在準備列印工作，請稍候..."
PRINT_SUBMITTING_MESSAGE = "正在送出列印工作，請稍候..."
PRINT_CLOSING_MESSAGE = "正在完成最後工作，請稍候..."
PRINT_STALLED_MESSAGE = "列印子系統沒有回應，您可以終止背景列印工作。"
PRINT_TERMINATING_MESSAGE = "正在終止背景列印工作，請稍候..."
PRINT_TERMINATE_BUTTON_TEXT = "終止列印工作"


PRINT_STATUS_MESSAGE = CLEAN_PRINT_STATUS_MESSAGE
PRINT_PREPARING_MESSAGE = CLEAN_PRINT_PREPARING_MESSAGE
PRINT_SUBMITTING_MESSAGE = CLEAN_PRINT_SUBMITTING_MESSAGE
PRINT_CLOSING_MESSAGE = CLEAN_PRINT_CLOSING_MESSAGE
PRINT_STALLED_MESSAGE = CLEAN_PRINT_STALLED_MESSAGE
PRINT_TERMINATING_MESSAGE = CLEAN_PRINT_TERMINATING_MESSAGE
PRINT_TERMINATE_BUTTON_TEXT = CLEAN_PRINT_TERMINATE_BUTTON_TEXT

@dataclass
class SessionUIState:
    current_page: int = 0
    scale: float = 1.0
    search_state: dict = field(default_factory=lambda: {"query": "", "results": [], "index": -1})
    mode: str = "browse"
    viewport_anchor: ViewportAnchor | None = None


@dataclass
class FullscreenSessionSnapshot:
    current_page: int
    scale: float
    anchor: ViewportAnchor


@dataclass(frozen=True)
class PrintJobRequest:
    capture_pdf_bytes: Callable[[], bytes]
    watermarks: list[dict]
    options: object
    job_id: str
    work_dir: str


@dataclass(frozen=True)
class OptimizePdfCopyRequest:
    output_path: str
    options: object


class _PrintSubmissionWorker(QObject):
    progress = Signal(str)
    prepared = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, request: PrintJobRequest) -> None:
        super().__init__()
        self._request = request

    def run(self) -> None:
        try:
            self.progress.emit(PRINT_PREPARING_MESSAGE)
            pdf_bytes = self._request.capture_pdf_bytes()
            input_pdf_path = Path(self._request.work_dir) / "input.pdf"
            input_pdf_path.write_bytes(pdf_bytes)
            self.prepared.emit(
                PrintHelperJob(
                    job_id=self._request.job_id,
                    input_pdf_path=str(input_pdf_path),
                    watermarks=self._request.watermarks,
                    options=self._request.options,
                )
            )
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class _PrintWorkerBridge(QObject):
    """Marshals worker-thread callbacks back onto the GUI thread."""

    progress = Signal(str)
    prepared = Signal(object)
    failed = Signal(object)
    thread_finished = Signal()

    @Slot(str)
    def forward_progress(self, message: str) -> None:
        self.progress.emit(message)

    @Slot(object)
    def forward_prepared(self, job) -> None:
        self.prepared.emit(job)

    @Slot(object)
    def forward_failed(self, exc) -> None:
        self.failed.emit(exc)

    @Slot()
    def notify_thread_finished(self) -> None:
        self.thread_finished.emit()


class _OptimizePdfCopyWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, model: PDFModel, request: OptimizePdfCopyRequest) -> None:
        super().__init__()
        self._model = model
        self._request = request

    def run(self) -> None:
        try:
            result = self._model.save_optimized_copy(
                self._request.output_path,
                self._request.options,
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class _OptimizeWorkerBridge(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    thread_finished = Signal()

    @Slot(object)
    def forward_succeeded(self, result) -> None:
        self.succeeded.emit(result)

    @Slot(object)
    def forward_failed(self, exc) -> None:
        self.failed.emit(exc)

    @Slot()
    def notify_thread_finished(self) -> None:
        self.thread_finished.emit()


class _OcrWorker(QObject):
    """Runs Surya OCR one page at a time on a background thread."""

    progress = Signal(int, int, int)
    page_done = Signal(int, object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        tool,
        page_nums: list[int],
        languages: list[str],
        device: str,
    ) -> None:
        super().__init__()
        self._tool = tool
        self._page_nums = list(page_nums)
        self._languages = list(languages)
        self._device = device
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            total = len(self._page_nums)
            for index, page_num in enumerate(self._page_nums, start=1):
                if self._cancel_requested:
                    break
                result = self._tool.ocr_pages(
                    [page_num],
                    languages=self._languages,
                    device=self._device,
                )
                spans = list(result.get(page_num, []))
                self.page_done.emit(page_num, spans)
                self.progress.emit(page_num, index, total)
        except Exception as exc:
            logger.exception("OCR worker failed")
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class _OcrBridge(QObject):
    progress = Signal(int, int, int)
    page_done = Signal(int, object)
    failed = Signal(object)
    thread_finished = Signal()

    @Slot(int, int, int)
    def forward_progress(self, page_num: int, done: int, total: int) -> None:
        self.progress.emit(page_num, done, total)

    @Slot(int, object)
    def forward_page_done(self, page_num: int, spans) -> None:
        self.page_done.emit(page_num, spans)

    @Slot(object)
    def forward_failed(self, exc) -> None:
        self.failed.emit(exc)

    @Slot()
    def notify_thread_finished(self) -> None:
        self.thread_finished.emit()


class PDFController:
    _VALID_MODES = {"browse", "edit_text", "add_text", "rect", "highlight", "add_annotation"}
    def __init__(self, model: PDFModel, view: PDFView):
        self.model = model
        self.view = view
        self.annotations = []
        self.print_dispatcher: PrintDispatcher | None = None
        self._print_dialog = None
        self._print_progress_dialog: QProgressDialog | None = None
        self._print_thread: QThread | None = None
        self._print_worker: _PrintSubmissionWorker | None = None
        self._print_runner: PrintSubprocessRunner | None = None
        self._print_worker_bridge: _PrintWorkerBridge | None = None
        self._print_close_pending = False
        self._print_stalled = False
        self._optimize_progress_dialog: QProgressDialog | None = None
        self._optimize_thread: QThread | None = None
        self._optimize_worker: _OptimizePdfCopyWorker | None = None
        self._optimize_worker_bridge: _OptimizeWorkerBridge | None = None
        self._optimize_paused_session_id: str | None = None
        self._ocr_progress_dialog: QProgressDialog | None = None
        self._ocr_thread: QThread | None = None
        self._ocr_worker: _OcrWorker | None = None
        self._ocr_worker_bridge: _OcrBridge | None = None
        self._load_gen_by_session: dict[str, int] = {}
        self._render_gen_by_session: dict[str, int] = {}
        self._stale_index_gen_by_session: dict[str, int] = {}
        self._session_ui_state: dict[str, SessionUIState] = {}
        self._desired_scroll_page: dict[str, int] = {}
        self._open_priority_page_by_session: dict[str, int] = {}
        self._background_loading_started_by_session: dict[str, bool] = {}
        self._render_batch_pending_by_session: dict[str, bool] = {}
        self._page_sizes_by_session: dict[str, list[tuple[float, float]]] = {}
        self._page_render_quality_by_session: dict[str, dict[int, str]] = {}
        self._render_revision_by_session: dict[str, int] = {}
        self._render_cache: OrderedDict[tuple[str, int, int, str, int], tuple[QPixmap, int]] = OrderedDict()
        self._render_cache_total_bytes = 0
        self._fullscreen_session_snapshots: dict[str, FullscreenSessionSnapshot] = {}
        self._global_mode = self._normalize_mode(getattr(self.view, "current_mode", "browse"))
        self._signals_connected = False
        self._activated = False

    @property
    def is_active(self) -> bool:
        return self._activated

    def activate(self) -> None:
        if self._activated:
            return
        if self._print_worker_bridge is None:
            self._print_worker_bridge = _PrintWorkerBridge(self.view)
            self._print_worker_bridge.progress.connect(self._update_print_progress_dialog)
            self._print_worker_bridge.prepared.connect(self._on_print_job_prepared)
            self._print_worker_bridge.failed.connect(self._on_print_submission_failed)
            self._print_worker_bridge.thread_finished.connect(self._on_print_thread_finished)
        if self._optimize_worker_bridge is None:
            self._optimize_worker_bridge = _OptimizeWorkerBridge(self.view)
            self._optimize_worker_bridge.succeeded.connect(self._on_optimize_copy_succeeded)
            self._optimize_worker_bridge.failed.connect(self._on_optimize_copy_failed)
            self._optimize_worker_bridge.thread_finished.connect(self._on_optimize_thread_finished)
        if self._ocr_worker_bridge is None:
            self._ocr_worker_bridge = _OcrBridge(self.view)
            self._ocr_worker_bridge.progress.connect(self._on_ocr_progress)
            self._ocr_worker_bridge.page_done.connect(self._on_ocr_page_done)
            self._ocr_worker_bridge.failed.connect(self._on_ocr_failed)
            self._ocr_worker_bridge.thread_finished.connect(self._on_ocr_thread_finished)
        if self.print_dispatcher is None:
            self.print_dispatcher = PrintDispatcher()
        if not self._signals_connected:
            self._connect_signals()
            self._signals_connected = True
        self._activated = True
        self._refresh_ocr_availability()

    def _refresh_ocr_availability(self) -> None:
        updater = getattr(self.view, "update_ocr_availability", None)
        if not callable(updater):
            return
        tool = getattr(getattr(self.model, "tools", None), "ocr", None)
        if tool is None:
            updater(False, "OCR 工具未啟用")
            return
        try:
            info = tool.availability()
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.warning("OCR availability probe failed: %s", exc)
            updater(False, str(exc))
            return
        if info.available:
            updater(True, "")
        else:
            parts = [p for p in (info.reason, info.install_hint) if p]
            updater(False, "\n".join(parts) or "OCR 工具不可用")

    def _connect_signals(self):
        # Existing connections
        self.view.sig_open_pdf.connect(self.open_pdf)
        self.view.sig_tab_changed.connect(self.on_tab_changed)
        self.view.sig_tab_close_requested.connect(self.on_tab_close_requested)
        self.view.sig_print_requested.connect(self.print_document)
        self.view.sig_save_as.connect(self.save_as)
        self.view.sig_save.connect(self.save)
        self.view.sig_delete_pages.connect(self.delete_pages)
        self.view.sig_rotate_pages.connect(self.rotate_pages)
        self.view.sig_export_pages.connect(self.export_pages)
        self.view.sig_add_highlight.connect(self.add_highlight)
        self.view.sig_add_rect.connect(self.add_rect)
        self.view.sig_edit_text.connect(self.edit_text)
        self.view.sig_move_text_across_pages.connect(self.move_text_across_pages)
        self.view.sig_add_textbox.connect(self.add_textbox)
        if hasattr(self.view, "sig_add_image_object"):
            self.view.sig_add_image_object.connect(self.add_image_object)
        self.view.sig_move_object.connect(self.move_object)
        self.view.sig_delete_object.connect(self.delete_object)
        self.view.sig_rotate_object.connect(self.rotate_object)
        if hasattr(self.view, "sig_resize_object"):
            self.view.sig_resize_object.connect(self.resize_object)
        self.view.sig_jump_to_result.connect(self.jump_to_result)
        self.view.sig_search.connect(self.search_text)
        if hasattr(self.view, "sig_start_ocr"):
            self.view.sig_start_ocr.connect(self.start_ocr)
        self.view.sig_undo.connect(self.undo)
        self.view.sig_redo.connect(self.redo)
        self.view.sig_mode_changed.connect(self._update_mode)
        self.view.sig_page_changed.connect(self.change_page)
        self.view.sig_scale_changed.connect(self.change_scale)
        self.view.sig_viewport_changed.connect(self._on_viewport_changed)
        self.view.sig_toggle_fullscreen.connect(self.toggle_fullscreen)
        self.view.sig_text_target_mode_changed.connect(self.set_text_target_mode)

        # New annotation connections
        self.view.sig_add_annotation.connect(self.add_annotation)
        self.view.sig_load_annotations.connect(self.load_annotations)
        self.view.sig_jump_to_annotation.connect(self.jump_to_annotation)
        self.view.sig_toggle_annotations_visibility.connect(self.toggle_annotations_visibility)

        # Snapshot connection
        self.view.sig_snapshot_page.connect(self.snapshot_page)

        # Insert pages connections
        self.view.sig_insert_blank_page.connect(self.insert_blank_page)
        self.view.sig_insert_pages_from_file.connect(self.insert_pages_from_file)
        self.view.sig_merge_pdfs_requested.connect(self.start_merge_pdfs)
        self.view.sig_optimize_pdf_copy_requested.connect(self.start_optimize_pdf_copy)

        # Watermark connections
        self.view.sig_add_watermark.connect(self.add_watermark)
        self.view.sig_update_watermark.connect(self.update_watermark)
        self.view.sig_remove_watermark.connect(self.remove_watermark)
        self.view.sig_load_watermarks.connect(self.load_watermarks)

        # Zoom re-render connection
        self.view.sig_request_rerender.connect(self._on_request_rerender)

        # Align model granularity with UI default at startup.
        combo = getattr(self.view, "text_target_mode_combo", None)
        if combo is not None:
            mode = combo.currentData()
            if mode in ("run", "paragraph"):
                self.set_text_target_mode(mode)

    def _next_load_gen(self, session_id: str) -> int:
        gen = self._load_gen_by_session.get(session_id, 0) + 1
        self._load_gen_by_session[session_id] = gen
        return gen

    def _next_render_gen(self, session_id: str) -> int:
        gen = self._render_gen_by_session.get(session_id, 0) + 1
        self._render_gen_by_session[session_id] = gen
        return gen

    def _next_stale_index_gen(self, session_id: str) -> int:
        gen = self._stale_index_gen_by_session.get(session_id, 0) + 1
        self._stale_index_gen_by_session[session_id] = gen
        return gen

    def _pause_session_background_loading(self, session_id: str | None) -> None:
        if not session_id:
            return
        self._next_load_gen(session_id)
        self._next_render_gen(session_id)
        self._next_stale_index_gen(session_id)
        self._render_batch_pending_by_session[session_id] = False

    def _start_open_background_loading(self, session_id: str) -> None:
        if not session_id or not self.model.doc:
            return
        if self.model.get_active_session_id() != session_id:
            return
        self._background_loading_started_by_session[session_id] = True
        load_gen = self._load_gen_by_session.get(session_id)
        if load_gen is not None:
            QTimer.singleShot(0, lambda sid=session_id, gen=load_gen: self._schedule_thumbnail_batch(0, sid, gen))
        self._schedule_deferred_sidebar_scans(session_id)

    def _maybe_start_background_loading_after_render(self, session_id: str, page_idx: int, quality: str) -> None:
        if quality != "high":
            return
        if self._background_loading_started_by_session.get(session_id):
            return
        if self._open_priority_page_by_session.get(session_id) != page_idx:
            return
        self._background_loading_started_by_session[session_id] = True
        self._start_open_background_loading(session_id)

    def _start_open_background_loading_if_current(self, session_id: str, load_gen: int) -> None:
        if self.model.get_active_session_id() != session_id:
            return
        if self._load_gen_by_session.get(session_id) != load_gen:
            return
        if self._background_loading_started_by_session.get(session_id):
            return
        self._start_open_background_loading(session_id)

    def _capture_current_ui_state(self) -> None:
        sid = self.model.get_active_session_id()
        if not sid:
            return
        self._session_ui_state[sid] = SessionUIState(
            current_page=max(0, self.view.current_page),
            scale=max(0.1, min(float(self.view.scale), 4.0)),
            search_state=self.view.get_search_ui_state(),
            mode=self._normalize_mode(getattr(self.view, "current_mode", "browse")),
            viewport_anchor=self.view.capture_viewport_anchor(),
        )

    def _get_ui_state(self, session_id: str) -> SessionUIState:
        state = self._session_ui_state.get(session_id)
        if state is None:
            state = SessionUIState()
            self._session_ui_state[session_id] = state
        return state

    def _refresh_document_tabs(self) -> None:
        tabs = self.model.list_sessions()
        active_idx = self.model.get_active_session_index()
        self.view.set_document_tabs(tabs, active_idx)
        active_sid = self.model.get_active_session_id()
        default_save_as_path = None
        if active_sid:
            meta = self.model.get_session_meta(active_sid) or {}
            default_save_as_path = (
                meta.get("saved_path")
                or meta.get("path")
                or meta.get("display_name")
                or "未命名.pdf"
            )
        self.view.set_save_as_default_path(default_save_as_path)

    def _normalize_mode(self, mode: str) -> str:
        return mode if mode in self._VALID_MODES else "browse"

    def _apply_session_mode(self, mode: str) -> None:
        normalized = self._normalize_mode(mode)
        current = self._normalize_mode(getattr(self.view, "current_mode", "browse"))
        if current != normalized:
            self.view.set_mode(normalized)

    def _empty_search_state(self) -> dict:
        return {"query": "", "results": [], "index": -1}

    def _capture_fullscreen_snapshot(self, session_id: str | None = None, use_current_view: bool = True) -> None:
        sid = session_id or self.model.get_active_session_id()
        if not sid or sid in self._fullscreen_session_snapshots:
            return
        # Record the pre-fullscreen zoom+anchor so we can restore per-tab layout on exit.
        state = self._get_ui_state(sid)
        if use_current_view:
            current_page = max(0, self.view.current_page)
            scale = max(0.1, float(self.view.scale))
            anchor = self.view.capture_viewport_anchor()
        else:
            current_page = max(0, state.current_page)
            scale = max(0.1, float(state.scale))
            anchor = state.viewport_anchor or ViewportAnchor(current_page, 0, 0)
        self._fullscreen_session_snapshots[sid] = FullscreenSessionSnapshot(
            current_page=current_page,
            scale=scale,
            anchor=anchor,
        )

    def _fullscreen_is_blocked(self) -> bool:
        if not self.model.doc:
            return True
        if self._has_active_print_submission():
            return True
        app = QApplication.instance()
        if app is None:
            return False
        for candidate in (app.activeModalWidget(), app.activePopupWidget()):
            if candidate is not None and self.view._is_widget_owned_by_main(candidate):
                return True
        return False

    def _apply_fullscreen_fit_for_active_session(self) -> None:
        if not self.view.is_fullscreen_active() or not self.model.doc:
            return
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._capture_fullscreen_snapshot(session_id)
        target_page = max(0, self.view.current_page)
        scale = self.view.compute_contain_scale_for_page(target_page)
        self.change_scale(target_page, scale)

    def _restore_fullscreen_session_state(self, session_id: str, snapshot: FullscreenSessionSnapshot) -> None:
        state = self._get_ui_state(session_id)
        state.scale = snapshot.scale
        state.current_page = snapshot.current_page
        state.viewport_anchor = snapshot.anchor

    def _restore_active_fullscreen_anchor(self, snapshot: FullscreenSessionSnapshot) -> None:
        self.view.restore_viewport_anchor(snapshot.anchor)

    def _restore_viewport_anchor_if_current(self, session_id: str, gen: int, anchor: ViewportAnchor | None) -> None:
        if anchor is None:
            return
        if self.model.get_active_session_id() != session_id:
            return
        if self._load_gen_by_session.get(session_id) != gen:
            return
        self.view.restore_viewport_anchor(anchor)

    def _schedule_restore_viewport_anchor(self, session_id: str, gen: int, anchor: ViewportAnchor | None) -> None:
        if anchor is None:
            return
        QTimer.singleShot(0, lambda sid=session_id, g=gen, a=anchor: self._restore_viewport_anchor_if_current(sid, g, a))
        QTimer.singleShot(180, lambda sid=session_id, g=gen, a=anchor: self._restore_viewport_anchor_if_current(sid, g, a))

    def _session_page_sizes(self, session_id: str) -> list[tuple[float, float]]:
        cached = self._page_sizes_by_session.get(session_id)
        if cached and self.model.doc and len(cached) == len(self.model.doc):
            return cached
        if not self.model.doc:
            return []
        sizes = [(float(page.rect.width), float(page.rect.height)) for page in self.model.doc]
        self._page_sizes_by_session[session_id] = sizes
        return sizes

    def _render_revision(self, session_id: str) -> int:
        return self._render_revision_by_session.get(session_id, 0)

    def _bump_render_revision(self, session_id: str | None = None) -> None:
        sid = session_id or self.model.get_active_session_id()
        if not sid:
            return
        self._render_revision_by_session[sid] = self._render_revision_by_session.get(sid, 0) + 1
        self._page_render_quality_by_session[sid] = {}
        self._drop_render_cache_for_session(sid)

    def _drop_render_cache_for_session(self, session_id: str) -> None:
        doomed = [key for key in self._render_cache.keys() if key[0] == session_id]
        for key in doomed:
            _, cost = self._render_cache.pop(key)
            self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - cost)

    def _render_cache_key(self, session_id: str, page_idx: int, rendered_scale: float, quality: str) -> tuple[str, int, int, str, int]:
        return (
            session_id,
            page_idx,
            int(round(rendered_scale * 1000)),
            quality,
            self._render_revision(session_id),
        )

    def _get_cached_render(self, session_id: str, page_idx: int, rendered_scale: float, quality: str) -> QPixmap | None:
        key = self._render_cache_key(session_id, page_idx, rendered_scale, quality)
        cached = self._render_cache.pop(key, None)
        if cached is None:
            return None
        pixmap, cost = cached
        self._render_cache[key] = (pixmap, cost)
        return pixmap

    def _store_cached_render(self, session_id: str, page_idx: int, rendered_scale: float, quality: str, pixmap: QPixmap) -> None:
        key = self._render_cache_key(session_id, page_idx, rendered_scale, quality)
        cost = max(1, pixmap.width()) * max(1, pixmap.height()) * 4
        previous = self._render_cache.pop(key, None)
        if previous is not None:
            self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - previous[1])
        self._render_cache[key] = (pixmap, cost)
        self._render_cache_total_bytes += cost
        while self._render_cache_total_bytes > RENDER_CACHE_BUDGET_BYTES and self._render_cache:
            _, (_, old_cost) = self._render_cache.popitem(last=False)
            self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - old_cost)

    def _render_scale_for_quality(self, target_scale: float, quality: str) -> float:
        target = max(0.1, float(target_scale))
        if quality != "low":
            return target
        return min(target, LOW_RES_RENDER_SCALE)

    def _render_page_into_scene(self, session_id: str, page_idx: int, quality: str) -> bool:
        if (
            self.model.get_active_session_id() != session_id
            or not self.model.doc
            or page_idx < 0
            or page_idx >= len(self.model.doc)
        ):
            return False
        target_scale = max(0.1, float(self.view.scale))
        rendered_scale = self._render_scale_for_quality(target_scale, quality)
        cached = self._get_cached_render(session_id, page_idx, rendered_scale, quality)
        if cached is None:
            pix = self.model.get_page_pixmap(page_idx + 1, rendered_scale)
            cached = pixmap_to_qpixmap(pix)
            self._store_cached_render(session_id, page_idx, rendered_scale, quality, cached)
        self.view.update_page_in_scene_scaled(page_idx, cached, rendered_scale, target_scale)
        self._page_render_quality_by_session.setdefault(session_id, {})[page_idx] = quality
        self._maybe_start_background_loading_after_render(session_id, page_idx, quality)
        return True

    def _visible_render_targets(self) -> tuple[list[int], list[int]]:
        if not self.view.page_items:
            return ([], [])
        visible_start, visible_end = self.view.visible_page_range(prefetch=0)
        prefetch_start, prefetch_end = self.view.visible_page_range(prefetch=VISIBLE_PREFETCH_PAGES)
        visible_pages = list(range(visible_start, visible_end + 1)) if visible_end >= visible_start else []
        prefetch_pages = list(range(prefetch_start, prefetch_end + 1)) if prefetch_end >= prefetch_start else []
        return (visible_pages, prefetch_pages)

    def _schedule_visible_render(self, session_id: str, immediate_page_idx: int | None = None) -> None:
        if not session_id or not self.model.doc or not self.view.continuous_pages:
            return
        if immediate_page_idx is not None:
            current_quality = self._page_render_quality_by_session.setdefault(session_id, {}).get(immediate_page_idx)
            if current_quality not in {"low", "high"}:
                self._render_page_into_scene(session_id, immediate_page_idx, "low")
        if self._render_batch_pending_by_session.get(session_id):
            return
        gen = self._next_render_gen(session_id)
        self._render_batch_pending_by_session[session_id] = True
        QTimer.singleShot(0, lambda sid=session_id, g=gen: self._process_visible_render_batch(sid, g))

    def _process_visible_render_batch(self, session_id: str, gen: int) -> None:
        if (
            self.model.get_active_session_id() != session_id
            or self._render_gen_by_session.get(session_id) != gen
            or not self.model.doc
            or not self.view.continuous_pages
        ):
            self._render_batch_pending_by_session[session_id] = False
            return
        visible_pages, prefetch_pages = self._visible_render_targets()
        if not prefetch_pages:
            self._render_batch_pending_by_session[session_id] = False
            return

        page_quality = self._page_render_quality_by_session.setdefault(session_id, {})
        candidates: list[tuple[int, str]] = []
        for page_idx in visible_pages:
            quality = page_quality.get(page_idx)
            if quality is None:
                candidates.append((page_idx, "low"))
            elif quality == "low":
                candidates.append((page_idx, "high"))
        for page_idx in prefetch_pages:
            if page_idx in visible_pages:
                continue
            quality = page_quality.get(page_idx)
            if quality is None:
                candidates.append((page_idx, "low"))

        if not candidates:
            self._render_batch_pending_by_session[session_id] = False
            return

        rendered = 0
        for page_idx, quality in candidates:
            if self._render_page_into_scene(session_id, page_idx, quality):
                rendered += 1
            if rendered >= VISIBLE_RENDER_BATCH_SIZE:
                break

        if rendered > 0:
            QTimer.singleShot(0, lambda sid=session_id, g=gen: self._process_visible_render_batch(sid, g))
            return
        self._render_batch_pending_by_session[session_id] = False

    def _schedule_deferred_sidebar_scans(self, session_id: str) -> None:
        if not session_id:
            return
        revision = self._render_revision(session_id)
        QTimer.singleShot(
            0,
            lambda sid=session_id, rev=revision: self._run_deferred_sidebar_scans(sid, rev),
        )

    def _run_deferred_sidebar_scans(self, session_id: str, revision: int) -> None:
        if (
            self.model.get_active_session_id() != session_id
            or self._render_revision(session_id) != revision
        ):
            return
        self.load_annotations()
        self.load_watermarks()

    def _invalidate_active_render_state(self, clear_page_sizes: bool = False) -> None:
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._bump_render_revision(session_id)
        if clear_page_sizes:
            self._page_sizes_by_session.pop(session_id, None)

    def enter_fullscreen(self) -> None:
        self.activate()
        if self._fullscreen_is_blocked():
            return
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._fullscreen_session_snapshots.clear()
        self._capture_fullscreen_snapshot(session_id)
        # Enter fullscreen from any mode, but normalize interactions to a clean browse state.
        self.view.cancel_interaction_for_fullscreen()
        self.view._clear_text_selection()
        self.view.clear_search_ui_state()
        self._get_ui_state(session_id).search_state = self._empty_search_state()
        self.view.set_mode("browse")
        self.view.enter_fullscreen_ui()
        self._apply_fullscreen_fit_for_active_session()

    def exit_fullscreen(self) -> None:
        if not self.view.is_fullscreen_active():
            return
        # Restore all visited tabs to their pre-fullscreen layout, keep current tab active.
        active_session_id = self.model.get_active_session_id()
        snapshots = dict(self._fullscreen_session_snapshots)
        self.view.exit_fullscreen_ui()
        for sid, snapshot in snapshots.items():
            self._restore_fullscreen_session_state(sid, snapshot)
        if active_session_id and active_session_id in snapshots:
            snapshot = snapshots[active_session_id]
            self._render_active_session(initial_page_idx=snapshot.current_page)
            QTimer.singleShot(0, lambda snap=snapshot: self._restore_active_fullscreen_anchor(snap))
            QTimer.singleShot(180, lambda snap=snapshot: self._restore_active_fullscreen_anchor(snap))
        self._fullscreen_session_snapshots.clear()

    def toggle_fullscreen(self) -> None:
        if self.view.is_fullscreen_active():
            self.exit_fullscreen()
            return
        self.enter_fullscreen()

    def handle_fullscreen_view_resized(self) -> None:
        if self.view.is_fullscreen_active() and self.model.doc:
            self._apply_fullscreen_fit_for_active_session()

    def _on_viewport_changed(self) -> None:
        session_id = self.model.get_active_session_id()
        if not session_id or not self.view.continuous_pages:
            return
        self._schedule_visible_render(session_id)

    def _reset_empty_ui(self) -> None:
        self.annotations = []
        self.view.clear_document_tabs()
        self.view.reset_document_view()
        self.view.populate_annotations_list([])
        self.view.populate_watermarks_list([])
        self.view.update_undo_redo_tooltips("復原（無可撤銷操作）", "重做（無可重做操作）")

    def _render_active_session(self, initial_page_idx: int | None = None) -> None:
        sid = self.model.get_active_session_id()
        if not sid or not self.model.doc:
            self._reset_empty_ui()
            return
        self.view.ensure_heavy_panels_initialized()

        state = self._get_ui_state(sid)
        if initial_page_idx is None:
            initial_page_idx = state.current_page
        initial_page_idx = max(0, min(initial_page_idx, len(self.model.doc) - 1))
        self._desired_scroll_page[sid] = initial_page_idx
        self._open_priority_page_by_session[sid] = initial_page_idx
        self._background_loading_started_by_session[sid] = False
        self._render_batch_pending_by_session[sid] = False

        self.view.scale = state.scale
        self.view.total_pages = len(self.model.doc)
        self._page_render_quality_by_session[sid] = {}
        self._session_page_sizes(sid)
        self.view.initialize_continuous_placeholders(self._page_sizes_by_session[sid], state.scale, initial_page_idx)
        self.view.set_thumbnail_placeholders(len(self.model.doc))
        self.view.apply_search_ui_state(state.search_state)
        self._apply_session_mode(self._global_mode)
        self._update_undo_redo_tooltips()

        gen = self._next_load_gen(sid)
        self._schedule_visible_render(sid, immediate_page_idx=initial_page_idx)
        QTimer.singleShot(
            OPEN_BACKGROUND_FALLBACK_MS,
            lambda sid=sid, load_gen=gen: self._start_open_background_loading_if_current(sid, load_gen),
        )
        self._schedule_restore_viewport_anchor(sid, gen, state.viewport_anchor)

    def _switch_to_session_id(self, session_id: str) -> None:
        active = self.model.get_active_session_id()
        if active == session_id:
            self._refresh_document_tabs()
            return
        self._capture_current_ui_state()
        if self.view.text_editor:
            self.view._finalize_text_edit()
        self.model.activate_session(session_id)
        self._refresh_document_tabs()
        state = self._get_ui_state(session_id)
        self._render_active_session(initial_page_idx=state.current_page)

    def open_pdf(self, path: str):
        self.activate()
        existing_sid = self.model.find_session_by_path(path)
        if existing_sid:
            self._switch_to_session_id(existing_sid)
            return

        self._capture_current_ui_state()
        password = None
        while True:
            try:
                sid = self.model.open_pdf(path, password=password, append=True)
                self._session_ui_state.setdefault(sid, SessionUIState())
                self._refresh_document_tabs()
                self._render_active_session(initial_page_idx=0)
                break
            except RuntimeError as e:
                err_msg = str(e)
                # 加密 PDF 需要密碼：彈出密碼框後重試
                if "需要密碼" in err_msg or "encrypted" in err_msg.lower():
                    pw = self.view.ask_pdf_password(path)
                    if pw is None:
                        if not self.model.get_active_session_id():
                            self._reset_empty_ui()
                        break
                    password = pw
                    continue
                # 密碼驗證失敗：提示後再次詢問密碼
                if "密碼驗證失敗" in err_msg:
                    show_error(self.view, "密碼錯誤，請重試。")
                    pw = self.view.ask_pdf_password(path)
                    if pw is None:
                        break
                    password = pw
                    continue
                # 其他 RuntimeError
                logger.error(f"打開 PDF 失敗: {e}")
                show_error(self.view, f"打開 PDF 失敗: {e}")
                break
            except Exception as e:
                logger.error(f"打開 PDF 失敗: {e}")
                show_error(self.view, f"打開 PDF 失敗: {e}")
                break

    def handle_forwarded_cli(self, files: list[str]) -> None:
        forwarded_files = [str(path) for path in files if str(path).strip()]

        def _apply() -> None:
            self.activate()
            if self.view.isMinimized():
                self.view.showNormal()
            self.view.raise_()
            self.view.activateWindow()
            for path in forwarded_files:
                self.open_pdf(path)

        QTimer.singleShot(0, _apply)

    def start_merge_pdfs(self) -> None:
        active_sid = self.model.get_active_session_id()
        if not active_sid:
            show_error(self.view, "沒有開啟的PDF文件")
            return

        meta = self.model.get_session_meta(active_sid)
        if not meta:
            show_error(self.view, "沒有可合併的目前文件")
            return

        from model.merge_session import MergeSessionModel
        from view.pdf_view import MergePdfDialog

        session_model = MergeSessionModel(
            current_label=meta["display_name"],
            current_source_id=active_sid,
        )
        dialog = MergePdfDialog(session_model, self.view, file_resolver=self._resolve_merge_file)
        if dialog.exec() != QDialog.Accepted:
            return

        ordered_sources: list[dict] = []
        for entry in dialog.ordered_entries():
            if getattr(entry, "source_kind", "") == "current":
                ordered_sources.append({"source_kind": "current"})
                continue
            resolved = self._resolve_merge_file(
                {
                    "source_kind": "file",
                    "path": getattr(entry, "path", None),
                    "password": getattr(entry, "password", None),
                }
            )
            if resolved is not None:
                ordered_sources.append(resolved)

        if not ordered_sources:
            show_error(self.view, "沒有可合併的有效 PDF")
            return

        if dialog.selected_mode() == "merge_current":
            self.merge_ordered_sources_into_current(ordered_sources)
            return

        path, _ = QFileDialog.getSaveFileName(self.view, "儲存合併後的 PDF", "merged.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.save_ordered_sources_as_new(ordered_sources, path)

    def merge_ordered_sources_into_current(self, ordered_sources: list[dict]) -> None:
        if not self.model.doc:
            raise ValueError("沒有開啟的PDF文件")

        before = self.model._capture_doc_snapshot()
        merged_doc = self.model.compose_merged_document(ordered_sources)
        try:
            stream = io.BytesIO()
            merged_doc.save(stream, garbage=0)
            after = stream.getvalue()
        finally:
            merged_doc.close()

        self.model.replace_active_document_from_snapshot(after, [1])
        cmd = SnapshotCommand(
            model=self.model,
            command_type="merge_pdfs",
            affected_pages=[1],
            before_bytes=before,
            after_bytes=after,
            description="合併 PDF",
        )
        self.model.command_manager.record(cmd)
        self._update_thumbnails()
        self._rebuild_continuous_scene(0)
        self._schedule_stale_index_drain()
        self._update_undo_redo_tooltips()

    def save_ordered_sources_as_new(self, ordered_sources: list[dict], output_path: str) -> None:
        merged_doc = self.model.compose_merged_document(ordered_sources)
        try:
            merged_doc.save(output_path, garbage=0)
        finally:
            merged_doc.close()
        self.open_pdf(output_path)

    def _resolve_merge_file(self, entry: dict) -> dict | None:
        path = (entry or {}).get("path")
        if not path:
            return None

        password = entry.get("password")
        while True:
            try:
                resolved = self.model.open_merge_source(path, password=password)
                resolved["source_kind"] = "file"
                return resolved
            except RuntimeError as e:
                err_msg = str(e)
                if "需要密碼" in err_msg or "encrypted" in err_msg.lower():
                    pw = self.view.ask_pdf_password(path)
                    if pw is None:
                        return None
                    password = pw
                    continue
                if "密碼驗證失敗" in err_msg:
                    show_error(self.view, "密碼錯誤，請重試。")
                    pw = self.view.ask_pdf_password(path)
                    if pw is None:
                        return None
                    password = pw
                    continue
                show_error(self.view, f"無法讀取來源檔案: {e}")
                return None
            except Exception as e:
                show_error(self.view, f"無法讀取來源檔案: {e}")
                return None

    def start_optimize_pdf_copy(self) -> None:
        # UI flow:
        # file-tab action -> dialog -> save path -> background optimize worker -> open new tab
        active_sid = self.model.get_active_session_id()
        if not active_sid or not self.model.doc:
            show_error(self.view, "沒有可最佳化的 PDF")
            return
        if self._has_active_optimize_submission():
            self._show_optimize_progress_dialog("正在最佳化 PDF 副本...")
            return

        meta = self.model.get_session_meta(active_sid) or {}
        source_path = meta.get("path") or "optimized.pdf"
        source_stem = Path(source_path).stem or "optimized"
        suggested_name = f"{source_stem}.optimized.pdf"

        dialog = OptimizePdfDialog(self.view, audit_provider=self.model.build_pdf_audit_report)
        if dialog.exec() != QDialog.Accepted:
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self.view,
            "另存為最佳化的副本",
            suggested_name,
            "PDF (*.pdf)",
        )
        if not output_path:
            return
        if not Path(output_path).suffix:
            output_path = f"{output_path}.pdf"
        if meta.get("path"):
            current_canonical = self.model._canonicalize_path(meta["path"])
            if self.model._canonicalize_path(output_path) == current_canonical:
                show_error(self.view, "最佳化副本必須使用新的輸出路徑，且不能覆蓋已開啟的檔案。")
                return

        self._start_optimize_submission(output_path, dialog.get_options())

    def _has_active_optimize_submission(self) -> bool:
        return self._optimize_thread is not None

    def _show_optimize_progress_dialog(self, label_text: str) -> None:
        if self._optimize_progress_dialog is None:
            progress = QProgressDialog(label_text, "", 0, 0, self.view)
            progress.setWindowTitle("最佳化 PDF")
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            self._optimize_progress_dialog = progress
        else:
            self._optimize_progress_dialog.setLabelText(label_text)
        self._optimize_progress_dialog.show()
        self._optimize_progress_dialog.raise_()

    def _hide_optimize_progress_dialog(self) -> None:
        if self._optimize_progress_dialog is None:
            return
        self._optimize_progress_dialog.close()
        self._optimize_progress_dialog.deleteLater()
        self._optimize_progress_dialog = None

    def _set_optimize_ui_busy(self, busy: bool) -> None:
        action = getattr(self.view, "_action_optimize_copy", None)
        if action is not None:
            action.setEnabled(not busy)

    def _start_optimize_submission(self, output_path: str, options: object) -> None:
        bridge = self._optimize_worker_bridge
        if bridge is None:
            raise RuntimeError("Optimize worker bridge is not initialized")
        # Background scene/index batches for the active tab can dominate large-PDF optimize latency.
        # The worker calls `PDFModel.save_optimized_copy(...)` (facade); optimizer internals live in `model/pdf_optimizer.py`.
        self._optimize_paused_session_id = self.model.get_active_session_id()
        self._pause_session_background_loading(self._optimize_paused_session_id)
        request = OptimizePdfCopyRequest(output_path=output_path, options=options)
        thread = QThread(self.view)
        worker = _OptimizePdfCopyWorker(self.model, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(bridge.forward_succeeded)
        worker.failed.connect(bridge.forward_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(bridge.notify_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._optimize_thread = thread
        self._optimize_worker = worker
        self._set_optimize_ui_busy(True)
        self._show_optimize_progress_dialog("正在最佳化 PDF 副本...")
        thread.start()

    @staticmethod
    def _format_size_units(size_bytes: int) -> str:
        units = ["bytes", "KB", "MB", "GB", "TB"]
        value = float(max(0, int(size_bytes)))
        unit_index = 0
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(size_bytes):,} bytes"
        return f"{value:.2f} {units[unit_index]} ({int(size_bytes):,} bytes)"

    def _on_optimize_copy_succeeded(self, result) -> None:
        self._hide_optimize_progress_dialog()
        self.open_pdf(result.output_path)
        original_size = self._format_size_units(result.original_bytes)
        optimized_size = self._format_size_units(result.optimized_bytes)
        saved_size = self._format_size_units(result.bytes_saved)
        QMessageBox.information(
            self.view,
            "最佳化完成",
            (
                f"已建立最佳化副本:\n{result.output_path}\n\n"
                f"原始大小: {original_size}\n"
                f"最佳大小: {optimized_size}\n"
                f"節省: {saved_size} ({result.percent_saved:.1f}%)"
            ),
        )

    def _on_optimize_copy_failed(self, exc) -> None:
        self._hide_optimize_progress_dialog()
        logger.error(f"最佳化 PDF 失敗: {exc}")
        show_error(self.view, f"最佳化 PDF 失敗: {exc}")

    def _on_optimize_thread_finished(self) -> None:
        self._optimize_thread = None
        self._optimize_worker = None
        self._optimize_paused_session_id = None
        self._set_optimize_ui_busy(False)

    def on_tab_changed(self, index: int):
        sid = self.model.get_session_id_by_index(index)
        if not sid:
            return
        self._switch_to_session_id(sid)
        if self.view.is_fullscreen_active():
            self._capture_fullscreen_snapshot(sid, use_current_view=False)
            self._apply_fullscreen_fit_for_active_session()

    def _save_session_with_dialog(self, session_id: str) -> bool:
        meta = self.model.get_session_meta(session_id) or {}
        default_path = meta.get("saved_path") or meta.get("path") or "未命名.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self.view,
            "儲存PDF",
            str(default_path),
            "PDF (*.pdf)",
        )
        if not path:
            return False
        try:
            self.model.save_session_as(session_id, path)
            return True
        except Exception as e:
            logger.error(f"儲存 session 失敗: {e}")
            show_error(self.view, f"儲存失敗: {e}")
            return False

    def _attach_yes_no_shortcuts(self, msg_box: QMessageBox, yes_btn, no_btn) -> None:
        """讓確認對話框支援 Y/N 快捷鍵。"""
        shortcut_yes = QShortcut(QKeySequence("Y"), msg_box)
        shortcut_no = QShortcut(QKeySequence("N"), msg_box)
        shortcut_yes.setAutoRepeat(False)
        shortcut_no.setAutoRepeat(False)
        shortcut_yes.activated.connect(lambda: yes_btn.click() if yes_btn.isEnabled() else None)
        shortcut_no.activated.connect(lambda: no_btn.click() if no_btn.isEnabled() else None)
        # 保留引用，避免被 GC 回收後失效。
        msg_box._shortcut_yes = shortcut_yes
        msg_box._shortcut_no = shortcut_no

    def _confirm_close_session(self, session_id: str) -> bool:
        if not self.model.session_has_unsaved_changes(session_id):
            return True
        meta = self.model.get_session_meta(session_id) or {}
        name = meta.get("display_name") or "未命名"
        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("未儲存的變更")
        msg_box.setText(f"分頁「{name}」有未儲存的變更，是否要儲存？")
        msg_box.setInformativeText("取消將保留分頁不關閉。快捷鍵：Y=儲存，N=放棄，Esc=取消。")
        save_btn = msg_box.addButton("儲存後關閉", QMessageBox.AcceptRole)
        discard_btn = msg_box.addButton("放棄變更", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
        self._attach_yes_no_shortcuts(msg_box, save_btn, discard_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == cancel_btn:
            return False
        if clicked == save_btn:
            return self._save_session_with_dialog(session_id)
        return True

    def on_tab_close_requested(self, index: int):
        sid = self.model.get_session_id_by_index(index)
        if not sid:
            return
        if sid == self.model.get_active_session_id() and self.view.text_editor:
            self.view._finalize_text_edit()
        if not self._confirm_close_session(sid):
            return
        if sid == self.model.get_active_session_id():
            self._capture_current_ui_state()
        self.model.close_session(sid)
        self._session_ui_state.pop(sid, None)
        self._fullscreen_session_snapshots.pop(sid, None)
        self._load_gen_by_session.pop(sid, None)
        self._desired_scroll_page.pop(sid, None)
        self._open_priority_page_by_session.pop(sid, None)
        self._background_loading_started_by_session.pop(sid, None)
        self._render_batch_pending_by_session.pop(sid, None)
        self._refresh_document_tabs()
        active_sid = self.model.get_active_session_id()
        if active_sid:
            state = self._get_ui_state(active_sid)
            self._render_active_session(initial_page_idx=state.current_page)
        else:
            self._reset_empty_ui()

    def save_as(self, path: str):
        try:
            self.model.save_as(path)
            self._refresh_document_tabs()
            self._update_undo_redo_tooltips()
        except Exception as e:
            logger.error(f"另存失敗: {e}")
            show_error(self.view, f"另存失敗: {e}")

    def save(self):
        """存回原檔（Ctrl+S）。若有原檔或上次儲存路徑則直接儲存（適用時使用增量更新）；否則改開另存對話框。"""
        path = self.model.saved_path or self.model.original_path
        if not path:
            # 無路徑時改為另存，讓使用者選路徑
            self.view._save_as()
            return
        try:
            self.model.save_as(path)
            self._refresh_document_tabs()
            self._update_undo_redo_tooltips()
            QMessageBox.information(self.view, "儲存完成", f"已儲存至：{path}")
        except Exception as e:
            logger.error(f"儲存失敗: {e}")
            show_error(self.view, f"儲存失敗: {e}")

    def _render_print_preview_image(self, page_index: int, dpi: int) -> QImage:
        scale = max(1.0, float(dpi) / 72.0)
        pix = self.model.get_page_snapshot(page_index + 1, scale=scale)
        fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
        return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()

    def _has_active_print_submission(self) -> bool:
        return self._print_thread is not None or self._print_runner is not None

    def _show_print_progress_dialog(self, label_text: str) -> None:
        if self._print_progress_dialog is None:
            progress = QProgressDialog(label_text, "", 0, 0, self.view)
            progress.setWindowTitle("列印")
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            if hasattr(progress, "canceled"):
                progress.canceled.connect(self._terminate_active_print_submission)
            self._print_progress_dialog = progress
        else:
            self._print_progress_dialog.setLabelText(label_text)
        self._print_progress_dialog.show()
        self._print_progress_dialog.raise_()

    def _update_print_progress_dialog(self, label_text: str) -> None:
        if self._print_progress_dialog is None:
            self._show_print_progress_dialog(label_text)
            return
        self._print_progress_dialog.setLabelText(label_text)

    def _hide_print_progress_dialog(self) -> None:
        if self._print_progress_dialog is None:
            return
        self._print_progress_dialog.close()
        self._print_progress_dialog.deleteLater()
        self._print_progress_dialog = None

    def _set_print_status_message(self, message: str | None) -> None:
        if hasattr(self.view, "set_status_bar_override_message"):
            self.view.set_status_bar_override_message(message)
            return
        if getattr(self.view, "status_bar", None):
            if message:
                self.view.status_bar.showMessage(message)
            else:
                self.view._update_status_bar()

    def _set_print_ui_busy(self, busy: bool) -> None:
        action = getattr(self.view, "_action_print", None)
        if action is not None:
            action.setEnabled(not busy)
        if hasattr(self.view, "set_fullscreen_action_enabled"):
            self.view.set_fullscreen_action_enabled(not busy)
        if busy:
            if self._print_stalled:
                status_message = PRINT_STALLED_MESSAGE
            else:
                status_message = PRINT_CLOSING_MESSAGE if self._print_close_pending else PRINT_STATUS_MESSAGE
            self._set_print_status_message(status_message)
            return
        self._set_print_status_message(None)

    def _update_print_close_pending_ui(self) -> None:
        if not self._has_active_print_submission():
            return
        self._set_print_status_message(PRINT_CLOSING_MESSAGE)
        self._update_print_progress_dialog(PRINT_CLOSING_MESSAGE)

    def _enable_print_terminate_option(self) -> None:
        if self._print_progress_dialog is None:
            return
        if hasattr(self._print_progress_dialog, "setCancelButtonText"):
            self._print_progress_dialog.setCancelButtonText(PRINT_TERMINATE_BUTTON_TEXT)

    def _start_print_submission(self, options) -> None:
        self.activate()
        bridge = self._print_worker_bridge
        if bridge is None:
            raise RuntimeError("Print worker bridge is not initialized")
        work_dir = tempfile.mkdtemp(prefix="pdf_editor_print_")
        request = PrintJobRequest(
            capture_pdf_bytes=self.model.capture_print_input_pdf_bytes,
            watermarks=self.model.get_print_watermarks(),
            options=options.normalized() if hasattr(options, "normalized") else options,
            job_id=str(uuid.uuid4()),
            work_dir=work_dir,
        )
        thread = QThread(self.view)
        worker = _PrintSubmissionWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(bridge.forward_progress)
        worker.prepared.connect(bridge.forward_prepared)
        worker.failed.connect(bridge.forward_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(bridge.notify_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._print_thread = thread
        self._print_worker = worker
        self._print_stalled = False
        thread.start()

    def _create_print_runner(self, job: PrintHelperJob) -> PrintSubprocessRunner:
        work_dir = str(Path(job.input_pdf_path).parent)
        return PrintSubprocessRunner(job, work_dir=work_dir, parent=self.view)

    def _on_print_job_prepared(self, job: PrintHelperJob) -> None:
        self._update_print_progress_dialog(PRINT_SUBMITTING_MESSAGE)
        runner = self._create_print_runner(job)
        runner.progress.connect(self._update_print_progress_dialog)
        runner.stalled.connect(self._on_print_submission_stalled)
        runner.succeeded.connect(self._on_print_submission_succeeded)
        runner.failed.connect(self._on_print_submission_failed)
        runner.finished.connect(self._on_print_runner_finished)
        self._print_runner = runner
        runner.start()

    def _on_print_submission_succeeded(self, result) -> None:
        route = result.route if hasattr(result, "route") else ""
        message = result.message if hasattr(result, "message") else str(result)
        self._finalize_print_submission()
        if self._print_close_pending:
            return
        QMessageBox.information(
            self.view,
            "列印送出",
            f"{message}\n路徑: {route}",
        )

    def _on_print_submission_stalled(self) -> None:
        self._print_stalled = True
        self._set_print_status_message(PRINT_STALLED_MESSAGE)
        self._update_print_progress_dialog(PRINT_STALLED_MESSAGE)
        self._enable_print_terminate_option()

    def _terminate_active_print_submission(self) -> None:
        runner = self._print_runner
        if runner is None:
            return
        self._print_close_pending = False
        self._print_stalled = False
        self._set_print_status_message(PRINT_TERMINATING_MESSAGE)
        self._update_print_progress_dialog(PRINT_TERMINATING_MESSAGE)
        if self._print_runner is not runner:
            return
        runner.terminate()

    def _on_print_submission_failed(self, exc) -> None:
        self._finalize_print_submission()
        if isinstance(exc, PrintHelperTerminatedError):
            logger.warning("列印背景工作已終止: %s", exc)
            return
        if isinstance(exc, PrintingError):
            logger.error(f"列印失敗: {exc}")
            if not self._print_close_pending:
                show_error(self.view, f"列印失敗: {exc}")
            return
        logger.error(f"列印發生非預期錯誤: {exc}")
        if not self._print_close_pending:
            show_error(self.view, f"列印發生非預期錯誤: {exc}")

    def _finalize_print_submission(self) -> None:
        self._hide_print_progress_dialog()

    def _on_print_thread_finished(self) -> None:
        self._print_thread = None
        self._print_worker = None
        self._complete_active_print_submission_if_idle()

    def _on_print_runner_finished(self) -> None:
        self._print_runner = None
        self._complete_active_print_submission_if_idle()

    def _complete_active_print_submission_if_idle(self) -> None:
        if self._has_active_print_submission():
            return
        self._print_stalled = False
        if not self._print_close_pending:
            self._set_print_ui_busy(False)
            return
        self._print_close_pending = False
        self._set_print_ui_busy(False)
        self.view.close()

    def print_document(self):
        """列印當前文件（統一設定視窗 + 右側預覽）。"""
        if not self.model.doc:
            show_error(self.view, "沒有可列印的 PDF 文件")
            return

        self.activate()
        if self._has_active_print_submission():
            self._set_print_status_message(PRINT_STATUS_MESSAGE)
            return

        if self._print_dialog is not None and self._print_dialog.isVisible():
            self._print_dialog.raise_()
            self._print_dialog.activateWindow()
            return

        try:
            if self.print_dispatcher is None:
                raise RuntimeError("Print dispatcher is not initialized")
            printers = self.print_dispatcher.list_printers()
            if not printers:
                show_error(self.view, "找不到可用的印表機")
                return

            self._print_dialog = UnifiedPrintDialog(
                parent=self.view,
                dispatcher=self.print_dispatcher,
                printers=printers,
                pdf_path="",
                total_pages=len(self.model.doc),
                current_page=self.view.current_page + 1,
                job_name=Path(self.model.original_path or "pdf_editor_job").name,
                preview_page_provider=self._render_print_preview_image,
            )

            if self._print_dialog.exec() != QDialog.DialogCode.Accepted:
                return

            dialog_result = self._print_dialog.result_data()
            if dialog_result is None:
                return

            selected_printer = dialog_result.options.printer_name
            if selected_printer:
                status = self.print_dispatcher.get_printer_status(selected_printer)
                if status in {"offline", "stopped"}:
                    show_error(self.view, f"印表機狀態異常：{status}")
                    return

            self._show_print_progress_dialog(PRINT_PREPARING_MESSAGE)
            self._set_print_ui_busy(True)
            self._start_print_submission(dialog_result.options)
        except PrintingError as e:
            logger.error(f"列印失敗: {e}")
            show_error(self.view, f"列印失敗: {e}")
            self._finalize_print_submission()
        except Exception as e:
            logger.error(f"列印發生非預期錯誤: {e}")
            show_error(self.view, f"列印發生非預期錯誤: {e}")
            self._finalize_print_submission()
        finally:
            self._print_dialog = None

    def delete_pages(self, pages: list[int]):
        before = self.model._capture_doc_snapshot()
        # Model is the source of truth: it sanitizes dirty input and returns the actual deleted pages.
        actual_deleted_pages = self.model.delete_pages(pages)
        if not actual_deleted_pages:
            return
        self._invalidate_active_render_state(clear_page_sizes=True)
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="delete_pages",
            # SnapshotCommand metadata must reflect the real effect, not the user's requested intent.
            affected_pages=actual_deleted_pages,
            before_bytes=before,
            after_bytes=after,
            description=f"刪除頁面 {actual_deleted_pages}",
        )
        self.model.command_manager.record(cmd)
        self._update_thumbnails()
        self._rebuild_continuous_scene(min(self.view.current_page, len(self.model.doc) - 1))
        self._schedule_stale_index_drain()
        self._update_undo_redo_tooltips()

    def rotate_pages(self, pages: list[int], degrees: int):
        before = self.model._capture_doc_snapshot()
        # Model sanitizes and returns the actual rotated pages for metadata correctness.
        actual_rotated_pages = self.model.rotate_pages(pages, degrees)
        if not actual_rotated_pages:
            return
        self._invalidate_active_render_state(clear_page_sizes=True)
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="rotate_pages",
            affected_pages=actual_rotated_pages,
            before_bytes=before,
            after_bytes=after,
            description=f"旋轉頁面 {actual_rotated_pages} {degrees}°",
        )
        self.model.command_manager.record(cmd)
        self._update_thumbnails()
        self._rebuild_continuous_scene(self.view.current_page)
        self._update_undo_redo_tooltips()

    def export_pages(self, pages: list[int], path: str, as_image: bool, dpi: int, image_format: str):
        self.model.export_pages(pages, path, as_image=as_image, dpi=dpi, image_format=image_format)

    def add_highlight(self, page: int, rect: fitz.Rect, color: tuple[float, float, float, float]):
        before = self.model._capture_doc_snapshot()
        self.model.tools.annotation.add_highlight(page, rect, color)
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="add_highlight",
            affected_pages=[page],
            before_bytes=before,
            after_bytes=after,
            description=f"新增螢光筆（頁面 {page}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(page - 1)
        self._update_undo_redo_tooltips()

    def get_text_bounds(self, page: int, rough_rect: fitz.Rect) -> fitz.Rect:
        return self.model.tools.annotation.get_text_bounds(page, rough_rect)

    def get_object_info_at_point(self, page: int, point: fitz.Point):
        return self.model.get_object_info_at_point(page, point)

    def add_rect(self, page: int, rect: fitz.Rect, color: tuple[float, float, float, float], fill: bool):
        before = self.model._capture_doc_snapshot()
        self.model.tools.annotation.add_rect(page, rect, color, fill)
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="add_rect",
            affected_pages=[page],
            before_bytes=before,
            after_bytes=after,
            description=f"新增矩形（頁面 {page}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(page - 1)
        self._update_undo_redo_tooltips()

    def move_object(self, request: MoveObjectRequest) -> None:
        if isinstance(request, BatchMoveObjectsRequest):
            before = self.model._capture_doc_snapshot()
            affected_pages: list[int] = []
            changed = False
            for move in request.moves:
                if self.model.move_object(move):
                    changed = True
                    affected_pages.append(int(move.destination_page))
            if not changed:
                return
            self._invalidate_active_render_state()
            after = self.model._capture_doc_snapshot()
            pages = sorted(set(affected_pages))
            cmd = SnapshotCommand(
                model=self.model,
                command_type="move_object_batch",
                affected_pages=pages,
                before_bytes=before,
                after_bytes=after,
                description=f"Move objects (pages {pages})",
            )
            self.model.command_manager.record(cmd)
            self.show_page(pages[-1] - 1)
            self._update_undo_redo_tooltips()
            return
        before = self.model._capture_doc_snapshot()
        if not self.model.move_object(request):
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="move_object",
            affected_pages=[request.destination_page],
            before_bytes=before,
            after_bytes=after,
            description=f"移動物件（頁面 {request.destination_page}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.destination_page - 1)
        self._update_undo_redo_tooltips()

    def rotate_object(self, request: RotateObjectRequest) -> None:
        before = self.model._capture_doc_snapshot()
        if not self.model.rotate_object(request):
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="rotate_object",
            affected_pages=[request.page_num],
            before_bytes=before,
            after_bytes=after,
            description=f"旋轉物件（頁面 {request.page_num}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.page_num - 1)
        self._update_undo_redo_tooltips()

    def delete_object(self, request: DeleteObjectRequest) -> None:
        if isinstance(request, BatchDeleteObjectsRequest):
            before = self.model._capture_doc_snapshot()
            affected_pages: list[int] = []
            changed = False
            for ref in request.objects:
                single = DeleteObjectRequest(
                    object_id=ref.object_id,
                    object_kind=ref.object_kind,
                    page_num=ref.page_num,
                )
                if self.model.delete_object(single):
                    changed = True
                    affected_pages.append(int(ref.page_num))
            if not changed:
                return
            self._invalidate_active_render_state()
            after = self.model._capture_doc_snapshot()
            pages = sorted(set(affected_pages))
            cmd = SnapshotCommand(
                model=self.model,
                command_type="delete_object_batch",
                affected_pages=pages,
                before_bytes=before,
                after_bytes=after,
                description=f"Delete objects (pages {pages})",
            )
            self.model.command_manager.record(cmd)
            self.show_page(pages[-1] - 1)
            self._update_undo_redo_tooltips()
            return
        before = self.model._capture_doc_snapshot()
        if not self.model.delete_object(request):
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="delete_object",
            affected_pages=[request.page_num],
            before_bytes=before,
            after_bytes=after,
            description=f"刪除物件（頁面 {request.page_num}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.page_num - 1)
        self._update_undo_redo_tooltips()

    def resize_object(self, request: ResizeObjectRequest) -> None:
        before = self.model._capture_doc_snapshot()
        if not self.model.resize_object(request):
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="resize_object",
            affected_pages=[request.page_num],
            before_bytes=before,
            after_bytes=after,
            description=f"Resize object (page {request.page_num})",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.page_num - 1)
        self._update_undo_redo_tooltips()

    def add_image_object(self, request: InsertImageObjectRequest) -> None:
        before = self.model._capture_doc_snapshot()
        self.model.add_image_object(
            int(request.page_num),
            fitz.Rect(request.visual_rect),
            bytes(request.image_bytes),
            rotation=int(getattr(request, "rotation", 0) or 0),
        )
        self._invalidate_active_render_state()
        # Drop any stale object selection so lingering resize handles in the scene
        # don't intercept the user's first click on the freshly-inserted image.
        try:
            clear_selection = getattr(self.view, "_clear_object_selection", None)
            if callable(clear_selection):
                clear_selection()
        except Exception:
            pass
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="add_image_object",
            affected_pages=[int(request.page_num)],
            before_bytes=before,
            after_bytes=after,
            description=f"Add image object (page {int(request.page_num)})",
        )
        self.model.command_manager.record(cmd)
        self.show_page(int(request.page_num) - 1)
        self._update_undo_redo_tooltips()

    def _edit_result_to_message(self, result: EditTextResult) -> str | None:
        if result is EditTextResult.TARGET_BLOCK_NOT_FOUND:
            return "找不到可編輯的文字區塊"
        if result is EditTextResult.TARGET_SPAN_NOT_FOUND:
            return "找不到要編輯的文字內容"
        return None

    def _show_edit_result_feedback(self, result: EditTextResult) -> None:
        message = self._edit_result_to_message(result)
        if not message:
            return
        if hasattr(self.view, "_show_toast"):
            self.view._show_toast(message, duration_ms=2500, tone="error")
            return
        show_error(self.view, message)

    def edit_text(
        self,
        page: int | EditTextRequest,
        rect: fitz.Rect | None = None,
        new_text: str | None = None,
        font: str | None = None,
        size: float | None = None,
        color: tuple | None = None,
        original_text: str = None,
        vertical_shift_left: bool = True,
        new_rect=None,
        target_span_id: str = None,
        target_mode: str = None,
    ):
        if isinstance(page, EditTextRequest):
            request = page
        else:
            request = EditTextRequest(
                page=page,
                rect=rect,
                new_text=new_text or "",
                font=font or "helv",
                size=float(size or 12.0),
                color=color or (0.0, 0.0, 0.0),
                original_text=original_text,
                vertical_shift_left=vertical_shift_left,
                new_rect=new_rect,
                target_span_id=target_span_id,
                target_mode=target_mode,
            )
        page = request.page
        rect = request.rect
        new_text = request.new_text
        font = request.font
        size = request.size
        color = request.color
        original_text = request.original_text
        vertical_shift_left = request.vertical_shift_left
        new_rect = request.new_rect
        target_span_id = request.target_span_id
        target_mode = request.target_mode
        # Empty string is a valid "delete textbox content" intent from inline edit.
        if new_text is None:
            new_text = ""
        if not self.model.doc or page < 1 or page > len(self.model.doc): return
        try:
            page_idx = page - 1
            view = getattr(self, "view", None)

            # 擷取 viewport anchor（在任何頁面變動前），供編輯後還原捲軸位置
            anchor = (
                view.capture_viewport_anchor()
                if (view is not None and hasattr(view, "capture_viewport_anchor"))
                else None
            )

            # Phase 4: 透過 CommandManager 執行，支援頁面快照 undo/redo
            snapshot = self.model._capture_page_snapshot(page_idx)

            # Displacement reflow callback（Track B → Track A fallback）
            # 在 model.edit_text() 完成後，只移動後續受影響塊，不重新處理 edited block。
            #
            # Bug fixes:
            # 1. 用 _model 而非 _doc 閉包，redo 時透過 _model.doc 取到目前有效的 doc 物件，
            #    避免 full-GC / save-reopen 後對已關閉的舊 doc 執行 reflow。
            # 2. drag-move 場景：以 new_rect 作為定位 edited block 的 rect（block 已在新位置），
            #    否則用原始 rect 在 move 後找不到 block，displacement 靜默失敗。
            # 3. Track B fallback 條件：plan is None（span not found）也要 fallback，
            #    不能只看 success flag（Track B 找不到 span 時仍回傳 success=True）。
            _model = self.model
            _edit_rect = fitz.Rect(new_rect if new_rect is not None else rect)
            _orig_rect = fitz.Rect(rect)
            _new_text = new_text
            _original_text = original_text or ""
            _font = font
            _size = float(size)
            _color = color
            _page_idx = page_idx
            # mutable container：_reflow_fn 在 cmd.execute() 期間寫入，
            # show_page() 完成後再讀取，確保警告不被 _update_status_bar() 覆蓋
            _reflow_warning: list = [None]

            def _reflow_fn():
                try:
                    _doc = _model.doc   # 每次執行時取當前有效 doc（非閉包時的舊 doc）
                    if _doc is None:
                        return
                    from reflow.track_A_core import TrackAEngine
                    from reflow.track_B_core import TrackBEngine
                    result_b = TrackBEngine().apply_displacement_only(
                        doc=_doc, page_idx=_page_idx,
                        edited_rect=_edit_rect, new_text=_new_text,
                        original_text=_original_text,
                        font=_font, size=_size, color=_color,
                    )
                    # fallback 條件：明確失敗 OR Track B 未找到 span（plan is None）
                    b_ok = result_b.get("success", False) and result_b.get("plan") is not None
                    if not b_ok:
                        result_a = TrackAEngine().apply_displacement_only(
                            doc=_doc, page_idx=_page_idx,
                            edited_rect=_edit_rect, new_text=_new_text,
                            original_text=_original_text,
                            font=_font, size=_size, color=_color,
                        )
                        a_ok = result_a.get("success", False) and result_a.get("plan") is not None
                        if not a_ok:
                            logger.warning(
                                "edit_text reflow: Track A/B 均無法定位段落（displacement 跳過）"
                            )
                            _reflow_warning[0] = "⚠ 段落位移未執行（版面結構未識別），請手動調整"
                except Exception as _e:
                    logger.warning(f"edit_text reflow_fn 失敗（不影響主編輯）: {_e}")
                    _reflow_warning[0] = f"⚠ Reflow 例外（主編輯不受影響）: {_e}"

            cmd = EditTextCommand(
                model=self.model,
                page_num=page,
                rect=rect,
                new_text=new_text,
                font=font,
                size=size,
                color=color,
                original_text=original_text,
                vertical_shift_left=vertical_shift_left,
                page_snapshot_bytes=snapshot,
                old_block_id=target_span_id,
                old_block_text=original_text,
                new_rect=new_rect,
                target_span_id=target_span_id,
                target_mode=target_mode,
                reflow_fn=_reflow_fn,
            )
            self.model.command_manager.execute(cmd)
            if cmd.result is not EditTextResult.SUCCESS:
                self._show_edit_result_feedback(cmd.result)
                self._update_undo_redo_tooltips()
                return
            if hasattr(self, "_invalidate_active_render_state") and hasattr(self.model, "get_active_session_id"):
                self._invalidate_active_render_state()
            self.show_page(page_idx)
            self._update_undo_redo_tooltips()
            # 還原 viewport anchor（避免頁面重繪後捲軸跳位）
            if anchor is not None and view is not None and hasattr(view, "restore_viewport_anchor"):
                QTimer.singleShot(0, lambda a=anchor, v=view: v.restore_viewport_anchor(a))
                QTimer.singleShot(180, lambda a=anchor, v=view: v.restore_viewport_anchor(a))
            # 顯示 reflow 警告：使用 override 機制確保不被 _update_status_bar 覆蓋
            if _reflow_warning[0]:
                _msg = _reflow_warning[0]
                _view_ref = view
                if hasattr(_view_ref, "set_status_bar_override_message"):
                    _view_ref.set_status_bar_override_message(_msg)
                    # 5 秒後自動清除 override
                    QTimer.singleShot(5000, lambda v=_view_ref:
                        v.set_status_bar_override_message(None))
                else:
                    _sb = getattr(_view_ref, "status_bar", None)
                    if _sb is not None:
                        QTimer.singleShot(200, lambda m=_msg, sb=_sb:
                            sb.showMessage(m, 5000))
        except Exception as e:
            logger.error(f"編輯文字失敗: {e}")
            show_error(self.view, f"編輯失敗: {e}")

    def move_text_across_pages(
        self,
        request: MoveTextRequest | int | None = None,
        source_rect: fitz.Rect | None = None,
        destination_page: int | None = None,
        destination_rect: fitz.Rect | None = None,
        new_text: str | None = None,
        font: str | None = None,
        size: float | None = None,
        color: tuple | None = None,
        original_text: str | None = None,
        target_span_id: str | None = None,
        target_mode: str | None = None,
        **legacy_kwargs,
    ) -> None:
        if isinstance(request, MoveTextRequest):
            move_request = request
        else:
            move_request = MoveTextRequest(
                source_page=int(legacy_kwargs.pop("source_page", request or 0)),
                source_rect=legacy_kwargs.pop("source_rect", source_rect),
                destination_page=int(legacy_kwargs.pop("destination_page", destination_page)),
                destination_rect=legacy_kwargs.pop("destination_rect", destination_rect),
                new_text=legacy_kwargs.pop("new_text", new_text) or "",
                font=legacy_kwargs.pop("font", font) or "helv",
                size=float(legacy_kwargs.pop("size", size) or 12.0),
                color=legacy_kwargs.pop("color", color) or (0.0, 0.0, 0.0),
                original_text=legacy_kwargs.pop("original_text", original_text),
                target_span_id=legacy_kwargs.pop("target_span_id", target_span_id),
                target_mode=legacy_kwargs.pop("target_mode", target_mode),
            )

        source_page = move_request.source_page
        source_rect = move_request.source_rect
        destination_page = move_request.destination_page
        destination_rect = move_request.destination_rect
        new_text = move_request.new_text or ""
        font = move_request.font
        size = move_request.size
        color = move_request.color
        original_text = move_request.original_text
        target_span_id = move_request.target_span_id
        target_mode = move_request.target_mode
        if not new_text.strip():
            show_error(self.view, "跨頁移動失敗：文字內容不可為空。")
            return
        if not self.model.doc:
            return
        if source_page == destination_page:
            self.edit_text(
                source_page,
                source_rect,
                new_text,
                font,
                size,
                color,
                original_text=original_text,
                vertical_shift_left=True,
                new_rect=destination_rect,
                target_span_id=target_span_id,
                target_mode=target_mode,
            )
            return

        page_count = len(self.model.doc)
        if (
            source_page < 1
            or destination_page < 1
            or source_page > page_count
            or destination_page > page_count
        ):
            show_error(self.view, "跨頁移動失敗：頁碼超出範圍。")
            return

        try:
            self.model.ensure_page_index_built(source_page)
            self.model.ensure_page_index_built(destination_page)

            resolved_target_span_id = self._resolve_cross_page_move_source_span_id(
                source_page=source_page,
                source_rect=source_rect,
                original_text=original_text,
                target_span_id=target_span_id,
            )
            if not resolved_target_span_id:
                raise RuntimeError("找不到要移動的原始文字。")

            before_snapshot = self.model._capture_doc_snapshot()

            # cross-page move
            #   preflight source
            #     -> fail: no mutation + clear error
            #     -> pass:
            #          capture before
            #          delete source
            #          add destination
            #            -> fail: restore before + refresh UI + error
            #            -> pass: capture after + record one undo entry
            source_edit_result = self.model.edit_text(
                source_page,
                source_rect,
                "",
                font,
                size,
                color,
                original_text=original_text,
                vertical_shift_left=True,
                new_rect=None,
                target_span_id=resolved_target_span_id,
                target_mode=target_mode,
            )
            if source_edit_result is not EditTextResult.SUCCESS:
                raise RuntimeError(self._edit_result_to_message(source_edit_result) or "跨頁移動前無法移除來源文字")

            self.model.ensure_page_index_built(source_page)
            if self.model.block_manager.find_run_by_id(source_page - 1, resolved_target_span_id) is not None:
                raise RuntimeError("原始文字刪除未完成，已取消跨頁移動。")

            self.model.add_textbox(
                destination_page,
                destination_rect,
                new_text,
                font=font,
                size=size,
                color=color,
            )

            after_snapshot = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="move_text_across_pages",
                affected_pages=sorted({source_page, destination_page}),
                before_bytes=before_snapshot,
                after_bytes=after_snapshot,
                description="跨頁移動文字",
            )
            self.model.command_manager.record(cmd)
            self._invalidate_active_render_state()
            self._update_thumbnails()
            self.show_page(destination_page - 1)
            self._update_undo_redo_tooltips()
        except Exception as e:
            before_snapshot = locals().get("before_snapshot")
            if before_snapshot:
                try:
                    self.model.replace_active_document_from_snapshot(
                        before_snapshot,
                        affected_pages=sorted({source_page, destination_page}),
                    )
                    self._invalidate_active_render_state()
                    self._update_thumbnails()
                    self.show_page(source_page - 1)
                    self._update_undo_redo_tooltips()
                except Exception as restore_error:
                    logger.error("move_text_across_pages restore failed: %s", restore_error)
            logger.error("跨頁移動文字失敗: %s", e)
            show_error(self.view, f"跨頁移動文字失敗: {e}")

    def _resolve_cross_page_move_source_span_id(
        self,
        source_page: int,
        source_rect: fitz.Rect,
        original_text: str = None,
        target_span_id: str = None,
    ) -> str | None:
        page_idx = source_page - 1
        if target_span_id:
            source_run = self.model.block_manager.find_run_by_id(page_idx, target_span_id)
            if source_run is not None:
                return target_span_id

        target = self.model.block_manager.find_by_rect(
            page_idx,
            source_rect,
            original_text=original_text,
            doc=self.model.doc,
        )
        if not target:
            return None

        candidate_spans = self.model.block_manager.find_overlapping_runs(
            page_idx,
            target.layout_rect,
            tol=0.5,
        )
        if not candidate_spans:
            return None
        if len(candidate_spans) == 1:
            return candidate_spans[0].span_id

        text_probe = self.model._normalize_text_for_compare(original_text or target.text or "")
        if not text_probe:
            return candidate_spans[-1].span_id

        ranked = sorted(
            candidate_spans,
            key=lambda span: difflib.SequenceMatcher(
                None,
                text_probe,
                self.model._normalize_text_for_compare(span.text),
            ).ratio(),
        )
        return ranked[-1].span_id

    def add_textbox(
        self,
        page: int,
        visual_rect: fitz.Rect,
        text: str,
        font: str,
        size: float,
        color: tuple,
    ) -> None:
        if not text.strip():
            return
        if not self.model.doc or page < 1 or page > len(self.model.doc):
            return
        try:
            page_idx = page - 1
            before_page_snapshot = self.model._capture_page_snapshot_strict(page_idx)
            cmd = AddTextboxCommand(
                model=self.model,
                page_num=page,
                visual_rect=visual_rect,
                text=text,
                font=font,
                size=size,
                color=color,
                before_page_snapshot_bytes=before_page_snapshot,
            )
            self.model.command_manager.execute(cmd)
            self._invalidate_active_render_state()
            self.show_page(page_idx)
            self._update_undo_redo_tooltips()
        except Exception as e:
            logger.error(f"新增文字框失敗: {e}")
            show_error(self.view, f"新增文字框失敗: {e}")

    def set_text_target_mode(self, mode: str):
        self.model.set_text_target_mode(mode)

    def search_text(self, query: str):
        results = self.model.tools.search.search_text(query)
        self.view.display_search_results(results)
        sid = self.model.get_active_session_id()
        if sid:
            state = self._get_ui_state(sid)
            state.search_state = {"query": query, "results": list(results), "index": -1}

    def jump_to_result(self, page_num: int, rect: fitz.Rect):
        scale = self.view.scale
        matrix = fitz.Matrix(scale, scale)
        scaled_rect = rect * matrix
        pix = self.model.get_page_pixmap(page_num, scale)
        qpix = pixmap_to_qpixmap(pix)
        self.view.display_page(page_num - 1, qpix, highlight_rect=scaled_rect)
        sid = self.model.get_active_session_id()
        if sid:
            state = self._get_ui_state(sid)
            state.current_page = max(0, page_num - 1)

    def start_ocr(self, request) -> None:
        """Run Surya OCR for the pages in ``request`` on a background thread."""
        if self._ocr_thread is not None:
            show_error(self.view, "OCR 已在執行中")
            return
        if not self.model.doc:
            show_error(self.view, "沒有開啟的 PDF 文件")
            return

        tool = self.model.tools.ocr
        availability = tool.availability()
        if not availability.available:
            msg = availability.reason or "Surya OCR 未安裝"
            if availability.install_hint:
                msg = f"{msg}\n{availability.install_hint}"
            show_error(self.view, msg)
            return

        page_nums = [idx + 1 for idx in request.page_indices]
        if not page_nums:
            show_error(self.view, "未選擇任何頁面")
            return

        thread = QThread()
        worker = _OcrWorker(
            tool,
            page_nums=page_nums,
            languages=list(request.languages),
            device=request.device,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if self._ocr_worker_bridge is not None:
            worker.progress.connect(self._ocr_worker_bridge.forward_progress)
            worker.page_done.connect(self._ocr_worker_bridge.forward_page_done)
            worker.failed.connect(self._ocr_worker_bridge.forward_failed)
            thread.finished.connect(self._ocr_worker_bridge.notify_thread_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._ocr_thread = thread
        self._ocr_worker = worker
        self._show_ocr_progress_dialog(len(page_nums))
        thread.start()

    def cancel_ocr(self) -> None:
        if self._ocr_worker is not None:
            self._ocr_worker.request_cancel()

    def _show_ocr_progress_dialog(self, total_pages: int) -> None:
        parent = self.view if isinstance(self.view, PDFView) else None
        try:
            dialog = QProgressDialog(
                f"辨識第 0/{total_pages} 頁…",
                "取消",
                0,
                total_pages,
                parent,
            )
        except Exception:
            self._ocr_progress_dialog = None
            return
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(self.cancel_ocr)
        dialog.show()
        self._ocr_progress_dialog = dialog

    @Slot(int, int, int)
    def _on_ocr_progress(self, page_num: int, done: int, total: int) -> None:
        dialog = self._ocr_progress_dialog
        if dialog is None:
            return
        dialog.setMaximum(total)
        dialog.setValue(done)
        dialog.setLabelText(f"辨識第 {done}/{total} 頁… (頁 {page_num})")

    @Slot(int, object)
    def _on_ocr_page_done(self, page_num: int, spans) -> None:
        try:
            self.model.apply_ocr_spans(page_num, list(spans))
        except Exception:
            logger.exception("apply_ocr_spans failed for page %s", page_num)

    @Slot(object)
    def _on_ocr_failed(self, exc) -> None:
        logger.error("OCR failed: %s", exc)
        show_error(self.view, f"OCR 失敗: {exc}")

    @Slot()
    def _on_ocr_thread_finished(self) -> None:
        dialog = self._ocr_progress_dialog
        if dialog is not None:
            dialog.close()
        self._ocr_progress_dialog = None
        self._ocr_thread = None
        self._ocr_worker = None

    def undo(self):
        """
        Phase 6: 統一使用 CommandManager。
        SnapshotCommand（結構性操作）→ 全量重建縮圖與場景。
        EditTextCommand / 非結構性 SnapshotCommand → 僅刷新受影響頁面。
        """
        if not self.model.command_manager.can_undo():
            return
        last_cmd = self.model.command_manager._undo_stack[-1]
        self.model.command_manager.undo()
        self._invalidate_active_render_state(clear_page_sizes=getattr(last_cmd, "is_structural", False))
        self._refresh_after_command(last_cmd)
        self._update_undo_redo_tooltips()

    def redo(self):
        """Phase 6: 統一使用 CommandManager。"""
        if not self.model.command_manager.can_redo():
            return
        next_cmd = self.model.command_manager._redo_stack[-1]
        self.model.command_manager.redo()
        self._invalidate_active_render_state(clear_page_sizes=getattr(next_cmd, "is_structural", False))
        self._refresh_after_command(next_cmd)
        self._update_undo_redo_tooltips()

    def _refresh_after_command(self, cmd) -> None:
        """undo/redo 後，依指令類型決定重新整理範圍。"""
        # 擷取 anchor（undo/redo 前的捲軸位置，避免頁面跳動）
        anchor = self.view.capture_viewport_anchor()

        is_structural = getattr(cmd, 'is_structural', False)
        if is_structural:
            page_idx = min(self.view.current_page, len(self.model.doc) - 1)
            self._update_thumbnails()
            self._rebuild_continuous_scene(page_idx)
            self.load_annotations()
            self._schedule_stale_index_drain()
        else:
            # 精準刷新：找出受影響的頁碼
            if hasattr(cmd, '_page_num'):
                page_idx = cmd._page_num - 1        # EditTextCommand
            elif hasattr(cmd, 'affected_pages') and cmd.affected_pages:
                page_idx = cmd.affected_pages[0] - 1
            else:
                page_idx = self.view.current_page
            page_idx = min(page_idx, len(self.model.doc) - 1)
            self.show_page(page_idx)
            # 非結構性但包含 FreeText 的操作（add_annotation）需更新列表
            if getattr(cmd, '_command_type', '') == 'add_annotation':
                self.load_annotations()

        # 還原 viewport anchor，避免 undo/redo 後捲軸跳位
        QTimer.singleShot(0, lambda a=anchor: self.view.restore_viewport_anchor(a))
        QTimer.singleShot(180, lambda a=anchor: self.view.restore_viewport_anchor(a))

    def change_page(self, page_idx: int):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            logger.warning(f"無效頁碼: {page_idx}")
            return
        self.show_page(page_idx)
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).current_page = page_idx

    def change_scale(self, page_idx: int, scale: float):
        """設定縮放比例：連續模式先重建 placeholder 幾何，再只重繪可見頁。"""
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            return
        self.view.scale = scale
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).scale = scale
        if self.view.continuous_pages:
            self._rebuild_continuous_scene(page_idx)
        else:
            pix = self.model.get_page_pixmap(page_idx + 1, scale)
            qpix = pixmap_to_qpixmap(pix)
            self.view.display_page(page_idx, qpix)
            self.view._update_page_counter()
            self.view._update_status_bar()

    def _update_thumbnails(self):
        thumbs = [pixmap_to_qpixmap(self.model.get_thumbnail(i+1)) for i in range(len(self.model.doc))]
        self.view.update_thumbnails(thumbs)

    def _schedule_thumbnail_batch(self, start: int, session_id: str, gen: int):
        if (
            self.model.get_active_session_id() != session_id
            or self._load_gen_by_session.get(session_id) != gen
            or not self.model.doc
        ):
            return
        n = len(self.model.doc)
        end = min(start + THUMB_BATCH_SIZE, n)
        thumbs = [pixmap_to_qpixmap(self.model.get_thumbnail(i + 1)) for i in range(start, end)]
        self.view.update_thumbnail_batch(start, thumbs)
        if end < n:
            QTimer.singleShot(
                THUMB_BATCH_INTERVAL_MS,
                lambda e=end, sid=session_id, g=gen: self._schedule_thumbnail_batch(e, sid, g),
            )

    def _schedule_index_batch(self, start: int, session_id: str, gen: int):
        if (
            self.model.get_active_session_id() != session_id
            or self._load_gen_by_session.get(session_id) != gen
            or not self.model.doc
        ):
            return
        n = len(self.model.doc)
        end = min(start + INDEX_BATCH_SIZE, n)
        for i in range(start, end):
            self.model.ensure_page_index_built(i + 1)
        if end < n:
            QTimer.singleShot(
                INDEX_BATCH_INTERVAL_MS,
                lambda e=end, sid=session_id, g=gen: self._schedule_index_batch(e, sid, g),
            )

    def _schedule_stale_index_drain(self) -> None:
        """
        Drain stale page indices in small batches.

        This is triggered after structural operations (insert/delete) and after snapshot restore (undo/redo).
        The model marks shifted pages "stale" (cheap), and the controller rebuilds them lazily in the
        background so the UI stays responsive (especially for large PDFs).
        """
        session_id = self.model.get_active_session_id()
        if not session_id or not self.model.doc:
            return
        gen = self._next_stale_index_gen(session_id)
        # Kick cleanup to the next tick so the structural UI refresh wins first.
        QTimer.singleShot(
            0,
            lambda sid=session_id, g=gen: self._drain_stale_index_batch(sid, g),
        )

    def _drain_stale_index_batch(self, session_id: str, gen: int) -> None:
        """
        Rebuild a small slice of stale pages, then reschedule until drained.

        The `gen` token cancels older drains when a new structural operation happens, preventing multiple
        concurrent drain loops from competing for CPU and recreating the "large PDF stalls" problem.
        """
        if (
            self.model.get_active_session_id() != session_id
            or self._stale_index_gen_by_session.get(session_id) != gen
            or not self.model.doc
        ):
            return
        stale_pages = self.model.block_manager.list_stale_pages()
        if not stale_pages:
            return
        # Small batches prevent structural cleanup from recreating the large-PDF stall.
        batch = stale_pages[:INDEX_BATCH_SIZE]
        for page_idx in batch:
            self.model.ensure_page_index_built(page_idx + 1)
        if len(stale_pages) > len(batch):
            QTimer.singleShot(
                INDEX_BATCH_INTERVAL_MS,
                lambda sid=session_id, g=gen: self._drain_stale_index_batch(sid, g),
            )

    def _on_request_rerender(self):
        """觸控板縮放停止後的重渲回呼：重建 placeholder 幾何並刷新可見區。"""
        if not self.model.doc:
            return
        self._rebuild_continuous_scene(self.view.current_page)

    def _rebuild_continuous_scene(self, scroll_to_page_idx: int = 0):
        """重建連續頁面 placeholder 場景並捲動至指定頁。"""
        if not self.model.doc or not self.view.continuous_pages:
            return
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._page_render_quality_by_session[session_id] = {}
        self.view.initialize_continuous_placeholders(
            self._session_page_sizes(session_id),
            self.view.scale,
            min(scroll_to_page_idx, len(self.model.doc) - 1),
        )
        self._schedule_visible_render(
            session_id,
            immediate_page_idx=min(scroll_to_page_idx, len(self.model.doc) - 1),
        )

    def show_page(self, page_idx: int):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            return
        if self.view.continuous_pages and self.view.page_items:
            self.view.scroll_to_page(page_idx, emit_viewport_changed=False)
            sid = self.model.get_active_session_id()
            if sid:
                self._schedule_visible_render(sid, immediate_page_idx=page_idx)
        else:
            pix = self.model.get_page_pixmap(page_idx + 1, self.view.scale)
            qpix = pixmap_to_qpixmap(pix)
            self.view.display_page(page_idx, qpix)
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).current_page = page_idx

    def get_text_info_at_point(
        self,
        page_num: int,
        point: fitz.Point,
        allow_fallback: bool = True,
    ):
        return self.model.get_text_info_at_point(page_num, point, allow_fallback=allow_fallback)

    def get_text_in_rect(self, page_num: int, rect: fitz.Rect) -> str:
        return self.model.get_text_in_rect(page_num, rect)

    def get_text_selection_snapshot_from_run(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
    ) -> tuple[str, fitz.Rect | None]:
        return self.model.get_text_selection_snapshot_from_run(page_num, start_span_id, end_point)

    def _update_undo_redo_tooltips(self) -> None:
        """更新 View 的 undo/redo 按鈕 tooltip，顯示下一步操作描述。"""
        cm = self.model.command_manager
        undo_enabled = cm.can_undo()
        redo_enabled = cm.can_redo()
        if cm.can_undo():
            last = cm._undo_stack[-1]
            undo_tip = f"復原：{last.description}"
        else:
            undo_tip = "復原（無可撤銷操作）"
        if cm.can_redo():
            nxt = cm._redo_stack[-1]
            redo_tip = f"重做：{nxt.description}"
        else:
            redo_tip = "重做（無可重做操作）"
        self.view.update_undo_redo_tooltips(undo_tip, redo_tip)
        if hasattr(self.view, "update_undo_redo_enabled"):
            self.view.update_undo_redo_enabled(undo_enabled, redo_enabled)
        self._refresh_document_tabs()

    def _update_mode(self, mode: str):
        self._global_mode = self._normalize_mode(mode)

    # --- New Annotation Handlers ---

    def load_annotations(self):
        """Load all annotations from the model and update the view's list."""
        try:
            self.annotations = self.model.tools.annotation.get_all_annotations()
        except Exception as e:
            logger.error(f"Failed to load annotations: {e}")
            self.annotations = []
        logger.debug(f"Controller loaded {len(self.annotations)} annotations")
        self.view.populate_annotations_list(self.annotations)

    def add_annotation(self, page_idx: int, doc_point: fitz.Point, text: str):
        """Handle request to add a new annotation. doc_point 已由 view 轉為文件座標。"""
        if not self.model.doc: return

        try:
            before = self.model._capture_doc_snapshot()
            # Model expects 1-based page number
            new_annot_xref = self.model.tools.annotation.add_annotation(page_idx + 1, doc_point, text)
            self._invalidate_active_render_state()
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="add_annotation",
                affected_pages=[page_idx + 1],
                before_bytes=before,
                after_bytes=after,
                description=f"新增註解（頁面 {page_idx + 1}）",
            )
            self.model.command_manager.record(cmd)

            self.show_page(page_idx)
            self.load_annotations()
            self.view._show_annotation_panel()
            self._update_undo_redo_tooltips()

        except Exception as e:
            logger.error(f"新增註解失敗: {e}")
            show_error(self.view, f"新增註解失敗: {e}")

    def jump_to_annotation(self, xref: int):
        """Jump to the page and location of the selected annotation."""
        for annot in self.annotations:
            if annot['xref'] == xref:
                # jump_to_result expects 1-based page number
                page_num_1_based = annot['page_num'] + 1
                self.jump_to_result(page_num_1_based, annot['rect'])
                logger.debug(f"跳轉至註解 xref={xref} 於頁面 {page_num_1_based}")
                return
        logger.warning(f"找不到註解 xref={xref}")

    def toggle_annotations_visibility(self, visible: bool):
        """Show or hide all annotations."""
        if not self.model.doc: return
        self.model.tools.annotation.toggle_annotations_visibility(visible)
        self._invalidate_active_render_state()
        self.show_page(self.view.current_page)
        logger.debug(f"設定註解可見性為 {visible}")

    def snapshot_page(self, page_idx: int):
        """將當前頁面轉換為扁平化影像並複製到剪貼簿"""
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            logger.warning(f"無效頁碼: {page_idx}")
            show_error(self.view, "無效的頁碼")
            return

        try:
            # 獲取包含所有註解的扁平化頁面影像
            # 使用較高的縮放比例以獲得更好的品質
            pix = self.model.get_page_snapshot(page_idx + 1, scale=2.0)

            # 轉換為 QPixmap
            qpix = pixmap_to_qpixmap(pix)

            # 複製到剪貼簿
            clipboard = QApplication.clipboard()
            clipboard.setPixmap(qpix)

            logger.debug(f"頁面 {page_idx + 1} 的快照已複製到剪貼簿，尺寸: {qpix.width()}x{qpix.height()}")
            QMessageBox.information(self.view, "快照成功", f"頁面 {page_idx + 1} 的快照已複製到剪貼簿")

        except Exception as e:
            logger.error(f"快照失敗: {e}")
            show_error(self.view, f"快照失敗: {e}")

    def insert_blank_page(self, position: int):
        """插入空白頁面"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的PDF文件")
            return

        try:
            before = self.model._capture_doc_snapshot()
            # Model clamps/sanitizes position and returns the actual inserted page number.
            actual_inserted_pages = self.model.insert_blank_page(position)
            if not actual_inserted_pages:
                return
            self._invalidate_active_render_state(clear_page_sizes=True)
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="insert_blank_page",
                # Undo metadata must match real state after model-side validation.
                affected_pages=actual_inserted_pages,
                before_bytes=before,
                after_bytes=after,
                description=f"插入空白頁（位置 {actual_inserted_pages[0]}）",
            )
            self.model.command_manager.record(cmd)
            self._update_thumbnails()
            new_page_idx = min(actual_inserted_pages[0] - 1, len(self.model.doc) - 1)
            self._rebuild_continuous_scene(new_page_idx)
            self._schedule_stale_index_drain()
            self._update_undo_redo_tooltips()
            QMessageBox.information(self.view, "插入成功", f"已在位置 {actual_inserted_pages[0]} 插入空白頁面")
        except Exception as e:
            logger.error(f"插入空白頁面失敗: {e}")
            show_error(self.view, f"插入空白頁面失敗: {e}")

    def insert_pages_from_file(self, source_file: str, source_pages: list[int], position: int):
        """從其他檔案插入頁面"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的PDF文件")
            return

        try:
            before = self.model._capture_doc_snapshot()
            # Model validates source pages and returns the actual inserted target positions.
            actual_inserted_pages = self.model.insert_pages_from_file(source_file, source_pages, position)
            if not actual_inserted_pages:
                return
            self._invalidate_active_render_state(clear_page_sizes=True)
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="insert_pages_from_file",
                # SnapshotCommand metadata is derived from the model return (source of truth).
                affected_pages=actual_inserted_pages,
                before_bytes=before,
                after_bytes=after,
                description=f"從 {Path(source_file).name} 插入 {len(actual_inserted_pages)} 頁（位置 {actual_inserted_pages[0]}）",
            )
            self.model.command_manager.record(cmd)
            self._update_thumbnails()
            new_page_idx = min(actual_inserted_pages[0] - 1, len(self.model.doc) - 1)
            self._rebuild_continuous_scene(new_page_idx)
            # Immediate page is ready now; the shifted suffix is drained asynchronously.
            self._schedule_stale_index_drain()
            self._update_undo_redo_tooltips()
            QMessageBox.information(
                self.view,
                "插入成功",
                f"已從 {Path(source_file).name} 插入 {len(actual_inserted_pages)} 個頁面到位置 {actual_inserted_pages[0]}",
            )
        except Exception as e:
            logger.error(f"從檔案插入頁面失敗: {e}")
            show_error(self.view, f"從檔案插入頁面失敗: {e}")

    def add_watermark(self, pages: list, text: str, angle: float, opacity: float, font_size: int, color: tuple, font: str, offset_x: float = 0, offset_y: float = 0, line_spacing: float = 1.3):
        """新增浮水印"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的 PDF 文件")
            return
        try:
            self.model.tools.watermark.add_watermark(pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing)
            self._invalidate_active_render_state()
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self.view._show_watermark_panel()
            self._refresh_document_tabs()
        except Exception as e:
            logger.error(f"新增浮水印失敗: {e}")
            show_error(self.view, f"新增浮水印失敗: {e}")

    def update_watermark(self, wm_id: str, pages: list, text: str, angle: float, opacity: float, font_size: int, color: tuple, font: str, offset_x: float = 0, offset_y: float = 0, line_spacing: float = 1.3):
        """更新浮水印"""
        if not self.model.doc:
            return
        if self.model.tools.watermark.update_watermark(wm_id, text=text, pages=pages, angle=angle, opacity=opacity, font_size=font_size, color=color, font=font, offset_x=offset_x, offset_y=offset_y, line_spacing=line_spacing):
            self._invalidate_active_render_state()
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self._refresh_document_tabs()

    def remove_watermark(self, wm_id: str):
        """移除浮水印"""
        if not self.model.doc:
            return
        if self.model.tools.watermark.remove_watermark(wm_id):
            self._invalidate_active_render_state()
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self._refresh_document_tabs()

    def load_watermarks(self):
        """Load watermark list and update view."""
        try:
            watermarks = self.model.tools.watermark.get_watermarks()
        except Exception as e:
            logger.error(f"Failed to load watermarks: {e}")
            watermarks = []
        self.view.populate_watermarks_list(watermarks)

    def _save_session_for_close(self, session_id: str) -> bool:
        meta = self.model.get_session_meta(session_id) or {}
        save_path = meta.get("saved_path") or meta.get("path")
        if save_path:
            try:
                self.model.save_session_as(session_id, save_path)
                return True
            except Exception as e:
                logger.warning(f"自動儲存失敗，改為另存對話框: {e}")
        return self._save_session_with_dialog(session_id)

    def handle_app_close(self, event) -> None:
        if self._has_active_print_submission():
            self._print_close_pending = True
            self._update_print_close_pending_ui()
            event.ignore()
            return

        dirty_ids = self.model.get_dirty_session_ids()
        if not dirty_ids:
            event.accept()
            return

        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("未儲存的變更")
        msg_box.setText(f"共有 {len(dirty_ids)} 個分頁尚未儲存。")
        msg_box.setInformativeText("是否要儲存所有變更後再關閉？快捷鍵：Y=全部儲存，N=全部放棄，Esc=取消。")
        save_all_btn = msg_box.addButton("全部儲存", QMessageBox.AcceptRole)
        discard_all_btn = msg_box.addButton("全部放棄", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
        self._attach_yes_no_shortcuts(msg_box, save_all_btn, discard_all_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == cancel_btn:
            event.ignore()
            return
        if clicked == discard_all_btn:
            event.accept()
            return

        for sid in dirty_ids:
            if not self._save_session_for_close(sid):
                event.ignore()
                return
        event.accept()

    def save_and_close(self) -> bool:
        """Backward-compatible helper used by legacy flows."""
        sid = self.model.get_active_session_id()
        if not sid:
            return True
        return self._save_session_for_close(sid)
