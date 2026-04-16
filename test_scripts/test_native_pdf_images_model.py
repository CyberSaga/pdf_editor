from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ResizeObjectRequest, RotateObjectRequest
from model.pdf_content_ops import discover_native_image_invocations
from model.pdf_model import PDFModel


def _png_bytes(rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    for y in range(8):
        for x in range(8):
            pix.set_pixel(x, y, rgb)
    return pix.tobytes("png")


def _make_native_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((255, 0, 0)))
    page.insert_image(fitz.Rect(70, 45, 170, 135), stream=_png_bytes((0, 255, 0)))
    doc.save(path)
    doc.close()


def _make_shared_native_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((10, 20, 30)))
    image_name = str(page.get_images(full=True)[0][7])
    stream_xref = int(page.get_contents()[0])
    original_stream = doc.xref_stream(stream_xref)
    duplicate_stream = original_stream + f"q\n100 0 0 70 150 140 cm\n/{image_name} Do\nQ\n".encode("ascii")
    doc.update_stream(stream_xref, duplicate_stream)
    doc.save(path)
    doc.close()


def _make_outer_q_nested_sibling_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((120, 30, 30)))
    page.insert_image(fitz.Rect(160, 30, 260, 100), stream=_png_bytes((30, 120, 30)))
    image_names = [str(image[7]) for image in page.get_images(full=True)]
    stream_xrefs = [int(xref) for xref in page.get_contents()]
    stream_xref = stream_xrefs[0]
    nested_name, target_name = image_names
    custom_stream = (
        b"q\n"
        b"q\n"
        + f"100 0 0 70 20 150 cm\n/{nested_name} Do\nQ\n".encode("ascii")
        + f"100 0 0 70 160 140 cm\n/{target_name} Do\n".encode("ascii")
        + b"Q\n"
    )
    doc.update_stream(stream_xref, custom_stream)
    for extra_stream_xref in stream_xrefs[1:]:
        doc.update_stream(extra_stream_xref, b"")
    doc.save(path)
    doc.close()


def _make_cropped_native_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(50, 60, 150, 140), stream=_png_bytes((200, 0, 0)))
    # Crop from the bottom: keep the top of the page unchanged.
    page.set_cropbox(fitz.Rect(0, 100, 400, 400))
    doc.save(path)
    doc.close()


def _make_native_image_no_cm_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((0, 0, 200)))
    image_name = str(page.get_images(full=True)[0][7])
    stream_xref = int(page.get_contents()[0])
    # Replace the stream with a minimal image invocation that relies on the default CTM (no local cm).
    doc.update_stream(stream_xref, f"q\n/{image_name} Do\nQ\n".encode("ascii"))
    doc.save(path)
    doc.close()


def _hit(model: PDFModel, point: fitz.Point):
    return model.get_object_info_at_point(1, point)


def _image_names(page: fitz.Page) -> list[str]:
    return [str(image[7]) for image in page.get_images(full=True)]


def test_native_image_hit_detection_returns_native_kind() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))

            assert hit is not None
            assert hit.object_kind == "native_image"
            assert hit.object_id == "native_image:1:0"
            assert hit.supports_move is True
            assert hit.supports_delete is True
            assert hit.supports_rotate is True
            assert hit.rotation == 0
        finally:
            model.close()


def test_native_image_hit_prefers_topmost_invocation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_topmost.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(90, 60))

            assert hit is not None
            assert hit.object_kind == "native_image"
            assert hit.object_id == "native_image:1:1"
            assert fitz.Rect(hit.bbox) == fitz.Rect(70, 45, 170, 135)
        finally:
            model.close()


def test_move_native_image_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_move.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(180, 140, 280, 210),
                )
            )

            assert ok is True
            assert _hit(model, fitz.Point(30, 30)) is None
            moved = _hit(model, fitz.Point(200, 160))
            assert moved is not None
            assert moved.object_id == hit.object_id
            assert fitz.Rect(moved.bbox) == fitz.Rect(180, 140, 280, 210)
        finally:
            model.close()


def test_resize_native_image_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_resize.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.resize_object(
                ResizeObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    destination_rect=fitz.Rect(20, 20, 200, 140),
                )
            )

            assert ok is True
            resized = _hit(model, fitz.Point(180, 120))
            assert resized is not None
            assert resized.object_id == hit.object_id
            assert fitz.Rect(resized.bbox) == fitz.Rect(20, 20, 200, 140)
        finally:
            model.close()


def test_rotate_native_image_preserves_bbox_and_updates_rotation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_rotate.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None
            before_bbox = fitz.Rect(hit.bbox)

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )

            assert ok is True
            rotated = _hit(model, fitz.Point(30, 30))
            assert rotated is not None
            assert rotated.object_id == hit.object_id
            assert rotated.rotation == 90
            assert fitz.Rect(rotated.bbox) == before_bbox
        finally:
            model.close()


