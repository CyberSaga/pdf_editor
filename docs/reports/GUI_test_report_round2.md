# GUI Test Report — Round 2
**Branch**: `codex/text-editing-function-by-iterating-repeatedly`
**Commits tested**: `4c671b7` + `29a1395` (latest)
**PDF under test**: `test_files/2.pdf`
**Date**: 2026-03-27
**Tester**: Claude (automated GUI observation)

---

## Summary Table

| Fix | Description | Result | Notes |
|-----|-------------|--------|-------|
| Fix 1 | Ghost text on no-edit close | ✅ PASS | No ghost text, no spurious "已修改" |
| Fix 2 | Undo/Redo | ⚠️ PARTIAL | Toolbar 復原 works; Ctrl+Z keyboard shortcut broken |
| Fix 3 | Cross-page drag page_idx | ⚠️ AMBIGUOUS | Editor crosses boundary visually; commit destination uncertain |
| Fix 4 | Sub-pixel drag threshold | ✅ PASS | 3 px diagonal drag triggers editor move |
| Fix S-1 | Cancel button discards edits | ✅ PASS | 取消 button reliably discards |
| Fix S-1b | Escape key discards edits | ❌ FAIL | Escape does NOT close editor when text is focused |
| Fix S-2 | Ctrl+S in editor | ⚠️ INCONCLUSIVE | Not fully testable (no clear "dirty + editor open" scenario hit) |

---

## Detailed Results

### Fix 1 — Ghost Text Prevention ✅ PASS

**Test**: Double-click text block → do not type anything → click elsewhere to close.

**Expected**: No "已修改" asterisk, block count unchanged.

**Observed**: Tab showed `2.pdf` (no asterisk) after close. Text block content and position unchanged. The `_normalize_for_edit_compare` helper correctly detects no real change and skips the redact+reinsert pipeline.

**Verdict**: ✅ Confirmed working.

---

### Fix 4 — Sub-pixel Drag Threshold ✅ PASS

**Test**: Open editor on text block → drag ~3 px diagonally → observe if editor moves.

**Expected**: Editor should move (new threshold `dx²+dy² > 9` → 3 px triggers drag).

**Observed**: A ~3 px diagonal drag caused the editor widget to visibly reposition. Old threshold (`> 25`, i.e. 5 px) would have swallowed this.

**Verdict**: ✅ Confirmed working.

---

### Fix S-1 — Cancel Button Discards Edits ✅ PASS

**Test**: Open editor → type "TEST " → click "取消" (Cancel) button in right panel.

**Expected**: Editor closes; text reverts to original; no "已修改" asterisk.

**Observed**: Clicking "取消" closed the editor, restored original text ("剖面設定，匯入AutoCAD面視圖"), and tab remained `2.pdf` (no asterisk). Confirmed across multiple test runs.

**Verdict**: ✅ Confirmed working.

---

### Fix S-1b — Escape Key Discards Edits ❌ FAIL

**Test**: Open editor → type "TEST " → press Escape (×2).

**Expected**: Editor closes; text reverts to original.

**Observed**: Pressing Escape once or twice did NOT close the editor. The QTextEdit appears to consume the Escape keypress before the `QShortcut(Qt.Key_Escape, editor)` handler fires. The editor remained open with "TEST" visible.

**Root cause hypothesis**: When the QTextEdit widget has active text-cursor focus, Qt delivers key events to the widget first. The shortcut on the parent editor widget is not receiving the event. The `_editor_key_press` override or the shortcut context may need adjusting.

**Verdict**: ❌ Bug — Escape does not close/discard editor when text is focused.

**Workaround**: Use the "取消" button (which works correctly).

---

### Fix 2 — Undo/Redo ⚠️ PARTIAL

**Test A — Toolbar undo after commit**:
Open editor → type "TEST " → click away (commit) → click "復原" toolbar button.
**Result**: ✅ Text reverted to original. Tab asterisk removed after second undo (cross-page drag also undone).

**Test B — Ctrl+Z keyboard shortcut (document-level, editor closed)**:
After committing an edit, press Ctrl+Z repeatedly.
**Result**: ❌ No effect. "TEST" remained visible; asterisk persisted.

**Test C — Ctrl+Z keyboard shortcut (in-editor local undo)**:
While editor open with "TEST " typed, press Ctrl+Z.
**Result**: ❌ No effect. "TEST" remained in editor.

