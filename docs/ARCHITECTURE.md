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

Entry wiring happens in `main.py`. CLI-open startup instantiates `PDFModel`, `PDFView`, and `PDFController` immediately; empty startup instantiates only `PDFView` until a document is requested.
Application-level logging configuration is also owned by `main.py`; importable modules only acquire named loggers and do not call `logging.basicConfig(...)` at import time. Some modules may still apply narrow logger-level adjustments for extremely noisy third-party debug channels (for example PIL PNG chunk parsing).
For empty startup (no CLI PDF paths), `main.py` shows `PDFView` first and defers backend creation. When the user requests a document (open or drop), the view queues paths and emits `sig_backend_bootstrap_requested`; `main.py` then creates model/controller, attaches/activates them, and drains queued open paths. Direct CLI-open startup keeps the synchronous attach/activate/open path.
The CLI entry point in `main.py` now has an `argparse` surface: positional PDF paths open as tabs, `--merge OUTPUT <inputs...>` runs a headless `fitz`-only merge and exits before Qt widget bootstrap, and real app launches use a per-user single-instance bridge (`QLocalServer` / `QLocalSocket`) so later invocations forward file paths into the already-running window instead of spawning duplicate editor windows.

App identity is **CyberSagaPDF** (org `CyberSaga`): `main.py` sets the Windows AppUserModelID (`CyberSaga.CyberSagaPDF`) and the application icon (`view/icons.py:load_app_icon` → `view/resources/app_icon.ico`); `utils/preferences.py` stores QSettings under `CyberSaga/CyberSagaPDF` and migrates each known key from the legacy `pdf_editor` namespace when it is missing in the new store; `utils/single_instance.py` probes the legacy `pdf_editor_singleinstance_*` server name as a fallback so a new build still forwards into an older running instance. Optional Windows `.pdf` association is handled by `scripts/windows_file_association.ps1` (HKCU-only, snapshot/rollback, never touches the protected UserChoice). The identity strings are consolidated in the dependency-free leaf `utils/app_identity.py` (R1.2; mirrors `utils/theme_ids.py`), which `main.py`, `utils/preferences.py`, and `utils/single_instance.py` import; the `.ps1` cannot import Python, so it mirrors the leaf with a header sync-note. The IPC prefixes and the legacy QSettings org/app are compatibility values kept byte-identical — a drift silently breaks open-file forwarding to a running instance or the one-time settings migration.

## 2. Layer Responsibilities

**CI enforcement (2026-07-02):** the boundaries below are checked by `.github/workflows/ci.yml`'s `layer-boundaries`
job — `[tool.importlinter]` in `pyproject.toml` (advisory until the known violations in `TODOS.md` clear) plus a
blocking `threading.Thread` grep over `view/`+`controller/`.

### 2.1 Model (`model/pdf_model.py`)

Model owns document correctness and persistence behavior. It manages sessions (`DocumentSession`), document handles (`fitz.Document`), text hit-testing, text edit transactions, add-text insertion, save/save-as pipeline, and snapshot helpers used by history commands.

Important text APIs include `get_text_info_at_point(...)`, `edit_text(...)`, `add_textbox(...)`, and `set_text_target_mode(...)`.
The text rendering path now resolves style tokens and supports custom CJK-family embedding for insert-html flows (for example `microsoft jhenghei`, `pmingliu`, `dfkai-sb`) when local font files are available.
Browse-mode selection is also model-owned: legacy rectangle helpers still exist, but the primary browse drag path now uses a run-anchored resolver. Mouse-down locks the start run, mouse-up resolves the end run, boundary lines stay partial, and only the fully covered lines between them expand to whole-line units. `get_text_info_at_point(...)` now has a strict-hit option (`allow_fallback=False`) so browse selection can reject coarse block fallback hits while other flows keep backward-compatible text-block behavior.
Object manipulation correctness is also model-owned. App-owned textboxes/rectangles/images still use hidden annotation markers for identity, while native PDF images are discovered from parsed page content stream operators. Their primary bbox/rotation data comes from the parsed `cm` transform, with per-xref placement APIs only used as a fallback when a safe `cm` is unavailable. Native-image move/resize/rotate/delete rewrites the target image invocation operators instead of redacting the painted bbox, so overlapping text/graphics are preserved.

Snapshot APIs include `_capture_doc_snapshot()`, `_restore_doc_from_snapshot(...)`, `_capture_page_snapshot(...)`, `_capture_page_snapshot_strict(...)`, and `_restore_page_from_snapshot(...)`.
`build_print_snapshot(dest: Path) -> None` (delegating to `ToolManager.build_print_snapshot(dest)`) writes the print-input PDF directly to a destination path instead of returning bytes, so the print path never holds a full serialized copy of the document in memory. The former `capture_print_input_pdf_bytes()` helper was removed with this change (the print submission worker was its only caller).

#### Transactional Text Editing Phases (Helper Boundaries)

`PDFModel.edit_text(...)` is implemented as a transactional pipeline and is structured into independently testable helper phases:

- Target-mode resolution: `_resolve_effective_target_mode(...)`
- Phase 1 (resolve): `_resolve_edit_target(...)`
- Phase 2 (mutate): `_apply_redact_insert(...)`
- Phase 3 (verify + index): `_verify_rebuild_edit(...)`
- Horizontal single-line edits that still fit on one line use an origin-preserving `insert_text(...)` fast path inside `_apply_redact_insert(...)`; wrapped / dragged / vertical cases still use the existing htmlbox flow.
- Paragraph-mode edits that span ≥2 distinct span colors use `_build_multi_style_html(...)` (difflib char-level mapping) to rebuild per-run color fidelity. This path is gated on `preserve_multi_style` and takes priority over the single-line fast path.

This structure is enforced by per-phase unit tests using real PyMuPDF documents (no mocks) in `test_scripts/test_edit_text_helpers.py`.

#### Structural Page Operations and Text Indexing

Structural operations (insert/delete pages) are model-owned correctness logic. The model must sanitize dirty inputs and return the actual effected pages so the controller can synchronize UI and undo metadata without re-deriving page numbers.

Key contracts:
- `delete_pages(pages) -> list[int]` returns the actual deleted pages (1-based, sorted).
- `insert_blank_page(position) -> list[int]` returns the actual inserted page number (1-based).
- `insert_pages_from_file(source_file, source_pages, position) -> list[int]` returns the actual inserted target page numbers (1-based, sorted).

Text index lifecycle:
- Page text indices live in `TextBlockManager` ([`model/text_block.py`](../model/text_block.py)). The
  stateless parsing layer — geometry helpers, the `TextBlock`/`EditableSpan`/`EditableParagraph`
  dataclasses, and the pure fitz-dict→dataclass transforms — lives in
  [`model/text_block_parsing.py`](../model/text_block_parsing.py) (R3.1). It owns **no** index state;
  `TextBlockManager` keeps every page-keyed index and delegates the transforms. `text_block` re-exports
  the dataclasses and `rotation_degrees_from_dir`, so `from model.text_block import …` is unchanged.
- Each cached page has a state: `"missing" | "clean" | "stale"`.
- Structural ops shift cached keys and mark shifted pages `"stale"` (cheap), instead of eagerly rebuilding the entire document.
- Any immediate edit/search path calls `model.ensure_page_index_built(page_num)` which rebuilds missing/stale pages on-demand.

### 2.2 Commands (`model/edit_commands.py`)

Command classes define history boundaries:
- `EditTextCommand` for existing text edits.
- `AddTextboxCommand` for atomic add-text insertion.
- `SnapshotCommand` for document-level structural operations.
- `CommandManager` for undo/redo stacks.

`EditTextCommand` now carries an `EditTextResult` outcome (`success`, `no_change`, `target_block_not_found`, `target_span_not_found`). When execution does not succeed, `CommandManager.execute()` / redo skip undo-stack recording for that command instead of creating a no-op history entry.
`AddTextboxCommand` stores strict before-page snapshots, captures after-page snapshots on first execute, and restores only the target page on undo/redo.

Undo-stack memory budget: in addition to the count cap (`MAX_UNDO_STACK_SIZE = 100`), `CommandManager` enforces `MAX_UNDO_STACK_BYTES = 512 MiB` over the sum of each command's `_byte_size()` (snapshot payload bytes; base `EditCommand` reports 0). `_trim_undo_stack_if_needed()` evicts oldest commands first and decrements `_saved_stack_size` per eviction (clamped at 0) so `has_pending_changes()` stays correct. After every push (execute/record/redo), `_dedup_top_snapshot_pair()` shares a single `bytes` object between two adjacent `SnapshotCommand`s whose `after`/`before` boundary snapshots are equal — safe because `bytes` is immutable and `_restore_doc_from_snapshot` copies on `fitz.open("pdf", ...)`.

### 2.3 Controller (`controller/pdf_controller.py`)

Controller is the only mutation coordinator between View and Model. It normalizes mode transitions, creates/executes commands, controls refresh scopes, and preserves per-session UI state.
Document-tab refresh also synchronizes the active session's Save As suggestion into the view, so the view-owned `另存PDF` dialog opens with the current tab's path/name instead of a blank or stale filename.

Mode registry includes `browse`, `edit_text`, `add_text`, `rect`, `highlight`, and `add_annotation`.

Controller activation is now explicit. `PDFController.__init__()` keeps startup cheap, while `PDFController.activate()` performs view-signal wiring, print subsystem setup, and startup sync such as text-target granularity alignment. This keeps the no-document startup shell decoupled from full controller behavior until the UI is ready.

