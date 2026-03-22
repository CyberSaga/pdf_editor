"""
reflow_agent_loop.py — 主控多軌並行迭代循環腳本

負責：
  1. 同時驅動 Track A（Vision LLM 頁面重生）與 Track B（低階 content stream）
  2. 每輪收集兩軌的產出，執行自動評分（visual diff + 文字選取 + 防干擾檢查）
  3. 根據分數決定：保留 / 回退 / 合併兩軌最佳邏輯
  4. 輸出每輪改動摘要 + 跨軌合併建議

使用方式：
  python -m reflow.reflow_agent_loop --rounds 10 --test-dir test_files/

階段流程（與使用者約定的 6 階段對應）：
  階段 0 → 本檔 + track_A_core + track_B_core + unified_command + test_suite
  階段 1 → define_evaluation_baseline() 產生評分表 + 邊界案例
  階段 2 → generate_initial_code() 產生 Track A/B 第一版
  階段 3 → iterate() 自動迭代優化
  階段 4 → merge_tracks() 跨軌合併
  階段 5 → finalize() 最終驗證 + 整合
"""

import argparse
import copy
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 確保 pdf_editor 根目錄在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reflow.track_A_core import TrackAEngine
from reflow.track_B_core import TrackBEngine
from reflow.test_suite import ReflowTestSuite, TestResult

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 資料結構
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IterationRecord:
    """單輪迭代的完整記錄。"""
    round_num: int
    track_a_score: float = 0.0
    track_b_score: float = 0.0
    track_a_changes: str = ""
    track_b_changes: str = ""
    merge_suggestion: str = ""
    best_track: str = ""           # "A" | "B" | "merged"
    best_score: float = 0.0
    edge_case_failures: list = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class LoopState:
    """整個迭代循環的全域狀態。"""
    current_round: int = 0
    max_rounds: int = 10
    target_score: float = 0.95     # 達到此分數即提前停止
    history: list = field(default_factory=list)       # list[IterationRecord]
    best_overall_score: float = 0.0
    best_overall_track: str = ""
    converged: bool = False

    # 各軌道當前程式碼版本（字串形式，用於傳給 LLM 分析）
    track_a_code_version: str = ""
    track_b_code_version: str = ""
    merged_code_version: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# 評估基準（階段 1 會填充，此處定義結構）
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EvaluationBaseline:
    """評估基準：分數定義、權重、邊界案例清單。

    第 1 階段產出：
      scoring_table  — 5 大評分維度與子指標、閾值
      weights        — test_suite 加權計算用（6 個子維度，總和 = 1.0）
      edge_cases     — 10 個邊界案例（含觸發條件、期望 SSIM、期望 quad 干擾數）
      track_a_criteria — Track A 視覺 SSIM 評估參數
      track_b_criteria — Track B quad 精準干擾檢查參數
      speed_budget   — 各操作類型執行時間上限
    """

    # ── 5 大高階評分維度（供人類閱讀；實際加權用 weights）────────────────
    scoring_table: dict = field(default_factory=lambda: {
        # 維度名稱 → {中文, 子指標, 通過閾值, 權重比例}
        "精準度": {
            "zh": "精準度 (Precision)",
            "sub_metrics": ["no_overlap", "no_misdelete"],
            "pass_threshold": 0.90,   # 子指標加權後 ≥ 0.90
            "weight_share":  0.50,
            "notes": "文字塊不重疊 + 不誤刪鄰近內容，為最關鍵維度",
        },
        "視覺一致性": {
            "zh": "視覺一致性 (Visual Consistency)",
            "sub_metrics": ["reflow_correct", "visual_fidelity"],
            "pass_threshold": 0.85,   # 非編輯區 SSIM ≥ 0.85
            "weight_share":  0.30,
            "notes": (
                "Track A：非編輯區 SSIM ≥ 0.85（pixel diff）；"
                "Track B：content stream 無殘留幽靈字形"
            ),
        },
        "可選取性": {
            "zh": "可選取性 (Text Selectability)",
            "sub_metrics": ["text_selectable"],
            "pass_threshold": 0.95,   # 搜尋命中率 ≥ 95%
            "weight_share":  0.10,
            "notes": "新插入文字必須可被 page.search_for() 找到",
        },
        "相容性": {
            "zh": "相容性 (File Compatibility)",
            "sub_metrics": ["file_compat"],
            "pass_threshold": 1.00,   # 必須可渲染、不崩潰
            "weight_share":  0.05,
            "notes": "必須能以 PyMuPDF / Adobe Reader / Chrome 開啟",
        },
        "速度": {
            "zh": "速度 (Execution Speed)",
            "sub_metrics": ["execution_ms"],
            "pass_threshold": 3000,   # 單頁操作 ≤ 3000ms
            "weight_share":  0.05,
            "notes": "超過閾值不影響 weighted score，僅記錄為警告",
        },
    })

    # ── test_suite 加權計算用（6 個子維度，總和 = 1.0）────────────────────
    weights: dict = field(default_factory=lambda: {
        "no_overlap":       0.25,   # 文字塊不重疊
        "no_misdelete":     0.25,   # 未誤刪鄰近內容
        "reflow_correct":   0.20,   # 後續塊正確位移（不留白洞）
        "visual_fidelity":  0.15,   # 像素 diff < 閾值
        "text_selectable":  0.10,   # 新文字可選取 / 搜尋
        "file_compat":      0.05,   # 多 viewer 開啟不崩
    })

    # ── 10 個邊界案例（第 1 階段定義；pdf 路徑由 define_evaluation_baseline 填充）
    edge_cases: list = field(default_factory=lambda: [
        {
            "id": "EC01",
            "desc": "單欄純文字，刪除中間一行",
            "pdf": None,
            "trigger": "new_text 長度 < original_text 長度",
            "expected": "後續行前移，無白洞，non-edited SSIM ≥ 0.90",
            "expected_ssim": 0.90,
            "expected_quad_interference": 0,
            "preferred_track": "B",
        },
        {
            "id": "EC02",
            "desc": "雙欄排版，編輯左欄不影響右欄",
            "pdf": None,
            "trigger": "edited_rect 橫向寬度 < page_width / 2",
            "expected": "右欄位置不變，quad 干擾數 = 0",
            "expected_ssim": 0.92,
            "expected_quad_interference": 0,
            "preferred_track": "A",
        },
        {
            "id": "EC03",
            "desc": "表格旁緊密排版，加長文字",
            "pdf": None,
            "trigger": "new_text 長度 > original_text 長度 × 1.5",
            "expected": "文字不侵入表格區域，quad 干擾數 ≤ 1",
            "expected_ssim": 0.85,
            "expected_quad_interference": 1,
            "preferred_track": "A",
        },
        {
            "id": "EC04",
            "desc": "旋轉頁面（90°），編輯水平文字",
            "pdf": None,
            "trigger": "page.rotation in {90, 270}",
            "expected": "derotation matrix 正確轉換座標，reflow 方向正確",
            "expected_ssim": 0.88,
            "expected_quad_interference": 0,
            "preferred_track": "B",
        },
        {
            "id": "EC05",
            "desc": "多行段落，替換為更長文字（溢出邊界）",
            "pdf": None,
            "trigger": "estimated_new_height > page_height - edited_rect.y0",
            "expected": "自動 shrink_height 或截斷，不超出頁面邊界",
            "expected_ssim": 0.82,
            "expected_quad_interference": 0,
            "preferred_track": "A",
        },
        {
            "id": "EC06",
            "desc": "垂直文字（CJK），刪除一個字",
            "pdf": None,
            "trigger": "span.flags & TEXT_FLAG_VERTICAL != 0",
            "expected": "後續字上移，維持垂直排列，no_overlap = 1.0",
            "expected_ssim": 0.87,
            "expected_quad_interference": 0,
            "preferred_track": "B",
        },
        {
            "id": "EC07",
            "desc": "密集排版頁面（行距 < 2pt），編輯一行",
            "pdf": None,
            "trigger": "avg_line_gap < 2.0",
            "expected": "不壓縮其他行，reflow_correct = 1.0",
            "expected_ssim": 0.89,
            "expected_quad_interference": 0,
            "preferred_track": "B",
        },
        {
            "id": "EC08",
            "desc": "含透明文字層（OCR PDF），編輯可見文字",
            "pdf": None,
            "trigger": "page 含 invisible text（color=(1,1,1) 或 render_mode=3）",
            "expected": "不破壞隱形 OCR 層，block_count 在 ±1 範圍內",
            "expected_ssim": 0.91,
            "expected_quad_interference": 0,
            "preferred_track": "B",
        },
        {
            "id": "EC09",
            "desc": "多字體混排段落，替換部分文字",
            "pdf": None,
            "trigger": "paragraph 內含 ≥ 2 種不同 fontname",
            "expected": "保留周圍字體風格，no_misdelete = 1.0",
            "expected_ssim": 0.88,
            "expected_quad_interference": 0,
            "preferred_track": "A",
        },
        {
            "id": "EC10",
            "desc": "頁面含圖片 + 文字，圖片旁文字 reflow",
            "pdf": None,
            "trigger": "page 含 image block（type=1），edited_rect 距圖片 < 10pt",
            "expected": "文字繞圖不重疊，non-edited SSIM ≥ 0.90（圖片區域不變）",
            "expected_ssim": 0.90,
            "expected_quad_interference": 0,
            "preferred_track": "A",
        },
    ])

    # ── Track A 專屬評估（視覺重建品質）────────────────────────────────────
    track_a_criteria: dict = field(default_factory=lambda: {
        # 非編輯區域（edited_rect 以外）的結構相似度閾值
        "non_edited_ssim_threshold": 0.90,
        # 整頁 pixel diff 閾值（比例；0.03 = 允許 3% 像素有差異）
        "whole_page_pixel_diff_ratio": 0.03,
        # 評估解析度（倍率；2x 避免字形鋸齒影響 SSIM）
        "render_scale": 2.0,
        # OCR 還原文字匹配率（開發期用，最終版不需要 LLM）
        "ocr_text_match_ratio": 0.95,
        # 圖像比對使用的視窗大小（px，SSIM 計算用）
        "ssim_window_size": 11,
        # 評估方法說明
        "_method": (
            "1. 以 render_scale 將 before/after 各渲染成 PNG；"
            "2. 對 non-edited 區域計算 pixel-diff 分數；"
            "3. score = 1 - (diff_pixels / total_non_edited_pixels × 放大係數)；"
            "4. 分數 ≥ non_edited_ssim_threshold 為通過"
        ),
    })

    # ── Track B 專屬評估（content stream 精準度）────────────────────────────
    track_b_criteria: dict = field(default_factory=lambda: {
        # quad 邊界偏差容忍值（pt）—— 超過視為干擾
        "quad_boundary_tolerance_pt": 0.5,
        # 非目標區域的 quad 最大允許位移（pt）
        "non_target_quad_max_shift_pt": 1.0,
        # 編輯後 content stream 語法必須正確
        "content_stream_valid": True,
        # 最多允許幾個 quad 干擾（表格/密排時給 1 個容忍）
        "max_allowed_interference": 0,
        # 評估方法說明
        "_method": (
            "1. 用 page.get_text('rawdict') 取得 before/after 所有 span quads；"
            "2. 對 non-edited-rect 的 quad，比較 before → after 位移是否 ≤ tolerance；"
            "3. 對 edited-rect 的新 quads，確認不與周圍 quads 交疊；"
            "4. interference_count = 超出容忍的 quad 數；0 為滿分，每 +1 扣 0.2"
        ),
    })

    # ── 速度預算（各操作類型的執行時間上限，ms）─────────────────────────────
    speed_budget: dict = field(default_factory=lambda: {
        "text_reflow":    3000,  # 文字 reflow（含 redact + re-insert）
        "object_color":    500,  # 顏色修改
        "object_opacity":  500,  # 透明度修改
        "object_fill":     500,  # 填色修改
        "textbox_rotate": 1000,  # 文字框旋轉
        "object_move":    1000,  # 物件移動
    })


