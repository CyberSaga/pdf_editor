from __future__ import annotations

import json
import tempfile
from pathlib import Path

import fitz

from model.object_requests import DeleteObjectRequest, MoveObjectRequest, RotateObjectRequest
from model.pdf_content_ops import discover_native_image_invocations
from model.pdf_model import PDFModel


def _png_bytes(rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    # Generate a known-good tiny PNG without external deps (Pillow).
    # Distinct colours produce distinct image streams, hence distinct xrefs and
    # digests — the two app-images then resolve independently.
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 1, 1), 0)
    pix.set_pixel(0, 0, rgb)
    return pix.tobytes("png")


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=320, height=240)
    doc.save(path)
    doc.close()


def _image_markers(model: PDFModel, page_num: int = 1) -> dict[str, dict]:
    """object_id -> payload for every app-image marker annot on the page."""
    payloads: dict[str, dict] = {}
    for annot in model.doc[page_num - 1].annots() or []:
        if annot.info.get("subject") != "pdf_editor_image_object":
            continue
        payload = json.loads(annot.info.get("content") or "{}")
        payloads[payload["object_id"]] = payload
    return payloads


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

            # B1: the sole placement is gone, so _remove_native_image_invocation nulls
            # Resources/XObject/<name> and the page no longer lists the image. Re-fetch
            # the page handle rather than reusing the pre-delete one.
            assert len(before_images) == 1
            after_images = list(model.doc[0].get_images(full=True))
            assert after_images == [], f"page must list no images after delete, got {after_images}"

            # R6-01: the orphaned image xref must not survive as a recoverable object.
            # delete_objects_atomic sets secure_save_required, which makes the save a
            # full garbage=4 rewrite.
            assert model.secure_save_required is True
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


# ---------------------------------------------------------------------------
# B1 (R5 backlog): deleting an app-image must strip ONLY its own content-stream
# invocation.  The old path redacted the image's rectangle, and
# ``apply_redactions`` is geometric: it destroys every image, glyph and stroke the
# rectangle touches.  See plans/b1-delete-app-image-invocation-removal.md.
# ---------------------------------------------------------------------------


def test_delete_overlapping_app_images_neighbor_survives() -> None:
    """Deleting B must leave overlapping neighbour A's placement intact.

    Mirror of test_move_overlapping_app_images_both_survive for the delete path.
    Distinct colours => distinct xrefs => the two images resolve independently.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes((255, 0, 0)), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes((0, 0, 255)), rotation=0)

            assert len(discover_native_image_invocations(model.doc, 1)) == 2

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None and hit_b.object_kind == "image"

            ok = model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1))
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 1, (
                f"Expected 1 invocation after delete (A must survive), got {len(invocations_after)}"
            )
            # A's placement, not B's, is the survivor.
            surviving = invocations_after[0].bbox
            assert abs(surviving.x0 - 10) < 1.0 and abs(surviving.x1 - 80) < 1.0, (
                f"Survivor must be A at (10..80), got {tuple(surviving)}"
            )
            # A is still selectable; B's exclusive region is empty.
            assert _hit(model, fitz.Point(20, 20)) is not None
            assert _hit(model, fitz.Point(100, 100)) is None
        finally:
            model.close()


def test_delete_app_image_preserves_underlying_text() -> None:
    """apply_redactions strips glyphs under the rect; invocation removal must not."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "text_under_image.pdf"
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        page.insert_text((45, 70), "UNDER THE IMAGE", fontsize=9, fontname="helv")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            assert "UNDER THE IMAGE" in model.doc[0].get_text()

            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 60))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, "image", 1))
            assert ok is True

            text_after = model.doc[0].get_text()
            assert "UNDER THE IMAGE" in text_after, (
                f"Deleting the image must not remove text beneath it; got {text_after.strip()!r}"
            )
        finally:
            model.close()


def test_delete_app_image_preserves_underlying_vector_art() -> None:
    """apply_redactions removes line art touching the rect; invocation removal must not."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "art_under_image.pdf"
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        page.draw_line(fitz.Point(45, 60), fitz.Point(105, 60), color=(1, 0, 0), width=2)
        page.draw_line(fitz.Point(10, 220), fitz.Point(300, 220), color=(0, 1, 0), width=2)
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            drawings_before = len(model.doc[0].get_drawings())
            assert drawings_before == 2

            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 60))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, "image", 1))
            assert ok is True

            drawings_after = len(model.doc[0].get_drawings())
            assert drawings_after == drawings_before, (
                f"Deleting the image must not remove line art crossing its rect; "
                f"{drawings_before} -> {drawings_after}"
            )
        finally:
            model.close()


def test_delete_one_of_two_shared_xref_images_neighbor_survives() -> None:
    """Identical bytes dedupe to one image xref under two XObject names.

    Deleting one placement must strip only its own name; the shared xref must stay
    alive while the neighbour still references it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shared_xref_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), png, rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), png, rotation=0)

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2
            shared_xref = invocations_before[0].xref
            assert invocations_before[1].xref == shared_xref, "expected PyMuPDF to dedupe the stream"

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None

            ok = model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1))
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 1, (
                f"Expected 1 invocation after delete, got {len(invocations_after)}"
            )
            # The shared xref survives because the neighbour still names it.
            assert invocations_after[0].xref == shared_xref
            assert model.doc.xref_stream(shared_xref), "shared image xref must still hold its stream"
        finally:
            model.close()


