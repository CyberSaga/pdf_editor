# Trusted Task

Adversarially code-review the supplied R4 commit diff only. Context: PySide6/PyMuPDF desktop PDF editor; range promises output-identical performance changes. Enforce changed-line causality and reject pre-existing/style/test-only noise. Focus on correctness, security, resources, architecture, async QThread/session races, cache invalidation, and undo memory-budget semantics. For each real issue provide exact file/lines, trigger, causal trace, severity, and confidence 0-100. Specifically verify or refute: (A) content-based set[bytes] counts equal but separately allocated snapshots once even though both remain resident; (B) thumbnail bridge signals carry gen but not session id while generation counters are per-session and can collide after tab switches. Also search independently for other >=80-confidence defects.

# Untrusted Context

--- BEGIN UNTRUSTED STDIN ---
diff --git a/TODOS.md b/TODOS.md
index 9d13150..795b7a6 100644
--- a/TODOS.md
+++ b/TODOS.md
@@ -1,53 +1,54 @@
 # TODOS
 
 ## Audit remediation (2026-06-10 two-round audit)
 
 - [x] **Phase 1 (2026-06-12) ? Search snapshot restore / print snapshot funnel:** search workers now read private snapshot bytes captured on the GUI thread, completed tab-search results are preserved per tab across switches, and only in-flight partial searches are cleared on cancel; print submission captures snapshot bytes before the helper thread starts. Tests: `test_scripts/test_search_worker_flow.py`, `test_scripts/test_multi_tab_plan.py::test_05_search_state_restored_per_tab`, `test_scripts/test_print_controller_flow.py`.
 - [x] **Phase 2 (2026-06-12) ? Watermark double-stamp fix:** `WatermarkTool.needs_page_overlay(...)` now returns `False` for `purpose == "print"`, leaving the helper subprocess as the only print stamping path; helper heartbeat output now refreshes runner activity so heartbeat lines do not trip the stall watchdog. Tests: `test_scripts/test_print_snapshot_path.py`, `test_scripts/test_print_subprocess_runner.py`.
 - [x] **Phase 3 (2026-06-12) ? OCR worker parity:** `_OcrWorker` now receives GUI-thread snapshot bytes, `OcrTool.ocr_pages(..., doc=...)` can render from an override document/bytes, every OCR signal carries a generation token (`cancel_ocr` bumps it, handlers drop stale gens) and `page_done` is additionally dropped when the active session no longer matches the captured `_ocr_session_id`; OCR cancellation is non-blocking from session-switch/close chokepoints. Tests: `test_scripts/test_ocr_controller_flow.py`.
 - [x] **Flaky test under load (resolved R0.3, 2026-06-15):** `test_scripts/test_print_subprocess_runner.py::test_runner_heartbeat_events_prevent_false_stall` ? fixed by injecting a fake monotonic clock into `PrintSubprocessRunner` (`monotonic=` param defaulting to `time.monotonic`, production behavior unchanged); the test advances the clock explicitly, so stall detection is wall-clock independent. Verified green ?5 under `.venv`.
 
 - [x] **Phase 0 ? Restore the Gate:** polluter = stylesheet leak in `test_main_startup_behavior.py`; fixed via cleanup + widget QSS override + conftest fixture (7 order-dependent failures in `test_no_jump_editor_geometry.py` eliminated).
 - [x] **Phase 1 ? Linearize Capability Gate + Error Wrapping:** dead PyMuPDF `linear=1` fallback deleted (fail-fast `PdfOptimizeError`); `optimize_capabilities()` runtime probe gates the dialog's linearize/object-streams checkboxes; double ???? PDF ??:? prefix fixed; `pikepdf>=8.0` in optional-requirements.txt and installed into `.venv`.
 - [x] **Phase 2 ? Chokepoint Guards (OOM / Logic-Bypass):** all six items landed (2026-06-10): central `_safe_render_scale` clamp in `ToolManager.render_page_pixmap` (strict-xfail red-light flipped green, marker removed); shared `_MIN/_MAX_VIEW_ZOOM` constants across wheel/pinch/combo; `_guard_foreign_doc` chokepoint (size/pages/encryption) routing `insert_pages_from_file` + `headless_merge`, with post-merge `_MAX_PAGES` invariant and contiguous-run insert batching; `AnnotationTool._require_page` (page 0 no longer silently annotates `doc[-1]`); NaN/inf-safe watermark `_coerce_wm` chokepoint funneling `add_watermark`/`update_watermark`; single-instance argv filter now resolves every non-flag token. Plan: `plans/phase-2-chokepoint-guards.md`.
 - [x] **Phase 3 ? Memory Budgets** (landed 2026-06-10): `CommandManager` now enforces `MAX_UNDO_STACK_BYTES = 512 MiB` over per-command `_byte_size()` (oldest-first eviction, `_saved_stack_size` decremented per eviction) and dedups adjacent `SnapshotCommand` boundary snapshots (`prev._after_bytes` shared into `curr._before_bytes` when equal) at all three push sites; `build_print_snapshot` writes the print-input PDF directly to a dest `Path` (fast path `doc.save(..., encryption=KEEP)`, overlay path `tmp_doc.save`), `PrintJobRequest.capture_pdf_bytes` ? `write_pdf_to`, and dead `PDFModel.capture_print_input_pdf_bytes` removed. Plan: `plans/phase-3-memory-budgets.md`. Tests: `test_scripts/test_undo_memory_budget.py`, `test_scripts/test_print_snapshot_path.py`.
 - [x] **Phase 4 ? UI-Thread Responsiveness** (landed 2026-06-10): 4.1 async thumbnails ? structural call sites (delete/rotate/straighten/insert ?2/merge, structural undo/redo) now use `_invalidate_thumbnails(affected)` (synchronous `set_thumbnail_placeholders` first, then load-gen bump + `_schedule_thumbnail_batch` next tick); cross-page text moves no longer touch thumbnails; `_update_thumbnails` kept only as a deprecated test shim. 4.2 search worker ? `SearchTool.search_page(page_num, query)` + `_SearchWorker`/`_SearchBridge` (gen-tokened signals), incremental accumulate into `display_search_results`, search_state persisted on worker finish; `_cancel_search()` guards all doc-mutating methods + tab switch/close/open. Plan: `plans/phase-4-ui-responsiveness.md`. Tests: `test_scripts/test_thumbnail_async.py`, `test_scripts/test_search_worker_flow.py`.
 - [x] **Phase 4 (2026-06-12) ? Thumbnail invalidation fixes:** `_invalidate_thumbnails` now skips `set_thumbnail_placeholders` when page count is unchanged (rotate/straighten/text-move), rendering only affected rows via `end_limit`; uses dedicated `_thumb_gen_by_session` counter instead of bumping `_load_gen` (no longer cancels viewport-anchor restore or open-background fallback); cross-page text moves now invalidate thumbnails for both source and destination pages on success and rollback; dead `_update_thumbnails` deleted. Tests: `test_scripts/test_thumbnail_async.py`, `test_scripts/test_cross_page_text_move.py`.
 - [x] **Phase 5 (2026-06-12) ? Undo byte budget fixes:** Trim floor keeps at least 1 command (the newest) even if it exceeds the budget ? prevents `can_undo()` silently becoming False; `_unique_byte_total()` counts shared dedup'd bytes objects once (via `id()`), not double, restoring the full effective 512 MiB budget for dedup'd stacks. Tests: `test_scripts/test_undo_memory_budget.py`.
 - [x] **Phase 6 (2026-06-12) ? QSS padding fix + preview render clamp:** `_build_text_editor_stylesheet` now includes `padding: 0px; margin: 0px;` so the theme's `QTextEdit { padding: 4px 8px; }` rule cannot cascade back and shift glyphs; new `utils/render_limits.py` with `safe_render_scale` and `_MAX_PIXMAP_PX` (moved from `pdf_model.py`, re-exported for backwards compat); `view/text_editing.py` clamps the preview `get_pixmap` via `_safe_render_scale`. Tests: `test_scripts/test_text_editor_theme_padding.py`.
 - [x] **Phase 7 (2026-06-12) ? Guards + optimizer + hygiene:** `render_page_pixmap` now rejects page_num < 1 or > len(doc); wheel zoom uses effective clamped factor instead of raw factor (no overshoot/snap-back at boundaries); IPC dash-token skip deleted (every non-blank token must resolve to an existing .pdf); `optimize_capabilities` reports `object_streams: True` unconditionally (native PyMuPDF `use_objstms=1`), `fast_save_kwargs` passes objstms from options, `requires_post_save_packaging` only gates on linearize. Tests: `test_scripts/test_phase7_guard_hygiene.py`.
-- [ ] **Phase 4.3 (deferred) ? Overlay render cache.** Deferred from Phase 4: caching the overlay raster (watermark/annotation overlays composited during page render) requires revision counters on BOTH `WatermarkTool` and `AnnotationTool` plus cache state on the currently stateless `ToolManager`; the overlay path is only active when overlays exist, so the win is conditional. Non-blocking per the audit master plan ? design the revision-counter invalidation before implementing.
-- [ ] **Deferred ? Snapshot-bytes caching.** Cache worker snapshot bytes keyed by `_render_revision` so overlapping search/OCR/print requests reuse the same serialization instead of re-calling `tobytes()`.
-- [ ] **Deferred ? Undo dedup digest optimization.** The `memcmp`-on-record optimization (C-speed `bytes.__eq__`, one adjacent pair) is accepted but deferred ? the current `id()`-based dedup covers the common case.
+- [~] **R4.1 (2026-06-17) ? Overlay render cache: EVALUATED ? DEFERRED.** (Was "Phase 4.3 ? Overlay render cache.") Source audit + 3-way design review concluded every variant is incorrect, high-risk (no watermark pixel gate), or a non-win: (1) watermark-only (annotations are baked via `annots=True`, not overlays); (2) the literal spec key omits a base-content revision ? would serve stale composites when text under a watermark is edited; (3) the only complete invalidation signal is the controller's whole-session `_render_revision`, so a safe cache is redundant with the existing `_render_cache` (which already prevents redundant overlay compute within a revision) ? it only helps under a cache-eviction edge case while needing the controller token threaded into the model + ~2? memory; (4) the separate-canvas variant must replicate page rotation/MediaBox/colorspace exactly with no pixel-parity coverage. The real win (cross-revision per-page reuse) needs per-page content-revision tracking across the ~25 `_invalidate_active_render_state` sites (one miss = silent stale render). Disproportionate risk for a watermark-only conditional gain. Full rationale: `plans/refactor-R4-performance-deferrals.md` (R4.1 STATUS block) + `refactor-state.md` turn 28. **Revisit only if** watermarked scroll-after-edit latency becomes a measured bottleneck (then: separate-canvas + a new watermark pixel gate built first).
+- [x] **R4.3 (2026-06-17) ? Thumbnail rasterization ? QThread.** Large, overlay-free thumbnail rebuilds now render on a background `_ThumbnailWorker` (`controller/thumbnail_coordinator.py`, mirrors `SearchCoordinator`/`OcrCoordinator`) off the R4.2 snapshot bytes ? never the live `fitz.Document` ? marshalling detached `QImage`s back via `_ThumbnailBridge` to the GUI thread, which converts to `QPixmap`. `_schedule_thumbnail_batch` delegates to `coordinator.try_start(...)` and falls back to the existing synchronous path. **Behavior-preserving:** the async path runs ONLY when the session has no view overlays (watermarks compose at render time and are absent from snapshot bytes, so a worker render would drop them ? `_should_async` checks `get_watermarks()`) and the range ? `THUMB_ASYNC_MIN_PAGES`; otherwise sync (output byte-identical). The `_thumb_gen_by_session` token drops a cancelled/superseded tab's late batches before painting. Tests: `test_thumbnail_coordinator.py` (11 tests; the real-thread end-to-end was deliberately left out as Qt/COM-flaky ? see the file note).
+- [x] **R4.2 (2026-06-17) ? Snapshot-bytes caching.** Controller now owns a single-entry cache of the full-doc worker snapshot bytes (`PDFController.capture_worker_snapshot_bytes`), keyed by `(active_session_id, render_revision)`; the 3 coordinators (search/OCR/print) call the controller instead of the model, so overlapping jobs on an unedited doc reuse one serialization. **Correctness subtlety (caught in design):** OCR's `apply_ocr_spans` injects invisible text (`render_mode=3`) ? searchable but pixel-identical, so it does NOT bump `_render_revision`; the OCR coordinator therefore drops the snapshot cache after applying spans, or a later search would read stale pre-OCR bytes. Tests: `test_worker_snapshot_cache.py` (4 tests incl. the OCR-staleness regression guard).
+- [x] **R4.4 (2026-06-17) ? Undo dedup coverage.** `_unique_byte_total` (`edit_commands.py:642`) deduped by `id()`, so byte-identical snapshots that `_dedup_top_snapshot_pair` never aliased (any *non-adjacent* pair ? only the top two are compared at push time) were double-counted against the 512 MiB budget, evicting undo history prematurely. Now dedups by **content** (`set[bytes]`; CPython caches the hash on each bytes object, so it stays amortized-cheap across the repeated calls in the trim loop) ? exact, leak-free (no persistent intern map). `_dedup_top_snapshot_pair`'s real RAM-sharing for the hot adjacent case is unchanged. Tests: `test_undo_memory_budget.py::test_non_adjacent_identical_bytes_counted_once` + `::test_non_adjacent_duplicate_does_not_prematurely_evict`.
 - [ ] **Deferred ? MVC routing of merge-dialog page counting.** The view-layer `fitz.open()` calls in `pdf_view.py` (merge dialog page-count probe) should route through a controller/model utility to respect layer boundaries.
-- [ ] **Deferred ? Preset objstms re-enable.** The optimizer presets currently leave `use_object_streams=False`; now that native `use_objstms=1` works, consider enabling it by default in balanced/compression presets.
+- [x] **R4.5 (2026-06-17) ? Preset objstms re-enable.** Census found the residual was narrower than the original note: `??` already sets `use_object_streams=True`, and `????` is structurally blocked (`linearize=True` ? `normalize_optimize_options` strips objstms). `??` (`linearize=False`) was the only genuine opportunity ? flipped `use_object_streams=False ? True` in `preset_optimize_options` (`pdf_optimizer.py:229`); the flag survives normalization and reaches `fast_save_kwargs` as `use_objstms=1`. Test: `test_pdf_optimize_workflow.py::test_fast_preset_enables_object_streams`.
 - [x] **Phase 5 ? Hygiene / Documentation** (landed 2026-06-11): `pyproject.toml` added (name=`cybersaga-pdf`, setuptools backend with explicit flat-layout package discovery incl. the `src.printing` namespace package; deps mirror requirements.txt; `dev` extra = ruff/mypy/pytest; `[tool.ruff]` encodes the default rule set so the 240-violation baseline is stable; `[tool.mypy]` gradual + `explicit_package_bases` for the parent-dir `__init__.py` gotcha; `[tool.pytest.ini_options] testpaths=["test_scripts"]`). `pip install -e ".[dev]"` now works (`.venv` pip upgraded 21.2.3 ? 26.1.2 for PEP 660). PITFALLS: cooperative OCR cancellation entry. CLAUDE.md ?3.1 violation count reconciled (113 ? 240). Plan: `plans/phase-5-hygiene.md`.
 
 ## Done (2026-06-14) -- UI/UX Fable-5 polish refactor
 
 - What: Raised UI/UX polish (visual hierarchy, spacing/alignment, elevation, and
   modern `:hover`/`:pressed`/`:focus` feedback) under two hard constraints ?
   **no icon changes** and **no new colours**. Branch `feat/ui-ux-fable5-refactor`.
 - Shipped:
   - `view/theme.py` ? token dicts grew 17 ? 20 keys with three brand colours
     lifted verbatim from `appearance_design/colors.css` (`accent_line`,
     `hover_strong`, `shadow`; shadow alpha pinned to the documented `--shadow-lg`
     layer). `build_qss` gained: colour-only focus rings (no layout shift), hover
     states on all three tab families (scoped), slim themed scrollbars, themed
     `QSplitter::handle`, `QToolTip`, accent-fill check/radio indicators (no glyph
     asset ? respects icon lockdown), `QMenu` padding + separators, accent
     `QPushButton:default`, `#rightPanelTitle` section header, toolbar separators.
     New Qt-guarded `shadow_color()` + `_parse_qcolor` (QColor can't parse
     `rgba()` float-alpha).
   - `view/pdf_view.py` ? right-panel "??" title moved off an inline stylesheet
     onto `#rightPanelTitle`; theme-aware `QGraphicsDropShadowEffect` on the
     toolbar chrome (`_apply_chrome_shadow`, re-applied colour-only on theme
     switch). Adaptive-toolbar logic untouched.
   - Tests: `test_scripts/test_theme_and_icons.py` +28 (new tokens, focus,
     scrollbars, splitter, tooltip, scoped tab hover, indicators, default button,
     shadow helper, `#rightPanelTitle`). Red-light shown before implementation.
 - Verified: 1354 passed / 20 skipped / 0 failed; ruff clean on both files; QSS
   parses with 0 warnings across all 4 themes; icons (`view/icons.py`,
   `appearance_design/`) byte-identical. 5-lens adversarial review (icons /
   colors / architecture / qss-correctness) returned clean (qt-runtime lens
   blocked by a session limit; its concerns were self-verified offscreen).
