# Phase R4 — Performance Deferrals

**Status:** Ready (after R3 coordinators land). **Fusion:** 3-model for cache/threading;
2-model for the mechanical items. **Why here:** these are real but each is narrower than a naive
reading suggests, and two are partially mitigated by existing infra. The snapshot-bytes-cache step
is sequenced **after** R3's coordinator extraction (it touches the same controller call sites).
(Census: performance lens; critique HAZARD 5.)

> **Implicit risks:** the overlay revision cache can serve **stale composites** if any mutation
> path forgets to bump its counter (~25 invalidation sites) — a correctness regression that *looks
> like success* in tests that don't assert overlay content. The snapshot cache key spans layers
> (revision on controller, bytes produced by model). Moving thumbnails to a `QThread` introduces
> stale-emission risk.

---

## R4.1 — Overlay raster cache with per-tool revision counters (3-model)

- **Current state (not "no cache"):** the controller already caches the final composited QPixmap
  in `_render_cache` keyed by `_render_revision` (`pdf_controller.py:857`). The residual cost is
  the **cache-MISS** path: `render_page_pixmap` overlay branch (`manager.py:88-99`) does
  `fitz.open()+insert_pdf(single page)+apply_page_overlay+get_pixmap` on the Qt main thread; and
  `_bump_render_revision` (L810) drops the **whole session cache** via
  `_invalidate_active_render_state` (~25 mutation sites, L1833-3305). So one annotation on page 5
  re-runs the full overlay pipeline for watermarked pages 1-4. `WatermarkTool`/`AnnotationTool`
  have no revision counter; `ToolManager` is stateless.
- **Fix:** add per-`(session,page)` revision counters on `WatermarkTool` and `AnnotationTool`
  (bumped in `add/remove/update_watermark` + annotation mutators), and a page-overlay raster cache
  on `ToolManager` keyed by `(session_id, page_num, scale, dpr, wm_revision, annot_revision)`.
  Invalidation: only the page whose overlay-owning tool bumped its counter is dropped — decoupling
  overlay invalidation from the controller's whole-session `_render_revision` bump.
- **Conditional:** win only exists when overlays exist; zero benefit on overlay-free docs.

## R4.2 — Revision-keyed worker snapshot-bytes cache (3-model, AFTER R3 coordinators)

- `capture_worker_snapshot_bytes` (`pdf_model.py:3200-3204`) does a full `doc.tobytes(...)` and is
  called independently by print (`:1657`), search (`:2557`), OCR (`:2690`). Search-then-OCR on an
  unedited doc serializes the same bytes twice.
- **Fix:** a bytes cache keyed by `(active_session_id, render_revision)`. **Ownership is the bug
  surface** — `_render_revision` lives on the controller, the bytes are produced by the model. The
  **controller** owns the cache (it knows the revision) and passes cached bytes into the (now R3-
  extracted) coordinator capture sites; invalidate on the same hook as `_bump_render_revision`.
- **Conditional:** only helps overlapping search/OCR/print on an unedited doc; invalidated by any
  edit. **Sequence after R3.2** so the cache wires into the coordinators, not soon-to-move code.

## R4.3 — Thumbnail rasterization → QThread worker (3-model)

- `_schedule_thumbnail_batch` (`pdf_controller.py:2904`) calls `model.get_thumbnail(...)`
  **synchronously** inside a `QTimer.singleShot` chain (THUMB_BATCH_SIZE=10/30ms). Only the
  *batching* is deferred — the rasterization (incl. the overlay `insert_pdf` path) runs on the Qt
  main thread, competing with page-view renders on big/watermarked docs.
