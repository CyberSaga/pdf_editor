# Phase R1 — Mechanical Hygiene (ruff + app-identity + packaging)

**Status:** Ready (after R0). **Fusion:** 2-model throughout (mechanical/triage).
**Why here:** lowest blast radius, independent of all other phases; builds confidence in the
green-net plumbing before structural work. (Census: hygiene lens.)

> **Implicit risks:** `ruff --fix` can strip an f-string prefix or import a dynamic `getattr`/
> `__all__` re-export relies on. The `app_identity` leaf is the sharpest item — **4 of 6
> consumers fail silently** (QSettings migration, single-instance server name, AUMID). One
> production F841 is *not* auto-fix-safe (side-effecting RHS).

---

## R1.1 — 18 auto-fixable + 28 production-layer ruff items

Scope is deliberately the **production layers only** (model/controller/view/utils/main.py = 28)
plus the 18 repo-wide auto-fixes. Defer the 210 test/script violations (88% of the debt) to a
separate per-file pass to keep this diff readable.

- **Auto-fix (18):** `ruff check --fix .` clears F541 (12, mostly `scripts/completion_gate.py`)
  + F401 (6). Re-run tests after — F-class autofix can touch dynamic-use sites.
- **Production E402 (23) — single root cause:** module docstring placed *after*
  `from __future__ import annotations` forces every import to E402.
  - `model/pdf_optimizer.py:1-28` (12 sites): move the docstring **above** `__future__` (PEP
    permits `__future__` to follow a docstring) — must remain the first statement or it becomes a
    dead expression.
  - `controller/pdf_controller.py:1-66` (11 sites): hoist the `from src.printing...` imports
    above the module constants (`THUMB_BATCH_SIZE` etc. at L32-40).
- **Production F401 (1):** `model/pdf_model.py:91` unused `_MAX_PIXMAP_PX` import — `--fix`-safe.
- **Production F841 (1) — manual, NOT autofix:** `controller/pdf_controller.py:3100`
  `new_annot_xref = self.model.tools.annotation.add_annotation(...)`; the call is side-effecting
  (the annotation *is* added). Drop only the binding, keep the call.
- **Production E701 (3):** `pdf_controller.py:2171,3095,3135` one-line `if ...: return` guards →
  split onto two lines.

## R1.2 — `utils/app_identity.py` leaf (consolidate 6 hardcoded identity sites)

- Sites (none derived from a shared constant): `main.py:21` (`prog="cybersaga_pdf"`);
  `main.py:37` (`APP_USER_MODEL_ID="CyberSaga.CyberSagaPDF"`, consumed `:50`);
  `utils/preferences.py:29-30` (`_ORG`/`_APP`, consumed `:41/:50/:58`);
  `utils/single_instance.py:22` (server prefix `cybersagapdf_singleinstance_`, legacy probe
  `pdf_editor_singleinstance_` `:26`); `scripts/windows_file_association.ps1:63-69`
  (`$Launcher/$ProgId/$AppExe/$AppName/$AppRegName`).
- **Fix (pattern = `utils/theme_ids.py`):** a dependency-free leaf exporting `ORG`, `APP`,
  `ARGPARSE_PROG`, `APP_USER_MODEL_ID`, `IPC_SERVER_PREFIX`, `IPC_LEGACY_SERVER_PREFIX`. Import
  into main.py/preferences.py/single_instance.py. The `.ps1` cannot import Python → parameterize
  via `param(...)` with current defaults + a header note that defaults track `app_identity.py`.
- **CRITICAL preservation:** the IPC prefix literal `cybersagapdf_singleinstance_` **and** the
  legacy `pdf_editor_singleinstance_` probe must stay byte-identical, or in-flight forwarding to a
  running instance breaks with no error.

## R1.3 — Packaging: `MANIFEST.in` defense-in-depth

- The wheel already excludes `scripts/` via the `pyproject.toml:31-35`
  `[tool.setuptools.packages.find]` allow-list (`include=["controller*","model*","utils*",
  "view*","src*"]`). The gap is the **sdist**: `python -m build --sdist` uses MANIFEST/SCM, not
  `packages.find`, so `scripts/ux_signoff_agent.py` (drives real keyboard/mouse) could ride along.
- **Fix:** add `MANIFEST.in` with `prune scripts` / `prune test_scripts` / `prune docs` /
  `prune .codegraph`. (The PyInstaller `.spec` for the frozen `cybersaga_pdf.exe` is noted for a
  later packaging task — out of scope here.)

---

## Fusion Protocol Playbook

- **Playbook 4.2** (ruff triage, 2-model) per touched production file, before any manual edit:
  ```powershell
  .venv\Scripts\python.exe -m ruff check model/pdf_optimizer.py controller/pdf_controller.py --output-format=json |
    .venv\Scripts\python.exe scripts/fusion.py "Group these violations: (1) auto-fixable; (2) safe
        manual no-behavior-change; (3) risky. The docstring-after-__future__ E402 cluster is the
        main one — confirm moving the docstring above __future__ keeps it a docstring." --stdin
  ```
- **app_identity (R1.2):** 2-model Playbook 4.2, but explicitly prompt for the silent-failure
  call sites:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py "I am consolidating 6 hardcoded app-identity sites
      into utils/app_identity.py. List every consumer that would FAIL SILENTLY (no exception) if a
      value drifts — preferences migration, single-instance server name, AUMID — and confirm the
      IPC prefix + legacy probe stay byte-identical." `
      --file utils/preferences.py --file utils/single_instance.py --file main.py
  ```

## Verification & Gatekeeping

```powershell
.venv\Scripts\python.exe -m ruff check model/ controller/ view/ utils/ main.py   # production layers: 0
.venv\Scripts\python.exe -m pytest test_scripts/test_user_preferences.py test_scripts/test_security_single_instance_isolation.py -v
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider  # full green, no regressions
# Identity round-trip: launch twice, assert second invocation forwards into the first (no duplicate window).
```

**Red-light first:** `test_scripts/test_app_identity.py` — assert `app_identity.IPC_SERVER_PREFIX
== "cybersagapdf_singleinstance_"`, the legacy probe constant is present, and every site imports
from the leaf (AST-grep that no module re-defines the literals). Write it red (leaf absent) before
creating the module.

## Risk Triage (2→3 upgrade points)

- Everything here stays **2-model** (pure text/reorder/dead-code). The `app_identity` leaf
  creates a new module but it is *pure string constants with no behavior* — does not meet the
  "load-bearing facade other layers reason about" bar; the silent-failure consumers are mitigated
  by the byte-identical-preservation rule + the round-trip test.
- **Vectors:** dynamic-use of an autofixed import/f-string (scan `getattr`/`__all__` first);
  docstring-move becoming a no-op expression; F841 RHS deletion (keep the call).

## Docs (same commit)

- `docs/ARCHITECTURE.md`: add `utils/app_identity.py` to the leaf-tier list (alongside
  `theme_ids.py`); note the `.ps1` parameterization contract.
- `docs/PITFALLS.md`: "E402 from docstring-after-__future__"; "consolidating silent-failure
  identity strings — preserve IPC prefixes byte-identical".
- `TODOS.md`: mark "Consolidate app-identity strings" + "Exclude scripts/ from packaged artifact"
  done; update the ruff count in CLAUDE.md §3.1 (238 → post-fix production-clean count).

## Commit

One commit: `chore: R1 mechanical hygiene — ruff production-layer clean, app_identity leaf,
MANIFEST prune`. `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
