# Phase R0 — Baseline Freeze & Regression-Net Repair

**Status:** Ready. **Fusion:** 2-model (mechanical) + one 3-model gate (interpreter authority).
**Why first:** the campaign's entire regression net is currently broken in three ways — the tree
is RED, the *shipped* `.venv` stack cannot collect the suite, and one gate test is flaky. No
later phase can be validated until this is repaired. (Census: test-env lens; critique HAZARD 1+2.)

> **Implicit risks:** declaring `.venv` (PyMuPDF 1.27.1) the authority may surface 1.27-only
> failures that system Python 1.25.5 masked — those must be triaged *before* the freeze or the
> "green baseline" is fiction. A membership-only icon assertion would mask a real future
> icon-map regression.

---

## R0.1 — Fix the RED tree (icon-count staleness)

- `test_scripts/test_theme_and_icons.py:339` asserts `len(ACTION_ICON_MAP) == 32`; the live
  value is **33** (the Fable-5 commit `7b6fe6c` grew the map, left the literal). Product is
  correct; the test is stale.
- **Fix:** assert **`== 33` AND a membership invariant** (e.g. every label in the ribbon spec
  maps to a non-empty PNG), not membership-only — an exact count still catches a *dropped* icon.

## R0.2 — Make the suite `.venv`-collectable (unblock the shipped stack)

- `scripts/ux_signoff_agent.py:36-39` runs `try: import pyautogui except ImportError: print(...);
  sys.exit(1)` **at import time**. `test_scripts/test_ux_signoff_agent.py:8` and
  `test_scripts/test_security_cua_allowlist.py` import the module at top level, so
  `.venv\Scripts\python.exe -m pytest test_scripts/` aborts with `INTERNALERROR` (983 collected,
  then dies).
- **Fix:** make the import side-effect-free — move the `pyautogui` import to the use-site (or a
  lazy `_require_pyautogui()` helper) so a missing dep degrades the *test* to a skip, not a
  collection abort. Preserve the dangerous-action gating the CUA allowlist test asserts.

## R0.3 — De-flake the heartbeat gate

- `test_scripts/test_print_subprocess_runner.py:190-231` uses `stall_timeout_ms=40` /
  `stall_check_interval_ms=10` with `time.sleep(0.02)` between 4 heartbeats; under full-suite CPU
  contention the watchdog fires and `stalled == []` fails (passes in isolation).
- **Fix:** widen to `stall_timeout_ms>=400`, **or** inject a fake monotonic clock so the test is
  deterministic (preferred — wall-clock independence). Compare the non-flaky siblings at lines
  141/168 (`stall_timeout_ms=1000`).

## R0.4 — Declare the regression-net authority (3-model gate)

- The app ships from `.venv` (PyMuPDF 1.27.1 / PySide6 6.10.2 / pytest 9.0.3); the only currently-
  green interpreter is system Python (1.25.5 / 6.9.2 / 8.3.3) — a **three-library** skew.
- **Decision (3-model — security/correctness reasoning):** once R0.1–R0.3 land, run the full
  suite under `.venv`. Triage any 1.27/6.10-only failures. Declare `.venv` the canonical
  regression interpreter and set the canonical command to
  `.venv\Scripts\python.exe -m pytest test_scripts/`.

## R0.5 — Coverage baseline

- No `coverage`/`pytest-cov` in either interpreter. Add `pytest-cov` to the `dev` extra in
  `pyproject.toml`, capture `--cov=model --cov=controller --cov=view --cov-report=term-missing`,
  and record the per-module % in `refactor-state.md §1` as the floor (measure first; ratchet later).

---

## Fusion Protocol Playbook

- **Mechanical steps (R0.1–R0.3, R0.5):** Two-model, Playbook **4.5** (test-gap lens) on each
  touched test file:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "These are stale/flaky gate tests. Confirm the fix preserves the original assertion intent
       and does not mask a real regression (icon-count, CUA gating, stall detection)." `
      --file test_scripts/test_theme_and_icons.py --file scripts/ux_signoff_agent.py
  ```
- **R0.4 (interpreter authority):** **Three-model** — Playbook 4.5. Run fusion.py `--no-synthesize`
  on the cross-version risk, give `/codex:rescue` the same prompt + the version table, synthesize
  per manual §3. This is a 3-model step because it is *security/correctness-invariant-adjacent*:
  the wrong authority silently validates against a stack users never run.

## Verification & Gatekeeping

```powershell
# Canonical (post-R0.2 fix) — the shipped stack must collect:
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider
# Expected: >=1355 passed, exactly 20 OCR skips, 0 failed.
# Determinism: run the heartbeat file x5, must pass every time:
.venv\Scripts\python.exe -m pytest test_scripts/test_print_subprocess_runner.py -q  # x5
# Coverage floor capture:
.venv\Scripts\python.exe -m pytest test_scripts/ --cov=model --cov=controller --cov=view --cov-report=term-missing
ruff check test_scripts/test_theme_and_icons.py scripts/ux_signoff_agent.py
```

**Gate:** the freeze is valid ONLY when (a) `.venv` collects the full suite, (b) green with the
exact skip set, (c) heartbeat deterministic over 5 runs, (d) coverage number recorded.

## Risk Triage (2→3 upgrade points)

- **R0.4 interpreter authority → 3-model** (security/correctness-adjacent trigger #2): a hidden
  1.27-only failure freezes a fiction.
- All others stay **2-model**: pure test fixes, no product behavior, no state, no security path.
- **Regression vector to watch:** R0.1 membership-only assert masks dropped icons → keep the
  exact count. R0.2 lazification must not disable the CUA-allowlist test's gating assertion.

## Docs (same commit)

- `docs/PITFALLS.md`: "import-time `sys.exit` aborts pytest collection — guard optional-dep
  imports at use-site"; "exact-count test assertions go stale on additive changes — pair count
  with membership invariant".
- `refactor-state.md`: flip R0 status, record the frozen numbers + coverage floor.
- `TODOS.md`: mark the heartbeat-flaky item (TODOS.md:8) resolved.

## Commit

One commit: `test: R0 regression-net repair — green the shipped .venv stack (icon count, ux_signoff
lazy import, heartbeat de-flake, coverage baseline)`. `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
