# Test Scripts Guide

This file provides a simple usage summary for every script under `test_scripts/`.
This document follows `docs/Methodology_for_Writing_Docs.md` as the single source of truth for how to run and interpret `test_scripts/`.

Run commands from repository root.

## Quick Start

- canonical full suite (Windows PowerShell):
```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH='.'; pytest -q
```
- canonical full suite (bash):
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q
```
- `pytest` style tests:
```bash
pytest -q test_scripts/<file>.py
```
- script style tests:
```bash
python test_scripts/<file>.py
```
- hybrid test (`pytest` wrapper + script CLI):
```bash
pytest -q test_scripts/test_1pdf_horizontal.py
python test_scripts/test_1pdf_horizontal.py --gui --save out.pdf
```

## Pytest Collection Policy

- Some files under `test_scripts/` are operational script runners, not unit-test modules.
- These files are intentionally marked with `__test__ = False` so `pytest` will not auto-collect them:
  - `test_scripts/test_all_pdfs.py`
  - `test_scripts/test_drag_move.py`
  - `test_scripts/test_sample_pdfs.py`
  - `test_scripts/test_deep.py`
- Run them directly with `python ...` as listed in the index below.

## Script Index

| Script | Type | Purpose | Usage |
|---|---|---|---|
| `benchmark_optimize_ab.py` | script | A/B benchmark optimize-copy between a baseline git revision and the current worktree | `python test_scripts/benchmark_optimize_ab.py --baseline-revision 2cd2a67 test_files/2024_ASHRAE_content.pdf` |
| `core_interaction_audit.py` | script | Thin harness for the core interaction UX audit; reuses existing pytest regressions, emits PASS/FAIL/BLOCKED, writes a sanitized markdown report, and generates a manual operator checklist for the blocked screen-operation scenarios | `python test_scripts/core_interaction_audit.py` or `python test_scripts/core_interaction_audit.py --report test_scripts/test_outputs/core_interaction_audit.md --manual-checklist test_scripts/test_outputs/core_interaction_manual_checklist.md` |
| `generate_large_pdf.py` | script | Generate large PDF for stress tests | `python test_scripts/generate_large_pdf.py --pages 1000 --output test_scripts/large_stress.pdf` |
| `live_acrobat_parity_run.py` | script | Focused live Acrobat-vs-editor parity runner for the current open files; captures per-task before/after screenshots, writes CSV/Markdown evidence, starts a desktop recording when `ffmpeg` is available, and honestly blocks non-comparable edit/persistence tasks | `python test_scripts/live_acrobat_parity_run.py` |
| `measure_startup_time.py` | script | Measure import/init time of `PDFModel` and run `test_font_fix.py` timing | `python test_scripts/measure_startup_time.py` |
| `test_1pdf_audit.py` | script | Audit `test_files/1.pdf` page/block geometry and index data | `python test_scripts/test_1pdf_audit.py` |
| `test_1pdf_horizontal.py` | pytest + script | Validate horizontal text edit result stays visible/in-page | `pytest -q test_scripts/test_1pdf_horizontal.py` or `python test_scripts/test_1pdf_horizontal.py --gui --save out.pdf` |
| `test_50_rounds.py` | script | 50-round preservation stress test (horizontal + vertical) | `python test_scripts/test_50_rounds.py` |
| `test_add_textbox_atomic.py` | pytest | Regression tests for add-text atomicity/rotation/font/immediate detectability | `pytest -q test_scripts/test_add_textbox_atomic.py` |
| `test_app_icon.py` | pytest | App icon asset loads as a non-null `QIcon` and propagates from the application to `PDFView` | `pytest -q test_scripts/test_app_icon.py` |
| `test_dialogs_package.py` | pytest | Every dialog class in `view/dialogs` is importable through the package's lazy `__getattr__` re-export | `pytest -q test_scripts/test_dialogs_package.py` |
| `test_startup_heavy_imports.py` | pytest | Startup import guard: subprocess probe asserts numpy/PIL/pikepdf/lxml are NOT loaded by importing `view.pdf_view` / `view.text_editing` (protects the lazy-import cold-boot win) | `pytest -q test_scripts/test_startup_heavy_imports.py` |
| `test_all_pdfs.py` | script | Batch test all PDFs under `test_files` (open/index/edit layers) | `python test_scripts/test_all_pdfs.py` |
| `test_char_run_reconstruction.py` | pytest | Regression tests for char-run reconstruction and paragraph/run behavior | `pytest -q test_scripts/test_char_run_reconstruction.py` |
| `test_core_interaction_audit.py` | pytest | Core UX audit: regressions for browse/edit/objects mode transitions and basic workflows | `pytest -q test_scripts/test_core_interaction_audit.py` |
| `test_deep.py` | script | Deep integration suite T1~T10 with report output | `python test_scripts/test_deep.py --quick --output deep_test_report.txt --only T1,T2` |
| `test_drag_move.py` | script | Drag-move and edit workflow validation across multiple scenarios | `python test_scripts/test_drag_move.py` |
| `test_empty_text_edit.py` | pytest | Regression tests for empty existing-text commit behavior (delete target textbox content) and command-path undo/redo | `pytest -q test_scripts/test_empty_text_edit.py` |
| `test_edit_flow.py` | script | End-to-end smoke test for basic edit flow | `python test_scripts/test_edit_flow.py` |
| `test_feature_conflict.py` | script | Cross-feature conflict workflow validation | `python test_scripts/test_feature_conflict.py` |
| `test_font_fix.py` | script | Font/HTML conversion behavior checks | `python test_scripts/test_font_fix.py` |
| `test_large_scale.py` | script | Large-scale stress run (random edits/undo/perf/scan) | `python test_scripts/test_large_scale.py --rounds 50 --pages 100 --seed 2026` |
| `test_main_startup_behavior.py` | pytest | Startup lifecycle regression for shell-first empty launch, deferred controller attachment/activation, and synchronous CLI open behavior | `pytest -q test_scripts/test_main_startup_behavior.py` |
| `test_image_objects_gui.py` | pytest | GUI regressions for image-object insert entry points (file and clipboard) and current-page default target behavior | `pytest -q test_scripts/test_image_objects_gui.py` |
| `test_image_objects_model.py` | pytest | App-owned image object persistence, move/rotate/delete behavior, and hit detection | `pytest -q test_scripts/test_image_objects_model.py` |
| `test_native_pdf_images_model.py` | pytest | Native PDF image XObject hit detection and stream-rewrite move/resize/rotate/delete behavior, including save/reopen coverage | `pytest -q test_scripts/test_native_pdf_images_model.py` |
| `test_no_jump_editor_geometry.py` | pytest | No-jump editor geometry + pixel-diff matrix: geometry match across render scales / DPI / font / rotation, paragraph-mode height, reopen stability, blanking detection, mutation stability, and negative controls; writes artifacts to `test_artifacts/no_jump/` | `pytest -q test_scripts/test_no_jump_editor_geometry.py` |
| `test_text_editing_fidelity_suite.py` | pytest | Text editing fidelity regression suite: font pt round-trip, wrap width, line-height honor, anchor drift, multi-script, rotation, and preview pixel-diff tests using real PyMuPDF documents | `pytest -q test_scripts/test_text_editing_fidelity_suite.py` |
| `test_completion_proof_hook.py` | pytest | 18-case test suite for the no-jump completion gate Stop hook: covers all bypass vectors including absent/corrupt/stale proof, self-consistent forged artifacts, and goal-file deletion | `pytest -q test_scripts/test_completion_proof_hook.py` |
| `test_snapshot_restore.py` | pytest | Snapshot restore correctness: page count preservation, idempotency, and xref-table validation | `pytest -q test_scripts/test_snapshot_restore.py` |
| `test_text_edit_finalize_outcome.py` | pytest | Regressions for text-edit finalize outcome enum and failed-emit reporting path | `pytest -q test_scripts/test_text_edit_finalize_outcome.py` |
| `test_resolve_target_mode.py` | pytest | Target-mode resolution regressions: `run`-without-span-id promotes to paragraph, `run`-with-span-id stays in run scope | `pytest -q test_scripts/test_resolve_target_mode.py` |
| `test_ux_signoff_agent.py` | pytest | UX signoff agent unit tests: fail-closed without credentials, PDF-run isolation and continuation after failure | `pytest -q test_scripts/test_ux_signoff_agent.py` |
| `test_text_editor_theme_padding.py` | pytest | QSS theme padding cascade fix regression + safe_render_scale clamp for pathological page rects (40 MP pixmap budget) | `pytest -q test_scripts/test_text_editor_theme_padding.py` |
| `test_phase7_guard_hygiene.py` | pytest | Audit remediation Phase 7 guards: render_page_pixmap bounds check, wheel zoom overshoot prevention, IPC dash-token rejection, native PyMuPDF object-streams support | `pytest -q test_scripts/test_phase7_guard_hygiene.py` |
| `test_text_selection.py` | pytest | AC-1: character-level browse-mode text selection — same-run, cross-run, multi-line clipping; copied text matches highlight | `pytest -q test_scripts/test_text_selection.py` |
| `test_print_layout.py` | pytest | AC-2/AC-3: print auto-orientation and paper-size matching; orientation override; paper combo coverage | `pytest -q test_scripts/test_print_layout.py` |
| `test_print_speed.py` | pytest | AC-9: 10-page A4 @300 DPI spooled within 20s; progress visible; no UI freeze | `pytest -q test_scripts/test_print_speed.py` |
| `test_object_free_rotation.py` | pytest | AC-4: free drag rotation (real-time angle, selection box/handles rotate, move preserves rotation) | `pytest -q test_scripts/test_object_free_rotation.py` |
| `test_object_free_rotation_gui.py` | pytest | AC-4 GUI: rotate handle drag behaviour, angle accumulation, undo entry | `pytest -q test_scripts/test_object_free_rotation_gui.py` |
| `test_object_resize.py` | pytest | AC-5: resize handles (free-form + Shift-lock aspect ratio), newly inserted/native images default to free-form | `pytest -q test_scripts/test_object_resize.py` |
| `test_native_image_discovery.py` | pytest | AC-6: native PDF image selectability including Form XObjects; move/rotate/delete; regression on 01_報告書.pdf | `pytest -q test_scripts/test_native_image_discovery.py` |
| `test_macos_menu.py` | pytest | AC-7: macOS native menu bar structure/shortcuts and platform guards (Windows/Linux no-op) | `pytest -q test_scripts/test_macos_menu.py` |
| `test_pdf_compliance.py` | pytest | AC-8: PDF conformance validation (xref, page tree, object refs, encryption); XREF repair safeguard | `pytest -q test_scripts/test_pdf_compliance.py` |
| `test_multi_tab_plan.py` | pytest | Multi-tab/session isolation and shortcut/UI behavior tests; includes thumbnail layout/spacing/auto-follow + landscape cell-gap regressions (`test_06a`~`test_06e`), and AC-7 font-size menu integration | `pytest -q test_scripts/test_multi_tab_plan.py` or `pytest -q test_scripts/test_multi_tab_plan.py -k "test_06a or test_06b or test_06c or test_06d or test_06e"` |
| `test_object_controller_flow.py` | pytest | Controller wiring for app-owned object move/rotate/delete/resize/add-image request handling and snapshot recording | `pytest -q test_scripts/test_object_controller_flow.py` |
| `test_object_manipulation_gui.py` | pytest | GUI regressions for objects mode, delete/rotate shortcuts, context menus, and mixed object-selection drag thresholds | `pytest -q test_scripts/test_object_manipulation_gui.py` |
| `test_object_manipulation_model.py` | pytest | Model regressions for app-owned textbox/rect/image object identity, hit detection, move/rotate/delete, and persistence | `pytest -q test_scripts/test_object_manipulation_model.py` |
| `test_object_multi_select.py` | pytest | Same-page multi-select regression coverage for supported object types | `pytest -q test_scripts/test_object_multi_select.py` |
| `test_object_requests.py` | pytest | Typed request dataclasses for object manipulation, batch requests, resize, and app-inserted images | `pytest -q test_scripts/test_object_requests.py` |
| `test_object_resize.py` | pytest | Resize-handle regressions for supported object types, including textbox resize behavior | `pytest -q test_scripts/test_object_resize.py` |
| `test_open_large_pdf.py` | script | Open-large-PDF stress benchmark (optionally generate input PDF) | `python test_scripts/test_open_large_pdf.py --pages 1000 --first-page` |
| `test_overlap_corpus_recursive.py` | script | Recursive overlap-safe edit validation for full corpus; writes CSV/MD reports | `python test_scripts/test_overlap_corpus_recursive.py` |
| `test_overlap_textbox_edit.py` | pytest | Targeted overlap textbox edit regressions | `pytest -q test_scripts/test_overlap_textbox_edit.py` |
| `test_pdf_merge_workflow.py` | pytest | Merge-PDF workflow regressions (merge dialog list behavior, validation, merge outputs, and ordering preservation) | `pytest -q test_scripts/test_pdf_merge_workflow.py` |
| `test_performance.py` | script | Repeated-edit performance benchmark | `python test_scripts/test_performance.py --rounds 20` |
| `test_interaction_modes.py` | pytest | Interaction-mode gating regressions for browse, objects, and text-edit modes | `pytest -q test_scripts/test_interaction_modes.py` |
| `test_printing_pipeline.py` | script | Printing pipeline validation (accuracy + memory/perf) | `python test_scripts/test_printing_pipeline.py` |
| `test_qt_bridge_layout.py` | pytest | Qt print bridge regressions: per-page layout receives each page's own rect; page size/orientation applied via the dedicated `setPageSize()`/`setPageOrientation()` setters (GDI ignores `setPageLayout` for size); `override_fields` gating of hardware setters; plus pure layout helpers | `pytest -q test_scripts/test_qt_bridge_layout.py` |
| `test_print_dialog_properties_button.py` | pytest | Print dialog UI regression for native printer properties button (`屬性`), settings sync-back, and collapsed read-only inherited-properties panel behavior | `pytest -q test_scripts/test_print_dialog_properties_button.py` |
| `test_linux_driver_overrides.py` | pytest | Linux/macOS print-driver regression: untouched duplex/color must inherit native defaults, while touched hardware fields emit explicit CUPS/`lp` overrides | `pytest -q test_scripts/test_linux_driver_overrides.py` |
| `test_structural_indexing.py` | pytest | Structural page ops indexing regressions: insert/delete should not force full rebuild; affected_pages metadata must match model-validated results | `pytest -q test_scripts/test_structural_indexing.py` |
| `test_win_driver_properties.py` | pytest | Windows driver regression: opening `屬性` must NOT persist a per-user default (`SetPrinter` level 9) — settings are job-scoped; still prefers per-user defaults when syncing preferences for display, ignores canceled dialogs, returns tray/preferences, and omits `devmode_buffer` on the pywin32 fallback path | `pytest -q test_scripts/test_win_driver_properties.py` |
| `test_win_print_fixes.py` | pytest | Windows print fixes P1–P4 against the real driver/dialog paths: job-scoped DEVMODE (no level-9 persistence, base64 carry, scoped apply/restore), per-page size/orientation split + multi-copy ordering, 150-DPI spooler cap, PDF-output preservation, and the `setPageSize` page-size regression (incl. a live-printer check, skipped if none) | `pytest -q test_scripts/test_win_print_fixes.py` |
| `test_print_dialog_logic.py` | script | Print dialog logic checks for layout/range/options normalization | `python test_scripts/test_print_dialog_logic.py` |
| `test_sample_pdfs.py` | script | Quick smoke test on `1.pdf`, `2.pdf`, `when I was young I.pdf` | `python test_scripts/test_sample_pdfs.py` |
| `test_unified_undo.py` | script | Unified undo stack scenario validation (delete/edit/undo/redo) | `python test_scripts/test_unified_undo.py` |
| `validate_optimized_pdf.py` | script | Multi-parser integrity validation for an optimized PDF (fitz + pikepdf + pypdf) | `python test_scripts/validate_optimized_pdf.py test_files/2024_ASHRAE_content.pdf` |

## Pytest markers

`pyproject.toml` (`[tool.pytest.ini_options]`) registers a fixed marker scheme with `addopts = "--strict-markers"`, so a typo'd or unregistered marker is a collection error, not a silent no-op.

| Marker | Meaning |
|---|---|
| `local_only` | Needs real local hardware (physical printer/screen); never selected in CI |
| `windows_only` | Requires Windows-specific APIs or drivers; skipped/deselected on other OSes |
| `needs_fixtures` | Depends on gitignored `test_files/` fixture PDFs; self-skips when absent |
| `ocr_heavy` | Exercises the heavy OCR stack (surya/torch); excluded from standard runs |

CI (and anyone reproducing the CI selection locally) excludes hardware-bound and fixture-dependent tests with:
```bash
pytest -m "not local_only and not needs_fixtures"
```

Currently `test_win_print_fixes.py::test_set_page_layout_applies_size_on_real_printer` carries `local_only`; `test_core_interaction_audit.py` and `test_no_jump_editor_geometry.py` carry `needs_fixtures` (gitignored `test_files/` fixtures are absent on CI runners, so those tests self-skip locally when fixtures are present but are deselected outright on CI). `windows_only` and `ocr_heavy` are registered for later triage passes and are not yet applied to any test.

## Continuous Integration

`.github/workflows/ci.yml` is the source of truth; this section summarizes what it runs and how to reproduce a given leg locally. See the workflow's own header comment for the full gate list (ruff, mypy, 4 import-linter contracts + threading grep, the security regression suite).

- **`test-functional` (windows-latest — BLOCKING):** runs the full marker-filtered suite with coverage instrumentation:
  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  .venv\Scripts\python.exe -m pytest -q -m "not local_only and not needs_fixtures" --cov --cov-report=term --cov-report=xml
  ```
  This leg is blocking on both test outcomes and coverage: `pyproject.toml`'s `[tool.coverage.report] fail_under = 75` gates the run (as of PR-12 — no CI-side override). Evidence basis: three consecutive PR-11 CI runs measured a stable TOTAL coverage of 78% on this leg (local `.venv` measures 79%), so 75% carries three points of real headroom.
