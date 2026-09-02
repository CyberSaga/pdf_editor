# P4-B1 final bounded review — verdict

```
status: HEURISTIC_CEILING_REACHED
merge_status: NO_MERGE
branch_tip: 49c98ee (task15/p4-b1-hscale-admission, frozen)
superseded_by: P4-B2 exact painter geometry (plans/task15-p4b2-exact-painter-geometry-spike.md)
census_baseline: source_bindable=6811 all_gates_pass=6624 duplicate_painter_only=187 tj_array_only=112 hscale_only=0
census_reach_only: source_bindable=6811 all_gates_pass=4478 duplicate_painter_only=2333 tj_array_only=112 hscale_only=0
```

**Reviewed:** `8dbf809..49c98ee` on `task15/p4-b1-hscale-admission` (round-4 tip, pushed).
**Method:** 5 dimension finders → 2 adversarial refutation lenses per finding
(repro + upstream-blocked) → completeness critic. 26 agents, 2.20M subagent
tokens, 668 tool calls, 54m. One agent died on an API safeguard false-positive;
its verdict was recovered verbatim from its transcript and is counted.

**Verdict: NOT complete.** 10 findings survived adversarial verification, 0 were
refuted. Five are reproduced end-to-end false admits in
`duplicate_source_painter_detail` — the gate whose entire contract is to
fail closed against ghosts.

Scoring note: survival required only that *one* of two lenses fail to refute, so
"0 of 10 refuted" is partly the rule, not purely finder discipline. The five
`false_admit` findings do not lean on it — each carries
`(refuted=false, reproduced=true)` from **both** lenses, with real-engine
`CommitStatus.COMMITTED` and pixel-diff evidence. F7 is the one weak finding
(1 of 2 lenses refuted, neither reproduced). F9 is really part of F2.

## Independent gate status at the tip

| Gate | Result |
| --- | --- |
| `pytest` (full) | 2999 passed, 21 skipped, 5 xfailed (683s) |
| `ruff check .` | clean |
| `mypy model/ utils/` | clean, 52 files |
| `git diff --check` | clean |

All four green. They do not detect any of the findings below — every false admit
is a *silent* wrong answer, not a crash or a lint violation.

## Confirmed findings

Severity `false_admit` = the planner ADMITS a plan and `TieredCommitEngine.commit`
reaches `COMMITTED` while the old glyphs stay painted over the edit. Each was
reproduced by two independent verifiers with the real engine and real fixtures.

| # | Where | Defect |
| --- | --- | --- |
| F1 | `plan.py:337` | A measured advance of **0** yields a zero-width exact quad; `overlap_x > 0.05` then reads "disjoint" for a twin painting directly on top. `/W` legitimately declares 0 for combining marks, so `width_of_cid` believes it. Admits at every offset in the band; verified ghost of 972/6240 differing pixels inside the plan's own target bbox. |
| F2 | `plan.py:440` | `simple_round_trip` grants the narrow exact quad on `encode_simple(text) == candidate.decoded_bytes` — which is ASCII byte-identity and proves nothing about widths or glyphs. `/Widths 200` vs real Helvetica ink → ghost. |
| F3 | `plan.py:240` | `_glyph_identity` dropping widths is right about glyph identity but makes over-matching **no longer free**: a width-only clone now returns `same_font=True`, which is exactly the condition that grants the exact quad measured from that clone's short widths. |
| F4 | `plan.py:337` | The quad equates the pen's **net** advance with the ink span. Negative `Tc`/`Tw` walks glyphs backwards; real ink lies outside the quad. Nothing in `plan.py` gates the sign of `char_spacing`/`word_spacing`. Also mis-shapes the **target** core at `plan.py:415`. |
| F5 | `plan.py:475` | The fail-closed reach path still assumes Tj ink never extends left of the origin (`0.0 - x_pad`). Negative `Tc` paints arbitrarily far left, outside the quad — on the branch that exists *because* identity is unprovable. |
| F6 | `measure_type0_funnel.py:359` | Census docstring declares exactly one known omission, but the Tier-0 `target_bbox` chokepoint (`plan.py:929`) is also unmodelled and is **not** replacement-dependent → `all_gates_pass` over-counts. |
| F7 | `measure_type0_funnel.py:364` | Census never runs `encode_strict`/`glyph_gate` on its replacement → a ToUnicode-ambiguous show counts as `all_gates_pass` though production refuses it. (Weakest finding: 1 of 2 lenses refuted, neither reproduced.) |
| F8 | `test_..._duplicate_painter_gate.py:387` | Metric-clone tests pass with the `_glyph_identity` narrowing reverted; they never assert `result.detail`. |
| F9 | `plan.py:440` | The `simple_round_trip` leg — a new admission-**widening** branch — has zero test coverage. |
| F10 | `test_..._duplicate_painter_gate.py:398` | `test_disjoint_type0_metric_clone_uses_its_own_widths` is vacuous: green under every revert of this round. |

