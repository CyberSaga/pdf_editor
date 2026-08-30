"""Task 14 P4-A replacement-vocabulary counterfactual tests."""
from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace

from model.pdf_model import _WINDOWS_CJK_FONT_FILES
from model.text_commit.fonts import DocumentFontRegistry
from test_scripts.type0_fixture_builder import (
    append_page_content,
    build_identity_h_fixture,
    cid_for,
    write_minimal_tounicode,
    write_tounicode_cmap,
)


def _report(monkeypatch, fixture, chars, candidate_has_glyph=None):
    import scripts.measure_type0_funnel as funnel

    monkeypatch.setattr(funnel, "VOCABULARIES", {"fixture": tuple(chars)})
    return funnel.funnel_document(
        fixture.doc,
        run_e2e=False,
        candidate_has_glyph=candidate_has_glyph,
    )["vocabulary_counterfactual"]


def _cid(fixture):
    capability = DocumentFontRegistry(fixture.doc).capability(
        fixture.page, fixture.resource_name
    )
    assert capability is not None and capability.cid is not None
    return capability.cid


def _register_font_resource(fixture, name: str, font_xref: int) -> None:
    _register_page_resource(fixture, "Font", name, font_xref)


def _register_page_resource(
    fixture, category: str, name: str, xref: int
) -> None:
    doc = fixture.doc
    owner = fixture.page.xref
    kind, value = doc.xref_get_key(owner, "Resources")
    assert kind in ("dict", "xref")
    if kind == "xref":
        owner = int(value.split()[0])
    kind, value = doc.xref_get_key(owner, category)
    if kind == "xref":
        doc.xref_set_key(int(value.split()[0]), name, f"{xref} 0 R")
    elif kind == "dict":
        doc.xref_set_key(owner, f"{category}/{name}", f"{xref} 0 R")
    else:
        doc.xref_set_key(owner, category, f"<< /{name} {xref} 0 R >>")


def test_vocabularies_are_closed_nonempty_and_distinct() -> None:
    from scripts.type0_vocabulary import VOCABULARIES, VOCABULARY_NAMES

    assert tuple(VOCABULARIES) == VOCABULARY_NAMES
    assert VOCABULARY_NAMES == (
        "fullwidth_digits_punct",
        "cad_common",
        "japanese_common",
        "sip_sample",
    )
    values = list(VOCABULARIES.values())
    assert all(value and len(value) == len(set(value)) for value in values)
    assert len({value for value in values}) == len(values)
    assert all(len(char) == 1 for value in values for char in value)


def test_font_weighted_buckets_sum_to_vocab_times_fonts(
    monkeypatch,
) -> None:
    from scripts.measure_type0_funnel import VOCABULARY_BASE_BUCKETS

    fixture = build_identity_h_fixture(text="你好", subset=True)
    report = _report(monkeypatch, fixture, "你好圖")
    values = report["font_weighted"]["fixture"]
    assert sum(values[key] for key in VOCABULARY_BASE_BUCKETS) == (
        3 * report["fonts_evaluated"]
    )


def test_minimal_tounicode_pins_unmapped_and_encodable_buckets(
    monkeypatch,
) -> None:
    fixture = build_identity_h_fixture(text="你好", subset=True)
    write_minimal_tounicode(
        fixture, [(cid_for("你"), "你"), (cid_for("好"), "好")]
    )
    values = _report(monkeypatch, fixture, "你好圖")["font_weighted"][
        "fixture"
    ]
    assert values["encodable_now"] == 2
    assert values["type0_unicode_unmapped"] == 1
    assert values["after_augmentation"] == 2


def test_mapped_missing_glyph_and_candidate_upper_bound(monkeypatch) -> None:
    fixture = build_identity_h_fixture(text="你好", subset=True)
    write_minimal_tounicode(
        fixture,
        [
            (cid_for("你"), "你"),
            (cid_for("好"), "好"),
            (cid_for("圖"), "圖"),
        ],
    )
    values = _report(
        monkeypatch,
        fixture,
        "你好圖",
        candidate_has_glyph=lambda char: char == "圖",
    )["font_weighted"]["fixture"]
    assert values["encodable_now"] == 2
    assert values["type0_glyph_missing"] == 1
    assert values["candidate_could_supply"] == 1
    assert values["after_augmentation"] == 3


