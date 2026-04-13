# TEST_SCRIPTS — Test Suite Reference

**330 collected · 310 pass · 8 fail (pre-existing, missing fixture files) · 12 skip**

Run with:
```bash
pytest test_scripts/          # full suite
pytest test_scripts/ -q       # quiet summary
pytest test_scripts/<file>    # single file
```

Pre-existing failures require `test_files/1.pdf` or `test_files/sample-files-main/` which are not checked in. All other tests are self-contained.

---

## Files Not Collected by pytest

These are manual script runners (`__test__ = False` or `main()`-only). Run them directly with `python test_scripts/<file>`:

| File | Purpose |
|---|---|
| `test_deep.py` | 10-scenario deep stress test: repeated edits, undo/redo cycles, extreme inputs, annotation coexistence, structural mutations, memory pressure, edge cases, performance, visual output |
| `test_large_scale.py` | 100-page × 50-round random edit stress test with undo/redo success statistics |
| `test_performance.py` | 20-round sequential edit timing: avg/max/min latency, memory growth, GC behaviour |
| `test_feature_conflict.py` (runners) | 12 concept runners for single-feature and conflict scenarios — also partially collected (see below) |
| `test_open_large_pdf.py` (main) | 1000-page open stress test with configurable page count — also partially collected (see below) |
| `test_50_rounds.py` | 50-round random edit stress test with pass-rate tracking |
| `test_all_pdfs.py` | Batch open/edit over every PDF in `test_files/` |
| `test_sample_pdfs.py` | Quick smoke over `sample-files-main/` PDFs |
| `test_overlap_corpus_recursive.py` | Overlap detection across a corpus of PDFs |
| `test_1pdf_audit.py` | Full audit of a single PDF |
| `generate_large_pdf.py` | Helper script — generates a large synthetic PDF |
| `benchmark_optimize_ab.py` | Benchmarks A/B comparison of PDF optimisation |
| `validate_optimized_pdf.py` | Validates an optimised PDF against the source |
| `live_acrobat_parity_run.py` | Manual Acrobat UX parity checklist |
| `measure_startup_time.py` | Startup latency benchmark |
| `core_interaction_audit.py` | Manual interaction audit runner |

---

## Collected Files (pytest)

### Model — Core Document Operations

#### `test_edit_text_helpers.py` (15 tests)
Transactional `edit_text` pipeline phases in isolation.

| Test | Validates |
|---|---|
| `test_mode_default_no_args` | Default mode resolves to `"run"` when no args given |
| `test_mode_explicit_span_id` | Explicit span-id forces `"run"` mode |
| `test_mode_new_rect_promotes` | New-rect target promotes to `"paragraph"` mode |
| `test_mode_explicit_paragraph` | Explicit `"paragraph"` target_mode is honoured |
| `test_mode_run_auto_promotes` | Run mode auto-promotes to paragraph when block is single-run |
| `test_mode_run_no_promote_subsection` | Run mode does not promote when block has multiple runs |
| `test_resolve_target_happy_path` | Phase 1 (resolve) finds the correct `TextBlock` by rect |
| `test_resolve_target_missing_block` | Phase 1 returns `TARGET_BLOCK_NOT_FOUND` gracefully |
| `test_resolve_target_no_change` | Phase 1 returns `NO_CHANGE` when new text equals original |
| `test_resolve_target_by_span_id` | Phase 1 resolves by span ID when provided |
| `test_apply_insert_basic` | Phase 3 (insert) writes text to the page |
| `test_apply_insert_empty_deletes` | Phase 3 with empty string redacts the block |
| `test_apply_insert_preserves_others` | Phase 3 does not disturb other blocks on the page |
| `test_verify_rebuild_passes` | Phase 4 (verify) passes when similarity threshold is met |
| `test_verify_rebuild_rollback` | Phase 4 rolls back to page snapshot when similarity fails |

#### `test_structural_indexing.py` (8 tests)
`TextBlockManager` index lifecycle after structural operations.

