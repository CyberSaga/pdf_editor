"""Red-light tests: text_commit must never poison a live encrypted document.

``tobytes()`` defaults to ``encryption=NONE`` (decrypt-on-serialize).  Calling
it on a *live, authenticated, encrypted* handle silently corrupts that
handle's internal crypt state — a measured PyMuPDF AES quirk already pinned
by ``test_secure_persistence`` and already guarded in
``PDFModel._decrypted_snapshot_bytes``, ``engine.py:_build_scratch_copy`` and
the V0e reopen probe.  The damage surfaces only at the *next* save, far from
the cause: the file is written successfully, ``needs_pass`` still looks
normal, and the content streams no longer decrypt.

Two call sites in ``model/text_commit`` were still unguarded:
``preview.py:open_preview_session`` (reachable behind ``TEXT_COMMIT_PREVIEW=
plan``) and ``verify.py:_ocg_membership_lost``.  These tests pin the
non-corruption contract for both, plus the plan-validity property the fix
must not break: an encrypted session's snapshot has to stay byte-valid for
plans that will be applied to the live document.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_tier0_plan  # noqa: E402
from model.text_commit.preview import open_preview_session  # noqa: E402
from model.text_commit.verify import _ocg_membership_lost  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
USER_PW = "user-secret"
OWNER_PW = "owner-secret"


def _tier0_doc() -> fitz.Document:
    """Page whose only content is a raw literal-Tj stream (Tier 0 eligible)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref,
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET",
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _encrypted_tier0_pdf(tmp_path: Path) -> Path:
    """The same Tier 0 page, saved AES-256 encrypted."""
    doc = _tier0_doc()
    path = tmp_path / "encrypted.pdf"
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=OWNER_PW,
        user_pw=USER_PW,
    )
    doc.close()
    return path


def _authenticated(path: Path) -> fitz.Document:
    doc = fitz.open(str(path))
    assert doc.needs_pass, "fixture must actually be encrypted"
    assert doc.authenticate(USER_PW) > 0
    return doc


def _assert_live_handle_still_saves_intact(
    doc: fitz.Document, out_path: Path
) -> None:
    """The live handle's crypt state survived: a KEEP save still decrypts.

    This is the assertion that catches the poisoning.  A corrupted handle
    still *saves successfully* — the failure only appears on reopen, as
    stripped encryption or as content streams that no longer decode.
    """
    doc.save(str(out_path), encryption=fitz.PDF_ENCRYPT_KEEP)
    reopened = fitz.open(str(out_path))
    try:
        assert reopened.needs_pass, "encryption was silently stripped"
        assert reopened.authenticate(USER_PW) > 0
        assert TARGET in reopened[0].get_text(), "content streams no longer decrypt"
    finally:
        reopened.close()


def test_open_preview_session_does_not_poison_live_encrypted_document(tmp_path):
    """The defect, against the current call signature.

    ``controller/pdf_controller.py`` opens a preview session on
    ``self.model.doc`` — the live handle — on the first keystroke of an edit
    session.  On an encrypted document that must not damage the document the
    user is editing, whether or not a preview can actually be produced.
    """
    doc = _authenticated(_encrypted_tier0_pdf(tmp_path))
    try:
        open_preview_session(doc, 0, "session-1")
        _assert_live_handle_still_saves_intact(doc, tmp_path / "after-preview.pdf")
    finally:
        doc.close()


def test_open_preview_session_snapshot_stays_plan_valid_on_encrypted_doc(tmp_path):
    """Non-corruption must not cost plan validity.

    The whole point of the session snapshot is that plans prepared on it are
    byte-valid on the live document.  A fix that merely stopped decrypting
    would hand the renderer a locked scratch and silently kill preview on
    every encrypted file, so pin the real property: with the password
    available, the snapshot still yields a ``PreparedEdit`` whose byte range
    matches the *live* document's stream.
    """
    doc = _authenticated(_encrypted_tier0_pdf(tmp_path))
    try:
        session = open_preview_session(doc, 0, "session-1", password=USER_PW)
        assert session is not None, "an authenticated session must be available"

        scratch = fitz.open("pdf", session.snapshot_bytes)
        try:
            assert not scratch.needs_pass, "renderer opens the scratch with no password"
            prepared = prepare_tier0_plan(
                scratch,
                scratch[0],
                target_text=TARGET,
                replacement_text=REPLACEMENT,
                expected_origin=None,
                target_bbox=None,
                registry=DocumentFontRegistry(scratch),
            )
            assert isinstance(prepared, PreparedEdit), prepared
        finally:
            scratch.close()

        # The offsets are into decoded stream bytes, so they must address the
        # same bytes on the live (encrypted) document.
        live_stream = doc.xref_stream(prepared.replacement.stream_xref) or b""
        spliced = live_stream[
            prepared.replacement.start : prepared.replacement.end
        ]
        assert spliced == prepared.replacement.expected_bytes

        _assert_live_handle_still_saves_intact(doc, tmp_path / "after-plan.pdf")
    finally:
        doc.close()


def test_open_preview_session_refuses_encrypted_doc_without_password(tmp_path):
    """No password: refuse the session rather than guess or corrupt.

    Returning ``None`` lets the controller fall back to the legacy CSS
    preview without claiming exactness — the same refusal shape
    ``_build_scratch_copy`` already uses.
    """
    doc = _authenticated(_encrypted_tier0_pdf(tmp_path))
    try:
        assert open_preview_session(doc, 0, "session-1", password=None) is None
        _assert_live_handle_still_saves_intact(doc, tmp_path / "after-refusal.pdf")
    finally:
        doc.close()


def test_open_preview_session_unchanged_for_unencrypted_documents(tmp_path):
    """KEEP is a no-op on unencrypted docs: one code path, same result."""
    doc = _tier0_doc()
    try:
        session = open_preview_session(doc, 0, "session-1")
        assert session is not None
        assert session.page_number == 0
        assert session.session_key == "session-1"

        scratch = fitz.open("pdf", session.snapshot_bytes)
        try:
            assert not scratch.needs_pass
            assert TARGET in scratch[0].get_text()
        finally:
            scratch.close()
    finally:
        doc.close()


def test_ocg_membership_probe_does_not_poison_live_encrypted_document(tmp_path):
    """``verify.py`` V0d's OCG probe is the same unguarded pattern.

    Latent today (it runs on an already-decrypted scratch), but Task 11 would
    promote it onto documents reached from the live handle, so pin the
    contract before that happens rather than after.
    """
    doc = _authenticated(_encrypted_tier0_pdf(tmp_path))
    try:
        _ocg_membership_lost(doc, TARGET)
        _assert_live_handle_still_saves_intact(doc, tmp_path / "after-ocg.pdf")
    finally:
        doc.close()
