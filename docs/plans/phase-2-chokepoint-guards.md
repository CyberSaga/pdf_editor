# Phase 2 — Chokepoint Guards: Implementation Plan

**Status:** Ready to implement (Sonnet 4.6 deep-plan pass, 2026-06-10; all line numbers
verified against actual source). Six items, one pattern: guard once at the chokepoint.

---

## 2.1 Central render-scale clamp (`model/tools/manager.py`)

- `render_page_pixmap` builds `matrix = fitz.Matrix(scale, scale)` at line 71 with raw
  `scale`. `_safe_render_scale` lives at `model/pdf_model.py:100–110`; never called here.
- **Circular-import constraint:** manager.py imports pdf_model only under TYPE_CHECKING.
  Use a LOCAL import inside the function (same pattern as `ocr_tool.py:262–263`):

```python
page = self._model.doc[page_num - 1]
needs_overlay = any(ext.needs_page_overlay(session_id, page_num, purpose) for ext in self._extensions)
# Local import avoids a module-load cycle between pdf_model and the tools package.
from model.pdf_model import _safe_render_scale  # noqa: PLC0415
scale = _safe_render_scale(page, scale)
matrix = fitz.Matrix(scale, scale)
```

- **Existing red-light test:** `test_scripts/test_security_pdf_resource_guards.py::test_render_page_pixmap_clamps_oversized_scale`
  (lines 157–193) is `@pytest.mark.xfail(strict=True)`. After the fix, REMOVE the xfail
  decorator (strict xfail would otherwise turn XPASS into a failure). The test body is
  correct as-is.
- `_render_scale_for_quality` (controller:784–788): no change needed.
- Clamp on the ORIGINAL page is correct for the overlay branch too (tmp page has the same rect).
- OCR pre-clamps before calling; double-clamp is idempotent/harmless.

## 2.2 Shared zoom-limit constants (`view/pdf_view.py`)

Module-level constants (near `logger = logging.getLogger(__name__)`):

```python
# Zoom limits shared by all three zoom entry points (wheel, pinch, combo).
_MAX_VIEW_ZOOM = 4.0   # 400%
_MIN_VIEW_ZOOM = 0.1   # 10%
```

- Wheel (line 2677, currently unbounded `self.scale *= factor`):
  `self.scale = max(_MIN_VIEW_ZOOM, min(_MAX_VIEW_ZOOM, self.scale * factor))`
- `_zoom_relative` / pinch (line 3601): replace `max(0.1, min(4.0, new_scale))` with constants.
- Zoom combo (line 1351): replace `if 10 <= pct <= 400:` with
  `scale_val = pct / 100.0; if _MIN_VIEW_ZOOM <= scale_val <= _MAX_VIEW_ZOOM: emit(..., scale_val)`.

## 2.3 Foreign-document open guard (`model/pdf_model.py`, `model/headless_merge.py`)

`_guard_before_open` (pdf_model.py:94–97) does ONLY the size check. Add after it:

```python
def _guard_foreign_doc(path: Path) -> fitz.Document:
    """Open a foreign PDF with all resource guards applied.

    Size limit (_MAX_PDF_BYTES), open, page limit (_MAX_PAGES), encryption.
    Returns the opened document; caller closes it.
    """
    _guard_before_open(path)
    doc = fitz.open(str(path))
    if doc.needs_pass:
        doc.close()
        raise ValueError(f"Foreign PDF is encrypted and cannot be opened without a password: {path}")
    if doc.page_count > _MAX_PAGES:
        doc.close()
        raise ValueError(f"Foreign PDF exceeds page limit ({_MAX_PAGES} pages): {path}")
    return doc
```

`insert_pages_from_file` (line 1383 `source_doc = fitz.open(...)`):
- Replace with `source_doc = _guard_foreign_doc(source_path)`.
- Post-merge invariant BEFORE inserting:
  `if len(self.doc) + len(actual_source_pages) > _MAX_PAGES: source_doc.close(); raise ValueError(...)`
- Replace the per-page insert loop (1409–1419) with contiguous-run batching:
  group sorted/deduped `actual_source_pages` into consecutive runs; one
  `insert_pdf(source_doc, from_page=from_pg-1, to_page=to_pg-1, start_at=insert_at+offset)`
  per run; `inserted_positions = list(range(insert_at + 1, insert_at + len(actual_source_pages) + 1))`.
- Semantics preserved: list is already `sorted(set(...))` (line 1405); rotation carries
  automatically; empty selection → no-op.

`headless_merge.py` (line 24): `from model.pdf_model import _guard_foreign_doc` at top
(no circular dep — pdf_model does not import headless_merge); `src = _guard_foreign_doc(input_path)`.

## 2.4 Page-number validation helper (`model/tools/annotation_tool.py`)

Add to `AnnotationTool`:

```python
def _require_page(self, page_num: int) -> fitz.Page:
    """Return the fitz.Page for *page_num* (1-based) or raise ValueError.

    Guards both the no-doc case and out-of-range page numbers, preventing
    page 0 from silently resolving to doc[-1] (last page).
    """
    if not self._model.doc:
        raise ValueError("沒有開啟的 PDF 文件")
    if page_num < 1 or page_num > len(self._model.doc):
        raise ValueError(f"無效的頁碼: {page_num}")
    return self._model.doc[page_num - 1]
```

Use in `add_highlight` (line 31), `add_rect` (line 47), and replace the inline guard in
`add_annotation` (lines 68–70). Note message format change: 「無效的頁碼: N」.

## 2.5 Watermark sanitization chokepoint (`model/tools/watermark_tool.py`)

