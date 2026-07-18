from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from view.pdf_view import PDFView, _ReorderableThumbnailList


def _make_pdf(path: Path, labels: list[str]) -> Path:
    doc = fitz.open()
    try:
        for label in labels:
            page = doc.new_page()
            page.insert_text((72, 72), label, fontsize=12, fontname="helv")
        doc.save(path)
    finally:
        doc.close()
    return path


def _page_labels(model: PDFModel) -> list[str]:
    assert model.doc is not None
    return [page.get_text("text").strip() for page in model.doc]


def test_pymupdf_move_page_inserts_before_its_native_destination_index() -> None:
    """Pin the native forward-move offset that the model must normalize."""
    doc = fitz.open()
    try:
        for label in ("one", "two", "three", "four", "five"):
            page = doc.new_page()
            page.insert_text((72, 72), label, fontsize=12, fontname="helv")

        doc.move_page(0, 2)

        assert [page.get_text("text").strip() for page in doc] == [
            "two",
            "one",
            "three",
            "four",
            "five",
        ]
    finally:
        doc.close()


def test_move_page_moves_first_page_to_final_target_and_marks_interval_stale(tmp_path: Path) -> None:
    model = PDFModel()
    try:
        model.open_pdf(str(_make_pdf(tmp_path / "five-pages.pdf", ["one", "two", "three", "four", "five"])))
        for page_num in range(1, 6):
            model.ensure_page_index_built(page_num)

        affected_pages = model.move_page(0, 2)

        assert affected_pages == [1, 2, 3]
        assert _page_labels(model) == ["two", "three", "one", "four", "five"]
        assert model.block_manager.page_state(0) == "stale"
        assert model.block_manager.page_state(1) == "stale"
        assert model.block_manager.page_state(2) == "clean"
        for page_num in (1, 2, 3):
            model.ensure_page_index_built(page_num)
        assert [model.block_manager.page_state(page_num) for page_num in range(3)] == ["clean", "clean", "clean"]
    finally:
        model.close()


def test_move_page_moves_middle_page_to_first_position(tmp_path: Path) -> None:
    model = PDFModel()
    try:
        model.open_pdf(str(_make_pdf(tmp_path / "five-pages.pdf", ["one", "two", "three", "four", "five"])))

        affected_pages = model.move_page(2, 0)

        assert affected_pages == [1, 2, 3]
        assert _page_labels(model) == ["three", "one", "two", "four", "five"]
    finally:
        model.close()


def test_move_page_moves_first_page_to_final_page_boundary(tmp_path: Path) -> None:
    model = PDFModel()
    try:
        model.open_pdf(str(_make_pdf(tmp_path / "five-pages.pdf", ["one", "two", "three", "four", "five"])))

        affected_pages = model.move_page(0, 4)

        assert affected_pages == [1, 2, 3, 4, 5]
        assert _page_labels(model) == ["two", "three", "four", "five", "one"]
    finally:
        model.close()


@pytest.mark.parametrize(
    ("source_index", "destination_index"),
    [(-1, 0), (0, -1), (5, 0), (0, 5), (True, 1), (1, False), (2, 2)],
)
def test_move_page_rejects_invalid_or_unchanged_positions_without_mutating(
    tmp_path: Path,
    source_index: object,
    destination_index: object,
) -> None:
    model = PDFModel()
    try:
        model.open_pdf(str(_make_pdf(tmp_path / "five-pages.pdf", ["one", "two", "three", "four", "five"])))
        before = _page_labels(model)

        assert model.move_page(source_index, destination_index) == []
        assert _page_labels(model) == before
    finally:
        model.close()


