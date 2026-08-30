# PITFALLS.md — Known Failure Modes

> Add entries here whenever a non-obvious bug is fixed. Format:
> `## <short title>` / Area / Symptom / Cause / Fix / File

---

## Import-time `sys.exit` aborts pytest collection for the whole suite

**Area:** `scripts/ux_signoff_agent.py` (R0.2)
**Symptom:** `.venv\Scripts\python.exe -m pytest test_scripts/` dies with `INTERNALERROR ... SystemExit: 1` after collecting ~983 of 1375 tests; the shipped stack cannot run the suite at all.
**Cause:** An optional dependency was imported at module top with `try: import pyautogui except ImportError: sys.exit(1)`. Two CUA tests import the module at top level, so the `sys.exit` ran during *collection* and aborted the whole session — not just those tests.
**Fix:** Bind the optional name to `None` on `ImportError` and resolve it lazily at the use-site (`_require_pyautogui()` raises a clear `RuntimeError`). A missing optional dep then degrades to a runtime error in the one code path that needs it, never a collection abort.
**File:** `scripts/ux_signoff_agent.py`

---

## Exact-count test assertions go stale on additive changes

**Area:** `test_scripts/test_theme_and_icons.py` (R0.1)
**Symptom:** `assert len(ACTION_ICON_MAP) == 32` failed (`33 == 32`) after a ribbon action was added; the product was correct, the literal was stale.
**Cause:** A bare magic-number count with no membership invariant breaks on every legitimate addition and tells you nothing about *which* entry changed.
**Fix:** Keep the exact count (it still catches a *dropped* icon) **and** pair it with a membership invariant — every mapped label resolves to a non-empty PNG on disk. Count + membership catches both additions and silent asset removals.
**File:** `test_scripts/test_theme_and_icons.py`

---

## PyMuPDF 1.27 names a stream-opened doc `"pdf"`, not `""`

**Area:** `model/pdf_model.py` repair round-trip; `test_scripts/test_xref_repair.py` (R0.4)
**Symptom:** After `_repair_doc_xref_in_memory`, `model.doc.name == "pdf"` on PyMuPDF 1.27 where 1.25 returned `""`; tests using `doc.name == ""` as a "memory-backed" proxy fail.
**Cause:** `fitz.open("pdf", repaired_bytes)` still produces a memory/stream doc, but 1.27 reflects the filetype argument (`"pdf"`) in `doc.name`; 1.25 left it empty. The product behavior (round-trip to memory) is unchanged.
**Fix:** Don't use `doc.name == ""` to mean "memory-backed". Assert `doc.name in ("", "pdf")` (or `!= <original path>`), and prefer `is_repaired is False` as the real proof the xref round-trip happened.
**File:** `test_scripts/test_xref_repair.py`

---

## PyMuPDF 1.27 `insert_htmlbox` renders nothing on overflow at `scale_low=1`

**Area:** `view/text_editing.py` `PreviewRenderer.render`; `test_scripts/test_rotated_text_editor_preview.py` (R0.4)
**Symptom:** A preview that produced (clipped) ink on 1.25 produces **zero** ink on 1.27 when the text cannot fit the box at 100% scale; `insert_htmlbox` returns a negative spare-height (`-1`).
**Cause:** With `scale_low=1` (no shrink permitted, used for pixel-parity with the commit path), 1.27 declines to render overflowing content at all where 1.25 rendered it clipped. A test feeding a 20pt-wide box an unrotated 7-glyph run hit this; real rotated cases (90/270) swap to a wide page and still fit.
**Fix (test):** size controls so the text fits at every rotation (60×120, not 20×120). **Watch (product):** the live preview/commit may blank out for edits that overflow the box at 100% — flagged for a follow-up assessment, not changed here.
**File:** `test_scripts/test_rotated_text_editor_preview.py`

---

## Stall watchdog needs an injectable clock to be testable under load

**Area:** `src/printing/subprocess_runner.py`; `test_scripts/test_print_subprocess_runner.py` (R0.3)
**Symptom:** `test_runner_heartbeat_events_prevent_false_stall` flaked in full-suite runs (passed in isolation): under CPU contention the real-clock 40ms watchdog false-fired between heartbeats spaced by `time.sleep(0.02)`.
**Cause:** `_check_stall` read wall-clock `time.monotonic()`, so test timing depended on OS scheduling, not the heartbeats it meant to assert.
**Fix:** Add a `monotonic: Callable[[], float] = time.monotonic` injection seam (production default unchanged); the test passes a `_FakeClock` it advances explicitly, making stall detection wall-clock independent and deterministic.
**File:** `src/printing/subprocess_runner.py`

---

## Windows fatal exception `0x80040155` in the offscreen test suite is benign

**Area:** test suite under `QT_QPA_PLATFORM=offscreen` (R0.4)
**Symptom:** `Windows fatal exception: code 0x80040155` with a `Current thread ... (most recent call first)` stack dump appears repeatedly during the pytest run; the suite still reports all-passed.
**Cause:** `0x80040155` is `REGDB_E_IIDNOTREG` — a *handled* COM/OLE exception from Qt's Windows integration in headless/offscreen mode. pytest's built-in faulthandler prints any SEH exception's stack even when it is caught and the process continues.
**Fix:** Nothing — it is noise, not a crash. The suite stays green and deterministic across runs. Do **not** disable faulthandler (it would also hide real native crashes); recognize this code and move on.
**File:** n/a (environment artifact)

---

## `ruff --fix` (F401) silently strips an intentional re-export

**Area:** `model/pdf_model.py` (R1.1)
**Symptom:** After a blanket `ruff check --fix .`, `test_security_pdf_resource_guards` failed with `AttributeError: module 'model.pdf_model' has no attribute '_MAX_PIXMAP_PX'`.
**Cause:** `pdf_model.py` imported `_MAX_PIXMAP_PX` from `utils/render_limits` purely to **re-export** it (external callers/tests read `pdf_model._MAX_PIXMAP_PX`). It is unused *within* the module, so ruff flagged F401 and `--fix` removed it — exactly the dynamic/re-export footgun blanket autofix is prone to.
**Fix:** Restore the import and annotate the intent: `from utils.render_limits import _MAX_PIXMAP_PX, ...  # noqa: E402, F401` with a comment. Before running `ruff --fix` on a module, scan for symbols other modules access via `<module>.<name>` (re-exports) and `# noqa: F401` them first.
**File:** `model/pdf_model.py`

---

## Module docstring after `from __future__` makes every import E402

**Area:** `model/pdf_optimizer.py` (R1.1)
**Symptom:** Every import in the file is flagged E402 ("module level import not at top of file") even though they sit directly below the docstring.
**Cause:** The file opened with `from __future__ import annotations` and *then* the module docstring. A docstring placed after a statement is a plain string-expression statement, so ruff treats it as code and every subsequent import is "not at top". (It is also a dead expression, not the module `__doc__`.)
**Fix:** Order is docstring → `from __future__ import annotations` → imports. The `__future__` import is permitted to follow the docstring; the docstring must be the file's first statement to remain `__doc__`.
**File:** `model/pdf_optimizer.py`

---

## Consolidating identity strings must preserve IPC prefixes byte-identical

**Area:** `utils/app_identity.py`, `utils/single_instance.py`, `utils/preferences.py` (R1.2)
**Symptom:** A drifted single-instance server-name prefix or QSettings org/app breaks open-file forwarding to a running instance, or "resets" preferences — with **no exception** surfaced.
**Cause:** These are compatibility values shared with already-running / already-installed builds (`cybersagapdf_singleinstance_`, the legacy `pdf_editor_singleinstance_` probe, and `QSettings("CyberSaga"/"CyberSagaPDF")` plus the legacy `pdf_editor` migration source). A consolidation that "tidies" any of them silently breaks runtime behavior.
**Fix:** Source them from the `utils/app_identity.py` leaf and pin them byte-identical with a test (`test_app_identity.py`). The Windows `.ps1` cannot import Python, so it mirrors the leaf with a header sync-note.
**File:** `utils/app_identity.py`

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

## Centering a page requires updating every scene/document x conversion

**Area:** continuous rendering and interaction geometry (`view/pdf_view.py`, `view/text_selection.py`, `view/object_selection.py`, `view/text_editing.py`)
**Symptom:** Mixed portrait/landscape pages looked centered, but clicks, selection highlights, object handles, annotation rectangles, or inline editors were horizontally displaced on narrower pages.
**Cause:** Moving only the page `QGraphicsPixmapItem` introduces a per-page scene x origin. Older code assumed every page began at scene x=0 and converted with `scene_x / render_scale` or `doc_x * render_scale` at many independent sites.
**Fix:** Store `page_x_positions` parallel to y positions and route all page geometry through `_page_scene_x/_page_scene_y`, `_scene_pos_to_page_and_doc_point`, `_doc_rect_to_scene_rect`, and `_get_page_scene_rect`. Pixmap quality replacement must preserve the placeholder item position. Regression-test text, objects, annotations, and editor placement—not only the visible page image.
**File:** `view/pdf_view.py`, `view/text_selection.py`, `view/object_selection.py`, `view/text_editing.py`

---

## Structural TOC remapping must start from the pre-operation entries

**Area:** `model/pdf_model.py` page insert/delete/move and TOC APIs
**Symptom:** Bookmarks drift to the wrong logical content after page operations, or deleted-target bookmarks disappear/change before custom remapping runs.
**Cause:** PyMuPDF may adjust document navigation structures as pages mutate. Reading `doc.get_toc()` only after the operation loses the original page identity needed to distinguish moved, shifted, and deleted targets.
**Fix:** Capture normalized TOC entries before the structural mutation, apply the same final-index map used by the page operation, clamp every result to the final page count, then replace the document TOC. Deleted targets map to the nearest surviving original page; delete-all maps to page 1.
**File:** `model/pdf_model.py`, `test_scripts/test_bookmarks_toc.py`

---

## Tab detachment must be prepare-first and must not share a live document

**Area:** `controller/session_transfer.py`, `controller/pdf_controller.py`, `main.py`
**Symptom:** A failed detached-window creation loses the source tab, or edits/close/undo in one window corrupt the other window.
**Cause:** Closing the source before destination readiness is non-atomic; sharing a `fitz.Document`, command manager, or worker across windows violates both PyMuPDF thread safety and MVC lifecycle ownership.
**Fix:** Transfer immutable snapshot bytes and metadata in a repr-safe DTO, build and activate a fully independent MVC triple in `main.py`, restore UI state, then acknowledge readiness. Only after a true acknowledgment may the source controller close its session. Pre-detach undo history is deliberately not transferred.
**File:** `controller/session_transfer.py`, `view/detachable_tab_bar.py`, `controller/pdf_controller.py`, `model/pdf_model.py`, `main.py`

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

## PyMuPDF forward page moves use a pre-removal destination

**Area:** `model/pdf_model.py`
**Symptom:** Dragging page 1 to the visual position after page 3 leaves it after page 2 instead.
**Cause:** `fitz.Document.move_page(source, destination)` interprets a forward `destination` before removing `source`; the requested final row is therefore one greater than its native insertion index. Moving to the final page uses PyMuPDF's `-1` sentinel rather than `page_count`.
**Fix:** Keep `PDFModel.move_page()`'s public source/destination contract as final 0-based rows, then translate forward moves to `destination + 1` or `-1` for the final boundary. Mark the entire moved index interval stale and rebuild its destination anchor immediately.
**File:** `model/pdf_model.py`, `model/text_block.py`
**Tests:** `test_scripts/test_page_reorder.py`

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
**Cause:** `Document.save(...)` and `tobytes(...)` take `encryption=` defaulting to **`PDF_ENCRYPT_NONE` (1)**, *not* `PDF_ENCRYPT_KEEP` (0). `inspect.signature(fitz.Document.save).parameters["encryption"].default == 1`. So `self.doc.save(path, garbage=0)` with no explicit `encryption=` actively re-writes the doc with no encryption. (Incremental save — `save(..., incremental=True)` — is **not** exempt either, contrary to an earlier assumption: the default `encryption=NONE` conflicts with incremental and *raises* — see the dedicated incremental entry below.)
**Also hits live editing, not just save:** the same default bit every *live-doc round-trip* (`self.doc = fitz.open(self.doc.tobytes(...))`). Found one at a time across reviews — `_maybe_garbage_collect()` (every 20 edits) and `_repair_active_doc_in_memory()` (error-recovery fallback for damaged docs) — each silently decrypting the live doc in memory (`(doc.metadata or {}).get("encryption")` going `'Standard V5 R6 256-bit AES'` → `None`), so the next save dropped the password even with the save paths fixed.
**Fix (structural, not per-call):** There are now **two serialization chokepoints**, each of which always injects `encryption=fitz.PDF_ENCRYPT_KEEP`, so no call site spells the kwarg itself. (1) Disk/stream writes go through `_save_doc(doc, target, *, garbage=, incremental=)` — covers `_full_save_to_path` both branches, the `save_as` full-save / temp-overwrite / **incremental** branches, and the doc-level snapshot capture. (2) In-memory round-trips go through `_roundtrip_live_doc(garbage=, deflate=)`, which serializes with `encryption=KEEP`, re-authenticates the reopened handle (`_reauthenticate_if_needed`, using the in-memory `DocumentSession.password`), and opens the new handle before closing the old so a failed round-trip leaves the live doc intact. A regression test (`test_live_doc_roundtrips_preserve_encryption`) AST-scans the module and fails on any **direct** `self.doc.tobytes(...)` / `self.doc.save(...)` lacking `encryption=` — a backstop for code that bypasses the two funnels. KEEP preserves whatever the source had (including "no encryption"), so it is always safe here. Export paths (`new_doc.save`, `pix.save`) are deliberately new documents and out of scope.
**Known residual (now closed for password loss):** the doc-level snapshot path was the last instance of this invariant and is fixed in the entry below; page-level snapshots never lost the password (in-place restore). What remains is only in-memory plaintext snapshot bytes — a defense-in-depth note, not a save-back hole.
**File:** `model/pdf_model.py` (`_save_doc`, `_roundtrip_live_doc`, `_full_save_to_path`, `save_as`, `_maybe_garbage_collect`, `_repair_active_doc_in_memory`)

