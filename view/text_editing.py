from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from enum import Enum

import fitz
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import QTextEdit

from model.edit_requests import EditTextRequest, MoveTextRequest  # re-exported for view/controller

logger = logging.getLogger(__name__)


def _parse_font_size_str(text: str) -> float | None:
    """Parse combo-box font-size text as float; return None on malformed input."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _format_font_size(size: float) -> str:
    """Render a font size for the combo box: ``9`` / ``9.5`` — no trailing ``.0``."""
    value = float(size)
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:g}"

_LIGATURE_EXPAND = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

_DEFAULT_EDITOR_MASK_COLOR = QColor("#FFFFFF")
_DARK_EDITOR_MASK_COLOR = QColor("#18181B")
_LIGHT_TEXT_LUMA_THRESHOLD = 180.0


def _readable_editor_mask_color(text_rgb: tuple[int, int, int] | None = None) -> QColor:
    """Pick an editor underlay that keeps the text legible: a dark mask under
    light text, the default light mask otherwise. Derived purely from the text
    color (no page sampling) so the underlay is deterministic and never bleeds
    the old glyphs through."""
    if text_rgb is not None:
        r, g, b = [max(0, min(255, int(value))) for value in text_rgb]
        luma = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
        if luma >= _LIGHT_TEXT_LUMA_THRESHOLD:
            return QColor(_DARK_EDITOR_MASK_COLOR)
    return QColor(_DEFAULT_EDITOR_MASK_COLOR)


class TextEditUIConstants:
    MIN_EDITOR_WIDTH_PX = 80
    MIN_EDITOR_HEIGHT_PX = 40
    FOCUS_RESTORE_DELAY_MS = 0
    MASK_SAMPLE_INSET_RATIO = 0.15
    MASK_SAMPLE_INSET_MAX_PX = 6.0
    # QTextEdit has a few px of internal frame/viewport margin; pad so measured
    # natural content height doesn't clip the last line visually.
    EDITOR_CONTENT_PADDING_PX = 8
    MAX_EDITOR_VIEWPORT_HEIGHT_RATIO = 0.6


class TextEditGeometryConstants:
    POSITION_CHANGE_TOLERANCE_PT = 0.5
    DRAG_START_DISTANCE_PX = 3.0


class TextEditFinalizeReason(str, Enum):
    APPLY = "apply"
    CLICK_AWAY = "click_away"
    CANCEL_BUTTON = "cancel_button"
    ESCAPE = "escape"
    SAVE_SHORTCUT = "save_shortcut"
    MODE_SWITCH = "mode_switch"
    FOCUS_OUTSIDE = "focus_outside"
    CLOSE_DOCUMENT = "close_document"


class TextEditOutcome(str, Enum):
    DISCARDED = "discarded"
    NO_OP = "no_op"
    COMMITTED = "committed"


class TextEditDragState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    ACTIVE = "active"


@dataclass(frozen=True)
class TextEditDelta:
    text_changed: bool
    style_changed: bool
    position_changed: bool
    page_changed: bool

    @property
    def any_change(self) -> bool:
        return self.text_changed or self.style_changed or self.position_changed or self.page_changed


@dataclass(frozen=True)
class TextEditFinalizeResult:
    reason: TextEditFinalizeReason
    outcome: TextEditOutcome
    intent: str
    edit_page: int
    origin_page: int
    delta: TextEditDelta


@dataclass(frozen=True)
class TextEditSession:
    original_rect: fitz.Rect | None
    current_rect: fitz.Rect | None
    current_font: str
    initial_font: str
    original_color: tuple
    current_size: float
    initial_size: float
    edit_page: int
    origin_page: int
    intent: str
    target_span_id: str | None
    target_mode: str
    original_text: str | None


class _EditorShortcutForwarder(QObject):
    """Forward common window shortcuts while the embedded editor has focus."""

    def __init__(self, view) -> None:
        super().__init__(view if isinstance(view, QObject) else None)
        self._view = view

    def _trigger(self, action_name: str, fallback_name: str | None = None) -> bool:
        action = getattr(self._view, action_name, None)
        if action is not None and hasattr(action, "trigger"):
            action.trigger()
            return True
        if fallback_name:
            fallback = getattr(self._view, fallback_name, None)
            if callable(fallback):
                fallback()
                return True
        return False

    def _editor_widget(self):
        editor = getattr(self._view, "text_editor", None)
        if editor is None or not hasattr(editor, "widget"):
            return None
        return editor.widget()

    def _handle_editor_undo(self) -> bool:
        widget = self._editor_widget()
        if widget is None:
            return True
        document = widget.document() if hasattr(widget, "document") else None
        if document is not None and document.isUndoAvailable():
            widget.undo()
        return True

    def _handle_editor_redo(self) -> bool:
        widget = self._editor_widget()
        if widget is None:
            return True
        document = widget.document() if hasattr(widget, "document") else None
        if document is not None and document.isRedoAvailable():
            widget.redo()
        return True

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return False
        if event.key() == Qt.Key_Escape:
            handler = getattr(self._view, "_handle_escape", None)
            return bool(handler()) if callable(handler) else False
        modifiers = event.modifiers()
        if not (modifiers & Qt.ControlModifier):
            return False
        if event.key() == Qt.Key_S and (modifiers & Qt.ShiftModifier):
            return self._trigger("_action_save_as", "_save_as")
        if event.key() == Qt.Key_S and not (modifiers & Qt.ShiftModifier):
            return self._trigger("_action_save", "_save")
        if event.key() == Qt.Key_Z and not (modifiers & Qt.ShiftModifier):
            return self._handle_editor_undo()
        if event.key() == Qt.Key_Y:
            return self._handle_editor_redo()
        if event.key() == Qt.Key_Z and (modifiers & Qt.ShiftModifier):
            return self._handle_editor_redo()
        return False


class InlineTextEditor(QTextEdit):
    focus_out_requested = Signal()

    def keyPressEvent(self, event) -> None:
        # For single-paragraph inline edits, treat End as "move to document end"
        # instead of visual-line end so keyboard workflows stay deterministic.
        if event.key() == Qt.Key_End and self.document().blockCount() <= 1:
            cursor = self.textCursor()
            move_mode = (
                QTextCursor.KeepAnchor
                if event.modifiers() & Qt.ShiftModifier
                else QTextCursor.MoveAnchor
            )
            cursor.movePosition(QTextCursor.End, move_mode)
            self.setTextCursor(cursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.focus_out_requested.emit()
@dataclass(frozen=True)
class ViewportAnchor:
    page_idx: int
    horizontal_value: int
    vertical_value: int


def _normalize_for_edit_compare(text: str) -> str:
    if not text:
        return ""
    for ligature, expanded in _LIGATURE_EXPAND.items():
        text = text.replace(ligature, expanded)
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).strip()


def _average_image_rect_color(image, rect: QRect) -> QColor:
    bounded = rect.intersected(image.rect())
    if bounded.isEmpty():
        return QColor(_DEFAULT_EDITOR_MASK_COLOR)
    total_r = 0
    total_g = 0
    total_b = 0
    count = 0
    for y in range(bounded.top(), bounded.bottom() + 1):
        for x in range(bounded.left(), bounded.right() + 1):
            color = image.pixelColor(x, y)
            total_r += color.red()
            total_g += color.green()
            total_b += color.blue()
            count += 1
    if count <= 0:
        return QColor(_DEFAULT_EDITOR_MASK_COLOR)
    return QColor(total_r // count, total_g // count, total_b // count)


def _widget_logical_dpi() -> float:
    """Logical DPI Qt uses for font rendering; 96 on typical Windows."""
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is not None:
        dpi = float(screen.logicalDotsPerInch())
        if dpi > 0:
            return dpi
    return 96.0


def _display_font_pt(pdf_font_size: float, render_scale: float) -> float:
    """Qt point size that makes the editor's glyphs match the rendered PDF's
    glyphs in physical pixels.

    PyMuPDF rasterizes at ``72 × render_scale`` DPI, so a ``S`` pt glyph is
    ``S × render_scale`` physical px tall. Qt renders ``setPointSizeF(P)`` at
    ``P × logical_dpi/72`` px. Equating gives
    ``P = S × render_scale × 72/logical_dpi`` — the only point size at which
    "what you see while editing" equals "what you get after commit".
    """
    return float(pdf_font_size) * float(render_scale) * (72.0 / _widget_logical_dpi())


def _measure_text_content_height_px(
    *,
    text: str,
    qt_font_family: str,
    display_font_pt: float,
    wrap_width_px: int,
) -> int:
    """Natural laid-out height of ``text`` at the given (already display-scaled)
    font and wrap width. Used for paragraph-mode editors whose region box is
    larger than the actual ink."""
    import math

    measure_font = QFont(qt_font_family)
    measure_font.setPointSizeF(float(display_font_pt))
    doc = QTextDocument()
    doc.setDefaultFont(measure_font)
    doc.setTextWidth(float(max(wrap_width_px, 1)))
    doc.setPlainText(text or "")
    return int(math.ceil(doc.size().height()))


def _compute_editor_proxy_layout(
    *,
    scaled_rect: fitz.Rect,
    scaled_width: int,
    page_y_offset: float,
    rotation: int,
    content_height_px: int | None = None,
) -> tuple[int, int, float, float, int]:
    normalized_rotation = int(rotation) % 360
    width_px = max(int(round(scaled_width)), TextEditUIConstants.MIN_EDITOR_WIDTH_PX)
    raw_height = (
        content_height_px
        if content_height_px is not None
        else int(round(scaled_rect.height))
    )
    # First-frame height tracks the PDF span bbox / measured content height.
    # A large fixed minimum (e.g. 40px) is exactly what produced the visible
    # click-to-edit size jump, so it is deliberately NOT applied here.
    height_px = max(int(round(raw_height)), 1)
    pos_x = float(scaled_rect.x0)
    pos_y = float(page_y_offset + scaled_rect.y0)

    if normalized_rotation == 180:
        pos_x += width_px
        pos_y += height_px

    return width_px, height_px, pos_x, pos_y, normalized_rotation


def _viewport_editor_height_cap_px(view) -> int | None:
    """Cap the editor height to a fraction of the viewport so a huge paragraph
    box never fills the screen. Returns None when no viewport is available."""
    graphics_view = getattr(view, "graphics_view", None)
    if graphics_view is None or not hasattr(graphics_view, "viewport"):
        return None
    viewport = graphics_view.viewport()
    if viewport is None or not hasattr(viewport, "height"):
        return None
    try:
        viewport_height = int(viewport.height())
    except (TypeError, ValueError):
        return None
    if viewport_height <= 0:
        return None
    return max(
        TextEditUIConstants.MIN_EDITOR_HEIGHT_PX,
        int(viewport_height * TextEditUIConstants.MAX_EDITOR_VIEWPORT_HEIGHT_RATIO),
    )


def _alias_font_family(font_name: str) -> str:
    """Normalize PDF font hints to a CSS family MuPDF resolves consistently.

    ``helv`` / ``helvetica`` (and bold variants without an explicit family)
    map to ``Helvetica`` so the preview's fallback CSS resolves to the same
    base-14 face the commit path and a direct ``insert_htmlbox`` would use —
    a prerequisite for pixel-height parity.
    """
    family = str(font_name or "Helvetica").strip()
    low = family.lower()
    if low in {"helv", "helvetica", ""}:
        return "Helvetica"
    if "bold" in low and "helvetica" not in low:
        return "Helvetica"
    return family


class PreviewRenderer:
    """Rasterizes proposed edit content through the *same* MuPDF
    ``insert_htmlbox`` engine the commit path uses, so the glyphs an opened
    editor shows are pixel-identical to what lands in the PDF.

    A model may be supplied so the preview borrows the model's exact CSS /
    HTML builders; with ``model=None`` (unit isolation) a minimal but
    metrics-equivalent CSS/HTML is used instead.
    """

    def __init__(self, model=None) -> None:
        self._model = model
        self._cache_key: tuple | None = None
        self._cache_image: QImage | None = None

    @staticmethod
    def _pixel_dims(rect: fitz.Rect, render_scale: float, rotation: int) -> tuple[int, int]:
        width = max(1, int(round(float(rect.width) * float(render_scale))))
        height = max(1, int(round(float(rect.height) * float(render_scale))))
        if int(rotation) % 360 in (90, 270):
            width, height = height, width
        return width, height

    def _to_qimage_dimensions(self, *, rect: fitz.Rect, render_scale: float, rotation: int) -> QImage:
        width, height = self._pixel_dims(rect, render_scale, rotation)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        return image

    def render(
        self,
        *,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple[float, float, float],
        member_spans: list[object] | None,
        rect_pt: fitz.Rect,
        rotation: int,
        render_scale: float,
        line_height: float = 0.0,
    ) -> QImage:
        key = (
            text,
            font_name,
            float(font_size),
            tuple(float(c) for c in color),
            int(rotation),
            float(render_scale),
            float(line_height),
            int(round(float(rect_pt.width) * 100)),
            int(round(float(rect_pt.height) * 100)),
        )
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        normalized_rotation = int(rotation) % 360
        if normalized_rotation in (90, 270):
            page_w_pt = max(float(rect_pt.height), 1.0)
            page_h_pt = max(float(rect_pt.width), 1.0)
        else:
            page_w_pt = max(float(rect_pt.width), 1.0)
            page_h_pt = max(float(rect_pt.height), 1.0)

        temp_doc = fitz.open()
        try:
            temp_page = temp_doc.new_page(width=page_w_pt, height=page_h_pt)

            if self._model is not None and hasattr(self._model, "_build_insert_css"):
                # Borrow the commit path's exact CSS/HTML so preview and
                # committed pixels come from one engine configuration.
                css = self._model._build_insert_css(
                    size=float(font_size),
                    color=tuple(float(c) for c in color),
                    font_hint=str(font_name),
                    line_height=float(line_height),
                )
                html = self._model._convert_text_to_html(
                    text=text or "",
                    font_size=float(font_size),
                    color=tuple(float(c) for c in color),
                    latin_font=str(font_name),
                )
            else:
                import html as _html_mod

                r, g, b = (int(c * 255) for c in color)
                family = _alias_font_family(font_name)
                lh_css = f" line-height: {line_height}pt;" if line_height > 0 else ""
                css = (
                    f"span {{ font-family: {family}; font-size: {font_size}pt;{lh_css} "
                    f"color: rgb({r},{g},{b}); white-space: pre-wrap; }}"
                )
                html = f"<span>{_html_mod.escape(text or '')}</span>"

            target_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            try:
                temp_page.insert_htmlbox(
                    target_rect, html, css=css, rotate=normalized_rotation, scale_low=1
                )
            except TypeError:
                temp_page.insert_htmlbox(target_rect, html, css=css, scale_low=1)

            pixmap = temp_page.get_pixmap(
                matrix=fitz.Matrix(float(render_scale), float(render_scale)),
                alpha=True,
            )
            fmt = QImage.Format_RGBA8888 if pixmap.alpha else QImage.Format_RGB888
            image = QImage(
                pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, fmt
            ).copy()
        finally:
            temp_doc.close()

        self._cache_key = key
        self._cache_image = image
        return image


class PreviewBackedInlineTextEditor(InlineTextEditor):
    """Inline editor that paints a MuPDF-rasterized preview instead of Qt's
    native glyphs, so the on-screen text is pixel-faithful to the committed
    PDF. While the text is unchanged it paints a *frozen* capture of the real
    PDF span (the only thing that is truly pixel-perfect); once mutated it
    paints the live CSS preview from the shared engine.
    """

    # Treat an effectively-transparent mutated preview as invalid and fall
    # back to native QTextEdit painting so typed text stays readable.
    _MUTATED_PREVIEW_MIN_NONTRANSPARENT_COVERAGE = 0.0001
    _VISIBLE_ALPHA_THRESHOLD = 8

    def __init__(self, text: str, renderer: PreviewRenderer | None = None, **legacy_kwargs) -> None:
        super().__init__()
        self.setFrameStyle(0)
        self.setViewportMargins(0, 0, 0, 0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCursorWidth(0)
        self._cursor_revealed = False
        try:
            self.document().setDocumentMargin(0.0)
        except Exception:
            logger.debug("document margin reset skipped")
        self._renderer = renderer or PreviewRenderer(model=legacy_kwargs.get("model"))
        self._preview_image: QImage | None = None
        self._frozen_first_frame_image: QImage | None = None
        self._initial_text = text or ""
        # Cached (toPlainText() == _initial_text); refreshed only on
        # textChanged. paintEvent reads it but must never recompute it (it
        # fires on cursor blink/scroll and would walk the whole document).
        self._text_matches_initial: bool = True
        self._text_is_nonempty: bool = bool(self._initial_text)
        self._preview_nontransparent_coverage: float = 0.0
        self._mutated_preview_is_valid: bool = True
        self._legacy_standalone_mode = bool(legacy_kwargs) and renderer is None
        self._render_args: dict[str, object] = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._regenerate_preview)
        self.setPlainText(text)
        self.textChanged.connect(self._schedule_preview)
        if legacy_kwargs:
            rgb = legacy_kwargs.get("color", (0.0, 0.0, 0.0))
            text_rgb = tuple(max(0, min(255, int(float(c) * 255))) for c in rgb)
            legacy_kwargs["text_rgb"] = text_rgb
            legacy_kwargs.setdefault("legacy_bg_rgb", (70, 70, 70))
            initial_frame_image = legacy_kwargs.pop("initial_frame_image", None)
            self.configure_render_context(**legacy_kwargs)
            if isinstance(initial_frame_image, QImage) and not initial_frame_image.isNull():
                self.setFixedSize(initial_frame_image.width(), initial_frame_image.height())
                self.freeze_first_frame(initial_frame_image)
            if self._preview_image is not None and not self._legacy_standalone_mode:
                self.freeze_first_frame(self._preview_image)

    def keyPressEvent(self, event) -> None:
        if not self._cursor_revealed:
            self.setCursorWidth(1)
            self._cursor_revealed = True
        super().keyPressEvent(event)

    def configure_render_context(self, **kwargs) -> None:
        self._render_args.update(kwargs)
        rect_val = self._render_args.get("rect_pt")
        scale_val = float(self._render_args.get("render_scale", 1.0) or 1.0)
        if rect_val is not None:
            rect = fitz.Rect(rect_val)
            width_px = max(1, int(round(float(rect.width) * scale_val)))
            height_px = max(1, int(round(float(rect.height) * scale_val)))
            rotation = int(self._render_args.get("rotation", 0)) % 360
            if rotation in (90, 270):
                width_px, height_px = height_px, width_px
            # create_text_editor() owns the no-jump geometry; only fall back to
            # rect-derived sizing when no explicit frame was set (or legacy
            # standalone mode where rect sizing is the sole input).
            if self._legacy_standalone_mode or self.width() <= 1 or self.height() <= 1:
                self.setFixedSize(width_px, height_px)
        self._regenerate_preview()

    def _schedule_preview(self) -> None:
        # CRITICAL — do NOT clear _frozen_first_frame_image here. It is the
        # real MuPDF pixmap of the span as the user saw it pre-click. Releasing
        # it on first mutation makes type-then-delete a one-way trip: the
        # editor never returns to PDF-faithful appearance even when content is
        # byte-identical to the original, leaving a permanent restore delta.
        # Gates: test_click_to_edit_qtest_integration,
        #        test_click_to_edit_then_insert_then_delete_stays_stable.
        #
        # textChanged is the ONLY event that can flip these flags; refresh them
        # here so paintEvent can read cached values instead of walking the
        # QTextDocument 60+ times/second.
        self._text_matches_initial = self.toPlainText() == self._initial_text
        self._text_is_nonempty = bool(self.toPlainText())
        self._debounce.start()
        self.viewport().update()

    def _compute_nontransparent_coverage(self, image: QImage | None) -> float:
        if (
            image is None
            or image.isNull()
            or self._frozen_first_frame_image is None
        ):
            return 0.0
        width = int(image.width())
        height = int(image.height())
        if width <= 0 or height <= 0:
            return 0.0
        if image.format() != QImage.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format_RGBA8888)
        threshold = int(self._VISIBLE_ALPHA_THRESHOLD)
        stride = int(image.bytesPerLine())
        buf = bytes(image.constBits())
        visible = 0
        for y in range(height):
            row_start = y * stride
            row_alpha = buf[row_start + 3 : row_start + 4 * width : 4]
            visible += sum(1 for a in row_alpha if a > threshold)
        return visible / float(width * height)

    def _regenerate_preview(self) -> None:
        if not self._render_args:
            return
        text = self.toPlainText()
        self._text_is_nonempty = bool(text)
        self._preview_image = self._renderer.render(
            text=text,
            font_name=str(self._render_args.get("font_name", "helv")),
            font_size=float(self._render_args.get("font_size", 12.0)),
            color=tuple(self._render_args.get("color", (0.0, 0.0, 0.0))),
            member_spans=self._render_args.get("member_spans"),
            rect_pt=fitz.Rect(self._render_args.get("rect_pt")),
            rotation=int(self._render_args.get("rotation", 0)),
            render_scale=float(self._render_args.get("render_scale", 1.0)),
            line_height=float(self._render_args.get("line_height", 0.0)),
        )
        self._preview_nontransparent_coverage = self._compute_nontransparent_coverage(
            self._preview_image
        )
        self._mutated_preview_is_valid = (
            not self._text_is_nonempty
            or self._preview_nontransparent_coverage
            > self._MUTATED_PREVIEW_MIN_NONTRANSPARENT_COVERAGE
        )
        self.viewport().update()

    def paintEvent(self, event) -> None:
        # CRITICAL — visual fidelity contract. While text == initial (incl.
        # after a type-then-delete round-trip) paint the frozen MuPDF capture;
        # CSS preview never pixel-matches MuPDF hinting, so using it for
        # unchanged text introduces a permanent delta. _text_matches_initial is
        # cached (see _schedule_preview); never recompute it per paint.
        # Gates: test_click_to_edit_qtest_integration,
        #        test_click_to_edit_then_insert_then_delete_stays_stable.
        if self._frozen_first_frame_image is not None and self._text_matches_initial:
            painter = QPainter(self.viewport())
            painter.drawImage(0, 0, self._frozen_first_frame_image)
            painter.end()
            return
        if (
            self._preview_image is not None
            and self._text_is_nonempty
            and not self._text_matches_initial
            and not self._mutated_preview_is_valid
        ):
            # Fail-safe: mutated preview rendered effectively transparent. Seed
            # with the frozen capture, then native-paint typed text with the
            # background fill suppressed so it stays readable.
            if self._frozen_first_frame_image is not None:
                frozen_painter = QPainter(self.viewport())
                frozen_painter.drawImage(0, 0, self._frozen_first_frame_image)
                frozen_painter.end()
            viewport = self.viewport()
            old_auto_fill = viewport.autoFillBackground()
            viewport.setAutoFillBackground(False)
            super().paintEvent(event)
            viewport.setAutoFillBackground(old_auto_fill)
            return
        painter = QPainter(self.viewport())
        if self._preview_image is not None:
            if self._legacy_standalone_mode:
                bg_rgb = self._render_args.get("legacy_bg_rgb", (184, 184, 184))
                painter.fillRect(self.viewport().rect(), QColor(*bg_rgb))
            painter.drawImage(0, 0, self._preview_image)
        elif self._frozen_first_frame_image is not None:
            # Text differs but debounce is still in flight: paint the frozen
            # frame so the editor never flashes blank during the transition.
            painter.drawImage(0, 0, self._frozen_first_frame_image)
        else:
            painter.end()
            super().paintEvent(event)
            return
        painter.end()

    def freeze_first_frame(self, image: QImage | None) -> None:
        self._frozen_first_frame_image = image.copy() if image is not None else None
        self.viewport().update()


class TextEditManager:
    def __init__(self, view) -> None:
        self._view = view
        self._preview_renderer: PreviewRenderer | None = None

    def _clear_text_editor_mask_item(self) -> None:
        mask_item = getattr(self._view, "_text_editor_mask_item", None)
        if mask_item is None:
            return
        try:
            if mask_item.scene():
                self._view.scene.removeItem(mask_item)
        except Exception:
            logger.debug("text editor mask removal skipped")
        self._view._text_editor_mask_item = None

    def _sync_text_editor_mask_item(self, scene_rect: QRectF, mask_color: QColor) -> None:
        if scene_rect.isEmpty() or not hasattr(self._view, "scene"):
            self._clear_text_editor_mask_item()
            return
        if not hasattr(self._view.scene, "addRect"):
            return
        brush = QBrush(mask_color)
        pen = QPen(Qt.NoPen)
        mask_item = getattr(self._view, "_text_editor_mask_item", None)
        if mask_item is None:
            mask_item = self._view.scene.addRect(scene_rect, pen, brush)
            self._view._text_editor_mask_item = mask_item
        else:
            if hasattr(mask_item, "setRect"):
                mask_item.setRect(scene_rect)
            if hasattr(mask_item, "setBrush"):
                mask_item.setBrush(brush)
            if hasattr(mask_item, "setPen"):
                mask_item.setPen(pen)
        if hasattr(mask_item, "setZValue"):
            mask_item.setZValue(11)
        editor_proxy = getattr(self._view, "text_editor", None)
        if editor_proxy is not None and hasattr(editor_proxy, "setZValue"):
            editor_proxy.setZValue(12)

    def current_text_editor_scene_rect(self) -> QRectF | None:
        editor = getattr(self._view, "text_editor", None)
        if not editor or not editor.widget():
            return None
        if hasattr(editor, "sceneBoundingRect"):
            return editor.sceneBoundingRect()
        pos = editor.pos() if hasattr(editor, "pos") else QPointF(0, 0)
        widget = editor.widget()
        return QRectF(pos.x(), pos.y(), float(widget.width()), float(widget.height()))

    def refresh_text_editor_mask_color(self) -> None:
        self._clear_text_editor_mask_item()
        editor_proxy = getattr(self._view, "text_editor", None)
        if not editor_proxy or not editor_proxy.widget():
            return
        scene_rect = self.current_text_editor_scene_rect()
        if scene_rect is None:
            return
        editor = editor_proxy.widget()
        text_rgb = editor.property("text_rgb") or (0, 0, 0)
        # Underlay derived from the text color only — no page sampling. The
        # frozen-frame preview already carries the true background; sampling
        # the live scene here would re-introduce the old glyphs under the
        # editor.
        mask_color = _readable_editor_mask_color(text_rgb)
        self._sync_text_editor_mask_item(scene_rect, mask_color)
        editor.setStyleSheet(self._view._build_text_editor_stylesheet(text_rgb, mask_color))
        editor.setProperty("mask_rgb", (mask_color.red(), mask_color.green(), mask_color.blue()))

    def create_text_editor(
        self,
        rect: fitz.Rect,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple = (0, 0, 0),
        rotation: int = 0,
        target_span_id: str | None = None,
        target_mode: str = "run",
        editor_intent: str = "edit_existing",
        cluster_span_ids: list[str] | None = None,
    ) -> None:
        view = self._view
        if view.text_editor:
            view._finalize_text_edit()

        page_idx = getattr(view, "_editing_page_idx", view.current_page)
        rs = view._render_scale if view._render_scale > 0 else 1.0
        # edit_existing: wrap width is the exact source bbox width (no Qt
        # margin) so the editor wraps where the PDF wraps. add_new has no
        # source span, so fall back to the model's render-width helper.
        if editor_intent == "edit_existing":
            scaled_width = int(round(rect.width * rs))
        else:
            render_width_pt = view.controller.model.get_render_width_for_edit(page_idx + 1, rect)
            scaled_width = int(render_width_pt * rs)
        scaled_rect = rect * rs

        view.editing_rect = fitz.Rect(rect)
        view._editing_original_rect = fitz.Rect(rect)
        view._editing_origin_page_idx = page_idx
        y0 = view.page_y_positions[page_idx] if (view.continuous_pages and page_idx < len(view.page_y_positions)) else 0
        display_font_pt = _display_font_pt(font_size, rs)
        qt_font_family = view._pdf_font_to_qt(font_name)
        # Run-level edits: first frame matches the clicked span bbox exactly.
        # Paragraph edits can target an oversized region box, so use the real
        # wrapped-text layout height instead.
        content_height_px = max(int(round(scaled_rect.height)), 1)
        if target_mode == "paragraph":
            measured_height_px = _measure_text_content_height_px(
                text=text,
                qt_font_family=qt_font_family,
                display_font_pt=display_font_pt,
                wrap_width_px=max(int(round(scaled_width)), 1),
            )
            content_height_px = max(measured_height_px, 1)
        if rotation not in (90, 270):
            height_cap_px = _viewport_editor_height_cap_px(view)
            if height_cap_px is not None:
                content_height_px = min(content_height_px, height_cap_px)
        editor_width_px, editor_height_px, pos_x, pos_y, normalized_rotation = _compute_editor_proxy_layout(
            scaled_rect=scaled_rect,
            scaled_width=scaled_width,
            page_y_offset=y0,
            rotation=rotation,
            content_height_px=content_height_px,
        )
        if normalized_rotation == 90:
            editor_width_px = max(int(round(scaled_rect.height)), 1)
            editor_height_px = max(int(round(scaled_rect.width)), 1)
            pos_x = float(scaled_rect.x1)
            pos_y = float(y0 + scaled_rect.y0)
        elif normalized_rotation == 270:
            editor_width_px = max(int(round(scaled_rect.height)), 1)
            editor_height_px = max(int(round(scaled_rect.width)), 1)
            pos_x = float(scaled_rect.x0)
            pos_y = float(y0 + scaled_rect.y1)

        initial_frame = None
        graphics_view = getattr(view, "graphics_view", None)
        if graphics_view is not None and hasattr(graphics_view, "viewport"):
            try:
                # ──────────────────────────────────────────────────────────
                # CRITICAL — frozen-frame capture point.
                #
                # rotation 0/180: the editor's pre-rotation rect IS the PDF
                # bbox; grab it directly.
                #
                # rotation 90/270: the editor's local paint space is SWAPPED
                # and the scene rotates the proxy at display time. Grab the
                # axis-aligned PDF bbox and COUNTER-rotate the bytes so that,
                # after the proxy's setRotation, the widget's local paint
                # lands back on the correct PDF pixels. Without this the grab
                # samples the empty page margin and the editor opens blank.
                # Gate: test_click_to_edit_qtest_integration[
                #         test-vertical-texts.pdf-vertical].
                # ──────────────────────────────────────────────────────────
                if normalized_rotation in (90, 270):
                    bbox_tl = graphics_view.mapFromScene(QPointF(
                        float(scaled_rect.x0),
                        float(y0 + scaled_rect.y0),
                    ))
                    bbox_grab = QRect(
                        int(bbox_tl.x()),
                        int(bbox_tl.y()),
                        max(1, int(round(scaled_rect.width))),
                        max(1, int(round(scaled_rect.height))),
                    )
                    raw_img = (
                        graphics_view.viewport().grab(bbox_grab)
                        .toImage()
                        .convertToFormat(QImage.Format_RGBA8888)
                    )
                    from PySide6.QtGui import QTransform

                    counter = -90.0 if normalized_rotation == 90 else 90.0
                    initial_frame = raw_img.transformed(QTransform().rotate(counter))
                else:
                    vp_top_left = graphics_view.mapFromScene(QPointF(float(pos_x), float(pos_y)))
                    grab_rect = QRect(
                        int(vp_top_left.x()),
                        int(vp_top_left.y()),
                        max(1, int(editor_width_px)),
                        max(1, int(editor_height_px)),
                    )
                    initial_frame = (
                        graphics_view.viewport().grab(grab_rect)
                        .toImage()
                        .convertToFormat(QImage.Format_RGBA8888)
                    )
            except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
                logger.debug("frozen-frame grab failed: %s", exc)
                initial_frame = None

        if self._preview_renderer is None:
            model = getattr(getattr(view, "controller", None), "model", None)
            self._preview_renderer = PreviewRenderer(model=model)
        editor = PreviewBackedInlineTextEditor(text, self._preview_renderer)
        editor.setProperty("original_text", text)
        view._editing_rotation = normalized_rotation
        view.editing_target_span_id = target_span_id
        view.editing_target_mode = target_mode if target_mode in ("run", "paragraph") else "run"
        view.editing_intent = editor_intent if editor_intent in ("edit_existing", "add_new") else "edit_existing"

        qt_font_obj = QFont(qt_font_family)
        qt_font_obj.setPointSizeF(display_font_pt)
        editor.setFont(qt_font_obj)

        r, g, b = [int(c * 255) for c in color]
        text_rgb = (r, g, b)
        mask_color = _readable_editor_mask_color(text_rgb)
        editor.setProperty("text_rgb", text_rgb)
        editor.setAutoFillBackground(False)
        editor.viewport().setAutoFillBackground(False)
        editor.setStyleSheet(view._build_text_editor_stylesheet(text_rgb, mask_color))

        editor.setFixedWidth(editor_width_px)
        setattr(editor, "_width", editor_width_px)
        editor.setFixedHeight(editor_height_px)
        setattr(editor, "_height", editor_height_px)
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapAnywhere)

        # Derive preview line_height from the cluster spans so the editor's CSS
        # leading matches the commit path's leading exactly.
        line_ht_for_preview = 0.0
        member_spans_for_preview = None
        if cluster_span_ids:
            try:
                model_ref = getattr(getattr(view, "controller", None), "model", None)
                if model_ref is not None:
                    bm = model_ref.block_manager
                    spans = [bm.find_span_by_id(page_idx, sid) for sid in cluster_span_ids]
                    spans = [s for s in spans if s is not None]
                    if spans:
                        member_spans_for_preview = spans
                        ordered = sorted(spans, key=lambda s: float(s.bbox.y0))
                        if len(ordered) >= 2:
                            advances = [
                                abs(float(ordered[i + 1].bbox.y0) - float(ordered[i].bbox.y0))
                                for i in range(len(ordered) - 1)
                                if abs(float(ordered[i + 1].bbox.y0) - float(ordered[i].bbox.y0)) > 0.5
                            ]
                            if advances:
                                line_ht_for_preview = sorted(advances)[len(advances) // 2]
                        if line_ht_for_preview <= 0:
                            heights = [float(s.bbox.height) for s in spans if s.bbox.height > 0]
                            if heights:
                                line_ht_for_preview = max(heights)
            except Exception:
                line_ht_for_preview = 0.0

        editor.configure_render_context(
            font_name=font_name,
            font_size=float(font_size),
            color=tuple(float(c) for c in color),
            member_spans=member_spans_for_preview,
            rect_pt=fitz.Rect(rect),
            rotation=normalized_rotation,
            render_scale=float(rs),
            line_height=line_ht_for_preview,
        )

        size_str = _format_font_size(font_size)
        if view.text_size.findText(size_str) == -1:
            view.text_size.addItem(size_str)
            items = sorted(
                (view.text_size.itemText(i) for i in range(view.text_size.count())),
                key=lambda item: _parse_font_size_str(item) or 0.0,
            )
            view.text_size.clear()
            view.text_size.addItems(items)
        view.text_size.setCurrentText(size_str)
        normalized_font = view._qt_font_to_pdf(font_name)
        view._set_text_font_by_pdf(normalized_font)
        view._editing_initial_font_name = normalized_font
        view._editing_initial_size = float(font_size)
        view._editing_current_pdf_size = float(font_size)
        if not hasattr(view, "editing_font_name"):
            view.editing_font_name = normalized_font
        if not getattr(view, "_edit_font_size_connected", False):
            view.text_size.currentTextChanged.connect(view._on_edit_font_size_changed)
            view._edit_font_size_connected = True
        if not getattr(view, "_edit_font_family_connected", False):
            view.text_font.currentIndexChanged.connect(view._on_edit_font_family_changed)
            view._edit_font_family_connected = True

        view.text_editor = view.scene.addWidget(editor)
        view.text_editor.setPos(round(pos_x), round(pos_y))
        if hasattr(view.text_editor, "setTransformOriginPoint"):
            view.text_editor.setTransformOriginPoint(0.0, 0.0)
        if hasattr(view.text_editor, "setRotation"):
            view.text_editor.setRotation(float(normalized_rotation))
        if initial_frame is not None:
            editor.freeze_first_frame(initial_frame)
        self.refresh_text_editor_mask_color()
        view._editor_shortcut_forwarder = _EditorShortcutForwarder(view)
        if isinstance(view._editor_shortcut_forwarder, QObject):
            editor.installEventFilter(view._editor_shortcut_forwarder)
        editor.focus_out_requested.connect(view._schedule_finalize_on_focus_change)
        document = editor.document() if hasattr(editor, "document") else None
        refresh_undo_redo = getattr(view, "_refresh_undo_redo_action_state", None)
        if document is not None and callable(refresh_undo_redo):
            try:
                document.undoAvailable.connect(refresh_undo_redo)
                document.redoAvailable.connect(refresh_undo_redo)
            except (TypeError, RuntimeError):
                logger.debug("editor undo/redo signal hookup skipped")
        if callable(refresh_undo_redo):
            refresh_undo_redo()
        else:
            view._set_document_undo_redo_enabled(False)
        view._set_edit_focus_guard(True)
        sync_panel = getattr(view, "_sync_text_property_panel_state", None)
        if callable(sync_panel):
            sync_panel()
        editor.setFocus()

    def on_edit_font_family_changed(self, *_) -> None:
        view = self._view
        if not view.text_editor or not view.text_editor.widget():
            return
        editor = view.text_editor.widget()
        selected_pdf_font = view._qt_font_to_pdf(
            str(view.text_font.currentData() or view.text_font.currentText())
        )
        font = editor.font()
        font.setFamily(view._pdf_font_to_qt(selected_pdf_font))
        editor.setFont(font)
        if hasattr(editor, "configure_render_context"):
            editor.configure_render_context(font_name=selected_pdf_font)
        view.editing_font_name = selected_pdf_font
        QTimer.singleShot(
            TextEditUIConstants.FOCUS_RESTORE_DELAY_MS,
            lambda: editor.setFocus(Qt.OtherFocusReason)
            if (view.text_editor and view.text_editor.widget() is editor)
            else None,
        )

    def on_edit_font_size_changed(self, size_str: str) -> None:
        view = self._view
        if not view.text_editor or not view.text_editor.widget():
            return
        size = _parse_font_size_str(size_str)
        if size is None or size <= 0:
            return
        view._editing_current_pdf_size = float(size)
        editor = view.text_editor.widget()
        font = editor.font()
        # Combo values stay in PDF points; the widget font is display-scaled.
        rs = view._render_scale if getattr(view, "_render_scale", 0) > 0 else 1.0
        font.setPointSizeF(_display_font_pt(size, rs))
        editor.setFont(font)
        if hasattr(editor, "configure_render_context"):
            editor.configure_render_context(font_size=float(size))
        QTimer.singleShot(
            TextEditUIConstants.FOCUS_RESTORE_DELAY_MS,
            lambda: editor.setFocus(Qt.OtherFocusReason)
            if (view.text_editor and view.text_editor.widget() is editor)
            else None,
        )

    def finalize_text_edit(
        self,
        reason: TextEditFinalizeReason = TextEditFinalizeReason.CLICK_AWAY,
    ) -> TextEditFinalizeResult | None:
        view = self._view
        if view._finalizing_text_edit:
            return view._last_text_edit_finalize_result
        if not view.text_editor or not view.text_editor.widget():
            view._set_edit_focus_guard(False)
            view._edit_focus_check_pending = False
            return None
        view._finalizing_text_edit = True
        try:
            result = self.finalize_text_edit_impl(reason)
            view._last_text_edit_finalize_result = result
            logger.debug(
                "text edit finalize: reason=%s intent=%s outcome=%s delta=%s",
                result.reason.value,
                result.intent,
                result.outcome.value,
                result.delta,
            )
            return result
        finally:
            view._set_edit_focus_guard(False)
            view._edit_focus_check_pending = False
            view._finalizing_text_edit = False

    def finalize_text_edit_impl(
        self,
        reason: TextEditFinalizeReason = TextEditFinalizeReason.CLICK_AWAY,
    ) -> TextEditFinalizeResult:
        view = self._view
        if not view.text_editor or not view.text_editor.widget():
            raise RuntimeError("Cannot finalize text edit without an active editor")

        editor = view.text_editor.widget()
        new_text = editor.toPlainText()
        original_text_prop = editor.property("original_text")
        text_changed = (
            _normalize_for_edit_compare(new_text)
            != _normalize_for_edit_compare(original_text_prop or "")
        )

        original_rect = view._editing_original_rect
        current_rect = view.editing_rect
        position_changed = (
            original_rect is not None and current_rect is not None and
            (
                abs(current_rect.x0 - original_rect.x0) > TextEditGeometryConstants.POSITION_CHANGE_TOLERANCE_PT
                or abs(current_rect.y0 - original_rect.y0) > TextEditGeometryConstants.POSITION_CHANGE_TOLERANCE_PT
            )
        )

        combo_size = _parse_font_size_str(view.text_size.currentText())
        current_size_attr = getattr(view, "_editing_current_pdf_size", combo_size)
        initial_size_attr = getattr(view, "_editing_initial_size", current_size_attr)
        try:
            current_size = float(current_size_attr) if current_size_attr is not None else (combo_size or 0.0)
        except (TypeError, ValueError):
            current_size = combo_size or 0.0
        try:
            initial_size = float(initial_size_attr) if initial_size_attr is not None else current_size
        except (TypeError, ValueError):
            initial_size = current_size
        session = TextEditSession(
            original_rect=fitz.Rect(original_rect) if original_rect else None,
            current_rect=fitz.Rect(current_rect) if current_rect else None,
            current_font=getattr(view, "editing_font_name", "helv"),
            initial_font=getattr(view, "_editing_initial_font_name", getattr(view, "editing_font_name", "helv")),
            original_color=getattr(view, "editing_color", (0, 0, 0)),
            current_size=float(current_size),
            initial_size=float(initial_size),
            edit_page=getattr(view, "_editing_page_idx", view.current_page),
            origin_page=getattr(view, "_editing_origin_page_idx", getattr(view, "_editing_page_idx", view.current_page)),
            intent=getattr(view, "editing_intent", "edit_existing"),
            target_span_id=getattr(view, "editing_target_span_id", None),
            target_mode=getattr(view, "editing_target_mode", "run"),
            original_text=getattr(view, "editing_original_text", None),
        )
        font_changed = str(session.current_font).lower() != str(session.initial_font).lower()
        size_changed = abs(float(session.current_size) - float(session.initial_size)) > 1e-3
        delta = TextEditDelta(
            text_changed=text_changed,
            style_changed=(font_changed or size_changed),
            position_changed=position_changed,
            page_changed=(session.origin_page != session.edit_page),
        )

        view._drag_pending = False
        view._drag_active = False
        view._drag_start_scene_pos = None
        view._drag_editor_start_pos = None
        view._pending_text_info = None
        if hasattr(view, "_text_edit_drag_state"):
            view._text_edit_drag_state = TextEditDragState.IDLE

        proxy_to_remove = view.text_editor
        view.text_editor = None
        if proxy_to_remove.scene():
            view.scene.removeItem(proxy_to_remove)
        self._clear_text_editor_mask_item()
        # Restore dim outline for the block that was just edited
        try:
            active_key = getattr(view, '_active_outline_key', None)
            if active_key is not None:
                outline = view._block_outline_items.get(active_key)
                if outline is not None:
                    outline.setVisible(True)
                view._active_outline_key = None
        except Exception:
            pass
        view.editing_rect = None
        view._editing_original_rect = None
        if getattr(view, "_edit_font_size_connected", False):
            try:
                view.text_size.currentTextChanged.disconnect(view._on_edit_font_size_changed)
            except (TypeError, RuntimeError):
                logger.debug("text size disconnect skipped during finalize")
            view._edit_font_size_connected = False
        if getattr(view, "_edit_font_family_connected", False):
            try:
                view.text_font.currentIndexChanged.disconnect(view._on_edit_font_family_changed)
            except (TypeError, RuntimeError):
                logger.debug("text font disconnect skipped during finalize")
            view._edit_font_family_connected = False
        refresh_undo_redo = getattr(view, "_refresh_undo_redo_action_state", None)
        if callable(refresh_undo_redo):
            refresh_undo_redo()
        else:
            view._set_document_undo_redo_enabled(True)
        if hasattr(view, "editing_font_name"):
            del view.editing_font_name
        if hasattr(view, "_editing_initial_font_name"):
            del view._editing_initial_font_name
        if hasattr(view, "_editing_initial_size"):
            del view._editing_initial_size
        if hasattr(view, "_editing_current_pdf_size"):
            del view._editing_current_pdf_size
        if hasattr(view, "editing_color"):
            del view.editing_color
        if hasattr(view, "_editing_page_idx"):
            del view._editing_page_idx
        if hasattr(view, "_editing_origin_page_idx"):
            del view._editing_origin_page_idx
        if hasattr(view, "_editing_rotation"):
            del view._editing_rotation
        if hasattr(view, "editing_target_span_id"):
            del view.editing_target_span_id
        if hasattr(view, "editing_target_mode"):
            del view.editing_target_mode
        if hasattr(view, "editing_intent"):
            del view.editing_intent
        sync_panel = getattr(view, "_sync_text_property_panel_state", None)
        if callable(sync_panel):
            sync_panel()

        if reason in {
            TextEditFinalizeReason.CANCEL_BUTTON,
            TextEditFinalizeReason.ESCAPE,
            # MODE_SWITCH removed — falls through to commit (same as CLICK_AWAY)
            TextEditFinalizeReason.CLOSE_DOCUMENT,
        }:
            return TextEditFinalizeResult(
                reason=reason,
                outcome=TextEditOutcome.DISCARDED,
                intent=session.intent,
                edit_page=session.edit_page,
                origin_page=session.origin_page,
                delta=delta,
            )

        if session.intent == "add_new":
            if new_text.strip() and session.current_rect is not None:
                try:
                    view.sig_add_textbox.emit(
                        session.edit_page + 1,
                        session.current_rect,
                        new_text,
                        session.current_font or view._add_text_default_pdf_font,
                        session.current_size,
                        session.original_color,
                    )
                except Exception as exc:
                    logger.error("發送新增文字框信號時出錯: %s", exc)
                return TextEditFinalizeResult(
                    reason=reason,
                    outcome=TextEditOutcome.COMMITTED,
                    intent=session.intent,
                    edit_page=session.edit_page,
                    origin_page=session.origin_page,
                    delta=delta,
                )
            return TextEditFinalizeResult(
                reason=reason,
                outcome=TextEditOutcome.NO_OP,
                intent=session.intent,
                edit_page=session.edit_page,
                origin_page=session.origin_page,
                delta=delta,
            )

        if not delta.any_change or not session.original_rect:
            return TextEditFinalizeResult(
                reason=reason,
                outcome=TextEditOutcome.NO_OP,
                intent=session.intent,
                edit_page=session.edit_page,
                origin_page=session.origin_page,
                delta=delta,
            )

        try:
            vertical_shift_left = getattr(view, "vertical_shift_left_cb", None)
            vertical_shift_left_value = vertical_shift_left.isChecked() if vertical_shift_left else True
            new_rect_arg = session.current_rect if position_changed else None
            if delta.page_changed and session.current_rect is not None:
                move_request = MoveTextRequest(
                    source_page=session.origin_page + 1,
                    source_rect=session.original_rect,
                    destination_page=session.edit_page + 1,
                    destination_rect=session.current_rect,
                    new_text=new_text,
                    font=session.current_font,
                    size=session.current_size,
                    color=session.original_color,
                    original_text=session.original_text,
                    target_span_id=session.target_span_id,
                    target_mode=session.target_mode,
                )
                view.sig_move_text_across_pages.emit(move_request)
            else:
                request = EditTextRequest(
                    page=session.edit_page + 1,
                    rect=session.original_rect,
                    new_text=new_text,
                    font=session.current_font,
                    size=session.current_size,
                    color=session.original_color,
                    original_text=session.original_text,
                    vertical_shift_left=vertical_shift_left_value,
                    new_rect=new_rect_arg,
                    target_span_id=session.target_span_id,
                    target_mode=session.target_mode,
                )
                view.sig_edit_text.emit(request)
        except Exception as exc:
            logger.error("發送編輯信號時出錯: %s", exc)
        return TextEditFinalizeResult(
            reason=reason,
            outcome=TextEditOutcome.COMMITTED,
            intent=session.intent,
            edit_page=session.edit_page,
            origin_page=session.origin_page,
            delta=delta,
        )
