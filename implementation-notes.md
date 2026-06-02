# Implementation Notes — Security Patch Work

Running log of decisions, deviations from the spec, and tradeoffs while patching
the F1–F9 findings per `patch-weaknesses-found-in-immutable-knuth.md`.

## Environment facts (discovered, not in spec)

- **There is no `pyproject.toml`** in the repo, despite CLAUDE.md §3.1 referencing
  one. No `pytest.ini`/`setup.cfg`/`tox.ini` either. Tests run from the repo root
  via `python -m pytest test_scripts/`; `test_scripts/conftest.py` handles `sys.path`
  and forces `QT_QPA_PLATFORM=offscreen`. So "ruff config in pyproject.toml" does not
  exist — I run `python -m ruff check` with defaults.
- **Two Python environments.** The project `.venv` (Python 3.10.0) has only the core
  stack (PyMuPDF 1.27.1, PySide6) and is missing `pytest`, `surya`, `torch`,
  `pywin32`. The **global** Python 3.10.0
  (`C:\Users\jiang\AppData\Local\Programs\Python\Python310`) has the full stack:
  pytest, fitz (PyMuPDF 1.25.5), PySide6 6.9.2, Pillow 12.1.1, surya, torch,
  transformers 4.57.6, win32print. **The test suite runs under the global Python**,
  so all commands below use bare `python -m pytest` (global), not the venv.
- Global Pillow is already 12.1.1, so the P8 floor bump (`Pillow>=12.1.1`) is already
  satisfied at runtime here — the patch only raises the declared floor.
- 1184 tests collected under `test_scripts/`.
- ruff 0.15.9 available in global Python; used as `python -m ruff check`.

## Workflow per patch (CLAUDE.md §5.1 Red-Light first)

1. Write new failing test(s) in `test_scripts/` (never edit existing tests — boundary).
2. Run new test, confirm Red.
3. Implement patch.
4. Run new test + relevant existing tests, confirm Green.
5. `ruff check` on touched files.
6. Atomic commit.
7. Run `codex:review` (and/or `codex:adversarial-review`) on the commit; record the
   verdict here; select the next step from it.

## Execution order (from spec)

P6 → P3 → P2 → P4 → P5 → P7 → P1 → P8

## Decisions / deviations

### P6 — Release logging level (main.py) — DONE
- Implemented exactly per spec: `level = DEBUG if os.environ.get("PDF_EDITOR_DEBUG") else WARNING`.
- Test note: `logging.basicConfig` is a no-op when the root logger already has
  handlers, and pytest installs its own. The new test
  (`test_security_logging_level.py`) detaches root handlers in a context manager,
  calls `_configure_logging()`, asserts `root.level`, then restores the saved
  handlers/level so pytest's log capture for other tests is unaffected.
- Dropped the usual `sys.path.insert` boilerplate from the new test — `conftest.py`
  already puts the repo root on `sys.path`, and keeping the manual block tripped
  ruff E402. New test passes `ruff check` clean.
- Commit staging policy: each patch commit includes only its source/test files plus
  this notes file. The untracked planning docs (`*.md`) and scan artifacts
  (`bandit-report.json`, `semgrep-report.json`, `baseline_test_run.log`) are left
  unstaged — they are inputs/artifacts, not part of the patch.
