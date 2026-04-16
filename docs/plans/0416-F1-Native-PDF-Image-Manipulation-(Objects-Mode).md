# F1 Native PDF Image Manipulation (Objects Mode) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users select and manipulate *native* (pre-existing) PDF images in `objects mode` (`操作物件`) with move/resize/rotate/delete + multi-select, without using redactions (so text overlays aren’t destroyed).

**Architecture:** Detect native images by parsing page content streams into PDF operators, locating image XObject invocations (`/<name> Do`) and their `cm` matrices. Manipulation rewrites those operators (update `cm`, or remove the whole image invocation block) and keeps MVC boundaries (Qt-free requests; view/controller unchanged except allowing the new kind).

**Tech Stack:** Python, PyMuPDF (`fitz`), existing MVC (view/controller/model), pytest + existing Qt GUI regression harness.

---

### Task 1: Add failing tests for native-image hit + kind

**Files:**
- Create: `test_scripts/test_native_pdf_images_model.py`
- Modify: `model/pdf_model.py`

**Step 1: Write the failing test**
- Create a PDF in-temp that contains an image XObject but no app marker:
  - Use `fitz.open(); page=doc.new_page(...); page.insert_image(...); doc.save(path)`
- Open with `PDFModel.open_pdf(path)`
- Assert `model.get_object_info_at_point(1, point_inside)` returns:
  - `object_kind == "native_image"`
  - `supports_move/delete/rotate == True`
  - `rotation` inferred as `0` initially

**Step 2: Run test to verify it fails**
Run: `python -m pytest -q test_scripts/test_native_pdf_images_model.py -k native_image_hit`
Expected: FAIL (hit is `None` today)

**Step 3: Minimal implementation to make the hit test pass**
- In `model/pdf_model.py`:
  - Add a new supported kind string: `"native_image"`.
  - Extend `get_object_info_at_point(...)`:
    - Keep existing app-marker hit behavior first.
    - If no app hit: fall back to native-image hit (see Task 2 implementation details).

**Step 4: Run test**
Expected: PASS.

**Step 5: Commit**
Commit message: `feat: allow selecting native PDF images in objects mode`


### Task 2: Implement native image discovery by parsing content streams (operator-based, not substring matching)

**Files:**
- Create: `model/pdf_content_ops.py` (or `model/pdf_content_ops.py`-like helper module; keep Qt-free)
- Modify: `model/pdf_model.py`

**Step 1: Write the failing test**
In `test_scripts/test_native_pdf_images_model.py` add:
- A case with 2 images overlapping: clicking inside both returns the *topmost* (last in content order).
- Assert deterministic selection: later `Do` wins.

**Step 2: Run test to verify it fails**

**Step 3: Implement operator parser + native-image inventory**
Implement a minimal PDF content stream parser that produces an operator list:
- Tokenize into: numbers, names (`/Image19`), operators (`q`, `Q`, `cm`, `Do`), arrays/dicts are not needed for content streams in this slice.
- Parse into `[(op_name, operands, start_idx, end_idx)]` where `start_idx/end_idx` are token indexes (or byte offsets) sufficient to reserialize with edits/removals.
- Build name→xref mapping using `page.get_images(full=True)` (it includes `name` and `xref`).
- Walk operators in order:
  - Track graphics state depth via `q`/`Q` stack.
  - For each `Do` with operand `/<name>` where `<name>` maps to an image xref:
    - Associate it with the most recent `cm` in the same graphics scope.
    - Create a `NativeImageInvocation` record:
      - `page_num`
      - `occurrence_index` (0-based in encountered order)
      - `xobject_name` (e.g. `Image19` without `/`)
      - `xref`
      - `cm` matrix values (a,b,c,d,e,f)
      - `content_stream_xref`
      - pointers to the `cm` operator tokens and the `q..Q` block boundaries containing it (needed for delete)
    - Compute bbox by applying matrix to unit square (0,0)-(1,1) and taking min/max (use `fitz.Point` math, or manual).
    - Infer rotation as one of `{0,90,180,270}` based on sign/magnitude pattern of (a,b,c,d) with tolerance.

**Step 4: Wire fallback hit test**
- In `PDFModel.get_object_info_at_point`:
  - If no app object: enumerate invocations; choose the last whose bbox contains the point.
  - Set:
    - `object_kind="native_image"`
    - `object_id=f"native_image:{page_num}:{occurrence_index}"`
    - `supports_rotate=True`

