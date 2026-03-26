# Text Editing Undo/Focus UX Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make inline editor undo/redo behave like Acrobat by keeping those shortcuts local to the focused editor and preventing accidental finalize/commit.

**Architecture:** Keep the existing inline editor and PDF command stack separation. Update `view/pdf_view.py` so editor-focused undo/redo stays inside `QTextEdit`, and extend the focused regression tests in `test_scripts/test_text_editing_gui_regressions.py` to lock in the new shortcut contract.

**Tech Stack:** Python, PySide6, pytest, PyMuPDF

---

### Task 1: Add failing shortcut ownership regressions

**Files:**
- Modify: `test_scripts/test_text_editing_gui_regressions.py`
- Modify: `view/pdf_view.py`

**Step 1: Write the failing test**

Add tests that verify:
- `Ctrl+Z` calls editor-local `undo()` when local history exists.
- `Ctrl+Y` / `Ctrl+Shift+Z` call editor-local `redo()` when local redo history exists.
- window `_action_undo` / `_action_redo` are not triggered in those cases.

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: FAIL because the current shortcut forwarder still routes undo/redo to window actions.

**Step 3: Write minimal implementation**

Update `_EditorShortcutForwarder.eventFilter()` to inspect the focused editor document and invoke widget-local undo/redo first.

**Step 4: Run test to verify it passes**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: PASS for the new local-history tests.

### Task 2: Add failing no-history and no-finalize regressions

**Files:**
- Modify: `test_scripts/test_text_editing_gui_regressions.py`
- Modify: `view/pdf_view.py`

**Step 1: Write the failing test**

Add tests that verify:
- `Ctrl+Z` and redo shortcuts return handled when local history is empty.
- no window action is triggered.
- the editor remains active and no finalize helper is invoked.

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: FAIL because current behavior falls through to window undo/redo.

**Step 3: Write minimal implementation**

Consume editor-focused undo/redo shortcuts as no-ops when no local history is available.

**Step 4: Run test to verify it passes**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py -q`

Expected: PASS

### Task 3: Preserve save forwarding and verify existing edit regressions

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_text_editing_gui_regressions.py`
- Test: `test_scripts/test_empty_text_edit.py`

**Step 1: Write/keep the save-forwarding assertion**

Ensure the shortcut tests still verify `Ctrl+S` forwards to the window save action.

**Step 2: Run focused tests**

Run: `pytest test_scripts/test_text_editing_gui_regressions.py test_scripts/test_empty_text_edit.py -q`

Expected: PASS

**Step 3: Run broader Track A/B verification**

Run: `python test_scripts/test_track_ab_5scenarios.py`

Expected: PASS with the existing real-PDF skip if the sample is unavailable.

**Step 4: Commit**

```bash
git add view/pdf_view.py test_scripts/test_text_editing_gui_regressions.py docs/plans/2026-03-26-text-editing-undo-focus-design.md docs/plans/2026-03-26-text-editing-undo-focus-implementation.md
git commit -m "fix: keep editor undo local"
```
