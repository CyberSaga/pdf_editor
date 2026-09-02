"""P4-B2 commit 4: falsification matrix (Stage C) — the safety gate.

Every case builds a two-painter page, measures the ground truth (do the two
painters' single-painter rasters overlap?), and runs THREE arms on the
same page:

- ``exact``    — the spike gate (:func:`exact_duplicate_painter_verdict`);
- ``baseline`` — production ``prepare_plan`` at the frozen P4-B1 tip;
- ``reach``    — production with ``_painter_advance`` stubbed to ``None``
                 (the review's collapse-to-reach control).

The safety gate (plan §7.2): the exact arm never reports ``exact_safe`` on
a page whose rasters overlap.  Baseline/reach false-safes are counted and
listed, never asserted away.  Cases with a fixed expectation also pin the
exact arm's kind; the rest pin raster consistency only.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import plan as plan_module  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PlanRejection, prepare_plan  # noqa: E402
from scripts.painter_evidence import (  # noqa: E402
    VERDICT_KINDS,
    build_page_painter_evidence,
    exact_duplicate_painter_verdict,
)
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    hide_second_painter_in_ocg,
    install_text_form_xobject,
    replay_shows,
    single_painter_masks,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    FONTSIZE,
    REPLACEMENT,
    SOURCE,
    SOURCE_WIDTH,
    _build_second_show_doc,
)
from test_scripts.type0_fixture_builder import Type0Fixture, cid_for  # noqa: E402

OVERLAP_KINDS = {"exact_overlap_same_baseline", "exact_overlap_cross_baseline"}


# --------------------------------------------------------------- builders


def _twin_font_xref(fixture: Type0Fixture, resource: str) -> int:
    for entry in fixture.page.get_fonts(full=True):
        if entry[4] == resource:
            return int(entry[0])
    raise AssertionError("twin resource not found")


def _split_bt_around_twin(fixture: Type0Fixture, prelude: str, postlude: str) -> None:
    """``BT target ET <prelude> BT twin ET <postlude>`` from the one-BT page."""
    stream = fixture.content_bytes()
    marker = b"> Tj /"
    assert stream.count(marker) == 1 and stream.endswith(b" ET")
    edited = stream.replace(
        marker, b"> Tj ET " + prelude.encode("ascii") + b" BT /", 1
    )
    edited = edited + b" " + postlude.encode("ascii")
    fixture.doc.update_stream(fixture.content_xref, edited)


def _insert_between_painters(fixture: Type0Fixture, raw: str) -> None:
    stream = fixture.content_bytes()
    marker = b"> Tj /"
    assert stream.count(marker) == 1
    fixture.doc.update_stream(
        fixture.content_xref,
        stream.replace(marker, b"> Tj " + raw.encode("ascii") + b" /", 1),
    )


def _rewrite_twin_as_tj(fixture: Type0Fixture, items: list[str]) -> None:
    """Replace the SECOND painter's ``<hex> Tj`` with ``[ ... ] TJ``."""
    stream = fixture.content_bytes()
    operand = f"<{fixture.encoded.hex().upper()}> Tj".encode("ascii")
    assert stream.count(operand) == 2
    first = stream.index(operand)
    second = stream.index(operand, first + 1)
    new = ("[" + " ".join(items) + "] TJ").encode("ascii")
    fixture.doc.update_stream(
        fixture.content_xref, stream[:second] + new + stream[second + len(operand) :]
    )


def _set_resource(fixture: Type0Fixture, category: str, name: str, value: str) -> None:
    doc = fixture.doc
    owner = fixture.page.xref
    prefix: list[str] = []
    for part in ("Resources", category):
        kind, current = doc.xref_get_key(owner, "/".join([*prefix, part]))
        if kind == "xref":
            owner = int(current.split()[0])
            prefix = []
        else:
            prefix.append(part)
    doc.xref_set_key(owner, "/".join([*prefix, name]), value)


