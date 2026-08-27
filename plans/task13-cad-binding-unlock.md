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
2. [x] Priority 1 red matrix (taxonomy admissions + the 5 proof obligations +
       staleness pins), then implementation; separate PR.
       (2026-08-14: 28-test red matrix (27 red / 1 explicit control) →
       green; four stable `MC_*` codes; classification promoted into
       `model/text_commit/marked_content.py`; serialized-`/OCProperties`
       visibility resolution — see §7 and the get_ocgs PITFALLS entry.)
3. [x] Re-run funnel; record the new marked-content survival honestly.
       (2026-08-14: `outside_marked_content` 0 → **6,872** — exactly the
       census-predicted admissible set; **376 shows now clear every
       plan gate** (was 0); corpus e2e sample: 22 pages attempted,
       8 prepared, 8 committed, 8 reopen-extraction OK, 0 failures.
       §7 step-2 record.)
4. [x] Priority 2 red matrix (uniform-rotation predicate boundaries, rotated
       kern axis, visual-space verify), then implementation; separate PR.
       (2026-08-19 census-before-code sub-step DONE: rotated-TRM census on
       the post-P1 TRM-gate population — **6,417/6,444 uniform rotations,
       6,413/6,417 (99.94%) visual quarter-turn, 5,558 predicted newly
       bindable**; v1
       scope locked to the quarter-turn family — §7 census record and
       scope decision; classifier in `scripts/trm_taxonomy.py`, funnel
       `trm_census` block; 70-test red-first matrix + 2-agent adversarial
       round, 3 findings fixed red-first.)
       (2026-08-20 red matrix DONE: 95 red / 5 controls across four files
       + review round, 3 findings fixed red-first — §7 P2-B record.
       2026-08-20 implementation DONE: red matrix green, transforms.py
       single source, directional geometry/growth/fingerprint — §7
       implementation record.)
5. [ ] Re-run funnel; record rotated-Tm survival. The missing post-P2 funnel
       artifact remains explicit coverage-evidence debt; it does not block
       the measured Priority 3 latency work or P3-D interpretation-reuse
       spike, and must not be checked off without an actual run artifact.
6. [ ] Priority 3 spike: index design + latency measurement harness (ties
       into the preview-latency follow-up from Task 12 §8); own PR(s).
       P3-A, P3-B, and P3-C are COMPLETE; P3-D is NEXT, so the parent step
       remains open. (2026-08-21 first half DONE — P3-A read-only spike on
       `task13/p3-replay-indexing`: invalidation contract
       (pull-validation), two prototype shapes measured on the corpus,
       **Shape A materialized ShowOp table selected, Shape B checkpoint
       hybrid rejected on measured memory**; replay is ~90% of the
       dense-page keystroke cost, validated warm lookups 8–14 ms vs
       2.7–4.8 s cold.  Full record:
       `plans/task13-p3a-replay-index-spike.md`.  P3-B production replay
       reuse is complete (`plans/task13-p3b-replay-reuse.md`); P3-C
       post-prepare stream-write latency is complete
       (`plans/task13-p3c-preview-postprepare-latency.md`). P3-D must start
       with a fresh stage census on the new correctness closure, then test
       bounded DisplayList/TextPage interpretation reuse.)
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
    **SUPERSEDED by step 2**: `get_ocgs` (and rendering) turned out to be
    a load-time snapshot that `set_layer`/raw `/OCProperties` writes never
    refresh — step 2 resolves visibility by PARSING the serialized
    catalog `/OCProperties` instead (`resolve_default_visibility`), which
    is what every future opener of the committed artifact resolves.
    Census numbers unaffected (corpus docs are opened fresh from disk, so
    snapshot == serialized) — re-verified byte-identical in the step-3
    run.
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

