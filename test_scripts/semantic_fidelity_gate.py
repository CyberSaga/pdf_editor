"""Semantic fidelity gate — Task 12 P0-C acceptance harness (test-side only).

Judges a BEFORE/AFTER document pair for one edit region: absent a requested
style override, the replacement must keep the target's font identity, size,
color and baseline; replacement ink must not intersect non-target glyphs;
and every non-target glyph must sit exactly where it was. The verdict is
extraction-based (``get_text("rawdict")`` character records), never a
raster diff — the plan pins that ``outside_diff == 0`` alone is NOT a
fidelity pass (a same-metrics font substitution renders zero drift outside
the edit region while destroying the document's typography).

Deliberately lives in ``test_scripts/`` and is imported only by tests:
Phase 1 scope is acceptance, not runtime enforcement (plan §9 keeps the
always-on question open until its latency is measured). Production layers
must not import this module.

Scope limits (known, accepted for Phase 1 — see plan §7 decisions record):
non-text replacement ink (an opaque fill/image occluding a neighbor) is
invisible to this gate, which reads only ``rawdict`` text spans and never
rasterizes; and a mixed-style target region (e.g. two different fonts in
one edit's bbox) is judged only against its FIRST character's style, so a
flatten-to-a-different-segment's-style defect can slip through. Neither
gap is exercised by the motivating evidence (every proven defect class is
single-style, text-only). Widen before this gate judges real commits with
mixed-style or graphical-occlusion inputs.

Verdicts carry reason codes only — never document text, filenames, or
paths (data policy §10).
"""
from __future__ import annotations

from dataclasses import dataclass

import fitz

# Tolerances (pt). Origins compare within a quarter point — synthetic
# acceptance fixtures are exact, and real commits that "almost" preserve an
# origin have moved it. The overlap epsilon ignores sub-half-point bbox
# kisses between adjacent glyph boxes on the same line.
_ORIGIN_TOL = 0.25
_BASELINE_TOL = 0.75
_SIZE_TOL = 0.05
_OVERLAP_EPS = 0.5
_MOVED_SEARCH_RADIUS = 12.0

# Violation reason codes (stable, telemetry-safe).
FONT_IDENTITY_CHANGED = "font_identity_changed"
FONT_SIZE_CHANGED = "font_size_changed"
COLOR_CHANGED = "color_changed"
BASELINE_SHIFTED = "baseline_shifted"
REPLACEMENT_OVERLAPS = "replacement_ink_overlaps_non_target"
NON_TARGET_MOVED = "non_target_glyph_origin_moved"
NON_TARGET_MISSING = "non_target_glyph_missing"


@dataclass(frozen=True)
class FidelityReport:
    """Gate verdict: ``passed`` iff ``violations`` is empty."""

    passed: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class _Char:
    char: str
    origin: tuple[float, float]
    bbox: tuple[float, float, float, float]
    font: str
    size: float
    color: int


def _page_chars(data: bytes, page_idx: int) -> list[_Char]:
    """Non-whitespace character records of one page, from raw bytes.

    Opening from bytes makes every assessment a reopen assessment: verdicts
    hold for the persisted form, not a live in-memory document state.
    """
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        raw = doc[page_idx].get_text("rawdict")
    finally:
        doc.close()
    chars: list[_Char] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font = str(span.get("font", ""))
                size = float(span.get("size", 0.0))
                color = int(span.get("color", 0))
                for entry in span.get("chars", []):
                    char = entry.get("c", "")
                    if not char or char.isspace():
                        continue
                    origin = entry["origin"]
                    bbox = entry["bbox"]
                    chars.append(
                        _Char(
                            char=char,
                            origin=(float(origin[0]), float(origin[1])),
                            bbox=(
                                float(bbox[0]),
                                float(bbox[1]),
                                float(bbox[2]),
                                float(bbox[3]),
                            ),
                            font=font,
                            size=size,
                            color=color,
                        )
                    )
    return chars