def _add_type3_twin(fixture: Type0Fixture, *, offset: float) -> None:
    """A Type3 font whose single-byte codes are exactly the target's bytes,
    each painting a filled em square; shown as a second painter."""
    doc = fixture.doc
    codes = sorted(set(fixture.encoded))
    proc = doc.get_new_xref()
    doc.update_object(proc, "<<>>")
    doc.update_stream(proc, b"1000 0 0 0 1000 1000 d1 0 0 1000 1000 re f")
    first, last = min(codes), max(codes)
    widths = " ".join("1000" if code in codes else "0" for code in range(first, last + 1))
    differences = " ".join(f"{code} /sq" for code in codes)
    font = doc.get_new_xref()
    doc.update_object(
        font,
        "<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
        "/FontMatrix [0.001 0 0 0.001 0 0] "
        f"/CharProcs << /sq {proc} 0 R >> "
        f"/Encoding << /Type /Encoding /Differences [{differences}] >> "
        f"/FirstChar {first} /LastChar {last} /Widths [{widths}] "
        "/Resources << >> >>",
    )
    _set_resource(fixture, "Font", "T3", f"{font} 0 R")
    stream = fixture.content_bytes()
    assert stream.endswith(b" ET")
    twin = (
        f" /T3 {FONTSIZE:g} Tf 1 0 0 1 {fixture.origin[0] + offset:g} "
        f"{fixture.origin[1]:g} Tm <{fixture.encoded.hex().upper()}> Tj ET"
    ).encode("ascii")
    doc.update_stream(fixture.content_xref, stream[:-3] + twin)


@dataclass(frozen=True)
class Case:
    id: str
    build: Callable[[], tuple[Type0Fixture, tuple[float, float]]]
    expect: str | None = None  # exact-arm kind, or None for raster consistency only
    note: str = ""


def _two(**kwargs):
    return lambda: _build_second_show_doc(**kwargs)


def _post(build, edit):
    def _run():
        fixture, origin = build()
        edit(fixture)
        return fixture, origin

    return _run


def _clone_encoding(name: str):
    def _edit(fixture: Type0Fixture) -> None:
        clone = _twin_font_xref(fixture, "F_CLONE")
        fixture.doc.xref_set_key(clone, "Encoding", name)

    return _edit


def _clone_gid_beyond_count(fixture: Type0Fixture) -> None:
    clone = _twin_font_xref(fixture, "F_CLONE")
    _, descendant = fixture.doc.xref_get_key(clone, "DescendantFonts")
    descendant_xref = int(descendant.strip()[1:].split()[0])
    _, map_ref = fixture.doc.xref_get_key(descendant_xref, "CIDToGIDMap")
    map_xref = int(map_ref.split()[0])
    table = bytearray(fixture.doc.xref_stream(map_xref))
    for index in range(0, len(table), 2):
        if table[index : index + 2] != b"\x00\x00":
            table[index : index + 2] = (60000).to_bytes(2, "big")
    fixture.doc.update_stream(map_xref, bytes(table))


