from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication

from model.edit_commands import CommandManager, EditCommand
from model.pdf_model import PDFModel
import view.pdf_view as pdf_view


class _NamedCommand(EditCommand):
    def __init__(self, name: str) -> None:
        self.name = name
        self.executed = 0
        self.undone = 0

    @property
    def description(self) -> str:
        return self.name

    def execute(self) -> None:
        self.executed += 1

    def undo(self) -> None:
        self.undone += 1


class _UndoBoomCommand(_NamedCommand):
    def undo(self) -> None:
        raise RuntimeError("undo boom")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Rollback target", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    model.ensure_page_index_built(page_idx + 1)
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None


def test_inline_text_editor_emits_focus_out_signal_without_monkeypatch(qapp: QApplication) -> None:
    editor_cls = getattr(pdf_view, "InlineTextEditor", None)
    assert editor_cls is not None

    editor = editor_cls("hello")
    observed: list[str] = []
    editor.focus_out_requested.connect(lambda: observed.append("focus-out"))
    original_handler = editor.focusOutEvent

    editor.focusOutEvent(QFocusEvent(QFocusEvent.FocusOut))

    assert observed == ["focus-out"]
    assert editor.focusOutEvent == original_handler


def test_command_manager_undo_keeps_command_on_failure() -> None:
    manager = CommandManager()
    cmd = _UndoBoomCommand("boom")
    manager.record(cmd)

    with pytest.raises(RuntimeError, match="undo boom"):
        manager.undo()

    assert manager.undo_count == 1
    assert manager.redo_count == 0
    assert manager._undo_stack[-1] is cmd


def test_command_manager_evicts_oldest_entries_at_max_limit() -> None:
    manager = CommandManager()

    for i in range(105):
        manager.record(_NamedCommand(f"cmd-{i}"))

    assert manager.undo_count == 100
    assert manager._undo_stack[0].description == "cmd-5"
    assert manager._undo_stack[-1].description == "cmd-104"


def test_edit_text_reports_rollback_failures(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rollback.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target = _find_block(model, 0, "Rollback target")
            assert target is not None

            monkeypatch.setattr(model, "_convert_text_to_html", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("primary failure")))
            monkeypatch.setattr(model, "_restore_page_from_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("rollback failure")))

            with caplog.at_level(logging.ERROR):
                with pytest.raises(RuntimeError, match="rollback failure"):
                    model.edit_text(
                        page_num=1,
                        rect=fitz.Rect(target.layout_rect),
                        new_text="Edited text",
                        font=target.font,
                        size=max(8, int(round(target.size))),
                        color=target.color,
                        original_text=target.text,
                    )

            assert "rollback failure" in caplog.text.lower()
            assert "primary failure" in caplog.text.lower()
        finally:
            model.close()


def test_restore_page_from_snapshot_does_not_delete_live_page_when_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSnapshotDoc:
        page_count = 1

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _FakeDoc:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def insert_pdf(self, *args, **kwargs) -> None:
            self.calls.append(("insert", kwargs["start_at"]))
            raise RuntimeError("insert failure")

        def delete_page(self, index: int) -> None:
            self.calls.append(("delete", index))

    snapshot_doc = _FakeSnapshotDoc()
    model = PDFModel()
    model.doc = _FakeDoc()
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: snapshot_doc)

    with pytest.raises(RuntimeError, match="insert failure"):
        model._restore_page_from_snapshot(2, b"%PDF-fake")

    assert model.doc.calls == [("insert", 2)]
    assert snapshot_doc.closed is True


def test_restore_page_from_snapshot_inserts_replacement_before_deleting_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSnapshotDoc:
        page_count = 1

        def close(self) -> None:
            return None

    class _FakeDoc:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def insert_pdf(self, *args, **kwargs) -> None:
            self.calls.append(("insert", kwargs["start_at"]))

        def delete_page(self, index: int) -> None:
            self.calls.append(("delete", index))

    model = PDFModel()
    model.doc = _FakeDoc()
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: _FakeSnapshotDoc())

    model._restore_page_from_snapshot(3, b"%PDF-fake")

    assert model.doc.calls == [("insert", 3), ("delete", 4)]
