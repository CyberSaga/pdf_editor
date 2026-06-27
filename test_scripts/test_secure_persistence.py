from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from model.pdf_model import PDFModel


CANARY = b"DELETED-PERSISTENCE-CANARY-74091"


def _make_orphaned_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), CANARY.decode("ascii"), fontsize=12)
    doc.save(path)
    doc.close()


def _make_encrypted_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page().insert_text((30, 60), "ENCRYPTED SOURCE")
    doc.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
        permissions=fitz.PDF_PERM_PRINT,
    )
    doc.close()


def _redact_canary_without_gc(model: PDFModel) -> None:
    page = model.doc[0]
    page.add_redact_annot(fitz.Rect(20, 35, 290, 75))
    page.apply_redactions()
    assert CANARY.decode("ascii") not in page.get_text("text")


def _contains_canary_anywhere(path: Path) -> bool:
    doc = fitz.open(path)
    try:
        for xref in range(1, doc.xref_length()):
            for reader in (doc.xref_stream, doc.xref_stream_raw):
                try:
                    data = reader(xref)
                except Exception:
                    data = None
                if data and CANARY in data:
                    return True
            try:
                if CANARY.decode("latin-1") in doc.xref_object(xref):
                    return True
            except Exception:
                pass
        return False
    finally:
        doc.close()


def test_secure_save_forces_full_gc_and_never_incremental(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "saved.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        _redact_canary_without_gc(model)
        model.secure_save_required = True

        calls: list[tuple[int, bool]] = []
        original = model._save_doc

        def _spy(doc, target, *, garbage=0, incremental=False):
            calls.append((garbage, incremental))
            return original(doc, target, garbage=garbage, incremental=incremental)

        monkeypatch.setattr(model, "_save_doc", _spy)
        model.save_as(str(output))

        assert calls and all(garbage == 4 and not incremental for garbage, incremental in calls)
        assert not _contains_canary_anywhere(output)
        assert model.secure_save_required is True
    finally:
        model.close()


def test_secure_overwrite_failure_preserves_existing_destination(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    _make_orphaned_pdf(source)
    destination.write_bytes(b"ORIGINAL-DESTINATION")

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.secure_save_required = True

        def _fail_replace(_src, _dst):
            raise OSError("injected atomic replace failure")

        monkeypatch.setattr("model.pdf_model.os.replace", _fail_replace)
        with pytest.raises(OSError, match="atomic replace failure"):
            model.save_as(str(destination))

        assert destination.read_bytes() == b"ORIGINAL-DESTINATION"
        assert model.doc is not None and not model.doc.is_closed
    finally:
        model.close()


def test_secure_print_snapshot_prunes_deleted_orphans(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    snapshot = tmp_path / "print.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        _redact_canary_without_gc(model)
        model.secure_save_required = True
        model.build_print_snapshot(snapshot)
        assert not _contains_canary_anywhere(snapshot)
    finally:
        model.close()


def test_secure_print_snapshot_forces_garbage_four(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    snapshot = tmp_path / "print.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.secure_save_required = True
        calls: list[int | None] = []
        original = model.doc.save

        def _spy(target, *args, **kwargs):
            calls.append(kwargs.get("garbage"))
            return original(target, *args, **kwargs)

        monkeypatch.setattr(model.doc, "save", _spy)
        model.build_print_snapshot(snapshot)
        assert calls == [4]
    finally:
        model.close()


def test_pdf_export_uses_sanitized_serialization_after_delete(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "export.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        _redact_canary_without_gc(model)
        model.secure_save_required = True
        model.export_pages([1], str(output), as_image=False)
        assert not _contains_canary_anywhere(output)
    finally:
        model.close()


def test_periodic_edit_maintenance_keeps_light_cleanup_but_never_full_gc(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.pending_edits = [{"page_idx": 0, "rect": fitz.Rect(0, 0, 10, 10)}]
        model.edit_count = 20
        calls: list[int] = []
        monkeypatch.setattr(
            model,
            "_roundtrip_live_doc",
            lambda **kwargs: calls.append(int(kwargs["garbage"])),
        )

        model._maybe_garbage_collect()

        assert calls == []
        assert model.pending_edits == []
    finally:
        model.close()


@pytest.mark.parametrize("secure", [False, True])
def test_watermark_save_preserves_encryption_and_user_role(
    tmp_path: Path, secure: bool
) -> None:
    source = tmp_path / "encrypted.pdf"
    output = tmp_path / "watermarked.pdf"
    _make_encrypted_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source), password="user-secret")
        model.tools.watermark.add_watermark([1], "CONFIDENTIAL")
        model.secure_save_required = secure
        model.save_as(str(output))
    finally:
        model.close()

    reopened = fitz.open(output)
    try:
        assert reopened.needs_pass
        assert reopened.authenticate("user-secret") == 2
        assert reopened.permissions != -4
    finally:
        reopened.close()


def test_page_delete_sets_secure_latch_and_rolls_back_whole_batch_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "pages.pdf"
    doc = fitz.open()
    for text in ("PAGE ONE", "PAGE TWO", "PAGE THREE"):
        doc.new_page().insert_text((30, 60), text)
    doc.save(source)
    doc.close()

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        original = fitz.Document.delete_page
        calls = 0

        def _fail_second(target, page_index):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected page-delete failure")
            return original(target, page_index)

        monkeypatch.setattr(fitz.Document, "delete_page", _fail_second)
        with pytest.raises(RuntimeError, match="page-delete failure"):
            model.delete_pages([1, 2])

        assert len(model.doc) == 3
        assert [model.doc[i].get_text().strip() for i in range(3)] == [
            "PAGE ONE",
            "PAGE TWO",
            "PAGE THREE",
        ]
        assert model.secure_save_required is False

        monkeypatch.setattr(fitz.Document, "delete_page", original)
        assert model.delete_pages([2]) == [2]
        assert model.secure_save_required is True
    finally:
        model.close()
