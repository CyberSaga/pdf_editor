from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from controller.pdf_controller import PDFController
from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel
from view.pdf_view import PDFView


def _make_pdf(path: Path, pages: int = 5) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((30, 50), f"PAGE-{index + 1}")
    doc.save(path)
    doc.close()


def test_toc_set_get_round_trip_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "toc.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        entries = [[1, "One", 1], [2, "Child", 2], [1, "Three", 3]]
        assert model.set_toc(entries) is True
        assert model.get_toc() == entries
        assert model.set_toc(entries) is False

        for invalid in (
            [[2, "bad", 1]],
            [[1, "", 1]],
            [[1, "bad page", 0]],
            [[1, "bad page", 6]],
            [[1, "root", 1], [3, "jump", 2]],
        ):
            with pytest.raises((TypeError, ValueError)):
                model.set_toc(invalid)
        assert model.get_toc() == entries
    finally:
        model.close()


def test_insert_blank_page_shifts_bookmarks_with_original_content(tmp_path: Path) -> None:
    path = tmp_path / "insert.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, "P1", 1], [1, "P2", 2], [1, "P5", 5]])
        model.insert_blank_page(2)
        assert model.get_toc() == [[1, "P1", 1], [1, "P2", 3], [1, "P5", 6]]
    finally:
        model.close()


def test_delete_pages_remaps_deleted_targets_to_nearest_survivor(tmp_path: Path) -> None:
    path = tmp_path / "delete.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, f"P{i}", i] for i in range(1, 6)])
        model.delete_pages([2, 4])
        assert model.get_toc() == [
            [1, "P1", 1],
            [1, "P2", 2],
            [1, "P3", 2],
            [1, "P4", 3],
            [1, "P5", 3],
        ]
    finally:
        model.close()


def test_move_page_remaps_bookmarks_by_final_index(tmp_path: Path) -> None:
    path = tmp_path / "move.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, f"P{i}", i] for i in range(1, 6)])
        model.move_page(0, 2)
        assert model.get_toc() == [
            [1, "P1", 3],
            [1, "P2", 1],
            [1, "P3", 2],
            [1, "P4", 4],
            [1, "P5", 5],
        ]
    finally:
        model.close()


def test_delete_all_placeholder_clamps_every_bookmark_to_page_one(tmp_path: Path) -> None:
    path = tmp_path / "all.pdf"
    _make_pdf(path, pages=3)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, "A", 1], [1, "B", 3]])
        model.delete_pages([1, 2, 3])
        assert model.blank_placeholder_active is True
        assert model.get_toc() == [[1, "A", 1], [1, "B", 1]]
    finally:
        model.close()


def test_view_toc_tree_preserves_nesting_and_emits_navigation(qapp) -> None:
    view = PDFView()
    activated: list[int] = []
    view.sig_bookmark_activated.connect(activated.append)
    try:
        view.populate_toc([[1, "Root", 1], [2, "Child", 3], [1, "Other", 5]])
        assert view.bookmark_tree.topLevelItemCount() == 2
        root = view.bookmark_tree.topLevelItem(0)
        assert root.text(0) == "Root"
        assert root.childCount() == 1
        child = root.child(0)
        assert child.text(0) == "Child"
        view._on_bookmark_activated(child, 0)
        assert activated == [2]
    finally:
        view.close()
        qapp.processEvents()


def test_controller_toc_update_records_snapshot() -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = MagicMock()
    controller.model.doc.__len__ = lambda _self=None: 5
    controller.model._capture_doc_snapshot.side_effect = [b"before", b"after"]
    controller.model.set_toc.return_value = True
    controller.model.command_manager = MagicMock()
    controller.view = MagicMock(current_page=0)
    controller._worker_snapshot_cache = None
    controller.load_toc = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()

    controller.update_toc([[1, "Root", 1]])

    command = controller.model.command_manager.record.call_args.args[0]
    assert isinstance(command, SnapshotCommand)
    assert command._command_type == "update_toc"
    controller.load_toc.assert_called_once_with()
