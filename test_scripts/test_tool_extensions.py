from __future__ import annotations

import fitz
import pytest

from model.pdf_model import PDFModel


@pytest.fixture
def model_with_text_pdf(tmp_path):
    path = tmp_path / "s.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(path))
    doc.close()
    m = PDFModel()
    m.open_pdf(str(path))
    yield m
    m.close_all_sessions()


def test_search_returns_results(model_with_text_pdf):
    results = model_with_text_pdf.tools.search.search_text("hello")
    assert len(results) >= 1
    page_num, context, rect = results[0]
    assert page_num == 1
    assert "hello" in context.lower()


def test_search_empty_returns_empty(model_with_text_pdf):
    assert model_with_text_pdf.tools.search.search_text("xyzzy_no_match") == []


def test_search_no_doc_returns_empty():
    assert PDFModel().tools.search.search_text("anything") == []


def test_ocr_no_doc_returns_empty():
    assert PDFModel().tools.ocr.ocr_pages([1]) == {}


def test_ocr_invalid_page_raises(model_with_text_pdf):
    with pytest.raises((ValueError, RuntimeError)):
        model_with_text_pdf.tools.ocr.ocr_pages([999])
