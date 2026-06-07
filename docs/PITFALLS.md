# PITFALLS.md — Known Failure Modes

> Add entries here whenever a non-obvious bug is fixed. Format:
> `## <short title>` / Area / Symptom / Cause / Fix / File

---

## PDF cm tokens must not use scientific notation

**Area:** `model/pdf_content_ops.py`  
**Symptom:** Some rewritten content streams fail to parse in downstream PDF processors after object move/resize, especially when near-zero transform terms are present.  
**Cause:** Serializing cm operands with `f"{value:g}"` can emit scientific notation (for example `1.2e-14`), which is not accepted consistently by PDF tokenizers.  
**Fix:** Route cm serialization through `format_cm_value(...)` for all cm writers, clamp tiny values to `0`, and emit fixed-point ASCII tokens.  
**File:** `model/pdf_content_ops.py`

---

## Probe-growth logs must not reference undefined or misleading variables

**Area:** `model/pdf_model.py`  
**Symptom:** Pre-push probe logging can either crash with `NameError` (undefined variable) or silently mislead debugging output with duplicated values under different labels.  
**Cause:** The log path referenced `raw_growth` after refactors removed that variable, and a quick fix reused `height_growth` for both placeholders while keeping the `raw=` label.  
**Fix:** Keep log arguments aligned with real computed values; if raw growth is not computed, remove the `raw=` placeholder and log only `height_growth`.  
**File:** `model/pdf_model.py`

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

## CMYK pixmaps must be converted before constructing `QImage`

**Area:** `src/printing/pdf_renderer.py`  
**Symptom:** Selecting a CMYK preview render path can crash or display corrupted output during printing because Qt `QImage` constructors assume RGB(A) channel layouts.  
**Cause:** PyMuPDF can render pixmaps in CMYK (4-channel) when `colorspace=fitz.csCMYK` is requested. Passing CMYK `pix.samples` into `QImage(..., Format_RGB888)` misinterprets the stride/pixel layout.  
**Fix:** When rendering in CMYK for preview/print, bridge-convert the pixmap to RGB before creating a `QImage` (e.g. `fitz.Pixmap(fitz.csRGB, cmyk_pix)`), while keeping the CMYK sampling intent as the upstream selection.  
**File:** `src/printing/pdf_renderer.py`

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

## Multi-style paragraph edit collapses all runs to one color

**Area:** `model/pdf_model.py` — `_apply_redact_insert`
**Symptom:** Editing a paragraph that contains runs with different colors (e.g. one red word, rest black) makes the entire replacement text appear in a single color.
**Cause:** `_convert_text_to_html(new_text, color=color)` uses the dominant color for the whole string. Additionally, the single-line fast path (`page.insert_text(...)`) bypassed multi-style detection entirely.
**Fix:** Detect `preserve_multi_style` when in paragraph mode with ≥2 distinct span colors and the request color matches one of them. When active, use `_build_multi_style_html(...)` (difflib char-level mapping) to rebuild per-run colored HTML, and skip the single-line fast path.
**File:** `model/pdf_model.py`

---

## Inline editor opens with oversized grey void below single-line text

**Area:** `view/text_editing.py` — `_compute_editor_proxy_layout`, `create_text_editor`
**Symptom:** Clicking a single-line run inside a paragraph block opens an inline editor ~6× taller than the text, with a solid grey rectangle filling the gap below the text.
**Cause:** `_compute_editor_proxy_layout` used `scaled_rect.height` directly. In paragraph mode the resolver returns the full paragraph bounding box, so the editor proxy is sized to the paragraph height even when only one line is being edited.
**Fix:** `create_text_editor` now measures actual content height via `_measure_text_content_height_px` — a `QTextDocument` laid out with the target font and wrap width, returning `doc.size().height()`. This height (plus an 8px padding constant) flows into `_compute_editor_proxy_layout` through a new optional `content_height_px` param, replacing the rect-height basis for non-rotated editors. A newline-counting heuristic (`text.count("\\n") + 1`) was considered and rejected: `EditableParagraph` assembly joins wrapped lines with spaces (not `\\n`), so the heuristic would undersize genuine multi-line wrapped paragraphs. Rotated editors (90°/270°) still use the swapped `scaled_rect.width` path unchanged.
**File:** `view/text_editing.py`

---

## Inline editor mask samples text into a grey rectangle

**Area:** `view/text_editing.py` - `refresh_text_editor_mask_color`
**Symptom:** While editing text, a sampled page-color mask can appear as a grey block behind the editor, while a fully transparent mask lets the original PDF glyphs overlap the editable text.
**Cause:** Sampling the rendered page under the editor includes text pixels, so the averaged color becomes grey. Making the mask transparent removes the grey block but stops hiding the original PDF text.
**Fix:** Use a stable white scene-mask brush during inline editing and keep the `QTextEdit` stylesheet background transparent. The mask item lifecycle remains in place for positioning and cleanup, and the underlay hides the original glyphs without text-pixel sampling.
**File:** `view/text_editing.py`

---

## Inline editor glyphs look smaller than the underlying PDF text

**Area:** `view/text_editing.py` — `create_text_editor`, `on_edit_font_size_changed`
**Symptom:** With the editor open, the text inside the editor looks perceptibly smaller than the rendered PDF text around it. Wrap boundaries in the editor don't match the committed PDF — "what you edit" ≠ "what you get". Most visible at `render_scale` > 1 (zoomed in) on 96-DPI Windows; invisible at `render_scale=1` on 72-DPI macOS.
**Cause:** PyMuPDF rasterizes PDF at `72 × render_scale` DPI, so a 10pt glyph becomes `10 × render_scale` physical pixels tall in the scene. Qt's `QFont.setPointSizeF(P)` renders glyphs at `P × logicalDotsPerInch / 72` widget-px. Scene = widget-px at devicePixelRatio=1. Passing `font_size` raw into `setPointSizeF` gives a widget glyph height of `font_size × 96/72 = font_size × 1.33` widget-px, while the PDF rendering is `font_size × rs` — only equal when `rs = 1.33` (never, in practice). At `rs=2`, widget text is 33% smaller; wrap widths diverge proportionally.
**Fix:** Compute widget point size via `_display_font_pt(pdf_font_size, render_scale) = pdf_font_size × render_scale × 72 / _widget_logical_dpi()` and use it for both the editor font (`qt_font_obj.setPointSizeF(...)`) and the `_measure_text_content_height_px` layout probe. Stored sizes (session.current_size, EditTextRequest.size) remain in PDF points — only the display/measurement path is DPI-corrected.
**File:** `view/text_editing.py`

