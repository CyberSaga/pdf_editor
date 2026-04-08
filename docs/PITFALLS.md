# PITFALLS.md — Known Failure Modes

> Add entries here whenever a non-obvious bug is fixed. Format:
> `## <short title>` / Area / Symptom / Cause / Fix / File

---

## PyMuPDF font sizes are floats, not ints

**Area:** `model/pdf_model.py`, `view/text_editing.py`  
**Symptom:** Fractional font sizes (e.g. 9.5pt) silently become 9pt after editing.  
**Cause:** `span["size"]` returns `float`; coercing to `int` truncates.  
**Fix:** Use `float` for all size fields in `EditTextRequest` and `MoveTextRequest`.  
**File:** `view/text_editing.py`

---

## TEXT_PRESERVE_LIGATURES breaks push-down re-insert

**Area:** `model/pdf_model.py` — `_push_down_overlapping_text`  
**Symptom:** Text containing ligatures (ﬁ, ﬀ) disappears after push-down; e.g. "misfits" → "mits".  
**Cause:** `get_text("dict", flags=TEXT_PRESERVE_LIGATURES)` returns ligature characters; `insert_text(fontname="helv")` silently drops glyphs it cannot encode.  
**Fix:** Use only `TEXT_PRESERVE_WHITESPACE` when fetching text for re-insertion; PyMuPDF expands ligatures to plain ASCII.  
**File:** `model/pdf_model.py`

---

## push-down insert_text(helv) drops non-Latin Unicode (€, emoji)

**Area:** `model/pdf_model.py` — `_push_down_overlapping_text`  
**Symptom:** Pushed-down spans containing `€` or emoji are silently replaced (e.g. `€` → `·`).  
**Cause:** Helvetica Type1 has no glyphs for U+20AC and above; PyMuPDF substitutes silently.  
**Fix:** Use `page.insert_htmlbox(rect, html, css=css)` for re-insertion; fall back to `insert_text(helv)` only on failure.  
**File:** `model/pdf_model.py`

---

## Vertical text double-redact erases adjacent horizontal text

**Area:** `model/pdf_model.py` — `edit_text` vertical branch  
**Symptom:** After editing a vertical text block, the first character of a nearby horizontal line disappears.  
**Cause:** The original flow ran Strategy A (`insert_htmlbox`) on the main page to measure height, then cleared the full `insert_rect` with `apply_redactions()`. If `insert_rect` spanned x≈0 it overlapped horizontal content.  
**Fix:** Measure `shrunk_rect` on a temp page; apply only one `insert_htmlbox(shrunk_rect)` to the main page. No second redact on the main page.  
**File:** `model/pdf_model.py`

---

## Continuous mode `change_scale` only redraws one page

**Area:** `controller/pdf_controller.py` — `change_scale`  
**Symptom:** After zooming in continuous mode, only the current page re-renders; others stay at old scale.  
**Cause:** `change_scale` called `display_page(page_idx, qpix)` instead of rebuilding the full scene.  
**Fix:** Set `self.view.scale = scale` first; then call `_rebuild_continuous_scene(page_idx)` in continuous mode.  
**File:** `controller/pdf_controller.py`

---

## Zoom combo always shows 100%

**Area:** `controller/pdf_controller.py`, `view/pdf_view.py`  
**Symptom:** Scale selector and status bar always read 100% regardless of actual zoom.  
**Cause:** `view.scale` was never updated, so `_update_page_counter()` read the stale default.  
**Fix:** Set `view.scale = scale` before calling `_update_page_counter()` and `_update_status_bar()`.  
**File:** `controller/pdf_controller.py`

---

## QToolBar overflow hides Undo/Redo buttons

**Area:** `view/pdf_view.py` — right toolbar  
**Symptom:** Redo button hidden behind `»` overflow; increasing right margin does not help.  
**Cause:** `setMaximumWidth(320)` on the right block too small; stretch widget squeezes the toolbar to minimum.  
**Fix:** `setMaximumWidth(420)`; remove stretch widget from `right_layout`; add `toolbar_right.setMinimumWidth(100)`.  
**File:** `view/pdf_view.py`