def _degenerate_twin_glyphs(fixture: Type0Fixture, chars: str) -> None:
    """Give the twin's clone font its OWN program in which each of ``chars``
    is a zero-height two-point contour ``(0,0)-(600,0)``.

    Review finding (2026-09-02): a stroke paints a pen-width line along that
    contour while every outline oracle (O1 ``fz_bound_glyph``, O2 pens,
    ``fz_bound_text``) reports an EMPTY box — MuPDF's union drops empty
    rects, so the bboxlog entry carries no stroke expansion either.  The
    target keeps the pristine program (own descriptor, own FontFile2).
    """
    clone = _twin_font_xref(fixture, "F_CLONE")
    _, descendant = fixture.doc.xref_get_key(clone, "DescendantFonts")
    descendant_xref = int(descendant.strip()[1:].split()[0])
    assert descendant_xref != fixture.descendant_xref, "clone the descendant first"
    _, map_ref = fixture.doc.xref_get_key(descendant_xref, "CIDToGIDMap")
    table = fixture.doc.xref_stream(int(map_ref.split()[0]))
    _, descriptor_ref = fixture.doc.xref_get_key(descendant_xref, "FontDescriptor")
    descriptor_xref = int(descriptor_ref.split()[0])
    _, program_ref = fixture.doc.xref_get_key(descriptor_xref, "FontFile2")
    program_xref = int(program_ref.split()[0])
    font = TTFont(io.BytesIO(fixture.doc.xref_stream(program_xref)))
    order = font.getGlyphOrder()
    for char in chars:
        cid = cid_for(char)
        gid = int.from_bytes(table[2 * cid : 2 * cid + 2], "big")
        pen = TTGlyphPen(font.getGlyphSet())
        pen.moveTo((0, 0))
        pen.lineTo((600, 0))
        pen.closePath()
        font["glyf"][order[gid]] = pen.glyph()
    out = io.BytesIO()
    font.save(out)
    new_program = fixture.doc.get_new_xref()
    fixture.doc.update_object(new_program, "<<>>")
    fixture.doc.update_stream(new_program, out.getvalue())
    new_descriptor = fixture.doc.get_new_xref()
    fixture.doc.update_object(new_descriptor, fixture.doc.xref_object(descriptor_xref))
    fixture.doc.xref_set_key(new_descriptor, "FontFile2", f"{new_program} 0 R")
    fixture.doc.xref_set_key(descendant_xref, "FontDescriptor", f"{new_descriptor} 0 R")


def _degenerate_clone(*, offset: float, chars: str, raw: str | None):
    """A two-painter page whose twin uses the degenerate-glyph clone."""

    def _run():
        fixture, origin = _build_second_show_doc(
            offset=offset,
            second_resource="F_CLONE",
            second_clone_font=True,
            second_clone_distinct_cidtogid=True,
        )
        _degenerate_twin_glyphs(fixture, chars)
        if raw is not None:
            _insert_between_painters(fixture, raw)
        return fixture, origin

    return _run


CASES: list[Case] = []

for width in (0, 1):
    for distinct in (False, True):
        for offset in (-2.0, -1.0, 1.0, 2.0):
            CASES.append(
                Case(
                    f"w{width}-{'distinct' if distinct else 'same'}-{offset:+.0f}",
                    _two(
                        offset=offset,
                        second_resource="F_CLONE",
                        second_clone_font=True,
                        second_clone_width=width,
                        second_clone_distinct_cidtogid=distinct,
                    ),
                    "exact_overlap_same_baseline",
                    "F1/F3 /W continuum",
                )
            )
for dy in (-7.3, 7.3):
    CASES.append(
        Case(
            f"core-band-{dy:+.1f}",
            _two(offset=1.0, second_dy=dy),
            "exact_overlap_cross_baseline",
            "R5 core band",
        )
    )

