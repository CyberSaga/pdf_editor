# Task 13 P3-C — preview post-prepare latency (one complete bounded slice)

**Status:** COMPLETE — pushed 2026-08-23, PR not yet opened (created 2026-08-22)
**Branch:** `task13/p3c-preview-postprepare-latency` (cut from `task11/slice1-closure` post-PR-#36 merge, `f57f590`)
**Parent evidence:** `plans/task13-p3b-replay-reuse.md` §6b — after P3-B, warm `prepare_plan` is
p50 31 ms (replay-free), but warm end-to-end `PlanPreviewRenderer.render` stayed p50 ~3.3 s on the
dense synthetic page; that residual splice+verify+raster share was named the next P3 lever there,
deliberately not solved.

## 1. Goal

Attribute the residual post-prepare cost of one preview keystroke by phase, then remove the single
largest attributable phase without touching prepare, admission, or the live commit path. Scope is
explicitly the **preview renderer's** per-keystroke work (`PlanPreviewRenderer.render`) — the engine
commit path (`TieredCommitEngine.commit`, called once per accepted edit, not per keystroke) and the
engine's own scratch-proof path (`TieredCommitEngine.prepare`, confirmed below to be off the
interactive keystroke path entirely) are out of scope by name.

## 2. Hard fences

- No change to admission, the 4 MiB replay budget, plan semantics, or rollout defaults
  (`engine="legacy"`, `max_tier=0`).
- No change to `TieredCommitEngine.commit`'s live-document apply/revert (`engine.py:240,255,274`) or
  to `model/edit_commands.py`'s undo/redo `apply_patchset` calls — those mutate the document that
  will actually be saved, so their stream-storage encoding stays exactly as it is today.
- No change to `TieredCommitEngine.prepare`'s scratch-proof call (`engine.py:175`) — confirmed below
  to be off the interactive per-keystroke path in production; revisiting it is a separate decision.
- No new caching layer, no persistence, no admission widening. Verify's V0a–V0e post-conditions and
  `apply_patchset`'s fingerprint/digest staleness gates are unchanged in substance — only how the
  *storage encoding* of an already-decided splice is written may change, and only for a target whose
  bytes are never read back as a serialized artifact.
- R1 (simple-font capability staleness, P3-B review) stays out — already registered, prepare-path,
  unrelated to this slice.

## 3. Census (2026-08-22, `.venv` PyMuPDF 1.27.1)

### 3.1 Confirming the interactive call graph

`controller/text_commit_coordinator.py` calls only `PlanPreviewRenderer.render()` per keystroke.
Its result's `PreparedEdit` (`result.prepared`) is injected directly into the engine's verified-
candidate cache via `PDFController._consume_plan_preview` → `self.model.cache_verified_candidate`
(`controller/pdf_controller.py:3736`) — `TieredCommitEngine.commit()` prefers that cached candidate
at actual accept time and skips re-preparing when it's usable.

**Correction (P3-C adversarial review, 2026-08-22):** the first-pass census claimed
`engine.prepare()`'s scratch-apply (`engine.py:175`) "has no production caller on the interactive
path (only benchmark/spike scripts call it)" — **that is false.** `model/pdf_text_edit.py:1734`
(`_attempt_tiered_commit`) calls `engine.prepare()` in production whenever the verified-candidate
cache misses at accept time: an explicit style override or a user-dragged `new_rect` (the same-page
move flow, `controller/pdf_controller.py:2591-2602`, always supplies one) forces `cached = None`
(`pdf_text_edit.py:1694-1705`), a target/replacement framing drift does the same
(`pdf_text_edit.py:1706-1715`), and the cache is bounded (`engine.py:100-103`, LRU eviction). None of
these is per-keystroke — they all fire once at the moment a candidate is actually accepted, which is
the correct scope boundary: `engine.prepare()`'s scratch-apply (including its own compressed
`apply_patchset`, `engine.py:175`) is a genuine production cost, just not a keystroke-multiplied one,
so it stays out of this slice by the *once-per-accept* argument, not by nonexistence. Revisiting it
(the same `compress=False` trick would help the move-flow / restyle-at-accept path too) is a
reasonable follow-up, not part of this slice.

### 3.2 Phase attribution (ad hoc instrumentation, no production code changed; dense synthetic
page reused verbatim from `scripts/benchmark_p3b_preview_reuse.py::_build_doc(dense=True)`,
2,621,460 decoded bytes; 30 warm keystrokes after one warming prepare; span resolution hoisted out
of every timed section, closing P3-B review finding #2)

