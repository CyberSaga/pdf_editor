# Milestone 1 Closeout — CI & Quality Debt

Executed 2026-07-03 → 2026-07-05. All 13 PRs merged squash onto linear main; final HEAD `dc4146d`. Full plan with per-PR evidence is archived at `plans/archive/milestone-1-ci-quality-debt.md`.

## 1. Merged PRs

| Plan | GitHub | Purpose |
|---|---|---|
| PR-0 (unplanned) | **#10** | Restore green baseline: fixed the windows pip-audit crash (CJK comment + cp1252 fallback, red since 2026-06-14) and the stale `wait_for_done` test stub; added the blocking pure-ASCII guard for requirement/constraint files |
| PR-1 | **#9** | `constraints-ci.txt` pins every CI install to the `.venv` truth (PyMuPDF 1.27.1 stack); pip-audit deliberately unpinned |
| PR-2 | **#11** | Pytest marker scheme (`local_only`/`windows_only`/`needs_fixtures`/`ocr_heavy`) + `--strict-markers`; the one real-printer test marked |
| PR-3 | **#12** | Advisory cross-platform `test-functional` CI job (windows + ubuntu matrix, junit artifacts) |
| PR-4 | **#13** | E402 part 1: removed redundant env/path preambles from 19 pytest-only test files (91 → 28) |
| PR-5 | **#14** | E402 part 2: `test_scripts/_bootstrap.py` for 16 hybrid scripts, conftest lazy-import, fusion.py noqa; **ruff flipped to full rule set, blocking** (E402 = 0) |
| PR-6 | **#15** | 24 mechanical mypy fixes (67 → 43) + advisory typecheck job; `platform`/`python_version` pinned for CI/local parity |
| PR-7 | **#16** | Final 43 mypy errors → 0 via typed local binds + annotation fixes; **mypy flipped blocking**. `_require_doc()` rejected at design time (behavior-preserving constraint); 3 no-doc behavior-pin tests added. Codex-reviewed |
| PR-8 | **#17** | `ocr_types` → `utils/` (shim kept), `show_error` → `view/message_boxes.py`; **utils import contract flipped blocking** |
| PR-9 | **#18** | Dialog behavior calls (`is_device_available`, `preset_optimize_options`) routed via controller injection; DTO imports permitted via `ignore_imports` + name-level AST guard; **all 4 import contracts blocking**. Codex-reviewed |
| PR-10 | **#20** | Advisory triage: 14 tests marked `needs_fixtures`; 2 real fixes (child-process `PYTHONIOENCODING`; missing `build` package in the CI job); issue #19 filed for the ubuntu segfault |
| PR-11 | **#21** | **Windows functional leg flipped blocking**; coverage measured (78% CI / 79% local), `coverage.xml` artifact |
| PR-12 | **#22** | Coverage gate active via pyproject `fail_under = 75`; pins consolidated into `constraints-ci.txt`; end-of-M1 tripwire executed; plan archived |

## 2. Final CI gate matrix

| Job | Gate | Status |
|---|---|---|
| `dependency-audit` (ubuntu + windows) | pip-audit over requirements files, fails on any advisory | **Blocking** |
| `ruff (blocking)` | Full selected rule set (E4/E7/E9/F), zero tolerance | **Blocking** |
| `mypy model/ utils/ (blocking)` | Zero errors, stub/platform parity with local | **Blocking** |
| `Layer boundaries` | 4 import-linter contracts + `threading.Thread` grep over view/+controller/ | **Blocking** |
| `Security regression tests` | Pillow floor, OCR requirements/weights, requirements-ASCII guard | **Blocking** |
| `Functional suite (windows - BLOCKING)` | Full suite minus `local_only`/`needs_fixtures` (1553 tests) + coverage ≥ 75% | **Blocking** |
| `Functional suite (ubuntu - advisory, issue #19)` | Same selection | Advisory only |
| OCR-extra audit step | pip-audit on `ocr-requirements.txt` (upstream-blocked CVEs) | Advisory only |

Test-level guards now live in the suite itself: pure-ASCII requirement files, view→model DTO **name** allowlist, `fitz.open` count pin in view/, no-doc behavior pins, `--strict-markers`.

## 3. Coverage baseline and gate

