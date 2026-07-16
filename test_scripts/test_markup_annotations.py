from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from view.pdf_view import PDFView


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "first markup line", fontsize=12)
    page.insert_text((72, 115), "second markup line", fontsize=12)
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize(
    ("signal_name", "command_type", "annot_type"),
    [
        ("sig_add_underline", "add_underline", "Underline"),
        ("sig_add_strikeout", "add_strikeout", "StrikeOut"),
    ],
)
def test_controller_records_markup_snapshot_and_undo_redo(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_name: str,
    command_type: str,
    annot_type: str,
) -> None:
    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    try:
        controller.activate()
        controller.open_pdf(str(_make_pdf(tmp_path / f"{command_type}.pdf")))
        monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda **_kwargs: None)
        monkeypatch.setattr(controller, "show_page", lambda _page: None)
        monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)

        signal = getattr(view, signal_name)
        signal.emit(1, fitz.Rect(68, 77, 190, 120), (0.8, 0.1, 0.2, 0.7))

        command = model.command_manager._undo_stack[-1]
        assert command._command_type == command_type
        page = model.doc[0]
        assert [annot.type[1] for annot in page.annots()] == [annot_type]

        monkeypatch.setattr(controller, "_refresh_after_command", lambda _command: None)
        controller.undo()
        assert list(model.doc[0].annots() or []) == []
        controller.redo()
        page = model.doc[0]
        assert [annot.type[1] for annot in page.annots()] == [annot_type]
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_controller_records_rectangle_appearance_snapshot_and_undo_redo(
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
        controller.open_pdf(str(_make_pdf(tmp_path / "rect_appearance.pdf")))
        monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda **_kwargs: None)
        monkeypatch.setattr(controller, "show_page", lambda _page: None)
        monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)

        view.sig_add_rect.emit(
            1,
            fitz.Rect(40, 130, 180, 200),
            (1.0, 0.0, 0.0, 0.8),
            (0.0, 1.0, 0.0, 0.8),
            2.5,
        )

        command = model.command_manager._undo_stack[-1]
        assert command._command_type == "add_rect"
        page = model.doc[0]
        annot = next(page.annots())
        assert annot.colors["stroke"] == pytest.approx([1.0, 0.0, 0.0])
        assert annot.colors["fill"] == pytest.approx([0.0, 1.0, 0.0])
        assert annot.border["width"] == pytest.approx(2.5)

        monkeypatch.setattr(controller, "_refresh_after_command", lambda _command: None)
        controller.undo()
        assert list(model.doc[0].annots() or []) == []
        controller.redo()
        page = model.doc[0]
        assert [annot.type[1] for annot in page.annots()] == ["Square"]
    finally:
        model.close()
        view.close()
        qapp.processEvents()
