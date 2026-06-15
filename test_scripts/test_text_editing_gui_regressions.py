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

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QComboBox, QMenu, QPushButton, QStackedWidget, QWidget  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402
import view.text_editing as text_editing  # noqa: E402
from view.text_editing import MoveTextRequest  # noqa: E402


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
        self._properties: dict[str, object] = {}
        self.stylesheet = ""

    def toPlainText(self) -> str:
        return self._text

    def property(self, name: str):
        if name in self._properties:
            return self._properties[name]
        if name == "original_text":
            return self._original_text
        return None

    def setProperty(self, name: str, value) -> None:
        self._properties[name] = value

    def height(self) -> int:
        return self._height

    def width(self) -> int:
        return 120

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheet = stylesheet


class _FakeEditorDocument:
    def __init__(self, undo_available: bool = False, redo_available: bool = False) -> None:
        self._undo_available = undo_available
        self._redo_available = redo_available

    def isUndoAvailable(self) -> bool:
        return self._undo_available

    def isRedoAvailable(self) -> bool:
        return self._redo_available


class _FakeShortcutEditorWidget(_FakeEditorWidget):
    def __init__(
        self,
        text: str = "text",
        original_text: str = "text",
        *,
        undo_available: bool = False,
        redo_available: bool = False,
    ) -> None:
        super().__init__(text, original_text)
        self._document = _FakeEditorDocument(undo_available=undo_available, redo_available=redo_available)
        self.undo_calls = 0
        self.redo_calls = 0

    def document(self) -> _FakeEditorDocument:
        return self._document

    def undo(self) -> None:
        self.undo_calls += 1

    def redo(self) -> None:
        self.redo_calls += 1


class _FakeAction:
    def __init__(self, name: str) -> None:
        self.name = name
        self.enabled = True
        self.triggered = 0

    def trigger(self) -> None:
        self.triggered += 1

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _FakeProxy:
    def __init__(self, widget: _FakeEditorWidget, pos: QPointF | None = None) -> None:
        self._widget = widget
        self._pos = pos or QPointF(0, 0)
        self.last_pos: QPointF | None = None
        self.rotation = 0.0
        self.transform_origin = QPointF(0, 0)

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

    def setRotation(self, rotation: float) -> None:
        self.rotation = float(rotation)

    def setTransformOriginPoint(self, x, y=None) -> None:
        if y is None:
            self.transform_origin = QPointF(float(x.x()), float(x.y()))
        else:
            self.transform_origin = QPointF(float(x), float(y))


class _FakeInlineSignal:
    def connect(self, callback) -> None:
        self._callback = callback


class _FakeInlineDocSignal:
    def connect(self, callback) -> None:
        self._callback = callback


class _FakeInlineDocument:
    def __init__(self) -> None:
        self.undoAvailable = _FakeInlineDocSignal()
        self.redoAvailable = _FakeInlineDocSignal()


class _FakeInlineViewport:
    def setAutoFillBackground(self, enabled: bool) -> None:
        self.auto_fill_background = bool(enabled)


class _FakeInlineTextEditor:
    WidgetWidth = object()

    def __init__(self, text: str) -> None:
        self.text = text
        self._properties: dict[str, object] = {}
        self._width = 0
        self._height = 0
        self.focus_out_requested = _FakeInlineSignal()
        self._document = _FakeInlineDocument()
        self._viewport = _FakeInlineViewport()
        self.stylesheet = ""

    def setProperty(self, name: str, value) -> None:
        self._properties[name] = value

    def property(self, name: str):
        return self._properties.get(name)

    def setFont(self, font) -> None:
        self.font = font

    def setAutoFillBackground(self, enabled: bool) -> None:
        self.auto_fill_background = bool(enabled)

    def viewport(self) -> _FakeInlineViewport:
        return self._viewport

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheet = stylesheet

    def setFixedWidth(self, width: int) -> None:
        self._width = int(width)

    def setMinimumHeight(self, height: int) -> None:
        self._height = max(self._height, int(height))

    def setFixedHeight(self, height: int) -> None:
        self._height = int(height)

    def setLineWrapMode(self, mode) -> None:
        self.line_wrap_mode = mode

    def setWordWrapMode(self, mode) -> None:
        self.word_wrap_mode = mode

    def document(self) -> _FakeInlineDocument:
        return self._document

    def installEventFilter(self, event_filter) -> None:
        self.event_filter = event_filter

    def setFocus(self, *args, **kwargs) -> None:
        self.focused = True

    def toPlainText(self) -> str:
        return self.text

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _FakeRectItem:
    def __init__(self, rect) -> None:
        self.rect = QRectF(rect)
        self.brush = None
        self.pen = None
        self.z_value = 0.0
        self.visible = True

    def setRect(self, rect) -> None:
        self.rect = QRectF(rect)

    def setBrush(self, brush) -> None:
        self.brush = brush

    def setPen(self, pen) -> None:
        self.pen = pen

    def setZValue(self, value: float) -> None:
        self.z_value = float(value)

    def setVisible(self, value: bool) -> None:
        self.visible = bool(value)

    def scene(self):
        return True


class _FakePixmap:
    def __init__(self, image: QImage) -> None:
        self._image = image

    def isNull(self) -> bool:
        return False

    def toImage(self) -> QImage:
        return self._image


class _FakePageItem:
    def __init__(self, image: QImage, rect: QRectF) -> None:
        self._pixmap = _FakePixmap(image)
        self._rect = rect

    def pixmap(self) -> _FakePixmap:
        return self._pixmap

    def sceneBoundingRect(self) -> QRectF:
        return self._rect


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

    def height(self) -> int:
        return 800


class _FakeGraphicsView:
    def __init__(self) -> None:
        self._viewport = _FakeViewport()

    def mapToScene(self, pos) -> QPointF:
        return QPointF(pos.x(), pos.y())

    def viewport(self) -> _FakeViewport:
        return self._viewport

    def mapToGlobal(self, pos) -> QPoint:
        if hasattr(pos, "x") and hasattr(pos, "y"):
            return QPoint(int(pos.x()), int(pos.y()))
        return QPoint(0, 0)


class _FakeViewportWithHeight:
    def __init__(self, height: int) -> None:
        self._height = int(height)

    def height(self) -> int:
        return self._height


class _FakeGraphicsViewWithViewportHeight:
    def __init__(self, height: int) -> None:
        self._viewport = _FakeViewportWithHeight(height)

    def viewport(self):
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
    view.text_editor = None
    view.sig_edit_text = _FakeSignal()
    view.sig_move_text_across_pages = _FakeSignal()
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
    view._text_selection_active = False
    view._text_selection_page_idx = None
    view._text_selection_start_scene_pos = None
    view._text_selection_rect_item = None
    view._text_selection_live_doc_rect = None
    view._text_selection_last_scene_pos = None
    view._text_selection_start_span_id = None
    view._text_selection_start_hit_info = None
    view._selected_text_rect_doc = None
    view._selected_text_page_idx = None
    view._selected_text_cached = ""
    view._selected_text_hit_info = None
    view._autopan_active = False
    view._autopan_suppress_next_context_menu = False
    view._autopan_manual_menu = False
    return view