- **Baseline:** 78% on the CI windows leg (15,385 stmts / 3,354 missed; identical across 3+ runs); 79% locally with fixtures present.
- **Gate:** `fail_under = 75` in `pyproject.toml` is the single source of truth — CI no longer overrides it. Deliberate deviation from the plan's "CI−2" formula (76%): 75 was already evidence-cleared, and one number in one place beats two. Headroom: ~3 points ≈ 460 statements.

## 4. Remaining follow-ups

1. **Issue #19** — ubuntu functional leg intermittently segfaults (Qt offscreen teardown; crash site isolated to `test_page_deskew_scope.py::test_controller_straightens_batch_as_single_undo`). Blocks ubuntu ever flipping blocking.
2. **No-doc guard unification** — a behavior-allowed PR to unify the heterogeneous no-document failure modes (`ValueError` vs `RuntimeError` vs silent return, two message spellings); would supersede the behavior-pin tests. Tracked in the archived plan.
3. **`needs_fixtures` tests run only locally** (14 tests) — CI never exercises them; either commit sanitized fixtures or synthesize them (like conftest already does for `1.pdf`) to regain CI coverage.
4. Two scoped `# type: ignore`s from PR-6 (single_instance stub gap, edit_commands LSP widening) — fine indefinitely, documented in-code.
5. TODOS.md pre-M1 items (M2 backlog: delete-image bug, R5-01 print path, worker byte-lifetime, `.venv` Pillow bump).

## 5. Known flaky / advisory-only areas

- **Local only — orphaned print-helper processes:** an interrupted suite run leaves child `python.exe` processes that poison later runs (status-bar restore races in `test_print_controller_flow`, COM `0x80040155` segfault in `test_print_speed`). First response: kill stray python processes, rerun. Documented in `docs/PITFALLS.md`.
- **Local only — transient `0xC0000142` child-process failures** in subprocess-spawning tests under heavy load (seen once during PR-11 validation; watch item in the archived plan).
- **Advisory legs:** ubuntu functional (issue #19 segfault ~1-in-2 runs, plus ~5 ubuntu-specific failures when it does complete — untriaged, low priority) and the OCR-extra audit step.
- The lone recurring local warning: cp950 `UnicodeDecodeError` in `test_security_packaging`'s reader thread — mitigated in #20, harmless.

## 6. If main turns red, check in this order

1. **Which job?** The name tells you the class — every job is single-purpose.
2. **pip-audit red** — usually a *new upstream advisory*, not your code (it's deliberately unpinned). Read the CVE; fix is typically a floor bump in requirements + `.venv` + constraints together.
3. **Windows functional red** — read the tail: `Required test coverage of 75%` failure means coverage regression (compare `coverage.xml` artifact against the 78% baseline); test failures mean a real regression — reproduce locally with `.venv\Scripts\python.exe -m pytest -q -m "not local_only and not needs_fixtures"`. If it smells unrelated to the diff, check runner-side history (3 stable green runs is the norm) before blaming the code.
4. **mypy/ruff/layer red** — deterministic, reproduce locally with the exact CI command; CI and local are pinned to identical versions and mypy platform, so any divergence means the constraints file drifted from `.venv`.
5. **Windows-only weirdness with encodings** — it's the cp1252 class again; `docs/PITFALLS.md` has two entries on it.

## 7. Recommended entry criteria for Milestone 2

1. **Main green on 2–3 consecutive runs** after this closeout (it is now; just confirm nothing drifts overnight — pip-audit is the only gate that can turn red without a commit).
2. **B4 first** (`.venv` Pillow ≥ 12.2.0 + pip/setuptools refresh): it's mechanical, and doing the environment bump *before* touching content-stream code means any B1 regression is attributable to code, not dependency skew. Remember: a `.venv` bump must update `constraints-ci.txt` in the same PR.
3. **Fixture strategy decided for B1**: the delete-image overlap bug needs overlapping-image test PDFs; decide whether they're synthesized in-test (preferred — CI can then gate the fix) or added to gitignored `test_files/` (CI-blind). This determines whether M1's safety net actually protects M2's riskiest change.
4. **Red-light discipline stays mandatory**: B1's regression test (two overlapping images, delete one, neighbor survives) must be shown failing before the fix, mirroring `test_move_overlapping_app_images_both_survive`.
5. Optional but cheap: rerun the windows functional leg once on the morning you start, so B1's baseline pass-count (1553) is fresh.

Milestone 1 is closed. I'll wait for your signal on Milestone 2.