- 2026-08-14 (step 2 — Priority 1 admission; red-first, 28-test matrix in
  `test_scripts/test_text_commit_mc_admission.py`, 27 red / 1 explicit
  control pinning that underflow pages keep admitting UNwrapped shows):
  - **Four stable reject codes**, one per independent gate, test keeps its
    own literals: `mc_wrapper_not_pure_layer` (any non-/OC semantic class,
    detail = class slug), `mc_layer_not_default_visible` (hidden OCG or
    OCMD), `mc_malformed_pairing` (unclosed / q-Q-crossing / EMC-underflow
    page / evidence-depth mismatch), `mc_splice_crosses_wrapper_boundary`
    (proof obligation 4).  Details carry class slugs ONLY (§10 pin: the
    `7Q` fixture marker asserted absent from every detail).
  - **Classification promoted to `model/text_commit/marked_content.py`**;
    `scripts/wrapper_taxonomy.py` delegates (single source of truth), the
    census `show_verdict` fold stays script-side.  Resolution is
    parse-based (`resolve_properties_mapping` over the page object via
    `parse_pdf_value`; inherited `/Resources` → unresolved, fail-closed).
  - **Serialized-truth visibility** (`resolve_default_visibility`): parse
    catalog `/OCProperties` (`/OCGs` registration + `/D` `/BaseState`,
    `/ON`, `/OFF`; OFF wins a dual listing — fail-closed on ambiguity).
    NOT `get_ocgs`: PyMuPDF's OC descriptor (and rendering) is a
    load-time snapshot that `set_layer`/raw writes never refresh
    (verified empirically; PITFALLS entry, index 266).  Alternate
    (`/Configs`) configurations are NOT consulted: default config only,
    per plan §2's "default configuration" contract.
  - **Boundary guard** (obligation 4): `McWrapper` now records
    `open_op_end`/`close_stream_xref`/`close_op_start`; the whole-op
    range must sit strictly inside EVERY enclosing wrapper's span, same
    stream both ends — cross-stream wrappers refuse with the boundary
    code (unit-pinned so deleting the guard fails a test).
  - **Fingerprint closure** (obligation 5): `page_fingerprint` folds the
    resolved `/Properties` mapping (name + binding xref identity +
    canonical target object) and each target's resolved visibility bit
    (on/off/absent — RESOLVED shape, Task 12 lesson).  Pinned stale:
    visibility flip via `set_layer`, `/Properties` re-point to another
    (also-visible) OCG, OCG object key mutation.  Stable across the
    `tobytes()` scratch round trip (fingerprint-roundtrip suite green).
  - **Funnel gate now mirrors production admission** (same
    `admit_show_wrappers` call); the `state:marked_content_wrapper` loss
    slug is retired for the `MC_*` codes; stage NAMES unchanged, and
    `outside_marked_content` now counts admissibly-wrapped survivors too.
  - Obligations 1–3 pinned as tests: encode round-trip and splice bytes
    identical inside vs outside a wrapper; save→reopen extraction
    equality; render-hash (pixmap sha256) equality wrapped vs unwrapped
    before AND after commit.
  - **Adversarial review round** (Codex + serial deep-reasoner workflow,
    both on the same diff independently; 9 red pins added, all fixes
    red-first):
    1. `/D /AS` usage auto-states can hide an `/ON`-listed OCG in a
       conforming viewer → any AS-selected OCG is now UNPROVABLE (dropped
       from the visibility map; a poisoned /AS shape poisons the whole
       config); adding an AS rule post-prepare goes stale via the
       resolved-bit fold.
    2. `/BaseState` was fail-open (any non-`/OFF` value → visible) → now
       deref'd and required to resolve to exactly `/ON`/`/OFF` (absence =
       ON per spec); indirect-BaseState-target flips post-prepare go
       stale; `/ON`/`/OFF`/`/AS` entries present-but-unresolvable poison
       the config.
    3. Parse-budget asymmetry: classification reads targets via the
       unbudgeted `xref_get_key` surface while the fold parsed
       whole-object (over-budget targets collapsed to a constant
       sentinel absorbing all mutations) → the fold now digests the SAME
       structured key/value surface (`_fold_target_structured`);
       `/Type`-flip on a >1 MiB object red-pinned stale.
    4. Duplicate dict keys parsed last-wins vs mupdf's lookup order
       (viewer behavior undefined = unprovable) → the shared
       `parse_pdf_value` now refuses duplicates outright
       (`PdfParseError`); Type0 suites and the corpus funnel re-verified
       unchanged.
    5. Fold name field length-prefixed (frame injectivity — defense in
       depth, no observable pin).
    Rejected finding: "details must be bare slugs" — repo §10 contract is
    no-document-values; prose + slug is house style.

