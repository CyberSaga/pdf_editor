from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from src.printing.pdf_renderer import PDFRenderer
from utils.helpers import pixmap_to_qpixmap


def _make_single_page_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    page.insert_text((20, 40), "colorspace regression", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_pixmap_to_qpixmap_bridges_gray_and_cmyk(qapp) -> None:
    _ = qapp
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]

            gray_pix = page.get_pixmap(colorspace=fitz.csGRAY, alpha=False)
            gray_qpix = pixmap_to_qpixmap(gray_pix)
            assert gray_qpix.width() == gray_pix.width
            assert gray_qpix.height() == gray_pix.height

            cmyk_pix = page.get_pixmap(colorspace=fitz.csCMYK, alpha=False)
            cmyk_qpix = pixmap_to_qpixmap(cmyk_pix)
            assert cmyk_qpix.width() == cmyk_pix.width
            assert cmyk_qpix.height() == cmyk_pix.height
        finally:
            doc.close()


def test_pdf_renderer_grayscale_output_matches_rgb_dimensions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)

        rgb = PDFRenderer(colorspace=fitz.csRGB)
        gray = PDFRenderer(colorspace=fitz.csGRAY)

        rgb_page = next(rgb.iter_page_images(str(pdf_path), [0], dpi=96))
        gray_page = next(gray.iter_page_images(str(pdf_path), [0], dpi=96))

        assert gray_page.image.width() == rgb_page.image.width()
        assert gray_page.image.height() == rgb_page.image.height()