def test_delete_stale_shared_xref_marker_preserves_surviving_placement() -> None:
    """A stale marker must not retarget another placement of the same image stream."""
    from model.pdf_object_ops import _remove_native_image_invocation

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stale_shared_xref_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            stale_oid = model.add_image_object(1, fitz.Rect(10, 10, 80, 80), png, rotation=0)
            survivor_oid = model.add_image_object(
                1, fitz.Rect(150, 150, 220, 220), png, rotation=0
            )

            invocations = discover_native_image_invocations(model.doc, 1)
            assert len(invocations) == 2
            assert invocations[0].xref == invocations[1].xref

            # Simulate an external editor removing the first placement while leaving
            # pdf_editor's hidden marker annotation behind.
            assert _remove_native_image_invocation(model, invocations[0]) is True
            remaining = discover_native_image_invocations(model.doc, 1)
            assert len(remaining) == 1
            survivor_bbox = fitz.Rect(remaining[0].bbox)

            assert model.delete_object(DeleteObjectRequest(stale_oid, "image", 1)) is True

            after = discover_native_image_invocations(model.doc, 1)
            assert len(after) == 1, "deleting a stale marker must not delete its shared-xref neighbour"
            assert fitz.Rect(after[0].bbox) == survivor_bbox
            assert set(_image_markers(model)) == {survivor_oid}
        finally:
            model.close()


