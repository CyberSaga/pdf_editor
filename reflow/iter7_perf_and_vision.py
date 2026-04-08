"""iter7_perf_and_vision.py — 效能量測 + 多場景 Vision 驗證"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz

from reflow.unified_command import apply_object_edit

ROOT = pathlib.Path(__file__).parent.parent
TEST_FILES = ROOT / "test_files"
OUT = ROOT / "reflow" / "_vision_output" / "iter7"
OUT.mkdir(parents=True, exist_ok=True)

def render_page(page, path, scale=2.0):
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    pix.save(str(path))

def time_apply(page, object_info, changes, track="auto", runs=3):
    """計時 apply_object_edit 的平均耗時（排除首次 JIT 暖身）"""
    times = []
    for i in range(runs):
        doc = fitz.open()
        doc._pdf = page.parent  # can't copy page; re-open each time
        # Workaround: measure on fresh doc copy
        import io
        buf = io.BytesIO()
        page.parent.save(buf)
        buf.seek(0)
        doc2 = fitz.open("pdf", buf)
        p2 = doc2[page.number]
        t0 = time.perf_counter()
        apply_object_edit(page=p2, object_info=object_info, changes=changes, track=track)
        times.append((time.perf_counter() - t0) * 1000)
        doc2.close()
    return min(times), sum(times)/len(times)

print("=" * 70)
print("Round 7: Performance Benchmark")
print("=" * 70)

SCENARIOS = [
    ("simple_1line→1line", "Short.", "Also short.", "A"),
    ("medium_1line→3line", "Short.", "This is a longer replacement text that spans multiple lines.", "A"),
    ("long_3line→1line",
     "This is a paragraph with multiple lines of text that is quite long.",
     "Short.", "A"),
    ("track_B_simple", "Short.", "Replacement.", "B"),
    ("track_auto_fallback", "Short.", "Replacement.", "auto"),
]

for label, orig, new, track in SCENARIOS:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 400, 120), orig, fontname="helv", fontsize=12)
    page.insert_textbox(fitz.Rect(72, 150, 400, 200), "Below paragraph stays.", fontname="helv", fontsize=12)

    object_info = {
        "original_rect": fitz.Rect(72, 72, 400, 120),
        "font": "helv", "size": 12.0, "color": (0,0,0),
        "original_text": orig, "page_rotation": 0,
    }
    changes = {"new_text": new, "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True}

    t_min, t_avg = time_apply(page, object_info, changes, track=track)
    budget_ok = t_min < 100
    print(f"  [{label:<30}] min={t_min:.1f}ms avg={t_avg:.1f}ms {'✓ <100ms' if budget_ok else '✗ SLOW'}")
    doc.close()

print("\n" + "=" * 70)
print("Round 8: Vision Verification — Multiple Real Scenarios")
print("=" * 70)

# Scenario V1: word_table.pdf
v1_pdf = TEST_FILES / "word_table.pdf"
if v1_pdf.exists():
    doc = fitz.open(str(v1_pdf))
    page = doc[0]
    td = page.get_text("dict")
    blocks = [b for b in td["blocks"] if b["type"] == 0
              and fitz.Rect(b["bbox"]).width > 80
              and "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", [])).strip()]
    if blocks:
        b = max(blocks, key=lambda x: fitz.Rect(x["bbox"]).width * fitz.Rect(x["bbox"]).height)
        r = fitz.Rect(b["bbox"])
        orig = "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", []))
        render_page(page, OUT / "v1_word_table_before.png")
        apply_object_edit(page=page,
            object_info={"original_rect": r, "font": "helv", "size": 11.0,
                         "color": (0,0,0), "original_text": orig, "page_rotation": page.rotation},
            changes={"new_text": "Updated table content", "font": "helv", "size": 11.0,
                     "color": (0,0,0), "reflow_enabled": True},
            track="auto")
        render_page(page, OUT / "v1_word_table_after.png")
        print(f"  V1 word_table.pdf: OK (see {OUT}/v1_word_table_*.png)")
    doc.close()

# Scenario V2: excel_table.pdf
v2_pdf = TEST_FILES / "excel_table.pdf"
if v2_pdf.exists():
    doc = fitz.open(str(v2_pdf))
    page = doc[0]
    td = page.get_text("dict")
    blocks = [b for b in td["blocks"] if b["type"] == 0
              and fitz.Rect(b["bbox"]).width > 80
              and "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", [])).strip()]
    if blocks:
        b = max(blocks, key=lambda x: fitz.Rect(x["bbox"]).width * fitz.Rect(x["bbox"]).height)
        r = fitz.Rect(b["bbox"])
        orig = "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", []))
        render_page(page, OUT / "v2_excel_before.png")
        apply_object_edit(page=page,
            object_info={"original_rect": r, "font": "helv", "size": 10.0,
                         "color": (0,0,0), "original_text": orig, "page_rotation": page.rotation},
            changes={"new_text": "New data value", "font": "helv", "size": 10.0,
                     "color": (0,0,0), "reflow_enabled": True},
            track="auto")
        render_page(page, OUT / "v2_excel_after.png")
        print("  V2 excel_table.pdf: OK")
    doc.close()

# Scenario V3: 1.pdf
v3_pdf = TEST_FILES / "1.pdf"
if v3_pdf.exists():
    doc = fitz.open(str(v3_pdf))
    page = doc[0]
    td = page.get_text("dict")
    blocks = [b for b in td["blocks"] if b["type"] == 0
              and fitz.Rect(b["bbox"]).width > 100
              and "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", [])).strip()]
    if blocks:
        b = max(blocks, key=lambda x: fitz.Rect(x["bbox"]).width * fitz.Rect(x["bbox"]).height)
        r = fitz.Rect(b["bbox"])
        orig = "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", []))
        render_page(page, OUT / "v3_simple_before.png")
        apply_object_edit(page=page,
            object_info={"original_rect": r, "font": "helv", "size": 12.0,
                         "color": (0,0,0), "original_text": orig, "page_rotation": page.rotation},
            changes={"new_text": "This is the replacement text for the first paragraph block.",
                     "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
            track="auto")
        render_page(page, OUT / "v3_simple_after.png")
        print("  V3 1.pdf: OK")
    doc.close()

# Scenario V4: Synthetic multi-column (the key UX scenario)
doc4 = fitz.open()
page4 = doc4.new_page(width=595, height=842)
# Two-column layout
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

render_page(page4, OUT / "v4_multicol_before.png")

apply_object_edit(page=page4,
    object_info={"original_rect": fitz.Rect(40, 80, 285, 200),
                 "font": "helv", "size": 12.0, "color": (0,0,0),
                 "original_text": "Chapter 1: Introduction\n\nThis is the first paragraph of the document. It contains multiple lines of text.",
                 "page_rotation": 0},
    changes={"new_text": "Chapter 1: Introduction — Revised Edition\n\nThis paragraph has been completely rewritten with substantially more content than the original version had, forcing the subsequent paragraph to move downward appropriately.",
             "font": "helv", "size": 12.0, "color": (0,0,0), "reflow_enabled": True},
    track="A")

render_page(page4, OUT / "v4_multicol_after.png")
print("  V4 multi-column: OK")
doc4.close()

print(f"\n★ Vision PNG 輸出: {OUT}/")
print("  v1_word_table_before/after.png")
print("  v2_excel_before/after.png")
print("  v3_simple_before/after.png")
print("  v4_multicol_before/after.png")
