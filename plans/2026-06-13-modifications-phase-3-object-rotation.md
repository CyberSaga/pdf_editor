# Exact Object Rotation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Change object rotation menu actions from additive 90-degree steps to exact angle selection: 90, 180, 270, or 360 degrees from the object's original/page-coordinate angle.

**Architecture:** Route menu-based object rotation through `RotateObjectRequest.absolute_rotation` and keep drag rotation behavior intact. Extend the existing model textbox branch to honor absolute rotation, matching the image/native-image branches.

**Tech Stack:** PySide6 `QMenu`, PyMuPDF content rewriting, app-object annotations, pytest.

---

## Current Touchpoints

- `view/pdf_view.py`: `_rotate_selected_object()`, `_commit_free_rotation()`, `_mouse_release()`, `_show_context_menu()`, `_supports_free_rotate()`.
- `model/pdf_model.py`: `rotate_object()`.
- `model/object_requests.py`: `RotateObjectRequest.absolute_rotation` already exists.
- Tests: `test_scripts/test_object_free_rotation_gui.py`, `test_scripts/test_object_manipulation_gui.py`, `test_scripts/test_object_manipulation_model.py`, `test_scripts/test_object_free_rotation.py`.

## Required Behavior

- Object context menu must show exact rotation choices: `90°`, `180°`, `270°`, `360°`.
- A no-drag click on an object rotate handle must open the same exact-angle menu.
- Exact menu selection must emit `RotateObjectRequest(..., rotation_delta=0, absolute_rotation=angle)`.
- `360°` must be stored/emitted as `0°`.
- Drag rotation remains freeform and continues to emit `absolute_rotation` calculated by `absolute_rotation_from_drag()`.
- Existing image/native-image absolute rotation remains exact, not additive.
- Textbox objects must also honor `absolute_rotation`.

## Task 1: Add Textbox Absolute Rotation In Model

**Files:**
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_object_manipulation_model.py`

**Step 1: Write failing test**

Add a textbox test that first rotates additively, then sets an absolute angle:

```python
def test_textbox_absolute_rotation_sets_exact_angle() -> None:
    model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "ROT_ME", font="cjk", size=14, color=(0, 0, 0))
    hit = _object_hit(model, fitz.Point(80, 90))
    assert model.rotate_object(RotateObjectRequest(hit.object_id, hit.object_kind, 1, 90))
    assert model.rotate_object(
        RotateObjectRequest(
            hit.object_id,
            hit.object_kind,
            1,
            rotation_delta=0,
            absolute_rotation=180,
        )
    )
    rotated = _object_hit(model, fitz.Point(80, 90))
    assert rotated.rotation == 180
```

Add a second assertion for `absolute_rotation=360` expecting `0`.

**Step 2: Run failing test**

```powershell
pytest -q test_scripts/test_object_manipulation_model.py -k absolute_rotation
```

Expected: fails because textbox branch ignores `absolute_rotation`.

**Step 3: Implement**

In `PDFModel.rotate_object()` textbox branch, replace:

```python
new_rotation = (int(payload.get("rotation", 0)) + int(request.rotation_delta)) % 360
```

with:

```python
if request.absolute_rotation is not None:
    new_rotation = int(round(float(request.absolute_rotation))) % 360
else:
    new_rotation = (int(payload.get("rotation", 0)) + int(request.rotation_delta)) % 360
```

Leave the existing redact/delete/reinsert marker flow unchanged.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_object_manipulation_model.py -k "rotate_textbox or absolute_rotation"
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- model/pdf_model.py test_scripts/test_object_manipulation_model.py
git commit -m "feat(model): support exact textbox rotation"
```

## Task 2: Add Exact Rotation Emit Helper In View

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_object_manipulation_gui.py`

**Step 1: Write failing test**

Add a test that calls a new helper and asserts exact request shape:

```python
view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
assert pdf_view.PDFView._rotate_selected_object_absolute(view, 180)
req = view.sig_rotate_object.emitted[0][0]
assert req.rotation_delta == 0
assert req.absolute_rotation == 180
```

Add `360` case expecting `absolute_rotation == 0`.

**Step 2: Run failing test**

```powershell
pytest -q test_scripts/test_object_manipulation_gui.py -k absolute
```

Expected: helper missing.

**Step 3: Implement**

Add:

```python
def _normalize_object_rotation_angle(self, angle: int | float) -> float:
    return float(angle) % 360.0

