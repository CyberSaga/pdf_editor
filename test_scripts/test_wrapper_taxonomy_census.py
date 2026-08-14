"""Red-light tests for the Task 13 Priority-1 wrapper-taxonomy census.

Census-before-code (P0-D discipline): BEFORE any marked-content admission
logic exists, replay must capture per-show wrapper EVIDENCE (BDC/BMC/EMC
stack with tags, property operands, pairing and q/Q-crossing flags), and a
script-layer classifier must taxonomize wrappers into the plan §2 classes
so `scripts/measure_type0_funnel.py` can report the admissible pure-layer
share as aggregate slugs only.

Three layers, matching the implementation split:

- Part A — `model.text_commit.replay` wrapper-evidence capture (pure byte
  streams; no admission logic, ``mc_depth`` semantics untouched);
- Part B — `scripts.wrapper_taxonomy` classifier over synthetic documents
  (OCG visible/hidden, OCMD, ActualText, Alt, Artifact, nested, missing
  properties, malformed pairing);
- Part C — funnel integration: `mc_census` aggregate block, legacy stages
  unchanged, and the §10 data-policy pin (no document-derived strings in
  the report).

Part B/C import their new symbols inside the tests so Part A failures stay
individually visible during the red run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.replay import replay_page_streams  # noqa: E402

from test_scripts.type0_fixture_builder import build_identity_h_fixture  # noqa: E402


def _replay_one(stream: bytes, xref: int = 5):
    return replay_page_streams([(xref, stream)])


# ------------------------------------------------- Part A: replay evidence


def test_bdc_named_props_wrapper_recorded():
    stream = b"/OC /P0 BDC BT /F1 12 Tf (x) Tj ET EMC BT /F1 12 Tf (y) Tj ET"
    replay = _replay_one(stream)
    assert not replay.malformed
    assert len(replay.mc_wrappers) == 1
    wrapper = replay.mc_wrappers[0]
    assert wrapper.wrapper_id == 0
    assert wrapper.operator == "BDC"
    assert wrapper.tag == "OC"
    assert wrapper.props_kind == "name"
    assert wrapper.props_name == "P0"
    assert wrapper.stream_xref == 5
    assert wrapper.closed
    assert not wrapper.crossed_q
    inside, outside = replay.shows
    assert inside.mc_stack == (0,)
    assert inside.mc_depth == 1
    assert outside.mc_stack == ()
    assert outside.mc_depth == 0


def test_bmc_bare_wrapper_recorded():
    stream = b"/P BMC BT /F1 12 Tf (x) Tj ET EMC"
    replay = _replay_one(stream)
    wrapper = replay.mc_wrappers[0]
    assert wrapper.operator == "BMC"
    assert wrapper.tag == "P"
    assert wrapper.props_kind == "none"
    assert wrapper.props_name is None
    assert replay.shows[0].mc_stack == (0,)


def test_nested_wrapper_stack_outermost_first():
    stream = (
        b"/OC /P0 BDC "
        b"BT /F1 12 Tf (a) Tj "
        b"/Span <</Foo 1>> BDC (b) Tj EMC "
        b"(c) Tj ET EMC"
    )
    replay = _replay_one(stream)
    assert len(replay.mc_wrappers) == 2
    outer, inner = replay.mc_wrappers
    assert outer.tag == "OC" and inner.tag == "Span"
    a_show, b_show, c_show = replay.shows
    assert a_show.mc_stack == (0,)
    assert b_show.mc_stack == (0, 1)
    assert c_show.mc_stack == (0,)


def test_inline_dict_top_level_keys_only():
    stream = (
        b"/Span <</ActualText (SECRETTEXT7Q) /Nested <</Bar 1>> "
        b"/Arr [1 2 3]>> BDC BT /F1 12 Tf (x) Tj ET EMC"
    )
    replay = _replay_one(stream)
    assert not replay.malformed
    wrapper = replay.mc_wrappers[0]
    assert wrapper.props_kind == "dict"
    assert wrapper.props_dict_keys == ("ActualText", "Nested", "Arr")
    # Data policy: evidence carries structural KEYS only — never values.
    assert "SECRETTEXT7Q" not in repr(wrapper)


def test_unclosed_wrapper_not_closed():
    stream = b"/OC /P0 BDC BT /F1 12 Tf (x) Tj ET"
    replay = _replay_one(stream)
    wrapper = replay.mc_wrappers[0]
    assert not wrapper.closed
    assert replay.shows[0].mc_stack == (0,)


def test_emc_underflow_counted_and_depth_clamp_unchanged():
    stream = b"EMC BT /F1 12 Tf (x) Tj ET"
    replay = _replay_one(stream)
    assert replay.mc_emc_underflows == 1
    assert replay.mc_wrappers == ()
    show = replay.shows[0]
    assert show.mc_depth == 0  # existing clamp semantics must not change
    assert show.mc_stack == ()


def test_wrapper_crossing_q_pop_marks_crossed():
    stream = b"q /OC /P0 BDC Q BT /F1 12 Tf (x) Tj ET EMC"
    replay = _replay_one(stream)
    wrapper = replay.mc_wrappers[0]
    assert wrapper.open_gs_depth == 1
    assert wrapper.crossed_q
    assert replay.shows[0].mc_stack == (0,)


def test_wrapper_closed_at_deeper_gs_depth_marks_crossed():
    stream = b"/OC /P0 BDC q BT /F1 12 Tf (x) Tj ET EMC Q"
    replay = _replay_one(stream)
    wrapper = replay.mc_wrappers[0]
    assert wrapper.open_gs_depth == 0
    assert wrapper.closed
    assert wrapper.crossed_q


def test_wrapper_fully_inside_q_is_not_crossed():
    stream = b"q /OC /P0 BDC BT /F1 12 Tf (x) Tj ET EMC Q"
    replay = _replay_one(stream)
    wrapper = replay.mc_wrappers[0]
    assert wrapper.closed
    assert not wrapper.crossed_q


def test_wrapper_spans_stream_boundary():
    streams = [
        (11, b"/OC /P0 BDC"),
        (12, b"BT /F1 12 Tf (x) Tj ET EMC"),
    ]
    replay = replay_page_streams(streams)
    wrapper = replay.mc_wrappers[0]
    assert wrapper.stream_xref == 11
    assert wrapper.closed
    assert not wrapper.crossed_q
    assert replay.shows[0].mc_stack == (0,)


def test_bdc_operand_garbage_is_unparsed_never_malformed():
    stream = b"42 BDC BT /F1 12 Tf (x) Tj ET EMC"
    replay = _replay_one(stream)
    assert not replay.malformed  # BDC has never set malformed; keep that
    wrapper = replay.mc_wrappers[0]
    assert wrapper.tag is None
    assert wrapper.props_kind == "unparsed"
    assert replay.shows[0].mc_stack == (0,)
    assert replay.shows[0].mc_depth == 1


def test_bdc_with_garbage_before_valid_pair_is_unparsed():
    """Codex review pin: a valid-LOOKING trailing pair must not rescue a
    BDC whose operand list is not exactly ``/Tag /Name`` — fail-closed."""
    stream = b"42 /OC /P0 BDC BT /F1 12 Tf (x) Tj ET EMC"
    replay = _replay_one(stream)
    assert not replay.malformed
    wrapper = replay.mc_wrappers[0]
    assert wrapper.props_kind == "unparsed"
    assert wrapper.tag is None
    assert wrapper.props_name is None


def test_bmc_with_garbage_operands_is_unparsed():
    stream = b"42 /P BMC BT /F1 12 Tf (x) Tj ET EMC"
    replay = _replay_one(stream)
    assert not replay.malformed
    assert replay.mc_wrappers[0].props_kind == "unparsed"


def test_bdc_with_garbage_before_inline_dict_is_unparsed():
    stream = b"42 /Span <</Foo 1>> BDC BT /F1 12 Tf (x) Tj ET EMC"
    replay = _replay_one(stream)
    assert not replay.malformed
    assert replay.mc_wrappers[0].props_kind == "unparsed"
    assert replay.mc_wrappers[0].props_dict_keys == ()


def test_inline_dict_keyword_values_keep_keys():
    """Codex review pin: bare ``true``/``false``/``null`` are object
    VALUES inside an inline property dict, not graphics operators — they
    must not clear the operand list and lose the dict's keys."""
    stream = (
        b"/Span <</ActualText null /Hidden true /Shown false>> BDC "
        b"BT /F1 12 Tf (x) Tj ET EMC"
    )
    replay = _replay_one(stream)
    assert not replay.malformed
    wrapper = replay.mc_wrappers[0]
    assert wrapper.props_kind == "dict"
    assert wrapper.props_dict_keys == ("ActualText", "Hidden", "Shown")


