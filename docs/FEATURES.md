# Features

This document is the behavior-level source of truth for implemented features.

## 1. Document and Session Management

The editor uses a multi-tab session model. Each tab keeps independent page index, zoom, mode, search state, tool state, and dirty state so switching tabs does not leak workflow state between documents. This behavior is coordinated by session-aware model and controller flows. Key functions include `open_pdf(...)`, `list_sessions()`, `activate_session_by_index(...)`, and controller tab switch handlers.

## 2. Modes and Interaction Rules

The supported modes are `browse`, `edit_text`, `add_text`, `rect`, `highlight`, and `add_annotation`. In `edit_text` mode, clicking existing text enters edit on that target while clicking blank area does not create a new textbox. In `add_text` mode, click behavior is dedicated to insertion: if an editor is already open, clicking blank space commits and closes it; if no editor is active, clicking creates a new textbox editor. `rect`, `highlight`, and `add_annotation` are sticky modes: after each operation they remain active for repeated actions. Empty add-new commit is a no-op and does not create history. Mode toolbar buttons are checkable and synchronized to the active mode. Key functions include `set_mode(...)`, `_mouse_press(...)`, `_mouse_release(...)`, `_create_add_text_editor_at_scene(...)`, and `_finalize_text_edit(...)`.

## 3. Text Target Granularity

Text targeting supports `run` and `paragraph` granularity. The UI control `文字選取粒度` defaults to `paragraph`, and startup sync aligns model state to that UI default. For compatibility and overlap safety, when an explicit `target_span_id` is present and mode is not explicitly provided, execution resolves to `run` precision. Key functions include `_on_text_target_mode_changed(...)`, `set_text_target_mode(...)`, `get_text_info_at_point(...)`, and `edit_text(...)` mode resolution.

## 4. Transactional Text Editing

Existing-text editing is transactional: resolve target, build overlap cluster, redact once, replay protected content, insert replacement text, validate output, and rollback on failure. This protects non-target content and maintains deterministic undo/redo through command boundaries. Key functions include `edit_text(...)`, `_resolve_paragraph_candidate(...)`, `_restore_page_from_snapshot(...)`, and `EditTextCommand` execution paths.
Style-only edits are first-class: if only font and/or size changes (without text change), commit still records a history entry and persists to page content.
Clearing all text in an existing inline editor and committing is treated as an intentional delete operation for that target textbox content (not a revert/no-op), and remains fully undo/redo-compatible via `EditTextCommand`.

## 5. Add Textbox as True Page Text

Add-text insertion creates true page content, not temporary overlay objects, so inserted text is immediately detectable by the existing edit workflow. The insertion path uses CJK-capable font defaults and fallback resolution, with UI default family aligned to `Microsoft JhengHei` for better mixed CJK/Latin coverage. Key functions include `sig_add_textbox`, controller `add_textbox(...)`, model `add_textbox(...)`, `_resolve_add_text_font(...)`, and page index rebuild after insertion.

## 6. Inline Editor Focus Lifecycle and Apply/Cancel

Inline text editing uses context-aware focus guards. Opening font/font-size combo popups no longer closes the editor. Focus moves are finalized only when focus leaves the editing context (editor widget + right text panel + combo popup lineage), with deferred focus checks to avoid Qt popup handoff races.

`套用/取消` have explicit behavior:
- `套用`: commit and close editor.
- `取消`: close editor and discard current session edits.

Key functions include `_is_focus_within_edit_context(...)`, `_is_widget_from_text_combo_popup(...)`, `_finalize_if_focus_outside_edit_context(...)`, `_on_text_apply_clicked(...)`, and `_on_text_cancel_clicked(...)`.

## 7. Rotation-Safe Click Anchoring

Textbox placement is anchored to the user’s visual click even when page rotation is `0/90/180/270`. The view captures insertion geometry in visual page coordinates, then the model maps the visual rectangle to unrotated coordinates with derotation mapping, clamps against unrotated page bounds, and inserts using rotation-aware rendering. Key functions include `_build_add_text_visual_rect(...)`, `_visual_rect_to_unrotated_rect(...)`, `_unrotated_page_rect(...)`, and insertion in `add_textbox(...)`.

## 8. Undo/Redo and History Boundaries

