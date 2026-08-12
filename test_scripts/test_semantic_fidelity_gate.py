"""Red-light tests for the Task 12 P0-C semantic fidelity gate (acceptance).

The gate judges a BEFORE/AFTER document pair for one edit region and answers
"did this commit preserve semantic fidelity?" — where fidelity means, absent
a requested style override: font identity / size / color / baseline
unchanged for the replacement, replacement ink not intersecting non-target
glyphs, and every non-target glyph exactly where it was. Doctrine pinned by
the plan (§P0-C): ``outside_diff == 0`` alone is NOT a fidelity pass — the
first test builds exactly that false negative (a font substitution with
ZERO drift outside the edit region) and requires the gate to fail it.

Phase 1 scope: acceptance harness only (imported by tests, never by
production code). Runtime enforcement is a later, separately-measured
decision (plan §9).

Every fixture is synthetic and hand-built as a document PAIR — the gate
judges documents, not engines, so each defect class is fabricated exactly.
All pairs round-trip through ``tobytes()`` + reopen, so the verdicts hold
for the persisted form (save/reopen clause of the gate contract).

Red-light note (§5.1): the harness module ``semantic_fidelity_gate`` does
not exist yet — every test here must fail at collection/import time first.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_scripts.semantic_fidelity_gate import (  # noqa: E402
    assess_semantic_fidelity,
)

TARGET = "Price 2024"
NEIGHBOR_RIGHT = "Neighbor stays"
NEIGHBOR_BELOW = "Second line stays put"

SERIF_BOLD = "tibo"  # Times-Bold — serif + bold, the identity to preserve
SANS = "helv"  # Helvetica — the substitution legacy commits actually make
SIZE = 12.0
TARGET_ORIGIN = (72.0, 700.0)
BELOW_ORIGIN = (72.0, 740.0)


def _build_page(doc: fitz.Document, target_text: str, target_font: str,
                neighbor_x: float) -> None:
    page = doc.new_page(width=595, height=842)
    page.insert_text(TARGET_ORIGIN, target_text, fontname=target_font,
                     fontsize=SIZE)
    page.insert_text((neighbor_x, TARGET_ORIGIN[1]), NEIGHBOR_RIGHT,
                     fontname=SERIF_BOLD, fontsize=SIZE)
    page.insert_text(BELOW_ORIGIN, NEIGHBOR_BELOW, fontname=SERIF_BOLD,
                     fontsize=SIZE)


def _pair(before_target: str, after_target: str, after_font: str,
          neighbor_x: float = 200.0) -> tuple[bytes, bytes, fitz.Rect]:
    """Build a (before_bytes, after_bytes, target_bbox) pair whose ONLY
    difference is the target span — neighbors are byte-identical inserts."""
    before = fitz.open()
    _build_page(before, before_target, SERIF_BOLD, neighbor_x)
    before_bytes = before.tobytes()
    target_bbox = fitz.Rect(before[0].search_for(before_target)[0])
    before.close()

    after = fitz.open()
    _build_page(after, after_target, after_font, neighbor_x)
    after_bytes = after.tobytes()
    after.close()
    return before_bytes, after_bytes, target_bbox


def test_identical_document_passes_the_gate():
    """Control: a no-op pair (same bytes twice) must pass with no
    violations — the gate cannot be unconditionally paranoid."""
    before_bytes, _after, target_bbox = _pair(TARGET, TARGET, SERIF_BOLD)
    report = assess_semantic_fidelity(
        before_bytes, before_bytes, page_idx=0, target_bbox=target_bbox
    )
    assert report.passed, f"violations: {report.violations!r}"
    assert report.violations == ()


def test_font_substitution_fails_even_with_zero_outside_drift():
    """The proven false negative: Times-Bold → Helvetica at the same origin
    and size, with every non-target glyph byte-identical (outside drift is
    exactly zero). ``outside_diff == 0`` reasoning would pass this; the
    gate must fail it on font identity alone."""
    before_bytes, after_bytes, target_bbox = _pair(TARGET, TARGET, SANS)
    report = assess_semantic_fidelity(
        before_bytes, after_bytes, page_idx=0, target_bbox=target_bbox
    )
    assert not report.passed
    assert "font_identity_changed" in report.violations
    # The failure must be PURELY the font: neighbors did not move and the
    # replacement did not invade them — otherwise this fixture would not
    # isolate the outside_diff==0 false negative.
    assert "non_target_glyph_origin_moved" not in report.violations
    assert "non_target_glyph_missing" not in report.violations
    assert "replacement_ink_overlaps_non_target" not in report.violations


def test_replacement_overlapping_neighbor_fails():
    """Same font, same size, same baseline — but the replacement is long
    enough that its ink runs into the right-hand neighbor. Must fail on
    the overlap check specifically."""
    long_replacement = TARGET + " overrunning far beyond its region"
    before_bytes, after_bytes, target_bbox = _pair(
        TARGET, long_replacement, SERIF_BOLD, neighbor_x=150.0
    )
    # Fixture self-check: the replacement really does reach the neighbor.
    assert (
        TARGET_ORIGIN[0]
        + fitz.get_text_length(long_replacement, fontname=SERIF_BOLD,
                               fontsize=SIZE)
        > 150.0
    )
    report = assess_semantic_fidelity(
        before_bytes, after_bytes, page_idx=0, target_bbox=target_bbox
    )
    assert not report.passed
    assert "replacement_ink_overlaps_non_target" in report.violations
    assert "font_identity_changed" not in report.violations
    assert "non_target_glyph_origin_moved" not in report.violations


def test_no_reflow_shrink_gap_passes():
    """The no-reflow contract: a shorter replacement leaves a visible gap
    where the old text ended — that is CORRECT behavior (neighbors must not
    move to close it), so the gate must pass."""
    before_bytes, after_bytes, target_bbox = _pair(TARGET, "P 24", SERIF_BOLD)
    report = assess_semantic_fidelity(
        before_bytes, after_bytes, page_idx=0, target_bbox=target_bbox
    )
    assert report.passed, f"violations: {report.violations!r}"
    assert report.violations == ()


def test_moved_neighbor_fails():
    """Neighbor displacement (the reflow-style defect class): the right
    neighbor re-inserted a few points away must fail on origin movement."""
    before = fitz.open()
    _build_page(before, TARGET, SERIF_BOLD, neighbor_x=200.0)
    before_bytes = before.tobytes()
    target_bbox = fitz.Rect(before[0].search_for(TARGET)[0])
    before.close()

    after = fitz.open()
    page = after.new_page(width=595, height=842)
    page.insert_text(TARGET_ORIGIN, TARGET, fontname=SERIF_BOLD, fontsize=SIZE)
    page.insert_text((206.0, TARGET_ORIGIN[1]), NEIGHBOR_RIGHT,
                     fontname=SERIF_BOLD, fontsize=SIZE)
    page.insert_text(BELOW_ORIGIN, NEIGHBOR_BELOW, fontname=SERIF_BOLD,
                     fontsize=SIZE)
    after_bytes = after.tobytes()
    after.close()

    report = assess_semantic_fidelity(
        before_bytes, after_bytes, page_idx=0, target_bbox=target_bbox
    )
    assert not report.passed
    assert "non_target_glyph_origin_moved" in report.violations


def test_style_override_does_not_silence_color_or_baseline_drift():
    """RED (verification F9): the app's ONLY style-override producer
    (``build_style_overrides``, view/text_editing.py) hardcodes
    ``color=None`` -- a color change can never be a requested outcome -- and
    a font/size override never licenses moving the baseline. The gate's
    ``style_override_requested`` flag must silence font-identity and
    font-size checks only; color and baseline must still fail."""
    # Baseline drop: same font/size, replacement sits 5pt lower (no overlap).
    before = fitz.open()
    _build_page(before, TARGET, SERIF_BOLD, neighbor_x=260.0)
    before_bytes = before.tobytes()
    target_bbox = fitz.Rect(before[0].search_for(TARGET)[0])
    before.close()

    after = fitz.open()
    page = after.new_page(width=595, height=842)
    page.insert_text((TARGET_ORIGIN[0], TARGET_ORIGIN[1] + 5.0), TARGET,
                     fontname=SERIF_BOLD, fontsize=SIZE)
    page.insert_text((260.0, TARGET_ORIGIN[1]), NEIGHBOR_RIGHT,
                     fontname=SERIF_BOLD, fontsize=SIZE)
    page.insert_text(BELOW_ORIGIN, NEIGHBOR_BELOW, fontname=SERIF_BOLD,
                     fontsize=SIZE)
    after_bytes = after.tobytes()
    after.close()

    report = assess_semantic_fidelity(
        before_bytes,
        after_bytes,
        page_idx=0,
        target_bbox=target_bbox,
        style_override_requested=True,
    )
    assert not report.passed
    assert "baseline_shifted" in report.violations
    assert "font_identity_changed" not in report.violations


def test_style_override_permits_the_requested_font_change():
    """When the USER asked for the restyle, font identity loss is the
    requested outcome, not a fidelity defect — the override flag must
    silence exactly the style checks and nothing else."""
    before_bytes, after_bytes, target_bbox = _pair(TARGET, TARGET, SANS)
    report = assess_semantic_fidelity(
        before_bytes,
        after_bytes,
        page_idx=0,
        target_bbox=target_bbox,
        style_override_requested=True,
    )
    assert report.passed, f"violations: {report.violations!r}"
