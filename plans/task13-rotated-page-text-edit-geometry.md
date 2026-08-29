# Task 13 — rotated-page text editing: visual-space model boundary

## Goal

Make inline text editing work on `/Rotate 90/180/270` pages in the GUI: editable-region
outlines and hover highlight land on the visible glyphs, a click on the visible glyphs opens
the editor over them with the correct on-screen orientation, the plan-backed preview renders
inside that editor, and Apply produces a plan-backed (Tier 0) commit — the P3-D manual smoke
gate (`docs/history/reports/2026-08-29-p3d-manual-smoke-attempt.md`).

## Diagnosis (2026-08-29, five-segment trace + model probe on the smoke fixture)

Three independent defects, none introduced by P3-D (the GUI read path has never converted):

1. **Coordinate-space class bug.** Every text-geometry value the model exposes to the view is
   unrotated *dict space* (`page.get_text("dict"/"rawdict")`): `EditableSpan.bbox/origin`,
   `EditableParagraph.bbox`, `TextBlock.rect/layout_rect`, `TextHit.target_bbox`, glyph rects,
   selection bounds/lines. `EditableSpan.rotation`/`TextHit.rotation` is the *text-direction*
   rotation in dict space, never `/Rotate`. The view is uniformly *visual space* (`page.rect` /
   `get_pixmap`): `_doc_rect_to_scene_rect` and `_scene_pos_to_page_and_doc_point` are pure
   scale+offset. The controller facade forwards verbatim. On `/Rotate 0` both spaces coincide,
   so no existing test or smoke could see it. Probe on the smoke fixture (`/Rotate 270`,
   612×792 mediabox): index bbox of `Price` = (72,101,127,125) [dict, top-left]; raster ink =
   (102,426,180,539) [visual, bottom-left]; `get_text_info_at_point` hits the dict centre and
   misses the visual centre.
2. **False style override.** `pdf_view.py:3751/4268` store the raw span font
   (`"Helvetica"`) in `editing_font_name`; `_sync_font_combo_state` stores the normalized
   `_qt_font_to_pdf(...)` (`"helv"`) in `_editing_initial_font_name` and never overwrites
   `editing_font_name` (hasattr guard). `build_style_overrides` compares the two →
   `font_family="Helvetica"` on an untouched session → `plan.py:297`
   `STYLE_OVERRIDE_PRESENT` → legacy fallback. Rotation-independent; masked in GUI tests that
   preset both attributes to `"helv"`.
3. **Plan preview refuses rotated editors.** `_install_plan_preview_hook` returns when
   `rotation != 0` ("the Tier 0 raster clip assumes an unrotated editor frame"). Once the hit
   rotation is the visual one (270 on the smoke page) the exact preview would silently fall
   back to CSS. The raster is a visual-space clip; the proxy is rotated by `setRotation`, so
   the image must be counter-rotated into the proxy-local frame exactly as
   `_capture_frozen_first_frame` already does for the frozen first frame.

## Design

**Chokepoint = the model's public text-geometry surface speaks displayed (visual) space.**
Precedent: PITFALLS "PyMuPDF annot geometry is unrotated-space on BOTH write and read"
(`AnnotationTool` derotate-on-write / rotate-on-read), `add_textbox(visual_rect=)`,
ARCHITECTURE §10.1 space discipline. The block index, resolve pipeline, reopen anchors and
the text-commit engine stay dict space (they already convert internally via
`_dict_space_to_visual`); the controller stays a pass-through; the view keeps its visual-only
converters.

- `model/geometry.py`: `visual_to_unrotated_point/rect`, `unrotated_to_visual_point/rect`,
  `visual_text_rotation(page_rotation, text_rotation)` = `(text + page) % 360` (both
  clockwise-positive in y-down coordinates: `rotation_degrees_from_dir` uses `atan2(dy, dx)`,
  Qt `setRotation` is clockwise, `/Rotate` is clockwise).
- `PDFModel` public wrappers convert in/out, the existing bodies become `_..._unrotated`:
  `get_text_info_at_point` (point in; `target_bbox`, `rotation` out),
  `get_char_context_at_point` (point in; glyph rects out), `get_text_selection_snapshot`
  (+`get_text_in_rect`, `get_text_selection_bounds`; rect in, bounds out),
  `get_text_selection_snapshot_from_run` (end point in, bounds out),
  `get_text_selection_lines` (points in, rects out), new `get_text_targets(page_idx, mode,
  blocks_fallback)` / `get_text_blocks_visual(page_idx)` returning `dataclasses.replace`
  copies with visual `bbox`/`rect`/`layout_rect`/`rotation` for the outline drawer.
  Internal callers use the `_unrotated` bodies.
- Write side: `pdf_text_edit.edit_text` and `derive_tier0_preview_target` derotate `rect` /
  `new_rect` at entry (`_visual_rect_to_unrotated_rect`); the cross-page move path derotates
  `source_rect`/`destination_rect` the same way. Legacy page-bounds clamps against visual
  `page.rect` are pre-existing and out of fence (registered).
- Controller: `iter_text_targets` / `get_text_blocks` forward to the new model methods.
- View: `_sync_font_combo_state` seeds `_editing_initial_font_name` from the value
  `editing_font_name` already holds (same normalization on both sides of the comparison);
  `_install_plan_preview_hook` installs for every rotation; `apply_plan_preview` counter-rotates
  the raster by the editor's configured rotation (`-90` for 90, `+90` for 270, `180` for 180).

## Fences

No change to `EditableSpan`/block index space; no rotation math in the view converters; no
change to admission/rollout defaults; legacy insert clamps untouched (registered follow-up).

## Steps

1. Red: `test_scripts/test_text_geometry_page_rotation.py` (model surface, ink oracle on
   `/Rotate 0/90/180/270`), `test_scripts/test_text_edit_rotated_page_gui.py` (offscreen MVC:
   outlines/hover/click/editor rotation/style override/plan preview counter-rotation/plan-backed
   Apply). Show the failing log.
2. Green: geometry helpers + model wrappers + controller forwards + write-side derotation.
3. Green: view style-override seed + rotated plan preview.
4. Adversarial review round; docs (PITFALLS, ARCHITECTURE §2.4/§7.2, TODOS, smoke report retest
   section); gates.

## Record

- 2026-08-29: `32a7630` (270° corner `y1→y0`) reverted in `8eb91b5` — the branch it changed
  never executes for horizontal text on a rotated page (`rotation` was the dict text direction).