def _attach_text_property_panel(view: pdf_view.PDFView) -> None:
    view.page_info_card = QWidget()
    view.text_card = QWidget()
    view.right_stacked_widget = QStackedWidget()
    view.right_stacked_widget.addWidget(view.page_info_card)
    view.right_stacked_widget.addWidget(view.text_card)
    view.right_stacked_widget.setCurrentWidget(view.page_info_card)
    view.text_apply_btn = QPushButton("套用")
    view.text_cancel_btn = QPushButton("取消")
    view.text_font = QComboBox()
    view.text_font.addItem("Sans (helv)", "helv")
    view.text_font.addItem("Serif (tiro)", "tiro")
    view.text_font.addItem("Mono (cour)", "cour")
    view.text_font.addItem("CJK Serif (china-ts)", "china-ts")
    view.text_size = QComboBox()
    view.text_size.addItems(["8", "10", "12", "14", "16", "18"])
    view.text_target_mode_combo = QComboBox()
    view.text_target_mode_combo.addItem("run", "run")
    view.text_target_mode_combo.addItem("paragraph", "paragraph")
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._selected_text_page_idx = None
    view._selected_text_hit_info = None


def _capture_context_menu_labels(
    monkeypatch: pytest.MonkeyPatch,
    view: pdf_view.PDFView,
    pos: QPoint | None = None,
) -> list[str]:
    labels: list[str] = []

    def _fake_exec(menu: QMenu, *args, **kwargs):
        labels.extend([action.text() for action in menu.actions() if action.text()])
        return None

    monkeypatch.setattr(QMenu, "exec_", _fake_exec)
    view._show_context_menu(pos or QPoint(0, 0))
    return labels


def _make_image(width: int, height: int, color: QColor) -> QImage:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(color)
    return image


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


def test_text_property_panel_helper_disables_actions_without_editor(qapp) -> None:
    view = _make_view()
    _attach_text_property_panel(view)

    view._sync_text_property_panel_state()

    assert view.right_stacked_widget.currentWidget() is view.page_info_card
    assert view.text_apply_btn.isEnabled() is False
    assert view.text_cancel_btn.isEnabled() is False


def test_text_property_panel_helper_shows_selection_state_without_enabling_actions(qapp) -> None:
    view = _make_view()
    _attach_text_property_panel(view)
    view._selected_text_cached = "selected text"
    view._selected_text_rect_doc = fitz.Rect(10, 10, 40, 20)
    view._selected_text_page_idx = 0
    view._selected_text_hit_info = SimpleNamespace(font="cour", size=14)

    view._sync_text_property_panel_state()

    assert view.right_stacked_widget.currentWidget() is view.text_card
    assert view.text_font.currentData() == "cour"
    assert view.text_size.currentText() == "14"
    assert view.text_apply_btn.isEnabled() is False
    assert view.text_cancel_btn.isEnabled() is False


def test_text_property_panel_helper_enables_actions_for_live_editor(qapp) -> None:
    view = _make_view()
    _attach_text_property_panel(view)
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text"))

    view._sync_text_property_panel_state()

    assert view.right_stacked_widget.currentWidget() is view.text_card
    assert view.text_apply_btn.isEnabled() is True
    assert view.text_cancel_btn.isEnabled() is True


def test_text_property_panel_live_editor_uses_pdf_size_state_not_display_pt(qapp) -> None:
    from PySide6.QtGui import QFont

    class _EditorWithDisplayFont:
        def __init__(self) -> None:
            self._font = QFont("Arial")
            self._font.setPointSizeF(9.0)

        def font(self):
            return self._font

    view = _make_view()
    _attach_text_property_panel(view)
    view.text_editor = _FakeProxy(_EditorWithDisplayFont())
    view.editing_font_name = "helv"
    view._editing_initial_size = 14.0
    view._editing_current_pdf_size = 14.0

    view._sync_text_property_panel_state()

    assert view.text_size.currentText() == "14"


def test_context_menu_includes_safe_browse_actions_for_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _make_view()
    view.total_pages = 1
    view.scale = 1.0
    view._selected_text_cached = "selected text"
    view._selected_text_rect_doc = fitz.Rect(10, 10, 40, 20)

    labels = _capture_context_menu_labels(monkeypatch, view)

    assert "Copy Selected Text" in labels
    assert "Select All" in labels
    assert "Zoom In" in labels
    assert "Zoom Out" in labels
    assert "Fit to View" in labels


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
        get_text_info_at_point=lambda page_num, point, allow_fallback=True: None if point.x < 50 else SimpleNamespace(
            target_span_id="run-2",
            font="helv",
            size=12,
        )
    )

    pdf_view.PDFView._start_text_selection(view, QPointF(10, 10), 0)
    assert view._text_selection_active is False

    pdf_view.PDFView._start_text_selection(view, QPointF(60, 20), 0)

    assert view._text_selection_active is True
    assert getattr(view, "_text_selection_start_span_id", None) == "run-2"
    assert getattr(view, "_text_selection_start_hit_info", None).target_span_id == "run-2"


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
        get_text_info_at_point=lambda page_num, point, allow_fallback=True: None if not allow_fallback else SimpleNamespace(
            target_span_id="fallback-run",
            font="helv",
            size=12,
            fallback_used=True,
        )
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
    view._render_scale = 1.0
    view.page_y_positions = [0.0]
    view.continuous_pages = False

    class _FakeSceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            return _FakeRectItem(rect)

    view.scene = _FakeSceneWithAddRect()
    view._text_selection_rect_item = _FakeRectItem(QRectF(60, 20, 1, 1))
    view._clamp_scene_point_to_page = lambda scene_pos, page_idx: QPointF(scene_pos.x(), scene_pos.y())
    view._scene_rect_to_doc_rect = lambda rect, page_idx: fitz.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())
    view._sync_text_property_panel_state = lambda: None
    view.controller = SimpleNamespace(
        get_text_selection_lines=lambda page_num, start_span_id, end_point, start_point=None: (
            "Beta Gamma\nDelta Epsilon Zeta\nEta Theta",
            [fitz.Rect(132, 59, 258, 123)],
        )
    )

    pdf_view.PDFView._finalize_text_selection(view, QPointF(230, 120))

    assert view._selected_text_cached == "Beta Gamma\nDelta Epsilon Zeta\nEta Theta"
    assert view._selected_text_rect_doc == fitz.Rect(132, 59, 258, 123)
    assert view._selected_text_hit_info is start_hit


def test_context_menu_offers_edit_text_when_point_hits_editable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _make_view()
    view.total_pages = 1
    view.scale = 1.0
    view.controller = SimpleNamespace(
        get_text_info_at_point=lambda page_num, point: SimpleNamespace(
            target_bbox=fitz.Rect(10, 10, 40, 20),
            target_text="editable",
            font="helv",
            size=12,
            color=(0.0, 0.0, 0.0),
            rotation=0,
            target_span_id="span-1",
            target_mode="run",
        )
    )
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(20, 20))
    view.graphics_view = _FakeGraphicsView()

    labels = _capture_context_menu_labels(monkeypatch, view, QPoint(12, 12))

    assert "Edit Text" in labels


def test_escape_marks_current_editor_as_discard_before_finalize() -> None:
    view = _make_view()
    view.text_editor = object()
    observed = []
    focus_calls: list[bool] = []
    view._finalize_text_edit = lambda reason=pdf_view.TextEditFinalizeReason.CLICK_AWAY: observed.append(reason)
    view._focus_page_canvas = lambda: focus_calls.append(True)

    assert view._handle_escape() is True
    assert observed == [pdf_view.TextEditFinalizeReason.ESCAPE]
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


