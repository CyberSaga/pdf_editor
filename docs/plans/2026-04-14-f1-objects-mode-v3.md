# F1 Objects Mode V3 Implementation Plan

**Summary**

Extend the current F1 object-manipulation foundation into a clean two-mode model:

- `objects mode` (`操作物件`) handles **rectangles and images only**
- `text edit mode` handles **textboxes only**, including word editing plus move/rotate/delete/resize/multi-select
- Multi-select is **same-page only for now**, but the request/state shape should not block future cross-page expansion
- Textbox resize means **resize the box only**; text reflows inside it and font size does not change
- App-owned images ship in this tranche with **both file-insert and clipboard-paste entry points**
- Native PDF image manipulation stays out of scope for this tranche and gets its own later plan

**Public / interface changes**

- Add a first-class interaction mode that distinguishes `browse`, `objects`, and `text_edit`
- Add batch object request types for same-page selection/manipulation
- Add resize request types for rect/textbox/image objects
- Add app-owned image object identity parallel to textbox/rect identity
- Keep all request types Qt-free and model-owned

## Key Changes

### 1. Interaction modes and event routing

Implement explicit mode gating in the view/controller:

- `browse`
  - Keeps current text selection / copy behavior
  - Does not start object manipulation
- `objects`
  - Select / move / rotate / delete / resize / multi-select **rectangles and images only**
  - Does not start text selection or textbox word editing
- `text_edit`
  - Keeps word-editing behavior for textboxes
  - Adds textbox select / move / rotate / delete / resize / multi-select
  - Does not manipulate rects or images

Required UI behavior:

- Add a dedicated toolbar mode action for `objects mode`
- Keep existing `編輯文字` action as the entry to `text_edit`
- Switching modes clears incompatible temporary state and selection visuals
- Context menus should follow the active mode’s allowed object types

### 2. Multi-select model

Implement same-page multi-select first.

Decision-complete behavior:

- Plain click selects one object and clears existing selection
- `Shift+click` toggles objects into or out of the selection set
- Selection set is restricted to one page at a time in this tranche
- Clicking an object on a different page clears the prior set and starts a new one-page set
- Batch delete removes all selected objects on the active page
- Batch move moves all selected objects by the same delta on the active page
- Rotation in this tranche is:
  - allowed for textbox single-select in `text_edit`
  - allowed for image single-select in `objects mode`
  - not required for multi-select batches unless all selected objects are same-kind and the implementation remains clean
- The internal request/state shape should store page + object ids in a way that can later support cross-page expansion without redesign

### 3. Resize behavior

Add resize handles after multi-select.

Decision-complete behavior:

- Show resize handles only for a **single selected** object
- Multi-select shows a group selection outline only; no batch resize in this tranche
- Rectangle resize updates the annotation bbox
- Image resize updates the image object bbox
- Textbox resize in `text_edit` updates the textbox rect only
- Textbox font size stays unchanged; content reflows/wraps inside the new bounds
- Rotated textbox resize must preserve rotation metadata and re-render correctly
- Handle hits must work even when handles extend outside the object bbox, same lesson as the rotate handle fix

### 4. App-owned image objects

Ship app-inserted images before native image manipulation.

Decision-complete behavior:

- Users can insert an image by:
  - file picker
  - clipboard paste
- Inserted images become app-owned objects with stable ids and metadata
- App-owned image objects support:
  - select
  - move
  - rotate
  - delete
  - resize
  - same-page multi-select
- Image hit-testing uses the object identity layer, not loose page image-block scans
- Persist image metadata the same way textbox/rect objects persist metadata: stable id + kind + rect + rotation + source bookkeeping needed to rebuild the visible object
- Do not attempt native PDF image/XObject manipulation in this plan

### 5. Implementation order and commit slices

1. `feat: add explicit browse objects text-edit modes`
2. `feat: add same-page multi-select for supported objects`
3. `feat: add single-object resize handles`
4. `feat: add app-inserted image objects`
5. `docs: record objects-mode interaction rules and object pitfalls`

## Task-by-task execution

### Task 1: Mode plumbing

**Files**
- Modify: `view/pdf_view.py`
- Modify: `controller/pdf_controller.py`
- Test: `test_scripts/test_object_manipulation_gui.py`
- Create: `test_scripts/test_interaction_modes.py`

**Steps**
1. Write failing tests for mode switching, state clearing, and routing exclusions.
2. Run `python -m pytest -q test_scripts/test_interaction_modes.py`.
3. Add explicit mode constants and a single mode setter.
4. Wire the new toolbar action for `objects mode`.
5. Re-run `python -m pytest -q test_scripts/test_interaction_modes.py test_scripts/test_object_manipulation_gui.py`.
6. Commit.

