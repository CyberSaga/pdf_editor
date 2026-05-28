from __future__ import annotations

import fitz

from model.pdf_content_ops import (
    fitz_rect_to_stream_cm,
    form_rect_to_stream_cm,
    rotated_image_stream_cm,
)


def _contains_scientific_notation(tokens: list[bytes]) -> bool:
    return any(b"e" in token.lower() for token in tokens)


def test_fitz_rect_to_stream_cm_avoids_scientific_notation() -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        rect = fitz.Rect(50.0, 60.0, 50.0 + 1e-12, 60.0 + 2e-12)
        tokens = fitz_rect_to_stream_cm(rect, page, rotation=0)
        assert not _contains_scientific_notation(tokens)
    finally:
        doc.close()


def test_form_rect_to_stream_cm_avoids_scientific_notation() -> None:
    tokens = form_rect_to_stream_cm(
        destination_rect=fitz.Rect(10.0, 20.0, 10.0 + 1e-12, 20.0 + 2e-12),
        current_cm_values=(1_000_000.0, 0.0, 0.0, 1_000_000.0, 0.0, 0.0),
        current_page_bbox=fitz.Rect(0.0, 0.0, 1_000_000.0, 1_000_000.0),
        rotation=0,
    )
    assert tokens is not None
    assert not _contains_scientific_notation(tokens)


def test_rotated_image_stream_cm_zero_angle_parity() -> None:
    tokens = rotated_image_stream_cm(
        centre_x=200.0,
        centre_y_fitz=300.0,
        width=120.0,
        height=80.0,
        angle_deg=0.0,
        page_height=1000.0,
    )
    values = [float(token.decode("ascii")) for token in tokens]
    assert values == [120.0, 0.0, 0.0, 80.0, 140.0, 660.0]
