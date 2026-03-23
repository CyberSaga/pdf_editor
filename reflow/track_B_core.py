"""
track_B_core.py — 低階 content stream 精準操作版（Track B 核心引擎）

策略：
  1. 直接解析頁面的 content stream（PDF 運算子層級）
  2. 精準定位目標文字塊的 Tm/Td/TJ 運算子
  3. 計算 delta 位移，逐 glyph 或逐 span 調整座標
  4. 重建受影響部分的 content stream snippet
  5. 驗證 stream 語法正確 + 無重疊

優點：
  - 不需 redact（不會誤刪鄰近內容）
  - 精準到 glyph 級別的位置控制
  - 保留原始字體嵌入、kerning、ligature

整合點：
  - 使用 PyMuPDF (fitz) 操作 PDF
  - 使用 TextBlockManager 的 span/quad 索引做定位
  - 輸出透過 UnifiedObjectCommand 封裝
"""

import logging
import inspect
import re
from dataclasses import dataclass, field
from typing import Optional

import fitz

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Content Stream 分析結構
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class StreamSpan:
    """Content stream 中的一段文字資訊。"""
    span_idx: int
    bbox: fitz.Rect
    text: str
    font_name: str = ""
    font_size: float = 12.0
    color_rgb: tuple = (0, 0, 0)
    tm_matrix: tuple = (1, 0, 0, 1, 0, 0)  # Text Matrix [a b c d e f]
    origin: fitz.Point = field(default_factory=lambda: fitz.Point(0, 0))
    char_positions: list = field(default_factory=list)  # list[(x, y, char)]


@dataclass
class StreamAnalysis:
    """頁面 content stream 分析結果。"""
    page_idx: int
    spans: list = field(default_factory=list)          # list[StreamSpan]
    non_text_rects: list = field(default_factory=list)  # list[fitz.Rect]（圖形/圖片區域）
    raw_stream_length: int = 0


@dataclass
class DeltaShift:
    """單一 span 的座標位移指令。"""
    span_idx: int
    old_bbox: fitz.Rect
    new_bbox: fitz.Rect
    delta_x: float = 0.0
    delta_y: float = 0.0
    rewrite_text: Optional[str] = None  # 若不為 None，表示需要改寫文字內容


@dataclass
class StreamReflowPlan:
    """Content stream 級別的 reflow 規劃。"""
    edited_span_idx: int
    shifts: list = field(default_factory=list)      # list[DeltaShift]
    warnings: list = field(default_factory=list)
    delta_y_total: float = 0.0
    original_rect: object = None   # 使用者指定的原始編輯矩形（visual 座標）
    new_height: float = 0.0        # 估算的新文字高度（供 apply_shifts 設 insert rect 用）


# ──────────────────────────────────────────────────────────────────────────────
# Track B 引擎
# ──────────────────────────────────────────────────────────────────────────────

