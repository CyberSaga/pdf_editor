"""Regression tests for controller-driven cross-page text moves."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz
import pytest

import controller.pdf_controller as pdf_controller_module
from controller.pdf_controller import PDFController
from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_two_page_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=360, height=240)
    doc.new_page(width=360, height=240)
    page1 = doc[0]
    page2 = doc[1]
    page1.insert_text(fitz.Point(40, 60), "MOVE_ME", fontsize=16, fontname="helv", color=(0, 0, 0))
    page2.insert_text(fitz.Point(40, 160), "KEEP_PAGE_TWO", fontsize=16, fontname="helv", color=(0, 0, 0))
    doc.save(path)
    doc.close()


class _FakeView:
    def capture_viewport_anchor(self):
        return None


def _make_controller(model: PDFModel) -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = model
    controller.view = _FakeView()
    controller._invalidate_active_render_state = lambda *args, **kwargs: None
    controller._update_thumbnails = lambda: None
    controller.show_page = lambda page_idx: None
    controller._update_undo_redo_tooltips = lambda: None
    return controller


def test_move_text_across_pages_records_single_snapshot_command_and_undoes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_move.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None
            controller = _make_controller(model)

            before_undo = model.command_manager.undo_count
            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode=hit.target_mode,
            )

            assert model.command_manager.undo_count == before_undo + 1
            last_cmd = model.command_manager._undo_stack[-1]
            assert isinstance(last_cmd, SnapshotCommand)
            assert last_cmd.description == "跨頁移動文字"

            page1_text = _norm(model.doc[0].get_text("text"))
            page2_text = _norm(model.doc[1].get_text("text"))
            assert "move_me" not in page1_text
            assert "move_me" in page2_text
            assert "keep_page_two" in page2_text

            model.command_manager.undo()
            page1_undo = _norm(model.doc[0].get_text("text"))
            page2_undo = _norm(model.doc[1].get_text("text"))
            assert "move_me" in page1_undo
            assert "move_me" not in page2_undo
            assert "keep_page_two" in page2_undo

            model.command_manager.redo()
            page1_redo = _norm(model.doc[0].get_text("text"))
            page2_redo = _norm(model.doc[1].get_text("text"))
            assert "move_me" not in page1_redo
            assert "move_me" in page2_redo
        finally:
            model.close()


def test_cross_page_move_unresolved_source_without_span_id_aborts_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(pdf_controller_module, "show_error", lambda _view, message: errors.append(message))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_missing_source.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            controller = _make_controller(model)

            before_page1 = _norm(model.doc[0].get_text("text"))
            before_page2 = _norm(model.doc[1].get_text("text"))
            before_undo = model.command_manager.undo_count

            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(220, 180, 320, 220),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text="MOVE_ME",
                font="helv",
                size=16,
                color=(0.0, 0.0, 0.0),
                original_text="DOES_NOT_EXIST",
                target_span_id=None,
                target_mode="run",
            )

            assert model.command_manager.undo_count == before_undo
            assert _norm(model.doc[0].get_text("text")) == before_page1
            assert _norm(model.doc[1].get_text("text")) == before_page2
            assert errors
        finally:
            model.close()


def test_cross_page_move_stale_span_id_falls_back_to_rect_text_resolution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_stale_span_id.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None
            controller = _make_controller(model)

            before_undo = model.command_manager.undo_count
            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id="stale-span-id",
                target_mode=hit.target_mode,
            )

            assert model.command_manager.undo_count == before_undo + 1
            assert "move_me" not in _norm(model.doc[0].get_text("text"))
            assert "move_me" in _norm(model.doc[1].get_text("text"))
        finally:
            model.close()


def test_cross_page_move_add_failure_restores_before_snapshot_and_refreshes_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(pdf_controller_module, "show_error", lambda _view, message: errors.append(message))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_add_failure.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None

            controller = PDFController.__new__(PDFController)
            controller.model = model
            controller.view = _FakeView()
            invalidate_calls: list[tuple] = []
            thumb_calls: list[bool] = []
            shown_pages: list[int] = []
            tooltip_calls: list[bool] = []
            controller._invalidate_active_render_state = lambda *args, **kwargs: invalidate_calls.append((args, kwargs))
            controller._update_thumbnails = lambda: thumb_calls.append(True)
            controller.show_page = lambda page_idx: shown_pages.append(page_idx)
            controller._update_undo_redo_tooltips = lambda: tooltip_calls.append(True)

            before_page1 = _norm(model.doc[0].get_text("text"))
            before_page2 = _norm(model.doc[1].get_text("text"))
            before_undo = model.command_manager.undo_count

            monkeypatch.setattr(
                model,
                "add_textbox",
                lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
            )

            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode=hit.target_mode,
            )

            assert model.command_manager.undo_count == before_undo
            assert _norm(model.doc[0].get_text("text")) == before_page1
            assert _norm(model.doc[1].get_text("text")) == before_page2
            assert invalidate_calls
            assert thumb_calls
            assert shown_pages == [0]
            assert tooltip_calls
            assert errors
        finally:
            model.close()
