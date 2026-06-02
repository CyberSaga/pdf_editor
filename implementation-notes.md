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

## Baseline test run (BEFORE any patch, global Python)

`python -m pytest test_scripts/` → **7 failed, 1156 passed, 21 skipped** (184 s).

The 7 failures are ALL pre-existing and unrelated to the security work — every one
is in `test_scripts/test_no_jump_editor_geometry.py` (click-to-edit geometry /
textbox-reopen-shrink pipeline). They fail on the pristine tree before I touched
anything. I do not edit these (boundary: new tests only), and they are not in the
F1–F9 scope. The success criterion I hold myself to: **no new failures beyond these
7**, and the security-relevant suites stay green.

Pre-existing failures to ignore as regressions:
- test_no_jump_editor_geometry.py::test_click_to_edit_real_geometry_pipeline
- test_no_jump_editor_geometry.py::test_click_to_edit_qtest_integration[colored/complexed/vertical]
- test_no_jump_editor_geometry.py::test_reopen_same_textbox_cycles_do_not_cumulate_shrink[colored/complexed/vertical]

## Decisions / deviations

### P2 — IPC socket user-isolation (single_instance.py) — DONE
- `_listen_server`: `server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)`
  before `listen()`. Verified the scoped enum + `socketOptions()` membership test on
  PySide6 6.9.2 (`SocketOption.UserAccessOption` value 1).
- Added `_forwarded_argv_is_acceptable(argv)` and gated the `on_message` call in
  `_handle_socket_message` on it. Rejects (ack `0`) any message where an *absolute*
  item is missing or not `.pdf`. Followed the spec's "absolute-only" rule rather than
  the inline `write/return`, folding the reject into the existing single-ack path so
  the disconnect flow stays intact.
- Design note: validation lives in `_handle_socket_message` (the cross-process socket
  boundary), NOT in `send_to_running_instance`'s in-process shortcut. That shortcut is
  same-process (trusted) and is what the existing forwarding tests exercise — which is
  why `test_single_instance_forwarding.py` (forwards relative `x.pdf`) still passes:
  it never crosses the socket. The real untrusted peer always hits the validated path.

### P3 — Absolute subprocess binary paths — DONE (with one documented deviation)
- **win_driver.py:** added `import os` + module constant
  `_RUNDLL32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "rundll32.exe")`,
  evaluated once at import; the `open_printer_properties` fallback now launches
  `[_RUNDLL32, ...]`. Full fix per spec.
- **linux_driver.py:** the two `lpstat` sites (`list_printers`, `get_default_printer`)
  now capture `lpstat_path = shutil.which("lpstat")` and pass it to `subprocess.run`.
- **DEVIATION (important):** the spec also wanted `_submit_via_lp` changed to use the
  absolute `shutil.which("lp")` path. I did **NOT** make that change. The existing
  test `test_linux_driver_overrides.py::test_submit_via_lp_omits_hardware_options_when_not_overridden`
  asserts `captured_cmd[:5] == ["lp", "-n", "3", "-d", "Printer A"]` — it pins the
  bare `"lp"` token, and its fake `which` returns `/usr/bin/lp`. Switching the call
  site to the absolute path makes `cmd[0] == "/usr/bin/lp"`, which would break that
  test. The boundary forbids editing current tests, and "all current tests pass" is a
  hard requirement, so the two constraints make the `_submit_via_lp` fix impossible
  without violating one of them. **Tradeoff:** `_submit_via_lp` keeps bare `"lp"`.
  Residual risk is Low (per investigation-review.md: `/usr/bin` is not user-writable
  by default and CWD is not on `$PATH`, so Linux `execvp` planting is not a practical
  vector). The `lpstat` sites and the Windows `rundll32` site — the higher-value
  surfaces — are fully fixed. **If you want `_submit_via_lp` hardened too, the
  existing test must be amended (out of my boundary), so flag it and I'll do it.**
- There is no `lpoptions` call in the codebase (spec mentioned one "if present").

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
