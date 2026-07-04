# Milestone 1 — CI & Quality Debt

> Execution copy of Milestone 1 from the stabilization roadmap (2026-07-03).
> Updated as PRs land; archived to `plans/archive/` when the milestone completes.

**Goal:** the functional suite gates merges on a Windows runner; E402 = 0; mypy(model/, utils/) = 0 and blocking; all 4 import-linter contracts blocking; coverage measured on CI.

**Key facts from investigation:**

- The suite is already headless-by-design (`test_scripts/conftest.py:9` sets `QT_QPA_PLATFORM=offscreen`); the "headless subset" ≈ the whole suite. Real CI risks: gitignored `test_files/` fixtures (fixture-dependent tests self-skip), Windows-only driver paths (mostly mocked), Linux font/pixel-diff skew.
- No pytest markers exist yet; `[tool.pytest.ini_options]` has only `testpaths`.
- All 91 E402s are redundant `os.environ.setdefault(...)` + `sys.path.insert(...)` preambles in `test_scripts/` (conftest already does both) plus 1 in `scripts/fusion.py`.
- mypy 67 errors: ~27 are `self.doc: Document | None` dereferences (`pdf_model.py` 22, `pdf_object_ops.py` 16); rest are mechanical (Pillow `Image.Resampling`, `Counter` annotations, `bytes(QByteArray)`, implicit Optional, `FitZColorspace` alias).
- `requirements.txt` floors are loose (`PyMuPDF>=1.23`); CI matching `.venv` (PyMuPDF 1.27.1) today is luck, not policy.

## PR execution plan (12 PRs, land strictly in order)

One PR = one reviewable unit. Standard validation applies to every PR in addition to the listed commands: `.venv\Scripts\python.exe -m pytest -q` (full local suite), `ruff check .`, and a green CI run on the PR branch.

### PR-0 (unplanned prerequisite) — `fix: restore green baseline`

- **Discovered during PR-1 validation:** the baseline was red twice over. (a) CI's windows-latest pip-audit leg had failed on every run since 2026-06-14 — commit `559d92f` added a CJK comment to `optional-requirements.txt` and pip-audit's parser falls back to cp1252 on Windows, crashing on byte `0x81`. (b) `test_app_close_waits_for_optimizer_worker` had failed locally since `310f6ca` gave `handle_app_close` a `wait_for_done` call the test stub lacked.
- **Fix:** ASCII-rewritten comment + `wait_for_done` stub; new blocking guard test `test_scripts/test_security_requirements_encoding.py` (all requirement/constraint files must be pure ASCII); pitfall recorded in `docs/PITFALLS.md`.
- **PR:** #10 — merges BEFORE PR-1 (#9); #9 then picks up main.
- **Status:** merged 2026-07-04 as PR #10.

### PR-1 — `ci: pin CI dependency environment to .venv versions`

- **Scope:** Add `constraints-ci.txt` capturing `.venv` truth (`PyMuPDF==1.27.1`, `PySide6==6.10.2`, `Pillow==12.2.0`, plus numpy/pytest/pytest-cov/tooling exact versions from `pip freeze`). Project-dependency and tool install steps in ci.yml become `pip install ... -c constraints-ci.txt`. Add a `pip list` visibility step to the test job. `pip-audit` itself stays deliberately unconstrained (the auditor needs a current advisory DB). No test or code changes.
- **Files:** `constraints-ci.txt` (new), `.github/workflows/ci.yml`.
- **Model:** Sonnet 5.
- **Validation:** `.venv\Scripts\python.exe -m pip freeze` to source the pins; CI log shows PyMuPDF 1.27.1.
- **Acceptance:** all existing jobs green; CI versions now match `.venv` by policy, not by luck.
- **Rollback risk:** **Low** — CI-only; revert restores floor-resolution behavior.
- **Status:** merged 2026-07-04 as PR #9 (squash 5abfab7); pins verified on CI (test job resolved PyMuPDF 1.27.1 / PySide6 6.10.2 / Pillow 12.2.0 / numpy 2.2.6 / pytest 9.0.3).

### PR-2 — `test: register pytest marker scheme and mark hardware-bound tests`

