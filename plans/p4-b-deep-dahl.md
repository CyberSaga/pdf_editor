# P4-B — Fix A → Fix B → P4-B1 positive-hscale admission

**Base:** `task14/type0-augmentation-census@03b08db` (pushed; contains `c276018`)
**Scope (user-confirmed):** all three items, in order, as three stacked branches.

## Context

P4-A closed with **Safety NO-GO** for Type0 augmentation (no safe same-handle
cache refresh; `store_shrink(100)` is process-global with no worker-exclusion
proof) and **Priority GO: hscale** — 877 newly bindable doc_0 shows (Unit A),
127.00 Unit B (`plans/task14-type0-augmentation-census.md` §7). The next
production work is admitting `Tz != 100` in the planner — but not by deleting
the gate: Tz participates implicitly (as an assumed 100) in the Tier 0
equal-advance proof, the fallback bbox, the Tier 1 growth bbox, and the TJ
kern compensation. Two independent correctness fixes recorded in task14 §2
land first, because P4-B1's Tier 1 red matrix would otherwise hit their false
rejects.

## Branch strategy

Stacked, one PR each, merged in order (supersedes task14 §2's stale
"independent branches based on c276018" — record that supersession in Fix A's
commit by updating `plans/task14-type0-augmentation-census.md:5`):

1. `task15/fix-a-v0c-operator-proof` — cut from `03b08db`
2. `task15/fix-b-growth-background-box` — cut from Fix A tip
3. `task15/p4-b1-hscale-admission` — cut from Fix B tip

Both fixes edit `verify.py` (stacking avoids a guaranteed conflict), and the
P4-B1 census rerun must run on a tree containing all three.

New plan file per CLAUDE.md §8: `plans/task15-verify-fixes-and-hscale-admission.md`
(goal, three item sections, decisions log); `git mv` to `plans/archive/` on
completion.

## Advance-unit contract (governs Item 3; referenced by Item 2)

PDF 32000-1 §9.4.4: tx = ((w0 − Tj/1000)·Tfs + Tc + Tw)·Th, Th = hscale/100
(Th multiplies the whole bracket, Tc/Tw included).

- `raw_advance` — text-space, Tz-free: today's `_advance` (plan.py:167-181)
  and `advance_points` (cid_fonts.py:818-825). **They stay raw; no signature
  change** (`test_text_commit_textwriter_zorder.py:338-345` calls `_advance`
  directly). `PreparedEdit.source_advance`/`replacement_advance` and the
  `%.6f` token components (plan.py:251-252) stay RAW → Th==100 token
  stability is automatic.
- `effective_displacement = raw_advance · Th` — what geometry and successor
  origins see.
- **Kern algebra (resolved — contract B, raw in, Th cancels):** a `[N] TJ`
  element displaces `−N/1000·Tfs·Th`; successor preservation gives
  `raw_repl − N/1000·Tfs = raw_src` — Th cancels because the kern executes
  under the same Tz as the show. `kern_for_displacement` (patch.py:252-273)
  keeps its raw-delta input and its denominator becomes
  `show.font_size * 100.0` (bit-identical at Th==100). Both kern call sites
  (plan.py:758-760, patch.py:319) stay unchanged and agree by construction.
  Rewrite the docstrings at patch.py:252-273 and the stale warning at
  :264-267 (raw in; Th cancels; valid for finite Th>0; planner gate enforces
  positivity; the ValueError guards are defense-in-depth). Extend guards at
  patch.py:235-238 and :269-272 to `hscale <= 0.0 or not isfinite`.
- **Th consumer sites (all of them):**
  1. plan.py:570-580 fallback quad → x1 = `old_advance * th`
  2. plan.py:747-752 Tier 1 growth → `max(0.0, repl − src) * th` before
     `_grown_verify_bbox` (its `norm` at :694 is Tm×CTM-only — correct as-is;
     docstring notes the input is now effective)
  3. patch.py:273 denominator (see above)
  4. Fix B's `background_bbox_page` quad → baseline extent
     `classified.source_advance * th` (added in Item 3)