# --------------------------------------------- Part B: taxonomy classifier
#
# Fixture-builder helpers under test (to be added to type0_fixture_builder):
#   install_oc_layer(fixture, *, name, label, on) -> ocg_xref
#   install_ocmd(fixture, *, name, ocg_xrefs) -> ocmd_xref
#   wrap_content_in_marked_content(fixture, prelude, suffix=" EMC")


def _classify(fixture):
    from scripts.wrapper_taxonomy import classify_wrappers

    from model.text_commit.inspect import read_page_streams

    page = fixture.page
    replay = replay_page_streams(
        read_page_streams(fixture.doc, page), max_decoded_bytes=None
    )
    return replay, classify_wrappers(fixture.doc, page, replay)


def test_oc_ocg_visible_default_is_admissible():
    from scripts.wrapper_taxonomy import (
        VERDICT_ADMISSIBLE,
        show_verdict,
    )
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrRes7Q", label="SecretLayer7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /LyrRes7Q BDC")
    replay, classes = _classify(fixture)
    assert classes == {0: "oc_layer_visible_default"}
    assert show_verdict(replay.shows[0], classes, replay) == VERDICT_ADMISSIBLE


def test_oc_ocg_hidden_default_is_out():
    from scripts.wrapper_taxonomy import show_verdict
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrRes7Q", label="SecretLayer7Q", on=False)
    wrap_content_in_marked_content(fixture, "/OC /LyrRes7Q BDC")
    replay, classes = _classify(fixture)
    assert classes == {0: "oc_layer_hidden_default"}
    verdict = show_verdict(replay.shows[0], classes, replay)
    assert verdict == "mc:oc_layer_hidden_default"


