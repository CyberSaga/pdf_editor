from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeTimer:
    def __init__(self) -> None:
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active


class _FakeViewport:
    def __init__(self) -> None:
        self._cursor = None
        self.unset_called = False

    def mapFrom(self, widget, pos: QPoint) -> QPoint:
        _ = widget
        return QPoint(pos)

    def cursor(self):
        return self._cursor

    def setCursor(self, cursor) -> None:
        self._cursor = cursor

    def unsetCursor(self) -> None:
        self.unset_called = True
        self._cursor = None


class _FakeScrollBar:
    def __init__(self) -> None:
        self._value = 0

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = int(value)


class _FakeGraphicsView:
    def __init__(self) -> None:
        self._viewport = _FakeViewport()
        self._hbar = _FakeScrollBar()
        self._vbar = _FakeScrollBar()

    def viewport(self) -> _FakeViewport:
        return self._viewport

    def horizontalScrollBar(self) -> _FakeScrollBar:
        return self._hbar

    def verticalScrollBar(self) -> _FakeScrollBar:
        return self._vbar

    def mapToScene(self, pos) -> QPointF:
        return QPointF(pos.x(), pos.y())

    def mapToGlobal(self, pos: QPoint) -> QPoint:
        return QPoint(pos)


class _FakeEvent:
    def __init__(self, x: float, y: float, button=Qt.LeftButton) -> None:
        self._pos = QPointF(x, y)
        self._button = button
        self.accepted = False

    def position(self):
        return self._pos

    def pos(self):
        return self._pos.toPoint()

    def button(self):
        return self._button

    def accept(self) -> None:
        self.accepted = True


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.graphics_view = _FakeGraphicsView()
    view.sig_mode_changed = _FakeSignal()
    view.current_mode = "browse"
    view.current_page = 0
    view.total_pages = 1
    view.scale = 1.0
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._selected_object_info = None
    view._fullscreen_active = False
    view.text_editor = None
    view._context_menu_pos = None
    view._resolve_object_info_for_context_menu_pos = lambda pos: None
    view._resolve_text_info_for_context_menu_pos = lambda pos: None
    view._copy_selected_text_to_clipboard = lambda: None
    view._select_all_text_on_current_page = lambda: None
    view._zoom_relative = lambda factor: None
    view._fit_to_view = lambda: None
    view._export_specific_pages = lambda pages: None
    view._rotate_specific_pages = lambda pages, degrees: None
    view._delete_specific_pages = lambda pages: None
    view._insert_blank_page_at = lambda position: None
    view._insert_pages_from_file_at = lambda position: None
    view._save_as = lambda: None
    view._print_document = lambda: None
    view._optimize_pdf_copy = lambda: None
    view._rotate_pages = lambda: None
    view._finalize_text_edit = lambda *args, **kwargs: None
    view._event_scene_pos = lambda event: QPointF(float(event.position().x()), float(event.position().y()))
    view._autopan_timer = _FakeTimer()
    view._autopan_active = False
    view._autopan_origin_viewport = None
    view._autopan_cursor_viewport = None
    view._autopan_accum_x = 0.0
    view._autopan_accum_y = 0.0
    view._autopan_prev_cursor = None
    view._autopan_suppress_next_context_menu = False
    view._autopan_manual_menu = False
    return view


def test_middle_click_enters_autopan(monkeypatch) -> None:
    view = _make_view()

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(200, 220, Qt.MiddleButton)
    pdf_view.PDFView._mouse_press(view, event)

    assert event.accepted is True
    assert view._autopan_active is True
    assert view._autopan_origin_viewport == QPoint(200, 220)
    assert view._autopan_cursor_viewport == QPoint(200, 220)
    assert view._autopan_timer.isActive() is True


def test_second_middle_click_exits_autopan(monkeypatch) -> None:
    view = _make_view()

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(200, 220, Qt.MiddleButton))
    pdf_view.PDFView._mouse_press(view, _FakeEvent(260, 280, Qt.MiddleButton))

    assert view._autopan_active is False
    assert view._autopan_timer.isActive() is False
    assert view._autopan_origin_viewport is None
    assert view._autopan_cursor_viewport is None