**Step 5: Run tests**
Run: `python -m pytest -q test_scripts/test_native_pdf_images_model.py -k native_image_hit`
Expected: PASS.

**Step 6: Commit**
Commit message: `feat: parse page content to hit-test native images`


### Task 3: Add failing tests for move/resize (cm rewrite)

**Files:**
- Modify: `test_scripts/test_native_pdf_images_model.py`
- Modify: `model/pdf_model.py`

**Step 1: Write failing tests**
Add:
- `test_move_native_image_updates_hit_location()`
  - Select native image
  - Call `model.move_object(MoveObjectRequest(... destination_rect=...))`
  - Assert old point misses, new point hits with same `object_id`
- `test_resize_native_image_updates_hit_location()` (reuse `ResizeObjectRequest` path via move)

**Step 2: Run to see FAIL**

**Step 3: Implement cm rewrite**
In `PDFModel.move_object` (early branch before app-object lookup):
- If `request.object_kind == "native_image"`:
  - Resolve `occurrence_index` from `request.object_id`
  - Recompute invocations; pick that index
  - Compute a new `cm` from `destination_rect` and the invocation’s current quantized rotation:
    - rot=0: `(w,0,0,h,x0,y0)`
    - rot=90: `(0,h,-w,0,x1,y0)`
    - rot=180: `(-w,0,0,-h,x1,y1)`
    - rot=270: `(0,-h,w,0,x0,y1)`
  - Rewrite just the 6 operands of the invocation’s `cm` operator.
  - Re-serialize operator stream back to bytes (space-separated tokens, newline between ops is fine).
  - `doc.update_stream(content_stream_xref, new_bytes)`
  - Append `pending_edits` for the destination rect (and/or whole page) and bump `edit_count`.

**Step 4: Run tests**
Run: `python -m pytest -q test_scripts/test_native_pdf_images_model.py -k \"move_native_image or resize_native_image\"`
Expected: PASS.

**Step 5: Commit**
Commit message: `fix: move and resize native images by rewriting cm operators`


### Task 4: Add failing tests for rotate (keep bbox constant)

**Files:**
- Modify: `test_scripts/test_native_pdf_images_model.py`
- Modify: `model/pdf_model.py`

**Step 1: Write failing test**
- `test_rotate_native_image_preserves_bbox_and_updates_rotation()`
  - Select native image, store bbox
  - Call `rotate_object(rotation_delta=90)`
  - Hit again at a point in bbox
  - Assert `rotation == 90`
  - Assert bbox remains the same (within a small tolerance)

**Step 2: Run to confirm FAIL**

**Step 3: Implement rotate for native images**
In `PDFModel.rotate_object` (early branch):
- Resolve invocation by occurrence index.
- Compute new rotation = (old + delta) % 360, quantized to 0/90/180/270.
- Keep the same bbox rectangle and rewrite `cm` using the same bbox but new rotation (same formulas as Task 3, using the *current bbox* as the rect).

**Step 4: Run test**
Expected: PASS.

**Step 5: Commit**
Commit message: `fix: rotate native images by rewriting cm while preserving bbox`


### Task 5: Add failing tests for delete (remove invocation block + resources cleanup)

User decision: **Delete should remove the image invocation block (operator-based), and update page `/Resources /XObject` accordingly.**

**Files:**
- Modify: `test_scripts/test_native_pdf_images_model.py`
- Modify: `model/pdf_model.py`
- Modify: helper module from Task 2 (serializer/parser)
  
**Step 1: Write failing tests**
Add:
- `test_delete_native_image_removes_invocation_and_updates_resources()`
  - Select a native image
  - Capture `page_xref_object = doc.xref_object(page.xref)` or `doc.xref_get_key(page.xref,"Resources")`
  - Call `delete_object(DeleteObjectRequest(...))`
  - Assert hit is now `None`
  - Assert the content stream no longer contains the removed image invocation (by re-parsing operators and ensuring that occurrence count decreased and/or the removed occurrence is gone)
  - Assert that if the deleted image name is no longer referenced by any `Do` on that page, it is removed from `/Resources /XObject`
- Add a second test where the same image name is used twice:
  - Delete only one occurrence
  - Assert `/XObject` entry remains if still referenced.

**Step 2: Run and confirm FAIL**