Undo/redo uses command history. Add-text insertion is atomic per insertion event via dedicated `AddTextboxCommand`, with strict page snapshot requirements. Undo/redo for add-text restores only the target page snapshot for that event, preventing unrelated page/object mutation. Key functions include `_capture_page_snapshot_strict(...)`, `AddTextboxCommand.execute()`, `AddTextboxCommand.undo()`, and `CommandManager` stack operations.

## 9. Structural Page Operations

Page-level operations include delete, rotate, insert blank page, insert pages from another file, and export selected pages. These operations participate in command history and refresh flows.

Export behavior is now driven by a unified dialog:
- Page scope supports `當前頁` and `指定頁面`.
- `指定頁面` accepts page expressions like `1,3-5`.
- Inline page counter is shown beside the page input (`/ N`) to indicate upper bound.
- DPI options are `72`, `96`, `144`, `300`, `400`, `600`, `1200`, and `2400`.
- Output target supports `PDF` or image export.
- Image save dialog supports `JPEG`, `PNG`, and `TIFF`.
- For image export, multi-page naming uses page-number suffix (`*_p{page_num}`).
- For TIFF, export uses Pillow-backed save path because `fitz.Pixmap.save(...)` does not support TIFF directly.

Key functions include `ExportPagesDialog`, `_export_pages(...)`, `_resolve_image_format(...)`, controller `export_pages(...)`, and model `export_pages(...)`.

## 10. Annotation, Watermark, Search, and OCR

Annotations support rectangle, highlight, free-text, and visibility toggle behavior. Watermark workflows support add/update/remove with persisted metadata behavior. Search supports query and jump-to-result flow. OCR is optional and uses runtime dependency checks with actionable errors when required components are missing. Key functions include `model.tools.annotation.*`, `model.tools.watermark.*`, `model.tools.search.search_text(...)`, and `model.tools.ocr.ocr_pages(...)`.

## 11. Browse Selection and Copy

Browse mode supports drag text selection with text-bounds snapping. Copy is available through `Ctrl+C` and context menu only when selection exists. Selection is cleared by blank-click, mode switch, and scene/document rebuild paths. Key functions include `get_text_in_rect(...)`, `get_text_bounds(...)`, `_start_text_selection(...)`, `_update_text_selection(...)`, and `_copy_selected_text_to_clipboard()`.

## 12. Performance and Progressive Loading

Large PDF handling uses staged loading and batching to preserve interactivity while thumbnails, scene items, and indexes are built. Rendering and refresh scopes are coordinated to avoid blocking behavior and stale geometry. Key functions include controller batch scheduling and view continuous-scene rebuild paths.

Empty-launch startup also uses a shell-first path. When the app starts without an input file, `PDFView` can show a lightweight shell first, defer the heavy sidebars/property inspector until after the first UI turn, then let `main.py` attach and activate the controller only after the view emits `shell_ready`. Direct file-open startup keeps the synchronous path so `open_pdf(...)` still runs against a fully wired controller/view pair. Key functions include `main.run(...)`, `PDFView.ensure_heavy_panels_initialized()`, `PDFView.showEvent()`, `PDFView.shell_ready`, and `PDFController.activate()`.

Structural page operations (insert/delete) avoid full-document text reindex:
- Inserted/imported pages are immediately indexed so their text is editable right away (hit-testing works without manual refresh).
- Pages whose page numbers shifted are marked stale and rebuilt lazily in the background, keeping the UI responsive on large PDFs.
- Undo metadata for these operations uses the model-returned "actual affected pages" after validation, so undo/redo refresh targets stay synchronized with real document state.

Key functions include model `delete_pages(...)`, `insert_blank_page(...)`, `insert_pages_from_file(...)`, `ensure_page_index_built(...)`, `TextBlockManager.shift_after_insert/delete`, controller `_schedule_stale_index_drain(...)`, and snapshot restore via `SnapshotCommand`.

## 13. Text Font Families and CJK Rendering

The text properties font menu supports PDF-safe Latin families and CJK families, including explicit Windows CJK selections:
- `Microsoft JhengHei`
- `PMingLiU`
- `DFKai-SB`

For htmlbox insertion, model CSS generation can inject `@font-face` rules when local Windows font files are present. This prevents different CJK selections from collapsing to the same fallback face in common environments.

