# CODEGRAPH_REPORT — pdf_editor

> Generated 2026-06-07 by `.codegraph/report_gen.py`  
> Source: `.codegraph/graph.db` — re-run after structural changes.

## 1. Summary

| Metric | Count |
| ------------------------------ | ---------- |
| Python files indexed | 200 |
| Classes | 251 |
| Functions | 1497 |
| Methods | 1362 |
| Total callable symbols | 2859 |
| Called (name seen in a call site) | 1791 |
| **Never-called** | **1068** |
| Never-called % | 37.4% |
| Total edges | 21872 |
|   — defines | 3110 |
|   — calls | 18403 |
|   — imports | 284 |
|   — inherits | 75 |

## 2. Layer Breakdown

| Layer | Files | Classes | Functions | Methods |
| -------------------- | ------- | --------- | ----------- | --------- |
| `view/` | 13 | 26 | 25 | 333 |
| `controller/` | 2 | 11 | 0 | 183 |
| `model/` | 24 | 49 | 89 | 301 |
| `utils/` | 5 | 2 | 19 | 9 |
| `src/` | 17 | 27 | 34 | 106 |
| `scripts/` | 9 | 0 | 53 | 0 |
| `test_scripts/` | 123 | 132 | 1245 | 406 |

## 3. Heaviest Classes (by method count)

| Class | Methods |
| -------------------------------------------------- | --------- |
| `PDFView` | 245 |
| `PDFController` | 164 |
| `PDFModel` | 162 |
| `_FakeEvent` | 38 |
| `TextBlockManager` | 37 |
| `UnifiedPrintDialog` | 32 |
| `_FakeGraphicsView` | 29 |
| `WatermarkTool` | 22 |
| `_FakeSignal` | 22 |
| `_FakeViewport` | 20 |
| `WindowsPrinterDriver` | 19 |
| `_FakeRectItem` | 19 |
| `_FakeInlineTextEditor` | 18 |
| `DesignSystemGenerator` | 16 |
| `_FakeProgressDialog` | 15 |

## 4. Most Imported Modules (internal)

> Modules that appear most often as import targets — changing them has the widest blast radius.

| Module | Imported by N files |
| ------------------------------------------------------- | -------------------- |
| `model/pdf_model.py` | 64 |
| `view/pdf_view.py` | 29 |
| `controller/pdf_controller.py` | 18 |
| `model/edit_commands.py` | 18 |
| `model/object_requests.py` | 15 |
| `src/printing/base_driver.py` | 12 |
| `view/text_editing.py` | 8 |
| `model/tools/ocr_types.py` | 8 |
| `utils/helpers.py` | 7 |
| `model/pdf_content_ops.py` | 5 |
| `main.py` | 5 |
| `utils/preferences.py` | 5 |
| `src/printing/__init__.py` | 4 |
| `src/printing/helper_protocol.py` | 4 |
| `src/printing/print_dialog.py` | 4 |

## 5. Inheritance Relationships

| Subclass | Base |
| ------------------------------------------------------- | ----------------------------------- |
| `_OcrBridge` | `QObject` |
| `_OcrWorker` | `QObject` |
| `_OptimizePdfCopyWorker` | `QObject` |
| `_OptimizeWorkerBridge` | `QObject` |
| `_PrintSubmissionWorker` | `QObject` |
| `_PrintWorkerBridge` | `QObject` |
| `ColorProfile` | `str` |
| `ColorProfile` | `Enum` |
| `AddTextboxCommand` | `EditCommand` |
| `EditCommand` | `ABC` |
| `EditTextCommand` | `EditCommand` |
| `EditTextResult` | `str` |
| `EditTextResult` | `Enum` |
| `SnapshotCommand` | `EditCommand` |
| `AnnotationTool` | `ToolExtension` |
| `ToolExtension` | `ABC` |
| `OcrTool` | `ToolExtension` |
| `OcrDevice` | `str` |
| `OcrDevice` | `Enum` |
| `OcrLanguage` | `str` |
| `OcrLanguage` | `Enum` |
| `OcrWeightsError` | `RuntimeError` |
| `SearchTool` | `ToolExtension` |
| `WatermarkTool` | `ToolExtension` |
| `PrinterDriver` | `ABC` |
| `PrintHelperStalledError` | `PrintingError` |
| `PrintHelperTerminatedError` | `PrintingError` |
| `PrintJobSubmissionError` | `PrintingError` |
| `PrinterOfflineError` | `PrintingError` |
| `PrinterUnavailableError` | `PrintingError` |
| `PrintingError` | `RuntimeError` |
| `RenderingError` | `PrintingError` |
| `LinuxPrinterDriver` | `PrinterDriver` |
| `MacPrinterDriver` | `LinuxPrinterDriver` |
| `WindowsPrinterDriver` | `PrinterDriver` |
| `_DEVMODE_STRUCT1` | `ctypes.Structure` |
| `_DEVMODE_UNION1` | `ctypes.Union` |
| `_DEVMODE_UNION2` | `ctypes.Union` |
| `_POINTL` | `ctypes.Structure` |
| `_PRINTER_INFO_9` | `ctypes.Structure` |
| `_PUBLIC_DEVMODEW` | `ctypes.Structure` |
| `UnifiedPrintDialog` | `QDialog` |
| `PrintSubprocessRunner` | `QObject` |
| `_FakeEllipseItem` | `_FakeRectItem` |
| `_FakeProcess` | `QObject` |
| `_NamedCommand` | `EditCommand` |
| `_UndoBoomCommand` | `_NamedCommand` |
| `_FakeSceneCapture` | `_FakeScene` |
| `_FakeShortcutEditorWidget` | `_FakeEditorWidget` |
| `_FakeWin32PrintCancel` | `_FakeWin32Print` |
| `_FakeWin32PrintLimitedPort` | `_FakeWin32Print` |
| `_FakeWin32PrintUserDefaults` | `_FakeWin32Print` |
| `PyFakeHandle` | `int` |
| `_SettingsLike` | `Protocol` |
| `AuditStackedBar` | `QWidget` |
| `PdfAuditReportDialog` | `QDialog` |
| `ExportPagesDialog` | `QDialog` |
| `MergePdfDialog` | `QDialog` |
| `OcrDialog` | `QDialog` |
| `OptimizePdfDialog` | `QDialog` |
*… 15 more inheritance edges not shown.*

## 6. Never-Called Symbols

> These functions/methods have no call-site reference detected by static AST analysis.
> **Caveats:** Qt signal-connected slots, `__dunder__` methods, and entry points called
> via `getattr`/reflection may appear here as false positives.

### 6.1 By File (ranked by count)

| File | Never-called count |
| ------------------------------------------------------- | ------------------ |
| `test_scripts/test_multi_tab_plan.py` | 72 |
| `test_scripts/test_text_editing_gui_regressions.py` | 55 |
| `view/pdf_view.py` | 50 |
| `test_scripts/test_theme_and_icons.py` | 38 |
| `test_scripts/test_edit_text_helpers.py` | 32 |
| `test_scripts/test_pdf_optimize_workflow.py` | 28 |
| `test_scripts/test_win_print_fixes.py` | 24 |
| `controller/pdf_controller.py` | 23 |
| `test_scripts/test_ocr_tool_surya.py` | 23 |
| `test_scripts/test_text_editing_fidelity_suite.py` | 23 |
| `test_scripts/test_print_layout.py` | 21 |
| `model/pdf_model.py` | 20 |
| `test_scripts/test_completion_proof_hook.py` | 20 |
| `test_scripts/test_ocr_types.py` | 20 |
| `test_scripts/test_main_startup_behavior.py` | 19 |
| `test_scripts/test_track_ab_5scenarios.py` | 17 |
| `test_scripts/test_object_manipulation_gui.py` | 15 |
| `test_scripts/test_ocr_dialog.py` | 15 |
| `test_scripts/test_geometry.py` | 14 |
| `test_scripts/test_pdf_merge_workflow.py` | 14 |
| `test_scripts/test_print_dialog_properties_button.py` | 14 |
| `test_scripts/test_security_ocr_weights.py` | 14 |
| `test_scripts/test_user_preferences.py` | 14 |
| `test_scripts/test_native_pdf_images_model.py` | 13 |
| `test_scripts/test_ocr_model_insert.py` | 12 |
| `test_scripts/test_qt_bridge_layout.py` | 12 |
| `test_scripts/test_no_jump_editor_geometry.py` | 11 |
| `test_scripts/test_ocr_e2e.py` | 11 |
| `test_scripts/test_text_edit_manager_foundation.py` | 11 |
| `test_scripts/test_text_normalization.py` | 11 |
| `test_scripts/test_text_extraction_line_joining.py` | 10 |
| `test_scripts/test_char_run_reconstruction.py` | 9 |
| `test_scripts/test_dialogs_package.py` | 9 |
| `test_scripts/test_drag_move.py` | 9 |
| `test_scripts/test_ocr_controller_flow.py` | 9 |
| `test_scripts/test_security_cua_allowlist.py` | 9 |
| `test_scripts/test_security_pdf_resource_guards.py` | 9 |
| `test_scripts/test_security_watermark_coercion.py` | 9 |
| `model/edit_commands.py` | 8 |
| `test_scripts/test_autopan.py` | 8 |
| `test_scripts/test_image_objects_model.py` | 8 |
| `test_scripts/test_short_term_safety.py` | 8 |
| `test_scripts/test_tool_extensions.py` | 8 |
| `src/printing/print_dialog.py` | 7 |
| `test_scripts/test_large_scale.py` | 7 |
| `test_scripts/test_object_manipulation_model.py` | 7 |
| `test_scripts/test_object_resize.py` | 7 |
| `test_scripts/test_structural_indexing.py` | 7 |
| `test_scripts/test_win_driver_properties.py` | 7 |
| `test_scripts/test_deep.py` | 6 |
| `test_scripts/test_linux_driver_overrides.py` | 6 |
| `test_scripts/test_native_image_discovery.py` | 6 |
| `test_scripts/test_object_free_rotation_gui.py` | 6 |
| `test_scripts/test_ocr_view_entry.py` | 6 |
| `test_scripts/test_print_subprocess_runner.py` | 6 |
| `test_scripts/test_text_selection.py` | 6 |
| `src/printing/subprocess_runner.py` | 5 |
| `test_scripts/test_add_textbox_atomic.py` | 5 |
| `test_scripts/test_core_interaction_audit.py` | 5 |
| `test_scripts/test_macos_menu.py` | 5 |
| `test_scripts/test_object_controller_flow.py` | 5 |
| `test_scripts/test_overlap_textbox_edit.py` | 5 |
| `test_scripts/test_page_deskew_scope.py` | 5 |
| `test_scripts/test_pdf_compliance.py` | 5 |
| `test_scripts/test_print_controller_flow.py` | 5 |
| `test_scripts/live_acrobat_parity_run.py` | 4 |
| `test_scripts/test_cli_argparse.py` | 4 |
| `test_scripts/test_color_profile_controller.py` | 4 |
| `test_scripts/test_cross_page_text_move.py` | 4 |
| `test_scripts/test_headless_merge.py` | 4 |
| `test_scripts/test_image_objects_gui.py` | 4 |
| `test_scripts/test_interaction_modes.py` | 4 |
| `test_scripts/test_object_multi_select.py` | 4 |
| `test_scripts/test_security_single_instance_isolation.py` | 4 |
| `test_scripts/test_security_subprocess_paths.py` | 4 |
| `test_scripts/test_single_instance_forwarding.py` | 4 |
| `test_scripts/test_thumbnail_context_menu.py` | 4 |
| `test_scripts/test_week1_model_regressions.py` | 4 |
| `test_scripts/test_xref_repair.py` | 4 |
| `model/pdf_optimizer.py` | 3 |
| `test_scripts/test_browse_selection_gui_regressions.py` | 3 |
| `test_scripts/test_color_profile_enum.py` | 3 |
| `test_scripts/test_color_profile_gui.py` | 3 |
| `test_scripts/test_feature_conflict.py` | 3 |
| `test_scripts/test_object_free_rotation.py` | 3 |
| `test_scripts/test_page_deskew.py` | 3 |
| `test_scripts/test_pdf_content_ops_cm_format.py` | 3 |
| `test_scripts/test_print_subprocess_helper.py` | 3 |
| `test_scripts/test_security_logging_level.py` | 3 |
| `test_scripts/test_security_ocr_requirements.py` | 3 |
| `test_scripts/test_security_pillow_floor.py` | 3 |
| `test_scripts/test_snapshot_restore.py` | 3 |
| `test_scripts/test_track_ab_model_regressions.py` | 3 |
| `view/dialogs/optimize.py` | 3 |
| `model/text_block.py` | 2 |
| `src/printing/base_driver.py` | 2 |
| `test_scripts/conftest.py` | 2 |
| `test_scripts/test_edit_geometry_stability.py` | 2 |
| `test_scripts/test_empty_text_edit.py` | 2 |
| `test_scripts/test_qt_pixmap_colorspaces.py` | 2 |
| `test_scripts/test_render_colorspace.py` | 2 |
| `test_scripts/test_resolve_target_mode.py` | 2 |
| `test_scripts/test_scene_context_menu.py` | 2 |
| `test_scripts/test_text_edit_finalize_outcome.py` | 2 |
| `test_scripts/test_ux_signoff_agent.py` | 2 |
| `view/text_editing.py` | 2 |
| `.agents/skills/ui-ux-pro-max/scripts/core.py` | 1 |
| `.agents/skills/ui-ux-pro-max/scripts/design_system.py` | 1 |
| `.agents/skills/ui-ux-pro-max/scripts/search.py` | 1 |
| `.claude/skills/ui-ux-pro-max/scripts/core.py` | 1 |
| `.claude/skills/ui-ux-pro-max/scripts/design_system.py` | 1 |
| `.claude/skills/ui-ux-pro-max/scripts/search.py` | 1 |
| `model/edit_requests.py` | 1 |
| `model/merge_session.py` | 1 |
| `model/tools/ocr_tool.py` | 1 |
| `model/tools/watermark_tool.py` | 1 |
| `src/printing/dispatcher.py` | 1 |
| `src/printing/helper_main.py` | 1 |
| `src/printing/platforms/linux_driver.py` | 1 |
| `src/printing/platforms/win_driver.py` | 1 |
| `test_scripts/core_interaction_audit.py` | 1 |
| `test_scripts/test_1pdf_audit.py` | 1 |
| `test_scripts/test_1pdf_horizontal.py` | 1 |
| `test_scripts/test_font_fix.py` | 1 |
| `test_scripts/test_object_requests.py` | 1 |
| `test_scripts/test_ocr_loading_status.py` | 1 |
| `test_scripts/test_ocr_predictor_cache.py` | 1 |
| `test_scripts/test_performance.py` | 1 |
| `test_scripts/test_performance_script_runner.py` | 1 |
| `test_scripts/test_print_colorspace.py` | 1 |
| `test_scripts/test_print_speed.py` | 1 |
| `test_scripts/test_render_clarity_dpr.py` | 1 |
| `test_scripts/test_rotated_text_editor_preview.py` | 1 |
| `test_scripts/test_security_dispatcher_temp_cleanup.py` | 1 |
| `view/theme.py` | 1 |
| `view/dialogs/audit.py` | 1 |
| `view/dialogs/export.py` | 1 |
| `view/dialogs/merge.py` | 1 |
| `view/dialogs/ocr.py` | 1 |
| `view/dialogs/password.py` | 1 |
| `view/dialogs/watermark.py` | 1 |

### 6.2 Full Never-Called Symbol List

