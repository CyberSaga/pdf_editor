# PDF Text Editing UX — Prioritized Fix Plan

## Context

Branch `codex/text-editing-function-by-iterating-repeatedly` implements redact+reinsert text editing for a PDF editor. Three independent reviews (my code review, static analysis `to_fix(static).md`, GUI testing `to_fix(GUI).md`) found 16 bugs. This plan deduplicates, triages, and orders fixes into 4 batches.

**Goal**: Acrobat-level text editing — no ghost text, no silent failures, no position drift, stable undo, correct style inheritance.

---

## Triage Summary

| Priority | Count | Description |
|----------|-------|-------------|
| **P0** | 3 fixes | Core UX broken — ghost text, coordinate errors |
| **P1** | 3 fixes | Important UX — zoom editor, Ctrl+Z, multi-color |
| **P2** | 6 fixes | Edge cases & polish |
| **P3** | 2 fixes | Low priority cosmetic/performance |
| **Skip** | 2 items | Not worth fixing now |

---

## Batch 1 — P0 (Must Fix)

### Fix 1a: G1 — No-edit finalize creates ghost text [CRITICAL]

**File**: `view/pdf_view.py` ~line 3442-3444

**Problem**: Clicking a text block then clicking away (no edits) triggers full redact+reinsert. `text_changed` is `True` because `editor.toPlainText()` normalizes whitespace/ligatures differently from PDF extraction.

**Fix**:
1. Add `_normalize_for_edit_compare(text)` helper at top of `pdf_view.py` — expand ligatures (`_LIGATURE_MAP` from `model/text_block.py`), collapse whitespace, strip, lowercase
2. Replace line 3444:
   ```python
   # Before
   text_changed = new_text != original_text_prop
   # After
   text_changed = _normalize_for_edit_compare(new_text) != _normalize_for_edit_compare(original_text_prop or "")
   ```

### Fix 1b: #1/#14 — Annotation coordinates use wrong scale [HIGH]

**File**: `view/pdf_view.py` lines 3203-3204

**Problem**: Uses `self.scale` (expected zoom) instead of `self._render_scale` (actual rendered). All other conversions in the file already use `_render_scale` correctly — this is the only outlier.

**Fix**: 2-line change — replace `self.scale` with `rs` variable:
```python
rs = self._render_scale if self._render_scale > 0 else 1.0
fitz_rect = fitz.Rect(rect.x() / rs, (rect.y() - y0) / rs,
                      rect.right() / rs, (rect.bottom() - y0) / rs)
```

### Fix 1c: #6/#10/#15/#17 — Cross-page drag page_idx fixed [HIGH]

**File**: `view/pdf_view.py` ~lines 2779-2787, 3067-3094

**Problem**: `_editing_page_idx` set once at drag start, never updated. Cross-page drag uses wrong page origin for Y-offset.

**Fix**:
1. In drag-active block (~line 2784): dynamically compute `page_idx = self._scene_y_to_page_index(raw_y)` and update `self._editing_page_idx`
2. In `_clamp_editor_pos_to_page`: accept `page_idx=None` for auto-detection

---

## Batch 2 — P1 (Should Fix)

### Fix 2a: #8 — Zoom debounce: editor with stale scale [HIGH]

**File**: `view/pdf_view.py` ~line 3235

**Problem**: If user double-clicks during zoom debounce (~200ms window), editor position computed with stale `_render_scale`.

**Fix**: At top of `_create_text_editor`, if debounce active, use `self.scale` as authoritative:
```python
if hasattr(self, '_zoom_debounce_timer') and self._zoom_debounce_timer.isActive():
    rs = max(0.1, float(self.scale))
else:
    rs = self._render_scale if self._render_scale > 0 else 1.0
```

### Fix 2b: G3 — Ctrl+Z not working [MEDIUM]

**File**: `view/pdf_view.py` lines 1511-1513, 1619-1630

**Problem**: Shortcut uses `WidgetWithChildrenShortcut` context. After editor closes, focus may not return to PDFView, making shortcut unreachable.

**Fix**:
1. Line 1511: `QKeySequence("Ctrl+Z")` → `QKeySequence.StandardKey.Undo`
2. Line 1513: `QKeySequence("Ctrl+Y")` → `QKeySequence.StandardKey.Redo`
3. Change undo/redo shortcut context to `Qt.ShortcutContext.WindowShortcut`

