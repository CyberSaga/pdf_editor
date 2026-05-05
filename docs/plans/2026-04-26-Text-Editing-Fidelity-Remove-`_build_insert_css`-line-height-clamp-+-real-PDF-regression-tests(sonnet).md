# Text Editing Fidelity: Remove `_build_insert_css` line-height clamp + real-PDF regression tests

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix remaining fidelity failures — text appears larger or smaller after editing — by removing an over-aggressive clamp in `_build_insert_css` that overwrites the original line height with `max(size, line_height)` even when an explicit, authoritative value is provided.

**Architecture:** Single-line model change at `model/pdf_model.py:2787`, plus new pytest fixtures that use the actual reproducer PDFs (`test-complexed-layout.pdf` for "larger" case, `test-colored-background.pdf` for "smaller" case). These tests must go RED before any implementation.

**Tech Stack:** PyMuPDF (`fitz`), pytest, `model/pdf_model.py`

---

## Background and root cause

Previous sessions added passing `_line_ht` to `_build_insert_css`, and the pre-push probe was fixed to trust actual height measurements. The Codex adversarial review identified a **remaining clamp** that defeats both fixes for tight-leading PDFs.

### The surviving bug — `model/pdf_model.py:2787`

```python
# Current code (lines 2780–2787):
if line_height <= 0:
    try:
        font_obj = fitz.Font(resolved_font)
        line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
    except Exception:
        line_height = size * 1.2
line_height = round(max(size, line_height), 2)   # ← clamps ALWAYS, including explicit values
```

The last line runs whether or not `line_height` was auto-calculated. If `_apply_redact_insert` passes `_line_ht = 8.0` (a tight-leading PDF where baseline advance < font size, e.g. 10pt font with 8pt advance), the clamp forces `max(10.0, 8.0) = 10.0`. The committed HTML box is 10pt tall per line instead of 8pt — **bigger** than original. This directly causes the "larger" symptom observed in `test-complexed-layout.pdf`.

For the "smaller" symptom in `test-colored-background.pdf`: `_line_ht` may fall back to `max(span.bbox.height)` for single-line spans, which only measures glyph height (≈ font size), not the full line advance including extra leading. The committed CSS `line-height` then under-estimates the original spacing, producing a more compact block.

### The fix

Move the `max(size, ...)` clamp INSIDE the auto-calculate branch only. Explicit positive values get passed through with only a rounding step:

```python
if line_height <= 0:
    try:
        font_obj = fitz.Font(resolved_font)
        line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
    except Exception:
        line_height = size * 1.2
    line_height = round(max(size, line_height), 2)   # auto-calc: must be ≥ size
else:
    line_height = round(line_height, 2)              # explicit: trust caller
```

---

## Critical files

| File | Lines | Role |
|------|-------|------|
| `model/pdf_model.py` | 2780–2787 | `_build_insert_css` — clamp to fix |
| `model/pdf_model.py` | 3453–3469 | `_apply_redact_insert` — `_line_ht` computation |
| `test_scripts/test_edit_text_helpers.py` | end of file | Add real-PDF regression tests |
| `test_files/test-complexed-layout.pdf` | — | Reproducer for "larger" case |
| `test_files/test-colored-background.pdf` | — | Reproducer for "smaller" case |

---

## Implementation Plan

### Task 1: Write failing regression tests using the real reproducer PDFs

**File:** `test_scripts/test_edit_text_helpers.py` (append at end)

The existing synthetic tests use `_make_pdf_at_size()` with Helvetica, which happens to have `span.bbox.height ≈ font size`. These pass even with the clamp. The real PDFs expose the clamp bug.

**Note on `model.edit_text` API:** Call as `model.edit_text(page_num=1, rect=..., new_text=..., font=..., size=..., color=..., original_text=..., target_span_id=..., target_mode="run")`. Not via `EditTextRequest`. See existing test at line 360 for the correct calling pattern.

**Step 1: Write and append the tests**

