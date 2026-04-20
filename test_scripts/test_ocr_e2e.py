"""End-to-end OCR smoke test using real PDFs and the actual Surya backend.

Requires: surya-ocr and torch installed.
Run: python -m pytest test_scripts/test_ocr_e2e.py -v -s
"""
from __future__ import annotations

import os
import sys
import pathlib
import pytest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = ROOT / "test_files" / "testOCR"
PDFS = {
    "english": TEST_DIR / "Engineering_Handover_Blueprint.pdf",
    "chinese": TEST_DIR / "機電O_M竣工資料要求_可重複使用規範_詳細教案.pdf",
}


def _surya_available() -> bool:
    try:
        import surya  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _surya_available(), reason="surya-ocr not installed"
)


@pytest.fixture(scope="module")
def eng_model():
    from model.pdf_model import PDFModel
    m = PDFModel()
    m.open_pdf(str(PDFS["english"]))
    return m


@pytest.fixture(scope="module")
def cjk_model():
    from model.pdf_model import PDFModel
    m = PDFModel()
    m.open_pdf(str(PDFS["chinese"]))
    return m


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def test_ocr_availability_reports_available():
    """OcrTool.availability() returns available=True when surya is installed."""
    from model.pdf_model import PDFModel
    from model.tools.ocr_tool import OcrTool

    model = PDFModel()
    model.open_pdf(str(PDFS["english"]))
    tool = OcrTool(model)
    avail = tool.availability()
    assert avail.available, f"Expected available but got: {avail.reason}"


# ---------------------------------------------------------------------------
# English PDF
# ---------------------------------------------------------------------------

def test_english_pdf_page1_returns_spans(eng_model):
    """OCR page 1 of the English PDF produces at least some text spans."""
    from model.tools.ocr_tool import OcrTool

    tool = OcrTool(eng_model)
    results = tool.ocr_pages([1], languages=["en"])
    assert 1 in results, "No result for page 1"
    spans = results[1]
    assert len(spans) > 0, "Zero spans on English page 1"
    print(f"\n[eng p1] {len(spans)} spans, sample texts:")
    for span in spans[:5]:
        print(f"  conf={span.confidence:.2f}  text={span.text!r}")


def test_english_spans_have_valid_bboxes(eng_model):
    """All spans have 4-coordinate bboxes within plausible page dimensions."""
    from model.tools.ocr_tool import OcrTool

    tool = OcrTool(eng_model)
    results = tool.ocr_pages([1], languages=["en"])
    spans = results.get(1, [])
    assert spans, "No spans returned"
    for span in spans:
        x0, y0, x1, y1 = span.bbox
        assert x1 > x0, f"Invalid x range: {span.bbox}"
        assert y1 > y0, f"Invalid y range: {span.bbox}"
        assert x0 >= 0 and y0 >= 0, f"Negative coords: {span.bbox}"


def test_english_spans_have_text(eng_model):
    """All returned spans have non-empty text."""
    from model.tools.ocr_tool import OcrTool

    tool = OcrTool(eng_model)
    results = tool.ocr_pages([1], languages=["en"])
    spans = results.get(1, [])
    for span in spans:
        assert span.text.strip(), f"Empty text span: {span}"


def test_english_spans_confidence_range(eng_model):
    """Confidence scores are in [0, 1]."""
    from model.tools.ocr_tool import OcrTool

    tool = OcrTool(eng_model)
    results = tool.ocr_pages([1], languages=["en"])
    spans = results.get(1, [])
    assert spans
    for span in spans:
        assert 0.0 <= span.confidence <= 1.0, f"Out of range confidence: {span.confidence}"


# ---------------------------------------------------------------------------
# Chinese PDF
# ---------------------------------------------------------------------------

def test_chinese_pdf_page1_returns_spans(cjk_model):
    """OCR page 1 of the CJK PDF produces spans."""
    from model.tools.ocr_tool import OcrTool

    tool = OcrTool(cjk_model)
    results = tool.ocr_pages([1], languages=["zh-Hant"])
    assert 1 in results
    spans = results[1]
    assert len(spans) > 0, "Zero spans on Chinese page 1"
    print(f"\n[cjk p1] {len(spans)} spans, sample texts:")
    for span in spans[:5]:
        print(f"  conf={span.confidence:.2f}  text={span.text!r}")


# ---------------------------------------------------------------------------
# Model insertion (apply_ocr_spans)
# ---------------------------------------------------------------------------

def test_apply_ocr_spans_inserts_invisible_text():
    """apply_ocr_spans writes render_mode=3 text into the PDF page."""
    from model.pdf_model import PDFModel
    from model.tools.ocr_tool import OcrTool

    model = PDFModel()
    model.open_pdf(str(PDFS["english"]))
    tool = OcrTool(model)

    results = tool.ocr_pages([1], languages=["en"])
    spans = results.get(1, [])
    assert spans, "No spans to insert"

    count = model.apply_ocr_spans(1, spans)
    assert count > 0, "apply_ocr_spans returned 0 insertions"

    page = model.doc[0]
    text = page.get_text("text")
    assert text.strip(), "Page has no extractable text after OCR insertion"
    print(f"\n[eng p1 insert] inserted={count}, extracted text snippet: {text[:200]!r}")


def test_apply_ocr_spans_page_marked_dirty():
    """After OCR insertion the model records a pending edit for that page."""
    from model.pdf_model import PDFModel
    from model.tools.ocr_tool import OcrTool

    model = PDFModel()
    model.open_pdf(str(PDFS["english"]))
    tool = OcrTool(model)

    pre_edits = model.edit_count
    results = tool.ocr_pages([1], languages=["en"])
    model.apply_ocr_spans(1, results.get(1, []))
    assert model.edit_count > pre_edits, "edit_count not incremented after OCR insert"
    assert any(e["page_idx"] == 0 for e in model.pending_edits), "Page 0 not in pending_edits"
