# Text Editing Fidelity: Harden real-PDF regression tests + GUI editor regression

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Strengthen the three weaknesses the adversarial review found in `codex/best-text-editing-ux`:
1. Real-PDF regression tests unnecessarily monkeypatch `_needs_cjk_font` — remove it since the reproducer PDFs already contain CJK text that naturally routes through `insert_htmlbox`.
2. Span discovery is heuristic (`_find_largest_font_span`, `_find_any_editable_span`) — replace with deterministic targets using known text content from each PDF.
3. No GUI-level regression for the pre-commit inline editor geometry mismatch — add one.

**Branch:** All edits go on `codex/best-text-editing-ux` (already contains the `_build_insert_css` fix and base tests).

**Tech Stack:** PyMuPDF (`fitz`), pytest, PySide6, `model/pdf_model.py`, `view/text_editing.py`

---

## Context

The previous Codex session fixed `_build_insert_css` (removed unconditional `max(size, line_height)` clamp) and added regression tests. The adversarial review (`gpt-5.4`) flagged three test weaknesses that allow the manual regression to survive while tests stay green.

### Why the PDFs don't need `_needs_cjk_font` monkeypatch

Both reproducer PDFs contain Chinese text:
- `test-complexed-layout.pdf` page 1: `'在編輯文字時清除舊有文字的做法'` (size 9.0, all-CJK content)
- `test-colored-background.pdf` page 1: `'Revit前置作業操作流程'` (size 60.0, CJK heading)

`_apply_redact_insert` fast-path (`insert_text`) requires `not self._needs_cjk_font(new_text)`. CJK text always takes the `insert_htmlbox` path naturally, so `monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)` is redundant AND misleading (it now also forces the font-resolution path to pretend ALL text is CJK).

The synthetic tests at lines 491-598 *intentionally* monkeypatch (they exercise the htmlbox path with a Latin-only PDF and have comments explaining this). Those are KEPT as-is. Only the real-PDF tests (lines 783-907) need the monkeypatch removed.

### Deterministic span coordinates (verified from actual PDFs)

**test-complexed-layout.pdf page 1**
- Target text: `'在編輯文字時清除舊有文字的做法'`
- Source bbox: `[117.6, 80.2, 252.6, 89.2]`  → probe point `fitz.Point(185, 85)`
- Font size: 9.0pt
- CJK → naturally uses `insert_htmlbox`

**test-colored-background.pdf page 1**
- Target text: `'Revit前置作業操作流程'`
- Source bbox: `[410.5, 256.5, 1030.2, 333.3]` → probe point `fitz.Point(720, 295)`
- Font size: 60.0pt
- CJK → naturally uses `insert_htmlbox`

---

## Critical files

| File | Lines | Role |
|------|-------|------|
| `test_scripts/test_edit_text_helpers.py` | 783–907 | Real-PDF regression tests — remove monkeypatch, fix deterministic targets |
| `test_scripts/test_text_editing_gui_regressions.py` | end | Add GUI editor geometry regression |
| `view/text_editing.py` | 338–395 | `create_text_editor` — sets editor font size + width |
| `model/pdf_model.py` | ~1525 | `get_render_width_for_edit` — already fixed to return `float(rect.width)` |

---

## Implementation Plan

### Task 1: Remove `_needs_cjk_font` monkeypatch from real-PDF regression tests

**File:** `test_scripts/test_edit_text_helpers.py` (lines ~783–907 on `codex/best-text-editing-ux`)

**Precondition:** Checkout `codex/best-text-editing-ux` first.

**Step 1: Verify current state**
```bash
git checkout codex/best-text-editing-ux
grep -n "_needs_cjk_font\|monkeypatch" test_scripts/test_edit_text_helpers.py
```
Expected: lines 813 and 877 have `monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)`

**Step 2: Edit `test_real_pdf_complexed_layout_edit_does_not_enlarge_span`**

Remove the `monkeypatch: pytest.MonkeyPatch` parameter from the function signature and delete the monkeypatch line.

Change:
```python
def test_real_pdf_complexed_layout_edit_does_not_enlarge_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
```
To:
```python
def test_real_pdf_complexed_layout_edit_does_not_enlarge_span(
    tmp_path: Path,
):
```

Remove the line:
```python
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)
```

