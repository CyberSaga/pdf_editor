"""Task 13 Priority 2 — four-direction growth gates, red-first (P2-B part 3).

The census corpus contains all four cardinal visual directions (right
6,212 / left 123 / down 100 / up 5), so v1 ships all four — through ONE
shared cardinal ``growth_direction``, never four divergent verifiers and
never arbitrary-angle polygons.

Per direction (visual): the growth zone is the axis-aligned strip on the
FORWARD side of the target —

    right → target.x1 … verify.x1      left → verify.x0 … target.x0
    down  → target.y1 … verify.y1      up   → verify.y0 … target.y0

and every Tier 1 blank-growth proof must run against that strip: blank →
admit; a glyph, vector fill, image, or unprovable shading in the strip →
reject with the honest gate prefix; a uniform band that mismatches the
target's own background → reject; growth past the page edge →
``growth_outside_page``.  An obstacle BEHIND the baseline start must
NOT reject — forward-only proof, not an inflate-all-sides box.
(Reference-point SAMPLING POSITION is an implementation-phase
obligation, pinned when ``background_reference_points`` gains its
direction parameter — today's disjoint-from-halo(verify) filter already
excludes forward-side samples structurally; see the plan's P2-B record.)

Fixture geometry is authored in USER space along the baseline unit vector
(u), so every direction reuses the same arithmetic; the ``right`` case is
the census-dominant CAD idiom (/Rotate 270 page + compensating −90° Tm).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    REPLACEMENT_LONGER,
    Type0Fixture,
    append_page_content,
    build_identity_h_fixture,
    cid_for,
    install_image_xobject,
    install_shading_form_xobject,
    set_text_matrix,
)

ROT90 = (0.0, 1.0, -1.0, 0.0)
ROT180 = (-1.0, 0.0, 0.0, -1.0)
ROT270 = (0.0, -1.0, 1.0, 0.0)

_ADVANCE = 48.0  # 4 full-width chars at 12pt
_GROWTH = 12.0  # REPLACEMENT_LONGER adds one full-width char


@dataclass(frozen=True)
class _DirectionCase:
    slug: str  # the shared cardinal growth_direction contract value
    linear: tuple[float, float, float, float] | None  # Tm (None = identity)
    rotate: int  # page /Rotate
    origin: tuple[float, float]
    u: tuple[float, float]  # USER-space baseline unit vector
    edge_origin: tuple[float, float]  # puts the growth strip off-page
    # which visual bbox edge the growth moves: (index, sign)
    moved_edge: tuple[int, int]


_CASES = (
    _DirectionCase(
        slug="up",
        linear=ROT90,
        rotate=0,
        origin=(300.0, 400.0),
        u=(0.0, 1.0),
        edge_origin=(300.0, 788.0),
        moved_edge=(1, -1),
    ),
    _DirectionCase(
        slug="down",
        linear=ROT270,
        rotate=0,
        origin=(300.0, 400.0),
        u=(0.0, -1.0),
        edge_origin=(300.0, 54.0),
        moved_edge=(3, 1),
    ),
    _DirectionCase(
        slug="left",
        linear=ROT180,
        rotate=0,
        origin=(300.0, 400.0),
        u=(-1.0, 0.0),
        edge_origin=(54.0, 400.0),
        moved_edge=(0, -1),
    ),
    _DirectionCase(
        slug="right",  # the census-dominant CAD idiom
        linear=ROT270,
        rotate=270,
        origin=(300.0, 400.0),
        u=(0.0, -1.0),
        edge_origin=(300.0, 54.0),
        moved_edge=(2, 1),
    ),
)

_IDS = tuple(case.slug for case in _CASES)


def _fixture(case: _DirectionCase, *, origin: tuple[float, float] | None = None) -> Type0Fixture:
    fixture = build_identity_h_fixture(
        rotate=case.rotate, origin=origin or case.origin
    )
    if case.linear is not None:
        set_text_matrix(fixture, case.linear)
    return fixture


def _along(case: _DirectionCase, distance: float) -> tuple[float, float]:
    ox, oy = case.origin
    return (ox + case.u[0] * distance, oy + case.u[1] * distance)


def _square(center: tuple[float, float], half: float = 5.0) -> str:
    x0 = center[0] - half
    y0 = center[1] - half
    return f"{x0:g} {y0:g} {2 * half:g} {2 * half:g}"


def _strip_bbox(
    case: _DirectionCase, start: float, end: float, cross: float = 16.0
) -> tuple[float, float, float, float]:
    """USER-space axis-aligned bbox covering ``start``..``end`` points along
    the baseline (from the origin), ±``cross`` across it."""
    p0 = _along(case, start)
    p1 = _along(case, end)
    cross_x = cross * abs(case.u[1])
    cross_y = cross * abs(case.u[0])
    return (
        min(p0[0], p1[0]) - cross_x,
        min(p0[1], p1[1]) - cross_y,
        max(p0[0], p1[0]) + cross_x,
        max(p0[1], p1[1]) + cross_y,
    )


def _prepare(
    fixture: Type0Fixture,
) -> tuple[TieredCommitEngine, PreparedEdit | PlanRejection]:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_LONGER,
        expected_origin=None,
    )
    return engine, result


def _assert_growth_rejected(
    result: PreparedEdit | PlanRejection, detail_prefix: str
) -> PlanRejection:
    assert isinstance(result, PlanRejection), (
        f"expected a growth rejection ({detail_prefix}…), got a PreparedEdit"
    )
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK, (
        result.reason,
        result.detail,
    )
    assert result.detail.startswith(detail_prefix), result.detail
    return result


# ==========================================================================
# Blank strip → admit, growth on the correct visual edge, commit
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_blank_growth_strip_admits_and_commits(case: _DirectionCase) -> None:
    fixture = _fixture(case)
    engine, result = _prepare(fixture)
    assert isinstance(result, PreparedEdit), (
        getattr(result, "reason", None),
        getattr(result, "detail", None),
    )
    assert result.has_ink_growth is True
    assert result.growth_direction == case.slug
    target = result.target_bbox_page
    verify = result.effective_verify_bbox
    index, sign = case.moved_edge
    moved = verify[index] - target[index]
    assert sign * moved == pytest.approx(_GROWTH, abs=0.2), (
        case.slug,
        target,
        verify,
    )
    for other in range(4):
        if other != index:
            assert verify[other] == pytest.approx(target[other], abs=0.2), (
                case.slug,
                other,
            )
    outcome = engine.commit(result)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        outcome.degraded_reason,
    )
    assert "tier1_ink_growth" in outcome.warnings
    fixture.doc.close()


# ==========================================================================
# A neighbour glyph in the strip → the GLYPH gate refuses (honest prefix)
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_glyph_in_growth_strip_is_rejected(case: _DirectionCase) -> None:
    fixture = _fixture(case)
    cx, cy = _along(case, _ADVANCE + _GROWTH / 2.0)
    glyph = cid_for("大")
    append_page_content(
        fixture,
        f"BT /{fixture.resource_name} 12 Tf "
        f"1 0 0 1 {cx - 6.0:g} {cy - 6.0:g} Tm <{glyph:04X}> Tj ET",
    )
    _, result = _prepare(fixture)
    _assert_growth_rejected(result, "glyphs:")
    fixture.doc.close()


# ==========================================================================
# A vector fill in the strip → the occupancy gate refuses
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_vector_fill_in_growth_strip_is_rejected(case: _DirectionCase) -> None:
    fixture = _fixture(case)
    square = _square(_along(case, _ADVANCE + _GROWTH / 2.0))
    append_page_content(fixture, f"0 0 0 rg {square} re f")
    _, result = _prepare(fixture)
    _assert_growth_rejected(result, "occupancy:")
    fixture.doc.close()


# ==========================================================================
# An image in the strip → the occupancy gate refuses
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_image_in_growth_strip_is_rejected(case: _DirectionCase) -> None:
    fixture = _fixture(case)
    install_image_xobject(fixture, name="Im7Q", rgb=(255, 0, 0))
    cx, cy = _along(case, _ADVANCE + _GROWTH / 2.0)
    append_page_content(
        fixture, f"q 10 0 0 10 {cx - 5.0:g} {cy - 5.0:g} cm /Im7Q Do Q"
    )
    _, result = _prepare(fixture)
    _assert_growth_rejected(result, "occupancy:")
    fixture.doc.close()


# ==========================================================================
# A page-level shading (bounds unprovable) → the occupancy gate refuses
# ==========================================================================


def _install_page_shading(
    fixture: Type0Fixture, name: str, bbox: tuple[float, float, float, float]
) -> None:
    doc = fixture.doc
    x0, y0, x1, y1 = bbox
    shading_xref = doc.get_new_xref()
    doc.update_object(
        shading_xref,
        "<< /ShadingType 2 /ColorSpace /DeviceRGB "
        f"/Coords [{x0:g} {y0:g} {x1:g} {y1:g}] /Extend [true true] "
        "/Function << /FunctionType 2 /Domain [0 1] "
        "/C0 [0 0 0] /C1 [0 0 0] /N 1 >> >>",
    )
    owner = fixture.page.xref
    prefix: list[str] = []
    for part in ("Resources", "Shading"):
        kind, value = doc.xref_get_key(owner, "/".join([*prefix, part]))
        if kind == "xref":
            owner = int(value.split()[0])
            prefix = []
        else:
            prefix.append(part)
    doc.xref_set_key(
        owner, "/".join([*prefix, name]), f"{shading_xref} 0 R"
    )


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_page_shading_makes_growth_unprovable(case: _DirectionCase) -> None:
    fixture = _fixture(case)
    strip = _strip_bbox(case, _ADVANCE, _ADVANCE + _GROWTH)
    _install_page_shading(fixture, "Shpg7Q", strip)
    append_page_content(fixture, "q /Shpg7Q sh Q")
    _, result = _prepare(fixture)
    _assert_growth_rejected(result, "occupancy:")
    fixture.doc.close()


# ==========================================================================
# A uniform band that mismatches the target's own background → the raster
# background gate refuses ON ITS OWN (the band is a Form-XObject shading —
# invisible to every cheap occupancy gate, the proven Tier 1 fixture shape)
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_uniform_mismatched_band_is_rejected_by_the_background_gate(
    case: _DirectionCase,
) -> None:
    fixture = _fixture(case)
    band = _strip_bbox(case, _ADVANCE + 0.5, _ADVANCE + 22.0)
    install_shading_form_xobject(fixture, name="Fx7Q", bbox=band)
    append_page_content(fixture, "/Fx7Q Do")
    assert fixture.page.get_drawings() == []
    assert fixture.page.get_images(full=True) == []
    _, result = _prepare(fixture)
    _assert_growth_rejected(result, "background:")
    fixture.doc.close()


# ==========================================================================
# Growth past the page edge → growth_outside_page
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_growth_past_the_page_edge_is_rejected(case: _DirectionCase) -> None:
    fixture = _fixture(case, origin=case.edge_origin)
    _, result = _prepare(fixture)
    assert isinstance(result, PlanRejection), (
        "growth escaping the page must never be accepted"
    )
    assert result.reason == RejectReason.GROWTH_OUTSIDE_PAGE, (
        result.reason,
        result.detail,
    )
    fixture.doc.close()


# ==========================================================================
# Forward-only proof: an obstacle BEHIND the baseline start must not reject
# (kills any "inflate the box on all sides" implementation)
# ==========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_obstacle_behind_the_baseline_start_still_admits(
    case: _DirectionCase,
) -> None:
    fixture = _fixture(case)
    square = _square(_along(case, -20.0))
    append_page_content(fixture, f"0 0 0 rg {square} re f")
    engine, result = _prepare(fixture)
    assert isinstance(result, PreparedEdit), (
        getattr(result, "reason", None),
        getattr(result, "detail", None),
    )
    outcome = engine.commit(result)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        outcome.degraded_reason,
    )
    fixture.doc.close()
