from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QDialog

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from view.dialogs.metadata import MetadataDialog
from view.pdf_view import PDFView

_EDITABLE_KEYS = {"title", "author", "subject", "keywords"}


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page()
    metadata = dict(doc.metadata or {})
    metadata.update(
        {
            "title": "Original",
            "author": "Original Author",
            "subject": "Original Subject",
            "keywords": "one,two",
            "creator": "Fixture Creator",
            "producer": "Fixture Producer",
            "creationDate": "D:20260716090000",
        }
    )
    doc.set_metadata(metadata)
    doc.save(path)
    doc.close()
    return path


def test_model_metadata_round_trip_preserves_unedited_standard_keys(tmp_path: Path) -> None:
    path = _make_pdf(tmp_path / "metadata.pdf")
    output = tmp_path / "metadata-saved.pdf"
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        assert model.get_editable_metadata() == {
            "title": "Original",
            "author": "Original Author",
            "subject": "Original Subject",
            "keywords": "one,two",
        }

        changed = model.set_editable_metadata(
            {
                "title": 2026,
                "author": "Updated Author",
                "subject": None,
                "keywords": "pdf,editor",
            }
        )

        assert changed is True
        assert model.get_editable_metadata() == {
            "title": "2026",
            "author": "Updated Author",
            "subject": "",
            "keywords": "pdf,editor",
        }
        assert model.doc.metadata["creator"] == "Fixture Creator"
        assert model.doc.metadata["producer"] == "Fixture Producer"
        assert model.doc.metadata["creationDate"] == "D:20260716090000"
        model.save_as(str(output))
    finally:
        model.close()

    reopened = fitz.open(output)
    try:
        assert reopened.metadata["title"] == "2026"
        assert reopened.metadata["author"] == "Updated Author"
        assert reopened.metadata["subject"] == ""
        assert reopened.metadata["keywords"] == "pdf,editor"
        assert reopened.metadata["creator"] == "Fixture Creator"
        assert reopened.metadata["producer"] == "Fixture Producer"
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "payload",
    [None, [], {"unknown": "value"}, {"title": object()}],
)
def test_model_metadata_rejects_invalid_payload_without_mutation(
    tmp_path: Path,
    payload: object,
) -> None:
    model = PDFModel()
    try:
        model.open_pdf(str(_make_pdf(tmp_path / "metadata-invalid.pdf")))
        before = model.get_editable_metadata()
        with pytest.raises((TypeError, ValueError)):
            model.set_editable_metadata(payload)
        assert model.get_editable_metadata() == before
    finally:
        model.close()


def test_metadata_dialog_prefills_and_returns_only_editable_fields(qapp) -> None:
    initial = {
        "title": "Title",
        "author": "Author",
        "subject": "Subject",
        "keywords": "one,two",
        "producer": "must not appear",
    }
    dialog = MetadataDialog(initial)
    try:
        assert dialog.title_edit.text() == "Title"
        assert dialog.author_edit.text() == "Author"
        assert dialog.subject_edit.text() == "Subject"
        assert dialog.keywords_edit.text() == "one,two"

        dialog.title_edit.setText("Changed")
        values = dialog.metadata_values()
        assert set(values) == _EDITABLE_KEYS
        assert values["title"] == "Changed"
        assert "producer" not in values
    finally:
        dialog.close()
        dialog.deleteLater()


def test_view_metadata_dialog_acceptance_emits_payload(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import view.pdf_view as pdf_view_module

    class _AcceptedDialog:
        def __init__(self, initial, parent=None) -> None:
            assert initial["title"] == "Before"
            assert parent is view

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def metadata_values(self) -> dict[str, str]:
            return {"title": "After", "author": "", "subject": "", "keywords": ""}

    view = PDFView(defer_heavy_panels=True)
    emitted: list[dict[str, str]] = []
    view.sig_update_metadata.connect(emitted.append)
    monkeypatch.setattr(pdf_view_module, "MetadataDialog", _AcceptedDialog)
    try:
        view.show_metadata_editor(
            {"title": "Before", "author": "", "subject": "", "keywords": ""}
        )
        assert emitted == [
            {"title": "After", "author": "", "subject": "", "keywords": ""}
        ]
    finally:
        view.close()
        qapp.processEvents()


def test_controller_metadata_snapshot_undo_redo_and_dirty_tab_refresh(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    try:
        controller.activate()
        controller.open_pdf(str(_make_pdf(tmp_path / "metadata-controller.pdf")))
        monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda **_kwargs: None)
        monkeypatch.setattr(controller, "_refresh_after_command", lambda _command: None)

        view.sig_update_metadata.emit(
            {
                "title": "Updated",
                "author": "A",
                "subject": "S",
                "keywords": "K",
            }
        )

        command = model.command_manager._undo_stack[-1]
        assert command._command_type == "update_metadata"
        assert model.get_editable_metadata()["title"] == "Updated"
        assert "*" in view.document_tab_bar.tabText(view.document_tab_bar.currentIndex())

        controller.undo()
        assert model.get_editable_metadata()["title"] == "Original"
        controller.redo()
        assert model.get_editable_metadata()["title"] == "Updated"
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_controller_metadata_request_prefills_view_from_model(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    shown: list[dict[str, str]] = []
    monkeypatch.setattr(view, "show_metadata_editor", shown.append)
    try:
        controller.activate()
        controller.open_pdf(str(_make_pdf(tmp_path / "metadata-query.pdf")))

        view.sig_request_metadata_editor.emit()

        assert shown == [model.get_editable_metadata()]
    finally:
        model.close()
        view.close()
        qapp.processEvents()
