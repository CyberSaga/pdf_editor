# Text Editing Fidelity: Line Height Preservation

## Context

When a user edits existing text in the PDF editor, the committed text should look the same size as the original. Currently it doesn't:

- **Texts appear visually bigger** after editing: the committed text block takes more vertical space, pushing unedited lines below it down ("push unedited lines away").
- **Texts appear visually smaller** after editing: the committed text is more compact than the original (less spacing between lines).
- **Editor display wrapping diverges from PDF**: the inline editor shows text breaking at different line positions than the original PDF render, before the user types anything.

These symptoms are caused by two distinct root causes in the model and view layers.

---

## Root Cause Analysis

### Root Cause 1 (Primary): `_build_insert_css` recalculates line height instead of preserving the original

**File:** `model/pdf_model.py:2761–2800` (`_build_insert_css`) and `model/pdf_model.py:3450` (call site)

When the model commits an edit via `_apply_redact_insert`, it builds a CSS block for `insert_htmlbox`:

```python
css = self._build_insert_css(size, color, resolve_result.resolved_font)
# ← no line_height passed; defaults to 0
```

`_build_insert_css` when `line_height=0` auto-calculates:
```python
line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
```

For a typical font this produces `~size × 1.1`. The original PDF line may have had a tighter or looser line height. Any mismatch causes the committed text block to be taller or shorter than the original, triggering the pre-push mechanism at `model/pdf_model.py:3567–3580` which then pushes surrounding unedited text.

`_build_insert_css` already accepts a `line_height` parameter designed exactly for this purpose (see docstring at line 2768). It is simply never passed at the primary call site.

### Root Cause 2 (Secondary): `get_render_width_for_edit` expands editor beyond the original text block width

**File:** `model/pdf_model.py:1519–1531`

```python
def get_render_width_for_edit(self, page_num, rect, rotation, font_size) -> float:
    right_margin_pt = max(60.0, min(120.0, float(font_size) * 2.0))
    right_safe = page_rect.x1 - right_margin_pt
    max_w = right_safe - max(rect.x0, page_rect.x0) - margin
    return max(rect.width, min(max_w, page_rect.width * 0.98))
```

This can return a width **larger** than `rect.width`, meaning the editor is shown wider than the original text block. The editor's Qt font renderer (which has slightly different horizontal glyph metrics than PyMuPDF) lays out text at a different visual width, so wrapping breaks at different character positions — even before the user types anything. This is the "break lines once edit box opened" symptom.

The correct behavior for fidelity is to match the original block width exactly.

### Non-issue found during investigation

`_convert_text_to_html(new_text, int(size), color, ...)` at line 3448 passes `int(size)` but the function **does not use its `font_size` parameter**. The CSS `font-size` comes from `_build_insert_css` which correctly uses `float(size)`. So `int(size)` is dead code (no size truncation occurs). Needs cleanup only.

---

## Critical Files

| File | Lines | Role |
|------|-------|------|
| `model/pdf_model.py` | 3446–3451 | `_apply_redact_insert` — call to `_build_insert_css` |
| `model/pdf_model.py` | 2761–2800 | `_build_insert_css` — line_height param already exists |
| `model/pdf_model.py` | 1519–1531 | `get_render_width_for_edit` — returns expanded width |
| `view/text_editing.py` | 413–415 | `create_text_editor` — calls `get_render_width_for_edit` |
| `test_scripts/test_edit_text_helpers.py` | — | Model-layer tests (add new ones here) |
| `test_scripts/test_text_editing_gui_regressions.py` | — | View-layer tests |

---

## Implementation Plan

### Task 1: Write failing test — no-op round-trip must be NO_OP

**File:** `test_scripts/test_edit_text_helpers.py`

**Goal:** Confirm that opening an editor and closing without any change never commits anything to the PDF.

**Step 1: Write the test**

