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

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

import view.pdf_view as pdf_view


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeEditorWidget:
    def __init__(self, text: str, original_text: str, height: int = 40) -> None:
        self._text = text
        self._original_text = original_text
        self._height = height

    def toPlainText(self) -> str:
        return self._text

    def property(self, name: str):
        if name == "original_text":
            return self._original_text
        return None

    def height(self) -> int:
        return self._height

    def width(self) -> int:
        return 120


class _FakeProxy:
    def __init__(self, widget: _FakeEditorWidget, pos: QPointF | None = None) -> None:
        self._widget = widget
        self._pos = pos or QPointF(0, 0)
        self.last_pos: QPointF | None = None

    def widget(self) -> _FakeEditorWidget:
        return self._widget

    def scene(self):
        return True

    def setPos(self, x, y=None) -> None:
        if y is None:
            point = QPointF(x.x(), x.y())
        else:
            point = QPointF(float(x), float(y))
        self._pos = point
        self.last_pos = point

    def pos(self) -> QPointF:
        return self._pos


class _FakeScene:
    def __init__(self) -> None:
        self.removed: list[object] = []

    def removeItem(self, item: object) -> None:
        self.removed.append(item)


class _FakeCombo:
    def currentText(self) -> str:
        return "12"


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


class _FakeMouseEvent:
    def __init__(self, x: float, y: float) -> None:
        self._point = QPointF(x, y)

    def position(self) -> QPointF:
        return self._point

    def buttons(self):
        return Qt.NoButton


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.scene = _FakeScene()
    view.text_size = _FakeCombo()
    view.sig_edit_text = _FakeSignal()
    view.current_page = 0
    view.continuous_pages = False
    view.page_y_positions = []
    view.page_heights = []
    view._drag_pending = False
    view._drag_active = False
    view._drag_start_scene_pos = None
    view._drag_editor_start_pos = None
    view._pending_text_info = None
    view._last_hover_scene_pos = None
    view.graphics_view = _FakeGraphicsView()
    view._fullscreen_active = False
    view.current_mode = "browse"
    return view


def test_finalize_skips_emit_for_normalized_noop_edit() -> None:
    view = _make_view()
    original_text = "o\ufb03ce   plan"
    view.text_editor = _FakeProxy(_FakeEditorWidget("office plan", original_text))
    view._editing_original_rect = fitz.Rect(10, 20, 120, 50)
    view.editing_rect = fitz.Rect(10, 20, 120, 50)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = original_text

    view._finalize_text_edit_impl()

    assert view.sig_edit_text.calls == []


def test_escape_marks_current_editor_as_discard_before_finalize() -> None:
    view = _make_view()
    view.text_editor = object()
    observed: list[bool] = []
    focus_calls: list[bool] = []
    view._finalize_text_edit = lambda: observed.append(
        bool(getattr(view, "_discard_text_edit_once", False))
    )
    view._focus_page_canvas = lambda: focus_calls.append(True)

    assert view._handle_escape() is True
    assert observed == [True]
    assert focus_calls == [True]


def test_small_drag_can_activate_editor_move(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    view = _make_view()
    view.current_mode = "edit_text"
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text"), pos=QPointF(10, 10))
    view._drag_pending = True
    view._drag_active = False
    view._drag_start_scene_pos = QPointF(0, 0)
    view._drag_editor_start_pos = QPointF(10, 10)
    captured_pages: list[int] = []
    view._editing_page_idx = 0
    view._clamp_editor_pos_to_page = lambda x, y, page_idx: (
        captured_pages.append(page_idx) or (x, y)
    )

    view._mouse_move(_FakeMouseEvent(3, 3))

    assert view._drag_active is True
    assert view.text_editor.last_pos == QPointF(13, 13)
    assert captured_pages == [0]


def test_drag_across_page_updates_editing_page_idx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    view = _make_view()
    view.current_mode = "edit_text"
    view.continuous_pages = True
    view.page_y_positions = [0, 100]
    view.page_heights = [80, 80]
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text", height=40), pos=QPointF(10, 70))
    view._drag_pending = False
    view._drag_active = True
    view._drag_start_scene_pos = QPointF(0, 0)
    view._drag_editor_start_pos = QPointF(10, 70)
    view._editing_page_idx = 0
    captured_pages: list[int] = []
    view._clamp_editor_pos_to_page = lambda x, y, page_idx: (
        captured_pages.append(page_idx) or (x, y)
    )

    view._mouse_move(_FakeMouseEvent(0, 15))

    assert view._editing_page_idx == 1
    assert captured_pages == [1]


def test_editor_shortcut_forwarder_routes_common_actions() -> None:
    forwarder_cls = getattr(pdf_view, "_EditorShortcutForwarder", None)
    assert forwarder_cls is not None

    triggered: list[str] = []

    class _Action:
        def __init__(self, name: str) -> None:
            self.name = name

        def trigger(self) -> None:
            triggered.append(self.name)

    view = SimpleNamespace(
        _action_save=_Action("save"),
        _action_undo=_Action("undo"),
        _action_redo=_Action("redo"),
    )
    forwarder = forwarder_cls(view)

    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(
        None,
        QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier),
    ) is True
    assert triggered == ["save", "undo", "redo", "redo"]
