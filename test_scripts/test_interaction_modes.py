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

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QKeySequence, QShortcut  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402
from model.object_requests import ObjectHitInfo  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeRectItem:
    def __init__(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self.removed = False
        self.z_value = 0

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def setRect(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)

    def setPen(self, _pen) -> None:
        pass

    def setBrush(self, _brush) -> None:
        pass

    def setZValue(self, value: float) -> None:
        self.z_value = value


class _FakeScene:
    def __init__(self) -> None:
        self.items: list[_FakeRectItem] = []
        self.removed: list[_FakeRectItem] = []

    def addRect(self, rect: QRectF, *_args) -> _FakeRectItem:
        item = _FakeRectItem(rect)
        self.items.append(item)
        return item

    def removeItem(self, item: _FakeRectItem) -> None:
        item.removed = True
        self.removed.append(item)


class _FakeEvent:
    def __init__(
        self,
        x: float,
        y: float,
        button=Qt.LeftButton,
        modifiers: Qt.KeyboardModifiers = Qt.NoModifier,
    ) -> None:
        self._pos = QPointF(x, y)
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def position(self):
        return self._pos

    def pos(self):
        return self._pos.toPoint()

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def _make_object_hit(kind: str) -> ObjectHitInfo:
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
    view.current_mode = "browse"
    view.current_page = 0
    view.total_pages = 1
    view.scale = 1.0
    view._render_scale = 1.0
    view.continuous_pages = True
    view.page_y_positions = [0.0]
    view.page_heights = [500.0]
    view.drawing_start = None
    view._drawing_page_idx = None
    view._rect_preview_item = None
    view._fullscreen_active = False
    view.graphics_view = object()
    view.scene = _FakeScene()

    # Object selection state (single-select in current implementation).
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

    # Text selection stub.
    view._text_selection_active = False
    view._text_selection_started = False
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._clear_text_selection = lambda: None
    view._start_text_selection = lambda scene_pos, page_idx: setattr(view, "_text_selection_started", True)

    # Scene/geometry stubs.
    view._event_scene_pos = lambda event: QPointF(float(event.position().x()), float(event.position().y()))
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))

    # Signals used by actions.
    view.sig_mode_changed = _FakeSignal()
    view.sig_add_rect = _FakeSignal()
    view.sig_add_highlight = _FakeSignal()
    view.sig_add_underline = _FakeSignal()
    view.sig_add_strikeout = _FakeSignal()

    # Object hit testing and selection helpers.
    view._point_hits_object_rotate_handle = lambda scene_pos: False
    view._select_object = lambda info: setattr(view, "_selected_object_info", info)
    view._clear_object_selection = lambda: setattr(view, "_selected_object_info", None)

    view.controller = SimpleNamespace(
        get_object_info_at_point=lambda page_num, point: None,
        get_text_info_at_point=lambda page_num, point, allow_fallback=False: None,
        has_unsaved_changes=lambda: False,
    )

    return view


_VIEW_LOCAL_MODES = {"text_edit", "objects"}


def test_valid_modes_parity() -> None:
    """Controller _VALID_MODES must be a subset of View _VALID_MODES,
    and any View-only modes must be explicitly documented as view-local."""
    from controller.pdf_controller import PDFController

    view_modes = pdf_view.PDFView._VALID_MODES
    ctrl_modes = PDFController._VALID_MODES

    assert ctrl_modes <= view_modes, (
        f"Controller has modes unknown to View: {ctrl_modes - view_modes}"
    )

    view_only = view_modes - ctrl_modes
    assert view_only == _VIEW_LOCAL_MODES, (
        f"Undocumented view-local modes: {view_only - _VIEW_LOCAL_MODES}; "
        f"missing expected view-local modes: {_VIEW_LOCAL_MODES - view_only}"
    )


def test_markup_line_mode_has_a_single_combined_toolbar_action(qapp) -> None:
    """Underline and strikeout are combined into one 'markup_line' tool/mode
    with a style toggle in its property card, rather than two separate
    toolbar buttons/modes."""
    view = pdf_view.PDFView()
    try:
        assert "markup_line" in view._VALID_MODES
        assert "underline" not in view._VALID_MODES
        assert "strikeout" not in view._VALID_MODES
        assert view._mode_actions["markup_line"].text() == "標記線"
    finally:
        view.close()
        view.deleteLater()


