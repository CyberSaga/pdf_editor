from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402
import pytest  # noqa: E402

from model.pdf_model import PDFModel  # noqa: E402


def _make_pdf(path: Path, *, pages: int = 3) -> None:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=200)
    doc.save(path)
    doc.close()


def _make_labeled_pdf(path: Path, *, pages: int = 5) -> None:
    """Create a PDF with page labels: i, ii, iii for pages 0-2, then 1, 2 for pages 3-4."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=200)
    doc.set_page_labels(
        [
            {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
            {"startpage": 3, "prefix": "", "style": "D", "firstpagenum": 1},
        ]
    )
    doc.save(path)
    doc.close()


class TestGetPageLabel:
    def test_returns_document_label(self, tmp_path: Path) -> None:
        pdf = tmp_path / "labeled.pdf"
        _make_labeled_pdf(pdf)
        model = PDFModel()
        model.open_pdf(str(pdf))
        try:
            assert model.get_page_label(1) == "i"
            assert model.get_page_label(2) == "ii"
            assert model.get_page_label(3) == "iii"
            assert model.get_page_label(4) == "1"
            assert model.get_page_label(5) == "2"
        finally:
            model.close()

    def test_fallback_when_no_labels_defined(self, tmp_path: Path) -> None:
        pdf = tmp_path / "plain.pdf"
        _make_pdf(pdf)
        model = PDFModel()
        model.open_pdf(str(pdf))
        try:
            assert model.get_page_label(1) == "1"
            assert model.get_page_label(2) == "2"
            assert model.get_page_label(3) == "3"
        finally:
            model.close()

    def test_page_zero_raises(self, tmp_path: Path) -> None:
        pdf = tmp_path / "plain.pdf"
        _make_pdf(pdf)
        model = PDFModel()
        model.open_pdf(str(pdf))
        try:
            with pytest.raises(ValueError):
                model.get_page_label(0)
        finally:
            model.close()

    def test_negative_page_raises(self, tmp_path: Path) -> None:
        pdf = tmp_path / "plain.pdf"
        _make_pdf(pdf)
        model = PDFModel()
        model.open_pdf(str(pdf))
        try:
            with pytest.raises(ValueError):
                model.get_page_label(-1)
        finally:
            model.close()

    def test_page_beyond_count_raises(self, tmp_path: Path) -> None:
        pdf = tmp_path / "plain.pdf"
        _make_pdf(pdf, pages=3)
        model = PDFModel()
        model.open_pdf(str(pdf))
        try:
            with pytest.raises(ValueError):
                model.get_page_label(4)
        finally:
            model.close()

    def test_no_document_raises(self) -> None:
        model = PDFModel()
        with pytest.raises(ValueError):
            model.get_page_label(1)