def _rotate_selected_object_absolute(self, angle: int | float) -> bool:
    info = getattr(self, "_selected_object_info", None)
    if info is None or not getattr(info, "supports_rotate", False):
        return False
    absolute = self._normalize_object_rotation_angle(angle)
    self.sig_rotate_object.emit(
        RotateObjectRequest(
            object_id=info.object_id,
            object_kind=info.object_kind,
            page_num=info.page_num,
            rotation_delta=0,
            absolute_rotation=absolute,
        )
    )
    self._selected_object_info = replace(
        info,
        bbox=fitz.Rect(info.bbox),
        rotation=absolute,
    )
    self._update_object_selection_visuals()
    return True
```

Keep `_rotate_selected_object(rotation_delta)` for legacy tests and future fallback, but stop using it from menu/click paths.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_object_manipulation_gui.py -k absolute
```

Expected: pass.

## Task 3: Replace Object Context Menu Rotation Action

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_object_manipulation_gui.py`

**Step 1: Update failing tests**

Replace old assertion:

```python
assert any(label.startswith("Rotate Object 90") for label in labels)
```

with assertions that the rotation menu/submenu exposes all exact choices.

If fake `QMenu` cannot model submenus, implement `_add_object_rotation_actions(menu)` so tests can inspect flat labels under a fake menu while production uses a submenu.

Expected labels may be:

```python
["Rotate Object 90°", "Rotate Object 180°", "Rotate Object 270°", "Rotate Object 360°"]
```

or a submenu named `Rotate Object` with actions `90°`, `180°`, `270°`, `360°`. Choose one pattern and keep tests aligned.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_object_manipulation_gui.py -k context_menu
```

Expected: fails under old single 90-degree action.

**Step 3: Implement**

Add helper:

```python
def _add_object_rotation_actions(self, menu: QMenu) -> None:
    rotate_menu = menu.addMenu("Rotate Object") if hasattr(menu, "addMenu") else menu
    for angle in (90, 180, 270, 360):
        rotate_menu.addAction(
            f"{angle}°" if rotate_menu is not menu else f"Rotate Object {angle}°",
            lambda checked=False, a=angle: self._rotate_selected_object_absolute(a),
        )
```

In `_show_context_menu()`, replace the old `Rotate Object 90°` action with `_add_object_rotation_actions(menu)`.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_object_manipulation_gui.py -k context_menu
```

Expected: pass.

## Task 4: Change Rotate Handle Click To Open Menu

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_object_free_rotation_gui.py`, `test_scripts/test_object_manipulation_gui.py`

**Step 1: Update old tests**

Update `test_rotate_handle_click_without_drag_uses_90_step` to assert a menu is shown and selecting `270°` emits `absolute_rotation=270`.

Update `test_textbox_rotate_pending_release_uses_legacy_90_step` to the same exact menu behavior for textboxes.

Use monkeypatches for `_show_object_rotation_menu()` if direct `QMenu` testing is too brittle.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_object_free_rotation_gui.py -k click_without_drag
pytest -q test_scripts/test_object_manipulation_gui.py -k rotate_pending
```

Expected: fail because release path still calls `_rotate_selected_object(90)`.

**Step 3: Implement**

Add:

```python
def _show_object_rotation_menu(self, pos: QPoint | QPointF | None = None) -> None:
    menu = QMenu(self)
    self._add_object_rotation_actions(menu)
    if pos is None:
        menu.exec_(QCursor.pos())
    elif isinstance(pos, QPointF):
        menu.exec_(self.graphics_view.viewport().mapToGlobal(pos.toPoint()))
    else:
        menu.exec_(self.graphics_view.viewport().mapToGlobal(pos))
```

In `_mouse_release()`, replace no-drag rotate-handle calls to `_rotate_selected_object(90)` with `_show_object_rotation_menu(event.pos())`.

Do this for both object/text edit branch and any browse branch that handles `_object_rotate_pending`.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_object_free_rotation_gui.py test_scripts/test_object_manipulation_gui.py
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_object_free_rotation_gui.py test_scripts/test_object_manipulation_gui.py
git commit -m "feat(ui): use exact object rotation menus"
```

## Phase Verification

Run:

```powershell
pytest -q test_scripts/test_object_free_rotation_gui.py test_scripts/test_object_free_rotation.py test_scripts/test_object_manipulation_gui.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_controller_flow.py
```

Expected: all pass.

## Notes For Implementer

- Do not remove drag rotation tests; they are still required.
- Do not change `RotateObjectRequest` dataclass shape.
- `360°` means exact stored angle `0°`, not an additive full turn.
- If context-menu submenu tests are difficult with fake menus, use a helper and test the helper with fake menu actions.