diff --git a/controller/ocr_coordinator.py b/controller/ocr_coordinator.py
index 011a97c..a1d0743 100644
--- a/controller/ocr_coordinator.py
+++ b/controller/ocr_coordinator.py
@@ -153,61 +153,61 @@ class OcrCoordinator:
         if self._ocr_thread is not None:
             show_error(self._c.view, "OCR ?????")
             return
         if not self._c.model.doc:
             show_error(self._c.view, "????? PDF ??")
             return
 
         tool = self._c.model.tools.ocr
         availability = tool.availability()
         if not availability.available:
             msg = availability.reason or "Surya OCR ???"
             if availability.install_hint:
                 msg = f"{msg}\n{availability.install_hint}"
             show_error(self._c.view, msg)
             return
 
         page_nums = [idx + 1 for idx in request.page_indices]
         if not page_nums:
             show_error(self._c.view, "???????")
             return
 
         self.cancel_ocr()
         self._ocr_gen += 1
         self._ocr_session_id = self._c.model.get_active_session_id()
         thread = QThread()
         worker = _OcrWorker(
             tool,
             page_nums=page_nums,
             languages=list(request.languages),
             device=request.device,
-            doc_bytes=self._c.model.capture_worker_snapshot_bytes(),
+            doc_bytes=self._c.capture_worker_snapshot_bytes(),
             gen=self._ocr_gen,
         )
         worker.moveToThread(thread)
         thread.started.connect(worker.run)
         if self._ocr_worker_bridge is not None:
             worker.progress.connect(self._ocr_worker_bridge.forward_progress)
             worker.status.connect(self._ocr_worker_bridge.forward_status)
             worker.page_done.connect(self._ocr_worker_bridge.forward_page_done)
             worker.failed.connect(self._ocr_worker_bridge.forward_failed)
             thread.finished.connect(self._ocr_worker_bridge.notify_thread_finished)
         worker.finished.connect(thread.quit)
         worker.finished.connect(worker.deleteLater)
         thread.finished.connect(thread.deleteLater)
         thread.finished.connect(lambda t=thread: self._release_ocr_thread(t))
 
         self._ocr_thread = thread
         self._ocr_worker = worker
         self._show_ocr_progress_dialog(len(page_nums))
         thread.start()
 
     def cancel_ocr(self) -> None:
         # Bump the gen first so queued cross-thread signals already posted by
         # the worker are dropped by the handlers (they compare against it).
         self._ocr_gen += 1
         if self._ocr_worker is not None:
             self._ocr_worker.request_cancel()
 
     def _release_ocr_thread(self, thread) -> None:
         if self._ocr_thread is thread:
             self._ocr_thread = None
@@ -238,47 +238,51 @@ class OcrCoordinator:
     def _on_ocr_progress(self, gen: int, page_num: int, done: int, total: int) -> None:
         if gen != self._ocr_gen:
             return
         dialog = self._ocr_progress_dialog
         if dialog is None:
             return
         dialog.setMaximum(total)
         dialog.setValue(done)
         dialog.setLabelText(f"??? {done}/{total} ?? (? {page_num})")
 
     @Slot(int, str)
     def _on_ocr_status(self, gen: int, message: str) -> None:
         if gen != self._ocr_gen:
             return
         dialog = self._ocr_progress_dialog
         if dialog is None:
             return
         dialog.setLabelText(message)
 
     @Slot(int, int, object)
     def _on_ocr_page_done(self, gen: int, page_num: int, spans) -> None:
         if gen != self._ocr_gen:
             logger.warning("Dropping OCR page %s from stale gen %s (current=%s)", page_num, gen, self._ocr_gen)
             return
         active_sid = self._c.model.get_active_session_id()
         if self._ocr_session_id is not None and active_sid != self._ocr_session_id:
             logger.warning("Dropping OCR page %s for stale session %s (active=%s)", page_num, self._ocr_session_id, active_sid)
             return
         try:
             self._c.model.apply_ocr_spans(page_num, list(spans))
+            # OCR injects invisible text (render_mode=3): it changes doc.tobytes()
+            # (searchable!) but is pixel-identical, so it does NOT bump render_revision.
+            # Drop the worker snapshot cache or a later search reads stale pre-OCR bytes.
+            self._c._invalidate_worker_snapshot_cache()
         except Exception:
             logger.exception("apply_ocr_spans failed for page %s", page_num)
 
     @Slot(int, object)
     def _on_ocr_failed(self, gen: int, exc) -> None:
         if gen != self._ocr_gen:
             return
         logger.error("OCR failed: %s", exc)
         show_error(self._c.view, f"OCR ??: {exc}")
 
     @Slot()
     def _on_ocr_thread_finished(self) -> None:
         dialog = self._ocr_progress_dialog
         if dialog is not None:
             dialog.close()
         self._ocr_progress_dialog = None
         self._release_ocr_thread(None)
diff --git a/controller/pdf_controller.py b/controller/pdf_controller.py
index d567fe6..06cd6e4 100644
--- a/controller/pdf_controller.py
+++ b/controller/pdf_controller.py
@@ -139,115 +139,121 @@ class _OptimizeWorkerBridge(QObject):
     succeeded = Signal(object)
     failed = Signal(object)
     thread_finished = Signal()
 
     @Slot(object)
     def forward_succeeded(self, result) -> None:
         self.succeeded.emit(result)
 
     @Slot(object)
     def forward_failed(self, exc) -> None:
         self.failed.emit(exc)
 
     @Slot()
     def notify_thread_finished(self) -> None:
         self.thread_finished.emit()
 
 
 # R3.2: the async OCR subsystem (worker, bridge, orchestration + state) lives in
 # controller/ocr_coordinator.py. _OcrWorker/_OcrBridge are re-exported here so
 # `from controller.pdf_controller import _OcrWorker, _OcrBridge` stays valid.
 from controller.ocr_coordinator import (  # noqa: E402
     OcrCoordinator,
     _OcrBridge,  # noqa: F401  (re-export for backward compatibility)
     _OcrWorker,  # noqa: F401  (re-export for backward compatibility)
 )
 
 
 # R3.2: the async search subsystem (worker, bridge, orchestration + state) lives in
 # controller/search_coordinator.py. _SearchWorker/_SearchBridge are re-exported here so
 # `from controller.pdf_controller import _SearchWorker, _SearchBridge` stays valid.
+from controller.thumbnail_coordinator import ThumbnailCoordinator  # noqa: E402
 from controller.search_coordinator import (  # noqa: E402
     SearchCoordinator,
     _SearchBridge,  # noqa: F401  (re-export for backward compatibility)
     _SearchWorker,  # noqa: F401  (re-export for backward compatibility)
 )
 
 
 class PDFController:
     _VALID_MODES = {"browse", "edit_text", "add_text", "rect", "highlight", "add_annotation"}
     def __init__(self, model: PDFModel, view: PDFView):
         self.model = model
         self.view = view
         self.annotations = []
         self._print_coordinator = PrintCoordinator(self)
         self._optimize_progress_dialog: QProgressDialog | None = None
         self._optimize_thread: QThread | None = None
         self._optimize_worker: _OptimizePdfCopyWorker | None = None
         self._optimize_worker_bridge: _OptimizeWorkerBridge | None = None
         self._optimize_paused_session_id: str | None = None
         self._ocr_coordinator = OcrCoordinator(self)
         self._search_coordinator = SearchCoordinator(self)
+        self._thumbnail_coordinator = ThumbnailCoordinator(self)
         self._load_gen_by_session: dict[str, int] = {}
         self._thumb_gen_by_session: dict[str, int] = {}
         self._render_gen_by_session: dict[str, int] = {}
         self._stale_index_gen_by_session: dict[str, int] = {}
         self._session_ui_state: dict[str, SessionUIState] = {}
         self._desired_scroll_page: dict[str, int] = {}
         self._open_priority_page_by_session: dict[str, int] = {}
         self._background_loading_started_by_session: dict[str, bool] = {}
         self._render_batch_pending_by_session: dict[str, bool] = {}
         self._page_sizes_by_session: dict[str, list[tuple[float, float]]] = {}
         self._page_render_quality_by_session: dict[str, dict[str, dict[int, str]]] = {}
         self._render_revision_by_session: dict[str, int] = {}
         self._render_cache: OrderedDict[tuple[str, str, int, int, str, int], tuple[QPixmap, int]] = OrderedDict()
         self._render_cache_total_bytes = 0
+        # R4.2: single-entry cache of the full-doc worker snapshot bytes, keyed by
+        # (active_session_id, render_revision). See capture_worker_snapshot_bytes().
+        self._worker_snapshot_cache: tuple[str, int, bytes] | None = None
         self._fullscreen_session_snapshots: dict[str, FullscreenSessionSnapshot] = {}
         self._global_mode = self._normalize_mode(getattr(self.view, "current_mode", "browse"))
         self._signals_connected = False
         self._activated = False
 
     @property
     def is_active(self) -> bool:
         return self._activated
 
     def activate(self) -> None:
         if self._activated:
             return
         self._print_coordinator.connect_bridge()
         if self._optimize_worker_bridge is None:
             self._optimize_worker_bridge = _OptimizeWorkerBridge(self.view)
             self._optimize_worker_bridge.succeeded.connect(self._on_optimize_copy_succeeded)
             self._optimize_worker_bridge.failed.connect(self._on_optimize_copy_failed)
             self._optimize_worker_bridge.thread_finished.connect(self._on_optimize_thread_finished)
         self._ocr_coordinator.connect_bridge()
         self._search_coordinator.connect_bridge()
+        self._thumbnail_coordinator.connect_bridge()
         if not self._signals_connected:
             self._connect_signals()
             self._signals_connected = True
         self._activated = True
         self._refresh_ocr_availability()
 
     def _refresh_ocr_availability(self) -> None:
         updater = getattr(self.view, "update_ocr_availability", None)
         if not callable(updater):
             return
         tool = getattr(getattr(self.model, "tools", None), "ocr", None)
         if tool is None:
             updater(False, "OCR ?????")
             return
         try:
             info = tool.availability()
         except (ImportError, RuntimeError, AttributeError) as exc:
             logger.warning("OCR availability probe failed: %s", exc)
             updater(False, str(exc))
             return
         if info.available:
             updater(True, "")
         else:
             parts = [p for p in (info.reason, info.install_hint) if p]
             updater(False, "\n".join(parts) or "OCR ?????")
 
     def _connect_signals(self):
         # Existing connections
         self.view.sig_open_pdf.connect(self.open_pdf)
         self.view.sig_tab_changed.connect(self.on_tab_changed)
@@ -552,60 +558,93 @@ class PDFController:
         if self._load_gen_by_session.get(session_id) != gen:
             return
         self.view.restore_viewport_anchor(anchor)
 
     def _schedule_restore_viewport_anchor(self, session_id: str, gen: int, anchor: ViewportAnchor | None) -> None:
         if anchor is None:
             return
         QTimer.singleShot(0, lambda sid=session_id, g=gen, a=anchor: self._restore_viewport_anchor_if_current(sid, g, a))
         QTimer.singleShot(180, lambda sid=session_id, g=gen, a=anchor: self._restore_viewport_anchor_if_current(sid, g, a))
 
     def _session_page_sizes(self, session_id: str) -> list[tuple[float, float]]:
         cached = self._page_sizes_by_session.get(session_id)
         if cached and self.model.doc and len(cached) == len(self.model.doc):
             return cached
         if not self.model.doc:
             return []
         sizes = [(float(page.rect.width), float(page.rect.height)) for page in self.model.doc]
         self._page_sizes_by_session[session_id] = sizes
         return sizes
 
     def _render_revision(self, session_id: str) -> int:
         return self._render_revision_by_session.get(session_id, 0)
 
     def _bump_render_revision(self, session_id: str | None = None) -> None:
         sid = session_id or self.model.get_active_session_id()
         if not sid:
             return
         self._render_revision_by_session[sid] = self._render_revision_by_session.get(sid, 0) + 1
         self._page_render_quality_by_session[sid] = {}
         self._drop_render_cache_for_session(sid)
