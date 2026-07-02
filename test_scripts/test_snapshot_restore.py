# test_scripts/test_snapshot_restore.py
from __future__ import annotations
import fitz
from model.pdf_model import PDFModel


def _model(n: int) -> PDFModel:
    doc = fitz.open()
    for i in range(n):
        doc.new_page().insert_text((50, 50), f"Page {i + 1}")
    m = PDFModel.__new__(PDFModel)
    m.doc = doc
    return m


def test_restore_preserves_page_count():
    m = _model(3)
    snap = m._capture_page_snapshot(0)
    n = m.doc.page_count
    m._restore_page_from_snapshot(0, snap)
    assert m.doc.page_count == n, f"Restore changed page count {n}→{m.doc.page_count}"


def test_restore_is_idempotent():
    m = _model(2)
    snap = m._capture_page_snapshot(0)
    m._restore_page_from_snapshot(0, snap)
    n = m.doc.page_count
    m._restore_page_from_snapshot(0, snap)
    assert m.doc.page_count == n, "Second restore changed page count"


def test_restore_validates_xref_table():
    m = _model(2)
    snap = m._capture_page_snapshot(0)
    m._restore_page_from_snapshot(0, snap)
    assert m.doc.xref_length() > 0, "xref table corrupted after restore"
