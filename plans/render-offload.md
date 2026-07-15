# M3 Tranche 3.6 — Render Offload

**Status:** Seeded by tranche 3.0 baseline; implementation planning deferred until tranche 3.6.

## Goal

Improve AC-FIX-01 startup/open responsiveness and AC-FIX-02 complex-vector rendering without stale/blank-page regressions. Preserve the immediate low-resolution first paint, then move expensive high-resolution rasterization off the Qt GUI thread using QThread + Signals.

## Scope fence

- In scope: primary-page raster scheduling, generation-token cancellation, render cache/profile/DPR correctness, complex-vector benchmark evidence.
- Out of scope: Acrobat-parity text commit engine; page-centering coordinate changes (separate `plans/continuous-centering.md` later in tranche 3.6); thumbnail rendering unless shared infrastructure requires a narrowly documented change.

## Affected modules

- `controller/pdf_controller.py` — `_render_page_into_scene`, `_render_gen_by_session`, `_render_cache`, profile-scoped page-quality map
- `controller/thumbnail_coordinator.py` — QThread/worker pattern to reuse
- `model/pdf_model.py` — `get_page_pixmap` and synchronous XREF-repair measurements
- `utils/render_limits.py` — existing 40 MP safety cap
- `test_scripts/benchmark_ui_open_render.py` — repeatable baseline and post-change measurements

## Baseline procedure (2026-07-15)


Each run starts a fresh application process in offscreen Qt mode. Run each command twice in sequence; record both values rather than assuming the second is faster, because OS file cache and vector-page complexity vary.

```text
 <python> test_scripts/benchmark_ui_open_render.py --path "<fixture-a>"
 <python> test_scripts/benchmark_ui_open_render.py --path "<fixture-b>" --timeout 120
```

| Fixture / run| Startup→placeholders | Initial high ready | Midpoint jump high ready | Jump total |
|---|---:|---:|---:|---:|
| fixture-a| 861.3 ms | 18.7 ms | 0.0 ms | 3.7 ms |
| fixture-a| 923.7 ms | 18.4 ms | 0.0 ms | 0.3 ms |
| fixture-b| 1252.6 ms | 56.8 ms | 81775.0 ms | 81991.4 ms |
| fixture-b| 1044.1 ms | 52.4 ms | 107254.7 ms | 107464.7 ms |

`initial_low_ready_ms=0.0` in all runs because the synchronous low-resolution render completed before the benchmark began waiting. This does not prove the GUI remained responsive; tranche 3.6 must add explicit event-loop responsiveness/busy-indicator checks from AC-FIX-02.

## Planned steps (execute in tranche 3.6 only)

1. Re-run the baseline and profile the complex fixture; identify whether high-resolution raster, XREF repair, or another stage dominates each path.
2. Write red-light tests for stale-result rejection, profile/DPR cache isolation, session switches, close-during-render, and event-loop responsiveness.
3. Introduce a QThread worker mirroring `controller/thumbnail_coordinator.py`; keep low-res first paint synchronous and submit high-res work with session/page/generation/profile/DPR identity.
4. Apply results only when all identity tokens still match; preserve existing page-quality and background-loading transitions.
5. Add tile/band rendering or complexity-aware scale caps only if worker offload alone misses the AC-FIX-02 target and profiler evidence identifies raster latency as the remaining bottleneck.
6. Re-run both fixtures; publish before/after numbers and memory observations.

## Open questions for tranche 3.6 design review

- Is page rasterization safe on an independently opened worker document for all current encrypted/dirty-session paths?
- Should dirty sessions use worker snapshot bytes, a serialized render request, or retain a bounded synchronous fallback?
- What is the exact timeout/cancellation policy when a tab closes or its color profile changes mid-render?