- **`test-functional` (ubuntu-latest — advisory):** same marker selection, no coverage flags; `continue-on-error: true` pending the Qt offscreen-teardown SIGBUS tracked in issue #19. Failures here are surfaced in the check run but do not block merge.
- **Reproducing the CI selection locally:** the `-m "not local_only and not needs_fixtures"` filter is what differs from a plain local run — locally you normally want `needs_fixtures` tests included (they self-skip only when `test_files/` is absent), so only pass the filter when you specifically want CI-equivalent scope:
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -m "not local_only and not needs_fixtures"
  ```
- **Full local run (recommended for real verification):** omit the marker filter entirely and let `needs_fixtures` tests run against the real `test_files/` corpus — see Quick Start above.

## Output Notes

- Several script runners generate artifacts under `test_scripts/test_outputs/` (for example reports or exported PDFs).
- Keep this directory for debugging evidence; clean it manually when needed.

## Recommended Sets

### Core regressions (fast)
```bash
pytest -q test_scripts/test_add_textbox_atomic.py test_scripts/test_overlap_textbox_edit.py test_scripts/test_char_run_reconstruction.py test_scripts/test_empty_text_edit.py test_scripts/test_main_startup_behavior.py test_scripts/test_pdf_merge_workflow.py test_scripts/test_resolve_target_mode.py test_scripts/test_snapshot_restore.py test_scripts/test_text_edit_finalize_outcome.py
python test_scripts/test_edit_flow.py
```

### Merge-PDF workflow focus (fast, headless)
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q test_scripts/test_pdf_merge_workflow.py
```

