"""Rotated-TRM census classifier (Task 13 Priority 2, census-before-code).

Since the P2-B admission slice, this module is a thin DELEGATE of the
production classifier ``model/text_commit/transforms.py`` — one predicate,
never two near-identical ones that drift apart (the delegation and a
probe-grid equivalence are both pinned by
``test_scripts/test_text_commit_trm_admission.py``).  What remains here is
the census-only vocabulary: shape SLUGS (the census taxonomy predates the
production ``trm_*`` codes), the loose near-miss diagnostic tolerance, and
the closed ``/Rotate`` bucket fold.

Aggregate-only (plan §10): callers emit these slugs and counts, never
matrix components or any document-derived value.

Gate precedence is fixed and pinned by tests — finite → non-singular →
positive orientation → orthogonal axes → equal axis norms — so a matrix
with several defects always buckets on the FIRST failing gate and the
attribution cannot drift.  (The census shape dimension carries NO absolute
scale floor — that gate lives in the census's predicted chain, and in
production's ``shape_reject_reason`` default.)
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from model.text_commit import transforms
from model.text_commit.dto import RejectReason

if TYPE_CHECKING:
    import fitz

Matrix = tuple[float, float, float, float, float, float]
Linear = tuple[float, float, float, float]

SHAPE_NON_FINITE = "non_finite"
SHAPE_SINGULAR = "singular"
SHAPE_REFLECTED = "reflected"
SHAPE_SHEARED = "sheared"
SHAPE_NON_UNIFORM_SCALE = "non_uniform_scale"
SHAPE_AXIS_ALIGNED = "axis_aligned_uniform_positive"
SHAPE_UNIFORM_ROTATED = "uniform_rotated_positive"

DIRECTION_RIGHT = transforms.DIRECTION_RIGHT
DIRECTION_LEFT = transforms.DIRECTION_LEFT
DIRECTION_UP = transforms.DIRECTION_UP
DIRECTION_DOWN = transforms.DIRECTION_DOWN
DIRECTION_OBLIQUE = transforms.DIRECTION_OBLIQUE
DIRECTION_DEGENERATE = transforms.DIRECTION_DEGENERATE

CARDINAL_DIRECTIONS = transforms.CARDINAL_DIRECTIONS

# Relative, not absolute — see transforms.REL_TOL (the same constant).
_REL_TOL = transforms.REL_TOL
# Diagnostic-only loose tolerance (review finding F1): a quarter turn a
# CAD export wrote with ROUNDED decimals (e.g. "0.0001 1 -1 0") fails
# the strict gates as sheared/oblique; classifying a second time at 1e-3
# makes that near-miss mass visible on the corpus BEFORE the admission
# tolerance argument is settled.  Never used for any predicted count.
LOOSE_REL_TOL = 1e-3
# The census predicted chain applies production's absolute floor in front
# of its bindable projection (review finding F2) — same constant.
ABS_SCALE_FLOOR = transforms.ABS_SCALE_FLOOR

_CODE_TO_SLUG = {
    RejectReason.TRM_NON_FINITE: SHAPE_NON_FINITE,
    RejectReason.TRM_SINGULAR: SHAPE_SINGULAR,
    RejectReason.TRM_REFLECTED: SHAPE_REFLECTED,
    RejectReason.TRM_SHEARED: SHAPE_SHEARED,
    RejectReason.TRM_NON_UNIFORM_SCALE: SHAPE_NON_UNIFORM_SCALE,
}


def combined_linear(tm: Matrix, ctm: Matrix) -> Linear:
    """Linear part of ``tm × ctm`` (delegates to production)."""
    return transforms.combined_linear(tm, ctm)


def baseline_scale(linear: Linear) -> float:
    """Norm of text-space ``(1, 0)``'s image — the baseline scale."""
    return math.hypot(linear[0], linear[1])


def page_rotate_slug(rotation: int) -> str:
    """Closed-vocabulary ``/Rotate`` bucket: 0/90/180/270 or ``other``.

    Folding instead of ``str(rotation)`` keeps a malformed document's
    verbatim ``/Rotate`` value out of the aggregate output.
    """
    if rotation % 90 == 0:
        return str(rotation % 360)
    return "other"


def classify_user_matrix(linear: Linear, *, rel_tol: float = _REL_TOL) -> str:
    """Stable shape slug for one combined user-space linear map.

    Delegates the gate chain to production's
    :func:`~model.text_commit.transforms.shape_reject_reason` (with the
    floor disabled — census vocabulary predates it) and keeps only the
    census-side axis-aligned vs rotated split of the admitted family.
    """
    code = transforms.shape_reject_reason(
        linear, rel_tol=rel_tol, abs_floor=0.0
    )
    if code is not None:
        return _CODE_TO_SLUG[code]
    a, b, c = linear[0], linear[1], linear[2]
    row_x = math.hypot(a, b)
    if abs(b) <= rel_tol * row_x and abs(c) <= rel_tol * row_x:
        # det > 0 with b ≈ c ≈ 0 forces a > 0, d > 0: the already-admitted
        # axis-aligned idiom (a 180° turn has b = c = 0 but a, d < 0 — it
        # lands in the rotated bucket below, as it must).
        if a > 0.0:
            return SHAPE_AXIS_ALIGNED
    return SHAPE_UNIFORM_ROTATED


def visual_baseline_direction(
    page: fitz.Page, linear: Linear, *, rel_tol: float = _REL_TOL
) -> str:
    """Cardinal slug for where the text baseline points ON SCREEN
    (delegates to production — the same
    ``transformation_matrix × rotation_matrix`` chain)."""
    return transforms.visual_baseline_direction(page, linear, rel_tol=rel_tol)