def test_controller_records_structural_move_and_restores_order_with_undo_redo(
    tmp_path: Path,
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    refreshes: list[tuple[str, object]] = []
    try:
        path = _make_pdf(tmp_path / "five-pages.pdf", ["one", "two", "three", "four", "five"])
        controller.open_pdf(str(path))
        monkeypatch.setattr(controller, "_cancel_search", lambda: None)
        monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda **kwargs: None)
        monkeypatch.setattr(controller, "_invalidate_thumbnails", lambda pages: refreshes.append(("thumbnails", pages)))
        monkeypatch.setattr(controller, "_rebuild_continuous_scene", lambda page: refreshes.append(("scene", page)))
        monkeypatch.setattr(controller, "_schedule_stale_index_drain", lambda: refreshes.append(("stale", None)))
        monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)

        view.sig_reorder_page.emit(0, 2)

        command = model.command_manager._undo_stack[-1]
        assert command._command_type == "move_page"
        assert command.is_structural is True
        assert refreshes == [("thumbnails", [1, 2, 3]), ("scene", 2), ("stale", None)]
        assert _page_labels(model) == ["two", "three", "one", "four", "five"]

        monkeypatch.setattr(controller, "_refresh_after_command", lambda _command: None)
        controller.undo()
        assert _page_labels(model) == ["one", "two", "three", "four", "five"]
        controller.redo()
        assert _page_labels(model) == ["two", "three", "one", "four", "five"]
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_thumbnail_reorder_callback_emits_only_controller_intent() -> None:
    calls: list[tuple[int, int]] = []
    view = PDFView.__new__(PDFView)
    view.sig_reorder_page = SimpleNamespace(emit=lambda source, destination: calls.append((source, destination)))

    PDFView._on_thumbnail_reordered(view, 0, 2)

    assert calls == [(0, 2)]


