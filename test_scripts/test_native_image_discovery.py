"""AC-6 — native PDF images nested inside Form XObjects are selectable/editable.

Awareness.pdf draws its only image (`Im0`, xref 50) *inside* a Form XObject
(`Fm0`), so the page content stream contains only `/Fm0 Do` — there is no
`/Im0 Do` to discover. The original discovery scanned only page content streams,
so the image could not be clicked, moved, resized, or deleted.

These tests pin the fixed behaviour: discovery also walks Form XObject streams,
reports the image's page-space bbox, and the model can move/resize/delete it.
01_報告書.pdf (direct page-level images) must keep working unchanged (AC-6c).
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ResizeObjectRequest
from model.pdf_content_ops import discover_native_image_invocations
from model.pdf_model import PDFModel

REPO_ROOT = Path(__file__).resolve().parents[1]
AWARENESS = REPO_ROOT / "test_files" / "Awareness.pdf"
REPORT = REPO_ROOT / "test_files" / "01_報告書.pdf"

# Page-space placement of Awareness.pdf's image (from get_image_rects).
_AWARENESS_IMG_RECT = fitz.Rect(356.147, 142.729, 665.707, 519.377)
_AWARENESS_IMG_CENTER = fitz.Point(
    (_AWARENESS_IMG_RECT.x0 + _AWARENESS_IMG_RECT.x1) / 2,
    (_AWARENESS_IMG_RECT.y0 + _AWARENESS_IMG_RECT.y1) / 2,
)


def _rects_close(a: fitz.Rect, b: fitz.Rect, tol: float = 2.0) -> bool:
    return (
        abs(a.x0 - b.x0) <= tol
        and abs(a.y0 - b.y0) <= tol
        and abs(a.x1 - b.x1) <= tol
        and abs(a.y1 - b.y1) <= tol
    )


@pytest.mark.skipif(not AWARENESS.exists(), reason="Awareness.pdf fixture missing")
def test_awareness_form_nested_image_is_discovered() -> None:
    """AC-6a (discovery): the form-nested image yields an invocation with the
    correct page-space bbox."""
    doc = fitz.open(str(AWARENESS))
    try:
        invocations = discover_native_image_invocations(doc, 1)
        assert len(invocations) >= 1, "form-nested image was not discovered"
        inv = invocations[0]
        assert _rects_close(fitz.Rect(inv.bbox), _AWARENESS_IMG_RECT)
        assert inv.is_form_nested is True
    finally:
        doc.close()


@pytest.mark.skipif(not AWARENESS.exists(), reason="Awareness.pdf fixture missing")
def test_awareness_image_is_hit_testable() -> None:
    """AC-6a: clicking the image in objects mode selects a native_image."""
    model = PDFModel()
    try:
        model.open_pdf(str(AWARENESS))
        hit = model.get_object_info_at_point(1, _AWARENESS_IMG_CENTER)
        assert hit is not None
        assert hit.object_kind == "native_image"
        assert hit.supports_move is True
        assert hit.supports_delete is True
    finally:
        model.close()


@pytest.mark.skipif(not AWARENESS.exists(), reason="Awareness.pdf fixture missing")
def test_awareness_image_can_be_moved() -> None:
    """AC-6b: moving the form-nested image relocates it to the requested rect."""
    model = PDFModel()
    try:
        model.open_pdf(str(AWARENESS))
        hit = model.get_object_info_at_point(1, _AWARENESS_IMG_CENTER)
        assert hit is not None
        dest = fitz.Rect(50, 50, 250, 300)
        ok = model.move_object(
            MoveObjectRequest(
                object_id=hit.object_id,
                object_kind=hit.object_kind,
                source_page=1,
                destination_page=1,
                destination_rect=dest,
            )
        )
        assert ok is True
        moved = model.get_object_info_at_point(1, fitz.Point(150, 175))
        assert moved is not None
        assert _rects_close(fitz.Rect(moved.bbox), dest)
        # original location no longer holds the image
        assert model.get_object_info_at_point(1, _AWARENESS_IMG_CENTER) is None
    finally:
        model.close()


@pytest.mark.skipif(not AWARENESS.exists(), reason="Awareness.pdf fixture missing")
def test_awareness_image_can_be_resized() -> None:
    """AC-6b: resizing the form-nested image changes its page-space rect."""
    model = PDFModel()
    try:
        model.open_pdf(str(AWARENESS))
        hit = model.get_object_info_at_point(1, _AWARENESS_IMG_CENTER)
        assert hit is not None
        dest = fitz.Rect(100, 100, 500, 250)
        ok = model.resize_object(
            ResizeObjectRequest(
                object_id=hit.object_id,
                object_kind=hit.object_kind,
                page_num=1,
                destination_rect=dest,
            )
        )
        assert ok is True
        resized = model.get_object_info_at_point(1, fitz.Point(300, 175))
        assert resized is not None
        assert _rects_close(fitz.Rect(resized.bbox), dest)
    finally:
        model.close()


@pytest.mark.skipif(not AWARENESS.exists(), reason="Awareness.pdf fixture missing")
def test_awareness_image_can_be_deleted() -> None:
    """AC-6b: deleting the form-nested image removes it from the page."""
    model = PDFModel()
    try:
        model.open_pdf(str(AWARENESS))
        hit = model.get_object_info_at_point(1, _AWARENESS_IMG_CENTER)
        assert hit is not None
        ok = model.delete_object(
            DeleteObjectRequest(hit.object_id, hit.object_kind, 1)
        )
        assert ok is True
        assert model.get_object_info_at_point(1, _AWARENESS_IMG_CENTER) is None
    finally:
        model.close()


@pytest.mark.skipif(not REPORT.exists(), reason="01_報告書.pdf fixture missing")
def test_report_direct_images_still_discovered() -> None:
    """AC-6c: a PDF with direct page-level images is unaffected by the form pass."""
    doc = fitz.open(str(REPORT))
    try:
        invocations = discover_native_image_invocations(doc, 4)
        assert len(invocations) == 2
        assert all(inv.is_form_nested is False for inv in invocations)
    finally:
        doc.close()
