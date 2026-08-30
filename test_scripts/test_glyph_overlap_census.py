"""Task 14 P4-A glyph-overlap census tests.

The census runs at the Type0-font gate, before the main funnel's operator,
budget, and text-state early exits.  Its report is aggregate-only.
"""
from __future__ import annotations

import json

from model.text_commit.inspect import read_page_streams
from model.text_commit.replay import replay_page_streams
from scripts.measure_type0_funnel import funnel_document
from test_scripts.type0_fixture_builder import (
    append_page_content,
    build_identity_h_fixture,
    cid_for,
    write_minimal_tounicode,
    write_tounicode_cmap,
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


def _existing_show(operator_source: str):
    fixture = build_identity_h_fixture(subset=True)
    append_page_content(
        fixture,
        (
            f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 72 650 Tm "
            f"{operator_source.format(cid=cid_for('你'))} ET"
        ),
    )
    return fixture


def _descriptor_xref(fixture) -> int:
    kind, value = fixture.doc.xref_get_key(
        fixture.descendant_xref, "FontDescriptor"
    )
    assert kind == "xref"
    return int(value.split()[0])


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
    assert census["operator_x_glyph"]
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
    assert set(census["sole_loss"]) == {
        "all_gates_pass",
        "tj_array_only",
        "hscale_only",
        "tj_array_and_hscale_only",
        "other",
    }


def test_sole_loss_classifies_tj_array_only() -> None:
    fixture = _existing_show("[<{cid:04X}> -100] TJ")
    sole = funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]["sole_loss"]
    assert sole["tj_array_only"] == 1


def test_sole_loss_classifies_hscale_only() -> None:
    fixture = _existing_show("80 Tz <{cid:04X}> Tj")
    sole = funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]["sole_loss"]
    assert sole["hscale_only"] == 1


def test_sole_loss_keeps_tj_and_hscale_overlap_separate() -> None:
    fixture = _existing_show("80 Tz [<{cid:04X}> -100] TJ")
    sole = funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]["sole_loss"]
    assert sole["tj_array_and_hscale_only"] == 1
    assert sole["tj_array_only"] == 0
    assert sole["hscale_only"] == 0


def test_sole_loss_attributes_budget_plus_operator_to_other(
    monkeypatch,
) -> None:
    import scripts.measure_type0_funnel as funnel

    monkeypatch.setattr(funnel, "DEFAULT_MAX_REPLAY_BYTES", 1)
    fixture = _existing_show("[<{cid:04X}> -100] TJ")
    sole = funnel.funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]["sole_loss"]
    assert sole["tj_array_only"] == 0
    assert sole["other"] >= 1


def test_all_gates_pass_reconciles_to_source_bindable() -> None:
    fixture = build_identity_h_fixture()
    report = funnel_document(fixture.doc, run_e2e=False)
    assert (
        report["glyph_overlap_census"]["sole_loss"]["all_gates_pass"]
        == report["funnel_shows"]["source_bindable"]
        >= 1
    )


def test_malformed_partial_replay_is_ineligible_like_production() -> None:
    fixture = build_identity_h_fixture(text="你")
    append_page_content(fixture, "(unterminated")
    replay = replay_page_streams(
        read_page_streams(fixture.doc, fixture.page),
        max_decoded_bytes=None,
    )
    assert replay.shows and replay.malformed

    report = funnel_document(fixture.doc, run_e2e=False)
    assert report["funnel_shows"]["source_bindable"] == 0
    assert report["glyph_overlap_census"]["sole_loss"]["all_gates_pass"] == 0
    assert report["page_eligibility"] == {
        "replay_malformed_pages": 1,
        "replay_malformed_type0_shows": 1,
        "shared_content_stream_pages": 0,
        "shared_content_stream_type0_shows": 0,
    }


