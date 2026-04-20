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
from model.pdf_content_ops import discover_native_image_invocations
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


def test_move_overlapping_app_images_both_survive() -> None:
    """Moving one app-image across an overlapping neighbour must not destroy the other.

    The real failure mode is visual: redaction of B's old region erases A's pixels
    from the content stream.  We verify both images still have content-stream placements.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_move.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            # Image A at (10, 10, 80, 80)
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes(), rotation=0)
            # Image B overlapping A, at (40, 40, 110, 110)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2, "Expected 2 image invocations before move"

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None and hit_b.object_kind == "image"

            # Move B to a new location that overlaps A
            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit_b.object_id,
                    object_kind="image",
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(50, 50, 120, 120),
                )
            )
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 2, (
                f"Expected 2 image invocations after move (A must survive), got {len(invocations_after)}"
            )
        finally:
            model.close()


def test_rotate_overlapping_app_image_neighbour_survives() -> None:
    """Rotating one app-image must not remove an overlapping neighbour's content-stream entry."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_rotate.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes(), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit_b.object_id,
                    object_kind="image",
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 2, (
                f"Expected 2 image invocations after rotate (A must survive), got {len(invocations_after)}"
            )
        finally:
            model.close()


def test_move_second_of_identical_app_images_moves_correct_placement() -> None:
    """Two app-images sharing the same xref AND identical bbox must be independently movable.

    Regression: _find_app_image_invocation used closest-bbox heuristic, which silently
    moved the FIRST placement when the user dragged the SECOND, breaking objects-mode UX.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "twin.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            rect = fitz.Rect(40, 60, 140, 140)
            oid1 = model.add_image_object(1, rect, png, rotation=0)
            oid2 = model.add_image_object(1, rect, png, rotation=0)
            assert oid1 != oid2

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=oid2,
                    object_kind="image",
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(200, 100, 280, 160),
                )
            )
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 2

            # The placement that moved must be tied to oid2, NOT oid1.
            page = model.doc[0]
            payloads = {}
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                payloads[payload["object_id"]] = payload

            assert payloads[oid1]["rect"] == [40.0, 60.0, 140.0, 140.0], (
                f"oid1 marker rect must remain at original, got {payloads[oid1]['rect']}"
            )
            # oid2 marker rect should reflect its new home
            r2 = payloads[oid2]["rect"]
            assert abs(r2[0] - 200) < 1.0 and abs(r2[2] - 280) < 1.0, (
                f"oid2 marker rect must reflect move destination, got {r2}"
            )

            # And the actual content-stream placement positions must agree:
            # one invocation at the original rect (oid1), one at the new rect (oid2).
            bboxes = sorted([(inv.bbox.x0, inv.bbox.y0, inv.bbox.x1, inv.bbox.y1) for inv in invocations_after])
            assert any(abs(b[0] - 40) < 1.0 and abs(b[2] - 140) < 1.0 for b in bboxes), (
                f"Expected an invocation still at original (40..140), got {bboxes}"
            )
            assert any(abs(b[0] - 200) < 1.0 and abs(b[2] - 280) < 1.0 for b in bboxes), (
                f"Expected an invocation at new (200..280), got {bboxes}"
            )
        finally:
            model.close()
