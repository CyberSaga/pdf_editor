from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class StyleOverrides:
    """Style fields the user *explicitly* touched during an edit session.

    A field is non-None only when the user operated that control; merely
    opening the editor never populates anything.  This is how the model
    distinguishes "user typed text" from "user restyled" — with an empty
    overrides object, style truth stays with the source spans and no
    substitute font/size/color may silently replace them.
    """

    font_family: str | None = None
    font_size: float | None = None
    color: tuple[float, float, float] | None = None

    @property
    def changed(self) -> bool:
        return any(
            value is not None
            for value in (self.font_family, self.font_size, self.color)
        )


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
    style_overrides: StyleOverrides | None = None
    plan_token: str | None = None

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
