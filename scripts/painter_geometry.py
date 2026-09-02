"""Pure geometry for the P4-B2 exact-painter-geometry spike (read-only).

Everything here is document-free arithmetic plus the fontTools per-glyph
outline oracle (O2 in ``plans/task15-p4b2-exact-painter-geometry-spike.md``
§4.2).  No PyMuPDF, no admission logic, no I/O beyond parsing a font
program that is already in memory.

Privacy: every failure surfaces as a :class:`GeometryUnavailable` carrying
one slug from :data:`GEOMETRY_SLUGS` and nothing else.  fontTools messages
name glyphs (``uni518D``), so they are dropped at the chokepoint.

Declared advance is never an ink bound here: the only quantities that
leave this module are outline bounds and the transforms that place them.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

try:  # fontTools is a dev/spike dependency, never a production one.
    from fontTools.pens.boundsPen import BoundsPen, ControlBoundsPen
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover - exercised only where fontTools is absent
    BoundsPen = ControlBoundsPen = TTFont = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

Rect = tuple[float, float, float, float]
Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

PROOF_QUALITIES = ("exact", "conservative", "ambiguous", "unavailable")

GEOMETRY_SLUGS = (
    "fonttools_absent",
    "program_unparseable",
    "glyf_missing",
    "upem_invalid",
    "gid_out_of_range",
    "glyph_unparseable",
    "cyclic_composite",
)

# Production's overlap epsilon (``model/text_commit/plan.py``): a strict
# overlap deeper than this on BOTH axes is an overlap.
OVERLAP_EPSILON = 0.05
SAME_BASELINE_EPSILON = 0.05


class GeometryUnavailable(Exception):
    """A geometry question the document cannot answer; ``slug`` is closed."""

    def __init__(self, slug: str) -> None:
        if slug not in GEOMETRY_SLUGS:
            raise ValueError("unknown geometry slug")
        super().__init__(slug)
        self.slug = slug

    def __str__(self) -> str:
        return self.slug


# ------------------------------------------------------------- rectangles


def rect_is_empty(rect: Rect) -> bool:
    return rect[2] <= rect[0] or rect[3] <= rect[1]


def rect_union(rects: list[Rect] | tuple[Rect, ...]) -> Rect:
    live = [rect for rect in rects if not rect_is_empty(rect)]
    if not live:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(rect[0] for rect in live),
        min(rect[1] for rect in live),
        max(rect[2] for rect in live),
        max(rect[3] for rect in live),
    )


def rect_pad(rect: Rect, pad: float) -> Rect:
    return (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)


def rect_within(inner: Rect, outer: Rect, tolerance: float) -> bool:
    """``inner`` lies inside ``outer`` grown by ``tolerance`` on every side."""
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def strict_overlap_depths(first: Rect, second: Rect) -> tuple[float, float]:
    """Same semantics as ``plan._strict_overlap_depths``: positive depths on
    both axes mean a real overlap; zero or negative means touching/apart."""
    return (
        min(first[2], second[2]) - max(first[0], second[0]),
        min(first[3], second[3]) - max(first[1], second[1]),
    )


def rects_overlap(first: Rect, second: Rect, epsilon: float = OVERLAP_EPSILON) -> bool:
    depth_x, depth_y = strict_overlap_depths(first, second)
    return depth_x > epsilon and depth_y > epsilon


# --------------------------------------------------------------- matrices


def matrix_concat(first: Matrix, second: Matrix) -> Matrix:
    """``first`` applied first, then ``second`` (PDF row-vector convention)."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def linear_part(matrix: Matrix) -> Matrix:
    return (matrix[0], matrix[1], matrix[2], matrix[3], 0.0, 0.0)


def transform_point(point: Point, matrix: Matrix) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def transform_rect(rect: Rect, matrix: Matrix) -> Rect:
    """Axis-aligned bounds of the four transformed corners (rect-transform
    semantics: exact for quarter turns, a superset otherwise)."""
    corners = (
        transform_point((rect[0], rect[1]), matrix),
        transform_point((rect[2], rect[1]), matrix),
        transform_point((rect[0], rect[3]), matrix),
        transform_point((rect[2], rect[3]), matrix),
    )
    xs = [corner[0] for corner in corners]
    ys = [corner[1] for corner in corners]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------- glyph placement


def scale_units_to_text(
    units: Rect, units_per_em: int, font_size: float, hscale: float
) -> Rect:
    """Font-unit bounds → the show's text space: ``[Tfs·Th, 0, 0, Tfs]``.

    ``hscale`` is ``Tz / 100`` and may be negative (mirrored text); the
    result is normalized so ``x0 <= x1``.
    """
    sx = font_size * hscale / units_per_em
    sy = font_size / units_per_em
    x0, x1 = units[0] * sx, units[2] * sx
    y0, y1 = units[1] * sy, units[3] * sy
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def place_text_rect(
    rect_text: Rect,
    cursor_x: float,
    rise: float,
    tm: Matrix,
    ctm: Matrix,
    base: Matrix,
) -> Rect:
    """A text-space rect at the glyph's cursor position → derotated page.

    Chain: translate by ``(cursor_x, rise)`` → ``Tm × CTM`` → ``base``
    (the page transform captured at rotation 0).  Every corner rides the
    full chain; no ``+x`` assumption anywhere.
    """
    translated = (
        rect_text[0] + cursor_x,
        rect_text[1] + rise,
        rect_text[2] + cursor_x,
        rect_text[3] + rise,
    )
    return transform_rect(translated, matrix_concat(matrix_concat(tm, ctm), base))