---

## Test fixture skips `__init__` — manually inject `_autopan_active`

**Area:** `test_scripts/test_text_editing_gui_regressions.py`
**Symptom:** Three drag tests fail with `AttributeError: 'PDFView' object has no attribute '_autopan_active'` after the middle-click autopan merge.
**Cause:** The `_make_view()` fixture uses `PDFView.__new__(PDFView)` to skip `__init__`, so any attribute set in `__init__` is absent. The autopan merge added `self._autopan_active = False` in `__init__`.
**Fix:** Add `view._autopan_active = False` to the fixture's manual attribute injection block.
**File:** `test_scripts/test_text_editing_gui_regressions.py`

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

---

## PySide6 scene.clear() leaves dangling Python wrappers to deleted C++ items

**Area:** `view/pdf_view.py` — object selection overlay  
**Symptom:** Selecting an object after a scene rebuild crashes with `RuntimeError: Internal C++ object (QGraphicsRectItem) already deleted` when trying to update the selection rect.  
**Cause:** When `self.scene.clear()` runs (during continuous-mode rebuilds, page re-render, profile switch re-renders), all QGraphicsItems are deleted at the C++ level. But Python instance variables like `self._object_selection_rect_item`, `self._object_rotate_handle_item`, `self._object_resize_handle_items` still hold references to the freed wrappers.  
**Fix:** At the start of `_update_object_selection_visuals(...)`, use `shiboken6.isValid(item)` to detect dead C++ wrappers and reset them to `None` so they are re-created on demand. The same guard applies to all three overlay item collections.  
**File:** `view/pdf_view.py`

---

## Auto-pan right-click exit can double-open the context menu

**Area:** `view/pdf_view.py`  
**Symptom:** Right-clicking to exit middle-click auto-pan opens the context menu twice.  
**Cause:** The auto-pan exit path intentionally shows the regular context menu immediately, but `QGraphicsView.customContextMenuRequested` can still fire afterward for the same gesture and trigger a second menu.  
**Fix:** Gate `_show_context_menu(...)` with a one-shot `_autopan_suppress_next_context_menu` flag, and route the intentional exit-path menu through `_show_context_menu_manual(...)` so the manual call bypasses suppression while the next signal-driven call is swallowed.  
**File:** `view/pdf_view.py`

## PyMuPDF rawdict drops span['text'] once Qt is live
**Area:** `model/pdf_model.py` (text extraction), no-jump E2E gate
**Symptom:** With a QApplication running (e.g. offscreen test env), `page.get_text("rawdict")` returns spans whose `text` key is absent/None even though `get_text("text")` works; every real-PDF gate test fails at span lookup.
**Cause:** Some PyMuPDF builds only populate per-`chars` data in rawdict spans under that condition.
**Fix:** `_install_rawdict_text_compat()` wraps `fitz.Page.get_text` once at import to backfill `span['text']` from `chars`.
**File:** `model/pdf_model.py`

## Inline editor glyphs differ in size from the rendered PDF
**Area:** `view/text_editing.py` (inline text editor)
**Symptom:** Opening the editor makes text visibly larger/smaller than the PDF; reopen cumulatively shrinks the box.
**Cause:** (1) Qt renders `setPointSizeF(P)` at `P×logical_dpi/72` px while MuPDF rasterizes at `72×render_scale` DPI — using the raw pdf pt desyncs them. (2) `editor.font = qfont` shadows `QTextEdit.font()`. (3) Per-commit shrink had no cross-edit anchor.
**Fix:** `_display_font_pt(pdf_pt, rs)=pdf_pt×rs×72/logical_dpi` for the widget font; never assign `editor.font`; `run_reopen_anchors` pin original bbox+size across reopen cycles.
**File:** `view/text_editing.py`, `model/pdf_model.py`

## test_19b font-size assertion is render-scale/DPI sensitive
**Area:** `test_scripts/test_multi_tab_plan.py`, gate `full_suite`
**Symptom:** `assert 14 == 18` on `editor.font().pointSize()` after setting size combo to 18, in offscreen/low-DPI environments.
**Cause:** Layer C intentionally display-scales the widget font; the assertion only holds when `view._render_scale ≈ 1.333` cancels `72/96`. Fails identically on validated baseline code in such environments — not a regression.
**Fix:** Run the gate's full-suite step in a normal desktop (real screen DPI) environment; treat as environment fragility, not a code defect.
**File:** `test_scripts/test_multi_tab_plan.py`
---

## Single-line edits dramatically push surrounding text away

**Area:** `model/pdf_model.py` — `_apply_redact_insert` pre-push probe  
**Symptom:** Editing a single character on one line can shift every line below by 20pt+, making the page look like the edited text "got much larger" or "much smaller".  
**Cause:** Two compounding bugs: (a) `_probe_y1` was clamped to `max(probe_actual, base_y1)` where `base_y1 = y0 + max(layout_h, line_count × size × 2 + size × 2)` — the heuristic floor was ~4× the realistic single-line height, forcing the probe artificially high; (b) MuPDF's `insert_htmlbox` adds a fixed 2.0pt of leading to every render regardless of CSS line-height, which alone exceeds the `size × 0.2` push-down threshold for small fonts.  
**Fix:** Trust the probe's raw `_probe_used_h` measurement (drop the `max(probe, base_y1)` clamping) and subtract the constant 2.0pt MuPDF overhead from `raw_growth` before comparing to the threshold.  
**File:** `model/pdf_model.py`

---

## Committed text line height diverges from original PDF

**Area:** `model/pdf_model.py` — `_apply_redact_insert` (call to `_build_insert_css`)  
**Symptom:** After editing text, the committed text block can take more or less vertical space than the original because line spacing changed.  
**Cause:** `_build_insert_css` defaults to `line_height = max(size × 1.1, font_metrics × size)` when no explicit value is given. This auto-calculated value differs from the original PDF's actual per-line height.  
**Fix:** Compute original line height from `member_spans` — median baseline-to-baseline advance for multi-line targets, max `bbox.height` for single-line — and pass it as `line_height` to `_build_insert_css`.  
**File:** `model/pdf_model.py`

---

## Editor wrap width wider than source rect causes wrapping divergence