### Task 2: Same-page multi-select

**Files**
- Modify: `view/pdf_view.py`
- Modify: `model/object_requests.py`
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Create: `test_scripts/test_object_multi_select.py`

**Steps**
1. Write failing tests for single-page shift-select, toggle-off, cross-page reset, batch delete, and batch move.
2. Run `python -m pytest -q test_scripts/test_object_multi_select.py`.
3. Add selection-set state and batch request types.
4. Implement same-page-only selection enforcement and batch controller/model paths.
5. Re-run `python -m pytest -q test_scripts/test_object_multi_select.py test_scripts/test_object_controller_flow.py`.
6. Commit.

### Task 3: Single-object resize

**Files**
- Modify: `view/pdf_view.py`
- Modify: `model/object_requests.py`
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Create: `test_scripts/test_object_resize.py`

**Steps**
1. Write failing tests for rect resize, textbox resize with unchanged font size, rotated textbox resize, and single-select-only handles.
2. Run `python -m pytest -q test_scripts/test_object_resize.py`.
3. Add resize handles, resize hit-testing, preview visuals, and resize request types.
4. Implement rect/textbox resize mutations in the model.
5. Re-run `python -m pytest -q test_scripts/test_object_resize.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_manipulation_gui.py`.
6. Commit.

### Task 4: App-owned images

**Files**
- Modify: `view/pdf_view.py`
- Modify: `controller/pdf_controller.py`
- Modify: `model/object_requests.py`
- Modify: `model/pdf_model.py`
- Create: `test_scripts/test_image_objects_model.py`
- Create: `test_scripts/test_image_objects_gui.py`

**Steps**
1. Write failing tests for file-insert, clipboard-paste, hit detection, move, rotate, resize, delete, and same-page multi-select.
2. Run `python -m pytest -q test_scripts/test_image_objects_model.py test_scripts/test_image_objects_gui.py`.
3. Add image insert actions and controller entry points.
4. Add app-owned image identity + model mutation pipeline.
5. Re-run the image test slice plus neighboring object GUI tests.
6. Commit.

### Task 5: Verification and docs

**Files**
- Modify: `TODOS.md`
- Modify: `docs/plans/2026-04-09-backlog-execution-order.md`
- Modify: `docs/plans/2026-04-10-backlog-checklist.md`
- Modify: `docs/PITFALLS.md`
- Modify if boundaries moved: `docs/ARCHITECTURE.md`

**Steps**
1. Add or update the mixed-sample GUI verifier to cover:
   - objects mode rect/image operations
   - text edit mode textbox operations
2. Run:
   - `python -m pytest -q test_scripts/test_interaction_modes.py`
   - `python -m pytest -q test_scripts/test_object_multi_select.py test_scripts/test_object_resize.py`
   - `python -m pytest -q test_scripts/test_image_objects_model.py test_scripts/test_image_objects_gui.py`
   - `python -m pytest -q test_scripts/test_object_manipulation_gui.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_controller_flow.py test_scripts/test_object_requests.py test_scripts/test_add_textbox_atomic.py`
   - live GUI verification script for the mixed sample
3. Update tracker/checklist/TODO docs with the shipped behavior and remaining native-image follow-up.
4. Commit.

## Test cases and scenarios

- Switching to `objects mode` prevents browse text selection from starting
- Switching to `text edit mode` prevents rect/image manipulation
- `Shift+click` adds/removes objects "selection" on the same page
- Selecting an object on another page resets the set instead of creating cross-page batches
- Batch move/delete works for same-page selection
- Single-object resize works for rects, images, and textboxes
- Textbox resize preserves font size and reflows text
- Rotate handle and resize handles remain clickable even when outside bbox edges
- File-inserted image becomes a stable app-owned object after save/reload
- Clipboard-pasted image becomes a stable app-owned object
- Undo/redo works across image and textbox manipulation operations

## Test reuse and new tests (this round)

This plan intentionally reuses existing regression suites in `test_scripts/` so we add the minimum new tests needed for the missing behaviors.

### Reuse (extend or keep green)

- Reuse: `test_scripts/test_object_manipulation_gui.py`
  - Extend for mode routing: in `browse`, do not start object manipulation; in `objects`, do not start browse text selection.
  - Reuse existing coverage for: object-vs-text press priority, rotate-handle hit arming, and request emission.
