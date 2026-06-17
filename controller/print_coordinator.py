"""Print submission coordinator (R3.2 god-module decomposition seam).

Owns the print runtime: the `_PrintSubmissionWorker`/`_PrintWorkerBridge` QObjects, the
`PrintJobRequest` payload, the `PrintDispatcher`, the `PrintSubprocessRunner` lifecycle,
the progress dialog, and the stall/terminate state machine — all previously on
`PDFController`. The controller keeps thin `print_document`/`_has_active_print_submission`
delegates plus the model-coupled `_render_print_preview_image` and the app-lifecycle hooks
(`handle_app_close`/`_fullscreen_is_blocked`), and re-exports
`_PrintSubmissionWorker`/`_PrintWorkerBridge`/`PrintJobRequest`.

Extracted verbatim from `pdf_controller.py` (only controller-owned reads rewritten to
`self._c.<attr>`, and `_has_active_print_submission()` -> `has_active_job()`) so the
behavior — signal wiring, QThread + subprocess lifecycle, the GUI-thread
`capture_worker_snapshot_bytes` handoff (name unchanged; the R5.1 fix is deferred), the
stall/terminate transitions, and progress-dialog ownership — is byte-identical.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QDialog, QMessageBox, QProgressDialog

from src.printing import PrintDispatcher, PrintHelperTerminatedError, PrintingError
from src.printing.helper_protocol import PrintHelperJob
from src.printing.messages import (
    PRINT_CLOSING_MESSAGE,
    PRINT_PREPARING_MESSAGE,
    PRINT_STALLED_MESSAGE,
    PRINT_STATUS_MESSAGE,
    PRINT_SUBMITTING_MESSAGE,
    PRINT_TERMINATE_BUTTON_TEXT,
    PRINT_TERMINATING_MESSAGE,
)
from src.printing.print_dialog import UnifiedPrintDialog
from src.printing.subprocess_runner import PrintSubprocessRunner
from utils.helpers import show_error

if TYPE_CHECKING:
    from controller.pdf_controller import PDFController

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrintJobRequest:
    pdf_bytes: bytes
    watermarks: list[dict]
    options: object
    job_id: str
    work_dir: str


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
            input_pdf_path = Path(self._request.work_dir) / "input.pdf"
            input_pdf_path.write_bytes(self._request.pdf_bytes)
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


class PrintCoordinator:
    """Owns the print runtime for one PDFController.

    The controller holds exactly one of these (`self._print_coordinator`) and delegates
    `print_document` + `_has_active_print_submission` to it. The coordinator reaches back
    through `self._c` for the controller-owned model/view/session helpers and the
    `_render_print_preview_image` preview callback, which stay on PDFController.
    """

    def __init__(self, controller: PDFController) -> None:
        self._c = controller
        self.print_dispatcher: PrintDispatcher | None = None
        self._print_dialog = None
        self._print_progress_dialog: QProgressDialog | None = None
        self._print_thread: QThread | None = None
        self._print_worker: _PrintSubmissionWorker | None = None
        self._print_runner: PrintSubprocessRunner | None = None
        self._print_worker_bridge: _PrintWorkerBridge | None = None
        self._print_close_pending = False
        self._print_stalled = False

    def connect_bridge(self) -> None:
        """Lazy-init the GUI-thread bridge + dispatcher (from PDFController.activate())."""
        if self._print_worker_bridge is None:
            self._print_worker_bridge = _PrintWorkerBridge(self._c.view)
            self._print_worker_bridge.progress.connect(self._update_print_progress_dialog)
            self._print_worker_bridge.prepared.connect(self._on_print_job_prepared)
            self._print_worker_bridge.failed.connect(self._on_print_submission_failed)
            self._print_worker_bridge.thread_finished.connect(self._on_print_thread_finished)
        if self.print_dispatcher is None:
            self.print_dispatcher = PrintDispatcher()

    def has_active_job(self) -> bool:
        return self._print_thread is not None or self._print_runner is not None

    def begin_close_pending(self) -> None:
        """Mark an app-close as pending while a print job is in flight (from handle_app_close)."""
        self._print_close_pending = True
        self._update_print_close_pending_ui()

    def _show_print_progress_dialog(self, label_text: str) -> None:
        if self._print_progress_dialog is None:
            progress = QProgressDialog(label_text, "", 0, 0, self._c.view)
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
        if hasattr(self._c.view, "set_status_bar_override_message"):
            self._c.view.set_status_bar_override_message(message)
            return
        if getattr(self._c.view, "status_bar", None):
            if message:
                self._c.view.status_bar.showMessage(message)
            else:
                self._c.view._update_status_bar()

    def _set_print_ui_busy(self, busy: bool) -> None:
        action = getattr(self._c.view, "_action_print", None)
        if action is not None:
            action.setEnabled(not busy)
        if hasattr(self._c.view, "set_fullscreen_action_enabled"):
            self._c.view.set_fullscreen_action_enabled(not busy)
        if busy:
            if self._print_stalled:
                status_message = PRINT_STALLED_MESSAGE
            else:
                status_message = PRINT_CLOSING_MESSAGE if self._print_close_pending else PRINT_STATUS_MESSAGE
            self._set_print_status_message(status_message)
            return
        self._set_print_status_message(None)

    def _update_print_close_pending_ui(self) -> None:
        if not self.has_active_job():
            return
        self._set_print_status_message(PRINT_CLOSING_MESSAGE)
        self._update_print_progress_dialog(PRINT_CLOSING_MESSAGE)

    def _enable_print_terminate_option(self) -> None:
        if self._print_progress_dialog is None:
            return
        if hasattr(self._print_progress_dialog, "setCancelButtonText"):
            self._print_progress_dialog.setCancelButtonText(PRINT_TERMINATE_BUTTON_TEXT)

    def _start_print_submission(self, options) -> None:
        self._c.activate()
        bridge = self._print_worker_bridge
        if bridge is None:
            raise RuntimeError("Print worker bridge is not initialized")
        session_id = self._c.model.get_active_session_id()
        work_dir = tempfile.mkdtemp(prefix="pdf_editor_print_")
        normalized_options = options.normalized() if hasattr(options, "normalized") else options
        if session_id and hasattr(normalized_options, "extra_options"):
            profile = self._c._resolve_session_profile(session_id, sync_view=True)
            extra = {**(getattr(normalized_options, "extra_options", {}) or {}), "render_colorspace": profile}
            normalized_options = dataclass_replace(normalized_options, extra_options=extra)

        pdf_bytes = self._c.capture_worker_snapshot_bytes()
        request = PrintJobRequest(
            pdf_bytes=pdf_bytes,
            watermarks=self._c.model.get_print_watermarks(),
            options=normalized_options,
            job_id=str(uuid.uuid4()),
            work_dir=work_dir,
        )
        thread = QThread(self._c.view)
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
        return PrintSubprocessRunner(job, work_dir=work_dir, parent=self._c.view)

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
            self._c.view,
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
                show_error(self._c.view, f"列印失敗: {exc}")
            return
        logger.error(f"列印發生非預期錯誤: {exc}")
        if not self._print_close_pending:
            show_error(self._c.view, f"列印發生非預期錯誤: {exc}")

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
        if self.has_active_job():
            return
        self._print_stalled = False
        if not self._print_close_pending:
            self._set_print_ui_busy(False)
            return
        self._print_close_pending = False
        self._set_print_ui_busy(False)
        self._c.view.close()

    def print_document(self):
        """列印當前文件（統一設定視窗 + 右側預覽）。"""
        if not self._c.model.doc:
            show_error(self._c.view, "沒有可列印的 PDF 文件")
            return

        self._c.activate()
        if self.has_active_job():
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
                show_error(self._c.view, "找不到可用的印表機")
                return

            self._print_dialog = UnifiedPrintDialog(
                parent=self._c.view,
                dispatcher=self.print_dispatcher,
                printers=printers,
                pdf_path="",
                total_pages=len(self._c.model.doc),
                current_page=self._c.view.current_page + 1,
                job_name=Path(self._c.model.original_path or "pdf_editor_job").name,
                preview_page_provider=self._c._render_print_preview_image,
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
                    show_error(self._c.view, f"印表機狀態異常：{status}")
                    return

            self._show_print_progress_dialog(PRINT_PREPARING_MESSAGE)
            self._set_print_ui_busy(True)
            self._start_print_submission(dialog_result.options)
        except PrintingError as e:
            logger.error(f"列印失敗: {e}")
            show_error(self._c.view, f"列印失敗: {e}")
            self._finalize_print_submission()
        except Exception as e:
            logger.error(f"列印發生非預期錯誤: {e}")
            show_error(self._c.view, f"列印發生非預期錯誤: {e}")
            self._finalize_print_submission()
        finally:
            self._print_dialog = None
