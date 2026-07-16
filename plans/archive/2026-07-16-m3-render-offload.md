# M3 Tranche 3.6 — Render Offload

**Status:** Implemented and benchmarked on 2026-07-16; focused regressions green.

## Goal

Improve AC-FIX-01 startup/open responsiveness and AC-FIX-02 complex-vector navigation without stale, blank, cross-session, color-profile, or HiDPI regressions. Preserve the immediate low-resolution first paint, then move every non-immediate visible/prefetch raster off the Qt GUI thread using QThread + Signals.

## Scope fence

- In scope: primary-page raster scheduling, prefetch scheduling, generation-token cancellation, render cache/profile/DPR correctness, foreground priority over thumbnail rendering, and complex-vector benchmark evidence.
- Out of scope: Acrobat-parity text commit engine; page-centering coordinate changes (a separate tranche-3.6 plan); thumbnail output semantics except the narrow pause/resume required to stop full-document thumbnail work starving foreground page rendering.
- Runtime watermarks remain on the synchronous overlay-aware renderer because they are not baked into `doc.tobytes()`. This preserves correctness until overlay requests can be serialized independently.

## Affected modules

- `controller/page_render_coordinator.py` — immutable request/result identity and one-worker QThread ownership
- `controller/pdf_controller.py` — immediate-low path, worker dispatch/result acceptance, thumbnail foreground priority, close/switch cancellation
- `controller/thumbnail_coordinator.py` — reused identity/thread pattern; no output-format change
- `model/pdf_model.py` / `model/tools/manager.py` — existing synchronous reference path only
- `utils/render_limits.py` — existing 40 MP safety cap reused in the worker
- `test_scripts/test_page_render_coordinator.py` — new worker/coordinator/controller contract tests
- `test_scripts/test_render_clarity_dpr.py`, `test_scripts/test_worker_snapshot_cache.py`, `test_scripts/test_benchmark_ui_open_render.py` — regression controls

## Baseline procedure and evidence (2026-07-16)

Each run starts a fresh offscreen application process. Commands use the project interpreter:

```text
.venv\Scripts\python.exe test_scripts/benchmark_ui_open_render.py --path "test_files/test-colored-background.pdf" --timeout 30
.venv\Scripts\python.exe test_scripts/benchmark_ui_open_render.py --path "test_files/MIC-VB-HVAC-DWG-0001 空調系統設計圖說20260528-Bb版.pdf" --timeout 150
```

| Fixture / run | Startup→placeholders | Initial high ready | Midpoint jump high ready | Jump total |
|---|---:|---:|---:|---:|
| `test-colored-background.pdf` run 1 | 1789.8 ms | 267.4 ms | 864.3 ms | 931.3 ms |
| `test-colored-background.pdf` run 2 | 1652.8 ms | 243.4 ms | 798.7 ms | 867.7 ms |
| complex fixture run 1 | 2065.7 ms | 111.7 ms | 78055.2 ms | 78437.4 ms |
| complex fixture run 2 | 1841.1 ms | 104.1 ms | 80070.6 ms | 80426.7 ms |

`initial_low_ready_ms=0.0` in all runs because the immediate synchronous low-resolution render completes before the benchmark wait starts.

### Bottleneck profile

A worker-style direct profile of complex page 25 at scale 1.0 measured:

| Stage | Time |
|---|---:|
| file open | 11.8 ms |
| `doc.tobytes(...)` snapshot | 1092.7 ms |
| worker `fitz.open(stream=...)` | 9.1 ms |
| `page.get_displaylist(annots=True)` | 139.1 ms |
| display-list raster | 306.4 ms |

The source and worker documents both reported `is_repaired=False`; XREF repair is not the bottleneck.

A traced UI run with thumbnail startup disabled showed that page 25 low/high rendered in 376.9/406.3 ms, but the same GUI callback then synchronously rendered prefetched page 24 low quality for 8263.6 ms before the event loop could observe page 25 as ready. With the normal full-document thumbnail worker active, the midpoint jump rose to 78–80 seconds. Therefore the dominant defect is scheduling and foreground starvation, not page-25 high-resolution raster time itself:

1. `_process_visible_render_batch()` performs more than one MuPDF render in one GUI callback.
2. Low-quality prefetch can itself take seconds and still runs on the GUI thread.
3. Full-document thumbnail raster begins after initial high quality and competes with foreground page rendering.

The implementation must offload both high-quality renders and non-immediate low-quality prefetch, and must pause/resume thumbnail work around foreground visible rendering. Offloading only the high-quality page would leave the measured 8.3-second GUI-thread prefetch stall intact.

## Request ownership and identity

`PageRenderIdentity` is immutable and contains:

- globally unique token
- session id
- render generation
- render revision
- page index
- quality (`low` or `high`)
- rendered scale
- target logical scale
- normalized color profile
- device-pixel ratio

`PageRenderRequest` additionally owns immutable snapshot bytes. The GUI thread captures bytes through `PDFController.capture_worker_snapshot_bytes()` before `QThread.start()`. The worker opens its own `fitz.Document`, uses the requested page/profile/scale, and emits only a `QImage` plus identity. It never receives the live model document and never constructs a `QPixmap`.

The GUI accepts a result only when all identity fields still match the active session, current generation/revision/profile/DPR/scale, and page bounds. It converts `QImage` to `QPixmap`, applies DPR, stores under the existing render-cache identity, updates the page scene and quality map, and then schedules the next candidate.

## Dirty, encrypted, and overlaid sessions

