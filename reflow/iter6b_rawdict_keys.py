"""iter6b_rawdict_keys.py — 確認 rawdict span 有哪些 keys"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import fitz

doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 120), "Short text sample.",
                    fontname="helv", fontsize=12)

td = page.get_text("rawdict")
for b in td["blocks"]:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            print("span keys:", list(span.keys()))
            print("chars sample:", span.get("chars", [])[:3])
            text_from_chars = "".join(ch.get("c","") for ch in span.get("chars", []))
            print(f"text from chars: '{text_from_chars}'")
            break
        break
    break
