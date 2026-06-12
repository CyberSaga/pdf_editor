# Security Weakness Patch Work - Organized Report

Source: `weakness_patch.md`

This report reorganizes the execution transcript into a readable summary of what
was done, what was verified, and what remains open.

## Executive Summary

All evidence-backed findings from
`patch-weaknesses-found-in-immutable-knuth.md` were addressed in priority order.
The work was implemented as atomic commits, each with new tests, focused
verification, and review notes captured in `implementation-notes.md`.

The patch series hardened PDF resource handling, subprocess invocation, IPC
forwarding, CUA agent actions, watermark metadata loading, logging defaults,
temporary print-file cleanup visibility, and dependency floors.

## Patch Inventory

| Patch | Finding | Status | Main Change |
|---|---|---:|---|
| P6 | F7 | Done | Production logging now defaults to `WARNING`; `DEBUG` is enabled only with `PDF_EDITOR_DEBUG`. |
| P3 | F4 | Done, with one documented deviation | Windows `rundll32` uses an absolute `System32` path; Linux `lpstat` uses an absolute `shutil.which` path. |
| P2 | F6 | Done | `QLocalServer` is user-scoped and forwarded socket messages validate absolute PDF paths. |
| P4 | F8 | Done | Embedded watermark JSON is coerced, bounded, and schema-validated on load. |
| P5 | F5 | Done | Temporary print-file unlink failures are logged at debug level instead of silently swallowed. |
| P7 | F3 | Done | CUA action execution now allows only mouse/screenshot actions and blocks keyboard-driving actions. |
| P1 | F1 | Done | PDF open/render paths now enforce file-size, page-count, and pixmap-pixel guards. |
| P1-fix | F1 | Done | OCR render clamping now tolerates non-introspectable test doubles while still clamping real documents. |
| P8 | F2 | Done | `Pillow>=12.1.1` is enforced with a regression test. |
| F9 | F9 | Deferred | OCR model weight pinning/hash verification was logged as future offline-bundle work. |

## Execution Timeline

### 1. Baseline And Environment

- Confirmed there is no `pyproject.toml`, despite references in project notes.
- Confirmed tests run from the repository root through `test_scripts/conftest.py`.
- Identified the usable test environment as the global Python 3.10 installation,
  not the project `.venv`.
- Confirmed `ruff 0.15.9` is available.
- Established baseline test result before patching:
  `7 failed, 1156 passed, 21 skipped`.
- Confirmed all 7 baseline failures were pre-existing
  `test_no_jump_editor_geometry.py` failures unrelated to the security work.

### 2. P6 - Logging Level

- Added tests around `_configure_logging()`.
- Changed logging so release startup defaults to `WARNING`.
- `DEBUG` logging is now opt-in via `PDF_EDITOR_DEBUG`.
- Removed unnecessary test path boilerplate after `conftest.py` handled import setup.
- Verification: new logging tests and relevant main tests passed; ruff clean.
- Review: Codex review returned clean.

### 3. P3 - Subprocess Binary Paths

- Hardened Windows printer-properties fallback by launching absolute
  `System32\rundll32.exe`.
- Hardened Linux `lpstat` calls by resolving them through `shutil.which`.
- Left `_submit_via_lp` on bare `"lp"` because an existing test pins the exact
  command token and the work boundary forbade editing existing tests.
- Verification: new subprocess-path tests and existing print-driver tests passed;
  ruff clean.
- Review: Codex review returned clean.

### 4. P2 - IPC Socket Isolation

- Added `QLocalServer.SocketOption.UserAccessOption` before listening.
- Added forwarded-argv validation at the real socket trust boundary.
- Rejected absolute forwarded paths that are missing or not `.pdf`.
- Kept existing in-process forwarding behavior untouched because it bypasses the
  socket and is same-process trusted.
- Verification: new IPC tests and existing forwarding tests passed; ruff clean.
- Review: Codex review returned clean.

### 5. P4 - Watermark JSON Coercion

- Added bounded coercion for loaded watermark metadata.
- Dropped invalid entries instead of letting malformed data poison the load path.
- Adapted the implementation to the real watermark schema rather than the spec's
  nonexistent `font_color_name` field.
- Preserved renderer-required fields: `text`, `angle`, `opacity`, `font_size`,
  `color`, `font`, `offset_x`, `offset_y`, `line_spacing`, and `pages`.
- Verification: new coercion tests and watermark round-trip tests passed; ruff clean.
- Review: Codex review was inconclusive because of sandbox startup flakiness.

### 6. P5 - Print Temp Cleanup Visibility

- Replaced silent broad cleanup swallowing with debug logging.
- Preserved behavior that cleanup failure must not mask the print result.
- Added a test that simulates `Path.unlink` failure and verifies a debug log record.
- Verification: new test passed; ruff clean.
- Review: Codex review returned clean.