def test_f1_shortcut_switches_to_browse_mode(qapp) -> None:
    view = pdf_view.PDFView()
    try:
        view.set_mode("rect")
        shortcuts = [
            child
            for child in view.findChildren(QShortcut)
            if child.key().matches(QKeySequence(Qt.Key_F1)) == QKeySequence.ExactMatch
        ]
        assert shortcuts

        shortcuts[0].activated.emit()

        assert view.current_mode == "browse"
    finally:
        view.close()
        view.deleteLater()


def test_rect_inspector_exposes_independent_fill_and_border_controls(qapp) -> None:
    view = pdf_view.PDFView()
    try:
        assert view.rect_stroke_color_btn.text() == "邊框顏色"
        assert view.rect_fill_enabled.isChecked() is False
        assert view.rect_fill_color_btn.text() == "填滿顏色"
        assert view.rect_border_width.minimum() == 0.1
        assert view.rect_border_width.maximum() == 20.0
        assert view.rect_border_width.value() == 1.0
    finally:
        view.close()
        view.deleteLater()


def test_highlight_card_exposes_opacity_control(qapp) -> None:
    """highlight_card previously exposed only a color button with no opacity
    slider — the color dialog itself can't set alpha, so opacity was
    permanently stuck at the QColor(255,255,0,128) construction default."""
    view = pdf_view.PDFView()
    try:
        assert view.highlight_opacity.minimum() == 0
        assert view.highlight_opacity.maximum() == 100
        assert view.highlight_opacity.value() == 50  # matches the initial alpha=128/255

        view.highlight_opacity.setValue(30)
        assert view.highlight_color.alphaF() == pytest.approx(0.3, abs=0.01)
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.parametrize(
    "mode,expected_card_attr",
    [
        ("rect", "rect_card"),
        ("highlight", "highlight_card"),
        ("markup_line", "markup_line_card"),
        ("add_text", "text_card"),
    ],
)
def test_entering_a_property_mode_reopens_a_hidden_right_sidebar(
    qapp, mode: str, expected_card_attr: str
) -> None:
    """The stroke/fill/border/opacity controls exist on rect_card (and the
    equivalent highlight/text cards), but switching QStackedWidget's current
    page is invisible if the whole right sidebar is hidden — e.g. left toggled
    off via Ctrl+Alt+R or auto-collapsed by the compact shell. Entering a mode
    with a dedicated properties card must force the sidebar back open, or the
    controls are unreachable even though they're fully wired."""
    view = pdf_view.PDFView()
    try:
        view.show()
        view.ensure_heavy_panels_initialized()
        view.right_sidebar.hide()
        assert not view.right_sidebar.isVisible()

        view.set_mode(mode)

        assert view.right_sidebar.isVisible()
        assert view.right_stacked_widget.currentWidget() is getattr(view, expected_card_attr)
    finally:
        view.close()
        view.deleteLater()


def test_rect_drag_creates_preview_on_starting_page(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.total_pages = 2
    view.page_y_positions = [0.0, 1000.0]
    view._scene_y_to_page_index = lambda y: 0 if y < 1000 else 1
    view._get_page_scene_rect = lambda page_idx: QRectF(0, page_idx * 1000, 500, 500)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(700, 1400))

    assert view._drawing_page_idx == 0
    assert view._rect_preview_item is not None
    assert view._rect_preview_item.rect() == QRectF(10, 10, 490, 490)