Key functions include `_qt_font_to_pdf(...)`, `_pdf_font_to_qt(...)`, `_resolve_add_text_font(...)`, `_font_face_css_for_token(...)`, `_convert_text_to_html(...)`, and `_build_insert_css(...)`.

## 14. Keyboard Shortcuts and Save Prompt Keys

Core keyboard shortcuts include `Ctrl+Z` (undo), `Ctrl+Y` (redo), `Ctrl+S` (save), `Ctrl+Shift+S` (save as), and `F2` (enter edit-text mode).  
`Esc` handling follows priority rules: close active editor/dialog first (and keep current mode), otherwise switch non-browse mode back to `browse`, otherwise run existing browse fallback (for example search sidebar close).  
When closing with unsaved changes, confirmation dialogs provide explicit key hints and single-key actions: `Y` to save and `N` to discard (with `Esc` as cancel).

## 15. Native Printer Properties Entry

In the unified print dialog, the printer selector row includes a `屬性` button beside the printer combo. On supported systems, this opens the OS-native printer properties/preferences dialog for the currently selected printer so users can adjust vendor-specific settings with system tools. Returned/default preferences are synchronized back into dialog controls (`paper_size`, `orientation`, `duplex`, `color_mode`, `dpi`, `copies`).
Paper tray is not exposed as an app-side field. Tray and vendor/private options are inherited from system/native properties and passed through by keeping tray source unmodified in app defaults.
On Windows, per-user DEVMODE persistence is attempted via `SetPrinter` level 9 so vendor/private properties set in `屬性` can continue to apply to later jobs without requiring queue-admin permissions.
Hardware-field precedence is touch-based. `paper_size`, `orientation`, `duplex`, and `color_mode` inherit printer defaults until the user explicitly changes them in the app dialog; once touched, the current job overrides the native value. If a printer default for one of those hardware fields is unavailable, the dialog keeps the current UI value and treats it as an explicit override for that job.
For some Windows vendor drivers, native properties update only private `DriverExtra` data and do not refresh public DEVMODE fields such as `dmColor` or `dmDefaultSource`. In that case, the app does not pretend it knows the exact native value: `color_mode` is shown as `依系統屬性`, while tray selection remains hidden from the app UI and continues to pass through from the system driver.
Preview rendering is guarded against temporary invalid input. If page-range input becomes invalid during live editing, preview errors are shown inside the dialog and the UI event path keeps running.
Print preview no longer requires building the full print snapshot before the dialog opens. Preview pages can be rendered directly from the live document, while the full print snapshot/temp PDF is generated only after the user confirms printing.
Job-level settings remain app-owned regardless of native properties: `copies`, `dpi`, `collate`, page range, page subset, reverse order, and scaling are always taken from the unified print dialog.

## 16. Print Lifecycle Resilience (Windows)

Windows print submission can hang inside the GUI process due to OS/driver stack behavior. The app protects responsiveness and shutdown correctness with the following behavior:

- From the moment the user confirms printing, document capture (PDF bytes) runs in a background thread and does not block the UI thread.
- Windows raster submission is performed in a helper subprocess (child Python process) so driver/GDI stalls do not freeze the main UI process.
- The helper emits periodic heartbeat messages during long rendering/submission so legitimate long jobs are not misclassified as stalled.
- The main app monitors helper activity and surfaces a “not responding” print state after a stall threshold, offering a “terminate print job” action that kills only the helper subprocess and restores the app to normal state.
- If the user attempts to close the window while printing is active, close is deferred and the UI stays alive; the window auto-closes after printing finishes.

Key files/functions:
- Controller entry: `controller/pdf_controller.py` `print_document()` and print lifecycle helpers.
- Helper protocol and job payload: `src/printing/helper_protocol.py` (`PrintHelperJob`) and `src/printing/helper_main.py`.
- Subprocess runner: `src/printing/subprocess_runner.py`.

## 17. Fullscreen Viewing

