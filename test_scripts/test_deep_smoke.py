"""
test_deep_smoke.py — Pytest-collectable versions of the T8 edge-case and T2 undo/redo
scenarios from test_deep.py.

test_deep.py deliberately sets ``__test__ = False`` (it is a manual stress runner)
and importing it side-effects ``logging.disable(logging.CRITICAL)``.  These smoke
tests reproduce the same logical coverage in a standalone, CI-safe form.

T8 synthetic sub-tests (no sample PDFs required):
  8.1  Empty-content PDF (1 blank page)
  8.2  Tiny page (1 pt × 1 pt)
  8.3  Large page (A0)
  8.4  edit_text with degenerate rect (0,0,0,0) — graceful, no crash
  8.5  edit_text with out-of-range page_num — controlled exception only

T2 undo/redo cycle (synthetic PDF, no sample PDFs required):
  delete page → record SnapshotCommand → undo → assert page count restored
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blank_pdf_path(tmp_path: Path, n_pages: int = 1, text: str | None = None) -> str:
    """Write a minimal PDF and return the path string."""
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 100), text, fontsize=12, fontname="helv")
    pdf_path = tmp_path / f"smoke_{n_pages}p.pdf"
    pdf_path.write_bytes(doc.tobytes(garbage=0))
    doc.close()
    return str(pdf_path)


# ---------------------------------------------------------------------------
# T8 — edge cases (all self-contained, no sample PDFs needed)
# ---------------------------------------------------------------------------


def test_t8_empty_content_pdf_opens_without_crash(tmp_path: Path) -> None:
    """T8-8.1: 1-page blank PDF (no text) must open and return 0 blocks."""
    path = _blank_pdf_path(tmp_path, n_pages=1, text=None)
    model = PDFModel()
    model.open_pdf(path)
    model.ensure_page_index_built(1)
    blocks = model.block_manager.get_blocks(0)
    assert isinstance(blocks, list)  # must not crash; empty is fine
    model.close()


def test_t8_tiny_page_1pt_opens_without_crash(tmp_path: Path) -> None:
    """T8-8.2: 1 pt × 1 pt page must open without an unhandled exception."""
    doc = fitz.open()
    page = doc.new_page(width=1, height=1)
    try:
        page.insert_text((0, 0.8), "X", fontsize=0.5)
    except Exception:
        pass  # fitz may refuse sub-point text; that is acceptable
    pdf_path = tmp_path / "tiny.pdf"
    pdf_path.write_bytes(doc.tobytes(garbage=0))
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    assert len(model.doc) >= 1
    model.close()


def test_t8_large_a0_page_opens_without_crash(tmp_path: Path) -> None:
    """T8-8.3: A0-sized page (2384 × 3370 pt) must open without an unhandled exception."""
    doc = fitz.open()
    page = doc.new_page(width=2384, height=3370)
    page.insert_text((100, 200), "Large page test", fontsize=24, fontname="helv")
    pdf_path = tmp_path / "a0.pdf"
    pdf_path.write_bytes(doc.tobytes(garbage=0))
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    assert len(model.doc) >= 1
    model.close()


def test_t8_edit_text_degenerate_rect_does_not_crash(tmp_path: Path) -> None:
    """T8-8.4: edit_text with rect(0,0,0,0) must fail gracefully — no unhandled exception."""
    path = _blank_pdf_path(tmp_path, text="some content here")
    model = PDFModel()
    model.open_pdf(path)
    try:
        model.edit_text(
            page_num=1,
            rect=fitz.Rect(0, 0, 0, 0),
            new_text="degenerate rect test",
            font="helv",
            size=11.0,
            color=(0.0, 0.0, 0.0),
        )
        # If no exception: the model handled it gracefully.
    except (RuntimeError, ValueError, IndexError):
        pass  # Controlled exception is acceptable.
    # Must never raise AttributeError, TypeError, or any other unhandled exception.
    model.close()


def test_t8_edit_text_out_of_range_page_does_not_crash(tmp_path: Path) -> None:
    """T8-8.5: edit_text with page_num=9999 must raise a controlled exception or return."""
    path = _blank_pdf_path(tmp_path, text="test content")
    model = PDFModel()
    model.open_pdf(path)
    try:
        model.edit_text(
            page_num=9999,
            rect=fitz.Rect(0, 0, 100, 100),
            new_text="out of range",
            font="helv",
            size=11.0,
            color=(0.0, 0.0, 0.0),
        )
    except (IndexError, RuntimeError, ValueError):
        pass  # Controlled exception is the correct response.
    model.close()


# ---------------------------------------------------------------------------
# T2 — undo/redo cycle (synthetic PDF, no sample PDFs needed)
# ---------------------------------------------------------------------------


def test_t2_undo_redo_delete_page_restores_count(tmp_path: Path) -> None:
    """T2: delete page → record SnapshotCommand → undo → page count restored → redo."""
    doc = fitz.open()
    for i in range(3):
        p = doc.new_page(width=595, height=842)
        p.insert_text((72, 100), f"T2 page {i + 1}", fontsize=12, fontname="helv")
    pdf_path = tmp_path / "t2_sample.pdf"
    pdf_path.write_bytes(doc.tobytes(garbage=0))
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    assert len(model.doc) == 3

    before = model._capture_doc_snapshot()
    model.delete_pages([3])
    after = model._capture_doc_snapshot()
    assert len(model.doc) == 2

    cmd = SnapshotCommand(
        model=model,
        command_type="delete_pages",
        affected_pages=[3],
        before_bytes=before,
        after_bytes=after,
        description="delete page 3",
    )
    model.command_manager.record(cmd)
    assert model.command_manager.undo_count == 1

    # Undo: restore to 3 pages
    model.command_manager.undo()
    assert len(model.doc) == 3, (
        f"undo must restore original page count; got {len(model.doc)}"
    )
    assert model.command_manager.undo_count == 0
    assert model.command_manager.redo_count == 1

    # Redo: back to 2 pages
    model.command_manager.redo()
    assert len(model.doc) == 2, (
        f"redo must re-apply delete; got {len(model.doc)}"
    )
    assert model.command_manager.undo_count == 1
    assert model.command_manager.redo_count == 0

    model.close()


def test_t2_empty_undo_stack_returns_false_no_crash(tmp_path: Path) -> None:
    """T2: undo on an empty stack must return False without raising."""
    path = _blank_pdf_path(tmp_path)
    model = PDFModel()
    model.open_pdf(path)
    model.command_manager.clear()

    result = model.command_manager.undo()

    assert result is False, f"empty-stack undo must return False; got {result!r}"
    assert model.command_manager.undo_count == 0
    model.close()