```python
# ── Real-PDF regression tests — "larger" and "smaller" symptoms ─────────────

REAL_PDFS_DIR = ROOT / "test_files"


def _find_first_editable_span(model: PDFModel, page_num: int):
    """Return the first span with non-empty text on page_num, or None."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    for y in range(50, int(page_rect.height) - 20, 20):
        for x in range(30, int(page_rect.width) - 20, 30):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is not None and hit.target_text.strip():
                return hit
    return None


def test_real_pdf_complexed_layout_edit_does_not_enlarge_span(tmp_path: Path):
    """Editing text in test-complexed-layout.pdf must not grow the span's vertical extent.

    'Larger' symptom reproducer: _build_insert_css clamped line_height to >= size
    even for explicit tight-leading values, making committed boxes taller than original.
    """
    import shutil
    pdf_src = REAL_PDFS_DIR / "test-complexed-layout.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")

    pdf_copy = tmp_path / "complexed.pdf"
    shutil.copy2(pdf_src, pdf_copy)

    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        hit = _find_first_editable_span(model, 1)
        assert hit is not None, "Could not find any editable text on page 1"
        height_before = float(hit.target_bbox.height)

        model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=hit.target_text + " ",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )

        model.ensure_page_index_built(1)
        hit_after = model.get_text_info_at_point(1, fitz.Point(
            float(hit.target_bbox.x0) + 2, float(hit.target_bbox.y0) + 2
        ))
        if hit_after is None:
            return
        height_after = float(hit_after.target_bbox.height)

        assert height_after <= height_before + 1.5, (
            f"Span height grew {height_before:.2f}pt → {height_after:.2f}pt in complexed-layout.pdf "
            f"— 'larger' symptom still active: check _build_insert_css clamp"
        )
    finally:
        model.close()


def test_real_pdf_colored_background_edit_does_not_shrink_span(tmp_path: Path):
    """Editing text in test-colored-background.pdf must not shrink the span's vertical extent.

    'Smaller' symptom reproducer: _line_ht from span.bbox.height under-estimates
    original line advance for PDFs with extra leading, producing more compact committed text.
    """
    import shutil
    pdf_src = REAL_PDFS_DIR / "test-colored-background.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")

    pdf_copy = tmp_path / "colored.pdf"
    shutil.copy2(pdf_src, pdf_copy)

    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        hit = _find_first_editable_span(model, 1)
        assert hit is not None, "Could not find any editable text on page 1"
        height_before = float(hit.target_bbox.height)

        model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=hit.target_text + " ",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )

        model.ensure_page_index_built(1)
        hit_after = model.get_text_info_at_point(1, fitz.Point(
            float(hit.target_bbox.x0) + 2, float(hit.target_bbox.y0) + 2
        ))
        if hit_after is None:
            return
        height_after = float(hit_after.target_bbox.height)

        assert height_after >= height_before - 1.5, (
            f"Span height shrank {height_before:.2f}pt → {height_after:.2f}pt in colored-background.pdf "
            f"— 'smaller' symptom still active: check _line_ht computation"
        )
    finally:
        model.close()
```

**Step 2: Run to verify RED**

```bash
cd "C:\Users\jiang\Documents\python programs\pdf_editor"
pytest test_scripts/test_edit_text_helpers.py::test_real_pdf_complexed_layout_edit_does_not_enlarge_span \
       test_scripts/test_edit_text_helpers.py::test_real_pdf_colored_background_edit_does_not_shrink_span \
       -xvs 2>&1 | head -80
```

Expected: at least one FAILS. If both SKIP, verify `test_files/` paths. If both PASS already, move probe point closer to where the manual symptom was observed (adjust the `_find_first_editable_span` loop range).

**Step 3: Commit the red tests**

```bash
git add test_scripts/test_edit_text_helpers.py
git commit -m "test(fidelity): red-light regression tests using real reproducer PDFs"
```

---

### Task 2: Fix `_build_insert_css` — move clamp inside auto-calculate branch

**File:** `model/pdf_model.py:2780–2787`

**Step 1: Verify exact line numbers**

```bash
grep -n "max(size, line_height)" model/pdf_model.py
```

Expected: `2787:        line_height = round(max(size, line_height), 2)`

