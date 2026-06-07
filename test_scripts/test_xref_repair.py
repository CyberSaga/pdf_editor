"""Auto-repair of a damaged XREF table when a PDF is opened.

Mission: 開檔自動修復 XREF 表. PyMuPDF rebuilds a broken cross-reference table when
it opens a damaged PDF (``doc.is_repaired``). On open the editor round-trips that
document in memory so the active document carries a clean, internally-consistent
xref; healthy files are left untouched (still file-backed, no needless rewrite).
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_model import PDFModel  # noqa: E402


def _valid_pdf_bytes() -> bytes:
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 60), f"xref-repair-page-{i}", fontsize=14, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def _corrupt_startxref(data: bytes) -> bytes:
    # Point the final startxref offset at a bogus location so the xref table
    # cannot be read there and MuPDF must rebuild it on open.
    return re.sub(rb"startxref\s+\d+", b"startxref\n9999999", data, count=1)


def _encrypted_pdf_bytes(*, user_pw: str, owner_pw: str = "owner-secret") -> bytes:
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 60), f"secret-page-{i}", fontsize=14, fontname="helv")
    data = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=owner_pw, user_pw=user_pw
    )
    doc.close()
    return data


def _is_encrypted(doc: fitz.Document) -> bool:
    return bool((doc.metadata or {}).get("encryption"))


def test_open_damaged_pdf_auto_repairs_in_memory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken.pdf"
        broken.write_bytes(_corrupt_startxref(_valid_pdf_bytes()))

        # Sanity: the corrupted file must actually trigger MuPDF's repair path.
        probe = fitz.open(str(broken))
        assert bool(getattr(probe, "is_repaired", False)) is True, (
            "test fixture did not produce a repairable xref"
        )
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(broken))

            # The active document must have been repaired in memory: a clean
            # xref (not flagged as repaired) and a memory-backed handle (the
            # round-trip drops the original file name).
            assert model.doc is not None
            assert bool(getattr(model.doc, "is_repaired", False)) is False, (
                "damaged document was not auto-repaired on open"
            )
            assert model.doc.name == "", (
                "repaired document should be memory-backed (round-tripped)"
            )

            # Content and structure are preserved through the repair.
            assert model.doc.page_count == 2
            assert "xref-repair-page-0" in model.doc[0].get_text("text")
        finally:
            model.close()


def test_open_damaged_encrypted_pdf_keeps_encryption() -> None:
    # Regression guard: auto-repair must NOT strip encryption. Round-tripping an
    # authenticated encrypted doc through tobytes() emits a *decrypted* PDF, so a
    # later save-back would silently drop the password. A damaged+encrypted file
    # must skip the in-memory round-trip and stay encrypted (MuPDF's repaired doc
    # is still usable; a later full save with encryption=KEEP preserves it).
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken-encrypted.pdf"
        broken.write_bytes(_corrupt_startxref(_encrypted_pdf_bytes(user_pw="user-pw")))

        # Sanity: the fixture is both encrypted and triggers MuPDF's repair path.
        probe = fitz.open(str(broken))
        assert probe.needs_pass  # int 1 from PyMuPDF
        assert bool(getattr(probe, "is_repaired", False)) is True, (
            "test fixture did not produce a repairable xref"
        )
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(broken), password="user-pw")

            assert model.doc is not None
            # Encryption must survive the open (in-memory half of the guarantee).
            assert _is_encrypted(model.doc), (
                "auto-repair stripped encryption from a damaged encrypted PDF"
            )
            # Encrypted docs skip the in-memory round-trip, so the handle stays
            # file-backed; a later full save (encryption=KEEP) keeps the password.
            assert model.doc.name != "", (
                "encrypted document must not be round-tripped to a memory handle"
            )
            assert model.doc.page_count == 2
            assert "secret-page-0" in model.doc[0].get_text("text")

            # The real, end-to-end guarantee: saving back to disk must NOT strip
            # the password. A repaired doc full-rewrites (no incremental save), so
            # the full-save path must pass encryption=KEEP.
            model.save_as(str(broken))
        finally:
            model.close()

        reopened = fitz.open(str(broken))
        try:
            assert reopened.needs_pass, "save-back stripped the user password"
            assert reopened.authenticate("user-pw") in (2, 4, 6), (
                "saved file no longer accepts the original password"
            )
            # And the rewrite produced a clean xref with content intact.
            assert bool(getattr(reopened, "is_repaired", False)) is False
            assert "secret-page-0" in reopened[0].get_text("text")
        finally:
            reopened.close()


def test_open_damaged_owner_only_pdf_keeps_encryption() -> None:
    # Owner-password-only PDFs open without a password (needs_pass / is_encrypted
    # are both False), so the flag-based checks miss them; only the metadata
    # encryption string survives. The round-trip would still strip the owner
    # restrictions, so this case must also be skipped.
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken-owner-only.pdf"
        broken.write_bytes(_corrupt_startxref(_encrypted_pdf_bytes(user_pw="")))

        probe = fitz.open(str(broken))
        assert not probe.needs_pass  # empty user password → opens freely
        assert bool(getattr(probe, "is_repaired", False)) is True
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(broken))

            assert model.doc is not None
            assert _is_encrypted(model.doc), (
                "auto-repair stripped owner-only encryption from a damaged PDF"
            )
            assert model.doc.name != "", (
                "owner-encrypted document must not be round-tripped to memory"
            )
            assert model.doc.page_count == 2

            # Save-back must preserve the owner encryption (no password to enter,
            # but the encryption dict / restrictions must survive the rewrite).
            model.save_as(str(broken))
        finally:
            model.close()

        reopened = fitz.open(str(broken))
        try:
            assert _is_encrypted(reopened), (
                "save-back stripped owner-only encryption"
            )
            assert bool(getattr(reopened, "is_repaired", False)) is False
        finally:
            reopened.close()


def test_open_healthy_pdf_is_left_file_backed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        healthy = Path(tmp) / "healthy.pdf"
        healthy.write_bytes(_valid_pdf_bytes())

        # Sanity: a clean file does not trigger MuPDF's repair path.
        probe = fitz.open(str(healthy))
        assert bool(getattr(probe, "is_repaired", False)) is False
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(healthy))

            # A healthy file must NOT be round-tripped: it stays file-backed so
            # incremental save-to-original keeps working and open stays cheap.
            assert model.doc is not None
            assert bool(getattr(model.doc, "is_repaired", False)) is False
            assert Path(model.doc.name).resolve() == healthy.resolve(), (
                "healthy document should remain file-backed (no needless rewrite)"
            )
            assert model.doc.page_count == 2
        finally:
            model.close()