def test_wide_bfrange_reverse_index_matches_production(monkeypatch) -> None:
    from scripts.measure_type0_funnel import (
        _lookup_reverse_cids,
        _reverse_cid_index,
    )

    fixture = build_identity_h_fixture()
    write_tounicode_cmap(
        fixture,
        "\n".join(
            (
                "2 beginbfrange",
                "<0000> <FFFF> <0000>",
                "<0001> <0001> <005A>",
                "endbfrange",
            )
        ),
    )
    cid = _cid(fixture)
    index = _reverse_cid_index(cid)
    assert set(cid.tounicode.cids_for_char("Z")) == {1, 90}
    assert _lookup_reverse_cids(index, "Z") == {1, 90}
    for char in ("A", "Z", "你", "\uffff"):
        assert _lookup_reverse_cids(index, char) == set(
            cid.tounicode.cids_for_char(char)
        )
    values = _report(
        monkeypatch,
        fixture,
        "Z",
        candidate_has_glyph=lambda _char: True,
    )["font_weighted"]["fixture"]
    assert values["type0_tounicode_ambiguous"] == 1
    assert values["candidate_supply|type0_tounicode_ambiguous"] == 1
    assert values["candidate_could_supply"] == 0
    assert values["after_augmentation"] == 0


def test_reverse_index_matches_default_fixture_records() -> None:
    from scripts.measure_type0_funnel import (
        _lookup_reverse_cids,
        _reverse_cid_index,
    )

    cid = _cid(build_identity_h_fixture())
    index = _reverse_cid_index(cid)
    chars = {
        text
        for kind, _lo, _hi, text in cid.tounicode.records
        if kind == "char" and len(text) == 1
    }
    assert chars
    for char in chars:
        assert _lookup_reverse_cids(index, char) == set(
            cid.tounicode.cids_for_char(char)
        )


def test_corpus_union_is_not_shared_capped_across_fonts(monkeypatch) -> None:
    fixture = build_identity_h_fixture(text="你好", subset=True)
    write_minimal_tounicode(fixture, [(cid_for("你"), "你")])

    copied_font = fixture.doc.get_new_xref()
    fixture.doc.update_object(
        copied_font, fixture.doc.xref_object(fixture.font_xref)
    )
    copied_tounicode = fixture.doc.get_new_xref()
    fixture.doc.update_object(
        copied_tounicode, fixture.doc.xref_object(fixture.tounicode_xref)
    )
    fixture.doc.update_stream(
        copied_tounicode,
        fixture.doc.xref_stream(fixture.tounicode_xref),
    )
    fixture.doc.xref_set_key(
        copied_font, "ToUnicode", f"{copied_tounicode} 0 R"
    )
    write_tounicode_cmap(
        SimpleNamespace(doc=fixture.doc, tounicode_xref=copied_tounicode),
        f"1 beginbfchar\n<{cid_for('好'):04X}> <597D>\nendbfchar",
    )
    _register_font_resource(fixture, "FUnion", copied_font)
    append_page_content(
        fixture,
        (
            f"BT /FUnion 12 Tf 1 0 0 1 72 650 Tm "
            f"<{cid_for('好'):04X}> Tj ET"
        ),
    )

    report = _report(monkeypatch, fixture, "你")
    union = report["font_weighted"]["corpus_union"]
    assert report["fonts_evaluated"] == 2
    assert sum(union[key] for key in ("encodable_now", "type0_unicode_unmapped")) == 4
    assert report["corpus_union_truncated_fonts"] == 0


def test_corpus_union_reports_per_font_truncation(monkeypatch) -> None:
    fixture = build_identity_h_fixture()
    write_tounicode_cmap(
        fixture,
        "\n".join(
            (
                "2 beginbfrange",
                "<0000> <FFFF> <0000>",
                "<0001> <0001> <D800DC00>",
                "endbfrange",
            )
        ),
    )
    report = _report(monkeypatch, fixture, "Z")
    assert report["corpus_union_truncated_fonts"] == 1


def test_priority_units_use_per_font_corpus_union_rates(monkeypatch) -> None:
    fixture = build_identity_h_fixture(text="你", subset=True)
    write_minimal_tounicode(
        fixture,
        [(cid_for("你"), "你"), (cid_for("圖"), "圖")],
    )
    append_page_content(
        fixture,
        (
            f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 72 650 Tm "
            f"[<{cid_for('你'):04X}>] TJ ET "
            f"BT /{fixture.resource_name} 12 Tf 80 Tz "
            f"1 0 0 1 72 625 Tm <{cid_for('你'):04X}> Tj ET"
        ),
    )
    report = _report(
        monkeypatch,
        fixture,
        "你圖",
        candidate_has_glyph=lambda char: char == "圖",
    )
    units = report["priority_go_units"]
    assert units["unit_a_self_proxy"] == {
        "augmentation_show_equivalents": 0,
        "tj_array_show_equivalents": 1,
        "hscale_show_equivalents": 1,
    }
    assert units["unit_b_corpus_union"] == {
        "vocabulary_size": 2,
        "baseline_numerator": 1,
        "augmentation_numerator": 1,
        "tj_array_numerator": 1,
        "hscale_numerator": 1,
    }