+        # Any render-visible mutation also changes doc.tobytes(); free the stale
+        # snapshot now (the revision-keyed read below would miss it anyway).
+        self._invalidate_worker_snapshot_cache()
+
+    def capture_worker_snapshot_bytes(self) -> bytes:
+        """Revision-keyed cache over ``model.capture_worker_snapshot_bytes()``.
+
+        The snapshot is a full ``doc.tobytes()``; search, OCR and print each capture it
+        independently on the GUI thread before ``QThread.start()``, so overlapping jobs
+        on an unedited doc re-serialize identical bytes. Cache on
+        ``(active_session_id, render_revision)`` ? the same token the page-render cache
+        trusts: any mutation that changes a rendered page bumps ``_render_revision`` via
+        ``_invalidate_active_render_state``. The one doc mutation that changes
+        ``doc.tobytes()`` WITHOUT a render bump is OCR invisible-text injection
+        (``apply_ocr_spans``, ``render_mode=3`` ? searchable but pixel-identical); the
+        OCR coordinator drops this cache after applying spans so a later search never
+        reads stale bytes. A session with no active id is never cached. The cached
+        ``bytes`` are immutable, so handing them to a worker thread is safe.
+        """
+        sid = self.model.get_active_session_id()
+        if not sid:
+            return self.model.capture_worker_snapshot_bytes()
+        revision = self._render_revision(sid)
+        cached = self._worker_snapshot_cache
+        if cached is not None and cached[0] == sid and cached[1] == revision:
+            return cached[2]
+        data = self.model.capture_worker_snapshot_bytes()
+        self._worker_snapshot_cache = (sid, revision, data)
+        return data
+
+    def _invalidate_worker_snapshot_cache(self) -> None:
+        """Drop the cached worker snapshot bytes (frees a full-document copy)."""
+        self._worker_snapshot_cache = None
 
     def _drop_render_cache_for_session(self, session_id: str) -> None:
         doomed = [key for key in self._render_cache.keys() if key[0] == session_id]
         for key in doomed:
             _, cost = self._render_cache.pop(key)
             self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - cost)
 
     def _render_device_pixel_ratio(self) -> float:
         """Physical-pixel ratio of the page view, so renders stay crisp on HiDPI /
         Windows-scaled displays instead of being upscaled (blurred) by the OS.
 
         Capped at 2.0: beyond that the extra pixels are imperceptible but the
         per-page rasterization cost (and render-cache memory) grows quadratically,
         which would slow page changes on 3x/4x displays.
         """
         try:
             gv = getattr(self.view, "graphics_view", None)
             if gv is not None and hasattr(gv, "devicePixelRatioF"):
                 dpr = float(gv.devicePixelRatioF())
                 if dpr > 0.0:
                     return min(dpr, 2.0)
         except Exception:
             pass
         return 1.0
 
     def _render_cache_key(
         self,
         session_id: str,
         profile: str,
         page_idx: int,
@@ -2178,60 +2217,65 @@ class PDFController:
         """Schedule an async thumbnail batch for affected pages.
 
         ``affected`` holds 1-based page numbers; ``None`` means a full rebuild.
         When the page count is unchanged and ``affected`` is known, only the
         affected rows are re-rendered (prior thumbnail icons are preserved).
         When the count changed, ``set_thumbnail_placeholders`` resets the widget
         item count first.
         """
         sid = self.model.get_active_session_id()
         if not sid or not self.model.doc:
             return
         n = len(self.model.doc)
         count_unchanged = affected and hasattr(self.view, "thumbnail_list") and self.view.thumbnail_list.count() == n
         gen = self._next_thumb_gen(sid)
         if count_unchanged:
             start = max(0, min(affected) - 2)
             end_limit = min(max(affected), n)
             QTimer.singleShot(0, lambda s=sid, g=gen, st=start, el=end_limit: self._schedule_thumbnail_batch(st, s, g, el))
         else:
             self.view.set_thumbnail_placeholders(n)
             start = max(0, min(affected) - 2) if affected else 0
             QTimer.singleShot(0, lambda s=sid, g=gen, st=start: self._schedule_thumbnail_batch(st, s, g))
 
     def _schedule_thumbnail_batch(self, start: int, session_id: str, gen: int, end_limit: int | None = None):
         if (
             self.model.get_active_session_id() != session_id
             or self._thumb_gen_by_session.get(session_id) != gen
             or not self.model.doc
         ):
             return
+        # R4.3: offload large, overlay-free rebuilds to a background worker (renders off
+        # snapshot bytes, never the live doc). Returns True only when it owns the range.
+        coordinator = getattr(self, "_thumbnail_coordinator", None)
+        if coordinator is not None and coordinator.try_start(start, session_id, gen, end_limit):
+            return
         n = end_limit if end_limit is not None else len(self.model.doc)
         end = min(start + THUMB_BATCH_SIZE, n)
         colorspace = self._fitz_colorspace_for_session(session_id)
         thumbs = [pixmap_to_qpixmap(self.model.get_thumbnail(i + 1, colorspace=colorspace)) for i in range(start, end)]
         self.view.update_thumbnail_batch(start, thumbs)
         if end < n:
             QTimer.singleShot(
                 THUMB_BATCH_INTERVAL_MS,
                 lambda e=end, sid=session_id, g=gen, el=end_limit: self._schedule_thumbnail_batch(e, sid, g, el),
             )
 
     def _schedule_index_batch(self, start: int, session_id: str, gen: int):
         if (
             self.model.get_active_session_id() != session_id
             or self._load_gen_by_session.get(session_id) != gen
             or not self.model.doc
         ):
             return
         n = len(self.model.doc)
         end = min(start + INDEX_BATCH_SIZE, n)
         for i in range(start, end):
             self.model.ensure_page_index_built(i + 1)
         if end < n:
             QTimer.singleShot(
                 INDEX_BATCH_INTERVAL_MS,
                 lambda e=end, sid=session_id, g=gen: self._schedule_index_batch(e, sid, g),
             )
 
     def _schedule_stale_index_drain(self) -> None:
         """
diff --git a/controller/print_coordinator.py b/controller/print_coordinator.py
index 8c38091..c7fd673 100644
--- a/controller/print_coordinator.py
+++ b/controller/print_coordinator.py
@@ -205,61 +205,61 @@ class PrintCoordinator:
                 status_message = PRINT_CLOSING_MESSAGE if self._print_close_pending else PRINT_STATUS_MESSAGE
             self._set_print_status_message(status_message)
             return
         self._set_print_status_message(None)
 
     def _update_print_close_pending_ui(self) -> None:
         if not self.has_active_job():
             return
         self._set_print_status_message(PRINT_CLOSING_MESSAGE)
         self._update_print_progress_dialog(PRINT_CLOSING_MESSAGE)
 
     def _enable_print_terminate_option(self) -> None:
         if self._print_progress_dialog is None:
             return
         if hasattr(self._print_progress_dialog, "setCancelButtonText"):
             self._print_progress_dialog.setCancelButtonText(PRINT_TERMINATE_BUTTON_TEXT)
 
     def _start_print_submission(self, options) -> None:
         self._c.activate()
         bridge = self._print_worker_bridge
         if bridge is None:
             raise RuntimeError("Print worker bridge is not initialized")
         session_id = self._c.model.get_active_session_id()
         work_dir = tempfile.mkdtemp(prefix="pdf_editor_print_")
         normalized_options = options.normalized() if hasattr(options, "normalized") else options
         if session_id and hasattr(normalized_options, "extra_options"):
             profile = self._c._resolve_session_profile(session_id, sync_view=True)
             extra = {**(getattr(normalized_options, "extra_options", {}) or {}), "render_colorspace": profile}
             normalized_options = dataclass_replace(normalized_options, extra_options=extra)
 
-        pdf_bytes = self._c.model.capture_worker_snapshot_bytes()
+        pdf_bytes = self._c.capture_worker_snapshot_bytes()
         request = PrintJobRequest(
             pdf_bytes=pdf_bytes,
             watermarks=self._c.model.get_print_watermarks(),
             options=normalized_options,
             job_id=str(uuid.uuid4()),
             work_dir=work_dir,
         )
         thread = QThread(self._c.view)
         worker = _PrintSubmissionWorker(request)
         worker.moveToThread(thread)
         thread.started.connect(worker.run)
         worker.progress.connect(bridge.forward_progress)
         worker.prepared.connect(bridge.forward_prepared)
         worker.failed.connect(bridge.forward_failed)
         worker.finished.connect(thread.quit)
         worker.finished.connect(worker.deleteLater)
         thread.finished.connect(bridge.notify_thread_finished)
         thread.finished.connect(thread.deleteLater)
         self._print_thread = thread
         self._print_worker = worker
         self._print_stalled = False
         thread.start()
 
     def _create_print_runner(self, job: PrintHelperJob) -> PrintSubprocessRunner:
         work_dir = str(Path(job.input_pdf_path).parent)
         return PrintSubprocessRunner(job, work_dir=work_dir, parent=self._c.view)
 
     def _on_print_job_prepared(self, job: PrintHelperJob) -> None:
         self._update_print_progress_dialog(PRINT_SUBMITTING_MESSAGE)
         runner = self._create_print_runner(job)
diff --git a/controller/search_coordinator.py b/controller/search_coordinator.py
index 69329f2..62b0683 100644
--- a/controller/search_coordinator.py
+++ b/controller/search_coordinator.py
@@ -119,61 +119,61 @@ class SearchCoordinator:
             self._search_worker_bridge.hits_found.connect(self._on_search_hits_found)
             self._search_worker_bridge.failed.connect(self._on_search_failed)
             self._search_worker_bridge.finished.connect(self._on_search_finished)
 
     def search_text(self, query: str):
         """????????????????GUI ?????????????
 
         ?????????????generation token ????????????
         worker ?????????? session ? search_state?
         """
         self.cancel()
         query = query or ""
         sid = self._c.model.get_active_session_id()
         self._search_accumulated_hits = []
         self._search_query = query
         self._search_session_id = sid
         self._search_finished = False
         if not query or not self._c.model.doc or not sid:
             self._c.view.display_search_results([])
             if sid:
                 self._c._get_ui_state(sid).search_state = {"query": query, "results": [], "index": -1}
             return
 
         gen = self._search_gen  # already bumped by cancel()
         thread = QThread()
         worker = _SearchWorker(
             self._c.model.tools.search,
             query,
             len(self._c.model.doc),
             gen,
-            self._c.model.capture_worker_snapshot_bytes(),
+            self._c.capture_worker_snapshot_bytes(),
         )
         worker.moveToThread(thread)
         thread.started.connect(worker.run)
         if self._search_worker_bridge is not None:
             worker.hits_found.connect(self._search_worker_bridge.forward_hits_found)
             worker.failed.connect(self._search_worker_bridge.forward_failed)
             worker.finished.connect(self._search_worker_bridge.forward_finished)
         worker.finished.connect(thread.quit)
         worker.finished.connect(worker.deleteLater)
         thread.finished.connect(thread.deleteLater)
         # Drop controller refs only once the THREAD has finished (not the worker):
         # releasing the Python QThread wrapper while the thread still runs lets GC
         # destroy the C++ object and hard-crash the process.
         thread.finished.connect(lambda t=thread: self._release_search_thread(t))
 
         self._search_thread = thread
         self._search_worker = worker
         thread.start()
 
     def _release_search_thread(self, thread) -> None:
         if self._search_thread is thread:
             self._search_thread = None
             self._search_worker = None
 
     def cancel(self) -> None:
         """Cancel any in-flight search and wait for its worker to stop.
 
         Must be called before any document mutation: the worker reads the live
         fitz document, which is not safe for concurrent read-during-mutation.
         Bumping ``_search_gen`` makes the handlers drop late queued signals.
diff --git a/controller/thumbnail_coordinator.py b/controller/thumbnail_coordinator.py
new file mode 100644
index 0000000..0e9e981
--- /dev/null
+++ b/controller/thumbnail_coordinator.py
@@ -0,0 +1,241 @@
+"""Hybrid async thumbnail coordinator (R4.3 performance deferral).
+
+Large, overlay-free thumbnail rebuilds are the one remaining synchronous rasterization
+on the Qt main thread (`_schedule_thumbnail_batch` rendered `model.get_thumbnail` inline
+inside a `QTimer` chain). This coordinator offloads them to a background `_ThumbnailWorker`
+that renders pages off the R4.2 worker-snapshot bytes ? never the live, non-thread-safe
+`fitz.Document` ? and marshals detached `QImage`s back through `_ThumbnailBridge` onto the
+GUI thread, which converts them to `QPixmap`s (a GUI-thread-only type) and paints them.
+
+Behavior-preserving by construction: the async path is taken ONLY when the session has no
+view overlays (watermarks compose at render time and are absent from the snapshot bytes,
+so a worker render would drop them) and the range is large enough to amortize the thread.
+Otherwise the caller falls back to the existing synchronous path, byte-for-byte unchanged.
+
+The thumbnail generation token (`controller._thumb_gen_by_session`) is the cancellation /
+staleness guard: a tab switch or a fresh invalidation bumps it, and stale batches that
+arrive afterwards are dropped before painting (a cancelled tab must not paint over a new
+one). The QThread lifecycle mirrors `SearchCoordinator`/`OcrCoordinator`: controller refs
+are dropped on `thread.finished` (never `worker.finished`), so the C++ thread object is
+never freed while still running.
+"""
+
+from __future__ import annotations
+
+import logging
+from typing import TYPE_CHECKING
+
+import fitz
+from PySide6.QtCore import QObject, QThread, Signal, Slot
+from PySide6.QtGui import QImage, QPixmap
+
+from model.color_profile import safe_to_fitz_colorspace
+from utils.helpers import pixmap_to_qimage
+
+if TYPE_CHECKING:
+    from controller.pdf_controller import PDFController
+
+logger = logging.getLogger(__name__)
+
+# Below this many pages a thread (spawn + snapshot capture) costs more than it saves;
+# small affected-page invalidations (rotate/move) stay on the cheap synchronous path.
+THUMB_ASYNC_MIN_PAGES = 24
+
+# Mirror the on-screen thumbnail render (model.get_thumbnail -> get_page_pixmap scale=0.2).
+THUMB_RENDER_SCALE = 0.2
+THUMB_WORKER_BATCH_SIZE = 10
+
+
+class _ThumbnailWorker(QObject):
+    """Renders thumbnail pages from snapshot bytes on a background thread.
+
+    Emits one ``batch_ready`` per chunk so the sidebar fills progressively. Every signal
+    carries the generation token so the GUI side can drop a cancelled tab's late batches.
+    """
+
+    batch_ready = Signal(int, int, list)  # gen, start_index, list[QImage]
+    finished = Signal(int)  # gen
+
+    def __init__(
+        self,
+        doc_bytes: bytes,
+        start: int,
+        end_n: int,
+        scale: float,
+        profile: str,
+        gen: int,
+        batch_size: int = THUMB_WORKER_BATCH_SIZE,
+    ) -> None:
+        super().__init__()
+        self._doc_bytes = doc_bytes
+        self._start = int(start)
+        self._end_n = int(end_n)
+        self._scale = float(scale)
+        self._profile = profile
+        self._gen = gen
+        self._batch_size = max(1, int(batch_size))
+        self._cancel_requested = False
+
+    def request_cancel(self) -> None:
+        self._cancel_requested = True
+
+    @Slot()
+    def run(self) -> None:
+        # Local import avoids a model<->controller import cycle at module load and keeps the
+        # central MediaBox clamp identical to the synchronous render path.
+        from model.pdf_model import _safe_render_scale  # noqa: PLC0415
+
+        try:
+            doc = fitz.open("pdf", self._doc_bytes) if self._doc_bytes else None
+            if doc is None:
+                return
+            try:
+                colorspace = safe_to_fitz_colorspace(self._profile)
+                i = self._start
+                while i < self._end_n:
+                    if self._cancel_requested:
+                        break
+                    images: list[QImage] = []
+                    j = i
+                    while j < min(i + self._batch_size, self._end_n):
+                        if self._cancel_requested:
+                            break
+                        page = doc[j]
+                        scale = _safe_render_scale(page, self._scale)
+                        matrix = fitz.Matrix(scale, scale)
+                        pix = page.get_pixmap(matrix=matrix, annots=True, colorspace=colorspace)
+                        images.append(pixmap_to_qimage(pix))
+                        j += 1
+                    if images and not self._cancel_requested:
+                        self.batch_ready.emit(self._gen, i, images)
+                    i = j
+            finally:
+                doc.close()
+        except Exception as exc:
+            logger.exception("Thumbnail worker failed: %s", exc)
+        finally:
+            self.finished.emit(self._gen)
+
+
+class _ThumbnailBridge(QObject):
+    """GUI-thread bridge: re-emits worker signals so handlers run on the GUI thread."""
+
+    batch_ready = Signal(int, int, list)
+    finished = Signal(int)
+
+    @Slot(int, int, list)
+    def forward_batch_ready(self, gen: int, start_index: int, images) -> None:
+        self.batch_ready.emit(gen, start_index, images)
+
+    @Slot(int)
+    def forward_finished(self, gen: int) -> None:
+        self.finished.emit(gen)
+
+
+class ThumbnailCoordinator:
+    """Owns the async-thumbnail runtime for one PDFController.
+
+    The controller holds exactly one of these (`self._thumbnail_coordinator`);
+    `_schedule_thumbnail_batch` asks `try_start(...)` to offload a large overlay-free
+    rebuild and only renders synchronously when it declines.
+    """
+
+    def __init__(self, controller: PDFController) -> None:
+        self._c = controller
+        self._thread: QThread | None = None
+        self._worker: _ThumbnailWorker | None = None
+        self._bridge: _ThumbnailBridge | None = None
+        self._session_id: str | None = None
+
+    def connect_bridge(self) -> None:
+        """Lazy-init the GUI-thread bridge and wire it to the handlers (from activate())."""
+        if self._bridge is None:
+            self._bridge = _ThumbnailBridge(self._c.view)
+            self._bridge.batch_ready.connect(self._on_batch_ready)
+            self._bridge.finished.connect(self._on_finished)
+
+    def _should_async(self, start: int, session_id: str, end_limit: int | None) -> bool:
+        """True iff this thumbnail range should be rendered off-thread.
+
+        Off-thread is only safe/correct when: the bridge is wired (post-activate); the
+        session is still active; the doc exists; the range is large enough to amortize the
+        thread; and the session has NO view overlays (watermarks are absent from the
+        snapshot bytes the worker renders, so a worker render would silently drop them).
+        """
+        if self._bridge is None:
+            return False
+        if not self._c.model.doc or self._c.model.get_active_session_id() != session_id:
+            return False
+        n = end_limit if end_limit is not None else len(self._c.model.doc)
+        if n - start < THUMB_ASYNC_MIN_PAGES:
+            return False
+        if self._c.get_watermarks():
+            return False
+        return True
+
+    def try_start(self, start: int, session_id: str, gen: int, end_limit: int | None) -> bool:
+        """Start an async render for ``[start, n)`` and return True, or False to fall back.
+
+        Returning True means the caller must NOT render synchronously ? this coordinator
+        owns the whole range from ``start`` onward.
+        """
+        if not self._should_async(start, session_id, end_limit):
+            return False
+
+        self.cancel()
+        n = end_limit if end_limit is not None else len(self._c.model.doc)
+        profile = self._c._resolve_session_profile(session_id)
+        doc_bytes = self._c.capture_worker_snapshot_bytes()
+
+        thread = QThread()
+        worker = _ThumbnailWorker(doc_bytes, start, n, THUMB_RENDER_SCALE, profile, gen)
+        worker.moveToThread(thread)
+        thread.started.connect(worker.run)
+        if self._bridge is not None:
+            worker.batch_ready.connect(self._bridge.forward_batch_ready)
+            worker.finished.connect(self._bridge.forward_finished)
+        worker.finished.connect(thread.quit)
+        worker.finished.connect(worker.deleteLater)
+        thread.finished.connect(thread.deleteLater)
+        # Drop refs only once the THREAD finished (not the worker): releasing the Python
+        # QThread wrapper while the thread still runs lets GC destroy the C++ object and
+        # hard-crash the process.
+        thread.finished.connect(lambda t=thread: self._release(t))
+
+        self._thread = thread
+        self._worker = worker
+        self._session_id = session_id
+        thread.start()
+        return True
+
+    def _release(self, thread) -> None:
+        if self._thread is thread:
+            self._thread = None
+            self._worker = None
+
+    def cancel(self) -> None:
+        """Cancel any in-flight thumbnail worker (quit() is thread-safe)."""
+        worker = self._worker
+        thread = self._thread
+        self._worker = None
+        self._thread = None
+        if worker is not None:
+            worker.request_cancel()
+        if thread is not None and thread.isRunning():
+            thread.quit()
+
+    @Slot(int, int, list)
+    def _on_batch_ready(self, gen: int, start_index: int, images) -> None:
+        sid = self._session_id
+        # Drop a cancelled tab's late batch (tab switch) or a superseded generation
+        # (a fresh invalidation bumped _thumb_gen_by_session) before it paints.
+        if sid is None or self._c.model.get_active_session_id() != sid:
+            return
+        if self._c._thumb_gen_by_session.get(sid) != gen:
+            return
+        pixmaps = [QPixmap.fromImage(img) for img in images]
+        self._c.view.update_thumbnail_batch(start_index, pixmaps)
+
+    @Slot(int)
+    def _on_finished(self, gen: int) -> None:
+        return None
diff --git a/docs/ARCHITECTURE.md b/docs/ARCHITECTURE.md
index dc9b4f1..642157e 100644
--- a/docs/ARCHITECTURE.md
+++ b/docs/ARCHITECTURE.md
@@ -82,62 +82,66 @@ Text index lifecycle:
 ### 2.2 Commands (`model/edit_commands.py`)
 
 Command classes define history boundaries:
 - `EditTextCommand` for existing text edits.
 - `AddTextboxCommand` for atomic add-text insertion.
 - `SnapshotCommand` for document-level structural operations.
 - `CommandManager` for undo/redo stacks.
 
 `EditTextCommand` now carries an `EditTextResult` outcome (`success`, `no_change`, `target_block_not_found`, `target_span_not_found`). When execution does not succeed, `CommandManager.execute()` / redo skip undo-stack recording for that command instead of creating a no-op history entry.
 `AddTextboxCommand` stores strict before-page snapshots, captures after-page snapshots on first execute, and restores only the target page on undo/redo.
 
 Undo-stack memory budget: in addition to the count cap (`MAX_UNDO_STACK_SIZE = 100`), `CommandManager` enforces `MAX_UNDO_STACK_BYTES = 512 MiB` over the sum of each command's `_byte_size()` (snapshot payload bytes; base `EditCommand` reports 0). `_trim_undo_stack_if_needed()` evicts oldest commands first and decrements `_saved_stack_size` per eviction (clamped at 0) so `has_pending_changes()` stays correct. After every push (execute/record/redo), `_dedup_top_snapshot_pair()` shares a single `bytes` object between two adjacent `SnapshotCommand`s whose `after`/`before` boundary snapshots are equal ? safe because `bytes` is immutable and `_restore_doc_from_snapshot` copies on `fitz.open("pdf", ...)`.
 
 ### 2.3 Controller (`controller/pdf_controller.py`)
 
 Controller is the only mutation coordinator between View and Model. It normalizes mode transitions, creates/executes commands, controls refresh scopes, and preserves per-session UI state.
 Document-tab refresh also synchronizes the active session's Save As suggestion into the view, so the view-owned `??PDF` dialog opens with the current tab's path/name instead of a blank or stale filename.
 
 Mode registry includes `browse`, `edit_text`, `add_text`, `rect`, `highlight`, and `add_annotation`.
 
 Controller activation is now explicit. `PDFController.__init__()` keeps startup cheap, while `PDFController.activate()` performs view-signal wiring, print subsystem setup, and startup sync such as text-target granularity alignment. This keeps the no-document startup shell decoupled from full controller behavior until the UI is ready.
 
 For performance on large PDFs, controller schedules heavy work in small batches (thumbnail rasterization, visible-page rendering, and text indexing). Continuous mode now uses a placeholder-first pipeline: the view allocates full-document scene geometry immediately from lightweight placeholders, then the controller progressively renders only the viewport window (plus a small prefetch margin) so the UI stays interactive even on 1000+ page PDFs. Open-time priority is now explicit: the initial visible page is allowed to reach high quality before background thumbnail batches and sidebar scans start, with a short fallback timer so background work still resumes if that high-quality upgrade never arrives. After structural operations or snapshot restore, controller also drains stale page indices in the background (`_schedule_stale_index_drain`), while the active/visible pages remain immediately usable via the model's `ensure_page_index_built(...)` contract.
 Search requests now use a private snapshot byte buffer captured on the GUI thread before the worker starts, so background search never reads the live `fitz.Document`. Completed searches store their accumulated hits back into `SessionUIState.search_state`, which lets tab switches restore finished result lists per tab; `_cancel_search()` only clears search state when it aborts an in-flight partial search. The async-search runtime ? the `_SearchWorker`/`_SearchBridge` QObjects plus the thread/worker/bridge/generation/session state and the per-page hit/finish/fail slots ? lives in [`controller/search_coordinator.py`](../controller/search_coordinator.py) as `SearchCoordinator` (R3.2). `PDFController` holds one coordinator and keeps thin `search_text`/`_cancel_search` delegates (the latter still called by 13 pre-mutation sites); `_SearchWorker`/`_SearchBridge` are re-exported from `pdf_controller` for backward compatibility. The coordinator preserves the exact QThread lifecycle (release bound to `thread.finished`, never `worker.finished`), the two-hop `worker?bridge?coordinator` wiring, and the `_search_gen` token that drops late queued signals from a cancelled search.
 
 The background-OCR runtime is extracted the same way into [`controller/ocr_coordinator.py`](../controller/ocr_coordinator.py) as `OcrCoordinator` (R3.2): the `_OcrWorker`/`_OcrBridge` QObjects plus the OCR thread/worker/bridge/`_ocr_gen`/`_ocr_session_id`/progress-dialog state and the page-done/progress/status/failure/thread-finished slots. `PDFController` holds one coordinator and keeps thin `start_ocr`/`cancel_ocr` delegates; `_OcrWorker`/`_OcrBridge` are re-exported from `pdf_controller`. The coordinator preserves the `_ocr_gen` cancellation token, the per-page **session guard** (`_on_ocr_page_done` drops spans whose `_ocr_session_id` no longer matches the active session, so recognized text never lands in the wrong document after a tab switch), the GUI-thread `model.apply_ocr_spans` sequencing, and the `QProgressDialog` parenting/cleanup. `_refresh_ocr_availability` (a one-shot UI-availability probe, not worker runtime) intentionally **stays on `PDFController`**.
 
 The print pipeline is the third and largest async coordinator: [`controller/print_coordinator.py`](../controller/print_coordinator.py) `PrintCoordinator` (R3.2) owns the `_PrintSubmissionWorker`/`_PrintWorkerBridge` QObjects, the `PrintJobRequest` payload, the `PrintDispatcher`, the `PrintSubprocessRunner` lifecycle, the progress dialog, and the stall/terminate state machine (`_print_stalled`/`_print_close_pending`). `PDFController` holds one coordinator and keeps thin `print_document` + `_has_active_print_submission` delegates; the model-coupled `_render_print_preview_image` (preview callback) and the app-lifecycle hooks (`handle_app_close` ? `coordinator.begin_close_pending()`, `_fullscreen_is_blocked`) stay on the controller, and `_PrintSubmissionWorker`/`_PrintWorkerBridge`/`PrintJobRequest` are re-exported from `pdf_controller`. The coordinator preserves verbatim: the GUI-thread `capture_worker_snapshot_bytes()` handoff before `QThread.start()` (name unchanged ? the R5.1 disk-leak/encryption fix is a separate deferred commit), the `worker?bridge?coordinator` wiring, the `thread.finished`-bound release, the `PrintSubprocessRunner` stall/terminate transitions and `work_dir` cleanup, the close-during-print message suppression (view closes only once idle), and the view-parented progress dialog.
 Print submissions also snapshot the active document on the GUI thread before the helper worker starts. The helper worker writes those bytes into its temp `input.pdf`, and watermark overlays are intentionally suppressed for `purpose == "print"` so the helper subprocess remains the single print-stamp path.
 
+Worker snapshot-bytes cache (R4.2): the full-doc `model.capture_worker_snapshot_bytes()` (`doc.tobytes(...)`) is captured independently by the search, OCR and print coordinators on the GUI thread before their worker threads start. The controller wraps it in a single-entry cache (`PDFController.capture_worker_snapshot_bytes`, keyed by `(active_session_id, render_revision)`), so overlapping jobs on an unedited document reuse one serialization; the three coordinators call the controller method, not the model. The cache key reuses the page-render invalidation token (`render_revision`), and `_bump_render_revision` drops the cache. The one doc mutation that is render-invisible but worker-visible is OCR's `apply_ocr_spans` (invisible `render_mode=3` text ? searchable but pixel-identical, so no render bump), so `ocr_coordinator._on_ocr_page_done` explicitly calls `_invalidate_worker_snapshot_cache()` after applying spans. Any future render-invisible/worker-visible mutation must do likewise.
+
 Thumbnail refresh is asynchronous via `_invalidate_thumbnails(affected)`. When the page count changed (insert/delete), it calls `view.set_thumbnail_placeholders(len(doc))` to resize the widget first, then schedules a full batch from the earliest affected page. When the page count is unchanged (rotate/straighten/text move), it skips the placeholder reset (preserving existing thumbnail icons) and schedules a bounded batch covering only the affected rows ? rotating 1 page of a 2000-page doc re-rasters 1 page, not 2000. Thumbnail batches use a dedicated `_thumb_gen_by_session` counter so invalidation does not cancel unrelated background loading or viewport-anchor restoration (which rely on `_load_gen_by_session`). `_next_load_gen` bumps both counters, but `_invalidate_thumbnails` bumps only the thumb counter. Cross-page text moves invalidate thumbnails for both source and destination pages on success and rollback. The old synchronous `_update_thumbnails` method has been deleted.
 
+Hybrid async thumbnails (R4.3): `_schedule_thumbnail_batch` first asks [`controller/thumbnail_coordinator.py`](../controller/thumbnail_coordinator.py) `ThumbnailCoordinator.try_start(...)` to offload the rebuild to a background `_ThumbnailWorker` (mirrors `SearchCoordinator`/`OcrCoordinator`: `worker?bridge?handler` wiring, refs dropped on `thread.finished`). The worker renders pages off the R4.2 worker-snapshot bytes (its own `fitz` handle ? never the live, non-thread-safe document) and marshals detached `QImage`s back through `_ThumbnailBridge` to the GUI thread, which converts them to `QPixmap`s (a GUI-thread-only type) and paints. `try_start` returns False ? and the caller renders synchronously, byte-for-byte unchanged ? unless the rebuild is large (`? THUMB_ASYNC_MIN_PAGES`) AND the session has no view overlays: watermarks compose at render time (`needs_page_overlay(..., "view")`) and are absent from the snapshot bytes, so a worker render would silently drop them (`_should_async` gates on `get_watermarks()`). The `_thumb_gen_by_session` token is the staleness guard: `_on_batch_ready` drops a batch whose generation no longer matches (a cancelled tab must not paint over a freshly-loaded one).
+
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
 - `??` commits current inline edit.
diff --git a/docs/PITFALLS.md b/docs/PITFALLS.md
index 221c62f..c6b48e4 100644
--- a/docs/PITFALLS.md
+++ b/docs/PITFALLS.md
@@ -1210,30 +1210,65 @@
 **Fix:** For real shadows use a `QGraphicsDropShadowEffect` in code (`PDFView._apply_chrome_shadow`), applied to a container that does **not** hold the heavy `QGraphicsView` (avoids render-path interaction). Re-apply only its `setColor(...)` on theme switch (the hue is theme-dependent); guard with `isinstance(..., QGraphicsDropShadowEffect)` so the effect is created once, not leaked per switch. For "smooth feedback", differentiate `:hover` / `:pressed` / `:focus` as distinct *static* states instead.
 **File:** `view/pdf_view.py` (`_apply_chrome_shadow`), `view/theme.py` (`build_qss`)
 
 ## QColor() cannot parse `rgba(r,g,b,a)` float-alpha strings
 **Area:** `view/theme.py` ? `_parse_qcolor`
 **Symptom:** Feeding an interaction/shadow token like `rgba(40,28,72,0.18)` straight into `QColor(str)` yields an **invalid** colour (`isValid() == False`), so the drop shadow renders as nothing.
 **Cause:** `QColor`'s string constructor accepts `#rrggbb`, `#aarrggbb`, and named colours, but not the CSS `rgba(...)` functional form with a 0?1 float alpha (those tokens were authored for CSS in `colors.css`).
 **Fix:** `_parse_qcolor` detects the `rgba(...)` form, splits the four components, and scales the float alpha to 0?255 (`int(round(a*255))`); hex/named values fall through to `QColor(str)`, with a final opaque-ish black fallback for unparseable input.
 **File:** `view/theme.py`
 
 ## Focus rings must be colour-only to avoid layout shift
 **Area:** `view/theme.py` ? `build_qss`
 **Symptom:** Adding a border on `:focus` to a control that has no base border makes the content jump by the border width each time it gains/loses focus.
 **Cause:** A QSS border participates in box metrics; introducing it on `:focus` changes the widget's content rect.
 **Fix:** Give the control a base `1px` border at rest and only **recolour** it to `accent` on `:focus` (inputs/combos/buttons already carry a 1px line border). Skipped focus rings on `QToolButton` (no base border) to avoid perturbing the measured ribbon width used by the adaptive toolbar.
 **File:** `view/theme.py`
 
 ## Free-function extraction silently bypasses method monkeypatching
 **Area:** model/pdf_text_edit.py, model/pdf_object_ops.py (god-module decomposition seams)
 **Symptom:** After extracting a method `_foo` into a free function `_foo(model, ...)`, a test that does `monkeypatch.setattr(model, "_foo", ...)` and asserts the patch fired starts failing ? the patch never intercepts.
 **Cause:** The original inter-method call was `self._foo(...)` (a bound-method lookup that honours instance/class monkeypatching). A naive transform rewrites sibling calls to the *local* free function `_foo(model, ...)`, which resolves at module scope and never consults `model._foo` ? so the monkeypatch is invisible. `test_edit_text_helpers.test_prepush_growth_branch_does_not_raise_name_error` patches `_push_down_overlapping_text` exactly this way.
 **Fix:** Use a UNIFORM `self.` ? `model.` transform (every inter-method call dispatches through the PDFModel delegating wrapper), and keep a wrapper on PDFModel for *every* moved method the test net pokes ? not only the public verbs. Calls that were already bare module-level (e.g. `_classify_insert_path`, `_EditTextResolveResult(...)`) stay bare. Verify by grepping the test suite for `monkeypatch.setattr(... , "_<moved>"` and for `model._<moved>(` / direct `from model.pdf_model import _<moved>` before deciding move-vs-wrapper.
 **File:** `model/pdf_text_edit.py` (wrappers in `model/pdf_model.py`)
 
 ## Helper-class extraction: getattr(self,?) and staticmethods escape the self.?self._view transform
 **Area:** view/object_selection.py (R3.6 view seam); applies to any PDFView?manager extraction
 **Symptom:** After moving methods into a `Manager(self._view)` helper, methods return wrong results (e.g. `_delete_selected_object` returns False) or `AttributeError: 'int' object has no attribute '_ensure_?'`.
 **Cause:** A regex that rewrites `self.X ? self._view.X` only matches *attribute* syntax. It misses (a) `getattr(self, "X")` / `setattr` / `hasattr` ? the receiver `self` stays the manager but `X` lives on the view; and (b) a moved `@staticmethod` whose PDFView delegating wrapper, if generated as a normal `def f(self, ?)`, breaks unbound `PDFView._f(arg)` calls (first positional arg binds to `self`).
 **Fix:** (1) also rewrite `(get|set|has)attr(self,` ? `?(self._view,` (verify none name a moved method first). (2) Make the wrapper for a moved staticmethod a `@staticmethod` delegating to `Manager._f(...)`. (3) Use a UNIFORM `self.?self._view.` transform (route inter-method calls through the PDFView wrappers too) so view-level `monkeypatch.setattr(PDFView, "_method"/instance, ?)` in tests is honored ? a direct `self._method` manager call silently bypasses it (same lesson as the R3.5 `_push_down_overlapping_text` monkeypatch).
 **File:** `view/object_selection.py` (wrappers in `view/pdf_view.py`)
+
+## Undo byte-budget must dedup by content, not id()
+**Area:** model/edit_commands.py ? `CommandManager._unique_byte_total` / `_dedup_top_snapshot_pair` / `_trim_undo_stack_if_needed`
+**Symptom:** Undo history is evicted earlier than the 512 MiB budget should allow, even though the *distinct* snapshot bytes are well under budget ? a correctness-looking "memory pressure" that silently shortens undo depth.
+**Cause:** `_dedup_top_snapshot_pair` only aliases the **top two** commands' boundary bytes at push time. Byte-identical snapshots that are *non-adjacent* (e.g. a fresh `_capture_doc_snapshot()` that matches an earlier document state) remain distinct `bytes` objects. The budget accountant `_unique_byte_total` deduped by `id()`, so those distinct-but-identical objects were summed twice, inflating the figure past the cap and triggering eviction.
+**Fix:** Dedup `_unique_byte_total` by **content** (`seen: set[bytes]`, membership-test the chunk itself). `bytes` are hashable and CPython caches the hash on the object, so it stays amortized-cheap even though `_trim_undo_stack_if_needed` recomputes the total inside its eviction `while` loop. Exact and leak-free ? deliberately NOT a persistent `digest?bytes` intern map (that would keep evicted snapshots alive, since `bytes` aren't weak-referenceable). The hot-path adjacent aliasing in `_dedup_top_snapshot_pair` (real RAM sharing) is left intact.
+**File:** `model/edit_commands.py`
+
+## OCR invisible text changes doc.tobytes() without bumping render_revision
+**Area:** controller/pdf_controller.py (`capture_worker_snapshot_bytes` cache) + controller/ocr_coordinator.py (`_on_ocr_page_done`)
+**Symptom:** After the R4.2 worker snapshot-bytes cache landed, an OCR pass followed by a text search could miss the just-recognized text ? the search worker received a snapshot serialized *before* OCR injected its text.
+**Cause:** The snapshot cache keys on `(active_session_id, render_revision)`, reusing the page-render cache's invalidation token. That token is bumped (`_bump_render_revision` via `_invalidate_active_render_state`) only for mutations that change a *rendered page*. OCR's `apply_ocr_spans` inserts text with `render_mode=3` (invisible) ? it changes `doc.tobytes()` (and therefore text extraction / searchability) but the rendered pixels are identical, so no render-revision bump occurs. The cache key never changes, so a stale pre-OCR snapshot is served on the next capture. `render_mode=3` appears ONLY in `apply_ocr_spans` (grep-verified), so OCR is the unique invisible-content mutation that affects a worker (search text-extraction).
+**Fix:** `_on_ocr_page_done` calls `self._c._invalidate_worker_snapshot_cache()` immediately after `apply_ocr_spans`, dropping the cached bytes so the next capture re-serializes the post-OCR document. The render-visible mutation paths are already covered because `_bump_render_revision` also drops the cache. When adding any new doc mutation that is *render-invisible but worker-visible* (e.g. a future hidden-layer or metadata-driven search field), it must likewise invalidate the worker snapshot cache ? keying on `render_revision` alone is not sufficient for such paths.
+**File:** `controller/pdf_controller.py`, `controller/ocr_coordinator.py`
+
+## Thumbnail threading: render off snapshot bytes, never the live doc ? and watermarks vanish
+**Area:** controller/thumbnail_coordinator.py (R4.3 hybrid async thumbnails)
+**Symptom:** Two distinct hazards when moving thumbnail rasterization to a QThread: (1) a worker that renders `model.doc` directly races the GUI thread's mutations and hard-crashes (PyMuPDF documents are not thread-safe); (2) a worker that renders off `capture_worker_snapshot_bytes` produces thumbnails with NO watermarks on watermarked docs.
+**Cause:** (1) `render_page_pixmap` reads the live `fitz.Document`. (2) Watermarks are *overlays* composed at render time via `apply_page_overlay` for `purpose in {"view","snapshot"}` ? they are NOT baked into `doc.tobytes()`, so the snapshot bytes the worker opens have no watermark content. Annotations, by contrast, ARE in the bytes (rendered via `annots=True`), so they survive.
+**Fix:** The worker opens its OWN `fitz` handle over the snapshot bytes (thread-safe, no live-doc access) AND the async path is taken only when the session has no view overlays ? `_should_async` returns False when `controller.get_watermarks()` is non-empty, so watermarked sessions stay on the synchronous overlay-applying path. Keep the central `_safe_render_scale` clamp and `annots=True`/colorspace identical to the sync path so output is byte-identical.
+**File:** `controller/thumbnail_coordinator.py`
+
+## A test that builds a QPixmap needs the `qapp` fixture or it hangs
+**Area:** test_scripts (any Qt-touching test that constructs QPixmap/QImage?QPixmap off a fixture)
+**Symptom:** A pytest module passes its first N tests, then *hangs* (no crash, no failure) on the first test that calls `QPixmap.fromImage(...)` / `pixmap_to_qpixmap(...)`; in isolation that same test passes in <1s.
+**Cause:** `QPixmap` requires a live `QGuiApplication`. Without the `qapp` fixture, the first QPixmap construction blocks on Windows. Tests that only build `QImage` (e.g. a worker's `pixmap_to_qimage`) or exercise pure logic don't need `qapp`, which is why the earlier tests pass and masks the missing fixture.
+**Fix:** Add the `qapp` fixture parameter to every test that (even indirectly) constructs a `QPixmap`. For genuinely cross-thread render tests, prefer verifying the worker synchronously (`worker.run()` emitting `QImage`) plus deterministic GUI-marshalling tests ? a live QThread render test reproduces the suite's known Qt/COM event-loop instability (passes alone, hangs interleaved).
+**File:** `test_scripts/test_thumbnail_coordinator.py`
+
+## Overlay raster caching: only watermarks are overlays, and the cache key must capture base content (R4.1 design-note)
+**Area:** model/tools/manager.py (`render_page_pixmap` overlay branch), model/tools/watermark_tool.py, controller `_render_revision`/`_render_cache`
+**Symptom:** A planned per-tool-revision overlay raster cache, keyed on `(session,page,scale,dpr,wm_revision,annot_revision)`, would (a) do nothing for annotations and (b) render stale text under a watermark after an edit.
+**Cause:** Two wrong premises. (1) Only `WatermarkTool` overrides `needs_page_overlay` (true for `purpose="view"`); `AnnotationTool` uses the base default `False` ? annotations are *baked* into the doc and rendered by `get_pixmap(annots=True)`, NOT composited as overlays, so an `annot_revision` counter is meaningless for the overlay path. (2) The overlay branch composites `insert_pdf(base page) ? draw watermark ? get_pixmap`, so the raster includes the page's text/objects; a key that tracks only watermark state is incomplete and serves stale composites when base content changes. The only *complete* "render changed" signal is the controller's whole-session `_render_revision` (bumped at the ~25 `_invalidate_active_render_state` sites); model-side counters (`edit_count`, `rebuild_page`) are incomplete (miss rotation/annotations/watermarks).
+**Fix:** Deferred (R4.1). Any future overlay cache must key on a *complete* invalidation signal. Keying on `_render_revision` is correct but redundant with the existing `_render_cache` (no within-revision win). A real cross-edit win needs *per-page* content-revision tracking wired across all ~25 invalidation sites (high stale-render risk) or a separate-canvas composite (must replicate page rotation + MediaBox origin + session colorspace sRGB/gray/CMYK, with no watermark pixel-parity gate). Treat overlay-vs-baked and key-completeness as the first questions for any render-cache work.
+**File:** `plans/refactor-R4-performance-deferrals.md` (R4.1 STATUS block)
diff --git a/model/edit_commands.py b/model/edit_commands.py
index 8f07553..8393e49 100644
--- a/model/edit_commands.py
+++ b/model/edit_commands.py
@@ -613,67 +613,73 @@ class CommandManager:
             logger.debug(
                 "CommandManager: evicted %s oldest undo commands to enforce max=%s",
                 overflow,
                 self.MAX_UNDO_STACK_SIZE,
             )
 
         total_bytes = self._unique_byte_total()
         if total_bytes <= self.MAX_UNDO_STACK_BYTES:
             return
         evicted = 0
         while len(self._undo_stack) > 1 and total_bytes > self.MAX_UNDO_STACK_BYTES:
             self._undo_stack.pop(0)
             evicted += 1
             total_bytes = self._unique_byte_total()
         if evicted:
             self._saved_stack_size = max(0, self._saved_stack_size - evicted)
             logger.debug(
                 "CommandManager: evicted %s oldest undo commands to enforce byte budget=%s (remaining=%s bytes)",
                 evicted,
                 self.MAX_UNDO_STACK_BYTES,
                 total_bytes,
             )
         if total_bytes > self.MAX_UNDO_STACK_BYTES:
             logger.warning(
                 "CommandManager: newest command (%s bytes) exceeds byte budget %s ? keeping it",
                 total_bytes,
                 self.MAX_UNDO_STACK_BYTES,
             )
 
     def _unique_byte_total(self) -> int:
-        seen: set[int] = set()
+        # Dedup by CONTENT, not id(): adjacent boundary pairs are aliased to one
+        # object by _dedup_top_snapshot_pair, but byte-identical snapshots that are
+        # *non-adjacent* (e.g. a fresh capture matching an earlier doc state) remain
+        # distinct objects. An id()-keyed sum double-counts those against the budget
+        # and evicts prematurely. bytes are hashable (CPython caches the hash on the
+        # object), so a content-keyed set is exact and amortized-cheap across the
+        # repeated calls in the trim loop.
+        seen: set[bytes] = set()
         total = 0
         for cmd in self._undo_stack:
             for chunk in cmd._snapshot_chunks():
-                chunk_id = id(chunk)
-                if chunk_id not in seen:
-                    seen.add(chunk_id)
+                if chunk not in seen:
+                    seen.add(chunk)
                     total += len(chunk)
         return total
 
     def can_undo(self) -> bool:
         """??????????? UI ??/?? Undo ????"""
         return bool(self._undo_stack)
 
     def can_redo(self) -> bool:
         """??????????? UI ??/?? Redo ????"""
         return bool(self._redo_stack)
 
     @property
     def undo_count(self) -> int:
         """undo ?????????"""
         return len(self._undo_stack)
 
     @property
     def redo_count(self) -> int:
         """redo ?????????"""
         return len(self._redo_stack)
 
     def has_pending_changes(self) -> bool:
         """
         ???????????????
 
         [??] ?? _saved_stack_size ??????????????
           - ?????????? ? True
           - ???? undo????????????? True
           - ???? / clear() ? ? False
 
diff --git a/model/pdf_optimizer.py b/model/pdf_optimizer.py
index c3bf470..6971c79 100644
--- a/model/pdf_optimizer.py
+++ b/model/pdf_optimizer.py
@@ -199,61 +199,61 @@ def _rewrite_source_image_task(task: tuple[int, float, dict[str, int | bool]]) -
         image_info = _IMAGE_REWRITE_WORKER_DOC.extract_image(int(xref))
         image_bytes = image_info.get("image")
         rewritten = _transcode_image_payload(image_bytes, float(max_dpi), settings)
         return int(xref), rewritten, None
     except Exception as exc:
         return int(xref), None, str(exc)
 
 
 def _rewrite_extracted_image_task(
     task: tuple[int, int, float, bytes, dict[str, int | bool]]
 ) -> tuple[int, int, bytes | None, str | None]:
     xref, page_index, max_dpi, image_bytes, settings = task
     try:
         rewritten = _transcode_image_payload(image_bytes, float(max_dpi), settings)
         return int(xref), int(page_index), rewritten, None
     except Exception as exc:
         return int(xref), int(page_index), None, str(exc)
 
 
 def preset_optimize_options(preset: str) -> PdfOptimizeOptions:
     normalized = (preset or "").strip()
     if normalized == "??":
         return PdfOptimizeOptions(
             preset="??",
             image_dpi_target=220,
             image_dpi_threshold=300,
             image_jpeg_quality=78,
             remove_metadata=False,
             remove_xml_metadata=False,
             garbage_level=2,
-            use_object_streams=False,
+            use_object_streams=True,
             linearize=False,
             compression_effort=3,
         )
     if normalized == "????":
         return PdfOptimizeOptions(
             preset="????",
             image_dpi_target=110,
             image_dpi_threshold=165,
             image_jpeg_quality=42,
             remove_metadata=True,
             remove_xml_metadata=True,
             garbage_level=4,
             use_object_streams=False,
             linearize=True,
             compression_effort=9,
         )
     return PdfOptimizeOptions()
 
 
 def normalize_optimize_options(options: PdfOptimizeOptions) -> PdfOptimizeOptions:
     if options.linearize and options.use_object_streams:
         return replace(options, use_object_streams=False)
     return options
 
 
 def is_large_optimize_job(original_bytes: int, image_usage: dict[int, dict[str, float | int]]) -> bool:
     return int(original_bytes) >= _LARGE_OPTIMIZE_BYTES or len(image_usage) >= _LARGE_OPTIMIZE_IMAGE_COUNT
 
 
 def optimize_capabilities() -> dict[str, bool]:
diff --git a/plans/refactor-R4-performance-deferrals.md b/plans/refactor-R4-performance-deferrals.md
index cbb0bde..6774cda 100644
--- a/plans/refactor-R4-performance-deferrals.md
+++ b/plans/refactor-R4-performance-deferrals.md
@@ -1,48 +1,87 @@
 # Phase R4 ? Performance Deferrals
 
 **Status:** Ready (after R3 coordinators land). **Fusion:** 3-model for cache/threading;
 2-model for the mechanical items. **Why here:** these are real but each is narrower than a naive
 reading suggests, and two are partially mitigated by existing infra. The snapshot-bytes-cache step
 is sequenced **after** R3's coordinator extraction (it touches the same controller call sites).
 (Census: performance lens; critique HAZARD 5.)
 
 > **Implicit risks:** the overlay revision cache can serve **stale composites** if any mutation
 > path forgets to bump its counter (~25 invalidation sites) ? a correctness regression that *looks
 > like success* in tests that don't assert overlay content. The snapshot cache key spans layers
 > (revision on controller, bytes produced by model). Moving thumbnails to a `QThread` introduces
 > stale-emission risk.
 
 ---
 
 ## R4.1 ? Overlay raster cache with per-tool revision counters (3-model)
 
+> **STATUS: EVALUATED ? DEFERRED (2026-06-17).** A source audit + 3-way design review found
+> every viable variant is either incorrect, high-risk-without-a-pixel-gate, or a non-win with
+> architectural friction. R4 ships at **4/5** (R4.5/R4.4/R4.2/R4.3 landed). Full rationale below;
+> see also `refactor-state.md` turn 28 and the PITFALLS design-note.
+>
+> **Key audit findings (vs the original spec):**
+> 1. **Watermark-only.** Only `WatermarkTool` overrides `needs_page_overlay` (true for
+>    `purpose="view"`). `AnnotationTool` uses the base default (`False`) ? annotations are *baked*
+>    into the doc and rendered via `get_pixmap(annots=True)`, NOT composited as overlays. So the
+>    spec's `annot_revision` counter is moot, and the entire win applies only to watermarked docs.
+> 2. **The literal spec key is incorrect (stale composites).** Keying on
+>    `(session,page,scale,dpr,wm_revision,annot_revision)` omits any *base-content* revision, yet the
+>    overlay branch does `insert_pdf(base page) ? draw watermark ? get_pixmap`, so the composite
+>    includes the page's text/objects. Editing text under a watermark changes the composite while
+>    leaving `wm_revision` untouched ? the cache would serve the old text under the watermark.
+> 3. **No model-owned complete invalidation signal.** `edit_count`/`rebuild_page` are incomplete
+>    (rotation, annotations, watermarks don't all route through them). The only complete
+>    "render changed" signal is the controller's whole-session `_render_revision`.
+> 4. **The safe (`render_revision`-keyed) cache is correct but a non-win.** It is redundant with the
+>    existing `_render_cache` (already keyed on `render_revision`), which prevents redundant overlay
+>    computation *within* a revision: page-view composites hit `_render_cache` and never reach the
+>    overlay branch; thumbnails render once into the widget; snapshots are on-demand. A new
+>    `render_revision`-keyed cache helps only under a QPixmap-cache eviction edge case, while
+>    requiring the controller's `render_revision` token be threaded into the model render API (layer
+>    smell) and roughly doubling composite memory.
+> 5. **Separate-canvas variant = high risk, no pixel gate.** Rendering the watermark on a transparent
+>    canvas and alpha-compositing over the base (skipping `insert_pdf`) must replicate page rotation,
+>    MediaBox origin, and session colorspace (sRGB/gray/CMYK) exactly, and accept anti-aliasing /
+>    overlap-blending differences ? silent visual regressions on rotated/CMYK/multi-watermark pages,
+>    with no automated pixel-parity coverage for watermark rendering (no-jump only guards the editor).
+>
+> **What the real win would require (and why it's not worth it):** cross-revision *per-page* reuse,
+> i.e. per-page base-content revision tracking wired across the ~25 `_invalidate_active_render_state`
+> sites (one miss = silent stale render) OR the separate-canvas rewrite. Disproportionate risk for a
+> watermark-only conditional gain on a path the existing multi-layer caches already keep efficient
+> within a revision. **Revisit only if** watermarked-doc scroll-after-edit latency becomes a measured,
+> reported bottleneck; the lowest-risk path then is the separate-canvas approach *plus* a new
+> watermark pixel-parity gate built first.
+
 - **Current state (not "no cache"):** the controller already caches the final composited QPixmap
   in `_render_cache` keyed by `_render_revision` (`pdf_controller.py:857`). The residual cost is
   the **cache-MISS** path: `render_page_pixmap` overlay branch (`manager.py:88-99`) does
   `fitz.open()+insert_pdf(single page)+apply_page_overlay+get_pixmap` on the Qt main thread; and
   `_bump_render_revision` (L810) drops the **whole session cache** via
   `_invalidate_active_render_state` (~25 mutation sites, L1833-3305). So one annotation on page 5
   re-runs the full overlay pipeline for watermarked pages 1-4. `WatermarkTool`/`AnnotationTool`
   have no revision counter; `ToolManager` is stateless.
 - **Fix:** add per-`(session,page)` revision counters on `WatermarkTool` and `AnnotationTool`
   (bumped in `add/remove/update_watermark` + annotation mutators), and a page-overlay raster cache
   on `ToolManager` keyed by `(session_id, page_num, scale, dpr, wm_revision, annot_revision)`.
   Invalidation: only the page whose overlay-owning tool bumped its counter is dropped ? decoupling
   overlay invalidation from the controller's whole-session `_render_revision` bump.
 - **Conditional:** win only exists when overlays exist; zero benefit on overlay-free docs.
 
 ## R4.2 ? Revision-keyed worker snapshot-bytes cache (3-model, AFTER R3 coordinators)
 
 - `capture_worker_snapshot_bytes` (`pdf_model.py:3200-3204`) does a full `doc.tobytes(...)` and is
   called independently by print (`:1657`), search (`:2557`), OCR (`:2690`). Search-then-OCR on an
   unedited doc serializes the same bytes twice.
 - **Fix:** a bytes cache keyed by `(active_session_id, render_revision)`. **Ownership is the bug
   surface** ? `_render_revision` lives on the controller, the bytes are produced by the model. The
   **controller** owns the cache (it knows the revision) and passes cached bytes into the (now R3-
   extracted) coordinator capture sites; invalidate on the same hook as `_bump_render_revision`.
 - **Conditional:** only helps overlapping search/OCR/print on an unedited doc; invalidated by any
   edit. **Sequence after R3.2** so the cache wires into the coordinators, not soon-to-move code.
 
 ## R4.3 ? Thumbnail rasterization ? QThread worker (3-model)
 
 - `_schedule_thumbnail_batch` (`pdf_controller.py:2904`) calls `model.get_thumbnail(...)`
diff --git a/refactor-state.md b/refactor-state.md
index f0f8f2e..633839a 100644
--- a/refactor-state.md
+++ b/refactor-state.md
@@ -43,61 +43,61 @@ state machine internals before its managers exist (`pdf_view.py:2899-4558`).
 | 20 skips | all OCR (surya/torch absent) ? environmental, not regressions | ? |
 | ruff total (E4/E7/E9+F, E501 unselected) | **238** (doc said 240); 28 in production layers, 210 in test/script | hygiene lens |
 | ruff auto-fixable | 18 (F541?12, F401?6) | hygiene lens |
 | God-module LOC | `pdf_view` 5497 / `pdf_model` 5166 / `pdf_controller` 3383 / `text_editing` 1809 / `text_block` 1043 | LOC scan |
 | Coverage tooling | **pytest-cov 7.1.0 in `.venv` (R0.5)**; floor: model 79.2% / controller 78.8% / view 76.6% (combined 78.0%) | R0.5 |
 
 **R0 freeze target:** `.venv` collects full suite; **?1355 passed / exactly the 20 OCR skips / 0 failed**, deterministic; a captured per-module coverage number as the floor.
 
 **R0 FROZEN (2026-06-15):** `.venv` declared the canonical regression interpreter ? canonical command
 `.venv\Scripts\python.exe -m pytest test_scripts/`. Result **1355 passed / 20 skipped / 0 failed**,
 deterministic over 2 full runs + heartbeat ?5. The 20 skips = OCR (surya/torch absent) **+ 2
 large-fixture-absent optimizer-integrity params** (the census machine had those fixtures, so its
 count was "20 OCR"; composition differs, count holds). Coverage floor recorded above. **1.27-skew
 triage (R0.4, the 3-model authority gate): all 3 surfaced failures were non-product** ? (A) `pypdf`
 test-dep missing in `.venv` ? installed + declared in `optional-requirements.txt`; (B) degenerate
 20pt-wide preview box hit PyMuPDF 1.27's `insert_htmlbox` overflow?blank (1.25 clipped) ? test rect
 widened to 60pt, **product overflow behavior flagged as a follow-up, not changed**; (C) stale
 `doc.name == ""` memory-backed proxy (1.27 names stream docs `"pdf"`). The `Windows fatal exception
 0x80040155` faulthandler dumps in offscreen runs are benign handled-COM noise (see PITFALLS).
 
 ---
 
 ## 2. Phase ledger
 
 | ID | Phase | Fusion mode | Playbook(s) | Status | Plan |
 |----|-------|-------------|-------------|--------|------|
 | **R0** | Baseline Freeze & Regression-Net Repair | 2-model (mech) + 3-model (interpreter-authority) | 4.5 | ? **done 2026-06-15** | [`plans/refactor-R0-baseline-freeze.md`](plans/refactor-R0-baseline-freeze.md) |
 | **R1** | Mechanical Hygiene (ruff + app-identity + packaging) | 2-model | 4.2 | ? **done 2026-06-15** | [`plans/refactor-R1-mechanical-hygiene.md`](plans/refactor-R1-mechanical-hygiene.md) |
 | **R2** | MVC Boundary Reconvergence (**guard-first**) | 2-model | 4.3 | ? **done 2026-06-15** | [`plans/refactor-R2-mvc-boundary.md`](plans/refactor-R2-mvc-boundary.md) |
 | **R3** | God-Module Decomposition | 3-model | 4.4 + 4.1 | ? **done 2026-06-17** (R3.1-R3.7 ?; R3.8a ? state migration; **R3.8b dispatcher DEFERRED per user** ? gate can't validate Qt event-routing; context+landmines documented) | [`plans/refactor-R3-god-module-decomposition.md`](plans/refactor-R3-god-module-decomposition.md) |
-| **R4** | Performance Deferrals | 3-model (cache/thread) + 2-model (digest/objstms) | 4.4 + 4.5 | ? not started | [`plans/refactor-R4-performance-deferrals.md`](plans/refactor-R4-performance-deferrals.md) |
+| **R4** | Performance Deferrals | 3-model (cache/thread) + 2-model (digest/objstms) | 4.4 + 4.5 | ? **done 2026-06-17** (4/5: R4.5 objstms ?, R4.4 undo-dedup ?, R4.2 snapshot-bytes cache ?, R4.3 async thumbnails ?; **R4.1 overlay raster cache EVALUATED ? DEFERRED** ? all variants incorrect/high-risk/non-win, see plan + turn 28) | [`plans/refactor-R4-performance-deferrals.md`](plans/refactor-R4-performance-deferrals.md) |
 | **R5** | Security & Supply-Chain Hardening | 3-model (leak/bundle) + 2-model (guard) | 4.6 + security-review | ? not started | [`plans/refactor-R5-security-supply-chain.md`](plans/refactor-R5-security-supply-chain.md) |
 | **R6** | Coverage Hardening (tail over decomposed seams) | 3-model | 4.5 | ? not started | [`plans/refactor-R6-coverage-tail.md`](plans/refactor-R6-coverage-tail.md) |
 
 ---
 
 ## 3. Cross-phase dependency hazards (the wiring that constrains ordering)
 
 1. **R0 ? everything.** No phase has a real regression net until R0 makes the *shipped* `.venv`
    stack collect + green + deterministic. Non-negotiable first.
 2. **R2 ? R3 (guard precedes decomposition).** R2's AST import-boundary guard must land
    *first within R2*; it locks the currently-true 0-Qt/0-cross-import invariant so R3's
    extractions cannot regress it silently.
 3. **R2/R3 ? encryption AST guard generalization.** The `self.doc.{save,tobytes}` guard
    (`test_xref_repair.py:324-368`) only walks `pdf_model.py`. It must be generalized to walk
    **all of model/** *before* `edit_text`/object-ops leave `pdf_model.py`, or it goes blind
    exactly when risk peaks (R3 step 3).
 4. **R3 ? R4 snapshot-cache.** R4's revision-keyed `capture_worker_snapshot_bytes` cache
    touches controller `:1657/:2557/:2690`; R3's coordinator extraction relocates those sites.
    The R4 cache step must follow R3's coordinators.
 5. **R3 ? R5 print path (shared regression pass).** R5's print-disk-leak fix
    (`pdf_controller.py:131-135` + `capture_worker_snapshot_bytes` `PDF_ENCRYPT_NONE`) and
    R3's `print_coordinator` extraction touch the same handoff ? coordinate one regression pass.
 6. **R5 quick-wins pulled forward into R2.** `pdf_renderer.py:84` `safe_render_scale` clamp
    (one call site) and `compose_merged_document`/`open_merge_source` `_guard_foreign_doc`
    routing are mechanical, verified, independent ? land them in R2 rather than holding them
    behind 3-model R5.
 
 ---
 
 ## 4. High-risk bar ? when a phase STEP upgrades 2-model ? 3-model
@@ -431,30 +431,127 @@ created. (Examples: icon-count fix, `app_identity` leaf, F401/F841 removal, E701
   lazy accessor. **UNIFORM transform** `self.X?self._view.X` + `(get|set|has)attr(self,"X")?self._view` (notably the
   `_selected_text_from_drag` copy-fallback guard). Source = 3 non-contiguous regions (1791; 3453-3729; 3763-3781) with
   `_zoom_relative`/`_start_text_edit_from_hit` interleaved as STAY. **DEFERRED finding** (flagged, NOT fixed ? keeps the
   move verbatim): text cleanup uses `if item.scene():` not `shiboken6.isValid()` like ObjectSelectionManager; harden in a
   follow-up. **R3.8 highest-risk attrs to migrate:** `_selected_text_rect_doc`/`_selected_text_cached` (read by non-text
   code). The R6.6-style playbook carried over with **ZERO debugging** ? contract + text/object GUI suites 101p GREEN
   first try. **pdf_view 5152?4894 LOC, ZERO test churn.** New `test_text_selection_extraction.py` RED?GREEN. Gates: full
   suite **1391p/20s** (clean first run), production ruff 0, codegraph re-indexed, **no-jump completion-gate before/after.**
   **Next:** R3.8 ? the LAST view artifact: refactor `_mouse_press/move/release` into a per-mode dispatcher delegating to
   the two managers + migrate the object/text interaction state into them (preserve the `current_mode` early-return
   ordering exactly).
 - **2026-06-17 (turn 24): R3.8a LANDED + R3.8b DEFERRED (user decision) ? R3 COMPLETE.** Full 3-model review
   (Gemini dual-lens + Codex) on the 3 mouse handlers (~1090 LOC, 8-mode convergence). Gemini first timed out on
   the 1100-line extract (documented large-input failure) ? retried with a compact structure-only prompt. **Both
   vendors independently SPLIT R3.8** into R3.8a (state-ownership) vs R3.8b (handler-ordering/Qt-event) and both
   concluded the **377-case pixel-parity + model gate STRUCTURALLY CANNOT validate R3.8b** (blind to Qt event
   routing: accept/ignore propagation, autopan QTimer, drag-vs-click thresholds, super().mouseMoveEvent fallthrough,
   overlapping-hit priority) ? needs pytest-qt interaction tests + manual QA. Surfaced this as a checkpoint; **user
   chose: R3.8a only, defer R3.8b, document context + Codex's landmines, /compact when R3 done.** **R3.8a (executed,
   gate-verified):** migrated all 43 interaction-state attrs (17 text + 26 object, incl. the 9 never-in-__init__
   `_object_resize_*`/`_selected_object_infos`/`_selected_object_page_idx`) out of `PDFView.__init__` into the two
   managers' `__init__`; PDFView keeps get/set `@property` forwarders for all 43 proxying via the lazy accessors
   (so `__new__` test doubles + pre-construction access work). Manager bodies `self._view._<attr>` ? `self._<attr>`
   (word-boundary exact) for migrated names only. Handlers byte-identical. One transform bug caught + fixed: the
   8-space init-line removal matched a 20-space handler substring (`str.replace` corruption) ? anchored removal with
   a leading `\n` + asserted exactly 34 lines removed. ZERO test churn. **R3.8b fully documented** in the plan
   (branch boundaries, Strangler-Fig/Boolean-consumption procedure, Codex's 10 landmines, the verification-gap test
   files). Gates: interaction GUI suites 130p, full suite **1391p/20s** (clean), production ruff 0, codegraph
   re-indexed, **no-jump completion-gate before/after.** **R3 COMPLETE** (R3.1-R3.7 + R3.8a; R3.8b deferred). **Next:**
   per user, `/compact`, then R4 (performance deferrals).
+- **2026-06-17 (turn 25): R4 BEGUN ? R4.5 LANDED (?? preset objstms flip, the lowest-risk R4 item).** Post-`/compact`,
+  re-indexed codegraph (3338?3762 nodes), froze the `.venv` baseline GREEN (**1391p/20s**), then started R4 with
+  the most-mechanical item (2-model class). **Census confirmed the scope was narrower than the original deferral
+  note claimed:** of the three presets, `??` already had `use_object_streams=True`, and `????` is structurally
+  blocked (`linearize=True` ? `normalize_optimize_options:250-252` strips objstms), so **only `??`
+  (`linearize=False`) was a genuine opportunity.** Flipped `use_object_streams=False ? True` in
+  `preset_optimize_options` (`pdf_optimizer.py:229`). **Red-Light First:** new
+  `test_pdf_optimize_workflow.py::test_fast_preset_enables_object_streams` proves the full chain (preset True ?
+  survives `normalize_optimize_options` ? reaches `fast_save_kwargs` as `use_objstms=1`), RED before the flip
+  (`assert False is True`) ? GREEN after. The two capability-gate tests (928/942) assert `use_object_streams is
+  False` for the *gated* dialog (preset ??/???? with `object_streams:False` capability) ? verified unaffected.
+  Gates: optimize-workflow + phase7-guard 41p/4s (the 4 skips = large-fixture-absent integrity params), production
+  ruff 0, full suite GREEN. **Next:** R4.4 (undo dedup coverage, 2-model) ? then the three 3-model concurrency
+  items: R4.2 (snapshot-bytes cache, now unblocked by R3 coordinators) ? R4.3 (thumbnail QThread, reuses R4.2) ?
+  R4.1 (overlay raster cache, highest invalidation risk).
+- **2026-06-17 (turn 25b): R4.4 LANDED (undo dedup coverage, 2-model).** `CommandManager._unique_byte_total`
+  (`edit_commands.py:642`) deduped the undo byte-budget accounting by `id()`. But `_dedup_top_snapshot_pair`
+  only aliases the **top two** commands at push time, so byte-identical snapshots that are *non-adjacent* (a
+  fresh `_capture_doc_snapshot()` matching an earlier doc state) stay distinct `bytes` objects and were summed
+  twice ? the 512 MiB cap tripped early ? undo history evicted prematurely. **Fix:** dedup by **content**
+  (`seen: set[bytes]`); CPython caches each bytes object's hash, so it's amortized-cheap across the recompute
+  loop in `_trim_undo_stack_if_needed`. Exact + leak-free ? deliberately NOT a persistent `digest?bytes` intern
+  map (would keep evicted snapshots alive; `bytes` aren't weak-referenceable). The hot-path adjacent RAM-sharing
+  in `_dedup_top_snapshot_pair` is untouched. **Red-Light First:** two new tests ? `test_non_adjacent_identical_bytes_counted_once`
+  (asserts exact unique total 300, was 400) + `test_non_adjacent_duplicate_does_not_prematurely_evict` (budget
+  350 fits unique 300 but not id-double-counted 400 ? was `undo_count=2`, now 3). Both RED before, GREEN after.
+  Gates: undo-budget 8p, production ruff 0, full suite GREEN. PITFALLS entry added ("Undo byte-budget must dedup
+  by content, not id()"). **Next:** the three 3-model concurrency items ? R4.2 (snapshot-bytes cache) ? R4.3
+  (thumbnail QThread) ? R4.1 (overlay raster cache).
+- **2026-06-17 (turn 26): R4.2 LANDED (worker snapshot-bytes cache, 3-model concurrency item).** Fusion
+  tooling was inconclusive this turn (both Gemini passes timed out at 180s even on a compact prompt ? the
+  documented hang; the codex-rescue agent returned only a forwarding meta-message, and SendMessage isn't in
+  this session's toolset) ? so per the manual ("fusion is advisory; authoritative gates = ruff + pytest +
+  no-jump") and the R1 precedent, the design lens was applied via **my own source-grounded verification**.
+  **The finding that de-risked AND re-risked the design:** keying the cache on the existing `render_revision`
+  token (the page-render cache's invalidation key) is sound for every *render-visible* mutation ? but
+  `grep render_mode=3` proved OCR's `apply_ocr_spans` is the UNIQUE *render-invisible, worker-visible* mutation
+  (injects invisible but searchable text; `_on_ocr_page_done` does NOT bump render_revision). A naive
+  `(sid, render_revision)` cache would serve pre-OCR bytes to a later search ? silently miss the OCR'd text
+  (regression vs the current always-fresh call). **Design:** controller `capture_worker_snapshot_bytes()`
+  single-entry cache keyed `(active_session_id, render_revision)`; `_invalidate_worker_snapshot_cache()` dropped
+  from BOTH `_bump_render_revision` (visible mutations + memory free) AND `ocr_coordinator._on_ocr_page_done`
+  after `apply_ocr_spans` (the invisible-text gap). The 3 coordinators (search/OCR/print) now call
+  `self._c.capture_worker_snapshot_bytes()` not the model. Threading-safe (capture is GUI-thread
+  pre-`thread.start()`; `bytes` immutable). Encryption AST guard undisturbed (cache delegates to the model; no
+  new `tobytes` in model/) ? `test_xref_repair` green. **Red-Light First:** new `test_worker_snapshot_cache.py`
+  (4 tests incl. the **OCR-staleness regression guard** asserting `_on_ocr_page_done` drops the cache), all RED
+  (method absent) ? GREEN. **Test churn (R2.5-class):** the search + OCR flow harnesses' `__new__` controllers
+  needed `_worker_snapshot_cache=None` + `_render_revision_by_session={}` (2 lines each; print harness already
+  passed). Gates: search+ocr+print flow + snapshot + xref-guard 41p, production ruff 0, full suite GREEN.
+  PITFALLS + ARCHITECTURE (controller perf ?) updated. **Next:** R4.3 (thumbnail rasterization ? QThread,
+  reuses this cache) ? R4.1 (overlay raster cache, highest invalidation risk).
+- **2026-06-17 (turn 27): R4.3 LANDED (hybrid async thumbnails, 3-model concurrency item; user-approved scope).**
+  Source mapping surfaced a design fork the one-paragraph plan missed: `get_thumbnail` ? `get_page_pixmap(0.2)` ?
+  `render_page_pixmap` reads the LIVE non-thread-safe `fitz.Document` AND applies watermark overlays
+  (`needs_page_overlay(..., "view")`). The plan's "worker opens its own fitz over snapshot bytes" avoids the
+  live-doc race but the snapshot (`doc.tobytes()`) has NO overlays ? so a naive worker render would silently drop
+  watermarks from thumbnails. Surfaced this as a checkpoint; **user chose the behavior-preserving hybrid.**
+  Built `controller/thumbnail_coordinator.py` (`ThumbnailCoordinator`/`_ThumbnailWorker`/`_ThumbnailBridge`,
+  mirroring Search/Ocr coordinators verbatim: `worker?bridge?handler`, refs dropped on `thread.finished`).
+  `_schedule_thumbnail_batch` now calls `coordinator.try_start(start, sid, gen, end_limit)` first and falls back
+  to the unchanged synchronous path. **Async path taken ONLY when** `_should_async` holds: bridge wired
+  (post-activate), session still active, range ? `THUMB_ASYNC_MIN_PAGES=24`, AND `get_watermarks()` empty
+  (watermarked sessions stay sync ? output byte-identical; annotations are baked into the bytes via `annots=True`
+  so they survive). Worker renders off R4.2 snapshot bytes with the same `_safe_render_scale` clamp + colorspace,
+  emits detached `QImage`s; `_on_batch_ready` converts to `QPixmap` on the GUI thread and drops stale batches via
+  the `_thumb_gen_by_session` token. **Red-Light First:** new `test_thumbnail_coordinator.py` RED (ModuleNotFound)
+  ? 11 GREEN (worker batches synchronously, `_should_async` ?5 eligibility, `_on_batch_ready` paint + staleness,
+  scheduler delegation). **Two bugs caught mid-gating:** (a) a live-thread end-to-end test hung when interleaved
+  (passed in isolation) ? the documented Qt/COM instability; removed it (behavior covered deterministically + the
+  wiring is identical to proven coordinators). (b) `QPixmap.fromImage` HANGS without the `qapp` fixture ? added it
+  to the QPixmap-touching tests (PITFALLS entry). **ZERO churn** to existing thumbnail/flow/multi-tab suites
+  (100p). Gates: thumbnail+flow+multitab 100p/1s, production ruff 0, full suite GREEN. PITFALLS ?2 + ARCHITECTURE
+  (hybrid async thumbnails ?) + TODOS updated. **Next (last R4 item):** R4.1 ? overlay raster cache with per-tool
+  revision counters (highest invalidation risk, ~25 mutation sites).
+- **2026-06-17 (turn 28): R4.1 EVALUATED ? DEFERRED ? R4 COMPLETE (4/5).** Source audit + 3-way design review of
+  the overlay raster cache found every viable variant is incorrect, high-risk-without-a-pixel-gate, or a non-win
+  with friction ? so the deliverable is the documented deferral, not code. **Findings (recorded in the plan's R4.1
+  STATUS block):** (1) **watermark-only** ? only `WatermarkTool` overlays `purpose="view"`; `AnnotationTool` uses
+  the base `needs_page_overlay=False` (annotations are baked via `get_pixmap(annots=True)`, not overlays), so the
+  spec's `annot_revision` is moot. (2) **The literal spec key is incorrect** ? `(...,wm_revision,annot_revision)`
+  omits a base-content revision, but the overlay branch composites `insert_pdf(base)?draw?get_pixmap`, so editing
+  text under a watermark would serve a stale composite. (3) **No complete model-owned invalidation signal**
+  (`edit_count`/`rebuild_page` miss rotation/annotations/watermarks); the only complete one is the controller's
+  whole-session `_render_revision`. (4) **The safe `render_revision`-keyed cache is correct but a non-win** ?
+  redundant with the existing `_render_cache` (already `render_revision`-keyed; prevents redundant overlay compute
+  within a revision ? page view hits `_render_cache` and never reaches the overlay branch, thumbnails render once
+  into the widget, snapshots are on-demand); it would only help under a QPixmap-cache eviction edge case while
+  requiring the controller token threaded into the model render API (layer smell) + ~2? composite memory.
+  (5) **Separate-canvas variant = high risk** ? must replicate page rotation, MediaBox origin, and session
+  colorspace (sRGB/gray/CMYK) and accept AA/overlap blending diffs, with NO watermark pixel-parity gate (no-jump
+  only guards the editor). The real win (cross-revision per-page reuse) needs per-page content-revision tracking
+  across the ~25 `_invalidate_active_render_state` sites (one miss = silent stale render) ? disproportionate risk
+  for a watermark-only conditional gain. **Decision (user-directed):** defer R4.1, record considerations, close R4.
+  Docs-only commit; PITFALLS design-note added. **R4 ? 4/5** ? R4.5 `2a8cf8c` ? R4.4 `62e0b81` ? R4.2 `883fc6e` ?
+  R4.3 `60c36fc`. **Next:** R5 (security & supply-chain hardening) ? and the deferred-findings backlog (R5.1
+  print-decrypt, R5.5 optimizer-decrypt, R3.4 pending_edits, R3.7 shiboken6.isValid, R3.8b dispatcher).
diff --git a/test_scripts/test_ocr_controller_flow.py b/test_scripts/test_ocr_controller_flow.py
index 96bf859..44ce278 100644
--- a/test_scripts/test_ocr_controller_flow.py
+++ b/test_scripts/test_ocr_controller_flow.py
@@ -268,60 +268,63 @@ def test_controller_cancel_ocr_invalidates_generation(qapp, monkeypatch):
 # -----------------------------------------------------------------------------
 
 
 def _build_minimal_controller(monkeypatch, *, available: bool, per_page: dict | None = None, delay: float = 0.0):
     """Create a PDFController with its view replaced by a stub and model mocked."""
     from controller.pdf_controller import PDFController
 
     model = MagicMock()
     model.doc = MagicMock()
     model.doc.__len__ = lambda self=None: 10
     model.apply_ocr_spans = MagicMock(return_value=1)
     model.capture_worker_snapshot_bytes = MagicMock(return_value=b"snapshot-bytes")
 
     tool = _FakeTool(per_page or {}, delay=delay)
 
     def _fake_availability():
         return OcrAvailability(available=True) if available else OcrAvailability(
             available=False, reason="surya missing", install_hint="pip install surya-ocr"
         )
 
     tool.availability = _fake_availability  # type: ignore[assignment]
     model.tools = MagicMock()
     model.tools.ocr = tool
 
     view = MagicMock()
     view.thread = lambda: QCoreApplication.instance().thread()
 
     controller = PDFController.__new__(PDFController)
     controller.model = model
     controller.view = view
+    # R4.2: the worker snapshot cache lives on the controller now.
+    controller._worker_snapshot_cache = None
+    controller._render_revision_by_session = {}
     # R3.2: the OCR runtime now lives on the coordinator (PDFController keeps only
     # the start_ocr/cancel_ocr delegates).
     from controller.ocr_coordinator import OcrCoordinator
 
     oc = OcrCoordinator(controller)
     controller._ocr_coordinator = oc
     oc._ocr_thread = None
     oc._ocr_worker = None
     oc._ocr_worker_bridge = _OcrBridge(None)
     oc._ocr_progress_dialog = None
     oc._ocr_gen = 0
     oc._ocr_session_id = None
     # Wire bridge to coordinator handlers (mirrors activate()/connect_bridge()).
     oc._ocr_worker_bridge.page_done.connect(oc._on_ocr_page_done)
     oc._ocr_worker_bridge.progress.connect(oc._on_ocr_progress)
     oc._ocr_worker_bridge.failed.connect(oc._on_ocr_failed)
     oc._ocr_worker_bridge.thread_finished.connect(oc._on_ocr_thread_finished)
     return controller
 
 
 def _wait_for_ocr_finish(controller, qapp, timeout_ms: int = 4000) -> None:
     loop = QEventLoop()
     from PySide6.QtCore import QTimer
 
     timer = QTimer()
     timer.setSingleShot(True)
     timer.timeout.connect(loop.quit)
     timer.start(timeout_ms)
 
     def _check():
diff --git a/test_scripts/test_pdf_optimize_workflow.py b/test_scripts/test_pdf_optimize_workflow.py
index ac0972f..eb3edd8 100644
--- a/test_scripts/test_pdf_optimize_workflow.py
+++ b/test_scripts/test_pdf_optimize_workflow.py
@@ -118,60 +118,81 @@ def mvc(monkeypatch, qapp):
     model.close()
     view.close()
     _pump_events(50)
 
 
 def test_optimize_dialog_defaults_to_balanced_and_switches_to_custom(qapp) -> None:
     from view.pdf_view import OptimizePdfDialog
 
     dialog = OptimizePdfDialog()
 
     assert dialog.preset_combo.currentText() == "??"
     assert dialog.image_target_dpi_suffix.text() == "dpi"
     assert dialog.image_threshold_dpi_suffix.text() == "dpi"
     assert dialog.image_quality_slider.value() == 60
 
     dialog.metadata_checkbox.setChecked(not dialog.metadata_checkbox.isChecked())
 
     assert dialog.preset_combo.currentText() == "??"
 
 
 def test_pdf_model_optimizer_facade_uses_internal_module() -> None:
     from model.pdf_model import PDFModel
     from model.pdf_optimizer import PdfOptimizeOptions as InternalPdfOptimizeOptions
 
     options = PDFModel.preset_optimize_options("??")
 
     assert isinstance(options, InternalPdfOptimizeOptions)
     assert options.preset == "??"
 
 
+def test_fast_preset_enables_object_streams(tmp_path: Path) -> None:
+    """R4.5: ?? must enable object streams (cheap structural shrink).
+
+    It is the only preset where the flip is both effective and unblocked: ?? already
+    sets it True, ???? forces linearize=True (which strips objstms in
+    normalize_optimize_options). ?? has linearize=False, so the flip survives
+    normalization and reaches the save settings as use_objstms=1.
+    """
+    from model.pdf_model import PDFModel
+    from model.pdf_optimizer import fast_save_kwargs, normalize_optimize_options
+
+    options = PDFModel.preset_optimize_options("??")
+    assert options.use_object_streams is True
+    # linearize is False, so normalization must NOT strip object streams.
+    assert options.linearize is False
+    normalized = normalize_optimize_options(options)
+    assert normalized.use_object_streams is True
+    # The win must actually reach the PyMuPDF save settings (use_objstms=1).
+    assert fast_save_kwargs(normalized)["use_objstms"] == 1
+
+
 def test_file_tab_exposes_optimize_copy_action(mvc) -> None:
     _model, view, _controller = mvc
 
     action = getattr(view, "_action_optimize_copy", None)
 
     assert action is not None
     assert action.text() == "?????????"
 
 
 def test_save_optimized_copy_uses_working_doc_and_preserves_live_doc(tmp_path: Path) -> None:
     from model.pdf_model import PDFModel, PdfOptimizeOptions
 
     source = _make_pdf_with_image(tmp_path / "source.pdf")
     output = tmp_path / "optimized.pdf"
 
     model = PDFModel()
     try:
         model.open_pdf(str(source))
         before_bytes = model.doc.tobytes(no_new_id=1)
 
         result = model.save_optimized_copy(str(output), PdfOptimizeOptions())
 
         after_bytes = model.doc.tobytes(no_new_id=1)
 
         assert output.exists() is True
         assert result.output_path == str(output)
         assert result.optimized_bytes > 0
         assert before_bytes == after_bytes
     finally:
         model.close()
diff --git a/test_scripts/test_search_worker_flow.py b/test_scripts/test_search_worker_flow.py
index db4f361..f6467a3 100644
--- a/test_scripts/test_search_worker_flow.py
+++ b/test_scripts/test_search_worker_flow.py
@@ -145,60 +145,63 @@ def test_search_bridge_forwards_signals(qapp):
     QCoreApplication.processEvents()
 
     assert hits_seen and hits_seen[0][:2] == (2, 1)
     assert failed_seen and isinstance(failed_seen[0][1], RuntimeError)
     assert finished_seen == [2]
 
 
 # -----------------------------------------------------------------------------
 # Controller-level flow
 # -----------------------------------------------------------------------------
 
 
 def _build_minimal_controller(per_page: dict[int, list], *, page_count: int = 3, delay: float = 0.0):
     controller = PDFController.__new__(PDFController)
 
     model = MagicMock()
     model.doc = MagicMock()
     model.doc.__len__ = lambda self=None: page_count
     model.get_active_session_id = MagicMock(return_value="sid-1")
     tool = _FakeSearchTool(per_page, delay=delay)
     model.tools = MagicMock()
     model.tools.search = tool
     model.capture_worker_snapshot_bytes = MagicMock(return_value=_sample_doc_bytes())
 
     view = MagicMock()
     view.thread = lambda: QCoreApplication.instance().thread()
 
     controller.model = model
     controller.view = view
     controller._session_ui_state = {}
+    # R4.2: the worker snapshot cache lives on the controller now.
+    controller._worker_snapshot_cache = None
+    controller._render_revision_by_session = {}
     # R3.2: the search runtime now lives on the coordinator (PDFController keeps only
     # the search_text/_cancel_search delegates + _session_ui_state).
     sc = SearchCoordinator(controller)
     controller._search_coordinator = sc
     sc._search_thread = None
     sc._search_worker = None
     sc._search_gen = 0
     sc._search_query = ""
     sc._search_session_id = None
     sc._search_accumulated_hits = []
     sc._search_worker_bridge = _SearchBridge(None)
     # Wire bridge to coordinator handlers (mirrors activate()/connect_bridge()).
     sc._search_worker_bridge.hits_found.connect(sc._on_search_hits_found)
     sc._search_worker_bridge.failed.connect(sc._on_search_failed)
     sc._search_worker_bridge.finished.connect(sc._on_search_finished)
     return controller, tool
 
 
 def _wait_for_search_finish(controller, qapp, timeout_ms: int = 4000) -> None:
     loop = QEventLoop()
     timer = QTimer()
     timer.setSingleShot(True)
     timer.timeout.connect(loop.quit)
     timer.start(timeout_ms)
 
     def _check():
         if controller._search_coordinator._search_thread is None:
             loop.quit()
         else:
             QTimer.singleShot(20, _check)
diff --git a/test_scripts/test_thumbnail_coordinator.py b/test_scripts/test_thumbnail_coordinator.py
new file mode 100644
index 0000000..6e2a580
--- /dev/null
+++ b/test_scripts/test_thumbnail_coordinator.py
@@ -0,0 +1,206 @@
+"""R4.3 ? hybrid async thumbnail rasterization on a QThread worker.
+
+Large, overlay-free thumbnail rebuilds are offloaded to a background `_ThumbnailWorker`
+that renders pages off the R4.2 worker-snapshot bytes (never the live, non-thread-safe
+`fitz.Document`) and marshals QImages back through `_ThumbnailBridge` to the GUI thread,
+which converts them to QPixmaps. Watermarked sessions (view overlays) and small ranges
+fall back to the existing synchronous batch path, so output is unchanged.
+"""
+
+from __future__ import annotations
+
+import tempfile
+from pathlib import Path
+from unittest.mock import MagicMock
+
+import fitz
+from PySide6.QtGui import QImage, QPixmap
+
+from controller.pdf_controller import PDFController
+from controller.thumbnail_coordinator import (
+    THUMB_ASYNC_MIN_PAGES,
+    ThumbnailCoordinator,
+    _ThumbnailBridge,
+    _ThumbnailWorker,
+)
+from model.pdf_model import PDFModel
+
+
+def _make_pdf(path: Path, pages: int) -> None:
+    doc = fitz.open()
+    for i in range(pages):
+        page = doc.new_page(width=200, height=200)
+        page.insert_text((20, 40), f"page {i + 1}", fontsize=12, fontname="helv")
+    doc.save(str(path), garbage=0)
+    doc.close()
+
+
+def _snapshot_bytes(tmp: str, pages: int) -> bytes:
+    pdf = Path(tmp) / "src.pdf"
+    _make_pdf(pdf, pages)
+    m = PDFModel()
+    try:
+        m.open_pdf(str(pdf))
+        return m.capture_worker_snapshot_bytes()
+    finally:
+        m.close()
+
+
+def _coord_controller(*, page_count: int, watermarks: list, sid: str = "sid-1", connect: bool = True):
+    controller = PDFController.__new__(PDFController)
+    model = MagicMock()
+    model.doc = MagicMock()
+    model.doc.__len__ = lambda self=None: page_count
+    model.get_active_session_id = MagicMock(return_value=sid)
+    model.capture_worker_snapshot_bytes = MagicMock(return_value=b"")
+    model.get_thumbnail = MagicMock()
+    controller.model = model
+    controller.view = MagicMock()
+    controller._thumb_gen_by_session = {sid: 3}
+    controller._worker_snapshot_cache = None
+    controller._render_revision_by_session = {}
+    controller.get_watermarks = MagicMock(return_value=watermarks)
+    controller._resolve_session_profile = MagicMock(return_value="srgb")
+    coord = ThumbnailCoordinator(controller)
+    controller._thumbnail_coordinator = coord
+    if connect:
+        # Parent on None in tests (the production parent is the QObject view).
+        coord._bridge = _ThumbnailBridge(None)
+        coord._bridge.batch_ready.connect(coord._on_batch_ready)
+        coord._bridge.finished.connect(coord._on_finished)
+    return controller, coord
+
+
+# ?? worker (runs synchronously; no thread needed) ???????????????????????????
+
+
+def test_worker_renders_all_pages_in_batches() -> None:
+    with tempfile.TemporaryDirectory() as tmp:
+        snap = _snapshot_bytes(tmp, 5)
+
+    worker = _ThumbnailWorker(snap, 0, 5, 0.2, "srgb", 7, batch_size=2)
+    batches: list[tuple] = []
+    finished: list[int] = []
+    worker.batch_ready.connect(lambda g, s, imgs: batches.append((g, s, imgs)))
+    worker.finished.connect(lambda g: finished.append(g))
+
+    worker.run()
+
+    assert [b[1] for b in batches] == [0, 2, 4]
+    assert sum(len(b[2]) for b in batches) == 5
+    assert all(b[0] == 7 for b in batches)
+    assert all(isinstance(im, QImage) and not im.isNull() for b in batches for im in b[2])
+    assert finished == [7]
+
+
+def test_worker_stops_when_cancelled_before_run() -> None:
+    with tempfile.TemporaryDirectory() as tmp:
+        snap = _snapshot_bytes(tmp, 6)
+
+    worker = _ThumbnailWorker(snap, 0, 6, 0.2, "srgb", 1, batch_size=2)
+    batches: list[tuple] = []
+    finished: list[int] = []
+    worker.batch_ready.connect(lambda g, s, imgs: batches.append((g, s, imgs)))
+    worker.finished.connect(lambda g: finished.append(g))
+
+    worker.request_cancel()
+    worker.run()
+
+    assert batches == []
+    assert finished == [1], "finished must always fire for thread teardown"
+
+
+# ?? eligibility (deterministic; no thread) ??????????????????????????????????
+
+
+def test_should_async_false_when_watermarks_present() -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[{"id": "w1"}])
+    assert coord._should_async(0, "sid-1", None) is False
+
+
+def test_should_async_false_for_small_range() -> None:
+    controller, coord = _coord_controller(page_count=THUMB_ASYNC_MIN_PAGES - 1, watermarks=[])
+    assert coord._should_async(0, "sid-1", None) is False
+
+
+def test_should_async_false_when_bridge_not_connected() -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[], connect=False)
+    assert coord._should_async(0, "sid-1", None) is False
+
+
+def test_should_async_true_for_large_overlay_free_range() -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[])
+    assert coord._should_async(0, "sid-1", None) is True
+
+
+def test_should_async_false_for_stale_session() -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[])
+    assert coord._should_async(0, "other-sid", None) is False
+
+
+# ?? GUI-side painting + staleness guard (deterministic) ?????????????????????
+
+
+def test_on_batch_ready_paints_fresh_gen(qapp) -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[])
+    coord._session_id = "sid-1"
+    img = QImage(8, 8, QImage.Format_RGB888)
+    img.fill(0)
+
+    coord._on_batch_ready(3, 4, [img, img])  # gen 3 == current thumb gen
+
+    controller.view.update_thumbnail_batch.assert_called_once()
+    start_index, pixmaps = controller.view.update_thumbnail_batch.call_args[0]
+    assert start_index == 4
+    assert all(isinstance(p, QPixmap) for p in pixmaps)
+
+
+def test_on_batch_ready_drops_stale_gen() -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[])
+    coord._session_id = "sid-1"
+    img = QImage(8, 8, QImage.Format_RGB888)
+
+    coord._on_batch_ready(1, 0, [img])  # gen 1 != current thumb gen 3
+
+    controller.view.update_thumbnail_batch.assert_not_called()
+
+
+# NOTE: a real-thread end-to-end test (try_start -> QThread -> bridge -> paint) was
+# intentionally NOT committed. The QThread wiring here is byte-identical to the proven
+# SearchCoordinator/OcrCoordinator, and a live cross-thread render test exhibits the same
+# Qt/COM event-loop instability the suite already documents for the async search test
+# (it passes in isolation but hangs/crashes when interleaved). The off-thread render is
+# verified deterministically by test_worker_renders_all_pages_in_batches (worker.run), the
+# decision by _should_async, and the GUI marshalling by the _on_batch_ready tests.
+
+
+# ?? scheduler delegation (the integration seam) ?????????????????????????????
+
+
+def test_schedule_thumbnail_batch_delegates_to_coordinator_when_async() -> None:
+    controller, coord = _coord_controller(page_count=200, watermarks=[])
+    coord.try_start = MagicMock(return_value=True)
+
+    controller._schedule_thumbnail_batch(0, "sid-1", 3)
+
+    coord.try_start.assert_called_once_with(0, "sid-1", 3, None)
+    # Async took over -> the synchronous per-page render must be skipped.
+    controller.model.get_thumbnail.assert_not_called()
+
+
+def test_schedule_thumbnail_batch_runs_sync_when_coordinator_declines(qapp) -> None:
+    controller, coord = _coord_controller(page_count=3, watermarks=[])
+    coord.try_start = MagicMock(return_value=False)
+    controller._fitz_colorspace_for_session = MagicMock(return_value=None)
+
+    # Use a real tiny pixmap so pixmap_to_qpixmap works on the sync fallback.
+    doc = fitz.open()
+    doc.new_page(width=40, height=40)
+    controller.model.get_thumbnail = MagicMock(return_value=doc[0].get_pixmap())
+
+    controller._schedule_thumbnail_batch(0, "sid-1", 3)
+
+    coord.try_start.assert_called_once()
+    controller.model.get_thumbnail.assert_called()  # sync path rendered
+    controller.view.update_thumbnail_batch.assert_called_once()
+    doc.close()
diff --git a/test_scripts/test_undo_memory_budget.py b/test_scripts/test_undo_memory_budget.py
index daab8d6..90dead2 100644
--- a/test_scripts/test_undo_memory_budget.py
+++ b/test_scripts/test_undo_memory_budget.py
@@ -219,30 +219,85 @@ def test_single_oversized_command_survives_byte_trim(monkeypatch) -> None:
     assert cm.has_pending_changes() is True
 
 
 def test_dedup_shared_bytes_counted_once_in_budget(monkeypatch) -> None:
     """After dedup, shared bytes between adjacent commands should count once,
     not twice. A budget that fits unique bytes but not double-counted bytes
     must not evict anything."""
     cm = CommandManager()
     model = _FakeModel()
 
     shared = b"s" * 100
     cmd1 = _snapshot_cmd(model, b"a" * 50, bytes(shared), "op1")
     cmd2 = _snapshot_cmd(model, bytes(shared), b"c" * 50, "op2")
 
     cm.record(cmd1)
     cm.record(cmd2)
 
     # Verify dedup fired.
     assert cm._undo_stack[0]._after_bytes is cm._undo_stack[1]._before_bytes
 
     # Unique bytes: 50 (a) + 100 (shared) + 50 (c) = 200.
     # Double-counted: 50 + 100 + 100 + 50 = 300.
     # Budget = 250: fits unique (200), but not double-counted (300).
     monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 250)
     cm._trim_undo_stack_if_needed()
 
     assert cm.undo_count == 2, (
         f"dedup'd shared bytes should count once ? both commands fit in 250-byte budget, "
         f"but got undo_count={cm.undo_count}"
     )
+
+
+def test_non_adjacent_identical_bytes_counted_once() -> None:
+    """R4.4: byte-identical snapshots that are NOT an adjacent boundary pair must
+    still count once against the budget. `_dedup_top_snapshot_pair` only aliases the
+    top two commands at push time, so non-adjacent duplicates stay distinct objects;
+    `_unique_byte_total` must dedup them by CONTENT, not by id()."""
+    cm = CommandManager()
+    model = _FakeModel()
+
+    x = b"x" * 100
+    x_dup = bytes(bytearray(b"x" * 100))  # identical content, distinct object
+    assert x == x_dup and x is not x_dup
+
+    cmd1 = _snapshot_cmd(model, b"a" * 50, x, "op1")
+    cmd2 = _snapshot_cmd(model, b"b" * 50, b"c" * 50, "op2")
+    cmd3 = _snapshot_cmd(model, x_dup, b"d" * 50, "op3")
+
+    cm.record(cmd1)
+    cm.record(cmd2)
+    cm.record(cmd3)
+
+    # The duplicate (x / x_dup) is non-adjacent, so no alias was created.
+    assert cm._undo_stack[0]._after_bytes is not cm._undo_stack[2]._before_bytes
+
+    # Distinct content: a(50) + x(100) + b(50) + c(50) + d(50) = 300.
+    # id()-keyed double-counts x twice -> 400.
+    assert cm._unique_byte_total() == 300, (
+        f"non-adjacent identical bytes must count once, got {cm._unique_byte_total()}"
+    )
+
+
+def test_non_adjacent_duplicate_does_not_prematurely_evict(monkeypatch) -> None:
+    """R4.4: a budget that fits the unique footprint but not the id()-double-counted
+    figure must NOT evict when the duplicate is non-adjacent."""
+    cm = CommandManager()
+    model = _FakeModel()
+
+    x = b"x" * 100
+    cmd1 = _snapshot_cmd(model, b"a" * 50, x, "op1")
+    cmd2 = _snapshot_cmd(model, b"b" * 50, b"c" * 50, "op2")
+    cmd3 = _snapshot_cmd(model, bytes(bytearray(b"x" * 100)), b"d" * 50, "op3")
+
+    cm.record(cmd1)
+    cm.record(cmd2)
+    cm.record(cmd3)
+
+    # Unique footprint = 300; id()-double-counted = 400. Budget 350 fits unique only.
+    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 350)
+    cm._trim_undo_stack_if_needed()
+
+    assert cm.undo_count == 3, (
+        f"non-adjacent duplicate should count once ? all 3 fit in 350-byte budget, "
+        f"got undo_count={cm.undo_count}"
+    )
diff --git a/test_scripts/test_worker_snapshot_cache.py b/test_scripts/test_worker_snapshot_cache.py
new file mode 100644
index 0000000..8921ad7
--- /dev/null
+++ b/test_scripts/test_worker_snapshot_cache.py
@@ -0,0 +1,110 @@
+"""R4.2 ? controller-owned, revision-keyed worker snapshot-bytes cache.
+
+`model.capture_worker_snapshot_bytes()` does a full `doc.tobytes()`; search, OCR and
+print each capture it independently (GUI thread, before `QThread.start()`), so
+overlapping jobs on an unedited doc re-serialize identical bytes. The controller caches
+the bytes keyed on `(active_session_id, render_revision)` ? the same token the page
+render cache trusts.
+
+The subtle correctness hazard (and the reason this is a 3-model item): OCR injects
+INVISIBLE text (`render_mode=3`) via `apply_ocr_spans`, which changes `doc.tobytes()`
+(searchable!) but is pixel-identical and so does NOT bump `_render_revision`. A naive
+`(sid, revision)` cache would serve pre-OCR bytes to a later search ? it misses the
+OCR'd text, a silent regression vs the current always-fresh call. The OCR coordinator
+must therefore drop the snapshot cache after applying spans.
+"""
+
+from __future__ import annotations
+
+from unittest.mock import MagicMock
+
+from controller.ocr_coordinator import OcrCoordinator
+from controller.pdf_controller import PDFController
+
+
+def _counter_bytes():
+    """Distinct bytes per call so a cache hit is observable by identity."""
+    state = {"n": 0}
+
+    def _make() -> bytes:
+        state["n"] += 1
+        return f"snapshot-{state['n']}".encode()
+
+    return _make
+
+
+def _minimal_controller(sid: str | None = "sid-1") -> PDFController:
+    controller = PDFController.__new__(PDFController)
+    model = MagicMock()
+    model.get_active_session_id = MagicMock(return_value=sid)
+    model.capture_worker_snapshot_bytes = MagicMock(side_effect=_counter_bytes())
+    controller.model = model
+    # State the cache method + _bump_render_revision touch.
+    controller._worker_snapshot_cache = None
+    controller._render_revision_by_session = {}
+    controller._page_render_quality_by_session = {}
+    controller._render_cache = {}
+    controller._render_cache_total_bytes = 0
+    return controller
+
+
+def test_cache_hit_on_unedited_doc_serializes_once() -> None:
+    controller = _minimal_controller()
+
+    first = controller.capture_worker_snapshot_bytes()
+    second = controller.capture_worker_snapshot_bytes()
+
+    assert first == second
+    assert first is second, "unedited doc must return the cached bytes object"
+    assert controller.model.capture_worker_snapshot_bytes.call_count == 1
+
+
+def test_render_revision_bump_invalidates_cache() -> None:
+    controller = _minimal_controller()
+
+    first = controller.capture_worker_snapshot_bytes()
+    controller._bump_render_revision("sid-1")  # an edit / mutation
+    second = controller.capture_worker_snapshot_bytes()
+
+    assert first != second, "a render-revision bump must force a fresh serialization"
+    assert controller.model.capture_worker_snapshot_bytes.call_count == 2
+
+
+def test_no_active_session_bypasses_cache() -> None:
+    controller = _minimal_controller(sid=None)
+
+    first = controller.capture_worker_snapshot_bytes()
+    second = controller.capture_worker_snapshot_bytes()
+
+    # No session id -> never cached -> fresh each call.
+    assert first != second
+    assert controller.model.capture_worker_snapshot_bytes.call_count == 2
+    assert controller._worker_snapshot_cache is None
+
+
+def test_ocr_apply_invalidates_worker_snapshot_cache() -> None:
+    """The regression guard: OCR injects invisible (searchable) text without bumping
+    render_revision, so applying spans MUST drop the snapshot cache ? otherwise a
+    later search reads stale pre-OCR bytes and misses the recognized text."""
+    controller = _minimal_controller()
+    controller.model.apply_ocr_spans = MagicMock(return_value=1)
+    coord = OcrCoordinator(controller)
+    controller._ocr_coordinator = coord
+    coord._ocr_gen = 7
+    coord._ocr_session_id = "sid-1"
+
+    # The OCR worker primes the cache when it captures its input snapshot.
+    primed = controller.capture_worker_snapshot_bytes()
+    assert controller._worker_snapshot_cache is not None
+
+    # A page of OCR completes: invisible text injected, render_revision unchanged.
+    coord._on_ocr_page_done(7, 1, [object()])
+    controller.model.apply_ocr_spans.assert_called_once()
+
+    assert controller._worker_snapshot_cache is None, (
+        "apply_ocr_spans changes doc.tobytes() without a render bump ? the snapshot "
+        "cache must be invalidated or a later search serves stale pre-OCR bytes"
+    )
+    # And the next capture is genuinely fresh (would contain the OCR text).
+    fresh = controller.capture_worker_snapshot_bytes()
+    assert fresh != primed

--- END UNTRUSTED STDIN ---
