"""iter4_overlap_audit.py — 診斷 verify_no_overlap 回報的重疊原因"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz

from reflow.track_A_core import TrackAEngine


def make_two_block_doc():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # 左欄 block
    page.insert_textbox(fitz.Rect(72, 100, 280, 150), "Left column text here.",
                        fontname="helv", fontsize=11)
    # 右欄 block
    page.insert_textbox(fitz.Rect(310, 100, 520, 150), "Right column text here.",
                        fontname="helv", fontsize=11)
    # 下方 block
    page.insert_textbox(fitz.Rect(72, 200, 520, 250), "Body paragraph below both columns.",
                        fontname="helv", fontsize=11)
    return doc

def show_overlaps(page, label):
    engine = TrackAEngine()
    result = engine.verify_no_overlap(page)
    print(f"\n[{label}] clean={result['clean']}, overlaps={len(result['overlaps'])}")
    for o in result['overlaps']:
        print(f"  {o}")
    # Print all block bboxes
    td = page.get_text("dict")
    for i, b in enumerate(td.get("blocks", [])):
        if b.get("type") == 0:
            r = fitz.Rect(b["bbox"])
            txt = ""
            for line in b.get("lines", []):
                for sp in line.get("spans", []):
                    txt += sp.get("text", "")
            print(f"  block[{i}] {r} '{txt[:40]}'")

print("=" * 60)
print("Overlap audit: before and after Track A reflow")
print("=" * 60)

# Scenario 1: Normal two-column page
doc1 = make_two_block_doc()
page1 = doc1[0]
show_overlaps(page1, "BEFORE edit")

engine = TrackAEngine()
result = engine.apply_reflow(
    doc=doc1, page_idx=0,
    edited_rect=fitz.Rect(72, 100, 280, 150),
    new_text="Left column replacement with more text here.",
    original_text="Left column text here.",
    font="helv", size=11, color=(0,0,0),
)
print(f"\nReflow result: success={result['success']} warnings={result['warnings']}")
if result.get("plan"):
    print(f"  delta_y={result['plan'].delta_y:.2f} affected={len(result['plan'].affected_blocks)}")

show_overlaps(doc1[0], "AFTER edit")

# Scenario 2: Tight table-like layout (lots of small blocks)
print("\n" + "=" * 60)
print("Scenario 2: Dense table layout")
doc2 = fitz.open()
page2 = doc2.new_page(width=595, height=842)
# Create many rows
for i in range(8):
    y = 50 + i * 30
    page2.insert_textbox(fitz.Rect(50, y, 200, y+25), f"Cell A{i+1}",
                         fontname="helv", fontsize=10)
    page2.insert_textbox(fitz.Rect(210, y, 360, y+25), f"Cell B{i+1}",
                         fontname="helv", fontsize=10)
    page2.insert_textbox(fitz.Rect(370, y, 520, y+25), f"Cell C{i+1}",
                         fontname="helv", fontsize=10)

show_overlaps(page2, "Table BEFORE edit")

result2 = engine.apply_reflow(
    doc=doc2, page_idx=0,
    edited_rect=fitz.Rect(50, 50, 200, 75),
    new_text="Extended content that wraps to next line.",
    original_text="Cell A1",
    font="helv", size=10, color=(0,0,0),
)
print(f"\nReflow result: success={result2['success']} warnings={result2['warnings']}")
show_overlaps(doc2[0], "Table AFTER edit")