For performance on large PDFs, controller schedules heavy work in small batches (thumbnail rasterization, visible-page rendering, and text indexing). Continuous mode now uses a placeholder-first pipeline: the view allocates full-document scene geometry immediately from lightweight placeholders, then the controller progressively renders only the viewport window (plus a small prefetch margin) so the UI stays interactive even on 1000+ page PDFs. Open-time priority is now explicit: the initial visible page is allowed to reach high quality before background thumbnail batches and sidebar scans start, with a short fallback timer so background work still resumes if that high-quality upgrade never arrives. After structural operations or snapshot restore, controller also drains stale page indices in the background (`_schedule_stale_index_drain`), while the active/visible pages remain immediately usable via the model's `ensure_page_index_built(...)` contract.
Search requests now use a private snapshot byte buffer captured on the GUI thread before the worker starts, so background search never reads the live `fitz.Document`. Completed searches store their accumulated hits back into `SessionUIState.search_state`, which lets tab switches restore finished result lists per tab; `_cancel_search()` only clears search state when it aborts an in-flight partial search. The async-search runtime — the `_SearchWorker`/`_SearchBridge` QObjects plus the thread/worker/bridge/generation/session state and the per-page hit/finish/fail slots — lives in [`controller/search_coordinator.py`](../controller/search_coordinator.py) as `SearchCoordinator` (R3.2). `PDFController` holds one coordinator and keeps thin `search_text`/`_cancel_search` delegates (the latter still called by 13 pre-mutation sites); `_SearchWorker`/`_SearchBridge` are re-exported from `pdf_controller` for backward compatibility. The coordinator preserves the exact QThread lifecycle (release bound to `thread.finished`, never `worker.finished`), the two-hop `worker→bridge→coordinator` wiring, and the `_search_gen` token that drops late queued signals from a cancelled search.

The background-OCR runtime is extracted the same way into [`controller/ocr_coordinator.py`](../controller/ocr_coordinator.py) as `OcrCoordinator` (R3.2): the `_OcrWorker`/`_OcrBridge` QObjects plus the OCR thread/worker/bridge/`_ocr_gen`/`_ocr_session_id`/progress-dialog state and the page-done/progress/status/failure/thread-finished slots. `PDFController` holds one coordinator and keeps thin `start_ocr`/`cancel_ocr` delegates; `_OcrWorker`/`_OcrBridge` are re-exported from `pdf_controller`. The coordinator preserves the `_ocr_gen` cancellation token, the per-page **session guard** (`_on_ocr_page_done` drops spans whose `_ocr_session_id` no longer matches the active session, so recognized text never lands in the wrong document after a tab switch), the GUI-thread `model.apply_ocr_spans` sequencing, and the `QProgressDialog` parenting/cleanup. `_refresh_ocr_availability` (a one-shot UI-availability probe, not worker runtime) intentionally **stays on `PDFController`**.

The print pipeline is the third and largest async coordinator: [`controller/print_coordinator.py`](../controller/print_coordinator.py) `PrintCoordinator` (R3.2) owns the `_PrintSubmissionWorker`/`_PrintWorkerBridge` QObjects, the `PrintJobRequest` payload, the `PrintDispatcher`, the `PrintSubprocessRunner` lifecycle, the progress dialog, and the stall/terminate state machine (`_print_stalled`/`_print_close_pending`). `PDFController` holds one coordinator and keeps thin `print_document` + `_has_active_print_submission` delegates; the model-coupled `_render_print_preview_image` (preview callback) and the app-lifecycle hooks (`handle_app_close` → `coordinator.begin_close_pending()`, `_fullscreen_is_blocked`) stay on the controller, and `_PrintSubmissionWorker`/`_PrintWorkerBridge`/`PrintJobRequest` are re-exported from `pdf_controller`. The coordinator preserves verbatim: the GUI-thread `capture_worker_snapshot_bytes()` handoff before `QThread.start()` (name unchanged — the R5.1 disk-leak/encryption fix is a separate deferred commit), the `worker→bridge→coordinator` wiring, the `thread.finished`-bound release, the `PrintSubprocessRunner` stall/terminate transitions and `work_dir` cleanup, the close-during-print message suppression (view closes only once idle), and the view-parented progress dialog. **Secure print-input contract (R5.1):** `capture_worker_snapshot_bytes()` decrypts (`PDF_ENCRYPT_NONE`), so for a password-protected source the coordinator captures the session password (`model.password`, only when `model.doc.needs_pass`) onto `PrintJobRequest.password` and `self._print_password`. `_PrintSubmissionWorker._encode_input_bytes()` re-encrypts those bytes (AES-256, `owner_pw == user_pw == password`) before writing `work_dir/input.pdf`, so no decrypted copy of a protected PDF ever lands at rest. The password reaches the helper **out-of-band** via the subprocess environment (`PrintSubprocessRunner(helper_password=...)` → `PDF_EDITOR_PRINT_PASSWORD` in the QProcess env) — never `job.json`, which is on disk in the same `work_dir`. `helper_main._build_snapshot_bytes(..., password=…)` authenticates the encrypted `input.pdf` in-memory so the printer still receives rasterizable bytes; the decryption never touches disk. The coordinator drops `self._print_password` once the job is idle. The re-encrypt/authenticate `save` calls live in `controller/` and `src/printing/` (outside `model/`), so the encryption AST guard does not apply.
Print submissions also snapshot the active document on the GUI thread before the helper worker starts. The helper worker writes those bytes into its temp `input.pdf`, and watermark overlays are intentionally suppressed for `purpose == "print"` so the helper subprocess remains the single print-stamp path.

Worker snapshot-bytes cache (R4.2): the full-doc `model.capture_worker_snapshot_bytes()` (`doc.tobytes(...)`) is captured independently by the search, OCR and print coordinators on the GUI thread before their worker threads start. The controller wraps it in a single-entry cache (`PDFController.capture_worker_snapshot_bytes`, keyed by `(active_session_id, render_revision)`), so overlapping jobs on an unedited document reuse one serialization; the three coordinators call the controller method, not the model. The cache key reuses the page-render invalidation token (`render_revision`), and `_bump_render_revision` drops the cache. The one doc mutation that is render-invisible but worker-visible is OCR's `apply_ocr_spans` (invisible `render_mode=3` text — searchable but pixel-identical, so no render bump), so `ocr_coordinator._on_ocr_page_done` explicitly calls `_invalidate_worker_snapshot_cache()` after applying spans. Any future render-invisible/worker-visible mutation must do likewise.

Thumbnail refresh is asynchronous via `_invalidate_thumbnails(affected)`. When the page count changed (insert/delete), it calls `view.set_thumbnail_placeholders(len(doc))` to resize the widget first, then schedules a full batch from the earliest affected page. When the page count is unchanged (rotate/straighten/text move), it skips the placeholder reset (preserving existing thumbnail icons) and schedules a bounded batch covering only the affected rows — rotating 1 page of a 2000-page doc re-rasters 1 page, not 2000. Thumbnail batches use a dedicated `_thumb_gen_by_session` counter so invalidation does not cancel unrelated background loading or viewport-anchor restoration (which rely on `_load_gen_by_session`). `_next_load_gen` bumps both counters, but `_invalidate_thumbnails` bumps only the thumb counter. Cross-page text moves invalidate thumbnails for both source and destination pages on success and rollback. The old synchronous `_update_thumbnails` method has been deleted.

Thumbnail rendering is **synchronous** (bounded `QTimer` batches on the GUI thread). The R4.3 hybrid-async `ThumbnailCoordinator` was **removed** (2026-06-21, R4-01…R4-04): its `batch_ready` signal carried only `(gen, start_index, images)` and per-session generation tokens are not globally unique, so a cancelled tab's queued batch could paint into the newly-active tab; it also serialized the snapshot on the GUI thread, retained a decrypted snapshot after tab close, and left the old worker running on sync fallback. `_schedule_thumbnail_batch` now renders `THUMB_BATCH_SIZE` pages per `QTimer.singleShot(THUMB_BATCH_INTERVAL_MS)` tick, guarded by the `_thumb_gen_by_session` token (a superseded generation exits at the head check before painting — cross-paint is impossible by construction). The R4.2 worker-snapshot cache is retained for search/OCR/print, and `on_tab_close_requested` now clears it for the departing session (R4-03) so decrypted bytes do not outlive the tab.

### 2.4 View (`view/pdf_view.py`)

View owns widgets, scene interactions, and signal emission. It does not mutate model business state directly.
For empty startup it can show a lightweight shell with no model/controller attached. When the user requests a document (open or drop), the view queues paths and emits a backend-bootstrap signal so `main.py` can create model/controller and drain pending open paths.
The view also owns the Save As dialog invocation (`_save_as()`), but the controller supplies the active-session default path through `set_save_as_default_path(...)`.

Continuous mode rendering contracts:
- `initialize_continuous_placeholders(...)` establishes the full scene rect and per-page y offsets for the entire document without rasterizing every page.
- The view emits `sig_viewport_changed` when the user scrolls/resizes; the controller uses this as the steady-state trigger to schedule visible-page rendering.
- Programmatic jumps (for example controller-driven navigation) may suppress `sig_viewport_changed` emissions to avoid double-scheduling the same visible render batch.
- Visible-render scheduling is controller-owned and now coalesced per session. Repeated page changes or viewport notifications may update the target page immediately, but they must not keep spawning fresh render generations while a batch is already queued.
- Thumbnail layout metrics are view-owned; when the left sidebar becomes unusually wide, the thumbnail column caps its content width and uses symmetric viewport margins so thumbnails stay centered instead of stretching indefinitely.

The text editor state is split by intent:
- `edit_existing` for updating existing text.
- `add_new` for inserting new page text.
- Browse-mode drag selection still starts in the view, but the actual copied text and highlight bounds are resolved through the model's run-anchored selection helpers so the MVC boundary stays intact. Start requires a direct run hit via strict hit-testing (`allow_fallback=False`); the end point may snap to the nearest run on the same page only after exact-run hit detection misses.

Typed edit payloads are part of the view/controller boundary and are defined in `model/edit_requests.py` (single source of truth):
- `EditTextRequest` packages same-page edit commits.
- `MoveTextRequest` packages cross-page text moves and replaces the previous positional `sig_move_text_across_pages(...)` signature.
Both are re-exported via `view/text_editing.py` for backward-compatible view/controller imports.

Inline editor finalization is guarded by focus context:
- Focus transitions inside text-edit context (editor widget, text property panel, combo popups) keep the session alive.
- Focus transitions outside the edit context finalize the current inline editor.
- A short deferred check avoids false finalize during Qt popup handoff.

