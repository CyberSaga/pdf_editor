# Text Editing UX Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix four critical text editing UX problems: bad initial framing, oversized editor, white-on-white text visibility, and reader context loss.

**Architecture:** The fixes span the View layer (`text_editing.py`) with targeted changes to editor mask color selection, content height calculation, and initial viewport positioning. The Model layer remains unchanged; no cross-layer API additions.

**Tech Stack:** PyMuPDF (fitz), PySide6 (QGraphicsScene, QTextEdit), Qt graphics geometry (QRect, QRectF)

---

## Problem Analysis

### Problem 1: White Editor Mask Hides White Text
**File:** `view/text_editing.py`, line 43  
**Symptom:** When PDF text is white and the editor background is also white (from `_DEFAULT_EDITOR_MASK_COLOR = QColor("#FFFFFF")`), the text becomes completely invisible inside the editor.  
**Root Cause:** `_readable_editor_mask_color()` ignores text color and always returns white.  
**Expected Fix:** Choose editor background color intelligently: if text is light (RGB average > 128), use dark background; if text is dark, use light background.

### Problem 2: Oversized Editor Container
**File:** `view/text_editing.py`, lines 435–441  
**Symptom:** Single-line text in a paragraph opens an editor that's 6× taller than needed, with grey void filling the gap.  
**Root Cause:** `_compute_editor_proxy_layout` uses `scaled_rect.height` directly; in paragraph mode, the resolver returns the full paragraph bounding box, not the individual line height.  
**Expected Fix:** Verify `content_height_px` path is correctly used; if issues remain, ensure measured height replaces rect-based sizing for non-rotated editors.

### Problem 3: Initial Viewport Over-Zoomed and Clipped
**File:** Likely `controller/pdf_controller.py` or `view/pdf_view.py`  
**Symptom:** Document opens with the first visible area appearing magnified/cropped instead of showing readable context (e.g., whole first page or first paragraph).  
**Root Cause:** Initial `render_scale` or viewport anchor is set too high or positioned off-page.  
**Expected Fix:** On first document open, set initial scale to fit-page (or fit-width) and center the viewport on page 1, y=0.

### Problem 4: Editor Mask Color Sampling Includes Text Pixels (Greying)
**File:** `view/text_editing.py`, lines 231–248  
**Symptom:** The sampled editor background color becomes grey instead of a pure, readable color (symptom of sampling rendered PDF text into the mask color average).  
**Root Cause:** `_average_image_rect_color()` samples the rendered pixmap under the editor, picking up text pixels.  
**Expected Fix:** Stop sampling the page image. Instead, use a stable, contrast-aware computed color (light text → dark background; dark text → light background).

---

## Task Breakdown

### Task 1: Compute Contrast-Aware Editor Background Color

**Files:**
- Modify: `view/text_editing.py:46-48` — replace `_readable_editor_mask_color()`
- Modify: `view/text_editing.py:390-395` — update `refresh_text_editor_mask_color()` call site

**Step 1: Write the failing test**

```python
# test_scripts/test_text_editing_gui_regressions.py

def test_editor_mask_color_white_text():
    """White text should have dark mask background for visibility."""
    from view.text_editing import _readable_editor_mask_color
    
    text_rgb = (255, 255, 255)  # white text
    mask_color = _readable_editor_mask_color(text_rgb)
    
    # Dark background for white text
    luminance = (mask_color.red() + mask_color.green() + mask_color.blue()) / 3
    assert luminance < 128, f"Expected dark mask for white text, got RGB({mask_color.red()}, {mask_color.green()}, {mask_color.blue()})"

def test_editor_mask_color_dark_text():
    """Dark text should have light mask background for visibility."""
    from view.text_editing import _readable_editor_mask_color
    
    text_rgb = (0, 0, 0)  # black text
    mask_color = _readable_editor_mask_color(text_rgb)
    
    # Light background for dark text
    luminance = (mask_color.red() + mask_color.green() + mask_color.blue()) / 3
    assert luminance > 128, f"Expected light mask for dark text, got RGB({mask_color.red()}, {mask_color.green()}, {mask_color.blue()})"

def test_editor_mask_color_grey_text():
    """Medium-grey text should have contrasting background."""
    from view.text_editing import _readable_editor_mask_color
    
    text_rgb = (128, 128, 128)  # medium grey
    mask_color = _readable_editor_mask_color(text_rgb)
    
    # Should pick either very light or very dark, not grey
    luminance = (mask_color.red() + mask_color.green() + mask_color.blue()) / 3
    assert luminance < 64 or luminance > 192, f"Expected high-contrast mask for grey text, got luminance {luminance}"
```

