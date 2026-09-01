# P4-B fix round 2 — Pro LOOP_REVIEW findings on `edf40f5`

**Goal:** close the three findings from the ChatGPT-Pro `LOOP_REVIEW` (verdict
CHANGES_REQUIRED) of `task15/p4-b1-hscale-admission` @ `edf40f5`, preserving
the accepted hscale algebra and census attribution.

**Status:** Complete 2026-09-01; all three findings closed and final gates green.

All three findings were independently re-verified against source before any
edit:

- **F1 (P1)** — the "+1.0 pt legitimate neighbor" V0c fixture is a 12pt
  full-width CJK glyph offset by 1pt → ~11pt overlap: it IS the fake-bold
  twin. Production V0c never pins the twin: `_span_origins_from_values`
  (verify.py:255) drops every origin inside target bbox ±1pt; the
  origin-stability assert exists only in the test. The accepted-risk record's
  premises were wrong.
- **F2 (P1)** — `_target_operator_failure` (verify.py:416) replays the FULL
  patched stream with `max_decoded_bytes=None`, and preview.py:350 runs it
  per preview render (measured 3.2–5.9 s at 2.5 MiB).
- **F3 (P2)** — plan.py:414 gates raw `hscale` only; `th = hscale/100`
  (5e-324 → 0.0 underflow) and `advance*th` (finite×finite → inf overflow)
  escape. `kern_for_displacement` never checks displacement/result
  finiteness, and `f"[{kern:.6f}]"` would serialize `inf` into the stream.

## Affected modules

- `model/text_commit/plan.py` — `_classify_common`: derived-Th/effective
  finiteness gate, target-bbox finiteness, duplicate-painter overlap gate.
- `model/text_commit/verify.py` — `_target_operator_failure`: local
  single-token / isolated-op proof, no full-stream replay.
- `model/text_commit/patch.py` — `kern_for_displacement` finiteness.
- `model/text_commit/replay.py` — contract comment (verifier byte proof
  unguarded ≠ verifier lexical replay unguarded).
- `model/text_commit/dto.py` — new `DUPLICATE_SOURCE_PAINTER` reason.
- `scripts/measure_tier_funnel.py`, `scripts/audit_tier_coverage.py`,
  `scripts/measure_type0_funnel.py` — census mirrors follow the admission
  vector (add derived-th leg).
- Tests: `test_text_commit_v0c_operator_proof.py` (rewrite fixture +
  refusal + no-full-replay), new `test_text_commit_duplicate_painter_gate.py`,
  `test_text_commit_hscale_admission.py` (F3 boundary matrix).

## Design decisions

1. **F1 gate lives at plan time** (`_classify_common`, after advances /
   before `_ClassifiedTarget`), not verify time — the plan already holds the
   full bounded `resolved.replay`; a verify-time scan would reintroduce
   exactly the full-stream replay F2 removes. New fail-closed reason code
   `DUPLICATE_SOURCE_PAINTER` (new-gate-new-code rule, Task 10a).
2. **Twin candidate** = another replayed show with identical
   `decoded_bytes` AND identical `font_resource`. Geometry = core quad
   `(0, 0, advance·(fs_c/fs_t)·th_c, 0.6·fs_c)` in each show's own text
   space via `map_text_quad_to_visual`; reject when strict overlap depth
   > 0.05 pt on BOTH axes. Core box (baseline→x-height, no descent/ascent)
   keeps single-spaced repeated lines admissible while any sub-glyph-width
   offset twin (0 / 1.0 / 1.2 pt) overlaps massively. Abutting repeated
   glyphs (`(a) Tj (a) Tj`) share only an edge → depth ≈ 0 → admissible.
3. **Unplaceable twin candidates fail closed** (non-finite/non-positive
   `font_size` or `hscale`, `origin_reliable=False`): same reason code —
   we cannot prove disjointness. Census impact accepted; measurable later.
