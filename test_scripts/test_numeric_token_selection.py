from __future__ import annotations

from unittest.mock import MagicMock

import fitz
import pytest
from PySide6.QtCore import QPointF

from model.pdf_model import PDFModel
from view.pdf_view import PDFView
from view.text_selection import numeric_token_bounds


@pytest.mark.parametrize(
    ("text", "index", "expected"),
    [
        ("123456", 2, (0, 6)),
        ("123.45", 4, (0, 6)),
        ("A-123.45", 4, (1, 8)),
        ("2026/07/02", 6, (0, 10)),
        ("ABC123DEF", 4, (3, 6)),
        ("1,234.56", 5, (0, 8)),
        ("-42", 2, (0, 3)),
        ("123.", 1, (0, 3)),
        ("ABC", 1, None),
        ("12/", 2, (0, 2)),
    ],
)
def test_numeric_token_bounds(text: str, index: int, expected) -> None:
    assert numeric_token_bounds(text, index) == expected


def _make_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((30, 80), "A-123.45 ABC", fontsize=18, fontname="helv")
    doc.save(path)
    doc.close()


def test_model_character_context_resolves_strict_hit(tmp_path) -> None:
    path = tmp_path / "numeric.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        run = model.block_manager.get_runs(0)[0]
        chars = model.get_chars_in_run(1, run.span_id)
        digit_index = next(i for i, (glyph, _rect) in enumerate(chars) if glyph == "3")
        rect = chars[digit_index][1]
        point = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)

        context = model.get_char_context_at_point(1, point)

        assert context is not None
        text, hit_index, rects = context
        assert text == "".join(glyph for glyph, _rect in chars)
        assert hit_index == digit_index
        assert rects[hit_index] == rect
        assert model.get_char_context_at_point(1, fitz.Point(350, 180)) is None
    finally:
        model.close()


def test_numeric_double_click_reuses_existing_selection_and_copy_state(qapp) -> None:
    view = PDFView()
    view.show()
    try:
        view.initialize_continuous_placeholders(
            [(300.0, 500.0), (600.0, 400.0)],
            1.0,
        )
        rects = [fitz.Rect(10 + i * 8, 20, 18 + i * 8, 36) for i in range(8)]
        controller = MagicMock()
        controller.get_char_context_at_point.return_value = (
            "A-123.45",
            4,
            rects,
        )
        controller.get_text_info_at_point.return_value = None
        view.controller = controller
        scene_pos = QPointF(view.page_x_positions[0] + 42, 28)

        assert view._select_numeric_token_at_scene_pos(scene_pos) is True

        manager = view._ensure_text_selection_manager()
        assert manager._selected_text_cached == "-123.45"
        assert manager._selected_text_page_idx == 0
        assert manager._selected_text_rect_doc == fitz.Rect(18, 20, 74, 36)
        assert view._copy_selected_text_to_clipboard() is True
        assert qapp.clipboard().text() == "-123.45"
        assert manager._text_selection_rect_item is not None
        assert manager._text_selection_rect_item.rect().left() == view.page_x_positions[0] + 18
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_nonnumeric_double_click_is_not_consumed(qapp) -> None:
    view = PDFView()
    try:
        view.initialize_continuous_placeholders([(300.0, 500.0)], 1.0)
        controller = MagicMock()
        controller.get_char_context_at_point.return_value = (
            "ABC",
            1,
            [fitz.Rect(10, 20, 18, 36), fitz.Rect(18, 20, 26, 36), fitz.Rect(26, 20, 34, 36)],
        )
        view.controller = controller

        assert view._select_numeric_token_at_scene_pos(QPointF(20, 28)) is False
        assert view._ensure_text_selection_manager()._selected_text_cached == ""
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()
