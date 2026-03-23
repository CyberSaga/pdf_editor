"""
track_A_core.py — Vision LLM 重生頁面版（Track A 核心引擎）

策略：
  1. 分析頁面佈局（文字塊位置、間距、字體、行距）
  2. 計算編輯後的 delta（高度/寬度變化）
  3. 產生 reflow 規劃（哪些塊要移、移多少）
  4. 執行 redact + re-insert（用精準 rect 控制）
  5. 驗證無重疊、無誤刪

開發期可選用 Vision LLM 輔助分析佈局；
成品為純固定算法，無 LLM 依賴。

整合點：
  - 使用 PyMuPDF (fitz) 操作 PDF
  - 使用 TextBlockManager 的 block/span 索引
  - 輸出透過 UnifiedObjectCommand 封裝
"""

import logging
import inspect
from dataclasses import dataclass, field
from typing import Optional

import fitz

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 佈局分析結構
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BlockLayout:
    """單一文字塊的佈局資訊。"""
    block_idx: int
    bbox: fitz.Rect
    text: str
    font: str = ""
    size: float = 12.0
    color: tuple = (0, 0, 0)
    line_count: int = 0
    avg_line_height: float = 0.0
    is_vertical: bool = False
    reading_order: int = 0          # 閱讀順序（由上到下、由左到右）


@dataclass
class ReflowPlan:
    """Reflow 規劃：哪些塊要移、移多少。"""
    edited_block_idx: int
    delta_y: float = 0.0            # 垂直位移量（正 = 往下推）
    delta_x: float = 0.0            # 水平位移量（正 = 往右推）
    affected_blocks: list = field(default_factory=list)   # list[(block_idx, new_bbox)]
    warnings: list = field(default_factory=list)
    original_rect: object = None    # 使用者指定的原始編輯矩形（visual 座標）
    new_height: float = 0.0         # 估算的新文字高度（供 execute_reflow 設 insert_rect 用）


@dataclass
class LayoutAnalysis:
    """整頁佈局分析結果。"""
    page_idx: int
    page_rect: fitz.Rect
    blocks: list = field(default_factory=list)   # list[BlockLayout]
    columns: list = field(default_factory=list)  # list[fitz.Rect]（偵測到的欄位區域）
    reading_order: list = field(default_factory=list)  # list[int]（block_idx 排序）


# ──────────────────────────────────────────────────────────────────────────────
# Track A 引擎
# ──────────────────────────────────────────────────────────────────────────────

