# Phase R3 — God-Module Decomposition

**Status:** Ready (after R2 guard lands). **Fusion:** 3-model (Playbook 4.4 design + 4.1 pre-edit).
**Why:** `pdf_view` 5497 / `pdf_model` 5166 / `pdf_controller` 3383 / `text_editing` 1809 /
`text_block` 1043 LOC are genuine god-modules. This is the **highest-risk** phase — state
migration + signal rewiring. It is gated on R2's import guard + generalized encryption guard.
(Census: god-module lens.)

> **Implicit risks:** state migration is the dominant vector (ObjectSelectionManager must move ~25
> attrs); the mouse-handler dispatcher must preserve `current_mode` early-return ordering;
> coordinator extraction must preserve exact `QThread` signal wiring (a missed `connect` = a
> worker that runs but never reports back — silent hang). Encryption/snapshot-adjacent model seams
> must keep `save`/`tobytes` visible to the generalized AST guard.

## Pattern (proven in-repo)

Every extraction follows an existing precedent and **stays inside its own MVC layer behind a
stable facade**: free-function modules taking `model: PDFModel` (like `pdf_optimizer.py`
`def fn(model, ...)` with 1-line delegating wrappers at `pdf_model.py:3207-3340`); view managers
holding `self._view` and emitting via `self._view.sig_*` (like `TextEditManager`,
`text_editing.py:964`); PEP-562 lazy packages (`view/dialogs/__init__.py:17`). **No extraction
crosses a layer.** One cohesive seam per commit; full suite green before/after each.

## HARD internal ordering (non-negotiable — critique-enforced)

### R3.1 — `model/text_block_parsing.py` (FIRST — verified pure leaf) ✅ DONE 2026-06-16
> Landed: `text_block.py` 1043→338 LOC; new pure leaf `model/text_block_parsing.py` (helpers + 3
> dataclasses + 14 transforms), moved verbatim. `TextBlockManager` keeps all index state and delegates
> (signatures preserved); `text_block` re-exports dataclasses + `rotation_degrees_from_dir`. Red-Light via
> `test_text_block_parsing_extraction.py`. Suite 1366p/20s, AST guards green, ruff 0, codegraph re-indexed.

- `text_block.py:392-1043` (~652 LOC): `_parse_block/_parse_spans/_parse_runs_from_raw_*/
  _build_paragraphs/_merge_vertical_paragraphs/_expand_ligatures/...`. **10 `self.` refs total, 5
  `@staticmethod`**; none touch the instance indices (`_index/_span_index/_paragraph_index/
  _run_to_paragraph/_page_plain_lines/_page_state`, L152-169). Stateless transforms: fitz page
  dict → `TextBlock/EditableSpan/EditableParagraph` dataclasses (L99/117/134).
- **Extract** a free-function module owning **no** state. `TextBlockManager._build_page_index`
  (L244) keeps ownership of all indices and calls into it. Public API unchanged. Own red-light
  test (feed a fitz page dict, assert dataclass output) before the move. **Lowest blast radius of
  all five modules — do it first.**

### R3.2 — Controller async-job coordinators (search → OCR → print) — ✅ ALL DONE 2026-06-16
> **R3.2/search landed** (3-model fusion design: Gemini Pass A + Codex Pass C agreed; Pass B timed
> out). New `controller/search_coordinator.py` (`SearchCoordinator` + `_SearchWorker`/`_SearchBridge`
> moved, re-exported from `pdf_controller`). 8 runtime attrs + 4 slots moved off the controller;
> `search_text`/`_cancel_search` are delegates. Signal wiring / QThread lifecycle / `_search_gen`
> guards preserved verbatim. Test net redirected to `controller._search_coordinator`. Gates: search +
> guards 23p, related controller-flow 96p, full suite green, ruff 0.
>
> **R3.2/OCR landed 2026-06-16** (full 3-model fusion: Gemini A+B + Codex C). New
> `controller/ocr_coordinator.py` (`OcrCoordinator` + `_OcrWorker`/`_OcrBridge` moved, re-exported).
> 6 runtime attrs + 5 slots + dialog/release helpers moved; `start_ocr`/`cancel_ocr` delegates.
> **Design split resolved:** 2 Gemini said move `_refresh_ocr_availability`, Codex said keep it on the
> controller (it owns no worker runtime — a UI probe); upheld Codex (scope-minimal, lower-churn). Session
> guard / `_ocr_gen` token / GUI-thread `apply_ocr_spans` / dialog parenting preserved verbatim. Gates:
> OCR + guards 33p/8s, full suite green, ruff 0. **print coordinator still TODO (largest; coord. R5.1).**

- The 8 worker/bridge QObjects are **already module-level** (`_PrintSubmissionWorker:121`,
  `_OcrWorker:216`, `_SearchWorker:308`, + bridges); only orchestration methods/state live on
  PDFController.
- **Extract** `controller/search_coordinator.py` (smallest, ~7 methods, already async-isolated by
  Phase4) → then `ocr_coordinator.py` → then `print_coordinator.py` (largest; subprocess runner +
  stall/terminate edges). Each holds `self._controller`, owns its `thread/worker/bridge/gen/
  dialog/session_id` state. Facade = `PDFController` keeps thin `search_text/start_ocr/
  print_document/start_optimize_pdf_copy` delegates. Bridges keep emitting to `QObject(view)`.
- **Coordinate with R5:** `print_coordinator` relocates the decrypted-snapshot handoff R5.1 fixes
  — share one regression pass (see refactor-state §3 hazard 5).

