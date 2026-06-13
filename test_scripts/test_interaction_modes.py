from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence, QShortcut  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402
from model.object_requests import ObjectHitInfo  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeRectItem:
    def __init__(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self.removed = False
        self.z_value = 0

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def setRect(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)

    def setPen(self, _pen) -> None:
        pass

    def setBrush(self, _brush) -> None:
        pass

    def setZValue(self, value: float) -> None:
        self.z_value = value


class _FakeScene:
    def __init__(self) -> None:
        self.items: list[_FakeRectItem] = []
        self.removed: list[_FakeRectItem] = []

    def addRect(self, rect: QRectF, *_args) -> _FakeRectItem:
        item = _FakeRectItem(rect)
        self.items.append(item)
        return item

    def removeItem(self, item: _FakeRectItem) -> None:
        item.removed = True
        self.removed.append(item)


class _FakeEvent:
    def __init__(
        self,
        x: float,
        y: float,
        button=Qt.LeftButton,
        modifiers: Qt.KeyboardModifiers = Qt.NoModifier,
    ) -> None:
        self._pos = QPointF(x, y)
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def position(self):
        return self._pos

    def pos(self):
        return self._pos.toPoint()

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def _make_object_hit(kind: str) -> ObjectHitInfo:
    return ObjectHitInfo(
        object_kind=kind,
        object_id="obj-1",
        page_num=1,
        bbox=fitz.Rect(20, 20, 120, 80),
        rotation=0,
        supports_move=True,
        supports_delete=True,
        supports_rotate=(kind == "textbox"),
    )


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.current_mode = "browse"
    view.current_page = 0
    view.total_pages = 1
    view.scale = 1.0
    view._render_scale = 1.0
    view.continuous_pages = True
    view.page_y_positions = [0.0]
    view.drawing_start = None
    view._drawing_page_idx = None
    view._rect_preview_item = None
    view._fullscreen_active = False
    view.graphics_view = object()
    view.scene = _FakeScene()

    # Object selection state (single-select in current implementation).
    view._selected_object_info = None
    view._object_selection_rect_item = None
    view._object_rotate_handle_item = None
    view._object_drag_pending = False
    view._object_drag_active = False
    view._object_rotate_pending = False
    view._object_drag_start_scene_pos = None
    view._object_drag_start_doc_rect = None
    view._object_drag_preview_rect = None
    view._object_drag_page_idx = None

    # Text selection stub.
    view._text_selection_active = False
    view._text_selection_started = False
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._clear_text_selection = lambda: None
    view._start_text_selection = lambda scene_pos, page_idx: setattr(view, "_text_selection_started", True)

    # Scene/geometry stubs.
    view._event_scene_pos = lambda event: QPointF(float(event.position().x()), float(event.position().y()))
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))

    # Signals used by actions.
    view.sig_mode_changed = _FakeSignal()
    view.sig_add_rect = _FakeSignal()
    view.sig_add_highlight = _FakeSignal()

    # Object hit testing and selection helpers.
    view._point_hits_object_rotate_handle = lambda scene_pos: False
    view._select_object = lambda info: setattr(view, "_selected_object_info", info)
    view._clear_object_selection = lambda: setattr(view, "_selected_object_info", None)

    view.controller = SimpleNamespace(
        get_object_info_at_point=lambda page_num, point: None,
        get_text_info_at_point=lambda page_num, point, allow_fallback=False: None,
    )

    return view


def test_f1_shortcut_switches_to_browse_mode(qapp) -> None:
    view = pdf_view.PDFView()
    try:
        view.set_mode("rect")
        shortcuts = [
            child
            for child in view.findChildren(QShortcut)
            if child.key().matches(QKeySequence(Qt.Key_F1)) == QKeySequence.ExactMatch
        ]
        assert shortcuts

        shortcuts[0].activated.emit()

        assert view.current_mode == "browse"
    finally:
        view.close()
        view.deleteLater()


def test_rect_drag_creates_preview_on_starting_page(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.total_pages = 2
    view.page_y_positions = [0.0, 1000.0]
    view._scene_y_to_page_index = lambda y: 0 if y < 1000 else 1
    view._get_page_scene_rect = lambda page_idx: QRectF(0, page_idx * 1000, 500, 500)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(700, 1400))

    assert view._drawing_page_idx == 0
    assert view._rect_preview_item is not None
    assert view._rect_preview_item.rect() == QRectF(10, 10, 490, 490)


def test_rect_release_emits_from_starting_page_and_clears_preview(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.total_pages = 2
    view.page_y_positions = [0.0, 1000.0]
    view._scene_y_to_page_index = lambda y: 0 if y < 1000 else 1
    view._get_page_scene_rect = lambda page_idx: QRectF(0, page_idx * 1000, 500, 500)
    view.rect_color = SimpleNamespace(getRgbF=lambda: (1.0, 0.0, 0.0, 1.0))

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QMessageBox, "question", lambda *args, **kwargs: pdf_view.QMessageBox.No)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(700, 1400))
    preview = view._rect_preview_item
    pdf_view.PDFView._mouse_release(view, _FakeEvent(700, 1400))

    assert view.sig_add_rect.calls == [(1, fitz.Rect(10, 10, 500, 500), (1.0, 0.0, 0.0, 1.0), False)]
    assert view._rect_preview_item is None
    assert view._drawing_page_idx is None
    assert preview.removed is True


def test_objects_mode_blocks_browse_text_selection_start(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    view.controller.get_text_info_at_point = lambda page_num, point, allow_fallback=False: object()

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._text_selection_started is False


def test_browse_mode_does_not_start_object_manipulation(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "browse"
    view.controller.get_object_info_at_point = lambda page_num, point: _make_object_hit("rect")

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info is None


def test_text_edit_mode_does_not_select_rect_or_image(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view.controller.get_object_info_at_point = lambda page_num, point: _make_object_hit("rect")

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info is None


def test_text_edit_mode_allows_textbox_object_select(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view.controller.get_object_info_at_point = lambda page_num, point: _make_object_hit("textbox")

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info is not None
    assert view._selected_object_info.object_kind == "textbox"
