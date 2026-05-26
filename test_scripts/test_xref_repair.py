"""XREF table repair: rewrite a damaged PDF with a clean, rebuilt xref.

Mission: 修復 XREF 表. PyMuPDF auto-repairs a broken cross-reference table when it
opens a damaged PDF (``doc.is_repaired``); saving with full garbage collection
writes a fresh, consistent xref. The model exposes this as an explicit repair op.
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


def test_repair_document_xref_produces_clean_copy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken.pdf"
        repaired = Path(tmp) / "repaired.pdf"
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
            report = model.repair_document_xref(str(repaired))

            assert report["was_repaired_on_open"] is True
            assert report["output_path"] == str(repaired)
            assert repaired.exists() and repaired.stat().st_size > 0

            # The repaired copy must open without needing repair, with content kept.
            reopened = fitz.open(str(repaired))
            try:
                assert bool(getattr(reopened, "is_repaired", False)) is False, (
                    "repaired copy still has a damaged xref"
                )
                assert reopened.page_count == 2
                assert "xref-repair-page-0" in reopened[0].get_text("text")
            finally:
                reopened.close()
        finally:
            model.close()
