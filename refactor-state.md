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
| **R3** | God-Module Decomposition | 3-model | 4.4 + 4.1 | ✅ **done 2026-06-17** (R3.1-R3.7 ✅; R3.8a ✅ state migration; **R3.8b dispatcher DEFERRED per user** — gate can't validate Qt event-routing; context+landmines documented) | [`plans/refactor-R3-god-module-decomposition.md`](plans/refactor-R3-god-module-decomposition.md) |
| **R4** | Performance Deferrals | 3-model (cache/thread) + 2-model (digest/objstms) | 4.4 + 4.5 | ✅ **done 2026-06-17** (4/5: R4.5 objstms ✅, R4.4 undo-dedup ✅, R4.2 snapshot-bytes cache ✅, R4.3 async thumbnails ✅; **R4.1 overlay raster cache EVALUATED → DEFERRED** — all variants incorrect/high-risk/non-win, see plan + turn 28) | [`plans/refactor-R4-performance-deferrals.md`](plans/refactor-R4-performance-deferrals.md) |
| **R5** | Security & Supply-Chain Hardening | 3-model (leak/bundle) + 2-model (guard) | 4.6 + security-review | ◑ **in progress** (R5.3 ✅ in R2.2; **R5.5 optimize-copy encryption ✅** + **R5.1 print-decrypt ✅ 2026-06-18**, both Option A; R5.4 packaging guard next, R5.2 OCR bundle pending — needs out-of-band bundle) | [`plans/refactor-R5-security-supply-chain.md`](plans/refactor-R5-security-supply-chain.md) |
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
- **2026-06-16 (turn 13): R3.2/print LANDED — R3.2 COMPLETE (all 3 controller coordinators).** Full 3-model
  fusion design (Gemini A+B + Codex C, all agreed; Codex mapped the exact test-churn — its biggest
  contribution). Largest/highest-risk coordinator (subprocess runner + stall/terminate state machine +
  app-close/fullscreen coupling + the R5.1-adjacent snapshot handoff). New `controller/print_coordinator.py`:
  `_PrintSubmissionWorker`/`_PrintWorkerBridge`/`PrintJobRequest` moved verbatim (re-exported from
  `pdf_controller`, `# noqa: F401`) + `class PrintCoordinator(controller)` owning `print_dispatcher` +
  the 8 `_print_*` attrs + the dialog/status/busy helpers + stall/terminate machine + `PrintSubprocessRunner`
  lifecycle + all `_on_print_*` + `print_document`. Bodies verbatim, only `self.{model,view,activate,
  _resolve_session_profile,_render_print_preview_image}`→`self._c.*` and `_has_active_print_submission()`→
  `has_active_job()`. **Design resolutions:** `print_dispatcher` MOVED (only print uses it; lazy-init in
  `connect_bridge()`); `_render_print_preview_image` + `handle_app_close` (→ new coordinator
  `begin_close_pending()`) + `_fullscreen_is_blocked` STAY on the controller; `print_document` +
  `_has_active_print_submission` are controller delegates. Removed 9 now-unused print imports from
  pdf_controller (`tempfile`/`uuid`/`replace`/`PrintDispatcher`/`PrintHelperTerminatedError`/`PrintingError`/
  `PrintHelperJob`/`UnifiedPrintDialog`/`PrintSubprocessRunner`) via ruff `--fix` (each verified count=1,
  no re-export — unlike the R1 `_MAX_PIXMAP_PX` incident). **Invariants verbatim:** GUI-thread
  `capture_worker_snapshot_bytes()` before `QThread.start()`, **name unchanged** (R5.1 deferred — encryption
  AST-guard chokepoint untouched); `worker→bridge→coordinator` wiring; `thread.finished`-bound release;
  stall/terminate transitions + `work_dir = Path(job.input_pdf_path).parent`; close-during-print
  suppression (view.close() only when idle); view-parented progress dialog. **Red-Light:**
  `test_print_coordinator_extraction.py` RED (`ModuleNotFoundError`) → GREEN (4 contract tests). **Test
  churn (Codex-mapped, R2.5-class):** `test_print_controller_flow.py` accesses → `controller._print_coordinator.*`,
  module patches `UnifiedPrintDialog`/`QProgressDialog`/`PrintSubprocessRunner`/`show_error`/`QMessageBox`
  retargeted `pdf_controller`→`print_coordinator` (dropped the now-unused `pdf_controller_module` alias →
  test E402 count back to baseline 7). `test_multi_tab_plan.py` `_has_active_print_submission` monkeypatch
  untouched (facade kept). Gates: print 8p, AST guards + snapshot/speed/multi_tab 85p/1s, production ruff 0.
  **R3.2 ✅ (search c66877c + OCR cc1e0f9 + print this).** Next: R3.4 (`model/pdf_object_ops.py`) → R3.5
  (`model/pdf_text_edit.py`, LAST model seam — full edit_text suite + no-jump gate before/after).
- **2026-06-16 (turn 14): R3.4/object-ops LANDED (first MODEL seam).** Extracted `model/pdf_object_ops.py`
  (~830 LOC, 19 free functions `def fn(model: PDFModel, ...)` + the moved `_APP_OBJECT_*` constants) out of
  pdf_model.py (5164→4410 LOC), mirroring the `pdf_optimizer.py` precedent. **3-model design:** Codex Pass C
  (thorough) + Gemini Pass A (focused — the full-file Gemini fusion HUNG on the 5160-LOC file, killed + re-ran
  on an extract) + my own authoritative call-graph verification, which found: (a) the OCR methods
  `apply_ocr_spans`/`_pick_ocr_font` are **interleaved** in the object-ops region and must STAY (Gemini wrongly
  grouped them as movable — Codex/I overrode); (b) the cluster is **closed** (no staying method calls a moved
  private → zero staying-code churn). **Process note:** the codex-rescue agent (run for DESIGN ONLY) overstepped
  and wrote an unrequested `pdf_object_ops.py` (incl. the OCR methods) — I **quarantined** it and did my OWN
  controlled verbatim transform via a one-shot script (dedent 4 + `self.<moved>(`→`<moved>(model,` +
  `self.`→`model.` + def-sig `self`→`model: PDFModel`), guaranteeing no-logic-drift. Caught during gating: the
  new module needed `import html as _html_mod` (a bare module-level name the moved code used); `_html_mod` ALSO
  stays in pdf_model (used by `_convert_text_to_html`/`_build_multi_style_html`). PDFModel keeps 7 public
  delegating wrappers; moved privates (no external callers) deleted. **Invariants verbatim:** free functions
  NEVER call `_capture_*`/`_restore_*` (undo = controller's boundary); `pending_edits`/`edit_count` order after
  `doc.update_stream`; `block_manager.rebuild_page` verbatim; NO `.save`/`.tobytes` (encryption guard scans
  pdf_object_ops.py — PASSED); `TYPE_CHECKING`-only PDFModel import. **Red-Light:**
  `test_pdf_object_ops_extraction.py` RED→GREEN. **Zero test churn** (8 object-ops files call the public
  wrappers). Removed 10 now-unused pdf_content_ops imports from pdf_model (ruff `--fix`, non-re-export).
  **Deferred finding** (Gemini A): some move/rotate/delete branches may omit `pending_edits` that native-image
  does — moved VERBATIM, flagged, NOT fixed. Gates: object-ops 78p (8 suites + extraction + AST guards), full
  suite green, production ruff 0, codegraph re-indexed. **Next:** R3.5 (`model/pdf_text_edit.py` — LAST +
  highest-risk model seam; DO NOT split `_apply_redact_insert`; no-jump gate before/after).
- **2026-06-16 (turn 15): R3.5 LANDED — `model/pdf_text_edit.py`, the LAST + highest-risk model seam. ALL
  model seams now done.** Full 3-model design review on a focused extract (pdf_model `2861-4190`): Gemini
  dual-lens (both passes completed) + Codex. **Source verification produced a concrete override both Gemini
  lenses missed:** they classified `_resolve_font_for_push` as MOVE, but it is called by the *staying*
  `_resolve_add_text_font` (pdf_model:2144) → it must STAY (Codex independently concurred). Extracted a
  contiguous run of **9 methods** (pdf_model `2951-4184`) into free functions `fn(model: PDFModel, ...)`:
  `_has_complex_script/_push_down_overlapping_text/_replay_protected_spans/_validate_protected_spans/
  _resolve_edit_target/_apply_redact_insert` (moved **WHOLE**, ~360 LOC, never split)`/_verify_rebuild_edit/
  _resolve_effective_target_mode/edit_text`. Two module-level helpers moved with the cluster and are
  **re-exported from pdf_model** (`_EditTextResolveResult` dataclass + `_classify_insert_path` view/model
  shared classifier — tests `from model.pdf_model import` both). **STAY** (cross-cutting consumers, reached
  via `model.`): `_resolve_font_for_push` (add-text), `_needs_cjk_font` (object-ops + monkeypatched),
  `_convert_text_to_html`/`_build_insert_css`/`_build_multi_style_html` (controller+view preview),
  `_maybe_garbage_collect` (encryption `_roundtrip_live_doc` + `test_xref_repair`), `_reauthenticate_if_needed`.
  **Transform discipline:** UNIFORM `self.`→`model.` (NOT local free-calls among the moved set) so every
  inter-method call dispatches through its PDFModel wrapper — this preserves exact bound-method/monkeypatch
  semantics (**Codex caught** `test_edit_text_helpers` monkeypatching `_push_down_overlapping_text`; a local
  free-call would have silently bypassed it and failed parity). PDFModel keeps delegating wrappers for **all 9**
  (8 generic `(*args, **kwargs)` forwarders + explicit `edit_text` signature) because the test net pokes the
  privates directly → **ZERO test churn.** pdf_model 4411→3159 LOC; BOM preserved; 5 now-unused imports
  stripped (ruff `--fix`, none re-exported). **Red-Light First:** new `test_pdf_text_edit_extraction.py` RED
  (`ModuleNotFoundError`) → GREEN. Gates: edit suites 425p (incl. monkeypatch + privates-poking + xref guard),
  AST boundary + object-ops guards 43p, full suite **1384p/20s** (clean first run), production ruff 0, **no-jump
  completion-gate PASSED before (`04b0a4c`) and after.** **Next:** R3.6 (`view/object_selection.py` — first
  view seam; migrate ~25 selection attrs into the manager; Qt Signals stay class attrs on PDFView).
- **2026-06-16 (turn 18-19): R3.6 LANDED — `view/object_selection.py` `ObjectSelectionManager`, the FIRST view
  seam.** Map first (`5179b4f`, doc-only, 3-model: Gemini dual-lens + Codex + source-verified), then the
  extraction. **Approach X (lower-risk, method-only):** moved the 20 object selection/drag/resize/free-rotation
  verbs + the pure `absolute_rotation_from_drag` (re-exported from `pdf_view`) into the manager, which reads
  view state via `self._view` and emits via `self._view.sig_*` (Signals stay PDFView class attrs). PDFView keeps
  20 delegating wrappers + eager construct + `_ensure_object_selection_manager()` lazy accessor (mirrors
  `_ensure_text_edit_manager`; needed because `set_mode` can call `_clear_object_selection` at startup).
  **Deferred to R3.8:** migrating the 26 interaction-state attrs + a `handle_press/move/release` facade — they
  are coupled to the mouse-handler refactor, so the 26 attrs and the three handlers stay UNCHANGED on PDFView
  (no temporary property-forwarder scaffold). **Transform = UNIFORM `self.X → self._view.X`** for ALL X incl.
  inter-method calls (they dispatch through the PDFView wrappers, preserving monkeypatch semantics — tests patch
  `view._update_object_selection_visuals` / `view._point_hits_object_*`). Two bugs caught by the GUI suites
  mid-extraction (RED→GREEN loop): the dotted regex missed `(get|set|has)attr(self,"X")` receivers (→ wrong
  `_delete_selected_object` result) — fixed by also rewriting those to `self._view`; and `_next_right_angle_rotation`
  is a `@staticmethod` called unbound by tests — its PDFView wrapper must be `@staticmethod` too. No-cycle import:
  manager imports nothing from pdf_view at runtime (mirrors TextEditManager); `pdf_view` imports the manager +
  re-exports the helper. **pdf_view 5481→5158 LOC. ZERO test churn.** New `test_object_selection_extraction.py`
  RED→GREEN. Gates: object suites 59p (6 GUI + interaction + autopan + AST guard), full suite 1387p/20s (1
  unrelated print-heartbeat timing flake — passes in isolation), production ruff 0, codegraph re-indexed,
  **no-jump completion-gate before/after.** **Next:** R3.7 (`view/text_selection.py` `TextSelectionManager`) —
  lower coupling now objects are out; then R3.8 (mouse-handler dispatcher + object/text state migration).
- **2026-06-17 (turn 22): R3.7 LANDED — `view/text_selection.py` `TextSelectionManager`, the SECOND view seam.**
  Full 3-model design review (Gemini dual-lens + Codex, both no timeout) + source verification, synthesized and
  executed in ONE atomic tick (no separate map commit — folded the map into this commit, avoiding R3.6's wasteful
  doc-commit gate-rebind). **Approach X again (method-only):** moved 12 browse-mode text-selection/highlight/copy
  verbs into the manager (reads view state via `self._view`); the ~17 state attrs + three mouse handlers stay on
  PDFView. **No Qt signals** (copy = `QApplication.clipboard()`). **Gemini surfaced** the `_selection_doc_rect_to_scene`
  rendering helper (not in my initial grep — its name lacks "text_selection"; called only intra-cluster → MOVE, the
  12th). **Source-verified STAY:** `_sync_text_property_panel_state` (called by both text + non-text code 1716/1982 →
  cross-cutting), `_update_browse_hover_cursor`/`_reset_browse_hover_cursor` (outside cluster). **Codex caught** the
  cross-layer caller `controller/pdf_controller.py:791` (`view._clear_text_selection()`) and the Ctrl+A/Ctrl+C
  `QAction.triggered` bindings (1354/4351/4363) → all 12 get mandatory PDFView wrappers + `_ensure_text_selection_manager()`
  lazy accessor. **UNIFORM transform** `self.X→self._view.X` + `(get|set|has)attr(self,"X")→self._view` (notably the
  `_selected_text_from_drag` copy-fallback guard). Source = 3 non-contiguous regions (1791; 3453-3729; 3763-3781) with
  `_zoom_relative`/`_start_text_edit_from_hit` interleaved as STAY. **DEFERRED finding** (flagged, NOT fixed — keeps the
  move verbatim): text cleanup uses `if item.scene():` not `shiboken6.isValid()` like ObjectSelectionManager; harden in a
  follow-up. **R3.8 highest-risk attrs to migrate:** `_selected_text_rect_doc`/`_selected_text_cached` (read by non-text
  code). The R6.6-style playbook carried over with **ZERO debugging** — contract + text/object GUI suites 101p GREEN
  first try. **pdf_view 5152→4894 LOC, ZERO test churn.** New `test_text_selection_extraction.py` RED→GREEN. Gates: full
  suite **1391p/20s** (clean first run), production ruff 0, codegraph re-indexed, **no-jump completion-gate before/after.**
  **Next:** R3.8 — the LAST view artifact: refactor `_mouse_press/move/release` into a per-mode dispatcher delegating to
  the two managers + migrate the object/text interaction state into them (preserve the `current_mode` early-return
  ordering exactly).
- **2026-06-17 (turn 24): R3.8a LANDED + R3.8b DEFERRED (user decision) → R3 COMPLETE.** Full 3-model review
  (Gemini dual-lens + Codex) on the 3 mouse handlers (~1090 LOC, 8-mode convergence). Gemini first timed out on
  the 1100-line extract (documented large-input failure) → retried with a compact structure-only prompt. **Both
  vendors independently SPLIT R3.8** into R3.8a (state-ownership) vs R3.8b (handler-ordering/Qt-event) and both
  concluded the **377-case pixel-parity + model gate STRUCTURALLY CANNOT validate R3.8b** (blind to Qt event
  routing: accept/ignore propagation, autopan QTimer, drag-vs-click thresholds, super().mouseMoveEvent fallthrough,
  overlapping-hit priority) — needs pytest-qt interaction tests + manual QA. Surfaced this as a checkpoint; **user
  chose: R3.8a only, defer R3.8b, document context + Codex's landmines, /compact when R3 done.** **R3.8a (executed,
  gate-verified):** migrated all 43 interaction-state attrs (17 text + 26 object, incl. the 9 never-in-__init__
  `_object_resize_*`/`_selected_object_infos`/`_selected_object_page_idx`) out of `PDFView.__init__` into the two
  managers' `__init__`; PDFView keeps get/set `@property` forwarders for all 43 proxying via the lazy accessors
  (so `__new__` test doubles + pre-construction access work). Manager bodies `self._view._<attr>` → `self._<attr>`
  (word-boundary exact) for migrated names only. Handlers byte-identical. One transform bug caught + fixed: the
  8-space init-line removal matched a 20-space handler substring (`str.replace` corruption) → anchored removal with
  a leading `\n` + asserted exactly 34 lines removed. ZERO test churn. **R3.8b fully documented** in the plan
  (branch boundaries, Strangler-Fig/Boolean-consumption procedure, Codex's 10 landmines, the verification-gap test
  files). Gates: interaction GUI suites 130p, full suite **1391p/20s** (clean), production ruff 0, codegraph
  re-indexed, **no-jump completion-gate before/after.** **R3 COMPLETE** (R3.1-R3.7 + R3.8a; R3.8b deferred). **Next:**
  per user, `/compact`, then R4 (performance deferrals).
- **2026-06-17 (turn 25): R4 BEGUN — R4.5 LANDED (快速 preset objstms flip, the lowest-risk R4 item).** Post-`/compact`,
  re-indexed codegraph (3338→3762 nodes), froze the `.venv` baseline GREEN (**1391p/20s**), then started R4 with
  the most-mechanical item (2-model class). **Census confirmed the scope was narrower than the original deferral
  note claimed:** of the three presets, `平衡` already had `use_object_streams=True`, and `極致壓縮` is structurally
  blocked (`linearize=True` → `normalize_optimize_options:250-252` strips objstms), so **only `快速`
  (`linearize=False`) was a genuine opportunity.** Flipped `use_object_streams=False → True` in
  `preset_optimize_options` (`pdf_optimizer.py:229`). **Red-Light First:** new
  `test_pdf_optimize_workflow.py::test_fast_preset_enables_object_streams` proves the full chain (preset True →
  survives `normalize_optimize_options` → reaches `fast_save_kwargs` as `use_objstms=1`), RED before the flip
  (`assert False is True`) → GREEN after. The two capability-gate tests (928/942) assert `use_object_streams is
  False` for the *gated* dialog (preset 平衡/極致壓縮 with `object_streams:False` capability) — verified unaffected.
  Gates: optimize-workflow + phase7-guard 41p/4s (the 4 skips = large-fixture-absent integrity params), production
  ruff 0, full suite GREEN. **Next:** R4.4 (undo dedup coverage, 2-model) → then the three 3-model concurrency
  items: R4.2 (snapshot-bytes cache, now unblocked by R3 coordinators) → R4.3 (thumbnail QThread, reuses R4.2) →
  R4.1 (overlay raster cache, highest invalidation risk).
- **2026-06-17 (turn 25b): R4.4 LANDED (undo dedup coverage, 2-model).** `CommandManager._unique_byte_total`
  (`edit_commands.py:642`) deduped the undo byte-budget accounting by `id()`. But `_dedup_top_snapshot_pair`
  only aliases the **top two** commands at push time, so byte-identical snapshots that are *non-adjacent* (a
  fresh `_capture_doc_snapshot()` matching an earlier doc state) stay distinct `bytes` objects and were summed
  twice → the 512 MiB cap tripped early → undo history evicted prematurely. **Fix:** dedup by **content**
  (`seen: set[bytes]`); CPython caches each bytes object's hash, so it's amortized-cheap across the recompute
  loop in `_trim_undo_stack_if_needed`. Exact + leak-free — deliberately NOT a persistent `digest→bytes` intern
  map (would keep evicted snapshots alive; `bytes` aren't weak-referenceable). The hot-path adjacent RAM-sharing
  in `_dedup_top_snapshot_pair` is untouched. **Red-Light First:** two new tests — `test_non_adjacent_identical_bytes_counted_once`
  (asserts exact unique total 300, was 400) + `test_non_adjacent_duplicate_does_not_prematurely_evict` (budget
  350 fits unique 300 but not id-double-counted 400 → was `undo_count=2`, now 3). Both RED before, GREEN after.
  Gates: undo-budget 8p, production ruff 0, full suite GREEN. PITFALLS entry added ("Undo byte-budget must dedup
  by content, not id()"). **Next:** the three 3-model concurrency items — R4.2 (snapshot-bytes cache) → R4.3
  (thumbnail QThread) → R4.1 (overlay raster cache).
- **2026-06-17 (turn 26): R4.2 LANDED (worker snapshot-bytes cache, 3-model concurrency item).** Fusion
  tooling was inconclusive this turn (both Gemini passes timed out at 180s even on a compact prompt — the
  documented hang; the codex-rescue agent returned only a forwarding meta-message, and SendMessage isn't in
  this session's toolset) — so per the manual ("fusion is advisory; authoritative gates = ruff + pytest +
  no-jump") and the R1 precedent, the design lens was applied via **my own source-grounded verification**.
  **The finding that de-risked AND re-risked the design:** keying the cache on the existing `render_revision`
  token (the page-render cache's invalidation key) is sound for every *render-visible* mutation — but
  `grep render_mode=3` proved OCR's `apply_ocr_spans` is the UNIQUE *render-invisible, worker-visible* mutation
  (injects invisible but searchable text; `_on_ocr_page_done` does NOT bump render_revision). A naive
  `(sid, render_revision)` cache would serve pre-OCR bytes to a later search → silently miss the OCR'd text
  (regression vs the current always-fresh call). **Design:** controller `capture_worker_snapshot_bytes()`
  single-entry cache keyed `(active_session_id, render_revision)`; `_invalidate_worker_snapshot_cache()` dropped
  from BOTH `_bump_render_revision` (visible mutations + memory free) AND `ocr_coordinator._on_ocr_page_done`
  after `apply_ocr_spans` (the invisible-text gap). The 3 coordinators (search/OCR/print) now call
  `self._c.capture_worker_snapshot_bytes()` not the model. Threading-safe (capture is GUI-thread
  pre-`thread.start()`; `bytes` immutable). Encryption AST guard undisturbed (cache delegates to the model; no
  new `tobytes` in model/) — `test_xref_repair` green. **Red-Light First:** new `test_worker_snapshot_cache.py`
  (4 tests incl. the **OCR-staleness regression guard** asserting `_on_ocr_page_done` drops the cache), all RED
  (method absent) → GREEN. **Test churn (R2.5-class):** the search + OCR flow harnesses' `__new__` controllers
  needed `_worker_snapshot_cache=None` + `_render_revision_by_session={}` (2 lines each; print harness already
  passed). Gates: search+ocr+print flow + snapshot + xref-guard 41p, production ruff 0, full suite GREEN.
  PITFALLS + ARCHITECTURE (controller perf §) updated. **Next:** R4.3 (thumbnail rasterization → QThread,
  reuses this cache) → R4.1 (overlay raster cache, highest invalidation risk).
- **2026-06-17 (turn 27): R4.3 LANDED (hybrid async thumbnails, 3-model concurrency item; user-approved scope).**
  Source mapping surfaced a design fork the one-paragraph plan missed: `get_thumbnail` → `get_page_pixmap(0.2)` →
  `render_page_pixmap` reads the LIVE non-thread-safe `fitz.Document` AND applies watermark overlays
  (`needs_page_overlay(..., "view")`). The plan's "worker opens its own fitz over snapshot bytes" avoids the
  live-doc race but the snapshot (`doc.tobytes()`) has NO overlays — so a naive worker render would silently drop
  watermarks from thumbnails. Surfaced this as a checkpoint; **user chose the behavior-preserving hybrid.**
  Built `controller/thumbnail_coordinator.py` (`ThumbnailCoordinator`/`_ThumbnailWorker`/`_ThumbnailBridge`,
  mirroring Search/Ocr coordinators verbatim: `worker→bridge→handler`, refs dropped on `thread.finished`).
  `_schedule_thumbnail_batch` now calls `coordinator.try_start(start, sid, gen, end_limit)` first and falls back
  to the unchanged synchronous path. **Async path taken ONLY when** `_should_async` holds: bridge wired
  (post-activate), session still active, range ≥ `THUMB_ASYNC_MIN_PAGES=24`, AND `get_watermarks()` empty
  (watermarked sessions stay sync → output byte-identical; annotations are baked into the bytes via `annots=True`
  so they survive). Worker renders off R4.2 snapshot bytes with the same `_safe_render_scale` clamp + colorspace,
  emits detached `QImage`s; `_on_batch_ready` converts to `QPixmap` on the GUI thread and drops stale batches via
  the `_thumb_gen_by_session` token. **Red-Light First:** new `test_thumbnail_coordinator.py` RED (ModuleNotFound)
  → 11 GREEN (worker batches synchronously, `_should_async` ×5 eligibility, `_on_batch_ready` paint + staleness,
  scheduler delegation). **Two bugs caught mid-gating:** (a) a live-thread end-to-end test hung when interleaved
  (passed in isolation) — the documented Qt/COM instability; removed it (behavior covered deterministically + the
  wiring is identical to proven coordinators). (b) `QPixmap.fromImage` HANGS without the `qapp` fixture — added it
  to the QPixmap-touching tests (PITFALLS entry). **ZERO churn** to existing thumbnail/flow/multi-tab suites
  (100p). Gates: thumbnail+flow+multitab 100p/1s, production ruff 0, full suite GREEN. PITFALLS ×2 + ARCHITECTURE
  (hybrid async thumbnails §) + TODOS updated. **Next (last R4 item):** R4.1 — overlay raster cache with per-tool
  revision counters (highest invalidation risk, ~25 mutation sites).
- **2026-06-17 (turn 28): R4.1 EVALUATED → DEFERRED → R4 COMPLETE (4/5).** Source audit + 3-way design review of
  the overlay raster cache found every viable variant is incorrect, high-risk-without-a-pixel-gate, or a non-win
  with friction — so the deliverable is the documented deferral, not code. **Findings (recorded in the plan's R4.1
  STATUS block):** (1) **watermark-only** — only `WatermarkTool` overlays `purpose="view"`; `AnnotationTool` uses
  the base `needs_page_overlay=False` (annotations are baked via `get_pixmap(annots=True)`, not overlays), so the
  spec's `annot_revision` is moot. (2) **The literal spec key is incorrect** — `(...,wm_revision,annot_revision)`
  omits a base-content revision, but the overlay branch composites `insert_pdf(base)→draw→get_pixmap`, so editing
  text under a watermark would serve a stale composite. (3) **No complete model-owned invalidation signal**
  (`edit_count`/`rebuild_page` miss rotation/annotations/watermarks); the only complete one is the controller's
  whole-session `_render_revision`. (4) **The safe `render_revision`-keyed cache is correct but a non-win** —
  redundant with the existing `_render_cache` (already `render_revision`-keyed; prevents redundant overlay compute
  within a revision — page view hits `_render_cache` and never reaches the overlay branch, thumbnails render once
  into the widget, snapshots are on-demand); it would only help under a QPixmap-cache eviction edge case while
  requiring the controller token threaded into the model render API (layer smell) + ~2× composite memory.
  (5) **Separate-canvas variant = high risk** — must replicate page rotation, MediaBox origin, and session
  colorspace (sRGB/gray/CMYK) and accept AA/overlap blending diffs, with NO watermark pixel-parity gate (no-jump
  only guards the editor). The real win (cross-revision per-page reuse) needs per-page content-revision tracking
  across the ~25 `_invalidate_active_render_state` sites (one miss = silent stale render) — disproportionate risk
  for a watermark-only conditional gain. **Decision (user-directed):** defer R4.1, record considerations, close R4.
  Docs-only commit; PITFALLS design-note added. **R4 ✅ 4/5** — R4.5 `2a8cf8c` · R4.4 `62e0b81` · R4.2 `883fc6e` ·
  R4.3 `60c36fc`. **Next:** R5 (security & supply-chain hardening) — and the deferred-findings backlog (R5.1
  print-decrypt, R5.5 optimizer-decrypt, R3.4 pending_edits, R3.7 shiboken6.isValid, R3.8b dispatcher).
- **2026-06-18 (turn 29): R5 begins — R5.5 optimize-copy encryption preservation (HIGH, Option A).** User chose
  Option A (preserve encryption) for the R5.1/R5.5 fork. R5.5 landed first (model-contained, lower risk; and the
  more serious leak — a *persistent* user-kept file, not a temp). **Bug:** for an encrypted (`needs_pass`) source,
  `_resolve_file_backed_optimize_source` returns None at the `needs_pass` gate, so the working doc is built from
  `model.doc.tobytes(...)` (defaults to `encryption=NONE`, decrypted) and saved unprotected — 另存為最佳化的副本 of a
  password-protected PDF silently produced an openable, unprotected copy. **Fix:** `save_optimized_copy` calls the
  new `reapply_source_encryption(model, new_path)` as the final step (after the `shutil.move` AND after any pikepdf
  post-packaging — which itself re-saves and would strip encryption): reopens the output file and re-saves with the
  session password (`model.password`; `owner_pw == user_pw` because only one password is retained in memory), the
  live doc's permission bits (`int(doc.permissions)` — the signed value round-trips exactly through fitz
  `save(permissions=...)`, verified empirically: print/copy preserved, modify denied), and an encryption method
  parsed from `metadata['encryption']` (default AES-256, never weakening). **Key empirical finding (PyMuPDF 1.27):**
  `doc.needs_pass` STAYS truthy after a successful `authenticate()` (it is `is_encrypted` that flips to False), so
  `needs_pass` is the reliable "file required a password" signal post-auth and the correct re-encrypt trigger;
  owner-password-only PDFs open with `needs_pass` False and are intentionally left unencrypted. The re-save targets a
  reopened handle of the *output file*, never `model.doc`, so the R2.2 encryption AST guard stays green (verified —
  `test_xref_repair` 44p incl. guard). **Red→Green:** `test_save_optimized_copy_preserves_encryption` (asserts the
  optimized copy `needs_pass` + rejects wrong pw + opens with the original pw) failed RED (output `needs_pass=0`),
  passes GREEN after the fix. Docs: ARCHITECTURE optimizer § + PITFALLS entry + TODOS R5.5. **Next:** R5.1 (print
  writes encrypted temp + plumb password to helper via a non-disk channel — env/stdin, NOT job.json).
- **2026-06-18 (turn 30): R5.1 — print path no longer writes a decrypted PDF to disk (HIGH, Option A).** The
  acute at-rest leak: `capture_worker_snapshot_bytes()` decrypts (`PDF_ENCRYPT_NONE`), and the print worker wrote
  those bytes verbatim to `work_dir/input.pdf`, leaving a fully decrypted copy of a password-protected source on
  disk for the print job's duration. **Fix (variant A2 — controller/helper only, no model changes):** (1)
  `PrintJobRequest` gains `password`; `_start_print_submission` captures `model.password` *only* when
  `model.doc.needs_pass`. (2) `_PrintSubmissionWorker._encode_input_bytes()` re-encrypts the captured bytes
  (AES-256, `owner_pw==user_pw`) before `write_bytes`, so the temp is never plaintext. (3) The password reaches the
  helper **out-of-band** via the QProcess environment — `PrintSubprocessRunner(helper_password=…)` injects
  `PDF_EDITOR_PRINT_PASSWORD` in `_build_helper_env` — explicitly NOT `job.json`, which lives in the same `work_dir`
  (PDF + password side-by-side would defeat the fix). (4) `helper_main._build_snapshot_bytes(..., password=…)`
  authenticates the encrypted `input.pdf` in-memory so the dispatcher still gets rasterizable bytes; the decryption
  never touches disk. Coordinator drops `self._print_password` once idle. **Isolation/guard:** every re-encrypt/auth
  `save` is in `controller/` + `src/printing/`, outside `model/`, so the R2.2 encryption AST guard does not apply and
  `pdf_model.py:267-668` is untouched; `model.password` is only *read*. **Behavior:** unencrypted + no-watermark
  path returns captured bytes byte-identically; only encrypted inputs change (they now print instead of failing).
  **Red→Green:** `test_print_encrypted_input.py` — 5 RED (TypeError: no `password` field/param) → 6 GREEN (worker
  encrypts temp, plain when no pw, password absent from job.json, helper decrypts with pw / raises without / leaves
  unencrypted input unchanged). Print suite 43p, ruff clean. Docs: ARCHITECTURE print § (secure print-input
  contract) + PITFALLS + TODOS. **Next:** R5.4 (packaging guard — resolve the build-env approach: setuptools 57.4.0
  + no `build` frontend make an in-`.venv` artifact build fragile) then R5.2 (OCR bundle — blocked on out-of-band
  vetted weights, not a code change).