def test_oc_ocmd_is_bucketed_not_admissible():
    from scripts.wrapper_taxonomy import show_verdict
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        install_ocmd,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    ocg = install_oc_layer(fixture, name="LyrA7Q", label="SecretLayer7Q", on=True)
    install_ocmd(fixture, name="Md7Q", ocg_xrefs=[ocg])
    wrap_content_in_marked_content(fixture, "/OC /Md7Q BDC")
    replay, classes = _classify(fixture)
    assert classes == {0: "oc_ocmd"}
    assert show_verdict(replay.shows[0], classes, replay) == "mc:oc_ocmd"


def test_actual_text_is_out():
    from scripts.wrapper_taxonomy import show_verdict
    from test_scripts.type0_fixture_builder import wrap_content_in_marked_content

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(
        fixture, "/Span <</ActualText (SECRETTEXT7Q)>> BDC"
    )
    replay, classes = _classify(fixture)
    assert classes == {0: "actual_text"}
    assert show_verdict(replay.shows[0], classes, replay) == "mc:actual_text"


def test_alt_is_out():
    from test_scripts.type0_fixture_builder import wrap_content_in_marked_content

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/Span <</Alt (SECRETTEXT7Q)>> BDC")
    _, classes = _classify(fixture)
    assert classes == {0: "alt_text"}


def test_artifact_is_out():
    from test_scripts.type0_fixture_builder import wrap_content_in_marked_content

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(
        fixture, "/Artifact <</Type /Pagination>> BDC"
    )
    _, classes = _classify(fixture)
    assert classes == {0: "artifact"}


def test_mcid_struct_content_is_bucketed():
    from test_scripts.type0_fixture_builder import wrap_content_in_marked_content

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/P <</MCID 0>> BDC")
    _, classes = _classify(fixture)
    assert classes == {0: "struct_content"}


def test_bmc_bare_is_bucketed():
    from test_scripts.type0_fixture_builder import wrap_content_in_marked_content

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/P BMC")
    _, classes = _classify(fixture)
    assert classes == {0: "bmc_bare"}


def test_named_props_missing_from_resources_is_unresolved():
    from test_scripts.type0_fixture_builder import wrap_content_in_marked_content

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/OC /Missing7Q BDC")
    _, classes = _classify(fixture)
    assert classes == {0: "props_unresolved"}


def test_nested_every_wrapper_must_qualify():
    from scripts.wrapper_taxonomy import (
        VERDICT_ADMISSIBLE,
        show_verdict,
    )
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrA7Q", label="SecretLayer7Q", on=True)
    install_oc_layer(fixture, name="LyrB7Q", label="SecretLayerB7Q", on=True)
    # inner admissible layer inside outer admissible layer -> admissible
    wrap_content_in_marked_content(fixture, "/OC /LyrB7Q BDC")
    wrap_content_in_marked_content(fixture, "/OC /LyrA7Q BDC")
    replay, classes = _classify(fixture)
    assert set(classes.values()) == {"oc_layer_visible_default"}
    assert show_verdict(replay.shows[0], classes, replay) == VERDICT_ADMISSIBLE

    # one ActualText anywhere in the stack poisons the show
    fixture2 = build_identity_h_fixture()
    install_oc_layer(fixture2, name="LyrA7Q", label="SecretLayer7Q", on=True)
    wrap_content_in_marked_content(
        fixture2, "/Span <</ActualText (SECRETTEXT7Q)>> BDC"
    )
    wrap_content_in_marked_content(fixture2, "/OC /LyrA7Q BDC")
    replay2, classes2 = _classify(fixture2)
    verdict = show_verdict(replay2.shows[0], classes2, replay2)
    assert verdict == "mc:actual_text"


