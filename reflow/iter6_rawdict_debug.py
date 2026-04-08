"""iter6_rawdict_debug.py — dict vs rawdict text extraction 比較"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import fitz

# Create synthetic page
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 120), "Short text sample.",
                    fontname="helv", fontsize=12)

print("=== dict extraction ===")
td = page.get_text("dict")
for b in td["blocks"]:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            print(f"  span bbox={fitz.Rect(span['bbox'])} text='{span['text']}' font={span['font']}")

print("\n=== rawdict extraction ===")
td2 = page.get_text("rawdict")
for b in td2["blocks"]:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            print(f"  span bbox={fitz.Rect(span['bbox'])} text='{span['text']}' font={span['font']}")

# After insert_htmlbox
doc2 = fitz.open()
page2 = doc2.new_page(width=595, height=842)
page2.insert_htmlbox(fitz.Rect(72, 72, 400, 120), "HTML inserted text.",
                     css="* { font-family: helv; font-size: 12pt; }")

print("\n=== After insert_htmlbox: dict ===")
td3 = page2.get_text("dict")
for b in td3["blocks"]:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            print(f"  span bbox={fitz.Rect(span['bbox'])} text='{span['text']}' font={span['font']}")

print("\n=== After insert_htmlbox: rawdict ===")
td4 = page2.get_text("rawdict")
for b in td4["blocks"]:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            print(f"  span bbox={fitz.Rect(span['bbox'])} text='{span['text']}' font={span['font']}")