| Kind | File | Line | Symbol |
| -------- | -------------------------------------------------- | ------ | -------------------------------------------------- |
| function | `.agents/skills/ui-ux-pro-max/scripts/core.py` | 234 | `search_stack` |
| function | `.agents/skills/ui-ux-pro-max/scripts/design_system.py` | 462 | `generate_design_system` |
| function | `.agents/skills/ui-ux-pro-max/scripts/search.py` | 30 | `format_output` |
| function | `.claude/skills/ui-ux-pro-max/scripts/core.py` | 233 | `search_stack` |
| function | `.claude/skills/ui-ux-pro-max/scripts/design_system.py` | 460 | `generate_design_system` |
| function | `.claude/skills/ui-ux-pro-max/scripts/search.py` | 30 | `format_output` |
| method | `controller/pdf_controller.py` | 165 | `_PrintWorkerBridge.forward_prepared` |
| method | `controller/pdf_controller.py` | 206 | `_OptimizeWorkerBridge.forward_succeeded` |
| method | `controller/pdf_controller.py` | 282 | `_OcrBridge.forward_status` |
| method | `controller/pdf_controller.py` | 341 | `PDFController.is_active` |
| method | `controller/pdf_controller.py` | 597 | `PDFController._on_color_profile_changed` |
| method | `controller/pdf_controller.py` | 950 | `PDFController.toggle_fullscreen` |
| method | `controller/pdf_controller.py` | 960 | `PDFController._on_viewport_changed` |
| method | `controller/pdf_controller.py` | 1305 | `PDFController._on_optimize_copy_succeeded` |
| method | `controller/pdf_controller.py` | 1322 | `PDFController._on_optimize_copy_failed` |
| method | `controller/pdf_controller.py` | 1327 | `PDFController._on_optimize_thread_finished` |
| method | `controller/pdf_controller.py` | 1448 | `PDFController._render_print_preview_image` |
| method | `controller/pdf_controller.py` | 1568 | `PDFController._on_print_job_prepared` |
| method | `controller/pdf_controller.py` | 1626 | `PDFController._on_print_thread_finished` |
| method | `controller/pdf_controller.py` | 2509 | `PDFController._on_ocr_progress` |
| method | `controller/pdf_controller.py` | 2518 | `PDFController._on_ocr_status` |
| method | `controller/pdf_controller.py` | 2525 | `PDFController._on_ocr_page_done` |
| method | `controller/pdf_controller.py` | 2532 | `PDFController._on_ocr_failed` |
| method | `controller/pdf_controller.py` | 2537 | `PDFController._on_ocr_thread_finished` |
| method | `controller/pdf_controller.py` | 2715 | `PDFController._on_request_rerender` |
| method | `controller/pdf_controller.py` | 2810 | `PDFController._update_mode` |
| method | `controller/pdf_controller.py` | 2854 | `PDFController.jump_to_annotation` |
| method | `controller/pdf_controller.py` | 2873 | `PDFController.snapshot_page` |
| method | `controller/pdf_controller.py` | 3071 | `PDFController.save_and_close` |
| method | `model/edit_commands.py` | 51 | `EditCommand.description` |
| method | `model/edit_commands.py` | 148 | `EditTextCommand.description` |
| method | `model/edit_commands.py` | 249 | `AddTextboxCommand.description` |
| method | `model/edit_commands.py` | 343 | `SnapshotCommand.description` |
| method | `model/edit_commands.py` | 347 | `SnapshotCommand.is_structural` |
| method | `model/edit_commands.py` | 352 | `SnapshotCommand.affected_pages` |
| method | `model/edit_commands.py` | 572 | `CommandManager.undo_count` |
| method | `model/edit_commands.py` | 577 | `CommandManager.redo_count` |
| method | `model/edit_requests.py` | 22 | `EditTextRequest.to_legacy_args` |
| method | `model/merge_session.py` | 96 | `MergeSessionModel.can_confirm` |
| method | `model/pdf_model.py` | 178 | `TextHit.__getitem__` |
| method | `model/pdf_model.py` | 181 | `TextHit.__iter__` |
| method | `model/pdf_model.py` | 184 | `TextHit.__len__` |
| method | `model/pdf_model.py` | 337 | `PDFModel.session_ids` |
| method | `model/pdf_model.py` | 379 | `PDFModel.activate_session_by_index` |
| method | `model/pdf_model.py` | 391 | `PDFModel.has_any_unsaved_changes` |
| method | `model/pdf_model.py` | 447 | `PDFModel.doc` |
| method | `model/pdf_model.py` | 460 | `PDFModel.original_path` |
| method | `model/pdf_model.py` | 473 | `PDFModel.saved_path` |
| method | `model/pdf_model.py` | 486 | `PDFModel.block_manager` |
| method | `model/pdf_model.py` | 499 | `PDFModel.command_manager` |
| method | `model/pdf_model.py` | 512 | `PDFModel.edit_count` |
| method | `model/pdf_model.py` | 525 | `PDFModel.pending_edits` |
| method | `model/pdf_model.py` | 545 | `PDFModel.run_reopen_anchors` |
| method | `model/pdf_model.py` | 558 | `PDFModel.run_reopen_anchor_sizes` |
| method | `model/pdf_model.py` | 934 | `PDFModel._y_overlaps` |
| method | `model/pdf_model.py` | 937 | `PDFModel._shift_rect_left` |
| method | `model/pdf_model.py` | 950 | `PDFModel._shift_rect_right` |
| method | `model/pdf_model.py` | 1513 | `PDFModel.capture_print_input_pdf_bytes` |
| method | `model/pdf_model.py` | 2156 | `PDFModel._iter_page_annots` |
| function | `model/pdf_optimizer.py` | 112 | `_init_image_rewrite_worker` |
| function | `model/pdf_optimizer.py` | 175 | `_rewrite_source_image_task` |
| function | `model/pdf_optimizer.py` | 188 | `_rewrite_extracted_image_task` |
| method | `model/text_block.py` | 112 | `TextBlock.__post_init__` |
| method | `model/text_block.py` | 340 | `TextBlockManager.find_overlapping_paragraphs` |
| method | `model/tools/ocr_tool.py` | 123 | `_SuryaAdapter.device` |
| method | `model/tools/watermark_tool.py` | 257 | `WatermarkTool._get_watermark_font` |
| method | `src/printing/base_driver.py` | 114 | `PrinterDriver.supports_direct_pdf` |
| method | `src/printing/base_driver.py` | 119 | `PrinterDriver.supports_printer_properties_dialog` |
| method | `src/printing/dispatcher.py` | 52 | `PrintDispatcher.supports_printer_properties_dialog` |
| function | `src/printing/helper_main.py` | 40 | `_stdout_emit` |
| method | `src/printing/platforms/linux_driver.py` | 28 | `LinuxPrinterDriver.supports_direct_pdf` |
| method | `src/printing/platforms/win_driver.py` | 268 | `WindowsPrinterDriver.supports_printer_properties_dialog` |
| method | `src/printing/print_dialog.py` | 370 | `UnifiedPrintDialog._open_printer_properties_dialog` |
| method | `src/printing/print_dialog.py` | 458 | `UnifiedPrintDialog._update_inherited_property_fields` |
| method | `src/printing/print_dialog.py` | 590 | `UnifiedPrintDialog._on_range_mode_changed` |
| method | `src/printing/print_dialog.py` | 595 | `UnifiedPrintDialog._on_scale_mode_changed` |
| method | `src/printing/print_dialog.py` | 611 | `UnifiedPrintDialog._on_preview_row_changed` |
| method | `src/printing/print_dialog.py` | 619 | `UnifiedPrintDialog._build_options` |
| method | `src/printing/print_dialog.py` | 622 | `UnifiedPrintDialog._refresh_preview` |
| method | `src/printing/subprocess_runner.py` | 124 | `PrintSubprocessRunner._on_ready_stdout` |
| method | `src/printing/subprocess_runner.py` | 139 | `PrintSubprocessRunner._on_ready_stderr` |
| method | `src/printing/subprocess_runner.py` | 175 | `PrintSubprocessRunner._check_stall` |
| method | `src/printing/subprocess_runner.py` | 186 | `PrintSubprocessRunner._on_error` |
| method | `src/printing/subprocess_runner.py` | 202 | `PrintSubprocessRunner._on_finished` |
| function | `test_scripts/conftest.py` | 19 | `qapp` |
| function | `test_scripts/conftest.py` | 26 | `_ensure_test_file_1_pdf` |
| function | `test_scripts/core_interaction_audit.py` | 287 | `_run_pytest_target` |
| function | `test_scripts/live_acrobat_parity_run.py` | 174 | `page_navigation_action` |
| function | `test_scripts/live_acrobat_parity_run.py` | 187 | `zoom_flow_action` |
| function | `test_scripts/live_acrobat_parity_run.py` | 204 | `reading_state_action` |
| function | `test_scripts/live_acrobat_parity_run.py` | 217 | `selection_copy_action` |
| function | `test_scripts/test_1pdf_audit.py` | 20 | `audit_1pdf` |
| function | `test_scripts/test_1pdf_horizontal.py` | 131 | `test_horizontal_edit_and_verify` |
| function | `test_scripts/test_add_textbox_atomic.py` | 50 | `test_add_textbox_rotation_anchor_visual_location` |
| function | `test_scripts/test_add_textbox_atomic.py` | 82 | `test_add_textbox_default_font_supports_cjk` |
| function | `test_scripts/test_add_textbox_atomic.py` | 105 | `test_add_textbox_atomic_undo_redo_boundaries` |
| function | `test_scripts/test_add_textbox_atomic.py` | 162 | `test_add_textbox_undo_keeps_other_page_objects` |
| function | `test_scripts/test_add_textbox_atomic.py` | 202 | `test_add_textbox_immediately_editable_by_hit_detection` |
| function | `test_scripts/test_autopan.py` | 156 | `test_middle_click_enters_autopan` |
| function | `test_scripts/test_autopan.py` | 171 | `test_second_middle_click_exits_autopan` |
| function | `test_scripts/test_autopan.py` | 185 | `test_right_click_exit_shows_context_menu` |
| function | `test_scripts/test_autopan.py` | 200 | `test_autopan_tick_scrolls_with_fractional_accumulation` |
| function | `test_scripts/test_autopan.py` | 218 | `test_autopan_mouse_move_updates_cursor_position` |
| function | `test_scripts/test_autopan.py` | 233 | `test_autopan_speed_scales_with_distance` |
| function | `test_scripts/test_autopan.py` | 256 | `test_context_menu_manual_bypasses_single_signal_suppression` |
| function | `test_scripts/test_autopan.py` | 298 | `test_autopan_real_view_enters_and_exits` |
| function | `test_scripts/test_browse_selection_gui_regressions.py` | 105 | `test_start_text_selection_requires_text_hit_and_stores_start_run` |
| function | `test_scripts/test_browse_selection_gui_regressions.py` | 135 | `test_start_text_selection_rejects_block_fallback_hits` |
| function | `test_scripts/test_browse_selection_gui_regressions.py` | 159 | `test_finalize_text_selection_uses_run_anchored_snapshot_and_preserves_start_hit_info` |
| function | `test_scripts/test_char_run_reconstruction.py` | 21 | `test_runs_merge_micro_spans_on_test_file_1` |
| function | `test_scripts/test_char_run_reconstruction.py` | 37 | `test_hit_and_edit_use_reconstructed_run` |
| function | `test_scripts/test_char_run_reconstruction.py` | 71 | `test_paragraph_mode_hit_and_redo_stability` |
| function | `test_scripts/test_char_run_reconstruction.py` | 126 | `test_paragraph_drag_without_text_change_with_overlap` |
| function | `test_scripts/test_char_run_reconstruction.py` | 170 | `test_paragraph_drag_twice_with_stale_span_id` |
| function | `test_scripts/test_char_run_reconstruction.py` | 239 | `test_1pdf_paragraph_target_excludes_overlapping_run_or_not_run` |
| function | `test_scripts/test_char_run_reconstruction.py` | 276 | `test_1pdf_text_hit_does_not_contain_replacement_character_when_plain_text_has_alternative` |
| function | `test_scripts/test_char_run_reconstruction.py` | 303 | `test_vertical_paragraph_groups_adjacent_columns_in_reading_order` |
| function | `test_scripts/test_char_run_reconstruction.py` | 335 | `test_phase2_paragraph_edit_preserves_mixed_color_runs` |
| function | `test_scripts/test_cli_argparse.py` | 23 | `test_parse_cli_accepts_positional_files` |
| function | `test_scripts/test_cli_argparse.py` | 32 | `test_parse_cli_supports_merge_output` |
| function | `test_scripts/test_cli_argparse.py` | 41 | `test_parse_cli_requires_input_for_merge` |
| function | `test_scripts/test_cli_argparse.py` | 48 | `test_run_merge_and_exit_is_headless` |
| function | `test_scripts/test_color_profile_controller.py` | 39 | `test_default_session_color_profile_is_srgb` |
| function | `test_scripts/test_color_profile_controller.py` | 44 | `test_set_session_color_profile_updates_state_and_triggers_render_and_thumbs` |
| function | `test_scripts/test_color_profile_controller.py` | 55 | `test_set_session_color_profile_rejects_unknown_profile` |
| function | `test_scripts/test_color_profile_controller.py` | 61 | `test_visible_render_dispatch_passes_session_colorspace` |
| function | `test_scripts/test_color_profile_enum.py` | 9 | `test_to_fitz_colorspace_maps_expected_profiles` |
| function | `test_scripts/test_color_profile_enum.py` | 15 | `test_color_profile_from_string_round_trips` |
| function | `test_scripts/test_color_profile_enum.py` | 21 | `test_unknown_profile_raises_value_error` |
| function | `test_scripts/test_color_profile_gui.py` | 8 | `test_color_profile_sidebar_combo_exists` |
| function | `test_scripts/test_color_profile_gui.py` | 20 | `test_color_profile_combo_emits_signal_on_user_change` |
| function | `test_scripts/test_color_profile_gui.py` | 30 | `test_set_color_profile_updates_combo_without_emitting` |
| function | `test_scripts/test_completion_proof_hook.py` | 68 | `tmp_gate` |
| function | `test_scripts/test_completion_proof_hook.py` | 85 | `test_hook_exits_0_when_no_goal_file` |
| function | `test_scripts/test_completion_proof_hook.py` | 97 | `test_hook_blocks_when_proof_absent` |
| function | `test_scripts/test_completion_proof_hook.py` | 109 | `test_hook_blocks_corrupt_proof` |
| function | `test_scripts/test_completion_proof_hook.py` | 121 | `test_hook_blocks_wrong_status` |
| function | `test_scripts/test_completion_proof_hook.py` | 138 | `test_hook_blocks_stale_commit` |
| function | `test_scripts/test_completion_proof_hook.py` | 156 | `test_hook_blocks_nonzero_exit_code` |
| function | `test_scripts/test_completion_proof_hook.py` | 174 | `test_hook_allows_valid_proof` |
| function | `test_scripts/test_completion_proof_hook.py` | 191 | `test_hook_blocks_missing_invocation_id` |
| function | `test_scripts/test_completion_proof_hook.py` | 208 | `test_hook_blocks_missing_tracked_scripts` |
| function | `test_scripts/test_completion_proof_hook.py` | 227 | `test_hook_blocks_forged_minimal_proof` |
| function | `test_scripts/test_completion_proof_hook.py` | 252 | `test_hook_blocks_gate_passed_file_absent` |
| function | `test_scripts/test_completion_proof_hook.py` | 269 | `test_hook_blocks_gate_passed_digest_mismatch` |
| function | `test_scripts/test_completion_proof_hook.py` | 288 | `test_hook_blocks_signoff_file_absent` |
| function | `test_scripts/test_completion_proof_hook.py` | 305 | `test_hook_blocks_signoff_digest_mismatch` |
| function | `test_scripts/test_completion_proof_hook.py` | 326 | `test_hook_real_goal_path_blocks_without_proof` |
| function | `test_scripts/test_completion_proof_hook.py` | 345 | `test_hook_blocks_self_consistent_forged_artifacts` |
| function | `test_scripts/test_completion_proof_hook.py` | 367 | `test_hook_allows_when_check_gate_passed_succeeds` |
| function | `test_scripts/test_completion_proof_hook.py` | 386 | `test_hook_blocks_when_goal_file_deleted_but_tracked` |
| function | `test_scripts/test_completion_proof_hook.py` | 405 | `test_hook_layer7_always_runs_on_repeated_calls` |
| function | `test_scripts/test_core_interaction_audit.py` | 16 | `test_default_core_interaction_plan_uses_three_existing_fixtures` |
| function | `test_scripts/test_core_interaction_audit.py` | 27 | `test_default_core_interaction_plan_includes_automated_manual_and_acrobat_scenarios` |
| function | `test_scripts/test_core_interaction_audit.py` | 39 | `test_run_audit_plan_marks_non_automated_scenarios_blocked` |
| function | `test_scripts/test_core_interaction_audit.py` | 64 | `test_render_markdown_report_includes_summary_and_blockers` |
| function | `test_scripts/test_core_interaction_audit.py` | 88 | `test_render_manual_checklist_includes_manual_steps_and_relative_fixture_paths` |
| function | `test_scripts/test_cross_page_text_move.py` | 54 | `test_move_text_across_pages_records_single_snapshot_command_and_undoes` |
| function | `test_scripts/test_cross_page_text_move.py` | 109 | `test_cross_page_move_unresolved_source_without_span_id_aborts_cleanly` |
| function | `test_scripts/test_cross_page_text_move.py` | 151 | `test_cross_page_move_stale_span_id_falls_back_to_rect_text_resolution` |
| function | `test_scripts/test_cross_page_text_move.py` | 186 | `test_cross_page_move_add_failure_restores_before_snapshot_and_refreshes_ui` |
| method | `test_scripts/test_deep.py` | 119 | `TestSuite.total` |
| method | `test_scripts/test_deep.py` | 121 | `TestSuite.passed` |
| method | `test_scripts/test_deep.py` | 123 | `TestSuite.failed` |
| method | `test_scripts/test_deep.py` | 125 | `TestSuite.pass_rate` |
| method | `test_scripts/test_deep.py` | 128 | `TestSuite.total_ms` |
| method | `test_scripts/test_deep.py` | 130 | `TestSuite.avg_ms` |
| function | `test_scripts/test_dialogs_package.py` | 9 | `test_password_dialog_importable` |
| function | `test_scripts/test_dialogs_package.py` | 15 | `test_merge_dialog_importable` |
| function | `test_scripts/test_dialogs_package.py` | 21 | `test_optimize_dialog_importable` |
| function | `test_scripts/test_dialogs_package.py` | 27 | `test_watermark_dialog_importable` |
| function | `test_scripts/test_dialogs_package.py` | 33 | `test_export_dialog_importable` |
| function | `test_scripts/test_dialogs_package.py` | 39 | `test_audit_classes_importable` |
| function | `test_scripts/test_dialogs_package.py` | 45 | `test_legacy_import_path_still_works` |
| function | `test_scripts/test_dialogs_package.py` | 63 | `test_password_dialog_basic` |
| function | `test_scripts/test_dialogs_package.py` | 70 | `test_export_dialog_basic` |
| function | `test_scripts/test_drag_move.py` | 98 | `_count_text_blocks` |
| method | `test_scripts/test_drag_move.py` | 155 | `TestResult.total` |
| method | `test_scripts/test_drag_move.py` | 159 | `TestResult.pass_rate` |
| function | `test_scripts/test_drag_move.py` | 177 | `test_A_basic_move` |
| function | `test_scripts/test_drag_move.py` | 214 | `test_B_move_and_edit` |
| function | `test_scripts/test_drag_move.py` | 251 | `test_C_moved_block_not_lost` |
| function | `test_scripts/test_drag_move.py` | 290 | `test_D_other_block_not_lost` |
| function | `test_scripts/test_drag_move.py` | 327 | `test_E_vertical_move` |
| function | `test_scripts/test_drag_move.py` | 359 | `test_F_boundary_clamp` |
| function | `test_scripts/test_edit_geometry_stability.py` | 33 | `test_repeated_identical_edits_keep_y1_drift_under_half_point` |
| function | `test_scripts/test_edit_geometry_stability.py` | 66 | `test_single_line_edit_preserves_anchor_and_does_not_push_neighbor` |
| function | `test_scripts/test_edit_text_helpers.py` | 21 | `model_with_pdf` |
| function | `test_scripts/test_edit_text_helpers.py` | 119 | `test_mode_default_no_args` |
| function | `test_scripts/test_edit_text_helpers.py` | 135 | `test_classify_insert_path_fast_vs_htmlbox` |
| function | `test_scripts/test_edit_text_helpers.py` | 179 | `test_mode_explicit_span_id` |
| function | `test_scripts/test_edit_text_helpers.py` | 196 | `test_mode_new_rect_promotes` |
| function | `test_scripts/test_edit_text_helpers.py` | 215 | `test_mode_explicit_paragraph` |
| function | `test_scripts/test_edit_text_helpers.py` | 231 | `test_mode_run_auto_promotes` |
| function | `test_scripts/test_edit_text_helpers.py` | 247 | `test_mode_run_no_promote_subsection` |
| function | `test_scripts/test_edit_text_helpers.py` | 263 | `test_resolve_target_happy_path` |
| function | `test_scripts/test_edit_text_helpers.py` | 280 | `test_resolve_target_missing_block` |
| function | `test_scripts/test_edit_text_helpers.py` | 292 | `test_resolve_target_no_change` |
| function | `test_scripts/test_edit_text_helpers.py` | 310 | `test_resolve_target_by_span_id` |
| function | `test_scripts/test_edit_text_helpers.py` | 329 | `test_apply_insert_basic` |
| function | `test_scripts/test_edit_text_helpers.py` | 338 | `test_apply_insert_empty_deletes` |
| function | `test_scripts/test_edit_text_helpers.py` | 345 | `test_apply_insert_preserves_others` |
| function | `test_scripts/test_edit_text_helpers.py` | 351 | `test_verify_rebuild_passes` |
| function | `test_scripts/test_edit_text_helpers.py` | 373 | `test_verify_rebuild_rollback` |
| function | `test_scripts/test_edit_text_helpers.py` | 398 | `test_phase2_single_line_run_edit_preserves_anchor_without_drag` |
| function | `test_scripts/test_edit_text_helpers.py` | 428 | `test_phase2_edit_text_preserves_fractional_font_size` |
| function | `test_scripts/test_edit_text_helpers.py` | 491 | `test_edit_preserves_font_size_pt_after_content_change` |
| function | `test_scripts/test_edit_text_helpers.py` | 537 | `test_edit_preserves_span_bbox_height_after_content_change` |
| function | `test_scripts/test_edit_text_helpers.py` | 590 | `test_single_line_edit_does_not_push_unedited_text` |
| function | `test_scripts/test_edit_text_helpers.py` | 656 | `test_prepush_growth_branch_does_not_raise_name_error` |
| function | `test_scripts/test_edit_text_helpers.py` | 711 | `test_render_width_for_edit_does_not_exceed_rect_width` |
| function | `test_scripts/test_edit_text_helpers.py` | 740 | `test_render_width_for_edit_signature_is_slimmed_to_page_and_rect` |
| function | `test_scripts/test_edit_text_helpers.py` | 747 | `test_repeated_edits_do_not_accumulate_size_drift` |
| function | `test_scripts/test_edit_text_helpers.py` | 802 | `_find_largest_font_span` |
| function | `test_scripts/test_edit_text_helpers.py` | 821 | `_find_any_editable_span` |
| function | `test_scripts/test_edit_text_helpers.py` | 868 | `test_build_insert_css_explicit_tight_line_height_not_clamped` |
| function | `test_scripts/test_edit_text_helpers.py` | 892 | `test_real_pdf_complexed_layout_edit_does_not_enlarge_span` |
| function | `test_scripts/test_edit_text_helpers.py` | 962 | `test_real_pdf_colored_background_edit_does_not_shrink_span` |
| function | `test_scripts/test_edit_text_helpers.py` | 1035 | `test_classify_insert_path_empty_member_spans_routes_to_htmlbox` |
| function | `test_scripts/test_empty_text_edit.py` | 64 | `test_controller_empty_edit_is_not_ignored` |
| function | `test_scripts/test_empty_text_edit.py` | 86 | `test_empty_edit_deletes_target_textbox_and_supports_undo_redo` |
| method | `test_scripts/test_feature_conflict.py` | 61 | `ConceptResult.total` |
| method | `test_scripts/test_feature_conflict.py` | 63 | `ConceptResult.passed` |
| method | `test_scripts/test_feature_conflict.py` | 65 | `ConceptResult.pass_rate` |
| function | `test_scripts/test_font_fix.py` | 19 | `test_html_conversion` |
| function | `test_scripts/test_geometry.py` | 9 | `test_clamp_inside_page_unchanged` |
| function | `test_scripts/test_geometry.py` | 14 | `test_clamp_overflow_right` |
| function | `test_scripts/test_geometry.py` | 19 | `test_clamp_overflow_bottom` |
| function | `test_scripts/test_geometry.py` | 24 | `test_clamp_degenerate_is_nonempty` |
| function | `test_scripts/test_geometry.py` | 29 | `test_rect_from_points_basic` |
| function | `test_scripts/test_geometry.py` | 34 | `test_rect_from_points_multiple` |
| function | `test_scripts/test_geometry.py` | 40 | `test_rect_union_empty` |
| function | `test_scripts/test_geometry.py` | 44 | `test_rect_union_single` |
| function | `test_scripts/test_geometry.py` | 49 | `test_rect_union_two` |
| function | `test_scripts/test_geometry.py` | 54 | `test_rect_union_three` |
| function | `test_scripts/test_geometry.py` | 59 | `test_overlap_ratio_no_overlap` |
| function | `test_scripts/test_geometry.py` | 63 | `test_overlap_ratio_full_contain` |
| function | `test_scripts/test_geometry.py` | 68 | `test_overlap_ratio_partial` |
| function | `test_scripts/test_geometry.py` | 74 | `test_overlap_ratio_empty_rect` |
| function | `test_scripts/test_headless_merge.py` | 25 | `test_headless_merge_combines_inputs` |
| function | `test_scripts/test_headless_merge.py` | 43 | `test_headless_merge_rejects_empty_inputs` |
| function | `test_scripts/test_headless_merge.py` | 48 | `test_headless_merge_rejects_missing_input` |
| function | `test_scripts/test_headless_merge.py` | 53 | `test_headless_merge_rejects_missing_output_directory` |
| function | `test_scripts/test_image_objects_gui.py` | 35 | `test_insert_image_from_file_emits_request` |
| function | `test_scripts/test_image_objects_gui.py` | 52 | `test_insert_image_from_clipboard_emits_request` |
| function | `test_scripts/test_image_objects_gui.py` | 66 | `test_insert_image_from_file_current_page_uses_default_target` |
| function | `test_scripts/test_image_objects_gui.py` | 88 | `test_insert_image_from_clipboard_current_page_uses_default_target` |
| function | `test_scripts/test_image_objects_model.py` | 37 | `test_add_image_object_creates_marker_and_hit_detection` |
| function | `test_scripts/test_image_objects_model.py` | 68 | `test_move_image_object_updates_hit_location` |
| function | `test_scripts/test_image_objects_model.py` | 98 | `test_rotate_image_object_updates_rotation_metadata` |
| function | `test_scripts/test_image_objects_model.py` | 127 | `test_delete_image_object_removes_marker_and_page_image_ref` |
| function | `test_scripts/test_image_objects_model.py` | 156 | `test_image_object_persists_through_save_and_reopen` |
| function | `test_scripts/test_image_objects_model.py` | 180 | `test_move_overlapping_app_images_both_survive` |
| function | `test_scripts/test_image_objects_model.py` | 224 | `test_rotate_overlapping_app_image_neighbour_survives` |
| function | `test_scripts/test_image_objects_model.py` | 260 | `test_move_second_of_identical_app_images_moves_correct_placement` |
| function | `test_scripts/test_interaction_modes.py` | 121 | `test_objects_mode_blocks_browse_text_selection_start` |
| function | `test_scripts/test_interaction_modes.py` | 132 | `test_browse_mode_does_not_start_object_manipulation` |
| function | `test_scripts/test_interaction_modes.py` | 143 | `test_text_edit_mode_does_not_select_rect_or_image` |
| function | `test_scripts/test_interaction_modes.py` | 154 | `test_text_edit_mode_allows_textbox_object_select` |
| method | `test_scripts/test_large_scale.py` | 132 | `Metrics.attempts` |
| method | `test_scripts/test_large_scale.py` | 136 | `Metrics.success_count` |
| method | `test_scripts/test_large_scale.py` | 140 | `Metrics.error_rate` |
| method | `test_scripts/test_large_scale.py` | 144 | `Metrics.avg_ms` |
| method | `test_scripts/test_large_scale.py` | 148 | `Metrics.max_ms` |
| method | `test_scripts/test_large_scale.py` | 152 | `Metrics.min_ms` |
| method | `test_scripts/test_large_scale.py` | 156 | `Metrics.slow_count` |
| function | `test_scripts/test_linux_driver_overrides.py` | 16 | `test_to_cups_options_omits_hardware_defaults_when_not_overridden` |
| function | `test_scripts/test_linux_driver_overrides.py` | 37 | `test_to_cups_options_includes_hardware_defaults_when_overridden` |
| function | `test_scripts/test_linux_driver_overrides.py` | 51 | `test_submit_via_lp_omits_hardware_options_when_not_overridden` |
| function | `test_scripts/test_linux_driver_overrides.py` | 95 | `test_submit_via_lp_includes_hardware_options_when_overridden` |
| function | `test_scripts/test_linux_driver_overrides.py` | 131 | `test_print_pdf_keeps_direct_pdf_for_source_following_auto_layout` |
| function | `test_scripts/test_linux_driver_overrides.py` | 167 | `test_print_pdf_forces_raster_when_user_overrides_layout` |
| function | `test_scripts/test_macos_menu.py` | 57 | `test_build_macos_menu_bar_is_noop_off_darwin` |
| function | `test_scripts/test_macos_menu.py` | 67 | `test_macos_menu_spec_has_expected_menus_and_actions` |
| function | `test_scripts/test_macos_menu.py` | 94 | `test_macos_menu_uses_native_shortcuts` |
| function | `test_scripts/test_macos_menu.py` | 112 | `test_build_macos_menu_bar_assembles_menus_on_darwin` |
| function | `test_scripts/test_macos_menu.py` | 137 | `test_app_menu_actions_have_macos_roles` |
| function | `test_scripts/test_main_startup_behavior.py` | 60 | `test_empty_launch_keeps_backend_detached_until_document_request` |
| function | `test_scripts/test_main_startup_behavior.py` | 78 | `test_cli_open_path_keeps_controller_attached_before_opening_documents` |
| function | `test_scripts/test_main_startup_behavior.py` | 99 | `test_pdf_view_emits_shell_ready_before_lazy_panel_hydration` |
| function | `test_scripts/test_main_startup_behavior.py` | 136 | `test_empty_launch_keeps_heavy_panels_lazy_until_pdf_open` |
| function | `test_scripts/test_main_startup_behavior.py` | 165 | `test_lazy_shell_hydrates_panels_when_user_opens_search_tab` |
| function | `test_scripts/test_main_startup_behavior.py` | 185 | `test_empty_launch_buffers_dropped_pdf_paths_until_controller_attaches` |
| function | `test_scripts/test_main_startup_behavior.py` | 217 | `test_empty_launch_buffers_multi_drop_pdf_paths_in_order_until_controller_attaches` |
| function | `test_scripts/test_main_startup_behavior.py` | 252 | `test_cli_open_builds_placeholder_geometry_before_background_rasterization` |
| function | `test_scripts/test_main_startup_behavior.py` | 269 | `test_cli_open_defers_annotation_and_watermark_sidebar_scans` |
| function | `test_scripts/test_main_startup_behavior.py` | 305 | `test_change_scale_does_not_rerender_every_page_in_continuous_mode` |
| function | `test_scripts/test_main_startup_behavior.py` | 334 | `test_reset_empty_ui_tolerates_lazy_shell_without_heavy_panels` |
| function | `test_scripts/test_main_startup_behavior.py` | 355 | `test_empty_launch_cancelled_password_prompt_returns_to_empty_shell` |
| function | `test_scripts/test_main_startup_behavior.py` | 386 | `test_panel_helpers_do_not_emit_sidebar_reload_signals` |
| function | `test_scripts/test_main_startup_behavior.py` | 405 | `test_watermark_mutations_reload_sidebar_once` |
| function | `test_scripts/test_main_startup_behavior.py` | 447 | `test_show_page_schedules_visible_render_once_in_continuous_mode` |
| function | `test_scripts/test_main_startup_behavior.py` | 469 | `test_rebuild_continuous_scene_schedules_visible_render_once` |
| function | `test_scripts/test_main_startup_behavior.py` | 491 | `test_render_active_session_prioritizes_visible_render_before_background_loading` |
| function | `test_scripts/test_main_startup_behavior.py` | 543 | `test_initial_high_quality_render_starts_background_loading_once` |
| function | `test_scripts/test_main_startup_behavior.py` | 573 | `test_schedule_visible_render_coalesces_pending_batches` |
| function | `test_scripts/test_multi_tab_plan.py` | 188 | `qapp` |
| function | `test_scripts/test_multi_tab_plan.py` | 196 | `mvc` |
| function | `test_scripts/test_multi_tab_plan.py` | 211 | `test_01_open_two_and_switch_tabs` |
| function | `test_scripts/test_multi_tab_plan.py` | 228 | `test_02_duplicate_open_focus_existing` |
| function | `test_scripts/test_multi_tab_plan.py` | 238 | `test_drag_drop_opens_multiple_local_pdfs_in_order` |
| function | `test_scripts/test_multi_tab_plan.py` | 258 | `test_drag_drop_ignores_non_pdf_folder_and_remote_urls` |
| function | `test_scripts/test_multi_tab_plan.py` | 286 | `test_drag_drop_multiple_pdfs_never_calls_merge_paths` |
| function | `test_scripts/test_multi_tab_plan.py` | 316 | `test_03_edit_in_a_undo_in_b_isolated` |
| function | `test_scripts/test_multi_tab_plan.py` | 334 | `test_04_structural_undo_redo_isolated` |
| function | `test_scripts/test_multi_tab_plan.py` | 355 | `test_04b_structural_actions_schedule_stale_index_drain` |
| function | `test_scripts/test_multi_tab_plan.py` | 370 | `test_04c_structural_metadata_uses_actual_blank_insert_position` |
| function | `test_scripts/test_multi_tab_plan.py` | 381 | `test_04d_structural_metadata_uses_actual_import_insert_positions` |
| function | `test_scripts/test_multi_tab_plan.py` | 393 | `test_04e_structural_metadata_uses_actual_deleted_pages` |
| function | `test_scripts/test_multi_tab_plan.py` | 404 | `test_05_search_state_restored_per_tab` |
| function | `test_scripts/test_multi_tab_plan.py` | 424 | `test_06_rapid_switch_has_no_stale_async_render` |
| function | `test_scripts/test_multi_tab_plan.py` | 439 | `test_06a_thumbnail_list_enforces_single_column_layout` |
| function | `test_scripts/test_multi_tab_plan.py` | 446 | `test_06b_thumbnail_click_navigation_with_single_column` |
| function | `test_scripts/test_multi_tab_plan.py` | 460 | `test_06c_thumbnail_layout_fills_sidebar_width_and_has_spacing` |
| function | `test_scripts/test_multi_tab_plan.py` | 472 | `test_06d_thumbnail_list_auto_scrolls_with_page_scroll` |
| function | `test_scripts/test_multi_tab_plan.py` | 489 | `test_06e_landscape_thumbnail_does_not_create_tall_blank_cell` |
| function | `test_scripts/test_multi_tab_plan.py` | 501 | `test_06f_thumbnail_layout_caps_width_and_centers_in_wide_sidebar` |
| function | `test_scripts/test_multi_tab_plan.py` | 519 | `test_07_close_modified_tab_cancel_keeps_tab` |
| function | `test_scripts/test_multi_tab_plan.py` | 533 | `test_08_close_modified_tab_save_then_close` |
| function | `test_scripts/test_multi_tab_plan.py` | 553 | `test_09_app_close_cancel_and_save_all_paths` |
| function | `test_scripts/test_multi_tab_plan.py` | 613 | `test_10_save_as_path_collision_blocked` |
| function | `test_scripts/test_multi_tab_plan.py` | 630 | `test_10a_active_session_updates_view_save_as_default_path` |
| function | `test_scripts/test_multi_tab_plan.py` | 649 | `test_11_close_last_tab_resets_ui` |
| function | `test_scripts/test_multi_tab_plan.py` | 662 | `test_12_cli_style_multi_open_loop` |
| function | `test_scripts/test_multi_tab_plan.py` | 676 | `test_13_ctrl_tab_switches_to_right_tab` |
| function | `test_scripts/test_multi_tab_plan.py` | 692 | `test_14_ctrl_shift_tab_switches_to_left_tab` |
| function | `test_scripts/test_multi_tab_plan.py` | 709 | `test_15_ctrl_tab_on_toolbar_does_not_switch_toolbar_tabs` |
| function | `test_scripts/test_multi_tab_plan.py` | 728 | `test_16_ctrl_shift_tab_on_sidebar_does_not_switch_sidebar_tabs` |
| function | `test_scripts/test_multi_tab_plan.py` | 748 | `test_17_fit_to_view_syncs_zoom_state_to_current_page_fit_scale` |
| function | `test_scripts/test_multi_tab_plan.py` | 775 | `test_17b_zoom_combo_keeps_only_default_options` |
| function | `test_scripts/test_multi_tab_plan.py` | 791 | `test_18_mode_checked_state_sync_and_restore` |
| function | `test_scripts/test_multi_tab_plan.py` | 811 | `test_19_escape_with_editor_closes_editor_but_keeps_mode` |
| function | `test_scripts/test_multi_tab_plan.py` | 828 | `test_19a_inline_existing_text_escape_discards_changes` |
| function | `test_scripts/test_multi_tab_plan.py` | 846 | `test_19aa_inline_existing_text_ctrl_z_undoes_locally` |
| function | `test_scripts/test_multi_tab_plan.py` | 869 | `test_19aaa_inline_existing_text_ctrl_z_on_real_multicolor_pdf_keeps_document_undo_idle` |
| function | `test_scripts/test_multi_tab_plan.py` | 895 | `test_19ab_inline_existing_text_ctrl_z_after_commit_undoes_document` |
| function | `test_scripts/test_multi_tab_plan.py` | 930 | `test_19ac_inline_existing_text_cross_page_move_roundtrips_via_document_undo_redo` |
| function | `test_scripts/test_multi_tab_plan.py` | 986 | `test_19b_font_size_menu_keeps_editor_and_outside_focus_finalizes_editor` |
| function | `test_scripts/test_multi_tab_plan.py` | 1037 | `test_19c_edit_font_change_commits_without_text_change` |
| function | `test_scripts/test_multi_tab_plan.py` | 1084 | `test_19d_text_apply_commits_and_cancel_discards` |
| function | `test_scripts/test_multi_tab_plan.py` | 1166 | `test_19e_cjk_font_change_commits_without_text_change` |
| function | `test_scripts/test_multi_tab_plan.py` | 1212 | `test_19f_convert_text_to_html_uses_cjk_companion_font` |
| function | `test_scripts/test_multi_tab_plan.py` | 1220 | `test_19f2_custom_cjk_font_generates_embedded_css` |
| function | `test_scripts/test_multi_tab_plan.py` | 1231 | `test_19g_add_text_cjk_font_selection_commits` |
| function | `test_scripts/test_multi_tab_plan.py` | 1263 | `test_19h_edit_existing_switch_to_dfkai_commits_font_token` |
| function | `test_scripts/test_multi_tab_plan.py` | 1306 | `test_19i_custom_windows_cjk_fonts_render_distinct_span_fonts` |
| function | `test_scripts/test_multi_tab_plan.py` | 1341 | `test_19j_font_popup_interaction_can_refocus_editor_without_finalize` |
| function | `test_scripts/test_multi_tab_plan.py` | 1391 | `test_20_escape_non_browse_switches_to_browse` |
| function | `test_scripts/test_multi_tab_plan.py` | 1404 | `test_21_escape_browse_fallback_keeps_existing_sidebar_behavior` |
| function | `test_scripts/test_multi_tab_plan.py` | 1417 | `test_22_sticky_highlight_mode_after_draw` |
| function | `test_scripts/test_multi_tab_plan.py` | 1442 | `test_23_sticky_add_annotation_mode_after_click` |
| function | `test_scripts/test_multi_tab_plan.py` | 1463 | `test_24_open_existing_file_keeps_current_mode` |
| function | `test_scripts/test_multi_tab_plan.py` | 1482 | `test_25_close_last_tab_keeps_mode_when_window_stays_open` |
| function | `test_scripts/test_multi_tab_plan.py` | 1501 | `test_26_fullscreen_no_document_is_noop` |
| function | `test_scripts/test_multi_tab_plan.py` | 1513 | `test_27_fullscreen_enter_and_escape_restore_chrome` |
| function | `test_scripts/test_multi_tab_plan.py` | 1545 | `test_28_fullscreen_restores_zoom_scroll_and_dirty_state` |
| function | `test_scripts/test_multi_tab_plan.py` | 1580 | `test_29_fullscreen_clears_search_and_cancels_editor` |
| function | `test_scripts/test_multi_tab_plan.py` | 1612 | `test_30_fullscreen_blocked_while_print_busy_or_modal` |
| function | `test_scripts/test_multi_tab_plan.py` | 1636 | `test_31_fullscreen_exit_button_stays_visible` |
| function | `test_scripts/test_multi_tab_plan.py` | 1660 | `test_32_fullscreen_tab_switch_restores_each_visited_tab_state` |
| function | `test_scripts/test_multi_tab_plan.py` | 1713 | `test_33_fullscreen_from_highlight_mode_cancels_partial_state_and_enters_browse` |
| function | `test_scripts/test_multi_tab_plan.py` | 1736 | `test_34_fullscreen_quick_button_sits_between_fit_and_undo_and_f5_toggles` |
| function | `test_scripts/test_multi_tab_plan.py` | 1755 | `test_34a_fullscreen_quick_button_has_12px_gap_from_fit_button` |
| function | `test_scripts/test_multi_tab_plan.py` | 1768 | `test_34b_fullscreen_context_menu_offers_exit_action_and_triggers_toggle` |
| function | `test_scripts/test_multi_tab_plan.py` | 1797 | `test_35_ctrl_alt_l_toggles_left_sidebar_with_focus_and_width_fallback` |
| function | `test_scripts/test_multi_tab_plan.py` | 1824 | `test_36_ctrl_f_reopens_hidden_left_sidebar_and_focuses_search` |
| function | `test_scripts/test_multi_tab_plan.py` | 1845 | `test_37_ctrl_alt_r_toggles_right_sidebar_with_focus_and_width_fallback` |
| function | `test_scripts/test_multi_tab_plan.py` | 1874 | `test_38_fullscreen_restores_user_hidden_sidebars` |
| function | `test_scripts/test_native_image_discovery.py` | 46 | `test_awareness_form_nested_image_is_discovered` |
| function | `test_scripts/test_native_image_discovery.py` | 61 | `test_awareness_image_is_hit_testable` |
| function | `test_scripts/test_native_image_discovery.py` | 76 | `test_awareness_image_can_be_moved` |
| function | `test_scripts/test_native_image_discovery.py` | 104 | `test_awareness_image_can_be_resized` |
| function | `test_scripts/test_native_image_discovery.py` | 129 | `test_awareness_image_can_be_deleted` |
| function | `test_scripts/test_native_image_discovery.py` | 146 | `test_report_direct_images_still_discovered` |
| function | `test_scripts/test_native_pdf_images_model.py` | 100 | `test_native_image_hit_detection_returns_native_kind` |
| function | `test_scripts/test_native_pdf_images_model.py` | 121 | `test_native_image_hit_prefers_topmost_invocation` |
| function | `test_scripts/test_native_pdf_images_model.py` | 139 | `test_move_native_image_updates_hit_location` |
| function | `test_scripts/test_native_pdf_images_model.py` | 170 | `test_resize_native_image_updates_hit_location` |
| function | `test_scripts/test_native_pdf_images_model.py` | 199 | `test_rotate_native_image_preserves_bbox_and_updates_rotation` |
| function | `test_scripts/test_native_pdf_images_model.py` | 230 | `test_delete_native_image_removes_one_invocation_but_keeps_shared_resource` |
| function | `test_scripts/test_native_pdf_images_model.py` | 257 | `test_delete_native_image_prunes_unused_resource_name` |
| function | `test_scripts/test_native_pdf_images_model.py` | 283 | `test_delete_native_image_does_not_delete_nested_sibling_in_outer_q` |
| function | `test_scripts/test_native_pdf_images_model.py` | 311 | `test_native_discovery_does_not_depend_on_get_image_info_order` |
| function | `test_scripts/test_native_pdf_images_model.py` | 343 | `test_native_discovery_survives_missing_get_image_info` |
| function | `test_scripts/test_native_pdf_images_model.py` | 362 | `test_native_bbox_matches_get_image_info_on_cropped_page` |
| function | `test_scripts/test_native_pdf_images_model.py` | 380 | `test_native_discovery_survives_no_cm_invocation` |
| function | `test_scripts/test_native_pdf_images_model.py` | 399 | `test_native_no_cm_invocation_rejects_move_and_rotate` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 355 | `test_editor_geometry_matches_pdf_bbox` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 426 | `test_geometry_negative_control_x_offset` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 456 | `test_geometry_negative_control_wrong_font_size` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 501 | `test_click_to_edit_real_geometry_pipeline` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 736 | `test_click_to_edit_qtest_integration` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 989 | `test_click_to_edit_then_insert_then_delete_stays_stable` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 1183 | `test_click_to_edit_continuous_insertions_then_delete_stays_stable` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 1369 | `test_reopen_same_textbox_cycles_do_not_cumulate_shrink` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 1711 | `test_blanking_detector_catches_a_blank_image` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 1748 | `test_preview_pixel_diff_under_one_pct` |
| function | `test_scripts/test_no_jump_editor_geometry.py` | 1811 | `test_pixel_diff_negative_control_bad_font_size` |
| function | `test_scripts/test_object_controller_flow.py` | 61 | `test_controller_delegates_object_hit_info` |
| function | `test_scripts/test_object_controller_flow.py` | 69 | `test_controller_records_snapshot_for_move_object` |
| function | `test_scripts/test_object_controller_flow.py` | 79 | `test_controller_records_snapshot_for_batch_move_object` |
| function | `test_scripts/test_object_controller_flow.py` | 95 | `test_controller_records_snapshot_for_rotate_and_delete_object` |
| function | `test_scripts/test_object_controller_flow.py` | 108 | `test_controller_records_snapshot_for_batch_delete_object` |
| function | `test_scripts/test_object_free_rotation.py` | 41 | `test_free_rotate_native_image_to_30_degrees` |
| function | `test_scripts/test_object_free_rotation.py` | 74 | `test_moving_a_freely_rotated_image_preserves_its_angle` |
| function | `test_scripts/test_object_free_rotation.py` | 123 | `test_resizing_a_rotated_image_does_not_inflate_geometry` |
| function | `test_scripts/test_object_free_rotation_gui.py` | 33 | `test_screen_angle_is_clockwise_in_scene_coords` |
| function | `test_scripts/test_object_free_rotation_gui.py` | 40 | `test_absolute_rotation_from_drag_matches_clockwise_direction` |
| function | `test_scripts/test_object_free_rotation_gui.py` | 149 | `test_rotate_handle_drag_emits_absolute_rotation` |
| function | `test_scripts/test_object_free_rotation_gui.py` | 169 | `test_textbox_drag_rotate_does_not_emit_absolute_rotation` |
| function | `test_scripts/test_object_free_rotation_gui.py` | 195 | `test_apply_selection_rotation_turns_box_and_handles` |
| function | `test_scripts/test_object_free_rotation_gui.py` | 214 | `test_rotate_handle_click_without_drag_uses_90_step` |
| function | `test_scripts/test_object_manipulation_gui.py` | 161 | `test_objects_mouse_press_selects_object_and_blocks_text_selection` |
| function | `test_scripts/test_object_manipulation_gui.py` | 175 | `test_objects_mouse_press_selects_native_image` |
| function | `test_scripts/test_object_manipulation_gui.py` | 190 | `test_event_scene_pos_normalizes_viewport_offset` |
| function | `test_scripts/test_object_manipulation_gui.py` | 196 | `test_delete_selected_object_emits_request` |
| function | `test_scripts/test_object_manipulation_gui.py` | 204 | `test_rotate_selected_object_emits_request` |
| function | `test_scripts/test_object_manipulation_gui.py` | 212 | `test_delete_shortcut_works_in_objects_mode` |
| function | `test_scripts/test_object_manipulation_gui.py` | 224 | `test_delete_shortcut_works_in_text_edit_mode` |
| function | `test_scripts/test_object_manipulation_gui.py` | 236 | `test_browse_object_drag_threshold_starts_drag` |
| function | `test_scripts/test_object_manipulation_gui.py` | 254 | `test_text_edit_mouse_press_on_rotate_handle_does_not_arm_free_rotation` |
| function | `test_scripts/test_object_manipulation_gui.py` | 271 | `test_textbox_rotate_pending_release_uses_legacy_90_step` |
| function | `test_scripts/test_object_manipulation_gui.py` | 291 | `test_scene_context_menu_includes_object_actions` |
| function | `test_scripts/test_object_manipulation_gui.py` | 327 | `test_objects_context_menu_exposes_image_insert_actions` |
| function | `test_scripts/test_object_manipulation_gui.py` | 365 | `test_objects_mode_move_release_rebases_selected_object_info_immediately` |
| function | `test_scripts/test_object_manipulation_gui.py` | 413 | `test_objects_mode_move_release_rebases_when_preview_rects_populated` |
| function | `test_scripts/test_object_manipulation_gui.py` | 474 | `test_add_image_object_clears_stale_object_selection_in_view` |
| function | `test_scripts/test_object_manipulation_model.py` | 30 | `test_add_textbox_creates_hidden_object_marker_and_hit_detection` |
| function | `test_scripts/test_object_manipulation_model.py` | 61 | `test_get_object_info_ignores_legacy_text_without_marker` |
| function | `test_scripts/test_object_manipulation_model.py` | 75 | `test_add_rect_creates_object_metadata_and_hit_detection` |
| function | `test_scripts/test_object_manipulation_model.py` | 93 | `test_move_rect_object_updates_hit_location` |
| function | `test_scripts/test_object_manipulation_model.py` | 123 | `test_delete_rect_object_removes_annotation` |
| function | `test_scripts/test_object_manipulation_model.py` | 148 | `test_rotate_textbox_object_updates_rotation_metadata` |
| function | `test_scripts/test_object_manipulation_model.py` | 178 | `test_delete_textbox_after_move_and_rotate_removes_all_markers` |
| function | `test_scripts/test_object_multi_select.py` | 143 | `test_shift_click_toggles_objects_on_same_page` |
| function | `test_scripts/test_object_multi_select.py` | 164 | `test_click_on_other_page_resets_selection_set` |
| function | `test_scripts/test_object_multi_select.py` | 183 | `test_batch_delete_emits_one_request` |
| function | `test_scripts/test_object_multi_select.py` | 201 | `test_batch_move_emits_one_request` |
| function | `test_scripts/test_object_requests.py` | 15 | `test_object_request_shapes` |
| function | `test_scripts/test_object_resize.py` | 169 | `test_single_select_creates_resize_handles_and_hit_outside_bbox` |
| function | `test_scripts/test_object_resize.py` | 185 | `test_resize_drag_emits_resize_request` |
| function | `test_scripts/test_object_resize.py` | 204 | `test_top_left_handle_drag_moves_x0_y0_preserves_x1_y1` |
| function | `test_scripts/test_object_resize.py` | 229 | `test_compute_resize_rect_free_form_changes_aspect_ratio` |
| function | `test_scripts/test_object_resize.py` | 239 | `test_compute_resize_rect_shift_locks_aspect_ratio` |
| function | `test_scripts/test_object_resize.py` | 250 | `test_compute_resize_rect_lock_keeps_opposite_corner_for_tl` |
| function | `test_scripts/test_object_resize.py` | 259 | `test_bottom_left_handle_drag_moves_x0_y1_preserves_x1_y0` |
| function | `test_scripts/test_ocr_controller_flow.py` | 65 | `test_worker_emits_page_done_and_progress` |
| function | `test_scripts/test_ocr_controller_flow.py` | 84 | `test_worker_runs_on_non_gui_thread` |
| function | `test_scripts/test_ocr_controller_flow.py` | 94 | `test_worker_respects_cancel_between_pages` |
| function | `test_scripts/test_ocr_controller_flow.py` | 116 | `test_worker_emits_failed_on_tool_exception` |
| function | `test_scripts/test_ocr_controller_flow.py` | 130 | `test_worker_forwards_device_and_languages` |
| function | `test_scripts/test_ocr_controller_flow.py` | 137 | `test_ocr_bridge_forwards_signals` |
| function | `test_scripts/test_ocr_controller_flow.py` | 160 | `test_controller_start_ocr_refuses_when_surya_missing` |
| function | `test_scripts/test_ocr_controller_flow.py` | 173 | `test_controller_start_ocr_applies_spans_per_page` |
| function | `test_scripts/test_ocr_controller_flow.py` | 193 | `test_controller_cancel_ocr_sets_worker_flag` |
| function | `test_scripts/test_ocr_dialog.py` | 32 | `test_dialog_defaults_to_current_page` |
| function | `test_scripts/test_ocr_dialog.py` | 39 | `test_dialog_switching_to_custom_enables_range_edit` |
| function | `test_scripts/test_ocr_dialog.py` | 47 | `test_dialog_custom_range_with_multi_lang_produces_request` |
| function | `test_scripts/test_ocr_dialog.py` | 62 | `test_dialog_current_page_option_returns_current_index` |
| function | `test_scripts/test_ocr_dialog.py` | 70 | `test_dialog_whole_document_returns_all_pages` |
| function | `test_scripts/test_ocr_dialog.py` | 80 | `test_dialog_invalid_range_disables_ok` |
| function | `test_scripts/test_ocr_dialog.py` | 90 | `test_dialog_validation_clears_when_range_fixed` |
| function | `test_scripts/test_ocr_dialog.py` | 104 | `test_dialog_reject_returns_none` |
| function | `test_scripts/test_ocr_dialog.py` | 110 | `test_dialog_no_languages_selected_disables_ok` |
| function | `test_scripts/test_ocr_dialog.py` | 118 | `test_dialog_seeds_device_from_preferences` |
| function | `test_scripts/test_ocr_dialog.py` | 124 | `test_dialog_persists_device_choice_to_preferences` |
| function | `test_scripts/test_ocr_dialog.py` | 139 | `test_dialog_request_carries_device` |
| function | `test_scripts/test_ocr_dialog.py` | 148 | `test_dialog_pre_checks_languages_from_preferences` |
| function | `test_scripts/test_ocr_dialog.py` | 156 | `test_dialog_disables_cuda_and_mps_when_unavailable` |
| function | `test_scripts/test_ocr_dialog.py` | 174 | `test_dialog_default_falls_back_when_stored_pref_unavailable` |
| function | `test_scripts/test_ocr_e2e.py` | 23 | `_surya_available` |
| function | `test_scripts/test_ocr_e2e.py` | 38 | `eng_model` |
| function | `test_scripts/test_ocr_e2e.py` | 46 | `cjk_model` |
| function | `test_scripts/test_ocr_e2e.py` | 57 | `test_ocr_availability_reports_available` |
| function | `test_scripts/test_ocr_e2e.py` | 73 | `test_english_pdf_page1_returns_spans` |
| function | `test_scripts/test_ocr_e2e.py` | 87 | `test_english_spans_have_valid_bboxes` |
| function | `test_scripts/test_ocr_e2e.py` | 102 | `test_english_spans_have_text` |
| function | `test_scripts/test_ocr_e2e.py` | 113 | `test_english_spans_confidence_range` |
| function | `test_scripts/test_ocr_e2e.py` | 129 | `test_chinese_pdf_page1_returns_spans` |
| function | `test_scripts/test_ocr_e2e.py` | 147 | `test_apply_ocr_spans_inserts_invisible_text` |
| function | `test_scripts/test_ocr_e2e.py` | 169 | `test_apply_ocr_spans_page_marked_dirty` |
| function | `test_scripts/test_ocr_loading_status.py` | 31 | `test_worker_emits_loading_status_before_first_page` |
| function | `test_scripts/test_ocr_model_insert.py` | 43 | `model_with_scan` |
| function | `test_scripts/test_ocr_model_insert.py` | 50 | `test_apply_ocr_spans_inserts_searchable_text` |
| function | `test_scripts/test_ocr_model_insert.py` | 62 | `test_apply_ocr_spans_locates_text_via_search_for` |
| function | `test_scripts/test_ocr_model_insert.py` | 72 | `test_apply_ocr_spans_keeps_render_visually_unchanged` |
| function | `test_scripts/test_ocr_model_insert.py` | 89 | `test_apply_ocr_spans_handles_cjk_text` |
| function | `test_scripts/test_ocr_model_insert.py` | 99 | `test_apply_ocr_spans_handles_japanese_text` |
| function | `test_scripts/test_ocr_model_insert.py` | 109 | `test_apply_ocr_spans_skips_empty_text` |
| function | `test_scripts/test_ocr_model_insert.py` | 120 | `test_apply_ocr_spans_increments_edit_count` |
| function | `test_scripts/test_ocr_model_insert.py` | 129 | `test_apply_ocr_spans_rebuilds_block_index` |
| function | `test_scripts/test_ocr_model_insert.py` | 140 | `test_apply_ocr_spans_rejects_invalid_page` |
| function | `test_scripts/test_ocr_model_insert.py` | 153 | `test_apply_ocr_spans_without_doc_returns_zero` |
| function | `test_scripts/test_ocr_model_insert.py` | 162 | `test_pixmap_hash_helper` |
| function | `test_scripts/test_ocr_predictor_cache.py` | 22 | `test_predictors_constructed_once_across_adapters` |
| method | `test_scripts/test_ocr_tool_surya.py` | 35 | `_FakeAdapter.__post_init__` |
| method | `test_scripts/test_ocr_tool_surya.py` | 54 | `_FakeDoc.__len__` |
| method | `test_scripts/test_ocr_tool_surya.py` | 57 | `_FakeDoc.__bool__` |
| function | `test_scripts/test_ocr_tool_surya.py` | 80 | `test_availability_reports_missing_when_surya_not_installed` |
| function | `test_scripts/test_ocr_tool_surya.py` | 93 | `test_availability_reports_present_when_module_imports` |
| function | `test_scripts/test_ocr_tool_surya.py` | 105 | `test_ocr_pages_returns_visual_coords_scaled_by_render_scale` |
| function | `test_scripts/test_ocr_tool_surya.py` | 122 | `test_ocr_pages_forwards_languages_to_adapter` |
| function | `test_scripts/test_ocr_tool_surya.py` | 130 | `test_ocr_pages_rejects_unknown_language_before_adapter_call` |
| function | `test_scripts/test_ocr_tool_surya.py` | 139 | `test_ocr_pages_emits_progress_per_page` |
| function | `test_scripts/test_ocr_tool_surya.py` | 154 | `test_ocr_pages_uses_render_page_pixmap_with_purpose_ocr` |
| function | `test_scripts/test_ocr_tool_surya.py` | 167 | `test_ocr_pages_passes_device_to_adapter_factory` |
| function | `test_scripts/test_ocr_tool_surya.py` | 186 | `test_ocr_pages_raises_for_invalid_page_number` |
| function | `test_scripts/test_ocr_tool_surya.py` | 194 | `test_ocr_pages_returns_empty_when_no_doc` |
| function | `test_scripts/test_ocr_tool_surya.py` | 203 | `test_ocr_pages_raises_runtime_error_when_surya_missing` |
| function | `test_scripts/test_ocr_tool_surya.py` | 216 | `test_ocr_pages_pixmap_to_image_strips_alpha` |
| function | `test_scripts/test_ocr_tool_surya.py` | 232 | `test_real_pixmap_round_trip` |
| function | `test_scripts/test_ocr_tool_surya.py` | 252 | `test_resolve_torch_device_explicit_cuda_unavailable_raises` |
| function | `test_scripts/test_ocr_tool_surya.py` | 271 | `test_resolve_torch_device_explicit_mps_unavailable_raises` |
| function | `test_scripts/test_ocr_tool_surya.py` | 292 | `test_resolve_torch_device_explicit_cpu_always_returns_cpu` |
| function | `test_scripts/test_ocr_tool_surya.py` | 298 | `test_is_device_available_cpu_always_true` |
| function | `test_scripts/test_ocr_tool_surya.py` | 305 | `test_is_device_available_cuda_reflects_torch` |
| function | `test_scripts/test_ocr_tool_surya.py` | 322 | `test_ocr_pages_calls_cuda_empty_cache` |
| function | `test_scripts/test_ocr_tool_surya.py` | 342 | `test_ocr_pages_skips_empty_cache_on_cpu` |
| function | `test_scripts/test_ocr_types.py` | 15 | `test_ocr_span_constructs_with_bbox_text_confidence` |
| function | `test_scripts/test_ocr_types.py` | 22 | `test_ocr_span_is_immutable` |
| function | `test_scripts/test_ocr_types.py` | 28 | `test_ocr_language_codes_match_surya_strings` |
| function | `test_scripts/test_ocr_types.py` | 35 | `test_ocr_language_lookup_from_string` |
| function | `test_scripts/test_ocr_types.py` | 43 | `test_ocr_device_known_options` |
| function | `test_scripts/test_ocr_types.py` | 49 | `test_ocr_availability_default_unavailable` |
| function | `test_scripts/test_ocr_types.py` | 56 | `test_ocr_availability_with_install_hint` |
| function | `test_scripts/test_ocr_types.py` | 61 | `test_ocr_request_holds_indices_languages_device` |
| function | `test_scripts/test_ocr_types.py` | 68 | `test_ocr_request_default_device_is_auto` |
| function | `test_scripts/test_ocr_types.py` | 73 | `test_parse_page_range_basic_mixed` |
| function | `test_scripts/test_ocr_types.py` | 77 | `test_parse_page_range_handles_whitespace` |
| function | `test_scripts/test_ocr_types.py` | 81 | `test_parse_page_range_all_keyword_returns_full_doc` |
| function | `test_scripts/test_ocr_types.py` | 86 | `test_parse_page_range_empty_uses_default_current` |
| function | `test_scripts/test_ocr_types.py` | 91 | `test_parse_page_range_empty_without_default_raises` |
| function | `test_scripts/test_ocr_types.py` | 96 | `test_parse_page_range_dedupes_and_sorts` |
| function | `test_scripts/test_ocr_types.py` | 100 | `test_parse_page_range_rejects_zero_or_negative` |
| function | `test_scripts/test_ocr_types.py` | 107 | `test_parse_page_range_rejects_inverted_range` |
| function | `test_scripts/test_ocr_types.py` | 112 | `test_parse_page_range_rejects_non_numeric` |
| function | `test_scripts/test_ocr_types.py` | 119 | `test_parse_page_range_rejects_out_of_bounds` |
| function | `test_scripts/test_ocr_types.py` | 126 | `test_parse_page_range_default_current_must_be_in_range` |
| function | `test_scripts/test_ocr_view_entry.py` | 9 | `test_view_exposes_ocr_action` |
| function | `test_scripts/test_ocr_view_entry.py` | 16 | `test_view_update_ocr_availability_disables_action` |
| function | `test_scripts/test_ocr_view_entry.py` | 25 | `test_view_update_ocr_availability_reenables` |
| function | `test_scripts/test_ocr_view_entry.py` | 34 | `test_view_ocr_action_when_unavailable_shows_error_and_does_not_open_dialog` |
| function | `test_scripts/test_ocr_view_entry.py` | 49 | `test_view_ocr_action_opens_dialog_and_emits_request` |
| function | `test_scripts/test_ocr_view_entry.py` | 70 | `test_view_ocr_action_cancel_does_not_emit` |
| function | `test_scripts/test_overlap_textbox_edit.py` | 81 | `test_exact_overlap_edit` |
| function | `test_scripts/test_overlap_textbox_edit.py` | 110 | `test_partial_overlap_edit` |
| function | `test_scripts/test_overlap_textbox_edit.py` | 140 | `test_overlap_undo_redo` |
| function | `test_scripts/test_overlap_textbox_edit.py` | 188 | `test_vertical_overlap_edit` |
| function | `test_scripts/test_overlap_textbox_edit.py` | 218 | `test_overlap_replay_with_unavailable_font_fallback` |
| function | `test_scripts/test_page_deskew.py` | 50 | `test_detect_page_skew_recovers_known_angle` |
| function | `test_scripts/test_page_deskew.py` | 65 | `test_straighten_page_keeps_size_and_page_count` |
| function | `test_scripts/test_page_deskew.py` | 86 | `test_straighten_page_auto_detects_when_angle_omitted` |
| function | `test_scripts/test_page_deskew_scope.py` | 40 | `test_scope_all_emits_every_page` |
| function | `test_scripts/test_page_deskew_scope.py` | 53 | `test_scope_current_emits_only_current_page` |
| function | `test_scripts/test_page_deskew_scope.py` | 66 | `test_scope_custom_parses_range` |
| function | `test_scripts/test_page_deskew_scope.py` | 80 | `test_scope_cancelled_emits_nothing` |
| function | `test_scripts/test_page_deskew_scope.py` | 113 | `test_controller_straightens_batch_as_single_undo` |
| function | `test_scripts/test_pdf_compliance.py` | 29 | `test_well_formed_pdf_reports_no_issues` |
| function | `test_scripts/test_pdf_compliance.py` | 37 | `test_repository_sample_pdf_is_conformant` |
| function | `test_scripts/test_pdf_compliance.py` | 45 | `test_damaged_xref_is_flagged` |
| function | `test_scripts/test_pdf_compliance.py` | 63 | `test_unopenable_file_reports_issue` |
| function | `test_scripts/test_pdf_compliance.py` | 71 | `test_encrypted_pdf_is_reported_not_silently_passed` |
| function | `test_scripts/test_pdf_content_ops_cm_format.py` | 16 | `test_fitz_rect_to_stream_cm_avoids_scientific_notation` |
| function | `test_scripts/test_pdf_content_ops_cm_format.py` | 27 | `test_form_rect_to_stream_cm_avoids_scientific_notation` |
| function | `test_scripts/test_pdf_content_ops_cm_format.py` | 38 | `test_rotated_image_stream_cm_zero_angle_parity` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 45 | `qapp` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 53 | `mvc` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 72 | `test_merge_session_keeps_current_entry_locked_and_appends_new_files` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 93 | `test_start_merge_pdfs_seeds_dialog_with_current_document` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 113 | `test_merge_ordered_sources_into_current_replaces_active_document_in_list_order` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 138 | `test_merge_dialog_appends_picker_results_and_deletes_only_unlocked_rows` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 182 | `test_save_ordered_sources_as_new_opens_merged_result_as_new_tab` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 208 | `test_resolve_merge_file_retries_password_and_skips_on_cancel` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 235 | `test_start_merge_pdfs_accepts_dialog_and_saves_new_file` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 267 | `test_start_merge_pdfs_passes_controller_resolver_into_dialog` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 296 | `test_merge_dialog_validates_selected_files_before_appending` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 338 | `test_merge_dialog_updates_progress_while_processing_picker_batch` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 384 | `test_merge_dialog_preserves_reordered_list_when_adding_files` |
| function | `test_scripts/test_pdf_merge_workflow.py` | 414 | `test_merge_dialog_preserves_reordered_list_when_removing_files` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 96 | `qapp` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 104 | `mvc` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 123 | `test_optimize_dialog_defaults_to_balanced_and_switches_to_custom` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 138 | `test_pdf_model_optimizer_facade_uses_internal_module` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 148 | `test_file_tab_exposes_optimize_copy_action` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 157 | `test_save_optimized_copy_uses_working_doc_and_preserves_live_doc` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 180 | `test_save_optimized_copy_avoids_live_doc_tobytes_for_clean_session` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 209 | `test_save_optimized_copy_prefers_parallel_image_rewrite_for_clean_source` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 249 | `test_save_optimized_copy_prefers_parallel_image_rewrite_for_dirty_session` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 291 | `test_fast_preset_skips_content_cleanup` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 315 | `test_fast_preset_skips_font_subsetting` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 339 | `test_balanced_preset_keeps_cleanup_and_subset_for_small_jobs` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 369 | `test_balanced_preset_skips_cleanup_for_large_jobs` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 415 | `test_extreme_preset_keeps_cleanup_and_subset_for_large_jobs` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 445 | `test_save_optimized_copy_dirty_session_preserves_unsaved_edits` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 469 | `test_save_optimized_copy_accepts_all_presets` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 488 | `test_build_pdf_audit_report_groups_known_categories` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 509 | `test_build_pdf_audit_report_caches_active_document_results` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 544 | `test_pdf_audit_report_dialog_uses_table_and_stacked_bar` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 570 | `test_start_optimize_pdf_copy_saves_and_opens_new_tab` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 605 | `test_start_optimize_pdf_copy_rejects_current_path_collision` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 630 | `test_start_optimize_pdf_copy_runs_work_in_background` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 670 | `test_start_optimize_pdf_copy_cancels_active_background_loading` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 713 | `test_start_optimize_pdf_copy_completion_message_uses_human_units` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 755 | `test_format_size_units_covers_kb_mb_and_gb` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 764 | `test_pil_png_debug_logging_is_suppressed` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 771 | `test_large_file_optimize_submission_keeps_progress_dialog_responsive` |
| function | `test_scripts/test_pdf_optimize_workflow.py` | 819 | `test_large_file_optimized_copy_passes_integrity_validation` |
| function | `test_scripts/test_performance.py` | 58 | `run_performance_test` |
| function | `test_scripts/test_performance_script_runner.py` | 8 | `test_performance_script_runs_from_repo_root` |
| function | `test_scripts/test_print_colorspace.py` | 11 | `test_raster_print_pdf_uses_render_colorspace_from_extra_options` |
| method | `test_scripts/test_print_controller_flow.py` | 181 | `_FakeProgressDialog.canceled` |
| function | `test_scripts/test_print_controller_flow.py` | 204 | `test_print_document_defers_snapshot_until_user_accepts` |
| function | `test_scripts/test_print_controller_flow.py` | 242 | `test_print_document_runs_in_background_and_defers_close_until_helper_finishes` |
| function | `test_scripts/test_print_controller_flow.py` | 374 | `test_stalled_print_helper_can_be_terminated_without_closing_main_window` |
| function | `test_scripts/test_print_controller_flow.py` | 460 | `test_terminate_active_print_submission_handles_reentrant_runner_cleanup` |
| method | `test_scripts/test_print_dialog_properties_button.py` | 43 | `_FakeDispatcher.supports_printer_properties_dialog` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 75 | `test_properties_button_calls_dispatcher_when_supported` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 100 | `test_properties_button_disabled_when_not_supported` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 125 | `test_properties_button_syncs_dialog_fields_from_system_preferences` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 172 | `test_properties_button_keeps_auto_paper_and_orientation_app_owned` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 217 | `test_properties_tray_preferences_are_inherited_without_dialog_field` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 244 | `test_user_changed_hardware_field_marks_only_that_override` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 283 | `test_opening_properties_resets_touched_overrides` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 330 | `test_properties_cancel_keeps_current_ui_and_touched_state` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 369 | `test_driver_private_properties_use_system_color_state_in_ui` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 420 | `test_switching_printers_resets_touched_overrides_and_loads_new_defaults` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 474 | `test_preview_errors_are_handled_without_raising_from_ui_path` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 506 | `test_preview_provider_supports_dialog_without_temp_pdf_path` |
| function | `test_scripts/test_print_dialog_properties_button.py` | 537 | `test_preview_page_info_label_uses_readable_page_summary` |
| function | `test_scripts/test_print_layout.py` | 42 | `test_match_standard_paper_size_a3_portrait` |
| function | `test_scripts/test_print_layout.py` | 46 | `test_match_standard_paper_size_a3_landscape` |
| function | `test_scripts/test_print_layout.py` | 51 | `test_match_standard_paper_size_a4` |
| function | `test_scripts/test_print_layout.py` | 55 | `test_match_standard_paper_size_letter` |
| function | `test_scripts/test_print_layout.py` | 59 | `test_match_standard_paper_size_tabloid` |
| function | `test_scripts/test_print_layout.py` | 63 | `test_match_standard_paper_size_non_standard_returns_none` |
| function | `test_scripts/test_print_layout.py` | 67 | `test_match_standard_paper_size_tolerates_small_rounding` |
| function | `test_scripts/test_print_layout.py` | 77 | `test_to_q_page_size_auto_a3_source_returns_named_a3` |
| function | `test_scripts/test_print_layout.py` | 83 | `test_to_q_page_size_auto_a3_landscape_source_returns_named_a3` |
| function | `test_scripts/test_print_layout.py` | 88 | `test_to_q_page_size_auto_a4_source_returns_named_a4_not_custom` |
| function | `test_scripts/test_print_layout.py` | 94 | `test_to_q_page_size_auto_non_standard_falls_back_to_custom` |
| function | `test_scripts/test_print_layout.py` | 103 | `test_to_q_page_size_auto_non_standard_landscape_is_portrait_normalised` |
| function | `test_scripts/test_print_layout.py` | 112 | `test_to_q_page_size_explicit_a4_overrides_source` |
| function | `test_scripts/test_print_layout.py` | 118 | `test_to_q_page_size_explicit_a3_returns_named_a3` |
| function | `test_scripts/test_print_layout.py` | 123 | `test_to_q_page_size_explicit_tabloid_returns_named_tabloid` |
| method | `test_scripts/test_print_layout.py` | 148 | `_LayoutPrinter.setPageLayout` |
| function | `test_scripts/test_print_layout.py` | 162 | `test_set_page_layout_auto_landscape_source_sets_landscape` |
| function | `test_scripts/test_print_layout.py` | 173 | `test_set_page_layout_auto_portrait_source_sets_portrait` |
| function | `test_scripts/test_print_layout.py` | 184 | `test_set_page_layout_explicit_portrait_overrides_landscape_source` |
| function | `test_scripts/test_print_layout.py` | 195 | `test_set_page_layout_explicit_landscape_overrides_portrait_source` |
| function | `test_scripts/test_print_layout.py` | 211 | `test_print_dialog_paper_combo_offers_a3` |
| function | `test_scripts/test_print_speed.py` | 37 | `test_ten_page_a4_300dpi_spools_within_budget` |
| function | `test_scripts/test_print_subprocess_helper.py` | 38 | `test_run_print_helper_emits_success_events` |
| function | `test_scripts/test_print_subprocess_helper.py` | 75 | `test_run_print_helper_emits_failed_event_on_dispatch_error` |
| function | `test_scripts/test_print_subprocess_helper.py` | 102 | `test_run_print_helper_emits_heartbeat_during_long_submission` |
| method | `test_scripts/test_print_subprocess_runner.py` | 72 | `_FakeProcess.setWorkingDirectory` |
| method | `test_scripts/test_print_subprocess_runner.py` | 75 | `_FakeProcess.setProcessEnvironment` |
| function | `test_scripts/test_print_subprocess_runner.py` | 105 | `test_runner_emits_stalled_after_silence` |
| function | `test_scripts/test_print_subprocess_runner.py` | 128 | `test_runner_maps_terminated_process_to_helper_terminated_error` |
| function | `test_scripts/test_print_subprocess_runner.py` | 155 | `test_runner_logs_startup_error_and_uses_sys_executable` |
| function | `test_scripts/test_print_subprocess_runner.py` | 190 | `test_runner_heartbeat_events_prevent_false_stall` |
| method | `test_scripts/test_qt_bridge_layout.py` | 57 | `_FakePrinter.setPageLayout` |
| method | `test_scripts/test_qt_bridge_layout.py` | 78 | `_LayoutPrinter.setPageLayout` |
| function | `test_scripts/test_qt_bridge_layout.py` | 118 | `test_raster_print_per_page_layout_receives_correct_rects` |
| function | `test_scripts/test_qt_bridge_layout.py` | 153 | `test_raster_print_single_auto_page_calls_layout_once` |
| function | `test_scripts/test_qt_bridge_layout.py` | 182 | `test_set_page_layout_landscape_source_produces_landscape_layout` |
| function | `test_scripts/test_qt_bridge_layout.py` | 194 | `test_set_page_layout_portrait_source_produces_portrait_layout` |
| function | `test_scripts/test_qt_bridge_layout.py` | 206 | `test_set_page_layout_named_a4_portrait_uses_a4_dimensions` |
| function | `test_scripts/test_qt_bridge_layout.py` | 225 | `test_apply_printer_options_skips_tray_when_auto` |
| function | `test_scripts/test_qt_bridge_layout.py` | 260 | `test_apply_printer_options_hardware_setters_gated_by_override_fields` |
| function | `test_scripts/test_qt_bridge_layout.py` | 300 | `test_resolve_page_indices_odd_subset_and_reverse` |
| function | `test_scripts/test_qt_bridge_layout.py` | 312 | `test_compute_target_draw_rect_fit_actual_custom` |
| function | `test_scripts/test_qt_bridge_layout.py` | 326 | `test_print_job_options_normalization_clamps_and_lowercases` |
| function | `test_scripts/test_qt_pixmap_colorspaces.py` | 20 | `test_pixmap_to_qpixmap_bridges_gray_and_cmyk` |
| function | `test_scripts/test_qt_pixmap_colorspaces.py` | 43 | `test_pdf_renderer_grayscale_output_matches_rgb_dimensions` |
| function | `test_scripts/test_render_clarity_dpr.py` | 33 | `test_high_quality_render_uses_device_pixel_ratio` |
| function | `test_scripts/test_render_colorspace.py` | 22 | `test_tool_manager_render_page_pixmap_accepts_colorspace` |
| function | `test_scripts/test_render_colorspace.py` | 45 | `test_pdf_model_render_entry_points_forward_colorspace` |
| function | `test_scripts/test_resolve_target_mode.py` | 17 | `test_run_without_span_id_logs_warning` |
| function | `test_scripts/test_resolve_target_mode.py` | 31 | `test_run_with_span_id_does_not_promote` |
| function | `test_scripts/test_rotated_text_editor_preview.py` | 60 | `test_preview_glyphs_stay_upright_for_proxy_rotation` |
| function | `test_scripts/test_scene_context_menu.py` | 55 | `test_scene_context_menu_includes_richer_browse_actions` |
| function | `test_scripts/test_scene_context_menu.py` | 107 | `test_scene_context_menu_page_actions_reuse_page_specific_helpers` |
| function | `test_scripts/test_security_cua_allowlist.py` | 49 | `test_execute_cua_action_blocks_type` |
| function | `test_scripts/test_security_cua_allowlist.py` | 55 | `test_execute_cua_action_blocks_key` |
| function | `test_scripts/test_security_cua_allowlist.py` | 61 | `test_execute_cua_action_blocks_unknown` |
| function | `test_scripts/test_security_cua_allowlist.py` | 67 | `test_execute_cua_action_allows_click` |
| function | `test_scripts/test_security_cua_allowlist.py` | 74 | `test_execute_cua_action_allows_screenshot` |
| function | `test_scripts/test_security_cua_allowlist.py` | 87 | `test_execute_cua_action_rejects_out_of_window_click` |
| function | `test_scripts/test_security_cua_allowlist.py` | 97 | `test_execute_cua_action_rejects_out_of_window_move` |
| function | `test_scripts/test_security_cua_allowlist.py` | 104 | `test_execute_cua_action_allows_in_window_click` |
| function | `test_scripts/test_security_cua_allowlist.py` | 113 | `test_execute_cua_action_no_rect_skips_bounds` |
| function | `test_scripts/test_security_dispatcher_temp_cleanup.py` | 19 | `test_print_pdf_bytes_logs_unlink_failure_at_debug` |
| function | `test_scripts/test_security_logging_level.py` | 41 | `test_configure_logging_defaults_to_warning` |
| function | `test_scripts/test_security_logging_level.py` | 48 | `test_configure_logging_debug_env_enables_debug` |
| function | `test_scripts/test_security_logging_level.py` | 55 | `test_configure_logging_empty_env_value_is_not_debug` |
| function | `test_scripts/test_security_ocr_requirements.py` | 32 | `test_ocr_requirements_file_exists` |
| function | `test_scripts/test_security_ocr_requirements.py` | 36 | `test_surya_ocr_is_declared_in_ocr_file` |
| function | `test_scripts/test_security_ocr_requirements.py` | 41 | `test_transformers_not_pinned_to_unvalidated_5x` |
| function | `test_scripts/test_security_ocr_weights.py` | 36 | `test_sha256_file_matches_hashlib` |
| function | `test_scripts/test_security_ocr_weights.py` | 42 | `test_resolve_weights_dir_from_env` |
| function | `test_scripts/test_security_ocr_weights.py` | 48 | `test_pinned_checkpoints_default_pins_three_models` |
| function | `test_scripts/test_security_ocr_weights.py` | 58 | `test_pinned_checkpoints_revision_override_targets_ocr_only` |
| function | `test_scripts/test_security_ocr_weights.py` | 66 | `test_verify_weights_dir_accepts_matching_hash` |
| function | `test_scripts/test_security_ocr_weights.py` | 71 | `test_verify_weights_dir_rejects_mismatched_hash` |
| function | `test_scripts/test_security_ocr_weights.py` | 77 | `test_verify_weights_dir_rejects_missing_file` |
| function | `test_scripts/test_security_ocr_weights.py` | 83 | `test_verify_weights_dir_empty_manifest_fails_closed` |
| function | `test_scripts/test_security_ocr_weights.py` | 89 | `test_verify_weights_dir_missing_directory` |
| function | `test_scripts/test_security_ocr_weights.py` | 94 | `test_enforce_policy_no_bundle_pins_revisions_online` |
| function | `test_scripts/test_security_ocr_weights.py` | 104 | `test_enforce_policy_does_not_mutate_os_environ` |
| function | `test_scripts/test_security_ocr_weights.py` | 113 | `test_enforce_policy_bundle_mismatch_refuses` |
| function | `test_scripts/test_security_ocr_weights.py` | 120 | `test_enforce_policy_bundle_match_allows_offline` |
| function | `test_scripts/test_security_ocr_weights.py` | 133 | `test_adapter_refuses_load_on_weight_failure` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 36 | `test_guard_before_open_rejects_oversize` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 41 | `test_guard_before_open_allows_normal_size` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 59 | `test_safe_render_scale_clamps_huge_page` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 68 | `test_safe_render_scale_leaves_normal_page_untouched` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 73 | `test_safe_render_scale_floors_at_min` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 89 | `test_open_pdf_rejects_oversize_before_parsing` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 114 | `test_open_pdf_rejects_excess_page_count` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 128 | `test_open_pdf_allows_normal_document` |
| function | `test_scripts/test_security_pdf_resource_guards.py` | 163 | `test_render_page_pixmap_clamps_oversized_scale` |
| function | `test_scripts/test_security_pillow_floor.py` | 47 | `test_pillow_floor_is_at_least_12_2_0` |
| function | `test_scripts/test_security_pillow_floor.py` | 51 | `test_surya_ocr_not_in_core_requirements` |
| function | `test_scripts/test_security_pillow_floor.py` | 59 | `test_surya_ocr_not_in_optional_requirements` |
| function | `test_scripts/test_security_single_instance_isolation.py` | 21 | `test_listen_server_enables_user_access_option` |
| function | `test_scripts/test_security_single_instance_isolation.py` | 74 | `test_handle_socket_message_rejects_nonexistent_path` |
| function | `test_scripts/test_security_single_instance_isolation.py` | 81 | `test_handle_socket_message_rejects_non_pdf_path` |
| function | `test_scripts/test_security_single_instance_isolation.py` | 89 | `test_handle_socket_message_accepts_existing_pdf` |
| function | `test_scripts/test_security_subprocess_paths.py` | 35 | `test_win_rundll32_uses_absolute_system32_path` |
| function | `test_scripts/test_security_subprocess_paths.py` | 63 | `test_linux_get_default_printer_uses_absolute_lpstat_path` |
| function | `test_scripts/test_security_subprocess_paths.py` | 86 | `test_linux_list_printers_uses_absolute_lpstat_path` |
| function | `test_scripts/test_security_subprocess_paths.py` | 112 | `test_linux_submit_via_lp_uses_absolute_lp_path` |
| function | `test_scripts/test_security_watermark_coercion.py` | 19 | `test_coerce_clamps_oversized_font_size` |
| function | `test_scripts/test_security_watermark_coercion.py` | 25 | `test_coerce_floors_tiny_font_size` |
| function | `test_scripts/test_security_watermark_coercion.py` | 31 | `test_coerce_truncates_long_text` |
| function | `test_scripts/test_security_watermark_coercion.py` | 37 | `test_coerce_caps_page_count` |
| function | `test_scripts/test_security_watermark_coercion.py` | 43 | `test_coerce_clamps_opacity_and_wraps_angle` |
| function | `test_scripts/test_security_watermark_coercion.py` | 50 | `test_coerce_drops_wrong_type_pages` |
| function | `test_scripts/test_security_watermark_coercion.py` | 54 | `test_coerce_drops_missing_required_keys` |
| function | `test_scripts/test_security_watermark_coercion.py` | 59 | `test_coerce_preserves_valid_watermark_fields` |
| function | `test_scripts/test_security_watermark_coercion.py` | 88 | `test_load_watermarks_drops_bad_entries_and_clamps_good` |
| method | `test_scripts/test_short_term_safety.py` | 33 | `_NamedCommand.description` |
| function | `test_scripts/test_short_term_safety.py` | 49 | `qapp` |
| function | `test_scripts/test_short_term_safety.py` | 72 | `test_inline_text_editor_emits_focus_out_signal_without_monkeypatch` |
| function | `test_scripts/test_short_term_safety.py` | 87 | `test_command_manager_undo_keeps_command_on_failure` |
| function | `test_scripts/test_short_term_safety.py` | 100 | `test_command_manager_evicts_oldest_entries_at_max_limit` |
| function | `test_scripts/test_short_term_safety.py` | 111 | `test_edit_text_reports_rollback_failures` |
| function | `test_scripts/test_short_term_safety.py` | 142 | `test_restore_page_from_snapshot_does_not_delete_live_page_when_insert_fails` |
| function | `test_scripts/test_short_term_safety.py` | 177 | `test_restore_page_from_snapshot_inserts_replacement_before_deleting_original` |
| function | `test_scripts/test_single_instance_forwarding.py` | 64 | `test_single_instance_server_receives_forwarded_argv` |
| function | `test_scripts/test_single_instance_forwarding.py` | 77 | `test_try_become_server_returns_none_when_server_alive` |
| function | `test_scripts/test_single_instance_forwarding.py` | 90 | `test_try_become_server_cleans_stale_socket` |
| function | `test_scripts/test_single_instance_forwarding.py` | 139 | `test_controller_handle_forwarded_cli_opens_forwarded_files` |
| function | `test_scripts/test_snapshot_restore.py` | 15 | `test_restore_preserves_page_count` |
| function | `test_scripts/test_snapshot_restore.py` | 21 | `test_restore_is_idempotent` |
| function | `test_scripts/test_snapshot_restore.py` | 28 | `test_restore_validates_xref_table` |
| function | `test_scripts/test_structural_indexing.py` | 19 | `test_insert_blank_page_rebuilds_inserted_page_and_marks_shifted_pages_stale` |
| function | `test_scripts/test_structural_indexing.py` | 32 | `test_shifted_page_is_rebuilt_on_demand_after_delete` |
| function | `test_scripts/test_structural_indexing.py` | 51 | `test_insert_pages_from_file_rebuilds_inserted_pages_and_marks_shifted_pages_stale` |
| function | `test_scripts/test_structural_indexing.py` | 72 | `test_structural_undo_avoids_full_rebuild_and_rebuilds_only_affected_pages` |
| function | `test_scripts/test_structural_indexing.py` | 94 | `test_insert_pages_from_file_returns_actual_insert_positions_after_validation` |
| function | `test_scripts/test_structural_indexing.py` | 112 | `test_delete_pages_returns_actual_deleted_pages_after_validation` |
| function | `test_scripts/test_structural_indexing.py` | 122 | `test_insert_blank_page_returns_actual_insert_position_after_validation` |
| function | `test_scripts/test_text_edit_finalize_outcome.py` | 19 | `test_failed_outcome_exists` |
| function | `test_scripts/test_text_edit_finalize_outcome.py` | 25 | `test_finalize_returns_failed_when_emit_raises` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 86 | `test_pdf_view_init_does_not_warn_about_outline_disconnects` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 105 | `test_pdf_view_exposes_text_edit_manager_on_real_init` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 114 | `test_finalize_emits_typed_edit_request_payload` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 141 | `test_sig_move_text_emits_move_text_request` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 165 | `test_move_text_request_fields_match_session` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 197 | `test_controller_accepts_move_text_request` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 243 | `test_controller_updates_undo_redo_enabled_state_from_command_manager` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 271 | `test_controller_edit_text_shows_error_toast_for_invalid_result` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 310 | `test_edit_text_command_initializes_result_before_execute` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 331 | `test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands` |
| function | `test_scripts/test_text_edit_manager_foundation.py` | 337 | `test_edit_text_command_execute_annotation_is_bool` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 51 | `test_latin_single_line_edit_preserves_font_pt` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 60 | `test_cjk_single_line_edit_preserves_height` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 70 | `test_fractional_font_pt_round_trips_through_edit` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 78 | `test_repeated_ten_edits_cumulative_drift_under_half_pt` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 93 | `test_preview_pixmap_dimensions_match_render_scale_2x` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 98 | `test_bold_flag_preserved_through_edit` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 107 | `test_italic_flag_preserved_through_edit` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 115 | `test_non_black_color_preserved_through_edit` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 124 | `test_multi_line_wrap_column_matches_source` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 132 | `test_tight_leading_honored_on_commit` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 141 | `test_loose_leading_honored_on_commit` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 150 | `test_position_anchor_drift_under_half_pt_at_all_corners` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 161 | `test_mixed_latin_cjk_span_renders_both_scripts` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 169 | `test_vertical_rotated_text_edit_preserves_orientation_and_size` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 179 | `test_preview_pixmap_width_equals_source_rect_times_render_scale` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 186 | `test_preview_render_produces_visible_text_pixels` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 214 | `test_preview_render_at_render_scale_2x_doubles_pixel_dimensions` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 229 | `test_preview_render_caches_identical_input` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 241 | `test_preview_render_rotation_90_swaps_pixel_dimensions` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 258 | `test_preview_render_uses_explicit_line_height_not_auto` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 306 | `test_inline_editor_glyph_height_matches_pdf_at_render_scale_2x` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 365 | `test_glyph_height_parity_negative_control` |
| function | `test_scripts/test_text_editing_fidelity_suite.py` | 404 | `test_glyph_height_1pct_gate_rejects_2px_delta` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 437 | `test_finalize_skips_emit_for_normalized_noop_edit` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 454 | `test_text_property_panel_helper_disables_actions_without_editor` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 465 | `test_text_property_panel_helper_shows_selection_state_without_enabling_actions` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 482 | `test_text_property_panel_helper_enables_actions_for_live_editor` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 494 | `test_text_property_panel_live_editor_uses_pdf_size_state_not_display_pt` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 517 | `test_context_menu_includes_safe_browse_actions_for_selection` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 533 | `test_start_text_selection_requires_text_hit_and_stores_start_run` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 563 | `test_start_text_selection_rejects_block_fallback_hits` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 590 | `test_finalize_text_selection_uses_run_anchored_snapshot_and_preserves_start_hit_info` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 627 | `test_context_menu_offers_edit_text_when_point_hits_editable_text` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 651 | `test_escape_marks_current_editor_as_discard_before_finalize` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 664 | `test_small_drag_can_activate_editor_move` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 686 | `test_drag_across_page_updates_editing_page_idx` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 710 | `test_drag_page_resolution_follows_cross_page_target_when_present` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 724 | `test_finalize_cross_page_existing_text_emits_move_signal_only` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 756 | `test_average_image_rect_color_returns_local_average` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 771 | `test_sample_page_mask_color_uses_local_scene_crop` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 788 | `test_drag_move_refreshes_editor_mask_color` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 807 | `test_editor_shortcut_forwarder_keeps_save_forwarding` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 823 | `test_editor_shortcut_forwarder_keeps_save_as_forwarding` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 846 | `test_editor_shortcut_forwarder_handles_escape_before_ctrl_guard` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 864 | `test_editor_shortcut_forwarder_uses_local_undo_redo_history` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 890 | `test_save_shortcut_finalizes_editor_before_emitting_save` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 903 | `test_save_as_shortcut_finalizes_editor_before_emitting_save_as` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 917 | `test_save_as_uses_current_document_default_path_when_present` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 936 | `test_finalize_noop_records_explicit_result` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 957 | `test_finalize_position_only_existing_text_records_commit_result` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 983 | `test_editor_shortcut_forwarder_consumes_empty_local_history_without_fallback` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1009 | `test_toggle_document_undo_redo_actions_disables_and_reenables` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1023 | `test_update_undo_redo_enabled_prefers_local_editor_history` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1067 | `test_mode_switch_commits_edit_not_discards` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1081 | `test_escape_still_discards` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1093 | `test_block_outlines_only_drawn_for_visible_pages` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1137 | `test_block_outlines_follow_run_boxes_in_run_mode` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1178 | `test_paragraph_outlines_use_light_blue_dashed_border` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1218 | `test_build_text_editor_stylesheet_keeps_editor_background_transparent` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1229 | `test_create_text_editor_keeps_background_transparent_for_edit_and_add_text` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1293 | `test_create_text_editor_rotates_proxy_for_vertical_text` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1341 | `test_create_text_editor_adds_mask_item_to_hide_display_text` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1407 | `test_finalize_text_edit_removes_mask_item` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1424 | `test_cmd_shift_z_fires_redo` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1450 | `test_phase2_finalize_preserves_fractional_font_size_in_edit_request` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1478 | `test_phase2_create_text_editor_records_fractional_initial_size` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1532 | `test_phase2_refresh_mask_matches_local_background_with_texture_underlay` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1588 | `test_phase2_refresh_mask_falls_back_to_dark_underlay_for_light_text` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1649 | `test_phase2_editor_height_fits_content_not_paragraph_rect` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1686 | `test_phase2_editor_height_accommodates_wrapped_paragraph` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1719 | `test_editor_height_capped_to_viewport_ratio_for_long_text` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1743 | `test_phase2_editor_font_matches_pdf_render_scale` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1782 | `test_phase2_editor_height_honors_embedded_newlines` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1811 | `test_create_text_editor_uses_source_span_font_size_and_width` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1885 | `test_preview_pixmap_dimensions_match_render_scale_2x` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1892 | `test_preview_pixmap_width_equals_source_rect_times_render_scale` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1899 | `test_preview_backed_editor_font_is_callable` |
| function | `test_scripts/test_text_editing_gui_regressions.py` | 1921 | `test_preview_backed_editor_paintEvent_shows_text_pixels` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 77 | `test_fallback_extraction_space_joins_wrapped_lines` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 98 | `test_paragraph_builder_space_joins_visual_lines` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 112 | `test_multicolumn_hit_detection_does_not_merge_columns` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 127 | `test_bullet_items_keep_semantic_breaks` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 144 | `test_get_text_in_rect_expands_partial_clip_to_whole_visual_lines` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 160 | `test_get_text_bounds_expands_partial_clip_to_full_visual_line_bounds` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 187 | `test_run_anchored_selection_uses_partial_boundary_lines_and_full_middle_lines` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 219 | `test_run_anchored_selection_keeps_reading_order_for_backward_drag_same_line` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 243 | `test_exact_run_hit_ignores_block_whitespace_fallback` |
| function | `test_scripts/test_text_extraction_line_joining.py` | 261 | `test_run_anchored_selection_uses_nearest_run_when_mouseup_is_in_block_whitespace` |
| function | `test_scripts/test_text_normalization.py` | 6 | `test_normalize_strips_whitespace` |
| function | `test_scripts/test_text_normalization.py` | 10 | `test_normalize_lowercases` |
| function | `test_scripts/test_text_normalization.py` | 14 | `test_normalize_expands_fi_ligature` |
| function | `test_scripts/test_text_normalization.py` | 18 | `test_normalize_expands_ff_ligature` |
| function | `test_scripts/test_text_normalization.py` | 22 | `test_normalize_empty` |
| function | `test_scripts/test_text_normalization.py` | 26 | `test_similarity_identical` |
| function | `test_scripts/test_text_normalization.py` | 30 | `test_similarity_one_empty` |
| function | `test_scripts/test_text_normalization.py` | 34 | `test_similarity_substring` |
| function | `test_scripts/test_text_normalization.py` | 38 | `test_token_coverage_full` |
| function | `test_scripts/test_text_normalization.py` | 42 | `test_token_coverage_empty_source` |
| function | `test_scripts/test_text_normalization.py` | 46 | `test_token_coverage_no_match` |
| function | `test_scripts/test_text_selection.py` | 35 | `test_get_chars_in_run_returns_per_character_boxes` |
| function | `test_scripts/test_text_selection.py` | 53 | `test_same_run_drag_selects_only_character_range` |
| function | `test_scripts/test_text_selection.py` | 82 | `test_same_run_drag_is_order_independent` |
| function | `test_scripts/test_text_selection.py` | 101 | `test_cross_run_same_line_clips_both_boundaries` |
| function | `test_scripts/test_text_selection.py` | 136 | `test_multi_run_selection_fetches_rawdict_once` |
| function | `test_scripts/test_text_selection.py` | 178 | `test_multi_line_drag_partial_first_full_middle_partial_last` |
| function | `test_scripts/test_theme_and_icons.py` | 45 | `test_token_dicts_all_keys` |
| function | `test_scripts/test_theme_and_icons.py` | 50 | `test_token_accent_values` |
| function | `test_scripts/test_theme_and_icons.py` | 57 | `test_registry_ids_exact` |
| function | `test_scripts/test_theme_and_icons.py` | 62 | `test_registry_matches_canonical_valid_ids` |
| function | `test_scripts/test_theme_and_icons.py` | 69 | `test_swatch_is_bg_color` |
| function | `test_scripts/test_theme_and_icons.py` | 76 | `test_registry_meta_id_matches_key` |
| function | `test_scripts/test_theme_and_icons.py` | 85 | `test_build_qss_all_themes_contain_colors` |
| function | `test_scripts/test_theme_and_icons.py` | 93 | `test_build_qss_unknown_falls_back_to_alpine_snow` |
| function | `test_scripts/test_theme_and_icons.py` | 98 | `test_build_qss_default_is_alpine_snow` |
| function | `test_scripts/test_theme_and_icons.py` | 102 | `test_ribbon_rules_are_scoped` |
| function | `test_scripts/test_theme_and_icons.py` | 113 | `test_sidebar_rules_present` |
| function | `test_scripts/test_theme_and_icons.py` | 118 | `test_document_tabbar_rules_present` |
| function | `test_scripts/test_theme_and_icons.py` | 123 | `test_panel_rules_present` |
| function | `test_scripts/test_theme_and_icons.py` | 130 | `test_dark_theme_has_foreground` |
| function | `test_scripts/test_theme_and_icons.py` | 136 | `test_all_themes_pair_bg_and_fg` |
| function | `test_scripts/test_theme_and_icons.py` | 145 | `test_dialog_themed` |
| function | `test_scripts/test_theme_and_icons.py` | 153 | `test_native_controls_themed` |
| function | `test_scripts/test_theme_and_icons.py` | 163 | `test_qmenu_rules_present` |
| function | `test_scripts/test_theme_and_icons.py` | 168 | `test_combobox_dropdown_themed` |
| function | `test_scripts/test_theme_and_icons.py` | 173 | `test_dark_dialog_renders_dark` |
| function | `test_scripts/test_theme_and_icons.py` | 197 | `test_action_icon_map_covers_core_actions` |
| function | `test_scripts/test_theme_and_icons.py` | 206 | `test_load_icon_unknown_label_returns_null` |
| function | `test_scripts/test_theme_and_icons.py` | 212 | `test_load_icon_known_label_returns_icon` |
| function | `test_scripts/test_theme_and_icons.py` | 219 | `test_load_icon_straighten_page` |
| function | `test_scripts/test_theme_and_icons.py` | 231 | `test_chip_count_matches_registry` |
| function | `test_scripts/test_theme_and_icons.py` | 238 | `test_chip_single_square` |
| function | `test_scripts/test_theme_and_icons.py` | 247 | `test_active_chip_on_init` |
| function | `test_scripts/test_theme_and_icons.py` | 257 | `test_theme_selected_signal_emits` |
| function | `test_scripts/test_theme_and_icons.py` | 267 | `test_set_active_theme_updates_chips` |
| function | `test_scripts/test_theme_and_icons.py` | 292 | `test_apply_initial_theme_sets_app_stylesheet` |
| function | `test_scripts/test_theme_and_icons.py` | 307 | `test_construction_does_not_mutate_global_stylesheet` |
| function | `test_scripts/test_theme_and_icons.py` | 323 | `test_switcher_applies_theme_without_a_controller` |
| function | `test_scripts/test_theme_and_icons.py` | 341 | `test_graphics_view_no_inline_stylesheet` |
| function | `test_scripts/test_theme_and_icons.py` | 352 | `test_document_tabbar_no_inline_stylesheet` |
| function | `test_scripts/test_theme_and_icons.py` | 363 | `test_toolbar_container_height` |
| function | `test_scripts/test_theme_and_icons.py` | 374 | `test_toolbar_button_style` |
| function | `test_scripts/test_theme_and_icons.py` | 390 | `test_toolbar_icon_size` |
| function | `test_scripts/test_theme_and_icons.py` | 404 | `test_straighten_action_has_icon` |
| function | `test_scripts/test_thumbnail_context_menu.py` | 69 | `test_thumbnail_context_menu_exposes_page_operations` |
| function | `test_scripts/test_thumbnail_context_menu.py` | 118 | `test_delete_rotate_and_insert_helpers_emit_page_specific_signals` |
| function | `test_scripts/test_thumbnail_context_menu.py` | 130 | `test_export_specific_pages_defaults_to_pdf_when_filter_is_pdf` |
| function | `test_scripts/test_thumbnail_context_menu.py` | 143 | `test_insert_pages_from_file_at_uses_given_position` |
| function | `test_scripts/test_tool_extensions.py` | 11 | `model_with_text_pdf` |
| function | `test_scripts/test_tool_extensions.py` | 24 | `test_search_returns_results` |
| function | `test_scripts/test_tool_extensions.py` | 32 | `test_search_empty_returns_empty` |
| function | `test_scripts/test_tool_extensions.py` | 36 | `test_search_no_doc_returns_empty` |
| function | `test_scripts/test_tool_extensions.py` | 40 | `test_ocr_no_doc_returns_empty` |
| function | `test_scripts/test_tool_extensions.py` | 44 | `test_ocr_invalid_page_raises` |
| function | `test_scripts/test_tool_extensions.py` | 49 | `test_rawdict_text_compat_backfills_keyword_option` |
| function | `test_scripts/test_tool_extensions.py` | 91 | `test_close_all_sessions_tolerates_new_bypass_instance` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 140 | `scenario_1_displacement` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 206 | `scenario_2_no_silent_noop` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 233 | `scenario_2b_same_length` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 263 | `scenario_3_position_consistency` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 303 | `scenario_4_consecutive_undo_redo` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 393 | `scenario_5_style_inheritance` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 494 | `scenario_1b_dense_paragraph_displacement` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 545 | `scenario_2c_edit_to_empty` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 573 | `scenario_3b_position_after_longer_edit` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 611 | `scenario_4b_edit_same_block_twice` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 661 | `scenario_5b_cjk_mixed_edit` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 734 | `scenario_1c_multirun_edit_single_run` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 781 | `scenario_1d_tightly_packed_lines` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 824 | `scenario_4c_rapid_consecutive_same_block` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 865 | `scenario_real_pdf_edit` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 929 | `scenario_7_run_mode_orphan_guard` |
| function | `test_scripts/test_track_ab_5scenarios.py` | 973 | `scenario_8_verification_sensitivity` |
| function | `test_scripts/test_track_ab_model_regressions.py` | 80 | `case_move_only_run` |
| function | `test_scripts/test_track_ab_model_regressions.py` | 118 | `case_move_only_paragraph_preserves_colors` |
| function | `test_scripts/test_track_ab_model_regressions.py` | 167 | `case_missing_protected_span_ids` |
| function | `test_scripts/test_user_preferences.py` | 19 | `test_default_ocr_device_is_auto` |
| function | `test_scripts/test_user_preferences.py` | 24 | `test_set_then_get_ocr_device_round_trips` |
| function | `test_scripts/test_user_preferences.py` | 30 | `test_set_ocr_device_persists_in_store` |
| function | `test_scripts/test_user_preferences.py` | 38 | `test_set_ocr_device_rejects_unknown_value` |
| function | `test_scripts/test_user_preferences.py` | 44 | `test_get_ocr_device_recovers_from_corrupt_value` |
| function | `test_scripts/test_user_preferences.py` | 49 | `test_default_ocr_languages_is_english` |
| function | `test_scripts/test_user_preferences.py` | 54 | `test_set_ocr_languages_stores_list` |
| function | `test_scripts/test_user_preferences.py` | 60 | `test_set_ocr_languages_rejects_unknown_code` |
| function | `test_scripts/test_user_preferences.py` | 66 | `test_set_ocr_languages_rejects_empty_list` |
| function | `test_scripts/test_user_preferences.py` | 78 | `test_default_theme_is_alpine_snow` |
| function | `test_scripts/test_user_preferences.py` | 84 | `test_set_then_get_theme_round_trips` |
| function | `test_scripts/test_user_preferences.py` | 90 | `test_set_theme_persists_across_instances` |
| function | `test_scripts/test_user_preferences.py` | 96 | `test_set_theme_rejects_unknown_value` |
| function | `test_scripts/test_user_preferences.py` | 102 | `test_get_theme_recovers_from_corrupt_value` |
| function | `test_scripts/test_ux_signoff_agent.py` | 11 | `test_main_fails_closed_without_credentials` |
| function | `test_scripts/test_ux_signoff_agent.py` | 26 | `test_main_isolates_each_pdf_run_and_continues_after_failure` |
| function | `test_scripts/test_week1_model_regressions.py` | 57 | `test_fallback_hit_detection_space_joins_wrapped_lines` |
| function | `test_scripts/test_week1_model_regressions.py` | 83 | `test_build_paragraphs_space_joins_lines` |
| function | `test_scripts/test_week1_model_regressions.py` | 124 | `test_same_height_edit_does_not_push_neighbor_block_down` |
| function | `test_scripts/test_week1_model_regressions.py` | 156 | `test_longer_edit_keeps_original_top_anchor` |
| method | `test_scripts/test_win_driver_properties.py` | 62 | `_FakeWin32Print.SetPrinter` |
| function | `test_scripts/test_win_driver_properties.py` | 82 | `test_open_printer_properties_returns_prefs_without_persisting` |
| function | `test_scripts/test_win_driver_properties.py` | 118 | `test_get_printer_preferences_prefers_richer_tray_list` |
| method | `test_scripts/test_win_driver_properties.py` | 155 | `_FakeWin32PrintUserDefaults.SetPrinter` |
| function | `test_scripts/test_win_driver_properties.py` | 166 | `test_get_printer_preferences_prefers_user_defaults_for_color_mode` |
| function | `test_scripts/test_win_driver_properties.py` | 180 | `test_open_printer_properties_does_not_persist_user_defaults` |
| function | `test_scripts/test_win_driver_properties.py` | 206 | `test_open_printer_properties_cancel_returns_none_without_persisting` |
| function | `test_scripts/test_win_print_fixes.py` | 76 | `_ok_result` |
| function | `test_scripts/test_win_print_fixes.py` | 109 | `test_open_printer_properties_does_not_call_setprinter` |
| function | `test_scripts/test_win_print_fixes.py` | 120 | `test_open_printer_properties_returns_base64_devmode` |
| function | `test_scripts/test_win_print_fixes.py` | 132 | `test_print_pdf_applies_devmode_job_scoped_and_restores` |
| function | `test_scripts/test_win_print_fixes.py` | 185 | `test_devmode_buffer_injected_at_submission_survives_preview_and_json` |
| function | `test_scripts/test_win_print_fixes.py` | 230 | `test_devmode_buffer_cleared_when_printer_switches` |
| function | `test_scripts/test_win_print_fixes.py` | 269 | `test_mixed_layout_pdf_splits_into_two_jobs` |
| function | `test_scripts/test_win_print_fixes.py` | 297 | `test_uniform_layout_pdf_stays_single_job` |
| function | `test_scripts/test_win_print_fixes.py` | 328 | `test_windows_caps_raster_dpi_at_150_but_keeps_lower` |
| function | `test_scripts/test_win_print_fixes.py` | 363 | `test_pdf_output_path_is_not_split_or_capped` |
| method | `test_scripts/test_win_print_fixes.py` | 407 | `_FakeDispatcher.supports_printer_properties_dialog` |
| function | `test_scripts/test_win_print_fixes.py` | 424 | `test_finding1_explicit_paper_preserved_when_orientation_auto` |
| function | `test_scripts/test_win_print_fixes.py` | 460 | `test_finding2_collated_multicopy_mixed_layout_uses_document_order` |
| function | `test_scripts/test_win_print_fixes.py` | 501 | `test_finding2_uncollated_multicopy_mixed_layout_groups_copies_per_page` |
| function | `test_scripts/test_win_print_fixes.py` | 539 | `test_finding2_uniform_layout_multicopy_stays_single_job` |
| function | `test_scripts/test_win_print_fixes.py` | 574 | `test_finding3_pending_devmode_survives_recoverable_range_error` |
| function | `test_scripts/test_win_print_fixes.py` | 631 | `test_finding4_denied_apply_skips_restore_and_still_prints` |
| function | `test_scripts/test_win_print_fixes.py` | 684 | `test_finding6_partial_failure_reports_already_spooled` |
| function | `test_scripts/test_win_print_fixes.py` | 715 | `test_finding6_first_group_failure_returns_plain_result` |
| function | `test_scripts/test_win_print_fixes.py` | 739 | `test_finding11_malformed_devmode_b64_falls_through_to_split` |
| function | `test_scripts/test_win_print_fixes.py` | 778 | `test_finding7_buffer_only_props_do_not_reload_defaults` |
| method | `test_scripts/test_win_print_fixes.py` | 838 | `_WindowsLikePrinter.setPageLayout` |
| function | `test_scripts/test_win_print_fixes.py` | 852 | `test_set_page_layout_actually_applies_page_size` |
| function | `test_scripts/test_win_print_fixes.py` | 871 | `test_set_page_layout_applies_size_on_real_printer` |
| function | `test_scripts/test_xref_repair.py` | 57 | `test_open_damaged_pdf_auto_repairs_in_memory` |
| function | `test_scripts/test_xref_repair.py` | 91 | `test_open_damaged_encrypted_pdf_keeps_encryption` |
| function | `test_scripts/test_xref_repair.py` | 129 | `test_open_damaged_owner_only_pdf_keeps_encryption` |
| function | `test_scripts/test_xref_repair.py` | 159 | `test_open_healthy_pdf_is_left_file_backed` |
| method | `view/dialogs/audit.py` | 119 | `PdfAuditReportDialog._on_stacked_bar_hovered` |
| method | `view/dialogs/export.py` | 94 | `ExportPagesDialog._on_scope_changed` |
| method | `view/dialogs/merge.py` | 141 | `MergePdfDialog._create_progress_dialog` |
| method | `view/dialogs/ocr.py` | 149 | `OcrDialog._on_scope_changed` |
| method | `view/dialogs/optimize.py` | 170 | `OptimizePdfDialog._show_audit_report` |
| method | `view/dialogs/optimize.py` | 224 | `OptimizePdfDialog._on_preset_changed` |
| method | `view/dialogs/optimize.py` | 229 | `OptimizePdfDialog._mark_custom` |
| method | `view/dialogs/password.py` | 45 | `PDFPasswordDialog._on_show_hide_toggled` |
| method | `view/dialogs/watermark.py` | 123 | `WatermarkDialog._choose_color` |
| method | `view/pdf_view.py` | 860 | `PDFView._complete_deferred_shell_startup` |
| method | `view/pdf_view.py` | 960 | `PDFView._on_document_tab_changed` |
| method | `view/pdf_view.py` | 972 | `PDFView._close_current_document_tab` |
| method | `view/pdf_view.py` | 1324 | `PDFView._on_color_profile_combo_changed` |
| method | `view/pdf_view.py` | 1327 | `PDFView._on_zoom_combo_changed` |
| method | `view/pdf_view.py` | 1394 | `PDFView.toggle_left_sidebar` |
| method | `view/pdf_view.py` | 1409 | `PDFView.toggle_right_sidebar` |
| method | `view/pdf_view.py` | 1424 | `PDFView._show_thumbnails_tab` |
| method | `view/pdf_view.py` | 1607 | `PDFView._choose_rect_color` |
| method | `view/pdf_view.py` | 1618 | `PDFView._choose_highlight_color` |
| method | `view/pdf_view.py` | 1637 | `PDFView._on_text_apply_clicked` |
| method | `view/pdf_view.py` | 1642 | `PDFView._on_text_cancel_clicked` |
| method | `view/pdf_view.py` | 1873 | `PDFView._on_escape_shortcut` |
| method | `view/pdf_view.py` | 1997 | `PDFView._finalize_if_focus_outside_edit_context` |
| method | `view/pdf_view.py` | 2016 | `PDFView._on_app_focus_changed` |
| method | `view/pdf_view.py` | 2024 | `PDFView._on_editor_focus_out` |
| method | `view/pdf_view.py` | 2278 | `PDFView._on_scroll_changed` |
| method | `view/pdf_view.py` | 2313 | `PDFView._iter_outline_targets` |
| method | `view/pdf_view.py` | 2348 | `PDFView._current_text_editor_scene_rect` |
| method | `view/pdf_view.py` | 2351 | `PDFView._sample_page_mask_color` |
| method | `view/pdf_view.py` | 2619 | `PDFView._on_search_result_clicked` |
| method | `view/pdf_view.py` | 2627 | `PDFView._on_annotation_selected` |
| method | `view/pdf_view.py` | 2632 | `PDFView._navigate_search_previous` |
| method | `view/pdf_view.py` | 2638 | `PDFView._navigate_search_next` |
| method | `view/pdf_view.py` | 2651 | `PDFView._wheel_event` |
| method | `view/pdf_view.py` | 2665 | `PDFView._on_zoom_debounce` |
| method | `view/pdf_view.py` | 3202 | `PDFView._scene_rect_to_doc_rect` |
| method | `view/pdf_view.py` | 3518 | `PDFView._select_all_text_on_current_page` |
| method | `view/pdf_view.py` | 4029 | `PDFView._schedule_outline_redraw` |
| method | `view/pdf_view.py` | 4391 | `PDFView._on_edit_font_family_changed` |
| method | `view/pdf_view.py` | 4394 | `PDFView._on_edit_font_size_changed` |
| method | `view/pdf_view.py` | 4488 | `PDFView._open_file` |
| method | `view/pdf_view.py` | 4493 | `PDFView._print_document` |
| method | `view/pdf_view.py` | 4520 | `PDFView._optimize_pdf_copy` |
| method | `view/pdf_view.py` | 4526 | `PDFView._delete_pages` |
| method | `view/pdf_view.py` | 4543 | `PDFView._rotate_pages` |
| method | `view/pdf_view.py` | 4622 | `PDFView._export_pages` |
| method | `view/pdf_view.py` | 4679 | `PDFView._show_search_panel` |
| method | `view/pdf_view.py` | 4685 | `PDFView._show_thumbnails` |
| method | `view/pdf_view.py` | 4700 | `PDFView._show_add_watermark_dialog` |
| method | `view/pdf_view.py` | 4712 | `PDFView._on_watermark_selected` |
| method | `view/pdf_view.py` | 4715 | `PDFView._edit_selected_watermark` |
| method | `view/pdf_view.py` | 4731 | `PDFView._remove_selected_watermark` |
| method | `view/pdf_view.py` | 4752 | `PDFView._trigger_search` |
| method | `view/pdf_view.py` | 4818 | `PDFView.add_annotation_to_list` |
| method | `view/pdf_view.py` | 4851 | `PDFView._snapshot_page` |
| method | `view/pdf_view.py` | 4858 | `PDFView._insert_blank_page` |
| method | `view/pdf_view.py` | 4885 | `PDFView._insert_pages_from_file` |
| method | `view/pdf_view.py` | 5085 | `PDFView._resize_event` |
| method | `view/pdf_view.py` | 5109 | `PDFView.closeEvent` |
| method | `view/text_editing.py` | 139 | `TextEditDelta.any_change` |
| method | `view/text_editing.py` | 801 | `PreviewBackedInlineTextEditor._schedule_preview` |
| function | `view/theme.py` | 122 | `_meta` |

