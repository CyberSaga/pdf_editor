"""Phase 3.1 — undo stack byte budget + adjacent snapshot dedup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from model.edit_commands import (
    AddTextboxCommand,
    CommandManager,
    EditCommand,
    EditTextCommand,
    SnapshotCommand,
)
from model.pdf_model import PDFModel


class _FakeModel:
    """Minimal stand-in: SnapshotCommand only needs these two methods."""

    def _restore_doc_from_snapshot(self, snapshot_bytes: bytes) -> None:
        pass

    def refresh_structural_indexes(self, affected_pages: list[int]) -> None:
        pass


def _snapshot_cmd(model: _FakeModel, before: bytes, after: bytes, desc: str) -> SnapshotCommand:
    return SnapshotCommand(
        model=model,
        command_type="delete_pages",
        affected_pages=[1],
        before_bytes=before,
        after_bytes=after,
        description=desc,
    )


def _make_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), f"page {i + 1}", fontsize=12, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def test_byte_budget_evicts_oldest_snapshot_commands(monkeypatch) -> None:
    # Red-light: MAX_UNDO_STACK_BYTES does not exist yet -> AttributeError here.
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 300 * 1024)

    cm = CommandManager()
    model = _FakeModel()

    # Three commands of ~160 KiB each (80 KiB before + 80 KiB after), unique
    # payloads so the dedup pass cannot fire.
    cmds = []
    for i in range(3):
        before = bytes([i]) * (80 * 1024)
        after = bytes([i + 10]) * (80 * 1024)
        cmd = _snapshot_cmd(model, before, after, f"op {i}")
        cmds.append(cmd)

    cm.record(cmds[0])
    cm.mark_saved()  # saved marker at depth 1; evictions must clamp it
    cm.record(cmds[1])
    cm.record(cmds[2])

    # 3 x 160 KiB = 480 KiB > 300 KiB -> evict cmd0 (320 KiB still > 300) -> evict
    # cmd1 (160 KiB <= 300). Only the newest survives.
    assert cm.undo_count == 1, f"byte budget should evict oldest, undo_count={cm.undo_count}"
    assert cm._undo_stack[-1] is cmds[2]
    # Saved-stack marker must follow evictions (clamped at 0), so
    # has_pending_changes() still reports the unsaved tail.
    assert cm._saved_stack_size == 0
    assert cm.has_pending_changes() is True


def test_adjacent_dedup_shares_bytes_object() -> None:
    cm = CommandManager()
    model = _FakeModel()

    shared_after = bytes(bytearray(b"y" * 4096))
    equal_before = bytes(bytearray(b"y" * 4096))
    assert shared_after == equal_before
    assert shared_after is not equal_before

    cmd1 = _snapshot_cmd(model, b"a" * 1024, shared_after, "op 1")
    cmd2 = _snapshot_cmd(model, equal_before, b"z" * 1024, "op 2")

    cm.record(cmd1)
    cm.record(cmd2)

    assert cm._undo_stack[-2]._after_bytes is cm._undo_stack[-1]._before_bytes, (
        "adjacent SnapshotCommands with equal boundary bytes should share one object"
    )


def test_dedup_does_not_corrupt_undo_redo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "three_page.pdf"
        _make_pdf(pdf_path, pages=3)

        m = PDFModel()
        try:
            m.open_pdf(str(pdf_path))
            assert len(m.doc) == 3

            # Op 1: delete page 3.
            before1 = m._capture_doc_snapshot()
            m.delete_pages([3])
            after1 = m._capture_doc_snapshot()
            m.command_manager.record(
                SnapshotCommand(
                    model=m,
                    command_type="delete_pages",
                    affected_pages=[3],
                    before_bytes=before1,
                    after_bytes=after1,
                    description="delete page 3",
                )
            )
            assert len(m.doc) == 2

            # Op 2: insert a blank page (adjacent snapshot boundary == after1).
            before2 = m._capture_doc_snapshot()
            m.insert_blank_page(2)
            after2 = m._capture_doc_snapshot()
            m.command_manager.record(
                SnapshotCommand(
                    model=m,
                    command_type="insert_blank_page",
                    affected_pages=[2],
                    before_bytes=before2,
                    after_bytes=after2,
                    description="insert blank page",
                )
            )
            assert len(m.doc) == 3

            # Full round-trip must survive any dedup sharing.
            assert m.command_manager.undo() is True
            assert len(m.doc) == 2
            assert m.command_manager.undo() is True
            assert len(m.doc) == 3
            assert m.command_manager.redo() is True
            assert len(m.doc) == 2
            assert m.command_manager.redo() is True
            assert len(m.doc) == 3
        finally:
            m.close()


def test_byte_size_returns_correct_values() -> None:
    class _NoopCommand(EditCommand):
        def execute(self) -> None:
            pass

        def undo(self) -> None:
            pass

    # Red-light: _byte_size() does not exist yet -> AttributeError.
    assert _NoopCommand()._byte_size() == 0

    edit_cmd = EditTextCommand(
        model=None,
        page_num=1,
        rect=fitz.Rect(0, 0, 10, 10),
        new_text="t",
        font="helv",
        size=12.0,
        color=(0, 0, 0),
        original_text="o",
        vertical_shift_left=False,
        page_snapshot_bytes=b"abc",
        old_block_id=None,
        old_block_text=None,
    )
    assert edit_cmd._byte_size() == 3

    textbox_cmd = AddTextboxCommand(
        model=None,
        page_num=1,
        visual_rect=fitz.Rect(0, 0, 10, 10),
        text="t",
        font="helv",
        size=12,
        color=(0, 0, 0),
        before_page_snapshot_bytes=b"abcd",
    )
    assert textbox_cmd._byte_size() == 4  # after-bytes still None
    textbox_cmd._after_page_snapshot_bytes = b"xy"
    assert textbox_cmd._byte_size() == 6

    snap_cmd = SnapshotCommand(
        model=None,
        command_type="delete_pages",
        affected_pages=[1],
        before_bytes=b"123",
        after_bytes=b"4567",
        description="d",
    )
    assert snap_cmd._byte_size() == 7
