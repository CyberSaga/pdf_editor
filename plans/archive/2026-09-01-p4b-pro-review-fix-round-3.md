# P4-B fix round 3 — Pro LOOP_REVIEW findings on `bdec284`

**Goal:** close the four findings from the ChatGPT-Pro `LOOP_REVIEW` (verdict
continue, "do not merge bdec284 as-is") of `task15/p4-b1-hscale-admission`,
without widening into Form-XObject traversal.

**Status:** complete 2026-09-01.

## Findings (re-verified against source before any edit)

- **F1 (P1)** — `_duplicate_source_painter_detail` (plan.py:210) selects
  candidates by `candidate.font_resource == target.font_resource`. PDF
  resource names are aliases, not identity: `test_overlapping_different_
  font_resource_is_admissible` installs `/F_ALT` pointing at the SAME
  `fixture.font_xref`, paints the same text at a 1.2pt overlap, and asserts
  `PreparedEdit`. Confirmed. The candidate core is also derived from the
  TARGET's advance scaled by a font-size ratio, ignoring the candidate's own
  `Tc`/`Tw`/`Ts`; `rise` is ignored on both sides even though replay keeps it
  out of `tm` (`origin_user=_mat_apply(trm, 0.0, state.rise)`, replay.py:463).
- **F2 (P2)** — `kern_for_displacement` (patch.py:283) guards its inputs and
  its RESULT but not its intermediates: `font_size=1e307` makes
  `show.font_size * 100.0` overflow to `inf`, so the function returns a finite
  `-0.0` where the algebraic value is `-1e-4`. A finite result is not proof of
  a correct result.
- **F3 (P2)** — `_build_tier1` (plan.py:868) derives `background_bbox_page`
  (and `verify_bbox_page`) after `_classify_common`'s `target_bbox` finiteness
  gate and stores them unchecked. TRM shape admission inspects only the linear
  coefficients, so a non-finite `Tm`/`CTM` TRANSLATION reaches
  `map_text_quad_to_visual` whenever the caller supplied a finite
  `target_bbox`.
- **F4 (P2)** — `scripts/measure_type0_funnel.py::_sole_loss_class` still
  calls itself "an independent full production gate vector" while its
  `downstream_ok` conjunction has no duplicate-painter leg, so it can report
  `all_gates_pass` for shows the planner now rejects. The 6,811 source-bindable
  / 877 newly-admitted hscale figures were measured before the gate existed.

## Affected modules

- `model/text_commit/plan.py` — `_duplicate_source_painter_detail` (semantic
  font identity, candidate-local geometry, rise), `_classify_common`
  (`tm`/`ctm` component finiteness chokepoint), `_build_tier1` (derived
  verify/background bbox finiteness).
- `model/text_commit/patch.py` — `kern_for_displacement` pre-division guards.
- `scripts/measure_type0_funnel.py` (+ `measure_tier_funnel.py`,
  `audit_tier_coverage.py` if they claim parity) — duplicate-painter loss leg.
- Tests: `test_text_commit_duplicate_painter_gate.py` (invert `/F_ALT`, add
  Tc/Tw/Ts/size/alias matrix + disjoint controls + a COMMIT-level twin proof),
  `test_text_commit_hscale_admission.py` (kern counterexample, non-finite
  translation), census tests.
- Docs: PITFALLS (correct the round-2 duplicate-painter entry, do not append a
  second one), ARCHITECTURE §10.1.4/§10.1.6, TODOS (close + reconcile census).

## Design decisions

1. **Candidacy = same `decoded_bytes` AND (same resolved `capability.font_xref`
   OR font identity unprovable).** Resource-name equality is removed entirely.
   Identity is resolved through the same `DocumentFontRegistry` the planner
   already holds — no second source of truth.
2. **Candidate geometry is candidate-local.** Width comes from the CANDIDATE's
   own capability: `cap_c.string_width(target_text, candidate.font_size)`, plus
   the candidate's own `Tc`/`Tw` under the existing `_advance` convention,
   scaled by the candidate's own `Th`. No font-size ratio, no target advance.
3. **Unprovable geometry is BOUNDED, then fails closed only if it could
   matter** — revised after verification showed the blanket rule was an
   admission regression against `bdec284` (a twin 300pt away with a dangling
   `/Tf` blocked every edit of that string). `_painter_reach` derives the
   largest text-space extent whose image can still land on the page; the
   candidate core is widened to it (both directions for `TJ`, whose dropped
   array numerics mean the recorded origin is not where the ink starts) and
   the same overlap test decides. Only `origin_reliable=False`, a
   non-finite/non-positive size or hscale, or a non-derivable reach still
   fails closed outright.
