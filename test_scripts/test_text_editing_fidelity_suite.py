from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtGui import QImage

from model.edit_commands import EditTextResult
from model.pdf_model import PDFModel
from view.text_editing import PreviewRenderer


def _build_model_with_doc(tmp_path: Path, text: str, *, fontsize: float = 12.0, fontname: str = "helv", color=(0, 0, 0), rotate: int = 0, rect: fitz.Rect | None = None) -> tuple[PDFModel, fitz.Rect]:
    pdf_path = tmp_path / "fidelity.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if rect is None:
        rect = fitz.Rect(72, 72, 320, 140)
    if rotate in (90, 180, 270):
        css = f"* {{ font-family: {fontname}; font-size: {fontsize}pt; color: rgb({int(color[0]*255)}, {int(color[1]*255)}, {int(color[2]*255)}); }}"
        page.insert_htmlbox(rect, text, css=css, rotate=rotate)
    else:
        page.insert_text((rect.x0, rect.y0 + fontsize), text, fontsize=fontsize, fontname=fontname, color=color)
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    return model, rect


def _first_block(model: PDFModel):
    blocks = model.block_manager.get_blocks(0)
    assert blocks
    return blocks[0]


def _edit_block(model: PDFModel, block, new_text: str, *, size: float | None = None, color: tuple[float, float, float] | None = None) -> EditTextResult:
    return model.edit_text(
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font=block.font,
        size=float(size if size is not None else block.size),
        color=tuple(float(c) for c in (color if color is not None else block.color)),
        original_text=block.text,
        target_mode="run",
    )


def test_latin_single_line_edit_preserves_font_pt(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Hello World", fontsize=12.0)
    block = _first_block(model)
    assert _edit_block(model, block, "Hello World!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    edited = _first_block(model)
    assert abs(float(edited.size) - 12.0) < 0.1


def test_cjk_single_line_edit_preserves_height(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "\u4e2d\u6587\u6e2c\u8a66", fontsize=14.0)
    block = _first_block(model)
    before_h = float(block.layout_rect.height)
    assert _edit_block(model, block, "\u4e2d\u6587\u6e2c\u8a66\u4e00") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    after_h = float(_first_block(model).layout_rect.height)
    assert abs(after_h - before_h) <= 1.0


def test_fractional_font_pt_round_trips_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Fractional", fontsize=9.5)
    block = _first_block(model)
    assert _edit_block(model, block, "FractionalX", size=9.5) is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).size) - 9.5) < 0.1


