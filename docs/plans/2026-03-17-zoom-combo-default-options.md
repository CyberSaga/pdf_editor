# Zoom Combo Default Options Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure runtime zoom updates do not pollute the zoom preset dropdown while still showing the current zoom accurately.

**Architecture:** Keep the combo editable for display and manual entry, but treat the dropdown items as a fixed preset list. The only code change should be in the combo synchronization path so non-default values update the edit text without becoming new options.

**Tech Stack:** Python, PySide6, pytest

---

### Task 1: Capture the dropdown pollution bug in a failing test

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py` (later task)

**Step 1: Write the failing test**

Add a regression test that:

```python
defaults = [view.zoom_combo.itemText(i) for i in range(view.zoom_combo.count())]
controller.change_scale(view.current_page, 1.33)
_pump_events(50)
assert view.zoom_combo.currentText() == "133%"
assert [view.zoom_combo.itemText(i) for i in range(view.zoom_combo.count())] == defaults
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k zoom_combo -v`

Expected: FAIL because the current implementation appends `133%` into the combo items.

### Task 2: Implement the minimal combo-sync fix

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Write minimal implementation**

Change `_update_page_counter()` so it:

```python
self.zoom_combo.blockSignals(True)
self.zoom_combo.setCurrentText(text)
self.zoom_combo.blockSignals(False)
```

and does not call `addItem(text)` for runtime values.

**Step 2: Run targeted test to verify it passes**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k zoom_combo -v`

Expected: PASS

### Task 3: Final verification

**Files:**
- Verify only

**Step 1: Run focused regression coverage**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "zoom_combo or fit_to_view" -v`

Expected: PASS

**Step 2: Run full file verification**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -v`

Expected: PASS
