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
