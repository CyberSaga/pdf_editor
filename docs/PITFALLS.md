# PITFALLS.md — Known Failure Modes

> Add entries here whenever a non-obvious bug is fixed. Format:
> `## <short title>` / Area / Symptom / Cause / Fix / File

---

## Rotated text editors need proxy geometry, not just a stored rotation flag

**Area:** `view/text_editing.py`  
**Symptom:** Editing rotated text opens an upright editor, so the content orientation does not match the underlying PDF text.  
**Cause:** The edit flow carried `rotation` through hit-testing and width estimation, but never applied rotation-aware geometry or proxy rotation when creating the inline editor.  
**Fix:** Compute rotation-aware editor width/height/position before adding the widget to the scene, then rotate the proxy itself for `90/180/270` targets.  
**File:** `view/text_editing.py`

---

## Single-line htmlbox edits can drift the text anchor

**Area:** `model/pdf_model.py`  
**Symptom:** Editing a one-line text run that still fits on one line nudges the text right/down after commit, even though the user did not drag it.  
**Cause:** The generic htmlbox edit path re-laid out simple one-line edits with different text metrics than the original `insert_text(...)` origin.  
**Fix:** In `_apply_redact_insert(...)`, use an origin-preserving `insert_text(...)` fast path for horizontal single-line edits that still fit without wrapping; keep htmlbox for wrapped, dragged, and vertical edits.  
**File:** `model/pdf_model.py`

---

## Edit-mode outlines must follow selectable targets, not coarse blocks

**Area:** `view/pdf_view.py`  
**Symptom:** The dim edit outlines cover blank space around text, making empty areas look selectable.  
**Cause:** `_draw_all_block_outlines()` used block rectangles from the text index instead of the actual run/paragraph target boxes used by hit-testing.  
**Fix:** Build outlines from run boxes in `run` mode and paragraph boxes in `paragraph` mode, with block rectangles only as a fallback.  
**File:** `view/pdf_view.py`

---

## Transparent inline editors still need a separate scene mask

**Area:** `view/pdf_view.py`, `view/text_editing.py`  
**Symptom:** If the editor widget is transparent without any backing mask, the live edit text overlaps the already-rendered PDF text and becomes hard to read.  
**Cause:** The sampled page color was only being fed into the editor stylesheet; there was no separate scene-layer mask item covering the display-layer text under the editor.  
**Fix:** Keep the editor widget transparent, but create/update a sampled-color scene rect behind the editor proxy and remove it on finalize.  
**File:** `view/pdf_view.py`, `view/text_editing.py`

---

## Raw clip extraction returns chopped words for drag selection

**Area:** `model/pdf_model.py`, `model/tools/annotation_tool.py`
**Symptom:** Drag-selecting across the middle of a line copies clipped fragments like `a Beta Gamm` and draws a too-narrow highlight box instead of selecting the whole line.
**Cause:** Browse-mode selection previously delegated directly to `page.get_text(..., clip=...)` / clipped-word bounds, which obey the drag rectangle literally and do not snap to visual line units.
**Fix:** Resolve intersected line keys from the text index, then rebuild copied text and highlight bounds from the full visual lines in the model. Keep the view on the same typed controller/model boundary.
**File:** `model/pdf_model.py`, `model/tools/annotation_tool.py`

---

## Run-anchored browse selection cannot rely on cached `(block_idx, line_idx)` alone

**Area:** `model/pdf_model.py`
**Symptom:** When visually aligned words were inserted or extracted as separate runs, browse selection treated each word as its own line, producing output like `Beta\nGamma` instead of `Beta Gamma`.
**Cause:** The text index can contain separate runs on the same visual row with different cached block/line ids, so grouping by `(block_idx, line_idx)` alone is not enough for line snapping.
**Fix:** Build visual line groups from run reading order plus geometry overlap, then apply the start-run / end-run slicing rules against those visual groups.
**File:** `model/pdf_model.py`

