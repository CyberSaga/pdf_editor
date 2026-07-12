# Milestone 2 Defect Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use systematic-debugging and execute this plan task-by-task.

**Goal:** Correct the three independently reproduced Milestone 2 defects without changing unrelated behavior.

**Architecture:** Keep app-image identity placement-based by validating xref/digest candidates against marker geometry. When pruning inherited PDF resources, inspect only pages whose effective name binding points to the target resource. Make the print runner's terminal path idempotent so `FailedToStart` performs the same cleanup and coordinator notification as `finished`.

**Tech Stack:** Python 3.10, PyMuPDF, PySide6 `QProcess`, pytest.

---

### Task 1: Shared-xref stale marker safety

**Files:**
- Modify: `model/pdf_object_ops.py`
- Test: `test_scripts/test_image_objects_model.py`

1. Add a regression test with two separated app images created from identical bytes.
2. Remove the first placement while leaving both markers, then delete the stale first marker.
3. Run the test and confirm that current code wrongly deletes the surviving placement.
4. Restrict the recorded-xref/digest fast path to candidates matching marker geometry and rotation; return no resolution when none match.
5. Run the new test plus existing shared-xref, ambiguous, orphan, move, and rotate tests.

### Task 2: Inherited-resource pruning

**Files:**
- Modify: `model/pdf_object_ops.py`
- Test: `test_scripts/test_image_objects_model.py`

1. Add a two-page PDF fixture where page 1 inherits `/fzImg0` and page 2 owns a different `/fzImg0` binding.
2. Delete page 1's app image, save with `garbage=4`, and assert its resource/image stream is absent after reopen.
3. Run the test and confirm the unrelated page-2 token currently prevents pruning.
4. Scan only content streams whose effective `Resources/XObject/<name>` binding resolves to the target owner and image xref.
5. Run inherited-resource, prefix-collision, shared-xref, and secure-delete tests.

### Task 3: Print helper startup cleanup

**Files:**
- Modify: `src/printing/subprocess_runner.py`
- Test: `test_scripts/test_print_subprocess_runner.py`

1. Add a process fake that emits `FailedToStart` without emitting `finished`, matching real `QProcess` behavior.
2. Assert one failure, one runner `finished` notification, stopped watchdog, cleared process/PDF payload, and removed work directory.
3. Run the test and confirm the runner currently remains active and retains the payload.
4. Route terminal process errors through a single idempotent finalization helper shared with `_on_finished`; preserve normal crash/finish behavior without duplicate signals.
5. Run subprocess-runner, fileless-print, and print-controller tests.

### Task 4: Verification

**Files:**
- Update only documentation required to record the completed fixes, if needed.

1. Run the focused regression selections.
2. Run the complete pytest suite with `.venv\\Scripts\\python.exe -m pytest -q`.
3. Run `ruff check .`, `mypy model/ utils/`, and all import-linter contracts.
4. Inspect `git diff --check` and the final scoped diff.

## Outcome

Completed 2026-07-12. All three regressions failed before their production fixes and pass afterward.
Focused verification: 84 passed. Full verification: 1636 passed, 21 skipped. Ruff, mypy, all four
import-linter contracts, and `git diff --check` pass. The pre-task workspace state is preserved in the
named Git stash `pre-m2-defect-fixes workspace save 2026-07-12` (`stash@{0}` at completion time).