Critic additions (non-safety, `local`): `x_pad` is subtracted from the Tj lower
bound of 0.0 and is ≥ `0.6·Tfs` even at rise 0, an over-refusal that regresses
existing admissions (measured flips 24.5–31.1pt at rise 0, ~52pt at rise 20);
removing the different-font `continue` makes a dense same-bytes bucket ~84×
more expensive on the reach path while `TODOS.md:1039` still cites the old
~15ms/275-way figure; `PITFALLS.md:2728` states as a precondition what the code
implements as one disjunct of three, and `ARCHITECTURE.md`'s "encoding-name
equality is not evidence" is contradicted by `_glyph_identity` using
`capability.encoding`.

## Two facts that reframe the routing

1. **F1, F2 and F3 reproduce at `8dbf809` too.** They are not regressions round 4
   introduced — round 4 changed *which route* reaches the flawed quad, not the
   verdict. Round 4 was still a net improvement: removing
   `same_font is False → continue` closed a strictly larger hole, since before it
   *any* provably-different-font twin was skipped without geometry at all. F3
   exists because those candidates now reach the flawed quad instead of being
   skipped entirely.
2. **`model/text_commit/` does not exist on `main`.** This branch is 152 commits
   ahead of `main` (branch point `4118e9f`). No user is exposed to any of this;
   the duplicate-painter gate is incomplete *new* protection, not a broken
   shipping one.

## F1 and F3 are one defect, and it is the ceiling

The obvious fix for F1 — "treat a **non-positive** advance as unprovable" — does
not work, and the review's own evidence says so. The F1 verifier swept the width:

> `W=0 -> ADMIT in all 8 combinations. W=1 -> ADMIT in all 8 combinations.`
> `W=1 (advance 0.024pt at 12pt) admits identically at ±1.0/±2.0. A fix that
> special-cases a zero advance would not close it.`

`/W` = 1 is a *positive* advance of 0.024pt; the quad is 0.024 wide, `overlap_x`
is 0.024, which fails `> 0.05` → disjoint → admit. And no threshold on the
advance *value* fixes it either: at `/W` = 100 the quad is 2.4pt against ~24pt of
real ink. Zero is just the visible end of a continuum.

So F1 and F3 are the same defect wearing two identities
(`same_font is None` vs `True`): **the exact quad treats declared advance as an
upper bound on ink, and a declared width is never that.** Requiring metric
equality does not help F1's `distinct_cidtogid=False` case, where the metrics
*are* the font's own honest declaration.

That is precisely the pre-existing ceiling the critic named — "declared advance
is not an upper bound on ink" (italic/swash overhang; the 0.6-em core ignoring
ascenders/descenders) — arriving through a route this round widened. Closing
F1/F3 means one of:

| | Approach | Ceiling rule |
| --- | --- | --- |
| **(a)** | Refuse to use declared advance as an ink bound at all → the exact-extent path collapses entirely into `_painter_reach` | pure narrowing, **not** triggered |
| **(b)** | Threshold the advance against glyph count × font size | new heuristic constant → **triggered** |
| **(c)** | Bound ink from FontBBox / glyph envelopes | the genuine new dimension → **triggered** |

## Routing against the controlling document's Stage C

- Not `complete`: five reproduced false admits in the gate under review.
- Whether this is the **heuristic ceiling** turns entirely on whether option (a)
  is affordable. It is not a design argument; it is one measurement.

**The decisive probe:** re-run the sealed census with `_painter_advance` stubbed
to `None` — exactly the collapse option (a) describes, and exactly the control
the verifiers already used — and read the new `all_gates_pass` against 6,624.
`_painter_reach` is a page-diagonal bound, so a reach-only gate refuses every
same-bytes twin not provably off-page.

- Small drop → option (a) is the fix; "narrow and stop" below is authorized.
- Large drop → the exact-extent path is load-bearing, keeping it needs (b) or
  (c), and **that is the ceiling**: the document's pre-committed route to a
  P4-B2 exact-geometry spike fires.

**Probe result (measured 2026-09-01, both sealed documents, `--no-e2e`):**

| Bucket | Baseline (tip) | Reach-only | Δ |
| --- | --- | --- | --- |
| `all_gates_pass` | 6,624 | 4,478 | **−2,146 (−32.4%)** |
| `duplicate_painter_only` | 187 | 2,333 | +2,146 |
| `tj_array_only` | 112 | 112 | 0 |
| `hscale_only` | 0 | 0 | 0 |

