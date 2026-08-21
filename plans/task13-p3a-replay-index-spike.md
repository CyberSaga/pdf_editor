# Task 13 P3-A — replay index spike: latency census + invalidation contract

**Status:** IN PROGRESS (created 2026-08-21)
**Branch:** `task13/p3-replay-indexing` (off `task11/slice1-closure` @ 137a50b, P2 merged)
**Parent plan:** `plans/task13-cad-binding-unlock.md` §4 (Priority 3) — this is
step 6's first half: the read-only spike that must precede any production
index/caching change (census-before-code, the P0-D discipline).
**Data policy:** unchanged from the parent plan — aggregate-only corpus
output (counts, timings, byte totals, reason codes); no text, no filenames,
no paths, no coefficients in any committed artifact or emitted report.

## 1. Goal

Measure — do not yet fix — the preview-latency half of the replay budget
problem. Task 12 sealed the numbers: prepare costs ~1.05 s per decoded MiB
per keystroke because `preview.py` re-runs `prepare_tier0_plan` per
generation, which replays every content stream on the page and then re-reads
them (`inspect.py` `read_page_streams` is called twice per prepare). 16,549
operand-stage candidates die at the 4 MiB summed budget
(`DEFAULT_MAX_REPLAY_BYTES`, `replay.py:36`).

Deliverables (all read-only w.r.t. production admission):

1. **Cold/warm latency harness** (`scripts/benchmark_replay_index_spike.py`)
   decomposing prepare latency by stage: stream read/decode → lex/replay
   walk (ShowOp construction) → target binding → admission (mc + TRM) →
   planning/fingerprint → scratch clone + apply → verification. Scenarios:
   cold first edit; same page second target; same page same target changed
   replacement; same page after content mutation; different page.
2. **Two index-shape prototypes**, spike-only, in `scripts/` (never
   `model/`), each measured for build latency, warm lookup latency, and
   memory (bytes/ShowOp, bytes per decoded MiB):
   - **Shape A — materialized ShowOp table:** one full replay per page
     generation, retain `PageReplay` (already-frozen dataclasses); warm
     lookups are table scans/binds against the retained tuple.
   - **Shape B — sparse index + checkpoint replay:** retain only operator
     offsets, periodic state checkpoints, and candidate show boundaries;
     a warm lookup restores the nearest checkpoint and replays locally to
     the target.
3. **Invalidation surface contract** (§4 below + `docs/` record): every
   mutation path that MUST invalidate a per-page replay index, every one
   that MUST NOT, and the existing hooks that carry the signal
   (`PDFModel.mark_page_content_dirty`, `DocumentFontRegistry.
   bump_generation`, `TieredCommitEngine.clear_verified_candidates`).

## 2. Hard fences (violating any of these voids the spike)

- **No production admission change.** `model/text_commit/` is read-only
  this slice except — nothing. Zero edits.
- **No persistent cache.** Prototypes live and die inside one harness
  process; nothing is written to the document or to disk except the
  aggregate JSON report.
- **The 4 MiB budget is untouched.** `DEFAULT_MAX_REPLAY_BYTES` stays
  4 MiB; production paths never pass `max_decoded_bytes=None`; the
  prototypes must refuse over-budget pages exactly as replay does today.
  (The harness MAY measure over-budget pages under an explicit
  `--diagnostic-unbounded` flag using the same `max_decoded_bytes=None`
  channel every existing diagnostic script already uses — clearly labeled
  in the report, never a production behavior claim.)
- **Red-first** for every piece of spike logic with a correctness contract
  (checkpoint-replay equivalence, index build refusal, report data-policy
  pins). Measurement plumbing (timers, JSON emit) follows the benchmark
  script precedent.

## 3. Latency decomposition (what the harness times)

Cold path (per keystroke today, `preview.py` → `prepare_plan`):