| phase                 | p50 (ms) | share of total p50 |
|------------------------|---------:|--------------------:|
| prepare (warm)          |    11.3  |   1.3% |
| capture_page_state      |    68.1  |   7.8% |
| **apply_patchset**      | **338.7**| **38.7%** |
| verify                  |    98.8  |  11.3% |
| final preview pixmap    |    29.1  |   3.3% |
| **revert**              | **322.0**| **36.8%** |
| **total**               |   874.4  | 100% |

`apply_patchset` + `revert` = **75.5%** of total render time — each is exactly one
`fitz.Document.update_stream()` call on the page's ~2.5 MiB content stream (one to splice the
replacement in, one to restore the prior bytes so the next keystroke sees the unmodified scratch).

### 3.3 Root cause

`Document.update_stream(xref, stream, new=1, compress=1)` — `compress` defaults to `True` and pays
FlateDecode compression proportional to the stream's decoded size. Microbenchmark on an isolated
2.6 MiB stream: `compress=1` median 307 ms vs `compress=0` median 0.57 ms (~540×). Verified
empirically: `xref_stream()` (decoded bytes) is byte-identical regardless of `compress`; the flag is
a pure storage-encoding choice, never observed by any downstream reader (`page_fingerprint`, the
P3-B evidence digest, `page.get_text()`, `page.get_pixmap()` all operate on decoded content).

**This is safe to disable *only* where the written bytes are never serialized to a persisted
artifact.** `PlanPreviewRenderer`'s scratch document (`preview.py:251`, opened once per session from
`snapshot_bytes`) is never saved or `tobytes()`'d after a splice — every keystroke's `apply_patchset`
is immediately followed by `.revert()` inside the same `render()` call
(`preview.py:330-361`), and `close()` (`preview.py:379`) just calls `scratch.close()`. No code path
serializes the scratch's stream storage encoding to anything the user or the live document ever sees.
`TieredCommitEngine.commit()`'s live-document write is the opposite case — its output *is* what gets
saved — so it keeps `compress=True`, unchanged.

Re-measured with `compress=0` forced on both calls (simulated, no production code changed yet):
`apply_patchset` 338.7→7.3 ms, `revert` 322.0→0.9 ms, **total 874.4→184.2 ms (4.75× on this
corpus)**. Residual phases (`capture_page_state` 57.2 ms + `verify` 87.3 ms + `final_pixmap` 25.3 ms
≈ 92% of the new total) are dominated by three `page.get_pixmap()` calls per keystroke (pre-state,
post-verify, final preview raster) plus repeated `page.get_fonts(full=True)` scans (6.1 calls/
keystroke) — named as the next P3 lever, deliberately not touched here (see §6).

## 4. Design

- `apply_patchset(doc, page, patchset, *, compress: bool = True) -> AppliedPatch` — thread `compress`
  through to each `doc.update_stream(stream_xref, new_bytes, compress=compress)` call. Default
  preserves today's behavior for every existing caller (`engine.py`, `edit_commands.py`, benchmark
  scripts, the whole test suite) with zero call-site changes required outside `preview.py`.
- `AppliedPatch.revert(doc, *, compress: bool = True) -> None` — same treatment, independently
  settable at the revert call site (matches how `apply_patchset`'s `compress` is settable at the
  apply call site; a caller reverting on a different document/path than it applied to is free to
  choose differently, though no current caller does).
- `PlanPreviewRenderer.render()` (`preview.py:330,361`): the only two call sites in the codebase that
  pass `compress=False`, both on the session-scoped scratch. One-line comment at each site records
  *why* (never serialized) so a future reader does not "fix" it back to the default.
- No new parameters on `prepare_plan`, `PatchSet`, or anything upstream of `apply_patchset` — the
  splice bytes and validation logic are completely unchanged; only the storage encoding of an
  already-decided write differs.

## 5. Test matrix (red first — new file `test_scripts/test_text_commit_apply_compress.py`)

A. `apply_patchset` contract: `compress=False` produces decoded bytes identical to `compress=True`
   for the same patchset (byte-for-byte `xref_stream()` equality); the stream's raw (on-disk-shape)
   representation is smaller under `compress=True` than `compress=False` (proves the flag actually
   took effect, not a no-op); default (`compress` omitted) behaves exactly as `compress=True`
   (backward-compatible default, existing callers unaffected).
B. `AppliedPatch.revert` contract: same identity + default-equivalence pair for revert; a
   compress=False apply followed by a compress=False revert round-trips to decoded-byte-identical
   original content (splice+revert stays exact, matching the P3-B module docstring's exactness
   guarantee — preview's plan token must still equal a fresh cold prepare's token afterward).
C. Cross-cutting correctness: `page_fingerprint` / the P3-B `ReplayEvidenceKey` digest are identical
   regardless of the compress state a stream happens to be stored in (digests hash decoded bytes,
   never storage encoding) — a mutation-detection regression test proving compress state itself
   is never mistaken for a content change.
