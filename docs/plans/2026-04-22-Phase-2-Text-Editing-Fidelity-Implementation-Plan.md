# Phase 2 Text Editing Fidelity Implementation Plan

## Summary

Close Phase 2 as one text-editing epic, with root-cause work centered on the transactional edit pipeline in `model/pdf_model.py` plus the inline-editor state in `view/text_editing.py`. Treat the five backlog items as one shared regression cluster: geometry drift, font-size round-tripping, styled-span collapse, transparent editor masking, and rotated-text clipping must all get red-light coverage first, then be fixed together so the pipeline stops regressing symptom-by-symptom.

Important repo truth to plan against:
- The backlog doc’s `src/...` pointers are stale for this workspace.
- The real edit-fidelity code lives in `model/pdf_model.py`, `view/text_editing.py`, `view/pdf_view.py`, and `controller/pdf_controller.py`.
- `model/edit_requests.py` should remain the single source of truth for typed edit payloads; `view/text_editing.py` should only re-export them.

## Key Changes

### Task 1: Build the Phase-2 red-light matrix first

**Files**
- Modify: `test_scripts/test_edit_text_helpers.py`
- Modify: `test_scripts/test_text_editing_gui_regressions.py`
- Modify: `test_scripts/test_text_edit_manager_foundation.py`
- Modify: `test_scripts/test_char_run_reconstruction.py`
- Create if needed: `test_scripts/test_text_edit_phase2_regressions.py`

**Work**
- Add one explicit failing reproduction for each Phase-2 symptom:
  - Commit keeps same-line text anchored when content/style change but no drag happened.
  - Fractional font size survives open-edit-commit without truncation.
  - Multi-style text edits do not collapse to dominant `helv`/black styling.
  - Inline editor stylesheet stays transparent while the scene mask hides rendered PDF text underneath.
  - Rotated text editor commits without scaling up or clipping content.
- Keep model failures in real-PDF tests and widget/proxy failures in GUI-fake tests.
- Reuse `test_files/1.pdf` and existing char-run reconstruction coverage for styled-span cases instead of inventing synthetic-only fixtures.

**Red commands**
- `pytest test_scripts/test_edit_text_helpers.py -v`
- `pytest test_scripts/test_text_editing_gui_regressions.py -v`
- `pytest test_scripts/test_char_run_reconstruction.py -v`

### Task 2: Normalize edit payloads and float font-size handling

**Files**
- Modify: `model/edit_requests.py`
- Modify: `view/text_editing.py`
- Modify: `controller/pdf_controller.py`

**Work**
- Remove the duplicate `EditTextRequest` and `MoveTextRequest` dataclasses from `view/text_editing.py`; import and re-export the model-layer types instead.
- Change `TextEditSession.current_size` and `initial_size` from `int` to `float`.
- Add one parsing/formatting path for the size combo box so the UI can display and round-trip values like `9.5` without truncating to `9`.
- Keep controller request handling backward-compatible: typed requests still flow through `edit_text(...)` and `move_text_across_pages(...)` with float size preserved end-to-end.

**Acceptance**
- A view-originated edit emits float `size` in the request payload.
- Cross-page move payloads keep the same float size.
- Existing controller compatibility tests keep passing.

### Task 3: Fix the model edit pipeline at the real root cause

**Files**
- Modify: `model/pdf_model.py`
- Modify if needed: `model/text_block.py`

**Work**
- Keep the current transactional phases (`_resolve_edit_target`, `_apply_redact_insert`, `_verify_rebuild_edit`) but tighten responsibilities:
  - Same-page, non-drag, single-line edits must preserve the original anchor and avoid paragraph-style push-down/reflow when the text still fits.
  - Dragged edits and paragraph moves may still re-layout, but only inside the requested rect and without moving unrelated spans.
- Add style-aware reinsertion for multi-style targets:
  - If the user did not explicitly change font/size/color, reconstruct HTML from the target member runs and preserve per-run styling instead of collapsing to the paragraph’s dominant font/color.
  - Inserted text should inherit the nearest edited run’s style.
  - Explicit user style changes may still restyle only the edited target uniformly.
- Strengthen verification:
  - Fail and roll back if anchor drift exceeds tolerance for non-drag edits.
  - Fail and roll back if protected spans disappear or if preserved runs lose expected style metadata.
  - Keep existing protected-span replay and char-run reconstruction as the reference mechanism, not a second parallel path.

**Acceptance**
- Position-shift regressions stop at the model layer, not via view-only compensation.
- Styled paragraphs stay styled after edit/undo/redo.
- Verification catches both text loss and style-collapse regressions.

### Task 4: Fix inline-editor geometry, transparency, and rotated editing behavior

**Files**
- Modify: `view/text_editing.py`
- Modify: `view/pdf_view.py`

**Work**
- Keep the editor widget background transparent and the scene mask item responsible for hiding the already-rendered PDF text.
- Ensure mask refresh happens on editor creation, drag move, zoom/scale-sensitive relayout, and finalize cleanup.
- Recompute proxy layout from `_render_scale`, source rect, and rotation using floats; do not let font-size rounding or swapped width/height produce oversized/clipped rotated editors.
- Keep finalize delta checks tolerant to float-size comparisons and no-op detection.

**Acceptance**
- Rotated editors open with correct proxy rotation and commit without clipping.
- Transparent editor tests verify no solid background is introduced.
- Mask item is added, updated, and removed correctly across create/drag/finalize flows.

### Task 5: Final integration, docs, and verification

**Files**
- Modify: `docs/PITFALLS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TODOS.md`

**Work**
- Document the real Phase-2 root cause and the final contracts:
  - `model/edit_requests.py` is the only request-type definition point.
  - Float font sizes are preserved from hit-test through commit.
  - Non-drag edits preserve anchors; paragraph/run scope decides whether re-layout is allowed.
  - Transparent editor masking is split between widget stylesheet and scene mask item.
- Mark the backlog/TODO state for Phase 2 once the regression matrix is green.

## Public Interfaces / Type Changes

- `TextEditSession.current_size` and `TextEditSession.initial_size` become `float`.
- `view/text_editing.py` stops defining local request dataclasses and re-exports `EditTextRequest` / `MoveTextRequest` from `model.edit_requests`.
- No controller API break: `PDFController.edit_text(...)` and `move_text_across_pages(...)` keep accepting typed requests and legacy kwargs.

## Test Plan

Run in this order:
1. `pytest test_scripts/test_edit_text_helpers.py -v`
2. `pytest test_scripts/test_text_edit_manager_foundation.py -v`
3. `pytest test_scripts/test_text_editing_gui_regressions.py -v`
4. `pytest test_scripts/test_char_run_reconstruction.py test_scripts/test_cross_page_text_move.py test_scripts/test_empty_text_edit.py -v`
5. `ruff check .`
6. `pytest -q`

Manual smoke after automated tests:
- Edit a same-line horizontal run without dragging and confirm no post-commit shift.
- Edit a `9.5pt` text run and confirm it remains `9.5pt` after reopen.
- Edit a mixed-style paragraph and confirm font/color diversity survives commit, undo, and redo.
- Edit a rotated text target and confirm live editor orientation and final content match.

## Assumptions

- Phase 2 should close the whole regression cluster even if parts of it are partially fixed already; existing fixes are treated as candidates to lock in with tests, not as reasons to skip coverage.
- Styled-span preservation applies when the user is editing content, not intentionally reformatting the selection; explicit style changes still win for the edited target.
- This plan targets the current repo layout, not the stale `src/...` paths in `docs/5-phases-of-to_Update.md`.
