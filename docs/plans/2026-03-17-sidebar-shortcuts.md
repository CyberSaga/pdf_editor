# Sidebar Shortcut Toggle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add keyboard shortcuts to toggle the left and right sidebars while preserving usable widths, restoring focus intelligently, and keeping existing fullscreen and search behavior correct.

**Architecture:** Keep all sidebar visibility, width memory, splitter sizing, and focus transitions inside `PDFView`, which already owns the sidebars, shortcuts, and fullscreen chrome state. Reuse existing left-sidebar entry points and page-canvas focus helpers instead of introducing controller state or a new layout abstraction.

**Tech Stack:** Python, PySide6, PyMuPDF, pytest

---

## Step 0: Scope Challenge

### What already exists

- `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py:887-927` already creates and owns `main_splitter`, `left_sidebar_widget`, and `right_sidebar`.
- `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py:1246-1262` already installs window-wide `QShortcut` instances with `WidgetWithChildrenShortcut`.
- `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py:1530-1543` already centralizes left-sidebar tab switching for thumbnails, search, annotations, and watermarks.
- `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py:1938-1940` already has `_focus_page_canvas()`, which should remain the only “return focus to PDF area” path.
- `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py:1112-1148` already snapshots and restores sidebar visibility for fullscreen transitions.

### Minimum viable change

- Modify exactly two files:
  - `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`
  - `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`
- Add only view-local helpers and shortcut wiring.
- Do not add new controller/model/session state.
- Do not add toolbar buttons, settings persistence, or new classes.

### Complexity check

- Target: 2 touched files, 0 new classes, 4-6 small helper methods maximum.
- If implementation expands beyond that, stop and collapse back into existing `PDFView` flows.

## Combined Engineering Review (SMALL CHANGE)

### Architecture Review: single most important issue

- **Issue:** Sidebar visibility must remain owned by `PDFView`; adding controller/session state would create a parallel layout model that fights fullscreen restore.
- **Recommendation:** Keep width memory and toggle behavior as transient `PDFView` state only.

### Code Quality Review: single most important issue

- **Issue:** Left-sidebar entry points currently assume the panel is visible, so `Ctrl+F` or toolbar tab switches could silently target a hidden panel.
- **Recommendation:** Add one shared `ensure_left_sidebar_visible(...)` path and route existing left-tab methods through it to stay DRY.

### Test Review: single most important issue

- **Issue:** This feature is easy to “look correct” while still failing on focus return, hidden-state restore, or undersized remembered widths.
- **Recommendation:** Lock in behavior with targeted UI tests for keyboard shortcuts, focus movement, width fallback, and fullscreen state restore.

### Performance Review: single most important issue

- **Issue:** Repeated hide/show relayout work can become noisy if the implementation recomputes geometry in multiple places or uses timers unnecessarily.
- **Recommendation:** Use one constant-time splitter size update per toggle and reuse current sizes instead of rebuilding layout or emitting extra signals.

## Test Diagram

```text
New UX / codepaths
==================

Ctrl+Alt+L
  -> toggle_left_sidebar()
     -> visible?
        -> yes: remember left width -> hide left -> focus PDF canvas
        -> no: resolve width (remembered or default 260 when <50)
             -> show left -> apply splitter sizes
             -> current tab == Search?
                -> yes: focus search_input
                -> no: focus left tab bar

Ctrl+Alt+R
  -> toggle_right_sidebar()
     -> visible?
        -> yes: remember right width -> hide right -> focus PDF canvas
        -> no: resolve width (remembered or default 280 when <50)
             -> show right -> apply splitter sizes
             -> focus first widget in current property card
                -> fallback: focus right sidebar container

Existing left-sidebar entry points
  -> _show_thumbnails_tab()
  -> _show_search_tab()
  -> _show_annotations_tab()
  -> _show_watermarks_tab()
     -> ensure_left_sidebar_visible()
     -> switch tab
     -> search path still focuses search_input

Fullscreen
  -> enter_fullscreen_ui()
     -> snapshot current visibility booleans
  -> exit_fullscreen_ui()
     -> restore hidden/visible state chosen before fullscreen
```

## Failure Modes