D. Preview integration (extend `test_scripts/test_text_commit_preview_parity.py` or the P3-B replay-
   reuse matrix, whichever the red run shows is the natural home): `PlanPreviewRenderer.render()`'s
   observable outputs (`plan_token`, `png_bytes`, `prepared`, `reject_reason`) are byte-identical
   between the shipped (`compress=False`) code and a `compress=True` control run of the same
   keystroke sequence — proves the optimization changes nothing a caller can observe. A count-based
   regression gate (the `_ReplayCounter`-style pattern): install a shim counting
   `fitz.Document.update_stream` calls by their resolved `compress` value; assert every
   `PlanPreviewRenderer.render()` call makes exactly 0 `compress=True` update_stream calls and
   exactly 2 `compress=False` calls (apply + revert) for an accepted Tier 0 candidate, while a
   parallel `TieredCommitEngine.commit()` scenario on the live document continues to make its
   existing `compress=True` calls unchanged (regression guard against accidentally flipping the
   live path).
E. Memory bound: repeated preview keystrokes show the scratch's stored content-stream
   representation (`xref_stream_raw` length, the actual C-side storage PyMuPDF reports — NOT
   `tracemalloc`, which only traces the Python heap and cannot see MuPDF's C-side `fz_buffer`, so it
   could pass vacuously while the C-side representation grew unbounded) is IDENTICAL after every
   keystroke — a one-time expansion, replaced in place, never an accumulation.

## 6. Step list

1. [x] Census: call-graph confirmation + phase attribution + root-cause microbenchmark (§3).
2. [x] Red matrix committed with failing log (`test:` — 10 red / 2 guard-pins).
3. [x] `compress` plumbing through `apply_patchset`/`AppliedPatch.revert` + `preview.py` call sites,
   green (`feat:`).
4. [x] Adversarial review (deep-reasoner attack pass); findings fixed (`fix:` — F1–F6, see §8).
5. [x] Latency/count acceptance harness + measured record (`perf:` — §6b).
6. [x] Docs seal: ARCHITECTURE / PITFALLS / TODOS (`docs:`), push (no PR unless asked).

## 6b. Acceptance record (2026-08-23, `scripts/benchmark_p3c_postprepare_latency.py`)

Synthetic deterministic corpus (same generator shape as P3-B's harness: 401-show page padded with
raster-free `q/cm/Q` tokens to ~2.5 MiB decoded, within the 4 MiB budget), `.venv` PyMuPDF 1.27.1.
Raw aggregate JSON: gitignored `benchmarks/p3c-acceptance-2026-08-23.json`.

**Compress-count contract (the gate) — all PASS:** cold render = 0 compressed / 2 uncompressed
`update_stream` calls; 30 warm keystrokes = 0 compressed / 60 uncompressed calls total (2 per
keystroke, 30/30 accepted); live `TieredCommitEngine.commit()` = 1 compressed / 0 uncompressed calls
(the regression guard — the live path is provably untouched).

**Structural memory bound — PASS:** 100 keystrokes on a small page hold the scratch's stored
content-stream representation (`xref_stream_raw` length) at exactly one distinct size throughout —
no accumulation, measured on PyMuPDF's own reported C-side storage (not `tracemalloc`, which the F2
review finding showed is blind to it).

