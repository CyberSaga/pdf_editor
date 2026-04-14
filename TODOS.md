# TODOS

## In Progress (2026-04-14) -- F1 object manipulation v2

- What: Expanded the F1 object layer from v1 textboxes/rectangles into a first-class `objects mode` with visible entry points, same-page multi-select, resize handles, and app-inserted image objects.
- Why: The backlog needs a clean separation between browse text selection, object manipulation, and text edit mode, and the app-owned image path is the safest place to grow next.
- Outcome: Focused request/model/controller/view tests are green, the GUI slices are green, and the mixed-sample GUI verification still passes. The remaining F1 follow-up is native-PDF image manipulation, which stays intentionally separate from app-owned image support.

## Future F1 Follow-Ups

- Native PDF image manipulation:
  - Later: selecting/manipulating existing (native) PDF image XObjects.
- Any remaining F1 polish that needs its own child plan.

## Notes on `objects mode`

- Treat `objects mode` as a separate interaction mode from browse mode and text-edit mode.
- Browse mode keeps its text-selection behavior and should not accidentally start moving objects.
- Objects mode should focus on selecting/manipulating objects:
  - Supported now: rectangles and app-inserted images.
  - Textboxes stay in text-edit mode.
- Text edit mode focuses on textboxes:
  - Supported: move/rotate/delete/resize/multi-select textboxes, plus editing words.
- The same object identity layer stays shared across the object and text-edit paths.

## Done (2026-04-13) -- Close B4 performance campaign

- What: Closed `B4` after the optimize-copy and open/page-change slices shipped and the final before/after evidence was captured in the tracker and performance plan.
- Why: The backlog explicitly required measured wins, not just profiling, before `B4` could close.
- Outcome: Startup/import+instantiate is down to about `0.193s` from the `0.444s` baseline, UI-path open on `2024_ASHRAE_content.pdf` now reaches initial high-quality visible page at about `73ms` and far-page jump at about `222ms`, and large optimize-copy now completes in the tens of seconds instead of timing out past the original probe window.

## Done (2026-04-13) -- B4 Slice 2 open/page-change responsiveness

- What: Changed the controller open path so full-page placeholders still appear immediately, but thumbnail raster batches and sidebar scans wait until the initial visible page reaches high quality or a short fallback timer expires. Also coalesced repeated visible-render scheduling so page changes and viewport updates stop restarting the render queue on every tick.
- Why: After the optimize-copy slice, the next best B4 move was making the document feel ready sooner in the real UI path. The existing controller already had batched rendering and caching, but it still spent early open time on background work and allowed redundant render scheduling churn during navigation.
- Outcome: `test_scripts/benchmark_ui_open_render.py` now measures `test_files/2024_ASHRAE_content.pdf` at startup-to-placeholders ~534.9ms, initial high-quality page ready ~78.1ms, and far-page jump to page 483 high-quality ready ~268.7ms. The startup controller regression suite now locks in visible page first, background work later plus visible-render coalescing.

## Done (2026-04-12) -- B4 Slice 1 preset-aware optimize-copy performance

- What: Added explicit execution profiles for the three optimize-copy presets so speed-first skips content cleanup/font subsetting and avoids the slower extracted-image parallel fallback, balanced keeps the heavier pipeline for small jobs but downgrades cleanup on large jobs, and compression-first preserves the full path.
- Why: The first measured `B4` hotspot was large-file optimize-copy, not open or page-change. The old implementation used nearly the same expensive pipeline for all presets, which left too much latency on the table for the speed-first and balanced modes.
- Outcome: Large-file optimize-copy on `test_files/2024_ASHRAE_content.pdf` now measures about `15.6s` for speed-first, `20.4s` for balanced with about `37.9%` saved, and `23.2s` for compression-first with about `57.8%` saved. `B4` remains open for open/page-change work, but the optimize-copy slice is now a shipped measured win.

## Done (2026-04-12) -- B4 baseline capture and performance-plan handoff

- What: Captured fresh baseline numbers for startup, synthetic large-file open, page render, repeated-edit latency, and a first optimize-copy sample, then wrote the dedicated `B4` child plan for closing performance with measured wins.
- Why: The backlog requires `B4` to stay open until we have both baseline evidence and shipped before/after improvements. We had planning placeholders, but not a concrete performance handoff with real numbers and hotspots.
- Outcome: `B4` is now `in_progress` instead of vague-open. The plan identifies large-file optimize-copy as the highest-risk hotspot on this machine, and the next step is shipping measured wins for open, page-change, and optimize-copy flows.