## 7. Module Map

> All files with their classes and top-level functions.

### `.agents/skills/ui-ux-pro-max/scripts/core.py`
*UI/UX Pro Max Core - BM25 search engine for UI/UX style guides*
**Classes:** `BM25`
**Functions:** `_load_csv`, `_search_csv`, `detect_domain`, `search`, `search_stack`⚠
**Methods:** 4 total, 0 never-called

### `.agents/skills/ui-ux-pro-max/scripts/design_system.py`
*Design System Generator - Aggregates search results and applies reasoning to generate comprehensive design system recomm*
**Classes:** `DesignSystemGenerator`
**Functions:** `format_ascii_box`, `format_markdown`, `generate_design_system`⚠, `persist_design_system`, `format_master_md`, `format_page_override_md`, `_generate_intelligent_overrides`, `_detect_page_type`
**Methods:** 8 total, 0 never-called

### `.agents/skills/ui-ux-pro-max/scripts/search.py`
*UI/UX Pro Max Search - BM25 search engine for UI/UX style guides Usage: python search.py "<query>" [--domain <domain>] [*
**Functions:** `format_output`⚠

### `.claude/skills/ui-ux-pro-max/scripts/core.py`
*UI/UX Pro Max Core - BM25 search engine for UI/UX style guides*
**Classes:** `BM25`
**Functions:** `_load_csv`, `_search_csv`, `detect_domain`, `search`, `search_stack`⚠
**Methods:** 4 total, 0 never-called

### `.claude/skills/ui-ux-pro-max/scripts/design_system.py`
*Design System Generator - Aggregates search results and applies reasoning to generate comprehensive design system recomm*
**Classes:** `DesignSystemGenerator`
**Functions:** `format_ascii_box`, `format_markdown`, `generate_design_system`⚠, `persist_design_system`, `format_master_md`, `format_page_override_md`, `_generate_intelligent_overrides`, `_detect_page_type`
**Methods:** 8 total, 0 never-called

### `.claude/skills/ui-ux-pro-max/scripts/search.py`
*UI/UX Pro Max Search - BM25 search engine for UI/UX style guides Usage: python search.py "<query>" [--domain <domain>] [*
**Functions:** `format_output`⚠

### `controller/__init__.py`
*Controller layer — mutation coordination between View and Model.*

### `controller/pdf_controller.py`
**Classes:** `SessionUIState`, `FullscreenSessionSnapshot`, `PrintJobRequest`, `OptimizePdfCopyRequest`, `_PrintSubmissionWorker`, `_PrintWorkerBridge`, `_OptimizePdfCopyWorker`, `_OptimizeWorkerBridge`, `_OcrWorker`, `_OcrBridge`, `PDFController`
**Methods:** 183 total, 23 never-called

### `main.py`
**Functions:** `_configure_logging`, `parse_cli`, `run_merge_and_exit`, `run`

### `model/__init__.py`
*Model layer — document correctness, sessions, text editing, commands.*

### `model/color_profile.py`
**Classes:** `ColorProfile`
**Functions:** `to_fitz_colorspace`, `safe_to_fitz_colorspace`
**Methods:** 1 total, 0 never-called

### `model/edit_commands.py`
**Classes:** `EditTextResult`, `EditCommand`, `EditTextCommand`, `AddTextboxCommand`, `SnapshotCommand`, `CommandManager`
**Methods:** 30 total, 8 never-called

### `model/edit_requests.py`
**Classes:** `EditTextRequest`, `MoveTextRequest`
**Methods:** 1 total, 1 never-called

### `model/geometry.py`
**Functions:** `clamp_rect_to_page`, `rect_from_points`, `rect_union`, `rect_overlap_ratio`

### `model/headless_merge.py`
**Functions:** `headless_merge`

### `model/merge_session.py`
**Classes:** `MergeEntry`, `MergeSessionModel`
**Methods:** 7 total, 1 never-called

### `model/object_requests.py`
**Classes:** `ObjectRef`, `ObjectHitInfo`, `MoveObjectRequest`, `BatchMoveObjectsRequest`, `RotateObjectRequest`, `DeleteObjectRequest`, `BatchDeleteObjectsRequest`, `ResizeObjectRequest`, `InsertImageObjectRequest`

### `model/pdf_content_ops.py`
**Classes:** `ContentToken`, `ParsedOperator`, `NativeImageInvocation`
**Functions:** `_is_whitespace`, `_is_delimiter`, `tokenize_content_stream`, `parse_operators`, `_rotation_from_cm`, `format_cm_value`, `decompose_image_cm`, `rotated_image_stream_cm`, `_cm_values_from_operands`, `_bbox_from_stream_cm`, `_q_bounds_by_operator_index`, `discover_native_image_invocations`, `_discover_form_nested_invocations`, `replace_operator_operands`, `remove_operator_range`, `serialize_tokens`, `fitz_rect_to_stream_cm`, `form_rect_to_stream_cm`

### `model/pdf_model.py`
**Classes:** `TextHit`, `_EditTextResolveResult`, `DocumentSession`, `PDFModel`
**Functions:** `_guard_before_open`, `_safe_render_scale`, `_install_rawdict_text_compat`, `_classify_insert_path`
**Methods:** 166 total, 20 never-called

### `model/pdf_optimizer.py`
**Classes:** `PdfOptimizeOptions`, `PdfAuditItem`, `PdfAuditReport`, `PdfOptimizationResult`, `PdfOptimizeExecutionProfile`
**Functions:** `_init_image_rewrite_worker`⚠, `_classify_worker_pil_image_mode`, `_transcode_image_payload`, `_rewrite_source_image_task`⚠, `_rewrite_extracted_image_task`⚠, `preset_optimize_options`, `normalize_optimize_options`, `is_large_optimize_job`, `resolve_optimize_execution_profile`, `resolve_file_backed_optimize_source`, `current_document_size_bytes`, `build_working_doc_for_optimized_copy`, `make_active_audit_cache_key`, `blank_metadata_dict`, `xref_size_bytes`, `build_pdf_audit_report`, `apply_optimize_options`, `image_rewrite_settings`, `parallel_image_worker_count`, `can_use_parallel_image_rewrite`, `rewrite_images_serially`, `collect_extracted_images`, `collect_image_usage`, `rewrite_images_from_source_in_parallel`, `rewrite_extracted_images_in_parallel`, `rewrite_images_with_pillow`, `requires_post_save_packaging`, `fast_save_kwargs`, `postprocess_optimized_pdf_with_pikepdf`, `save_optimized_working_doc`, `save_optimized_copy`

### `model/pdf_validator.py`
*PDF conformance checks.  Light-weight structural validation used as evidence that the editor's output targets a well-for*
**Functions:** `check_pdf_conformance`, `is_pdf_conformant`

### `model/text_block.py`
**Classes:** `TextBlock`, `EditableSpan`, `EditableParagraph`, `TextBlockManager`
**Functions:** `rotation_degrees_from_dir`, `_norm_dir_vec`, `_rect_axis_projection`, `_char_kind`, `_kind_compatible`, `_starts_bullet_item`
**Methods:** 38 total, 2 never-called

### `model/text_normalization.py`
**Functions:** `normalize_text`, `normalized_similarity`, `token_coverage_ratio`

### `model/tools/__init__.py`

### `model/tools/annotation_tool.py`
**Classes:** `AnnotationTool`
**Methods:** 9 total, 0 never-called

### `model/tools/base.py`
**Classes:** `ToolExtension`
**Methods:** 7 total, 0 never-called

### `model/tools/manager.py`
**Classes:** `ToolManager`
**Methods:** 9 total, 0 never-called

### `model/tools/ocr_tool.py`
**Classes:** `_SuryaAdapter`, `OcrTool`
**Functions:** `_check_surya_import`, `is_device_available`, `_empty_torch_cache`, `_resolve_torch_device`, `_create_surya_adapter`, `_pixmap_to_image`
**Methods:** 7 total, 1 never-called

### `model/tools/ocr_types.py`
**Classes:** `OcrSpan`, `OcrLanguage`, `OcrDevice`, `OcrAvailability`, `OcrRequest`
**Functions:** `parse_page_range`
**Methods:** 2 total, 0 never-called

### `model/tools/ocr_weights.py`
*OCR model-weight integrity policy (finding F9, CWE-494).  Surya fetches its detection/recognition weights from datalab's*
**Classes:** `OcrWeightsError`
**Functions:** `sha256_file`, `resolve_weights_dir`, `pinned_checkpoints`, `verify_weights_dir`, `_apply_settings`, `enforce_weights_policy`

### `model/tools/search_tool.py`
**Classes:** `SearchTool`
**Methods:** 2 total, 0 never-called

### `model/tools/watermark_rendering.py`
**Functions:** `needs_cjk_font`, `resolve_watermark_font`, `apply_watermarks_to_page`, `apply_watermarks_to_document`

### `model/tools/watermark_tool.py`
**Classes:** `WatermarkTool`
**Functions:** `_coerce_wm`
**Methods:** 22 total, 1 never-called

### `scripts/__init__.py`

### `scripts/check_completion_proof_hook.py`
*Claude/Codex Stop hook — validates .completion_proof.json before allowing completion.  Registered in .claude/settings.js*
**Functions:** `_sha256`, `_goal_file_tracked_in_git`, `_git_head`, `_run_check_gate_passed`, `main`

### `scripts/check_gate_passed.py`
*Final gate re-verifier — shares all validation logic with verify_no_jump.py.  Run this AS THE ABSOLUTE FINAL STEP before*
**Functions:** `main`

### `scripts/codex_session_guard.py`
*Codex /goal session guard — runtime-agnostic post-completion enforcement.  Codex `/goal` does NOT fire the Claude Code S*
**Functions:** `_git_head`, `_is_ancestor`, `_cmd_begin`, `_cmd_verify`, `main`

### `scripts/completion_gate.py`
*Single-command completion enforcer for the no-jump gate.  Run this as THE ONLY completion action.  It mechanically chain*
**Functions:** `_sha256`, `_run`, `main`

### `scripts/gate_anchor.py`
*Anchor file: records the expected SHA-256 of check_completion_proof_hook.py.  completion_gate.py reads this file's _HOOK*

### `scripts/manual_visual_edit_check.py`
**Functions:** `_process_events`, `_first_non_empty_span`, `_editor_viewport_rect`, `_crop`, `_changed_pixel_pct`, `_diff_image`, `_capture_editor_crop`, `run`, `main`

### `scripts/ux_signoff_agent.py`
*GPT-5.4/5.5 computer-use UX signoff for AC 6.  Normally invoked by scripts/verify_no_jump.py after both pytest runs comp*
**Functions:** `_sha256`, `_git_head`, `_has_image_artifacts`, `_collect_artifact_hashes`, `_screenshot_b64`, `_point_in_rect`, `_execute_cua_action`, `_extract_text`, `_b64_to_png`, `_assert_app_window_shows_pdf`, `_get_window_rect`, `_run_agent_on_pdf`, `_validate_trace_vs_checklist`, `_validate_signoff_report`, `main`

### `scripts/verify_no_jump.py`
*Tamper-evident, run-isolated completion gate for the no-jump acceptance suite.  Run:  python scripts/verify_no_jump.py E*
**Functions:** `_sha256`, `_git_head`, `_expected_case_ids`, `_assert_clean_worktree`, `_clear_and_prepare`, `_clean_pytest_env`, `_run_pytest`, `_check_artifacts`, `_check_manifests_match`, `_check_signoff_checklist`, `_check_signoff`, `_run_full_suite`, `_reverify_artifact_hashes`, `_run_lint`, `main`

### `src/printing/__init__.py`
*Cross-platform printing subsystem entrypoints.*

### `src/printing/base_driver.py`
*Abstract printing driver contracts and shared models.*
**Classes:** `PrinterDevice`, `PrintJobOptions`, `PrintJobResult`, `PrinterDriver`
**Methods:** 10 total, 2 never-called

### `src/printing/dispatcher.py`
*Print dispatcher and factory entrypoints.*
**Classes:** `PrintDispatcher`
**Functions:** `get_printer_driver`
**Methods:** 11 total, 1 never-called

### `src/printing/errors.py`
*Printing subsystem exceptions.*
**Classes:** `PrintingError`, `PrinterUnavailableError`, `PrinterOfflineError`, `PrintJobSubmissionError`, `RenderingError`, `PrintHelperStalledError`, `PrintHelperTerminatedError`

### `src/printing/helper_main.py`
*Helper subprocess entrypoint for Windows print submission.*
**Functions:** `_build_snapshot_bytes`, `_stdout_emit`⚠, `_start_heartbeat`, `run_print_helper`, `main`

### `src/printing/helper_protocol.py`
*Protocol models shared by the print helper subprocess.*
**Classes:** `PrintHelperJob`
**Functions:** `encode_helper_event`, `parse_helper_event`
**Methods:** 4 total, 0 never-called

### `src/printing/layout.py`
*Shared paper/layout helpers for print preview and print rendering.*
**Functions:** `match_standard_paper_size`, `normalize_orientation`, `normalize_scale_mode`, `normalize_scale_percent`, `resolve_paper_size_points`, `resolve_orientation`, `compute_target_draw_rect`

### `src/printing/messages.py`
*Shared user-facing messages for the print lifecycle.*

### `src/printing/page_selection.py`
*Shared page selection utilities for preview and print submission.*
**Functions:** `normalize_page_subset`, `resolve_page_indices`

### `src/printing/pdf_renderer.py`
*PDF raster renderer for print pipeline.*
**Classes:** `RenderedPage`, `PDFRenderer`
**Methods:** 6 total, 0 never-called

### `src/printing/platforms/__init__.py`
*Platform-specific printing drivers.*

### `src/printing/platforms/linux_driver.py`
*Linux CUPS/lp print driver implementation.*
**Classes:** `LinuxPrinterDriver`
**Methods:** 10 total, 1 never-called

### `src/printing/platforms/mac_driver.py`
*macOS print driver implementation (CUPS stack).*
**Classes:** `MacPrinterDriver`
**Methods:** 1 total, 0 never-called

### `src/printing/platforms/win_driver.py`
*Windows print driver implementation.*
**Classes:** `_POINTL`, `_DEVMODE_STRUCT1`, `_DEVMODE_UNION1`, `_DEVMODE_UNION2`, `_PUBLIC_DEVMODEW`, `_PRINTER_INFO_9`, `WindowsPrinterDriver`
**Functions:** `_decode_capability_text`, `_map_devmode_values_to_preferences`, `_buffer_to_public_devmode`, `_buffer_to_preferences`, `_buffer_private_crc32`, `_decode_devmode_b64`, `_devmode_buffer_to_b64`
**Methods:** 19 total, 1 never-called

### `src/printing/print_dialog.py`
*Unified print dialog with settings + preview in one window.*
**Classes:** `UnifiedPrintDialogResult`, `UnifiedPrintDialog`
**Methods:** 32 total, 7 never-called

### `src/printing/qt_bridge.py`
*Qt print bridge: send rendered pages into OS spooler via QPrinter.*
**Functions:** `_ensure_qapplication`, `_to_duplex_mode`, `_to_paper_source`, `_to_q_orientation`, `_to_q_page_size`, `_set_page_layout`, `_fitz_rect_to_qrectf`, `_apply_printer_options`, `_draw_page_image`, `raster_print_pdf`

### `src/printing/subprocess_runner.py`
*Controller-facing runner for the print helper subprocess.*
**Classes:** `PrintSubprocessRunner`
**Methods:** 13 total, 5 never-called

### `test_scripts/benchmark_optimize_ab.py`
**Functions:** `_run_measurement`, `_extract_revision`, `compare_revisions`, `main`

### `test_scripts/benchmark_ui_open_render.py`
*benchmark_ui_open_render.py -- UI-path open/page-change responsiveness benchmark =======================================*
**Functions:** `_wait_for_quality`, `_cleanup_startup`, `main`

### `test_scripts/conftest.py`
**Functions:** `qapp`⚠, `_ensure_test_file_1_pdf`⚠

### `test_scripts/core_interaction_audit.py`
**Classes:** `AuditFixture`, `AuditScenario`, `AuditPlan`, `AuditScenarioResult`, `AuditReport`
**Functions:** `_relative_path`, `default_core_interaction_plan`, `_default_blocked_details`, `run_audit_plan`, `render_markdown_report`, `render_manual_checklist`, `_run_pytest_target`⚠, `main`

### `test_scripts/generate_large_pdf.py`
*generate_large_pdf.py — 產生極大 PDF（壓力測試用） ==================================================== 依「超大 PDF 壓力測試」計畫：產生 500～100*
**Functions:** `build_large_pdf`, `main`

### `test_scripts/live_acrobat_parity_run.py`
**Classes:** `AppWindow`, `AppSnapshot`, `TaskResult`
**Functions:** `now_iso`, `ensure_output_dir`, `minimize_noise_windows`, `resolve_window`, `activate_window`, `capture_window`, `diff_ratio`, `run_task`, `page_navigation_action`⚠, `zoom_flow_action`⚠, `reading_state_action`⚠, `selection_copy_action`⚠, `blocked_action`, `render_markdown`, `write_csv`, `ffmpeg_path`, `start_recording`, `stop_recording`, `main`

### `test_scripts/measure_startup_time.py`
*測量啟動時間： 1) 匯入 PDFModel 2) 建立 PDFModel 實例 3) 執行 test_font_fix.py*
**Functions:** `main`

