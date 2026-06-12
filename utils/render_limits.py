from __future__ import annotations

import fitz

_MAX_PIXMAP_PX = 40_000_000  # ~40 MP per rendered page


def safe_render_scale(page: fitz.Page, scale: float) -> float:
    """Clamp a render scale so a single page's pixmap stays under _MAX_PIXMAP_PX.

    Normal-sized pages are returned unchanged; only pathologically large pages are
    scaled down. A 0.1 floor is kept so the result is never a degenerate render —
    note this means an extreme page (millions of points per side) can still exceed
    the cap at 0.1, which is an accepted tradeoff."""
    w, h = page.rect.width, page.rect.height
    if w * h * scale * scale > _MAX_PIXMAP_PX:
        scale = (_MAX_PIXMAP_PX / max(1.0, w * h)) ** 0.5
    return max(0.1, scale)