### Step-3 funnel record (corpus aggregates, 2026-08-14, admission live)

Full funnel with the e2e sample enabled.  Base stages and every census
aggregate byte-identical to the step-1 record; the only loss-slug change
is the retirement of `state:marked_content_wrapper` (10,701) for
`mc_malformed_pairing` (3,829) — no other `MC_*` code fires on the
corpus (zero boundary violations, zero hidden/semantic wrappers, exactly
as the census predicted).

| stage / aggregate | doc_0 before → after |
|---|---|
| `outside_marked_content` | 0 → **6,872** |
| `uniform_trm` | 0 → 428 (then 52 `state:hscale` losses) |
| `default_text_state` … `replacement_encodable_proxy` | 0 → **376** (every downstream gate passes) |
| new losses at the mc gate | `mc_malformed_pairing` 3,829 (only) |
| rotated-Tm loss (now visible) | `state:trm_not_uniform_scaled` 6,444 |
| e2e sample (in-memory copies) | 22 pages attempted, 8 prepared, **8 committed, 8 reopen-extraction OK, 0 failures**; refusals: 12 `ambiguous_source_match`, 2 `verification_failed` (both correct fail-closed behavior) |

Reading: Priority 1 is DONE at 64.2% of its gated population; the funnel
now shows the Priority 2 bottleneck directly (6,444 rotated-Tm losses on
admitted-or-unwrapped shows).  doc_1 unchanged (all TJ-array).

- 2026-08-19 (step 4 census-before-code — rotated-TRM census tooling;
  red-first, 70-test matrix in `test_scripts/test_trm_census.py`):
  - **Classifier lives in `scripts/trm_taxonomy.py`**, outside `model/`
    until the Priority-2 admission slice promotes it (same discipline as
    the step-1 wrapper taxonomy).  Two orthogonal dimensions: user-space
    SHAPE of the `Tm × CTM` linear part (`non_finite` / `singular` /
    `reflected` / `sheared` / `non_uniform_scale` /
    `axis_aligned_uniform_positive` / `uniform_rotated_positive`, fixed
    gate precedence finite → non-singular → orientation → orthogonality
    → equal norms, RELATIVE tolerance 1e-6), and visual baseline
    DIRECTION after `transformation_matrix × rotation_matrix` (`right` /
    `left` / `up` / `down` / `oblique` / `degenerate`, visual y down —
    the same chain production `inspect`/`plan` use).  Shape is
    angle-blind on purpose: a rotated `Tm` compensating a page
    `/Rotate` is only classifiable against the visual matrix.
  - **Funnel `trm_census` block** hangs off the existing
    `state:trm_not_uniform_scaled` gate — population = exactly the
    post-P1 TRM-gate deaths, membership decided by the production
    predicate itself; no admission change, all sealed stages/slugs
    byte-identical (cross-checked between two runs).
  - **Adversarial round (2-agent Attack → skeptical Verify, serial):
    3 confirmed findings, all fixed red-first before the corpus run;
    3 refuted.**  F1: strict tolerance could silently drop ROUNDED
    quarter turns → added the diagnostic `near_miss` section (loose
    1e-3 re-classification, never predicted).  F2: predicted chain had
    no absolute scale floor while production's `_uniform_scale` rejects
    `a <= _EPS` → added `ABS_SCALE_FLOOR` (1e-6) in front of the
    predicted chain.  F3: predicted front gate was quarter-turn-only
    while plan §3 pins any-uniform-rotation → the chain now measures
    BOTH candidate scopes (`any_uniform_rotation` and the quarter-turn
    subset at each terminal).  Refuted: conditioning-style singular test
    on extreme aspect ratios (defensible, not corpus-real); `/Rotate`
    int as a §10 leak (bounded reason-code-level telemetry — still
    hardened to a closed 0/90/180/270/`other` vocabulary); `_pdf_num`
    sub-5e-9 collapse in the fixture mutator (latent footgun, no test
    invalidated).
  - **Geometry pin worth recording**: `/Rotate 270` displays the page
    turned 90° counter-clockwise, so the compensating CAD idiom is a
    **−90° `Tm`** (baseline down on the paper → visually right); a +90°
    `Tm` on the same page reads LEFT.  The census direction tests pin
    both readings.
  - **PDF numbers have no exponent notation**: `%g`-formatting a
    quarter-turn matrix emits `6.12e-17`, which a real content-stream
    lexer refuses — the whole `Tm` silently voids and the fixture tests
    nothing.  `set_text_matrix` formats fixed-point; quarter-turn
    fixtures use exact 0/±1 coefficients.

