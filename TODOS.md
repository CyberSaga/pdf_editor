# TODOS

## Done (2026-04-12) -- B4 Slice 1 preset-aware optimize-copy performance

- What: Added explicit execution profiles for the three optimize-copy presets so `快速` skips content cleanup/font subsetting and avoids the slower extracted-image parallel fallback, `平衡` keeps the heavier pipeline for small jobs but downgrades cleanup on large jobs, and `極致壓縮` preserves the full compression-first path.
- Why: The first measured `B4` hotspot was large-file optimize-copy, not open or page-change. The old implementation used nearly the same expensive pipeline for all presets, which left too much latency on the table for the speed-first and balanced modes.
- Outcome: Large-file optimize-copy on `test_files/2024_ASHRAE_content.pdf` now measures about `15.6s` for `快速`, `20.4s` for `平衡` with about `37.9%` saved, and `23.2s` for `極致壓縮` with about `57.8%` saved. `B4` remains open for open/page-change work, but the optimize-copy slice is now a shipped measured win.

## Done (2026-04-12) -- B4 baseline capture and performance-plan handoff

- What: Captured fresh baseline numbers for startup, synthetic large-file open, page render, repeated-edit latency, and a first optimize-copy sample, then wrote the dedicated `B4` child plan for closing performance with measured wins.
- Why: The backlog requires `B4` to stay open until we have both baseline evidence and shipped before/after improvements. We had planning placeholders, but not a concrete performance handoff with real numbers and hotspots.
- Outcome: `B4` is now `in_progress` instead of vague-open. The plan identifies large-file optimize-copy as the highest-risk hotspot on this machine, and the next step is shipping measured wins for open, page-change, and optimize-copy flows.

## Done (2026-04-12) -- Make repeated-edit benchmark self-contained

- What: Fixed `test_scripts/test_performance.py` so it can import the repo modules when run directly from the repo root, and added a subprocess regression that proves the script works without a manual `PYTHONPATH` override.
- Why: The repeated-edit benchmark is part of the `B4` baseline path. A benchmark that only works with ad-hoc shell setup makes the performance campaign brittle and easy to mis-measure.
- Outcome: `python test_scripts/test_performance.py --rounds 1` now works as documented, and future profiling sessions can rely on it without hidden environment setup.

## Done (2026-04-12) -- Phase 5 context-menu improvements

- What: Added thumbnail right-click page operations and expanded the browse-mode scene context menu with richer page/file actions, all routed through shared page-specific helper methods in the view.
- Why: The backlog called for higher-utility right-click flows after print parity, and the app already had the underlying delete/rotate/export/insert signals; it just lacked page-aware context-menu entry points.
- Outcome: Phase 5 is now closed. Thumbnails expose direct page operations, and the main browse context menu now surfaces current-page export/rotate/delete/insert plus file actions like Save As, Print, and optimized copy.

## Done (2026-04-11) -- Fix custom landscape PDF output orientation on raster print

- What: Fixed the Qt raster print bridge so custom source-sized landscape pages no longer serialize as portrait pages in PDF output.
- Why: Qt expects custom `QPageSize` dimensions in portrait order and applies orientation separately. We were passing already-landscape dimensions plus `Landscape`, which flipped A3 landscape source pages back to A3 portrait in the generated PDF.
- Outcome: Mixed jobs now keep pages 13-15 landscape for the provided postal monthly report fixture, and the print regression suite covers the custom landscape contract directly.

## Done (2026-04-11) -- Phase 4 print parity tranche

- What: Closed `B1`, `UX4`, and `UX5` by keeping paper/orientation `auto` under app ownership, applying source-following per-page layout on the Qt raster path, and forcing Linux/mac fixed-layout overrides onto raster instead of direct PDF submission.
- Why: The old dialog merged printer-default paper/orientation back into the app UI, and the raster bridge only set page layout once per job, which broke mixed-size/mixed-orientation source printing and risked mutating native printer expectations.
- Outcome: Printing now follows the source file page-by-page when paper/orientation are left on `auto`, while explicit paper/orientation choices remain real job overrides without silently rewriting printer defaults.

## Deferred (2026-04-11) -- Real-mouse verification for browse-selection boundary lines

- What: Leave a follow-up note that the user still reports whole-line expansion during physical mouse drags, even though the committed run-anchored browse-selection fix and automated viewport checks look correct.
- Why: This should stay visible, but it is no longer the active critical path for the campaign.
- Outcome: Resume from Phase 4 print parity (`B1`, then `UX4`, then `UX5`) and revisit the real-mouse browse-selection report afterward unless reprioritized sooner.

## Done (2026-04-11) -- Tighten run-anchored browse hits for real-mouse drags

- What: Added a strict run-hit path for browse-mode selection so mouse-down and mouse-up resolution no longer fall back to coarse block hits when the pointer lands in whitespace inside a text row.
- Why: With a physical mouse, slight near-misses inside a text block could resolve to the block fallback span, which made multi-line drags look like they expanded the first or last boundary line to the whole row.
- Outcome: Browse selection now keeps partial boundary lines during real-world drags, while legacy block fallback remains available for other callers that still want coarse text hits.

## Done (2026-04-11) -- Refine run-anchored browse selection boundaries

