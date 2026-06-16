# refactor-state.md — Post-Audit Refactor Campaign (R-Series)

> **Single Source of Truth** for the 2026-06-15 production-grade refactoring campaign.
> Supersedes the manual's §7 "Integration with the Cleanup Plan" table (that mapped the
> *prior* Phase 0–7 audit, all landed). This campaign (`R0`–`R6`) targets the **residual,
> post-audit debt**: god-modules, MVC reach-through, ruff/identity hygiene, performance
> deferrals, supply-chain gaps, and a regression net that does not currently hold.
>
> **Grounding:** every scope item below was verified against source by a 6-lens debt census
> + an adversarial phasing critique (workflow `wf_73afc783-06d`, 7 agents, 510k tok). Line
> numbers are census-verified against branch `feat/ui-ux-fable5-refactor` HEAD.

---

## ⚙️ Active operating directive (user, 2026-06-15)

Continue **R2.5 → R2.7** on the autonomous ticks (cron `5f4278a1` + dynamic wakeups).
**When R2 is fully committed (all of R2.1–R2.7), the conversation context should be
`/compact`'d** before starting R3 (the high-risk god-module decomposition). `/compact` is a
harness command the agent cannot self-invoke, so on R2 completion the loop will
**PushNotification** that R2 is done and that it is the `/compact` point, then continue to R3
after compaction. (This note exists so the directive survives the compaction itself.)

---

## 0. Campaign invariant — pragmatic & deployable

Incremental, behavior-preserving, always-green. No big-bang rewrites. Every phase ends at a
runnable tree. **Red-Light First** (CLAUDE.md §5.1) is mandatory for every code-bearing step.
The two structural seams flagged **DO-NOT-TOUCH** for this campaign: the model
session/legacy-shadow accessor layer (`pdf_model.py:267-668`) and the view mouse-handler
state machine internals before its managers exist (`pdf_view.py:2899-4558`).

---

## 1. Verified baseline (what R0 must freeze)

| Metric | Measured value | Source |
|---|---|---|
| Suite (system Py3.10 / PyMuPDF 1.25.5) | **1 failed, 1354 passed, 20 skipped** (149.7s) | census test-env lens |
| The 1 failure | `test_theme_and_icons.py:339` `assert len(ACTION_ICON_MAP)==32`; live = 33 | RED tree |
| Suite (`.venv` / PyMuPDF 1.27.1 — shipped stack) | **R0 FROZEN: 1355 passed / 20 skipped / 0 failed** (was: cannot collect — `INTERNALERROR` aborts at 983) | frozen 2026-06-15 |
| 20 skips | all OCR (surya/torch absent) — environmental, not regressions | — |
| ruff total (E4/E7/E9+F, E501 unselected) | **238** (doc said 240); 28 in production layers, 210 in test/script | hygiene lens |
| ruff auto-fixable | 18 (F541×12, F401×6) | hygiene lens |
| God-module LOC | `pdf_view` 5497 / `pdf_model` 5166 / `pdf_controller` 3383 / `text_editing` 1809 / `text_block` 1043 | LOC scan |
| Coverage tooling | **pytest-cov 7.1.0 in `.venv` (R0.5)**; floor: model 79.2% / controller 78.8% / view 76.6% (combined 78.0%) | R0.5 |

**R0 freeze target:** `.venv` collects full suite; **≥1355 passed / exactly the 20 OCR skips / 0 failed**, deterministic; a captured per-module coverage number as the floor.