Do the same for `test_real_pdf_colored_background_edit_does_not_shrink_span`.

**Step 3: Run to verify tests still pass**
```bash
pytest test_scripts/test_edit_text_helpers.py::test_real_pdf_complexed_layout_edit_does_not_enlarge_span \
       test_scripts/test_edit_text_helpers.py::test_real_pdf_colored_background_edit_does_not_shrink_span \
       -xvs
```
Expected: PASS (CJK text naturally uses htmlbox path).

If FAIL with "no span found" — the probe point is not matching; skip to Task 2 first (deterministic targets) which also fixes probe points.

**Step 4: Commit**
```bash
git add test_scripts/test_edit_text_helpers.py
git commit -m "test(fidelity): remove unnecessary _needs_cjk_font monkeypatch from real-PDF tests"
```

---

### Task 2: Replace heuristic span discovery with deterministic targets

**File:** `test_scripts/test_edit_text_helpers.py`

The two heuristic helpers (`_find_largest_font_span`, `_find_any_editable_span`) scan the page with a grid and pick the first/largest hit — fragile and non-reproducible. Replace with direct `get_text_info_at_point` calls using known probe coordinates.

**Step 1: Edit `test_real_pdf_complexed_layout_edit_does_not_enlarge_span`**

Replace the helper call and assertion:
```python
        hit = _find_largest_font_span(model, 1)
        assert hit is not None, "Could not find largest-font heading on page 1"
```
With:
```python
        # Deterministic target: '在編輯文字時清除舊有文字的做法' at bbox [117.6, 80.2, 252.6, 89.2]
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(185, 85))
        assert hit is not None, "Could not find CJK heading span at (185, 85) on page 1 of complexed-layout.pdf"
        assert "在" in hit.target_text, (
            f"Expected CJK heading but found: {hit.target_text!r}"
        )
```

**Step 2: Edit `test_real_pdf_colored_background_edit_does_not_shrink_span`**

Replace:
```python
        hit = _find_any_editable_span(model, 1)
        assert hit is not None, "Could not find any editable text on page 1"
```
With:
```python
        # Deterministic target: 'Revit前置作業操作流程' at bbox [410.5, 256.5, 1030.2, 333.3]
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(720, 295))
        assert hit is not None, "Could not find CJK heading span at (720, 295) on page 1 of colored-background.pdf"
        assert "Revit" in hit.target_text, (
            f"Expected 'Revit前置...' heading but found: {hit.target_text!r}"
        )
```

**Step 3: Run both tests**
```bash
pytest test_scripts/test_edit_text_helpers.py::test_real_pdf_complexed_layout_edit_does_not_enlarge_span \
       test_scripts/test_edit_text_helpers.py::test_real_pdf_colored_background_edit_does_not_shrink_span \
       -xvs
```
Expected: both PASS.

**Step 4: Run full suite to check for regressions**
```bash
pytest test_scripts/ -x --tb=short -q
```
Expected: all pass.

**Step 5: Commit**
```bash
git add test_scripts/test_edit_text_helpers.py
git commit -m "test(fidelity): deterministic span targets in real-PDF regression tests"
```

---

### Task 3: Add GUI-level regression for pre-commit inline editor geometry

**File:** `test_scripts/test_text_editing_gui_regressions.py` (append at end)

**Why:** The adversarial review noted that the model-only tests pass even if the inline editor opens with wrong font size or wrong width. This test verifies that `create_text_editor` configures the editor with the font size and width from the source span.

The test must NOT need a real PDF file — create a synthetic one inline so it's fast and always available.

**Step 1: Append the following test**

