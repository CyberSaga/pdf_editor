# Fix Plan: Codex Week 2 Implementation Bugs

## Context

Codex implemented the Week 2 Acrobat-parity sprint (4 steps). Review found 3 issues to fix in `model/edit_commands.py`. All other changes are correct.

---

## Fix 1: Misplaced `self.result` initialization (BUG)

**File:** `model/edit_commands.py:50`

`self.result: EditTextResult = EditTextResult.SUCCESS` is indented inside the abstract `undo()` method body of `EditCommand` (line 50). It should be in `EditTextCommand.__init__` so it's initialized before `execute()` runs.

**Action:**
- Remove line 50 (`self.result: EditTextResult = EditTextResult.SUCCESS`) from inside `EditCommand.undo()`
- Add `self.result: EditTextResult = EditTextResult.SUCCESS` to `EditTextCommand.__init__` (after `self._reflow_fn` assignment, around line 145)

## Fix 2: Abstract `execute()` return type mismatch

**File:** `model/edit_commands.py:41`

`EditCommand.execute()` declares `-> bool` but `SnapshotCommand.execute()` (line 356) and `AddTextboxCommand.execute()` (line 254) return `None`. `CommandManager.execute()` checks `if executed is False:` which works by accident (`None is not False`) but violates the abstract contract.

**Action:**
- Revert abstract signature back to `-> None` (line 41)
- Keep `EditTextCommand.execute() -> bool` as a concrete override — it's the only command that needs conditional recording
- `CommandManager.execute()` already uses `if executed is False:` which correctly distinguishes `None` (other commands) from `False` (failed edit). No change needed there.

## Fix 3: Stripped comments in extracted helpers (MINOR)

The phase extraction removed inline engineering comments that explained *why* strategies exist. This is a documentation loss but not a functional bug. **Skip for now** — not worth the churn.

---

## Files to modify

1. `model/edit_commands.py` — fixes 1 and 2

## Verification

```
python -m pytest test_scripts/test_text_edit_manager_foundation.py test_scripts/test_text_editing_gui_regressions.py -v
```

Expected: all 36 tests pass, zero regressions.