CASES += [
    Case("neg-tc-walkback", _two(offset=-12.5, second_char_spacing=-8.0),
         "exact_overlap_same_baseline", "F4: second glyph walks back over the target"),
    Case("neg-tc-same-origin", _two(offset=1.0, second_char_spacing=-12.0),
         "exact_overlap_same_baseline", "all twin glyphs at one origin"),
    Case("neg-tw-ignored", _two(offset=SOURCE_WIDTH + 0.5, second_word_spacing=-40.0),
         "exact_safe", "Tw never applies to 2-byte codes"),
    Case("pos-tc-gap-aggregate", _two(offset=-12.5, second_char_spacing=24.0),
         "exact_safe", "aggregate boxes overlap, per-glyph ink disjoint"),
    Case("metric-clone-1500-overlap",
         _two(offset=1.2, second_resource="F_CLONE", second_clone_font=True, second_clone_width=1500),
         "exact_overlap_same_baseline", "width clone"),
    Case("metric-clone-1500-disjoint",
         _two(offset=SOURCE_WIDTH + 20.0, second_resource="F_CLONE", second_clone_font=True, second_clone_width=1500),
         "exact_safe", "width clone, provably apart"),
    Case("distinct-cidtogid-overlap",
         _two(offset=1.2, second_resource="F_CLONE", second_clone_font=True, second_clone_distinct_cidtogid=True),
         None, "different glyphs, same bytes"),
    Case("tz80", _two(offset=SOURCE_WIDTH + 0.5, second_font_size=FONTSIZE), None, "control"),
    Case("tz120-right", _post(_two(offset=SOURCE_WIDTH + 0.5), lambda f: None), None, "control"),
    Case("tz-neg-left-mirrored", _two(offset=-0.5, second_matrix=None), None, "placeholder"),
    Case("rotated-45-crossing",
         _two(offset=0.0, second_matrix=f"0.7071 0.7071 -0.7071 0.7071 {72.0 + 6.0:g} {700.0 - 4.0:g}"),
         "exact_overlap_cross_baseline", "rotated twin crosses the target"),
    Case("sheared", _two(offset=1.0, second_matrix=f"1 0 0.5 1 {73.0:g} {700.0:g}"),
         "exact_overlap_same_baseline", "shear keeps the baseline"),
    Case("anisotropic-2x", _two(offset=-30.0, second_matrix=f"2 0 0 1 {42.0:g} {700.0:g}"),
         "exact_overlap_same_baseline", "2x wide twin from the left"),
    Case("tj-intra-kern-overlap",
         _post(_two(offset=SOURCE_WIDTH + 30.0),
               lambda f: _rewrite_twin_as_tj(f, [f"<{f.encoded[:2].hex().upper()}>", "4000", f"<{f.encoded[2:].hex().upper()}>"])),
         "exact_overlap_same_baseline", "kern pulls glyph 2 back onto the target"),
    Case("tj-intra-kern-disjoint",
         _post(_two(offset=SOURCE_WIDTH + 30.0),
               lambda f: _rewrite_twin_as_tj(f, [f"<{f.encoded[:2].hex().upper()}>", "500", f"<{f.encoded[2:].hex().upper()}>"])),
         "exact_safe", "TJ twin provably apart (reach rejects it)"),
    Case("identity-v-clone",
         _post(_two(offset=1.0, second_resource="F_CLONE", second_clone_font=True), _clone_encoding("/Identity-V")),
         "unavailable", "vertical writing never exact"),
    Case("custom-cmap-clone",
         _post(_two(offset=1.0, second_resource="F_CLONE", second_clone_font=True), _clone_encoding("/UniGB-UCS2-H")),
         "unavailable", "non-Identity CMap never exact"),
    Case("type3-twin", _post(_two(offset=SOURCE_WIDTH + 4.0), lambda f: _add_type3_twin(f, offset=1.0)),
         "unavailable", "Type3 twin: no cid capability"),
    Case("tz-zero", _post(_two(offset=1.0), lambda f: _insert_between_painters(f, "0 Tz")),
         None, "degenerate: paints nothing"),
    Case("tfs-zero", _two(offset=1.0, second_font_size=0.0), None, "degenerate"),
    Case("singular-tm", _two(offset=1.0, second_matrix="0 0 0 0 73 700"), None, "degenerate"),
    Case("gid-beyond-count",
         _post(_two(offset=1.0, second_resource="F_CLONE", second_clone_font=True, second_clone_distinct_cidtogid=True), _clone_gid_beyond_count),
         "unavailable", "gid out of range"),
    Case("clipped-away-twin",
         _post(_two(offset=1.0), lambda f: _split_bt_around_twin(f, "q 0 0 1 1 re W n", "Q")),
         "ambiguous", "display list culls fully clipped text: no window"),
    Case("alpha-zero-twin",
         _post(_two(offset=1.0), lambda f: (_set_resource(f, "ExtGState", "GS0", "<< /ca 0 /CA 0 >>"), _split_bt_around_twin(f, "q /GS0 gs", "Q"))),
         "exact_overlap_same_baseline", "invisible ink still counts"),
    Case("inline-image-between",
         _post(_two(offset=1.0), lambda f: _split_bt_around_twin(f, "q 10 0 0 10 200 200 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI Q", "")),
         "exact_overlap_same_baseline", "seqno alignment across fill_image"),
    Case("xobject-twice",
         _post(_two(offset=1.0), lambda f: (install_text_form_xobject(f, name="Fx1", text="再", fontsize=24.0, origin=(300.0, 200.0)), _split_bt_around_twin(f, "q /Fx1 Do Q q /Fx1 Do Q", ""))),
         "exact_overlap_same_baseline", "unattributed glyphs never decide"),
    Case("colour-flush", _post(_two(offset=1.0), lambda f: _insert_between_painters(f, "0 0 1 rg")),
         "exact_overlap_same_baseline", "two fz_texts"),
    Case("hidden-ocg-twin", _post(_two(offset=1.0), lambda f: hide_second_painter_in_ocg(f, on=False)),
         "ambiguous", "absent from the devices"),
    Case("abutting", _two(offset=SOURCE_WIDTH), "exact_safe", "side bearings"),
    Case("far-line", _two(offset=1.0, second_dy=-40.0), "exact_safe", "another line"),
    Case("raised-twin", _two(offset=1.0, second_rise=2.0 * FONTSIZE), None, "production rejects by rule"),
    Case("rise-cancelled", _two(offset=1.2, second_dy=-7.2, second_rise=7.2),
         "exact_overlap_same_baseline", "rise cancels the baseline shift"),
    Case("bigger-twin", _two(offset=-(SOURCE_WIDTH + 0.5), second_font_size=24.0),
         "exact_overlap_same_baseline", "its own size widens it onto the target"),
    Case("dangling-resource", _two(offset=1.0, second_dangling=True), "unavailable", "unresolvable font"),
    # Adversarial review (2026-09-02): degenerate control boxes on the
    # stroke ladder.  A rank-1 Tm collapses every outline onto the baseline;
    # Tr 1/2 strokes the collapsed path with the CTM-scaled pen (an 8 pt
    # bar over the target) while every outline oracle reports "empty" and
    # fz_bound_text drops empty rects (no stroke expansion, no +1).
    Case("collapsed-tm-stroke-tr1",
         _post(_two(offset=1.0, second_matrix="1 0 0 0 73 700"), lambda f: _insert_between_painters(f, "1 Tr 8 w")),
         "ambiguous", "review: rank-1 Tm + Tr 1 paints a pen bar"),
    Case("collapsed-tm-stroke-tr2",
         _post(_two(offset=1.0, second_matrix="1 0 0 0 73 700"), lambda f: _insert_between_painters(f, "2 Tr 8 w")),
         "ambiguous", "review: rank-1 Tm + Tr 2 paints a pen bar"),
    Case("collapsed-tm-fill-control", _two(offset=1.0, second_matrix="1 0 0 0 73 700"),
         "exact_safe", "review control: a filled collapsed outline paints nothing"),
    Case("degenerate-contour-stroke", _degenerate_clone(offset=1.0, chars=SOURCE, raw="1 Tr 6 w"),
         "ambiguous", "review: zero-height contour glyphs, identity Tm, stroked"),
    Case("degenerate-contour-fill-control", _degenerate_clone(offset=1.0, chars=SOURCE, raw=None),
         "exact_safe", "review control: zero-height contours filled paint nothing"),
    Case("degenerate-contour-mixed-stroke", _degenerate_clone(offset=1.0, chars=SOURCE[:1], raw="1 Tr 6 w"),
         "ambiguous", "review: one degenerate + one normal glyph, stroked"),
    # Raster-oracle blind spots named by the review: luminance >= 50% and
    # hairline strokes give an empty < 128 mask.  The exact arm is colour
    # blind, so these pin the arm's verdict while the raster stays silent.
    Case("grey-twin", _post(_two(offset=1.0), lambda f: _insert_between_painters(f, "0.6 g")),
         "exact_overlap_same_baseline", "review: raster mask blind to grey 153"),
    Case("hairline-stroke-twin", _post(_two(offset=1.0), lambda f: _insert_between_painters(f, "1 Tr 0.1 w")),
         "ambiguous", "review: hairline stroke, conservative overlap"),
]