#### R3.2a — `controller/search_coordinator.py` extraction map (reverse-engineered 2026-06-16, pre-move)
> Scoped and ready to execute; **blocked on the fusion-design decision below** (3-model review the plan
> mandates is unavailable in this env). All line numbers vs HEAD `89770be`.
- **Module-level classes stay put / re-exported:** `_SearchWorker` (`pdf_controller.py:306`), `_SearchBridge`
  (`:354`). `test_search_worker_flow.py:18` does `from controller.pdf_controller import _SearchWorker,
  _SearchBridge` and the worker/bridge **unit** tests (lines 71–148) exercise the real async machinery
  **without touching the controller** — so if the classes move into `search_coordinator.py` they MUST be
  re-exported from `pdf_controller` to keep that import green.
- **State to migrate (8 attrs, `__init__` 398–405):** `_search_thread`, `_search_worker`,
  `_search_worker_bridge`, `_search_accumulated_hits`, `_search_gen`, `_search_query`,
  `_search_session_id`, `_search_finished` → onto `SearchCoordinator(self._c)`.
- **Methods to move (6):** `search_text` (2530), `_release_search_thread` (2576), `_cancel_search` (2581),
  `_on_search_hits_found` (2607), `_on_search_failed` (2618), `_on_search_finished` (2625).
- **Controller delegates kept:** `search_text` (public) **and** `_cancel_search` — the latter has **13
  internal callers** (1016/1114/1132/1238/1517/1825/1849/1873/2536/2800/2811/3181/3222) that call
  `self._cancel_search()` before mutations, so it must stay callable on the controller (thin delegate).
  `test_thumbnail_async.py:112` does `controller._cancel_search = MagicMock()` — works with a delegate.
- **Bridge lazy-init** moves from `activate()` (450–454) into the coordinator (connect bridge→coordinator
  handlers). `jump_to_result` (2640) stays on the controller (no worker/thread state — pixmap+nav only).
- **Signal wiring to preserve VERBATIM** (the silent-hang / hard-crash vectors): `thread.started→worker.run`;
  `worker.{hits_found,failed,finished}→bridge.forward_*`; `worker.finished→thread.quit`+`worker.deleteLater`;
  `thread.finished→thread.deleteLater`+`lambda t: _release_search_thread(t)` (release the QThread wrapper
  ONLY after `thread.finished`, never mid-run — see the inline comment at 2567–2569).
- **Test churn (accepted, R2.5-class):** rewrite `test_search_worker_flow.py` `_build_minimal_controller`
  (156–185) + `_wait_for_search_finish` (188–202) + the 3 controller-flow tests (205–258) to drive
  `controller._search_coordinator` instead of `controller._search_*`. Worker/bridge unit tests unchanged.
- **Gate:** worker/bridge unit tests + rewritten flow tests + full suite + AST guards all green; revert (not
  patch forward) if not. **DECISION NEEDED:** proceed solo with manual-lens + pytest gating (R1/R2
  precedent), or hold for fusion 3-model review.

#### R3.2c — `controller/print_coordinator.py` extraction map (3-model fusion, 2026-06-16, pre-move)
> Synthesized from Gemini Pass A + Pass B + Codex Pass C — **all three agreed** on the design; Codex
> supplied the exact test-churn map. Ready to execute (strictly mechanical; **R5.1 deferred**). Largest /
> highest-risk coordinator (subprocess runner + stall/terminate state machine + app-close/fullscreen
> coupling). Line numbers vs HEAD `cc1e0f9` (±, verify on read).
- **Stay on `PDFController`:** `print_document()` (delegate → coordinator), `activate()` (→
  `connect_bridge()`), `_render_print_preview_image()` (~:1402 — controller-only render helpers
  `_fitz_colorspace_for_session`/session state/`pixmap_to_qimage`; passed as the dialog's preview
  callback), `handle_app_close()` + `_fullscreen_is_blocked()` (app-lifecycle; query the coordinator), and
  **`_has_active_print_submission()` MUST stay a controller facade** (monkeypatched at
  `test_multi_tab_plan.py:1630,1634`; used by close/fullscreen) — delegate it to
  `self._print_coordinator.has_active_job()`. **Verify `print_dispatcher` ownership** (Pass A said move it;
  Codex didn't list it — confirm whether it's print-submission state or separate before moving).
- **Move to `PrintCoordinator`:** 8 state attrs (`_print_dialog`, `_print_progress_dialog`,
  `_print_thread`, `_print_worker`, `_print_runner`, `_print_worker_bridge`, `_print_close_pending`,
  `_print_stalled`); `_PrintSubmissionWorker` + `_PrintWorkerBridge` + **`PrintJobRequest`** (move +
  re-export from `pdf_controller`); `_show/_update/_hide_print_progress_dialog`, `_set_print_status_message`,
  `_set_print_ui_busy`, `_update_print_close_pending_ui`, `_enable_print_terminate_option`,
  `_start_print_submission`, `_create_print_runner`, all `_on_print_*`, `_terminate_active_print_submission`,
  `_finalize_print_submission`, `_complete_active_print_submission_if_idle` (~:1412-1599).
- **Invariants (verbatim):** `connect_bridge()` in `activate()`; all 4 bridge signals
  (progress/prepared/failed/thread_finished) + all 5 runner signals connected BEFORE `runner.start()`;
  `thread.finished`-bound `_release_print_thread`; `work_dir = Path(job.input_pdf_path).parent` (so
  `PrintSubprocessRunner._cleanup` deletes the right temp dir); stall/terminate state machine
  (`_print_stalled`/`_print_close_pending` + `PRINT_*_MESSAGE`/`PRINT_TERMINATE_BUTTON_TEXT`);
  close-during-print suppresses message boxes + ignores the close event, view.close() only after idle;
  `capture_worker_snapshot_bytes()` SYNCHRONOUS on the GUI thread before `QThread.start()`, **name
  unchanged** (encryption AST-guard chokepoint, allowlisted at `test_xref_repair.py:350-414`); progress
  dialog view-parented, non-auto-close, `deleteLater()`, cancel→terminate.
