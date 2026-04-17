# Native-Image-Review-Follow-Up-Plan

## Summary
Apply a small follow-up slice after the P0 native-image fixes to close the remaining high-signal review items without reopening coordinate risk.

Chosen default:
- Use a validation-first approach for the CropBox/MediaBox concern.
- Fix the fragile shared-image fixture immediately.
- Add targeted regressions for cropped pages and genuine no-`cm` invocations.
- Only change bbox Y-flip math if the new cropped-page regression proves the current mapping is wrong.

## Key Changes
- Harden the shared-image test fixture in `test_scripts/test_native_pdf_images_model.py`.
  - Replace the hardcoded `/fzImg0 Do` with the actual image name discovered from `page.get_images(full=True)`.
  - Keep the fixture structure the same otherwise so existing delete/shared-resource assertions stay meaningful.

- Add a cropped-page native-image regression before touching coordinate math.
  - Build a PDF whose page has a `CropBox` different from its `MediaBox`, with a native image placed before cropping.
  - Assert `discover_native_image_invocations(...)` and hit-testing return the same visual bbox as PyMuPDF’s page-level image APIs.
  - If this fails under the current `_bbox_from_stream_cm(...)` mapping, then the implementation change in this slice is:
    - derive the stream-space page height from the page’s unrotated PDF box, not `page.rect.height`
    - keep all returned bbox values in the existing fitz visual coordinate space
    - add a brief architecture/pitfall note that native-image bbox reconstruction uses raw stream coordinates and must not depend on cropped visual height

- Add a real no-`cm` fallback regression.
  - Construct or rewrite a content stream so an image `Do` is valid without an explicit local `cm` for that invocation.
  - Assert discovery still finds the native image through the fallback path, and hit-testing remains correct.
  - Keep move/resize behavior unchanged for now: if `cm_operator_index is None`, mutation still returns `False` rather than synthesizing a new operator in this slice.

- Preserve the current P0 invariants.
  - Keep ancestor `q` bubbling exactly as implemented.
  - Keep content-order `occurrence_index` as the object identity used by the UI.
  - Keep primary bbox/rotation derivation from parsed `cm`, with per-xref placement lookup only as fallback when `cm` is unavailable.

## Test Cases And Scenarios
- Shared-resource fixture stability:
  - shared-image delete test still passes when the duplicated `Do` uses the discovered XObject name rather than `fzImg0`
- Cropped-page correctness:
  - uncropped baseline still passes
  - cropped page with different `CropBox` and `MediaBox` returns the expected visual bbox
  - if bbox mapping changes, rotate/move/delete on the cropped page still target the intended image
- No-`cm` fallback:
  - discovery survives an invocation with `cm_operator_index is None`
  - hit-testing works for that image
  - mutation failure path stays explicit and stable for no-`cm` images
- Guardrails:
  - rerun `test_scripts/test_native_pdf_images_model.py`
  - rerun the native-image GUI slice in `test_scripts/test_object_manipulation_gui.py`
  - rerun `test_scripts/test_interaction_modes.py`

## Assumptions
- The immediate must-fix item from the review is the fragile `fzImg0` fixture.
- The CropBox/MediaBox comment is treated as a hypothesis to verify, not as an automatic code change.
- No new caching, serializer compaction, or double-parse optimization is included in this slice.
- No-`cm` images remain selectable but not yet movable/resizable unless a later plan explicitly adds operator synthesis.
