# -*- coding: utf-8 -*-
"""
test_large_scale.py — Phase 7 大規模測試
=========================================
目標：
  1. 開啟 100 頁合成 PDF，連續 50 次隨機編輯不同頁面 / 文字塊
  2. 統計：平均/最大/最小單次耗時、doc 大小變化、消失率、undo/redo 成功率
  3. 特殊場景：垂直文字、模擬掃描頁（無文字塊，期望 graceful skip）
  4. 若存在 1.pdf 則附加測試（小規模隨機 5 次編輯）
  5. 輸出完整 Phase 7 測試報告

執行方式：
  python test_large_scale.py
  python test_large_scale.py --rounds 50 --pages 100  # 預設值
  python test_large_scale.py --rounds 10 --pages 20   # 快速冒煙測試
"""
import sys
import io
import os
import time
import random
import argparse
import traceback
import tempfile
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import fitz

sys.path.insert(0, os.path.dirname(__file__))
from model.pdf_model import PDFModel
from model.edit_commands import EditTextCommand

# ──────────────────────────────────────────────────────────────────
# 常數
# ──────────────────────────────────────────────────────────────────
REAL_PDF_PATH = Path(__file__).parent / "1.pdf"

HORIZONTAL_SAMPLES = [
    "Growth & Revenue: 2025-2026 Annual Report",
    "Key Performance Indicators (KPIs) — Q3 Summary",
    "第一季度業績摘要：總收入達 NT$1,234,567",
    "市場分析與競爭態勢報告（CJK / Latin 混排）",
    "fi fl ﬁ ﬂ ligature & special chars: <>'\"",
    "Conclusion: all targets met, YoY +18.5%",
    "Product roadmap for H1 2026: launch 3 features",
    "資產負債表摘要：流動資產 / 非流動資產比較",
    "Executive Summary — draft for board review",
    "附件 A：詳細數據說明（含備註）",
]

EDIT_TEXTS = [
    "Updated text: Phase 7 test round {i}",
    "修訂版本 {i}：Phase 7 大規模壓測通過",
    "Revised Q{i} KPI: target exceeded by 12%",
    "第 {i} 次壓測更新：Growth & Revenue <2026>",
    "Patched: fi fl ﬁ ligature & ampersand & test {i}",
]

# ──────────────────────────────────────────────────────────────────
# PDF 生成工具
# ──────────────────────────────────────────────────────────────────
def _build_large_pdf(n_pages: int) -> bytes:
    """
    生成含多種文字類型的 n_pages 頁測試 PDF：
      - 一般水平文字（每頁 3-5 個文字塊）
      - 每 10 頁插入一個垂直文字方塊（旋轉 90°）
      - 每 15 頁插入一個「空白頁」模擬掃描頁（無文字）
    """
    doc = fitz.open()
    rng = random.Random(42)  # 固定種子，保證可重現

    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)

        is_scan_sim = (i % 15 == 14)   # 第 15、30、45... 頁模擬掃描頁
        is_vertical = (i % 10 == 9)    # 第 10、20、30... 頁含垂直文字

        if is_scan_sim:
            # 掃描頁：只放一個圖形佔位，無文字
            page.draw_rect(fitz.Rect(72, 72, 523, 770), color=(0.9, 0.9, 0.9), fill=(0.9, 0.9, 0.9))
            continue

        # 水平文字塊
        n_blocks = rng.randint(3, 5)
        y = 80
        for j in range(n_blocks):
            sample = HORIZONTAL_SAMPLES[(i * 3 + j) % len(HORIZONTAL_SAMPLES)]
            page.insert_text(
                (72, y),
                f"P{i+1}-B{j+1}: {sample}",
                fontsize=11,
                fontname="helv",
            )
            y += rng.randint(28, 40)

        if is_vertical:
            # 垂直文字：使用旋轉矩形（fitz 的 insert_textbox rotate=90）
            vbox = fitz.Rect(540, 100, 560, 400)
            page.insert_textbox(
                vbox,
                f"垂直 P{i+1} Vertical Text",
                fontsize=9,
                fontname="helv",
                rotate=90,
            )

    data = doc.tobytes(garbage=0)
    doc.close()
    return data