- **Float identity rule:** compute `th = show.hscale / 100.0` FIRST, then
  multiply (`100.0/100.0 == 1.0` exact; `x*1.0` bit-exact) → Th==100
  bytes/tokens/bboxes provably unchanged. Never `x * hscale / 100.0`.
- **Tier 0 equal-advance gate (plan.py:615-623) unchanged** — raw-vs-raw is
  scale-invariant and sidesteps the non-scaling tolerance floors
  (1e-9/1e-4 at plan.py:497/543/545). One-line comment at the gate.

---

## Item 1 — Fix A: V0c target-local operator proof

Branch `task15/fix-a-v0c-operator-proof`. Defect: V0c's substring test
`original_text in clip_text` (verify.py:488-494) falsely rejects a CJK
single-char edit whose original char legitimately appears in a neighboring
show inside the halo.

**Design:**
- Substring check #1 (verify.py:483-487, replacement extractable) **stays
  verbatim** — it is the extraction/ToUnicode consistency gate the operator
  proof cannot cover (pinned by test_text_commit_interpretation_reuse.py:317).
- Substring check #2 (:488-494 "source text still present") is **replaced**
  by the operator proof (keeping it would keep the false reject; V0a proves
  all other bytes unchanged, `_span_origins` proves neighbors unmoved, V0d
  proves raster identity outside the halo — the operator proof closes the
  one remaining byte range).
- `_span_origins` comparison untouched (PITFALLS:2134).
- **Operator proof** (new helper in verify.py, run in the V0c block after
  V0b): replay ONLY the patched stream from the `post_streams` already read
  for V0a (verify.py:433) via `replay_page_streams([(stream_xref,
  bytes)], max_decoded_bytes=DEFAULT_MAX_REPLAY_BYTES)` — sound because show
  recording is stream-local (operands reset per stream, replay.py:481) and
  only lexical fields are consulted; rotation-independent; within the
  per-keystroke budget. Refusal/malformed → VERIFICATION_FAILED (fail closed).
  Locate the target show by exact splice identity — Tier 0: `Tj` with
  `string_start == replacement.start` and `string_end == start +
  len(replacement_bytes)`; Tier 1: `TJ` with `op_start/op_end` equal to the
  splice range and `array_item_count == 1` (the kern number is skipped by
  the TJ decode by construction). Zero or >1 matches → fail. Then require
  `show.decoded_bytes ==` expected operand derived from
  `replacement.replacement_bytes` alone — Tier 0 via
  `decode_literal_string`/`decode_hex_string` (pdf_lexer.py:206/272);
  Tier 1 by replaying the replacement bytes in isolation (recording does not
  require BT) and taking that one show's `decoded_bytes`. Byte-level equality
  suffices: plan already proved `replacement_encoded ↔ replacement_text`
  (plan.py:462-516), so text equality follows transitively; this also keeps
  test_text_commit_apply_compress.py:816-829's failure ordering (extraction
  gate still fires on a tampered `replacement_text`).
- Verified-property tuple (verify.py:570-578) gains `"target_operator_reproven"`
  (append at end; check exact-tuple pins first).

**Red tests** (new `test_scripts/test_text_commit_v0c_operator_proof.py`,
shown failing before any verify.py edit):
1. CJK single-char Tier 0 edit, equal-width CID replacement, original char
   present in a neighbor show inside the halo → red today with "source text
   still present"; green after; neighbor bytes + origins unchanged.
2. Same shape, Tier 1 (wider replacement, blank growth) — proves TJ branch
   + kern skip.
3. Tampered `StreamReplacement.replacement_bytes = b"(a)(b)"` via
   `dataclasses.replace` → new detail (operand decodes wrong); Tier 1
   sibling `[(x)(y) 0] TJ` → `array_item_count == 2` → reject.
