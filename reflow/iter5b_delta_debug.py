"""iter5b_delta_debug.py — 診斷真實 PDF 的 delta_y 過大問題"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz
from reflow.track_A_core import TrackAEngine, LayoutAnalysis

ROOT = pathlib.Path(__file__).parent.parent
res_pdf = ROOT / "test_files" / "reservation_table.pdf"

engine = TrackAEngine()
doc = fitz.open(str(res_pdf))
page = doc[0]

# Analyze layout
layout = engine.analyze_layout(page, 0)
print(f"Total blocks in layout: {len(layout.blocks)}")
for bl in layout.blocks[:5]:
    print(f"  block[{bl.block_idx}] bbox={bl.bbox} "
          f"text='{bl.text[:40]}' "
          f"avg_lh={bl.avg_line_height:.1f} "
          f"reading_order={bl.reading_order}")

# Find edited block
edited_rect = fitz.Rect(layout.blocks[0].bbox) if layout.blocks else fitz.Rect(72, 48, 550, 62)
print(f"\nEdited rect: {edited_rect}")

edited_block_idx = engine._find_edited_block(layout, edited_rect)
edited_block = next((bl for bl in layout.blocks if bl.block_idx == edited_block_idx), None)
print(f"Edited block: {edited_block}")

# Compute plan
original_text = edited_block.text if edited_block else ""
new_text = "修改後的標題文字 Updated Title"
print(f"\noriginal_text = '{original_text[:60]}'")
print(f"new_text = '{new_text}'")

est_width = edited_rect.width
print(f"\nest_width = {est_width:.1f}pt")

old_dw = engine._count_display_width(original_text, 11)
new_dw = engine._count_display_width(new_text, 11)
print(f"old display_w = {old_dw:.1f}pt")
print(f"new display_w = {new_dw:.1f}pt")

avg_lh = edited_block.avg_line_height if edited_block else 13.2
old_height = engine._estimate_text_height(original_text, "helv", 11, est_width, avg_lh)
new_height = engine._estimate_text_height(new_text, "helv", 11, est_width, avg_lh)
print(f"\nold_height = {old_height:.2f}pt")
print(f"new_height = {new_height:.2f}pt")
print(f"delta_y = {new_height - old_height:.2f}pt")

# Show all block positions to understand what "overflow" means
print(f"\nAll blocks y0 positions (should show table rows):")
for bl in layout.blocks:
    print(f"  [{bl.reading_order}] y0={bl.bbox.y0:.1f} y1={bl.bbox.y1:.1f} '{bl.text[:30]}'")
