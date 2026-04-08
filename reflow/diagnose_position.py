"""
diagnose_position.py — 精確診斷編輯後各塊位置

顯示 before/after 所有 text block 的座標，並渲染標注圖。
"""
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reflow.track_A_core import TrackAEngine

OUT = ROOT / "reflow" / "_vision_output"
OUT.mkdir(exist_ok=True)

def render_with_boxes(page, path, title=""):
    """渲染頁面並用彩色框標出所有 text block。"""
    mat = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    # 在 pixmap 上畫框（用 page.draw_rect 是就地修改，改用 copy）
    tmp = fitz.open()
    tmp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    p2 = tmp[0]
    colors = [(1,0,0), (0,0.6,0), (0,0,1), (0.8,0.4,0)]
    blocks = [b for b in p2.get_text("dict")["blocks"] if b["type"] == 0]
    for i, b in enumerate(blocks):
        r = fitz.Rect(b["bbox"])
        p2.draw_rect(r, color=colors[i % len(colors)], width=1.5)
    pix2 = p2.get_pixmap(matrix=mat)
    pix2.save(str(path))
    tmp.close()

def dump_blocks(page, label):
    print(f"\n  [{label}] text blocks:")
    blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
    for i, b in enumerate(blocks):
        text = "".join(s["text"] for l in b.get("lines",[]) for s in l.get("spans",[]))
        print(f"    [{i}] y0={b['bbox'][1]:.1f} y1={b['bbox'][3]:.1f} "
              f"h={b['bbox'][3]-b['bbox'][1]:.1f}  {text[:50]!r}")
    return blocks

# ── 場景：短文字 → 長文字，下方有段落塊 ─────────────────────────────────────
print("="*60)
print("場景：1行 → 多行，下方段落塊位移測試")
print("="*60)

doc = fitz.open()
page = doc.new_page(width=595, height=842)

rect_edit  = fitz.Rect(72, 72, 400, 120)
rect_below = fitz.Rect(72, 130, 400, 170)

page.insert_textbox(rect_edit,  "Short.",     fontsize=12)
page.insert_textbox(rect_below, "Paragraph below the edited block.", fontsize=12)

blocks_before = dump_blocks(page, "BEFORE")
render_with_boxes(page, OUT / "diag_before.png", "BEFORE")

# 執行 reflow
long_text = ("This is a much longer replacement text that will span at least "
             "three lines when rendered inside the narrow editing rectangle.")

r = TrackAEngine().apply_object_edit(
    page,
    {"original_rect": rect_edit, "font": "helv", "size": 12.0,
     "color": (0,0,0), "original_text": "Short.", "page_rotation": 0},
    {"new_text": long_text, "reflow_enabled": True},
)

print(f"\n  result: success={r['success']} warnings={r['warnings']}")
if r.get("plan"):
    print(f"  plan.delta_y={r['plan'].delta_y:.2f}")
    print(f"  plan.affected_blocks={[(idx, round(ob.y0,1), round(nb.y0,1)) for idx,ob,nb in r['plan'].affected_blocks]}")

blocks_after = dump_blocks(page, "AFTER")
render_with_boxes(page, OUT / "diag_after.png", "AFTER")

# 計算實際位移
if blocks_before and blocks_after:
    print("\n  ── 位移量 ──")
    before_below_y0 = max(b["bbox"][1] for b in blocks_before[1:]) if len(blocks_before)>1 else None
    after_below_y0  = min(b["bbox"][1] for b in blocks_after  if b["bbox"][1] > 120) if blocks_after else None
    if before_below_y0 and after_below_y0:
        shift = after_below_y0 - before_below_y0
        print(f"  下方塊 y0: {before_below_y0:.1f} → {after_below_y0:.1f}  shift={shift:+.1f}pt")
        expected = r['plan'].delta_y if r.get('plan') else 0
        print(f"  plan.delta_y={expected:.1f}  actual_shift={shift:.1f}  diff={shift-expected:.1f}pt")

doc.close()
print(f"\n★ 輸出: {OUT}/diag_before.png / diag_after.png")
