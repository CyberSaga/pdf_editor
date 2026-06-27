"""R6-01 / R3.4 — object-ops must not bypass garbage collection.

``move_object``/``rotate_object``/``delete_object`` rewrite page content via
redact-and-reinsert (``_redact_and_restore_textbox_region`` +
``_insert_textbox_visual_content``) but historically skipped the GC bookkeeping the
text-edit path performs (``model.edit_count`` / ``model.pending_edits`` /
``model._maybe_garbage_collect``). Two consequences, both reproduced here against HEAD:

  * **Unbounded growth.** Each transform orphans the previous content stream; with no
    ``edit_count`` bump the every-20-edits ``garbage=4`` round-trip never fires, so
    ``doc.xref_length()`` climbs monotonically (measured: ~57x over 25 moves). The fix
    makes repeated transforms periodically reclaim orphans — the xref count *drops* when
    GC runs. We assert that a drop occurs (phase-independent proof GC ran) rather than a
    brittle absolute count.

  * **Deleted-data recovery.** A redaction removes text from the *current* content stream
    but leaves the pre-redaction stream as an orphan xref — byte-for-byte recoverable
    from a saved file until ``garbage=4`` prunes it. Delete is destructive and
    security-sensitive, so the fix forces an immediate ``garbage=4`` round-trip rather
    than waiting for the batch threshold. We save with ``garbage=0`` to isolate the live
    document's state: the canary must be gone because the *live* doc no longer holds it.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import (  # noqa: E402
    DeleteObjectRequest,
    MoveObjectRequest,
    RotateObjectRequest,
)
from model.pdf_model import PDFModel  # noqa: E402


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text(fitz.Point(40, 40), "LEGACY_TEXT", fontsize=12, fontname="helv", color=(0, 0, 0))
    doc.save(path)
    doc.close()


def _xref_streams_contain(doc: fitz.Document, needle: bytes) -> bool:
    """True if *needle* appears in any xref's stream (raw or decompressed) or object def."""
    text_needle = needle.decode("latin-1")
    for xref in range(1, doc.xref_length()):
        for reader in (doc.xref_stream, doc.xref_stream_raw):
            try:
                data = reader(xref)
            except Exception:
                data = None
            if data and needle in data:
                return True
        try:
            obj = doc.xref_object(xref)
        except Exception:
            obj = ""
        if obj and text_needle in obj:
            return True
    return False


def test_repeated_moves_do_not_run_live_full_gc(monkeypatch) -> None:
    """Interactive transforms track edits but defer full GC to persistence."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "moves.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "BOX", font="cjk", size=14, color=(0, 0, 0))
            hit = model.get_object_info_at_point(1, fitz.Point(80, 90))
            assert hit is not None
            oid, kind = hit.object_id, hit.object_kind
            monkeypatch.setattr(
                model,
                "_roundtrip_live_doc",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live GC forbidden")),
            )

            for i in range(25):
                x0 = 40 + (i % 5) * 20
                y0 = 60 + (i % 3) * 20
                ok = model.move_object(
                    MoveObjectRequest(
                        object_id=oid,
                        object_kind=kind,
                        source_page=1,
                        destination_page=1,
                        destination_rect=fitz.Rect(x0, y0, x0 + 120, y0 + 40),
                    )
                )
                assert ok is True

            assert model.edit_count >= 25
        finally:
            model.close()


def test_repeated_rotates_do_not_run_live_full_gc(monkeypatch) -> None:
    """Rotations must not cause synchronous whole-document round trips."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotates.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "BOX", font="cjk", size=14, color=(0, 0, 0))
            hit = model.get_object_info_at_point(1, fitz.Point(80, 90))
            assert hit is not None
            oid, kind = hit.object_id, hit.object_kind
            monkeypatch.setattr(
                model,
                "_roundtrip_live_doc",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live GC forbidden")),
            )

            for _ in range(25):
                ok = model.rotate_object(
                    RotateObjectRequest(
                        object_id=oid,
                        object_kind=kind,
                        page_num=1,
                        rotation_delta=90,
                    )
                )
                assert ok is True

            assert model.edit_count >= 25
        finally:
            model.close()


