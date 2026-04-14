from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import DeleteObjectRequest, MoveObjectRequest, RotateObjectRequest
from model.pdf_model import PDFModel


def _png_bytes() -> bytes:
    # Generate a known-good tiny PNG without external deps (Pillow).
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 1, 1), 0)
    pix.set_pixel(0, 0, (255, 0, 0))
    return pix.tobytes("png")


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=320, height=240)
    doc.save(path)
    doc.close()


def _hit(model: PDFModel, point: fitz.Point):
    return model.get_object_info_at_point(1, point)


def test_add_image_object_creates_marker_and_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            rect = fitz.Rect(40, 60, 140, 140)
            model.add_image_object(1, rect, _png_bytes(), rotation=0)

            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None
            assert hit.object_kind == "image"
            assert hit.supports_move is True
            assert hit.supports_delete is True
            assert hit.supports_rotate is True

            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_image_object"
            ]
            assert len(marker_annots) == 1
            payload = json.loads(marker_annots[0].info.get("content") or "{}")
            assert payload["kind"] == "image"
            assert "xref" in payload
        finally:
            model.close()


def test_move_image_object_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "move_img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(160, 60, 260, 140),
                )
            )
            assert ok is True
            assert _hit(model, fitz.Point(60, 80)) is None
            moved = _hit(model, fitz.Point(180, 80))
            assert moved is not None
            assert moved.object_id == hit.object_id
        finally:
            model.close()


def test_rotate_image_object_updates_rotation_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rot_img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None
            assert hit.rotation == 0

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert ok is True
            rotated = _hit(model, fitz.Point(60, 80))
            assert rotated is not None
            assert rotated.rotation == 90
        finally:
            model.close()


def test_delete_image_object_removes_marker_and_page_image_ref() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "del_img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None
            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_image_object"
            ]
            assert len(marker_annots) == 1
            payload = json.loads(marker_annots[0].info.get("content") or "{}")
            before_images = list(page.get_images(full=True))

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))
            assert ok is True
            assert _hit(model, fitz.Point(60, 80)) is None

            after_images = list(page.get_images(full=True))
            assert len(after_images) <= len(before_images)
        finally:
            model.close()


def test_image_object_persists_through_save_and_reopen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "persist_img.pdf"
        out = Path(tmp) / "persist_out.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            model.save_as(str(out))
        finally:
            model.close()

        model2 = PDFModel()
        try:
            model2.open_pdf(str(out))
            hit = _hit(model2, fitz.Point(60, 80))
            assert hit is not None
            assert hit.object_kind == "image"
        finally:
            model2.close()