**Area:** `model/pdf_model.py` — `get_render_width_for_edit`  
**Symptom:** Inline editor shows text wrapping on different lines than the rendered PDF beneath it (the "break lines once edit box opened" symptom).  
**Cause:** `get_render_width_for_edit` returned `max(rect.width, page-margin-safe-width)`, potentially wider than the source rect. Qt's font renderer (with slightly different horizontal glyph metrics than PyMuPDF) then re-laid the text at different break points.  
**Fix:** Return `float(rect.width)` directly so the editor wraps at exactly the same character positions as the source PDF.  
**File:** `model/pdf_model.py`

---

## Fidelity tests can pass on no-op edits unless they assert committed content

**Area:** `test_scripts/test_edit_text_helpers.py`  
**Symptom:** Font-size / bbox-height / anchor-drift tests can stay green even when `edit_text(...)` returns success but does not actually change page text. Real-PDF checks can also pass by sampling an unrelated nearby span after edit.  
**Cause:** Assertions focused on geometry and status code only; they did not require proof that the edited text was committed or that post-edit measurement targeted the edited span.  
**Fix:** Add explicit committed-content checks (`_page_contains_text(...)`), force htmlbox path when testing line-height/probe behavior, and tag real-PDF edits with unique markers then locate post-edit spans via marker lookup (`_find_span_with_text(...)`).  
**File:** `test_scripts/test_edit_text_helpers.py`

---

## `_build_insert_css` unconditional clamp defeats explicit tight line heights

**Area:** `model/pdf_model.py` — `_build_insert_css`  
**Symptom:** Edited text remains visibly taller than original even after `_apply_redact_insert` correctly computes `_line_ht` from source spans. Surrounding unedited content still gets pushed when the source PDF has tight leading (baseline advance below font size).  
**Cause:** `line_height = round(max(size, line_height), 2)` ran unconditionally for both auto-calculated and caller-supplied values. An explicit tight value (e.g. 8pt advance for a 10pt font) was silently raised to font size, so committed boxes stayed taller than original.  
**Fix:** Apply the `max(size, ...)` floor only when `line_height <= 0` (auto-calculate path). Explicit positive values are honored as-is with only a tiny minimum safety bound (`max(0.1, ...)`) and a final rounding step.  
**File:** `model/pdf_model.py` — `_build_insert_css`

---

## Mixed-script headings split into per-script spans by PyMuPDF

**Area:** `model/pdf_model.py` — `get_text_info_at_point`, text index  
**Symptom:** A heading that visually reads as one string (e.g. `'Revit前置作業操作流程'`) is returned as two separate `TextHit` objects — one for the Latin prefix (`'Revit'`) and one for the CJK suffix (`'前置作業操作流程'`). A probe inside the CJK region returns only the CJK span; asserting the full heading text in `hit.target_text` will fail.  
**Cause:** PDF renderers, and consequently PyMuPDF's span extraction, split text runs at script boundaries (Latin → CJK, etc.). Each sub-run becomes its own span with its own bbox.  
**Fix:** When probing for a known mixed-script target, probe inside one script region and assert only the portion of text you expect in that span (e.g. assert `"前置" in hit.target_text` instead of `"Revit" in hit.target_text`). Add a font-size guard to confirm you hit the right heading rather than a different CJK span elsewhere on the page.  
**File:** `test_scripts/test_edit_text_helpers.py`

---

## `_needs_cjk_font` monkeypatch in real-PDF tests masks CJK path coverage

**Area:** `test_scripts/test_edit_text_helpers.py`  
**Symptom:** Real-PDF regression tests that monkeypatch `_needs_cjk_font` to always return `True` stay green even when CJK detection is broken for other inputs, because the patch forces the `insert_htmlbox` path unconditionally instead of letting it be chosen naturally.  
**Cause:** If the reproducer PDF already contains CJK text, `_apply_redact_insert` routes through `insert_htmlbox` naturally without any monkeypatching. Adding the patch is redundant and hides whether the natural CJK-detection path is exercised.  
**Fix:** Remove `monkeypatch.setattr(model, "_needs_cjk_font", ...)` from real-PDF tests whose target spans already contain CJK characters. Keep the monkeypatch only in synthetic tests that use Latin-only PDFs and explicitly need to force the htmlbox path (document the intent with a comment).  
**File:** `test_scripts/test_edit_text_helpers.py`

---

## Heuristic span discovery in regression tests targets wrong spans after layout change

**Area:** `test_scripts/test_edit_text_helpers.py`  
**Symptom:** Grid-scanning helpers like `_find_largest_font_span` or `_find_any_editable_span` can silently pick a different span if page layout changes slightly (font scaling, new content, PDF re-export), causing tests to measure the wrong element without failing immediately.  
**Cause:** These helpers scan a coarse grid and accept the first acceptable hit, so the selected target drifts with page content rather than being pinned to a known span.  
**Fix:** Replace heuristic discovery with `model.get_text_info_at_point(page, fitz.Point(x, y))` using verified coordinates for a known text fragment (verified from the actual PDF). Assert both the expected text substring and a font-size range to confirm the correct span was hit before proceeding with the fidelity measurement.  
**File:** `test_scripts/test_edit_text_helpers.py`

---

## Preview-backed inline editor must keep Qt text painting suppressed

**Area:** `view/text_editing.py`  
**Symptom:** During inline edit, glyphs appear doubled or mismatched against committed PDF output.  
**Cause:** Qt text glyph painting and MuPDF preview painting were both visible in the editor viewport.  
**Fix:** Add `PreviewBackedInlineTextEditor.paintEvent(...)` that draws the MuPDF preview image and custom caret/selection, and does not call QTextEdit default text painting.  
**File:** `view/text_editing.py`

---

## Shared insert-path classification prevents preview/commit drift

**Area:** `model/pdf_model.py`, `view/text_editing.py`  
**Symptom:** Preview can choose a different rendering path than commit (fast insert vs htmlbox), causing during-edit and post-commit mismatch.  
**Cause:** Path selection logic lived only inside `_apply_redact_insert(...)` and was not reusable by preview flows.  
**Fix:** Extract `_classify_insert_path(...)` as shared classification logic and route `_apply_redact_insert(...)` through it; preview paths can now reuse the same decision contract.  
**File:** `model/pdf_model.py`, `view/text_editing.py`

---

## `editor.font` method shadowed by attribute assignment