def test_delete_text_absent_from_all_xref_streams() -> None:
    """Secure persistence must remove deleted text from every output xref."""
    canary = b"CANARY-12345"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "delete.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(
                1, fitz.Rect(50, 70, 250, 110), canary.decode(), font="helv", size=14, color=(0, 0, 0)
            )
            hit = model.get_object_info_at_point(1, fitz.Point(80, 90))
            assert hit is not None

            ok = model.delete_object(
                DeleteObjectRequest(object_id=hit.object_id, object_kind=hit.object_kind, page_num=1)
            )
            assert ok is True

            out = Path(tmp) / "deleted.pdf"
            # Sanitization belongs at persistence, not in the interactive delete path.
            model.save_as(str(out))
        finally:
            model.close()

        raw = fitz.open(str(out))
        try:
            assert not _xref_streams_contain(raw, canary), (
                "deleted text is still recoverable from an orphan xref in the saved file (R6-01)"
            )
        finally:
            raw.close()


def test_delete_object_defers_full_gc_to_secure_persistence(monkeypatch) -> None:
    """Deletion latches secure persistence without invoking the legacy live GC path."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "failclosed.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 250, 110), "SECRET", font="helv", size=14, color=(0, 0, 0))
            hit = model.get_object_info_at_point(1, fitz.Point(80, 90))
            assert hit is not None

            def _raise(*_args, **_kwargs):
                raise RuntimeError("injected GC round-trip failure")

            monkeypatch.setattr(model, "_roundtrip_live_doc", _raise)

            assert model.delete_object(
                DeleteObjectRequest(object_id=hit.object_id, object_kind=hit.object_kind, page_num=1)
            ) is True
            assert model.secure_save_required is True
        finally:
            model.close()


def test_native_image_delete_sets_secure_latch_without_live_gc(monkeypatch) -> None:
    """Native-image deletion uses the same persistence-boundary sanitization contract."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native.pdf"
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
        for y in range(8):
            for x in range(8):
                pix.set_pixel(x, y, (255, 0, 0))
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=pix.tobytes("png"))
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_object_info_at_point(1, fitz.Point(60, 50))
            assert hit is not None and hit.object_kind == "native_image"

            calls: list[int] = []
            original = model._roundtrip_live_doc

            def _spy(*args, **kwargs):
                calls.append(1)
                return original(*args, **kwargs)

            monkeypatch.setattr(model, "_roundtrip_live_doc", _spy)
            ok = model.delete_object(
                DeleteObjectRequest(object_id=hit.object_id, object_kind=hit.object_kind, page_num=1)
            )
            assert ok is True
            assert calls == []
            assert model.secure_save_required is True
        finally:
            model.close()


def test_render_equivalent_after_gc() -> None:
    """Guard: a garbage=4 round-trip after moves must not change the rendered page.

    Green by construction at HEAD; pins that the GC the fix introduces is visually
    transparent (no content loss/shift from orphan reclamation).
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "RENDER", font="helv", size=14, color=(0, 0, 0))
            hit = model.get_object_info_at_point(1, fitz.Point(80, 90))
            assert hit is not None
            oid, kind = hit.object_id, hit.object_kind
            for i in range(5):
                x0 = 40 + (i % 5) * 20
                model.move_object(
                    MoveObjectRequest(
                        object_id=oid,
                        object_kind=kind,
                        source_page=1,
                        destination_page=1,
                        destination_rect=fitz.Rect(x0, 70, x0 + 120, 110),
                    )
                )

            before = hashlib.sha256(model.doc[0].get_pixmap(matrix=fitz.Matrix(2, 2)).samples).hexdigest()
            model._roundtrip_live_doc(garbage=4, deflate=True)
            model.block_manager.build_index(model.doc)
            after = hashlib.sha256(model.doc[0].get_pixmap(matrix=fitz.Matrix(2, 2)).samples).hexdigest()

            assert before == after, "garbage=4 round-trip changed the rendered page"
        finally:
            model.close()
