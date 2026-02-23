import fitz
import tempfile
import os
import shutil
import logging
import math
import time
from typing import List, Tuple, Optional
import pytesseract
from PIL import Image
from pathlib import Path
import uuid
import difflib  # 相似度比對
import io  # 用於 BytesIO 記憶體 stream（文件推薦 in-memory PDF）
import re
import html as _html_mod

from model.text_block import TextBlock, TextBlockManager, rotation_degrees_from_dir
from model.edit_commands import CommandManager, EditTextCommand

# [優化 1] 模組級正則預編譯：避免每次呼叫 _convert_text_to_html / _normalize_text_for_compare 時重新編譯，提升效能
_RE_HTML_TEXT_PARTS = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff]+|[^\u4e00-\u9fff\u3040-\u30ff\n ]+| +|\n)')
_RE_WS_STRIP = re.compile(r'\s+')
_RE_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff]+')

# Unicode ligature → 分解字元對照表
# PyMuPDF 的 insert_htmlbox 渲染會將字母組合替換為 Unicode 合字（如 fi→ﬁ），
# 導致 get_text() 擷取結果與原始字串比對失敗。此表供 _normalize_text_for_compare 展開用。
_LIGATURE_MAP = {
    '\ufb00': 'ff',   # ﬀ
    '\ufb01': 'fi',   # ﬁ
    '\ufb02': 'fl',   # ﬂ
    '\ufb03': 'ffi',  # ﬃ
    '\ufb04': 'ffl',  # ﬄ
    '\ufb05': 'st',   # ﬅ (long s + t)
    '\ufb06': 'st',   # ﬆ
}

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFModel:
    def __init__(self):
        self.doc: fitz.Document = None
        self.temp_dir = None
        self.original_path: str = None
        self.saved_path: str = None  # 追蹤最後儲存的路徑
        # Phase 1 & 2: 新管理器取代舊 text_block_index dict
        self.block_manager = TextBlockManager()
        self.command_manager = CommandManager()
        # Phase 6: 效能優化 — 公開計數器 + 延遲清理追蹤
        self.edit_count: int = 0
        # pending_edits 記錄每次 edit_text 修改過的頁面資訊，
        # apply_pending_redactions() 儲存前呼叫 page.clean_contents() 壓縮 content stream。
        # 注意：apply_redactions() 本身仍在 Step 2 立即執行（插入前必須先清除舊文字），
        # pending_edits 提供的是儲存時的批次 clean_contents 優化。
        self.pending_edits: list = []          # [{"page_idx": int, "rect": fitz.Rect}]
        # 浮水印列表（僅存於本階段，不寫入 PDF 直到儲存）：[{id, pages, text, angle, opacity, font_size, color, font}, ...]
        self.watermark_list: List[dict] = []
        self._watermark_modified = False
        # 是否在「存回原檔」時使用增量更新（Incremental Update），以減少對數位簽章與大檔的影響
        self.use_incremental_save: bool = True
        self._initialize_temp_dir()
        # 全局 glyph 高度調整（文件推薦，import 後設定一次）
        try:
            fitz.TOOLS.set_small_glyph_heights(True)
            logger.debug("已設定 PyMuPDF TOOLS.set_small_glyph_heights(True)")
        except AttributeError:
            logger.warning("PyMuPDF 版本無 TOOLS 支援，跳過 glyph 調整")

    def _initialize_temp_dir(self):
        """初始化臨時目錄，確保可寫入"""
        try:
            self.temp_dir = tempfile.TemporaryDirectory()
            logger.debug(f"成功創建臨時目錄: {self.temp_dir.name}")
            # 檢查目錄是否可寫入
            test_file = Path(self.temp_dir.name) / "test.txt"
            test_file.touch()
            test_file.unlink()
        except (PermissionError, OSError) as e:
            logger.error(f"無法創建臨時目錄: {str(e)}")
            # 後備：使用當前工作目錄下的自訂臨時目錄
            fallback_dir = Path.cwd() / "pdf_temp"
            try:
                fallback_dir.mkdir(exist_ok=True)
                self.temp_dir = tempfile.TemporaryDirectory(dir=str(fallback_dir))
                logger.debug(f"使用後備臨時目錄: {self.temp_dir.name}")
            except Exception as e:
                raise RuntimeError(f"無法創建後備臨時目錄: {str(e)}")

    def __del__(self):
        self.close()

    def open_pdf(self, path: str, password: Optional[str] = None):
        """
        開啟 PDF 檔案並建立文字塊索引。

        Args:
            path: PDF 檔案路徑
            password: 可選密碼（支援 user password 與 owner/permission password）。
                      PyMuPDF authenticate() 會自動嘗試兩種類型：
                        回傳 2 = user password 認證成功（可讀取內容）
                        回傳 4 = owner password 認證成功（可讀取並修改權限）
                        回傳 6 = 兩者皆成功
        """
        logger.debug(f"嘗試開啟PDF: {path}")
        self.original_path = path
        try:
            # 規範化路徑
            src_path = Path(path).resolve()
            if not src_path.exists():
                logger.error(f"原始檔案不存在: {path}")
                raise FileNotFoundError(f"原始檔案不存在: {path}")
            if not src_path.is_file():
                logger.error(f"路徑不是有效檔案: {path}")
                raise ValueError(f"路徑不是有效檔案: {path}")

            # 為新文件會話清理狀態
            if self.doc:
                self.doc.close()
            self.saved_path = None
            self.block_manager.clear()
            self.command_manager.clear()
            self.watermark_list.clear()
            self._watermark_modified = False
            self.edit_count = 0
            self.pending_edits.clear()

            # 直接從原始路徑開啟（以便存檔時可選用增量更新）
            self.doc = fitz.open(str(src_path))

            # 若 PDF 需要密碼，嘗試認證（支援 user 與 owner password）
            if self.doc.needs_pass:
                if password is None:
                    raise RuntimeError("document closed or encrypted — 需要密碼")
                auth_result = self.doc.authenticate(password)
                if auth_result == 0:
                    raise RuntimeError(
                        f"PDF 密碼驗證失敗（authenticate 回傳 0）: {path}"
                    )
                # auth_result: 2=user, 4=owner, 6=both — 均允許繼續
                logger.debug(
                    f"PDF 密碼驗證成功 (auth_level={auth_result}，"
                    f"2=user/4=owner/6=both): {src_path}"
                )

            logger.debug(f"成功開啟PDF: {src_path}")

            # 建立文字方塊索引（Phase 1: TextBlockManager）
            self.block_manager.build_index(self.doc)
        except PermissionError as e:
            logger.error(f"無權限存取檔案: {str(e)}")
            raise PermissionError(f"無權限存取檔案: {str(e)}")
        except Exception as e:
            logger.error(f"開啟PDF失敗: {str(e)}")
            raise RuntimeError(f"開啟PDF失敗: {str(e)}")

    def _insert_rotate_for_htmlbox(self, rotation: int) -> int:
        """
        insert_htmlbox(rotate=...) 的旋轉方向與 PDF 文字 dir 相反（順時針 vs 逆時針），
        垂直文字若直接傳 90 會變成 180° 反轉。改傳 (360 - rotation) % 360 以對齊原檔方向。
        """
        return (360 - rotation) % 360

    def _vertical_html_rect(self, base_rect: fitz.Rect, text: str, size: float, font_name: str, page_rect: fitz.Rect, anchor_right: bool = True) -> fitz.Rect:
        """
        垂直文字：估算「需要的 x 方向寬度（列數 × 行高）」。
        anchor_right=True（預設）：固定右緣 x1，向左擴展（x0 往左）→ 左側文字需左移。
        anchor_right=False：固定左緣 x0，向右擴展（x1 往右）→ 右側文字需右移。
        不超出頁面邊界。
        """
        line_gap = 1.1
        try:
            font_obj = fitz.Font(font_name)
            line_height = max(1.0, (font_obj.ascender - font_obj.descender) * size * line_gap)
        except Exception:
            line_height = max(1.0, size * line_gap)
        rect_height = max(base_rect.height, line_height)
        chars_per_col = max(1, int(rect_height / line_height))
        logical_cols = 1 + text.count('\n')
        chars_no_nl = len(text.replace('\n', ''))
        wrap_cols = math.ceil(max(1, chars_no_nl) / chars_per_col) if chars_no_nl else 0
        cols = max(logical_cols, wrap_cols)
        needed_width = max(base_rect.width, cols * line_height)
        max_width = max(1.0, page_rect.width * 0.98)
        needed_width = min(needed_width, max_width)

        if anchor_right:
            # 固定 x1，向左擴展
            new_x1 = base_rect.x1
            new_x0 = new_x1 - needed_width
            if new_x0 < page_rect.x0:
                new_x0 = page_rect.x0
                new_x1 = min(new_x0 + needed_width, page_rect.x1)
        else:
            # 固定 x0，向右擴展
            new_x0 = base_rect.x0
            new_x1 = new_x0 + needed_width
            if new_x1 > page_rect.x1:
                new_x1 = page_rect.x1
                new_x0 = max(new_x1 - needed_width, page_rect.x0)
        # 夾緊 y 於頁面內，避免超出頁面
        y0 = max(base_rect.y0, page_rect.y0)
        y1 = min(base_rect.y1, page_rect.y1)
        if y0 >= y1:
            y1 = y0 + max(1.0, base_rect.height)
        return fitz.Rect(new_x0, y0, new_x1, min(y1, page_rect.y1))

    def _clamp_rect_to_page(self, rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形夾在頁面邊界內，確保文字不會超出頁面。"""
        x0 = max(rect.x0, page_rect.x0)
        y0 = max(rect.y0, page_rect.y0)
        x1 = min(rect.x1, page_rect.x1)
        y1 = min(rect.y1, page_rect.y1)
        if x0 >= x1 or y0 >= y1:
            return fitz.Rect(page_rect.x0, page_rect.y0, page_rect.x0 + 1, page_rect.y0 + 1)
        return fitz.Rect(x0, y0, x1, y1)

    def _y_overlaps(self, rect_a: fitz.Rect, rect_b: fitz.Rect) -> bool:
        return not (rect_a.y1 <= rect_b.y0 or rect_b.y1 <= rect_a.y0)

    def _shift_rect_left(self, rect: fitz.Rect, target_right_x0: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形左移，使右緣不超過 target_right_x0 - min_gap。若會移出頁面則不移動。"""
        width = rect.width
        new_x1 = min(rect.x1, target_right_x0 - min_gap)
        shift = rect.x1 - new_x1
        if shift <= 0:
            return rect
        new_x0 = rect.x0 - shift
        new_x1 = new_x0 + width
        if new_x0 < page_rect.x0 or new_x1 > page_rect.x1:
            return rect
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    def _shift_rect_right(self, rect: fitz.Rect, target_left_x1: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形右移，使左緣至少為 target_left_x1 + min_gap。若會移出頁面則不移動。"""
        width = rect.width
        new_x0 = max(rect.x0, target_left_x1 + min_gap)
        if new_x0 <= rect.x0:
            return rect
        new_x1 = new_x0 + width
        if new_x0 < page_rect.x0 or new_x1 > page_rect.x1:
            return rect
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    def _normalize_text_for_compare(self, text: str) -> str:
        """
        將空白移除、轉小寫、展開 Unicode ligature，供文字比對用。
        PyMuPDF 的 insert_htmlbox 渲染時會將 fi→ﬁ (U+FB01) 等字母合字替換，
        導致 get_text() 擷取結果與原始字串不一致；此處統一展開後再比對。
        """
        if not text:
            return ""
        # 展開常見 Unicode ligatures（PyMuPDF 渲染產生的合字）
        result = text
        for lig, expanded in _LIGATURE_MAP.items():
            if lig in result:
                result = result.replace(lig, expanded)
        return _RE_WS_STRIP.sub('', result).lower()

    def _text_fits_in_rect(self, page: fitz.Page, rect: fitz.Rect, expected_text: str) -> bool:
        extracted = page.get_text("text", clip=rect)
        return self._normalize_text_for_compare(expected_text) in self._normalize_text_for_compare(extracted)

    def _binary_shrink_height(self, page: fitz.Page, rect: fitz.Rect, expected_text: str, iterations: int = 7, padding: float = 4.0, min_y1: float | None = None) -> fitz.Rect:
        """
        先用全頁高度 rect 渲染，再二分縮減 y1 找到最小可用高度。
        y0 固定，最後加 padding。
        [優化 11] 早期結束：若範圍已足夠小則提前返回，減少不必要的 get_text 呼叫
        """
        page_rect = page.rect
        low = rect.y1 if min_y1 is None else max(rect.y0, min_y1)
        high = page_rect.y1
        if low > high:
            low = high
        best_y1 = high

        for _ in range(iterations):
            if high - low < 2.0:  # [優化 11] 範圍小於 2pt 時提前結束
                break
            mid = (low + high) / 2.0
            test_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, mid)
            if self._text_fits_in_rect(page, test_rect, expected_text):
                best_y1 = mid
                high = mid
            else:
                low = mid

        best_y1 = min(page_rect.y1, best_y1 + padding)
        return fitz.Rect(rect.x0, rect.y0, rect.x1, best_y1)

    def _calc_vertical_padding(self, size: float) -> float:
        return max(4.0, float(size) * 0.8) # 0.2 還是會被裁切到，我先試 0.8 是可行的，待有需要再測試能否進一步減少

    def close(self):
        logger.debug("關閉PDF並清理臨時目錄")
        if self.doc:
            try:
                self.doc.close()
                logger.debug("PDF檔案已關閉")
            except Exception as e:
                logger.warning(f"關閉PDF失敗: {str(e)}")
            self.doc = None
        self.block_manager.clear()
        self.command_manager.clear()
        self.watermark_list.clear()
        self.pending_edits.clear()
        self.edit_count = 0
        if self.temp_dir:
            self.temp_dir.cleanup()
            logger.debug("臨時目錄已清理")
            self.temp_dir = None

    def delete_pages(self, pages: List[int]):
        for page_num in sorted(pages, reverse=True):
            self.doc.delete_page(page_num - 1)

    def rotate_pages(self, pages: List[int], degrees: int):
        for page_num in pages:
            page = self.doc[page_num - 1]
            page.set_rotation((page.rotation + degrees) % 360)

    def export_pages(self, pages: List[int], output_path: str, as_image: bool = False):
        base_path = Path(output_path).with_suffix('')
        logger.debug(f"原始路徑: {output_path}, 清理後基底路徑: {base_path}")
        if as_image:
            for i, page_num in enumerate(pages):
                if 1 <= page_num <= len(self.doc):
                    pix = self.get_page_pixmap(page_num, scale=1.0)
                    output_path = f"{base_path}.png" if len(pages) == 1 else f"{base_path}_{i}.png"
                    pix.save(output_path)
                    logger.debug(f"匯出影像: 頁面 {page_num} 至 {output_path}")
        else:
            new_doc = fitz.open()
            for page_num in pages:
                if 1 <= page_num <= len(self.doc):
                    new_doc.insert_pdf(self.doc, from_page=page_num-1, to_page=page_num-1)
                    logger.debug(f"匯出PDF頁面: {page_num}")
            new_doc.save(output_path)
            new_doc.close()

    def insert_blank_page(self, position: int):
        """在指定位置插入空白頁面
        
        Args:
            position: 插入位置（1-based），例如 1 表示在第一頁之前，2 表示在第一頁之後
                     如果 position > 總頁數，則插入到最後
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        
        # 獲取當前第一頁的尺寸作為新頁面的尺寸
        if len(self.doc) > 0:
            first_page = self.doc[0]
            page_rect = first_page.rect
            width = page_rect.width
            height = page_rect.height
        else:
            # 如果文件為空，使用標準 A4 尺寸
            width = 595  # A4 width in points
            height = 842  # A4 height in points
        
        # 轉換為 0-based 索引，並確保不超出範圍
        insert_at = min(position - 1, len(self.doc))
        if insert_at < 0:
            insert_at = 0
        
        # 插入空白頁面
        self.doc.new_page(insert_at, width=width, height=height)
        logger.debug(f"在位置 {insert_at + 1} 插入空白頁面，尺寸: {width}x{height}")

    def insert_pages_from_file(self, source_file: str, source_pages: List[int], position: int):
        """從其他PDF檔案插入頁面到當前文件
        
        Args:
            source_file: 來源PDF檔案路徑
            source_pages: 要插入的來源頁碼列表（1-based）
            position: 插入位置（1-based），例如 1 表示在第一頁之前
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {source_file}")
        
        try:
            # 開啟來源PDF
            source_doc = fitz.open(str(source_path))
            
            # 轉換為 0-based 索引
            insert_at = min(position - 1, len(self.doc))
            if insert_at < 0:
                insert_at = 0
            
            # 插入指定的頁面
            for i, page_num in enumerate(sorted(source_pages)):
                if 1 <= page_num <= len(source_doc):
                    # 使用 insert_pdf 方法插入單頁
                    self.doc.insert_pdf(
                        source_doc,
                        from_page=page_num - 1,
                        to_page=page_num - 1,
                        start_at=insert_at + i
                    )
                    logger.debug(f"從 {source_file} 插入頁面 {page_num} 到位置 {insert_at + i + 1}")
                else:
                    logger.warning(f"來源檔案頁碼 {page_num} 超出範圍（總頁數: {len(source_doc)}）")
            
            source_doc.close()

        except Exception as e:
            logger.error(f"從檔案插入頁面失敗: {e}")
            raise RuntimeError(f"從檔案插入頁面失敗: {e}")

    def add_highlight(self, page_num: int, rect: fitz.Rect, color: Tuple[float, float, float, float]):
        page = self.doc[page_num - 1]
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=color[:3], fill=color[:3])
        annot.set_opacity(color[3])
        annot.update()
        logger.debug(f"新增螢光筆: 頁面 {page_num}, 矩形 {rect}, 顏色 {color}")

    def get_text_bounds(self, page_num: int, rough_rect: fitz.Rect) -> fitz.Rect:
        """獲取文字精準邊界"""
        page = self.doc[page_num - 1]
        words = page.get_text("words", clip=rough_rect)
        if not words:
            logger.debug(f"頁面 {page_num} 在 {rough_rect} 無文字，返回原矩形")
            return rough_rect
        x0 = min(word[0] for word in words)
        y0 = min(word[1] for word in words)
        x1 = max(word[2] for word in words)
        y1 = max(word[3] for word in words)
        precise_rect = fitz.Rect(x0, y0, x1, y1)
        logger.debug(f"頁面 {page_num} 在 {rough_rect} 精準矩形 {precise_rect}")
        return precise_rect

    def add_rect(self, page_num: int, rect: fitz.Rect, color: Tuple[float, float, float, float], fill: bool):
        page = self.doc[page_num - 1]
        annot = page.add_rect_annot(rect)
        annot.set_colors(stroke=color[:3], fill=color[:3] if fill else None)
        annot.set_border(width=5 if not fill else 0) # 空心矩形設置邊框寬度
        annot.set_opacity(color[3])
        annot.update()
        logger.debug(f"新增矩形: 頁面 {page_num}, 矩形 {rect}, 顏色 {color}, 填滿={fill}")

    def add_annotation(self, page_num: int, point: fitz.Point, text: str) -> int:
        """在指定頁面和位置新增文字註解"""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError("無效的頁碼")

        page = self.doc[page_num - 1]
        
        # 定義註解的固定寬度和外觀
        fixed_width = 200
        font_size = 10.5
        
        # 初始矩形，高度稍後會被 PyMuPDF 自動調整
        rect = fitz.Rect(point.x, point.y, point.x + fixed_width, point.y + 50)
        
        # 建立 FreeText 註解
        annot = page.add_freetext_annot(
            rect,
            text,
            fontsize=font_size,
            fontname="helv",  # 使用一個常見的無襯線字體
            text_color=(0, 0, 0),  # 黑色
            fill_color=(1, 1, 0.8), # 淡黃色背景
            rotate=page.rotation
        )
        
        # PyMuPDF 會自動根據內容調整 FreeText 註解的高度，我們只需更新即可
        annot.update()
        
        logger.debug(f"新增註解: 頁面 {page_num}, 最終矩形 {annot.rect}, xref: {annot.xref}")
        return annot.xref

    def get_all_annotations(self) -> List[dict]:
        """獲取文件中所有的 FreeText 註解"""
        results = []
        if not self.doc:
            return results
        
        for page in self.doc:
            for annot in page.annots():
                if annot.type[1] == 'FreeText': # 判斷一個註解是否為文字註解
                    info = {
                        "xref": annot.xref,
                        "page_num": page.number,
                        "rect": annot.rect,
                        "text": annot.info.get("content", "")
                    }
                    results.append(info)
        
        logger.debug(f"找到 {len(results)} 個 FreeText 註解")
        return results

    def toggle_annotations_visibility(self, visible: bool):
        """切換所有 FreeText 註解的可見性"""
        if not self.doc:
            return

        for page in self.doc:
            for annot in page.annots():
                if annot.type[1] == 'FreeText': # 判斷一個註解是否為文字註解
                    current_flags = annot.flags
                    if visible:
                        # 移除 Hidden 旗標
                        new_flags = current_flags & ~fitz.ANNOT_FLAG_HIDDEN
                    else:
                        # 新增 Hidden 旗標
                        new_flags = current_flags | fitz.ANNOT_FLAG_HIDDEN
                    
                    annot.set_flags(new_flags)
                    annot.update()
        
        logger.debug(f"註解可見性設定為: {visible}")

    # --- 浮水印相關 ---

    def _needs_cjk_font(self, text: str) -> bool:
        """檢查文字是否包含中日韓字元，需使用 CJK 字型才能正確顯示"""
        return bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))

    def _get_watermark_font(self, font_name: str, text: str) -> str:
        """取得適合浮水印文字的字型（中文等 CJK 需使用 china-ts）"""
        non_cjk_fonts = ("helv", "cour", "Helvetica", "Courier")
        if self._needs_cjk_font(text) and font_name in non_cjk_fonts:
            return "china-ts"  # 繁體中文字型
        return font_name

    def _apply_watermarks_to_page(self, page: fitz.Page, watermarks: List[dict]) -> None:
        """在頁面上繪製浮水印（多行文字、可旋轉、可調透明度與顏色）"""
        if not watermarks:
            return
        page_rect = page.rect
        cx = page_rect.width / 2
        cy = page_rect.height / 2

        for wm in watermarks:
            text = wm.get("text", "")
            angle = wm.get("angle", 0)
            opacity = max(0.0, min(1.0, wm.get("opacity", 0.5)))
            font_size = wm.get("font_size", 48)
            color = wm.get("color", (0.7, 0.7, 0.7))
            font_name = wm.get("font", "helv")
            offset_x = wm.get("offset_x", 0)
            offset_y = wm.get("offset_y", 0)
            line_spacing = wm.get("line_spacing", 1.3)

            font_name = self._get_watermark_font(font_name, text)
            center_x = cx + offset_x
            center_y = cy + offset_y
            center = fitz.Point(center_x, center_y)

            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if not lines:
                continue

            try:
                font = fitz.Font(font_name)
            except Exception:
                font = fitz.Font("china-ts" if self._needs_cjk_font(text) else "helv")

            line_height = font_size * line_spacing
            total_height = line_height * len(lines)
            rad = math.radians(-angle)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)

            for i, line in enumerate(lines):
                if not line:
                    continue
                line_len = font.text_length(line, fontsize=font_size)
                dx = -line_len / 2
                dy = -total_height / 2 + i * line_height + font_size * 0.35
                px = center_x + dx * cos_a - dy * sin_a
                py = center_y + dx * sin_a + dy * cos_a
                pt = fitz.Point(px, py)
                mat = fitz.Matrix(cos_a, -sin_a, sin_a, cos_a, 0, 0)
                page.insert_text(
                    pt,
                    line,
                    fontsize=font_size,
                    fontname=font_name,
                    color=color[:3] if len(color) >= 3 else (0.7, 0.7, 0.7),
                    morph=(center, mat),
                    fill_opacity=opacity,
                    stroke_opacity=opacity,
                )

    def add_watermark(
        self,
        pages: List[int],
        text: str,
        angle: float = 45,
        opacity: float = 0.4,
        font_size: int = 48,
        color: Tuple[float, float, float] = (0.7, 0.7, 0.7),
        font: str = "helv",
        offset_x: float = 0,
        offset_y: float = 0,
        line_spacing: float = 1.3,
    ) -> str:
        """新增浮水印到指定頁面，返回浮水印 id。
        offset_x: 水平偏移（正=向右，負=向左），單位：點
        offset_y: 垂直偏移（正=向下，負=向上），單位：點
        line_spacing: 行距倍率（相對於字型大小，如 1.3 表示 1.3 倍行高）
        """
        if not self.doc or not text.strip():
            raise ValueError("無效的文件或浮水印文字")
        wm_id = str(uuid.uuid4())
        wm = {
            "id": wm_id,
            "pages": [p for p in pages if 1 <= p <= len(self.doc)],
            "text": text.strip(),
            "angle": angle,
            "opacity": opacity,
            "font_size": font_size,
            "color": color,
            "font": font,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "line_spacing": max(0.8, min(3.0, line_spacing)),
        }
        self.watermark_list.append(wm)
        self._watermark_modified = True
        logger.debug(f"新增浮水印: {wm_id}, 頁面 {wm['pages']}")
        return wm_id

    def get_watermarks(self) -> List[dict]:
        """取得所有浮水印"""
        return list(self.watermark_list)

    def remove_watermark(self, watermark_id: str) -> bool:
        """移除浮水印"""
        for i, wm in enumerate(self.watermark_list):
            if wm.get("id") == watermark_id:
                self.watermark_list.pop(i)
                self._watermark_modified = True
                logger.debug(f"已移除浮水印: {watermark_id}")
                return True
        return False

    def update_watermark(
        self,
        watermark_id: str,
        text: Optional[str] = None,
        pages: Optional[List[int]] = None,
        angle: Optional[float] = None,
        opacity: Optional[float] = None,
        font_size: Optional[int] = None,
        color: Optional[Tuple[float, float, float]] = None,
        font: Optional[str] = None,
        offset_x: Optional[float] = None,
        offset_y: Optional[float] = None,
        line_spacing: Optional[float] = None,
    ) -> bool:
        """更新浮水印屬性"""
        for wm in self.watermark_list:
            if wm.get("id") == watermark_id:
                if text is not None:
                    wm["text"] = text.strip()
                if pages is not None:
                    wm["pages"] = [p for p in pages if 1 <= p <= len(self.doc)]
                if angle is not None:
                    wm["angle"] = angle
                if opacity is not None:
                    wm["opacity"] = max(0.0, min(1.0, opacity))
                if font_size is not None:
                    wm["font_size"] = font_size
                if color is not None:
                    wm["color"] = color
                if font is not None:
                    wm["font"] = font
                if offset_x is not None:
                    wm["offset_x"] = offset_x
                if offset_y is not None:
                    wm["offset_y"] = offset_y
                if line_spacing is not None:
                    wm["line_spacing"] = max(0.8, min(3.0, line_spacing))
                self._watermark_modified = True
                logger.debug(f"已更新浮水印: {watermark_id}")
                return True
        return False

    def _get_watermarks_for_page(self, page_num: int) -> List[dict]:
        """取得適用於指定頁面的浮水印"""
        return [wm for wm in self.watermark_list if page_num in wm.get("pages", [])]

    def search_text(self, query: str) -> List[Tuple[int, str, fitz.Rect]]:
        results = []
        if not self.doc:
            return results
        for i in range(len(self.doc)):
            page = self.doc[i]
            found_rects = page.search_for(query)
            for inst in found_rects:
                # 獲取上下文，稍微擴大矩形以獲得更完整的句子
                context_rect = inst + (-10, -5, 10, 5)
                context = page.get_text("text", clip=context_rect, sort=True).strip().replace('\n', ' ')
                results.append((i + 1, context, inst))
        return results

    def ocr_pages(self, pages: List[int]) -> dict:
        results = {}
        for page_num in pages:
            pix = self.doc[page_num - 1].get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img)
            results[page_num] = text
        return results

    def get_page_pixmap(self, page_num: int, scale: float = 1.0) -> fitz.Pixmap:
        """取得頁面影像（含浮水印）"""
        page = self.doc[page_num - 1]
        watermarks = self._get_watermarks_for_page(page_num)
        if not watermarks:
            return page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        tmp_doc = fitz.open()
        tmp_doc.insert_pdf(self.doc, from_page=page_num - 1, to_page=page_num - 1)
        tmp_page = tmp_doc[0]
        self._apply_watermarks_to_page(tmp_page, watermarks)
        pix = tmp_page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        tmp_doc.close()
        return pix

    def get_page_snapshot(self, page_num: int, scale: float = 1.0) -> fitz.Pixmap:
        """獲取頁面的扁平化快照影像（包含所有註解、標記、浮水印）"""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        watermarks = self._get_watermarks_for_page(page_num)
        if not watermarks:
            page = self.doc[page_num - 1]
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix, annots=True)
            logger.debug(f"生成頁面 {page_num} 的快照，尺寸: {pix.width}x{pix.height}, 縮放: {scale}")
            return pix
        tmp_doc = fitz.open()
        tmp_doc.insert_pdf(self.doc, from_page=page_num - 1, to_page=page_num - 1)
        tmp_page = tmp_doc[0]
        self._apply_watermarks_to_page(tmp_page, watermarks)
        matrix = fitz.Matrix(scale, scale)
        pix = tmp_page.get_pixmap(matrix=matrix, annots=True)
        tmp_doc.close()
        logger.debug(f"生成頁面 {page_num} 的快照（含浮水印），尺寸: {pix.width}x{pix.height}, 縮放: {scale}")
        return pix

    def get_thumbnail(self, page_num: int) -> fitz.Pixmap:
        return self.get_page_pixmap(page_num, scale=0.2)

    def get_text_info_at_point(self, page_num: int, point: fitz.Point) -> Tuple[fitz.Rect, str, str, float, tuple, int] | None:
        """獲取指定點下方的文字區塊、內容、字型、大小、顏色與旋轉角度。回傳 (rect, text, font_name, font_size, color, rotation)。"""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None
        page = self.doc[page_num - 1]

        blocks = page.get_text("dict", flags=0)["blocks"]
        for b in blocks:
            if b['type'] == 0:
                rect = fitz.Rect(b["bbox"])
                if point in rect:
                    full_text = []
                    font_name = "helv"
                    font_size = 12.0
                    color_int = 0
                    rotation = 0

                    if b["lines"] and b["lines"][0]["spans"]:
                        first_span = b["lines"][0]["spans"][0]
                        font_name = first_span["font"]
                        font_size = first_span["size"]
                        color_int = first_span.get("color", 0)
                    if b.get("lines") and b["lines"][0].get("dir") is not None:
                        rotation = rotation_degrees_from_dir(b["lines"][0]["dir"])

                    rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
                    color = tuple(c / 255.0 for c in rgb_int)

                    for l in b["lines"]:
                        for s in l["spans"]:
                            full_text.append(s["text"])
                        full_text.append("\n")

                    text_content = "".join(full_text).rstrip("\n")
                    logger.debug(f"找到文字區塊: {rect}, 字型: {font_name}, 大小: {font_size}, rotation: {rotation}")
                    return rect, text_content, font_name, font_size, color, rotation
        return None

    def get_render_width_for_edit(self, page_num: int, rect: fitz.Rect, rotation: int = 0, font_size: float = 12) -> float:
        """取得編輯時會使用的換行寬度（points），供編輯框預覽與 PDF 渲染一致。"""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return rect.width
        page = self.doc[page_num - 1]
        page_rect = page.rect
        margin = 15
        right_margin_pt = max(60.0, min(120.0, float(font_size) * 2.0))
        right_safe = page_rect.x1 - right_margin_pt
        if rotation in (90, 270):
            return rect.width
        max_w = right_safe - max(rect.x0, page_rect.x0) - margin
        return max(rect.width, min(max_w, page_rect.width * 0.98))

    def _convert_text_to_html(self, text: str, font_size: int, color: tuple) -> str:
        """
        將混合文本轉換為帶有字體樣式的簡單 HTML，並正確處理空格。
        [優化 3] 使用模組級預編譯正則 _RE_HTML_TEXT_PARTS、_RE_CJK，避免重複編譯
        """
        html_parts = []
        if not text:
            return ""

        parts = _RE_HTML_TEXT_PARTS.findall(text)

        for part in parts:
            if part == '\n':
                html_parts.append('<br>')
            elif part.isspace():
                html_parts.append(f'<span style="font-family: helv;">{part}</span>')
            elif _RE_CJK.match(part):
                html_parts.append(f'<span style="font-family: cjk;">{_html_mod.escape(part)}</span>')
            else:
                html_parts.append(f'<span style="font-family: helv;">{_html_mod.escape(part)}</span>')

        return "".join(html_parts)


    # ──────────────────────────────────────────────────────────────────────────
    # Phase 6: 文件整體快照（供 SnapshotCommand undo/redo 使用）
    # ──────────────────────────────────────────────────────────────────────────

    def _capture_doc_snapshot(self) -> bytes:
        """擷取整份文件的 bytes 快照（SnapshotCommand before/after 用）。"""
        stream = io.BytesIO()
        self.doc.save(stream, garbage=0)
        return stream.getvalue()

    def _restore_doc_from_snapshot(self, snapshot_bytes: bytes) -> None:
        """用 bytes 快照替換整份文件（SnapshotCommand undo/redo 時呼叫）。"""
        self.doc.close()
        self.doc = fitz.open("pdf", snapshot_bytes)
        logger.debug(f"_restore_doc_from_snapshot: 已還原文件（{len(snapshot_bytes)} bytes）")

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 3: 頁面快照（取代 clone_page）
    # ──────────────────────────────────────────────────────────────────────────

    def _capture_page_snapshot(self, page_num_0based: int) -> bytes:
        """
        擷取指定頁面的 bytes 快照，供 undo / rollback 使用。
        Fallback 策略（依序）：
          1. 正常 insert_pdf（含 annotations）
          2. insert_pdf annots=False（含跨頁 annotation 引用的 PDF）
          3. 整份文件快照（最保守）
        """
        # 嘗試 1：完整頁面（含 annotations）
        try:
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(self.doc, from_page=page_num_0based, to_page=page_num_0based)
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            data = stream.getvalue()
            tmp_doc.close()
            return data
        except Exception as e1:
            logger.debug(f"_capture_page_snapshot 完整複製失敗 (p{page_num_0based+1}): {e1}，嘗試 annots=False")

        # 嘗試 2：不含 annotations（避免跨頁 xref 無效引用）
        try:
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(
                self.doc, from_page=page_num_0based, to_page=page_num_0based,
                annots=False
            )
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            data = stream.getvalue()
            tmp_doc.close()
            logger.debug(f"_capture_page_snapshot: 使用 annots=False 快照 (p{page_num_0based+1})")
            return data
        except Exception as e2:
            logger.debug(f"_capture_page_snapshot annots=False 亦失敗: {e2}，改用文件級快照")

        # 嘗試 3：整份文件快照（最保守，undo 效果較差但不崩潰）
        return self._capture_doc_snapshot()

    def _restore_page_from_snapshot(self, page_num_0based: int, snapshot_bytes: bytes) -> None:
        """用 bytes 快照替換 doc 中指定頁面（undo / rollback 時呼叫）"""
        snapshot_doc = fitz.open("pdf", snapshot_bytes)
        self.doc.delete_page(page_num_0based)
        self.doc.insert_pdf(snapshot_doc, from_page=0, to_page=0, start_at=page_num_0based)
        snapshot_doc.close()

    def _build_insert_css(self, size: float, color: tuple) -> str:
        """建構 insert_htmlbox 所需的 CSS 樣式字串"""
        return f"""
            span {{
                font-size: {size}pt;
                white-space: pre-wrap;
                word-break: break-all;
                overflow-wrap: anywhere;
                color: rgb({int(color[0]*255)}, {int(color[1]*255)}, {int(color[2]*255)});
            }}
            .helv {{ font-family: helv; }}
            .cjk {{ font-family: cjk; }}
        """

    # ──────────────────────────────────────────────────────────────────────────
    # Bug fix: apply_redactions 會誤刪與 redact_rect 重疊的非文字 annot（FreeText 等）。
    # 在呼叫前儲存重疊 annot，呼叫後還原。
    # ──────────────────────────────────────────────────────────────────────────

    _ANNOT_FREE_TEXT = 2    # fitz.PDF_ANNOT_FREE_TEXT
    _ANNOT_HIGHLIGHT = 8
    _ANNOT_SQUARE    = 4
    _ANNOT_CIRCLE    = 5
    _ANNOT_UNDERLINE = 9
    _ANNOT_STRIKEOUT = 10
    _ANNOT_REDACT    = 12   # fitz.PDF_ANNOT_REDACT — 不保留

    def _save_overlapping_annots(self, page: fitz.Page, redact_rect: fitz.Rect) -> list:
        """
        擷取頁面中與 redact_rect 重疊的非 redact 類型 annot 資訊。
        apply_redactions 後呼叫 _restore_annots() 還原。

        對壞損 xref / NoneType 等 PyMuPDF 異常做 graceful 跳過，不讓單一
        損壞 annotation 阻斷整個 edit_text 流程。
        """
        saved = []
        try:
            annot_iter = list(page.annots())
        except Exception as e:
            logger.warning(f"_save_overlapping_annots: page.annots() 失敗（壞損 annot xref？）: {e}")
            return saved

        for annot in annot_iter:
            try:
                if annot is None:
                    continue
                if annot.type[0] == self._ANNOT_REDACT:
                    continue
                if not fitz.Rect(annot.rect).intersects(redact_rect):
                    continue
                entry = {
                    "type_code": annot.type[0],
                    "type_name": annot.type[1],
                    "rect":      fitz.Rect(annot.rect),
                    "info":      dict(annot.info),
                    "colors":    annot.colors,
                    "opacity":   annot.opacity,
                    "border":    annot.border,
                    "vertices":  annot.vertices,
                }
                saved.append(entry)
                logger.debug(f"_save_overlapping_annots: 儲存 {annot.type[1]} @ {annot.rect}")
            except Exception as e:
                logger.warning(f"_save_overlapping_annots: 跳過損壞 annot: {e}")
                continue
        return saved

    def _restore_annots(self, page: fitz.Page, saved: list) -> None:
        """
        還原 _save_overlapping_annots 儲存的 annot。
        僅支援常見類型；不支援的類型記錄 warning。
        """
        for a in saved:
            tc = a["type_code"]
            rect = a["rect"]
            info = a["info"]
            colors = a["colors"] or {}
            stroke = colors.get("stroke") or (0, 0, 0)
            fill   = colors.get("fill")

            try:
                if tc == self._ANNOT_FREE_TEXT:
                    new_a = page.add_freetext_annot(
                        rect,
                        info.get("content", ""),
                        fontname="helv",
                        fontsize=10.5,
                        text_color=stroke if stroke else (0, 0, 0),
                        fill_color=fill if fill else (1, 1, 0.8),
                        rotate=page.rotation,
                    )
                    new_a.update()

                elif tc == self._ANNOT_HIGHLIGHT:
                    verts = a.get("vertices")
                    if verts:
                        new_a = page.add_highlight_annot(quads=verts)
                    else:
                        new_a = page.add_highlight_annot(rect)
                    if stroke:
                        new_a.set_colors(stroke=stroke)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                elif tc == self._ANNOT_SQUARE:
                    new_a = page.add_rect_annot(rect)
                    new_a.set_colors(stroke=stroke, fill=fill)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                elif tc == self._ANNOT_CIRCLE:
                    new_a = page.add_circle_annot(rect)
                    new_a.set_colors(stroke=stroke, fill=fill)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                elif tc in (self._ANNOT_UNDERLINE, self._ANNOT_STRIKEOUT):
                    verts = a.get("vertices")
                    if tc == self._ANNOT_UNDERLINE:
                        new_a = page.add_underline_annot(quads=verts) if verts else page.add_underline_annot(rect)
                    else:
                        new_a = page.add_strikeout_annot(quads=verts) if verts else page.add_strikeout_annot(rect)
                    if stroke:
                        new_a.set_colors(stroke=stroke)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                else:
                    logger.warning(
                        f"_restore_annots: 不支援的 annot 類型 {a['type_name']} ({tc})，跳過還原"
                    )
                    continue

                logger.debug(f"_restore_annots: 已還原 {a['type_name']} @ {rect}")

            except Exception as e:
                logger.warning(f"_restore_annots: 還原 {a['type_name']} 失敗: {e}")

    def apply_pending_redactions(self) -> None:
        """
        批次清理所有已修改頁面的 content stream（Phase 6 效能優化）。
        對每個 pending_edit 中記錄的頁面呼叫 page.clean_contents()，
        壓縮 content stream、移除孤立資源，可降低 PDF 大小 10-30%。
        應在 save() 前或每 5 次編輯時呼叫。
        """
        if not self.pending_edits or not self.doc:
            return
        unique_pages = {e["page_idx"] for e in self.pending_edits}
        cleaned = 0
        for page_idx in sorted(unique_pages):
            if 0 <= page_idx < len(self.doc):
                try:
                    self.doc[page_idx].clean_contents()
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"clean_contents 失敗（頁面 {page_idx + 1}）: {e}")
        logger.debug(
            f"apply_pending_redactions: 已清理 {cleaned}/{len(unique_pages)} 頁的 content stream"
        )
        self.pending_edits.clear()

    def _maybe_garbage_collect(self) -> None:
        """
        分層垃圾回收策略（Phase 6）：
          - 每 5 次編輯：呼叫 apply_pending_redactions()（輕量，clean_contents）
          - 每 20 次編輯：tobytes(garbage=4) + 重新載入（完整 GC，清孤立 xref）
        閾值從 10 提高到 20，降低 live editing 時的全量序列化頻率。
        """
        if self.edit_count <= 0:
            return
        # 輕量層：每 5 次清理 content stream
        if self.edit_count % 5 == 0:
            self.apply_pending_redactions()
        # 完整層：每 20 次重建文件以清孤立物件
        if self.edit_count % 20 == 0:
            try:
                data = self.doc.tobytes(garbage=4, deflate=True)
                self.doc.close()
                self.doc = fitz.open("pdf", data)
                self.block_manager.build_index(self.doc)
                logger.info(
                    f"完整 GC 完成（第 {self.edit_count} 次編輯後），已重新載入文件"
                )
            except Exception as e:
                logger.warning(f"完整 GC 失敗，繼續使用現有文件: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Push-Down 輔助方法：換行溢出時保留並推移下方文字塊
    # ──────────────────────────────────────────────────────────────────────────

    def _resolve_font_for_push(self, raw_font_name: str) -> str:
        """
        將 get_text("dict") 返回的字體名稱（如 'ABCDEF+ArialMT'）轉為
        page.insert_text() 可接受的名稱。若原字體不可用則回退至最接近的
        PyMuPDF 內建字體（helv / tiro / cour 系列）。
        """
        # 去除嵌入子集前綴（如 "ABCDEF+Arial" → "Arial"）
        base = raw_font_name.split("+", 1)[-1] if "+" in raw_font_name else raw_font_name

        # 嘗試直接使用原名稱
        try:
            fitz.Font(base)
            return base
        except Exception:
            pass

        # 依字體名稱特徵回退至 PyMuPDF 內建字體
        low = base.lower()
        is_bold   = "bold"   in low
        is_italic = "italic" in low or "oblique" in low
        is_mono   = "courier" in low or "mono" in low or "typewriter" in low
        is_serif  = "times" in low or "roman" in low or "georgia" in low

        if is_mono:
            if is_bold and is_italic: return "cour-bi"
            if is_bold:               return "cour-b"
            if is_italic:             return "cour-i"
            return "cour"
        if is_serif:
            if is_bold and is_italic: return "tibo"
            if is_bold:               return "tib"
            if is_italic:             return "tiit"
            return "tiro"
        # sans-serif (Helvetica / Arial / 其他)
        if is_bold and is_italic: return "heit"
        if is_bold:               return "hebo"
        if is_italic:             return "heit"
        return "helv"

    def _push_down_overlapping_text(
        self,
        page: fitz.Page,
        page_rect: fitz.Rect,
        above_y: float,
        new_bottom: float,
        edit_x0: float,
        edit_x1: float,
    ) -> None:
        """
        換行溢出修正：將位於 [above_y, new_bottom] Y 區間內（且與
        [edit_x0, edit_x1] X 範圍有重疊）的文字塊向下推移，使它們
        落在 new_bottom 之後，保留原有文字內容，不重疊於新插入的文字。

        支援 cascade：每個 block 推移後，若與下一個 block 仍有重疊，
        自動繼續推移，直到頁面底部。

        Args:
            page       : 當前頁面物件
            page_rect  : 頁面邊界 Rect
            above_y    : 原始 block 的底部 Y（= redact_rect.y1）
            new_bottom : 新插入文字的底部 Y（= shrunk_rect.y1）
            edit_x0    : 編輯區 X 左邊界
            edit_x1    : 編輯區 X 右邊界
        """
        GAP   = 2.0   # 推移後與上方文字的最小間距
        X_TOL = 5.0   # X 方向重疊容差
        page_idx = page.number

        # ── 1. 取得整頁文字結構 ──
        raw = page.get_text(
            "dict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES,
        )

        # ── 2. 找出溢出區間內且 X 重疊的文字 block ──
        candidates: list[tuple[fitz.Rect, dict]] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:      # 只處理純文字 block
                continue
            bbox = fitz.Rect(block["bbox"])
            # Y 範圍：必須在 above_y 和 new_bottom + margin 之間開始
            if bbox.y0 < above_y - 1.0:
                continue
            if bbox.y0 > new_bottom + 5.0:
                continue
            # X 重疊：至少有部分與編輯欄重疊
            if bbox.x1 < edit_x0 - X_TOL or bbox.x0 > edit_x1 + X_TOL:
                continue
            candidates.append((fitz.Rect(bbox), block))

        if not candidates:
            logger.debug("_push_down_overlapping_text: 溢出區內無需推移的文字塊")
            return

        # ── 3. 按 y0 排序，cascade 計算各 block 的 delta_y ──
        candidates.sort(key=lambda c: c[0].y0)
        push_floor = new_bottom + GAP   # 目前可用的最低安全邊界

        plan: list[tuple[fitz.Rect, dict, float]] = []   # (bbox, block, delta_y)
        for bbox, block in candidates:
            delta_y = max(0.0, push_floor - bbox.y0)
            new_y1  = bbox.y1 + delta_y
            if new_y1 > page_rect.y1 + 5.0:
                logger.warning(
                    f"_push_down: block [y={bbox.y0:.0f}~{bbox.y1:.0f}] "
                    f"推移 {delta_y:.1f}pt 後超出頁面，跳過"
                )
                push_floor = max(push_floor, bbox.y1 + GAP)
                continue
            plan.append((fitz.Rect(bbox), block, delta_y))
            push_floor = new_y1 + GAP   # cascade：更新安全邊界

        if not plan:
            return

        # ── 4. 預先收集所有 span 資料（讀），避免 redact 後影響 get_text ──
        insert_tasks: list[dict] = []
        redact_rects: list[fitz.Rect] = []
        shifted_annots: list[dict] = []

        for bbox, block, delta_y in plan:
            redact_rects.append(fitz.Rect(bbox))
            # 儲存此 block 上的 annotation 並計算推移後位置
            for saved_a in self._save_overlapping_annots(page, bbox):
                r = fitz.Rect(saved_a["rect"])
                shifted_annots.append(dict(
                    saved_a,
                    rect=fitz.Rect(r.x0, r.y0 + delta_y, r.x1, r.y1 + delta_y),
                ))
            # 收集 span 資訊
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    orig = span.get("origin")
                    if not orig:
                        continue
                    c_int = span.get("color", 0)
                    insert_tasks.append({
                        "origin": fitz.Point(orig[0], orig[1] + delta_y),
                        "text":   span.get("text", ""),
                        "font":   span.get("font", "helv"),
                        "size":   float(span.get("size", 12)),
                        "color":  (
                            ((c_int >> 16) & 0xFF) / 255.0,
                            ((c_int >>  8) & 0xFF) / 255.0,
                            ( c_int        & 0xFF) / 255.0,
                        ),
                    })

        # ── 5. 批次 Redact（一次 apply，減少 PDF stream 操作次數）──
        for rect in redact_rects:
            page.add_redact_annot(rect)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        # 在推移後的位置還原 annotation
        if shifted_annots:
            self._restore_annots(page, shifted_annots)

        # ── 6. 批次 Insert（span 逐一插入，字體回退）──
        inserted = 0
        for task in insert_tasks:
            if not task["text"].strip():
                continue
            font_name = self._resolve_font_for_push(task["font"])
            try:
                page.insert_text(
                    task["origin"], task["text"],
                    fontname=font_name,
                    fontsize=task["size"],
                    color=task["color"],
                )
                inserted += 1
            except Exception as e_main:
                logger.debug(
                    f"_push_down insert_text({font_name}) 失敗: {e_main}，改用 helv"
                )
                try:
                    page.insert_text(
                        task["origin"], task["text"],
                        fontname="helv",
                        fontsize=task["size"],
                        color=task["color"],
                    )
                    inserted += 1
                except Exception as e2:
                    logger.warning(
                        f"_push_down: span '{task['text'][:20]}' 無法插入: {e2}"
                    )

        # ── 7. 更新 TextBlockManager 索引中被推移 block 的 layout_rect ──
        for bbox, _block, delta_y in plan:
            new_rect = fitz.Rect(
                bbox.x0, bbox.y0 + delta_y,
                bbox.x1, bbox.y1 + delta_y,
            )
            tb = self.block_manager.find_by_rect(page_idx, bbox)
            if tb:
                self.block_manager.update_block(tb, layout_rect=new_rect)

        logger.debug(
            f"_push_down_overlapping_text: 推移了 {len(plan)} 個 block，"
            f"插入 {inserted} 個 span"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 3: 五步流程 + 三策略 edit_text
    # ──────────────────────────────────────────────────────────────────────────

    def edit_text(self, page_num: int, rect: fitz.Rect, new_text: str,
                  font: str = "helv", size: int = 12,
                  color: tuple = (0.0, 0.0, 0.0),
                  original_text: str = None,
                  vertical_shift_left: bool = True):
        """
        編輯文字：五步流程 + 三策略智能插入。

        流程：
          1. 驗證：從 TextBlockManager 取出 TextBlock，比對原文字
          2. 安全 Redaction：只清除目標 block 的 layout_rect
          3. 智能插入：策略 A (htmlbox) → B (auto-expand) → C (fallback)
          4. 驗證與回滾：difflib.ratio > 0.92，否則 page-level snapshot 回滾
          5. 更新索引：block_manager.update_block()

        Args:
            page_num: 頁碼（1-based）
            rect: 使用者選取的粗略矩形
            new_text: 新文字內容
            font: 字體名稱
            size: 字體大小
            color: 文字顏色 (0-1 float tuple)
            original_text: 原始文字內容（可選，用於精確定位）
            vertical_shift_left: 垂直文字擴展方向（True=左移，False=右移）
        """
        if not new_text.strip():
            logger.warning("文字內容為空，跳過編輯")
            return

        _t0 = time.perf_counter()  # Phase 6: 效能計時
        page_idx = page_num - 1
        page = self.doc[page_idx]
        page_rect = page.rect

        # ── Step 0: 擷取 page-level 快照，供回滾使用 ──
        snapshot_bytes = self._capture_page_snapshot(page_idx)

        try:
            # ═══════════ Step 1: 驗證 ═══════════
            target = self.block_manager.find_by_rect(
                page_idx, rect, original_text=original_text, doc=self.doc
            )
            if not target:
                logger.warning(f"無法找到目標文字方塊，頁面 {page_num} 矩形 {rect}")
                return

            clip_text = page.get_text("text", clip=target.rect).strip()
            norm_clip = self._normalize_text_for_compare(clip_text)
            norm_block = self._normalize_text_for_compare(target.text)
            if norm_block and norm_clip:
                match_ratio = difflib.SequenceMatcher(
                    None, norm_block, norm_clip
                ).ratio()
                if match_ratio < 0.5:
                    logger.debug(
                        f"索引文字與頁面文字不匹配 (ratio={match_ratio:.2f})，"
                        "重建該頁索引"
                    )
                    self.block_manager.rebuild_page(page_idx, self.doc)
                    target = self.block_manager.find_by_rect(
                        page_idx, rect, original_text=original_text, doc=self.doc
                    )
                    if not target:
                        logger.warning("重建索引後仍找不到目標文字方塊")
                        return

            rotation = target.rotation
            is_vertical = target.is_vertical
            insert_rotate = self._insert_rotate_for_htmlbox(rotation)
            redact_rect = fitz.Rect(target.layout_rect)

            # ═══════════ Step 2: 安全 Redaction ═══════════
            # apply_redactions 必須在 insert_htmlbox 之前立即執行（確保舊文字已清除），
            # pending_edits 僅追蹤已修改的頁面，供 apply_pending_redactions() 批次 clean_contents。
            # [Bug fix] 在 redaction 前先儲存重疊的非文字 annot，redaction 後還原，
            # 避免 PyMuPDF apply_redactions 誤刪 FreeText 等 annotation。
            _saved_annots = self._save_overlapping_annots(page, redact_rect)
            page.add_redact_annot(redact_rect)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            if _saved_annots:
                self._restore_annots(page, _saved_annots)
            self.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(redact_rect)})
            logger.debug(f"已安全清除目標文字框: {redact_rect}，還原 {len(_saved_annots)} 個 annot")

            # ═══════════ Step 3: 智能插入（三策略）═══════════
            html_content = self._convert_text_to_html(new_text, int(size), color)
            css = self._build_insert_css(size, color)

            # --- 計算初始插入矩形 ---
            if is_vertical:
                base_rect = self._vertical_html_rect(
                    target.layout_rect, new_text, size, font,
                    page_rect, anchor_right=vertical_shift_left
                )
                base_y1 = base_rect.y1
                insert_rect = fitz.Rect(
                    base_rect.x0, base_rect.y0, base_rect.x1, page_rect.y1
                )
            else:
                margin = 15
                right_margin_pt = max(60.0, min(120.0, float(size) * 2.0))
                right_safe = page_rect.x1 - right_margin_pt
                x0 = max(target.layout_rect.x0, page_rect.x0)
                max_w = max(0, min(
                    page_rect.width - margin,
                    right_safe - x0 - margin
                ))
                x1 = min(x0 + max(target.layout_rect.width, max_w), right_safe)
                y0 = max(target.layout_rect.y0, page_rect.y0)
                line_count = max(1, len(new_text.split('\n')))
                est_height = line_count * size * 2 + size * 2
                base_y1 = y0 + max(target.layout_rect.height, est_height)
                insert_rect = fitz.Rect(x0, y0, x1, page_rect.y1)

            insert_rect = self._clamp_rect_to_page(insert_rect, page_rect)

            # ── Pre-push Probe（水平文字）：預估換行高度，預先推移下方文字塊 ──────
            # 重要：Push-Down 必須在 insert_htmlbox「之前」執行。
            # 原因：apply_redactions() 清除舊 block 時，若 Form XObject 已存在，
            #       會同時抹去 Form XObject 內落在同一矩形的新文字（PyMuPDF 預設行為），
            #       導致新插入的文字在驗證時消失（ratio 暴跌）。
            #
            # 做法：先用臨時頁面 probe 估算換行高度，若預測會溢出則先推移，
            #       再對乾淨的頁面執行正式 insert_htmlbox。
            if not is_vertical:
                try:
                    _probe_doc = fitz.open()
                    _probe_page = _probe_doc.new_page(
                        width=page_rect.width, height=page_rect.height
                    )
                    _probe_spare, _ = _probe_page.insert_htmlbox(
                        insert_rect, html_content, css=css,
                        rotate=0, scale_low=1,
                    )
                    _probe_doc.close()
                    _probe_used_h = insert_rect.height - _probe_spare
                    _probe_y1 = insert_rect.y0 + _probe_used_h + 4.0
                    _probe_y1 = float(min(max(_probe_y1, base_y1), page_rect.y1))
                    if _probe_y1 > redact_rect.y1 + 2.0:
                        logger.debug(
                            f"換行預估溢出 {_probe_y1 - redact_rect.y1:.1f}pt，"
                            "預先推移下方文字塊（pre-push）"
                        )
                        self._push_down_overlapping_text(
                            page, page_rect,
                            above_y=redact_rect.y1,
                            new_bottom=_probe_y1,
                            edit_x0=x0,
                            edit_x1=x1,
                        )
                except Exception as _probe_err:
                    logger.debug(f"Pre-push probe 失敗（忽略）: {_probe_err}")
            # ── End of pre-push probe ──────────────────────────────────────────

            # ── 策略 A: insert_htmlbox (scale_low=1) ──
            spare_height, scale_used = page.insert_htmlbox(
                insert_rect, html_content, css=css,
                rotate=insert_rotate, scale_low=1
            )
            new_layout_rect = fitz.Rect(insert_rect)
            logger.debug(f"策略 A: spare_height={spare_height}, scale={scale_used}")

            if spare_height < 0:
                # ── 策略 B: 自動擴寬 + 再試 ──
                logger.debug("策略 A 失敗，嘗試策略 B（自動擴寬）")
                try:
                    font_for_measure = (
                        "china-ts" if self._needs_cjk_font(new_text) else font
                    )
                    try:
                        font_obj = fitz.Font(font_for_measure)
                    except Exception:
                        font_for_measure = "helv"
                        font_obj = fitz.Font(font_for_measure)
                    text_width = font_obj.text_length(
                        new_text.replace('\n', ''), fontsize=size
                    )
                    expanded_width = max(
                        insert_rect.width, text_width * 1.15 + size
                    )

                    if is_vertical:
                        expanded_rect = fitz.Rect(
                            insert_rect.x0 - (expanded_width - insert_rect.width),
                            insert_rect.y0, insert_rect.x1, insert_rect.y1
                        )
                    else:
                        expanded_rect = fitz.Rect(
                            insert_rect.x0, insert_rect.y0,
                            min(insert_rect.x0 + expanded_width,
                                page_rect.x1 - 10),
                            insert_rect.y1
                        )
                    expanded_rect = self._clamp_rect_to_page(
                        expanded_rect, page_rect
                    )
                    spare_height, scale_used = page.insert_htmlbox(
                        expanded_rect, html_content, css=css,
                        rotate=insert_rotate, scale_low=1
                    )
                    new_layout_rect = fitz.Rect(expanded_rect)
                    logger.debug(
                        f"策略 B: spare_height={spare_height}, scale={scale_used}"
                    )
                except Exception as ex_b:
                    logger.debug(f"策略 B 失敗: {ex_b}")

            if spare_height < 0:
                # ── 策略 C: fallback ──
                if is_vertical:
                    spare_height, scale_used = page.insert_htmlbox(
                        new_layout_rect, html_content, css=css,
                        rotate=insert_rotate, scale_low=0
                    )
                    logger.debug(
                        f"策略 C（垂直, scale_low=0）: "
                        f"spare_height={spare_height}"
                    )
                else:
                    # 水平文字：允許最低縮放 0.5 倍來塞入，避免直接放棄
                    spare_height, scale_used = page.insert_htmlbox(
                        new_layout_rect, html_content, css=css,
                        rotate=insert_rotate, scale_low=0.5
                    )
                    if spare_height < 0:
                        self._restore_page_from_snapshot(page_idx, snapshot_bytes)
                        self.block_manager.rebuild_page(page_idx, self.doc)
                        raise RuntimeError(
                            f"文字框內容在字級 {size}pt 下無法完整塞入 "
                            f"(spare_height={spare_height})，"
                            "策略 A/B/C 均失敗，已回滾。"
                        )
                    logger.debug(
                        f"策略 C（水平, scale_low=0.5）: "
                        f"spare_height={spare_height}, scale={scale_used}"
                    )

            # --- 垂直文字：binary shrink height ---
            if is_vertical:
                padding = self._calc_vertical_padding(size)
                shrunk_rect = self._binary_shrink_height(
                    page, insert_rect, new_text,
                    iterations=7, padding=padding, min_y1=base_y1
                )
                shrunk_rect = self._clamp_rect_to_page(shrunk_rect, page_rect)
                _saved_annots_v = self._save_overlapping_annots(page, insert_rect)
                page.add_redact_annot(insert_rect)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                if _saved_annots_v:
                    self._restore_annots(page, _saved_annots_v)
                spare_height, scale_used = page.insert_htmlbox(
                    shrunk_rect, html_content, css=css,
                    rotate=insert_rotate, scale_low=1
                )
                if spare_height < 0:
                    page.insert_htmlbox(
                        shrunk_rect, html_content, css=css,
                        rotate=insert_rotate, scale_low=0
                    )
                new_layout_rect = fitz.Rect(shrunk_rect)
            else:
                # spare_height 直接告訴我們文字實際佔用高度（比 binary search + get_text probe 更可靠），
                # 避免 _text_fits_in_rect 因 HTML escape / 字型差異導致全部 probe 失敗，
                # 進而使 new_layout_rect 退化成整頁高度、抓到其他 block 的文字。
                text_used_height = new_layout_rect.height - spare_height
                computed_y1 = new_layout_rect.y0 + text_used_height + 4.0
                # 至少覆蓋原始 block 高度，避免 layout_rect 過小
                computed_y1 = max(computed_y1, base_y1)
                shrunk_rect = fitz.Rect(
                    new_layout_rect.x0, new_layout_rect.y0,
                    new_layout_rect.x1, computed_y1
                )
                shrunk_rect = self._clamp_rect_to_page(shrunk_rect, page_rect)
                new_layout_rect = fitz.Rect(shrunk_rect)


            # ═══════════ Step 4: 驗證與回滾 ═══════════
            # 使用全頁文字做 substring check，避免 clip 邊界截斷或抓到鄰近 block：
            #   - 若 norm_new 是全頁文字的子字串 → ratio=1.0
            #   - 否則 fallback 到 SequenceMatcher（仍用全頁文字，容許輕微差異）
            full_page_text = page.get_text("text")
            norm_new = self._normalize_text_for_compare(new_text)
            norm_page = self._normalize_text_for_compare(full_page_text)

            if norm_new and norm_new in norm_page:
                sim_ratio = 1.0
            elif norm_new and norm_page:
                sim_ratio = difflib.SequenceMatcher(
                    None, norm_new, norm_page
                ).ratio()
            else:
                sim_ratio = 1.0 if not norm_new else 0.0

            logger.debug(
                f"Step4 驗證: ratio={sim_ratio:.2f}, "
                f"layout_rect={new_layout_rect}, "
                f"norm_new[:{min(40, len(norm_new))}]={norm_new[:40]!r}"
            )

            # 垂直文字 get_text(clip=) 對旋轉內容擷取不準確，跳過嚴格驗證
            # 閾值 0.80：容許 get_text clip 邊界截斷、字型差異等正常偏差（<20%）
            if sim_ratio < 0.80 and not is_vertical:
                logger.warning(
                    f"插入後驗證失敗 (ratio={sim_ratio:.2f})，"
                    f"正在回滾頁面 {page_num}"
                )
                self._restore_page_from_snapshot(page_idx, snapshot_bytes)
                self.block_manager.rebuild_page(page_idx, self.doc)
                raise RuntimeError(
                    f"文字編輯驗證失敗：difflib.ratio="
                    f"{sim_ratio:.2f} < 0.80，已回滾。"
                )

            # ═══════════ Step 5: 更新索引 ═══════════
            update_kwargs = dict(
                text=new_text,
                font=font,
                size=float(size),
                color=color,
            )
            # 垂直文字保持原始 rect/layout_rect，避免逐次編輯造成 bbox 漂移
            if not is_vertical:
                update_kwargs['layout_rect'] = new_layout_rect
            self.block_manager.update_block(target, **update_kwargs)
            logger.debug(
                f"編輯文字成功: 頁面 {page_num}, "
                f"block_id={target.block_id}, "
                f"text='{new_text[:30]}...'"
            )

            # ── Phase 6: GC + 效能計時 ──
            self.edit_count += 1
            self._maybe_garbage_collect()

            _duration = time.perf_counter() - _t0
            if _duration > 0.3:
                logger.warning(
                    f"單次編輯過慢：{_duration:.3f}s，頁面 {page_num}，"
                    f"text='{new_text[:20]}…'"
                )
            else:
                logger.debug(f"編輯完成，耗時 {_duration:.3f}s，頁面 {page_num}")

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"編輯文字時發生非預期錯誤: {e}")
            try:
                self._restore_page_from_snapshot(page_idx, snapshot_bytes)
                self.block_manager.rebuild_page(page_idx, self.doc)
            except Exception:
                pass
            raise RuntimeError(f"編輯文字失敗: {e}") from e

        # Phase 4: undo/redo 已由 CommandManager (EditTextCommand) 全權負責，
        #          此處不再呼叫 _save_state()，避免雙重儲存浪費 I/O。

    # _save_state() 已於 Phase 6 移除，所有 undo/redo 由 CommandManager 統一管理。
    
    def _full_save_to_path(self, path: str):
        """
        完整儲存到指定路徑。若目標路徑與目前開啟的檔案相同（doc.name），
        先寫入暫存檔再覆蓋，避免 Windows 上「覆寫已開啟檔案」導致 Permission denied。
        """
        path_resolved = Path(path).resolve()
        doc_name_resolved = Path(self.doc.name).resolve() if self.doc.name else None
        saving_over_open_file = doc_name_resolved is not None and path_resolved == doc_name_resolved

        if saving_over_open_file:
            # 先寫入暫存檔，關閉 doc 後再覆蓋原檔，最後重新開啟
            temp_save = Path(self.temp_dir.name) / f"save_{uuid.uuid4()}.pdf"
            self.doc.save(str(temp_save), garbage=0)
            self.doc.close()
            try:
                shutil.copy2(str(temp_save), path)
            finally:
                try:
                    os.unlink(temp_save)
                except OSError as e:
                    logger.warning(f"無法刪除暫存檔 {temp_save}: {e}")
            self.doc = fitz.open(path)
            logger.debug(f"已透過暫存檔覆寫原檔: {path}")
        else:
            self.doc.save(path, garbage=0)

    def save_as(self, new_path: str):
        """另存 PDF（含浮水印）。若存回原檔且支援增量更新，則使用 incremental=True。"""
        if not self.doc:
            return
        # Phase 6: 儲存前批次清理已修改頁面的 content stream，壓縮 PDF 大小
        self.apply_pending_redactions()
        new_path_resolved = Path(new_path).resolve()
        original_resolved = Path(self.original_path).resolve() if self.original_path else None
        doc_name_resolved = Path(self.doc.name).resolve() if self.doc.name else None
        # 是否為「存回原檔」：新路徑與開啟時路徑相同，且目前 doc 仍是從原檔開啟（未經 undo 載入 temp）
        is_save_back_to_original = (
            original_resolved is not None
            and doc_name_resolved is not None
            and new_path_resolved == original_resolved
            and doc_name_resolved == original_resolved
        )
        can_incr = getattr(self.doc, "can_save_incrementally", None)
        use_incremental = (
            self.use_incremental_save
            and is_save_back_to_original
            and can_incr
            and self.doc.can_save_incrementally()
        )
        if self.watermark_list:
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(self.doc)
            for wm in self.watermark_list:
                for p in wm.get("pages", []):
                    if 1 <= p <= len(tmp_doc):
                        self._apply_watermarks_to_page(tmp_doc[p - 1], [wm])
            # 若目標路徑為目前開啟的檔案，先寫暫存再覆蓋，避免 Windows Permission denied
            if doc_name_resolved is not None and new_path_resolved == doc_name_resolved:
                temp_save = Path(self.temp_dir.name) / f"save_{uuid.uuid4()}.pdf"
                tmp_doc.save(str(temp_save), garbage=0)
                tmp_doc.close()
                self.doc.close()
                try:
                    shutil.copy2(str(temp_save), new_path)
                finally:
                    try:
                        os.unlink(temp_save)
                    except OSError:
                        pass
                self.doc = fitz.open(new_path)
            else:
                tmp_doc.save(new_path, garbage=0)
                tmp_doc.close()
        elif use_incremental:
            # 增量更新時使用與 doc.name 一致的路徑格式，避免 PyMuPDF 判定為非原檔
            try:
                save_target = self.doc.name if self.doc.name else new_path
                self.doc.save(save_target, incremental=True)
                logger.debug(f"已使用增量更新儲存: {new_path}")
            except Exception as e:
                logger.warning(f"增量更新儲存失敗，改為完整儲存: {e}")
                self._full_save_to_path(new_path)
        else:
            self._full_save_to_path(new_path)
        self.saved_path = new_path
        self.command_manager.mark_saved()
        self.edit_count = 0
        self._watermark_modified = False
    
    def has_unsaved_changes(self) -> bool:
        """檢查是否有未儲存的變更（Phase 6：統一由 command_manager 管理）。"""
        if not self.doc:
            return False
        if getattr(self, '_watermark_modified', False):
            return True
        return self.command_manager.has_pending_changes()

    # undo() / redo() 已於 Phase 6 移除，改由 Controller 呼叫 model.command_manager.undo/redo()。