**Analysis**:
- The `_handle_editor_undo` function added in `29a1395` is supposed to intercept Ctrl+Z via the `_EditorShortcutForwarder` event filter. However, Ctrl+Z is not reaching this handler — likely because:
  1. QTextEdit's built-in Ctrl+Z handler intercepts it before the event filter, OR
  2. The event filter is installed but `document().isUndoAvailable()` returns False (editor's undo stack may not track the typed characters correctly after editor initialization).
- For document-level undo (editor closed), the `WidgetWithChildrenShortcut` context for Ctrl+Z means focus must be precisely on the PDFView widget. After editor closes, focus may revert to the PDFView, but the shortcut still doesn't fire — suggesting the shortcut is not connected to the document undo action in the first place.

**Verdict**: ⚠️ Partial — toolbar button works; keyboard shortcut broken at both in-editor and document levels.

---

### Fix 3 — Cross-page Drag ⚠️ AMBIGUOUS

**Test**: Open editor on page 4 subtitle → drag from y≈270 (page 4) to y≈640 (visually in page 5) → click away to commit.

**Expected**: Text block committed to page 5's coordinate space; page 4 no longer shows subtitle at original position.

**Observed**:
1. Editor widget DID visually move into page 5 territory (confirmed in screenshot).
2. After committing: `2.pdf *` asterisk appeared — something was committed.
3. Scrolling back to page 4: subtitle text appeared at approximately original position.
4. Scrolling to page 5: subtitle text NOT visible on page 5.
5. Two "復原" clicks were needed to clear the asterisk — suggesting TWO commits happened (the cross-page position change was committed but did not place the text on page 5 visibly).

**Analysis**:
The `_resolve_editor_page_idx_for_drag` fix (Fix 1c) correctly updates the page index dynamically during drag. However, Fix 3b ("Position-only drag silent rollback") is **not yet implemented** (P2, Batch 3). When only position changes (no text change), the `model/pdf_model.py` verification pipeline still may silently rollback or clamp the result. The committed change may have placed the text within page 4's bounds at an extreme Y coordinate (clamped by `_clamp_editor_pos_to_page`), which rendered in the same region as the original position.

**Verdict**: ⚠️ Ambiguous — cross-page drag is visually functional (editor crosses boundary), but the position commit to the destination page is not confirmed. Fix 3b (P2) needs to be implemented to resolve position-only rollback.

---

## Issues Found (Not in Original Plan)

### New Issue: Escape key non-functional when editor has text focus
- **Severity**: Medium
- **Reproduction**: Open text editor → type any character → press Escape
- **Expected**: Editor closes, changes discarded
- **Actual**: Editor stays open; Escape consumed by QTextEdit
- **Recommendation**: Install event filter on QTextEdit's keyPressEvent to intercept Escape before it reaches the default QTextEdit handler, or use `installEventFilter` with `eventFilter` checking for `Qt.Key_Escape`.

---

## Regression Check

| Previously confirmed | Status |
|---------------------|--------|
| Fix 1 ghost text | ✅ Still passing |
| Fix 4 sub-pixel threshold | ✅ Still passing |
| Fix S-1 Cancel button | ✅ Still passing |
| No crash during drag/edit | ✅ No crashes observed |

---

## Outstanding Items (Not Tested This Round)

- **Fix S-2 (Ctrl+S in editor)**: Would need to make a committed edit, re-open editor, then press Ctrl+S. The `_EditorShortcutForwarder` forwards Ctrl+S to the main window — unclear if a Save dialog appears. Not conclusively tested.
- **Fix 2a (zoom debounce)**: Requires zooming then immediately double-clicking — not tested.
- **Fix 2c (multi-color paragraph)**: Requires a PDF with multi-color text runs — not tested with `2.pdf`.

---

## Acrobat Comparison Assessment

| UX Criterion | Acrobat | This build |
|-------------|---------|-----------|
| No ghost text on tap-away | ✅ | ✅ Fixed |
| Sub-pixel drag detection | ✅ | ✅ Fixed |
| Cancel discards edits | ✅ | ✅ Fixed |
| Escape discards edits | ✅ | ❌ Broken |
| Ctrl+Z undoes in-editor typing | ✅ | ❌ Broken |
| Ctrl+Z undoes committed edit | ✅ | ❌ Broken (toolbar works) |
| Cross-page text drag | ✅ | ⚠️ Partial |

**Overall**: The build is meaningfully closer to Acrobat-level UX — the most disruptive bugs (ghost text, drag threshold) are resolved. The remaining gaps are primarily in keyboard shortcuts (Escape, Ctrl+Z) which are important for power-user workflows.
