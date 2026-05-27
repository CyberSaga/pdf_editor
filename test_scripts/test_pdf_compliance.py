"""AC-8 — PDF conformance evidence.

Verifies model/pdf_validator.check_pdf_conformance reports a clean bill of health
for a well-formed PDF and flags a deliberately corrupted cross-reference table
(the condition the XREF-repair feature exists to fix).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from model.pdf_validator import check_pdf_conformance, is_pdf_conformant

REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD_PDF = REPO_ROOT / "test_files" / "01_報告書.pdf"


def _make_valid_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "conformance fixture", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_well_formed_pdf_reports_no_issues() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "good.pdf"
        _make_valid_pdf(path)
        assert check_pdf_conformance(str(path)) == []
        assert is_pdf_conformant(str(path)) is True


def test_repository_sample_pdf_is_conformant() -> None:
    if not GOOD_PDF.exists():
        import pytest

        pytest.skip("sample PDF fixture missing")
    assert check_pdf_conformance(str(GOOD_PDF)) == []


def test_damaged_xref_is_flagged() -> None:
    """A corrupted startxref offset forces PyMuPDF to rebuild the xref on open;
    the validator must surface this as a conformance issue."""
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.pdf"
        _make_valid_pdf(good)
        data = good.read_bytes()
        idx = data.rfind(b"startxref")
        assert idx != -1
        broken = Path(tmp) / "broken.pdf"
        broken.write_bytes(data[:idx] + b"startxref\n999999\n%%EOF\n")

        issues = check_pdf_conformance(str(broken))
        assert issues, "expected at least one conformance issue for a damaged xref"
        assert any("cross-reference" in issue for issue in issues)
        assert is_pdf_conformant(str(broken)) is False


def test_unopenable_file_reports_issue() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        not_a_pdf = Path(tmp) / "nope.pdf"
        not_a_pdf.write_bytes(b"this is not a pdf at all")
        issues = check_pdf_conformance(str(not_a_pdf))
        assert issues  # must not silently pass


def test_encrypted_pdf_is_reported_not_silently_passed() -> None:
    """An un-authenticated encrypted PDF cannot be validated and must be flagged
    rather than returning a misleading clean result."""
    with tempfile.TemporaryDirectory() as tmp:
        enc = Path(tmp) / "enc.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((50, 50), "secret")
        doc.save(
            str(enc),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
        doc.close()
        issues = check_pdf_conformance(str(enc))
        assert issues
        assert any("encrypt" in issue.lower() for issue in issues)
