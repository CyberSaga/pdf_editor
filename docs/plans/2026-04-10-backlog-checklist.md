# Backlog Closure Checklist

Purpose: keep a compact, current execution checklist alongside `TODOS.md` so backlog state survives conversation compaction and quick handoffs.

Last updated: 2026-04-16
Canonical tracker: `docs/plans/2026-04-09-backlog-execution-order.md`
Worktree: `C:/Users/jiang/Documents/python programs/pdf_editor`

## Current State

- Current phase: Post-Phase 6 handoff
- Current batch status: `F1` is now closed end-to-end for textboxes, rectangles, app-inserted images, and native PDF images
- Resume from: review/approve the next child-plan item (`F2`, `F3`, `F4`, or `UX7`)
- Next likely phase after F1: review/approve one of the remaining child-plan items (`F2`, `F3`, `F4`, or `UX7`)

## Completed In This Campaign

- [x] Normalize backlog tracking and establish canonical tracker
- [x] Replace root duplicate tracker with pointer file
- [x] `F5` Save As defaults to active document path/name
- [x] `UX1` Thumbnail column caps width and centers in wide sidebar
- [x] `B2` Single-line text edits keep anchor and avoid unnecessary neighbor push
- [x] `B3` Edit-mode outlines follow real selectable targets instead of coarse blank-area boxes
- [x] `UX3` Inline editor background is transparent and keeps real text color
- [x] `UX2` Rotated text editors now rotate with the underlying text
- [x] `UX6` Browse-mode text selection snaps partial drags to whole visual lines
- [x] Tighten run-anchored browse selection so block-whitespace near-misses no longer expand boundary lines to whole rows
- [x] `B1` Print jobs preserve printer defaults while keeping paper/orientation auto under app ownership
- [x] `UX4` Print auto-orientation follows each source page
- [x] `UX5` Print auto paper size follows each source page, while Linux/mac fixed-layout overrides fall back to raster
- [x] Fix Qt custom-page PDF output so landscape source pages stay landscape in generated PDF files
- [x] `F6` Thumbnail right-click page operations reuse the existing page helpers/signals
- [x] `F7` Browse-mode scene context menu now exposes richer page/file actions
- [x] `F1` Objects mode, resize handles, multi-select, and app-inserted images
- [x] `F1` Native PDF image manipulation follow-up
- [x] `B4` Slice 1 adds preset-aware optimize-copy routing
- [x] `B4` Slice 2 defers background thumbnail/sidebar work until the initial page is ready and coalesces visible-render scheduling during open/page changes
- [x] Close `B4` with final before/after performance evidence

## Deferred Follow-ups

- [ ] Revisit the real-mouse browse-selection boundary-line report after the object-manipulation work.
- [ ] Resolve the low-level Windows injected-selection gap for object-verification automation. The temporary harness can create the mixed sample reliably, but object selection via injected clicks is still less trustworthy than the live `QTest` GUI pass.

## Active / Next

- [x] Finish the wider F1 verification pass
- [x] Run one successful mixed-sample GUI check that covers select, move, rotate, delete, undo, and redo for the supported object types
- [x] `objects mode` (`操作物件`) now has a visible toolbar entry and supports rect/image manipulation without fighting browse/text-selection behavior
- [x] Resize handles and same-page multi-select now work for the supported object types
- [x] App-inserted image objects now have typed identity + move/rotate/delete/resize plumbing
- [x] Native PDF image XObjects now support select/move/rotate/delete in `objects mode` without redaction-based text loss
- [ ] Review/approve child plans for `F2`, `F3`, `F4`, and `UX7`

## Remaining Backlog

- [x] `F1` Complete verification and close object manipulation v1
- [x] `F1` Native PDF image manipulation follow-up
- [ ] `F2` Review/approve child plan for Surya OCR
- [ ] `F3` Review/approve child plan for shell/file-explorer integration
- [ ] `F4` Review/approve child plan for color profile switching
- [ ] `UX7` Review/approve child plan for macOS native menu bar

## Verification Snapshot

- [x] `python -m pytest -q test_scripts/test_object_requests.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_controller_flow.py test_scripts/test_object_manipulation_gui.py test_scripts/test_add_textbox_atomic.py`
- [x] `python -m pytest -q test_scripts/test_object_manipulation_model.py test_scripts/test_object_manipulation_gui.py`
- [x] `python -m pytest -q test_scripts/test_native_pdf_images_model.py`
- [x] `python -m pytest -q test_scripts/test_object_manipulation_gui.py -k native_image`
- [x] `python tmp/manual_verify_f1_qtest.py`
- [x] Real-file native-image round-trip on `test_files/2.pdf` (move/rotate/delete plus save/reopen via `PDFModel`)
- [x] `python -m pytest -q test_scripts/test_main_startup_behavior.py`
- [x] `python -m pytest -q test_scripts/test_pdf_optimize_workflow.py -k "optimize or parallel or clean_session"`
- [x] `python -m pytest -q test_scripts/test_performance_script_runner.py`
- [x] `python test_scripts/measure_startup_time.py`
- [x] `python test_scripts/test_open_large_pdf.py --pages 300 --first-page`
- [x] `python test_scripts/test_performance.py --rounds 10`
- [x] `python test_scripts/benchmark_ui_open_render.py --path test_files/2024_ASHRAE_content.pdf`
- [x] `python test_scripts/test_all_pdfs.py`
- [ ] Clear legacy `ruff` debt still reported in `view/pdf_view.py` and `controller/pdf_controller.py`

## Resume Notes

- `B4` is closed. Keep the benchmark scripts intact so future regressions are comparable to the captured before/after numbers.
- F1 now covers app-owned textboxes, rectangle annotations, objects mode, resize handles, same-page multi-select, app-inserted images, and native PDF image manipulation.
- Native PDF images are manipulated by rewriting image invocation operators in page content streams instead of redacting overlapping page regions.
- The broader GUI/manual path is covered by a live `QTest` mixed-sample pass, plus focused object-mode, native-image model, and image-entry-point regressions.