---

## Browse selection must not use block fallback for run anchoring

**Area:** `model/pdf_model.py`, `controller/pdf_controller.py`, `view/pdf_view.py`
**Symptom:** A real mouse drag that starts or ends slightly inside row whitespace can appear to expand the boundary line to the whole row instead of staying anchored to the intended word/run.
**Cause:** `get_text_info_at_point(...)` has a backward-compatible block fallback for coarse text hits. Browse-mode selection was reusing that fallback for its run-anchored start/end resolution, so near-misses inside a text block silently degraded to the block's fallback span.
**Fix:** Add a strict hit-testing path (`allow_fallback=False`) and require browse-mode start/end resolution to use it. If exact run hit misses on mouse-up, the model then resolves the nearest run explicitly instead of accepting a coarse block fallback.
**File:** `model/pdf_model.py`, `controller/pdf_controller.py`, `view/pdf_view.py`

---

## Printer preferences must not overwrite source-following auto layout

**Area:** `src/printing/print_dialog.py`, `src/printing/qt_bridge.py`, `src/printing/platforms/linux_driver.py`  
**Symptom:** Opening native printer properties or switching printers can replace the dialog's `auto` paper/orientation with printer defaults, and mixed-size/mixed-orientation jobs can print with one stale layout for the whole job.  
**Cause:** The dialog used to merge printer-default `paper_size` and `orientation` back into the UI, and the Qt raster bridge only set page layout once before printing. Linux/mac direct-PDF routing also did not distinguish between source-following auto layout and explicit fixed-layout overrides.  
**Fix:** Keep paper/orientation app-owned and defaulting to `auto`, sync only duplex/color/DPI/copies from native properties, update raster layout from each rendered page's source rect, and force Linux/mac fixed-layout overrides onto raster instead of direct PDF submission.  
**File:** `src/printing/print_dialog.py`, `src/printing/qt_bridge.py`, `src/printing/platforms/linux_driver.py`

---

## Qt custom landscape page sizes must use portrait-ordered base dimensions

**Area:** `src/printing/qt_bridge.py`  
**Symptom:** Source pages that are truly landscape, such as A3 landscape sheets in a mixed job, can come out as portrait pages in generated PDF output even though the layout orientation is set to landscape.  
**Cause:** `QPageSize` for custom sizes expects the base dimensions in portrait order, then applies `QPageLayout.Landscape` separately. Passing already-landscape dimensions into `QPageSize` makes Qt flip the final PDF page back to portrait.  
**Fix:** Normalize custom point sizes to portrait order before creating `QPageSize`, and let orientation carry the landscape intent.  
**File:** `src/printing/qt_bridge.py`

---

## Open-time background work can steal responsiveness from the first visible page

**Area:** `controller/pdf_controller.py`  
**Symptom:** Large PDFs technically open quickly, but the UI still feels late to become usable because thumbnail rasterization and sidebar scans compete with the first visible page render. Repeated page jumps can also keep restarting visible-render generations and make navigation feel noisier than it needs to.  
**Cause:** The placeholder-first pipeline already existed, but open-time scheduling still kicked off thumbnail batches and deferred sidebar scans immediately, and `_schedule_visible_render(...)` created a fresh render generation for every repeated request even when one batch was already pending.  
**Fix:** Prioritize the initial visible page first. Start thumbnails/sidebar scans only after that page reaches high quality or a short fallback timer expires, and coalesce visible-render scheduling so repeated viewport/page-change requests reuse the queued batch instead of thrashing the render loop.  
**File:** `controller/pdf_controller.py`

---

## Save As default path can drift from the active tab