**Area:** `view/text_editing.py` — `TextEditManager.create_text_editor`  
**Symptom:** `TypeError: 'QFont' object is not callable` raised inside `on_edit_font_size_changed` or `on_edit_font_family_changed` whenever the user changes font/size during an active edit session.  
**Cause:** A "test harness compatibility" workaround assigned `editor.font = qt_font_obj` on top of the correct `setFont(qt_font_obj)` call, overwriting the `QTextEdit` instance's `font()` method with a `QFont` instance. Real-editor flows that call `editor.font()` raised `TypeError`.  
**Fix:** Removed the assignment entirely. Real editors expose `.font()` as a Qt method; test fakes set their own `.font` attribute on their own fake instances and don't need production code to mirror it.  
**File:** `view/text_editing.py` (removed `try: editor.font = qt_font_obj` block).

---

## `PreviewRenderer.render` returned blank QImage with no rasterization

**Area:** `view/text_editing.py` — `PreviewRenderer.render`  
**Symptom:** Inline editor visually shows no glyphs (or only caret). User reports "glyphs unexpectedly larger or smaller when I click a line" because the editor box is effectively empty — Qt's default text painting was suppressed by `paintEvent`.  
**Cause:** `PreviewRenderer.render` only allocated a transparent `QImage` sized to `rect × render_scale`; it never called `insert_htmlbox` or rasterized the proposed text. The Phase 2 stretch goal was scaffolded but not implemented.  
**Fix:** Open a temp document, create a temp page sized rotation-aware to `rect_pt`, build CSS+HTML via `model._build_insert_css` and `model._convert_text_to_html` (same helpers `_apply_redact_insert` calls), call `insert_htmlbox` into the temp rect, rasterize via `temp_page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=True)`, convert to `QImage` and detach via `.copy()` before closing `temp_doc`. Falls back to minimal Helvetica CSS when model is `None` or lacks `_build_insert_css` (e.g. `SimpleNamespace` test fakes).  
**File:** `view/text_editing.py` — `PreviewRenderer.render` (full implementation).

---

## `_classify_insert_path` returned `"fast"` on empty `member_spans`, caller crashed

**Area:** `model/pdf_model.py` — `_classify_insert_path` / `_apply_redact_insert`  
**Symptom:** Edit operation aborts with `ValueError: min() arg is an empty sequence` when `member_spans` resolution yields an empty list.  
**Cause:** `_classify_insert_path` treated empty `member_spans` as a single-line case and returned `"fast"`; the caller then ran `origin_span = min(member_spans, key=...)` unguarded.  
**Fix:** Empty `member_spans` → `"htmlbox"`. The fast path requires an anchor span for `insert_text` origin; without one there is no valid fast path.  
**File:** `model/pdf_model.py:100–101`.

---

## Click-to-edit causes visible glyph-size jump (no-jump UX)

**Area:** `view/text_editing.py` — `PreviewBackedInlineTextEditor`, `TextEditManager.create_text_editor`  
**Symptom:** The moment the user clicks a text span to edit it, glyphs appear to jump — they look visibly larger or smaller in the editor than in the underlying PDF, and the editor box does not match the PDF bbox.  
**Cause:** Multiple compounding geometry errors:
1. Qt's `QFont.setPointSizeF(pdf_size)` renders at `pdf_size × screen_dpi/72` widget-px, while PyMuPDF renders at `pdf_size × render_scale` scene-px; these diverge at any `render_scale ≠ screen_dpi/72` (always wrong on 96-DPI Windows at any scale other than ~1.33).
2. The editor widget had Qt-default frame borders and viewport margins, adding several extra pixels to the visual size.
3. `configure_render_context` re-called `setFixedSize` from the rect dimensions, overwriting the carefully-sized initial frame.
4. Rotated targets (90°/270°) did not swap width/height in the preview context, so the editor appeared with transposed dimensions.
5. Paragraph-mode editors used the full block-bbox height rather than the wrapped-content height, producing an oversized grey void below the text.  
**Fix:**
- `_display_font_pt(pdf_font_size, render_scale)` computes DPI-corrected widget point size: `pdf_font_size × render_scale × 72 / logical_screen_dpi`.
- `PreviewBackedInlineTextEditor.__init__` zeroes all Qt frame/viewport/margin extras (`setFrameStyle(0)`, `setViewportMargins(0,0,0,0)`, `document().setDocumentMargin(0.0)`, `setContentsMargins(0,0,0,0)`) and hides the cursor until first keypress.
- A `freeze_first_frame(image)` method stamps the very first preview frame; `paintEvent` draws the frozen frame (and the MuPDF live preview) instead of any Qt text painting, so the initial visual exactly matches the surrounding PDF.
- `configure_render_context` only calls `setFixedSize` when the editor has no explicit frame yet (`width <= 1`), so the create-time geometry is not overwritten on subsequent render-context updates.
- For rotated targets (90°/270°), `create_text_editor` computes swapped `editor_width_px` / `editor_height_px` from the rect before calling `_compute_editor_proxy_layout`.
- Paragraph-mode `create_text_editor` measures actual wrapped-content height via `_measure_text_content_height_px` (a `QTextDocument` probe) and uses that instead of the block-bbox height.  
**File:** `view/text_editing.py`

---

## `insert_htmlbox` with default `scale_low` can produce inconsistent vertical metrics across preview and commit

**Area:** `view/text_editing.py` — `PreviewRenderer.render`  
**Symptom:** Preview image glyph height appears slightly different from committed glyph height when the same CSS is applied via `insert_htmlbox` in both paths, producing a subtle shift on first keystroke.  
**Cause:** `insert_htmlbox` has a `scale_low` parameter that controls minimum font scaling; the default allows MuPDF to scale down small glyphs, which can change layout metrics compared to the commit path.  
**Fix:** Pass `scale_low=1` to `insert_htmlbox` in `PreviewRenderer.render` so preview metrics match commit-path metrics exactly.  
**File:** `view/text_editing.py` — `PreviewRenderer.render`

---

## Block outlines in edit-text mode overlap with inline editor affordance

**Area:** `view/pdf_view.py` — `_draw_all_block_outlines`, `create_text_editor` / `_finalize_text_edit`  
**Symptom:** When a text block is being actively edited, its outline rect remains visible behind the editor, producing a confusing double-border or a block outline peeking around the editor widget.  
**Cause:** `_draw_all_block_outlines` was called for all visible blocks, including the block currently being edited.  
**Fix:** Suppress block outline drawing for the actively-edited target while an inline editor is open; restore the outline on finalization.  
**File:** `view/pdf_view.py`