def test_rect_release_emits_from_starting_page_and_clears_preview(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.total_pages = 2
    view.page_y_positions = [0.0, 1000.0]
    view._scene_y_to_page_index = lambda y: 0 if y < 1000 else 1
    view._get_page_scene_rect = lambda page_idx: QRectF(0, page_idx * 1000, 500, 500)
    view.rect_color = SimpleNamespace(getRgbF=lambda: (1.0, 0.0, 0.0, 1.0))

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_move(view, _FakeEvent(700, 1400))
    preview = view._rect_preview_item
    pdf_view.PDFView._mouse_release(view, _FakeEvent(700, 1400))

    assert view.sig_add_rect.calls == [
        (1, fitz.Rect(10, 10, 500, 500), (1.0, 0.0, 0.0, 1.0), None, 1.0)
    ]
    assert view._rect_preview_item is None
    assert view._drawing_page_idx is None
    assert preview.removed is True


def _make_markup_line_view(style: str):
    view = _make_view()
    view.current_mode = "markup_line"
    view.markup_line_style = style
    view.underline_color = SimpleNamespace(getRgbF=lambda: (1.0, 1.0, 0.0, 0.5))
    view.strikeout_color = SimpleNamespace(getRgbF=lambda: (1.0, 0.0, 0.0, 0.5))
    view._markup_line_current_color = lambda: (
        view.underline_color if view.markup_line_style == "underline" else view.strikeout_color
    )
    return view


@pytest.mark.parametrize(
    ("style", "signal_name", "expected_rgba"),
    [
        ("underline", "sig_add_underline", (1.0, 1.0, 0.0, 0.5)),
        ("strikeout", "sig_add_strikeout", (1.0, 0.0, 0.0, 0.5)),
    ],
)
def test_markup_line_drag_emits_style_specific_signal_and_color(
    style: str,
    signal_name: str,
    expected_rgba: tuple,
    monkeypatch,
) -> None:
    """Underline and strikeout share one 'markup_line' mode; the release
    handler must dispatch to the correct signal and use that style's own
    independently-remembered color (e.g. underline yellow, strikeout red)."""
    view = _make_markup_line_view(style)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 20))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(80, 40))

    signal = getattr(view, signal_name)
    assert signal.calls == [(1, fitz.Rect(10, 20, 80, 40), expected_rgba)]
    other_signal = view.sig_add_strikeout if style == "underline" else view.sig_add_underline
    assert other_signal.calls == []


@pytest.mark.parametrize("style", ["underline", "strikeout"])
def test_markup_line_drag_stays_anchored_to_starting_page(style: str, monkeypatch) -> None:
    """rect mode locks page_idx to _drawing_page_idx (set at press time) so a
    release past the page boundary still commits to the page the user started
    drawing on. The markup release handler instead recomputed page_idx from
    the drag rect's vertical CENTER every time, ignoring _drawing_page_idx —
    if the drag drifted toward an adjacent page, the annotation (and the
    show_page() call after it) would land on a different page than the one
    being drawn on, which is what manual testing saw as the page "jumping"."""
    view = _make_markup_line_view(style)
    view.total_pages = 2
    view.page_y_positions = [0.0, 1000.0]
    view._scene_y_to_page_index = lambda y: 0 if y < 1000 else 1
    view._get_page_scene_rect = lambda page_idx: QRectF(0, page_idx * 1000, 500, 500)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **kw: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    # Press on page 0 (y=10); release drifts deep into page 1's y-range (y=2200)
    # so the drag rect's vertical CENTER (≈1105) also falls past the y=1000
    # page boundary — this is exactly the case the center-based recompute got
    # wrong.
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(400, 2200))

    signal_name = "sig_add_underline" if style == "underline" else "sig_add_strikeout"
    signal = getattr(view, signal_name)
    assert len(signal.calls) == 1
    committed_page = signal.calls[0][0]
    assert committed_page == 1, f"expected commit anchored to starting page 1, got page {committed_page}"


@pytest.mark.parametrize("mode", ["highlight", "markup_line"])
def test_markup_drag_accepts_press_and_shows_live_preview(mode: str, monkeypatch) -> None:
    """Markup-mode press previously fell through to the default
    QGraphicsView.mousePressEvent (no event.accept()/return, unlike 'rect'
    mode), letting Qt's native drag/rubber-band handling run underneath —
    manual testing saw this as the page "jumping" mid-drag. Move also had no
    preview at all for these modes (only 'rect' got one), so nothing visible
    tracked the cursor until mouse-up. Both must match 'rect' mode's behavior:
    press is fully consumed and a live rect preview follows the drag."""
    view = _make_view() if mode == "highlight" else _make_markup_line_view("underline")
    view.current_mode = mode
    view.total_pages = 1
    view._scene_y_to_page_index = lambda y: 0
    view._get_page_scene_rect = lambda page_idx: QRectF(0, 0, 500, 500)
    view.highlight_color = SimpleNamespace(getRgbF=lambda: (0.2, 0.3, 0.9, 0.7))

    press_called = SimpleNamespace(count=0)

    def _native_press(*_args, **_kwargs):
        press_called.count += 1

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", _native_press)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)

    press_event = _FakeEvent(10, 10)
    pdf_view.PDFView._mouse_press(view, press_event)

    assert press_event.accepted is True
    assert press_called.count == 0
    assert view._drawing_page_idx == 0

    pdf_view.PDFView._mouse_move(view, _FakeEvent(90, 40))

    assert view._rect_preview_item is not None
    assert view._rect_preview_item.rect() == QRectF(10, 10, 80, 30)


