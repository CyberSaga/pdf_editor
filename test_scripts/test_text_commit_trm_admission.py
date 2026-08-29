"""Task 13 Priority 2 — rotated-TRM admission red matrix (P2-B part 1).

Promotes the census taxonomy (plan §7, measured 2026-08-19: 6,413/6,417
uniform rotations are visual quarter-turn) into the production admission
gate, red-first.  The core contract: Priority 2 is NOT "allow rotated
matrices" — it is "make the whole geometric proof chain run along the
transformed text baseline", and ONLY for the census-locked quarter-turn
family (positive-orientation uniform rotation+scale whose visual baseline
is cardinal).

- Part A pins the SEVEN new stable reject codes verbatim (house rule: the
  test keeps its own literal constants; a rename in dto.py must fail here,
  never silently follow).
- Part B pins the production classifier module
  ``model/text_commit/transforms.py`` — the single source replay/inspect/
  plan/verify and the census script must all share: combined ``Tm × CTM``
  shape proof with FIXED gate precedence (finite → singular → absolute
  scale floor → positive orientation → orthogonal axes → equal axis norms
  → cardinal visual direction), RELATIVE 1e-6 tolerance proven at three
  scales with just-inside/just-outside boundaries, visual baseline
  direction through ``transformation_matrix × rotation_matrix`` (visual y
  down), and the text-space→visual quad mapping the geometry rework rides.
- Part C pins the admissions at ``TieredCommitEngine.prepare`` level on
  synthetic Identity-H fixtures: quarter-turn uniform rotations admit (and
  commit byte-exactly), rotations split across ``Tm`` and ``CTM`` admit by
  their combined shape, every defect class keeps a fail-closed rejection
  with its own literal ``trm_*`` code, and the existing axis-aligned
  behavior plus the residual text-state gates stay unchanged.

Data policy (plan §10): fixtures are synthetic; rejection details must
speak in stable codes/slugs only and never echo matrix coefficients.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    CJK_TEXT,
    REPLACEMENT_EQUAL_ADVANCE,
    Type0Fixture,
    build_identity_h_fixture,
    set_text_matrix,
    wrap_content_in_cm,
)

# --------------------------------------------------------------------------
# THE contract these red tests pin: one stable code per independent gate,
# in the FIXED precedence order below (first failing gate wins, always).
# --------------------------------------------------------------------------
TRM_NON_FINITE = "trm_non_finite"
TRM_SINGULAR = "trm_singular"
TRM_SCALE_BELOW_FLOOR = "trm_scale_below_floor"
TRM_REFLECTED = "trm_reflected"
TRM_SHEARED = "trm_sheared"
TRM_NON_UNIFORM_SCALE = "trm_non_uniform_scale"
TRM_ROTATION_NOT_QUARTER_TURN = "trm_rotation_not_quarter_turn"

_ALL_TRM_CODES = (
    TRM_NON_FINITE,
    TRM_SINGULAR,
    TRM_SCALE_BELOW_FLOOR,
    TRM_REFLECTED,
    TRM_SHEARED,
    TRM_NON_UNIFORM_SCALE,
    TRM_ROTATION_NOT_QUARTER_TURN,
)

_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Exact quarter-turn linears (no float noise: these are the admissible v1
# family, written the way a CAD export writes them).
ROT90 = (0.0, 1.0, -1.0, 0.0)
ROT180 = (-1.0, 0.0, 0.0, -1.0)
ROT270 = (0.0, -1.0, 1.0, 0.0)


def _rot(degrees: float, scale: float = 1.0) -> tuple[float, float, float, float]:
    r = math.radians(degrees)
    return (
        math.cos(r) * scale,
        math.sin(r) * scale,
        -math.sin(r) * scale,
        math.cos(r) * scale,
    )


def _tm(linear: tuple[float, float, float, float], e: float = 0.0, f: float = 0.0):
    return (linear[0], linear[1], linear[2], linear[3], e, f)


def _transforms():
    """The production classifier module this red matrix brings into being."""
    from model.text_commit import transforms

    return transforms


def _plain_page(rotate: int = 0) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if rotate:
        page.set_rotation(rotate)
    return doc, page


def _prepare(
    fixture: Type0Fixture,
    *,
    replacement: str = REPLACEMENT_EQUAL_ADVANCE,
    max_tier: int = 1,
) -> PreparedEdit | PlanRejection:
    engine = TieredCommitEngine(fixture.doc, max_tier=max_tier)
    return engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=replacement,
        expected_origin=None,
    )


def _prepare_with_engine(
    fixture: Type0Fixture, *, max_tier: int = 1
) -> tuple[TieredCommitEngine, PreparedEdit | PlanRejection]:
    engine = TieredCommitEngine(fixture.doc, max_tier=max_tier)
    result = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
    )
    return engine, result


def _assert_rejected(
    result: PreparedEdit | PlanRejection, reason: str
) -> PlanRejection:
    assert isinstance(result, PlanRejection), (
        f"expected a PlanRejection({reason}), got a PreparedEdit"
    )
    assert result.reason == reason, (result.reason, result.detail)
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


def test_trm_reject_reason_constants_exist_verbatim() -> None:
    assert RejectReason.TRM_NON_FINITE == TRM_NON_FINITE
    assert RejectReason.TRM_SINGULAR == TRM_SINGULAR
    assert RejectReason.TRM_SCALE_BELOW_FLOOR == TRM_SCALE_BELOW_FLOOR
    assert RejectReason.TRM_REFLECTED == TRM_REFLECTED
    assert RejectReason.TRM_SHEARED == TRM_SHEARED
    assert RejectReason.TRM_NON_UNIFORM_SCALE == TRM_NON_UNIFORM_SCALE
    assert (
        RejectReason.TRM_ROTATION_NOT_QUARTER_TURN
        == TRM_ROTATION_NOT_QUARTER_TURN
    )
    # Seven distinct codes, and none reuses an existing emission site's code
    # (a reused code lets a test survive deletion of its own gate).
    assert len(set(_ALL_TRM_CODES)) == 7
    assert RejectReason.UNSUPPORTED_TEXT_STATE not in _ALL_TRM_CODES
    assert RejectReason.MALFORMED_STREAM not in _ALL_TRM_CODES


# ==========================================================================
# Part B — the production classifier module (transforms.py), the single
# source the census script must delegate to and production must share
# ==========================================================================


def test_transforms_is_a_model_leaf_that_never_imports_scripts() -> None:
    transforms = _transforms()
    source = Path(transforms.__file__).read_text(encoding="utf-8")
    assert "import scripts" not in source and "from scripts" not in source, (
        "production classifier must never depend on census tooling"
    )


def test_census_taxonomy_delegates_to_the_production_classifier() -> None:
    """scripts/trm_taxonomy.py must become a thin delegate — one predicate,
    not two near-identical ones that drift apart."""
    import scripts.trm_taxonomy as taxonomy

    _transforms()  # the delegate target must exist
    source = Path(taxonomy.__file__).read_text(encoding="utf-8")
    assert "model.text_commit.transforms" in source, (
        "census classifier must delegate to the production module"
    )


def test_census_shape_slugs_and_production_codes_cannot_drift() -> None:
    """Behavioral no-drift pin: on a probe grid covering every shape class,
    the census slug and the production shape verdict must correspond."""
    import scripts.trm_taxonomy as taxonomy

    transforms = _transforms()
    slug_to_code = {
        taxonomy.SHAPE_NON_FINITE: TRM_NON_FINITE,
        taxonomy.SHAPE_SINGULAR: TRM_SINGULAR,
        taxonomy.SHAPE_REFLECTED: TRM_REFLECTED,
        taxonomy.SHAPE_SHEARED: TRM_SHEARED,
        taxonomy.SHAPE_NON_UNIFORM_SCALE: TRM_NON_UNIFORM_SCALE,
        taxonomy.SHAPE_AXIS_ALIGNED: None,
        taxonomy.SHAPE_UNIFORM_ROTATED: None,
    }
    probes = [
        (1.0, 0.0, 0.0, 1.0),
        (2.0, 0.0, 0.0, 2.0),
        ROT90,
        ROT180,
        ROT270,
        _rot(30.0),
        _rot(45.0, 2.0),
        (math.nan, 0.0, 0.0, 1.0),
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, -1.0),
        (0.0, 1.0, 1.0, 0.0),
        (1.0, 0.0, 0.5, 1.0),
        (2.0, 0.0, 0.0, 1.0),
    ]
    for linear in probes:
        slug = taxonomy.classify_user_matrix(linear)
        expected = slug_to_code[slug]
        # The absolute floor sits outside the census shape taxonomy (it was
        # a predicted-chain gate there); above-floor probes must agree.
        assert transforms.shape_reject_reason(linear) == expected, (
            linear,
            slug,
        )


def test_transforms_tolerances_are_pinned() -> None:
    transforms = _transforms()
    assert transforms.REL_TOL == 1e-6
    assert transforms.ABS_SCALE_FLOOR == 1e-6


def test_shape_admits_the_uniform_family_at_every_scale() -> None:
    transforms = _transforms()
    for scale in (1e-3, 1.0, 1e3):
        for degrees in (0.0, 90.0, 180.0, 270.0, 30.0, 45.0):
            linear = _rot(degrees, scale)
            assert transforms.shape_reject_reason(linear) is None, (
                degrees,
                scale,
            )
    # Angle-blindness is the point: quarter-turn vs oblique is the visual
    # DIRECTION dimension's job, never the user-space shape gate's.


def test_shape_single_defect_classes_at_every_scale() -> None:
    transforms = _transforms()
    for s in (1e-3, 1.0, 1e3):
        assert (
            transforms.shape_reject_reason((math.nan, 0.0, 0.0, s))
            == TRM_NON_FINITE
        )
        assert (
            transforms.shape_reject_reason((math.inf, 0.0, 0.0, s))
            == TRM_NON_FINITE
        )
        assert (
            transforms.shape_reject_reason((0.0, 0.0, 0.0, 0.0))
            == TRM_SINGULAR
        )
        assert (
            transforms.shape_reject_reason((s, 0.0, 0.0, -s)) == TRM_REFLECTED
        )
        assert (
            transforms.shape_reject_reason((s, 0.0, 0.5 * s, s)) == TRM_SHEARED
        )
        assert (
            transforms.shape_reject_reason((2.0 * s, 0.0, 0.0, s))
            == TRM_NON_UNIFORM_SCALE
        )


def test_shape_singular_boundary_is_relative_at_three_scales() -> None:
    transforms = _transforms()
    for s in (1e-3, 1.0, 1e3):
        # det / scale² == 9e-7: just inside the singularity tolerance.
        assert (
            transforms.shape_reject_reason((s, 0.0, 0.0, s * 9e-7))
            == TRM_SINGULAR
        ), s
        # det / scale² == 1.1e-6: provably non-singular — the matrix then
        # fails the equal-axis-norms gate instead (precedence-informative).
        assert (
            transforms.shape_reject_reason((s, 0.0, 0.0, s * 1.1e-6))
            == TRM_NON_UNIFORM_SCALE
        ), s


def test_shape_shear_boundary_is_relative_at_three_scales() -> None:
    transforms = _transforms()
    for s in (1e-3, 1.0, 1e3):
        # |a·c + b·d| / scale² == 9e-7: inside tolerance — admitted.
        assert (
            transforms.shape_reject_reason((s, 0.0, s * 9e-7, s)) is None
        ), s
        # 1.1e-6: outside — sheared.
        assert (
            transforms.shape_reject_reason((s, 0.0, s * 1.1e-6, s))
            == TRM_SHEARED
        ), s


def test_shape_axis_norm_boundary_is_relative_at_three_scales() -> None:
    transforms = _transforms()
    for s in (1e-3, 1.0, 1e3):
        assert (
            transforms.shape_reject_reason((s, 0.0, 0.0, s * (1.0 + 9e-7)))
            is None
        ), s
        assert (
            transforms.shape_reject_reason((s, 0.0, 0.0, s * (1.0 + 1.1e-6)))
            == TRM_NON_UNIFORM_SCALE
        ), s


def test_shape_scale_floor_is_absolute_not_relative() -> None:
    transforms = _transforms()
    # A perfectly uniform matrix below the absolute floor: relatively clean
    # (every relative gate passes), absolutely degenerate.
    assert (
        transforms.shape_reject_reason((5e-7, 0.0, 0.0, 5e-7))
        == TRM_SCALE_BELOW_FLOOR
    )
    assert (
        transforms.shape_reject_reason((0.0, 5e-7, -5e-7, 0.0))
        == TRM_SCALE_BELOW_FLOOR
    )
    # Exactly at the floor rejects (closed boundary, mirroring replay's
    # ``a <= _EPS`` absolute floor).
    assert (
        transforms.shape_reject_reason((1e-6, 0.0, 0.0, 1e-6))
        == TRM_SCALE_BELOW_FLOOR
    )
    # Just above the floor admits; small-but-legitimate scales (1e-3) are
    # far above an ABSOLUTE floor even though they'd die against a page-
    # sized relative one.
    assert transforms.shape_reject_reason((2e-6, 0.0, 0.0, 2e-6)) is None
    assert transforms.shape_reject_reason((1e-3, 0.0, 0.0, 1e-3)) is None


def test_shape_gate_precedence_on_dual_defect_matrices() -> None:
    transforms = _transforms()
    # finite beats orientation
    assert (
        transforms.shape_reject_reason((math.nan, 0.0, 0.0, -1.0))
        == TRM_NON_FINITE
    )
    # singular beats the floor
    assert (
        transforms.shape_reject_reason((1e-9, 0.0, 0.0, 0.0)) == TRM_SINGULAR
    )
    # the floor beats orthogonality (tiny AND sheared → floor)
    assert (
        transforms.shape_reject_reason((5e-7, 0.0, 5e-7, 5e-7))
        == TRM_SCALE_BELOW_FLOOR
    )
    # orientation beats DIRECTION: the quarter-turn MIRROR is reflected,
    # never "rotation" anything (it is orthogonal with equal norms, so the
    # orientation-vs-orthogonality order needs its own probe below)
    assert transforms.shape_reject_reason((0.0, 1.0, 1.0, 0.0)) == TRM_REFLECTED
    # orientation beats orthogonality: reflected AND sheared → reflected
    # (a shear-before-reflection implementation fails here)
    assert (
        transforms.shape_reject_reason((1.0, 0.0, 0.5, -1.0)) == TRM_REFLECTED
    )
    # orthogonality beats equal norms
    assert (
        transforms.shape_reject_reason((1.0, 0.0, 0.5, 2.0)) == TRM_SHEARED
    )


def test_visual_direction_unrotated_page_quarter_turns() -> None:
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        assert transforms.visual_baseline_direction(page, (1.0, 0.0, 0.0, 1.0)) == "right"
        assert transforms.visual_baseline_direction(page, ROT90) == "up"
        assert transforms.visual_baseline_direction(page, ROT180) == "left"
        assert transforms.visual_baseline_direction(page, ROT270) == "down"
        assert transforms.visual_baseline_direction(page, _rot(30.0)) == "oblique"
        assert (
            transforms.visual_baseline_direction(page, (0.0, 0.0, 0.0, 0.0))
            == "degenerate"
        )
        assert (
            transforms.visual_baseline_direction(page, (math.nan, 0.0, 0.0, 1.0))
            == "degenerate"
        )
    finally:
        doc.close()


def test_visual_direction_rotated_pages_truth_table() -> None:
    """The full /Rotate × quarter-turn-Tm table (numerically verified via
    ``transformation_matrix × rotation_matrix``, visual y down)."""
    transforms = _transforms()
    table = {
        0: {0: "right", 90: "up", 180: "left", 270: "down"},
        90: {0: "down", 90: "right", 180: "up", 270: "left"},
        180: {0: "left", 90: "down", 180: "right", 270: "up"},
        270: {0: "up", 90: "left", 180: "down", 270: "right"},
    }
    quarter = {0: (1.0, 0.0, 0.0, 1.0), 90: ROT90, 180: ROT180, 270: ROT270}
    for page_rot, row in table.items():
        doc, page = _plain_page(rotate=page_rot)
        try:
            for tm_deg, expected in row.items():
                assert (
                    transforms.visual_baseline_direction(page, quarter[tm_deg])
                    == expected
                ), (page_rot, tm_deg)
        finally:
            doc.close()


def test_visual_direction_cardinal_boundary_is_relative() -> None:
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        for scale in (1e-3, 1.0, 1e3):
            inside = _rot(90.0 + math.degrees(9e-7), scale)
            outside = _rot(90.0 + math.degrees(1.1e-6), scale)
            assert transforms.visual_baseline_direction(page, inside) == "up", scale
            assert (
                transforms.visual_baseline_direction(page, outside) == "oblique"
            ), scale
    finally:
        doc.close()


def test_admission_verdict_admits_quarter_turns_with_direction_and_scale() -> None:
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        verdict = transforms.admission_verdict(page, _tm(ROT90, 100.0, 200.0), _IDENTITY)
        assert verdict.reject_reason is None
        assert verdict.direction == "up"
        assert verdict.scale == pytest.approx(1.0)

        scaled = transforms.admission_verdict(
            page, _tm(_rot(270.0, 3.0), 100.0, 200.0), _IDENTITY
        )
        assert scaled.reject_reason is None
        assert scaled.direction == "down"
        assert scaled.scale == pytest.approx(3.0)
    finally:
        doc.close()


def test_admission_verdict_rejects_oblique_rotations_only_at_the_last_gate() -> None:
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        for degrees in (30.0, 45.0):
            verdict = transforms.admission_verdict(
                page, _tm(_rot(degrees)), _IDENTITY
            )
            assert verdict.reject_reason == TRM_ROTATION_NOT_QUARTER_TURN, degrees
            assert verdict.direction is None
        # Shape defects keep their own code even when the direction happens
        # to be cardinal: the mirror never reaches the rotation gate.
        mirror = transforms.admission_verdict(
            page, _tm((0.0, 1.0, 1.0, 0.0)), _IDENTITY
        )
        assert mirror.reject_reason == TRM_REFLECTED
    finally:
        doc.close()


def test_shape_defects_win_even_when_the_direction_is_oblique() -> None:
    """The shape gates precede the cardinal-direction gate for OBLIQUE
    baselines too: a direction-first implementation that short-circuits
    oblique matrices into trm_rotation_not_quarter_turn fails here."""
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        c30 = math.cos(math.radians(30.0))
        s30 = math.sin(math.radians(30.0))
        # Orthogonal, det > 0, row norms 2 vs 1, baseline 30° oblique:
        # the equal-axis-norms gate owns it, never the direction gate.
        nonuniform_oblique = (2.0 * c30, 2.0 * s30, -s30, c30)
        assert (
            transforms.shape_reject_reason(nonuniform_oblique)
            == TRM_NON_UNIFORM_SCALE
        )
        verdict = transforms.admission_verdict(
            page, _tm(nonuniform_oblique), _IDENTITY
        )
        assert verdict.reject_reason == TRM_NON_UNIFORM_SCALE
        # Sheared with an oblique baseline: the orthogonality gate owns it.
        sheared_oblique = (1.0, 0.3, 0.5, 1.0)
        assert (
            transforms.shape_reject_reason(sheared_oblique) == TRM_SHEARED
        )
        verdict = transforms.admission_verdict(
            page, _tm(sheared_oblique), _IDENTITY
        )
        assert verdict.reject_reason == TRM_SHEARED
    finally:
        doc.close()


def test_admission_verdict_proves_the_combined_tm_ctm_shape() -> None:
    """Two 45° halves combine to one admissible quarter turn; the same 45°
    alone stays out.  The proof object is ``Tm × CTM``, never ``Tm``."""
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        split = transforms.admission_verdict(
            page, _tm(_rot(45.0)), _tm(_rot(45.0))
        )
        assert split.reject_reason is None
        assert split.direction == "up"
        alone = transforms.admission_verdict(page, _tm(_rot(45.0)), _IDENTITY)
        assert alone.reject_reason == TRM_ROTATION_NOT_QUARTER_TURN
    finally:
        doc.close()


def test_admission_verdict_cad_idiom_rotate270_with_compensating_tm() -> None:
    transforms = _transforms()
    doc, page = _plain_page(rotate=270)
    try:
        verdict = transforms.admission_verdict(page, _tm(ROT270), _IDENTITY)
        assert verdict.reject_reason is None
        assert verdict.direction == "right"
    finally:
        doc.close()


def test_admission_verdict_overflow_to_infinity_is_non_finite() -> None:
    """The one non-finite shape a real PDF can produce: two large finite
    halves whose product overflows."""
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        verdict = transforms.admission_verdict(
            page, _tm((1e200, 0.0, 0.0, 1e200)), _tm((1e200, 0.0, 0.0, 1e200))
        )
        assert verdict.reject_reason == TRM_NON_FINITE
    finally:
        doc.close()


def test_map_text_quad_to_visual_hand_computed_axis_aligned() -> None:
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        bounds = transforms.map_text_quad_to_visual(
            page, (1.0, 0.0, 0.0, 1.0, 72.0, 700.0), _IDENTITY, (0.0, -4.2, 48.0, 12.0)
        )
        assert bounds[0] == pytest.approx(72.0)
        assert bounds[1] == pytest.approx(842.0 - 712.0)
        assert bounds[2] == pytest.approx(120.0)
        assert bounds[3] == pytest.approx(842.0 - 695.8)
    finally:
        doc.close()


def test_map_text_quad_to_visual_hand_computed_rotated_tm() -> None:
    """90° Tm at (100, 200) on an unrotated page: the advance runs UP the
    page (visual y shrinks), ascent extends to the LEFT — hand-derived."""
    transforms = _transforms()
    doc, page = _plain_page()
    try:
        bounds = transforms.map_text_quad_to_visual(
            page, (0.0, 1.0, -1.0, 0.0, 100.0, 200.0), _IDENTITY, (0.0, -4.2, 48.0, 12.0)
        )
        assert bounds[0] == pytest.approx(88.0)
        assert bounds[1] == pytest.approx(842.0 - 248.0)
        assert bounds[2] == pytest.approx(104.2)
        assert bounds[3] == pytest.approx(842.0 - 200.0)
    finally:
        doc.close()


def test_map_text_quad_to_visual_folds_the_page_rotation_matrix() -> None:
    """On a /Rotate 270 page the mapping must ride the SAME chain the
    verifier's pixmaps use (``transformation_matrix × rotation_matrix``) —
    ``transformation_matrix`` alone omits /Rotate (the known pitfall)."""
    transforms = _transforms()
    doc, page = _plain_page(rotate=270)
    try:
        tm = (0.0, -1.0, 1.0, 0.0, 72.0, 700.0)
        quad = (0.0, -4.2, 48.0, 12.0)
        bounds = transforms.map_text_quad_to_visual(page, tm, _IDENTITY, quad)
        visual = page.transformation_matrix * page.rotation_matrix
        xs: list[float] = []
        ys: list[float] = []
        for tx, ty in (
            (quad[0], quad[1]),
            (quad[2], quad[1]),
            (quad[0], quad[3]),
            (quad[2], quad[3]),
        ):
            ux = tm[0] * tx + tm[2] * ty + tm[4]
            uy = tm[1] * tx + tm[3] * ty + tm[5]
            vx = ux * visual.a + uy * visual.c + visual.e
            vy = ux * visual.b + uy * visual.d + visual.f
            xs.append(vx)
            ys.append(vy)
        assert bounds[0] == pytest.approx(min(xs))
        assert bounds[1] == pytest.approx(min(ys))
        assert bounds[2] == pytest.approx(max(xs))
        assert bounds[3] == pytest.approx(max(ys))
    finally:
        doc.close()


# ==========================================================================
# Part C — admissions at prepare level
# ==========================================================================


def _rotated_fixture(
    linear: tuple[float, float, float, float],
    *,
    rotate: int = 0,
    origin: tuple[float, float] = (200.0, 400.0),
) -> Type0Fixture:
    fixture = build_identity_h_fixture(rotate=rotate, origin=origin)
    set_text_matrix(fixture, linear)
    return fixture


def _committed_stream_is_a_byte_exact_splice(
    fixture: Type0Fixture, prepared: PreparedEdit, before: bytes
) -> None:
    replacement = prepared.replacement
    expected = (
        before[: replacement.start]
        + replacement.replacement_bytes
        + before[replacement.end :]
    )
    assert fixture.content_bytes() == expected, (
        "commit must be exactly the planned splice — nothing else moves"
    )


@pytest.mark.parametrize("linear", [ROT90, ROT180, ROT270], ids=["90", "180", "270"])
def test_quarter_turn_tm_admits_and_commits_byte_exactly(
    linear: tuple[float, float, float, float],
) -> None:
    fixture = _rotated_fixture(linear)
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        getattr(outcome, "degraded_reason", None),
    )
    _committed_stream_is_a_byte_exact_splice(fixture, prepared, before)
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    extracted = "".join(reopened[0].get_text().split())
    assert REPLACEMENT_EQUAL_ADVANCE in extracted
    assert CJK_TEXT not in extracted
    reopened.close()


def test_scaled_quarter_turn_tm_admits(  # rotation + uniform scale together
) -> None:
    fixture = _rotated_fixture(_rot(90.0, 2.0), origin=(300.0, 300.0))
    _assert_prepared(_prepare(fixture))
    fixture.doc.close()


def test_cad_idiom_rotate270_page_with_compensating_tm_admits_and_commits() -> None:
    """The census-dominant corpus shape: /Rotate 270 page, −90° Tm, visual
    baseline right (6,212 of 6,413 quarter-turn candidates)."""
    fixture = _rotated_fixture(ROT270, rotate=270)
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED
    fixture.doc.close()


def test_rotation_split_between_tm_and_ctm_admits() -> None:
    """45° in the Tm times 45° in the CTM is one admissible quarter turn:
    the gate proves ``Tm × CTM``, never the ``Tm`` alone."""
    fixture = _rotated_fixture(_rot(45.0), origin=(72.0, 700.0))
    wrap_content_in_cm(fixture, _rot(45.0), translate=(500.0, 100.0))
    _assert_prepared(_prepare(fixture))
    fixture.doc.close()


def test_rotation_purely_in_the_ctm_admits() -> None:
    fixture = build_identity_h_fixture(origin=(200.0, 100.0))
    wrap_content_in_cm(fixture, ROT90, translate=(500.0, 100.0))
    _assert_prepared(_prepare(fixture))
    fixture.doc.close()


def test_oblique_rotation_is_rejected_as_not_quarter_turn() -> None:
    for degrees in (30.0, 45.0):
        fixture = _rotated_fixture(_rot(degrees), origin=(300.0, 400.0))
        _assert_rejected(_prepare(fixture), TRM_ROTATION_NOT_QUARTER_TURN)
        fixture.doc.close()


def test_reflected_tm_is_rejected() -> None:
    fixture = _rotated_fixture((1.0, 0.0, 0.0, -1.0))
    _assert_rejected(_prepare(fixture), TRM_REFLECTED)
    fixture.doc.close()


def test_quarter_turn_mirror_is_rejected_as_reflected_not_rotation() -> None:
    """Gate precedence at prepare level: the mirror's direction is cardinal
    but its orientation is negative — the earlier gate owns the code."""
    fixture = _rotated_fixture((0.0, 1.0, 1.0, 0.0))
    _assert_rejected(_prepare(fixture), TRM_REFLECTED)
    fixture.doc.close()


def test_sheared_tm_is_rejected() -> None:
    fixture = _rotated_fixture((1.0, 0.0, 0.5, 1.0))
    _assert_rejected(_prepare(fixture), TRM_SHEARED)
    fixture.doc.close()


def test_non_uniform_scale_tm_is_rejected() -> None:
    fixture = _rotated_fixture((2.0, 0.0, 0.0, 1.0))
    _assert_rejected(_prepare(fixture), TRM_NON_UNIFORM_SCALE)
    fixture.doc.close()


def test_oblique_non_uniform_tm_gets_the_shape_code_not_the_rotation_code() -> None:
    """Precedence at prepare level for an OBLIQUE shape defect: the norms
    gate owns it even though the direction is also disqualifying."""
    c30 = math.cos(math.radians(30.0))
    s30 = math.sin(math.radians(30.0))
    fixture = _rotated_fixture((2.0 * c30, 2.0 * s30, -s30, c30))
    _assert_rejected(_prepare(fixture), TRM_NON_UNIFORM_SCALE)
    fixture.doc.close()


def test_singular_tm_is_rejected() -> None:
    fixture = _rotated_fixture((0.0, 0.0, 0.0, 0.0))
    _assert_rejected(_prepare(fixture), TRM_SINGULAR)
    fixture.doc.close()


def test_below_floor_tm_is_rejected_axis_aligned_and_rotated() -> None:
    tiny_axis = _rotated_fixture((0.0000005, 0.0, 0.0, 0.0000005))
    _assert_rejected(_prepare(tiny_axis), TRM_SCALE_BELOW_FLOOR)
    tiny_axis.doc.close()
    tiny_rot = _rotated_fixture((0.0, 0.0000005, -0.0000005, 0.0))
    _assert_rejected(_prepare(tiny_rot), TRM_SCALE_BELOW_FLOOR)
    tiny_rot.doc.close()


def test_rejection_details_never_echo_matrix_coefficients() -> None:
    """§10: trm rejections speak in stable codes, never coefficient values
    (a coefficient uniquely fingerprints a private document's producer)."""
    oblique = _rotated_fixture((0.52, 0.73519, -0.73519, 0.52))
    rejection = _assert_rejected(
        _prepare(oblique), TRM_ROTATION_NOT_QUARTER_TURN
    )
    assert "73519" not in rejection.detail and "0.52" not in rejection.detail
    oblique.doc.close()

    sheared = _rotated_fixture((1.0, 0.0, 0.73519, 1.0))
    rejection = _assert_rejected(_prepare(sheared), TRM_SHEARED)
    assert "73519" not in rejection.detail
    sheared.doc.close()


def test_axis_aligned_admission_is_unchanged_control() -> None:
    """CONTROL (green today, pinned so the P2 rework cannot disturb the
    already-admitted axis-aligned idiom): identity and uniform-scale Tm
    prepare and commit exactly as before."""
    identity = build_identity_h_fixture()
    engine, result = _prepare_with_engine(identity)
    prepared = _assert_prepared(result)
    before = identity.content_bytes()
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED
    _committed_stream_is_a_byte_exact_splice(identity, prepared, before)
    identity.doc.close()

    scaled = build_identity_h_fixture(origin=(100.0, 300.0))
    set_text_matrix(scaled, (2.0, 0.0, 0.0, 2.0))
    _assert_prepared(_prepare(scaled))
    scaled.doc.close()


def test_rotated_tj_array_target_keeps_the_tj_scope_gate() -> None:
    """Admission must not silently widen the show-operator scope: a rotated
    TJ-array target passes the TRM gate and then fails the SAME Tj-only
    gate axis-aligned targets fail."""
    fixture = _rotated_fixture(ROT90)
    stream = fixture.content_bytes()
    rewritten = stream.replace(b" Tm <", b" Tm [<", 1).replace(
        b"> Tj", b">] TJ", 1
    )
    assert rewritten != stream
    fixture.doc.update_stream(fixture.content_xref, rewritten)
    _assert_rejected(_prepare(fixture), RejectReason.NOT_SINGLE_LITERAL_TJ)
    fixture.doc.close()


def test_rotated_rise_keeps_the_residual_text_state_gate() -> None:
    """P2 admits the rotation — nothing else: a rotated show with a text
    rise still fails the residual state gate, with rise named in the
    detail (proving the TRM gate is no longer what refused it)."""
    fixture = _rotated_fixture(ROT90)
    stream = fixture.content_bytes()
    rewritten = stream.replace(b" Tm <", b" Tm 3 Ts <", 1)
    assert rewritten != stream
    fixture.doc.update_stream(fixture.content_xref, rewritten)
    rejection = _assert_rejected(
        _prepare(fixture), RejectReason.UNSUPPORTED_TEXT_STATE
    )
    assert "rise" in rejection.detail, rejection.detail
    fixture.doc.close()


def test_rotated_hscale_keeps_the_residual_text_state_gate() -> None:
    fixture = _rotated_fixture(ROT90)
    stream = fixture.content_bytes()
    rewritten = stream.replace(b" Tm <", b" Tm 50 Tz <", 1)
    assert rewritten != stream
    fixture.doc.update_stream(fixture.content_xref, rewritten)
    rejection = _assert_rejected(
        _prepare(fixture), RejectReason.UNSUPPORTED_TEXT_STATE
    )
    assert "hscale" in rejection.detail, rejection.detail
    fixture.doc.close()


def test_rotated_render_mode_keeps_the_residual_text_state_gate() -> None:
    fixture = _rotated_fixture(ROT90)
    stream = fixture.content_bytes()
    rewritten = stream.replace(b" Tm <", b" Tm 1 Tr <", 1)
    assert rewritten != stream
    fixture.doc.update_stream(fixture.content_xref, rewritten)
    rejection = _assert_rejected(
        _prepare(fixture), RejectReason.UNSUPPORTED_TEXT_STATE
    )
    assert "render_mode" in rejection.detail, rejection.detail
    fixture.doc.close()
