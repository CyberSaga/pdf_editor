# CEO Review: Round 3 GUI Validation Audit
**Date:** 2026-03-29
**Reviewer:** Claude (post-hoc audit of own testing)
**Scope:** Audit the 4 GUI tests performed on commit `0e7c9d4`, identify problems in the testing methodology, and propose improvements.

---

## Executive Summary

Round 3 tested 4 scenarios from the text-editing UX fix plan. Three passed, one was inconclusive. However, auditing the test process reveals **5 systemic problems** that reduce confidence in the results and leave significant risk uncovered. The "3/3 testable passed" framing masks real gaps.

**Bottom line:** The fixes are likely correct (code inspection supports this), but the *testing* is not rigorous enough to ship with confidence. Below is what went wrong and how to fix it.

---

## Problem 1: Single Test File, Single Text Block

**What happened:** All 4 tests used the same file (`test_files/2.pdf`) and the same text block ("設定樓層" on page 4). This is the equivalent of testing a calculator by only trying `2 + 2`.

**Why it matters:**
- The drag clamp was only tested on a page 4→5 boundary. What about page 1→2 (top of document), page 7→8 (end of document), or single-page PDFs?
- Undo was only tested on a large heading block (32pt Sans). Would it behave the same on a small body-text span, a multi-color paragraph, or a block with ligatures?
- The normalization fix (`_normalize_for_edit_compare`) was not tested at all — no test involved ligatures or whitespace differences.

**Risk:** The fix plan explicitly called out bugs like "multi-color paragraph loses per-run colors" (Fix 2c) and "ghost text from ligature normalization" (Fix 1a). Neither of these was exercised.

---

## Problem 2: Escape Test Was Abandoned, Not Solved

**What happened:** When synthetic `key("escape")` didn't close the editor, the test was marked "inconclusive" and attributed to a "test-tooling limitation." No further attempts were made.

**Why it matters:**
- The report concludes "the code logic is correct per static analysis" — but static analysis is exactly what the GUI test was supposed to *go beyond*. Falling back to code reading defeats the purpose.
- There were unexplored alternatives: clicking the "取消" (Cancel) button in the right panel, using `cmd+z` after typing to undo all changes then clicking away, or trying `key("Escape")` with different casing/modifiers.
- Most critically: if synthetic Escape doesn't reach the editor, this is itself a bug signal. Real users might trigger Escape via keyboard shortcuts, accessibility tools, or remote desktop — the same delivery path as synthetic injection. Dismissing this as "tooling" is premature.

**Risk:** The Escape-to-discard flow is the primary safety hatch for users who accidentally modify text. It cannot be left unverified.

---

## Problem 3: No Negative Testing

**What happened:** Every test checked a happy path — "does the right thing happen?" None checked negative cases — "does the wrong thing NOT happen?"

**Missing negative tests:**
- After in-editor Cmd+Z, is the document undo stack still empty? (Verifies undo isolation)
- After drag clamp commit, does page 5 contain any new text? (Verifies no ghost write)
- After document undo, is the redo stack populated? (Verifies undo is reversible)
- After committing a position-only move (no text change), does `_normalize_for_edit_compare` correctly detect "no text edit"?

**Risk:** Positive-only testing can pass even when the fix has off-by-one errors, partial failures, or side effects that don't affect the immediate UI state.

---

## Problem 4: No State Verification Between Steps

**What happened:** Tests relied on visual screenshots to verify outcomes (e.g., "text reverted to 設定樓層"). There was no programmatic verification of internal state.

**What should have been checked:**
- Tab title asterisk: verified visually, but not whether the undo stack depth is correct
- Page assignment after drag: verified by scrolling, but not by reading the actual PDF page content (e.g., via PyMuPDF `page.get_text()`)
- Editor closure: verified by screenshot, but not by checking `self.text_editor is None`

**Risk:** Visual verification is fragile — a text block could appear in the right position on screen but actually be written to the wrong page in the PDF data model. Only a programmatic check (e.g., `fitz.open(path).load_page(3).get_text()`) can confirm the data is correct.

---

## Problem 5: Test Isolation Was Not Maintained

**What happened:** Tests were run sequentially on the same editor session. Test 2 left the document modified (typed "X", undid it). Test 3 picked up from there. Test 4 reused the same text block after Test 3's undo.

