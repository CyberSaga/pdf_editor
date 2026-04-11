# Backlog Closure Master Tracker

> Canonical tracker for closing the open backlog from `docs/to_Update.md`. Cross-checked once on 2026-04-10; `docs/to_Update.md` is now historical input only.

## Rules

- `done-implement`: item is implemented, tested, and reflected in docs/tracker.
- `done-plan`: item is replaced by an approved child plan with successor items and acceptance criteria.
- `open`: not started.
- `in_progress`: active implementation or profiling work.

## Phase Overview

| Phase | Focus | Status | Notes |
|---|---|---|---|
| 1 | F5, UX1 | done | First batch landed in code and regression tests; tracker/docs updated in same batch. |
| 2 | B2, B3, UX3, UX2 | done | Text-edit parity tranche is complete; rotated-editor behavior now matches rotated text orientation. |
| 3 | UX6 | done | Browse-mode text selection now snaps partial drags to whole visual lines in both copied text and highlight bounds. |
| 4 | B1, UX4, UX5 | done | Print parity tranche landed: app-owned auto paper/orientation now follow source pages, fixed-layout overrides stay explicit, and direct-PDF Linux/mac routing preserves that contract. |
| 5 | F6, F7 | open | Reuse existing context-menu entry points. |
| 6 | F1 | open | Replace with child plan before implementation. |
| 7 | B4 | open | Needs profiling, then a child performance plan, then measured wins. |
| 8 | UX7 | open | Replace with child plan; macOS-only. |
| 9 | F4, F2, F3 | open | Replace with child plans before implementation. |

## Item Tracker

| ID | Item | Phase | Status | Closure Type | Evidence | Next Step |
|---|---|---|---|---|---|---|
| B1 | Print must not modify printer preferences | 4 | done | done-implement | `pytest -q test_print_dialog_logic.py test_print_dialog_properties_button.py test_qt_bridge_layout.py test_linux_driver_overrides.py test_win_driver_properties.py test_print_controller_flow.py` | Preserve the app-owned `auto` paper/orientation contract while later print features land. |
| B2 | Text box drifts position after edit, pushes others | 2 | done | done-implement | `pytest -q test_edit_geometry_stability.py -k "single_line_edit_preserves_anchor_and_does_not_push_neighbor"` plus full text-edit safety slice in `test_edit_geometry_stability.py` / `test_overlap_textbox_edit.py` / `test_text_editing_gui_regressions.py` | Keep the single-line anchor-preserving path in place while UX2 lands. |
| B3 | Edit-mode outline selects blank areas | 2 | done | done-implement | `pytest -q test_text_editing_gui_regressions.py -k "block_outlines_only_drawn_for_visible_pages or block_outlines_follow_run_boxes_in_run_mode"` | Preserve run/paragraph outline alignment when UX2 changes editor presentation. |
| B4 | All workflows are slow | 7 | open | done-implement | Baseline scripts: `measure_startup_time.py`, `test_open_large_pdf.py`, `test_performance.py` | Capture baselines, create performance child plan, then implement measured wins. |
| UX1 | Thumbnails resize with sidebar / center when sidebar is too wide | 1 | done | done-implement | `pytest -q test_multi_tab_plan.py -k "test_06a or test_06b or test_06c or test_06d or test_06e or test_06f or test_10_save_as_path_collision_blocked or test_10a_active_session_updates_view_save_as_default_path"` | Keep watching Phase 1 regressions while later UI work lands. |
| UX2 | Editing rotated text: editor box content should also rotate | 2 | done | done-implement | `pytest -q test_text_editing_gui_regressions.py -k "create_text_editor_rotates_proxy_for_vertical_text"` plus the full text-edit GUI slice | Preserve rotation-aware editor geometry while Phase 3 selection work lands. |
| UX3 | Edit box should be transparent, show real text color | 2 | done | done-implement | `pytest -q test_text_editing_gui_regressions.py -k "build_text_editor_stylesheet_keeps_editor_background_transparent"` plus the broader GUI regression slice | Carry the transparent-editor contract forward when rotated-editor support lands. |
| UX4 | Print auto-rotate based on page orientation | 4 | done | done-implement | `pytest -q test_qt_bridge_layout.py` plus the print dialog/property slice now cover per-page source-orientation layout on raster output and source-following auto behavior in the dialog | Keep per-page layout updates in the Qt bridge; do not collapse auto orientation back to a single job-level layout. |
| UX5 | Print auto-select paper size from source page | 4 | done | done-implement | `pytest -q test_qt_bridge_layout.py test_linux_driver_overrides.py` plus the dialog/property slice now cover source-following auto paper size and Linux/mac raster fallback for fixed-layout overrides | Keep direct-PDF routing only for source-following auto jobs; explicit paper-size overrides must stay on the raster path. |
| UX6 | Text selection should use whole-line units | 3 | done | done-implement | `pytest -q test_text_extraction_line_joining.py -k "get_text_in_rect_expands_partial_clip_to_whole_visual_lines or get_text_bounds_expands_partial_clip_to_full_visual_line_bounds"` plus `pytest -q test_text_extraction_line_joining.py test_text_editing_gui_regressions.py` | Follow up later on the user-reported physical-mouse whole-line expansion; not on the current critical path. |
| UX7 | macOS native menu bar | 8 | open | done-plan | No child plan yet | Write a dedicated macOS child plan before code. |
| F1 | Add/manipulate objects (including rotate text box) | 6 | open | done-plan | No child plan yet | Write object-manipulation child plan with scoped successor items. |
| F2 | OCR with Surya | 9 | open | done-plan | No child plan yet | Write Surya child plan covering dependency isolation and threading. |
| F3 | File-explorer right-click “Merge with PDF Editor” | 9 | open | done-plan | No child plan yet | Write OS integration child plan for Windows/macOS. |
| F4 | Color profile switching | 9 | open | done-plan | No child plan yet | Write color-conversion child plan before code. |
| F5 | Save As auto-fills current filename | 1 | done | done-implement | `pytest -q test_text_editing_gui_regressions.py -k "save_as_shortcut_finalizes_editor_before_emitting_save_as or save_as_uses_current_document_default_path_when_present"` and integrated tab/save-path coverage in `test_multi_tab_plan.py` | Keep active-session default-path sync in place as tabs/save state evolve. |
| F6 | Thumbnail right-click page operations | 5 | open | done-implement | Existing thumbnail widget and click-navigation tests | Add context-menu red tests after print tranche. |
| F7 | Richer right-click menus everywhere | 5 | open | done-implement | Existing scene context-menu regression harness in `test_text_editing_gui_regressions.py` | Extend menu assertions once F6 is complete. |

## Child Plans Required Before Implementation

- `docs/plans/2026-04-10-object-manipulation.md` for F1.
- `docs/plans/2026-04-10-surya-ocr.md` for F2.
- `docs/plans/2026-04-10-shell-integration.md` for F3.
- `docs/plans/2026-04-10-color-profile-switching.md` for F4.
- `docs/plans/2026-04-10-macos-native-menu-bar.md` for UX7.
- `docs/plans/2026-04-10-performance-closure-plan.md` for B4 after baseline profiling.