| Test | Validates |
|---|---|
| `test_insert_blank_page_rebuilds_inserted_page_and_marks_shifted_pages_stale` | Inserted page is immediately clean; pages shifted after it are marked stale |
| `test_shifted_page_is_rebuilt_on_demand_after_delete` | Page shifted by a delete is rebuilt lazily on `ensure_page_index_built` |
| `test_insert_pages_from_file_rebuilds_inserted_pages_and_marks_shifted_pages_stale` | Imported pages are immediately indexable; pages shifted after are stale |
| `test_structural_undo_avoids_full_rebuild_and_rebuilds_only_affected_pages` | Snapshot undo rebuilds only affected pages, never triggers full `build_index` |
| `test_insert_pages_from_file_returns_actual_insert_positions_after_validation` | Returns validated 1-based insert positions, ignoring out-of-range source pages |
| `test_delete_pages_returns_actual_deleted_pages_after_validation` | Returns only valid deleted pages; silently ignores out-of-range/duplicate indices |
| `test_insert_blank_page_returns_actual_insert_position_after_validation` | Clamps out-of-range position to end; returns actual inserted page number |
| `test_concurrent_ensure_page_index_built_no_python_level_crash` | Four threads rebuilding different pages simultaneously must not raise |

#### `test_week1_model_regressions.py` (4 tests)
Regression guard for early model behaviour changes.

| Test | Validates |
|---|---|
| `test_fallback_hit_detection_space_joins_wrapped_lines` | Fallback hit detection joins wrapped text lines with a space |
| `test_build_paragraphs_space_joins_lines` | Paragraph builder joins visual lines without inserting newlines |
| `test_same_height_edit_does_not_push_neighbor_block_down` | Editing text of the same height does not shift adjacent blocks vertically |
| `test_longer_edit_keeps_original_top_anchor` | A longer replacement preserves the top-left anchor of the original block |

#### `test_short_term_safety.py` (6 tests)
Quick regression checks for known past crashes.

| Test | Validates |
|---|---|
| `test_open_close_model_no_crash` | Opening and immediately closing a model doesn't crash |
| `test_open_save_roundtrip_preserves_page_count` | `save_as` preserves page count on the round-trip |
| `test_edit_text_on_blank_page_returns_gracefully` | `edit_text` on a page with no blocks returns a defined result, not a crash |
| `test_delete_all_but_one_page_model_still_usable` | Deleting all but the last page leaves the model in a usable state |
| `test_undo_after_delete_restores_page_count` | `undo` after `delete_pages` restores the original page count |
| `test_add_textbox_then_undo_removes_textbox` | `AddTextboxCommand` followed by `undo` removes the inserted textbox |

#### `test_empty_text_edit.py` (2 tests)
Empty-string edit (redaction) path.

| Test | Validates |
|---|---|
| `test_controller_empty_edit_is_not_ignored` | Empty-string edit is treated as a real operation, not silently discarded |
| `test_empty_edit_deletes_target_textbox_and_supports_undo_redo` | Empty edit redacts the block; undo/redo correctly restore and re-redact it |

#### `test_unified_undo.py` (1 test)
Phase-6 unified undo stack integration.

| Test | Validates |
|---|---|
| `test_phase6_unified_undo_round_trip_passes` | Full round-trip: delete page → edit text → undo×2 → redo×2 restores page count and text correctly at each step |

#### `test_char_run_reconstruction.py` (5 tests — require `test_files/1.pdf`)
Character-level run reconstruction and hit detection.

| Test | Validates |
|---|---|
| `test_runs_merge_micro_spans_on_test_file_1` | Micro-spans from kerning are merged into coherent runs |
| `test_hit_and_edit_use_reconstructed_run` | Hit detection returns reconstructed run, not raw span |
| `test_paragraph_mode_hit_and_redo_stability` | Paragraph-mode edit survives redo without span-ID drift |
| `test_paragraph_drag_without_text_change_with_overlap` | Drag-only (no text change) with overlapping blocks does not corrupt selection |
| `test_paragraph_drag_twice_with_stale_span_id` | Second drag with a stale span ID falls back to rect-based resolution |

---

### Model — Text Extraction

#### `test_text_extraction_line_joining.py` (10 tests)
Visual line joining, selection bounds, and run-anchored selection.

