# Text Editing GUI Design

**Date:** 2026-03-26

## Goal

Harden inline text editing so that closing an unchanged editor is a true no-op, dragging can cross page boundaries in continuous mode, small intentional drags are preserved, and editor-focused keyboard/closure behavior remains consistent with app-level actions.

## Scope

- Fix false-positive text-change detection during finalize.
- Fix frozen page ownership while dragging the inline editor across pages.
- Reduce drag activation friction for precise moves.
- Ensure `Escape`, click-outside, and `Ctrl+S`/undo/redo work while the embedded editor has focus.
- Add focused regressions around the new helper/state-transition behavior.

## Chosen Approach

Keep the existing controller/model edit pipeline, including `EditTextCommand`, and correct the view-layer state it receives. This avoids reworking undo infrastructure that already exists on the current branch and keeps the change localized to editor lifecycle and scene-coordinate handling.

## Alternatives Considered

### 1. Rebuild finalize/undo around page snapshots

This would duplicate logic that already exists in `controller/pdf_controller.py` and `model/edit_commands.py`. It is higher risk and not justified by the current code.

### 2. Block complex interactions instead of fixing them

Examples: disallow cross-page drags, disable shortcuts while editing, or force-close the editor on more events. This would reduce bugs but also regress usability.

### 3. Fix the view state machine only

This keeps behavior aligned with existing architecture, addresses the confirmed bugs directly, and preserves the current undo command path. This is the selected approach.

## Design

### Finalize behavior

Normalize editor text and original text before comparing, with ligature expansion and whitespace normalization. Treat finalize as a no-op when text, position, font, and size are materially unchanged. Preserve the existing discard path for explicit cancel actions.

### Drag behavior

Resolve the current page from scene Y during drag start and drag move, update `_editing_page_idx` as the editor crosses page boundaries, and clamp against the destination page rather than the origin page. Recompute the final `editing_rect` from the updated page index.

### Editor interaction behavior

Route `Escape` through the existing discard path, finalize when clicking outside active editor context, and forward editor-focused `Ctrl+S`, `Ctrl+Z`, `Ctrl+Y`, and `Ctrl+Shift+Z` to the window actions so embedded `QTextEdit` focus does not trap those shortcuts.

### Testing

Add targeted regressions for text normalization/no-op finalize, page-index resolution during drag, and editor shortcut forwarding. Use the existing offscreen Qt test harness in `test_scripts`.
