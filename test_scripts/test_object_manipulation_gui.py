from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QPoint, QPointF, Qt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import view.pdf_view as pdf_view
from model.object_requests import ObjectHitInfo


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _FakeViewport:
    def __init__(self, offset: QPoint | None = None) -> None:
        self.cursor = None
        self._offset = offset or QPoint(0, 0)

    def setCursor(self, cursor) -> None:
        self.cursor = cursor

    def mapFrom(self, _parent, pos):
        return QPoint(pos.x() + self._offset.x(), pos.y() + self._offset.y())


class _FakeGraphicsView:
    def __init__(self, viewport_offset: QPoint | None = None) -> None:
        self._viewport = _FakeViewport(viewport_offset)
        self._scene_offset = viewport_offset or QPoint(0, 0)

    def viewport(self):
        return self._viewport

    def mapToGlobal(self, pos):
        return pos

    def mapToScene(self, pos):
        if isinstance(pos, QPointF):
            return QPointF(float(pos.x() - self._scene_offset.x()), float(pos.y() - self._scene_offset.y()))
        return QPointF(float(pos.x() - self._scene_offset.x()), float(pos.y() - self._scene_offset.y()))


class _FakeEvent:
    def __init__(self, x: float, y: float, button=Qt.LeftButton) -> None:
        self._point = QPointF(x, y)
        self._button = button
        self.accepted = False

    def position(self):
        return self._point

    def pos(self):
        return self._point.toPoint()

    def button(self):
        return self._button

    def accept(self):
        self.accepted = True


class _FakeKeyEvent:
    def __init__(self, key: int, modifiers: Qt.KeyboardModifiers = Qt.NoModifier) -> None:
        self._key = key
        self._modifiers = modifiers
        self.accepted = False

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def matches(self, sequence):
        return False

    def accept(self):
        self.accepted = True


def _make_object_hit(kind: str = "textbox", supports_rotate: bool = True) -> ObjectHitInfo:
    return ObjectHitInfo(
        object_kind=kind,
        object_id="obj-1",
        page_num=1,
        bbox=fitz.Rect(20, 20, 120, 80),
        rotation=0,
        supports_move=True,
        supports_delete=True,
        supports_rotate=supports_rotate,
    )


def _make_view(viewport_offset: QPoint | None = None) -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.graphics_view = _FakeGraphicsView(viewport_offset)
    view.current_mode = "browse"
    view.current_page = 0
    view.total_pages = 1
    view.scale = 1.0
    view._fullscreen_active = False
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._selected_object_info = None
    view._object_selection_rect_item = None
    view._object_rotate_handle_item = None
    view._object_drag_pending = False
    view._object_drag_active = False
    view._object_rotate_pending = False
    view._object_drag_start_scene_pos = None
    view._object_drag_start_doc_rect = None
    view._object_drag_page_idx = None
    view._object_drag_current_scene_pos = None
    view._render_scale = 1.0
    view.page_y_positions = [0.0]
    view.continuous_pages = True
    view.scene = None
    view.controller = SimpleNamespace(
        get_object_info_at_point=lambda page_num, point: None,
        get_text_info_at_point=lambda page_num, point, allow_fallback=False: None,
    )
    view._clear_text_selection = lambda: None
    view._start_text_selection = lambda scene_pos, page_idx: setattr(view, "_text_selection_started", True)
    view._text_selection_started = False
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))
    view._select_object = lambda info: setattr(view, "_selected_object_info", info)
    view._clear_object_selection = lambda: setattr(view, "_selected_object_info", None)
    view._update_browse_hover_cursor = lambda scene_pos: None
    view._reset_browse_hover_cursor = lambda: None
    view._point_hits_object_rotate_handle = lambda scene_pos: False
    view.sig_delete_object = _FakeSignal()
    view.sig_rotate_object = _FakeSignal()
    return view


