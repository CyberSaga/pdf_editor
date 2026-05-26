"""Shared paper/layout helpers for print preview and print rendering."""

from __future__ import annotations

# Portrait dimensions in points (1 pt = 1/72 inch). ISO 216 (A/B series) and
# ANSI sizes. These are the canonical sizes a printer driver recognises by name.
PAPER_SIZE_POINTS = {
    "a0": (2383.94, 3370.39),
    "a1": (1683.78, 2383.94),
    "a2": (1190.55, 1683.78),
    "a3": (841.89, 1190.55),
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
    "a6": (297.64, 419.53),
    "b4": (708.66, 1000.63),
    "b5": (498.90, 708.66),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "tabloid": (792.0, 1224.0),
    "executive": (521.86, 756.0),
}

# How close (in points) a source page must be to a standard size to match it.
# PyMuPDF rounds A4 to 595.0×842.0, so a couple of points of slack is required.
_PAPER_MATCH_TOLERANCE_PT = 3.0

_VALID_ORIENTATIONS = {"auto", "portrait", "landscape"}
_VALID_SCALE_MODES = {"fit", "actual", "custom"}


def match_standard_paper_size(
    width_pt: float,
    height_pt: float,
    tolerance_pt: float = _PAPER_MATCH_TOLERANCE_PT,
) -> str | None:
    """Return the standard paper-size key matching the given dimensions, or None.

    Matching is orientation-independent: dimensions are normalised to
    (short, long) before comparison, so a landscape A3 page still matches "a3".
    The closest size within ``tolerance_pt`` wins; genuinely non-standard sizes
    return None so callers can fall back to a custom size.
    """
    short = min(width_pt, height_pt)
    long = max(width_pt, height_pt)
    best_key: str | None = None
    best_err: float | None = None
    for key, (std_short, std_long) in PAPER_SIZE_POINTS.items():
        err = max(abs(short - std_short), abs(long - std_long))
        # Eligible if within tolerance; only replace on a strictly smaller error
        # so insertion order (most canonical sizes first) breaks exact ties.
        if err <= tolerance_pt and (best_err is None or err < best_err):
            best_err = err
            best_key = key
    return best_key


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
) -> tuple[float, float]:
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
) -> tuple[float, float, float, float]:
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

