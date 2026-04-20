from __future__ import annotations

import fitz
import pytest

from model.color_profile import ColorProfile, to_fitz_colorspace


def test_to_fitz_colorspace_maps_expected_profiles() -> None:
    assert to_fitz_colorspace(ColorProfile.SRGB) is fitz.csRGB
    assert to_fitz_colorspace(ColorProfile.GRAY) is fitz.csGRAY
    assert to_fitz_colorspace(ColorProfile.CMYK) is fitz.csCMYK


def test_color_profile_from_string_round_trips() -> None:
    assert ColorProfile.from_string("srgb") is ColorProfile.SRGB
    assert ColorProfile.from_string("gray") is ColorProfile.GRAY
    assert ColorProfile.from_string("cmyk") is ColorProfile.CMYK


def test_unknown_profile_raises_value_error() -> None:
    with pytest.raises(ValueError):
        ColorProfile.from_string("nope")

    with pytest.raises(ValueError):
        to_fitz_colorspace("nope")

