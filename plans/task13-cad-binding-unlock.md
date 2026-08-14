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

1. [x] Wrapper-taxonomy census on the corpus (aggregate-only, read-only) —
       measure the admissible pure-layer share BEFORE any code.
       (2026-08-14: **64.2% admissible pure-layer** — §7 decisions record
       and census results; evidence capture in replay, classifier in
       `scripts/wrapper_taxonomy.py`, funnel `mc_census` block; 31-test
       red-first matrix + Codex review round, 2 findings fixed red-first.)
2. [ ] Priority 1 red matrix (taxonomy admissions + the 5 proof obligations +
       staleness pins), then implementation; separate PR.
3. [ ] Re-run funnel; record the new marked-content survival honestly.
4. [ ] Priority 2 red matrix (uniform-rotation predicate boundaries, rotated
       kern axis, visual-space verify), then implementation; separate PR.
5. [ ] Re-run funnel; record rotated-Tm survival.
6. [ ] Priority 3 spike: index design + latency measurement harness (ties
       into the preview-latency follow-up from Task 12 §8); own PR(s).
7. [ ] Docs per protocol; keep this plan updated with decisions/dead ends.

## 7. Decisions record

- 2026-08-14 (step 1 — wrapper-taxonomy census tooling; red-first, 27-test
  matrix in `test_scripts/test_wrapper_taxonomy_census.py`):
  - **Evidence capture lives in `model/text_commit/replay.py`** as pure
    read-only enrichment: `McWrapper` (operator, tag, props kind/name,
    top-level inline-dict KEYS only — values never retained), per-wrapper
    `closed`/`crossed_q`/`open_gs_depth`, `PageReplay.mc_emc_underflows`,
    and `ShowOp.mc_stack` (open wrapper ids, outermost-first).  The
    existing `mc_depth` clamp semantics are untouched and BDC/BMC operand
    oddities NEVER set `malformed` (they never did — evidence stays
    evidence: `props_kind="unparsed"`).  Rationale: the funnel must
    measure THROUGH production evidence (P0-D discipline), and the step-2
    fingerprint closure needs exactly this evidence anyway.
  - **Taxonomy classification lives OUTSIDE model** in
    `scripts/wrapper_taxonomy.py` (census-before-code): stable class slugs
    per plan §2 (`oc_layer_visible_default` — the only admissible class —
    `oc_layer_hidden_default`, `oc_ocmd`, `actual_text`, `alt_text`,
    `artifact`, `struct_content` (/MCID), `bmc_bare`, `bdc_other`,
    `props_unresolved`, `props_unparsed`, `malformed_pairing`).  Show
    verdict folds the stack outermost-first; EMC underflow poisons the
    whole page's verdicts (fail-closed).  Step 2 promotes accepted classes
    into `plan.py` behind its own red matrix.
  - **Crossing detection**: a wrapper is `crossed_q` when a `Q` pops below
    its opening gs-depth while it is open, OR its `EMC` closes at a
    different gs-depth than it opened.  Both directions red-pinned.
  - **Default-config visibility** resolves via `Document.get_ocgs()`
    (`on` flag = default config); an OCG absent from `/OCProperties` has
    no provable visibility → `props_unresolved` (fail-closed).  The §8
    open question (D vs alternate configs) stays open for step 2.
  - **Char weighting** for census verdicts uses
    `len(decoded_bytes) // 2` (2-byte CIDs — the locked v1 scope), not a
    decode pass: decode-free, and identical for the dominant population.
  - Funnel output gains one `mc_census` block (wrapper_classes counted
    once per wrapper enclosing ≥1 gated show, show/char verdicts,
    stack-depth histogram, and the unlock predictor overlap
    `admissible_uniform_trm_default_state`).  All existing funnel stages
    and loss slugs unchanged (numbers stay comparable with Task 12 §8).
  - Data-policy pin added as a TEST: the serialized funnel report must
    not contain ActualText values, OCG layer labels, properties resource
    names, or shown text (synthetic sentinels asserted absent).
  - Fixture note: `xref_set_key` cannot create keys through indirect
    paths — known pitfall (PITFALLS "path to 'X' has indirects" entry);
    `install_oc_layer`/`install_ocmd` hop to the innermost indirect dict
    first.