### `test_scripts/test_1pdf_audit.py`
*稽核 1.pdf：檢查頁面尺寸、文字塊位置、編輯後輸出*
**Functions:** `audit_1pdf`⚠

### `test_scripts/test_1pdf_horizontal.py`
*測試 1.pdf 水平文字編輯：驗證輸出在頁面內、文字可見 支援兩種測試路徑： 1. 索引路徑：直接用 index 的 block rect（與 model 內部一致） 2. GUI 路徑：用 get_text_info_at_point *
**Functions:** `run_horizontal_edit_and_verify`, `test_horizontal_edit_and_verify`⚠

### `test_scripts/test_50_rounds.py`
*50 rounds text-preservation test - Horizontal: real PDFs from test_files/sample-files-main - Vertical:   synthetic PDFs *
**Classes:** `Issue`, `RoundResult`
**Functions:** `_norm`, `_safe_text`, `_all_pdfs`, `_open`, `_safe_blocks`, `_pre_snap`, `_check_loss`, `_pick_horiz`, `horiz_round`, `_make_vert_pdf`, `vert_round`, `main`

### `test_scripts/test_add_textbox_atomic.py`
*Regression tests for add_text textbox mode backend behavior.*
**Functions:** `_norm`, `_make_pdf`, `_first_span_bbox_contains`, `test_add_textbox_rotation_anchor_visual_location`⚠, `test_add_textbox_default_font_supports_cjk`⚠, `test_add_textbox_atomic_undo_redo_boundaries`⚠, `test_add_textbox_undo_keeps_other_page_objects`⚠, `test_add_textbox_immediately_editable_by_hit_detection`⚠

