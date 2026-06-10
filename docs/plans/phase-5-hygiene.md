# Phase 5 — Hygiene: pyproject.toml + OCR-cancel PITFALLS entry

**Status:** Ready to implement (Sonnet 4.6 deep-plan pass, 2026-06-11). Final phase.

## Verified facts (from planning pass)

- `pyproject.toml` does not exist in the repo or git history; `pip install -e ".[dev]"`
  fails today with "neither 'setup.py' nor 'pyproject.toml' found" — that failing output
  IS the red-light evidence for this phase (record it before creating the file).
- Current ruff baseline: **240 violations** under ruff 0.15.9 DEFAULT rules (E501 not in
  the default select set). CLAUDE.md §3.1's "113 remaining" is stale — update it to 240
  with the measurement date.
- Canonical app name: CyberSagaPDF → project name `cybersaga-pdf`.
- mypy gotcha on this machine: a stray `__init__.py` in the PARENT directory
  (`C:\Users\jiang\Documents\python programs\__init__.py`) makes `python -m mypy` fail
  with "not a valid Python package name"; document invoking mypy via
  `.venv\Scripts\python.exe -m mypy model/ utils/` instead.
- `.gitignore` lacks `*.egg-info/` and `dist/` — add them (editable install creates
  `cybersaga_pdf.egg-info/`).
- TODOS.md already tracks 5.1 under "Repo governance" ("Reconcile CLAUDE.md §3.1") —
  mark that item done as well as the Phase 5 line in the audit-remediation section.

## 5.1 Create `pyproject.toml`

Hard constraints (the implementer must verify each):

1. `[build-system]`: setuptools backend. The repo is a flat collection of top-level
   packages (model/, view/, controller/, utils/, src/, ...). Use EXPLICIT
   `[tool.setuptools]` package discovery (e.g. `packages.find` with an `include` list of
   the real top-level packages, or an explicit `packages` list) so editable install works
   without restructuring and without accidentally packaging test_scripts/docs.
2. `[project]`: name = "cybersaga-pdf", version 0.1.0 (or read an existing version
   constant if one exists), requires-python = ">=3.9" (per CLAUDE.md), dependencies
   mirroring requirements.txt (read it; preserve any intentionally-lazy notes as
   comments), `[project.optional-dependencies] dev = ["ruff", "mypy", "pytest"]`
   (optional-requirements.txt stays separate — it is platform/feature extras, not dev
   tooling; pikepdf remains there per Phase 1).
3. `[tool.ruff]`: target-version = "py39". CRITICAL: the config must reproduce the
   current default-rule behavior EXACTLY — after creating the file,
   `python -m ruff check . --statistics` must report the same 240 (or fewer) violations.
   Ruff's defaults = E4/E7/E9 + F; explicitly encoding `lint.select = ["E4", "E7", "E9", "F"]`
   preserves the default set. Do NOT enable E501.
4. `[tool.mypy]`: permissive/gradual (`ignore_missing_imports = true`, no strict flags)
   so `mypy model/ utils/` at least runs. Check `python -m mypy --version` availability.
5. `[tool.pytest.ini_options]`: `testpaths = ["test_scripts"]`. Verify pytest still
   collects the same count: `python -m pytest --collect-only -q | tail` before/after.
6. Validate editable install WITHOUT polluting the user's env: run
   `python -m pip install -e ".[dev]" --dry-run` first; if a real install is needed to
   prove the gate, do it in the project `.venv` (`.venv\Scripts\pip install -e ".[dev]"`)
   — that venv is the app's own. Record output. If a real editable install is performed,
   confirm the app still imports (`.venv\Scripts\python.exe -c "import model, view, controller, utils"`)
   — note: a plain `pip install --dry-run` may not exercise the build backend fully; at
   minimum run `python -m pip wheel . --no-deps -w %TEMP%` or `python -m build --sdist`
   equivalent check if available, else rely on the .venv editable install as the gate.

## 5.2 PITFALLS entry — cooperative OCR cancellation

Verify the `_OcrWorker.request_cancel` mechanics in controller/pdf_controller.py
(find current line numbers — they shifted during Phases 1–4), then append:

```
## Cooperative OCR cancellation: per-page only
**Area:** controller/pdf_controller.py _OcrWorker
**Symptom:** Cancel appears to hang during a long page
**Cause:** request_cancel() is checked between pages, not inside a single fitz call
**Fix:** Accepted design. A slow page completes before cancel takes effect.
**File:** controller/pdf_controller.py:<current-lines>
```

## Other files in the same commit

- `CLAUDE.md` §3.1: violation count 113 → 240 (measured 2026-06-11, ruff 0.15.9 default
  rules, E501 unselected); add the mypy parent-`__init__.py` note + venv invocation.
- `.gitignore`: append `*.egg-info/` and `dist/` under a "Packaging artifacts" comment.
  CAUTION: `.gitignore` currently has UNRELATED uncommitted user modifications — edit the
  file but stage ONLY if the unrelated hunk can be excluded; if not separable, append the
  lines and stage the whole file ONLY after confirming the pre-existing modification is
  a deletion-of-lines the user made intentionally (check `git diff .gitignore` first; if
  the user's hunk is unrelated, use `git add -p`-equivalent or leave .gitignore unstaged
  and note it in the report — do NOT silently commit unrelated changes).
- `TODOS.md`: Phase 5 done; "Reconcile CLAUDE.md §3.1" (Repo governance) done; the
  audit-remediation section should end fully checked (verify Phases 0–4 lines are all
  checked; 4.3 deferred item remains open by design).
- `docs/plans/phase-5-hygiene.md` (this file).

## Verification gates

```powershell
python -m ruff check . --statistics            # ≤ 240, ideally identical set
python -m pytest --collect-only -q             # same collection count as before
python -m pytest test_scripts -q --tb=line -p no:cacheprovider   # full gate: 1281 passed / 21 skipped / 0 failed
.venv\Scripts\pip install -e ".[dev]"          # succeeds (was: file-not-found error)
.venv\Scripts\python.exe -m mypy model/ utils/ # runs (errors allowed — gradual)
```

## Commit

```
feat(hygiene): add pyproject.toml + OCR cancel pitfall (Phase 5)

- pyproject.toml: name=cybersaga-pdf, requires-python>=3.9, dev group
  (ruff/mypy/pytest), [tool.ruff] encodes the exact default rule set so the
  violation count stays at 240, [tool.mypy] gradual/permissive,
  [tool.pytest.ini_options] testpaths=["test_scripts"]. pip install -e ".[dev]"
  now works (was: "neither setup.py nor pyproject.toml found").
- docs/PITFALLS.md: add "Cooperative OCR cancellation: per-page only" entry.
- CLAUDE.md 3.1: update stale 113-violation count to 240 (ruff 0.15.9 default
  rules; E501 not selected; measured 2026-06-11); document the parent-dir
  __init__.py mypy workaround.
- TODOS.md: Phase 5 checked; "Reconcile CLAUDE.md 3.1" checked.
- .gitignore: add *.egg-info/, dist/.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```
