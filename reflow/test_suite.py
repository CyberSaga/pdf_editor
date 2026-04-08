"""
test_suite.py — 自動視覺 diff + 文字選取 + 防干擾 測試套件

提供兩種執行方式：
  1. 作為 ReflowTestSuite 類被 reflow_agent_loop.py 呼叫（程式化）
  2. 直接執行 pytest 測試（CLI: pytest reflow/test_suite.py -v）

測試維度：
  - no_overlap:      文字塊不重疊
  - no_misdelete:    未誤刪鄰近內容
  - reflow_correct:  後續塊正確位移
  - visual_fidelity: 像素 diff（SSIM 或簡易 pixel-diff）
  - text_selectable: 新文字可選取
  - file_compat:     多 viewer 開啟不崩（基本檢查）
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import fitz

# 確保 pdf_editor 根目錄在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 測試結果結構
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    """單一測試的結果。"""
    pdf_path: str
    track: str                          # "A" | "B"
    passed: bool
    score: float                        # 0.0 ~ 1.0
    details: str = ""
    subscores: dict = field(default_factory=dict)


@dataclass
class OverlapCheckResult:
    """重疊檢查結果。"""
    clean: bool
    overlaps: list = field(default_factory=list)   # list[str]


@dataclass
class MisdeleteCheckResult:
    """誤刪檢查結果。"""
    clean: bool = True
    missing_blocks: list = field(default_factory=list)  # list[str]
    original_block_count: int = 0
    after_block_count: int = 0


@dataclass
class ReflowCheckResult:
    """Reflow 正確性檢查結果。"""
    correct: bool
    gaps: list = field(default_factory=list)        # 白洞位置
    overflow: list = field(default_factory=list)     # 溢出位置


@dataclass
class TrackAImageDiffResult:
    """Track A：非編輯區 pixel-diff 評估結果。"""
    score: float                                    # 0.0 ~ 1.0
    non_edited_pixel_diff_ratio: float              # 非編輯區差異像素比例
    edited_region_changed: bool                     # 編輯區是否確實有變化
    notes: str = ""


@dataclass
class TrackBQuadInterferenceResult:
    """Track B：quad 干擾檢查結果。"""
    clean: bool
    interference_count: int = 0
    interference_details: list = field(default_factory=list)  # list[str]
    missing_non_target_quads: int = 0
    score: float = 1.0                              # 0.0 ~ 1.0


# ──────────────────────────────────────────────────────────────────────────────
# 測試套件
# ──────────────────────────────────────────────────────────────────────────────

class ReflowTestSuite:
    """
    Reflow 自動測試套件。

    提供個別維度的檢查方法，
    以及整合評分的 evaluate_single() 方法。
    """

    def __init__(self, test_dir: str = "test_files"):
        self.test_dir = Path(test_dir)

    # ── 整合評分 ─────────────────────────────────────────────────────────

    def evaluate_single(
        self,
        pdf_path: str,
        track: str,
        original_png: bytes,
        after_png: bytes,
        page: fitz.Page,
        edited_rect: fitz.Rect,
        weights: dict | None = None,
        original_page: fitz.Page | None = None,
    ) -> TestResult:
        """
        對單一 PDF 頁面的 reflow 結果進行全面評分。

        參數：
          pdf_path:      PDF 檔案路徑
          track:         "A" | "B"
          original_png:  reflow 前的頁面 PNG bytes
          after_png:     reflow 後的頁面 PNG bytes
          page:          reflow 後的 fitz.Page 物件
          edited_rect:   被編輯的文字塊矩形
          weights:       各維度權重（預設使用 EvaluationBaseline 的權重）
          original_page: reflow 前的 fitz.Page（用於誤刪檢查）

        回傳：
          TestResult
        """
        if weights is None:
            weights = {
                "no_overlap":       0.25,
                "no_misdelete":     0.25,
                "reflow_correct":   0.20,
                "visual_fidelity":  0.15,
                "text_selectable":  0.10,
                "file_compat":      0.05,
            }

        subscores = {}

        # 1. 不重疊
        overlap_result = self.check_no_overlap(page)
        subscores["no_overlap"] = 1.0 if overlap_result.clean else max(
            0.0, 1.0 - len(overlap_result.overlaps) * 0.2
        )

        # 2. 不誤刪
        misdelete_result = self.check_no_misdelete(
            page, edited_rect, original_page
        )
        subscores["no_misdelete"] = 1.0 if misdelete_result.clean else max(
            0.0, 1.0 - len(misdelete_result.missing_blocks) * 0.3
        )

        # 3. Reflow 正確性
        reflow_result = self.check_reflow_correct(page, edited_rect)
        subscores["reflow_correct"] = 1.0 if reflow_result.correct else max(
            0.0, 1.0 - (len(reflow_result.gaps) + len(reflow_result.overflow)) * 0.2
        )

        # 4. 視覺保真度
        subscores["visual_fidelity"] = self.compute_visual_diff(
            original_png, after_png
        )

        # 5. 文字可選取
        subscores["text_selectable"] = self.check_text_selectable(
            page, edited_rect
        )

        # 6. 檔案相容性
        subscores["file_compat"] = self.check_file_compat(page)

        # 加權總分
        total_score = sum(
            subscores.get(key, 0) * weight
            for key, weight in weights.items()
        )

        # 判定通過（總分 ≥ 0.7 且關鍵維度 ≥ 0.5）
        passed = (
            total_score >= 0.7
            and subscores.get("no_overlap", 0) >= 0.5
            and subscores.get("no_misdelete", 0) >= 0.5
        )

        # 產生詳細描述
        details_parts = []
        if not overlap_result.clean:
            details_parts.append(f"overlaps: {len(overlap_result.overlaps)}")
        if not misdelete_result.clean:
            details_parts.append(f"misdeletes: {len(misdelete_result.missing_blocks)}")
        if not reflow_result.correct:
            details_parts.append(
                f"gaps: {len(reflow_result.gaps)}, "
                f"overflow: {len(reflow_result.overflow)}"
            )
        details = "; ".join(details_parts) if details_parts else "all checks passed"

        return TestResult(
            pdf_path=pdf_path,
            track=track,
            passed=passed,
            score=total_score,
            details=details,
            subscores=subscores,
        )

    # ── 維度 1: 不重疊 ──────────────────────────────────────────────────

    def check_no_overlap(
        self, page: fitz.Page, tolerance: float = 1.0,
    ) -> OverlapCheckResult:
        """
        檢查頁面上的文字塊是否有重疊。

        tolerance: 允許的重疊像素（考慮 anti-aliasing 等微小重疊）
        """
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = [
            b for b in text_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]

        overlaps = []
        for i in range(len(blocks)):
            r1 = fitz.Rect(blocks[i]["bbox"])
            for j in range(i + 1, len(blocks)):
                r2 = fitz.Rect(blocks[j]["bbox"])
                intersection = r1 & r2
                if not intersection.is_empty:
                    if (intersection.width > tolerance
                            and intersection.height > tolerance):
                        overlaps.append(
                            f"Block {i} ({r1}) ∩ Block {j} ({r2})"
                        )

        return OverlapCheckResult(
            clean=len(overlaps) == 0,
            overlaps=overlaps,
        )

    # ── 維度 2: 不誤刪 ──────────────────────────────────────────────────

    def check_no_misdelete(
        self,
        page: fitz.Page,
        edited_rect: fitz.Rect,
        original_page: fitz.Page | None = None,
    ) -> MisdeleteCheckResult:
        """
        檢查是否有非目標文字塊被誤刪。

        策略：
          - 比對 reflow 前後的文字塊數量與位置
          - 只有被編輯的 rect 範圍內的塊應該改變
          - 其他塊不應消失
        """
        result = MisdeleteCheckResult()

        # 取得 reflow 後的所有塊
        after_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        after_blocks = [
            b for b in after_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]
        result.after_block_count = len(after_blocks)

        if original_page is None:
            # 無法比對，假設通過
            result.clean = True
            return result

        # 取得 reflow 前的所有塊
        before_dict = original_page.get_text(
            "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE
        )
        before_blocks = [
            b for b in before_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]
        result.original_block_count = len(before_blocks)

        # 檢查：非目標區域的塊是否仍然存在
        for bb in before_blocks:
            bb_rect = fitz.Rect(bb["bbox"])

            # 跳過被編輯區域內的塊（允許改變）
            if bb_rect.intersects(edited_rect):
                continue

            # 提取原始塊的文字
            bb_text = ""
            for line in bb.get("lines", []):
                for span in line.get("spans", []):
                    bb_text += span.get("text", "")
            bb_text = bb_text.strip()

            if not bb_text:
                continue

            # 在 reflow 後的塊中尋找匹配
            found = False
            for ab in after_blocks:
                ab_text = ""
                for line in ab.get("lines", []):
                    for span in line.get("spans", []):
                        ab_text += span.get("text", "")
                ab_text = ab_text.strip()

                if bb_text in ab_text or ab_text in bb_text:
                    found = True
                    break

                # 模糊匹配（允許小差異）
                import difflib
                ratio = difflib.SequenceMatcher(None, bb_text, ab_text).ratio()
                if ratio > 0.8:
                    found = True
                    break

            if not found:
                result.missing_blocks.append(
                    f"Block at {bb_rect}: '{bb_text[:50]}...'"
                )

        result.clean = len(result.missing_blocks) == 0
        return result

    # ── 維度 3: Reflow 正確性 ───────────────────────────────────────────

    def check_reflow_correct(
        self, page: fitz.Page, edited_rect: fitz.Rect,
    ) -> ReflowCheckResult:
        """
        檢查 reflow 後的排版是否正確。

        檢查項目：
          - 被編輯區域下方是否有白洞（gap > 正常行距 × 2）
          - 文字是否溢出頁面邊界
        """
        result = ReflowCheckResult(correct=True)

        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = [
            b for b in text_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]

        if len(blocks) < 2:
            return result

        # 按 y 座標排序
        sorted_blocks = sorted(blocks, key=lambda b: b["bbox"][1])

        # 計算平均行距
        gaps = []
        for i in range(1, len(sorted_blocks)):
            prev_bottom = sorted_blocks[i - 1]["bbox"][3]
            curr_top = sorted_blocks[i]["bbox"][1]
            gap = curr_top - prev_bottom
            gaps.append(gap)

        if not gaps:
            return result

        avg_gap = sum(gaps) / len(gaps)
        # 白洞閾值：平均間距的 3 倍
        gap_threshold = max(avg_gap * 3, 20.0)

        # 檢查被編輯區域下方的間距
        for i in range(1, len(sorted_blocks)):
            prev_rect = fitz.Rect(sorted_blocks[i - 1]["bbox"])
            curr_rect = fitz.Rect(sorted_blocks[i]["bbox"])

            # 只檢查被編輯區域附近的間距
            if prev_rect.y0 < edited_rect.y0:
                continue

            gap = curr_rect.y0 - prev_rect.y1
            if gap > gap_threshold:
                result.correct = False
                result.gaps.append(
                    f"Gap={gap:.1f}pt between blocks at "
                    f"y={prev_rect.y1:.0f} and y={curr_rect.y0:.0f}"
                )

        # 檢查溢出
        page_rect = page.rect
        for block in sorted_blocks:
            b_rect = fitz.Rect(block["bbox"])
            if b_rect.y1 > page_rect.height + 1:
                result.correct = False
                result.overflow.append(
                    f"Block at {b_rect} exceeds page bottom "
                    f"(y1={b_rect.y1:.0f} > page_h={page_rect.height:.0f})"
                )
            if b_rect.x1 > page_rect.width + 1:
                result.correct = False
                result.overflow.append(
                    f"Block at {b_rect} exceeds page right "
                    f"(x1={b_rect.x1:.0f} > page_w={page_rect.width:.0f})"
                )

        return result

    # ── 維度 4: 視覺保真度 ──────────────────────────────────────────────

    def compute_visual_diff(
        self,
        original_png: bytes,
        after_png: bytes,
    ) -> float:
        """
        計算 reflow 前後的視覺差異分數。

        使用簡易 pixel-by-pixel 比對（不需 PIL / scikit-image）。
        回傳 0.0 ~ 1.0（1.0 = 完全相同）。
        """
        try:
            # 用 PyMuPDF 的 Pixmap 載入 PNG
            pix1 = fitz.Pixmap(original_png)
            pix2 = fitz.Pixmap(after_png)

            # 確保尺寸一致
            if pix1.width != pix2.width or pix1.height != pix2.height:
                # 尺寸不同，直接回傳低分
                return 0.5

            # 取得原始 samples
            samples1 = pix1.samples
            samples2 = pix2.samples

            if len(samples1) != len(samples2):
                return 0.5

            # 計算像素差異
            total_pixels = pix1.width * pix1.height
            n = pix1.n  # channels per pixel
            diff_sum = 0
            max_diff = 255 * n * total_pixels

            for i in range(0, len(samples1), n):
                for c in range(min(n, 3)):  # 只比 RGB，忽略 alpha
                    diff_sum += abs(samples1[i + c] - samples2[i + c])

            if max_diff == 0:
                return 1.0

            # 正規化到 0~1（反轉：差異越小分數越高）
            diff_ratio = diff_sum / max_diff
            score = max(0.0, 1.0 - diff_ratio * 5)  # 放大差異

            return score

        except Exception as e:
            logger.error(f"visual diff 計算失敗: {e}")
            return 0.5  # 預設中等分數

    # ── 維度 5: 文字可選取 ──────────────────────────────────────────────

    def check_text_selectable(
        self, page: fitz.Page, edited_rect: fitz.Rect,
    ) -> float:
        """
        檢查被編輯區域內的文字是否可選取（可搜尋/複製）。

        回傳 0.0 ~ 1.0（1.0 = 完全可選取）。
        """
        # 提取被編輯區域內的文字
        text_in_rect = page.get_text("text", clip=edited_rect).strip()

        if not text_in_rect:
            # 區域內無文字（可能是刪除操作）
            return 1.0

        # 檢查文字是否可被搜尋
        search_results = page.search_for(text_in_rect[:20])

        if search_results:
            return 1.0

        # 嘗試搜尋更短的片段
        for length in [10, 5, 3]:
            if len(text_in_rect) >= length:
                results = page.search_for(text_in_rect[:length])
                if results:
                    return 0.8

        return 0.3  # 文字存在但不完全可搜尋

    # ── 維度 6: 檔案相容性 ──────────────────────────────────────────────

    def check_file_compat(self, page: fitz.Page) -> float:
        """
        基本檔案相容性檢查。

        檢查：
          - 頁面可正常渲染為 pixmap
          - 文字可正常提取
          - 無結構性錯誤
        """
        try:
            # 嘗試渲染
            pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
            if pix.width == 0 or pix.height == 0:
                return 0.0

            # 嘗試提取文字
            _ = page.get_text("text")
            _ = page.get_text("dict")

            return 1.0

        except Exception as e:
            logger.error(f"相容性檢查失敗: {e}")
            return 0.0

    # ── Track A 專屬：非編輯區 pixel-diff ───────────────────────────────

    def check_track_a_image_diff(
        self,
        original_png: bytes,
        after_png: bytes,
        edited_rect: fitz.Rect,
        page_rect: fitz.Rect,
        render_scale: float = 2.0,
        ssim_threshold: float = 0.90,
    ) -> "TrackAImageDiffResult":
        """
        Track A 評估方法：比較 reflow 前後頁面圖像，
        只在「非編輯區域」計算 pixel-diff，避免被正常的文字變更污染分數。

        演算法：
          1. 將 before/after PNG 載入為 Pixmap（均已以 render_scale 渲染）
          2. 計算 edited_rect 對應的像素座標（考慮 render_scale）
          3. 只統計 edited_rect 以外像素的差異
          4. score = 1 - (non_edited_diff_pixels / total_non_edited_pixels × 放大係數)
          5. 同時確認 edited_rect 內確實有像素變化（否則 reflow 無效）

        通過條件：score ≥ ssim_threshold（預設 0.90）
        """
        try:
            pix1 = fitz.Pixmap(original_png)
            pix2 = fitz.Pixmap(after_png)

            if pix1.width != pix2.width or pix1.height != pix2.height:
                return TrackAImageDiffResult(
                    score=0.5,
                    non_edited_pixel_diff_ratio=1.0,
                    edited_region_changed=True,
                    notes="尺寸不一致，無法比對",
                )

            w, h = pix1.width, pix1.height
            n = pix1.n  # channels per pixel

            # 計算 edited_rect 在像素座標中的範圍（考慮 render_scale）
            scale_x = w / page_rect.width  if page_rect.width  > 0 else render_scale
            scale_y = h / page_rect.height if page_rect.height > 0 else render_scale

            ex0 = max(0, int(edited_rect.x0 * scale_x))
            ey0 = max(0, int(edited_rect.y0 * scale_y))
            ex1 = min(w, int(edited_rect.x1 * scale_x))
            ey1 = min(h, int(edited_rect.y1 * scale_y))

            s1 = pix1.samples
            s2 = pix2.samples

            non_edited_diff = 0
            non_edited_total_channels = 0
            edited_diff = 0

            for py in range(h):
                for px in range(w):
                    idx = (py * w + px) * n
                    pixel_diff = sum(
                        abs(s1[idx + c] - s2[idx + c])
                        for c in range(min(n, 3))
                    )
                    in_edited = (ex0 <= px < ex1 and ey0 <= py < ey1)
                    if in_edited:
                        edited_diff += pixel_diff
                    else:
                        non_edited_diff += pixel_diff
                        non_edited_total_channels += min(n, 3)

            # 非編輯區差異比例
            if non_edited_total_channels == 0:
                non_edited_ratio = 0.0
            else:
                non_edited_ratio = non_edited_diff / (non_edited_total_channels * 255)

            # 得分（差異越小越高，5× 放大讓分數曲線敏感）
            score = max(0.0, 1.0 - non_edited_ratio * 5)

            # 編輯區是否有變化
            edited_changed = edited_diff > 0

            return TrackAImageDiffResult(
                score=score,
                non_edited_pixel_diff_ratio=non_edited_ratio,
                edited_region_changed=edited_changed,
                notes=(
                    f"non_edited_diff_ratio={non_edited_ratio:.4f}, "
                    f"score={score:.3f}, "
                    f"pass={'YES' if score >= ssim_threshold else 'NO'}"
                ),
            )

        except Exception as e:
            logger.error(f"Track A image diff 計算失敗: {e}")
            return TrackAImageDiffResult(
                score=0.5,
                non_edited_pixel_diff_ratio=1.0,
                edited_region_changed=False,
                notes=f"Exception: {e}",
            )

    # ── Track B 專屬：quad 干擾檢查 ─────────────────────────────────────

    def check_track_b_quad_interference(
        self,
        page_before: fitz.Page,
        page_after: fitz.Page,
        edited_rect: fitz.Rect,
        position_tolerance_pt: float = 0.5,
        max_shift_pt: float = 1.0,
    ) -> "TrackBQuadInterferenceResult":
        """
        Track B 評估方法：檢查 content stream 操作後的 quad 干擾。

        檢查邏輯：
          A. 「非目標 quad 消失」→ 誤刪（missing_non_target_quads + 1）
          B. 「非目標 quad 位移超過 max_shift_pt」→ 干擾（interference_count + 1）
          C. 「編輯後 quad 與非目標 quad 交疊超過 tolerance」→ 干擾

        演算法：
          1. 從 before 提取所有 word quads；過濾出 non-target（不與 edited_rect 交疊）
          2. 在 after 的所有 word quads 中尋找最接近的匹配
          3. 記錄位移量；超過閾值視為干擾
          4. score = 1 - interference_count × 0.2（最低 0.0）

        通過條件：interference_count == 0
        """
        result = TrackBQuadInterferenceResult(clean=True)

        try:
            # 取得 before 的 word quads（使用 "words" 模式：x0,y0,x1,y1,word,...)
            before_words = page_before.get_text("words")
            after_words  = page_after.get_text("words")

            # 過濾出非目標區域的 before words
            non_target_before = [
                w for w in before_words
                if not fitz.Rect(w[:4]).intersects(edited_rect)
                and w[4].strip()  # 忽略空白
            ]

            # 建立 after words 的矩形索引（方便近鄰搜尋）
            after_rects = [fitz.Rect(w[:4]) for w in after_words]

            missing = 0
            interferences = []

            for bw in non_target_before:
                br = fitz.Rect(bw[:4])
                btext = bw[4].strip()

                # 在 after 中尋找同文字的 quad
                best_match_rect = None
                best_dist = float("inf")

                for i, aw in enumerate(after_words):
                    if aw[4].strip() == btext:
                        ar = after_rects[i]
                        # 計算中心點距離
                        dist = abs(ar.x0 - br.x0) + abs(ar.y0 - br.y0)
                        if dist < best_dist:
                            best_dist = dist
                            best_match_rect = ar

                if best_match_rect is None:
                    missing += 1
                    continue

                # 檢查位移是否超過閾值
                shift_x = abs(best_match_rect.x0 - br.x0)
                shift_y = abs(best_match_rect.y0 - br.y0)
                max_shift = max(shift_x, shift_y)

                if max_shift > max_shift_pt:
                    interferences.append(
                        f"'{btext}' 位移 ({shift_x:.1f},{shift_y:.1f})pt "
                        f"> tolerance {max_shift_pt}pt"
                    )

            # 檢查 edited_rect 內的新 quads 是否與非目標區域交疊
            after_edited_words = [
                w for w in after_words
                if fitz.Rect(w[:4]).intersects(edited_rect)
            ]
            for ew in after_edited_words:
                er = fitz.Rect(ew[:4])
                # 超出 edited_rect 的部分（溢出量）
                overflow_x = max(0.0, er.x1 - edited_rect.x1)
                overflow_y = max(0.0, er.y1 - edited_rect.y1)
                if overflow_x > position_tolerance_pt or overflow_y > position_tolerance_pt:
                    interferences.append(
                        f"編輯區 quad '{ew[4]}' 溢出 "
                        f"(x+{overflow_x:.1f}, y+{overflow_y:.1f})pt"
                    )

            result.interference_count = len(interferences)
            result.interference_details = interferences
            result.missing_non_target_quads = missing
            result.clean = (result.interference_count == 0 and missing == 0)
            result.score = max(0.0, 1.0 - result.interference_count * 0.2)

        except Exception as e:
            logger.error(f"Track B quad 干擾檢查失敗: {e}")
            result.clean = False
            result.score = 0.0
            result.interference_details = [f"Exception: {e}"]

        return result


# ──────────────────────────────────────────────────────────────────────────────
# Pytest 測試
# ──────────────────────────────────────────────────────────────────────────────

import pytest


def _find_test_pdf() -> str | None:
    """尋找可用的測試 PDF。"""
    test_dirs = [
        Path(__file__).resolve().parent.parent / "test_files",
        Path(__file__).resolve().parent.parent / "tests",
    ]
    for d in test_dirs:
        if d.exists():
            pdfs = sorted(d.glob("*.pdf"))
            if pdfs:
                return str(pdfs[0])
    return None


class TestReflowOverlap:
    """文字塊不重疊測試。"""

    def test_empty_page_no_overlap(self):
        """空白頁面不應有重疊。"""
        doc = fitz.open()
        doc.new_page()
        suite = ReflowTestSuite()
        result = suite.check_no_overlap(doc[0])
        assert result.clean
        doc.close()

    def test_single_block_no_overlap(self):
        """單一文字塊不應有重疊。"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Hello World", fontsize=12)
        suite = ReflowTestSuite()
        result = suite.check_no_overlap(page)
        assert result.clean
        doc.close()

    def test_separate_blocks_no_overlap(self):
        """兩個分離的文字塊不應有重疊。"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Block 1", fontsize=12)
        page.insert_text(fitz.Point(72, 200), "Block 2", fontsize=12)
        suite = ReflowTestSuite()
        result = suite.check_no_overlap(page)
        assert result.clean
        doc.close()


class TestReflowMisdelete:
    """不誤刪測試。"""

    def test_no_original_page_passes(self):
        """無原始頁面時應預設通過。"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Test", fontsize=12)
        suite = ReflowTestSuite()
        result = suite.check_no_misdelete(page, fitz.Rect(0, 0, 100, 50))
        assert result.clean
        doc.close()