- Reuse: `test_scripts/test_object_manipulation_model.py`
  - Extend for any new object kinds (image objects) and resize mutations.
  - Reuse existing coverage for: object identity + hit detection, rect move/delete, textbox rotation metadata, and marker cleanup after move/rotate/delete.
- Reuse: `test_scripts/test_object_controller_flow.py`
  - Extend for batch operations (move/delete) once selection-set requests exist.
- Reuse: `test_scripts/test_object_requests.py`
  - Extend for new request dataclasses/enums: interaction mode, selection-set ops, batch ops, resize ops, and image insert ops.
- Reuse: `test_scripts/test_text_editing_gui_regressions.py`
  - Extend for `text_edit` mode-only textbox manipulation rules (no rect/image manipulation).
  - Reuse existing coverage for: editor transparency, rotated editor geometry, selection strict-hit, mask lifecycle, save/save-as finalization, undo/redo safety, and mode switch semantics.
- Reuse: `test_scripts/test_browse_selection_gui_regressions.py`
  - Keep green as a browse-mode guardrail: selection must remain strict-hit and not regress via object-mode changes.
- Reuse: `test_scripts/test_edit_geometry_stability.py`
  - Keep green to ensure textbox geometry changes (especially resize) do not reintroduce drift/anchor regressions.
- Reuse: `test_scripts/test_add_textbox_atomic.py`
  - Keep green; extend only if textbox identity/selection plumbing changes.

### New tests (missing coverage to add)

The following behaviors do not have dedicated coverage yet and need new tests (added as new files unless otherwise noted).

- Create: `test_scripts/test_interaction_modes.py`
  - Mode switching is explicit and deterministic: `browse` <-> `objects` <-> `text_edit`.
  - Switching modes clears incompatible transient state (armed drag, armed rotate, selection overlays).
  - Mode gating: in `objects`, text selection does not start; in `text_edit`, rect/image manipulation does not start; in `browse`, object manipulation does not start.
- Create: `test_scripts/test_object_multi_select.py`
  - Same-page only multi-select: click selects single, `Shift+click` toggles add/remove, click on another page resets set.
  - Batch delete emits one batch request and deletes all selected on the active page.
  - Batch move moves all selected by a single delta on the active page.
  - No cross-page selection set exists in this tranche (explicitly asserted).
- Create: `test_scripts/test_object_resize.py`
  - Resize handles exist for single-select only; multi-select shows group outline only.
  - Rect resize updates bbox and hit testing follows new bbox.
  - Textbox resize updates textbox rect only (font size unchanged); text reflows inside the new bounds.
  - Rotated textbox resize preserves rotation metadata and remains interactive.
  - Handle hit testing works when handles extend beyond bbox edges.
- Create: `test_scripts/test_image_objects_model.py`
  - App-owned image object identity is stable (id, rect, rotation) and persists through save/reload.
  - Image hit testing uses object identity, not loose page image-block scans.
  - Image move/rotate/resize/delete mutations update identity and rendering metadata correctly.
- Create: `test_scripts/test_image_objects_gui.py`
  - Insert image from file picker path emits the correct insert request (use a test double; do not require a real OS file dialog).
  - Paste image from clipboard emits the correct insert request (use a test double; do not require OS clipboard integration in CI).
  - After insertion, image is selectable and supports move/rotate/resize/delete in `objects` mode.
  - Undo/redo covers image insertion and subsequent manipulations.

### Test running slices (kept tight)

- Modes + routing: `python -m pytest -q test_scripts/test_interaction_modes.py test_scripts/test_object_manipulation_gui.py test_scripts/test_text_editing_gui_regressions.py -k "mode or objects or browse"`
- Multi-select: `python -m pytest -q test_scripts/test_object_multi_select.py test_scripts/test_object_controller_flow.py test_scripts/test_object_requests.py`
- Resize: `python -m pytest -q test_scripts/test_object_resize.py test_scripts/test_object_manipulation_model.py test_scripts/test_edit_geometry_stability.py`
- Image objects: `python -m pytest -q test_scripts/test_image_objects_model.py test_scripts/test_image_objects_gui.py test_scripts/test_object_manipulation_gui.py`

## Assumptions and defaults

- `objects mode` excludes textboxes in this tranche
- `text edit mode` owns all textbox manipulation plus word editing
- Multi-select is same-page only now, but internal state should not block later cross-page support
- Textbox resize changes bounds only; it does not scale font size
- App-owned images support both file insert and clipboard paste in the first image tranche
- Native PDF image manipulation is explicitly deferred to a later child plan
