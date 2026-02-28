from PySide6.QtWidgets import QMessageBox, QApplication, QFileDialog, QDialog
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QTimer
from model.pdf_model import PDFModel
from model.edit_commands import EditTextCommand, SnapshotCommand
from view.pdf_view import PDFView
from typing import List, Tuple, Optional
from utils.helpers import pixmap_to_qpixmap, show_error
from pathlib import Path
from dataclasses import dataclass, field
import logging
import tempfile
import fitz

THUMB_BATCH_SIZE = 10
SCENE_BATCH_SIZE = 3
THUMB_BATCH_INTERVAL_MS = 30
SCENE_BATCH_INTERVAL_MS = 0
INDEX_BATCH_SIZE = 5
INDEX_BATCH_INTERVAL_MS = 50
FIRST_PAGE_PREVIEW_SCALE = 0.25

from src.printing import PrintDispatcher, PrintingError
from src.printing.print_dialog import UnifiedPrintDialog

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class SessionUIState:
    current_page: int = 0
    scale: float = 1.0
    search_state: dict = field(default_factory=lambda: {"query": "", "results": [], "index": -1})
    mode: str = "browse"

class PDFController:
    _VALID_MODES = {"browse", "edit_text", "rect", "highlight", "add_annotation"}
    def __init__(self, model: PDFModel, view: PDFView):
        self.model = model
        self.view = view
        self.annotations = []
        self.print_dispatcher = PrintDispatcher()
        self._print_dialog = None
        self._load_gen_by_session: dict[str, int] = {}
        self._session_ui_state: dict[str, SessionUIState] = {}
        self._desired_scroll_page: dict[str, int] = {}
        self._connect_signals()

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
        self.view.sig_jump_to_result.connect(self.jump_to_result)
        self.view.sig_search.connect(self.search_text)
        self.view.sig_ocr.connect(self.ocr_pages)
        self.view.sig_undo.connect(self.undo)
        self.view.sig_redo.connect(self.redo)
        self.view.sig_mode_changed.connect(self._update_mode)
        self.view.sig_page_changed.connect(self.change_page)
        self.view.sig_scale_changed.connect(self.change_scale)
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

        # Watermark connections
        self.view.sig_add_watermark.connect(self.add_watermark)
        self.view.sig_update_watermark.connect(self.update_watermark)
        self.view.sig_remove_watermark.connect(self.remove_watermark)
        self.view.sig_load_watermarks.connect(self.load_watermarks)

        # Zoom re-render connection
        self.view.sig_request_rerender.connect(self._on_request_rerender)

    def _next_load_gen(self, session_id: str) -> int:
        gen = self._load_gen_by_session.get(session_id, 0) + 1
        self._load_gen_by_session[session_id] = gen
        return gen

    def _capture_current_ui_state(self) -> None:
        sid = self.model.get_active_session_id()
        if not sid:
            return
        self._session_ui_state[sid] = SessionUIState(
            current_page=max(0, self.view.current_page),
            scale=max(0.1, min(float(self.view.scale), 4.0)),
            search_state=self.view.get_search_ui_state(),
            mode=self._normalize_mode(getattr(self.view, "current_mode", "browse")),
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

    def _normalize_mode(self, mode: str) -> str:
        return mode if mode in self._VALID_MODES else "browse"

    def _apply_session_mode(self, mode: str) -> None:
        normalized = self._normalize_mode(mode)
        current = self._normalize_mode(getattr(self.view, "current_mode", "browse"))
        if current != normalized:
            self.view.set_mode(normalized)

    def _reset_empty_ui(self) -> None:
        self.annotations = []
        self.view.clear_document_tabs()
        self._apply_session_mode("browse")
        self.view.reset_document_view()
        self.view.populate_annotations_list([])
        self.view.populate_watermarks_list([])
        self.view.update_undo_redo_tooltips("復原（無可撤銷操作）", "重做（無可重做操作）")

    def _render_active_session(self, initial_page_idx: Optional[int] = None) -> None:
        sid = self.model.get_active_session_id()
        if not sid or not self.model.doc:
            self._reset_empty_ui()
            return

        state = self._get_ui_state(sid)
        if initial_page_idx is None:
            initial_page_idx = state.current_page
        initial_page_idx = max(0, min(initial_page_idx, len(self.model.doc) - 1))
        self._desired_scroll_page[sid] = initial_page_idx

        self.view.scale = state.scale
        self.view.total_pages = len(self.model.doc)
        first_pix = self.model.get_page_pixmap(initial_page_idx + 1, FIRST_PAGE_PREVIEW_SCALE)
        qpix = pixmap_to_qpixmap(first_pix)
        self.view.display_page(initial_page_idx, qpix)
        self.view.set_thumbnail_placeholders(len(self.model.doc))
        self.load_annotations()
        self.load_watermarks()
        self.view.apply_search_ui_state(state.search_state)
        self._apply_session_mode(state.mode)
        self._update_undo_redo_tooltips()

        gen = self._next_load_gen(sid)
        QTimer.singleShot(0, lambda sid=sid, gen=gen: self._schedule_thumbnail_batch(0, sid, gen))
        QTimer.singleShot(0, lambda sid=sid, gen=gen: self._start_continuous_scene_loading(sid, gen))

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

    def on_tab_changed(self, index: int):
        sid = self.model.get_session_id_by_index(index)
        if not sid:
            return
        self._switch_to_session_id(sid)

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

    def _confirm_close_session(self, session_id: str) -> bool:
        if not self.model.session_has_unsaved_changes(session_id):
            return True
        meta = self.model.get_session_meta(session_id) or {}
        name = meta.get("display_name") or "未命名"
        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("未儲存的變更")
        msg_box.setText(f"分頁「{name}」有未儲存的變更，是否要儲存？")
        msg_box.setInformativeText("取消將保留分頁不關閉。")
        save_btn = msg_box.addButton("儲存後關閉", QMessageBox.AcceptRole)
        discard_btn = msg_box.addButton("放棄變更", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
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
        self._load_gen_by_session.pop(sid, None)
        self._desired_scroll_page.pop(sid, None)
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

    def print_document(self):
        """列印當前文件（統一設定視窗 + 右側預覽）。"""
        if not self.model.doc:
            show_error(self.view, "沒有可列印的 PDF 文件")
            return

        if self._print_dialog is not None and self._print_dialog.isVisible():
            self._print_dialog.raise_()
            self._print_dialog.activateWindow()
            return

        temp_path = None
        try:
            printers = self.print_dispatcher.list_printers()
            if not printers:
                show_error(self.view, "找不到可用的印表機")
                return

            snapshot_bytes = self.model.build_print_snapshot()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(snapshot_bytes)
                temp_path = tmp.name

            self._print_dialog = UnifiedPrintDialog(
                parent=self.view,
                dispatcher=self.print_dispatcher,
                printers=printers,
                pdf_path=temp_path,
                total_pages=len(self.model.doc),
                current_page=self.view.current_page + 1,
                job_name=Path(self.model.original_path or "pdf_editor_job").name,
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

            result = self.print_dispatcher.print_pdf_file(temp_path, dialog_result.options)
            QMessageBox.information(
                self.view,
                "列印送出",
                f"{result.message}\n路徑: {result.route}",
            )
        except PrintingError as e:
            logger.error(f"列印失敗: {e}")
            show_error(self.view, f"列印失敗: {e}")
        except Exception as e:
            logger.error(f"列印發生非預期錯誤: {e}")
            show_error(self.view, f"列印發生非預期錯誤: {e}")
        finally:
            self._print_dialog = None
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def delete_pages(self, pages: List[int]):
        before = self.model._capture_doc_snapshot()
        self.model.delete_pages(pages)
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="delete_pages",
            affected_pages=pages,
            before_bytes=before,
            after_bytes=after,
            description=f"刪除頁面 {pages}",
        )
        self.model.command_manager.record(cmd)
        self._update_thumbnails()
        self._rebuild_continuous_scene(min(self.view.current_page, len(self.model.doc) - 1))
        self._update_undo_redo_tooltips()

    def rotate_pages(self, pages: List[int], degrees: int):
        before = self.model._capture_doc_snapshot()
        self.model.rotate_pages(pages, degrees)
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="rotate_pages",
            affected_pages=pages,
            before_bytes=before,
            after_bytes=after,
            description=f"旋轉頁面 {pages} {degrees}°",
        )
        self.model.command_manager.record(cmd)
        self._update_thumbnails()
        self._rebuild_continuous_scene(self.view.current_page)
        self._update_undo_redo_tooltips()

    def export_pages(self, pages: List[int], path: str, as_image: bool):
        self.model.export_pages(pages, path, as_image)

    def add_highlight(self, page: int, rect: fitz.Rect, color: Tuple[float, float, float, float]):
        before = self.model._capture_doc_snapshot()
        self.model.tools.annotation.add_highlight(page, rect, color)
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

    def add_rect(self, page: int, rect: fitz.Rect, color: Tuple[float, float, float, float], fill: bool):
        before = self.model._capture_doc_snapshot()
        self.model.tools.annotation.add_rect(page, rect, color, fill)
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

    def edit_text(
        self,
        page: int,
        rect: fitz.Rect,
        new_text: str,
        font: str,
        size: int,
        color: tuple,
        original_text: str = None,
        vertical_shift_left: bool = True,
        new_rect=None,
        target_span_id: str = None,
        target_mode: str = None,
    ):
        if not new_text.strip(): return
        if not self.model.doc or page < 1 or page > len(self.model.doc): return
        try:
            page_idx = page - 1

            # Phase 4: 透過 CommandManager 執行，支援頁面快照 undo/redo
            snapshot = self.model._capture_page_snapshot(page_idx)

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
            )
            self.model.command_manager.execute(cmd)
            self.show_page(page_idx)
            self._update_undo_redo_tooltips()
        except Exception as e:
            logger.error(f"編輯文字失敗: {e}")
            show_error(self.view, f"編輯失敗: {e}")
        
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

    def ocr_pages(self, pages: List[int]):
        if not self.model.doc:
            show_error(self.view, "No PDF is open.")
            return {}
        try:
            results = self.model.tools.ocr.ocr_pages(pages)
            non_empty = sum(1 for text in results.values() if isinstance(text, str) and text.strip())
            QMessageBox.information(
                self.view,
                "OCR Completed",
                f"OCR finished for {len(results)} page(s); {non_empty} page(s) contain recognized text.",
            )
            return results
        except RuntimeError as e:
            show_error(self.view, str(e))
            return {}
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            show_error(self.view, f"OCR failed: {e}")
            return {}

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
        self._refresh_after_command(last_cmd)
        self._update_undo_redo_tooltips()

    def redo(self):
        """Phase 6: 統一使用 CommandManager。"""
        if not self.model.command_manager.can_redo():
            return
        next_cmd = self.model.command_manager._redo_stack[-1]
        self.model.command_manager.redo()
        self._refresh_after_command(next_cmd)
        self._update_undo_redo_tooltips()

    def _refresh_after_command(self, cmd) -> None:
        """undo/redo 後，依指令類型決定重新整理範圍。"""
        is_structural = getattr(cmd, 'is_structural', False)
        if is_structural:
            page_idx = min(self.view.current_page, len(self.model.doc) - 1)
            self._update_thumbnails()
            self._rebuild_continuous_scene(page_idx)
            self.load_annotations()
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

    def change_page(self, page_idx: int):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            logger.warning(f"無效頁碼: {page_idx}")
            return
        self.show_page(page_idx)
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).current_page = page_idx
        
    def change_scale(self, page_idx: int, scale: float):
        """設定縮放比例：更新 view.scale，連續模式時所有頁面等齊重繪，並同步右上角縮放選單。"""
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

    def _start_continuous_scene_loading(self, session_id: str, gen: int):
        if (
            self.model.get_active_session_id() != session_id
            or self._load_gen_by_session.get(session_id) != gen
            or not self.model.doc
            or not self.view.continuous_pages
        ):
            return
        QTimer.singleShot(0, lambda sid=session_id, g=gen: self._schedule_scene_batch(0, sid, g))

    def _schedule_scene_batch(self, start: int, session_id: str, gen: int):
        if (
            self.model.get_active_session_id() != session_id
            or self._load_gen_by_session.get(session_id) != gen
            or not self.model.doc
            or not self.view.continuous_pages
        ):
            return
        n = len(self.model.doc)
        end = min(start + SCENE_BATCH_SIZE, n)
        pixmaps = [pixmap_to_qpixmap(self.model.get_page_pixmap(i + 1, self.view.scale)) for i in range(start, end)]
        self.view.append_pages_continuous(pixmaps, start)
        target = self._desired_scroll_page.get(session_id, 0)
        if self.view.page_items:
            self.view.scroll_to_page(min(target, len(self.view.page_items) - 1))
        if end < n:
            QTimer.singleShot(
                SCENE_BATCH_INTERVAL_MS,
                lambda e=end, sid=session_id, g=gen: self._schedule_scene_batch(e, sid, g),
            )
        else:
            # 場景載完後才開始分批建立索引，避免開檔時 main thread 被 index 阻塞
            QTimer.singleShot(0, lambda sid=session_id, g=gen: self._schedule_index_batch(0, sid, g))

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

    def _on_request_rerender(self):
        """觸控板縮放停止後的重渲回呼：以 self.view.scale 重新渲染所有頁面，確保清晰顯示。"""
        if not self.model.doc:
            return
        self._rebuild_continuous_scene(self.view.current_page)

    def _rebuild_continuous_scene(self, scroll_to_page_idx: int = 0):
        """重建連續頁面場景並捲動至指定頁。"""
        if not self.model.doc or not self.view.continuous_pages:
            return
        pixmaps = [pixmap_to_qpixmap(self.model.get_page_pixmap(i + 1, self.view.scale)) for i in range(len(self.model.doc))]
        self.view.display_all_pages_continuous(pixmaps)
        self.view.scroll_to_page(min(scroll_to_page_idx, len(self.model.doc) - 1))

    def show_page(self, page_idx: int):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            return
        if self.view.continuous_pages and self.view.page_items:
            n_loaded = len(self.view.page_items)
            if page_idx >= n_loaded:
                self.view.scroll_to_page(n_loaded - 1)
                return
            pix = self.model.get_page_pixmap(page_idx + 1, self.view.scale)
            qpix = pixmap_to_qpixmap(pix)
            self.view.update_page_in_scene(page_idx, qpix)
            self.view.scroll_to_page(page_idx)
        else:
            pix = self.model.get_page_pixmap(page_idx + 1, self.view.scale)
            qpix = pixmap_to_qpixmap(pix)
            self.view.display_page(page_idx, qpix)
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).current_page = page_idx

    def get_text_info_at_point(self, page_num: int, point: fitz.Point):
        return self.model.get_text_info_at_point(page_num, point)

    def _update_undo_redo_tooltips(self) -> None:
        """更新 View 的 undo/redo 按鈕 tooltip，顯示下一步操作描述。"""
        cm = self.model.command_manager
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
        self._refresh_document_tabs()

    def _update_mode(self, mode: str):
        sid = self.model.get_active_session_id()
        if not sid:
            return
        state = self._get_ui_state(sid)
        state.mode = self._normalize_mode(mode)

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
            self.model.insert_blank_page(position)
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="insert_blank_page",
                affected_pages=[position],
                before_bytes=before,
                after_bytes=after,
                description=f"插入空白頁（位置 {position}）",
            )
            self.model.command_manager.record(cmd)
            self._update_thumbnails()
            new_page_idx = min(position - 1, len(self.model.doc) - 1)
            self._rebuild_continuous_scene(new_page_idx)
            self._update_undo_redo_tooltips()
            QMessageBox.information(self.view, "插入成功", f"已在位置 {position} 插入空白頁面")
        except Exception as e:
            logger.error(f"插入空白頁面失敗: {e}")
            show_error(self.view, f"插入空白頁面失敗: {e}")

    def insert_pages_from_file(self, source_file: str, source_pages: List[int], position: int):
        """從其他檔案插入頁面"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的PDF文件")
            return
        
        try:
            before = self.model._capture_doc_snapshot()
            self.model.insert_pages_from_file(source_file, source_pages, position)
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="insert_pages_from_file",
                affected_pages=source_pages,
                before_bytes=before,
                after_bytes=after,
                description=f"從 {Path(source_file).name} 插入 {len(source_pages)} 頁（位置 {position}）",
            )
            self.model.command_manager.record(cmd)
            self._update_thumbnails()
            new_page_idx = min(position - 1, len(self.model.doc) - 1)
            self._rebuild_continuous_scene(new_page_idx)
            self._update_undo_redo_tooltips()
            QMessageBox.information(self.view, "插入成功", f"已從 {Path(source_file).name} 插入 {len(source_pages)} 個頁面到位置 {position}")
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
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self._refresh_document_tabs()

    def remove_watermark(self, wm_id: str):
        """移除浮水印"""
        if not self.model.doc:
            return
        if self.model.tools.watermark.remove_watermark(wm_id):
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
        dirty_ids = self.model.get_dirty_session_ids()
        if not dirty_ids:
            event.accept()
            return

        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("未儲存的變更")
        msg_box.setText(f"共有 {len(dirty_ids)} 個分頁尚未儲存。")
        msg_box.setInformativeText("是否要儲存所有變更後再關閉？")
        save_all_btn = msg_box.addButton("全部儲存", QMessageBox.AcceptRole)
        discard_all_btn = msg_box.addButton("全部放棄", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
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