- **Fix:** move rasterization to a `QThread` worker producing `QImage`/pixmap bytes, marshalled
  back via a bridge Signal (same pattern as `_SearchWorker`/`_OcrWorker`). The worker opens its own
  `fitz` over snapshot bytes (reuse R4.2's cache). The existing `_thumb_gen_by_session` token must
  be checked in the bridge or a cancelled tab's thumbnails paint over the new tab.
- **Conditional:** largest win on big/watermarked docs; small docs already finish in 1-2 ticks.

## R4.4 — Undo dedup coverage (2-model)

- `_dedup_top_snapshot_pair` (`edit_commands.py:585`) only compares `[-2]` vs `[-1]` and only when
  both are `SnapshotCommand`; `_unique_byte_total` (`:642`) dedups by `id()` so it counts shared
  bytes once **only** if already aliased by the top-pair dedup. Non-adjacent byte-identical
  snapshots (e.g. after a redo re-push) are double-counted against the 512 MiB budget.
- **Fix:** broaden dedup beyond the top pair (content digest over the stack, or a digest→bytes
  intern map), making `_unique_byte_total` exact. The deferred `memcmp-on-record` note (TODOS:21)
  is the cheaper-equality half; the larger residual is the limited *scope*.

## R4.5 — `快速` preset objstms flip (2-model)

- The default `平衡` preset already sets `use_object_streams=True` (`pdf_optimizer.py:80`);
  `極致壓縮` is structurally blocked (`linearize=True` forces objstms off via
  `normalize_optimize_options:250-252`). The **only** genuine opportunity is the `快速` preset
  (`:229`, `linearize=False`): flip `use_object_streams=False → True`.

---

## Fusion Protocol Playbook

- **R4.1 / R4.2 / R4.3:** Playbook **4.4** (3-model design — invalidation correctness + threading
  are non-local) before, **4.5** (3-model test-gap) after. fusion.py `--no-synthesize` for the
  cache-key design, `/codex:rescue` same prompt, synthesize:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "Design a per-(session,page) overlay raster cache with revision counters on WatermarkTool +
       AnnotationTool. Enumerate EVERY mutation path that must bump a counter (there are ~25
       _invalidate_active_render_state sites) and prove no path can serve a stale composite." `
      --file model/tools/manager.py --file model/tools/watermark_tool.py `
      --file model/tools/annotation_tool.py --file controller/pdf_controller.py --no-synthesize
  ```
- **R4.4 / R4.5:** Playbook **4.4** 2-model (mechanical, bounded).

## Verification & Gatekeeping

```powershell
# Behavioral correctness (cache must never change rendered output):
.venv\Scripts\python.exe -m pytest test_scripts/test_thumbnail_async.py test_scripts/test_undo_memory_budget.py -v
.venv\Scripts\python.exe -m pytest test_scripts/test_pdf_optimize_workflow.py -v       # R4.5 objstms
# Perf gating (before/after, same machine):
.venv\Scripts\python.exe test_scripts/benchmark_ui_open_render.py
# Invariant: render a watermarked page, mutate an unrelated page, assert the overlay raster is
# served from cache (cache-hit counter) AND pixel-identical to the pre-mutation render.
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider
```

**Gate:** every cache step needs a **pixel-identity** assertion (cached == uncached output) plus a
**staleness** assertion (mutate → counter bump → fresh render) — a hit-rate win that changes output
is a regression. Benchmark deltas recorded in the plan.

## Risk Triage (2→3 upgrade points)

- **R4.1/R4.2/R4.3 → 3-model** (trigger #3 concurrency/invalidation, and R4.3 trigger #3 thread
  marshalling).
- **R4.4/R4.5 → 2-model** (mechanical; no cache invalidation introduced, no threading).
- **Vectors:** missed counter bump (stale overlay); cross-layer cache-key ownership (stale/wrong-
  encryption doc to a worker); stale thumbnail emission painting over a switched tab.

## Docs (same commit)

- `docs/ARCHITECTURE.md §5`: ToolManager now holds an overlay raster cache + the per-tool revision
  contract; controller owns the snapshot-bytes cache.
- `docs/PITFALLS.md`: "overlay cache staleness — every mutator must bump its tool's revision";
  "snapshot-bytes cache key ownership spans layers".
- `TODOS.md`: mark Phase 4.3 overlay cache, snapshot-bytes caching, undo dedup digest, preset
  objstms items done.

## Commit

Per item: `perf: R4.<n> <item> (output-identical)`. `Co-Authored-By: Claude Fable 5
<noreply@anthropic.com>`.
