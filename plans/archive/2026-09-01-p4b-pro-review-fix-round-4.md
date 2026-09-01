# P4-B Pro-review fix round 4

## Goal

Close the four direct-path findings in `plans/p4-b-deep-dahl(2).md` without
expanding scope: candidate text rise, glyph identity versus layout metrics,
renderable target bboxes, and census effective-advance parity.

## Affected modules

- `model/text_commit/plan.py`
- `scripts/measure_type0_funnel.py`
- `test_scripts/test_text_commit_duplicate_painter_gate.py`
- `test_scripts/test_text_commit_hscale_admission.py`
- `test_scripts/test_glyph_overlap_census.py`
- Required architecture, pitfalls, TODO, and project-memory documentation

## Steps

1. Implement Fix 3 with red tests, then focused green verification.
2. Implement Fix 4 with a red test, then focused green verification.
3. Implement Fix 1 with red tests, including the sheared reach-bound probe, then
   focused green verification.
4. Implement Fix 2 with red tests for metric clones, distinct fonts, and the
   self-measurable CID branch, then focused green verification.
5. Run the specified focused suites and an adversarial verification pass.
6. Run the full suite, ruff, mypy, and `git diff --check`.
7. Rerun the sealed-corpus census, reconcile aggregate deltas, and privacy-scan
   the aggregate-only report.
8. Update architecture, pitfalls/index, TODOs, and project memory.
9. Archive this plan and commit logical units on the current branch. Do not push,
   merge, open a PR, or touch `main`.

## Standing constraints

- No Form-XObject traversal.
- No TJ operand-array re-lexing to replace `_painter_reach`.
- No global retune of the 0.6-em core.
- Preserve positive-hscale/TJ-cancellation algebra and ordinary-corpus
  attribution.
- Census output remains aggregate-only.

## Decisions log

- 2026-09-01: Accepted the supplied execution order 3 → 4 → 1 → 2.
- 2026-09-01: The supplied review brief is retained as an input artifact; this
  dated plan is the mutable controlling artifact required by `CLAUDE.md`.
- 2026-09-01: No design decision has been overturned at plan review.
- 2026-09-01: Fix 3 uses one `_renderable_bbox` conversion chokepoint for
  caller/fallback and both Tier-1-derived boxes. Red reproduced both verifier
  overflow for `1.4e308` and planner overflow for `10**400`; focused green is
  23 passed.
- 2026-09-01: The first Fix 4 fixture was masked by duplicate-painter
  classification because the enormous candidate core overlapped an identical
  base show. It was corrected to use a two-glyph base and one-glyph candidate,
  isolating the effective-advance leg. Red was `all_gates_pass == 2`; focused
  green is 25 passed, including preserved nonpositive-hscale attribution.
- 2026-09-01: Fix 1 adopts the specified baseline/rise envelope and returns
  the mapped `|v| / |u|` ratio with `_painter_reach`, so the reach-path x pad
  is derived once from the same mappings. Red covered both rise signs, the
  real engine, and a sheared large-rise candidate; all 40 gate tests are green
  after Fix 2 as well.
- 2026-09-01: Fix 2 separates `_glyph_identity` from layout metrics and makes
  `_same_font_object` return only `True` or `None`. Unproven Tj candidates use
  exact extents only for raw-byte CID measurement or a widths-backed simple
  round trip; otherwise they retain the bounded reach path. The first cloned
  descendant fixture attempted key-by-key copying, but PyMuPDF decoded an
  escaped `/BaseFont` name into an unwritable name; cloning the serialized
  object whole preserves valid PDF escaping. No production design changed.
- 2026-09-01: Adversarial verification added and passed a three-case
  rise/shear grid, a simple-font `/Identity-H` encoding collision, bbox arity,
  the exact 1e308 boundary, a just-above-limit float, and `10**400`. The
  combined focused battery passed 119 tests before the added probes; the final
  duplicate-painter suite passed 40 tests before the grid expansion.
- 2026-09-01: Authoritative full suite passed 2,999, with 21 skipped and 5
  xfailed in 860.61s. `ruff check .`, mypy over 52 model/utils files, and
  `git diff --check` passed before the census/doc stage.
- 2026-09-01: The sealed census pair was resolved from the prior recorded
  50-page/23-page shape and rerun with `--json --no-e2e`. Counts were unchanged:
  `source_bindable=6811`, `all_gates_pass=6624`,
  `duplicate_painter_only=187`, `tj_array_only=112`, and `hscale_only=0`;
  doc_1 remains zero past eligibility. The expected direction was not observed
  because this corpus has none of the newly distinguished rise-cancel,
  metric-clone, unproven-font-overlap, or effective-product-overflow shapes.
  This does not overturn a design decision; the adversarial fixtures exercise
  those shapes directly. Privacy scan passed: the JSON contains only ASCII
  aggregate schema/counters and `doc_0`/`doc_1`, with no text, filenames,
  basefonts, or resource names.
- 2026-09-01: At completion the user-supplied untracked
  `plans/p4-b-deep-dahl(2).md` attachment was no longer present in the
  workspace (no agent move or deletion occurred), so only this controlling
  plan can be archived. The full brief remains represented by this plan's
  goal, constraints, steps, and decisions log; implementation was completed
  while the source brief was present and had been read in full.

## Open questions

- None currently. Any mismatch found between the brief and runtime behavior will
  be recorded here before substitution.
