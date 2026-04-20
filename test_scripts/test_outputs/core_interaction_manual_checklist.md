# Core Interaction Manual Operator Checklist

Use this checklist for the Phase 1 manual screen-operation pass.
Record timings, hesitation points, visible glitches, and whether the persisted PDF matches the visible result.

## manual.open_and_navigation - Open, tab-switch, scroll, jump, and zoom remain smooth

- Fixtures: `test_files/1.pdf`, `test_files/TIA-942-B-2017 Rev Full.pdf`
- Mouse/Keyboard Steps: Launch the app and open `test_files/1.pdf`. Use mouse navigation to switch tabs, scroll, and jump between pages. Use zoom in, zoom out, and fit-to-view, then continue scrolling immediately. Repeat the same flow on `test_files/TIA-942-B-2017 Rev Full.pdf` and note hesitation, focus loss, or visible jank.
- Expected Visible Result: Navigation remains stable with no surprise focus jumps, stale page counter, or obvious scroll/zoom hitching.
- Expected Persisted Result: N/A for this scenario.

## manual.selection_save_close - Selection, copy, save, close-with-dirty-prompt, and reopen confidence

- Fixtures: `test_files/1.pdf`, `test_files/excel_table.pdf`
- Mouse/Keyboard Steps: Open `test_files/1.pdf` and select visible text with the mouse. Use keyboard copy, start a text edit, then trigger save and close flows with the keyboard. Confirm the dirty prompt appears with the expected options, save the document, reopen it, and verify the edited result. Repeat a shorter version on `test_files/excel_table.pdf` to confirm the same persistence behavior on the edge-case fixture.
- Expected Visible Result: Selection, save, dirty prompt, reopen, and recovery flows feel predictable and do not trap focus.
- Expected Persisted Result: Saved output reopens with the intended text change and without ghost edits or reverted state.
