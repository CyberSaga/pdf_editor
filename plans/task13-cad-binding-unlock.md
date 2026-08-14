# Task 13 — CAD Binding Unlock (marked-content → rotated-Tm → replay budget)

**Status:** PLANNING (created 2026-08-14, at Task 12 sealing)
**Base lineage:** `task11/slice1-closure` (after the Task 12 closure-cleanup PR merges)
**Defaults untouched throughout:** `engine=legacy`, `max_tier=0`. Nothing in this
task reaches a user until the zero-tolerance rollout gates (TODOS "After Task 11"
block) pass.
**Data policy:** identical to Task 12 plan §10, carried forward verbatim — the
motivating corpus is a private, identifying engineering document; raw evidence
(renders, edited PDFs, absolute paths, filenames, doc identifiers) stays out of
the repo permanently; synthetic fixtures only; reason-code-level telemetry only.

## 1. Goal

Task 12 P0-D finished the CID/Type0 codec with honest coverage: **0
source-bindable shows** on the reference corpus — not because the codec is
wrong, but because three OUTER gates wall off every candidate. This task
attacks them in measured dominance order (Task 12 final funnel, §8 of the
archived plan):

| Priority | Gate | Corpus evidence (show-weighted, doc_0) |
|----------|------|----------------------------------------|
| 1 | Marked-content wrapper (`mc_depth != 0`) | 10,701 / 10,701 budget-eligible single-hex-`Tj` shows sit inside a BDC/EMC wrapper — the **common dominant gate**, 100% |
| 2 | Rotated text matrix (`trm_uniform_scaled` false) | 10,211 of those additionally use a rotated `Tm` compensating `/Rotate 270` in content space (~95%) |
| 3 | P0-A replay budget (4 MiB summed, decoded) | 16,549 operand-stage candidates refused before state gating even runs |

Strict sequencing: three separate slices, three separate PRs. **Do not bundle
the three blockers into one large PR.** Priority 2 is measurable only after
Priority 1 lands (its candidates are currently shadowed by the mc gate);
Priority 3 is an infrastructure change with its own safety contract and no
dependency on 1–2.

Not in this task (explicitly out, keep fail-closed): array-destination
`bfrange` ToUnicode (registered P1, its own tiny slice), subset augmentation /
font re-embedding, whole-`TJ` simple-font, paragraph layout/reflow. None of
them unlocks the current 0-bindable main path, so none may jump this queue.

## 2. Priority 1 — marked-content tolerance (the common dominant gate)

**Never** relax `mc_depth != 0` into a blanket allowance. BDC/EMC wrappers are
not one thing; the slice must taxonomize first and admit only the provably
inert form:

- pure layer wrapper (`/OC` on an AutoCAD layer, `BDC ... EMC` with no
  content-bearing properties) — the candidate class;