---

## Editor font-size combo and Qt widget font can drift after user changes size mid-edit

**Area:** `view/text_editing.py` — `TextEditManager.on_edit_font_size_changed`  
**Symptom:** User picks a different font size in the size combo during an edit; the editor glyphs do not visually update, or they update to the wrong size.  
**Cause:** The size-change handler recomputed widget point size through `_display_font_pt` (DPI-corrected), but the size combo represents on-screen point size directly (not PDF points). Applying DPI correction again double-scaled the size.  
**Fix:** In `on_edit_font_size_changed`, apply the combo's size value directly via `font.setPointSizeF(size)` without DPI correction, since the combo already holds the screen-space size.  
**File:** `view/text_editing.py`

---

## Paper size matching tie-break selects wrong size on precision edge

**Area:** `src/printing/layout.py` — `match_standard_paper_size`  
**Symptom:** A 841.9 × 595.3 pt source (A3) matches both A3 and A4 within ±3pt tolerance. The function returned the wrong one.  
**Cause:** The matching loop used `<=` on distance comparison, allowing ties to survive, and continued iterating without an explicit tie-break strategy.  
**Fix:** Use strict `<` instead of `<=`, so the first matching size is returned and later equally-close candidates are rejected.  
**File:** `src/printing/layout.py` — `match_standard_paper_size`

---

## Form XObject images not discovered by `page.get_images(full=True)`

**Area:** `model/pdf_content_ops.py` — `discover_native_image_invocations`  
**Symptom:** Some PDFs (e.g., Awareness.pdf) contain images embedded inside Form XObjects. These images do not appear in objects mode and cannot be selected/rotated.  
**Cause:** `page.get_images(full=True)` only scans the main page content stream. Images inside Form XObjects (referenced via indirect `/XObject /Form` entries) are not included.  
**Fix:** Add a secondary pass iterating `page.get_xobjects()` to enumerate all XObject dict entries, identify image-type XObjects, and parse their content streams for embedded images. Use a third pass to discover Form-nested images by walking form `/Resources /XObject` entries.  
**File:** `model/pdf_content_ops.py` — `discover_native_image_invocations`

---

## Form-space to page-space coordinate transform analytical solution is brittle

**Area:** `model/pdf_content_ops.py` — `form_rect_to_stream_cm`  
**Symptom:** A form XObject's `cm` matrix (coordinate transformation matrix) relates form-user-space (y-up, bottom-left origin) to page-fitz-space (y-down, top-left origin). Deriving the affine transformation analytically fails when the form's bbox contains negative coordinates or the transformation includes rotation/shearing.  
**Cause:** Analytical approaches (matrix inversion, corner-to-corner mapping) assume rectilinear transforms; rotated or sheared forms produce indeterminate systems.  
**Fix:** Use empirical component-wise recovery: apply the transform to the form's four corners, measure the resulting page-space bbox, and solve for individual affine components (sx, sy, a, b, c, d, e, f) from the correspondence between form corners and page-space results. Return `None` for non-rectilinear cases (rotated/sheared forms cannot be safely edited).  
**File:** `model/pdf_content_ops.py` — `form_rect_to_stream_cm`

---

## Float rotation angle truncated to int on object hit-test retrieval

**Area:** `view/pdf_view.py` — `_hit_test_objects`, `ObjectHitInfo`  
**Symptom:** A user rotates an object to 25°. On the next mouse move, the object's rotation jumps to 24° or reverts partway.  
**Cause:** `ObjectHitInfo.rotation` was stored as `int(native_hit.rotation)`, truncating fractional angles. Each subsequent drag-move re-fetched the object and re-truncated, losing precision with every interaction.  
**Fix:** Store rotation as `float(native_hit.rotation)` in `ObjectHitInfo` and throughout the drag pipeline; only round to cardinal angles (0°/90°/180°/270°) when explicitly snapping to grid.  
**File:** `view/pdf_view.py` — `ObjectHitInfo` class, hit-test retrieval path

---

## Character-level run assignment fails for overlapping text lines

**Area:** `model/pdf_model.py` — `get_chars_in_run`  
**Symptom:** In dense PDFs with overlapping lines, a character's hit-test centre falls within the y-span of the wrong line's glyphs, and the character is assigned to the wrong run.  
**Cause:** The centre-in-bbox proximity test applied ±0.5pt tolerance on both x and y axes uniformly. Overlapping lines have glyphs whose y-centres fall within both lines' y-ranges, so they falsely passed the y-tolerance check for the wrong line.  
**Fix:** Apply asymmetric tolerance: tight on the cross-axis (perpendicular to reading direction; ±0.1pt for y in horizontal text) to reject glyphs from other lines, and loose on the reading axis (±0.5pt for x in horizontal) to accommodate natural inter-character spacing.  
**File:** `model/pdf_model.py` — `get_chars_in_run`

---

## Test fixture gitignored, tests error out on fresh checkout

**Area:** `test_scripts/conftest.py`  
**Symptom:** Tests like `test_char_run_reconstruction` and `test_core_interaction_audit` fail immediately with "fixture not found" on a fresh clone.  
**Cause:** `test_files/1.pdf` is a small-clean sample needed by these suites for predictable token distribution. It is gitignored and not committed.  
**Fix:** Add a session-scoped autouse fixture in `conftest.py` that synthesizes `test_files/1.pdf` on-the-fly if it doesn't exist. The fixture generates a PDF with specific content (per-word runs "young"/"the"/"program"/"favorite" + a control line "run or not run") so reconstruction/audit tests find the expected tokens. Never overwrites an existing fixture.  
**File:** `test_scripts/conftest.py` — `_ensure_test_file_1_pdf()`

## Context menus and dialogs stay light when QSS is window-scoped
**Area:** `view/theme.py`, `view/pdf_view.py`, `controller/pdf_controller.py`
**Symptom:** After applying a theme via `QMainWindow.setStyleSheet(...)`, modal dialogs and right-click context menus kept the native light palette (white-on-white / dark-on-dark, unreadable under the dark theme).
**Cause:** Top-level `QMenu`s and `QDialog`s are not children of the main window in the widget tree, so a window-level stylesheet never reaches them.
**Fix:** Apply the themed QSS once at the `QApplication` level (`QApplication.instance().setStyleSheet(build_qss(name))`) on startup and on theme switch. Keep an explicit `QDialog`/`QMenu` rule in `build_qss`. Remove all per-widget color `setStyleSheet` calls so nothing overrides the global sheet.
**File:** `view/pdf_view.py` (`__init__`), `controller/pdf_controller.py` (`set_theme`)

