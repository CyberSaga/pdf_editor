"""Task 13 Priority 2 step P2-A — rotated-TRM census (census-before-code).

Red matrix for the AGGREGATE-ONLY matrix census that must run BEFORE any
admission change: classify the combined user-space text/transform matrix
(``Tm × CTM``) of every show currently dying at the funnel's TRM gate,
and the visual baseline direction after the page's
``transformation_matrix × rotation_matrix``.  No admission logic changes
here: the ``state:trm_not_uniform_scaled`` loss slug and every funnel
stage stay exactly as sealed after Task 13 P1.

Data policy (plan §10): census output is stable bucket slugs and counts
only — never raw matrix components, text, names, or paths.
"""
from __future__ import annotations

import math

import fitz
import pytest

from scripts.measure_type0_funnel import funnel_document
from scripts.trm_taxonomy import (
    ABS_SCALE_FLOOR,
    CARDINAL_DIRECTIONS,
    DIRECTION_DEGENERATE,
    DIRECTION_DOWN,
    DIRECTION_LEFT,
    DIRECTION_OBLIQUE,
    DIRECTION_RIGHT,
    DIRECTION_UP,
    LOOSE_REL_TOL,
    SHAPE_AXIS_ALIGNED,
    SHAPE_NON_FINITE,
    SHAPE_NON_UNIFORM_SCALE,
    SHAPE_REFLECTED,
    SHAPE_SHEARED,
    SHAPE_SINGULAR,
    SHAPE_UNIFORM_ROTATED,
    baseline_scale,
    classify_user_matrix,
    combined_linear,
    page_rotate_slug,
    visual_baseline_direction,
)
from test_scripts.type0_fixture_builder import (
    build_identity_h_fixture,
    set_text_matrix,
)


def _rot(degrees: float, scale: float = 1.0) -> tuple[float, float, float, float]:
    rad = math.radians(degrees)
    c, s = math.cos(rad) * scale, math.sin(rad) * scale
    return (c, s, -s, c)


# --------------------------------------------------------------- Part A
# User-matrix shape taxonomy: literal slugs on purpose, so a production
# rename cannot silently keep this matrix green.


def test_shape_slugs_are_stable_literals() -> None:
    assert SHAPE_NON_FINITE == "non_finite"
    assert SHAPE_SINGULAR == "singular"
    assert SHAPE_REFLECTED == "reflected"
    assert SHAPE_SHEARED == "sheared"
    assert SHAPE_NON_UNIFORM_SCALE == "non_uniform_scale"
    assert SHAPE_AXIS_ALIGNED == "axis_aligned_uniform_positive"
    assert SHAPE_UNIFORM_ROTATED == "uniform_rotated_positive"
    assert DIRECTION_RIGHT == "right"
    assert DIRECTION_LEFT == "left"
    assert DIRECTION_UP == "up"
    assert DIRECTION_DOWN == "down"
    assert DIRECTION_OBLIQUE == "oblique"
    assert DIRECTION_DEGENERATE == "degenerate"
    assert CARDINAL_DIRECTIONS == frozenset({"right", "left", "up", "down"})


@pytest.mark.parametrize("scale", [0.01, 1.0, 12.0, 1000.0])
def test_axis_aligned_uniform_positive(scale: float) -> None:
    assert classify_user_matrix((scale, 0.0, 0.0, scale)) == SHAPE_AXIS_ALIGNED


@pytest.mark.parametrize("degrees", [90.0, -90.0, 180.0, 270.0, 30.0, 45.0])
@pytest.mark.parametrize("scale", [0.01, 1.0, 1000.0])
def test_uniform_rotation_any_angle_is_uniform_rotated(
    degrees: float, scale: float
) -> None:
    # Shape taxonomy is angle-blind: quarter-turn vs arbitrary angle is
    # the DIRECTION dimension's job, not the shape's.
    assert classify_user_matrix(_rot(degrees, scale)) == SHAPE_UNIFORM_ROTATED


def test_shear_is_sheared() -> None:
    assert classify_user_matrix((1.0, 0.0, 0.5, 1.0)) == SHAPE_SHEARED


def test_unequal_axis_norms_is_non_uniform_scale() -> None:
    assert classify_user_matrix((2.0, 0.0, 0.0, 1.0)) == SHAPE_NON_UNIFORM_SCALE


def test_mirror_is_reflected() -> None:
    assert classify_user_matrix((-1.0, 0.0, 0.0, 1.0)) == SHAPE_REFLECTED


def test_zero_matrix_is_singular() -> None:
    assert classify_user_matrix((0.0, 0.0, 0.0, 0.0)) == SHAPE_SINGULAR


def test_rank_one_matrix_is_singular() -> None:
    assert classify_user_matrix((1.0, 2.0, 2.0, 4.0)) == SHAPE_SINGULAR


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_component_is_non_finite(bad: float) -> None:
    assert classify_user_matrix((bad, 0.0, 0.0, 1.0)) == SHAPE_NON_FINITE