Confirmed NaN hazards: `min/max` are argument-order sensitive with NaN
(`min(nan, x) → nan`, `min(x, nan) → x`); json.loads accepts Infinity/NaN.

- `import math` at top; add helper:

```python
def _finite(v: float, lo: float, hi: float, default: float) -> float:
    """Return v clamped to [lo, hi] if v is finite, else default."""
    if not math.isfinite(v):
        return default
    return max(lo, min(hi, v))
```

- `_coerce_wm` rewrite: angle = `(raw % 360) if math.isfinite(raw) else 0.0`;
  `font_size = _finite(..., 1.0, 1000.0, 48.0)`; `opacity = _finite(..., 0.0, 1.0, 0.5)`;
  color must have `len == 3` else default `(0.7, 0.7, 0.7)`, each component
  `_finite(float(c), 0.0, 1.0, 0.7)`; optional keys: `offset_x/offset_y =
  _finite(..., -10000.0, 10000.0, 0.0)`, `line_spacing = _finite(..., 0.8, 3.0, 1.3)`.
  Color is now ALWAYS present in result (schema-compatible: watermark_rendering.py:33
  uses `.get("color", default)`).
- `add_watermark` (113–147): build candidate dict (same keys), pass through `_coerce_wm`;
  `None` → `raise ValueError("無效的浮水印參數（強制校驗失敗）")`; re-filter pages
  against current page count after coercion; store coerced dict. Public signature unchanged.
- `update_watermark` (166–208): merge stored dict + non-None overrides into candidate,
  `_coerce_wm`, `None` → return False; re-filter pages; replace stored entry. Signature unchanged.
- `_load_watermarks_from_doc` (~210) already routes through `_coerce_wm` — inherits hardening.

## 2.6 Single-instance argv filter (`utils/single_instance.py:103–114`)

Replace `_forwarded_argv_is_acceptable` body: for each token, skip tokens starting with
`-` (future-proof; none forwarded today); otherwise `path = Path(item).resolve()` then
require `path.exists() and path.suffix.lower() == ".pdf"` else return False. Sender
(`_normalize_forwarded_argv`, line 99–100) already resolves; double-resolve is idempotent.

---

## Red-light tests (write FIRST; run to confirm failure before implementing)

- 2.1: existing strict-xfail `test_render_page_pixmap_clamps_oversized_scale` IS the
  red-light evidence; fix flips it green, remove the decorator.
- 2.3 in `test_security_pdf_resource_guards.py`: `test_guard_foreign_doc_rejects_oversize`
  (monkeypatch `_MAX_PDF_BYTES = 0`), `test_guard_foreign_doc_rejects_excess_pages`
  (monkeypatch `_MAX_PAGES = 0`), `test_insert_pages_from_file_rejects_oversize_source`,
  `test_insert_pages_from_file_respects_post_merge_invariant` (base 3 + src 3 pages,
  `_MAX_PAGES = 4`).
- 2.3 in `test_headless_merge.py`: `test_headless_merge_rejects_oversize_input`
  (monkeypatch pdf_model._MAX_PDF_BYTES = 0).
- 2.4 in `test_tool_extensions.py`: `test_add_highlight_rejects_page_zero`,
  `test_add_rect_rejects_page_zero`, `test_add_highlight_rejects_out_of_range`
  (currently page 0 silently annotates last page — assert pytest.raises(ValueError)).
- 2.5 in `test_security_watermark_coercion.py`: `test_coerce_nan_angle_replaced_with_default`,
  `test_coerce_inf_offset_clamped` (expect ±10000.0), `test_coerce_color_with_nan_component_replaced`,
  `test_coerce_color_wrong_length_replaced_with_default`; in `test_tool_extensions.py`:
  `test_add_watermark_nan_angle_sanitized`.
- 2.6 in `test_security_single_instance_isolation.py`:
  `test_forwarded_argv_rejects_relative_non_pdf`, `test_forwarded_argv_rejects_path_traversal`
  (use the file's existing `_run_message` helper; expect `received == []`, `ack == b"0\n"`),
  optional `test_forwarded_argv_accepts_relative_pdf_that_exists` (documents tradeoff).

## Verification

```powershell
python -m pytest test_scripts/test_security_pdf_resource_guards.py test_scripts/test_security_watermark_coercion.py test_scripts/test_security_single_instance_isolation.py test_scripts/test_headless_merge.py test_scripts/test_tool_extensions.py -v --tb=short
python -c "from view import pdf_view; print('pdf_view ok')"
python -m ruff check model/tools/manager.py view/pdf_view.py model/pdf_model.py model/headless_merge.py model/tools/annotation_tool.py model/tools/watermark_tool.py utils/single_instance.py
```

Then full suite gate: `python -m pytest test_scripts -q --tb=line -p no:cacheprovider` → 0 failures.

## Docs (same commit)

- PITFALLS.md: 4 new entries — (1) foreign-doc guards before fitz.open on ALL open paths;
  (2) `doc[-1]` silent wrong-page mutation on page_num=0; (3) Python min/max NaN
  argument-order sensitivity — use math.isfinite, never min/max alone to sanitize;
  (4) IPC argv filter must resolve all tokens, not just absolute.
- ARCHITECTURE.md: document `_guard_foreign_doc` contract (all non-primary opens route
  through it; caller closes) + the resolved-token IPC filter rule.
- TODOS.md: mark Phase 2 done; also mark the pre-existing "F1 follow-up — central
  render-scale clamp gap" item done (search TODOS.md for it).

## Commit

One atomic commit, message per plan (security: Phase 2 chokepoint guards — …; list items
2.1–2.6 and the new tests; Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>).
