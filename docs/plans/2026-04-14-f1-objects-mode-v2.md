# F1 Objects Mode V2 (Resize, Multi-Select, Images) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an explicit `objects mode` (`操作物件`) and extend manipulation to support resize handles + multi-select, then add image objects (app-inserted first) while keeping browse/text-edit behavior predictable.

**Architecture:** Keep MVC boundaries: view owns gestures/handles/selection visuals, controller owns typed requests and undo/redo commands, model owns hit-testing and PDF mutations without Qt types. Add an explicit interaction-mode gate so object gestures never leak into browse-mode text selection.

**Tech Stack:** PySide6 (`QGraphicsView`/`QGraphicsScene`), PyMuPDF (`fitz`), existing typed request boundary (`model/*_requests.py`) and snapshot-backed undo/redo.

---

## Scope

### Required UX (from backlog/user requirements)

- **Objects mode (`操作物件`)**
  - User can move/rotate/delete/resize/multi-select rectangles and images.
- **Text edit mode**
  - User can move/rotate/delete/resize/multi-select textboxes.
  - User can edit words inside textboxes (existing behavior).

### Sequencing / Safety Constraints

- Keep F1 v1 object identity plumbing as the single source of truth (no parallel object model).
- Implement multi-select before resize handles (so resize applies to either single or selected set deterministically).
- Add **app-inserted images** before attempting manipulation of **native PDF images**.
  - Native image selection/manipulation is higher risk (XObject reuse, content-stream complexity).

---

## Task 1: Introduce Explicit Interaction Mode State (Browse vs Objects vs Text Edit)

**Files:**
- Modify: `view/pdf_view.py`
- Modify: `controller/pdf_controller.py`
- Test: `test_scripts/test_object_manipulation_gui.py`
- Create: `test_scripts/test_interaction_modes.py`

**Step 1: Write failing tests (mode gating)**

```python
def test_objects_mode_disables_text_selection_and_enables_object_drag(qtbot, app_window):
    view = app_window.view
    view.set_interaction_mode("objects")
    # Attempt drag on text area should NOT start text selection rect.
    assert getattr(view, "_text_selection_active", False) is False
```

**Step 2: Run tests to verify failures**

Run: `python -m pytest -q test_scripts/test_interaction_modes.py`
Expected: FAIL (no mode concept yet / missing API)

**Step 3: Implement minimal mode plumbing**

- Add `InteractionMode` enum (or simple string constants) at view-level:
  - `"browse"`, `"objects"`, `"text_edit"`
- Add a single setter `set_interaction_mode(...)` that:
  - clears incompatible selection state (`_clear_text_selection`, `_clear_object_selection`)
  - toggles the event-routing gate in mouse handlers
- Wire the mode to toolbar actions:
  - Ensure that selecting the existing edit-text tool sets `"text_edit"`.
  - Add a new toolbar action/button for `"objects"`.
  - Default remains `"browse"` when no tool is selected.

**Step 4: Run tests**

Run: `python -m pytest -q test_scripts/test_interaction_modes.py test_scripts/test_object_manipulation_gui.py`
Expected: PASS

**Step 5: Commit**

Commit message (example): `feat: add explicit interaction modes for browse/objects/text-edit`

---

## Task 2: Multi-Select Core (Objects Mode: Rects + Images; Text Edit Mode: Textboxes)

**Files:**
- Modify: `view/pdf_view.py`
- Modify: `model/object_requests.py`
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_object_controller_flow.py`
- Create: `test_scripts/test_object_multi_select.py`

**Step 1: Write failing tests**

```python
def test_shift_click_adds_second_object_to_selection(model, controller, view):
    view.set_interaction_mode("objects")
    # click obj A, shift-click obj B -> selection contains both
    assert len(view.get_selected_objects()) == 2
```

**Step 2: Run tests to verify failures**

Run: `python -m pytest -q test_scripts/test_object_multi_select.py`
Expected: FAIL

**Step 3: Implement minimal multi-select**

- View:
  - Replace `_selected_object_info` with `_selected_object_infos: list[ObjectHitInfo]`
  - Shift-click toggles membership
  - Plain click selects single and clears others
  - Delete key deletes all selected objects (batch)
  - Drag-move moves all selected objects (batch move request)
- Requests:
  - Add `MoveObjectsRequest` and `DeleteObjectsRequest` (plural) OR allow lists inside existing requests.
  - Keep payload Qt-free and stable for undo/redo.
- Model:
  - Implement batch move/delete by iterating stable object ids and applying existing single-item mutations.
  - Stop early with rollback behavior if any object mutation fails (define policy in tests).

**Step 4: Run tests**

Run: `python -m pytest -q test_scripts/test_object_multi_select.py test_scripts/test_object_controller_flow.py`
Expected: PASS

**Step 5: Commit**

Commit message (example): `feat: add multi-select and batch move/delete for objects`

---

## Task 3: Resize Handles (Single + Multi-Select Policy)

**Files:**
- Modify: `view/pdf_view.py`
- Modify: `model/object_requests.py`
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_object_manipulation_model.py`
- Create: `test_scripts/test_object_resize.py`

**Step 1: Write failing tests**

