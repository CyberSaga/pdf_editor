# F1 Child Plan -- Object Manipulation

## Goal

Add first-class manipulation for non-text page objects and edited text boxes, including selection, move, resize, delete, and rotation where the underlying PDF representation supports it.

## Success Criteria

- Users can select supported objects without entering text-edit mode.
- Selected objects can be moved and deleted with undo/redo support.
- Text boxes created by this app can be rotated after creation.
- Unsupported native PDF objects fail clearly instead of behaving inconsistently.

## Scope

1. Inventory and classify movable objects:
   - app-created text boxes
   - annotations/shapes added by this app
   - imported image-like objects, if the current model can identify them safely
2. Introduce a typed object-selection/request boundary.
3. Implement object move/delete command flow with snapshot safety.
4. Add rotation support for app-owned text boxes.
5. Add visual handles/selection affordances in the view.

## Out of Scope

- Full arbitrary PDF content editing for every native object type.
- Rotation for unsupported embedded objects with no stable identity.
- Group transforms or multi-object selection in the first tranche.

## Workstreams

- Model: object discovery, stable identifiers, mutation primitives.
- Controller: typed manipulation commands and undo/redo integration.
- View: hit-testing, selection chrome, drag/rotate affordances.
- Tests: object identity, command safety, and GUI regressions.

## Risks

- Native PDF objects may not expose stable editable identities.
- Rotation can drift object geometry if view-space and PDF-space transforms diverge.
- Snapshot size may grow if object edits are implemented too coarsely.

## Exit Evidence

- Focused model/controller tests for object selection and mutation.
- GUI tests for select, move, delete, and rotate flows.
- Manual verification on a mixed document containing text boxes, shapes, and images.
