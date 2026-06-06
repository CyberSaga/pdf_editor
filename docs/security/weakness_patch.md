I'll start by reading the key documents to understand the weaknesses I need to patch.

I've read the full security patch plan and both review documents. Let me orient myself: establish the test baseline, explore the structure, and check the codex review tooling the iteration logic depends on.

`pyproject.toml` doesn't exist despite CLAUDE.md referencing it. Let me check the actual project config and the codex tooling.

No pytest config — tests run from repo root with `test_scripts/conftest.py` handling path setup. Let me check the environment and codex availability, then kick off a baseline test run.

pytest isn't in the `.venv` — but the prior investigation used a global Python 3.10. Let me locate the environment that actually runs the tests.

Global Python 3.10 has the full stack (pytest, surya, torch, win32print). That's the test environment. Let me confirm versions and start a baseline test run in the background.

1184 tests collected. Note the global env already has **Pillow 12.1.1** (so P8's floor is already satisfied at runtime — the patch is to the requirements floor only). Let me start a baseline full-suite run in the background while I work.

Baseline is running in the background. Now let me set up my tracking artifacts and understand the codex review tooling the iteration logic depends on.

Good — I can invoke codex reviews via the companion script. Let me verify codex is configured and the script path resolves.

Codex is configured and node is available. Let me set up my tracking task list and the running notes file, then begin patching.

ruff 0.15.9 is in global Python. Let me create the task list for the 8 patches in execution order, then write the initial notes file.

Now let me write the initial implementation-notes.md capturing the environment context and plan.

Now starting **P6** (main.py logging level — fastest win). Let me update the task status and look at existing main-startup tests for patterns, then write the failing test.

I understand the patterns. Let me start P6: write the failing test, confirm Red, then implement.

Red confirmed (2 fail, 1 trivially passes since current code is always DEBUG). Now implement P6.

Green (3 passed). The `os` import is unused and the E402 comes from the manual `sys.path` block — but `conftest.py` already inserts the repo root, so I can drop that boilerplate entirely and import `main` at the top.

Green and ruff clean. Let me verify the relevant existing tests still pass and check baseline progress.

Main tests pass (23 passed). The baseline shows ~7 pre-existing failures (FFFF/FFF) around the 54-60% mark — I'll capture the exact list when it finishes. P6 is isolated and its tests pass, so let me record the decision and make the atomic commit (staging only P6 files + notes, not the scan-artifact JSONs or input docs).

P6 committed. The baseline run finished — let me read its results to establish the pre-existing failure set before going further.

Baseline established: **7 pre-existing failures, all in `test_no_jump_editor_geometry.py`** (editor click-to-edit geometry — unrelated to any security patch), plus 1156 passed, 21 skipped. Let me record this baseline so I can distinguish regressions later.

Baseline recorded. Now, per the iteration logic, I'll run a codex review on the committed P6 change to get a verdict before proceeding. Let me invoke the codex companion directly, scoped to this commit.

Remote Control connecting…

Codex verdict on P6: **clean** ("did not identify any discrete, actionable regressions"). (Note: codex's sandbox declined several PowerShell git commands but still produced a verdict — I'll watch that on larger diffs.) Proceeding to **P3**.

Now let me read the win_driver rundll32 site and the existing linux_driver test to match patterns.

I see a critical constraint: the existing test `test_submit_via_lp_omits_hardware_options_when_not_overridden` asserts `captured_cmd[:5] == ["lp", ...]` — pinning the **bare** name. Changing `_submit_via_lp` to the absolute path would break that test, which I'm forbidden to edit. Let me check whether any existing tests also pin the win_driver `rundll32` and the lpstat sites before deciding the exact scope.

The win_driver `rundll32` branch and the lpstat sites aren't pinned by any existing test — only `_submit_via_lp` is (it asserts `cmd[:5] == ["lp", ...]`). Let me read the win_driver method structure to place the absolute-path fix correctly.

Let me find the `open_printer_properties` method start and the module-level constants location.

I have the full picture. The win `rundll32` branch is only hit when `win32print is None` (line 788), and no test pins it. Let me confirm the `supports_printer_properties_dialog` property and `get_printer_preferences` shapes so my test drives the fallback correctly.

No existing test pins the win `rundll32` or lpstat sites — only `_submit_via_lp` pins the bare `"lp"`. That's a real conflict with the spec that I'll handle deliberately. Let me write the failing tests for the safe sites first.

All 3 Red. Now implement the fixes — win_driver first.

Now the linux_driver lpstat sites:

Now verify: new P3 tests green, and the existing print-driver tests (especially the `_submit_via_lp` one I deliberately left untouched) still pass.

All 48 pass (including the untouched `_submit_via_lp` test), ruff clean. Let me record the deliberate `_submit_via_lp` deviation and commit P3.

P3 committed. Running codex review on it.

Codex verdict on P3: **clean**. Marking P3 done, starting **P2** (IPC socket isolation). Let me read the file and its existing test.

Let me read the existing single-instance test to ensure my path-validation change won't break it (it may forward synthetic paths).

Key insight: the existing forwarding tests use `send_to_running_instance`'s **in-process shortcut** (the server is in `_ACTIVE_SERVERS`, so `on_message` is called directly, bypassing the socket). So validation added to `_handle_socket_message` — the real cross-process trust boundary — won't touch them. Let me verify the PySide6 enum API before writing the test.

Confirmed the API. Now writing the failing P2 tests (socket option + `_handle_socket_message` path validation via a fake socket).

Red confirmed (3 fail, accept-case trivially passes). Now implement P2.

Now the path-validation in `_handle_socket_message`:

8 passed (4 new + 4 existing forwarding), ruff clean. Let me record P2 and commit.

Codex verdict on P2: **clean**. Marking done, starting **P4** (watermark coercion). Let me read the relevant part of watermark_tool.py and find existing watermark tests.

Let me see the full watermark dict schema (from `add_watermark`) so coercion doesn't silently drop fields the renderer needs, and find any existing watermark round-trip tests.

Let me check which keys the rendering code reads, so coercion preserves everything the renderer needs.

The renderer reads `text/angle/opacity/font_size/color/font/offset_x/offset_y/line_spacing/pages` — note it does **not** read `font_color_name` (which the spec's snippet invented; it's not in the real schema). I'll adapt coercion to the actual `add_watermark` schema. Let me check for existing watermark round-trip tests before changing the loader.

Let me read the watermark round-trip assertions in test_feature_conflict.py to ensure coercion preserves what they check.

The C6 round-trip test only checks `len(wl) >= 1` + render success, so coercion is safe as long as it preserves valid watermarks. I'll adapt `_coerce_wm` to the **real** schema (drop the spec's nonexistent `font_color_name`, default `font` to `"helv"`, preserve `offset_x/offset_y/line_spacing/color`). Writing the failing tests:

Red (import error — `_coerce_wm` doesn't exist yet). Now implement P4.

P4 green (9 new), the watermark round-trip suite passes (69 passed), ruff clean. Recording the schema adaptation and committing.

Codex's sandbox failed to start on the P4 review (inconclusive "no findings"). The PowerShell sandbox is flaky on this machine — my test suite + ruff + baseline-diff remain the real gate. I'll note this and keep running codex per commit, but get a thorough review on the big P1 patch. Proceeding to **P5**.

Now let me check the `PrintJobOptions`/`PrintJobResult` constructors so my test builds them correctly.

`PrintJobOptions()` has all defaults. Writing the P5 test (Red: currently the failure is silently swallowed, no log emitted).

Red confirmed. Implementing P5.

P5 green, ruff clean. (test_printing_pipeline.py is a `__main__` script with no pytest tests — my P3 run already covered 48 print tests.) Recording and committing P5.

Codex verdict on P5: **clean**. Marking done, starting **P7** (CUA allowlist). Let me read `_execute_cua_action` and the existing agent test.

No existing test invokes `_execute_cua_action` directly (they mock `_run_agent_on_pdf`), so blocking `type`/`key` is safe. Writing the failing P7 tests:

Red confirmed (3 block-tests fail, 2 allow-tests pass). Implementing P7.

Tests pass (7). Let me see the exact ruff errors — they may be pre-existing in the agent file, not from my change.

Both ruff errors (lines 35, 481) are **pre-existing** tracked violations far from my edit (~198–211); my added lines are clean. Per DoD ("zero *new* violations") I leave those out-of-scope. Recording P7 and committing.

Codex verdict on P7: **clean**. Now the big one — **P1** (PDF resource guards), the most invasive patch. Let me carefully map the open path, render/raster sites, and check whether any existing tests open >5000 pages or huge files.

Let me read `get_page_pixmap`, the export raster site, and the straighten sites to choose the cleanest clamp points.

`get_page_pixmap` delegates to `self.tools.render_page_pixmap`. The export site calls `get_page_pixmap`, straighten calls `page.get_pixmap` directly. Per the spec I'll wrap at the named sites (export 1143, straighten 4777/4830, OCR) rather than centrally, to avoid perturbing the ~30 render tests. Let me read the straighten region.

Now let me see the top of pdf_model.py (imports, logger) to place the constants/helpers, and confirm `Path` is imported.

Let me confirm the constants won't break large-PDF tests, and find the module-level insertion point (logger + first class).

`test_open_large_pdf` uses 1000 pages (< 5000). Let me make sure no test creates >5000 pages or a >512MB file.

No test creates >5000 pages; the largest page is A0 (2384×3370) which at scale 2.0 = ~32M px, under the 40M cap (so straighten is unchanged for it). Let me confirm the large-PDF generators' page counts.

All clear — `test_large_scale` defaults to 100 pages. Now let me check how `scale` is used after the straighten raster (line 4830) so reassigning it is safe.

`scale` is only used at the raster line; the output page keeps `rect` dimensions. Safe to reassign. Now I'll implement all of P1. First the constants and helpers:

I'll insert the constants/helpers after the optimizer re-exports (line 83).

Now the two guards in `open_pdf`:

Now the three raster-site wraps (export, deskew gray-array, straighten):

Now the OCR render loop. Let me read ocr_tool.py around the render site.

The OCR loop renders at a fixed `render_scale=2.0` per page. I'll clamp per-page via `_safe_render_scale`, using a local import to avoid any circular-import risk with `pdf_model`.

Now let me write the P1 tests (helper unit tests + open_pdf integration via monkeypatched constants):

I implemented P1 before writing its test — to honor Red-Light-first faithfully, let me retroactively confirm Red by stashing just the implementation (the new test file is untracked, so it stays), running the test, then restoring.

Red confirmed (helpers don't exist when implementation is stashed). Now restore the implementation:

Green (8 passed), implementation restored. Now let me run the suites that exercise the P1-touched paths (open, render, deskew/straighten, OCR, export) to check for regressions.

60 passed, 4 skipped, ruff clean. P1 paths are solid. Recording P1 (including the TDD-order note and key design decisions), then committing.

Now a thorough **adversarial** codex review on this largest patch, with focus:

Codex adversarial review of P1: **approve / "Ship"**, no material findings. Marking P1 done, starting the final patch **P8** (Pillow floor). Let me check TODOS.md.

TODOS.md is the historical log. For P8 I'll add a lightweight new test locking the Pillow floor (a real regression guard), bump the requirement, and add the open dependency items to TODOS.md. Writing the failing test first:

Red confirmed (9.0 < 12.1.1). Now implement P8: bump the floor and add the pip-audit comment.

Green. Now add the open dependency items to TODOS.md per the spec (surya/transformers floor + pip-audit CI), then record P8 in notes.

All 8 patches committed. P8's codex review was sandbox-blocked (trivial change, low risk). Now the critical final verification: full suite vs the recorded baseline (must be ≤7 pre-existing failures, no new ones).

15 failures now vs 7 baseline — **8 new failures** introduced. I need to identify them. Let me extract the failure list and compare to baseline.

The 8 new failures are all `test_ocr_tool_surya.py::test_ocr_pages_*` — my P1 OCR clamp broke them (the test's mock model likely doesn't provide a real `doc[page_num-1].rect`). I must fix the implementation without editing the test. Let me read the test's mock setup.

Found it: the test's `_FakeDoc` implements only `__len__`/`__bool__`, not `__getitem__`, so my `self._model.doc[page_num - 1]` raises `TypeError`. A real fitz document is always subscriptable, so the fix is to degrade gracefully when geometry isn't introspectable — preserving the clamp for real (attacker) docs while not breaking the mocks.

Fixed — 28 passed, ruff clean. This was a regression my P1 OCR clamp introduced; I'll record it and commit as an atomic follow-up, then re-run the full suite to confirm we're back to the 7-failure baseline.

Down to 8 failures: the 7 pre-existing `test_no_jump_editor_geometry` ones, plus `test_print_subprocess_runner::test_runner_heartbeat_events_prevent_false_stall`. That last one is documented in TODOS.md (line 107) as a known timing-flaky test that fails under long runs but passes alone, and none of my changes touch subprocess_runner. Let me confirm it passes in isolation.

Confirmed: the heartbeat test passes alone — it's the documented timing flake (TODOS.md:107), not a regression; none of my patches touch `subprocess_runner.py`. So the suite is back to the **exact baseline** (the same 7 pre-existing `test_no_jump_editor_geometry` failures) plus my 34 new security tests all passing. Let me do a final comprehensive ruff check on everything I touched and record the verification.

All touched source + new tests are ruff-clean. (The only ruff hits anywhere are the 2 pre-existing ones in `ux_signoff_agent.py` at lines 35/481, which predate my edit.) Let me record the final verification, clean up scratch logs, and run a final codex review on the regression-fix commit.

All 10 commits are in place. Let me run one final holistic codex review of the entire security series (against the pre-security HEAD `19e4ccc`) to close the loop.

The final holistic review hit the same sandbox-startup failure (inconclusive) — but the per-commit reviews already covered each change (P1 got an adversarial "approve/Ship"), and the test suite + ruff are the authoritative gate. Let me confirm the working tree state.

All work is committed; the tree is clean (the untracked files are your input docs and scan reports, which I intentionally left out of the patch commits). 

## Summary

I patched all evidence-backed findings from `patch-weaknesses-found-in-immutable-knuth.md` (F1–F9), in the spec's priority order, each as an atomic commit with a new test, codex review, and a running log in `implementation-notes.md`.

**10 commits on `claude/simplify`:**

| Patch | Finding | Change |
|---|---|---|
| P6 | F7 | `main.py` logging defaults to WARNING; DEBUG only via `PDF_EDITOR_DEBUG` |
| P3 | F4 | Absolute `System32\rundll32.exe`; Linux `lpstat` via absolute `shutil.which` path |
| P2 | F6 | `QLocalServer` `UserAccessOption` + forwarded-path validation in `_handle_socket_message` |
| P4 | F8 | `_coerce_wm` clamps/validates embedded watermark JSON on load |
| P5 | F5 | Print temp-unlink failures logged at debug instead of silently swallowed |
| P7 | F3 | `_execute_cua_action` allowlist blocks `type`/`key` actions |
| P1 | F1 | Size (512 MB) / page-count (5000) / pixmap (40 MP) guards at open + all raster sites |
| P1‑fix | F1 | OCR clamp tolerates non-introspectable (mock) docs |
| P8 | F2 | `Pillow>=12.1.1` floor + regression test; surya/transformers, pip‑audit CI, F9 weight-pinning logged as open TODOs |

**Verification:** full suite = **8 failed, 1189 passed, 21 skipped** → the 8 are the 7 pre‑existing `test_no_jump_editor_geometry` failures (in baseline, untouched) plus the documented timing-flake `test_runner_heartbeat...` which **passes in isolation**. **Zero new persistent failures.** All 34 new security tests pass; `ruff check` clean on every touched file.

**Three things you should know (full detail in `implementation-notes.md`):**

1. **`_submit_via_lp` left on bare `"lp"` (deviation from spec).** The existing test `test_linux_driver_overrides.py` pins `cmd[:5] == ["lp", ...]`. Hardening it to the absolute path would break that test, and your boundary forbids editing current tests + requires all current tests pass. I fully fixed the higher-value `rundll32` and `lpstat` sites; the residual Linux `lp` risk is Low (per your own review: `/usr/bin` isn't user-writable, CWD isn't on `$PATH`). **Say the word and I'll harden it + update that test.**

2. **`_coerce_wm` adapted to the real schema.** The spec snippet referenced a `font_color_name` field that doesn't exist in the codebase; I dropped it and matched `add_watermark`'s actual fields so watermark round-trips stay faithful (verified).

3. **Codex reviews were flaky.** Codex's PowerShell sandbox intermittently failed to inspect diffs on this Windows box — P6/P3/P2/P5/P7 returned clean, P1's adversarial review returned **approve/"Ship"**, but P4/P8/the final holistic review were inconclusive (sandbox couldn't start). No codex finding required a change; the test suite + ruff were the real gate.

One open item per the plan: F9 (pinning/bundling OCR model weights) needs offline-bundle infra, so it's logged in `TODOS.md` rather than patched — consistent with the plan's guidance not to bump the `surya-ocr` floor until the `transformers>=5.0.0rc3` chain is verified.