### `test_scripts/test_all_pdfs.py`
*test_all_pdfs.py — 全 test_files 目錄 PDF 批次測試 ==================================================== 測試策略（三層）：   Layer 1 — o*
**Classes:** `Result`
**Functions:** `_top_subdir`, `_is_no_edit`, `_get_password`, `test_one_pdf`, `_finalize`, `_try_edit`, `collect_pdfs`, `main`

### `test_scripts/test_autopan.py`
**Classes:** `_FakeSignal`, `_FakeTimer`, `_FakeViewport`, `_FakeScrollBar`, `_FakeGraphicsView`, `_FakeEvent`
**Functions:** `_make_view`, `test_middle_click_enters_autopan`⚠, `test_second_middle_click_exits_autopan`⚠, `test_right_click_exit_shows_context_menu`⚠, `test_autopan_tick_scrolls_with_fractional_accumulation`⚠, `test_autopan_mouse_move_updates_cursor_position`⚠, `test_autopan_speed_scales_with_distance`⚠, `test_context_menu_manual_bypasses_single_signal_suppression`⚠, `test_autopan_real_view_enters_and_exits`⚠
**Methods:** 25 total, 0 never-called

### `test_scripts/test_browse_selection_gui_regressions.py`
**Classes:** `_FakeSignal`, `_FakeViewport`, `_FakeGraphicsView`, `_FakeScene`, `_FakeRectItem`
**Functions:** `_make_view`, `test_start_text_selection_requires_text_hit_and_stores_start_run`⚠, `test_start_text_selection_rejects_block_fallback_hits`⚠, `test_finalize_text_selection_uses_run_anchored_snapshot_and_preserves_start_hit_info`⚠
**Methods:** 14 total, 0 never-called

