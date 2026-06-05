from pathlib import Path

import fitz

from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel


def _make_three_page_doc(path: Path) -> Path:
    doc = fitz.open()
    for label in ("alpha", "beta", "gamma"):
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def test_insert_blank_page_rebuilds_inserted_page_and_marks_shifted_pages_stale(tmp_path) -> None:
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path / "three-pages.pdf")))
    model.ensure_page_index_built(1)
    model.ensure_page_index_built(2)

    model.insert_blank_page(2)

    assert model.block_manager.page_state(0) == "clean"
    assert model.block_manager.page_state(1) == "clean"
    assert model.block_manager.page_state(2) == "stale"


def test_shifted_page_is_rebuilt_on_demand_after_delete(tmp_path) -> None:
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path / "three-pages.pdf")))
    for page_num in (1, 2, 3):
        model.ensure_page_index_built(page_num)

    model.delete_pages([1])

    assert model.block_manager.page_state(0) == "clean"
    assert model.block_manager.page_state(1) == "stale"
    runs = model.block_manager.get_runs(0)
    assert any("beta" in run.text for run in runs)

    model.ensure_page_index_built(2)
    shifted_runs = model.block_manager.get_runs(1)
    assert any("gamma" in run.text for run in shifted_runs)
    assert model.block_manager.page_state(1) == "clean"


def test_insert_pages_from_file_rebuilds_inserted_pages_and_marks_shifted_pages_stale(tmp_path) -> None:
    base_path = _make_three_page_doc(tmp_path / "base.pdf")
    source_path = tmp_path / "source.pdf"
    source_doc = fitz.open()
    source_page = source_doc.new_page()
    source_page.insert_text((72, 72), "imported", fontsize=12, fontname="helv")
    source_doc.save(source_path)
    source_doc.close()

    model = PDFModel()
    model.open_pdf(str(base_path))
    model.ensure_page_index_built(1)
    model.ensure_page_index_built(2)

    model.insert_pages_from_file(str(source_path), [1], 2)

    inserted_runs = model.block_manager.get_runs(1)
    assert any("imported" in run.text for run in inserted_runs)
    assert model.block_manager.page_state(2) == "stale"


def test_structural_undo_avoids_full_rebuild_and_rebuilds_only_affected_pages(tmp_path, monkeypatch) -> None:
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path / "three-pages.pdf")))
    for page_num in (1, 2, 3):
        model.ensure_page_index_built(page_num)

    before = model._capture_doc_snapshot()
    model.delete_pages([1])
    after = model._capture_doc_snapshot()
    cmd = SnapshotCommand(model, "delete_pages", [1], before, after, "delete first page")

    def _fail_build_index(_doc) -> None:
        raise AssertionError("full rebuild should not be used for structural undo")

    monkeypatch.setattr(model.block_manager, "build_index", _fail_build_index)

    cmd.undo()

    assert model.block_manager.page_state(0) == "clean"
    assert model.block_manager.page_state(1) == "missing"


def test_insert_pages_from_file_returns_actual_insert_positions_after_validation(tmp_path) -> None:
    base_path = _make_three_page_doc(tmp_path / "base.pdf")
    source_path = tmp_path / "source.pdf"
    source_doc = fitz.open()
    source_page = source_doc.new_page()
    source_page.insert_text((72, 72), "imported", fontsize=12, fontname="helv")
    source_doc.save(source_path)
    source_doc.close()

    model = PDFModel()
    model.open_pdf(str(base_path))

    inserted_positions = model.insert_pages_from_file(str(source_path), [0, 1], 2)

    assert inserted_positions == [2]
    assert len(model.doc) == 4


def test_delete_pages_returns_actual_deleted_pages_after_validation(tmp_path) -> None:
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path / "three-pages.pdf")))

    deleted_pages = model.delete_pages([0, -1, 2, 2, 99])

    assert deleted_pages == [2]
    assert len(model.doc) == 2


def test_insert_blank_page_returns_actual_insert_position_after_validation(tmp_path) -> None:
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path / "three-pages.pdf")))

    inserted_pages = model.insert_blank_page(99)

    assert inserted_pages == [4]
    assert len(model.doc) == 4