# Replace the two placeholder Tz cases with real text-state edits.
CASES = [case for case in CASES if case.id not in ("tz80", "tz120-right", "tz-neg-left-mirrored")]
for tz, offset in ((80.0, SOURCE_WIDTH + 0.5), (120.0, SOURCE_WIDTH + 0.5), (120.0, -30.0), (-100.0, -0.5), (50.0, 1.0)):
    CASES.append(
        Case(
            f"tz{tz:+.0f}-at{offset:+.1f}",
            _post(_two(offset=offset), lambda f, tz=tz: _insert_between_painters(f, f"{tz:g} Tz")),
            None,
            "horizontal scaling sweep",
        )
    )

CASE_IDS = [case.id for case in CASES]
assert len(CASE_IDS) == len(set(CASE_IDS))


# ----------------------------------------------------------------- arms


@dataclass(frozen=True)
class Row:
    id: str
    overlap_pixels: int
    exact_kind: str
    exact_reason: str | None
    baseline_admits: bool
    reach_admits: bool
    target_ink_pixels: int = -1
    twin_ink_pixels: int = -1


def _production(fixture, expected_origin, *, reach: bool) -> bool:
    original = plan_module._painter_advance
    if reach:
        plan_module._painter_advance = lambda capability, show, text: None  # type: ignore[assignment]
    try:
        result = prepare_plan(
            fixture.doc,
            fixture.page,
            target_text=SOURCE,
            replacement_text=REPLACEMENT,
            expected_origin=expected_origin,
            target_bbox=None,
            registry=DocumentFontRegistry(fixture.doc),
            max_tier=1,
        )
    finally:
        plan_module._painter_advance = original
    return not isinstance(result, PlanRejection)


