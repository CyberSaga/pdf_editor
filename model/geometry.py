from __future__ import annotations

import fitz


def clamp_rect_to_page(rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    """Clamp rect to page bounds.

    Returns a 1×1 rect at the page origin if the clamped result is degenerate
    (i.e. the input rect is entirely outside the page).
    """
    x0 = max(rect.x0, page_rect.x0)
    y0 = max(rect.y0, page_rect.y0)
    x1 = min(rect.x1, page_rect.x1)
    y1 = min(rect.y1, page_rect.y1)
    if x0 >= x1 or y0 >= y1:
        return fitz.Rect(page_rect.x0, page_rect.y0, page_rect.x0 + 1, page_rect.y0 + 1)
    return fitz.Rect(x0, y0, x1, y1)


def rect_from_points(points: list[fitz.Point]) -> fitz.Rect:
    """Return the bounding rect of a list of points."""
    xs = [float(p.x) for p in points]
    ys = [float(p.y) for p in points]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def rect_union(rects: list[fitz.Rect]) -> fitz.Rect:
    """Return the union of a list of rects. Returns an empty rect for an empty list."""
    if not rects:
        return fitz.Rect()
    u = fitz.Rect(rects[0])
    for r in rects[1:]:
        u.include_rect(r)
    return u


# --- page-space conversion chokepoints ------------------------------------
#
# Two coordinate spaces coexist on a ``/Rotate`` page (docs/PITFALLS.md,
# "get_text geometry is UNROTATED page space"):
#
# * VISUAL (displayed) space -- ``page.rect`` / ``page.get_pixmap()`` -- what the
#   user sees and what every View coordinate is derived from.
# * UNROTATED (dict) space -- ``page.get_text("dict"/"rawdict")``,
#   ``get_drawings``, annotation ``/Rect``, the text index and its resolve
#   pipeline.
#
# The model's PUBLIC text-geometry surface speaks visual space; the index stays
# unrotated.  Convert at the boundary, once, through these helpers -- never
# with ad-hoc matrix arithmetic at a call site.  At ``/Rotate 0`` every helper
# is the identity, which is exactly why the mismatch is invisible there.


def visual_to_unrotated_point(page: fitz.Page, point: fitz.Point) -> fitz.Point:
    """Displayed-space point -> unrotated (dict) page space."""
    return fitz.Point(point) * page.derotation_matrix


def visual_to_unrotated_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """Displayed-space rect -> unrotated (dict) page space (axis-aligned)."""
    return (fitz.Rect(rect) * page.derotation_matrix).normalize()


def unrotated_to_visual_point(page: fitz.Page, point: fitz.Point) -> fitz.Point:
    """Unrotated (dict) page-space point -> displayed space."""
    return fitz.Point(point) * page.rotation_matrix


def unrotated_to_visual_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """Unrotated (dict) page-space rect -> displayed space (axis-aligned)."""
    return (fitz.Rect(rect) * page.rotation_matrix).normalize()


def unrotated_page_rect(page: fitz.Page) -> fitz.Rect:
    """The page's bounds in unrotated (dict) space.

    ``page.rect`` is the DISPLAYED box: on ``/Rotate 90/270`` its width and
    height are swapped, so clamping unrotated-space geometry against it
    truncates or empties rects in the lower/right band of the page.
    """
    return visual_to_unrotated_rect(page, page.rect)


def visual_text_rotation(page_rotation: int, text_rotation: int) -> int:
    """On-screen glyph rotation for text whose *unrotated* writing direction
    is ``text_rotation`` on a page displayed with ``/Rotate page_rotation``.

    Both angles are clockwise-positive in y-down coordinates
    (``rotation_degrees_from_dir`` uses ``atan2(dy, dx)`` on dict-space
    vectors; ``/Rotate`` and Qt ``setRotation`` are clockwise), so they add.
    """
    return (int(text_rotation) + int(page_rotation)) % 360


def rect_overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    """Area overlap ratio against the smaller rect (0..1).

    Returns 0.0 if either rect is empty or there is no intersection.
    Returns 1.0 when the smaller rect is fully contained within the larger.
    """
    if a.is_empty or b.is_empty:
        return 0.0
    inter = fitz.Rect(a)
    inter.intersect(b)
    if inter.is_empty:
        return 0.0
    inter_area = max(0.0, inter.width * inter.height)
    min_area = max(1.0, min(a.width * a.height, b.width * b.height))
    return inter_area / min_area