### Step-4 census record (corpus aggregates, 2026-08-19, read-only)

Population: the 6,444 `state:trm_not_uniform_scaled` deaths (doc_0 only;
doc_1 has zero TRM losses — all its mass is TJ-array).  All 6,444 are
`wrapped_p1_admitted` (the P1 unlock feeds this gate directly) and all
sit on `/Rotate 270` pages.

| aggregate | doc_0 |
|---|---|
| `user_shape` | `uniform_rotated_positive` **6,417**, `reflected` 27 — zero sheared / non-uniform / singular / non-finite |
| `visual_direction` | `right` **6,212**, `left` 123, `down` 100, `up` 5, `oblique` **4** |
| `near_miss` | **empty** — no rounded quarter turns; the strict 1e-6 tolerance loses nothing on this corpus |
| `predicted` (any-uniform scope) | 6,417 → default-state 5,576 → decoded/reproduced **5,561** bindable + encodable (33,605 chars) |
| `predicted` (quarter-turn scope) | gate 6,413 → **5,558** bindable + encodable |

**Scope decision (v1 lock)**: quarter-turn family — positive-orientation
uniform rotation+scale with visual baseline 0°/90°/180°/270° only.  The
census's decision rule (advisory): dominant eligible bucket must be the
visual quarter-turn family — it is, at 6,413/6,417 uniform rotations
(99.94%; equivalently 6,413/6,444 = 99.52% of all TRM-gate deaths); the
broad any-uniform scope would add only **3** bindable shows while
forcing arbitrary-angle verifier geometry.  Non-quarter-turn uniform
rotations stay fail-closed with their own stable reason
(`trm_rotation_not_quarter_turn` in the P2-B red matrix); `reflected`
27 stay fail-closed permanently (plan §3).  **Acceptance for the P2
implementation**: newly admitted set == census prediction exactly —
6,413 at the TRM gate, 5,558 through every downstream gate.