- Dirty documents: snapshot bytes include current in-memory edits and annotations, so they use the same worker path.
- Encrypted documents: worker bytes are decrypted in memory by the existing snapshot contract. They are never written to disk or logged. Tab close drops the controller cache; worker/request references are released on completion.
- Runtime watermarks: snapshot bytes do not contain ToolManager overlays. Watermarked sessions use the existing synchronous overlay-aware renderer, one candidate per event-loop turn, rather than silently omitting watermarks.
- Snapshot capture cost: the complex fixture serializes in about 1.1 seconds. The revision-keyed cache keeps this to one capture per unchanged session; this remaining GUI-thread cost is recorded for post-change measurement.

## Cancellation and thread policy

- Exactly one page-render worker thread may rasterize at a time. A newer request cancels the active identity and replaces a single pending request; it never starts an overlapping page-render thread.
- Cancellation is cooperative before/after MuPDF calls. `get_displaylist()` / `get_pixmap()` are not assumed interruptible.
- A canceled worker may finish its current MuPDF call, but its result is rejected and it cannot start another page.
- Session switch, tab close, profile change, zoom rebuild, structural render-revision bump, and application close invalidate generation and cancel matching active/pending requests.
- No GUI close path waits indefinitely. The coordinator exposes a bounded `wait_for_done()` for final application teardown and keeps stale result rejection independent of worker stop timing.
- Foreground visible scheduling cancels the active thumbnail batch and records a resume request. Thumbnails restart only after visible/prefetch page candidates are exhausted; repeated viewport changes coalesce instead of creating worker storms.

## Red-light test matrix

1. Worker opens snapshot bytes and emits `QImage`, never `QPixmap`; profile and safe scale are honored.
2. Controller keeps immediate current-page low rendering synchronous but delegates high and non-immediate low/prefetch rendering without calling `model.get_page_pixmap()` inline.
3. Token, session, generation, revision, page, profile, scale, and DPR mismatches each reject a result.
4. Accepted high-DPR results set `QPixmap.devicePixelRatio()` and enter the existing cache under the matching key.
5. Worker failure leaves an existing low-quality page visible and ends the current batch without a retry loop.
6. Tab close/session switch cancels page rendering and drops that session’s snapshot cache; another session’s cache remains untouched.
7. Repeated requests keep at most one active worker and one latest pending request.
8. Foreground visible work cancels thumbnail rendering; thumbnails resume only after foreground candidates drain.
9. Watermarked sessions stay on the overlay-aware synchronous path.
10. A QTimer/event-loop control fires while a fake high render remains pending, proving controller dispatch itself does not perform raster work.

Live QThread coverage is limited to a small real-PDF worker smoke test. Identity, cancellation, controller marshalling, stale rejection, and responsiveness use synchronous worker execution or injected/fake coordinator seams to avoid the known Windows Qt test-suite instability from long live-thread render tests.

## Implementation steps

1. Add and run the coordinator/controller red tests.
2. Implement `controller/page_render_coordinator.py` with immutable dataclasses, QImage worker output, globally unique tokens, one active worker, and one latest pending request.
3. Split controller application from synchronous rasterization so cached/sync and worker results share one GUI-only apply path.
4. Keep only the explicitly requested immediate low render synchronous. Dispatch high and batch/prefetch low requests to the coordinator.
5. Add complete identity checks and cancellation at profile/zoom/session/close/revision seams.
6. Pause/resume thumbnail batches around foreground visible rendering.
7. Run focused rendering, thumbnail, DPR, worker-cache, rapid-switch, and multi-tab regressions.
8. Re-run both benchmark fixtures twice and record post-change timing plus close/tab-switch responsiveness.
9. Add tile/band rendering or a scale cap only if post-offload evidence still shows a single worker raster as the remaining bottleneck; do not add fixture-specific heuristics.

## Post-implementation evidence (2026-07-16)

| Fixture / run | Startup→placeholders | Initial high ready | Midpoint jump high ready | Jump total |
|---|---:|---:|---:|---:|
| `test-colored-background.pdf` run 1 | 490.0 ms | 100.1 ms | 78.5 ms | 97.8 ms |
| `test-colored-background.pdf` run 2 | 501.1 ms | 104.6 ms | 96.0 ms | 114.6 ms |
| complex fixture run 1 | 599.9 ms | 5268.0 ms | 180.5 ms | 292.7 ms |
| complex fixture run 2 | 604.5 ms | 5414.0 ms | 167.5 ms | 269.4 ms |

The complex midpoint interaction improved from 78.1/80.1 seconds to 180.5/167.5 ms (over 99% lower observed readiness latency). The initial low-quality page remains synchronous and visible before the benchmark begins waiting. Complex initial *high* readiness rose to about 5.3–5.4 seconds because the first unchanged-session worker request pays the full-document snapshot capture/open path before upgrading quality; this does not delay the immediate low first paint, but it is the principal remaining optimization target. The revision-keyed snapshot is reused after that first capture, which is why midpoint jumps are sub-300 ms total.

Focused verification after implementation:

```text
12 passed — test_page_render_coordinator.py
37 passed — page render, DPR, snapshot-cache, thumbnail, benchmark-helper, and color-profile regressions
108 passed, 1 skipped — startup, multi-tab, page-control, and structural-indexing regressions
ruff check — changed render/controller/tests clean
```

No tile/band renderer or fixture-specific scale heuristic was added: isolated page raster was not the measured bottleneck, and worker offload plus foreground scheduling exceeded the AC-FIX-02 responsiveness target.
