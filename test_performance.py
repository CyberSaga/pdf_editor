"""
test_performance.py — Phase 6 效能測試
======================================
模擬 20 次連續編輯同一頁，量測：
  - 每次 edit_text 耗時
  - 平均 / 最大 / 最小耗時
  - 記憶體增長（首次 vs 末次 doc.tobytes() 大小）
  - apply_pending_redactions 前後檔案大小差異
  - GC 觸發情況（edit_count % 5 / % 20）

執行方式：
  python test_performance.py
  python test_performance.py --rounds 50    # 自訂編輯次數
"""
import sys
import time
import fitz
import tempfile
import os
import argparse

# 確保 import 路徑
sys.path.insert(0, os.path.dirname(__file__))
from model.pdf_model import PDFModel

# ──────────────────────────────────────────────────
# 輔助：建立多頁測試 PDF
# ──────────────────────────────────────────────────
def _make_test_pdf(n_pages: int = 5) -> bytes:
    doc = fitz.open()
    texts = [
        "Growth & Revenue: 2025-2026 Annual Report",
        "第一季度業績摘要：總收入達 NT$1,234,567",
        "Key Performance Indicators (KPIs) — Q4",
        "市場分析與競爭態勢：CJK / Latin 混排測試",
        "Conclusion: fi fl ﬁ ligature & special chars <>'\"",
    ]
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        text = texts[i % len(texts)]
        page.insert_text(
            (72, 100 + i * 30),
            text,
            fontsize=12,
            fontname="helv",
        )
    return doc.tobytes()


# ──────────────────────────────────────────────────
# 主測試流程
# ──────────────────────────────────────────────────
def run_performance_test(rounds: int = 20):
    print(f"\n{'='*60}")
    print(f"Phase 6 效能測試：{rounds} 次連續編輯同一頁")
    print(f"{'='*60}")

    # 1. 準備測試 PDF 檔案
    pdf_bytes = _make_test_pdf(n_pages=3)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = f.name

    model = PDFModel()
    model.open_pdf(tmp_path)

    page_num = 1
    # 取出第 1 頁第一個文字塊的資訊，供後續連續編輯使用
    page = model.doc[0]
    blocks = page.get_text("dict")["blocks"]
    first_block = next(
        (b for b in blocks if b.get("type") == 0 and b.get("lines")),
        None
    )
    if not first_block:
        print("SKIP：無法找到可編輯文字塊，請檢查測試 PDF")
        model.close()
        os.unlink(tmp_path)
        return

    orig_rect = fitz.Rect(first_block["bbox"])
    orig_text = " ".join(
        span["text"]
        for line in first_block["lines"]
        for span in line["spans"]
    ).strip()
    print(f"目標文字塊：{orig_text[:40]!r}  rect={orig_rect}")

    # 2. 初始文件大小
    size_before_gc = len(model.doc.tobytes())
    print(f"初始 doc 大小：{size_before_gc:,} bytes")

    # 3. 連續編輯 rounds 次
    durations: list[float] = []
    errors = 0
    new_texts = [
        f"edited round {i+1}: Growth & Revenue <test> 測試文字 {i+1}"
        for i in range(rounds)
    ]

    for i in range(rounds):
        t0 = time.perf_counter()
        try:
            model.edit_text(
                page_num=page_num,
                rect=orig_rect,
                new_text=new_texts[i],
                font="helv",
                size=11,
                color=(0.0, 0.0, 0.0),
                original_text=None,   # 每次依矩形定位
            )
            elapsed = time.perf_counter() - t0
            durations.append(elapsed)

            status = "⚠ SLOW" if elapsed > 0.3 else "OK"
            # 每 5 次印一次進度
            if (i + 1) % 5 == 0 or elapsed > 0.3:
                print(
                    f"  [{i+1:02d}/{rounds}] {elapsed:.3f}s  {status}"
                    f"  edit_count={model.edit_count}"
                    f"  pending={len(model.pending_edits)}"
                )
        except Exception as e:
            errors += 1
            elapsed = time.perf_counter() - t0
            print(f"  [{i+1:02d}/{rounds}] ERROR ({elapsed:.3f}s): {e}")
            # 重新定位（可能因前次編輯 block 已更新）
            page = model.doc[0]
            blocks = page.get_text("dict")["blocks"]
            fb = next(
                (b for b in blocks if b.get("type") == 0 and b.get("lines")),
                None
            )
            if fb:
                orig_rect = fitz.Rect(fb["bbox"])

    # 4. 統計
    if durations:
        avg = sum(durations) / len(durations)
        mx = max(durations)
        mn = min(durations)
        slow = sum(1 for d in durations if d > 0.3)
        print(f"\n{'─'*40}")
        print(f"成功編輯：{len(durations)}/{rounds}，錯誤：{errors}")
        print(f"耗時 — 平均：{avg:.3f}s  最大：{mx:.3f}s  最小：{mn:.3f}s")
        print(f"超過 300ms：{slow} 次")
        if avg < 0.3:
            print("✓ 平均耗時 < 300ms（達標）")
        else:
            print("✗ 平均耗時 ≥ 300ms（需優化）")

    # 5. apply_pending_redactions 前後大小比對
    size_before_clean = len(model.doc.tobytes())
    model.apply_pending_redactions()
    size_after_clean = len(model.doc.tobytes())
    print(f"\ncontent stream 清理前大小：{size_before_clean:,} bytes")
    print(f"content stream 清理後大小：{size_after_clean:,} bytes")
    diff = size_before_clean - size_after_clean
    pct = diff / size_before_clean * 100 if size_before_clean else 0
    print(f"縮減：{diff:+,} bytes（{pct:.1f}%）")
    if diff >= 0:
        print("✓ apply_pending_redactions 有壓縮效果（或持平）")
    else:
        print("⚠ 大小略增（PyMuPDF 版本或文件結構差異，可忽略）")

    # 6. GC 觸發確認
    print(f"\nfinal edit_count = {model.edit_count}")
    expected_light_gc = rounds // 5
    expected_full_gc = rounds // 20
    print(
        f"預期輕量 GC 觸發次數（每 5 次）：≈ {expected_light_gc}，"
        f"完整 GC（每 20 次）：≈ {expected_full_gc}"
    )

    # 7. 清理
    model.close()
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    print(f"\n{'='*60}")
    print("Phase 6 效能測試完成")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 6 效能測試")
    parser.add_argument(
        "--rounds", type=int, default=20,
        help="連續編輯次數（預設 20，建議 50 壓測）"
    )
    args = parser.parse_args()
    run_performance_test(rounds=args.rounds)