def test_delete_native_image_removes_one_invocation_but_keeps_shared_resource() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_delete_shared.pdf"
        _make_shared_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            names_before = _image_names(page)
            assert len(names_before) == 1

            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))

            assert ok is True
            assert _hit(model, fitz.Point(30, 30)) is None
            survivor = _hit(model, fitz.Point(180, 60))
            assert survivor is not None
            assert survivor.object_kind == "native_image"
            assert _image_names(page) == names_before
        finally:
            model.close()


def test_delete_native_image_prunes_unused_resource_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_delete_unique.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            names_before = _image_names(page)
            assert len(names_before) == 2

            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))

            assert ok is True
            names_after = _image_names(page)
            assert len(names_after) == 1
            assert names_after != names_before
            assert _hit(model, fitz.Point(30, 30)) is None
        finally:
            model.close()


def test_delete_native_image_does_not_delete_nested_sibling_in_outer_q() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_nested_q.pdf"
        _make_outer_q_nested_sibling_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            before = discover_native_image_invocations(model.doc, 1)
            assert len(before) == 2

            target = _hit(model, fitz.Point(180, 60))
            assert target is not None
            assert target.object_kind == "native_image"

            ok = model.delete_object(DeleteObjectRequest(target.object_id, target.object_kind, 1))

            assert ok is True
            after = discover_native_image_invocations(model.doc, 1)
            assert len(after) == 1
            survivor = _hit(model, fitz.Point(40, 40))
            assert survivor is not None
            assert survivor.object_kind == "native_image"
            assert fitz.Rect(survivor.bbox) == fitz.Rect(20, 20, 120, 90)
        finally:
            model.close()


def test_native_discovery_does_not_depend_on_get_image_info_order(monkeypatch) -> None:
    original = fitz.Page.get_image_info

    def _reversed_info(page: fitz.Page, *args, **kwargs):
        items = list(reversed(original(page, *args, **kwargs)))
        rewritten = []
        for idx, item in enumerate(items):
            rewritten_item = dict(item)
            rewritten_item["number"] = idx
            rewritten.append(rewritten_item)
        return rewritten

    monkeypatch.setattr(fitz.Page, "get_image_info", _reversed_info)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_reversed_info.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            first = _hit(model, fitz.Point(30, 30))
            topmost = _hit(model, fitz.Point(90, 60))

            assert first is not None
            assert fitz.Rect(first.bbox) == fitz.Rect(20, 20, 120, 90)
            assert topmost is not None
            assert fitz.Rect(topmost.bbox) == fitz.Rect(70, 45, 170, 135)
        finally:
            model.close()


def test_native_discovery_survives_missing_get_image_info(monkeypatch) -> None:
    monkeypatch.setattr(fitz.Page, "get_image_info", lambda self, *args, **kwargs: [])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_missing_info.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))

            assert hit is not None
            assert hit.object_kind == "native_image"
            assert fitz.Rect(hit.bbox) == fitz.Rect(20, 20, 120, 90)
        finally:
            model.close()


def test_native_bbox_matches_get_image_info_on_cropped_page() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_cropbox.pdf"
        _make_cropped_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            expected = fitz.Rect(page.get_image_info(xrefs=True)[0]["bbox"])

            invocations = discover_native_image_invocations(model.doc, 1)
            assert len(invocations) == 1
            assert fitz.Rect(invocations[0].bbox) == expected
        finally:
            model.close()


def test_native_discovery_survives_no_cm_invocation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_no_cm.pdf"
        _make_native_image_no_cm_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            expected_bbox = fitz.Rect(page.get_image_info(xrefs=True)[0]["bbox"])

            hit = _hit(model, expected_bbox.tl + (expected_bbox.br - expected_bbox.tl) * 0.5)
            assert hit is not None
            assert hit.object_kind == "native_image"
            assert fitz.Rect(hit.bbox) == expected_bbox
        finally:
            model.close()


def test_native_no_cm_invocation_rejects_move_and_rotate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_no_cm_actions.pdf"
        _make_native_image_no_cm_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            bbox = fitz.Rect(page.get_image_info(xrefs=True)[0]["bbox"])
            center = fitz.Point((bbox.x0 + bbox.x1) * 0.5, (bbox.y0 + bbox.y1) * 0.5)
            hit = _hit(model, center)
            assert hit is not None
            assert hit.object_kind == "native_image"

            move_ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(40, 30, 140, 100),
                )
            )
            rotate_ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )

            assert move_ok is False
            assert rotate_ok is False
        finally:
            model.close()
