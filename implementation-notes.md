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

## FINAL VERIFICATION (after all 9 commits)

Full suite: `python -m pytest test_scripts/` → **8 failed, 1189 passed, 21 skipped**.
- 7 failures = the recorded pre-existing baseline (`test_no_jump_editor_geometry.py`),
  untouched by this work.
- 1 failure = `test_print_subprocess_runner.py::test_runner_heartbeat_events_prevent_false_stall`,
  which **passes in isolation** (re-ran alone → 1 passed). This is the timing-sensitive
  flake already documented in TODOS.md line ~107 ("can fail during long pytest runs …
  passes when run alone"); none of my patches touch `subprocess_runner.py`.
- **Net: zero new persistent failures vs baseline.** All 34 new security tests pass.
- `ruff check` clean on every touched source file and every new test file. The only
  ruff hits in the repo are 2 pre-existing violations in `scripts/ux_signoff_agent.py`
  (F401 @35, E401 @481) that predate and are outside my edits.

Commits (atomic, one per patch + one regression fix), oldest→newest:
P6 → P3 → P2 → P4 → P5 → P7 → P1 → (P1 OCR follow-up) → P8.
Each got a `codex:review` (P1 also a `codex:adversarial-review`, verdict: approve/Ship).
Codex verdicts were clean or inconclusive (sandbox flakiness, see note above); no codex
finding required a change. The real correctness gate was the test suite + ruff.

## Decisions / deviations

### P8 — Raise Pillow floor (optional-requirements.txt) — DONE
- `Pillow>=9.0` → `Pillow>=12.1.1` with the pip-audit comment block.
- Did NOT touch `surya-ocr`/`torch` floors — per spec, the transformers CVE fix needs
  confirming which surya release pins `transformers>=5.0.0rc3` without breaking the
  OCR adapter API. Logged as an open item in TODOS.md along with the pip-audit CI gate
  and F9 (pin/verify OCR weights).
- Added a new locking test (`test_security_pillow_floor.py`) that parses
  optional-requirements.txt and asserts the Pillow floor ≥ 12.1.1, so the floor can't
  be silently lowered later. (Runtime Pillow here is already 12.1.1, so this is a
  spec/floor regression guard, not a runtime check.)

### P1 — PDF resource guards (pdf_model.py, ocr_tool.py) — DONE
- Added module consts `_MAX_PDF_BYTES=512MB`, `_MAX_PAGES=5000`, `_MAX_PIXMAP_PX=40M`
  and helpers `_guard_before_open(path)` / `_safe_render_scale(page, scale)` in
  pdf_model.py (after the optimizer re-exports).
- `open_pdf`: size guard `_guard_before_open(src_path)` placed right after the
  `is_file()` check and BEFORE the append/`close_all_sessions` block, so an oversized
  file is rejected without first tearing down the user's open sessions. Page-count
  guard placed after the password-auth block and before the len==0 fallback; it
  `doc.close()`es then raises.
- **Exception-type note:** `open_pdf` wraps every non-`PermissionError` in
  `RuntimeError("開啟PDF失敗: …")`. So although the guards raise `ValueError`, callers
  of `open_pdf` see `RuntimeError` with the original message embedded. I deliberately
  did NOT add an `except ValueError: raise` shortcut — that would also change the
  long-standing wrapping of the existing line-642 `ValueError`/`FileNotFoundError`
  paths and risk other callers. The new tests therefore assert on the message
  substring ("size limit" / "page limit") rather than the exact type, and unit-test
  the helpers directly for the clean `ValueError`/scale math.
- Raster clamps applied at the spec's named sites only — export (`get_page_pixmap`
  call), deskew gray-array (`_render_page_gray_array`), straighten (`straighten_page`),
  and the OCR loop (`ocr_tool.ocr_pages`, via a local `from model.pdf_model import
  _safe_render_scale` to dodge an import cycle). I did NOT clamp centrally inside
  `get_page_pixmap`/`render_page_pixmap`, to avoid perturbing the ~30 render tests;
  for normal pages `_safe_render_scale` is a no-op so behaviour is unchanged (verified
  deskew/render/ocr/export/merge/optimize suites: 60 passed, 4 skipped).
