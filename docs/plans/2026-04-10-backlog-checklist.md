# Backlog Closure Checklist

Purpose: keep a compact, current execution checklist alongside `TODOS.md` so backlog state survives conversation compaction and quick handoffs.

Last updated: 2026-04-11
Canonical tracker: `docs/plans/2026-04-09-backlog-execution-order.md`
Worktree: `C:/Users/jiang/Documents/python programs/pdf_editor/.worktrees/codex-backlog-closure-campaign`

## Current State

- Current phase: Phase 5 context-menu improvements
- Current batch status: Phase 4 complete; browse-selection follow-up deferred
- Resume from: `F6`
- Next likely phase after `F6`: complete the rest of Phase 5 (`F7`)

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

## Deferred Follow-ups

- [ ] Revisit the real-mouse browse-selection boundary-line report after Phase 4. Current worktree code is committed, but the user still reports whole-line expansion during physical drags, so this needs a fresh manual verification pass later.

## Active / Next

- [ ] `F6` Thumbnail right-click page operations
- [ ] `F7` Richer right-click menus everywhere

## Remaining Backlog

- [ ] `B4` Performance profiling plus shipped speed improvements
- [ ] `F1` Child plan for object manipulation
- [ ] `F2` Child plan for Surya OCR
- [ ] `F3` Child plan for shell/file-explorer integration
- [ ] `F4` Child plan for color profile switching
- [ ] `UX7` Child plan for macOS native menu bar

## Child Plans Still Needed

- [ ] `docs/plans/2026-04-10-object-manipulation.md`
- [ ] `docs/plans/2026-04-10-surya-ocr.md`
- [ ] `docs/plans/2026-04-10-shell-integration.md`
- [ ] `docs/plans/2026-04-10-color-profile-switching.md`
- [ ] `docs/plans/2026-04-10-macos-native-menu-bar.md`
- [ ] `docs/plans/2026-04-10-performance-closure-plan.md`

## Verification Snapshot

- [x] `python -m pytest -q test_scripts/test_text_editing_gui_regressions.py -k "save_as_shortcut_finalizes_editor_before_emitting_save_as or save_as_uses_current_document_default_path_when_present"`
- [x] `python -m pytest -q test_scripts/test_multi_tab_plan.py -k "test_06a or test_06b or test_06c or test_06d or test_06e or test_06f or test_10_save_as_path_collision_blocked or test_10a_active_session_updates_view_save_as_default_path"`
- [x] `python -m pytest -q test_scripts/test_edit_geometry_stability.py test_scripts/test_overlap_textbox_edit.py test_scripts/test_text_editing_gui_regressions.py`
- [x] `python -m pytest -q test_scripts/test_text_edit_manager_foundation.py -k "controller_edit_text_shows_error_toast_for_invalid_result or edit_text_command_initializes_result_before_execute or edit_text_command_execute_annotation_is_bool"`
- [x] `python -m pytest -q test_scripts/test_text_editing_gui_regressions.py -k "create_text_editor_rotates_proxy_for_vertical_text"`
- [x] `python -m pytest -q test_scripts/test_text_edit_manager_foundation.py`
- [x] `python -m pytest -q test_scripts/test_text_editing_gui_regressions.py -k "create_text_editor_adds_mask_item_to_hide_display_text or finalize_text_edit_removes_mask_item"`
- [x] `python -m pytest -q test_scripts/test_text_extraction_line_joining.py -k "get_text_in_rect_expands_partial_clip_to_whole_visual_lines or get_text_bounds_expands_partial_clip_to_full_visual_line_bounds"`
- [x] `python -m pytest -q test_scripts/test_text_extraction_line_joining.py test_scripts/test_text_editing_gui_regressions.py`
- [x] `python -m pytest -q test_scripts/test_print_dialog_logic.py test_scripts/test_print_dialog_properties_button.py test_scripts/test_qt_bridge_layout.py test_scripts/test_linux_driver_overrides.py test_scripts/test_win_driver_properties.py test_scripts/test_print_controller_flow.py`
- [x] Manual raster-to-PDF check with `郵政-A7自用層技服案-115.03月份工作月報.pdf`: output pages 13-15 confirmed as A3 landscape after the Qt custom-page fix
- [ ] Clear legacy `ruff` debt still reported in `view/pdf_view.py`

## Resume Notes

- Browse-mode selection is now run-anchored: start requires a direct run hit, end may snap to the nearest run, boundary lines are partial, and only fully covered middle lines expand to whole-line units. Do not regress this by falling back to raw clip-rect selection.
- Browse-mode hit-testing now has a strict path: selection start and end resolution must call `get_text_info_at_point(..., allow_fallback=False)` so block-whitespace misses do not silently degrade into line-start fallbacks.
- The committed browse-selection fix is deferred for follow-up, not the current critical path. Treat it as a checklist item to re-verify with a physical mouse after the print tranche, unless the user reprioritizes it sooner.
- Print auto paper/orientation are now app-owned and source-following. Native printer properties still sync duplex/color/DPI/copies, but printer-default paper/orientation must not overwrite the dialog's `auto` state.
- Linux/mac direct-PDF printing is still allowed for source-following auto jobs. If the user explicitly fixes paper size or orientation in-app, the driver must force the raster path so per-page/source layout semantics are preserved.
- Qt custom page sizes must be created in portrait order before applying landscape orientation. Passing already-landscape dimensions into `QPageSize(..., Point, ...)` makes generated PDF output flip back to portrait.
- `view/pdf_view.py` still carries pre-existing `E701` lint debt; avoid mixing cleanup-only edits into behavior batches unless explicitly planned.
- Keep `docs/plans/2026-04-09-backlog-execution-order.md` as the source of truth for statuses; update this checklist as the compact execution mirror.
