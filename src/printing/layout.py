"""Shared paper/layout helpers for print preview and print rendering."""

from __future__ import annotations

from typing import Tuple

PAPER_SIZE_POINTS = {
    "a4": (595.0, 842.0),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}

_VALID_ORIENTATIONS = {"auto", "portrait", "landscape"}
_VALID_SCALE_MODES = {"fit", "actual", "custom"}


def normalize_orientation(value: str | None) -> str:
    orientation = (value or "auto").strip().lower()
    return orientation if orientation in _VALID_ORIENTATIONS else "auto"


def normalize_scale_mode(value: str | None, fit_to_page: bool = True) -> str:
    mode = (value or "").strip().lower()
    if mode in _VALID_SCALE_MODES:
        return mode
    return "fit" if fit_to_page else "actual"


def normalize_scale_percent(value: int | float | None) -> int:
    if value is None:
        return 100
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 100
    return max(25, min(400, numeric))


def resolve_paper_size_points(
    paper_size: str | None,
    source_width_pt: float,
    source_height_pt: float,
) -> Tuple[float, float]:
    key = (paper_size or "auto").strip().lower()
    if key == "auto":
        return max(1.0, source_width_pt), max(1.0, source_height_pt)
    return PAPER_SIZE_POINTS.get(
        key,
        (max(1.0, source_width_pt), max(1.0, source_height_pt)),
    )


def resolve_orientation(
    orientation: str | None,
    source_width: float,
    source_height: float,
) -> str:
    norm = normalize_orientation(orientation)
    if norm != "auto":
        return norm
    return "landscape" if source_width > source_height else "portrait"


def compute_target_draw_rect(
    target_width: float,
    target_height: float,
    source_width: float,
    source_height: float,
    scale_mode: str | None = "fit",
    scale_percent: int | float | None = 100,
    fit_to_page: bool = True,
) -> Tuple[float, float, float, float]:
    """
    Return centered draw rect (x, y, width, height) in target-space pixels.
    """
    tw = max(1.0, float(target_width))
    th = max(1.0, float(target_height))
    sw = max(1.0, float(source_width))
    sh = max(1.0, float(source_height))

    mode = normalize_scale_mode(scale_mode, fit_to_page=fit_to_page)
    percent = normalize_scale_percent(scale_percent)

    if mode == "fit":
        factor = min(tw / sw, th / sh)
    elif mode == "custom":
        factor = percent / 100.0
    else:
        factor = 1.0

    draw_w = max(1.0, sw * factor)
    draw_h = max(1.0, sh * factor)
    x = (tw - draw_w) / 2.0
    y = (th - draw_h) / 2.0
    return x, y, draw_w, draw_h