**Area:** `controller/pdf_controller.py`, `view/pdf_view.py`  
**Symptom:** `Ctrl+Shift+S` opens with a blank filename or the previously active tab's path after switching tabs or saving to a new file.  
**Cause:** The Save As dialog is view-owned, but its default path was never refreshed when the active session changed or when `save_as()` updated `saved_path`.  
**Fix:** Refresh the view's Save As default path from active-session metadata during `_refresh_document_tabs()`, and have `_save_as()` pass that value into `QFileDialog.getSaveFileName(...)`.  
**File:** `controller/pdf_controller.py`, `view/pdf_view.py`

---

## Wide thumbnail sidebars should center, not endlessly stretch

**Area:** `view/pdf_view.py`  
**Symptom:** Expanding the left sidebar makes thumbnails grow too wide and visually awkward instead of keeping a readable centered column.  
**Cause:** Thumbnail layout metrics previously used the full sidebar width for every resize, with no width cap or centering behavior.  
**Fix:** Cap thumbnail cell width and apply symmetric viewport margins when the sidebar exceeds that cap so the column remains centered.  
**File:** `view/pdf_view.py`

---

## PyMuPDF font sizes are floats, not ints

**Area:** `model/pdf_model.py`, `view/text_editing.py`  
**Symptom:** Fractional font sizes (e.g. 9.5pt) silently become 9pt after editing.  
**Cause:** `span["size"]` returns `float`; coercing to `int` truncates.  
**Fix:** Use `float` for all size fields in `EditTextRequest` and `MoveTextRequest`.  
**File:** `view/text_editing.py`

---

## Cross-page move controller signature drift breaks legacy callers

**Area:** `controller/pdf_controller.py` ??`move_text_across_pages`  
**Symptom:** Tests or integrations fail with `TypeError` (unexpected keyword args or missing positional args) when calling `move_text_across_pages(...)`.  
**Cause:** Controller entrypoint was narrowed to a typed `MoveTextRequest` only, while some call sites still pass legacy keyword arguments.  
**Fix:** Accept both `MoveTextRequest` and legacy kwargs, normalize into a request, and keep the typed pipeline underneath.  
**File:** `controller/pdf_controller.py`

---

## Windows parallel image rewrite disabled under pytest / non-script launchers

**Area:** `model/pdf_optimizer.py` ??`can_use_parallel_image_rewrite`  
**Symptom:** Image-heavy optimize-copy takes the serial path; tests expecting the parallel hook fail.  
**Cause:** Windows spawn-safety gate relied only on `__main__.__file__`, which may be unset or non-file under pytest/embedded launchers.  
**Fix:** Treat `sys.argv[0]` and `sys.executable` as valid spawn anchors when present, enabling multiprocessing when it is actually safe.  
**File:** `model/pdf_optimizer.py`

---

## TEXT_PRESERVE_LIGATURES breaks push-down re-insert

**Area:** `model/pdf_model.py` — `_push_down_overlapping_text`  
**Symptom:** Text containing ligatures (ﬁ, ﬀ) disappears after push-down; e.g. "misfits" → "mits".  
**Cause:** `get_text("dict", flags=TEXT_PRESERVE_LIGATURES)` returns ligature characters; `insert_text(fontname="helv")` silently drops glyphs it cannot encode.  
**Fix:** Use only `TEXT_PRESERVE_WHITESPACE` when fetching text for re-insertion; PyMuPDF expands ligatures to plain ASCII.  
**File:** `model/pdf_model.py`

---

## push-down insert_text(helv) drops non-Latin Unicode (€, emoji)

**Area:** `model/pdf_model.py` — `_push_down_overlapping_text`  
**Symptom:** Pushed-down spans containing `€` or emoji are silently replaced (e.g. `€` → `·`).  
**Cause:** Helvetica Type1 has no glyphs for U+20AC and above; PyMuPDF substitutes silently.  
**Fix:** Use `page.insert_htmlbox(rect, html, css=css)` for re-insertion; fall back to `insert_text(helv)` only on failure.  
**File:** `model/pdf_model.py`

---

## Vertical text double-redact erases adjacent horizontal text

