# Task 11 Completion — everything between 08b15e7 and Task 12

**Date:** 2026-08-04 · **Branch:** `task11/slice1-closure` · **Orchestrator:** Fable 5 (serial workflows; opus=design/verify, sonnet=implementation, haiku=mechanical)

## Goal

Close every Task 11 item that remains before Task 12 begins, taking the GPT 5.6 Pro
review of `08b15e7` as the external audit baseline. The four closure commits
(WS-A/B/C/D, `db5ca5d..46623c5`) claim to fix the review's five P0s — that claim gets
independently, adversarially re-verified rather than trusted.

## Phases (each = one small serial workflow; Fable synthesizes between phases)

### Phase 1 — verify closure + named residuals
1. **Adversarial closure verification** (opus, read-only): try to refute each of the
   five P0 fixes on HEAD. Early-exit the phase if any P0 is not actually fixed.
2. **`RejectReason.GROWTH_OUTSIDE_PAGE` constant** (haiku): declared in `dto.py`;
   `getattr` fallbacks removed (`plan.py:61`, two test sites).
3. **Rotation parity** (sonnet, red-first): `inspect.py:296` `origin_page` must map
   through `transformation_matrix * rotation_matrix` (mirror `plan.py:168`);
   caller-supplied `target_bbox` shape proven or fixed on `/Rotate 90/270`.
4. **GUI token assertion** (sonnet): dedicated View-level test that finalize reads
   `plan_token` from the saved editor local before `view.text_editor = None`;
   sensitivity proven by temporarily reintroducing the original bug.

### Phase 2 — owed pre-Task-11 debts
5. **Whitespace-collapsed bind recovery** (opus design → sonnet implement): use the
   dict parse's verbatim text; resolve the rawdict↔dict index-alignment blockers
   (TODOS.md:434 a+b). Re-run `scripts/measure_tier_funnel.py` after to watch the
   19.8% `TARGET_RECONSTRUCTION_UNVERIFIED` class convert.
6. **Preview `NO_MATCH` asymmetry** (sonnet): thread `joined_runs` through
   `controller/pdf_controller.py:3565` → `text_commit_coordinator.request` →
   `preview.py:191` so preview reports `target_reconstruction_unverified` too.
7. **`any(...)` line-identity guard** — Fable decision (keep-as-defence vs delete);
   no fabricated fixture.

### Phase 3 — perf gate, then layout remainder
8. Re-run `scripts/benchmark_text_commit_baseline.py`; compare against the local
   gitignored baseline. The plan's constraint governs: no layout expansion until
   Slice 1 preview is responsive. If regressed → remediate preview cost first.
9. If gate passes: Task 11 Steps 1–6 smallest horizontal Latin layout
   (opus design → sonnet red tests → sonnet implement → UI warnings), flag-off.

### Phase 4 — closing (Fable)
Full gates (`ruff`, `mypy model/ utils/`, `.venv` pytest), docs (PITFALLS +
index regen, ARCHITECTURE, TODOS), plan amendment, commits, final verdict.

## Decisions / dead ends

- **2026-08-04 Phase 1 verification (opus, adversarial): the 2026-08-03 closure verdict
  was too generous.** P0-4/P0-5 confirmed fixed (non-vacuous). P0-1 partially: cached-
  candidate commit path bypasses style/geometry policy gates (drag silently discarded,
  UI-reachable; token test vacuous). P0-2 partially: preview V0e certificate is a
  tautology (`verify.py:272-273`); Tier 1 font-resource proof absent from preview.
  P0-3 NOT fixed: solid-black growth zone via shading-in-Form-XObject still accepted —
  occupancy checks are a mechanism blocklist; background-reference gate samples inside
  the growth band (inert, monkeypatch-proven) and is fail-open on ambiguity.
  → Phase 1b inserted: F1 growth-proof redesign (opus), F2 cached-candidate policy
  re-check (sonnet), F3 preview V0e + font proof (sonnet), F4 rollback breadth (sonnet).
  P0-4's fingerprint /Rotate//CropBox residual folds into T12-P1-04.
- **2026-08-04 Phase 1b landed (all red-light-first, working tree, uncommitted):**
  - **F1 (opus)**: growth blank proof rebuilt as a background-surface proof —
    `_target_tail_reference_rgb` deleted (tail sample + fail-open median gone); new
    `background_reference_points` (left/above/below of target, provably disjoint from
    the widened halo), `_target_background_rgb` (strict-majority colour of the target's
    own bbox; no-majority ⇒ reject, 100% majority ⇒ ink invisible ⇒ reject — this is
    what kills black-on-black), `_reference_confirms_background`; occupancy gates kept
    as cheap extras but the raster proof stands alone (pinned with occupancy neutered).
    `count_growth_zone_glyphs` foreign-overhang blind spot fixed. Opus corrected my
    fixture-geometry model: the black shading also covers all reference points, so
    reference-comparison alone would still accept — the ink-visibility rule is the
    load-bearing gate. Deliberate deviation: non-uniform reference neighbourhood skips
    that candidate (not whole-proof abort) — pass still requires an affirmative match.
  - **F3 (sonnet)**: V0e tautology fixed (PageState.page_count captured pre-patch);
    real per-session KEEP round-trip probe (reuses the existing single tobytes call —
    snapshot-count contract preserved); preview consults it fail-closed; preview now
    runs `build_tier1_font_outcome` and refuses FONT_RESOURCE_NOT_PROVEN like commit.
  - **F2 (sonnet)**: cached-candidate branch refuses on style/geometry overrides
    (falls through to fresh prepare ⇒ honest refusal reasons) and re-runs the
    shared-content-stream scan pre-commit; vacuous token test rewritten (spy fires,
    prepare poisoned to prove cache reuse); controller caches only after PNG decode.
  - **F4 (sonnet)**: live commit catches BaseException (revert + re-raise); revert
    failure chains both errors and states the document may be inconsistent.
  - **Hazard noted (F1/F3)**: whole-suite `pytest test_scripts/` may hang/crash at
    PySide6 interpreter teardown in this venv, pre-existing — chunked fallback in gate.
