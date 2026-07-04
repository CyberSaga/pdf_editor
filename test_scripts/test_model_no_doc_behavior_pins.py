"""Behavior pins for PDFModel with NO open document (PR-7 refactor evidence).

These tests deliberately PIN CURRENT CRASH BEHAVIOR of the model when no
document is open. PR-7 replaces the flagged `self.doc`/`model.doc` accesses
with typed local binds (`doc: fitz.Document = self.doc`) purely to satisfy
mypy; the runtime semantics — including the exact exception raised when the
doc is None — must stay byte-identical. These pins prove that.

They assert on CRASH behavior on purpose. The current no-doc failure modes are
heterogeneous (TypeError here, silent no-op elsewhere), which is exactly why a
unified raising `_require_doc()` guard was REJECTED at design time (it would
change behavior). A future, behavior-allowed PR may unify the no-doc guards and
replace these pins accordingly.
"""

from __future__ import annotations

import fitz
import pytest

from model.pdf_model import PDFModel


def test_export_pages_as_image_no_doc_raises_typeerror(tmp_path):
    """Fresh model: as_image export hits `len(self.doc)` with doc=None.

    `self.doc` is None on a fresh model, so `1 <= page_num <= len(self.doc)`
    calls `len(None)` and raises TypeError. Pin that exact type.
    """
    model = PDFModel()
    assert model.doc is None
    with pytest.raises(TypeError):
        model.export_pages([1], str(tmp_path / "out.png"), as_image=True)


def test_edit_text_no_doc_raises_typeerror():
    """Fresh model: edit_text indexes `model.doc[page_idx]` with doc=None.

    `ensure_page_index_built(0)` returns silently (page_idx = -1 < 0), then
    `page = model.doc[page_idx]` subscripts None -> TypeError. Pin that.
    """
    model = PDFModel()
    assert model.doc is None
    with pytest.raises(TypeError):
        model.edit_text(0, fitz.Rect(0, 0, 10, 10), "x")


def test_repair_active_doc_in_memory_no_doc_returns_false():
    """Fresh model: `_repair_active_doc_in_memory` guard returns False on no doc."""
    model = PDFModel()
    assert model.doc is None
    assert model._repair_active_doc_in_memory() is False
