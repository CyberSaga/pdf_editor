from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402
from model.object_requests import ObjectHitInfo  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

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


class _FakeRectItem:
    def __init__(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self._z = 0

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def setRect(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)

    def setPen(self, pen) -> None:
        self._pen = pen

    def setBrush(self, brush) -> None:
        self._brush = brush

    def setZValue(self, z: float) -> None:
        self._z = z

    def scene(self):
        return True


class _FakeEllipseItem(_FakeRectItem):
    pass


class _FakeScene:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.removed: list[object] = []

    def addRect(self, rect: QRectF, pen=None, brush=None):
        item = _FakeRectItem(rect)
        self.added.append(item)
        return item

    def addEllipse(self, rect: QRectF, pen=None, brush=None):
        item = _FakeEllipseItem(rect)
        self.added.append(item)
        return item

    def removeItem(self, item) -> None:
        self.removed.append(item)


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


def _make_object_hit(kind: str = "rect") -> ObjectHitInfo:
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
    view.graphics_view = _FakeGraphicsView()
    view.scene = _FakeScene()
    view.current_mode = "objects"
    view.current_page = 0
    view.total_pages = 1
    view.scale = 1.0
    view._fullscreen_active = False
    view._render_scale = 1.0
    view.page_y_positions = [0.0]
    view.continuous_pages = True

    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._clear_text_selection = lambda: None

    view._selected_object_info = _make_object_hit("rect")
    view._selected_object_infos = {view._selected_object_info.object_id: view._selected_object_info}
    view._selected_object_page_idx = 0

    view._object_selection_rect_item = None
    view._object_rotate_handle_item = None
    view._point_hits_object_rotate_handle = lambda scene_pos: False

    view.sig_resize_object = _FakeSignal()
    view.controller = SimpleNamespace(model=SimpleNamespace(doc=[SimpleNamespace(rect=fitz.Rect(0, 0, 500, 500))]))

    return view


def test_single_select_creates_resize_handles_and_hit_outside_bbox() -> None:
    view = _make_view()

    pdf_view.PDFView._update_object_selection_visuals(view)

    assert getattr(view, "_object_resize_handle_items", None)

    # Top-right handle should extend slightly outside the bbox so it can be hit.
    handle_rects = [item.rect() for item in view._object_resize_handle_items]
    assert any(r.right() > (120.0 * view._render_scale) for r in handle_rects)

    # A point just above the bbox top-right corner should still hit a handle.
    scene_hit = QPointF(120.0 * view._render_scale + 1.0, 20.0 * view._render_scale - 1.0)
    assert pdf_view.PDFView._point_hits_object_resize_handle(view, scene_hit) is True


def test_resize_drag_emits_resize_request(monkeypatch) -> None:
    view = _make_view()
    pdf_view.PDFView._update_object_selection_visuals(view)

    # Pretend the press lands on a resize handle.
    monkeypatch.setattr(pdf_view.PDFView, "_point_hits_object_resize_handle", lambda self, pos: True)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(120, 20))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(150, 120))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 120))

    assert len(view.sig_resize_object.emitted) == 1
    req = view.sig_resize_object.emitted[0][0]
    assert req.__class__.__name__ == "ResizeObjectRequest"


def test_top_left_handle_drag_moves_x0_y0_preserves_x1_y1(monkeypatch) -> None:
    """TL handle drag must move x0/y0; opposite corner (x1, y1) must stay anchored."""
    view = _make_view()
    # bbox is (20, 20, 120, 80); TL handle center is approximately (20, 20)
    pdf_view.PDFView._update_object_selection_visuals(view)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    # Press on TL handle center, drag 15px left and 10px up
    pdf_view.PDFView._mouse_press(view, _FakeEvent(20, 20))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(5, 10))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(5, 10))

    assert len(view.sig_resize_object.emitted) == 1
    req = view.sig_resize_object.emitted[0][0]
    dest = req.destination_rect
    # x0 and y0 must move; x1 and y1 must stay at original values
    assert dest.x0 < 20, f"expected x0 < 20 (TL drag), got {dest.x0}"
    assert dest.y0 < 20, f"expected y0 < 20 (TL drag), got {dest.y0}"
    assert abs(dest.x1 - 120) < 1.0, f"expected x1 ≈ 120 (anchored), got {dest.x1}"
    assert abs(dest.y1 - 80) < 1.0, f"expected y1 ≈ 80 (anchored), got {dest.y1}"


