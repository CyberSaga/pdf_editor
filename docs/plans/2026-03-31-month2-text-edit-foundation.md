# Month 2 Text Edit Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract the text-edit lifecycle from `PDFView`, introduce typed state/event objects, centralize touched constants, and begin internal decomposition of `PDFModel.edit_text()` without breaking existing behavior.

**Architecture:** Keep `PDFView` and `PDFController` public entrypoints stable while moving text-edit workflow logic into a dedicated manager module. Introduce typed request/state dataclasses and constants for the extracted path first, then refactor `PDFModel.edit_text()` behind the current public API into phase helpers.

**Tech Stack:** PySide6, PyMuPDF (`fitz`), `pytest`

---

### Task 1: Add foundation tests for typed edit payloads and manager extraction

**Files:**
- Create: `test_scripts/test_text_edit_manager_foundation.py`
- Modify: `test_scripts/test_text_editing_gui_regressions.py`

**Step 1: Write the failing tests**

Add coverage for:
- `PDFView` exposing `text_edit_manager`
- inline finalize emitting a typed `EditTextRequest` payload instead of an 11-value positional tuple

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_text_edit_manager_foundation.py -q`
Expected: FAIL because `view.text_edit_manager` does not exist yet and finalize still emits legacy positional args.

### Task 2: Extract `TextEditManager` and typed objects

**Files:**
- Create: `view/text_editing.py`
- Modify: `view/pdf_view.py`

**Step 1: Create the manager module**

Add:
- `TextEditRequest`
- `TextEditSession`
- `TextEditDragState`
- text-edit constants/config classes
- `InlineTextEditor`
- `_EditorShortcutForwarder`
- `TextEditManager`

**Step 2: Delegate from `PDFView`**

Move text-edit lifecycle methods to the manager and leave `PDFView` wrappers for compatibility.

### Task 3: Route controller through typed edit requests

**Files:**
- Modify: `controller/pdf_controller.py`
- Test: `test_scripts/test_text_edit_manager_foundation.py`

**Step 1: Accept either a typed request or the legacy argument list**

Keep the public controller API compatible while allowing `sig_edit_text` to emit a dataclass object.

### Task 4: Start internal `PDFModel.edit_text()` phase extraction

**Files:**
- Modify: `model/pdf_model.py`
- Test: existing focused model regression suites

**Step 1: Extract helper methods**

Introduce internal helpers for:
- target resolution
- redaction/insert execution
- verification/rebuild

**Step 2: Keep the public `edit_text()` signature stable**

The behavior should remain unchanged; only the internal shape gets simpler.

### Task 5: Verify the foundation slice

**Files:**
- Modify: `test_scripts/test_outputs/fixes_results_report_2026-03-31.md`

**Step 1: Run focused regressions**

Run:
- `pytest test_scripts/test_text_edit_manager_foundation.py -q`
- `pytest test_scripts/test_text_editing_gui_regressions.py -q`
- `pytest test_scripts/test_fullscreen_transitions.py -q`
- `pytest test_scripts/test_short_term_safety.py test_scripts/test_text_extraction_line_joining.py test_scripts/test_edit_geometry_stability.py test_scripts/test_week1_model_regressions.py -q`

**Step 2: Update the exported report**

Document the Month 2 foundation progress and any remaining follow-up for actions 13, 16, and 17.