```python
def test_resize_rect_updates_bbox(model, make_rect_object):
    rect_id = make_rect_object()
    ok = model.resize_object(object_id=rect_id, object_kind="rect", page_num=1, new_rect=fitz.Rect(10, 10, 50, 60))
    assert ok
```

**Step 2: Run tests**

Run: `python -m pytest -q test_scripts/test_object_resize.py`
Expected: FAIL

**Step 3: Implement resize**

- View:
  - Add corner/edge handle visuals when exactly one object is selected.
  - Hit-test handles first, then object body.
  - While resizing, draw live preview outline (do not mutate model until mouseup).
- Requests:
  - Add `ResizeObjectRequest(object_id, object_kind, page_num, destination_rect)`
- Controller:
  - Convert resize mouse gesture into a typed request and snapshot command (`command_type="resize_object"`).
- Model:
  - For rectangle objects: update annotation rect + stored payload metadata.
  - For textbox objects: update marker payload + redact/restore region contract (like move/rotate).
  - For image objects: defer until Task 4 (but include request type now).

**Step 4: Run tests**

Run: `python -m pytest -q test_scripts/test_object_resize.py test_scripts/test_object_manipulation_model.py`
Expected: PASS

**Step 5: Commit**

Commit message (example): `feat: add resize handles and resize request pipeline`

---

## Task 4: App-Inserted Image Objects (Identity + Hit-Test + Move/Delete/Rotate/Resize)

**Files:**
- Modify: `model/pdf_model.py`
- Modify: `model/object_requests.py`
- Modify: `controller/pdf_controller.py`
- Modify: `view/pdf_view.py`
- Create: `test_scripts/test_image_objects_model.py`
- Create: `test_scripts/test_image_objects_gui.py`

**Step 1: Write failing tests**

```python
def test_inserted_image_is_discoverable_as_object(model, sample_doc):
    image_id = model.insert_image_object(page_num=1, rect=fitz.Rect(10, 10, 100, 100), image_bytes=b"...png...")
    hit = model.get_object_info_at_point(1, fitz.Point(50, 50))
    assert hit is not None
    assert hit.object_kind == "image"
    assert hit.object_id == image_id
```

**Step 2: Run tests**

Run: `python -m pytest -q test_scripts/test_image_objects_model.py`
Expected: FAIL

**Step 3: Implement image objects (app-inserted)**

- Define a stable app-owned identity marker (similar to textbox marker) that captures:
  - `object_kind=image`, `object_id`, page, visual bbox, rotation
  - A reference to the inserted image resource (implementation-specific; start simple)
- For v1 of images:
  - Support only images inserted by this app in this session (or persisted via marker + embedded image).
  - Defer advanced dedupe/reuse of XObjects until stability is proven.
- Hook hit-testing:
  - `get_object_info_at_point` must return images in objects mode.

**Step 4: Implement manipulation operations**

- Move/delete/rotate/resize should follow the same typed request -> model mutation pipeline as rect/textbox.

**Step 5: Run tests**

Run: `python -m pytest -q test_scripts/test_image_objects_model.py test_scripts/test_image_objects_gui.py`
Expected: PASS

**Step 6: Commit**

Commit message (example): `feat: add app-inserted image objects with full manipulation support`

---

## Task 5: Native/Imported PDF Image Manipulation (Defer Until App Images Are Stable)

**Files:**
- Create: `docs/plans/2026-04-14-f1-native-pdf-image-objects.md` (optional split plan)
- Modify: `model/pdf_model.py`
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_native_image_hit_testing.py`

**Step 1: Write a focused sub-plan or spike test**

- Identify how PyMuPDF exposes image blocks and their bboxes in a page.
- Decide selection semantics:
  - Select “visual instances” (image blocks on a page), not raw XObject names shared across pages.

**Step 2: Add a minimal hit-test-only implementation**

- Allow selecting native images (no mutation yet) in objects mode.

**Step 3: Only after hit-test is stable, add mutation**

- Move/rotate/resize/delete must be content-stream safe:
  - Avoid breaking resource reuse across pages.
  - Avoid touching shared XObjects unless user intends that.

**Commit policy:** keep this as its own epic slice; do not mix with core objects-mode work.

---

## Manual Verification (Windows GUI + Low-Level Harness)

**Files:**
- Modify: `tmp/manual_verify_f1_low_level.py`

Minimum manual pass to close the v2 tranche:

1. Toggle `objects mode` and confirm text-selection does not activate while dragging on a text area.
2. Create/select a rect; move; resize; rotate (if supported); delete; undo/redo.
3. Insert/select an image; move; resize; rotate; delete; undo/redo.
4. Toggle `text edit mode`; select a textbox; edit words; move; resize; rotate; multi-select; delete; undo/redo.

---

## Regression Test Slice

Before calling v2 done:

- `python -m pytest -q test_scripts/test_interaction_modes.py`
- `python -m pytest -q test_scripts/test_object_multi_select.py test_scripts/test_object_resize.py`
- `python -m pytest -q test_scripts/test_object_manipulation_gui.py`
- `python -m pytest -q test_scripts/test_image_objects_model.py test_scripts/test_image_objects_gui.py`

