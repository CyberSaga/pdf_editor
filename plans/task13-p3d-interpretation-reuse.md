# Task 13 P3-D implementation record

## Contract

- Base: `a9f00c41e3ff9f500f3345cd0ba43d2d11027831`
- Branch: `task13/p3d-interpretation-reuse`
- Source contract: `plans/plan-p3-d-sol-medium-complete.md` in the invoking checkout
- PR policy: push after all applicable gates; do not open a PR
- Commit policy: preserve red/green/perf/fix/docs commits without rewrite

## Execution log

### Base verification

- `git fetch origin task11/slice1-closure` resolved the named remote branch to
  `a9f00c41e3ff9f500f3345cd0ba43d2d11027831`.
- An isolated worktree was created because the invoking checkout was on
  `task13/cid-stream-evidence-attestation` and contained the untracked source plan.
- The P3-D worktree started clean at the exact base.

### Commit 1 — premises and base census

Command:

```powershell
.venv\Scripts\python.exe scripts/benchmark_p3c_stage_census.py
```

Fresh base result (2026-08-28): PASS. Private real-PDF corpus: NOT RUN (absent).

| corpus | warm p50 control (ms) | warm p50 shipped (ms) | warm p95 control (ms) | warm p95 shipped (ms) | cold control (ms) | cold shipped (ms) |
|---|---:|---:|---:|---:|---:|---:|
| dense | 2607.601 | 613.117 | 2664.744 | 658.809 | 15268.815 | 12759.223 |
| small | 26.625 | 31.113 | 35.175 | 36.240 | 31.005 | 35.866 |

Premise probe command:

```powershell
.venv\Scripts\python.exe scripts/probe_p3d_interpretation_equivalence.py
```

Premise probe verdict (2026-08-28): PASS on PyMuPDF 1.27.1.

| fixture legs | raster equal | rawdict equal | fixed clipped-text equal | seeded random clips | 0.1pt boundary clips | derotated-raster negative mismatches | quarter-turn clip negative mismatches (90 / 270) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 20 | 20 | 440 | 400 | 110 | 4 | 4 / 3 |

The AP-less rotated annotation first-render comparison passed on two independently
opened copies. Timings are not an acceptance gate and were not claimed by this probe.

### Commit 2 — Stage-A red

Command:

```powershell
.venv\Scripts\python.exe -m pytest -q test_scripts/test_text_commit_interpretation_reuse.py
```

Red confirmed (2026-08-28): collection failed with
`ModuleNotFoundError: No module named 'model.text_commit.interpretation'`.
Result: 1 collection error, exit code 1. Production code had not been changed.

### Commit 3 — Stage-A green

Implemented the leaf `PageInterpretation`, shared rawdict value derivation,
preview-only single pre-rawdict extraction, opt-in post verification reuse, and
release-before-revert nesting. The live engine call sites remain unchanged.

Commands/results:

```powershell
.venv\Scripts\python.exe -m pytest -q test_scripts/test_text_commit_interpretation_reuse.py
# 26 passed in 16.03s

$files = Get-ChildItem test_scripts -Filter 'test_text_commit_*.py'
.venv\Scripts\python.exe -m pytest -q $files
# 634 passed, 3 skipped, 5 xfailed in 193.32s
```

### Commit 4 — Stage-A census and decision

Pending.

## Dead ends and review notes

- The requested `using-git-worktrees` skill was unavailable. Native `git worktree`
  was used to satisfy the same isolation invariant without touching the invoking checkout.