4. **F2** — Tier 0: `lex_content_stream(replacement_bytes)` must yield
   exactly ONE non-trivia token, kind literal/hex string, spanning
   `[0, len)`, and decode without error (`decode_literal_string(b"(a)(b)")`
   succeeds — the delimiter check alone is NOT single-token proof; the
   lexer is). Tier 1: keep the GUARDED isolated replay of
   `replacement_bytes` only; require 1 show, `TJ`, `array_item_count == 1`,
   `op_start == 0`, `op_end == len(raw)`. No `replay_page_streams` call
   ever sees the full patched stream. V0a's unguarded BYTE proof is
   untouched — replay.py:384 comment updated to say exactly that.
5. **F3** — one chokepoint in `_classify_common`: `th`, `old·th`, `new·th`,
   `(new−old)·th` all finite and `th > 0`, else UNSUPPORTED_TEXT_STATE;
   `target_bbox` (metric or caller-supplied) all-finite, else rejection.
   `kern_for_displacement` raises on non-finite result (covers non-finite
   displacement/font_size). Existing raw-hscale gate stays (detail pinned).
6. Existing `+1.0` neighbor tests are rewritten to DISJOINT neighbors
   (gap 1 pt < 2 pt halo) preserving the original legitimate-neighbor
   contract; overlap cases move to the new red matrix as rejections.

## Steps

1. Red tests (fail first): duplicate-painter matrix; v0c operator-proof
   rewrite; F3 boundary matrix; no-full-replay proof.
2. Implement plan.py / verify.py / patch.py / dto.py.
3. Census mirror scripts.
4. Gates: focused files → ruff → mypy → full suite (background) →
   `git diff --check`.
5. Docs: PITFALLS (retire accepted-risk entry premises, add F2/F3 entries),
   regen index, TODOS (close twin-heuristic + preview-cost items),
   ARCHITECTURE (V0c description), this plan → archive on completion.

## Decisions log

- 2026-09-01: Followed the specified plan-time duplicate gate and 0.05 pt
  two-axis strict-overlap geometry. Exact-coincident shows remain capable of
  failing earlier as `AMBIGUOUS_MATCH`; that is already fail-closed and does
  not weaken the new gate for bindable near twins.
- 2026-09-01: Corrected the old “+1.0 pt neighbor” fixtures to a 1 pt GAP
  after the target's full advance. No plan decision was overturned; the red
  run confirmed the old offset was overlapping, as the Pro review reported.
- 2026-09-01: Tier 0 V0c uses lexer token shape plus successful decode; Tier 1
  uses exactly one guarded isolated replay. No full patched stream enters
  `replay_page_streams`.
- 2026-09-01: Added the derived-finiteness chokepoint after raw advances and
  mirrored the derived-`Th` admission leg in all three census scripts.
- 2026-09-01: Adversarial verification found a new arithmetic edge in the
  duplicate scan: a duplicated target with zero/non-finite font size could
  divide by the target size while scaling the candidate core. The scan now
  fails that duplicated/unplaceable target closed with the same reason; shows
  with no matching twin retain their pre-existing admission behavior.
- Residual limit retained as scoped: Form-XObject-hosted twins are not visible
  to the page replay scan; V0d's raster halo remains the bounding proof.
- 2026-09-01: Full-suite first pass had one unrelated load-sensitive timing
  miss in `test_fusion_pipeline.py` (0.235 s vs 0.22 s); the untouched test
  passed three isolated reruns and the authoritative full rerun passed all
  2,955 tests. No out-of-scope threshold change was made.
- 2026-09-01: Commit/archive dead end: `git mv` could not create
  `.git/index.lock` because the managed workspace exposes `.git` read-only.
  The untracked plan was archived with a validated workspace-local move; code,
  tests, docs, and gates are complete, but commits require git-metadata write
  permission outside this session.
- 2026-09-01 (orchestrator follow-up): commits landed from the main session
  after independent re-verification — F2/F1/F3 in three logical commits plus
  this docs/archive commit. The new duplicate-painter test's SOURCE and
  REPLACEMENT literals arrived mojibake'd ("雿?"/"?", a lossy console
  encoding); replaced with full-width "你好"/"再" so the abutting case truly
  shares an edge (a half-width `?` made it a gap case), re-ran 8/8 green.

## Open questions

- XObject-hosted twins stay invisible to the replay-based scan (pre-existing
  replay blind spot; V0d raster halo still bounds the damage) — recorded as
  a residual limit, not widened scope.