def test_precedence_non_finite_beats_everything() -> None:
    assert classify_user_matrix((math.nan, math.nan, math.nan, math.nan)) == (
        SHAPE_NON_FINITE
    )


def test_precedence_reflection_beats_shear_and_scale() -> None:
    # Negative determinant AND sheared AND unequal norms: the gate order
    # finite → non-singular → orientation → orthogonality → equal norms
    # must attribute this to reflection.
    assert classify_user_matrix((-2.0, 0.0, 0.5, 1.0)) == SHAPE_REFLECTED


@pytest.mark.parametrize("scale", [0.01, 1.0, 1000.0])
def test_relative_tolerance_admits_float_noise(scale: float) -> None:
    # A rotation reconstructed through float math at any magnitude must
    # not fall out of the uniform bucket: the tolerance is RELATIVE.
    noisy = tuple(v * (1.0 + 1e-12) for v in _rot(37.0, scale))
    assert classify_user_matrix(noisy) == SHAPE_UNIFORM_ROTATED


@pytest.mark.parametrize("scale", [0.01, 1.0, 1000.0])
def test_relative_tolerance_rejects_real_shear(scale: float) -> None:
    a, b, c, d = _rot(37.0, scale)
    sheared = (a, b, c + 0.05 * scale, d)
    assert classify_user_matrix(sheared) == SHAPE_SHEARED


# Review-round pins (F1/F2/F3 confirmed by the adversarial pass): the
# predicted chain's FRONT gate must be measurable under BOTH candidate
# scopes, must expose near-miss mass, and must not admit degenerate
# scales production's absolute floor rejects.


def test_loose_tolerance_recovers_rounded_quarter_turn() -> None:
    # A CAD export writing rounded decimals: strict 1e-6 buckets it
    # sheared/oblique, the loose diagnostic tolerance must recover it.
    rounded = (0.0001, 1.0, -1.0, 0.0)
    assert classify_user_matrix(rounded) == SHAPE_SHEARED
    assert classify_user_matrix(rounded, rel_tol=LOOSE_REL_TOL) == (
        SHAPE_UNIFORM_ROTATED
    )


def test_baseline_scale_is_the_baseline_row_norm() -> None:
    assert baseline_scale((3.0, 4.0, -4.0, 3.0)) == 5.0
    assert baseline_scale((0.0, 0.0, 0.0, 1.0)) == 0.0
    assert ABS_SCALE_FLOOR == 1e-6  # mirrors replay._EPS's absolute floor


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [(0, "0"), (90, "90"), (180, "180"), (270, "270"), (360, "0"),
     (-90, "270"), (450, "90"), (33, "other"), (91, "other")],
)
def test_page_rotate_slug_closed_vocabulary(rotation: int, expected: str) -> None:
    assert page_rotate_slug(rotation) == expected


def test_combined_linear_multiplies_tm_by_ctm() -> None:
    tm = (0.0, 2.0, -2.0, 0.0, 5.0, 7.0)
    ctm = (3.0, 0.0, 0.0, 3.0, 11.0, 13.0)
    assert combined_linear(tm, ctm) == (0.0, 6.0, -6.0, 0.0)


# --------------------------------------------------------------- Part B
# Visual baseline direction: Tm×CTM linear part pushed through the
# page's transformation_matrix × rotation_matrix (the SAME chain
# production inspect/plan use), classified into cardinal slugs.


def _page_with_rotation(rotation: int) -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    if rotation:
        page.set_rotation(rotation)
    return page


@pytest.mark.parametrize(
    ("page_rotation", "expected"),
    [(0, DIRECTION_RIGHT), (90, DIRECTION_DOWN), (180, DIRECTION_LEFT), (270, DIRECTION_UP)],
)
def test_axis_aligned_baseline_follows_page_rotation(
    page_rotation: int, expected: str
) -> None:
    page = _page_with_rotation(page_rotation)
    assert visual_baseline_direction(page, (1.0, 0.0, 0.0, 1.0)) == expected


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [(90.0, DIRECTION_UP), (-90.0, DIRECTION_DOWN), (180.0, DIRECTION_LEFT)],
)
def test_rotated_tm_on_unrotated_page(degrees: float, expected: str) -> None:
    page = _page_with_rotation(0)
    assert visual_baseline_direction(page, _rot(degrees)) == expected