### `test_scripts/test_char_run_reconstruction.py`
*Regression tests for char-level run reconstruction from rawdict.*
**Functions:** `_norm`, `test_runs_merge_micro_spans_on_test_file_1`⚠, `test_hit_and_edit_use_reconstructed_run`⚠, `test_paragraph_mode_hit_and_redo_stability`⚠, `test_paragraph_drag_without_text_change_with_overlap`⚠, `test_paragraph_drag_twice_with_stale_span_id`⚠, `test_1pdf_paragraph_target_excludes_overlapping_run_or_not_run`⚠, `test_1pdf_text_hit_does_not_contain_replacement_character_when_plain_text_has_alternative`⚠, `test_vertical_paragraph_groups_adjacent_columns_in_reading_order`⚠, `test_phase2_paragraph_edit_preserves_mixed_color_runs`⚠

### `test_scripts/test_cli_argparse.py`
**Functions:** `_make_pdf`, `test_parse_cli_accepts_positional_files`⚠, `test_parse_cli_supports_merge_output`⚠, `test_parse_cli_requires_input_for_merge`⚠, `test_run_merge_and_exit_is_headless`⚠

### `test_scripts/test_color_profile_controller.py`
**Functions:** `_make_controller`, `test_default_session_color_profile_is_srgb`⚠, `test_set_session_color_profile_updates_state_and_triggers_render_and_thumbs`⚠, `test_set_session_color_profile_rejects_unknown_profile`⚠, `test_visible_render_dispatch_passes_session_colorspace`⚠

### `test_scripts/test_color_profile_enum.py`
**Functions:** `test_to_fitz_colorspace_maps_expected_profiles`⚠, `test_color_profile_from_string_round_trips`⚠, `test_unknown_profile_raises_value_error`⚠

### `test_scripts/test_color_profile_gui.py`
**Functions:** `test_color_profile_sidebar_combo_exists`⚠, `test_color_profile_combo_emits_signal_on_user_change`⚠, `test_set_color_profile_updates_combo_without_emitting`⚠