```python
# test_scripts/test_edit_text_helpers.py

def test_no_op_open_close_does_not_modify_span_height():
    """Opening editor and closing with no change must not alter span bbox height."""
    import fitz
    from model.pdf_model import PDFModel

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    # Insert text at a known size; use insert_htmlbox for realistic line-height
    page.insert_text((50, 100), "Hello World", fontname="helv", fontsize=12.0)
    doc.save(tf := __import__('tempfile').mktemp(suffix='.pdf'))
    doc.close()

    model = PDFModel()
    model.open_pdf(tf)
    page_num = 1

    # Measure original span height
    model.ensure_page_index_built(page_num)
    hit = model.get_text_info_at_point(page_num, fitz.Point(70, 100))
    assert hit is not None, "Must find text at insertion point"
    original_height = float(hit.target_bbox.height)

    # Simulate no-op edit: same text back with same size
    from model.edit_requests import EditTextRequest
    request = EditTextRequest(
        page=page_num,
        rect=hit.target_bbox,
        new_text=hit.target_text,   # unchanged
        font=hit.font,
        size=hit.size,              # unchanged
        color=hit.color,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
    )
    result = model.edit_text(request)
    # Check outcome — if text and style unchanged, model should detect NO_OP
    # If NO_OP: PDF not modified, span height preserved

    model.ensure_page_index_built(page_num)
    hit2 = model.get_text_info_at_point(page_num, fitz.Point(70, 100))
    assert hit2 is not None
    new_height = float(hit2.target_bbox.height)

    tolerance = 1.5  # pt
    assert abs(new_height - original_height) <= tolerance, (
        f"Span height changed from {original_height:.2f}pt to {new_height:.2f}pt "
        f"after no-op edit — line height not preserved"
    )
    model.close_document()
```

**Step 2: Run to verify RED**

```bash
cd "C:\Users\jiang\Documents\python programs\pdf_editor"
pytest test_scripts/test_edit_text_helpers.py::test_no_op_open_close_does_not_modify_span_height -xvs
```

Expected: FAIL — span height increases by ~2pt due to auto-calculated line-height

**Step 3: Commit test**

```bash
git add test_scripts/test_edit_text_helpers.py
git commit -m "test(fidelity): red-light test for span height preservation in no-op edit"
```

---

### Task 2: Write failing test — actual edit must preserve line height

**File:** `test_scripts/test_edit_text_helpers.py`

**Step 1: Write the test**

```python
def test_actual_edit_preserves_span_line_height():
    """Changing text content must not change the line height of the committed span."""
    import fitz, tempfile
    from model.pdf_model import PDFModel
    from model.edit_requests import EditTextRequest

    # Create PDF with a specific text block
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "Hello World", fontname="helv", fontsize=12.0)
    tmp = tempfile.mktemp(suffix='.pdf')
    doc.save(tmp)
    doc.close()

    model = PDFModel()
    model.open_pdf(tmp)
    model.ensure_page_index_built(1)
    hit = model.get_text_info_at_point(1, fitz.Point(70, 100))
    assert hit is not None
    original_height = float(hit.target_bbox.height)

    # Make a real edit: change one character
    edited_text = hit.target_text.replace("Hello", "Hi")
    request = EditTextRequest(
        page=1,
        rect=hit.target_bbox,
        new_text=edited_text,
        font=hit.font,
        size=hit.size,
        color=hit.color,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
    )
    model.edit_text(request)

    model.ensure_page_index_built(1)
    # Re-locate text after edit
    hit2 = model.get_text_info_at_point(1, fitz.Point(70, 100))
    assert hit2 is not None, "Text must still be found after edit"
    new_height = float(hit2.target_bbox.height)

    tolerance = 1.5  # pt
    assert abs(new_height - original_height) <= tolerance, (
        f"Line height changed {original_height:.2f}pt → {new_height:.2f}pt "
        f"after content edit — layout is not size-preserving"
    )
    model.close_document()
```

**Step 2: Run to verify RED**

```bash
pytest test_scripts/test_edit_text_helpers.py::test_actual_edit_preserves_span_line_height -xvs
```

Expected: FAIL — span height changes due to auto-calculated line_height in CSS

**Step 3: Commit test**

```bash
git add test_scripts/test_edit_text_helpers.py
git commit -m "test(fidelity): red-light test for line height preservation in content edit"
```

---

### Task 3: Implement fix — pass original line height to `_build_insert_css`

**File:** `model/pdf_model.py:3446–3451`

**Step 1: Read `_apply_redact_insert` context**