| Test | Validates |
|---|---|
| `test_fallback_extraction_space_joins_wrapped_lines` | Fallback extraction joins wrapped lines with a space, not a newline |
| `test_paragraph_builder_space_joins_visual_lines` | Paragraph builder joins lines within a paragraph with spaces |
| `test_multicolumn_hit_detection_does_not_merge_columns` | Hit detection on multi-column layouts does not merge text from different columns |
| `test_bullet_items_keep_semantic_breaks` | Bullet list items are not merged across items |
| `test_get_text_in_rect_expands_partial_clip_to_whole_visual_lines` | Partial rect selection expands to include full visual lines |
| `test_get_text_bounds_expands_partial_clip_to_full_visual_line_bounds` | Bounding rect expands to cover full visual line, not just the clipped fragment |
| `test_run_anchored_selection_uses_partial_boundary_lines_and_full_middle_lines` | Drag selection keeps partial first/last lines, full middle lines |
| `test_run_anchored_selection_keeps_reading_order_for_backward_drag_same_line` | Backward drag (right-to-left) on same line returns text in reading order |
| `test_exact_run_hit_ignores_block_whitespace_fallback` | `allow_fallback=False` rejects block-level whitespace hits |
| `test_run_anchored_selection_uses_nearest_run_when_mouseup_is_in_block_whitespace` | Mouse-up in block whitespace snaps to nearest run (fallback allowed) |

---

### Model — Structural Operations

#### `test_add_textbox_atomic.py` (5 tests)
`AddTextboxCommand` atomicity, rotation, and hit-detection.

| Test | Validates |
|---|---|
| `test_add_textbox_rotation_anchor_visual_location` | Textbox anchors at the visual top-left regardless of rotation |
| `test_add_textbox_default_font_supports_cjk` | Default font (`helv` fallback via htmlbox) can render CJK characters |
| `test_add_textbox_atomic_undo_redo_boundaries` | `undo`/`redo` captures only the target page, not the whole document |
| `test_add_textbox_undo_keeps_other_page_objects` | Undoing a textbox does not remove annotations or other content on the page |
| `test_add_textbox_immediately_editable_by_hit_detection` | Newly added textbox is immediately reachable by `get_text_info_at_point` |

#### `test_cross_page_text_move.py` (4 tests)
Cross-page text move operations.

| Test | Validates |
|---|---|
| `test_move_text_across_pages_records_single_snapshot_command_and_undoes` | Cross-page move records one `SnapshotCommand` and correctly undoes |
| `test_cross_page_move_unresolved_source_without_span_id_aborts_cleanly` | Unresolvable source block aborts the move without corrupting state |
| `test_cross_page_move_stale_span_id_falls_back_to_rect_text_resolution` | Stale span ID falls back to rect-based resolution rather than aborting |
| `test_cross_page_move_add_failure_restores_before_snapshot_and_refreshes_ui` | If the add-to-target fails, before-snapshot is restored and UI is refreshed |

#### `test_pdf_merge_workflow.py` (12 tests)
Multi-PDF merge dialog lifecycle.

| Test | Validates |
|---|---|
| `test_merge_list_preserves_reorder_via_move_up_move_down` | Move-up/move-down updates model order correctly |
| `test_merge_list_reorder_reflected_in_final_document_page_sequence` | Reordered list produces pages in the expected order in the merged PDF |
| `test_merge_removes_item_and_shifts_selection` | Remove item shifts selection index cleanly |
| `test_merge_accepts_duplicate_paths` | Adding the same file twice is permitted |
| `test_merge_password_file_accepted_with_correct_password` | Password-protected source accepted with the right password |
| `test_merge_password_file_rejected_with_wrong_password` | Wrong password raises an error before the merge starts |
| `test_merge_cancel_does_not_modify_active_document` | Cancelling the dialog leaves the active session unchanged |
| `test_merge_operation_is_atomic_undo_in_one_step` | Entire merge is wrapped in a single `SnapshotCommand`, undone in one step |
| `test_merge_page_range_subset` | Merging a page subset inserts only the specified pages |
| `test_merge_with_blank_page_inserted_between_sources` | Blank page separator between sources appears in the correct position |
| `test_merge_large_source_does_not_corrupt_index` | Merging a 50-page source does not leave stale index entries |
| `test_merge_empty_list_produces_no_change` | Merging an empty list is a no-op |

---

### Model — Optimisation

#### `test_pdf_optimize_workflow.py` (21 tests)
PDF optimisation presets, image rewriting, audit, and controller wiring.

