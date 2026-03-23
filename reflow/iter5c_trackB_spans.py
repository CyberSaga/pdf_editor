"""iter5c_trackB_spans.py — 診斷 Track B 在真實 PDF 找不到 span 的原因"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import fitz
from reflow.track_B_core import TrackBEngine

ROOT = pathlib.Path(__file__).parent.parent
res_pdf = ROOT / "test_files" / "reservation_table.pdf"

doc = fitz.open(str(res_pdf))
page = doc[0]
engine = TrackBEngine()

analysis = engine.analyze_stream(page, 0)
target_rect = fitz.Rect(122.4, 48.3, 550.1, 60.1)

print(f"Total spans: {len(analysis.spans)}")
print(f"\nSpans near target rect {target_rect}:")
for sp in analysis.spans:
    intersection = sp.bbox & target_rect
    if not intersection.is_empty:
        print(f"  span[{sp.span_idx}] bbox={sp.bbox} text='{sp.text[:40]}' "
              f"font={sp.font_name} size={sp.font_size:.1f}")

print(f"\nAll spans in y=[40,70]:")
for sp in analysis.spans:
    if 40 <= sp.bbox.y0 <= 70 or 40 <= sp.bbox.y1 <= 70:
        print(f"  span[{sp.span_idx}] y0={sp.bbox.y0:.1f} y1={sp.bbox.y1:.1f} "
              f"x0={sp.bbox.x0:.1f} x1={sp.bbox.x1:.1f} "
              f"text='{sp.text[:30]}' stripped='{sp.text.strip()[:20]}'")

print(f"\nFirst 10 spans:")
for sp in analysis.spans[:10]:
    print(f"  span[{sp.span_idx}] bbox={sp.bbox} text='{sp.text[:30]}' stripped='{sp.text.strip()[:20]}'")
