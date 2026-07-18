# M3.7 Notes and Bookmarks Implementation Plan

**Status:** Complete 2026-07-16; archived after full verification.

**Goal:** Replace oversized new FreeText comments with compact draggable PDF text notes and add an MVC-owned nested TOC/bookmark panel whose page targets survive structural edits.

**Architecture:** AnnotationTool and PDFModel own PDF annotation/TOC correctness. PDFController wraps every mutation in one SnapshotCommand and refreshes render/list/tree state. PDFView and FloatingNote emit DTO requests only; no widget accesses the model. Structural model methods route bookmark page numbers through one remapping helper.

## Slice A — Compact draggable notes

Affected files:
- `model/tools/annotation_tool.py`
- `controller/pdf_controller.py`
- `view/floating_note.py`
- `view/pdf_view.py`
- `test_scripts/test_floating_notes.py`

Steps:
1. Red-test real PyMuPDF text-note create/list/reopen, legacy FreeText compatibility, update/move/delete, and invalid xref/page guards.
2. Add normalized annotation DTOs with `xref`, zero-based `page_num`, `rect`, `text`, `kind`, and `read_only`.
3. Change new-comment creation to `page.add_text_annot`; retain legacy FreeText list/jump compatibility as read-only.
4. Add controller snapshot handlers for content update, marker move, and delete.
5. Add `FloatingNote`, a main-window-owned frameless child with text editor, save/delete/close signals, and independent popup dragging.
6. Route browse-mode note-marker clicks before text selection; marker drag emits a move request, popup drag changes only window-local position.
7. Verify create/move/update/delete/undo/redo/save/reopen and no taskbar/Alt-Tab window.

## Slice B — TOC/bookmarks

Affected files:
- `model/pdf_model.py`
- `controller/pdf_controller.py`
- `view/pdf_view.py`
- `view/dialogs/bookmarks.py` only if inline tree controls are insufficient
- `test_scripts/test_bookmarks_toc.py`

Steps:
1. Red-test normalized get/set round trip and invalid levels/pages/titles.
2. Red-test one central page-map helper for insert, delete range/delete-all placeholder, and final-index move semantics.
3. Apply the helper from every structural model operation so bookmarks follow logical content and always remain within `1..page_count`.
4. Add controller query/snapshot handlers for add/rename/delete/reorder and tree refresh.
5. Add a nested `QTreeWidget` left-sidebar tab; clicks emit page navigation, edits emit controller requests.
6. Verify nesting, structural remap, undo/redo, save/reopen, and existing thumbnail/search/annotation tabs.

## Open questions resolved

- New notes use standard PDF Text annotations; legacy FreeText entries stay listed/jumpable but are not edited by the compact-note popup.
- Popup position is UI-only. Marker rectangle and note content are the only persisted note state.
- Deleted bookmark targets map to the nearest surviving page at the deleted position, clamped to the final page count.
- TOC entry levels must start at 1 and may increase by at most one between adjacent entries, matching PyMuPDF's hierarchy contract.

## Completion evidence

- Red notes phase: `view.floating_note` did not exist.
- Red TOC phase: `PDFModel.set_toc` did not exist.
- Focused notes/bookmark tests: 12 passed; structural/annotation regressions: 140 passed, 1 skipped.
- Full suite: 1800 passed, 21 skipped in 217.62 s.
- Ruff: all checks passed.
- mypy: success, no issues in 36 source files.
