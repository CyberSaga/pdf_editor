# PDF Editor Architecture

## 1. Overview

The application uses an MVC design:

- `Model`: PDF document/session lifecycle, text editing core, save pipeline, and command history.
- `View`: Qt UI state and rendering widgets (tabs, tool panels, canvas, dialogs).
- `Controller`: coordinates UI events and model calls, preserves per-tab UI state, triggers refresh.

Entry point:

- `main.py` wires `PDFModel`, `PDFView`, and `PDFController`.

## 2. Core Layers

### 2.1 Model Layer

Main file:

- `model/pdf_model.py`

Responsibilities:

- Multi-session registry (`DocumentSession`) and active-session switching.
- `fitz.Document` ownership per session.
- Text edit transaction pipeline (`edit_text`) with verification and rollback.
- Page operations (delete, rotate, insert blank, export, render helpers).
- Save/save-as orchestration (including overwrite/collision behavior).
- Command integration via `CommandManager`.
- Delegation to built-in tools via `self.tools` (`ToolManager`).

Session model (`DocumentSession`) stores:

- `session_id`, paths, `doc`
- `TextBlockManager`
- `CommandManager`
- per-session edit bookkeeping (`pending_edits`, `edit_count`)

Dirty state rule:

- `session.command_manager.has_pending_changes() or tools.has_unsaved_changes(session_id)`

Related model components:

- `model/text_block.py`: block/run/paragraph indexing and lookup.
- `model/edit_commands.py`: `EditTextCommand`, `SnapshotCommand`, `CommandManager`.

### 2.2 Built-in Tool Extensions

Directory:

- `model/tools/`

Files:

- `base.py`: `ToolExtension` lifecycle/render/save hooks.
- `manager.py`: `ToolManager` static registration and fan-out.
- `annotation_tool.py`
- `watermark_tool.py`
- `search_tool.py`
- `ocr_tool.py`

Registration order in `ToolManager`:

1. Annotation
2. Watermark
3. Search
4. OCR

Tool lifecycle hooks used by model:

- `on_session_open`
- `on_session_close`
- `on_session_saved`
- `has_unsaved_changes`
- `needs_page_overlay` / `apply_page_overlay`
- `prepare_doc_for_save`

Public tool APIs used by app:

- `model.tools.annotation.*`
- `model.tools.watermark.*`
- `model.tools.search.search_text(...)`
- `model.tools.ocr.ocr_pages(...)`

### 2.3 Controller Layer

Main file:

- `controller/pdf_controller.py`

Responsibilities:

- Connects Qt signals to model operations.
- Keeps UI API stable while routing tool calls through `model.tools.*`.
- Maintains per-session UI state (page, zoom, search, mode).
- Synchronizes mode when switching tabs/sessions.
- Wraps edit/structural actions into command objects for undo/redo.
- Coordinates page/thumbnail/continuous rendering refresh.
- Handles print workflow through `src/printing/*`.

### 2.4 View Layer

Main file:

- `view/pdf_view.py`

Responsibilities:

- Qt widgets, toolbars, panels, tabbed document UI.
- Emits user-intent signals; does not mutate model directly.
- Hosts canvas and edit overlays.
- Displays search/OCR/watermark/annotation interactions via controller callbacks.

## 3. Runtime Flows

### 3.1 Open / Activate / Close

1. View emits open request.
2. Controller calls `model.open_pdf(path, append=True|False)`.
3. Model creates/activates session and calls `tools.on_session_open(...)`.
4. Controller renders active session and restores session UI state.
5. On close, controller confirms unsaved changes; model calls `tools.on_session_close(...)`.

### 3.2 Text Edit (Undoable)

1. View emits edit intent (including `target_span_id` and `target_mode` when available).
2. Controller captures snapshot and executes `EditTextCommand`.
3. `PDFModel.edit_text(...)` runs transaction:
   - target resolution (run/paragraph),
   - safe redaction + protected replay,
   - insertion strategy,
   - validation (`target_present`, protected spans),
   - rollback on failure,
   - index rebuild.
4. Command manager tracks undo/redo stacks.

### 3.3 Render / Print

- `PDFModel.get_page_pixmap(...)` delegates to `ToolManager.render_page_pixmap(...)`.
- Tools may inject overlays (notably watermark) by purpose (`view`, `snapshot`, `print`).
- `PDFModel.build_print_snapshot()` delegates to tool manager to build printable bytes.

### 3.4 Save

1. Model applies pending redactions/cleanup.
2. Model asks `tools.prepare_doc_for_save(session_id)` for save-time transformed doc if needed.
3. Model writes output and marks command manager saved.
4. Model calls `tools.on_session_saved(session_id)`.

## 4. Printing Subsystem

Directory:

- `src/printing/`

Key pieces:

- `dispatcher.py`: printer discovery/dispatch and job routing.
- `print_dialog.py`: unified print dialog and options.
- `page_selection.py`, `layout.py`: page selection and layout mapping.
- platform drivers in `src/printing/platforms/`.

Controller entry:

- `PDFController.print_document()`

## 5. Boundary Rules

- View does not call model directly for business mutations; it emits signals.
- Controller is the only coordinator between View and Model.
- Model owns document data and edit/save correctness.
- Tool-specific state and logic live in tool extensions, keyed by `session_id`.
- Built-in tools are statically registered; no runtime plugin discovery in current design.