4. **`rise` enters NEITHER core** — reversed after adversarial verification.
   The original decision ("both cores get `[rise, rise + 0.6·font_size]`,
   asymmetry would create false negatives") was wrong on its premise: the
   target's rise is ALWAYS zero, because `_classify_common` refuses any target
   whose `rise != 0.0`. There is no symmetry to preserve — only an
   uncounterbalanced translation of the candidate core, which opened a
   false-admit band at `rise ∈ [7.15, 15.68)` for 12pt text and committed with
   the ghost intact. Both cores are taken at the baseline.
5. **F2 rejects rather than rescues.** The `-100_000.0 * d / (fs * 100.0)`
   shape is load-bearing for bit-identical serialized kern tokens, so the fix
   is a pre-division finiteness/non-zero check on the numerator and the
   denominator, not restructured arithmetic.
6. **F3 gets the class fix, not the instance fix**: `tm`/`ctm` component
   finiteness at the `_classify_common` chokepoint (covers every tier and every
   derived-geometry site), PLUS a bound on
   `verify_bbox_page`/`background_bbox_page` right after derivation in
   `_build_tier1`. That bound is the SAMPLER's, not `isfinite`: verification
   showed a finite-coordinate band (`1.348e308 < |c| ≤ 1.797e308`) where
   `verify._bbox_pixels`' `int(x * 96 / 72)` still raises `OverflowError`, so
   the check is `abs(value) <= _RENDERABLE_COORD_LIMIT` (1e9). It also closes
   the `kern_for_displacement` `ValueError` that escaped `prepare` from
   `_build_tier1`.
7. **F4 branch decision recorded explicitly**: the census corpus IS reachable
   locally (`test_files/`), so the leg is added AND the census is rerun and the
   877/6,811 figures reconciled. If the rerun cannot reproduce the prior
   baseline, the coverage claim is retracted as unreconciled rather than left
   standing.

## Steps

1. Red tests first for F1/F2/F3 (fail before implementation).
2. Implement plan.py / patch.py.
3. Census leg + rerun + reconcile.
4. Gates: focused → ruff → mypy → full suite (detached) → `git diff --check` →
   aggregate-only privacy scan of every changed census surface.
5. Adversarial verification fan-out (one agent per finding + completeness
   critic against all five `validation_required` items).
6. Docs + archive this plan.

## Open questions / scoped residuals

- Form-XObject-hosted twins remain out of scope this round (Pro: "do not
  broaden into Form-XObject traversal in this round"). Damage stays bounded
  by V0d's raster halo.
- The 0.6-em core under-covers tall ink (a descender or an accent can overlap
  while the cores do not). Pre-existing in the `Tm` form at `bdec284`;
  raising the core to a true ~1.3-em ink envelope trades it for rejecting
  legitimate stacked same-text lines at sub-1-em leading, so the constant was
  NOT retuned under time pressure.
- Exact `TJ` segment geometry (re-lexing the operand array from stream bytes
  to recover per-item extents) is deferred to P4-B2. `_painter_reach` is the
  conservative stand-in: it never under-covers, and it costs admission only
  for `TJ` twins on the target's own baseline.
- `_painter_semantics` can over-match two genuinely different simple fonts
  that share subtype/encoding/advance source and carry no `/Widths`. That
  direction is fail-closed (a spurious rejection, never a ghost) and needs
  identical decoded bytes plus core overlap to matter at all.

## Census reconciliation (2026-09-01, sealed two-document corpus)

`source_bindable` is unchanged at **6,811** for doc_0, so the 877-show hscale
figure from P4-B1 stands as measured. Downstream changed: the new
`duplicate_painter_only` bucket takes **187** shows, so `all_gates_pass` is
**6,624**; `tj_array_only` falls 130 → 112 (18 TJ shows now also lose on
duplicate and fall to `other`); `hscale_only` stays 0; doc_1 stays all-zero.
The report was privacy-scanned: no document text, basefonts, resource names,
file basenames, or non-ASCII values.

## Decisions log

- 2026-09-01: Red confirmed before implementation. The duplicate matrix failed
  4/15 (alias resource admitted; candidate-local Tc ignored; rise ignored, so a
  superscript twin was wrongly refused; commit-level alias proof admitted), and
  both new numeric tests failed — the kern counterexample returned `-0.0`
  instead of raising, and the non-finite-translation case was caught only late,
  as `verification_failed` from verification rather than as a planner reason.
- 2026-09-01: `_advance` alone was NOT enough for candidate-local widths: for
  Identity-H, `FontCapability.string_width` returns `None` and the target's own
  advance comes from `cid.advance_points`. Added `_painter_advance` so a twin is
  measured through exactly the branch the target uses, instead of a generic
  path that would have failed every Type0 twin closed and hidden the fix behind
  a fail-closed verdict.
- 2026-09-01: Identity-H `Tw` genuinely cannot widen a twin (PDF 32000-1 §9.3.3
  applies word spacing to single-byte code 32 only). The Tw case is therefore
  kept as an ADMISSIBLE control asserting exactly that, rather than dressed up
  as a rejection case it cannot be.
- 2026-09-01: `_duplicate_source_painter_detail` was made public
  (`duplicate_source_painter_detail`) because the census now CALLS it instead of
  mirroring it — a hand-copied mirror is what drifted into F4 in the first place.
- 2026-09-01: `audit_tier_coverage.py` and `measure_tier_funnel.py` do not get
  the gate: neither has the page replay and font registry in scope. Both already
  enumerate their omissions, so each gained an explicit "upper bound, not
  parity" disclaimer instead of a silent gap.

- 2026-09-01 (post-verification round): a four-agent adversarial fan-out (one
  per finding plus a completeness critic against the five `validation_required`
  items) returned DO-NOT-MERGE on the first cut. Six defects, all reproduced to
  `CommitStatus.COMMITTED` or to an escaping exception, and all now closed:
  (a) the `rise` term I added was itself a regression against `bdec284`;
  (b) a `TJ` twin's leading kern moves ink off the recorded origin, and a
  second kern inside the array splits it — neither is visible in `ShowOp`;
  (c) a cloned font dictionary differing only by subset tag defeated
  xref/digest identity, and a clone whose `/ToUnicode` will not parse defeated
  the semantic comparison too (it degrades to `advance_source == "none"`);
  (d) the derived-bbox gate proved `isfinite` while the raster sampler's real
  precondition is `|coord| <= ~1.348e308`;
  (e) the new `tm`/`ctm` planner gate had no census leg — F4 reintroduced by
  the F4 fix;
  (f) resolving each candidate through `registry.capability` cost 0.873 ms a
  call, which is 232 ms per interactive `prepare` on a dense bucket and made
  the corpus census infeasible (>295 s on a 114 KB document).
  Fix (f) first: it changes the cost model every other decision depends on.
- 2026-09-01: the two other census scripts' disclaimers claimed the page
  replay and font registry "do not reach here". A probe showed both are live
  at both call sites. Corrected to say the omission is a deliberate scope
  choice — parity belongs to `measure_type0_funnel.py` — rather than an
  impossibility.
- 2026-09-01: `_painter_reach`'s soundness under a non-uniform matrix was
  challenged and checked rather than assumed. The scalar it divides by is
  `|map(1,0) - map(0,0)|` — the mapped length of one text-space unit along
  +x, which is the ONLY direction whose extent is unknown; the core's y
  extent is a known `0.6*Tfs` and rides `map_text_quad_to_visual` exactly.
  Shear, anisotropy and rotation are therefore all carried by the mapping
  and the bound is exact, not an estimate. Confirmed empirically for
  `0.001x`, `1000x`, shear `c=3` and a 45 degree rotation: overlapping
  unprovable twins reject, off-line ones still admit
  (`test_reach_bound_holds_under_exotic_matrices` and its disjoint control).
- 2026-09-01: `_RENDERABLE_COORD_LIMIT` was first set to `1e9` and RAISED to
  `1e308`. A tighter cut would reject geometry the raster sampler handles
  correctly today (probed: a background box at `1.5e305` reaches the sampler
  and returns an ordinary `growth_region_not_blank`), and rejecting what
  still renders is an admission regression, not a safety gain. The limit is
  now the sampler's own precondition (`_bbox_pixels`' `int()` fails above
  ~1.348e308) with headroom. The `kern_for_displacement` `ValueError` that
  `1e9` had been closing as a side effect is closed properly instead: the
  Tier-1 call site converts it to `UNSUPPORTED_TEXT_STATE`, so the
  serialization chokepoint keeps raising while `prepare` keeps returning
  reason codes.
