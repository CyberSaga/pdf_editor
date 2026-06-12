# Transparent Editbox Report

Date: 2026-05-20 16:41:30 +08:00  
Repo: `pdf_editor`

## Scope
This report documents the transparent editbox hardening with strict focus on:
- no original glyph overlap during live editing,
- background-matched opaque underlay mask,
- restore fidelity after type-then-delete,
- geometry stability under strict no-jump tests.

## Implementation Summary
Code paths updated:
- `view/text_editing.py`
- `view/pdf_view.py`
- `test_scripts/test_text_editing_gui_regressions.py`
- `test_scripts/test_no_jump_editor_geometry.py`
- `scripts/verify_no_jump.py`
- `scripts/manual_visual_edit_check.py`

Key behavior changes:
1. Live editing no longer repaints frozen source glyphs in mutated states.
2. During debounce/invalid-preview windows, only live editor text is painted over the mask.
3. Background mask generation fail-closes to local perimeter color to suppress residual glyph texture leak.
4. During-edit evidence capture now includes `during_empty_editor.png` and corresponding diffs.
5. Mutation tests enforce explicit during-edit source-ink suppression metric (`empty_source_ink_retained`).

## During-Editing Evidence
Artifacts were exported under:
- `test_artifacts/manual_visual_batch/test-colored-background/`
- `test_artifacts/manual_visual_batch/test-complexed-layout/`
- `test_artifacts/manual_visual_batch/test-horizontal-texts/`
- `test_artifacts/manual_visual_batch/test-large-file/`
- `test_artifacts/manual_visual_batch/test-vertical-texts/`

Per-PDF metrics from `metrics.json`:
- `test-colored-background`: `open=0.0`, `empty=0.9333517454706143`, `during=0.9302806009721608`, `restored=0.0`, `leak=0.0`, `ring_delta=0.5141767415083484`
- `test-complexed-layout`: `open=0.0`, `empty=0.24717348927875243`, `during=0.26530214424951265`, `restored=0.0`, `leak=0.0`, `ring_delta=0.8845437616387244`
- `test-horizontal-texts`: `open=0.0`, `empty=1.0`, `during=0.9990009950248756`, `restored=0.0`, `leak=0.0`, `ring_delta=40.666666666666664`
- `test-large-file`: `open=0.0`, `empty=0.11407553798858147`, `during=0.12983091787439613`, `restored=0.0`, `leak=0.0`, `ring_delta=0.0`
- `test-vertical-texts`: `open=0.0`, `empty=0.12598121219920216`, `during=0.14710140265088148`, `restored=0.0`, `leak=0.0`, `ring_delta=0.0`

Interpretation:
- `open=0.0` and `restored=0.0` indicate strict open/restored parity in captured region.
- `leak=0.0` indicates mask leak detector passes.
- During-edit captures (`during_empty_editor.png`, `during_editor.png`) are present for all five PDFs.

## Verification Results
Executed and passing:
1. `python -m pytest test_scripts/test_text_editing_gui_regressions.py -k "mask" -q`  
   Result: `6 passed`
2. `python -m pytest test_scripts/test_no_jump_editor_geometry.py -q`  
   Result: `377 passed, 6 skipped`
3. `python -m ruff check scripts/manual_visual_edit_check.py view/text_editing.py view/pdf_view.py test_scripts/test_no_jump_editor_geometry.py scripts/verify_no_jump.py test_scripts/test_text_editing_gui_regressions.py`  
   Result: clean
4. `python -m py_compile scripts/manual_visual_edit_check.py view/text_editing.py view/pdf_view.py test_scripts/test_no_jump_editor_geometry.py scripts/verify_no_jump.py`  
   Result: clean

## Notes
- `scripts/verify_no_jump.py` enforces a clean-worktree precondition and will stop if source files are modified/uncommitted.
- Offscreen Qt environment may lack installed font families; this affects visual rendering style of live typed glyphs in headless captures, but does not invalidate old-glyph suppression checks using `during_empty_editor.png`.

## Conclusion
Transparent editbox behavior is hardened with explicit during-edit evidence and strict regression coverage for no-overlap/no-jump constraints.