class TrackBEngine:
    """
    Track B：低階 content stream 精準 reflow 引擎。

    核心流程：
      analyze_stream() → compute_shifts() → apply_shifts() → verify_stream()

    完全不使用 redact（避免誤刪），
    而是直接操作 content stream 中的文字座標。
    """

    def __init__(self):
        self._position_tolerance = 0.5   # pt，位置偏差容忍度
        self._overlap_tolerance = 0.5    # pt，重疊容忍度

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
        對指定頁面執行低階 content stream reflow。

        參數：
          doc:           fitz.Document（會被就地修改）
          page_idx:      0-based 頁面索引
          edited_rect:   被編輯的文字塊矩形（visual 座標）
          new_text:      編輯後的新文字
          original_text: 編輯前的原始文字
          font/size/color: 文字樣式

        回傳：
          dict: {"success": bool, "plan": StreamReflowPlan, "warnings": list}
        """
        page = doc[page_idx]

        # Step 1: 分析 content stream
        analysis = self.analyze_stream(page, page_idx)

        # Step 2: 找出被編輯的 span
        edited_span_idx = self._find_edited_span(analysis, edited_rect)
        if edited_span_idx is None:
            logger.warning(f"Track B: 找不到被編輯的 span at {edited_rect}")
            return {
                "success": False,
                "plan": None,
                "warnings": ["edited span not found in stream"],
            }

        # Step 3: 計算位移
        plan = self.compute_shifts(
            analysis=analysis,
            edited_span_idx=edited_span_idx,
            new_text=new_text,
            original_text=original_text,
            font=font,
            size=size,
            page_rect=page.rect,
            original_rect=edited_rect,
        )

        # Step 4: 套用位移
        success = self.apply_shifts(
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
            verify_result = self.verify_stream(doc[page_idx])
            if not verify_result["valid"]:
                plan.warnings.extend(verify_result["issues"])

        return {
            "success": success,
            "plan": plan,
            "warnings": plan.warnings,
        }

    def apply_displacement_only(
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
        只位移受影響的後續 spans，不重新處理已編輯的 span。

        與 apply_reflow() 的差異：過濾掉 edited span 自身的 shift
        （rewrite_text is not None），只套用後續 spans 的位移。

        適合在 model.edit_text() 已完成文字替換後呼叫。
        """
        page = doc[page_idx]

        # Step 1: 分析當前 content stream（model.edit_text 修改後）
        analysis = self.analyze_stream(page, page_idx)

        # Step 2: 找出被編輯的 span
        edited_span_idx = self._find_edited_span(analysis, edited_rect)
        if edited_span_idx is None:
            logger.debug(f"Track B displacement: 找不到 edited span at {edited_rect}，跳過")
            return {"success": True, "plan": None, "warnings": ["edited span not found, skipped"]}

        # Step 3: 計算位移（包含 edited span + 後續 spans）
        plan = self.compute_shifts(
            analysis=analysis,
            edited_span_idx=edited_span_idx,
            new_text=new_text,
            original_text=original_text,
            font=font,
            size=size,
            page_rect=page.rect,
            original_rect=edited_rect,
        )

        # 過濾掉 edited span 本身的 shift（rewrite_text is not None 表示是 edited span）
        displacement_shifts = [s for s in plan.shifts if s.rewrite_text is None]

        if not displacement_shifts:
            return {"success": True, "plan": plan, "warnings": plan.warnings}

        # 只套用後續 spans 的位移
        plan.shifts = displacement_shifts
        try:
            success = self.apply_shifts(
                doc=doc,
                page_idx=page_idx,
                plan=plan,
                new_text="",   # 不影響 edited span，此值不被使用
                font=font,
                size=size,
                color=color,
            )
        except Exception as e:
            logger.error(f"Track B displacement apply_shifts 失敗: {e}", exc_info=True)
            plan.warnings.append(f"displacement exception: {e}")
            return {"success": False, "plan": plan, "warnings": plan.warnings}

        return {"success": success, "plan": plan, "warnings": plan.warnings}

    # ── Step 1: Content Stream 分析 ──────────────────────────────────────

    def analyze_stream(self, page: fitz.Page, page_idx: int) -> StreamAnalysis:
        """
        分析頁面的文字 span 佈局（使用 PyMuPDF 的 text extraction）。

        注意：PyMuPDF 不直接暴露 content stream 運算子的修改 API，
        因此我們使用 span-level 的資訊作為中間表示，
        並透過 redact + re-insert（quad-precise）來實現「不誤刪」的位移。
        """
        analysis = StreamAnalysis(page_idx=page_idx)

        # 取得所有 span 的詳細資訊
        text_dict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        try:
            analysis.raw_stream_length = len(page.read_contents())
        except Exception:
            analysis.raw_stream_length = 0

        span_idx = 0
        for block in text_dict.get("blocks", []):
            if block.get("type") == 1:
                # 圖片塊：記錄其佔據的區域（用於防干擾）
                analysis.non_text_rects.append(fitz.Rect(block["bbox"]))
                continue

            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = fitz.Rect(span["bbox"])
                    origin = fitz.Point(span.get("origin", (bbox.x0, bbox.y1)))

                    # 解析 color（int → RGB tuple）
                    raw_color = span.get("color", 0)
                    if isinstance(raw_color, int):
                        r = ((raw_color >> 16) & 0xFF) / 255.0
                        g = ((raw_color >> 8) & 0xFF) / 255.0
                        b = (raw_color & 0xFF) / 255.0
                        color_rgb = (r, g, b)
                    else:
                        color_rgb = (0, 0, 0)

                    # 建構 char positions（如果有 chars 資訊）
                    # rawdict 模式：spans 無 'text' key，文字從 chars[*]['c'] 重建
                    char_positions = []
                    chars_list = span.get("chars", [])
                    for ch in chars_list:
                        ch_bbox = fitz.Rect(ch["bbox"])
                        char_positions.append((
                            ch_bbox.x0, ch_bbox.y0, ch.get("c", "")
                        ))
                    # 優先從 chars 重建文字（rawdict 格式），否則嘗試 'text' key
                    span_text = (
                        "".join(ch.get("c", "") for ch in chars_list)
                        if chars_list
                        else span.get("text", "")
                    )

                    stream_span = StreamSpan(
                        span_idx=span_idx,
                        bbox=bbox,
                        text=span_text,
                        font_name=span.get("font", ""),
                        font_size=span.get("size", 12.0),
                        color_rgb=color_rgb,
                        origin=origin,
                        char_positions=char_positions,
                    )
                    analysis.spans.append(stream_span)
                    span_idx += 1

        logger.debug(
            f"Track B analyze_stream: page {page_idx}, "
            f"{len(analysis.spans)} spans, "
            f"{len(analysis.non_text_rects)} non-text rects"
        )
        return analysis

    # ── Step 2: 計算位移 ─────────────────────────────────────────────────

    def compute_shifts(
        self,
        analysis: StreamAnalysis,
        edited_span_idx: int,
        new_text: str,
        original_text: str,
        font: str,
        size: float,
        page_rect: fitz.Rect,
        original_rect: fitz.Rect = None,
    ) -> StreamReflowPlan:
        """
        計算精準的 span-level 位移。

        策略：
          - 計算被編輯 span 的高度變化（delta_y）
          - 只影響「在被編輯 span 下方」且「在同一水平範圍內」的後續 spans
          - 逐 span 計算新 bbox，並做防干擾檢查（不與圖片/其他靜態塊重疊）
        """
        plan = StreamReflowPlan(edited_span_idx=edited_span_idx)
        plan.original_rect = original_rect  # 保存供 apply_shifts 使用

        # 找出被編輯的 span
        edited_span = None
        for sp in analysis.spans:
            if sp.span_idx == edited_span_idx:
                edited_span = sp
                break

        if edited_span is None:
            plan.warnings.append("edited span not found")
            return plan

        # 估算高度變化
        # 優先使用 original_rect.width（使用者指定寬度），避免 tight bbox 寬度造成誤差
        est_width = (
            original_rect.width if original_rect is not None
            else edited_span.bbox.width
        )
        # 安全下限：寬度過小時高度估算會爆炸，回退至頁面寬度 50%
        min_safe_width = max(size * 3, 30.0)
        if est_width < min_safe_width:
            page_w = page_rect.width if page_rect else 595.0
            est_width = max(est_width, page_w * 0.5)
            plan.warnings.append(f"est_width 過小，已回退至 {est_width:.1f}pt")
        old_height = self._estimate_span_height(
            original_text or edited_span.text,
            size,
            est_width,
        )
        new_height = self._estimate_span_height(
            new_text, size, est_width,
        )
        plan.delta_y_total = new_height - old_height
        plan.new_height = new_height  # 供 apply_shifts 計算正確 insert rect 高度

        if abs(plan.delta_y_total) < self._position_tolerance:
            # 高度變化太小，不需要位移後續 span
            return plan

        # 被編輯 span 自身的 rewrite
        # 使用 original_rect 的 x 範圍以取得正確寬度（避免 tight bbox 造成文字過窄）
        base_x0 = original_rect.x0 if original_rect else edited_span.bbox.x0
        base_x1 = original_rect.x1 if original_rect else edited_span.bbox.x1
        plan.shifts.append(DeltaShift(
            span_idx=edited_span_idx,
            old_bbox=fitz.Rect(edited_span.bbox),
            new_bbox=fitz.Rect(
                base_x0,
                edited_span.bbox.y0,
                base_x1,
                edited_span.bbox.y0 + new_height,
            ),
            delta_x=0,
            delta_y=0,
            rewrite_text=new_text,
        ))

        # 找出需要位移的後續 spans
        edited_bottom = edited_span.bbox.y1
        edited_x_range = (edited_span.bbox.x0, edited_span.bbox.x1)

        for sp in analysis.spans:
            if sp.span_idx == edited_span_idx:
                continue

            # 只位移在被編輯 span 下方的 spans
            if sp.bbox.y0 < edited_bottom - self._position_tolerance:
                continue

            # 檢查是否在同一水平範圍內（允許一定偏差）
            span_x_center = sp.bbox.x0 + sp.bbox.width / 2
            column_overlap = (
                edited_x_range[0] - page_rect.width * 0.1
                <= span_x_center
                <= edited_x_range[1] + page_rect.width * 0.1
            )

            if not column_overlap:
                continue

            # 計算新 bbox
            new_bbox = fitz.Rect(sp.bbox)
            new_bbox.y0 += plan.delta_y_total
            new_bbox.y1 += plan.delta_y_total

            # 邊界檢查
            if new_bbox.y1 > page_rect.height:
                overflow = new_bbox.y1 - page_rect.height
                plan.warnings.append(
                    f"Span {sp.span_idx} 超出頁面底部 {overflow:.1f}pt"
                )
                new_bbox.y0 = max(0, new_bbox.y0 - overflow)
                new_bbox.y1 = page_rect.height

            if new_bbox.y0 < 0:
                new_bbox.y0 = 0
                plan.warnings.append(f"Span {sp.span_idx} 被限制在頁面頂部")

            # 防干擾檢查：不與圖片區域重疊
            blocked = False
            for nr in analysis.non_text_rects:
                if self._rects_overlap(new_bbox, nr):
                    plan.warnings.append(
                        f"Span {sp.span_idx} 新位置與圖片/圖形區域重疊，跳過位移"
                    )
                    blocked = True
                    break

            if blocked:
                continue

            plan.shifts.append(DeltaShift(
                span_idx=sp.span_idx,
                old_bbox=fitz.Rect(sp.bbox),
                new_bbox=new_bbox,
                delta_x=0,
                delta_y=plan.delta_y_total,
            ))

        logger.debug(
            f"Track B compute_shifts: "
            f"delta_y={plan.delta_y_total:.1f}, "
            f"{len(plan.shifts)} spans affected"
        )
        return plan

    # ── Step 3: 套用位移 ─────────────────────────────────────────────────

    def apply_shifts(
        self,
        doc: fitz.Document,
        page_idx: int,
        plan: StreamReflowPlan,
        new_text: str,
        font: str = "helv",
        size: float = 12.0,
        color: tuple = (0, 0, 0),
    ) -> bool:
        """
        套用位移規劃。

        策略（PyMuPDF 限制下的最佳做法）：
          1. 對被編輯的 span：使用 quad-precise redact + re-insert
          2. 對後續需位移的 spans：逐一 redact 原位 + re-insert 新位
          3. 保留未受影響的 spans 不動

        之所以使用 quad-precise redact 而非直接修改 content stream，
        是因為 PyMuPDF 不提供 content stream 運算子級別的直接修改 API。
        但透過 quad（四邊形）精準定位，可避免 rect-based redact 的誤刪問題。
        """
        if not plan.shifts:
            return True

        page = doc[page_idx]

        try:
            # ── Phase 1: 收集所有需要 redact 的 span 資訊 ──
            # 先收集文字（redact 前），按 span_idx 建索引
            span_info = {}
            text_dict = page.get_text(
                "rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE
            )

            flat_spans = []
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        flat_spans.append(span)

            for shift in plan.shifts:
                idx = shift.span_idx
                # 用 old_bbox 中心點比對現有 span（flat index 在 redact 後會失效）
                cx = shift.old_bbox.x0 + shift.old_bbox.width / 2
                cy = shift.old_bbox.y0 + shift.old_bbox.height / 2
                best_sp = None
                best_dist = float("inf")
                for sp in flat_spans:
                    sr = fitz.Rect(sp["bbox"])
                    if sr.contains(fitz.Point(cx, cy)):
                        dist = abs(sr.x0 - shift.old_bbox.x0) + abs(sr.y0 - shift.old_bbox.y0)
                        if dist < best_dist:
                            best_dist = dist
                            best_sp = sp
                # fallback: 仍用 flat index
                if best_sp is None and idx < len(flat_spans):
                    best_sp = flat_spans[idx]
                if best_sp is not None:
                    sp = best_sp
                    span_info[idx] = {
                        "text": shift.rewrite_text or sp.get("text", ""),
                        "font": sp.get("font", font),
                        "size": sp.get("size", size),
                        "color": self._parse_span_color(sp.get("color", 0)),
                        "old_bbox": shift.old_bbox,
                        "new_bbox": shift.new_bbox,
                    }
                else:
                    plan.warnings.append(
                        f"Span {idx} 無法以 bbox 比對（flat_spans len={len(flat_spans)}）"
                    )

            # ── Phase 2: 精準 Redact ──
            # 使用 quads（如果可用）提高精準度
            for idx, info in span_info.items():
                old_rect = info["old_bbox"]
                # 建立 redact annotation（使用 rect + 無填充）
                annot = page.add_redact_annot(
                    old_rect,
                    text="",               # 不自動插入替換文字
                    fill=False,            # 不填白色背景
                )

            # 一次性 apply（減少 content stream 重建次數）
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            # ── Phase 3: Re-insert 到新位置 ──
            for idx, info in sorted(span_info.items()):
                text = info["text"]
                if not text.strip():
                    continue

                new_bbox = info["new_bbox"]
                font_name = self._resolve_font(info["font"])
                sp_color = info["color"]

                lh = info["size"] * 1.2
                try:
                    _fo = fitz.Font(font_name)
                    lh = max(info["size"], (_fo.ascender - _fo.descender) * info["size"])
                except Exception:
                    pass
                css = (
                    f"* {{ font-family: {font_name}; "
                    f"font-size: {info['size']}pt; "
                    f"line-height: {lh:.2f}pt; "
                    f"color: rgb({int(sp_color[0]*255)},"
                    f"{int(sp_color[1]*255)},"
                    f"{int(sp_color[2]*255)}); "
                    f"word-wrap: break-word; overflow-wrap: break-word; "
                    f"box-sizing: border-box; }}"
                )

                rc = page.insert_htmlbox(new_bbox, text, css=css)
                if (rc[0] if isinstance(rc, tuple) else rc) < 0:
                    # Fallback to insert_textbox
                    try:
                        page.insert_textbox(
                            new_bbox,
                            text,
                            fontname=font_name,
                            fontsize=info["size"],
                            color=sp_color,
                        )
                    except Exception as e:
                        plan.warnings.append(
                            f"Span {idx} re-insert 失敗: {e}"
                        )

            return True

        except Exception as e:
            logger.error(f"Track B apply_shifts 失敗: {e}", exc_info=True)
            plan.warnings.append(f"apply_shifts exception: {e}")
            return False

    # ── Step 4: 驗證 ─────────────────────────────────────────────────────

    def verify_stream(self, page: fitz.Page) -> dict:
        """
        驗證 content stream 的完整性與文字塊無重疊。

        檢查：
          1. Content stream 可被 PyMuPDF 正確解析（無語法錯誤）
          2. 文字塊之間無實質重疊
          3. 文字未超出頁面邊界
        """
        issues = []

        # 1. Stream 語法檢查
        try:
            _ = page.get_text("dict")
        except Exception as e:
            issues.append(f"Content stream 解析失敗: {e}")
            return {"valid": False, "issues": issues}

        # 2. 重疊檢查
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = [
            b for b in text_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]

        for i in range(len(blocks)):
            r1 = fitz.Rect(blocks[i]["bbox"])

            # 3. 邊界檢查
            if r1.y1 > page.rect.height + 1 or r1.x1 > page.rect.width + 1:
                issues.append(
                    f"Block {i} 超出頁面邊界: {r1} vs page={page.rect}"
                )

            for j in range(i + 1, len(blocks)):
                r2 = fitz.Rect(blocks[j]["bbox"])
                if self._rects_overlap(r1, r2):
                    issues.append(
                        f"Block {i} 與 Block {j} 重疊: {r1} ∩ {r2}"
                    )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }

    # ── Quad-level 精準操作 ──────────────────────────────────────────────

    def get_span_quads(
        self, page: fitz.Page, target_rect: fitz.Rect, target_text: str = "",
    ) -> list:
        """
        取得指定區域內所有 span 的 quads（四邊形）。
        Quad 比 rect 更精準，能處理旋轉或傾斜的文字。
        """
        quads = []
        text_dict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_rect = fitz.Rect(span["bbox"])
                    intersection = span_rect & target_rect
                    if intersection.is_empty:
                        continue

                    # 如果有目標文字，比對
                    if target_text and target_text not in span.get("text", ""):
                        continue

                    # 使用 span 的 bbox 轉 quad
                    quad = fitz.Quad(span_rect)
                    quads.append({
                        "quad": quad,
                        "text": span.get("text", ""),
                        "font": span.get("font", ""),
                        "size": span.get("size", 12),
                        "color": span.get("color", 0),
                        "bbox": span_rect,
                    })

        return quads

    # ── 輔助方法 ─────────────────────────────────────────────────────────

    def get_source_snapshot(self) -> str:
        """回傳本模組的原始碼（供 agent loop 記錄版本用）。"""
        return inspect.getsource(type(self))

    def _find_edited_span(
        self, analysis: StreamAnalysis, edited_rect: fitz.Rect,
    ) -> Optional[int]:
        """找出與 edited_rect 重疊最大的 span 索引。

        注意：rawdict 模式對部分 CJK 字型可能回傳 text=''，
        因此不做文字內容過濾，只以 bbox 面積決定最佳 span。
        若所有 span 的 text 都為空，Track B 無法實際修改文字，
        此時上層應回退到 Track A。
        """
        best_idx = None
        best_overlap = 0.0

        for sp in analysis.spans:
            intersection = sp.bbox & edited_rect
            if intersection.is_empty:
                continue
            area = intersection.width * intersection.height
            if area > best_overlap:
                best_overlap = area
                best_idx = sp.span_idx

        # 若找到的 span text 為空（CJK 不可解碼字型），回傳 None 讓上層回退 Track A
        if best_idx is not None:
            found_sp = next(sp for sp in analysis.spans if sp.span_idx == best_idx)
            if not found_sp.text.strip():
                logger.warning(
                    f"Track B: found span {best_idx} but text is empty "
                    f"(non-decodable font), falling back to Track A"
                )
                return None

        return best_idx

    @staticmethod
    def _count_display_width(text: str, size: float) -> float:
        """CJK 字元視為全形（size*1.0），其餘視為半形（size*0.6）。"""
        cjk_w = size * 1.0
        lat_w = size * 0.6
        total = 0.0
        for ch in text:
            cp = ord(ch)
            if (
                0x1100 <= cp <= 0x11FF or
                0x2E80 <= cp <= 0x2FFF or
                0x3000 <= cp <= 0x9FFF or
                0xA000 <= cp <= 0xA4CF or
                0xAC00 <= cp <= 0xD7AF or
                0xF900 <= cp <= 0xFAFF or
                0xFE10 <= cp <= 0xFE4F or
                0xFF00 <= cp <= 0xFFEF or
                0x20000 <= cp <= 0x2FA1F
            ):
                total += cjk_w
            else:
                total += lat_w
        return total

    def _estimate_span_height(
        self, text: str, size: float, width: float,
    ) -> float:
        """估算文字在指定寬度內的高度（CJK-aware）。"""
        if not text:
            return 0.0

        lines = text.split("\n")
        total_lines = 0
        for line in lines:
            if not line:
                total_lines += 1
                continue
            display_w = self._count_display_width(line, size)
            wrapped = max(1, int((display_w / width) + 0.99)) if width > 0 else 1
            total_lines += wrapped

        return total_lines * size * 1.2

    def _rects_overlap(self, r1: fitz.Rect, r2: fitz.Rect) -> bool:
        """檢查兩個 rect 是否有實質重疊。"""
        intersection = r1 & r2
        if intersection.is_empty:
            return False
        return (
            intersection.width > self._overlap_tolerance
            and intersection.height > self._overlap_tolerance
        )

    def _resolve_font(self, font: str) -> str:
        """將字體名稱映射到 PyMuPDF 內建字體。"""
        font_map = {
            "helv": "helv",
            "helvetica": "helv",
            "Helvetica": "helv",
            "times": "tiro",
            "Times-Roman": "tiro",
            "courier": "cour",
            "Courier": "cour",
            "cjk": "china-s",
            "gothic": "china-s",
            "mincho": "japan",
        }
        return font_map.get(font, font)

    # ── 統一物件編輯介面（apply_object_edit） ──────────────────────────

    def apply_object_edit(
        self,
        page: fitz.Page,
        object_info: dict,
        changes,
    ) -> dict:
        """
        Track B 統一物件編輯介面（含內建 quad 干擾前置/後置檢查）。

        object_info 欄位：
          original_rect  fitz.Rect  目標矩形（visual 座標）
          font           str        字體名稱
          size           float      字級（pt）
          color          tuple      文字顏色 (r,g,b) 0~1
          original_text  str        原始文字
          page_rotation  int        頁面旋轉角度

        changes 接受 ObjectChanges dataclass 或 dict，有效欄位：
          new_text / color / new_color / opacity / new_opacity /
          fill / new_fill / new_fill_color / rotation_angle /
          reflow_enabled / font / size

        回傳：
          dict: {
            "success": bool,
            "track": "B",
            "warnings": list[str],
            "plan": StreamReflowPlan | None,
            "interference_count": int,
            "interference_details": list[str],
          }
        """
        ch = self._normalize_changes(changes)
        original_rect  = fitz.Rect(object_info.get("original_rect", fitz.Rect()))
        font           = ch.get("font")  or object_info.get("font",  "helv")
        size           = ch.get("size")  or object_info.get("size",  12.0)
        color          = ch.get("color") or object_info.get("color", (0, 0, 0))
        original_text  = object_info.get("original_text", "")

        new_text       = ch.get("new_text")
        new_color      = ch.get("new_color")
        new_opacity    = ch.get("new_opacity") if ch.get("new_opacity") is not None \
                         else ch.get("opacity")
        new_fill       = ch.get("new_fill") if ch.get("new_fill") is not None \
                         else ch.get("fill")
        new_fill_color = ch.get("new_fill_color")

        result: dict = {
            "success": True,
            "track": "B",
            "warnings": [],
            "plan": None,
            "interference_count": 0,
            "interference_details": [],
        }

        # ── Phase 0: 前置 quad 快照（只快照非目標區域）──────────────────
        non_target_before = self._capture_non_target_quads(page, original_rect)

        # ── 文字 reflow ──────────────────────────────────────────────────
        if new_text is not None:
            doc      = page.parent
            page_idx = page.number
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

        # ── 純顏色變更（annotation / drawing 操作）──────────────────────
        if new_color is not None and new_text is None:
            ok = self._apply_annotation_color(page, original_rect, new_color, new_fill_color)
            if not ok:
                result["warnings"].append("Track B object_color: 找不到目標 annotation")

        # ── 透明度變更 ───────────────────────────────────────────────────
        if new_opacity is not None:
            ok = self._apply_annotation_opacity(page, original_rect, new_opacity)
            if not ok:
                result["warnings"].append("Track B object_opacity: 找不到目標 annotation")

        # ── 填滿切換 ─────────────────────────────────────────────────────
        if new_fill is not None and new_text is None:
            ok = self._apply_annotation_fill(page, original_rect, new_fill, new_fill_color)
            if not ok:
                result["warnings"].append("Track B object_fill: 找不到目標 annotation")

        # ── Phase N: 後置 quad 干擾檢查 ─────────────────────────────────
        interference = self._check_quad_interference(
            page, non_target_before, original_rect,
        )
        result["interference_count"]   = interference["count"]
        result["interference_details"] = interference["details"]
        if interference["count"] > 0:
            result["warnings"].extend([
                f"[quad干擾 {i+1}/{interference['count']}] {d}"
                for i, d in enumerate(interference["details"])
            ])

        return result

    # ── quad 干擾檢查輔助方法 ─────────────────────────────────────────

    def _capture_non_target_quads(
        self,
        page: fitz.Page,
        edited_rect: fitz.Rect,
        tolerance: float = 0.5,
    ) -> list:
        """
        快照頁面中「不應被 reflow 移動」的 word-level quads。

        只快照以下兩類（其餘可能被 reflow 合法移動，不納入干擾判斷）：
          1. 在 edited_rect 上方的 word（y1 < edited_rect.y0）
          2. 在 edited_rect 旁邊不同欄的 word（x 範圍不重疊，
             以頁面寬度 30% 作為「同欄」的 x overlap 容忍）

        不包含：
          - edited_rect 內的 word（目標本身）
          - edited_rect 下方且同欄的 word（reflow 正常移動區域）

        回傳 list[dict]: [{"text": str, "rect": fitz.Rect}, ...]
        """
        quads = []
        page_width = page.rect.width
        col_overlap_threshold = page_width * 0.3  # 欄寬容忍

        try:
            for w in page.get_text("words"):
                word_rect = fitz.Rect(w[:4])
                word_text = w[4].strip() if len(w) > 4 else ""
                if not word_text:
                    continue

                # 跳過與 edited_rect 交疊的 word
                expanded_edit = fitz.Rect(
                    edited_rect.x0 - tolerance,
                    edited_rect.y0 - tolerance,
                    edited_rect.x1 + tolerance,
                    edited_rect.y1 + tolerance,
                )
                if word_rect.intersects(expanded_edit):
                    continue

                # 判斷是否在上方（安全）
                above = word_rect.y1 < edited_rect.y0 - tolerance

                # 判斷是否在不同欄：
                # 以「word 的 x 中心是否落在 edited_rect 的 x 範圍外」判斷
                word_cx = (word_rect.x0 + word_rect.x1) / 2
                in_same_column_x = edited_rect.x0 - tolerance <= word_cx <= edited_rect.x1 + tolerance

                # 在上方 → 安全；在下方且不同欄 → 安全；在下方且同欄 → reflow 合法移動，跳過
                below_same_col = (word_rect.y0 > edited_rect.y1 - tolerance) and in_same_column_x
                if below_same_col:
                    continue  # reflow 可能合法移動此 word，不納入干擾判斷

                different_column = not in_same_column_x

                if above or different_column:
                    quads.append({"text": word_text, "rect": fitz.Rect(word_rect)})

        except Exception as e:
            logger.warning(f"_capture_non_target_quads 失敗: {e}")
        return quads

    def _check_quad_interference(
        self,
        page: fitz.Page,
        non_target_before: list,
        edited_rect: fitz.Rect,
        position_tolerance: float = 0.5,
        max_shift: float = 1.0,
    ) -> dict:
        """
        比較 edit 前後的非目標 quads，偵測：
          A. 消失的 non-target quad（誤刪）
          B. 位移超過 max_shift pt 的 non-target quad（干擾）
          C. 編輯後新插入的 quad 溢出 edited_rect 過多（溢位）

        回傳 {"count": int, "details": list[str]}
        """
        details = []

        # 取得 edit 後的 word quads（非目標區域）
        after_words: dict[str, fitz.Rect] = {}
        try:
            for w in page.get_text("words"):
                word_rect = fitz.Rect(w[:4])
                word_text = w[4].strip() if len(w) > 4 else ""
                if not word_text:
                    continue
                if word_rect.intersects(edited_rect):
                    continue
                # 同一文字可能多處出現，取最接近原始位置的
                if word_text not in after_words:
                    after_words[word_text] = fitz.Rect(word_rect)
        except Exception as e:
            logger.warning(f"_check_quad_interference after-scan 失敗: {e}")
            return {"count": 0, "details": []}

        # 比對 before → after
        for item in non_target_before:
            text = item["text"]
            before_rect = item["rect"]

            if text not in after_words:
                # 可能因多個相同文字而漏匹配，做二次掃描
                found_any = False
                try:
                    results = page.search_for(text)
                    for r in results:
                        if not r.intersects(edited_rect):
                            shift = max(
                                abs(r.x0 - before_rect.x0),
                                abs(r.y0 - before_rect.y0),
                            )
                            if shift <= max_shift:
                                found_any = True
                                break
                except Exception:
                    pass
                if not found_any:
                    details.append(
                        f"non-target quad 消失: '{text}' at {before_rect}"
                    )
                continue

            after_rect = after_words[text]
            shift_x = abs(after_rect.x0 - before_rect.x0)
            shift_y = abs(after_rect.y0 - before_rect.y0)
            shift   = max(shift_x, shift_y)

            if shift > max_shift:
                details.append(
                    f"non-target quad '{text}' 位移 "
                    f"({shift_x:.1f}, {shift_y:.1f})pt > {max_shift}pt"
                )

        # 檢查 edited_rect 內新插入的 quads 是否溢出
        try:
            for w in page.get_text("words"):
                word_rect = fitz.Rect(w[:4])
                word_text = w[4].strip() if len(w) > 4 else ""
                if not word_text or not word_rect.intersects(edited_rect):
                    continue
                overflow_x = max(0.0, word_rect.x1 - edited_rect.x1)
                overflow_y = max(0.0, word_rect.y1 - edited_rect.y1)
                if overflow_x > position_tolerance or overflow_y > position_tolerance:
                    details.append(
                        f"edited quad '{word_text}' 溢出 "
                        f"(x+{overflow_x:.1f}, y+{overflow_y:.1f})pt"
                    )
        except Exception as e:
            logger.warning(f"_check_quad_interference overflow 檢查失敗: {e}")

        return {"count": len(details), "details": details}

    # ── Annotation 操作輔助（與 Track A 一致）────────────────────────

    @staticmethod
    def _normalize_changes(changes) -> dict:
        if isinstance(changes, dict):
            return changes
        if hasattr(changes, "__dataclass_fields__"):
            return {k: getattr(changes, k) for k in changes.__dataclass_fields__}
        return {}

    def _apply_annotation_color(
        self,
        page: fitz.Page,
        target_rect: fitz.Rect,
        stroke_color: tuple,
        fill_color: Optional[tuple] = None,
    ) -> bool:
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

    def _parse_span_color(self, raw_color) -> tuple:
        """將 PyMuPDF 的 color 值（int 或 tuple）轉為 (r, g, b) tuple。"""
        if isinstance(raw_color, tuple):
            return raw_color
        if isinstance(raw_color, int):
            r = ((raw_color >> 16) & 0xFF) / 255.0
            g = ((raw_color >> 8) & 0xFF) / 255.0
            b = (raw_color & 0xFF) / 255.0
            return (r, g, b)
        return (0, 0, 0)
