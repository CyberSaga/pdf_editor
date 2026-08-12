# Task 12 — Tiered Engine Hardening & CID Coverage

**Status:** PLANNING (created 2026-08-12)
**Base lineage:** `task11/slice1-closure` (merge-base decision confirmed twice; by-fable is NOT cherry-picked — see Decisions)
**Defaults untouched until rollout gates pass:** `engine=legacy`, `max_tier=0` (same rule as Task 11 acceptance).

## 1. Goal

Close the three empirically proven engine-level defect classes found in the
2026-08-12 verification campaign against a real 50-page CAD document, then open
the first real coverage lever (CID hex-`Tj`). Priority order is evidence-driven,
not the order the original branch-analysis doc proposed:

| Priority | Workstream | Why it outranks the rest |
|----------|-----------|--------------------------|
| P0-A | Decoded-stream size/latency guard at the replay chokepoint | Prevents a ~10 GB OOM class reachable from an in-app edit today |
| P0-B | Streaming (generator) lexer | Removes the root cause P0-A guards against |
| P0-C | No silent legacy degrade (staged) | Proven fidelity loss is currently presented as ordinary success |
| P0-D | CID/Type0 single-hex-`Tj`, existing-glyph-only slice | The only lever that moves real-document coverage (ceiling ~82.7% ops) |

## 2. Evidence base (why this ordering)

From the 2026-08-12 session-local verification (5-agent forensics/funnel/memory/
fidelity campaign + 12 code-claim checks; raw evidence intentionally NOT in the
repo — see §10 Data policy):

