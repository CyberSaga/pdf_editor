from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import DeleteObjectRequest, MoveObjectRequest  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model import pdf_object_ops  # noqa: E402


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 4, 4), 0)
    for y in range(4):
        for x in range(4):
            pix.set_pixel(x, y, color)
    return pix.tobytes("png")


def _open_model(tmp_path: Path) -> PDFModel:
    path = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page(width=320, height=240)
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _render_digest(model: PDFModel) -> str:
    samples = model.doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).samples
    return hashlib.sha256(samples).hexdigest()


def _image_marker(model: PDFModel, object_id: str) -> tuple[fitz.Annot, dict]:
    for annot in model.doc[0].annots() or []:
        payload = json.loads(annot.info.get("content") or "{}")
        if payload.get("object_id") == object_id:
            return annot, payload
    raise AssertionError(f"marker not found: {object_id}")


def _rewrite_marker(model: PDFModel, object_id: str, mutate) -> None:
    page = model.doc[0]
    for annot in page.annots() or []:
        payload = json.loads(annot.info.get("content") or "{}")
        if payload.get("object_id") != object_id:
            continue
        mutate(payload)
        annot.set_info(
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            subject="pdf_editor_image_object",
        )
        annot.update()
        return
    raise AssertionError(f"marker not found: {object_id}")


def test_delete_rolls_back_document_and_bookkeeping_when_index_refresh_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _open_model(tmp_path)
    try:
        model.add_textbox(1, fitz.Rect(40, 60, 180, 110), "ROLLBACK", font="helv")
        hit = model.get_object_info_at_point(1, fitz.Point(70, 80))
        assert hit is not None
        before_render = _render_digest(model)
        before_pending = list(model.pending_edits)
        before_count = model.edit_count

        monkeypatch.setattr(
            model.block_manager,
            "rebuild_page",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected index failure")),
        )

        with pytest.raises(RuntimeError, match="injected index failure"):
            model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))

        assert _render_digest(model) == before_render
        restored = model.get_object_info_at_point(1, fitz.Point(70, 80))
        assert restored is not None and restored.object_id == hit.object_id
        assert model.pending_edits == before_pending
        assert model.edit_count == before_count
        assert model._active_session().secure_save_required is False
    finally:
        model.close()


def test_app_image_redaction_failure_propagates_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _open_model(tmp_path)
    try:
        oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes())
        before = _render_digest(model)

        def _fail_redaction(_page, *args, **kwargs):
            raise RuntimeError("injected redaction failure")

        monkeypatch.setattr(fitz.Page, "apply_redactions", _fail_redaction)
        with pytest.raises(RuntimeError, match="injected redaction failure"):
            model.delete_object(DeleteObjectRequest(oid, "image", 1))

        assert _render_digest(model) == before
        assert model.get_object_info_at_point(1, fitz.Point(60, 80)) is not None
        assert model._active_session().secure_save_required is False
    finally:
        model.close()


def test_successful_delete_sets_secure_latch_without_live_full_gc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _open_model(tmp_path)
    try:
        oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes())
        monkeypatch.setattr(
            model,
            "_roundtrip_live_doc",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live full GC forbidden")),
        )

        assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True
        assert model._active_session().secure_save_required is True
    finally:
        model.close()


def test_batch_delete_is_all_or_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = _open_model(tmp_path)
    try:
        first = model.add_image_object(1, fitz.Rect(20, 20, 100, 100), _png_bytes())
        second = model.add_image_object(1, fitz.Rect(180, 20, 260, 100), _png_bytes((0, 0, 255)))
        before = _render_digest(model)
        original = fitz.Page.apply_redactions
        calls = 0

        def _fail_second(page, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("second delete failed")
            return original(page, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "apply_redactions", _fail_second)
        with pytest.raises(RuntimeError, match="second delete failed"):
            pdf_object_ops.delete_objects_atomic(
                model,
                [
                    DeleteObjectRequest(first, "image", 1),
                    DeleteObjectRequest(second, "image", 1),
                ],
            )

        assert _render_digest(model) == before
        assert _image_marker(model, first)
        assert _image_marker(model, second)
        assert model._active_session().secure_save_required is False
    finally:
        model.close()


def test_new_image_marker_has_digest_and_stale_xref_is_refreshed(tmp_path: Path) -> None:
    model = _open_model(tmp_path)
    try:
        oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes())
        _annot, original = _image_marker(model, oid)
        assert len(original["image_digest"]) == 64
        actual_xref = original["xref"]
        _rewrite_marker(model, oid, lambda payload: payload.__setitem__("xref", 999999))

        assert model.move_object(
            MoveObjectRequest(oid, "image", 1, 1, fitz.Rect(160, 60, 260, 140))
        ) is True
        _annot, refreshed = _image_marker(model, oid)
        assert refreshed["xref"] == actual_xref
        assert refreshed["image_digest"] == original["image_digest"]
    finally:
        model.close()


def test_reused_xref_number_is_rejected_when_digest_and_geometry_disagree(tmp_path: Path) -> None:
    model = _open_model(tmp_path)
    try:
        first = model.add_image_object(1, fitz.Rect(20, 20, 100, 100), _png_bytes((255, 0, 0)))
        second = model.add_image_object(1, fitz.Rect(180, 20, 260, 100), _png_bytes((0, 0, 255)))
        _annot, second_payload = _image_marker(model, second)
        _rewrite_marker(
            model,
            first,
            lambda payload: payload.__setitem__("xref", second_payload["xref"]),
        )

        assert model.move_object(
            MoveObjectRequest(first, "image", 1, 1, fitz.Rect(20, 120, 100, 200))
        ) is True
        _annot, refreshed = _image_marker(model, first)
        assert refreshed["xref"] != second_payload["xref"]
    finally:
        model.close()


def test_unique_legacy_marker_falls_back_and_ambiguous_legacy_marker_fails(tmp_path: Path) -> None:
    model = _open_model(tmp_path)
    try:
        unique = model.add_image_object(1, fitz.Rect(20, 20, 100, 100), _png_bytes())

        def _legacy(payload: dict) -> None:
            payload.pop("image_digest", None)
            payload["xref"] = 999999

        _rewrite_marker(model, unique, _legacy)
        assert model.move_object(
            MoveObjectRequest(unique, "image", 1, 1, fitz.Rect(20, 120, 100, 200))
        ) is True
        _annot, migrated = _image_marker(model, unique)
        assert len(migrated["image_digest"]) == 64
        assert migrated["xref"] != 999999

        rect = fitz.Rect(180, 20, 260, 100)
        model.add_image_object(1, rect, _png_bytes((0, 255, 0)))
        ambiguous = model.add_image_object(1, rect, _png_bytes((0, 0, 255)))
        _rewrite_marker(model, ambiguous, _legacy)
        assert model.move_object(
            MoveObjectRequest(ambiguous, "image", 1, 1, fitz.Rect(180, 120, 260, 200))
        ) is False
    finally:
        model.close()