**Step 2: Apply the fix**

Replace:
```python
        if line_height <= 0:
            try:
                font_obj = fitz.Font(resolved_font)
                line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
            except Exception:
                line_height = size * 1.2
        line_height = round(max(size, line_height), 2)
```

With:
```python
        if line_height <= 0:
            try:
                font_obj = fitz.Font(resolved_font)
                line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
            except Exception:
                line_height = size * 1.2
            line_height = round(max(size, line_height), 2)
        else:
            line_height = round(line_height, 2)
```

**Step 3: Run the real-PDF regression tests**

```bash
pytest test_scripts/test_edit_text_helpers.py::test_real_pdf_complexed_layout_edit_does_not_enlarge_span \
       test_scripts/test_edit_text_helpers.py::test_real_pdf_colored_background_edit_does_not_shrink_span \
       -xvs
```

Expected: both PASS.

If "smaller" test still fails: proceed to Task 3. If "larger" test still fails: re-read `_line_ht` computation in `_apply_redact_insert` lines 3453–3469 — the median Y-advance may be computing a still-too-large value for that PDF.

**Step 4: Run full test suite**

```bash
pytest test_scripts/ -x --tb=short -q
```

Expected: all pass.

**Step 5: Commit**

```bash
git add model/pdf_model.py
git commit -m "fix(fidelity): trust explicit line_height in _build_insert_css — remove unconditional size clamp"
```

---

### Task 3 (conditional): Fix `_line_ht` single-line fallback if "smaller" test still fails

**Only do this if the `test_real_pdf_colored_background_edit_does_not_shrink_span` test still fails after Task 2.**

**Diagnosis:** For single-line blocks, `_line_ht` falls back to `max(span.bbox.height)` ≈ font size. But PDFs from Word/Acrobat often have extra leading BELOW the glyph that doesn't appear in `span.bbox.height`. Using `resolve_result.target.layout_rect.height` captures this full vertical extent.

**File:** `model/pdf_model.py:3463–3466`

Replace:
```python
        if _line_ht <= 0:
            _heights = [float(s.bbox.height) for s in member_spans if s.bbox.height > 0]
            if _heights:
                _line_ht = max(_heights)
```

With:
```python
        if _line_ht <= 0:
            # layout_rect.height captures the full line advance including extra leading,
            # whereas span.bbox.height only measures the glyph extent.
            layout_h = float(resolve_result.target.layout_rect.height)
            if layout_h > 0:
                _line_ht = layout_h
            else:
                _heights = [float(s.bbox.height) for s in member_spans if s.bbox.height > 0]
                if _heights:
                    _line_ht = max(_heights)
```

**Verify:**
```bash
pytest test_scripts/test_edit_text_helpers.py -x --tb=short -q
```

Expected: all pass.

**Commit:**
```bash
git add model/pdf_model.py
git commit -m "fix(fidelity): use block layout_rect height as single-line fallback for _line_ht"
```

---

### Task 4: Update PITFALLS.md

**File:** `docs/PITFALLS.md`

Append:

```markdown
## `_build_insert_css` unconditional `max(size, line_height)` clamp defeats explicit line heights

**Area:** `model/pdf_model.py` — `_build_insert_css`
**Symptom:** Edited text appears taller than original despite `_apply_redact_insert` correctly computing `_line_ht` from spans. Tight-leading PDFs (where baseline advance < font size) always get a taller line box after edit, pushing surrounding text.
**Cause:** `line_height = round(max(size, line_height), 2)` executed unconditionally — both for auto-calculated and explicit values. Explicit tight values (e.g. 8pt for a 10pt font) were silently clamped up to font size.
**Fix:** Move the clamp inside the `if line_height <= 0:` auto-calculate branch. Explicit positive values skip the clamp and are only rounded.
**File:** `model/pdf_model.py` — `_build_insert_css` lines 2780–2787
```

```bash
git add docs/PITFALLS.md
git commit -m "docs: add PITFALLS entry for _build_insert_css unconditional clamp"
```

---

## Verification