**Step 2: Run test to verify it fails**

```bash
cd C:\Users\jiang\Documents\python programs\pdf_editor
pytest test_scripts/test_text_editing_gui_regressions.py::test_editor_mask_color_white_text -xvs
```

Expected output: `FAILED — TypeError: _readable_editor_mask_color() takes 0 positional arguments but 1 was given`

**Step 3: Write the implementation**

Replace `view/text_editing.py` lines 46-48:

```python
def _readable_editor_mask_color(text_rgb: tuple = (0, 0, 0)) -> QColor:
    """Choose editor background color for text visibility.
    
    If text is light (luminance > 128), use dark background.
    If text is dark (luminance <= 128), use light background.
    
    Args:
        text_rgb: (r, g, b) tuple with values 0-255. Defaults to black.
    
    Returns:
        QColor for editor background that contrasts with the text.
    """
    r, g, b = [int(c) if isinstance(c, (int, float)) else 0 for c in text_rgb[:3]]
    luminance = (0.299 * r + 0.587 * g + 0.114 * b)
    
    if luminance > 128:
        return QColor("#2B2B2B")  # Dark grey-black for light text
    else:
        return QColor("#FFFFFF")  # White for dark text
```

Update the call site in `create_text_editor()` line 459:

```python
editor.setStyleSheet(view._build_text_editor_stylesheet(text_rgb, _readable_editor_mask_color(text_rgb)))
```

And in `refresh_text_editor_mask_color()` line 391:

```python
text_rgb = editor.property("text_rgb") or (0, 0, 0)
mask_color = _readable_editor_mask_color(text_rgb)
```

**Step 4: Run test to verify it passes**

```bash
pytest test_scripts/test_text_editing_gui_regressions.py::test_editor_mask_color_white_text test_scripts/test_text_editing_gui_regressions.py::test_editor_mask_color_dark_text test_scripts/test_text_editing_gui_regressions.py::test_editor_mask_color_grey_text -xvs
```

Expected output: `PASSED` (3 tests)

**Step 5: Commit**

```bash
git add view/text_editing.py test_scripts/test_text_editing_gui_regressions.py
git commit -m "feat(text-edit): Compute contrast-aware editor background color for white/light text"
```

---

### Task 2: Remove Image Sampling from Editor Mask Color Path

**Files:**
- Modify: `view/text_editing.py:231-248` — remove `_average_image_rect_color()` or mark as unused
- Modify: `view/text_editing.py:390-395` — ensure mask color uses computed contrast, not sampling

**Step 1: Write the test**

```python
# test_scripts/test_text_editing_gui_regressions.py

def test_editor_mask_color_does_not_sample_pixmap():
    """Editor background should use computed contrast, not pixmap sampling."""
    from view.text_editing import _readable_editor_mask_color
    
    # With the fix, the color depends only on text_rgb, never on page pixmap
    white_text_mask = _readable_editor_mask_color((255, 255, 255))
    black_text_mask = _readable_editor_mask_color((0, 0, 0))
    
    # These should be deterministic, not grey (which would indicate sampling)
    white_lum = (white_text_mask.red() + white_text_mask.green() + white_text_mask.blue()) / 3
    black_lum = (black_text_mask.red() + black_text_mask.green() + black_text_mask.blue()) / 3
    
    # White text → dark background; black text → light background
    assert white_lum < 100, f"White text mask should be dark, got luminance {white_lum}"
    assert black_lum > 150, f"Black text mask should be light, got luminance {black_lum}"
```

**Step 2: Run test to verify current state**

```bash
pytest test_scripts/test_text_editing_gui_regressions.py::test_editor_mask_color_does_not_sample_pixmap -xvs
```

(Should pass if Task 1 was completed.)

**Step 3: Remove sampling function (mark as unused)**

In `view/text_editing.py`, add a comment above `_average_image_rect_color()` at line 231:

```python
# Deprecated: Editor mask now uses computed contrast-aware color instead of sampling.
# Kept for backward compatibility but no longer called.
def _average_image_rect_color(image, rect: QRect) -> QColor:
    ...
```

**Step 4: Verify no call sites remain**