4. Monkeypatched `replay_page_streams` refusal → VERIFICATION_FAILED.
5. Latin regression sentinels: apply_compress, tier1_slice1,
   interpretation_reuse suites green; update stale comment at
   test_text_commit_apply_compress.py:817-821.

**Edit sites:** verify.py:470-504 + new helper; imports from replay/pdf_lexer;
module docstring; verified-property tuple. plan.py untouched.

**Verification:**
```
.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_v0c_operator_proof.py -q   (red → green)
.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_apply_compress.py test_scripts/test_text_commit_interpretation_reuse.py test_scripts/test_text_commit_tier1_slice1.py test_scripts/test_text_commit_cid_hex_tj.py -q
.venv\Scripts\python.exe -m pytest ; ruff check . ; .venv\Scripts\python.exe -m mypy model/ utils/ ; git diff --check
```

---

## Item 2 — Fix B: growth-background metric box

Branch `task15/fix-b-growth-background-box` (stacked). Defect
(TODOS.md:927-938, PITFALLS:2529-2534): under the app's own
`set_small_glyph_heights(True)`, caller-supplied extraction bboxes are
fontsize-tall; dense-CJK ink ≥50% of the box → `_target_background_rgb`
finds no strict majority → Tier 1 growth fail-closed rejects on BOTH app
paths, while `target_bbox=None` callers pass via the flag-immune 1.35-em
metric quad.

**Design — sampling-box-only, threaded from the planner** (do NOT normalize
`target_bbox_page` itself: it is also V0c's span-origin clip, V0d's Tier-0
halo, and the growth-zone edge):
- `_build_tier1` computes a flag-immune **metric-quad background box** the
  same way the fallback bbox is built:
  `map_text_quad_to_visual(page, show.tm, show.ctm,
  (0.0, -0.35·size, source_advance, size))` — quad-only (not a union with
  the caller box) so the sampled region is literally identical with the flag
  on and off; rotation-correct by construction.
- New `PreparedEdit` field `background_bbox_page: … | None = None` (set only
  by `_build_tier1`; Tier 0 stays None). **Not folded into the token** — it
  is a pure derivation of token-bound inputs (fingerprint hashes the streams
  that determine the show; `source_advance` is a token component); comment
  at plan.py:210-216 saying so.
