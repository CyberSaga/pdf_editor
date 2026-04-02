# CEO Review — Root Cause Analysis & Fix Plan
**Date**: 2026-03-27
**Branch**: `codex/text-editing-function-by-iterating-repeatedly`
**Reviewed commits**: `4c671b7`, `29a1395`

---

## Executive Summary

Three remaining bugs block Acrobat-level UX. All three have clear, traceable root causes in `view/pdf_view.py` and `controller/pdf_controller.py`. The fixes are surgical — no architectural redesign needed.

| # | Bug | Severity | Root Cause (1 sentence) | Fix Effort |
|---|-----|----------|------------------------|------------|
| 1 | Escape key doesn't close editor | P0 | Event filter skips non-Ctrl keys, so Escape never reaches `_handle_escape()` | 10 min |
| 2 | Ctrl+Z broken (in-editor + document-level) | P0 | Two independent causes: event filter steals + swallows Ctrl+Z; shortcut context blocks hidden-tab actions | 20 min |
| 3 | Cross-page drag writes to wrong page | P1 | Signal sends destination page + source-page rect — model looks for text on wrong page | 30 min |

---

## Bug 1 — Escape Key Doesn't Close Editor

### Symptom
Pressing Escape 1–2× while the QTextEdit editor has text focus does nothing. The editor stays open.

### Root Cause

**File**: `view/pdf_view.py`

Three Escape handlers exist; **all three fail** when the QTextEdit is embedded in a QGraphicsProxyWidget:

1. **Monkey-patch** (L3486–3491):
   ```python
   editor.keyPressEvent = _editor_key_press  # L3491
   ```
   PySide6's QGraphicsProxyWidget dispatches key events through the C++ virtual table. The Python-level instance method override is bypassed — `_editor_key_press` is never called.

2. **QShortcut** (L3481–3483):
   ```python
   editor_esc = QShortcut(QKeySequence(Qt.Key_Escape), editor)
   editor_esc.setContext(Qt.ShortcutContext.WidgetShortcut)
   ```
   `WidgetShortcut` requires the widget to have native Qt focus. Inside a graphics proxy, the QTextEdit doesn't hold focus in the widget tree — the QGraphicsView does. The shortcut never activates.

3. **`_EditorShortcutForwarder.eventFilter`** (L112–126):
   ```python
   def eventFilter(self, obj, event):
       if event.type() != QEvent.KeyPress:
           return False
       modifiers = event.modifiers()
       if not (modifiers & Qt.ControlModifier):
           return False          # ← Escape (no modifier) exits here!
   ```
   The event filter is the **only handler that actually fires** (installed via `installEventFilter` at L3479, which works inside proxies). But it has an early return at L116 for non-Ctrl keys, so Escape is silently dropped.

### Fix

Add Escape handling **before** the Ctrl modifier check in `_EditorShortcutForwarder.eventFilter`:

```python
# view/pdf_view.py, class _EditorShortcutForwarder, eventFilter method
def eventFilter(self, obj, event):
    if event.type() != QEvent.KeyPress:
        return False
    # ── NEW: handle Escape (no modifier required) ──
    if event.key() == Qt.Key_Escape:
        view = self._view
        if view is not None and hasattr(view, '_handle_escape'):
            if view._handle_escape():
                return True
        return False
    # ── existing Ctrl+ handling ──
    modifiers = event.modifiers()
    if not (modifiers & Qt.ControlModifier):
        return False
    ...
```

**Insert at**: L113, before `modifiers = event.modifiers()` (L115).

**Lines to remove** (now redundant):
- L3481–3484 (QShortcut on editor) — optional cleanup, no harm leaving them.
- L3486–3491 (monkey-patch keyPressEvent) — optional cleanup.

---

## Bug 2 — Ctrl+Z Broken (Two Independent Causes)

### Bug 2a: In-Editor Ctrl+Z (Local Undo)

#### Symptom
User types "TEST " in editor → presses Ctrl+Z → nothing happens.

#### Root Cause

**File**: `view/pdf_view.py`, `_EditorShortcutForwarder`

The event filter intercepts Ctrl+Z (L120–121) and calls `_handle_editor_undo()`. This function:

```python
def _handle_editor_undo(self) -> bool:        # L94
    widget = self._editor_widget()
    if widget is None:
        return True                            # L97 — consumes event even if no widget
    document = widget.document() if hasattr(widget, "document") else None
    if document is not None and document.isUndoAvailable():
        widget.undo()                          # L100
    return True                                # L101 — ALWAYS consumes event
```

Two problems:
1. **Always returns True** (L101): even when `isUndoAvailable()` is False, the event is consumed. QTextEdit's **built-in** Ctrl+Z handler never gets the event.
2. **Redundant manual undo**: QTextEdit already handles Ctrl+Z natively. The event filter steals the event, calls `widget.undo()` manually (which may or may not work through the proxy), and prevents the natural path.

#### Fix

**Option A (minimal)**: Change `_handle_editor_undo` to return `False` so QTextEdit handles it natively:

```python
def _handle_editor_undo(self) -> bool:
    return False  # let QTextEdit's built-in undo handle it
```

**Option B (clean, recommended)**: Remove Ctrl+Z/Y interception entirely from the event filter. QTextEdit's built-in undo already works. The original intent was to prevent document-level undo from firing — but that is better solved by disabling the shortcut (see Bug 2b fix).

```python
# Remove L120-125 from eventFilter:
#   if event.key() == Qt.Key_Z and not (modifiers & Qt.ShiftModifier):
#       return self._handle_editor_undo()
#   if event.key() == Qt.Key_Y:
#       return self._handle_editor_redo()
#   if event.key() == Qt.Key_Z and (modifiers & Qt.ShiftModifier):
#       return self._handle_editor_redo()
```

Then add shortcut disabling when editor opens (see 2b fix below).

### Bug 2b: Document-Level Ctrl+Z (Editor Closed)

#### Symptom
After committing an edit (editor closed), pressing Ctrl+Z does nothing. The toolbar "復原" button works.

#### Root Cause

**File**: `view/pdf_view.py`, L1732

```python
for action in (
    self._action_open,
    ...
    self._action_undo,          # ← L1727
    self._action_redo,          # ← L1728
    ...
):
    action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # L1732
```

`WidgetWithChildrenShortcut` means: shortcut fires only when the action's parent widget **or its children** has focus.

`_action_undo` was added to `tb_common` (the "常用" toolbar, L1613). When the user is on the **"編輯" tab** (where text editing happens), the "常用" tab is hidden. A hidden toolbar cannot have focus → shortcut never fires.

The toolbar "復原" button (`_action_undo_right`, L1698) works because it's clicked directly — no shortcut needed.

#### Fix

Change shortcut context for undo/redo to `WindowShortcut`:

```python
# L1732 — change the loop to exclude undo/redo, or add special handling:
# AFTER the existing loop, override for undo/redo:
self._action_undo.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
self._action_redo.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
```

**Insert at**: After L1732 (after the `for` loop that sets `WidgetWithChildrenShortcut`).

**Conflict prevention**: When the editor is open, Ctrl+Z should do local undo (not document undo). Add a guard:

```python
# In _create_text_editor, after L3478:
self._action_undo.setEnabled(False)  # disable document undo while editor is open
self._action_redo.setEnabled(False)

# In _finalize_text_edit_impl, after proxy removal (~L3668):
self._action_undo.setEnabled(True)
self._action_redo.setEnabled(True)
```

This ensures:
- **Editor open**: Ctrl+Z → QTextEdit handles it natively (local undo)
- **Editor closed**: Ctrl+Z → `_action_undo` fires → `sig_undo.emit()` → document undo

---

## Bug 3 — Cross-Page Drag Writes to Wrong Page

### Symptom
Drag text from page 4 into page 5 territory → commit → text appears to stay on page 4 (or position is silently clamped). The `*` asterisk appears (something committed) but visible result is unchanged.

### Root Cause

**File**: `view/pdf_view.py` + `controller/pdf_controller.py`

When the drag crosses a page boundary:

1. **`_resolve_editor_page_idx_for_drag`** (L2600) correctly updates `_editing_page_idx` to the destination page (e.g., 5).

2. **Drag-end handler** (L3367–3378) computes `editing_rect` in the **destination page's** coordinate space:
   ```python
   page_idx = getattr(self, '_editing_page_idx', ...)  # destination page
   y0 = self.page_y_positions[page_idx]                 # destination page offset
   new_y0 = (proxy_pos.y() - y0) / rs                   # dest page coords
   self.editing_rect = fitz.Rect(...)                    # in dest page space
   ```