**Step 3: Implement deletion by operator removal**
In `PDFModel.delete_object` (early branch for `"native_image"`):
- Resolve invocation by occurrence index.
- Remove the invocation’s enclosing block safely:
  - Prefer removing from the `q` that opened the graphics state for this image through the corresponding closing `Q`, when that `q..Q` contains exactly one image `Do` (the target).
  - Otherwise remove the minimal sequence covering:
    - the `cm` operator + the `Do` operator (and keep surrounding content).
- Update the content stream bytes via `doc.update_stream(...)`.
- Re-parse all streams for that page to compute remaining referenced XObject names.
- Update page resources:
  - Read resources via `doc.xref_get_key(page.xref, "Resources")` which returns a dict string.
  - Parse that dict string into a structured PDF dict (minimal parser: names, dicts `<<>>`, arrays `[]`, refs `n n R`).
  - If `/XObject` exists: remove keys for image names that are no longer referenced by content streams.
  - Serialize dict back to a valid PDF dict string and set with `doc.xref_set_key(page.xref, "Resources", <dict_str>)`.

**Step 4: Run tests**
Run: `python -m pytest -q test_scripts/test_native_pdf_images_model.py -k delete_native_image`
Expected: PASS.

**Step 5: Commit**
Commit message: `fix: delete native images by removing Do block and pruning XObject resources`


### Task 6: UX entry point: allow selecting native images in objects mode (view gating) + GUI regression

**Files:**
- Modify: `view/pdf_view.py`
- Modify or Extend: `test_scripts/test_object_manipulation_gui.py` (preferred) or create `test_scripts/test_native_pdf_images_gui.py`

**Step 1: Write failing GUI test**
- Build a temp PDF with a native image (same helper).
- Open GUI test harness, switch mode to `objects`.
- Click the image.
- Assert selection visuals appear (existing helpers in GUI test suite).
- Drag slightly; assert a `MoveObjectRequest` is emitted with `object_kind == "native_image"`.

**Step 2: Run to see FAIL**

**Step 3: Implement**
- In `view/pdf_view.py`, when `current_mode == "objects"` set:
  - `allowed_kinds = ("rect", "image", "native_image")`
- Keep `browse` behavior unchanged.

**Step 4: Run GUI test slice**
Run: `python -m pytest -q test_scripts/test_object_manipulation_gui.py -k native_image`
Expected: PASS.

**Step 5: Commit**
Commit message: `fix: enable selecting native images in objects mode`


### Task 7: Manual verification (UX-focused)

**Files:**
- (Optional scratch) `tmp/manual_verify_native_images_qtest.py` (do not commit unless requested)

**Steps:**
- Launch the real GUI build.
- Open `test_files/2.pdf` (Page 3 has images per inspection).
- In `objects mode`:
  - Select a native image
  - Move, resize, rotate 90
  - Delete
  - Undo/redo each step
- Verify: no text overlay disappears (key regression guardrail).

Record evidence (commands run + observed behaviors) in:
- `docs/PITFALLS.md` (only if a new pitfall/constraint is discovered), otherwise keep it in tracker notes.


### Task 8: Close Phase 6 (F1) in trackers + update test index

**Files:**
- Modify: `docs/plans/2026-04-09-backlog-execution-order.md`
- Modify: `docs/plans/2026-04-10-backlog-checklist.md`
- Modify: `TODOS.md`
- Modify: `test_scripts/TEST_SCRIPTS.md`

**Steps:**
- Mark `F1` as `done` with evidence:
  - model tests slice
  - GUI slice
  - manual check on `test_files/2.pdf` (plus any other sample you used)
- Add “Native PDF image manipulation” to the recommended test slices section in `test_scripts/TEST_SCRIPTS.md`.

Commit message: `docs: close F1 native image manipulation follow-up`

---

## Test Plan (one-liners)
- Model: `python -m pytest -q test_scripts/test_native_pdf_images_model.py`
- Neighbor guardrails: `python -m pytest -q test_scripts/test_image_objects_model.py test_scripts/test_object_manipulation_model.py`
- GUI: `python -m pytest -q test_scripts/test_object_manipulation_gui.py -k \"objects and (image or native)\"`

## Assumptions / Defaults
- Native-image detection is limited to image XObject invocations (`/<name> Do`) with a resolvable `cm` in the same graphics scope.
- Rotation is quantized to `{0,90,180,270}` (matches current `rotation_delta` int semantics).
- Delete removes only the targeted invocation (not the underlying image xref object), and prunes `/Resources /XObject` keys only when unused on that page.
- If the parser cannot safely locate a well-scoped removal region, deletion returns `False` (no mutation) rather than attempting a risky rewrite.
