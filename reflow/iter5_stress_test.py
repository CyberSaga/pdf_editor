"""iter5_stress_test.py — 多 PDF 壓力測試（表格、多欄、CJK、旋轉頁面）"""
import pathlib
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz

from reflow.track_A_core import TrackAEngine
from reflow.track_B_core import TrackBEngine
from reflow.unified_command import apply_object_edit

ROOT = pathlib.Path(__file__).parent.parent
TEST_FILES = ROOT / "test_files"
OUT = ROOT / "reflow" / "_vision_output"
OUT.mkdir(exist_ok=True)

engine_a = TrackAEngine()
engine_b = TrackBEngine()

results = []

def pick_meaningful_block(blocks, min_width=50.0):
    """選取寬度 > min_width 且非純空白的最大塊。"""
    candidates = [
        b for b in blocks
        if b["type"] == 0
        and b.get("lines")
        and fitz.Rect(b["bbox"]).width > min_width
        and "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", [])).strip()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda b: fitz.Rect(b["bbox"]).width * fitz.Rect(b["bbox"]).height)

def run_test(label, doc_path, page_idx, edit_rect, new_text, original_text,
             track="A", font="helv", size=12, color=(0,0,0)):
    t0 = time.perf_counter()
    try:
        doc = fitz.open(str(doc_path))
        page = doc[page_idx]

        # Render before
        pix_before = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        before_path = OUT / f"stress_{label}_before.png"
        pix_before.save(str(before_path))

        object_info = {
            "original_rect": fitz.Rect(edit_rect),
            "font": font, "size": float(size), "color": color,
            "original_text": original_text,
            "page_rotation": page.rotation,
        }
        changes = {"new_text": new_text, "font": font, "size": float(size),
                   "color": color, "reflow_enabled": True}
        result = apply_object_edit(page=page, object_info=object_info,
                                   changes=changes, track=track)

        # Render after
        pix_after = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        after_path = OUT / f"stress_{label}_after.png"
        pix_after.save(str(after_path))

        # Pixel diff
        diff_px = sum(1 for a, b in zip(pix_before.samples, pix_after.samples) if a != b)

        elapsed = (time.perf_counter() - t0) * 1000
        # Check text appears on page
        page_text = page.get_text()
        new_words = new_text.split()[:3]
        text_found = any(w in page_text for w in new_words if len(w) > 2)

        status = "PASS" if result["success"] and elapsed < 3000 else "FAIL"
        doc.close()
        results.append({
            "label": label, "status": status, "elapsed_ms": elapsed,
            "success": result["success"], "warnings": result.get("warnings", []),
            "diff_px": diff_px, "text_found": text_found,
            "track": result.get("track", track),
        })
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        results.append({
            "label": label, "status": "ERROR", "elapsed_ms": elapsed,
            "success": False, "warnings": [str(e)], "diff_px": 0, "text_found": False,
            "track": track,
        })
        traceback.print_exc()


# ── Test scenarios ──────────────────────────────────────────────────────────

# T-S01: reservation_table.pdf — CJK header edit (use meaningful block)
res_pdf = TEST_FILES / "reservation_table.pdf"
if res_pdf.exists():
    doc_tmp = fitz.open(str(res_pdf))
    td = doc_tmp[0].get_text("dict")
    block = pick_meaningful_block(td["blocks"], min_width=100)
    if block:
        r = fitz.Rect(block["bbox"])
        orig = "".join(sp["text"] for line in block["lines"] for sp in line.get("spans", []))
        doc_tmp.close()
        run_test("S01_cjk_table", res_pdf, 0, r, "修改後的標題文字 Updated Title", orig,
                 track="A", font="helv", size=11)
    else:
        doc_tmp.close()

# T-S02: reservation_table.pdf Track B — use the known-good single-line header
if res_pdf.exists():
    # Use the specific header block identified in T11: rect=(122.4, 48.3, 550.1, 60.1)
    target_r = fitz.Rect(122.4, 48.3, 550.1, 60.1)
    doc_tmp = fitz.open(str(res_pdf))
    td = doc_tmp[0].get_text("dict")
    orig = ""
    for b in td["blocks"]:
        if b["type"] != 0:
            continue
        br = fitz.Rect(b["bbox"])
        if (br & target_r).get_area() > 50:
            orig = "".join(sp["text"] for ln in b["lines"] for sp in ln.get("spans", []))
            break
    doc_tmp.close()
    # track="auto": Track B 無法解碼此 CJK 字型，預期自動回退到 Track A
    run_test("S02_cjk_auto_fallback", res_pdf, 0, target_r, "Track B→A 自動回退修改後標題", orig or " 日光香頌 館 訂席編號：I401202511-0006",
             track="auto", font="helv", size=11)