def test_shared_content_stream_show_is_ineligible_like_production() -> None:
    fixture = build_identity_h_fixture(text="你")
    other_page = fixture.doc.new_page()
    fixture.doc.xref_set_key(
        other_page.xref, "Contents", f"{fixture.content_xref} 0 R"
    )

    report = funnel_document(fixture.doc, run_e2e=False)
    assert report["funnel_shows"]["source_bindable"] == 0
    assert report["glyph_overlap_census"]["sole_loss"]["all_gates_pass"] == 0
    assert report["page_eligibility"] == {
        "replay_malformed_pages": 0,
        "replay_malformed_type0_shows": 0,
        "shared_content_stream_pages": 1,
        "shared_content_stream_type0_shows": 1,
    }


def test_unwrapped_shows_ignore_bare_emc_underflows_like_production() -> None:
    fixture = build_identity_h_fixture()
    append_page_content(
        fixture,
        (
            f"EMC BT /{fixture.resource_name} 12 Tf "
            f"1 0 0 1 72 650 Tm <{cid_for('你'):04X}> Tj ET EMC"
        ),
    )
    report = funnel_document(fixture.doc, run_e2e=False)
    assert report["funnel_shows"]["source_bindable"] == 2
    assert report["glyph_overlap_census"]["sole_loss"]["all_gates_pass"] == 2


def test_wrapped_show_refuses_bare_emc_underflow_like_production() -> None:
    from model.text_commit.dto import RejectReason
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Layer7Q", label="SecretLayer7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Layer7Q BDC")
    append_page_content(fixture, "EMC")
    report = funnel_document(fixture.doc, run_e2e=False)
    assert report["glyph_overlap_census"]["sole_loss"]["other"] == 1
    assert report["loss_reasons"][RejectReason.MC_MALFORMED_PAIRING] == 1


def test_sole_loss_reuses_preclassified_wrapper_evidence(monkeypatch) -> None:
    import scripts.measure_type0_funnel as funnel
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Layer7Q", label="SecretLayer7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Layer7Q BDC")
    calls = 0
    original = funnel.admit_show_wrappers

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(funnel, "admit_show_wrappers", counted)
    report = funnel.funnel_document(fixture.doc, run_e2e=False)
    assert report["glyph_overlap_census"]["sole_loss"]["all_gates_pass"] == 1
    assert calls == 1


def test_cid_unavailable_reason_is_counted_once_per_font() -> None:
    fixture = build_identity_h_fixture()
    write_tounicode_cmap(fixture, "not a cmap")
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["glyph_overlap_census"]
    assert census["cid_unavailable_reasons"] == {
        "type0_tounicode_unparseable": 1
    }
    assert census["operator_x_glyph"]["single_hex_tj|cid_unavailable"] == 1


def test_tounicode_unparseable_details_are_closed_and_counted() -> None:
    from scripts.measure_type0_funnel import TOUNICODE_UNPARSEABLE_DETAILS

    fixture = build_identity_h_fixture()
    write_tounicode_cmap(
        fixture,
        "1 beginbfrange <0000> <0001> [<0041> <0042>] endbfrange",
    )
    census = funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]
    assert set(census["tounicode_unparseable_details"]) <= set(
        TOUNICODE_UNPARSEABLE_DETAILS
    )
    assert census["tounicode_unparseable_details"] == {
        "array-destination bfrange is outside the v1 grammar": 1
    }

    fixture = build_identity_h_fixture()
    write_tounicode_cmap(fixture, "not a cmap")
    census = funnel_document(fixture.doc, run_e2e=False)[
        "glyph_overlap_census"
    ]
    assert census["tounicode_unparseable_details"] == {
        "no bfchar or bfrange records": 1
    }


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
    fixture.doc.xref_set_key(
        _descriptor_xref(fixture), "FontName", "/SECRET7Q+Face"
    )
    fixture.doc.xref_set_key(
        fixture.font_xref, "BaseFont", "/SECRET7Q+Face"
    )
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["glyph_overlap_census"]
    assert census["operator_x_glyph"]
    dumped = json.dumps(report)
    assert fixture.text not in dumped
    assert fixture.resource_name not in dumped
    assert "SECRET7Q" not in dumped