class _InternalDropEvent(QDropEvent):
    """Synthesized internal drop whose source() reports the list itself."""

    def __init__(self, widget: QListWidget, pos: QPoint) -> None:
        super().__init__(
            QPointF(pos),
            Qt.MoveAction,
            QMimeData(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self._drag_source = widget

    def source(self) -> QListWidget:  # noqa: N802 - Qt override
        return self._drag_source


def _make_thumbnail_list(qapp, count: int = 5, height: int = 640) -> _ReorderableThumbnailList:
    widget = _ReorderableThumbnailList()
    widget.setFixedSize(240, height)
    for row in range(count):
        item = QListWidgetItem(f"頁{row + 1}")
        item.setSizeHint(QSize(200, 120))
        widget.addItem(item)
    widget.show()
    widget.doItemsLayout()
    qapp.processEvents()
    return widget


def _list_labels(widget: QListWidget) -> list[str]:
    return [widget.item(row).text() for row in range(widget.count())]


def test_internal_drop_moves_row_and_emits_final_positions(qapp) -> None:
    widget = _make_thumbnail_list(qapp)
    emitted: list[tuple[int, int]] = []
    widget.page_reordered.connect(lambda source, destination: emitted.append((source, destination)))
    try:
        widget.setCurrentRow(0)
        target_rect = widget.visualItemRect(widget.item(2))
        drop_pos = QPoint(target_rect.center().x(), target_rect.bottom() - 4)

        widget.dropEvent(_InternalDropEvent(widget, drop_pos))

        assert _list_labels(widget) == ["頁2", "頁3", "頁1", "頁4", "頁5"]
        assert emitted == [(0, 2)]
    finally:
        widget.close()
        qapp.processEvents()


def test_internal_drop_above_earlier_item_moves_row_up(qapp) -> None:
    widget = _make_thumbnail_list(qapp)
    emitted: list[tuple[int, int]] = []
    widget.page_reordered.connect(lambda source, destination: emitted.append((source, destination)))
    try:
        widget.setCurrentRow(3)
        target_rect = widget.visualItemRect(widget.item(1))
        drop_pos = QPoint(target_rect.center().x(), target_rect.top() + 4)

        widget.dropEvent(_InternalDropEvent(widget, drop_pos))

        assert _list_labels(widget) == ["頁1", "頁4", "頁2", "頁3", "頁5"]
        assert emitted == [(3, 1)]
    finally:
        widget.close()
        qapp.processEvents()


def test_internal_drop_below_last_item_moves_row_to_end(qapp) -> None:
    widget = _make_thumbnail_list(qapp)
    emitted: list[tuple[int, int]] = []
    widget.page_reordered.connect(lambda source, destination: emitted.append((source, destination)))
    try:
        widget.setCurrentRow(0)
        last_rect = widget.visualItemRect(widget.item(widget.count() - 1))
        drop_pos = QPoint(last_rect.center().x(), last_rect.bottom() + 30)

        widget.dropEvent(_InternalDropEvent(widget, drop_pos))

        assert _list_labels(widget) == ["頁2", "頁3", "頁4", "頁5", "頁1"]
        assert emitted == [(0, 4)]
    finally:
        widget.close()
        qapp.processEvents()


def test_start_drag_runs_qdrag_without_qt_row_removal(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    """QAbstractItemView.startDrag deletes the still-selected source row via
    clearOrRemove() when a drag ends with MoveAction — after dropEvent already
    moved the row, that cleanup removes the moved thumbnail. The list must run
    the QDrag itself and never invoke Qt's post-exec removal."""
    import view.pdf_view as pdf_view_module

    executed: dict[str, object] = {}

    class _FakeDrag:
        def __init__(self, source) -> None:
            executed["source"] = source

        def setMimeData(self, mime) -> None:  # noqa: N802 - Qt API shape
            executed["mime"] = mime

        def setPixmap(self, pixmap) -> None:  # noqa: N802
            executed["pixmap"] = pixmap

        def setHotSpot(self, point) -> None:  # noqa: N802
            executed["hotspot"] = point

        def exec(self, *actions) -> object:
            executed["exec"] = actions
            return Qt.MoveAction

    monkeypatch.setattr(pdf_view_module, "QDrag", _FakeDrag)
    widget = _make_thumbnail_list(qapp)
    try:
        widget.setCurrentRow(1)

        widget.startDrag(Qt.MoveAction)

        assert executed["source"] is widget
        assert executed["exec"] == (Qt.MoveAction, Qt.MoveAction)
        assert widget.count() == 5
        assert _list_labels(widget) == ["頁1", "頁2", "頁3", "頁4", "頁5"]
    finally:
        widget.close()
        qapp.processEvents()


def test_thumbnail_viewport_accepts_drops_after_configuration(qapp) -> None:
    """setMovement(Static) silently disables viewport drops; the viewport is
    where Qt delivers real drag events, so it must accept them explicitly."""
    widget = _make_thumbnail_list(qapp)
    try:
        assert widget.viewport().acceptDrops() is True
        assert widget.acceptDrops() is True
    finally:
        widget.close()
        qapp.processEvents()


class _InternalDragMoveEvent(QDragMoveEvent):
    """Synthesized internal drag-move whose source() reports the list itself."""

    def __init__(self, widget: QListWidget, pos: QPoint) -> None:
        super().__init__(
            pos,
            Qt.MoveAction,
            QMimeData(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self._drag_source = widget

    def source(self) -> QListWidget:  # noqa: N802 - Qt override
        return self._drag_source


def test_internal_drag_move_is_accepted_over_every_row(qapp) -> None:
    """Static movement makes Qt refuse drag-moves away from the source row;
    the list must accept internal drags anywhere so the drop can land."""
    widget = _make_thumbnail_list(qapp)
    try:
        widget.setCurrentRow(0)
        for row in range(widget.count()):
            pos = widget.visualItemRect(widget.item(row)).center()
            event = _InternalDragMoveEvent(widget, pos)
            event.ignore()
            widget.dragMoveEvent(event)
            assert event.isAccepted(), f"drag-move rejected over row {row}"
    finally:
        widget.close()
        qapp.processEvents()


def test_drag_near_top_and_bottom_edges_scrolls_thumbnail_list(qapp) -> None:
    widget = _make_thumbnail_list(qapp, count=12, height=320)
    try:
        bar = widget.verticalScrollBar()
        assert bar.maximum() > 0, "fixture must overflow the viewport so drag scrolling is observable"

        bar.setValue(0)
        widget._auto_scroll_during_drag(QPoint(100, widget.viewport().height() - 4))
        assert bar.value() > 0

        scrolled_down = bar.value()
        widget._auto_scroll_during_drag(QPoint(100, 4))
        assert bar.value() < scrolled_down

        # Away from both edges the list must not creep.
        middle = QPoint(100, widget.viewport().height() // 2)
        before = bar.value()
        widget._auto_scroll_during_drag(middle)
        assert bar.value() == before
    finally:
        widget.close()
        qapp.processEvents()