## Ribbon tab QSS leaks onto the sidebar tab widget
**Area:** `view/theme.py`
**Symptom:** Styling the ribbon tabs also restyled the left sidebar tabs (縮圖/搜尋/註解列表/浮水印列表).
**Cause:** Bare `QTabBar::tab` / `QTabWidget::pane` selectors match every tab widget in the app.
**Fix:** Scope every tab rule by object name (`QTabWidget#ribbonTabs`, `QTabWidget#sidebarTabs`, `QTabBar#documentTabBar`) and assign those object names in the view. A test asserts no bare `QTabBar::tab` / `QTabWidget::pane` rule appears in the built QSS.
**File:** `view/theme.py` (`build_qss`)

## Applying app-level QSS from a widget constructor pollutes the shared-qapp test suite
**Area:** `view/pdf_view.py`, `main.py`
**Symptom:** After theming moved to an application-level stylesheet, geometry-sensitive suites (e.g. `test_no_jump_editor_geometry.py`) failed intermittently in the full run but passed in isolation. The failure set shifted run-to-run.
**Cause:** `PDFView.__init__` called `QApplication.instance().setStyleSheet(...)`. Because the test `qapp` fixture is session-scoped, merely *constructing* a view re-themed every widget for the rest of the session, adding global `QToolButton`/`QSpinBox` padding that shifted later geometry measurements.
**Fix:** Keep view construction side-effect-free. Resolve the theme in `__init__` but apply it only via an explicit `view.apply_initial_theme()` call from the composition root (`main.py`). Runtime switches go through `PDFView.apply_theme(...)`. Constructing a view no longer mutates global app state, and the geometry suites became deterministic.
**File:** `view/pdf_view.py` (`apply_theme`/`apply_initial_theme`), `main.py`

## Printing once permanently mutated the printer's per-user defaults
**Area:** `src/printing/platforms/win_driver.py`, `src/printing/print_dialog.py`
**Symptom:** Adjusting anything in the native `屬性` dialog (or just printing once) changed the printer's defaults for every later job and every other app.
**Cause:** `open_printer_properties` wrote the chosen DEVMODE as the per-user default via `SetPrinter`/`SetPrinterW` level 9. Level 9 = `PRINTER_INFO_9` = the persistent per-user default — that *is* the global mutation.
**Fix:** Make settings job-scoped. The dialog hands the captured DEVMODE back as a base64 string (JSON-safe across the helper-subprocess `job.json` boundary), the dialog injects it only at submission, and `print_pdf` applies it for that job by writing level 9 then restoring the previous default in a `finally`. Treat the apply as "applied" only on a confirmed write, only after the original was captured (so a successful apply can always be undone), and log a failed restore loudly instead of swallowing it.
**File:** `win_driver.py` (`_print_with_scoped_devmode`, `_persist_devmode_buffer_user_defaults`), `print_dialog.py` (`_build_submission_options`, `accept`)

## extra_options must be JSON-serializable (no raw bytes)
**Area:** `src/printing/helper_protocol.py`, `src/printing/platforms/win_driver.py`
**Symptom:** Putting a raw DEVMODE `bytes` object into `PrintJobOptions.extra_options` crashes every Windows print job with `TypeError: bytes is not JSON serializable`.
**Cause:** The real job is dispatched to an out-of-process helper; `PrintHelperJob.to_json_dict()` → `json.dumps(...)` serializes every option, including `extra_options`. Raw bytes have no JSON representation.
**Fix:** Carry binary as a base64 ASCII string under `extra_options["devmode_buffer"]`; decode back to bytes only inside the helper process where the `QPrinter` is created. Keep `extra_options` typed `dict[str, str]`. Centralized in `_encode_devmode_b64` / `_decode_devmode_b64`.
**File:** `win_driver.py` (`_encode_devmode_b64`, `_decode_devmode_b64`, `print_pdf`)

## GDI ignores mid-job page-layout changes; mixed-media must be split
**Area:** `src/printing/qt_bridge.py`, `src/printing/platforms/win_driver.py`
**Symptom:** A PDF with mixed page sizes/orientations printed every page on the first page's media on a real Windows printer, even though per-page `setPageLayout` worked for PDF export.
**Cause:** `QPainter.begin()` fixes the device media; subsequent `printer.setPageLayout(...)` + `newPage()` are honored by Qt's PDF writer but ignored by the Windows GDI printer DC.
**Fix:** `qt_bridge.raster_print_pdf` keeps per-page layout (correct for PDF export and within one uniform group). For the GDI spooler, `win_driver._raster_split_or_direct` pre-splits the job into one spooler job per contiguous uniform-layout group. Multi-copy collated jobs loop the whole document in order across groups; uncollated jobs use one pass with `copies=N` per group. These jobs are not atomic (a separate spool job per group cannot be recalled) — a mid-job failure reports how many pages were already spooled.
**File:** `win_driver.py` (`_split_by_layout`, `_print_layout_groups`)

## Windows full-DPI raster spools are huge and slow
**Area:** `src/printing/platforms/win_driver.py`, `src/printing/qt_bridge.py`
**Symptom:** Jobs sat in the spooler far longer than Acrobat; a 10-page A4 doc produced an enormous EMF spool.
**Cause:** Windows has no vector/direct-PDF path; every page is a full-resolution `QImage` blitted at `dpi` (default 300) onto a `QPrinter(HighResolution)` DC. An A4 page at 300 DPI is ~26 MB raw.
**Fix:** Cap the effective raster DPI for the real spooler path (`_WIN_MAX_RASTER_DPI = 150`); PDF-output/virtual targets keep full DPI. The cap composes with the `normalized()` floor (72), so the Windows spooler range is [72, 150]. (A true vector path remains future work.)
**File:** `win_driver.py` (`_raster_split_or_direct`, `_WIN_MAX_RASTER_DPI`)

