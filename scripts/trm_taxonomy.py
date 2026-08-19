"""Rotated-TRM census classifier (Task 13 Priority 2, census-before-code).

Classifies the LINEAR part of a show's combined user-space matrix
(``Tm × CTM``) into stable shape slugs, and the visual baseline
direction after the page's ``transformation_matrix × rotation_matrix``
(the same visual chain production ``inspect``/``plan`` already use)
into cardinal slugs.  This module deliberately lives OUTSIDE ``model/``
until the Priority-2 admission slice promotes the winning taxonomy —
the same census-before-code discipline the Task 13 P1 wrapper taxonomy
followed.

Aggregate-only (plan §10): callers emit these slugs and counts, never
matrix components or any document-derived value.

Gate precedence is fixed and pinned by tests — finite → non-singular →
positive orientation → orthogonal axes → equal axis norms — so a matrix
with several defects always buckets on the FIRST failing gate and the
attribution cannot drift.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

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

DIRECTION_RIGHT = "right"
DIRECTION_LEFT = "left"
DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_OBLIQUE = "oblique"
DIRECTION_DEGENERATE = "degenerate"

CARDINAL_DIRECTIONS = frozenset(
    {DIRECTION_RIGHT, DIRECTION_LEFT, DIRECTION_UP, DIRECTION_DOWN}
)

# Relative, not absolute: a rotation reconstructed through float math at
# scale 1000 carries proportionally larger component noise than one at
# scale 0.01, and both must classify identically.
_REL_TOL = 1e-6
# Diagnostic-only loose tolerance (review finding F1): a quarter turn a
# CAD export wrote with ROUNDED decimals (e.g. "0.0001 1 -1 0") fails
# the strict gates as sheared/oblique; classifying a second time at 1e-3
# makes that near-miss mass visible on the corpus BEFORE the P2-B
# admission tolerance is pinned.  Never used for any predicted count.
LOOSE_REL_TOL = 1e-3
# Production's _uniform_scale rejects a <= _EPS with an ABSOLUTE floor
# (replay.py) — the census predicted chain must not admit a degenerate
# scale the relative shape gates cannot see (review finding F2).
ABS_SCALE_FLOOR = 1e-6


def combined_linear(tm: Matrix, ctm: Matrix) -> Linear:
    """Linear part of ``tm × ctm`` (row-vector convention, as replay's)."""
    a1, b1, c1, d1, _, _ = tm
    a2, b2, c2, d2, _, _ = ctm
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
    )


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

    Angle-blind on purpose: quarter-turn vs arbitrary angle is the
    DIRECTION dimension's job (``visual_baseline_direction``), because
    a rotated ``Tm`` compensating a page ``/Rotate`` is only classifiable
    against the page's visual matrix, not in user space alone.
    """
    a, b, c, d = linear[0], linear[1], linear[2], linear[3]
    if not all(math.isfinite(v) for v in (a, b, c, d)):
        return SHAPE_NON_FINITE
    row_x = math.hypot(a, b)
    row_y = math.hypot(c, d)
    scale_sq = max(row_x * row_x, row_y * row_y)
    det = a * d - b * c
    if scale_sq == 0.0 or abs(det) <= rel_tol * scale_sq:
        return SHAPE_SINGULAR
    if det < 0.0:
        return SHAPE_REFLECTED
    if abs(a * c + b * d) > rel_tol * scale_sq:
        return SHAPE_SHEARED
    if abs(row_x - row_y) > rel_tol * max(row_x, row_y):
        return SHAPE_NON_UNIFORM_SCALE
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
    """Cardinal slug for where the text baseline points ON SCREEN.

    Pushes text-space ``(1, 0)`` through the combined linear map and then
    the page's ``transformation_matrix × rotation_matrix`` — the same
    visual chain ``inspect._origin_in_page_space`` and ``plan`` use — and
    classifies against visual axes (y grows DOWNWARD in visual space).
    """
    ux, uy = linear[0], linear[1]
    if not (math.isfinite(ux) and math.isfinite(uy)):
        return DIRECTION_DEGENERATE
    visual = page.transformation_matrix * page.rotation_matrix
    vx = ux * visual.a + uy * visual.c
    vy = ux * visual.b + uy * visual.d
    norm = math.hypot(vx, vy)
    if norm == 0.0 or not math.isfinite(norm):
        return DIRECTION_DEGENERATE
    if abs(vy) <= rel_tol * norm:
        return DIRECTION_RIGHT if vx > 0.0 else DIRECTION_LEFT
    if abs(vx) <= rel_tol * norm:
        return DIRECTION_DOWN if vy > 0.0 else DIRECTION_UP
    return DIRECTION_OBLIQUE
