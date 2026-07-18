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
from view.pdf_view import PDFView


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


def test_note_drag_bar_is_visually_identifiable_as_a_grab_handle(qapp) -> None:
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
    try:
        assert note.drag_bar.styleSheet().strip() != ""
        assert note.drag_bar.cursor().shape() in (Qt.SizeAllCursor, Qt.OpenHandCursor)
    finally:
        note.close()
        parent.close()
        qapp.processEvents()


def test_delete_button_closes_the_popup(qapp) -> None:
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
    deleted: list[tuple[int, int]] = []
    note.delete_requested.connect(lambda page, xref: deleted.append((page, xref)))
    parent.show()
    note.show()
    qapp.processEvents()
    try:
        note.delete_button.click()
        qapp.processEvents()
        # Deleting the annotation must dismiss the popup that edits it — otherwise the
        # popup keeps showing/editing a now-nonexistent xref.
        assert deleted == [(0, 12)]
        assert note.isVisible() is False
    finally:
        parent.close()
        qapp.processEvents()


def _live_view_controller(tmp_path: Path, names: list[str]) -> tuple[PDFView, PDFController, PDFModel, list[str]]:
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    sids: list[str] = []
    for name in names:
        path = tmp_path / f"{name}.pdf"
        _make_pdf(path)
        controller.open_pdf(str(path))
        sids.append(model.get_active_session_id())
    return view, controller, model, sids


def _note_dto(model: PDFModel, sid: str, text: str) -> dict:
    model.activate_session(sid)
    xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), text)
    return {
        "page_num": 0,
        "xref": xref,
        "rect": fitz.Rect(40, 50, 60, 70),
        "text": text,
        "kind": "note",
        "read_only": False,
    }


def test_closing_the_popups_owning_tab_dismisses_the_popup(qapp, tmp_path: Path) -> None:
    view, controller, model, sids = _live_view_controller(tmp_path, ["docA", "docB"])
    sid_a, sid_b = sids
    try:
        # Make A active, then open a note popup that belongs to A.
        controller.on_tab_changed(model.session_ids.index(sid_a))
        qapp.processEvents()
        dto = _note_dto(model, sid_a, "note on A")
        controller.load_annotations()
        view._show_floating_note(dto)
        note = view._floating_note
        assert note is not None

        controller.on_tab_close_requested(model.session_ids.index(sid_a))
        qapp.processEvents()

        # Closing the note's owning tab must dismiss the popup; otherwise it floats
        # over whatever tab is now active and can mutate the wrong document.
        assert view._floating_note is None
        assert note.isVisible() is False
    finally:
        view.close()
        model.close()
        qapp.processEvents()


def test_switching_away_from_owning_tab_severs_the_cross_session_mutation_path(
    qapp, tmp_path: Path
) -> None:
    view, controller, model, sids = _live_view_controller(tmp_path, ["docA", "docB"])
    sid_a, sid_b = sids
    # Give B its own note so we can prove A's stale popup never touches B's content.
    dto_b = _note_dto(model, sid_b, "B original")
    xref_b = dto_b["xref"]
    try:
        controller.on_tab_changed(model.session_ids.index(sid_a))
        qapp.processEvents()
        dto_a = _note_dto(model, sid_a, "note on A")
        controller.load_annotations()
        view._show_floating_note(dto_a)
        note = view._floating_note
        assert note is not None

        # Switch the active session to B. A left-open popup from A would now save/delete
        # against B (the active session), silently corrupting B's document.
        controller.on_tab_changed(model.session_ids.index(sid_b))
        qapp.processEvents()

        # The popup opened for A must no longer exist, so it can never fire into B.
        assert view._floating_note is None
        assert view._floating_note_sid is None
        assert note.isVisible() is False

        # B's own note is untouched: no stray write leaked from A's popup teardown.
        model.activate_session(sid_b)
        b_notes = model.tools.annotation.get_all_annotations()
        assert [n["xref"] for n in b_notes] == [xref_b]
        assert b_notes[0]["text"] == "B original"
    finally:
        view.close()
        model.close()
        qapp.processEvents()