| Test | Covers |
|---|---|
| `test_optimize_dialog_defaults_to_balanced_and_switches_to_custom` | Dialog preset defaults and custom switch |
| `test_pdf_model_optimizer_facade_uses_internal_module` | `PDFModel.save_optimized_copy` delegates to `pdf_optimizer` |
| `test_file_tab_exposes_optimize_copy_action` | File menu exposes the optimise action |
| `test_save_optimized_copy_uses_working_doc_and_preserves_live_doc` | Optimise copy does not mutate the live session document |
| `test_save_optimized_copy_avoids_live_doc_tobytes_for_clean_session` | Clean sessions avoid an extra `tobytes()` round-trip |
| `test_save_optimized_copy_prefers_parallel_image_rewrite_for_clean_source` | Parallel image rewrite path is selected for clean sessions |
| `test_save_optimized_copy_prefers_parallel_image_rewrite_for_dirty_session` | Parallel image rewrite path is selected for dirty sessions |
| `test_save_optimized_copy_dirty_session_preserves_unsaved_edits` | Optimise copy does not clear the `has_unsaved_changes` flag |
| `test_save_optimized_copy_accepts_all_presets` | All preset names (`web`, `print`, `archive`, `balanced`, `custom`) are accepted |
| `test_build_pdf_audit_report_groups_known_categories` | Audit report groups image, font, and page-structure findings correctly |
| `test_build_pdf_audit_report_caches_active_document_results` | Audit results for the active document are cached (not recomputed on second call) |
| `test_pdf_audit_report_dialog_uses_table_and_stacked_bar` | Audit dialog renders a table and a stacked bar chart |
| `test_start_optimize_pdf_copy_saves_and_opens_new_tab` | Completed optimisation opens the output in a new tab |
| `test_start_optimize_pdf_copy_rejects_current_path_collision` | Saving optimised copy over the currently-open file is rejected |
| `test_start_optimize_pdf_copy_runs_work_in_background` | Worker is launched on a background `QThread`, not the GUI thread |
| `test_start_optimize_pdf_copy_cancels_active_background_loading` | Starting a second optimisation cancels any active background load |
| `test_start_optimize_pdf_copy_completion_message_uses_human_units` | Completion toast shows KB/MB/GB units, not raw byte count |
| `test_format_size_units_covers_kb_mb_and_gb` | `_format_size` formats all three human-readable tiers correctly |
| `test_pil_png_debug_logging_is_suppressed` | PIL PNG debug noise is suppressed to avoid log pollution |
| `test_large_file_optimize_submission_keeps_progress_dialog_responsive` | Progress dialog does not freeze during a large-file optimisation |
| `test_large_file_optimized_copy_passes_integrity_validation` | Output PDF of a large-file optimisation passes `pikepdf` integrity check |

---

### Controller — Workers & Threading

#### `test_controller_workers.py` (4 tests)
Signal-emission invariants for `QThread` worker objects.

| Test | Validates |
|---|---|
| `test_optimize_worker_emits_succeeded_and_finished_on_success` | `_OptimizePdfCopyWorker` emits `succeeded(result)` then `finished` on success |
| `test_optimize_worker_emits_failed_and_finished_on_exception` | `_OptimizePdfCopyWorker` emits `failed(exc)` then `finished` when `save_optimized_copy` raises |
| `test_print_submission_worker_emits_prepared_and_finished_on_success` | `_PrintSubmissionWorker` emits `prepared(PrintHelperJob)` then `finished` on success |
| `test_print_submission_worker_emits_failed_and_finished_on_capture_exception` | `_PrintSubmissionWorker` emits `failed(exc)` then `finished` when `capture_pdf_bytes` raises |

#### `test_multi_tab_plan.py` (69 tests)
Multi-session (multi-tab) orchestration — the largest single test file.

Covers: tab open/close/switch, per-session undo stack isolation, dirty-flag tracking, `save_as` default-path sync across tab switches, session state preservation during close, thumbnail consistency, and drag-and-drop into empty vs. populated tab bar.

#### `test_main_startup_behavior.py` (15 tests)
Application startup paths.

| Test cluster | Validates |
|---|---|
| CLI path argument | File passed on CLI opens in the first tab |
| Empty startup | No crash when launched with no file |
| Deferred backend | Backend initialisation is deferred until the window is shown |
| Drag-and-drop | Dropping a file onto the window opens it |
| Duplicate open | Opening an already-open file activates its tab, not a second copy |