```python
def test_create_text_editor_uses_source_span_font_size_and_width(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """The inline editor must open with font_size and width that match the source span.

    Regression guard for two fidelity failures:
    - Editor font size != span size  → user sees different text size before committing
    - Editor width > rect width      → text wraps at different positions than the PDF
    """
    from types import SimpleNamespace

    captured: dict = {}

    class _CapturingInlineTextEditor(_FakeInlineTextEditor):
        def setFont(self, font) -> None:
            captured["font_size"] = font.pointSizeF()
        def setFixedWidth(self, w: int) -> None:
            captured["fixed_width"] = w

    source_font_size = 14.0
    source_rect = fitz.Rect(50, 80, 250, 100)  # width = 200pt

    class _FakeSceneCapturing(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
        def addWidget(self, widget):
            return _FakeProxy(widget)

    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneCapturing()
    view._render_scale = 1.0
    # Use the real get_render_width_for_edit logic: PDFModel already returns float(rect.width)
    # but we stub it to isolate this test from any model state.
    view.controller = SimpleNamespace(
        model=SimpleNamespace(
            get_render_width_for_edit=lambda page_num, rect, rotation, font_size: float(rect.width)
        )
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view._set_edit_focus_guard = lambda enabled: None
    view._sync_text_property_panel_state = lambda: None

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color = lambda: None

    monkeypatch.setattr(text_editing, "InlineTextEditor", _CapturingInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda view: object())

    manager.create_text_editor(
        rect=source_rect,
        text="Sample span text",
        font_name="helv",
        font_size=source_font_size,
        color=(0.0, 0.0, 0.0),
        rotation=0,
        target_span_id="test-span",
        target_mode="run",
    )

    assert "font_size" in captured, "setFont was never called — editor creation failed"
    assert abs(captured["font_size"] - source_font_size) < 0.1, (
        f"Editor font size {captured['font_size']:.2f}pt ≠ source span {source_font_size:.2f}pt"
    )

    assert "fixed_width" in captured, "setFixedWidth was never called"
    expected_width_px = int(source_rect.width * 1.0)  # render_scale=1.0
    assert captured["fixed_width"] == expected_width_px, (
        f"Editor width {captured['fixed_width']}px ≠ expected {expected_width_px}px "
        f"(rect.width={source_rect.width}pt at scale=1.0) — editor may show wrong wrapping"
    )
```

**Step 2: Run the new test**
```bash
pytest test_scripts/test_text_editing_gui_regressions.py::test_create_text_editor_uses_source_span_font_size_and_width -xvs
```
Expected: PASS.

**Step 3: Run full GUI regression suite**
```bash
pytest test_scripts/test_text_editing_gui_regressions.py -x --tb=short -q
```
Expected: all pass.

**Step 4: Commit**
```bash
git add test_scripts/test_text_editing_gui_regressions.py
git commit -m "test(fidelity): GUI regression — editor font size and width must match source span"
```

---

### Task 4: Final verification and cleanup

**Step 1: Run full test suite**
```bash
pytest test_scripts/ -q --tb=short
```
Expected: zero failures.

**Step 2: Lint**
```bash
ruff check .
```
Expected: zero new violations.

**Step 3: Verify `_FakeInlineTextEditor` has `setFont` method**

Check that `_FakeInlineTextEditor` (used throughout the GUI test file) has a `setFont` stub, otherwise the `_CapturingInlineTextEditor` subclass override won't be called:
```bash
grep -n "class _FakeInlineTextEditor\|def setFont" test_scripts/test_text_editing_gui_regressions.py | head -10
```

If `_FakeInlineTextEditor` is missing `setFont`, add it:
```python
def setFont(self, font) -> None:
    pass
```

**Step 4: Final commit (if any fixups needed)**
```bash
git add test_scripts/
git commit -m "test(fidelity): fixup _FakeInlineTextEditor setFont stub"
```

---

## Verification

```bash
# On codex/best-text-editing-ux branch:
pytest test_scripts/ -q --tb=short          # zero failures
ruff check .                                 # zero violations
```

Manual spot-check:
1. Open `test_files/test-complexed-layout.pdf` → click on `'在編輯文字時清除舊有文字的做法'` heading → edit one character → commit → surrounding text must NOT shift
2. Open `test_files/test-colored-background.pdf` → click on `'Revit前置作業操作流程'` → edit one character → commit → line spacing must be identical before/after

## Previously completed (do not redo)

On `codex/best-text-editing-ux`:
- `_line_ht` computation from `member_spans` and passing to `_build_insert_css` (`fbfe4c6`)
- `_build_insert_css` clamp moved inside auto-calculate branch (`c1d8d79`)
- `get_render_width_for_edit` simplified to `return float(rect.width)` (`1ffe189`)
- Pre-push probe fixed (`cc55872`)
- Dead `int(size)` cast removed (`b252f90`)
- PITFALLS.md updated (`bf51f15`, `ccbcc3f`)
- Synthetic tests with monkeypatch (lines 491-598) — KEEP as-is, they intentionally test the htmlbox path for Latin text