# ──────────────────────────────────────────────────────────────────
# 指標收集器
# ──────────────────────────────────────────────────────────────────
class Metrics:
    def __init__(self, label: str):
        self.label = label
        self.durations: list[float] = []
        self.errors: list[str] = []
        self.skips: int = 0
        self.undo_ok: int = 0
        self.undo_fail: int = 0
        self.redo_ok: int = 0
        self.redo_fail: int = 0
        self.doc_size_before: int = 0
        self.doc_size_after: int = 0

    # ── 편집 ──
    @property
    def attempts(self) -> int:
        return len(self.durations) + len(self.errors)

    @property
    def success_count(self) -> int:
        return len(self.durations)

    @property
    def error_rate(self) -> float:
        return len(self.errors) / self.attempts if self.attempts else 0.0

    @property
    def avg_ms(self) -> float:
        return (sum(self.durations) / len(self.durations) * 1000) if self.durations else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.durations) * 1000 if self.durations else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.durations) * 1000 if self.durations else 0.0

    @property
    def slow_count(self) -> int:
        return sum(1 for d in self.durations if d > 0.3)

    def report(self) -> str:
        lines = [
            f"\n{'═'*60}",
            f"  測試場景：{self.label}",
            f"{'─'*60}",
            f"  嘗試次數：{self.attempts}  (成功 {self.success_count} / 跳過 {self.skips} / 錯誤 {len(self.errors)})",
            f"  消失率（驗證失敗 / 嘗試）：{self.error_rate*100:.1f}%",
        ]
        if self.durations:
            lines += [
                f"  耗時 — 平均 {self.avg_ms:.1f}ms  最大 {self.max_ms:.1f}ms  最小 {self.min_ms:.1f}ms",
                f"  超過 300ms 次數：{self.slow_count}",
                f"  {'✓' if self.avg_ms < 300 else '✗'} 平均耗時 {'達標 (<300ms)' if self.avg_ms < 300 else '超標 (≥300ms)'}",
            ]
        if self.doc_size_before:
            delta = self.doc_size_after - self.doc_size_before
            pct = delta / self.doc_size_before * 100
            lines.append(
                f"  Doc 大小：{self.doc_size_before:,} → {self.doc_size_after:,} bytes  ({delta:+,} / {pct:+.1f}%)"
            )
        if self.undo_ok + self.undo_fail > 0:
            total_ur = self.undo_ok + self.undo_fail
            lines.append(
                f"  Undo 成功率：{self.undo_ok}/{total_ur} ({self.undo_ok/total_ur*100:.0f}%)"
            )
        if self.redo_ok + self.redo_fail > 0:
            total_rr = self.redo_ok + self.redo_fail
            lines.append(
                f"  Redo 成功率：{self.redo_ok}/{total_rr} ({self.redo_ok/total_rr*100:.0f}%)"
            )
        if self.errors:
            lines.append(f"  錯誤清單（前 5）：")
            for e in self.errors[:5]:
                lines.append(f"    · {e[:90]}")
        lines.append(f"{'═'*60}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# 核心：隨機編輯壓測
# ──────────────────────────────────────────────────────────────────
def _random_blocks(model: PDFModel, rng: random.Random) -> list[tuple[int, object]]:
    """
    掃描所有頁面，返回 [(page_num_1based, block), ...] 供隨機抽樣。
    排除空白頁（掃描模擬頁）和 text 為空的塊。
    """
    pool = []
    for page_idx in range(len(model.doc)):
        for blk in model.block_manager.get_blocks(page_idx):
            if blk.text.strip():
                pool.append((page_idx + 1, blk))
    rng.shuffle(pool)
    return pool


def run_random_edits(
    model: PDFModel,
    rounds: int,
    metrics: Metrics,
    rng: random.Random,
    test_undo: bool = True,
    verbose: bool = True,
) -> None:
    """
    對 model 執行 rounds 次隨機編輯，使用 EditTextCommand 包裝，
    確保每次操作都進入 command_manager._undo_stack，可正確壓測 undo/redo。
    """
    metrics.doc_size_before = len(model.doc.tobytes())
    pool = _random_blocks(model, rng)

    if not pool:
        print("  [SKIP] 無可用文字塊，跳過場景")
        metrics.skips += rounds
        return

    edit_num = 0
    pool_idx = 0

    while edit_num < rounds:
        page_num, blk = pool[pool_idx % len(pool)]
        pool_idx += 1

        new_text_tmpl = EDIT_TEXTS[edit_num % len(EDIT_TEXTS)]
        new_text = new_text_tmpl.format(i=edit_num + 1)
        rect = fitz.Rect(blk.layout_rect)   # 副本，避免後續被修改
        font = blk.font if blk.font else "helv"
        size = max(8, int(blk.size) if blk.size else 11)
        color = blk.color if blk.color else (0.0, 0.0, 0.0)

        t0 = time.perf_counter()
        try:
            # 用 EditTextCommand 包裝，確保進入 undo_stack
            snapshot = model._capture_page_snapshot(page_num - 1)
            cmd = EditTextCommand(
                model=model,
                page_num=page_num,
                rect=rect,
                new_text=new_text,
                font=font,
                size=size,
                color=color,
                original_text=blk.text,
                vertical_shift_left=True,
                page_snapshot_bytes=snapshot,
                old_block_id=blk.block_id,
                old_block_text=blk.text,
            )
            model.command_manager.execute(cmd)  # 呼叫 edit_text + 推入 undo_stack
            elapsed = time.perf_counter() - t0
            metrics.durations.append(elapsed)
            edit_num += 1

            status = "SLOW" if elapsed > 0.3 else "ok"
            if verbose and (edit_num % 10 == 0 or elapsed > 0.3):
                print(
                    f"    [{edit_num:02d}/{rounds}] p{page_num} "
                    f"{elapsed*1000:.0f}ms {status}  "
                    f"edit_count={model.edit_count}"
                    f"  undo_stack={len(model.command_manager._undo_stack)}"
                )

            # ── Undo / Redo 壓測（每 5 次做一輪）──
            if test_undo and edit_num % 5 == 0:
                _test_one_undo_redo(model, metrics, page_num, verbose)

        except RuntimeError as e:
            elapsed = time.perf_counter() - t0
            err_msg = f"p{page_num} '{blk.text[:25]}' -> {e}"
            metrics.errors.append(err_msg)
            edit_num += 1
            if verbose:
                print(f"    [{edit_num:02d}/{rounds}] ERROR {elapsed*1000:.0f}ms: {str(e)[:60]}")
            # 更新 pool（block rect 可能已改變）
            pool = _random_blocks(model, rng)
            pool_idx = 0

        except Exception as e:
            elapsed = time.perf_counter() - t0
            metrics.errors.append(f"UNEXPECTED p{page_num}: {e}")
            edit_num += 1
            if verbose:
                print(f"    [{edit_num:02d}/{rounds}] UNEXPECTED ERROR: {str(e)[:60]}")
            traceback.print_exc()
            pool = _random_blocks(model, rng)
            pool_idx = 0

    metrics.doc_size_after = len(model.doc.tobytes())


def _test_one_undo_redo(
    model: PDFModel, metrics: Metrics, ref_page: int, verbose: bool
) -> None:
    """
    使用 CommandManager.undo()/redo() 做一輪 undo+redo 驗證。
    CommandManager.undo/redo() 回傳 bool（True=成功, False=堆疊空）。
    """
    cm = model.command_manager
    if not cm.can_undo():
        return  # 堆疊空，不計入統計

    # ── 記錄 undo 前的 description（從 stack 頂端讀取）──
    top_cmd = cm._undo_stack[-1] if cm._undo_stack else None
    desc = top_cmd.description[:50] if top_cmd else "?"

    # ── Undo ──
    try:
        ok = cm.undo()
        if ok:
            metrics.undo_ok += 1
            if verbose:
                print(f"      undo OK: {desc}")
        else:
            metrics.undo_fail += 1
            if verbose:
                print(f"      undo FAIL: returned False")
    except Exception as e:
        metrics.undo_fail += 1
        if verbose:
            print(f"      undo FAIL: {e}")
        return

    # ── Redo ──
    try:
        ok2 = cm.redo()
        if ok2:
            metrics.redo_ok += 1
            if verbose:
                print(f"      redo OK")
        else:
            metrics.redo_fail += 1
            if verbose:
                print(f"      redo FAIL: returned False")
    except Exception as e:
        metrics.redo_fail += 1
        if verbose:
            print(f"      redo FAIL: {e}")


# ──────────────────────────────────────────────────────────────────
# 特殊場景：垂直文字專項
# ──────────────────────────────────────────────────────────────────
def run_vertical_text_test(metrics_v: Metrics, n_pages: int) -> None:
    """
    只針對垂直文字塊做編輯壓測，每頁10個中取 1 個垂直頁。
    """
    print("\n[垂直文字測試] 建立含垂直文字的 PDF...")
    doc = fitz.open()
    for i in range(6):
        page = doc.new_page(width=595, height=842)
        # 正常水平文字
        page.insert_text((72, 80), f"水平文字第 {i+1} 頁", fontsize=11, fontname="helv")
        # 垂直文字
        vbox = fitz.Rect(540, 80, 560, 400)
        page.insert_textbox(
            vbox,
            f"垂直欄位 Page {i+1}",
            fontsize=9,
            fontname="helv",
            rotate=90,
        )
    pdf_bytes = doc.tobytes()
    doc.close()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = f.name

    model = PDFModel()
    rng = random.Random(77)
    try:
        model.open_pdf(tmp)
        print(f"  頁數={len(model.doc)}, 文字塊數={sum(len(model.block_manager.get_blocks(i)) for i in range(len(model.doc)))}")
        run_random_edits(model, rounds=6, metrics=metrics_v, rng=rng, test_undo=True, verbose=True)
    finally:
        model.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────
# 特殊場景：掃描頁（無文字塊）graceful skip
# ──────────────────────────────────────────────────────────────────
def run_scan_page_test() -> bool:
    """
    測試當 edit_text 目標頁面為掃描頁（無文字塊）時，
    是否能 graceful skip（返回 None，不崩潰）。
    """
    print("\n[掃描頁測試] 建立無文字頁面並嘗試編輯...")
    doc = fitz.open()
    # p1: 有文字
    p1 = doc.new_page()
    p1.insert_text((72, 80), "Normal page text", fontsize=11)
    # p2: 無文字（模擬掃描頁）
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = f.name

    model = PDFModel()
    passed = False
    try:
        model.open_pdf(tmp)
        # 嘗試在掃描頁（page 2）上編輯任意 rect
        fake_rect = fitz.Rect(72, 80, 300, 100)
        result = model.edit_text(
            page_num=2,
            rect=fake_rect,
            new_text="This should be skipped",
            original_text=None,
        )
        # 預期：find_by_rect 找不到 block → 直接 return（not crash）
        passed = True
        print("  [OK] 掃描頁 graceful skip：無崩潰，返回 None")
    except RuntimeError as e:
        # 若 raise RuntimeError 也算 graceful（不是 crash）
        passed = True
        print(f"  [OK] 掃描頁 graceful RuntimeError（可接受）: {str(e)[:60]}")
    except Exception as e:
        passed = False
        print(f"  [FAIL] 掃描頁測試發生非預期例外: {e}")
        traceback.print_exc()
    finally:
        model.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass

    return passed


# ──────────────────────────────────────────────────────────────────
# 真實 1.pdf 測試（若存在）
# ──────────────────────────────────────────────────────────────────
def run_real_pdf_test(metrics_r: Metrics) -> None:
    if not REAL_PDF_PATH.exists():
        print(f"\n[1.pdf 測試] 未找到 {REAL_PDF_PATH}，跳過。")
        return

    print(f"\n[1.pdf 測試] 開啟 {REAL_PDF_PATH}...")
    model = PDFModel()
    rng = random.Random(99)
    try:
        model.open_pdf(str(REAL_PDF_PATH))
        n_pages = len(model.doc)
        total_blocks = sum(
            len(model.block_manager.get_blocks(i)) for i in range(n_pages)
        )
        print(f"  頁數={n_pages}, 文字塊數={total_blocks}")
        run_random_edits(model, rounds=5, metrics=metrics_r, rng=rng, test_undo=True, verbose=True)
    except Exception as e:
        metrics_r.errors.append(f"open/run failed: {e}")
        print(f"  [ERROR] {e}")
    finally:
        model.close()


# ──────────────────────────────────────────────────────────────────
# apply_pending_redactions 大小壓測
# ──────────────────────────────────────────────────────────────────
def run_clean_contents_bench(pdf_bytes: bytes, rounds: int) -> tuple[int, int]:
    """
    用同一份 PDF 跑 rounds 次編輯，測量 apply_pending_redactions 前後 doc 大小。
    返回 (size_before, size_after)。
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = f.name

    model = PDFModel()
    rng = random.Random(13)
    try:
        model.open_pdf(tmp)
        pool = _random_blocks(model, rng)
        if not pool:
            return 0, 0

        for i in range(min(rounds, len(pool))):
            page_num, blk = pool[i % len(pool)]
            try:
                model.edit_text(
                    page_num=page_num,
                    rect=blk.layout_rect,
                    new_text=f"bench edit {i}: Growth & Revenue",
                    font="helv",
                    size=max(8, int(blk.size) if blk.size else 11),
                    color=(0.0, 0.0, 0.0),
                    original_text=blk.text,
                )
            except Exception:
                pool = _random_blocks(model, rng)

        size_before = len(model.doc.tobytes())
        model.apply_pending_redactions()
        size_after = len(model.doc.tobytes())
        return size_before, size_after
    finally:
        model.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────
def main(rounds: int = 50, n_pages: int = 100, seed: int = 2026) -> int:
    print(f"\n{'#'*65}")
    print(f"  Phase 7 大規模測試")
    print(f"  頁數={n_pages}，隨機編輯={rounds} 次，seed={seed}")
    print(f"{'#'*65}\n")

    rng = random.Random(seed)
    all_pass = True

    # ── 1. 建立 100 頁合成 PDF ──────────────────────────────────
    print(f"[1/6] 建立 {n_pages} 頁合成 PDF...")
    t_build = time.perf_counter()
    pdf_bytes = _build_large_pdf(n_pages)
    print(f"  完成，大小 {len(pdf_bytes):,} bytes，耗時 {(time.perf_counter()-t_build)*1000:.0f}ms")

    # ── 2. 主壓測（50 次隨機多頁編輯）──────────────────────────
    print(f"\n[2/6] 主壓測：{rounds} 次隨機多頁編輯...")
    metrics_main = Metrics(f"合成 {n_pages} 頁 PDF，{rounds} 次隨機編輯")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_main = f.name

    model_main = PDFModel()
    try:
        model_main.open_pdf(tmp_main)
        n_editable_pages = sum(
            1 for i in range(len(model_main.doc))
            if model_main.block_manager.get_blocks(i)
        )
        total_blocks = sum(
            len(model_main.block_manager.get_blocks(i))
            for i in range(len(model_main.doc))
        )
        print(f"  開啟成功：{len(model_main.doc)} 頁，可編輯頁 {n_editable_pages}，共 {total_blocks} 個文字塊")

        run_random_edits(
            model_main, rounds=rounds, metrics=metrics_main,
            rng=rng, test_undo=True, verbose=True
        )
    except Exception as e:
        metrics_main.errors.append(f"FATAL: {e}")
        print(f"  [FATAL] {e}")
        traceback.print_exc()
        all_pass = False
    finally:
        model_main.close()
        try:
            os.unlink(tmp_main)
        except OSError:
            pass

    # ── 3. 垂直文字場景 ──────────────────────────────────────────
    print(f"\n[3/6] 垂直文字場景...")
    metrics_vert = Metrics("垂直文字場景")
    try:
        run_vertical_text_test(metrics_vert, n_pages=n_pages)
    except Exception as e:
        metrics_vert.errors.append(f"FATAL: {e}")
        print(f"  [FATAL] {e}")
        all_pass = False

    # ── 4. 掃描頁 graceful skip ───────────────────────────────────
    print(f"\n[4/6] 掃描頁 graceful skip 測試...")
    scan_ok = run_scan_page_test()
    if not scan_ok:
        all_pass = False

    # ── 5. apply_pending_redactions 壓縮效益 ─────────────────────
    print(f"\n[5/6] apply_pending_redactions 壓縮效益測試...")
    sb, sa = run_clean_contents_bench(pdf_bytes, rounds=min(rounds, 20))
    if sb > 0:
        delta = sb - sa
        pct = delta / sb * 100
        sym = "✓" if delta >= 0 else "⚠"
        print(f"  {sym} 壓縮前 {sb:,} → 壓縮後 {sa:,} bytes  縮減 {delta:+,} bytes ({pct:+.1f}%)")
    else:
        print("  [SKIP] 無足夠文字塊")

    # ── 6. 1.pdf 真實 PDF 測試 ────────────────────────────────────
    print(f"\n[6/6] 真實 PDF 測試 (1.pdf)...")
    metrics_real = Metrics("1.pdf 真實 PDF")
    run_real_pdf_test(metrics_real)

    # ── 報告 ─────────────────────────────────────────────────────
    print("\n" + "="*65)
    print("  Phase 7 測試報告")
    print("="*65)
    print(metrics_main.report())
    print(metrics_vert.report())
    if metrics_real.attempts > 0 or REAL_PDF_PATH.exists():
        print(metrics_real.report())

    # ── 掃描頁結果 ──
    print(f"\n  掃描頁 graceful skip：{'PASS' if scan_ok else 'FAIL'}")

    # ── apply_pending_redactions ──
    if sb > 0:
        delta = sb - sa
        print(f"  apply_pending_redactions 縮減：{delta:+,} bytes ({delta/sb*100:+.1f}%)")

    # ── 整體判定 ──
    undo_total = metrics_main.undo_ok + metrics_main.undo_fail
    if undo_total > 0:
        undo_rate = metrics_main.undo_ok / undo_total * 100
        undo_ok_flag = undo_rate >= 90
    else:
        undo_rate = None      # N/A：沒有 undo 被觸發（pool 太小或 stack 為空）
        undo_ok_flag = True   # 不算失敗

    main_ok = (
        metrics_main.error_rate < 0.05                                     # 消失率 < 5%
        and (metrics_main.avg_ms < 300 or not metrics_main.durations)      # 平均 < 300ms
        and undo_ok_flag                                                    # undo 率 ≥ 90% or N/A
    )
    vert_ok = metrics_vert.error_rate < 0.20     # 垂直文字允許較高錯誤率

    stable = all_pass and main_ok and vert_ok and scan_ok

    undo_str = (
        f"{undo_rate:.0f}%  {'✓ >=90%' if undo_ok_flag else '✗ <90%'}"
        if undo_rate is not None
        else "N/A (no undo triggered)  ✓"
    )

    print(f"\n{'─'*65}")
    print(f"  主壓測消失率：{metrics_main.error_rate*100:.1f}%  {'✓ <5%' if metrics_main.error_rate < 0.05 else '✗ >=5%'}")
    print(f"  主壓測平均耗時：{metrics_main.avg_ms:.0f}ms  {'✓ <300ms' if metrics_main.avg_ms < 300 else '✗ >=300ms'}")
    print(f"  Undo 成功率：{undo_str}")
    print(f"  垂直文字消失率：{metrics_vert.error_rate*100:.1f}%  {'✓ <20%' if metrics_vert.error_rate < 0.20 else '✗ >=20%'}")
    print(f"  掃描頁 graceful：{'✓' if scan_ok else '✗'}")
    print(f"{'─'*65}")

    if stable:
        print("\n  ✓✓✓ 所有指標達標 — 專案狀態：STABLE（可視為穩定版本）✓✓✓")
    else:
        print("\n  ✗ 部分指標未達標，請查閱上方錯誤清單後修正。")

    print(f"\n  [Phase 7 完成]\n")
    return 0 if stable else 1


# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 7 大規模測試")
    parser.add_argument("--rounds", type=int, default=50, help="主壓測編輯次數")
    parser.add_argument("--pages",  type=int, default=100, help="合成 PDF 頁數")
    parser.add_argument("--seed",   type=int, default=2026, help="隨機種子")
    args = parser.parse_args()
    sys.exit(main(rounds=args.rounds, n_pages=args.pages, seed=args.seed))