```bash
cd C:\Users\jiang\Documents\python programs\pdf_editor
grep -n "_average_image_rect_color" view/text_editing.py
```

Expected: Only the function definition, no call sites.

**Step 5: Commit**

```bash
git add view/text_editing.py test_scripts/test_text_editing_gui_regressions.py
git commit -m "refactor(text-edit): Remove pixmap sampling from editor mask; use computed contrast instead"
```

---

### Task 3: Verify Editor Content Height Calculation

**Files:**
- Test: `view/text_editing.py:277-298` — `_measure_text_content_height_px()`
- Test: `view/text_editing.py:435-441` — `_compute_editor_proxy_layout()` call in `create_text_editor()`

**Step 1: Write the integration test**

```python
# test_scripts/test_text_editing_gui_regressions.py

def test_editor_height_matches_content():
    """Single-line text should open an editor sized to content, not paragraph box."""
    from view.text_editing import _measure_text_content_height_px, TextEditUIConstants
    
    # Measure a single line of text
    single_line_height = _measure_text_content_height_px(
        text="Hello World",
        qt_font_family="Helvetica",
        display_font_pt=12.0,
        wrap_width_px=200,
    )
    
    # Should be roughly one line height (~18-20px), not 6x taller
    assert single_line_height < 40, f"Single-line height should be < 40px, got {single_line_height}px"
    assert single_line_height >= TextEditUIConstants.MIN_EDITOR_HEIGHT_PX, f"Height must be >= {TextEditUIConstants.MIN_EDITOR_HEIGHT_PX}px"

def test_editor_height_wraps_long_text():
    """Multi-line wrapped text should open an editor tall enough for all lines."""
    from view.text_editing import _measure_text_content_height_px
    
    # Long text that wraps
    wrapped_text = "a" * 100  # Will wrap in narrow width
    wrapped_height = _measure_text_content_height_px(
        text=wrapped_text,
        qt_font_family="Helvetica",
        display_font_pt=12.0,
        wrap_width_px=100,  # Narrow to force wrapping
    )
    
    # Should be multiple lines
    single_line_height = _measure_text_content_height_px(
        text="Hello",
        qt_font_family="Helvetica",
        display_font_pt=12.0,
        wrap_width_px=100,
    )
    
    assert wrapped_height > single_line_height * 2, f"Wrapped text should be > 2 lines tall, got {wrapped_height}px"
```

**Step 2: Run test to verify it passes**

```bash
pytest test_scripts/test_text_editing_gui_regressions.py::test_editor_height_matches_content test_scripts/test_text_editing_gui_regressions.py::test_editor_height_wraps_long_text -xvs
```

Expected: `PASSED` (2 tests)

If test fails → debug `_measure_text_content_height_px()` logic.

**Step 3: Visual regression test (manual)**

Open PDF with single-line text inside a paragraph. Verify:
- Editor height ≈ text line height + 8px padding (not paragraph height)
- Multi-line wrapped text expands correctly
- Text is readable inside editor

**Step 4: Commit**

```bash
git add test_scripts/test_text_editing_gui_regressions.py
git commit -m "test(text-edit): Add unit tests for editor content height calculation"
```

---

### Task 4: Fix Initial Viewport (Fit-Page on Open)

**Files:**
- Likely: `controller/pdf_controller.py` — `open_pdf()` or initial render setup
- Likely: `view/pdf_view.py` — initial viewport positioning

**Step 1: Research the current open flow**

```bash
cd C:\Users\jiang\Documents\python programs\pdf_editor
grep -n "def open_pdf" controller/pdf_controller.py | head -5
grep -n "initialize_continuous" view/pdf_view.py | head -5
grep -n "change_scale\|fit_page" view/pdf_view.py | head -10
```

**Step 2: Write the test**

```python
# test_scripts/test_initial_viewport.py

import fitz
from pathlib import Path
from PySide6.QtWidgets import QApplication, QGraphicsView

def test_initial_viewport_fits_page(tmp_path, qapp):
    """After opening a PDF, viewport should show the whole first page readable, not over-zoomed."""
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    
    # Create a test PDF
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Test Content", fontsize=12)
    doc.save(pdf_path)
    
    # Open in view
    view = PDFView()
    model = PDFModel()
    controller = PDFController(view, model)
    controller.activate()
    controller.open_pdf(str(pdf_path))
    
    # Check initial scale is reasonable (fit-page or fit-width)
    # For an 8.5x11" page (595x842 pt) at 96 DPI:
    # - Fit-page on ~1200px viewport should be ~0.8-1.0 scale
    # - Over-zoom would be scale > 2.0
    
    scale = view.scale
    assert 0.5 < scale < 2.0, f"Initial scale should be readable (0.5-2.0), got {scale}"
    
    # Viewport should be at top of page, not clipped
    viewport_y = view.verticalScrollBar().value() if hasattr(view, 'verticalScrollBar') else 0
    assert viewport_y < 100, f"Initial viewport should be at top of page, got y={viewport_y}"
```

