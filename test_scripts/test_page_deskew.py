"""Page straightening (deskew).

Mission: 拉正頁面. Detect a page's skew angle (projection-profile method) and
rotate the page to level it. Used mainly for scanned/photographed pages, so the
straightened page is rasterized.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_model import PDFModel  # noqa: E402

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def _skewed_lines_pdf(path: Path, skew_deg: float) -> None:
    """Build a 1-page PDF whose horizontal text rows are tilted by skew_deg."""
    # Clean image with evenly spaced horizontal bars (strong row structure).
    w, h = 800, 1000
    img = Image.new("L", (w, h), color=255)
    draw = ImageDraw.Draw(img)
    for y in range(80, h - 80, 40):
        draw.rectangle([80, y, w - 80, y + 12], fill=0)
    # Tilt the whole sheet by skew_deg (positive => counter-clockwise).
    skewed = img.rotate(skew_deg, resample=Image.BICUBIC, expand=False, fillcolor=255)
    import io

    buf = io.BytesIO()
    skewed.convert("RGB").save(buf, format="PNG")
    png = buf.getvalue()

    doc = fitz.open()
    page = doc.new_page(width=float(w) * 0.75, height=float(h) * 0.75)
    page.insert_image(page.rect, stream=png)
    doc.save(path)
    doc.close()


def test_detect_page_skew_recovers_known_angle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skewed.pdf"
        # Skew the sheet clockwise by 6 degrees (rotate -6).
        _skewed_lines_pdf(path, -6.0)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            detected = model.detect_page_skew(1)
            # The corrective angle should be about +6 to undo the -6 skew.
            assert abs(detected - 6.0) <= 1.5, f"detected skew {detected} not ~6.0"
        finally:
            model.close()


def test_straighten_page_keeps_size_and_page_count() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skewed.pdf"
        _skewed_lines_pdf(path, -6.0)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            before_rect = fitz.Rect(model.doc[0].rect)
            ok = model.straighten_page(1, angle_degrees=6.0)
            assert ok is True
            assert model.doc.page_count == 1
            after_rect = fitz.Rect(model.doc[0].rect)
            assert abs(after_rect.width - before_rect.width) < 1.0
            assert abs(after_rect.height - before_rect.height) < 1.0
            # After straightening, the residual skew should be near zero.
            residual = model.detect_page_skew(1)
            assert abs(residual) <= 1.5, f"residual skew {residual} too large after straighten"
        finally:
            model.close()


def test_straighten_page_auto_detects_when_angle_omitted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skewed.pdf"
        _skewed_lines_pdf(path, -5.0)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            ok = model.straighten_page(1)  # auto-detect
            assert ok is True
            residual = model.detect_page_skew(1)
            assert abs(residual) <= 1.5, f"residual skew {residual} too large after auto straighten"
        finally:
            model.close()
