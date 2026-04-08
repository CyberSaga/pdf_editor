"""
explore_test_pdfs.py — 探索 test_files/ 中的 PDF 結構，找合適的測試段落
"""
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = ROOT / "test_files"

pdfs = [
    "1.pdf", "2.pdf", "word_table.pdf", "reservation_table.pdf",
    "when I was young I.pdf", "excel_table.pdf",
]

for fname in pdfs:
    p = TEST_DIR / fname
    if not p.exists():
        continue
    doc = fitz.open(str(p))
    page = doc[0]
    blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
    # 找有實質文字的 block（非空白）
    good = [b for b in blocks if
            len(''.join(s["text"] for l in b.get("lines",[]) for s in l.get("spans",[])).strip()) > 10]
    print(f"\n{'='*60}")
    print(f"{fname}: {len(doc)}p, page0={page.rect}, {len(good)} non-empty blocks")
    for i, b in enumerate(good[:4]):
        text = ''.join(s["text"] for l in b.get("lines",[]) for s in l.get("spans",[]))
        spans = [s for l in b.get("lines",[]) for s in l.get("spans",[])]
        font = spans[0]["font"] if spans else "?"
        size = spans[0]["size"] if spans else 0
        print(f"  [{i}] bbox={tuple(round(x,1) for x in b['bbox'])} "
              f"lines={len(b.get('lines',[]))} font={font} size={size:.1f}")
        print(f"      text={text[:80]!r}")
    doc.close()