**Area:** `model/pdf_model.py` — `edit_text` vertical branch  
**Symptom:** After editing a vertical text block, the first character of a nearby horizontal line disappears.  
**Cause:** The original flow ran Strategy A (`insert_htmlbox`) on the main page to measure height, then cleared the full `insert_rect` with `apply_redactions()`. If `insert_rect` spanned x≈0 it overlapped horizontal content.  
**Fix:** Measure `shrunk_rect` on a temp page; apply only one `insert_htmlbox(shrunk_rect)` to the main page. No second redact on the main page.  
**File:** `model/pdf_model.py`

---

## Continuous mode `change_scale` only redraws one page

**Area:** `controller/pdf_controller.py` — `change_scale`  
**Symptom:** After zooming in continuous mode, only the current page re-renders; others stay at old scale.  
**Cause:** `change_scale` called `display_page(page_idx, qpix)` instead of rebuilding the full scene.  
**Fix:** Set `self.view.scale = scale` first; then call `_rebuild_continuous_scene(page_idx)` in continuous mode.  
**File:** `controller/pdf_controller.py`

---

## Zoom combo always shows 100%

**Area:** `controller/pdf_controller.py`, `view/pdf_view.py`  
**Symptom:** Scale selector and status bar always read 100% regardless of actual zoom.  
**Cause:** `view.scale` was never updated, so `_update_page_counter()` read the stale default.  
**Fix:** Set `view.scale = scale` before calling `_update_page_counter()` and `_update_status_bar()`.  
**File:** `controller/pdf_controller.py`

---

## QToolBar overflow hides Undo/Redo buttons

**Area:** `view/pdf_view.py` — right toolbar  
**Symptom:** Redo button hidden behind `»` overflow; increasing right margin does not help.  
**Cause:** `setMaximumWidth(320)` on the right block too small; stretch widget squeezes the toolbar to minimum.  
**Fix:** `setMaximumWidth(420)`; remove stretch widget from `right_layout`; add `toolbar_right.setMinimumWidth(100)`.  
**File:** `view/pdf_view.py`

---

## PDFModel has no `.open()` method — it is `.open_pdf()`

**Area:** test scripts  
**Symptom:** `AttributeError: 'PDFModel' object has no attribute 'open'`  
**Cause:** Incorrect method name used in tests.  
**Fix:** Call `model.open_pdf(filepath)`.  
**File:** Any test importing `PDFModel`

---

## focusOutEvent recursive call in text editor finalization

**Area:** `view/pdf_view.py` — `_finalize_text_edit`  
**Symptom:** `_finalize_text_edit` re-enters itself; unexpected double-finalize behavior.  
**Cause:** `self.text_editor` was set to `None` after `removeItem()`, so `focusOutEvent` triggered during removal could re-enter.  
**Fix:** Set `self.text_editor = None` before calling `removeItem(proxy_to_remove)`.  
**File:** `view/pdf_view.py`

---

## Drag clamp produces invalid rect when target is fully off-page

**Area:** `model/pdf_model.py` / `view/pdf_view.py` — clamp helpers  
**Symptom:** `insert_htmlbox` fails after clamping because `y0 > y1` or `x0 > x1`.  
**Cause:** Clamp logic did not guard against producing an inverted or zero-area rectangle.  
**Fix:** After clamping, check `x0 < x1` and `y0 < y1`; skip or reject if the rect is degenerate.  
**File:** `view/pdf_view.py`, `model/pdf_model.py`

---

## Merge list reorder lost on next add/remove

**Area:** `view/pdf_view.py`, `model/merge_session.py`  
**Symptom:** After drag-reordering in the Merge PDF dialog, adding or removing a file resets the order.  
**Cause:** `_refresh_file_list()` rebuilt from `MergeSessionModel.entries` which was never updated after drag.  
**Fix:** On Qt `rowsMoved`, sync QListWidget order back to `MergeSessionModel.entries` using stable `entry_id` keys.  
**File:** `view/pdf_view.py`, `model/merge_session.py`

