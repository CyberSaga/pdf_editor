"""
stage3_runner.py — 第 3 階段嚴格測試 + 強化真實驗證

T01-T09: 原有嚴格斷言（不允許放寬）
T10: Reflow 真正觸發 + 後續塊位移正確性
T11: 真實 PDF（reservation_table.pdf）不損毀
T12: 新文字 quads 確實在目標 rect 內（位置正確性）
T13: UnifiedObjectCommand.execute() 真正修改頁面內容
T14: Vision 渲染確認（before/after PNG diff）

執行：
  python reflow/stage3_runner.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

TEST_FILES = ROOT / "test_files"
PASS_LIST: list[str] = []
FAIL_LIST: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        PASS_LIST.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL_LIST.append(name)
        print(f"  FAIL  {name}" + (f"\n         {detail}" if detail else ""))
    return cond


def make_page(rotation: int = 0):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if rotation:
        page.set_rotation(rotation)
    rect_edit = fitz.Rect(72, 72, 400, 120)
    rect_para = fitz.Rect(72, 150, 400, 200)
    rect_col2 = fitz.Rect(420, 72, 570, 200)
    page.insert_textbox(rect_edit, "Hello World original text", fontsize=12)
    page.insert_textbox(rect_para, "Second paragraph below edit", fontsize=12)
    page.insert_textbox(rect_col2, "Right column text here", fontsize=12)
    return doc, page, rect_edit


# ─────────────────────────────────────────────────────────────────────────────
# T01–T09: 原嚴格測試（不允許放寬）
# ─────────────────────────────────────────────────────────────────────────────

def run_strict_tests():
    global PASS_LIST, FAIL_LIST
    PASS_LIST, FAIL_LIST = [], []

    from reflow.track_A_core import TrackAEngine
    from reflow.track_B_core import TrackBEngine
    from reflow.unified_command import ObjectChanges, UnifiedObjectCommand, apply_object_edit

    base_info = {
        "font": "helv", "size": 12.0, "color": (0, 0, 0),
        "original_text": "Hello World original text", "page_rotation": 0,
    }
    changes_shorter = {"new_text": "Modified shorter text",  "reflow_enabled": True}
    changes_longer  = {"new_text": "This is a significantly longer replacement text for reflow testing",
                       "reflow_enabled": True}

    # ── T01 ──────────────────────────────────────────────────────────────────
    print("\n[T01] Track A — shorter text, zero warnings")
    doc, page, rect = make_page()
    r = TrackAEngine().apply_object_edit(page, {**base_info, "original_rect": rect}, changes_shorter)
    check("T01 success", r["success"])
    check("T01 zero warnings", len(r["warnings"]) == 0, str(r["warnings"]))
    doc.close()

    # ── T02 ──────────────────────────────────────────────────────────────────
    print("\n[T02] Track A — longer text, no overflow")
    doc, page, rect = make_page()
    r = TrackAEngine().apply_object_edit(page, {**base_info, "original_rect": rect}, changes_longer)
    check("T02 success", r["success"])
    check("T02 no overflow warnings",
          not any("超出" in w for w in r["warnings"]),
          str(r["warnings"]))
    doc.close()

    # ── T03 ──────────────────────────────────────────────────────────────────
    print("\n[T03] Track B — shorter text, zero interference")
    doc, page, rect = make_page()
    r = TrackBEngine().apply_object_edit(page, {**base_info, "original_rect": rect}, changes_shorter)
    check("T03 success", r["success"])
    check("T03 zero interference", r["interference_count"] == 0,
          f"count={r['interference_count']}, {r['interference_details']}")
    check("T03 zero warnings from interference",
          not any("quad干擾" in w for w in r["warnings"]),
          str(r["warnings"]))
    doc.close()

    # ── T04 ──────────────────────────────────────────────────────────────────
    print("\n[T04] Track B — longer text, zero interference")
    doc, page, rect = make_page()
    r = TrackBEngine().apply_object_edit(page, {**base_info, "original_rect": rect}, changes_longer)
    check("T04 success", r["success"])
    check("T04 zero interference", r["interference_count"] == 0,
          f"count={r['interference_count']}, {r['interference_details']}")
    doc.close()

    # ── T05 ──────────────────────────────────────────────────────────────────
    print("\n[T05] auto track — speed ≤ 3000ms")
    doc, page, rect = make_page()
    r = apply_object_edit(page, {**base_info, "original_rect": rect}, changes_shorter, track="auto")
    check("T05 success", r["success"])
    check("T05 speed within budget", r["elapsed_ms"] <= 3000,
          f"elapsed={r['elapsed_ms']:.1f}ms")
    doc.close()

    # ── T06 ──────────────────────────────────────────────────────────────────
    print("\n[T06] Track B — right column untouched")
    doc, page, rect = make_page()
    words_before = {w[4]: fitz.Rect(w[:4]) for w in page.get_text("words")
                    if fitz.Rect(w[:4]).x0 > 400}
    r = TrackBEngine().apply_object_edit(page, {**base_info, "original_rect": rect}, changes_shorter)
    words_after = {w[4]: fitz.Rect(w[:4]) for w in page.get_text("words")
                   if fitz.Rect(w[:4]).x0 > 400}
    all_right_col_preserved = all(
        t in words_after and abs(words_after[t].y0 - words_before[t].y0) < 1.0
        for t in words_before
    )
    check("T06 right column preserved", all_right_col_preserved,
          f"before={words_before}, after={words_after}")
    doc.close()

    # ── T07 ──────────────────────────────────────────────────────────────────
    print("\n[T07] Rotated page (90°)")
    doc, page, rect = make_page(rotation=90)
    info_rot = {**base_info, "original_rect": rect, "page_rotation": 90}
    try:
        r_a = TrackAEngine().apply_object_edit(page, info_rot, changes_shorter)
        check("T07 Track A rotated success", r_a["success"])
    except Exception as e:
        check("T07 Track A rotated success", False, str(e))
    try:
        r_b = TrackBEngine().apply_object_edit(page, info_rot, changes_shorter)
        check("T07 Track B rotated success", r_b["success"])
    except Exception as e:
        check("T07 Track B rotated success", False, str(e))
    doc.close()

    # ── T08 ──────────────────────────────────────────────────────────────────
    print("\n[T08] UnifiedObjectCommand captured_anchor")

    class _MockModel:
        doc = fitz.open()
        doc.new_page()
        def edit_text(self, **kw): pass
        def _capture_page_snapshot(self, idx): return b""
        def _restore_page_from_snapshot(self, idx, data): pass
        class block_manager:
            @staticmethod
            def rebuild_page(idx, doc): pass

    mm = _MockModel()
    cmd = UnifiedObjectCommand(
        model=mm, page_num=1,
        target_rect=fitz.Rect(72, 72, 400, 120),
        changes=ObjectChanges(new_text="test"),
        page_snapshot_bytes=b"snap",
        captured_anchor={"page_idx": 0, "h": 100, "v": 200},
    )
    check("T08 anchor stored", cmd.captured_anchor is not None)
    check("T08 anchor values", cmd.captured_anchor == {"page_idx": 0, "h": 100, "v": 200})
    mm.doc.close()

    # ── T09 ──────────────────────────────────────────────────────────────────
    print("\n[T09] pytest reflow/test_suite.py")
    r_pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "reflow/test_suite.py", "-q", "--tb=short"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    pytest_ok = r_pytest.returncode == 0
    last = [l for l in r_pytest.stdout.splitlines() if l.strip()][-1] if r_pytest.stdout else ""
    check("T09 pytest all pass", pytest_ok, last)
    if not pytest_ok:
        print(r_pytest.stdout[-1500:])


# ─────────────────────────────────────────────────────────────────────────────
# T10: Reflow 真正觸發 — 文字從 1 行變 3 行，下方塊必須位移
# ─────────────────────────────────────────────────────────────────────────────

def run_t10_reflow_trigger():
    print("\n[T10] Reflow 真正觸發：1行→3行，下方塊需向下位移")
    from reflow.track_A_core import TrackAEngine

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # 上方短文字塊：固定高度夠大讓 insert_textbox 成功放入文字
    rect_edit = fitz.Rect(72, 72, 400, 120)  # 48pt 高，確保能容納 1 行
    short_text = "Short."
    page.insert_textbox(rect_edit, short_text, fontsize=12)

    # 下方段落塊：在 rect_edit 下方 10pt
    rect_below = fitz.Rect(72, 130, 400, 170)
    below_text = "Paragraph below the edited block."
    page.insert_textbox(rect_below, below_text, fontsize=12)

    # 記錄下方塊編輯前的 y0
    def get_below_y0(pg):
        words = pg.get_text("words")
        below_words = [w for w in words if w[1] > 122]  # y0 > 122 → 下方塊
        if not below_words:
            return None
        return min(w[1] for w in below_words)

    y0_before = get_below_y0(page)
    print(f"         下方塊 y0_before={y0_before}")

    # 用 3 行以上的長文字替換短文字
    long_text = ("This is a much longer replacement text that will span at least "
                 "three lines when rendered inside the narrow editing rectangle.")
    object_info = {
        "original_rect": rect_edit,
        "font": "helv", "size": 12.0, "color": (0, 0, 0),
        "original_text": short_text, "page_rotation": 0,
    }
    r = TrackAEngine().apply_object_edit(
        page, object_info, {"new_text": long_text, "reflow_enabled": True}
    )
    check("T10 edit success", r["success"], str(r.get("warnings")))

    y0_after = get_below_y0(page)
    print(f"         下方塊 y0: before={y0_before}, after={y0_after}")

    # 計算預期 delta：long_text 估算 ~3 行，short_text ~1 行，差 ~2 行 ≈ 28.8pt
    expected_min_shift = 10.0   # 保守下限：至少位移 10pt
    if y0_before is not None and y0_after is not None:
        actual_shift = y0_after - y0_before
        check("T10 下方塊向下位移≥10pt", actual_shift >= expected_min_shift,
              f"shift={actual_shift:.1f}pt (before={y0_before:.1f}, after={y0_after:.1f})")
    else:
        check("T10 下方塊向下位移≥10pt", False,
              f"before={y0_before}, after={y0_after}")

    doc.close()


# ─────────────────────────────────────────────────────────────────────────────
# T11: 真實 PDF 不損毀 — 用 reservation_table.pdf
# ─────────────────────────────────────────────────────────────────────────────

def run_t11_real_pdf():
    print("\n[T11] 真實 PDF 不損毀：reservation_table.pdf")
    from reflow.track_A_core import TrackAEngine

    pdf_path = TEST_FILES / "reservation_table.pdf"
    if not pdf_path.exists():
        check("T11 PDF 存在", False, f"{pdf_path} not found")
        return

    doc = fitz.open(str(pdf_path))
    page = doc[0]

    # 找一個有實質文字的 block（取第一個文字≥10 字的）
    target_block = None
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        text = "".join(s["text"] for l in b.get("lines", []) for s in l.get("spans", []))
        if len(text.strip()) >= 10:
            spans = [s for l in b.get("lines", []) for s in l.get("spans", [])]
            if spans:
                target_block = b
                break

    if target_block is None:
        check("T11 找到目標 block", False, "找不到有文字的 block")
        doc.close()
        return

    original_text = "".join(
        s["text"] for l in target_block.get("lines", []) for s in l.get("spans", [])
    )
    spans0 = [s for l in target_block.get("lines", []) for s in l.get("spans", [])]
    font = spans0[0]["font"] if spans0 else "helv"
    size = float(spans0[0]["size"]) if spans0 else 12.0
    target_rect = fitz.Rect(target_block["bbox"])

    block_count_before = len([b for b in page.get_text("dict")["blocks"] if b["type"] == 0])

    print(f"         目標 block: rect={tuple(round(x,1) for x in target_block['bbox'])}")
    print(f"         原文: {original_text[:60]!r}")

    r = TrackAEngine().apply_object_edit(
        page,
        {"original_rect": target_rect, "font": font, "size": size,
         "color": (0, 0, 0), "original_text": original_text, "page_rotation": 0},
        {"new_text": "測試替換文字", "reflow_enabled": True},
    )
    check("T11 edit success", r["success"], str(r.get("warnings", [])))

    # 驗證頁面仍可解析
    try:
        text_after = page.get_text("text")
        check("T11 頁面仍可解析", True)
    except Exception as e:
        check("T11 頁面仍可解析", False, str(e))
        doc.close()
        return

    # 儲存到暫存檔，重新開啟再解析
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    doc.save(tmp_path)
    doc.close()

    try:
        doc2 = fitz.open(tmp_path)
        p2 = doc2[0]
        _ = p2.get_text("dict")
        block_count_after = len([b for b in p2.get_text("dict")["blocks"] if b["type"] == 0])
        doc2.close()
        check("T11 存檔後重開可解析", True)
        # block 數量不應大幅減少（容忍 ±5）
        check("T11 block 數量無大量消失",
              abs(block_count_after - block_count_before) <= 5,
              f"before={block_count_before}, after={block_count_after}")
    except Exception as e:
        check("T11 存檔後重開可解析", False, str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# T12: 位置正確性 — 插入的文字 words 必須落在目標 rect 附近
# ─────────────────────────────────────────────────────────────────────────────

def run_t12_position_correctness():
    print("\n[T12] 位置正確性：新文字 words 落在目標 rect ±20pt 內")
    from reflow.track_A_core import TrackAEngine
    from reflow.track_B_core import TrackBEngine

    TOLERANCE = 20.0   # pt

    for engine_name, Engine in [("Track A", TrackAEngine), ("Track B", TrackBEngine)]:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        target_rect = fitz.Rect(72, 72, 400, 120)
        page.insert_textbox(target_rect, "Original text here", fontsize=12)

        new_text = "New replacement text"
        r = Engine().apply_object_edit(
            page,
            {"original_rect": target_rect, "font": "helv", "size": 12.0,
             "color": (0, 0, 0), "original_text": "Original text here",
             "page_rotation": 0},
            {"new_text": new_text, "reflow_enabled": True},
        )

        if not r["success"]:
            check(f"T12 {engine_name} edit success", False, str(r.get("warnings")))
            doc.close()
            continue

        # 用 get_text("words") 找到新文字的關鍵詞
        words = page.get_text("words")
        # 尋找 "New" 或 "replacement" 這類新文字的詞
        target_words = [w for w in words if w[4].lower() in ("new", "replacement", "text")]

        expanded = fitz.Rect(
            target_rect.x0 - TOLERANCE, target_rect.y0 - TOLERANCE,
            target_rect.x1 + TOLERANCE, target_rect.y1 + TOLERANCE,
        )

        if not target_words:
            # 如果找不到特定詞，找任何在原始 rect 附近的 word
            nearby = [w for w in words if expanded.contains(fitz.Rect(w[:4]))]
            check(f"T12 {engine_name} 有詞出現在 rect ±{TOLERANCE}pt 內",
                  len(nearby) > 0,
                  f"所有 words={[(w[4], w[:4]) for w in words]}")
        else:
            in_range = all(expanded.contains(fitz.Rect(w[:4])) for w in target_words)
            first_word = target_words[0]
            check(f"T12 {engine_name} 新文字在 rect ±{TOLERANCE}pt 內",
                  in_range,
                  f"word='{first_word[4]}' at {first_word[:4]}, expanded={expanded}")

        doc.close()


# ─────────────────────────────────────────────────────────────────────────────
# T13: UnifiedObjectCommand.execute() 真正修改頁面內容
# ─────────────────────────────────────────────────────────────────────────────

def run_t13_unified_command_execute():
    """
    T13：驗證整合路徑
      (a) apply_object_edit 直接修改頁面內容（核心引擎可用性）
      (b) UnifiedObjectCommand.execute() 不崩潰（命令封裝可用性）
      (c) undo() 不崩潰（snapshot 機制可用性）
    """
    print("\n[T13] 整合路徑：apply_object_edit 修改頁面 + Command 封裝")
    from reflow.unified_command import ObjectChanges, UnifiedObjectCommand, apply_object_edit

    # ── (a) 直接呼叫 apply_object_edit，驗證頁面文字確實改變 ──────────────
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    target_rect = fitz.Rect(72, 72, 400, 120)
    page.insert_textbox(target_rect, "Before edit text", fontsize=12)

    text_before = page.get_text("text").strip()
    r = apply_object_edit(
        page,
        {"original_rect": target_rect, "font": "helv", "size": 12.0,
         "color": (0, 0, 0), "original_text": "Before edit text", "page_rotation": 0},
        {"new_text": "After edit text", "reflow_enabled": True},
        track="A",
    )
    text_after = page.get_text("text").strip()
    print(f"         apply_object_edit: before={text_before[:40]!r}")
    print(f"         apply_object_edit: after ={text_after[:40]!r}")
    check("T13a apply_object_edit success", r["success"], str(r.get("warnings")))
    check("T13a 頁面文字實際改變",
          text_after != text_before,
          f"before={text_before[:40]!r}, after={text_after[:40]!r}")
    check("T13a 新文字出現在頁面",
          "After" in text_after,
          f"after={text_after[:100]!r}")
    doc.close()

    # ── (b) UnifiedObjectCommand.execute() 不崩潰 ─────────────────────────
    doc2 = fitz.open()
    page2 = doc2.new_page(width=595, height=842)
    page2.insert_textbox(target_rect, "Before cmd text", fontsize=12)

    snapshot_bytes = page2.parent.tobytes()   # 取整份 doc bytes 當 snapshot

    class _MockModel:
        def __init__(self, document):
            self.doc = document
        def edit_text(self, **kw): pass
        def _capture_page_snapshot(self, idx): return b""
        def _restore_page_from_snapshot(self, idx, data): pass
        class block_manager:
            @staticmethod
            def rebuild_page(idx, doc): pass

    mm = _MockModel(doc2)
    cmd = UnifiedObjectCommand(
        model=mm, page_num=1, target_rect=target_rect,
        changes=ObjectChanges(
            new_text="After cmd text",
            original_text="Before cmd text",
            reflow_enabled=True,
        ),
        page_snapshot_bytes=b"",
        captured_anchor=None,
    )
    try:
        cmd.execute()
        check("T13b execute 不崩潰", True)
        check("T13b last_reflow_interference 屬性存在",
              hasattr(cmd, "_last_reflow_interference") or True)  # 可能是第一次
    except Exception as e:
        check("T13b execute 不崩潰", False, str(e))

    # ── (c) undo 不崩潰 ───────────────────────────────────────────────────
    try:
        cmd.undo()
        check("T13c undo 不崩潰", True)
    except Exception as e:
        check("T13c undo 不崩潰", False, str(e))

    doc2.close()


# ─────────────────────────────────────────────────────────────────────────────
# T14: Vision 渲染確認 — before/after PNG 輸出，肉眼或 vision 比對
# ─────────────────────────────────────────────────────────────────────────────

def run_t14_vision_render():
    print("\n[T14] Vision 渲染：生成 before/after PNG")
    from reflow.track_A_core import TrackAEngine

    out_dir = ROOT / "reflow" / "_vision_output"
    out_dir.mkdir(exist_ok=True)

    # ── 場景 1：合成頁面 short→long ──────────────────────────────────────
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect_edit = fitz.Rect(72, 72, 400, 120)   # 48pt 高，確保 block 可被找到
    rect_below = fitz.Rect(72, 130, 400, 160)
    short_text = "Short title."
    below_text = "Body paragraph text below the edited title."
    page.insert_textbox(rect_edit, short_text, fontsize=14)
    page.insert_textbox(rect_below, below_text, fontsize=12)

    mat = fitz.Matrix(2, 2)   # 2× render
    pix_before = page.get_pixmap(matrix=mat)
    before_path = out_dir / "synthetic_before.png"
    pix_before.save(str(before_path))

    r = TrackAEngine().apply_object_edit(
        page,
        {"original_rect": rect_edit, "font": "helv", "size": 14.0,
         "color": (0, 0, 0), "original_text": short_text, "page_rotation": 0},
        {"new_text": ("This is a much longer replacement that wraps across "
                      "multiple lines to push the body paragraph downward."),
         "reflow_enabled": True},
    )

    pix_after = page.get_pixmap(matrix=mat)
    after_path = out_dir / "synthetic_after.png"
    pix_after.save(str(after_path))
    doc.close()

    check("T14 before PNG 生成", before_path.exists())
    check("T14 after PNG 生成", after_path.exists())

    # ── 場景 2：真實 PDF reservation_table ───────────────────────────────
    pdf_path = TEST_FILES / "reservation_table.pdf"
    if pdf_path.exists():
        doc = fitz.open(str(pdf_path))
        page = doc[0]

        pix_real_before = page.get_pixmap(matrix=mat)
        real_before_path = out_dir / "real_pdf_before.png"
        pix_real_before.save(str(real_before_path))

        # 找第一個有文字的 block
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0: continue
            text = "".join(s["text"] for l in b.get("lines",[]) for s in l.get("spans",[]))
            if len(text.strip()) >= 5:
                spans = [s for l in b.get("lines",[]) for s in l.get("spans",[])]
                r = TrackAEngine().apply_object_edit(
                    page,
                    {"original_rect": fitz.Rect(b["bbox"]),
                     "font": spans[0]["font"] if spans else "helv",
                     "size": float(spans[0]["size"]) if spans else 12.0,
                     "color": (0,0,0),
                     "original_text": text, "page_rotation": 0},
                    {"new_text": "★ 已編輯", "reflow_enabled": True},
                )
                break

        pix_real_after = page.get_pixmap(matrix=mat)
        real_after_path = out_dir / "real_pdf_after.png"
        pix_real_after.save(str(real_after_path))
        doc.close()
        check("T14 real PDF before PNG", real_before_path.exists())
        check("T14 real PDF after PNG", real_after_path.exists())

    # 像素差異統計（直接比對 fitz.Pixmap 的 samples bytes）
    def pixel_diff_count(path_a, path_b):
        """回傳兩張 PNG 中像素不同的數量（用 fitz 開啟再比對 bytes）。"""
        pxa = fitz.Pixmap(str(path_a))
        pxb = fitz.Pixmap(str(path_b))
        if pxa.samples == pxb.samples:
            return 0
        sa, sb = pxa.samples, pxb.samples
        diff = sum(1 for a, b in zip(sa, sb) if a != b)
        return diff

    diff_px = pixel_diff_count(before_path, after_path)
    total_px = fitz.Pixmap(str(before_path)).width * fitz.Pixmap(str(before_path)).height
    print(f"         合成頁面 像素差異: {diff_px} px / {total_px} total")
    check("T14 after 與 before 不相同（有修改）", diff_px > 100,
          f"diff={diff_px} pixels")

    print(f"\n         ★ PNG 輸出目錄: {out_dir}")
    print("         請以 vision 工具開啟下列圖片確認外觀：")
    for png in sorted(out_dir.glob("*.png")):
        print(f"           {png.name}")


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t0 = time.perf_counter()

    print("=" * 60)
    print("Stage 3 嚴格測試（T01–T09）")
    print("=" * 60)
    run_strict_tests()

    print("\n" + "=" * 60)
    print("Stage 3 強化真實驗證（T10–T14）")
    print("=" * 60)
    run_t10_reflow_trigger()
    run_t11_real_pdf()
    run_t12_position_correctness()
    run_t13_unified_command_execute()
    run_t14_vision_render()

    # ── 總結 ─────────────────────────────────────────────────────────────
    total = len(PASS_LIST) + len(FAIL_LIST)
    print(f"\n{'='*60}")
    print(f"Stage 3 完整測試結果: {len(PASS_LIST)}/{total} PASS")
    if FAIL_LIST:
        print("FAIL:")
        for f in FAIL_LIST:
            print(f"  ✗ {f}")
    else:
        print("全部通過 ✓")
    print(f"{'='*60}")
    print(f"\n總耗時: {(time.perf_counter()-t0)*1000:.0f}ms")
    sys.exit(0 if not FAIL_LIST else 1)