Text style controls include explicit commit/cancel buttons:
- `套用` commits current inline edit.
- `取消` discards current inline edit session changes.

Mode behavior boundary:
- In `edit_text`, blank-click does not create new textbox. All visible selectable text targets are drawn as persistent outlines (`_draw_all_block_outlines`) so users can see editable zones without hovering. In `run` mode the outlines follow run boxes; in `paragraph` mode they follow paragraph boxes instead of coarse block rectangles.
- Outline redraws driven by scroll and zoom are debounced through `_schedule_outline_redraw()` (80 ms single-shot timer) so rapid viewport events collapse to one redraw instead of rebuilding 30 to 90 `QGraphicsRectItem`s on every tick.
- When the selected text target is rotated (`90/180/270`), the inline editor proxy is laid out with rotation-aware geometry and the proxy itself is rotated, so the editor content matches the source text orientation instead of always appearing upright.
- In `add_text`, blank-click commits open editor; otherwise it creates a new textbox editor.
- In `rect`, `highlight`, and `add_annotation`, each tool is sticky for repeated operations.
- Mode actions are checkable and remain synchronized with the active mode state.
- Switching away from `edit_text` with an open editor auto-commits the edit (same path as CLICK_AWAY) and shows a brief toast notification. Previously this silently discarded edits.
- `Esc` priority is: close active editor/dialog first (keep mode), else revert non-browse mode to `browse`, else run browse fallback behavior.
- The inline editor keeps the real text color and its widget background stays transparent, but the view now inserts a sampled-color scene mask item behind the editor proxy so the already-rendered PDF text does not visually overlap the live edit layer.
- Middle-click auto-pan is implemented as an overlay state, not as a real `current_mode` entry. The top of `_mouse_press`, `_mouse_move`, and `_mouse_release` intercepts overlay events before normal tool routing, tracks the auto-pan origin/cursor in viewport coordinates, and drives scrolling via a 16 ms timer against the graphics view scrollbars. Because the overlay does not call `set_mode(...)`, exiting auto-pan restores the previously active tool state and cursor behavior instead of tearing down the active mode.

Fullscreen UX is implemented in the view, but coordinated by controller state:
- View owns chrome visibility, fullscreen enter/exit, top-edge exit affordance, and viewport anchor helpers.
- Controller decides when fullscreen is allowed, normalizes mode/interaction state on entry, and restores per-tab layout on exit.

**Deferred heavy imports:** `view/text_editing.py` defers `import numpy` to the first call of each numpy-using helper (function-body import, same pattern as `model/pdf_model.py:_render_page_gray_array`). Dialog classes live in the `view/dialogs` package (one submodule per dialog; `view/dialogs/__init__.py:_EXPORTS` is the single source of truth for the name→submodule map) and load lazily via a PEP 562 module `__getattr__`; `view/pdf_view.py` re-exports them through its own `__getattr__` (its `_DIALOG_EXPORTS` is derived from `_EXPORTS`, not hand-maintained) so PIL/pikepdf/lxml (31 MB) only load when a dialog is first opened — after `view.show()`. Both ensure cold-boot DLL reads stay under 30 MB; `test_scripts/test_startup_heavy_imports.py` guards this in CI via a subprocess import probe.

### 2.5 Theming (`view/theme.py`, `view/icons.py`)

The UI ships four selectable themes (`alpine-snow`, `meadow-lupine`, `ink-porcelain`, `glimmering-glacier`), translated from `docs/design/colors.css`. `view/theme.py` is the single source of truth:
- Per-theme token dicts (20 keys each) and a `THEME_REGISTRY` of frozen `ThemeMeta` (insertion order = on-screen order). Each chip's `swatch` is the theme's `bg`, so light modes that share an accent stay distinguishable. The token set includes three brand colours lifted verbatim from `colors.css` that were documented but historically unplumbed: `accent_line` (`--color-accent-line`, focus rings + splitter hover), `hover_strong` (`--color-hover-strong`, tab hover), and `shadow` (the `--shadow-*` hue, chrome elevation). These are NOT new hues — the palette/brand is unchanged.
- `build_qss(theme_name)` returns the complete application QSS; unknown names fall back to `alpine-snow`. Ribbon, sidebar, and document-tab rules are object-name-scoped (`#ribbonTabs`, `#sidebarTabs`, `#documentTabBar`) so they never leak across tab widgets. The QSS gives every interactive surface explicit `:hover` / `:pressed` / `:focus` states (Qt QSS cannot animate transitions, so differentiation is static): colour-only focus rings on inputs/combos/buttons (recolour the existing 1px border → no layout shift), themed slim scrollbars, a themed `QSplitter::handle`, themed `QToolTip`, accent-fill `QCheckBox`/`QRadioButton` indicators (no glyph asset), `QMenu` item padding + separators, scoped tab `:hover`, an accent `QPushButton:default` (primary affordance for dialog OK buttons), and a `#rightPanelTitle` section header.
- `shadow_color(theme_name)` (Qt-guarded) parses the `shadow` token (`#hex` or `rgba(r,g,b,a)` via `_parse_qcolor`) into a `QColor` for `QGraphicsDropShadowEffect`. QSS has no `box-shadow`, so real elevation is applied in code.
- `ThemeSwitcherWidget` / `_ThemeChip` render one square per theme in the status-bar corner and emit `theme_selected(str)`.

Key contract: the themed QSS is applied **once at the `QApplication` level**, not per-widget. This is deliberate — top-level `QMenu` context menus and modal `QDialog`s are not children of the main window and would otherwise miss a window-level stylesheet. No widget carries an inline `setStyleSheet` for colors. The one real drop shadow (top toolbar chrome) is a `QGraphicsDropShadowEffect`, not a stylesheet: `PDFView._apply_chrome_shadow(theme_id)` creates it once on the `_toolbar_container` and only refreshes its colour on subsequent theme switches (called from `apply_theme`). It is applied to the toolbar container alone, which never holds the heavy `QGraphicsView`, so there is no render-path interaction; it does not change the container's `maximumHeight`.

Theming is **owned by the View** because it never touches the document model — it only writes a QApplication stylesheet and a UI preference, so it does not need the Controller (the Model-mutation coordinator). `PDFView.apply_theme(theme_id, *, persist=True)` sets the app QSS, syncs the active-chip ring, and (by default) persists via `UserPreferences.set_theme`; it is a no-op for unknown ids. The view constructor stays **side-effect-free** — it resolves `self._initial_theme` but does not touch global state. The composition root applies the saved theme once: `main.py` calls `view.apply_initial_theme()` right after building the view (this also keeps the switcher live on the empty shell, before any controller exists, and prevents a stray view from re-theming the shared `QApplication` in tests). Switch flow: `ThemeSwitcherWidget.theme_selected` is connected directly to `PDFView.apply_theme`.

Single source of truth for valid ids: `utils/theme_ids.py` (a dependency-free leaf) defines `THEME_IDS`, `DEFAULT_THEME_ID`, and `VALID_THEME_IDS`. Both `utils/preferences.py` (which stores the choice under `ui/theme` and validates against it) and `view/theme.py` import it; `view/theme.py` raises at import if `THEME_REGISTRY` drifts from `VALID_THEME_IDS`, so a half-added theme fails fast instead of surfacing as a late `ValueError` when selected. `view/icons.py` maps the 31 Traditional-Chinese ribbon action labels to PNG filenames in `view/resources/function_icons/` and exposes `load_icon(label, size=24)` (null `QIcon` for unknown labels / missing files). `view/theme.py` and `view/icons.py` guard their Qt imports with `try/except ImportError` so token/map-only tests run headless.

## 3. Runtime Flows

### 3.1 Open / Activate / Close

View emits open/switch/close intent. Controller calls model session operations. Model opens/activates/cleans session and tool hooks. Controller restores session UI state and schedules rendering/index batches.

Open intake now has three entry shapes that still converge on the same controller/model path:
- File picker: `PDFView` emits `sig_open_pdf(path)` after user selection.
- CLI startup: `main.py` attaches/activates the controller immediately, then calls `controller.open_pdf(path)` for each argv path.
- Window drag-and-drop: `PDFView` accepts local `.pdf` URLs, ignores folders/non-PDF/remote URLs, and emits `sig_open_pdf(path)` in dropped order when the controller is already active.

For empty startup, drag-and-drop must respect the backend-on-demand lifecycle. `PDFView` can receive drops before any model/controller exist, so it queues pending paths and requests backend bootstrap. `main.py` creates/attaches/activates the controller, drains that queue, and replays each path through `controller.open_pdf(path)`. This preserves one open pipeline and avoids losing early drops.

```mermaid
flowchart TD
  A["User opens via picker / CLI / drag-drop"] --> B{"Entry type"}
  B -->|Picker| C["PDFView.emit sig_open_pdf(path)"]
  B -->|CLI| D["main.py attach+activate controller"]
  B -->|Drag-drop, controller active| E["PDFView emits sig_open_pdf(path) in drop order"]
  B -->|Drag-drop, backend not ready| F["PDFView queues dropped local PDF paths"]
  F --> G["PDFView emits sig_backend_bootstrap_requested"]
  G --> H["main.py create+attach+activate controller"]
  H --> I["Drain queued paths"]
  D --> J["controller.open_pdf(path)"]
  I --> J
  C --> J
  E --> J
  J --> K["PDFModel.open_pdf(..., append=True)"]
```

Key invariants:
- Drag hover validation stays cheap on the UI thread: only local-URL and `.pdf` checks run during drag-enter / drag-move.
- File existence checks for dropped paths happen only on drop, not on hover.
- All successful opens still flow through `PDFController.open_pdf(...)`; drag-and-drop does not introduce a second open contract.

### 3.2 Edit Existing Text

