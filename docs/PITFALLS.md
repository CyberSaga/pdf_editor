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

## Async thumbnail QThread coordinator was removed (R4) — keep thumbnails synchronous
**Area:** `controller/pdf_controller.py` (R4-01…R4-04)
**Symptom:** The R4.3 `ThumbnailCoordinator` could paint a cancelled tab's queued batch into the newly-active tab (the `batch_ready` signal carried only `(gen, start_index, images)` and `gen` collides across sessions), serialized the snapshot on the GUI thread, retained a decrypted snapshot after tab close, and left the old worker running on sync fallback.
**Cause:** Per-session generation tokens are not globally unique, and the coordinator's session id was a mutable field overwritten by each `try_start`.
**Fix:** Removed the coordinator entirely; `_schedule_thumbnail_batch` renders synchronously in bounded `QTimer` batches guarded by `_thumb_gen_by_session` (cannot cross-paint by construction). Separately, `on_tab_close_requested` clears `_worker_snapshot_cache` for the departing session (R4-03) so decrypted bytes don't outlive it. Do not reintroduce an async thumbnail path without a globally-unique job token and a close/switch-time cancel+cache-clear.
**File:** `controller/pdf_controller.py`

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