Before editing, re-read lines 3380–3460 of `model/pdf_model.py` to locate:
- Where `member_spans` are populated
- The exact position of the `css = self._build_insert_css(size, color, ...)` call

**Step 2: Write the fix**

At line 3450, replace the call with a version that computes `original_line_ht` from `member_spans` before building the CSS:

```python
# Calculate original line height from member spans to preserve visual height.
# For single-line runs: use the span bbox height directly.
# For multi-line: use the distance between consecutive baselines (line advance).
_line_ht = 0.0
if member_spans:
    sorted_spans = sorted(member_spans, key=lambda s: float(s.origin.y))
    if len(sorted_spans) >= 2:
        # Multi-line: measure baseline-to-baseline advance
        _advances = [
            abs(float(sorted_spans[i + 1].origin.y) - float(sorted_spans[i].origin.y))
            for i in range(len(sorted_spans) - 1)
            if abs(float(sorted_spans[i + 1].origin.y) - float(sorted_spans[i].origin.y)) > 0.5
        ]
        if _advances:
            _line_ht = sorted(_advances)[len(_advances) // 2]  # median
    if _line_ht <= 0:
        # Single-line: use span bbox height
        _line_ht = max(float(s.bbox.height) for s in member_spans if s.bbox.height > 0)

css = self._build_insert_css(size, color, resolve_result.resolved_font, line_height=_line_ht)
```

This replaces the single line:
```python
css = self._build_insert_css(size, color, resolve_result.resolved_font)
```

**Step 3: Run tests**

```bash
pytest test_scripts/test_edit_text_helpers.py::test_no_op_open_close_does_not_modify_span_height test_scripts/test_edit_text_helpers.py::test_actual_edit_preserves_span_line_height -xvs
```

Expected: PASS (both)

**Step 4: Run full test suite**

```bash
pytest test_scripts/ -x --tb=short -q
```

Expected: all existing tests pass

**Step 5: Commit**

```bash
git add model/pdf_model.py
git commit -m "fix(fidelity): preserve original line height when committing edited text"
```

---

### Task 4: Fix `get_render_width_for_edit` to not expand beyond original rect width

**File:** `model/pdf_model.py:1519–1531`

**Step 1: Write the test**

```python
# test_scripts/test_edit_text_helpers.py

def test_render_width_for_edit_does_not_exceed_rect_width():
    """Editor width should match original text block width, never wider."""
    import fitz
    from model.pdf_model import PDFModel

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    doc.save(tf := __import__('tempfile').mktemp(suffix='.pdf'))
    doc.close()

    model = PDFModel()
    model.open_pdf(tf)
    
    test_rect = fitz.Rect(50, 80, 200, 100)  # width = 150pt
    returned_width = model.get_render_width_for_edit(
        page_num=1, rect=test_rect, rotation=0, font_size=12.0
    )
    
    assert returned_width <= test_rect.width + 0.5, (
        f"Editor width {returned_width:.1f}pt exceeds original rect width "
        f"{test_rect.width:.1f}pt — editor will show different wrapping than PDF"
    )
    model.close_document()
```

**Step 2: Run to verify RED**

```bash
pytest test_scripts/test_edit_text_helpers.py::test_render_width_for_edit_does_not_exceed_rect_width -xvs
```

Expected: FAIL when `right_safe - x0 - margin` > `rect.width`

**Step 3: Implement fix**

Replace the body of `get_render_width_for_edit` (lines 1519–1531) with:

```python
def get_render_width_for_edit(
    self,
    page_num: int,
    rect: fitz.Rect,
    rotation: int = 0,
    font_size: float = 12,
) -> float:
    """Return the line-wrap width (points) for the inline editor.
    
    For fidelity, return the original rect width so the editor wraps
    text at exactly the same points as the source PDF.
    Rotated text uses rect.width unchanged (swapped in caller).
    """
    return float(rect.width)
```

**Step 4: Run all tests**

```bash
pytest test_scripts/ -x --tb=short -q
```

Expected: all pass. If any tests fail due to the narrower width (e.g., tests that assume expansion), update assertions.

**Step 5: Commit**

```bash
git add model/pdf_model.py test_scripts/test_edit_text_helpers.py
git commit -m "fix(fidelity): editor width matches original text block — no spurious wrapping divergence"
```