| Codepath | Realistic failure | Test coverage in this plan | Error handling / fallback | User impact |
| --- | --- | --- | --- | --- |
| Left reopen after bad width memory | Remembered width is `< 50`, panel reopens as an unusable sliver | Yes | Clamp to default `260` | Avoids “opened but unusable” state |
| Right reopen after bad width memory | Remembered width is `< 50`, property panel reopens as a sliver | Yes | Clamp to default `280` | Avoids hidden inspector bug |
| Hide sidebar via shortcut | Focus stays on a hidden widget and keyboard input appears dead | Yes | Always call `_focus_page_canvas()` on hide | Prevents keyboard dead-end |
| Show left sidebar on Search tab | Focus lands on tab bar instead of search box | Yes | Explicitly focus and select `search_input` | Search flow remains one-keystroke |
| Show right sidebar on info card | No child widget is focusable | Yes | Fallback focus to right sidebar container | Avoids silent focus loss |
| Enter fullscreen while a sidebar is user-hidden | Exit fullscreen incorrectly shows hidden panel again | Yes | Reuse existing fullscreen visibility snapshot | Preserves user layout choice |

**Critical gaps:** None, as long as all planned tests are added and kept green.

## NOT in Scope

- Persist sidebar visibility or widths across app restarts.
  Rationale: not required for keyboard toggle UX and would add storage/state complexity.
- Add toolbar/menu buttons for left/right sidebar toggle.
  Rationale: the requested feature is keyboard-first and this would expand UI surface.
- Create a generalized layout manager or sidebar service.
  Rationale: overbuilt for a two-sidebar `PDFView` implementation.
- Store sidebar visibility per open document session.
  Rationale: current fullscreen snapshot is window-level; per-document layout state is a separate feature.
- Change the right sidebar into a tabbed UI.
  Rationale: the current right panel is a dynamic inspector and does not need structural redesign.

## Inline Diagram Guidance

- No new inline ASCII code comment is required if helpers stay short and explicit.
- If the splitter width reconciliation helper grows beyond a few branches, add a short ASCII note in `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py` above that helper showing how `[left, center, right]` sizes are preserved on hide/show.

## Completion Summary

- Step 0: Scope Challenge (user chose: `3. SMALL CHANGE`)
- Architecture Review: 1 issue found
- Code Quality Review: 1 issue found
- Test Review: diagram produced, 3 gaps identified
- Performance Review: 1 issue found
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 0 items proposed
- Failure modes: 0 critical gaps flagged

---

