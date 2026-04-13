"""
test_export_boundaries.py — File I/O edge cases for export_pages and save_as.

Covers:
- export_pages([], as_image=True) produces no output file
- export_pages([1], as_image=True, format=png) produces a non-empty PNG
- export_pages([1], as_image=True, format=jpg) produces a non-empty JPEG
- save_as to a read-only directory raises a permission-style error

These scenarios had zero test coverage before this file (grep confirmed).
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import fitz
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from model.pdf_model import PDFModel


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _make_single_page_pdf(tmp_path: Path) -> str:
    """Write a one-page PDF with readable text and return the path string."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "export boundary test", fontsize=12, fontname="helv")
    pdf_path = tmp_path / "src.pdf"
    pdf_path.write_bytes(doc.tobytes(garbage=0))
    doc.close()
    return str(pdf_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_export_pages_empty_list_image_mode_creates_no_file(tmp_path: Path) -> None:
    """export_pages([], as_image=True) must write nothing to disk."""
    model = PDFModel()
    model.open_pdf(_make_single_page_pdf(tmp_path))

    out = tmp_path / "should_not_exist.png"
    model.export_pages([], str(out), as_image=True)

    assert not out.exists(), "export_pages with empty list must not create any output file"
    model.close()


@pytest.mark.parametrize("image_format,ext", [("png", ".png"), ("jpg", ".jpg")])
def test_export_single_page_as_image_creates_non_empty_file(
    tmp_path: Path, image_format: str, ext: str
) -> None:
    """Exporting one page as image (PNG or JPEG) must produce a non-empty file."""
    model = PDFModel()
    model.open_pdf(_make_single_page_pdf(tmp_path))

    out = tmp_path / f"page{ext}"
    model.export_pages([1], str(out), as_image=True, dpi=72, image_format=image_format)

    assert out.exists(), f"export as {image_format.upper()} must create output file"
    assert out.stat().st_size > 0, f"exported {image_format.upper()} file must not be empty"
    model.close()


def test_save_as_readonly_directory_raises(tmp_path: Path) -> None:
    """save_as to a write-protected directory must raise PermissionError or OSError."""
    model = PDFModel()
    model.open_pdf(_make_single_page_pdf(tmp_path))

    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()

    # Remove write permission
    ro_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

    # Verify the chmod actually took effect; skip if the OS ignores it (e.g. Windows
    # running as admin, or NTFS ignoring POSIX bits).
    if os.access(str(ro_dir), os.W_OK):
        model.close()
        pytest.skip("OS did not honour chmod — read-only test not applicable here")

    target = ro_dir / "out.pdf"
    try:
        with pytest.raises((PermissionError, OSError, RuntimeError)):
            model.save_as(str(target))
    finally:
        # Always restore write permission so tmp_path cleanup succeeds
        ro_dir.chmod(stat.S_IRWXU)

    model.close()
