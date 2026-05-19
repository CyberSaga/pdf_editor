# Middle-Click Auto-Pan Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this task-by-task. Follow TDD per CLAUDE.md §5.1 (Red-Light First).

**Goal:** Add browser/Acrobat-style auto-pan: middle-click engages a sticky pan mode where the view scrolls automatically at a speed proportional to the cursor's distance from the mousedown origin. Another click (left/middle/right) exits and restores the previously active tool mode; right-click also opens the regular context menu.

**Architecture:** Pan is implemented as an **overlay state**, not a real entry in `_VALID_MODES`. A `QTimer` ticking every 16 ms translates `(cursor − origin)` distance into scroll deltas via the view's own scrollbars. Because continuous mode already stacks all pages into a single scene, scrolling vertically naturally crosses page boundaries — no extra layout code is needed. Mouse routing piggybacks on the existing `_mouse_press` / `_mouse_move` / `_mouse_release` entry points bound in `view/pdf_view.py:421-423`.

**Tech Stack:** PySide6 (QGraphicsView, QTimer, QScrollBar, QCursor), pytest + pytest-qt.

---

## Context

**Why now:** The PDF viewer currently offers only `ScrollHandDrag` (hand-cursor grab-to-scroll) in browse mode and wheel-based scroll. Users who read long documents want a hands-free "auto-scroll" akin to Acrobat's middle-click auto-pan — engage once, glide, click to stop. The request also wants this to work across pages and to be usable from any tool mode (not just browse).

**Intended outcome:** Pressing the middle mouse button anywhere on the page switches the view into an overlay "auto-pan" state; moving the cursor away from the press point scrolls the view continuously, faster the further the cursor gets. Pressing any mouse button exits the overlay and returns to the previous tool mode; a right-click exit additionally pops the standard context menu for that restored mode.

---

## Key Files & Reference Points

| Concern | File : line |
|---|---|
| Mouse routing (press/move/release overridden) | `view/pdf_view.py:421-423` |
| `_mouse_press` entry | `view/pdf_view.py:2405` |
| `_mouse_move` entry | `view/pdf_view.py:2601` |
| `_mouse_release` entry | `view/pdf_view.py:3614` |
| `_event_scene_pos` helper (viewport→scene coords) | `view/pdf_view.py:2395` |
| Mode switcher (reuse for restore) | `view/pdf_view.py:1530` (`set_mode`) |
| Current mode tracker | `view/pdf_view.py:1565` (`self.current_mode`) |
| Context menu trigger | `view/pdf_view.py:3929` (`_show_context_menu`) |
| Context menu signal wiring | `view/pdf_view.py:424-425` |
| Vertical scrollbar access | `self.graphics_view.verticalScrollBar()` |
| Horizontal scrollbar access | `self.graphics_view.horizontalScrollBar()` |
| Timer pattern precedent | `view/pdf_view.py:332` (`_zoom_debounce_timer`) |
| Architecture contract | `docs/ARCHITECTURE.md` §2.4 (View layer), §continuous mode |
| Mouse-pos normalization pitfall | `docs/PITFALLS.md` "Browse object drag normalization" |

---

## Design Decisions

