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


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text(fitz.Point(40, 40), "LEGACY_TEXT", fontsize=12, fontname="helv", color=(0, 0, 0))
    doc.save(path)
    doc.close()


def _object_hit(model: PDFModel, point: fitz.Point):
    return model.get_object_info_at_point(1, point)


def test_add_textbox_creates_hidden_object_marker_and_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "textbox.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            visual_rect = fitz.Rect(50, 70, 180, 110)
            model.add_textbox(1, visual_rect, "OBJECT_BOX", font="cjk", size=14, color=(0, 0, 0))

            hit = _object_hit(model, fitz.Point(80, 90))
            assert hit is not None
            assert hit.object_kind == "textbox"
            assert hit.supports_move is True
            assert hit.supports_delete is True
            assert hit.supports_rotate is True

            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_textbox_object"
            ]
            assert len(marker_annots) == 1
            payload = json.loads(marker_annots[0].info.get("content") or "{}")
            assert payload["kind"] == "textbox"
            assert payload["text"] == "OBJECT_BOX"
        finally:
            model.close()


def test_get_object_info_ignores_legacy_text_without_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _object_hit(model, fitz.Point(42, 38))
            assert hit is None
        finally:
            model.close()


def test_add_rect_creates_object_metadata_and_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rect.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(1, fitz.Rect(20, 90, 120, 150), (1.0, 0.0, 0.0, 1.0), False)

            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None
            assert hit.object_kind == "rect"
            assert hit.supports_rotate is False
        finally:
            model.close()


def test_move_rect_object_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "move_rect.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(1, fitz.Rect(20, 90, 120, 150), (1.0, 0.0, 0.0, 1.0), False)
            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(160, 95, 260, 155),
                )
            )
            assert ok is True
            assert _object_hit(model, fitz.Point(30, 100)) is None
            moved = _object_hit(model, fitz.Point(180, 110))
            assert moved is not None
            assert moved.object_id == hit.object_id
        finally:
            model.close()


def test_delete_rect_object_removes_annotation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "delete_rect.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(1, fitz.Rect(20, 90, 120, 150), (1.0, 0.0, 0.0, 1.0), False)
            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None

            ok = model.delete_object(
                DeleteObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                )
            )
            assert ok is True
            assert _object_hit(model, fitz.Point(30, 100)) is None
        finally:
            model.close()


def test_rotate_textbox_object_updates_rotation_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotate_box.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "ROT_ME", font="cjk", size=14, color=(0, 0, 0))
            hit = _object_hit(model, fitz.Point(80, 90))
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

            rotated = _object_hit(model, fitz.Point(80, 90))
            assert rotated is not None
            assert rotated.rotation == 90
        finally:
            model.close()


def test_delete_textbox_after_move_and_rotate_removes_all_markers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "delete_rotated_box.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "ROT_DEL", font="cjk", size=14, color=(0, 0, 0))
            hit = _object_hit(model, fitz.Point(80, 90))
            assert hit is not None

            moved_ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(120, 100, 250, 140),
                )
            )
            assert moved_ok is True

            rotated_ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert rotated_ok is True

            delete_ok = model.delete_object(
                DeleteObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                )
            )
            assert delete_ok is True

            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_textbox_object"
            ]
            assert marker_annots == []
            assert _object_hit(model, fitz.Point(180, 120)) is None
        finally:
            model.close()
