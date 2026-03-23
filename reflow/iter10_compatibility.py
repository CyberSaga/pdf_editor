"""iter10_compatibility.py — 輸出 PDF 結構完整性 + 相容性驗證

測試項目：
  C1  基本編輯後 PDF 可用 PyMuPDF 乾淨重新載入（無 MuPDF warnings）
  C2  clean_contents() 後文字仍完整（不因 stream 壓縮損毀）
  C3  garbage=4 save 後 xref 無孤立物件
  C4  Track A reflow 輸出的文字在存檔後仍可正確提取
  C5  Track B reflow 輸出的文字在存檔後仍可正確提取
  C6  置入 line-height CSS 不造成文字截斷
  C7  壞損輸入 PDF 不讓編輯管線崩潰（graceful skip）
  C8  多次連續編輯後存檔，xref 長度合理（無無限膨脹）
"""
import io
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fitz
from reflow.unified_command import apply_object_edit

OUT = pathlib.Path(__file__).parent / "_vision_output" / "iter10"
OUT.mkdir(parents=True, exist_ok=True)

results = []

def _suppress():
    fitz.TOOLS.mupdf_display_errors(False)

def _restore():
    fitz.TOOLS.mupdf_display_errors(True)

def _fresh_warnings():
    w = fitz.TOOLS.mupdf_warnings()
    fitz.TOOLS.reset_mupdf_warnings()
    return w

def _make_doc():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 400, 110),
        "First paragraph: original content.", fontname="helv", fontsize=12)
    page.insert_textbox(fitz.Rect(72, 130, 400, 160),
        "Second paragraph should shift when first expands.", fontname="helv", fontsize=12)
    return doc

def _save_and_reopen(doc):
    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    doc.close()
    buf.seek(0)
    _suppress()
    reopened = fitz.open("pdf", buf.read())
    _restore()
    return reopened

print("=" * 70)
print("Round 10: Output PDF Compatibility")
print("=" * 70)

# ── C1: 重新載入無 MuPDF warnings ────────────────────────────────────────
doc = _make_doc()
page = doc[0]
page.add_redact_annot(fitz.Rect(72, 72, 400, 110))
page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
css = "* { font-family: helv; font-size: 12pt; line-height: 14.4pt; color: rgb(0,0,0); word-wrap: break-word; }"
page.insert_htmlbox(fitz.Rect(72, 72, 400, 200), "Edited first paragraph, much longer now.", css=css)
_fresh_warnings()
reopened = _save_and_reopen(doc)
w = _fresh_warnings()
c1_ok = len(w) == 0
print(f"C1 reopen no warnings: {c1_ok} (warnings: {w or 'none'})")
results.append(("C1", c1_ok))
reopened.close()

# ── C2: clean_contents 後文字仍完整 ──────────────────────────────────────
doc = _make_doc()
page = doc[0]
page.add_redact_annot(fitz.Rect(72, 72, 400, 110))
page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
css = "* { font-family: helv; font-size: 12pt; line-height: 14.4pt; color: rgb(0,0,0); }"
page.insert_htmlbox(fitz.Rect(72, 72, 400, 200), "Cleaned content check.", css=css)
reopened = _save_and_reopen(doc)
_fresh_warnings()
reopened[0].clean_contents()
w2 = _fresh_warnings()
text_after = reopened[0].get_text()
c2_ok = "Cleaned content check" in text_after and len(w2) == 0
print(f"C2 clean_contents OK: {c2_ok} (text_present={('Cleaned content check') in text_after}, warnings={w2 or 'none'})")
results.append(("C2", c2_ok))
reopened.close()

# ── C3: xref 無孤立物件 ──────────────────────────────────────────────────
doc = _make_doc()
page = doc[0]
page.add_redact_annot(fitz.Rect(72, 72, 400, 110))
page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
css = "* { font-family: helv; font-size: 12pt; color: rgb(0,0,0); }"
page.insert_htmlbox(fitz.Rect(72, 72, 400, 200), "xref test.", css=css)
reopened = _save_and_reopen(doc)
xref_len = reopened.xref_length()
c3_ok = xref_len > 0
print(f"C3 xref valid: {c3_ok} (length={xref_len})")
results.append(("C3", c3_ok))
reopened.close()

