"""Task 13 Priority 1 — marked-content admission red matrix.

Promotes the census taxonomy (plan §2, measured 2026-08-14: 64.2%
admissible pure-layer) into the production admission gate, red-first:

- Part A pins the four NEW stable reject codes verbatim (house rule: the
  test keeps its own literal constants; a rename in dto.py must fail here,
  never silently follow).
- Part B pins the taxonomy admissions at ``TieredCommitEngine.prepare``
  level on synthetic Identity-H fixtures: ONLY a default-visible pure
  ``/OC`` layer wrapper (every enclosing wrapper individually qualifying)
  is admitted; every other class keeps a fail-closed rejection with its
  class slug in the detail.
- Part C pins the wrapper byte-span evidence and the splice boundary
  guard (proof obligation 4): the replacement range must lie strictly
  inside every enclosing wrapper's BDC..EMC span, same stream, own code.
- Part D pins proof obligations 1 (encode round-trip identical inside vs
  outside the wrapper), 2 (save→reopen extraction equality), 3
  (render-hash equality wrapped vs unwrapped), and 5 (wrapper-evidence
  staleness → STALE_PLAN: the page fingerprint closes over the resolved
  ``/Properties`` mapping, the OCG object, and its default-config
  visibility bit).

Data policy (plan §10): fixtures are synthetic; every fixture-specific
name/label/value carries the ``7Q`` marker and rejection details must
never echo it — details speak in class slugs only.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    CJK_TEXT,
    REPLACEMENT_EQUAL_ADVANCE,
    Type0Fixture,
    _set_page_property,
    build_identity_h_fixture,
    install_oc_layer,
    install_ocmd,
    wrap_content_in_marked_content,
)

# --------------------------------------------------------------------------
# THE contract these red tests pin: one stable code per independent gate.
# --------------------------------------------------------------------------
MC_WRAPPER_NOT_PURE_LAYER = "mc_wrapper_not_pure_layer"
MC_LAYER_NOT_DEFAULT_VISIBLE = "mc_layer_not_default_visible"
MC_MALFORMED_PAIRING = "mc_malformed_pairing"
MC_SPLICE_CROSSES_WRAPPER_BOUNDARY = "mc_splice_crosses_wrapper_boundary"

_ALL_MC_CODES = (
    MC_WRAPPER_NOT_PURE_LAYER,
    MC_LAYER_NOT_DEFAULT_VISIBLE,
    MC_MALFORMED_PAIRING,
    MC_SPLICE_CROSSES_WRAPPER_BOUNDARY,
)


def _prepare(fixture: Type0Fixture) -> PreparedEdit | PlanRejection:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    return engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
    )


def _prepare_with_engine(
    fixture: Type0Fixture,
) -> tuple[TieredCommitEngine, PreparedEdit | PlanRejection]:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
    )
    return engine, result


def _install_and_wrap(
    fixture: Type0Fixture, *, name: str = "Lyr7Q", label: str = "L7Q", on: bool = True
) -> int:
    ocg_xref = install_oc_layer(fixture, name=name, label=label, on=on)
    wrap_content_in_marked_content(fixture, f"/OC /{name} BDC")
    return ocg_xref


def _assert_rejected(
    result: PreparedEdit | PlanRejection, reason: str, detail_substring: str
) -> PlanRejection:
    assert isinstance(result, PlanRejection), (
        f"expected a PlanRejection({reason}), got a PreparedEdit"
    )
    assert result.reason == reason, (result.reason, result.detail)
    assert detail_substring in result.detail, result.detail
    return result


def _assert_prepared(result: PreparedEdit | PlanRejection) -> PreparedEdit:
    assert isinstance(result, PreparedEdit), (
        f"expected a PreparedEdit, got rejection "
        f"{(result.reason, result.detail)}"
    )
    return result


# ==========================================================================
# Part A — the stable codes exist on RejectReason, verbatim
# ==========================================================================


def test_mc_reject_reason_constants_exist_verbatim() -> None:
    assert RejectReason.MC_WRAPPER_NOT_PURE_LAYER == MC_WRAPPER_NOT_PURE_LAYER
    assert (
        RejectReason.MC_LAYER_NOT_DEFAULT_VISIBLE == MC_LAYER_NOT_DEFAULT_VISIBLE
    )
    assert RejectReason.MC_MALFORMED_PAIRING == MC_MALFORMED_PAIRING
    assert (
        RejectReason.MC_SPLICE_CROSSES_WRAPPER_BOUNDARY
        == MC_SPLICE_CROSSES_WRAPPER_BOUNDARY
    )
    # Four distinct codes, and none reuses an existing emission site's code
    # (a reused code lets a test survive deletion of its own gate).
    assert len(set(_ALL_MC_CODES)) == 4
    assert RejectReason.UNSUPPORTED_TEXT_STATE not in _ALL_MC_CODES
    assert RejectReason.MALFORMED_STREAM not in _ALL_MC_CODES


# ==========================================================================
# Part B — taxonomy admissions at prepare level (plan §2)
# ==========================================================================


def test_visible_pure_oc_layer_is_admitted_and_commits() -> None:
    """The candidate class: default-visible pure /OC layer → Tier 0 plan,
    and the commit splices INSIDE the wrapper (BDC/EMC survive)."""
    fixture = build_identity_h_fixture()
    _install_and_wrap(fixture)
    engine, prepared = _prepare_with_engine(fixture)
    plan = _assert_prepared(prepared)
    outcome = engine.commit(plan)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        getattr(outcome, "reason", None),
        getattr(outcome, "detail", None),
    )
    after = fixture.content_bytes()
    assert b"BDC" in after and b"EMC" in after, "commit must not eat the wrapper"
    fixture.doc.close()


def test_wrapped_commit_save_reopen_extraction_equality() -> None:
    """Proof obligation 2: the wrapper does not change extraction
    semantics across a save→reopen round trip."""
    fixture = build_identity_h_fixture()
    _install_and_wrap(fixture)
    engine, prepared = _prepare_with_engine(fixture)
    plan = _assert_prepared(prepared)
    outcome = engine.commit(plan)
    assert outcome.status is CommitStatus.COMMITTED
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    extracted = "".join(reopened[0].get_text().split())
    assert REPLACEMENT_EQUAL_ADVANCE in extracted
    assert CJK_TEXT not in extracted
    assert reopened.get_ocgs(), "the OC layer must survive the round trip"
    reopened.close()


def test_hidden_layer_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    _install_and_wrap(fixture, on=False)
    _assert_rejected(
        _prepare(fixture), MC_LAYER_NOT_DEFAULT_VISIBLE, "oc_layer_hidden_default"
    )
    fixture.doc.close()


def test_ocmd_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    ocg_xref = fixture.doc.add_ocg("M7Q", on=True)
    install_ocmd(fixture, name="Md7Q", ocg_xrefs=[ocg_xref])
    wrap_content_in_marked_content(fixture, "/OC /Md7Q BDC")
    _assert_rejected(_prepare(fixture), MC_LAYER_NOT_DEFAULT_VISIBLE, "oc_ocmd")
    fixture.doc.close()


def test_actual_text_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(
        fixture, "/Span <</ActualText (SECRETTEXT7Q)>> BDC"
    )
    rejection = _assert_rejected(
        _prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "actual_text"
    )
    # §10: the detail speaks in class slugs, never property VALUES.
    assert "SECRETTEXT7Q" not in rejection.detail
    fixture.doc.close()


def test_alt_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/Span <</Alt (SECRETTEXT7Q)>> BDC")
    _assert_rejected(_prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "alt_text")
    fixture.doc.close()


def test_artifact_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/Artifact BMC")
    _assert_rejected(_prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "artifact")
    fixture.doc.close()


def test_struct_content_mcid_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/P <</MCID 0>> BDC")
    _assert_rejected(_prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "struct_content")
    fixture.doc.close()


def test_bare_bmc_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/P BMC")
    _assert_rejected(_prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "bmc_bare")
    fixture.doc.close()


def test_unresolvable_named_properties_are_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/OC /Missing7Q BDC")
    rejection = _assert_rejected(
        _prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "props_unresolved"
    )
    assert "Missing7Q" not in rejection.detail  # names are values too (§10)
    fixture.doc.close()


def test_unparseable_bdc_operands_are_rejected() -> None:
    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "42 BDC")
    _assert_rejected(_prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "props_unparsed")
    fixture.doc.close()


def test_nested_all_visible_layers_are_admitted() -> None:
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    install_oc_layer(fixture, name="LyrB7Q", label="B7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Lyr7Q BDC")
    wrap_content_in_marked_content(fixture, "/OC /LyrB7Q BDC")  # outer
    _assert_prepared(_prepare(fixture))
    fixture.doc.close()


def test_nested_inner_actual_text_poisons_the_stack() -> None:
    """Nested admission requires EVERY wrapper to qualify individually."""
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    wrap_content_in_marked_content(
        fixture, "/Span <</ActualText (SECRETTEXT7Q)>> BDC"
    )
    wrap_content_in_marked_content(fixture, "/OC /Lyr7Q BDC")  # outer, visible
    _assert_rejected(_prepare(fixture), MC_WRAPPER_NOT_PURE_LAYER, "actual_text")
    fixture.doc.close()


def test_unclosed_wrapper_is_rejected() -> None:
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Lyr7Q BDC", suffix="")
    _assert_rejected(_prepare(fixture), MC_MALFORMED_PAIRING, "")
    fixture.doc.close()


def test_wrapper_crossing_q_is_rejected() -> None:
    """A wrapper whose EMC closes below its opening q-depth is structurally
    unsound: the graphics state it captured is gone."""
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    wrap_content_in_marked_content(
        fixture, "q /OC /Lyr7Q BDC", suffix=" Q EMC"
    )
    _assert_rejected(_prepare(fixture), MC_MALFORMED_PAIRING, "")
    fixture.doc.close()


def test_stray_emc_poisons_wrapped_shows() -> None:
    """An EMC underflow makes the page's pairing evidence untrustworthy for
    every WRAPPED show (census decision, byte-identical here)."""
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Lyr7Q BDC", suffix=" EMC EMC")
    _assert_rejected(_prepare(fixture), MC_MALFORMED_PAIRING, "")
    fixture.doc.close()


def test_underflow_page_unwrapped_show_keeps_todays_admission() -> None:
    """CONTROL (green today, pinned so the promotion cannot widen the
    refusal): a stray EMC after an UNwrapped show never rejected under the
    blanket ``mc_depth`` clamp, and must not start rejecting now."""
    fixture = build_identity_h_fixture()
    fixture.doc.update_stream(
        fixture.content_xref, fixture.content_bytes() + b" EMC"
    )
    _assert_prepared(_prepare(fixture))
    fixture.doc.close()


# ==========================================================================
# Part C — wrapper byte-span evidence and the splice boundary guard
# (proof obligation 4)
# ==========================================================================


def test_wrapper_records_open_and_close_byte_spans() -> None:
    data = b"/OC /L7Q BDC BT (x) Tj ET EMC"
    replay = replay_page_streams([(7, data)])
    assert len(replay.mc_wrappers) == 1
    wrapper = replay.mc_wrappers[0]
    assert wrapper.open_op_end == data.index(b"BDC") + len(b"BDC")
    assert wrapper.close_stream_xref == 7
    assert wrapper.close_op_start == data.index(b"EMC")


def test_bdc_in_earlier_stream_trips_the_boundary_guard() -> None:
    """A wrapper opened in another content stream cannot bracket the splice
    range; the candidate gets the boundary code, not an admission."""
    from model.text_commit.marked_content import admit_show_wrappers

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    body = fixture.content_bytes()
    replay = replay_page_streams(
        [(101, b"/OC /Lyr7Q BDC"), (102, body + b" EMC")]
    )
    shows = [s for s in replay.shows if s.mc_stack]
    assert shows, "fixture must yield a wrapped show"
    show = shows[0]
    wrappers = tuple(replay.mc_wrappers[i] for i in show.mc_stack)
    rejection = admit_show_wrappers(
        fixture.doc,
        fixture.page,
        show,
        wrappers=wrappers,
        emc_underflows=replay.mc_emc_underflows,
    )
    assert rejection is not None
    assert rejection.reason == MC_SPLICE_CROSSES_WRAPPER_BOUNDARY, (
        rejection.reason,
        rejection.detail,
    )
    fixture.doc.close()


def test_emc_in_later_stream_trips_the_boundary_guard() -> None:
    from model.text_commit.marked_content import admit_show_wrappers

    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="A7Q", on=True)
    body = fixture.content_bytes()
    replay = replay_page_streams(
        [(101, b"/OC /Lyr7Q BDC " + body), (102, b"EMC")]
    )
    shows = [s for s in replay.shows if s.mc_stack]
    assert shows, "fixture must yield a wrapped show"
    show = shows[0]
    wrappers = tuple(replay.mc_wrappers[i] for i in show.mc_stack)
    rejection = admit_show_wrappers(
        fixture.doc,
        fixture.page,
        show,
        wrappers=wrappers,
        emc_underflows=replay.mc_emc_underflows,
    )
    assert rejection is not None
    assert rejection.reason == MC_SPLICE_CROSSES_WRAPPER_BOUNDARY
    fixture.doc.close()


def test_splice_range_guard_unit_pins() -> None:
    """Defense-in-depth: the range check itself is pinned, so deleting the
    guard (not just rerouting it) fails a test."""
    from model.text_commit.marked_content import splice_range_within_wrapper

    data = b"/OC /L7Q BDC BT (x) Tj ET EMC"
    replay = replay_page_streams([(7, data)])
    wrapper = replay.mc_wrappers[0]
    show = replay.shows[0]
    assert splice_range_within_wrapper(
        wrapper, stream_xref=show.stream_xref, start=show.op_start, end=show.op_end
    )
    assert not splice_range_within_wrapper(
        wrapper,
        stream_xref=show.stream_xref,
        start=show.op_start,
        end=wrapper.close_op_start + 1,  # would swallow the EMC
    )
    assert not splice_range_within_wrapper(
        wrapper,
        stream_xref=show.stream_xref,
        start=wrapper.open_op_end - 1,  # would bite into the BDC
        end=show.op_end,
    )
    assert not splice_range_within_wrapper(
        wrapper, stream_xref=8, start=show.op_start, end=show.op_end
    )


# ==========================================================================
# Part D — proof obligations 1, 3 and 5
# ==========================================================================


def test_encode_roundtrip_identical_inside_and_outside_wrapper() -> None:
    """Proof obligation 1: the wrapper changes neither the decoded source
    bytes nor the encoded replacement operand."""
    plain = build_identity_h_fixture()
    wrapped = build_identity_h_fixture()
    _install_and_wrap(wrapped)
    plain_plan = _assert_prepared(_prepare(plain))
    wrapped_plan = _assert_prepared(_prepare(wrapped))
    assert (
        wrapped_plan.binding.show.decoded_bytes
        == plain_plan.binding.show.decoded_bytes
    )
    assert (
        wrapped_plan.replacement.expected_bytes
        == plain_plan.replacement.expected_bytes
    )
    assert (
        wrapped_plan.replacement.replacement_bytes
        == plain_plan.replacement.replacement_bytes
    )
    plain.doc.close()
    wrapped.doc.close()


def test_render_hash_equal_wrapped_vs_unwrapped_after_commit() -> None:
    """Proof obligation 3: a default-visible pure layer wrapper is
    render-inert — the committed page rasterizes byte-identically."""

    def pixmap_digest(fixture: Type0Fixture) -> str:
        pix = fixture.page.get_pixmap()
        return hashlib.sha256(pix.samples).hexdigest()

    plain = build_identity_h_fixture()
    wrapped = build_identity_h_fixture()
    _install_and_wrap(wrapped)
    assert pixmap_digest(plain) == pixmap_digest(wrapped), (
        "fixture drift: the wrapper must be render-inert BEFORE the edit"
    )
    for fixture in (plain, wrapped):
        engine, prepared = _prepare_with_engine(fixture)
        outcome = engine.commit(_assert_prepared(prepared))
        assert outcome.status is CommitStatus.COMMITTED
    assert pixmap_digest(plain) == pixmap_digest(wrapped)
    plain.doc.close()
    wrapped.doc.close()


def test_visibility_flip_between_prepare_and_commit_is_stale() -> None:
    """Proof obligation 5a: the admission read the OCG's default-config
    visibility; flipping it afterwards must invalidate the plan."""
    fixture = build_identity_h_fixture()
    ocg_xref = _install_and_wrap(fixture)
    engine, prepared = _prepare_with_engine(fixture)
    plan = _assert_prepared(prepared)
    fixture.doc.set_layer(-1, off=[ocg_xref])
    assert fixture.doc.get_ocgs()[ocg_xref]["on"] is False, "flip did not take"
    outcome = engine.commit(plan)
    assert outcome.status is CommitStatus.STALE_PLAN, outcome.status
    fixture.doc.close()


def test_properties_repoint_between_prepare_and_commit_is_stale() -> None:
    """Proof obligation 5b: re-pointing the named /Properties entry at a
    DIFFERENT (even also-visible) OCG changes the evidence the admission
    was built on."""
    fixture = build_identity_h_fixture()
    _install_and_wrap(fixture)
    other_xref = fixture.doc.add_ocg("B7Q", on=True)
    engine, prepared = _prepare_with_engine(fixture)
    plan = _assert_prepared(prepared)
    _set_page_property(fixture, "Lyr7Q", f"{other_xref} 0 R")
    outcome = engine.commit(plan)
    assert outcome.status is CommitStatus.STALE_PLAN, outcome.status
    fixture.doc.close()


def test_ocg_object_mutation_between_prepare_and_commit_is_stale() -> None:
    """Proof obligation 5c: mutating the OCG object itself (any key) after
    prepare must go stale — the fingerprint folds the resolved object."""
    fixture = build_identity_h_fixture()
    ocg_xref = _install_and_wrap(fixture)
    engine, prepared = _prepare_with_engine(fixture)
    plan = _assert_prepared(prepared)
    fixture.doc.xref_set_key(ocg_xref, "Name", "(Renamed7Q)")
    outcome = engine.commit(plan)
    assert outcome.status is CommitStatus.STALE_PLAN, outcome.status
    fixture.doc.close()


def test_rejection_details_never_echo_fixture_names() -> None:
    """§10 sweep: every admission rejection speaks in class slugs; the
    ``7Q`` marker rides every fixture-specific name/label/value, so no
    detail may contain it."""
    details: list[str] = []

    fixture = build_identity_h_fixture()
    _install_and_wrap(fixture, on=False)
    result = _prepare(fixture)
    assert isinstance(result, PlanRejection)
    details.append(result.detail)
    fixture.doc.close()

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(
        fixture, "/Span <</ActualText (SECRETTEXT7Q)>> BDC"
    )
    result = _prepare(fixture)
    assert isinstance(result, PlanRejection)
    details.append(result.detail)
    fixture.doc.close()

    fixture = build_identity_h_fixture()
    wrap_content_in_marked_content(fixture, "/OC /Missing7Q BDC")
    result = _prepare(fixture)
    assert isinstance(result, PlanRejection)
    details.append(result.detail)
    fixture.doc.close()

    for detail in details:
        assert "7Q" not in detail, detail
    # And the sweep must be exercising the NEW gates, not the blanket
    # UNSUPPORTED_TEXT_STATE rejection this slice replaces.
    assert result.reason in _ALL_MC_CODES
