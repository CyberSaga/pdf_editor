# Fit-To-View Zoom Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the `適應畫面` action reuse the normal zoom pipeline so the recorded zoom state always matches the actual fitted view.

**Architecture:** Keep `_fit_to_view()` as a UI event entry point, but remove its direct `fitInView(...)` transform mutation. Compute the target contain scale in the view, then hand off to `controller.change_scale(...)` through `sig_scale_changed(...)` so zoom persistence, UI text, and re-rendering stay on one code path.

**Tech Stack:** Python, PySide6, PyMuPDF, pytest

---

### Task 1: Lock in the new fit-to-view contract with a failing test

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py` (later task)
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\controller\pdf_controller.py` (verification target only)

**Step 1: Write the failing test**

Add or replace the fit-to-view regression test so it verifies all of the following after `view._fit_to_view()`:

```python
expected_scale = view.compute_contain_scale_for_page(view.current_page)

view._fit_to_view()
_pump_events(50)

assert view.scale == pytest.approx(expected_scale, rel=1e-3)
assert view.zoom_combo.currentText() == f"{int(round(expected_scale * 100))}%"
```

Keep the current-page targeting assertion so the test still proves the fit action uses the active page, not the whole scene.

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_multi_tab_plan.py -k fit_to_view -v`

Expected: FAIL because the current implementation changes the visible transform without synchronizing `view.scale` or the zoom combo.

**Step 3: Commit**

Do not commit yet. Continue once the failure is confirmed.

### Task 2: Route the fit button through the shared zoom pipeline

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Write minimal implementation**

Update `_fit_to_view()` so it:

```python
if not target_rect or not target_rect.isValid():
    return

scale = self.compute_contain_scale_for_page(self.current_page)
self.sig_scale_changed.emit(self.current_page, scale)
```

Do not call `self.graphics_view.fitInView(...)` inside this button path anymore.

**Step 2: Run targeted test to verify it passes**

Run: `pytest test_scripts/test_multi_tab_plan.py -k fit_to_view -v`

Expected: PASS

**Step 3: Sanity-check for code duplication**

Confirm `_fit_to_view()` remains only a thin event handler and does not introduce duplicate zoom-state update logic.

### Task 3: Verify the shared zoom path still reflects the new scale in the UI

**Files:**
- Verify: `C:\Users\jiang\Documents\python programs\pdf_editor\controller\pdf_controller.py`
- Verify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Inspect the existing shared path**

Confirm `controller.change_scale(...)` still:

```python
self.view.scale = scale
self._get_ui_state(sid).scale = scale
self._rebuild_continuous_scene(page_idx)
```

And confirm the view rebuild path still updates the zoom combo via `_update_page_counter()`.

**Step 2: Run a broader regression slice**

Run: `pytest test_scripts/test_multi_tab_plan.py -k "fit_to_view or fullscreen or zoom or mode_checked_state_sync" -v`

Expected: PASS

**Step 3: Commit**

```bash
git add test_scripts/test_multi_tab_plan.py view/pdf_view.py docs/plans/2026-03-17-fit-to-view-zoom-sync-design.md docs/plans/2026-03-17-fit-to-view-zoom-sync.md
git commit -m "fix: sync fit-to-view zoom state"
```

### Task 4: Final verification before completion

**Files:**
- Verify only

**Step 1: Run the focused regression command**

Run: `pytest test_scripts/test_multi_tab_plan.py -k fit_to_view -v`

Expected: PASS

**Step 2: Run the broader safety check**

Run: `pytest test_scripts/test_multi_tab_plan.py -v`

Expected: PASS, or if unrelated failures already exist, document the exact failing tests and keep the fit-to-view regression green.

**Step 3: Review diff**

Run: `git diff -- view/pdf_view.py test_scripts/test_multi_tab_plan.py docs/plans/2026-03-17-fit-to-view-zoom-sync-design.md docs/plans/2026-03-17-fit-to-view-zoom-sync.md`

Expected: Only the fit-to-view button path, associated regression test, and planning docs changed.
