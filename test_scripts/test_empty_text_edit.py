# -*- coding: utf-8 -*-
"""Regression tests for empty text edits deleting the target textbox."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller.pdf_controller import PDFController
from model.edit_commands import EditTextCommand
from model.pdf_model import PDFModel


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_two_box_pdf(path: Path) -> fitz.Rect:
    doc = fitz.open()
    page = doc.new_page(width=360, height=260)
    delete_rect = fitz.Rect(40, 40, 260, 92)
    keep_rect = fitz.Rect(40, 140, 260, 192)
    page.insert_textbox(
        delete_rect,
        "DELETE_ME_BLOCK",
        fontsize=16,
        fontname="helv",
        color=(0, 0, 0),
    )
    page.insert_textbox(
        keep_rect,
        "KEEP_BLOCK",
        fontsize=16,
        fontname="helv",
        color=(0, 0, 0),
    )
    doc.save(path)
    doc.close()
    return delete_rect


class _FakeCommandManager:
    def __init__(self) -> None:
        self.executed: list[object] = []

    def execute(self, cmd: object) -> None:
        self.executed.append(cmd)


class _FakeModel:
    def __init__(self) -> None:
        self.doc = [object()]
        self.command_manager = _FakeCommandManager()

    def _capture_page_snapshot(self, page_idx: int) -> bytes:
        _ = page_idx
        return b"snapshot"


def test_controller_empty_edit_is_not_ignored() -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = _FakeModel()
    controller.view = None
    controller.show_page = lambda page_idx: None
    controller._update_undo_redo_tooltips = lambda: None

    controller.edit_text(
        page=1,
        rect=fitz.Rect(10, 10, 80, 30),
        new_text="",
        font="helv",
        size=12,
        color=(0, 0, 0),
        original_text="OLD",
    )

    executed = controller.model.command_manager.executed
    assert len(executed) == 1
    assert isinstance(executed[0], EditTextCommand)


def test_empty_edit_deletes_target_textbox_and_supports_undo_redo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty_edit_delete.pdf"
        target_rect = _make_two_box_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            before = _norm(model.doc[0].get_text("text"))
            assert "delete_me_block" in before
            assert "keep_block" in before

            snapshot = model._capture_page_snapshot(0)
            cmd = EditTextCommand(
                model=model,
                page_num=1,
                rect=target_rect,
                new_text="",
                font="helv",
                size=16,
                color=(0, 0, 0),
                original_text="DELETE_ME_BLOCK",
                vertical_shift_left=True,
                page_snapshot_bytes=snapshot,
                old_block_id=None,
                old_block_text="DELETE_ME_BLOCK",
                target_mode="paragraph",
            )
            model.command_manager.execute(cmd)

            after_delete = _norm(model.doc[0].get_text("text"))
            assert "delete_me_block" not in after_delete
            assert "keep_block" in after_delete

            model.command_manager.undo()
            after_undo = _norm(model.doc[0].get_text("text"))
            assert "delete_me_block" in after_undo
            assert "keep_block" in after_undo

            model.command_manager.redo()
            after_redo = _norm(model.doc[0].get_text("text"))
            assert "delete_me_block" not in after_redo
            assert "keep_block" in after_redo
        finally:
            model.close()
