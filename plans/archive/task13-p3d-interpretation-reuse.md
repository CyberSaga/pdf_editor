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

Command:

```powershell
.venv\Scripts\python.exe scripts/benchmark_p3d_interpretation_reuse.py
```

Result: PASS; all shipped/control identity, engagement, replay, write-count,
and Stage-A interpretation-count gates were green.

| corpus | Stage-A capture-share median | shipped warm p50 (ms) | legacy warm p50 (ms) |
|---|---:|---:|---:|
| dense unrotated | 0.486094 | 227.930 | 770.650 |
| small unrotated | 0.066304 | 79.540 | 76.680 |
| dense rotated | 0.406783 | 602.560 | 880.200 |

Decision: **GO**. The primary dense-unrotated same-render median capture share
was 48.6094%, above the 20% threshold, and all Stage-A hard gates passed.
Continue with the conditional Stage-B red/green cycle.

### Commit 5 — Stage-B red

Command:

```powershell
.venv\Scripts\python.exe -m pytest -q test_scripts/test_text_commit_prestate_baseline.py
```

Red confirmed (2026-08-28): collection failed with
`ImportError: cannot import name 'PreStateBaseline' from model.text_commit.verify`.
Result: 1 collection error, exit code 1. No Stage-B production cache code existed.

### Commit 6 — Stage-B green

Implemented the renderer-owned, one-slot `PreStateBaselineCache` with immutable
bytes/tuple/scalar payloads; fresh stream/font/annotation/page-count/fingerprint
reads; small-glyph, quad-correction, and AA key inputs; miss release; close clear;
and revert-failure invalidation.

Commands/results:

```powershell
.venv\Scripts\python.exe -m pytest -q test_scripts/test_text_commit_prestate_baseline.py
# 18 passed in 18.16s

$files = Get-ChildItem test_scripts -Filter 'test_text_commit_*.py'
.venv\Scripts\python.exe -m pytest -q $files
# 651 passed, 3 skipped, 5 xfailed in 204.02s
```

The key-invisible negative control changed an image XObject outside the target
halo without changing the baseline key: the stale-baseline path rejected with no
token/PNG, while a fresh disabled-baseline control accepted.

### Commit 7 — final P3-D acceptance harness

Command:

```powershell
.venv\Scripts\python.exe scripts/benchmark_p3d_interpretation_reuse.py
```

Result: PASS with no hard-gate failures. The final instrumented Stage-A
dense-unrotated capture-share median was 0.457574, retaining the GO decision.

| scenario | unrotated page interpretations | rotated page interpretations | legacy control |
|---|---:|---:|---:|
| Stage A warm | 3 | 4 | 6 |
| Stage B cold | 2 | 4 | 6 |
| Stage B warm | **1** | **2** | **6** |

Every Stage-B corpus recorded 1 miss, 1 store, and 30 hits. Warm renders used
two `DisplayList.get_pixmap` calls, one `DisplayList.get_textpage`, one low-level
clipped stext run, zero pre-patch page interpretations, zero replay executions,
and two uncompressed / zero compressed scratch writes.

| corpus | warm p50 (ms, info) | warm p95 (ms, info) | cold (ms, info) | retained Python bytes | structural bound |
|---|---:|---:|---:|---:|---:|
| dense | 127.982 | 135.747 | 6207.016 | 3,240,162 | 5,046,154 |
| small | 69.355 | 84.602 | 90.953 | 2,691,262 | 3,754,122 |
| dense rotated | 347.174 | 421.280 | 14184.690 | 3,240,162 | 5,046,154 |

Stage A, Stage B, and legacy control were identical per keystroke for PNG bytes,
plan token, rejection/verifier result, clip, render scale, new rectangle, and
prepared-plan identity. Private real-PDF corpus: NOT RUN (absent).

## Dead ends and review notes

- The requested `using-git-worktrees` skill was unavailable. Native `git worktree`
  was used to satisfy the same isolation invariant without touching the invoking checkout.
- Two independent adversarial self-review passes were completed after Commit 7.
  They re-checked rotation conventions, release-before-revert ordering, cache-key
  freshness and global settings, key-invisible mutation fail-closed behavior,
  live-engine isolation, and memory/count assertions. No confirmed production
  defect remained and no fix commit was required.
- Manual GUI smoke: NOT PERFORMED. The blocking rotated path is covered by the
  automated renderer/coordinator-shaped smoke in the final gate record.
- Private real-PDF corpus: NOT RUN because no local corpus was present.

## Final verification

Final gate sweep (2026-08-29):

- `ruff check .`: PASS.
- `mypy model/ utils/`: PASS, 52 source files.
- `lint-imports`: PASS, 4 kept / 0 broken.
- pitfalls index: regenerated, 293 entries.
- codegraph: regenerated, 377 Python files / 6,471 nodes / 41,748 edges.
- device guard against the exact base: PASS.
- diff check against the exact base: PASS.
- targeted P3-D and prerequisite files: 26 + 18 + 29 + 40 + 27 passed.
- automated rotated renderer/coordinator-shaped smoke: 2 passed.
- all `test_text_commit_*`: 652 passed, 3 skipped, 5 xfailed.
- premise probe: PASS, 20/20 raster and rawdict fixtures, 440 clipped-text
  comparisons, 400 seeded random clips, 110 boundary clips, and all negative
  controls mutation-sensitive.
- final acceptance harness: PASS; Stage B GO; final dense-unrotated Stage-A
  capture-share median 0.503762; required 3/4, 2/4, 1/2, and legacy-6 count
  cells unchanged. Informational clean Stage-B warm p50: dense 261.486 ms,
  small 72.364 ms, dense-rotated 138.180 ms.
- CI-shaped single-process offscreen selection: 2,742 passed, 35 skipped,
  15 deselected, 5 xfailed in 744.02 s.
- isolated per-file sweep: 230 files, 0 timeouts, all 16 documented script-only
  rc=5 results accepted. Two files initially failed only because the isolated
  worktree lacked gitignored real-PDF fixtures; after copying the six fixtures
  unchanged from the invoking checkout, they passed 5/5 and 377 passed /
  6 skipped. The temporary copies were removed afterward. No source fix was
  made because the root cause was the worktree fixture environment.
- manual GUI smoke: NOT PERFORMED.
- private real-PDF corpus: NOT RUN (absent as a P3-D benchmark corpus).

Final SHA is reported after the documentation commit is created; a commit cannot
embed its own SHA. Remote push confirmation is likewise recorded in the completion
report rather than claimed before publication.
