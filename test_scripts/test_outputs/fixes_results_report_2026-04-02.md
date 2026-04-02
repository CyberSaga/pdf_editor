# Fixes Results Report

**Date:** 2026-04-02  
**Baseline Commit:** `683a103d67e213083ad6043ecef9880555603158`  
**Scope:** April 2 Week 2 plan execution on the local manually-updated baseline, without pulling remote.

## 1. Summary

This round completed the planned Week 2 follow-up work on top of the post-April-1 parity baseline:

- kept the already-landed `size: float` edit typing fix in place
- decomposed `PDFModel.edit_text()` into phase helpers
- added explicit invalid-edit result handling instead of treating all edit attempts as success
- added user-facing error toasts for invalid edit targets
- added real undo/redo enabled-state feedback for both:
  - global document command history
  - local inline editor typing history

## 2. Implemented Changes

### `model/pdf_model.py`

- added `_EditTextResolveResult` to carry resolved edit target state across phases
- extracted `edit_text()` internals into:
  - `_resolve_edit_target(...)`
  - `_apply_redact_insert(...)`
  - `_verify_rebuild_edit(...)`
- kept the outer rollback/error handling in `edit_text()` intact
- changed `edit_text()` to return `EditTextResult`:
  - `SUCCESS`
  - `NO_CHANGE`
  - `TARGET_BLOCK_NOT_FOUND`
  - `TARGET_SPAN_NOT_FOUND`

### `model/edit_commands.py`

- added `EditTextResult` enum
- updated `EditTextCommand.execute()` to capture and expose model edit result
- prevented invalid/no-op edit attempts from being pushed onto undo history
- kept undo/redo stack semantics for real edits unchanged

### `controller/pdf_controller.py`

- mapped invalid edit results to user-facing messages
- reused the view toast overlay for edit failures
- stopped the edit flow early when `EditTextCommand` reports a non-success result
- updated undo/redo refresh to also propagate enabled/disabled state to the view
- hardened same-document cross-page move flow by checking the source delete result

### `view/pdf_view.py`

- extended `_show_toast(...)` with tone-aware styling:
  - success: existing dark gray
  - error: muted red
- added undo/redo action-state helpers:
  - `_set_undo_redo_action_state(...)`
  - `_refresh_undo_redo_action_state(...)`
  - `update_undo_redo_enabled(...)`
- initialized undo/redo actions to disabled on fresh view startup
- kept bottom-center toast placement unchanged

### `view/text_editing.py`

- when inline editor opens:
  - connects editor document undo/redo availability to view action-state refresh
  - switches toolbar buttons to local editor history state
- when inline editor closes:
  - restores action state from global command history

### Regression Tests

Added/updated tests in:

- `test_scripts/test_text_edit_manager_foundation.py`
- `test_scripts/test_text_editing_gui_regressions.py`

New coverage includes:

- controller propagates undo/redo enabled state from command stack
- controller shows toast feedback for invalid edit results
- view prefers local editor undo/redo state while inline editor is active

## 3. Verification Results

### Focused Week 2 regression slice

```powershell
python -m pytest test_scripts\test_text_edit_manager_foundation.py test_scripts\test_text_editing_gui_regressions.py -v
```

Result:

```text
36 passed, 7 warnings in 0.31s
```

### Broader GUI/startup/editor regression slice

```powershell
python -m pytest test_scripts\test_fullscreen_transitions.py test_scripts\test_main_startup_behavior.py test_scripts\test_text_edit_manager_foundation.py test_scripts\test_text_editing_gui_regressions.py -q
```

Result:

```text
61 passed, 59 warnings in 12.36s
```

### Short-term safety regression slice

```powershell
python -m pytest test_scripts\test_short_term_safety.py -q
```

Result:

```text
6 passed, 5 warnings in 0.40s
```

## 4. Status of This Round

| Area | Status | Notes |
|---|---|---|
| `edit_text()` phase extraction | PASS | structural refactor landed without regression |
| invalid edit result handling | PASS | now typed and surfaced instead of silently falling through |
| error toast feedback | PASS | muted-red bottom-center toast used for invalid edit targets |
| global undo/redo enabled state | PASS | follows `CommandManager.can_undo()` / `can_redo()` |
| local editor undo/redo enabled state | PASS | toolbar reflects inline editor document history while editing |
| bogus undo entries for failed/no-op edits | PASS | command manager skips recording when edit result is non-success |

## 5. Residual Notes

- A pre-existing Qt test warning remains in some suites:
  - disconnect warnings around `_schedule_outline_redraw` from `sig_viewport_changed` / `sig_scale_changed` in `view/pdf_view.py`
- These warnings do **not** fail the current regression suite and were not part of this execution batch.

## 6. Expected Next Move

With the April 2 Week 2 batch now green, the natural next options are:

1. clean up the pre-existing outline redraw disconnect warnings
2. export or update an architecture/session handoff report for this baseline
3. start the next planned slice beyond Week 2 using the April 2 plan set
