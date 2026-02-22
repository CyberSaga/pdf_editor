import fitz
import math
import re
import difflib
import logging
from dataclasses import dataclass, field
from typing import Optional

# 模組級正則預編譯：供文字比對用，與 pdf_model.py 保持一致
_RE_WS_STRIP = re.compile(r'\s+')

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 模組層級工具函式
# ──────────────────────────────────────────────────────────────────────────────

def rotation_degrees_from_dir(dir_tuple) -> int:
    """
    從 get_text("dict") 中 line 的 dir 方向向量計算旋轉角度（CTM 文字方向）。
    dir 為 (dx, dy)，例如 (1,0)=水平、(0,1)=垂直向下、(0,-1)=垂直向上。
    回傳 0、90、180、270 其中之一（內部儲存用）。

    此函式為模組層級獨立函式，供 TextBlockManager.build_index() 呼叫，
    同時可供 pdf_model.py 在 Phase 3 重構後共用，取代原有的 instance method。
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


# ──────────────────────────────────────────────────────────────────────────────
# TextBlock dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TextBlock:
    """
    代表 PDF 頁面上一個文字方塊的完整狀態。

    欄位說明：
      block_id           : 唯一識別碼，格式 "page_{page_num}_block_{i}"（0-based）
      page_num           : 0-based 頁面索引（與 fitz.Document 內部索引一致）
      rect               : 從 PDF 解析的原始 bbox，識別用，原則上不因編輯而改變
      layout_rect        : 實際渲染位置，可因文字擴欄/移位而與 rect 不同
      text               : 文字內容（編輯後會更新）
      font               : 字型名稱
      size               : 字型大小（pt）
      color              : 文字顏色 (r, g, b)，各分量 0.0~1.0；Phase 3 可細化為 tuple[float, float, float]
      rotation           : 文字旋轉角度：0 / 90 / 180 / 270
      original_span_count: 開檔時的原始 span 數量，供插入後完整性驗證用
      is_vertical        : 衍生欄位，由 rotation 決定，透過 __post_init__ 設定；
                           default=False 確保 __post_init__ 執行失敗時仍有安全初值
    """
    # --- 必填欄位（無預設值，影響 __init__ 參數順序）---
    block_id: str
    page_num: int                   # 0-based 頁面索引
    rect: fitz.Rect                 # 原始 bbox（識別用，不因編輯而改變）
    layout_rect: fitz.Rect          # 實際佈局位置（可移動/擴欄）
    text: str                       # 文字內容
    font: str                       # 字型名稱
    size: float                     # 字型大小（pt）
    color: tuple                    # 文字顏色 (r, g, b)，各分量 0.0~1.0
    rotation: int                   # 文字旋轉角度：0 / 90 / 180 / 270

    # --- 有預設值的欄位 ---
    original_span_count: int = 0    # 開檔時的原始 span 數量

    # --- 衍生欄位（不透過 __init__ 設定，由 __post_init__ 計算）---
    # [修正] default=False：確保 __post_init__ 執行失敗或被跳過時有安全初值，
    #        避免存取時出現 AttributeError
    is_vertical: bool = field(init=False, default=False)

    def __post_init__(self):
        # rotation in (90, 270) 表示垂直文字方向
        self.is_vertical = self.rotation in (90, 270)


# ──────────────────────────────────────────────────────────────────────────────
# TextBlockManager
# ──────────────────────────────────────────────────────────────────────────────

class TextBlockManager:
    """
    管理 PDF 所有頁面的 TextBlock 索引。

    設計原則：
    - 開檔時呼叫 build_index() 一次性建立全文件索引。
    - 編輯後只呼叫 update_block() 或 rebuild_page()，避免重建整個索引。
    - 內部以 0-based page_num 為 key（與 TextBlock.page_num 一致）。
      呼叫端若使用 1-based 頁碼，需自行減 1 後傳入。

    整合說明（Phase 3）：
    - PDFModel 的 self.text_block_index 將由 self.block_manager（本類別實例）取代。
    - _build_text_block_index() 邏輯已移入 build_index() / _build_page_index()。
    - _find_text_block_by_rect() 和 _find_target_text_block() 邏輯已合併至 find_by_rect()。
    - _find_text_block_by_id() 邏輯已移入 find_by_id()。
    """

    def __init__(self):
        # 主索引：{page_num_0based: [TextBlock, ...]}
        self._index: dict[int, list[TextBlock]] = {}

    # ──────────────────────────────────────────────────────────────────────────
    # 索引建立
    # ──────────────────────────────────────────────────────────────────────────

    def build_index(self, doc: fitz.Document) -> None:
        """
        掃描整份文件，為所有頁面建立 TextBlock 索引。
        邏輯移植自 pdf_model.py 的 _build_text_block_index()，改用 TextBlock 建構。
        開檔（open_pdf）時呼叫一次；關閉前無需再呼叫。
        """
        self._index.clear()

        for page_num in range(len(doc)):
            page = doc[page_num]
            self._build_page_index(page_num, page)

        total = sum(len(blocks) for blocks in self._index.values())
        logger.info(f"TextBlockManager 索引建立完成，共 {total} 個文字方塊")

    def rebuild_page(self, page_num: int, doc: fitz.Document) -> None:
        """
        重建指定頁（0-based）的索引。
        用於 undo/redo 還原頁面後，只需重建該頁而不是整份文件，避免效能浪費。

        Args:
            page_num: 0-based 頁面索引
            doc     : 已更新的 fitz.Document
        """
        if page_num < 0 or page_num >= len(doc):
            logger.warning(f"rebuild_page: 無效的頁碼 {page_num}，跳過")
            return

        page = doc[page_num]
        self._build_page_index(page_num, page)
        logger.debug(
            f"已重建頁面 {page_num + 1} 的索引，"
            f"共 {len(self._index.get(page_num, []))} 個文字方塊"
        )

    def _build_page_index(self, page_num: int, page: fitz.Page) -> None:
        """
        解析單一 fitz.Page 並建立 TextBlock 列表，存入 self._index[page_num]。
        為 build_index() 與 rebuild_page() 共用的核心邏輯。

        [修正] 改用 _parse_block() 輔助方法，消除與 _dynamic_scan() 的程式碼重複（DRY）。
        """
        blocks_raw = page.get_text("dict", flags=0)["blocks"]
        page_blocks: list[TextBlock] = []

        for i, block in enumerate(blocks_raw):
            tb = self._parse_block(page_num, i, block)
            if tb is not None:
                page_blocks.append(tb)

        self._index[page_num] = page_blocks
        logger.debug(f"頁面 {page_num + 1} 建立了 {len(page_blocks)} 個 TextBlock 索引")

    # ──────────────────────────────────────────────────────────────────────────
    # 索引查詢
    # ──────────────────────────────────────────────────────────────────────────

    def get_blocks(self, page_num: int) -> list[TextBlock]:
        """取得指定頁（0-based）的所有 TextBlock。若頁面不存在則回傳空列表。"""
        return self._index.get(page_num, [])

    def find_by_id(self, page_num: int, block_id: str) -> Optional[TextBlock]:
        """
        根據 block_id 查找 TextBlock（O(n)，n = 頁面 block 數）。
        對應原 pdf_model.py 的 _find_text_block_by_id()。

        Args:
            page_num: 0-based 頁面索引
            block_id: 目標 block_id（格式 "page_{page_num}_block_{i}"）
        """
        for block in self._index.get(page_num, []):
            if block.block_id == block_id:
                return block
        return None

    def find_by_rect(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: Optional[str] = None,
        doc: Optional[fitz.Document] = None,
    ) -> Optional[TextBlock]:
        """
        根據矩形與原始文字內容定位最匹配的 TextBlock。
        合併了原 pdf_model.py 的 _find_text_block_by_rect() 與
        _find_target_text_block() 的邏輯，消除重複。

        查找策略（依序）：
          1. 使用索引找出與 rect 相交（intersects）的候選 TextBlock。
          2. 若提供 original_text，用相似度匹配
             （含長度比快速預檢 + 包含關係短路）。
          3. 若無 original_text 或相似度比對未命中，
             回退到「layout_rect 中心距 rect 中心最近」的 block。
          4. 若索引無候選且有傳入 doc，動態掃描該頁（保護網，
             索引過舊或首次查詢時使用）。

        Args:
            page_num     : 0-based 頁面索引
            rect         : 使用者點擊或框選的粗略矩形
            original_text: 點擊時擷取的原始文字（可選，提升定位精度）
            doc          : fitz.Document（可選），索引無候選時用於動態掃描
        """
        candidates = [
            b for b in self._index.get(page_num, [])
            if b.layout_rect.intersects(rect)
        ]

        # 若索引無候選，嘗試動態掃描（保護網）
        if not candidates:
            if doc is not None:
                logger.debug(
                    f"索引中找不到候選 block，改為動態掃描頁面 {page_num + 1}"
                )
                return self._dynamic_scan(page_num, rect, original_text, doc)
            logger.debug(
                f"索引中找不到候選 block，頁面 {page_num + 1} 矩形 {rect}"
            )
            return None

        # --- 若有原始文字，用相似度匹配 ---
        if original_text and original_text.strip():
            result = self._match_by_text(candidates, original_text)
            if result is not None:
                return result

        # --- fallback：選最接近 rect 中心的 block ---
        return self._closest_to_center(candidates, rect)

    # ──────────────────────────────────────────────────────────────────────────
    # 索引更新
    # ──────────────────────────────────────────────────────────────────────────

    def update_block(self, block: TextBlock, **kwargs) -> None:
        """
        更新 TextBlock 的欄位值（就地修改）。
        常用於 edit_text 完成後更新 text/font/size/color/layout_rect 等屬性。

        注意：若 rotation 有被更新，is_vertical 會自動同步（衍生欄位）。

        用法範例：
            self.block_manager.update_block(
                target_block,
                text=new_text,
                font=new_font,
                size=new_size,
                color=new_color,
                layout_rect=new_layout_rect,
            )
        """
        for key, value in kwargs.items():
            if hasattr(block, key):
                setattr(block, key, value)
            else:
                logger.warning(f"TextBlock 沒有屬性 '{key}'，跳過更新")

        # 若 rotation 有被更新，同步衍生欄位
        if 'rotation' in kwargs:
            block.is_vertical = block.rotation in (90, 270)

    def clear(self) -> None:
        """清空全部索引（關閉 PDF 或開啟新文件時呼叫）。"""
        self._index.clear()
        logger.debug("TextBlockManager 索引已清空")

    # ──────────────────────────────────────────────────────────────────────────
    # 私有輔助方法
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_block(
        self,
        page_num: int,
        raw_index: int,
        block: dict,
    ) -> Optional[TextBlock]:
        """
        將原始 block dict 解析為 TextBlock。
        若 block 非文字塊（type != 0）則回傳 None。

        [修正] 提取為獨立輔助方法，供 _build_page_index() 和 _dynamic_scan() 共用，
        消除原本 35 行的程式碼重複（DRY 違反修正）。

        顏色轉換、旋轉計算、字型擷取邏輯與原 _build_text_block_index() 完全對齊，
        並包含 original_span_count 統計（供 Phase 3 插入後完整性驗證）。

        Args:
            page_num  : 0-based 頁面索引（用於建構 block_id）
            raw_index : block 在 get_text("dict")["blocks"] 中的原始索引
                        （含圖片塊，與 pdf_model.py 原邏輯一致）
            block     : get_text("dict") 回傳的原始 block dict
        """
        if block.get('type') != 0:  # 只處理文字塊（type=0），略過圖片塊
            return None

        block_rect = fitz.Rect(block["bbox"])

        # --- 提取文字內容、字型資訊、span 數量 ---
        text_parts: list[str] = []
        font_name = "helv"
        font_size = 12.0
        color_int = 0
        span_count = 0

        if block.get("lines"):
            for line in block["lines"]:
                for span in line.get("spans", []):
                    text_parts.append(span.get("text", ""))
                    span_count += 1
                    # 取第一個有效 span 的字型資訊（與原邏輯一致）
                    if font_name == "helv" and "font" in span:
                        font_name = span.get("font", "helv")
                        font_size = span.get("size", 12.0)
                        color_int = span.get("color", 0)

        text = "".join(text_parts)

        # --- 顏色轉換：sRGB int → (r, g, b) float tuple ---
        rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
        color = tuple(c / 255.0 for c in rgb_int)

        # --- 旋轉角度：從第一行的 dir 向量計算（與原邏輯一致）---
        rotation = 0
        if block.get("lines"):
            first_line = block["lines"][0]
            dir_vec = first_line.get("dir")
            if dir_vec is not None:
                rotation = rotation_degrees_from_dir(dir_vec)

        return TextBlock(
            block_id=f"page_{page_num}_block_{raw_index}",
            page_num=page_num,
            rect=fitz.Rect(block_rect),         # 存副本，識別用，不應被外部改動
            layout_rect=fitz.Rect(block_rect),  # 初始與 rect 相同，編輯後可變
            text=text,
            font=font_name,
            size=font_size,
            color=color,
            rotation=rotation,
            original_span_count=span_count,
        )

    def _match_by_text(
        self,
        candidates: list[TextBlock],
        original_text: str,
    ) -> Optional[TextBlock]:
        """
        對候選 TextBlock 做相似度比對，回傳最佳匹配或 None。

        [優化 5] 使用快速預檢與 SequenceMatcher 僅對候選塊計算相似度。
        [優化 6] 快速預檢：長度比超過 3:1 直接跳過，減少 SequenceMatcher 呼叫。
        [優化 7] 包含關係直接短路，避免 SequenceMatcher 計算。
        [優化 8] 相似度門檻 0.5，與原邏輯一致。
        """
        original_clean = _RE_WS_STRIP.sub('', original_text.strip()).lower()
        orig_len = len(original_clean)
        if orig_len == 0:
            # 移除空白後長度為 0，改用原始小寫
            original_clean = original_text.strip().lower()
            orig_len = len(original_clean)

        best_block: Optional[TextBlock] = None
        best_similarity = 0.5  # 相似度門檻

        for block in candidates:
            block_clean = _RE_WS_STRIP.sub('', block.text.strip()).lower()
            blen = len(block_clean)

            # [優化 6] 空塊或長度差過大則跳過
            if blen == 0:
                continue
            if orig_len > 0 and blen > 0:
                len_ratio = max(orig_len, blen) / min(orig_len, blen)
                if len_ratio > 3.0:
                    continue

            # [優化 7] 包含關係直接選中
            if original_clean in block_clean or block_clean in original_clean:
                logger.debug(f"文字包含關係命中 block_id={block.block_id}")
                return block

            similarity = difflib.SequenceMatcher(
                None, original_clean, block_clean
            ).ratio()
            if similarity > best_similarity:
                best_similarity = similarity
                best_block = block

        if best_block:
            logger.debug(
                f"相似度匹配命中 block_id={best_block.block_id}, "
                f"similarity={best_similarity:.2f}"
            )
        return best_block

    def _closest_to_center(
        self,
        candidates: list[TextBlock],
        rect: fitz.Rect,
    ) -> Optional[TextBlock]:
        """
        選擇 layout_rect 中心距離 rect 中心最近的 TextBlock（Manhattan 距離）。
        當無法透過文字相似度匹配時的 fallback 策略。
        """
        rect_cx = rect.x0 + rect.width / 2
        rect_cy = rect.y0 + rect.height / 2
        best_block: Optional[TextBlock] = None
        min_distance = float('inf')

        for block in candidates:
            bcx = block.layout_rect.x0 + block.layout_rect.width / 2
            bcy = block.layout_rect.y0 + block.layout_rect.height / 2
            dist = abs(bcx - rect_cx) + abs(bcy - rect_cy)
            if dist < min_distance:
                min_distance = dist
                best_block = block

        if best_block:
            logger.debug(f"最近中心命中 block_id={best_block.block_id}")
        return best_block

    def _dynamic_scan(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: Optional[str],
        doc: fitz.Document,
    ) -> Optional[TextBlock]:
        """
        當索引無候選時，直接掃描 fitz.Page 的文字塊作為保護網。
        結果不會存回索引；若呼叫端預期後續還會用到該 block，
        應在取得結果後呼叫 rebuild_page() 同步索引。

        [修正] 改用 _parse_block() 輔助方法，消除與 _build_page_index() 的程式碼重複。
        """
        page = doc[page_num]
        blocks_raw = page.get_text("dict", flags=0)["blocks"]
        temp_blocks: list[TextBlock] = []

        for i, block in enumerate(blocks_raw):
            # 快速類型預檢（比建立 Rect 更廉價），再做空間過濾
            if block.get('type') != 0:
                continue
            block_rect = fitz.Rect(block["bbox"])
            if not block_rect.intersects(rect):
                continue

            tb = self._parse_block(page_num, i, block)
            if tb is not None:
                temp_blocks.append(tb)

        if not temp_blocks:
            return None

        if original_text and original_text.strip():
            result = self._match_by_text(temp_blocks, original_text)
            if result is not None:
                return result

        return self._closest_to_center(temp_blocks, rect)