- **Did NOT add a recursion cap** to `_discover_form_nested_invocations` — the spec
  and investigation-review.md both confirm it is depth-1 (not recursive), so the
  CWE-674 sub-claim does not apply.
- **0.1-floor tradeoff:** `_safe_render_scale` keeps a `max(0.1, scale)` floor per the
  spec, so an extreme page (≈1e6 pt/side) still renders above the 40 MP cap at scale
  0.1. Accepted: scaling below 0.1 yields a useless render, and such pages are
  exotic. Documented in the helper's docstring and tested (`floors_at_min`).
- **TDD-order slip (transparency):** for P1 I wrote the implementation before the
  test file, then retroactively confirmed Red by `git stash`-ing only the two impl
  files (the new test is untracked, so it stayed) — collection ERROR'd because the
  helpers didn't exist — then `git stash pop` and confirmed Green (8 passed). The
  Red→Green evidence is genuine; the authoring order just wasn't test-first for this
  one patch.

### P1 follow-up — OCR clamp regression fix
- The full-suite run after P1 surfaced **8 new failures**, all in
  `test_ocr_tool_surya.py::test_ocr_pages_*`. Cause: the OCR clamp did
  `self._model.doc[page_num - 1]`, but that test's `_FakeDoc` implements only
  `__len__`/`__bool__`, not `__getitem__` → `TypeError: not subscriptable`. A real
  fitz document is always subscriptable, so this only affected the mock.
- Fix (could not edit the test — boundary): wrapped the page lookup in
  `try/except (TypeError, IndexError, AttributeError)` and fall back to the requested
  `render_scale` when geometry can't be introspected. Real attacker PDFs still hit
  the clamp; mocks degrade cleanly. Re-ran: `test_ocr_tool_surya.py` +
  `test_security_pdf_resource_guards.py` = 28 passed.
- Lesson logged: a guard that introspects the live document object must tolerate the
  test doubles already in the suite. I should have run the OCR suite (not just the
  guard + render/deskew suites) before committing P1.

### P7 — CUA agent action allowlist (ux_signoff_agent.py) — DONE
- Added module `_ALLOWED_CUA_ACTIONS = frozenset({"click","double_click","scroll",
  "move","screenshot"})` and a guard at the top of `_execute_cua_action` that raises
  `PermissionError` for any other type. This makes the existing `type`/`key` branches
  unreachable by design (that is the F3 fix — block keyboard-driving actions).
- No existing test calls `_execute_cua_action` (they mock `_run_agent_on_pdf`), so
  blocking `type`/`key` breaks nothing. `test_ux_signoff_agent.py` still passes.
- Pre-existing ruff violations in this file (F401 `PIL.Image` unused @ line 35, E401
  multiple imports @ line 481) are untouched by my edit (~line 198) and are part of
  the repo's tracked existing-violation set; my added lines are ruff-clean. Did NOT
  fix them — out of scope for the security patch, keeps the commit focused.
- I did NOT add the optional window-bounds geometry check from the F3 remediation
  example (`window_rect.contains(...)`). The spec's P7 scope is the action-type
  allowlist only; bounds-checking needs a window-rect plumbed into the call, which is
  a larger dev-harness change beyond the agreed patch. Allowlist alone closes the
  keyboard-injection vector, which is the material risk.

### P5 — Temp-unlink error visibility (dispatcher.py) — DONE
- Added module `logger`; the `print_pdf_bytes` finally-block `except Exception: pass`
  now logs at debug (`logger.debug("Failed to remove print temp file %s: %s", ...)`).
  Still catches broadly so cleanup failure never masks the print result.
- Test note: the test patches `Path.unlink` to raise `PermissionError`, asserts the
  result still returns and a debug record is emitted, then deletes the leaked temp
  file via `os.unlink` (the real unlink, not the patched one) so no junk is left in
  the system temp dir.

### Codex review reliability (environment note)
- The codex companion review runs codex in a sandbox that shells out to PowerShell;
  on this Windows box those git/PowerShell sandbox commands intermittently fail
  ("Command failed/declined", and once "sandbox failed to start"). P6/P3/P2 returned
  clean verdicts anyway; P4's review was inconclusive ("couldn't reliably inspect the
  diff"). Treating codex verdicts as a secondary signal — the primary gate is the new
  + existing pytest suite (compared against the recorded 7-failure baseline) plus
  `ruff check`. I run a codex review per commit regardless and will push for a solid
  adversarial review on the largest patch (P1).