def _exact(fixture):
    shows = replay_shows(fixture)
    target = shows[0]
    twins = tuple(
        show for show in shows if show.seq != target.seq and show.decoded_bytes == target.decoded_bytes
    )
    evidence = build_page_painter_evidence(
        fixture.doc, fixture.page, registry=DocumentFontRegistry(fixture.doc)
    )
    try:
        return exact_duplicate_painter_verdict(evidence, target, twins)
    finally:
        evidence.release()


def _run_case(case: Case) -> Row:
    fixture, expected_origin = case.build()
    try:
        first, second = single_painter_masks(fixture)
        overlap = first.overlap_pixels(second)
        verdict = _exact(fixture)
        baseline = _production(fixture, expected_origin, reach=False)
        reach = _production(fixture, expected_origin, reach=True)
    finally:
        fixture.doc.close()
    return Row(
        case.id,
        overlap,
        verdict.kind,
        verdict.reason,
        baseline,
        reach,
        first.ink_pixels,
        second.ink_pixels,
    )


@pytest.fixture(scope="module")
def matrix() -> dict[str, Row]:
    return {case.id: _run_case(case) for case in CASES}


# ---------------------------------------------------------------- tests


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_exact_arm_never_reports_safe_when_rasters_overlap(case: Case, matrix) -> None:
    row = matrix[case.id]
    assert row.exact_kind in VERDICT_KINDS
    assert row.exact_kind != "error", row
    if row.overlap_pixels > 0:
        assert row.exact_kind != "exact_safe", row


@pytest.mark.parametrize("case", [c for c in CASES if c.expect is not None], ids=[c.id for c in CASES if c.expect is not None])
def test_exact_arm_kind_matches_the_pre_registered_expectation(case: Case, matrix) -> None:
    row = matrix[case.id]
    assert row.exact_kind == case.expect, row


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_exact_safe_implies_raster_disjoint(case: Case, matrix) -> None:
    row = matrix[case.id]
    if row.exact_kind == "exact_safe":
        assert row.overlap_pixels == 0, row


