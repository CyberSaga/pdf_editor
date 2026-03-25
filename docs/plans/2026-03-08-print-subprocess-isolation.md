# Print Subprocess Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Isolate Windows print submission into a helper subprocess, detect stalled child execution, allow child-only termination, and keep the main window responsive through print completion or failure.

**Architecture:** The controller launches a `QProcess`-managed helper with an immutable job file, listens for JSON progress and heartbeat events, and drives progress dialog plus deferred-close state from child lifecycle. The helper performs watermark application and Windows Qt/GDI submission entirely out of process, so print-driver stalls cannot freeze the main app process.

**Tech Stack:** Python, PySide6 (`QProcess`, timers, dialogs), PyMuPDF, pytest

---

### Task 1: Add failing controller regressions for subprocess lifecycle

**Files:**
- Modify: `test_scripts/test_print_controller_flow.py`

**Step 1: Write the failing test**

Add regressions for:

- print starts a helper-backed submission path without blocking `print_document()`
- close is deferred while the helper is active
- helper silence moves UI into a stalled-print state
- terminating the stalled helper restores normal UI state without closing the window

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: FAIL because the controller only knows about the in-process worker path today.

**Step 3: Write minimal implementation**

Add only the controller seams needed for a process-backed print session and watchdog.

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: PASS

### Task 2: Add failing tests for helper event protocol

**Files:**
- Create: `test_scripts/test_print_subprocess_runner.py`
- Create or modify: `src/printing/subprocess_runner.py`
- Create or modify: `src/printing/helper_protocol.py`

**Step 1: Write the failing test**

Add tests for:

- job file serialization
- newline-delimited JSON event parsing
- helper exit and error mapping into controller-friendly results

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_subprocess_runner.py -q`
Expected: FAIL because the subprocess protocol layer does not exist yet.

**Step 3: Write minimal implementation**

Create the helper protocol and runner abstractions with only the behavior needed by the tests.

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_subprocess_runner.py -q`
Expected: PASS

### Task 3: Add failing tests for helper main entrypoint

**Files:**
- Create: `test_scripts/test_print_subprocess_helper.py`
- Create: `src/printing/helper_main.py`

**Step 1: Write the failing test**

Add tests for:

- helper loads the job file
- helper emits `started`, `progress`, and `succeeded`
- helper maps exceptions to `failed`

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_subprocess_helper.py -q`
Expected: FAIL because no helper entrypoint exists yet.

**Step 3: Write minimal implementation**

Implement the helper CLI entrypoint and event emission.

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_subprocess_helper.py -q`
Expected: PASS

### Task 4: Wire Windows print dispatcher to subprocess isolation

**Files:**
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Modify: `src/printing/dispatcher.py`
- Modify: `src/printing/__init__.py`
- Modify: `src/printing/qt_bridge.py`
- Modify: `src/printing/platforms/win_driver.py`

**Step 1: Write the failing test**

Extend controller tests to assert that the main process responds to helper progress, stall, terminate, and completion events.

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: FAIL because lifecycle wiring is still incomplete.

**Step 3: Write minimal implementation**

Add:

- controller-owned `QProcess` session handling
- watchdog timer and silent-child detection
- terminate-child action and cleanup
- subprocess-backed Windows dispatch path

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_print_controller_flow.py -q`
Expected: PASS

### Task 5: Verify focused and broader behavior

**Files:**
- No code changes unless verification exposes gaps

**Step 1: Run focused regressions**

Run:
- `python -m pytest test_scripts/test_print_controller_flow.py -q`
- `python -m pytest test_scripts/test_print_subprocess_runner.py -q`
- `python -m pytest test_scripts/test_print_subprocess_helper.py -q`

**Step 2: Run broader verification**

Run: `python -m pytest test_scripts -q`

**Step 3: Confirm exact status**

Report the exact pass/fail counts and any remaining unrelated fixture failures before claiming completion.