3. **`_finalize_text_edit_impl`** (L3653) reads:
   ```python
   edit_page = getattr(self, '_editing_page_idx', ...)   # destination page (5)
   original_rect = self._editing_original_rect            # SOURCE page (4) coords
   current_rect = self.editing_rect                       # DEST page (5) coords
   ```

4. **Signal emission** (L3723):
   ```python
   self.sig_edit_text.emit(
       edit_page + 1,     # page 5 (1-indexed)
       original_rect,     # page 4's coordinate space  ← MISMATCH
       new_text,
       ...
       new_rect_arg,      # page 5's coordinate space  (correct)
   )
   ```

5. **Controller `edit_text`** (L1457–1470):
   ```python
   page_idx = page - 1                                    # = 4 (page 5, 0-indexed)
   snapshot = self.model._capture_page_snapshot(page_idx)  # snapshots page 5
   ```
   Then `EditTextCommand` tries to find text at `original_rect` **on page 5**. The text is actually on page 4 → **lookup fails** → model can't redact the old text → the edit becomes a ghost insertion or silent no-op, depending on the model's error handling.

### Fix (Two Phases)

#### Phase 1 — Safety: Clamp drag to same page (prevents data corruption)

Prevent `_editing_page_idx` from changing during drag. This disables cross-page drag but avoids silent data corruption.

```python
# L2600, _resolve_editor_page_idx_for_drag
def _resolve_editor_page_idx_for_drag(self, editor_top_y: float) -> int:
    # Phase 1: always return original page to prevent cross-page corruption
    return getattr(self, "_editing_page_idx", self.current_page)
```

This is a 1-line change that restores safe behavior until Phase 2 is ready.

#### Phase 2 — Full cross-page move (requires model support)

1. **Track source page separately**:
   ```python
   # In _create_text_editor (~L3420):
   self._editing_original_page_idx = page_idx  # NEW: remember source page
   ```

2. **Extend `sig_edit_text` signal** to include source page:
   ```python
   sig_edit_text = Signal(int, int, object, str, ...)  # add source_page param
   ```

3. **In `_finalize_text_edit_impl`**, detect cross-page move:
   ```python
   original_page = getattr(self, '_editing_original_page_idx', edit_page)
   is_cross_page = (original_page != edit_page)
   if is_cross_page:
       # Emit delete on source page + add on destination page
       self.sig_delete_text.emit(original_page + 1, original_rect)
       self.sig_add_textbox.emit(edit_page + 1, current_rect, new_text, ...)
   else:
       self.sig_edit_text.emit(edit_page + 1, original_rect, ...)
   ```

4. **Snapshot both pages** in the command for proper undo.

Phase 2 is a moderate refactor (~50 lines). Recommend shipping Phase 1 now and Phase 2 in the next sprint.

---

## Implementation Priority

| Order | Fix | Lines Changed | Risk |
|-------|-----|--------------|------|
| 1 | Bug 1 (Escape) | ~6 lines in eventFilter | Zero — additive |
| 2 | Bug 2b (doc Ctrl+Z context) | ~3 lines after L1732 | Low — isolated |
| 3 | Bug 2a (editor Ctrl+Z) | ~6 lines in eventFilter + 4 lines in create/finalize | Low — removes code |
| 4 | Bug 3 Phase 1 (clamp drag) | 1 line in `_resolve_editor_page_idx_for_drag` | Zero — conservative |
| 5 | Bug 3 Phase 2 (full cross-page) | ~50 lines across view + controller | Medium — needs testing |

**Total for fixes 1–4**: ~20 lines changed. Can ship in one commit.

---

## Verification Plan

After applying fixes 1–4:

```
Test 1 (Bug 1): Double-click text → type "X" → press Escape → editor closes, text reverted
Test 2 (Bug 2a): Double-click text → type "X" → Ctrl+Z → "X" disappears in editor
Test 3 (Bug 2b): Double-click text → type "X" → click away (commit) → Ctrl+Z → text reverts
Test 4 (Bug 3): Double-click text near page boundary → drag across → editor clamps to same page
```
