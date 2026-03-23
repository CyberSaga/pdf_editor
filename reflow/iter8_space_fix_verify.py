"""iter8_space_fix_verify.py — 驗證 shouldmove 空格修復 + 新 v4 vision 輸出"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz
from reflow.unified_command import apply_object_edit

OUT = pathlib.Path(__file__).parent / "_vision_output" / "iter8"
OUT.mkdir(parents=True, exist_ok=True)

def render(page, path, scale=2.0):
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    pix.save(str(path))

print("=" * 70)
print("Round 8: Space-fix verification + V4 multi-column re-run")
print("=" * 70)

# ── T1: shouldmove 修復驗證 ─────────────────────────────────────────────
print("\nT1: Verify space preserved after reflow of adjacent block")

doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(40, 60, 285, 120),
    "Short first paragraph.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(40, 130, 285, 220),
    "This is the second paragraph that should move when the first one changes.",
    fontname="helv", fontsize=12)

apply_object_edit(
    page=page,
    object_info={"original_rect": fitz.Rect(40, 60, 285, 120),
                 "font": "helv", "size": 12.0, "color": (0,0,0),
                 "original_text": "Short first paragraph.", "page_rotation": 0},
    changes={"new_text": "This is a much longer replacement for the first paragraph, forcing the next block downward.",
             "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

render(page, OUT / "t1_space_after.png")

# Extract text of moved block and check for "shouldmove"
td = page.get_text("text")
has_space_bug = "shouldmove" in td
print(f"  'shouldmove' bug present: {has_space_bug}")
print(f"  Page text snippet: {repr(td[:300])}")
doc.close()

t1_pass = not has_space_bug
print(f"  T1: {'PASS ✓' if t1_pass else 'FAIL ✗'}")

# ── T2: V4 multi-column re-run ──────────────────────────────────────────
print("\nT2: V4 multi-column — re-run with space fix applied")

doc4 = fitz.open()
page4 = doc4.new_page(width=595, height=842)
page4.insert_textbox(fitz.Rect(40, 80, 285, 200),
    "Chapter 1: Introduction\n\nThis is the first paragraph of the document. "
    "It contains multiple lines of text.", fontname="helv", fontsize=12)
page4.insert_textbox(fitz.Rect(40, 210, 285, 320),
    "This is the second paragraph that should move when the first one changes.",
    fontname="helv", fontsize=12)
page4.insert_textbox(fitz.Rect(310, 80, 555, 200),
    "Right column: this content should NOT move.", fontname="helv", fontsize=12)
page4.insert_textbox(fitz.Rect(310, 210, 555, 320),
    "Right column paragraph 2: also should not move.", fontname="helv", fontsize=12)

render(page4, OUT / "t2_multicol_before.png")

apply_object_edit(
    page=page4,
    object_info={"original_rect": fitz.Rect(40, 80, 285, 200),
                 "font": "helv", "size": 12.0, "color": (0,0,0),
                 "original_text": "Chapter 1: Introduction\n\nThis is the first paragraph of the document. It contains multiple lines of text.",
                 "page_rotation": 0},
    changes={"new_text": "Chapter 1: Introduction — Revised Edition\n\nThis paragraph has been completely rewritten with substantially more content than the original version had, forcing the subsequent paragraph to move downward appropriately.",
             "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

render(page4, OUT / "t2_multicol_after.png")

# Verify: check moved para has correct spacing
td4 = page4.get_text("text")
has_bug = "shouldmove" in td4
print(f"  'shouldmove' in moved para: {has_bug}")
print(f"  Page text: {repr(td4[:400])}")
doc4.close()

t2_pass = not has_bug
print(f"  T2: {'PASS ✓' if t2_pass else 'FAIL ✗'}")

# ── T3: Multi-span block space preservation ──────────────────────────────
print("\nT3: Multi-span block (mixed fonts) space preservation")

doc3 = fitz.open()
page3 = doc3.new_page(width=595, height=842)
# Edited block
page3.insert_textbox(fitz.Rect(72, 72, 400, 100), "Short.", fontname="helv", fontsize=12)
# Block with text that will wrap and potentially lose space
page3.insert_textbox(fitz.Rect(72, 120, 400, 200),
    "The quick brown fox jumps over the lazy dog and then some more words here.",
    fontname="helv", fontsize=12)

apply_object_edit(
    page=page3,
    object_info={"original_rect": fitz.Rect(72, 72, 400, 100),
                 "font": "helv", "size": 12.0, "color": (0,0,0),
                 "original_text": "Short.", "page_rotation": 0},
    changes={"new_text": "A longer replacement paragraph that pushes the block below downward significantly.",
             "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

td3 = page3.get_text("text")
# Check that "foxjumps" doesn't appear (space lost)
fox_space_ok = "fox jumps" in td3 or "foxjumps" not in td3
dog_space_ok = "dog and" in td3 or "dogand" not in td3
print(f"  'fox jumps' preserved: {fox_space_ok}, 'dog and' preserved: {dog_space_ok}")
doc3.close()

t3_pass = fox_space_ok and dog_space_ok
print(f"  T3: {'PASS ✓' if t3_pass else 'FAIL ✗'}")

# ── Summary ─────────────────────────────────────────────────────────────
all_pass = t1_pass and t2_pass and t3_pass
print(f"\n{'='*70}")
print(f"iter8 結果: {'3/3 PASS ✓' if all_pass else 'FAILED'}")
print(f"Vision PNG: {OUT}/")
print(f"  t1_space_after.png  — 應顯示 'should move' 有空格")
print(f"  t2_multicol_before/after.png — 左欄移動，右欄不動")