Notes for `test_pdf_merge_workflow.py`:
- Validates merge list ordering is stable across operations.
  - `test_merge_dialog_preserves_reordered_list_when_adding_files`: reorder then add must not revert.
  - `test_merge_dialog_preserves_reordered_list_when_removing_files`: reorder then delete must not revert.
- Validates the core output contracts:
  - save-as-new opens merged result as a new tab.
  - merge-into-current replaces the active document and marks it dirty.

### Thumbnail layout regressions (fast, headless)
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q test_scripts/test_multi_tab_plan.py -k "test_06a or test_06b or test_06c or test_06d or test_06e"
```

### Object-mode regressions (fast, headless)
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q test_scripts/test_interaction_modes.py test_scripts/test_object_requests.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_controller_flow.py test_scripts/test_object_multi_select.py test_scripts/test_object_resize.py test_scripts/test_image_objects_model.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q test_scripts/test_object_manipulation_gui.py test_scripts/test_image_objects_gui.py test_scripts/test_native_pdf_images_model.py
```

Notes:
- Resize-handle anchoring and emitted `ResizeObjectRequest` behavior is covered by `test_scripts/test_object_resize.py`.
- Multi-select move behavior and immediate selection-overlay rebasing after move is covered by `test_scripts/test_object_multi_select.py` and `test_scripts/test_object_manipulation_gui.py`.
- The real production drag-release path for single-object moves in `objects` mode (the `_object_drag_preview_rects` multi-branch) is explicitly locked in by `test_scripts/test_object_manipulation_gui.py::test_objects_mode_move_release_rebases_when_preview_rects_populated`.
- Image object persistence/move/rotate/delete behavior is covered by `test_scripts/test_image_objects_model.py` and `test_scripts/test_native_pdf_images_model.py`.

