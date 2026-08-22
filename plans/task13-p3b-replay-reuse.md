# Task 13 P3-B — production replay reuse (one complete bounded slice)

**Status:** IN PROGRESS (created 2026-08-22)
**Branch:** `task13/p3b-replay-evidence-plumbing` (cut from `task11/slice1-closure` post-PR-#35 merge, `e71b13e`)
**Parent evidence:** `plans/task13-p3a-replay-index-spike.md` (Shape A selected; invalidation contract §4; measured replay ≈ 90% of dense prepare cost, warm validated lookup 8–14 ms vs 2.7–4.8 s cold on the standalone spike path).

## 1. Goal

Within one preview session / page content generation, later keystrokes must not
pay a full `replay_page_streams` walk again — and a cache hit must be provably
incapable of using stale replay evidence, with memory bounded by construction.

Concretely, per the P3-A record:

- `prepare_plan`'s accepted path today reads the page's decoded content
  streams **3×** (bind at `plan.py:315`, the direct `streams` dict at
  `plan.py:517-519`, `page_fingerprint` at `plan.py:522`) and replays every
  keystroke (~2.7 s median on dense corpus pages, ~90% of the bill).
- After this slice: **one read + at most one replay per prepare**, and for
  the preview keystroke loop (`PlanPreviewRenderer.render`), **zero replays
  on a validated warm hit** — the retained Shape A object is the production
  `PageReplay` verbatim.

Acceptance is stated in replay counts, not milliseconds: cold = 1 replay,
validated warm = 0, post-mutation = 1, false cache hits = 0.

## 2. Hard fences (unchanged from P3-A verdict)

- `DEFAULT_MAX_REPLAY_BYTES` (4 MiB) neither raised nor disabled; over-budget
  pages stay refused verbatim, and refused/malformed replays are **never**
  wrapped into retainable evidence (production analog of spike pin F4).
- No admission widening, no plan-semantics change: the rejection surface and
  gate order of `_classify_common` are byte-identical (pinned by the 19
  structural-gate tests).
- No persistent cache across save/reopen; no document-wide cache; no Shape B,
  no checkpoint replay, no `__slots__` `ShowOp`, no `page_fingerprint`/render/
  font-capability caches; rollout defaults stay `engine="legacy"`, `max_tier=0`.
- Push hooks remain eviction-only concepts; **freshness is proven exclusively
  by lookup-time pull-validation** (fresh read + digest compare) per P3-A §4 —
  the four unsignalled mutation classes make anything else unsound.
- The existing staleness layers are not replaced: `apply_patchset` still
  re-fingerprints fresh at apply time; `verify.py` still reads fresh.

## 3. Design

### 3.1 New module `model/text_commit/evidence.py` (pure; no fitz import)

- `ReplayEvidenceKey` (frozen): `page_xref`, ordered `stream_xrefs` tuple,
  per-stream sha256 `stream_digests` of the decoded bytes — exactly the P3-A
  §4 key. Digest (not xref identity) is load-bearing: freed xref numbers can
  be reused (mutation class 4).
- `ReplayEvidence` (frozen, retainable): `key` + `replay: PageReplay`.
  Construction **raises** on a refused or malformed replay — fail-closed;
  a refusal can never become warm evidence.
- `PageStreamSnapshot` (frozen, ephemeral): one prepare's ordered
  `(xref, decoded_bytes)` read plus its computed key. Built only by
  `inspect.capture_page_streams` (the ONE read per prepare).
- `resolve_replay(snapshot, cached) -> ResolvedPageStreams`: re-compares
  `cached.key == snapshot.key` itself (never trusts the caller's lookup) —
  hit reuses `cached.replay` with zero replay work; miss replays the
  snapshot bytes under the default budget and wraps clean results into new
  evidence (`None` evidence when refused/malformed).
- `ReplayEvidenceCache`: **single-slot**, session-scoped, not thread-safe
  (same contract as `PlanPreviewRenderer`). `lookup(key)` / `store(evidence)`
  / `clear()`, plus `hits`/`misses`/`stores` counters and `entry_count` for
  acceptance observability. Bounded eviction is replacement: storing drops
  the previous entry; memory bound ≈ one Shape A page (~0.78–1.19 MB dense).

The snapshot's key is computed from the **fresh bytes just read** — that IS
the pull-validation: every warm hit has already paid `page.get_contents()` +
`xref_stream` + sha256 before it may reuse anything.

### 3.2 Plumbing (all callers, cache or not)

- `inspect.capture_page_streams(doc, page) -> PageStreamSnapshot`.
- `bind_source_text(..., resolved: ResolvedPageStreams | None = None)`:
  when given, binds against the resolved streams/replay instead of reading +
  replaying itself. Gate order preserved (empty-streams check still first;
  refusal/malformed propagation verbatim).
- `page_fingerprint(doc, page, *, streams=None)`: the stream portion may be
  fed from the snapshot; every non-stream dependency (fonts, MC closure,
  geometry, annots/widgets) is always read fresh. `apply_patchset`/verify
  call sites keep the no-kwarg fresh-read form.
- `_classify_common(..., evidence_cache=None)`: after the cheap early gates
  (which must keep paying zero stream reads), capture the snapshot once,
  resolve against the cache, store new clean evidence, and feed the same
  snapshot to bind, the `streams` dict, and the fingerprint stream portion —
  the three P3-A-census read sites collapse to one coherent read.
- `prepare_plan(..., evidence_cache: ReplayEvidenceCache | None = None)`.
  `prepare_tier0_plan` keeps its signature (still gains read-once).

### 3.3 Ownership (bounded by construction)

- `PlanPreviewRenderer` owns one `ReplayEvidenceCache` (single slot = the
  current page generation of its one scratch page); `render` passes it to
  `prepare_plan`; `close()` clears it. Session close releases the retained
  `PageReplay`.
- `TieredCommitEngine.prepare` stays **ephemeral only** (no cache argument):
  the per-keystroke latency lives in the preview path; the engine keeps
  exactly today's behavior. Revisiting an engine-side bounded cache is a
  separate decision, deliberately out of this slice.

## 4. Test matrix (red first — `test_scripts/test_text_commit_replay_reuse.py`)

A. Evidence contracts: key composition; refused/malformed replay refuse
   wrapping (ValueError); resolve hit/miss/stale semantics incl. replay-call
   counts and object identity; single-slot cache semantics + counters.
B. Read-once plumbing: accepted `prepare_plan` performs exactly one decoded
   read per content stream (red: 3 today); cold cache/no-cache/warm
   `PreparedEdit` field-by-field equality; `page_fingerprint(streams=...)`
   equivalence + sensitivity; `bind_source_text(resolved=...)` equivalence
   and verbatim refusal propagation.
C. Reuse + invalidation: warm hit = 0 replays; missed-hook direct
   `doc.update_stream` (no signal) → digest mismatch → rebuild, never reuse;
   /Contents identity sweep (bytes changed, xref replaced same bytes,
   reordered, added, removed) → all MISS; non-replay mutations (/Rotate,
   annotation) → replay HIT while fingerprint stays fresh; mutation-after-
   lookup → `apply_patchset` still raises `StalePlanError`; over-budget and
   malformed pages cache nothing; engine.prepare stays ephemeral.
D. Memory: repeated keystrokes keep entry_count == 1; replaced/cleared
   `PageReplay`s become unreachable (weakref + gc); close releases.

## 5. Step list

1. [x] Context: seam mapped (`plan.py` 3-read census confirmed at source level).
2. [x] Red matrix committed with failing log (`test:` — 33 red / 3 guard-pins).
3. [x] Evidence module + plumbing green (`feat:` evidence plumbing).
4. [x] Preview session reuse green (`feat:` session-scoped Shape A reuse).
5. [x] Adversarial review (serial attack → verify) findings fixed (`fix:` — R1–R4, see §7).
6. [ ] Latency/memory acceptance harness + measured record (`perf:`).
7. [ ] Docs seal: ARCHITECTURE / PITFALLS / TODOS (`docs:`), push.

## 6. Open questions

- Does the preview splice+revert round trip restore byte-identical stream
  bytes (⇒ next keystroke hits) or re-encode (⇒ digest miss, correct but
  cold)? **ANSWERED — byte-identical.** The matrix's
  `test_preview_warm_keystroke_replays_zero_times` and the acceptance
  harness's 30-keystroke warm loop (30/30 cache hits, 0 replays) both
  prove consecutive renders hit through the splice+revert cycle.
- Engine-side bounded cache: deferred, see §3.3.

## 7. Decisions & dead ends (running log)

- 2026-08-22: Two-object design (ephemeral `PageStreamSnapshot` + retainable
  `ReplayEvidence`) chosen over a single evidence object carrying stream
  bytes: the retained footprint must stay ≈ Shape A (~1 MB dense), not the
  ~2–3.5 MiB decoded stream bytes, and every warm lookup re-reads fresh bytes
  anyway (pull-validation), so retaining bytes buys nothing.
- 2026-08-22: `resolve_replay` re-validates key equality itself so a buggy
  cache handing back wrong-keyed evidence cannot cause a false hit.
- 2026-08-22: snapshot capture placed AFTER the cheap early gates —
  early-rejected prepares keep paying zero stream reads (today's behavior).

### Adversarial review round (2026-08-22, serial attack → verify workflow)

One attack pass (4 findings: 2 important, 2 minor); the top 3 verified
serially by independent refute-first agents, all 3 CONFIRMED with executed
probes; the 4th confirmed by hand. All fixed before the `perf:` commit:

- **R1 (important, = attack F1):** the review-prompt invariant "capability
  recomputed fresh every prepare" overreaches — `DocumentFontRegistry`
  serves cached *simple-font* capabilities with no per-lookup revalidation
  until `bump_generation` (Type0 is digest-revalidated; `fonts.py:546-559`).
  **Pre-existing engine-path behavior, NOT introduced by P3-B**, unreachable
  in preview (private scratch, splice+revert only) — and rewriting the
  registry is explicitly outside this slice's fences. Fixed in-scope: the
  missing fonts-mutation matrix test was added
  (`test_font_object_mutation_hits_replay_but_fingerprint_stays_fresh`:
  replay HIT + fingerprint fresh, so the apply-time gate still fires), and
  the registry revalidation follow-up is recorded in TODOS.md.
- **R2 (important, = F2):** two regression-permeable matrix assertions —
  the /Rotate test guarded its load-bearing freshness pins behind
  `if isinstance(...)` (probe confirmed the post-/Rotate prepare accepts, so
  hard-asserting is safe), and the second-target preview test never asserted
  the second render succeeds (an early-gate rejection also yields 0
  replays). Both hardened.
- **R3 (minor, = F3):** `ReplayEvidence.__post_init__` could wrap (a) a
  diagnostic-unbounded replay of an over-budget page (refusal collapses on
  warm hits only — probe demonstrated it) and (b) a key/replay mis-pairing
  with the right key. Fixed: `PageReplay` now records the budget it ran
  under (`max_decoded_bytes`, `compare=False` — provenance metadata, not
  replay semantics, so every existing equality pin holds), and the
  constructor refuses `None`-budget replays and
  `key.stream_xrefs != replay.stream_xrefs`. Residual (documented, accepted):
  same-xrefs-different-bytes forgery is undetectable without retaining
  digests inside `PageReplay`; Python cannot stop deliberate forgery — the
  constructor now enforces the module's own posture, no more.
- **R4 (minor, = F4):** an empty-`/Contents` page replayed `[]` and stored
  empty-key evidence into the slot (pre-change: NO_MATCH with zero replay
  work, no store). Fixed: `_classify_common` short-circuits to the verbatim
  `NO_MATCH` / "page has no content streams" rejection before resolve/store;
  pinned by `test_empty_contents_page_rejects_without_replay_or_store`.

Matrix after fixes: 40/40 green (36 original + 4 new pins), replay/guard/
spike/gates/tier0/preview/lexer/mc suites green, ruff + mypy clean.
