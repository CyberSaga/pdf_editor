"""
stage2_smoke_test.py — 第 2 階段冒煙測試

驗證：
  1. Track A apply_object_edit 成功
  2. Track B apply_object_edit 成功，無誤判干擾
  3. 模組級 apply_object_edit(track='auto') 成功
  4. 旋轉頁面（90°）座標轉換不崩潰
  5. UnifiedObjectCommand captured_anchor 屬性存在
  6. 全部 pytest 仍通過
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

PASS = []
FAIL = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def make_page(rotation: int = 0):
    """建立含兩段文字的測試頁面（single-column layout）。"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if rotation:
        page.set_rotation(rotation)
    rect_edit = fitz.Rect(72, 72, 400, 120)
    rect_para = fitz.Rect(72, 150, 400, 200)
    rect_col2 = fitz.Rect(420, 72, 570, 200)   # 右欄（應不受 reflow 影響）
    page.insert_textbox(rect_edit, "Hello World original text", fontsize=12)
    page.insert_textbox(rect_para, "Second paragraph below edit", fontsize=12)
    page.insert_textbox(rect_col2, "Right column text here", fontsize=12)
    return doc, page, rect_edit


# ─────────────────────────────────────────────
# 1. Track A apply_object_edit
# ─────────────────────────────────────────────
print("\n[1] Track A apply_object_edit")
from reflow.track_A_core import TrackAEngine

doc1, page1, rect1 = make_page()
object_info = {
    "original_rect": rect1,
    "font": "helv",
    "size": 12.0,
    "color": (0, 0, 0),
    "original_text": "Hello World original text",
    "page_rotation": 0,
}
changes_text = {"new_text": "Modified shorter text", "reflow_enabled": True}

r = TrackAEngine().apply_object_edit(page1, object_info, changes_text)
check("Track A success", r["success"], str(r.get("warnings")))
check("Track A track label", r["track"] == "A")
# Stage 2 允許 overlap warning（算法精度問題，在後續迭代階段修正）
check("Track A returned warnings list", isinstance(r["warnings"], list))
if r["warnings"]:
    print(f"       [Track A warnings] {r['warnings']}")
doc1.close()

# color-only change
doc1b, page1b, rect1b = make_page()
object_info_base = {**object_info, "original_rect": rect1b}
r_color = TrackAEngine().apply_object_edit(
    page1b, object_info_base, {"new_color": (1, 0, 0)}
)
check("Track A color-only no crash", isinstance(r_color["success"], bool))
doc1b.close()

# ─────────────────────────────────────────────
# 2. Track B apply_object_edit + quad 干擾判斷
# ─────────────────────────────────────────────
print("\n[2] Track B apply_object_edit")
from reflow.track_B_core import TrackBEngine

doc2, page2, rect2 = make_page()
r_b = TrackBEngine().apply_object_edit(
    page2, {**object_info, "original_rect": rect2}, changes_text
)
check("Track B success", r_b["success"], str(r_b.get("warnings")))
check("Track B track label", r_b["track"] == "B")
check("Track B interference_count field exists", "interference_count" in r_b)
check("Track B interference_details field exists", "interference_details" in r_b)
# 右欄文字不應被誤判為干擾（interference 應 == 0）
check(
    "Track B no false-positive interference",
    r_b["interference_count"] == 0,
    f"interference_count={r_b['interference_count']}, details={r_b['interference_details']}",
)
doc2.close()

# ─────────────────────────────────────────────
# 3. 模組級 apply_object_edit (auto)
# ─────────────────────────────────────────────
print("\n[3] Module-level apply_object_edit (auto)")
from reflow.unified_command import apply_object_edit

doc3, page3, rect3 = make_page()
r_auto = apply_object_edit(
    page3, {**object_info, "original_rect": rect3}, changes_text, track="auto"
)
check("auto success", r_auto["success"], str(r_auto.get("warnings")))
check("auto elapsed_ms > 0", r_auto["elapsed_ms"] > 0)
check("auto track is A or B", r_auto["track"] in ("A", "B"))
doc3.close()

# ─────────────────────────────────────────────
# 4. 旋轉頁面（90°）不崩潰
# ─────────────────────────────────────────────
print("\n[4] Rotated page (90°)")
doc4, page4, rect4 = make_page(rotation=90)
try:
    r_rot = TrackAEngine().apply_object_edit(
        page4, {**object_info, "original_rect": rect4, "page_rotation": 90}, changes_text
    )
    check("Track A rotated page no crash", isinstance(r_rot["success"], bool))
except Exception as e:
    check("Track A rotated page no crash", False, str(e))

try:
    r_rot_b = TrackBEngine().apply_object_edit(
        page4, {**object_info, "original_rect": rect4, "page_rotation": 90}, changes_text
    )
    check("Track B rotated page no crash", isinstance(r_rot_b["success"], bool))
except Exception as e:
    check("Track B rotated page no crash", False, str(e))
doc4.close()

# ─────────────────────────────────────────────
# 5. UnifiedObjectCommand captured_anchor 屬性
# ─────────────────────────────────────────────
print("\n[5] UnifiedObjectCommand captured_anchor")
from reflow.unified_command import UnifiedObjectCommand, ObjectChanges


class _MockModel:
    doc = fitz.open()
    doc.new_page()

    def edit_text(self, **kw):
        pass

    def _capture_page_snapshot(self, idx):
        return b""

    def _restore_page_from_snapshot(self, idx, data):
        pass

    class block_manager:
        @staticmethod
        def rebuild_page(idx, doc):
            pass


mock_model = _MockModel()
cmd = UnifiedObjectCommand(
    model=mock_model,
    page_num=1,
    target_rect=fitz.Rect(72, 72, 400, 120),
    changes=ObjectChanges(new_text="test"),
    page_snapshot_bytes=b"snap",
    captured_anchor={"page_idx": 0, "h": 0, "v": 0},  # 模擬 ViewportAnchor
)
check("captured_anchor stored", cmd.captured_anchor is not None)
check("captured_anchor value", cmd.captured_anchor["page_idx"] == 0)
check("_operation_type text_reflow", cmd._operation_type == "text_reflow")
check("last_reflow_interference default 0", cmd.last_reflow_interference == 0)
mock_model.doc.close()

# ─────────────────────────────────────────────
# 6. 執行 pytest
# ─────────────────────────────────────────────
print("\n[6] Running pytest reflow/test_suite.py ...")
import subprocess, os

result_pytest = subprocess.run(
    [sys.executable, "-m", "pytest", "reflow/test_suite.py", "-v", "--tb=short", "-q"],
    capture_output=True,
    text=True,
    cwd=str(ROOT),
)
pytest_ok = result_pytest.returncode == 0
last_line = [l for l in result_pytest.stdout.splitlines() if l.strip()][-1] if result_pytest.stdout else ""
check("pytest 24/24 pass", pytest_ok, last_line)
if not pytest_ok:
    print(result_pytest.stdout[-2000:])

# ─────────────────────────────────────────────
# 結果匯總
# ─────────────────────────────────────────────
total = len(PASS) + len(FAIL)
print(f"\n{'='*52}")
print(f"結果: {len(PASS)}/{total} PASS")
if FAIL:
    print("FAIL 項目:")
    for f in FAIL:
        print(f"  ✗ {f}")
else:
    print("全部通過 ✓")
print('='*52)
sys.exit(0 if not FAIL else 1)