def test_top_left_handle_drag_with_shift_locks_aspect_ratio(monkeypatch) -> None:
    """TL corner drag with Shift held must preserve the original aspect ratio
    end to end through the live mouse event handlers, not just in the pure
    compute_object_resize_rect() unit (which test_compute_resize_rect_shift_locks_
    aspect_ratio already covers directly)."""
    view = _make_view()
    pdf_view.PDFView._update_object_selection_visuals(view)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    # bbox is (20, 20, 120, 80): 100x60, ratio ~1.667. Free-form dx/dy here
    # would change the ratio; Shift must force it back to the original.
    pdf_view.PDFView._mouse_press(view, _FakeEvent(20, 20))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(5, 15, modifiers=Qt.ShiftModifier))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(5, 15, modifiers=Qt.ShiftModifier))

    req = view.sig_resize_object.emitted[0][0]
    dest = req.destination_rect
    original_ratio = 100.0 / 60.0
    assert abs((dest.width / dest.height) - original_ratio) < 0.01
    assert abs(dest.x1 - 120) < 1.0
    assert abs(dest.y1 - 80) < 1.0


def test_compute_resize_rect_free_form_changes_aspect_ratio() -> None:
    """AC-5a: a plain drag resizes freely (aspect ratio is allowed to change)."""
    start = fitz.Rect(20, 20, 120, 80)  # 100×60, ratio ≈ 1.667
    # BR drag: widen a lot, shorten a little → ratio must change.
    out = pdf_view.compute_object_resize_rect(start, anchor=3, dx=100.0, dy=-20.0, lock_ar=False)
    assert abs(out.width - 200.0) < 1e-6
    assert abs(out.height - 40.0) < 1e-6
    assert abs((out.width / out.height) - (start.width / start.height)) > 0.1


def test_compute_resize_rect_shift_locks_aspect_ratio() -> None:
    """AC-5b: Shift+drag preserves the start rect's aspect ratio."""
    start = fitz.Rect(20, 20, 120, 80)  # ratio 100/60
    start_ratio = start.width / start.height
    out = pdf_view.compute_object_resize_rect(start, anchor=3, dx=100.0, dy=-20.0, lock_ar=True)
    assert abs((out.width / out.height) - start_ratio) < 1e-3
    # BR drag keeps the opposite corner (TL = 20,20) anchored.
    assert abs(out.x0 - 20.0) < 1e-6
    assert abs(out.y0 - 20.0) < 1e-6


def test_compute_resize_rect_lock_keeps_opposite_corner_for_tl() -> None:
    """AC-5b: locking about a TL handle keeps the BR corner anchored."""
    start = fitz.Rect(20, 20, 120, 80)
    out = pdf_view.compute_object_resize_rect(start, anchor=0, dx=-50.0, dy=-10.0, lock_ar=True)
    assert abs(out.x1 - 120.0) < 1e-6
    assert abs(out.y1 - 80.0) < 1e-6
    assert abs((out.width / out.height) - (start.width / start.height)) < 1e-3


