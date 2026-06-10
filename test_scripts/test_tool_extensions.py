from __future__ import annotations

import math

import fitz
import pytest

from model import pdf_model as pdf_model_module
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


def test_add_highlight_rejects_page_zero(model_with_text_pdf):
    # Phase 2.4: page 0 must raise, not silently resolve doc[-1] (last page).
    rect = fitz.Rect(10, 10, 50, 30)
    with pytest.raises(ValueError):
        model_with_text_pdf.tools.annotation.add_highlight(0, rect, (1.0, 1.0, 0.0, 0.5))
    assert len(list(model_with_text_pdf.doc[0].annots())) == 0  # no silent annotation


def test_add_rect_rejects_page_zero(model_with_text_pdf):
    rect = fitz.Rect(10, 10, 50, 30)
    with pytest.raises(ValueError):
        model_with_text_pdf.tools.annotation.add_rect(0, rect, (1.0, 0.0, 0.0, 0.5), fill=False)
    assert len(list(model_with_text_pdf.doc[0].annots())) == 0


def test_add_highlight_rejects_out_of_range(model_with_text_pdf):
    rect = fitz.Rect(10, 10, 50, 30)
    with pytest.raises(ValueError):
        model_with_text_pdf.tools.annotation.add_highlight(999, rect, (1.0, 1.0, 0.0, 0.5))


def test_add_watermark_nan_angle_sanitized(model_with_text_pdf):
    # Phase 2.5: add_watermark must funnel through _coerce_wm so a NaN angle is
    # stored as the finite default instead of poisoning later rendering math.
    wm_id = model_with_text_pdf.tools.watermark.add_watermark([1], "DRAFT", angle=float("nan"))
    stored = next(
        wm for wm in model_with_text_pdf.tools.watermark.get_watermarks() if wm["id"] == wm_id
    )
    assert math.isfinite(stored["angle"])
    assert stored["angle"] == 0.0


def test_rawdict_text_compat_backfills_keyword_option(monkeypatch):
    sentinel = "_pdf_editor_rawdict_text_compat"

    def fake_get_text(page, option="text", *args, **kwargs):
        selected_option = kwargs.get("option", option)
        if selected_option != "rawdict":
            return "plain text"
        return {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "chars": [
                                        {"c": "H"},
                                        {"c": "i"},
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(fitz.Page, sentinel, False, raising=False)
    monkeypatch.setattr(fitz.Page, "get_text", fake_get_text)
    pdf_model_module._install_rawdict_text_compat()

    doc = fitz.open()
    try:
        page = doc.new_page()
        rawdict = page.get_text(option="rawdict")
    finally:
        doc.close()

    span = rawdict["blocks"][0]["lines"][0]["spans"][0]
    assert span["text"] == "Hi"


def test_close_all_sessions_tolerates_new_bypass_instance():
    model = PDFModel.__new__(PDFModel)

    model.close_all_sessions()
    model.__del__()
