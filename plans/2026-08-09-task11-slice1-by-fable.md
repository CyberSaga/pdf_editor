# Task 11 Slice 1 — Tier 1 transplant+kern commit engine (by-fable independent build)

**Status:** in progress (2026-08-09). Branch `worktree-by-fable`, pinned at `1e8b02f`
(pre-Slice-1 state; all Pre-Task-11 prerequisites D1/D5/audit/measurement/baseline landed).

**Independence constraint:** this is a from-scratch build of Slice 1 in this worktree.
Do NOT read other branches' implementations (`git show`/`git log`/`git diff` against any
ref other than the current HEAD history is forbidden for this task). Work only from the
checked-out tree, the governing plan (`plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`
lines 798–963), and `TODOS.md` lines 443–459.

## Goal

Where Tier 0 today refuses with `ADVANCE_MISMATCH`, build and verify a Tier 1 candidate:
replace the source `(src) Tj` operator — at its exact byte range, whole operator — with
`[(new) K] TJ`, same font resource, same encoding, where the kern number `K` absorbs the
advance delta so **every following show provably keeps its origin**. Honest Tier 1 outcome
(never `LOSSLESS_STREAM_PATCH`), flag-off by default (`TEXT_COMMIT_MAX_TIER=1` opt-in).

## Scope

**In:** single-`Tj` targets (literal or hex operand), same font resource/encoding as source,
whole-operator transplant splice, kern compensation, growth/shrink handling with honest
refusals, scratch-first prepare → live commit → verify → revert pipeline, preview parity
(token equality), undo/redo byte identity, persistence (save/reopen), shared-content-stream
guard, operator guard (`'`/`"` refused in the builders), the composite Red test.

**Out (explicitly deferred, keep existing refusals):** deletion (`EMPTY_REPLACEMENT` stays),
multiline, style overrides (font/size/color changes), geometry overrides (`new_rect`),
TJ-array targets (pivot condition met: 0.59% binding survival — stays refused), `'`/`"`
operators (refused with tests), Identity-H, layout work (`layout.py`, wrapping, alignment,
overflow UI — the later slice), D4 OCG tri-state (see decision D8), view-layer warning
banners (plan Step 4 belongs to the layout slice; the honest machine-readable surface is
`CommitOutcome`).

## Pre-decisions (the designer refines mechanics; these stand unless refuted with evidence)

- **D1 — Single-pass planner.** Refactor `plan.py` internals into one classification pass
  parameterized by `max_tier: int` (0|1). `prepare_tier0_plan(...)` remains as a thin
  wrapper (`max_tier=0`) so every existing test and call site is untouched. At the
  equal-advance gate: `max_tier=0` → reject `ADVANCE_MISMATCH` exactly as today;
  `max_tier=1` → continue to Tier 1 assembly. No duplicate replay/bind per call.
- **D2 — All other Tier 0 gates retained verbatim** for Tier 1 admission: operator
  `Tj` (literal|hex), render_mode 0, rise 0, hscale 100, mc_depth 0, uniform-positive-scale
  TRM, same font capability path, encoding round-trip against source bytes, `/Widths`
  coverage for both strings. The ONLY relaxed gate is equal-advance.
- **D3 — Kern math** reuses the proven formula (`build_advance_preserving_erase`):
  `K = -100000·(old_advance − new_advance)/(font_size·hscale)`, where advances include
  the Tc/Tw contributions of each respective string. Replacement bytes:
  `[(escaped-new-literal) K] TJ` spliced at `show.op_start:show.op_end` via
  `build_transplant_replacement`. Deterministic formatting (fixed precision) — the
  content-derived token must be stable.
- **D4 — Declared affected region** (page space) = union(source `target_bbox`, replacement
  extent), computed with the same trm-scale × page-matrix-hypot scale logic `plan.py`
  already uses. Shrink ⇒ declared == source bbox. Growth ⇒ growth zone = declared − source
  (the right-side band).
