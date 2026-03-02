# PDF Editor Architecture

## 1. Overview

The project uses MVC with built-in tool extensions.

```text
+-------------------+         signals          +---------------------+
|       View        | -----------------------> |     Controller      |
| (Qt widgets/UI)   | <----------------------- | (flow coordination) |
+-------------------+        updates           +----------+----------+
                                                       calls |
                                                             v
                                                +------------+------------+
                                                |          Model          |
                                                | (docs, sessions, edits) |
                                                +------------+------------+
                                                             |
                                               delegates     |
                                                             v
                                                +------------+------------+
                                                |       ToolManager       |
                                                | annotation/watermark/   |
                                                | search/ocr extensions   |
                                                +-------------------------+
```

Entry wiring happens in `main.py`, which instantiates `PDFModel`, `PDFView`, and `PDFController`.

## 2. Layer Responsibilities

### 2.1 Model (`model/pdf_model.py`)

Model owns document correctness and persistence behavior. It manages sessions (`DocumentSession`), document handles (`fitz.Document`), text hit-testing, text edit transactions, add-text insertion, save/save-as pipeline, and snapshot helpers used by history commands.

Important text APIs include `get_text_info_at_point(...)`, `edit_text(...)`, `add_textbox(...)`, and `set_text_target_mode(...)`.
The text rendering path now resolves style tokens and supports custom CJK-family embedding for insert-html flows (for example `microsoft jhenghei`, `pmingliu`, `dfkai-sb`) when local font files are available.

Snapshot APIs include `_capture_doc_snapshot()`, `_restore_doc_from_snapshot(...)`, `_capture_page_snapshot(...)`, `_capture_page_snapshot_strict(...)`, and `_restore_page_from_snapshot(...)`.

### 2.2 Commands (`model/edit_commands.py`)

Command classes define history boundaries:
- `EditTextCommand` for existing text edits.
- `AddTextboxCommand` for atomic add-text insertion.
- `SnapshotCommand` for document-level structural operations.
- `CommandManager` for undo/redo stacks.

`AddTextboxCommand` stores strict before-page snapshots, captures after-page snapshots on first execute, and restores only the target page on undo/redo.

### 2.3 Controller (`controller/pdf_controller.py`)

Controller is the only mutation coordinator between View and Model. It wires view signals, normalizes mode transitions, creates/executes commands, controls refresh scopes, and preserves per-session UI state.

Mode registry includes `browse`, `edit_text`, `add_text`, `rect`, `highlight`, and `add_annotation`.

At startup, controller syncs text-target granularity from the view control to model state so runtime default behavior matches the UI default.

### 2.4 View (`view/pdf_view.py`)

View owns widgets, scene interactions, and signal emission. It does not mutate model business state directly.

The text editor state is split by intent:
- `edit_existing` for updating existing text.
- `add_new` for inserting new page text.

Inline editor finalization is guarded by focus context:
- Focus transitions inside text-edit context (editor widget, text property panel, combo popups) keep the session alive.
- Focus transitions outside the edit context finalize the current inline editor.
- A short deferred check avoids false finalize during Qt popup handoff.

Text style controls include explicit commit/cancel buttons:
- `套用` commits current inline edit.
- `取消` discards current inline edit session changes.

Mode behavior boundary:
- In `edit_text`, blank-click does not create new textbox.
- In `add_text`, blank-click commits open editor; otherwise it creates a new textbox editor.
- In `rect`, `highlight`, and `add_annotation`, each tool is sticky for repeated operations.
- Mode actions are checkable and remain synchronized with the active mode state.
- `Esc` priority is: close active editor/dialog first (keep mode), else revert non-browse mode to `browse`, else run browse fallback behavior.

## 3. Runtime Flows

### 3.1 Open / Activate / Close

View emits open/switch/close intent. Controller calls model session operations. Model opens/activates/cleans session and tool hooks. Controller restores session UI state and schedules rendering/index batches.

### 3.2 Edit Existing Text

View hit-tests text and opens editor with target metadata. On commit, view emits `sig_edit_text(...)`. Controller creates `EditTextCommand` with page snapshot. Model runs transactional edit pipeline and page index rebuild. Controller refreshes affected view scope. Commit criteria include text, position, font, and size deltas so style-only edits are persisted.

### 3.3 Add New Textbox

View computes visual insertion rect and opens add editor. On commit, view emits `sig_add_textbox(...)`. Controller captures strict page snapshot and executes `AddTextboxCommand`. Model maps visual-to-unrotated geometry, clamps bounds, inserts page text, and rebuilds page index. Controller refreshes page render so new text is immediately editable through existing edit flow.

### 3.4 Undo / Redo

Controller invokes command manager undo/redo. Commands restore page/doc snapshots according to command type. Controller then refreshes the minimal required UI scope and tooltip descriptions.

### 3.5 Export Pages

View opens `ExportPagesDialog` and collects all export arguments in one pass:
- pages (`當前頁` or parsed `指定頁面`)
- output type (`PDF` or image)
- dpi (`72`..`2400`)
- image format (`jpg` / `png` / `tiff`)

View emits `sig_export_pages(pages, path, as_image, dpi, image_format)`. Controller passes through to model `export_pages(...)`.

Model behavior:
- Image export renders by `scale = dpi / 72.0`.
- `jpg/png` use `fitz.Pixmap.save(...)`.
- `tiff` uses Pillow-backed `fitz.Pixmap.pil_save(..., format="TIFF")` because TIFF is not supported by plain `Pixmap.save`.
- Multi-page image export uses page-number suffix naming (`*_p{page_num}`).

## 4. Coordinate and Rotation Strategy

Add-text insertion uses visual coordinates from the current view. Model converts visual rectangle corners through derotation mapping into unrotated page space, clamps against unrotated page bounds (`cropbox`/`mediabox` fallback), and inserts with rotation-aware parameters. This keeps placement stable at the visual click location for page rotation `0/90/180/270`.

## 5. Tool Extension Architecture

Built-in tools are statically registered in `ToolManager` and accessed via `model.tools.<tool>.*`.

Current registration order:
1. Annotation
2. Watermark
3. Search
4. OCR

Tool lifecycle hooks cover session open/close/saved behavior, unsaved-change checks, overlay rendering, and save-time transformations.

## 6. Printing Subsystem

Printing is implemented under `src/printing/*` (dialog, dispatcher, layout, selection, renderer, platform drivers). Controller entry is `PDFController.print_document()`.

## 7. Guardrails

View must not directly mutate model. Controller owns mutation orchestration. Model owns document correctness and persistence. Behavior-level feature truth is in `docs/FEATURES.md`; root-cause/fix history is in `docs/solutions.md`.