```bash
pytest test_scripts/ -q --tb=short   # zero failures
ruff check .                          # zero new violations
mypy model/ utils/                    # passes
```

Manual verification:
1. Open `test_files/test-complexed-layout.pdf` → edit a span → surrounding text must NOT shift
2. Open `test_files/test-colored-background.pdf` → edit a span → line spacing must stay the same
3. Repeat 3× on same span — no cumulative drift in either direction

## Previously completed (do not redo)

The following were already committed on branch `codex/best-text-editing-ux`:
- `_line_ht` passing from `_apply_redact_insert` to `_build_insert_css` (commit `fbfe4c6`)
- `get_render_width_for_edit` simplified to `return float(rect.width)` (commit `1ffe189`)
- Pre-push probe fixed to trust `_probe_used_h` and subtract MuPDF 2pt overhead (commit `cc55872`)
- Dead `int(size)` cast removed (commit `b252f90`)
- PITFALLS.md entries for prior fixes (commit `bf51f15`)

---

## [ORIGINAL — preserved for reference only]

*The section below was the original plan from a prior session. The tasks in it have been completed. The active work is described above.*

**Context:** When a user edits existing text in the PDF editor, the committed text should look the same size as the original. Currently it doesn't:

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

### Task 1: Write failing tests — font size and span height must survive a round-trip edit

**File:** `test_scripts/test_edit_text_helpers.py`

**Goal:** Confirm that both the font point size *and* the visual line height (bbox height) are preserved after an edit.  Two separate assertions are needed:

- `span["size"]` (font pt) must equal the original — guards against integer truncation re-emerging (see PITFALLS: "PyMuPDF font sizes are floats, not ints").
- `span["bbox"].height` must stay within tolerance — guards against line-height drift from `_build_insert_css` auto-calculation.

**Step 1: Write the tests**

