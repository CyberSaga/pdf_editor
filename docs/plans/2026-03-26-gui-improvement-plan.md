# GUI Improvement Plan — Based on 2026-03-26 Live Test Results

**Date:** 2026-03-26
**Source:** `GUI_test_report.md` (9-case live Cowork session)
**Branch:** `codex/text-editing-function-by-iterating-repeatedly`
**Cross-ref:** `docs/plans/2026-03-25-text-editing-ux-fix-plan.md` (static analysis plan)

---

## Overview

Live GUI testing confirmed **4 bugs** out of 9 checklist items. This plan provides concrete implementation steps for each confirmed bug, ordered by severity. Two additional usability issues discovered during testing are appended as supplementary fixes.

**Confirmed bugs:**

| ID | Case | Severity | Status vs. Static Plan |
|----|------|----------|------------------------|
| G-1 | No-edit ghost text | P0 Critical | Matches Fix 1a — needs refined approach |
| G-3 | Cross-page drag frozen page_idx | P1 High | Matches Fix 1c — confirmed in live test |
| G-5 | Undo history not populated | P1 High | Matches Fix 2b (shortcut) + NEW finding: finalize bypasses undo stack |
| G-7 | Sub-pixel drag threshold | P2 Medium | Matches Fix 3f — confirmed 5px too high |

**Supplementary (discovered during testing):**

| ID | Issue | Severity |
|----|-------|----------|
| S-1 | Editor non-closure (Escape / click-outside unreliable) | P1 High |
| S-2 | Ctrl+S blocked by open editor focus | P2 Medium |

---

## Fix 1: G-1 — No-Edit Finalize Ghost Text [P0 CRITICAL]

### Problem

`_finalize_text_edit_impl` (L3436–L3544 in `view/pdf_view.py`) unconditionally emits `sig_edit_text` when `text_changed` is `True`. But `text_changed` fires spuriously because `editor.toPlainText()` normalizes whitespace and ligatures differently from the original PDF extraction. Multi-run paragraphs are flattened into a single span, destroying block structure even when the user made zero edits.

### Root Cause (line-level)

```
L3442  new_text = editor.toPlainText()
L3443  original_text_prop = editor.property("original_text")
L3444  text_changed = new_text != original_text_prop
```

The simple `!=` comparison fails because:
1. PDF text extraction preserves ligatures (ﬁ, ﬂ, ﬀ, etc.) while QPlainTextEdit normalizes them.
2. PDF extraction preserves inter-run whitespace boundaries while Qt collapses consecutive spaces.
3. Trailing/leading whitespace differs between extraction and Qt rendering.

### Fix

**File:** `view/pdf_view.py`

**Step 1** — Add a normalization helper near the top of the file (after imports):

```python
import unicodedata

_LIGATURE_EXPAND = {
    '\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl',
    '\ufb03': 'ffi', '\ufb04': 'ffl', '\ufb05': 'st', '\ufb06': 'st',
}

def _normalize_for_edit_compare(text: str) -> str:
    """Normalize text for before/after comparison, ignoring ligature and whitespace differences."""
    if not text:
        return ""
    # Expand known ligatures
    for lig, expanded in _LIGATURE_EXPAND.items():
        text = text.replace(lig, expanded)
    # NFKD decomposition to catch other Unicode normalization differences
    text = unicodedata.normalize('NFKD', text)
    # Collapse all whitespace sequences to single space
    text = ' '.join(text.split())
    return text.strip()
```

**Step 2** — Replace the comparison at L3444:

```python
# Before:
text_changed = new_text != original_text_prop

# After:
text_changed = _normalize_for_edit_compare(new_text) != _normalize_for_edit_compare(original_text_prop or "")
```

**Step 3** — Also add a comprehensive no-change guard at L3523 (before the `sig_edit_text.emit` block):

```python
# If nothing meaningful changed, skip the rewrite entirely
if not text_changed and not position_changed and not font_changed and not size_changed:
    return
```

This guard already exists implicitly in the `if` condition at L3523, but adding an explicit early return makes the intent clearer and prevents future regressions if new change-type flags are added.

### Verification