class TrackAEngine:
    """
    Track A：高階佈局分析 + 精準 redact/re-insert reflow 引擎。

    核心流程：
      analyze_layout() → compute_reflow_plan() → execute_reflow() → verify()

    不依賴任何 LLM；純固定算法。
    開發期可搭配 Vision LLM 做佈局分析輔助（見 analyze_with_vision()）。
    """

    def __init__(self):
        self._overlap_tolerance = 0.5  # pt，重疊容忍度

    # ── 主入口 ────────────────────────────────────────────────────────────

    def apply_reflow(
        self,
        doc: fitz.Document,
        page_idx: int,
        edited_rect: fitz.Rect,
        new_text: str,
        original_text: str = "",
        font: str = "helv",
        size: float = 12.0,
        color: tuple = (0, 0, 0),
    ) -> dict:
        """
        對指定頁面執行局部 reflow。

        參數：
          doc:           fitz.Document（會被就地修改）
          page_idx:      0-based 頁面索引
          edited_rect:   被編輯的文字塊矩形（visual 座標）
          new_text:      編輯後的新文字
          original_text: 編輯前的原始文字
          font/size/color: 文字樣式

        回傳：
          dict: {"success": bool, "plan": ReflowPlan, "warnings": list}
        """
        page = doc[page_idx]

        # Step 1: 分析佈局
        layout = self.analyze_layout(page, page_idx)

        # Step 2: 找到被編輯的塊
        edited_block_idx = self._find_edited_block(layout, edited_rect)
        if edited_block_idx is None:
            logger.warning(f"Track A: 找不到被編輯的塊 at {edited_rect}")
            return {"success": False, "plan": None, "warnings": ["edited block not found"]}

        # Step 3: 計算 reflow 規劃
        plan = self.compute_reflow_plan(
            layout=layout,
            edited_block_idx=edited_block_idx,
            new_text=new_text,
            original_text=original_text,
            font=font,
            size=size,
            original_rect=edited_rect,
        )

        # Step 4: 執行 reflow
        success = self.execute_reflow(
            doc=doc,
            page_idx=page_idx,
            plan=plan,
            new_text=new_text,
            font=font,
            size=size,
            color=color,
        )

        # Step 5: 驗證
        if success:
            verification = self.verify_no_overlap(doc[page_idx])
            if not verification["clean"]:
                plan.warnings.extend(verification["overlaps"])
                logger.warning(f"Track A: 驗證發現 {len(verification['overlaps'])} 處重疊")

        return {
            "success": success,
            "plan": plan,
            "warnings": plan.warnings,
        }

    # ── Step 1: 佈局分析 ─────────────────────────────────────────────────

    def analyze_layout(self, page: fitz.Page, page_idx: int) -> LayoutAnalysis:
        """
        分析頁面佈局：提取所有文字塊的位置、字體、行距，
        並推斷閱讀順序與欄位結構。
        """
        layout = LayoutAnalysis(
            page_idx=page_idx,
            page_rect=page.rect,
        )

        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks_data = text_dict.get("blocks", [])

        for i, block in enumerate(blocks_data):
            if block.get("type") != 0:  # 只處理文字塊
                continue

            lines = block.get("lines", [])
            if not lines:
                continue

            # 收集字體 / 大小 / 顏色資訊（取第一個 span 為代表）
            first_span = lines[0]["spans"][0] if lines[0].get("spans") else {}
            block_text = ""
            for line_i, line in enumerate(lines):
                for span_i, span in enumerate(line.get("spans", [])):
                    span_t = span.get("text", "")
                    if span_t:
                        if span_i == 0 and line_i > 0 and block_text and not block_text[-1].isspace():
                            block_text += " "
                        block_text += span_t

            # 計算平均行高
            line_heights = []
            for j in range(1, len(lines)):
                prev_bottom = lines[j - 1]["bbox"][3]
                curr_top = lines[j]["bbox"][1]
                line_heights.append(curr_top - prev_bottom + (
                    lines[j]["bbox"][3] - lines[j]["bbox"][1]
                ))
            avg_line_height = (
                sum(line_heights) / len(line_heights) if line_heights
                else (lines[0]["bbox"][3] - lines[0]["bbox"][1]) if lines
                else 12.0
            )

            # 偵測垂直文字（dir vector 接近 (0, -1) 或 (0, 1)）
            dir_vec = first_span.get("dir", (1, 0))
            is_vertical = abs(dir_vec[0]) < 0.3 and abs(dir_vec[1]) > 0.7

            bl = BlockLayout(
                block_idx=i,
                bbox=fitz.Rect(block["bbox"]),
                text=block_text,
                font=first_span.get("font", ""),
                size=first_span.get("size", 12.0),
                color=first_span.get("color", 0),
                line_count=len(lines),
                avg_line_height=avg_line_height,
                is_vertical=is_vertical,
            )
            layout.blocks.append(bl)

        # 推斷閱讀順序（由上到下、由左到右，分欄時按欄排序）
        self._infer_reading_order(layout)

        # 偵測欄位結構
        self._detect_columns(layout)

        return layout

    # ── Step 2: 計算 reflow 規劃 ─────────────────────────────────────────

    def compute_reflow_plan(
        self,
        layout: LayoutAnalysis,
        edited_block_idx: int,
        new_text: str,
        original_text: str,
        font: str = "helv",
        size: float = 12.0,
        original_rect: fitz.Rect = None,
    ) -> ReflowPlan:
        """
        計算 reflow 規劃：根據文字長度變化，決定後續塊的位移量。

        規則：
          - 文字變短 → delta_y < 0（後續塊上移）
          - 文字變長 → delta_y > 0（後續塊下推）
          - 只影響同欄內、閱讀順序在後的塊
          - 不超出頁面邊界
        """
        plan = ReflowPlan(edited_block_idx=edited_block_idx)
        plan.original_rect = original_rect  # 保存供 execute_reflow 使用

        # 找到被編輯的塊
        edited_block = None
        for bl in layout.blocks:
            if bl.block_idx == edited_block_idx:
                edited_block = bl
                break

        if edited_block is None:
            plan.warnings.append("edited block not found in layout")
            return plan

        # 估算新舊文字的高度差
        # 優先使用 original_rect.width（使用者指定的編輯寬度），
        # 避免以緊貼文字的 tight bbox 寬度（可能只有 43pt）造成 delta_y 嚴重偏差。
        est_width = (
            original_rect.width if original_rect is not None
            else edited_block.bbox.width
        )
        # 安全下限：寬度過小（< 3 個字元寬）時高度估算會爆炸，
        # 改用頁面寬度的 50% 作為合理回退值。
        min_safe_width = max(size * 3, 30.0)
        if est_width < min_safe_width:
            est_width = max(est_width, layout.page_rect.width * 0.5)
            plan.warnings.append(
                f"est_width={est_width:.1f}pt 過小，已回退至頁面寬度 50%"
            )
        old_height = self._estimate_text_height(
            original_text or edited_block.text,
            font, size,
            width=est_width,
            avg_line_height=edited_block.avg_line_height,
        )
        new_height = self._estimate_text_height(
            new_text, font, size,
            width=est_width,
            avg_line_height=edited_block.avg_line_height,
        )
        plan.delta_y = new_height - old_height
        plan.new_height = new_height  # 供 execute_reflow 計算正確的 insert_rect 高度

        if abs(plan.delta_y) < 0.5:
            # 變化太小，不需要 reflow
            return plan

        # 找出受影響的後續塊（同欄、閱讀順序在後）
        edited_column = self._find_column_for_block(layout, edited_block)

        for bl in layout.blocks:
            if bl.block_idx == edited_block_idx:
                continue
            if bl.reading_order <= edited_block.reading_order:
                continue

            # 檢查是否在同一欄
            bl_column = self._find_column_for_block(layout, bl)
            if edited_column is not None and bl_column is not None:
                if not edited_column.intersects(bl_column):
                    continue  # 不同欄，跳過

            # 檢查是否在被編輯塊的下方
            if bl.bbox.y0 < edited_block.bbox.y0:
                continue

            # 計算新位置
            new_bbox = fitz.Rect(bl.bbox)
            new_bbox.y0 += plan.delta_y
            new_bbox.y1 += plan.delta_y

            # 邊界檢查
            if new_bbox.y1 > layout.page_rect.height:
                plan.warnings.append(
                    f"Block {bl.block_idx} 位移後超出頁面底部 "
                    f"(y1={new_bbox.y1:.1f} > page_h={layout.page_rect.height:.1f})"
                )
                # 限制在頁面內
                overflow = new_bbox.y1 - layout.page_rect.height
                new_bbox.y0 -= overflow
                new_bbox.y1 = layout.page_rect.height

            if new_bbox.y0 < 0:
                plan.warnings.append(
                    f"Block {bl.block_idx} 位移後超出頁面頂部"
                )
                new_bbox.y0 = 0

            # 防干擾檢查：新位置是否與其他未移動的塊重疊
            overlap_found = False
            for other in layout.blocks:
                if other.block_idx in (
                    edited_block_idx, bl.block_idx
                ):
                    continue
                if other.reading_order <= edited_block.reading_order:
                    # 未移動的塊
                    if self._rects_overlap(new_bbox, other.bbox):
                        overlap_found = True
                        plan.warnings.append(
                            f"Block {bl.block_idx} 新位置與 Block {other.block_idx} 重疊"
                        )
                        break

            if not overlap_found:
                # 儲存 (block_idx, old_bbox, new_bbox)
                # old_bbox 用於 redact 後以 bbox 比對（block number 在 redact 後會重排）
                plan.affected_blocks.append((bl.block_idx, fitz.Rect(bl.bbox), new_bbox))

        return plan

    # ── Step 3: 執行 reflow ──────────────────────────────────────────────

    def execute_reflow(
        self,
        doc: fitz.Document,
        page_idx: int,
        plan: ReflowPlan,
        new_text: str,
        font: str = "helv",
        size: float = 12.0,
        color: tuple = (0, 0, 0),
    ) -> bool:
        """
        執行 reflow 規劃：
          1. Redact 被編輯的塊
          2. Re-insert 新文字
          3. 位移受影響的後續塊（redact → re-insert at new position）
        """
        page = doc[page_idx]

        try:
            # ── 關鍵：在任何 redaction 之前，預先讀取受影響塊的文字 ──
            # 原因：apply_redactions() 後 PyMuPDF 可能將相鄰塊合併（例如刪除中欄 p1
            # 後，左欄 p2 和中欄 p2 因為同一 y 位置而被合併成一個 block）。
            # 在 redaction 前讀取可確保取得正確的個別塊資料。
            pre_block_data = {}
            if plan.affected_blocks:
                pre_block_data = self._pre_read_affected_blocks(page, plan)

            # ── 處理被編輯的塊 ──
            edited_block = None
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0 and block.get("number") == plan.edited_block_idx:
                    edited_block = block
                    break

            if edited_block is None:
                # Fallback: 用 block index 取得
                all_text_blocks = [
                    b for b in text_dict.get("blocks", []) if b.get("type") == 0
                ]
                for b in all_text_blocks:
                    if b.get("number", -1) == plan.edited_block_idx:
                        edited_block = b
                        break

            if edited_block is None:
                plan.warnings.append("無法找到被編輯的塊，跳過 reflow 執行")
                return False

            tight_rect = fitz.Rect(edited_block["bbox"])

            # Redact 區域：優先使用 plan.original_rect（使用者選取範圍），
            # 而非 tight_rect（整個合併塊的 bbox）。
            # 原因：PyMuPDF 可能將同行相鄰文字（如表格 A1、B1、C1）合併成同一個 block，
            # 若以 tight_rect 做 redact，會誤刪 B1、C1 等鄰近內容。
            # 使用 original_rect 確保只擦除使用者選取的區域。
            redact_rect = fitz.Rect(plan.original_rect) if plan.original_rect else tight_rect
            page.add_redact_annot(redact_rect)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            # Re-insert 新文字
            # 優先使用 plan.original_rect（使用者指定的編輯矩形，寬度正確），
            # 避免以 tight bbox 寬度插入導致文字一行只放一個字。
            font_name = self._resolve_font(font)
            base_rect = fitz.Rect(plan.original_rect) if plan.original_rect else fitz.Rect(tight_rect)
            insert_rect = fitz.Rect(base_rect)
            # 用 plan.new_height（估算後的新文字高度）設定 insert_rect，
            # 而非 base_rect.height + delta_y（base_rect.height 是使用者指定高度，不等於 old_height）。
            estimated_h = plan.new_height if plan.new_height > 0 else base_rect.height
            insert_rect.y1 = min(
                insert_rect.y0 + max(size * 1.5, estimated_h),
                page.rect.height,
            )

            r, g, b = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
            css = (
                f"* {{ font-family: {font_name}; font-size: {size}pt; "
                f"color: rgb({r},{g},{b}); "
                f"word-wrap: break-word; overflow-wrap: break-word; "
                f"box-sizing: border-box; }}"
            )
            rc = page.insert_htmlbox(insert_rect, new_text, css=css)

            if (rc[0] if isinstance(rc, tuple) else rc) < 0:
                plan.warnings.append(f"insert_htmlbox 失敗 (rc={rc})，嘗試 fallback")
                page.insert_textbox(
                    insert_rect,
                    new_text,
                    fontname=font_name,
                    fontsize=size,
                    color=color,
                )

            # ── 處理受影響的後續塊（使用 redaction 前預讀的資料）──
            if plan.affected_blocks:
                self._reflow_affected_blocks(
                    doc=doc,
                    page_idx=page_idx,
                    plan=plan,
                    font=font,
                    size=size,
                    color=color,
                    pre_block_data=pre_block_data,
                )

            return True

        except Exception as e:
            logger.error(f"Track A execute_reflow 失敗: {e}", exc_info=True)
            plan.warnings.append(f"execute_reflow exception: {e}")
            return False

    # ── Step 4: 驗證 ─────────────────────────────────────────────────────

    def verify_no_overlap(self, page: fitz.Page) -> dict:
        """
        驗證頁面上所有文字塊是否有重疊。
        回傳 {"clean": bool, "overlaps": list[str]}
        """
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = [
            b for b in text_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]

        overlaps = []
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                r1 = fitz.Rect(blocks[i]["bbox"])
                r2 = fitz.Rect(blocks[j]["bbox"])
                if self._rects_overlap(r1, r2):
                    overlaps.append(
                        f"Block {blocks[i].get('number', i)} 與 "
                        f"Block {blocks[j].get('number', j)} 重疊: "
                        f"{r1} ∩ {r2}"
                    )

        return {"clean": len(overlaps) == 0, "overlaps": overlaps}

    # ── 輔助方法 ─────────────────────────────────────────────────────────

    def get_source_snapshot(self) -> str:
        """回傳本模組的原始碼（供 agent loop 記錄版本用）。"""
        return inspect.getsource(type(self))

    def _find_edited_block(
        self, layout: LayoutAnalysis, edited_rect: fitz.Rect,
    ) -> Optional[int]:
        """找出與 edited_rect 重疊最大的塊索引。

        跳過以下不合格的塊：
          - 純空白文字（只有空格/換行）
          - 塊的 bbox 面積 < edited_rect 面積的 1%（尺寸不合理的小塊）
        """
        best_idx = None
        best_overlap = 0.0
        edit_area = edited_rect.width * edited_rect.height

        for bl in layout.blocks:
            # 跳過純空白塊（格式用的空白 block 容易干擾比對）
            if not bl.text.strip():
                continue
            # 跳過寬度明顯不合理的塊（< 10pt 或 < edited_rect 寬度的 5%）
            min_w = max(10.0, edited_rect.width * 0.05)
            if bl.bbox.width < min_w:
                continue

            intersection = bl.bbox & edited_rect
            if intersection.is_empty:
                continue
            area = intersection.width * intersection.height
            if area > best_overlap:
                best_overlap = area
                best_idx = bl.block_idx

        return best_idx

    def _infer_reading_order(self, layout: LayoutAnalysis):
        """推斷閱讀順序：由上到下，同高度由左到右。"""
        sorted_blocks = sorted(
            layout.blocks,
            key=lambda bl: (round(bl.bbox.y0 / 10) * 10, bl.bbox.x0),
        )
        for order, bl in enumerate(sorted_blocks):
            bl.reading_order = order
        layout.reading_order = [bl.block_idx for bl in sorted_blocks]

    def _detect_columns(self, layout: LayoutAnalysis):
        """
        簡易欄位偵測：根據文字塊的 x 座標分布，
        將塊分成若干垂直欄位。
        """
        if not layout.blocks:
            return

        # 收集所有塊的 x 中心點（加入 block_idx 作為 tie-breaker 避免 BlockLayout 比較失敗）
        x_centers = sorted(
            (bl.bbox.x0 + bl.bbox.width / 2, bl.block_idx, bl) for bl in layout.blocks
        )

        # 簡易分群：相鄰 x 中心差距 > 頁寬的 30% 視為不同欄
        page_width = layout.page_rect.width
        threshold = page_width * 0.3
        columns = []
        current_group = [x_centers[0]]

        for i in range(1, len(x_centers)):
            if x_centers[i][0] - x_centers[i - 1][0] > threshold:
                columns.append(current_group)
                current_group = [x_centers[i]]
            else:
                current_group.append(x_centers[i])
        columns.append(current_group)

        # 產生欄位 rect
        for group in columns:
            if not group:
                continue
            blocks_in_col = [item[2] for item in group]
            x0 = min(bl.bbox.x0 for bl in blocks_in_col)
            x1 = max(bl.bbox.x1 for bl in blocks_in_col)
            y0 = min(bl.bbox.y0 for bl in blocks_in_col)
            y1 = max(bl.bbox.y1 for bl in blocks_in_col)
            layout.columns.append(fitz.Rect(x0, y0, x1, y1))

    def _find_column_for_block(
        self, layout: LayoutAnalysis, block: BlockLayout,
    ) -> Optional[fitz.Rect]:
        """找出包含指定塊的欄位。"""
        center_x = block.bbox.x0 + block.bbox.width / 2
        for col in layout.columns:
            if col.x0 <= center_x <= col.x1:
                return col
        return None

    @staticmethod
    def _count_display_width(text: str, size: float) -> float:
        """
        計算文字的估算顯示寬度（pt）。
        CJK 字元視為全形（size * 1.0），其餘視為半形（size * 0.6）。
        """
        cjk_width = size * 1.0
        latin_width = size * 0.6
        total = 0.0
        for ch in text:
            cp = ord(ch)
            # CJK Unified Ideographs, Katakana, Hiragana, Hangul, etc.
            if (
                0x1100 <= cp <= 0x11FF or  # Hangul Jamo
                0x2E80 <= cp <= 0x2FFF or  # CJK Radicals / Kangxi
                0x3000 <= cp <= 0x9FFF or  # CJK block (incl. Hiragana/Katakana)
                0xA000 <= cp <= 0xA4CF or  # Yi
                0xAC00 <= cp <= 0xD7AF or  # Hangul Syllables
                0xF900 <= cp <= 0xFAFF or  # CJK Compatibility Ideographs
                0xFE10 <= cp <= 0xFE4F or  # CJK Compatibility Forms
                0xFF00 <= cp <= 0xFFEF or  # Halfwidth/Fullwidth Forms
                0x20000 <= cp <= 0x2FA1F    # CJK Extension B+
            ):
                total += cjk_width
            else:
                total += latin_width
        return total

    def _estimate_text_height(
        self,
        text: str,
        font: str,
        size: float,
        width: float,
        avg_line_height: float,
    ) -> float:
        """
        估算文字在指定寬度內的排版高度。
        CJK 字元使用全形寬度（size * 1.0），其餘使用半形（size * 0.6）。
        """
        if not text:
            return 0.0

        # 考慮換行：逐行計算
        lines = text.split("\n")
        total_lines = 0
        for line in lines:
            if not line:
                total_lines += 1
                continue
            # 計算此行的顯示寬度，再除以容器寬度得到換行數
            display_w = self._count_display_width(line, size)
            wrapped = max(1, int((display_w / width) + 0.99)) if width > 0 else 1
            total_lines += wrapped

        line_height = max(avg_line_height, size * 1.2)
        return total_lines * line_height

    def _rects_overlap(self, r1: fitz.Rect, r2: fitz.Rect) -> bool:
        """檢查兩個 rect 是否有實質重疊（超過容忍度）。"""
        intersection = r1 & r2
        if intersection.is_empty:
            return False
        return (
            intersection.width > self._overlap_tolerance
            and intersection.height > self._overlap_tolerance
        )

    def _resolve_font(self, font: str) -> str:
        """將使用者字體名稱映射到 PyMuPDF 內建字體名稱。"""
        font_map = {
            "helv": "helv",
            "helvetica": "helv",
            "times": "tiro",
            "times-roman": "tiro",
            "courier": "cour",
            "cjk": "china-s",
            "gothic": "china-s",
            "mincho": "japan",
        }
        return font_map.get(font.lower(), font)

    def _pre_read_affected_blocks(self, page: fitz.Page, plan: "ReflowPlan") -> dict:
        """
        在任何 redaction 之前讀取受影響塊的文字。

        原因：apply_redactions() 後 PyMuPDF 可能將相鄰同 y 位置的塊合併（例如
        刪除中欄 p1 後，左欄 p2 和中欄 p2 因同一 y 位置而合併成一個 block），
        導致 _reflow_affected_blocks 讀到錯誤（合併後）的塊內容。
        在 redaction 前讀取可確保取得正確的個別塊資料。

        回傳 dict：key=block_idx，value={text, font, size, color, old_bbox}
        另有 "_all_blocks" key 存放全部塊資料，供 re-insert 時推斷欄寬使用。
        """
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        all_blocks = text_dict.get("blocks", [])
        block_data: dict = {"_all_blocks": all_blocks}

        for block_idx, old_bbox, new_bbox in plan.affected_blocks:
            cx = old_bbox.x0 + old_bbox.width / 2
            cy = old_bbox.y0 + old_bbox.height / 2
            best_b = None
            best_dist = float("inf")
            for b in all_blocks:
                if b.get("type") != 0:
                    continue
                br = fitz.Rect(b["bbox"])
                if br.contains(fitz.Point(cx, cy)):
                    dist = abs(br.x0 - old_bbox.x0) + abs(br.y0 - old_bbox.y0)
                    if dist < best_dist:
                        best_dist = dist
                        best_b = b

            if best_b is None:
                for b in all_blocks:
                    if b.get("type") != 0:
                        continue
                    br = fitz.Rect(b["bbox"])
                    dist = abs(br.x0 - old_bbox.x0) + abs(br.y0 - old_bbox.y0)
                    if dist < best_dist and dist < 5.0:
                        best_dist = dist
                        best_b = b

            if best_b is None:
                continue

            b = best_b
            block_text = ""
            block_font = None
            block_size = 12.0
            block_color = (0, 0, 0)
            for line_idx, line in enumerate(b.get("lines", [])):
                for span_idx, span in enumerate(line.get("spans", [])):
                    span_text = span.get("text", "")
                    if span_text:
                        if span_idx == 0 and line_idx > 0:
                            if block_text and not block_text[-1].isspace():
                                block_text += " "
                        block_text += span_text
                    if not block_font:
                        block_font = span.get("font", None)
                    block_size = span.get("size", block_size)
                    raw_color = span.get("color", 0)
                    if isinstance(raw_color, int):
                        rv = ((raw_color >> 16) & 0xFF) / 255.0
                        gv = ((raw_color >> 8) & 0xFF) / 255.0
                        bv = (raw_color & 0xFF) / 255.0
                        block_color = (rv, gv, bv)

            block_data[block_idx] = {
                "text": block_text,
                "font": block_font,
                "size": block_size,
                "color": block_color,
                "old_bbox": fitz.Rect(b["bbox"]),
            }

        return block_data

    def _reflow_affected_blocks(
        self,
        doc: fitz.Document,
        page_idx: int,
        plan: "ReflowPlan",
        font: str,
        size: float,
        color: tuple,
        pre_block_data: dict = None,
    ):
        """
        位移受影響的後續塊：
          1. 收集塊的文字內容（優先使用 pre_block_data，避免 redaction 後塊合併）
          2. Redact 原位置
          3. 在新位置 re-insert
        """
        page = doc[page_idx]

        # 優先使用 pre_block_data（redaction 前預讀，避免 PyMuPDF 合併問題）；
        # 若無則回退到重新讀取（舊行為，保持相容性）。
        if pre_block_data:
            all_blocks = pre_block_data.get("_all_blocks", [])
            block_texts = {
                k: v for k, v in pre_block_data.items()
                if k != "_all_blocks"
            }
            # 補齊缺少的 font/size/color（使用呼叫者傳入的預設值）
            for info in block_texts.values():
                if not info.get("font"):
                    info["font"] = font
                if not info.get("size"):
                    info["size"] = size
                if not info.get("color"):
                    info["color"] = color
        else:
            # 回退：重新讀取（可能受 redaction 影響）
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            all_blocks = text_dict.get("blocks", [])
            block_texts = {}

            for block_idx, old_bbox, new_bbox in plan.affected_blocks:
                cx = old_bbox.x0 + old_bbox.width / 2
                cy = old_bbox.y0 + old_bbox.height / 2
                best_b = None
                best_dist = float("inf")
                for b in all_blocks:
                    if b.get("type") != 0:
                        continue
                    br = fitz.Rect(b["bbox"])
                    if br.contains(fitz.Point(cx, cy)):
                        dist = abs(br.x0 - old_bbox.x0) + abs(br.y0 - old_bbox.y0)
                        if dist < best_dist:
                            best_dist = dist
                            best_b = b

                if best_b is None:
                    for b in all_blocks:
                        if b.get("type") != 0:
                            continue
                        br = fitz.Rect(b["bbox"])
                        dist = abs(br.x0 - old_bbox.x0) + abs(br.y0 - old_bbox.y0)
                        if dist < best_dist and dist < 5.0:
                            best_dist = dist
                            best_b = b

                if best_b is None:
                    continue

                b = best_b
                block_text = ""
                block_font = font
                block_size = size
                block_color = color
                for line_idx, line in enumerate(b.get("lines", [])):
                    for span_idx, span in enumerate(line.get("spans", [])):
                        span_text = span.get("text", "")
                        if span_text:
                            if span_idx == 0 and line_idx > 0:
                                if block_text and not block_text[-1].isspace():
                                    block_text += " "
                            block_text += span_text
                        if not block_font:
                            block_font = span.get("font", font)
                        block_size = span.get("size", size)
                        raw_color = span.get("color", 0)
                        if isinstance(raw_color, int):
                            r = ((raw_color >> 16) & 0xFF) / 255.0
                            g = ((raw_color >> 8) & 0xFF) / 255.0
                            b_val = (raw_color & 0xFF) / 255.0
                            block_color = (r, g, b_val)
                block_texts[block_idx] = {
                    "text": block_text,
                    "font": block_font,
                    "size": block_size,
                    "color": block_color,
                    "old_bbox": fitz.Rect(b["bbox"]),
                }

        # Redact 所有受影響塊的原位置
        for block_idx, old_bbox, new_bbox in plan.affected_blocks:
            info = block_texts.get(block_idx)
            if info:
                page.add_redact_annot(info["old_bbox"])

        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 在新位置 re-insert
        page_height = page.rect.height
        for block_idx, old_bbox, new_bbox in plan.affected_blocks:
            info = block_texts.get(block_idx)
            if not info or not info["text"].strip():
                continue

            font_name = self._resolve_font(info["font"])
            css = (
                f"* {{ font-family: {font_name}; "
                f"font-size: {info['size']}pt; "
                f"color: rgb({int(info['color'][0]*255)},"
                f"{int(info['color'][1]*255)},"
                f"{int(info['color'][2]*255)}); "
                f"word-wrap: break-word; overflow-wrap: break-word; }}"
            )
            # 使用足夠高 + 足夠寬的 rect 避免字體替換後文字被截斷或錯誤換行。
            # 問題：tight bbox x1 通常遠小於原始 textbox x1（"Block B." tight=44pt，但
            #       原始 textbox=328pt），用 tight x1 重新插入會導致單詞被錯誤換行。
            # 修復：從頁面現有塊推斷欄位右邊界（同 x0 附近最寬的塊的 x1），
            #       再以 original_rect.x1 補強，確保使用正確的欄位寬度。
            insert_height = max(new_bbox.height, info["size"] * 3)
            # 從已讀取的 all_blocks（redact 前）找同欄 x0 附近最大 x1
            inferred_x1 = new_bbox.x1
            for _b in all_blocks:
                if _b.get("type") != 0:
                    continue
                _br = fitz.Rect(_b["bbox"])
                if abs(_br.x0 - new_bbox.x0) < 15:
                    inferred_x1 = max(inferred_x1, _br.x1)
            # 同時參考 original_rect 的右邊界（若合理）
            if plan.original_rect and plan.original_rect.x1 > new_bbox.x0 + 40:
                inferred_x1 = max(inferred_x1, plan.original_rect.x1)
            insert_x1 = min(inferred_x1, page.rect.x1)
            insert_rect = fitz.Rect(
                new_bbox.x0, new_bbox.y0,
                insert_x1,
                min(new_bbox.y0 + insert_height, page_height),
            )
            rc = page.insert_htmlbox(insert_rect, info["text"], css=css)
            if (rc[0] if isinstance(rc, tuple) else rc) < 0:
                plan.warnings.append(
                    f"Block {block_idx} re-insert 失敗 (rc={rc})"
                )
                # Fallback
                try:
                    page.insert_textbox(
                        new_bbox,
                        info["text"],
                        fontname=font_name,
                        fontsize=info["size"],
                        color=info["color"],
                    )
                except Exception as e:
                    plan.warnings.append(
                        f"Block {block_idx} fallback insert 也失敗: {e}"
                    )

    # ── 統一物件編輯介面（apply_object_edit） ──────────────────────────

    def apply_object_edit(
        self,
        page: fitz.Page,
        object_info: dict,
        changes,
    ) -> dict:
        """
        Track A 統一物件編輯介面。

        object_info 欄位：
          original_rect  fitz.Rect  目標矩形（visual 座標）
          font           str        字體名稱
          size           float      字級（pt）
          color          tuple      文字顏色 (r,g,b) 0~1
          original_text  str        原始文字（供 diff/reflow 計算）
          page_rotation  int        頁面旋轉角度 0/90/180/270

        changes 接受 ObjectChanges dataclass 或 dict，有效欄位：
          new_text        str        新文字（None = 不改文字）
          color           tuple      新文字顏色
          new_color       tuple      新形狀顏色（與 color 二選一）
          opacity / new_opacity  float  新透明度 0~1
          fill / new_fill  bool   填滿切換
          new_fill_color  tuple      填滿顏色
          rotation_angle  float      旋轉角度（度）
          reflow_enabled  bool       是否啟用後續塊 reflow（預設 True）
          font            str        覆寫字體
          size            float      覆寫字級

        回傳：
          dict: {
            "success": bool,
            "track": "A",
            "warnings": list[str],
            "plan": ReflowPlan | None,
          }
        """
        ch = self._normalize_changes(changes)
        original_rect = fitz.Rect(object_info.get("original_rect", fitz.Rect()))
        font    = ch.get("font")  or object_info.get("font",  "helv")
        size    = ch.get("size")  or object_info.get("size",  12.0)
        color   = ch.get("color") or object_info.get("color", (0, 0, 0))
        original_text  = object_info.get("original_text", "")
        page_rotation  = object_info.get("page_rotation", page.rotation)

        new_text       = ch.get("new_text")
        new_color      = ch.get("new_color")
        new_opacity    = ch.get("new_opacity") if ch.get("new_opacity") is not None \
                         else ch.get("opacity")
        new_fill       = ch.get("new_fill") if ch.get("new_fill") is not None \
                         else ch.get("fill")
        new_fill_color = ch.get("new_fill_color")
        rotation_angle = ch.get("rotation_angle")
        reflow_enabled = ch.get("reflow_enabled", True)

        result: dict = {"success": True, "track": "A", "warnings": [], "plan": None}

        # ── 旋轉頁面座標修正 ────────────────────────────────────────────
        # PyMuPDF 的 get_text / add_redact_annot 都使用 visual 座標，
        # 但 insert_htmlbox 的 rect 參數在旋轉頁面上需要 derotate。
        insert_rect = self._derotate_rect(original_rect, page)

        # ── 文字 reflow ──────────────────────────────────────────────────
        if new_text is not None:
            doc = page.parent
            page_idx = page.number
            # 傳 original_rect（visual 座標）供佈局分析用；
            # insert_rect（derotated）已記錄於 insert_rect，
            # execute_reflow 內部會從 block bbox 取得正確 visual rect 做 redact，
            # 再用相同 rect 做 insert（rotated page 上 insert_htmlbox 接受 visual rect）
            reflow_result = self.apply_reflow(
                doc=doc,
                page_idx=page_idx,
                edited_rect=original_rect,
                new_text=new_text,
                original_text=original_text,
                font=font,
                size=size,
                color=color,
            )
            result["success"] = reflow_result["success"]
            result["plan"]    = reflow_result.get("plan")
            result["warnings"].extend(reflow_result.get("warnings", []))

        # ── 純顏色變更 ───────────────────────────────────────────────────
        if new_color is not None and new_text is None:
            ok = self._apply_annotation_color(page, original_rect, new_color, new_fill_color)
            if not ok:
                result["warnings"].append("object_color: 找不到目標 annotation")

        # ── 透明度變更 ───────────────────────────────────────────────────
        if new_opacity is not None:
            ok = self._apply_annotation_opacity(page, original_rect, new_opacity)
            if not ok:
                result["warnings"].append("object_opacity: 找不到目標 annotation")

        # ── 填滿切換 ─────────────────────────────────────────────────────
        if new_fill is not None and new_text is None:
            ok = self._apply_annotation_fill(page, original_rect, new_fill, new_fill_color)
            if not ok:
                result["warnings"].append("object_fill: 找不到目標 annotation")

        # ── 旋轉操作 ─────────────────────────────────────────────────────
        if rotation_angle is not None:
            rot_result = self._apply_text_rotation(
                page, insert_rect, rotation_angle, font, size, color,
            )
            result["success"] = rot_result["success"]
            result["warnings"].extend(rot_result.get("warnings", []))

        return result

    # ── apply_object_edit 輔助方法 ────────────────────────────────────

    @staticmethod
    def _normalize_changes(changes) -> dict:
        """將 ObjectChanges dataclass 或 dict 統一轉為 dict。"""
        if isinstance(changes, dict):
            return changes
        if hasattr(changes, "__dataclass_fields__"):
            return {k: getattr(changes, k) for k in changes.__dataclass_fields__}
        return {}

    def _derotate_rect(self, rect: fitz.Rect, page: fitz.Page) -> fitz.Rect:
        """
        將 visual 座標轉換為 insert_htmlbox 所需的「未旋轉」座標。

        PyMuPDF 的 insert_htmlbox 在旋轉頁面上使用頁面原始座標空間，
        而非 visual 空間；若頁面旋轉角度為 0，直接回傳原 rect。
        """
        rotation = page.rotation
        if rotation == 0:
            return fitz.Rect(rect)

        pw = page.rect.width
        ph = page.rect.height

        # 以頁面中心為原點做旋轉逆變換
        x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1

        if rotation == 90:
            # visual(x,y) → pdf(y, pw-x)
            return fitz.Rect(y0, pw - x1, y1, pw - x0)
        elif rotation == 180:
            return fitz.Rect(pw - x1, ph - y1, pw - x0, ph - y0)
        elif rotation == 270:
            # visual(x,y) → pdf(ph-y, x)
            return fitz.Rect(ph - y1, x0, ph - y0, x1)

        return fitz.Rect(rect)

    def _apply_annotation_color(
        self,
        page: fitz.Page,
        target_rect: fitz.Rect,
        stroke_color: tuple,
        fill_color: Optional[tuple] = None,
    ) -> bool:
        """透過 annotation API 變更顏色。回傳是否成功。"""
        best, best_area = None, 0.0
        for annot in page.annots():
            inter = annot.rect & target_rect
            if not inter.is_empty:
                area = inter.width * inter.height
                if area > best_area:
                    best_area = area
                    best = annot

        if best is None:
            return False

        best.set_colors(stroke=stroke_color)
        if fill_color is not None:
            best.set_colors(fill=fill_color)
        best.update()
        return True

    def _apply_annotation_opacity(
        self,
        page: fitz.Page,
        target_rect: fitz.Rect,
        opacity: float,
    ) -> bool:
        """透過 annotation API 變更透明度。回傳是否成功。"""
        best, best_area = None, 0.0
        for annot in page.annots():
            inter = annot.rect & target_rect
            if not inter.is_empty:
                area = inter.width * inter.height
                if area > best_area:
                    best_area = area
                    best = annot

        if best is None:
            return False

        best.set_opacity(max(0.0, min(1.0, opacity)))
        best.update()
        return True

    def _apply_annotation_fill(
        self,
        page: fitz.Page,
        target_rect: fitz.Rect,
        fill: bool,
        fill_color: Optional[tuple] = None,
    ) -> bool:
        """透過 annotation API 切換填滿狀態。回傳是否成功。"""
        best, best_area = None, 0.0
        for annot in page.annots():
            inter = annot.rect & target_rect
            if not inter.is_empty:
                area = inter.width * inter.height
                if area > best_area:
                    best_area = area
                    best = annot

        if best is None:
            return False

        if fill:
            best.set_colors(fill=fill_color or (1, 1, 1))
        else:
            best.set_colors(fill=None)
        best.update()
        return True

    def _apply_text_rotation(
        self,
        page: fitz.Page,
        derotated_rect: fitz.Rect,
        angle: float,
        font: str,
        size: float,
        color: tuple,
    ) -> dict:
        """
        旋轉文字框：redact 原位置 + 以新角度 re-insert。

        angle 為相對旋轉量（不是絕對角度）。
        insert_htmlbox 的 rotate 參數是 0/90/180/270 的絕對角度。
        """
        result = {"success": True, "warnings": []}
        try:
            # 擷取原始文字（在 derotate 前的視覺座標中提取）
            text_in_rect = page.get_text("text", clip=derotated_rect).strip()
            if not text_in_rect:
                result["warnings"].append("旋轉區域內無文字")
                return result

            # Redact 原位置
            page.add_redact_annot(derotated_rect)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            # 計算插入角度（順時針，0/90/180/270 之一）
            current_rot = page.rotation
            insert_rot = int((current_rot + angle) % 360)
            # 對齊到 0/90/180/270
            insert_rot = round(insert_rot / 90) * 90 % 360

            font_name = self._resolve_font(font)
            css = (
                f"* {{ font-family: {font_name}; font-size: {size}pt; "
                f"color: rgb({int(color[0]*255)},"
                f"{int(color[1]*255)},{int(color[2]*255)}); }}"
            )
            page.insert_htmlbox(derotated_rect, text_in_rect, css=css, rotate=insert_rot)

        except Exception as e:
            logger.error(f"Track A _apply_text_rotation 失敗: {e}", exc_info=True)
            result["success"] = False
            result["warnings"].append(f"rotation exception: {e}")

        return result

    # ── Vision LLM 輔助（開發期可選） ────────────────────────────────────

    def analyze_with_vision(
        self,
        page_image_png: bytes,
        prompt: str = "",
    ) -> dict:
        """
        （開發期輔助）使用 Vision LLM 分析頁面圖片的佈局。
        此方法不會出現在成品中，僅供迭代開發時使用。

        回傳格式：
          {"blocks": [...], "columns": [...], "suggestions": "..."}
        """
        # 佔位：實際接入 LLM API 時替換
        logger.info("analyze_with_vision: 佔位方法，開發期替換為真實 LLM 呼叫")
        return {
            "blocks": [],
            "columns": [],
            "suggestions": "Please connect a Vision LLM API for layout analysis.",
        }
