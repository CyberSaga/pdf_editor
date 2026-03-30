# Core Interaction UX Audit Report

## Summary
- PASS: 4
- FAIL: 0
- BLOCKED: 3

## Fixture Matrix
- `small_clean`: `test_files/1.pdf` - Small clean fixture for deterministic reruns.
- `long_real_world`: `test_files/TIA-942-B-2017 Rev Full.pdf` - Long real-world fixture for navigation and sustained interaction checks.
- `edge_case`: `test_files/excel_table.pdf` - Mixed-layout fixture for table-like text/layout behavior.

## Scenario Results
- `internal.noop_finalize` | PASS | No-op finalize should not emit a ghost edit | Automated check passed via `test_scripts/test_text_editing_gui_regressions.py::test_finalize_skips_emit_for_normalized_noop_edit`.
- `internal.escape_discard` | PASS | Escape path marks the active editor as discard-before-finalize | Automated check passed via `test_scripts/test_text_editing_gui_regressions.py::test_escape_marks_current_editor_as_discard_before_finalize`.
- `internal.local_undo_redo` | PASS | Local editor undo/redo stays local while the editor is open | Automated check passed via `test_scripts/test_text_editing_gui_regressions.py::test_editor_shortcut_forwarder_uses_local_undo_redo_history`.
- `internal.cross_page_move` | PASS | Cross-page move writes once and remains undoable | Automated check passed via `test_scripts/test_cross_page_text_move.py::test_move_text_across_pages_records_single_snapshot_command_and_undoes`.
- `manual.open_and_navigation` | BLOCKED | Open, tab-switch, scroll, jump, and zoom remain smooth | Requires manual screen operation and timing notes.
- `manual.selection_save_close` | BLOCKED | Selection, copy, save, close-with-dirty-prompt, and reopen confidence | Requires manual keyboard/mouse validation and post-save inspection.
- `acrobat.core_parity` | BLOCKED | Run the same core interaction protocol against Acrobat | Blocked until a machine with Adobe Acrobat is available.

## Notes
- `BLOCKED` is expected for manual and Acrobat-only scenarios in the thin-harness phase.
- Acrobat parity remains blocked until a machine with Acrobat is available.