# -------------------------------------------------------- stroke expansion

# PDF /LineJoin values reachable from a content stream's ``j`` operator
# (ISO 32000-1 8.5.2, Table 55). MuPDF's internal ``FZ_LINEJOIN_MITER_XPS``
# (3) has no PDF operator and is out of scope: it is never produced by any
# content stream this codebase writes or a spec-compliant PDF parses to.
LINEJOIN_MITER = 0
LINEJOIN_ROUND = 1
LINEJOIN_BEVEL = 2


def stroke_expansion(
    linewidth: float,
    ctm: Matrix,
    miterlimit: float = 10.0,
    linejoin: int = LINEJOIN_MITER,
) -> float:
    """The scalar MuPDF adds on every side of a bbox to bound a stroke.

    Pins ``fz_adjust_rect_for_stroke()`` (MuPDF, called from PyMuPDF
    1.27.1's ``jm_bbox_stroke_text`` -> ``fz_bound_text(text, stroke,
    ctm)``, see ``.venv/Lib/site-packages/pymupdf/__init__.py``). MuPDF
    ships no Python source for the C routine itself, so this formula is
    reverse-measured directly against the compiled ``_mupdf`` extension
    (``mupdf.FzRect.fz_adjust_rect_for_stroke`` /
    ``mupdf.FzMatrix.fz_matrix_max_expansion``) rather than read from a
    header, and MUST be re-measured (not assumed) after any MuPDF/PyMuPDF
    upgrade:

        effective_width = abs(linewidth) or 1.0   # PDF default width is 1
        scale = max(abs(a), abs(b), abs(c), abs(d))   # ctm's linear part;
                                                       # NOT sqrt(det) or a
                                                       # singular value --
                                                       # measured, see below
        factor = max(miterlimit, 0.5) if linejoin == FZ_LINEJOIN_MITER
                 else 0.5
        expand = effective_width * factor * scale

    ``fz_bound_text`` then adds its own fixed 1.0 pt margin on top of this
    (``BBOXLOG_MARGIN`` in test_scripts/test_p4b2_oracles.py) in device
    space, same as the unstroked fill-text case; that margin is NOT part
    of this function.

    Measured facts this formula rests on (float32 MuPDF arithmetic; expect
    ~1e-4 relative noise, well under the pinning test's 0.02 pt tolerance):

    - ``fz_matrix_max_expansion`` is exactly ``max(|a|, |b|, |c|, |d|)``,
      not ``sqrt(|det|)`` or the matrix's largest singular value: for
      ``(a=3, b=4, c=0, d=1)`` it measures ``4.0`` (== max(3,4,0,1)),
      not ``sqrt(3) ~ 1.73`` (sqrt|det|) or ``~5.06`` (largest singular
      value). Pure shear leaves it at ``1.0`` (``c=0.5`` alongside unit
      ``a``/``d``), and translation (``e``/``f``) never affects it.
      Consequence: ``max|elem|`` can undershoot the true stretch of the
      pen (the largest singular value) -- by ``sqrt(2)`` for a rotation
      (45 degrees: every element ``0.707``, pen stretched by ``1.0``) and
      by up to ``2`` for a shear (measured ``(1, 1, 1, 1.01)``: max|elem|
      ``1.01`` vs sigma_max ``2.005``). Miter joins hide this under the ``miterlimit`` factor
      (10x by default); round/bevel joins (factor ``0.5``) do not, so for
      them the bboxlog rect bounds the stroked ink only up to the fixed
      1.0 pt margin: ``0.5 * w * (sigma_max - max|elem|) > 1.0`` is an
      under-bound (``6 w`` rotated 45 degrees at any ctm scale above
      ~1.14). The spike's stroke ladder is exposed to this; a production
      slice must treat every non-fill render mode as ambiguous by rule.
    - Miter join (0): the multiplier is ``miterlimit`` itself (not
      ``miterlimit`` scaled by any extra 0.5), floored at ``0.5`` for any
      ``miterlimit`` at or below that floor -- including 0 and negative
      values a malformed stream could carry (a compliant ``M`` operand is
      always >= 1, per ISO 32000-1 8.5.2, so this floor is a hard-clamp
      documented but not independently exercised by the pinning test).
      There is no clamp at 1.0: ``miterlimit`` values strictly between 0.5
      and 1.0 measure ``linewidth * miterlimit * scale`` exactly, same
      formula as values above 1.0.
    - Round (1) and bevel (2) joins ignore ``miterlimit`` entirely and
      always use the ``0.5`` floor (a plain half-linewidth expansion).
    - A linewidth of exactly ``0`` measures as if it were ``1.0`` (PDF's
      default stroke width), consistent with ``fz_bound_text``'s "a
      stroke is never truly invisible" hairline behaviour; the pinning
      test exercises this at identity ctm (id ``w0-identity``).

    Not covered (and not needed): dashing, line caps, and negative
    linewidths -- ``fz_adjust_rect_for_stroke`` reads ``fabsf(linewidth)``
    for the effective width, but no ``w`` operator this codebase writes
    ever emits a negative operand, so the pinning test does not exercise
    that leg beyond documenting it here.
    """
    effective_width = abs(linewidth) if linewidth != 0.0 else 1.0
    scale = max(abs(ctm[0]), abs(ctm[1]), abs(ctm[2]), abs(ctm[3]))
    if linejoin == LINEJOIN_MITER:
        factor = max(miterlimit, 0.5)
    else:
        factor = 0.5
    return effective_width * factor * scale


