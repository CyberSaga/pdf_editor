# Phase R6 — Coverage Hardening (tail over decomposed seams)

**Status:** Ready (after R3). **Fusion:** 3-model (Playbook 4.5 — different models catch different
untested paths). **Why last & thin:** the test-env *unification* that a standalone R6 would have
done is a **precondition** and lives in R0. What remains is coverage-gap hardening, sequenced
**after** R3 so new tests cover the *decomposed* seams, plus retiring stale gate ignores.
(Census: test-env lens; critique "R6 folded".)

> **Implicit risks:** tests written *after* R3 risk pinning the **new** seam rather than the **old**
> behavior — they won't catch a decomposition regression. Re-enabling stale `verify_no_jump.py`
> ignores could re-introduce gate flakiness under `.venv`. A coverage floor set above current
> measured coverage blocks unrelated PRs.

---

## R6.1 — Characterization tests for verified-untested live methods

Genuinely zero test references **and** live production callers (census-verified):
- `model.compose_merged_document` (`pdf_model.py:1491`, called by `pdf_controller.py:1242,1266`).
- `model.get_print_watermarks` (`pdf_model.py:1592`, feeds the print path `pdf_controller.py:1660`).
- `model.get_text_selection_bounds`; `model.run_reopen_anchors`.
- Controller QThread bridge slots `forward_prepared/forward_succeeded/forward_status`
  (`pdf_controller.py:163/204/292`, wired at `:1391/1670/2697`).
- **These are exactly the glue where a 1.25→1.27 PyMuPDF or 6.9→6.10 PySide6 change regresses
  silently** — which is why R0 made `.venv` the authority.
- **Order subtlety:** where a method is touched by R3, write the **characterization test against
  pre-R3 behavior first** (during/before R3) so it pins old behavior, then carry it through R3
  green. For methods R3 does not touch, author here directly.

(Census false positives to NOT chase: the fullscreen subsystem and session-lifecycle are covered
via `test_fullscreen_transitions.py` re-importing `test_multi_tab_plan.py` cases — already green.)

## R6.2 — Retire stale `verify_no_jump.py` full-suite ignores

- `scripts/verify_no_jump.py:806-814` hard-ignores `test_multi_tab_plan.py`, `test_ocr_e2e.py`,
  `test_render_colorspace.py` as "missing fixtures" — census verified all three now pass/skip
  cleanly (`test_multi_tab_plan`: 70 passed/1 skipped; OCR+colorspace: 2 passed/8 skipped).
- **Fix:** remove the three `--ignore` lines so the gate's full-suite step actually covers them.
  Keep the documented `--skip-signoff` path (`:1000`) as the CI-runnable subset (the CUA signoff is
  structurally unrunnable headless — that is the source of "6/9 failing", not a code defect).

## R6.3 — Coverage floor ratchet

- With `pytest-cov` added in R0.5 and a measured per-module baseline, set a CI floor **at or below
  current** coverage for `model/`, `controller/`, `view/`. Ratchet upward in a *separate* PR — do
  not gate this campaign's merges on a floor above the measured baseline.
- Target the R6.1 gaps first; the decomposed R3 seams (`text_block_parsing`, the coordinators, the
  view managers) are now independently testable — add focused unit tests where the extraction made
  a previously-buried branch reachable in isolation.

---

## Fusion Protocol Playbook

- **Playbook 4.5** (test coverage gap, 3-model) on each impl+test pair — different vendors surface
  different untested branches:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "Review this implementation and its (absent/thin) test coverage. Identify public methods or
       branches with no test, edge cases (empty/boundary/error paths) uncovered, and any test that
       passes on a no-op (checks return value, not side effects). Name the untested method and the
       missing assertion." `
      --file model/pdf_model.py --file test_scripts/test_pdf_merge_workflow.py --no-synthesize
  # then /codex:rescue same prompt + files, synthesize per §3.
  ```

## Verification & Gatekeeping

```powershell
# New characterization tests green on the shipped stack:
.venv\Scripts\python.exe -m pytest test_scripts/test_merge_composition.py test_scripts/test_print_watermarks.py test_scripts/test_worker_bridge_slots.py -v
# Coverage delta recorded:
.venv\Scripts\python.exe -m pytest test_scripts/ --cov=model --cov=controller --cov=view --cov-report=term-missing
# Gate now covers the previously-ignored files:
.venv\Scripts\python.exe scripts/verify_no_jump.py --skip-signoff
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider
```

**Gate:** new tests assert **state changes and side effects** (CLAUDE.md §5.2), not only return
values; coverage floor recorded and set at-or-below baseline; the three un-ignored files pass under
`.venv`.

## Risk Triage (2→3 upgrade points)

- **Authoring stays 3-model** (4.5 — vendor diversity is the point of the phase). The *mechanical*
  ignore-removal (R6.2) and floor config (R6.3) are 2-model, but the coverage *analysis* that
  drives R6.1 is 3-model.
- **Vectors:** post-R3 tests pinning the new seam not old behavior (write characterization tests
  early); re-enabled files flaky under `.venv`; a too-high coverage floor blocking unrelated PRs.

## Docs (same commit)

- `docs/PITFALLS.md`: "characterization tests must pin pre-refactor behavior to catch
  decomposition regressions"; "verify_no_jump ignores go stale — re-audit on every gate change".
- `TODOS.md`: close the coverage-gap + stale-ignore items; record the coverage floor.
- `refactor-state.md`: flip R6 status; record final campaign metrics (LOC reduction per god-module,
  ruff production-clean, coverage delta, 0 layer-boundary violations locked by CI).

## Commit

Per group: `test: R6 coverage hardening — characterize merge/print-watermark/bridge-slot seams;
retire stale no-jump ignores; coverage floor`. `Co-Authored-By: Claude Fable 5
<noreply@anthropic.com>`.
