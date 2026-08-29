"""Task 14 P4-A glyph-overlap census tests.

The census runs at the Type0-font gate, before the main funnel's operator,
budget, and text-state early exits.  Its report is aggregate-only.
"""
from __future__ import annotations

import json

from scripts.measure_type0_funnel import funnel_document
from test_scripts.type0_fixture_builder import (
    append_page_content,
    build_identity_h_fixture,
    cid_for,
    write_minimal_tounicode,
)


def _missing_show(operator_source: str):
    fixture = build_identity_h_fixture(subset=True)
    missing_cid = cid_for("圖")
    append_page_content(
        fixture,
        (
            f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 72 650 Tm "
            f"{operator_source.format(cid=missing_cid)} ET"
        ),
    )
    return fixture


def test_report_has_closed_slug_keyed_integer_axes() -> None:
    from scripts.measure_type0_funnel import (
        GLYPH_OVERLAP_HSCALE_CLASSES,
        GLYPH_OVERLAP_OPERATOR_CLASSES,
        GLYPH_OVERLAP_REACH_CLASSES,
        GLYPH_OVERLAP_VERDICTS,
    )

    fixture = build_identity_h_fixture()
    census = funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]
    axes = (
        (
            census["operator_x_glyph"],
            set(GLYPH_OVERLAP_OPERATOR_CLASSES),
            set(GLYPH_OVERLAP_VERDICTS),
        ),
        (
            census["hscale_x_glyph"],
            set(GLYPH_OVERLAP_HSCALE_CLASSES),
            set(GLYPH_OVERLAP_VERDICTS),
        ),
    )
    for values, left_slugs, right_slugs in axes:
        for key, value in values.items():
            left, right = key.split("|")
            assert left in left_slugs
            assert right in right_slugs
            assert type(value) is int
    assert set(census["font_glyph_reach"]) <= set(
        GLYPH_OVERLAP_REACH_CLASSES
    )
    assert all(
        type(value) is int
        for value in census["font_glyph_reach"].values()
    )


def test_tj_array_missing_glyph_survives_main_fold_operator_loss() -> None:
    fixture = _missing_show("[<{cid:04X}> -100] TJ")
    report = funnel_document(fixture.doc, run_e2e=False)
    assert (
        report["glyph_overlap_census"]["operator_x_glyph"][
            "tj_array|type0_glyph_missing"
        ]
        == 1
    )
    assert report["loss_reasons"]["not_single_hex_tj"] >= 1


def test_non_default_hscale_missing_glyph_survives_state_loss() -> None:
    fixture = _missing_show("80 Tz <{cid:04X}> Tj")
    report = funnel_document(fixture.doc, run_e2e=False)
    assert (
        report["glyph_overlap_census"]["hscale_x_glyph"][
            "hscale_non_default|type0_glyph_missing"
        ]
        == 1
    )
    assert report["loss_reasons"]["state:hscale"] >= 1


def test_single_hex_missing_glyph_matches_main_fold_loss() -> None:
    fixture = _missing_show("<{cid:04X}> Tj")
    report = funnel_document(fixture.doc, run_e2e=False)
    overlap = report["glyph_overlap_census"]["operator_x_glyph"]
    assert (
        overlap["single_hex_tj|type0_glyph_missing"]
        == report["loss_reasons"]["type0_glyph_missing"]
    )


def test_font_reach_separates_unmapped_glyphs_and_mapped_missing_glyphs() -> None:
    full = build_identity_h_fixture(subset=False)
    full_reach = funnel_document(full.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]["font_glyph_reach"]
    assert full_reach["glyph_present_no_tounicode_cid"] > 0

    subset = build_identity_h_fixture(text="你", subset=True)
    write_minimal_tounicode(
        subset,
        [(cid_for("你"), "你"), (cid_for("圖"), "圖")],
    )
    subset_reach = funnel_document(subset.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]["font_glyph_reach"]
    assert subset_reach["tounicode_cid_without_glyph"] == 1


def test_operator_axis_reconciles_to_all_type0_shows() -> None:
    fixture = _missing_show("[<{cid:04X}> -100] TJ")
    report = funnel_document(fixture.doc, run_e2e=False)
    assert sum(
        report["glyph_overlap_census"]["operator_x_glyph"].values()
    ) == report["funnel_shows"]["on_type0_font"]


def test_report_never_contains_document_text_or_resource_names() -> None:
    fixture = build_identity_h_fixture(text="秘密資料", subset=True)
    dumped = json.dumps(funnel_document(fixture.doc, run_e2e=False))
    assert fixture.text not in dumped
    assert fixture.resource_name not in dumped