- **Scope:** Add `markers` to `[tool.pytest.ini_options]`: `local_only` (real hardware/screen — never in CI), `windows_only`, `needs_fixtures`, `ocr_heavy`. Apply `local_only` to `test_win_print_fixes.py::test_set_page_layout_applies_size_on_real_printer` (real printer) and any other real-device tests found during a `--collect-only` sweep. Document the scheme in `test_scripts/TEST_SCRIPTS.md`.
- **Files:** `pyproject.toml`, `test_scripts/test_win_print_fixes.py`, `test_scripts/TEST_SCRIPTS.md`.
- **Model:** Sonnet 5.
- **Validation:** `.venv\Scripts\python.exe -m pytest --markers`; `... -m "not local_only" --collect-only -q` (count ≈ full suite minus marked).
- **Acceptance:** no `PytestUnknownMarkWarning`; collection counts documented in the PR description.
- **Rollback risk:** **Low** — markers are additive; nothing changes for unmarked tests.
- **Status:** merged 2026-07-04 as PR #11 (squash 91acf3f).

### PR-3 — `ci: add advisory cross-platform functional test job`

- **Scope:** New `test-functional` job: matrix `[windows-latest, ubuntu-latest]`, `fail-fast: false`, Python 3.10, `QT_QPA_PLATFORM: offscreen`, ubuntu gets the existing libegl/libgl apt step; installs `requirements.txt` + `optional-requirements.txt` with `-c constraints-ci.txt`; step runs `python -m pytest -q -m "not local_only" --junitxml=pytest-report.xml` with `continue-on-error: true`, `timeout-minutes: 40`, junit artifact upload.
- **Files:** `.github/workflows/ci.yml`.
- **Model:** Sonnet 5.
- **Validation:** CI run on the PR; download artifacts, record pass/fail/skip per OS.
- **Acceptance:** both legs execute to completion (even if red) and never block merge.
- **Rollback risk:** **None** — advisory job; deleting it restores status quo.
- **Status:** merged 2026-07-04 as PR #12 (squash b617c78). First-run data recorded in the PR-10 section below and in a comment on #12.

### PR-4 — `test: remove redundant import preambles from pytest-only files (E402 part 1)`

- **Scope:** In ~40 pytest-only test files, delete the redundant `os.environ.setdefault(...)` + `sys.path.insert(...)` preamble (conftest already does both before any test module imports) and move imports to top. Fix `conftest.py`'s own E402 by lazy-importing `QApplication` inside the `qapp` fixture. **No hybrid/script-runner files in this PR.**
- **Files:** `test_scripts/conftest.py` + ~40 `test_scripts/test_*.py` (pytest-only category).
- **Model:** fast-worker for the bulk edit (fully mechanical, pattern decided); Sonnet 5 for `conftest.py` and final verification.
- **Validation:** `ruff check test_scripts --select E402 --no-cache` (count drops to hybrid files only); full local suite pass count unchanged.
- **Acceptance:** zero E402 in pytest-only files; identical suite results before/after.
- **Rollback risk:** **Low–medium** — import-order side effects possible in principle; mitigated because conftest guarantees env/path before collection. Revert is trivial (test-only diff).
- **Status:** merged 2026-07-04 as PR #13 (squash 5a6dc51).

### PR-5 — `test: bootstrap module for hybrid scripts; flip E402 blocking (E402 part 2)`

- **Scope:** Add `test_scripts/_bootstrap.py` (underscore-prefixed, never collected: sets repo-root `sys.path` + offscreen env at import time). Hybrid files that also run as `python test_scripts/x.py` start with `import _bootstrap  # noqa: F401`. Fix `scripts/fusion.py`'s single E402. Then flip: lint job drops the E402 ignore; update the ci.yml header comment documenting the old 91-finding backlog.
- **Files:** `test_scripts/_bootstrap.py` (new), ~12 hybrid files, `scripts/fusion.py`, `.github/workflows/ci.yml`.
- **Model:** Sonnet 5.
- **Validation:** `ruff check . --select E402 --no-cache` → 0; spot-run 3 hybrid files as plain scripts; full suite.
- **Acceptance:** lint job blocking with E402 included, green; script-mode invocation still works.
- **Rollback risk:** **Medium** for script-mode regressions (affects only manual runners, not pytest or the app); revert is simple.
- **Status:** merged 2026-07-04 as PR #14 (squash fe748d9).

### PR-6 — `types: mypy quick-wins + advisory CI typecheck job`