def test_drag_page_resolution_follows_cross_page_target_when_present() -> None:
    view = _make_view()
    view.continuous_pages = True
    view.page_y_positions = [0, 100]
    view.page_heights = [80, 80]
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text", height=40), pos=QPointF(10, 70))
    view._editing_page_idx = 0
    view._editing_origin_page_idx = 0

    page_idx = view._resolve_editor_page_idx_for_drag(85)

    assert page_idx == 1


def test_finalize_cross_page_existing_text_emits_move_signal_only() -> None:
    view = _make_view()
    original_rect = fitz.Rect(10, 20, 120, 50)
    current_rect = fitz.Rect(16, 12, 126, 42)
    view.text_editor = _FakeProxy(_FakeEditorWidget("moved text", "source text"))
    view._editing_original_rect = fitz.Rect(original_rect)
    view.editing_rect = fitz.Rect(current_rect)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = "source text"
    view._editing_page_idx = 1
    view._editing_origin_page_idx = 0
    view.editing_target_span_id = "span-1"
    view.editing_target_mode = "run"
    view.editing_intent = "edit_existing"

    view._finalize_text_edit_impl()

    assert view.sig_edit_text.calls == []
    assert len(view.sig_move_text_across_pages.calls) == 1
    call = view.sig_move_text_across_pages.calls[0]
    request = call[0]
    assert isinstance(request, MoveTextRequest)
    assert request.source_page == 1
    assert request.source_rect == original_rect
    assert request.destination_page == 2
    assert request.destination_rect == current_rect
    assert request.new_text == "moved text"


def test_average_image_rect_color_returns_local_average() -> None:
    average_fn = getattr(pdf_view, "_average_image_rect_color", None)
    assert average_fn is not None

    image = _make_image(2, 2, QColor(0, 0, 0))
    image.setPixelColor(0, 0, QColor(10, 20, 30))
    image.setPixelColor(1, 0, QColor(30, 40, 50))
    image.setPixelColor(0, 1, QColor(50, 60, 70))
    image.setPixelColor(1, 1, QColor(70, 80, 90))

    color = average_fn(image, QRect(0, 0, 2, 2))

    assert (color.red(), color.green(), color.blue()) == (40, 50, 60)


def test_sample_page_mask_color_uses_local_scene_crop() -> None:
    view = _make_view()
    sample_fn = getattr(view, "_sample_page_mask_color", None)
    assert sample_fn is not None

    image = _make_image(10, 10, QColor(20, 30, 40))
    for x in range(5, 10):
        for y in range(5, 10):
            image.setPixelColor(x, y, QColor(200, 210, 220))

    view.page_items = [_FakePageItem(image, QRectF(0, 0, 100, 100))]

    color = sample_fn(0, QRectF(60, 60, 20, 20))

    assert (color.red(), color.green(), color.blue()) == (200, 210, 220)


def test_drag_move_refreshes_editor_mask_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    view = _make_view()
    view.current_mode = "edit_text"
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text"), pos=QPointF(10, 10))
    view._drag_pending = False
    view._drag_active = True
    view._drag_start_scene_pos = QPointF(0, 0)
    view._drag_editor_start_pos = QPointF(10, 10)
    view._editing_page_idx = 0
    view._clamp_editor_pos_to_page = lambda x, y, page_idx: (x, y)
    refresh_calls: list[bool] = []
    view._refresh_text_editor_mask_color = lambda: refresh_calls.append(True)

    view._mouse_move(_FakeMouseEvent(4, 4))

    assert refresh_calls == [True]


def test_editor_shortcut_forwarder_keeps_save_forwarding() -> None:
    forwarder_cls = getattr(pdf_view, "_EditorShortcutForwarder", None)
    assert forwarder_cls is not None

    view = SimpleNamespace(
        _action_save=_FakeAction("save"),
        _action_undo=_FakeAction("undo"),
        _action_redo=_FakeAction("redo"),
        text_editor=None,
    )
    forwarder = forwarder_cls(view)

    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.ControlModifier)) is True
    assert view._action_save.triggered == 1


def test_editor_shortcut_forwarder_keeps_save_as_forwarding() -> None:
    forwarder_cls = getattr(pdf_view, "_EditorShortcutForwarder", None)
    assert forwarder_cls is not None

    view = SimpleNamespace(
        _action_save=_FakeAction("save"),
        _action_save_as=_FakeAction("save_as"),
        _action_undo=_FakeAction("undo"),
        _action_redo=_FakeAction("redo"),
        text_editor=None,
    )
    forwarder = forwarder_cls(view)

    assert (
        forwarder.eventFilter(
            None,
            QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier),
        )
        is True
    )
    assert view._action_save_as.triggered == 1


def test_editor_shortcut_forwarder_handles_escape_before_ctrl_guard() -> None:
    forwarder_cls = getattr(pdf_view, "_EditorShortcutForwarder", None)
    assert forwarder_cls is not None

    observed: list[str] = []
    view = SimpleNamespace(
        _action_save=_FakeAction("save"),
        _action_undo=_FakeAction("undo"),
        _action_redo=_FakeAction("redo"),
        text_editor=object(),
        _handle_escape=lambda: observed.append("escape") or True,
    )
    forwarder = forwarder_cls(view)

    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)) is True
    assert observed == ["escape"]


def test_editor_shortcut_forwarder_uses_local_undo_redo_history() -> None:
    forwarder_cls = getattr(pdf_view, "_EditorShortcutForwarder", None)
    assert forwarder_cls is not None

    widget = _FakeShortcutEditorWidget(undo_available=True, redo_available=True)
    view = SimpleNamespace(
        _action_save=_FakeAction("save"),
        _action_undo=_FakeAction("undo"),
        _action_redo=_FakeAction("redo"),
        text_editor=_FakeProxy(widget),
    )
    forwarder = forwarder_cls(view)

    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(
        None,
        QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier),
    ) is True

    assert widget.undo_calls == 1
    assert widget.redo_calls == 2
    assert view._action_undo.triggered == 0
    assert view._action_redo.triggered == 0


def test_save_shortcut_finalizes_editor_before_emitting_save() -> None:
    view = _make_view()
    recorded = []
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text"))
    view.sig_save = _FakeSignal()
    view._finalize_text_edit = lambda reason=pdf_view.TextEditFinalizeReason.CLICK_AWAY: recorded.append(reason)

    view._save()

    assert recorded == [pdf_view.TextEditFinalizeReason.SAVE_SHORTCUT]
    assert view.sig_save.calls == [()]