- **2026-08-04 Phase 1c landed (residuals):** `RejectReason.GROWTH_OUTSIDE_PAGE`
  declared (dto.py:62), getattr fallbacks gone. Rotation parity: `inspect.py`
  `_origin_in_page_space` now composes `rotation_matrix` (Defect A); caller-supplied
  `target_bbox` was NOT rotation-aware — dict/rawdict extraction geometry is unrotated
  page space (same PITFALLS quirk as annot geometry), fixed via `_dict_space_to_visual`
  at the model boundary in `pdf_text_edit.py` (Defect B); PLUS a pre-existing Defect C
  found: V0c/V0d verify comparisons read dict-space rawdict geometry vs visual-space
  `target_bbox_page`, so no tiered commit ever succeeded on a /Rotate page — fixed in
  verify.py, pinned by `test_full_tiered_commit_succeeds_on_rotated_page[90/270]`.
  GUI token assertion added (sensitivity-proven by temporarily reintroducing the WS-A
  bug). Gate: 2,201 passed / 21 skipped / 5 xfailed chunked (whole-suite run hits the
  pre-existing PySide6 teardown hang); ruff clean; mypy clean. One intermittent flake:
  `test_multi_tab_plan.py::test_05_search_state_restored_per_tab` (green in isolation
  and on re-run; unrelated tab/search state).

- **2026-08-04 Phase 2 landed (owed pre-Task-11 debts):**
  - **Whitespace recovery (opus design → sonnet implement, Red-first):** `_Tier0Target`
    gained `source_kind` (`"run_join"` | `"dict_line"`), a `whitespace_reconstructed`
    property and `replacement_for(edited)`; `_dict_line_for_runs` resolves the dict line
    for a run set behind a **runtime** content-and-geometry alignment proof (P1–P5 /
    A1–A2 / G1–G4) — this is how blocker (a) is answered: the rawdict↔dict alignment is
    verified per call, so the shapes where it breaks refuse rather than mis-bind.
    Blocker (b) (single-run padding) falls out, since the dict line carries the padding
    verbatim. **Funnel after landing: `TARGET_RECONSTRUCTION_UNVERIFIED` 19.8% → 29.1%,
    bind survivors 51 → 93.** The rise is the honest-relabel effect — MuPDF materializes
    wide `TJ` kerns as synthesized spaces, so on the dominant document the dict line is
    itself a reconstruction. The measuring agent reported this as a "pre-recovery" run;
    that was wrong (it ran after recovery landed, serially) and is corrected here.
    Provenance caveat carried into TODOS: orchestrator did not independently re-run,
    exact invocation not captured — Task 12 must re-measure, not cite.
  - **Preview `NO_MATCH` asymmetry closed:** `whitespace_reconstructed` threaded
    `pdf_controller.py:3595` → `text_commit_coordinator.request` →
    `PlanPreviewRequest`; renderer relabels bare `NO_MATCH` →
    `TARGET_RECONSTRUCTION_UNVERIFIED`. TODOS:433's description was stale — the
    derivation already returned a full `_Tier0Target`; the gap was the DTO chain.
  - **`any(...)` guard — decision: KEEP as defence-in-depth** (`pdf_text_edit.py:1478`).
    Its protection must not hinge on `span_id`'s format staying identical across two
    parsers; that is incidental, not contractual. Comment records the decision and
    forbids fabricating a fixture. No fixture was fabricated.
- **2026-08-04 Phase 4 (closing):** pytest re-run **chunked after Phase 2** rather than
  quoting the Phase 1c number — Phase 2 changed `_Tier0Target`'s shape and added 365
  lines to `pdf_text_edit.py`, and this repo has a documented pitfall where exactly that
  kind of change breaks `__new__`-built test doubles in a way targeted runs miss.
  Result: **2,219 passed / 21 skipped / 5 xfailed / 0 failed** (402 + 871 + 323 + 623,
  every chunk exit 0); ruff clean; mypy clean (47 files). Docs
  updated: PITFALLS +7 entries (index regenerated), ARCHITECTURE §10.1.1 added and the
  Tiered Preview Verification block corrected, TODOS ticks + the 08-03 closure entry
  marked SUPERSEDED (not rewritten), plan v2 amendment added. Session plan stays in
  `plans/` — **not** archived, because Phase 3 is outstanding.

## Open questions

- Whether the perf re-measure blocks Phase 3 layout (resolved by measurement in Phase 3).

## Outstanding at hand-off

**Phase 3 was not executed, and is gated rather than skipped.** The v2 plan's own
constraint is that no layout expansion happens until Slice 1 preview is responsive;
Slice 1 has since *added* per-keystroke verification work to the preview path, so the
constraint binds harder than when it was written. Order is fixed: re-run
`scripts/benchmark_text_commit_baseline.py`, compare against the gitignored
`benchmarks/baseline-2026-08-01.json`, and only if dense-page preview p95 holds does
Steps 1–6 horizontal layout start. If it regressed, remediate preview cost first
(the known suspect is `preview.py` re-running `prepare_tier0_plan` per keystroke
generation — a full page re-parse on the 35,844-show file).