def test_cad_idiom_on_rotate270_page() -> None:
    # THE corpus shape: a rotated Tm compensating /Rotate 270.  The page
    # is displayed turned 90° counter-clockwise, so a −90° Tm (baseline
    # down on the paper) reads visually left-to-right — and a +90° Tm
    # reads LEFT, not right (the direction pin that keeps the census
    # honest about which quarter-turn actually compensates).
    page = _page_with_rotation(270)
    assert visual_baseline_direction(page, (0.0, -1.0, 1.0, 0.0)) == (
        DIRECTION_RIGHT
    )
    assert visual_baseline_direction(page, (0.0, 1.0, -1.0, 0.0)) == (
        DIRECTION_LEFT
    )


def test_oblique_angle_is_oblique() -> None:
    page = _page_with_rotation(0)
    assert visual_baseline_direction(page, _rot(30.0)) == DIRECTION_OBLIQUE


def test_zero_baseline_is_degenerate() -> None:
    page = _page_with_rotation(0)
    assert visual_baseline_direction(page, (0.0, 0.0, 0.0, 1.0)) == (
        DIRECTION_DEGENERATE
    )


def test_non_finite_baseline_is_degenerate() -> None:
    page = _page_with_rotation(0)
    assert visual_baseline_direction(page, (math.nan, 0.0, 0.0, 1.0)) == (
        DIRECTION_DEGENERATE
    )


# --------------------------------------------------------------- Part C
# Funnel integration: the census block hangs off the EXISTING TRM gate;
# stages and loss slugs stay byte-identical to the Task 13 P1 record.

_SHAPE_SLUGS = frozenset(
    {
        "non_finite",
        "singular",
        "reflected",
        "sheared",
        "non_uniform_scale",
        "axis_aligned_uniform_positive",
        "uniform_rotated_positive",
    }
)
_DIRECTION_SLUGS = frozenset(
    {"right", "left", "up", "down", "oblique", "degenerate"}
)
_PREDICTED_SLUGS = frozenset(
    {
        "any_uniform_rotation",
        "quarter_turn_uniform",
        "and_default_state",
        "and_scope_accepted",
        "and_source_decoded",
        "and_bytes_reproduced",
        "predicted_source_bindable",
        "predicted_source_bindable_quarter_turn",
        "predicted_source_bindable_chars",
        "predicted_replacement_encodable",
        "predicted_replacement_encodable_quarter_turn",
    }
)
_NEAR_MISS_SLUGS = frozenset(
    {
        "shape_uniform_only_at_1e3",
        "direction_cardinal_only_at_1e3",
        "quarter_turn_only_at_1e3",
    }
)


def test_funnel_reports_trm_census_for_rotated_show() -> None:
    fixture = build_identity_h_fixture()
    # Exact +90° quarter turn (float _rot() would serialize exponent
    # noise a PDF lexer cannot read).
    set_text_matrix(fixture, (0.0, 1.0, -1.0, 0.0))
    report = funnel_document(fixture.doc, run_e2e=False)

    # Task 13 P2: the quarter-turn show is ADMITTED at the (now
    # production-mirroring) TRM gate and flows downstream; the blanket
    # "state:trm_not_uniform_scaled" slug is retired with the blanket
    # gate.  The census fold still records the same population.
    assert report["funnel_shows"]["outside_marked_content"] == 1
    assert report["funnel_shows"]["trm_rotated_admitted"] == 1
    assert report["funnel_shows"]["uniform_trm"] == 1
    assert "state:trm_not_uniform_scaled" not in report["loss_reasons"]
    acceptance = report["trm_census"]["acceptance"]
    assert acceptance["predicted_gate"] == 1
    assert acceptance["production_gate"] == 1
    assert acceptance["gate_symmetric_difference"] == 0
    assert acceptance["gate_membership_exact"] is True
    assert acceptance["predicted_downstream"] == 1
    assert acceptance["production_downstream"] == 1
    assert acceptance["downstream_symmetric_difference"] == 0
    assert acceptance["downstream_membership_exact"] is True

    census = report["trm_census"]
    assert census["user_shape"] == {"uniform_rotated_positive": 1}
    assert census["visual_direction"] == {"up": 1}
    assert census["page_rotate"] == {"0": 1}
    assert census["overlap"] == {"never_wrapped": 1}
    predicted = census["predicted"]
    # The fixture clears every downstream gate — the census must predict
    # it as newly bindable AND replacement-encodable under BOTH candidate
    # scopes (any uniform rotation per plan §3, quarter-turn subset per
    # the P2 v1 candidate lock).
    assert predicted["any_uniform_rotation"] == 1
    assert predicted["quarter_turn_uniform"] == 1
    assert predicted["and_default_state"] == 1
    assert predicted["and_scope_accepted"] == 1
    assert predicted["and_source_decoded"] == 1
    assert predicted["and_bytes_reproduced"] == 1
    assert predicted["predicted_source_bindable"] == 1
    assert predicted["predicted_source_bindable_quarter_turn"] == 1
    assert predicted["predicted_source_bindable_chars"] == len(fixture.text)
    assert predicted["predicted_replacement_encodable"] == 1
    assert predicted["predicted_replacement_encodable_quarter_turn"] == 1
    assert census["near_miss"] == {}