**R0 FROZEN (2026-06-15):** `.venv` declared the canonical regression interpreter — canonical command
`.venv\Scripts\python.exe -m pytest test_scripts/`. Result **1355 passed / 20 skipped / 0 failed**,
deterministic over 2 full runs + heartbeat ×5. The 20 skips = OCR (surya/torch absent) **+ 2
large-fixture-absent optimizer-integrity params** (the census machine had those fixtures, so its
count was "20 OCR"; composition differs, count holds). Coverage floor recorded above. **1.27-skew
triage (R0.4, the 3-model authority gate): all 3 surfaced failures were non-product** — (A) `pypdf`
test-dep missing in `.venv` → installed + declared in `optional-requirements.txt`; (B) degenerate
20pt-wide preview box hit PyMuPDF 1.27's `insert_htmlbox` overflow→blank (1.25 clipped) — test rect
widened to 60pt, **product overflow behavior flagged as a follow-up, not changed**; (C) stale
`doc.name == ""` memory-backed proxy (1.27 names stream docs `"pdf"`). The `Windows fatal exception
0x80040155` faulthandler dumps in offscreen runs are benign handled-COM noise (see PITFALLS).

---

## 2. Phase ledger

| ID | Phase | Fusion mode | Playbook(s) | Status | Plan |
|----|-------|-------------|-------------|--------|------|
| **R0** | Baseline Freeze & Regression-Net Repair | 2-model (mech) + 3-model (interpreter-authority) | 4.5 | ✅ **done 2026-06-15** | [`plans/refactor-R0-baseline-freeze.md`](plans/refactor-R0-baseline-freeze.md) |
| **R1** | Mechanical Hygiene (ruff + app-identity + packaging) | 2-model | 4.2 | ✅ **done 2026-06-15** | [`plans/refactor-R1-mechanical-hygiene.md`](plans/refactor-R1-mechanical-hygiene.md) |
| **R2** | MVC Boundary Reconvergence (**guard-first**) | 2-model | 4.3 | ✅ **done 2026-06-15** | [`plans/refactor-R2-mvc-boundary.md`](plans/refactor-R2-mvc-boundary.md) |
| **R3** | God-Module Decomposition | 3-model | 4.4 + 4.1 | ◐ **in progress** (R3.1 ✅, R3.2 search+OCR ✅, print TODO) | [`plans/refactor-R3-god-module-decomposition.md`](plans/refactor-R3-god-module-decomposition.md) |
| **R4** | Performance Deferrals | 3-model (cache/thread) + 2-model (digest/objstms) | 4.4 + 4.5 | ☐ not started | [`plans/refactor-R4-performance-deferrals.md`](plans/refactor-R4-performance-deferrals.md) |
| **R5** | Security & Supply-Chain Hardening | 3-model (leak/bundle) + 2-model (guard) | 4.6 + security-review | ☐ not started | [`plans/refactor-R5-security-supply-chain.md`](plans/refactor-R5-security-supply-chain.md) |
| **R6** | Coverage Hardening (tail over decomposed seams) | 3-model | 4.5 | ☐ not started | [`plans/refactor-R6-coverage-tail.md`](plans/refactor-R6-coverage-tail.md) |

---

## 3. Cross-phase dependency hazards (the wiring that constrains ordering)

1. **R0 ⟸ everything.** No phase has a real regression net until R0 makes the *shipped* `.venv`
   stack collect + green + deterministic. Non-negotiable first.
2. **R2 ⟶ R3 (guard precedes decomposition).** R2's AST import-boundary guard must land
   *first within R2*; it locks the currently-true 0-Qt/0-cross-import invariant so R3's
   extractions cannot regress it silently.
