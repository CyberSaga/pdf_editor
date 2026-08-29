"""Production TRM classifier — the single source for rotated-text geometry.

Task 13 Priority 2: classifies the combined ``Tm × CTM`` linear map of a
show operator into a fail-closed admission verdict, and maps text-space
geometry into visual space along the SAME chain the raster verifier's
pixmaps use (``page.transformation_matrix × page.rotation_matrix``, row
vectors, visual y down).

The v1 scope is the census-locked quarter-turn family: positive-orientation
uniform rotation+scale whose visual baseline direction is cardinal.  Every
other shape keeps its own stable :class:`~model.text_commit.dto.RejectReason`
code, attributed by a FIXED gate precedence so telemetry can never drift:

    finite → non-singular determinant → absolute scale floor →
    positive orientation → orthogonal axes → equal axis norms →
    cardinal visual direction

Shared by replay/inspect/plan/verify; the census tooling
(``scripts/trm_taxonomy.py``) delegates to this module — this module must
never import ``scripts/`` (pinned by tests).  Contract pinned verbatim by
``test_scripts/test_text_commit_trm_admission.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from model.text_commit.dto import RejectReason

if TYPE_CHECKING:
    import fitz

Matrix = tuple[float, float, float, float, float, float]
Linear = tuple[float, float, float, float]

# Relative, not absolute: a rotation reconstructed through float math at
# scale 1000 carries proportionally larger component noise than one at
# scale 0.01, and both must classify identically.
REL_TOL = 1e-6
# Absolute, not relative: mirrors replay._uniform_scale's ``a <= _EPS``
# floor — a degenerate baseline scale has no defensible advance geometry
# no matter how "relatively clean" the matrix is.  Closed boundary
# (exactly the floor rejects).
ABS_SCALE_FLOOR = 1e-6

DIRECTION_RIGHT = "right"
DIRECTION_LEFT = "left"
DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_OBLIQUE = "oblique"
DIRECTION_DEGENERATE = "degenerate"

CARDINAL_DIRECTIONS = frozenset(
    {DIRECTION_RIGHT, DIRECTION_LEFT, DIRECTION_UP, DIRECTION_DOWN}
)


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


def _combined_matrix(tm: Matrix, ctm: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = tm
    a2, b2, c2, d2, e2, f2 = ctm
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def shape_reject_reason(
    linear: Linear, *, rel_tol: float = REL_TOL, abs_floor: float = ABS_SCALE_FLOOR
) -> str | None:
    """First failing shape gate's stable code, or ``None`` when the linear
    map is a positive-orientation uniform rotation+scale.

    Angle-blind on purpose: quarter-turn vs arbitrary angle is the visual
    DIRECTION dimension's job (:func:`visual_baseline_direction` /
    :func:`admission_verdict`), because a rotated ``Tm`` compensating a
    page ``/Rotate`` is only classifiable against the page's visual
    matrix, never in user space alone.  ``abs_floor=0.0`` disables the
    floor gate — the census taxonomy delegates that way because its shape
    dimension predates the floor (which it applies in its predicted chain
    instead); production callers keep the default.
    """
    a, b, c, d = linear[0], linear[1], linear[2], linear[3]
    if not all(math.isfinite(v) for v in (a, b, c, d)):
        return RejectReason.TRM_NON_FINITE
    row_x = math.hypot(a, b)
    row_y = math.hypot(c, d)
    scale_sq = max(row_x * row_x, row_y * row_y)
    det = a * d - b * c
    if scale_sq == 0.0 or abs(det) <= rel_tol * scale_sq:
        return RejectReason.TRM_SINGULAR
    if row_x <= abs_floor:
        # The baseline scale (text-space (1, 0)'s image) is what every
        # advance/kern computation divides by — the absolute floor guards
        # it; a degenerate CROSS axis is caught by the norms gate below.
        return RejectReason.TRM_SCALE_BELOW_FLOOR
    if det < 0.0:
        return RejectReason.TRM_REFLECTED
    if abs(a * c + b * d) > rel_tol * scale_sq:
        return RejectReason.TRM_SHEARED
    if abs(row_x - row_y) > rel_tol * max(row_x, row_y):
        return RejectReason.TRM_NON_UNIFORM_SCALE
    return None


def visual_baseline_direction(
    page: fitz.Page, linear: Linear, *, rel_tol: float = REL_TOL
) -> str:
    """Cardinal slug for where the text baseline points ON SCREEN.

    Pushes text-space ``(1, 0)`` through the combined linear map and then
    ``page.transformation_matrix × page.rotation_matrix`` — the exact
    chain the raster verifier's pixmaps use (``transformation_matrix``
    alone omits ``/Rotate``, the known pitfall) — and classifies against
    visual axes (y grows DOWNWARD in visual space).
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


@dataclass(frozen=True)
class TrmVerdict:
    """One show's fail-closed TRM admission verdict.

    ``reject_reason`` is one of the seven ``trm_*`` codes, or ``None``
    when admitted; ``direction`` (a cardinal slug) and ``scale`` (the
    uniform baseline scale factor) are set exactly when admitted.
    """

    reject_reason: str | None
    direction: str | None
    scale: float | None


def admission_verdict(
    page: fitz.Page, tm: Matrix, ctm: Matrix, *, rel_tol: float = REL_TOL
) -> TrmVerdict:
    """Prove (or refuse) one show's combined transform for the v1 scope."""
    linear = combined_linear(tm, ctm)
    reason = shape_reject_reason(linear, rel_tol=rel_tol)
    if reason is not None:
        return TrmVerdict(reject_reason=reason, direction=None, scale=None)
    direction = visual_baseline_direction(page, linear, rel_tol=rel_tol)
    if direction not in CARDINAL_DIRECTIONS:
        return TrmVerdict(
            reject_reason=RejectReason.TRM_ROTATION_NOT_QUARTER_TURN,
            direction=None,
            scale=None,
        )
    return TrmVerdict(
        reject_reason=None,
        direction=direction,
        scale=math.hypot(linear[0], linear[1]),
    )


def map_text_quad_to_visual(
    page: fitz.Page,
    tm: Matrix,
    ctm: Matrix,
    quad: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Visual-space bounds of a TEXT-space rectangle under one show's
    full transform chain.

    ``quad`` is ``(x0, y0, x1, y1)`` in text space (points; x along the
    baseline, y toward the ascender).  Each corner rides
    ``tm × ctm`` (translations included) and then
    ``page.transformation_matrix × page.rotation_matrix``; the result is
    the axis-aligned bounds of the mapped quad — the ONE way every
    fallback target box and growth strip becomes visual geometry, so no
    caller can reintroduce a ``+x`` assumption.
    """
    trm = _combined_matrix(tm, ctm)
    visual = page.transformation_matrix * page.rotation_matrix
    xs: list[float] = []
    ys: list[float] = []
    for tx, ty in (
        (quad[0], quad[1]),
        (quad[2], quad[1]),
        (quad[0], quad[3]),
        (quad[2], quad[3]),
    ):
        ux = trm[0] * tx + trm[2] * ty + trm[4]
        uy = trm[1] * tx + trm[3] * ty + trm[5]
        vx = ux * visual.a + uy * visual.c + visual.e
        vy = ux * visual.b + uy * visual.d + visual.f
        xs.append(vx)
        ys.append(vy)
    return (min(xs), min(ys), max(xs), max(ys))