### Census results (corpus aggregates, 2026-08-14)

Read-only run of the extended funnel (`--no-e2e`) over the private
corpus; every base funnel stage byte-identical to the Task 12 §8 sealed
record (numbers stay comparable).  The census population is the 10,701
budget-eligible single-hex-`Tj` shows lost at the marked-content gate
(doc_0; doc_1 contributes zero — all 543 Type0 shows are `TJ`-array, as
sealed).  Re-run after the review-round strictness fixes:
**byte-identical** — the corpus contains no garbage-preceded BDC operand
lists and no keyword-valued inline dicts, so the fail-closed tightening
cost nothing.

| aggregate | doc_0 |
|---|---|
| wrapper classes (wrappers enclosing ≥1 gated show) | 946 `oc_layer_visible_default`, 106 `malformed_pairing` — nothing else |
| show verdicts | **6,872 / 10,701 (64.2%) `admissible_pure_layer`**; 3,829 (35.8%) `mc:malformed_pairing` |
| char verdicts (2-byte-CID weighting) | 41,471 admissible / 27,588 malformed |
| stack depth | 100% depth 1 — the corpus has NO nested wrappers |
| unlock predictor (`admissible_uniform_trm_default_state`) | **376** shows |

Readings:

1. The taxonomy is maximally clean: every wrapper on the gated population
   is either a pure default-visible `/OC` layer or structurally malformed
   under our v1 pairing definition.  Zero ActualText / Alt / Artifact /
   OCMD / hidden-layer / struct-content / BMC / unresolved wrappers —
   plan §2's "AutoCAD layer wrapper" hypothesis confirmed.
2. **Priority 1's admissible share is 64.2%** (show-weighted).  The
   35.8% `malformed_pairing` share is a v1 POLICY bucket (unbalanced or
   q/Q-crossing by the plan §2 definition, or page-level EMC underflow) —
   whether any of it is a tolerable legal shape (PDF permits BDC/EMC to
   straddle q/Q) is a step-2+ question, registered under Open questions;
   v1 stays fail-closed.
3. The nested-depth open question is ANSWERED for this corpus: max depth
   1 — v1 needs no depth budget, but keeps the every-wrapper-qualifies
   rule for safety.
4. Only **376** of the 6,872 admissible shows also carry a uniform `Tm`
   and default residual state: Priority 1 alone unlocks ~376 candidates
   into the downstream gates; the bulk stays behind Priority 2
   (rotated `Tm`), matching the sealed ~95%-rotated overlap analysis.

## 8. Open questions

- OCG default-visibility resolution: which configuration dictionary governs
  (D vs alternate configs), and is visibility stable across viewers?
- Nested wrapper depth cap: is there a corpus-measured maximum, or does v1
  need an explicit depth budget with its own reject code?
- Rotated growth-zone gates: how do the occupancy/background probes transform
  under 90°-family rotations vs arbitrary angles — same code path or a
  restricted 90°-family v1?
- Index persistence: per-session only, or survives save/reopen via digest
  keys? (Privacy: digests only, never text.)
- `malformed_pairing` tolerance (census 2026-08-14): 35.8% of the gated
  population sits in the v1 malformed bucket (unbalanced / q/Q-crossing /
  EMC-underflow-poisoned pages).  The PDF spec permits marked-content
  sequences to straddle q/Q — is the corpus's crossing shape provably
  inert (pure `/OC` wrapper whose splice never crosses the BDC/EMC
  boundary), and can a later slice admit it with its own proof
  obligations?  Needs the structural-vs-page-poison decomposition first;
  v1 stays fail-closed.
