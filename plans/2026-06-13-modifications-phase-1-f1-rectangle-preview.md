# F1 Browse Mode and Rectangle Preview Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add F1 as a reliable shortcut back to browse mode and show a live rectangle preview while dragging in rectangle mode.

**Architecture:** Keep behavior inside `PDFView` because both changes are view interaction concerns. Reuse existing `set_mode("browse")` cleanup for F1 and the existing scene/doc coordinate helpers for rectangle conversion so preview and final annotation use the same page and scale basis.

**Tech Stack:** PySide6, PyMuPDF `fitz.Rect`, pytest, existing lightweight view test doubles.

---

## Current Touchpoints

- `view/pdf_view.py`: `_setup_toolbar()`, `set_mode()`, `_mouse_press()`, `_mouse_move()`, `_mouse_release()`, `_handle_escape()`.
- `test_scripts/test_interaction_modes.py`: mode switching and annotation interaction tests.
- Add tests in `test_scripts/test_interaction_modes.py` unless the file becomes too crowded; if so create `test_scripts/test_rectangle_preview.py`.

## Required Behavior

- Pressing F1 must call `PDFView.set_mode("browse")` from any mode.
- F1 must finalize/cancel active edit state exactly as clicking `瀏覽模式` does.
- Rectangle mode must display a translucent preview rectangle after mouse press and during drag.
- The preview must stay on the page where the drag started, even if the cursor moves over another page.
- The preview must be removed after mouse release, Escape, or mode switch.
- Final rectangle emission must still call `sig_add_rect.emit(page_num, fitz_rect, color, fill)`.
- Highlight mode must not be changed in this phase.

## Task 1: Add F1 Browse Shortcut

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_interaction_modes.py`

**Step 1: Write failing tests**

Add a focused test that constructs a `PDFView` or existing lightweight view fixture, sets modes such as `rect`, `objects`, and `edit_text`, sends an F1 key event or calls the shortcut activation callback, and asserts `current_mode == "browse"`.

Expected test intent:

```python
def test_f1_switches_to_browse_mode(qapp):
    view = PDFView()
    try:
        view.set_mode("rect")
        QTest.keyClick(view, Qt.Key_F1)
        assert view.current_mode == "browse"
    finally:
        view.close()
        view.deleteLater()
```

If `QTest` is unstable in this suite, assert the created `QShortcut` exists and manually emit `activated`.

**Step 2: Run the failing test**

Run:

```powershell
pytest -q test_scripts/test_interaction_modes.py -k f1
```

Expected: fails because F1 is not wired to browse mode.

**Step 3: Implement**

In `PDFView.__init__()` after toolbar setup or in the toolbar setup section, add a `QShortcut(QKeySequence(Qt.Key_F1), self)` whose `activated` signal calls `self.set_mode("browse")`.

Implementation shape:

```python
self._browse_shortcut = QShortcut(QKeySequence(Qt.Key_F1), self)
self._browse_shortcut.activated.connect(lambda: self.set_mode("browse"))
```

Do not duplicate cleanup logic in the shortcut handler.

**Step 4: Verify**

Run:

```powershell
pytest -q test_scripts/test_interaction_modes.py -k f1
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_interaction_modes.py
git commit -m "feat(ui): add F1 browse shortcut"
```

## Task 2: Add Rectangle Preview State

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_interaction_modes.py`

**Step 1: Write failing tests**

Add tests with fake scene/item objects or a real offscreen `PDFView` that assert:

- Mouse press in `rect` mode stores `drawing_start` and the starting page index.
- Mouse move creates one preview item and updates its `QRectF`.
- Moving across a page boundary clamps the preview endpoint to the starting page.
- Mouse release clears the preview item.

Expected assertions:

```python
assert view._rect_preview_item is not None
assert view._drawing_page_idx == 0
assert view._rect_preview_item.rect().isValid()
```

**Step 2: Run the failing tests**

Run:

```powershell
pytest -q test_scripts/test_interaction_modes.py -k "rect and preview"
```

Expected: fails because no preview state exists.

**Step 3: Implement preview helpers**

In `PDFView.__init__()` initialize:

```python
self._rect_preview_item = None
self._drawing_page_idx = None
```

Add helpers:

```python
def _clear_rect_preview(self) -> None:
    item = getattr(self, "_rect_preview_item", None)
    if item is not None:
        try:
            self.scene.removeItem(item)
        except Exception:
            pass
    self._rect_preview_item = None
    self._drawing_page_idx = None

def _update_rect_preview(self, scene_pos: QPointF) -> None:
    if self.current_mode != "rect" or self.drawing_start is None:
        return
    page_idx = self._drawing_page_idx
    if page_idx is None:
        return
    end_pos = self._clamp_scene_point_to_page(scene_pos, page_idx)
    rect = QRectF(self.drawing_start, end_pos).normalized()
    pen = QPen(QColor(220, 38, 38, 210), 1)
    brush = QBrush(QColor(220, 38, 38, 35))
    if self._rect_preview_item is None:
        self._rect_preview_item = self.scene.addRect(rect, pen, brush)
        self._rect_preview_item.setZValue(20)
    else:
        self._rect_preview_item.setRect(rect)
        self._rect_preview_item.setPen(pen)
        self._rect_preview_item.setBrush(brush)
```

**Step 4: Wire press, move, release, cancel**

- In `_mouse_press()`, when `current_mode == "rect"`, resolve `page_idx` from the press position, clamp the start point to that page, store `_drawing_page_idx`, and create/update preview.
- In `_mouse_move()`, when `current_mode == "rect"` and left button is down, call `_update_rect_preview(scene_pos)` and accept the event.
- In `_mouse_release()`, clear the preview before returning.
- In `set_mode()` and `_handle_escape()`, call `_clear_rect_preview()`.

Keep highlight mode using the old path.

**Step 5: Fix final rectangle conversion**

When finalizing a rectangle, use the stored `_drawing_page_idx` and `_scene_rect_to_doc_rect(rect, page_idx)`.

Required behavior:

```python
page_idx = self._drawing_page_idx
if page_idx is None:
    page_idx = self._scene_y_to_page_index(cy) if (...) else self.current_page
doc_rect = self._scene_rect_to_doc_rect(rect, page_idx)
if doc_rect is not None:
    self.sig_add_rect.emit(page_idx + 1, doc_rect, color, fill)
```

Do not use stale `self.scale` in the new rectangle path.

**Step 6: Verify**

Run:

```powershell
pytest -q test_scripts/test_interaction_modes.py
```

Expected: pass.

**Step 7: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_interaction_modes.py
git commit -m "feat(ui): preview rectangle drawing"
```

## Phase Verification

Run:

```powershell
pytest -q test_scripts/test_interaction_modes.py test_scripts/test_browse_selection_gui_regressions.py
```

Expected: all pass.

## Notes For Implementer

- Do not add rectangle preview to highlight mode in this phase.
- Do not change model annotation APIs.
- If a test double lacks `scene.removeItem`, guard it like existing cleanup helpers do.
- Avoid using `self.scale` for new scene-to-doc conversion; use `_render_scale` helpers.