- `/ActualText` — OUT (splicing glyphs under an ActualText changes extraction
  semantics; the wrapper's text no longer matches the shown text);
- `/Alt` — OUT (same class of semantic override);
- OCG/OCMD visibility — admit only when the wrapping OCG resolves to VISIBLE
  in the default configuration and the edit cannot change membership;
- `/Artifact` — OUT for v1 (artifact content is by definition not logical
  text; editing it as text is a semantic lie);
- nested wrappers — admit only when EVERY enclosing wrapper individually
  qualifies;
- malformed BDC/EMC pairing (unbalanced, crossing q/Q) — OUT, stable reject
  code, red-pinned.

**Safe-slice proof obligations** (each one red-first, synthetic fixtures):

1. the wrapper does not change glyph encoding (decode/encode round-trip
   identical inside vs outside the wrapper);
2. the wrapper does not change extraction semantics (save→reopen extraction
   equality, the existing e2e probe extended with wrapped fixtures);
3. the wrapper does not change visibility (render-hash equality for the
   untouched region, wrapped vs unwrapped);
4. the splice NEVER crosses a BDC/EMC boundary (the replacement byte-range
   must lie strictly inside the innermost wrapper's span; boundary-crossing
   candidates get their own reject code);
5. staleness: wrapper property mutation (e.g. the OCG object, the `/OC`
   property list) between prepare and commit → STALE_PLAN (fingerprint must
   close over the wrapper evidence — apply the Task 12 lesson: fold by
   RESOLVED shape, pin every accepted form including hybrids).

Funnel first: extend `scripts/measure_type0_funnel.py` (or a sibling) with a
wrapper-taxonomy breakdown so the slice's admissible share is measured BEFORE
implementation (census-before-code, the P0-D discipline).

## 3. Priority 2 — uniform rotated `Tm`

After the marked-content gate opens, ~95% of surviving candidates still carry
a rotated `Tm`. Admit only the provable uniform case:

- rotation/scale only: `a*d - b*c != 0` (non-singular), `a*c + b*d == 0`
  within tolerance AND `a^2+b^2 == c^2+d^2` within tolerance (no shear, equal
  axis scaling — the `trm_uniform_scaled` predicate already computes this);
- the advance axis is derivable from the matrix (glyph advances march along
  the rotated baseline exactly);
- compensating kern for Tier 1 is computed along the TEXT'S OWN axis, not the
  page axis (the kern term lives in text space — prove with a rotated
  composite fixture that the successor's origin is preserved in BOTH page
  axes);
- the `/Rotate 270` page-level visual-space contract (P0-D's acceptance
  matrix already pins both tiers on rotated PAGES) passes for rotated-`Tm`
  fixtures too: verify regions computed in visual space, growth gates
  correct under rotation;
- **no generalization to arbitrary affine text**: shear, mirror, and
  non-uniform scale stay fail-closed with their own stable reason codes.

## 4. Priority 3 — replay budget / indexing

16,549 operand-stage candidates die at the 4 MiB summed decoded budget. The
cap is NOT the defect: P0-A measured it as the OOM guard (~10 GB class) and
the preview-latency guard (~1.05 s per decoded MiB per keystroke). **Do not
raise it, do not disable it; production paths never pass
`max_decoded_bytes=None`.** The unlock is architectural:

- page content-stream index: one bounded indexing pass per page generation
  (op offsets, show-op table, font-state checkpoints), so target lookup stops
  being O(page bytes) per keystroke;
- target-scoped scanning: given a resolve-result rect/span, replay only the
  spans/streams that can contain it (checkpointed state restore instead of
  full-stream replay);
- reusable replay cache keyed by stream digest + generation, with PRECISE
  invalidation on mutation (the existing `mark_page_content_dirty`
  chokepoint + registry generation bump are the invalidation hooks);
- the budget then converts from a hard refusal into a latency SLO: pages
  whose INDEXING would exceed the safety envelope still refuse with the
  existing stable reason (the P0-A reason-propagation invariant stays
  frozen).

Acceptance here is a measured latency budget (dense-page preview p95), not a
coverage number — it feeds the TODOS "latency half stays open" item.

## 5. Affected modules (expected)

- `model/text_commit/replay.py`, `inspect.py` (mc taxonomy evidence, wrapper
  fingerprint closure, index/caching)
- `model/text_commit/plan.py` (admission gates, new stable reject codes)
- `model/text_commit/verify.py` (visual-space verification under rotated Tm,
  wrapper render/extraction probes)
- `model/text_commit/patch.py` (rotated-axis kern; splice boundary guard)
- `scripts/measure_type0_funnel.py` (taxonomy breakdowns per slice)
- `test_scripts/` (synthetic wrapped/rotated fixture builders — extend
  `type0_fixture_builder.py`)

## 6. Step list

1. [ ] Wrapper-taxonomy census on the corpus (aggregate-only, read-only) —
       measure the admissible pure-layer share BEFORE any code.
2. [ ] Priority 1 red matrix (taxonomy admissions + the 5 proof obligations +
       staleness pins), then implementation; separate PR.
3. [ ] Re-run funnel; record the new marked-content survival honestly.
4. [ ] Priority 2 red matrix (uniform-rotation predicate boundaries, rotated
       kern axis, visual-space verify), then implementation; separate PR.
5. [ ] Re-run funnel; record rotated-Tm survival.
6. [ ] Priority 3 spike: index design + latency measurement harness (ties
       into the preview-latency follow-up from Task 12 §8); own PR(s).
7. [ ] Docs per protocol; keep this plan updated with decisions/dead ends.

## 7. Open questions

- OCG default-visibility resolution: which configuration dictionary governs
  (D vs alternate configs), and is visibility stable across viewers?
- Nested wrapper depth cap: is there a corpus-measured maximum, or does v1
  need an explicit depth budget with its own reject code?
- Rotated growth-zone gates: how do the occupancy/background probes transform
  under 90°-family rotations vs arbitrary angles — same code path or a
  restricted 90°-family v1?
- Index persistence: per-session only, or survives save/reopen via digest
  keys? (Privacy: digests only, never text.)