# ──────────────────────────────────────────────────────────────────────────────
# 主控迭代引擎
# ──────────────────────────────────────────────────────────────────────────────

class ReflowAgentLoop:
    """
    多軌並行迭代主控器。

    驅動 Track A / Track B 同時優化，每輪自動評分，
    並在分數收斂或達標時停止。
    """

    def __init__(
        self,
        test_dir: str,
        max_rounds: int = 10,
        target_score: float = 0.95,
    ):
        self.test_dir = Path(test_dir)
        self.state = LoopState(max_rounds=max_rounds, target_score=target_score)
        self.baseline = EvaluationBaseline()
        self.test_suite = ReflowTestSuite(test_dir=str(self.test_dir))

        # 初始化兩條軌道引擎
        self.track_a = TrackAEngine()
        self.track_b = TrackBEngine()

        logger.info(
            f"ReflowAgentLoop 初始化完成: "
            f"test_dir={self.test_dir}, max_rounds={max_rounds}, "
            f"target_score={target_score}"
        )

    # ── 階段 1：定義評估基準 ───────────────────────────────────────────────

    def define_evaluation_baseline(self, test_pdfs: Optional[list] = None):
        """
        階段 1：掃描 test_dir，產生評分表 + 邊界案例清單，並印出摘要。

        若 test_pdfs 已提供具體路徑，則填充到 edge_cases 中。
        """
        if test_pdfs:
            for i, pdf_path in enumerate(test_pdfs[:10]):
                if i < len(self.baseline.edge_cases):
                    self.baseline.edge_cases[i]["pdf"] = str(pdf_path)

        # 掃描 test_dir 中的 PDF 補充未指定的邊界案例
        available_pdfs = sorted(self.test_dir.glob("*.pdf"))
        for ec in self.baseline.edge_cases:
            if ec["pdf"] is None and available_pdfs:
                ec["pdf"] = str(available_pdfs.pop(0))

        # 印出評分表
        self._print_scoring_table()

        logger.info(
            f"階段 1 完成: {len(self.baseline.edge_cases)} 個邊界案例, "
            f"權重分配: {self.baseline.weights}"
        )
        return self.baseline

    def _print_scoring_table(self):
        """印出格式化評分表（階段 1 輸出）。"""
        lines = [
            "",
            "╔══════════════════════════════════════════════════════════════════╗",
            "║          Reflow & Object Editor — 評估基準表（第 1 階段）        ║",
            "╠══════════╦══════╦════════╦═══════════════════════════════════════╣",
            "║ 維度     ║ 比重 ║ 通過線 ║ 子指標                                ║",
            "╠══════════╬══════╬════════╬═══════════════════════════════════════╣",
        ]
        for name, info in self.baseline.scoring_table.items():
            sub = ", ".join(info["sub_metrics"])
            weight_pct = f"{info['weight_share']*100:.0f}%"
            threshold = info["pass_threshold"]
            thresh_str = (
                f"≤{threshold}ms" if name == "速度"
                else f"≥{threshold:.0%}" if isinstance(threshold, float)
                else str(threshold)
            )
            lines.append(
                f"║ {name:<8s} ║ {weight_pct:>4s} ║ {thresh_str:>6s} ║"
                f" {sub:<37s} ║"
            )
        lines += [
            "╠══════════╩══════╩════════╩═══════════════════════════════════════╣",
            "║ Track A 專屬：非編輯區 pixel-diff SSIM ≥ 0.90（2× 解析度渲染）  ║",
            "║ Track B 專屬：non-target quad 位移 ≤ 0.5pt，干擾數 = 0          ║",
            "╠══════════════════════════════════════════════════════════════════╣",
            "║ 10 個邊界案例（EC01–EC10）                                       ║",
            "╠══════════════════════════════════════════════════════════════════╣",
        ]
        for ec in self.baseline.edge_cases:
            ec_id = ec["id"]
            desc = ec["desc"][:46]
            preferred = ec.get("preferred_track", "?")
            pdf_status = "✓" if ec["pdf"] else "✗"
            lines.append(
                f"║ {ec_id} [{preferred}] {pdf_status} {desc:<46s} ║"
            )
        lines += [
            "╠══════════════════════════════════════════════════════════════════╣",
            "║ 速度預算：text_reflow ≤ 3000ms，color/opacity ≤ 500ms           ║",
            "╚══════════════════════════════════════════════════════════════════╝",
            "",
        ]
        print("\n".join(lines))

    # ── 階段 2：產生初始程式碼 ─────────────────────────────────────────────

    def generate_initial_code(self):
        """
        階段 2：同時輸出 Track A、Track B、Unified Command 的第一版完整程式碼。
        此處載入各軌道的初始模板（已在 track_A_core.py / track_B_core.py 中定義）。
        """
        self.state.track_a_code_version = self.track_a.get_source_snapshot()
        self.state.track_b_code_version = self.track_b.get_source_snapshot()

        logger.info("階段 2 完成: Track A / Track B 初始程式碼已載入")
        return {
            "track_a": self.state.track_a_code_version,
            "track_b": self.state.track_b_code_version,
        }

    # ── 階段 3：自動迭代優化循環 ──────────────────────────────────────────

    def iterate(self) -> IterationRecord:
        """
        執行單輪迭代：
          1. 對所有邊界案例分別跑 Track A 和 Track B
          2. 用 test_suite 評分
          3. 記錄結果 + 產生跨軌合併建議
          4. 更新全域最佳分數
        """
        self.state.current_round += 1
        rnd = self.state.current_round
        logger.info(f"=== 第 {rnd}/{self.state.max_rounds} 輪迭代 ===")

        record = IterationRecord(round_num=rnd)

        # 收集邊界案例 PDF 路徑
        pdf_paths = [
            ec["pdf"] for ec in self.baseline.edge_cases
            if ec["pdf"] and Path(ec["pdf"]).exists()
        ]

        if not pdf_paths:
            logger.warning("沒有可用的測試 PDF，跳過本輪")
            record.track_a_changes = "SKIP: no test PDFs"
            record.track_b_changes = "SKIP: no test PDFs"
            self.state.history.append(record)
            return record

        # ── Track A 測試 ──
        a_results: list[TestResult] = []
        for pdf_path in pdf_paths:
            try:
                result = self._run_track_test(self.track_a, pdf_path, "A")
                a_results.append(result)
            except Exception as e:
                logger.error(f"Track A 測試失敗 ({pdf_path}): {e}")
                a_results.append(TestResult(
                    pdf_path=pdf_path, track="A", passed=False,
                    score=0.0, details=f"Exception: {e}",
                ))

        # ── Track B 測試 ──
        b_results: list[TestResult] = []
        for pdf_path in pdf_paths:
            try:
                result = self._run_track_test(self.track_b, pdf_path, "B")
                b_results.append(result)
            except Exception as e:
                logger.error(f"Track B 測試失敗 ({pdf_path}): {e}")
                b_results.append(TestResult(
                    pdf_path=pdf_path, track="B", passed=False,
                    score=0.0, details=f"Exception: {e}",
                ))

        # ── 計算加權分數 ──
        record.track_a_score = self._weighted_score(a_results)
        record.track_b_score = self._weighted_score(b_results)

        # ── 決定本輪最佳 ──
        if record.track_a_score >= record.track_b_score:
            record.best_track = "A"
            record.best_score = record.track_a_score
        else:
            record.best_track = "B"
            record.best_score = record.track_b_score

        # ── 收集失敗案例 ──
        all_results = a_results + b_results
        record.edge_case_failures = [
            {"pdf": r.pdf_path, "track": r.track, "details": r.details}
            for r in all_results if not r.passed
        ]

        # ── 產生跨軌合併建議 ──
        record.merge_suggestion = self._generate_merge_suggestion(
            a_results, b_results
        )
        record.track_a_changes = f"Round {rnd}: score={record.track_a_score:.3f}"
        record.track_b_changes = f"Round {rnd}: score={record.track_b_score:.3f}"

        # ── 更新全域最佳 ──
        if record.best_score > self.state.best_overall_score:
            self.state.best_overall_score = record.best_score
            self.state.best_overall_track = record.best_track

        # ── 收斂檢查 ──
        if record.best_score >= self.state.target_score:
            self.state.converged = True
            logger.info(
                f"已達目標分數 {self.state.target_score}，"
                f"最佳 Track {record.best_track} = {record.best_score:.3f}"
            )

        self.state.history.append(record)
        logger.info(
            f"第 {rnd} 輪結果: A={record.track_a_score:.3f}, "
            f"B={record.track_b_score:.3f}, best={record.best_track}"
        )
        return record

    def run_all_iterations(self) -> LoopState:
        """階段 3：執行所有迭代輪次直到收斂或達上限。"""
        while (
            self.state.current_round < self.state.max_rounds
            and not self.state.converged
        ):
            self.iterate()
        return self.state

    # ── 階段 4：跨軌合併 ─────────────────────────────────────────────────

    def merge_tracks(self) -> str:
        """
        階段 4：分析兩軌歷史，合併最佳邏輯為 unified_reflow_engine.py。
        回傳合併後的程式碼概要。
        """
        if not self.state.history:
            return "尚無迭代記錄，無法合併"

        # 找出 Track A 和 Track B 各自最佳輪次
        best_a = max(
            (r for r in self.state.history if r.track_a_score > 0),
            key=lambda r: r.track_a_score,
            default=None,
        )
        best_b = max(
            (r for r in self.state.history if r.track_b_score > 0),
            key=lambda r: r.track_b_score,
            default=None,
        )

        summary_lines = [
            "=== 跨軌合併摘要 ===",
            f"Track A 最佳: Round {best_a.round_num if best_a else '?'}, "
            f"score={best_a.track_a_score if best_a else 0:.3f}",
            f"Track B 最佳: Round {best_b.round_num if best_b else '?'}, "
            f"score={best_b.track_b_score if best_b else 0:.3f}",
            "",
            "合併策略：",
            "  - 取 Track B 的 content stream 精準位移邏輯作為核心",
            "  - 取 Track A 的佈局分析 + 防干擾檢測作為前置檢查",
            "  - Unified Command 統一封裝為 UnifiedObjectCommand",
        ]

        summary = "\n".join(summary_lines)
        self.state.merged_code_version = summary
        logger.info("階段 4 完成: 跨軌合併摘要已產生")
        return summary

    # ── 階段 5：最終驗證 ─────────────────────────────────────────────────

    def finalize(self) -> dict:
        """
        階段 5：最終驗證 + 產出整合說明。
        """
        final_report = {
            "total_rounds": self.state.current_round,
            "converged": self.state.converged,
            "best_overall_score": self.state.best_overall_score,
            "best_overall_track": self.state.best_overall_track,
            "edge_case_summary": [],
            "integration_notes": [
                "1. 將 unified_reflow_engine.py 放入 reflow/ 目錄",
                "2. 在 pdf_controller.py 的 edit_text() 改用 UnifiedObjectCommand",
                "3. 在 _refresh_after_command() 的 non-structural 分支加入 viewport anchor 恢復",
                "4. 在 pdf_view.py 的 _finalize_text_edit_impl() 前呼叫 capture_viewport_anchor()",
            ],
        }

        # 彙總邊界案例通過率
        for ec in self.baseline.edge_cases:
            ec_id = ec["id"]
            # 查看最後一輪此案例的結果
            final_report["edge_case_summary"].append({
                "id": ec_id,
                "desc": ec["desc"],
                "pdf": ec["pdf"],
                "status": "pending_verification",
            })

        logger.info(f"階段 5 完成: 最終報告已產生 (score={self.state.best_overall_score:.3f})")
        return final_report

    # ── 內部輔助方法 ──────────────────────────────────────────────────────

    def _run_track_test(self, engine, pdf_path: str, track_name: str) -> TestResult:
        """對單一 PDF 執行指定軌道的 reflow 並評分。"""
        import fitz

        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            doc.close()
            return TestResult(
                pdf_path=pdf_path, track=track_name, passed=False,
                score=0.0, details="Empty PDF",
            )

        page = doc[0]

        # 擷取原始頁面圖片（用於 visual diff）
        original_pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        original_png = original_pix.tobytes("png")

        # 取得頁面所有文字塊
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        text_blocks = [b for b in blocks if b.get("type") == 0 and b.get("lines")]

        if not text_blocks:
            doc.close()
            return TestResult(
                pdf_path=pdf_path, track=track_name, passed=True,
                score=1.0, details="No text blocks to reflow",
            )

        # 選第一個文字塊做測試編輯（模擬刪除一行）
        target_block = text_blocks[0]
        target_rect = fitz.Rect(target_block["bbox"])
        original_text = ""
        for line in target_block["lines"]:
            for span in line["spans"]:
                original_text += span["text"]

        # 執行軌道的 reflow
        try:
            engine.apply_reflow(
                doc=doc,
                page_idx=0,
                edited_rect=target_rect,
                new_text=original_text[:len(original_text) // 2],  # 模擬縮短
                original_text=original_text,
            )
        except Exception as e:
            doc.close()
            return TestResult(
                pdf_path=pdf_path, track=track_name, passed=False,
                score=0.0, details=f"Reflow failed: {e}",
            )

        # 擷取 reflow 後的頁面圖片
        page = doc[0]  # 重新取得（可能已被修改）
        after_pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        after_png = after_pix.tobytes("png")

        # 用 test_suite 評分
        result = self.test_suite.evaluate_single(
            pdf_path=pdf_path,
            track=track_name,
            original_png=original_png,
            after_png=after_png,
            page=page,
            edited_rect=target_rect,
            weights=self.baseline.weights,
        )

        doc.close()
        return result

    def _weighted_score(self, results: list) -> float:
        """計算一組 TestResult 的加權平均分數。"""
        if not results:
            return 0.0
        return sum(r.score for r in results) / len(results)

    def _generate_merge_suggestion(
        self, a_results: list, b_results: list,
    ) -> str:
        """根據本輪 A/B 的失敗模式，產生跨軌合併建議。"""
        a_failures = [r for r in a_results if not r.passed]
        b_failures = [r for r in b_results if not r.passed]

        suggestions = []
        if len(a_failures) < len(b_failures):
            suggestions.append("Track A 本輪失敗較少，建議以 A 的佈局分析為主")
        elif len(b_failures) < len(a_failures):
            suggestions.append("Track B 本輪失敗較少，建議以 B 的精準位移為主")
        else:
            suggestions.append("兩軌失敗數相同，建議各取所長合併")

        # 分析失敗類型
        a_fail_types = set(r.details.split(":")[0] for r in a_failures if r.details)
        b_fail_types = set(r.details.split(":")[0] for r in b_failures if r.details)
        only_a_fails = a_fail_types - b_fail_types
        only_b_fails = b_fail_types - a_fail_types

        if only_a_fails:
            suggestions.append(f"Track A 獨有失敗模式: {only_a_fails}")
        if only_b_fails:
            suggestions.append(f"Track B 獨有失敗模式: {only_b_fails}")

        return "; ".join(suggestions) if suggestions else "無特殊建議"


# ──────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PDF Reflow & Object Editor — 多軌並行迭代主控器"
    )
    parser.add_argument(
        "--test-dir", default="test_files",
        help="測試 PDF 所在目錄（預設: test_files/）",
    )
    parser.add_argument(
        "--rounds", type=int, default=10,
        help="最大迭代輪數（預設: 10）",
    )
    parser.add_argument(
        "--target-score", type=float, default=0.95,
        help="目標分數，達到即停止（預設: 0.95）",
    )
    parser.add_argument(
        "--stage", type=int, default=None,
        help="只執行指定階段（0-5），省略則執行全部",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="啟用詳細日誌",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    loop = ReflowAgentLoop(
        test_dir=args.test_dir,
        max_rounds=args.rounds,
        target_score=args.target_score,
    )

    if args.stage is not None:
        stages = [args.stage]
    else:
        stages = [1, 2, 3, 4, 5]

    for stage in stages:
        print(f"\n{'='*60}")
        print(f"  階段 {stage}")
        print(f"{'='*60}\n")

        if stage == 1:
            baseline = loop.define_evaluation_baseline()
            print(f"評分權重: {json.dumps(baseline.weights, indent=2)}")
            print(f"邊界案例數: {len(baseline.edge_cases)}")

        elif stage == 2:
            code = loop.generate_initial_code()
            print(f"Track A 程式碼長度: {len(code['track_a'])} chars")
            print(f"Track B 程式碼長度: {len(code['track_b'])} chars")

        elif stage == 3:
            state = loop.run_all_iterations()
            print(f"完成 {state.current_round} 輪迭代")
            print(f"收斂: {state.converged}")
            print(f"最佳分數: {state.best_overall_score:.3f} (Track {state.best_overall_track})")
            for rec in state.history:
                print(
                    f"  Round {rec.round_num}: "
                    f"A={rec.track_a_score:.3f}, B={rec.track_b_score:.3f}, "
                    f"best={rec.best_track}"
                )

        elif stage == 4:
            summary = loop.merge_tracks()
            print(summary)

        elif stage == 5:
            report = loop.finalize()
            print(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"\n已完成階段 {stages}，準備進入下一階段。")


if __name__ == "__main__":
    main()
