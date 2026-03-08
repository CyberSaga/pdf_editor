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
Application-level logging configuration is also owned by `main.py`; importable modules only acquire named loggers and do not call `logging.basicConfig(...)` at import time.
For empty startup (no CLI PDF paths), `main.py` now follows a shell-first lifecycle: show `PDFView`, let the view hydrate deferred panels, wait for `PDFView.shell_ready`, then attach/activate the controller. Direct CLI-open startup keeps the synchronous attach/activate/open path.

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

Controller is the only mutation coordinator between View and Model. It normalizes mode transitions, creates/executes commands, controls refresh scopes, and preserves per-session UI state.

Mode registry includes `browse`, `edit_text`, `add_text`, `rect`, `highlight`, and `add_annotation`.

Controller activation is now explicit. `PDFController.__init__()` keeps startup cheap, while `PDFController.activate()` performs view-signal wiring, print subsystem setup, and startup sync such as text-target granularity alignment. This keeps the no-document startup shell decoupled from full controller behavior until the UI is ready.

### 2.4 View (`view/pdf_view.py`)

View owns widgets, scene interactions, and signal emission. It does not mutate model business state directly.
For empty startup it can defer building heavy sidebars/property panels, then emit `shell_ready` only after deferred hydration completes.

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

View hit-tests text and opens editor with target metadata. On commit, view emits `sig_edit_text(...)`. Controller creates `EditTextCommand` with page snapshot. Model runs transactional edit pipeline and page index rebuild. Controller refreshes affected view scope. Commit criteria include text, position, font, and size deltas so style-only edits are persisted. Empty text commits from existing-text edit are valid delete intents: the target textbox content is redacted and not reinserted, and history remains undo/redo-safe.

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
The unified print dialog also exposes native printer properties through driver-dispatched calls (`PrintDispatcher.open_printer_properties(...)`), enabling OS/vendor preference dialogs from the same workflow. The dialog caches the latest returned printer preferences and tracks only user-touched hardware fields in-app. Effective print options are built by merging native defaults with current UI state: untouched `paper_size`, `orientation`, `duplex`, and `color_mode` inherit the printer preference snapshot; touched fields are marked in `PrintJobOptions.override_fields`. If a native value for one of those hardware fields is unavailable, the dialog falls back to the current UI value and marks that field overridden for the job. On Windows, preference collection merges printer DEVMODE data from `GetPrinter(..., 2/8/9)` so per-user defaults from native `屬性` can sync back into the app UI even when a driver exposes some values only through user-specific defaults. When the native properties dialog is canceled, the driver returns `None` and the unified dialog preserves both current UI values and touched-state instead of resyncing from printer defaults.
Tray and other non-UI driver preferences remain pass-through system defaults because dialog output keeps `paper_tray="auto"`. The app no longer renders a tray/system-properties section in the dialog UI. On Windows, the driver attempts per-user preference persistence (`SetPrinter` level 9) so vendor/private DEVMODE settings can carry into later jobs without queue-admin rights. When a driver changes only private `DriverExtra` data and leaves public DEVMODE fields stale, the driver marks those fields opaque; the dialog then shows `color_mode="system"` (`依系統屬性`) instead of incorrectly echoing stale public values.
`PrintJobOptions.override_fields` is the shared contract between the dialog and print backends. The Qt bridge applies page layout only when `paper_size` or `orientation` is overridden, and applies duplex/color mode only when those fields are marked overridden. The Linux/macOS CUPS path follows the same rule by omitting duplex/color command options unless the app explicitly touched them. This keeps app-owned job settings (`copies`, `dpi`, `collate`, page range, scaling) unconditional while preventing silent overrides of native hardware defaults.
The Qt bridge sets page layout before print activation and does not mutate layout after `QPainter.begin(...)`, preventing active-printer warnings (`QPrinter::setPageLayout: Cannot be changed while printer is active`).
Preview rendering and final submission are intentionally split. `UnifiedPrintDialog` can render preview pages from a live-document provider callback, so opening the dialog does not require prebuilding a full print snapshot. `PDFController.print_document()` builds the full print snapshot/temp PDF only after the dialog returns `Accepted`, avoiding wasted serialization and disk I/O on cancel.
Preview refresh is also guarded at the dialog boundary: resize / wheel / row-change paths flow through a safe preview wrapper that converts temporary option-building errors (for example invalid custom page range while typing) into inline preview messages rather than unhandled UI-event exceptions.

### 6.1 Windows Spooler Isolation (Helper Subprocess)

On Windows, the Qt/GDI print submission path can stall the entire GUI process even when invoked from a `QThread` because the OS print stack can block inside the process. To protect application responsiveness and lifecycle stability, Windows raster submission is isolated into a helper subprocess:

- Main app prepares a job (immutable inputs): capture current document bytes, write an `input.pdf` into a temp work dir, and serialize a `PrintHelperJob` into `job.json`.
- Main app launches a child Python process via `QProcess` using `sys.executable` and runs `python -m src.printing.helper_main <job.json>`.
- Child process performs end-to-end submission: apply watermarks (if any), render/rasterize, and submit to either `output_pdf_path` (PDF output) or the OS spooler.
- Progress and terminal status are emitted as line-delimited JSON on stdout (see `src/printing/helper_protocol.py`). The main app parses these events in `src/printing/subprocess_runner.py`.

The helper uses shared user-facing message constants from `src/printing/messages.py` so controller UI and helper progress stay consistent.

### 6.2 Lifecycle Guardrails (Close, Stall, Terminate)

Controller print submission is explicitly lifecycle-aware:

- Snapshot/input capture runs off the GUI thread from the moment the user confirms printing.
- Worker-thread callbacks are marshaled back to the GUI thread before touching UI objects (see `_PrintWorkerBridge` in `controller/pdf_controller.py`).
- If the user closes the app while printing is active, the close request is deferred and the UI remains alive; the window auto-closes after the submission finishes.
- The subprocess runner monitors activity and emits a stalled state after a no-progress threshold; UI surfaces a terminate option that kills only the helper subprocess and returns the app to normal without requiring a restart.

## 7. Guardrails

View must not directly mutate model. Controller owns mutation orchestration. Model owns document correctness and persistence. Behavior-level feature truth is in `docs/FEATURES.md`; root-cause/fix history is in `docs/solutions.md`.