def _in_target(char: _Char, target_bbox: fitz.Rect) -> bool:
    center_x = (char.bbox[0] + char.bbox[2]) / 2.0
    center_y = (char.bbox[1] + char.bbox[3]) / 2.0
    probe = fitz.Rect(target_bbox)
    probe.x0 -= _ORIGIN_TOL
    probe.y0 -= _ORIGIN_TOL
    probe.x1 += _ORIGIN_TOL
    probe.y1 += _ORIGIN_TOL
    return probe.contains(fitz.Point(center_x, center_y))


def _same_place(a: _Char, b: _Char, tol: float) -> bool:
    return (
        abs(a.origin[0] - b.origin[0]) <= tol
        and abs(a.origin[1] - b.origin[1]) <= tol
    )


def _same_style(a: _Char, b: _Char) -> bool:
    return (
        a.font == b.font
        and abs(a.size - b.size) <= _SIZE_TOL
        and a.color == b.color
    )


def _boxes_overlap(a: _Char, b: _Char) -> bool:
    overlap = fitz.Rect(a.bbox) & fitz.Rect(b.bbox)
    return overlap.width > _OVERLAP_EPS and overlap.height > _OVERLAP_EPS


def assess_semantic_fidelity(
    before_bytes: bytes,
    after_bytes: bytes,
    *,
    page_idx: int,
    target_bbox: fitz.Rect,
    style_override_requested: bool = False,
) -> FidelityReport:
    """Judge one edit region of one page across a BEFORE/AFTER pair.

    ``target_bbox`` (page space, BEFORE coordinates) delimits the glyphs
    the edit was allowed to change; everything outside it is non-target.
    AFTER characters are matched one-to-one against BEFORE non-target
    characters (same glyph, same style, origin within tolerance); whatever
    remains unmatched is the replacement and is judged against the BEFORE
    target's style and baseline.
    """
    before_chars = _page_chars(before_bytes, page_idx)
    after_chars = _page_chars(after_bytes, page_idx)

    target_before = [c for c in before_chars if _in_target(c, target_bbox)]
    non_target_before = [c for c in before_chars if not _in_target(c, target_bbox)]

    violations: set[str] = set()

    # One-to-one matching: every BEFORE non-target glyph must reappear
    # unmoved and unrestyled.
    unmatched_after = list(after_chars)
    matched_after: list[_Char] = []
    for before_char in non_target_before:
        found = None
        for candidate in unmatched_after:
            if (
                candidate.char == before_char.char
                and _same_style(candidate, before_char)
                and _same_place(candidate, before_char, _ORIGIN_TOL)
            ):
                found = candidate
                break
        if found is not None:
            unmatched_after.remove(found)
            matched_after.append(found)
            continue
        moved = any(
            candidate.char == before_char.char
            and _same_style(candidate, before_char)
            and _same_place(candidate, before_char, _MOVED_SEARCH_RADIUS)
            for candidate in unmatched_after
        )
        violations.add(NON_TARGET_MOVED if moved else NON_TARGET_MISSING)

    # Whatever the matching did not consume is the replacement ink.
    replacement = unmatched_after

    if replacement and target_before:
        reference = target_before[0]
        baseline_y = reference.origin[1]
        for char in replacement:
            # A style override can only ever request font/size (the app's
            # sole producer, view/text_editing.py build_style_overrides,
            # hardcodes color=None and has no baseline control) -- so ONLY
            # those two checks may be silenced by the flag. Color and
            # baseline stay live regardless: neither is a requestable
            # outcome, so drift in either is always a defect.
            if not style_override_requested:
                if char.font != reference.font:
                    violations.add(FONT_IDENTITY_CHANGED)
                if abs(char.size - reference.size) > _SIZE_TOL:
                    violations.add(FONT_SIZE_CHANGED)
            if char.color != reference.color:
                violations.add(COLOR_CHANGED)
            if abs(char.origin[1] - baseline_y) > _BASELINE_TOL:
                violations.add(BASELINE_SHIFTED)

    # Replacement ink may never intersect surviving non-target glyphs —
    # regardless of any style override.
    for char in replacement:
        if any(_boxes_overlap(char, kept) for kept in matched_after):
            violations.add(REPLACEMENT_OVERLAPS)
            break

    ordered = tuple(sorted(violations))
    return FidelityReport(passed=not ordered, violations=ordered)
