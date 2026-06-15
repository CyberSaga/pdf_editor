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
| Suite (`.venv` / PyMuPDF 1.27.1 — shipped stack) | **cannot collect** — `INTERNALERROR`, aborts at 983 | `ux_signoff_agent.py:36-39 sys.exit(1)` at import |
| 20 skips | all OCR (surya/torch absent) — environmental, not regressions | — |
| ruff total (E4/E7/E9+F, E501 unselected) | **238** (doc said 240); 28 in production layers, 210 in test/script | hygiene lens |
| ruff auto-fixable | 18 (F541×12, F401×6) | hygiene lens |
| God-module LOC | `pdf_view` 5497 / `pdf_model` 5166 / `pdf_controller` 3383 / `text_editing` 1809 / `text_block` 1043 | LOC scan |
| Coverage tooling | **none installed** in either interpreter | test-env lens |

**R0 freeze target:** `.venv` collects full suite; **≥1355 passed / exactly the 20 OCR skips / 0 failed**, deterministic; a captured per-module coverage number as the floor.

---

## 2. Phase ledger

| ID | Phase | Fusion mode | Playbook(s) | Status | Plan |
|----|-------|-------------|-------------|--------|------|
| **R0** | Baseline Freeze & Regression-Net Repair | 2-model (mech) + 3-model (interpreter-authority) | 4.5 | ☐ not started | [`plans/refactor-R0-baseline-freeze.md`](plans/refactor-R0-baseline-freeze.md) |
| **R1** | Mechanical Hygiene (ruff + app-identity + packaging) | 2-model | 4.2 | ☐ not started | [`plans/refactor-R1-mechanical-hygiene.md`](plans/refactor-R1-mechanical-hygiene.md) |
| **R2** | MVC Boundary Reconvergence (**guard-first**) | 2-model | 4.3 | ☐ not started | [`plans/refactor-R2-mvc-boundary.md`](plans/refactor-R2-mvc-boundary.md) |
| **R3** | God-Module Decomposition | 3-model | 4.4 + 4.1 | ☐ not started | [`plans/refactor-R3-god-module-decomposition.md`](plans/refactor-R3-god-module-decomposition.md) |
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
