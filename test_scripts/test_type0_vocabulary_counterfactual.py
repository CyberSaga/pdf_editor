"""Task 14 P4-A replacement-vocabulary counterfactual tests."""
from __future__ import annotations

import json

from model.pdf_model import _WINDOWS_CJK_FONT_FILES
from test_scripts.type0_fixture_builder import (
    build_identity_h_fixture,
    cid_for,
    write_minimal_tounicode,
)


def _report(monkeypatch, fixture, chars, candidate_has_glyph=None):
    import scripts.measure_type0_funnel as funnel

    monkeypatch.setattr(funnel, "VOCABULARIES", {"fixture": tuple(chars)})
    return funnel.funnel_document(
        fixture.doc,
        run_e2e=False,
        candidate_has_glyph=candidate_has_glyph,
    )["vocabulary_counterfactual"]


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


def test_counterfactual_builds_one_reverse_index_instead_of_rescanning(
    monkeypatch,
) -> None:
    """The runtime corpus union can contain tens of thousands of chars."""
    from model.text_commit.cid_fonts import ToUnicodeMap

    calls = 0
    original = ToUnicodeMap.cids_for_char

    def counted(self, char):
        nonlocal calls
        calls += 1
        return original(self, char)

    monkeypatch.setattr(ToUnicodeMap, "cids_for_char", counted)
    fixture = build_identity_h_fixture()
    _report(monkeypatch, fixture, "你好")
    # The main funnel's source-reproduction / self-proxy checks may use this
    # API once per shown character.  The counterfactual must add no calls.
    assert calls <= 2 * len(fixture.text)


def test_counterfactual_report_has_closed_integer_keys_and_no_text(
    monkeypatch,
) -> None:
    from scripts.measure_type0_funnel import (
        VOCABULARY_ALL_BUCKETS,
        VOCABULARY_WEIGHTINGS,
    )

    fixture = build_identity_h_fixture(text="秘密資料", subset=True)
    report = _report(monkeypatch, fixture, "秘密資料")
    assert set(report) == {
        "fonts_evaluated",
        "font_page_references",
        "bindable_shows",
        *VOCABULARY_WEIGHTINGS,
    }
    for weighting in VOCABULARY_WEIGHTINGS:
        values = report[weighting]["fixture"]
        assert set(values) == set(VOCABULARY_ALL_BUCKETS)
        assert all(type(value) is int for value in values.values())
    dumped = json.dumps(report)
    assert fixture.text not in dumped
    assert fixture.resource_name not in dumped
    assert all(
        path.stem not in dumped
        for path in _WINDOWS_CJK_FONT_FILES.values()
    )