def test_delete_app_image_ambiguous_resolution_fails_safely() -> None:
    """Unresolvable placement => delete is a no-op, never a redaction.

    NOTE: this is a *contract* test, not a red-light test. On the pre-fix code the
    delete path never resolves an invocation at all, so it "succeeds" by redacting.
    It only becomes meaningful once resolution exists — it pins the decision that the
    ambiguous case fails safe rather than falling back to redaction.

    Ambiguity is forced the way it arises in the wild: the marker's recorded xref has
    drifted (post-GC renumbering), so resolution falls back to geometry+digest, and two
    same-digest twins sit at the same rect.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ambiguous_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            rect = fitz.Rect(40, 60, 140, 140)
            oid1 = model.add_image_object(1, rect, png, rotation=0)
            oid2 = model.add_image_object(1, rect, png, rotation=0)
            assert len(discover_native_image_invocations(model.doc, 1)) == 2

            # Drift oid2's recorded xref to a dead value, keeping its digest: the
            # xref_candidates branch finds nothing, and the geometric+digest fallback
            # then sees two equally-good candidates and must refuse.
            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                if payload["object_id"] != oid2:
                    continue
                payload["xref"] = 999999
                annot.set_info(
                    content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    subject="pdf_editor_image_object",
                )
                annot.update()

            ok = model.delete_object(DeleteObjectRequest(oid2, "image", 1))
            assert ok is False, "ambiguous resolution must fail safe, not redact"

            # Document untouched: both placements and both markers survive.
            assert len(discover_native_image_invocations(model.doc, 1)) == 2
            markers = _image_markers(model)
            assert set(markers) == {oid1, oid2}
        finally:
            model.close()


def test_delete_app_image_then_undo_restores_both() -> None:
    """Undo after an overlap-delete brings the deleted image back, neighbour intact."""
    from model.edit_commands import SnapshotCommand

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "undo_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes((255, 0, 0)), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes((0, 0, 255)), rotation=0)

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None

            before = model._capture_doc_snapshot()
            assert model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1)) is True
            after = model._capture_doc_snapshot()

            assert len(discover_native_image_invocations(model.doc, 1)) == 1

            model.command_manager.record(
                SnapshotCommand(
                    model=model,
                    command_type="delete_object",
                    affected_pages=[1],
                    before_bytes=before,
                    after_bytes=after,
                    description="delete image",
                )
            )
            assert model.command_manager.undo() is True

            assert len(discover_native_image_invocations(model.doc, 1)) == 2
            assert _hit(model, fitz.Point(20, 20)) is not None
            assert _hit(model, fitz.Point(100, 100)) is not None
        finally:
            model.close()


def _raw_inherited_resources_pdf() -> bytes:
    """A spec-legal PDF whose /Page has NO /Resources — it inherits from /Pages.

    Hand-built because PyMuPDF always writes a page-level /Resources. Older writers and
    optimizers routinely emit this shape (PDF 1.7 §7.7.3.4, Table 30).
    """
    content = b"BT /F1 14 Tf 30 300 Td (INHERITED RESOURCES TEXT) Tj ET\n"
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 "
            b"/Resources << /Font << /F1 5 0 R >> >> /MediaBox [0 0 400 400] >>"
        ),
        3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        4: b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    out = bytearray(b"%PDF-1.7\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for num in sorted(objs):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    return bytes(out)


def _raw_two_page_mixed_resources_pdf() -> bytes:
    """Page 1 inherits resources; page 2 owns an unrelated resource dictionary."""
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 "
            b"/Resources << >> /MediaBox [0 0 400 400] >>"
        ),
        3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        4: b"<< /Length 0 >>\nstream\n\nendstream",
        5: (
            b"<< /Type /Page /Parent 2 0 R /Resources << >> "
            b"/MediaBox [0 0 400 400] /Contents 6 0 R >>"
        ),
        6: b"<< /Length 0 >>\nstream\n\nendstream",
    }
    out = bytearray(b"%PDF-1.7\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for num in sorted(objs):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    return bytes(out)


def test_delete_app_image_prunes_prefix_colliding_resource_name() -> None:
    """`/fzImg1` must not be considered "still referenced" because `/fzImg10` exists.

    PyMuPDF names page XObjects fzImg0, fzImg1, ... fzImg10, ... Once there are 11+ images,
    the retention check's raw substring scan (`b"/fzImg1" in stream`) matches the *token*
    `/fzImg10` in a neighbour's content stream, so the deleted image's resource entry is
    never pruned and the page keeps advertising an image it no longer draws.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "many_images.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oids = []
            for i in range(12):
                rgb = ((i * 20) % 256, (255 - i * 15) % 256, (i * 7) % 256)
                rect = fitz.Rect(10 + i * 5, 10 + i * 5, 60 + i * 5, 60 + i * 5)
                oids.append(model.add_image_object(1, rect, _png_bytes(rgb), rotation=0))

            invocations = discover_native_image_invocations(model.doc, 1)
            names = [inv.xobject_name for inv in invocations]
            assert "fzImg1" in names and "fzImg10" in names, names

            target = next(inv for inv in invocations if inv.xobject_name == "fzImg1")
            markers = _image_markers(model)
            target_oid = next(
                oid for oid, pl in markers.items() if abs(pl["rect"][0] - target.bbox.x0) < 1.5
            )

            before_images = list(model.doc[0].get_images(full=True))
            assert len(before_images) == 12

            assert model.delete_object(DeleteObjectRequest(target_oid, "image", 1)) is True

            after_names = [x[7] for x in model.doc[0].get_images(full=True)]
            assert "fzImg1" not in after_names, (
                f"fzImg1's resource entry must be pruned, got {sorted(after_names)}"
            )
            # The prefix-colliding neighbour must be untouched.
            assert "fzImg10" in after_names
            assert len(after_names) == 11
        finally:
            model.close()


def test_delete_app_image_does_not_shadow_inherited_resources() -> None:
    """Pruning must not fabricate a page-level /Resources on a page that inherits one.

    `xref_set_key(page.xref, "Resources/XObject/<name>", "null")` creates every missing
    link in the path, so on an inheriting page it writes a direct
    ``/Resources << /XObject << /fzImg0 null >> >>`` that SHADOWS the inherited dict —
    the page's fonts and other XObjects stop resolving through it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "inherited.pdf"
        path.write_bytes(_raw_inherited_resources_pdf())

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page_xref = model.doc[0].xref
            assert model.doc.xref_get_key(page_xref, "Resources")[0] == "null", (
                "fixture must start with an inheriting page"
            )
            text_before = model.doc[0].get_text().strip()
            assert "INHERITED RESOURCES TEXT" in text_before

            oid = model.add_image_object(1, fitz.Rect(50, 50, 150, 150), _png_bytes(), rotation=0)
            # PyMuPDF registers the XObject in the *inherited* dict, not on the page.
            assert model.doc.xref_get_key(page_xref, "Resources")[0] == "null"

            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True

            kind, value = model.doc.xref_get_key(page_xref, "Resources")
            assert kind == "null", (
                f"delete must not fabricate a page-level /Resources, got {kind}: {value}"
            )
            # The inherited font must still resolve, and the image must be gone.
            assert model.doc[0].get_text().strip() == text_before
            assert discover_native_image_invocations(model.doc, 1) == []
            assert model.doc[0].get_images(full=True) == []
        finally:
            model.close()


def test_delete_inherited_image_ignores_same_name_in_unrelated_page_resources() -> None:
    """An unrelated page's `/fzImg0` must not retain the deleted inherited binding."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mixed_resources.pdf"
        path.write_bytes(_raw_two_page_mixed_resources_pdf())

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target_oid = model.add_image_object(
                1, fitz.Rect(20, 20, 90, 90), _png_bytes((255, 0, 0)), rotation=0
            )
            model.add_image_object(
                2, fitz.Rect(120, 120, 190, 190), _png_bytes((0, 0, 255)), rotation=0
            )
            assert [row[7] for row in model.doc[0].get_images(full=True)] == ["fzImg0"]
            assert [row[7] for row in model.doc[1].get_images(full=True)] == ["fzImg0"]

            assert model.delete_object(DeleteObjectRequest(target_oid, "image", 1)) is True

            reopened = fitz.open("pdf", model.doc.tobytes(garbage=4))
            try:
                assert reopened[0].get_images(full=True) == [], (
                    "the deleted inherited resource must not survive secure garbage collection"
                )
                assert len(reopened[1].get_images(full=True)) == 1
            finally:
                reopened.close()
        finally:
            model.close()