---

## Test normalization misses Unicode ligatures

**Area:** test scripts  
**Symptom:** Text preservation test fails: `insert_htmlbox` produces `ﬁ` but comparison target has `fi`.  
**Cause:** Test `_norm()` only stripped whitespace; did not expand ligature characters.  
**Fix:** Add `_LIGATURE_MAP` (`\ufb01`→`fi`, `\ufb02`→`fl`, etc.) and apply before comparison.  
**File:** `test_scripts/test_drag_move.py`

---

## Controller activation must be deferred to `activate()`

**Area:** `controller/pdf_controller.py`  
**Symptom:** Signal wiring or print subsystem setup runs before the view is ready, causing startup errors.  
**Cause:** Init code that belongs in `activate()` was placed in `__init__()`.  
**Fix:** Keep `__init__()` cheap (store refs only); put all view-signal wiring and startup sync in `PDFController.activate()`.  
**File:** `controller/pdf_controller.py`

---

## Text index must be rebuilt on-demand after structural ops

**Area:** `model/pdf_model.py`, `model/text_block.py`  
**Symptom:** Search or edit on a page after insert/delete returns stale or missing results.  
**Cause:** Structural ops mark cached pages `"stale"` rather than eagerly rebuilding, so callers that skip `ensure_page_index_built()` read stale data.  
**Fix:** Always call `model.ensure_page_index_built(page_num)` before any edit or search path.  
**File:** `model/pdf_model.py`, `model/text_block.py`

---

## Edit request dataclasses must stay Qt-free

**Area:** `model/edit_requests.py`, `controller/pdf_controller.py`, `view/text_editing.py`  
**Symptom:** Importing `EditTextCommand` or other model-layer helpers pulls in Qt/view dependencies and risks circular imports.  
**Cause:** If `EditTextRequest` or `MoveTextRequest` are defined under `view/`, the command layer must import upward across the architecture boundary to use the typed payloads.  
**Fix:** Keep shared request dataclasses in `model/edit_requests.py`, re-export them from `view/text_editing.py`, and avoid adding any Qt imports to the request module.  
**File:** `model/edit_requests.py`

---

## App-owned object identity must not rely on text-span discovery

**Area:** `model/pdf_model.py`, `view/pdf_view.py`, `controller/pdf_controller.py`  
**Symptom:** New textboxes look editable, but later object-level actions like move/rotate/delete need a stable identity that survives save/reopen and is independent of the current text index.  
**Cause:** Text spans and rebuilt text indices are not a stable object-identity layer. If object manipulation is wired to ephemeral span hits, later page rebuilds or text edits can orphan the object action path.  
**Fix:** Persist textbox identity with a hidden companion annotation marker and keep rectangle annotations stamped with app-owned metadata. Treat object hit detection as a dedicated model path, parallel to text hit detection, not as a thin wrapper over current text-run discovery.  
**File:** `model/pdf_model.py`, `view/pdf_view.py`

---

## Low-level Windows GUI injection can diverge from physical browse hits

**Area:** temporary verification harnesses under `tmp/`, browse/object selection in `view/pdf_view.py`  
**Symptom:** A low-level Windows harness can create the mixed sample reliably, but injected object-selection clicks may fail to activate the browse object-selection path even when direct model hit tests say the object is hittable.  
**Cause:** Qt/Windows coordinate conversion and event routing can diverge between control-message injection, `SendInput`, and real user mouse input, especially around `QGraphicsView` and viewport geometry.  
**Fix:** Do not treat a failing low-level injected selection gesture as proof that the model/controller object path is broken. Keep the focused automated object tests green, keep the manual harness evidence, and resolve the injection mismatch separately instead of silently declaring the broader manual verification complete.  
**File:** `tmp/manual_verify_f1_low_level.py`, `view/pdf_view.py`

---

## Browse object drag/selection on `QGraphicsView` must normalize through the viewport

