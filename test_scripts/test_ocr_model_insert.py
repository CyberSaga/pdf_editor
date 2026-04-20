from __future__ import annotations

import hashlib

import fitz
import pytest

from model.pdf_model import PDFModel
from model.tools.ocr_types import OcrSpan


def _pixmap_hash(page: fitz.Page, scale: float = 1.5) -> str:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), annots=False)
    return hashlib.sha1(pix.samples).hexdigest()


def _pixmap_distance(a: fitz.Pixmap, b: fitz.Pixmap) -> float:
    """Mean absolute difference per pixel across all channels, in [0, 255]."""
    assert a.width == b.width and a.height == b.height and a.n == b.n
    buf_a = a.samples
    buf_b = b.samples
    diff = 0
    length = len(buf_a)
    for i in range(0, length, 97):  # sparse sample — good enough for tolerance check
        diff += abs(buf_a[i] - buf_b[i])
    samples = (length + 96) // 97
    return diff / samples if samples else 0.0


def _scanlike_pdf(tmp_path) -> str:
    """Produce a page whose content is a raster shape (no text at all)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(40, 40, 360, 120), color=(0.85, 0.85, 0.85), fill=(0.85, 0.85, 0.85))
    page.draw_rect(fitz.Rect(40, 140, 360, 220), color=(0.7, 0.7, 0.7), fill=(0.7, 0.7, 0.7))
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def model_with_scan(tmp_path) -> PDFModel:
    path = _scanlike_pdf(tmp_path)
    model = PDFModel()
    model.open_pdf(path)
    return model


def test_apply_ocr_spans_inserts_searchable_text(model_with_scan):
    page = model_with_scan.doc[0]
    assert "hello world" not in page.get_text()

    count = model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="hello world", confidence=0.99)],
    )
    assert count == 1
    assert "hello world" in page.get_text().lower()


def test_apply_ocr_spans_locates_text_via_search_for(model_with_scan):
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="invoice", confidence=0.92)],
    )
    page = model_with_scan.doc[0]
    hits = page.search_for("invoice")
    assert len(hits) >= 1


def test_apply_ocr_spans_keeps_render_visually_unchanged(model_with_scan):
    page = model_with_scan.doc[0]
    before = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), annots=False)

    model_with_scan.apply_ocr_spans(
        1,
        [
            OcrSpan(bbox=(50.0, 50.0, 310.0, 110.0), text="sample one", confidence=0.9),
            OcrSpan(bbox=(50.0, 150.0, 310.0, 210.0), text="sample two", confidence=0.9),
        ],
    )
    after = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), annots=False)
    # Render-mode 3 text emits no glyphs to the page content, so pixel output must match.
    mean_diff = _pixmap_distance(before, after)
    assert mean_diff < 1.0, f"page pixels changed unexpectedly: mean diff={mean_diff}"


def test_apply_ocr_spans_handles_cjk_text(model_with_scan):
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="測試文字", confidence=0.85)],
    )
    page = model_with_scan.doc[0]
    hits = page.search_for("測試")
    assert len(hits) >= 1


def test_apply_ocr_spans_handles_japanese_text(model_with_scan):
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 150.0, 250.0, 190.0), text="こんにちは", confidence=0.8)],
    )
    page = model_with_scan.doc[0]
    hits = page.search_for("こんにちは")
    assert len(hits) >= 1


def test_apply_ocr_spans_skips_empty_text(model_with_scan):
    count = model_with_scan.apply_ocr_spans(
        1,
        [
            OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="", confidence=0.5),
            OcrSpan(bbox=(50.0, 100.0, 200.0, 130.0), text="   ", confidence=0.5),
        ],
    )
    assert count == 0


def test_apply_ocr_spans_increments_edit_count(model_with_scan):
    baseline = model_with_scan.edit_count
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="foo", confidence=0.9)],
    )
    assert model_with_scan.edit_count == baseline + 1


def test_apply_ocr_spans_rebuilds_block_index(model_with_scan):
    # Force the page index into 'stale' before OCR.
    model_with_scan.block_manager._page_state[0] = "stale"
    assert model_with_scan.block_manager.page_state(0) == "stale"
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="bar", confidence=0.9)],
    )
    assert model_with_scan.block_manager.page_state(0) != "stale"


def test_apply_ocr_spans_rejects_invalid_page(model_with_scan):
    with pytest.raises(ValueError):
        model_with_scan.apply_ocr_spans(
            0,
            [OcrSpan(bbox=(0, 0, 10, 10), text="x", confidence=0.5)],
        )
    with pytest.raises(ValueError):
        model_with_scan.apply_ocr_spans(
            99,
            [OcrSpan(bbox=(0, 0, 10, 10), text="x", confidence=0.5)],
        )


def test_apply_ocr_spans_without_doc_returns_zero():
    model = PDFModel()
    result = model.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(0, 0, 10, 10), text="x", confidence=0.5)],
    )
    assert result == 0


def test_pixmap_hash_helper():
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    h1 = _pixmap_hash(page)
    page.draw_rect(fitz.Rect(0, 0, 100, 100), fill=(0.5, 0.5, 0.5))
    h2 = _pixmap_hash(page)
    assert h1 != h2
    doc.close()