@pytest.mark.parametrize(
    ("anchor", "dx", "dy", "expected"),
    [
        (4, 35.0, -12.0, fitz.Rect(20, 8, 120, 80)),   # top midpoint
        (5, 25.0, -30.0, fitz.Rect(20, 20, 145, 80)),  # right midpoint
        (6, -40.0, 18.0, fitz.Rect(20, 20, 120, 98)),  # bottom midpoint
        (7, -15.0, 22.0, fitz.Rect(5, 20, 120, 80)),   # left midpoint
    ],
)
def test_compute_resize_rect_edge_handles_move_only_owned_edge(
    anchor: int,
    dx: float,
    dy: float,
    expected: fitz.Rect,
) -> None:
    start = fitz.Rect(20, 20, 120, 80)

    out = pdf_view.compute_object_resize_rect(start, anchor, dx, dy, lock_ar=False)

    assert out == expected


@pytest.mark.parametrize(
    ("anchor", "dx", "dy", "expected"),
    [
        (4, 100.0, 100.0, fitz.Rect(20, 72, 120, 80)),
        (5, -100.0, 100.0, fitz.Rect(20, 20, 28, 80)),
        (6, 100.0, -100.0, fitz.Rect(20, 20, 120, 28)),
        (7, 100.0, -100.0, fitz.Rect(112, 20, 120, 80)),
    ],
)
def test_compute_resize_rect_edge_handles_enforce_minimum_and_ignore_shift_lock(
    anchor: int,
    dx: float,
    dy: float,
    expected: fitz.Rect,
) -> None:
    start = fitz.Rect(20, 20, 120, 80)

    out = pdf_view.compute_object_resize_rect(start, anchor, dx, dy, lock_ar=True)

    assert out == expected


def test_selection_visuals_add_four_midpoint_handles() -> None:
    view = _make_view()

    pdf_view.PDFView._update_object_selection_visuals(view)

    handles = view._object_resize_handle_items
    assert len(handles) == 8
    centers = [(round(item.rect().center().x()), round(item.rect().center().y())) for item in handles]
    assert centers == [
        (20, 20),
        (120, 20),
        (20, 80),
        (120, 80),
        (70, 20),
        (120, 50),
        (70, 80),
        (20, 50),
    ]
    assert pdf_view.PDFView._hit_object_resize_handle_index(view, QPointF(70, 20)) == 4
    assert pdf_view.PDFView._hit_object_resize_handle_index(view, QPointF(120, 50)) == 5
    assert pdf_view.PDFView._hit_object_resize_handle_index(view, QPointF(70, 80)) == 6
    assert pdf_view.PDFView._hit_object_resize_handle_index(view, QPointF(20, 50)) == 7


def test_top_midpoint_drag_changes_height_only(monkeypatch) -> None:
    view = _make_view()
    pdf_view.PDFView._update_object_selection_visuals(view)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(70, 20))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(95, 5, modifiers=Qt.ShiftModifier))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(95, 5))

    req = view.sig_resize_object.emitted[0][0]
    assert req.destination_rect == fitz.Rect(20, 5, 120, 80)


def test_bottom_left_handle_drag_moves_x0_y1_preserves_x1_y0(monkeypatch) -> None:
    """BL handle drag must move x0/y1; opposite corner edge x1 and top y0 must be anchored."""
    view = _make_view()
    # bbox is (20, 20, 120, 80); BL handle center is approximately (20, 80)
    pdf_view.PDFView._update_object_selection_visuals(view)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    # Press on BL handle center, drag 15px left and 10px down
    pdf_view.PDFView._mouse_press(view, _FakeEvent(20, 80))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(5, 90))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(5, 90))

    assert len(view.sig_resize_object.emitted) == 1
    req = view.sig_resize_object.emitted[0][0]
    dest = req.destination_rect
    # x0 and y1 must move; x1 and y0 must stay at original values
    assert dest.x0 < 20, f"expected x0 < 20 (BL drag), got {dest.x0}"
    assert dest.y1 > 80, f"expected y1 > 80 (BL drag), got {dest.y1}"
    assert abs(dest.x1 - 120) < 1.0, f"expected x1 ≈ 120 (anchored), got {dest.x1}"
    assert abs(dest.y0 - 20) < 1.0, f"expected y0 ≈ 20 (anchored), got {dest.y0}"
