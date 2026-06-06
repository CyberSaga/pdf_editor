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