- **Scope:** Fix the ~20 mechanical mypy errors: `Image.NEAREST/BICUBIC → Image.Resampling.*` (`pdf_model.py:3173,3209`; Pillow floor 12.2.0 makes this safe), `Counter[str]`/`set[int]` annotations (`text_block_parsing.py`, `utils/helpers.py`), `FitZColorspace` TypeAlias (`color_profile.py`), `bytes(QByteArray) → .data()` (`single_instance.py:132,247`), implicit-Optional defaults (`pdf_model.py:3062`, `pdf_text_edit.py:1177`), `ocr_weights.py` Mapping params, `edit_commands.py:170` return annotation. Add advisory `typecheck` CI job (`mypy model/ utils/`, `continue-on-error: true`).
  - **Deviation from this split (recorded during execution):** `utils/helpers.py:38`'s `QImage.Format.Format_RGBA8888/RGB888` enum-qualification and the remaining bare-list/set annotation stragglers (`search_tool.py:39`, `annotation_tool.py:99,135`, `helpers.py:9`) landed here in PR-6 instead of PR-7, since they were equally mechanical annotation-only fixes; `pdf_content_ops.py`'s int/float assignment fix stayed in PR-7 as planned. Also, `single_instance.py:132,247` kept the original `bytes(socket.readAll())  # type: ignore[call-overload]` form rather than switching to `.data()`, because the isolation test suite's `_FakeSocket.readAll()` test double returns plain `bytes` (no `.data()` method) — switching would have been a real behavior/compatibility change, not the intended mechanical one. And `edit_commands.py:170`'s fix is a `# type: ignore[override]` on `EditTextCommand.execute` (not a base-class signature change), because `test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands` pins `EditCommand.execute`'s return annotation to `None`.
- **Files:** `model/pdf_model.py`, `model/text_block_parsing.py`, `model/color_profile.py`, `model/tools/ocr_weights.py`, `model/pdf_text_edit.py`, `model/edit_commands.py`, `utils/single_instance.py`, `utils/helpers.py`, `model/tools/search_tool.py`, `model/tools/annotation_tool.py`, `.github/workflows/ci.yml`, `pyproject.toml`.
- **Model:** Sonnet 5.
- **Validation:** `.venv\Scripts\python.exe -m mypy model/ utils/` (67 → 43); full suite (1576 passed / 21 skipped / 0 failed, unchanged); app smoke launch.
- **Acceptance:** only annotation/enum-form changes — no behavior change; advisory typecheck job visible on CI.
- **Rollback risk:** **Low** — the Pillow Resampling rename and `QImage.Format` qualification are the only runtime-touching lines, both enum-value-identical.
- **Status:** merged 2026-07-04 as PR #15 (squash d1cf684).

### PR-7 — `types: eliminate doc-None dereferences; flip mypy blocking`

- **Scope:** Add `PDFModel._require_doc() -> fitz.Document` (raises, matching the existing zh-TW error-message style); convert the ~27 flagged `self.doc` dereferences in `pdf_model.py`/`pdf_object_ops.py`; fix stragglers (`ocr_tool.py` ×5, `pdf_content_ops.py` int→float). `utils/helpers.py:38`'s `QImage.Format.Format_RGBA8888` enum form and the `annotation_tool.py`/`search_tool.py` list-annotation stragglers moved to PR-6 (see that PR's deviation note) — dropped from this scope. When local mypy = 0, remove `continue-on-error` from the typecheck job in the same PR.
  - **Deviation from this split (recorded during execution):** the planned raising `_require_doc()` helper was **rejected at design time** — the current no-doc failure modes are heterogeneous (TypeError from `len(None)`/`None[idx]`, silently-swallowed AttributeError in `_image_xref_digest`, and silent no-ops that return early), so a single raising guard would have *changed* behavior on paths that today crash differently or not at all. Instead each of the 26 B+C sites uses a runtime-inert typed local bind (`doc: fitz.Document = self.doc`, which mypy accepts because `fitz.Document` is `Any`, and which raises the exact same AttributeError/TypeError at runtime if `self.doc` is `None`); unifying the no-doc guards is deferred to a future behavior-allowed PR. New `test_scripts/test_model_no_doc_behavior_pins.py` pins the current crash behavior (passes identically before and after the refactor).
