"""Phase 6 — the inline text editor must have zero effective padding even when
the application-level theme QSS is active (theme.py applies
`QTextEdit { padding: 4px 8px; }` globally).
"""

from __future__ import annotations

from PySide6.QtGui import QColor

from utils.render_limits import _MAX_PIXMAP_PX, safe_render_scale


def test_build_text_editor_stylesheet_includes_zero_padding(qapp):
    """_build_text_editor_stylesheet must include padding:0px and margin:0px
    so the theme rule cannot cascade back and shift glyphs."""
    from view.pdf_view import PDFView

    view = PDFView.__new__(PDFView)
    css = view._build_text_editor_stylesheet((0, 0, 0), QColor(255, 255, 255))

    assert "padding: 0px" in css, f"missing padding:0px in stylesheet: {css}"
    assert "margin: 0px" in css, f"missing margin:0px in stylesheet: {css}"


def test_safe_render_scale_clamps_pathological_page():
    """A pathologically large page must be clamped so the pixmap is within budget."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=10_000, height=10_000)
    clamped = safe_render_scale(page, 2.0)
    resulting_px = page.rect.width * page.rect.height * clamped * clamped
    assert resulting_px <= _MAX_PIXMAP_PX * 1.01, (
        f"clamped scale {clamped} produces {resulting_px:.0f} pixels, exceeds {_MAX_PIXMAP_PX}"
    )
    doc.close()


def test_safe_render_scale_leaves_normal_page():
    """A normal A4 page at 2x should pass through unclamped."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    assert safe_render_scale(page, 2.0) == 2.0
    doc.close()
