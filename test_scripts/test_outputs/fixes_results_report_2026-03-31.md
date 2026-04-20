# Fixes Results Report

**Date:** 2026-03-31  
**Target PDF:** `test_files\TIA-942-B-2017 Rev Full.pdf`  
**Scope:** cleanup after recovery, Week 2-3 safety/stability verification, and GUI workflow smoke checks.

## 1. Cleanup Completed

- Repaired `model/pdf_model.py` rollback handling in `edit_text()`:
  - removed silent rollback swallow (`except: pass`)
  - added rollback failure logging
  - added compound error raise when both edit and rollback fail
- Re-applied lost Week 1 logic after recovery:
  - smart fallback line joining for point-hit extraction (`get_text_info_at_point`)
  - no-op guard for unchanged text/style edits (skip re-estimation)
  - pre-push gate based on meaningful height growth
- Stabilized inline keyboard workflow:
  - `InlineTextEditor` now treats `End` as document-end for single-paragraph inline edits (prevents mid-string insertion when wrapped visually)

## 2. GUI Entry Workflow Check

The literal command `python main.py "test_files\TIA-942-B-2017 Rev Full.pdf"` was executed and stayed running until timeout (expected, because Qt event loop is interactive).

To validate behavior in automation, the same startup path was exercised via:

```python
from main import run
ctx = run([r"test_files\TIA-942-B-2017 Rev Full.pdf"], start_event_loop=False)
```

Observed workflow outputs:

```text
startup_ok=True pages=402
fullscreen_initial=False
fullscreen_after_enter=True
escape_handled=True
fullscreen_after_escape=False
fit_fullscreen_gap_px=12
```

## 3. Verification Results

### Core safety + P0 regression suite

```powershell
python -m pytest test_scripts/test_short_term_safety.py test_scripts/test_fullscreen_transitions.py test_scripts/test_text_extraction_line_joining.py test_scripts/test_edit_geometry_stability.py test_scripts/test_week1_model_regressions.py test_scripts/test_text_editing_gui_regressions.py test_scripts/test_text_edit_manager_foundation.py test_scripts/test_main_startup_behavior.py -q
```

Result:

```text
59 passed, 5 warnings in 11.94s
```

### Additional GUI keyboard/mouse workflow slice

```powershell
python -m pytest test_scripts/test_multi_tab_plan.py -q -k "fullscreen or inline_existing_text or escape_with_editor"
```

Result:

```text
18 passed, 49 deselected, 5 warnings in 24.80s
```

## 4. Issue Status (1-11)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Global ESC shortcut + always-visible exit button | PASS | `test_fullscreen_transitions.py`, startup smoke |
| 2 | Smart line-joining in extraction paths | PASS | `test_text_extraction_line_joining.py` |
| 3 | Skip re-estimation for no-change edits; anchor stability | PASS | `test_edit_geometry_stability.py`, `test_week1_model_regressions.py` |
| 4 | Gate push-down cascade on meaningful height increase | PASS | `test_week1_model_regressions.py` |
| 5 | 12px spacing between fit/fullscreen buttons | PASS | startup smoke (`fit_fullscreen_gap_px=12`), `test_fullscreen_transitions.py` |
| 6 | Add "Exit Fullscreen" to context menu | PASS | `test_fullscreen_transitions.py` |
| 7 | Memory leak fix via `QTextEdit` subclass | PASS | `test_short_term_safety.py` |
| 8 | Undo safety (peek before pop) | PASS | `test_short_term_safety.py` |
| 9 | Undo stack max=100 with eviction | PASS | `test_short_term_safety.py` |
| 10 | Log rollback failures (no silent pass) | PASS | `test_short_term_safety.py` |
| 11 | Regression tests for 3 P0 bugs | PASS | dedicated regression test files + 59-test sweep |

## 5. Safe User-Facing Polish (Post Week 1-3 / Month 2 Cleanup)

### Implemented

- Text property panel now reflects real state:
  - Apply/Cancel are disabled when no inline editor is open
  - browse-mode text selection can surface the text settings card with detected font/size
  - live inline editors re-enable Apply/Cancel through a single shared sync path
- Browse-mode context menu now exposes safer editor affordances:
  - `Copy Selected Text`
  - `Select All`
  - `Edit Text` when right-click hits editable text
  - `Zoom In`
  - `Zoom Out`
  - `Fit to View`
  - existing `Exit Fullscreen` / `Rotate Pages` entries remain available where applicable
- Editor lifecycle cleanup:
  - `TextEditManager` now notifies the view to resync property-panel state on editor open/close
  - initialization/startup ordering issues were fixed so the sync helper is safe during real `PDFView()` construction
- Snapshot restore is now atomic-safe-first:
  - replacement page is inserted before the original page is deleted
  - if deleting the original page fails, cleanup attempts to remove the inserted replacement page
  - new regression coverage ensures restore never deletes the live page after an insert failure

### Verification

Targeted polish regression file:

```powershell
python -m pytest test_scripts/test_text_editing_gui_regressions.py -q
```

Result:

```text
24 passed, 5 warnings in 0.44s
```

Broader GUI/startup verification:

```powershell
python -m pytest test_scripts/test_fullscreen_transitions.py test_scripts/test_main_startup_behavior.py test_scripts/test_text_edit_manager_foundation.py test_scripts/test_text_editing_gui_regressions.py -q
```

Result:

```text
51 passed, 5 warnings in 14.79s
```

Atomic restore safety regression:

```powershell
python -m pytest test_scripts/test_short_term_safety.py -q
```

Result:

```text
6 passed, 5 warnings in 0.50s
```

Real startup smoke using the production entry path with the target PDF:

```python
from main import run
startup = run([r"test_files\TIA-942-B-2017 Rev Full.pdf"], start_event_loop=False)
view = startup["view"]
```

Observed:

```text
startup_ok=True pages=402 mode=browse
text_panel_buttons=False/False
```
