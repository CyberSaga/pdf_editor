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

from PySide6.QtCore import QPointF, QRectF

import view.pdf_view as pdf_view


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeViewport:
    def __init__(self) -> None:
        self.cursor = None

    def setCursor(self, cursor) -> None:
        self.cursor = cursor


class _FakeGraphicsView:
    def __init__(self) -> None:
        self._viewport = _FakeViewport()

    def mapToScene(self, pos) -> QPointF:
        return QPointF(pos.x(), pos.y())

    def viewport(self) -> _FakeViewport:
        return self._viewport


class _FakeScene:
    def __init__(self) -> None:
        self.removed: list[object] = []

    def removeItem(self, item: object) -> None:
        self.removed.append(item)


class _FakeRectItem:
    def __init__(self, rect: QRectF) -> None:
        self.rect = QRectF(rect)
        self.visible = True
        self.z = 0.0

    def setRect(self, rect: QRectF) -> None:
        self.rect = QRectF(rect)

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def setZValue(self, z: float) -> None:
        self.z = float(z)

    def scene(self):
        return True


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.scene = _FakeScene()
    view.graphics_view = _FakeGraphicsView()
    view.sig_edit_text = _FakeSignal()
    view.sig_move_text_across_pages = _FakeSignal()
    view.current_page = 0
    view.current_mode = "browse"
    view.continuous_pages = False
    view.page_y_positions = []
    view.page_heights = []
    view._fullscreen_active = False
    view._browse_text_cursor_active = False
    view._text_selection_active = False
    view._text_selection_page_idx = None
    view._text_selection_start_scene_pos = None
    view._text_selection_rect_item = None
    view._text_selection_live_doc_rect = None
    view._text_selection_live_text = ""
    view._text_selection_last_scene_pos = None
    view._text_selection_start_span_id = None
    view._text_selection_start_hit_info = None
    view._selected_text_rect_doc = None
    view._selected_text_page_idx = None
    view._selected_text_cached = ""
    view._selected_text_hit_info = None
    view._render_scale = 1.0
    return view


def test_start_text_selection_requires_text_hit_and_stores_start_run() -> None:
    view = _make_view()

    class _FakeSceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            return _FakeRectItem(rect)

    view.scene = _FakeSceneWithAddRect()
    view._clear_hover_highlight = lambda: None
    view._reset_browse_hover_cursor = lambda: None
    view._clear_text_selection = pdf_view.PDFView._clear_text_selection.__get__(view, pdf_view.PDFView)
    view._clamp_scene_point_to_page = lambda scene_pos, page_idx: QPointF(scene_pos.x(), scene_pos.y())
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))
    view.controller = SimpleNamespace(
        get_text_info_at_point=lambda page_num, point, allow_fallback=True: None
        if point.x < 50
        else SimpleNamespace(target_span_id="run-2", font="helv", size=12)
    )

    pdf_view.PDFView._start_text_selection(view, QPointF(10, 10), 0)

    assert view._text_selection_active is False

    pdf_view.PDFView._start_text_selection(view, QPointF(60, 20), 0)

    assert view._text_selection_active is True
    assert view._text_selection_start_span_id == "run-2"
    assert view._text_selection_start_hit_info.target_span_id == "run-2"


def test_start_text_selection_rejects_block_fallback_hits() -> None:
    view = _make_view()

    class _FakeSceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            return _FakeRectItem(rect)

    view.scene = _FakeSceneWithAddRect()
    view._clear_hover_highlight = lambda: None
    view._reset_browse_hover_cursor = lambda: None
    view._clear_text_selection = pdf_view.PDFView._clear_text_selection.__get__(view, pdf_view.PDFView)
    view._clamp_scene_point_to_page = lambda scene_pos, page_idx: QPointF(scene_pos.x(), scene_pos.y())
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))
    view.controller = SimpleNamespace(
        get_text_info_at_point=lambda page_num, point, allow_fallback=True: None
        if not allow_fallback
        else SimpleNamespace(target_span_id="fallback-run", font="helv", size=12, fallback_used=True)
    )

    pdf_view.PDFView._start_text_selection(view, QPointF(60, 20), 0)

    assert view._text_selection_active is False


def test_finalize_text_selection_uses_run_anchored_snapshot_and_preserves_start_hit_info() -> None:
    view = _make_view()
    start_hit = SimpleNamespace(target_span_id="run-2", font="cour", size=14)
    view._text_selection_active = True
    view._text_selection_page_idx = 0
    view._text_selection_start_scene_pos = QPointF(60, 20)
    view._text_selection_last_scene_pos = None
    view._text_selection_start_span_id = "run-2"
    view._text_selection_start_hit_info = start_hit
    view._text_selection_live_doc_rect = fitz.Rect(100, 10, 180, 60)
    view.page_y_positions = [0.0]

    class _FakeSceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            return _FakeRectItem(rect)

    view.scene = _FakeSceneWithAddRect()
    view._text_selection_rect_item = _FakeRectItem(QRectF(60, 20, 1, 1))
    view._clamp_scene_point_to_page = lambda scene_pos, page_idx: QPointF(scene_pos.x(), scene_pos.y())
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))
    view._sync_text_property_panel_state = lambda: None
    view.controller = SimpleNamespace(
        get_text_selection_snapshot_from_run=lambda page_num, start_span_id, end_point: (
            "Beta Gamma\nDelta Epsilon Zeta\nEta Theta",
            fitz.Rect(132, 59, 258, 123),
        )
    )

    pdf_view.PDFView._finalize_text_selection(view, QPointF(230, 120))

    assert view._selected_text_cached == "Beta Gamma\nDelta Epsilon Zeta\nEta Theta"
    assert view._selected_text_rect_doc == fitz.Rect(132, 59, 258, 123)
    assert view._selected_text_hit_info is start_hit