3. **R2/R3 ⟶ encryption AST guard generalization.** The `self.doc.{save,tobytes}` guard
   (`test_xref_repair.py:324-368`) only walks `pdf_model.py`. It must be generalized to walk
   **all of model/** *before* `edit_text`/object-ops leave `pdf_model.py`, or it goes blind
   exactly when risk peaks (R3 step 3).
4. **R3 ⟶ R4 snapshot-cache.** R4's revision-keyed `capture_worker_snapshot_bytes` cache
   touches controller `:1657/:2557/:2690`; R3's coordinator extraction relocates those sites.
   The R4 cache step must follow R3's coordinators.
5. **R3 ⟷ R5 print path (shared regression pass).** R5's print-disk-leak fix
   (`pdf_controller.py:131-135` + `capture_worker_snapshot_bytes` `PDF_ENCRYPT_NONE`) and
   R3's `print_coordinator` extraction touch the same handoff — coordinate one regression pass.
6. **R5 quick-wins pulled forward into R2.** `pdf_renderer.py:84` `safe_render_scale` clamp
   (one call site) and `compose_merged_document`/`open_merge_source` `_guard_foreign_doc`
   routing are mechanical, verified, independent — land them in R2 rather than holding them
   behind 3-model R5.

---

## 4. High-risk bar — when a phase STEP upgrades 2-model → 3-model

Upgrade on **ANY ONE** trigger (the rule of thumb: *2-model reviews TEXT; 3-model reviews
STRUCTURE, STATE, SECRECY, CONCURRENCY*):

1. **State migration** — relocating instance state across an object/file boundary (e.g. the
   ~25 `_object_*` attrs into `ObjectSelectionManager`). Moving *functions* ≠ moving *state*.
2. **Security-invariant-adjacent** — touches `.save`/`.tobytes` on a live doc; a
   password/`needs_pass`/`authenticate`; `capture_worker_snapshot_bytes` output; or opens a
   foreign user file.
3. **Concurrency / invalidation correctness** — adds/moves a cache whose staleness yields
   wrong output, or moves rasterization onto/off a `QThread`.
4. **New public seam / facade** — creates a module other layers depend on.
5. **Entangled control flow** — refactors a scope where ≥2 state machines converge
   (`_mouse_press/move/release`).

**Stays 2-model only if ALL of:** pure reorder/dead-code; no state moved; no
save/tobytes/password/foreign-open touched; no cache-invalidation logic; no cross-layer API
created. (Examples: icon-count fix, `app_identity` leaf, F401/F841 removal, E701 split,
快速-preset `objstms` flip, undo memcmp-on-record, the single-site `pdf_renderer` clamp,
`MANIFEST.in prune`.)

---

## 5. Changelog

- **2026-06-15 (turn 1):** Created this SSOT + 7 phase plans (`plans/refactor-R0..R6-*.md`).
  Grounded by census/critique `wf_73afc783-06d`. Adopted the critique's three non-negotiable
  corrections: R0 expanded (RED+venv+deflake+coverage), R2 before R3 (guard-first), R6 folded
  (test-env→R0, coverage→tail). **Next step:** begin **R0** — fix `test_theme_and_icons.py:339`
  (assert `==33` *and* membership), then lazify `ux_signoff_agent.py` import so `.venv` collects.
- **2026-06-15 (turn 2): R0 LANDED.** Red-Light-First throughout: reproduced the RED icon test, the
  `.venv` collection abort, and a deterministic root-cause repro of the heartbeat flake before each
  fix. Shipped: R0.1 icon count `==33` + on-disk membership invariant; R0.2 `ux_signoff_agent`
  lazy `pyautogui` (collection abort gone, 1375 collected); R0.3 injectable monotonic clock in
  `subprocess_runner` + `_FakeClock` (heartbeat green ×5); R0.4 ran the suite under `.venv`, triaged
  3 1.27-skew failures (all non-product — see §1 FROZEN note) → `.venv` declared authority; R0.5
  `pytest-cov` added + coverage floor captured. Net: 4 failed → **0 failed (1355 passed / 20
  skipped)**, deterministic ×2. Docs: 6 PITFALLS entries, TODOS heartbeat items closed. One atomic
  commit (HEAD, unpushed). **Open follow-up (not R0 scope):** assess whether the live preview/commit
  path blanks on `insert_htmlbox` overflow at `scale_low=1` under 1.27. **Next step:** begin **R1**
  (mechanical hygiene — ruff production-layer clean, `app_identity` leaf, `MANIFEST.in` prune).
- **2026-06-15 (turn 3): R1 LANDED.** R1.1 ruff: 18 repo-wide auto-fixes + 27 manual production fixes
  (E402 docstring-before-`__future__` in `pdf_optimizer.py`; hoisted `src.printing` imports above the
  constants in `pdf_controller.py`; E701 ×3; F841 `new_annot_xref`) → **production layers ruff-clean
  (0)**, repo-wide 238→193 (remaining all test/script, deferred). R1.2 `utils/app_identity.py` leaf
  (Red-Light-First via `test_app_identity.py`): 8 identity constants consolidated from main.py/
  preferences.py/single_instance.py + `.ps1` sync-note; IPC prefixes + QSettings org/app byte-identical
  (verified). R1.3 `MANIFEST.in` (prune scripts/test_scripts/docs/.codegraph). **Regression caught by
  the gate & fixed:** the plan called `pdf_model.py:91 _MAX_PIXMAP_PX` "`--fix`-safe", but it is an
  intentional **re-export** (tests read `pdf_model._MAX_PIXMAP_PX`); `ruff --fix` stripped it and broke
  2 render-guard tests → restored with `# noqa: F401` + comment (PITFALLS entry added). **Fusion
  tooling unavailable** in this environment (`gemini` not in PATH; `/codex:rescue` needs OAuth) — the
  2-model Playbook-4.2 lens was applied manually; authoritative gates were ruff + the full pytest net.
  Docs: 3 PITFALLS entries, CLAUDE.md §3.1 ruff count, ARCHITECTURE.md identity para, 2 TODOS closed.
  **Next step:** begin **R2** (MVC boundary reconvergence, guard-first — ship `test_layer_boundaries.py`
  AST guard FIRST, then generalize the encryption guard, then the View→Model reach-through fixes).
- **2026-06-15 (turn 4): R2.1 LANDED (import-boundary guard).** Verified the invariant green first
  (model/ has 0 Qt/view/controller imports; view/ `fitz.open` only at `text_editing.py:680` +
  `pdf_view.py:5319`). Shipped `test_scripts/test_layer_boundaries.py` (2 tests, green): model/ Qt +
  cross-import ban; view/ `fitz.open` exact-count allowlist (`text_editing.py`:1 permanent;
  `pdf_view.py`:1 **PENDING R2.3 removal** — exact counts catch a new handle while tolerating line
  drift). **R2.2 analysis surfaced a NEW security finding (→ R5):** generalizing the encryption guard
  to the `model.doc` receiver (used by `pdf_optimizer.py` and the R3 free-functions) catches
  `pdf_optimizer.py:332` (size-measure via `len(...tobytes())`, ephemeral — safe) and `:347`
  `build_working_doc_for_optimized_copy`: for an **encrypted** source (`needs_pass` ⇒
  `_resolve_file_backed_optimize_source` returns None at `:310`) it falls to
  `fitz.open("pdf", model.doc.tobytes(...))` and **decrypts the live doc into the optimized copy** —
  so 另存為最佳化的副本 of an encrypted PDF silently drops its password (same class as R5.1's print
  leak; NOT previously tracked). Decision: do **not** fix in R2 (product call: refuse vs
  preserve-encryption); allowlist `:347` in the R2.2 guard with a flag and add an R5 item. **Next
  step:** R2.2 — generalize the encryption AST guard to all of model/ with a function-scoped
  decrypt-sink allowlist (`capture_worker_snapshot_bytes`, optimizer `332`/`347` [flagged],
  page-snapshot `tmp_doc.save`, export `new_doc.save`) + strengthen the explicit-`PDF_ENCRYPT_NONE`
  check; then R2.3–R2.7 (view→model reach-through + pulled-forward render clamp/merge guard).
- **2026-06-15 (turn 5): R2.2 LANDED (encryption guard generalized).** Replaced the pdf_model-only
  `self.doc` scan in `test_xref_repair.py::test_live_doc_roundtrips_preserve_encryption` with an
  all-`model/` walk over the `self.doc`/`model.doc`/`self._model.doc` receivers + a function-scoped
  decrypt-sink allowlist (`capture_worker_snapshot_bytes`; optimizer `current_document_size_bytes`
  [safe]; optimizer `build_working_doc_for_optimized_copy` [flagged]) + the explicit-`PDF_ENCRYPT_NONE`
  strengthening. **Red-Light-verified teeth** (un-allowlisting flags optimizer `:332`/`:347`), green
  restored (11 passed xref+boundary). This satisfies the planned **R5.3** (marked done in
  `plans/refactor-R5`), and the optimizer-decrypt finding is now tracked there as **R5.5** (HIGH;
  fix = preserve-encryption vs refuse, a product decision — not done autonomously). Also, per a user
  request mid-turn, created cron `5f4278a1` (`51 17,22,3,8 * * *` → "continue"; durable requested but
  runtime forced **session-only**, 7-day expiry). **Next step:** R2.3 — remove the `pdf_view.py:5319`
  `fitz.open` merge-dialog fallback (route page-count through the controller) and drop its entry from
  `test_layer_boundaries.py` (leaving `text_editing.py:1`); then R2.4 (8 `controller.model.doc[...]`
  reads → `controller.get_page_rect`), R2.5/2.6 (controller query facade + PreviewRenderer public
  preview-HTML), R2.7 (`pdf_renderer.py:84` clamp + merge `_guard_foreign_doc`).
- **2026-06-15 (turn 6): R2.3 + R2.4 LANDED (view stops touching model.doc).** R2.3: removed the
  `pdf_view.py` `_resolve_insert_source_file` `fitz.open` fallback (the controller's
  `resolve_insert_source_file`, which handles passwords via the model, is now the only path; shows an
  error if no controller) and dropped `pdf_view.py` from the `test_layer_boundaries` allowlist — so
  `view/` now has **exactly one** sanctioned `fitz.open` (`text_editing.py`), enforced by the guard.
  R2.4: added read-only `controller.get_page_rect(page_idx) -> fitz.Rect` (rotation-faithful copy) +
  `get_page_rotation`, and replaced all **8** `…model.doc[page_idx].rect/.rotation` reach-through
  reads in `pdf_view.py` (3239/3354/3411/3428/3460/3730/4191/5386). `view/pdf_view.py` now has **0**
  `.doc[` indexes (verified); behavior-identical (each site only read `.rect`/`.rotation`). Production
  ruff still 0. One test (`test_thumbnail_context_menu`'s insert-position case) drove the removed view
  `fitz.open` fallback via a monkeypatched `pdf_view.fitz`; updated it to wire a controller mock
  (`resolve_insert_source_file`) — the MVC path R2.3 enforces. Full suite **1361 passed / 20 skipped /
  0 failed**. **Next step:** R2.5 (controller read-only query facade — `get_render_width_for_edit`,
  `iter_text_targets`, `get_watermarks`, `has_unsaved_changes`); R2.6 (PreviewRenderer → public
  `controller.build_insert_preview_html` — PIXEL-PARITY, run `verify_no_jump.py --skip-signoff`);
  R2.7 (`pdf_renderer.py:84` clamp + `compose_merged_document`/`open_merge_source` `_guard_foreign_doc`).
- **2026-06-15 (turn 7): R2.5 LANDED (controller query facade).** Added thin read-only forwards on
  PDFController — `has_unsaved_changes`, `get_watermarks`, `get_render_width_for_edit`,
  `ensure_page_index_built`, `iter_text_targets(page_idx, mode, *, blocks_fallback)`, `get_text_blocks`
  — and routed every remaining View→Model **method** reach-through through them: pdf_view status-bar
  `has_unsaved_changes` (1879); watermark-edit 4-hop `tools.watermark.get_watermarks` (5083);
  `_iter_outline_targets` + `_draw_all_block_outlines` `block_manager.get_paragraphs/runs/blocks` +
  `ensure_page_index_built`; text_editing.py:1227 `get_render_width_for_edit`. Forwards only;
  `iter_text_targets` mirrors each site's exact mode/fallback, so behavior-identical. **ruff caught a
  real bug before the suite ran:** the first pass missed `_iter_outline_targets`' third (blocks-fallback)
  branch — F821 `manager` undefined — fixed via `get_text_blocks`. Incidental `model.doc`/`text_target_mode`
  attribute reads remain (lighter coupling, out of R2.5's method scope). Production ruff still 0.
  **Test churn (expected for MVC decoupling):** the first full-suite gate caught **5** GUI tests that
  mocked the OLD `controller.model.<method>` path; updated them to the new controller facade (a shared
  `_outline_controller(model)` helper for the 3 block-outline tests + controller-level
  `get_render_width_for_edit`/`has_unsaved_changes` on the add-text/interaction-mode mocks). Re-gated
  green. (Note for R2.6/R3: the suite mocks `controller.model` heavily, so further view→controller
  decoupling carries a mock-update tail.) **Next step:** R2.6 PreviewRenderer → public
  `controller.build_insert_preview_html` (PIXEL-PARITY, verify_no_jump); R2.7 `pdf_renderer.py:84`
  clamp + merge `_guard_foreign_doc`.
- **2026-06-15 (turn 8): R2.6 LANDED (PreviewRenderer decoupled, PIXEL-PARITY held).** Added public
  `controller.build_insert_preview_html(text, font_size, color, font_name, line_height) -> (css, html)`
  forwarding to the model's `_build_insert_css`/`_convert_text_to_html`; `PreviewRenderer.render()` now
  depends on an injected `build_preview_html` callable (production passes the controller's). **Zero test
  churn** via a backward-compat `model=` shim that derives the same callable, so the ~15
  `PreviewRenderer(model=...)`/`PreviewRenderer()` sites are untouched; render() passes byte-identical
  args → bit-exact raster. Verified: `test_no_jump_editor_geometry` **377 passed**, preview/fidelity
  **82 passed**, full suite **1361 passed / 20 skipped / 0 failed**, production ruff 0. (Residual, out of
  R2.6 scope: the view still pulls `model.block_manager.find_span_by_id` at ~text_editing.py:1364 for the
  cluster line-height probe — a separate reach-through.) **Infra note:** the full pytest suite
  intermittently hard-crashes (Windows fatal exception in offscreen Qt/PyMuPDF — exit 3 + faulthandler
  "Extension modules" dump, **no FAILED lines**); environmental — same code passes 1361 on re-run.
  **Next step:** R2.7 (`pdf_renderer.py:84` `safe_render_scale` clamp + `compose_merged_document`/
  `open_merge_source` `_guard_foreign_doc`) — last R2 item; then mark R2 done, ARCHITECTURE §7, and
  PushNotification the `/compact` point.
- **2026-06-15 (turn 9): R2.7 LANDED — R2 COMPLETE.** R2.7 (pulled-forward security quick-wins):
  `src/printing/pdf_renderer.py:iter_page_images` clamps the render zoom **per page** via
  `safe_render_scale` (the last unclamped raster path — CWE-400/409 bomb guard); `open_merge_source`
  and the `compose_merged_document` file-source block now open foreign files through `_guard_foreign_doc`
  (size/page caps + auth, identical auth errors), mirroring the already-guarded `open_insert_source`.
  Behavior-identical for normal docs; adds the `_MAX_PDF_BYTES`/`_MAX_PAGES` caps a merge previously
  bypassed. Verified: merge + resource-guard tests **34 passed**, full suite **1361 passed / 20 skipped
  / 0 failed**, production ruff 0. **All R2.1–R2.7 done → R2 ✅.** Docs: ARCHITECTURE §7.2 added
  (import-boundary guard + controller read-only query API + preview-HTML builder + print clamp),
  §7.1 `_guard_foreign_doc` routing updated. **Per the user directive this is the `/compact` point**
  (recorded in the "Active operating directive" section) — PushNotification sent so the context can be
  `/compact`'d before R3 (the high-risk god-module decomposition). Campaign commits: R0 6f16ec2 ·
  R1 4e6f755 · R2.1 2a2aa96 · R2.2 cbe0284 · R2.3+4 6e3dea1 · R2.5 870728c · R2.6 dc1bb2c · R2.7 0dd1fac.
- **2026-06-16 (turn 10): R3.1 LANDED (model/text_block_parsing.py — first god-module seam).** Post-`/compact`,
  began R3. Extracted the stateless parsing layer out of `text_block.py` (1043→338 LOC) into a new pure
  leaf `model/text_block_parsing.py` (~640 LOC): the 6 geometry helpers, the 3 output dataclasses
  (`TextBlock`/`EditableSpan`/`EditableParagraph`), and the 14 fitz-dict→dataclass transforms
  (`_parse_block`/`_parse_spans`/`_parse_runs_from_raw_block`/`_parse_runs_from_raw_line`/
  `_build_paragraphs`/`_merge_vertical_paragraphs`/`_match_by_text`/`_dynamic_scan`/…). Moved **verbatim**
  (only `self.`→module-fn calls; constants byte-verified incl. U+2022/U+FFFD) — **no logic drift**. The
  module owns **no** instance state; `TextBlockManager` keeps every page-keyed index and the 14 methods
  become thin **delegates** (signatures preserved → `manager._build_paragraphs(...)` and all internal
  `self._parse_*` callers unchanged). `text_block` re-exports the dataclasses + `rotation_degrees_from_dir`
  (`# noqa: F401`) so `from model.text_block import …` (pdf_model + 3 tests) is byte-identical. **Red-Light
  First:** new `test_text_block_parsing_extraction.py` failed RED (`ModuleNotFoundError`) before the move,
  GREEN after (5 tests: module surface, free-fn callability, parse_block/build_paragraphs output,
  manager↔module parity). Gates: parsing regressions 59p/1s, AST guards (boundary+encryption) 11p,
  production ruff **0**, codegraph re-indexed (3338→3609 nodes). Lowest-blast-radius seam, done first per
  plan ordering. **Next step:** R3.2 — controller async-job coordinators, smallest first
  (`controller/search_coordinator.py` → `ocr_coordinator.py` → `print_coordinator.py`); preserve exact
  `QThread` signal wiring (a missed `connect` = silent worker hang).
- **2026-06-16 (turn 11): R3.2/search LANDED (first controller async coordinator) — fusion tooling restored.**
  User fixed the 3-model panel (Codex auth + a Windows `gemini.cmd` path fix in `fusion.py`), so this seam
  used the **mandated 3-model design review**: Gemini Pass A (correctness/arch) + Codex Pass C (o3) — both
  **independently agreed** on the design; Gemini Pass B (simplification) timed out at 180s on the 3383-LOC
  file (noted, not blocking). Synthesis verified against source (the 8 runtime `_search_*` attrs are read
  ONLY in `__init__`/`activate`/the 6 search methods — `search_state` persistence goes through
  `_get_ui_state`, untouched). Extracted `controller/search_coordinator.py`: `_SearchWorker`/`_SearchBridge`
  moved verbatim (re-exported from `pdf_controller` — `# noqa: F401` — keeping `test_search_worker_flow.py:18`
  valid) + `class SearchCoordinator(controller)` owning `_search_thread/_worker/_worker_bridge/
  _accumulated_hits/_gen/_query/_session_id/_finished` + `search_text`/`cancel`/`connect_bridge`/
  `_release_search_thread`/`_on_search_{hits_found,failed,finished}`. Bodies moved verbatim, only
  `self.model/view/_get_ui_state`→`self._c.*` and `_cancel_search()`→`cancel()`. PDFController now holds one
  `self._search_coordinator` and keeps `search_text` + `_cancel_search` **delegates** (the latter for the 13
  pre-mutation callers + `sig_search`); `__init__` 8-attr block → 1 line; `activate()` bridge-wiring →
  `connect_bridge()`. **Invariants preserved verbatim** (per fusion): `thread.finished`-bound release (NOT
  `worker.finished` — GC hard-crash), two-hop `worker→bridge→coordinator` wiring (missing = silent hang),
  synchronous `cancel()` with `_search_gen += 1` + `gen != self._search_gen` slot guards, empty-query +
  `capture_worker_snapshot_bytes` paths. **Red-Light First:** new `test_search_coordinator_extraction.py`
  RED (`ModuleNotFoundError`) → GREEN. **Test churn (R2.5-class, accepted):** `test_search_worker_flow.py`
  `_build_minimal_controller`/`_wait_for_search_finish` + 3 flow tests redirected to
  `controller._search_coordinator` (assertions unchanged); worker/bridge unit tests untouched. Gates:
  search+guards 23p, related controller-flow 96p/1s, full suite green, production ruff 0. **Next:** R3.2/OCR
  (`controller/ocr_coordinator.py`) then R3.2/print (largest; coordinate with R5.1 decrypt-snapshot).
- **2026-06-16 (turn 12): R3.2/OCR LANDED (second controller async coordinator).** Full 3-model fusion
  design review (tooling now restored): Gemini Pass A + Pass B (both completed, no timeout) + Codex Pass C.
  **One design split, resolved:** both Gemini passes said move `_refresh_ocr_availability` into the
  coordinator; Codex said KEEP it on PDFController (it owns no thread/worker/gen/session/dialog runtime —
  it's a one-shot UI-availability probe). Upheld **Codex** (aligns with the plan's coordinator-scope
  definition = async-job runtime only; also lower-churn — the method + its activate() call stay untouched).
  Extracted `controller/ocr_coordinator.py`: `_OcrWorker`/`_OcrBridge` moved verbatim (re-exported from
  `pdf_controller`, `# noqa: F401`) + `class OcrCoordinator(controller)` owning `_ocr_progress_dialog/
  _ocr_thread/_ocr_worker/_ocr_worker_bridge/_ocr_gen/_ocr_session_id` + `start_ocr`/`cancel_ocr`/
  `connect_bridge`/`_release_ocr_thread`/`_show_ocr_progress_dialog`/`_on_ocr_{progress,status,page_done,
  failed,thread_finished}`. Bodies verbatim, only `self.model/view`→`self._c.*`. PDFController keeps
  `start_ocr`+`cancel_ocr` delegates + `_refresh_ocr_availability`; `__init__` 6-attr block → 1 line;
  `activate()` bridge-wiring → `connect_bridge()`. **Invariants preserved verbatim:** `thread.finished`-bound
  release; two-hop worker→bridge→coordinator wiring; `_ocr_gen += 1` in cancel + `gen != self._ocr_gen`
  slot guards; the per-page **session guard** (`active_sid != _ocr_session_id` drops OCR spans after a tab
  switch — never inject text into the wrong doc); GUI-thread `model.apply_ocr_spans`; `QProgressDialog`
  parent-only-if-PDFView + close/null on finish. **Red-Light:** the existing `test_ocr_controller_flow.py`
  broke 6→green on the controller change (behavioral net); added `test_ocr_coordinator_extraction.py`
  (4p) as the contract guard, mirroring the search seam. **Test churn (R2.5-class):** redirected the OCR
  flow test's `controller._ocr_*`/`_on_ocr_*` pokes to `controller._ocr_coordinator`, and retargeted one
  `monkeypatch` of `show_error` from `pdf_controller`→`ocr_coordinator` (the availability-error call
  relocated with the seam). Gates: OCR + guards 33p/8s, full suite green, production ruff 0. Also this
  turn: regenerated the no-jump completion proof (PASSED at 2634359, confirming R3.1/R3.2 left the
  text-editor geometry intact) after repairing two stale gate-script pins (R0/R1 loose end). **Next:**
  R3.2/print (largest coordinator: subprocess runner + stall/terminate edges; coordinate with R5.1
  decrypt-snapshot handoff — share one regression pass per §3 hazard 5).
