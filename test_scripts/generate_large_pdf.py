# -*- coding: utf-8 -*-
"""
generate_large_pdf.py — 產生極大 PDF（壓力測試用）
====================================================
依「超大 PDF 壓力測試」計畫：產生 500～1000 頁（可調）的 PDF，
寫入指定路徑，供後續 headless 開檔計時與 GUI 手動開啟測試。

執行方式：
  python test_scripts/generate_large_pdf.py
  python test_scripts/generate_large_pdf.py --pages 1000 --output large_stress.pdf
  python test_scripts/generate_large_pdf.py --pages 500
"""
import sys
import os
import argparse
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import fitz

# 預設輸出路徑（專案 test_scripts 下）
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "large_stress.pdf"


def build_large_pdf(n_pages: int) -> bytes:
    """
    產生 n_pages 頁的測試 PDF（每頁少量文字，控制檔案大小與產生時間）。
    """
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (72, 80),
            f"Page {i+1} / {n_pages} — Stress test PDF for open/performance testing.",
            fontsize=11,
            fontname="helv",
        )
        page.insert_text((72, 110), "Line 2: 測試文字 / 壓力測試用極大 PDF。", fontsize=10, fontname="helv")
    data = doc.tobytes(garbage=0)
    doc.close()
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="產生極大 PDF（壓力測試用）")
    parser.add_argument("--pages", type=int, default=1000, help="頁數（預設 1000）")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="輸出 PDF 路徑")
    args = parser.parse_args()

    n = max(1, args.pages)
    out_path = Path(args.output)

    print(f"產生 {n} 頁 PDF...")
    pdf_bytes = build_large_pdf(n)
    out_path.write_bytes(pdf_bytes)
    size_mb = len(pdf_bytes) / (1024 * 1024)
    print(f"已寫入：{out_path}")
    print(f"大小：{len(pdf_bytes):,} bytes ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
