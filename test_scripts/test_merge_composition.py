"""R6.1 — characterization tests for ``PDFModel.compose_merged_document``.

This is the low-level merge primitive (``pdf_model.py``): the controller merge
flow (``merge_ordered_sources_into_current`` / ``save_ordered_sources_as_new``)
is exercised by ``test_pdf_merge_workflow.py``, but the model method that
actually stitches the ``fitz.Document`` together had **zero** test references
(census-verified, R6.1). It is exactly the kind of PyMuPDF glue that regresses
silently across a 1.25 -> 1.27 bump, so these tests pin its current behavior:

  * no open document -> ``ValueError``
  * ``source_kind == "current"`` inserts a snapshot of the live doc
  * ``source_kind == "file"`` inserts the foreign file's pages
  * list order is preserved across mixed source kinds
  * unknown ``source_kind`` and a ``"file"`` entry with no ``path`` are skipped
  * an empty / ``None`` source list yields an empty (0-page) document

Assertions check the produced document's page count *and* page text (side
effects / state), not just that an object came back (CLAUDE.md s5.2).
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_model import PDFModel  # noqa: E402


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _page_texts(doc: fitz.Document) -> list[str]:
    return ["".join(doc[i].get_text("text").split()) for i in range(len(doc))]


@pytest.fixture()
def model_with_current(tmp_path: Path):
    current = _make_pdf(tmp_path / "Current.pdf", ["CURRENTONE", "CURRENTTWO"])
    model = PDFModel()
    model.open_pdf(str(current))
    try:
        yield model
    finally:
        model.close()


def test_compose_without_open_document_raises() -> None:
    model = PDFModel()
    try:
        with pytest.raises(ValueError):
            model.compose_merged_document([{"source_kind": "current"}])
    finally:
        model.close()


def test_compose_current_source_inserts_live_snapshot(model_with_current) -> None:
    merged = model_with_current.compose_merged_document([{"source_kind": "current"}])
    try:
        assert len(merged) == 2
        assert _page_texts(merged) == ["CURRENTONE", "CURRENTTWO"]
    finally:
        merged.close()


def test_compose_file_source_inserts_foreign_pages(model_with_current, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRAPAGE"])
    merged = model_with_current.compose_merged_document(
        [{"source_kind": "file", "path": str(extra)}]
    )
    try:
        assert len(merged) == 1
        assert _page_texts(merged) == ["EXTRAPAGE"]
    finally:
        merged.close()


def test_compose_preserves_list_order_across_mixed_sources(model_with_current, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRAPAGE"])
    merged = model_with_current.compose_merged_document(
        [
            {"source_kind": "file", "path": str(extra)},
            {"source_kind": "current"},
        ]
    )
    try:
        # file first, then the two current pages, in declared order.
        assert _page_texts(merged) == ["EXTRAPAGE", "CURRENTONE", "CURRENTTWO"]
    finally:
        merged.close()


def test_compose_skips_unknown_kind_and_pathless_file(model_with_current) -> None:
    merged = model_with_current.compose_merged_document(
        [
            {"source_kind": "mystery"},
            {"source_kind": "file"},  # no path
            {"source_kind": "file", "path": ""},  # empty path
            None,  # malformed entry
        ]
    )
    try:
        assert len(merged) == 0
    finally:
        merged.close()


def test_compose_empty_sources_yields_empty_document(model_with_current) -> None:
    merged_empty = model_with_current.compose_merged_document([])
    merged_none = model_with_current.compose_merged_document(None)  # type: ignore[arg-type]
    try:
        assert len(merged_empty) == 0
        assert len(merged_none) == 0
    finally:
        merged_empty.close()
        merged_none.close()