- **Files:** `model/pdf_model.py`, `model/pdf_object_ops.py`, `model/pdf_content_ops.py`, `model/tools/ocr_tool.py`, `.github/workflows/ci.yml`.
- **Model:** Fable 5 designs the `_require_doc` guard semantics (which sites may legitimately see `None` vs. impossible states); Opus 4.6 applies the many-site conversion; codex review before merge.
- **Validation:** `.venv\Scripts\python.exe -m mypy model/ utils/` → 0; full suite; targeted no-document tests (operations on a closed/never-opened model must raise the same error as before).
- **Acceptance:** mypy job blocking + green; error behavior for None-doc paths byte-identical to before.
- **Rollback risk:** **Medium** — touches many model call sites; a wrong guard could turn a soft no-op into a raise. Mitigated by per-file revert-ability and no-document regression tests.
- **Status:** merged 2026-07-04 as PR #16 (squash c9b14c4; codex-reviewed: APPROVE WITH FOLLOW-UPS, docstring follow-up applied pre-merge).

### PR-8 — `refactor: fix utils layer violations; flip utils import contract blocking`

- **Scope:** Move the QMessageBox-showing helper out of `utils/helpers.py` into view (update all callers found by grep); relocate `model/tools/ocr_types.py` → `utils/ocr_types.py` (pure DTOs/enums) leaving a one-line re-export shim at the old path (model→utils is a legal direction); update `utils/preferences.py` import. Flip `utils-no-controller-view-model` from the advisory to the blocking lint-imports step. Check off the two TODOS.md items.
- **Files:** `utils/helpers.py`, `utils/ocr_types.py` (new), `model/tools/ocr_types.py` (shim), `utils/preferences.py`, view module receiving the helper, callers in `controller/`/`view/`, `.github/workflows/ci.yml`, `pyproject.toml`, `TODOS.md`.
- **Model:** Sonnet 5.
- **Validation:** `lint-imports` clean on the flipped contract; `test_ocr_types.py` + preferences tests; full suite.
- **Acceptance:** utils contract blocking + green; no caller left importing the moved helper from utils.
- **Rollback risk:** **Medium** — import moves ripple across layers, but the shim keeps old `ocr_types` imports alive, and CI now catches misses.
- **Status:** in review as PR #17 (branch `refactor/pr8-utils-contract`).

### PR-9 — `refactor: route view dialog model calls through controller; flip view contract blocking`

- **Scope:** Route `view/dialogs/optimize.py` (preset options) and `view/dialogs/ocr.py` (device availability) through `controller/pdf_controller.py`, following the existing dialog-wiring pattern. Add `PDFController.count_pdf_pages(path)` so `view/pdf_view.py` drops its merge-dialog `fitz.open()` probe. Permit remaining DTO-only imports via `ignore_imports` under the `view-no-model` contract with justification comments. Flip `view-no-model` blocking; delete the advisory lint-imports step entirely. Update `docs/ARCHITECTURE.md` + TODOS.md in the same commit (CLAUDE.md §5.3).
- **Files:** `view/dialogs/optimize.py`, `view/dialogs/ocr.py`, `view/pdf_view.py`, `controller/pdf_controller.py`, `pyproject.toml`, `.github/workflows/ci.yml`, `docs/ARCHITECTURE.md`, `TODOS.md`.
- **Model:** Fable 5 reviews the boundary design (what crosses via controller vs. permitted DTO); Sonnet 5 implements; codex review before merge.
- **Validation:** `lint-imports` — all 4 contracts blocking + clean; dialog workflow tests (`test_pdf_optimize_workflow.py`, `test_ocr_dialog.py`, `test_ocr_controller_flow.py`, merge tests); app smoke: open merge + optimize + OCR dialogs.
- **Acceptance:** all import contracts blocking and green; dialogs behave identically.
- **Rollback risk:** **Medium** — changes user-visible dialog wiring; covered by existing workflow tests, revert straightforward.
- **Status:** pending.

### PR-10 — `ci: stabilize functional suite from advisory triage`