- **Test churn (Codex-mapped, R2.5-class):** `test_print_controller_flow.py` — redirect `_print_*`/
  `_on_print_*`/`_terminate_active_print_submission` accesses to `controller._print_coordinator.*`, AND
  **retarget module patches** `UnifiedPrintDialog`/`QProgressDialog`/`PrintSubprocessRunner`/`show_error`
  (and maybe `QMessageBox`) from `controller.pdf_controller` → `controller.print_coordinator` (the symbols
  are used in the coordinator now). Keep `controller._has_active_print_submission` facade for
  `test_multi_tab_plan.py`. `test_print_subprocess_runner.py` unchanged. `test_print_speed.py:10` stale
  comment → comment-only update.
- **Commit boundary:** single mechanical commit; **defer R5.1** (decrypt-snapshot/PDF_ENCRYPT_NONE) to its
  own reviewed commit — don't mix relocation with security semantics.

> **R3.2/print LANDED 2026-06-16** (per the map above). New `controller/print_coordinator.py`
> (`PrintCoordinator` + `_PrintSubmissionWorker`/`_PrintWorkerBridge`/`PrintJobRequest` moved + re-exported).
> Resolved `print_dispatcher` → **moved** (only print uses it; coordinator's `connect_bridge()` lazy-inits
> it). `print_document` + `_has_active_print_submission` are controller delegates; `_render_print_preview_image`
> + `handle_app_close` (→ `coordinator.begin_close_pending()`) + `_fullscreen_is_blocked` stay. Removed 9
> now-unused print imports from pdf_controller (ruff `--fix`, verified non-re-export). R5.1 deferred;
> `capture_worker_snapshot_bytes` name + GUI-thread sequence unchanged. Test churn: redirected
> `test_print_controller_flow.py` accesses to `controller._print_coordinator.*` and retargeted the
> `UnifiedPrintDialog`/`QProgressDialog`/`PrintSubprocessRunner`/`show_error`/`QMessageBox` patches
> `pdf_controller`→`print_coordinator` (removed the now-unused `pdf_controller_module` alias → test ruff
> back to baseline 7). Gates: print contract + flow 8p, AST guards + snapshot/speed/multi_tab 85p/1s,
> production ruff 0. **R3.2 COMPLETE (search + OCR + print).** Next: R3.3 (confirm encryption guard, done
> in R2.2) → R3.4 (`model/pdf_object_ops.py`) → R3.5 (`model/pdf_text_edit.py`, LAST model seam, no-jump gate).

### R3.3 — Generalize the encryption AST guard to all of model/ (if not already done in R2.2)
- **Before** any model engine leaves `pdf_model.py`. Confirm the guard walks all of model/ and the
  decrypt-sink allowlist is in place. (Belt-and-suspenders with R2.2.)

### R3.4 — `model/pdf_object_ops.py` (object markers + native-image invocation + verbs) ✅ DONE 2026-06-16
> Landed: pdf_model.py 5164→4410 LOC; new `model/pdf_object_ops.py` (~830 LOC, 19 free functions + the
> moved `_APP_OBJECT_*` constants). Controlled verbatim transform (my own script: dedent + `self`→`model` +
> `self.<moved>(`→`<moved>(model,`), NOT the codex-rescue agent's unrequested file (quarantined; it wrongly
> moved OCR). 7 public wrappers; OCR (`apply_ocr_spans`/`_pick_ocr_font`) + HTML converters stay. Caught
> `_html_mod` (module-level `import html`) needed in the new module. Gates: object-ops 78p (8 suites +
> extraction + guards), full suite green, ruff 0. Deferred finding (possible missing pending_edits in some
> move/rotate/delete branches) moved verbatim, NOT fixed.
- `pdf_model.py:2211-3065` (~850 LOC): markers, `_find/_rewrite/_remove_native_image_invocation`,
  `add_image_object/add_textbox/move_object/rotate_object/delete_object/resize_object`. self-refs
  dominated by `doc×50`, shares `pending_edits/edit_count` + snapshot machinery with edit_text.
- **Extract** a free-function module (`model: PDFModel` first arg); imports (does not move)
  `pdf_content_ops.py` stream parsing. PDFModel keeps the verbs as delegates. **HIGH risk** (undo-
  snapshot + encryption roundtrip). Sequence adjacent to R3.5; share a single regression pass.

#### R3.4a — `model/pdf_object_ops.py` extraction map (3-model: Codex + source-verified; Gemini hung on 5160-LOC file)
> Verified against source at HEAD `a597f42`. Gemini full-file fusion HUNG (>10min, killed) — re-ran focused
> on a 2200-3070 extract; Codex Pass C was thorough and I cross-verified the call graph myself (authoritative).
- **MOVE to `model/pdf_object_ops.py`** (free functions `def fn(model: PDFModel, ...)`, mirroring
  `pdf_optimizer.py`): two NON-contiguous blocks — **2209-2643** (`_dump_app_object_payload`,
  `_load_app_object_payload`, `_iter_page_annots` [dead — no callers; move w/ cluster],
  `_find_app_object_annot`, `_find_native_image_invocation`, `_rewrite_native_image_matrix`,
  `_find_app_image_invocation` [nested `_rect_dist`], `_remove_native_image_invocation`,
  `_delete_app_object_annots`, `_create_textbox_object_marker`, `_create_image_object_marker`,
  `add_image_object`, `_insert_textbox_visual_content`) and **2725-3061** (`add_textbox`,
  `get_object_info_at_point`, `_redact_and_restore_textbox_region`, `move_object`,
  `_rotate_native_image_absolute`, `rotate_object`, `delete_object`, `resize_object`).