---

### View — Text Editing GUI

#### `test_text_editing_gui_regressions.py` (38 tests)
Inline text editor: geometry, rotation, focus, style controls, selection, keyboard shortcuts.

Key areas:
- **Editor creation** — proxy rotation for vertical text, mask item to hide background text, stylesheet transparency
- **Selection** — start/end anchored to run (not block), backward drag reading order, whitespace snapping
- **Finalisation** — noop detection, position-only commit, cross-page move, discard vs. commit on Escape/mode-switch
- **Keyboard forwarding** — `Ctrl+S` / `Ctrl+Shift+S` finalize before emitting, `Cmd+Shift+Z` fires redo, local editor undo/redo history isolation
- **Outline rendering** — block outlines only for visible pages, run-box outlines in run mode
- **Mask color** — sampled from local scene crop, refreshed on drag-move

#### `test_text_edit_manager_foundation.py` (11 tests)
`TextEditManager` typed request routing and controller wiring.

| Test | Validates |
|---|---|
| `test_pdf_view_init_does_not_warn_about_outline_disconnects` | No Qt signal-connection warnings on `PDFView` init |
| `test_pdf_view_exposes_text_edit_manager_on_real_init` | `PDFView.text_edit_manager` is accessible after real init |
| `test_finalize_emits_typed_edit_request_payload` | `finalize` emits an `EditTextRequest` with correct field values |
| `test_sig_move_text_emits_move_text_request` | Move signal emits a `MoveTextRequest` with source/dest fields |
| `test_move_text_request_fields_match_session` | `MoveTextRequest` fields match the active session context |
| `test_controller_accepts_move_text_request` | Controller routes `MoveTextRequest` to the model correctly |
| `test_controller_updates_undo_redo_enabled_state_from_command_manager` | Undo/redo toolbar actions reflect `CommandManager` stack state |
| `test_controller_edit_text_shows_error_toast_for_invalid_result` | Invalid `EditTextResult` triggers a user-visible error toast |
| `test_edit_text_command_initializes_result_before_execute` | `EditTextCommand.result` is initialised before `execute()` is called |
| `test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands` | Non-`EditTextCommand` types are not required to set `.result` |
| `test_edit_text_command_execute_annotation_is_bool` | `execute()` return annotation is `bool`, not `None` |

#### `test_edit_geometry_stability.py` (2 tests)
Text-block geometry stability across repeated edits.

| Test | Validates |
|---|---|
| `test_repeated_identical_edits_keep_y1_drift_under_half_point` | 10 repeated identical edits drift the bottom edge by < 0.5 pt |
| `test_single_line_edit_preserves_anchor_and_does_not_push_neighbor` | Editing a single-line block does not shift the block above or below it |

#### `test_drag_move.py` (9 tests)
Drag-to-move text block interactions.

Covers: visual drag threshold, move commit vs. discard, snap-to-page-boundary clamping, degenerate rect prevention after drag, overlap detection during move.

#### `test_overlap_textbox_edit.py` (5 tests)
Textbox edit interaction when blocks overlap.

Covers: overlapping blocks don't corrupt each other's content, hit detection priority when blocks share the same pixel, undo of an edit on one block does not affect overlapping block.

#### `test_fullscreen_transitions.py` (varies)
Fullscreen entry/exit.

Covers: scroll position preserved on exit, editor closed before entering fullscreen, thumbnail sidebar hidden in fullscreen, Escape exits fullscreen.

---

### View — Rendering & Layout

#### `test_1pdf_horizontal.py` (1 test — requires `1.pdf`)
End-to-end horizontal text edit and verify on a real PDF.

#### `test_edit_flow.py` (not collected)
Smoke test for the basic edit flow. Run manually: `python test_scripts/test_edit_flow.py`.

---

### Printing

#### `test_print_dialog_logic.py` (6 tests)
Print pipeline pure-logic checks.

