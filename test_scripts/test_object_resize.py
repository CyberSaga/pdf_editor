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
