# PDF Merge Feature Design

**Date:** 2026-03-11

**Goal:** Add a merge workflow on the `頁面` tab that lets users collect PDFs from the Windows file picker, reorder them with the current document included, and either save a brand-new merged file or merge back into the current tab.

## Scope

- Add a modal merge dialog launched from the `頁面` tab.
- Always include the current document in the reorder list.
- Allow additional PDFs to be appended through repeated file-picker selections.
- Support drag reordering, including multi-selection reordering with `Shift`.
- Lock the current document row so it cannot be removed.
- Support two outcomes:
  - save a brand-new merged PDF and open it as a new tab
  - merge into the current tab and mark it unsaved

## Architecture

- `view/pdf_view.py`
  - Add a merge action on the `頁面` toolbar.
  - Add a `MergePdfDialog` for the workflow UI.
  - Add a lightweight dialog-owned session model for merge entries and button state.
- `controller/pdf_controller.py`
  - Open the dialog.
  - Resolve ordered entries into readable PDF sources.
  - Reuse existing password prompt behavior with retry-on-failure and skip-on-cancel.
  - Show clear rejection messages for unreadable or fake PDFs.
- `model/pdf_model.py`
  - Add merge helpers that compose a new temporary document from ordered sources.
  - Reuse the composed document for both outcomes:
    - save/open as new
    - replace active session document contents and mark dirty

## Merge Rules

- The current file is always part of the order list in both modes.
- The current file can be reordered but cannot be removed.
- New file-picker selections append to the end of the current list.
- Final page order matches the visible list order exactly.
- Password-protected files prompt for a password.
- Wrong passwords show a retry message.
- Cancelling the password prompt skips that file.
- Fake `.pdf` files and other unreadable files are rejected with clear messages and skipped.
- If no valid files remain, `確認合併` stays disabled.

## Error Handling

- File picker cancel: no state change.
- Save dialog cancel in brand-new mode: abort merge without changing the current document.
- Empty/invalid effective list: keep confirm disabled.
- Large add/validation operations: show progress dialog while processing.

## Testing Strategy

- Unit-style tests for merge-session ordering, locked-row removal rules, and confirm enablement.
- Dialog/controller tests for repeated file selection, invalid-file rejection, and password retry/cancel behavior.
- Model tests for ordered merge composition and active-session replacement behavior.
- Integration test for opening the dialog from the `頁面` tab and completing a merge path.