# ------------------------------------------------------------ render modes


def render_mode_ladder(render_mode: int) -> str:
    """Spike plan §4.4: ``exact`` (0), ``stroke`` (1/2: never exact,
    conservative from the stroked union), ``invisible`` (3), ``clip``
    (4–7: ambiguous)."""
    if render_mode == 0:
        return "exact"
    if render_mode in (1, 2):
        return "stroke"
    if render_mode == 3:
        return "invisible"
    if 4 <= render_mode <= 7:
        return "clip"
    return "unknown"


# ------------------------------------------------------------- O2 oracle


@dataclass(frozen=True)
class GlyphBounds:
    """Font-unit bounds of one glyph: exact extrema (lower) and control box
    (upper).  Both ``None`` for an empty outline."""

    lower: Rect | None
    upper: Rect | None


class OutlineOracle:
    """Per-glyph outline bounds from a TrueType program (fontTools).

    ``lower`` is :class:`BoundsPen` (exact extrema of the flattened
    outline), ``upper`` is :class:`ControlBoundsPen` (control-point box).
    MuPDF's FreeType-based bound lies between the two; the spike's
    pre-registered relation is ``lower ⊆ O1 ⊆ upper ⊕ 0.02 pt``.
    """

    def __init__(self, program: bytes) -> None:
        if TTFont is None:
            raise GeometryUnavailable("fonttools_absent")
        try:
            font = TTFont(io.BytesIO(program), lazy=True)
        except Exception:  # noqa: BLE001 - every parser error maps to one slug
            raise GeometryUnavailable("program_unparseable") from None
        try:
            tags = set(font.reader.keys())
            if "glyf" not in tags or "loca" not in tags:
                raise GeometryUnavailable("glyf_missing")
            units_per_em = int(font["head"].unitsPerEm)
            num_glyphs = int(font["maxp"].numGlyphs)
            glyph_order = font.getGlyphOrder()
            glyph_set = font.getGlyphSet()
        except GeometryUnavailable:
            raise
        except Exception:  # noqa: BLE001
            raise GeometryUnavailable("program_unparseable") from None
        if units_per_em <= 0 or num_glyphs <= 0:
            raise GeometryUnavailable("upem_invalid")
        self._font: Any = font
        self._glyph_order = glyph_order
        self._glyph_set = glyph_set
        self.units_per_em = units_per_em
        self.num_glyphs = min(num_glyphs, len(glyph_order))
        self.hinted = "fpgm" in tags or "prep" in tags
        self._cache: dict[int, GlyphBounds] = {}

    def table_offset(self, tag: str) -> int | None:
        entry = self._font.reader.tables.get(tag)
        return None if entry is None else int(entry.offset)

    def bounds(self, gid: int) -> GlyphBounds:
        if not 0 <= gid < self.num_glyphs:
            raise GeometryUnavailable("gid_out_of_range")
        cached = self._cache.get(gid)
        if cached is not None:
            return cached
        try:
            glyph = self._glyph_set[self._glyph_order[gid]]
            lower_pen = BoundsPen(self._glyph_set)
            glyph.draw(lower_pen)
            upper_pen = ControlBoundsPen(self._glyph_set)
            glyph.draw(upper_pen)
        except RecursionError:
            raise GeometryUnavailable("cyclic_composite") from None
        except Exception:  # noqa: BLE001 - message would carry glyph names
            raise GeometryUnavailable("glyph_unparseable") from None
        lower = _as_rect(lower_pen.bounds)
        upper = _as_rect(upper_pen.bounds)
        result = GlyphBounds(lower=lower, upper=upper)
        self._cache[gid] = result
        return result


def _as_rect(bounds: tuple[float, float, float, float] | None) -> Rect | None:
    if bounds is None:
        return None
    x0, y0, x1, y1 = (float(value) for value in bounds)
    return (x0, y0, x1, y1)
