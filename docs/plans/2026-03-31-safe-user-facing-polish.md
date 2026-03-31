# Safe User-Facing Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the dead text-property panel and expand the browse/fullscreen context menu without taking on risky architectural churn.

**Architecture:** Keep the changes local to `PDFView` and `TextEditManager`, because those already own the text editor lifecycle and context menu rendering. Add regression tests first, then update the panel state from the existing selection/editor flows so we improve UX without widening the controller/model surface area.

**Tech Stack:** Python, PySide6, PyMuPDF, pytest

---

### Task 1: Add failing tests for text property panel state

**Files:**
- Modify: `test_scripts/test_text_editing_gui_regressions.py`
- Modify: `test_scripts/test_multi_tab_plan.py`

**Steps:**
1. Add a regression test that verifies `text_apply_btn` and `text_cancel_btn` are disabled when no inline editor is open.
2. Add a regression test that verifies opening an inline editor enables those buttons.
3. Add a regression test that verifies browse-mode text selection switches the right sidebar to `text_card` and populates text controls from the hit text.
4. Run the targeted tests and confirm they fail for the intended reason.

### Task 2: Add failing tests for richer context menu behavior

**Files:**
- Modify: `test_scripts/test_fullscreen_transitions.py`
- Modify: `test_scripts/test_text_editing_gui_regressions.py`

**Steps:**
1. Add a regression test for browse-mode context menu entries when selected text exists.
2. Add a regression test for zoom actions in the context menu.
3. Add a regression test for “Edit Text” being present when right-clicking over editable text in browse mode.
4. Run the targeted tests and confirm they fail for the intended reason.

### Task 3: Implement text panel state synchronization

**Files:**
- Modify: `view/text_editing.py`
- Modify: `view/pdf_view.py`

**Steps:**
1. Add a single helper that updates the text-property panel enabled state from the actual editor lifecycle.
2. Call that helper when the editor opens, when it finalizes, and when browse-mode text selection changes.
3. Make browse-mode text selection show `text_card` with the selected text’s font/size when available, while keeping Apply/Cancel disabled until an editor exists.
4. Keep existing edit-mode behavior intact.

### Task 4: Implement expanded context menu actions

**Files:**
- Modify: `view/pdf_view.py`

**Steps:**
1. Refactor `_show_context_menu()` into a small action-builder flow.
2. Add safe browse/fullscreen actions first:
   - `Copy Selected Text`
   - `Select All` (selected text only, clipboard copy)
   - `Edit Text`
   - `Zoom In`
   - `Zoom Out`
   - `Fit to View`
   - `Exit Fullscreen` when applicable
3. Keep destructive actions out of this slice unless they can be wired safely from existing flows.
4. Preserve the existing rotate/fullscreen behaviors.

### Task 5: Verify and document results

**Files:**
- Modify: `test_scripts/test_outputs/fixes_results_report_2026-03-31.md`

**Steps:**
1. Run the targeted regression suite.
2. Run the broader Week 1–3 polish/safety suite to confirm no regressions.
3. Update the report with the new user-facing polish outcomes and any remaining known gaps.