- 2026-08-20 (step 4 P2-B — rotated-TRM admission red matrix, tests only;
  no production change in this commit):
  - **Contract module decision**: the census taxonomy is promoted to a new
    production leaf `model/text_commit/transforms.py` — the single source
    replay/inspect/plan/verify share and `scripts/trm_taxonomy.py` must
    delegate to (pinned: the module never imports `scripts/`, the census
    classifier imports it, and a probe-grid equivalence test keeps the two
    from drifting).  Pinned API: `combined_linear(tm, ctm)`,
    `shape_reject_reason(linear, rel_tol=REL_TOL)`,
    `visual_baseline_direction(page, linear, rel_tol=REL_TOL)`,
    `admission_verdict(page, tm, ctm) -> TrmVerdict(reject_reason,
    direction, scale)`, `map_text_quad_to_visual(page, tm, ctm, quad)`,
    with `REL_TOL = 1e-6` (relative) and `ABS_SCALE_FLOOR = 1e-6`
    (absolute, closed boundary — mirrors replay's `_EPS` floor).
  - **Seven stable codes** (not six): the census adversarial round proved
    the absolute scale floor is an independent condition, so it gets its
    own `trm_scale_below_floor` instead of hiding inside another code.
    Fixed precedence: finite → singular det → absolute scale floor →
    positive orientation → orthogonal axes → equal axis norms → cardinal
    visual direction; dual-defect matrices pin the attribution.
  - **Boundaries at three scales** (1e-3 / 1 / 1e3), just-inside 9e-7 vs
    just-outside 1.1e-6 for every relative gate; the /Rotate ×
    quarter-turn-Tm visual truth table is pinned in full (numerically
    verified through `transformation_matrix × rotation_matrix`).
  - **PreparedEdit gains `growth_direction`** (cardinal slug, pinned on
    every ink-growth candidate; defaulted so existing constructions stay
    valid), and the four visual growth directions each pin: blank→admit
    (growth on the correct visual edge only), glyph→`glyphs:`,
    vector/image/page-shading→`occupancy:`, uniform mismatched
    form-xobject band→`background:`, off-page→`growth_outside_page`, and
    obstacle-behind-the-baseline→still admits (forward-only proof).
  - **Kern oracle fixture**: the successor show must stay
    advance-dependent but clear of the growth strip, so the fixture
    inserts a kern-only `[-2000] TJ` (24pt pure text-space advance, no
    repositioning) between target and tail — an immediately-adjacent
    successor sits IN the growth zone and is *correctly* refused by the
    blank-growth gate (the axis-aligned control proved this red-first).
    The kern scalar itself is pinned rotation-invariant (same advances →
    same `%.6f` number, rotated or not).
  - **Page-geometry staleness**: prepare → mutate `/Rotate` (page API and
    raw xref), `/UserUnit`, `/CropBox`, `/MediaBox`, and the INHERITED
    `/Rotate` on the `/Pages` ancestor → all must go `STALE_PLAN` with
    zero mutation (today they slip the fingerprint and die later as
    dishonest `FAILED`/committed).  Controls pin the fold canonical:
    direct-vs-inherited fingerprints equivalent, stable across
    `tobytes`→reopen, and no false-stale on unmutated commits.
  - **Adversarial round on the red contract** (serial 2-agent
    Attack→skeptical Verify, wf_77bdb1c6): 3 findings, all confirmed,
    all addressed red-first.  F1 (important): two precedence links were
    unpinned — added reflected∧sheared → `trm_reflected`
    (orientation-beats-orthogonality; the mirror probe only pins
    orientation-beats-direction) and oblique∧non-uniform /
    oblique∧sheared → shape codes at unit, verdict, AND prepare level
    (kills direction-first short-circuits).  F2 (minor): census
    aggregate counts in test docstrings — explicit KEEP decision:
    aggregates are precedent-consistent with this committed plan and
    outside the data policy's prohibited raw-evidence categories
    (which bans text/filenames/paths/coefficients, never slug-level
    counts).  F3 (minor): the reference-point sampling-POSITION clause
    was docstring-claimed but unpinned — docstring softened;
    **implementation-phase obligation** (FULFILLED in the implementation:
    a direction-parametrized invariant pin now asserts every returned
    sampling point's 3×3 neighbourhood is disjoint from halo(verify)
    for all four directions — the sampler needed no new parameter, its
    disjointness filter is the structural guarantee).
  - **Red tallies** (true red confirmed before any implementation):
    admission 44 red / 1 control; kern 12 red / 1 control; growth
    directions 32 red / 0; page geometry 7 red / 3 controls — 95 red,
    5 explicitly-labeled green controls, every red failing via today's
    blanket `unsupported_text_state`, the missing `transforms` module, or
    the missing `growth_direction` field.

- 2026-08-20 (step 4 P2 — quarter-turn admission IMPLEMENTATION; the
  red matrix above turned green — 104/104 across the four files (95 red
  → green, 5 controls still green, plus the 4 new F3 invariant pins)):
  - **`model/text_commit/transforms.py`** is the production single
    source (shape gates / visual direction / admission verdict / the
    text-quad→visual mapping); `scripts/trm_taxonomy.py` is now a thin
    delegate (`shape_reject_reason(..., abs_floor=0.0)` reproduces the
    census's floor-free shape vocabulary byte-identically; the floor
    stays in its predicted chain).  Seven `trm_*` codes on
    `RejectReason`; `inspect.bind_source_text`'s blanket refusal
    replaced by `admission_verdict` with fixed, coefficient-free
    details.
  - **Geometry**: plan's fallback target box now rides
    `map_text_quad_to_visual` (reproduces the historical axis-aligned
    halo exactly); `_grown_verify_bbox` extends the USER-space rect
    edge chosen by the combined baseline vector (caller-bbox cross
    extent preserved; axis-aligned path arithmetically unchanged);
    `PreparedEdit.growth_direction` (cardinal slug) rides the plan
    token.  Kern arithmetic untouched — proven rotation-invariant by
    the red matrix, not re-derived.
  - **Verify**: `_growth_zone_rect` infers the forward strip from the
    DOMINANT extended edge (immune to sub-point cross-edge slivers;
    existing unit-call signatures unchanged); `count_growth_zone_glyphs`
    generalizes the own-glyph exclusion per direction and converts to
    dict space; occupancy intersects convert the growth rect through
    `derotation_matrix` — `get_drawings`/`get_image_rects` speak
    UNROTATED page space (new PITFALLS entry 269; found by the
    four-direction red matrix's CAD-idiom cases).
  - **Fingerprint**: `_update_page_geometry` folds inheritance-RESOLVED
    /Rotate//MediaBox//CropBox (PyMuPDF accessors), page-local
    /UserUnit (one indirect hop), and the live visual matrices — the
    prepare→mutate→commit matrix (page API, raw xref, and /Pages
    ancestor) now dies STALE_PLAN with zero mutation; canonical
    equivalence and round-trip stability pinned by controls.
  - **Funnel** (`measure_type0_funnel.py`): the TRM gate now mirrors
    the production admission; the blanket `state:trm_not_uniform_scaled`
    slug is retired for per-code `state:trm_*` slugs (same pattern as
    P1's retirement of `state:marked_content_wrapper`); new stage
    `trm_rotated_admitted`; `trm_census.acceptance` block compares the
    census-predicted vs production-admitted sets IN MEMORY and emits
    counts + symmetric differences + membership booleans only.
    (`scripts/measure_tier_funnel.py` — the legacy simple-font tier
    funnel — still models the OLD blanket gate; registered in TODOS,
    not this slice.)
  - **Replaced-contract test updates** (the old pins the red matrix
    supersedes): structural gates (off-axis → per-code; the point
    reflection = 180°×10 and the 90° turn now PLAN — the mirror keeps
    `trm_reflected`), replay's rotated-bind refusal → now binds, the
    audit script's rotated count → binds with a sheared fixture keeping
    the refusal path pinned, and the census funnel test → admission +
    acceptance block.

- 2026-08-20 (step 4 P2 — implementation review round, serial
  Attack→Verify workflow wf_3cb287ec; the Verify agent died on the
  session limit, so every finding was verified by hand — two confirmed
  and fixed red-first, three documented):
  - **F2 (important, CONFIRMED → fixed red-first)**: the admission gate
    ran for EVERY bound show, so replay-uniform matrices carrying
    boundary residuals exactly ON replay's absolute tolerance
    (`|b| == 1e-6`) — previously bound and planned — flipped to
    `trm_sheared` under the relative shape checks, violating "the
    pre-P2 admitted set stays admitted byte-identically"; the funnel
    (which gates its admission mirror on `not trm_uniform_scaled`) also
    diverged from production on exactly those shows.  Fix:
    `bind_source_text` skips the shape gate for replay-uniform shows —
    with the single exception of `trm_non_finite`, which replay's
    comparison-based idiom test cannot flag (NaN compares False
    everywhere) and which stays refused unconditionally (a deliberate,
    strictly-fail-closed delta from pre-P2, unreachable from real
    numeric content).  Such a sliver show plans with
    `growth_direction=None` and rides the axis path exactly as before
    P2.  Pin: `test_planner_still_admits_replay_uniform_boundary_residuals`
    (red as `trm_sheared` before the fix).  The non-finite corner is the
    one residual funnel/production divergence — documented, not mirrored
    (the instrument would have crashed on NaN upstream anyway).
  - **F4 (CONFIRMED empirically → fixed red-first)**: `/UserUnit 2.0`
    reads `('float','2')` live but `('int','2')` after `tobytes`→reopen
    (MuPDF prints integer-valued reals minimally), so the raw
    `kind:value` fold broke live-vs-scratch fingerprint equality — every
    prepare on such a document would fail its scratch-apply forever.
    Fix: numeric values fold as canonical `num:{float(value)!r}`;
    `kind:value` survives only for non-numeric kinds.  New PITFALLS
    entry 270.  Pin:
    `test_fingerprint_is_stable_when_userunit_is_spelled_as_a_real`
    (red before the fix).
  - **F1 (verified — instrument property, documented not changed)**: the
    funnel acceptance sets are one-directional by construction:
    predicted-gate membership uses the census's STRICT
    `SHAPE_UNIFORM_ROTATED` classification while the production side
    uses `admission_verdict`, so a replay-rotated show whose combined
    linear classifies axis-aligned under the relative tolerance (e.g.
    sub-relative residuals at large CTM scale) can be
    production-admitted but predicted-excluded — never the reverse
    (predicted ⊆ production).  A nonzero symmetric difference is
    therefore always a TRUE report that production admits something the
    census did not predict — the instrument can only fail loudly, never
    pass wrongly.  Kept as-is: that fail-loud asymmetry is exactly what
    the census-before-code acceptance is for; the committed census shows
    `user_shape axis_aligned = 0` among rotated candidates, so the
    corpus run is expected to close at difference 0.
  - **F3 (verified — accepted as documented)**: `_grown_verify_bbox`'s
    axis path round-trips the caller bbox through `~visual`/`visual`, so
    the three unchanged edges can drift ~1 ulp of the page dimension
    (~1e-13 pt) relative to the historical direct edge extension, and
    the growth norm uses `hypot(a, b)` vs the old scalar `a` (~5e-13
    relative for admitted residuals).  Bounded, fail-closed (a
    knife-edge pixel lands as an extra probe or hands back to the
    outside-halo check — never unchecked), and absorbed by the 1e-6
    token quantization and every pinned tolerance; the plan §7 claim
    "arithmetically unchanged" is hereby corrected to "unchanged within
    ~1 ulp, one-sided clamped by the min/max union".
  - **F5 (verified — doc drift, docstrings corrected)**: verify never
    reads `PreparedEdit.growth_direction` — the strip edge is re-derived
    from target/verify bbox geometry (dominant-edge), which agrees with
    the stored slug by construction since `_grown_verify_bbox` extends
    exactly the edge the slug names, and the slug itself is token-bound.
    The `plan.py`/`verify.py` docstrings claiming verify "consumes" the
    shared direction were corrected to state the re-derivation and the
    agreement argument; threading the field through verify's signatures
    was declined (no behavioral gap for engine-built plans; hand-built
    `PreparedEdit`s are already outside the token's protection).

### Step-5 funnel acceptance record (corpus aggregates, 2026-08-20, --no-e2e)

Run at the sealed P2 tip (feat 0d5333b + fix 0862906), same two-document
corpus as every prior record; counts and set-membership results only.

- **Set-identity acceptance (the verdict's contract 6 — sets, not just
  numbers): PASS.** `trm_census.acceptance` (doc_0): predicted_gate
  **6,413** == production_gate **6,413**, gate_symmetric_difference
  **0**, gate_membership_exact **true**; predicted_downstream **5,558**
  == production_downstream **5,558**, downstream_symmetric_difference
  **0**, downstream_membership_exact **true**.  Membership was compared
  in memory on `(page_index, stream_xref, seq)` keys; only counts /
  differences / booleans are published.  F1's fail-loud asymmetry
  (predicted ⊆ production by construction) did not materialize.
- **Census counters unchanged vs the pre-implementation baseline**
  (7ea5f56-era run): shows_total 28,043; on_type0_font 27,820;
  single_hex_tj 27,250; within_replay_budget 10,701;
  outside_marked_content 6,872; the full `trm_census` block
  (user_shape / visual_direction / page_rotate / overlap / predicted)
  is identical.
- **The retired blanket slug decomposes exactly**: old
  `state:trm_not_uniform_scaled` 6,444 = 6,413 `trm_rotated_admitted`
  + 27 `state:trm_reflected` + 4 `state:trm_rotation_not_quarter_turn`.
  Downstream `replacement_encodable_proxy` 5,934 = 376 (axis-aligned,
  unchanged) + 5,558 (quarter-turn family) — the +5,558 newly bindable
  shows predicted by the step-4 census, landed exactly.
- doc_1 unchanged: no budget-eligible single-hex-`Tj` shows (all
  stages 0 past `on_type0_font` 543), as in every prior record.
- E2E sample: not run in this pass (`--no-e2e`); the corpus e2e pass
  stays optional per the step-4 advisory and can ride the rollout-gate
  work.

## 8. Open questions

- OCG default-visibility resolution: which configuration dictionary governs
  (D vs alternate configs), and is visibility stable across viewers?
  (Step 2 partial answer: v1 resolves the SERIALIZED default config `/D`
  only, fail-closed on anything else; alternate `/Configs` are ignored —
  an OCG visible only under an alternate config still admits via /D. The
  cross-viewer stability half stays open.)
- Registered over-reject precision items from the step-2 review round
  (all fail-closed, none block v1; recover in later slices if the corpus
  demands): inherited `/Resources` from `/Pages` ancestors (no `/Parent`
  walk — a page with hoisted resources zeroes the unlock for that doc);
  whole-catalog/`/OCProperties` parse under the 1 MiB / 50k-token budget
  (a ~16.7k-layer doc would reject everything with an unhelpful code —
  targeted `xref_get_key` hops would fix); `#xx` hex escapes in
  content-stream name operands not decoded (an escaped `/O#43` tag
  mismatches `OC`); indirect `/Type` on property targets not deref'd
  (genuine OCG with `/Type 15 0 R` rejects; if ever deref'd, the target
  must join the fingerprint fold in the same change).
- Nested wrapper depth cap: is there a corpus-measured maximum, or does v1
  need an explicit depth budget with its own reject code?
- Rotated growth-zone gates: how do the occupancy/background probes transform
  under 90°-family rotations vs arbitrary angles — same code path or a
  restricted 90°-family v1?
  (Step-4 census answer: restricted 90°-family v1 — 6,413/6,417 uniform
  rotations (99.94%) are visual quarter-turn and the broad scope buys
  only 3 shows; the probes
  generalize through ONE shared cardinal `growth_direction`, not four
  divergent implementations and not arbitrary-angle polygons.  The 4
  oblique + 27 reflected shows stay fail-closed with their own codes;
  arbitrary-angle admission would be its own later slice with new census
  evidence.)
  (Step-4 implementation answer, 2026-08-20: SAME code path for all four
  directions — `_growth_zone_rect` infers the forward strip from the
  dominant extended edge, the glyph counter and occupancy intersects
  convert to unrotated dict space first (PITFALLS 269), and the
  axis-aligned visual strip proved sufficient exactly as the census
  predicted.  CLOSED.)
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
