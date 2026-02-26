# -*- coding: utf-8 -*-
"""
test_open_large_pdf.py — 超大 PDF 開檔壓力測試（headless）
==========================================================
依「超大 PDF 壓力測試」計畫：對極大 PDF 執行 Model.open_pdf 並量測耗時，
觀察是否崩潰或長時間無回應。可選擇先產生大 PDF 或指定既有路徑。

執行方式：
  python test_scripts/test_open_large_pdf.py
    → 先產生 1000 頁 PDF 到 test_scripts/large_stress.pdf，再計時開檔
  python test_scripts/test_open_large_pdf.py --pages 500
  python test_scripts/test_open_large_pdf.py --path path/to/large.pdf
  python test_scripts/test_open_large_pdf.py --path test_scripts/large_stress.pdf
"""
import sys
import os
import time
import argparse
import tempfile
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 確保可 import 專案模組（專案根目錄 + test_scripts）
_root = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(SCRIPT_DIR))

from model.pdf_model import PDFModel

DEFAULT_LARGE_PDF = SCRIPT_DIR / "large_stress.pdf"


def ensure_large_pdf(pages: int) -> Path:
    """產生指定頁數的 PDF 並回傳路徑。"""
    from generate_large_pdf import build_large_pdf
    path = SCRIPT_DIR / "large_stress.pdf"
    print(f"產生 {pages} 頁 PDF 至 {path}...")
    t0 = time.perf_counter()
    pdf_bytes = build_large_pdf(pages)
    path.write_bytes(pdf_bytes)
    elapsed = time.perf_counter() - t0
    print(f"  完成，大小 {len(pdf_bytes):,} bytes，耗時 {elapsed:.2f}s")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="超大 PDF 開檔壓力測試（headless）")
    parser.add_argument("--path", type=str, default="", help="既有 PDF 路徑（不給則先產生）")
    parser.add_argument("--pages", type=int, default=1000, help="未給 --path 時產生的頁數")
    parser.add_argument("--first-page", action="store_true", help="開檔後再量測第一頁 get_page_pixmap 耗時")
    args = parser.parse_args()

    if args.path:
        pdf_path = Path(args.path)
        if not pdf_path.is_file():
            print(f"錯誤：檔案不存在 {pdf_path}")
            return 1
    else:
        pdf_path = ensure_large_pdf(args.pages)

    print(f"\n開檔測試：{pdf_path}")
    print("─" * 50)

    model = PDFModel()
    t0 = time.perf_counter()
    try:
        model.open_pdf(str(pdf_path))
        elapsed = time.perf_counter() - t0
        n = len(model.doc)
        print(f"  開檔成功，頁數 = {n}")
        print(f"  開檔耗時 = {elapsed:.2f}s ({elapsed*1000:.0f} ms)")
        if args.first_page:
            t1 = time.perf_counter()
            _ = model.get_page_pixmap(1, 1.0)
            first_page_ms = (time.perf_counter() - t1) * 1000
            print(f"  第一頁 get_page_pixmap(1, 1.0) 耗時 = {first_page_ms:.0f} ms")
        model.close()
        return 0
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  開檔失敗（崩潰/例外）耗時 = {elapsed:.2f}s")
        print(f"  錯誤：{e}")
        import traceback
        traceback.print_exc()
        try:
            model.close()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