## Incremental save needs `encryption=KEEP` too — the default *raises*, silently degrading every encrypted save-back to a full rewrite
**Area:** `model/pdf_model.py` (`save_as` incremental branch)
**Symptom:** Every save-back of a **healthy encrypted** PDF logged `WARNING 增量更新儲存失敗，改為完整儲存: code=4: Can't do incremental writes when changing encryption` and did a full rewrite instead of an incremental update. The password *survived* (the full-rewrite fallback passes `encryption=KEEP`), so it looked harmless — but incremental save, the whole point of fast save-back, was defeated for all encrypted files, and the scary warning fired on every save.
**Cause:** The `encryption=KEEP` sweep covered only the full-rewrite save paths; the incremental call `self.doc.save(save_target, incremental=True)` was left with the default `encryption=NONE` (1). PyMuPDF *cannot change encryption during an incremental write*, so the default NONE (≠ the file's KEEP) makes it **raise** `FzErrorArgument` rather than silently decrypt. The `except` clause caught it and fell back to `_full_save_to_path`. So the earlier belief that "incremental is exempt because it can't change encryption" was backwards: it can't change encryption, therefore you must pass `KEEP` explicitly, or it errors out.
**Fix:** Pass `encryption=fitz.PDF_ENCRYPT_KEEP` on the incremental save too (it now routes through the shared `_save_doc` chokepoint with `incremental=True`, so there is no separate literal to forget). KEEP is a no-op for unencrypted docs (verified: `needs_pass=0`, content intact) and preserves the password for encrypted docs as a true incremental append (verified: `needs_pass=1`, `authenticate()→2`, file grows rather than rewrites). The AST guard was widened to flag `self.doc.save(...)` (not just `tobytes`) missing `encryption=`, so this class can't recur.
**Gotcha:** A "password still survives" end-to-end test is **not** enough to catch this — the fallback preserved it. The behavioral test (`test_healthy_encrypted_save_back_uses_incremental_and_keeps_password`) spies on `_full_save_to_path` and asserts it is **not** called, so a silent degradation to full rewrite fails the test.
**File:** `model/pdf_model.py` (`save_as`), `test_scripts/test_xref_repair.py`

## Reopen-after-save must re-authenticate or the live session is bricked (once encryption is preserved)
**Area:** `model/pdf_model.py` (`_full_save_to_path`, `save_as`, `_reopen_doc_after_save`)
**Symptom:** After saving back an encrypted+damaged PDF (now that `encryption=KEEP` keeps the password), the in-editor document went dead — `model.doc[0].get_text()` raised `ValueError: document closed or encrypted`, nothing rendered, no further edits — until the file was closed and reopened with the password.
**Cause:** The save-over-open-file paths write to a temp file, **close** the live (authenticated) doc to release the Windows file lock, copy the temp over the original, then `self.doc = fitz.open(path)`. Once the saved file is encrypted again, that reopened handle is locked (`needs_pass`), and nothing re-authenticated it — `DocumentSession` did not persist the password (`open_pdf` authenticated and discarded it). Before encryption was preserved, the reopened file was decrypted, so the bug was masked.
**Fix:** Persist the open-time password on `DocumentSession.password` (in-memory only; the decrypted content already lives in RAM, so exposure is marginal — never logged or written to disk). Route both reopen-after-save points through `_reopen_doc_after_save`, which re-authenticates with `self.password` when the reopened doc `needs_pass`. Verified: 170/170 encrypted save-backs preserve content (live + on-disk) and leave the live doc usable.
**Gotcha:** Do **not** assert `needs_pass == 0` to test "usable". `needs_pass` stays **1** on an encrypted file *even after a successful* `authenticate()` — it reports "this file has a password", not "currently locked". The live-authenticated signal is `is_encrypted` flipping to **False**; the real guarantee is that content reads again (`get_text()` works).
**Benign noise:** Saving a *repaired* encrypted doc emits intermittent `MuPDF error: aes padding out of range` / `syntax error in content stream` on stderr (MuPDF re-serializing recovered encrypted streams). Verified harmless — content is byte-correct across 170 runs — but it is alarming uncaught noise; not suppressed globally (that would hide real errors).
**File:** `model/pdf_model.py` (`DocumentSession.password`, `_reopen_doc_after_save`)

## Undo/redo snapshots: only the *doc-level* path decrypts — page-level restores in place
**Area:** `model/pdf_model.py` (`_capture_doc_snapshot`, `_restore_doc_from_snapshot`, `_restore_page_from_snapshot`)
**Symptom:** Undo/redo of a *structural* edit on an encrypted doc left the live document decrypted, so the next save silently dropped the password — even after every save path and live-doc round-trip was already encryption-safe.
**Cause:** There are two distinct snapshot mechanisms, and only one was affected. **Doc-level** snapshots (`SnapshotCommand` for structural ops) *replace the live handle*: `_restore_doc_from_snapshot` does `self.doc = fitz.open("pdf", snapshot_bytes)`, and `_capture_doc_snapshot` serialized with `save()`'s decrypting default — so restoring an undo swapped in a `needs_pass=0` doc. **Page-level** snapshots (`_restore_page_from_snapshot`) *mutate the still-encrypted live doc in place* via `insert_pdf`/`delete_page` — they never replace the handle, so the live doc keeps its encryption and a save-back keeps the password (verified `needs_pass=1`); the implementer's earlier "page-level needs full re-encryption logic to keep the password" framing was inaccurate for the save-back guarantee.
**Fix:** Capture the doc-level snapshot with `encryption=fitz.PDF_ENCRYPT_KEEP`, and re-authenticate the reopened handle in `_restore_doc_from_snapshot` via `_reauthenticate_if_needed` (reusing the in-memory `DocumentSession.password`). No-op for unencrypted docs. Verified end-to-end: capture→restore→save_as on an encrypted doc keeps `metadata.encryption`, leaves the live doc usable, and reopens at `needs_pass=1` / `authenticate→2`. Page-level capture is left untouched (it saves a fresh `insert_pdf` tmp doc, structurally unencrypted — KEEP would be a no-op there).
**Residual (tracked, not a password bug):** page-level snapshot *bytes* held in the undo history are plaintext in memory. This is the same exposure class as the already-decrypted live document, never reaches disk, and does not affect the saved file's encryption. Encrypting them at rest would need real re-encryption (method + permissions + both keys, of which the session holds only the one password the user typed) — deferred to a separate task.
**File:** `model/pdf_model.py` (`_capture_doc_snapshot`, `_restore_doc_from_snapshot`)

## On-open XREF repair peak memory is ~1.15× file size (one serialization buffer), not 2×
**Area:** `model/pdf_model.py` (`_repair_doc_xref_in_memory`)
**Symptom:** Concern that the in-memory round-trip (`tobytes` → reopen) holds two full copies of a large PDF at once (~2× file size resident).
**Cause:** Measured on the real 47 MB damaged file (psutil RSS): the **original** file-backed doc adds only ~4.7 MB after open (MuPDF streams object data lazily from disk even after repairing the xref), the `tobytes(garbage=1)` buffer is ~1× file size (47.6 MB), and `fitz.open("pdf", buf)` reads lazily from that **same** buffer — reopening adds nothing measurable. Peak ≈ **+54 MB ≈ 1.15× file size**, dominated by the single unavoidable serialization buffer.
**Fix:** No code change needed. The ~1× buffer is inherent to any in-memory round-trip; closing the original doc before reopen saves only ~4.7 MB (not worth giving up the "open never fails" fallback ordering), and a temp-file round-trip would cut the buffer but break the documented/tested memory-backed contract and add temp-file lifecycle risk. At the 512 MB open cap the transient is ~590 MB above baseline — bounded and acceptable for a one-time, damaged-file-only op.
**File:** `model/pdf_model.py` (`_repair_doc_xref_in_memory`)

---

## Eager module-level imports of optional native deps block cold-boot startup

**Area:** `view/text_editing.py`, `view/pdf_view.py`
**Symptom:** First launch after reboot took 15+ seconds; subsequent launches were fast (2-3 s).
**Cause:** Two module-level import chains loaded 55 MB of native DLLs before the window appeared:
1. `view/text_editing.py` had `try: import numpy as np` at module top -- ran the 24 MB numpy load the moment any code imported the module, even before any text editing.
2. `view/pdf_view.py` had `from view.dialogs import (...)` at module level -- chained through `model.pdf_optimizer` -> PIL + pikepdf (which pulls lxml), 31 MB total.
**Fix:** Moved the `try: import numpy as np / except ImportError: np = None` block inside each of the 5 numpy-using functions. Replaced the eager dialog re-export block in `view/pdf_view.py` with a PEP 562 module-level `__getattr__` that imports from `view.dialogs` on first access and caches names into `globals()`. Internal uses of dialog classes within `pdf_view.py` itself use function-local imports.
**File:** `view/text_editing.py`, `view/pdf_view.py`
**Tests:** `test_scripts/test_startup_heavy_imports.py`

## QApplication-level QSS leaks across tests and shifts inline-editor pixels
**Area:** test_scripts (process-wide Qt state), view/text_editing.py, view/pdf_view.py
**Symptom:** 7 order-dependent failures in `test_no_jump_editor_geometry.py` when the full suite runs (~57.86% pixel diff vs the 1% threshold); the same tests pass in isolation (377 passed).
**Cause:** Every test in `test_main_startup_behavior.py` runs `main_module.run(...)`, which calls `view.apply_initial_theme()` -> `app.setStyleSheet(build_qss(theme_id))`. The QApplication is a session-wide singleton, and `_cleanup_startup()` never cleared the stylesheet, so the theme QSS (`QTextEdit { padding: 4px 8px; ... }`) stayed active for every later test. When Qt polishes a freshly shown `PreviewBackedInlineTextEditor`, the app QSS padding overrides the constructor's `setViewportMargins(0,0,0,0)`, shifting the editor text relative to the PDF rendering in pixel-diff comparisons.
**Fix:** Four layers: (1) `_cleanup_startup()` now calls `app.setStyleSheet("")` before `app.quit()`; (2) `PreviewBackedInlineTextEditor.__init__` sets a widget-level QSS override (`QTextEdit { padding: 0px; border: 0px; margin: 0px; }`) -- widget QSS beats app QSS, so the inline editor stays flush to the page even in a themed production app; (3) a function-scoped autouse fixture in `test_scripts/conftest.py` snapshots `app.styleSheet()` before each test and restores it after, so no future test can leak app-level QSS; (4) `_build_text_editor_stylesheet` (pdf_view.py) now includes `padding: 0px; margin: 0px;` in the replacement stylesheet that is applied after editor creation and on every mask refresh — this prevents the theme rule from cascading back after the initial `__init__` stylesheet is overwritten.
**Gotcha:** `setViewportMargins()`/`setContentsMargins()` are NOT a defense against stylesheets -- app-level QSS padding is applied at polish time (first `show()`), after the constructor runs, and silently wins.
**File:** `test_scripts/test_main_startup_behavior.py`, `view/text_editing.py`, `view/pdf_view.py`, `test_scripts/conftest.py`

## Preview render must clamp scale for pathological pages
**Area:** `view/text_editing.py` (`_MuPDFPreviewRenderer._render_preview`), `utils/render_limits.py`
**Symptom:** A page with very large dimensions rendered via the inline-editor preview path could produce an enormous pixmap (hundreds of megapixels), consuming memory or crashing.
**Cause:** The preview `get_pixmap` call used `render_scale` unclamped; `_safe_render_scale` lived in `model/pdf_model.py` which the view layer cannot import.
**Fix:** Extracted `safe_render_scale` and `_MAX_PIXMAP_PX` to `utils/render_limits.py` (view→utils is legal); `pdf_model.py` re-exports for backward compatibility. The preview renderer now calls `_safe_render_scale(temp_page, render_scale)` before `get_pixmap`.
**File:** `utils/render_limits.py`, `view/text_editing.py`, `model/pdf_model.py`
**Tests:** `test_scripts/test_text_editor_theme_padding.py`

## PyMuPDF `linear=1` removed in 1.24+; the pikepdf-absent fallback save was dead code
**Area:** `model/pdf_optimizer.py` (optimize-copy save pipeline)
**Symptom:** On the app runtime (`.venv`, PyMuPDF 1.27.1, no pikepdf) the 「極致壓縮」 preset crashed `另存為最佳化的副本` (`code=4: Linearisation is no longer supported`); the test suite never caught it because the test runner's PyMuPDF 1.25.5 still silently accepts `linear=1`. The fallback also raised `ValueError: 'linear' and 'use_objstms' cannot both be requested` for un-normalized options, and the controller doubled the error prefix (`最佳化 PDF 失敗: 最佳化 PDF 失敗: ...`).
**Cause:** `save_optimized_working_doc` had a "no pikepdf" fallback branch that passed `linear=`/`use_objstms=` straight to `fitz.Document.save(...)`; PyMuPDF removed linearization in 1.24, so post-save packaging is only deliverable via pikepdf. The generic `except Exception` wrapper in `save_optimized_copy` re-wrapped already-wrapped messages, and `_on_optimize_copy_failed` prefixed them a second time.
**Fix:** Deleted the dead fallback — `save_optimized_working_doc` now fails fast with `PdfOptimizeError` (actionable Chinese message) when packaging is requested without pikepdf. `optimize_capabilities()` probes the runtime; the controller passes it to `OptimizePdfDialog(capabilities=...)`, which disables + unchecks the gated checkboxes *before* applying presets (preset writes are guarded with `isEnabled()`, and the gate's `setChecked` calls are wrapped in `_applying_preset` so `_mark_custom` doesn't flip the combo to 自訂 — `setChecked` works on disabled widgets, so the guard is mandatory). `save_optimized_copy` re-raises `PdfOptimizeError` bare and wraps only unexpected exceptions once; the controller shows `str(exc)` without re-prefixing. `pikepdf>=8.0` added to `optional-requirements.txt` and installed into `.venv`.
**File:** `model/pdf_optimizer.py`, `model/pdf_model.py`, `view/dialogs/optimize.py`, `controller/pdf_controller.py`
**Tests:** `test_scripts/test_pdf_optimize_workflow.py` (capability gate / domain error / no-double-prefix; always monkeypatch `_pikepdf` to simulate absence — the test env has pikepdf installed)

## Foreign-PDF opens need the full resource-guard set, not just the primary open path

**Area:** `model/pdf_model.py`, `model/headless_merge.py`
**Symptom:** A merge/insert source PDF that would be rejected by `open_pdf` (oversize file, excess pages, encrypted) was opened with a bare `fitz.open(...)` in `insert_pages_from_file` and `headless_merge`, so a crafted "foreign" document could OOM/hang the process through a side door the primary path already guards (CWE-400).
**Cause:** The F1 guards (`_guard_before_open`, `_MAX_PAGES` check) were wired only into `PDFModel.open_pdf`; every other `fitz.open` call site on user-supplied paths was added independently and never picked them up.
**Fix:** Single chokepoint `_guard_foreign_doc(path)` in `model/pdf_model.py` (size limit → open → encryption check → page limit; caller closes). All non-primary opens of user-supplied PDFs route through it. `insert_pages_from_file` additionally enforces the post-merge invariant `len(self.doc) + len(inserted) <= _MAX_PAGES` BEFORE inserting. Any future `fitz.open` on a path the user picked must go through `_guard_foreign_doc`, never bare `fitz.open`.
**File:** `model/pdf_model.py` (`_guard_foreign_doc`, `insert_pages_from_file`), `model/headless_merge.py`
**Tests:** `test_scripts/test_security_pdf_resource_guards.py`, `test_scripts/test_headless_merge.py`

## Python negative indexing turns page 0 into a silent doc[-1] mutation

**Area:** `model/tools/annotation_tool.py` (pattern applies to every `doc[page_num - 1]` site)
**Symptom:** Calling `add_highlight`/`add_rect` with `page_num=0` did not fail — it silently annotated the LAST page (`doc[0 - 1]` == `doc[-1]`), a wrong-page document mutation with no error signal.
**Cause:** The 1-based→0-based conversion `doc[page_num - 1]` hits Python's negative-index semantics for `page_num=0` (and PyMuPDF accepts negative page indexes), so the out-of-range input maps to a valid page instead of raising.
**Fix:** `AnnotationTool._require_page(page_num)` validates the no-doc case and `1 <= page_num <= len(doc)` before indexing, raising `ValueError`(「無效的頁碼: N」). All AnnotationTool page lookups go through it. When adding new 1-based page APIs, never index `doc[n - 1]` without a lower-bound check.
**File:** `model/tools/annotation_tool.py`
**Tests:** `test_scripts/test_tool_extensions.py` (`test_add_highlight_rejects_page_zero`, `test_add_rect_rejects_page_zero`, `test_add_highlight_rejects_out_of_range`)

## min/max do NOT sanitize NaN — they are argument-order sensitive

**Area:** `model/tools/watermark_tool.py` (pattern applies to any numeric clamp on untrusted input)
**Symptom:** `max(0.0, min(1.0, nan))` and friends can return NaN, so "clamped" watermark fields (angle, opacity, offsets) could still carry NaN/±inf into rendering math (`nan % 360 == nan`; `json.loads` accepts `NaN`/`Infinity` literals, and Python callers can pass them directly).
**Cause:** Python's `min`/`max` compare with `<`/`>`, and every comparison with NaN is False — so the result depends on argument ORDER (`min(nan, x) → nan`, `min(x, nan) → x`). A clamp built only from `min`/`max` silently passes NaN through on one ordering.
**Fix:** `_finite(v, lo, hi, default)` helper: explicit `math.isnan` screen (NaN → default) before `max(lo, min(hi, v))`; ±inf compares normally and clamps to the bounds. All watermark numeric fields go through `_finite` inside `_coerce_wm`, and `add_watermark`/`update_watermark` now funnel through `_coerce_wm` too, so there is exactly one sanitization chokepoint. Never "sanitize" untrusted floats with bare `min`/`max`.
**File:** `model/tools/watermark_tool.py` (`_finite`, `_coerce_wm`)
**Tests:** `test_scripts/test_security_watermark_coercion.py`, `test_scripts/test_tool_extensions.py::test_add_watermark_nan_angle_sanitized`

## IPC argv filters must resolve EVERY token — skipping relative paths is a bypass

**Area:** `utils/single_instance.py`
**Symptom:** The single-instance forwarded-argv filter validated only *absolute* tokens (exists + `.pdf` suffix) and let relative tokens through unchecked, so a local socket peer could smuggle arbitrary paths (e.g. `..\..\etc\passwd`-style traversal) past the filter into `on_message`.
**Cause:** The filter assumed sender-side normalization (`_normalize_forwarded_argv` resolves to absolute), but the untrusted peer is not bound by the sender's code — "legitimate input is always absolute" is not a property of hostile input.
**Fix:** `_forwarded_argv_is_acceptable` now `Path(item).resolve()`s every non-flag token and requires an existing `.pdf`; anything else rejects the whole message (ack `0`). Double-resolve of legitimate already-resolved paths is idempotent. Validate what the peer SENT, not what a well-behaved sender would have sent.
**File:** `utils/single_instance.py` (`_forwarded_argv_is_acceptable`)
**Tests:** `test_scripts/test_security_single_instance_isolation.py`

## Byte-budget eviction must decrement _saved_stack_size or has_pending_changes drifts

**Area:** `model/edit_commands.py` (`CommandManager._trim_undo_stack_if_needed`)
**Symptom:** After the 512 MiB undo byte budget evicts oldest commands, `has_pending_changes()` can report False with unsaved edits on the stack (or True right after a save), because the saved-depth marker still points at pre-eviction stack indices.
**Cause:** `_saved_stack_size` is an absolute depth into `_undo_stack`. Removing N entries from the FRONT shifts every remaining index down by N; any eviction pass (count cap OR byte budget) that does not subtract N desynchronizes the marker.
**Fix:** Both trim passes decrement `_saved_stack_size` by the number of evicted entries and clamp at 0 (`max(0, saved - evicted)`). Any future eviction path added to `CommandManager` must do the same.
**File:** `model/edit_commands.py` (`_trim_undo_stack_if_needed`)
**Tests:** `test_scripts/test_undo_memory_budget.py::test_byte_budget_evicts_oldest_snapshot_commands`

## Undo byte budget must floor at 1 command and use unique-byte accounting

**Area:** `model/edit_commands.py` (`CommandManager._trim_undo_stack_if_needed`, `_unique_byte_total`)
**Symptom:** (1) A single oversized command could be evicted, leaving `can_undo()` False and the edit silently lost. (2) After adjacent snapshot dedup (`curr._before_bytes = prev._after_bytes`), the shared bytes object was counted twice in the budget total, effectively halving the budget for deduped stacks.
**Cause:** (1) The trim loop had `while self._undo_stack and ...` with no floor. (2) `_byte_size()` sums `len(before) + len(after)` per command, not per unique object.
**Fix:** (1) Changed loop condition to `while len(self._undo_stack) > 1 and ...`, keeping the newest command; log warning if it still exceeds budget. (2) Added `_snapshot_chunks()` returning the actual `bytes` objects held; `_unique_byte_total()` sums `len(chunk)` over unique `id(chunk)` across all commands.
**File:** `model/edit_commands.py`
**Tests:** `test_scripts/test_undo_memory_budget.py` (`test_single_oversized_command_survives_byte_trim`, `test_dedup_shared_bytes_counted_once_in_budget`)

## Adjacent-snapshot dedup is only safe for SnapshotCommand pairs

**Area:** `model/edit_commands.py` (`CommandManager._dedup_top_snapshot_pair`)
**Symptom:** Naively extending the boundary-snapshot dedup ("op N after_bytes is op N+1 before_bytes") to page-level commands corrupts undo: page snapshots from different commands can be byte-equal while belonging to DIFFERENT pages, and `_after_page_snapshot_bytes` is captured lazily (still None at push time).
**Cause:** Only `SnapshotCommand` holds full-document serializations where "equal bytes" implies "identical document state". The dedup relies on `bytes` immutability plus `_restore_doc_from_snapshot` copying internally via `fitz.open("pdf", ...)`; sharing is a pure memory optimization with no aliasing hazard — but only under those invariants.
**Fix:** `_dedup_top_snapshot_pair()` double-`isinstance`-checks `SnapshotCommand`, short-circuits on identity (`is`) before paying the `==` comparison, and only assigns `curr._before_bytes = prev._after_bytes`. Do not widen it to `EditTextCommand`/`AddTextboxCommand`.
**File:** `model/edit_commands.py` (`_dedup_top_snapshot_pair`)
**Tests:** `test_scripts/test_undo_memory_budget.py` (`test_adjacent_dedup_shares_bytes_object`, `test_dedup_does_not_corrupt_undo_redo`)

## build_print_snapshot signature changed: () -> bytes became (dest: Path) -> None

**Area:** `model/tools/manager.py`, `model/pdf_model.py`, `controller/pdf_controller.py`
**Symptom:** Code (or test monkeypatches) written against the old `build_print_snapshot() -> bytes` contract raises `TypeError` or silently writes nothing: the method now takes a destination path and returns None.
**Cause:** The print path serialized the whole document into RAM (`io.BytesIO` -> bytes -> `write_bytes`) just to immediately write it to a temp file. The fix writes straight to disk (`doc.save(str(dest), garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP)` on the fast path; `tmp_doc.save(...)` on the overlay path), which required the signature change all the way up: `PrintJobRequest.capture_pdf_bytes` was renamed to `write_pdf_to: Callable[[Path], None]` and `PDFModel.capture_print_input_pdf_bytes()` was deleted (the submission worker was its only caller).
**Fix:** Call `model.build_print_snapshot(dest)` with a `Path`; the fast path must keep `encryption=fitz.PDF_ENCRYPT_KEEP` (plain `save()` defaults to NONE and decrypts protected documents — same chokepoint rationale as `PDFModel._save_doc`).
**File:** `model/tools/manager.py` (`ToolManager.build_print_snapshot`), `controller/pdf_controller.py` (`PrintJobRequest`, `_PrintSubmissionWorker.run`)
**Tests:** `test_scripts/test_print_snapshot_path.py`, `test_scripts/test_print_controller_flow.py`

## Uncapped portrait thumbnails can make page reordering impractical

**Area:** `view/pdf_view.py`
**Symptom:** A narrow sidebar displays only two very tall portrait thumbnails, so dragging one page over another requires leaving the sidebar and the internal move cannot complete.
**Cause:** Thumbnail height was derived only from sidebar width and the source page aspect ratio; portrait pages could create 345 px rows.
**Fix:** Preserve width-aware scaling but cap thumbnail icon height at 120 px in narrow sidebars, keeping at least three internal-drop targets visible at the real 900×620 shell size. (The earlier 168 px cap appeared sufficient only because the old 800 px minimum height silently enlarged the test window.)
**File:** `view/pdf_view.py`
**Tests:** `test_scripts/test_multi_tab_plan.py::test_06c1_thumbnail_rows_keep_three_drop_targets_visible`

---

## QListWidget InternalMove never reorders rows in IconMode with non-Static movement

**Area:** `view/pdf_view.py`
**Symptom:** Dragging a thumbnail either shows a forbidden cursor and never drops, or appears to reorder but removes the moved thumbnail afterward.
**Cause:** Three Qt item-view behaviors conflict here. `IconMode` with `Snap`/`Free` repositions icons without changing model rows. Switching to `Static` prevents that, but `setMovement(Static)` silently disables `viewport().acceptDrops()`, while a later `setAcceptDrops(True)` restores only the outer view; native drag events are delivered to the viewport. Finally, inherited `QAbstractItemView.startDrag()` removes the selected source row after a MoveAction completes, even though the custom `dropEvent()` has already relocated that same item.
**Fix:** Keep Static movement but explicitly restore `viewport().setAcceptDrops(True)`. Accept internal enter/move events in the subclass, compute the destination by scanning row centers, and perform `takeItem`/`insertItem` without calling Qt's internal drop handler. Own the `QDrag` in `startDrag()` so Qt never performs post-exec source-row removal. Nudge the vertical scrollbar within a 48 px edge margin so off-screen rows remain reachable.
**File:** `view/pdf_view.py` (`_ReorderableThumbnailList`)
**Tests:** `test_scripts/test_page_reorder.py` (native-delivery configuration, enter/move acceptance, manual drop, custom QDrag ownership, edge auto-scroll); real-GUI verification uses `test_files/test-colored-background.pdf`

---

## Instance-assigned Qt event handlers shadow class overrides

**Area:** `view/pdf_view.py` responsive shell
**Symptom:** A new `PDFView.resizeEvent()` override is present and lint-clean, but resizing the real/offscreen window never calls it, so compact-shell state does not change.
**Cause:** `PDFView.__init__()` already assigns `self.resizeEvent = self._resize_event` to preserve the existing scene/fullscreen resize path. The instance attribute shadows the class method entirely.
**Fix:** Extend the existing `_resize_event()` chokepoint rather than adding a second class-level override. Tests must assert the resulting sidebar visibility after a real `resize()` event, not merely call the helper directly.
**File:** `view/pdf_view.py`
**Tests:** `test_scripts/test_shell_tab_ux.py::test_small_shell_collapses_sidebars_and_preserves_canvas`

---

## Thumbnail invalidation must distinguish count-changed from count-unchanged

**Area:** `controller/pdf_controller.py` (`_invalidate_thumbnails`, `_schedule_thumbnail_batch`), `view/pdf_view.py` (`update_thumbnail_batch`)
**Symptom:** (1) After insert/delete, async thumbnail batches stop short if the widget item count is stale. (2) After rotate/straighten, `set_thumbnail_placeholders(n)` blanks ALL existing thumbnail icons (rows 0..n-1) even though only the rotated page changed — rotating 1 page of 2000 re-rasters all 2000. (3) `_invalidate_thumbnails` bumped `_load_gen_by_session`, which cancelled unrelated background loading and viewport-anchor restoration.
**Cause:** The original implementation always called `set_thumbnail_placeholders` (which clears ALL rows) and used `_next_load_gen` (shared counter) as the cancellation token.
**Fix:** When page count changed (widget item count != doc length), `set_thumbnail_placeholders` resets the widget first, then schedules a full batch. When count is unchanged and `affected` is known, skip the placeholder reset (preserve existing icons) and schedule a bounded batch covering only affected rows via the `end_limit` parameter. Thumbnail batches use a dedicated `_thumb_gen_by_session` counter — `_next_load_gen` bumps both counters, but `_invalidate_thumbnails` bumps only the thumb counter.
**File:** `controller/pdf_controller.py` (`_invalidate_thumbnails`, `_schedule_thumbnail_batch`)
**Tests:** `test_scripts/test_thumbnail_async.py`

## Cross-page text move must invalidate thumbnails

**Area:** `controller/pdf_controller.py` (`move_text_across_pages`)
**Symptom:** After a cross-page text move, the source and destination page thumbnails show stale content (old text still visible on source, new text missing on destination).
**Cause:** The success path had a wrong comment ("thumbnails stay valid") and skipped thumbnail invalidation. The rollback path also skipped it.
**Fix:** Call `_invalidate_thumbnails(sorted({source_page, destination_page}))` on both success and rollback paths.
**File:** `controller/pdf_controller.py`
**Tests:** `test_scripts/test_cross_page_text_move.py`

## Search worker must be cancelled (and waited for) before any document mutation

**Area:** `controller/pdf_controller.py` (`_SearchWorker`, `_cancel_search`), `model/tools/search_tool.py`
**Symptom:** Random crashes/corruption when deleting/rotating/inserting pages, undo/redo, switching or closing tabs while a search is running: the worker thread reads the live fitz document while the GUI thread mutates (or closes) it.
**Cause:** PyMuPDF documents are not safe for concurrent read-during-mutation, and the worker resolves `model.doc` dynamically ??a tab switch silently swaps the document under it mid-search.
**Fix:** Search workers now read from a private snapshot byte buffer captured on the GUI thread, so live-doc mutation no longer races the worker. `_cancel_search()` still drops stale generations and requests cancel, but it only clears the session `search_state` when an in-flight search is actually being aborted; a completed search keeps its results so tab restore can repopulate the finished results list. Two thread-lifecycle gotchas still matter: (1) controller refs to the `QThread` wrapper must be released on `thread.finished` (identity-checked `_release_search_thread`), NOT on `worker.finished` ??dropping the wrapper while the thread still runs lets Python GC destroy the C++ QThread and hard-crash the process with no traceback; (2) queued cross-thread signals already posted before a cancel are still delivered afterwards, so every worker signal carries the `_search_gen` generation token and handlers drop stale generations.
**File:** `controller/pdf_controller.py` (`_cancel_search`, `_on_search_finished`, `_release_search_thread`)
**Tests:** `test_scripts/test_search_worker_flow.py`

## Search tab restore must persist completed results, not just the query

**Area:** `controller/pdf_controller.py`, `view/pdf_view.py`
**Symptom:** Switching away from a tab after a completed search could restore the query text but leave the result list empty when the tab was revisited.
**Cause:** The controller treated a finished-but-not-yet-cleaned-up worker like an in-flight search and cleared the active session state during tab changes.
**Fix:** Track whether the current search has actually finished. Only an active partial search gets cleared on cancel; a completed search keeps its accumulated hits and is restored from the per-session `search_state`.
**File:** `controller/pdf_controller.py`, `view/pdf_view.py`

## Print path must not double-stamp watermark overlays

**Area:** `model/tools/watermark_tool.py`, `controller/pdf_controller.py`, `src/printing/subprocess_runner.py`
**Symptom:** Watermark pages were eligible for both the controller-side print snapshot overlay path and the helper subprocess watermark stamping path, causing print output to be stamped twice.
**Cause:** `WatermarkTool.needs_page_overlay(...)` ignored the render purpose and treated print the same as on-screen/view rendering.
**Fix:** Return `False` for `purpose == "print"` so the helper subprocess remains the single stamping path for printed output. The subprocess runner heartbeat now also refreshes activity on every stdout chunk so heartbeat lines do not trip the stall watchdog.
**File:** `model/tools/watermark_tool.py`, `src/printing/subprocess_runner.py`

## OCR workers must read from a snapshot, not the live doc

**Area:** `controller/pdf_controller.py`, `model/tools/ocr_tool.py`
**Symptom:** OCR can race live document mutations or apply page_done spans to the wrong tab if the active session changes mid-run.
**Cause:** A background OCR worker that reads `model.doc` directly can outlive a session switch, and queued cross-thread signals posted before a cancel are still delivered afterward (same gotcha as the search worker).
**Fix:** Capture snapshot bytes on the GUI thread, pass them into `_OcrWorker`, let `OcrTool.ocr_pages(..., doc=...)` render from that override. Every worker signal carries a generation token — `cancel_ocr()` bumps `_ocr_gen` *before* `request_cancel()` so already-queued emissions are dropped by the handlers; `page_done` is additionally dropped unless the active session still matches `_ocr_session_id`.
**File:** `controller/pdf_controller.py`, `model/tools/ocr_tool.py`

## Cooperative OCR cancellation: per-page only
**Area:** controller/pdf_controller.py _OcrWorker
**Symptom:** Cancel appears to hang during a long page
**Cause:** request_cancel() is checked between pages, not inside a single fitz call
**Fix:** Accepted design. A slow page completes before cancel takes effect.
**File:** controller/pdf_controller.py:217-266 (`_OcrWorker`; `request_cancel` at 240, per-page check at 251-253)

## render_page_pixmap must reject page_num=0
**Area:** `model/tools/manager.py` (`ToolManager.render_page_pixmap`)
**Symptom:** Calling `render_page_pixmap(0)` silently renders `doc[-1]` (the last page) because Python negative indexing wraps around.
**Cause:** No bounds check on the 1-based page_num parameter.
**Fix:** Raise `ValueError` for `page_num < 1` or `page_num > len(doc)`.
**File:** `model/tools/manager.py`
**Tests:** `test_scripts/test_phase7_guard_hygiene.py`

## Wheel zoom must use effective (clamped) factor for the transform
**Area:** `view/pdf_view.py` (`_wheel_event`)
**Symptom:** At max zoom, scrolling up visually overshoots past 400%, then snaps back when the debounce re-renders at the clamped scale.
**Cause:** `self.scale` was clamped to `[MIN, MAX]` but the visual transform used the raw unclamped factor.
**Fix:** Compute `eff = clamped_scale / old_scale`; apply transform with `eff`; skip when 1.0 (at boundary).
**File:** `view/pdf_view.py`
**Tests:** `test_scripts/test_phase7_guard_hygiene.py`

## Object streams are natively supported by PyMuPDF
**Area:** `model/pdf_optimizer.py`
**Symptom:** The optimize dialog grayed out "使用物件串流" when pikepdf was absent, even though PyMuPDF supports `use_objstms=1` natively on both 1.25.5 and 1.27.1.
**Cause:** The original comment conflated objstms with linearization; both were gated on pikepdf.
**Fix:** `optimize_capabilities` returns `object_streams: True` unconditionally; `fast_save_kwargs` passes `use_objstms` from options; `requires_post_save_packaging` only gates on `linearize`.
**File:** `model/pdf_optimizer.py`
**Tests:** `test_scripts/test_phase7_guard_hygiene.py`, `test_scripts/test_pdf_optimize_workflow.py`

## Deskew Can Increase File Size

**Area:** `model/pdf_model.py` (`straighten_page`)
**Symptom:** After using `拉正頁面`, the saved PDF can become much larger than the original.
**Cause:** `PDFModel.straighten_page()` is designed for scanned or photographed pages. It renders the current page to a full-page RGB image, inserts that bitmap back into the document, and replaces the original page content. Compact vector text, PDF drawing operators, and reusable resources therefore become pixels. A larger output file is expected for this rasterizing implementation, especially on text/vector-heavy pages.
**Mitigation:** When file size matters, use `另存為最佳化的副本` after deskew and choose the `極致壓縮` preset.
**File:** `model/pdf_model.py`
**Tests:** `test_scripts/test_page_deskew.py`, `test_scripts/test_page_deskew_scope.py`, `test_scripts/test_theme_and_icons.py::test_straighten_action_warns_about_size_growth`

## Adaptive toolbar preset must use measured width, not window state
**Area:** `view/pdf_view.py` — `_update_toolbar_style`
**Symptom:** Toolbar shows icon-only on a wide restored window, or icon+text on a narrow maximized window (e.g. snapped to half-screen).
**Cause:** An earlier implementation keyed the ribbon preset off `isMaximized()` / `isFullScreen()` instead of actual available width. Window state does not correlate with space.
**Fix:** Measure the widest ribbon toolbar's `sizeHint().width()` once (cached in `_ribbon_text_min_width`), compare against `toolbar_tabs.width()` on every resize. Listen via `eventFilter` on `toolbar_tabs` (not `resizeEvent` on the main window) so child-only width changes are caught.
**File:** `view/pdf_view.py`

## Toolbar preset stale after fullscreen or theme change
**Area:** `view/pdf_view.py` — `_update_toolbar_style`, `exit_fullscreen_ui`, `apply_theme`
**Symptom:** After exiting fullscreen, the toolbar stays in icon-only mode even though the window is wide. Or after switching theme, buttons overflow because the cached width threshold no longer matches themed padding.
**Cause:** `_update_toolbar_style` skips work when `_toolbar_container` is hidden (correct), but the cached `_toolbar_last_preset` then blocks recomputation after the toolbar is re-shown. Theme QSS changes `QToolButton` padding, invalidating the pre-theme `sizeHint` measurement.
**Fix:** `exit_fullscreen_ui` clears `_toolbar_last_preset` and schedules a deferred `_update_toolbar_style` via `QTimer.singleShot(0, ...)`. `apply_theme` calls `_recompute_ribbon_text_min_width()` after setting the stylesheet.
**File:** `view/pdf_view.py`

## Qt QSS has no box-shadow or CSS transitions
**Area:** `view/theme.py`, `view/pdf_view.py`
**Symptom:** Attempting `box-shadow:` / `transition:` in `build_qss` does nothing (silently ignored), so "elevation" and "smooth state changes" never appear.
**Cause:** Qt Style Sheets implement a CSS *subset* — neither `box-shadow` nor `transition`/animation properties exist.
**Fix:** For real shadows use a `QGraphicsDropShadowEffect` in code (`PDFView._apply_chrome_shadow`), applied to a container that does **not** hold the heavy `QGraphicsView` (avoids render-path interaction). Re-apply only its `setColor(...)` on theme switch (the hue is theme-dependent); guard with `isinstance(..., QGraphicsDropShadowEffect)` so the effect is created once, not leaked per switch. For "smooth feedback", differentiate `:hover` / `:pressed` / `:focus` as distinct *static* states instead.
**File:** `view/pdf_view.py` (`_apply_chrome_shadow`), `view/theme.py` (`build_qss`)

## QColor() cannot parse `rgba(r,g,b,a)` float-alpha strings
**Area:** `view/theme.py` — `_parse_qcolor`
**Symptom:** Feeding an interaction/shadow token like `rgba(40,28,72,0.18)` straight into `QColor(str)` yields an **invalid** colour (`isValid() == False`), so the drop shadow renders as nothing.
**Cause:** `QColor`'s string constructor accepts `#rrggbb`, `#aarrggbb`, and named colours, but not the CSS `rgba(...)` functional form with a 0–1 float alpha (those tokens were authored for CSS in `colors.css`).
**Fix:** `_parse_qcolor` detects the `rgba(...)` form, splits the four components, and scales the float alpha to 0–255 (`int(round(a*255))`); hex/named values fall through to `QColor(str)`, with a final opaque-ish black fallback for unparseable input.
**File:** `view/theme.py`

## Focus rings must be colour-only to avoid layout shift
**Area:** `view/theme.py` — `build_qss`
**Symptom:** Adding a border on `:focus` to a control that has no base border makes the content jump by the border width each time it gains/loses focus.
**Cause:** A QSS border participates in box metrics; introducing it on `:focus` changes the widget's content rect.
**Fix:** Give the control a base `1px` border at rest and only **recolour** it to `accent` on `:focus` (inputs/combos/buttons already carry a 1px line border). Skipped focus rings on `QToolButton` (no base border) to avoid perturbing the measured ribbon width used by the adaptive toolbar.
**File:** `view/theme.py`

## Print dialog: programmatic combo restore must run AFTER signal wiring or overrides silently lose
**Area:** `src/printing/print_dialog.py` — `UnifiedPrintDialog.__init__` ordering vs `_resolve_hardware_values` (M3.2)
**Symptom:** Second print in the same process: restored duplex/color combos *display* the user's previous choice, but the submitted job uses the printer-driver preference instead — the UI lies. Also, a restored `scale_mode="custom"` left the percent spinbox disabled.
**Cause:** Hardware fields (duplex/color_mode) only win over driver preferences if they're in `_touched_hardware_fields`, which is populated by `_on_hardware_field_changed` — a slot connected in `_wire_signals()`. Restoring combo values *before* wiring means no touch-marking fires, so `_resolve_hardware_values()` falls back to the driver pref; likewise `_on_scale_mode_changed` (which enables the percent spin) never runs. `setCurrentIndex()` looks like state restoration but is really an event source — its side effects only exist if the listeners are already connected.
**Fix:** Call `_apply_previous_settings()` **after** `_wire_signals()`. Restoring then fires the same handlers as a human click: fields get marked touched, dependent enable-states update. Additional ordering constraint inside the restore: printer selection must be restored *first*, because `_on_printer_changed` clears `_touched_hardware_fields` and re-applies that printer's preferences — restoring any field before the printer switch gets wiped. Assert persistence tests against `_build_effective_options()`, not combo `currentData()` — the display can be right while the effective value is wrong.
**File:** `src/printing/print_dialog.py`
**Tests:** `test_scripts/test_m3_print_settings_persistence.py::TestPrintDialogSettingsPersistence::test_previous_settings_win_over_printer_preferences_in_effective_options`, `::test_previous_settings_restores_printer_selection_before_other_fields`

## unittest.mock.patch on PySide6 dialog methods → Windows fatal access violation
**Area:** `test_scripts/` — any test constructing a real Qt widget with `patch.object(SomeQDialogSubclass, "method")` active (M3.2)
**Symptom:** `Windows fatal exception: access violation` inside `__init__`/signal-connect during test collection or execution; pytest exits with code 5/9 and no Python traceback for the real cause.
**Cause:** `patch.object` replaces the method on the class with a `MagicMock`. PySide6's signal `.connect(self._method)` and internal C++ bookkeeping resolve bound methods through the class; handing them a MagicMock (not a real slot/callable bound to the QObject) corrupts the binding layer under the offscreen QPA.
**Fix:** Don't patch methods on Qt widget classes. Inject behavior the way the existing print-dialog tests do: hand the widget a plain-Python fake collaborator (e.g. `_FakeDispatcher` duck-typing `PrintDispatcher`) so no Qt-side method resolution is touched.
**File:** `test_scripts/test_m3_print_settings_persistence.py` (pattern), `test_scripts/test_print_dialog_properties_button.py` (original pattern source)

## Free-function extraction silently bypasses method monkeypatching
**Area:** model/pdf_text_edit.py, model/pdf_object_ops.py (god-module decomposition seams)
**Symptom:** After extracting a method `_foo` into a free function `_foo(model, ...)`, a test that does `monkeypatch.setattr(model, "_foo", ...)` and asserts the patch fired starts failing — the patch never intercepts.
**Cause:** The original inter-method call was `self._foo(...)` (a bound-method lookup that honours instance/class monkeypatching). A naive transform rewrites sibling calls to the *local* free function `_foo(model, ...)`, which resolves at module scope and never consults `model._foo` — so the monkeypatch is invisible. `test_edit_text_helpers.test_prepush_growth_branch_does_not_raise_name_error` patches `_push_down_overlapping_text` exactly this way.
**Fix:** Use a UNIFORM `self.` → `model.` transform (every inter-method call dispatches through the PDFModel delegating wrapper), and keep a wrapper on PDFModel for *every* moved method the test net pokes — not only the public verbs. Calls that were already bare module-level (e.g. `_classify_insert_path`, `_EditTextResolveResult(...)`) stay bare. Verify by grepping the test suite for `monkeypatch.setattr(... , "_<moved>"` and for `model._<moved>(` / direct `from model.pdf_model import _<moved>` before deciding move-vs-wrapper.
**File:** `model/pdf_text_edit.py` (wrappers in `model/pdf_model.py`)

## Helper-class extraction: getattr(self,…) and staticmethods escape the self.→self._view transform
**Area:** view/object_selection.py (R3.6 view seam); applies to any PDFView→manager extraction
**Symptom:** After moving methods into a `Manager(self._view)` helper, methods return wrong results (e.g. `_delete_selected_object` returns False) or `AttributeError: 'int' object has no attribute '_ensure_…'`.
**Cause:** A regex that rewrites `self.X → self._view.X` only matches *attribute* syntax. It misses (a) `getattr(self, "X")` / `setattr` / `hasattr` — the receiver `self` stays the manager but `X` lives on the view; and (b) a moved `@staticmethod` whose PDFView delegating wrapper, if generated as a normal `def f(self, …)`, breaks unbound `PDFView._f(arg)` calls (first positional arg binds to `self`).
**Fix:** (1) also rewrite `(get|set|has)attr(self,` → `…(self._view,` (verify none name a moved method first). (2) Make the wrapper for a moved staticmethod a `@staticmethod` delegating to `Manager._f(...)`. (3) Use a UNIFORM `self.→self._view.` transform (route inter-method calls through the PDFView wrappers too) so view-level `monkeypatch.setattr(PDFView, "_method"/instance, …)` in tests is honored — a direct `self._method` manager call silently bypasses it (same lesson as the R3.5 `_push_down_overlapping_text` monkeypatch).
**File:** `view/object_selection.py` (wrappers in `view/pdf_view.py`)

## Undo byte-budget must dedup by content, not id()
**Area:** model/edit_commands.py — `CommandManager._unique_byte_total` / `_dedup_top_snapshot_pair` / `_trim_undo_stack_if_needed`
**Symptom:** Undo history is evicted earlier than the 512 MiB budget should allow, even though the *distinct* snapshot bytes are well under budget — a correctness-looking "memory pressure" that silently shortens undo depth.
**Cause:** `_dedup_top_snapshot_pair` only aliases the **top two** commands' boundary bytes at push time. Byte-identical snapshots that are *non-adjacent* (e.g. a fresh `_capture_doc_snapshot()` that matches an earlier document state) remain distinct `bytes` objects. The budget accountant `_unique_byte_total` deduped by `id()`, so those distinct-but-identical objects were summed twice, inflating the figure past the cap and triggering eviction.
**Fix:** Dedup `_unique_byte_total` by **content** (`seen: set[bytes]`, membership-test the chunk itself). `bytes` are hashable and CPython caches the hash on the object, so it stays amortized-cheap even though `_trim_undo_stack_if_needed` recomputes the total inside its eviction `while` loop. Exact and leak-free — deliberately NOT a persistent `digest→bytes` intern map (that would keep evicted snapshots alive, since `bytes` aren't weak-referenceable). The hot-path adjacent aliasing in `_dedup_top_snapshot_pair` (real RAM sharing) is left intact.
**File:** `model/edit_commands.py`

## OCR invisible text changes doc.tobytes() without bumping render_revision
**Area:** controller/pdf_controller.py (`capture_worker_snapshot_bytes` cache) + controller/ocr_coordinator.py (`_on_ocr_page_done`)
**Symptom:** After the R4.2 worker snapshot-bytes cache landed, an OCR pass followed by a text search could miss the just-recognized text — the search worker received a snapshot serialized *before* OCR injected its text.
**Cause:** The snapshot cache keys on `(active_session_id, render_revision)`, reusing the page-render cache's invalidation token. That token is bumped (`_bump_render_revision` via `_invalidate_active_render_state`) only for mutations that change a *rendered page*. OCR's `apply_ocr_spans` inserts text with `render_mode=3` (invisible) — it changes `doc.tobytes()` (and therefore text extraction / searchability) but the rendered pixels are identical, so no render-revision bump occurs. The cache key never changes, so a stale pre-OCR snapshot is served on the next capture. `render_mode=3` appears ONLY in `apply_ocr_spans` (grep-verified), so OCR is the unique invisible-content mutation that affects a worker (search text-extraction).
**Fix:** `_on_ocr_page_done` calls `self._c._invalidate_worker_snapshot_cache()` immediately after `apply_ocr_spans`, dropping the cached bytes so the next capture re-serializes the post-OCR document. The render-visible mutation paths are already covered because `_bump_render_revision` also drops the cache. When adding any new doc mutation that is *render-invisible but worker-visible* (e.g. a future hidden-layer or metadata-driven search field), it must likewise invalidate the worker snapshot cache — keying on `render_revision` alone is not sufficient for such paths.
**File:** `controller/pdf_controller.py`, `controller/ocr_coordinator.py`

## Thumbnail threading: render off snapshot bytes, never the live doc — and watermarks vanish
**Area:** controller/thumbnail_coordinator.py (R4.3 hybrid async thumbnails)
**Symptom:** Two distinct hazards when moving thumbnail rasterization to a QThread: (1) a worker that renders `model.doc` directly races the GUI thread's mutations and hard-crashes (PyMuPDF documents are not thread-safe); (2) a worker that renders off `capture_worker_snapshot_bytes` produces thumbnails with NO watermarks on watermarked docs.
**Cause:** (1) `render_page_pixmap` reads the live `fitz.Document`. (2) Watermarks are *overlays* composed at render time via `apply_page_overlay` for `purpose in {"view","snapshot"}` — they are NOT baked into `doc.tobytes()`, so the snapshot bytes the worker opens have no watermark content. Annotations, by contrast, ARE in the bytes (rendered via `annots=True`), so they survive.
**Fix:** The worker opens its OWN `fitz` handle over the snapshot bytes (thread-safe, no live-doc access) AND the async path is taken only when the session has no view overlays — `_should_async` returns False when `controller.get_watermarks()` is non-empty, so watermarked sessions stay on the synchronous overlay-applying path. Keep the central `_safe_render_scale` clamp and `annots=True`/colorspace identical to the sync path so output is byte-identical.
**File:** `controller/thumbnail_coordinator.py`

## A test that builds a QPixmap needs the `qapp` fixture or it hangs
**Area:** test_scripts (any Qt-touching test that constructs QPixmap/QImage→QPixmap off a fixture)
**Symptom:** A pytest module passes its first N tests, then *hangs* (no crash, no failure) on the first test that calls `QPixmap.fromImage(...)` / `pixmap_to_qpixmap(...)`; in isolation that same test passes in <1s.
**Cause:** `QPixmap` requires a live `QGuiApplication`. Without the `qapp` fixture, the first QPixmap construction blocks on Windows. Tests that only build `QImage` (e.g. a worker's `pixmap_to_qimage`) or exercise pure logic don't need `qapp`, which is why the earlier tests pass and masks the missing fixture.
**Fix:** Add the `qapp` fixture parameter to every test that (even indirectly) constructs a `QPixmap`. For genuinely cross-thread render tests, prefer verifying the worker synchronously (`worker.run()` emitting `QImage`) plus deterministic GUI-marshalling tests — a live QThread render test reproduces the suite's known Qt/COM event-loop instability (passes alone, hangs interleaved).
**File:** `test_scripts/test_thumbnail_coordinator.py`

## Overlay raster caching: only watermarks are overlays, and the cache key must capture base content (R4.1 design-note)
**Area:** model/tools/manager.py (`render_page_pixmap` overlay branch), model/tools/watermark_tool.py, controller `_render_revision`/`_render_cache`
**Symptom:** A planned per-tool-revision overlay raster cache, keyed on `(session,page,scale,dpr,wm_revision,annot_revision)`, would (a) do nothing for annotations and (b) render stale text under a watermark after an edit.
**Cause:** Two wrong premises. (1) Only `WatermarkTool` overrides `needs_page_overlay` (true for `purpose="view"`); `AnnotationTool` uses the base default `False` — annotations are *baked* into the doc and rendered by `get_pixmap(annots=True)`, NOT composited as overlays, so an `annot_revision` counter is meaningless for the overlay path. (2) The overlay branch composites `insert_pdf(base page) → draw watermark → get_pixmap`, so the raster includes the page's text/objects; a key that tracks only watermark state is incomplete and serves stale composites when base content changes. The only *complete* "render changed" signal is the controller's whole-session `_render_revision` (bumped at the ~25 `_invalidate_active_render_state` sites); model-side counters (`edit_count`, `rebuild_page`) are incomplete (miss rotation/annotations/watermarks).
**Fix:** Deferred (R4.1). Any future overlay cache must key on a *complete* invalidation signal. Keying on `_render_revision` is correct but redundant with the existing `_render_cache` (no within-revision win). A real cross-edit win needs *per-page* content-revision tracking wired across all ~25 invalidation sites (high stale-render risk) or a separate-canvas composite (must replicate page rotation + MediaBox origin + session colorspace sRGB/gray/CMYK, with no watermark pixel-parity gate). Treat overlay-vs-baked and key-completeness as the first questions for any render-cache work.
**File:** `plans/refactor-R4-performance-deferrals.md` (R4.1 STATUS block)

## Optimize-copy of an encrypted PDF must re-apply the password, or it ships unprotected
**Area:** model/pdf_optimizer.py (`save_optimized_copy` / `reapply_source_encryption`, R5.5)
**Symptom:** 另存為最佳化的副本 of a password-protected PDF produced an output that opened with NO password — a silent loss of confidentiality on a persistent, user-kept file (not a temp).
**Cause:** For an encrypted (`needs_pass`) live doc, `_resolve_file_backed_optimize_source` returns None (the `needs_pass` gate), so the working doc is built from `model.doc.tobytes(...)`, which defaults to `encryption=NONE` (decrypted). The optimized working doc was then saved with no encryption.
**Fix:** After the optimized file is written (and after any pikepdf post-packaging, which would itself strip encryption), `reapply_source_encryption` reopens the output and re-saves with the session password captured at open (`model.password`; `owner_pw == user_pw` because only one password is retained), the live doc's permission bits (`int(doc.permissions)` — the signed value round-trips exactly through fitz `save(permissions=...)`), and a method parsed from `metadata['encryption']` (default AES-256, never weakening). Detection signal is `doc.needs_pass`: in PyMuPDF 1.27 it STAYS truthy after a successful `authenticate()` (it is `is_encrypted` that flips to False), so `needs_pass` is the reliable "file required a password" flag post-auth. Owner-password-only PDFs open with `needs_pass` False and are intentionally left as-is. The re-save is on a reopened handle of the *output file*, never `model.doc`, so the encryption AST guard does not flag it.
**File:** `model/pdf_optimizer.py`

## Print path wrote a fully decrypted PDF to disk; keep the temp encrypted + pass the password out-of-band
**Area:** controller/print_coordinator.py + src/printing/subprocess_runner.py + src/printing/helper_main.py (R5.1)
**Symptom:** Printing a password-protected PDF wrote a *fully decrypted* copy to `work_dir/input.pdf` (a real file in the temp dir) for the duration of the print job — an at-rest exposure of protected content.
**Cause:** `capture_worker_snapshot_bytes()` serializes with `PDF_ENCRYPT_NONE` (decrypted, by design — search/OCR consume the in-memory bytes), and the print worker wrote those bytes verbatim to disk.
**Fix (Option A):** The worker (`_encode_input_bytes`) re-encrypts the captured bytes with the session password (AES-256, `owner_pw==user_pw`) before the disk write, so the temp is never plaintext. The helper must then re-authenticate to rasterize, so the password is handed to it **out-of-band via the QProcess environment** (`PrintSubprocessRunner(helper_password=…)` → `PDF_EDITOR_PRINT_PASSWORD`), NOT via `job.json` — `job.json` lives in the same `work_dir`, so putting the password there would defeat the point (PDF + its password side-by-side at rest). `helper_main._build_snapshot_bytes(..., password=…)` authenticates the encrypted input in-memory; the decrypted print bytes never touch disk. Gotchas: (1) capture the password only when `model.doc.needs_pass` (owner-only/unencrypted docs have None); (2) keep the unencrypted no-watermark fast path returning the captured bytes verbatim (byte-identical) — only encrypted inputs change behavior; (3) all re-encrypt/auth `save`s are in `controller/`+`src/printing/`, outside `model/`, so the encryption AST guard is not involved; (4) a test that connects a Qt slot to capture the `prepared` job must hold a reference to the slot's owner or GC drops the signal silently.
**File:** `controller/print_coordinator.py`

## Building a wheel/sdist in `.venv`: setuptools is too old, and `pip wheel` litters build/ in the repo
**Area:** packaging / test_scripts/test_security_packaging.py (R5.4)
**Symptom:** (1) A direct `setuptools`/`build_meta` build in `.venv` ignores `[tool.setuptools.packages.find]` and fails on the PEP 621 `[project]` metadata. (2) `python -m build` errors ("No module named build.__main__"). (3) Running `pip wheel .` leaves a `build/` directory in the project root, dirtying the tree and (without a gitignore entry) breaking the no-jump clean-tree gate.
**Cause:** `.venv` ships setuptools 57.4.0 — older than the 61+ that reads `[project]` and `[tool.setuptools]` from pyproject.toml. The real `build` frontend isn't installed; a local `build/` artifact dir shadows the import. setuptools' wheel/bdist build writes intermediate output to `<cwd>/build/`.
**Fix:** Build with PEP 517 **isolation** (`pip wheel . --no-deps -w <tmp>`), which fetches a modern setuptools from PyPI (reachable here) into an ephemeral build env — ~5s, honors the config. Make the build test SKIP (not fail) on a non-zero rc / OSError so an offline runner degrades to the hermetic config guards (pyproject allow-list + MANIFEST prunes). Gitignore `build/` (alongside the already-ignored `dist/`/`*.egg-info/`) and `rmtree` it in the test so the suite leaves a clean tree. Note `scripts/` IS a package (`scripts/__init__.py`), so it genuinely leaks into the wheel under find-all discovery; `test_scripts/` is not (sdist-only, guarded by MANIFEST).
**File:** `.gitignore`, `test_scripts/test_security_packaging.py`

## `Path.write_text` on Windows rewrites LF→CRLF — don't use it to "revert" a tracked file
**Area:** tooling / any transient edit-then-restore of a source file on Windows
**Symptom:** After editing a file in Python and writing the original string back, an in-memory `read_text() == original` check passes, yet `git status` still shows the file modified.
**Cause:** `Path.write_text`/`open(mode="w")` use `newline=None`, which translates `\n` → `os.linesep` (`\r\n`) on write; `read_text` translates `\r\n` → `\n` on read. So a round-trip through write_text converts an LF-committed file to CRLF on disk while the normalized string compare hides it.
**Fix:** To restore a tracked file exactly, use `git checkout -- <file>` (or write bytes with `newline=""`). Never rely on a Python write_text round-trip to leave a file byte-identical for git.
**File:** (general — observed during the R5.4 teeth experiment)

## Characterization tests are green-by-construction — they need *teeth*, not a red-light
**Area:** testing / coverage-hardening (R6.1)
**Symptom:** A "characterization" test added over already-shipped behavior passes on first run, which superficially violates Red-Light-First (CLAUDE.md §5.1: "if a test passes before any implementation exists, the test is invalid").
**Cause:** Red-Light-First governs *new features* (write the failing test, then make it pass). A characterization test pins **existing** behavior, so it is green by definition — there is no implementation to write. The real risk is a vacuous assertion that would still pass if the behavior silently flipped (a no-op test), and — when written after an R3-style decomposition — a test that pins the **new** seam rather than the **old** contract, so it cannot catch a decomposition regression.
**Fix:** Give each characterization test teeth: assert a state change / side effect that a plausible regression would break, and prove it out-of-band. E.g. `get_print_watermarks` returns a JSON deep copy, not the shallow `get_watermarks` list — the isolation test was proven to have teeth by confirming the shallow path *does* leak a nested mutation (999 appended) while the deep path does not. For methods touched by a refactor, author the characterization test against pre-refactor behavior first and carry it through green.
**File:** `test_scripts/test_merge_composition.py`, `test_scripts/test_print_watermarks.py`, `test_scripts/test_worker_bridge_slots.py`, `test_scripts/test_text_selection_bounds.py`

## `verify_no_jump.py` full-suite `--ignore` lines go stale — re-audit on every gate change
**Area:** tooling / no-jump completion gate (R6.2)
**Symptom:** The gate's full-suite step (`_run_full_suite`) hard-`--ignore`s test files with a comment like "missing test fixtures / pre-existing failures", but the cited failures were fixed long ago — so the gate silently stops covering tests that now pass cleanly. A regression in an ignored file would never trip the gate.
**Cause:** An `--ignore` added to route around a *transient* breakage (a missing fixture, a since-fixed flake) is inert documentation once the breakage is resolved. Nothing forces a re-audit, so the ignore outlives its reason. R6.2 found three (`test_multi_tab_plan`, `test_ocr_e2e`, `test_render_colorspace`) that had passed/skipped cleanly under `.venv` (72 passed / 9 skipped) since well before the audit.
**Fix:** Before removing any gate ignore, run the named files directly under `.venv` and confirm they pass/skip. Only then delete the `--ignore` line(s) and leave a dated comment recording the re-audit result. Keep ignores that are *structurally* justified (the no-jump artifacts validated by a dedicated earlier step; genuinely timing-sensitive print runner/helper tests) — those are not stale. Re-audit the whole ignore list whenever the gate script itself changes.
**File:** `scripts/verify_no_jump.py` (`_run_full_suite`)

---

## Object-ops (move/rotate/delete) bypassed GC → unbounded growth + deleted-data recovery
**Area:** `model/pdf_object_ops.py` (R6-01; reopened R3.4)
**Symptom:** Repeated textbox move/rotate grew `doc.xref_length()` ~57× over 25 ops (super-linear, unbounded); a deleted textbox/image was recoverable byte-for-byte from the *saved* PDF.
**Cause:** The textbox move/rotate and textbox/app-image/native-image delete branches rewrite page content via redact-and-reinsert but never bumped `model.edit_count` / `model.pending_edits`, so `_maybe_garbage_collect`'s every-20-edits `garbage=4` orphan-xref round-trip never fired for object ops. Orphaned content streams accumulated, and because the normal save path uses `garbage=0` (`_save_doc` default), they persisted in saved files. (The earlier R3.4 closure looked only at `clean_contents()` compaction and wrongly concluded "slightly larger but byte-correct.")
**Fix:** `_register_mutation(model, page_idx, rect)` (mirrors the text-edit bookkeeping: append `pending_edits`, bump `edit_count`, call `_maybe_garbage_collect`) on textbox move/rotate; `_purge_deleted_content(...)` (immediate `garbage=4` round-trip) on every delete branch — deletes are destructive/security-sensitive so they don't wait for the batch threshold.
**File:** `model/pdf_object_ops.py`

---

## `delete_object` now replaces the live `fitz.Document` handle
**Area:** `model/pdf_object_ops.py` `_purge_deleted_content`; callers/tests
**Symptom:** Code that captured `page = model.doc[0]` (or held `model.doc`) before a delete then used it after crashed with `AttributeError: 'NoneType' object has no attribute 'get_page_images'` (a page from a closed document).
**Cause:** The immediate `garbage=4` purge calls `_roundtrip_live_doc`, which serializes + reopens the document and closes the old handle (same post-condition as the every-20-edits GC, but now on *every* delete). Pre-delete page/doc references become stale.
**Fix:** Always re-fetch `model.doc` / `model.doc[page_idx]` after any object delete. Never cache page handles across a mutation that can trigger GC.
**File:** `model/pdf_object_ops.py`, `test_scripts/test_image_objects_model.py`, `test_scripts/test_native_pdf_images_model.py`

---

## Delete confidentiality must fail closed, not swallow the GC error
**Area:** `model/pdf_object_ops.py` `_purge_deleted_content` (Codex F4)
**Symptom:** A first cut caught the round-trip exception and logged a warning (mirroring `_maybe_garbage_collect`), so `delete_object` returned `True` even when the orphan purge failed — claiming success while deleted content stayed recoverable.
**Cause:** The immediate purge *is* the confidentiality guarantee of a delete; swallowing its failure is unlike the batched GC (where a failure only defers compaction).
**Fix:** Let the round-trip exception propagate from `_purge_deleted_content` so the delete surfaces as a failed operation. The batched `_maybe_garbage_collect` may still swallow (non-destructive), but destructive deletes must not.
**File:** `model/pdf_object_ops.py`

---

## Optimize-copy must bind to its source session, not live `model.doc`
**Area:** `model/pdf_optimizer.py`, `controller/pdf_controller.py` (R5-03; Codex F1/F2)
**Symptom:** A background optimize could read whichever tab was active when the worker ran, mixing document A's optimize request with document B's bytes/encryption if the user (or a single-instance `open_pdf` via `QTimer`) switched tabs mid-run.
**Cause:** `save_optimized_copy` captured `active_sid` on the *worker* thread, and `build_working_doc_for_optimized_copy` / size / source-resolve helpers read the active `model.doc` property rather than the requested session's document.
**Fix:** Capture the session id at *dispatch* (`OptimizePdfCopyRequest.session_id`), thread it through the worker to `save_optimized_copy(session_id=...)`, and resolve every document read via `_session_doc(model, session_id)` (`model._sessions_by_id[sid].doc`). Capture the `EncryptionDescriptor` up front, before any background work.
**File:** `model/pdf_optimizer.py`, `controller/pdf_controller.py`

---

## Re-encryption must preserve the auth role and never publish plaintext at the output
**Area:** `model/pdf_optimizer.py` `reapply_source_encryption` / `save_optimized_copy` (R5-02, R5-04)
**Symptom:** (R5-02) A source opened with a restricted *user* password produced an optimized copy where that same password authenticated as *owner* (`owner_pw == user_pw`), silently dropping the permission mask; an owner-only/blank-user encrypted source became fully unprotected. (R5-04) On a re-encryption/`os.replace` failure, the plaintext optimized file was left at the requested output path (it had already been `shutil.move`d there before encryption).
**Cause:** One captured credential was reused as both owner and user password; the pipeline moved plaintext to `new_path` and *then* encrypted in place, with cleanup that only checked the already-moved temp.
**Fix:** Track `DocumentSession.auth_level` (2/4/6/None). In `reapply_source_encryption`: user-auth keeps the credential as `user_pw` + a random `owner_pw` (no promotion); owner/both retain the credential; owner-only blank-user sources (detected via encryption metadata, not just `needs_pass`) re-lock with a random `owner_pw` + blank `user_pw` + the restricted permissions. In `save_optimized_copy`: write plaintext to a temp, encrypt into a *destination-sibling* staging file, then atomic `os.replace` only on success; clean every staging path in `finally`. `new_path` never holds transient plaintext for an encrypted source.
**File:** `model/pdf_optimizer.py`, `model/pdf_model.py`

---

## PyMuPDF `Document.save()`/`tobytes()` default to `garbage=0` — orphans persist on disk
**Area:** `model/pdf_model.py` save path; relevant to any redaction/delete
**Symptom:** Content removed by `apply_redactions` (or a redact-and-reinsert edit) is still recoverable from a saved file — the redaction rewrites the *current* content stream but the pre-redaction stream remains as an orphan xref.
**Cause:** `_save_doc` / `_full_save_to_path` / `save_as` use the PyMuPDF default `garbage=0`, which does not prune unreferenced objects. Only `garbage>=1` (full pruning at `garbage=4`) reclaims orphans.
**Fix:** For security-sensitive deletions, reclaim orphans *before* the user can save (immediate `garbage=4` round-trip, see `_purge_deleted_content`). Do not assume the save step will scrub them — it won't at the default garbage level. (Raising the save garbage level globally is a larger, separate change with incremental-save implications.)
**File:** `model/pdf_object_ops.py`, `model/pdf_model.py`

---

## Async thumbnail identity must include a global token, session, and generation
**Area:** `controller/thumbnail_coordinator.py`, `controller/pdf_controller.py` (R4-01…R4-04; M3.6 foreground priority)
**Symptom:** An earlier async thumbnail worker could paint a cancelled tab's queued batch into the newly active tab, retain decrypted snapshot bytes after close, or leave the old worker running when a live fallback was selected. On complex-vector documents, a full-document thumbnail worker could also starve the foreground page render for tens of seconds.
**Cause:** Per-session generations can collide across tabs; mutable coordinator session state is not immutable job identity; and background raster work needs an explicit foreground-priority contract rather than merely living on another thread.
**Fix:** Every request/result carries a globally unique token plus session and generation. Clean documents use a verified file-backed worker; dirty/watermarked documents use a one-page-per-event-turn live fallback. Cancellation happens before replacement strategy selection, tab close clears matching decrypted cache bytes, and visible-page rendering cancels/restarts thumbnail work only after foreground visible/prefetch candidates drain.
**File:** `controller/thumbnail_coordinator.py`, `controller/pdf_controller.py`

---

## Completed print runner retained its password until the view was destroyed (R5-05)
**Area:** `src/printing/subprocess_runner.py`
**Symptom:** Each `PrintSubprocessRunner` stored `_helper_password` and was parented to the long-lived view; completion dropped the coordinator's refs but Qt parent ownership kept the runner (and its credential) alive — `view.children()` accumulated `['secret-0', 'secret-1', ...]`.
**Cause:** `_cleanup()` neither cleared the password nor scheduled the runner for deletion.
**Fix:** Clear `self._helper_password = None` immediately after `self._process.start()` (QProcess already inherited the env) and again in `_cleanup()`, then `self.deleteLater()`. Test note: `deleteLater` posts a `DeferredDelete` event that a plain `processEvents()` does not deliver — drain it with `app.sendPostedEvents(None, QEvent.Type.DeferredDelete)`.
**File:** `src/printing/subprocess_runner.py`

---

## Packaging guard accepted a find-all `*` discovery pattern (R5-06)
**Area:** `test_scripts/test_security_packaging.py`
**Symptom:** The allow-list guard stripped trailing `*`/`.` and checked the remaining prefix, so a discovery list like `['controller*', '*']` passed — `'*'` stripped to `''`, which does not start with any forbidden prefix — even though setuptools would then discover `scripts`.
**Cause:** Prefix-string matching cannot model setuptools' fnmatch-glob discovery semantics; a find-all reduces to the empty string and slips through.
**Fix:** Evaluate each include pattern with `fnmatch` against concrete forbidden package names (`scripts`, `scripts.fusion_schemas`, `test_scripts`, `docs`, `plans`) and reject any pattern that strips to empty (`*`/`**`). Keep a teeth test asserting the validator flags `*`/`scripts*`.
**File:** `test_scripts/test_security_packaging.py`

---

## Windows pip-audit crashes on non-ASCII bytes in requirement files
**Area:** CI (`dependency-audit` job) / requirement files
**Symptom:** The windows-latest pip-audit leg fails in seconds with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x81` while *parsing* `optional-requirements.txt`; the ubuntu leg stays green. Main was red this way from 2026-06-14 to 2026-07-03 without anyone noticing the cause.
**Cause:** pip-audit's `pip_requirements_parser.auto_decode` (like pip's own) falls back to the locale codepage when a requirements file has no BOM. GitHub Windows runners use cp1252, and several bytes inside UTF-8 CJK sequences (e.g. `0x81`) are undefined in cp1252, so a Traditional-Chinese comment crashes the parse outright. Linux never reproduces it (UTF-8 locale).
**Fix:** Keep every `*requirements*.txt` / `constraints*.txt` at the repo root pure ASCII. Guarded by `test_scripts/test_security_requirements_encoding.py`, which runs in the blocking CI security suite on every PR.
**File:** `optional-requirements.txt`, `test_scripts/test_security_requirements_encoding.py`

---

## Orphaned print-helper processes poison later full-suite runs
**Area:** `test_scripts/` print stack / local dev machine state
**Symptom:** A full-suite run intermittently fails a print test on a status-bar-restore assertion (`test_print_controller_flow.py::test_stalled_print_helper_can_be_terminated_without_closing_main_window`) or hard-segfaults with Windows fatal exception `0x80040155` (REGDB_E_CLASSNOTREG) inside `raster_print_pdf` during `test_print_speed.py` — while the same files pass in isolation and the diff under test touches nothing related.
**Cause:** A suite run that crashes or is killed mid-way can leave print-helper `python` subprocesses alive. They keep the Windows print/COM stack engaged, and later runs race against them (stalled-status leakage, COM registration errors).
**Fix:** Before judging a red suite run, check for orphaned `python` processes (`Get-Process | Where-Object { $_.ProcessName -match 'python' }`), kill them, and rerun. Two consecutive clean runs after the kill confirmed the suite itself was green.
**File:** procedural (no code change); observed 2026-07-04 while validating the PR-4 E402 cleanup

---

## Subprocess text I/O silently depends on the caller's locale, not the child's

**Area:** `test_scripts/` — any test that `subprocess.run(...)` a script/tool and reads its stdout/stderr
**Symptom:** Two distinct failure shapes from the same root cause, seen while triaging PR-10's advisory `test-functional` data:
  1. `test_performance_script_runner.py::test_performance_script_runs_from_repo_root` failed on windows-latest CI (never on ubuntu) with the *child* process (`test_performance.py`) raising `UnicodeEncodeError: 'charmap' codec can't encode characters ... Phase 6 效能測試` — the child's own `print()` of zh-TW status text crashed before the parent ever read anything.
  2. `test_security_packaging.py::test_built_wheel_and_sdist_exclude_dev_trees` has a known local flake: `subprocess.run(..., text=True)` decodes the child's pipes using `locale.getpreferredencoding()`, which is `cp950` (Traditional Chinese Big5) on the maintainer's machine — a `UnicodeDecodeError` there if the build tool's own output isn't Big5-representable.
**Cause:** Neither the parent's `subprocess.run` call nor the child process pin an explicit encoding. On Windows, a captured (non-tty) child stdout falls back to the *process* locale codepage (cp1252 on GitHub's windows-latest runners) for the child's own `print()`/`sys.stdout` calls unless `PYTHONIOENCODING`/`PYTHONUTF8` is set in its `env`; separately, the *parent's* `text=True` decode of the captured bytes uses `locale.getpreferredencoding()` on whichever machine runs the test, not a fixed encoding. This is the same encoding-class bug as the `optional-requirements.txt` cp1252 pitfall above, just at the subprocess-I/O layer instead of the file-parsing layer.
**Fix:** Pin encodings explicitly on both sides of any `subprocess.run` a test spawns: pass `env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}` so the *child's* own text output can't hit an undefined-codepage crash, and read captured output with an explicit `encoding="utf-8", errors="replace"` (or manually `.decode("utf-8", errors="replace")` on `bytes` output) rather than bare `text=True`, so the *parent's* decode doesn't depend on whatever locale happens to be active on the machine running the test.
**File:** `test_scripts/test_performance_script_runner.py`, `test_scripts/test_security_packaging.py`

---

## CI's `test-functional` job never installed `build`/`setuptools`/`wheel`

**Area:** `.github/workflows/ci.yml` (`test-functional` job) / `test_scripts/test_security_packaging.py`
**Symptom:** `test_built_wheel_and_sdist_exclude_dev_trees` failed on every sampled `test-functional` CI run (both windows-latest and ubuntu-latest) with `AssertionError: distribution build failed (rc=1): ... No module named build` — easy to misdiagnose as an encoding bug (see previous entry) because the CI traceback's outer assertion message shape looks similar, but the actual `stderr` payload is just a missing-module error, not a decode crash.
**Cause:** `build`/`setuptools`/`wheel` are declared in `pyproject.toml`'s `dev` optional-dependency extra, which only gets installed locally via `pip install -e ".[dev]"`. The `test-functional` CI step installs `requirements.txt` + `optional-requirements.txt` + `pytest packaging` — never the `dev` extra — so `python -m build` (which this test invokes as a subprocess) doesn't exist in that job's environment at all.
**Fix:** Install `build`/`setuptools`/`wheel` explicitly in the `test-functional` step, version-pinned inline to match the maintainer's `.venv` (`build==1.5.0`, `setuptools==82.0.1`, `wheel==0.47.0`) rather than adding them to `constraints-ci.txt` (that file only binds packages installed by other steps' `-c` flags; adding entries there wouldn't install anything).
**File:** `.github/workflows/ci.yml`

---

## `apply_redactions` is geometric: it destroys text and line art, not just the targeted image

**Area:** `model/pdf_object_ops.py` (object delete/move/rotate), any PyMuPDF redaction call
**Symptom:** Deleting one app-inserted image silently destroyed *other* content that merely overlapped its rectangle. Measured on PyMuPDF 1.27.1 with a 320×240 page, image at `(40,40,110,110)`:
  - an overlapping neighbour image at `(10,10,80,80)` vanished entirely (2 invocations → 0);
  - text drawn under the image, `"UNDER THE IMAGE"`, came back from `page.get_text()` as `"AGE"` — *partial glyph removal*, so the corruption is not even visible as a whole missing word;
  - a `draw_line` crossing the rect disappeared (2 drawings → 1).
**Cause:** `page.add_redact_annot(rect)` + `page.apply_redactions(...)` is defined on **geometry**, not on object identity. It removes every image *touching* the rect (`images=PDF_REDACT_IMAGE_REMOVE`), every glyph whose box intersects it, and — via the `graphics` parameter's default — line art the rect touches. Passing `images=PDF_REDACT_IMAGE_REMOVE` to delete "the image at this rect" reads like an identity operation but is not one. The object-identity layer (`NativeImageInvocation`) exists precisely because a rectangle does not identify an object.
**Fix:** Never use redaction to delete an identified object. Resolve the object to its content-stream invocation (`_resolve_marker_image_invocation`, digest-verified and xref-drift tolerant) and excise just that `q … cm … /Name Do … Q` token range (`_remove_native_image_invocation`), which also prunes `Resources/XObject/<name>` only when no remaining content stream still names it. If the invocation cannot be resolved uniquely, **fail safe** (return `False`, a no-op) rather than falling back to redaction — the fallback is the data-loss vector. Redaction remains correct only where the intent really is geometric (`_redact_and_restore_textbox_region`, which re-inserts the annots it must preserve).

Corollary for shared xrefs: two images with identical bytes dedupe to **one** image xref under **two** XObject names (`fzImg0`, `fzImg1`) in two content streams. Removing one placement must prune only its own name; the xref stays alive while the other name references it, and is reclaimed by the deferred `garbage=4` save that `secure_save_required` forces.
**File:** `model/pdf_object_ops.py` (`_delete_object_impl` image branch); design + measurements in `plans/b1-delete-app-image-invocation-removal.md`; regressions in `test_scripts/test_image_objects_model.py`, `test_scripts/test_pdf_object_ops_transactional.py`

---

## Pruning an XObject resource: `/fzImg1` is a prefix of `/fzImg10`, and `/Resources` is inheritable

**Area:** `model/pdf_object_ops.py` (`_remove_native_image_invocation`)
**Symptom:** Two independent failures when removing an image's content-stream invocation, both in the "is this XObject name still used?" retention check. Found by adversarial review of the B1 change, then reproduced:
  1. **Prefix collision.** With 11+ images on a page PyMuPDF names them `fzImg0 … fzImg10`. Deleting `fzImg1` left its `/Resources/XObject` entry behind — `page.get_images()` stayed at 12 — because the check was a raw substring test, `b"/fzImg1" in stream`, which the token `/fzImg10` in a *neighbour's* stream satisfies. (`garbage=4` at save still reclaims it, so R6-01 held; the live document was simply wrong.)
  2. **Inherited `/Resources`.** On a page with no `/Resources` of its own (spec-legal, PDF 1.7 §7.7.3.4 Table 30 — the key is inheritable through `/Parent`), `doc.xref_set_key(page.xref, "Resources/XObject/fzImg0", "null")` **fabricated** a direct `/Resources <</XObject<</fzImg0 null>>>>` on the page. `xref_set_key` creates every missing link in the path. That dict then *shadows* the inherited one, so the page's `/Font` and other XObjects no longer resolve through it. Measured: the page gained `<</XObject<</fzImg0 null>>>>` where it previously had nothing, and the real entry — which `insert_image` had registered in the *ancestor* dict — was never removed.
**Cause:** (1) PDF name tokens are delimited (§7.2.2, Tables 1-2); a substring test ignores the terminator. (2) `insert_image` uses `pdf_dict_get_inheritable`, so it registers the XObject wherever `/Resources` actually resolves — possibly an ancestor `/Pages` node — while the removal code assumed `page.xref` always owns it.
**Fix:** Match the name as a whole token (`/name` followed by a delimiter or end-of-stream) via `_stream_references_xobject`. Resolve the owning dict with `_resolve_xobject_resource_owner`: the page's own `/Resources` if it has one containing the name, else walk `/Parent` until the key is found; give up (prune nothing) rather than write a shadowing dict. When the owner is an inherited dict, sibling pages share it, so the still-referenced scan must cover **every** page's content streams, not just this page's.
**File:** `model/pdf_object_ops.py`; regressions `test_delete_app_image_prunes_prefix_colliding_resource_name`, `test_delete_app_image_does_not_shadow_inherited_resources` in `test_scripts/test_image_objects_model.py`

---

## A "fail safe" that refuses to act can strand the object it was protecting

**Area:** `model/pdf_object_ops.py` (`_delete_object_impl` image branch), and any resolve-then-act path
**Symptom:** Converting delete from geometric redaction to identity-based invocation removal introduced a fail-safe: if the marker cannot be resolved to a content-stream invocation, return `False` and change nothing. That is correct when the resolution is *ambiguous*. It is wrong when there is **no candidate at all** — the image was already removed by an external editor and only our hidden marker annot survived. The marker then stays hit-detectable (hit-testing reads the annot payload and never checks for an invocation), still reports `supports_delete=True`, and no verb touches it: move and rotate already failed on that population, so delete was the last one that worked. The user gets selection handles on an object that silently refuses to die.
**Cause:** `_find_app_image_invocation` returns `None` for both "zero candidates" and "more than one candidate", so a single `is None` check collapses two failures that want opposite handling.
**Fix:** Distinguish them. `_app_image_invocation_candidates()` computes a deliberate *superset* of what the resolver will accept; `≥1` → ambiguous, fail safe (deleting the marker alone would orphan visible pixels); `0` → orphaned, delete the marker and register the mutation. The general lesson: before shipping a fail-safe, ask what the object looks like *after* the safe path runs, and whether any verb can still reach it.

Two adjacent fixes from the same review: `int(payload.get("xref", 0) or 0)` raised `ValueError` on a corrupt or third-party payload (`"xref": "abc"`) straight through `delete_objects_atomic`'s re-raise into an uncaught Qt slot — all four parse sites now go through `_marker_xref()`, which degrades to `0`, exactly the value the geometric+digest fallback wants. And the `if not xref: return False` guard was strictly *stronger* than the resolver it gated (`_find_app_image_invocation` handles `xref == 0` fine and `_resolve_marker_image_invocation` backfills the payload), so it foreclosed deletes that would have succeeded.
**File:** `model/pdf_object_ops.py`; tests `test_delete_orphaned_app_image_marker_cleans_up_the_marker`, `test_delete_app_image_with_corrupt_xref_payload_does_not_raise`, `test_delete_app_image_without_xref_in_payload_still_resolves`

---

## Rolling back a transaction that changed nothing closes the live `fitz.Document`

**Area:** `model/pdf_object_ops.py` (`delete_objects_atomic`), `model/pdf_model.py` (`_restore_doc_from_snapshot`)
**Symptom:** A delete that failed *before touching the document* (resolution returned `None`) still ran the snapshot rollback. `_restore_doc_from_snapshot` closes `model.doc` and reopens it from bytes, so a pure no-op swapped the live handle: `model.doc` became a nameless `Document('pdf', <memory>)` and the previous handle was closed. Any cached `fitz.Page` now raises (the stale-handle class documented above), and the reopened document's empty `doc.name` silently degrades the next save from incremental to full.
**Cause:** `delete_objects_atomic` treated "returned `False`" as "may have mutated". Before the B1 conversion this was practically unreachable for app-images — a marker just found by hit-detection was always found again inside delete — so the cost never showed up.
**Fix:** Make the rollback conditional on an actual mutation. Every mutating path bumps `model.edit_count`, so comparing it against the transaction's opening value witnesses a mutation by the failing request *or* by any earlier one in the batch. Guard the optimisation with a test that drives a batch whose first delete mutates and whose second fails, and asserts the render digest is restored — otherwise a "skip the rollback" optimisation will eventually skip one that was needed. Controllers should still invalidate render state on the failure path, because a *genuine* partial rollback does reopen the document.
**File:** `model/pdf_object_ops.py`, `controller/pdf_controller.py`; tests `test_failed_delete_without_mutation_keeps_the_live_document_handle`, `test_failed_batch_delete_after_a_successful_one_still_rolls_back`

---

## The print path wrote two plaintext temps, and `capture_print_snapshot_bytes` is always decrypted

**Area:** `controller/print_coordinator.py`, `src/printing/*` (R5-01)
**Symptom:** Every print job left a fully decrypted copy of the document on disk — twice. `work_dir/input.pdf` (written by the submission worker) and a `NamedTemporaryFile` (written by `PrintDispatcher.print_pdf_bytes` for the driver call). Both were deleted afterwards, but the content was recoverable from the filesystem and, on Windows, from the NTFS journal.
**Cause:** `PDFModel.capture_print_snapshot_bytes` returns `doc.tobytes(..., encryption=fitz.PDF_ENCRYPT_NONE)` on **both** branches, so the print pipeline is holding plaintext from the moment the user clicks Print — including for password-protected sources. R5.1 had patched only the *encrypted-source* case by re-encrypting `input.pdf`, which then forced the session password into the helper subprocess's environment so it could authenticate. Unprotected sources still wrote plaintext, and the dispatcher's temp was plaintext in every case.
**Fix:** Never materialise the document. Stream it to the helper's **stdin** (chunked, with `bytesWritten` flow control so peak buffer is one chunk, not one document — `QProcess.write()` never blocks, so the classic pipe-buffer deadlock does not apply; the cost is memory). Widen `PDFRenderer` / `raster_print_pdf` to accept `str | bytes` and add `PrinterDriver.print_pdf_from_bytes` (default: scoped temp + `print_pdf`, so unmodified drivers still work; `WindowsPrinterDriver` overrides it and never touches disk). Deleting the file also deletes the reason the password had to travel: the piped bytes are already plaintext, so drop the re-encryption *and* the `PDF_EDITOR_PRINT_PASSWORD` env var from the production path.

**Residual (accepted, Linux/macOS only):** the CUPS/lp *direct-PDF* route needs a real file — `conn.printFile` and `lp` pass the path to a filter chain that must parse and rasterise it. That temp **cannot** be re-encrypted, as the original design proposed: the consumer requires plaintext, so encrypting it would break printing rather than harden it. It is instead created inside `LinuxPrinterDriver` (not the dispatcher), so it lives only across the submission call, is `0600` via `NamedTemporaryFile`, and is unlinked in a `finally`.
**File:** `src/printing/dispatcher.py`, `src/printing/base_driver.py`, `src/printing/pdf_renderer.py`, `src/printing/qt_bridge.py`, `src/printing/platforms/*.py`, `src/printing/helper_main.py`, `src/printing/helper_protocol.py`, `src/printing/subprocess_runner.py`, `controller/print_coordinator.py`; design `plans/r5-01-fileless-print.md` §11

---

## A QThread worker can clear its own decrypted payload race-free — no join needed

**Area:** `controller/search_coordinator.py`, `controller/ocr_coordinator.py` (Codex F6 / B3)
**Symptom:** `cancel_ocr` / `_cancel_search` are non-blocking: they bump a generation token, set the worker's cancel flag, and return. The worker's `_doc_bytes` — a decrypted snapshot — then stayed reachable not just until the loop's next checkpoint but until Qt processed the pending `deleteLater()`, i.e. an unbounded time after the tab closed.
**Cause:** The payload was treated as immutable worker state, and the obvious fix (have the GUI thread null it) looks racy, so the item sat deferred as "revisit only if a worker can be made to clear its payload race-free."
**Fix:** The worker clears it **itself, on its own thread**. `request_cancel()` only flips a bool; the worker thread is the sole writer of `_doc_bytes`, so no synchronisation is required and the non-blocking cancel is untouched. `_SearchWorker` can drop the reference immediately after `fitz.open("pdf", data)` — PyMuPDF retains its own reference to the buffer, so the `Document` remains fully usable (verify with `sys.getrefcount`, not a weakref: `bytes` is variable-size and cannot be weak-referenced even via a subclass). `_OcrWorker` needs the bytes each iteration, so it clears in `run()`'s `finally`.

Two testing gotchas found here: pytest's assertion rewriting keeps its own temporaries alive in the frame, so `sys.getrefcount` deltas are unreliable *inside a test* — assert on `vars(worker)` instead; and `_SearchWorker.run()` had a latent `finally: doc.close()` that raised `AttributeError` whenever `doc_bytes` was empty and `doc` was therefore `None`.
**File:** `controller/search_coordinator.py`, `controller/ocr_coordinator.py`; tests `test_scripts/test_worker_doc_bytes_lifetime.py`

---

## XObject identity requires both the resource binding and the placement

**Area:** `model/pdf_object_ops.py` app-image resolution and resource pruning
**Symptom:** A stale marker for one of two identical, shared-xref images deleted the surviving placement. Separately, a page with its own unrelated `/fzImg0` prevented an inherited `/fzImg0` from being pruned, so deleted pixels survived `garbage=4`.
**Cause:** Xref/digest identifies image bytes, not a particular placement, while an XObject name identifies a binding only inside its effective resource dictionary. Treating either value as globally unique conflates independent placements or pages.
**Fix:** Require marker geometry and rotation even on the xref/digest fast path. For pruning, resolve each page's effective `(resource owner, name -> image xref)` binding and scan only pages bound to the target; stop at the first `/Resources` dictionary because that key is inherited as a whole.
**File:** `model/pdf_object_ops.py`; tests `test_delete_stale_shared_xref_marker_preserves_surviving_placement`, `test_delete_inherited_image_ignores_same_name_in_unrelated_page_resources`

---

## `QProcess.FailedToStart` has no matching `finished` signal

**Area:** `src/printing/subprocess_runner.py`
**Symptom:** If the print helper executable could not start, the runner emitted a failure but remained active forever, retained the fileless plaintext payload and work directory, and caused normal application close to be rejected.
**Cause:** Qt emits `errorOccurred(FailedToStart)` and transitions to `NotRunning`, but does not subsequently emit `finished`; cleanup existed only in the latter handler.
**Fix:** Route `FailedToStart` through the same idempotent terminal lifecycle as `_on_finished`, clearing the payload/process/work directory and emitting the runner's `finished` signal exactly once.
**File:** `src/printing/subprocess_runner.py`; test `test_runner_failed_to_start_releases_fileless_payload_and_finishes`

---

## PDF font identity must be keyed per-xref, never per-basefont

**Area:** font handling for the text-commit engine design (`plans/2026-07-14-acrobat-parity-text-commit-engine.md`); any code matching spans to fonts
**Symptom:** A glyph-coverage audit reported the document's *own* characters as missing from the document's *own* subset font — false "missing glyph" results.
**Cause:** One document can carry multiple distinct subset instances sharing a single basefont name (observed: four different `LAAAAA+Consolas` xrefs with disjoint glyph sets). Matching spans to fonts by (subset-stripped) basefont name conflates the instances, so coverage/metric checks run against the wrong font object.
**Fix:** Track font identity by xref end-to-end (`page.get_fonts(full=True)` xref → `doc.extract_font(xref)` → `fitz.Font(fontbuffer=...)`); use span→xref mapping (texttrace/text-state replay), never name equality.
**File:** design record in `plans/2026-07-14-acrobat-parity-text-commit-engine.md` §3; audit script (scratchpad `font_roundtrip_audit.py`, to be productized as `scripts/audit_tier_coverage.py`)

---

## Render-quality benchmark must use the profile-scoped quality map

**Area:** `test_scripts/benchmark_ui_open_render.py`, controller render state
**Symptom:** The UI open/render benchmark timed out waiting for a quality that had already been rendered.
**Cause:** `_page_render_quality_by_session` changed from a flat page map to `{session_id: {color_profile: {page_idx: quality}}}`, but the benchmark continued to look up `page_idx` directly under the session.
**Fix:** Read quality through `PDFController._page_quality_map(session_id)`, which selects the active profile, instead of reaching into `_page_render_quality_by_session` directly. Cover the benchmark helper with a profile-scoped regression test.
**File:** `test_scripts/benchmark_ui_open_render.py`; test `test_wait_for_quality_reads_active_color_profile_map`

---

## A quality flag is not observable until the render callback yields

**Area:** `controller/pdf_controller.py`, `controller/page_render_coordinator.py`, complex-vector continuous rendering
**Symptom:** The requested page's high-quality raster completed in about 0.4 seconds, yet the UI benchmark reported 9–80 seconds before that quality became ready and close/tab-switch input stalled.
**Cause:** `_process_visible_render_batch()` marked the requested page high, then synchronously rendered another low-quality prefetch page in the same GUI callback. One neighboring complex page took 8.3 seconds. Concurrent full-document thumbnail work amplified the delay to 78–80 seconds. Qt could not process the benchmark/input event that observed the already-written quality map until the callback returned.
**Fix:** Keep only the explicitly requested low first paint synchronous. Dispatch high-quality and non-immediate low/prefetch rasters through a one-worker `PageRenderCoordinator`, process one fallback render per event-loop turn, and pause/resume thumbnail work around foreground candidates. Measure stage timings separately from event-loop-observed readiness; a fast `get_pixmap()` does not prove responsive scheduling.
**File:** `controller/page_render_coordinator.py`, `controller/pdf_controller.py`, `plans/archive/2026-07-16-m3-render-offload.md`

---

## A growing thumbnail icon box does not upscale its source pixmap

**Area:** thumbnail rendering and layout (`controller/thumbnail_coordinator.py`, `model/pdf_model.py`, `view/pdf_view.py`)
**Symptom:** The sidebar's icon/grid dimensions grew as the splitter widened, but each rendered page image stayed about 120 px wide and appeared surrounded by excessive blank space.
**Cause:** Both thumbnail render paths used a fixed MuPDF scale of `0.2`. `QIcon.actualSize()` can downscale a larger source, but it does not invent higher-resolution pixels to fill a larger icon box; the item also lacked a full-grid size hint.
**Fix:** Render both clean-file and live-session thumbnails near the UI's maximum icon width, let QIcon downscale for narrow sidebars, and set each item's size hint/alignment to the computed grid cell.
**File:** `utils/render_limits.py::thumbnail_render_scale`, `controller/thumbnail_coordinator.py`, `model/pdf_model.py::get_thumbnail`, `view/pdf_view.py::_update_thumbnail_layout_metrics`

---

## Editable combo validation must distinguish draft text from committed values

**Area:** `view/pdf_view.py`, `view/text_editing.py` — font-size control
**Symptom:** Typing a font size could resize the inline editor on every partial keystroke; standard `QDoubleValidator` behavior also blocked `-2`, `1000`, or the second decimal digit before commit, so an attempted invalid value could silently become a different valid value instead of restoring the last valid size.
**Cause:** Editable `QComboBox.currentTextChanged` fires while the user is still composing text. A normal validator rejects some invalid keystrokes and does not emit `editingFinished` for intermediate input, which makes commit-time restoration unreliable.
**Fix:** Treat numeric-shaped text as a draft, gate live preview while the line edit is dirty, catch Return/focus-out in the line edit's event filter, and apply a strict one-decimal/range validator only at commit. Invalid commits restore the remembered display text; preset/programmatic changes continue through the existing immediate-preview path.
**File:** `view/pdf_view.py` (`_FontSizeInputValidator`, `_commit_text_size_input`), `view/text_editing.py` (`_validated_font_size_input`)

---

## Printable-area centering is not physical-paper centering

**Area:** `src/printing/qt_bridge.py`
**Symptom:** A PDF looked centred within a printer's printable region but had unequal margins on the physical sheet when hardware margins were asymmetric.
**Cause:** `QPrinter.pageRect(DevicePixel)` describes the printable area, not the paper sheet; its centre can differ from `paperRect(DevicePixel)`.
**Fix:** Pass `paperRect(DevicePixel)` to the existing fit/placement calculation in `_draw_page_image()`. Retain normal painter clipping for unprintable edge areas and test with deliberately asymmetric printable margins.
**File:** `src/printing/qt_bridge.py`; `test_scripts/test_print_layout.py`

---

## Document snapshots must restore blank-placeholder state too

**Area:** `model/pdf_model.py`, `model/edit_commands.py`
**Symptom:** Undo restored the original page bytes after delete-all, but the active session still treated a subsequently restored real document as a blank placeholder; redo after importing a real page could invert the same state.
**Cause:** `blank_placeholder_active` is intentionally model/session state rather than serialized PDF metadata, while `SnapshotCommand` previously restored only document bytes.
**Fix:** Store optional before/after placeholder flags on `SnapshotCommand` and apply the matching flag immediately after its byte snapshot is restored. Controllers capture the flags around delete-all and imported-page replacement commands.
**File:** `model/pdf_model.py`, `model/edit_commands.py`, `controller/pdf_controller.py`

---

## App-object payload versions are parser contracts, not feature counters

**Area:** `model/tools/annotation_tool.py`, `model/pdf_object_ops.py`
**Symptom:** A newly created rectangle rendered correctly, but object hit-testing, move, resize, and delete stopped recognizing it.
**Cause:** Adding appearance fields also changed the embedded payload from version 1 to version 2, while `_load_app_object_payload()` deliberately accepts only `_APP_OBJECT_VERSION == 1`. The new fields were backward-compatible, but the version bump made the whole annotation opaque to object operations.
**Fix:** Keep payload version 1 when adding optional backward-compatible fields. Only bump the version together with parser migration/compatibility logic and tests covering every object operation.
**File:** `model/tools/annotation_tool.py`, `model/pdf_object_ops.py`
**Tests:** `test_scripts/test_object_manipulation_model.py`

---

## PyMuPDF annotations retain their page through the page wrapper

**Area:** PyMuPDF annotation tests
**Symptom:** Accessing `annot.type`, `annot.border`, or `annot.colors` immediately after `next(doc[0].annots())` raises `FzErrorArgument: annotation not bound to any page`.
**Cause:** The temporary `doc[0]` page wrapper can be released after the expression, while the annotation wrapper still depends on that page object.
**Fix:** Keep a strong local page reference for as long as annotation properties are inspected: `page = doc[0]; annot = next(page.annots())`.
**File:** `test_scripts/test_object_manipulation_model.py`

---

## `tobytes(encryption=NONE)` on the *live* encrypted doc poisons its next `encryption=KEEP` save

**Area:** `model/pdf_model.py` — `capture_worker_snapshot_bytes()` / `capture_print_snapshot_bytes()` (M3.5)
**Symptom:** Manual test: edit metadata on an encrypted PDF, save, close, reopen with the correct password — all pages render blank, and MuPDF logs `syntax error in content stream` / `format error: aes padding out of range` from the render/thumbnail workers. `needs_pass`/`is_encrypted` looked normal on the saved file the whole time, so nothing in the save path's own checks caught it.
**Cause:** Every page render and thumbnail calls `capture_worker_snapshot_bytes()`, which called `self.doc.tobytes(garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE)` directly on the live, already-authenticated `fitz.Document`. In PyMuPDF 1.27.1, decrypt-and-flatten on the live handle silently corrupts its internal AES crypt state — invisible to `needs_pass`/`is_encrypted`, which read the same both before and after. Any later `doc.save(..., encryption=PDF_ENCRYPT_KEEP)` on that *same* handle then writes content streams that no longer decrypt correctly. Since real usage always renders a page before the first save, this reliably corrupted every encrypted-PDF save, not just a rare edge case. (Reading `.needs_pass`/`.is_encrypted` a second time on an already-authenticated handle is a *separate* trigger for the identical symptom — never re-read either property after `authenticate()` has already succeeded once; `doc.metadata["encryption"]` is the safe encryption probe, confirmed non-corrupting.)
**Fix:** Added `_decrypted_snapshot_bytes()`: for unencrypted docs, behavior is unchanged (direct `tobytes(NONE)`, no overhead). For encrypted docs, first take an `encryption=KEEP` snapshot (proven safe — the same pattern `_capture_doc_snapshot`/`_roundtrip_live_doc` already use), open it as a throwaway clone, re-authenticate the clone if needed, and call `tobytes(encryption=NONE)` on the *clone* — never on `self.doc`. `capture_worker_snapshot_bytes()` and `capture_print_snapshot_bytes()` both route through it.
**File:** `model/pdf_model.py`
**Tests:** `test_scripts/test_secure_persistence.py::test_worker_snapshot_before_edit_does_not_corrupt_later_encrypted_save`

---

## A later unconditional panel sync silently undoes an earlier mode-specific one

**Area:** `view/pdf_view.py` — `PDFView.set_mode()` / `_sync_text_property_panel_state()` (M3.5)
**Symptom:** Manual test: entering rectangle/underline/strikeout mode showed no stroke/fill/border/opacity controls in the right sidebar — "no place to pick" — even though the widgets existed and were fully wired (`rect_card`, `highlight_card`).
**Cause:** `set_mode()` correctly calls `right_stacked_widget.setCurrentWidget(self.rect_card)` (etc.), but it *unconditionally* calls `_sync_text_property_panel_state()` right after. That function only special-cases `add_text`/`edit_text`/an active text selection; for every other mode (including `rect`/`highlight`/`underline`/`strikeout`) it falls through to `stacked.setCurrentWidget(page_info_card)`, immediately clobbering the card `set_mode()` had just picked. Two functions independently "owned" the same `QStackedWidget.currentWidget()` with no coordination, so the later call always won regardless of which mode was actually active. Also found in the same investigation: the right sidebar itself has no auto-show when entering one of these modes (parallel to the existing `_ensure_left_sidebar_visible()` used for the left sidebar), so a previously-hidden right sidebar stayed hidden even once the correct card was showing.
**Fix:** `_sync_text_property_panel_state()` now returns immediately when `current_mode` is `rect`/`highlight`/`underline`/`strikeout`, leaving whatever `set_mode()` set untouched. Added `_ensure_right_sidebar_visible()` (mirrors `_ensure_left_sidebar_visible()`) and call it from `set_mode()` for every mode with a dedicated properties card (`rect`, `highlight`/`underline`/`strikeout`, `add_text`, `edit_text`).
**File:** `view/pdf_view.py`
**Tests:** `test_scripts/test_interaction_modes.py::test_entering_a_property_mode_reopens_a_hidden_right_sidebar`

---

## Markup-mode mouse press fell through to Qt's default QGraphicsView handling

**Area:** `view/pdf_view.py` — `_mouse_press()` / `_mouse_move()` / `_mouse_release()` for `highlight`/`underline`/`strikeout` modes (M3.5)
**Symptom:** Manual test: dragging to create an underline moved the page/view unexpectedly mid-drag and on release ("page jumps to another place"), and no live preview rectangle followed the cursor — only a shape appeared at mouse-up, and its geometry only tracked the release Y-position.
**Cause:** Two independent bugs, both from markup modes not mirroring `rect` mode:
1. The `rect` press handler set `_drawing_page_idx`/`drawing_start`, called the preview updater, then `event.accept(); return`. Markup press only set `drawing_start` and fell through to `QGraphicsView.mousePressEvent(...)` — Qt's *default* handling ran underneath (rubber-band/pan) — and `_mouse_move`'s preview branch was gated to `current_mode == 'rect'` only, so markup drags got zero visual feedback until release. (Fixed first, but the release-time page jump persisted — this was fix #2, below.)
2. `rect`'s release handler anchors to `_drawing_page_idx` — the page the drag *started* on — for the entire gesture. The markup release handler instead recomputed the target page from the drag rect's vertical **center** every time, ignoring `_drawing_page_idx` entirely and never clamping `end_pos` to the starting page. A drag that drifted toward an adjacent page (or a page short enough that the drag's midpoint fell into the next page's y-range) would commit the annotation to a *different* page than the one being drawn on — and the subsequent `show_page()` call would then visibly navigate/recenter there. This is what manual testing kept seeing as "page jump" even after fix #1 landed.
**Fix:** Markup press now mirrors `rect`: computes and clamps to the starting page, sets `_drawing_page_idx`, calls the (now-shared) preview updater, and accepts+returns; `_update_rect_preview()` and the move handler's preview branch cover `rect`/`highlight`/`markup_line` uniformly (markup preview renders in the active style's color). Markup release now also prefers `_drawing_page_idx` over the center recompute and clamps `end_pos` to that page before building the rect — identical anchoring to `rect` mode.
**File:** `view/pdf_view.py`
**Tests:** `test_scripts/test_interaction_modes.py::test_markup_drag_accepts_press_and_shows_live_preview`, `test_scripts/test_interaction_modes.py::test_markup_line_drag_stays_anchored_to_starting_page`

---

## Underline/strikeout merged into one `markup_line` mode; PyMuPDF has no width API for either

**Area:** `view/pdf_view.py` — toolbar, `_setup_property_inspector()`, mode dispatch (M3.5 follow-up)
**Symptom/request:** User asked to combine the separate underline/strikeout tools into one, with per-style color (e.g. underline yellow, strikeout red) and a line-width control.
**Investigation:** `page.add_underline_annot()`/`add_strikeout_annot()` both raise on `annot.set_border(width=...)` — `"Cannot set border for 'Underline'"` / `'StrikeOut'`. These annotation subtypes have no PDF-level border/width concept at all; PyMuPDF isn't withholding an existing feature, there's genuinely nothing to set. A width control would require switching to a generic `Line` annotation positioned at the underline/strikeout Y-offset instead — which gains `set_border()` but loses the semantic Underline/StrikeOut subtype other PDF readers use to recognize/toggle "underlined text". User deferred this decision; tracked in `TODOS.md`.
**Fix:** Two former toolbar actions/modes (`underline`, `strikeout`) collapsed into one `markup_line` mode and toolbar button ("標記線"). `markup_line_card` holds a style radio pair (底線/刪除線) plus one color button + opacity slider; `self.underline_color`/`self.strikeout_color` are independent `QColor`s so switching styles never clobbers the other's setting (`_markup_line_current_color()` resolves the active one). The release-time dispatch (`sig_add_underline` vs `sig_add_strikeout`) now keys off `self.markup_line_style`, not `self.current_mode` — the controller-side `add_underline`/`add_strikeout` methods and their signals are unchanged.
**File:** `view/pdf_view.py`, `controller/pdf_controller.py` (`_VALID_MODES`)
**Tests:** `test_scripts/test_interaction_modes.py::test_markup_line_mode_has_a_single_combined_toolbar_action`, `test_scripts/test_interaction_modes.py::test_markup_line_style_toggle_preserves_each_styles_own_color`, `test_scripts/test_interaction_modes.py::test_markup_line_drag_emits_style_specific_signal_and_color`

---

## PyMuPDF annot geometry is unrotated-space on BOTH write and read; `annot.rect` readback is a false oracle

**Area:** `model/tools/annotation_tool.py` — every `page.add_*_annot` / `annot.set_rect` / `annot.rect` site
**Symptom:** Rectangle/highlight/underline/strikeout/note annotations land down-right of the click on `/Rotate` pages (the complex HVAC fixture's pages are rotation=270). Tests asserting on `annot.rect` readback pass anyway, because readback echoes the requested values in unrotated space — only pixel-level verification of a rendered pixmap exposes the misplacement.
**Cause:** PyMuPDF 1.27 interprets annot-creation geometry (and stores `/Rect`) in **unrotated** page space, while the app deals exclusively in displayed (`page.rect`) coordinates. Every self-canceling view path (text selection, object handles, inline editor) *looked* correct because scene→doc→scene round-trips through the same helpers cancel any absolute bias; annotations bake absolute coordinates. (Correction, 2026-08-29: the text paths only cancelled *relative to their own misplaced outline* — against the raster they were wrong on every `/Rotate 90/270` page; see "The model's text-geometry surface was unrotated dict space…".) Two extra traps: (1) markup annots follow quad corner roles, so a derotated *rect* still draws underline ink on a vertical edge at 90/270 — a corner-mapped `fitz.Quad` is required; (2) Text/Note icons are fixed-size glyphs anchored at the rect corner, so `set_rect` needs anchor-point derotation, not corner-remap+normalize. Exception: `add_redact_annot` accepts displayed coords (rotation-safe), so the text-commit engine is unaffected.
**Fix:** Convert at the model boundary in BOTH directions via chokepoint helpers in `AnnotationTool`: `_derotate_rect`/`_derotate_point`/`_displayed_rect_to_quad`/`_derotate_text_annot_rect` on write, `_rotate_rect_to_displayed` on read (`get_all_annotations`). Regression tests must use baseline-relative pixel detection (render at rotation 0 as the expected ink bbox, compare rotations 90/180/270 against it) — never `annot.rect`.
**File:** `model/tools/annotation_tool.py`, `test_scripts/test_annotation_rotation.py`

---

## Python 3.10 `Path.resolve(strict=False)` still raises on unreachable UNC paths (WinError 53)

**Area:** `utils/preferences.py` — `canonicalize_recent_path`; any `resolve()` on user-supplied paths
**Symptom:** `PDFController.activate()` crashed with `FileNotFoundError: [WinError 53] 找不到網路路徑` when the recent-files store contained a document on a currently-unreachable network share; ~8 controller tests failed identically. Was live on the dev machine 2026-07-17 (a `\\192.168.1.238\...` work document went stale). A second live crash path: `open_pdf()` → `find_session_by_path()` → `PDFModel._canonicalize_path` (plain `resolve()`, no strict) ran BEFORE `open_pdf`'s try/except at startup/forwarded-CLI/recent-click.
**Cause:** CPython 3.10's non-strict `resolve()` walks `_getfinalpathname` and only swallows an allow-list of WinErrors; 53 (`ERROR_BAD_NETPATH`) was added to that list in a later Python. `Path.is_file()` is safe (returns False); `resolve()` is not. Compounding gap: the test suite reads the REAL user preference store, so one stale machine-local entry poisons unrelated suites.
**Fix:** Chokepoint guards catching ONLY `OSError` with a pure-string fallback (`os.path.abspath(os.path.expanduser(...))`, which preserves the normcase+normpath dedup identity): `_safe_resolve_path` in `utils/preferences.py`, the same pattern inside `PDFModel._canonicalize_path`, plus per-entry defense in `_refresh_recent_files` (`available=False`, never abort activate). `utils/single_instance.py` must stay FAIL-CLOSED per the IPC argv contract: sender `_normalize_forwarded_argv` returns `None` on any unresolvable token (whole hand-off rejected), receiver `_forwarded_argv_is_acceptable` returns `False` — never skip a token. Lower-severity inline save-time `resolve()` sites (insert/merge/save paths in `pdf_model.py`, optimize dedupe, print dispatcher) are audited-but-unguarded follow-ups tracked in `TODOS.md`.
**File:** `utils/preferences.py`, `model/pdf_model.py` (`_canonicalize_path`), `utils/single_instance.py`, `controller/pdf_controller.py` (`_refresh_recent_files`)
**Tests:** `test_scripts/test_recent_files_unc_robustness.py` (6, red-light-first; guard tests verified red-on-revert)

## `itemActivated` + `EditKeyPressed`-only triggers hide a QTreeWidget's editability
**Area:** `view/pdf_view.py` — bookmark panel (`self.bookmark_tree`)
**Symptom:** M3.7 manual QA reported "沒找到怎麼操作" (couldn't find how) for both renaming a bookmark and changing its page number, even though `populate_toc()` already sets `Qt.ItemIsEditable` on both columns and `_on_toc_item_changed` already validates/clamps page edits and emits `sig_toc_changed`. The feature worked end-to-end; users just never triggered it.
**Cause:** `setEditTriggers(QAbstractItemView.EditKeyPressed)` means only F2 opens the inline editor, and the intuitive gesture — double-click — was already claimed by `itemActivated` → `_on_bookmark_activated` (jump-to-page navigation). With no visible affordance (no menu, no button) pointing at F2, the edit path was functionally undiscoverable despite being fully implemented.
**Fix:** Added a right-click context menu on the tree (`setContextMenuPolicy(Qt.CustomContextMenu)` + `customContextMenuRequested`) with "重新命名" and "設定頁碼" actions that call `self.bookmark_tree.editItem(item, 0)` / `editItem(item, 1)` — reusing the existing `itemChanged` → `_on_toc_item_changed` → `sig_toc_changed` path unchanged. Double-click-to-navigate is untouched. General lesson: an `EditTriggers` value narrower than the default (`AllEditTriggers`) needs an explicit, visible affordance somewhere, or treat the feature as undiscovered even if the wiring is correct.
**File:** `view/pdf_view.py` (`_build_bookmark_context_menu`, `_show_bookmark_context_menu`)
**Tests:** `test_scripts/test_bookmark_rename_ux.py`

## View-owned popup not scoped to a session silently mutates the wrong document
**Area:** `view/pdf_view.py` (`_floating_note`) + `view/floating_note.py`; class of bug applies to any singleton view widget that outlives a session
**Symptom:** There is one `PDFView` for the whole app; "tabs" are model/controller sessions keyed by `sid`, not separate widgets. `_floating_note` was a single un-scoped attribute. Open a note popup on tab A, switch to tab B (making B the active session), then hit Save/Delete on the still-open A popup — it wrote/deleted against B's document at A's page/xref, silently corrupting B. Deleting the note via its own 刪除 button also left the popup editing a now-nonexistent xref (it emitted `delete_requested` but never `.close()`d).
**Cause:** The popup's `save_requested`/`delete_requested`/`marker_move_requested` signals route through the controller to `update_annotation_content`/`delete_annotation`/`move_annotation_marker`, which all call `_record_annotation_mutation` → `self.model.tools.annotation.*`. Those tools operate on `self.model.doc`, i.e. whatever `get_active_session_id()` currently points at — never the session the popup was opened for. A view-owned widget with no session ownership + active-session-relative mutation = cross-document write. `on_tab_close_requested` tore down a dozen `*_by_session` dicts but never referenced `view._floating_note`.
**Fix:** Give the popup a session identity and one lifecycle chokepoint. The view records `_floating_note_sid` (the active tab's `tabData`) when the popup opens, and `_dismiss_floating_note_if_orphaned()` closes it whenever the currently-active tab's `sid` no longer matches. That chokepoint is called from `set_document_tabs`, which the controller already funnels every tab switch, tab close, and empty-UI reset through — so one function covers all three paths instead of three ad-hoc patches. Session identity comes from the tab bar's `tabData` the controller already handed the view (no new View→Model call). Separately, `FloatingNote`'s delete button now `.close()`s itself (relying on `WA_DeleteOnClose`) after emitting. General lesson: a singleton view widget that acts on the *active* session must track which session spawned it and self-dismiss the instant that session stops being current.
**File:** `view/pdf_view.py` (`_show_floating_note`, `_active_document_session_id`, `_dismiss_floating_note_if_orphaned`, `_forget_floating_note`, `set_document_tabs`), `view/floating_note.py` (`_emit_delete`)
**Tests:** `test_scripts/test_floating_notes.py` (`test_delete_button_closes_the_popup`, `test_closing_the_popups_owning_tab_dismisses_the_popup`, `test_switching_away_from_owning_tab_severs_the_cross_session_mutation_path`)

## Full-rebuild `populate_toc` discards any selection set immediately before `sig_toc_changed`
**Area:** `view/pdf_view.py` — bookmark panel (`self.bookmark_tree`), TOC round-trip
**Symptom:** M3.7 manual QA reported that every "上移"/"下移" (move bookmark up/down) press deselected the moved bookmark, forcing a re-click before the next move (每按一次上移或下移就會取消聚焦該書籤). `_move_selected_bookmark` did the right thing locally — reorder, `setCurrentItem(moved)`, emit — yet the selection was gone the moment control returned.
**Cause:** `sig_toc_changed` is connected to the controller's `update_toc`, which persists then calls `load_toc()` → `view.populate_toc(entries)`. `populate_toc` does a FULL `tree.clear()` + rebuild of fresh `QTreeWidgetItem`s. Qt signal emission is **synchronous within the same call stack**, so the rebuild runs immediately after `setCurrentItem` and destroys the just-selected item before the event loop ever repaints. Any per-widget UI state (selection, expansion, scroll, focus) set right before emitting a signal that triggers a clear-and-rebuild is thrown away — the same trap applies to annotations/watermarks lists or any list that round-trips through the model.
**Fix:** Carry the intent through the rebuild instead of setting live widget state before it. The moved item's identity is expressed as its flat DFS pre-order index in the TOC entries (the exact order `populate_toc` iterates and `_toc_entries_from_tree`/`get_toc` preserve), stashed in a View-internal `_pending_toc_selection` by `_move_selected_bookmark`. `populate_toc` collects the items it builds in order and, at the end, `_restore_pending_toc_selection` re-selects/`setFocus`es the item at that index, then clears the pending state. Mechanism lives entirely in the View (it owns its own refresh behavior — no Controller/Model change) and is scoped to the move path (add/delete/rename intentionally let focus move). Boundary no-op moves (`return` before any emit) never set the pending index, so they can't mis-target.
**File:** `view/pdf_view.py` (`_move_selected_bookmark`, `_flat_index_of_bookmark_item`, `populate_toc`, `_restore_pending_toc_selection`)
**Tests:** `test_scripts/test_bookmarks_toc.py` (`test_move_bookmark_up_preserves_selection_after_rebuild`, `test_move_bookmark_down_preserves_selection_after_rebuild`, `test_move_child_bookmark_preserves_selection_after_rebuild`, `test_move_bookmark_boundary_noop_leaves_selection_intact`)

---

## PyMuPDF version skew masks runtime-only bugs
**Area:** Environment / test toolchain (`requirements.txt`, `constraints-ci.txt`)
**Symptom:** A test suite run passes or fails inconsistently depending on which interpreter ran it, even with no code changes -- e.g. a stream-serialization or `extract_font` bug that only reproduces on one machine.
**Cause:** `requirements.txt` used to floor-pin `PyMuPDF>=1.23`. The maintainer's `.venv` resolves 1.27.1, but a bare system-Python `pytest` invocation can resolve a materially older minor (observed: 1.25.5) with different stream serialization / font-extraction behavior. CI was already pinned exactly via `constraints-ci.txt`, so the drift only bit local runs -- which is worse, because it looks like a flaky bug instead of an environment mismatch.
**Fix:** Pin `requirements.txt`/`pyproject.toml` to a single minor range (`>=1.27,<1.28`), and add `test_scripts/test_environment_pins.py::test_pymupdf_version_within_pinned_range`, which fails loudly (naming the resolved version and the fix) instead of letting skew silently change behavior. Always invoke tests via `.venv\Scripts\python.exe -m pytest`, never bare `pytest` (CLAUDE.md §3.1).
**File:** `requirements.txt`, `pyproject.toml`, `test_scripts/test_environment_pins.py`

## A local pre-commit hook is not durable across clones/worktrees -- pair it with a CI gate
**Area:** `scripts/hooks/` (device-identity guard)
**Symptom:** A rule the maintainer has learned the hard way (e.g. "never commit this machine's username/hardware fingerprint" -- see the 2026-07-15 incident that required a git history rewrite) gets re-violated later because a fresh clone or worktree never had the local git hook installed.
**Cause:** `.git/hooks/` is not version-controlled; git never installs hooks from a repo checkout automatically, and hooks live in the *common* git dir (`git rev-parse --git-common-dir`), not per-worktree, which trips up naive `.git/hooks`-path assumptions in linked worktrees.
**Fix:** Ship the guard logic as an importable, unit-testable module (`scan_diff()` in `scripts/hooks/pre_commit_device_guard.py`) with a separate installer (`scripts/hooks/install_git_hooks.py`) for the opt-in local hook, AND run the same script in CI with `--base <ref>` diffing the PR/push range -- the CI leg is the one that can't be skipped by an uninstalled hook.
**File:** `scripts/hooks/pre_commit_device_guard.py`, `scripts/hooks/install_git_hooks.py`, `.github/workflows/ci.yml` (`device-guard` job)

---

## Normalized PDF token serialization cannot prove lossless text patching
**Area:** text-commit design; `model/pdf_content_ops.py`
**Symptom:** A content-stream edit appears semantically correct, but comments, whitespace, token formatting, or unrelated bytes change across the stream, invalidating a byte-identity fidelity guarantee.
**Cause:** `tokenize_content_stream()` intentionally skips whitespace/comments, and `serialize_tokens()` rejoins every token with newlines. This is acceptable for existing native-image operator rewrites, but it cannot preserve untouched source bytes for a high-fidelity text tier.
**Fix:** Use a separate lossless lexer that records raw byte ranges/trivia and a splice-only writer whose replacements carry expected source bytes and stream digests. Keep `pdf_content_ops` on its existing normalized contract; do not retrofit Tier 0 text patching onto it.
**File:** design in `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`; future `model/text_commit/pdf_lexer.py`

---

## `Tj`/`TJ` edits must preserve consumed text advance, not just surrounding operators
**Area:** text-commit design; future `model/text_commit/replay.py` and `patch.py`
**Symptom:** Editing or removing a target string leaves every non-target operator byte intact, yet suffix glyphs or later text in the same `BT`/`ET` move.
**Cause:** PDF text-show operators advance the text matrix. Replacing a substring with different metrics shifts suffix glyphs; removing a show operator removes its entire advance. Preserving nearby kerning numbers or positioning operators alone does not preserve later text position.
**Fix:** Initial Tier 0 accepts only whole supported show operations with verified equal advance. Any later substring or Tier 1 erase support must emit an exact text-space compensation and verify downstream matrices/origins before commit. Ambiguous or unsupported cases reject rather than guess.
**File:** design in `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`; future `model/text_commit/replay.py`, `model/text_commit/patch.py`, `model/text_commit/verify.py`

---

## PyMuPDF PDF generation is not byte-deterministic
**Area:** `scripts/build_fidelity_corpus.py` (fidelity corpus generator)
**Symptom:** Calling `doc.tobytes()` multiple times on identically-constructed PyMuPDF documents produces different byte content (different SHA-256 hashes each run), even after stripping metadata with `doc.set_metadata({})`.
**Cause:** Internal MuPDF allocation or serialisation uses non-deterministic state (object numbering, compression, internal IDs). There is no public API to seed or stabilise this.
**Fix:** Do not check generated PDFs into git and rely on byte identity. Instead, treat the generator script as the canonical corpus definition: generate PDFs on-the-fly (in `tmp_path` / at test time), and verify *structural* properties (font types, encodings, text content, stream operators) rather than byte hashes.
**File:** `scripts/build_fidelity_corpus.py`

## PyMuPDF `insert_text` vs TextWriter produce fundamentally different font structures
**Area:** `scripts/build_fidelity_corpus.py`, `model/text_commit/font_registry.py` (future)
**Symptom:** `page.insert_text(fontname="helv")` creates an unembedded Type1 base-14 reference (buffer length 0), while `TextWriter` with `fitz.Font("helv")` embeds the font as a Type0/CIDFont with Identity-H encoding (buffer ~33KB). Both use "Helvetica" but produce completely different PDF structures.
**Cause:** `insert_text` uses the PDF spec's base-14 font reference (no embedding required). TextWriter always embeds the font program as a CIDFont for full Unicode coverage.
**Fix:** Choose the API based on which PDF structure the test case needs. For base-14 unembedded: `page.insert_text(fontname="helv")`. For embedded/extractable fonts: use TextWriter with `fitz.Font(...)`. The `DocumentFontRegistry` (Phase A) must handle both structures.
**File:** `scripts/build_fidelity_corpus.py`

## PyMuPDF merges close `insert_text` calls into a single text block
**Area:** `scripts/build_fidelity_corpus.py`, test fixtures
**Symptom:** Two separate `page.insert_text()` calls placed vertically close together (e.g. 15pt gap with fontsize=12) appear as a single block in `page.get_text("dict")["blocks"]` — tests expecting separate blocks fail.
**Cause:** MuPDF's text extraction groups lines into blocks using a proximity heuristic (~1.5x font size). Lines closer than this threshold are merged into one block regardless of how they were inserted.
**Fix:** Space separate text blocks at least 2x the font size apart (e.g. >=35pt gap for fontsize=12) to ensure they report as distinct blocks in `get_text("dict")`.
**File:** `scripts/build_fidelity_corpus.py`

## PyMuPDF `Document.get_new_xref()` not `new_xref()`
**Area:** `scripts/build_fidelity_corpus.py` (direct PDF object construction)
**Symptom:** `AttributeError: 'Document' object has no attribute 'new_xref'` when trying to create new indirect objects for Type3 fonts, Form XObjects, or custom encoding dictionaries.
**Cause:** PyMuPDF 1.27 renamed the method to `get_new_xref()`. Older documentation and examples may reference `new_xref()`.
**Fix:** Use `doc.get_new_xref()` to allocate new indirect object numbers.
**File:** `scripts/build_fidelity_corpus.py`

---

## `doc.tobytes()` of the SAME unchanged document differs between calls
**Area:** `model/text_commit/engine.py`; any "no mutation" test assertion
**Symptom:** `assert doc.tobytes() == before` fails even though nothing touched the document — one byte in the trailer region differs.
**Cause:** PyMuPDF regenerates the trailer `/ID` (and may re-serialize other bookkeeping) on every save/serialization, so two `tobytes()` calls on an identical in-memory document are not byte-equal.
**Fix:** Never prove "document unchanged" with `tobytes()` equality. Compare structural fingerprints instead: `model/text_commit/inspect.py:page_fingerprint` (decoded streams + fonts + annots + widgets) plus `doc.xref_length()` for object-count drift. `tobytes()` round-trips are still fine for making scratch copies — xref numbering and decoded stream bytes are preserved.
**File:** `test_scripts/test_text_commit_tier0.py`, `model/text_commit/inspect.py`

---

## `fitz.Font(<unknown name>)` raises `FzErrorArgument`, not RuntimeError — and known names may silently alias
**Area:** `model/text_commit/fonts.py`
**Symptom:** Catching `(RuntimeError, ValueError)` around `fitz.Font(name)` lets `pymupdf.mupdf.FzErrorArgument` escape (its MRO is `FzErrorBase -> Exception`, not RuntimeError). Separately, some name lookups can succeed with an unrelated face.
**Cause:** PyMuPDF 1.27 raises its own `FzError*` hierarchy from `fz_new_base14_font`; name resolution is permissive.
**Fix:** Catch `fitz.mupdf.FzErrorBase` alongside RuntimeError/ValueError, and after a successful named load verify `face.name` corroborates the requested family before trusting it (`resolve_system_face` returns None otherwise — no silent Helvetica).
**File:** `model/text_commit/fonts.py`

---

## `Document.xref_copy` needs a dict-initialized target; `xref_set_key` cannot create keys through indirect paths
**Area:** test fixtures / direct PDF object surgery
**Symptom:** `xref_copy(src, doc.get_new_xref())` fails with "not a dict (null)"; `xref_set_key(page.xref, "Resources/Font/X", ...)` fails with "path to 'X' has indirects" when /Resources (or /Font) is an indirect reference.
**Cause:** A fresh xref from `get_new_xref()` holds `null` — `xref_copy` copies key-by-key into an existing dict. `xref_set_key` refuses to auto-create nested keys across indirect boundaries.
**Fix:** `doc.update_object(new_xref, "<<>>")` before `xref_copy`. For resource registration, resolve each indirect level (`xref_get_key` returning `("xref", "N 0 R")`) and set the key on the owning object directly.
**File:** `test_scripts/test_text_commit_fonts.py:_register_font_resource`

---

## MuPDF `insert_htmlbox` break-all does NOT split words that fit a line
**Area:** legacy commit path characterization; `model/pdf_model.py:_build_insert_css`
**Symptom:** Expected mid-word line breaks from `word-break: break-all; overflow-wrap: anywhere` do not reproduce: MuPDF still breaks at spaces when each word fits the box width.
**Cause:** MuPDF's HTML engine applies break-anywhere only when a single word exceeds the full line width; it is not a browser-faithful `break-all`.
**Fix:** The real, deterministic line-break defect of the legacy engine is different: the insert box is widened up to the page's safe right margin and the paragraph re-breaks at that new width (a 3-line paragraph commits as 1 line). Characterize that (`test_paragraph_edit_preserves_original_line_breaks`), not mid-word splitting.
**File:** `test_scripts/test_text_commit_characterization.py`

---

## Block-manager runs are word-level: one show op maps to several member spans
**Area:** `model/pdf_text_edit.py` (V2 engine target derivation); `model/text_block_parsing.py`
**Symptom:** A single-line `(Price 2024) Tj` resolves to TWO member spans ('Price', '2024'), so a "single member span" gate rejects every normal edit with `multi_span_target`, and Tier 0 never fires.
**Cause:** `TextBlockManager` deliberately splits rawdict spans into word-level runs (`EditableSpan`) for run-mode editing granularity. Span-count is therefore a property of the editing UI model, not of the content stream: N member runs can still be one whole show operator.
**Fix:** Derive the Tier 0 target as either exactly one member run (whole-word Tj) or a member set that covers one full line of one block (verified against `block_manager.get_runs`), space-joining the run texts in x-order to reconstruct the show-op string. Partial-line and multi-line selections reject honestly.
**File:** `model/pdf_text_edit.py:_tier0_target_from_resolve`

---

## Dropping the last Python reference to an unparented cross-thread QObject is an access violation
**Area:** PySide6 threading; `controller/text_commit_coordinator.py`
**Symptom:** `Windows fatal exception: access violation` with `<no Python frame>` in the worker thread during session teardown; the main thread sits innocently in `QThread.wait()`.
**Cause:** An unparented `QObject` worker moved to a `QThread` is owned by its Python wrapper. Setting `self._worker = None` on the main thread while the worker thread is still delivering a queued call destroys the C++ object immediately — from the wrong thread, under a live event delivery.
**Fix:** Retain retired `(thread, worker)` pairs in a list until `thread.isFinished()`; only then let the wrappers go. Prefer a dedicated queued Signal for cross-thread shutdown over `QMetaObject.invokeMethod`, and quit the thread from inside the worker's shutdown slot. `PageRenderCoordinator._threads` follows the same rule.
**File:** `controller/text_commit_coordinator.py:TextCommitPreviewCoordinator.end_session`

---

## `insert_pdf` strips the SOURCE page's annotation `/P` key — even on whole-document copies
**Area:** PyMuPDF; `model/pdf_model.py` undo snapshots
**Symptom:** After any `edit_text()` call (Tier 0 or legacy), an annotation on the edited page loses its `/P` (parent-page) key in the LIVE document; xref, rect, and `/AP` appearance stream all survive. Dictionary-identity assertions fail.
**Cause:** `PDFModel._capture_page_snapshot` builds the undo snapshot via `tmp_doc.insert_pdf(self.doc, ...)`. PyMuPDF's `insert_pdf` mutates the *source* document as a side effect: it deletes each source annotation's `/P` key. Confirmed independent of the `annots=` flag and reproduced even with a full `from_page=0, to_page=-1` copy — pure fitz, no model code.
**Fix:** Snapshot every annotation's FULL `xref_object()` string before the `insert_pdf` call and restore it verbatim afterwards with `doc.update_object(xref, captured)`. A `xref_get_key`/`xref_set_key` round-trip of just `/P` is NOT enough — the restored key is re-appended at the end of the dict, so string-identity checks still fail; only the full-object restore round-trips byte-for-byte including key order.
**File:** `model/text_commit/inspect.py:capture_annotation_parent_refs` / `restore_annotation_parent_refs`; caller `model/pdf_model.py:_capture_page_snapshot`

---

## `doc.tobytes()` with default encryption poisons a live encrypted document — even read-only
**Area:** PyMuPDF AES-256; `model/text_commit/engine.py`, `model/text_commit/verify.py`
**Symptom:** After a Tier 0 attempt on an encrypted document, a later `encryption=PDF_ENCRYPT_KEEP` save (incremental OR full) writes a file whose content streams no longer decrypt — real corruption, not a safe reject.
**Cause:** `tobytes()` defaults to `encryption=NONE` (decrypt-on-serialize). Calling it on the LIVE authenticated handle — as `TieredCommitEngine.prepare` did to build its scratch copy and as V0e's reopen probe did again — silently poisons that handle's internal crypt state (same PyMuPDF 1.27.1 quirk already pinned by `test_secure_persistence.py::test_worker_snapshot_before_edit_does_not_corrupt_later_encrypted_save`). The damage surfaces only at the NEXT save, far from the cause.
**Fix:** On any live possibly-encrypted doc, always serialize with `encryption=fitz.PDF_ENCRYPT_KEEP` (a safe no-op for unencrypted docs, so one code path covers both), then reopen + re-authenticate a throwaway clone for anything needing decrypted content. A locked reopened doc still exposes an accurate `page_count`, so pure reopenability probes need no password at all. The two remaining unguarded call sites — `preview.py:open_preview_session` and `verify.py:_ocg_membership_lost` — were closed the same way (2026-07-31); both were measurably stripping encryption off the live handle, not just theoretically at risk. Note the asymmetry when converting a probe: a *reopenability* probe works fine against a locked clone, but a probe that must read content (OCG membership, text extraction) cannot, so it needs either a password or an explicit "could not evaluate" answer — never a silent "no problem found".
**File:** `model/text_commit/engine.py:_build_scratch_copy`; `model/text_commit/verify.py` (V0e probe, `_ocg_membership_lost`); `model/text_commit/preview.py:_session_snapshot_bytes`; tests in `test_scripts/test_text_commit_encrypted_safety.py`

---

## `insert_pdf` renumbers xrefs — unusable for xref-identical scratch copies
**Area:** PyMuPDF; `model/text_commit` scratch-first verification
**Symptom:** A scratch copy built with `insert_pdf` yields different `page.xref` / content-stream xrefs than the source, so fingerprint- and xref-keyed plans (PatchSet.page_xref, stream xrefs) never match.
**Cause:** `insert_pdf` rebuilds the object graph and renumbers destination xrefs relative to the source — even for a full `from_page=0, to_page=-1` copy.
**Fix:** Only a same-document `tobytes()`+reopen round-trip preserves xref numbering (with `encryption=PDF_ENCRYPT_KEEP` on live encrypted docs — see previous entry). Use that for any scratch copy that must be xref-identical.
**File:** `model/text_commit/engine.py:_build_scratch_copy`

## Pixel-uniformity occlusion checks need edge erosion
**Area:** model/text_commit/verify.py (Tier-1 spike: verify_tier1_strategy / _region_is_uniform)
**Symptom:** A z-order/occlusion check that samples "is this whole region one flat color" reported non-uniform even when a fully-opaque covering rectangle painted over the target with nothing else in the region — because PyMuPDF anti-aliases the rectangle's own edge against the page background, producing a thin ring of blended colors right at the declared bbox boundary.
**Cause:** The declared target bbox coincided exactly with the covering rect's own fill coordinates; sampling all the way to that boundary picks up the rect's edge anti-aliasing, not any change in the underlying (occluded) content.
**Fix:** Erode the sampled pixel region inward by a small fixed margin (`_UNIFORM_ERODE_PX = 2`) before checking uniformity, so only the flat interior — away from any shape's own rendered edge — is compared.
**File:** model/text_commit/verify.py (`_region_is_uniform`, `_UNIFORM_ERODE_PX`)

## A "graphics-state bleed" ink-tint check must not sample a covering shape's own fill color
**Area:** model/text_commit/verify.py (Tier-1 spike: verify_tier1_strategy)
**Symptom:** A check for "is the darkest pixel in the target region tinted (non-gray), meaning a dangling `rg` bled into the replacement's glyph ink" produced a false positive when the target was correctly still hidden under an opaque red rectangle (the z-order-preserving, PASSING outcome) — the only/darkest pixel found was the rectangle's own red fill, not glyph ink at all, since there was no visible ink to sample.
**Cause:** When z-order is correctly preserved, the target text stays fully occluded post-edit; naively sampling "whichever color is darkest in the declared region" instead samples whatever opaque content is on top, which is unrelated to the replacement's own fill color.
**Fix:** Gate the ink-tint check on the target region NOT being fully occluded post-edit, reusing the same flat-color occlusion test already computed for the z-order check; skip the ink check entirely (record `glyph_ink_not_visible_ignored`) when the region is still uniform/occluded.
**File:** model/text_commit/verify.py (`verify_tier1_strategy`)

## PyMuPDF insert_font(fontbuffer=..., set_simple=True) dedupes byte-identical programs onto the same xref
**Area:** model/text_commit fonts (font-honesty Tier-1 spike)
**Symptom:** Re-embedding the exact same extracted font bytes under a NEW resource name via `page.insert_font` silently reuses the original font's xref instead of creating a distinct object — a naive test/rebuild that expects a fresh `written_font_xref` gets the source xref back, which would make an honesty test for "not SOURCE_RESOURCE_REUSED" pass for the wrong reason.
**Cause:** PyMuPDF content-addresses inserted font programs; identical bytes never produce a second xref.
**Fix:** To force a genuinely distinct font object (as any real Tier-1 rebuild must produce), hand-clone it: `new_xref = doc.get_new_xref(); doc.update_object(new_xref, doc.xref_object(source_xref))`, then splice the new xref into the Resources' /Font subdict directly (Resources itself may be an indirect xref object, not an inline dict — read/rewrite via `doc.xref_get_key`/`doc.xref_set_key` on the Resources xref, not the page xref).
**File:** test_scripts/test_text_commit_textwriter_zorder.py (font-honesty fixture); relevant to any future model/text_commit/fonts.py Tier-1 rebuild code.

## OCG visibility only takes effect after a tobytes()+reopen round trip — and only on a *second* round trip after set_layer
**Area:** model/text_commit/verify.py (`_ocg_membership_status`)
**Symptom:** Calling `doc.set_layer(-1, off=[...])` on a live document and then immediately calling `get_text()`/rendering the same live page shows no change at all — the OCG toggle appears to be a no-op. Separately: a locked/encrypted KEEP probe (or any exception) used to return bool `False`, which `verify_tier1_strategy` recorded as `ocg_membership_preserved`.
**Cause:** OCG on/off state is only consulted by MuPDF's content interpreter when a document is (re)opened from bytes; a live, already-parsed page/pixmap does not re-evaluate it. Bool "not lost" conflated "preserved" with "could not evaluate".
**Fix:** Probe via KEEP `tobytes()`+reopen → `set_layer` → second `tobytes()`+reopen before `get_text()`, never mutating the live doc. Return tri-state `preserved`/`lost`/`unknown`; unknown must never be recorded as preserved.
**File:** model/text_commit/verify.py (`_ocg_membership_status`)

## Concatenating a block's spans is right; concatenating its lines deletes a word boundary
**Area:** model/text_block_parsing.py (`_parse_block`)
**Symptom:** `TextBlock.text` for a three-line paragraph read `'The quick brown fox jumpsover the lazy dog whilecarrying a heavy basket'` — the substring `'jumps over'` was not present at all. Silent: no error, just a wrong string handed to block matching and to `original_text=` on edit requests.
**Cause:** `_parse_block` flattened every span of every line into one list and `"".join`-ed it. Within a line that is correct — rawdict spans are contiguous style runs, and inserting a separator between them would split styled fragments mid-word (`"Sun"` + `"day"` → `"Sun day"`). Across lines it is not: soft wrapping is where the space went. The same module already had the right rule in `_build_paragraphs` (space between visual lines, `\n` at bullets/large gaps) and `pdf_text_edit.py:1223` space-joins its cluster path, so `_parse_block` was the lone dissenter — the giveaway that this was a defect rather than a deliberate convention.
**Fix:** Build one string per line, then join *lines* via `_join_visual_lines`: one space between lines, suppressed when the previous line already ends in space/newline/hyphen (a trailing hyphen is a split word, `"compre-"` + `"hensive"`), empty lines skipped. When fixing this class of bug, pin the non-fix too — a test that the over-correction (separating per *span*) does not happen.
**File:** `model/text_block_parsing.py:_join_visual_lines`; tests in `test_scripts/test_text_block_parsing_extraction.py`

## A wrong extracted string can hide as a *similarity* problem rather than a visible failure
**Area:** model/pdf_text_edit.py (`SequenceMatcher` block/page reconciliation)
**Symptom:** No user-visible error — just occasional unnecessary page-index rebuilds, and edit targeting that is subtly worse than it should be.
**Cause:** `pdf_text_edit.py:456-459` reconciles the indexed `target.text` against `page.get_text("text", clip=target.rect)` with `difflib.SequenceMatcher`, rebuilding the page index when the ratio drops below 0.5. `get_text` separates lines; the fused `TextBlock.text` did not, so every line break cost real similarity. The check absorbed the corruption instead of surfacing it — a threshold comparison degrades gracefully where an equality check would have failed loudly on day one.
**Fix:** Fixed at the source (see previous entry). The general lesson: a fuzzy comparator between two representations of the same text is a place where one side can be quietly wrong for a long time. When adding one, assert the *exact* agreement somewhere too, or the ratio silently becomes the spec.
**File:** `model/pdf_text_edit.py:456-459`

## Asserting that the replay *recorded* a text state does not test the gate that *rejects* it
**Area:** model/text_commit planner gates (`plan.py`, `inspect.py`) + their tests
**Symptom:** `plan.py`'s `mc_depth` gate and its `render_mode`/`rise`/`hscale` gate could both be deleted outright and the entire 135-test text_commit suite still passed. The marked-content gate — the single gate rejecting the most real-world shows (all 32 in `test-horizontal-texts.pdf`, 2364 in `test-complexed-layout.pdf`) — had zero coverage.
**Cause:** `test_text_commit_replay.py` builds the right fixtures (`80 Tz 3 Ts 2 Tr`, `/P <</MCID 0>> BDC … EMC`) but asserts only `show.hscale == 80.0` / `show.mc_depth == 1` — i.e. that the replay *observed* the state. Nothing asserted the planner *acted* on it. Meanwhile every case in `test_text_commit_tier0.py`'s parametrized rejection test varies only the **request** (replacement text, style/geometry overrides); the fixture document was never varied, so no structural gate was reachable from it. Sensor tested, switch untested.
**Fix:** Test the planner's return value, not the replay's fields: build one raw content stream per gate and assert `prepare_tier0_plan(...)` returns a `PlanRejection` with that gate's `RejectReason`. Confirm each new test is real by mutation — neuter the guard (`if False:`) and check that exactly the matching test fails. A green suite proves nothing about a gate no fixture reaches.
**File:** test_scripts/test_text_commit_structural_gates.py

## Two gates sharing one RejectReason let a test survive deletion of its own gate
**Area:** model/text_commit/plan.py (`FONT_FACE_UNAVAILABLE`, `UNSUPPORTED_TEXT_STATE`)
**Symptom:** A test pinning only `rejection.reason == FONT_FACE_UNAVAILABLE` for the "no font selected" gate still **passes** when that gate is deleted — a silently vacuous test.
**Cause:** `FONT_FACE_UNAVAILABLE` is emitted at two sites and `UNSUPPORTED_TEXT_STATE` at four. Deleting the `show.font_resource is None` check just lets control fall through to `registry.capability(page, None)`, which also returns `None` and re-emits the *same* reason with different detail text. The reason code alone cannot distinguish which guard fired.
**Fix:** Where several guards share a `RejectReason`, also pin a short stable substring of `PlanRejection.detail` (`"no font selected"` vs `"not resolvable"`; `"marked-content"` vs `"render_mode="` vs `"outside BT/ET"`). Additionally assert the fixture's `ShowOp` carries the intended off-nominal field *and no other* — otherwise the test can drift into a neighbouring gate and stay green. Verified by mutation: the detail assertion is the only thing that catches the `FONT_FACE_UNAVAILABLE` mutant.
**File:** test_scripts/test_text_commit_structural_gates.py (`_assert_only_off_nominal`)

## For a simple PDF font, `/Widths` overrides the font program — measuring advance from a face is wrong
**Area:** model/text_commit/fonts.py, plan.py (`_advance`)
**Symptom:** Tier 0 refused 29,526 of 38,540 corpus show ops (76.6%) with `font_face_unavailable`. All were one profile: unembedded TrueType Arial / Times New Roman / Courier New with WinAnsiEncoding — Word's default export. None is base-14 (base-14 is Helvetica/Times-Roman/Courier, *different* typefaces), so no face resolved and nothing could be measured.
**Cause:** advance was computed as `capability.face.text_length(...)`. But for a simple (non-CID) font the `/Widths` array **is** the layout contract: a conforming viewer advances by `Widths[code - FirstChar] / 1000 * font_size` and does not consult the font program's metrics. Every one of those fonts carried a complete `/Widths`, so the data was present all along and the engine was reading the wrong source.
**Fix:** Read `/Widths` (+ `/FirstChar`) and prefer it over any face. Measured proof that `/Widths` wins: embed a real `arial.ttf` as `/FontFile2` but write `/Widths` as all-1000 — MuPDF lays out **40.0pt** while the extracted face reports **23.32pt**. So this is a soundness *fix* for embedded fonts too, not only a widening for unembedded ones. Corollary worth internalising: a face resolved by *name* from the host system is a fact about the machine, not the document, so it is non-reproducible across machines — never let it decide a layout question the document already answered.
**File:** `model/text_commit/fonts.py` (`_read_width_table`, `FontCapability.advance_source`); tests in `test_scripts/test_text_commit_font_widths.py`

## `/Widths` proves an advance, not a glyph — trusting it as glyph evidence commits tofu
**Area:** model/text_commit/fonts.py (`FontCapability.missing_glyphs`)
**Symptom:** With advance sourced from `/Widths` and no face loaded, `missing_glyphs()` returned `""` for *any* text, so `encode_simple`'s coverage guard never fired and Tier 0 would commit a replacement whose glyphs do not exist — rendering as tofu boxes.
**Cause:** Conflating two different claims. A `/Widths` entry says a code has a horizontal advance; it says nothing about an outline existing. Subset fonts routinely declare widths across the whole `[FirstChar, LastChar]` range while embedding only the glyphs actually drawn. Guarding only against *zero* widths does not help — a positive `.notdef` or default width passes.
**Fix:** Keep glyph coverage as its own gate, exactly as the plan requires ("replacement glyphs exist in the source font encoding"). Without a face it is attestable only for an **unembedded, non-subset font from a closed allowlist of full-ASCII text families whose own descriptor does not flag it symbolic**. Note the first attempt at this fix — trusting any non-subset unembedded font, on the theory that a viewer substitutes a complete face — was itself wrong, and review caught it: if the named font *is* installed, the viewer uses that font rather than a substitute, so an unfamiliar name (barcode, icon, dingbat) can still render `.notdef`. Absence of a subset prefix is not glyph evidence; a closed family allowlist plus the document's own `/Flags` is. Note too that V0a–V0e cannot backstop any of this: raster identity is asserted *outside* a 2pt halo around the target, so tofu inside the edit region is invisible to verification — the check has to happen at plan time.
**File:** `model/text_commit/fonts.py` (`missing_glyphs`); tests in `test_scripts/test_text_commit_widths_hardening.py`

## A staleness fingerprint must cover whatever the plan was *measured* against, not just what it edits
**Area:** model/text_commit/inspect.py (`page_fingerprint`)
**Symptom:** After Tier 0 began measuring advance from `/Widths`, editing that table between prepare and commit left the page fingerprint unchanged, so a plan measured against the old widths still passed the freshness check and could commit.
**Cause:** the fingerprint hashed content streams, `page.get_fonts(full=True)` entries, and annotation/widget identity. That tuple reports the same metadata whether or not the width array changed, and the font *object* was never hashed. The fingerprint was built when advance came from a loaded face — a thing outside the document — so nothing in the document needed covering. Changing the measurement source silently widened what "stale" has to mean.
**Fix:** Hash the font object itself and, when `/Widths` is an indirect reference, the referenced object too. General rule: whenever a plan starts deriving a number from a new part of the document, extend the staleness fingerprint in the same change — the guard is only as good as its inputs, and its gaps are invisible until something mutates.
**File:** `model/text_commit/inspect.py` (`page_fingerprint`); test in `test_scripts/test_text_commit_widths_hardening.py`

## A tolerance that equals the quantum of its own measurement source stops being a tolerance
**Area:** model/text_commit/plan.py (`_ADVANCE_TOL_PER_PT`)
**Symptom:** Non-monotonic accept/reject on the *same* one-unit width difference — size 12 committed a 0.012pt shift, size 72 refused 0.072pt, size 600 committed a **0.600pt** shift. V0a–V0e passed all of it.
**Cause:** The advance tolerance was `1e-3 * font_size`, and one `/Widths` table unit is exactly `font_size / 1000` — algebraically identical. Against face-derived floats the tolerance absorbed genuine rounding noise; against integer `/Widths` the smallest representable difference lands precisely on the strict `>` boundary, so float representation, not design, decides the outcome.
**Fix:** Match the tolerance to the arithmetic of the source. `/Widths` advances are exact rational values (integer units scaled by size), so they need a float-noise tolerance (`1e-9 * size`), not the face's `1e-3 * size`. General rule: whenever a measurement source changes, re-derive the tolerance — one that happens to equal the source's quantisation step silently absorbs a full unit of real error while the comment still claims it "only absorbs rounding".
**File:** `model/text_commit/plan.py`; tests in `test_scripts/test_text_commit_widths_hardening.py`

## Word runs are stripped, so `" ".join` cannot reconstruct source whitespace
**Area:** model/pdf_text_edit.py (`_tier0_target_from_resolve`) → model/text_commit/inspect.py (`bind_source_text`)
**Symptom:** A Tier 0 edit on a line containing two or more consecutive spaces (`"Price is  100"`) always refused with `no_source_match` — the same code emitted when the text is genuinely absent from the page. Invisible to every corpus number, because `scripts/audit_tier_coverage.py` classifies *show operators*, not *edits*, and this stage sits above the planner.
**Cause:** `text_block_parsing.py:_finalize` ends each word run with `"".join(run["text_parts"]).strip()`, so a run never carries its surrounding whitespace — word boundaries come from geometric gap analysis, not from space characters. `_tier0_target_from_resolve` then rebuilds the show-op string as `" ".join(...)` over those runs, which is correct only when every gap in the source was exactly one space. `bind_source_text` demands exact byte equality (`s.decoded_bytes == target_bytes`), so any wider gap fails to bind. The reconstruction, not the document, was at fault — but the reason code blamed the document.
**Fix:** Do not let a *guess* be reported as a *finding*. `_tier0_target_from_resolve` now returns `_Tier0Target` carrying `joined_runs`, and a run-joined target whose only failure is `NO_MATCH` is re-labelled `TARGET_RECONSTRUCTION_UNVERIFIED` with a detail naming the join. Recovering these edits (reading the verbatim line text instead of rejoining runs) is still owed — the dict parse *does* preserve `"Price is  100"` verbatim, but mapping a run's `(block_idx, line_idx)` onto it crosses the rawdict↔dict index-alignment assumption in `_build_page_index` and does not help the single-run case (`"  Total  "` → run `"Total"`, which also fails to bind). Tracked in TODOS.md.
**File:** `model/pdf_text_edit.py` (`_Tier0Target`, `_reconstruction_aware_reason`); tests in `test_scripts/test_tier0_target_resolution.py`

## A redundant guard cannot be made mutation-SENSITIVE — check for subsumption before claiming a test pins it
**Area:** model/pdf_text_edit.py (`_tier0_target_from_resolve`), test design
**Symptom:** A new test asserting that members spanning two lines return `None` passed, but deleting the `any(s.block_idx != first.block_idx ...)` line-identity guard it claimed to pin left the entire suite green — the exact failure mode Task 10a was written to catch.
**Cause:** The guard is genuinely unreachable as a decision. `span_id` is built as `f"p{page}_b{block}_l{line}_s{idx}"` in **both** parsers, so a member on another line always carries an id absent from `first`'s `line_run_ids`; the full-line set-equality check immediately below refuses the same input first. With a single member, `any(...)` compares `first` to itself and is always `False`.
**Fix:** Report it rather than inventing a fixture that "proves" a redundant branch. A guard that no mutation can kill is either dead or subsumed, and the honest outcome is to say which — writing a test that passes for a different reason is worse than having no test. Kept as cheap defence-in-depth; the test's docstring now says it pins the *behaviour*, not that line.
**File:** `test_scripts/test_tier0_target_resolution.py` (`test_shape_multi_line_members_are_refused`)

## `TARGET_IN_FORM_XOBJECT` must be target-scoped — page-scoped labeling mislabels almost every miss on real corpora
**Area:** model/text_commit/inspect.py (`bind_source_text`)
**Symptom:** In the 2026-08-01 funnel measurement, 34,552 bind failures carried `TARGET_IN_FORM_XOBJECT`, but a byte-scan of every invoked Form XObject confirmed only 1,827 (5.3%) of those targets actually live in one. 409/415 corpus pages (98.6%) invoke *some* Form XObject (a logo, a bullet glyph), so the label was eligible to fire on virtually any miss.
**Cause:** The reclassification asked a *page* question — "does this page invoke any XObject?" — where a *target* question was needed — "is this target's text inside an invoked XObject?".
**Fix (WS-D 2026-08-03):** `_target_in_invoked_form_xobjects` replays each Form XObject from `page.get_xobjects()` (one level) and byte-checks the target; only a confirmed hit keeps the label, otherwise `NO_MATCH`.
**File:** model/text_commit/inspect.py (`bind_source_text`)

## Calling `bind_source_text` per target re-replays the whole page — prohibitively slow for multi-target sampling
**Area:** model/text_commit (measurement/tooling)
**Symptom:** 50 per-target calls against one 2-page fixture (`test-complexed-layout.pdf`) exceeded a 60-second timeout — not "slow", unusable. Measured, not theoretical.
**Cause:** Every call runs `read_page_streams` + `replay_page_streams` from scratch; replay cost scales with page operator count, so sampling N targets on a page pays the full page parse N times.
**Fix:** Replay once per page, then bind each target against the cached replay (`scripts/measure_tier_funnel.py:_bind_against_replay`, cross-checked with 0 mismatches against the real function over 618 targets). The same cost structure is why `preview.py` re-running `prepare_tier0_plan` per keystroke is the known perf risk.
**File:** `scripts/measure_tier_funnel.py`

## `tobytes(encryption=KEEP)` reorders dictionary keys the first time it serializes a disk-loaded object — breaking the scratch-first fingerprint self-check
**Area:** model/text_commit/engine.py (`prepare` → `_build_scratch_copy`) / inspect.py (`page_fingerprint`, `_update_font_dependencies`)
**Symptom:** On `test_files/test-large-file.pdf`, `TieredCommitEngine.prepare()` failed its own scratch-first self-consistency check on the *first* attempt against any genuinely Tier-0-eligible target: the pre-scratch `page_fingerprint` never matched the scratch copy's.
**Cause:** PyMuPDF's `tobytes(encryption=KEEP)` re-serializes a disk-loaded object's dictionary with reordered keys (same keys, same length, different order) the first time through; it is idempotent after that one round trip. `_update_font_dependencies` hashed `xref_object()` strings verbatim, so a cosmetic reorder read as a content change. Unit tests never hit this because synthetic fixtures are built via `fitz.open()` + `new_page()` — never loaded from disk. `page.get_fonts(full=True)`, decoded content-stream bytes, and annot/widget geometry are all round-trip-stable; only the raw serialized object string was not.
**Fix (landed):** `_update_font_dependencies` now folds `_canonical_object_digest(doc, xref)` — `sorted(doc.xref_get_keys(xref))`, then `doc.xref_get_key(xref, key)` per key, joined with field/record separators — instead of `doc.xref_object(xref).encode("utf-8")`. Order-independent by construction, so the MuPDF reorder no longer moves the digest; a real dependency mutation (e.g. `/FirstChar`) still does (see `test_page_fingerprint_detects_font_dependency_mutation`). The earlier workaround in `scripts/benchmark_text_commit_baseline.py` (`_canonicalize_once`) is now superseded by the production fix for this call path, though it stays in place there as its own dedicated canonicalization for the benchmark script's use.
**File:** `model/text_commit/inspect.py`; tests in `test_scripts/test_text_commit_fingerprint_roundtrip.py`

## Text-space and page-space quantities must not mix in bbox/halo math — under scale the error is a silent false ACCEPT
**Area:** model/text_commit/plan.py (fallback `target_bbox`)
**Symptom:** With `target_bbox=None` and a uniformly scaled Tm (`a==d==0.5`), the fallback bbox came out exactly 2× too wide — and the dangerous direction is `s<1`, where the halo *inflates*: `verify` proves raster identity only *outside* the halo, so an inflated halo silently absorbs out-of-halo corruption, invisible to V0a–V0e. A second instance: `/UserUnit != 1` left the halo off by the page scale. A third: `/Rotate 90/270` left a horizontal halo while pixmap ink ran vertically — because `page.transformation_matrix` omits `/Rotate` in PyMuPDF 1.27 (only `page.rotation_matrix` supplies it); rawdict stays in unrotated space while `get_pixmap` is visual.
**Cause:** Mixing text-space advance/size with page/visual coordinates without applying every matrix between them. Assuming `transformation_matrix` alone is the "full page transform" is wrong under `/Rotate`.
**Fix:** Build the rect in user space, map through `_page_visual_matrix` = `transformation_matrix * rotation_matrix`. Same matrix used by `_grown_verify_bbox`. Scale/`/UserUnit`/`/Rotate` fixtures in `test_text_commit_structural_gates.py`.
**File:** `model/text_commit/plan.py`; tests in `test_scripts/test_text_commit_structural_gates.py`

## PyMuPDF `insert_text` emits `[<...>] TJ` — an array, never a hex `Tj`
**Area:** test fixtures for text-commit gates
**Symptom:** A rejection test believed to cover hex-string `Tj` (`test_planner_rejects_hex_tj_pages_as_not_literal`) never did: `insert_text` output is a one-element hex-string *array* under `TJ`, so the test failed on the *operator* half of the gate and the string-kind half had zero coverage until D1 hand-built a real `... <48656c6c6f> Tj ...` stream.
**Cause:** Assuming the library's serialization matches the operator you meant to test, without dumping the stream. A rejection test named after a gate it never reaches is worse than no test — it reads as coverage.
**Fix:** Dump and assert the fixture's actual stream form (`show.operator`/`show.string_kind`), and name the test after the gate that really fires (now `test_planner_rejects_tj_array_pages`). Hex-`Tj` coverage requires a hand-built content stream.
**File:** `test_scripts/test_text_commit_tier0.py`, `test_scripts/test_text_commit_structural_gates.py`

## `pytest … | tail` reports tail's exit code — a hard interpreter abort can read as a passing run
**Area:** test harness / CI hygiene
**Symptom:** A full-suite run ended in `Fatal Python error: Aborted` inside `test_page_reorder.py`, but the pipeline exit code was 0 (tail's) and the visible tail showed only the post-abort faulthandler dump — nearly reported as green.
**Cause:** A pipe's exit status is the last command's. This is distinct from the documented-benign `0x80040155` COM dump (PITFALLS.md:58), after which the suite still prints a summary; "Fatal Python error" with **no summary line** is a real abort. Trigger here was contention: `test_page_reorder.py` (Qt drag-and-drop, offscreen) aborts natively when another pytest run or heavy PyMuPDF script is in flight, and passes 20/20 in isolation.
**Fix:** Redirect suite output to a file and read the summary line (or use pipefail); never overlap full-suite runs with other Python/PyMuPDF workloads on this machine. Second observation (2026-08-01, same day): the abort also fired on a run whose only companions were trivial git/markdown/ripgrep operations, then a fully isolated re-run passed 2135/2135 — so treat the trigger as "anything else at all, or plain flakiness", and on an abort re-run in isolation before suspecting the code change.
**File:** process note; no code change

## `doc.xref_get_keys(xref)` returns `[]` for a non-dictionary object — indistinguishable from an empty dictionary
**Area:** model/text_commit/inspect.py (`_canonical_object_digest`)
**Symptom:** Caught in review before it shipped, not in production: an order-independent digest built as "hash `sorted(xref_get_keys(xref))` + `xref_get_key` per key, else hash nothing" silently drops the *content* of any indirect object that is an array or scalar (a PDF `/Widths` table is exactly this — an indirect array of numbers, no dictionary keys at all) — mutating it moves nothing in the digest, reintroducing the "fingerprint blind to /Widths" defect `test_page_fingerprint_covers_the_width_table` already guards for the *inline* case (TODOS.md Codex round R5).
**Cause:** `xref_get_keys` enumerates dictionary keys; arrays, numbers, names, and strings have none, so it returns `[]` for them too — the same value a genuinely empty dictionary (`<<>>`) produces. "No keys" cannot be read as "nothing to hash" without silently going blind to every non-dict indirect object a font dictionary can point at.
**Fix:** When `xref_get_keys` is empty, fall back to hashing the raw `doc.xref_object(xref)` string (whitespace-normalized) instead of nothing. Safe specifically because the round-trip reordering this digest exists to survive is a *dictionary*-key phenomenon — arrays/scalars have a fixed element order and were measured stable (byte-identical, no normalization even needed) across the same `tobytes(KEEP)` round trip that reorders dict keys.
**File:** `model/text_commit/inspect.py` (`_canonical_object_digest`); test in `test_scripts/test_text_commit_widths_hardening.py::test_page_fingerprint_covers_an_indirect_widths_array_by_content`

## A mutation fixture can be subsumed by a sibling guard — rotation does not pin `b==c==0`, a mirror does not pin `a>0`
**Area:** test_scripts/test_text_commit_structural_gates.py (`_uniform_scale` gates)
**Symptom:** Plausible-looking fixtures pinned nothing: a 90° rotation has `a==0`, so deleting the `b==c==0` check still rejects it via `a>0`; a mirror (`a==-d`) is rejected by `a==d` before `a>0` is ever consulted. Both mutants survived those fixtures.
**Cause:** In a conjunction of guards, a fixture only pins the guard that is the *sole* reason it is rejected. Off-nominal in the mutated dimension is not enough — it must be nominal in every other dimension the earlier guards check.
**Fix:** Pin `b==c==0` with `a==d>0` plus off-diagonals set; pin `a>0` with a point reflection (`a==d<0`). Both confirmed by actually running the mutants — reasoning about which fixture kills which mutant was wrong twice here. Complements the "redundant guard cannot be made SENSITIVE" entry above.
**File:** `test_scripts/test_text_commit_structural_gates.py`

---

## Same-line successor merges into the target's own rawdict span without an intervening Tf/Tm/T*

**Area:** `model/text_commit` (rawdict-derived bboxes) / test fixtures
**Symptom:** Two Slice 1 red tests (neighbour-word and single-narrow-glyph growth-refusal fixtures) failed with engine.prepare() returning an accepted PreparedEdit instead of the expected GROWTH_REGION_NOT_BLANK PlanRejection.
**Cause:** `page.get_text('rawdict')` groups consecutive Tj shows sharing font state into ONE span when nothing (Td/Tm/T*/Tf) separates them, so `_span(page, TARGET)['bbox']` returned the union of the target AND its same-line successor's bbox, not the target's own — feeding an already-too-wide box into target_bbox made the 'occupied growth zone' look like it belonged to the target itself.
**Fix:** Added a char-level `_target_bbox(page, probe)` helper that unions only the rawdict characters belonging to the probe's own first occurrence (mirroring how `_first_char_origin` already had to work char-level for the same reason), and used it in place of the merged span bbox for the two affected fixtures.
**File:** `test_scripts/test_text_commit_tier1_slice1.py`

---

## plan -> patch -> verify -> plan runtime import cycle

**Area:** `model/text_commit`
**Symptom:** Importing `model.text_commit.plan` would raise ImportError as soon as plan.py needs patch.py's Tier 1 composite builder.
**Cause:** `patch.py` imports `verify.py` (for `prove_source_resource_reuse`); `verify.py` previously imported `PreparedEdit` from `plan.py` at runtime; `plan.py` now imports `patch.py` — closing the cycle.
**Fix:** `verify.py`'s `from model.text_commit.plan import PreparedEdit` moved under `if TYPE_CHECKING:` (safe because verify.py already has `from __future__ import annotations` and only uses `PreparedEdit` in annotations).
**File:** `model/text_commit/verify.py`

---

## mypy loses None-narrowing for a dataclass field re-accessed in a different function

**Area:** `model/text_commit/plan.py`
**Symptom:** mypy arg-type error passing `show.font_resource` (str | None) to `PreparedEdit(font_resource=...)` (str) inside the newly extracted _build_tier0/_build_tier1, even though the None case was already refused earlier.
**Cause:** The `if show.font_resource is None: return ...` guard runs inside `_classify_common`; `_build_tier0`/`_build_tier1` receive the same ShowOp via a stored `_ClassifiedTarget.show` field in a different function scope, and mypy does not carry narrowing across that boundary.
**Fix:** Added `assert show.font_resource is not None` at the top of both `_build_tier0` and `_build_tier1` — a type-narrowing restatement of an already-enforced invariant, not a new runtime check.
**File:** `model/text_commit/plan.py`

---

## Widening V0c's non-target-span-origin comparison to verify_bbox would false-reject every honest growth commit

**Area:** `model/text_commit/verify.py`
**Symptom:** The design's literal wording ('every use of prepared.target_bbox_page replaced by the verify_bbox parameter') would, if applied to the `_span_origins(...) != pre_state.nontarget_origins` comparison, spuriously report 'non-target span geometry changed' on every accepted Tier 1 growth commit.
**Cause:** `capture_page_state` always computes `pre_state.nontarget_origins` by excluding `target_bbox_page` (the narrow box), never `verify_bbox_page`; comparing that pre-set against a post-set excluded by the wider `verify_bbox` would silently drop any real neighbour span sitting between the two boxes from the post-set while it is still present in the pre-set.
**Fix:** `_verify_patch_postconditions` widens only the V0c extraction clip (halo_rect) and the V0d raster-diff halo to `verify_bbox`; the V0c span-origin comparison stays pinned to `prepared.target_bbox_page` on both sides, matching what `capture_page_state` actually computed.
**File:** `model/text_commit/verify.py`

---

## Preview verification must capture pre-patch state and reuse the session scratch

**Area:** `model/text_commit/preview.py`, `model/text_commit/verify.py`

**Symptom:** A preview either falsely rejects a valid growth candidate as
occupied or adds one full-document serialization/open per keystroke.

**Cause:** Growth occupancy is a PRE-EDIT proof, so calling
`capture_page_state(...)` after `apply_patchset(...)` counts the replacement
glyphs as pre-existing. Conversely, invoking live V0e's KEEP-encrypted
serialization probe for every preview generation defeats the one
session-scratch performance contract.

**Fix:** Capture `PageState` before applying the patch, run the same V0a–V0d
checks on the already-open session scratch, and use that scratch's
reopenability certificate for preview V0e. Live commit continues to perform
the real KEEP-encrypted serialize/reopen probe.

**File:** `model/text_commit/preview.py`, `model/text_commit/verify.py`

---

## High-fidelity stale undo must refuse, not snapshot-restore

**Area:** `model/edit_commands.py` (`EditTextCommand.undo`)
**Symptom:** After a Tier 0/1 commit, an out-of-band stream drift made the inverse PatchSet stale; undo silently fell through to `page-snapshot` restore, rewriting annotation xrefs and discarding the drifted page state while still popping the command off the undo stack.
**Cause:** Undo treated `StalePlanError` as "use the snapshot fallback", while redo already refused with `STALE_PLAN` and zero mutation. Asymmetric policy.
**Fix:** When a high-fidelity inverse is stale → `EditTextResult.STALE_UNDO`, set `CommitStatus.STALE_PLAN`, mutate nothing, return `False` so `CommandManager.undo` retains the command. Snapshot restore remains only for non-high-fidelity commands.
**File:** `model/edit_commands.py`; test `test_undo_after_external_change_fails_stale_without_mutation`

---

## PDFModel property setters must getattr-guard legacy slots — tests build models via `__new__`

**Area:** `model/pdf_model.py` (session-fallback properties), `test_scripts/`
**Symptom:** Six previously-green tests (`test_resolve_target_mode`, `test_snapshot_restore`, `test_tier0_target_resolution`) failed mid-workstream with `AttributeError: 'PDFModel' object has no attribute '_legacy_doc'` / `'_StubModel' object has no attribute 'get_tiered_commit_engine'` — caught only by the *full* suite, not the targeted text-commit runs.
**Cause:** Several unit tests construct model shells with `PDFModel.__new__(PDFModel)` (skipping `__init__`) or hand-rolled `_StubModel` doubles. Turning `doc` into a property whose setter touches `self._legacy_doc`, and routing `_attempt_tiered_commit` through `model.get_tiered_commit_engine()`, broke every such double even though production code was correct.
**Fix:** Setters/readers on session-fallback properties use `getattr(self, "_legacy_*", None)` (same pattern as `_active_session`), and test doubles that feed `_attempt_tiered_commit` must expose `get_tiered_commit_engine()`. When changing `PDFModel`'s attribute surface, grep tests for `PDFModel.__new__` first — the targeted suite will not warn you.
**File:** `model/pdf_model.py` (`doc` setter, `_active_session`); `test_scripts/test_tier0_target_resolution.py` (`_StubModel`)

---

## A reference sample taken inside the region it is proving is self-referential — the load-bearing rule is ink visibility

**Area:** `model/text_commit/verify.py` (`prove_growth_region_blank`)
**Symptom:** A growth zone filled solid black was accepted as blank, so a Tier 1 commit grew the target into ink the verifier had just certified as empty. The "background reference" gate added to stop exactly this was **inert**: monkeypatching every occupancy gate to a no-op left all five growth tests green.
**Cause:** Two compounding errors. (i) The reference colour was sampled from the target's own tail — inside the band being widened — so on a black background the reference *was* the ink, and "growth matches reference" was a tautology. (ii) The gate was fail-open on ambiguity (no reference resolvable ⇒ accept). Correcting (i) alone is not enough: a large black fill also covers every candidate reference point outside the target, so reference-comparison still accepts.
**Fix:** Rebuild as a background-*surface* proof with three independent parts. `background_reference_points` samples left/above/below the target, provably disjoint from the widened halo. `_target_background_rgb` takes the strict-majority colour inside the target's own bbox and returns whether the target's ink is *visible* against it — a 100% majority means the glyphs are indistinguishable from their background, i.e. ink-on-same-ink, which is refused outright. That ink-visibility rule, not the reference comparison, is what kills black-on-black. Ambiguity refuses everywhere; a pass requires an affirmative match. Occupancy gates (`get_drawings`/`get_images`/`sh` scan) are kept only as cheap early-outs and the raster proof is pinned standing alone with them neutered.
**File:** `model/text_commit/verify.py`; tests `test_growth_into_a_black_shading_xobject_region_is_rejected`, `test_growth_into_a_uniform_band_that_mismatches_the_page_background_is_rejected`

---

## `sh` inside a Form XObject is invisible to every page-level ink reader — a mechanism blocklist only refuses the mechanisms it enumerates

**Area:** `model/text_commit/verify.py` (growth occupancy gates)
**Symptom:** A shading operator painting the growth zone solid black was reported as "no drawings, no images, no shading" by all three occupancy probes.
**Cause:** `page.get_drawings()`, `page.get_images()`, and the `sh` scan over `read_page_streams` all see only the page's *own* content stream. Ink painted inside an invoked Form XObject is reachable by none of them. Enumerating ink mechanisms is a blocklist, and a blocklist cannot be complete over a format that lets any operator nest one level down.
**Fix:** Do not prove absence-of-known-ink-sources; prove the rendered surface. The raster background proof reads what MuPDF actually painted, so nesting is irrelevant. Occupancy checks remain as cheap early-outs and must never be the sole gate.
**File:** `model/text_commit/verify.py`

---

## `get_text("dict"/"rawdict")` geometry is UNROTATED page space — comparing it against a visual-space bbox passes on every unrotated page and is wrong on every `/Rotate` page

**Area:** `model/text_commit/verify.py` (V0c/V0d), `model/pdf_text_edit.py` (target derivation)
**Symptom:** No tiered commit had **ever** succeeded on a `/Rotate 90/270` page — a pre-existing defect (Defect C) found only when a rotation-parity pass went looking. Every such commit failed verification, and the same mismatch in the other direction is a false-accept risk.
**Cause:** Dict/rawdict extraction reports coordinates in unrotated page space, while `page.get_pixmap()` and `page.rect` are visual space (the same PyMuPDF quirk already documented for annotation geometry). V0c/V0d compared rawdict span origins and bboxes against a visual-space `target_bbox_page`; the caller-supplied `target_bbox` from `pdf_text_edit.py` was itself unconverted. On an unrotated page the two spaces coincide, so every test and every real edit agreed — the bug is invisible until `/Rotate` is non-zero.
**Fix:** Convert at the boundary, once: `_dict_space_to_visual` (`pdf_text_edit.py`) maps dict-space origin/bbox through `page.rotation_matrix` alone (dict coordinates already carry the CropBox/UserUnit part of `transformation_matrix`; only `/Rotate` is missing — see its docstring) before anything visual-space consumes it, and `verify.py` does the same on the read side. `inspect._origin_in_page_space` composes `rotation_matrix` too. Treat rawdict origin as *not* a visual-space oracle. When adding a geometry comparison, name the space of both operands in the assertion.
**File:** `model/pdf_text_edit.py` (`_dict_space_to_visual`), `model/text_commit/verify.py`, `model/text_commit/inspect.py`; tests `test_full_tiered_commit_succeeds_on_rotated_page[90/270]`, `test_bind_origin_page_follows_page_rotate`

---

## A verified-candidate cache keyed on a content token still needs the policy gates re-run at commit time

**Area:** `model/pdf_text_edit.py` (`_attempt_tiered_commit` cached-candidate branch), `controller/pdf_controller.py`
**Symptom:** With a preview candidate cached by `plan_token`, a commit that also carried a style change or a dragged `new_rect` reused the cached candidate and **silently discarded the drag** — UI-reachable, no refusal, no warning. Separately, the cache was populated before the preview PNG was validated.
**Cause:** The token's preimage covers the *candidate's* semantics, not the *request's*. Style/geometry overrides arrive with the commit request and never entered the token, so an unequal request hashed equal. And document-level facts checked during a fresh prepare (here: shared content streams) were skipped entirely on the cache-hit path — a cache that bypasses gates is a gate.
**Fix:** The cached branch refuses on `style_overrides.changed` or a supplied `new_rect` and falls through to a fresh prepare (which then produces an honest refusal reason), and re-runs `find_pages_sharing_content_stream` before applying. The controller caches only after the PNG decodes. Rule: a cache hit may skip *work*, never *checks*.
**File:** `model/pdf_text_edit.py`, `controller/pdf_controller.py`; `test_scripts/test_text_commit_candidate_identity.py` (`TestCachedCandidateBypassesPolicyGates`)

---

## A certificate that reads its evidence from the post-patch document proves nothing

**Area:** `model/text_commit/verify.py` (V0e), `model/text_commit/preview.py`
**Symptom:** Preview's V0e "reopen probe" passed unconditionally — it compared a page count read on the patched document against a page count read on that *same* patched document.
**Cause:** The pre-patch value was never captured, so the comparison was `x == x`. A tautological assertion is worse than a missing one: it reports a green certificate.
**Fix:** `PageState` captures `page_count` **pre**-patch. Preview gets a real per-session KEEP round-trip (`_live_keep_round_trip`) whose single `tobytes(KEEP)` + reopen feeds both the probe verdict and the session snapshot, preserving the one-scratch-per-session keystroke budget; `PreviewSessionInput.reopen_probe_ok` defaults to `False` (fail-closed). When writing a verification step, state which side of the mutation each operand is read from.
**File:** `model/text_commit/verify.py`, `model/text_commit/preview.py`

---

## `TJ` kern advances are materialized as synthesized spaces in dict extraction — verbatim dict text is not the source string

**Area:** `model/pdf_text_edit.py` (`_dict_line_for_runs`)
**Symptom:** Recovering whitespace-collapsed edits from the dict parse (which preserves `"Price is  100"` where joined word runs cannot) *raised* the `TARGET_RECONSTRUCTION_UNVERIFIED` rate on the dominant corpus document rather than converting it.
**Cause:** MuPDF materializes a wide `TJ` kern as a space character in the extracted text. That space exists in the extraction and not in the content stream, so the dict line is a reconstruction too — a different one, failing byte-binding for a different reason.
**Fix:** The dict line is used only when a runtime content-**and**-geometry alignment proof holds; otherwise the target stays run-joined. The rate rise is an honesty effect, not a regression: previously these were mislabeled `NO_MATCH`, and preview now relabels bare `NO_MATCH` to `TARGET_RECONSTRUCTION_UNVERIFIED` symmetrically with commit. Do not read either extraction as the source string without proving it against the stream.
**File:** `model/pdf_text_edit.py` (`_dict_line_for_runs`, `_Tier0Target.source_kind`), `model/text_commit/preview.py`

---

## `pytest test_scripts/` in one invocation hangs at PySide6 interpreter teardown — run the suite chunked

**Area:** test harness (`.venv`, PySide6)
**Symptom:** A whole-suite single invocation stops producing output after the last test and never exits; killing it loses the summary line, so the run reads as "no result" rather than "pass".
**Cause:** Pre-existing, environment-level: interpreter shutdown with the accumulated Qt state of 200+ test modules in one process. Not caused by, and not fixed by, any change in the text-commit engine.
**Fix:** Split `test_scripts/test_*.py` into ~4 alphabetical chunks and run one `pytest` invocation per chunk, summing the reported counts. Never quote a full-suite number from a run whose summary line you did not see (cf. the `| tail` pitfall above — a hard abort can read as a passing run).
**File:** — (harness); chunked runner pattern used for every Task 11 closure gate

## `lex_content_stream` materialized the full token list — a dense page stream is an in-app OOM

**Area:** `model/text_commit` (pdf_lexer, replay)
**Symptom:** prepare/preview on a vector-heavy page allocated GBs and stalled for minutes: a measured 8 MiB synthetic stream peaked at 1.16 GB RSS; a real ~72 MB decoded stream became ~54.7M `StreamToken`s ≈ 10 GB and ~115 s before the first show op was even bound. The GUI render pipeline was innocent (same document opens at ~470 MB).
**Cause:** the lexer returned `list[StreamToken]` (~0.77 tokens/byte at ~174–202 B/token incl. list+GC overhead), fully materialized before replay read token one; about half are WHITESPACE trivia that replay discards on sight.
**Fix:** Task 12 P0-B converted the lexer to a generator (callers needing random access wrap in `list()`), and P0-A added a summed-size budget `max_decoded_bytes` (default 4 MiB, `None` disables) at the single production chokepoint `replay_page_streams`, refusing BEFORE tokenization with the stable reason `content_stream_too_large_for_safe_replay`. Post-fix the same 8 MiB walk peaks at ~26 MB, but latency still scales ~1 s/MiB — the guard survives as a latency ceiling, not just OOM defense.
**File:** `model/text_commit/pdf_lexer.py`, `model/text_commit/replay.py`

## A resource refusal routed through `malformed` gets re-labelled — refusals need their own channel

**Area:** `model/text_commit` reason propagation (replay → inspect → plan)
**Symptom:** if the replay guard had signalled via `malformed=True`, the user-facing reason would have read `malformed_stream`; via an empty `shows` it would have read `no_source_match` — which `_reconstruction_aware_reason` can further rewrite into `target_reconstruction_unverified` on run-joined targets. Two hops, two lies.
**Cause:** `bind_source_text` legitimately collapses `replay.malformed` into `MALFORMED_STREAM`, and empty candidate lists into `NO_MATCH`; any new refusal class that reuses those channels inherits their labels.
**Fix:** a distinct `PageReplay.refusal_reason` field, surfaced verbatim by `bind_source_text` BEFORE the malformed check; `test_text_commit_replay_guard.py` pins verbatim survival all the way to `PlanRejection`. The field only works if EVERY consumer checks it: the Form-XObject deconfliction scan was missed on day one and collapsed refusals into `NO_MATCH` until the same-day adversarial review caught it. Any new consumer of `PageReplay` must handle `refusal_reason` before reading `shows` — the tri-state `_target_in_invoked_form_xobjects` (`True`/`False`/`None`=unprovable) is the pattern. `replay_page` (`inspect.py`) has no production caller today but carries the same trap for whoever calls it next.
**File:** `model/text_commit/replay.py`, `model/text_commit/inspect.py`

## ctypes `GetProcessMemoryInfo` silently zeroes without HANDLE restype (64-bit truncation)

**Area:** test harness (subprocess memory measurement)
**Symptom:** the call returns 0 with an all-zero struct; `GetLastError()` = 6 (ERROR_INVALID_HANDLE) — peak-RSS readings of 0 that can slip through as "under threshold" if unasserted.
**Cause:** ctypes defaults every restype to `c_int`, so `GetCurrentProcess()`'s 64-bit pseudo-handle (-1) truncates to 32 bits before being passed to `K32GetProcessMemoryInfo`.
**Fix:** set `GetCurrentProcess.restype = wintypes.HANDLE` and full argtypes/restype on `K32GetProcessMemoryInfo`; assert walk-coverage side-channels (`token_count`, `last_end == stream_bytes`) so a zeroed reading cannot masquerade as a pass.
**File:** `test_scripts/_streaming_memory_child.py`

## A GUI notice keyed only on outcome status fires under the shipped default too — gate on the fallback chain shape, not just the status enum

**Area:** `controller/pdf_controller.py` (Task 12 P0-C degrade visibility)
**Symptom:** a naive `if outcome.status is DEGRADED_COMMITTED: notify()` hookup would warn on literally every successful edit under the SHIPPED DEFAULT (`TextCommitSettings(engine="legacy")`), because the legacy engine's own success path (`legacy_commit_outcome()`, `dto.py`) honestly records `DEGRADED_COMMITTED` with chain `("legacy",)` — that status means "this is a legacy commit" for the default engine, not "a higher tier was attempted and failed." All 8 first-draft GUI tests constructed `TextCommitSettings(engine="tiered")` only, so this gap was invisible until an adversarial review asked "what does the default configuration do."
**Cause:** `CommitStatus.DEGRADED_COMMITTED` is overloaded — it means both "the baseline legacy engine, as configured" and "a real fidelity loss from an attempted fallback," and only `fallback_chain`'s *shape* distinguishes them.
**Fix:** gate the notice on `fallback_chain != ("legacy",)` (i.e. a chain with more than one element, meaning something higher was tried first), not on `status` alone. Any new DEGRADED_COMMITTED consumer must make the same distinction — write a test against `TextCommitSettings()` (bare defaults), not only `engine="tiered"`.
**File:** `controller/pdf_controller.py` (`_is_notifiable_degrade`)

## A per-command flag reset at only one entry point leaks into sibling commit paths

**Area:** `controller/pdf_controller.py` (Task 12 P0-C degrade visibility)
**Symptom:** `_last_edit_degraded` was reset only at `edit_text()` entry. A degraded edit finalized via a path that never consumes the flag (e.g. `FOCUS_OUTSIDE`/`APPLY` finalize reasons) left it `True`; a LATER, unrelated commit through a sibling method (`add_textbox`, `move_text_across_pages`) that never touches the flag would still trigger the View's mode-switch consumer, silently eating that later commit's success toast.
**Cause:** treating "reset the flag where I added the notify hookup" as sufficient, instead of auditing every method that can produce a `COMMITTED` result the View's shared finalize path (`text_editing.py` `_finalize_text_edit`) will consume.
**Fix:** every commit-producing controller entry point resets the flag at ITS OWN entry (`edit_text`, `add_textbox`, `move_text_across_pages`), even the ones that can never themselves degrade — the reset is about not inheriting stale state from a DIFFERENT interaction, not about that method's own outcome.
**File:** `controller/pdf_controller.py`

## Redo re-running the full commit pipeline must NOT re-fire a one-shot GUI notice

**Area:** `controller/pdf_controller.py` / `model/edit_commands.py` (Task 12 P0-C degrade visibility)
**Symptom:** an adversarial reviewer flagged that `EditTextCommand.redo()` for a legacy-tier command falls through to a full `model.edit_text()` re-run (no retained forward patchset for Tier 2), re-recording a fresh `DEGRADED_COMMITTED` outcome — and asked whether that should re-notify.
**Cause / resolution:** it correctly should NOT. "Exactly one notice per degraded edit" was already satisfied when the edit first committed; redo reproduces the SAME already-disclosed degrade against the undo-restored snapshot, so firing a second notice would violate the invariant it looks like it's protecting, not satisfy it. `controller.redo()` never calls the notify hookup (it lives only in `edit_text()`), which is correct by construction, not by accident.
**File:** `controller/pdf_controller.py` (documents intended behavior; no code change)

## An acceptance gate's style-override flag must be scoped to what the app can actually request

**Area:** `test_scripts/semantic_fidelity_gate.py` (Task 12 P0-C semantic fidelity gate)
**Symptom:** `style_override_requested=True` silenced ALL four style checks (font identity, size, color, baseline) as one bundle, so a size-only style override commit that also happened to recolor the replacement or drop its baseline by several points would pass — even though the app's one and only override producer (`build_style_overrides`, `view/text_editing.py`) hardcodes `color=None` and has no baseline control at all.
**Cause:** modeling "was a style override requested" as a single bool guarding every style-adjacent check, instead of scoping the silence to the specific fields an override can actually touch.
**Fix:** split the guard — `style_override_requested` now silences only `FONT_IDENTITY_CHANGED`/`FONT_SIZE_CHANGED`; `COLOR_CHANGED`/`BASELINE_SHIFTED` stay live unconditionally, since neither is ever a requestable outcome in this app.
**File:** `test_scripts/semantic_fidelity_gate.py`

## A two-pass preflight-then-commit consent design can't see a commit-stage-only failure in time

**Area:** `model/pdf_text_edit.py` (Task 12 P0-C phase 2 consent flow — design-time finding, not a shipped bug)
**Symptom:** the first design considered for pre-commit fallback consent was a Controller-side preflight — classify the fallback need read-only, show the confirm dialog, THEN call the existing unchanged `model.edit_text()`. It cannot detect the case where `engine.prepare()` succeeds on the scratch copy but live verification then fails inside `engine.commit()` — the exact case the user's own suggested test name (`test_commit_stage_fallback_confirmation_uses_coded_chain_only`) targets.
**Cause:** that information does not exist until `engine.commit()` actually runs, and running `commit()` during a "just checking" preflight is unsafe on the SUCCESS branch — a tier0/1 win there is a real, irreversible mutation, so the "real" `edit_text()` call afterward would re-resolve text the preflight had already replaced (double-edit corruption).
**Fix:** pivot to a Qt-free callback (`confirm_fallback: Callable[[tuple[str, ...]], bool] | None`) injected into `model.edit_text()` itself, invoked synchronously at the exact point the existing code already falls through to the legacy engine — reachable regardless of which stage (prepare or commit) produced the fallback reason, because both are proven zero-mutation-on-failure by construction (`engine.commit()` reverts internally before returning). No staleness/consent-token binding needed either: the callback fires with zero time gap between "ask" and "act".
**File:** `model/pdf_text_edit.py`, `model/edit_commands.py`, `controller/pdf_controller.py`

## A "was this command ever confirmed" flag must check what actually happened, not just that execute() succeeded

**Area:** `model/edit_commands.py` (Task 12 P0-C phase 2 — adversarial verification finding, high severity)
**Symptom:** `EditTextCommand._fallback_ever_confirmed` was set `True` after ANY successful `execute()`, including a clean Tier 0/1 win where `confirm_fallback` was never invoked at all (nothing needed consent). A legacy-tier command with no retained forward patchset re-runs the FULL `model.edit_text()` pipeline on every `execute()` call (including redo) — if a LATER `execute()` of that same command genuinely needed a fallback (e.g. the page's Tier 0 eligibility changed since the first call, via an out-of-band mutation like OCR that bypasses `command_manager` entirely and so never clears a stale redo entry), the flag would already be `True` and the confirm callback would be silently skipped — a legacy-fidelity mutation committed with zero prompt, on a command the user only ever consented to as a high-fidelity edit.
**Cause:** the flag conflated "this command has run to completion once" with "the user was actually asked about a fallback and agreed" — those coincide for the common case (fallback needed and confirmed) but not for a genuine Tier 0/1 success, which never calls the callback at all.
**Fix:** extracted the existing chain-shape check (`PDFController._is_notifiable_degrade`) into a shared, Qt-free Model-layer helper (`model.text_commit.dto.is_real_fallback_commit`) and gated `_fallback_ever_confirmed = True` on it instead of on bare `EditTextResult.SUCCESS`; the Controller's own check now delegates to the same helper so the two decisions about the same outcome shape can never drift apart again.
**File:** `model/edit_commands.py`, `model/text_commit/dto.py`, `controller/pdf_controller.py`

## A "did the signal emit" outcome is not "did the edit commit" — the View's success toast must pull the real result

**Area:** `view/pdf_view.py` / `controller/pdf_controller.py` (Task 12 P0-C phase 2 — post-review finding, promoted to a merge blocker)
**Symptom:** `set_mode()`'s mode-switch success toast gated only on `TextEditFinalizeResult.outcome == TextEditOutcome.COMMITTED`. That value is set by the View's finalize path whenever `sig_edit_text.emit(...)`/`sig_move_text_across_pages.emit(...)` itself doesn't raise — it never inspected what the Controller's slot actually did with the request. Once `EditTextResult.FALLBACK_DECLINED` existed (P0-C phase 2), a user who explicitly declined a legacy-fidelity fallback — zero mutation, no undo entry — could still see "文字已儲存" on the very next mode switch, directly contradicting the consent flow's own promise. The same gap pre-dated Phase 2 for `REJECTED_STRICT` and `TARGET_BLOCK_NOT_FOUND`, just with lower stakes (no explicit "I said no" UI action to contradict).
**Cause:** treating "the signal was emitted and the slot didn't throw" as a proxy for "the operation succeeded", when the Controller's slot has several legitimate early-return non-SUCCESS paths that never raise.
**Fix:** added `PDFController.consume_last_edit_result()` — a pull-and-clear API mirroring `consume_last_edit_degraded()` — returning the actual `EditTextResult` of the last commit-producing operation (`edit_text`, `move_text_across_pages`, `add_textbox`; the last one has no `EditTextResult` of its own, so it reports `SUCCESS` unconditionally on reaching its post-command code with no exception). `set_mode()` now pulls this FIRST and only evaluates the degrade-suppression flag when it is exactly `EditTextResult.SUCCESS`; `None` (no commit-producing operation happened, or a controller/mock without the new API) is treated the same as "not SUCCESS" — never as "assume success". (The reset-placement half of this fix had its own bug — see the next entry.)
**File:** `view/pdf_view.py`, `controller/pdf_controller.py`, `view/text_editing.py` (re-exports `EditTextResult` through the existing `view.text_editing -> model.edit_commands` allowlist entry, `pyproject.toml`)

## A "reset at entry" claim is only true if the reset actually runs before every early-return guard

**Area:** `controller/pdf_controller.py` (Task 12 P0-C phase 2 toast fix — adversarial verification finding, high + medium)
**Symptom:** the toast-correctness fix above added `self._last_edit_result = None` to `move_text_across_pages()` and `add_textbox()`, but placed it at the SAME point Phase 1's `self._last_edit_degraded = False` already lived — which, on inspection, sat AFTER both methods' own early-return validation guards (empty text, doc not open, page out of range), not before. A stale `EditTextResult.SUCCESS` left over from an earlier, unconsumed commit-producing interaction (any finalize reason other than `MODE_SWITCH` — e.g. `APPLY`/`FOCUS_OUTSIDE` — never calls `consume_last_edit_result()`, only `set_mode()`'s `MODE_SWITCH` branch does) survived straight through a guard return and was read as THIS interaction's outcome: an empty-text cross-page move could show a `跨頁移動失敗` error toast and a `文字已儲存` success toast simultaneously, for an interaction that mutated nothing.
**Cause:** copying an existing reset's location on the assumption it was already correct, instead of re-deriving "true entry" from scratch for the new field. `edit_text()`'s own reset genuinely does sit before its guard (checked and confirmed during the fix), which made the same placement in the other two methods look consistent — but consistency with a wrong precedent is still wrong. The author flagged this exact risk during design ("this reset placement was a case I explicitly considered and decided not to fix, reasoning it was lower-risk") and the adversarial round proved the reasoning wrong on reachability.
**Fix:** moved both `self._last_edit_degraded = False` and `self._last_edit_result = None` to the literal first lines of `move_text_across_pages()` (before even its request-object normalization) and `add_textbox()` (before either guard) — genuinely before any code path that can return. Two regression tests pin it (`test_stale_last_edit_result_does_not_survive_move_validation_guard`, `test_stale_last_edit_result_does_not_survive_add_textbox_validation_guard`): commit a real edit, leave it unconsumed, then trigger a DIFFERENT interaction's validation-guard failure, and assert the stale value never survives.
**File:** `controller/pdf_controller.py`

## AutoCAD-produced Type0 fonts inline their descendant CIDFont in /DescendantFonts

**Area:** `model/text_commit` (Type0/CID evidence readers), `scripts/audit_type0_census.py` (Task 12 P0-D census)
**Symptom:** the dominant real-corpus Type0 form carries the descendant CIDFont as an INLINE dictionary — `/DescendantFonts [<</Type/Font/Subtype/CIDFontType2 ... /W 724 0 R>>]` — not as an indirect reference (`[N 0 R]`). Readers that assume the indirect-array form classify every such font as unreadable: `verify.collect_cid_encoding_evidence` rejects them with "unreadable /DescendantFonts entry", and the census script's first run misbucketed 256 of 262 corpus Type0 fonts as `missing_or_unreadable` (every downstream facet then reads malformed too, because each classifier dereferences the descendant first). On the private reference corpus the inline form is 97.7% of Type0 fonts — a P0-D implementation without inline-descendant support would cover 6/262 fonts.
**Cause:** PDF 32000-1 permits any dictionary value to be inline or indirect; MuPDF/PyMuPDF authoring and most test PDFs use the indirect form, so readers get written and tested against `[N 0 R]` only. `doc.xref_get_key(font_xref, "DescendantFonts")` returns kind `"array"` with the full serialized inline dict as the value — there is no xref to chase, so key reads must fall back to parsing the serialized body.
**Fix:** resolve the descendant BOTH ways: kind `"xref"`/array-of-ref → dereference; array starting with `<<` → extract the balanced inline dict and read keys textually (with one-level deref for indirect values like `/W 724 0 R` inside it). `scripts/audit_type0_census.py` (`_resolve_descendant`/`_desc_key`) is the working reference; `collect_cid_encoding_evidence` must gain the same handling when P0-D's implementation lands (red-pinned by `test_inline_descendant_corpus_shape_commits`). Related corpus fact: those inline descendants also omit `/DW` (spec default 1000) and `/CIDToGIDMap` (spec-implicit Identity) — both defaults are the DOMINANT form, not edge cases, and their `/CIDSystemInfo` carries nonstandard registry/ordering strings, so gate on the Type0 `/Encoding` name, never on CIDSystemInfo contents.
**File:** `scripts/audit_type0_census.py`, `test_scripts/type0_fixture_builder.py` (`inline_descendant`), plan §8 2026-08-13 census entry

## Path-based xref_set_key cannot null a nested key — it plants a placeholder string

**Area:** PyMuPDF xref surgery (`test_scripts/type0_fixture_builder.py`, Task 12 P0-D fixtures)
**Symptom:** `doc.xref_set_key(descendant_xref, "FontDescriptor/FontFile2", "null")` does not remove the nested key: reading it back afterwards returns `('string', 'fitz: replace me!')` — PyMuPDF's internal placeholder — so the "unembedded font" fixture still looked embedded-ish (present-but-garbage) instead of cleanly stripped.
**Cause:** PyMuPDF's path-form `xref_set_key` builds intermediate placeholders when writing through a path; nulling through a path is not supported the way direct key nulling is.
**Fix:** resolve the nested dictionary's own xref first (`xref_get_key(descendant, "FontDescriptor")` → `('xref', 'N 0 R')` → N), then null the key directly on it: `xref_set_key(N, "FontFile2", "null")`. Verified: the key then reads back `('null', 'null')`.
**File:** `test_scripts/type0_fixture_builder.py` (`unembed_font`)

## subset_fonts strips the cmap — Unicode lookups cannot prove glyph presence in a subset

**Area:** PyMuPDF font subsetting (`test_scripts/type0_fixture_builder.py`, Task 12 P0-D fixtures; future P0-D glyph-presence gate)
**Symptom:** after `doc.subset_fonts()` (native in PyMuPDF 1.27 — no fontTools needed, despite older docs), `fitz.Font(fontbuffer=<subset>).has_glyph(ord(ch))` returns 0 for EVERY character — including the ones whose glyphs the subset genuinely retained — because the subsetter strips the font program's cmap (rendering goes CID→GID directly and never needs it). Any "is this glyph in the embedded subset" gate built on Unicode lookup would fail-closed on everything (or worse, get inverted into fail-open by a confused fix). `glyph_count` is equally useless: retain-gids subsetting keeps the glyph COUNT constant (50,483 before and after) and only empties the dropped outlines.
**Cause:** MuPDF subsets with retain-gids semantics for CIDFontType2 (so content-stream CIDs stay valid — shows are byte-identical across subsetting) and drops tables only the Unicode→GID path needs.
**Fix:** prove subset glyph presence by GID-level evidence, never Unicode: the fixture builder renders the CID alone and counts ink (`render_cid_ink` — a retained glyph renders >0 non-white pixels, a dropped one renders exactly 0); the production gate must read glyph table emptiness by GID (or equivalent) when it lands. Bonus fact: CID == GID for MuPDF's own Identity-H embedding, and `fitz.Font.has_glyph` on the FULL (pre-subset) face returns the GID itself, which is how the builder computes CIDs without parsing the ToUnicode CMap.
**File:** `test_scripts/type0_fixture_builder.py` (`render_cid_ink`, module docstring)

## _parse_tounicode silently fabricates mappings from array-destination bfranges

**Area:** `model/text_commit/verify.py` (`_parse_tounicode`, used by `collect_cid_encoding_evidence` — live Task 10 code), `scripts/audit_type0_census.py` (Task 12 P0-D adversarial finding)
**Symptom:** the array-destination `bfrange` form of PDF 32000-1 §9.10.3 — `<lo> <hi> [<d1> <d2> ...]` — is spec-legal, but `_parse_tounicode` flattens ALL hex tokens in a bfrange block and strides by 3, so instead of refusing the form it fabricates garbage mappings: for `<00> <02> [<0041> <0042> <0043>] <05> <06> <0044>` it emits `(0x00, 0x02, 'A')` and then `(0x0042, 0x0043, '\x05')` — CIDs 66–67 mapped to a control character — and silently loses the valid trailing single-destination record. Its own docstring claims the form is "deliberately left unsupported rather than guessed at", which the stride walk does not honor. The form is REAL in the reference corpus: 2 of 262 private-corpus Type0 fonts use it (one is a document's only Type0 font), and the census script's original substring-grep parseability check (`b"beginbfchar" in data`) could not see it either — the first recorded scope-lock numbers were wrong until a structural re-run corrected them.
**Cause:** token-stream parsing that assumes the single-destination record shape and never inspects block delimiters; a `[` inside a bfrange block changes the record arity and must be either supported or refused, never strided over.
**Fix:** the P0-D contract pins fail-closed behavior (`type0_tounicode_unparseable`, red test `test_array_destination_bfrange_tounicode_fails_closed`); the implementation must make `_parse_tounicode` (or its P0-D successor) refuse any bfrange block containing `[`. The census now does structural validation with a dedicated `present_with_array_destinations` bucket (`scripts/audit_type0_census.py::_classify_tounicode`). Broader lesson: a "parseable" verdict from a substring grep is not evidence — the very tool that produces scope-lock numbers needs the same fail-closed discipline as the engine.
**File:** `model/text_commit/verify.py` (fix pending with P0-D implementation), `scripts/audit_type0_census.py`, `test_scripts/test_text_commit_cid_hex_tj.py`

## PyMuPDF TextWriter embeds EVERYTHING as Type0 — Helvetica lands with a CIDFontType0 descendant

**Area:** test fixtures (`test_scripts/test_text_commit_fonts.py`, `test_text_commit_font_widths.py`), `model/text_commit/fonts.py` (Task 12 P0-D)
**Symptom:** a TextWriter page written with `fitz.Font("helv")` — plain ASCII Helvetica — does not produce a simple Type1 font: MuPDF embeds it as `Type0/Identity-H` with a **CIDFontType0** (CFF) descendant. Pre-P0-D tests pinned that shape as "embedded Type0 extracts a face" + blanket `font_unsupported_encoding`; under P0-D it correctly fail-closes as `type0_descendant_unsupported` (CIDFontType0 is out of the v1 slice), and Type0 capabilities no longer load a fitz face at all, so `face is None`/`face_source == "none"` became the pinned contract. Only `fitz.Font("cjk")` (Droid Sans Fallback, TrueType) produces the in-scope CIDFontType2 descendant.
**Cause:** MuPDF's TextWriter always writes composite fonts; the descendant subtype follows the source font's outline format (CFF → CIDFontType0, TrueType glyf → CIDFontType2).
**Fix:** fixture builders that need in-scope Identity-H/CIDFontType2 must use a TrueType-backed face (`fitz.Font("cjk")` — `test_scripts/type0_fixture_builder.py`); tests asserting Type0 capability behavior assert per-gate `type0_*` codes, never the old blanket code, and never a loaded face.
**File:** `test_scripts/test_text_commit_fonts.py`, `test_scripts/test_text_commit_font_widths.py`, `model/text_commit/fonts.py`

## A "default text state" percentage is only as good as its condition list

**Area:** Task 12 coverage evidence (`scripts/measure_type0_funnel.py` vs the 2026-08-12 campaign numbers)
**Symptom:** the campaign's "default-text-state subset: 82.7% ops" (plan §2) and the post-P0-D funnel's honest result — **0 source-bindable shows** on the same document — are both true. The single-hex-`Tj` layer matches exactly (97.2% in both), but the campaign's "default state" did not deduct the conditions the implemented gates actually check: on the reference document every budget-eligible show sits inside an AutoCAD BDC/EMC layer wrapper (`mc_depth != 0` → 100% fail) and 95% use a rotated text matrix compensating `/Rotate 270` in content space (`trm_uniform_scaled` → fail). Publishing the 82.7% as expected product coverage would have overstated reality by the whole number.
**Cause:** "default text state" is not a standard term — any coverage claim quoting it must enumerate the exact conditions (render_mode/rise/hscale/mc_depth/in_bt/trm/origin_reliable) or the number silently measures a different gate set than the code enforces.
**Fix:** the funnel script measures THROUGH the real gate implementations (capability build, decode, reproduction, glyph/width gates) and reports per-condition loss tallies; plan §8 records the two-layer coverage rule (structural family vs actually-processable) and the three follow-ups (budget relaxation, mc_depth tolerance, rotated-Tm) that own the corpus unlock.
**File:** `scripts/measure_type0_funnel.py`, plan §8 2026-08-13 funnel entry

## Canonical-fold gaps hide in HYBRID object forms, not the named ones
**Area:** model/text_commit (Type0 fingerprint staleness closure)
**Symptom:** prepare → mutate evidence → commit returned COMMITTED (stale plan committed against dead width evidence) for a font whose `/DescendantFonts` was an indirect ARRAY object holding the descendant dict INLINE — while both named sibling forms (direct inline array; indirect ref element) were staleness-gated and red-pinned. Two independent review agents reproduced it end-to-end (wf_1757a5fb-8e9); the five existing staleness pins all stayed green.
**Cause:** the canonical descendant fold keyed on the ARRIVAL PATH (PdfRef element ⇒ deref ⇒ fold) instead of the RESOLVED VALUE (dict ⇒ fold). The hybrid form arrives as a dict without passing the PdfRef branch, and the font-dict key loop had folded only the scalar `xref:N 0 R` — so every direct value inside the inline dict (inline `/W`, `/DW`, `/CIDToGIDMap` name, `/Subtype`) was invisible to `page_fingerprint` while `resolve_descendant` happily ACCEPTED the form for capability building.
**Fix:** fold `canonical_pdf_text(descendant)` whenever the RESOLVED value is a dict, regardless of how it was reached (the direct-inline path folding twice is harmless — both sides of a staleness comparison fold identically). The general rule: enumerate closure coverage by RESOLVED SHAPE, and for every shape the capability builder accepts, write a prepare→mutate→commit red pin — "both named forms are covered" says nothing about their hybrid.
**File:** `model/text_commit/inspect.py` (`_update_type0_dependencies`); pin `test_scripts/test_text_commit_cid_hex_tj.py::test_commit_is_stale_after_hybrid_indirect_array_descendant_mutation`

## A dead optional hook that catches its own ImportError becomes a per-edit user-visible defect
**Area:** `controller/pdf_controller.py` (`edit_text` displacement-reflow callback, removed Task 12 Step 7)
**Symptom:** every successful reflow-allowed text edit logged `edit_text reflow_fn 失敗（不影響主編輯）: No module named 'reflow'` AND pushed a `⚠ Reflow 例外（主編輯不受影響）` status-bar override at the user for 5 seconds — for a feature that could never run. The hook lazily imported `reflow.track_A_core`/`track_B_core`, a spike-era package that never existed on the shipping lineage (it lived only on abandoned Track A/B/C branches), was never a declared dependency, and was never installed.
**Cause:** the callback wrapped its body in `except Exception` and routed the exception into BOTH the log and the user-facing status channel, so a permanently-failing import degraded into "harmless-looking" per-edit noise instead of failing loudly once at wiring time. Nothing pinned the absence of the warning, so it survived multiple refactors; the evidence grade stayed "agent-reported" until a red pin captured the logger line from the production wiring.
**Fix:** capture reproducible evidence FIRST (the red pin's failing run logs the exact warning from `sig_edit_text` → `PDFController.edit_text`), then delete the whole hook: closure, `reflow_fn=` wiring, and the status-bar display block. `EditTextCommand.reflow_fn` stays as the model-layer extension point (still pinned by `test_text_commit_intent.py`); the regression pin asserts no reflow-related output on any channel after a successful edit. General rule: an optional integration whose import can fail must fail ONCE, at composition time, visibly — never per-action inside a catch-all that repaints the failure as a warning.
**File:** `controller/pdf_controller.py`; pin `test_scripts/test_text_commit_degrade_visibility.py::test_dead_reflow_hook_never_surfaces_after_successful_edit`

## Bare object keywords in content streams lex as OPERATOR tokens and silently clear accumulated operands
**Area:** `model/text_commit/pdf_lexer.py` consumers (`replay.py` operand accumulation)
**Symptom:** an inline BDC property dict with a keyword value — `/Span <</ActualText null>> BDC` — lost its whole operand list before BDC executed: the census bucketed it `props_unparsed` instead of `actual_text` (caught by the Codex review round, red-pinned before the fix).
**Cause:** `true`/`false`/`null` match the lexer's alphabetic-keyword OPERATOR pattern, so the replay dispatch treated them as unknown graphics operators, whose contract is `operands.clear()` — destroying the flat-lexed `<< ... >>` marker sequence accumulated so far. Any operand-accumulating consumer of `lex_content_stream` has this trap: PDF object keywords are legal VALUES inside inline dicts (and arrays), never operators.
**Fix:** intercept `true`/`false`/`null` in the operator branch BEFORE dispatch and append them as `_Operand("keyword", ...)` instead of clearing (`replay.py`). Blast radius is nil for real operators: prior behavior for e.g. `/F1 true 12 Tf` (malformed either way) is preserved because arity checks are tail-anchored. Pin: `test_scripts/test_wrapper_taxonomy_census.py::test_inline_dict_keyword_values_keep_keys`.
**File:** `model/text_commit/replay.py`

## PyMuPDF's OC state (get_ocgs, rendering) is a load-time snapshot — /OCProperties writes don't refresh it
**Area:** `model/text_commit/marked_content.py` — OCG default-config visibility resolution (Task 13 P1 admission)
**Symptom:** After `doc.set_layer(-1, off=[ocg_xref])` — or raw `xref_set_key` surgery on `/OCProperties /D` — the serialized document says the layer is OFF, but `doc.get_ocgs()[xref]["on"]` still reports `True` and `page.get_pixmap()` still renders the layer's ink. A staleness test asserting the flip "took" via `get_ocgs` fails even though the flip is fully serialized; conversely, code trusting `get_ocgs` would admit a wrapped edit against a layer every future opener of the saved file will hide.
**Cause:** MuPDF builds its in-memory OC descriptor when the document is opened (and `add_ocg` updates it as a side effect), and both `get_ocgs`'s `on` bit and rendering read that descriptor — neither re-reads the serialized `/OCProperties` after `set_layer` or direct xref writes. Only a save→reopen round trip re-resolves. Verified empirically on 1.27.1: after surgery, live `get_ocgs` says on/renders ink; the reopened bytes say off/render hidden.
**Fix:** Resolve default-config visibility from the SERIALIZED catalog: parse `/OCProperties` (`/OCGs` registration, `/D` `/BaseState`+`/ON`+`/OFF`, OFF wins on dual listing, fail-closed on anything unreadable) — `resolve_default_visibility()` — and fold the same resolved bits into the page fingerprint so a post-prepare flip goes `STALE_PLAN`. Never gate admission or staleness on `get_ocgs`. Test-side: assert flips on `xref_get_key(catalog, "OCProperties/D/OFF")`, not on `get_ocgs`.
**File:** `model/text_commit/marked_content.py` (`resolve_default_visibility`, `update_marked_content_dependencies`); pinned by `test_scripts/test_text_commit_mc_admission.py::test_visibility_flip_between_prepare_and_commit_is_stale`

## PDF numbers have no exponent notation — %g-formatted matrix coefficients silently void the whole operator
**Area:** `test_scripts/type0_fixture_builder.py` (`set_text_matrix`), any code writing numbers into content streams
**Symptom:** A fixture rewritten with a "rotated" `Tm` still behaved axis-aligned: the census bucketed nothing, `trm_uniform_scaled` stayed `True`, and the rotated-Tm funnel test failed with `uniform_trm == 1`. The rotation had never applied.
**Cause:** `math.cos(math.radians(90))` is `6.12e-17`, and Python's `%g`/`:g` formats it as `6.12323e-17` — but the PDF grammar (ISO 32000-1 §7.3.3) has NO exponent notation for numbers. A real content-stream lexer refuses the token, so the whole `6.12323e-17 1 -1 6.12323e-17 72 700 Tm` operand list is dropped and the previous text matrix silently stays in force. Nothing errors; the fixture just tests nothing.
**Fix:** Format content-stream numbers fixed-point (`f"{v:.8f}".rstrip("0").rstrip(".")`, mapping `-0`/empty to `0`), and author quarter-turn fixtures with exact `0`/`±1` coefficients instead of trig reconstructions. `set_text_matrix` does this via its `_pdf_num` helper.
**File:** `test_scripts/type0_fixture_builder.py` (`set_text_matrix`); pinned by `test_scripts/test_trm_census.py::test_funnel_reports_trm_census_for_rotated_show`

## Single-process full-suite pytest runs hang or abort nondeterministically inside Qt GUI tests
**Area:** test harness (whole-suite runs of `test_scripts/`), PySide6 offscreen platform
**Symptom:** `pytest` over the full suite freezes forever (process alive, zero CPU growth, output file stops updating) or dies with `Fatal Python error: Aborted` (native abort, no Python traceback) inside a Qt widget test — observed at different tests on different runs (an OCR-dialog-area test once, `test_page_reorder.py::test_internal_drop_moves_row_and_emits_final_positions` in `_make_thumbnail_list` another time). Every individual test passes; watchers that only detect "summary printed" or "process died" wait forever on the hung-but-alive case.
**Cause:** *Observed (proven):* a single-process offscreen Qt suite nondeterministically hangs or aborts after many test files, while every file passes in an isolated interpreter — so no single file necessarily fails in isolation, and the failure is environment-sensitive (more likely in non-interactive/detached shells). *Likely cause (not yet isolated):* cross-file / long-lived `QApplication` native-state or lifetime pollution — after hundreds of tests share one offscreen `QApplication`, widget construction/drag-drop simulation can deadlock or abort in the C++ layer. The precise contaminating predecessor sequence (or Qt object class) has NOT been identified; per-file green does not rule out one earlier file leaving native Qt state that detonates in another.
**Fix:** Verify the suite per-file: run each `test_scripts/test_*.py` in its own interpreter with a hard timeout (`timeout -k 10 240 .venv/Scripts/python.exe -m pytest -q <file>`), log one summary line per file, and aggregate. Hangs become named single-file timeouts instead of killing the run. Treat `rc=5` ("no tests ran") as success ONLY for the explicit allowlist of 16 legacy script-style files with no collectable tests (`test_1pdf_audit.py`, `test_50_rounds.py`, `test_all_pdfs.py`, `test_deep.py`, `test_drag_move.py`, `test_edit_flow.py`, `test_feature_conflict.py`, `test_large_scale.py`, `test_open_large_pdf.py`, `test_overlap_corpus_recursive.py`, `test_performance.py`, `test_printing_pipeline.py`, `test_sample_pdfs.py`, `test_track_ab_5scenarios.py`, `test_track_ab_model_regressions.py`, `test_unified_undo.py`); any OTHER file returning rc=5 is a failure — a real test module silently collecting zero tests. Any monitor watching a long pytest run must treat "output file stale >5 min while process alive" as a terminal state alongside "summary printed" and "process gone".
**File:** no code change — harness procedure (sweep loop documented here; 2026-08-19 baseline: 220 files, 2473 passed / 21 skipped / 0 failed / 0 timeouts, 16 allowlisted rc=5)

## get_drawings/get_image_rects report UNROTATED page space — occupancy gates silently miss obstacles on /Rotate pages
**Area:** model/text_commit/verify.py (Tier 1 growth occupancy gates), PyMuPDF geometry conventions
**Symptom:** On a /Rotate 270 page, a vector fill or image placed squarely inside the (visual-space) growth strip was NOT detected by `_drawings_intersect_growth`/`_images_intersect_growth` — the blank-growth proof fell through to the raster gates with the wrong attribution, and the four-direction red matrix caught it only in the CAD-idiom `right` cases.
**Cause:** `page.get_drawings()` and `page.get_image_rects()` return rectangles in UNROTATED page space — the same quirk long documented for `page.get_text` and annotation geometry — while `target_bbox`/`verify_bbox`/the growth rect are VISUAL space (`transformation_matrix × rotation_matrix`, matching `get_pixmap`). At /Rotate 0 the two coincide, so axis-aligned tests never see it.
**Fix:** Convert the growth rect to dict space once (`page.derotation_matrix`, the read-side half of the documented conversion) before intersecting — `verify._growth_rect_in_dict_space`, used by both occupancy intersects; `count_growth_zone_glyphs` converts its zone and target the same way before touching rawdict char bboxes. Any future gate comparing engine visual-space geometry against a PyMuPDF page-inspection API must ask which convention that API speaks first.
**File:** model/text_commit/verify.py (`_growth_rect_in_dict_space`, `count_growth_zone_glyphs`); pinned by test_scripts/test_text_commit_trm_growth_directions.py (vector/image × right)

## MuPDF re-serializes integer-valued reals as ints — raw kind:value folds break across a tobytes round trip
**Area:** model/text_commit/inspect.py (page fingerprint), PyMuPDF object serialization
**Symptom:** A document carrying `/UserUnit 2.0` (a real-typed spelling of an integer value) fingerprinted differently live vs after `tobytes()`→reopen: `xref_get_key` reports `('float', '2')` live but `('int', '2')` on the reopened copy. Since live-vs-scratch fingerprint equality gates every prepare's scratch-apply, EVERY prepare on such a document would fail persistently with VERIFICATION_FAILED — fail-closed, but a confusing whole-feature loss (review finding F4, confirmed empirically on 1.27.1).
**Cause:** MuPDF prints numbers minimally on save: an integer-valued real loses its `.0` and comes back typed as an int, flipping the reported KIND while the VALUE stays equal. The earlier scalar-fold precedent ("not observed to reformat") was measured on font keys, which are virtually never integer-valued reals; `/UserUnit` is exactly the key where that spelling occurs.
**Fix:** Fold numeric keys as a canonical NUMBER, never as the raw `kind:value` pair: parse the resolved value with `float()` and fold `num:{float(value)!r}` (`int:2` and `float:2` both fold `num:2.0`); keep `kind:value` only for non-numeric kinds. Applies to any future fingerprint surface that reads typed scalars off an xref.
**File:** model/text_commit/inspect.py (`_update_page_geometry`); pinned by test_scripts/test_text_commit_trm_page_geometry.py::test_fingerprint_is_stable_when_userunit_is_spelled_as_a_real

## tracemalloc-wrapped timing windows and iterated-build peaks corrupt benchmark numbers two different ways
**Area:** measurement harnesses (`scripts/benchmark_*`), tracemalloc + timing interaction
**Symptom:** A benchmark comparing an index build against plain replay reported a build premium that was instrumentation, not work; separately, the reported "single build peak" was roughly one whole retained index too high (P3-A review findings F1/F2, both confirmed).
**Cause:** Two distinct mechanisms. (1) Timing samples taken while `tracemalloc` is tracing carry per-allocation overhead (2-4x on allocation-heavy code) that competing stages timed without tracing do not — a systematic cross-stage bias, not noise. (2) A timing loop that keeps `result = fn()` bound across iterations holds iteration N-1's fully-built object alive while iteration N allocates inside the same tracing window, so the peak read once after N builds ≈ true single-build peak + one retained result.
**Fix:** Never report timings from inside a tracemalloc window; time clean first, then trace exactly ONE extra throwaway build in its own `gc.collect()` → `start()` → build → `get_traced_memory()` → `stop()` window for the peak.
**File:** `scripts/benchmark_replay_index_spike.py` (`_single_build_peak`; stage timings taken outside tracing)

## json.dumps backslash escaping makes Windows path-leak assertions silently inert
**Area:** data-policy tests asserting "no paths in the serialized report"
**Symptom:** `assert str(tmp_path) not in json.dumps(report)` passes even when the harness embeds the path verbatim in the report — the fence tests nothing on Windows (P3-A review finding F8).
**Cause:** `json.dumps` escapes every backslash to two characters, so the single-backslash needle (`C:\Users\...`) can never match the doubled-backslash haystack (`C:\Users\...`); the assertion fails at the first backslash from every alignment.
**Fix:** Assert the JSON-ENCODED spelling — `json.dumps(str(path))[1:-1] not in serialized` — plus the forward-slash form (`path.as_posix()`), so both verbatim and normalized embeddings are caught.
**File:** `test_scripts/test_replay_index_spike.py::test_harness_report_carries_no_text_or_paths`

## sys.getsizeof on a slotless dataclass misses the per-instance __dict__ that dominates its memory
**Area:** memory accounting (`_deep_size`-style recursive sizeof), dataclass instances
**Symptom:** A "deep" recursive `sys.getsizeof` walker that recursed into dataclass FIELDS reported bytes/ShowOp far below reality — the walker skipped the ~1 KB per-instance `__dict__` container that IS the dominant cost of a 24-field slotless dataclass.
**Cause:** `sys.getsizeof(instance)` returns only the object header; the instance `__dict__` is a separate object, and iterating `dataclasses.fields` sizes the VALUES while never sizing the dict container holding them.
**Fix:** For slotless dataclasses, recurse into `vars(obj)` (the `__dict__` itself) so the container, its keys, and its values are all counted; fall back to per-field walking only for `__slots__` classes (no `__dict__` to size).
**File:** `scripts/replay_index_spike.py` (`_deep_size`)

## Simple-font capabilities are served stale within a registry generation
**Area:** `model/text_commit/fonts.py` (`DocumentFontRegistry`), engine prepare path
**Symptom:** After an in-place font-object mutation (e.g. `/Widths` rewritten at the same xref) between two prepares sharing one registry, the second prepare's Tier 0 advance gate consumes the OLD widths while the page fingerprint (which hashes the defining font objects) is computed fresh — so the plan token and the apply-time staleness compare are fresh-vs-fresh and cannot catch the stale capability.
**Cause:** The capability cache key is `(generation, owner, name, xref)` and the per-lookup evidence-digest revalidation runs ONLY for Type0 (`cached.cid is not None`); simple fonts are returned without any pull-validation until `bump_generation`, which the engine calls only after a successful tiered commit. Pre-existing behavior surfaced by the P3-B adversarial review (R1); unreachable in preview (private scratch, splice+revert only).
**Fix:** CLOSED (Task 13 revalidation slice, 2026-08-27): every `FontCapability` carries `evidence_digest` (`compare=False`); `compute_font_evidence_digest` dispatches on the `get_fonts` entry's SUBTYPE (Type0 → `compute_cid_evidence_digest`, else the new `compute_simple_font_evidence_digest` — font dict keys, indirect `/Encoding`/`/Widths`/`/FirstChar`/`/LastChar`/`/FontDescriptor` targets, `FontDescriptor/Flags`, raw `FontFile*` bytes); `page_capabilities` re-derives it on EVERY lookup before probing the cache and rebuilds on mismatch. Keying on subtype rather than `cached.cid is not None` also closes the same-class hole for a REJECTED Type0 (`cid is None`). Two rules kept: the digest is taken BEFORE the build (a write racing the build is caught next lookup, not attested as current), and the enumeration in the digest must be extended in the same change whenever `_build_capability` starts reading another key. Deliberately NOT changed inside the P3-B slice — its fences excluded font-capability rework.
**File:** `model/text_commit/fonts.py` (`compute_simple_font_evidence_digest`, `DocumentFontRegistry.page_capabilities`), `test_scripts/test_text_commit_font_revalidation.py`

## Provenance fields on compared dataclasses silently break equality pins
**Area:** `model/text_commit/replay.py` (`PageReplay`), frozen-dataclass contracts generally
**Symptom:** Adding the P3-B budget-attestation field `max_decoded_bytes` to `PageReplay` broke `test_streams_within_budget_replay_identically`, which asserts a smaller-budget replay of in-budget streams equals the default-budget replay — dataclass `__eq__` folds every field, so recording HOW a result was produced changed WHAT it compares as.
**Cause:** Dataclass equality is field-wise by default; provenance/attestation metadata is not part of a result's semantic identity, but a plain field makes it so.
**Fix:** Declare provenance metadata with `field(compare=False)` (repr keeps it visible, consumers still read the value, equality stays semantic). `ReplayEvidence.__post_init__` still refuses `max_decoded_bytes is None` — the attestation's purpose — without perturbing any equality pin.
**File:** `model/text_commit/replay.py` (`PageReplay.max_decoded_bytes`)

## fitz.Document.update_stream(compress=False) never restores the original storage encoding
**Area:** `model/text_commit/patch.py` (`apply_patchset`, `AppliedPatch.revert`), PyMuPDF stream storage
**Symptom:** After a `compress=False` apply followed by a `compress=False` revert, the DECODED bytes (`xref_stream()`) are exactly the original content — but the stream object's own dict is not: `/Filter /FlateDecode` is gone and `/Length` reflects the uncompressed size, permanently, for the rest of the object's life. "Revert" restores decoded content, never the storage encoding a write happened to use (P3-C adversarial review F1 — the plan's first-pass claim that revert restored the object "exactly" was itself wrong, caught only because a test checked the wrong objects).
**Cause:** `compress` is a per-call encoding instruction to `update_stream`, not a property PyMuPDF tracks or restores; a write with `compress=False` always produces an uncompressed object, whatever the stream previously was.
**Fix:** Safe only where nothing reads a content stream's storage encoding (this codebase never does — every reader goes through `xref_stream()`/decoded bytes). Never assume "reverted" means "byte-identical stream object" — only "byte-identical decoded content." A test asserting object-graph stability across such a round trip must explicitly check the mutated stream's own object dict, not just its neighbors.
**File:** `model/text_commit/patch.py`; pinned by `test_scripts/test_text_commit_apply_compress.py::test_revert_compress_false_does_not_restore_original_storage_encoding`

## tracemalloc cannot see memory PyMuPDF stores in its own C heap
**Area:** memory-bound tests/harnesses for anything touching `fitz.Document` internals
**Symptom:** A memory-bound test using `tracemalloc.get_traced_memory()` around repeated `Document.update_stream` calls would pass even if the written bytes accumulated without bound on the C side (P3-C adversarial review F2) — `tracemalloc` traces only the Python allocator.
**Cause:** PyMuPDF stores stream bytes in MuPDF's own C-side `fz_buffer` structures, reached through the Python binding but never allocated via Python's `malloc` hooks — invisible to any `tracemalloc` window regardless of placement or scope.
**Fix:** For a bound on PyMuPDF-internal storage, assert directly on what PyMuPDF itself reports (e.g. `len(doc.xref_stream_raw(xref))` held constant across repeated writes), not on a Python-heap-only instrument. `tracemalloc` stays correct for genuinely Python-side allocations (e.g. P3-B's retained `ReplayEvidence` objects).
**File:** `test_scripts/test_text_commit_apply_compress.py::test_repeated_preview_keystrokes_stream_storage_stays_single_representation`

## PyMuPDF get_pixmap/get_text each build a private DisplayList/TextPage per call
**Area:** `model/text_commit/verify.py` / `preview.py` render pipeline, any PyMuPDF perf work
**Symptom:** Source-level grep shows zero `get_displaylist`/`get_textpage` calls in `model/text_commit`, yet the P3-C bridge census's class-level probes count THREE DisplayList builds and THREE TextPage builds per warm preview keystroke (~99 ms each on the dense synthetic page) — six independent full content-stream interpretations, none reused, ≈93% of post-P3-C warm render time.
**Cause:** `Page.get_pixmap` internally constructs its own DisplayList before rasterizing, and `Page.get_text` constructs its own TextPage — every call re-parses the page's content stream from scratch. The interpretation cost hides inside convenience utils, so call-site inspection undercounts it structurally; also note the nesting when timing (a wrapped `get_pixmap`'s elapsed INCLUDES its nested `get_displaylist`'s — never sum nested primitive timings).
**Fix:** Attribute interpretation cost by wrapping the `fitz.Page` class methods, not by grepping call sites (`scripts/benchmark_p3c_stage_census.py`'s `StageProbe`). The reuse lever (one post-patch DisplayList + one TextPage shared across verify extraction/raster and the final preview raster) is the registered P3-D candidate — see the plan's §6c/§8.
**File:** `scripts/benchmark_p3c_stage_census.py`; `plans/task13-p3c-preview-postprepare-latency.md` §6c

## An object-level digest misses what get_fonts() has already resolved for the builder
**Area:** `model/text_commit/fonts.py` (`compute_font_evidence_digest`), any staleness digest over font objects
**Symptom:** The first draft of the simple-font revalidation digest folded the font dict's own keys as raw `kind:value` text plus the indirect targets of /Encoding, /Widths, /FirstChar, /LastChar and /FontDescriptor — and still served a stale capability: with `/BaseFont 8 0 R`, rewriting object 8 from `/Helvetica` to `/Wingdings-Regular` left the digest byte-identical (`xref:8 0 R` is unchanged) while `page.get_fonts(full=True)` reported the new basefont and a fresh build refused with `font_face_unavailable`. Same shape for `/Subtype 9 0 R` (Type1→Type3 served as simple) and an inline `/Encoding << /BaseEncoding 10 0 R >>` (WinAnsi→MacExpert served as simple). Task 13 revalidation review F1, three executed probes.
**Cause:** `_build_capability` never reads /BaseFont, /Subtype or the encoding name itself — it consumes the MuPDF-RESOLVED entry fields (ext, subtype, basefont, encoding) that `get_fonts` hands it, and MuPDF follows indirect name objects the object-level digest only sees as references. A digest that enumerates "objects the builder reads" is incomplete unless it also folds every pre-resolved VALUE the builder consumes.
**Fix:** `compute_font_evidence_digest` folds the four resolved entry fields ahead of the per-subtype object closure. General rule for any evidence digest: fold the builder's INPUTS as the builder sees them (resolved values), not only the dictionaries you can name. **Correction (2026-08-27):** this did not imply an analogous cross-document fingerprint gap: `page_fingerprint()` has always folded the complete MuPDF-resolved `get_fonts(full=True)` entry before `_update_font_dependencies`. Three Green characterization pins prove KEEP-round-trip stability, then `prepare ->` indirect `/BaseFont`/`/Subtype`/inline `/BaseEncoding` target mutation `-> STALE_PLAN` with zero stream mutation.
**File:** `model/text_commit/fonts.py` (`compute_font_evidence_digest`); `model/text_commit/inspect.py` (`page_fingerprint`); `test_scripts/test_text_commit_font_revalidation.py::test_indirect_basefont_target_rewrite_rebuilds_the_capability` (+ `_subtype_`, `_base_encoding_`); `test_scripts/test_text_commit_tier0.py::test_resolved_font_entry_mutation_stales_prepared_plan`

## Per-lookup revalidation through a whole-page map is O(K·N) per prepare
**Area:** `model/text_commit/fonts.py` (`DocumentFontRegistry.capability`), engine prepare / per-keystroke preview path
**Symptom:** Adding a per-hit evidence digest made `prepare_plan` on `test_files/test-complexed-layout.pdf` p0 (98 fonts: 90 Type3 + 8 Type0) go from 1.45 s to 10.3 s (7.1×); a 3-font page 3.6 → 10.6 ms. Counting probe: 98 `page_capabilities` calls and 9,604 digests per prepare. Task 13 revalidation review F2.
**Cause:** `capability(page, name)` was a thin wrapper over `page_capabilities(page).get(name)`, so every single-resource lookup revalidated (and previously built/looked up) EVERY font on the page; `inspect._cid_show_candidates` and `plan.py` call it once per distinct show resource, so K lookups × N fonts. The old path hid the same O(K·N) shape behind cheap dict hits; a per-hit cost of a few hundred µs exposed it.
**Fix:** `capability()` locates the single matching `get_fonts` entry (last wins — the dict's answer) and resolves only it through the shared `_resolve`; `page_capabilities` stays for callers needing the map. Type3 digests only what its build reads (`FontDescriptor/Flags`). After: the 98-font page prepares in 340 ms — below the pre-slice baseline. Rule: when adding work to a cache hit, check the CALLER's shape first — a wrapper that resolves the whole collection turns per-hit cost into per-collection cost.
**File:** `model/text_commit/fonts.py` (`capability`, `_resolve`); `test_scripts/test_text_commit_font_revalidation.py::test_single_resource_lookup_digests_only_that_resource`

## Stored stream bytes are not the evidence a decoding builder consumed
**Area:** `model/text_commit/cid_fonts.py` (`compute_cid_evidence_digest`), any cache digest over decoded streams
**Symptom:** A Type0 capability stayed cached after direct `/Filter` rewrites and after an indirect `/Filter N 0 R` target changed: `xref_stream_raw()` remained byte-identical while `xref_stream()` changed or became unreadable. The same stale-hit shape reproduced independently for `ToUnicode`, `CIDToGIDMap`, and `FontFile2` (six red pins).
**Cause:** The CID builder consumes decoded bytes through `_stream_bytes()` (`doc.xref_stream`), but its revalidation digest hashed stored bytes through `xref_stream_raw()`. Hashing the stream dictionary too would still require following every indirect decoding target; attesting a different representation from the builder's input recreates an open-ended closure problem.
**Fix:** Fold exactly the builder-visible decoded bytes via the same `_stream_bytes()` helper. This automatically covers direct and indirect decoding metadata without a second object walker; unreadable evidence hashes as the same `None` sentinel the builder sees and rebuilds to a stable fail-closed rejection. Cost probe (decoded read + SHA p50): ToUnicode 0.011 ms, CIDToGIDMap 0.135 ms, FontFile2 3.617 ms. The implementation replaces raw hashing rather than hashing both; a structural guard pins one decoded read per evidence stream on a warm single-resource hit.
**File:** `model/text_commit/cid_fonts.py`; `test_scripts/test_text_commit_cid_hex_tj.py::test_registry_rebuilds_when_cid_stream_decoding_evidence_changes` (+ unchanged-cache and exact-read-count controls)

## Untyped ctypes windll call silently truncates GetCurrentProcess's pseudo-handle
**Area:** Windows harness/instrumentation code using ctypes (`GetProcessMemoryInfo` etc.)
**Symptom:** `ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ...)` fails with return 0 — and `GetLastError()` reads 0, so there is no diagnostic at all; a broad `except`/fallback then hides the failure as a silent `None` (the P3-C bridge census's memory snapshots came back null until probed directly).
**Cause:** Without an explicit `restype`, `GetCurrentProcess()`'s HANDLE comes back through the default c_int conversion, and without `argtypes` the 64-bit pseudo-handle is truncated on the way into the next call; `use_last_error=True` is also required for `ctypes.get_last_error()` to capture anything.
**Fix:** Use `ctypes.WinDLL(..., use_last_error=True)`, set `GetCurrentProcess.restype = wintypes.HANDLE`, and give the consuming function full `argtypes`/`restype` (`[wintypes.HANDLE, POINTER(struct), wintypes.DWORD]` → `BOOL`). Typed, the same call succeeds.
**File:** `scripts/benchmark_p3c_stage_census.py` (`_working_set_snapshot`)

## PDFModel.__init__ flips PyMuPDF's process-global small_glyph_heights — every later test in a single-process suite sees fontsize-tall (0.8/-0.2 em) text bboxes
**Area:** `model/pdf_model.py` + the text-commit Tier 1 growth proof (`model/text_commit/verify.py`) + any pytest run that shares one interpreter across files (CI's functional suite)
**Symptom:** `test_preview_render_type0_cid_tier1_identical_and_uncompressed` passed in isolation and in the per-file sweep everywhere, then failed in PR #37's single-process CI suite on BOTH platforms (Windows blocking, Ubuntu advisory) with `growth_region_not_blank` — detail `background: the target's own bbox has no majority background colour` — identically under shipped `compress=False` and forced `compress=True`.
**Cause:** `PDFModel.__init__` calls `fitz.TOOLS.set_small_glyph_heights(True)`, a process-global MuPDF flag that nothing in the repo ever resets; the first collected CI test (`test_1pdf_horizontal.py::test_horizontal_edit_and_verify`) constructs a `PDFModel`, so every later test that hands the planner a text-extraction bbox sees PyMuPDF's substituted 0.8/-0.2 em ascender/descender — a fontsize-tall box. (`target_bbox=None` callers get plan.py's flag-immune 1.35 em metric quad instead, which is why the Type0 growth tests in `test_text_commit_trm_*` stayed green in the same run; the app supplies an index-derived bbox on both its preview and commit paths, so it IS exposed.) For the 12 pt dense-CJK Type0 fixture the rawdict span bbox shrinks from 15.68 pt (font-metric box) to exactly 12.0 pt, non-background pixels (ink plus anti-aliased fringe) then reach ≥ 50 % of it, and `_target_background_rgb`'s strict-majority rule correctly finds no background colour — the growth proof fails closed on the `PageState` captured before apply, so no compress-dependent byte can influence it. Isolated runs never set the flag, so they exercise a configuration the app itself never runs in.
**Fix:** The Type0/CID Tier 1 parity pin uses `REPLACEMENT_SHORTER` (Tier 1 without ink growth, `has_ink_growth is False` asserted), so it proves CID encoding + the compensated splice + compress parity regardless of the flag; positive growth parity stays on the simple-font Tier 1 pin, whose target keeps a majority background in both bbox modes. Diagnose this class with a two-file run (`pytest test_scripts/test_1pdf_horizontal.py <suspect>`) or by pre-setting the flag before `pytest.main` — a per-file sweep cannot see it. Follow-ups are in TODOS (suite-level `TOOLS` flag hygiene; the production admission gap for dense-CJK growth candidates under the app's own flag).
**File:** `test_scripts/test_text_commit_apply_compress.py` (Group F Type0 Tier 1 pin); `model/pdf_model.py` (`__init__`, flag site)

## Supplying a TextPage to get_text silently disables the caller's clip and flags
**Area:** PyMuPDF text extraction, `model/text_commit/verify.py`
**Symptom:** Replacing `page.get_text("rawdict", clip=halo, flags=flags)` with `page.get_text("rawdict", clip=halo, flags=flags, textpage=shared)` returns text outside the halo or retains a shape that differs from the legacy verifier.
**Cause:** In PyMuPDF 1.27.1, a supplied TextPage is already interpreted; the convenience API ignores the new `clip` and extraction `flags` instead of rebuilding it.
**Fix:** Use the shared TextPage only for full-page rawdict extraction. For clipped extraction, run a fresh low-level stext device over the already-built DisplayList with the exact legacy clip and flags.
**File:** `model/text_commit/interpretation.py`; pinned by `scripts/probe_p3d_interpretation_equivalence.py` and `test_scripts/test_text_commit_interpretation_reuse.py`

## PyMuPDF's DisplayList and TextPage convenience builders use different rotation conventions
**Area:** PyMuPDF page interpretation, rotated pages
**Symptom:** One shared interpretation appears correct on unrotated pages but shifts text or changes raster bytes at 90/270 degrees.
**Cause:** `Page.get_textpage()` temporarily derotates the page, while `Page.get_displaylist()` bakes page rotation into the display-list transform. They are not interchangeable views of one coordinate system.
**Fix:** Keep two explicit products in `PageInterpretation`: a rotation-faithful DisplayList for raster output and a derotated TextPage for full rawdict identity. Treat their coordinate contracts as part of the type's invariant.
**File:** `model/text_commit/interpretation.py` (`PageInterpretation`)

## Composing derotation onto a DisplayList is not raster-byte stable
**Area:** PyMuPDF raster reuse, `/Rotate`, `/UserUnit`, and CropBox handling
**Symptom:** A DisplayList built under a derotated page and then rasterized with a composed rotation matrix produces a visually plausible image whose dimensions or PNG bytes differ from `Page.get_pixmap()`.
**Cause:** The legacy raster path's page rotation, crop translation, and user-unit transforms are baked in a specific order. Reconstructing that order outside the utility is not byte-stable, especially for rotated CropBoxes and non-default `/UserUnit`.
**Fix:** Build and retain a separate rotation-faithful DisplayList for all raster calls. The premise probe includes negative fixtures proving the composed-derotation alternative diverges.
**File:** `scripts/probe_p3d_interpretation_equivalence.py`; `model/text_commit/interpretation.py`

## DisplayList.run is unusable through the PyMuPDF 1.27.1 Python wrapper for clipped stext reuse
**Area:** PyMuPDF low-level devices
**Symptom:** Calling the public-looking `DisplayList.run()` with a clipped stext device raises or cannot express the exact legacy clipping operation.
**Cause:** The 1.27.1 wrapper does not expose the needed device/matrix/scissor combination compatibly, although MuPDF's underlying display-list runner does.
**Fix:** Keep the compatibility shim isolated in `PageInterpretation`: invoke the low-level run with the exact matrix and scissor, and pin it against independent legacy `get_text` results.
**File:** `model/text_commit/interpretation.py` (`clipped_rawdict` path)

## MEDIABOX_CLIP is not invariant under a quarter-turn CTM
**Area:** clipped stext extraction on rotated pages
**Symptom:** A reused clipped TextPage matches at rotation 0 but drops or admits boundary glyphs at 90/270 degrees when `TEXT_MEDIABOX_CLIP` is enabled.
**Cause:** The media-box clipping flag is applied in the stext device's coordinate space; feeding a non-identity quarter-turn CTM changes which boundary is clipped.
**Fix:** Run clipped stext in the derotated text convention with the legacy clip expressed in that convention. Preserve dedicated 0.1-point boundary and negative-control fixtures.
**File:** `scripts/probe_p3d_interpretation_equivalence.py`; `model/text_commit/interpretation.py`

## Rawdict Python object construction can dominate after interpretation reuse
**Area:** dense-page text verification performance
**Symptom:** Removing redundant DisplayList/TextPage builds does not make warm dense-page verification proportional to the remaining MuPDF interpretation count.
**Cause:** `extractRAWDICT()` still materializes a large nested Python dict/list tree. That allocation and conversion cost survives even when the underlying TextPage is reused.
**Fix:** Treat extraction shape reduction as a separate measured follow-up; do not attribute all residual time to content-stream interpretation or add an unproven private-structure shortcut.
**File:** `model/text_commit/verify.py`; follow-up registered in `TODOS.md`

## A PageInterpretation must not outlive the content-stream mutation window that created it
**Area:** `PlanPreviewRenderer`, scratch apply/revert lifecycle
**Symptom:** Reusing an interpretation after scratch streams have been reverted yields stale pixels/text, retains MuPDF objects, or makes later cleanup order-dependent.
**Cause:** A DisplayList/TextPage is a snapshot of the page at construction time; reverting the document does not mutate that snapshot into the old page.
**Fix:** Construct the post-patch interpretation after apply, use it for verification and final raster, release it idempotently in a nested `finally`, and only then revert streams. Never place it in the engine or session cache.
**File:** `model/text_commit/preview.py`; `model/text_commit/interpretation.py`

## A pre-state baseline cache key is a renderer-lifecycle guard, not a complete render-dependency proof
**Area:** `PreStateBaselineCache`
**Symptom:** A cache hit is mistaken for proof that every indirect image/resource/OCG dependency is unchanged.
**Cause:** The bounded key intentionally uses fresh page identity, fingerprint, font, annotation, and renderer-global evidence; enumerating the entire transitive renderer dependency graph would duplicate MuPDF and is not claimed.
**Fix:** Keep the cache private to one scratch renderer, one slot, and clear it on close/revert failure. Post-patch verification remains authoritative and must fail closed for a key-invisible mutation; the negative control mutates an image XObject outside the halo and proves exactly that.
**File:** `model/text_commit/verify.py` (`PreStateBaselineKey`, `PreStateBaselineCache`); `test_scripts/test_text_commit_prestate_baseline.py`

## Process-global PyMuPDF rendering switches belong in every reusable baseline key
**Area:** renderer caches, `fitz.TOOLS`
**Symptom:** A baseline built under one small-glyph, quad-correction, or anti-alias configuration is reused after another subsystem changes that global, producing inconsistent text geometry or pixels.
**Cause:** These settings live outside the document and page object, so page xref and content fingerprints cannot detect them.
**Fix:** Snapshot all three settings into `PreStateBaselineKey` on every lookup. Any future global that influences extraction or raster output must be added to the key and to the separate governance/reset follow-up.
**File:** `model/text_commit/verify.py` (`PreStateBaselineKey`)

## Building a TextPage can make inherited rotation explicit
**Area:** PyMuPDF inherited page attributes, document serialization
**Symptom:** A read-only-looking text interpretation changes whether `/Rotate` is inherited or explicitly present on the page object.
**Cause:** PyMuPDF's existing get-textpage derotation dance may write an explicit rotation value while restoring effective rotation. This is pre-existing library behavior, not introduced by interpretation reuse.
**Fix:** Compare effective page behavior and the established fingerprint contract, not raw inheritance spelling, unless a task explicitly requires object-graph preservation. Do not widen P3-D into a PyMuPDF serialization rewrite.
**File:** `model/text_commit/interpretation.py`; characterized by `scripts/probe_p3d_interpretation_equivalence.py`

## The model's text-geometry surface was unrotated dict space while the View is displayed space — GUI text editing never worked on `/Rotate 90/270` pages
**Area:** `model/pdf_model.py` (hit-test, selection, outline targets), `model/pdf_text_edit.py` (`edit_text`, `derive_tier0_preview_target`), `controller/pdf_controller.py` facade, `model/geometry.py`
**Symptom:** On a `/Rotate 270` page the raster showed the text vertically near the bottom, but text-edit mode drew the editable-region outlines horizontally near the top, clicking the visible glyphs opened nothing, and clicking the misplaced outline opened an upright editor (and its preview) at the top (P3-D manual smoke, 2026-08-29). A one-line "fix" to the 270° editor-corner branch (`32a7630`) changed nothing because that branch never ran: the hit's `rotation` was the dict-space text direction (0), not the on-screen rotation.
**Cause:** `EditableSpan`/`EditableParagraph`/`TextBlock` geometry comes from `page.get_text("dict"/"rawdict")` = unrotated page space, and `TextHit.target_bbox`/glyph rects/selection bounds were handed to the View unconverted, while `_doc_rect_to_scene_rect`/`_scene_pos_to_page_and_doc_point` are pure scale+offset over the displayed (`page.rect`/`get_pixmap`) raster. The controller forwarded verbatim. At `/Rotate 0` the two spaces coincide, so no unrotated fixture, GUI test or smoke could see it; the rotated GUI tests that existed all used *text-direction* rotation on unrotated pages. The same quirk was already documented for annotations and for the text-commit engine — the read/GUI path was simply never covered.
**Fix:** The model's PUBLIC text-geometry surface speaks displayed space; the index, reopen anchors, resolve pipeline, legacy insert and text-commit engine stay unrotated. Chokepoint helpers in `model/geometry.py` (`visual_to_unrotated_point/rect`, `unrotated_to_visual_point/rect`, `visual_text_rotation`) convert once at the boundary: `get_text_info_at_point` / `get_char_context_at_point` / `get_chars_in_run` / `get_text_selection_snapshot(+_bounds, get_text_in_rect)` / `get_text_selection_snapshot_from_run` / `get_text_selection_lines` convert points in and rects out (index-internal callers use the `_unrotated` bodies); `get_text_targets` / `get_text_blocks` return displayed-space COPIES for the outline drawer; `TextHit.rotation` is `(text_rotation + page.rotation) % 360`; `edit_text` / `derive_tier0_preview_target` derotate incoming `rect`/`new_rect` at entry. Never add rotation math to the View converters. When a new model query takes or returns page geometry, name its space in the docstring and test it on a `/Rotate 90/270` fixture against pixmap ink — never against the conversion matrix.
**File:** `model/geometry.py`, `model/pdf_model.py`, `model/pdf_text_edit.py`, `controller/pdf_controller.py` (`iter_text_targets`, `get_text_blocks`, cross-page-move fallback); pinned by `test_scripts/test_text_geometry_page_rotation.py` and `test_scripts/test_text_edit_rotated_page_gui.py`

## Untouched inline-edit sessions reported a font "override" and lost the Tier 0 plan
**Area:** `view/text_editing.py` (`_sync_font_combo_state`, `build_style_overrides`), `model/text_commit/plan.py` (`STYLE_OVERRIDE_PRESENT`)
**Symptom:** Apply on a Helvetica span the user never restyled reported `tier0:style_override_present -> legacy` and asked for legacy-fallback consent (P3-D manual smoke). Independent of page rotation; masked in GUI tests that preset both font attributes to `"helv"`.
**Cause:** On click the View stores the raw PyMuPDF span font (`"Helvetica"`) in `editing_font_name`, while `_sync_font_combo_state` stored the UI alias `_qt_font_to_pdf(...)` (`"helv"`) in `_editing_initial_font_name` and never overwrote `editing_font_name` (hasattr guard). `build_style_overrides` compares the two case-insensitively → `font_family="Helvetica"` on an untouched session → the plan path refuses (an explicit restyle cannot reuse the source show op).
**Fix:** Seed the baseline from the raw name the session opened with (`_editing_initial_font_name = editing_font_name`) and run BOTH sides of every changed-font comparison through one normaliser (`_font_alias` → `view._qt_font_to_pdf`, via `build_style_overrides(font_key=)` and `finalize_text_edit_impl`). Seeding alone is not enough: the combo writes aliases, so a raw baseline compared by plain string equality turned "pick Courier, pick the original back" into a `font_family="helv"` override (caught by adversarial review). The request's `font` stays the raw current name; only the comparison key is normalised.
**File:** `view/text_editing.py` (`_sync_font_combo_state`, `_font_alias`, `build_style_overrides`); pinned by `test_text_edit_rotated_page_gui.py::test_untouched_session_sends_no_style_override` and `::test_font_pick_and_revert_sends_no_style_override`

## Plan-preview rasters are displayed-space clips; a rotated editor proxy must counter-rotate them
**Area:** `view/text_editing.py` (`_install_plan_preview_hook`, `PreviewBackedInlineTextEditor.apply_plan_preview`, `_capture_frozen_first_frame`)
**Symptom:** The exact (plan-backed) preview was silently unavailable for any editor with a non-zero rotation (`_install_plan_preview_hook` returned early), which after the geometry fix would have meant every `/Rotate 90/270` page fell back to the CSS preview and could not warm the P3-D baseline cache.
**Cause:** The preview coordinator renders `clip_rect` from the rotation-faithful DisplayList, i.e. a displayed-space raster (tall for vertical glyphs), but the editor paints its image at local (0, 0) inside a proxy the scene rotates with `setRotation(rotation)`; unrotated, the raster would be double-rotated on screen.
**Fix:** Install the hook for every rotation and counter-rotate in `apply_plan_preview` and `_capture_frozen_first_frame` through ONE shared table, `PROXY_COUNTER_ROTATION = {90: -90, 180: 180, 270: 90}` (the proxy is rotated about its origin corner: top-right / bottom-right / bottom-left). Before this the frozen-frame grab had only a 90/270 branch — at 180 it grabbed a `w×h` region starting at the proxy origin (the bbox's bottom-right, i.e. the margin below-right of the glyphs) with no rotation, so every editor on a `/Rotate 180` page opened blank until the first keystroke; the grab also ignored the page scene x offset on centred pages. Rotation on the editor means the ON-SCREEN glyph rotation (page `/Rotate` folded in by the model), so rotated text on unrotated pages and unrotated text on rotated pages take the same path. Two paint paths that must agree share one table, not two literals.
**File:** `view/text_editing.py`; pinned by `test_text_edit_rotated_page_gui.py::test_plan_preview_stays_available_on_rotated_editor` (marker pixel per rotation) and `::test_click_on_visible_glyphs_opens_editor_over_them_with_screen_rotation` (frozen frame contains glyph ink, 90/180/270)

## Legacy text insert clamped unrotated rects against the displayed `page.rect`
**Area:** `model/pdf_text_edit.py` (`edit_text` → `_apply_redact_insert` / `_verify_rebuild_edit` / re-insert fallbacks)
**Symptom:** With the legacy engine (or after a Tier 0 reject), editing a run that sits in the lower band of the UNROTATED page of a `/Rotate 90/270` fixture through the htmlbox path (any `new_rect`, multi-line, CJK, or a too-wide replacement) failed with `RuntimeError: 文字框內容在字級 12.0pt 下無法完整塞入 (spare_height=-1)，策略 A/B/C 均失敗，已回滾`; the fast `insert_text` path (short single-line Latin replacements) never clamps, so the first model test written for this passed pre-fix and had to be reworked.
**Cause:** `edit_text` took `page_rect = page.rect` — the DISPLAYED box, 792×612 on a rotated Letter page — and every page-bounds clamp downstream (`clamped_new`, `insert_rect = Rect(x0, y0, x1, page_rect.y1)`, `clamp_rect_to_page`, the probe page dims, `get_text(clip=)`) compared unrotated-space rects (y up to 792) against it: `y0 > page_rect.y1` → degenerate insert rect → htmlbox cannot fit. Identity at `/Rotate 0`, so no unrotated fixture could see it.
**Fix:** `model/geometry.py::unrotated_page_rect(page)` (= `page.rect * page.derotation_matrix`, normalised) is the bounds the legacy pipeline receives; the re-insert fallbacks (`_reinsert...`, span re-insertion `clamp_rect_to_page(bbox, ...)`) use it too. Rule: a clamp's bounds must live in the same space as the rects it clamps — on `/Rotate` pages `page.rect` is only ever right for displayed-space values.
**File:** `model/geometry.py`, `model/pdf_text_edit.py`; pinned by `test_text_geometry_page_rotation.py::test_legacy_edit_keeps_place_when_source_sits_near_the_unrotated_bottom`
## Diagnostic funnels must include page-level production refusals in eligibility
**Area:** `scripts/measure_type0_funnel.py`, `model/text_commit/inspect.py`
**Symptom:** A partial show from a malformed replay, or a show whose content stream is shared by another page, can be counted as source-bindable even though production rejects it.
**Cause:** Recording a page diagnostic does not make it a gate, and show-local gate vectors can omit production checks performed before or after binding.
**Fix:** Compute malformed-replay and shared-content-stream eligibility once per page/stream, include both in the main fold and independent sole-loss vector, and emit affected page/show incidence.
**File:** `scripts/measure_type0_funnel.py`

## Same-face proofs must not succeed over an empty glyph witness set
**Area:** `scripts/audit_same_face.py`
**Symptom:** An all-empty embedded `glyf` table can classify an unrelated candidate as `A_same_gid_exact` without comparing any glyph or metric.
**Cause:** `max(active, default=-1)` passes the bounds check and an empty comparison loop leaves the exact flag true.
**Fix:** Return unproven immediately when `_active_gids` is empty, before computing any same-GID, outline, or renumbered proof.
**File:** `scripts/audit_same_face.py`

## CMap result caps do not bound repeated range-expansion work
**Area:** `scripts/measure_type0_funnel.py`
**Symptom:** Many overlapping full-span `bfrange` records repeatedly enumerate the same characters even after the corpus union stops growing.
**Cause:** The per-font cap bounds stored distinct output, not the work spent revisiting duplicate destination ranges.
**Fix:** Track covered scalar intervals, materialize only uncovered portions, and retain the distinct-character cap and exact truncation semantics.
**File:** `scripts/measure_type0_funnel.py`

## TTC face multiplicity does not imply distinct glyph programs
**Area:** `scripts/audit_same_face.py`
**Symptom:** Every subset matching a multi-face TTC was classified `face_ambiguous`, even when all faces referenced byte-identical `glyf`, `loca`, and `hmtx` tables.
**Cause:** The proof counted matching face names instead of distinct glyph programs. TTC faces can share one program while exposing different cmaps.
**Fix:** Classify multiple allowed exact matches as `A_same_gid_exact_shared_program` only when their raw program tables, UPEM, and glyph count agree; require every matched face to map each supplied character to the same non-empty GID.
**File:** `scripts/audit_same_face.py`

## Composite closure includes empty embedded component glyphs
**Area:** `scripts/audit_same_face.py`
**Symptom:** A candidate with a real component glyph could pass an outline proof when the embedded composite referenced the same GID but its component entry was empty.
**Cause:** The active-GID scan excludes empty glyphs, so component equality was never checked even though an active composite referenced the GID.
**Fix:** Extend the same-GID comparison transitively through every component of every active composite and compare bytes and metrics at those GIDs too.
**File:** `scripts/audit_same_face.py`

## Shared-content diagnostics need a fail-closed inverse index
**Area:** `scripts/measure_type0_funnel.py`, `model/text_commit/inspect.py`
**Symptom:** Scanning every page for every content stream was quadratic, while an unreadable `/Contents` on any page could abort the entire document report.
**Cause:** The diagnostic reused the production single-stream query inside a page/stream loop and read each page before isolating malformed content references.
**Fix:** Build `stream_xref -> owner pages` once, retain an `unknown_pages` set that makes every other page fail closed, and count unreadable pages instead of aborting the document.
**File:** `scripts/measure_type0_funnel.py`

## FontFile2 rewrites can remain invisible to the live MuPDF font cache
**Area:** `scripts/probe_type0_mutation_premises.py`, future Type0 augmentation
**Symptom:** Replacing FontFile2 in place or repointing the descriptor to a fresh stream does not make a previously missing glyph render on the same document handle; save/reopen does.
**Cause:** MuPDF retains font state beyond the rewritten PDF objects. `fitz.TOOLS.store_shrink(100)` refreshes the same handle, but it is process-global and the single-threaded probe cannot prove concurrent worker safety.
**Fix:** Keep live Tier 1b augmentation disabled until coordinator-level exclusion makes the global flush safe or a non-global same-handle refresh is proven. Reopen is evidence, not authorization to swap a live session handle.
**File:** `scripts/probe_type0_mutation_premises.py`

## `xref_set_key` array paths are not descendant-dictionary mutation
**Area:** `model/text_commit/cid_fonts.py`, future Type0 augmentation
**Symptom:** Writing `DescendantFonts/0/DW` through `xref_set_key` destroys the descendant array instead of updating its first dictionary.
**Cause:** PyMuPDF key paths traverse dictionaries, not PDF array indices; `0` is planted as dictionary syntax rather than interpreted as an array element.
**Fix:** Parse the descendant value, modify the dictionary object, serialize it with `serialize_pdf_value`, and rewrite the actual descendant xref or complete inline array.
**File:** `scripts/probe_type0_mutation_premises.py`

## MuPDF readback normalization is wider than the PDF-value serializer contract
**Area:** `model/text_commit/cid_fonts.py`
**Symptom:** A value serialized with hex bytes and an integral float can read back from `xref_object()` as an escaped literal string and an int.
**Cause:** MuPDF is free to reserialize equivalent PDF object syntax, while the bounded parser deliberately does not unescape literal strings and distinguishes ints from floats.
**Fix:** Define the writer contract as type-sensitive `parse_pdf_value(serialize_pdf_value(v))`; use MuPDF readback only for the proven name/ref/int/array/dict leaves and keep byte serialization hex-only.
**File:** `model/text_commit/cid_fonts.py`

## Restore stream bytes before restoring the stream dictionary
**Area:** `scripts/probe_type0_mutation_premises.py`, future multi-object revert
**Symptom:** Restoring a FontFile2 dictionary and then calling `update_stream` changes `/Length` and can add `/Filter`, so object identity is lost even when decoded bytes match.
**Cause:** `update_stream` owns stream compression metadata and rewrites the dictionary after the caller restored it.
**Fix:** Restore decoded bytes with the intended compression first, then restore the saved stream dictionary body; verify decoded bytes, object body, and page fingerprint independently.
**File:** `scripts/probe_type0_mutation_premises.py`