- **Coverage funnel** (28,043 show ops / 172,602 chars across 50 pages):
  - single-hex-`Tj` on CID/Type0 fonts: 97.2% of ops (95.1% of chars);
    default-text-state subset: **82.7% ops / 81.0% chars** — the source-bindable
    *ceiling* for P0-D before encodability deductions.
  - whole-`TJ` + simple font (the doc's original P0): **0.75% ops / 0.24% chars**,
    all on 3 of 50 pages. Pivot condition "defer whole-array TJ if binding
    survival is negligible" (TODOS §After-Task-11) is hereby **triggered**.
  - The doc's flagship simple-font example is unrenderable anyway: the embedded
    subset lacks glyphs for 2 of 4 replacement chars (gid 0, /Widths 0) —
    replacement-encodability is a second funnel, not a footnote.
- **Memory blow-up**: `lex_content_stream` materializes the entire token list —
  on a ~72 MB decoded page stream that is ~54.7M `StreamToken` objects
  (~174–202 B/token incl. list+GC overhead; half of them WHITESPACE), peaking at
  ~10 GB RSS and ~115 s for the lex alone. Full GUI open of the same document
  peaks at ~472 MB — the render pipeline is innocent. Any tiered edit
  (prepare/preview) touching such a page hits this path in-app.
- **Loop growth** (50 edit/undo cycles, one process): decelerating,
  cache-dominated — slopes 5.08 (iters 0–9) → 6.02 (10–29) → 1.87 (30–49) →
  1.25 MB/iter (40–49); +207 MB total; private tracks WS at corr 0.9999.
  NOT a fixed-slope leak; residual ~1.2 MB/iter not yet excluded. Keep the
  classifier verdict `mixed_undetermined`; never describe as monotonic decay
  (10–29 is *faster* than 0–9).
- **Silent degrade**: legacy fallback swaps a serif+bold embedded font for
  Helvetica (flags 20 → 0) at identical size/color/baseline, and on growth
  overlaps an unmoved neighbor glyph by 10.26 pt — while `outside_diff == 0`.
  Pixel-drift metrics cannot see this; a semantic gate can.

## 3. Non-goals (this task)

- Whole-`TJ` simple-font support (P2 — kept in backlog, value < 1% on this corpus).
- Font subset augmentation / re-embedding (P1 — required for missing-glyph
  replacements; separate plan when P0-D lands).
- Paragraph layout / reflow (unchanged Task 11 constraint).
- Changing strict-mode behavior — strict already fail-closes
  (`REJECTED_STRICT`, zero mutation, `pdf_text_edit.py:1571-1587`).

## 4. Workstreams

### P0-A — Replay resource guard (single chokepoint)

`replay_page_streams` (`model/text_commit/replay.py:181`) is the **only**
production path into `lex_content_stream` (verified: prepare
`pdf_text_edit.py:1733 → engine.py:132 → plan.py:289 → inspect.py:355`;
per-keystroke preview `preview.py:276 → same`; Form-XObject deconfliction
`inspect.py:331`; discovery helper `inspect.py:291-292`). Commit verification
(`verify.py`) only byte-compares/hashes — it never lexes.

- Add `max_decoded_bytes` (keyword, default constant) to `replay_page_streams`;
  refuse **before** tokenization with stable reason
  `content_stream_too_large_for_safe_replay`, surfaced through the existing
  fail-closed vocabulary (PlanRejection/BindingFailure style) so every caller
  handles it without new plumbing.
- Explicitly do NOT guard: `lex_content_stream` itself (diagnostic scripts lex
  small bounded slices legitimately), `read_page_streams` (verify must still
  hash/compare oversized streams — a perf limit must not become a correctness
  failure), or the commit verifier.
- The guard survives P0-B: even a streaming lexer needs ~minutes to walk a
  72 MB stream — this is a latency ceiling for preview, not only OOM defense.

### P0-B — Streaming lexer

- Convert `lex_content_stream` (`pdf_lexer.py:116`) from `list[StreamToken]` to
  a generator. Verified feasible with zero contract change: replay consumes
  tokens in one forward pass (`replay.py:257`), discards WHITESPACE/COMMENT
  immediately, clears the operand stack per operator, and copies every offset
  the splice needs into `ShowOp` (`stream_xref/op_start/op_end/string_start/
  string_end`, `replay.py:84-100`); `splice_stream` validates purely by byte
  range + expected bytes + SHA-256 and never sees a token.
- Mechanical notes: replace the lexer's single self-read `tokens[-1].end`
  (`pdf_lexer.py:184`) with a local; wrap lexer unit tests in `list()` (they
  assert gap-free tiling); `measure_tier_funnel.py`'s `any(...)` usage is
  already generator-compatible.
- `StreamToken` has fields `kind/start/end` only. If an interim `__slots__` is
  wanted before the generator lands: manual tuple `("kind", "start", "end")` —
  `@dataclass(slots=True)` is py3.10+, project floor is 3.9. After streaming,
  slots are optional micro-optimization, not the fix.

### P0-C — Degrade visibility & consent (promotes T12-P1-06)

Scope is the **default non-strict path only**. Staged:

1. **Phase 1 — visibility**: GUI must present `degraded_committed` distinctly
   from success (status + safe reason code, e.g. `tier0:not_single_literal_tj →
   legacy`). No document text, filename, or path in any telemetry/log line.
2. **Phase 2 — consent**: pause before legacy mutation:
   high-fidelity rejected → "degraded fallback pending confirmation" → user
   confirms → legacy commit. View emits a signal; Controller coordinates;
   Model stays Qt-free (layer rules).
3. **Semantic fidelity gate** (acceptance + optional runtime check): without a
   requested style override — font identity/serif/bold/italic, size, color,
   baseline unchanged; replacement ink must not intersect non-target glyphs;
   non-target glyph origins unmoved; all still true after save/reopen.
   `outside_diff == 0` alone is NOT a fidelity pass (proven false negative).

### P0-D — CID/Type0 single-hex-`Tj`, existing-glyph-only slice

Narrowest useful slice: direct page stream, single hex `Tj`, default text
state, unique origin, reversible ToUnicode/CMap, **every replacement glyph
already present in the embedded subset** (fail closed otherwise). Gate chain:

```
Unicode → unique reversible code → valid CID (Encoding CMap)
→ nonzero GID (/CIDToGIDMap) → glyph present in embedded subset (not .notdef)
→ advance provable (/W, /DW) → equal advance: keep Tj; else compensated TJ
→ scratch render + extraction verify → save/reopen verify
```

- `/FirstChar../LastChar` + encoding coverage is NOT proof a subset contains a
  glyph — gid 0 / width 0 must fail closed (proven trap on the real corpus).
- **Acceptance must include `/Rotate 270` pages** — 47 of 50 pages in the
  reference corpus are rotated landscape; passing only unrotated synthetic
  fixtures does not validate the page-space contract that the coverage
  numbers were measured on.
- Report coverage as the two-funnel model: source-bindable vs
  replacement-encodable (TODOS funnel item, both weightings).

### P1 / P2 / Cleanup (registered, not in this task's critical path)

- **P1**: subset augmentation / font re-embedding (unlocks missing-glyph
  replacements — the doc's flagship example class). Existing T12-P1-01..05
  fixtures list still applies where relevant.
- **P2**: whole-`TJ` simple-font; 100–200-cycle lifecycle attribution with
  per-subsystem counters (Qt/MuPDF/engine caches) to close the ~1.2 MB/iter
  residual question.
- **Cleanup**:
  - `decision_chain` field on `CommitOutcome` — record tier escalation
    (`tier0:rejected:advance_mismatch → tier1:committed`) while keeping
    `fallback_chain=()` for successful escalation (reserve `fallback_chain`
    for true degrades). Do NOT port by-fable's representation
    (`compensated_transplant_kern` as a warning is a category error; a
    `strategy` field waits until a second tier-1 strategy exists — today
    `tier==1` ⇔ kern-compensated transplant, `plan.py:678`, single builder).
  - Dead optional reflow hook: controller logs `No module named 'reflow'` on
    every edit (evidence grade: agent-reported; capture a logger run first,
    then remove the hook or ship the module).

## 5. Affected modules

- `model/text_commit/replay.py` (P0-A guard, P0-B consumption)
- `model/text_commit/pdf_lexer.py` (P0-B generator; splice untouched)
- `model/text_commit/plan.py`, `engine.py`, `dto.py` (P0-C reasons, P0-D slice,
  Cleanup `decision_chain`)
- `model/text_commit/fonts.py`, `inspect.py` (P0-D CMap/CIDToGIDMap/W parsing)
- `model/pdf_text_edit.py` (P0-C non-strict path)
- `controller/` + `view/` (P0-C phases 1–2; signals only, no Model imports)
- `test_scripts/` (new fixtures — all synthetic)

## 6. Test strategy (Red-Light First)

All fixtures synthetic — nothing derived from the private corpus (§10).

- **P0-A red**: synthetic PDF with a giant generated vector-path content stream
  (repeat `m/l/c` ops to tens of MB). Assert: refusal before lex (lexer spy =
  zero calls), stable reason, strict → zero mutation, small streams unchanged,
  `read_page_streams` + hashing still work on the oversized stream.
  **Reason-propagation invariant (frozen 2026-08-12):**
  `content_stream_too_large_for_safe_replay` must survive verbatim to the
  outermost observable surface (`PlanRejection` / `CommitOutcome`) — the red
  test asserts it is NOT collapsed en route into `malformed_stream`,
  `no_source_match`, `verification_failed`, or any other generic reason.
  (Without this, the guard stops the OOM but the user and the funnel can't see
  why; P0-C then surfaces a meaningless code.)
- **P0-B red**: memory acceptance — measured as **peak RSS in an isolated
  subprocess** (parent collects the result), not in-process RSS (allocator
  high-water pollution) and not gc object counts (misses non-GC allocations).
  Plus, on small fixtures: field-by-field equality of `ShowOp` records, splice
  offsets, and stream digests between the list lexer and the generator lexer;
  a structural assertion that `lex_content_stream(...)` returns an iterator
  (not a `list`/`Sequence`); gap-free tiling tests consume via
  `list(lex_content_stream(data))` on the test side.
- **P0-C red**: `test_non_strict_legacy_fallback_requires_consent`
  (T12-P1-06) + semantic-gate fixtures: embedded serif-bold subset replaced →
  gate must fail on font-identity loss even with zero outside-rect drift;
  growth-overlap fixture; shrink-gap fixture must PASS (no-reflow contract).
- **P0-D red**: synthetic Type0/CID fixtures (reversible ToUnicode; a subset
  missing one replacement glyph → must fail closed; equal-advance and
  unequal-advance cases; a `/Rotate 270` page variant of each).

## 7. Step list

1. [x] P0-A: red fixture + failing tests → guard in `replay_page_streams` → green.
       (2026-08-12: `test_text_commit_replay_guard.py`, 10 tests — 8 red shown,
       2 scope pins. Red output proved the hazard: a full `PreparedEdit` was
       built on an 8.5 MiB synthetic page after total token materialization.)
2. [x] P0-B: red memory-ceiling test → generator conversion (+ test `list()`
       wrappers) → green; re-run Task 11 tier0/tier1 suites for byte-identity.
       (2026-08-12: `test_text_commit_lexer_streaming.py` + subprocess child,
       3 red shown — 8 MiB walk peaked 1162/1178 MB pre-conversion, 26 MB
       post (44×); 6.02M tokens walked gap-free; full text_commit family
       265 passed.)
3. [x] Re-measure: preview latency + peak RSS on a dense synthetic page
       (TODOS re-measure item folds in here).
       (2026-08-12, post-P0-B, synthetic pages, per-`prepare` wall time:
       0.5 MiB ≈ 525 ms; 2 MiB ≈ 2.1 s; 3.8 MiB ≈ 4.1 s; 8 MiB → guard
       refusal in ~15 ms with the verbatim reason. Peak RSS flat 45–75 MB —
       the 133× amplification is gone; latency now scales ~1.05 s/MiB of
       decoded stream, so the guard's role as a preview latency ceiling is
       confirmed, and per-keystroke re-prepare stays the open P0-C-adjacent
       cost. Repeats are stable → no hidden caching.)
4. [ ] P0-C phase 1: reason-code surfacing, GUI visibility; semantic gate as
       acceptance harness.
5. [ ] P0-C phase 2: pre-commit confirmation flow (View→Controller signal).
6. [ ] P0-D: gate-chain slice behind `max_tier`/flag; `/Rotate 270` acceptance.
7. [ ] Cleanup: `decision_chain`; reflow-hook capture + removal.
8. [ ] Docs: ARCHITECTURE (guard + streaming lexer + outcome fields), PITFALLS
       (token materialization, gid-0 subset trap, slots-vs-3.9), TODOS sync,
       `git mv` this plan to `plans/archive/` on completion.

## 8. Decisions record

- 2026-08-12: merge base stays `task11/slice1-closure`; by-fable not
  cherry-picked (all new findings are shared-infrastructure issues; closure
  already has identical `CommitOutcome` fields incl. `verified_properties` —
  only population differs, `engine.py:274-283`).
- 2026-08-12: whole-`TJ` P0 demoted to P2 on measured coverage (<1%); CID
  hex-`Tj` promoted to the coverage P0.
- 2026-08-12: guard lives at the chokepoint only — one patch site, not six
  surfaces (bug-class rule: chokepoint first).
- 2026-08-12: 9.86 GB attributed to lexer token materialization, not GUI
  rendering; both the guard (latency+OOM) and the generator (root cause) ship.
- 2026-08-12 (P0-A implementation): budget is **summed** across the page's
  stream list (state carries across streams — per-stream would be a hole);
  initial default 4 MiB (~0.5 GB transient / few-seconds lex pre-streaming;
  over-budget pages fall to legacy, which is what every page gets today under
  `max_tier=0`, so aggressive refusal costs nothing); refusal travels on a NEW
  `PageReplay.refusal_reason` channel, distinct from `malformed`, because
  `bind_source_text` collapses `malformed` into `MALFORMED_STREAM` — the exact
  dilution the frozen invariant forbids. `max_decoded_bytes=None` disables
  (diagnostic escape hatch, e.g. funnel scripts). Test pin: default ≤ 8 MiB.
- 2026-08-12 (adversarial verification round, workflow `wf_e06e4c05-e6f`,
  2 serial agents): generator tiling parity proven branch-by-branch incl.
  ID/inline-image edges; spy namespace, escalation exclusion, rewrite gates,
  CI portability all cleared. Four real findings, all fixed same day:
  (1) medium — the Form-XObject deconfliction scan (`inspect.py`) collapsed
  a refused replay into `NO_MATCH` (rewritable into a fabricated
  `target_reconstruction_unverified`); fixed with a tri-state helper
  (`True`/`False`/`None`=scan refused) + verbatim refusal surfacing, 2 red
  tests shown first (both red as `no_source_match` — the exact collapse);
  (2) low — audit/funnel/benchmark scripts silently counted refused pages
  as zero-show; fixed with `max_decoded_bytes=None` at all 5 census sites;
  (3) medium — a `None or DEFAULT` coercion mutation would beat both
  suites; killed by having the memory child report `refusal_reason` and the
  parent assert it is None; (4) low — strict-`>` boundary unpinned; killed
  with an exact `total == budget` / `budget + 1` boundary pin.

## 9. Open questions

- ~~`max_decoded_bytes` default / per-stream vs summed~~ **RESOLVED in P0-A**
  (see Decisions: summed budget, 4 MiB initial default, `None` disables).
  Still open: post-P0-B the constant should relax into a latency budget —
  revisit after step 3 measurements.
- P0-D encoding scope for the first slice: which CMaps are in scope?
  Identity-H was previously marked NO-GO under `font_unsupported_encoding`
  (TODOS Q3-ceiling item) — the slice must either scope it in with the full
  gate chain or explicitly keep it out and say so in the funnel report.
- P0-C phase 2 UX: per-edit modal vs session-level policy setting.
- Runtime semantic gate: always-on vs acceptance-only (render+extract per
  commit has a latency cost; measure in step 3).

## 10. Data policy

The motivating evidence comes from a private, identifying engineering document.
Raw evidence (renders, edited PDFs, absolute paths, filenames, doc identifiers)
stays out of the repo permanently. The repo carries only: anonymized aggregate
numbers (as in §2), synthetic fixtures, and reason-code-level telemetry.
Telemetry/decision traces must never record document text, filenames, or paths.
