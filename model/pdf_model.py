import fitz
import tempfile
import os
import shutil
import logging
import math
from typing import List, Tuple, Optional
import pytesseract
from PIL import Image
from pathlib import Path
import uuid
import difflib  # 新增：相似度比對
import io  # 用於 BytesIO 記憶體 stream（文件推薦 in-memory PDF）
import re

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFModel:
    def __init__(self):
        self.doc: fitz.Document = None
        self.temp_dir = None
        self.original_path: str = None
        self.saved_path: str = None  # 追蹤最後儲存的路徑
        self.saved_undo_stack_size: int = 0  # 追蹤儲存時的undo_stack大小
        self.undo_stack = []
        self.redo_stack = []
        # 文字方塊索引：{page_num: [{block_id, rect, text, font, size, color, ...}, ...]}
        self.text_block_index: dict = {}
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

    def _clear_temp_files(self):
        """清理臨時目錄中的所有檔案，但不刪除目錄本身。"""
        if self.temp_dir and Path(self.temp_dir.name).exists():
            for item in Path(self.temp_dir.name).iterdir():
                try:
                    if item.is_file(): item.unlink()
                except OSError as e:
                    logger.warning(f"無法刪除臨時檔案 {item}: {e}")

    def open_pdf(self, path: str):
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
            self._clear_temp_files()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.saved_path = None  # 重置儲存路徑
            self.saved_undo_stack_size = 0  # 重置儲存時的undo_stack大小
            self.text_block_index.clear()  # 清除文字方塊索引
            self.watermark_list.clear()
            self._watermark_modified = False

            # 直接從原始路徑開啟（以便存檔時可選用增量更新）
            self.doc = fitz.open(str(src_path))
            logger.debug(f"成功開啟PDF: {src_path}")
            
            # 建立文字方塊索引
            self._build_text_block_index()
            
            # 將初始狀態寫入臨時檔作為撤銷堆疊的第一個狀態
            temp_initial = Path(self.temp_dir.name) / f"initial_{uuid.uuid4()}.pdf"
            self.doc.save(str(temp_initial), garbage=0)
            self.undo_stack.append(str(temp_initial))
            self.saved_undo_stack_size = len(self.undo_stack)  # 初始化時視為已儲存
            logger.debug(f"初始狀態已儲存: {temp_initial}。撤銷堆疊大小: {len(self.undo_stack)}")
        except PermissionError as e:
            logger.error(f"無權限存取檔案: {str(e)}")
            raise PermissionError(f"無權限存取檔案: {str(e)}")
        except Exception as e:
            logger.error(f"開啟PDF失敗: {str(e)}")
            raise RuntimeError(f"開啟PDF失敗: {str(e)}")

    def _build_text_block_index(self):
        """
        建立文字方塊索引，記錄每個文字方塊的內容和位置
        索引結構：{page_num: [{block_id, rect, text, font, size, color, block_index}, ...]}
        """
        if not self.doc:
            return
        
        self.text_block_index.clear()
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            blocks = page.get_text("dict", flags=0)["blocks"]
            
            page_blocks = []
            for i, block in enumerate(blocks):
                if block.get('type') == 0:  # 文字塊
                    block_rect = fitz.Rect(block["bbox"])
                    
                    # 提取文字內容
                    text_content = []
                    font_name = "helv"
                    font_size = 12.0
                    color_int = 0
                    
                    if block.get("lines"):
                        for line in block["lines"]:
                            for span in line.get("spans", []):
                                text_content.append(span.get("text", ""))
                                # 獲取第一個span的字體資訊
                                if font_name == "helv" and "font" in span:
                                    font_name = span.get("font", "helv")
                                    font_size = span.get("size", 12.0)
                                    color_int = span.get("color", 0)
                    
                    text = "".join(text_content)
                    
                    # 轉換顏色
                    rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
                    color = tuple(c / 255.0 for c in rgb_int)
                    
                    # 從第一行的 dir（方向向量）計算文字旋轉角度（CTM），保留非水平文字方向
                    rotation = 0
                    if block.get("lines"):
                        first_line = block["lines"][0]
                        dir_vec = first_line.get("dir")
                        if dir_vec is not None:
                            rotation = self._rotation_degrees_from_dir(dir_vec)
                    
                    # 生成唯一的 block_id
                    block_id = f"page_{page_num}_block_{i}"
                    
                    page_blocks.append({
                        'block_id': block_id,
                        'rect': block_rect,
                        'layout_rect': block_rect,  # 佈局位置（可移動/擴欄），rect 保留原始 bbox
                        'text': text,
                        'font': font_name,
                        'size': font_size,
                        'color': color,
                        'block_index': i,  # 原始PDF中的塊索引
                        'rotation': rotation  # 文字方向（0/90/180/270），供 insert_htmlbox(rotate=...) 使用
                    })
            
            self.text_block_index[page_num] = page_blocks
            logger.debug(f"頁面 {page_num + 1} 建立了 {len(page_blocks)} 個文字方塊索引")
        
        total_blocks = sum(len(blocks) for blocks in self.text_block_index.values())
        logger.info(f"文字方塊索引建立完成，共 {total_blocks} 個文字方塊")

    def _rotation_degrees_from_dir(self, dir_tuple) -> int:
        """
        從 get_text(\"dict\") 中 line 的 dir 方向向量計算旋轉角度（CTM 文字方向）。
        dir 為 (dx, dy)，例如 (1,0)=水平、(0,1)=垂直向下、(0,-1)=垂直向上。
        回傳 0、90、180、270 其中之一（內部儲存用）。
        """
        if not dir_tuple or len(dir_tuple) < 2:
            return 0
        dx, dy = float(dir_tuple[0]), float(dir_tuple[1])
        # atan2(dy, dx): (1,0)->0°, (0,1)->90°, (-1,0)->180°, (0,-1)->270°
        rad = math.atan2(dy, dx)
        deg = (math.degrees(rad) + 360) % 360
        # 取最接近的 90 的倍數
        nearest = round(deg / 90) * 90
        return int(nearest % 360)

    def _insert_rotate_for_htmlbox(self, rotation: int) -> int:
        """
        insert_htmlbox(rotate=...) 的旋轉方向與 PDF 文字 dir 相反（順時針 vs 逆時針），
        垂直文字若直接傳 90 會變成 180° 反轉。改傳 (360 - rotation) % 360 以對齊原檔方向。
        """
        return (360 - rotation) % 360

    def _vertical_html_rect(self, base_rect: fitz.Rect, text: str, size: float, font_name: str, page_rect: fitz.Rect) -> fitz.Rect:
        """
        垂直文字：估算「需要的 x 方向寬度（列數 × 行高）」。
        以原 rect 高度估算每列可容納字數，再推回列數。
        以「第一行」為基準：向左擴寬（x1 固定、x0 往左），y 保持原位置。
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

        new_x1 = base_rect.x1
        new_x0 = new_x1 - needed_width
        if new_x0 < page_rect.x0:
            new_x0 = page_rect.x0
            new_x1 = new_x0 + needed_width
        return fitz.Rect(new_x0, base_rect.y0, new_x1, base_rect.y1)

    def _y_overlaps(self, rect_a: fitz.Rect, rect_b: fitz.Rect) -> bool:
        return not (rect_a.y1 <= rect_b.y0 or rect_b.y1 <= rect_a.y0)

    def _shift_rect_left(self, rect: fitz.Rect, target_right_x0: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        width = rect.width
        new_x1 = min(rect.x1, target_right_x0 - min_gap)
        shift = rect.x1 - new_x1
        if shift <= 0:
            return rect
        new_x0 = rect.x0 - shift
        if new_x0 < page_rect.x0:
            new_x0 = page_rect.x0
            new_x1 = new_x0 + width
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    def _normalize_text_for_compare(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r'\s+', '', text).lower()

    def _text_fits_in_rect(self, page: fitz.Page, rect: fitz.Rect, expected_text: str) -> bool:
        extracted = page.get_text("text", clip=rect)
        return self._normalize_text_for_compare(expected_text) in self._normalize_text_for_compare(extracted)

    def _binary_shrink_height(self, page: fitz.Page, rect: fitz.Rect, expected_text: str, iterations: int = 7, padding: float = 4.0, min_y1: float | None = None) -> fitz.Rect:
        """
        先用全頁高度 rect 渲染，再二分縮減 y1 找到最小可用高度。
        y0 固定，最後加 padding。
        """
        page_rect = page.rect
        low = rect.y1 if min_y1 is None else max(rect.y0, min_y1)
        high = page_rect.y1
        if low > high:
            low = high
        best_y1 = high

        for _ in range(iterations):
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
        self.text_block_index.clear()
        self.watermark_list.clear()
        if self.temp_dir:
            self.temp_dir.cleanup()
            logger.debug("臨時目錄已清理")
            self.temp_dir = None

    def delete_pages(self, pages: List[int]):
        for page_num in sorted(pages, reverse=True):
            self.doc.delete_page(page_num - 1)
        self._save_state()

    def rotate_pages(self, pages: List[int], degrees: int):
        for page_num in pages:
            page = self.doc[page_num - 1]
            page.set_rotation((page.rotation + degrees) % 360)
        self._save_state()

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
        self._save_state()

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
            self._save_state()
            
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
        self._save_state()

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
        self._save_state()

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
        
        self._save_state()
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
        self._save_state()

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

    def get_text_info_at_point(self, page_num: int, point: fitz.Point) -> Tuple[fitz.Rect, str, str, float, tuple] | None:
        """獲取指定點下方的文字區塊、內容、字型、大小與顏色（轉 0-1 float）"""
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

                    if b["lines"] and b["lines"][0]["spans"]:
                        first_span = b["lines"][0]["spans"][0]
                        font_name = first_span["font"]
                        font_size = first_span["size"]
                        color_int = first_span.get("color", 0)

                    # 轉 0-255 int RGB，再轉 0-1 float（文件：insert_textbox 需 0-1）
                    rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
                    color = tuple(c / 255.0 for c in rgb_int)

                    for l in b["lines"]:
                        for s in l["spans"]:
                            full_text.append(s["text"])
                        full_text.append("\n")
                    
                    text_content = "".join(full_text).rstrip("\n")

                    logger.debug(f"找到文字區塊: {rect}, 字型: {font_name}, 大小: {font_size}, 顏色: {color} (from {color_int})")
                    return rect, text_content, font_name, font_size, color
        return None

    def _convert_text_to_html(self, text: str, font_size: int, color: tuple) -> str:
        """
        將混合文本轉換為帶有字體樣式的簡單 HTML，並正確處理空格。
        """
        html_parts = []
        if not text:
            return ""

        # 正則表達式：匹配連續的CJK字符、連續的英數字元與常見標點、空格或換行符（保留句點等）
        pattern = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff]+|[a-zA-Z0-9.,!?;:\'"\-]+| +|\n)')
        parts = pattern.findall(text)

        for part in parts:
            if part == '\n':
                html_parts.append('<br>')
            elif part.isspace():
                # 空格包在 span 內並用 helv 字體，避免 insert_htmlbox 在旋轉/窄框下把 &nbsp; 壓成零寬
                # 同時在每個空格後加入 <wbr>，提供可斷行點但保留 NBSP 寬度
                nbsp_wbr = ''.join(['&#160;<wbr>'] * len(part))  # U+00A0 non-breaking space
                html_parts.append(f'<span style="font-family: helv;">{nbsp_wbr}</span>')
            elif re.match(r'[\u4e00-\u9fff\u3040-\u30ff]+', part):
                # 中文字符
                html_parts.append(f'<span style="font-family: cjk;">{part}</span>')
            else: # 默認為英數字元
                # 英文字符
                html_parts.append(f'<span style="font-family: helv;">{part}</span>')
            
        return "".join(html_parts)

    def clone_page(self, page_num: int) -> fitz.Document:
        """優化單頁快照：用 insert_pdf + save(stream, garbage=0) 記憶體提取（文件推薦，防空 bytes）"""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        
        # 新 doc + 插入單頁
        clone_doc = fitz.open()
        clone_doc.insert_pdf(self.doc, from_page=page_num - 1, to_page=page_num - 1)
        
        # --- 策略修改：棄用 tobytes()，改用 save() 存入記憶體流 ---
        # 1. 創建一個記憶體流
        stream = io.BytesIO()
        # 2. 明確指定 garbage=0 (int) 存入流
        clone_doc.save(stream, garbage=0)
        # 3. 從流中獲取 bytes
        page_bytes = stream.getvalue()
        # ---------------------------------------------------------
        
        clone_doc.close()
        
        if not page_bytes:
            raise RuntimeError(f"頁面 {page_num} 提取 bytes 失敗 (空 bytes)")
        
        final_clone = fitz.open("pdf", page_bytes)  # 從 bytes 開新 doc
        logger.debug(f"成功 clone 頁面 {page_num} 到新 doc (頁數: {len(final_clone)}, bytes: {len(page_bytes)})")
        return final_clone

    def _get_text_blocks_in_rect(self, page_num: int, rect: fitz.Rect) -> List[dict]:
        """獲取矩形區域內的所有文字塊"""
        page = self.doc[page_num - 1]
        blocks = page.get_text("dict", flags=0)["blocks"]
        
        text_blocks = []
        for i, block in enumerate(blocks):
            if block.get('type') == 0:  # 文字塊
                block_rect = fitz.Rect(block["bbox"])
                if block_rect.intersects(rect):
                    text_content = []
                    words = []
                    rotation = 0
                    lines_list = block.get("lines", [])
                    if lines_list and lines_list[0].get("dir") is not None:
                        rotation = self._rotation_degrees_from_dir(lines_list[0]["dir"])
                    for line in lines_list:
                        for span in line.get("spans", []):
                            text_content.append(span.get("text", ""))
                            # 收集單詞位置（如果可用）
                            if "bbox" in span:
                                words.append(span["bbox"])
                    
                    text_blocks.append({
                        'rect': block_rect,
                        'text': "".join(text_content),
                        'words': words,
                        'block_index': i,
                        'rotation': rotation
                    })
        
        return text_blocks
    
    def _find_target_text_block(self, page_num: int, rect: fitz.Rect, 
                                original_text: str = None) -> dict:
        """精確定位要編輯的目標文字塊"""
        text_blocks = self._get_text_blocks_in_rect(page_num, rect)
        
        if not text_blocks:
            logger.debug(f"在矩形 {rect} 中未找到任何文字塊，使用原始矩形")
            return None
        
        # 如果提供了原始文字，使用內容匹配
        if original_text:
            original_text_clean = "".join(original_text.strip().split())
            
            best_match = None
            best_similarity = 0.0
            
            for block in text_blocks:
                block_text_clean = "".join(block['text'].strip().split())
                similarity = difflib.SequenceMatcher(
                    None, original_text_clean, block_text_clean
                ).ratio()
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = block
            
            if best_match and best_similarity > 0.5:
                logger.debug(f"找到匹配文字塊，相似度: {best_similarity:.2f}")
                return best_match
        
        # 選擇與矩形中心最接近的文字塊
        rect_center = fitz.Point(rect.x0 + rect.width/2, rect.y0 + rect.height/2)
        best_block = None
        min_distance = float('inf')
        
        for block in text_blocks:
            block_center = fitz.Point(
                block['rect'].x0 + block['rect'].width/2,
                block['rect'].y0 + block['rect'].height/2
            )
            distance = abs(block_center.x - rect_center.x) + abs(block_center.y - rect_center.y)
            
            if distance < min_distance:
                min_distance = distance
                best_block = block
        
        return best_block
    
    def _get_precise_text_bounds(self, page_num: int, text_block: dict) -> fitz.Rect:
        """獲取文字塊的精確邊界"""
        if text_block and text_block.get('words'):
            # 使用單詞位置計算精確邊界
            try:
                x0 = min(word[0] for word in text_block['words'] if len(word) >= 4)
                y0 = min(word[1] for word in text_block['words'] if len(word) >= 4)
                x1 = max(word[2] for word in text_block['words'] if len(word) >= 4)
                y1 = max(word[3] for word in text_block['words'] if len(word) >= 4)
                return fitz.Rect(x0, y0, x1, y1)
            except (ValueError, IndexError):
                pass
        
        # 回退到文字塊邊界
        if text_block:
            return text_block['rect']
        else:
            # 如果沒有文字塊，返回一個空矩形（這不應該發生，但作為安全措施）
            logger.warning("無法獲取文字塊邊界，返回空矩形")
            return fitz.Rect(0, 0, 0, 0)
    
    def _find_text_block_by_id(self, page_num: int, block_id: str) -> dict:
        """根據 block_id 查找文字方塊
        
        Args:
            page_num: 頁碼（1-based）
            block_id: 文字方塊的唯一標識符
        """
        page_idx = page_num - 1  # 轉換為 0-based
        if page_idx not in self.text_block_index:
            return None
        for block in self.text_block_index[page_idx]:
            if block['block_id'] == block_id:
                return block
        return None
    
    def _find_text_block_by_rect(self, page_num: int, rect: fitz.Rect, 
                                 original_text: str = None) -> dict:
        """
        根據矩形和文字內容查找文字方塊（使用索引）
        優先使用索引，如果找不到則回退到動態檢測
        """
        page_idx = page_num - 1  # 轉換為 0-based
        
        if page_idx not in self.text_block_index:
            logger.warning(f"頁面 {page_num} 沒有索引，使用動態檢測")
            return self._find_target_text_block(page_num, rect, original_text)
        
        # 在索引中查找
        candidates = []
        for block in self.text_block_index[page_idx]:
            block_rect = block.get('layout_rect', block['rect'])
            if block_rect.intersects(rect):
                candidates.append(block)
        
        if not candidates:
            logger.debug(f"索引中未找到匹配的文字方塊，使用動態檢測")
            return self._find_target_text_block(page_num, rect, original_text)
        
        # 如果提供了原始文字，使用內容匹配
        if original_text:
            original_text_clean = "".join(original_text.strip().split())
            
            best_match = None
            best_similarity = 0.0
            
            for block in candidates:
                block_text_clean = "".join(block['text'].strip().split())
                similarity = difflib.SequenceMatcher(
                    None, original_text_clean, block_text_clean
                ).ratio()
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = block
            
            if best_match and best_similarity > 0.5:
                logger.debug(f"在索引中找到匹配文字方塊，相似度: {best_similarity:.2f}, block_id: {best_match['block_id']}")
                return best_match
        
        # 選擇與矩形中心最接近的文字方塊
        rect_center = fitz.Point(rect.x0 + rect.width/2, rect.y0 + rect.height/2)
        best_block = None
        min_distance = float('inf')
        
        for block in candidates:
            block_rect = block.get('layout_rect', block['rect'])
            block_center = fitz.Point(
                block_rect.x0 + block_rect.width/2,
                block_rect.y0 + block_rect.height/2
            )
            distance = abs(block_center.x - rect_center.x) + abs(block_center.y - rect_center.y)
            
            if distance < min_distance:
                min_distance = distance
                best_block = block
        
        if best_block:
            logger.debug(f"在索引中找到最接近的文字方塊，block_id: {best_block['block_id']}")
        
        return best_block

    def _render_text_blocks_from_index(self, page_num: int) -> fitz.Document:
        """
        從索引渲染所有文字方塊到PDF頁面
        
        Args:
            page_num: 頁碼（1-based）
        
        Returns:
            包含渲染後頁面的臨時文檔
        """
        page_idx = page_num - 1
        if page_idx not in self.text_block_index:
            logger.warning(f"頁面 {page_num} 沒有索引，無法渲染")
            return None
        
        # 克隆頁面
        temp_doc = self.clone_page(page_num)
        temp_page = temp_doc[0]
        
        # 清除頁面上的所有文字塊（使用 redaction）
        page_rect = temp_page.rect
        blocks = temp_page.get_text("dict", flags=0)["blocks"]
        
        # 清除所有文字塊
        for block in blocks:
            if block.get('type') == 0:  # 文字塊
                block_rect = fitz.Rect(block["bbox"])
                temp_page.add_redact_annot(block_rect)
        
        temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        logger.debug(f"已清除頁面 {page_num} 上的所有文字塊")
        
        # 從索引渲染所有文字方塊
        page_width = temp_page.rect.width
        margin = 15
        
        for block in self.text_block_index[page_idx]:
            block_rect = block.get('layout_rect', block['rect'])
            text = block['text']
            font = block['font']
            size = block['size']
            color = block['color']
            rotation = block.get('rotation', 0)
            
            if not text.strip():
                continue  # 跳過空文字
            
            # 準備HTML內容
            html_content = self._convert_text_to_html(text, int(size), color)
            
            # 定義CSS樣式
            css = f"""
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
            
            # 全部用 HTML 渲染。垂直：以列數估算所需寬度，對稱擴展 x；水平維持原邏輯。
            insert_rotate = self._insert_rotate_for_htmlbox(rotation)
            if rotation in (90, 270):
                base_rect = self._vertical_html_rect(block_rect, text, size, font, temp_page.rect)
                base_y1 = base_rect.y1
                html_rect = fitz.Rect(base_rect.x0, block_rect.y0, base_rect.x1, temp_page.rect.y1)
            else:
                max_allowed_width = page_width - block_rect.x0 - margin
                line_count = max(1, len(text.split('\n')))
                estimated_height = line_count * size * 2 + size * 2
                base_rect = fitz.Rect(
                    block_rect.x0,
                    block_rect.y0,
                    block_rect.x0 + max_allowed_width,
                    block_rect.y0 + max(block_rect.height, estimated_height)
                )
                html_rect = fitz.Rect(base_rect.x0, base_rect.y0, base_rect.x1, temp_page.rect.y1)
            
            # 垂直文字：先全頁高度渲染，再二分縮減 y1
            try:
                if rotation in (90, 270):
                    full_rect = html_rect
                    spare_height, scale_used = temp_page.insert_htmlbox(
                        full_rect, html_content, css=css, rotate=insert_rotate, scale_low=1
                    )
                    if spare_height < 0:
                        temp_page.insert_htmlbox(
                            full_rect, html_content, css=css, rotate=insert_rotate, scale_low=0
                        )
                    if not self._text_fits_in_rect(temp_page, full_rect, text):
                        raise RuntimeError(
                            f"渲染文字方塊 {block['block_id']} 失敗：全頁高度仍裁切。"
                        )
                    padding = self._calc_vertical_padding(size)
                    html_rect = self._binary_shrink_height(temp_page, full_rect, text, iterations=7, padding=padding, min_y1=base_y1)
                    temp_page.add_redact_annot(full_rect)
                    temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                    spare_height, scale_used = temp_page.insert_htmlbox(
                        html_rect, html_content, css=css, rotate=insert_rotate, scale_low=1
                    )
                    if spare_height < 0:
                        temp_page.insert_htmlbox(
                            html_rect, html_content, css=css, rotate=insert_rotate, scale_low=0
                        )
                    logger.debug(f"已渲染文字方塊 {block['block_id']}: '{text[:30]}...' (rotation={rotation}, insert_rotate={insert_rotate})")
                else:
                    spare_height, scale_used = temp_page.insert_htmlbox(
                        html_rect, html_content, css=css, rotate=insert_rotate, scale_low=1
                    )
                    if spare_height < 0:
                        logger.error(
                            f"渲染文字方塊 {block['block_id']} 失敗：字級 {size}pt 下無法完整塞入 (spare_height={spare_height})，不縮小字級故未繪製。"
                        )
                    else:
                        logger.debug(f"已渲染文字方塊 {block['block_id']}: '{text[:30]}...' (rotation={rotation}, insert_rotate={insert_rotate})")
            except Exception as e:
                logger.warning(f"渲染文字方塊 {block['block_id']} 失敗: {e}")
        
        # 注意：PyMuPDF 的 Page 物件沒有 update() 方法
        # insert_htmlbox 和 apply_redactions 會自動更新頁面
        return temp_doc

    def edit_text(self, page_num: int, rect: fitz.Rect, new_text: str, font: str = "helv", size: int = 12, color: tuple = (0.0, 0.0, 0.0), original_text: str = None):
        """
        編輯文字（模仿 Stirling-PDF：只清除目標文字框，不影響其他文字）
        
        Args:
            page_num: 頁碼（1-based）
            rect: 粗略的矩形區域
            new_text: 新文字內容
            font: 字體名稱
            size: 字體大小
            color: 文字顏色 (0-1 float tuple)
            original_text: 原始文字內容（可選，用於精確定位）
        """
        if not new_text.strip():
            logger.warning("文字內容為空，跳過編輯")
            return

        # --- 步驟 1: 使用索引查找目標文字方塊 ---
        target_block = self._find_text_block_by_rect(page_num, rect, original_text)
        
        if not target_block:
            logger.warning(f"無法找到目標文字方塊，使用回退方法")
            # 回退到原來的編輯方式
            return
        
        block_id = target_block['block_id']
        page_idx = page_num - 1
        target_layout_rect = target_block.get('layout_rect', target_block['rect'])
        redact_rect = target_layout_rect
        
        # --- 步驟 2: 更新索引中的文字內容 ---
        if page_idx in self.text_block_index:
            for block in self.text_block_index[page_idx]:
                if block['block_id'] == block_id:
                    # 更新索引中的文字內容
                    old_text = block['text']
                    block['text'] = new_text
                    block['font'] = font
                    block['size'] = size
                    block['color'] = color
                    logger.debug(f"已更新索引中的文字方塊 {block_id}: '{old_text[:30]}...' -> '{new_text[:30]}...'")
                    break
        
        # --- 步驟 3: 只清除目標文字框，然後重新渲染該文字框 ---
        success_snapshot = None
        try:
            # 克隆頁面
            temp_doc = self.clone_page(page_num)
            temp_page = temp_doc[0]
            
            # --- 計算目標文字框位置 ---
            rotation = target_block.get('rotation', 0)
            page_width = temp_page.rect.width
            margin = 15
            if rotation in (90, 270):
                base_rect = self._vertical_html_rect(target_layout_rect, new_text, size, font, temp_page.rect)
                base_y1 = base_rect.y1
                html_rect = fitz.Rect(base_rect.x0, target_layout_rect.y0, base_rect.x1, temp_page.rect.y1)
            else:
                max_allowed_width = page_width - target_layout_rect.x0 - margin
                line_count = max(1, len(new_text.split('\n')))
                estimated_height = line_count * size * 2 + size * 2
                base_rect = fitz.Rect(
                    target_layout_rect.x0,
                    target_layout_rect.y0,
                    target_layout_rect.x0 + max_allowed_width,
                    target_layout_rect.y0 + max(target_layout_rect.height, estimated_height)
                )
                base_y1 = base_rect.y1
                html_rect = fitz.Rect(base_rect.x0, base_rect.y0, base_rect.x1, temp_page.rect.y1)

            full_rect = html_rect

            # --- 欄位碰撞檢測 + 左移連動 + 全頁高度起步 + 二分縮減 ---
            old_layout_rects = {block_id: target_layout_rect}
            moved_blocks = []
            threshold = 4.0
            if rotation in (90, 270) and html_rect.x0 < target_layout_rect.x0:
                for block in self.text_block_index[page_idx]:
                    if block['block_id'] == block_id:
                        continue
                    if block.get('rotation', 0) not in (90, 270):
                        continue
                    other_rect = block.get('layout_rect', block['rect'])
                    if not self._y_overlaps(other_rect, target_layout_rect):
                        continue
                    if other_rect.x1 > (html_rect.x0 - threshold) and other_rect.x0 < target_layout_rect.x0:
                        moved_blocks.append(block)

                moved_blocks.sort(key=lambda b: b.get('layout_rect', b['rect']).x1, reverse=True)
                next_right_x0 = html_rect.x0
                for block in moved_blocks:
                    other_rect = block.get('layout_rect', block['rect'])
                    old_layout_rects.setdefault(block['block_id'], other_rect)
                    new_rect = self._shift_rect_left(other_rect, next_right_x0, threshold, temp_page.rect)
                    block['layout_rect'] = new_rect
                    next_right_x0 = new_rect.x0

            target_block['layout_rect'] = html_rect

            # --- 清除舊位置 ---
            for old_rect in old_layout_rects.values():
                temp_page.add_redact_annot(old_rect)
            temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            logger.debug(f"已清除文字框位置: {[str(r) for r in old_layout_rects.values()]}")

            # --- 重繪（目標 + 被移動欄位）---
            affected_blocks = moved_blocks + [target_block]
            affected_blocks = sorted(affected_blocks, key=lambda b: b.get('layout_rect', b['rect']).x0)
            for block in affected_blocks:
                block_rect = block.get('layout_rect', block['rect'])
                block_text = block['text']
                block_size = block['size']
                block_color = block['color']
                block_rotation = block.get('rotation', 0)
                insert_rotate = self._insert_rotate_for_htmlbox(block_rotation)

                if not block_text.strip():
                    continue

                html_content = self._convert_text_to_html(block_text, int(block_size), block_color)
                css = f"""
                    span {{
                        font-size: {block_size}pt;
                        white-space: pre-wrap;
                        word-break: break-all;
                        overflow-wrap: anywhere;
                        color: rgb({int(block_color[0]*255)}, {int(block_color[1]*255)}, {int(block_color[2]*255)});
                    }}
                    .helv {{ font-family: helv; }}
                    .cjk {{ font-family: cjk; }}
                """

                spare_height, scale_used = temp_page.insert_htmlbox(
                    block_rect, html_content, css=css, rotate=insert_rotate, scale_low=1
                )
                if spare_height < 0:
                    if block_rotation in (90, 270):
                        spare_height, scale_used = temp_page.insert_htmlbox(
                            block_rect, html_content, css=css, rotate=insert_rotate, scale_low=0
                        )
                    if spare_height < 0 and block_rotation not in (90, 270):
                        fail_reason = (
                            f"文字框內容在字級 {block_size}pt 下無法完整塞入 (spare_height={spare_height})，不縮小字級故未繪製。"
                            "（insert_htmlbox 必須傳入 rect；若需「只算位置再放文字」可改為 insert_text + morph，但不支援 HTML。）"
                        )
                        logger.error(f"文字框 {block['block_id']} 渲染失敗：{fail_reason}")
                        raise RuntimeError(fail_reason)

                if block['block_id'] == block_id:
                    logger.debug(
                        f"已重新渲染目標文字框 {block_id}: '{new_text[:30]}...' "
                        f"(rotation={block_rotation}, insert_rotate={insert_rotate}, scale_used={scale_used})"
                    )

            if rotation in (90, 270):
                if not self._text_fits_in_rect(temp_page, full_rect, new_text):
                    raise RuntimeError(
                        f"目標文字框 {block_id} 渲染失敗：全頁高度仍裁切。"
                    )
                padding = self._calc_vertical_padding(size)
                html_rect = self._binary_shrink_height(temp_page, full_rect, new_text, iterations=7, padding=padding, min_y1=base_y1)
                target_block['layout_rect'] = html_rect
                temp_page.add_redact_annot(full_rect)
                temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                spare_height, scale_used = temp_page.insert_htmlbox(
                    html_rect, html_content, css=css, rotate=insert_rotate, scale_low=1
                )
                if spare_height < 0:
                    spare_height, scale_used = temp_page.insert_htmlbox(
                        html_rect, html_content, css=css, rotate=insert_rotate, scale_low=0
                    )
            else:
                html_rect = self._binary_shrink_height(temp_page, full_rect, new_text, iterations=7, padding=4.0, min_y1=base_y1)
                target_block['layout_rect'] = html_rect
            
            success_snapshot = temp_doc
            
            # --- 步驟 4: 應用更改並更新索引中的 rect（若已擴展文字框）---
            if success_snapshot:
                self.doc.delete_page(page_num - 1)
                self.doc.insert_pdf(success_snapshot, from_page=0, to_page=0, start_at=page_num - 1)
                if page_idx in self.text_block_index:
                    for block in self.text_block_index[page_idx]:
                        if block['block_id'] == block_id:
                            # 垂直文字保持原始 rect，避免逐次編輯造成 bbox 漂移
                            if rotation not in (90, 270):
                                block['rect'] = html_rect
                                block['layout_rect'] = html_rect
                            break
                logger.debug(f"編輯文字成功: 頁面 {page_num}, 文字='{new_text[:50]}...'")
            else:
                raise RuntimeError("未知錯誤，未能生成成功快照")

        except Exception as render_e:
            logger.error(f"編輯文字失敗，已回滾: {render_e}")
            # 回滾索引更改
            if page_idx in self.text_block_index:
                for block in self.text_block_index[page_idx]:
                    if block['block_id'] == block_id:
                        # 恢復原來的文字（如果可能）
                        block['text'] = original_text if original_text else target_block['text']
                        block['font'] = target_block['font']
                        block['size'] = target_block['size']
                        block['color'] = target_block['color']
                        break
                if 'old_layout_rects' in locals():
                    for block in self.text_block_index[page_idx]:
                        if block['block_id'] in old_layout_rects:
                            block['layout_rect'] = old_layout_rects[block['block_id']]
            raise # 重新拋出錯誤，讓 Controller 捕捉並顯示
        finally:
            # --- 清理 ---
            if success_snapshot and not success_snapshot.is_closed:
                success_snapshot.close()

        # --- 儲存狀態 ---
        self._save_state()

    def _save_state(self):
        """儲存狀態到undo堆疊"""
        if not self.doc:
            return

        # 為新狀態創建一個唯一的臨時檔案路徑
        new_path = Path(self.temp_dir.name) / f"state_{uuid.uuid4()}.pdf"

        # 將當前文件狀態保存到新路徑
        self.doc.save(str(new_path), garbage=0)

        # 將新狀態的路徑推入撤銷堆疊
        self.undo_stack.append(str(new_path))

        # 清理重做堆疊中的舊狀態檔案
        for path in self.redo_stack:
            try:
                os.unlink(path)
            except OSError as e:
                logger.warning(f"無法刪除重做狀態檔案 {path}: {e}")
        self.redo_stack.clear()
        logger.debug(f"狀態已儲存至 {new_path}。撤銷堆疊大小: {len(self.undo_stack)}")
    
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
        self.saved_undo_stack_size = len(self.undo_stack)
        self._watermark_modified = False
    
    def has_unsaved_changes(self) -> bool:
        """檢查是否有未儲存的變更
        
        比較當前undo_stack大小與儲存時的大小，如果不同則表示有未儲存的變更。
        浮水印的增刪改也會視為未儲存變更。
        """
        if not self.doc:
            return False
        if getattr(self, '_watermark_modified', False):
            return True
        if self.saved_path is None:
            return len(self.undo_stack) > 1
        return len(self.undo_stack) != self.saved_undo_stack_size

    def undo(self):
        if len(self.undo_stack) > 1:
            current_path = self.undo_stack.pop()
            self.redo_stack.append(current_path)
            prev_path = self.undo_stack[-1]
            self.doc.close()
            self.doc = fitz.open(prev_path)
            logger.debug(f"撤銷至 {prev_path}。重做堆疊大小: {len(self.redo_stack)}")

    def redo(self):
        if self.redo_stack:
            next_path = self.redo_stack.pop()
            self.undo_stack.append(next_path)
            self.doc.close()
            self.doc = fitz.open(next_path)
            logger.debug(f"重做至 {next_path}。撤銷堆疊大小: {len(self.undo_stack)}")
