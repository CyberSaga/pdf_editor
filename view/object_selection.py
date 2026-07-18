"""Object-selection subsystem (R3.6 god-module decomposition seam — first view seam).

The object selection / drag / resize / free-rotation methods extracted out of the
``PDFView`` god-class into ``ObjectSelectionManager``, mirroring ``TextEditManager``
(view/text_editing.py): a plain helper holding ``self._view`` (a back-reference to the
PDFView). It reads/writes view state via ``self._view.<attr>`` and emits Qt Signals via
``self._view.sig_*`` (Signals stay class attributes on PDFView — a plain helper cannot own
them). PDFView keeps 1-line delegating wrappers for the 20 verbs the mouse handlers,
context menu, keyPress and tests call.

Scope note (approach X): this seam moves the METHODS only. The ~26 interaction-state attrs
(`_selected_object_*`, `_object_drag_*`, `_object_rotate_*`, `_object_resize_*`) and the three
mouse handlers stay on PDFView for now; the manager reaches that state via ``self._view``.
Migrating the state into the manager is coupled to the mouse-handler refactor and lands with
R3.8 (the handler dispatcher), avoiding a temporary property-forwarder scaffold here.

``absolute_rotation_from_drag`` (pure geometry, used by ``_commit_free_rotation``) moves here
and is re-exported from ``pdf_view`` so ``pdf_view.absolute_rotation_from_drag`` test refs hold.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import fitz
import shiboken6
from PySide6.QtCore import QPoint, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QCursor, QPen
from PySide6.QtWidgets import QMenu

from model.object_requests import (
    BatchDeleteObjectsRequest,
    DeleteObjectRequest,
    ObjectRef,
    RotateObjectRequest,
)

if TYPE_CHECKING:
    from view.pdf_view import PDFView


def absolute_rotation_from_drag(
    start_rotation: float,
    start_angle: float,
    current_angle: float,
) -> float:
    """Absolute stored rotation for a rotate-handle drag.

    ``start_rotation`` is the object's stored angle at grab time;
    ``start_angle``/``current_angle`` are :func:`screen_angle_degrees` samples.
    The screen delta is clockwise-positive; the stored (raw-cm) convention is
    the screen direction's inverse, so it is subtracted.
    """
    delta = current_angle - start_angle
    return (start_rotation - delta) % 360.0



class ObjectSelectionManager:
    def __init__(self, view: PDFView) -> None:
        self._view = view
        self._selected_object_info = None
        self._object_selection_rect_item = None
        self._object_rotate_handle_item = None
        self._object_drag_pending = False
        self._object_drag_active = False
        self._object_rotate_pending = False
        self._object_rotate_active = False
        self._object_rotate_center_scene = None
        self._object_rotate_start_angle = 0.0
        self._object_rotate_start_rotation = 0.0
        self._object_rotate_preview_angle = 0.0
        self._object_drag_start_scene_pos = None
        self._object_drag_start_doc_rect = None
        self._object_drag_start_doc_rects = None
        self._object_drag_preview_rect = None
        self._object_drag_preview_rects = None
        self._object_drag_page_idx = None
        self._selected_object_infos = {}
        self._selected_object_page_idx = None
        self._object_resize_handle_items = []
        self._object_resize_pending = False
        self._object_resize_active = False
        self._object_resize_start_scene_pos = None
        self._object_resize_start_doc_rect = None
        self._object_resize_preview_rect = None
        self._object_resize_handle_anchor = 3

    def _resolve_object_info_for_context_menu_pos(self, pos: QPoint):
        if self._view.current_mode not in ("browse", "objects", "edit_text", "text_edit"):
            return None
        controller = getattr(self._view, "controller", None)
        graphics_view = getattr(self._view, "graphics_view", None)
        if controller is None or graphics_view is None:
            return None
        try:
            scene_pos = graphics_view.mapToScene(pos)
            page_idx, doc_point = self._view._scene_pos_to_page_and_doc_point(scene_pos)
            info = controller.get_object_info_at_point(page_idx + 1, doc_point)
        except Exception:
            return None
        if info is None:
            return None
        allowed_kinds = None
        if self._view.current_mode == "objects":
            allowed_kinds = ("rect", "image")
        elif self._view.current_mode in ("edit_text", "text_edit"):
            allowed_kinds = ("textbox",)
        if allowed_kinds is not None and getattr(info, "object_kind", None) not in allowed_kinds:
            return None
        return page_idx, info


    def _clear_object_selection(self) -> None:
        self._selected_object_info = None
        if hasattr(self, "_selected_object_infos"):
            self._selected_object_infos = {}
        if hasattr(self, "_selected_object_page_idx"):
            self._selected_object_page_idx = None
        self._object_drag_pending = False
        self._object_drag_active = False
        self._object_rotate_pending = False
        self._object_drag_start_scene_pos = None
        self._object_drag_start_doc_rect = None
        self._object_drag_preview_rect = None
        self._object_drag_page_idx = None
        if self._object_selection_rect_item is not None:
            try:
                self._view.scene.removeItem(self._object_selection_rect_item)
            except Exception:
                pass
            self._object_selection_rect_item = None
        if self._object_rotate_handle_item is not None:
            try:
                self._view.scene.removeItem(self._object_rotate_handle_item)
            except Exception:
                pass
            self._object_rotate_handle_item = None
        for item in getattr(self, "_object_resize_handle_items", []) or []:
            try:
                self._view.scene.removeItem(item)
            except Exception:
                pass
        self._object_resize_handle_items = []
        self._object_resize_pending = False
        self._object_resize_active = False
        self._object_resize_start_scene_pos = None
        self._object_resize_start_doc_rect = None
        self._object_resize_preview_rect = None
        self._object_resize_handle_anchor = 3  # default BR

    def _select_object(self, info) -> None:
        self._selected_object_info = info
        self._view._update_object_selection_visuals()

    def _rebase_object_selection_to_bboxes(self, new_bboxes: dict[str, fitz.Rect]) -> None:
        """Replace selection state with new bboxes and refresh overlay visuals.

        Used by drag/resize release paths so the selection overlay follows moved
        objects without waiting for the next click. Safe to call whether the
        selection is single (`_selected_object_info` only) or multi (`_selected_object_infos`).
        """
        infos = getattr(self, "_selected_object_infos", None)
        selected = self._selected_object_info
        selected_oid = str(selected.object_id) if selected is not None else None
        for oid, new_bbox in new_bboxes.items():
            target = None
            if infos is not None and oid in infos:
                target = infos[oid]
            elif selected_oid == oid:
                target = selected
            if target is None:
                continue
            new_info = replace(target, bbox=fitz.Rect(new_bbox))
            if infos is not None and oid in infos:
                infos[oid] = new_info
            if selected_oid == oid:
                self._selected_object_info = new_info
        if infos:
            self._object_drag_start_doc_rects = {
                k: fitz.Rect(v.bbox) for k, v in infos.items()
            }
        if self._selected_object_info is not None:
            self._object_drag_start_doc_rect = fitz.Rect(self._selected_object_info.bbox)
            self._object_drag_preview_rect = fitz.Rect(self._selected_object_info.bbox)
        self._view._update_object_selection_visuals()

    def _apply_object_selection_rotation(self, angle_deg: float) -> None:
        """Rotate the selection box + handle items about the object centre, so the
        whole frame turns rigidly with the object during a rotate drag (AC-4c)."""
        center = getattr(self, "_object_rotate_center_scene", None)
        if center is None:
            return
        items = [getattr(self, "_object_selection_rect_item", None)]
        items.append(getattr(self, "_object_rotate_handle_item", None))
        items.extend(getattr(self, "_object_resize_handle_items", None) or [])
        for item in items:
            if item is None:
                continue
            try:
                item.setTransformOriginPoint(center)
                item.setRotation(angle_deg)
            except Exception:
                continue

    def _object_center_scene(self, info) -> QPointF:
        """Scene-space centre of an object's bbox (accounts for render scale and
        continuous-mode page offset)."""
        rs = self._view._render_scale if self._view._render_scale > 0 else 1.0
        page_idx = max(0, int(info.page_num) - 1)
        x0 = self._view._page_scene_x(page_idx)
        y0 = self._view._page_scene_y(page_idx)
        bbox = fitz.Rect(info.bbox)
        return QPointF(
            x0 + (bbox.x0 + bbox.x1) / 2.0 * rs,
            y0 + (bbox.y0 + bbox.y1) / 2.0 * rs,
        )

    def _supports_free_rotate(self, info: object | None) -> bool:
        if info is None or not getattr(info, "supports_rotate", False):
            return False
        return str(getattr(info, "object_kind", "") or "") in {"image", "native_image"}

    def _update_object_selection_visuals(self, rect: fitz.Rect | None = None) -> None:
        info = getattr(self, "_selected_object_info", None)
        if info is None or getattr(self._view, "scene", None) is None:
            return
        # scene.clear() deletes the underlying C++ items but leaves the Python
        # wrappers dangling; drop them here so we re-create instead of poking
        # a freed object.
        if self._object_selection_rect_item is not None and not shiboken6.isValid(self._object_selection_rect_item):
            self._object_selection_rect_item = None
        if self._object_rotate_handle_item is not None and not shiboken6.isValid(self._object_rotate_handle_item):
            self._object_rotate_handle_item = None
        if getattr(self, "_object_resize_handle_items", None):
            self._object_resize_handle_items = [
                item for item in self._object_resize_handle_items if shiboken6.isValid(item)
            ]
        bbox = fitz.Rect(rect if rect is not None else info.bbox)
        page_idx = max(0, int(info.page_num) - 1)
        scene_rect = self._view._doc_rect_to_scene_rect(page_idx, bbox)
        pen = QPen(QColor(14, 165, 233, 220), 2)
        brush = QBrush(QColor(14, 165, 233, 30))
        if self._object_selection_rect_item is None:
            self._object_selection_rect_item = self._view.scene.addRect(scene_rect, pen, brush)
            self._object_selection_rect_item.setZValue(21)
        else:
            self._object_selection_rect_item.setRect(scene_rect)
            self._object_selection_rect_item.setPen(pen)
            self._object_selection_rect_item.setBrush(brush)
        if self._view._supports_free_rotate(info):
            handle_rect = QRectF(scene_rect.right() - 12, scene_rect.top() - 18, 12, 12)
            if self._object_rotate_handle_item is None:
                self._object_rotate_handle_item = self._view.scene.addEllipse(
                    handle_rect,
                    QPen(QColor(2, 132, 199, 230), 1),
                    QBrush(QColor(56, 189, 248, 220)),
                )
                self._object_rotate_handle_item.setZValue(22)
            else:
                self._object_rotate_handle_item.setRect(handle_rect)
        elif self._object_rotate_handle_item is not None:
            try:
                self._view.scene.removeItem(self._object_rotate_handle_item)
            except Exception:
                pass
            self._object_rotate_handle_item = None

        # Resize handles: single-select only.
        if getattr(self, "_object_resize_handle_items", None) is None:
            self._object_resize_handle_items = []
        for item in list(self._object_resize_handle_items):
            try:
                self._view.scene.removeItem(item)
            except Exception:
                pass
        self._object_resize_handle_items = []

        handle_size = 10.0
        half = handle_size / 2.0
        handle_pen = QPen(QColor(2, 132, 199, 230), 1)
        handle_brush = QBrush(QColor(56, 189, 248, 220))
        for hx, hy in (
            (scene_rect.left() - half, scene_rect.top() - half),  # TL
            (scene_rect.right() - half, scene_rect.top() - half),  # TR
            (scene_rect.left() - half, scene_rect.bottom() - half),  # BL
            (scene_rect.right() - half, scene_rect.bottom() - half),  # BR
            (scene_rect.center().x() - half, scene_rect.top() - half),  # top
            (scene_rect.right() - half, scene_rect.center().y() - half),  # right
            (scene_rect.center().x() - half, scene_rect.bottom() - half),  # bottom
            (scene_rect.left() - half, scene_rect.center().y() - half),  # left
        ):
            hrect = QRectF(hx, hy, handle_size, handle_size)
            item = self._view.scene.addRect(hrect, handle_pen, handle_brush)
            try:
                item.setZValue(22)
            except Exception:
                pass
            self._object_resize_handle_items.append(item)

    def _point_hits_object_resize_handle(self, scene_pos: QPointF) -> bool:
        return self._view._hit_object_resize_handle_index(scene_pos) >= 0

    def _hit_object_resize_handle_index(self, scene_pos: QPointF) -> int:
        """Return handle index (corners 0..3, edges top/right/bottom/left 4..7)."""
        items = getattr(self, "_object_resize_handle_items", None) or []
        for i, item in enumerate(items):
            try:
                if item.rect().contains(scene_pos):
                    return i
            except Exception:
                continue
        return -1

    def _point_hits_object_rotate_handle(self, scene_pos: QPointF) -> bool:
        if self._object_rotate_handle_item is None:
            return False
        try:
            return self._object_rotate_handle_item.rect().contains(scene_pos)
        except Exception:
            return False

    def _delete_selected_object(self) -> bool:
        infos = getattr(self, "_selected_object_infos", None)
        if infos and len(infos) > 1:
            refs: list[ObjectRef] = []
            for info in infos.values():
                if not getattr(info, "supports_delete", False):
                    continue
                refs.append(
                    ObjectRef(
                        object_id=str(info.object_id),
                        object_kind=str(info.object_kind),
                        page_num=int(info.page_num),
                    )
                )
            if not refs:
                return False
            self._view.sig_delete_object.emit(BatchDeleteObjectsRequest(objects=refs))
            self._view._clear_object_selection()
            return True
        info = getattr(self, "_selected_object_info", None)
        if info is None or not getattr(info, "supports_delete", False):
            return False
        self._view.sig_delete_object.emit(
            DeleteObjectRequest(
                object_id=info.object_id,
                object_kind=info.object_kind,
                page_num=info.page_num,
            )
        )
        self._view._clear_object_selection()
        return True

    def _commit_free_rotation(self) -> bool:
        """Emit an absolute-angle rotate request from an accumulated drag (AC-4a)."""
        info = getattr(self, "_selected_object_info", None)
        if not self._view._supports_free_rotate(info):
            return False
        start_rotation = float(getattr(self, "_object_rotate_start_rotation", 0.0) or 0.0)
        start_angle = float(getattr(self, "_object_rotate_start_angle", 0.0) or 0.0)
        delta_screen = float(getattr(self, "_object_rotate_preview_angle", 0.0) or 0.0)
        new_angle = absolute_rotation_from_drag(
            start_rotation, start_angle, start_angle + delta_screen
        )
        self._view.sig_rotate_object.emit(
            RotateObjectRequest(
                object_id=info.object_id,
                object_kind=info.object_kind,
                page_num=info.page_num,
                rotation_delta=0,
                absolute_rotation=new_angle,
            )
        )
        self._object_rotate_preview_angle = 0.0
        # Clear the live preview transform; the page re-render + reselect will
        # rebuild the frame around the new (rotated) bounding box.
        for item in (
            [getattr(self, "_object_selection_rect_item", None),
             getattr(self, "_object_rotate_handle_item", None)]
            + (getattr(self, "_object_resize_handle_items", None) or [])
        ):
            if item is None:
                continue
            try:
                item.setRotation(0.0)
            except Exception:
                continue
        self._selected_object_info = replace(
            info, bbox=fitz.Rect(info.bbox), rotation=new_angle
        )
        return True

    def _rotate_selected_object(self, rotation_delta: int) -> bool:
        info = getattr(self, "_selected_object_info", None)
        if info is None or not getattr(info, "supports_rotate", False):
            return False
        self._view.sig_rotate_object.emit(
            RotateObjectRequest(
                object_id=info.object_id,
                object_kind=info.object_kind,
                page_num=info.page_num,
                rotation_delta=rotation_delta,
            )
        )
        self._selected_object_info = replace(
            info,
            bbox=fitz.Rect(info.bbox),
            rotation=(int(info.rotation) + int(rotation_delta)) % 360,
        )
        self._view._update_object_selection_visuals()
        return True

    def _normalize_object_rotation_angle(self, angle: int | float) -> float:
        return float(angle) % 360.0

    def _rotate_selected_object_absolute(self, angle: int | float) -> bool:
        info = getattr(self, "_selected_object_info", None)
        if info is None or not getattr(info, "supports_rotate", False):
            return False
        absolute = self._view._normalize_object_rotation_angle(angle)
        self._view.sig_rotate_object.emit(
            RotateObjectRequest(
                object_id=info.object_id,
                object_kind=info.object_kind,
                page_num=info.page_num,
                rotation_delta=0,
                absolute_rotation=absolute,
            )
        )
        self._selected_object_info = replace(
            info,
            bbox=fitz.Rect(info.bbox),
            rotation=absolute,
        )
        self._view._update_object_selection_visuals()
        return True

    @staticmethod
    def _next_right_angle_rotation(current_angle: int | float) -> float:
        normalized = float(current_angle) % 360.0
        for target in (90.0, 180.0, 270.0, 360.0):
            if normalized < target:
                return 0.0 if target == 360.0 else target
        return 90.0

    def _rotate_selected_object_to_next_right_angle(self) -> bool:
        info = getattr(self, "_selected_object_info", None)
        if info is None or not getattr(info, "supports_rotate", False):
            return False
        target = self._view._next_right_angle_rotation(getattr(info, "rotation", 0.0))
        return self._view._rotate_selected_object_absolute(target)

    def _add_object_rotation_actions(self, menu: QMenu) -> None:
        menu.addAction("Rotate Object", lambda checked=False: self._view._rotate_selected_object_to_next_right_angle())

    def _show_object_rotation_menu(self, pos: QPoint | QPointF | None = None) -> None:
        menu = QMenu(self)
        self._view._add_object_rotation_actions(menu)
        if pos is None:
            menu.exec_(QCursor.pos())
            return
        if isinstance(pos, QPointF):
            pos = pos.toPoint()
        menu.exec_(self._view.graphics_view.viewport().mapToGlobal(pos))

