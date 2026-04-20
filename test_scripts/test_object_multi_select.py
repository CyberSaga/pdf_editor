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

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402
from model.object_requests import ObjectHitInfo  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _FakeViewport:
    def __init__(self) -> None:
        self._offset = QPoint(0, 0)

    def mapFrom(self, _parent, pos):
        return QPoint(pos.x() + self._offset.x(), pos.y() + self._offset.y())


class _FakeGraphicsView:
    def __init__(self) -> None:
        self._viewport = _FakeViewport()

    def viewport(self):
        return self._viewport

    def mapToScene(self, pos):
        if isinstance(pos, QPointF):
            return pos
        return QPointF(float(pos.x()), float(pos.y()))


class _FakeEvent:
    def __init__(
        self,
        x: float,
        y: float,
        *,
        button=Qt.LeftButton,
        modifiers: Qt.KeyboardModifiers = Qt.NoModifier,
    ) -> None:
        self._point = QPointF(x, y)
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def position(self):
        return self._point

    def pos(self):
        return self._point.toPoint()

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def _make_object_hit(object_id: str, *, kind: str = "rect", page_num: int = 1) -> ObjectHitInfo:
    return ObjectHitInfo(
        object_kind=kind,
        object_id=object_id,
        page_num=page_num,
        bbox=fitz.Rect(20, 20, 120, 80),
        rotation=0,
        supports_move=True,
        supports_delete=True,
        supports_rotate=(kind == "textbox"),
    )


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.graphics_view = _FakeGraphicsView()
    view.scene = None
    view.current_mode = "objects"
    view.current_page = 0
    view.total_pages = 3
    view.scale = 1.0
    view._fullscreen_active = False
    view.drawing_start = None

    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._clear_text_selection = lambda: None

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

    view._point_hits_object_rotate_handle = lambda scene_pos: False
    view._update_object_selection_visuals = lambda rect=None: None

    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (
        0 if scene_pos.y() < 100 else 1,
        fitz.Point(scene_pos.x(), scene_pos.y()),
    )

    view.sig_delete_object = _FakeSignal()
    view.sig_move_object = _FakeSignal()

    view.controller = SimpleNamespace(
        get_object_info_at_point=lambda page_num, point: None,
        model=SimpleNamespace(doc=[SimpleNamespace(rect=fitz.Rect(0, 0, 500, 500))]),
    )

    view.page_y_positions = [0.0, 800.0, 1600.0]
    view.continuous_pages = True
    view._render_scale = 1.0

    return view


def test_shift_click_toggles_objects_on_same_page(monkeypatch) -> None:
    view = _make_view()

    def _hit(page_num: int, point: fitz.Point):
        if point.x < 50:
            return _make_object_hit("a", kind="rect", page_num=page_num)
        return _make_object_hit("b", kind="rect", page_num=page_num)

    view.controller.get_object_info_at_point = _hit
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    assert getattr(view, "_selected_object_infos", {}) != {}

    pdf_view.PDFView._mouse_press(view, _FakeEvent(60, 10, modifiers=Qt.ShiftModifier))
    assert len(getattr(view, "_selected_object_infos", {})) == 2

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10, modifiers=Qt.ShiftModifier))
    assert len(getattr(view, "_selected_object_infos", {})) == 1


def test_click_on_other_page_resets_selection_set(monkeypatch) -> None:
    view = _make_view()

    def _hit(page_num: int, point: fitz.Point):
        return _make_object_hit(f"{page_num}:{int(point.x)}", kind="rect", page_num=page_num)

    view.controller.get_object_info_at_point = _hit
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_press(view, _FakeEvent(60, 10, modifiers=Qt.ShiftModifier))
    assert len(getattr(view, "_selected_object_infos", {})) == 2

    pdf_view.PDFView._mouse_press(view, _FakeEvent(20, 200))
    assert len(getattr(view, "_selected_object_infos", {})) == 1
    only = next(iter(getattr(view, "_selected_object_infos", {}).values()))
    assert only.page_num == 2


def test_batch_delete_emits_one_request(monkeypatch) -> None:
    view = _make_view()

    def _hit(page_num: int, point: fitz.Point):
        if point.x < 50:
            return _make_object_hit("a", kind="rect", page_num=page_num)
        return _make_object_hit("b", kind="rect", page_num=page_num)

    view.controller.get_object_info_at_point = _hit
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_press(view, _FakeEvent(60, 10, modifiers=Qt.ShiftModifier))

    assert pdf_view.PDFView._delete_selected_object(view) is True
    assert len(view.sig_delete_object.emitted) == 1


def test_batch_move_emits_one_request(monkeypatch) -> None:
    view = _make_view()

    def _hit(page_num: int, point: fitz.Point):
        if point.x < 50:
            return _make_object_hit("a", kind="rect", page_num=page_num)
        return _make_object_hit("b", kind="rect", page_num=page_num)

    view.controller.get_object_info_at_point = _hit
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)

    # Create a 2-item same-page selection set.
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_press(view, _FakeEvent(60, 10, modifiers=Qt.ShiftModifier))
    assert len(getattr(view, "_selected_object_infos", {})) == 2

    # Drag far enough to exceed the threshold and then release.
    pdf_view.PDFView._mouse_move(view, _FakeEvent(110, 110))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(110, 110))

    assert len(view.sig_move_object.emitted) == 1
    req = view.sig_move_object.emitted[0][0]
    assert req.__class__.__name__ == "BatchMoveObjectsRequest"
    assert len(getattr(req, "moves", [])) == 2