def test_markup_line_style_toggle_preserves_each_styles_own_color(qapp) -> None:
    """Switching between underline/strikeout in the property card must show
    (and let the user edit) each style's own remembered color/opacity —
    selecting strikeout must not show or overwrite the underline color."""
    view = pdf_view.PDFView()
    try:
        assert view.markup_line_style == "underline"
        assert view.underline_color.name() != view.strikeout_color.name()

        original_underline = QColor(view.underline_color)
        view.markup_line_strikeout_radio.setChecked(True)

        assert view.markup_line_style == "strikeout"
        assert view.markup_line_opacity.value() == round(view.strikeout_color.alphaF() * 100)
        # Changing opacity while strikeout is selected must not touch underline's.
        view.markup_line_opacity.setValue(20)
        assert view.strikeout_color.alphaF() == pytest.approx(0.2, abs=0.01)
        assert view.underline_color.name() == original_underline.name()
        assert view.underline_color.alphaF() == pytest.approx(original_underline.alphaF(), abs=0.01)

        view.markup_line_underline_radio.setChecked(True)
        assert view.markup_line_style == "underline"
        assert view.markup_line_opacity.value() == round(view.underline_color.alphaF() * 100)
    finally:
        view.close()
        view.deleteLater()


def test_scene_rebuild_clears_active_rect_drawing_preview() -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.drawing_start = QPointF(10, 10)
    view._drawing_page_idx = 0
    view._rect_preview_item = _FakeRectItem(QRectF(10, 10, 40, 40))
    view.scene = _FakeScene()

    pdf_view.PDFView._cancel_active_drawing_interactions(view)

    assert view.drawing_start is None
    assert view._drawing_page_idx is None
    assert view._rect_preview_item is None


def test_rect_mode_switch_clears_drawing_start_and_preview(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.total_pages = 1
    view._scene_y_to_page_index = lambda y: 0
    view._get_page_scene_rect = lambda page_idx: QRectF(0, 0, 500, 500)
    view._VALID_MODES = pdf_view.PDFView._VALID_MODES
    view.text_editor = None
    view._heavy_panels_initialized = True
    view._clear_object_selection = lambda: None
    view._reset_browse_hover_cursor = lambda: None
    view._clear_hover_highlight = lambda: None
    view._clear_all_block_outlines = lambda: None
    view._outline_redraw_timer = SimpleNamespace(stop=lambda: None)
    view._sync_mode_checked_state = lambda mode: None
    view.graphics_view = SimpleNamespace(
        setDragMode=lambda mode: None,
        viewport=lambda: SimpleNamespace(setCursor=lambda cursor: None),
    )
    view.right_stacked_widget = SimpleNamespace(setCurrentWidget=lambda widget: None)
    view.page_info_card = object()

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    preview = view._rect_preview_item

    pdf_view.PDFView.set_mode(view, "browse")

    assert view.drawing_start is None
    assert view._rect_preview_item is None
    assert view._drawing_page_idx is None
    assert preview.removed is True


def test_rect_ignores_non_left_mouse_buttons(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "rect"
    view.total_pages = 1
    view._scene_y_to_page_index = lambda y: 0
    view._get_page_scene_rect = lambda page_idx: QRectF(0, 0, 500, 500)
    view.rect_color = SimpleNamespace(getRgbF=lambda: (1.0, 0.0, 0.0, 1.0))

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_view.QMessageBox, "question", lambda *args, **kwargs: pdf_view.QMessageBox.No)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10, button=Qt.RightButton))
    pdf_view.PDFView._mouse_release(view, _FakeEvent(100, 100, button=Qt.RightButton))

    assert view.drawing_start is None
    assert view._rect_preview_item is None
    assert view.sig_add_rect.calls == []


def test_objects_mode_blocks_browse_text_selection_start(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    view.controller.get_text_info_at_point = lambda page_num, point, allow_fallback=False: object()

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._text_selection_started is False


def test_browse_mode_does_not_start_object_manipulation(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "browse"
    view.controller.get_object_info_at_point = lambda page_num, point: _make_object_hit("rect")

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info is None


def test_text_edit_mode_does_not_select_rect_or_image(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view.controller.get_object_info_at_point = lambda page_num, point: _make_object_hit("rect")

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info is None


def test_text_edit_mode_allows_textbox_object_select(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view.controller.get_object_info_at_point = lambda page_num, point: _make_object_hit("textbox")

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info is not None
    assert view._selected_object_info.object_kind == "textbox"
