"""Text-selection subsystem (R3.7 god-module decomposition seam — second view seam).

The browse-mode text-selection / highlight / copy methods extracted out of the PDFView
god-class into ``TextSelectionManager``, mirroring ``TextEditManager`` (view/text_editing.py)
and ``ObjectSelectionManager`` (view/object_selection.py, R3.6): a plain helper holding
``self._view`` (a back-reference to the PDFView). It reads/writes view state via
``self._view.<attr>``. There are NO Qt signals (selection is local; copy uses QClipboard).
PDFView keeps 1-line delegating wrappers for the 12 verbs (mouse handlers, context menu,
keyPress/menu QActions, the controller, and tests call them) + an ``_ensure_text_selection_manager()``
lazy accessor.

Scope note (approach X): this seam moves the METHODS only. The ~17 selection-state attrs
(`_text_selection_*`, `_selected_text_*`) and the three mouse handlers stay on PDFView for now
(manager reaches them via ``self._view``); state migration lands with the R3.8 handler refactor.

DEFERRED finding (not done here, to keep the move verbatim): unlike ObjectSelectionManager,
the selection-rect / extra-line-rect cleanup uses ``if item.scene():`` rather than
``shiboken6.isValid(item)``; hardening to the latter is a follow-up, not part of this no-op move.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QPoint, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from view.pdf_view import PDFView


class TextSelectionManager:
    def __init__(self, view: PDFView) -> None:
        self._view = view
        self._browse_text_cursor_active = False
        self._text_selection_active = False
        self._text_selection_page_idx = None
        self._text_selection_start_scene_pos = None
        self._text_selection_rect_item = None
        self._text_selection_live_doc_rect = None
        self._text_selection_live_text = ""
        self._text_selection_last_scene_pos = None
        self._text_selection_start_span_id = None
        self._text_selection_start_hit_info = None
        self._selected_text_rect_doc = None
        self._selected_text_page_idx = None
        self._selected_text_cached = ""
        self._selected_text_hit_info = None
        self._selected_text_from_drag = False
        self._text_selection_start_doc_point = None
        self._text_selection_extra_rect_items = []

    def _selected_text_has_context(self) -> bool:
        return bool(
            getattr(self._view, "current_mode", "browse") == "browse"
            and (
                getattr(self, "_selected_text_cached", "")
                or getattr(self, "_selected_text_rect_doc", None) is not None
            )
        )


    def _start_text_selection(self, scene_pos: QPointF, page_idx: int) -> None:
        self._view._clear_hover_highlight()
        self._view._reset_browse_hover_cursor()
        self._view._clear_text_selection()
        start_pos = self._view._clamp_scene_point_to_page(scene_pos, page_idx)
        try:
            hit_page_idx, doc_point = self._view._scene_pos_to_page_and_doc_point(start_pos)
            if hit_page_idx != page_idx:
                return
            start_hit = self._view.controller.get_text_info_at_point(
                page_idx + 1,
                doc_point,
                allow_fallback=False,
            )
        except Exception:
            start_hit = None
        if start_hit is None or not getattr(start_hit, "target_span_id", None):
            return
        self._text_selection_active = True
        self._text_selection_page_idx = page_idx
        self._text_selection_start_scene_pos = start_pos
        self._text_selection_live_doc_rect = None
        self._text_selection_live_text = ""
        self._text_selection_last_scene_pos = None
        self._text_selection_start_span_id = start_hit.target_span_id
        self._text_selection_start_hit_info = start_hit
        self._text_selection_start_doc_point = doc_point
        pen = QPen(QColor(30, 120, 255, 220), 1)
        brush = QBrush(QColor(30, 120, 255, 35))
        rect = QRectF(start_pos, start_pos).normalized()
        self._text_selection_rect_item = self._view.scene.addRect(rect, pen, brush)
        self._text_selection_rect_item.setZValue(20)
        # Live highlight should only appear after snapping to actual text bounds.
        self._text_selection_rect_item.setVisible(False)
        self._text_selection_extra_rect_items = []

    def _update_text_selection(self, scene_pos: QPointF, force: bool = False) -> None:
        if not self._text_selection_active or self._text_selection_page_idx is None:
            return
        if self._text_selection_start_scene_pos is None or self._text_selection_rect_item is None:
            return
        if not force and self._text_selection_last_scene_pos is not None:
            if (
                abs(scene_pos.x() - self._text_selection_last_scene_pos.x()) < 2.0 and
                abs(scene_pos.y() - self._text_selection_last_scene_pos.y()) < 2.0
            ):
                return
        self._text_selection_last_scene_pos = scene_pos

        end_pos = self._view._clamp_scene_point_to_page(scene_pos, self._text_selection_page_idx)
        try:
            end_page_idx, end_doc_point = self._view._scene_pos_to_page_and_doc_point(end_pos)
        except Exception:
            end_page_idx, end_doc_point = self._text_selection_page_idx, None
        if end_doc_point is None or end_page_idx != self._text_selection_page_idx:
            self._text_selection_live_doc_rect = None
            self._text_selection_live_text = ""
            self._text_selection_rect_item.setVisible(False)
            return

        try:
            selected_text, line_rects = self._view.controller.get_text_selection_lines(
                self._text_selection_page_idx + 1,
                self._text_selection_start_span_id,
                end_doc_point,
                getattr(self, "_text_selection_start_doc_point", None),
            )
        except Exception:
            selected_text = ""
            line_rects = []
        if not selected_text.strip() or not line_rects:
            self._text_selection_live_doc_rect = None
            self._text_selection_live_text = ""
            self._text_selection_rect_item.setVisible(False)
            self._view._clear_text_selection_extra_rects()
            return

        bounds = fitz.Rect(line_rects[0])
        for line_rect in line_rects[1:]:
            bounds.include_rect(line_rect)
        if bounds.width <= 0 or bounds.height <= 0:
            self._text_selection_live_doc_rect = None
            self._text_selection_live_text = ""
            self._text_selection_rect_item.setVisible(False)
            self._view._clear_text_selection_extra_rects()
            return

        self._text_selection_live_doc_rect = bounds
        self._text_selection_live_text = selected_text
        self._view._render_text_selection_line_rects(line_rects)

    def _finalize_text_selection(self, scene_pos: QPointF) -> None:
        if not self._text_selection_active:
            return
        if self._text_selection_start_scene_pos is not None:
            dx = scene_pos.x() - self._text_selection_start_scene_pos.x()
            dy = scene_pos.y() - self._text_selection_start_scene_pos.y()
            if dx * dx + dy * dy < 4.0:
                self._view._clear_text_selection()
                return

        self._view._update_text_selection(scene_pos, force=True)
        self._text_selection_active = False
        self._text_selection_start_scene_pos = None
        self._text_selection_last_scene_pos = None
        page_idx = self._text_selection_page_idx
        if page_idx is None or self._text_selection_rect_item is None:
            self._view._clear_text_selection()
            return
        doc_rect = self._text_selection_live_doc_rect
        if doc_rect is None:
            self._view._clear_text_selection()
            return
        selected_text = (getattr(self, "_text_selection_live_text", "") or "").strip()
        if not selected_text.strip():
            self._view._clear_text_selection()
            return
        self._selected_text_page_idx = page_idx
        self._selected_text_rect_doc = fitz.Rect(doc_rect)
        self._selected_text_cached = selected_text
        self._selected_text_hit_info = getattr(self, "_text_selection_start_hit_info", None)
        self._selected_text_from_drag = True
        # Per-line highlight rects were already rendered by _update_text_selection
        # above; keep them rather than collapsing to a single bounding rectangle.
        self._view._sync_text_property_panel_state()

    def _selection_doc_rect_to_scene(self, doc_rect: fitz.Rect) -> QRectF:
        rs = self._view._render_scale if self._view._render_scale > 0 else 1.0
        page_idx = self._text_selection_page_idx or 0
        y0 = self._view.page_y_positions[page_idx] if (
            self._view.continuous_pages and page_idx < len(self._view.page_y_positions)
        ) else 0.0
        return QRectF(
            doc_rect.x0 * rs,
            y0 + doc_rect.y0 * rs,
            max(1.0, doc_rect.width * rs),
            max(1.0, doc_rect.height * rs),
        )

    def _clear_text_selection_extra_rects(self) -> None:
        for item in getattr(self, "_text_selection_extra_rect_items", None) or []:
            try:
                self._view.scene.removeItem(item)
            except Exception:
                pass
        self._text_selection_extra_rect_items = []

    def _render_text_selection_line_rects(self, line_rects: list) -> None:
        """Draw one highlight rect per visual line so a multi-line selection shows
        a partial first line, full middle lines and a partial last line (AC-1d)."""
        if self._text_selection_rect_item is None or not line_rects:
            return
        self._view._clear_text_selection_extra_rects()
        self._text_selection_rect_item.setRect(self._view._selection_doc_rect_to_scene(line_rects[0]))
        self._text_selection_rect_item.setVisible(True)
        pen = QPen(QColor(30, 120, 255, 220), 1)
        brush = QBrush(QColor(30, 120, 255, 35))
        extras = []
        for doc_rect in line_rects[1:]:
            item = self._view.scene.addRect(self._view._selection_doc_rect_to_scene(doc_rect), pen, brush)
            try:
                item.setZValue(20)
            except Exception:
                pass
            extras.append(item)
        self._text_selection_extra_rect_items = extras

    def _clear_text_selection(self) -> None:
        self._text_selection_active = False
        self._text_selection_page_idx = None
        self._text_selection_start_scene_pos = None
        self._text_selection_live_doc_rect = None
        self._text_selection_live_text = ""
        self._text_selection_last_scene_pos = None
        self._text_selection_start_span_id = None
        self._text_selection_start_hit_info = None
        self._selected_text_rect_doc = None
        self._selected_text_page_idx = None
        self._selected_text_cached = ""
        self._selected_text_hit_info = None
        self._selected_text_from_drag = False
        if self._text_selection_rect_item is not None:
            try:
                if self._text_selection_rect_item.scene():
                    self._view.scene.removeItem(self._text_selection_rect_item)
            except Exception:
                pass
            self._text_selection_rect_item = None
        self._view._clear_text_selection_extra_rects()
        self._text_selection_start_doc_point = None
        self._view._sync_text_property_panel_state()

    def _resolve_text_info_for_doc_rect(self, page_idx: int, doc_rect: fitz.Rect):
        controller = getattr(self._view, "controller", None)
        if controller is None or doc_rect is None:
            return None
        try:
            center = fitz.Point((doc_rect.x0 + doc_rect.x1) / 2.0, (doc_rect.y0 + doc_rect.y1) / 2.0)
            return controller.get_text_info_at_point(page_idx + 1, center)
        except Exception:
            return None

    def _resolve_text_info_for_context_menu_pos(self, pos: QPoint):
        if self._view.current_mode != "browse":
            return None
        controller = getattr(self._view, "controller", None)
        graphics_view = getattr(self._view, "graphics_view", None)
        if controller is None or graphics_view is None:
            return None
        try:
            scene_pos = graphics_view.mapToScene(pos)
            page_idx, doc_point = self._view._scene_pos_to_page_and_doc_point(scene_pos)
            info = controller.get_text_info_at_point(page_idx + 1, doc_point)
        except Exception:
            return None
        if info is None:
            return None
        return page_idx, info

    def _select_all_text_on_current_page(self) -> bool:
        if self._view.total_pages <= 0:
            return False
        controller = getattr(self._view, "controller", None)
        model = getattr(controller, "model", None) if controller is not None else None
        if model is None or not getattr(model, "doc", None):
            return False

        page_idx = min(max(self._view.current_page, 0), self._view.total_pages - 1)
        try:
            page_rect = self._view.controller.get_page_rect(page_idx)
        except Exception:
            return False

        try:
            selected_text = controller.get_text_in_rect(page_idx + 1, page_rect)
        except Exception:
            selected_text = ""
        if not selected_text.strip():
            return False

        precise_doc_rect = fitz.Rect(page_rect)
        try:
            precise = controller.get_text_bounds(page_idx + 1, page_rect)
            if precise is not None and precise.width > 0 and precise.height > 0:
                precise_doc_rect = fitz.Rect(precise)
        except Exception:
            pass

        self._selected_text_page_idx = page_idx
        self._selected_text_rect_doc = precise_doc_rect
        self._selected_text_cached = selected_text
        self._selected_text_hit_info = self._view._resolve_text_info_for_doc_rect(page_idx, precise_doc_rect)
        self._selected_text_from_drag = False

        if self._text_selection_rect_item is None and getattr(self._view, "scene", None) is not None:
            pen = QPen(QColor(30, 120, 255, 200), 2)
            brush = QBrush(QColor(30, 120, 255, 35))
            self._text_selection_rect_item = self._view.scene.addRect(QRectF(), pen, brush)
            self._text_selection_rect_item.setZValue(11)

        if self._text_selection_rect_item is not None:
            rs = self._view._render_scale if self._view._render_scale > 0 else 1.0
            y0 = self._view.page_y_positions[page_idx] if (
                self._view.continuous_pages and page_idx < len(self._view.page_y_positions)
            ) else 0.0
            scene_rect = QRectF(
                precise_doc_rect.x0 * rs,
                y0 + precise_doc_rect.y0 * rs,
                max(1.0, precise_doc_rect.width * rs),
                max(1.0, precise_doc_rect.height * rs),
            )
            self._text_selection_rect_item.setRect(scene_rect)
            self._text_selection_rect_item.setVisible(True)

        self._view._sync_text_property_panel_state()
        return True


    def _copy_selected_text_to_clipboard(self) -> bool:
        text = (self._selected_text_cached or "").strip()
        if not text and self._selected_text_rect_doc is not None and self._selected_text_page_idx is not None:
            if getattr(self, "_selected_text_from_drag", False):
                return False
            try:
                text = self._view.controller.get_text_in_rect(self._selected_text_page_idx + 1, self._selected_text_rect_doc).strip()
            except Exception:
                text = ""
        if not text:
            return False
        QApplication.clipboard().setText(text)
        self._selected_text_cached = text
        if getattr(self._view, "status_bar", None):
            self._view.status_bar.showMessage("Copied selected text", 1500)
        return True

    # R3.6: object-selection verbs delegate to ObjectSelectionManager
    # (view/object_selection.py). State attrs + mouse handlers stay here for now.