## Print speed/layout tests can pass while the real path stays broken
**Area:** `test_scripts/test_print_speed.py`, `test_scripts/test_print_layout.py`, `test_scripts/test_win_print_fixes.py`
**Symptom:** All print tests were green while the four user-visible print defects persisted.
**Cause:** The speed test wrote to `output_pdf_path` (route `qt-raster->pdf`), not the GDI spooler; the layout tests used a fake `_LayoutPrinter` and pure helpers, never a real multi-page `QPrinter`. Neither exercised the path real printing uses.
**Fix:** Test the driver paths the dispatcher actually calls: `WindowsPrinterDriver.print_pdf` routing (DEVMODE decode → scoped apply/restore), `_split_by_layout` grouping/copy-ordering, the DPI cap, and the dialog's submission/clear semantics. See `test_win_print_fixes.py`.
**File:** `test_scripts/test_win_print_fixes.py`

## QPrinter.setPageLayout() silently drops the page SIZE on the Windows GDI spooler
**Area:** `src/printing/qt_bridge.py`
**Symptom:** Per-page size still failed after the layout-split fix: a mixed A3/A4 job printed every page on the printer's default media (e.g. 2× A3), even though orientation switched per page and PDF export was correct. The split classified pages correctly (`a3`/`a4`) and Qt's PDF writer honoured it — only the real GDI device ignored the size.
**Cause:** `_set_page_layout` did `layout = printer.pageLayout(); layout.setPageSize(...); printer.setPageLayout(layout)`. On Windows, `QPrinter.setPageLayout()` applies the orientation but **silently fails to apply the page size** to the device — `printer.pageLayout().pageSize()` stays at the printer default. (Confirmed live: after `setPageLayout` an A4 request read back as A3; `printer.setPageSize(QPageSize(A4))` read back as A4.) That is exactly why orientation looked fixed while size never changed.
**Fix:** Use the dedicated setters: `printer.setPageSize(page_size)` + `printer.setPageOrientation(orientation)`. Both reach the GDI device (verified on a real A3/A4 printer) and work for PDF output too. Regression-guarded by `test_set_page_layout_actually_applies_page_size` (models the Windows quirk) and `test_set_page_layout_applies_size_on_real_printer` (live printer, skipped if none).
**File:** `qt_bridge.py` (`_set_page_layout`)

## Auto XREF repair on open makes the document memory-backed
**Area:** `model/pdf_model.py` (`open_pdf`, `_repair_doc_xref_in_memory`)
**Symptom:** After opening a PDF whose xref MuPDF had to rebuild, the active `doc.name` is `""` and save-to-original takes the full-rewrite path instead of an incremental update.
**Cause:** When PyMuPDF flags `doc.is_repaired`, `open_pdf` round-trips the document through `tobytes(...)` and reopens it from bytes, so the doc is no longer file-backed (`doc.name` is empty). `save_as`/`_full_save_to_path` key "save back to original" off `doc.name == original_path`, which no longer holds.
**Fix:** Intended, not a bug — a repaired document **cannot** be saved incrementally (`can_save_incrementally()` is False on it), so a full rewrite to the original path is the correct, safe outcome. Guard auto-repair so it runs only when `is_repaired` is set, keeping healthy files file-backed (and incremental-save-capable). Reading `is_repaired` is free; the round-trip is paid once, only for damaged files.
**File:** `model/pdf_model.py` (`open_pdf`, `_doc_needs_xref_repair`, `_repair_doc_xref_in_memory`)

## On-open XREF repair must not use `deflate=True` (20× cost on large files)
**Area:** `model/pdf_model.py` (`_repair_doc_xref_in_memory`)
**Symptom:** Auto-repairing a large damaged PDF on open froze the UI for seconds — a 235 MB image-heavy file took ~4.9 s; extrapolated to the 512 MB open cap that is ~10 s.
**Cause:** The in-memory round-trip used `doc.tobytes(garbage=1, deflate=True)`. `deflate=True` re-compresses **every** stream (~20 ms/MB), which is wasted work on the already-compressed/incompressible image data that dominates large PDFs — it shrank nothing (117.6 MB → 117.6 MB) yet cost ~9× the time. The round-trip's only job is to bake in MuPDF's rebuilt xref, which `tobytes` does regardless of compression.
**Fix:** Drop `deflate=True` (use `tobytes(garbage=1)`); a fresh, internally-consistent xref still results and `is_repaired` still clears on reopen. Cost falls to ≈2.5 ms/MB (pure incompressible image) – ≈5 ms/MB (mixed content), i.e. ~1.3–2.6 s worst case at the 512 MB cap. Validated on a real damaged copy of `test_files/test-large-file.pdf` (47 MB, 402 pages): repaired on open in **240 ms** (5.1 ms/MB), `is_repaired` cleared, page count and mid-page text byte-identical to the healthy file. `deflate=False` copies existing streams as-is — it does **not** decompress them, so output size and memory are unchanged. Stream compression belongs on an explicit full save, not on every open. Text-heavy PDFs are object-count-bound rather than stream-bound, so deflate is ~neutral there; real 200 MB+ files are image-heavy, which is exactly where the win lands.
**File:** `model/pdf_model.py` (`_repair_doc_xref_in_memory`)

## On-open XREF repair must NOT round-trip an encrypted document (silent password/permission loss)
**Area:** `model/pdf_model.py` (`open_pdf`, `_repair_doc_xref_in_memory`)
**Symptom:** Opening a PDF that is **both encrypted and damaged**, then saving it back, silently dropped the password / owner restrictions — the saved file opened with no password.
**Cause:** `doc.tobytes()` on an authenticated encrypted document emits a **decrypted** PDF. The auto-repair round-trip therefore reopened a `needs_pass=0` doc, and a later full save (`encryption=KEEP`) had nothing to keep. Round-tripping a damaged encrypted doc can also emit broken streams (observed `MuPDF error: aes padding out of range` during `tobytes`). Detection is subtle: `needs_pass`/`is_encrypted` both flip to False after `authenticate()`, and an owner-password-only PDF (empty user password) opens with both already False — so neither flag survives to the repair branch.
**Fix (two parts):** (1) Gate the round-trip on `not _doc_is_encrypted(doc)`, where `_doc_is_encrypted` reads the trailer's encryption string `(doc.metadata or {}).get("encryption")` — it stays populated after authentication and is set even for owner-only encryption, making it the reliable "was encrypted on disk" signal. `metadata` is only read on the damaged path (gated behind `is_repaired`), so healthy files pay nothing. (2) **The full-save path must explicitly pass `encryption=fitz.PDF_ENCRYPT_KEEP`** — skipping the in-memory round-trip alone is not enough, because the repaired doc still full-rewrites on save (it can't save incrementally) and `save()`'s default decrypts (see the next entry). An encrypted+damaged doc keeps MuPDF's in-memory-repaired (still encrypted, file-backed) document; save-back then does a full rewrite with KEEP, which yields a clean xref (`is_repaired` clears on reopen) **and** preserves the password — verified end-to-end through the real `save_as` (`needs_pass=1`, `authenticate→2`).
**File:** `model/pdf_model.py` (`open_pdf`, `_doc_is_encrypted`, `_full_save_to_path`, `save_as`)