### P4 — Watermark JSON coercion on load (watermark_tool.py) — DONE (schema-adapted)
- Added module-level `_WM_TEXT_MAX=5000`, `_WM_PAGES_MAX=10000`, and `_coerce_wm(wm)`;
  rewrote the `_load_watermarks_from_doc` append loop to drop non-dicts and run each
  entry through `_coerce_wm`.
- **Deviation from spec snippet:** the spec's `_coerce_wm` carried a `font_color_name`
  key and defaulted `font` to `""`. The real watermark schema (from `add_watermark`)
  has NO `font_color_name`, and the renderer (`watermark_rendering.py`) never reads it;
  it reads text/angle/opacity/font_size/color/font/offset_x/offset_y/line_spacing/pages.
  So I adapted coercion to the actual schema: dropped `font_color_name`, defaulted
  `font` to `"helv"` (matching `add_watermark`), and preserved `offset_x/offset_y/
  line_spacing` (float) and `color` (tuple) when present. This keeps full round-trip
  fidelity — verified `test_feature_conflict.py`'s save→reopen→get_watermarks C6 case
  still passes.
- Kept the `isinstance(wm, dict)` guard before coercion: `_coerce_wm` uses `wm.get(...)`,
  which would raise `AttributeError` (uncaught inside the helper) on a list/str entry
  and abort the whole load via the outer except. The guard makes bad entries skip
  cleanly.

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

## Follow-up task series (user-requested, after the P1–P8 series)

A second batch of six tasks was requested after the initial F1–F9 patch series, to
close residual gaps and add CI/deployment hardening. Same workflow: new tests only
(with ONE explicitly authorized exception — see Task 1), atomic commit per task,
codex review per commit (record inconclusive if the sandbox fails), pytest+ruff as
the real gate.

### Task 1 — `_submit_via_lp` absolute-path hardening (F4) — DONE
- The earlier P3 work left `_submit_via_lp` on the bare `"lp"` token because the
  existing `test_linux_driver_overrides.py::test_submit_via_lp_omits_hardware_options_when_not_overridden`
  pinned `captured_cmd[:5] == ["lp", ...]` and the boundary forbade editing tests.
- The user **explicitly authorized this one test edit** as the exception. Changes:
  - `linux_driver._submit_via_lp` now does `lp_path = shutil.which("lp")` and uses
    `cmd = [lp_path, ...]` (absolute path; the pre-existing `None`→unavailable guard
    is preserved, just reworded to capture the path).
  - Updated the pinned assertion to expect `["/usr/bin/lp", "-n", "3", "-d", "Printer A"]`
    (the fake `which` resolves `"lp"`→`/usr/bin/lp`). This is the only existing-test
    edit in the whole engagement, and it was authorized.
  - Added `test_security_subprocess_paths.py::test_linux_submit_via_lp_uses_absolute_lp_path`
    locking argv[0] to an absolute path, and updated that file's scope-note docstring
    (all three subprocess sites are now covered).
- Verified: `test_linux_driver_overrides` + `test_security_subprocess_paths` = 10 passed;
  the full print/subprocess slice (`-k "print or linux_driver or win_driver or dispatcher
  or subprocess"`) = 90 passed. ruff clean on changed lines (the 2 E402 in
  test_linux_driver_overrides.py pre-date this work — confirmed via `git stash`).

### Task 2 — surya-ocr / transformers floor — BLOCKED (do not bump) + Pillow reconcile
- **Investigated, then BLOCKED the transformers 5.x bump.** Pulled every relevant
  surya-ocr release's `requires_dist` from PyPI. No surya-ocr release (through latest
  0.20.0) *requires* `transformers>=5.0.0rc3`; the newest only allow it via unbounded
  `>=4.56.1`, and releases ≤0.16 actively excluded 5.x. pip-audit confirms the two
  transformers CVEs: `CVE-2026-1839` (fix only in 5.0.0rc3+) and `PYSEC-2025-217`
  (**no fix exists**). Bumping would be an untested surya×transformers-5 combination
  and still wouldn't close PYSEC-2025-217. Full matrix + reasoning recorded in TODOS.md
  per the task's "if incompatible/unconfirmable → don't change, record matrix" branch.