| Test | Validates |
|---|---|
| `test_resolve_page_indices_odd_subset_with_range` | Odd-page filter on a custom range returns correct 0-based indices |
| `test_resolve_page_indices_odd_subset_reversed` | Reversed odd-page filter returns indices in reverse order |
| `test_compute_target_draw_rect_fit_mode` | Fit scaling preserves aspect ratio within target dimensions |
| `test_compute_target_draw_rect_actual_mode` | Actual-size mode preserves source dimensions exactly |
| `test_compute_target_draw_rect_custom_scale` | Custom percentage (150%) scales both dimensions correctly |
| `test_print_job_options_normalization_clamps_and_lowercases` | `PrintJobOptions.normalized()` clamps scale, lowercases enums, strips invalid override fields |

#### `test_print_dialog_properties_button.py` (13 tests)
Printer-properties dialog sync (Windows native dialog integration).

Covers: duplex sync, color-mode sync, paper-size/orientation not overwritten by driver defaults, cancel discards prefs, OK persists prefs.

#### `test_print_subprocess_runner.py` (4 tests)
`PrintSubprocessRunner` stall detection and termination.

| Test | Validates |
|---|---|
| `test_runner_emits_stalled_after_silence` | Stall signal fires after the helper process goes silent for the timeout duration |
| `test_runner_maps_terminated_process_to_helper_terminated_error` | A terminated process maps to `HelperTerminatedError`, not a generic exception |
| `test_runner_logs_startup_error_and_uses_sys_executable` | Startup failure is logged; subprocess uses `sys.executable` not a hard-coded path |
| `test_runner_heartbeat_events_prevent_false_stall` | Regular heartbeat events reset the stall timer and prevent false stalls |

#### `test_print_subprocess_helper.py` (3 tests)
Print helper subprocess protocol.

Covers: JSON progress events are emitted correctly, helper exits with code 0 on success, helper exits with code 1 on failure.

#### `test_print_controller_flow.py` (4 tests)
Controller-level print flow.

Covers: print action triggers submission worker, cancellation signal from controller, progress message forwarded to UI, worker thread lifecycle.

#### `test_qt_bridge_layout.py` (5 tests)
Qt raster/PDF rendering bridge layout calculations.

Covers: landscape page correctly uses portrait base dimensions + orientation flag, mixed-size job per-page layout, scale-to-fit calculation for oversized source.

---

### Platform Drivers

#### `test_win_driver_properties.py` (5 tests)
Windows printer driver property sync.

| Test | Validates |
|---|---|
| `test_open_printer_properties_ignores_setprinter_access_denied` | `ACCESS_DENIED` from `SetPrinter` is silently ignored (not fatal) |
| `test_get_printer_preferences_prefers_richer_tray_list` | Driver prefs prefer the device-capabilities tray list over the default |
| `test_get_printer_preferences_prefers_user_defaults_for_color_mode` | User-level defaults override driver defaults for color mode |
| `test_open_printer_properties_reloads_user_defaults_after_color_change` | After a color-mode change in properties dialog, user defaults are reloaded |
| `test_open_printer_properties_cancel_returns_none_without_persisting` | Cancelling the native properties dialog returns `None` without persisting |

#### `test_linux_driver_overrides.py` (6 tests)
Linux print driver option overrides.

Covers: orientation override correct, paper-size override correct, duplex flag mapping, colour/mono flag mapping.

---

### Application Startup & Interaction

#### `test_core_interaction_audit.py` (5 tests)
Interaction audit plan structure.

| Test | Validates |
|---|---|
| `test_default_core_interaction_plan_uses_three_existing_fixtures` | Audit plan references exactly 3 fixture files (requires fixtures on disk) |
| `test_default_core_interaction_plan_includes_automated_manual_and_acrobat_scenarios` | Plan includes automated, manual, and Acrobat-parity scenario types |
| `test_run_audit_plan_marks_non_automated_scenarios_blocked` | Running the plan marks non-automated scenarios as blocked |
| `test_render_markdown_report_includes_summary_and_blockers` | Markdown report includes pass summary and blocker list |
| `test_render_manual_checklist_includes_manual_steps_and_relative_fixture_paths` | Manual checklist includes steps and relative fixture paths |

#### `test_iso27001_sop_update.py` (1 test)
ISO 27001 SOP document update automation.

#### `test_font_fix.py` (1 test)
`test_html_conversion` — Validates HTML-to-PDF font substitution doesn't corrupt non-Latin characters.

---

### File I/O Edge Cases

