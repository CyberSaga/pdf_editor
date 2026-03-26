# Text Editing Undo/Focus UX Design

**Date:** 2026-03-26

## Goal

Align inline text-editor shortcut behavior with Acrobat: while the editor is focused, `Ctrl+Z` and redo shortcuts operate only on the editor's local text history, never fall through to PDF-level undo/redo, and never close or finalize the editor when no local history exists.

## Scope

- Keep the inline editor visually transparent over the PDF.
- Fix editor-focused `Ctrl+Z`, `Ctrl+Y`, and `Ctrl+Shift+Z`.
- Prevent shortcut-triggered focus changes from causing accidental finalize/commit.
- Validate that the PDF command stack still behaves correctly when edits are explicitly finalized.

## Approaches Considered

### 1. Always forward undo/redo to window actions

This is the current behavior. It keeps a single shortcut path but breaks the editor UX because typed characters do not undo locally and window action dispatch can trigger focus-out finalize.

### 2. Editor-local undo/redo first, then fallback to PDF undo/redo

This is closer to a hybrid document model, but it still violates the desired Acrobat-like behavior. It also keeps the focus-loss bug surface because fallback still routes through window actions.

### 3. Editor-local undo/redo only while focused

This matches the requested behavior and cleanly separates "editing text inside the widget" from "undoing committed PDF changes". It also removes the focus-loss/finalize path for undo/redo shortcuts because those shortcuts no longer invoke window actions while the editor is active.

This is the selected approach.

## Design

### Shortcut ownership

`Ctrl+Z`, `Ctrl+Y`, and `Ctrl+Shift+Z` are owned by the focused inline `QTextEdit`. The event filter should inspect the editor document state and call `undo()` or `redo()` directly when available.

### Empty local history

If the focused editor has no local undo/redo history, consume the shortcut and do nothing. The editor remains open and no finalize path runs.

### Window-level actions

`Ctrl+S` remains forwarded to the window save action because saving is not an editor-local text-history operation and the earlier UX improvement for save-while-editing remains useful.

### Focus/finalize interactions

Because undo/redo no longer forward to window actions, the main accidental finalize path should disappear. As a safety net, the tests should confirm that shortcut handling does not request finalize when local history is empty.

### Testing

Add regressions for:
- local undo when editor history exists,
- local redo when editor redo history exists,
- no-op consumption when local history is empty,
- `Ctrl+S` still forwarding,
- no window-level undo/redo action trigger while editor is focused.