def test_crossing_wrapper_is_malformed_pairing():
    from scripts.wrapper_taxonomy import show_verdict
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrRes7Q", label="SecretLayer7Q", on=True)
    # BDC q ... EMC Q -> the wrapper closes at a deeper gs depth: crossed
    wrap_content_in_marked_content(
        fixture, "/OC /LyrRes7Q BDC q", suffix=" EMC Q"
    )
    replay, classes = _classify(fixture)
    assert classes == {0: "malformed_pairing"}
    verdict = show_verdict(replay.shows[0], classes, replay)
    assert verdict == "mc:malformed_pairing"


def test_emc_underflow_poisons_page_verdicts():
    from scripts.wrapper_taxonomy import show_verdict
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrRes7Q", label="SecretLayer7Q", on=True)
    # stray leading EMC, then an otherwise-clean admissible wrapper
    wrap_content_in_marked_content(
        fixture, "EMC /OC /LyrRes7Q BDC"
    )
    replay, classes = _classify(fixture)
    assert replay.mc_emc_underflows == 1
    verdict = show_verdict(replay.shows[0], classes, replay)
    assert verdict == "mc:malformed_pairing"


# ------------------------------------------------ Part C: funnel wiring


def test_funnel_reports_mc_census_aggregates():
    from scripts.measure_type0_funnel import funnel_document
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrRes7Q", label="SecretLayer7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /LyrRes7Q BDC")
    report = funnel_document(fixture.doc, run_e2e=False)

    # Task 13 step 2: the funnel gate mirrors the production admission, so
    # an admissible pure-layer show now SURVIVES the marked-content stage
    # (stage name unchanged; the blanket state:marked_content_wrapper loss
    # slug is retired with the blanket gate).
    assert report["funnel_shows"]["single_hex_tj"] == 1
    assert report["funnel_shows"]["outside_marked_content"] == 1
    assert "state:marked_content_wrapper" not in report["loss_reasons"]

    census = report["mc_census"]
    assert census["wrapper_classes"] == {"oc_layer_visible_default": 1}
    assert census["show_verdicts"] == {"admissible_pure_layer": 1}
    assert census["char_verdicts"] == {
        "admissible_pure_layer": len(fixture.text)
    }
    assert census["stack_depth"] == {"1": 1}
    # the unlock predictor: admissible AND uniform-Tm AND default state
    assert census["overlap"] == {"admissible_uniform_trm_default_state": 1}


def test_funnel_mc_census_empty_when_nothing_wrapped():
    from scripts.measure_type0_funnel import funnel_document

    fixture = build_identity_h_fixture()
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["mc_census"]
    assert census["wrapper_classes"] == {}
    assert census["show_verdicts"] == {}
    assert census["stack_depth"] == {}


def test_funnel_output_carries_no_document_strings():
    """Plan §10 pin: the census report must stay aggregate-only."""
    from scripts.measure_type0_funnel import funnel_document
    from test_scripts.type0_fixture_builder import (
        install_oc_layer,
        wrap_content_in_marked_content,
    )

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="LyrRes7Q", label="SecretLayer7Q", on=True)
    wrap_content_in_marked_content(
        fixture, "/Span <</ActualText (SECRETTEXT7Q)>> BDC"
    )
    wrap_content_in_marked_content(fixture, "/OC /LyrRes7Q BDC")
    dumped = json.dumps(funnel_document(fixture.doc, run_e2e=False))
    assert "SECRETTEXT7Q" not in dumped  # ActualText value
    assert "SecretLayer7Q" not in dumped  # OCG layer label
    assert "LyrRes7Q" not in dumped  # properties resource name
    assert fixture.text not in dumped  # shown text


def test_fixture_builder_installs_real_default_config_ocg():
    """The OCG fixtures must be real: present in /OCProperties with the
    requested default-config visibility, and reachable from the page's
    /Resources /Properties under the requested name."""
    from test_scripts.type0_fixture_builder import install_oc_layer

    fixture = build_identity_h_fixture()
    xref = install_oc_layer(
        fixture, name="LyrRes7Q", label="SecretLayer7Q", on=False
    )
    ocgs = fixture.doc.get_ocgs()
    assert xref in ocgs
    assert ocgs[xref]["on"] is False
    kind, value = fixture.doc.xref_get_key(
        fixture.page.xref, "Resources/Properties/LyrRes7Q"
    )
    assert kind == "xref"
    assert int(value.split()[0]) == xref