---

### Task 5: Clean up dead `int(size)` cast at line 3448

**File:** `model/pdf_model.py:3447–3449`

**Step 1: Verify it's a dead parameter**

Run:
```bash
grep -n "font_size" model/pdf_model.py | head -20
```

Confirm `_convert_text_to_html` doesn't reference `font_size` in its body.

**Step 2: Write cleanup test (informational)**

```python
def test_convert_text_to_html_output_unchanged_for_float_vs_int_size():
    """Confirm _convert_text_to_html ignores its font_size arg (dead parameter)."""
    from model.pdf_model import PDFModel
    model = PDFModel.__new__(PDFModel)
    # Manually stub needed attributes
    model._pdf_font_to_qt = lambda x: x
    
    # Both calls must return identical output
    result_int = model._convert_text_to_html("Test ABC", 9, (0.0, 0.0, 0.0))
    result_float = model._convert_text_to_html("Test ABC", 9.5, (0.0, 0.0, 0.0))
    assert result_int == result_float, "font_size param is used — fix the plan"
```

**Step 3: Change `int(size)` to `size`**

At `model/pdf_model.py:3447–3449`, change:
```python
html_content = self._convert_text_to_html(
    new_text, int(size), color, latin_font=resolve_result.resolved_font
)
```
to:
```python
html_content = self._convert_text_to_html(
    new_text, size, color, latin_font=resolve_result.resolved_font
)
```

Also update `_convert_text_to_html`'s signature at line 2342:
```python
def _convert_text_to_html(
    self,
    text: str,
    font_size: float,   # was int
    color: tuple,
    latin_font: str = "helv",
) -> str:
```

**Step 4: Run tests**

```bash
pytest test_scripts/ -x --tb=short -q
ruff check .
```

**Step 5: Commit**

```bash
git add model/pdf_model.py
git commit -m "refactor(model): remove dead int(size) cast in _apply_redact_insert, update signature to float"
```

---

### Task 6: Update PITFALLS.md

**File:** `docs/PITFALLS.md`

Add at the end:

```markdown
## Committed text line height diverges from original PDF — text appears bigger/smaller

**Area:** `model/pdf_model.py` — `_apply_redact_insert`, `_build_insert_css`
**Symptom:** After editing text, the committed text block takes more or less vertical space than the original, making surrounding unedited content shift ("push unedited lines away") or leave a gap.
**Cause:** `_build_insert_css` defaults to `line_height = max(size × 1.1, font_metrics × size)` when no explicit line_height is given. This auto-calculated value differs from the original PDF's actual line spacing, so `insert_htmlbox` lays out committed text with different height than the original span.
**Fix:** Compute original line height from `member_spans`: baseline-to-baseline advance for multi-line targets, `span.bbox.height` for single-line. Pass this as `line_height` to `_build_insert_css`.
**File:** `model/pdf_model.py` — `_apply_redact_insert` (call to `_build_insert_css`)

---

## Editor width wider than source rect causes wrapping divergence

**Area:** `model/pdf_model.py` — `get_render_width_for_edit`
**Symptom:** Inline editor shows text on fewer lines than the PDF (text "expands" visually), because the editor is set wider than the original text block.
**Cause:** `get_render_width_for_edit` returned `max(rect.width, page-margin-safe-width)`, potentially exceeding the original block width.
**Fix:** Return `rect.width` directly; the editor should match the original block width to preserve visual wrapping fidelity.
**File:** `model/pdf_model.py` — `get_render_width_for_edit`
```

**Step: Commit**

```bash
git add docs/PITFALLS.md
git commit -m "docs: add PITFALLS entries for line height drift and editor width divergence"
```

---

## Verification

After all tasks:

```bash
# Full test suite
pytest test_scripts/ -q --tb=short

# Lint
ruff check .

# Type check
mypy model/ utils/
```

Manual verification using `1.pdf`:
1. Open `1.pdf` in the editor
2. Click on a text block → editor opens at same visual width as the text
3. Type one character change → commit
4. Verify the surrounding unedited text did NOT shift
5. The edited block should occupy the same vertical space as before
6. Repeat 3× — text size must remain stable across multiple edits
