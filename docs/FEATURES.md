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