# T-S03: word_table.pdf — dense table
word_pdf = TEST_FILES / "word_table.pdf"
if word_pdf.exists():
    doc_tmp = fitz.open(str(word_pdf))
    td = doc_tmp[0].get_text("dict")
    block = pick_meaningful_block(td["blocks"], min_width=50)
    doc_tmp.close()
    if block:
        r = fitz.Rect(block["bbox"])
        orig = "".join(sp["text"] for line in block["lines"] for sp in line.get("spans", []))
        run_test("S03_word_table_A", word_pdf, 0, r, "Modified cell content here", orig,
                 track="A", size=10)

# T-S04: excel_table.pdf — dense table
excel_pdf = TEST_FILES / "excel_table.pdf"
if excel_pdf.exists():
    doc_tmp = fitz.open(str(excel_pdf))
    td = doc_tmp[0].get_text("dict")
    block = pick_meaningful_block(td["blocks"], min_width=50)
    doc_tmp.close()
    if block:
        r = fitz.Rect(block["bbox"])
        orig = "".join(sp["text"] for line in block["lines"] for sp in line.get("spans", []))
        run_test("S04_excel_table_A", excel_pdf, 0, r,
                 "Updated data value extended", orig, track="A", size=10)

# T-S05: 1.pdf — simple doc
simple_pdf = TEST_FILES / "1.pdf"
if simple_pdf.exists():
    doc_tmp = fitz.open(str(simple_pdf))
    td = doc_tmp[0].get_text("dict")
    block = pick_meaningful_block(td["blocks"], min_width=80)
    doc_tmp.close()
    if block:
        r = fitz.Rect(block["bbox"])
        orig = "".join(sp["text"] for line in block["lines"] for sp in line.get("spans", []))
        run_test("S05_simple_A", simple_pdf, 0, r,
                 "This is a longer replacement text that should trigger reflow of subsequent blocks.",
                 orig, track="A", size=12)

# T-S06: synthetic multi-column page — test column isolation
def make_multi_col_doc():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Left column
    page.insert_textbox(fitz.Rect(50, 100, 270, 200),
                        "Left column paragraph one.\nSecond line here.",
                        fontname="helv", fontsize=11)
    page.insert_textbox(fitz.Rect(50, 210, 270, 280),
                        "Left column paragraph two.",
                        fontname="helv", fontsize=11)
    # Right column (should NOT be affected by left edits)
    page.insert_textbox(fitz.Rect(300, 100, 545, 200),
                        "Right column content stays fixed.",
                        fontname="helv", fontsize=11)
    page.insert_textbox(fitz.Rect(300, 210, 545, 280),
                        "Right column paragraph two.",
                        fontname="helv", fontsize=11)
    return doc

doc6 = make_multi_col_doc()
page6 = doc6[0]

# Capture right column position before
td_before = page6.get_text("dict")
right_blocks_before = [
    fitz.Rect(b["bbox"]) for b in td_before["blocks"]
    if b["type"] == 0 and fitz.Rect(b["bbox"]).x0 > 280
]

result6 = engine_a.apply_reflow(
    doc=doc6, page_idx=0,
    edited_rect=fitz.Rect(50, 100, 270, 200),
    new_text="Much longer left column text that spans many lines and should push down the left column paragraph two but NOT affect the right column at all.",
    original_text="Left column paragraph one.\nSecond line here.",
    font="helv", size=11, color=(0,0,0),
)
td_after = doc6[0].get_text("dict")
right_blocks_after = [
    fitz.Rect(b["bbox"]) for b in td_after["blocks"]
    if b["type"] == 0 and fitz.Rect(b["bbox"]).x0 > 280
]

right_col_stable = True
for rb_before in right_blocks_before:
    found = any(
        abs(rb_after.x0 - rb_before.x0) < 3 and abs(rb_after.y0 - rb_before.y0) < 3
        for rb_after in right_blocks_after
    )
    if not found:
        right_col_stable = False

