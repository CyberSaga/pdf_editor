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

    # Defensive; Enum values above should be exhaustive.
    raise ValueError(f"Unknown color profile: {profile!r}")