| stage | code | notes |
|---|---|---|
| stream read/decode | `inspect.read_page_streams` | called TWICE per prepare today (bind + plan re-read) — measure both |
| lex + replay walk | `replay.replay_page_streams` | tokenization + state machine + ShowOp construction; budget guard entry |
| font capability | `fonts.DocumentFontRegistry` | generation-keyed cache already exists — measure hit vs miss |
| target binding | `inspect.bind_source_text` | linear scan over shows |
| admission | `marked_content.admit_show_wrappers`, `transforms.admission_verdict` | per-candidate |
| planning + fingerprint | `plan.prepare_plan`, `inspect.page_fingerprint` | fingerprint hashes streams + deps |
| scratch clone + apply | `engine._build_scratch_copy`, `patch.apply_patchset` | `tobytes` + reopen dominates? measure |
| verification | `verify.verify_tier0_commit` | raster + extraction probes |

Warm-scenario matrix (each timed cold vs warm, N iterations, p50/p95):

1. cold: first prepare on a page (nothing retained);
2. warm-A / warm-B: second target on the same page through each prototype;
3. warm same-target changed-replacement (the keystroke case);
4. post-mutation: same page after a content splice (index must rebuild —
   measures invalidation cost honestly);
5. different page (index is per-page; must not help, must not hurt).

## 4. Invalidation surface — CONTRACT (census complete, 2026-08-21)

Serial analysis round (workflow wf_2d232d0d-211, 2 agents strictly
serial). Key = (page xref, ordered stream xref tuple, per-stream
decoded-byte digests). Everything else (fonts, annotations, /Rotate,
/OCProperties) stays OUTSIDE the index: it caches only what replay
itself proves (spans, state, wrapper evidence); visibility/capability/
fingerprint each have their own dependency closure.

**Headline verdict: push-only invalidation cannot be complete.** Four
mutation classes change live content-stream bytes with NO signal today:

1. `clean_contents` execution — `apply_pending_redactions`
   (`pdf_model.py:3467`) rewrites bytes AND the /Contents tuple of every
   non-protected pending page at save_as (`:3805`) and every 5th edit
   (`pdf_text_edit.py:1944` → `pdf_model.py:3490`); `pending_edits` is
   cleared with zero hook at execution time (the queue-time
   `mark_page_content_dirty` fired arbitrarily earlier).
2. Live tiered commit splice AND its revert — `patch.py:120` via
   `engine.py:240`; `patch.py:85` via `engine.py:255/274`.
   `bump_generation` is fonts-only; `mark_page_content_dirty` is
   deliberately absent (page becomes fidelity-protected,
   `pdf_text_edit.py:1871`).
3. Tier 0/1 undo/redo patchset replay — `edit_commands.py:394/460`
   (only the page-number text index rebuilds).
4. Page-splice restore — `_restore_page_from_snapshot`
   (`pdf_model.py:3366-3368`, 6 call sites): page xref and stream xrefs
   replaced; freed xref numbers can later be REUSED (key-identity
   hazard — the digest is the only defense).

**Therefore: pull-validation is the contract.** At lookup, re-read
`page.get_contents()` + per-stream digests and compare against the key
(exactly what `patch.py`'s splice gate and `page_fingerprint` already
do); a mismatch rebuilds. Every push hook is demoted to an eviction /
latency optimization, never a correctness dependency. Additional pins:

- `mark_page_content_dirty` fires MID-transaction (`pdf_text_edit.py:628`
  precedes the insert stage at `:745-935`): any eager recompute on the
  mark caches intermediate state — invalidation must be
  flag-now/recompute-lazily.
- Shared content streams: `update_stream` sites mutate streams other
  pages' /Contents may reference; only the digest defends sibling pages.
- `garbage>=1` save/repair paths renumber ALL xrefs; the doc-setter
  engine drop (`pdf_model.py:455-465`) is the natural whole-document
  reset home — an index owned by the engine inherits every
  doc-replacement invalidation for free. `garbage=0` snapshot restores
  preserve numbering and bytes, so warm keys genuinely re-validate.