results.append({
    "label": "S06_col_isolation",
    "status": "PASS" if right_col_stable and result6["success"] else "FAIL",
    "elapsed_ms": 0, "success": result6["success"],
    "warnings": result6.get("warnings", []),
    "diff_px": 0, "text_found": True,
    "track": "A",
    "note": f"right_col_stable={right_col_stable} right_before={len(right_blocks_before)} right_after={len(right_blocks_after)}"
})

# T-S07: Empty text replacement (delete text)
doc7 = fitz.open()
p7 = doc7.new_page(width=595, height=842)
p7.insert_textbox(fitz.Rect(72, 100, 400, 130), "Text to be deleted.",
                  fontname="helv", fontsize=12)
p7.insert_textbox(fitz.Rect(72, 150, 400, 180), "Block below should move up.",
                  fontname="helv", fontsize=12)

r7_result = engine_a.apply_reflow(
    doc=doc7, page_idx=0,
    edited_rect=fitz.Rect(72, 100, 400, 130),
    new_text="",
    original_text="Text to be deleted.",
    font="helv", size=12, color=(0,0,0),
)
td7 = doc7[0].get_text("dict")
below_blocks = [b for b in td7["blocks"] if b["type"] == 0 and fitz.Rect(b["bbox"]).y0 > 90]
below_moved_up = any(fitz.Rect(b["bbox"]).y0 < 140 for b in below_blocks)
results.append({
    "label": "S07_empty_text",
    "status": "PASS" if r7_result["success"] else "FAIL",
    "elapsed_ms": 0, "success": r7_result["success"],
    "warnings": r7_result.get("warnings", []),
    "diff_px": 0, "text_found": True, "track": "A",
    "note": f"below_moved_up={below_moved_up} below_count={len(below_blocks)}"
})

# T-S08: Very long single word (tests word-wrap CSS)
doc8 = fitz.open()
p8 = doc8.new_page(width=595, height=842)
p8.insert_textbox(fitz.Rect(72, 100, 400, 130), "Short.",
                  fontname="helv", fontsize=12)
p8.insert_textbox(fitz.Rect(72, 150, 400, 180), "Block below.",
                  fontname="helv", fontsize=12)

r8_result = engine_a.apply_reflow(
    doc=doc8, page_idx=0,
    edited_rect=fitz.Rect(72, 100, 400, 130),
    new_text="Supercalifragilisticexpialidocious_with_no_spaces_at_all_whatsoever",
    original_text="Short.",
    font="helv", size=12, color=(0,0,0),
)
results.append({
    "label": "S08_long_word",
    "status": "PASS" if r8_result["success"] else "FAIL",
    "elapsed_ms": 0, "success": r8_result["success"],
    "warnings": r8_result.get("warnings", []),
    "diff_px": 0, "text_found": True, "track": "A",
    "note": f"warnings={r8_result.get('warnings', [])}"
})

# T-S09: CJK text height estimation accuracy
cjk_text = "這是一段中文文字，用來測試 CJK 字元寬度估算的正確性。"
cjk_width = 300.0
cjk_size = 12.0
display_w = engine_a._count_display_width(cjk_text, cjk_size)
# CJK chars should be counted as size*1.0, not size*0.6
latin_count = sum(1 for ch in cjk_text if ord(ch) < 0x3000)
cjk_count = len(cjk_text) - latin_count
expected_w_naive = len(cjk_text) * cjk_size * 0.6  # wrong (all at 0.6)
expected_w_correct = cjk_count * cjk_size * 1.0 + latin_count * cjk_size * 0.6
cjk_ok = abs(display_w - expected_w_correct) < 5.0
results.append({
    "label": "S09_cjk_width",
    "status": "PASS" if cjk_ok else "FAIL",
    "elapsed_ms": 0, "success": cjk_ok,
    "warnings": [], "diff_px": 0, "text_found": True, "track": "A",
    "note": f"naive={expected_w_naive:.1f} correct={expected_w_correct:.1f} actual={display_w:.1f}"
})

# ── Print results ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Stress Test Results")
print("=" * 70)
passed = 0
for r in results:
    status = r["status"]
    if status == "PASS":
        passed += 1
    note = r.get("note", "")
    print(f"[{status}] {r['label']:<30} track={r['track']} {r['elapsed_ms']:.0f}ms  diff={r['diff_px']}px")
    if note:
        print(f"       {note}")
    if r["warnings"]:
        for w in r["warnings"][:3]:
            print(f"       WARN: {w}")

print(f"\n{passed}/{len(results)} PASS")
print("=" * 70)