---

## PDFModel has no `.open()` method — it is `.open_pdf()`

**Area:** test scripts  
**Symptom:** `AttributeError: 'PDFModel' object has no attribute 'open'`  
**Cause:** Incorrect method name used in tests.  
**Fix:** Call `model.open_pdf(filepath)`.  
**File:** Any test importing `PDFModel`

---

## focusOutEvent recursive call in text editor finalization

**Area:** `view/pdf_view.py` — `_finalize_text_edit`  
**Symptom:** `_finalize_text_edit` re-enters itself; unexpected double-finalize behavior.  
**Cause:** `self.text_editor` was set to `None` after `removeItem()`, so `focusOutEvent` triggered during removal could re-enter.  
**Fix:** Set `self.text_editor = None` before calling `removeItem(proxy_to_remove)`.  
**File:** `view/pdf_view.py`

---

## Drag clamp produces invalid rect when target is fully off-page

**Area:** `model/pdf_model.py` / `view/pdf_view.py` — clamp helpers  
**Symptom:** `insert_htmlbox` fails after clamping because `y0 > y1` or `x0 > x1`.  
**Cause:** Clamp logic did not guard against producing an inverted or zero-area rectangle.  
**Fix:** After clamping, check `x0 < x1` and `y0 < y1`; skip or reject if the rect is degenerate.  
**File:** `view/pdf_view.py`, `model/pdf_model.py`

---

## Merge list reorder lost on next add/remove

**Area:** `view/pdf_view.py`, `model/merge_session.py`  
**Symptom:** After drag-reordering in the Merge PDF dialog, adding or removing a file resets the order.  
**Cause:** `_refresh_file_list()` rebuilt from `MergeSessionModel.entries` which was never updated after drag.  
**Fix:** On Qt `rowsMoved`, sync QListWidget order back to `MergeSessionModel.entries` using stable `entry_id` keys.  
**File:** `view/pdf_view.py`, `model/merge_session.py`

---

## Test normalization misses Unicode ligatures

**Area:** test scripts  
**Symptom:** Text preservation test fails: `insert_htmlbox` produces `ﬁ` but comparison target has `fi`.  
**Cause:** Test `_norm()` only stripped whitespace; did not expand ligature characters.  
**Fix:** Add `_LIGATURE_MAP` (`\ufb01`→`fi`, `\ufb02`→`fl`, etc.) and apply before comparison.  
**File:** `test_scripts/test_drag_move.py`

---

## Controller activation must be deferred to `activate()`

**Area:** `controller/pdf_controller.py`  
**Symptom:** Signal wiring or print subsystem setup runs before the view is ready, causing startup errors.  
**Cause:** Init code that belongs in `activate()` was placed in `__init__()`.  
**Fix:** Keep `__init__()` cheap (store refs only); put all view-signal wiring and startup sync in `PDFController.activate()`.  
**File:** `controller/pdf_controller.py`

---

## Text index must be rebuilt on-demand after structural ops

**Area:** `model/pdf_model.py`, `model/text_block.py`  
**Symptom:** Search or edit on a page after insert/delete returns stale or missing results.  
**Cause:** Structural ops mark cached pages `"stale"` rather than eagerly rebuilding, so callers that skip `ensure_page_index_built()` read stale data.  
**Fix:** Always call `model.ensure_page_index_built(page_num)` before any edit or search path.  
**File:** `model/pdf_model.py`, `model/text_block.py`

---

## Edit request dataclasses must stay Qt-free

**Area:** `model/edit_requests.py`, `controller/pdf_controller.py`, `view/text_editing.py`  
**Symptom:** Importing `EditTextCommand` or other model-layer helpers pulls in Qt/view dependencies and risks circular imports.  
**Cause:** If `EditTextRequest` or `MoveTextRequest` are defined under `view/`, the command layer must import upward across the architecture boundary to use the typed payloads.  
**Fix:** Keep shared request dataclasses in `model/edit_requests.py`, re-export them from `view/text_editing.py`, and avoid adding any Qt imports to the request module.  
**File:** `model/edit_requests.py`
