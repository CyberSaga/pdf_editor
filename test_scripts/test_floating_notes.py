from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import fitz
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from controller.pdf_controller import PDFController
from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel
from view.floating_note import FloatingNote


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=400, height=300)
    doc.save(path)
    doc.close()


def test_text_note_create_list_update_move_delete_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    output = tmp_path / "notes-saved.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), "first")
        notes = model.tools.annotation.get_all_annotations()

        assert len(notes) == 1
        note = notes[0]
        assert note["xref"] == xref
        assert note["kind"] == "note"
        assert note["read_only"] is False
        assert note["text"] == "first"
        assert note["rect"].width <= 40
        assert note["rect"].height <= 40

        assert model.tools.annotation.update_annotation(xref, "updated") is True
        moved = fitz.Rect(120, 130, 138, 148)
        assert model.tools.annotation.move_annotation(xref, moved) is True
        updated = model.tools.annotation.get_all_annotations()[0]
        assert updated["text"] == "updated"
        assert fitz.Rect(updated["rect"]).x0 >= 119

        model.save_as(str(output))
        model.close()
        model.open_pdf(str(output))
        reopened = model.tools.annotation.get_all_annotations()[0]
        assert reopened["text"] == "updated"
        assert reopened["kind"] == "note"

        assert model.tools.annotation.delete_annotation(reopened["xref"]) is True
        assert model.tools.annotation.get_all_annotations() == []
        assert model.tools.annotation.delete_annotation(999999) is False
    finally:
        model.close()


def test_legacy_freetext_remains_listed_read_only(tmp_path: Path) -> None:
    path = tmp_path / "legacy.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.add_freetext_annot(fitz.Rect(20, 20, 220, 70), "legacy").update()
    doc.save(path)
    doc.close()
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        annotation = model.tools.annotation.get_all_annotations()[0]
        assert annotation["kind"] == "freetext"
        assert annotation["read_only"] is True
        assert model.tools.annotation.update_annotation(annotation["xref"], "no") is False
        assert model.tools.annotation.move_annotation(
            annotation["xref"], fitz.Rect(50, 50, 250, 100)
        ) is False
    finally:
        model.close()


def _controller_for_note_snapshot() -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = MagicMock()
    controller.model.doc.__len__ = lambda _self=None: 3
    controller.model._capture_doc_snapshot.side_effect = [b"before", b"after"]
    controller.model.tools.annotation.update_annotation.return_value = True
    controller.model.tools.annotation.move_annotation.return_value = True
    controller.model.tools.annotation.delete_annotation.return_value = True
    controller.model.command_manager = MagicMock()
    controller.view = MagicMock(current_page=0)
    controller._invalidate_active_render_state = MagicMock()
    controller.show_page = MagicMock()
    controller.load_annotations = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()
    return controller


def test_controller_note_update_records_one_snapshot() -> None:
    controller = _controller_for_note_snapshot()

    controller.update_annotation_content(1, 77, "changed")

    controller.model.tools.annotation.update_annotation.assert_called_once_with(77, "changed")
    command = controller.model.command_manager.record.call_args.args[0]
    assert isinstance(command, SnapshotCommand)
    assert command._command_type == "update_annotation"
    assert command.affected_pages == [2]
    controller._invalidate_active_render_state.assert_called_once_with()
    controller.load_annotations.assert_called_once_with()


def test_controller_note_move_and_delete_are_snapshot_backed() -> None:
    moved = _controller_for_note_snapshot()
    rect = fitz.Rect(30, 40, 48, 58)
    moved.move_annotation_marker(0, 88, rect)
    move_command = moved.model.command_manager.record.call_args.args[0]
    assert move_command._command_type == "move_annotation"

    deleted = _controller_for_note_snapshot()
    deleted.delete_annotation(0, 99)
    delete_command = deleted.model.command_manager.record.call_args.args[0]
    assert delete_command._command_type == "delete_annotation"


def test_floating_note_is_parented_and_popup_drag_is_ui_only(qapp) -> None:
    parent = QWidget()
    parent.resize(800, 600)
    note = FloatingNote(
        {
            "xref": 12,
            "page_num": 0,
            "rect": fitz.Rect(20, 30, 38, 48),
            "text": "hello",
            "kind": "note",
            "read_only": False,
        },
        parent=parent,
    )
    saved: list[tuple[int, int, str]] = []
    moved_markers: list[tuple[int, int, QRectF]] = []
    note.save_requested.connect(lambda page, xref, text: saved.append((page, xref, text)))
    note.marker_move_requested.connect(
        lambda page, xref, rect: moved_markers.append((page, xref, rect))
    )
    parent.show()
    note.show()
    qapp.processEvents()
    try:
        assert note.parentWidget() is parent
        assert note.isWindow() is False
        start = note.pos()
        QTest.mousePress(note.drag_bar, Qt.LeftButton, pos=QPoint(10, 8))
        QTest.mouseMove(note.drag_bar, QPoint(70, 58), delay=10)
        QTest.mouseRelease(note.drag_bar, Qt.LeftButton, pos=QPoint(70, 58))
        assert (note.pos() - start).manhattanLength() >= 50
        assert moved_markers == []

        note.editor.setPlainText("saved text")
        note.save_button.click()
        assert saved == [(0, 12, "saved text")]
    finally:
        note.close()
        parent.close()
        qapp.processEvents()
