from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class EditTextRequest:
    page: int
    rect: fitz.Rect
    new_text: str
    font: str
    size: float
    color: tuple
    original_text: str | None = None
    vertical_shift_left: bool = True
    new_rect: fitz.Rect | None = None
    target_span_id: str | None = None
    target_mode: str | None = None

    def to_legacy_args(self) -> tuple:
        return (
            self.page,
            self.rect,
            self.new_text,
            self.font,
            self.size,
            self.color,
            self.original_text,
            self.vertical_shift_left,
            self.new_rect,
            self.target_span_id,
            self.target_mode,
        )


@dataclass(frozen=True)
class MoveTextRequest:
    source_page: int
    source_rect: fitz.Rect
    destination_page: int
    destination_rect: fitz.Rect
    new_text: str
    font: str
    size: float
    color: tuple
    original_text: str | None = None
    target_span_id: str | None = None
    target_mode: str | None = None