def test_objects_mouse_press_selects_object_and_blocks_text_selection(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    hit = _make_object_hit(kind="rect", supports_rotate=False)
    view.controller.get_object_info_at_point = lambda page_num, point: hit

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info == hit
    assert view._text_selection_started is False


def test_objects_mouse_press_selects_native_image(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    hit = _make_object_hit(kind="native_image", supports_rotate=True)
    view.controller.get_object_info_at_point = lambda page_num, point: hit

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(40, 40)
    pdf_view.PDFView._mouse_press(view, event)

    assert view._selected_object_info == hit
    assert event.accepted is True


def test_event_scene_pos_normalizes_viewport_offset() -> None:
    view = _make_view(QPoint(97, 186))
    scene_pos = pdf_view.PDFView._event_scene_pos(view, _FakeEvent(166, 37))
    assert scene_pos == QPointF(166.0, 37.0)


def test_delete_selected_object_emits_request() -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="rect", supports_rotate=False)

    assert pdf_view.PDFView._delete_selected_object(view) is True
    assert view.sig_delete_object.emitted


def test_rotate_selected_object_emits_request() -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)

    assert pdf_view.PDFView._rotate_selected_object(view, 90) is True
    assert view.sig_rotate_object.emitted


def test_delete_shortcut_works_in_objects_mode() -> None:
    view = _make_view()
    view.current_mode = "objects"
    view._selected_object_info = _make_object_hit(kind="rect", supports_rotate=False)

    event = _FakeKeyEvent(Qt.Key_Delete)
    pdf_view.PDFView.keyPressEvent(view, event)

    assert event.accepted is True
    assert view.sig_delete_object.emitted


def test_delete_shortcut_works_in_text_edit_mode() -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)

    event = _FakeKeyEvent(Qt.Key_Backspace)
    pdf_view.PDFView.keyPressEvent(view, event)

    assert event.accepted is True
    assert view.sig_delete_object.emitted


def test_browse_object_drag_threshold_starts_drag(monkeypatch) -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
    view._object_drag_pending = True
    view._object_drag_start_scene_pos = QPointF(10, 10)
    view._object_drag_start_doc_rect = fitz.Rect(20, 20, 120, 80)
    view._object_drag_page_idx = 0
    view.controller.model = SimpleNamespace(doc=[SimpleNamespace(rect=fitz.Rect(0, 0, 500, 500))])
    view._object_drag_preview_rect = None
    view._update_object_selection_visuals = lambda rect=None: None

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_move(view, _FakeEvent(40, 40))

    assert view._object_drag_active is True


def test_text_edit_mouse_press_on_rotate_handle_arms_rotation(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    hit = _make_object_hit(kind="textbox", supports_rotate=True)
    view._selected_object_info = hit
    view._point_hits_object_rotate_handle = lambda scene_pos: True
    view.controller.get_object_info_at_point = lambda page_num, point: None

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(40, 40)
    pdf_view.PDFView._mouse_press(view, event)

    assert view._object_rotate_pending is True
    assert event.accepted is True


def test_scene_context_menu_includes_object_actions(monkeypatch) -> None:
    view = _make_view()
    labels = []
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
    view._resolve_text_info_for_context_menu_pos = lambda pos: None

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions = []

        def addAction(self, text: str, callback=None):
            self._actions.append(_FakeAction(text))
            return self._actions[-1]

        def addSeparator(self):
            return None

        def exec_(self, *args, **kwargs):
            labels.extend(action.text() for action in self._actions)
            return None

    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    pdf_view.PDFView._show_context_menu(view, QPoint(0, 0))

    assert "Delete Object" in labels
    assert any(label.startswith("Rotate Object 90") for label in labels)


def test_objects_context_menu_exposes_image_insert_actions(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    labels = []
    view._selected_object_info = None
    view._resolve_text_info_for_context_menu_pos = lambda pos: None
    view._resolve_default_image_insert_target = lambda pos: (1, fitz.Rect(10, 10, 110, 85))

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions = []

        def addAction(self, text: str, callback=None):
            self._actions.append(_FakeAction(text))
            return self._actions[-1]

        def addSeparator(self):
            return None

        def exec_(self, *args, **kwargs):
            labels.extend(action.text() for action in self._actions)
            return None

    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    pdf_view.PDFView._show_context_menu(view, QPoint(0, 0))

    assert any("插入圖片" in label for label in labels)
    assert any("剪貼簿" in label for label in labels)