View hit-tests text and opens editor with target metadata. On commit, view emits `sig_edit_text(EditTextRequest)`. Controller creates `EditTextCommand` with page snapshot. Model runs transactional edit pipeline and page index rebuild. Controller refreshes affected view scope. Commit criteria include text, position, font, and size deltas so style-only edits are persisted. Empty text commits from existing-text edit are valid delete intents: the target textbox content is redacted and not reinserted, and history remains undo/redo-safe.

Edit command failure handling is explicit:
- If model edit execution returns `TARGET_BLOCK_NOT_FOUND` or `TARGET_SPAN_NOT_FOUND`, controller surfaces targeted user feedback and does not record a history entry.
- No-op / failed edit executions must not create undoable commands.

Cross-page moves use a separate typed flow. When an inline edit changes page, the view emits `sig_move_text_across_pages(MoveTextRequest)`. Controller resolves the source span, captures a document snapshot, deletes the source text, inserts the destination textbox, and records a single `SnapshotCommand` only if the full move succeeds. Failure restores the document from the pre-move snapshot and refreshes both affected pages.

### 3.3 Add New Textbox

View computes visual insertion rect and opens add editor. On commit, view emits `sig_add_textbox(...)`. Controller captures strict page snapshot and executes `AddTextboxCommand`. Model maps visual-to-unrotated geometry, clamps bounds, inserts page text, and rebuilds page index. Controller refreshes page render so new text is immediately editable through existing edit flow.

### 3.4 App-Owned Object Manipulation (F1 v1)

Object manipulation is intentionally narrower than generic page-content editing. V1 only supports app-owned objects:

- new textboxes created after the F1 work landed
- rectangle annotations created by this app

The boundary stays MVC-clean:

- view owns selection visuals, drag gestures, and rotate-handle affordances
- controller owns typed object requests and snapshot command recording
- model owns object discovery and object mutation

Textbox identity is persisted through a hidden companion annotation marker rather than unstable text span identity. Rectangle annotations carry app-owned metadata directly on the annotation. Undo/redo is snapshot-backed in v1 to keep the object path safe while the supported object set is still small.

### 3.4 Undo / Redo

Controller invokes command manager undo/redo. Commands restore page/doc snapshots according to command type. Controller then refreshes the minimal required UI scope and tooltip descriptions.

Undo/redo enablement is split between document history and the active inline editor:
- Global document actions reflect `CommandManager.can_undo()` / `can_redo()`.
- While an inline text editor is active, toolbar actions temporarily reflect the editor document's own undo/redo availability.

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

### 3.6 Fullscreen Viewing

Entry can be triggered from any mode (`F5` or the top-right `全螢幕` button). The controller cancels active edits/partial gestures, clears transient selection/search UI state, forces `browse`, and captures a per-tab pre-fullscreen snapshot (page, scale, scroll anchor). The view enters native fullscreen and hides chrome; it computes a contain-fit scale for the active page and re-centers on resize. Exit restores the normal window chrome and per-tab pre-fullscreen layout, keeping the current tab active.

### 3.7 Optimize PDF Copy

Optimize-copy is an explicit new-file workflow from the `檔案` tab. It must not mutate the active live document while preparing the optimized output.

```text
[active session doc]
      |
      v
[in-memory snapshot bytes]
      |
      v
[disposable working doc]
      |
      +--> [audit xref/resource usage] -> [report dialog]
      |
      `--> [tool save prep]
              |
              v
      [image/font/metadata/cleanup passes]
              |
              v
      [full save to output path]
              |
              v
      [open optimized copy as new tab]
