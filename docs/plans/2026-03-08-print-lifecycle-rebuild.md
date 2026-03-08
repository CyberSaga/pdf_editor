# Print Lifecycle Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move print snapshot generation and submission off the UI thread, defer app close until print submission finishes, and preserve the regular status bar state.

**Architecture:** The controller captures immutable print job input on the UI thread, passes it to a `QThread` worker for snapshot generation and print submission, and manages a deferred-close state that auto-closes the window only after cleanup completes. The view exposes a status-bar override so print-specific messages do not destroy the normal document state message.

**Tech Stack:** Python, PySide6, PyMuPDF, pytest

---

### Task 1: Add failing print lifecycle regressions

**Files:**
- Modify: `test_scripts/test_print_controller_flow.py`

**Step 1: Write the failing test**

Add tests for:

- async snapshot generation that blocks in the worker without blocking `print_document()`
- close-during-print defers shutdown and later auto-closes
- status bar restoration after print cleanup

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: FAIL because print submission is still synchronous and close handling is not print-aware.

**Step 3: Write minimal implementation**

Implement only enough controller/view/model support to satisfy the new tests.

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: PASS

### Task 2: Build immutable print job capture and worker pipeline

**Files:**
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Modify: `model/tools/manager.py`
- Modify: `model/tools/watermark_tool.py`

**Step 1: Write the failing test**

Extend the regression test so the worker must use copied watermark/input data rather than the live document.

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: FAIL because worker support does not exist yet.

**Step 3: Write minimal implementation**

Add:

- immutable print job capture from model/controller
- helper(s) to render a print snapshot from bytes plus copied watermark data
- a `QThread` worker that emits progress/success/failure signals

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: PASS

### Task 3: Add deferred close and status override behavior

**Files:**
- Modify: `controller/pdf_controller.py`
- Modify: `view/pdf_view.py`

**Step 1: Write the failing test**

Add assertions for:

- close request ignored while print worker is active
- status message changes to `正在完成最後工作，請稍候...`
- second close is triggered automatically after print completion
- normal status bar message returns after cleanup

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: FAIL because close and status bar behavior still uses the old synchronous flow.

**Step 3: Write minimal implementation**

Add:

- deferred-close controller state
- guarded success/error UI during shutdown
- view status-bar override API used by print lifecycle cleanup

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: PASS

### Task 4: Verify focused regression coverage

**Files:**
- No code changes required unless verification exposes gaps

**Step 1: Run focused verification**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`

**Step 2: Run broader print-adjacent verification**

Run: `python -m pytest test_scripts -q`

**Step 3: Confirm results**

Record the exact pass/fail status before claiming completion.