- **Scope:** After ≥1 week of PR-3 advisory artifacts: apply `windows_only` marks where ubuntu import-fails, `needs_fixtures`/deselects for Linux pixel-diff font skew (do **NOT** loosen tolerances), file GitHub issues for any genuine cross-platform bug. Decision recorded in the PR: blocking leg = windows-latest; ubuntu stays advisory.
- **Files:** affected `test_scripts/` files, `.github/workflows/ci.yml`, `pyproject.toml` (if deselect list lives there).
- **Model:** Fable 5 for triage judgment (skew vs. real bug); fast-worker applies the marks.
- **Validation:** 3 consecutive fully-green windows-latest advisory runs with a stable pass count.
- **Acceptance:** stable pass count documented in the PR description; zero unexplained failures on the windows leg.
- **Rollback risk:** **None** — test-selection changes only.
- **Status:** pending (needs ≥1 week of PR-3 artifacts).
- **Advisory data so far** (first run, 2026-07-04, run 28692814887; details in the #12 comment):
  - windows-latest completed in 1m51s: 16 failed / 1547 passed / 33 skipped / 1 deselected. Failure clusters: 13× `test_no_jump_editor_geometry.py` + `test_core_interaction_audit.py` (+ probably `test_performance_script_runner.py`) fail — not skip — when the gitignored `test_files/*.pdf` fixtures are absent → `needs_fixtures` candidates; `test_security_packaging.py::test_built_wheel_and_sdist_exclude_dev_trees` is a REAL Windows console-encoding bug (charmap encode in the subprocess build; same class as the known local cp950 flake) → fix, don't mark.
  - ubuntu-latest segfaulted (exit 139) at ~90% through the suite (Qt offscreen teardown crash class predicted in the milestone risks). Needs junit/bisect isolation; ubuntu stays advisory.

### PR-11 — `ci: flip Windows functional suite to blocking; measure coverage`

- **Scope:** Remove `continue-on-error` from the windows-latest `test-functional` leg (ubuntu stays advisory, labeled as such). Add to the windows leg: `--cov --cov-report=term --cov-report=xml --cov-fail-under=0` (explicit 0 overrides pyproject's 75 so the report is advisory while tests block) + `coverage.xml` artifact. Record the CI-measured TOTAL in TODOS.md.
- **Files:** `.github/workflows/ci.yml`, `TODOS.md`.
- **Model:** Sonnet 5.
- **Validation:** blocking windows job green on this PR and one subsequent PR.
- **Acceptance:** functional regressions now block merges; CI coverage baseline captured.
- **Rollback risk:** **Low** — one-line flip back to advisory if unexpected flake emerges (then fix the flake, don't stay advisory).
- **Status:** pending.

### PR-12 — `ci: enforce evidence-based coverage gate`

- **Scope:** Set the windows leg's `--cov-fail-under=<CI-measured − 2, rounded down>` (CI measures lower than the local 78.7% because gitignored-fixture tests skip). If CI-measured ≥ 75, just drop the `=0` override. `pyproject.toml`'s `fail_under = 75` remains the local authority. Update `TEST_SCRIPTS.md` CI section, ci.yml header comments, TODOS.md.
- **Files:** `.github/workflows/ci.yml`, `test_scripts/TEST_SCRIPTS.md`, `TODOS.md`.
- **Model:** Sonnet 5.
- **Validation:** smoke test: a scratch branch deleting a covered production function must fail the coverage step; a normal PR passes.
- **Acceptance:** coverage gate active and evidence-based; M1 done — run the end-of-M1 smoke.
- **Rollback risk:** **Low** — threshold-only change.
- **Status:** pending.

## Ordering & dependencies

Strictly sequential spine: PR-1 → PR-2 → PR-3, then PR-10 → PR-11 → PR-12. The three debt tracks are independent of each other after PR-3 and interleave during PR-3's advisory data-collection week: E402 (PR-4→5), mypy (PR-6→7), import-linter (PR-8→9) — landed one at a time (serial subagents, one PR in review at a time).

## Milestone-level risks

- Qt offscreen teardown crashes on CI → isolate via `--deselect` + issue, never blanket `continue-on-error`.
- Linux rendering skew → ubuntu stays advisory in M1.
- Windows runner duration → 40-min budget; shard by directory later if >25 min.
- PyMuPDF drift → constraints file is the guard; bumps are deliberate PRs that also bump `.venv`.
- Env-var ordering → offscreen env must precede `QApplication` construction; conftest/`_bootstrap` preserve this.

## End-of-milestone verification

- CI gates accumulate: after PR-5 lint includes E402; after PR-7 mypy blocks; after PR-9 all 4 import contracts block; after PR-11 the windows functional suite blocks; after PR-12 coverage gates.
- End-of-M1 smoke: open a scratch PR that (a) adds an E402, (b) adds a `threading.Thread` in view/, (c) deletes a covered function — all three must fail CI.
- Post-milestone protocol: PITFALLS.md entries for gotchas found, ARCHITECTURE.md updates if structure changed, TODOS.md checkoffs, this plan archived to `plans/archive/`.