### Text editing fidelity and no-jump regressions (headless)
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q test_scripts/test_text_editing_fidelity_suite.py test_scripts/test_no_jump_editor_geometry.py test_scripts/test_text_editing_gui_regressions.py test_scripts/test_edit_text_helpers.py
```

Notes:
- `test_no_jump_editor_geometry.py` writes artifacts to `test_artifacts/no_jump/`; run via the full gate (`python scripts/completion_gate.py`) for tamper-evident proof.
- `test_text_editing_fidelity_suite.py` includes real-PDF tests that require fixture PDFs under `test_files/`; these are skipped automatically when fixtures are absent.
- Geometry tests exercise DPI-corrected font sizing, frozen first-frame, paragraph-mode height, and rotated-proxy invariants.

### Audit remediation phases (headless)
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest -q test_scripts/test_search_worker_flow.py test_scripts/test_print_snapshot_path.py test_scripts/test_ocr_controller_flow.py test_scripts/test_thumbnail_async.py test_scripts/test_undo_memory_budget.py test_scripts/test_text_editor_theme_padding.py test_scripts/test_phase7_guard_hygiene.py
```

Notes:
- Phases 1–3: Snapshot isolation for background workers (search, print, OCR); gen-tokened signals drop late arrivals.
- Phase 4: Thumbnail invalidation skip count-unchanged operations; dedicated `_thumb_gen_by_session` counter.
- Phase 5: Undo byte budget floor (1 command survives oversized); dedup'd bytes counted once via `id()`.
- Phase 6: QSS theme padding cascade fix; safe_render_scale clamp for preview pixmaps.
- Phase 7: Render page bounds validation; wheel zoom effective factor (no overshoot); IPC dash-token rejection; native objstms on both PyMuPDF versions.

### Corpus and integration
```bash
python test_scripts/test_all_pdfs.py
python test_scripts/test_overlap_corpus_recursive.py
python test_scripts/test_deep.py --quick
```

### Performance/stress
```bash
python test_scripts/test_open_large_pdf.py --pages 1000 --first-page
python test_scripts/test_large_scale.py --rounds 50 --pages 100
python test_scripts/test_performance.py --rounds 50
```