**Area:** `view/pdf_view.py`  
**Symptom:** Live object-selection or drag gestures can miss the intended object or fail to start reliably, even though direct model hit tests at the same logical point succeed.  
**Cause:** The object/text interaction handlers were attached to `QGraphicsView.mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent`, but they converted the incoming event position as if it were already in viewport coordinates. In practice, the position can arrive in the graphics-view coordinate space and needs viewport normalization before `mapToScene(...)`.  
**Fix:** Normalize event coordinates through `graphics_view.viewport().mapFrom(graphics_view, raw_pos)` before converting to scene coordinates, and keep a focused regression around the object-drag threshold path.  
**File:** `view/pdf_view.py`

---

## Object rotate handles must be hittable outside the bbox

**Area:** `view/pdf_view.py`  
**Symptom:** A selected textbox shows a rotate handle, but clicking the handle in the live GUI does not rotate the object.  
**Cause:** Browse-mode object manipulation only entered the object path after a bbox hit from `get_object_info_at_point(...)`. The rotate handle is drawn above/outside the bbox, so real handle clicks never armed rotation.  
**Fix:** When an object is already selected, check the rotate handle hit before the bbox hit path and arm `_object_rotate_pending` directly from that selected object.  
**File:** `view/pdf_view.py`

---

## Textbox move/rotate/delete must purge leftover same-id markers

**Area:** `model/pdf_model.py`  
**Symptom:** After moving or rotating a textbox, deleting it can remove the visible content but leave behind a hidden same-id textbox marker annotation. That stale marker can keep the object logically present for later hit detection or verification scripts.  
**Cause:** The textbox lifecycle relied on redact/restore plus marker recreation, but did not proactively purge all app-owned annotations with the same textbox `object_id` before recreating or finalizing deletion.  
**Fix:** Add a helper that deletes every app-owned annotation matching the textbox `object_id` on the page, and call it during textbox move, rotate, and delete flows.  
**File:** `model/pdf_model.py`

---

## App-owned image object removal cannot rely on `page.delete_image(xref)`

**Area:** `model/pdf_model.py`  
**Symptom:** Deleting or moving an app-owned image object appears to succeed (marker removed / new marker created), but the old image still remains visible on the page or remains discoverable via image-rect inspection.  
**Cause:** In this PyMuPDF build, `fitz.Page.delete_image(xref)` does not remove the placed image from the page content stream for images inserted via `insert_image(...)`.  
**Fix:** For app-owned image objects, remove the previous placement by redacting the old image rect and applying redactions with `images=fitz.PDF_REDACT_IMAGE_REMOVE`, then reinsert the image at the new rect / rotation.  
**File:** `model/pdf_model.py`

---

## Native PDF image manipulation must rewrite image invocation operators, not redact page content

**Area:** `model/pdf_model.py`, `model/pdf_content_ops.py`  
**Symptom:** Moving or deleting an existing PDF image by redacting its bbox can also erase unrelated text or graphics that overlap the image placement, especially on scanned or mixed-content pages.  
**Cause:** Native PDF images are painted from page content stream operators (`q`, `cm`, `/<name> Do`, `Q`), so bbox redaction removes everything in that painted region instead of just the target image invocation.  
**Fix:** Discover native image invocations from parsed page content streams, derive bbox/rotation from the invocation `cm` when available, then move/resize/rotate by rewriting the target `cm` operands and delete by removing the target image invocation block. Only prune the page `/Resources /XObject` entry when that image name is no longer referenced after the rewrite.  
**File:** `model/pdf_model.py`, `model/pdf_content_ops.py`

---

## Windows `QLocalServer.listen(name)` is not a reliable single-instance guard by itself