### Task 1: Lock in the left-sidebar shortcut contract with failing tests

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`
- Modify later: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Write the failing tests**

Add tests covering:

```python
def test_ctrl_alt_l_hides_left_sidebar_and_returns_focus_to_canvas(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "left_sidebar_toggle.pdf", ["page 1"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(250)

    assert view.left_sidebar_widget.isVisible()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(80)

    assert not view.left_sidebar_widget.isVisible()
    assert QApplication.focusWidget() in {view.graphics_view, view.graphics_view.viewport()}


def test_ctrl_f_reopens_hidden_left_sidebar_and_focuses_search(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "left_sidebar_search_reopen.pdf", ["alpha beta"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(250)

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(80)
    assert not view.left_sidebar_widget.isVisible()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_F, Qt.ControlModifier)
    _pump_events(80)

    assert view.left_sidebar_widget.isVisible()
    assert view.left_sidebar.currentIndex() == 1
    assert QApplication.focusWidget() is view.search_input
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "ctrl_alt_l or reopens_hidden_left_sidebar" -v`

Expected: FAIL because no sidebar-toggle shortcut exists and `_show_search_tab()` does not force a hidden left sidebar visible.

**Step 3: Commit**

Do not commit yet. Continue after the failures are confirmed.

### Task 2: Implement left-sidebar toggling, width memory, and focus routing

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Add minimal state fields near the existing fullscreen/view state**

Add view-local width memory:

```python
self._left_sidebar_last_width = 260
self._right_sidebar_last_width = 280
```

**Step 2: Install the new left shortcut in the existing shortcut setup**

Extend `_install_document_tab_shortcuts()` with:

```python
self._shortcut_toggle_left_sidebar = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
self._shortcut_toggle_left_sidebar.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
self._shortcut_toggle_left_sidebar.activated.connect(self.toggle_left_sidebar)
```

**Step 3: Add small helper methods instead of duplicating logic**

Implement only the minimum helpers needed:

```python
def _resolve_sidebar_width(self, remembered: int, default_width: int) -> int:
    return default_width if remembered < 50 else remembered

def _focus_left_sidebar_target(self) -> None:
    if self.left_sidebar.currentIndex() == 1:
        self.search_input.setFocus()
        self.search_input.selectAll()
    else:
        self.left_sidebar.tabBar().setFocus(Qt.ShortcutFocusReason)

def _ensure_left_sidebar_visible(self, focus_target: bool = False) -> None:
    ...

def toggle_left_sidebar(self) -> None:
    ...
```

Implementation rules:

- On hide:
  - read `self.main_splitter.sizes()[0]`
  - if width is usable, remember it
  - hide `self.left_sidebar_widget`
  - call `_focus_page_canvas()`
- On show:
  - show `self.left_sidebar_widget`
  - restore width using `_resolve_sidebar_width(..., 260)`
  - apply one `self.main_splitter.setSizes(...)`
  - if requested, focus search input or left tab bar

**Step 4: Route existing left-tab methods through the shared visibility helper**

Update:

- `_show_thumbnails_tab()`
- `_show_search_tab()`
- `_show_annotations_tab()`
- `_show_watermarks_tab()`

so they first call `_ensure_left_sidebar_visible(...)` and then set the tab.

**Step 5: Run targeted tests to verify they pass**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "ctrl_alt_l or reopens_hidden_left_sidebar" -v`

Expected: PASS

**Step 6: Commit**

```bash
git add "C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py"
git commit -m "feat: add left sidebar toggle shortcut"
```

### Task 3: Lock in the right-sidebar shortcut contract with failing tests

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`
- Modify later: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Write the failing tests**

Add tests covering:

```python
def test_ctrl_alt_r_toggles_right_sidebar_and_restores_focusable_control(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "right_sidebar_toggle.pdf", ["page 1"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(250)

    view.set_mode("add_text")
    _pump_events(80)

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_R, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(80)
    assert not view.right_sidebar.isVisible()
    assert QApplication.focusWidget() in {view.graphics_view, view.graphics_view.viewport()}

    view._right_sidebar_last_width = 36
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_R, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(80)

    assert view.right_sidebar.isVisible()
    assert view.right_sidebar.width() >= 240
    assert QApplication.focusWidget() is view.text_font


def test_fullscreen_restores_user_hidden_sidebars(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_hidden_sidebars.pdf", ["page 1", "page 2"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(300)

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_R, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(100)

    _trigger_fullscreen(view)
    _pump_events(180)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(220)

    assert not view.left_sidebar_widget.isVisible()
    assert not view.right_sidebar.isVisible()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "ctrl_alt_r or fullscreen_restores_user_hidden_sidebars" -v`

Expected: FAIL because no right-sidebar shortcut exists and no right-sidebar focus helper exists.

**Step 3: Commit**

Do not commit yet. Continue after the failures are confirmed.

### Task 4: Implement right-sidebar toggling and focus fallback

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Add the right shortcut alongside the left shortcut**

```python
self._shortcut_toggle_right_sidebar = QShortcut(QKeySequence("Ctrl+Alt+R"), self)
self._shortcut_toggle_right_sidebar.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
self._shortcut_toggle_right_sidebar.activated.connect(self.toggle_right_sidebar)
```

**Step 2: Add a single focus helper for the current property card**

Implement a minimal focus finder:

```python
def _focus_right_sidebar_target(self) -> None:
    current = self.right_stacked_widget.currentWidget()
    for child in current.findChildren(QWidget):
        if child.focusPolicy() != Qt.NoFocus and child.isEnabled() and child.isVisible():
            child.setFocus(Qt.ShortcutFocusReason)
            return
    self.right_sidebar.setFocus(Qt.ShortcutFocusReason)
```

Set a focus policy on `self.right_sidebar` if needed so the fallback is valid.

**Step 3: Implement `toggle_right_sidebar()`**

Rules:

- On hide:
  - remember `self.main_splitter.sizes()[2]` if usable
  - hide `self.right_sidebar`
  - call `_focus_page_canvas()`
- On show:
  - show `self.right_sidebar`
  - restore width using `_resolve_sidebar_width(..., 280)`
  - apply one `self.main_splitter.setSizes(...)`
  - call `_focus_right_sidebar_target()`

**Step 4: Run targeted tests to verify they pass**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "ctrl_alt_r or fullscreen_restores_user_hidden_sidebars" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add "C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py"
git commit -m "feat: add right sidebar toggle shortcut"
```

### Task 5: Run the regression slice and finalize verification

**Files:**
- Verify only:
  - `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`
  - `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`

**Step 1: Run the focused regression slice**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "ctrl_alt_l or ctrl_alt_r or fullscreen or search_tab" -v`

Expected: PASS

**Step 2: Run the full target file**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -v`

Expected: PASS; if unrelated failures already exist, document the exact failing test names and keep all new sidebar tests green.

**Step 3: Review the diff**

Run: `git diff -- "C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py" "C:\Users\jiang\Documents\python programs\pdf_editor\docs\plans\2026-03-17-sidebar-shortcuts.md"`

Expected: only shortcut wiring, sidebar helper logic, targeted tests, and this plan file changed.

**Step 4: Commit**

```bash
git add "C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py" "C:\Users\jiang\Documents\python programs\pdf_editor\docs\plans\2026-03-17-sidebar-shortcuts.md"
git commit -m "feat: add sidebar toggle shortcuts"
```