Fullscreen is available from any mode via `F5` or the top-right `全螢幕` button. Entering fullscreen cancels any active inline editor or partial draw/drag state, clears transient selection/search UI state, and forces `browse` mode before showing the fullscreen window. The fullscreen view hides all chrome (toolbars, tab bar, sidebars, status bar) and fits the current page using a contain scale so the entire page is visible. A top-edge hover reveals a small `X` exit affordance; `Esc`, `F5`, and the `X` button all exit fullscreen. While fullscreen is active, tab switching is allowed and each visited tab restores its pre-fullscreen zoom and scroll anchor on exit.

Key functions include controller `enter_fullscreen()`, `exit_fullscreen()`, `toggle_fullscreen()`, view `enter_fullscreen_ui()`, `exit_fullscreen_ui()`, `cancel_interaction_for_fullscreen()`, and viewport anchor capture/restore helpers.

## 18. Merge PDFs (頁面 Tab)

This section follows `docs/Methodology_for_Writing_Docs.md` as behavior-level source of truth.

User flow:
- From the `頁面` tab, user opens a modal merge dialog with a reorderable list, `選擇檔案`, `刪除檔案`, and `確認合併`.
- The current document is always present in the list as a locked row:
  - It participates in ordering.
  - It cannot be removed.
- `選擇檔案` adds files only via the OS file picker; reopening the picker appends new picks to the end.
- Users can reorder items via drag-and-drop (including multi-select reorder); add/remove operations must preserve the user’s current custom order.
- `刪除檔案` removes only selected unlocked rows.
- `確認合併` is disabled if there are no valid merge inputs.

Input handling:
- Password-protected PDFs prompt for password; wrong password supports retry; cancel skips that file.
- Files that are not valid PDFs (including “.pdf but not a PDF”) are rejected with a clear message and skipped.
- Other unreadable PDFs are also rejected with a clear message and skipped.
- Large batch add shows a progress indicator while validating/adding.

Outputs:
- `建立新檔`: prompts output path, saves immediately, opens merged result as a new tab.
- `合併到目前檔案`: merges into the active document, remains on that tab, and marks the document as unsaved (dirty).

Regression guardrails:
- The list-order contract is covered by tests in `test_scripts/test_pdf_merge_workflow.py` (reorder then add/remove must not revert).

## 19. Optimize PDF Copy (檔案 Tab)

The `檔案` tab includes `另存為最佳化的副本`, which always writes a new optimized PDF copy and never overwrites the active document through the optimizer flow.

Behavior:
- The optimizer opens a modal dialog with presets `快速`, `平衡`, `極致壓縮`, and `自訂`; default is `平衡`.
- Manual edits to optimizer controls switch the preset label to `自訂`.
- Supported controls are limited to implemented behavior: image downsampling / recompression, font subsetting, metadata removal, and cleanup / compression flags.
- Unsupported Acrobat-style controls are hidden and tracked in `docs/unsupported-optimizer.md`.
- `審計空間使用報告` is on-demand only for the current source document; it does not auto-refresh while options change.
- The audit report UI uses a table and stacked proportion bar. Hovering a bar segment shows the object type, and the current hover label is displayed above the bar.
- In the audit table, `數量` means unique referenced object count for that category (for example unique xref count for images / fonts / content streams), not visual occurrence count on page.
- Saving an optimized copy opens the new file as a new tab and leaves the original tab/session untouched.
- The optimizer rejects output paths that would overwrite the current file or any already-open file.
- Completion message shows human-readable size units (`KB`/`MB`/`GB`) with raw byte values for original / optimized / saved sizes.
- Optimization runs off the GUI thread. While optimization is in progress, controller pauses background scene/index batch loading for the active tab so the optimizer is not competing with those background tasks.
- For image-heavy PDFs, image transcoding can use multiple processes to accelerate JPEG recompression and downsampling. Clean file-backed documents can be processed directly from the source path; dirty/in-memory documents preserve unsaved edits by extracting image bytes from the working snapshot and only parallelizing the CPU-heavy transcode stage.
- Architecture-level workflow graph is documented in `docs/ARCHITECTURE.md` section “Optimize PDF Copy (檔案 Tab)”.

Key functions include `OptimizePdfDialog`, `PDFController.start_optimize_pdf_copy()`, `build_pdf_audit_report()`, and `save_optimized_copy()`.

Implementation note: optimizer internals are implemented in `model/pdf_optimizer.py`, while `model/pdf_model.py` keeps the stable facade used by UI/tests.
