# edit_text() Phase Helper Unit Tests

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-phase unit tests for the three extracted helpers of `PDFModel.edit_text()`, plus extract the inline target-mode resolution into its own testable method.

**Architecture:** The three helpers (`_resolve_edit_target`, `_apply_redact_insert`, `_verify_rebuild_edit`) already exist. We backfill unit tests using real PyMuPDF documents (no mocks). We also extract the ~40-line target-mode resolution block into `_resolve_effective_target_mode()` to make the orchestrator leaner and independently testable.

**Tech Stack:** pytest, PyMuPDF (fitz), PDFModel

---

## Context

The TODOS.md "Month 3" item calls for decomposing `edit_text()` into three helpers. **The structural extraction is already done** — the helpers exist at lines 2328, 2492, and 2732 of `model/pdf_model.py`. What's missing is per-phase unit tests and a small cleanup (extracting the inline target-mode resolution). This plan completes the TODO.

---

## Task 1: Extract `_resolve_effective_target_mode()`

**Files:**
- Modify: `model/pdf_model.py:2862` (insert new method before `edit_text`)
- Modify: `model/pdf_model.py:2905-2946` (replace inline logic with method call)

**Step 1: Add the new method** immediately before `edit_text()` (~line 2862):

```python
def _resolve_effective_target_mode(
    self,
    *,
    target_mode: str | None,
    target_span_id: str | None,
    new_rect: fitz.Rect | None,
    page_idx: int,
    rect: fitz.Rect,
    original_text: str | None,
) -> str:
    """Determine effective target mode from caller hints and heuristics."""
    if target_mode is None:
        if new_rect is not None and not target_span_id:
            effective = "paragraph"
        elif target_span_id:
            effective = "run"
        else:
            effective = "paragraph"
    else:
        effective = (target_mode or self.text_target_mode or "run").strip().lower()
    if effective not in {"run", "paragraph"}:
        effective = "run"
    if effective == "run" and not target_span_id:
        should_promote = True
        if original_text:
            probe_block = self.block_manager.find_by_rect(
                page_idx, rect, original_text=original_text, doc=self.doc
            )
            if probe_block and probe_block.text:
                norm_orig = self._normalize_text_for_compare(original_text)
                norm_block = self._normalize_text_for_compare(probe_block.text)
                if norm_block and len(norm_orig) < len(norm_block) * 0.6:
                    should_promote = False
                    logger.debug(
                        "keeping run mode: original_text (%d chars) < 60%% of block text (%d chars)",
                        len(norm_orig), len(norm_block),
                    )
        if should_promote:
            effective = "paragraph"
            logger.debug("auto-promoted target_mode run->paragraph (no explicit span_id)")
    return effective
```

**Step 2: Replace lines 2905-2946 in `edit_text()`** with:

```python
effective_target_mode = self._resolve_effective_target_mode(
    target_mode=target_mode,
    target_span_id=target_span_id,
    new_rect=new_rect,
    page_idx=page_idx,
    rect=rect,
    original_text=original_text,
)
```

**Step 3: Run existing tests to confirm no regression**

Run: `pytest test_scripts/test_edit_flow.py test_scripts/test_edit_geometry_stability.py test_scripts/test_drag_move.py -x -v`
Expected: All pass.

**Step 4: Commit**

```
feat: extract _resolve_effective_target_mode from edit_text
```

---

## Task 2: Create test file scaffold

**Files:**
- Create: `test_scripts/test_edit_text_helpers.py`

**Step 1: Write the scaffold:**

```python
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel
from model.edit_commands import EditTextResult


@pytest.fixture()
def model_with_pdf(tmp_path: Path):
    """Create a minimal PDF, open in PDFModel, yield model."""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    page.insert_text((72, 200), "Original text to edit", fontsize=12.0, fontname="helv")
    page.insert_text((72, 300), "Third block here", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    yield model
    if model.doc:
        model.doc.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None
```

**Step 2: Verify scaffold imports cleanly**

Run: `pytest test_scripts/test_edit_text_helpers.py --collect-only`
Expected: 0 tests collected, no import errors.

---

## Task 3: Tests for `_resolve_effective_target_mode()`

**Files:**
- Modify: `test_scripts/test_edit_text_helpers.py`

Add 6 tests (pure-logic, fast):

| Test | Scenario | Expected |
|---|---|---|
| `test_mode_default_no_args` | all None | `"paragraph"` |
| `test_mode_explicit_span_id` | `target_span_id="x"` | `"run"` |
| `test_mode_new_rect_promotes` | `new_rect=Rect(...)` | `"paragraph"` |
| `test_mode_explicit_paragraph` | `target_mode="paragraph"` | `"paragraph"` |
| `test_mode_run_auto_promotes` | `target_mode="run"`, no span_id, full block text | `"paragraph"` |
| `test_mode_run_no_promote_subsection` | `target_mode="run"`, no span_id, short original_text (< 60% of block) | `"run"` |

Run: `pytest test_scripts/test_edit_text_helpers.py -x -v`
Expected: All 6 pass.

**Step: Commit**

```
test: add _resolve_effective_target_mode unit tests
```

---

## Task 4: Tests for `_resolve_edit_target()`