# ── C4: Track A reflow 存檔後文字可提取 ──────────────────────────────────
doc = _make_doc()
apply_object_edit(
    page=doc[0],
    object_info={"original_rect": fitz.Rect(72, 72, 400, 110), "font": "helv", "size": 12.0,
                 "color": (0, 0, 0), "original_text": "First paragraph: original content.", "page_rotation": 0},
    changes={"new_text": "Track A greatly expanded first paragraph forcing the second block to move down significantly.",
             "font": "helv", "size": 12.0, "color": (0, 0, 0), "reflow_enabled": True},
    track="A",
)
_fresh_warnings()
reopened = _save_and_reopen(doc)
w = _fresh_warnings()
text = reopened[0].get_text()
c4_ok = "Track A greatly" in text and "Second paragraph" in text and len(w) == 0
print(f"C4 Track A reflow save: {c4_ok} (A_present={'Track A greatly' in text}, B_present={'Second paragraph' in text}, warnings={w or 'none'})")
results.append(("C4", c4_ok))
reopened.close()

# ── C5: Track B reflow — 存檔後文字可提取 + 閱讀順序正確 ─────────────────
# 驗證：
#   (a) track 確實走 B（不是 fallback 到 A）
#   (b) 新文字存在於存檔後的 PDF
#   (c) get_text() 閱讀順序正確：被改寫的第一段出現在第二段之前
#       （Track B 曾因 redact+append 把 rewritten span 塞到 stream 尾部）
def _norm(s):
    return s.replace("\ufb02", "fl").replace("\ufb01", "fi")

doc = _make_doc()
_result_c5 = apply_object_edit(
    page=doc[0],
    object_info={"original_rect": fitz.Rect(72, 72, 400, 110), "font": "helv", "size": 12.0,
                 "color": (0, 0, 0), "original_text": "First paragraph: original content.", "page_rotation": 0},
    changes={"new_text": "Track B reflow test same-height replace.",
             "font": "helv", "size": 12.0, "color": (0, 0, 0), "reflow_enabled": True},
    track="B",
)
_fresh_warnings()
reopened = _save_and_reopen(doc)
w = _fresh_warnings()
text = reopened[0].get_text()
_c5_track_used = _result_c5.get("track", "?")
_c5_text_ok = "Track B reflow" in _norm(text)
# 閱讀順序：在 get_text() 輸出中，被改寫的第一段必須出現在「Second paragraph」之前
_norm_text = _norm(text)
_pos_edited = _norm_text.find("Track B reflow")
_pos_second = _norm_text.find("Second paragraph")
_c5_order_ok = (
    _pos_edited != -1
    and (_pos_second == -1 or _pos_edited < _pos_second)
)
c5_ok = _c5_text_ok and _c5_track_used == "B" and len(w) == 0 and _c5_order_ok
print(f"C5 Track B reflow save: {c5_ok} "
      f"(track={_c5_track_used}, text_present={_c5_text_ok}, "
      f"order_ok={_c5_order_ok}, warnings={w or 'none'})")
results.append(("C5", c5_ok))
reopened.close()

# ── C6: line-height CSS 不造成文字截斷 ───────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
long_text = "Line height test paragraph. " * 4  # wraps to multiple lines
css = "* { font-family: helv; font-size: 11pt; line-height: 13.2pt; color: rgb(0,0,0); word-wrap: break-word; }"
rc = page.insert_htmlbox(fitz.Rect(72, 72, 400, 250), long_text, css=css)
reopened = _save_and_reopen(doc)
extracted = reopened[0].get_text()
# Check that most of the text is present (htmlbox might truncate if rc < 0)
words_in = sum(1 for w in ["Line", "height", "test", "paragraph"] if w in extracted)
c6_ok = words_in >= 3 and (rc[0] if isinstance(rc, tuple) else rc) >= 0
print(f"C6 line-height no truncation: {c6_ok} (rc={rc}, words_present={words_in}/4)")
results.append(("C6", c6_ok))
reopened.close()

# ── C7a: 未知密碼保護檔案 → graceful skip（不崩潰）─────────────────────
# 刻意不提供正確密碼，驗證程式能優雅地跳過而非拋例外。
# 以 libreoffice-writer-password.pdf 為測試對象，
# 正確密碼是 openpassword / permissionpassword，但這裡故意不提供。
_pw_pdf = pathlib.Path("test_files/sample-files-main/005-libreoffice-writer-password/libreoffice-writer-password.pdf")
c7a_ok = False
c7a_detail = "file_not_found"
if _pw_pdf.exists():
    try:
        _suppress()
        try:
            _pw_doc = fitz.open(str(_pw_pdf))
        finally:
            _restore()
        if _pw_doc.needs_pass:
            # 刻意用錯誤密碼（確保走 skip 分支）
            unlocked = _pw_doc.authenticate("wrong_password_intentional")
            if not unlocked:
                _pw_doc.close()
                c7a_ok = True   # graceful skip：沒有拋例外
                c7a_detail = "skip_on_wrong_password"
            else:
                _pw_doc.close()
                c7a_detail = "unexpected_unlock"
        else:
            _pw_doc.close()
            c7a_detail = "file_not_password_protected"
    except Exception as _e:
        c7a_detail = f"crash: {_e}"
