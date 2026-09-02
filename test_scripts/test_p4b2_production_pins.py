"""P4-B2 commit 1: production pins for the duplicate-painter gate's ceiling.

Characterization tests (CLAUDE.md §5.1 exemption: they pin KNOWN defects
that the frozen P4-B1 branch does not fix) plus strict-xfail twins that
encode the rejection the P4-B2 spike gate must produce.

Every case is a genuine false admit, proven two ways at once:

1. ``prepare_plan`` returns a ``PreparedEdit`` (production ADMITS);
2. the two painters' single-painter rasters overlap (the twin paints on
   top of the target, so a commit leaves a ghost).

The cases are the P4-B1 final review's F1≡F3 ``/W`` continuum
(``plans/2026-09-01-p4b1-final-review-verdict.md``: ``/W 0`` and ``/W 1``
same-bytes twins admit at every offset because the exact-extent quad treats
a declared advance as an ink bound) and the rev-2 plan's R5 core-band
counterexample (``_painter_reach`` keeps a 0.6-em band on both sides, so
``second_dy = ±7.3`` at 12 pt is disjoint in bands and overlapping in ink).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_plan,
)
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    painters_overlap_pixels,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    FONTSIZE,
    REPLACEMENT,
    SOURCE,
    _build_second_show_doc,
)

# ``/W`` continuum: a declared advance of 0 (F1) and of 1/1000 em (the
# verifier's sweep) on a cloned font dictionary, with the clone's
# CIDToGIDMap either identical (same_font is True, F3 route) or distinct
# (same_font is None, F1 route), at the four offsets the review swept.
W_CASES = [
    pytest.param(width, distinct, offset, id=f"W{width}-{'distinct' if distinct else 'same'}-{offset:+.1f}")
    for width in (0, 1)
    for distinct in (False, True)
    for offset in (-2.0, -1.0, 1.0, 2.0)
]

# Core band: 0.6 em = 7.2 pt at 12 pt; ±7.3 leaves the bands 0.1 pt apart.
CORE_BAND_CASES = [
    pytest.param(dy, id=f"dy{dy:+.1f}") for dy in (-7.3, 7.3)
]


def _w_kwargs(width: int, distinct: bool, offset: float) -> dict:
    return {
        "offset": offset,
        "second_resource": "F_CLONE",
        "second_clone_font": True,
        "second_clone_width": width,
        "second_clone_distinct_cidtogid": distinct,
    }


def _core_band_kwargs(dy: float) -> dict:
    return {"offset": 1.0, "second_dy": dy}


def _prepare_and_overlap(**kwargs) -> tuple[PreparedEdit | PlanRejection, int]:
    """Production verdict and single-painter raster overlap for one page."""
    fixture, expected_origin = _build_second_show_doc(**kwargs)
    try:
        overlap = painters_overlap_pixels(fixture)
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
        fixture.doc.close()
    return result, overlap


# --------------------------------------------------------------------------
# Characterization: production ADMITS while the rasters overlap.


@pytest.mark.parametrize(("width", "distinct", "offset"), W_CASES)
def test_w_continuum_twin_is_a_false_admit_at_the_frozen_tip(
    width: int, distinct: bool, offset: float
) -> None:
    """F1≡F3: declared advance is not an ink bound (verdict doc, 'F1 and
    F3 are one defect').  ``/W 0`` gives a zero-width exact quad; ``/W 1``
    a 0.024 pt one; both read as disjoint under ``overlap_x > 0.05``."""
    result, overlap = _prepare_and_overlap(**_w_kwargs(width, distinct, offset))
    assert overlap > 0, "the twin must paint on the target for this to be a pin"
    assert isinstance(result, PreparedEdit), result


@pytest.mark.parametrize("dy", CORE_BAND_CASES)
def test_core_band_twin_is_a_false_admit_at_the_frozen_tip(dy: float) -> None:
    """R5: the reach fallback and the exact quad both keep a 0.6-em core
    band in y (``_painter_core_quad``), so a twin one band-height away is
    'disjoint' while its ascenders/descenders overlap the target's ink."""
    result, overlap = _prepare_and_overlap(**_core_band_kwargs(dy))
    assert overlap > 0, "the twin must paint on the target for this to be a pin"
    assert isinstance(result, PreparedEdit), result


# --------------------------------------------------------------------------
# Strict-xfail twins: the rejection P4-B2's gate must produce.  They turn
# green only when production stops admitting these shapes; a silent pass
# would mean the pin above is stale, so ``strict=True``.


@pytest.mark.xfail(
    strict=True,
    reason="P4-B1 frozen at 49c98ee: declared advance still bounds ink (F1/F3)",
)
@pytest.mark.parametrize(("width", "distinct", "offset"), W_CASES)
def test_w_continuum_twin_must_be_rejected(
    width: int, distinct: bool, offset: float
) -> None:
    result, overlap = _prepare_and_overlap(**_w_kwargs(width, distinct, offset))
    assert overlap > 0
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


@pytest.mark.xfail(
    strict=True,
    reason="P4-B1 frozen at 49c98ee: 0.6-em core band is not an ink bound (R5)",
)
@pytest.mark.parametrize("dy", CORE_BAND_CASES)
def test_core_band_twin_must_be_rejected(dy: float) -> None:
    result, overlap = _prepare_and_overlap(**_core_band_kwargs(dy))
    assert overlap > 0
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


# --------------------------------------------------------------------------
# Positive control: the raster oracle itself distinguishes a genuinely
# disjoint twin from an overlapping one, so ``overlap > 0`` above is not a
# rendering artefact.


def test_raster_oracle_control_disjoint_twin_has_no_overlap() -> None:
    fixture, _ = _build_second_show_doc(offset=len(SOURCE) * FONTSIZE + 4.0)
    try:
        assert painters_overlap_pixels(fixture) == 0
    finally:
        fixture.doc.close()


def test_raster_oracle_control_coincident_twin_overlaps_fully() -> None:
    fixture, _ = _build_second_show_doc(offset=0.0)
    try:
        from test_scripts.painter_matrix_fixtures import single_painter_masks

        first, second = single_painter_masks(fixture)
        assert first.ink_pixels > 0
        assert first.overlap_pixels(second) == first.ink_pixels
    finally:
        fixture.doc.close()