**Files:**
- Modify: `test_scripts/test_edit_text_helpers.py`

Add 4 tests:

| Test | Scenario | Expected |
|---|---|---|
| `test_resolve_target_happy_path` | Block found by rect | `EditTextResult.SUCCESS`, result has `target_span` |
| `test_resolve_target_missing_block` | Rect far off-page `(9000,9000,9010,9010)` | `EditTextResult.TARGET_BLOCK_NOT_FOUND` |
| `test_resolve_target_no_change` | Same text/font/size/color | `EditTextResult.NO_CHANGE` |
| `test_resolve_target_by_span_id` | Pass explicit span_id from block_manager | `EditTextResult.SUCCESS`, matching span_id |

**Call pattern:**
```python
block = _find_block(model, 0, "Hello World")
page = model.doc[0]
status, result = model._resolve_edit_target(
    page_num=1, page_idx=0, page=page,
    rect=fitz.Rect(block.layout_rect),
    new_text="New text", font="helv", size=12.0, color=(0.0, 0.0, 0.0),
    original_text=block.text, new_rect=None,
    resolved_target_span_id=None, effective_target_mode="paragraph",
)
```

Run: `pytest test_scripts/test_edit_text_helpers.py -x -v -k resolve_target`
Expected: All 4 pass.

**Step: Commit**

```
test: add _resolve_edit_target unit tests
```

---

## Task 5: Tests for `_apply_redact_insert()`

**Files:**
- Modify: `test_scripts/test_edit_text_helpers.py`

Add 3 tests. Each requires calling `_resolve_edit_target` first to get a valid `_EditTextResolveResult`, then calling `_apply_redact_insert`.

| Test | Scenario | Expected |
|---|---|---|
| `test_apply_insert_basic` | Replace "Hello World" with "Goodbye" | Page text has "Goodbye", no "Hello World" |
| `test_apply_insert_empty_deletes` | Replace with `""` | "Hello World" gone from page |
| `test_apply_insert_preserves_others` | Replace one block | "Third block here" still on page |

**Pattern:**
```python
snapshot = model._capture_page_snapshot(0)
status, rr = model._resolve_edit_target(...)
new_rect = model._apply_redact_insert(
    page=page, page_num=1, page_idx=0, page_rect=page.rect,
    new_text="Goodbye", size=12.0, color=(0.0, 0.0, 0.0),
    vertical_shift_left=True, new_rect=None,
    snapshot_bytes=snapshot, resolve_result=rr,
)
assert isinstance(new_rect, fitz.Rect)
assert "Goodbye" in page.get_text("text")
```

Run: `pytest test_scripts/test_edit_text_helpers.py -x -v -k apply`
Expected: All 3 pass.

**Step: Commit**

```
test: add _apply_redact_insert unit tests
```

---

## Task 6: Tests for `_verify_rebuild_edit()`

**Files:**
- Modify: `test_scripts/test_edit_text_helpers.py`

Add 2 tests:

| Test | Scenario | Expected |
|---|---|---|
| `test_verify_rebuild_passes` | Full happy path (resolve + insert + verify) | No exception; block_manager updated |
| `test_verify_rebuild_rollback` | Call verify with text that's NOT on the page | `RuntimeError` matching `"verification failed"` |

**Rollback test strategy:** Call `_resolve_edit_target` but skip `_apply_redact_insert`. Then call `_verify_rebuild_edit` with `new_text="XYZZY_NONEXISTENT"` — the text isn't on the page, so verification fails and triggers rollback.

Run: `pytest test_scripts/test_edit_text_helpers.py -x -v -k verify`
Expected: Both pass.

**Step: Commit**

```
test: add _verify_rebuild_edit unit tests
```

---

## Task 7: Lint, full suite, docs update

**Step 1: Lint**

Run: `ruff check test_scripts/test_edit_text_helpers.py`
Fix any violations.

**Step 2: Full test suite**

Run: `pytest test_scripts/test_edit_text_helpers.py -v`
Expected: All 15 tests pass.

**Step 3: Update TODOS.md**

Move "Month 3 — PDFModel.edit_text() Phase Extraction" to Done section:

```markdown
## Done (2026-04-08) — PDFModel.edit_text() Phase Extraction

- What: Extracted `_resolve_effective_target_mode()` from `edit_text()`. Added 15 unit tests covering all three phase helpers (`_resolve_edit_target`, `_apply_redact_insert`, `_verify_rebuild_edit`) plus the new target-mode resolver.
- Why: Per-phase tests enable faster root-cause isolation; each helper is now independently testable.
- Outcome: `test_scripts/test_edit_text_helpers.py` covers happy paths, edge cases (missing block, no-change, empty text, rollback), and target-mode resolution heuristics.
```

**Step 4: Commit**

```
docs: mark edit_text phase extraction complete in TODOS.md
```

---

## Verification

1. `ruff check test_scripts/test_edit_text_helpers.py` -- zero violations
2. `pytest test_scripts/test_edit_text_helpers.py -v` -- all 15 tests pass
3. `pytest test_scripts/ -x` -- no regressions in existing tests
4. `ruff check model/pdf_model.py` -- no new violations from extraction