### `test_scripts/test_completion_proof_hook.py`
*Tests for scripts/check_completion_proof_hook.py.  Covers:   - Hook is inactive when goal file is absent (not in goal mo*
**Functions:** `_sha256_bytes`, `_write_artifacts`, `_valid_proof`, `tmp_gate`⚠, `test_hook_exits_0_when_no_goal_file`⚠, `test_hook_blocks_when_proof_absent`⚠, `test_hook_blocks_corrupt_proof`⚠, `test_hook_blocks_wrong_status`⚠, `test_hook_blocks_stale_commit`⚠, `test_hook_blocks_nonzero_exit_code`⚠, `test_hook_allows_valid_proof`⚠, `test_hook_blocks_missing_invocation_id`⚠, `test_hook_blocks_missing_tracked_scripts`⚠, `test_hook_blocks_forged_minimal_proof`⚠, `test_hook_blocks_gate_passed_file_absent`⚠, `test_hook_blocks_gate_passed_digest_mismatch`⚠, `test_hook_blocks_signoff_file_absent`⚠, `test_hook_blocks_signoff_digest_mismatch`⚠, `test_hook_real_goal_path_blocks_without_proof`⚠, `test_hook_blocks_self_consistent_forged_artifacts`⚠, `test_hook_allows_when_check_gate_passed_succeeds`⚠, `test_hook_blocks_when_goal_file_deleted_but_tracked`⚠, `test_hook_layer7_always_runs_on_repeated_calls`⚠

### `test_scripts/test_core_interaction_audit.py`
**Functions:** `test_default_core_interaction_plan_uses_three_existing_fixtures`⚠, `test_default_core_interaction_plan_includes_automated_manual_and_acrobat_scenarios`⚠, `test_run_audit_plan_marks_non_automated_scenarios_blocked`⚠, `test_render_markdown_report_includes_summary_and_blockers`⚠, `test_render_manual_checklist_includes_manual_steps_and_relative_fixture_paths`⚠

### `test_scripts/test_cross_page_text_move.py`
*Regression tests for controller-driven cross-page text moves.*
**Classes:** `_FakeView`
**Functions:** `_norm`, `_make_two_page_pdf`, `_make_controller`, `test_move_text_across_pages_records_single_snapshot_command_and_undoes`⚠, `test_cross_page_move_unresolved_source_without_span_id_aborts_cleanly`⚠, `test_cross_page_move_stale_span_id_falls_back_to_rect_text_resolution`⚠, `test_cross_page_move_add_failure_restores_before_snapshot_and_refreshes_ui`⚠
**Methods:** 1 total, 0 never-called

### `test_scripts/test_deep.py`
*test_deep.py — PDF 編輯器深度壓力測試 ====================================== 測試 10 大場景：   T1  連續 / 重複編輯同一文字塊（20–50 次）   T2  Undo *
**Classes:** `TestCase`, `TestSuite`
**Functions:** `_ms`, `_get_password`, `_open_model`, `_first_editable_block`, `_do_edit`, `_collect_sample_pdfs`, `_collect_vera_pdfs`, `run_t1_repeated_edits`, `run_t2_undo_redo`, `run_t3_extreme_inputs`, `run_t4_multipage_ops`, `run_t5_annotation_coexist`, `run_t6_structural_then_edit`, `run_t7_memory_pressure`, `run_t8_edge_cases`, `run_t9_performance`, `run_t10_visual_output`, `generate_report`, `main`
**Methods:** 6 total, 6 never-called

### `test_scripts/test_dialogs_package.py`
**Functions:** `test_password_dialog_importable`⚠, `test_merge_dialog_importable`⚠, `test_optimize_dialog_importable`⚠, `test_watermark_dialog_importable`⚠, `test_export_dialog_importable`⚠, `test_audit_classes_importable`⚠, `test_legacy_import_path_still_works`⚠, `test_password_dialog_basic`⚠, `test_export_dialog_basic`⚠

### `test_scripts/test_drag_move.py`
*test_drag_move.py -- drag-move text box feature test ===================================================== Test coverage*
**Classes:** `TestResult`
**Functions:** `_norm`, `_find_first_text_block`, `_text_exists_at`, `_count_text_blocks`⚠, `_make_test_pdf_with_two_blocks`, `_make_vertical_pdf`, `_do_move`, `test_A_basic_move`⚠, `test_B_move_and_edit`⚠, `test_C_moved_block_not_lost`⚠, `test_D_other_block_not_lost`⚠, `test_E_vertical_move`⚠, `test_F_boundary_clamp`⚠, `test_G_sample_files`, `test_H_vera_files`, `test_I_logic_simulation`, `print_report`, `main`
**Methods:** 8 total, 2 never-called

### `test_scripts/test_edit_flow.py`
*自動化測試：建立含文字的 PDF、開啟、執行 edit_text，驗證完整流程 用以確認優化後的 model 穩定、準確運作*
**Functions:** `create_test_pdf`, `main`

### `test_scripts/test_edit_geometry_stability.py`
**Functions:** `_make_pdf`, `_find_block`, `test_repeated_identical_edits_keep_y1_drift_under_half_point`⚠, `test_single_line_edit_preserves_anchor_and_does_not_push_neighbor`⚠

### `test_scripts/test_edit_text_helpers.py`
**Functions:** `model_with_pdf`⚠, `_find_block`, `_first_span_id`, `_resolve_target`, `_resolve_for_apply`, `_apply_insert`, `test_mode_default_no_args`⚠, `test_classify_insert_path_fast_vs_htmlbox`⚠, `test_mode_explicit_span_id`⚠, `test_mode_new_rect_promotes`⚠, `test_mode_explicit_paragraph`⚠, `test_mode_run_auto_promotes`⚠, `test_mode_run_no_promote_subsection`⚠, `test_resolve_target_happy_path`⚠, `test_resolve_target_missing_block`⚠, `test_resolve_target_no_change`⚠, `test_resolve_target_by_span_id`⚠, `test_apply_insert_basic`⚠, `test_apply_insert_empty_deletes`⚠, `test_apply_insert_preserves_others`⚠, `test_verify_rebuild_passes`⚠, `test_verify_rebuild_rollback`⚠, `test_phase2_single_line_run_edit_preserves_anchor_without_drag`⚠, `test_phase2_edit_text_preserves_fractional_font_size`⚠, `_make_pdf_at_size`, `_measure_span_at`, `test_edit_preserves_font_size_pt_after_content_change`⚠, `test_edit_preserves_span_bbox_height_after_content_change`⚠, `test_single_line_edit_does_not_push_unedited_text`⚠, `test_prepush_growth_branch_does_not_raise_name_error`⚠, `test_render_width_for_edit_does_not_exceed_rect_width`⚠, `test_render_width_for_edit_signature_is_slimmed_to_page_and_rect`⚠, `test_repeated_edits_do_not_accumulate_size_drift`⚠, `_find_largest_font_span`⚠, `_find_any_editable_span`⚠, `_find_span_with_text`, `_normalized_ws`, `_page_contains_text`, `test_build_insert_css_explicit_tight_line_height_not_clamped`⚠, `test_real_pdf_complexed_layout_edit_does_not_enlarge_span`⚠, `test_real_pdf_colored_background_edit_does_not_shrink_span`⚠, `test_classify_insert_path_empty_member_spans_routes_to_htmlbox`⚠

### `test_scripts/test_empty_text_edit.py`
*Regression tests for empty text edits deleting the target textbox.*
**Classes:** `_FakeCommandManager`, `_FakeModel`
**Functions:** `_norm`, `_make_two_box_pdf`, `test_controller_empty_edit_is_not_ignored`⚠, `test_empty_edit_deletes_target_textbox_and_supports_undo_redo`⚠
**Methods:** 4 total, 0 never-called

### `test_scripts/test_feature_conflict.py`
*test_feature_conflict.py — 功能與衝突驗證 ========================================== - 單一功能：逐項呼叫 Model/Command 流程，驗證每項功能可獨立成功。 *
**Classes:** `CaseResult`, `ConceptResult`
**Functions:** `_ms`, `_get_password`, `_collect_pdfs`, `_first_block`, `run_open_save`, `run_page_ops`, `_page_count`, `run_edit_undo_redo`, `run_annot_rect_highlight`, `run_search_pixmap`, `run_watermark`, `run_conflict_annot_then_edit`, `run_conflict_structural_undo`, `run_conflict_rotate_then_edit`, `run_conflict_insert_then_edit`, `run_conflict_multi_undo_redo`, `run_save_with_watermark`, `generate_report`, `main`
**Methods:** 3 total, 3 never-called

### `test_scripts/test_font_fix.py`
*測試腳本：驗證中英文混合文字的字體分配是否正確*
**Functions:** `test_html_conversion`⚠

### `test_scripts/test_fullscreen_transitions.py`

### `test_scripts/test_geometry.py`
**Functions:** `test_clamp_inside_page_unchanged`⚠, `test_clamp_overflow_right`⚠, `test_clamp_overflow_bottom`⚠, `test_clamp_degenerate_is_nonempty`⚠, `test_rect_from_points_basic`⚠, `test_rect_from_points_multiple`⚠, `test_rect_union_empty`⚠, `test_rect_union_single`⚠, `test_rect_union_two`⚠, `test_rect_union_three`⚠, `test_overlap_ratio_no_overlap`⚠, `test_overlap_ratio_full_contain`⚠, `test_overlap_ratio_partial`⚠, `test_overlap_ratio_empty_rect`⚠

### `test_scripts/test_headless_merge.py`
**Functions:** `_make_pdf`, `test_headless_merge_combines_inputs`⚠, `test_headless_merge_rejects_empty_inputs`⚠, `test_headless_merge_rejects_missing_input`⚠, `test_headless_merge_rejects_missing_output_directory`⚠

### `test_scripts/test_image_objects_gui.py`
**Classes:** `_FakeSignal`
**Functions:** `_make_view`, `test_insert_image_from_file_emits_request`⚠, `test_insert_image_from_clipboard_emits_request`⚠, `test_insert_image_from_file_current_page_uses_default_target`⚠, `test_insert_image_from_clipboard_current_page_uses_default_target`⚠
**Methods:** 2 total, 0 never-called

### `test_scripts/test_image_objects_model.py`
**Functions:** `_png_bytes`, `_make_pdf`, `_hit`, `test_add_image_object_creates_marker_and_hit_detection`⚠, `test_move_image_object_updates_hit_location`⚠, `test_rotate_image_object_updates_rotation_metadata`⚠, `test_delete_image_object_removes_marker_and_page_image_ref`⚠, `test_image_object_persists_through_save_and_reopen`⚠, `test_move_overlapping_app_images_both_survive`⚠, `test_rotate_overlapping_app_image_neighbour_survives`⚠, `test_move_second_of_identical_app_images_moves_correct_placement`⚠

### `test_scripts/test_interaction_modes.py`
**Classes:** `_FakeSignal`, `_FakeEvent`
**Functions:** `_make_object_hit`, `_make_view`, `test_objects_mode_blocks_browse_text_selection_start`⚠, `test_browse_mode_does_not_start_object_manipulation`⚠, `test_text_edit_mode_does_not_select_rect_or_image`⚠, `test_text_edit_mode_allows_textbox_object_select`⚠
**Methods:** 8 total, 0 never-called

### `test_scripts/test_large_scale.py`
*test_large_scale.py — Phase 7 大規模測試 ========================================= 目標：   1. 開啟 100 頁合成 PDF，連續 50 次隨機編輯不同頁面 / *
**Classes:** `Metrics`
**Functions:** `_build_large_pdf`, `_random_blocks`, `run_random_edits`, `_test_one_undo_redo`, `run_vertical_text_test`, `run_scan_page_test`, `run_real_pdf_test`, `run_clean_contents_bench`, `main`
**Methods:** 9 total, 7 never-called

### `test_scripts/test_linux_driver_overrides.py`
*Regression tests for Linux driver hardware override handling.*
**Functions:** `test_to_cups_options_omits_hardware_defaults_when_not_overridden`⚠, `test_to_cups_options_includes_hardware_defaults_when_overridden`⚠, `test_submit_via_lp_omits_hardware_options_when_not_overridden`⚠, `test_submit_via_lp_includes_hardware_options_when_overridden`⚠, `test_print_pdf_keeps_direct_pdf_for_source_following_auto_layout`⚠, `test_print_pdf_forces_raster_when_user_overrides_layout`⚠

### `test_scripts/test_macos_menu.py`
*AC-7 — macOS native menu bar.  Validates the menu structure/shortcuts produced for macOS and that the build is a no-op o*
**Functions:** `_app`, `_view_with_actions`, `_titles`, `_items`, `test_build_macos_menu_bar_is_noop_off_darwin`⚠, `test_macos_menu_spec_has_expected_menus_and_actions`⚠, `test_macos_menu_uses_native_shortcuts`⚠, `test_build_macos_menu_bar_assembles_menus_on_darwin`⚠, `test_app_menu_actions_have_macos_roles`⚠

### `test_scripts/test_main_startup_behavior.py`
**Functions:** `_send_drop`, `_make_pdf`, `_cleanup_startup`, `test_empty_launch_keeps_backend_detached_until_document_request`⚠, `test_cli_open_path_keeps_controller_attached_before_opening_documents`⚠, `test_pdf_view_emits_shell_ready_before_lazy_panel_hydration`⚠, `test_empty_launch_keeps_heavy_panels_lazy_until_pdf_open`⚠, `test_lazy_shell_hydrates_panels_when_user_opens_search_tab`⚠, `test_empty_launch_buffers_dropped_pdf_paths_until_controller_attaches`⚠, `test_empty_launch_buffers_multi_drop_pdf_paths_in_order_until_controller_attaches`⚠, `test_cli_open_builds_placeholder_geometry_before_background_rasterization`⚠, `test_cli_open_defers_annotation_and_watermark_sidebar_scans`⚠, `test_change_scale_does_not_rerender_every_page_in_continuous_mode`⚠, `test_reset_empty_ui_tolerates_lazy_shell_without_heavy_panels`⚠, `test_empty_launch_cancelled_password_prompt_returns_to_empty_shell`⚠, `test_panel_helpers_do_not_emit_sidebar_reload_signals`⚠, `test_watermark_mutations_reload_sidebar_once`⚠, `test_show_page_schedules_visible_render_once_in_continuous_mode`⚠, `test_rebuild_continuous_scene_schedules_visible_render_once`⚠, `test_render_active_session_prioritizes_visible_render_before_background_loading`⚠, `test_initial_high_quality_render_starts_background_loading_once`⚠, `test_schedule_visible_render_coalesces_pending_batches`⚠

### `test_scripts/test_multi_tab_plan.py`
**Classes:** `_FakeEvent`
**Functions:** `_make_pdf`, `_make_pdf_with_font`, `_make_landscape_pdf`, `_norm`, `_pump_events`, `_send_drop`, `_trigger_fullscreen`, `_assert_mode_checked`, `_make_dirty`, `_edit_first_run`, `_open_inline_editor_for_first_run`, `_load_pdf_and_open_inline_editor`, `_click_outside_active_editor`, `_active_shortcut_target`, `qapp`⚠, `mvc`⚠, `test_01_open_two_and_switch_tabs`⚠, `test_02_duplicate_open_focus_existing`⚠, `test_drag_drop_opens_multiple_local_pdfs_in_order`⚠, `test_drag_drop_ignores_non_pdf_folder_and_remote_urls`⚠, `test_drag_drop_multiple_pdfs_never_calls_merge_paths`⚠, `test_03_edit_in_a_undo_in_b_isolated`⚠, `test_04_structural_undo_redo_isolated`⚠, `test_04b_structural_actions_schedule_stale_index_drain`⚠, `test_04c_structural_metadata_uses_actual_blank_insert_position`⚠, `test_04d_structural_metadata_uses_actual_import_insert_positions`⚠, `test_04e_structural_metadata_uses_actual_deleted_pages`⚠, `test_05_search_state_restored_per_tab`⚠, `test_06_rapid_switch_has_no_stale_async_render`⚠, `test_06a_thumbnail_list_enforces_single_column_layout`⚠, `test_06b_thumbnail_click_navigation_with_single_column`⚠, `test_06c_thumbnail_layout_fills_sidebar_width_and_has_spacing`⚠, `test_06d_thumbnail_list_auto_scrolls_with_page_scroll`⚠, `test_06e_landscape_thumbnail_does_not_create_tall_blank_cell`⚠, `test_06f_thumbnail_layout_caps_width_and_centers_in_wide_sidebar`⚠, `test_07_close_modified_tab_cancel_keeps_tab`⚠, `test_08_close_modified_tab_save_then_close`⚠, `test_09_app_close_cancel_and_save_all_paths`⚠, `test_10_save_as_path_collision_blocked`⚠, `test_10a_active_session_updates_view_save_as_default_path`⚠, `test_11_close_last_tab_resets_ui`⚠, `test_12_cli_style_multi_open_loop`⚠, `test_13_ctrl_tab_switches_to_right_tab`⚠, `test_14_ctrl_shift_tab_switches_to_left_tab`⚠, `test_15_ctrl_tab_on_toolbar_does_not_switch_toolbar_tabs`⚠, `test_16_ctrl_shift_tab_on_sidebar_does_not_switch_sidebar_tabs`⚠, `test_17_fit_to_view_syncs_zoom_state_to_current_page_fit_scale`⚠, `test_17b_zoom_combo_keeps_only_default_options`⚠, `test_18_mode_checked_state_sync_and_restore`⚠, `test_19_escape_with_editor_closes_editor_but_keeps_mode`⚠, `test_19a_inline_existing_text_escape_discards_changes`⚠, `test_19aa_inline_existing_text_ctrl_z_undoes_locally`⚠, `test_19aaa_inline_existing_text_ctrl_z_on_real_multicolor_pdf_keeps_document_undo_idle`⚠, `test_19ab_inline_existing_text_ctrl_z_after_commit_undoes_document`⚠, `test_19ac_inline_existing_text_cross_page_move_roundtrips_via_document_undo_redo`⚠, `test_19b_font_size_menu_keeps_editor_and_outside_focus_finalizes_editor`⚠, `test_19c_edit_font_change_commits_without_text_change`⚠, `test_19d_text_apply_commits_and_cancel_discards`⚠, `test_19e_cjk_font_change_commits_without_text_change`⚠, `test_19f_convert_text_to_html_uses_cjk_companion_font`⚠, `test_19f2_custom_cjk_font_generates_embedded_css`⚠, `test_19g_add_text_cjk_font_selection_commits`⚠, `test_19h_edit_existing_switch_to_dfkai_commits_font_token`⚠, `test_19i_custom_windows_cjk_fonts_render_distinct_span_fonts`⚠, `test_19j_font_popup_interaction_can_refocus_editor_without_finalize`⚠, `test_20_escape_non_browse_switches_to_browse`⚠, `test_21_escape_browse_fallback_keeps_existing_sidebar_behavior`⚠, `test_22_sticky_highlight_mode_after_draw`⚠, `test_23_sticky_add_annotation_mode_after_click`⚠, `test_24_open_existing_file_keeps_current_mode`⚠, `test_25_close_last_tab_keeps_mode_when_window_stays_open`⚠, `test_26_fullscreen_no_document_is_noop`⚠, `test_27_fullscreen_enter_and_escape_restore_chrome`⚠, `test_28_fullscreen_restores_zoom_scroll_and_dirty_state`⚠, `test_29_fullscreen_clears_search_and_cancels_editor`⚠, `test_30_fullscreen_blocked_while_print_busy_or_modal`⚠, `test_31_fullscreen_exit_button_stays_visible`⚠, `test_32_fullscreen_tab_switch_restores_each_visited_tab_state`⚠, `test_33_fullscreen_from_highlight_mode_cancels_partial_state_and_enters_browse`⚠, `test_34_fullscreen_quick_button_sits_between_fit_and_undo_and_f5_toggles`⚠, `test_34a_fullscreen_quick_button_has_12px_gap_from_fit_button`⚠, `test_34b_fullscreen_context_menu_offers_exit_action_and_triggers_toggle`⚠, `test_35_ctrl_alt_l_toggles_left_sidebar_with_focus_and_width_fallback`⚠, `test_36_ctrl_f_reopens_hidden_left_sidebar_and_focuses_search`⚠, `test_37_ctrl_alt_r_toggles_right_sidebar_with_focus_and_width_fallback`⚠, `test_38_fullscreen_restores_user_hidden_sidebars`⚠
**Methods:** 3 total, 0 never-called

### `test_scripts/test_native_image_discovery.py`
*AC-6 — native PDF images nested inside Form XObjects are selectable/editable.  Awareness.pdf draws its only image (`Im0`*
**Functions:** `_rects_close`, `test_awareness_form_nested_image_is_discovered`⚠, `test_awareness_image_is_hit_testable`⚠, `test_awareness_image_can_be_moved`⚠, `test_awareness_image_can_be_resized`⚠, `test_awareness_image_can_be_deleted`⚠, `test_report_direct_images_still_discovered`⚠

### `test_scripts/test_native_pdf_images_model.py`
**Functions:** `_png_bytes`, `_make_native_image_pdf`, `_make_shared_native_image_pdf`, `_make_outer_q_nested_sibling_pdf`, `_make_cropped_native_image_pdf`, `_make_native_image_no_cm_pdf`, `_hit`, `_image_names`, `test_native_image_hit_detection_returns_native_kind`⚠, `test_native_image_hit_prefers_topmost_invocation`⚠, `test_move_native_image_updates_hit_location`⚠, `test_resize_native_image_updates_hit_location`⚠, `test_rotate_native_image_preserves_bbox_and_updates_rotation`⚠, `test_delete_native_image_removes_one_invocation_but_keeps_shared_resource`⚠, `test_delete_native_image_prunes_unused_resource_name`⚠, `test_delete_native_image_does_not_delete_nested_sibling_in_outer_q`⚠, `test_native_discovery_does_not_depend_on_get_image_info_order`⚠, `test_native_discovery_survives_missing_get_image_info`⚠, `test_native_bbox_matches_get_image_info_on_cropped_page`⚠, `test_native_discovery_survives_no_cm_invocation`⚠, `test_native_no_cm_invocation_rejects_move_and_rotate`⚠

### `test_scripts/test_no_jump_editor_geometry.py`
**Functions:** `_current_run_id`, `_append_to_manifest`, `_assert_written`, `_assert_image_saved`, `_save_artifacts`, `_make_diff_image`, `_changed_pixel_pct`, `_crop`, `_inset_editor_content_rect`, `_query_widget_bg_rgb`, `_is_blank_pixel`, `_blank_pixel_pct`, `_blanking_relative_to`, `_pdf_region_has_ink`, `_observed_editor_vp_rect`, `_detect_span_rotation`, `test_editor_geometry_matches_pdf_bbox`⚠, `test_geometry_negative_control_x_offset`⚠, `test_geometry_negative_control_wrong_font_size`⚠, `test_click_to_edit_real_geometry_pipeline`⚠, `_resolve_inner_editor_widget`, `_first_non_empty_span_data`, `_cycle_replacement_text_same_length`, `_grab_editor_only_image`, `_rect_drift_metrics`, `_assert_rect_drift_within`, `test_click_to_edit_qtest_integration`⚠, `test_click_to_edit_then_insert_then_delete_stays_stable`⚠, `test_click_to_edit_continuous_insertions_then_delete_stays_stable`⚠, `test_reopen_same_textbox_cycles_do_not_cumulate_shrink`⚠, `test_blanking_detector_catches_a_blank_image`⚠, `test_preview_pixel_diff_under_one_pct`⚠, `test_pixel_diff_negative_control_bad_font_size`⚠

### `test_scripts/test_object_controller_flow.py`
**Classes:** `_FakeCommandManager`, `_FakeModel`
**Functions:** `_make_controller`, `test_controller_delegates_object_hit_info`⚠, `test_controller_records_snapshot_for_move_object`⚠, `test_controller_records_snapshot_for_batch_move_object`⚠, `test_controller_records_snapshot_for_rotate_and_delete_object`⚠, `test_controller_records_snapshot_for_batch_delete_object`⚠
**Methods:** 8 total, 0 never-called

### `test_scripts/test_object_free_rotation.py`
*AC-4 (model) — free arbitrary-angle rotation of images, preserved on move.  The legacy rotate path only handled 90° step*
**Functions:** `_png_bytes`, `_make_image_pdf`, `_center`, `test_free_rotate_native_image_to_30_degrees`⚠, `test_moving_a_freely_rotated_image_preserves_its_angle`⚠, `test_resizing_a_rotated_image_does_not_inflate_geometry`⚠

### `test_scripts/test_object_free_rotation_gui.py`
*AC-4 (view) — free drag-rotation interaction.  Covers the angle maths (direction match, AC-4b) and that dragging the rot*
**Classes:** `_FakeSignal`, `_FakeViewport`, `_FakeGraphicsView`, `_FakeEvent`, `_RotatableItem`
**Functions:** `test_screen_angle_is_clockwise_in_scene_coords`⚠, `test_absolute_rotation_from_drag_matches_clockwise_direction`⚠, `_make_view`, `test_rotate_handle_drag_emits_absolute_rotation`⚠, `test_textbox_drag_rotate_does_not_emit_absolute_rotation`⚠, `test_apply_selection_rotation_turns_box_and_handles`⚠, `test_rotate_handle_click_without_drag_uses_90_step`⚠
**Methods:** 15 total, 0 never-called

### `test_scripts/test_object_manipulation_gui.py`
**Classes:** `_FakeSignal`, `_FakeViewport`, `_FakeGraphicsView`, `_FakeEvent`, `_FakeKeyEvent`
**Functions:** `_make_object_hit`, `_make_view`, `test_objects_mouse_press_selects_object_and_blocks_text_selection`⚠, `test_objects_mouse_press_selects_native_image`⚠, `test_event_scene_pos_normalizes_viewport_offset`⚠, `test_delete_selected_object_emits_request`⚠, `test_rotate_selected_object_emits_request`⚠, `test_delete_shortcut_works_in_objects_mode`⚠, `test_delete_shortcut_works_in_text_edit_mode`⚠, `test_browse_object_drag_threshold_starts_drag`⚠, `test_text_edit_mouse_press_on_rotate_handle_does_not_arm_free_rotation`⚠, `test_textbox_rotate_pending_release_uses_legacy_90_step`⚠, `test_scene_context_menu_includes_object_actions`⚠, `test_objects_context_menu_exposes_image_insert_actions`⚠, `test_objects_mode_move_release_rebases_selected_object_info_immediately`⚠, `test_objects_mode_move_release_rebases_when_preview_rects_populated`⚠, `test_add_image_object_clears_stale_object_selection_in_view`⚠
**Methods:** 20 total, 0 never-called

### `test_scripts/test_object_manipulation_model.py`
**Functions:** `_make_pdf`, `_object_hit`, `test_add_textbox_creates_hidden_object_marker_and_hit_detection`⚠, `test_get_object_info_ignores_legacy_text_without_marker`⚠, `test_add_rect_creates_object_metadata_and_hit_detection`⚠, `test_move_rect_object_updates_hit_location`⚠, `test_delete_rect_object_removes_annotation`⚠, `test_rotate_textbox_object_updates_rotation_metadata`⚠, `test_delete_textbox_after_move_and_rotate_removes_all_markers`⚠

### `test_scripts/test_object_multi_select.py`
**Classes:** `_FakeSignal`, `_FakeViewport`, `_FakeGraphicsView`, `_FakeEvent`
**Functions:** `_make_object_hit`, `_make_view`, `test_shift_click_toggles_objects_on_same_page`⚠, `test_click_on_other_page_resets_selection_set`⚠, `test_batch_delete_emits_one_request`⚠, `test_batch_move_emits_one_request`⚠
**Methods:** 13 total, 0 never-called

### `test_scripts/test_object_requests.py`
**Functions:** `test_object_request_shapes`⚠

### `test_scripts/test_object_resize.py`
**Classes:** `_FakeSignal`, `_FakeViewport`, `_FakeGraphicsView`, `_FakeRectItem`, `_FakeEllipseItem`, `_FakeScene`, `_FakeEvent`
**Functions:** `_make_object_hit`, `_make_view`, `test_single_select_creates_resize_handles_and_hit_outside_bbox`⚠, `test_resize_drag_emits_resize_request`⚠, `test_top_left_handle_drag_moves_x0_y0_preserves_x1_y1`⚠, `test_compute_resize_rect_free_form_changes_aspect_ratio`⚠, `test_compute_resize_rect_shift_locks_aspect_ratio`⚠, `test_compute_resize_rect_lock_keeps_opposite_corner_for_tl`⚠, `test_bottom_left_handle_drag_moves_x0_y1_preserves_x1_y0`⚠
**Methods:** 23 total, 0 never-called

### `test_scripts/test_ocr_controller_flow.py`
**Classes:** `_FakeTool`
**Functions:** `_drive_worker`, `test_worker_emits_page_done_and_progress`⚠, `test_worker_runs_on_non_gui_thread`⚠, `test_worker_respects_cancel_between_pages`⚠, `test_worker_emits_failed_on_tool_exception`⚠, `test_worker_forwards_device_and_languages`⚠, `test_ocr_bridge_forwards_signals`⚠, `test_controller_start_ocr_refuses_when_surya_missing`⚠, `test_controller_start_ocr_applies_spans_per_page`⚠, `test_controller_cancel_ocr_sets_worker_flag`⚠, `_build_minimal_controller`, `_wait_for_ocr_finish`
**Methods:** 3 total, 0 never-called

### `test_scripts/test_ocr_dialog.py`
**Classes:** `_FakeStore`
**Functions:** `_make_prefs`, `test_dialog_defaults_to_current_page`⚠, `test_dialog_switching_to_custom_enables_range_edit`⚠, `test_dialog_custom_range_with_multi_lang_produces_request`⚠, `test_dialog_current_page_option_returns_current_index`⚠, `test_dialog_whole_document_returns_all_pages`⚠, `test_dialog_invalid_range_disables_ok`⚠, `test_dialog_validation_clears_when_range_fixed`⚠, `test_dialog_reject_returns_none`⚠, `test_dialog_no_languages_selected_disables_ok`⚠, `test_dialog_seeds_device_from_preferences`⚠, `test_dialog_persists_device_choice_to_preferences`⚠, `test_dialog_request_carries_device`⚠, `test_dialog_pre_checks_languages_from_preferences`⚠, `test_dialog_disables_cuda_and_mps_when_unavailable`⚠, `test_dialog_default_falls_back_when_stored_pref_unavailable`⚠
**Methods:** 3 total, 0 never-called

### `test_scripts/test_ocr_e2e.py`
*End-to-end OCR smoke test using real PDFs and the actual Surya backend.  Requires: surya-ocr and torch installed. Run: p*
**Functions:** `_surya_available`⚠, `eng_model`⚠, `cjk_model`⚠, `test_ocr_availability_reports_available`⚠, `test_english_pdf_page1_returns_spans`⚠, `test_english_spans_have_valid_bboxes`⚠, `test_english_spans_have_text`⚠, `test_english_spans_confidence_range`⚠, `test_chinese_pdf_page1_returns_spans`⚠, `test_apply_ocr_spans_inserts_invisible_text`⚠, `test_apply_ocr_spans_page_marked_dirty`⚠

### `test_scripts/test_ocr_loading_status.py`
*The OCR worker must announce the model-loading phase.  Mission #8: after the OCR progress bar appears there is a long id*
**Classes:** `_FakeTool`
**Functions:** `test_worker_emits_loading_status_before_first_page`⚠
**Methods:** 1 total, 0 never-called

### `test_scripts/test_ocr_model_insert.py`
**Functions:** `_pixmap_hash`, `_pixmap_distance`, `_scanlike_pdf`, `model_with_scan`⚠, `test_apply_ocr_spans_inserts_searchable_text`⚠, `test_apply_ocr_spans_locates_text_via_search_for`⚠, `test_apply_ocr_spans_keeps_render_visually_unchanged`⚠, `test_apply_ocr_spans_handles_cjk_text`⚠, `test_apply_ocr_spans_handles_japanese_text`⚠, `test_apply_ocr_spans_skips_empty_text`⚠, `test_apply_ocr_spans_increments_edit_count`⚠, `test_apply_ocr_spans_rebuilds_block_index`⚠, `test_apply_ocr_spans_rejects_invalid_page`⚠, `test_apply_ocr_spans_without_doc_returns_zero`⚠, `test_pixmap_hash_helper`⚠

### `test_scripts/test_ocr_predictor_cache.py`
*Surya predictors must be loaded once and cached, not reloaded per page.  Mission #8: OCR shows the progress bar then sit*
**Functions:** `test_predictors_constructed_once_across_adapters`⚠

### `test_scripts/test_ocr_tool_surya.py`
**Classes:** `_FakePixmap`, `_FakeAdapter`, `_FakeDoc`
**Functions:** `_make_tool_with_fake`, `test_availability_reports_missing_when_surya_not_installed`⚠, `test_availability_reports_present_when_module_imports`⚠, `test_ocr_pages_returns_visual_coords_scaled_by_render_scale`⚠, `test_ocr_pages_forwards_languages_to_adapter`⚠, `test_ocr_pages_rejects_unknown_language_before_adapter_call`⚠, `test_ocr_pages_emits_progress_per_page`⚠, `test_ocr_pages_uses_render_page_pixmap_with_purpose_ocr`⚠, `test_ocr_pages_passes_device_to_adapter_factory`⚠, `test_ocr_pages_raises_for_invalid_page_number`⚠, `test_ocr_pages_returns_empty_when_no_doc`⚠, `test_ocr_pages_raises_runtime_error_when_surya_missing`⚠, `test_ocr_pages_pixmap_to_image_strips_alpha`⚠, `test_real_pixmap_round_trip`⚠, `test_resolve_torch_device_explicit_cuda_unavailable_raises`⚠, `test_resolve_torch_device_explicit_mps_unavailable_raises`⚠, `test_resolve_torch_device_explicit_cpu_always_returns_cpu`⚠, `test_is_device_available_cpu_always_true`⚠, `test_is_device_available_cuda_reflects_torch`⚠, `test_ocr_pages_calls_cuda_empty_cache`⚠, `test_ocr_pages_skips_empty_cache_on_cpu`⚠
**Methods:** 6 total, 3 never-called

### `test_scripts/test_ocr_types.py`
**Functions:** `test_ocr_span_constructs_with_bbox_text_confidence`⚠, `test_ocr_span_is_immutable`⚠, `test_ocr_language_codes_match_surya_strings`⚠, `test_ocr_language_lookup_from_string`⚠, `test_ocr_device_known_options`⚠, `test_ocr_availability_default_unavailable`⚠, `test_ocr_availability_with_install_hint`⚠, `test_ocr_request_holds_indices_languages_device`⚠, `test_ocr_request_default_device_is_auto`⚠, `test_parse_page_range_basic_mixed`⚠, `test_parse_page_range_handles_whitespace`⚠, `test_parse_page_range_all_keyword_returns_full_doc`⚠, `test_parse_page_range_empty_uses_default_current`⚠, `test_parse_page_range_empty_without_default_raises`⚠, `test_parse_page_range_dedupes_and_sorts`⚠, `test_parse_page_range_rejects_zero_or_negative`⚠, `test_parse_page_range_rejects_inverted_range`⚠, `test_parse_page_range_rejects_non_numeric`⚠, `test_parse_page_range_rejects_out_of_bounds`⚠, `test_parse_page_range_default_current_must_be_in_range`⚠

### `test_scripts/test_ocr_view_entry.py`
**Functions:** `test_view_exposes_ocr_action`⚠, `test_view_update_ocr_availability_disables_action`⚠, `test_view_update_ocr_availability_reenables`⚠, `test_view_ocr_action_when_unavailable_shows_error_and_does_not_open_dialog`⚠, `test_view_ocr_action_opens_dialog_and_emits_request`⚠, `test_view_ocr_action_cancel_does_not_emit`⚠

### `test_scripts/test_open_large_pdf.py`
*test_open_large_pdf.py — 超大 PDF 開檔壓力測試（headless） ========================================================== 依「超大 PDF 壓力測*
**Functions:** `ensure_large_pdf`, `main`

### `test_scripts/test_overlap_corpus_recursive.py`
*Recursive overlap-safe edit validation across all PDFs under test_files.*
**Classes:** `Row`, `Candidate`
**Functions:** `_norm`, `_get_password`, `_is_encrypted_error`, `_collect_spans`, `_find_overlap_candidate`, `_find_baseline_candidate`, `_assert_token`, `_execute_edit_with_undo_redo`, `_process_pdf`, `_write_csv`, `_write_markdown`, `main`

### `test_scripts/test_overlap_textbox_edit.py`
*Targeted overlap-edit regression tests.*
**Functions:** `_norm`, `_make_pdf_exact_overlap`, `_make_pdf_partial_overlap`, `_make_pdf_vertical_overlap`, `_assert_contains`, `_first_span_with`, `_center`, `test_exact_overlap_edit`⚠, `test_partial_overlap_edit`⚠, `test_overlap_undo_redo`⚠, `test_vertical_overlap_edit`⚠, `test_overlap_replay_with_unavailable_font_fallback`⚠

### `test_scripts/test_page_deskew.py`
*Page straightening (deskew).  Mission: 拉正頁面. Detect a page's skew angle (projection-profile method) and rotate the page *
**Functions:** `_skewed_lines_pdf`, `test_detect_page_skew_recovers_known_angle`⚠, `test_straighten_page_keeps_size_and_page_count`⚠, `test_straighten_page_auto_detects_when_angle_omitted`⚠

### `test_scripts/test_page_deskew_scope.py`
*Deskew page-scope selection: 全部 / 當前頁 / 自訂.  Mission: 拉正頁面 should let the user pick a scope — all pages, the current pag*
**Functions:** `_make_view`, `_capture`, `test_scope_all_emits_every_page`⚠, `test_scope_current_emits_only_current_page`⚠, `test_scope_custom_parses_range`⚠, `test_scope_cancelled_emits_nothing`⚠, `_skewed_pdf`, `test_controller_straightens_batch_as_single_undo`⚠

### `test_scripts/test_pdf_compliance.py`
*AC-8 — PDF conformance evidence.  Verifies model/pdf_validator.check_pdf_conformance reports a clean bill of health for *
**Functions:** `_make_valid_pdf`, `test_well_formed_pdf_reports_no_issues`⚠, `test_repository_sample_pdf_is_conformant`⚠, `test_damaged_xref_is_flagged`⚠, `test_unopenable_file_reports_issue`⚠, `test_encrypted_pdf_is_reported_not_silently_passed`⚠

### `test_scripts/test_pdf_content_ops_cm_format.py`
**Functions:** `_contains_scientific_notation`, `test_fitz_rect_to_stream_cm_avoids_scientific_notation`⚠, `test_form_rect_to_stream_cm_avoids_scientific_notation`⚠, `test_rotated_image_stream_cm_zero_angle_parity`⚠

### `test_scripts/test_pdf_merge_workflow.py`
**Functions:** `_make_pdf`, `_pump_events`, `_reorder_list_widget`, `qapp`⚠, `mvc`⚠, `test_merge_session_keeps_current_entry_locked_and_appends_new_files`⚠, `test_start_merge_pdfs_seeds_dialog_with_current_document`⚠, `test_merge_ordered_sources_into_current_replaces_active_document_in_list_order`⚠, `test_merge_dialog_appends_picker_results_and_deletes_only_unlocked_rows`⚠, `test_save_ordered_sources_as_new_opens_merged_result_as_new_tab`⚠, `test_resolve_merge_file_retries_password_and_skips_on_cancel`⚠, `test_start_merge_pdfs_accepts_dialog_and_saves_new_file`⚠, `test_start_merge_pdfs_passes_controller_resolver_into_dialog`⚠, `test_merge_dialog_validates_selected_files_before_appending`⚠, `test_merge_dialog_updates_progress_while_processing_picker_batch`⚠, `test_merge_dialog_preserves_reordered_list_when_adding_files`⚠, `test_merge_dialog_preserves_reordered_list_when_removing_files`⚠

### `test_scripts/test_pdf_optimize_workflow.py`
**Functions:** `_make_pdf`, `_make_pdf_with_image`, `_make_pdf_with_many_images`, `_large_pdf_path`, `_pump_events`, `_wait_until`, `qapp`⚠, `mvc`⚠, `test_optimize_dialog_defaults_to_balanced_and_switches_to_custom`⚠, `test_pdf_model_optimizer_facade_uses_internal_module`⚠, `test_file_tab_exposes_optimize_copy_action`⚠, `test_save_optimized_copy_uses_working_doc_and_preserves_live_doc`⚠, `test_save_optimized_copy_avoids_live_doc_tobytes_for_clean_session`⚠, `test_save_optimized_copy_prefers_parallel_image_rewrite_for_clean_source`⚠, `test_save_optimized_copy_prefers_parallel_image_rewrite_for_dirty_session`⚠, `test_fast_preset_skips_content_cleanup`⚠, `test_fast_preset_skips_font_subsetting`⚠, `test_balanced_preset_keeps_cleanup_and_subset_for_small_jobs`⚠, `test_balanced_preset_skips_cleanup_for_large_jobs`⚠, `test_extreme_preset_keeps_cleanup_and_subset_for_large_jobs`⚠, `test_save_optimized_copy_dirty_session_preserves_unsaved_edits`⚠, `test_save_optimized_copy_accepts_all_presets`⚠, `test_build_pdf_audit_report_groups_known_categories`⚠, `test_build_pdf_audit_report_caches_active_document_results`⚠, `test_pdf_audit_report_dialog_uses_table_and_stacked_bar`⚠, `test_start_optimize_pdf_copy_saves_and_opens_new_tab`⚠, `test_start_optimize_pdf_copy_rejects_current_path_collision`⚠, `test_start_optimize_pdf_copy_runs_work_in_background`⚠, `test_start_optimize_pdf_copy_cancels_active_background_loading`⚠, `test_start_optimize_pdf_copy_completion_message_uses_human_units`⚠, `test_format_size_units_covers_kb_mb_and_gb`⚠, `test_pil_png_debug_logging_is_suppressed`⚠, `test_large_file_optimize_submission_keeps_progress_dialog_responsive`⚠, `test_large_file_optimized_copy_passes_integrity_validation`⚠

### `test_scripts/test_performance.py`
*test_performance.py — Phase 6 效能測試 ====================================== 模擬 20 次連續編輯同一頁，量測：   - 每次 edit_text 耗時   - 平均 *
**Functions:** `_make_test_pdf`, `run_performance_test`⚠

### `test_scripts/test_performance_script_runner.py`
**Functions:** `test_performance_script_runs_from_repo_root`⚠

### `test_scripts/test_print_colorspace.py`
**Functions:** `test_raster_print_pdf_uses_render_colorspace_from_extra_options`⚠

### `test_scripts/test_print_controller_flow.py`
*Controller-level print flow regressions.*
**Classes:** `_FakePrintDispatcher`, `_CancelDialog`, `_AcceptDialog`, `_FakeProgressDialog`, `_FakeCloseEvent`
**Functions:** `_ensure_app`, `_pump_until`, `_make_single_page_pdf`, `test_print_document_defers_snapshot_until_user_accepts`⚠, `test_print_document_runs_in_background_and_defers_close_until_helper_finishes`⚠, `test_stalled_print_helper_can_be_terminated_without_closing_main_window`⚠, `test_terminate_active_print_submission_handles_reentrant_runner_cleanup`⚠
**Methods:** 34 total, 1 never-called

### `test_scripts/test_print_dialog_properties_button.py`
*Regression tests for print dialog native printer properties button.*
**Classes:** `_FakeDispatcher`
**Functions:** `_ensure_app`, `_make_single_page_pdf`, `test_properties_button_calls_dispatcher_when_supported`⚠, `test_properties_button_disabled_when_not_supported`⚠, `test_properties_button_syncs_dialog_fields_from_system_preferences`⚠, `test_properties_button_keeps_auto_paper_and_orientation_app_owned`⚠, `test_properties_tray_preferences_are_inherited_without_dialog_field`⚠, `test_user_changed_hardware_field_marks_only_that_override`⚠, `test_opening_properties_resets_touched_overrides`⚠, `test_properties_cancel_keeps_current_ui_and_touched_state`⚠, `test_driver_private_properties_use_system_color_state_in_ui`⚠, `test_switching_printers_resets_touched_overrides_and_loads_new_defaults`⚠, `test_preview_errors_are_handled_without_raising_from_ui_path`⚠, `test_preview_provider_supports_dialog_without_temp_pdf_path`⚠, `test_preview_page_info_label_uses_readable_page_summary`⚠
**Methods:** 6 total, 1 never-called

### `test_scripts/test_print_layout.py`
*Iteration 1 — Print auto paper-size detection + orientation (AC-2, AC-3).  Root cause being fixed: `_to_q_page_size()` f*
**Classes:** `_LayoutPrinter`
**Functions:** `test_match_standard_paper_size_a3_portrait`⚠, `test_match_standard_paper_size_a3_landscape`⚠, `test_match_standard_paper_size_a4`⚠, `test_match_standard_paper_size_letter`⚠, `test_match_standard_paper_size_tabloid`⚠, `test_match_standard_paper_size_non_standard_returns_none`⚠, `test_match_standard_paper_size_tolerates_small_rounding`⚠, `test_to_q_page_size_auto_a3_source_returns_named_a3`⚠, `test_to_q_page_size_auto_a3_landscape_source_returns_named_a3`⚠, `test_to_q_page_size_auto_a4_source_returns_named_a4_not_custom`⚠, `test_to_q_page_size_auto_non_standard_falls_back_to_custom`⚠, `test_to_q_page_size_auto_non_standard_landscape_is_portrait_normalised`⚠, `test_to_q_page_size_explicit_a4_overrides_source`⚠, `test_to_q_page_size_explicit_a3_returns_named_a3`⚠, `test_to_q_page_size_explicit_tabloid_returns_named_tabloid`⚠, `test_set_page_layout_auto_landscape_source_sets_landscape`⚠, `test_set_page_layout_auto_portrait_source_sets_portrait`⚠, `test_set_page_layout_explicit_portrait_overrides_landscape_source`⚠, `test_set_page_layout_explicit_landscape_overrides_portrait_source`⚠, `test_print_dialog_paper_combo_offers_a3`⚠
**Methods:** 5 total, 1 never-called

### `test_scripts/test_print_speed.py`
*AC-9a — print spool throughput.  A 10-page A4 PDF at 300 DPI must be fully rastered and spooled within 20 s. We spool to*
**Functions:** `_make_a4_pdf`, `test_ten_page_a4_300dpi_spools_within_budget`⚠

### `test_scripts/test_print_subprocess_helper.py`
*Helper-process print pipeline tests.*
**Functions:** `_make_single_page_pdf`, `test_run_print_helper_emits_success_events`⚠, `test_run_print_helper_emits_failed_event_on_dispatch_error`⚠, `test_run_print_helper_emits_heartbeat_during_long_submission`⚠

### `test_scripts/test_print_subprocess_runner.py`
*Subprocess runner lifecycle tests.*
**Classes:** `_FakeProcess`
**Functions:** `_ensure_app`, `_pump_until`, `test_runner_emits_stalled_after_silence`⚠, `test_runner_maps_terminated_process_to_helper_terminated_error`⚠, `test_runner_logs_startup_error_and_uses_sys_executable`⚠, `test_runner_heartbeat_events_prevent_false_stall`⚠
**Methods:** 11 total, 2 never-called

### `test_scripts/test_printing_pipeline.py`
*Cross-platform print pipeline validation.  Checks: 1. Accuracy: print-to-PDF output should preserve page visuals/text. 2*
**Classes:** `BenchmarkResult`
**Functions:** `_normalize_text`, `_build_sample_pdf`, `_render_page_gray`, `_page_similarity_score`, `_text_similarity`, `_benchmark_naive`, `_benchmark_on_demand`, `main`

### `test_scripts/test_qt_bridge_layout.py`
*Regression tests for Qt bridge layout, override gating, and pure print-layout helpers.  Covers Phase 1 Items 1–3:   Item*
**Classes:** `_FakePrinter`, `_LayoutPrinter`, `_FakePainter`, `_UniformRenderer`
**Functions:** `test_raster_print_per_page_layout_receives_correct_rects`⚠, `test_raster_print_single_auto_page_calls_layout_once`⚠, `test_set_page_layout_landscape_source_produces_landscape_layout`⚠, `test_set_page_layout_portrait_source_produces_portrait_layout`⚠, `test_set_page_layout_named_a4_portrait_uses_a4_dimensions`⚠, `test_apply_printer_options_skips_tray_when_auto`⚠, `test_apply_printer_options_hardware_setters_gated_by_override_fields`⚠, `test_resolve_page_indices_odd_subset_and_reverse`⚠, `test_compute_target_draw_rect_fit_actual_custom`⚠, `test_print_job_options_normalization_clamps_and_lowercases`⚠
**Methods:** 15 total, 2 never-called

### `test_scripts/test_qt_pixmap_colorspaces.py`
**Functions:** `_make_single_page_pdf`, `test_pixmap_to_qpixmap_bridges_gray_and_cmyk`⚠, `test_pdf_renderer_grayscale_output_matches_rgb_dimensions`⚠

### `test_scripts/test_render_clarity_dpr.py`
*High-quality page renders must be rasterized at the display device-pixel ratio.  Mission: 文件檢視起來還得再更清晰一點 (text/images lo*
**Functions:** `_make_pdf`, `test_high_quality_render_uses_device_pixel_ratio`⚠

### `test_scripts/test_render_colorspace.py`
**Functions:** `_resolve_fixture_pdf`, `test_tool_manager_render_page_pixmap_accepts_colorspace`⚠, `test_pdf_model_render_entry_points_forward_colorspace`⚠

### `test_scripts/test_resolve_target_mode.py`
**Functions:** `_model`, `test_run_without_span_id_logs_warning`⚠, `test_run_with_span_id_does_not_promote`⚠

### `test_scripts/test_rotated_text_editor_preview.py`
*Rotated inline-editor preview must match the frozen-frame orientation.  Mission: 編輯轉向的文字時，文字框裡面的文字也要跟著轉向 (when editing r*
**Functions:** `_ink_dims`, `test_preview_glyphs_stay_upright_for_proxy_rotation`⚠

### `test_scripts/test_sample_pdfs.py`
*使用 1.pdf、2.pdf、when I was young I.pdf 測試 PDF 編輯器 驗證：開啟、建立索引、擷取文字、執行編輯*
**Functions:** `test_pdf`, `main`

### `test_scripts/test_scene_context_menu.py`
**Classes:** `_FakeViewport`, `_FakeGraphicsView`
**Functions:** `_make_view`, `test_scene_context_menu_includes_richer_browse_actions`⚠, `test_scene_context_menu_page_actions_reuse_page_specific_helpers`⚠
**Methods:** 5 total, 0 never-called

### `test_scripts/test_security_cua_allowlist.py`
*Security patch P7 + Task 5 (finding F3): CUA agent action allowlist + bounds.  ``scripts/ux_signoff_agent.py`` is a dev-*
**Classes:** `_Action`, `_FakePyAutoGui`
**Functions:** `test_execute_cua_action_blocks_type`⚠, `test_execute_cua_action_blocks_key`⚠, `test_execute_cua_action_blocks_unknown`⚠, `test_execute_cua_action_allows_click`⚠, `test_execute_cua_action_allows_screenshot`⚠, `test_execute_cua_action_rejects_out_of_window_click`⚠, `test_execute_cua_action_rejects_out_of_window_move`⚠, `test_execute_cua_action_allows_in_window_click`⚠, `test_execute_cua_action_no_rect_skips_bounds`⚠
**Methods:** 8 total, 0 never-called

### `test_scripts/test_security_dispatcher_temp_cleanup.py`
*Security patch P5 (finding F5 / bandit B110): temp-unlink error visibility.  ``PrintDispatcher.print_pdf_bytes`` writes *
**Functions:** `test_print_pdf_bytes_logs_unlink_failure_at_debug`⚠

### `test_scripts/test_security_logging_level.py`
*Security patch P6 (finding F7): release logging level.  `main._configure_logging` must default the root logger to WARNIN*
**Functions:** `_isolated_root_logging`, `test_configure_logging_defaults_to_warning`⚠, `test_configure_logging_debug_env_enables_debug`⚠, `test_configure_logging_empty_env_value_is_not_debug`⚠

### `test_scripts/test_security_ocr_requirements.py`
*Task 2 (finding F2): lock the OCR-extra dependency file's documented decisions.  surya-ocr transitively constrains pillo*
**Functions:** `_requirements`, `test_ocr_requirements_file_exists`⚠, `test_surya_ocr_is_declared_in_ocr_file`⚠, `test_transformers_not_pinned_to_unvalidated_5x`⚠

### `test_scripts/test_security_ocr_weights.py`
*Security finding F9 (CWE-494): OCR weight revision pin + SHA256 verification.  surya downloads detection/recognition wei*
**Functions:** `_make_bundle`, `test_sha256_file_matches_hashlib`⚠, `test_resolve_weights_dir_from_env`⚠, `test_pinned_checkpoints_default_pins_three_models`⚠, `test_pinned_checkpoints_revision_override_targets_ocr_only`⚠, `test_verify_weights_dir_accepts_matching_hash`⚠, `test_verify_weights_dir_rejects_mismatched_hash`⚠, `test_verify_weights_dir_rejects_missing_file`⚠, `test_verify_weights_dir_empty_manifest_fails_closed`⚠, `test_verify_weights_dir_missing_directory`⚠, `test_enforce_policy_no_bundle_pins_revisions_online`⚠, `test_enforce_policy_does_not_mutate_os_environ`⚠, `test_enforce_policy_bundle_mismatch_refuses`⚠, `test_enforce_policy_bundle_match_allows_offline`⚠, `test_adapter_refuses_load_on_weight_failure`⚠

### `test_scripts/test_security_pdf_resource_guards.py`
*Security patch P1 (finding F1): PDF resource guards.  Untrusted PDFs are parsed/rasterized with no bound on file size, p*
**Classes:** `_FakeStat`, `_FakePath`, `_FakeRect`, `_FakePage`
**Functions:** `test_guard_before_open_rejects_oversize`⚠, `test_guard_before_open_allows_normal_size`⚠, `test_safe_render_scale_clamps_huge_page`⚠, `test_safe_render_scale_leaves_normal_page_untouched`⚠, `test_safe_render_scale_floors_at_min`⚠, `_make_pdf`, `test_open_pdf_rejects_oversize_before_parsing`⚠, `test_open_pdf_rejects_excess_page_count`⚠, `test_open_pdf_allows_normal_document`⚠, `test_render_page_pixmap_clamps_oversized_scale`⚠
**Methods:** 5 total, 0 never-called

### `test_scripts/test_security_pillow_floor.py`
*Security patch P8 + Task 2 (finding F2): Pillow dependency floor & OCR split.  `Pillow>=9.0` resolves to releases carryi*
**Functions:** `_pillow_floor`, `_has_surya`, `test_pillow_floor_is_at_least_12_2_0`⚠, `test_surya_ocr_not_in_core_requirements`⚠, `test_surya_ocr_not_in_optional_requirements`⚠

### `test_scripts/test_security_single_instance_isolation.py`
*Security patch P2 (finding F6): single-instance IPC user-isolation.  Two hardening measures:   1. The QLocalServer is cr*
**Classes:** `_FakeSocket`
**Functions:** `test_listen_server_enables_user_access_option`⚠, `_run_message`, `test_handle_socket_message_rejects_nonexistent_path`⚠, `test_handle_socket_message_rejects_non_pdf_path`⚠, `test_handle_socket_message_accepts_existing_pdf`⚠
**Methods:** 8 total, 0 never-called

### `test_scripts/test_security_subprocess_paths.py`
*Security patch P3 (finding F4 + Linux lp/lpstat): absolute subprocess paths.  External binaries must be launched via an *
**Functions:** `_make_fake_run`, `test_win_rundll32_uses_absolute_system32_path`⚠, `test_linux_get_default_printer_uses_absolute_lpstat_path`⚠, `test_linux_list_printers_uses_absolute_lpstat_path`⚠, `test_linux_submit_via_lp_uses_absolute_lp_path`⚠

### `test_scripts/test_security_watermark_coercion.py`
*Security patch P4 (finding F8): watermark JSON coercion on load.  Embedded watermark metadata comes from untrusted PDF b*
**Functions:** `test_coerce_clamps_oversized_font_size`⚠, `test_coerce_floors_tiny_font_size`⚠, `test_coerce_truncates_long_text`⚠, `test_coerce_caps_page_count`⚠, `test_coerce_clamps_opacity_and_wraps_angle`⚠, `test_coerce_drops_wrong_type_pages`⚠, `test_coerce_drops_missing_required_keys`⚠, `test_coerce_preserves_valid_watermark_fields`⚠, `test_load_watermarks_drops_bad_entries_and_clamps_good`⚠

### `test_scripts/test_short_term_safety.py`
**Classes:** `_NamedCommand`, `_UndoBoomCommand`
**Functions:** `qapp`⚠, `_make_pdf`, `_find_block`, `test_inline_text_editor_emits_focus_out_signal_without_monkeypatch`⚠, `test_command_manager_undo_keeps_command_on_failure`⚠, `test_command_manager_evicts_oldest_entries_at_max_limit`⚠, `test_edit_text_reports_rollback_failures`⚠, `test_restore_page_from_snapshot_does_not_delete_live_page_when_insert_fails`⚠, `test_restore_page_from_snapshot_inserts_replacement_before_deleting_original`⚠
**Methods:** 5 total, 1 never-called

### `test_scripts/test_single_instance_forwarding.py`
**Functions:** `_pump_until`, `_make_pdf`, `_cleanup_server`, `_cleanup_startup`, `test_single_instance_server_receives_forwarded_argv`⚠, `test_try_become_server_returns_none_when_server_alive`⚠, `test_try_become_server_cleans_stale_socket`⚠, `test_controller_handle_forwarded_cli_opens_forwarded_files`⚠

### `test_scripts/test_snapshot_restore.py`
**Functions:** `_model`, `test_restore_preserves_page_count`⚠, `test_restore_is_idempotent`⚠, `test_restore_validates_xref_table`⚠

### `test_scripts/test_structural_indexing.py`
**Functions:** `_make_three_page_doc`, `test_insert_blank_page_rebuilds_inserted_page_and_marks_shifted_pages_stale`⚠, `test_shifted_page_is_rebuilt_on_demand_after_delete`⚠, `test_insert_pages_from_file_rebuilds_inserted_pages_and_marks_shifted_pages_stale`⚠, `test_structural_undo_avoids_full_rebuild_and_rebuilds_only_affected_pages`⚠, `test_insert_pages_from_file_returns_actual_insert_positions_after_validation`⚠, `test_delete_pages_returns_actual_deleted_pages_after_validation`⚠, `test_insert_blank_page_returns_actual_insert_position_after_validation`⚠

### `test_scripts/test_text_edit_finalize_outcome.py`
**Functions:** `_make_session`, `test_failed_outcome_exists`⚠, `test_finalize_returns_failed_when_emit_raises`⚠

### `test_scripts/test_text_edit_manager_foundation.py`
**Classes:** `_FakeSignal`, `_FakeEditorWidget`, `_FakeProxy`, `_FakeCombo`, `_FakeScene`
**Functions:** `_make_view`, `test_pdf_view_init_does_not_warn_about_outline_disconnects`⚠, `test_pdf_view_exposes_text_edit_manager_on_real_init`⚠, `test_finalize_emits_typed_edit_request_payload`⚠, `test_sig_move_text_emits_move_text_request`⚠, `test_move_text_request_fields_match_session`⚠, `test_controller_accepts_move_text_request`⚠, `test_controller_updates_undo_redo_enabled_state_from_command_manager`⚠, `test_controller_edit_text_shows_error_toast_for_invalid_result`⚠, `test_edit_text_command_initializes_result_before_execute`⚠, `test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands`⚠, `test_edit_text_command_execute_annotation_is_bool`⚠
**Methods:** 10 total, 0 never-called

### `test_scripts/test_text_editing_fidelity_suite.py`
**Functions:** `_build_model_with_doc`, `_first_block`, `_edit_block`, `test_latin_single_line_edit_preserves_font_pt`⚠, `test_cjk_single_line_edit_preserves_height`⚠, `test_fractional_font_pt_round_trips_through_edit`⚠, `test_repeated_ten_edits_cumulative_drift_under_half_pt`⚠, `test_preview_pixmap_dimensions_match_render_scale_2x`⚠, `test_bold_flag_preserved_through_edit`⚠, `test_italic_flag_preserved_through_edit`⚠, `test_non_black_color_preserved_through_edit`⚠, `test_multi_line_wrap_column_matches_source`⚠, `test_tight_leading_honored_on_commit`⚠, `test_loose_leading_honored_on_commit`⚠, `test_position_anchor_drift_under_half_pt_at_all_corners`⚠, `test_mixed_latin_cjk_span_renders_both_scripts`⚠, `test_vertical_rotated_text_edit_preserves_orientation_and_size`⚠, `test_preview_pixmap_width_equals_source_rect_times_render_scale`⚠, `test_preview_render_produces_visible_text_pixels`⚠, `test_preview_render_at_render_scale_2x_doubles_pixel_dimensions`⚠, `test_preview_render_caches_identical_input`⚠, `test_preview_render_rotation_90_swaps_pixel_dimensions`⚠, `test_preview_render_uses_explicit_line_height_not_auto`⚠, `test_inline_editor_glyph_height_matches_pdf_at_render_scale_2x`⚠, `test_glyph_height_parity_negative_control`⚠, `test_glyph_height_1pct_gate_rejects_2px_delta`⚠

### `test_scripts/test_text_editing_gui_regressions.py`
**Classes:** `_FakeSignal`, `_FakeEditorWidget`, `_FakeEditorDocument`, `_FakeShortcutEditorWidget`, `_FakeAction`, `_FakeProxy`, `_FakeInlineSignal`, `_FakeInlineDocSignal`, `_FakeInlineDocument`, `_FakeInlineViewport`, `_FakeInlineTextEditor`, `_FakeRectItem`, `_FakePixmap`, `_FakePageItem`, `_FakeScene`, `_FakeCombo`, `_FakeViewport`, `_FakeGraphicsView`, `_FakeViewportWithHeight`, `_FakeGraphicsViewWithViewportHeight`, `_FakeMouseEvent`, `_FractionalCombo`, `_FakeSceneCapture`
**Functions:** `_make_view`, `_attach_text_property_panel`, `_capture_context_menu_labels`, `_make_image`, `test_finalize_skips_emit_for_normalized_noop_edit`⚠, `test_text_property_panel_helper_disables_actions_without_editor`⚠, `test_text_property_panel_helper_shows_selection_state_without_enabling_actions`⚠, `test_text_property_panel_helper_enables_actions_for_live_editor`⚠, `test_text_property_panel_live_editor_uses_pdf_size_state_not_display_pt`⚠, `test_context_menu_includes_safe_browse_actions_for_selection`⚠, `test_start_text_selection_requires_text_hit_and_stores_start_run`⚠, `test_start_text_selection_rejects_block_fallback_hits`⚠, `test_finalize_text_selection_uses_run_anchored_snapshot_and_preserves_start_hit_info`⚠, `test_context_menu_offers_edit_text_when_point_hits_editable_text`⚠, `test_escape_marks_current_editor_as_discard_before_finalize`⚠, `test_small_drag_can_activate_editor_move`⚠, `test_drag_across_page_updates_editing_page_idx`⚠, `test_drag_page_resolution_follows_cross_page_target_when_present`⚠, `test_finalize_cross_page_existing_text_emits_move_signal_only`⚠, `test_average_image_rect_color_returns_local_average`⚠, `test_sample_page_mask_color_uses_local_scene_crop`⚠, `test_drag_move_refreshes_editor_mask_color`⚠, `test_editor_shortcut_forwarder_keeps_save_forwarding`⚠, `test_editor_shortcut_forwarder_keeps_save_as_forwarding`⚠, `test_editor_shortcut_forwarder_handles_escape_before_ctrl_guard`⚠, `test_editor_shortcut_forwarder_uses_local_undo_redo_history`⚠, `test_save_shortcut_finalizes_editor_before_emitting_save`⚠, `test_save_as_shortcut_finalizes_editor_before_emitting_save_as`⚠, `test_save_as_uses_current_document_default_path_when_present`⚠, `test_finalize_noop_records_explicit_result`⚠, `test_finalize_position_only_existing_text_records_commit_result`⚠, `test_editor_shortcut_forwarder_consumes_empty_local_history_without_fallback`⚠, `test_toggle_document_undo_redo_actions_disables_and_reenables`⚠, `test_update_undo_redo_enabled_prefers_local_editor_history`⚠, `_make_view_for_finalize`, `test_mode_switch_commits_edit_not_discards`⚠, `test_escape_still_discards`⚠, `test_block_outlines_only_drawn_for_visible_pages`⚠, `test_block_outlines_follow_run_boxes_in_run_mode`⚠, `test_paragraph_outlines_use_light_blue_dashed_border`⚠, `test_build_text_editor_stylesheet_keeps_editor_background_transparent`⚠, `test_create_text_editor_keeps_background_transparent_for_edit_and_add_text`⚠, `test_create_text_editor_rotates_proxy_for_vertical_text`⚠, `test_create_text_editor_adds_mask_item_to_hide_display_text`⚠, `test_finalize_text_edit_removes_mask_item`⚠, `test_cmd_shift_z_fires_redo`⚠, `test_phase2_finalize_preserves_fractional_font_size_in_edit_request`⚠, `test_phase2_create_text_editor_records_fractional_initial_size`⚠, `test_phase2_refresh_mask_matches_local_background_with_texture_underlay`⚠, `test_phase2_refresh_mask_falls_back_to_dark_underlay_for_light_text`⚠, `_make_phase2_height_view`, `test_phase2_editor_height_fits_content_not_paragraph_rect`⚠, `test_phase2_editor_height_accommodates_wrapped_paragraph`⚠, `test_editor_height_capped_to_viewport_ratio_for_long_text`⚠, `test_phase2_editor_font_matches_pdf_render_scale`⚠, `test_phase2_editor_height_honors_embedded_newlines`⚠, `test_create_text_editor_uses_source_span_font_size_and_width`⚠, `test_preview_pixmap_dimensions_match_render_scale_2x`⚠, `test_preview_pixmap_width_equals_source_rect_times_render_scale`⚠, `test_preview_backed_editor_font_is_callable`⚠, `test_preview_backed_editor_paintEvent_shows_text_pixels`⚠
**Methods:** 81 total, 0 never-called

### `test_scripts/test_text_extraction_line_joining.py`
**Functions:** `_make_wrapped_pdf`, `_make_multicolumn_pdf`, `_make_bullets_pdf`, `_make_two_line_pdf`, `_make_multi_run_lines_pdf`, `test_fallback_extraction_space_joins_wrapped_lines`⚠, `test_paragraph_builder_space_joins_visual_lines`⚠, `test_multicolumn_hit_detection_does_not_merge_columns`⚠, `test_bullet_items_keep_semantic_breaks`⚠, `test_get_text_in_rect_expands_partial_clip_to_whole_visual_lines`⚠, `test_get_text_bounds_expands_partial_clip_to_full_visual_line_bounds`⚠, `test_run_anchored_selection_uses_partial_boundary_lines_and_full_middle_lines`⚠, `test_run_anchored_selection_keeps_reading_order_for_backward_drag_same_line`⚠, `test_exact_run_hit_ignores_block_whitespace_fallback`⚠, `test_run_anchored_selection_uses_nearest_run_when_mouseup_is_in_block_whitespace`⚠

### `test_scripts/test_text_normalization.py`
**Functions:** `test_normalize_strips_whitespace`⚠, `test_normalize_lowercases`⚠, `test_normalize_expands_fi_ligature`⚠, `test_normalize_expands_ff_ligature`⚠, `test_normalize_empty`⚠, `test_similarity_identical`⚠, `test_similarity_one_empty`⚠, `test_similarity_substring`⚠, `test_token_coverage_full`⚠, `test_token_coverage_empty_source`⚠, `test_token_coverage_no_match`⚠

### `test_scripts/test_text_selection.py`
*AC-1 — character-level browse-mode text selection.  The legacy selection worked at run/line granularity: any drag highli*
**Functions:** `_make_text_pdf`, `_first_run`, `test_get_chars_in_run_returns_per_character_boxes`⚠, `test_same_run_drag_selects_only_character_range`⚠, `test_same_run_drag_is_order_independent`⚠, `test_cross_run_same_line_clips_both_boundaries`⚠, `test_multi_run_selection_fetches_rawdict_once`⚠, `test_multi_line_drag_partial_first_full_middle_partial_last`⚠

### `test_scripts/test_theme_and_icons.py`
*Tests for the theme registry, QSS builder, icon loader, and theme switcher.  Token / registry / build_qss / icon-map tes*
**Classes:** `_FakeStore`
**Functions:** `test_token_dicts_all_keys`⚠, `test_token_accent_values`⚠, `test_registry_ids_exact`⚠, `test_registry_matches_canonical_valid_ids`⚠, `test_swatch_is_bg_color`⚠, `test_registry_meta_id_matches_key`⚠, `test_build_qss_all_themes_contain_colors`⚠, `test_build_qss_unknown_falls_back_to_alpine_snow`⚠, `test_build_qss_default_is_alpine_snow`⚠, `test_ribbon_rules_are_scoped`⚠, `test_sidebar_rules_present`⚠, `test_document_tabbar_rules_present`⚠, `test_panel_rules_present`⚠, `test_dark_theme_has_foreground`⚠, `test_all_themes_pair_bg_and_fg`⚠, `test_dialog_themed`⚠, `test_native_controls_themed`⚠, `test_qmenu_rules_present`⚠, `test_combobox_dropdown_themed`⚠, `test_dark_dialog_renders_dark`⚠, `test_action_icon_map_covers_core_actions`⚠, `test_load_icon_unknown_label_returns_null`⚠, `test_load_icon_known_label_returns_icon`⚠, `test_load_icon_straighten_page`⚠, `test_chip_count_matches_registry`⚠, `test_chip_single_square`⚠, `test_active_chip_on_init`⚠, `test_theme_selected_signal_emits`⚠, `test_set_active_theme_updates_chips`⚠, `test_apply_initial_theme_sets_app_stylesheet`⚠, `test_construction_does_not_mutate_global_stylesheet`⚠, `test_switcher_applies_theme_without_a_controller`⚠, `test_graphics_view_no_inline_stylesheet`⚠, `test_document_tabbar_no_inline_stylesheet`⚠, `test_toolbar_container_height`⚠, `test_toolbar_button_style`⚠, `test_toolbar_icon_size`⚠, `test_straighten_action_has_icon`⚠
**Methods:** 3 total, 0 never-called

### `test_scripts/test_thumbnail_context_menu.py`
**Classes:** `_FakeSignal`, `_FakeItem`, `_FakeViewport`, `_FakeThumbnailList`
**Functions:** `_make_view`, `test_thumbnail_context_menu_exposes_page_operations`⚠, `test_delete_rotate_and_insert_helpers_emit_page_specific_signals`⚠, `test_export_specific_pages_defaults_to_pdf_when_filter_is_pdf`⚠, `test_insert_pages_from_file_at_uses_given_position`⚠
**Methods:** 8 total, 0 never-called

### `test_scripts/test_tool_extensions.py`
**Functions:** `model_with_text_pdf`⚠, `test_search_returns_results`⚠, `test_search_empty_returns_empty`⚠, `test_search_no_doc_returns_empty`⚠, `test_ocr_no_doc_returns_empty`⚠, `test_ocr_invalid_page_raises`⚠, `test_rawdict_text_compat_backfills_keyword_option`⚠, `test_close_all_sessions_tolerates_new_bypass_instance`⚠

### `test_scripts/test_track_ab_5scenarios.py`
*Track A/B 五大 UX 場景診斷測試 ──────────────────────────────── 目標：以 headless model-level API 驗證五個關鍵場景，不需 Qt UI。  Scenario 1: 同段*
**Functions:** `_make_paragraph_pdf`, `_make_simple_pdf`, `_make_multiline_style_pdf`, `_make_consecutive_edit_pdf`, `_page_text`, `_norm`, `_find_block`, `_find_run`, `_edit`, `scenario_1_displacement`⚠, `scenario_2_no_silent_noop`⚠, `scenario_2b_same_length`⚠, `scenario_3_position_consistency`⚠, `scenario_4_consecutive_undo_redo`⚠, `scenario_5_style_inheritance`⚠, `_make_dense_paragraph_pdf`, `_make_cjk_mixed_pdf`, `scenario_1b_dense_paragraph_displacement`⚠, `scenario_2c_edit_to_empty`⚠, `scenario_3b_position_after_longer_edit`⚠, `scenario_4b_edit_same_block_twice`⚠, `scenario_5b_cjk_mixed_edit`⚠, `_make_multirun_block_pdf`, `_make_tightly_packed_pdf`, `scenario_1c_multirun_edit_single_run`⚠, `scenario_1d_tightly_packed_lines`⚠, `scenario_4c_rapid_consecutive_same_block`⚠, `scenario_real_pdf_edit`⚠, `scenario_7_run_mode_orphan_guard`⚠, `scenario_8_verification_sensitivity`⚠, `main`

### `test_scripts/test_track_ab_model_regressions.py`
*Focused model-level regressions for Track A/B follow-up fixes.  Coverage: 1. Move-only run edit should relocate text wit*
**Functions:** `_norm`, `_clip_has`, `_make_move_pdf`, `_make_multicolor_pdf`, `_find_run`, `_run_case`, `case_move_only_run`⚠, `case_move_only_paragraph_preserves_colors`⚠, `case_missing_protected_span_ids`⚠, `main`

### `test_scripts/test_unified_undo.py`
*Phase 6 測試：統一 undo 堆疊 流程：刪頁 → 編輯文字 → undo × 2 → redo × 2 → 確認頁數與文字都正確復原*
**Functions:** `make_two_page_pdf`, `run`

### `test_scripts/test_user_preferences.py`
**Classes:** `_FakeStore`
**Functions:** `test_default_ocr_device_is_auto`⚠, `test_set_then_get_ocr_device_round_trips`⚠, `test_set_ocr_device_persists_in_store`⚠, `test_set_ocr_device_rejects_unknown_value`⚠, `test_get_ocr_device_recovers_from_corrupt_value`⚠, `test_default_ocr_languages_is_english`⚠, `test_set_ocr_languages_stores_list`⚠, `test_set_ocr_languages_rejects_unknown_code`⚠, `test_set_ocr_languages_rejects_empty_list`⚠, `test_default_theme_is_alpine_snow`⚠, `test_set_then_get_theme_round_trips`⚠, `test_set_theme_persists_across_instances`⚠, `test_set_theme_rejects_unknown_value`⚠, `test_get_theme_recovers_from_corrupt_value`⚠
**Methods:** 3 total, 0 never-called

### `test_scripts/test_ux_signoff_agent.py`
**Functions:** `test_main_fails_closed_without_credentials`⚠, `test_main_isolates_each_pdf_run_and_continues_after_failure`⚠

### `test_scripts/test_week1_model_regressions.py`
**Functions:** `_make_wrapped_paragraph_pdf`, `_make_stacked_blocks_pdf`, `_find_block`, `test_fallback_hit_detection_space_joins_wrapped_lines`⚠, `test_build_paragraphs_space_joins_lines`⚠, `test_same_height_edit_does_not_push_neighbor_block_down`⚠, `test_longer_edit_keeps_original_top_anchor`⚠

### `test_scripts/test_win_driver_properties.py`
*Regression tests for Windows printer properties sync behavior.*
**Classes:** `_FakeDevMode`, `_FakeWin32Print`, `_FakeWin32PrintLimitedPort`, `_FakeWin32PrintUserDefaults`, `_FakeWin32PrintCancel`
**Functions:** `_clone_devmode`, `test_open_printer_properties_returns_prefs_without_persisting`⚠, `test_get_printer_preferences_prefers_richer_tray_list`⚠, `test_get_printer_preferences_prefers_user_defaults_for_color_mode`⚠, `test_open_printer_properties_does_not_persist_user_defaults`⚠, `test_open_printer_properties_cancel_returns_none_without_persisting`⚠
**Methods:** 13 total, 2 never-called

### `test_scripts/test_win_print_fixes.py`
*Red-Light tests for the four Windows printing fixes (P1–P4).  These exercise the *real* Windows driver paths the previou*
**Classes:** `PyFakeHandle`, `_FakeDispatcher`, `_WindowsLikePrinter`
**Functions:** `_ensure_app`, `_make_single_page_pdf`, `_ok_result`⚠, `_install_ctypes_dialog`, `test_open_printer_properties_does_not_call_setprinter`⚠, `test_open_printer_properties_returns_base64_devmode`⚠, `test_print_pdf_applies_devmode_job_scoped_and_restores`⚠, `test_devmode_buffer_injected_at_submission_survives_preview_and_json`⚠, `test_devmode_buffer_cleared_when_printer_switches`⚠, `test_mixed_layout_pdf_splits_into_two_jobs`⚠, `test_uniform_layout_pdf_stays_single_job`⚠, `test_windows_caps_raster_dpi_at_150_but_keeps_lower`⚠, `test_pdf_output_path_is_not_split_or_capped`⚠, `test_finding1_explicit_paper_preserved_when_orientation_auto`⚠, `test_finding2_collated_multicopy_mixed_layout_uses_document_order`⚠, `test_finding2_uncollated_multicopy_mixed_layout_groups_copies_per_page`⚠, `test_finding2_uniform_layout_multicopy_stays_single_job`⚠, `test_finding3_pending_devmode_survives_recoverable_range_error`⚠, `test_finding4_denied_apply_skips_restore_and_still_prints`⚠, `test_finding6_partial_failure_reports_already_spooled`⚠, `test_finding6_first_group_failure_returns_plain_result`⚠, `test_finding11_malformed_devmode_b64_falls_through_to_split`⚠, `test_finding7_buffer_only_props_do_not_reload_defaults`⚠, `test_set_page_layout_actually_applies_page_size`⚠, `test_set_page_layout_applies_size_on_real_printer`⚠
**Methods:** 11 total, 2 never-called

### `test_scripts/test_xref_repair.py`
*Auto-repair of a damaged XREF table when a PDF is opened.  Mission: 開檔自動修復 XREF 表. PyMuPDF rebuilds a broken cross-refer*
**Functions:** `_valid_pdf_bytes`, `_corrupt_startxref`, `_encrypted_pdf_bytes`, `_is_encrypted`, `test_open_damaged_pdf_auto_repairs_in_memory`⚠, `test_open_damaged_encrypted_pdf_keeps_encryption`⚠, `test_open_damaged_owner_only_pdf_keeps_encryption`⚠, `test_open_healthy_pdf_is_left_file_backed`⚠

### `test_scripts/validate_optimized_pdf.py`
**Functions:** `_tail_has_eof`, `_sample_page_indexes`, `validate_pdf_integrity`, `main`

### `utils/__init__.py`
*Utility helpers shared across layers.*

### `utils/helpers.py`
**Functions:** `parse_pages`, `show_error`, `pixmap_to_qimage`, `pixmap_to_qpixmap`

### `utils/preferences.py`
**Classes:** `_SettingsLike`, `UserPreferences`
**Functions:** `_make_default_store`
**Methods:** 9 total, 0 never-called

### `utils/single_instance.py`
**Functions:** `_build_server_name`, `_remove_server`, `_listen_server`, `_probe_live_server`, `_make_lock`, `_try_acquire_lock`, `_process_events`, `_wait_for_ready_read`, `_service_local_server`, `_normalize_forwarded_argv`, `_forwarded_argv_is_acceptable`, `_handle_socket_message`, `try_become_server`, `send_to_running_instance`

### `utils/theme_ids.py`
*Canonical theme identifiers — the single source of truth for valid themes.  This is a dependency-free leaf module so bot*

### `view/__init__.py`
*View layer — Qt widgets, scene interactions, signal emission.*

### `view/dialogs/__init__.py`

### `view/dialogs/audit.py`
**Classes:** `AuditStackedBar`, `PdfAuditReportDialog`
**Methods:** 7 total, 1 never-called

### `view/dialogs/export.py`
**Classes:** `ExportPagesDialog`
**Methods:** 4 total, 1 never-called

### `view/dialogs/merge.py`
**Classes:** `MergePdfDialog`
**Methods:** 10 total, 1 never-called

### `view/dialogs/ocr.py`
**Classes:** `OcrDialog`
**Methods:** 12 total, 1 never-called

### `view/dialogs/optimize.py`
**Classes:** `OptimizePdfDialog`
**Methods:** 10 total, 3 never-called

### `view/dialogs/password.py`
**Classes:** `PDFPasswordDialog`
**Methods:** 4 total, 1 never-called

### `view/dialogs/watermark.py`
**Classes:** `WatermarkDialog`
**Methods:** 4 total, 1 never-called

### `view/icons.py`
*Toolbar icon loading and the action-text -> PNG-filename mapping.  Icons live in ``appearance_design/function_icons/`` a*

### `view/pdf_view.py`
**Classes:** `_NoCtrlTabTabBar`, `PDFView`
**Functions:** `_ctrl_tab_direction`, `compute_object_resize_rect`, `screen_angle_degrees`, `absolute_rotation_from_drag`
**Methods:** 247 total, 50 never-called

### `view/text_editing.py`
**Classes:** `TextEditUIConstants`, `TextEditGeometryConstants`, `TextEditFinalizeReason`, `TextEditOutcome`, `TextEditReason`, `TextEditDragState`, `TextEditDelta`, `TextEditFinalizeResult`, `TextEditSession`, `_EditorShortcutForwarder`, `InlineTextEditor`, `ViewportAnchor`, `PreviewRenderer`, `PreviewBackedInlineTextEditor`, `TextEditManager`
**Functions:** `_parse_font_size_str`, `_format_font_size`, `_readable_editor_mask_color`, `_normalize_for_edit_compare`, `_average_image_rect_color`, `_contrast_ratio_rgb`, `_qimage_mean_rgb`, `_qimage_ring_mean_rgb`, `_blend_patch_towards_rgb`, `_mask_leak_ratio`, `_make_fallback_mask_result`, `_widget_logical_dpi`, `_display_font_pt`, `_measure_text_content_height_px`, `_compute_editor_proxy_layout`, `_viewport_editor_height_cap_px`, `_alias_font_family`, `_map_legacy_reason`, `finalize_text_edit_impl`
**Methods:** 35 total, 2 never-called

### `view/theme.py`
*Theme tokens, the global QSS builder, and the status-bar theme switcher.  Translates the selected blocks of ``appearance*
**Classes:** `ThemeMeta`
**Functions:** `_meta`⚠, `build_qss`