def test_funnel_trm_census_rotated_page_compensating_tm() -> None:
    fixture = build_identity_h_fixture(rotate=270)
    set_text_matrix(fixture, (0.0, -1.0, 1.0, 0.0))
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert census["user_shape"] == {"uniform_rotated_positive": 1}
    assert census["visual_direction"] == {"right": 1}
    assert census["page_rotate"] == {"270": 1}


def test_funnel_trm_census_sheared_show_never_predicted() -> None:
    fixture = build_identity_h_fixture()
    set_text_matrix(fixture, (12.0, 0.0, 6.0, 12.0))
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert census["user_shape"] == {"sheared": 1}
    assert census["predicted"] == {}
    # A REAL shear (6/12 off-orthogonal) is not tolerance noise: the
    # near-miss diagnostic must stay silent.
    assert census["near_miss"] == {}


def test_funnel_trm_census_oblique_uniform_measures_both_scopes() -> None:
    # 45° uniform rotation: inside plan §3's any-uniform-rotation scope,
    # outside the quarter-turn candidate lock — the predicted chain must
    # count it under the broad scope only (review finding F3).
    fixture = build_identity_h_fixture()
    set_text_matrix(fixture, _rot(45.0, 12.0))
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert census["user_shape"] == {"uniform_rotated_positive": 1}
    assert census["visual_direction"] == {"oblique": 1}
    predicted = census["predicted"]
    assert predicted["any_uniform_rotation"] == 1
    assert "quarter_turn_uniform" not in predicted
    assert predicted["predicted_source_bindable"] == 1
    assert "predicted_source_bindable_quarter_turn" not in predicted
    assert predicted["predicted_replacement_encodable"] == 1
    # A true 45° is not a rounded quarter turn: no near-miss noise.
    assert census["near_miss"] == {}


def test_funnel_trm_census_rounded_quarter_turn_hits_near_miss() -> None:
    # Review finding F1: a quarter turn written with rounded decimals
    # must not silently vanish into sheared/oblique — the near-miss
    # diagnostic is what makes the undercount visible on the corpus.
    fixture = build_identity_h_fixture()
    set_text_matrix(fixture, (0.0001, 1.0, -1.0, 0.0))
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert census["user_shape"] == {"sheared": 1}
    assert census["visual_direction"] == {"oblique": 1}
    assert census["predicted"] == {}
    assert census["near_miss"] == {
        "shape_uniform_only_at_1e3": 1,
        "direction_cardinal_only_at_1e3": 1,
        "quarter_turn_only_at_1e3": 1,
    }


def test_funnel_trm_census_degenerate_scale_never_predicted() -> None:
    # Review finding F2: production's _uniform_scale has an ABSOLUTE
    # floor (a <= _EPS); a tiny exact quarter turn sneaks past the
    # relative shape gates and must be stopped by the same floor before
    # entering the predicted chain.
    fixture = build_identity_h_fixture()
    set_text_matrix(fixture, (0.0, 0.0000005, -0.0000005, 0.0))
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert census["user_shape"] == {"uniform_rotated_positive": 1}
    assert census["predicted"] == {}


def test_funnel_trm_census_empty_for_axis_aligned_document() -> None:
    fixture = build_identity_h_fixture()
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert census["user_shape"] == {}
    assert census["visual_direction"] == {}
    assert census["page_rotate"] == {}
    assert census["overlap"] == {}
    assert census["predicted"] == {}
    assert census["near_miss"] == {}
    # And the P1-sealed funnel result is untouched.
    assert report["funnel_shows"]["source_bindable"] == 1


def test_trm_census_output_is_slug_keyed_counts_only() -> None:
    # Plan §10: aggregate-only — every leaf is an int, every key a slug
    # from the fixed vocabulary; no matrix component can leak out.
    fixture = build_identity_h_fixture()
    set_text_matrix(fixture, _rot(45.0, 12.0))
    report = funnel_document(fixture.doc, run_e2e=False)
    census = report["trm_census"]
    assert set(census["user_shape"]) <= _SHAPE_SLUGS
    assert set(census["visual_direction"]) <= _DIRECTION_SLUGS
    assert set(census["predicted"]) <= _PREDICTED_SLUGS
    assert set(census["near_miss"]) <= _NEAR_MISS_SLUGS
    assert set(census["overlap"]) <= {"never_wrapped", "wrapped_p1_admitted"}
    # page_rotate is a CLOSED vocabulary: any /Rotate not a multiple of
    # 90 folds to "other" instead of surfacing verbatim.
    assert set(census["page_rotate"]) <= {"0", "90", "180", "270", "other"}
    for section in census.values():
        for key, value in section.items():
            assert isinstance(key, str)
            assert isinstance(value, int)