1. Open any page, double-click a text block, make NO changes, click outside.
2. Assert: "已修改" indicator does NOT appear.
3. Assert: extracted text before and after is byte-identical.
4. Open a multi-run paragraph (e.g., TOC on page 8), repeat — block structure preserved.

---

## Fix 2: G-5 — Undo History Not Populated [P1 HIGH]

### Problem

`_finalize_text_edit_impl` emits `sig_edit_text` → controller `edit_text()` executes the Track B redact+reinsert pipeline. However, the operation is **not** wrapped in an undoable command. `command_manager.push()` is never called for this path, so Ctrl+Z has nothing to undo.

### Root Cause

The signal-slot chain:
```
view.sig_edit_text → controller.edit_text() → model.edit_text_in_page()
```
operates directly on the model without going through `CommandManager.push(EditTextCommand(...))`. The `EditTextCommand` class exists in `model/edit_commands.py` (L52) but is not instantiated for live interactive edits — only for programmatic batch edits.

### Fix

**File:** `controller/pdf_controller.py`

In the `edit_text()` method (connected to `sig_edit_text` at L261), wrap the model call in an `EditTextCommand`:

```python
def edit_text(self, page_num, original_rect, new_text, font, size, color,
              original_text, vsl, new_rect, target_span_id, target_mode):
    # Capture pre-edit state for undo
    pre_snapshot = self.model.snapshot_page(page_num)

    # Execute the edit
    success = self.model.edit_text_in_page(
        page_num, original_rect, new_text, font, size, color,
        original_text, vsl, new_rect, target_span_id, target_mode
    )

    if success:
        # Capture post-edit state
        post_snapshot = self.model.snapshot_page(page_num)
        # Push undoable command
        cmd = SnapshotCommand(
            model=self.model,
            page_num=page_num,
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            description=f"Edit text on page {page_num}"
        )
        self.model.command_manager.push(cmd)

    self._refresh_after_edit(page_num)
```

> **Note:** If `SnapshotCommand` does not support page-level pre/post snapshots yet, a simpler approach is to serialize the page's xref content before and after the edit. The exact implementation depends on the existing `SnapshotCommand` API — review `model/edit_commands.py` L268+ for the current snapshot format.

**Alternative (minimal change):** If the snapshot infrastructure is too heavy, at minimum store the `original_rect + original_text` as undo state and re-execute the inverse operation (redact the new text, reinsert the original) on undo. This is riskier but requires no new infrastructure.

### Verification

1. Edit a text block, finalize.
2. Press Ctrl+Z — edit reverts to original text.
3. Press Ctrl+Y — edit reapplies.
4. Edit, save, Ctrl+Z — verify undo still works after save.

---

## Fix 3: G-3 — Cross-Page Drag Frozen page_idx [P1 HIGH]

### Problem

`_editing_page_idx` is set once at editor creation and never updated during drag. `_clamp_editor_pos_to_page` (L3067) uses this frozen index to hard-clamp the editor to the origin page's bounds. `mouseReleaseEvent` also uses the frozen index, so finalized annotations always land on the origin page regardless of where the mouse was released.

### Root Cause (line-level)

```
L2784  page_idx = getattr(self, '_editing_page_idx', self.current_page)  # FROZEN
L2785  new_x, new_y = self._clamp_editor_pos_to_page(raw_x, raw_y, page_idx)  # clamps to wrong page
```

And in `_clamp_editor_pos_to_page`:
```
L3067  def _clamp_editor_pos_to_page(self, x, y, page_idx):
L3079      page_y0 = self.page_y_positions[page_idx]  # uses frozen index
```

### Fix

**File:** `view/pdf_view.py`

**Step 1** — Add a helper method to resolve page index from scene Y coordinate:

```python
def _scene_y_to_page_index(self, scene_y: float) -> int:
    """Given a scene Y coordinate, return the page index it falls within."""
    if not self.continuous_pages or not self.page_y_positions:
        return self.current_page
    for i in range(len(self.page_y_positions) - 1, -1, -1):
        if scene_y >= self.page_y_positions[i]:
            return i
    return 0
```

**Step 2** — In the drag-active block at L2779–2787, dynamically update `_editing_page_idx`:

```python
# Before (L2784):
page_idx = getattr(self, '_editing_page_idx', self.current_page)

# After:
editor_mid_y = raw_y + (self.text_editor.widget().height() / 2 if self.text_editor else 0)
page_idx = self._scene_y_to_page_index(editor_mid_y)
self._editing_page_idx = page_idx  # Update frozen index to destination page
```

**Step 3** — In `mouseReleaseEvent` (L3172–3190), read the now-updated `_editing_page_idx` for the finalization rect computation. No change needed if it already reads from `self._editing_page_idx` — just ensure the attribute was updated in Step 2.

**Step 4** — Also apply the same dynamic resolution in the `_drag_pending` block at L2769:

```python
# L2769: replace
page_idx = getattr(self, '_editing_page_idx', self.current_page)
# with:
editor_mid_y = (self._drag_editor_start_pos.y() + dy +
                (self.text_editor.widget().height() / 2 if self.text_editor else 0))
page_idx = self._scene_y_to_page_index(editor_mid_y)
self._editing_page_idx = page_idx
```

### Verification

1. Open continuous mode, navigate to a page boundary.
2. Double-click a text block near the bottom of page N.
3. Drag the editor downward past the page boundary into page N+1.
4. Release — editor should land on page N+1.
5. Finalize — text should be written to page N+1, not page N.

---

## Fix 4: G-7 — Sub-Pixel Drag Threshold [P2 MEDIUM]

### Problem

`mouseMoveEvent` at L2758 uses `dx*dx + dy*dy > 25` (5px Euclidean) as the drag threshold. Any movement smaller than 5px is silently discarded. Users cannot make precise small-distance position adjustments.

### Fix

**File:** `view/pdf_view.py` L2758

```python
# Before:
if dx * dx + dy * dy > 25:  # 超過 5px → 確認為拖曳

# After:
if dx * dx + dy * dy > 9:  # 超過 3px → 確認為拖曳
```

Lowering to 3px (threshold=9) balances between accidental trigger on click jitter (~1-2px typical) and allowing intentional small adjustments. If further precision is needed, consider accumulating sub-threshold movements:

```python
# Alternative: accumulate approach
if not hasattr(self, '_accumulated_drag_dist'):
    self._accumulated_drag_dist = 0.0
self._accumulated_drag_dist += math.sqrt(dx*dx + dy*dy)
if self._accumulated_drag_dist > 3.0:
    # begin drag...
```

Also update the position-change threshold at L3449–3452 to match:

```python
# Before (L3451-3452):
(abs(current_rect.x0 - original_rect.x0) > 0.5 or
 abs(current_rect.y0 - original_rect.y0) > 0.5)

# After:
(abs(current_rect.x0 - original_rect.x0) > 0.1 or
 abs(current_rect.y0 - original_rect.y0) > 0.1)
```

### Verification

1. Double-click a text block.
2. Drag exactly 3px diagonally.
3. Assert: editor moves 3px — not discarded as no-op.
4. Drag < 2px — assert: still treated as click (no accidental drag).

---

## Supplementary Fix S-1: Editor Non-Closure [P1 HIGH]

### Problem (discovered during testing)

The Escape key and clicks in blank/inter-page areas frequently failed to close the text editor. The editor remained open (Properties panel still showed 套用/取消 buttons), blocking Ctrl+S and other shortcuts. The only reliable way to close the editor was clicking on another text block — which also triggered a ghost write (Fix 1) and opened a new editor.

### Root Cause (hypothesis)

`keyPressEvent` for Escape likely calls `_finalize_text_edit` but the focus guard (`_finalize_if_focus_outside_edit_context`) may reject the finalization if focus hasn't actually left the editor widget. Clicking in the gray margin area (QGraphicsScene background) does not generate a `focusOut` event on the embedded QTextEdit because QGraphicsProxyWidget handles focus differently from regular widgets.

### Fix

**File:** `view/pdf_view.py`

**Step 1** — In `keyPressEvent` (or wherever Escape is handled), bypass the focus guard and call `_finalize_text_edit_impl` directly with a `discard=True` flag:

```python
if event.key() == Qt.Key_Escape and self.text_editor:
    self._discard_text_edit_once = True
    self._finalize_text_edit()
    event.accept()
    return
```

**Step 2** — In `mousePressEvent`, if the click is in a blank area (no text block hit) and an editor is open, force-close the editor:

```python
# After checking for text block hits and finding none:
if self.text_editor and not hit_text_block:
    self._finalize_text_edit()
    return
```

### Verification

1. Double-click a text block to open editor.
2. Press Escape — editor closes, no corruption.
3. Double-click to reopen, click in gray margin — editor closes.
4. Double-click to reopen, click in inter-page gap — editor closes.

---

## Supplementary Fix S-2: Ctrl+S Blocked by Editor Focus [P2 MEDIUM]

### Problem (discovered during testing)

When the text editor widget has keyboard focus, `Ctrl+S` is not dispatched to the `_action_save` toolbar action, even though it uses `Qt.WindowShortcut` context. Save only works via the toolbar 儲存 button while an editor is open.

### Root Cause

The QGraphicsProxyWidget-embedded QTextEdit captures all key events including `Ctrl+S`. `Qt.WindowShortcut` on a QAction requires the action's associated widget (the toolbar button) to be in the active window's shortcut scope — but QGraphicsProxyWidget's internal event handling intercepts the event before Qt's shortcut system processes it.

### Fix

**File:** `view/pdf_view.py`

Add a key event filter on the text editor widget that forwards Ctrl+S (and Ctrl+Z/Y) to the main window:

```python
def _install_editor_key_filter(self, editor_widget):
    """Install an event filter that forwards global shortcuts from the embedded editor."""
    class EditorKeyFilter(QObject):
        def __init__(self, view):
            super().__init__(view)
            self.view = view

        def eventFilter(self, obj, event):
            if event.type() == QEvent.KeyPress:
                if event.modifiers() == Qt.ControlModifier:
                    if event.key() == Qt.Key_S:
                        self.view._save()
                        return True
                    elif event.key() == Qt.Key_Z:
                        self.view._action_undo.trigger()
                        return True
                    elif event.key() == Qt.Key_Y:
                        self.view._action_redo.trigger()
                        return True
            return False

    editor_widget.installEventFilter(EditorKeyFilter(self))
```

Call `_install_editor_key_filter(editor)` in `_create_text_editor` after the editor widget is created.

### Verification

1. Double-click a text block (editor has focus).
2. Press Ctrl+S — save dialog appears.
3. Press Ctrl+Z — undo fires (after Fix 2 is implemented).

---

## Implementation Order

```
Phase 1 (P0):  Fix 1 (ghost text guard)           → eliminates the most damaging bug
Phase 2 (P1):  Fix 2 (undo stack)                  → makes all edits reversible
                Fix 3 (cross-page drag)             → unblocks cross-page editing
                Fix S-1 (editor non-closure)        → fixes the interaction that triggers ghost writes
Phase 3 (P2):  Fix 4 (drag threshold)              → precision improvement
                Fix S-2 (Ctrl+S in editor)          → keyboard shortcut passthrough
```

Within each phase, fixes are independent and can be implemented in any order. All fixes are in `view/pdf_view.py` except Fix 2 which also touches `controller/pdf_controller.py` and `model/edit_commands.py`.

---

## Regression Safety Net

After all fixes:

1. Run existing test suite: `python3 test_scripts/test_track_ab_5scenarios.py` — all 17 scenarios must pass.
2. Re-run the full 9-case GUI checklist from `docs/plans/2026-03-25-gui-cowork-checklist.md`.
3. Specifically verify the "ghost-write cascade" (Cases 1→3→5 interaction) no longer occurs.
4. Test with at least 3 different PDF files to catch font/encoding edge cases in the normalization helper.

---

## Key Files Summary

| File | Fixes |
|------|-------|
| `view/pdf_view.py` | Fix 1, Fix 3, Fix 4, Fix S-1, Fix S-2 |
| `controller/pdf_controller.py` | Fix 2 |
| `model/edit_commands.py` | Fix 2 (SnapshotCommand usage) |

---

*Plan generated based on live GUI test report — 2026-03-26*
