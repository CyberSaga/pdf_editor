from __future__ import annotations

from pathlib import Path

import fitz
import pytest


def _resolve_fixture_pdf() -> Path:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "test_files" / "2.pdf",
        root / "test_files" / "test-horizontal-texts.pdf",
        root / "test_files" / "test-colored-background.pdf",
    ]
    for path in candidates:
        if path.exists():
            return path
    pytest.skip("no render-colorspace fixture PDF available")


def test_tool_manager_render_page_pixmap_accepts_colorspace() -> None:
    from model.pdf_model import PDFModel

    pdf_path = _resolve_fixture_pdf()

    model = PDFModel()
    model.open_pdf(str(pdf_path))

    gray_pix = model.tools.render_page_pixmap(
        page_num=1,
        scale=1.0,
        annots=False,
        purpose="view",
        colorspace=fitz.csGRAY,
    )
    assert gray_pix.colorspace is not None
    assert gray_pix.colorspace.n == 1

    rgb_pix = model.tools.render_page_pixmap(page_num=1, scale=1.0, annots=False, purpose="view")
    assert rgb_pix.colorspace is not None
    assert rgb_pix.colorspace.n == 3


def test_pdf_model_render_entry_points_forward_colorspace() -> None:
    from model.pdf_model import PDFModel

    pdf_path = _resolve_fixture_pdf()

    model = PDFModel()
    model.open_pdf(str(pdf_path))

    page_pix = model.get_page_pixmap(page_num=1, scale=1.0, colorspace=fitz.csCMYK)
    assert page_pix.colorspace is not None
    assert page_pix.colorspace.n == 4

    thumb = model.get_thumbnail(page_num=1, colorspace=fitz.csCMYK)
    assert thumb.colorspace is not None
    assert thumb.colorspace.n == 4

    snap = model.get_page_snapshot(page_num=1, scale=1.0, colorspace=fitz.csCMYK)
    assert snap.colorspace is not None
    assert snap.colorspace.n == 4
