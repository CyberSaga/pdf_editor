# Text Editing GUI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the validated inline text-editing GUI regressions without changing the existing controller/model command architecture.

**Architecture:** Keep `EditTextCommand` as the undo boundary and correct the view-layer editor lifecycle, coordinate mapping, and shortcut forwarding that feed into it. Add narrow regressions around new helpers and state transitions, then verify with focused Qt tests and existing integration coverage.

**Tech Stack:** Python, PySide6, PyMuPDF (`fitz`), pytest-style tests in `test_scripts`

---

### Task 1: Add failing regressions for no-op finalize and drag/page helpers

**Files:**
- Create: `test_scripts/test_text_editing_gui_regressions.py`
- Modify: `view/pdf_view.py`

**Step 1: Write the failing test**

Add tests that:
- verify text normalization treats ligatures/whitespace-only differences as unchanged,
- verify scene-Y-to-page resolution returns the destination page,
- verify the editor shortcut filter forwards `Ctrl+S`, `Ctrl+Z`, `Ctrl+Y`, and `Ctrl+Shift+Z`.

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: FAIL because the helper methods/filter do not exist yet or existing behavior differs.

**Step 3: Write minimal implementation**

Implement helper functions and the shortcut forwarder in `view/pdf_view.py` only as far as required for the tests.

**Step 4: Run test to verify it passes**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: PASS

### Task 2: Fix finalize no-op detection and drag/page state transitions

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_text_editing_gui_regressions.py`

**Step 1: Write the failing test**

Add/extend tests to cover:
- unchanged finalize skipping `sig_edit_text`,
- drag threshold allowing small intentional movement,
- page index updates when an editor midpoint crosses to the next page.

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: FAIL on no-op finalize and drag/page assertions.

**Step 3: Write minimal implementation**

Update finalize comparison logic, reduce the drag threshold, and resolve `_editing_page_idx` dynamically from scene position before clamping and release-time rect calculation.

**Step 4: Run test to verify it passes**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: PASS

### Task 3: Fix editor closure and focused shortcuts

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_text_editing_gui_regressions.py`

**Step 1: Write the failing test**

Add/extend tests that verify:
- `Escape` sets discard and closes through the existing escape path,
- click-outside finalize path remains reachable,
- focused editor key handling forwards save/undo/redo shortcuts.

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: FAIL on one or more editor-interaction assertions.

**Step 3: Write minimal implementation**

Install an editor event filter or equivalent forwarding layer, and keep discard/finalize behavior within the existing edit state machine.

**Step 4: Run test to verify it passes**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: PASS

### Task 4: Run focused regression verification

**Files:**
- Test: `test_scripts/test_text_editing_gui_regressions.py`
- Test: `test_scripts/test_empty_text_edit.py`
- Test: `test_scripts/test_track_ab_5scenarios.py`

**Step 1: Run the focused Qt regressions**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

**Step 2: Run existing text-edit regressions**

Run: `pytest test_scripts/test_empty_text_edit.py -q`

**Step 3: Run the broader Track A/B integration script**

Run: `python test_scripts/test_track_ab_5scenarios.py`

**Step 4: Review failures and stop if any regression remains**

Expected: focused regressions pass; if Track A/B script fails, investigate whether it is pre-existing or introduced by the GUI-state fixes.
