"""iter9_edge_cases.py — 進階邊界情境測試

涵蓋：
  E1 - 編輯第二段（第一段不受影響）
  E2 - 連續兩次編輯同一頁
  E3 - 縮短文字（delta_y < 0，下方塊上移）
  E4 - 三欄版面：編輯中間欄，左右欄不動
  E5 - 頁底溢位防護（edited block 接近頁底）
  E6 - 純文字刪除（new_text = ""）
  E7 - 多次 reflow 後文字內容完整性
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz
from reflow.unified_command import apply_object_edit
from reflow.track_A_core import TrackAEngine

OUT = pathlib.Path(__file__).parent / "_vision_output" / "iter9"
OUT.mkdir(parents=True, exist_ok=True)

def render(page, path, scale=2.0):
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    pix.save(str(path))

def block_count(page):
    return sum(1 for b in page.get_text("dict")["blocks"] if b["type"] == 0 and
               "".join(s["text"] for l in b["lines"] for s in l["spans"]).strip())

results = []

print("=" * 70)
print("Round 9: Edge Cases")
print("=" * 70)

# ── E1: 編輯第二段，第一段不動 ──────────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 100), "First paragraph stays put.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 120, 400, 150), "Second paragraph is edited.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 170, 400, 200), "Third paragraph should move.", fontname="helv", fontsize=12)

blocks_before = page.get_text("dict")["blocks"]
first_before = fitz.Rect([b["bbox"] for b in blocks_before
    if b["type"]==0 and "First" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[]))][0])
third_before = fitz.Rect([b["bbox"] for b in blocks_before
    if b["type"]==0 and "Third" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[]))][0])

apply_object_edit(page=page,
    object_info={"original_rect": fitz.Rect(72, 120, 400, 150), "font": "helv", "size": 12.0,
                 "color": (0,0,0), "original_text": "Second paragraph is edited.", "page_rotation": 0},
    changes={"new_text": "Second paragraph has been replaced with much longer text that wraps to multiple lines.",
             "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

td_after = page.get_text("dict")
first_after = None
for b in td_after["blocks"]:
    if b["type"]==0 and "First" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        first_after = fitz.Rect(b["bbox"])
        break

e1_first_stable = first_after is not None and abs(first_after.y0 - first_before.y0) < 3
third_after_y0 = None
for b in td_after["blocks"]:
    if b["type"]==0 and "Third" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        third_after_y0 = fitz.Rect(b["bbox"]).y0
        break
e1_third_moved = third_after_y0 is not None and third_after_y0 > third_before.y0 + 0.5

third_y_str = f"{third_after_y0:.0f}" if third_after_y0 is not None else "None"
print(f"E1 edit-middle: first_stable={e1_first_stable} third_moved={e1_third_moved} "
      f"(third: {third_before.y0:.0f}→{third_y_str})")
results.append(("E1", e1_first_stable and e1_third_moved))
render(page, OUT / "e1_edit_second_after.png")
doc.close()

# ── E2: 連續兩次編輯同一頁 ───────────────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 100), "Block A.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 120, 400, 150), "Block B.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 170, 400, 200), "Block C.", fontname="helv", fontsize=12)

# First edit: A → longer
apply_object_edit(page=page,
    object_info={"original_rect": fitz.Rect(72, 72, 400, 100), "font": "helv", "size": 12.0,
                 "color": (0,0,0), "original_text": "Block A.", "page_rotation": 0},
    changes={"new_text": "Block A has been expanded significantly to push B and C down.",
             "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

td_mid = page.get_text("text")

# Second edit: B → shorter
b_rect = None
for b in page.get_text("dict")["blocks"]:
    if b["type"]==0 and "Block B" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        b_rect = fitz.Rect(b["bbox"])
        break

if b_rect:
    apply_object_edit(page=page,
        object_info={"original_rect": b_rect, "font": "helv", "size": 12.0,
                     "color": (0,0,0), "original_text": "Block B.", "page_rotation": 0},
        changes={"new_text": "B.", "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
        track="A")

td_final = page.get_text("text")
e2_has_a = "Block A has been expanded" in td_final
e2_has_b = "B." in td_final
e2_has_c = "Block C" in td_final
print(f"E2 double-edit: has_A={e2_has_a} has_B={e2_has_b} has_C={e2_has_c}")
results.append(("E2", e2_has_a and e2_has_b and e2_has_c))
render(page, OUT / "e2_double_edit_after.png")
doc.close()

# ── E3: 縮短文字，下方塊上移 ────────────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 150),
    "This is a long paragraph that will be shortened.\nIt spans multiple lines.\nThird line here.",
    fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 200, 400, 230), "Block below should move UP.", fontname="helv", fontsize=12)

td_before = page.get_text("dict")
below_y0_before = next(fitz.Rect(b["bbox"]).y0 for b in td_before["blocks"]
    if b["type"]==0 and "below" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])))

apply_object_edit(page=page,
    object_info={"original_rect": fitz.Rect(72, 72, 400, 150), "font": "helv", "size": 12.0,
                 "color": (0,0,0),
                 "original_text": "This is a long paragraph that will be shortened.\nIt spans multiple lines.\nThird line here.",
                 "page_rotation": 0},
    changes={"new_text": "Short.", "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

td_after = page.get_text("dict")
below_y0_after = None
for b in td_after["blocks"]:
    if b["type"]==0 and "below" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        below_y0_after = fitz.Rect(b["bbox"]).y0
        break

e3_moved_up = below_y0_after is not None and below_y0_after < below_y0_before
y_after_str = f"{below_y0_after:.0f}" if below_y0_after is not None else "None"
print(f"E3 shorten: below moved up {below_y0_before:.0f}→{y_after_str} ok={e3_moved_up}")
results.append(("E3", e3_moved_up))
render(page, OUT / "e3_shorten_after.png")
doc.close()

# ── E4: 三欄：編輯中間欄，左右欄不動 ───────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(10, 80, 185, 200), "Left col text here.", fontname="helv", fontsize=11)
page.insert_textbox(fitz.Rect(10, 210, 185, 300), "Left col para 2.", fontname="helv", fontsize=11)
page.insert_textbox(fitz.Rect(205, 80, 390, 200), "Middle col text.", fontname="helv", fontsize=11)
page.insert_textbox(fitz.Rect(205, 210, 390, 300), "Middle col para 2.", fontname="helv", fontsize=11)
page.insert_textbox(fitz.Rect(410, 80, 585, 200), "Right col text here.", fontname="helv", fontsize=11)
page.insert_textbox(fitz.Rect(410, 210, 585, 300), "Right col para 2.", fontname="helv", fontsize=11)

left_y_before = []
right_y_before = []
for b in page.get_text("dict")["blocks"]:
    if b["type"]!=0: continue
    r = fitz.Rect(b["bbox"])
    text = "".join(s["text"] for l in b["lines"] for s in l.get("spans",[]))
    if r.x0 < 100:
        left_y_before.append(r.y0)
    elif r.x0 > 390:
        right_y_before.append(r.y0)

apply_object_edit(page=page,
    object_info={"original_rect": fitz.Rect(205, 80, 390, 200), "font": "helv", "size": 11.0,
                 "color": (0,0,0), "original_text": "Middle col text.", "page_rotation": 0},
    changes={"new_text": "Middle column has been greatly expanded with much more text forcing para 2 downward.",
             "font": "helv", "size": 11.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

left_y_after = []
right_y_after = []
for b in page.get_text("dict")["blocks"]:
    if b["type"]!=0: continue
    r = fitz.Rect(b["bbox"])
    if r.x0 < 100:
        left_y_after.append(r.y0)
    elif r.x0 > 390:
        right_y_after.append(r.y0)

e4_left_stable = len(left_y_before)==len(left_y_after) and all(
    abs(a-b)<3 for a,b in zip(sorted(left_y_before), sorted(left_y_after)))
e4_right_stable = len(right_y_before)==len(right_y_after) and all(
    abs(a-b)<3 for a,b in zip(sorted(right_y_before), sorted(right_y_after)))
print(f"E4 3-col: left_stable={e4_left_stable} right_stable={e4_right_stable}")
results.append(("E4", e4_left_stable and e4_right_stable))
render(page, OUT / "e4_3col_after.png")
doc.close()

# ── E5: 頁底溢位防護 ─────────────────────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 700, 400, 730), "Near-bottom block.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 750, 400, 780), "Very close to bottom.", fontname="helv", fontsize=12)

try:
    apply_object_edit(page=page,
        object_info={"original_rect": fitz.Rect(72, 700, 400, 730), "font": "helv", "size": 12.0,
                     "color": (0,0,0), "original_text": "Near-bottom block.", "page_rotation": 0},
        changes={"new_text": "This text near the bottom is longer and might push content off the page boundary.",
                 "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
        track="A")
    # Check no block exceeds page height
    over_page = any(fitz.Rect(b["bbox"]).y1 > 843
                    for b in page.get_text("dict")["blocks"] if b["type"]==0)
    e5_ok = not over_page
    print(f"E5 bottom overflow: no_overflow={e5_ok}")
except Exception as ex:
    e5_ok = False
    print(f"E5 bottom overflow: EXCEPTION {ex}")
results.append(("E5", e5_ok))
doc.close()

# ── E6: 純文字刪除（new_text = ""）───────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 100, 400, 130), "Block to delete.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 150, 400, 180), "Block below should move up on delete.", fontname="helv", fontsize=12)

below_y_before = next(fitz.Rect(b["bbox"]).y0 for b in page.get_text("dict")["blocks"]
    if b["type"]==0 and "below" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])))

apply_object_edit(page=page,
    object_info={"original_rect": fitz.Rect(72, 100, 400, 130), "font": "helv", "size": 12.0,
                 "color": (0,0,0), "original_text": "Block to delete.", "page_rotation": 0},
    changes={"new_text": "", "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

td_after = page.get_text("dict")
deleted_gone = not any("Block to delete" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[]))
                        for b in td_after["blocks"] if b["type"]==0)
below_y_after = None
for b in td_after["blocks"]:
    if b["type"]==0 and "below" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        below_y_after = fitz.Rect(b["bbox"]).y0
        break
e6_moved_up = below_y_after is not None and below_y_after < below_y_before
below_y_after_str = f"{below_y_after:.0f}" if below_y_after is not None else "None"
print(f"E6 delete: gone={deleted_gone} below_moved_up={e6_moved_up} "
      f"({below_y_before:.0f}→{below_y_after_str})")
results.append(("E6", deleted_gone and e6_moved_up))
render(page, OUT / "e6_delete_after.png")
doc.close()

# ── E7: 多次 reflow 後文字完整性 ──────────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 100), "Initial A.", fontname="helv", fontsize=12)
page.insert_textbox(fitz.Rect(72, 120, 400, 150), "Stable content that should be preserved.", fontname="helv", fontsize=12)

# Edit 1
apply_object_edit(page=page,
    object_info={"original_rect": fitz.Rect(72, 72, 400, 100), "font": "helv", "size": 12.0,
                 "color": (0,0,0), "original_text": "Initial A.", "page_rotation": 0},
    changes={"new_text": "Expanded A paragraph to push content.", "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

# Find where stable block is now
stable_rect = None
for b in page.get_text("dict")["blocks"]:
    if b["type"]==0 and "Stable" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        stable_rect = fitz.Rect(b["bbox"])
        break

# Edit 2 (edit A block again)
a_rect = None
for b in page.get_text("dict")["blocks"]:
    if b["type"]==0 and "Expanded" in "".join(s["text"] for l in b["lines"] for s in l.get("spans",[])):
        a_rect = fitz.Rect(b["bbox"])
        break

if a_rect:
    apply_object_edit(page=page,
        object_info={"original_rect": a_rect, "font": "helv", "size": 12.0,
                     "color": (0,0,0), "original_text": "Expanded A paragraph to push content.", "page_rotation": 0},
        changes={"new_text": "Short A.", "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
        track="A")

td_final = page.get_text("text")
e7_stable_preserved = "Stable content" in td_final or "Stable" in td_final
e7_short_a = "Short A" in td_final
print(f"E7 multi-edit integrity: stable_preserved={e7_stable_preserved} short_a={e7_short_a}")
results.append(("E7", e7_stable_preserved and e7_short_a))
render(page, OUT / "e7_multi_edit_after.png")
doc.close()

# ── Summary ─────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
passed = sum(1 for _, ok in results if ok)
for label, ok in results:
    print(f"  [{label}] {'PASS ✓' if ok else 'FAIL ✗'}")
print(f"\n{passed}/{len(results)} PASS")
print("=" * 70)