def test_right_click_exit_shows_context_menu(monkeypatch) -> None:
    view = _make_view()

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(view, "_show_context_menu", lambda pos: setattr(view, "_context_menu_pos", QPoint(pos)))

    pdf_view.PDFView._mouse_press(view, _FakeEvent(200, 220, Qt.MiddleButton))
    event = _FakeEvent(320, 360, Qt.RightButton)
    pdf_view.PDFView._mouse_press(view, event)

    assert event.accepted is True
    assert view._autopan_active is False
    assert view._context_menu_pos == QPoint(320, 360)


def test_autopan_tick_scrolls_with_fractional_accumulation() -> None:
    view = _make_view()
    view._autopan_active = True
    view._autopan_origin_viewport = QPoint(100, 100)
    view._autopan_cursor_viewport = QPoint(100, 140)
    view._autopan_accum_x = 0.0
    view._autopan_accum_y = 0.0

    pdf_view.PDFView._autopan_tick(view)
    first = view.graphics_view.verticalScrollBar().value()
    pdf_view.PDFView._autopan_tick(view)
    second = view.graphics_view.verticalScrollBar().value()

    expected_step = (40.0 - view._AUTOPAN_DEADZONE_PX) / view._AUTOPAN_DIVISOR
    assert first == math.floor(expected_step)
    assert second > first


def test_autopan_mouse_move_updates_cursor_position(monkeypatch) -> None:
    view = _make_view()
    view._autopan_active = True
    view._autopan_origin_viewport = QPoint(100, 100)
    view._autopan_cursor_viewport = QPoint(100, 100)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(180, 210)
    pdf_view.PDFView._mouse_move(view, event)

    assert event.accepted is True
    assert view._autopan_cursor_viewport == QPoint(180, 210)


def test_autopan_speed_scales_with_distance() -> None:
    view = _make_view()
    vbar = view.graphics_view.verticalScrollBar()

    view._autopan_active = True
    view._autopan_origin_viewport = QPoint(100, 100)
    view._autopan_cursor_viewport = QPoint(100, 300)  # far
    vbar.setValue(0)
    for _ in range(10):
        pdf_view.PDFView._autopan_tick(view)
    far = vbar.value()

    view._autopan_accum_x = 0.0
    view._autopan_accum_y = 0.0
    view._autopan_cursor_viewport = QPoint(100, 120)  # near
    vbar.setValue(0)
    for _ in range(10):
        pdf_view.PDFView._autopan_tick(view)
    near = vbar.value()

    assert far > near * 2


def test_context_menu_manual_bypasses_single_signal_suppression(monkeypatch) -> None:
    view = _make_view()
    labels: list[str] = []

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions: list[_FakeAction] = []

        def addAction(self, text: str, callback=None):
            _ = callback
            self._actions.append(_FakeAction(text))
            return self._actions[-1]

        def addSeparator(self):
            return None

        def exec_(self, pos):
            _ = pos
            labels.extend([action.text() for action in self._actions])
            view._context_menu_pos = QPoint(5, 6)
            return None

    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    view._autopan_suppress_next_context_menu = True
    pdf_view.PDFView._show_context_menu_manual(view, QPoint(5, 6))
    assert labels
    assert view._autopan_suppress_next_context_menu is True

    labels.clear()
    pdf_view.PDFView._show_context_menu(view, QPoint(5, 6))
    assert labels == []
    assert view._autopan_suppress_next_context_menu is False


def test_autopan_real_view_enters_and_exits(qapp, monkeypatch) -> None:
    _ = qapp
    view = pdf_view.PDFView(defer_heavy_panels=True)
    try:
        monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
        event = _FakeEvent(150, 160, Qt.MiddleButton)
        pdf_view.PDFView._mouse_press(view, event)
        assert view._autopan_active is True
        assert view._autopan_timer.isActive()

        pdf_view.PDFView._mouse_press(view, _FakeEvent(150, 160, Qt.MiddleButton))
        assert view._autopan_active is False
        assert view._autopan_timer.isActive() is False
    finally:
        view.close()