1. **Not a real mode.** `_VALID_MODES` stays untouched; `self.current_mode` is left alone. A new flag `self._autopan_active: bool` (plus a saved origin and previous-mode name) governs the overlay. Rationale: mode-switch logic in `set_mode` already clears drag state, text editors, etc. — we don't want autopan engagement to tear those down. Autopan is *navigation*, not a tool.
2. **Sticky, not drag-to-hold.** Middle-button **press** toggles autopan on; any subsequent button **press** toggles it off. Matches the user's "按一下 ... 再按一下" wording and matches Acrobat/Firefox behavior.
3. **Cursor origin anchored in viewport coordinates.** The scene moves under us as we scroll, so scene-space origin would drift. Store origin as `QPoint` in viewport coords.
4. **Speed curve:** `speed_px_per_tick = sign(d) * max(0, |d| - DEADZONE) / DIVISOR`, with `DEADZONE = 12 px`, `DIVISOR = 8`, clamped to ±40 px/tick. ~60 fps tick → smooth, tunable. Linear is predictable; we can upgrade to quadratic later if needed.
5. **Sub-pixel accumulation.** Scrollbars are `int`. Keep float accumulators `_autopan_accum_x/_y` and floor on each `setValue` call, preserving fractional velocity.
6. **Right-click exit + context menu.** Suppress Qt's default right-press behavior during autopan, call `_exit_autopan()`, then invoke `self._show_context_menu(viewport_pos)` explicitly. Do **not** leave `customContextMenuRequested` to fire — swallow the release too, since the signal fires on release (would double-pop).
7. **Scope: all modes.** Middle-click engages autopan from any current_mode — user asked for "返回原本在的模式". If `self.text_editor` is active, first finalize it (mirrors `set_mode`'s behavior) to avoid stale editor state during pan.
8. **Cursor icon.** Use `Qt.SizeAllCursor` on the viewport during autopan (Qt's built-in 4-way arrow). Restore the previous cursor on exit.

---

## Implementation Tasks

### Task 1: State fields + helper scaffolding

**Files:**
- Modify: `view/pdf_view.py` (`__init__` around line 330-410; add helpers near `_mouse_press`)

**Step 1: Add state fields in `__init__`** (place alongside other drag-state fields, e.g. after the zoom debounce timer at line 332):

```python
# --- Auto-pan (middle-click auto-scroll) overlay state ---
self._autopan_active: bool = False
self._autopan_origin_viewport: QPoint | None = None
self._autopan_cursor_viewport: QPoint | None = None
self._autopan_accum_x: float = 0.0
self._autopan_accum_y: float = 0.0
self._autopan_prev_cursor: QCursor | None = None
self._autopan_timer = QTimer(self)
self._autopan_timer.setInterval(16)  # ~60 fps
self._autopan_timer.timeout.connect(self._autopan_tick)
```

Ensure `QPoint` and `QCursor` are imported (check existing `from PySide6.QtCore/QtGui import ...` blocks — add if missing).

**Step 2:** Add constants near the top of `PDFView` (after `_VALID_MODES`):

```python
_AUTOPAN_DEADZONE_PX: float = 12.0
_AUTOPAN_DIVISOR: float = 8.0
_AUTOPAN_MAX_STEP_PX: float = 40.0
```

**Step 3:** Add three private helpers as methods on `PDFView` (anywhere in the class; group near `_mouse_press` for locality):

```python
def _enter_autopan(self, origin_viewport: QPoint) -> None:
    if self._autopan_active:
        return
    if self.text_editor:
        self._finalize_text_edit()
    viewport = self.graphics_view.viewport()
    self._autopan_prev_cursor = viewport.cursor()
    viewport.setCursor(Qt.SizeAllCursor)
    self._autopan_active = True
    self._autopan_origin_viewport = QPoint(origin_viewport)
    self._autopan_cursor_viewport = QPoint(origin_viewport)
    self._autopan_accum_x = 0.0
    self._autopan_accum_y = 0.0
    self._autopan_timer.start()

def _exit_autopan(self) -> None:
    if not self._autopan_active:
        return
    self._autopan_timer.stop()
    self._autopan_active = False
    self._autopan_origin_viewport = None
    self._autopan_cursor_viewport = None
    self._autopan_accum_x = 0.0
    self._autopan_accum_y = 0.0
    viewport = self.graphics_view.viewport()
    if self._autopan_prev_cursor is not None:
        viewport.setCursor(self._autopan_prev_cursor)
    else:
        viewport.unsetCursor()
    self._autopan_prev_cursor = None

def _autopan_tick(self) -> None:
    if not self._autopan_active:
        return
    origin = self._autopan_origin_viewport
    cursor = self._autopan_cursor_viewport
    if origin is None or cursor is None:
        return
    import math as _math
    def _step(delta: float) -> float:
        sign = 1.0 if delta > 0 else (-1.0 if delta < 0 else 0.0)
        mag = max(0.0, abs(delta) - self._AUTOPAN_DEADZONE_PX) / self._AUTOPAN_DIVISOR
        return sign * min(mag, self._AUTOPAN_MAX_STEP_PX)
    self._autopan_accum_x += _step(float(cursor.x() - origin.x()))
    self._autopan_accum_y += _step(float(cursor.y() - origin.y()))
    dx = int(_math.copysign(_math.floor(abs(self._autopan_accum_x)), self._autopan_accum_x))
    dy = int(_math.copysign(_math.floor(abs(self._autopan_accum_y)), self._autopan_accum_y))
    self._autopan_accum_x -= dx
    self._autopan_accum_y -= dy
    if dx:
        hbar = self.graphics_view.horizontalScrollBar()
        hbar.setValue(hbar.value() + dx)
    if dy:
        vbar = self.graphics_view.verticalScrollBar()
        vbar.setValue(vbar.value() + dy)
```

**Step 4: Verify imports.** Ensure `QTimer`, `QPoint`, `QCursor`, `Qt` are imported in `view/pdf_view.py`. Most are already present; add any missing.

**Step 5: Commit** — `feat(view): scaffold auto-pan overlay state and timer helpers`.

---

### Task 2: Write failing integration tests (Red)

**Files:**
- Create: `tests/view/test_autopan.py` (check existing test layout — if tests live under `tests/` flat, use `tests/test_autopan.py`; inspect the `tests/` folder first)

**Step 1: Scan existing test layout.** Run `ls tests/` and pick the matching folder. Look for any existing `pytest-qt` tests to copy fixture patterns.

**Step 2: Write the failing tests.**

```python
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from view.pdf_view import PDFView


@pytest.fixture
def view(qtbot):
    v = PDFView(defer_heavy_panels=True)
    qtbot.addWidget(v)
    v.show()
    return v


def _press(view, button: Qt.MouseButton, pos: QPoint):
    viewport = view.graphics_view.viewport()
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos, viewport.mapToGlobal(pos), button, button, Qt.KeyboardModifier.NoModifier,
    )
    view.graphics_view.mousePressEvent(ev)


def test_middle_click_enters_autopan(view):
    assert view._autopan_active is False
    _press(view, Qt.MiddleButton, QPoint(200, 200))
    assert view._autopan_active is True
    assert view._autopan_origin_viewport == QPoint(200, 200)
    assert view._autopan_timer.isActive()


def test_second_middle_click_exits_autopan(view):
    _press(view, Qt.MiddleButton, QPoint(200, 200))
    _press(view, Qt.MiddleButton, QPoint(300, 300))
    assert view._autopan_active is False
    assert view._autopan_timer.isActive() is False


def test_left_click_exit_does_not_trigger_selection(view):
    view.set_mode("browse")
    _press(view, Qt.MiddleButton, QPoint(200, 200))
    _press(view, Qt.LeftButton, QPoint(200, 200))
    assert view._autopan_active is False
    assert view.current_mode == "browse"

def test_right_click_exit_triggers_context_menu(view, monkeypatch):
    called = {}
    monkeypatch.setattr(view, "_show_context_menu", lambda pos: called.setdefault("pos", pos))
    _press(view, Qt.MiddleButton, QPoint(200, 200))
    _press(view, Qt.RightButton, QPoint(250, 260))
    assert view._autopan_active is False
    assert "pos" in called


def test_autopan_tick_scrolls_when_cursor_moves(view):
    vbar = view.graphics_view.verticalScrollBar()
    vbar.setRange(0, 5000); vbar.setValue(1000)
    _press(view, Qt.MiddleButton, QPoint(400, 400))
    view._autopan_cursor_viewport = QPoint(400, 600)  # 200 px down
    for _ in range(10):
        view._autopan_tick()
    assert vbar.value() > 1000  # scrolled downward

def test_autopan_speed_scales_with_distance(view):
    vbar = view.graphics_view.verticalScrollBar()
    vbar.setRange(0, 100000)
    # far cursor
    vbar.setValue(0)
    _press(view, Qt.MiddleButton, QPoint(400, 400))
    view._autopan_cursor_viewport = QPoint(400, 800)
    for _ in range(10):
        view._autopan_tick()
    far = vbar.value()
    view._exit_autopan()
    # near cursor
    vbar.setValue(0)
    _press(view, Qt.MiddleButton, QPoint(400, 400))
    view._autopan_cursor_viewport = QPoint(400, 430)
    for _ in range(10):
        view._autopan_tick()
    near = vbar.value()
    assert far > near * 2  # strictly faster when cursor is further
```

**Step 3: Run tests, confirm RED.**

```bash
pytest tests/view/test_autopan.py -v
```

Expected: all tests fail (`_autopan_active` attribute missing on freshly constructed view, or routing not wired yet).

**Step 4: Commit** — `test(view): add failing tests for middle-click auto-pan`.

---

### Task 3: Wire press routing (Green for press-related tests)

**Files:**
- Modify: `view/pdf_view.py:2405` (top of `_mouse_press`)

**Step 1:** Insert an autopan-handling block as the **first** code inside `_mouse_press`, before any `scene_pos = ...` work or button-specific branches:

```python
def _mouse_press(self, event):
    # --- Auto-pan overlay handling (must run first) ---
    raw_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
    viewport = self.graphics_view.viewport()
    try:
        viewport_pos = viewport.mapFrom(self.graphics_view, raw_pos)
    except Exception:
        viewport_pos = raw_pos
    if self._autopan_active:
        button = event.button()
        self._exit_autopan()
        if button == Qt.RightButton:
            self._show_context_menu(viewport_pos)
        event.accept()
        return
    if event.button() == Qt.MiddleButton:
        self._enter_autopan(viewport_pos)
        event.accept()
        return
    # --- End auto-pan handling ---

    scene_pos = self._event_scene_pos(event)
    # ... existing code continues unchanged ...
```

**Step 2:** Run tests:

```bash
pytest tests/view/test_autopan.py::test_middle_click_enters_autopan tests/view/test_autopan.py::test_second_middle_click_exits_autopan tests/view/test_autopan.py::test_left_click_exit_does_not_trigger_selection tests/view/test_autopan.py::test_right_click_exit_triggers_context_menu -v
```

Expected: all four press-tests PASS.

**Step 3: Commit** — `feat(view): route middle-click to auto-pan enter/exit`.

---

### Task 4: Wire move tracking + suppress default context menu during exit (Green for scroll tests)

**Files:**
- Modify: `view/pdf_view.py:2601` (`_mouse_move`) and `view/pdf_view.py:424-425` (context-menu signal handling)

**Step 1:** Insert at the very top of `_mouse_move`:

```python
def _mouse_move(self, event):
    if self._autopan_active:
        raw_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        viewport = self.graphics_view.viewport()
        try:
            viewport_pos = viewport.mapFrom(self.graphics_view, raw_pos)
        except Exception:
            viewport_pos = raw_pos
        self._autopan_cursor_viewport = QPoint(viewport_pos)
        event.accept()
        return
    # ... existing code continues unchanged ...
```

**Step 2:** Also insert at the top of `_mouse_release` (to swallow the right-button release so `customContextMenuRequested` does not double-pop the menu after an autopan exit):

```python
def _mouse_release(self, event):
    # Autopan swallows releases entirely; exit happens on press.
    if self._autopan_active:
        event.accept()
        return
    # ... existing code continues unchanged ...
```

Note: the exit-exit transition happens on the press that toggles off; by the time the release arrives, `_autopan_active` is already False. To additionally prevent `customContextMenuRequested` from firing right after an autopan-exit-via-right-click, introduce a one-shot flag:

```python
# in __init__:
self._autopan_suppress_next_context_menu: bool = False

# at end of press-path that handles right-button autopan exit (Task 3 block), set:
self._autopan_suppress_next_context_menu = True
```

And patch `_show_context_menu` to honor it:

```python
def _show_context_menu(self, pos):
    if self._autopan_suppress_next_context_menu:
        self._autopan_suppress_next_context_menu = False
        # the manual call from _mouse_press still needs to show the menu,
        # so only suppress when pos came from the signal, not our manual call.
        ...
```

**Simpler alternative** (recommended): move the manual `self._show_context_menu(viewport_pos)` call to happen via `QTimer.singleShot(0, lambda: self._show_context_menu(viewport_pos))`, and **also** set the suppress-flag before returning. The signal-driven call consumes the flag; the deferred manual call runs after and always fires. Concretely:

```python
if self._autopan_active:
    button = event.button()
    self._exit_autopan()
    if button == Qt.RightButton:
        self._autopan_suppress_next_context_menu = True
        QTimer.singleShot(0, lambda: self._show_context_menu(viewport_pos))
    event.accept()
    return
```

And at the top of `_show_context_menu`:

```python
def _show_context_menu(self, pos):
    if self._autopan_suppress_next_context_menu and not getattr(self, "_autopan_manual_menu", False):
        self._autopan_suppress_next_context_menu = False
        return
    # existing body ...
```

Wrap the manual call to set `_autopan_manual_menu = True` briefly:

```python
def _show_context_menu_manual(self, pos):
    self._autopan_manual_menu = True
    try:
        self._show_context_menu(pos)
    finally:
        self._autopan_manual_menu = False
```

and call `self._show_context_menu_manual(viewport_pos)` from the deferred lambda.

**Step 3:** Run full autopan test file:

```bash
pytest tests/view/test_autopan.py -v
```

Expected: all six tests PASS.

**Step 4:** Run the whole suite to confirm no regression:

```bash
pytest -x
```

**Step 5:** Run lint:

```bash
ruff check view/pdf_view.py tests/view/test_autopan.py
```

Fix anything new; existing violations are tracked separately per CLAUDE.md §3.1.

**Step 6: Commit** — `feat(view): auto-pan cursor tracking and right-click context-menu handoff`.

---

### Task 5: Docs + pitfalls

**Files:**
- Modify: `docs/ARCHITECTURE.md` (View section)
- Modify: `docs/PITFALLS.md` (append a new entry)
- Modify: `TODOS.md` (mark done / add follow-ups)

**Step 1:** In `docs/ARCHITECTURE.md`, under the View layer section, add one paragraph describing auto-pan as an "overlay state" that does not change `current_mode` and interacts with the mouse-event pipeline at the top of `_mouse_press` / `_mouse_move` / `_mouse_release`.

**Step 2:** In `docs/PITFALLS.md`, append:

```
## Auto-pan vs. context menu double-pop
**Area:** view / PDFView mouse routing
**Symptom:** Context menu appears twice when right-clicking to exit auto-pan.
**Cause:** Qt's `customContextMenuRequested` fires on right-button release, independent of whether we swallowed the press. Both the manual exit-path menu call and the signal try to show the menu.
**Fix:** Gate `_show_context_menu` with a one-shot `_autopan_suppress_next_context_menu` flag that suppresses the signal-driven call; invoke the manual call via `QTimer.singleShot(0, ...)` with a companion `_autopan_manual_menu` flag that bypasses the suppressor.
**File:** `view/pdf_view.py:_show_context_menu` and the autopan handling block in `_mouse_press`.
```

**Step 3:** Update `TODOS.md` with any follow-ups (e.g., "tune autopan speed curve based on user feedback", "consider drawing a 4-way-arrow icon at the origin").

**Step 4:** Commit — `docs: document auto-pan overlay and context-menu pitfall`.

---

## Verification

End-to-end manual test (run `python main.py`, open any multi-page PDF):

1. In **browse** mode, click the middle mouse button mid-page. Cursor should change to a 4-way arrow; the view should not jump.
2. Move cursor downward slightly — view scrolls slowly. Move further — scrolls faster. Cross into the next page visually.
3. Move cursor upward past the origin — view scrolls backward.
4. Press **left** button. Auto-pan should stop; cursor returns to hand (browse default). Click-and-drag scrolls normally again.
5. Repeat step 1. Press **middle** button again — auto-pan toggles off.
6. Repeat step 1. Press **right** button — auto-pan stops AND the regular right-click context menu appears (Copy / Zoom / etc.).
7. Switch to **rect** mode. Click middle button — auto-pan engages from rect mode. Exit with left click — returns to rect mode (crosshair cursor, not hand).
8. Switch to **edit_text** mode, open a text editor by clicking a block, then middle-click. Editor should finalize and auto-pan engages. Exit — returns to edit_text mode.

Automated:

```bash
pytest tests/view/test_autopan.py -v          # feature tests
pytest -x                                     # no regression
ruff check view/pdf_view.py tests/view/test_autopan.py
```

Done when: all checks green, verification steps 1-8 all behave as described, and `docs/PITFALLS.md` + `docs/ARCHITECTURE.md` updated.
