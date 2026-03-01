# -*- coding: utf-8 -*-
"""
稽核 1.pdf：檢查頁面尺寸、文字塊位置、編輯後輸出
"""
import sys
import io
from pathlib import Path

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import fitz
from model.pdf_model import PDFModel

def audit_1pdf():
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "test_files" / "1.pdf",
        Path(__file__).parent / "1.pdf",
    ]
    path = next((p for p in candidates if p.exists()), candidates[0])
    if not path.exists():
        print("1.pdf 不存在")
        return

    doc = fitz.open(str(path))
    page = doc[0]
    page_rect = page.rect
    print("=== 1.pdf 頁面資訊 ===")
    print(f"頁面 rect: x0={page_rect.x0}, y0={page_rect.y0}, x1={page_rect.x1}, y1={page_rect.y1}")
    print(f"頁面寬度: {page_rect.width}, 高度: {page_rect.height}")
    print(f"頁面旋轉: {page.rotation}")

    blocks = page.get_text("dict", flags=0)["blocks"]
    print(f"\n文字塊數: {len(blocks)}")
    for i, b in enumerate(blocks):
        if b.get('type') != 0:
            continue
        r = fitz.Rect(b["bbox"])
        text = ""
        for line in b.get("lines", []):
            for s in line.get("spans", []):
                text += s.get("text", "")
        print(f"  Block {i}: rect=({r.x0:.1f}, {r.y0:.1f}, {r.x1:.1f}, {r.y1:.1f})")
        print(f"    寬={r.width:.1f}, 超出右邊? {r.x1 > page_rect.x1}")
        print(f"    文字: {repr(text[:50])}...")
    doc.close()

    print("\n=== 模擬編輯後 rect 計算 ===")
    model = PDFModel()
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    blocks_idx = model.block_manager.get_blocks(0)
    for i, block in enumerate(blocks_idx):
        rect = block.layout_rect
        rotation = block.rotation
        text = block.text[:30]
        print(f"Block {i} (rotation={rotation}): rect x1={rect.x1:.1f}, page.x1={model.doc[0].rect.x1:.1f}")
        if rect.x1 > model.doc[0].rect.x1:
            print(f"  *** 區塊超出頁面右緣! ***")
    model.close()

if __name__ == "__main__":
    audit_1pdf()
