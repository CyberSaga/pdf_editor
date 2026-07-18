# M3.8 True Tab Detachment Implementation Plan

**Status:** Complete 2026-07-16; archived after final milestone verification.

## Goal

Detach a document tab by dragging it outside the tab bar into a separate in-process window with an independent PDFModel/PDFView/PDFController triple, while preserving document bytes, path/dirty/current-page/zoom state and never sharing a live `fitz.Document` or undo stack.

## Fixed transfer contract

- `SessionTransferPayload` is a DTO containing immutable PDF snapshot bytes, source path, saved path, display name, dirty flag, current page, zoom, color profile, and in-memory password/auth metadata only where needed to reopen the snapshot.
- Snapshot bytes and credentials are never written to preferences, logs, temp files, or repr output.
- Destination creation is prepare-first and atomic: compose the destination MVC triple, import/activate the session, restore UI state, and signal readiness before removing the source tab.
- Any destination failure leaves the source session/tab untouched.
- The destination owns a separate `fitz.Document`, command manager, render workers, view, and controller. Pre-detach undo/redo history is intentionally unavailable and documented.
- Dirty state transfers as session-local state. It clears only through the normal successful save path.
- `main.py` remains the only composition root and owns a `WindowManager`-style registry of primary/secondary triples. Secondary cleanup removes the registry entry only after its view/controller workers close.
- Single-instance forwarded file opens continue targeting the primary window.

## Gesture contract

- `DetachableTabBar` records the pressed tab's stable session id and press position.
- A click or drag released inside the tab bar/window does not detach.
- A release outside the tab bar/window after `QApplication.startDragDistance()` emits exactly one `detach_requested(session_id, global_pos)`.
- Native in-bar tab switching/reordering behavior remains unchanged.

## Files

- Create: `controller/session_transfer.py`
- Create: `view/detachable_tab_bar.py`
- Modify: `model/pdf_model.py`
- Modify: `controller/pdf_controller.py`
- Modify: `view/pdf_view.py`
- Modify: `main.py`
- Create: `test_scripts/test_tab_detach.py`

## Red-light matrix

1. Payload repr excludes snapshot/password; source and destination documents are distinct handles with byte-equivalent content.
2. Saved and dirty source sessions transfer path/display/dirty state; destination save clears dirty normally.
3. Destination command manager begins empty; source history is not aliased.
4. Controller capture includes current page/zoom/profile and invokes an injected handoff callback.
5. Source closes only after callback success; callback exception/False preserves source.
6. Drag threshold/outside release emits once; click, short drag, or in-bar release emits zero.
7. Destination window close prompts independently and cleanup drops only that MVC triple.

## Steps

1. Write and run the red model/payload/controller/gesture tests.
2. Implement DTO and Qt-free model export/import seams.
3. Implement DetachableTabBar and replace the existing document tab bar without changing explicit close-button/session-id behavior.
4. Add controller transfer capture and success-gated source close.
5. Add main composition manager for secondary windows and cleanup.
6. Run focused multi-tab/single-instance/close/render worker regressions, then full suite/Ruff/mypy.
7. Archive this plan and document the intentional no-undo-history limitation.

## Completion evidence

- Red phase: `controller.session_transfer` did not exist.
- Focused transfer/gesture/atomicity tests: 4 passed.
- Multi-tab/startup regressions: 95 passed, 1 skipped.
- Final milestone suite: 1804 passed, 21 skipped in 226.84 s.
- Ruff: all checks passed.
- mypy: success, no issues in 36 source files.
- Manual saved/dirty drag-out acceptance remains explicitly pending in `TODOS.md`.
