"""Task 14 PDF-value serializer round-trip regressions."""
from __future__ import annotations

import math

import fitz
import pytest

from model.text_commit.cid_fonts import (
    PdfParseError,
    PdfRef,
    canonical_pdf_text,
    parse_pdf_value,
    serialize_pdf_value,
)
from test_scripts.type0_fixture_builder import (
    build_identity_h_fixture,
    inline_descendant,
)


def _leaf_types(value: object) -> object:
    if isinstance(value, dict):
        return {key: _leaf_types(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_leaf_types(item) for item in value]
    return type(value)


@pytest.mark.parametrize("inline", [False, True])
def test_fixture_descendant_round_trips_for_both_storage_forms(inline: bool) -> None:
    fixture = build_identity_h_fixture()
    if inline:
        inline_descendant(fixture)
    _, serialized = fixture.doc.xref_get_key(
        fixture.font_xref, "DescendantFonts"
    )
    parsed = parse_pdf_value(serialized)
    reparsed = parse_pdf_value(serialize_pdf_value(parsed))
    assert reparsed == parsed
    assert _leaf_types(reparsed) == _leaf_types(parsed)


def test_nested_values_round_trip_with_leaf_types_preserved() -> None:
    value = {
        "Type": "/CIDFontType2",
        "Ref": PdfRef(17),
        "Nested": [b"()\\", True, False, None, -3, 2.0, 0.00001],
    }
    serialized = serialize_pdf_value(value)
    assert "1e-05" not in serialized.lower()
    assert "0.00001" in serialized
    assert "2.0" in serialized
    assert "." in serialized
    parsed = parse_pdf_value(serialized)
    assert parsed == value
    assert _leaf_types(parsed) == _leaf_types(value)


@pytest.mark.parametrize(
    "value",
    [
        "plain string",
        "/bad name",
        "/bad[",
        {"bad key": 1},
        {"bad/": 1},
        math.nan,
        math.inf,
        -math.inf,
        object(),
    ],
)
def test_invalid_values_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        serialize_pdf_value(value)


def test_bytes_use_hex_because_literal_strings_are_not_unescaped() -> None:
    literal = parse_pdf_value(r"(a\)b)")
    assert literal == b"a\\)b"
    serialized = serialize_pdf_value(literal)
    assert serialized == "<615C2962>"
    assert parse_pdf_value(serialized) == literal


def test_mupdf_readback_preserves_nested_values_and_delimiter_bytes() -> None:
    doc = fitz.open()
    xref = doc.get_new_xref()
    value = {
        "Name": "/Fixture",
        "Ref": PdfRef(1),
        "Values": [3, 4, b"()\\"],
    }
    doc.update_object(xref, serialize_pdf_value(value))
    parsed = parse_pdf_value(doc.xref_object(xref))
    assert parsed["Name"] == value["Name"]
    assert parsed["Ref"] == value["Ref"]
    assert parsed["Values"][:2] == value["Values"][:2]
    assert parsed["Values"][2] == b"\\(\\)\\\\"
    assert parsed["Values"][2] != value["Values"][2]


def test_canonical_digest_text_is_not_pdf_object_syntax() -> None:
    canonical = canonical_pdf_text(PdfRef(7))
    with pytest.raises(PdfParseError):
        parse_pdf_value(canonical)