**Area:** `utils/single_instance.py`  
**Symptom:** On Windows, a second process can still call `QLocalServer.listen(name)` successfully even when another process is already listening on the same local-server name, which breaks naive single-instance detection.  
**Cause:** The local-server endpoint alone is not a strong ownership primitive on this platform, so name reuse can succeed without proving that no primary instance exists.  
**Fix:** Pair the `QLocalServer` transport with a per-user `QLockFile` ownership guard, and only use `QLocalServer.removeServer(...)` when the lock looks stale and no live server answers a probe connect.  
**File:** `utils/single_instance.py`

---

## Surya's `DetectionPredictor` / `RecognitionPredictor` constructor signature changed

**Area:** `model/tools/ocr_tool.py`  
**Symptom:** After installing `surya-ocr`, OCR initialization raises `TypeError: __init__() got an unexpected keyword argument 'device'` on older releases or `TypeError: __init__() missing 1 required positional argument` on newer releases.  
**Cause:** Surya's public API reshaped its predictor constructors between minor versions. Older versions accept a positional `device` string; newer versions accept no arguments and resolve device internally via torch.  
**Fix:** `_SuryaAdapter._ensure_loaded` tries the new no-arg signature first and falls back via `except TypeError` to the older positional-device signature. A single `_create_surya_adapter(device)` factory is the only direct caller, so tests can monkeypatch it without depending on surya's real API.  
**File:** `model/tools/ocr_tool.py`

---

## Fitz `Pixmap` to PIL image must strip alpha before Surya

**Area:** `model/tools/ocr_tool.py`  
**Symptom:** Running Surya on a rendered PDF page raises `ValueError: too many values to unpack` or yields garbage bounding boxes.  
**Cause:** `fitz.Pixmap.samples` can include an alpha channel (RGBA) when the page has transparency. Surya's detection pipeline assumes RGB input and mis-strides the buffer when alpha is present.  
**Fix:** In `_pixmap_to_image`, always convert to mode `RGB` after constructing the PIL image (drop alpha via `image.convert("RGB")`) before handing off to Surya.  
**File:** `model/tools/ocr_tool.py`

---

## Explicit CUDA/MPS selection must be probed before OCR starts

**Area:** `model/tools/ocr_tool.py`, `view/dialogs/ocr.py`  
**Symptom:** On a CPU-only torch build, selecting `cuda` starts OCR but fails mid-run with `RuntimeError: Torch not compiled with CUDA enabled` (or an equivalent MPS error), and the user only learns the choice is invalid after waiting.  
**Cause:** Explicit device strings (`cuda` / `mps`) were passed through without checking `torch.cuda.is_available()` / `torch.backends.mps.is_available()`, and the dialog offered/persisted device choices that could never work on the current machine.  
**Fix:** Add `_is_device_available(...)` and harden `_resolve_torch_device(...)` to raise a clear error on explicit unavailable devices; disable unavailable device options in `OcrDialog` and clamp the stored preference back to `auto` when needed.  
**File:** `model/tools/ocr_tool.py`, `view/dialogs/ocr.py`, `test_scripts/test_ocr_tool_surya.py`, `test_scripts/test_ocr_dialog.py`

---

## QAction `setToolTip("")` falls back to the action's text label

**Area:** `view/pdf_view.py` (availability-gated tooltips)  
**Symptom:** After re-enabling the OCR action via `update_ocr_availability(True, "")`, `ocr_action.toolTip()` still returns the Chinese action label `"OCR（文字辨識）"` instead of an empty string, so tests that assert `toolTip() == ""` fail.  
**Cause:** Qt's `QAction::toolTip()` returns the stripped `text()` when the tooltip is empty/null. PySide6 treats Python `""` the same as an unset tooltip and re-exposes the action text.  
**Fix:** Do not assert that `toolTip()` literally equals `""` after clearing. Assert the unavailability reason is gone (e.g. `"surya" not in toolTip().lower()`), and document that "no tooltip" means the tooltip falls back to the visible action label.  
**File:** `view/pdf_view.py`, `test_scripts/test_ocr_view_entry.py`
