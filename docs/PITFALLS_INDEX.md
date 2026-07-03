# PITFALLS index (generated — do not edit)

Regenerate: `python scripts/build_pitfalls_index.py` · 154 entries.
Read matched entries from `docs/PITFALLS.md` with `Read(offset=<line>, limit=~15)`.

| Line | Title | Area |
|---|---|---|
| 8 | Import-time `sys.exit` aborts pytest collection for the whole suite | `scripts/ux_signoff_agent.py` (R0.2) |
| 18 | Exact-count test assertions go stale on additive changes | `test_scripts/test_theme_and_icons.py` (R0.1) |
| 28 | PyMuPDF 1.27 names a stream-opened doc `"pdf"`, not `""` | `model/pdf_model.py` repair round-trip; `test_scripts/test_xref_repair.py` (R0.4) |
| 38 | PyMuPDF 1.27 `insert_htmlbox` renders nothing on overflow at `scale_low=1` | `view/text_editing.py` `PreviewRenderer.render`; `test_scripts/test_rotated_text_editor_preview.py` (R0.4) |
| 48 | Stall watchdog needs an injectable clock to be testable under load | `src/printing/subprocess_runner.py`; `test_scripts/test_print_subprocess_runner.py` (R0.3) |
| 58 | Windows fatal exception `0x80040155` in the offscreen test suite is benign | test suite under `QT_QPA_PLATFORM=offscreen` (R0.4) |
| 68 | `ruff --fix` (F401) silently strips an intentional re-export | `model/pdf_model.py` (R1.1) |
| 78 | Module docstring after `from __future__` makes every import E402 | `model/pdf_optimizer.py` (R1.1) |
| 88 | Consolidating identity strings must preserve IPC prefixes byte-identical | `utils/app_identity.py`, `utils/single_instance.py`, `utils/preferences.py` (R1.2) |
| 98 | PDF cm tokens must not use scientific notation | `model/pdf_content_ops.py` |
| 108 | Probe-growth logs must not reference undefined or misleading variables | `model/pdf_model.py` |
| 118 | Rotated text editors need proxy geometry, not just a stored rotation flag | `view/text_editing.py` |
| 128 | Single-line htmlbox edits can drift the text anchor | `model/pdf_model.py` |
| 138 | Edit-mode outlines must follow selectable targets, not coarse blocks | `view/pdf_view.py` |
| 148 | Transparent inline editors still need a separate scene mask | `view/pdf_view.py`, `view/text_editing.py` |
| 158 | Raw clip extraction returns chopped words for drag selection | `model/pdf_model.py`, `model/tools/annotation_tool.py` |
| 168 | Run-anchored browse selection cannot rely on cached `(block_idx, line_idx)` alone | `model/pdf_model.py` |
| 178 | Browse selection must not use block fallback for run anchoring | `model/pdf_model.py`, `controller/pdf_controller.py`, `view/pdf_view.py` |
| 188 | Printer preferences must not overwrite source-following auto layout | `src/printing/print_dialog.py`, `src/printing/qt_bridge.py`, `src/printing/platforms/linux_driver.py` |
| 198 | Qt custom landscape page sizes must use portrait-ordered base dimensions | `src/printing/qt_bridge.py` |
| 208 | CMYK pixmaps must be converted before constructing `QImage` | `src/printing/pdf_renderer.py` |
| 218 | Open-time background work can steal responsiveness from the first visible page | `controller/pdf_controller.py` |
| 228 | Save As default path can drift from the active tab | `controller/pdf_controller.py`, `view/pdf_view.py` |
| 238 | Wide thumbnail sidebars should center, not endlessly stretch | `view/pdf_view.py` |
| 248 | PyMuPDF font sizes are floats, not ints | `model/pdf_model.py`, `view/text_editing.py` |
| 258 | Cross-page move controller signature drift breaks legacy callers | `controller/pdf_controller.py` ??`move_text_across_pages` |
| 268 | Windows parallel image rewrite disabled under pytest / non-script launchers | `model/pdf_optimizer.py` ??`can_use_parallel_image_rewrite` |
| 278 | TEXT_PRESERVE_LIGATURES breaks push-down re-insert | `model/pdf_model.py` — `_push_down_overlapping_text` |
| 288 | push-down insert_text(helv) drops non-Latin Unicode (€, emoji) | `model/pdf_model.py` — `_push_down_overlapping_text` |
| 298 | Vertical text double-redact erases adjacent horizontal text | `model/pdf_model.py` — `edit_text` vertical branch |
| 308 | Multi-style paragraph edit collapses all runs to one color | `model/pdf_model.py` — `_apply_redact_insert` |
| 318 | Inline editor opens with oversized grey void below single-line text | `view/text_editing.py` — `_compute_editor_proxy_layout`, `create_text_editor` |
| 328 | Inline editor mask samples text into a grey rectangle | `view/text_editing.py` - `refresh_text_editor_mask_color` |
| 338 | Inline editor glyphs look smaller than the underlying PDF text | `view/text_editing.py` — `create_text_editor`, `on_edit_font_size_changed` |
| 348 | Test fixture skips `__init__` — manually inject `_autopan_active` | `test_scripts/test_text_editing_gui_regressions.py` |
| 358 | Continuous mode `change_scale` only redraws one page | `controller/pdf_controller.py` — `change_scale` |
| 368 | Zoom combo always shows 100% | `controller/pdf_controller.py`, `view/pdf_view.py` |
| 378 | QToolBar overflow hides Undo/Redo buttons | `view/pdf_view.py` — right toolbar |
| 388 | PDFModel has no `.open()` method — it is `.open_pdf()` | test scripts |
| 398 | focusOutEvent recursive call in text editor finalization | `view/pdf_view.py` — `_finalize_text_edit` |
| 408 | Drag clamp produces invalid rect when target is fully off-page | `model/pdf_model.py` / `view/pdf_view.py` — clamp helpers |
| 418 | Merge list reorder lost on next add/remove | `view/pdf_view.py`, `model/merge_session.py` |
| 428 | Test normalization misses Unicode ligatures | test scripts |
| 438 | Controller activation must be deferred to `activate()` | `controller/pdf_controller.py` |
| 448 | Text index must be rebuilt on-demand after structural ops | `model/pdf_model.py`, `model/text_block.py` |
| 458 | Edit request dataclasses must stay Qt-free | `model/edit_requests.py`, `controller/pdf_controller.py`, `view/text_editing.py` |
| 468 | App-owned object identity must not rely on text-span discovery | `model/pdf_model.py`, `view/pdf_view.py`, `controller/pdf_controller.py` |
| 478 | Low-level Windows GUI injection can diverge from physical browse hits | temporary verification harnesses under `tmp/`, browse/object selection in `view/pdf_view.py` |
| 488 | Browse object drag/selection on `QGraphicsView` must normalize through the viewport | `view/pdf_view.py` |
| 498 | Object rotate handles must be hittable outside the bbox | `view/pdf_view.py` |
| 508 | Textbox move/rotate/delete must purge leftover same-id markers | `model/pdf_model.py` |
| 518 | App-owned image object removal cannot rely on `page.delete_image(xref)` | `model/pdf_model.py` |
| 528 | Native PDF image manipulation must rewrite image invocation operators, not redact page content | `model/pdf_model.py`, `model/pdf_content_ops.py` |
| 538 | Windows `QLocalServer.listen(name)` is not a reliable single-instance guard by itself | `utils/single_instance.py` |
| 548 | Surya's `DetectionPredictor` / `RecognitionPredictor` constructor signature changed | `model/tools/ocr_tool.py` |
| 558 | Fitz `Pixmap` to PIL image must strip alpha before Surya | `model/tools/ocr_tool.py` |
| 568 | Explicit CUDA/MPS selection must be probed before OCR starts | `model/tools/ocr_tool.py`, `view/dialogs/ocr.py` |
| 578 | QAction `setToolTip("")` falls back to the action's text label | `view/pdf_view.py` (availability-gated tooltips) |
| 588 | PySide6 scene.clear() leaves dangling Python wrappers to deleted C++ items | `view/pdf_view.py` — object selection overlay |
| 598 | Auto-pan right-click exit can double-open the context menu | `view/pdf_view.py` |
| 606 | PyMuPDF rawdict drops span['text'] once Qt is live | `model/pdf_model.py` (text extraction), no-jump E2E gate |
| 613 | Inline editor glyphs differ in size from the rendered PDF | `view/text_editing.py` (inline text editor) |
| 620 | test_19b font-size assertion is render-scale/DPI sensitive | `test_scripts/test_multi_tab_plan.py`, gate `full_suite` |
| 628 | Single-line edits dramatically push surrounding text away | `model/pdf_model.py` — `_apply_redact_insert` pre-push probe |
| 638 | Committed text line height diverges from original PDF | `model/pdf_model.py` — `_apply_redact_insert` (call to `_build_insert_css`) |
| 648 | Editor wrap width wider than source rect causes wrapping divergence | `model/pdf_model.py` — `get_render_width_for_edit` |
| 658 | Fidelity tests can pass on no-op edits unless they assert committed content | `test_scripts/test_edit_text_helpers.py` |
| 668 | `_build_insert_css` unconditional clamp defeats explicit tight line heights | `model/pdf_model.py` — `_build_insert_css` |
| 678 | Mixed-script headings split into per-script spans by PyMuPDF | `model/pdf_model.py` — `get_text_info_at_point`, text index |
| 688 | `_needs_cjk_font` monkeypatch in real-PDF tests masks CJK path coverage | `test_scripts/test_edit_text_helpers.py` |
| 698 | Heuristic span discovery in regression tests targets wrong spans after layout change | `test_scripts/test_edit_text_helpers.py` |
| 708 | Preview-backed inline editor must keep Qt text painting suppressed | `view/text_editing.py` |
| 718 | Shared insert-path classification prevents preview/commit drift | `model/pdf_model.py`, `view/text_editing.py` |
| 728 | `editor.font` method shadowed by attribute assignment | `view/text_editing.py` — `TextEditManager.create_text_editor` |
| 738 | `PreviewRenderer.render` returned blank QImage with no rasterization | `view/text_editing.py` — `PreviewRenderer.render` |
| 748 | `_classify_insert_path` returned `"fast"` on empty `member_spans`, caller crashed | `model/pdf_model.py` — `_classify_insert_path` / `_apply_redact_insert` |
| 758 | Click-to-edit causes visible glyph-size jump (no-jump UX) | `view/text_editing.py` — `PreviewBackedInlineTextEditor`, `TextEditManager.create_text_editor` |
| 779 | `insert_htmlbox` with default `scale_low` can produce inconsistent vertical metrics across preview and commit | `view/text_editing.py` — `PreviewRenderer.render` |
| 789 | Block outlines in edit-text mode overlap with inline editor affordance | `view/pdf_view.py` — `_draw_all_block_outlines`, `create_text_editor` / `_finalize_text_edit` |
| 799 | Editor font-size combo and Qt widget font can drift after user changes size mid-edit | `view/text_editing.py` — `TextEditManager.on_edit_font_size_changed` |
| 809 | Paper size matching tie-break selects wrong size on precision edge | `src/printing/layout.py` — `match_standard_paper_size` |
| 819 | Form XObject images not discovered by `page.get_images(full=True)` | `model/pdf_content_ops.py` — `discover_native_image_invocations` |
| 829 | Form-space to page-space coordinate transform analytical solution is brittle | `model/pdf_content_ops.py` — `form_rect_to_stream_cm` |
| 839 | Float rotation angle truncated to int on object hit-test retrieval | `view/pdf_view.py` — `_hit_test_objects`, `ObjectHitInfo` |
| 849 | Character-level run assignment fails for overlapping text lines | `model/pdf_model.py` — `get_chars_in_run` |
| 859 | Test fixture gitignored, tests error out on fresh checkout | `test_scripts/conftest.py` |
| 867 | Context menus and dialogs stay light when QSS is window-scoped | `view/theme.py`, `view/pdf_view.py`, `controller/pdf_controller.py` |
| 874 | Ribbon tab QSS leaks onto the sidebar tab widget | `view/theme.py` |
| 881 | Applying app-level QSS from a widget constructor pollutes the shared-qapp test suite | `view/pdf_view.py`, `main.py` |
| 888 | Printing once permanently mutated the printer's per-user defaults | `src/printing/platforms/win_driver.py`, `src/printing/print_dialog.py` |
| 895 | extra_options must be JSON-serializable (no raw bytes) | `src/printing/helper_protocol.py`, `src/printing/platforms/win_driver.py` |
| 902 | GDI ignores mid-job page-layout changes; mixed-media must be split | `src/printing/qt_bridge.py`, `src/printing/platforms/win_driver.py` |
| 909 | Windows full-DPI raster spools are huge and slow | `src/printing/platforms/win_driver.py`, `src/printing/qt_bridge.py` |
| 916 | Print speed/layout tests can pass while the real path stays broken | `test_scripts/test_print_speed.py`, `test_scripts/test_print_layout.py`, `test_scripts/test_win_print_fixes.py` |
| 923 | QPrinter.setPageLayout() silently drops the page SIZE on the Windows GDI spooler | `src/printing/qt_bridge.py` |
| 930 | Auto XREF repair on open makes the document memory-backed | `model/pdf_model.py` (`open_pdf`, `_repair_doc_xref_in_memory`) |
| 937 | On-open XREF repair must not use `deflate=True` (20× cost on large files) | `model/pdf_model.py` (`_repair_doc_xref_in_memory`) |
| 944 | On-open XREF repair must NOT round-trip an encrypted document (silent password/permission loss) | `model/pdf_model.py` (`open_pdf`, `_repair_doc_xref_in_memory`) |
| 951 | PyMuPDF `doc.save()` defaults `encryption=PDF_ENCRYPT_NONE` — a plain full save *decrypts* | `model/pdf_model.py` (`_full_save_to_path`, `save_as`) |
| 960 | Incremental save needs `encryption=KEEP` too — the default *raises*, silently degrading every encrypted save-back to a full rewrite | `model/pdf_model.py` (`save_as` incremental branch) |
| 968 | Reopen-after-save must re-authenticate or the live session is bricked (once encryption is preserved) | `model/pdf_model.py` (`_full_save_to_path`, `save_as`, `_reopen_doc_after_save`) |
| 977 | Undo/redo snapshots: only the *doc-level* path decrypts — page-level restores in place | `model/pdf_model.py` (`_capture_doc_snapshot`, `_restore_doc_from_snapshot`, `_restore_page_from_snapshot`) |
| 985 | On-open XREF repair peak memory is ~1.15× file size (one serialization buffer), not 2× | `model/pdf_model.py` (`_repair_doc_xref_in_memory`) |
| 994 | Eager module-level imports of optional native deps block cold-boot startup | `view/text_editing.py`, `view/pdf_view.py` |
| 1005 | QApplication-level QSS leaks across tests and shifts inline-editor pixels | test_scripts (process-wide Qt state), view/text_editing.py, view/pdf_view.py |
| 1013 | Preview render must clamp scale for pathological pages | `view/text_editing.py` (`_MuPDFPreviewRenderer._render_preview`), `utils/render_limits.py` |
| 1021 | PyMuPDF `linear=1` removed in 1.24+; the pikepdf-absent fallback save was dead code | `model/pdf_optimizer.py` (optimize-copy save pipeline) |
| 1029 | Foreign-PDF opens need the full resource-guard set, not just the primary open path | `model/pdf_model.py`, `model/headless_merge.py` |
| 1038 | Python negative indexing turns page 0 into a silent doc[-1] mutation | `model/tools/annotation_tool.py` (pattern applies to every `doc[page_num - 1]` site) |
| 1047 | min/max do NOT sanitize NaN — they are argument-order sensitive | `model/tools/watermark_tool.py` (pattern applies to any numeric clamp on untrusted input) |
| 1056 | IPC argv filters must resolve EVERY token — skipping relative paths is a bypass | `utils/single_instance.py` |
| 1065 | Byte-budget eviction must decrement _saved_stack_size or has_pending_changes drifts | `model/edit_commands.py` (`CommandManager._trim_undo_stack_if_needed`) |
| 1074 | Undo byte budget must floor at 1 command and use unique-byte accounting | `model/edit_commands.py` (`CommandManager._trim_undo_stack_if_needed`, `_unique_byte_total`) |
| 1083 | Adjacent-snapshot dedup is only safe for SnapshotCommand pairs | `model/edit_commands.py` (`CommandManager._dedup_top_snapshot_pair`) |
| 1092 | build_print_snapshot signature changed: () -> bytes became (dest: Path) -> None | `model/tools/manager.py`, `model/pdf_model.py`, `controller/pdf_controller.py` |
| 1101 | Thumbnail invalidation must distinguish count-changed from count-unchanged | `controller/pdf_controller.py` (`_invalidate_thumbnails`, `_schedule_thumbnail_batch`), `view/pdf_view.py` (`update_thumbnail_batch`) |
| 1110 | Cross-page text move must invalidate thumbnails | `controller/pdf_controller.py` (`move_text_across_pages`) |
| 1119 | Search worker must be cancelled (and waited for) before any document mutation | `controller/pdf_controller.py` (`_SearchWorker`, `_cancel_search`), `model/tools/search_tool.py` |
| 1128 | Search tab restore must persist completed results, not just the query | `controller/pdf_controller.py`, `view/pdf_view.py` |
| 1136 | Print path must not double-stamp watermark overlays | `model/tools/watermark_tool.py`, `controller/pdf_controller.py`, `src/printing/subprocess_runner.py` |
| 1144 | OCR workers must read from a snapshot, not the live doc | `controller/pdf_controller.py`, `model/tools/ocr_tool.py` |
| 1152 | Cooperative OCR cancellation: per-page only | controller/pdf_controller.py _OcrWorker |
| 1159 | render_page_pixmap must reject page_num=0 | `model/tools/manager.py` (`ToolManager.render_page_pixmap`) |
| 1167 | Wheel zoom must use effective (clamped) factor for the transform | `view/pdf_view.py` (`_wheel_event`) |
| 1175 | Object streams are natively supported by PyMuPDF | `model/pdf_optimizer.py` |
| 1183 | Deskew Can Increase File Size | `model/pdf_model.py` (`straighten_page`) |
| 1192 | Adaptive toolbar preset must use measured width, not window state | `view/pdf_view.py` — `_update_toolbar_style` |
| 1199 | Toolbar preset stale after fullscreen or theme change | `view/pdf_view.py` — `_update_toolbar_style`, `exit_fullscreen_ui`, `apply_theme` |
| 1206 | Qt QSS has no box-shadow or CSS transitions | `view/theme.py`, `view/pdf_view.py` |
| 1213 | QColor() cannot parse `rgba(r,g,b,a)` float-alpha strings | `view/theme.py` — `_parse_qcolor` |
| 1220 | Focus rings must be colour-only to avoid layout shift | `view/theme.py` — `build_qss` |
| 1227 | Free-function extraction silently bypasses method monkeypatching | model/pdf_text_edit.py, model/pdf_object_ops.py (god-module decomposition seams) |
| 1234 | Helper-class extraction: getattr(self,…) and staticmethods escape the self.→self._view transform | view/object_selection.py (R3.6 view seam); applies to any PDFView→manager extraction |
| 1241 | Undo byte-budget must dedup by content, not id() | model/edit_commands.py — `CommandManager._unique_byte_total` / `_dedup_top_snapshot_pair` / `_trim_undo_stack_if_needed` |
| 1248 | OCR invisible text changes doc.tobytes() without bumping render_revision | controller/pdf_controller.py (`capture_worker_snapshot_bytes` cache) + controller/ocr_coordinator.py (`_on_ocr_page_done`) |
| 1255 | Thumbnail threading: render off snapshot bytes, never the live doc — and watermarks vanish | controller/thumbnail_coordinator.py (R4.3 hybrid async thumbnails) |
| 1262 | A test that builds a QPixmap needs the `qapp` fixture or it hangs | test_scripts (any Qt-touching test that constructs QPixmap/QImage→QPixmap off a fixture) |
| 1269 | Overlay raster caching: only watermarks are overlays, and the cache key must capture base content (R4.1 design-note) | model/tools/manager.py (`render_page_pixmap` overlay branch), model/tools/watermark_tool.py, controller `_render_revision`/`_render_cache` |
| 1276 | Optimize-copy of an encrypted PDF must re-apply the password, or it ships unprotected | model/pdf_optimizer.py (`save_optimized_copy` / `reapply_source_encryption`, R5.5) |
| 1283 | Print path wrote a fully decrypted PDF to disk; keep the temp encrypted + pass the password out-of-band | controller/print_coordinator.py + src/printing/subprocess_runner.py + src/printing/helper_main.py (R5.1) |
| 1290 | Building a wheel/sdist in `.venv`: setuptools is too old, and `pip wheel` litters build/ in the repo | packaging / test_scripts/test_security_packaging.py (R5.4) |
| 1297 | `Path.write_text` on Windows rewrites LF→CRLF — don't use it to "revert" a tracked file | tooling / any transient edit-then-restore of a source file on Windows |
| 1304 | Characterization tests are green-by-construction — they need *teeth*, not a red-light | testing / coverage-hardening (R6.1) |
| 1311 | `verify_no_jump.py` full-suite `--ignore` lines go stale — re-audit on every gate change | tooling / no-jump completion gate (R6.2) |
| 1320 | Object-ops (move/rotate/delete) bypassed GC → unbounded growth + deleted-data recovery | `model/pdf_object_ops.py` (R6-01; reopened R3.4) |
| 1329 | `delete_object` now replaces the live `fitz.Document` handle | `model/pdf_object_ops.py` `_purge_deleted_content`; callers/tests |
| 1338 | Delete confidentiality must fail closed, not swallow the GC error | `model/pdf_object_ops.py` `_purge_deleted_content` (Codex F4) |
| 1347 | Optimize-copy must bind to its source session, not live `model.doc` | `model/pdf_optimizer.py`, `controller/pdf_controller.py` (R5-03; Codex F1/F2) |
| 1356 | Re-encryption must preserve the auth role and never publish plaintext at the output | `model/pdf_optimizer.py` `reapply_source_encryption` / `save_optimized_copy` (R5-02, R5-04) |
| 1365 | PyMuPDF `Document.save()`/`tobytes()` default to `garbage=0` — orphans persist on disk | `model/pdf_model.py` save path; relevant to any redaction/delete |
| 1374 | Async thumbnail QThread coordinator was removed (R4) — keep thumbnails synchronous | `controller/pdf_controller.py` (R4-01…R4-04) |
| 1383 | Completed print runner retained its password until the view was destroyed (R5-05) | `src/printing/subprocess_runner.py` |
| 1392 | Packaging guard accepted a find-all `*` discovery pattern (R5-06) | `test_scripts/test_security_packaging.py` |
| 1401 | Windows pip-audit crashes on non-ASCII bytes in requirement files | CI (`dependency-audit` job) / requirement files |