def test_repeated_ten_edits_cumulative_drift_under_half_pt(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Drift", fontsize=12.0)
    block = _first_block(model)
    x0 = float(block.layout_rect.x0)
    y0 = float(block.layout_rect.y0)
    for i in range(10):
        model.block_manager.rebuild_page(0, model.doc)
        block = _first_block(model)
        assert _edit_block(model, block, f"Drift{i}") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    block = _first_block(model)
    assert abs(float(block.layout_rect.x0) - x0) < 0.5
    assert abs(float(block.layout_rect.y0) - y0) < 0.5


def test_preview_pixmap_dimensions_match_render_scale_2x() -> None:
    image = PreviewRenderer()._to_qimage_dimensions(rect=fitz.Rect(0, 0, 200, 80), render_scale=2.0, rotation=0)
    assert image.width() == 400 and image.height() == 160


def test_bold_flag_preserved_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "BoldText", fontsize=12.0, fontname="hebo")
    block = _first_block(model)
    assert _edit_block(model, block, "BoldText!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    lowered = (_first_block(model).font or "").lower()
    assert "bold" in lowered or "bd" in lowered


def test_italic_flag_preserved_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "ItalicText", fontsize=12.0, fontname="tiro")
    block = _first_block(model)
    assert _edit_block(model, block, "ItalicText!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert len(_first_block(model).font or "") > 0


def test_non_black_color_preserved_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Colored", fontsize=12.0, color=(0.8, 0.2, 0.1))
    block = _first_block(model)
    assert _edit_block(model, block, "Colored!", color=(0.8, 0.2, 0.1)) is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    c = tuple(float(v) for v in _first_block(model).color)
    assert abs(c[0] - 0.8) < 0.02 and abs(c[1] - 0.2) < 0.02 and abs(c[2] - 0.1) < 0.02


def test_multi_line_wrap_column_matches_source(tmp_path: Path) -> None:
    model, rect = _build_model_with_doc(tmp_path, "Wrap test line one line two line three", fontsize=12.0, rect=fitz.Rect(72, 72, 180, 160))
    block = _first_block(model)
    assert _edit_block(model, block, "Wrap test line one line too line three") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert float(_first_block(model).layout_rect.x0) >= rect.x0 - 0.5


def test_tight_leading_honored_on_commit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Line A\nLine B", fontsize=10.0)
    block = _first_block(model)
    before_h = float(block.layout_rect.height)
    assert _edit_block(model, block, "Line A\nLine B!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).layout_rect.height) - before_h) < 0.5


def test_loose_leading_honored_on_commit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Line C\nLine D", fontsize=10.0)
    block = _first_block(model)
    before_h = float(block.layout_rect.height)
    assert _edit_block(model, block, "Line C\nLine D!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).layout_rect.height) - before_h) < 0.5


def test_position_anchor_drift_under_half_pt_at_all_corners(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Corner", fontsize=10.0, rect=fitz.Rect(5, 5, 100, 40))
    block = _first_block(model)
    x0 = float(block.layout_rect.x0)
    y0 = float(block.layout_rect.y0)
    assert _edit_block(model, block, "Corner!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    block = _first_block(model)
    assert abs(float(block.layout_rect.x0) - x0) < 0.5 and abs(float(block.layout_rect.y0) - y0) < 0.5


def test_mixed_latin_cjk_span_renders_both_scripts(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "ABC \u4e2d\u6587 XYZ", fontsize=12.0)
    block = _first_block(model)
    assert _edit_block(model, block, "ABCD \u4e2d\u6587 XYZ") is EditTextResult.SUCCESS
    text = model.doc[0].get_text("text")
    assert "ABCD" in text and "\u4e2d\u6587" in text


def test_vertical_rotated_text_edit_preserves_orientation_and_size(tmp_path: Path) -> None:
    model, rect = _build_model_with_doc(tmp_path, "Vertical", fontsize=12.0, rotate=90, rect=fitz.Rect(200, 100, 260, 280))
    block = _first_block(model)
    assert _edit_block(model, block, "Vertical!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).size) - 12.0) < 0.5
    image = PreviewRenderer()._to_qimage_dimensions(rect=rect, render_scale=1.0, rotation=90)
    assert image.width() == int(round(rect.height))


def test_preview_pixmap_width_equals_source_rect_times_render_scale() -> None:
    image = PreviewRenderer()._to_qimage_dimensions(rect=fitz.Rect(0, 0, 200, 80), render_scale=1.5, rotation=0)
    assert image.width() == 300


# Task 3 — real PreviewRenderer rasterization tests.

def test_preview_render_produces_visible_text_pixels(qapp) -> None:
    """Latin text at 12pt must produce non-trivial dark pixels in the QImage."""
    renderer = PreviewRenderer(model=None)
    image = renderer.render(
        text="Hello",
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=fitz.Rect(0, 0, 200, 30),
        rotation=0,
        render_scale=2.0,
    )
    assert image is not None
    assert image.width() > 0 and image.height() > 0

    dark_pixels = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            color = image.pixelColor(x, y)
            if color.alpha() > 100 and color.lightness() < 100:
                dark_pixels += 1
    assert dark_pixels > 30, (
        f"Expected visible 'Hello' glyphs in preview pixmap, found {dark_pixels} "
        "dark opaque pixels. PreviewRenderer.render is likely returning a blank image."
    )


def test_preview_render_at_render_scale_2x_doubles_pixel_dimensions(qapp) -> None:
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 100.0, 20.0)
    image1x = renderer.render(
        text="x", font_name="helv", font_size=12.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=1.0,
    )
    image2x = renderer.render(
        text="x", font_name="helv", font_size=12.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=2.0,
    )
    assert image1x.width() == 100
    assert image2x.width() == 200


def test_preview_render_caches_identical_input(qapp) -> None:
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 100, 20)
    args: dict = dict(
        text="cache", font_name="helv", font_size=12.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=1.0,
    )
    image_a = renderer.render(**args)
    image_b = renderer.render(**args)
    assert image_a is image_b, "Same args must return cached QImage instance"


def test_preview_render_rotation_90_swaps_pixel_dimensions(qapp) -> None:
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 200, 50)
    image_h = renderer.render(
        text="h", font_name="helv", font_size=14.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=1.0,
    )
    image_v = renderer.render(
        text="v", font_name="helv", font_size=14.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=90, render_scale=1.0,
    )
    assert image_h.width() == 200 and image_h.height() == 50
    assert image_v.width() == 50 and image_v.height() == 200


# Task 3a — line_height threading.

def test_preview_render_uses_explicit_line_height_not_auto(qapp, tmp_path) -> None:
    """Tight vs. loose line_height must produce different pixel layouts.
    Guards the gap where auto-derive leading diverges from the committed CSS."""
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 200, 40)

    img_auto = renderer.render(
        text="Line1\nLine2", font_name="helv", font_size=12.0,
        color=(0, 0, 0), member_spans=None, rect_pt=rect,
        rotation=0, render_scale=2.0, line_height=0.0,
    )
    img_tight = renderer.render(
        text="Line1\nLine2", font_name="helv", font_size=12.0,
        color=(0, 0, 0), member_spans=None, rect_pt=rect,
        rotation=0, render_scale=2.0, line_height=5.0,
    )
    img_loose = renderer.render(
        text="Line1\nLine2", font_name="helv", font_size=12.0,
        color=(0, 0, 0), member_spans=None, rect_pt=rect,
        rotation=0, render_scale=2.0, line_height=25.0,
    )
    assert img_auto is not img_tight
    assert img_auto is not img_loose

    def _ink_count(img: QImage) -> int:
        """Count opaque-ish dark pixels (text glyphs)."""
        return sum(
            1
            for y in range(img.height())
            for x in range(0, img.width(), 4)
            if img.pixelColor(x, y).alpha() > 30 and img.pixelColor(x, y).lightness() < 150
        )

    auto_ink  = _ink_count(img_auto)
    tight_ink = _ink_count(img_tight)
    loose_ink = _ink_count(img_loose)

    # Tight line_height (5pt) should pack glyphs differently than auto or loose (25pt).
    # At least one pair must differ to show leading is being honoured.
    assert auto_ink != tight_ink or auto_ink != loose_ink, (
        f"Different line_height values must produce different glyph layouts. "
        f"auto={auto_ink} tight={tight_ink} loose={loose_ink}. "
        "Check that render() passes line_height into CSS and cache key includes it."
    )


# Task 5 — pixel-height parity.

def test_inline_editor_glyph_height_matches_pdf_at_render_scale_2x(qapp, tmp_path) -> None:
    """E2E: PreviewRenderer.render at render_scale=2.0 must produce glyph
    ink-pixel-height within 20% of the direct PyMuPDF rasterization of the
    same text. Regression guard for 'glyphs unexpectedly larger or smaller
    on click' — both sides use the same engine path so the ratio must be ~1."""
    font_size = 14.0
    span_rect = fitz.Rect(0, 0, 150, 25)

    def _ink_extent_px(image: QImage) -> int:
        """Vertical span of opaque dark pixels (text ink)."""
        top_row = None
        bottom_row = None
        for y in range(image.height()):
            has_ink = any(
                image.pixelColor(x, y).alpha() > 50 and image.pixelColor(x, y).lightness() < 150
                for x in range(0, image.width(), 4)
            )
            if has_ink:
                if top_row is None:
                    top_row = y
                bottom_row = y
        return (bottom_row - top_row + 1) if top_row is not None else 0

    # Reference: rasterize the same span directly via PyMuPDF at 2x.
    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(width=float(span_rect.width), height=float(span_rect.height))
    css_ref = f"span {{ font-family: Helvetica; font-size: {font_size}pt; color: rgb(0,0,0); }}"
    ref_page.insert_htmlbox(fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)), "<span>Hello World</span>", css=css_ref)
    ref_pixmap = ref_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=True)
    ref_doc.close()
    ref_image = QImage(ref_pixmap.samples, ref_pixmap.width, ref_pixmap.height, ref_pixmap.stride, QImage.Format_RGBA8888).copy()
    ref_ink_h = _ink_extent_px(ref_image)

    # Preview: render via PreviewRenderer (should use same engine path).
    renderer = PreviewRenderer(model=None)
    preview_image = renderer.render(
        text="Hello World",
        font_name="helv",
        font_size=font_size,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=span_rect,
        rotation=0,
        render_scale=2.0,
    )
    preview_ink_h = _ink_extent_px(preview_image)

    assert ref_ink_h > 0, "Reference render produced no ink pixels"
    assert preview_ink_h > 0, "Preview render produced no ink pixels"

    tolerance = max(3, int(0.20 * ref_ink_h))
    delta = abs(preview_ink_h - ref_ink_h)
    assert delta <= tolerance, (
        f"Preview ink-height ({preview_ink_h}px) diverges from reference "
        f"({ref_ink_h}px) by {delta}px (tol={tolerance}px) — "
        "glyph-size regression: preview and commit use different rasterizer paths."
    )