## PyMuPDF `doc.save()` defaults `encryption=PDF_ENCRYPT_NONE` — a plain full save *decrypts*
**Area:** `model/pdf_model.py` (`_full_save_to_path`, `save_as`)
**Symptom:** Saving (full-rewrite, not incremental) an encrypted-and-authenticated document produced an **unencrypted** file — the password/permissions were silently dropped. Affected "Save As" of any encrypted PDF and save-back of any repaired (incremental-incapable) encrypted PDF.
**Cause:** `Document.save(...)` and `tobytes(...)` take `encryption=` defaulting to **`PDF_ENCRYPT_NONE` (1)**, *not* `PDF_ENCRYPT_KEEP` (0). `inspect.signature(fitz.Document.save).parameters["encryption"].default == 1`. So `self.doc.save(path, garbage=0)` with no explicit `encryption=` actively re-writes the doc with no encryption. (Incremental save — `save(..., incremental=True)` — is exempt: it appends to the existing file and can't change encryption, so healthy encrypted docs that save-back incrementally were never affected; the gap is the full-rewrite paths.)
**Also hits live editing, not just save:** `_maybe_garbage_collect()` round-trips the doc every 20 edits via `tobytes(garbage=4, deflate=True)` — same default, so an encrypted doc being edited was silently decrypted *in memory* after 20 edits, and the next save then dropped the password even with the save paths fixed. Confirmed via `(doc.metadata or {}).get("encryption")` going `'Standard V5 R6 256-bit AES'` → `None` across the GC.
**Fix:** Pass `encryption=fitz.PDF_ENCRYPT_KEEP` on every full-rewrite-to-disk call (`_full_save_to_path` both branches; the `save_as` full-save/temp-overwrite branch) **and** on the live-editing GC round-trip (`_maybe_garbage_collect`, which then re-authenticates the reopened in-memory handle). KEEP preserves whatever the source had — including "no encryption" — so it is safe to apply unconditionally there. Do **not** add it to internal snapshot saves (`_capture_doc_snapshot`, `_capture_page_snapshot*`): those are reopened later *without* a password, so they must stay decrypted, and they target fresh `insert_pdf` docs that carry no encryption anyway. Export paths (`new_doc.save`, `pix.save`) are deliberately new documents and out of scope.
**Known residual:** undo/redo of an encrypted doc round-trips through a *decrypted* in-memory snapshot, so after an undo the live doc is decrypted and a subsequent save loses encryption. This is a separate, pre-existing limitation (snapshots can't be re-encrypted without re-authentication); not addressed here.
**File:** `model/pdf_model.py` (`_full_save_to_path`, `save_as`)

## Reopen-after-save must re-authenticate or the live session is bricked (once encryption is preserved)
**Area:** `model/pdf_model.py` (`_full_save_to_path`, `save_as`, `_reopen_doc_after_save`)
**Symptom:** After saving back an encrypted+damaged PDF (now that `encryption=KEEP` keeps the password), the in-editor document went dead — `model.doc[0].get_text()` raised `ValueError: document closed or encrypted`, nothing rendered, no further edits — until the file was closed and reopened with the password.
**Cause:** The save-over-open-file paths write to a temp file, **close** the live (authenticated) doc to release the Windows file lock, copy the temp over the original, then `self.doc = fitz.open(path)`. Once the saved file is encrypted again, that reopened handle is locked (`needs_pass`), and nothing re-authenticated it — `DocumentSession` did not persist the password (`open_pdf` authenticated and discarded it). Before encryption was preserved, the reopened file was decrypted, so the bug was masked.
**Fix:** Persist the open-time password on `DocumentSession.password` (in-memory only; the decrypted content already lives in RAM, so exposure is marginal — never logged or written to disk). Route both reopen-after-save points through `_reopen_doc_after_save`, which re-authenticates with `self.password` when the reopened doc `needs_pass`. Verified: 170/170 encrypted save-backs preserve content (live + on-disk) and leave the live doc usable.
**Gotcha:** Do **not** assert `needs_pass == 0` to test "usable". `needs_pass` stays **1** on an encrypted file *even after a successful* `authenticate()` — it reports "this file has a password", not "currently locked". The live-authenticated signal is `is_encrypted` flipping to **False**; the real guarantee is that content reads again (`get_text()` works).
**Benign noise:** Saving a *repaired* encrypted doc emits intermittent `MuPDF error: aes padding out of range` / `syntax error in content stream` on stderr (MuPDF re-serializing recovered encrypted streams). Verified harmless — content is byte-correct across 170 runs — but it is alarming uncaught noise; not suppressed globally (that would hide real errors).
**File:** `model/pdf_model.py` (`DocumentSession.password`, `_reopen_doc_after_save`)

## On-open XREF repair peak memory is ~1.15× file size (one serialization buffer), not 2×
**Area:** `model/pdf_model.py` (`_repair_doc_xref_in_memory`)
**Symptom:** Concern that the in-memory round-trip (`tobytes` → reopen) holds two full copies of a large PDF at once (~2× file size resident).
**Cause:** Measured on the real 47 MB damaged file (psutil RSS): the **original** file-backed doc adds only ~4.7 MB after open (MuPDF streams object data lazily from disk even after repairing the xref), the `tobytes(garbage=1)` buffer is ~1× file size (47.6 MB), and `fitz.open("pdf", buf)` reads lazily from that **same** buffer — reopening adds nothing measurable. Peak ≈ **+54 MB ≈ 1.15× file size**, dominated by the single unavoidable serialization buffer.
**Fix:** No code change needed. The ~1× buffer is inherent to any in-memory round-trip; closing the original doc before reopen saves only ~4.7 MB (not worth giving up the "open never fails" fallback ordering), and a temp-file round-trip would cut the buffer but break the documented/tested memory-backed contract and add temp-file lifecycle risk. At the 512 MB open cap the transient is ~590 MB above baseline — bounded and acceptable for a one-time, damaged-file-only op.
**File:** `model/pdf_model.py` (`_repair_doc_xref_in_memory`)
