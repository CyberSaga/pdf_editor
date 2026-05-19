# Phase 1 Item 1 Planning and Execution Handoff

## Summary
- Treat the current `docs/5-phases-of-to_Update.md` file as backlog sequencing only, not an executable implementation plan.
- Start with a clean isolated workspace in `.worktrees/` because the main worktree is dirty and the project already ignores `.worktrees/`.
- Create a dedicated child plan for Phase 1 Item 1 only: “printing must not mutate printer preferences after print.”
- Base the child plan on the existing printing architecture and tests, with the first implementation batch focused on reproducing the print-side-effect bug, not refactoring layout/orientation logic.

## Key Changes
- Worktree setup:
  - Use `.worktrees/` as the worktree root.
  - Default branch name: `codex/print-prefs-phase1-item1`.
  - Verify clean baseline in the worktree before any code changes with focused print tests first, then broader validation only if the focused baseline is already green.
- Child plan to create:
  - Save as `docs/plans/2026-04-22-print-preferences-after-print.md`.
  - Use the repo’s required plan header and explicitly hand off to `executing-plans`.
  - Scope only the print-preference mutation bug; do not fold in auto-rotate or source-paper-size work.
- Implementation target inside the child plan:
  - Clarify the bug boundary as “unexpected print-job side effects” and not “user-confirmed native property dialog persistence.”
  - Investigate the submission path around `src/printing/dispatcher.py`, `src/printing/platforms/win_driver.py`, and controller print flow to find where job-time settings leak into persisted defaults.
  - Prefer a narrow fix that keeps native properties dialog behavior intact while preventing print submission from rewriting driver/system defaults after a normal print.
- Execution batching:
  - Batch 1: add red tests for the unwanted preference mutation path, run them red, and document the exact failing behavior.
  - Batch 2: implement the smallest fix that preserves intended native dialog persistence and rerun the focused print suites.
  - Batch 3: run broader print/controller validation, then update `docs/PITFALLS.md` and `TODOS.md`; update `docs/ARCHITECTURE.md` only if responsibilities or contracts change.

## Test Plan
- Add or extend focused regression coverage near [test_print_dialog_properties_button.py](</C:/Users/jiang/Documents/python programs/pdf_editor/test_scripts/test_print_dialog_properties_button.py>) for the distinction between:
  - native properties dialog changes that are allowed to persist
  - ordinary print submission that must not persist preference changes
- Run red-light-first commands in the child plan with exact test selectors, starting from the focused print suites before any broad `pytest`.
- Keep the likely validation set centered on:
  - [test_print_dialog_properties_button.py](</C:/Users/jiang/Documents/python programs/pdf_editor/test_scripts/test_print_dialog_properties_button.py>)
  - [test_print_controller_flow.py](</C:/Users/jiang/Documents/python programs/pdf_editor/test_scripts/test_print_controller_flow.py>)
  - any new focused regression file if the current tests cannot express the print-submission side effect cleanly
- Finish with `ruff check .` and the relevant print-focused pytest slice; only run full `pytest` if the child plan confirms the baseline is stable enough to make that useful.

## Assumptions
- The next actionable unit is Phase 1 Item 1 only, because your earlier choice was the “full workflow” for that item rather than the whole print phase.
- `.worktrees/` is the correct location because it already exists and is ignored in `.gitignore`.
- `main` should remain untouched for implementation; all work happens in the new worktree branch.
- The existing behavior in `win_driver.open_printer_properties(...)` that persists user-confirmed native dialog changes is intentional and should not be “fixed away.”
- The child implementation plan should be written before any code execution, because the current document is explicitly sequencing-only.
