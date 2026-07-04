"""Asynchronous OCR coordinator (R3.2 god-module decomposition seam).

Owns the background-OCR runtime: the `_OcrWorker`/`_OcrBridge` QObjects and all of
the OCR thread/worker/bridge/generation/session/progress-dialog state that previously
lived on `PDFController`. The controller keeps thin `start_ocr`/`cancel_ocr` delegates
and re-exports `_OcrWorker`/`_OcrBridge` for backward compatibility.

Extracted verbatim from `pdf_controller.py` (only controller-owned reads rewritten to
`self._c.<attr>`) so the behavior — signal wiring, QThread lifecycle, the `_ocr_gen`
cancellation token, the per-page session guard that keeps recognized text out of the
wrong document on a tab switch, model-mutation sequencing, and progress-dialog
ownership — is byte-identical.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QProgressDialog

from view.message_boxes import show_error
from view.pdf_view import PDFView

if TYPE_CHECKING:
    from controller.pdf_controller import PDFController

logger = logging.getLogger(__name__)


class _OcrWorker(QObject):
    """Runs Surya OCR one page at a time on a background thread.

    Every signal (except ``finished``, which only drives thread teardown)
    carries the OCR generation token so the controller can drop late queued
    emissions from a cancelled run — mirroring ``_SearchWorker``.
    """

    progress = Signal(int, int, int, int)  # gen, page_num, done, total
    status = Signal(int, str)  # gen, message
    page_done = Signal(int, int, object)  # gen, page_num, spans
    failed = Signal(int, object)  # gen, exception
    finished = Signal()

    def __init__(
        self,
        tool,
        page_nums: list[int],
        languages: list[str],
        device: str,
        doc_bytes: bytes | None = None,
        gen: int = 0,
    ) -> None:
        super().__init__()
        self._tool = tool
        self._page_nums = list(page_nums)
        self._languages = list(languages)
        self._device = device
        self._doc_bytes = doc_bytes
        self._gen = gen
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            total = len(self._page_nums)
            # The first page triggers Surya model loading (weights load from disk
            # with no visible CPU/GPU activity). Announce it so the wait does not
            # look like a hang.
            self.status.emit(self._gen, "正在載入文字辨識模型，首次使用可能需要數十秒…")
            for index, page_num in enumerate(self._page_nums, start=1):
                if self._cancel_requested:
                    break
                ocr_kwargs = {"device": self._device}
                if self._doc_bytes is not None:
                    ocr_kwargs["doc"] = self._doc_bytes
                result = self._tool.ocr_pages(
                    [page_num],
                    languages=self._languages,
                    **ocr_kwargs,
                )
                spans = list(result.get(page_num, []))
                self.page_done.emit(self._gen, page_num, spans)
                self.progress.emit(self._gen, page_num, index, total)
        except Exception as exc:
            logger.exception("OCR worker failed")
            self.failed.emit(self._gen, exc)
        finally:
            self.finished.emit()


class _OcrBridge(QObject):
    progress = Signal(int, int, int, int)
    status = Signal(int, str)
    page_done = Signal(int, int, object)
    failed = Signal(int, object)
    thread_finished = Signal()

    @Slot(int, int, int, int)
    def forward_progress(self, gen: int, page_num: int, done: int, total: int) -> None:
        self.progress.emit(gen, page_num, done, total)

    @Slot(int, str)
    def forward_status(self, gen: int, message: str) -> None:
        self.status.emit(gen, message)

    @Slot(int, int, object)
    def forward_page_done(self, gen: int, page_num: int, spans) -> None:
        self.page_done.emit(gen, page_num, spans)

    @Slot(int, object)
    def forward_failed(self, gen: int, exc) -> None:
        self.failed.emit(gen, exc)

    @Slot()
    def notify_thread_finished(self) -> None:
        self.thread_finished.emit()


class OcrCoordinator:
    """Owns the async-OCR runtime for one PDFController.

    The controller holds exactly one of these (`self._ocr_coordinator`) and delegates
    `start_ocr`/`cancel_ocr` to it. The coordinator reaches back through `self._c` for
    the controller-owned model/view, which stay on PDFController.
    """

    def __init__(self, controller: PDFController) -> None:
        self._c = controller
        self._ocr_progress_dialog: QProgressDialog | None = None
        self._ocr_thread: QThread | None = None
        self._ocr_worker: _OcrWorker | None = None
        self._ocr_worker_bridge: _OcrBridge | None = None
        self._ocr_gen = 0
        self._ocr_session_id: str | None = None

    def connect_bridge(self) -> None:
        """Lazy-init the GUI-thread bridge and wire it to the handlers (from activate())."""
        if self._ocr_worker_bridge is None:
            self._ocr_worker_bridge = _OcrBridge(self._c.view)
            self._ocr_worker_bridge.progress.connect(self._on_ocr_progress)
            self._ocr_worker_bridge.status.connect(self._on_ocr_status)
            self._ocr_worker_bridge.page_done.connect(self._on_ocr_page_done)
            self._ocr_worker_bridge.failed.connect(self._on_ocr_failed)
            self._ocr_worker_bridge.thread_finished.connect(self._on_ocr_thread_finished)

    def start_ocr(self, request) -> None:
        """Run Surya OCR for the pages in ``request`` on a background thread."""
        if self._ocr_thread is not None:
            show_error(self._c.view, "OCR 已在執行中")
            return
        if not self._c.model.doc:
            show_error(self._c.view, "沒有開啟的 PDF 文件")
            return

        tool = self._c.model.tools.ocr
        availability = tool.availability()
        if not availability.available:
            msg = availability.reason or "Surya OCR 未安裝"
            if availability.install_hint:
                msg = f"{msg}\n{availability.install_hint}"
            show_error(self._c.view, msg)
            return

        page_nums = [idx + 1 for idx in request.page_indices]
        if not page_nums:
            show_error(self._c.view, "未選擇任何頁面")
            return

        self.cancel_ocr()
        self._ocr_gen += 1
        self._ocr_session_id = self._c.model.get_active_session_id()
        thread = QThread()
        worker = _OcrWorker(
            tool,
            page_nums=page_nums,
            languages=list(request.languages),
            device=request.device,
            doc_bytes=self._c.capture_worker_snapshot_bytes(),
            gen=self._ocr_gen,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if self._ocr_worker_bridge is not None:
            worker.progress.connect(self._ocr_worker_bridge.forward_progress)
            worker.status.connect(self._ocr_worker_bridge.forward_status)
            worker.page_done.connect(self._ocr_worker_bridge.forward_page_done)
            worker.failed.connect(self._ocr_worker_bridge.forward_failed)
            thread.finished.connect(self._ocr_worker_bridge.notify_thread_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._release_ocr_thread(t))

        self._ocr_thread = thread
        self._ocr_worker = worker
        self._show_ocr_progress_dialog(len(page_nums))
        thread.start()

    def cancel_ocr(self) -> None:
        # Bump the gen first so queued cross-thread signals already posted by
        # the worker are dropped by the handlers (they compare against it).
        self._ocr_gen += 1
        if self._ocr_worker is not None:
            self._ocr_worker.request_cancel()

    def _release_ocr_thread(self, thread) -> None:
        if self._ocr_thread is thread:
            self._ocr_thread = None
            self._ocr_worker = None

    def _show_ocr_progress_dialog(self, total_pages: int) -> None:
        parent = self._c.view if isinstance(self._c.view, PDFView) else None
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

    @Slot(int, int, int, int)
    def _on_ocr_progress(self, gen: int, page_num: int, done: int, total: int) -> None:
        if gen != self._ocr_gen:
            return
        dialog = self._ocr_progress_dialog
        if dialog is None:
            return
        dialog.setMaximum(total)
        dialog.setValue(done)
        dialog.setLabelText(f"辨識第 {done}/{total} 頁… (頁 {page_num})")

    @Slot(int, str)
    def _on_ocr_status(self, gen: int, message: str) -> None:
        if gen != self._ocr_gen:
            return
        dialog = self._ocr_progress_dialog
        if dialog is None:
            return
        dialog.setLabelText(message)

    @Slot(int, int, object)
    def _on_ocr_page_done(self, gen: int, page_num: int, spans) -> None:
        if gen != self._ocr_gen:
            logger.warning("Dropping OCR page %s from stale gen %s (current=%s)", page_num, gen, self._ocr_gen)
            return
        active_sid = self._c.model.get_active_session_id()
        if self._ocr_session_id is not None and active_sid != self._ocr_session_id:
            logger.warning("Dropping OCR page %s for stale session %s (active=%s)", page_num, self._ocr_session_id, active_sid)
            return
        try:
            self._c.model.apply_ocr_spans(page_num, list(spans))
            # OCR injects invisible text (render_mode=3): it changes doc.tobytes()
            # (searchable!) but is pixel-identical, so it does NOT bump render_revision.
            # Drop the worker snapshot cache or a later search reads stale pre-OCR bytes.
            self._c._invalidate_worker_snapshot_cache()
        except Exception:
            logger.exception("apply_ocr_spans failed for page %s", page_num)

    @Slot(int, object)
    def _on_ocr_failed(self, gen: int, exc) -> None:
        if gen != self._ocr_gen:
            return
        logger.error("OCR failed: %s", exc)
        show_error(self._c.view, f"OCR 失敗: {exc}")

    @Slot()
    def _on_ocr_thread_finished(self) -> None:
        dialog = self._ocr_progress_dialog
        if dialog is not None:
            dialog.close()
        self._ocr_progress_dialog = None
        self._release_ocr_thread(None)
