from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    FitZColorspace = fitz.Colorspace


class ColorProfile(str, Enum):
    SRGB = "srgb"
    GRAY = "gray"
    CMYK = "cmyk"

    @classmethod
    def from_string(cls, value: str) -> ColorProfile:
        normalized = value.strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"Unknown color profile: {value!r}") from exc


def to_fitz_colorspace(profile: ColorProfile | str) -> FitZColorspace:
    if isinstance(profile, str):
        profile = ColorProfile.from_string(profile)

    if profile is ColorProfile.SRGB:
        return fitz.csRGB
    if profile is ColorProfile.GRAY:
        return fitz.csGRAY
    if profile is ColorProfile.CMYK:
        return fitz.csCMYK

    raise ValueError(f"Unknown color profile: {profile!r}")


def safe_to_fitz_colorspace(
    profile: ColorProfile | str | None,
    default: FitZColorspace = fitz.csRGB,
) -> FitZColorspace:
    """Like to_fitz_colorspace, but returns ``default`` for unknown/empty values."""
    if not profile:
        return default
    try:
        return to_fitz_colorspace(profile)
    except ValueError:
        return default