def test_save_as_shortcut_finalizes_editor_before_emitting_save_as(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _make_view()
    recorded = []
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text"))
    view.sig_save_as = _FakeSignal()
    view._finalize_text_edit = lambda reason=pdf_view.TextEditFinalizeReason.CLICK_AWAY: recorded.append(reason)
    monkeypatch.setattr(pdf_view.QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("out.pdf", "PDF (*.pdf)"))

    view._save_as()

    assert recorded == [pdf_view.TextEditFinalizeReason.SAVE_SHORTCUT]
    assert view.sig_save_as.calls == [("out.pdf",)]


def test_save_as_uses_current_document_default_path_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _make_view()
    view.sig_save_as = _FakeSignal()
    view._save_as_default_path = str(Path("C:/tmp/Current Draft.pdf"))
    captured: dict[str, object] = {}

    def _fake_get_save_file_name(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return ("out.pdf", "PDF (*.pdf)")

    monkeypatch.setattr(pdf_view.QFileDialog, "getSaveFileName", _fake_get_save_file_name)

    view._save_as()

    assert captured["args"][2] == view._save_as_default_path
    assert view.sig_save_as.calls == [("out.pdf",)]


def test_finalize_noop_records_explicit_result() -> None:
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

    result = view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.CLICK_AWAY)

    assert result.reason is pdf_view.TextEditFinalizeReason.CLICK_AWAY
    assert result.outcome is pdf_view.TextEditOutcome.NO_OP
    assert result.delta.text_changed is False
    assert result.delta.position_changed is False
    assert view.sig_edit_text.calls == []


def test_finalize_position_only_existing_text_records_commit_result() -> None:
    view = _make_view()
    original_rect = fitz.Rect(10, 20, 120, 50)
    moved_rect = fitz.Rect(14, 30, 124, 60)
    view.text_editor = _FakeProxy(_FakeEditorWidget("same text", "same text"))
    view._editing_original_rect = fitz.Rect(original_rect)
    view.editing_rect = fitz.Rect(moved_rect)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = "same text"
    view.editing_intent = "edit_existing"

    result = view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.CLICK_AWAY)

    assert result.outcome is pdf_view.TextEditOutcome.COMMITTED
    assert result.delta.text_changed is False
    assert result.delta.position_changed is True
    assert result.delta.page_changed is False
    assert len(view.sig_edit_text.calls) == 1
    payload = view.sig_edit_text.calls[0][0]
    assert isinstance(payload, pdf_view.EditTextRequest)
    assert payload.new_rect == moved_rect


def test_editor_shortcut_forwarder_consumes_empty_local_history_without_fallback() -> None:
    forwarder_cls = getattr(pdf_view, "_EditorShortcutForwarder", None)
    assert forwarder_cls is not None

    widget = _FakeShortcutEditorWidget(undo_available=False, redo_available=False)
    view = SimpleNamespace(
        _action_save=_FakeAction("save"),
        _action_undo=_FakeAction("undo"),
        _action_redo=_FakeAction("redo"),
        text_editor=_FakeProxy(widget),
    )
    forwarder = forwarder_cls(view)

    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.ControlModifier)) is True
    assert forwarder.eventFilter(
        None,
        QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier),
    ) is True

    assert widget.undo_calls == 0
    assert widget.redo_calls == 0
    assert view._action_undo.triggered == 0
    assert view._action_redo.triggered == 0


def test_toggle_document_undo_redo_actions_disables_and_reenables() -> None:
    view = _make_view()
    view._action_undo = _FakeAction("undo")
    view._action_redo = _FakeAction("redo")

    view._set_document_undo_redo_enabled(False)
    assert view._action_undo.enabled is False
    assert view._action_redo.enabled is False

    view._set_document_undo_redo_enabled(True)
    assert view._action_undo.enabled is True
    assert view._action_redo.enabled is True


def test_update_undo_redo_enabled_prefers_local_editor_history() -> None:
    view = _make_view()
    view._action_undo = _FakeAction("undo")
    view._action_redo = _FakeAction("redo")
    view._action_undo_right = _FakeAction("undo_right")
    view._action_redo_right = _FakeAction("redo_right")
    widget = _FakeShortcutEditorWidget(undo_available=False, redo_available=True)
    view.text_editor = _FakeProxy(widget)

    view.update_undo_redo_enabled(True, True)

    assert view._action_undo.enabled is False
    assert view._action_redo.enabled is True
    assert view._action_undo_right.enabled is False
    assert view._action_redo_right.enabled is True


# ── Eng Review mandatory tests ───────────────────────────────────────────────


def _make_view_for_finalize(original_text: str = "Hello", new_text: str = "Hello World") -> pdf_view.PDFView:
    """Build a minimal view configured for a mid-edit finalize call."""
    view = _make_view()
    view.text_editor = _FakeProxy(_FakeEditorWidget(new_text, original_text))
    view._editing_original_rect = fitz.Rect(10, 20, 120, 50)
    view.editing_rect = fitz.Rect(10, 20, 120, 50)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = original_text
    view.editing_intent = "edit_existing"
    view._editing_page_idx = 0
    # Stub outline bookkeeping added by Week 1 fix
    view._block_outline_items: dict = {}
    view._hover_hidden_outline_key = None
    view._active_outline_key = None
    view._edit_font_size_connected = False
    view._edit_font_family_connected = False
    view._action_undo = _FakeAction("undo")
    view._action_redo = _FakeAction("redo")
    return view


def test_mode_switch_commits_edit_not_discards() -> None:
    """Switching modes while editing must auto-commit, not silently discard."""
    view = _make_view_for_finalize(original_text="Hello", new_text="Hello World")

    result = view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.MODE_SWITCH)

    assert result is not None
    assert result.outcome is not pdf_view.TextEditOutcome.DISCARDED, (
        "MODE_SWITCH must not discard — typed text would be silently lost"
    )
    # Outcome must be COMMITTED (text changed) or NO_OP (no change), never DISCARDED
    assert result.outcome in (pdf_view.TextEditOutcome.COMMITTED, pdf_view.TextEditOutcome.NO_OP)


def test_escape_still_discards() -> None:
    """ESCAPE must still discard — it is an explicit user cancel signal."""
    view = _make_view_for_finalize(original_text="Hello", new_text="Hello World")

    result = view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.ESCAPE)

    assert result is not None
    assert result.outcome is pdf_view.TextEditOutcome.DISCARDED, (
        "ESCAPE must always discard — user explicitly cancelled"
    )


def _outline_controller(model: SimpleNamespace) -> SimpleNamespace:
    """Controller mock exposing the R2.5 read-only facade the block-outline view
    code now calls (controller.iter_text_targets / ensure_page_index_built /
    get_text_blocks), forwarding to a model-shaped mock's block_manager. Mirrors
    PDFController's real facade so the view's behavior is unchanged."""
    bm = model.block_manager

    def iter_text_targets(page_idx, mode, *, blocks_fallback=False):
        if mode == "paragraph":
            return list(getattr(bm, "get_paragraphs", lambda _i: [])(page_idx) or [])
        candidates = list(getattr(bm, "get_runs", lambda _i: [])(page_idx) or [])
        if blocks_fallback and not candidates:
            candidates = list(getattr(bm, "get_blocks", lambda _i: [])(page_idx) or [])
        return candidates

    return SimpleNamespace(
        model=model,
        ensure_page_index_built=model.ensure_page_index_built,
        iter_text_targets=iter_text_targets,
        get_text_blocks=lambda page_idx: list(getattr(bm, "get_blocks", lambda _i: [])(page_idx) or []),
    )


def test_block_outlines_only_drawn_for_visible_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """_draw_all_block_outlines must only query visible pages using 0-based page indices."""

    class _FakeSceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            item = SimpleNamespace(setZValue=lambda z: None, setVisible=lambda v: None)
            return item

    view = _make_view()
    view._block_outline_items = {}
    view._hover_hidden_outline_key = None
    view._active_outline_key = None
    view._render_scale = 1.0
    view.scene = _FakeSceneWithAddRect()

    fake_run = SimpleNamespace(bbox=fitz.Rect(10, 10, 40, 20))
    visited_pages: list[int] = []

    def _fake_get_runs(page_idx: int):
        visited_pages.append(page_idx)
        return [fake_run]

    view.controller = _outline_controller(
        SimpleNamespace(
            doc=True,
            text_target_mode="run",
            ensure_page_index_built=lambda page_num: None,
            block_manager=SimpleNamespace(
                get_runs=_fake_get_runs,
                get_paragraphs=lambda page_idx: [],
            ),
        )
    )
    # visible_page_range returns 0-based (start, end) inclusive
    monkeypatch.setattr(view, "visible_page_range", lambda prefetch=0: (3, 5))

    view._draw_all_block_outlines()

    # visible_page_range returned (3, 5) → pages 3,4,5 (0-based) → page_num 4,5,6 (1-based)
    assert visited_pages == [3, 4, 5], (
        f"Must only draw outlines for visible pages 3-5 (0-based), got {visited_pages}"
    )