def test_page_weighting_counts_a_shared_font_once_per_page(monkeypatch) -> None:
    fixture = build_identity_h_fixture(text="你好", subset=True)
    second = fixture.doc.new_page()
    kind, resources = fixture.doc.xref_get_key(fixture.page.xref, "Resources")
    assert kind in ("dict", "xref")
    fixture.doc.xref_set_key(second.xref, "Resources", resources)

    report = _report(monkeypatch, fixture, "你好")
    font_values = report["font_weighted"]["fixture"]
    page_values = report["page_weighted"]["fixture"]
    for key, value in font_values.items():
        assert page_values[key] == 2 * value


def test_candidate_files_stay_synchronized_with_model_css_plumbing() -> None:
    from scripts.type0_vocabulary import CANDIDATE_FONT_FILES

    assert CANDIDATE_FONT_FILES == tuple(_WINDOWS_CJK_FONT_FILES.values())


def test_counterfactual_builds_one_reverse_index_per_font(
    monkeypatch,
) -> None:
    import scripts.measure_type0_funnel as funnel

    calls = 0
    original = funnel._reverse_cid_index

    def counted(cid):
        nonlocal calls
        calls += 1
        return original(cid)

    monkeypatch.setattr(funnel, "_reverse_cid_index", counted)
    fixture = build_identity_h_fixture()
    report = _report(monkeypatch, fixture, "你好")
    assert calls == report["fonts_evaluated"]


def test_candidate_supplier_is_memoized_per_character(monkeypatch) -> None:
    fixture = build_identity_h_fixture(text="你好", subset=True)
    calls: Counter[str] = Counter()

    def candidate(char: str) -> bool:
        calls[char] += 1
        return True

    _report(monkeypatch, fixture, "你好圖", candidate)
    assert calls
    assert max(calls.values()) == 1


def test_population_skips_name_resolution_mismatch(monkeypatch) -> None:
    fixture = build_identity_h_fixture()
    copied_font = fixture.doc.get_new_xref()
    fixture.doc.update_object(
        copied_font, fixture.doc.xref_object(fixture.font_xref)
    )
    xobject = fixture.doc.get_new_xref()
    fixture.doc.update_object(
        xobject,
        (
            "<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] "
            f"/Resources << /Font << /{fixture.resource_name} "
            f"{copied_font} 0 R >> >> >>"
        ),
    )
    fixture.doc.update_stream(xobject, b"")
    _register_page_resource(fixture, "XObject", "X1", xobject)

    report = _report(monkeypatch, fixture, "你")
    assert report["font_resolution_mismatch"] == 1
    assert report["fonts_evaluated"] == 1
    assert report["fonts_with_replayed_shows"] == 1


def test_population_reports_font_resource_without_replayed_show(
    monkeypatch,
) -> None:
    fixture = build_identity_h_fixture()
    copied_font = fixture.doc.get_new_xref()
    fixture.doc.update_object(
        copied_font, fixture.doc.xref_object(fixture.font_xref)
    )
    _register_font_resource(fixture, "FUnused", copied_font)

    report = _report(monkeypatch, fixture, "你")
    assert report["fonts_evaluated"] == 2
    assert report["fonts_with_replayed_shows"] == 1
    assert report["replayed_fonts_not_in_population"] == 0
    assert report["population_fonts_without_shows"] == 1


def test_counterfactual_report_has_closed_integer_keys_and_no_text(
    monkeypatch,
) -> None:
    from scripts.measure_type0_funnel import (
        VOCABULARY_ALL_BUCKETS,
        VOCABULARY_WEIGHTINGS,
    )

    fixture = build_identity_h_fixture(text="秘密資料", subset=True)
    fixture.doc.xref_set_key(fixture.font_xref, "BaseFont", "/SECRET7Q+Face")
    report = _report(monkeypatch, fixture, "秘密資料")
    assert set(report) == {
        "fonts_evaluated",
        "fonts_with_replayed_shows",
        "replayed_fonts_not_in_population",
        "population_fonts_without_shows",
        "font_resolution_mismatch",
        "font_page_references",
        "bindable_shows",
        "corpus_union_truncated_fonts",
        "priority_go_units",
        *VOCABULARY_WEIGHTINGS,
    }
    for weighting in VOCABULARY_WEIGHTINGS:
        values = report[weighting]["fixture"]
        assert set(values) == set(VOCABULARY_ALL_BUCKETS)
        assert all(type(value) is int for value in values.values())
    dumped = json.dumps(report)
    assert fixture.text not in dumped
    assert fixture.resource_name not in dumped
    assert "SECRET7Q" not in dumped
    assert all(
        path.stem not in dumped
        for path in _WINDOWS_CJK_FONT_FILES.values()
    )