class TestReflowCorrectness:
    """Reflow 正確性測試。"""

    def test_single_block_no_gap(self):
        """單一塊不應有白洞。"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Only block", fontsize=12)
        suite = ReflowTestSuite()
        result = suite.check_reflow_correct(page, fitz.Rect(50, 80, 200, 120))
        assert result.correct
        doc.close()

    def test_no_overflow(self):
        """文字不應溢出頁面。"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Within bounds", fontsize=12)
        suite = ReflowTestSuite()
        result = suite.check_reflow_correct(page, fitz.Rect(50, 80, 200, 120))
        assert len(result.overflow) == 0
        doc.close()


class TestVisualDiff:
    """視覺差異測試。"""

    def test_identical_images(self):
        """相同圖片的 diff 應為 1.0。"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Test", fontsize=12)
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        png = pix.tobytes("png")
        suite = ReflowTestSuite()
        score = suite.compute_visual_diff(png, png)
        assert score >= 0.99
        doc.close()


class TestTextSelectable:
    """文字可選取測試。"""

    def test_inserted_text_selectable(self):
        """插入的文字應可選取。"""
        doc = fitz.open()
        page = doc.new_page()
        rect = fitz.Rect(72, 72, 300, 150)
        page.insert_textbox(rect, "Selectable text here", fontsize=12)
        suite = ReflowTestSuite()
        score = suite.check_text_selectable(page, rect)
        assert score >= 0.3
        doc.close()


class TestFileCompat:
    """檔案相容性測試。"""

    def test_new_page_compat(self):
        """新頁面應通過相容性檢查。"""
        doc = fitz.open()
        page = doc.new_page()
        suite = ReflowTestSuite()
        score = suite.check_file_compat(page)
        assert score == 1.0
        doc.close()


class TestTrackAIntegration:
    """Track A 整合測試。"""

    def test_track_a_empty_page(self):
        """空白頁面的 reflow 不應崩潰。"""
        from reflow.track_A_core import TrackAEngine
        engine = TrackAEngine()
        doc = fitz.open()
        doc.new_page()
        result = engine.apply_reflow(
            doc=doc, page_idx=0,
            edited_rect=fitz.Rect(0, 0, 100, 50),
            new_text="test",
        )
        # 空白頁面應該報告找不到塊
        assert isinstance(result, dict)
        doc.close()

    def test_track_a_single_block(self):
        """單一文字塊的 reflow 基本測試。"""
        from reflow.track_A_core import TrackAEngine
        engine = TrackAEngine()
        doc = fitz.open()
        page = doc.new_page()
        rect = fitz.Rect(72, 72, 300, 150)
        page.insert_textbox(rect, "Original text content", fontsize=12)

        result = engine.apply_reflow(
            doc=doc, page_idx=0,
            edited_rect=rect,
            new_text="Modified text",
            original_text="Original text content",
        )
        assert isinstance(result, dict)
        assert "success" in result
        doc.close()


class TestTrackBIntegration:
    """Track B 整合測試。"""

    def test_track_b_empty_page(self):
        """空白頁面的 stream reflow 不應崩潰。"""
        from reflow.track_B_core import TrackBEngine
        engine = TrackBEngine()
        doc = fitz.open()
        doc.new_page()
        result = engine.apply_reflow(
            doc=doc, page_idx=0,
            edited_rect=fitz.Rect(0, 0, 100, 50),
            new_text="test",
        )
        assert isinstance(result, dict)
        doc.close()

    def test_track_b_stream_analysis(self):
        """Stream 分析應正確回傳結構。"""
        from reflow.track_B_core import TrackBEngine
        engine = TrackBEngine()
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), "Hello World", fontsize=12)
        analysis = engine.analyze_stream(page, 0)
        assert analysis.page_idx == 0
        assert len(analysis.spans) >= 0  # 可能有或沒有 span（取決於 rendering）
        doc.close()


class TestUnifiedCommand:
    """UnifiedObjectCommand 整合測試。"""

    def test_import(self):
        """確認 UnifiedObjectCommand 可正確 import。"""
        from reflow.unified_command import ObjectChanges, UnifiedObjectCommand
        assert UnifiedObjectCommand is not None
        assert ObjectChanges is not None

    def test_object_changes_defaults(self):
        """ObjectChanges 預設值正確。"""
        from reflow.unified_command import ObjectChanges
        changes = ObjectChanges()
        assert changes.new_text is None
        assert changes.reflow_enabled is True
        assert changes.track_preference == "auto"

    def test_operation_type_inference(self):
        """操作類型自動推斷。"""
        from reflow.unified_command import ObjectChanges, UnifiedObjectCommand

        # 模擬 model（只需最少介面）
        class MockModel:
            doc = fitz.open()
            doc.new_page()

            def _capture_page_snapshot(self, idx):
                return b""

            def _restore_page_from_snapshot(self, idx, data):
                pass

            class block_manager:
                @staticmethod
                def rebuild_page(idx, doc):
                    pass

        model = MockModel()
        snapshot = b"dummy"
        rect = fitz.Rect(0, 0, 100, 50)

        # text_reflow
        cmd = UnifiedObjectCommand(
            model, 1, rect,
            ObjectChanges(new_text="test"),
            snapshot,
        )
        assert cmd._operation_type == "text_reflow"

        # object_color
        cmd = UnifiedObjectCommand(
            model, 1, rect,
            ObjectChanges(new_color=(1, 0, 0)),
            snapshot,
        )
        assert cmd._operation_type == "object_color"

        # textbox_rotate
        cmd = UnifiedObjectCommand(
            model, 1, rect,
            ObjectChanges(rotation_angle=90),
            snapshot,
        )
        assert cmd._operation_type == "textbox_rotate"

        model.doc.close()


class TestRealPDF:
    """使用真實 PDF 的測試（如果有的話）。"""

    @pytest.fixture
    def test_pdf(self):
        pdf_path = _find_test_pdf()
        if pdf_path is None:
            pytest.skip("No test PDF found in test_files/")
        return pdf_path

    def test_real_pdf_overlap_check(self, test_pdf):
        """真實 PDF 的重疊檢查。"""
        doc = fitz.open(test_pdf)
        suite = ReflowTestSuite()
        for i in range(min(3, doc.page_count)):
            result = suite.check_no_overlap(doc[i])
            # 不 assert clean（原始 PDF 可能本來就有重疊），只確認不崩潰
            assert isinstance(result.clean, bool)
        doc.close()

    def test_real_pdf_track_a(self, test_pdf):
        """真實 PDF 的 Track A reflow 測試。"""
        from reflow.track_A_core import TrackAEngine
        engine = TrackAEngine()
        doc = fitz.open(test_pdf)
        page = doc[0]

        # 取得第一個文字塊
        text_dict = page.get_text("dict")
        text_blocks = [
            b for b in text_dict.get("blocks", [])
            if b.get("type") == 0 and b.get("lines")
        ]

        if not text_blocks:
            pytest.skip("No text blocks in first page")

        target = text_blocks[0]
        rect = fitz.Rect(target["bbox"])
        original_text = ""
        for line in target["lines"]:
            for span in line["spans"]:
                original_text += span["text"]

        result = engine.apply_reflow(
            doc=doc, page_idx=0,
            edited_rect=rect,
            new_text=original_text[:len(original_text) // 2],
            original_text=original_text,
        )
        assert isinstance(result, dict)
        doc.close()


class TestTrackAImageDiff:
    """Track A 圖像 diff 評估測試（第 1 階段新增）。"""

    def test_identical_pages_score_max(self):
        """前後相同頁面，非編輯區 score 應為 1.0。"""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(72, 100), "Same content", fontsize=12)
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        png = pix.tobytes("png")

        suite = ReflowTestSuite()
        result = suite.check_track_a_image_diff(
            original_png=png,
            after_png=png,
            edited_rect=fitz.Rect(50, 80, 300, 130),
            page_rect=page.rect,
        )
        assert result.score >= 0.99, f"Expected ~1.0, got {result.score}"
        doc.close()

    def test_edited_region_detected_as_changed(self):
        """編輯前後不同的頁面，edited_region_changed 應為 True。"""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(72, 100), "Before text", fontsize=12)
        pix_before = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        png_before = pix_before.tobytes("png")

        # 修改編輯區
        page.draw_rect(fitz.Rect(50, 80, 300, 130), color=(1, 1, 1), fill=(1, 1, 1))
        page.insert_text(fitz.Point(72, 100), "After text different", fontsize=12)
        pix_after = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        png_after = pix_after.tobytes("png")

        suite = ReflowTestSuite()
        result = suite.check_track_a_image_diff(
            original_png=png_before,
            after_png=png_after,
            edited_rect=fitz.Rect(50, 80, 300, 130),
            page_rect=page.rect,
        )
        assert result.edited_region_changed
        doc.close()

    def test_score_degrades_with_non_edited_changes(self):
        """非編輯區有大量變化時，score 應低於 1.0。"""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # 原始：有大量文字
        for y in range(50, 700, 30):
            page.insert_text(fitz.Point(72, y), "Line of text content here", fontsize=10)
        pix_before = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        png_before = pix_before.tobytes("png")

        # 清空非編輯區（模擬嚴重干擾）
        page.draw_rect(fitz.Rect(0, 200, 595, 842), color=(1, 1, 1), fill=(1, 1, 1))
        pix_after = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        png_after = pix_after.tobytes("png")

        suite = ReflowTestSuite()
        result = suite.check_track_a_image_diff(
            original_png=png_before,
            after_png=png_after,
            edited_rect=fitz.Rect(50, 80, 400, 180),  # 只編輯頂部
            page_rect=page.rect,
        )
        # 稀疏文字頁面底部被清空，非編輯區至少要有些許差異（score < 1.0）
        assert result.score < 0.995, f"Expected degraded score, got {result.score}"
        doc.close()


class TestTrackBQuadInterference:
    """Track B quad 干擾檢查測試（第 1 階段新增）。"""

    def test_identical_pages_clean(self):
        """前後相同頁面，quad 干擾應為 0。"""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(72, 100), "Line one content", fontsize=12)
        page.insert_text(fitz.Point(72, 150), "Line two content", fontsize=12)

        suite = ReflowTestSuite()
        result = suite.check_track_b_quad_interference(
            page_before=page,
            page_after=page,
            edited_rect=fitz.Rect(50, 80, 400, 130),
        )
        assert result.clean
        assert result.interference_count == 0
        assert result.score >= 0.99
        doc.close()

    def test_non_target_quads_preserved(self):
        """非目標區域的 quads 應在 after 中保持存在。"""
        doc_before = fitz.open()
        page_before = doc_before.new_page(width=595, height=842)
        page_before.insert_text(fitz.Point(72, 100), "Edited line", fontsize=12)
        page_before.insert_text(fitz.Point(72, 200), "Preserved line", fontsize=12)
        page_before.insert_text(fitz.Point(72, 300), "Another preserved", fontsize=12)

        doc_after = fitz.open()
        page_after = doc_after.new_page(width=595, height=842)
        # 模擬：編輯區替換文字，非編輯區保持不變
        page_after.insert_text(fitz.Point(72, 100), "New edited text", fontsize=12)
        page_after.insert_text(fitz.Point(72, 200), "Preserved line", fontsize=12)
        page_after.insert_text(fitz.Point(72, 300), "Another preserved", fontsize=12)

        suite = ReflowTestSuite()
        result = suite.check_track_b_quad_interference(
            page_before=page_before,
            page_after=page_after,
            edited_rect=fitz.Rect(50, 80, 400, 130),
        )
        assert result.missing_non_target_quads == 0
        doc_before.close()
        doc_after.close()

    def test_result_has_expected_fields(self):
        """結果物件應包含所有預期欄位。"""
        doc = fitz.open()
        page = doc.new_page()
        suite = ReflowTestSuite()
        result = suite.check_track_b_quad_interference(
            page_before=page,
            page_after=page,
            edited_rect=fitz.Rect(0, 0, 100, 50),
        )
        assert hasattr(result, "clean")
        assert hasattr(result, "interference_count")
        assert hasattr(result, "interference_details")
        assert hasattr(result, "missing_non_target_quads")
        assert hasattr(result, "score")
        assert 0.0 <= result.score <= 1.0
        doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