**Why it matters:**
- If Test 2's undo left residual state (e.g., an extra entry in QTextEdit's internal undo stack), Test 3 might pass even if document-level undo was broken — because the in-editor undo stack would have caught the change first.
- Sequential tests without a clean reload make it impossible to know if a test passed due to the fix or due to leftover state from a previous test.

**Risk:** Low for these specific tests (the code paths are well-separated), but methodologically this means the test suite cannot be trusted to catch regressions if the order changes.

---

## Improvement Plan

### Tier 1 — Fix Now (before shipping)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | **Test Escape via alternative method**: Try clicking "取消" button, or write a small PyMuPDF script that opens the file, simulates the edit, and checks `_discard_text_edit_once` flag. | 30 min | Closes the only open test |
| 2 | **Add a programmatic page-content check for drag clamp**: After committing the dragged text, run `fitz.open("test_files/2.pdf")` → `page(3).get_text()` to confirm text exists, and `page(4).get_text()` to confirm it doesn't. | 15 min | Eliminates visual-only verification risk |
| 3 | **Test on a second PDF**: Repeat Tests 2–4 on a different file (e.g., one with English text, ligatures, or multi-color spans) to break the single-file bias. | 30 min | Catches file-specific false passes |

### Tier 2 — Improve Process (next round)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 4 | **Add negative test cases**: For each test, define what should NOT happen and verify it explicitly. E.g., "after drag clamp commit, page 5 has no new text blocks." | 1 hr | Catches side effects |
| 5 | **Reload file between tests**: Close and reopen `2.pdf` between each test to ensure clean state. | 10 min/test | Guarantees isolation |
| 6 | **Test ligature normalization (Fix 1a)**: Create or find a PDF with fi/fl/ff ligatures. Open editor, close without changes, verify no ghost text is created. | 30 min | Validates a fix that was never GUI-tested |

### Tier 3 — Automation (future rounds)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 7 | **Write a headless Qt test harness**: Use `QTest` or `pytest-qt` to drive the editor programmatically (send real `QKeyEvent`s, not synthetic OS-level injection). This would solve the Escape key injection problem permanently. | 4 hrs | Eliminates entire class of "inconclusive" results |
| 8 | **CI regression suite**: Automate Tests 1–4 as a pre-merge check on the feature branch. | 2 hrs | Prevents regressions on future commits |
| 9 | **Multi-file test matrix**: Define a matrix of (file × text block × action) and run all combinations. Target: 3 files × 3 block types × 4 actions = 36 test cases. | 3 hrs | Comprehensive coverage |

---

## Revised Confidence Assessment

| Test | Report Verdict | Audit Verdict | Gap |
|------|---------------|---------------|-----|
| 1 (Escape) | ⚠️ INCONCLUSIVE | ❌ NOT TESTED | Needs alternative verification method |
| 2 (In-editor undo) | ✅ PASS | ✅ LIKELY PASS | Add negative check (doc undo stack empty) |
| 3 (Document undo) | ✅ PASS | ✅ LIKELY PASS | Add redo stack check, test on second file |
| 4 (Drag clamp) | ✅ PASS | ✅ LIKELY PASS | Add programmatic page-content verification |

**Ship readiness:** The code is probably correct (static analysis and partial GUI evidence support it), but the testing does not yet provide the rigor needed for an Acrobat-level quality bar. Recommend completing Tier 1 improvements before merging to `main`.

---

## Appendix: What the Fix Plan Required vs. What Was Tested

The fix plan (`2026-03-25-text-editing-ux-fix-plan.md`) defined fixes across 4 batches (P0–P3). Round 3 tested fixes from Batch 1 (drag clamp) and Batch 2 (Ctrl+Z, Escape). The following fixes from the plan were **not covered** by any GUI test:

- **Fix 1a** (ghost text from normalization): `_normalize_for_edit_compare` exists in code but was never exercised with ligature-containing text.
- **Fix 1b** (annotation coordinates wrong scale): Not tested — would require zoom + annotation interaction.
- **Fix 2a** (zoom debounce stale scale): Not tested — would require rapid zoom during editor open.
- **Fix 2c** (multi-color paragraph): Not tested — would require a PDF with multi-color text spans.
- **All P2/P3 fixes**: Not tested.

This is expected for Round 3 (which focused on P0/P1 core flows), but should be tracked for coverage in future rounds.