- **STAY on PDFModel — INTERLEAVED, do NOT move:** `_pick_ocr_font` (2644) + `apply_ocr_spans` (2654, the
  method the OcrCoordinator calls) + `_convert_text_to_html` (3063). The cluster is split around these.
- **Cluster is CLOSED:** every moved private's callers (verified) are all within the moved set
  (2248-3046); no staying method calls a moved private; `apply_ocr_spans` calls no object-op. So NO
  staying-code call-site changes — only the moved methods' own bodies transform.
- **Wrappers (7 public, tests call them):** `add_image_object`, `add_textbox`, `get_object_info_at_point`,
  `move_object`, `rotate_object`, `delete_object`, `resize_object` → 1-line `return pdf_object_ops.fn(self, …)`.
  Moved PRIVATES are deleted from PDFModel (no external callers).
- **Transform:** `def m(self,…)`→`def m(model: PDFModel,…)`; `self.<movedname>(`→`<movedname>(model, `;
  remaining `self.`→`model.`. Reaches staying surface via `model.`: `doc`, `pending_edits`, `edit_count`,
  `block_manager`, `tools`, `_resolve_add_text_font`, `_needs_cjk_font`, `_visual_rect_to_unrotated_rect`,
  `_unrotated_page_rect`, `_insert_tiny_plain_text`, `_repair_active_doc_in_memory`, `_safe_exc_message`.