- MUST NOT invalidate (verified against this repo's code): annotation
  create/update/move/delete (annot /AP only), hidden app-object marker
  maintenance, `/Rotate` via `set_rotation` (page dict only — replay
  output is user-space; caching anything visually-mapped is forbidden),
  metadata/outline, watermark session state (live content only changes
  at the save_as reopen, which the doc setter already covers),
  incremental save, saves to a different path, optimizer (clone-only),
  read-only serialization/snapshots (the insert_pdf `/P`-key quirk is
  annotation-dict-only).
- Complete raw-writer inventory on the live doc:
  `pdf_object_ops.py:195,431,928` (+`:457` dict-only), `patch.py:85,120`,
  `inspect.py:421` (dict-only). Nothing else in model/controller/utils/
  view writes streams directly.
- `pending_edits` membership (`plan.py:304` PENDING_MAINTENANCE gate) is
  the design precedent: a pending-maintenance page's index entry is
  at-risk exactly as Tier 0 refuses to plan against it.

## 5. Step list

1. [x] Serial analysis round (workflow wf_2d232d0d-211, 2 agents,
       serial): invalidation census + checkpoint-state contract — §4 and
       the 2026-08-21 §7 record.
2. [x] Red matrix (`test_scripts/test_replay_index_spike.py`): 40 tests,
       38 red at collection + 2 labeled controls; failing output shown
       before implementation (§7 steps-2+3 record).
3. [x] Implement harness + prototypes in `scripts/`; 40/40 green on the
       first post-implementation run; ruff clean (feat commit).
4. [x] Adversarial review round (workflow wf_d916552a-52f, serial
       Attack→Verify): 8 findings (4 important CONFIRMED), all fixed —
       stage-pin red-first for F3, mutation-verified pin for F4
       (fix commit; §7 step-4 record).
5. [x] Corpus measurement run (aggregate-only) — §7 step-5 record:
       replay is ~90% of the per-keystroke cost; warm validated lookups
       8–14 ms vs 2.7–4.8 s cold (~250–400×); **Shape A wins, Shape B
       rejected for v1 on measured memory** (checkpoints cost 4–6× more
       than Shape A retains in total on dense pages).
6. [x] Docs (PITFALLS entries added: tracemalloc bias, json.dumps
       backslash-inert assertion, getsizeof `__dict__` undercount),
       TODOS housekeeping (P2-merged note; spike status), commit,
       push branch for remote review.

## 6. Open questions going in (all but the last ANSWERED by §7 step 5)

- Where does the ~1.05 s/MiB actually go — lexing, ShowOp allocation, or
  the double stream read? **ANSWERED: the replay walk is ~90% (2.74 s of
  a ~3 s prepare on dense pages); the double read is 5 ms.**
- Is Shape B's checkpoint restore even sound mid-page? **ANSWERED:
  sound under the analysis-round placement contract (empty operands,
  token boundaries, BI..EI exclusion, retained page globals) — pinned
  by the equivalence matrix — but the shape is REJECTED for v1 anyway:
  at interval 64 its checkpoints retain 4–6× more than Shape A total.**
- Memory: is retaining a full `PageReplay` for a 4 MiB page acceptable
  (Shape A)? **ANSWERED: yes — 0.78–1.19 MB per dense corpus page
  (~1.1–1.7 KB/show, `__dict__`-dominated); `decoded_bytes` duplication
  is negligible (8–12 KB/page) on this corpus.**
- Index persistence across save/reopen (parent plan §8) stays OPEN —
  explicitly out of this spike (no persistent cache fence).

## 7. Decisions record

- 2026-08-21 (step 1 — serial analysis round, workflow wf_2d232d0d-211,
  invalidation census + checkpoint contract):
  - **Invalidation contract**: pull-validation (digest-verified keys at
    lookup); push hooks are optimizations only. Full record in §4.
  - **Shape B is necessarily a HYBRID.** `McWrapper.closed`/`crossed_q`/
    `close_*` are written by EMC/Q operators AFTER a show
    (`replay.py:536-539, :724-729`); `PageReplay.malformed`,
    `has_xobject_invocation`, `mc_emc_underflows`, `refusal_reason` are
    page-global. A local replay stopping at the target structurally
    CANNOT compute any of them, and `admit_show_wrappers` /
    `bind_source_text` consume exactly those fields. So Shape B =
    checkpoints + sparse rows + a retained end-of-page evidence block
    (small — wrappers are dozens, not thousands), and local-replay
    output may NEVER be served as wrapper evidence or page verdicts.
  - **Checkpoint state contract** (complete field list with sites in the
    analysis record): the 9-field `_State`, the FULL `gs_stack`
    contents (not depth — Q restores exact snapshots), `tm` AND `tlm`
    (Td/TD/T* compose against tlm), `in_bt`, `mc_depth` (clamped,
    independent of `len(mc_open)`), `mc_open` ids + per-open-wrapper
    scratch records (deep-copied, never aliased — `_McRecord` is
    mutable/shared), wrapper-id seed (`len(mc_records)`), show seed
    (`len(shows)` — `seq` must stay bit-identical), `advance_pending`
    (drives `origin_reliable` → UNTRACKED_ADVANCE; the easiest field to
    forget), and stream position (index + token-boundary byte offset).
  - **Placement constraints**: checkpoints only where the operands list
    is empty (excludes number runs, the `"` operand prefix, TJ array
    construction, BDC inline dicts, keyword operands), never from BI
    through EI (after-ID the operands ARE empty — the trap: a restart
    would lex the binary payload), offsets must be token boundaries
    captured during the initial lex (the lexer cannot restart
    mid-token; its only cross-token state is the ID lookahead), and
    stream starts are always legal (the per-stream operand reset at
    `replay.py:468` DROPS dangling cross-stream operands — checkpoint
    replay must reproduce the drop, not PDF-spec concatenation).
  - **Spike implementation decision — parameterized loop copy.** The
    production loop has no initial-state/start-offset parameters and
    P3-A must not touch `model/`; the spike therefore carries ONE
    parameterized copy of the operator loop (`scripts/`), used for both
    instrumented build and checkpoint restore, importing every helper
    (`_State`, `_Operand`, `_McRecord`, `_parse_mc_operands`,
    `_mat_mul`, decode fns) from `replay.py` so only the loop body is
    duplicated. Drift is pinned by a build-equals-production equivalence
    test (full `PageReplay` equality across every probe fixture) plus
    the field-by-field restore matrix. A future P3-B production
    implementation must instead parameterize `replay.py`'s own loop —
    the copy is a spike-only measurement device. (Also noted: the
    planned streaming lexer (Task 12 P0-B) changes exactly the
    offset/tiling layer — placement legality must be re-proven against
    it before any production index lands.)
  - **Retained truth comes from the single instrumented pass** (build
    runs the loop copy once; rows/globals/checkpoints all come from it)
    so Shape B build cost is measured honestly as one pass; the
    equivalence matrix is the drift net that keeps the copy honest.

- 2026-08-21 (steps 2+3 — red matrix + spike implementation):
  - **Red matrix**: `test_scripts/test_replay_index_spike.py`, 40 tests
    (38 red at collection via the missing `scripts.replay_index_spike` /
    `scripts.benchmark_replay_index_spike` modules — the P2-B
    missing-module precedent — plus 2 explicitly-labeled green CONTROLS
    pinning the production-replay facts the fixtures rely on).  All 39
    fixture assumptions were pre-validated against production replay
    BEFORE implementation (scratch probe); one assumption was wrong and
    fixed at the fixture level: a `Q` popping back TO a wrapper's
    opening gs depth is legal and uncrossed — `crossed_q` requires the
    wrapper to open INSIDE the `q` so the pop goes BELOW its opening
    depth.
  - **Implementation green**: 40/40 on the first post-implementation
    run.  Shape A = `MaterializedShowTable` (retains the production
    `PageReplay` verbatim — build calls `replay_page_streams` itself, so
    Shape A cannot drift).  Shape B = `SparseCheckpointIndex` (hybrid
    per the analysis verdict: packed `ShowRow`s + `Checkpoint`s +
    retained page-global evidence block; `_replay_core` is the
    parameterized loop copy used for both instrumented build and
    checkpoint restore, with a `scalar_mirror` seam so the capture
    closure snapshots the loop's scalar locals synchronously).  Refused
    warm lookups raise `ReplayIndexRefusedError(reason)` — the refusal
    is never collapsible into an empty miss.
  - **Harness**: `scripts/benchmark_replay_index_spike.py` — per-stage
    decomposition, five scenarios, per-prepare stream-read counting (a
    `doc.xref_stream` instance-shadow counter), refusal-cost probes for
    over-budget pages (page selection favors the largest WITHIN-budget
    pages: a pure top-by-size pick on the corpus doc would select only
    over-budget refusal pages and miss the latency story), aggregate-
    only JSON.
  - **Memory accounting pitfall caught pre-review**: `sys.getsizeof` on
    a slotless dataclass misses the per-instance `__dict__` container —
    exactly the dominant bytes/ShowOp driver the analysis round named —
    so `_deep_size` sizes `vars(obj)` for slotless dataclasses.

- 2026-08-21 (step 4 — adversarial review round, serial Attack→Verify
  workflow wf_d916552a-52f; 8 findings filed, verified verdicts: 4
  important CONFIRMED, 3 minor CONFIRMED, 1 minor PARTIAL — all 8
  addressed before the corpus run, which the Verify agent explicitly
  gated on F1/F2/F3):
  - **F1 (important)**: shape build stage timings ran with tracemalloc
    tracing active while every competing stage ran without it —
    systematically biasing the census's central build-vs-replay
    comparison against both index shapes.  Fix: builds are timed clean;
    the peak is measured separately.
  - **F2 (important)**: `build_peak_tracemalloc_bytes` was read after N
    iterated builds with the previous iteration's retained index still
    referenced — inflating the peak by roughly one whole retained index
    (worst for Shape A, whose retained size is the plan §6 memory
    question).  Fix: `_single_build_peak` traces exactly one throwaway
    build after a `gc.collect()`.
  - **F3 (important)**: warm-lookup timings omitted the pull-validation
    cost §4 charges to EVERY warm lookup (re-read + digest compare), so
    the cold-vs-warm headline was overstated by orders of magnitude on
    dense pages.  Fix: new pinned stage `key_validation`; the warm
    SCENARIOS are contract-honest validated composites (labeled
    `index_warm_validated`) while the raw `shape_*_lookup` stages stay
    pure scan/restore decompositions, with an explicit
    `raw_lookup_stages_exclude_key_validation` marker.  (Fixed
    test-first: the stage-name pin went red before the harness change.)
  - **F4 (important)**: the refused-lookup obligation was pinned only
    for Shape B; deleting Shape A's guard collapsed a refused lookup
    into the forbidden empty miss with the whole matrix green.  Fix:
    refusal-surfacing pin added to the Shape A over-budget test —
    mutation-verified SENSITIVE (guard neutered → red; restored →
    green).
  - **F5 (minor)**: `warm_changed_replacement` reported today's full
    prepare under a warm label with no index-warm counterpart.  Fix:
    every scenario carries a `path` label
    (`production_full_prepare` / `index_warm_validated` /
    `index_rebuild` / `index_build_other_page`) and the keystroke
    scenario gains `index_warm_replay_share` — the validated
    candidate-scan+restore share an index could actually replace.
  - **F6 (minor, PARTIAL)**: every restore-parity test ran at
    interval=1 or with an explicit checkpoint, so the harness's actual
    configuration (default nearest-selection at a sparse interval) had
    no direct pin — though the claimed silent-wrong-restore consequence
    was refuted (earlier-checkpoint selection is invariant-correct and
    past-the-row selection self-detects via `LookupError`).  Fix: new
    test restores every show of three fixtures at interval=8 via
    default nearest selection, field-by-field.
  - **F7 (minor)**: the +1-byte-per-stream mutation can flip a
    within-budget page over the budget, and the scenario then reported
    a refusal timing as rebuild cost.  Fix: the scenario records a
    `refused` flag.  (Verify correction absorbed: the refused path
    costs milliseconds, not microseconds — the sha256 key is computed
    before the budget check.)
  - **F8 (minor)**: the data-policy path assertion was inert on Windows
    (`json.dumps` escapes backslashes, so the raw path can never
    match).  Fix: assert the JSON-encoded spelling and the
    forward-slash form.
  - Attack notes worth keeping: the loop-copy fidelity audit
    (operator-by-operator normalized diff vs production) found ZERO
    semantic divergence; checkpoint capture, restore soundness (a
    misused later-position checkpoint raises rather than returning a
    wrong show), TJ re-lex decode parity, `_count_stream_reads`
    restoration, and the data-policy key audit all came back clean;
    fences 1 (no model/ edits) and 4 (no persistence, no doc mutation)
    verified against the staged diff.
  - Post-fix state: 41/41 green, ruff clean.

### Step-5 measurement record (corpus aggregates, 2026-08-21)

Run: both corpus documents, 3 iterations, top-4 WITHIN-budget pages per
doc + 2 over-budget refusal probes (doc_0: 50 pages, 11 over budget;
doc_1: 23 pages, 0 over).  Raw JSON stays in the gitignored local
`benchmarks/p3a-spike-2026-08-21.json`; aggregates only here.

**1. The per-keystroke cost is REPLAY, almost entirely.**  doc_0 dense
pages (1.95–3.47 MiB decoded, 667–1,075 shows): cold `prepare_plan`
median 2.70–4.77 s (~1.4 s/MiB — the Task 12 "~1.05 s/MiB" story,
re-confirmed on this machine); the replay stage alone is 2.74 s median
of medians vs read_streams 5.4 ms, fingerprint 50.6 ms.  A repeated
keystroke (changed replacement) pays the same full cost again
(2.66–4.73 s).  The double stream READ is a rounding error; the
re-REPLAY per generation is ~90% of the bill.

**2. Warm lookups under the honest pull-validation contract are
~8–14 ms on dense pages** — `key_validation` (mandatory re-read +
sha256 compare) is 8.3 ms median and dominates the warm path; the
validated index-warm keystroke share is 8.5–11.4 ms and the validated
second-target lookup 7.2–13.5 ms.  Against the 2.7–4.8 s cold replay
share that is a **~250–400× reduction**, leaving plan/verify stages and
validation as the new floor.

**3. Shape A wins, decisively.**  Build == one production replay
(2.80 s vs 2.74 s — i.e. the build costs what every keystroke already
pays today, once per page generation); retained memory 0.78–1.19 MB per
dense page (1,106–1,688 bytes/show — the slotless-`__dict__` overhead
the analysis round predicted dominates; `decoded_bytes` duplication is
negligible on this corpus, 8–12 KB/page of 2-byte CIDs); correctness is
inherited (it IS the production `PageReplay`).  Single-build tracemalloc
peak ≈ retained size (~1.2 MB) — no transient blow-up.

**4. Shape B LOSES on this corpus at the default interval.**  Retained
3.9–7.3 MB per dense page — 4–6× MORE than Shape A — because dense CAD
pages emit thousands of checkpoints (3,887–7,042 at interval 64) at
~1 KB each (full gs_stack + state tuples); the sparse rows themselves
are small (209–336 KB).  Its raw warm lookup is also ~30× slower than
Shape A's (1.3 ms vs 0.04 ms) and its build ~12% dearer (checkpoint
capture).  The hybrid's extra complexity buys nothing here: Shape B
would only win where retaining decoded bytes is expensive, and this
corpus's shows are tiny.  On doc_1's small pages Shape B does retain
less (e.g. 708 KB vs 1.00 MB) — but those pages replay in 58 ms and
need no index at all.

**5. Over-budget pages: even the refusal pays the DECODE.**  The two
~72 MB probe pages refuse in microseconds at the guard — but
`read_page_streams` (xref_stream decode) costs 190–240 ms before the
guard ever sees a byte count.  The budget's latency role is now
measured cleanly: within-budget dense pages are the index's target;
over-budget pages stay refused (revisiting them is P3-B's
indexing-SLO question per parent plan §4, NOT a budget raise).

**6. Probe honesty notes.**  Dense doc_0 targets die at
`type0_unicode_unmapped`/`mc_malformed_pairing` (the harness binds the
longest show, not a bindable one) — reject-path timings, like the Task
11 baseline benchmark, which still exercise the full replay+bind cost
that dominates real keystrokes.  On 2 of 4 doc_1 pages the picked
target contained a line break, so `prepare_plan` exited at
`multiline_replacement` before any stream work (cold ≈ 0 ms, 0 stream
reads) — the stage rows for those pages still measured replay/bind
directly.

**Scope verdict for P3-B (the production slice):** Materialized ShowOp
table (Shape A), keyed by the digest-verified `IndexKey`
(pull-validation per §4; hooks only as eviction optimizations), owned
by the engine so the doc-setter reset inherits every doc-replacement
invalidation.  Shape B (checkpoints) is REJECTED for v1 on measured
evidence.  Candidate follow-ups for P3-B, in order: reuse one replay
across bind→plan within a single prepare (pure plumbing, no cache
semantics), then the per-generation table for the preview keystroke
loop.  A `__slots__` ShowOp would cut the dominant 1.1 KB/show — but
that is a production change owned by P3-B, not this spike.