```

Contracts:
- Controller owns the dialog / save-path flow and opens the output as a new tab.
- Model owns the disposable working-document boundary, audit report generation, and optimization save pipeline.
- Optimizer internals are implemented in `model/pdf_optimizer.py`; `PDFModel` exposes a stable facade and delegates.
- Object-ops internals (app-object/native-image manipulation) live in `model/pdf_object_ops.py` (R3.4) as free functions `def fn(model: PDFModel, ...)`, same pattern as the optimizer. `PDFModel` keeps 1-line delegating wrappers for the public verbs (`add_image_object`, `add_textbox`, `get_object_info_at_point`, `move_object`, `rotate_object`, `delete_object`, `resize_object`); the private helpers (native-image invocation find/rewrite/remove, app-object payload/annot helpers, object markers, `_insert_textbox_visual_content`, `_redact_and_restore_textbox_region`) moved fully (no external callers). The free functions reach controller-undo-free: they never call `_capture_*`/`_restore_*` (undo is the controller's snapshot boundary), mutate `pending_edits`/`edit_count` in the original order after `doc.update_stream`, and do no `.save`/`.tobytes` on the live doc (the encryption AST guard scans `model/`). The OCR methods (`apply_ocr_spans`/`_pick_ocr_font`) and the HTML converters (`_convert_text_to_html`/`_build_multi_style_html`) stay on `PDFModel`.
- Edit-text / redaction engine lives in `model/pdf_text_edit.py` (R3.5, the LAST and highest-risk model seam) as free functions `def fn(model: PDFModel, ...)`, same pattern as the optimizer and object-ops. Nine methods moved as a contiguous run: `_has_complex_script`, `_push_down_overlapping_text`, `_replay_protected_spans`, `_validate_protected_spans`, `_resolve_edit_target`, `_apply_redact_insert` (moved whole), `_verify_rebuild_edit`, `_resolve_effective_target_mode`, and `edit_text`. The module-level `_EditTextResolveResult` dataclass and `_classify_insert_path` (the view/model shared insert-path classifier) moved with the cluster and are **re-exported from `pdf_model`** so existing `from model.pdf_model import ...` imports keep working. `PDFModel` keeps 1-line delegating wrappers for **all nine** (not just `edit_text`) because the test net pokes the privates directly; the inter-method calls inside the module go through `model.` (i.e. through those wrappers) rather than as local free-calls, preserving exact bound-method / monkeypatch dispatch (e.g. `_push_down_overlapping_text` is monkeypatched in tests). **STAY on `PDFModel`** (cross-cutting consumers reach them, moved code calls via `model.`): `_resolve_font_for_push` (called by the staying `_resolve_add_text_font`), `_needs_cjk_font` (also `pdf_object_ops` + monkeypatched), `_convert_text_to_html`/`_build_insert_css`/`_build_multi_style_html` (controller + view preview), `_maybe_garbage_collect` (encryption-preserving `_roundtrip_live_doc`), `_reauthenticate_if_needed`. The no-jump pixel-parity gate is required green before and after this seam.
- Object-selection interaction lives in `view/object_selection.py` (R3.6, the first view seam) as `ObjectSelectionManager`, a plain helper holding `self._view` (a back-reference to the PDFView), mirroring `TextEditManager` in `view/text_editing.py`. The 20 object selection / drag / resize / free-rotation verbs (`_clear_object_selection`, `_select_object`, `_rebase_object_selection_to_bboxes`, `_apply_object_selection_rotation`, `_update_object_selection_visuals`, the handle hit-tests, `_delete_selected_object`, `_commit_free_rotation`, the rotation verbs, `_add_object_rotation_actions`, `_show_object_rotation_menu`, `_resolve_object_info_for_context_menu_pos`) plus the pure `absolute_rotation_from_drag` helper moved here; `absolute_rotation_from_drag` is re-exported from `pdf_view` for back-compat. The manager reads/writes view state and emits Qt Signals through `self._view` (Signals stay class attributes on PDFView). `PDFView` keeps 1-line delegating wrappers for all 20 verbs (`_next_right_angle_rotation`'s wrapper is a `@staticmethod`) plus an `_ensure_object_selection_manager()` lazy accessor. Scope note: this seam moved the methods only — the ~26 interaction-state attrs (`_selected_object_*`, `_object_drag_*`, `_object_rotate_*`, `_object_resize_*`) and the three mouse handlers (`_mouse_press/move/release`) remain on PDFView for now; migrating that state and introducing a `handle_press/move/release` facade is coupled to the mouse-handler refactor and lands with R3.8.
- Browse-mode text selection lives in `view/text_selection.py` (R3.7, the second view seam) as `TextSelectionManager`, the same `self._view`-holding helper pattern. The 12 text-selection / highlight / copy verbs moved here: `_selected_text_has_context`, `_start_text_selection`, `_update_text_selection`, `_finalize_text_selection`, `_selection_doc_rect_to_scene`, `_clear_text_selection_extra_rects`, `_render_text_selection_line_rects`, `_clear_text_selection`, `_resolve_text_info_for_doc_rect`, `_resolve_text_info_for_context_menu_pos`, `_select_all_text_on_current_page`, `_copy_selected_text_to_clipboard`. There are no Qt signals (selection is local; copy uses `QApplication.clipboard()`). PDFView keeps 1-line delegating wrappers for all 12 plus an `_ensure_text_selection_manager()` lazy accessor — wrappers are mandatory because external callers exist (the controller calls `view._clear_text_selection()`; Ctrl+A/Ctrl+C `QAction.triggered` bind `_select_all_text_on_current_page`/`_copy_selected_text_to_clipboard`; the context menu calls the resolver/predicate). `_sync_text_property_panel_state` STAYS on PDFView (cross-cutting — called by both text methods and non-text code), reached via `self._view`. Scope note: as in R3.6, only the methods moved — the ~17 selection-state attrs (`_text_selection_*`, `_selected_text_*`) and the three mouse handlers stay on PDFView for now and migrate with R3.8. Known follow-up: the rect/extra-rect cleanup uses `if item.scene():` rather than `shiboken6.isValid()` (as ObjectSelectionManager does); hardening is deferred to keep this a verbatim no-op move.
- R3.8a (state migration) completed the manager ownership: the 43 object/text interaction-state attrs now live in `ObjectSelectionManager`/`TextSelectionManager` `__init__` (real storage), and `PDFView` exposes get/set `@property` forwarders for all 43 that proxy to the managers via the `_ensure_*_manager()` lazy accessors (so the mouse handlers, context menu, property panel, and `PDFView.__new__()` test doubles keep working unchanged). The managers are now the single source of truth for their interaction state. R3.8b — refactoring the three mouse handlers (`_mouse_press/move/release`) into a per-mode dispatcher that delegates branch bodies to `manager.handle_press/move/release` and drops the forwarders — is **deferred**: the pixel-parity/model gate structurally cannot validate Qt event-routing (accept/ignore propagation, autopan timers, drag thresholds, mode-priority on overlapping hits), so it requires dedicated `pytest-qt` interaction tests and/or manual QA. Full context, branch boundaries, the Strangler-Fig procedure, and Codex's 10 landmines are recorded in `plans/refactor-R3-god-module-decomposition.md` (R3.8b section).
- Save-option normalization runs at model boundary before `fitz.Document.save(...)` so invalid flag combinations (for example `linearize + use_object_streams`) are resolved before persistence.
- Post-save packaging (linearize / object streams) is pikepdf-only: PyMuPDF 1.24+ removed `linear=1`. `PDFModel.optimize_capabilities()` (static, delegates to `pdf_optimizer.optimize_capabilities()`) probes the runtime; the controller passes the dict to `OptimizePdfDialog(capabilities=...)`, which disables + unchecks the gated checkboxes before applying any preset. If packaging is still requested without pikepdf, the model fails fast with `PdfOptimizeError` (a `RuntimeError` subclass carrying the complete user-facing message — callers must not re-wrap it).
- The active session document remains the source of truth and is not rewritten by the optimizer path.
- **Encryption preservation (R5.5; hardened R5-02/03/04 + Codex 2026-06-21).** The optimize-copy working doc is rebuilt from the *decrypted* live-doc bytes (`build_working_doc_for_optimized_copy` → `tobytes` for the encrypted/`needs_pass` source), so the optimized output would otherwise ship unprotected. The job is **bound to its source session at dispatch**: `OptimizePdfCopyRequest.session_id` is captured on the GUI thread and threaded to `save_optimized_copy(session_id=...)`; every document read resolves `_session_doc(model, session_id)` (the session's own handle), never the active `model.doc`, so a tab switch during the background job cannot mix documents (R5-03). Encryption is decided from an immutable `EncryptionDescriptor` (`_capture_encryption_descriptor`) snapshotted up front: session id, password, method, permissions, and `DocumentSession.auth_level` (2=user/4=owner/6=both/None). `reapply_source_encryption(enc, src, dst)` **preserves the auth role** (R5-02) — a user credential stays `user_pw` with a random `owner_pw` (no promotion to owner); owner/both retain the credential; owner-only blank-user sources (detected via encryption metadata, not just `needs_pass`) re-lock with a random `owner_pw` + blank `user_pw` + the restricted permissions, never shipping unprotected. The install is **fail-closed** (R5-04): plaintext is written to a temp, encrypted into a destination-*sibling* staging file, then atomic `os.replace` only on success — `new_path` never holds the transient plaintext for an encrypted source — and every staging path is cleaned in `finally`. All saves target reopened output handles, never `model.doc`, so the R2.2 encryption AST guard does not flag them.

Audit report semantics:
- `build_pdf_audit_report(...)` derives category usage by collecting unique referenced xrefs from each page:
  - `圖片`: unique xrefs from `page.get_images(full=True)`
  - `字體`: unique xrefs from `page.get_fonts(full=True)`
  - `內容串流`: unique xrefs from `page.get_contents()`
- `數量` is unique-object count per category (not draw-call or visual-occurrence count).
- `文件開銷` and `其他/未分類` are byte-bucket rows; their `數量` is a presence marker (`1` or `0`) instead of a true xref count.

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

### 5.1 OCR Tool (Surya)

The OCR tool (`model/tools/ocr_tool.py`) uses Surya (`surya-ocr`) as its recognition backend. Pipeline:

1. `OcrTool.availability()` returns an `OcrAvailability` record, gating the view's toolbar action before any Surya import; install hint `pip install surya-ocr` is surfaced in the tooltip when missing.
2. `OcrTool.ocr_pages(pages, languages, *, device, on_progress)` renders each page pixmap through `model.render_page_pixmap(...)` at `OCR_RENDER_SCALE = 2.0` (higher DPI → better recall), converts to PIL via `_pixmap_to_image`, and runs Surya's `DetectionPredictor` + `RecognitionPredictor` (module-level singletons, lazy-loaded). Bounding boxes are scaled by `1/OCR_RENDER_SCALE` back into visual page coordinates and returned as `OcrSpan` tuples per page.
3. Device resolution is explicit and user-controllable: `OcrRequest.device` is `auto | cuda | cpu | mps`. `_resolve_torch_device("auto")` probes `torch.cuda.is_available()` then MPS and falls back to CPU when torch is missing; explicit `cuda`/`mps` selections are validated via `_is_device_available(...)` and raise a clear error when unavailable. The default is persisted in `utils.preferences.UserPreferences` under `ocr/device`, seeded into the `OcrDialog` device combo ("自動 (優先使用 GPU)"), and the dialog disables/clamps unavailable choices back to `auto`.
4. Results are committed per page into the PDF via `PDFModel.apply_ocr_spans(page_num, spans)`, which picks a built-in CJK-aware font ("japan"/"korea"/"china-t"/"helv") and calls `page.insert_text(..., render_mode=3, rotate=page_rotation)` so the text is invisible but searchable/selectable. After all spans are placed, `block_manager.rebuild_page(page_idx)` rebuilds the page text index once and the edit is appended to `pending_edits`.
5. To avoid VRAM accumulation across runs on small GPUs, `ocr_pages` drops the Surya adapter reference and calls `torch.cuda.empty_cache()` (or `torch.mps.empty_cache()` when available) after completion.

Threading: OCR runs on a `QThread` driven by `_OcrWorker` (`controller/pdf_controller.py`). The worker emits `progress`, `page_done`, `failed`, `finished` via a `_OcrBridge` parented on the GUI thread. Writes (`apply_ocr_spans`) always happen on the GUI thread via `page_done`, so Surya I/O never touches Qt objects directly. Per-page commit makes cancel safe — cancellation before a page finishes just drops that page's not-yet-returned spans. Phase 3 now snapshots the source PDF on the GUI thread before OCR starts. `_OcrWorker` receives the snapshot bytes, `OcrTool.ocr_pages(..., doc=...)` can render from that override without touching the live document, and the controller drops stale signals two ways: every worker signal carries a generation token (`cancel_ocr` bumps `_ocr_gen`, handlers ignore mismatches — mirroring the search worker), and `page_done` is additionally dropped when the active session id no longer matches the `_ocr_session_id` captured at start.

View entry: `PDFView.ocr_action` (menu/toolbar under 轉換) launches `view/dialogs/ocr.py::OcrDialog` (page scope + languages + device) and emits `sig_start_ocr(OcrRequest)`. Controller `activate()` calls `_refresh_ocr_availability()` to reflect Surya install state in the action tooltip and enabled flag. Device availability is injected, not imported: `PDFView._ocr_pages()` constructs `OcrDialog(..., device_available=self._ocr_device_available)`, and `_ocr_device_available` forwards to `self.controller.is_device_available(device)` (falling back to `True` if no controller is wired) — this keeps `view/dialogs/ocr.py` free of a direct `model.tools.ocr_tool` import (PR-9).

### 5.2 Search Tool (async worker, Phase 4.2)

`SearchTool` (`model/tools/search_tool.py`) exposes `search_page(page_num, query) -> list[tuple[int, str, rect]]` — a bounds-checked single-page search (out-of-range pages and missing documents return `[]` instead of raising) sharing the exact hit-tuple shape `(page_num, context, rect)` with the legacy full-document `search_text` (which now simply iterates `search_page`).

Threading mirrors the OCR pattern: `PDFController.search_text(query)` cancels any previous search, then runs `_SearchWorker` (`controller/pdf_controller.py`) on a `QThread`, calling `search_page` per page and emitting `hits_found`/`failed`/`finished` through `_SearchBridge` (parented on the GUI thread, wired in `activate()`). Two deliberate deviations from the OCR lifecycle:

- **Generation token in every worker signal** (`_search_gen`): searches are cancel-and-restart (typing a new query), and queued cross-thread emissions already posted to the GUI event queue are still delivered after a disconnect — the gen guard in the controller handlers drops them.
- **Controller refs are released on `thread.finished`** (`_release_search_thread`, identity-checked), never on `worker.finished` — dropping the Python `QThread` wrapper while the thread still runs lets GC destroy the C++ object and hard-crash the process.

Hits accumulate incrementally in `_search_accumulated_hits` and each per-page batch re-renders `view.display_search_results(list(accumulated))` (the view rebuilds its result list per call, so accumulate-and-replace is safe); on finish the controller persists `search_state = {"query", "results", "index": -1}` into the session UI state, preserving per-tab restore and next/prev navigation. `_cancel_search()` (cancel flag + `thread.quit()` + bounded `wait(2000)`) runs at the top of every document-mutating controller method (delete/rotate/straighten/insert ×2/merge/undo/redo) and at session-lifecycle boundaries (tab switch, tab close, new open), because a live fitz document is not safe for concurrent read-during-mutation.

## 6. Printing Subsystem

Printing is implemented under `src/printing/*` (dialog, dispatcher, layout, selection, renderer, platform drivers). Controller entry is `PDFController.print_document()`.
View-only color profile switching is session-scoped: `SessionUIState.color_profile` (`"srgb" | "gray" | "cmyk"`) is read by the controller and threaded into the on-screen render stack (page pixmaps, thumbnails, snapshots) via the PyMuPDF `colorspace` argument. The print raster path also carries the same intent through `PrintJobOptions.extra_options["render_colorspace"]`, so the Windows helper subprocess renders/prints using the selected colorspace without mutating the source PDF or loading ICC profiles.
The unified print dialog also exposes native printer properties through driver-dispatched calls (`PrintDispatcher.open_printer_properties(...)`), enabling OS/vendor preference dialogs from the same workflow. The dialog caches the latest returned printer preferences and tracks only user-touched hardware fields in-app. Effective print options are built with two ownership rules: `paper_size` and `orientation` are app-owned and default to `auto`, so native printer preferences must not overwrite them; `duplex` and `color_mode` still inherit native defaults until the user changes them in-app. On Windows, preference collection merges printer DEVMODE data from `GetPrinter(..., 2/8/9)` so per-user defaults from native `屬性` can sync back into the app UI even when a driver exposes some values only through user-specific defaults. When the native properties dialog is canceled, the driver returns `None` and the unified dialog preserves both current UI values and touched-state instead of resyncing from printer defaults.
Tray and other non-UI driver preferences remain pass-through system defaults because dialog output keeps `paper_tray="auto"`. The app no longer renders a tray/system-properties section in the dialog UI. On Windows, properties chosen in `屬性` are applied **job-scoped, not persisted**: the captured DEVMODE is carried with the job (base64 under `extra_options["devmode_buffer"]`, which keeps it JSON-safe across the helper-subprocess `job.json` boundary) and applied for that print only by briefly writing the per-user default (`SetPrinter` level 9) and restoring the previous default in a `finally`, so a single print never permanently mutates the printer's defaults for other jobs or apps. When a driver changes only private `DriverExtra` data and leaves public DEVMODE fields stale, the driver marks those fields opaque; the dialog then shows `color_mode="system"` (`依系統屬性`) instead of incorrectly echoing stale public values.
`PrintJobOptions.override_fields` is the shared contract between the dialog and print backends. Explicit fixed paper/orientation choices are marked overridden; `auto` paper/orientation remain unmarked and mean "follow the source page." Duplex/color mode are still applied only when those fields are marked overridden. This keeps app-owned job settings (`copies`, `dpi`, `collate`, page range, scaling) unconditional while preventing silent overrides of native hardware defaults.
The Qt bridge resolves page layout from each rendered page's source rect and applies it via the dedicated `QPrinter.setPageSize()` / `setPageOrientation()` setters — the `setPageLayout(pageLayout()-copy)` idiom silently drops the page **size** on the Windows GDI device (orientation still applies), which made mixed jobs print every page on the default media. Per-page layout changes mid-job are honoured by Qt's PDF writer but ignored by the Windows GDI spooler, so for the real spooler `WindowsPrinterDriver` pre-splits a mixed-size/orientation job into one spooler job per contiguous uniform-layout group, with multi-copy ordering coordinated in `_print_layout_groups` (collated → loop the document; uncollated → copies per group). The effective raster DPI is capped at `_WIN_MAX_RASTER_DPI = 150` for the spooler path while PDF output keeps full DPI. Linux/macOS direct-PDF submission remains valid only for source-following auto layout; explicit fixed paper/orientation choices force raster so the app, not the spooler default, owns the final page layout.
Preview rendering and final submission are intentionally split. `UnifiedPrintDialog` can render preview pages from a live-document provider callback, so opening the dialog does not require prebuilding a full print snapshot. `PDFController.print_document()` builds the full print snapshot only after the dialog returns `Accepted`, avoiding wasted serialization on cancel.

### 6.0 Fileless submission (R5-01)

The print pipeline never writes the document to disk. `PDFModel.capture_print_snapshot_bytes` returns `PDF_ENCRYPT_NONE` bytes on both of its branches — the pipeline is holding plaintext from the moment the user confirms, whatever the source's encryption — so any temp it produced was a recoverable decrypted copy.

- **Source type.** `PDFRenderer` (`get_page_count`, `iter_page_images`, `render_all_to_images`) and `qt_bridge.raster_print_pdf` take `PdfSource = str | bytes`, resolved through `pdf_renderer.open_pdf_source`. `QPrinter` only ever sees rendered `QImage`s, so the source format is invisible to the spooler.
- **Driver contract.** `PrinterDriver.print_pdf_from_bytes(pdf_bytes, page_indices, options)` sits beside the path-based `print_pdf`. Its default implementation writes a scoped temp and delegates, so a driver that understands only paths keeps working. `WindowsPrinterDriver` overrides it and threads bytes through the geometry-classification pass and the rasteriser, so **on Windows no document bytes touch disk at any point**. `PrintDispatcher.print_pdf_bytes` calls it directly; `print_pdf_file` remains for the path callers.
- **Coordinator → helper.** `_PrintSubmissionWorker` writes nothing; the document rides the helper subprocess's **stdin**, streamed by `PrintSubprocessRunner` in `_STDIN_CHUNK_BYTES` (1 MiB) chunks gated on `bytesWritten`, so peak buffering is one chunk rather than one document. `PrintHelperJob.pdf_bytes` carries it in memory (`repr=False`, never serialized); `job.json` holds options and watermarks only.
- **Protocol version.** `PrintHelperJob.input_pdf_path` is now `str | None` and omitted from `job.json` when unset. Helper rule: **present → read that file (v1); absent → read stdin.** This keeps the change coordinator-side revertable.
- **Credential consequence.** Because the piped bytes are already plaintext, the helper has nothing to authenticate. R5.1's temp re-encryption and the `PDF_EDITOR_PRINT_PASSWORD` environment variable are gone from the production path (`PrintSubprocessRunner.helper_password` survives for the v1 file branch). A process environment block is readable by same-user processes; an anonymous pipe is not.
- **Residual.** The Linux/macOS CUPS/lp *direct-PDF* route materialises one temp inside `LinuxPrinterDriver` (not the dispatcher), because `conn.printFile` / `lp` hand the path to a filter chain that must parse it. It cannot be encrypted — the consumer requires plaintext — so it is scoped, `0600`, and unlinked in a `finally`. See `docs/PITFALLS.md`.
Preview refresh is also guarded at the dialog boundary: resize / wheel / row-change paths flow through a safe preview wrapper that converts temporary option-building errors (for example invalid custom page range while typing) into inline preview messages rather than unhandled UI-event exceptions.

### 6.1 Windows Spooler Isolation (Helper Subprocess)

On Windows, the Qt/GDI print submission path can stall the entire GUI process even when invoked from a `QThread` because the OS print stack can block inside the process. To protect application responsiveness and lifecycle stability, Windows raster submission is isolated into a helper subprocess:

- Main app prepares a job (immutable inputs): serialize a `PrintHelperJob` into `job.json` in a temp work dir. **The document itself is not written there** — since R5-01 it is streamed to the child's stdin (see §6.0); the work dir holds `job.json` only.
- Main app launches a child Python process via `QProcess` using `sys.executable` and runs `python -m src.printing.helper_main <job.json>`, then writes the snapshot bytes to its stdin in chunks and closes the write channel so the child's `read()` sees EOF.
- The subprocess is started with `cwd=project_root`, and `PYTHONPATH` is extended to include the project root so `src.*` imports resolve regardless of launch directory or frozen packaging mode.
- Child process performs end-to-end submission: apply watermarks (if any), render/rasterize, and submit to either `output_pdf_path` (PDF output) or the OS spooler.
- Progress and terminal status are emitted as line-delimited JSON on stdout (see `src/printing/helper_protocol.py`). The main app parses these events in `src/printing/subprocess_runner.py`.
- During long-running rendering/submission, the helper emits heartbeat messages every few seconds so the parent can differentiate active work from a true stall.

The helper uses shared user-facing message constants from `src/printing/messages.py` so controller UI and helper progress stay consistent.

### 6.2 Lifecycle Guardrails (Close, Stall, Terminate)

Controller print submission is explicitly lifecycle-aware:

- Snapshot/input capture runs off the GUI thread from the moment the user confirms printing.
- Worker-thread callbacks are marshaled back to the GUI thread before touching UI objects (see `_PrintWorkerBridge` in `controller/pdf_controller.py`).
- If the user closes the app while printing is active, the close request is deferred and the UI remains alive; the window auto-closes after the submission finishes.
- The subprocess runner monitors activity and emits a stalled state after a no-progress threshold. Any valid helper message (heartbeat/progress/data) resets the stall timer, so long jobs remain healthy as long as the helper stays responsive. The UI surfaces a terminate option that kills only the helper subprocess and returns the app to normal without requiring a restart.

## 7. Guardrails

View must not directly mutate model. Controller owns mutation orchestration. Model owns document correctness and persistence. Behavior-level feature truth is in `docs/FEATURES.md`; root-cause/fix history is in `docs/solutions.md`.

### 7.1 Resource-guard chokepoints (Phase 2, 2026-06-10)

- **Foreign-document opens — `_guard_foreign_doc(path)` (`model/pdf_model.py`).** Contract: applies the size limit (`_MAX_PDF_BYTES`), opens, rejects encrypted documents, rejects documents over `_MAX_PAGES`, and returns the opened `fitz.Document`; the **caller closes it**. Every `fitz.open` on a user-supplied path *other than the primary `open_pdf` path* must route through it (currently: `insert_pages_from_file`, `headless_merge`, and the merge-dialog sources `open_insert_source`/`open_merge_source`/`compose_merged_document` — R2.7). `insert_pages_from_file` additionally enforces the post-merge invariant (current pages + inserted pages ≤ `_MAX_PAGES`) before mutating the live document, and batches contiguous source-page runs into single `insert_pdf` calls.
- **Central render clamp.** `ToolManager.render_page_pixmap` clamps the requested scale via `safe_render_scale` from `utils/render_limits.py` (shared between model and view layers — view→utils is legal, view→model is not), so every raster path — including interactive zoom and the inline-editor preview renderer — is bounded by construction; leaf-site clamps remain as harmless idempotent double-clamps. `pdf_model.py` re-exports `_safe_render_scale` for backward compatibility.
- **View zoom limits.** `view/pdf_view.py` module constants `_MIN_VIEW_ZOOM`/`_MAX_VIEW_ZOOM` are the single source of truth for all three zoom entry points (Ctrl+wheel, pinch `_zoom_relative`, zoom combo).
- **Watermark sanitization.** `_coerce_wm` (`model/tools/watermark_tool.py`) is the single sanitization chokepoint for watermark dicts; embedded-JSON load, `add_watermark`, and `update_watermark` all funnel through it (NaN/inf-safe via `_finite`).
- **Single-instance IPC filter rule.** `_forwarded_argv_is_acceptable` (`utils/single_instance.py`) resolves EVERY non-flag forwarded token and requires it to be an existing `.pdf`; relative tokens are resolved and validated, never skipped — the untrusted peer is not bound by sender-side normalization.

### 7.2 MVC import-boundary + read-only query API (R2, 2026-06-15)

- **Layer-boundary AST guard — `test_scripts/test_layer_boundaries.py` (R2.1).** CI contract: every `.py` under `model/` imports no Qt (PySide6/PyQt) and no `view`/`controller`; every `.py` under `view/` has **zero** `fitz.open(...)` outside an exact-count allowlist (only `view/text_editing.py`'s no-jump scratch doc). Geometry value-types (`fitz.Rect/Point/Quad/Matrix`) and the typed request channels (`model/edit_requests.py`, `model/object_requests.py`) are data, not document handles, and remain allowed. This guard is the structural net that keeps the R3 decomposition from regressing the boundary silently.
- **Generalized encryption guard (R2.2).** `test_xref_repair.py::test_live_doc_roundtrips_preserve_encryption` now walks **all of `model/`** (not just `pdf_model.py`) across the live-doc receivers `self.doc`/`model.doc`/`self._model.doc`, attributes each `save`/`tobytes` to its enclosing function, checks a function-scoped decrypt-sink allowlist, and rejects an explicit `encryption=PDF_ENCRYPT_NONE` outside that allowlist.
- **Controller read-only query API (R2.3–R2.6).** The view no longer reaches through `controller.model.<…>`; it calls thin read-only forwards on `PDFController` (which own no state): `get_page_rect`/`get_page_rotation` (page geometry), `has_unsaved_changes`, `get_watermarks`, `get_render_width_for_edit`, `ensure_page_index_built`, `iter_text_targets`/`get_text_blocks` (text-target candidates), `resolve_insert_source_file` (the merge-dialog page-count probe, replacing a view `fitz.open`), and `build_insert_preview_html` (the inline-editor preview's css/html — `PreviewRenderer` depends on this callable, not the model's private `_build_insert_css`/`_convert_text_to_html`; the no-jump gate enforces the pixel-identity contract).
- **Print renderer clamp (R2.7).** `src/printing/pdf_renderer.py` clamps the render zoom per page via `safe_render_scale` — the last raster path that had bypassed the decompression-bomb guard.
- **Utils layer purity (PR-8, 2026-07-04).** Two `utils/` violations from the `utils-no-controller-view-model` contract were fixed: (1) the OCR DTOs/enums (`OcrSpan`, `OcrLanguage`, `OcrDevice`, `OcrAvailability`, `OcrRequest`, `parse_page_range`) moved from `model/tools/ocr_types.py` to `utils/ocr_types.py` (a legal model→utils direction), with `model/tools/ocr_types.py` left as a one-line re-export shim so existing importers (`model/tools/ocr_tool.py`, `view/dialogs/ocr.py`) are unaffected; (2) `show_error` moved out of `utils/helpers.py` (it pulled in `PySide6.QtWidgets.QMessageBox`, a View-layer concern) into a new `view/message_boxes.py`. `utils/helpers.py` keeps `parse_pages`/`pixmap_to_qimage`/`pixmap_to_qpixmap`. Controllers import `show_error` from `view.message_boxes` (Controller→View is a legal coordination direction). `utils-no-controller-view-model` is now a **blocking** `lint-imports` contract.
- **View-no-model behavior routing (PR-9, 2026-07-04).** The two real boundary crossings under `view-no-model` were routed through controller injection instead of a direct model import: `view/dialogs/ocr.py::OcrDialog` now takes a required `device_available: Callable[[str], bool]` constructor kwarg (view wiring: `PDFView._ocr_device_available` forwards to `self.controller.is_device_available`, a thin facade added on `PDFController` that calls `model.tools.ocr_tool.is_device_available`); `view/dialogs/optimize.py::OptimizePdfDialog` now takes a required `preset_options: Callable[[str], PdfOptimizeOptions]` constructor kwarg, and `PDFController.start_optimize_pdf_copy()` passes `PDFModel.preset_optimize_options` directly (it already constructs the dialog). The remaining `view→model` imports are pure DTO/type imports (request payloads, options/report dataclasses) with no mutation surface, and are permitted via `ignore_imports` on the `view-no-model` contract in `pyproject.toml` rather than routed. `view-no-model` is now **blocking**; `lint-imports` (all four contracts) is fully blocking in CI.

### 7.3 CI quality gates (Milestone 1, 2026-07-05)

`.github/workflows/ci.yml` (source of truth; see its header comment for the full per-job breakdown) gates on evidence, not aspiration: every gate was flipped from advisory to blocking only after the number it enforces was observed stable on real CI runs. End state: `dependency-audit`, `lint` (ruff, full rule set), `typecheck` (mypy `model/ utils/`), `layer-boundaries` (all 4 import-linter contracts + the `threading.Thread` grep over `view/`+`controller/`), the import-light `test` security suite, and the windows-latest leg of `test-functional` (tests + coverage) are all blocking. The ubuntu-latest `test-functional` leg stays advisory pending the Qt offscreen-teardown SIGBUS (issue #19). The key architectural decision is **single-source coverage threshold**: `pyproject.toml`'s `[tool.coverage.report] fail_under = 75` is the only coverage number in the repo — CI no longer carries its own override (the windows leg previously ran with `--cov-fail-under=0` while its TOTAL was still unproven). It was left at 75 rather than raised once proven, since 3 consecutive windows-latest runs measured a stable 78% TOTAL (local `.venv`, with fixtures present, measures 79%) — 75 already carries real headroom against CI-measured signal, and tightening it further wasn't the evidence-based ask. Toolchain versions for every CI job route through `constraints-ci.txt` (one file, including the packaging toolchain `build`/`setuptools`/`wheel` trio needed by `test_security_packaging.py`'s real-artifact test), pinned to the maintainer's `.venv`, so CI failures reflect code changes rather than dependency drift. See `plans/archive/milestone-1-ci-quality-debt.md` for the full 12-PR history and end-of-milestone smoke-test evidence (a scratch branch with an E402, a `threading.Thread` in `view/`, and a deleted covered function each tripped their respective gate red, then was discarded).

## 8. Optimize PDF Copy (檔案 Tab)

The optimize-copy flow is a "write a new file" pipeline. It must never mutate the live active `fitz.Document` in-place. It is designed to keep the GUI responsive on large PDFs by moving the heavy work off the main thread and preventing competing background loaders from consuming CPU during optimization.

```mermaid
flowchart TD
  A["User: 檔案 > 另存為最佳化的副本"] --> B["Controller: start_optimize_pdf_copy()"]
  B --> C["OptimizePdfDialog(preset_options=PDFModel.preset_optimize_options)\n- preset=平衡(default)\n- 審計空間使用報告(on-demand)"]
  C -->|OK| D["Pick output path"]
  D --> E["Controller: _start_optimize_submission()\n- pause active tab background loading\n- show progress dialog\n- QThread worker"]
  E --> F["Worker: PDFModel.save_optimized_copy(output, options)"]

  subgraph Model["Model: save_optimized_copy()"]
    F --> G["Resolve options\n- normalize conflicts (linear vs objstms)\n- original_bytes from file stat when possible"]
    G --> H["Build disposable working_doc\n- clean file-backed: reopen from path\n- dirty/in-memory: snapshot bytes -> open\n- ToolManager.prepare_doc_for_save(session_id, working_doc)"]
    H --> I["Apply options\n- cleanup / metadata / fonts\n- optimize_images (dominant cost)"]
    I --> J["Optimize images\n- scan pages -> image_usage{xref -> (page_index, max_dpi)}"]
    J --> K{"Parallelize?"}
    K -->|clean file-backed| L["Parallel A\nworkers reopen source PDF\nextract_image + transcode\nparent replace_image"]
    K -->|dirty/in-memory| M["Parallel B\nparent extract_image once\nworkers transcode bytes\nparent replace_image"]
    K -->|fallback| N["Serial\nextract + transcode + replace"]
    L --> O["Fast save to temp\n- fitz.save fast flags\n- optional pikepdf packaging for linearize/object streams"]
    M --> O
    N --> O
  end

  O --> P["Atomic move temp -> output\nreturn PdfOptimizationResult"]
  P --> Q["Controller: open_pdf(output) as new tab\nthen show completion message (KB/MB/GB + bytes)"]
```

`OptimizePdfDialog` does not import `PDFModel` (PR-9): the controller injects `preset_options=PDFModel.preset_optimize_options` at construction time, and the dialog calls `self._preset_options(preset)` internally.

Performance guardrails:
- `PDFModel.save_optimized_copy(...)` runs in a worker thread (`QThread`) so the main thread remains interactive.
- Before dispatching the worker, the controller invalidates the active tab's background scene/index batch loops so they do not compete with the optimizer for CPU.
- Image transcode can use multiple processes for large PDFs; the model falls back to serial mode when multiprocessing is not safe in the current runtime.

## 9. Merge PDFs (Merge Dialog)

This section follows `docs/Methodology_for_Writing_Docs.md` and documents the stable contract for the merge-dialog design.

### 9.1 Components

- View: `MergePdfDialog` in `view/pdf_view.py`
  - Owns the modal UI and displays the ordered merge list.
  - Stores `entry_id` on each list item (Qt UserRole) and retains the `MergeEntry` object for confirm-time readout.
- Model (dialog-scoped): `MergeSessionModel` / `MergeEntry` in `model/merge_session.py`
  - Holds merge entries including a locked `current` entry.
  - Provides add/remove and ordering helpers.
- Controller: `PDFController.start_merge_pdfs()` and merge helpers in `controller/pdf_controller.py`
  - Supplies the file resolver (password loop, rejection handling) and dispatches the merge into either save-as-new or merge-into-current flows.

### 9.2 Ordering Contract (Change-Control)

Problem class: the merge list has two representations (Qt list widget order vs. `MergeSessionModel.entries` order). If these drift, add/remove can “snap back” to stale model order.

Contract:
- The session model must be synchronized from the UI order whenever the user reorders rows, and also before any add/remove mutation.
- The UI rebuild path (`_refresh_file_list()`) must always reflect `MergeSessionModel.entries` and must not be able to revert user order.

Guardrails (do not change casually):
- If you modify list ordering, add/remove, or refresh behavior, update `docs/FEATURES.md` section “Merge PDFs (頁面 Tab)” and re-run the regression tests in `test_scripts/test_pdf_merge_workflow.py` that assert reorder-then-add/remove preserves order.

## 10. No-Jump Inline Text Editing

The inline editor must be pixel-faithful to the committed PDF so opening,
typing, and reopening never visibly shift glyphs. Five cooperating pieces:

- **Shared insert classifier** — `model.pdf_model._classify_insert_path` is the
  single source of truth for "fast `insert_text`" vs "`insert_htmlbox`". Both
  the commit path (`_apply_redact_insert`) and the preview path
  (`PreviewRenderer`) route through it; they cannot diverge.
- **`PreviewRenderer`** (view) rasterizes proposed content through the *same*
  MuPDF `insert_htmlbox` engine and CSS the commit uses (borrowed from the
  model when present), cached by full arg tuple incl. `line_height`.
- **`_display_font_pt`** converts pdf pt → Qt widget pt
  (`× render_scale × 72/logical_dpi`) so editor glyphs equal rendered-PDF
  glyphs in physical pixels.
- **`PreviewBackedInlineTextEditor`** paints a *frozen* MuPDF capture of the
  span while text == initial, the live CSS preview once mutated; the decision
  flag is cached on `textChanged`, never recomputed per paint.
- **Run-reopen anchors** (`DocumentSession.run_reopen_anchors/_sizes`, keyed
  `"{page_idx}::{span_id}"`) record the original bbox+size on the first
  run-mode non-drag edit; commit pins layout back to the anchor and migrates it
  onto the best-scoring rebuilt run, so reopen cycles do not cumulate shrink.

Boundary note: `view/pdf_view.py` only emits signals
(`sig_edit_text`/`sig_add_textbox`) — the View→Controller→Model rule holds.
Two import-time compatibility shims exist (rawdict `span['text']` backfill in
the model; `QGraphicsProxyWidget.graphicsProxyWidget` in the view) — see
`docs/PITFALLS.md`.

Guardrails (do not change casually):
- Preview and commit must keep sharing `_classify_insert_path`.
- Never assign `editor.font = <QFont>` (shadows `QTextEdit.font()`); build the
  `QFont` with `_display_font_pt`.
- The `paintEvent` frozen-vs-preview two-branch contract and the
  `_text_matches_initial` caching are load-bearing — the gate
  `scripts/verify_no_jump.py` (27 deterministic cases, run twice) enforces it.

## 11. Character-Level Text Selection (Browse Mode)

**Module:** `model/pdf_model.py:get_chars_in_run()`, `get_text_selection_lines()`

Text selection in browse mode now operates at character granularity instead of
run/line granularity. The model provides per-character bounding boxes extracted
from `page.get_text("rawdict")` and clips boundary runs (start and end) to the
actual character range between cursor start and cursor end points.

- `get_chars_in_run(page_num, span_id) -> list[tuple[str, fitz.Rect]]` returns
  per-character data for a single run, cached per page session.
- `get_text_selection_lines(page_num, start_span_id, end_point, start_point)`
  returns `(text: str, rects: list[Rect])` with one highlight rect per visual
  line; boundary runs are clipped to character boundaries, intermediate runs are
  fully included.
- Character-bleed filtering uses asymmetric tolerance: loose along the reading
  axis (x for horizontal, y for vertical) to accommodate natural inter-character
  spacing; tight cross-axis to prevent glyphs from overlapping lines from
  entering the wrong run's list.

View-side: `_update_text_selection()` receives `(text, [rects])` from the model
and renders one highlight item per rect, so multi-line selections show proper
line-by-line coverage.

## 12. Print — Auto Orientation & Paper Size

**Modules:** `src/printing/layout.py`, `src/printing/qt_bridge.py`

Print now auto-detects source PDF page dimensions and applies matching:
- **Orientation:** If `width > height` (landscape), emit landscape orientation;
  if `height > width`, emit portrait. Mixed-orientation PDFs handle each page
  independently.
- **Paper size:** Match source dimensions (±3pt tolerance) against an expanded
  `PAPER_SIZE_POINTS` table (A0–A6, B4, B5, Letter, Legal, Tabloid). When a
  match is found, return the named `QPageSize` constant (driver-recognized);
  non-standard sizes fall back to a custom `QPageSize` with source dimensions.

`match_standard_paper_size(width_pt, height_pt, tolerance_pt=3.0)` performs
the matching with a tie-break fix: when two sizes are equally close, the first
match is returned (no truncation of equally-close candidates).

Windows printer drivers recognize named `QPageSize` objects but silently ignore
custom ones, snapping to their default (usually A4 portrait). Named sizes
guarantee driver-side behavior.

## 13. Object Manipulation — Free Drag Rotation & Aspect Ratio Resize

**Modules:** `view/pdf_view.py`, `model/pdf_content_ops.py`, `model/pdf_model.py`

### 13.1 Free Drag Rotation

Object rotate handles now support continuous real-time rotation on drag, not
just 90° increments:
- On press over rotate handle: capture starting angle (atan2 from object centre
  to cursor).
- On move: compute live angle, emit `RotateObjectRequest(absolute_rotation=...)`
  each frame (throttled to 8ms).
- On release: finalize; a single undo entry covers the entire drag sequence.

Selection box outline and resize handles rotate with the object via
`setTransformOriginPoint(center)` and `setRotation(angle)` applied to the
selection rect item and each handle item.

Moving a previously-rotated object preserves rotation by threading
`current_rotation` through `MoveObjectRequest` into the model's cm-matrix
rewrite path.

### 13.2 Aspect Ratio Locked Resize

Shift+drag on any resize handle locks the aspect ratio:
- Newly inserted images default to free-form (no lock).
- All native PDF images also default to free-form.
- When locked, the secondary dimension is clamped to preserve the start rect's
  aspect ratio.

### 13.3 Native Image Selectability

Native PDF images (Form XObjects and image XObjects) are discovered via a
multi-pass scan in `discover_native_image_invocations()`:
1. `page.get_images(full=True)` for directly embedded images.
2. `page.get_xobjects()` enumeration for image-type XObjects (including nested
   Form images).
3. Secondary pass for Form XObjects not caught by the above (empirically
   recovers placement affine from form-space to page-space via `form_rect_to_stream_cm()`).

Object rotation, move, and resize rewrite the PDF content stream operators
(`cm`, `Do`) in place, preserving overlapping text and graphics.

## 14. macOS Native Menu Bar

**Module:** `view/pdf_view.py:_build_macos_menu_bar()`, `_macos_menu_spec()`

On macOS, a native menu bar is built from a spec that reuses ribbon QActions:
- **App menu:** About, Preferences, Quit (role-tagged for OS relocation).
- **File menu:** Open, Save, Save As, Print, Close Tab.
- **Edit menu:** Undo, Redo, Copy, Paste (Copy/Paste use clipboard callbacks).
- **View menu:** Fullscreen.
- **Window, Help:** Standard macOS menu skeletons.

All keyboard shortcuts use `QKeySequence.StandardKey` constants (Cmd-mapped on
macOS: Cmd+Q, Cmd+W, Cmd+S, etc.).

On Windows/Linux, `_build_macos_menu_bar()` returns `False` as a no-op, leaving
existing platform-specific menu handling untouched.

## 15. PDF Standards Compliance Validation

**Module:** `model/pdf_validator.py`

`check_pdf_conformance(path) -> list[str]` validates ISO 32000-1 (PDF 1.7)
structural well-formedness:
1. Recognizable PDF version header.
2. Intact cross-reference table (PyMuPDF `is_repaired == False`).
3. Parseable, non-empty page tree; every page object and its content
   (streams, fonts, XObjects) resolve.
4. All in-use xref entries resolve to object definitions.

Returns an empty list if no issues detected; otherwise returns human-readable
warnings.

Encrypted/un-authenticated PDFs are reported as unable to validate rather than
silently passing.

XREF repair is automatic on open: `PDFModel.open_pdf()` checks `doc.is_repaired`
(the flag PyMuPDF sets when it rebuilds a damaged cross-reference table) and, if
set, round-trips the document in memory (`_repair_doc_xref_in_memory`,
`tobytes(garbage=1)` → reopen) so the active document carries a clean, consistent
xref. It deliberately skips `deflate=True`: re-compressing streams is the dominant
cost on large/image-heavy files (≈20 ms/MB) and adds nothing to a clean-xref repair,
so the round-trip stays at ≈2.5–5 ms/MB (~1.3–2.6 s worst case at the 512 MB open
cap; a real damaged 47 MB / 402-page file repaired on open in ~240 ms with content
byte-identical to the healthy file). Peak memory is ~1.15× file size (one
serialization buffer; the source streams lazily). Healthy files pay only a single
flag read; the round-trip runs only for damaged files. `check_pdf_conformance()`
then confirms restoration (the issue clears).
**Encrypted documents are exempt:** `tobytes()` emits a decrypted PDF, so a
round-trip would silently strip the password/permissions on the next save.
`open_pdf` skips the round-trip when `_doc_is_encrypted(doc)` (trailer encryption
string in `doc.metadata`, which survives auth and covers owner-only files);
MuPDF's repaired-but-encrypted doc is kept and a later full save with
`encryption=KEEP` writes a clean xref while preserving the encryption. Because the
save-over-open-file path closes and reopens the doc (to release the Windows lock),
the session keeps the open-time password (`DocumentSession.password`, in-memory)
and re-authenticates the reopened handle via `_reopen_doc_after_save` — otherwise
the live editing session would be left locked after an encrypted save-back.
There is no longer a manual "repair xref" toolbar action.

See `docs/pdf_compliance.md` for scope, limitations, and test coverage.
