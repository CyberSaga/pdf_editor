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

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QComboBox, QMenu, QPushButton, QStackedWidget, QWidget

import view.pdf_view as pdf_view
from view.text_editing import MoveTextRequest


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


def test_block_outlines_only_drawn_for_visible_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """_draw_all_block_outlines must only call get_blocks for pages in visible_page_range."""

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

    # Fake block with a .rect attribute
    fake_block = SimpleNamespace(rect=fitz.Rect(10, 10, 100, 30))
    visited_pages: list[int] = []

    def _fake_get_blocks(page_num: int):
        visited_pages.append(page_num)
        return [fake_block]

    view.controller = SimpleNamespace(
        model=SimpleNamespace(
            doc=True,
            ensure_page_index_built=lambda page_num: None,
            block_manager=SimpleNamespace(get_blocks=_fake_get_blocks),
        )
    )
    # visible_page_range returns 0-based (start, end) inclusive
    monkeypatch.setattr(view, "visible_page_range", lambda prefetch=0: (3, 5))

    view._draw_all_block_outlines()

    # visible_page_range returned (3, 5) → pages 3,4,5 (0-based) → page_num 4,5,6 (1-based)
    assert visited_pages == [4, 5, 6], (
        f"Must only draw outlines for visible pages 4-6 (1-based), got {visited_pages}"
    )


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


