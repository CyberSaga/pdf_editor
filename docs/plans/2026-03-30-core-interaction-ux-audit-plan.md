# Core Interaction UX Audit Plan

## Summary

This plan defines a two-phase UX audit for the PDF editor's core interactions.

- Phase 1 is an internal smoothness audit on this machine.
- Phase 2 is a true Acrobat comparison on a machine where Adobe Acrobat is available.

The first implementation slice uses a thin harness and a binary checklist.
It does not claim Acrobat parity locally.

## What Already Exists

- Existing GUI audit reports already cover key text-editing failures and methodology gaps:
  - `GUI_test_report_round2.md`
  - `docs/plans/2026-03-29-gui-validation-round3.md`
  - `docs/plans/2026-03-29-ceo-review-round3-audit.md`
- Existing docs already define the expected keyboard, focus, and mode behavior:
  - `docs/FEATURES.md`
  - `docs/ARCHITECTURE.md`
- Existing tests already validate several high-risk edit flows:
  - `test_scripts/test_text_editing_gui_regressions.py`
  - `test_scripts/test_cross_page_text_move.py`
  - `test_scripts/test_drag_move.py`

## Scope

Phase 1 covers the core interaction spine only:

- open, drag-drop, tab switching
- scroll, jump, zoom, fit-to-view
- text selection and copy
- existing-text edit and add-text
- undo, redo, save, close-with-dirty-prompt
- recovery flows such as cancel, click-away, Escape, and boundary drag handling

Out of scope for this first plan:

- print
- merge
- optimizer
- OCR
- whole-app feature parity
- weighted UX scoring
- heavy desktop automation

## Fixture Matrix

The first audit requires exactly three fixtures:

- `test_files/1.pdf` as the small clean fixture
- `test_files/TIA-942-B-2017 Rev Full.pdf` as the long real-world fixture
- `test_files/excel_table.pdf` as the edge-case mixed-layout fixture

## Execution Model

```text
Phase 1
  automated internal checks
  + manual screen-operation checks
  + PDF-result validation
  -> PASS / FAIL / BLOCKED

Phase 2
  same protocol on Acrobat
  -> only phase allowed to justify "Acrobat-level"
```

The thin harness is implemented by `test_scripts/core_interaction_audit.py`.
It reuses existing pytest coverage for automated checks and emits blocked entries for:

- manual operator scenarios
- Acrobat-only parity scenarios

The harness also writes:

- a sanitized audit report with repo-relative fixture paths
- a manual operator checklist for the blocked keyboard/mouse scenarios

## Scenario Groups

- Open and navigation
- Focus and selection
- Edit and recovery
- Persistence confidence

Each scenario must define:

- preconditions
- exact mouse or keyboard sequence
- expected visible result
- expected saved-PDF result when the document changes
- binary pass or fail criteria

## Failure Modes To Keep Visible

- synthetic key delivery differs from real keyboard delivery
- a visual pass hides wrong persisted PDF state
- in-editor undo leaks into document undo
- single-fixture bias causes false confidence
- state leaks between sequential scenarios because the fixture is not reloaded

If a scenario can fail silently and has neither validation nor explicit error handling, it should be treated as a critical gap.

## Current Constraint

Adobe Acrobat is not installed on this device, so all Acrobat comparison scenarios remain blocked locally.
That blocker is tracked in `TODOS.md`.