- What: Changed browse-mode selection so mouse-down must hit a run, mouse-up snaps to the nearest run when needed, and the copied text uses partial boundary lines with full middle lines in document reading order.
- Why: The first `UX6` pass snapped to whole intersected lines from a drag rectangle, but the intended behavior is anchored to the start run and end run, not to the full boundary lines.
- Outcome: Dragging from the middle of one line to the middle of another now selects from the start run to the end run, while still including any fully covered lines in between.

## Done (2026-04-10) -- Phase 3 whole-line text selection

- What: Changed browse-mode text selection so partial drag clips now snap to full intersected visual lines for both copied text and highlight bounds.
- Why: Raw PyMuPDF clip extraction was returning clipped word fragments like `a Beta Gamm`, which made drag selection feel broken and inconsistent with reader expectations.
- Outcome: `UX6` is now closed, and Phase 4 print parity is the next backlog handoff.

## Done (2026-04-10) -- Edit-layer readability regression fix

- What: Added a sampled scene mask behind the inline text editor so the live edit layer no longer visually overlaps the already-rendered PDF text.
- Why: Transparent editor text without a backing mask made the edit layer and display layer unreadable when they sat on top of each other.
- Outcome: The editor stays transparent and color-accurate, but the display-layer text under the edit region is now hidden while editing.

## Done (2026-04-10) -- Phase 2 text-editing tranche, batch 2

- What: Completed `UX2` by making rotated inline text editors rotate with the underlying PDF text. The editor proxy now uses rotation-aware geometry and placement instead of always rendering upright.
- Why: This closes the last open item in the Phase 2 text-edit parity tranche and removes a major visual mismatch for vertical or rotated text edits.
- Outcome: Phase 2 is now complete, and the next backlog handoff point is `UX6` in Phase 3.

## Done (2026-04-10) -- Phase 2 text-editing tranche, batch 1

- What: Landed the B2/B3/UX3 slice from the backlog campaign. Single-line edits now preserve their anchor when no wrap is needed, edit-mode outlines now follow the real run/paragraph targets instead of coarse block boxes, and the inline editor background is transparent while keeping the actual text color.
- Why: This batch removes the most distracting text-editing mismatches before we tackle rotated-editor behavior and line-based selection.
- Outcome: The focused geometry/overlap/GUI text-edit regressions are green, and the canonical backlog tracker now shows B2, B3, and UX3 as implemented while UX2 remains open.

## Done (2026-04-10) -- Phase 1 backlog quick wins

- What: Landed Save As default-path sync for the active session and capped/centered thumbnail layout behavior for wide left sidebars. Also established `docs/plans/2026-04-09-backlog-execution-order.md` as the canonical backlog tracker.
- Why: These were the lowest-risk user-visible wins and they set up the single-source-of-truth workflow for the larger backlog closure campaign.
- Outcome: Phase 1 regressions now cover the new Save As default-path behavior and wide-sidebar thumbnail centering.

## Acrobat Baseline For UX Audit

- What: Set up at least one test environment with Adobe Acrobat available for side-by-side UX benchmarking against this PDF editor.
- Why: The planned "Acrobat-level" audit depends on direct baseline comparison for task time, shortcut parity, focus behavior, and recovery UX. This device does not currently have Acrobat installed, so local parity testing is blocked.
- Pros: Enables real benchmark runs instead of internal-only scoring; prevents false claims of Acrobat-level smoothness; gives us a control app for ambiguous UX judgments.
- Cons: Requires access to a licensed/installable Acrobat environment; adds setup overhead before the full audit can be completed.
- Context: Existing GUI audits in this repo already cover many text-editing and focus/undo regressions, but they only validate this app in isolation. The missing Acrobat baseline means we can measure "good" or "bad" internally, but not "Acrobat-like" with confidence.
- Depends on / blocked by: Acrobat installation or access to another Windows machine/VM with Acrobat; final parity audit should stay blocked until that baseline environment exists.

## Done (2026-04-08) — PDFModel.edit_text() Phase Extraction

- What: Extracted `_resolve_effective_target_mode()` from `edit_text()`. Added 15 unit tests covering all three phase helpers (`_resolve_edit_target`, `_apply_redact_insert`, `_verify_rebuild_edit`) plus the new target-mode resolver.
- Why: Per-phase tests enable faster root-cause isolation; each helper is now independently testable.
- Outcome: `test_scripts/test_edit_text_helpers.py` covers happy paths, edge cases (missing block, no-change, empty text, rollback), and target-mode resolution heuristics.

## Done (2026-04-07) — Route Controller Through Typed Edit Requests

- What: Moved `EditTextRequest` and `MoveTextRequest` into `model/edit_requests.py`, re-exported from `view/text_editing.py`, routed `PDFController.edit_text()` through `EditTextCommand.from_request()`.
- Why: Keeps the typed payload intact from view to controller to command, removes repeated field unpacking, preserves the intended dependency direction.
- Outcome: Foundation tests cover request importability, controller routing, command construction, and same-page move reroute through typed payloads.

## Done (2026-04-07) — Fix size field type in EditTextRequest and MoveTextRequest

- What: Changed `size` to `float` in both request dataclasses.
- Why: PyMuPDF returns font sizes as floats; coercing to `int` silently truncates fractional sizes.
- Outcome: Request payloads match PyMuPDF's data model; canonical types now live in `model/edit_requests.py`.