The baseline run independently reproduced the sealed 6811/6624/187/112/0 at the
round-4 tip. The reach-only delta is exact and fully attributed: every lost row
moves to `duplicate_painter_only` and nothing else shifts.

**Verdict: option (a) is not affordable — the ceiling fires.** 2,146 of the
6,624 current admissions (32.4%) rest on the exact-extent quad, whose proof the
review showed unsound (declared advance is not an ink bound). Closing F1/F3
while keeping those admissions requires (b) or (c) — another painter/text-state
approximation — which is exactly the pre-committed trigger. Per the controlling
document: no round 5 of heuristics, no merge until the architectural
replacement is decided, next work is the P4-B2 exact-painter-geometry
read-only value spike.

This also re-scopes P4-B2's value upward: its target is no longer only the
187 + 112 rejected rows — it is also **re-proving the 2,146 currently-admitted
rows whose safety argument is unsound**. Exact painted quads would replace the
declared-advance assumption for a third of all admissions, not just chase the
tail.

F2, F4 and F5 are local either way (delete the `simple_round_trip` leg; fall to
reach on negative per-glyph steps) and do not depend on this number.

## Recommended scope — RESOLVED by the probe: ceiling declared, stop and spike

The probe answered the condition: option (a) costs 32.4% of all admissions, so
"narrow and stop" as a *complete* fix is off the table. F1/F3 cannot be closed
on this branch without a new approximation. The pre-committed route applies:

- **P4-B1 is at its heuristic ceiling.** Declared here, per the controlling
  document's rule.
- **No round 5.** No new font classification, geometry envelope, or replay
  model on this branch.
- **No merge** until the architectural replacement is decided — the branch
  carries five reproduced false admits in a fail-closed gate, and `main` has
  none of this code, so waiting costs nothing.
- **Next work: the P4-B2 exact-painter-geometry read-only value spike**, now
  with the larger mandate above (re-prove 2,146 + reclassify 187 + 112).

The items below were drafted as the conditional round-5 scope. They remain
valid as an *optional interim hardening pass* (pure removals, no new semantic
dimension — the kind of local correction the controlling document permits) if
the user wants the branch's known false-admit routes closed while P4-B2 runs.
They narrow admission (F2/F4/F5 fallers drop to reach) but do NOT close F1/F3,
whose fix is the spike itself:

1. ~~F1/F3 — per the probe: option (a) if affordable, else stop and spike.~~
   Resolved: not affordable; the spike is the fix.
2. F2 — delete the `simple_round_trip` leg (this also subsumes F9).
3. F4/F5 — close **conservatively**: fall back to reach whenever any per-glyph
   step is negative. Do *not* build the min/max-prefix extent model here — that
   is the P4-B2 exact-geometry investment and must be evaluated on value, not
   bolted onto a branch whose own deliverable is worth 0 rows.
4. F4 **target side** — there is no reach fallback for the target; the target
   quad *is* the reference geometry. A negative target `Tc`/`Tw` must fail the
   plan closed at `plan.py:415`. Easy to lose if not stated separately.
5. F6/F7 — census parity; F8/F10 — replace the vacuous tests with
   revert-sensitive ones asserting `result.detail`.

Steps 2–5 only *remove* approximations, so the ceiling rule stays armed.

## Standing, unchanged

`hscale_only = 0` on the sealed corpus. Positive finite `Tz` support exists and
is correct; its incremental admission on this corpus is zero. 877 remains a
source-bindable-stage figure only. Augmentation stays Safety NO-GO. No font
mutation, no `store_shrink(100)`.

## User rulings (2026-09-02)

1. **No interim hardening.** P4-B1 freezes at `49c98ee`. Items 2–5 above are
   not applied on this branch; F2/F4/F5 become P4-B2 negative controls and
   production acceptance requirements for whatever replaces the gate.
2. **P4-B2 spike authorized** as a read-only value spike with the enlarged
   mandate: decide whether exact painter-event geometry can safely re-prove
   the 2,146 exact-quad-dependent admissions and reclassify the 187
   `duplicate_painter_only` rows. Conservative reach stays as the fallback.
   Declared advance is permanently disallowed as an ink bound (widths, `/W`,
   `/DW`, `Tc`, `Tw`, kerns move the cursor only; outlines bound ink).
   Per-glyph quads; ambiguous joins are never "exact"; census aggregate-only;
   no font mutation; no `store_shrink(100)`; no merge until the architectural
   replacement is decided.