- **Discovered + fixed a P8 regression:** the P8 `Pillow>=12.1.1` floor was placed in
  optional-requirements.txt *next to* surya-ocr, but every surya release caps
  `pillow<11` → the file was **unsatisfiable** (`pip install -r optional-requirements.txt`
  could not resolve). pip-audit also shows Pillow 12.1.1 now has CVEs fixed in 12.2.0.
  - **Reconciliation (deviation from the original single-file layout):** split the OCR
    extra into a new mutually-exclusive `ocr-requirements.txt` (surya-ocr + torch, with
    a security header documenting the pillow<11 + transformers-CVE residual). Raised the
    *core* image-feature Pillow floor to `>=12.2.0` in optional-requirements.txt
    (deskew/straighten/optimize use Pillow directly, independent of OCR). This makes
    each file individually satisfiable and lets non-OCR users get a secured Pillow.
  - Updated my own P8 test `test_security_pillow_floor.py` (floor→12.2.0 + a separation
    assertion that surya-ocr is NOT in optional-requirements.txt) and added
    `test_security_ocr_requirements.py` (surya-ocr present in the OCR file; transformers
    not pinned ≥5). 5 passed, ruff clean. No existing tests edited.
  - **Why a file split rather than just lowering the floor:** keeping surya + a secured
    Pillow in one file is mathematically impossible (`<11` vs `>=12.2`). Lowering Pillow
    back below 11 would reintroduce the image-parser CVEs *and* make the Task 4 pip-audit
    gate fail on optional-requirements.txt. The split confines the unavoidable OCR
    residual to an opt-in file while keeping the audited core set clean.

### Task 3 — F9 OCR weight revision pin + SHA256 verification — DONE
- New module `model/tools/ocr_weights.py` (model layer, no Qt). Read surya's loader
  to design it correctly: surya checkpoints are env-configurable pydantic
  `BaseSettings` fields (`DETECTOR_MODEL_CHECKPOINT`, `FOUNDATION_MODEL_CHECKPOINT`,
  `RECOGNITION_MODEL_CHECKPOINT`), the download path (`surya.common.s3`) does **no**
  hash check, and a non-`s3://` checkpoint string loads from a **local dir** via
  `super().from_pretrained`. `surya/__init__.py` is empty and importing `surya` does
  not import `surya.settings`, so setting env vars before the lazy surya import (in
  `_ensure_loaded`) is sufficient; I also patch a live settings object defensively.
- `enforce_weights_policy()`:
  - No bundle: pins the checkpoint revisions (online but revision-locked).
  - Bundle (`PDF_EDITOR_OCR_WEIGHTS_DIR`): `verify_weights_dir` SHA256-checks every
    file in `WEIGHTS_MANIFEST`, redirects checkpoints to the bundle's local subdirs,
    and forces `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`. **Fails closed**: missing file,
    hash mismatch, or empty manifest → `OcrWeightsError` (load refused).
- Wired into `_SuryaAdapter._ensure_loaded` right after the predictor-cache check and
  **before** the surya import, so unverified weights are never constructed.
- **Red-Light first:** wrote `test_security_ocr_weights.py` (13 tests) first; the
  adapter-wiring test failed Red (`ocr_tool` had no `enforce_weights_policy`), the 12
  pure tests passed; then added the import + call → 33 passed (incl. all existing
  `test_ocr_tool_surya.py`). ruff clean.
- **Scope decision (matches the task's fallback):** the verification *layer* + revision
  *pin* are implemented and tested. The actual weights **bundle artifact** is not
  shipped (large binaries, needs a vetted offline build), so `WEIGHTS_MANIFEST` is empty
  and a configured-but-unmanifested bundle fails closed. Recorded as the open "F9 bundle
  distribution" TODO; update process documented in `docs/ocr-weights-verification.md`.
- **Interpretation note:** "hash matches → loading allowed" is asserted at the policy
  layer (`enforce_weights_policy` returns local checkpoints + offline flags without
  raising). A full end-to-end model load with real weights is infeasible in CI, so the
  test asserts the policy permits the load rather than running inference.

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
