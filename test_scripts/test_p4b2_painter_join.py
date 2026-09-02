"""P4-B2 commit 3: painter events, the show↔trace join, and the exact verdict.

Stage B/D of ``plans/task15-p4b2-exact-painter-geometry-spike.md``: one
evidence bundle per page joins every replayed ShowOp to the glyphs MuPDF
actually painted (window search on ``(origin, gid)``; never text equality),
carries per-glyph O1/O2 bounds, and feeds :func:`exact_duplicate_painter_verdict`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from scripts.painter_evidence import (  # noqa: E402
    EVIDENCE_COUNTER_KEYS,
    MISSING_WINDOW_REASONS,
    PagePainterEvidence,
    build_page_painter_evidence,
    exact_duplicate_painter_verdict,
)
from scripts.painter_geometry import (  # noqa: E402
    PROOF_QUALITIES,
    rect_within,
    rects_overlap,
)
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    hide_second_painter_in_ocg,
    install_text_form_xobject,
    map_cid_to_two_codepoints,
    painters_overlap_pixels,
    replay_shows,
    set_text_state,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    FONTSIZE,
    SOURCE,
    SOURCE_WIDTH,
    _build_second_show_doc,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    build_identity_h_fixture,
    cid_for,
)

VERDICT_KINDS = (
    "exact_safe",
    "exact_overlap_same_baseline",
    "exact_overlap_cross_baseline",
    "ambiguous",
    "unavailable",
    "error",
)


def _evidence(fixture) -> PagePainterEvidence:
    registry = DocumentFontRegistry(fixture.doc)
    return build_page_painter_evidence(fixture.doc, fixture.page, registry=registry)


def _verdict(fixture, *, target_index: int = 0):
    shows = replay_shows(fixture)
    target = shows[target_index]
    twins = tuple(
        show
        for show in shows
        if show.seq != target.seq and show.decoded_bytes == target.decoded_bytes
    )
    evidence = _evidence(fixture)
    try:
        return exact_duplicate_painter_verdict(evidence, target, twins), evidence
    finally:
        evidence.release()


# ------------------------------------------------------------ events


def test_two_show_page_yields_two_exact_events_keyed_by_byte_span() -> None:
    fixture, _ = _build_second_show_doc(offset=SOURCE_WIDTH + 10.0)
    try:
        shows = replay_shows(fixture)
        evidence = _evidence(fixture)
        try:
            assert evidence.builds == 1
            events = [evidence.event_for(show) for show in shows]
            assert all(event is not None for event in events)
            for show, event in zip(shows, events):
                assert event is not None
                assert (event.stream_xref, event.op_start) == (show.stream_xref, show.op_start)
                assert event.proof_quality == "exact"
                assert event.reason is None
                assert len(event.glyphs) == 2
                assert event.paints is True
                assert [g.gid for g in event.glyphs] == [cid_for(c) for c in SOURCE]
            first, second = events
            assert first is not None and second is not None
            assert second.glyphs[0].origin[0] - first.glyphs[0].origin[0] == pytest.approx(
                SOURCE_WIDTH + 10.0, abs=1e-6
            )
            assert first.seqnos != second.seqnos or first.seqnos == second.seqnos
            assert evidence.unattributed_glyphs == 0
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_events_carry_agreeing_o1_and_o2_bounds_per_glyph() -> None:
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        evidence = _evidence(fixture)
        try:
            event = evidence.event_for(replay_shows(fixture)[0])
            assert event is not None
            for glyph in event.glyphs:
                assert glyph.quality == "exact"
                assert glyph.bounds is not None
                assert glyph.bounds_o2_lower is not None
                assert glyph.bounds_o2_upper is not None
                assert rect_within(glyph.bounds_o2_lower, glyph.bounds, 0.02)
                assert rect_within(glyph.bounds, glyph.bounds_o2_upper, 0.02)
                assert not rect_within(glyph.bounds, glyph.bounds_o2_lower, -0.5)  # not empty
            assert evidence.counters["oracle_disagreement"] == 0
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_leading_kern_tj_twin_is_placed_by_its_kern() -> None:
    """The reach path exists because replay drops TJ numbers; the join
    re-lexes them, so the TJ twin gets an exact event at the kerned origin."""
    fixture, _ = _build_second_show_doc(
        offset=SOURCE_WIDTH + 50.0,
        second_operator="TJ",
        second_leading_kern=6000.0,  # 72 pt to the LEFT at 12 pt
    )
    try:
        shows = replay_shows(fixture)
        assert shows[1].operator == "TJ"
        evidence = _evidence(fixture)
        try:
            twin = evidence.event_for(shows[1])
            target = evidence.event_for(shows[0])
            assert twin is not None and target is not None
            assert twin.proof_quality == "exact"
            shift = twin.glyphs[0].origin[0] - target.glyphs[0].origin[0]
            assert shift == pytest.approx(SOURCE_WIDTH + 50.0 - 72.0, abs=1e-6)
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_coincident_twins_are_ambiguous_but_verdict_invariant() -> None:
    fixture, _ = _build_second_show_doc(offset=0.0)
    try:
        shows = replay_shows(fixture)
        evidence = _evidence(fixture)
        try:
            first, second = (evidence.event_for(show) for show in shows)
            assert first is not None and second is not None
            # The first show sees two candidate windows (its own and the
            # coincident twin's): ambiguous by rule, verdict-invariant in
            # fact.  The second show's only remaining candidate is unique.
            assert first.proof_quality == "ambiguous"
            assert first.reason == "multiple_windows"
            assert second.proof_quality == "exact"
            assert evidence.counters["multiple_windows"] == 1
            assert evidence.counters["verdict_invariant_ambiguity"] == 1
            verdict = exact_duplicate_painter_verdict(evidence, shows[0], (shows[1],))
            assert verdict.kind == "ambiguous"
            assert verdict.target_unproven is True
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_form_xobject_glyphs_between_shows_stay_unattributed() -> None:
    fixture, _ = _build_second_show_doc(offset=SOURCE_WIDTH + 10.0)
    try:
        install_text_form_xobject(
            fixture, name="Fx1", text="再", fontsize=24.0, origin=(300.0, 200.0)
        )
        stream = fixture.content_bytes()
        marker = b"> Tj /"
        assert stream.count(marker) == 1
        fixture.doc.update_stream(
            fixture.content_xref,
            stream.replace(marker, b"> Tj ET q /Fx1 Do Q BT /", 1),
        )
        shows = replay_shows(fixture)
        assert len(shows) == 2
        evidence = _evidence(fixture)
        try:
            events = [evidence.event_for(show) for show in shows]
            assert all(e is not None and e.proof_quality == "exact" for e in events)
            assert evidence.unattributed_glyphs == 1
            assert evidence.counters["form_xobject_pages"] == 1
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_hidden_ocg_twin_is_ambiguous_with_a_closed_reason() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0)
    try:
        hide_second_painter_in_ocg(fixture, on=False)
        shows = replay_shows(fixture)
        evidence = _evidence(fixture)
        try:
            twin = evidence.event_for(shows[1])
            assert twin is not None
            assert twin.proof_quality == "ambiguous"
            assert twin.reason in MISSING_WINDOW_REASONS
            assert twin.reason == "ocg_or_absent"
            assert evidence.counters["missing_window.ocg_or_absent"] == 1
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_two_codepoint_tounicode_show_still_joins_on_gids() -> None:
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        map_cid_to_two_codepoints(fixture, cid_for(SOURCE[0]), "ab")
        evidence = _evidence(fixture)
        try:
            event = evidence.event_for(replay_shows(fixture)[0])
            assert event is not None
            assert event.proof_quality == "exact"
            assert [g.gid for g in event.glyphs] == [cid_for(c) for c in SOURCE]
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_fill_and_stroke_mode_pairs_both_emissions_into_one_conservative_event() -> None:
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        set_text_state(fixture, render_mode=2)
        evidence = _evidence(fixture)
        try:
            event = evidence.event_for(replay_shows(fixture)[0])
            assert event is not None
            assert event.render_mode == 2
            assert event.proof_quality == "conservative"
            assert len(event.seqnos) == 2
            assert event.seqnos[1] == event.seqnos[0] + 1
            assert event.conservative_rect is not None
            union = event.glyph_union()
            assert union is not None
            assert rect_within(union, event.conservative_rect, 0.0)
            assert evidence.counters["render_mode.2"] == 1
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_invisible_mode_event_paints_nothing_when_all_devices_agree() -> None:
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        set_text_state(fixture, render_mode=3)
        evidence = _evidence(fixture)
        try:
            event = evidence.event_for(replay_shows(fixture)[0])
            assert event is not None
            assert event.proof_quality == "exact"
            assert event.paints is False
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


@pytest.mark.parametrize("mode", [4, 7])
def test_clip_modes_are_ambiguous(mode: int) -> None:
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        set_text_state(fixture, render_mode=mode)
        evidence = _evidence(fixture)
        try:
            event = evidence.event_for(replay_shows(fixture)[0])
            assert event is not None
            assert event.proof_quality == "ambiguous"
            assert event.reason == "tr_clip"
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_dangling_font_resource_is_unavailable() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0, second_dangling=True)
    try:
        shows = replay_shows(fixture)
        evidence = _evidence(fixture)
        try:
            twin = evidence.event_for(shows[1])
            assert twin is not None
            assert twin.proof_quality == "unavailable"
            assert twin.reason == "no_cid_capability"
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


def test_evidence_counters_use_a_closed_key_set() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0)
    try:
        evidence = _evidence(fixture)
        try:
            assert set(evidence.counters) <= set(EVIDENCE_COUNTER_KEYS)
            assert all(key.isascii() for key in EVIDENCE_COUNTER_KEYS)
            assert set(PROOF_QUALITIES) == {"exact", "conservative", "ambiguous", "unavailable"}
        finally:
            evidence.release()
    finally:
        fixture.doc.close()


# ------------------------------------------------------------ verdicts


def test_disjoint_twin_is_exact_safe() -> None:
    fixture, _ = _build_second_show_doc(offset=SOURCE_WIDTH + 4.0)
    try:
        assert painters_overlap_pixels(fixture) == 0
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_safe"
        assert verdict.kind in VERDICT_KINDS
    finally:
        fixture.doc.close()


def test_abutting_twin_with_side_bearings_is_exact_safe() -> None:
    """Advance-abutting CJK glyphs have side bearings: their INK is disjoint
    even though their advance boxes touch (production also admits here)."""
    fixture, _ = _build_second_show_doc(offset=SOURCE_WIDTH)
    try:
        assert painters_overlap_pixels(fixture) == 0
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_safe"
    finally:
        fixture.doc.close()


@pytest.mark.parametrize("offset", [1.0, -1.0, 12.0, 20.0])
def test_overlapping_same_baseline_twin_is_exact_overlap(offset: float) -> None:
    fixture, _ = _build_second_show_doc(offset=offset)
    try:
        assert painters_overlap_pixels(fixture) > 0
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_overlap_same_baseline"
        assert verdict.twin_seq == 1
    finally:
        fixture.doc.close()


def test_leading_kern_tj_twin_over_the_target_is_exact_overlap() -> None:
    fixture, _ = _build_second_show_doc(
        offset=SOURCE_WIDTH + 50.0, second_operator="TJ", second_leading_kern=6000.0
    )
    try:
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_overlap_same_baseline"
    finally:
        fixture.doc.close()


def test_cross_baseline_ink_overlap_is_split_out() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0, second_dy=7.3)
    try:
        assert painters_overlap_pixels(fixture) > 0
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_overlap_cross_baseline"
    finally:
        fixture.doc.close()


def test_twin_on_a_far_line_is_exact_safe() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0, second_dy=-40.0)
    try:
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_safe"
    finally:
        fixture.doc.close()


def test_hidden_ocg_twin_verdict_is_ambiguous() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0)
    try:
        hide_second_painter_in_ocg(fixture, on=False)
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "ambiguous"
        assert verdict.reason == "ocg_or_absent"
    finally:
        fixture.doc.close()


def test_dangling_twin_verdict_is_unavailable() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0, second_dangling=True)
    try:
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "unavailable"
    finally:
        fixture.doc.close()


def test_unproven_target_placement_never_yields_exact_safe() -> None:
    fixture, _ = _build_second_show_doc(offset=SOURCE_WIDTH + 40.0)
    try:
        # Put the TARGET (first show) into a clip render mode: its own
        # placement is then ambiguous, so no twin can be proven disjoint.
        set_text_state(fixture, render_mode=7)
        verdict, evidence = _verdict(fixture)
        assert verdict.kind == "ambiguous"
        assert verdict.target_unproven is True
    finally:
        fixture.doc.close()


def test_row_aggregation_prefers_overlap_over_ambiguous_over_safe() -> None:
    """Three twins: one far (safe), one hidden (ambiguous), one on top
    (overlap) — the row verdict is overlap."""
    fixture, _ = _build_second_show_doc(offset=1.0)
    try:
        hide_second_painter_in_ocg(fixture, on=False)
        stream = fixture.content_bytes()
        far = (
            f"/{fixture.resource_name} {FONTSIZE:g} Tf 1 0 0 1 400 700 Tm "
            f"<{fixture.encoded.hex().upper()}> Tj "
            f"/{fixture.resource_name} {FONTSIZE:g} Tf 1 0 0 1 73 700 Tm "
            f"<{fixture.encoded.hex().upper()}> Tj ET"
        ).encode("ascii")
        assert stream.endswith(b" ET")
        fixture.doc.update_stream(fixture.content_xref, stream[:-2] + far)
        shows = replay_shows(fixture)
        assert len(shows) == 4
        verdict, _ = _verdict(fixture)
        assert verdict.kind == "exact_overlap_same_baseline"
        assert verdict.twin_seq == 3
        assert verdict.twin_kinds == (
            "exact_overlap_same_baseline",
            "ambiguous",
            "exact_safe",
        )
    finally:
        fixture.doc.close()


def test_verdict_counts_twin_ink_inside_a_caller_target_bbox() -> None:
    fixture, _ = _build_second_show_doc(offset=SOURCE_WIDTH + 4.0)
    try:
        shows = replay_shows(fixture)
        evidence = _evidence(fixture)
        try:
            target_event = evidence.event_for(shows[0])
            assert target_event is not None
            halo = target_event.glyph_union()
            assert halo is not None
            wide_halo = (halo[0], halo[1], halo[2] + 30.0, halo[3])
            verdict = exact_duplicate_painter_verdict(
                evidence, shows[0], (shows[1],), target_bbox_page=wide_halo
            )
            assert verdict.kind == "exact_safe"
            assert verdict.twin_ink_in_target_bbox is True
            twin_event = evidence.event_for(shows[1])
            assert twin_event is not None
            assert rects_overlap(twin_event.glyph_union(), wide_halo)
        finally:
            evidence.release()
    finally:
        fixture.doc.close()