```python
# test_scripts/test_edit_text_helpers.py

import fitz
import tempfile
import pytest
from model.pdf_model import PDFModel
from model.edit_requests import EditTextRequest


def _make_pdf_with_text(text: str, fontsize: float, pos=(50, 100)) -> str:
    """Create a single-page PDF with insert_text and return its temp path."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text(pos, text, fontname="helv", fontsize=fontsize)
    tmp = tempfile.mktemp(suffix=".pdf")
    doc.save(tmp)
    doc.close()
    return tmp


def _measure_span_at(model: PDFModel, page_num: int, pt: fitz.Point):
    """Return (font_size_pt, bbox_height_pt) for the span under pt, or None."""
    model.ensure_page_index_built(page_num)
    hit = model.get_text_info_at_point(page_num, pt)
    if hit is None:
        return None
    return float(hit.size), float(hit.target_bbox.height)


def test_edit_preserves_font_size_pt_after_content_change():
    """Font pt must not change when only text content is edited (no font-size user action).

    Guards against integer truncation (PITFALLS: float sizes silently become int),
    and against the committed CSS producing a different pt than the original.
    Checks fractional size (9.5pt) to catch truncation to 9pt as well as whole sizes.
    """
    for original_size in (12.0, 9.5, 24.0):
        tmp = _make_pdf_with_text("Hello World", original_size)
        model = PDFModel()
        model.open_pdf(tmp)
        probe = fitz.Point(65, 100)

        before = _measure_span_at(model, 1, probe)
        assert before is not None, f"Cannot find span at {probe} for size {original_size}"
        size_before, _ = before

        hit = model.get_text_info_at_point(1, probe)
        request = EditTextRequest(
            page=1,
            rect=hit.target_bbox,
            new_text="Hi World",          # changed text
            font=hit.font,
            size=hit.size,               # same size from model
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        model.edit_text(request)

        after = _measure_span_at(model, 1, probe)
        assert after is not None, "Text not found after edit"
        size_after, _ = after

        assert abs(size_after - size_before) < 0.5, (
            f"Font pt changed {size_before:.2f}pt → {size_after:.2f}pt "
            f"(original_size={original_size}) — size must survive a content edit"
        )
        model.close_document()


def test_edit_preserves_span_bbox_height_after_content_change():
    """Span bbox height (visual line height) must not change when only text content is edited.

    If _build_insert_css auto-calculates line_height = size × 1.1 but the original
    used tighter spacing, the committed span will be taller — pushing surrounding text.
    This test catches that drift.
    """
    for original_size in (12.0, 24.0):
        tmp = _make_pdf_with_text("Hello World", original_size)
        model = PDFModel()
        model.open_pdf(tmp)
        probe = fitz.Point(65, 100)

        before = _measure_span_at(model, 1, probe)
        assert before is not None
        _, height_before = before

        hit = model.get_text_info_at_point(1, probe)
        request = EditTextRequest(
            page=1,
            rect=hit.target_bbox,
            new_text="Hi World",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        model.edit_text(request)

        after = _measure_span_at(model, 1, probe)
        assert after is not None
        _, height_after = after

        tolerance = 1.5  # pt
        assert abs(height_after - height_before) <= tolerance, (
            f"Span height changed {height_before:.2f}pt → {height_after:.2f}pt "
            f"(size={original_size}) — line height must survive a content edit"
        )
        model.close_document()


def test_repeated_edits_do_not_accumulate_size_drift():
    """Running edit_text 5 times on the same span must not drift font size or height.

    If each commit introduces a small error, 5 rounds would amplify it to a
    detectable level. This guards against cumulative drift from repeated editing.
    """
    tmp = _make_pdf_with_text("Hello World", 12.0)
    model = PDFModel()
    model.open_pdf(tmp)
    probe = fitz.Point(65, 100)

    before = _measure_span_at(model, 1, probe)
    assert before is not None
    size_before, height_before = before

    for i in range(5):
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, probe)
        assert hit is not None, f"Span lost on iteration {i}"
        request = EditTextRequest(
            page=1,
            rect=hit.target_bbox,
            new_text=f"Edit {i}",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        model.edit_text(request)

    after = _measure_span_at(model, 1, probe)
    assert after is not None, "Span lost after repeated edits"
    size_after, height_after = after

    assert abs(size_after - size_before) < 0.5, (
        f"Font pt drifted {size_before:.2f}pt → {size_after:.2f}pt over 5 edits"
    )
    assert abs(height_after - height_before) <= 2.0, (
        f"Span height drifted {height_before:.2f}pt → {height_after:.2f}pt over 5 edits"
    )
    model.close_document()
```

**Step 2: Run to verify RED**

```bash
cd "C:\Users\jiang\Documents\python programs\pdf_editor"
pytest test_scripts/test_edit_text_helpers.py::test_edit_preserves_font_size_pt_after_content_change \
       test_scripts/test_edit_text_helpers.py::test_edit_preserves_span_bbox_height_after_content_change \
       test_scripts/test_edit_text_helpers.py::test_repeated_edits_do_not_accumulate_size_drift \
       -xvs
```

Expected results:
- `test_edit_preserves_font_size_pt_after_content_change` — **may pass** (CSS `font-size` already uses float). If it passes, this is a safety regression guard.
- `test_edit_preserves_span_bbox_height_after_content_change` — **FAIL** due to auto-calculated `line-height` inflating span height.
- `test_repeated_edits_do_not_accumulate_size_drift` — **FAIL** for height on ≥5 iterations.

**Step 3: Commit tests**

```bash
git add test_scripts/test_edit_text_helpers.py
git commit -m "test(fidelity): red-light tests for font size and line height preservation across edits"
```

---

### Task 2: Implement fix — pass original line height to `_build_insert_css`

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

### Task 3: Fix `get_render_width_for_edit` to not expand beyond original rect width

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

### Task 4: Clean up dead `int(size)` cast at line 3448

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

### Task 5: Update PITFALLS.md

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

Manual verification using `test-vertical-texts.pdf`:
1. Open `test-vertical-texts.pdf` in the editor
2. Click on a text block → editor opens at same visual width as the text
3. Type one character change → commit
4. Verify the surrounding unedited text did NOT shift
5. The edited block should occupy the same vertical space as before
6. Repeat 3× — text size must remain stable across multiple edits