def test_safety_gate_zero_exact_false_safes_and_counted_production_false_safes(matrix) -> None:
    exact_false = [r.id for r in matrix.values() if r.overlap_pixels > 0 and r.exact_kind == "exact_safe"]
    baseline_false = sorted(r.id for r in matrix.values() if r.overlap_pixels > 0 and r.baseline_admits)
    reach_false = sorted(r.id for r in matrix.values() if r.overlap_pixels > 0 and r.reach_admits)
    assert exact_false == []
    # Known at the frozen tip: the 16 /W cases, the 2 core-band cases and
    # the F4 walk-back are baseline false admits; reach keeps the core band.
    assert len(baseline_false) >= 19, baseline_false
    assert set(reach_false) >= {"core-band-+7.3", "core-band--7.3"}, reach_false
    assert set(reach_false) <= set(baseline_false)


def test_value_wins_where_exact_is_safe_and_production_refuses(matrix) -> None:
    wins = sorted(
        r.id for r in matrix.values() if r.exact_kind == "exact_safe" and not r.baseline_admits
    )
    assert "pos-tc-gap-aggregate" in wins
    assert "tj-intra-kern-disjoint" in wins
    losses = sorted(
        r.id
        for r in matrix.values()
        if r.exact_kind in OVERLAP_KINDS and r.baseline_admits
    )
    assert set(losses) >= {"neg-tc-walkback", "core-band-+7.3", "core-band--7.3"}


# Rows whose TWIN leaves an empty < 128 ink mask, each for a stated reason:
# the raster oracle is blind there, so the two raster assertions above pass
# vacuously and only the pre-registered ``expect`` pins the exact arm.
TWIN_RASTER_BLIND = {
    "tz-zero": "Tz 0 collapses every glyph to a line; a fill paints nothing",
    "tfs-zero": "Tfs 0 paints nothing",
    "singular-tm": "zero Tm paints nothing",
    "collapsed-tm-fill-control": "rank-1 Tm, filled: zero-area path",
    "degenerate-contour-fill-control": "zero-height contours, filled",
    "clipped-away-twin": "clipped to a 1x1 pt corner",
    "alpha-zero-twin": "ca 0",
    "hidden-ocg-twin": "OFF optional content",
    "grey-twin": "grey 153 is above the 128 threshold",
    "custom-cmap-clone": "unresolvable CMap: MuPDF decodes no glyph",
    "gid-beyond-count": "gid >= numGlyphs renders nothing",
    "far-line": "twin sits 40 pt below the target-centred raster clip",
    # NOT blind (measured): a 0.1 pt stroke still darkens 1,293 px at 576
    # dpi (MuPDF widens hairlines to a device pixel), overlap 394 px.
}


def test_raster_oracle_blind_spots_are_exactly_the_pre_registered_rows(matrix) -> None:
    """Review finding: an empty mask lets both raster assertions pass
    vacuously.  Every such row must be named with its reason, and the
    target must always be visible."""
    blind = sorted(r.id for r in matrix.values() if r.twin_ink_pixels == 0)
    assert blind == sorted(TWIN_RASTER_BLIND), blind
    assert all(r.target_ink_pixels > 0 for r in matrix.values()), [
        r.id for r in matrix.values() if r.target_ink_pixels <= 0
    ]


def test_review_counterexamples_paint_over_the_target_and_are_never_safe(matrix) -> None:
    """The 2026-09-02 review's stroke-ladder counterexamples: the twin's
    stroked degenerate outline is real ink crossing the target."""
    for case_id in (
        "collapsed-tm-stroke-tr1",
        "collapsed-tm-stroke-tr2",
        "degenerate-contour-stroke",
        "degenerate-contour-mixed-stroke",
    ):
        row = matrix[case_id]
        assert row.twin_ink_pixels > 0, row
        assert row.overlap_pixels > 0, row
        assert row.exact_kind == "ambiguous", row
        assert row.exact_reason in {"degenerate_stroke", "conservative_overlap"}, row
    for case_id in ("collapsed-tm-fill-control", "degenerate-contour-fill-control"):
        row = matrix[case_id]
        assert row.twin_ink_pixels == 0, row
        assert row.exact_kind == "exact_safe", row
    assert matrix["degenerate-contour-stroke"].exact_reason == "degenerate_stroke"
    assert matrix["collapsed-tm-stroke-tr1"].exact_reason == "degenerate_stroke"