- **Invariants (Codex+verified):** object ops NEVER call `_capture_*`/`_restore_*` (undo is the controller's
  boundary — wrappers stay 1-line); keep `pending_edits.append(...)`/`edit_count += 1` in exact order after
  `doc.update_stream`; `block_manager.rebuild_page(...)` calls verbatim; NO `.save`/`.tobytes` (encryption
  guard scans model/); import `PDFModel` only under `TYPE_CHECKING`; import (don't move) `pdf_content_ops`.
- **Test surface (8 files, all via the public wrappers):** test_add_textbox_atomic, test_image_objects_model,
  test_native_image_discovery, test_native_pdf_images_model, test_object_free_rotation,
  test_object_manipulation_model, test_object_controller_flow, test_object_manipulation_gui — all call the
  7 public methods on `model`; **wrappers preserve them → expected ZERO test churn.** R3.5 (edit_text) is the
  adjacent next seam; object-ops moves FIRST and independently (shares no moved code).
- **Deferred finding (DO NOT fix in R3.4 — flagged by Gemini Pass A):** the `rect`/`textbox`/image-delete
  branches of `move_object`/`rotate_object`/`delete_object` may omit `pending_edits.append`/`edit_count += 1`
  that the native-image path performs. This is **existing** behavior (possibly intentional — the controller
  captures a doc snapshot for undo independently of `pending_edits`). Move it **verbatim**; if it's a real
  save-prompt/refresh bug it is a separate post-R3 fix, not part of this structural seam.
  - **RESOLVED 2026-06-18 (post-R6, traced end-to-end) → NOT a correctness bug; DOCUMENT & CLOSE (user decision).**
    `pending_edits` has exactly **one** consumer repo-wide: `PDFModel.apply_pending_redactions()`
    (`pdf_model.py:2775`), which calls `page.clean_contents()` on each registered page — a Phase-6 **content-stream
    size optimization** ("壓縮 content stream… 降低 PDF 大小 10-30%"), invoked before `save_as` (`:3082`) and on the
    text-edit GC cadence. It is **not** a correctness mechanism: no rendering, data, undo, encryption, or
    save-prompt path reads it (undo is the controller's independent doc snapshot; the dirty/save-prompt flag is
    separate). `edit_count` is read only by `_maybe_garbage_collect`, which is called **only** from the *text-edit*
    path (`pdf_text_edit.py:1276`), never from object ops — so its increment is inert for the object verbs.
    **Net consequence of the omission:** after a textbox move/rotate or image/textbox delete, that page skips the
    optional pre-save `clean_contents()` compaction the native-image path gets, so the saved PDF is slightly
    **larger** — but byte-correct and pixel-identical when rendered. The annotation-only `rect` branches correctly
    omit it (`clean_contents` cleans the content stream, not annotations). Any fix would **change saved-PDF output**
    for object edits, which the no-jump gate (text-editor pixel geometry only) structurally cannot validate — same
    class as the deferred R3.8b. Closed with no code change; revisit only if object-edit output size becomes a
    measured concern (then: register the content-rewriting branches for `clean_contents`, gated by an object-mode
    save-size test built first). See `refactor-state.md` turn 36.

### R3.5 — `model/pdf_text_edit.py` (edit_text/redaction engine — LAST model seam) ✅ LANDED
**As-built extraction map** (3-model: Gemini dual-lens + Codex + source-verified; the source
verification produced a concrete override BOTH Gemini lenses missed — see below).

**MOVE** (9 methods, a contiguous run `pdf_model.py:2951-4184`, → free functions `fn(model: PDFModel, ...)`):
`_has_complex_script`, `_push_down_overlapping_text`, `_replay_protected_spans`,
`_validate_protected_spans`, `_resolve_edit_target`, `_apply_redact_insert` (moved WHOLE, ~360 LOC),
`_verify_rebuild_edit`, `_resolve_effective_target_mode`, `edit_text` (body moves; wrapper stays).
Two module-level helpers move too and are **re-exported from pdf_model** (tests import them):
`_EditTextResolveResult` (dataclass) and `_classify_insert_path` (view/model shared classifier).

**STAY** (cross-cutting consumers reach them, so they remain PDFModel methods; moved code calls via `model.`):
- `_resolve_font_for_push` — **source-verified override of both Gemini lenses (which said MOVE):**
  called by the *staying* `_resolve_add_text_font` (pdf_model:2144), so it cannot move. Codex concurred.
- `_needs_cjk_font` — also `pdf_object_ops.py:444` + monkeypatched in tests.
- `_convert_text_to_html` / `_build_insert_css` / `_build_multi_style_html` — controller + view preview path.
- `_maybe_garbage_collect` — encryption-preserving `_roundtrip_live_doc`; also `test_xref_repair.py`.
- `_reauthenticate_if_needed` — save/snapshot/roundtrip paths.

**Transform discipline:** UNIFORM `self.` → `model.` (every inter-method call among the moved set
dispatches through its PDFModel wrapper) — this preserves exact bound-method / monkeypatch semantics
(`test_edit_text_helpers` monkeypatches `_push_down_overlapping_text`; a local free-call would bypass it).
`_classify_insert_path`/`_EditTextResolveResult` were already called BARE → stay local.
**Wrappers:** PDFModel keeps delegating wrappers for ALL 9 (not just `edit_text`) because the test net
pokes the privates directly (`test_edit_text_helpers`, `test_resolve_target_mode`) — 8 generic
`(*args, **kwargs)` forwarders + the explicit `edit_text` signature. ZERO test churn.
**Gates (all green):** contract test RED→GREEN; edit suites 425p; AST guards; full suite 1384p/20s;
no-jump completion-gate PASSED before (`04b0a4c`) and after.

### R3.6 — `view/object_selection.py` `ObjectSelectionManager(view)` — MAP (3-model synthesized + source-verified)
Template = `TextEditManager` (view/text_editing.py:976): plain helper holding `self._view`; own
migrated state via `self.X`; view state/methods via `self._view.X`; Qt Signals stay class attrs on
PDFView, manager emits via `self._view.sig_*`. PDFView constructs it eagerly in `__init__` (where the
attr block was, ~544) **and** exposes a lazy `_ensure_object_selection_manager()` (mirrors
`_ensure_text_edit_manager` :2486) because `set_mode` (:1932) calls `_clear_object_selection` and can
fire during startup.

**MOVE — 20 object-selection methods** (scattered in pdf_view.py 3688-4172, NOT a contiguous span; the
region also holds 5 STAY text/general methods — `_select_all_text_on_current_page`, `_zoom_relative`,
`_start_text_edit_from_hit`, `_copy_selected_text_to_clipboard`, `_clamp_editor_pos_to_page`):
`_resolve_object_info_for_context_menu_pos`, `_clear_object_selection`, `_select_object`,
`_rebase_object_selection_to_bboxes`, `_apply_object_selection_rotation`, `_object_center_scene`,
`_supports_free_rotate`, `_update_object_selection_visuals` (carries the post-`scene.clear()` validity
guard :3935-3945 — moves with it, so that invariant is preserved free), `_point_hits_object_resize_handle`,
`_hit_object_resize_handle_index`, `_point_hits_object_rotate_handle`, `_delete_selected_object`,
`_commit_free_rotation`, `_rotate_selected_object`, `_normalize_object_rotation_angle`,
`_rotate_selected_object_absolute`, `_next_right_angle_rotation` (staticmethod), `_rotate_selected_object_to_next_right_angle`,
`_add_object_rotation_actions`, `_show_object_rotation_menu`.

**MIGRATE — 27 instance attrs** into the manager `__init__` (delete from PDFView `__init__` 544-560):
`_selected_object_info`, `_selected_object_infos`, `_selected_object_page_idx`,
`_object_selection_rect_item`, `_object_rotate_handle_item`, `_object_resize_handle_items`,
`_object_drag_{pending,active,start_scene_pos,start_doc_rect,start_doc_rects,preview_rect,preview_rects,page_idx}`,
`_object_rotate_{pending,active,center_scene,start_angle,start_rotation,preview_angle}`,
`_object_resize_{pending,active,start_scene_pos,start_doc_rect,preview_rect,handle_anchor}`.
⚠ The **6 `_object_resize_*` attrs are NOT in PDFView `__init__`** today (first set at press, :2927-2932) —
the manager **must** init all 6 to `None`/`False` to avoid `AttributeError` on an early release.

**Facade — 3 methods** so the mouse handlers delegate WITHOUT inline-splitting (plan blocker; R3.8 owns the
handler refactor). Each returns `bool` (`True` = consumed → handler does `event.accept(); return`):
- `handle_press(scene_pos, event)` ← `_mouse_press` object branch (:2918-3014: resize/rotate handle hit → select/multi-select)
- `handle_move(scene_pos, event)` ← `_mouse_move` object branch (:3133-3246: resize/rotate/drag previews + browse-mode object-drag clamp)
- `handle_release(scene_pos, event)` ← `_mouse_release` object branch (:4344-4460: emit resize/rotate/move requests, rebase, clear pending)
Note the **browse-mode object-drag path** (:3213-3246, :4429-4459) touches `_object_drag_*` directly — those
reads move INTO the manager via the facade (not external).

**Signals STAY on PDFView** (class attrs :297-300 `sig_{move,delete,rotate,resize}_object`); manager emits via `self._view.sig_*`.

**Churn strategy (desync-safe, mirrors R3.5):** PDFView keeps **delegating method wrappers** for the
externally-called methods (context-menu :4674/4683/4687/4689 → `_resolve_object_info_for_context_menu_pos`/
`_select_object`/`_delete_selected_object`/`_add_object_rotation_actions`; keyPress :2246 → `_delete_selected_object`;
set_mode :1932 → `_clear_object_selection`) + **read-only `@property` forwarders** for attrs the 6 GUI tests
assert on (`test_object_{manipulation,multi_select,resize,free_rotation}_gui.py`, `test_interaction_modes.py`,
`test_autopan.py`) — chiefly `_selected_object_info` (also read by context menu :4684). Read-only forwarders are
NOT double-ownership (manager stays single source of truth). Decide per-symbol at execution via grep; add write-
forwarders only if a test mutates an attr directly.

**Transform discipline:** per moved method, classify every `self.X` — if `X` ∈ {27 migrated attrs} ∪ {20 moved
methods} → stays `self.X`; else (view attr/method: `scene`, `_render_scale`, `page_y_positions`,
`_clear_text_selection`, `sig_*`, etc.) → `self._view.X`. This is NOT a uniform replace (contrast R3.5) — needs the
symbol table above. **Invariants (preserve byte-identical):** QGraphicsItem validity (`shiboken6.isValid`), z-order
(rect/handles addRect/addEllipse z-values), hit-test geometry (`item.rect().contains(scene_pos)` — do NOT switch to
`mapFromScene`), no-jump drag parity (deltas ÷ `self._view._render_scale`), rotation transform-origin math.
**Gate:** new `test_object_selection_extraction.py` RED→GREEN; the 6 object GUI suites; AST boundary guard;
full suite; **no-jump completion-gate before/after** (selection visuals render to the scene).

**AS-BUILT (R3.6 LANDED — approach X, lower-risk method-only extraction):** Moved the 20 methods +
`absolute_rotation_from_drag` into `view/object_selection.py`; the manager reads/writes view state via
`self._view`. **Deferred to R3.8:** migrating the 26 state attrs into the manager + the `handle_*` facade —
those are coupled to the mouse-handler refactor, so the 26 attrs and the three handlers stay UNCHANGED on
PDFView for now (no temporary property-forwarder scaffold). Transform is **UNIFORM** `self.X → self._view.X`
for ALL X (incl. inter-method calls — they dispatch through the PDFView wrappers, preserving monkeypatch
semantics, e.g. tests patch `view._update_object_selection_visuals` / `view._point_hits_object_*`); two
non-obvious extras the dotted regex missed/needed: `(get|set|has)attr(self, "…")` receivers also rewritten to
`self._view`, and the `_next_right_angle_rotation` PDFView wrapper is a `@staticmethod` (tests call it unbound).
PDFView keeps 20 delegating wrappers + eager construct + `_ensure_object_selection_manager()`. `pdf_view`
4411→… (5481→5158 LOC). Zero test churn. Gates green: object suites 59p, full suite 1387p (1 unrelated print
heartbeat flake, passes in isolation), ruff 0, no-jump before/after.

### R3.7 — `view/text_selection.py` `TextSelectionManager(view)` ✅ LANDED (approach X, 3-model + source-verified)
**MOVE — 12 methods** (3 non-contiguous source regions; `_zoom_relative`/`_start_text_edit_from_hit`
interleave as STAY): `_selected_text_has_context` (1791), then `_start_text_selection`,
`_update_text_selection`, `_finalize_text_selection`, `_selection_doc_rect_to_scene` (rendering helper —
Gemini's catch, called only intra-cluster), `_clear_text_selection_extra_rects`,
`_render_text_selection_line_rects`, `_clear_text_selection`, `_resolve_text_info_for_doc_rect`,
`_resolve_text_info_for_context_menu_pos`, `_select_all_text_on_current_page` (3453-3729 block), and
`_copy_selected_text_to_clipboard` (3763-3781). No staticmethods/properties in the set.

**STAY:** `_sync_text_property_panel_state` (1800 — called by BOTH text methods AND non-text code 1716/1982,
so cross-cutting; moved methods reach it via `self._view`); `_update_browse_hover_cursor`/`_reset_browse_hover_cursor`
(3295/3323, browse-hover feedback, outside the cluster); the three mouse handlers; all ~17 state attrs
(`_text_selection_*`, `_selected_text_*`). **No Qt signals** (copy uses `QApplication.clipboard()`).

**Wrappers:** PDFView keeps 1-line delegating wrappers for all 12 + `_ensure_text_selection_manager()` lazy
accessor. Mandatory because external callers exist: **controller** (`controller/pdf_controller.py:791`
`self.view._clear_text_selection()`), set_mode/document-reset/scene-rebuild (`_clear_text_selection` ~11 refs),
context menu (`_resolve_text_info_for_context_menu_pos`, `_selected_text_has_context`), **QAction `triggered`
bindings** for Ctrl+A/Ctrl+C (`_select_all_text_on_current_page`, `_copy_selected_text_to_clipboard` at 1354/4351/4363),
and tests that call/monkeypatch these on PDFView.

**Transform:** UNIFORM `self.X → self._view.X` for ALL X (inter-method calls route through the wrappers →
monkeypatch-safe) + `(get|set|has)attr(self,"X") → (…)(self._view,…)` (notably `getattr(self,"_selected_text_from_drag")`
in the copy fallback guard). No-cycle import (manager imports nothing from pdf_view at runtime; mirrors the templates).
**Verbatim move:** kept the `if item.scene():` cleanup guards. **DEFERRED finding:** unlike ObjectSelectionManager,
text selection lacks `shiboken6.isValid()` guards on the rect/extra-rect cleanup — hardening is a follow-up, NOT done
here (no logic drift in a no-op move). **R3.8 high-risk attrs to migrate:** `_selected_text_rect_doc` + `_selected_text_cached`
(read by non-text code — mouse_press blank-click guard, context menu, panel-sync predicate).
**pdf_view 5152→4894 LOC. ZERO test churn.** Gates: new `test_text_selection_extraction.py` RED→GREEN; text/object
GUI suites 101p; full suite; production ruff 0; **no-jump completion-gate before/after.**

### R3.8 — Mouse-handler dispatcher (LAST view artifact) — SPLIT into R3.8a (DONE) + R3.8b (DEFERRED)
The 3-model review (Gemini dual-lens + Codex, both confirmed) **split R3.8** into two orthogonal failure
domains: state-ownership desync (R3.8a) vs handler-ordering/Qt-event drift (R3.8b). **User decision
(2026-06-17): do R3.8a only; defer R3.8b; document its context + landmines here.**

#### R3.8a — interaction-state migration ✅ LANDED (gate-verified)
Migrated all **43 interaction-state attrs** out of `PDFView.__init__` into the two managers' `__init__`
(real storage): 17 text (`_text_selection_*`, `_selected_text_*`, `_browse_text_cursor_active`) →
`TextSelectionManager`; 26 object (`_selected_object_*`, `_object_drag_*`, `_object_rotate_*`,
`_object_resize_*`) → `ObjectSelectionManager` (incl. the 9 that were never in `__init__` — the
`_object_resize_*` family + `_selected_object_infos`/`_selected_object_page_idx` — first-set in handlers;
defaults taken from `_clear_object_selection`). PDFView keeps **get/set `@property` forwarders** for all 43,
proxying to the manager **via the lazy accessor** (`_ensure_*_manager()`) so `PDFView.__new__()` test doubles
and any pre-construction access still work. Manager bodies changed `self._view._<attr>` → `self._<attr>`
(word-boundary exact) for the migrated names only; everything else (`scene`, `_render_scale`, `current_mode`,
`_sync_text_property_panel_state`, signals, …) still goes through `self._view`. Handlers stay byte-identical;
the only intended behavior delta is **none** — the gate proves it (pure state-binding: a desync fails pixel
parity / the full suite). Forwarders are NOT double-ownership (manager = single source of truth). pdf_view
shrank by the 34 removed init lines; +43 forwarder property pairs. ZERO test churn. **R3.8b will drop the
forwarders** once the handler branches move into the managers.

#### R3.8b — per-mode dispatcher (DEFERRED — needs interaction tests / manual QA)
**Why deferred:** both Gemini lenses AND Codex independently concluded the 377-case **pixel-parity + model
suite STRUCTURALLY CANNOT validate this refactor** — it asserts end-state rendering and is blind to Qt
event-routing mechanics (`accept()`/`ignore()` propagation to `QGraphicsView`, autopan `QTimer` + mouse-leave,
drag-vs-click `startDragDistance` thresholds, `super().mouseMoveEvent` fallthrough, mode-priority on
overlapping hits). R3.8b requires **dedicated `pytest-qt` interaction tests** (assert `event.isAccepted()`
after `qtbot.mousePress→mouseMove→mouseRelease` sequences) AND/OR **manual human verification** for
autopan, drag-out-of-bounds text selection, and overlapping object/handle hits. R3.8b is also **largely
cosmetic** — the handlers already delegate method *calls* to the managers (R3.6/R3.7); R3.8b only relocates
branch *bodies*, so functional behavior is identical either way.

**Procedure when resumed (Strangler-Fig / Boolean-consumption contract):** add
`handle_press/move/release(scene_pos, event) -> bool` to each manager; lift ONE mode-branch at a time,
keeping its existing `event.accept()` calls INSIDE the branch (do NOT centralize accept/ignore — there are
NO `event.ignore()` calls in these handlers); in the handler, replace the lifted branch with
`if self._<mgr>.handle_*(scene_pos, event): return` slotted at the EXACT same position in the if/elif chain;
test + gate + commit per mode. Then drop the R3.8a forwarders only after `rg` shows no remaining direct
PDFView state reads in handlers / context menu / property panel / hover-cursor helpers / tests.

**Branch boundaries (Codex, line-grounded at R3.8a HEAD — RE-VERIFY after edits):**
- `_mouse_press` (2869-3101): STAY = autopan 2870-2882, `scene_pos`/left-gate 2883-2884, `add_annotation`
  2885-2890 (returns WITHOUT accept), `add_text` 3010-3028, `edit_text` 3030-3090, `rect` 3091-3098,
  `highlight` 3099-3100, fallback 3101. → `ObjectSelectionManager.handle_press` = 2892-2991 (`objects`/`text_edit`;
  True only at the accepts 2910/2935/2990). → `TextSelectionManager.handle_press` = browse block 2993-3009
  (True only when selection starts + accepts at 3005; False if it only clears stale text at 3007-3008).
- `_mouse_move` (3103-3751): STAY = autopan 3104-3107, browse hover-cursor 3228-3231, edit/add-text drag+hover
  3232-3280, rect preview 3281-3284, fallback 3286. → `ObjectSelectionManager.handle_move` = 3110-3188
  (`objects`/`text_edit`/`edit_text`) + browse object-drag 3190-3223 (True at accepts 3131/3147/3187/3222). →
  `TextSelectionManager.handle_move` = active browse text-selection 3224-3227 (True at accept 3226).
- `_mouse_release` (3752-3955): STAY = autopan 3753-3755, edit/add-text release 3880-3923 (returns WITHOUT
  accept), rect/highlight/fallback 3925-3955. → `ObjectSelectionManager.handle_release` = 3757-3840
  (`objects`/`text_edit`) + browse selected-object release 3842-3873 (True at 3776/3788/3814/3834/3839/3847/3868/3872).
  → `TextSelectionManager.handle_release` = 3874-3878 (True at accept 3877).

**Codex's 10 CRITICAL LANDMINES for R3.8b (do NOT lose these):**
1. **`_object_resize_*` + `_object_resize_handle_items` were NOT in `__init__`** (first-set in `_mouse_press`).
   (R3.8a already initializes them in the manager `__init__` — but any getter/`hasattr` path must stay robust.)
2. **`text_edit` vs `edit_text` inconsistency:** `set_mode()` normalizes inbound `"text_edit"`→`"edit_text"`
   (1894-1895), but press/release guard on `("objects","text_edit")` while move guards on
   `("objects","text_edit","edit_text")`. **Preserve each tuple EXACTLY — do not simplify.**
3. **Accept behavior is intentionally UNEVEN:** `add_annotation`, `add_text`, and edit-text release paths
   return WITHOUT `event.accept()`, deliberately letting `QGraphicsView` run. Wrapping them in a
   `bool consumed` return and only calling `super()` when `not consumed` would **silently swallow that
   fallthrough**. Keep the `super()` call unconditional where the original falls through.
4. **Autopan (2870-2882) is unconditional** (all buttons, any mode) and interacts with
   `_autopan_suppress_next_context_menu`/`_autopan_manual_menu` (4082-4085). **Never wrap autopan into a manager.**
5. **Object/text mutual-exclusion clears are manual + repeated** (2903, 2917, 2968-2973; browse stale-text
   clear 3007-3008). Factoring into one "clear the other" call risks dropping a redundant-but-necessary clear.
6. **`scene.clear()` (2372/2611/2683) invalidates manager item pointers.** Object mgr guards with
   `shiboken6.isValid()`; text mgr uses `item.scene()`. Clear manager item refs BEFORE `scene.clear()` or verify
   the guards survive. (See also the R3.7 deferred `shiboken6.isValid` hardening for text.)
7. **`PDFView.__new__` test doubles** lack `_obj_sel_mgr`/`_text_sel_mgr`; property getters must lazy-init
   (R3.8a forwarders already do via `_ensure_*_manager()`).
8. **Shift has two unrelated meanings:** multi-select toggle (2950, object mode) vs aspect-ratio resize lock
   (3125, resize active). Do NOT unify.
9. **Release paths emit a model mutation then immediately rebase the overlay** (3773/3812/3831). The rebase must
   stay adjacent to the emit INSIDE the manager, or be explicitly re-triggered in the dispatcher after the
   delegate — else overlays go stale until next render.
10. **Browse object-drag (3208-3219) clamps to page bounds; objects/text_edit drag preview (3155-3188) does
    NOT.** They are functionally different — do NOT merge into one manager drag method.

**Verification-gap test files to extend first:** `test_interaction_modes.py`, `test_autopan.py`,
`test_object_{manipulation,resize,free_rotation,multi_select}_gui.py`, `test_browse_selection_gui_regressions.py`,
`test_scene_context_menu.py`. New coverage needed: overlapping-hit priority (resize-handle vs rotate-handle vs
body vs text), drag-threshold boundary, accept/ignore propagation, autopan timer + mouse-leave.

### DO-NOT-TOUCH in R3
- The model **session/legacy-shadow accessor layer** (`pdf_model.py:267-668`) — every core
  property branches on `_active_session()` vs `_legacy_*`; it is the dependency root every other
  model seam reads through. Consolidating the `_legacy_*` shadow into a default `DocumentSession`
  is a **separate post-R3 phase** with its own migration.
- Internal splitting of `_apply_redact_insert`.

---

## Fusion Protocol Playbook

- **Per seam, BEFORE the move:** Playbook **4.1** (pre-edit review, 3-model) on the target file to
  surface invariants not to worsen.
- **For each extraction design:** Playbook **4.4** (3-model design) — fusion.py `--no-synthesize`
  for two competing facade sketches, `/codex:rescue` same prompt, synthesize per manual §3:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "I am extracting <SEAM> into <new module> behind a stable facade, mirroring the
       pdf_optimizer free-function precedent (def fn(model: PDFModel, ...)). What state must stay
       owned by the original class, what must move, and what is the single safest commit boundary?
       Flag any encryption/snapshot/signal-wiring invariant I could break." `
      --file <TARGET_FILE> --no-synthesize
  # then /codex:rescue with the same prompt + file, then synthesize.
  ```
- **After each move:** Playbook **4.5** (3-model test-gap) to confirm no behavior/branch was lost.

## Verification & Gatekeeping

```powershell
# Per seam: targeted suite green, then full suite, then the boundary guards from R2:
.venv\Scripts\python.exe -m pytest test_scripts/test_edit_text_helpers.py test_scripts/test_char_run_reconstruction.py -v   # R3.1/R3.5
.venv\Scripts\python.exe -m pytest test_scripts/test_object_manipulation_gui.py test_scripts/test_native_pdf_images_model.py -v  # R3.4/R3.6
.venv\Scripts\python.exe -m pytest test_scripts/test_search_worker_flow.py test_scripts/test_ocr_controller_flow.py test_scripts/test_print_controller_flow.py -v  # R3.2
.venv\Scripts\python.exe scripts/verify_no_jump.py --skip-signoff                  # after R3.5
.venv\Scripts\python.exe -m pytest test_scripts/test_layer_boundaries.py test_scripts/test_xref_repair.py -v  # invariants intact
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider  # full green per seam
```

**Gate:** every seam is its own commit; full suite + both AST guards + no-jump gate green before
the next seam starts. A seam that cannot stay green is reverted, not patched forward.

## Risk Triage (2→3 upgrade points)

- **Entire phase is 3-model** — every seam trips triggers #1 (state migration), #4 (new facade),
  or #5 (entangled control flow). R3.5/R3.4 additionally trip #2 (security-invariant-adjacent).
- **Vectors:** attr left on/double-owned (selection desync); reordered mode early-returns; lost
  `connect` (silent worker hang); `save/tobytes` leaving the AST guard's view; `_apply_redact_insert`
  split across commits.

## Docs (per seam commit)

- `docs/ARCHITECTURE.md`: record each new module's responsibility + facade contract (§2.1/2.3/2.4).
- `docs/PITFALLS.md`: any state-migration or signal-wiring gotcha discovered.
- `plans/refactor-R3-*.md`: tick the seam; `refactor-state.md`: update R3 sub-status.
- `CODEINDEX.md` / `.codegraph`: re-run `python .codegraph/indexer.py` after each structural move.

## Commit

One commit **per seam** (8 commits), each: `refactor: R3.<n> extract <seam> behind facade (no
behavior change)`. `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
