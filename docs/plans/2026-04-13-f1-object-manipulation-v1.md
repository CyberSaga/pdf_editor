# F1 Object Manipulation V1

## Goal

Ship first-class manipulation for app-owned objects without destabilizing text editing or native PDF content.

## Scope

Supported in v1:
- new app-created textboxes
- rectangle annotations created by this app
- actions: select, move, delete, rotate textbox
- undo/redo through snapshot-backed commands

Not supported in v1:
- resize handles
- native/imported PDF images
- legacy textboxes created before app-owned metadata
- multi-object selection
- FreeText migration / broad annotation-object support

## Design

- View owns selection visuals and drag gestures.
- Controller owns typed requests, snapshot command creation, and render invalidation.
- Model owns object discovery and mutation.
- New textbox identity is persisted with a hidden companion annotation marker carrying:
  - `pdf_editor_object_id`
  - `pdf_editor_object_kind=textbox`
  - rotation and visual rect metadata
- Rectangle annotations use their own app-owned annotation metadata and stable annotation identity.

## Verification

Required automated slice:
- `python -m pytest -q test_scripts/test_object_requests.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_controller_flow.py test_scripts/test_object_manipulation_gui.py test_scripts/test_add_textbox_atomic.py`

Manual mixed-sample check:
1. Create a new textbox.
2. Create a rectangle annotation.
3. Move each object.
4. Rotate the textbox.
5. Delete each object.
6. Undo and redo every action.

## Current Status

As of 2026-04-13:
- request/model/controller/view scaffolding is landed
- focused automated object tests are green
- a temporary Windows low-level verification harness can create the mixed sample reliably
- low-level injected selection/manipulation of the created objects is still not fully reliable, so manual verification is not yet a full closeout signal

## Future F1 Follow-Ups

- Imported/native PDF images
- Resize handles for supported objects
- Multi-select across supported objects
- A dedicated `objects mode` for object-focused manipulation

### Objects Mode Intent

- Keep it separate from browse mode so text selection stays predictable.
- Let it become the primary place for object selection, move, rotate, delete, and eventually resize/multi-select.
- Reuse the same app-owned object identity layer introduced in F1 v1 instead of creating a parallel object system.
