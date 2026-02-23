from PySide6.QtWidgets import QMessageBox, QApplication, QFileDialog
from model.pdf_model import PDFModel
from model.edit_commands import EditTextCommand, SnapshotCommand
from view.pdf_view import PDFView
from typing import List, Tuple
from utils.helpers import parse_pages, pixmap_to_qpixmap, show_error
from pathlib import Path
import logging
import fitz

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFController:
    def __init__(self, model: PDFModel, view: PDFView):
        self.model = model
        self.view = view
        self.annotations = []
        self._connect_signals()

    def _connect_signals(self):
        # Existing connections
        self.view.sig_open_pdf.connect(self.open_pdf)
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

        # New annotation connections
        self.view.sig_add_annotation.connect(self.add_annotation)
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

    def open_pdf(self, path: str):
        password = None
        while True:
            try:
                self.model.open_pdf(path, password=password)
                self.view.total_pages = len(self.model.doc)
                self._update_thumbnails()
                self._rebuild_continuous_scene(0)
                self.load_annotations()
                self.load_watermarks()
                break
            except RuntimeError as e:
                err_msg = str(e)
                # 加密 PDF 需要密碼：彈出密碼框後重試
                if "需要密碼" in err_msg or "encrypted" in err_msg.lower():
                    pw = self.view.ask_pdf_password(path)
                    if pw is None:
                        show_error(self.view, "已取消開啟 PDF。")
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

    def save_as(self, path: str):
        self.model.save_as(path)

    def save(self):
        """存回原檔（Ctrl+S）。若有原檔或上次儲存路徑則直接儲存（適用時使用增量更新）；否則改開另存對話框。"""
        path = self.model.saved_path or self.model.original_path
        if not path:
            # 無路徑時改為另存，讓使用者選路徑
            self.view._save_as()
            return
        try:
            self.model.save_as(path)
            QMessageBox.information(self.view, "儲存完成", f"已儲存至：{path}")
        except Exception as e:
            logger.error(f"儲存失敗: {e}")
            show_error(self.view, f"儲存失敗: {e}")

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
        self.model.add_highlight(page, rect, color)
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
        return self.model.get_text_bounds(page, rough_rect)

    def add_rect(self, page: int, rect: fitz.Rect, color: Tuple[float, float, float, float], fill: bool):
        before = self.model._capture_doc_snapshot()
        self.model.add_rect(page, rect, color, fill)
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

    def edit_text(self, page: int, rect: fitz.Rect, new_text: str, font: str, size: int, color: tuple, original_text: str = None, vertical_shift_left: bool = True, new_rect=None):
        if not new_text.strip(): return
        if not self.model.doc or page < 1 or page > len(self.model.doc): return
        try:
            page_idx = page - 1

            # Phase 4: 透過 CommandManager 執行，支援頁面快照 undo/redo
            snapshot = self.model._capture_page_snapshot(page_idx)

            # 找目標 block 以填入 old_block_id（僅供 log，不影響執行）
            blocks = self.model.block_manager.get_blocks(page_idx)
            target = next(
                (b for b in blocks
                 if fitz.Rect(b.layout_rect).intersects(rect) or fitz.Rect(b.rect).intersects(rect)),
                None
            )

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
                old_block_id=target.block_id if target else None,
                old_block_text=original_text,
                new_rect=new_rect,
            )
            self.model.command_manager.execute(cmd)
            self.show_page(page_idx)
            self._update_undo_redo_tooltips()
        except Exception as e:
            logger.error(f"編輯文字失敗: {e}")
            show_error(self.view, f"編輯失敗: {e}")
        
    def search_text(self, query: str):
        results = self.model.search_text(query)
        self.view.display_search_results(results)

    def jump_to_result(self, page_num: int, rect: fitz.Rect):
        scale = self.view.scale
        matrix = fitz.Matrix(scale, scale)
        scaled_rect = rect * matrix
        pix = self.model.get_page_pixmap(page_num, scale)
        qpix = pixmap_to_qpixmap(pix)
        self.view.display_page(page_num - 1, qpix, highlight_rect=scaled_rect)

    def ocr_pages(self, pages: List[int]):
        self.model.ocr_pages(pages)

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
        
    def change_scale(self, page_idx: int, scale: float):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc): return
        pix = self.model.get_page_pixmap(page_idx + 1, scale)
        qpix = pixmap_to_qpixmap(pix)
        self.view.display_page(page_idx, qpix)

    def _update_thumbnails(self):
        thumbs = [pixmap_to_qpixmap(self.model.get_thumbnail(i+1)) for i in range(len(self.model.doc))]
        self.view.update_thumbnails(thumbs)

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
            pix = self.model.get_page_pixmap(page_idx + 1, self.view.scale)
            qpix = pixmap_to_qpixmap(pix)
            self.view.update_page_in_scene(page_idx, qpix)
            self.view.scroll_to_page(page_idx)
        else:
            pix = self.model.get_page_pixmap(page_idx + 1, self.view.scale)
            qpix = pixmap_to_qpixmap(pix)
            self.view.display_page(page_idx, qpix)

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

    def _update_mode(self, mode: str):
        pass

    # --- New Annotation Handlers ---

    def load_annotations(self):
        """Load all annotations from the model and update the view's list."""
        self.annotations = self.model.get_all_annotations()
        logger.debug(f"Controller 從 Model 載入 {len(self.annotations)} 個註解: {self.annotations}")
        self.view.populate_annotations_list(self.annotations)
        logger.debug(f"已呼叫 View 更新註解列表")

    def add_annotation(self, page_idx: int, doc_point: fitz.Point, text: str):
        """Handle request to add a new annotation. doc_point 已由 view 轉為文件座標。"""
        if not self.model.doc: return
        
        try:
            before = self.model._capture_doc_snapshot()
            # Model expects 1-based page number
            new_annot_xref = self.model.add_annotation(page_idx + 1, doc_point, text)
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
        self.model.toggle_annotations_visibility(visible)
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
            self.model.add_watermark(pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing)
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self.view._show_watermark_panel()
        except Exception as e:
            logger.error(f"新增浮水印失敗: {e}")
            show_error(self.view, f"新增浮水印失敗: {e}")

    def update_watermark(self, wm_id: str, pages: list, text: str, angle: float, opacity: float, font_size: int, color: tuple, font: str, offset_x: float = 0, offset_y: float = 0, line_spacing: float = 1.3):
        """更新浮水印"""
        if not self.model.doc:
            return
        if self.model.update_watermark(wm_id, text=text, pages=pages, angle=angle, opacity=opacity, font_size=font_size, color=color, font=font, offset_x=offset_x, offset_y=offset_y, line_spacing=line_spacing):
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()

    def remove_watermark(self, wm_id: str):
        """移除浮水印"""
        if not self.model.doc:
            return
        if self.model.remove_watermark(wm_id):
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()

    def load_watermarks(self):
        """載入浮水印列表並更新 View"""
        watermarks = self.model.get_watermarks()
        self.view.populate_watermarks_list(watermarks)

    def save_and_close(self) -> bool:
        """在關閉前儲存檔案
        
        Returns:
            bool: 如果成功儲存則返回True，如果用戶取消則返回False
        """
        if not self.model.doc:
            return True  # 沒有開啟的檔案，允許關閉
        
        # 如果有儲存過的路徑，建議使用該路徑，否則使用原始路徑
        suggested_path = self.model.saved_path if self.model.saved_path else self.model.original_path
        
        # 顯示檔案對話框
        if suggested_path:
            # 使用完整路徑作為預設值，讓用戶可以選擇是否要更改位置
            default_path = str(Path(suggested_path))
        else:
            default_path = "未命名.pdf"
        
        path, _ = QFileDialog.getSaveFileName(
            self.view,
            "儲存PDF",
            default_path,
            "PDF (*.pdf)"
        )
        
        if path:
            try:
                self.save_as(path)
                logger.debug(f"檔案已儲存至: {path}")
                return True  # 成功儲存，允許關閉
            except Exception as e:
                logger.error(f"儲存檔案失敗: {e}")
                show_error(self.view, f"儲存檔案失敗: {e}")
                return False  # 儲存失敗，不允許關閉
        else:
            # 用戶取消了檔案對話框
            return False  # 取消儲存，不允許關閉