def _strip_invocation(model: PDFModel, page_num: int = 1) -> None:
    """Excise the image's content-stream placement, leaving the marker annot orphaned.

    Simulates what an external editor does when it removes an image: the XObject
    invocation is gone, but our hidden marker annot (which it knows nothing about) stays.
    """
    from model.pdf_object_ops import _remove_native_image_invocation

    invocations = discover_native_image_invocations(model.doc, page_num)
    assert invocations, "fixture must have an invocation to strip"
    assert _remove_native_image_invocation(model, invocations[0]) is True


def test_delete_orphaned_app_image_marker_cleans_up_the_marker() -> None:
    """An unresolvable marker with NO surviving image must be deletable, not a zombie.

    Fail-safe (return False) is right when resolution is *ambiguous* — the pixels exist and
    deleting the marker alone would orphan them. It is wrong when there is no candidate at
    all: nothing renders, and refusing to delete leaves a hit-detectable object that
    advertises supports_delete=True and that no verb can touch (move/rotate already fail on
    this population, so delete was its last working verb).
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "orphan_marker.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)

            _strip_invocation(model)
            assert discover_native_image_invocations(model.doc, 1) == []
            # The marker survives and is still selectable — this is the zombie state.
            assert _hit(model, fitz.Point(60, 80)) is not None
            assert oid in _image_markers(model)

            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True

            assert _image_markers(model) == {}, "the orphaned marker must be cleaned up"
            assert _hit(model, fitz.Point(60, 80)) is None
        finally:
            model.close()


def test_delete_app_image_with_corrupt_xref_payload_does_not_raise() -> None:
    """A non-numeric `xref` in the marker payload must not raise through the Qt slot.

    `int(payload.get("xref", 0) or 0)` on `"abc"` raised ValueError, which
    delete_objects_atomic re-raises after rollback and PDFController.delete_object does not
    catch. The digest still resolves the image, so the delete should simply succeed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "corrupt_xref.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)

            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                payload["xref"] = "abc"  # corrupt / third-party writer
                annot.set_info(
                    content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    subject="pdf_editor_image_object",
                )
                annot.update()

            # Must not raise; the digest still identifies the unique image.
            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True
            assert discover_native_image_invocations(model.doc, 1) == []
        finally:
            model.close()


def test_delete_app_image_without_xref_in_payload_still_resolves() -> None:
    """The `if not xref: return False` guard was stronger than the resolver it gated.

    `_find_app_image_invocation` handles a missing/0 xref via its geometric+digest fallback,
    and `_resolve_marker_image_invocation` backfills the payload. Guarding on xref before
    calling them forecloses deletes that would otherwise succeed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "no_xref.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)

            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                payload.pop("xref", None)  # legacy marker, written before xref was recorded
                annot.set_info(
                    content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    subject="pdf_editor_image_object",
                )
                annot.update()

            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True
            assert discover_native_image_invocations(model.doc, 1) == []
            assert _image_markers(model) == {}
        finally:
            model.close()


def test_delete_overlapping_app_image_survives_save_reopen() -> None:
    """The rewritten content stream must persist: neighbour still there after reopen."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_persist.pdf"
        out = Path(tmp) / "overlap_persist_out.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes((255, 0, 0)), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes((0, 0, 255)), rotation=0)

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None
            assert model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1)) is True
            model.save_as(str(out))
        finally:
            model.close()

        model2 = PDFModel()
        try:
            model2.open_pdf(str(out))
            invocations = discover_native_image_invocations(model2.doc, 1)
            assert len(invocations) == 1, (
                f"Neighbour must survive save+reopen, got {len(invocations)} invocations"
            )
            assert _hit(model2, fitz.Point(20, 20)) is not None
            assert _hit(model2, fitz.Point(100, 100)) is None
        finally:
            model2.close()