- **D5 — Growth admission = blankness proof** (the plan's option b): compensated growth is
  admitted only when the growth zone is uniform (one flat color) pre-edit, proved by
  clip-render at `_VERIFY_DPI` + `_region_is_uniform`, via ONE shared helper used by both
  the preview path (pre-splice, per generation) and the engine verify paths (scratch and
  live pre-state). Refusal is a new stable `RejectReason`. Growth extending past the page
  boundary is refused. Widening the halo without proof is rejected as a design.
- **D6 — Verification** generalizes `verify_tier0_commit` into a shared core parameterized
  by the declared region (capture excludes and raster halo both use it). Tier 1 verified
  properties: the existing seven (with declared-region semantics) — plus growth evidence —
  and **no `ocg_membership_preserved` claim** (never probed ⇒ never claimed).
- **D7 — Outcome honesty.** `PreparedEdit` gains `tier`, `tier0_fallback_reason`,
  declared-region + kern metadata (frozen-dataclass additive fields with safe defaults).
  Commit outcome: `CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE` (enum name is historical;
  value stands for the tier), `fallback_chain=("tier0:advance_mismatch",)`, a warning
  naming the compensated transplant, `font_outcomes` via `build_tier1_font_outcome`
  (xref-proof, never assumed), `allows_external_reflow=False`.
- **D8 — No OCG probe in the production Tier 1 verifier.** Transplant inherits OCG by byte
  position; V0a byte-identity outside the declared range is the structural proof. Therefore
  D4-tri-state stays an open backlog item, NOT Slice 1 scope — and no OCG property is ever
  claimed (see D6). Rationale: the probe costs two extra whole-doc serializations per
  commit and proves nothing transplant can violate.
- **D9 — Operator guard in the builders.** `build_advance_preserving_erase` and
  `build_transplant_replacement` raise `ValueError` unless `show.operator` is `Tj`
  (`TJ`/`'`/`"` refused — `'` folds an implicit `T*`, `"` splices aw/ac operands whose
  `Tw`/`Tc` persist). Red tests for both builders × both quote operators.
- **D10 — Shared-content-stream guard in the COMMON path (both tiers).** A content stream
  referenced by more than one page must refuse with a new stable `RejectReason` — splicing
  it would silently edit sibling pages, and V0 checks only look at the edited page. This is
  a latent Tier 0 hole being closed in the same slice, with its own Red test. Detection via
  xref-level `/Contents` scan (no page loads); note the per-keystroke cost and keep it
  cheap.
- **D11 — Preview parity.** Thread `max_tier` through `PreviewSessionInput` (session-stable,
  from `model.text_commit_settings`); `PlanPreviewResult` gains `tier`. The preview renders
  the identical candidate the commit would apply; **parity = content-derived token
  equality**, asserted in the composite test. Preview growth admission runs the same shared
  helper so preview and commit agree on refusals.
- **D12 — Integration seam** (`model/pdf_text_edit.py`): `_attempt_tiered_commit` threads
  `settings.max_tier` into `engine.prepare`; success path uses `outcome.tier` in the debug
  log (today hardcodes `tier=0`); fidelity protection + block rebuild + strict semantics
  unchanged (a Tier 1 commit is a real commit, admitted under strict).

## The composite Red test (the anchor; GPT-5.6-sol correction 2)

One test exercising the whole candidate at once on a synthetic multi-show fixture:
replacement renders; arbitrary replacement advance is compensated; every later show retains
its origin (rawdict origins); persistent text state (Tc/Tw/Tz/TL/Tf/Tr/Ts) unchanged after
the op; exact source range + stream digest checked; preview token == commit-prepare token;
undo restores byte-identical streams; forced verification failure reverts everything.

## Files (extends the governing plan's incomplete list — GPT-5.6-sol correction 3)

- Modify: `model/text_commit/plan.py` (single-pass refactor + tier1 assembly)
- Modify: `model/text_commit/patch.py` (operator guards; tier1 op-bytes builder)
- Modify: `model/text_commit/verify.py` (shared verify core; growth helper; tier1 wrapper)
- Modify: `model/text_commit/engine.py` (max_tier; tier dispatch; tier1 outcome)
- Modify: `model/text_commit/dto.py` (new RejectReasons; PlanPreviewResult tier — if moved)
- Modify: `model/text_commit/preview.py` (max_tier; tier in result; growth admission)
- Modify: `model/pdf_text_edit.py` (max_tier threading; log fix)
- Modify: `controller/pdf_controller.py` + `controller/text_commit_coordinator.py`
  (session max_tier pass-through; no new Qt surface)
- Create: `test_scripts/test_text_commit_tier1_transplant.py` (Red suite incl. composite)
- Possibly touch: `test_scripts/test_text_commit_settings.py` (max_tier=1 plumbing)
- NOT touched: `view/text_editing.py`, `model/text_commit/layout.py` (layout slice)

## Open questions for the designer

1. Clip-path blindness: replay tracks `gs_depth`, not clip rects — clipped-away growth ink
   would pass V0-style checks. Tier 0 shares this V0c blindness. Detect via post-raster
   growth-zone non-uniformity (spaces-only tails break a strict assert), or document as a
   known shared limitation? Decide with evidence.
2. Exact refusal-code names for growth/shared-stream refusals (stable telemetry contracts).
3. Kern number formatting precision (token stability vs. sub-0.1pt exactness — spike proved
   0.1pt; pick and justify).
4. Whether the growth-zone uniformity check also needs the live-commit pre-state re-check
   (fingerprint gate may already make scratch≡live for streams — but annotations render
   into the pre-state pixmap and are NOT fingerprint-covered; decide with evidence).
5. Where `PlanPreviewResult.tier` lives without breaking the coordinator's DTO imports
   (importlinter `view-no-model` allowlist is NOT to grow).

## Verification gates (Definition of Done)

- Red log shown before implementation (mandatory §5.1).
- Full suite green via `../../../.venv/Scripts/python.exe -m pytest` (venv, NOT system
  python) — baseline 2026-08-09: 2135 passed / 28 skipped / 5 xfailed.
- `ruff check .` zero new violations; `mypy model/ utils/` clean.
- Mutation checks on the new gates (operator guard, growth admission, shared-stream guard,
  kern sign/magnitude) — each new gate's test must fail when its gate is deleted.
- Docs: PITFALLS.md (+ index regen), ARCHITECTURE.md, TODOS.md, this plan updated.

## Adjudicated design (2026-08-09, binding for implementation)

Designer (opus-4-6) + adversarial refuter (opus-4-6) both ran; refuter verdict was
*revise* with two confirmed defects. Full design JSON + refutation:
`C:\Users\jiang\AppData\Local\Temp\claude\C--Users-jiang-Documents-python-programs-pdf-editor\f3c3e610-6d46-4aec-9073-f285ab54cc4a\tasks\wb1jq1exo.output`
(read it; it is the concrete spec — signatures, byte formats, gate placement, step order).
The following adjudications override or refine that design where they conflict:

1. **Growth geometry (fixes refuter defect 1 — NameError/scope + shrink misfire):**
   hoist `scale = trm_scale * hypot(page_matrix.a, page_matrix.b)` out of the
   `if target_bbox is None:` block. Growth predicate is the scalar
   `new_advance > old_advance` — never a bbox tuple comparison. New `PreparedEdit`
   field `growth_bbox_page: tuple[float,float,float,float] | None = None` (None = no
   growth), computed FROM the in-force `target_bbox_page`:
   `(tb.x1, tb.y0, tb.x1 + (new_advance-old_advance)*scale, tb.y1)`. Declared region
   for halo/extraction = `target_bbox_page ∪ growth_bbox_page` (equals target bbox when
   no growth). All four consumers (planner, engine.prepare, engine.commit,
   preview.render) read `growth_bbox_page` — no local recomputation anywhere.
2. **font_size gate (fixes refuter defect 2):** in the common path alongside the
   existing text-state gate: `font_size <= 0` → `PlanRejection(UNSUPPORTED_TEXT_STATE,
   detail containing "font_size")`. Distinct detail substring per the PITFALLS rule on
   shared reasons; mutation-pinned by its own Red test.
3. **Kern formula:** keep `K = -100000.0*(old_advance-new_advance)/(font_size*hscale)`
   with a comment at the computation site stating the hscale==100 precondition: the
   `_advance` values are hscale-UNSCALED, so this formula is only correct because the
   hscale gate holds; relaxing that gate requires switching to `-1000*Δ/font_size` on
   hscale-scaled advances. `.6f` formatting; `-0.0` normalized to `0.0` before format.
4. **Growth admission helper (replaces both agents' proposals):**
   `growth_zone_is_blank(page: fitz.Page, growth_bbox) -> bool` in verify.py —
   clip-renders ONLY the growth zone (`page.get_pixmap(dpi=_VERIFY_DPI,
   clip=growth_bbox)`) and requires whole-pixmap uniformity with 2px inward erosion
   (skip erosion when the zone is ≤4px, mirroring `_region_is_uniform` policy). Called
   pre-patch on the scratch page (engine.prepare), the live page (engine.commit,
   before capture_page_state — annotation appearances render into pixmaps but are not
   fingerprint-covered, so the live re-check is load-bearing), and the preview scratch
   (renderer, before splice). One function, three call sites, zero full-page renders
   added. Refusal: `GROWTH_EXCEEDS_BLANK_REGION` (prepare/preview: PlanRejection;
   commit: FAILED outcome, no revert needed pre-apply).
5. **Shared-stream guard:** as designed (xref-level `/Contents` scan in inspect.py,
   common path after binding, before the advance gate; both tiers). Its Red test MUST
   use an advance-MATCHING replacement so deleting the guard yields a Tier 0
   PreparedEdit — otherwise ADVANCE_MISMATCH masks the deletion.
6. **Fixture constraints (refuter test gaps, binding):** the origins test builds three
   bare `(..) Tj` shows inside one BT/ET with NO positioning operators between them,
   and asserts that fixture property itself; the page-boundary test keeps its on-page
   growth zone blank on a /Rotate 0 page so only the boundary gate can fire.
7. **Close-out additions:** re-run `scripts/benchmark_text_commit_baseline.py` after
   implementation (TODOS:437 requirement; results stay machine-local). PITFALLS
   entries: V0c clip-path blindness (shared limitation), V0c widened-clip false-reject
   under growth (safe direction), narrow-growth-zone anti-aliasing false positives,
   vertical ink (ascender/descender) exposure at Tier 1.
8. Everything else in the designer's output stands as written: prepare_plan/
   prepare_tier0_plan wrapper shape, DTO additions (4 new RejectReasons; PreparedEdit
   tier/tier0_fallback_reason/kern_value/old_advance/new_advance;
   PreviewSessionInput.max_tier; PlanPreviewResult.tier), operator guards in both
   builders (ValueError, message contains "refused"), verify refactor
   (_verify_commit core + tier wrappers; span-origin exclusion ALWAYS uses source
   target_bbox_page; halo/extraction use the declared region), engine dispatch +
   honest Tier 1 outcome (fallback_chain=("tier0:advance_mismatch",),
   warnings=("compensated_transplant_kern",), font outcome via
   build_tier1_font_outcome), pdf_text_edit max_tier threading + tier log fix,
   controller pass-through, and the 17-test Red plan with the composite anchor test.

## Progress log

- 2026-08-09: scouted tree state; wrote this brief; dispatched design workflow
  (opus-4-6 designer → opus-4-6 adversarial refuter, serial).
- 2026-08-09: baseline: ruff clean, mypy clean; full suite 2120 passed / 14 failed —
  all 14 environmental (gitignored corpus PDFs absent from fresh worktree); copied
  test-*.pdf from main checkout; affected suites re-running.
- 2026-08-09: design + refutation complete (2 agents, ~193k tokens); adjudicated above;
  dispatching Red-test workflow (sonnet-5).
- 2026-08-09: Red suite landed — 20 tests, all Red, independently confirmed (0.32s run;
  each failure a missing-feature reason with passing baseline plumbing checks).
- 2026-08-09: implementation complete (sonnet-5, 9 code files + docs). 19/20 green +
  1 formal dispute; full suite 2160 passed / 28 skipped / 5 xfailed; ruff+mypy clean.
  **Post-implementation adjudications (orchestrator):**
  (a) *Entry-point split accepted:* `prepare_tier0_plan` is frozen legacy (no Slice 1
  common gates) rather than a pure delegate — two Red tests demanded the divergence, and
  production paths (engine.prepare, preview.render, shadow classify) all route through
  `prepare_plan`, so the D10 hole IS closed where it matters. Shared `_classify` body,
  `slice1_gates` flag; docstrings mark the frozen contract.
  (b) *Rotation-guard deviation accepted:* PyMuPDF 1.27.1's `transformation_matrix`
  property returns the UNROTATED flip matrix whenever `rotation % 360 != 0` (verified
  against the property's own source, 3 construction paths) — the adjudicated matrix-only
  check would be dead code, so the guard also reads `page.rotation` directly
  (mutation-verified by the implementer).
  (c) *Disputed test fixed by orchestrator:* the fixture-sanity assert at
  test_text_commit_tier1_transplant.py:416 tested that false matrix premise; replaced
  with `rotation % 360 != 0` + a comment recording the quirk. 20/20 now green.
  (d) *Shadow parity switch (orchestrator):* `_classify_tier0_candidate` now classifies
  via `prepare_plan(max_tier=0)` so shadow telemetry sees the same common gates the
  tiered path enforces; one shadow test's monkeypatch target updated to the new symbol
  (containment claim unchanged). Tier-aware shadow telemetry stays Task 12 scope.
  Post-fix verification: tier1+shadow+settings+preview suites 48/48; ruff+mypy clean.
- 2026-08-09: dispatching adversarial review workflow (opus-4-6, read-only).
- 2026-08-09: **review closed — verdict approve** (0 critical / 0 major / 3 minor + 2
  mutation gaps + 2 docs gaps), all findings fixed pre-commit since nothing had shipped:
  (1) helper + verified property renamed `growth_zone_is_uniform` /
  `growth_zone_proven_uniform` (the raster proof is uniformity, not blankness; refusal
  code `GROWTH_EXCEEDS_BLANK_REGION` keeps its value — a refusal names the requirement,
  it cannot overclaim); (2) page-boundary refusal narrowed to the growth edge (x1 only —
  the y-extent belongs to the source and false-rejected near-edge tall text on the
  fallback-bbox path); (3) shared-stream scan cached once per preview session
  (`prepare_plan(shared_stream_xrefs=...)`; keystroke path pays zero); (4) dead `-0.0`
  kern normalization removed (unreachable past the Tier 0 tolerance); plus two
  orchestrator additions the reviewer's checklist exposed: the live-growth-recheck
  divergence test (annotation appearance rewrite is fingerprint-invisible; only the live
  re-check catches it) and command-level Tier 1 undo (`EditTextCommand` now admits
  Tier 1 to byte-exact reversal capture, pinned by fingerprint equality), and one
  reviewer-missed honesty fix: `_rejection_outcome` fallback-chain labels carry the real
  tier (`tier1:...`, was hardcoded `tier0:`).
- 2026-08-09: **mutation battery 8/8 SENSITIVE** (each gate deleted → named test Red →
  restored): live growth re-check, Tier 1 reversal admission, transplant operator guard,
  font_size gate, shared-stream gate, page-boundary gate, rotation clause, kern sign.
  Tier 1 suite 22/22; ruff + mypy clean. Full-suite gate + benchmark re-run pending,
  then commit and archive this plan.
## Closure (2026-08-09)

All Definition of Done items (CLAUDE.md §7) met:
- Full suite: 2143 passed / 28 skipped / 5 xfailed (`--ignore=test_scripts/test_page_reorder.py`,
  a pre-existing documented flake — PITFALLS.md "`pytest … | tail` reports tail's exit
  code", unrelated to this change, GUI drag-and-drop) + that file's own 20/20 passing in
  isolation. 2163 total, zero regressions.
- `ruff check .`: zero violations. `mypy model/ utils/`: zero issues (47 files).
- Red log shown before implementation (20/20 Red, independently confirmed).
- New tests cover every added gate: 22 in `test_text_commit_tier1_transplant.py`
  (20 original + live-growth-recheck divergence + command-level Tier 1 undo).
- `docs/ARCHITECTURE.md` (§10.2), `docs/PITFALLS.md` (+8 entries, index regenerated),
  `TODOS.md` (Task 11 "During" section closed out) all current.
- Perf/memory baseline re-measured post-Slice-1 (TODOS:437):
  `scripts/benchmark_text_commit_baseline.py` → `benchmarks/baseline-2026-08-09-slice1.json`
  (gitignored, machine-local per repo convention).

Shipped flag-off (`TEXT_COMMIT_MAX_TIER=0` default) — no user-visible behavior change.
Remaining Task 11 backlog (TJ-array admission, layout slice, `/Rotate`-aware fallback
bbox shape, D4 OCG tri-state) stays in `TODOS.md` "During Task 11" / "After Task 11".
This plan is committed alongside the implementation, not archived to `plans/archive/`
per CLAUDE.md §8 — Slice 1 is a sub-slice of the still-open governing plan
(`2026-07-18-acrobat-stable-text-commit-engine-v2.md`), which archives when all of
Task 11 + Task 12 close.
