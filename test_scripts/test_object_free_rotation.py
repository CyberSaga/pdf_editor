"""AC-4 (model) — free arbitrary-angle rotation of images, preserved on move.

The legacy rotate path only handled 90° steps ("fit to rect"). Free rotation
adds a rotate-about-center path driven by an explicit absolute angle, and a move
of an already-rotated image must keep its angle (the review reported rotated
images snapping back upright on move). The 90° toolbar path is unchanged and is
covered by test_native_pdf_images_model.py.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from model.object_requests import MoveObjectRequest, RotateObjectRequest
from model.pdf_model import PDFModel


def _png_bytes(rgb: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    for y in range(8):
        for x in range(8):
            pix.set_pixel(x, y, rgb)
    return pix.tobytes("png")


def _make_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(120, 120, 220, 200), stream=_png_bytes())  # 100×80
    doc.save(path)
    doc.close()


def _center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def test_free_rotate_native_image_to_30_degrees() -> None:
    """AC-4a: an absolute-angle rotate yields ~30° read-back, center preserved."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rot.pdf"
        _make_image_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert hit is not None and hit.object_kind == "native_image"
            before_center = _center(fitz.Rect(hit.bbox))

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=30.0,
                )
            )
            assert ok is True

            rotated = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert rotated is not None
            assert abs((float(rotated.rotation) % 360) - 30.0) <= 1.0
            after_center = _center(fitz.Rect(rotated.bbox))
            assert abs(after_center.x - before_center.x) <= 1.5
            assert abs(after_center.y - before_center.y) <= 1.5
        finally:
            model.close()


def test_moving_a_freely_rotated_image_preserves_its_angle() -> None:
    """AC-4d: a rotated image keeps its angle after a move (no snap-to-upright)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotmove.pdf"
        _make_image_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert hit is not None

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=40.0,
                )
            )

            rotated = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert rotated is not None
            angle_before_move = float(rotated.rotation) % 360
            assert abs(angle_before_move - 40.0) <= 1.0

            # Translate the rotated image by (+80, +60): the new AABB is the old
            # one shifted by the same delta.
            old_bbox = fitz.Rect(rotated.bbox)
            dest = fitz.Rect(
                old_bbox.x0 + 80, old_bbox.y0 + 60, old_bbox.x1 + 80, old_bbox.y1 + 60
            )
            assert model.move_object(
                MoveObjectRequest(
                    object_id=rotated.object_id,
                    object_kind=rotated.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=dest,
                )
            )

            moved = model.get_object_info_at_point(1, _center(dest))
            assert moved is not None
            assert abs((float(moved.rotation) % 360) - angle_before_move) <= 1.0
        finally:
            model.close()
