# PITFALLS index (generated — do not edit)

Regenerate: `python scripts/build_pitfalls_index.py` · 315 entries.
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
| 368 | Centering a page requires updating every scene/document x conversion | continuous rendering and interaction geometry (`view/pdf_view.py`, `view/text_selection.py`, `view/object_selection.py`, `view/text_editing.py`) |
| 378 | Structural TOC remapping must start from the pre-operation entries | `model/pdf_model.py` page insert/delete/move and TOC APIs |
| 388 | Tab detachment must be prepare-first and must not share a live document | `controller/session_transfer.py`, `controller/pdf_controller.py`, `main.py` |
| 398 | Zoom combo always shows 100% | `controller/pdf_controller.py`, `view/pdf_view.py` |
| 408 | QToolBar overflow hides Undo/Redo buttons | `view/pdf_view.py` — right toolbar |
| 418 | PDFModel has no `.open()` method — it is `.open_pdf()` | test scripts |
| 428 | focusOutEvent recursive call in text editor finalization | `view/pdf_view.py` — `_finalize_text_edit` |
| 438 | Drag clamp produces invalid rect when target is fully off-page | `model/pdf_model.py` / `view/pdf_view.py` — clamp helpers |
| 448 | Merge list reorder lost on next add/remove | `view/pdf_view.py`, `model/merge_session.py` |
| 458 | Test normalization misses Unicode ligatures | test scripts |
| 468 | Controller activation must be deferred to `activate()` | `controller/pdf_controller.py` |
| 478 | Text index must be rebuilt on-demand after structural ops | `model/pdf_model.py`, `model/text_block.py` |
| 488 | PyMuPDF forward page moves use a pre-removal destination | `model/pdf_model.py` |
| 499 | Edit request dataclasses must stay Qt-free | `model/edit_requests.py`, `controller/pdf_controller.py`, `view/text_editing.py` |
| 509 | App-owned object identity must not rely on text-span discovery | `model/pdf_model.py`, `view/pdf_view.py`, `controller/pdf_controller.py` |
| 519 | Low-level Windows GUI injection can diverge from physical browse hits | temporary verification harnesses under `tmp/`, browse/object selection in `view/pdf_view.py` |
| 529 | Browse object drag/selection on `QGraphicsView` must normalize through the viewport | `view/pdf_view.py` |
| 539 | Object rotate handles must be hittable outside the bbox | `view/pdf_view.py` |
| 549 | Textbox move/rotate/delete must purge leftover same-id markers | `model/pdf_model.py` |
| 559 | App-owned image object removal cannot rely on `page.delete_image(xref)` | `model/pdf_model.py` |
| 569 | Native PDF image manipulation must rewrite image invocation operators, not redact page content | `model/pdf_model.py`, `model/pdf_content_ops.py` |
| 579 | Windows `QLocalServer.listen(name)` is not a reliable single-instance guard by itself | `utils/single_instance.py` |
| 589 | Surya's `DetectionPredictor` / `RecognitionPredictor` constructor signature changed | `model/tools/ocr_tool.py` |
| 599 | Fitz `Pixmap` to PIL image must strip alpha before Surya | `model/tools/ocr_tool.py` |
| 609 | Explicit CUDA/MPS selection must be probed before OCR starts | `model/tools/ocr_tool.py`, `view/dialogs/ocr.py` |
| 619 | QAction `setToolTip("")` falls back to the action's text label | `view/pdf_view.py` (availability-gated tooltips) |
| 629 | PySide6 scene.clear() leaves dangling Python wrappers to deleted C++ items | `view/pdf_view.py` — object selection overlay |
| 639 | Auto-pan right-click exit can double-open the context menu | `view/pdf_view.py` |
| 647 | PyMuPDF rawdict drops span['text'] once Qt is live | `model/pdf_model.py` (text extraction), no-jump E2E gate |
| 654 | Inline editor glyphs differ in size from the rendered PDF | `view/text_editing.py` (inline text editor) |
| 661 | test_19b font-size assertion is render-scale/DPI sensitive | `test_scripts/test_multi_tab_plan.py`, gate `full_suite` |
| 669 | Single-line edits dramatically push surrounding text away | `model/pdf_model.py` — `_apply_redact_insert` pre-push probe |
| 679 | Committed text line height diverges from original PDF | `model/pdf_model.py` — `_apply_redact_insert` (call to `_build_insert_css`) |
| 689 | Editor wrap width wider than source rect causes wrapping divergence | `model/pdf_model.py` — `get_render_width_for_edit` |
| 699 | Fidelity tests can pass on no-op edits unless they assert committed content | `test_scripts/test_edit_text_helpers.py` |
| 709 | `_build_insert_css` unconditional clamp defeats explicit tight line heights | `model/pdf_model.py` — `_build_insert_css` |
| 719 | Mixed-script headings split into per-script spans by PyMuPDF | `model/pdf_model.py` — `get_text_info_at_point`, text index |
| 729 | `_needs_cjk_font` monkeypatch in real-PDF tests masks CJK path coverage | `test_scripts/test_edit_text_helpers.py` |
| 739 | Heuristic span discovery in regression tests targets wrong spans after layout change | `test_scripts/test_edit_text_helpers.py` |
| 749 | Preview-backed inline editor must keep Qt text painting suppressed | `view/text_editing.py` |
| 759 | Shared insert-path classification prevents preview/commit drift | `model/pdf_model.py`, `view/text_editing.py` |
| 769 | `editor.font` method shadowed by attribute assignment | `view/text_editing.py` — `TextEditManager.create_text_editor` |
| 779 | `PreviewRenderer.render` returned blank QImage with no rasterization | `view/text_editing.py` — `PreviewRenderer.render` |
| 789 | `_classify_insert_path` returned `"fast"` on empty `member_spans`, caller crashed | `model/pdf_model.py` — `_classify_insert_path` / `_apply_redact_insert` |
| 799 | Click-to-edit causes visible glyph-size jump (no-jump UX) | `view/text_editing.py` — `PreviewBackedInlineTextEditor`, `TextEditManager.create_text_editor` |
| 820 | `insert_htmlbox` with default `scale_low` can produce inconsistent vertical metrics across preview and commit | `view/text_editing.py` — `PreviewRenderer.render` |
| 830 | Block outlines in edit-text mode overlap with inline editor affordance | `view/pdf_view.py` — `_draw_all_block_outlines`, `create_text_editor` / `_finalize_text_edit` |
| 840 | Editor font-size combo and Qt widget font can drift after user changes size mid-edit | `view/text_editing.py` — `TextEditManager.on_edit_font_size_changed` |
| 850 | Paper size matching tie-break selects wrong size on precision edge | `src/printing/layout.py` — `match_standard_paper_size` |
| 860 | Form XObject images not discovered by `page.get_images(full=True)` | `model/pdf_content_ops.py` — `discover_native_image_invocations` |
| 870 | Form-space to page-space coordinate transform analytical solution is brittle | `model/pdf_content_ops.py` — `form_rect_to_stream_cm` |
| 880 | Float rotation angle truncated to int on object hit-test retrieval | `view/pdf_view.py` — `_hit_test_objects`, `ObjectHitInfo` |
| 890 | Character-level run assignment fails for overlapping text lines | `model/pdf_model.py` — `get_chars_in_run` |
| 900 | Test fixture gitignored, tests error out on fresh checkout | `test_scripts/conftest.py` |
| 908 | Context menus and dialogs stay light when QSS is window-scoped | `view/theme.py`, `view/pdf_view.py`, `controller/pdf_controller.py` |
| 915 | Ribbon tab QSS leaks onto the sidebar tab widget | `view/theme.py` |
| 922 | Applying app-level QSS from a widget constructor pollutes the shared-qapp test suite | `view/pdf_view.py`, `main.py` |
| 929 | Printing once permanently mutated the printer's per-user defaults | `src/printing/platforms/win_driver.py`, `src/printing/print_dialog.py` |
| 936 | extra_options must be JSON-serializable (no raw bytes) | `src/printing/helper_protocol.py`, `src/printing/platforms/win_driver.py` |
| 943 | GDI ignores mid-job page-layout changes; mixed-media must be split | `src/printing/qt_bridge.py`, `src/printing/platforms/win_driver.py` |
| 950 | Windows full-DPI raster spools are huge and slow | `src/printing/platforms/win_driver.py`, `src/printing/qt_bridge.py` |
| 957 | Print speed/layout tests can pass while the real path stays broken | `test_scripts/test_print_speed.py`, `test_scripts/test_print_layout.py`, `test_scripts/test_win_print_fixes.py` |
| 964 | QPrinter.setPageLayout() silently drops the page SIZE on the Windows GDI spooler | `src/printing/qt_bridge.py` |
| 971 | Auto XREF repair on open makes the document memory-backed | `model/pdf_model.py` (`open_pdf`, `_repair_doc_xref_in_memory`) |
| 978 | On-open XREF repair must not use `deflate=True` (20× cost on large files) | `model/pdf_model.py` (`_repair_doc_xref_in_memory`) |
| 985 | On-open XREF repair must NOT round-trip an encrypted document (silent password/permission loss) | `model/pdf_model.py` (`open_pdf`, `_repair_doc_xref_in_memory`) |
| 992 | PyMuPDF `doc.save()` defaults `encryption=PDF_ENCRYPT_NONE` — a plain full save *decrypts* | `model/pdf_model.py` (`_full_save_to_path`, `save_as`) |
| 1001 | Incremental save needs `encryption=KEEP` too — the default *raises*, silently degrading every encrypted save-back to a full rewrite | `model/pdf_model.py` (`save_as` incremental branch) |
| 1009 | Reopen-after-save must re-authenticate or the live session is bricked (once encryption is preserved) | `model/pdf_model.py` (`_full_save_to_path`, `save_as`, `_reopen_doc_after_save`) |
| 1018 | Undo/redo snapshots: only the *doc-level* path decrypts — page-level restores in place | `model/pdf_model.py` (`_capture_doc_snapshot`, `_restore_doc_from_snapshot`, `_restore_page_from_snapshot`) |
| 1026 | On-open XREF repair peak memory is ~1.15× file size (one serialization buffer), not 2× | `model/pdf_model.py` (`_repair_doc_xref_in_memory`) |
| 1035 | Eager module-level imports of optional native deps block cold-boot startup | `view/text_editing.py`, `view/pdf_view.py` |
| 1046 | QApplication-level QSS leaks across tests and shifts inline-editor pixels | test_scripts (process-wide Qt state), view/text_editing.py, view/pdf_view.py |
| 1054 | Preview render must clamp scale for pathological pages | `view/text_editing.py` (`_MuPDFPreviewRenderer._render_preview`), `utils/render_limits.py` |
| 1062 | PyMuPDF `linear=1` removed in 1.24+; the pikepdf-absent fallback save was dead code | `model/pdf_optimizer.py` (optimize-copy save pipeline) |
| 1070 | Foreign-PDF opens need the full resource-guard set, not just the primary open path | `model/pdf_model.py`, `model/headless_merge.py` |
| 1079 | Python negative indexing turns page 0 into a silent doc[-1] mutation | `model/tools/annotation_tool.py` (pattern applies to every `doc[page_num - 1]` site) |
| 1088 | min/max do NOT sanitize NaN — they are argument-order sensitive | `model/tools/watermark_tool.py` (pattern applies to any numeric clamp on untrusted input) |
| 1097 | IPC argv filters must resolve EVERY token — skipping relative paths is a bypass | `utils/single_instance.py` |
| 1106 | Byte-budget eviction must decrement _saved_stack_size or has_pending_changes drifts | `model/edit_commands.py` (`CommandManager._trim_undo_stack_if_needed`) |
| 1115 | Undo byte budget must floor at 1 command and use unique-byte accounting | `model/edit_commands.py` (`CommandManager._trim_undo_stack_if_needed`, `_unique_byte_total`) |
| 1124 | Adjacent-snapshot dedup is only safe for SnapshotCommand pairs | `model/edit_commands.py` (`CommandManager._dedup_top_snapshot_pair`) |
| 1133 | build_print_snapshot signature changed: () -> bytes became (dest: Path) -> None | `model/tools/manager.py`, `model/pdf_model.py`, `controller/pdf_controller.py` |
| 1142 | Uncapped portrait thumbnails can make page reordering impractical | `view/pdf_view.py` |
| 1153 | QListWidget InternalMove never reorders rows in IconMode with non-Static movement | `view/pdf_view.py` |
| 1164 | Instance-assigned Qt event handlers shadow class overrides | `view/pdf_view.py` responsive shell |
| 1175 | Thumbnail invalidation must distinguish count-changed from count-unchanged | `controller/pdf_controller.py` (`_invalidate_thumbnails`, `_schedule_thumbnail_batch`), `view/pdf_view.py` (`update_thumbnail_batch`) |
| 1184 | Cross-page text move must invalidate thumbnails | `controller/pdf_controller.py` (`move_text_across_pages`) |
| 1193 | Search worker must be cancelled (and waited for) before any document mutation | `controller/pdf_controller.py` (`_SearchWorker`, `_cancel_search`), `model/tools/search_tool.py` |
| 1202 | Search tab restore must persist completed results, not just the query | `controller/pdf_controller.py`, `view/pdf_view.py` |
| 1210 | Print path must not double-stamp watermark overlays | `model/tools/watermark_tool.py`, `controller/pdf_controller.py`, `src/printing/subprocess_runner.py` |
| 1218 | OCR workers must read from a snapshot, not the live doc | `controller/pdf_controller.py`, `model/tools/ocr_tool.py` |
| 1226 | Cooperative OCR cancellation: per-page only | controller/pdf_controller.py _OcrWorker |
| 1233 | render_page_pixmap must reject page_num=0 | `model/tools/manager.py` (`ToolManager.render_page_pixmap`) |
| 1241 | Wheel zoom must use effective (clamped) factor for the transform | `view/pdf_view.py` (`_wheel_event`) |
| 1249 | Object streams are natively supported by PyMuPDF | `model/pdf_optimizer.py` |
| 1257 | Deskew Can Increase File Size | `model/pdf_model.py` (`straighten_page`) |
| 1266 | Adaptive toolbar preset must use measured width, not window state | `view/pdf_view.py` — `_update_toolbar_style` |
| 1273 | Toolbar preset stale after fullscreen or theme change | `view/pdf_view.py` — `_update_toolbar_style`, `exit_fullscreen_ui`, `apply_theme` |
| 1280 | Qt QSS has no box-shadow or CSS transitions | `view/theme.py`, `view/pdf_view.py` |
| 1287 | QColor() cannot parse `rgba(r,g,b,a)` float-alpha strings | `view/theme.py` — `_parse_qcolor` |
| 1294 | Focus rings must be colour-only to avoid layout shift | `view/theme.py` — `build_qss` |
| 1301 | Print dialog: programmatic combo restore must run AFTER signal wiring or overrides silently lose | `src/printing/print_dialog.py` — `UnifiedPrintDialog.__init__` ordering vs `_resolve_hardware_values` (M3.2) |
| 1309 | unittest.mock.patch on PySide6 dialog methods → Windows fatal access violation | `test_scripts/` — any test constructing a real Qt widget with `patch.object(SomeQDialogSubclass, "method")` active (M3.2) |
| 1316 | Free-function extraction silently bypasses method monkeypatching | model/pdf_text_edit.py, model/pdf_object_ops.py (god-module decomposition seams) |
| 1323 | Helper-class extraction: getattr(self,…) and staticmethods escape the self.→self._view transform | view/object_selection.py (R3.6 view seam); applies to any PDFView→manager extraction |
| 1330 | Undo byte-budget must dedup by content, not id() | model/edit_commands.py — `CommandManager._unique_byte_total` / `_dedup_top_snapshot_pair` / `_trim_undo_stack_if_needed` |
| 1337 | OCR invisible text changes doc.tobytes() without bumping render_revision | controller/pdf_controller.py (`capture_worker_snapshot_bytes` cache) + controller/ocr_coordinator.py (`_on_ocr_page_done`) |
| 1344 | Thumbnail threading: render off snapshot bytes, never the live doc — and watermarks vanish | controller/thumbnail_coordinator.py (R4.3 hybrid async thumbnails) |
| 1351 | A test that builds a QPixmap needs the `qapp` fixture or it hangs | test_scripts (any Qt-touching test that constructs QPixmap/QImage→QPixmap off a fixture) |
| 1358 | Overlay raster caching: only watermarks are overlays, and the cache key must capture base content (R4.1 design-note) | model/tools/manager.py (`render_page_pixmap` overlay branch), model/tools/watermark_tool.py, controller `_render_revision`/`_render_cache` |
| 1365 | Optimize-copy of an encrypted PDF must re-apply the password, or it ships unprotected | model/pdf_optimizer.py (`save_optimized_copy` / `reapply_source_encryption`, R5.5) |
| 1372 | Print path wrote a fully decrypted PDF to disk; keep the temp encrypted + pass the password out-of-band | controller/print_coordinator.py + src/printing/subprocess_runner.py + src/printing/helper_main.py (R5.1) |
| 1379 | Building a wheel/sdist in `.venv`: setuptools is too old, and `pip wheel` litters build/ in the repo | packaging / test_scripts/test_security_packaging.py (R5.4) |
| 1386 | `Path.write_text` on Windows rewrites LF→CRLF — don't use it to "revert" a tracked file | tooling / any transient edit-then-restore of a source file on Windows |
| 1393 | Characterization tests are green-by-construction — they need *teeth*, not a red-light | testing / coverage-hardening (R6.1) |
| 1400 | `verify_no_jump.py` full-suite `--ignore` lines go stale — re-audit on every gate change | tooling / no-jump completion gate (R6.2) |
| 1409 | Object-ops (move/rotate/delete) bypassed GC → unbounded growth + deleted-data recovery | `model/pdf_object_ops.py` (R6-01; reopened R3.4) |
| 1418 | `delete_object` now replaces the live `fitz.Document` handle | `model/pdf_object_ops.py` `_purge_deleted_content`; callers/tests |
| 1427 | Delete confidentiality must fail closed, not swallow the GC error | `model/pdf_object_ops.py` `_purge_deleted_content` (Codex F4) |
| 1436 | Optimize-copy must bind to its source session, not live `model.doc` | `model/pdf_optimizer.py`, `controller/pdf_controller.py` (R5-03; Codex F1/F2) |
| 1445 | Re-encryption must preserve the auth role and never publish plaintext at the output | `model/pdf_optimizer.py` `reapply_source_encryption` / `save_optimized_copy` (R5-02, R5-04) |
| 1454 | PyMuPDF `Document.save()`/`tobytes()` default to `garbage=0` — orphans persist on disk | `model/pdf_model.py` save path; relevant to any redaction/delete |
| 1463 | Async thumbnail identity must include a global token, session, and generation | `controller/thumbnail_coordinator.py`, `controller/pdf_controller.py` (R4-01…R4-04; M3.6 foreground priority) |
| 1472 | Completed print runner retained its password until the view was destroyed (R5-05) | `src/printing/subprocess_runner.py` |
| 1481 | Packaging guard accepted a find-all `*` discovery pattern (R5-06) | `test_scripts/test_security_packaging.py` |
| 1490 | Windows pip-audit crashes on non-ASCII bytes in requirement files | CI (`dependency-audit` job) / requirement files |
| 1499 | Orphaned print-helper processes poison later full-suite runs | `test_scripts/` print stack / local dev machine state |
| 1508 | Subprocess text I/O silently depends on the caller's locale, not the child's | `test_scripts/` — any test that `subprocess.run(...)` a script/tool and reads its stdout/stderr |
| 1520 | CI's `test-functional` job never installed `build`/`setuptools`/`wheel` | `.github/workflows/ci.yml` (`test-functional` job) / `test_scripts/test_security_packaging.py` |
| 1530 | `apply_redactions` is geometric: it destroys text and line art, not just the targeted image | `model/pdf_object_ops.py` (object delete/move/rotate), any PyMuPDF redaction call |
| 1545 | Pruning an XObject resource: `/fzImg1` is a prefix of `/fzImg10`, and `/Resources` is inheritable | `model/pdf_object_ops.py` (`_remove_native_image_invocation`) |
| 1557 | A "fail safe" that refuses to act can strand the object it was protecting | `model/pdf_object_ops.py` (`_delete_object_impl` image branch), and any resolve-then-act path |
| 1569 | Rolling back a transaction that changed nothing closes the live `fitz.Document` | `model/pdf_object_ops.py` (`delete_objects_atomic`), `model/pdf_model.py` (`_restore_doc_from_snapshot`) |
| 1579 | The print path wrote two plaintext temps, and `capture_print_snapshot_bytes` is always decrypted | `controller/print_coordinator.py`, `src/printing/*` (R5-01) |
| 1591 | A QThread worker can clear its own decrypted payload race-free — no join needed | `controller/search_coordinator.py`, `controller/ocr_coordinator.py` (Codex F6 / B3) |
| 1603 | XObject identity requires both the resource binding and the placement | `model/pdf_object_ops.py` app-image resolution and resource pruning |
| 1613 | `QProcess.FailedToStart` has no matching `finished` signal | `src/printing/subprocess_runner.py` |
| 1623 | PDF font identity must be keyed per-xref, never per-basefont | font handling for the text-commit engine design (`plans/2026-07-14-acrobat-parity-text-commit-engine.md`); any code matching spans to fonts |
| 1633 | Render-quality benchmark must use the profile-scoped quality map | `test_scripts/benchmark_ui_open_render.py`, controller render state |
| 1643 | A quality flag is not observable until the render callback yields | `controller/pdf_controller.py`, `controller/page_render_coordinator.py`, complex-vector continuous rendering |
| 1653 | A growing thumbnail icon box does not upscale its source pixmap | thumbnail rendering and layout (`controller/thumbnail_coordinator.py`, `model/pdf_model.py`, `view/pdf_view.py`) |
| 1663 | Editable combo validation must distinguish draft text from committed values | `view/pdf_view.py`, `view/text_editing.py` — font-size control |
| 1673 | Printable-area centering is not physical-paper centering | `src/printing/qt_bridge.py` |
| 1683 | Document snapshots must restore blank-placeholder state too | `model/pdf_model.py`, `model/edit_commands.py` |
| 1693 | App-object payload versions are parser contracts, not feature counters | `model/tools/annotation_tool.py`, `model/pdf_object_ops.py` |
| 1704 | PyMuPDF annotations retain their page through the page wrapper | PyMuPDF annotation tests |
| 1714 | `tobytes(encryption=NONE)` on the *live* encrypted doc poisons its next `encryption=KEEP` save | `model/pdf_model.py` — `capture_worker_snapshot_bytes()` / `capture_print_snapshot_bytes()` (M3.5) |
| 1725 | A later unconditional panel sync silently undoes an earlier mode-specific one | `view/pdf_view.py` — `PDFView.set_mode()` / `_sync_text_property_panel_state()` (M3.5) |
| 1736 | Markup-mode mouse press fell through to Qt's default QGraphicsView handling | `view/pdf_view.py` — `_mouse_press()` / `_mouse_move()` / `_mouse_release()` for `highlight`/`underline`/`strikeout` modes (M3.5) |
| 1749 | Underline/strikeout merged into one `markup_line` mode; PyMuPDF has no width API for either | `view/pdf_view.py` — toolbar, `_setup_property_inspector()`, mode dispatch (M3.5 follow-up) |
| 1760 | PyMuPDF annot geometry is unrotated-space on BOTH write and read; `annot.rect` readback is a false oracle | `model/tools/annotation_tool.py` — every `page.add_*_annot` / `annot.set_rect` / `annot.rect` site |
| 1770 | Python 3.10 `Path.resolve(strict=False)` still raises on unreachable UNC paths (WinError 53) | `utils/preferences.py` — `canonicalize_recent_path`; any `resolve()` on user-supplied paths |
| 1779 | `itemActivated` + `EditKeyPressed`-only triggers hide a QTreeWidget's editability | `view/pdf_view.py` — bookmark panel (`self.bookmark_tree`) |
| 1787 | View-owned popup not scoped to a session silently mutates the wrong document | `view/pdf_view.py` (`_floating_note`) + `view/floating_note.py`; class of bug applies to any singleton view widget that outlives a session |
| 1795 | Full-rebuild `populate_toc` discards any selection set immediately before `sig_toc_changed` | `view/pdf_view.py` — bookmark panel (`self.bookmark_tree`), TOC round-trip |
| 1805 | PyMuPDF version skew masks runtime-only bugs | Environment / test toolchain (`requirements.txt`, `constraints-ci.txt`) |
| 1812 | A local pre-commit hook is not durable across clones/worktrees -- pair it with a CI gate | `scripts/hooks/` (device-identity guard) |
| 1821 | Normalized PDF token serialization cannot prove lossless text patching | text-commit design; `model/pdf_content_ops.py` |
| 1830 | `Tj`/`TJ` edits must preserve consumed text advance, not just surrounding operators | text-commit design; future `model/text_commit/replay.py` and `patch.py` |
| 1839 | PyMuPDF PDF generation is not byte-deterministic | `scripts/build_fidelity_corpus.py` (fidelity corpus generator) |
| 1846 | PyMuPDF `insert_text` vs TextWriter produce fundamentally different font structures | `scripts/build_fidelity_corpus.py`, `model/text_commit/font_registry.py` (future) |
| 1853 | PyMuPDF merges close `insert_text` calls into a single text block | `scripts/build_fidelity_corpus.py`, test fixtures |
| 1860 | PyMuPDF `Document.get_new_xref()` not `new_xref()` | `scripts/build_fidelity_corpus.py` (direct PDF object construction) |
| 1869 | `doc.tobytes()` of the SAME unchanged document differs between calls | `model/text_commit/engine.py`; any "no mutation" test assertion |
| 1878 | `fitz.Font(<unknown name>)` raises `FzErrorArgument`, not RuntimeError — and known names may silently alias | `model/text_commit/fonts.py` |
| 1887 | `Document.xref_copy` needs a dict-initialized target; `xref_set_key` cannot create keys through indirect paths | test fixtures / direct PDF object surgery |
| 1896 | MuPDF `insert_htmlbox` break-all does NOT split words that fit a line | legacy commit path characterization; `model/pdf_model.py:_build_insert_css` |
| 1905 | Block-manager runs are word-level: one show op maps to several member spans | `model/pdf_text_edit.py` (V2 engine target derivation); `model/text_block_parsing.py` |
| 1914 | Dropping the last Python reference to an unparented cross-thread QObject is an access violation | PySide6 threading; `controller/text_commit_coordinator.py` |
| 1923 | `insert_pdf` strips the SOURCE page's annotation `/P` key — even on whole-document copies | PyMuPDF; `model/pdf_model.py` undo snapshots |
| 1932 | `doc.tobytes()` with default encryption poisons a live encrypted document — even read-only | PyMuPDF AES-256; `model/text_commit/engine.py`, `model/text_commit/verify.py` |
| 1941 | `insert_pdf` renumbers xrefs — unusable for xref-identical scratch copies | PyMuPDF; `model/text_commit` scratch-first verification |
| 1948 | Pixel-uniformity occlusion checks need edge erosion | model/text_commit/verify.py (Tier-1 spike: verify_tier1_strategy / _region_is_uniform) |
| 1955 | A "graphics-state bleed" ink-tint check must not sample a covering shape's own fill color | model/text_commit/verify.py (Tier-1 spike: verify_tier1_strategy) |
| 1962 | PyMuPDF insert_font(fontbuffer=..., set_simple=True) dedupes byte-identical programs onto the same xref | model/text_commit fonts (font-honesty Tier-1 spike) |
| 1969 | OCG visibility only takes effect after a tobytes()+reopen round trip — and only on a *second* round trip after set_layer | model/text_commit/verify.py (`_ocg_membership_status`) |
| 1976 | Concatenating a block's spans is right; concatenating its lines deletes a word boundary | model/text_block_parsing.py (`_parse_block`) |
| 1983 | A wrong extracted string can hide as a *similarity* problem rather than a visible failure | model/pdf_text_edit.py (`SequenceMatcher` block/page reconciliation) |
| 1990 | Asserting that the replay *recorded* a text state does not test the gate that *rejects* it | model/text_commit planner gates (`plan.py`, `inspect.py`) + their tests |
| 1997 | Two gates sharing one RejectReason let a test survive deletion of its own gate | model/text_commit/plan.py (`FONT_FACE_UNAVAILABLE`, `UNSUPPORTED_TEXT_STATE`) |
| 2004 | For a simple PDF font, `/Widths` overrides the font program — measuring advance from a face is wrong | model/text_commit/fonts.py, plan.py (`_advance`) |
| 2011 | `/Widths` proves an advance, not a glyph — trusting it as glyph evidence commits tofu | model/text_commit/fonts.py (`FontCapability.missing_glyphs`) |
| 2018 | A staleness fingerprint must cover whatever the plan was *measured* against, not just what it edits | model/text_commit/inspect.py (`page_fingerprint`) |
| 2025 | A tolerance that equals the quantum of its own measurement source stops being a tolerance | model/text_commit/plan.py (`_ADVANCE_TOL_PER_PT`) |
| 2032 | Word runs are stripped, so `" ".join` cannot reconstruct source whitespace | model/pdf_text_edit.py (`_tier0_target_from_resolve`) → model/text_commit/inspect.py (`bind_source_text`) |
| 2039 | A redundant guard cannot be made mutation-SENSITIVE — check for subsumption before claiming a test pins it | model/pdf_text_edit.py (`_tier0_target_from_resolve`), test design |
| 2046 | `TARGET_IN_FORM_XOBJECT` must be target-scoped — page-scoped labeling mislabels almost every miss on real corpora | model/text_commit/inspect.py (`bind_source_text`) |
| 2053 | Calling `bind_source_text` per target re-replays the whole page — prohibitively slow for multi-target sampling | model/text_commit (measurement/tooling) |
| 2060 | `tobytes(encryption=KEEP)` reorders dictionary keys the first time it serializes a disk-loaded object — breaking the scratch-first fingerprint self-check | model/text_commit/engine.py (`prepare` → `_build_scratch_copy`) / inspect.py (`page_fingerprint`, `_update_font_dependencies`) |
| 2067 | Text-space and page-space quantities must not mix in bbox/halo math — under scale the error is a silent false ACCEPT | model/text_commit/plan.py (fallback `target_bbox`) |
| 2074 | PyMuPDF `insert_text` emits `[<...>] TJ` — an array, never a hex `Tj` | test fixtures for text-commit gates |
| 2081 | `pytest … | tail` reports tail's exit code — a hard interpreter abort can read as a passing run | test harness / CI hygiene |
| 2088 | `doc.xref_get_keys(xref)` returns `[]` for a non-dictionary object — indistinguishable from an empty dictionary | model/text_commit/inspect.py (`_canonical_object_digest`) |
| 2095 | A mutation fixture can be subsumed by a sibling guard — rotation does not pin `b==c==0`, a mirror does not pin `a>0` | test_scripts/test_text_commit_structural_gates.py (`_uniform_scale` gates) |
| 2104 | Same-line successor merges into the target's own rawdict span without an intervening Tf/Tm/T* | `model/text_commit` (rawdict-derived bboxes) / test fixtures |
| 2114 | plan -> patch -> verify -> plan runtime import cycle | `model/text_commit` |
| 2124 | mypy loses None-narrowing for a dataclass field re-accessed in a different function | `model/text_commit/plan.py` |
| 2134 | Widening V0c's non-target-span-origin comparison to verify_bbox would false-reject every honest growth commit | `model/text_commit/verify.py` |
| 2144 | Preview verification must capture pre-patch state and reuse the session scratch | `model/text_commit/preview.py`, `model/text_commit/verify.py` |
| 2166 | High-fidelity stale undo must refuse, not snapshot-restore | `model/edit_commands.py` (`EditTextCommand.undo`) |
| 2176 | PDFModel property setters must getattr-guard legacy slots — tests build models via `__new__` | `model/pdf_model.py` (session-fallback properties), `test_scripts/` |
| 2186 | A reference sample taken inside the region it is proving is self-referential — the load-bearing rule is ink visibility | `model/text_commit/verify.py` (`prove_growth_region_blank`) |
| 2196 | `sh` inside a Form XObject is invisible to every page-level ink reader — a mechanism blocklist only refuses the mechanisms it enumerates | `model/text_commit/verify.py` (growth occupancy gates) |
| 2206 | `get_text("dict"/"rawdict")` geometry is UNROTATED page space — comparing it against a visual-space bbox passes on every unrotated page and is wrong on every `/Rotate` page | `model/text_commit/verify.py` (V0c/V0d), `model/pdf_text_edit.py` (target derivation) |
| 2216 | A verified-candidate cache keyed on a content token still needs the policy gates re-run at commit time | `model/pdf_text_edit.py` (`_attempt_tiered_commit` cached-candidate branch), `controller/pdf_controller.py` |
| 2226 | A certificate that reads its evidence from the post-patch document proves nothing | `model/text_commit/verify.py` (V0e), `model/text_commit/preview.py` |
| 2236 | `TJ` kern advances are materialized as synthesized spaces in dict extraction — verbatim dict text is not the source string | `model/pdf_text_edit.py` (`_dict_line_for_runs`) |
| 2246 | `pytest test_scripts/` in one invocation hangs at PySide6 interpreter teardown — run the suite chunked | test harness (`.venv`, PySide6) |
| 2254 | `lex_content_stream` materialized the full token list — a dense page stream is an in-app OOM | `model/text_commit` (pdf_lexer, replay) |
| 2262 | A resource refusal routed through `malformed` gets re-labelled — refusals need their own channel | `model/text_commit` reason propagation (replay → inspect → plan) |
| 2270 | ctypes `GetProcessMemoryInfo` silently zeroes without HANDLE restype (64-bit truncation) | test harness (subprocess memory measurement) |
| 2278 | A GUI notice keyed only on outcome status fires under the shipped default too — gate on the fallback chain shape, not just the status enum | `controller/pdf_controller.py` (Task 12 P0-C degrade visibility) |
| 2286 | A per-command flag reset at only one entry point leaks into sibling commit paths | `controller/pdf_controller.py` (Task 12 P0-C degrade visibility) |
| 2294 | Redo re-running the full commit pipeline must NOT re-fire a one-shot GUI notice | `controller/pdf_controller.py` / `model/edit_commands.py` (Task 12 P0-C degrade visibility) |
| 2301 | An acceptance gate's style-override flag must be scoped to what the app can actually request | `test_scripts/semantic_fidelity_gate.py` (Task 12 P0-C semantic fidelity gate) |
| 2309 | A two-pass preflight-then-commit consent design can't see a commit-stage-only failure in time | `model/pdf_text_edit.py` (Task 12 P0-C phase 2 consent flow — design-time finding, not a shipped bug) |
| 2317 | A "was this command ever confirmed" flag must check what actually happened, not just that execute() succeeded | `model/edit_commands.py` (Task 12 P0-C phase 2 — adversarial verification finding, high severity) |
| 2325 | A "did the signal emit" outcome is not "did the edit commit" — the View's success toast must pull the real result | `view/pdf_view.py` / `controller/pdf_controller.py` (Task 12 P0-C phase 2 — post-review finding, promoted to a merge blocker) |
| 2333 | A "reset at entry" claim is only true if the reset actually runs before every early-return guard | `controller/pdf_controller.py` (Task 12 P0-C phase 2 toast fix — adversarial verification finding, high + medium) |
| 2341 | AutoCAD-produced Type0 fonts inline their descendant CIDFont in /DescendantFonts | `model/text_commit` (Type0/CID evidence readers), `scripts/audit_type0_census.py` (Task 12 P0-D census) |
| 2349 | Path-based xref_set_key cannot null a nested key — it plants a placeholder string | PyMuPDF xref surgery (`test_scripts/type0_fixture_builder.py`, Task 12 P0-D fixtures) |
| 2357 | subset_fonts strips the cmap — Unicode lookups cannot prove glyph presence in a subset | PyMuPDF font subsetting (`test_scripts/type0_fixture_builder.py`, Task 12 P0-D fixtures; future P0-D glyph-presence gate) |
| 2365 | _parse_tounicode silently fabricates mappings from array-destination bfranges | `model/text_commit/verify.py` (`_parse_tounicode`, used by `collect_cid_encoding_evidence` — live Task 10 code), `scripts/audit_type0_census.py` (Task 12 P0-D adversarial finding) |
| 2373 | PyMuPDF TextWriter embeds EVERYTHING as Type0 — Helvetica lands with a CIDFontType0 descendant | test fixtures (`test_scripts/test_text_commit_fonts.py`, `test_text_commit_font_widths.py`), `model/text_commit/fonts.py` (Task 12 P0-D) |
| 2381 | A "default text state" percentage is only as good as its condition list | Task 12 coverage evidence (`scripts/measure_type0_funnel.py` vs the 2026-08-12 campaign numbers) |
| 2389 | Canonical-fold gaps hide in HYBRID object forms, not the named ones | model/text_commit (Type0 fingerprint staleness closure) |
| 2396 | A dead optional hook that catches its own ImportError becomes a per-edit user-visible defect | `controller/pdf_controller.py` (`edit_text` displacement-reflow callback, removed Task 12 Step 7) |
| 2403 | Bare object keywords in content streams lex as OPERATOR tokens and silently clear accumulated operands | `model/text_commit/pdf_lexer.py` consumers (`replay.py` operand accumulation) |
| 2410 | PyMuPDF's OC state (get_ocgs, rendering) is a load-time snapshot — /OCProperties writes don't refresh it | `model/text_commit/marked_content.py` — OCG default-config visibility resolution (Task 13 P1 admission) |
| 2417 | PDF numbers have no exponent notation — %g-formatted matrix coefficients silently void the whole operator | `test_scripts/type0_fixture_builder.py` (`set_text_matrix`), any code writing numbers into content streams |
| 2424 | Single-process full-suite pytest runs hang or abort nondeterministically inside Qt GUI tests | test harness (whole-suite runs of `test_scripts/`), PySide6 offscreen platform |
| 2431 | get_drawings/get_image_rects report UNROTATED page space — occupancy gates silently miss obstacles on /Rotate pages | model/text_commit/verify.py (Tier 1 growth occupancy gates), PyMuPDF geometry conventions |
| 2438 | MuPDF re-serializes integer-valued reals as ints — raw kind:value folds break across a tobytes round trip | model/text_commit/inspect.py (page fingerprint), PyMuPDF object serialization |
| 2445 | tracemalloc-wrapped timing windows and iterated-build peaks corrupt benchmark numbers two different ways | measurement harnesses (`scripts/benchmark_*`), tracemalloc + timing interaction |
| 2452 | json.dumps backslash escaping makes Windows path-leak assertions silently inert | data-policy tests asserting "no paths in the serialized report" |
| 2459 | sys.getsizeof on a slotless dataclass misses the per-instance __dict__ that dominates its memory | memory accounting (`_deep_size`-style recursive sizeof), dataclass instances |
| 2466 | Simple-font capabilities are served stale within a registry generation | `model/text_commit/fonts.py` (`DocumentFontRegistry`), engine prepare path |
| 2473 | Provenance fields on compared dataclasses silently break equality pins | `model/text_commit/replay.py` (`PageReplay`), frozen-dataclass contracts generally |
| 2480 | fitz.Document.update_stream(compress=False) never restores the original storage encoding | `model/text_commit/patch.py` (`apply_patchset`, `AppliedPatch.revert`), PyMuPDF stream storage |
| 2487 | tracemalloc cannot see memory PyMuPDF stores in its own C heap | memory-bound tests/harnesses for anything touching `fitz.Document` internals |
| 2494 | PyMuPDF get_pixmap/get_text each build a private DisplayList/TextPage per call | `model/text_commit/verify.py` / `preview.py` render pipeline, any PyMuPDF perf work |
| 2501 | An object-level digest misses what get_fonts() has already resolved for the builder | `model/text_commit/fonts.py` (`compute_font_evidence_digest`), any staleness digest over font objects |
| 2508 | Per-lookup revalidation through a whole-page map is O(K·N) per prepare | `model/text_commit/fonts.py` (`DocumentFontRegistry.capability`), engine prepare / per-keystroke preview path |
| 2515 | Stored stream bytes are not the evidence a decoding builder consumed | `model/text_commit/cid_fonts.py` (`compute_cid_evidence_digest`), any cache digest over decoded streams |
| 2522 | Untyped ctypes windll call silently truncates GetCurrentProcess's pseudo-handle | Windows harness/instrumentation code using ctypes (`GetProcessMemoryInfo` etc.) |
| 2529 | PDFModel.__init__ flips PyMuPDF's process-global small_glyph_heights — every later test in a single-process suite sees fontsize-tall (0.8/-0.2 em) text bboxes | `model/pdf_model.py` + the text-commit Tier 1 growth proof (`model/text_commit/verify.py`) + any pytest run that shares one interpreter across files (CI's functional suite) |
| 2536 | Supplying a TextPage to get_text silently disables the caller's clip and flags | PyMuPDF text extraction, `model/text_commit/verify.py` |
| 2543 | PyMuPDF's DisplayList and TextPage convenience builders use different rotation conventions | PyMuPDF page interpretation, rotated pages |
| 2550 | Composing derotation onto a DisplayList is not raster-byte stable | PyMuPDF raster reuse, `/Rotate`, `/UserUnit`, and CropBox handling |
| 2557 | DisplayList.run is unusable through the PyMuPDF 1.27.1 Python wrapper for clipped stext reuse | PyMuPDF low-level devices |
| 2564 | MEDIABOX_CLIP is not invariant under a quarter-turn CTM | clipped stext extraction on rotated pages |
| 2571 | Rawdict Python object construction can dominate after interpretation reuse | dense-page text verification performance |
| 2578 | A PageInterpretation must not outlive the content-stream mutation window that created it | `PlanPreviewRenderer`, scratch apply/revert lifecycle |
| 2585 | A pre-state baseline cache key is a renderer-lifecycle guard, not a complete render-dependency proof | `PreStateBaselineCache` |
| 2592 | Process-global PyMuPDF rendering switches belong in every reusable baseline key | renderer caches, `fitz.TOOLS` |
| 2599 | Building a TextPage can make inherited rotation explicit | PyMuPDF inherited page attributes, document serialization |
| 2606 | The model's text-geometry surface was unrotated dict space while the View is displayed space — GUI text editing never worked on `/Rotate 90/270` pages | `model/pdf_model.py` (hit-test, selection, outline targets), `model/pdf_text_edit.py` (`edit_text`, `derive_tier0_preview_target`), `controller/pdf_controller.py` facade, `model/geometry.py` |
| 2613 | Untouched inline-edit sessions reported a font "override" and lost the Tier 0 plan | `view/text_editing.py` (`_sync_font_combo_state`, `build_style_overrides`), `model/text_commit/plan.py` (`STYLE_OVERRIDE_PRESENT`) |
| 2620 | Plan-preview rasters are displayed-space clips; a rotated editor proxy must counter-rotate them | `view/text_editing.py` (`_install_plan_preview_hook`, `PreviewBackedInlineTextEditor.apply_plan_preview`, `_capture_frozen_first_frame`) |
| 2627 | Legacy text insert clamped unrotated rects against the displayed `page.rect` | `model/pdf_text_edit.py` (`edit_text` → `_apply_redact_insert` / `_verify_rebuild_edit` / re-insert fallbacks) |
| 2633 | Diagnostic funnels must include page-level production refusals in eligibility | `scripts/measure_type0_funnel.py`, `model/text_commit/inspect.py` |
| 2640 | Same-face proofs must not succeed over an empty glyph witness set | `scripts/audit_same_face.py` |
| 2647 | CMap result caps do not bound repeated range-expansion work | `scripts/measure_type0_funnel.py` |
| 2654 | TTC face multiplicity does not imply distinct glyph programs | `scripts/audit_same_face.py` |
| 2661 | Composite closure includes empty embedded component glyphs | `scripts/audit_same_face.py` |
| 2668 | Shared glyph tables alone do not prove identical rendering programs | `scripts/audit_same_face.py` |
| 2675 | Shared-content diagnostics need a fail-closed inverse index | `scripts/measure_type0_funnel.py`, `model/text_commit/inspect.py` |
| 2682 | FontFile2 rewrites can remain invisible to the live MuPDF font cache | `scripts/probe_type0_mutation_premises.py`, future Type0 augmentation |
| 2689 | `xref_set_key` array paths are not descendant-dictionary mutation | `model/text_commit/cid_fonts.py`, future Type0 augmentation |
| 2696 | MuPDF readback normalization is wider than the PDF-value serializer contract | `model/text_commit/cid_fonts.py` |
| 2703 | Restore stream bytes before restoring the stream dictionary | `scripts/probe_type0_mutation_premises.py`, future multi-object revert |
| 2710 | Halo-wide source substrings are not target-local evidence | `model/text_commit/verify.py` (V0c) |
| 2717 | Target-local V0c proof requires plan-time duplicate-painter admission | `model/text_commit/plan.py`, `model/text_commit/verify.py` V0c |
| 2724 | V0c operator proof must never replay the full patched stream | `model/text_commit/verify.py`, preview verification |
| 2731 | Growth background-majority sampling must ignore glyph-height flags | `model/text_commit/plan.py`, `model/text_commit/verify.py` (Tier 1 growth proof) |
| 2738 | Horizontal scale is geometry, but cancels from raw TJ compensation | `model/text_commit/plan.py`, `model/text_commit/patch.py` |
| 2745 | Raw finite horizontal scale does not imply finite effective geometry | `model/text_commit/plan.py`, `model/text_commit/patch.py` |
| 2752 | A finite quotient is not proof of a correct quotient | `model/text_commit/patch.py` (`kern_for_displacement`) |
