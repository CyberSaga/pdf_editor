"""R6.1 — characterization tests for ``PDFModel.get_print_watermarks``.

``get_print_watermarks`` (``pdf_model.py``) feeds the print path
(``pdf_controller`` -> print coordinator). It had **zero** test references
(census-verified, R6.1). Unlike ``WatermarkTool.get_watermarks`` (which returns
a *shallow* ``list(...)`` of the live dicts), ``get_print_watermarks`` does a
``json.loads(json.dumps(...))`` round-trip, so it returns a **deep copy**: a
caller that mutates the returned structure cannot corrupt the model's stored
watermarks. The print snapshot relies on that isolation, so it is pinned here.

Covered:
  * no watermarks -> empty list
  * an added watermark surfaces with its core fields (text/pages/angle)
  * unicode (CJK) text survives the ``ensure_ascii=False`` round-trip intact
  * deep-copy isolation: mutating the returned list/dicts does not leak back
    into the model (the property that distinguishes it from ``get_watermarks``)
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


def _make_pdf(path: Path, pages: int = 2) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def model_with_doc(tmp_path: Path):
    model = PDFModel()
    model.open_pdf(str(_make_pdf(tmp_path / "wm.pdf")))
    try:
        yield model
    finally:
        model.close()


def test_no_watermarks_returns_empty_list(model_with_doc) -> None:
    assert model_with_doc.get_print_watermarks() == []


def test_added_watermark_surfaces_core_fields(model_with_doc) -> None:
    model_with_doc.tools.watermark.add_watermark(pages=[1], text="DRAFT", angle=30.0)

    watermarks = model_with_doc.get_print_watermarks()

    assert len(watermarks) == 1
    wm = watermarks[0]
    assert wm["text"] == "DRAFT"
    assert wm["pages"] == [1]
    assert float(wm["angle"]) == 30.0


def test_unicode_text_survives_round_trip(model_with_doc) -> None:
    model_with_doc.tools.watermark.add_watermark(pages=[1], text="機密文件")

    watermarks = model_with_doc.get_print_watermarks()

    assert watermarks[0]["text"] == "機密文件"


def test_returned_structure_is_a_deep_copy(model_with_doc) -> None:
    model_with_doc.tools.watermark.add_watermark(pages=[1, 2], text="CONFIDENTIAL")

    snapshot = model_with_doc.get_print_watermarks()
    # Mutate both the outer list and a nested mutable field on the copy.
    snapshot[0]["text"] = "TAMPERED"
    snapshot[0]["pages"].append(999)
    snapshot.append({"id": "bogus"})

    fresh = model_with_doc.get_print_watermarks()
    assert len(fresh) == 1
    assert fresh[0]["text"] == "CONFIDENTIAL"
    assert 999 not in fresh[0]["pages"]
