# Reopen-Same-Box N-Cycle Drift Gate (TDD) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a strict regression gate for the real user workflow `open same textbox -> edit -> close/commit -> reopen` repeated N times, and fail on cumulative shrink/drift.

**Architecture:** Extend the existing full-stack `QTest` no-jump suite with a new across-session reopen-loop test that commits real edits each cycle and reopens the same span. Persist artifacts + manifest IDs through the same verifier pipeline (`verify_no_jump.py`, `ux_signoff_agent.py`) so this scenario is mandatory in gate completion, not advisory.

**Tech Stack:** Python 3.9+, PySide6, PyMuPDF (`fitz`), pytest, existing no-jump gate scripts.

---

## Problem Contract

Observed bug class:
1. Open a textbox.
2. Edit and commit.
3. Reopen the same textbox.
4. Repeat N times.
5. Editor box cumulatively shrinks (width/height/font scale drift).

Current gap:
1. Existing tests cover first-open no-jump and in-session mutations.
2. They do not strictly gate repeated reopen-across-commit loops on the same span.
3. `/goal` can pass while this manual workflow still fails.

---

## Acceptance Criteria (Strict)

All ACs below are hard-fail criteria.

### AC 1: Across-session reopen loop is mandatory

For targeted fixture `test_files/test-colored-background.pdf`:
1. Run `N=5` commit cycles plus one terminal reopen-only measurement.
2. Each cycle must execute full path:
   - open editor by real viewport click (`QTest.mousePress/mouseRelease`)
   - mutate text
   - finalize via real finalize path (`_finalize_text_edit(...APPLY)`)
   - reopen on same logical probe span
3. Any cycle that fails to open or commit is immediate FAIL.

### AC 2: No cumulative shrink

Let `R0` be first-open editor rect, `Ri` each later reopen rect:
1. For every `i`, `|dx|,|dy|,|dw|,|dh| <= 1px` relative to `R0`.
2. Cumulative shrink:
   - `R0.width - min(widths) <= 1px`
   - `R0.height - min(heights) <= 1px`
3. Resolved hit font size drift:
   - `size0 - min(sizes) <= 0.5pt`

### AC 3: Artifact + manifest evidence

For each PDF slug:
1. Persist `before.png` (first open), `after.png` (final reopen), `diff.png`, `metrics.json`.
2. Register test ID in `manifest.json`.
3. Embed gate run-id in metrics.

Required ID:
1. `e2e_qtest_reopen_cycles5_colored`

### AC 4: Verifier cannot bypass reopen cases

`verify_no_jump.py` must fail if any reopen ID is missing from manifest or artifacts.
`ux_signoff_agent.py` and verifier hash checks must include reopen IDs in image-artifact key sets.

---

## TDD Execution (RED -> GREEN -> REFACTOR)

### Task 1: RED - Add failing reopen-loop GUI test

**Files:**
1. Modify: `test_scripts/test_no_jump_editor_geometry.py`

**Steps:**
1. Add `test_reopen_same_textbox_cycles_do_not_cumulate_shrink`.
2. Parametrize over `REOPEN_QTEST_CASES` (colored-background fixture).
3. Add thresholds and deterministic same-length mutation helper.
4. Save reopen artifacts with IDs listed in AC 3.

**Run (RED expected):**
```powershell
python -m pytest test_scripts/test_no_jump_editor_geometry.py::test_reopen_same_textbox_cycles_do_not_cumulate_shrink -q
```

Expected before fix:
1. FAIL on one or more PDFs with cumulative shrink/drift assertion.

### Task 2: RED hardening - Make gate require new case IDs

**Files:**
1. Modify: `scripts/verify_no_jump.py`
2. Modify: `scripts/ux_signoff_agent.py`

**Steps:**
1. Add reopen IDs to `_REQUIRED_FIXED_IDS`.
2. Add invariant assertions that reopen IDs must exist.
3. Add reopen IDs to verifier image-case set and signoff image-case set.

**Run (still RED expected until behavior fix):**
```powershell
python -m pytest test_scripts/test_no_jump_editor_geometry.py::test_reopen_same_textbox_cycles_do_not_cumulate_shrink -q
```

### Task 3: GREEN (separate fix patch)

Apply minimal production fix for cross-session shrink root cause (likely re-resolve + reinsert geometry reuse path). Re-run the reopen test until green.

### Task 4: Regression sweep

Run:
```powershell
python -m pytest test_scripts/test_no_jump_editor_geometry.py -q
python -m pytest test_scripts/test_text_editing_fidelity_suite.py -q
```

### Task 5: Gate verification

Run:
```powershell
python scripts/verify_no_jump.py
```

Expected:
1. PASS only if reopen IDs are present and validated.
2. FAIL if any reopen evidence is missing/stale.

---

## Adversarial Controls

1. Reopen IDs are hardcoded in verifier fixed set (cannot be removed by test-only edits).
2. Manifest exact-set checks detect missing/extra/duplicate cases.
3. Artifact hash verification includes reopen case PNGs.
4. Run-ID stamping prevents stale artifact reuse.

---

## Definition of Done

1. Reopen-loop test exists and is strict enough to fail on cumulative shrink.
2. Verifier/signoff scripts require reopen evidence IDs.
3. `verify_no_jump.py` fails closed when reopen artifacts are absent or stale.
4. After production fix, full no-jump gate passes with reopen-loop coverage included.
