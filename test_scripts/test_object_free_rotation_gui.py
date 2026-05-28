"""AC-4 (view) — free drag-rotation interaction.

Covers the angle maths (direction match, AC-4b) and that dragging the rotate
handle emits an absolute-angle RotateObjectRequest (AC-4a), while a click with no
drag keeps the legacy 90° step (AC-4e).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402
from model.object_requests import ObjectHitInfo  # noqa: E402


# ---------------------------------------------------------------------------
# Pure angle helpers
# ---------------------------------------------------------------------------


def test_screen_angle_is_clockwise_in_scene_coords() -> None:
    # Scene y is down: a point below-right of centre is +45°, below-left is +135°.
    assert abs(pdf_view.screen_angle_degrees(0, 0, 10, 10) - 45.0) < 1e-6
    assert abs(pdf_view.screen_angle_degrees(0, 0, -10, 10) - 135.0) < 1e-6
    assert abs(pdf_view.screen_angle_degrees(0, 0, 10, 0) - 0.0) < 1e-6


def test_absolute_rotation_from_drag_matches_clockwise_direction() -> None:
    # Dragging the handle clockwise (angle increases) must rotate the object
    # clockwise on screen, i.e. decrease the stored (raw-cm) angle.
    start = pdf_view.screen_angle_degrees(0, 0, 100, 0)   # 0°
    end = pdf_view.screen_angle_degrees(0, 0, 0, 100)     # +90° clockwise
    out = pdf_view.absolute_rotation_from_drag(0.0, start, end)
    assert abs(out - 270.0) < 1e-6  # (0 - 90) % 360
    # Counter-clockwise drag → increase stored angle.
    end_ccw = pdf_view.screen_angle_degrees(0, 0, 0, -100)  # -90°
    out_ccw = pdf_view.absolute_rotation_from_drag(0.0, start, end_ccw)
    assert abs(out_ccw - 90.0) < 1e-6


# ---------------------------------------------------------------------------
# Drag interaction
# ---------------------------------------------------------------------------


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted: list = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _FakeViewport:
    def mapFrom(self, _parent, pos):
        return QPoint(pos.x(), pos.y())


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
    def __init__(self, x, y, *, button=Qt.LeftButton, modifiers=Qt.NoModifier) -> None:
        self._p = QPointF(x, y)
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def position(self):
        return self._p

    def pos(self):
        return self._p.toPoint()

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def _make_view(*, object_kind: str = "native_image"):
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.graphics_view = _FakeGraphicsView()
    view.current_mode = "objects"
    view._render_scale = 1.0
    view.page_y_positions = [0.0]
    view.continuous_pages = True
    view._clear_text_selection = lambda: None
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))
    view.controller = type(
        "_Controller",
        (),
        {"get_object_info_at_point": staticmethod(lambda page_num, point: None)},
    )()
    info = ObjectHitInfo(
        object_kind=object_kind,
        object_id=f"{object_kind}:1:0",
        page_num=1,
        bbox=fitz.Rect(100, 100, 200, 180),
        rotation=0,
        supports_move=True,
        supports_delete=True,
        supports_rotate=True,
    )
    view._selected_object_info = info
    view._selected_object_infos = {info.object_id: info}
    view._object_selection_rect_item = None
    view._object_rotate_handle_item = None
    view._object_resize_handle_items = []
    view._object_rotate_pending = False
    view._object_rotate_active = False
    view._object_resize_pending = False
    view._object_drag_pending = False
    view._object_drag_active = False
    view._text_selection_active = False
    view.drawing_start = None
    view._hit_object_resize_handle_index = lambda pos: -1
    view._update_object_selection_visuals = lambda *a, **k: None
    view.sig_rotate_object = _FakeSignal()
    return view


def test_rotate_handle_drag_emits_absolute_rotation(monkeypatch) -> None:
    view = _make_view()
    monkeypatch.setattr(pdf_view.PDFView, "_point_hits_object_rotate_handle", lambda self, pos: True)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **k: None)

    # Object centre is (150, 140). Press to the right, drag downward (clockwise).
    pdf_view.PDFView._mouse_press(view, _FakeEvent(250, 140))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(150, 240))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 240))

    assert len(view.sig_rotate_object.emitted) == 1
    req = view.sig_rotate_object.emitted[0][0]
    assert req.__class__.__name__ == "RotateObjectRequest"
    assert req.absolute_rotation is not None
    # Clockwise quarter-turn drag → stored angle ≈ 270 (0 - 90 mod 360).
    assert abs((req.absolute_rotation % 360) - 270.0) < 1.0


def test_textbox_drag_rotate_does_not_emit_absolute_rotation(monkeypatch) -> None:
    view = _make_view(object_kind="textbox")
    monkeypatch.setattr(pdf_view.PDFView, "_point_hits_object_rotate_handle", lambda self, pos: True)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **k: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(250, 140))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(150, 240))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 240))

    assert not view.sig_rotate_object.emitted


class _RotatableItem:
    def __init__(self) -> None:
        self.rotation = None
        self.origin = None

    def setRotation(self, angle) -> None:
        self.rotation = angle

    def setTransformOriginPoint(self, point) -> None:
        self.origin = point


def test_apply_selection_rotation_turns_box_and_handles() -> None:
    """AC-4c: the selection box and all handles receive the rotation transform
    about the shared object centre."""
    view = _make_view()
    view._object_rotate_center_scene = QPointF(150.0, 140.0)
    box = _RotatableItem()
    rot_handle = _RotatableItem()
    handles = [_RotatableItem(), _RotatableItem(), _RotatableItem(), _RotatableItem()]
    view._object_selection_rect_item = box
    view._object_rotate_handle_item = rot_handle
    view._object_resize_handle_items = handles

    pdf_view.PDFView._apply_object_selection_rotation(view, 30.0)

    for item in [box, rot_handle, *handles]:
        assert item.rotation == 30.0
        assert item.origin == QPointF(150.0, 140.0)


def test_rotate_handle_click_without_drag_uses_90_step(monkeypatch) -> None:
    view = _make_view()
    monkeypatch.setattr(pdf_view.PDFView, "_point_hits_object_rotate_handle", lambda self, pos: True)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **k: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(250, 140))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(250, 140))  # no move

    assert len(view.sig_rotate_object.emitted) == 1
    req = view.sig_rotate_object.emitted[0][0]
    assert req.absolute_rotation is None
    assert req.rotation_delta == 90