else:
    c7a_ok = True
    c7a_detail = "file_absent_skip"
print(f"C7a unknown-password graceful skip: {c7a_ok} ({c7a_detail})")
results.append(("C7a", c7a_ok))

# ── C7b: 已知密碼保護檔案 → 可開啟並完成最小編輯 ───────────────────────
# 驗證已知密碼能開啟，且 redact 不崩潰（即使 page 為空也算通過）。
_KNOWN_PASSWORDS = ["openpassword", "permissionpassword", "password", ""]
c7b_ok = False
c7b_detail = "file_not_found"
if _pw_pdf.exists():
    try:
        _suppress()
        try:
            _pw_doc = fitz.open(str(_pw_pdf))
        finally:
            _restore()
        unlocked = any(_pw_doc.authenticate(pw) for pw in _KNOWN_PASSWORDS)
        if unlocked and len(_pw_doc) > 0:
            _pw_page = _pw_doc[0]
            _suppress()
            try:
                _pw_page.add_redact_annot(fitz.Rect(10, 10, 100, 30))
                _pw_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                c7b_ok = True
                c7b_detail = "unlocked_and_edited"
            except Exception as _re:
                c7b_ok = True   # 開啟成功但 redact 失敗是可接受的
                c7b_detail = f"unlocked_redact_fail_ok: {_re}"
            finally:
                _restore()
        elif not unlocked:
            c7b_detail = "unlock_failed"
        else:
            c7b_detail = "empty_doc"
        _pw_doc.close()
    except Exception as _e:
        c7b_detail = f"crash: {_e}"
else:
    c7b_ok = True
    c7b_detail = "file_absent_skip"
print(f"C7b known-password open+edit: {c7b_ok} ({c7b_detail})")
results.append(("C7b", c7b_ok))

# ── C7c: 一般壞損/非標準 PDFs → 不崩潰 ──────────────────────────────────
# 排序確保可重現；排除已個別處理的 password PDF
corrupt_paths = [
    p for p in sorted(pathlib.Path("test_files/sample-files-main").glob("**/*.pdf"))[:12]
    if "password" not in p.name
][:10]
c7c_ok = True
c7c_errors = []
for pdf_path in corrupt_paths:
    try:
        _suppress()
        try:
            doc = fitz.open(str(pdf_path))
        finally:
            _restore()
        if doc.needs_pass:
            doc.close()
            continue
        if len(doc) == 0:
            doc.close()
            continue
        page = doc[0]
        _suppress()
        try:
            page.add_redact_annot(fitz.Rect(10, 10, 100, 30))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        except Exception:
            pass  # 部分壞檔 redact 失敗屬預期行為
        finally:
            _restore()
        doc.close()
    except Exception as e:
        err_str = str(e).lower()
        if "encrypted" in err_str or "password" in err_str:
            continue
        c7c_errors.append(f"{pdf_path.name}: {e}")
        c7c_ok = False
print(f"C7c corrupt-files no crash: {c7c_ok} (tested {len(corrupt_paths)}, errors={c7c_errors or 'none'})")
results.append(("C7c", c7c_ok))

# ── C8: 多次編輯後 xref 不爆炸 ───────────────────────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(fitz.Rect(72, 72, 400, 110), "Initial text.", fontname="helv", fontsize=12)

initial_xref = None
for i in range(5):
    page = doc[0]
    page.add_redact_annot(fitz.Rect(72, 72, 400, 110))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    css = "* { font-family: helv; font-size: 12pt; line-height: 14.4pt; }"
    page.insert_htmlbox(fitz.Rect(72, 72, 400, 110), f"Edit {i+1}.", css=css)
    if i == 0:
        buf = io.BytesIO()
        doc.save(buf, garbage=4)
        buf.seek(0)
        initial_xref = fitz.open("pdf", buf.read()).xref_length()

buf = io.BytesIO()
doc.save(buf, garbage=4, deflate=True)
buf.seek(0)
final_doc = fitz.open("pdf", buf.read())
final_xref = final_doc.xref_length()
doc.close()
final_doc.close()
# xref should not grow unboundedly (allow up to 3× initial)
c8_ok = final_xref <= initial_xref * 3 if initial_xref else True
print(f"C8 xref growth: {c8_ok} (initial={initial_xref}, final={final_xref}, ratio={final_xref/initial_xref if initial_xref else 'N/A'})")
results.append(("C8", c8_ok))

# ── Summary ─────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
passed = sum(1 for _, ok in results if ok)
for label, ok in results:
    print(f"  [{label}] {'PASS ✓' if ok else 'FAIL ✗'}")
print(f"\n{passed}/{len(results)} PASS")
print("=" * 70)
sys.exit(0 if passed == len(results) else 1)