### 7. P7 - CUA Action Allowlist

- Added an explicit action allowlist:
  `click`, `double_click`, `scroll`, `move`, and `screenshot`.
- Blocked unsupported actions, including `type` and `key`, with `PermissionError`.
- Left pre-existing ruff violations in `scripts/ux_signoff_agent.py` untouched
  because they were outside the edited region and out of scope.
- Verification: new CUA tests and existing agent tests passed.
- Review: Codex review returned clean.

### 8. P1 - PDF Resource Guards

- Added maximum PDF size guard: `512 MB`.
- Added maximum page-count guard: `5000 pages`.
- Added maximum raster pixmap guard: `40 MP`.
- Applied guards at PDF open and the named raster sites:
  export, deskew, straighten, and OCR rendering.
- Avoided central render-path changes to reduce regression risk across existing
  render tests.
- Added helper tests and integration tests.
- Verification: guard tests and relevant open/render/deskew/OCR/export suites passed.
- Review: adversarial Codex review returned approve/ship.

### 9. P1 Follow-Up - OCR Test-Double Compatibility

- Full-suite verification revealed 8 new OCR test failures after P1.
- Root cause: the OCR clamp attempted `self._model.doc[page_num - 1]`, but existing
  `_FakeDoc` test doubles were not subscriptable.
- Fixed by falling back to the requested render scale when page geometry cannot be
  introspected.
- Real PyMuPDF documents still hit the clamp.
- Verification: OCR suite and PDF resource guard tests passed; ruff clean.

### 10. P8 - Pillow Dependency Floor

- Raised the optional dependency floor from `Pillow>=9.0` to `Pillow>=12.1.1`.
- Added a regression test that parses `optional-requirements.txt` and prevents the
  floor from being lowered.
- Logged remaining dependency hygiene work in `TODOS.md`.
- Verification: new dependency-floor test passed.
- Review: Codex review was inconclusive because of sandbox startup flakiness.

## Verification Results

Final full-suite result:

```text
8 failed, 1189 passed, 21 skipped
```

Failure analysis:

- 7 failures were the known pre-existing `test_no_jump_editor_geometry.py` baseline
  failures.
- 1 failure was the documented timing-sensitive
  `test_runner_heartbeat_events_prevent_false_stall` flake.
- The heartbeat test passed when run in isolation.
- All 34 new security tests passed.
- Touched source and new tests were ruff-clean.
- The only ruff findings left in the repository were pre-existing violations in
  `scripts/ux_signoff_agent.py`.

Conclusion: the patch series introduced no new persistent test failures beyond the
known baseline and documented timing flake.

## Important Deviations And Tradeoffs

### `_submit_via_lp` Was Not Hardened

The plan wanted Linux `lp` submission to use an absolute path. That change was not
made because an existing test asserts the command starts with bare `"lp"`, and the
work boundary prohibited editing existing tests.

Risk assessment recorded in the transcript:

- Residual risk is low.
- `/usr/bin` is not user-writable by default.
- Current working directory is not normally on `$PATH`.
- The higher-value Windows `rundll32` and Linux `lpstat` surfaces were hardened.

### Watermark Coercion Followed The Real Schema

The spec referenced `font_color_name`, but that field is not used by the actual
watermark renderer. The implementation follows the live schema instead to preserve
round-trip behavior.

### F9 Was Deferred

OCR model weight pinning and hash verification require offline-bundle
infrastructure. The work was logged in `TODOS.md` rather than patched directly.

### Codex Reviews Were A Secondary Signal

Some Codex review runs failed or were inconclusive because of Windows PowerShell
sandbox startup issues. Per-commit tests, focused suites, ruff, and the final
baseline comparison were treated as the authoritative gate.

## Files And Documentation Updated During The Patch Series

- `implementation-notes.md` records environment facts, decisions, deviations, and
  verification results.
- `TODOS.md` records remaining dependency hygiene and OCR weight-pinning work.
- New and updated security regression tests were added under `test_scripts/`.
- Source changes were made in the relevant application modules for logging,
  subprocess handling, IPC, watermark loading, print cleanup, CUA action execution,
  PDF resource guarding, OCR rendering, and dependency declarations.

## Open Follow-Up Work

- Harden `_submit_via_lp` to use an absolute `lp` path if the pinned existing test is
  allowed to be updated.
- Raise the `surya-ocr` or transitive `transformers` floor only after confirming API
  compatibility with the OCR adapter.
- Add a `pip-audit` CI gate.
- Implement F9: bundled or pinned OCR model weights with hash verification.
- Continue tracking the pre-existing no-jump geometry failures and the documented
  heartbeat timing flake separately from this security patch series.