#### `test_export_boundaries.py` (4 tests)
`export_pages` and `save_as` boundary conditions.

| Test | Validates |
|---|---|
| `test_export_pages_empty_list_image_mode_creates_no_file` | Exporting an empty page list produces no output file |
| `test_export_single_page_as_image_creates_non_empty_file[png]` | Single-page PNG export produces a non-empty image file |
| `test_export_single_page_as_image_creates_non_empty_file[jpg]` | Single-page JPEG export produces a non-empty image file |
| `test_save_as_readonly_directory_raises` | `save_as` to a write-protected directory raises `PermissionError`/`OSError` (skipped on Windows where chmod is a no-op) |

#### `test_open_large_pdf.py` (1 test — partial collection)
| Test | Validates |
|---|---|
| `test_open_pdf_100_pages_completes_under_ten_seconds` | Opening a 100-page programmatic PDF completes in < 10 s |

---

### Edge Cases & Stress

#### `test_deep_smoke.py` (7 tests)
Pytest-collectable smoke tests extracted from the T8/T2 scenarios in `test_deep.py`.

| Test | Validates |
|---|---|
| `test_t8_empty_content_pdf_opens_without_crash` | 1-page blank PDF opens and returns an empty block list |
| `test_t8_tiny_page_1pt_opens_without_crash` | 1 pt × 1 pt page opens without an unhandled exception |
| `test_t8_large_a0_page_opens_without_crash` | A0-sized page (2384 × 3370 pt) opens without memory issues |
| `test_t8_edit_text_degenerate_rect_does_not_crash` | `edit_text` with `Rect(0,0,0,0)` fails gracefully |
| `test_t8_edit_text_out_of_range_page_does_not_crash` | `edit_text` with `page_num=9999` raises a controlled exception only |
| `test_t2_undo_redo_delete_page_restores_count` | Delete → undo restores page count; redo re-deletes it |
| `test_t2_empty_undo_stack_returns_false_no_crash` | `undo()` on an empty stack returns `False` without raising |

#### `test_feature_conflict.py` (5 tests collected — 12 runners manual)
Conflict-scenario wrappers (skip when `test_files/sample-files-main/` is absent).

| Test | Validates |
|---|---|
| `test_feature_conflict_runner_passes[run_conflict_annot_then_edit]` | Annotations survive subsequent text edits |
| `test_feature_conflict_runner_passes[run_conflict_structural_undo]` | Structural undo (page delete) restores correct state |
| `test_feature_conflict_runner_passes[run_conflict_rotate_then_edit]` | Text editing works on rotated pages |
| `test_feature_conflict_runner_passes[run_conflict_insert_then_edit]` | Text editing works on newly-inserted pages |
| `test_feature_conflict_runner_passes[run_conflict_multi_undo_redo]` | Multi-operation undo/redo cycles maintain consistent state |

---

### Track C — Advanced Edit Engine

#### `test_track_c.py` (8 tests)
Track-C character-precise edit engine.

| Test | Validates |
|---|---|
| `test_simple_replacement` | Simple word replacement produces correct output |
| `test_kerning_preserved` | Kerning pairs are preserved through a replacement |
| `test_different_length_no_crash` | Replacement with a different character count does not crash |
| `test_can_handle_form_xobject_phase1` | Phase-1 handler accepts Form XObject content streams |
| `test_can_handle_rejects_identity_h` | `Identity-H` CMap encoding is correctly rejected |
| `test_verification_catches_bad_edit` | Verification phase catches edits that corrupt the text stream |
| `test_no_silent_fail_on_missing_text` | Missing target text raises an error rather than silently passing |
| `test_real_pdfs` | End-to-end test on real PDFs (skipped when fixture PDFs absent) |

---

## Known Pre-existing Failures

These 8 failures require fixture files not present in this repository:

| Test | Reason |
|---|---|
| `test_1pdf_horizontal::test_horizontal_edit_and_verify` | Needs `test_files/1.pdf` |
| `test_char_run_reconstruction` (5 tests) | Needs `test_files/1.pdf` |
| `test_core_interaction_audit::test_default_core_interaction_plan_uses_three_existing_fixtures` | Needs fixture files in `test_files/fixtures/` |
| `test_track_c::test_real_pdfs` | Needs `test_files/reportlab-overlay.pdf` etc. |