- verify: `verify_tier1_commit` (:1239-1245) threads
  `background_bbox=prepared.background_bbox_page` →
  `_growth_probe_failure` → used ONLY for the `_target_background_rgb` call
  (:1054); `None` falls back to `target_bbox` (hand-built PreparedEdits and
  direct-call tests keep today's behavior). `prove_growth_region_blank`
  gains the same optional keyword. Reference points, growth-zone rect, probe
  regions, glyph count all stay on target/verify bbox.
- Ink-visibility rule survives (target ink is inside the quad; 100% majority
  ⇒ reject stays — PITFALLS 2186-2192). Correct `_target_background_rgb`'s
  docstring ("font-metric box" now matches the sampled box).
- Tier-1-only by construction (`has_ink_growth` gates the proof).

**Red tests** (new `test_scripts/test_text_commit_growth_background_box.py`;
every test snapshots/restores `set_small_glyph_heights` via try/finally):
1. Dense-CJK Tier 1, flag ON, caller extraction bbox (as the app passes it)
   → red today with `GROWTH_REGION_NOT_BLANK` "no majority background
   colour"; accepts after.
2. Same fixture, flag OFF → identical verdict.
3. Vector / image / shading ink in the growth zone, flag ON → still rejected.
4. Ink at the exact growth boundary → still rejected (raster gate).
5. White-on-white target → still rejected (100%-majority ink-visibility pin).
6. Rotation 0/90/180/270 parametrization over the accept case.
7. Hand-built PreparedEdit (`background_bbox_page=None`) reproduces today's
   sampling.

**Edit sites:** plan.py:74-125 (field) + :737-804 (compute);
verify.py:827-853 (docstring), :1029-1091, :1094-1121, :1215-1266.

**Verification:** red→green on the new file; then tier1_slice1,
trm_admission, apply_compress, candidate_identity suites; full suite, ruff,
mypy, diff check. Two-file CI-shape check per PITFALLS:
`pytest test_scripts/test_1pdf_horizontal.py test_scripts/test_text_commit_growth_background_box.py -q`.

---

## Item 3 — P4-B1: positive-hscale admission

Branch `task15/p4-b1-hscale-admission` (stacked). Contract per §Advance-unit.

**Gate change (plan.py:401-406)** — split, order preserved:
```python
if show.render_mode != 0 or show.rise != 0.0:
    return PlanRejection(RejectReason.UNSUPPORTED_TEXT_STATE,
        f"render_mode={show.render_mode} rise={show.rise}")
if not math.isfinite(show.hscale) or show.hscale <= 0.0:
    return PlanRejection(RejectReason.UNSUPPORTED_TEXT_STATE,
        f"hscale={show.hscale} is not a positive finite horizontal scale")
```
Pinned substrings "render_mode=2"/"rise=3.0" survive. Positivity+finiteness
is a hard gate: (a) `0 Tz` replays cleanly (replay.py:617-622 stores any
float; `float("1e999")` → inf passes `_numbers`) and reaches patch.py's
ValueError uncaught through `prepare_plan`; (b) negative Th mirrors text
invisibly to `shape_reject_reason` (Tm×CTM det only — hscale is not in the
TRM) and verify re-derives growth direction from bbox geometry alone
(verify.py:894-900) — **verify cannot catch an hscale sign error; the
planner gate is the only defense** (say so in the gate comment).

**Th consumer edits:** sites 1, 2, 4 with the `th = hscale/100.0`-first rule;
site 3 per contract B. **No new PreparedEdit field, no token change**
(fingerprint hashes every content-stream byte, so a Tz operand difference
already rotates the fingerprint → token; recorded tradeoff: folding hscale
in would rotate all tokens for zero discriminating power).
`test_text_commit_candidate_identity.py` untouched.

**Mirror surface (same branch — PITFALLS 2385 census-drift rule):** all gate
mirrors adopt the NEW vector (positive finite admitted; <=0/non-finite
refused):
- scripts/measure_tier_funnel.py:322; scripts/audit_tier_coverage.py:51-58.
- scripts/measure_type0_funnel.py:311-312 (`state:hscale` only for
  non-positive/non-finite) and :369 `hscale_ok` (bucket keys at :416-424
  keep their names; positive-hscale shows re-attribute into
  `all_gates_pass`/`tj_array_only`); :295-301 hscale cross-tab stays as a
  descriptive Tz distribution (note in plan file).
- test_glyph_overlap_census.py:110-125/358-367 (80 Tz → `all_gates_pass`;
  add a 0/−80 Tz fixture pinning `hscale_only`/`state:hscale`);
  test_type0_vocabulary_counterfactual.py:347/361/368 (recompute);
  test_audit_same_face.py:440 (verify unchanged, don't assume).
- docs/benchmark-reports/.../bench_gui_tier1.py:256 **frozen** (dated report
  artifact; divergence noted in plan file).

**Red matrix:**
- Convert test_text_commit_structural_gates.py:226-241 to the admission
  contract: 80 Tz + equal-advance replacement → `PreparedEdit`; 0 Tz, −80 Tz,
  and an overflow-to-inf Tz operand → refused with the new detail substring;
  `_NOMINAL["hscale"]=100.0` (:62) stays as isolation reference; module
  docstring updated.
- New `test_scripts/test_text_commit_hscale_admission.py`:
  - Tier 0 @ 80/120 Tz: prepare/apply/save/reopen; `b"80 Tz"` still in the
    stream; next reliably-positioned show origin unchanged.
  - Fallback bbox: `target_bbox=None` → baseline extent raw·0.8 / raw·1.2;
    caller bbox passed through verbatim (no double scaling).
  - Tier 1 @ 80/120 Tz × wider/narrower: successor origin identical after
    TJ compensation; kern pinned to `−1000·(src−repl)/Tfs` (hscale-free).
  - Growth boundary: blank exactly `raw_growth·Th` → accept; ε less → reject.
  - /Rotate 90 @ 80 Tz with growth: correct edge, Th-scaled length.
  - Save/reopen re-verification (origins, raster halo, non-target pixels).
  - Fail-closed: 0/negative/non-finite Tz; `2 Tr`, `3 Ts`, shared stream,
    whole-array TJ, quote ops keep their reasons on an 80 Tz fixture.
  - Mutation sensitivity (run during dev, recorded in plan file): drop `·th`
    at site 1 → fallback test red; site 2 → boundary test red; revert
    patch.py:273 → successor-origin test red.
- test_text_commit_trm_admission.py:849-859 → rotated×hscale admission case
  (50 Tz on the ROT90 fixture). test_text_commit_replay.py:99-106 unaffected.

**Verification:**
```
.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_hscale_admission.py test_scripts/test_text_commit_structural_gates.py test_scripts/test_text_commit_trm_admission.py test_scripts/test_text_commit_tier1_slice1.py test_scripts/test_glyph_overlap_census.py test_scripts/test_type0_vocabulary_counterfactual.py test_scripts/test_audit_same_face.py -q
.venv\Scripts\python.exe -m pytest ; ruff check . ; .venv\Scripts\python.exe -m mypy model/ utils/ ; git diff --check
```
Census rerun (private gitignored corpus; numbers never enter the repo;
whole-report privacy scan before quoting aggregates): re-attribute the 877
`hscale_only` doc_0 shows to their true downstream fate — do NOT assume 877
successes; confirm unrelated funnel buckets, page eligibility, and
malformed/shared/unreadable counters do not drift.

---

## Docs per CLAUDE.md §6 (each item's completion commit)

- PITFALLS.md (+ regen index): Fix A — halo substring not target-local /
  stream-local replay soundness; Fix B — background-majority box must be
  flag-immune; P4-B1 — Th cancels in the kern (raw in); zero/negative/
  non-finite Tz invisible to every TRM gate and to verify; th-first float
  identity rule.
- ARCHITECTURE.md §10.1: V0c operator proof, growth background-box source,
  plan/patch advance contract.
- TODOS.md: close the :927-938 admission gap under Fix B (TOOLS flag hygiene
  stays open); update task14 P4 records.
- Docs still record: augmentation Safety = NO-GO; no `store_shrink(100)`;
  no font-mutation path; Priority = hscale.

## Completion criteria

1. Th==100 plan tokens/bytes/bboxes byte-identical (guaranteed by the
   th-first rule + raw token components; no token-preimage change).
2. Positive-Th Tier 0/1 synthetic matrix green incl. save/reopen; downstream
   origins fixed.
3. One effective-displacement contract across fallback bbox, growth bbox,
   halo, page-boundary gates.
4. Census re-attribution recorded honestly; no unrelated bucket drift.
5. Focused + full suite, ruff, mypy, `git diff --check`, privacy scan —
   per item, before each merge.

## Resolved design decisions

1. Fix A replaces substring check #2 outright (check #1 stays) — keeping #2
   preserves the false reject; the operator proof is strictly stronger for
   what #2 tried to prove.
2. Fix A compares operand bytes, not decoded text — transitively equal via
   plan's proven encoders; no new simple-font decode API.
3. Fix B computes the metric box plan-side (`background_bbox_page`),
   quad-only — a verify-side halo ring would break the ink-visibility rule.
4. No token-preimage changes anywhere (fingerprint already determines Tz and
   the background box).
5. Kern contract B (raw in, Th cancels) — one edit site, bit-identical at
   Th==100, both kern computations agree by construction.
6. bench_gui_tier1.py frozen.
