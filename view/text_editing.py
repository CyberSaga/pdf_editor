from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from enum import Enum

import fitz
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor, QTextOption
from PySide6.QtWidgets import QTextEdit

from model.edit_requests import EditTextRequest, MoveTextRequest

logger = logging.getLogger(__name__)

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


class TextEditUIConstants:
    MIN_EDITOR_WIDTH_PX = 80
    MIN_EDITOR_HEIGHT_PX = 40
    FOCUS_RESTORE_DELAY_MS = 0
    MASK_SAMPLE_INSET_RATIO = 0.15
    MASK_SAMPLE_INSET_MAX_PX = 6.0


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
    current_size: int
    initial_size: int
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


class TextEditManager:
    def __init__(self, view) -> None:
        self._view = view

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
        editor_proxy = getattr(self._view, "text_editor", None)
        if not editor_proxy or not editor_proxy.widget():
            return
        page_idx = getattr(self._view, "_editing_page_idx", self._view.current_page)
        scene_rect = self.current_text_editor_scene_rect()
        if scene_rect is None:
            return
        editor = editor_proxy.widget()
        text_rgb = editor.property("text_rgb") or (0, 0, 0)
        mask_color = self._view._sample_page_mask_color(page_idx, scene_rect)
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
        target_span_id: str = None,
        target_mode: str = "run",
        editor_intent: str = "edit_existing",
    ) -> None:
        view = self._view
        if view.text_editor:
            view._finalize_text_edit()

        page_idx = getattr(view, "_editing_page_idx", view.current_page)
        render_width_pt = view.controller.model.get_render_width_for_edit(page_idx + 1, rect, rotation, font_size)
        rs = view._render_scale if view._render_scale > 0 else 1.0
        scaled_width = int(render_width_pt * rs)
        scaled_rect = rect * rs

        view.editing_rect = rect
        view._editing_original_rect = fitz.Rect(rect)
        view._editing_origin_page_idx = page_idx
        y0 = view.page_y_positions[page_idx] if (view.continuous_pages and page_idx < len(view.page_y_positions)) else 0
        pos_x = scaled_rect.x0
        pos_y = y0 + scaled_rect.y0

        editor = InlineTextEditor(text)
        editor.setProperty("original_text", text)
        view._editing_rotation = rotation
        view.editing_target_span_id = target_span_id
        view.editing_target_mode = target_mode if target_mode in ("run", "paragraph") else "run"
        view.editing_intent = editor_intent if editor_intent in ("edit_existing", "add_new") else "edit_existing"

        qt_font = view._pdf_font_to_qt(font_name)
        editor.setFont(QFont(qt_font, int(font_size)))

        r, g, b = [int(c * 255) for c in color]
        text_rgb = (r, g, b)
        editor.setProperty("text_rgb", text_rgb)
        editor.setAutoFillBackground(False)
        editor.viewport().setAutoFillBackground(False)
        editor.setStyleSheet(view._build_text_editor_stylesheet(text_rgb, QColor(_DEFAULT_EDITOR_MASK_COLOR)))

        editor.setFixedWidth(max(scaled_width, TextEditUIConstants.MIN_EDITOR_WIDTH_PX))
        editor.setMinimumHeight(max(scaled_rect.height, TextEditUIConstants.MIN_EDITOR_HEIGHT_PX))
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapAnywhere)

        size_str = str(round(font_size))
        if view.text_size.findText(size_str) == -1:
            view.text_size.addItem(size_str)
            items = sorted([view.text_size.itemText(i) for i in range(view.text_size.count())], key=int)
            view.text_size.clear()
            view.text_size.addItems(items)
        view.text_size.setCurrentText(size_str)
        normalized_font = view._qt_font_to_pdf(font_name)
        view._set_text_font_by_pdf(normalized_font)
        view._editing_initial_font_name = normalized_font
        view._editing_initial_size = int(round(font_size))
        if not hasattr(view, "editing_font_name"):
            view.editing_font_name = normalized_font
        if not getattr(view, "_edit_font_size_connected", False):
            view.text_size.currentTextChanged.connect(view._on_edit_font_size_changed)
            view._edit_font_size_connected = True
        if not getattr(view, "_edit_font_family_connected", False):
            view.text_font.currentIndexChanged.connect(view._on_edit_font_family_changed)
            view._edit_font_family_connected = True

        view.text_editor = view.scene.addWidget(editor)
        view.text_editor.setPos(pos_x, pos_y)
        self.refresh_text_editor_mask_color()
        view._editor_shortcut_forwarder = _EditorShortcutForwarder(view)
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
        try:
            size = int(size_str)
        except (ValueError, TypeError):
            return
        editor = view.text_editor.widget()
        font = editor.font()
        font.setPointSize(size)
        editor.setFont(font)
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

        session = TextEditSession(
            original_rect=fitz.Rect(original_rect) if original_rect else None,
            current_rect=fitz.Rect(current_rect) if current_rect else None,
            current_font=getattr(view, "editing_font_name", "helv"),
            initial_font=getattr(view, "_editing_initial_font_name", getattr(view, "editing_font_name", "helv")),
            original_color=getattr(view, "editing_color", (0, 0, 0)),
            current_size=int(view.text_size.currentText()),
            initial_size=int(getattr(view, "_editing_initial_size", int(view.text_size.currentText()))),
            edit_page=getattr(view, "_editing_page_idx", view.current_page),
            origin_page=getattr(view, "_editing_origin_page_idx", getattr(view, "_editing_page_idx", view.current_page)),
            intent=getattr(view, "editing_intent", "edit_existing"),
            target_span_id=getattr(view, "editing_target_span_id", None),
            target_mode=getattr(view, "editing_target_mode", "run"),
            original_text=getattr(view, "editing_original_text", None),
        )
        font_changed = str(session.current_font).lower() != str(session.initial_font).lower()
        size_changed = session.current_size != session.initial_size
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