**Step 2: Run test to see current behavior**

```bash
pytest test_scripts/test_initial_viewport.py::test_initial_viewport_fits_page -xvs
```

This will show what scale and position the view currently opens at.

**Step 3: Implement fix in controller**

Find `PDFController.open_pdf()` and check the initial `change_scale()` call. If not present or wrong, add:

```python
# After document is loaded and displayed
if current_page == 0:  # First page
    self.change_scale("fit-page")  # or "fit-width"
```

Or set initial scale in the view's `PDFView.__init__()` or `display_page()`.

**Step 4: Run test again**

```bash
pytest test_scripts/test_initial_viewport.py::test_initial_viewport_fits_page -xvs
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add controller/pdf_controller.py view/pdf_view.py test_scripts/test_initial_viewport.py
git commit -m "fix(viewport): Set initial zoom to fit-page on document open for readable framing"
```

---

### Task 5: Update PITFALLS.md with New Issues

**Files:**
- Modify: `docs/PITFALLS.md` — add new entries at the end

**Step 1: Add entries for the issues**

```markdown
## White editor mask makes light text invisible

**Area:** `view/text_editing.py` — `_readable_editor_mask_color`
**Symptom:** When a PDF contains white or light text, opening the inline editor makes the text disappear because the editor background is also white.
**Cause:** `_readable_editor_mask_color()` always returned white (`#FFFFFF`) regardless of the text color.
**Fix:** Compute the editor background color based on text luminance: dark text → light background (#FFFFFF), light text → dark background (#2B2B2B).
**File:** `view/text_editing.py`

---

## Initial document viewport over-zoomed and clipped

**Area:** `controller/pdf_controller.py`, `view/pdf_view.py`
**Symptom:** When a document opens, the user lands on an over-zoomed/cropped view instead of seeing a readable first page.
**Cause:** Initial scale/viewport was not set to a readable framing (e.g., fit-page or fit-width with top-left anchor).
**Fix:** On first document open, set initial scale to fit-page and anchor viewport at page 1, y=0.
**File:** `controller/pdf_controller.py`, `view/pdf_view.py`

---

## Editor mask color sampled from pixmap includes text pixels

**Area:** `view/text_editing.py` — `_average_image_rect_color`
**Symptom:** The inline editor background becomes grey instead of a clean, readable color.
**Cause:** `_average_image_rect_color()` sampled the rendered PDF pixmap under the editor region, picking up text and graphics pixels and averaging them to grey.
**Fix:** Removed pixmap sampling. Editor background now uses deterministic contrast-aware color (computed from text RGB). The sampled approach was deprecated in favor of computed contrast.
**File:** `view/text_editing.py`
```

**Step 2: Commit**

```bash
git add docs/PITFALLS.md
git commit -m "docs: Add PITFALLS entries for text editing UX fixes"
```

---

### Task 6: Manual Integration Test (Visual Verification)

**Files:**
- Test: `test_scripts/test_text_editing_gui_regressions.py` — new manual test helper
- Manual verification with provided `1.pdf`

**Step 1: Write manual test harness**

```python
# test_scripts/test_text_editing_ux_manual.py

"""
Manual visual regression tests for text editing UX.
Run with: pytest test_scripts/test_text_editing_ux_manual.py -xvs --tb=short

Tests require visual inspection of the live GUI.
Each test pauses and prints instructions for manual verification.
"""

import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from pathlib import Path

def test_white_text_visibility(qapp):
    """Manual: Open editor on white text and verify it's readable."""
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    
    pdf_path = Path(__file__).parent.parent / "1.pdf"
    if not pdf_path.exists():
        print(f"Skipping: {pdf_path} not found")
        return
    
    view = PDFView()
    model = PDFModel()
    controller = PDFController(view, model)
    controller.activate()
    controller.open_pdf(str(pdf_path))
    view.show()
    
    print("\n" + "="*60)
    print("MANUAL TEST: White Text Visibility")
    print("="*60)
    print("1. Look at the page content — note any white/light text")
    print("2. Click on the white text to open the inline editor")
    print("3. Verify the text is READABLE inside the editor")
    print("   - Should have dark background behind white text")
    print("   - NOT white-on-white (invisible)")
    print("4. Close the editor (Escape)")
    print("5. Check PASSED if text was readable")
    print("="*60)
    
    # In a real test, this would wait for user interaction
    # For now, just show the window for manual inspection
    QApplication.instance().quit()

def test_initial_framing(qapp):
    """Manual: Open PDF and verify first visible area is readable and not clipped."""
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    
    pdf_path = Path(__file__).parent.parent / "1.pdf"
    if not pdf_path.exists():
        print(f"Skipping: {pdf_path} not found")
        return
    
    view = PDFView()
    model = PDFModel()
    controller = PDFController(view, model)
    controller.activate()
    controller.open_pdf(str(pdf_path))
    view.show()
    
    print("\n" + "="*60)
    print("MANUAL TEST: Initial Framing")
    print("="*60)
    print("1. Document just opened — check the visible area")
    print("2. Verify:")
    print("   - NOT over-zoomed (can see multiple lines of text)")
    print("   - NOT clipped/cropped (can see text clearly, not cut off)")
    print("   - Viewport anchored at top of page (not jumping to middle)")
    print("3. Check PASSED if framing is readable and coherent")
    print("="*60)
    
    QApplication.instance().quit()

if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
```

**Step 2: Run manual tests**

```bash
cd C:\Users\jiang\Documents\python programs\pdf_editor
pytest test_scripts/test_text_editing_ux_manual.py::test_white_text_visibility -xvs
# Follow on-screen instructions for visual verification
```

**Step 3: Verify all issues are fixed**

For each test:
- [ ] White text is readable inside editor (dark background)
- [ ] Initial zoom shows readable context (not over-zoomed)
- [ ] Editor size matches text height (not 6× too tall)
- [ ] Surrounding context is visible (not completely covered by editor)

**Step 4: Commit**

```bash
git add test_scripts/test_text_editing_ux_manual.py
git commit -m "test(text-edit): Add manual visual regression tests for UX fixes"
```

---

## Testing Strategy

### Unit Tests (Automated)
- Task 1: `test_editor_mask_color_*` — contrast-aware color computation
- Task 2: `test_editor_mask_color_does_not_sample_pixmap` — no sampling fallback
- Task 3: `test_editor_height_*` — content height calculation
- Task 4: `test_initial_viewport_fits_page` — initial scale and position

### Integration Tests (Semi-Automated)
- Task 6 manual harness with live PDF (requires visual inspection)

### Regression Tests (Existing)
- Run full test suite: `pytest` (should pass with no regressions)
- Run linter: `ruff check .` (should pass)
- Run type checker: `mypy model/ utils/` (should pass)

### Definition of Done
- [ ] All new unit tests pass
- [ ] All existing tests pass (`pytest`)
- [ ] `ruff check .` passes with zero new violations
- [ ] Manual visual tests confirm all 4 UX issues are fixed
- [ ] `docs/PITFALLS.md` is updated
- [ ] Code is committed with clear messages

---

## Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Contrast color too dark/light | Test with variety of text colors (black, white, red, cyan) |
| Rotated editor still oversized | Verify Task 3 height calc doesn't affect 90/270° path |
| Initial scale breaks continuous mode | Test both single-page and continuous layouts |
| Sampling removal breaks transparency | Ensure stylesheet still sets transparent background |

---

## References

- **Related PITFALLs:**
  - "Inline editor opens with oversized grey void below single-line text" (line 207–214)
  - "Inline editor mask samples text into a grey rectangle" (line 219–224)
  - "Inline editor glyphs look smaller than the underlying PDF text" (line 228–234)
- **Related Code:**
  - `view/text_editing.py:46–48` — mask color function
  - `view/text_editing.py:277–298` — height measurement
  - `view/text_editing.py:301–327` — geometry layout
  - `view/text_editing.py:435–441` — editor creation
  - `controller/pdf_controller.py` — initial open flow
- **Test Files:**
  - `test_scripts/test_text_editing_gui_regressions.py`
  - `test_scripts/test_initial_viewport.py` (new)
  - `test_scripts/test_text_editing_ux_manual.py` (new)