**Latency (informational, NOT a gate; synthetic page, this machine; span resolution hoisted out of
every timed section per the P3-B review's finding #2):** cold render 5,227.7 ms (replay-dominated,
comparable to P3-B's cold-prepare figure) vs warm render p50 267.3 ms / p95 315.6 ms — down from this
slice's own pre-fix census baseline of p50 874.4 ms on the same corpus shape (§3.2), a ~3.3× warm
render speedup from removing FlateDecode compression on the two scratch-only stream writes alone.
The remaining ~267 ms is the named next lever (§7): three `page.get_pixmap()` calls and six
`page.get_fonts(full=True)` scans per keystroke, not touched here.

## 7. Open questions

- Does disabling compression change the scratch document's own internal xref/object-stream layout
  in a way that could shift *other* xrefs (page tree, fonts) between keystrokes, which downstream
  fingerprint/digest logic might misread as structural change? **ANSWERED — no**, with one
  correction from the adversarial review (2026-08-22): every OTHER object (page tree, fonts,
  `xref_length()`) is identical before vs. after a `compress=0` apply+revert round trip. The content
  stream's own object dict is **not** restored to its original encoding — since `revert` also passes
  `compress=False`, the stream stays permanently uncompressed (no `/Filter` key) after the first
  keystroke for the rest of the session; only its DECODED bytes are restored exactly. This is safe
  (nothing in this codebase reads a content stream's storage encoding — see §3's root-cause
  paragraph) but the original wording here ("restored exactly by revert") overclaimed; corrected
  after `test_apply_then_revert_compress_false_leaves_non_stream_objects_unchanged` was found to
  omit checking the one object that actually changes. See
  `test_revert_compress_false_does_not_restore_original_storage_encoding` for the pinned invariant.
- Named next lever (not solved here): `capture_page_state` + `verify` + `final_pixmap`'s three
  `page.get_pixmap()` calls and six `page.get_fonts(full=True)` scans per keystroke, ~92% of the
  post-fix total. Numbers above are pre-fix census baselines for whoever picks this up next.

## 8. Decisions & dead ends (running log)

- 2026-08-22: Confirmed via `pdf_controller.py`/`text_commit_coordinator.py` reading that
  `TieredCommitEngine.prepare()`'s own scratch-apply never runs on the interactive PER-KEYSTROKE
  path — ruled out of scope by evidence, not by branch-name convention. **Corrected 2026-08-22
  (adversarial review):** it DOES run in production, once per accepted edit on a verified-candidate
  cache miss (`pdf_text_edit.py:1734`) — see §3.1's correction. Out of scope by the once-per-accept
  argument, not by nonexistence.
- 2026-08-22: Considered compressing only on `close()`/session teardown instead of leaving every
  keystroke uncompressed — rejected: the scratch is never read back as a serialized artifact at any
  point in its life, so a compress-on-teardown step would be pure wasted work with no reader.

### Adversarial review round (2026-08-22, deep-reasoner attack pass)

One attack pass, 6 findings (1 high, 1 medium-high, 1 medium, 3 low/low-medium), all independently
verified before fixing (Findings 1 and 3 by direct empirical re-probe; the rest accepted on the
attack's own executed evidence — file:line citations and probes, not assertions):

- **F1 (high):** §7's original "restored exactly by revert" claim was false for the shipped
  combination (revert also passes `compress=False`) — the content stream's own object dict stays
  permanently uncompressed post-revert; only decoded bytes are restored exactly. The companion test
  omitted checking the one object that changes. Fixed: §7 corrected; test renamed
  (`test_apply_then_revert_compress_false_leaves_non_stream_objects_unchanged`, scoped to what it
  actually proves) plus a new test pinning the true invariant
  (`test_revert_compress_false_does_not_restore_original_storage_encoding`).
- **F2 (medium-high):** the memory test used `tracemalloc`, which only traces the Python heap —
  blind to the uncompressed stream's actual storage in MuPDF's C-side `fz_buffer`, so it could pass
  vacuously under a real C-heap accumulation regression. Fixed: replaced with a structural assertion
  directly on PyMuPDF's reported storage (`xref_stream_raw` length identical across 21 keystrokes —
  `test_repeated_preview_keystrokes_stream_storage_stays_single_representation`).
- **F3 (medium):** §3.1's claim that `engine.prepare()`'s scratch-apply "has no production caller...
  only benchmark/spike scripts call it" was false — see the §3.1/§8 corrections above. The scope
  conclusion (out of this slice) survives on the correct argument (once-per-accept, not per-keystroke).
- **F4 (medium-low):** the two default-compress-equivalence tests compared raw stream LENGTH, not
  bytes — a weaker proxy than necessary. Fixed: both now compare `xref_stream_raw()` bytes directly.
- **F5 (low-medium):** mismatched apply/revert `compress` pairs (legal by the API, argued safe, but
  untested) and a latent footgun (a future live-document caller reverting with `compress=False`
  would permanently decompress it). Fixed: two new round-trip tests for both mismatched pairs
  (`test_mismatched_compress_apply_true_revert_false_still_round_trips` and its inverse); strengthened
  `AppliedPatch.revert`'s docstring with the live-document warning.
- **F6 (low):** the render-pipeline-identity test hand-replicated `render()`'s internals rather than
  calling it, and had drifted from the real clip/verify-verdict logic. Fixed: renamed the hand-built
  version to `test_render_primitives_output_identical_between_compress_true_and_false` (kept as a
  cheap primitive-level sanity check) and added
  `test_preview_renderer_output_identical_between_compress_true_and_false`, which drives the REAL
  `PlanPreviewRenderer.render()` twice, monkeypatching both scratch-only call sites to force
  `compress=True` for the control run.
- Also fixed: a stale `PlanPreviewRenderer` docstring claiming the scratch "stays byte-identical to
  the session snapshot" (now correctly scoped to decoded bytes).

Matrix after fixes: 16/16 green (12 original + 4 new: F1's extra pin, F5's two mismatched-pair
tests, F6's real-renderer test; F2's and F6's other fixes were renames/rewrites of existing tests,
not additions). Ruff + mypy clean.