### Fix 2c: #5/#11 — Multi-color paragraph loses per-run colors [MEDIUM]

**Files**: `model/text_block.py` ~line 132+, `model/pdf_model.py` edit pipeline

**Problem**: `EditableParagraph` stores only dominant color via `most_common(1)`. All runs get same color after edit.

**Fix**:
1. Add `run_colors: list[tuple] = field(default_factory=list)` to `EditableParagraph`
2. Populate during construction: `run_colors=[tuple(r.color) for r in block_runs]`
3. In edit pipeline, use per-run colors for position-only moves; fall back to dominant color when text changes

**Note**: This is the highest-risk fix. Test with diverse PDFs.

---

## Batch 3 — P2 (Nice to Fix)

### Fix 3a: #3 — Double-finalize race [MEDIUM]
- Replace two `QTimer.singleShot(40)` calls with single reusable `QTimer` that auto-cancels on restart
- `view/pdf_view.py` ~lines 2122-2159

### Fix 3b: #7 — Position-only drag silent rollback [MEDIUM]
- Skip strict text-content verification when `original_text == new_text` and only position changed
- `model/pdf_model.py` verification pipeline

### Fix 3c: #9/#12 — Protected span failure: no user feedback [MEDIUM]
- `_validate_protected_spans` returns list of missing span IDs instead of bool
- Surface specific failures in status bar
- `model/pdf_model.py` + `controller/pdf_controller.py`

### Fix 3d: #16 — Fallback size unit confusion [TRIVIAL]
- `view/pdf_view.py` line 3186-3187: `100 / rs` → `100.0`, `30 / rs` → `30.0`

### Fix 3e: #19 — Viewport dual-timer jump [MEDIUM]
- `controller/pdf_controller.py` lines 1545-1546
- Replace dual `QTimer.singleShot(0) + QTimer.singleShot(180)` with conditional retry helper

### Fix 3f: #2/#18 — Sub-pixel threshold [TRIVIAL]
- `view/pdf_view.py` lines 3451-3452: change `0.5` → `0.1`

---

## Batch 4 — P3 (Low Priority)

### Fix 4a: G4 — Page counter not updating on scroll [LOW]
- Investigate `_on_scroll_changed` → `_update_page_counter()` chain
- `view/pdf_view.py`

### Fix 4b: #13 — Debug log performance [LOW]
- Convert f-string `logger.debug(f"...")` to %-style `logger.debug("...", arg)` in hot paths

---

## Skip (Not Worth Fixing Now)

1. **#4 (static review) — Viewport restore not found**: Static analysis couldn't locate the dual-timer pattern, but GUI review confirmed it exists as #19. Already covered by Fix 3e.
2. **Track C code** — Explicitly out of scope per project non-goals.

---

## Implementation Order & Dependencies

```
Batch 1 (P0): Fix 1a → 1b → 1c  (all in pdf_view.py, do sequentially to avoid merge conflicts)
Batch 2 (P1): Fix 2b → 2a → 2c  (2b is trivial, 2a small, 2c is largest)
Batch 3 (P2): Fix 3d → 3f → 3a → 3b → 3c → 3e  (trivials first, then medium)
Batch 4 (P3): Fix 4a → 4b  (independent)
```

---

## Verification Plan

After each batch:

1. **Launch GUI**: `python3 main.py test_files/TIA-942-B-2017\ Rev\ Full.pdf`
2. **P0 tests**:
   - Click text block → click away without editing → verify blocks/spans count unchanged
   - Zoom to 150% → draw highlight → verify it covers correct text
   - Continuous mode → drag text from page 1 to page 2 → verify correct landing
3. **P1 tests**:
   - Zoom with wheel → immediately double-click text → verify editor aligns
   - Cmd+Z (Mac) / Ctrl+Z (Win) after edit → verify undo works
   - Edit multi-color paragraph → verify per-run colors preserved
4. **P2/P3 tests**: Per-fix as described in each section
5. **Run existing test suite**: `python3 test_scripts/test_track_ab_5scenarios.py` — all 17 scenarios must still pass

---

## Key Files

| File | Fixes Touching It |
|------|-------------------|
| `view/pdf_view.py` | 1a, 1b, 1c, 2a, 2b, 3a, 3d, 3f, 4a |
| `model/pdf_model.py` | 3b, 3c, 4b |
| `model/text_block.py` | 2c (dataclass change) |
| `controller/pdf_controller.py` | 3c, 3e |
