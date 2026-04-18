# Image Manipulation Behavior Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix object-mode image manipulation so left-side resize handles move the left edge, images can overlap without destroying or displacing each other, and selection/edit overlays follow moved images immediately.

**Architecture:** Keep the resize interaction logic in the view, because handle semantics and live preview are UI-owned. Keep image persistence and overlap safety in the model, because the current app-image move/rotate implementation uses redaction and reinsertion, which is the source of overlap breakage. Keep controller changes minimal: it should continue to record snapshot commands, while the view immediately rebases local selection state after successful move/resize emits.

**Tech Stack:** Python, PySide6, PyMuPDF (`fitz`), existing MVC object manipulation flow, pytest GUI/model tests.

---

## Summary

- Fix resize-handle geometry so corner handles move their own edges instead of always stretching from bottom-right.
- Replace app-image move/rotate persistence so overlapping images survive and can stack visually.
- Update object-selection overlays immediately after move/resize in `objects` / `text_edit` / `edit_text` modes, without waiting for the next click.
- Add focused regressions for left-handle behavior, overlap-safe image motion, and immediate overlay rebasing.

## Key Changes

### 1. View: make corner handles anchor the opposite corner correctly
- In `view/pdf_view.py`, change object resize interaction from the current “always modify `x1`/`y1`” logic to handle-aware geometry.
- On mouse press, determine which resize handle was hit and store a resize anchor such as `top_left`, `top_right`, `bottom_left`, or `bottom_right`.
- On mouse move, compute preview rect by moving only the edges owned by that handle:
  - `top_left`: move `x0` and `y0`, keep `x1`/`y1`
  - `top_right`: move `x1` and `y0`, keep `x0`/`y1`
  - `bottom_left`: move `x0` and `y1`, keep `x1`/`y0`
  - `bottom_right`: move `x1` and `y1`, keep `x0`/`y0`
- Clamp preview rect to a minimum width/height so handles cannot invert the box; if the drag crosses the opposite edge, clamp at the minimum instead of flipping handles mid-drag.
- Keep existing single-select resize handles; no UI redesign is needed in this slice.

### 2. Model: stop using image-removing redaction for app-inserted images
- In `model/pdf_model.py`, replace app-image `move_object(...)` and `rotate_object(...)` behavior that currently does:
  - `add_redact_annot(old_rect)`
  - `apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)`
  - `insert_image(...)`
- That path removes overlapping images and is the direct cause of “pushing others aside”.
- Implement app-image mutation using the same durable primitive already used for native images: rewrite the specific image placement rather than redacting a whole visual region.
- Decision-complete implementation direction:
  - Treat app-inserted images as true image placements plus marker metadata.
  - Store enough placement identity in the app-image marker payload to re-find the exact image invocation on later move/rotate/resize. The preferred identity is a page-local invocation key, not only `xref`, because the same image resource may be reused.
  - Reuse the existing content-stream/image-placement helper approach already present for native images, rather than introducing a second redaction-based image system.
  - For app-image `move_object`, rewrite the targeted image placement to the new rect and update marker payload/rect only.
  - For app-image `rotate_object`, rewrite the targeted placement rotation in place and update marker payload only.
  - For app-image `resize_object`, continue to delegate to move-with-new-rect once placement rewriting is fixed.
- Preserve overlap by never applying image-removing redactions during app-image move/rotate/resize.
- Do not change delete in this slice unless needed for consistency; if delete still relies on redaction and can remove overlapping neighbors, that should be called out and planned separately rather than silently expanded here.

### 3. View: make selection/edit overlays follow immediately after move/resize
- In `view/pdf_view.py`, after emitting a successful move/resize request for a selected object in `objects`, `text_edit`, or `edit_text` modes, immediately rebase local selection state to the preview rect.
- The current browse-mode release path already updates `_selected_object_info`; mirror that behavior for the object-edit modes.
- Also update `_selected_object_infos` and `_object_drag_start_doc_rects` when multi-select move completes, so the next drag starts from the new positions.
- Repaint selection rectangle and handles immediately with `_update_object_selection_visuals(...)`.
- This fix applies to both images and textboxes, but the user-visible target is images.
- Keep controller logic unchanged unless a focused test proves a view-side update is insufficient.

## Test Cases And Scenarios

### View / interaction regressions
- Add a failing test in `test_scripts/test_object_resize.py` for left-top handle drag:
  - start from a known bbox
  - simulate press on top-left handle, drag leftward/upward
  - assert emitted `ResizeObjectRequest.destination_rect` changes `x0`/`y0` while preserving `x1`/`y1`
- Add a second failing test for left-bottom handle drag:
  - assert `x0` and `y1` move, while `x1` and `y0` stay anchored
- Add a failing test in `test_scripts/test_object_manipulation_gui.py` or `test_scripts/test_interaction_modes.py` that after object-mode move release:
  - `_selected_object_info.bbox` updates immediately
  - selection visuals are redrawn on the new rect without requiring another click

### Model regressions
- Add a failing test in `test_scripts/test_image_objects_model.py` that inserts two overlapping app-image objects, moves one across the other, and asserts both images remain hit-testable afterward.
- Add a second failing test that rotates one overlapping app-image and asserts the other overlapping image still remains.
- Add a resize regression for app-images once the handle fix is in place, proving left-handle resize preserves the opposite edge in persisted hit boxes.

### Neighbor smoke
- Re-run:
  - `python -m pytest -q test_scripts/test_object_resize.py`
  - `python -m pytest -q test_scripts/test_image_objects_model.py`
  - `python -m pytest -q test_scripts/test_object_manipulation_gui.py test_scripts/test_interaction_modes.py -k "object or resize"`
  - `python -m pytest -q test_scripts/test_native_pdf_images_model.py`
- Native-image tests are required because the plan deliberately reuses native-image placement rewriting patterns.

## Assumptions And Defaults

- “Image” here primarily means app-inserted image objects (`object_kind == "image"`). Native-image overlap is already placement-based and should only be affected by the shared handle/overlay fixes.
- Corner handles should use standard opposite-corner anchoring for both axes, not just horizontal correction on the left side.
- Immediate “edit boxes follow images” means the object selection rectangle, rotate handle, and resize handles move immediately after release; it does not imply live page raster repaint during drag.
- This slice does not introduce auto-layout, collision avoidance, or snap-to-object behavior; overlap is allowed by design.
- If durable app-image placement identity is missing today, the implementation should extend marker payloads and migration logic only as much as needed to target the exact placement safely.

