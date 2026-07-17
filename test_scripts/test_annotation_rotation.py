"""Pixel-level regression tests for annotation placement on rotated pages.

PyMuPDF 1.27.1 interprets the rect/point passed to ``page.add_*_annot`` in
UNROTATED page coordinates, while the app always deals in displayed
coordinates (``page.rect``-space, i.e. with /Rotate applied). ``annot.rect``
readback echoes the requested values regardless, so it is NOT a valid
oracle here -- only rendering the page to a pixmap and locating the ink
detects the bug. These tests go through the real ``AnnotationTool`` entry
points (not raw ``page.add_*_annot``) so they exercise the chokepoint fix.
"""

from __future__ import annotations

import fitz
import pytest

from model.tools.annotation_tool import AnnotationTool

RECT = fitz.Rect(100, 100, 220, 160)
POINT = fitz.Point(120, 140)
SCALE = 2.0
TOLERANCE_PX = 8


class _ModelStub:
    """Minimal stand-in providing the ``.doc`` attribute AnnotationTool needs."""

    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc


def _make_stub(rotation: int) -> tuple[_ModelStub, fitz.Document]:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(rotation)
    return _ModelStub(doc), doc


def _ink_bbox(pix: fitz.Pixmap) -> tuple[int, int, int, int] | None:
    """Bounding box of all non-near-white pixels, or None if the page is blank."""
    w, h, n = pix.width, pix.height, pix.n
    samples = pix.samples
    xmin, ymin, xmax, ymax = w, h, -1, -1
    for y in range(h):
        row = y * pix.stride
        for x in range(w):
            o = row + x * n
            r, g, b = samples[o], samples[o + 1], samples[o + 2]
            if not (r > 235 and g > 235 and b > 235):
                if x < xmin:
                    xmin = x
                if x > xmax:
                    xmax = x
                if y < ymin:
                    ymin = y
                if y > ymax:
                    ymax = y
    if xmax < 0:
        return None
    return (xmin, ymin, xmax, ymax)


def _add_and_measure(kind: str, rotation: int) -> tuple[int, int, int, int]:
    model, doc = _make_stub(rotation)
    tool = AnnotationTool(model)
    try:
        if kind == "rect":
            tool.add_rect(1, RECT, stroke_color=(1.0, 0.0, 0.0, 1.0), border_width=3.0)
        elif kind == "highlight":
            tool.add_highlight(1, RECT, (1.0, 1.0, 0.0, 1.0))
        elif kind == "underline":
            tool.add_underline(1, RECT, (0.0, 0.0, 1.0, 1.0))
        elif kind == "strikeout":
            tool.add_strikeout(1, RECT, (0.0, 0.6, 0.0, 1.0))
        elif kind == "note":
            tool.add_annotation(1, POINT, "note text")
        else:  # pragma: no cover - test author error, not a runtime path
            raise ValueError(f"unknown kind: {kind}")
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
        bbox = _ink_bbox(pix)
    finally:
        doc.close()
    assert bbox is not None, f"no ink found for kind={kind!r} rotation={rotation}"
    return bbox


@pytest.mark.parametrize("kind", ["rect", "highlight", "underline", "strikeout"])
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_markup_ink_matches_rotation0_baseline(kind: str, rotation: int) -> None:
    baseline = _add_and_measure(kind, 0)
    rotated = _add_and_measure(kind, rotation)
    for edge_base, edge_rot in zip(baseline, rotated):
        assert abs(edge_base - edge_rot) <= TOLERANCE_PX, (
            f"{kind} @ rotation={rotation}: baseline={baseline} rotated={rotated}"
        )


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_note_annotation_ink_matches_rotation0_baseline(rotation: int) -> None:
    baseline = _add_and_measure("note", 0)
    rotated = _add_and_measure("note", rotation)
    for edge_base, edge_rot in zip(baseline, rotated):
        assert abs(edge_base - edge_rot) <= TOLERANCE_PX, (
            f"note @ rotation={rotation}: baseline={baseline} rotated={rotated}"
        )


def test_rect_rotation0_matches_requested_rect_scaled() -> None:
    """Regression guard: derotation must be a no-op (identity matrix) at rotation 0."""
    bbox = _add_and_measure("rect", 0)
    expected = (RECT.x0 * SCALE, RECT.y0 * SCALE, RECT.x1 * SCALE, RECT.y1 * SCALE)
    for edge_exp, edge_found in zip(expected, bbox):
        assert abs(edge_exp - edge_found) <= TOLERANCE_PX


POINT_TOLERANCE = TOLERANCE_PX / SCALE
MOVE_TARGET = fitz.Rect(60, 60, 90, 80)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_get_all_annotations_rect_matches_displayed_icon_position(rotation: int) -> None:
    """The rect crossing back out of the model boundary must be in displayed
    coords: its top-left, scaled, must land on the rendered icon's ink bbox
    top-left -- the same displayed position the caller originally requested.
    """
    model, doc = _make_stub(rotation)
    tool = AnnotationTool(model)
    try:
        tool.add_annotation(1, POINT, "note text")
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
        ink_bbox = _ink_bbox(pix)
        assert ink_bbox is not None

        results = tool.get_all_annotations()
        assert len(results) == 1
        rect = results[0]["rect"]
        assert abs(rect.x0 * SCALE - ink_bbox[0]) <= TOLERANCE_PX, (
            f"rotation={rotation}: rect={rect} ink_bbox={ink_bbox}"
        )
        assert abs(rect.y0 * SCALE - ink_bbox[1]) <= TOLERANCE_PX, (
            f"rotation={rotation}: rect={rect} ink_bbox={ink_bbox}"
        )
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_move_annotation_round_trip_rect_and_ink_match_target(rotation: int) -> None:
    """add_annotation at P -> get_all_annotations -> move_annotation to a
    displayed target Q -> get_all_annotations must report ~Q, and the
    rendered ink must actually have moved to Q, at every rotation.
    """
    model, doc = _make_stub(rotation)
    tool = AnnotationTool(model)
    try:
        xref = tool.add_annotation(1, POINT, "note text")
        tool.move_annotation(xref, MOVE_TARGET)

        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
        ink_bbox = _ink_bbox(pix)
        assert ink_bbox is not None
        assert abs(ink_bbox[0] - MOVE_TARGET.x0 * SCALE) <= TOLERANCE_PX, (
            f"rotation={rotation}: ink_bbox={ink_bbox} target={MOVE_TARGET}"
        )
        assert abs(ink_bbox[1] - MOVE_TARGET.y0 * SCALE) <= TOLERANCE_PX, (
            f"rotation={rotation}: ink_bbox={ink_bbox} target={MOVE_TARGET}"
        )

        results = tool.get_all_annotations()
        assert len(results) == 1
        rect = results[0]["rect"]
        assert abs(rect.x0 - MOVE_TARGET.x0) <= POINT_TOLERANCE, (
            f"rotation={rotation}: rect={rect} target={MOVE_TARGET}"
        )
        assert abs(rect.y0 - MOVE_TARGET.y0) <= POINT_TOLERANCE, (
            f"rotation={rotation}: rect={rect} target={MOVE_TARGET}"
        )
    finally:
        doc.close()
