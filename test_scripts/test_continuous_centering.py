from __future__ import annotations

from types import SimpleNamespace

import fitz
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPixmap

from view.pdf_view import PDFView


def _view(qapp) -> PDFView:
    view = PDFView()
    view.show()
    qapp.processEvents()
    return view


def test_mixed_width_pages_are_centered_in_widest_page_column(qapp) -> None:
    view = _view(qapp)
    try:
        view.initialize_continuous_placeholders(
            [(300.0, 500.0), (600.0, 400.0), (400.0, 700.0)],
            1.0,
        )

        assert view.scene.sceneRect().width() == 600.0
        assert view.page_x_positions == [150.0, 0.0, 100.0]
        for item in view.page_items:
            assert abs(item.sceneBoundingRect().center().x() - 300.0) <= 0.01
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_centering_survives_scale_and_pixmap_replacement(qapp) -> None:
    view = _view(qapp)
    try:
        view.initialize_continuous_placeholders(
            [(300.0, 500.0), (600.0, 400.0)],
            2.0,
        )
        assert view.page_x_positions == [300.0, 0.0]
        before = view.page_items[0].pos()

        view.update_page_in_scene_scaled(0, QPixmap(300, 500), 1.0, 2.0)

        assert view.page_items[0].pos() == before
        assert abs(view.page_items[0].sceneBoundingRect().center().x() - 600.0) <= 0.01
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_scene_document_round_trip_uses_page_x_and_y_origins(qapp) -> None:
    view = _view(qapp)
    try:
        view.initialize_continuous_placeholders(
            [(300.0, 500.0), (600.0, 400.0)],
            1.5,
        )
        page_idx = 0
        x0 = view.page_x_positions[page_idx]
        y0 = view.page_y_positions[page_idx]
        scene_point = QPointF(x0 + 45.0, y0 + 75.0)

        resolved_page, doc_point = view._scene_pos_to_page_and_doc_point(scene_point)
        scene_rect = view._doc_rect_to_scene_rect(
            page_idx,
            fitz.Rect(doc_point.x, doc_point.y, doc_point.x + 20.0, doc_point.y + 10.0),
        )

        assert resolved_page == page_idx
        assert abs(doc_point.x - 30.0) <= 1e-6
        assert abs(doc_point.y - 50.0) <= 1e-6
        assert abs(scene_rect.left() - scene_point.x()) <= 1e-6
        assert abs(scene_rect.top() - scene_point.y()) <= 1e-6
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_selection_object_and_editor_geometry_share_page_x_origin(qapp) -> None:
    view = _view(qapp)
    try:
        view.initialize_continuous_placeholders(
            [(300.0, 500.0), (600.0, 400.0)],
            1.0,
        )
        view.controller = SimpleNamespace(
            get_page_rect=lambda _idx: fitz.Rect(0, 0, 300, 500),
        )
        x0 = view.page_x_positions[0]
        manager = view._ensure_text_selection_manager()
        manager._text_selection_page_idx = 0

        selected = manager._selection_doc_rect_to_scene(fitz.Rect(10, 20, 40, 50))
        object_center = view._ensure_object_selection_manager()._object_center_scene(
            SimpleNamespace(page_num=1, bbox=fitz.Rect(10, 20, 40, 50))
        )
        page_rect = view._get_page_scene_rect(0)
        clamped_x, _ = view._clamp_editor_pos_to_page(0.0, 20.0, 0)

        assert selected == QRectF(x0 + 10, 20, 30, 30)
        assert object_center == QPointF(x0 + 25, 35)
        assert page_rect.left() == x0
        assert clamped_x == x0
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()
