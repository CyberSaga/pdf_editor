"""P4-B2 commit 2: oracle characterization (Stage A).

Pins the pre-registered relations between the four geometry oracles of
``plans/task15-p4b2-exact-painter-geometry-spike.md`` §4.2 on synthetic
Identity-H pages, before any admission logic exists:

- O1  MuPDF per-glyph outline bounds from a custom device hook
- O2  fontTools per-glyph bounds (exact extrema = lower, control box = upper)
- O3  ``get_bboxlog``-equivalent union per ``fz_text``
- O4  raster ink at 576 dpi (ground truth)

plus the cursor-replay / trace-origin invariant the join will rest on, the
base-matrix capture on offset-CropBox / UserUnit / rotated pages, and the
render-mode witnesses.  Tolerances are the plan's §7.6 values.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from scripts.painter_evidence import (  # noqa: E402
    derotated_page,
    embedded_program,
    predict_glyphs,
    run_bboxlog,
    run_glyph_device,
    run_texttrace,
    tj_items,
)
from scripts.painter_geometry import (  # noqa: E402
    GEOMETRY_SLUGS,
    GeometryUnavailable,
    OutlineOracle,
    place_text_rect,
    rect_is_empty,
    rect_pad,
    rect_union,
    rect_within,
    render_mode_ladder,
    scale_units_to_text,
    transform_point,
)
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    TRICKY_FONT_PATH,
    build_face_fixture,
    first_show,
    glyph_ink_clip,
    hide_second_painter_in_ocg,
    install_text_form_xobject,
    map_cid_to_two_codepoints,
    render_ink_mask,
    replace_show_with_tj,
    set_page_boxes,
    set_show_cids,
    set_text_state,
    set_user_unit,
    tricky_font_available,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    _build_second_show_doc,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    append_page_content,
    build_identity_h_fixture,
    cid_for,
    fontfile2_xref,
)

TEXT = "再見"
SIZE = 48.0
ORIGIN = (100.0, 400.0)

O1_O2_TOL = 0.02
BBOXLOG_MARGIN = 1.0
BBOXLOG_MARGIN_TOL = 0.02
RASTER_TOL = 0.25
RASTER_TIGHTNESS = 1.0

# Glyphs of Droid Sans Fallback (the builder face) with known shapes:
CURVED_GID = 1166  # exact extrema differ from the control box
COMPOSITE_GID = 108  # a composite glyph
SPACE_CID = 1  # empty outline (space)


def _fixture(**kwargs):
    return build_identity_h_fixture(text=TEXT, fontsize=SIZE, origin=ORIGIN, **kwargs)


def _program(fixture) -> bytes:
    return fixture.doc.xref_stream(fontfile2_xref(fixture))


def _capability(fixture):
    registry = DocumentFontRegistry(fixture.doc)
    capability = registry.capability(fixture.page, fixture.resource_name)
    assert capability is not None and capability.cid is not None
    return capability


def _glyphs(fixture):
    interp = derotated_page(fixture.page)
    try:
        return interp, run_glyph_device(interp)
    except BaseException:
        interp.release()
        raise


def _o2_page_rects(fixture, interp, show, oracle, glyph_count):
    """Expected O2 (lower, upper) page rects per glyph via the cursor replay."""
    capability = _capability(fixture)
    predicted = predict_glyphs(show, capability, tj_items(fixture.content_bytes(), show))
    assert predicted.slug is None, predicted.slug
    assert len(predicted.glyphs) == glyph_count
    th = show.hscale / 100.0
    rects = []
    for glyph in predicted.glyphs:
        bounds = oracle.bounds(glyph.gid)
        pair = []
        for units in (bounds.lower, bounds.upper):
            assert units is not None
            text_rect = scale_units_to_text(units, oracle.units_per_em, show.font_size, th)
            pair.append(
                place_text_rect(
                    text_rect,
                    glyph.cursor_x,
                    show.rise,
                    show.tm,
                    show.ctm,
                    interp.base_matrix,
                )
            )
        rects.append(tuple(pair))
    return predicted, rects


# ------------------------------------------------------------- O2 oracle


def test_outline_oracle_reads_units_per_em_and_glyph_count() -> None:
    fixture = _fixture()
    try:
        oracle = OutlineOracle(_program(fixture))
        assert oracle.units_per_em == 256
        assert oracle.num_glyphs == 50483
        assert oracle.hinted is False
        bounds = oracle.bounds(cid_for("再"))
        assert bounds.lower == (12, -23, 244, 196)
        assert bounds.upper == (12, -23, 244, 196)
    finally:
        fixture.doc.close()


def test_outline_oracle_empty_outline_has_no_bounds() -> None:
    fixture = _fixture()
    try:
        oracle = OutlineOracle(_program(fixture))
        assert oracle.bounds(SPACE_CID).lower is None
        assert oracle.bounds(SPACE_CID).upper is None
        assert oracle.bounds(0).lower is None
    finally:
        fixture.doc.close()


def test_outline_oracle_composite_glyph_has_bounds() -> None:
    fixture = _fixture()
    try:
        oracle = OutlineOracle(_program(fixture))
        bounds = oracle.bounds(COMPOSITE_GID)
        assert bounds.lower is not None and bounds.upper is not None
        assert rect_within(bounds.lower, bounds.upper, 0.0)
    finally:
        fixture.doc.close()


def test_outline_oracle_curved_glyph_lower_is_strictly_inside_upper() -> None:
    fixture = _fixture()
    try:
        oracle = OutlineOracle(_program(fixture))
        bounds = oracle.bounds(CURVED_GID)
        assert bounds.lower != bounds.upper
        assert rect_within(bounds.lower, bounds.upper, 0.0)
    finally:
        fixture.doc.close()


def test_outline_oracle_out_of_range_gid_is_a_closed_slug() -> None:
    fixture = _fixture()
    try:
        oracle = OutlineOracle(_program(fixture))
        with pytest.raises(GeometryUnavailable) as info:
            oracle.bounds(oracle.num_glyphs)
        assert info.value.slug == "gid_out_of_range"
        assert info.value.slug in GEOMETRY_SLUGS
        assert str(info.value) == info.value.slug
    finally:
        fixture.doc.close()


def test_outline_oracle_unparseable_program_is_a_closed_slug() -> None:
    with pytest.raises(GeometryUnavailable) as info:
        OutlineOracle(b"\x00\x01\x00\x00garbage-not-a-font")
    assert info.value.slug == "program_unparseable"
    assert str(info.value) == info.value.slug
    assert str(info.value).isascii()


def test_outline_oracle_never_surfaces_glyph_names() -> None:
    """fontTools exception text carries glyph names (``uni518D``); the
    oracle must map every failure to a slug and drop the message."""
    fixture = _fixture()
    try:
        program = bytearray(_program(fixture))
        font = OutlineOracle(bytes(program))
        # Corrupt the glyf table body: any per-glyph parse failure must
        # surface as a slug, never as fontTools' message.
        glyf_offset = font.table_offset("glyf")
        assert glyf_offset is not None
        program[glyf_offset : glyf_offset + 4096] = b"\xff" * 4096
        broken = OutlineOracle(bytes(program))
        seen = set()
        for gid in range(1, 400):
            try:
                broken.bounds(gid)
            except GeometryUnavailable as exc:
                seen.add(exc.slug)
                assert str(exc) == exc.slug
        assert seen <= set(GEOMETRY_SLUGS)
    finally:
        fixture.doc.close()


# -------------------------------------------------------- O1 device + trace


def test_glyph_device_agrees_with_texttrace_on_identity() -> None:
    fixture = _fixture()
    try:
        interp, glyphs = _glyphs(fixture)
        try:
            trace = run_texttrace(interp)
        finally:
            interp.release()
        expected = [
            (span["seqno"], char[1], tuple(char[2]))
            for span in trace
            for char in span["chars"]
        ]
        assert [(g.seqno, g.gid, g.origin) for g in glyphs] == expected
        assert {g.kind for g in glyphs} == {"fill"}
        assert {g.wmode for g in glyphs} == {0}
        assert len(glyphs) == 2
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    "cids",
    [
        pytest.param(None, id="fixture-text"),
        pytest.param((CURVED_GID, CURVED_GID), id="curved"),
        pytest.param((COMPOSITE_GID, cid_for("見")), id="composite"),
    ],
)
def test_o1_lies_between_o2_lower_and_upper(cids) -> None:
    fixture = _fixture()
    try:
        if cids is not None:
            set_show_cids(fixture, cids)
        show = first_show(fixture)
        oracle = OutlineOracle(_program(fixture))
        interp, glyphs = _glyphs(fixture)
        try:
            _, rects = _o2_page_rects(fixture, interp, show, oracle, len(glyphs))
        finally:
            interp.release()
        for glyph, (lower, upper) in zip(glyphs, rects):
            assert glyph.bounds is not None
            assert rect_within(lower, glyph.bounds, O1_O2_TOL), (lower, glyph.bounds)
            assert rect_within(glyph.bounds, upper, O1_O2_TOL), (glyph.bounds, upper)
    finally:
        fixture.doc.close()


def test_o1_curved_glyph_reports_which_side_mupdf_takes() -> None:
    """Risk register item 1: is MuPDF's bound a control box or exact
    extrema?  Either satisfies the two-sided relation; record which."""
    fixture = _fixture()
    try:
        set_show_cids(fixture, (CURVED_GID,))
        show = first_show(fixture)
        oracle = OutlineOracle(_program(fixture))
        interp, glyphs = _glyphs(fixture)
        try:
            _, rects = _o2_page_rects(fixture, interp, show, oracle, 1)
        finally:
            interp.release()
        lower, upper = rects[0]
        bounds = glyphs[0].bounds
        assert bounds is not None
        matches_lower = rect_within(bounds, lower, O1_O2_TOL) and rect_within(lower, bounds, O1_O2_TOL)
        matches_upper = rect_within(bounds, upper, O1_O2_TOL) and rect_within(upper, bounds, O1_O2_TOL)
        assert matches_lower or matches_upper, (bounds, lower, upper)
    finally:
        fixture.doc.close()


# ------------------------------------------------------------ O3 bboxlog


def test_bboxlog_is_o1_union_plus_one_point_at_identity_ctm() -> None:
    fixture = _fixture()
    try:
        interp, glyphs = _glyphs(fixture)
        try:
            log = run_bboxlog(interp)
        finally:
            interp.release()
        assert [code for code, _ in log] == ["fill-text"]
        union = rect_union([g.bounds for g in glyphs if g.bounds is not None])
        expected = rect_pad(union, BBOXLOG_MARGIN)
        assert rect_within(union, log[0][1], 0.0)
        assert rect_within(expected, log[0][1], BBOXLOG_MARGIN_TOL)
        assert rect_within(log[0][1], expected, BBOXLOG_MARGIN_TOL)
    finally:
        fixture.doc.close()


def test_bboxlog_margin_is_one_point_in_page_space_under_a_scaling_ctm() -> None:
    fixture = _fixture()
    try:
        stream = fixture.content_bytes()
        fixture.doc.update_stream(
            fixture.content_xref, b"q 2 0 0 2 0 0 cm " + stream + b" Q"
        )
        interp, glyphs = _glyphs(fixture)
        try:
            log = run_bboxlog(interp)
        finally:
            interp.release()
        union = rect_union([g.bounds for g in glyphs if g.bounds is not None])
        assert rect_within(union, log[0][1], 0.0)
        # Measured: the margin is applied AFTER the CTM (device space, which
        # is page space for an identity display-list run), so it stays 1.0 pt.
        expected = rect_pad(union, BBOXLOG_MARGIN)
        assert rect_within(expected, log[0][1], BBOXLOG_MARGIN_TOL)
        assert rect_within(log[0][1], expected, BBOXLOG_MARGIN_TOL)
    finally:
        fixture.doc.close()


def test_bboxlog_index_equals_device_seqno_with_interleaved_path() -> None:
    fixture = _fixture()
    try:
        stream = fixture.content_bytes()
        fixture.doc.update_stream(
            fixture.content_xref,
            b"10 10 20 20 re f " + stream + b" 30 30 5 5 re f",
        )
        interp, glyphs = _glyphs(fixture)
        try:
            log = run_bboxlog(interp)
        finally:
            interp.release()
        assert [code for code, _ in log] == ["fill-path", "fill-text", "fill-path"]
        assert {g.seqno for g in glyphs} == {1}
        union = rect_union([g.bounds for g in glyphs if g.bounds is not None])
        assert rect_within(union, log[1][1], 0.0)
    finally:
        fixture.doc.close()


# ------------------------------------------------------------- O4 raster


@pytest.mark.parametrize("size", [48.0, 12.0])
def test_raster_ink_lies_within_o1(size: float) -> None:
    fixture = build_identity_h_fixture(text=TEXT, fontsize=size, origin=ORIGIN)
    try:
        interp, glyphs = _glyphs(fixture)
        interp.release()
        union = rect_union([g.bounds for g in glyphs if g.bounds is not None])
        mask = render_ink_mask(fixture.page, glyph_ink_clip(fixture))
        ink = mask.bbox_pt()
        assert ink is not None
        assert rect_within(ink, union, RASTER_TOL), (ink, union)
        if size >= 48.0:
            assert rect_within(union, ink, RASTER_TIGHTNESS), (union, ink)
    finally:
        fixture.doc.close()


# ------------------------------------------------- base matrix / origins


@pytest.mark.parametrize("rotate", [0, 90])
@pytest.mark.parametrize(
    ("mediabox", "cropbox", "user_unit"),
    [
        pytest.param(None, None, None, id="plain"),
        pytest.param((-100, -100, 495, 742), (50, 60, 545, 782), None, id="offset-boxes"),
        pytest.param(None, None, 2.0, id="userunit-2"),
        pytest.param((-100, -100, 495, 742), (50, 60, 545, 782), 0.5, id="offset-userunit-half"),
    ],
)
def test_trace_origin_equals_origin_user_through_base_matrix(
    rotate: int, mediabox, cropbox, user_unit
) -> None:
    fixture = _fixture(rotate=rotate)
    try:
        set_page_boxes(fixture, mediabox=mediabox, cropbox=cropbox)
        if user_unit is not None:
            set_user_unit(fixture, user_unit)
        show = first_show(fixture)
        assert show.origin_reliable
        interp, glyphs = _glyphs(fixture)
        try:
            assert interp.rotation == rotate
            assert fixture.page.rotation == rotate, "rotation must be restored"
            trace = run_texttrace(interp)
        finally:
            interp.release()
        expected = transform_point(show.origin_user, interp.base_matrix)
        assert glyphs[0].origin == pytest.approx(expected, abs=1e-6)
        assert tuple(trace[0]["chars"][0][2]) == pytest.approx(expected, abs=1e-6)
        # And the wrapper (which derotates itself) agrees.
        wrapper = fixture.page.get_texttrace()[0]["chars"][0][2]
        assert tuple(wrapper) == pytest.approx(expected, abs=1e-6)
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    "state",
    [
        pytest.param({}, id="default"),
        pytest.param({"hscale": 80.0}, id="Tz80"),
        pytest.param({"hscale": 120.0}, id="Tz120"),
        pytest.param({"hscale": -100.0}, id="Tz-100"),
        pytest.param({"char_spacing": 2.0}, id="Tc+2"),
        pytest.param({"char_spacing": -2.0}, id="Tc-2"),
        pytest.param({"word_spacing": 40.0}, id="Tw40-ignored"),
        pytest.param({"rise": 3.0}, id="Ts+3"),
        pytest.param({"rise": -3.0}, id="Ts-3"),
        pytest.param({"hscale": 80.0, "char_spacing": -1.5, "rise": 2.0}, id="combined"),
    ],
)
def test_cursor_replay_matches_device_origins_for_tj(state: dict) -> None:
    """Invariant 1 (STOP rule scope): on a plain ``Tj`` with a reliable
    origin, the Identity-H cursor replay must land every glyph where MuPDF
    paints it, within ``1e-3 * Tfs``."""
    fixture = _fixture()
    try:
        if state:
            set_text_state(fixture, **state)
        show = first_show(fixture)
        assert show.operator == "Tj" and show.origin_reliable
        capability = _capability(fixture)
        predicted = predict_glyphs(show, capability, tj_items(fixture.content_bytes(), show))
        assert predicted.slug is None
        interp, glyphs = _glyphs(fixture)
        try:
            base = interp.base_matrix
        finally:
            interp.release()
        assert len(glyphs) == len(predicted.glyphs) == 2
        tol = 1e-3 * show.font_size
        for device_glyph, guess in zip(glyphs, predicted.glyphs):
            assert device_glyph.gid == guess.gid
            expected = transform_point(guess.origin_user, base)
            assert device_glyph.origin == pytest.approx(expected, abs=tol), state
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    "items",
    [
        pytest.param([500.0, "再見"], id="leading-kern"),
        pytest.param(["再", -250.0, "見"], id="intra-kern"),
        pytest.param([-1000.0, "再", 300.0, "見", 100.0], id="mixed"),
    ],
)
def test_cursor_replay_matches_device_origins_for_tj_arrays(items) -> None:
    fixture = _fixture()
    try:
        replace_show_with_tj(fixture, items)
        show = first_show(fixture)
        assert show.operator == "TJ"
        lexed = tj_items(fixture.content_bytes(), show)
        assert lexed is not None
        assert [item.kind for item in lexed] == [
            "kern" if isinstance(item, float) else "string" for item in items
        ]
        capability = _capability(fixture)
        predicted = predict_glyphs(show, capability, lexed)
        assert predicted.slug is None
        interp, glyphs = _glyphs(fixture)
        try:
            base = interp.base_matrix
        finally:
            interp.release()
        assert len(glyphs) == len(predicted.glyphs) == 2
        tol = 1e-3 * show.font_size
        for device_glyph, guess in zip(glyphs, predicted.glyphs):
            expected = transform_point(guess.origin_user, base)
            assert device_glyph.origin == pytest.approx(expected, abs=tol)
    finally:
        fixture.doc.close()


def test_tj_relex_integrity_rejects_a_mismatched_show() -> None:
    fixture = _fixture()
    try:
        replace_show_with_tj(fixture, ["再", -250.0, "見"])
        show = first_show(fixture)
        stream = fixture.content_bytes()
        assert tj_items(stream, show) is not None
        # A stream that no longer matches the ShowOp's byte range: refuse.
        assert tj_items(stream[: show.string_end - 2], show) is None
        assert tj_items(b"x" + stream, show) is None
    finally:
        fixture.doc.close()


# --------------------------------------------------------- render modes


@pytest.mark.parametrize(
    ("mode", "kinds", "codes", "ladder"),
    [
        (0, ["fill"], ["fill-text"], "exact"),
        (1, ["stroke"], ["stroke-text"], "stroke"),
        (2, ["fill", "stroke"], ["fill-text", "stroke-text"], "stroke"),
        (3, ["ignore"], ["ignore-text"], "invisible"),
        (4, ["fill"], ["fill-text"], "clip"),
        (5, ["stroke"], ["stroke-text"], "clip"),
        (6, ["fill", "stroke"], ["fill-text", "stroke-text"], "clip"),
        (7, [], [], "clip"),
    ],
)
def test_render_mode_witnesses(mode: int, kinds, codes, ladder: str) -> None:
    fixture = _fixture()
    try:
        set_text_state(fixture, render_mode=mode)
        show = first_show(fixture)
        assert show.render_mode == mode
        assert render_mode_ladder(mode) == ladder
        interp, glyphs = _glyphs(fixture)
        try:
            log = run_bboxlog(interp)
        finally:
            interp.release()
        seen = []
        for glyph in glyphs:
            if glyph.kind not in seen:
                seen.append(glyph.kind)
        assert seen == kinds
        assert [code for code, _ in log] == codes
        if mode == 2:
            # The same fz_text is emitted twice: adjacent seqnos, same glyphs.
            fills = [g for g in glyphs if g.kind == "fill"]
            strokes = [g for g in glyphs if g.kind == "stroke"]
            assert [g.gid for g in fills] == [g.gid for g in strokes]
            assert {g.seqno for g in strokes} == {next(iter({g.seqno for g in fills})) + 1}
    finally:
        fixture.doc.close()


# ------------------------------------------------ trace shape edge cases


def test_two_codepoint_tounicode_continuation_item_is_dropped() -> None:
    fixture = _fixture()
    try:
        map_cid_to_two_codepoints(fixture, cid_for("再"), "ab")
        interp, glyphs = _glyphs(fixture)
        try:
            trace = run_texttrace(interp)
        finally:
            interp.release()
        raw_gids = [char[1] for span in trace for char in span["chars"]]
        assert -1 in raw_gids, raw_gids
        assert [g.gid for g in glyphs] == [cid_for("再"), cid_for("見")]
        assert all(g.gid >= 0 for g in glyphs)
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    "cids",
    [
        pytest.param((SPACE_CID,), id="space-only"),
        pytest.param((0,), id="notdef-only"),
        pytest.param((SPACE_CID, cid_for("再")), id="space-then-glyph"),
    ],
)
def test_empty_outline_shows_keep_their_count_and_carry_no_ink(cids) -> None:
    fixture = _fixture()
    try:
        set_show_cids(fixture, cids)
        interp, glyphs = _glyphs(fixture)
        try:
            trace = run_texttrace(interp)
            log = run_bboxlog(interp)
        finally:
            interp.release()
        assert len(glyphs) == len(cids)
        assert sum(len(span["chars"]) for span in trace) == len(cids)
        for glyph, cid in zip(glyphs, cids):
            assert glyph.gid == cid
            if cid in (SPACE_CID, 0):
                assert glyph.bounds is None or rect_is_empty(glyph.bounds)
        assert len(log) == 1
    finally:
        fixture.doc.close()


def test_text_form_xobject_glyphs_reach_the_devices_without_a_show() -> None:
    fixture = _fixture()
    try:
        install_text_form_xobject(
            fixture, name="Fx1", text="再", fontsize=24.0, origin=(300.0, 200.0)
        )
        append_page_content(fixture, "q /Fx1 Do Q")
        from test_scripts.painter_matrix_fixtures import replay_shows

        assert len(replay_shows(fixture)) == 1
        interp, glyphs = _glyphs(fixture)
        try:
            log = run_bboxlog(interp)
        finally:
            interp.release()
        assert len(glyphs) == 3
        assert [code for code, _ in log] == ["fill-text", "fill-text"]
        assert glyphs[2].seqno == 1
        assert glyphs[2].origin[0] == pytest.approx(300.0, abs=1e-6)
    finally:
        fixture.doc.close()


@pytest.mark.parametrize("on", [False, True])
def test_hidden_ocg_painter_is_absent_from_the_devices(on: bool) -> None:
    fixture, _ = _build_second_show_doc(offset=1.0)
    try:
        hide_second_painter_in_ocg(fixture, on=on)
        interp, glyphs = _glyphs(fixture)
        try:
            log = run_bboxlog(interp)
        finally:
            interp.release()
        assert len(glyphs) == (4 if on else 2)
        # A visible /OC BDC boundary FLUSHES the fz_text: the two painters of
        # one BT become two bboxlog entries (measured; hidden: one entry).
        assert len(log) == (2 if on else 1)
    finally:
        fixture.doc.close()


# ------------------------------------------------------- tricky font cell


@pytest.mark.skipif(not tricky_font_available(), reason="mingliu.ttc absent")
@pytest.mark.parametrize("fontsize", [SIZE, 12.0, 9.0], ids=["48pt", "12pt", "9pt"])
def test_tricky_hinted_font_oracles_agree(fontsize: float) -> None:
    """Review (2026-09-02): FreeType forces the bytecode hinter on
    FT_IS_TRICKY faces, and ``fz_bound_glyph`` loads at a different ppem
    than rendering, so O1 need not contain the ink at small sizes.  Measured
    at 48, 12 and 9 pt: raster within O1 + 0.25 pt, O2 lower/upper hold."""
    fixture = build_face_fixture(TRICKY_FONT_PATH, TEXT, fontsize=fontsize, origin=ORIGIN)
    try:
        program = embedded_program(fixture.doc, fixture.font_xref)
        assert program is not None
        oracle = OutlineOracle(program)
        assert oracle.hinted is True
        assert oracle.units_per_em == 1024
        show = first_show(fixture)
        interp, glyphs = _glyphs(fixture)
        try:
            _, rects = _o2_page_rects(fixture, interp, show, oracle, len(glyphs))
            log = run_bboxlog(interp)
        finally:
            interp.release()
        for glyph, (lower, upper) in zip(glyphs, rects):
            assert glyph.bounds is not None
            assert rect_within(lower, glyph.bounds, O1_O2_TOL)
            assert rect_within(glyph.bounds, upper, O1_O2_TOL)
        union = rect_union([g.bounds for g in glyphs if g.bounds is not None])
        assert rect_within(union, log[0][1], 0.0)
        ink = render_ink_mask(fixture.page, glyph_ink_clip(fixture)).bbox_pt()
        assert ink is not None
        assert rect_within(ink, union, RASTER_TOL), (ink, union)
    finally:
        fixture.doc.close()


def test_embedded_program_resolves_the_fixture_fontfile2() -> None:
    fixture = _fixture()
    try:
        program = embedded_program(fixture.doc, fixture.font_xref)
        assert program == _program(fixture)
        assert embedded_program(fixture.doc, 10**6) is None
    finally:
        fixture.doc.close()


def test_fonttools_is_importable_for_the_o2_oracle() -> None:
    from fontTools.ttLib import TTFont

    assert TTFont is not None
    assert io is not None
