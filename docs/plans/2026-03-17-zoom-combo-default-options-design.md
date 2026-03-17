# Zoom Combo Default Options Design

**Date:** 2026-03-17

**Goal:** Keep the zoom combo box displaying the current zoom percentage accurately without adding non-default historical values into the dropdown list.

## Problem

- The zoom combo is editable and is also used to reflect the current zoom state.
- `_update_page_counter()` currently appends any unseen zoom percentage into the combo items.
- After fit-to-view or arbitrary manual zoom changes, values like `83%` or `127%` become permanent dropdown options.
- This pollutes the menu and changes the intended preset-only affordance.

## Scope

- Keep the zoom combo editable so the current zoom can still be shown and manually entered.
- Preserve the preset dropdown options: `50%`, `75%`, `100%`, `125%`, `150%`, `200%`.
- Stop persisting non-default zoom values into the combo item list.

## Architecture

- `view/pdf_view.py`
  - Keep the preset options populated at construction time.
  - Change `_update_page_counter()` so it updates the combo's displayed text only.
  - Do not call `addItem(...)` for runtime zoom values.
- `test_scripts/test_multi_tab_plan.py`
  - Add regression coverage that a non-default zoom value updates the visible combo text but does not alter the preset dropdown contents.

## Design Decision

- The combo box serves two roles:
  - dropdown of preset zoom values
  - editable display of the current zoom
- Those roles should stay separate.
- The displayed text may be any valid current zoom value, but the dropdown list itself should remain a stable preset list.

## Expected User Outcome

- The current zoom still shows the exact current percentage.
- Opening the dropdown still shows only the preset zoom values.
- Repeated fit/manual zoom actions no longer accumulate extra historical entries.

## Testing Strategy

- Verify that changing to a non-default zoom updates `zoom_combo.currentText()`.
- Verify that `zoom_combo.count()` and item texts remain the preset set.