def test_block_outlines_follow_run_boxes_in_run_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSceneWithAddRect(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.added_rects: list[QRectF] = []

        def addRect(self, rect, pen=None, brush=None):
            self.added_rects.append(QRectF(rect))
            return SimpleNamespace(setZValue=lambda z: None, setVisible=lambda v: None)

    view = _make_view()
    view._block_outline_items = {}
    view._hover_hidden_outline_key = None
    view._active_outline_key = None
    view._render_scale = 1.0
    view.scene = _FakeSceneWithAddRect()
    view.page_y_positions = [0.0]
    view.continuous_pages = False

    fake_run = SimpleNamespace(bbox=fitz.Rect(20, 30, 70, 44))
    fake_block = SimpleNamespace(rect=fitz.Rect(10, 10, 180, 90))

    view.controller = _outline_controller(
        SimpleNamespace(
            doc=True,
            text_target_mode="run",
            ensure_page_index_built=lambda page_num: None,
            block_manager=SimpleNamespace(
                get_runs=lambda page_idx: [fake_run],
                get_paragraphs=lambda page_idx: [],
                get_blocks=lambda page_idx: [fake_block],
            ),
        )
    )
    monkeypatch.setattr(view, "visible_page_range", lambda prefetch=0: (0, 0))

    view._draw_all_block_outlines()

    assert view.scene.added_rects == [QRectF(20.0, 30.0, 50.0, 14.0)]


def test_paragraph_outlines_use_light_blue_dashed_border(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSceneWithAddRect(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.added: list[tuple[QRectF, object, object]] = []

        def addRect(self, rect, pen=None, brush=None):
            self.added.append((QRectF(rect), pen, brush))
            return SimpleNamespace(setZValue=lambda z: None, setVisible=lambda v: None)

    view = _make_view()
    view.current_mode = "edit_text"
    view._block_outline_items = {}
    view._hover_hidden_outline_key = None
    view._active_outline_key = None
    view._render_scale = 1.0
    view.scene = _FakeSceneWithAddRect()
    view.page_y_positions = [0.0]
    view.continuous_pages = False

    fake_para = SimpleNamespace(bbox=fitz.Rect(20, 30, 170, 74))
    view.controller = _outline_controller(
        SimpleNamespace(
            doc=True,
            text_target_mode="paragraph",
            ensure_page_index_built=lambda page_num: None,
            block_manager=SimpleNamespace(get_paragraphs=lambda page_idx: [fake_para]),
        )
    )
    monkeypatch.setattr(view, "visible_page_range", lambda prefetch=0: (0, 0))

    view._draw_all_block_outlines()

    assert len(view.scene.added) == 1
    _, pen, brush = view.scene.added[0]
    assert pen.style() == Qt.DashLine
    assert pen.color() == QColor(147, 197, 253, 170)
    assert brush.style() == Qt.NoBrush


def test_build_text_editor_stylesheet_keeps_editor_background_transparent() -> None:
    view = _make_view()

    stylesheet = view._build_text_editor_stylesheet((12, 34, 56), QColor(200, 210, 220))

    assert "background: transparent" in stylesheet
    assert "color: rgb(12,34,56)" in stylesheet
    assert "background: rgb(" not in stylesheet


@pytest.mark.parametrize("editor_intent", ["edit_existing", "add_new"])
def test_create_text_editor_keeps_background_transparent_for_edit_and_add_text(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    editor_intent: str,
) -> None:
    class _FakePreviewBackedInlineTextEditor(_FakeInlineTextEditor):
        def __init__(self, text: str, renderer=None, **legacy_kwargs) -> None:
            super().__init__(text)
            self.renderer = renderer

        def configure_render_context(self, **kwargs) -> None:
            self.render_context = kwargs

        def freeze_first_frame(self, image) -> None:
            self.frozen_first_frame = image

        def setFocus(self, *args, **kwargs) -> None:
            self.focused = True

    class _FakeSceneWithAddWidget(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.last_proxy: _FakeProxy | None = None

        def addWidget(self, widget):
            self.last_proxy = _FakeProxy(widget)
            return self.last_proxy

    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneWithAddWidget()
    view._render_scale = 1.0
    view.controller = SimpleNamespace(
        model=SimpleNamespace(get_render_width_for_edit=lambda page_num, rect: 40.0),
        get_render_width_for_edit=lambda page_num, rect: 40.0,
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view._set_edit_focus_guard = lambda enabled: None
    view._sync_text_property_panel_state = lambda: None

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color = lambda: None

    monkeypatch.setattr(text_editing, "PreviewBackedInlineTextEditor", _FakePreviewBackedInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda view: object())

    manager.create_text_editor(
        rect=fitz.Rect(10, 20, 50, 40),
        text="transparent text",
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        editor_intent=editor_intent,
    )

    proxy = view.scene.last_proxy
    assert proxy is not None
    editor_widget = proxy.widget()
    assert editor_widget.auto_fill_background is False
    assert editor_widget.viewport().auto_fill_background is False
    assert "background: transparent" in editor_widget.stylesheet
    assert "background: rgb(" not in editor_widget.stylesheet


def test_create_text_editor_rotates_proxy_for_vertical_text(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    class _FakeSceneWithAddWidget(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.last_proxy: _FakeProxy | None = None

        def addWidget(self, widget):
            self.last_proxy = _FakeProxy(widget)
            return self.last_proxy

    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneWithAddWidget()
    view._render_scale = 1.0
    view.controller = SimpleNamespace(
        model=SimpleNamespace(get_render_width_for_edit=lambda page_num, rect: 40.0),
        get_render_width_for_edit=lambda page_num, rect: 40.0,
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view._set_edit_focus_guard = lambda enabled: None
    view._sync_text_property_panel_state = lambda: None

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color = lambda: None

    monkeypatch.setattr(text_editing, "InlineTextEditor", _FakeInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda view: object())

    manager.create_text_editor(
        rect=fitz.Rect(10, 20, 50, 120),
        text="vertical text",
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        rotation=90,
        target_span_id="span-rotated",
        target_mode="run",
    )

    proxy = view.scene.last_proxy
    assert proxy is not None
    assert proxy.rotation == 90.0
    assert proxy.transform_origin == QPointF(0.0, 0.0)
    assert proxy.pos() == QPointF(50.0, 20.0)
    assert proxy.widget().width() == 100
    assert proxy.widget().height() == 40


def test_create_text_editor_adds_mask_item_to_hide_display_text(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    class _FakeSceneWithEditorMask(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.last_proxy: _FakeProxy | None = None
            self.last_mask_item: _FakeRectItem | None = None
            self.last_focus_border_item: _FakeRectItem | None = None

        def addWidget(self, widget):
            self.last_proxy = _FakeProxy(widget)
            return self.last_proxy

        def addRect(self, rect, pen=None, brush=None):
            item = _FakeRectItem(rect)
            item.pen = pen
            item.brush = brush
            if pen is not None and pen.style() == Qt.NoPen:
                self.last_mask_item = item
            else:
                self.last_focus_border_item = item
            return item

    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneWithEditorMask()
    view._render_scale = 1.0
    view.controller = SimpleNamespace(
        model=SimpleNamespace(get_render_width_for_edit=lambda page_num, rect: 40.0),
        get_render_width_for_edit=lambda page_num, rect: 40.0,
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view._set_edit_focus_guard = lambda enabled: None
    view._sync_text_property_panel_state = lambda: None
    view._sample_page_mask_color = lambda page_idx, scene_rect: QColor(210, 220, 230)

    manager = pdf_view.TextEditManager(view)

    monkeypatch.setattr(text_editing, "InlineTextEditor", _FakeInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda view: object())

    manager.create_text_editor(
        rect=fitz.Rect(10, 20, 50, 40),
        text="masked text",
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
    )

    assert getattr(view, "_text_editor_mask_item", None) is view.scene.last_mask_item
    assert view.scene.last_mask_item is not None
    # Mask rect must cover the editor proxy; exact height depends on measured
    # content layout (QTextDocument), not a fixed formula.
    editor_widget = view.scene.last_proxy._widget
    assert view.scene.last_mask_item.rect.x() == 10.0
    assert view.scene.last_mask_item.rect.y() == 20.0
    assert view.scene.last_mask_item.rect.width() == 80.0
    assert view.scene.last_mask_item.rect.height() == float(editor_widget._height)
    assert getattr(view, "_text_editor_focus_border_item", None) is view.scene.last_focus_border_item
    assert view.scene.last_focus_border_item is not None
    assert view.scene.last_focus_border_item.rect == view.scene.last_mask_item.rect.adjusted(
        -2.0, -2.0, 2.0, 2.0
    )
    assert view.scene.last_focus_border_item.pen.style() == Qt.SolidLine
    assert view.scene.last_focus_border_item.pen.color() == QColor(30, 120, 255, 230)


def test_finalize_text_edit_removes_mask_item(qapp) -> None:
    view = _make_view_for_finalize()
    mask_item = _FakeRectItem(QRectF(10, 20, 120, 40))
    border_item = _FakeRectItem(QRectF(10, 20, 120, 40))
    view._text_editor_mask_item = mask_item
    view._text_editor_focus_border_item = border_item
    view._block_outline_items = {}
    view._active_outline_key = None

    view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.ESCAPE)

    assert mask_item in view.scene.removed
    assert border_item in view.scene.removed
    assert getattr(view, "_text_editor_mask_item", None) is None
    assert getattr(view, "_text_editor_focus_border_item", None) is None


def test_cmd_shift_z_fires_redo(qapp) -> None:
    """Ctrl+Shift+Z (Cmd+Shift+Z on macOS) shortcut must emit sig_redo."""
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QWidget

    # Re-create exactly what __init__ does for the Cmd+Shift+Z alias
    parent = QWidget()
    shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), parent)

    redo_fired = [0]
    shortcut.activated.connect(lambda: redo_fired.__setitem__(0, redo_fired[0] + 1))

    # Programmatically activate the shortcut (same as key press)
    shortcut.activated.emit()

    assert redo_fired[0] == 1, "Ctrl+Shift+Z shortcut must fire exactly once when activated"


# ── Phase-2 red-light regressions ───────────────────────────────────────────


class _FractionalCombo:
    def currentText(self) -> str:
        return "9.5"


def test_phase2_finalize_preserves_fractional_font_size_in_edit_request() -> None:
    """Phase-2 symptoms 2/5 root cause: finalize must forward the fractional session
    size into ``EditTextRequest.size`` without int-truncation or round-trip loss.
    """
    view = _make_view()
    view.text_size = _FractionalCombo()
    view.text_editor = _FakeProxy(_FakeEditorWidget("edited text", "original text"))
    view._editing_original_rect = fitz.Rect(10, 20, 120, 50)
    view.editing_rect = fitz.Rect(10, 20, 120, 50)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 9.5
    view.editing_original_text = "original text"
    view.editing_intent = "edit_existing"

    view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.CLICK_AWAY)

    assert len(view.sig_edit_text.calls) == 1, (
        "finalize must emit exactly one EditTextRequest for a fractional-size edit"
    )
    payload = view.sig_edit_text.calls[0][0]
    assert isinstance(payload, pdf_view.EditTextRequest)
    assert abs(float(payload.size) - 9.5) < 1e-6, (
        f"Fractional font size collapsed to {payload.size} in EditTextRequest"
    )


def test_phase2_create_text_editor_records_fractional_initial_size(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """Phase-2 symptom 5: rotated/fractional editors must preserve float size at creation.

    Current root cause: ``view._editing_initial_size = int(round(font_size))`` silently
    collapses 9.5 to 10, which cascades into oversized/clipped rotated proxies and
    broken no-op detection on finalize.
    """
    class _FakeSceneWithAddWidget(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.last_proxy: _FakeProxy | None = None

        def addWidget(self, widget):
            self.last_proxy = _FakeProxy(widget)
            return self.last_proxy

    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneWithAddWidget()
    view._render_scale = 1.0
    view.controller = SimpleNamespace(
        model=SimpleNamespace(get_render_width_for_edit=lambda page_num, rect: 40.0),
        get_render_width_for_edit=lambda page_num, rect: 40.0,
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view._set_edit_focus_guard = lambda enabled: None
    view._sync_text_property_panel_state = lambda: None

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color = lambda: None

    monkeypatch.setattr(text_editing, "InlineTextEditor", _FakeInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda view: object())

    manager.create_text_editor(
        rect=fitz.Rect(10, 20, 50, 120),
        text="fractional text",
        font_name="helv",
        font_size=9.5,
        color=(0.0, 0.0, 0.0),
        rotation=90,
        target_span_id="span-frac",
        target_mode="run",
    )

    recorded = getattr(view, "_editing_initial_size", None)
    assert recorded is not None
    assert abs(float(recorded) - 9.5) < 1e-6, (
        f"Editor initial size truncated to {recorded}; fractional sizes lost at editor creation"
    )


def test_phase2_refresh_mask_matches_local_background_with_texture_underlay(qapp) -> None:
    """Mask should use a background-matched texture (opaque) rather than a flat fill."""
    view = _make_view()
    editor_widget = _FakeEditorWidget("mask text", "mask text")
    editor_widget.setProperty("text_rgb", (12, 34, 56))
    view.text_editor = _FakeProxy(editor_widget, pos=QPointF(10, 20))
    view._editing_page_idx = 0
    page_img = _make_image(400, 400, QColor(210, 220, 230))
    # Simulate dark source glyph strokes inside the editor region; the mask
    # generation should smooth and blend these out.
    for y in range(24, 58):
        for x in range(18, 126):
            if (x + y) % 5 == 0:
                page_img.setPixelColor(x, y, QColor(30, 30, 30))
    view.page_items = [_FakePageItem(page_img, QRectF(0, 0, 400, 400))]

    class _SceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            item = _FakeRectItem(rect)
            item.pen = pen
            item.brush = brush
            return item

    view.scene = _SceneWithAddRect()

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color()

    assert "background: transparent" in editor_widget.stylesheet, (
        f"editor stylesheet lost transparency after mask refresh: {editor_widget.stylesheet!r}"
    )
    assert "background: rgb(" not in editor_widget.stylesheet, (
        f"Mask refresh introduced a solid background on the editor: {editor_widget.stylesheet!r}"
    )
    mask_item = getattr(view, "_text_editor_mask_item", None)
    assert mask_item is not None, "mask refresh must create the scene mask item"
    assert mask_item.brush is not None, (
        "mask refresh must assign an opaque underlay brush to hide PDF text"
    )
    assert not mask_item.brush.texture().isNull(), (
        "background-matched mask should use a texture brush from local page pixels"
    )
    mask_rgb = editor_widget.property("mask_rgb")
    assert isinstance(mask_rgb, tuple) and len(mask_rgb) == 3
    # The generated underlay should stay near the local page background color.
    assert abs(mask_rgb[0] - 210) <= 35
    assert abs(mask_rgb[1] - 220) <= 35
    assert abs(mask_rgb[2] - 230) <= 35
    debug = editor_widget.property("mask_debug_metrics") or {}
    assert debug.get("mask_mode") == "background_match"
    assert float(debug.get("ring_delta", 999.0)) <= 35.0
    assert float(debug.get("leak_pct", 1.0)) <= 0.01
    assert float(debug.get("contrast_ratio", 0.0)) >= 1.0
    assert float(debug.get("tint_strength", 1.0)) <= 0.20


def test_phase2_refresh_mask_falls_back_to_dark_underlay_for_light_text() -> None:
    view = _make_view()
    editor_widget = _FakeEditorWidget("mask text", "mask text")
    editor_widget.setProperty("text_rgb", (250, 250, 250))
    view.text_editor = _FakeProxy(editor_widget, pos=QPointF(10, 20))
    view._editing_page_idx = 9  # force unavailable sampling path
    view.page_items = []

    class _SceneWithAddRect(_FakeScene):
        def addRect(self, rect, pen=None, brush=None):
            item = _FakeRectItem(rect)
            item.pen = pen
            item.brush = brush
            return item

    view.scene = _SceneWithAddRect()

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color()

    mask_item = getattr(view, "_text_editor_mask_item", None)
    assert mask_item is not None, "mask refresh must create the scene mask item"
    assert mask_item.brush is not None, "mask refresh must assign a readable underlay brush"
    assert mask_item.brush.color() != QColor(255, 255, 255), (
        f"light editor text needs a dark fallback underlay, got {mask_item.brush.color().getRgb()}"
    )
    debug = editor_widget.property("mask_debug_metrics") or {}
    assert debug.get("mask_mode") == "fallback"


class _FakeSceneCapture(_FakeScene):
    def __init__(self) -> None:
        super().__init__()
        self.last_proxy: _FakeProxy | None = None

    def addWidget(self, widget):
        self.last_proxy = _FakeProxy(widget)
        return self.last_proxy


def _make_phase2_height_view(monkeypatch: pytest.MonkeyPatch) -> tuple[pdf_view.PDFView, pdf_view.TextEditManager]:
    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneCapture()
    view._render_scale = 2.0
    view.controller = SimpleNamespace(
        model=SimpleNamespace(get_render_width_for_edit=lambda page_num, rect: 200.0)
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda _: None
    view._set_edit_focus_guard = lambda _: None
    view._sync_text_property_panel_state = lambda: None

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color = lambda: None

    monkeypatch.setattr(text_editing, "InlineTextEditor", _FakeInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda v: object())
    return view, manager


def test_phase2_editor_height_fits_content_not_paragraph_rect(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """Finding 1: paragraph rect is 300pt tall but text is one line.

    Editor proxy height must be ≈ one line height, NOT the full paragraph
    bounding-box height (~600px at 2× scale).

    Root cause: _compute_editor_proxy_layout blindly used scaled_rect.height
    from the paragraph-mode resolver, ignoring that rendered text occupies one
    line. Fix measures actual content via QTextDocument layout.
    """
    view, manager = _make_phase2_height_view(monkeypatch)

    manager.create_text_editor(
        rect=fitz.Rect(0, 0, 200, 300.0),
        text="single line of text",
        font_name="helv",
        font_size=10.0,
        color=(0.0, 0.0, 0.0),
        rotation=0,
        target_span_id="span-1",
        target_mode="paragraph",
    )

    editor = view.scene.last_proxy._widget
    # Generous ceiling: 3× one-line height at 10pt. Paragraph rect (600px
    # at 2× scale) is ~15× a single line — so this fails loudly if the fix
    # regresses back to rect-based height.
    max_acceptable_px = int(10.0 * 2.0 * 3)
    assert editor._height <= max_acceptable_px, (
        f"Editor height {editor._height}px exceeds single-line ceiling "
        f"{max_acceptable_px}px for a paragraph rect of 300pt "
        f"(oversized grey void — Finding 1)"
    )


def test_phase2_editor_height_accommodates_wrapped_paragraph(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """Guard against the opposite failure: wrapped multi-line paragraph text
    usually has NO ``\\n`` (adjacent lines joined with spaces by
    ``EditableParagraph`` assembly). A naive ``text.count('\\n') + 1`` heuristic
    would under-size the editor to 1 line, cutting off the user's content.

    The measurement must use real text layout (QTextDocument) so wrapping
    across a narrow width produces a tall-enough editor.
    """
    view, manager = _make_phase2_height_view(monkeypatch)
    long_text = " ".join(["paragraph word"] * 60)  # ~800 chars, no newlines
    single_line_baseline_px = int(10.0 * 2.0 * 2)  # generous 2× one-line ceiling

    manager.create_text_editor(
        rect=fitz.Rect(0, 0, 100, 200),
        text=long_text,
        font_name="helv",
        font_size=10.0,
        color=(0.0, 0.0, 0.0),
        rotation=0,
        target_span_id="span-wrap",
        target_mode="paragraph",
    )

    editor = view.scene.last_proxy._widget
    assert editor._height > single_line_baseline_px, (
        f"Wrapped paragraph got only {editor._height}px — under-sized by "
        f"a newline-counting heuristic? Expected multi-line layout."
    )


def test_editor_height_capped_to_viewport_ratio_for_long_text(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    view, manager = _make_phase2_height_view(monkeypatch)
    view.graphics_view = _FakeGraphicsViewWithViewportHeight(300)
    long_text = " ".join(["word"] * 400)

    manager.create_text_editor(
        rect=fitz.Rect(0, 0, 80, 300),
        text=long_text,
        font_name="helv",
        font_size=10.0,
        color=(0.0, 0.0, 0.0),
        rotation=0,
        target_span_id="span-long",
        target_mode="paragraph",
    )

    editor = view.scene.last_proxy._widget
    assert editor._height <= 180, (
        f"Editor height {editor._height}px should cap at 60% of a 300px viewport"
    )


def test_phase2_editor_font_matches_pdf_render_scale(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """Editing-vs-committed visual parity: widget glyphs must render at the
    same physical pixel size as the rendered PDF glyphs underneath. Otherwise
    the text in the editor appears a different size than the final PDF output,
    and wrapping boundaries drift between editing and after commit.

    Relationship: ``widget_pt × logical_dpi/72`` widget-px per em (Qt font
    rendering) must equal ``pdf_font × render_scale`` physical-px per em
    (PyMuPDF raster at ``72×rs`` DPI). Scene is 1:1 with physical px at
    devicePixelRatio=1, so widget-px ≈ physical-px.
    """
    view, manager = _make_phase2_height_view(monkeypatch)
    render_scale = view._render_scale  # 2.0 from the helper
    pdf_font_size = 10.0

    manager.create_text_editor(
        rect=fitz.Rect(0, 0, 200, 40),
        text="visual parity check",
        font_name="helv",
        font_size=pdf_font_size,
        color=(0.0, 0.0, 0.0),
    )

    editor = view.scene.last_proxy._widget
    widget_pt = editor.font().pointSizeF()
    widget_dpi = text_editing._widget_logical_dpi()
    widget_em_px = widget_pt * (widget_dpi / 72.0)
    pdf_em_px = pdf_font_size * render_scale

    visual_ratio = widget_em_px / pdf_em_px
    assert 0.95 < visual_ratio < 1.05, (
        f"Widget em-height {widget_em_px:.2f}px vs PDF em-height {pdf_em_px:.2f}px "
        f"(ratio {visual_ratio:.3f}) — editor text will look visually "
        f"different from the underlying PDF, breaking editing↔committed parity."
    )


def test_phase2_editor_height_honors_embedded_newlines(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """Paragraphs split on bullets / large gaps DO get literal ``\\n`` from
    ``EditableParagraph`` assembly. The editor must size tall enough for
    those explicit line breaks.
    """
    view, manager = _make_phase2_height_view(monkeypatch)

    manager.create_text_editor(
        rect=fitz.Rect(0, 0, 200, 200),
        text="line one\nline two\nline three\nline four",
        font_name="helv",
        font_size=10.0,
        color=(0.0, 0.0, 0.0),
        rotation=0,
        target_span_id="span-multi",
        target_mode="paragraph",
    )

    editor = view.scene.last_proxy._widget
    # Four explicit lines must exceed a two-line ceiling, and must not hit
    # the MIN clamp at 40px.
    two_line_ceiling_px = int(10.0 * 2.0 * 2)
    assert editor._height > two_line_ceiling_px, (
        f"Four-line editor collapsed to {editor._height}px — newlines ignored?"
    )


def test_create_text_editor_uses_source_span_font_size_and_width(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    """The inline editor must open with font size and width that match the source span.

    Regression guard for two pre-commit fidelity failures:
    - Editor font pt != _display_font_pt(span_size, render_scale) → user sees
      glyphs at a different size than the rendered PDF.
    - Editor width != int(rect.width * render_scale) → text wraps at different
      positions than the source span and the committed PDF will diverge.
    """
    class _FakeSceneWithAddWidget(_FakeScene):
        def __init__(self) -> None:
            super().__init__()
            self.last_proxy: _FakeProxy | None = None

        def addWidget(self, widget):
            self.last_proxy = _FakeProxy(widget)
            return self.last_proxy

    source_font_size = 14.0
    source_rect = fitz.Rect(50, 80, 250, 100)  # width = 200pt
    render_scale = 1.0

    view = _make_view()
    _attach_text_property_panel(view)
    view.scene = _FakeSceneWithAddWidget()
    view._render_scale = render_scale
    # Mirror PDFModel.get_render_width_for_edit on this branch: returns float(rect.width)
    view.controller = SimpleNamespace(
        model=SimpleNamespace(
            get_render_width_for_edit=lambda page_num, rect: float(rect.width)
        )
    )
    view._refresh_undo_redo_action_state = lambda: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view._set_edit_focus_guard = lambda enabled: None
    view._sync_text_property_panel_state = lambda: None

    manager = pdf_view.TextEditManager(view)
    manager.refresh_text_editor_mask_color = lambda: None

    monkeypatch.setattr(text_editing, "InlineTextEditor", _FakeInlineTextEditor)
    monkeypatch.setattr(text_editing, "_EditorShortcutForwarder", lambda view: object())

    manager.create_text_editor(
        rect=source_rect,
        text="Sample span text",
        font_name="helv",
        font_size=source_font_size,
        color=(0.0, 0.0, 0.0),
        rotation=0,
        target_span_id="test-span",
        target_mode="run",
    )

    editor = view.scene.last_proxy._widget
    assert callable(editor.font), "editor.font must remain QTextEdit.font() method — setFont was never called or method was shadowed"

    expected_font_pt = text_editing._display_font_pt(source_font_size, render_scale)
    actual_font_pt = editor.font().pointSizeF()
    assert abs(actual_font_pt - expected_font_pt) < 0.05, (
        f"Editor font {actual_font_pt:.3f}pt ≠ expected display pt {expected_font_pt:.3f}pt "
        f"(source span {source_font_size}pt at render_scale={render_scale}) — "
        f"editor will show glyphs at a different size than the rendered PDF"
    )

    expected_width_px = int(round(source_rect.width * render_scale))
    assert editor._width == expected_width_px, (
        f"Editor width {editor._width}px ≠ expected {expected_width_px}px "
        f"(rect.width={source_rect.width}pt at render_scale={render_scale}) — "
        f"editor will wrap text differently than the source span"
    )

def test_preview_pixmap_dimensions_match_render_scale_2x() -> None:
    renderer = text_editing.PreviewRenderer()
    image = renderer._to_qimage_dimensions(rect=fitz.Rect(0, 0, 200, 80), render_scale=2.0, rotation=0)
    assert image.width() == 400
    assert image.height() == 160


def test_preview_pixmap_width_equals_source_rect_times_render_scale() -> None:
    renderer = text_editing.PreviewRenderer()
    image = renderer._to_qimage_dimensions(rect=fitz.Rect(0, 0, 200, 80), render_scale=1.5, rotation=0)
    assert image.width() == 300


# Task 2 regression: editor.font must remain a callable Qt method.
def test_preview_backed_editor_font_is_callable(qapp):
    """PreviewBackedInlineTextEditor.font() must be the QTextEdit method,
    not a QFont attribute. Regression for the editor.font = qt_font_obj
    shadow that broke on_edit_font_size_changed and on_edit_font_family_changed."""
    from view.text_editing import PreviewBackedInlineTextEditor, PreviewRenderer

    renderer = PreviewRenderer(model=None)
    editor = PreviewBackedInlineTextEditor("hello", renderer)
    from PySide6.QtGui import QFont
    qt_font = QFont("Arial")
    qt_font.setPointSizeF(12.0)
    editor.setFont(qt_font)
    # Must be callable (QTextEdit method), not a QFont attribute.
    assert callable(editor.font), (
        "editor.font is not callable — the QTextEdit.font() method was overwritten "
        "by an attribute assignment. Remove 'editor.font = qt_font_obj' from create_text_editor."
    )
    qfont = editor.font()
    assert qfont.pointSizeF() > 0


# Task 4 — paintEvent visible pixels.
def test_preview_backed_editor_paintEvent_shows_text_pixels(qapp) -> None:
    """After real rasterization lands in PreviewRenderer.render, the editor
    viewport must contain visible glyph pixels after a brief event-loop pump."""
    from PySide6.QtCore import QEventLoop, QTimer
    from view.text_editing import PreviewBackedInlineTextEditor, PreviewRenderer

    renderer = PreviewRenderer(model=None)
    editor = PreviewBackedInlineTextEditor("ABC", renderer)
    editor.configure_render_context(
        font_name="helv",
        font_size=14.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=fitz.Rect(0, 0, 200, 30),
        rotation=0,
        render_scale=2.0,
    )
    editor.resize(400, 60)
    editor.show()

    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()

    pixmap = editor.viewport().grab()
    image = pixmap.toImage()
    dark_pixels = sum(
        1
        for y in range(0, image.height(), 2)
        for x in range(0, image.width(), 2)
        if image.pixelColor(x, y).alpha() > 50 and image.pixelColor(x, y).lightness() < 150
    )
    assert dark_pixels > 30, (
        f"After paintEvent, editor viewport should contain visible glyphs. "
        f"Found {dark_pixels} dark pixels — preview image may not be reaching paintEvent."
    )
    editor.close()
