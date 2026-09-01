"""Red-light matrix for the plan-time duplicate-source-painter gate."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    build_identity_h_fixture,
    cid_for,
    encode_cids,
    identity_cidtogid_bytes,
)

# Two full-width CJK chars (1.0 em each in the builder font) so
# ``len(SOURCE) * fontsize`` is the exact painted width: the abutting case
# below then shares only an edge with the second painter, not a gap.
SOURCE = "你好"
REPLACEMENT = "再"
FONTSIZE = 12.0
SOURCE_WIDTH = len(SOURCE) * FONTSIZE


def _first_origin(fixture) -> tuple[float, float]:
    span = fixture.page.get_text("rawdict")["blocks"][0]["lines"][0]["spans"][0]
    return tuple(float(value) for value in span["chars"][0]["origin"])


def _build_second_show_doc(
    *,
    offset: float,
    second_text: str = SOURCE,
    second_font_size: float = FONTSIZE,
    second_resource: str | None = None,
    second_alias_font_xref: bool = True,
    second_font_encoding: str | None = None,
    second_char_spacing: float = 0.0,
    second_word_spacing: float = 0.0,
    second_rise: float = 0.0,
    second_dy: float = 0.0,
    second_operator: str = "Tj",
    second_leading_kern: float = 0.0,
    second_clone_font: bool = False,
    second_clone_degraded: bool = False,
    second_clone_width: int | None = None,
    second_clone_distinct_cidtogid: bool = False,
    second_matrix: str | None = None,
    second_dangling: bool = False,
):
    """One page painting ``SOURCE`` twice; the second show is configurable.

    Returns ``(fixture, expected_origin)``. ``expected_origin`` is captured
    from the PRISTINE page so binding always addresses the FIRST painter,
    even when the second one is placed to its left.
    """
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    expected_origin = _first_origin(fixture)
    resource = second_resource or fixture.resource_name
    if second_dangling:
        # Named but never registered: the registry cannot resolve it, so
        # neither identity nor extent is provable for this painter.
        resource = "F_MISSING"
    elif second_clone_font:
        # A cloned font DICTIONARY: new xref, new /BaseFont subset tag, the
        # same descendant/program/width evidence — it paints identically.
        clone_descendant: int | None = None
        if second_clone_width is not None or second_clone_distinct_cidtogid:
            clone_descendant = fixture.doc.get_new_xref()
            fixture.doc.update_object(
                clone_descendant,
                fixture.doc.xref_object(fixture.descendant_xref),
            )
            if second_clone_width is not None:
                widths = "[ " + " ".join(
                    f"{cid_for(char)} [ {second_clone_width} ]" for char in SOURCE
                ) + " ]"
                fixture.doc.xref_set_key(clone_descendant, "W", widths)
                fixture.doc.xref_set_key(clone_descendant, "DW", "900")
            if second_clone_distinct_cidtogid:
                count = max(cid_for(char) for char in SOURCE) + 2
                table = bytearray(identity_cidtogid_bytes(count))
                for char in SOURCE:
                    cid = cid_for(char)
                    table[2 * cid : 2 * cid + 2] = (cid + 1).to_bytes(2, "big")
                map_xref = fixture.doc.get_new_xref()
                fixture.doc.update_object(map_xref, "<<>>")
                fixture.doc.update_stream(map_xref, bytes(table))
                fixture.doc.xref_set_key(
                    clone_descendant, "CIDToGIDMap", f"{map_xref} 0 R"
                )
        clone = fixture.doc.get_new_xref()
        fixture.doc.update_object(clone, "<<>>")
        for key in fixture.doc.xref_get_keys(fixture.font_xref):
            _, value = fixture.doc.xref_get_key(fixture.font_xref, key)
            if key == "BaseFont":
                value = "/ZZZZZZ+CloneFace"
            elif key == "DescendantFonts" and clone_descendant is not None:
                value = f"[ {clone_descendant} 0 R ]"
            fixture.doc.xref_set_key(clone, key, value)
        if second_clone_degraded:
            # The registry cannot finish building this capability, so it can
            # prove neither identity nor difference — but the face still
            # paints the same glyphs.
            fixture.doc.xref_set_key(clone, "ToUnicode", "null")
        _, resources_value = fixture.doc.xref_get_key(fixture.page.xref, "Resources")
        resources_xref = int(resources_value.split()[0])
        fixture.doc.xref_set_key(
            resources_xref, f"Font/{second_resource}", f"{clone} 0 R"
        )
    elif second_resource is not None:
        if second_alias_font_xref:
            # Another RESOURCE NAME for the exact same font object.
            target_xref = fixture.font_xref
        else:
            # A genuinely different font object (different program and
            # evidence), reached under its own resource name.
            target_xref = fixture.page.insert_font(fontname="helv")
            if second_font_encoding is not None:
                fixture.doc.xref_set_key(
                    target_xref, "Encoding", f"/{second_font_encoding}"
                )
        _, resources_value = fixture.doc.xref_get_key(fixture.page.xref, "Resources")
        resources_xref = int(resources_value.split()[0])
        fixture.doc.xref_set_key(
            resources_xref, f"Font/{second_resource}", f"{target_xref} 0 R"
        )
    stream = fixture.content_bytes()
    marker = b"> Tj ET"
    assert stream.count(marker) == 1
    second_x = fixture.origin[0] + offset
    body = encode_cids(second_text).hex().upper()
    if second_operator == "TJ":
        painted = f"[{second_leading_kern:g} <{body}>] TJ"
    else:
        painted = f"<{body}> Tj"
    second = (
        f"> Tj /{resource} {second_font_size:g} Tf "
        f"{second_char_spacing:g} Tc {second_word_spacing:g} Tw "
        f"{second_rise:g} Ts "
        + (
            f"{second_matrix} Tm "
            if second_matrix is not None
            else f"1 0 0 1 {second_x:g} {fixture.origin[1] + second_dy:g} Tm "
        )
        + (
            f"{painted} ET"
        )
    ).encode("ascii")
    fixture.doc.update_stream(fixture.content_xref, stream.replace(marker, second))
    return fixture, expected_origin


def _plan_with_second_show(**kwargs) -> PreparedEdit | PlanRejection:
    fixture, expected_origin = _build_second_show_doc(**kwargs)
    result = prepare_plan(
        fixture.doc,
        fixture.page,
        target_text=SOURCE,
        replacement_text=REPLACEMENT,
        expected_origin=expected_origin,
        target_bbox=None,
        registry=DocumentFontRegistry(fixture.doc),
        max_tier=1,
    )
    fixture.doc.close()
    return result


def _simple_metric_clone_plan() -> PreparedEdit | PlanRejection:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref,
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (HI) Tj "
        b"/F2 12 Tf 1 0 0 1 73.2 700 Tm (HI) Tj ET",
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    widths_600 = "[" + " ".join("600" for _ in range(95)) + "]"
    widths_800 = "[" + " ".join("800" for _ in range(95)) + "]"
    font_xrefs = []
    for widths in (widths_600, widths_800):
        font_xref = doc.get_new_xref()
        doc.update_object(
            font_xref,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            "/Encoding /WinAnsiEncoding /FirstChar 32 /LastChar 126 "
            f"/Widths {widths} >>",
        )
        font_xrefs.append(font_xref)
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /Font << /F1 {font_xrefs[0]} 0 R /F2 {font_xrefs[1]} 0 R >> >>",
    )
    result = prepare_plan(
        doc,
        page,
        target_text="HI",
        replacement_text="BY",
        expected_origin=(72.0, 142.0),
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
        max_tier=1,
    )
    doc.close()
    return result


@pytest.mark.parametrize("offset", [1.0, 1.2])
def test_overlapping_identical_source_painter_is_rejected(offset: float) -> None:
    result = _plan_with_second_show(offset=offset)
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "overlaps" in result.detail


def test_exactly_coincident_source_painters_still_fail_closed() -> None:
    result = _plan_with_second_show(offset=0.0)
    assert isinstance(result, PlanRejection), result
    # Binding itself cannot distinguish coincident candidates; either way,
    # the plan must fail closed before a patch can erase one painter only.
    assert result.reason in {
        RejectReason.AMBIGUOUS_MATCH,
        RejectReason.DUPLICATE_SOURCE_PAINTER,
    }


@pytest.mark.parametrize("offset", [SOURCE_WIDTH, SOURCE_WIDTH + 1.0])
def test_abutting_or_one_point_gap_duplicate_is_admissible(offset: float) -> None:
    result = _plan_with_second_show(offset=offset)
    assert isinstance(result, PreparedEdit), result


def test_overlapping_different_decoded_bytes_is_admissible() -> None:
    result = _plan_with_second_show(offset=1.2, second_text="末")
    assert isinstance(result, PreparedEdit), result


def test_overlapping_alias_resource_for_the_same_font_is_rejected() -> None:
    """A second RESOURCE NAME bound to the same font object is the same
    painter: resource names are aliases, never font identity."""
    result = _plan_with_second_show(offset=1.2, second_resource="F_ALT")
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


def test_overlapping_distinct_font_object_fails_closed() -> None:
    result = _plan_with_second_show(
        offset=1.2, second_resource="F_OTHER", second_alias_font_xref=False
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "font identity" in result.detail


def test_distinct_font_object_on_another_baseline_is_admissible() -> None:
    result = _plan_with_second_show(
        offset=1.2,
        second_dy=-40.0,
        second_resource="F_OTHER",
        second_alias_font_xref=False,
    )
    assert isinstance(result, PreparedEdit), result


def test_simple_font_declaring_identity_h_cannot_use_encoding_name_as_proof() -> None:
    result = _plan_with_second_show(
        offset=1.2,
        second_resource="F_OTHER",
        second_alias_font_xref=False,
        second_font_encoding="Identity-H",
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "font identity" in result.detail


def test_unplaceable_identical_candidate_fails_closed() -> None:
    result = _plan_with_second_show(offset=20.0, second_font_size=0.0)
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "cannot prove" in result.detail


# ---------------------------------------------------------------------------
# Candidate geometry must come from the CANDIDATE's own text state, never
# from the target's advance scaled by a font-size ratio.


def test_left_neighbor_without_char_spacing_is_admissible() -> None:
    """Control: the same placement is disjoint when Tc is zero."""
    result = _plan_with_second_show(offset=-(SOURCE_WIDTH + 0.5))
    assert isinstance(result, PreparedEdit), result


def test_left_neighbor_widened_by_its_own_char_spacing_is_rejected() -> None:
    """Its own Tc pushes the candidate's ink over the target; the target's
    advance (Tc == 0) would have called it disjoint."""
    result = _plan_with_second_show(
        offset=-(SOURCE_WIDTH + 0.5), second_char_spacing=2.0
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "overlaps" in result.detail


def test_left_neighbor_widened_by_its_own_font_size_is_rejected() -> None:
    result = _plan_with_second_show(
        offset=-(SOURCE_WIDTH + 0.5), second_font_size=24.0
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


def test_left_neighbor_word_spacing_does_not_widen_an_identity_h_twin() -> None:
    """Tw applies only to SINGLE-byte code 32 (PDF 32000-1 §9.3.3), so an
    Identity-H twin's width must ignore it — the candidate advance follows
    the same codec branch the target's own advance does, not a generic one."""
    result = _plan_with_second_show(
        offset=-(SOURCE_WIDTH + 0.5), second_word_spacing=40.0
    )
    assert isinstance(result, PreparedEdit), result


def test_overlapping_duplicate_raised_by_its_own_rise_still_fails_closed() -> None:
    """A raised twin must NOT buy admission.

    ``_classify_common`` refuses any target whose own rise is non-zero, so
    the target core is always pinned to the baseline.  Applying ``Ts`` to
    the CANDIDATE core alone would translate it clear of a baseline-pinned
    target and admit the edit while the twin still paints over it — a
    false-admit band starting at ``rise >= 0.6*Tfs``.  Both cores are taken
    at the baseline instead, so this stays a rejection.
    """
    result = _plan_with_second_show(offset=1.0, second_rise=2.0 * FONTSIZE)
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


@pytest.mark.parametrize(
    ("second_dy", "second_rise"),
    [(-7.2, 7.2), (7.2, -7.2)],
)
def test_candidate_rise_that_cancels_its_baseline_offset_is_rejected(
    second_dy: float, second_rise: float
) -> None:
    result = _plan_with_second_show(
        offset=1.2, second_dy=second_dy, second_rise=second_rise
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


def test_candidate_rise_does_not_block_a_provably_disjoint_line() -> None:
    result = _plan_with_second_show(offset=1.2, second_dy=-100.0, second_rise=7.2)
    assert isinstance(result, PreparedEdit), result


# ---------------------------------------------------------------------------
# Identity that survives a producer's cloning, and extents that survive a
# ``TJ`` array whose numeric items replay does not preserve.


def test_overlapping_subset_tag_clone_of_the_same_font_is_rejected() -> None:
    """A cloned font dict (new xref, new subset tag, same program and /W)
    paints the same glyphs; xref/digest inequality alone would admit it."""
    result = _plan_with_second_show(
        offset=1.2, second_resource="F_CLONE", second_clone_font=True
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


def test_overlapping_type0_metric_clone_is_rejected() -> None:
    result = _plan_with_second_show(
        offset=1.2,
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_width=1500,
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


def test_disjoint_type0_metric_clone_uses_its_own_widths() -> None:
    result = _plan_with_second_show(
        offset=SOURCE_WIDTH + 20.0,
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_width=1500,
    )
    assert isinstance(result, PreparedEdit), result


def test_overlapping_simple_metric_clone_is_rejected() -> None:
    result = _simple_metric_clone_plan()
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


def test_distinct_cid_font_is_exactly_measured_when_disjoint() -> None:
    result = _plan_with_second_show(
        offset=-(SOURCE_WIDTH + 1.0),
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_distinct_cidtogid=True,
    )
    assert isinstance(result, PreparedEdit), result


def test_overlapping_distinct_cid_font_fails_closed() -> None:
    result = _plan_with_second_show(
        offset=1.2,
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_distinct_cidtogid=True,
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "font identity" in result.detail


def test_overlapping_clone_the_registry_cannot_build_fails_closed() -> None:
    """A clone whose capability degrades (unreadable /ToUnicode) proves
    nothing about which glyphs it paints; unequal semantics must NOT be
    read as a different font."""
    result = _plan_with_second_show(
        offset=1.2,
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_degraded=True,
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "font identity" in result.detail


def test_tj_twin_whose_leading_kern_pulls_ink_over_the_target_is_rejected() -> None:
    """``ShowOp`` drops a TJ array's numeric items, so the recorded origin
    is not where the ink starts.  Measuring the candidate forward from that
    origin calls this twin disjoint; bounding its reach does not."""
    result = _plan_with_second_show(
        offset=SOURCE_WIDTH + 50.0,
        second_operator="TJ",
        second_leading_kern=6000.0,  # +6000/1000 * 12pt == 72pt to the LEFT
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "exact extent" in result.detail


def test_tj_twin_on_another_baseline_is_admissible() -> None:
    """The reach bound is horizontal only: a TJ twin one line away is still
    provably disjoint, so unprovable extents do not block every page."""
    result = _plan_with_second_show(
        offset=0.0, second_dy=-40.0, second_operator="TJ", second_leading_kern=6000.0
    )
    assert isinstance(result, PreparedEdit), result


def test_unresolvable_twin_resource_on_another_baseline_is_admissible() -> None:
    """Unprovable font identity fails closed only where it could matter;
    a twin that cannot reach the target core stays admissible."""
    fixture, expected_origin = _build_second_show_doc(offset=0.0, second_dy=-40.0)
    stream = fixture.content_bytes()
    dangling = stream.replace(
        f"> Tj /{fixture.resource_name} ".encode("ascii"), b"> Tj /F_MISSING ", 1
    )
    assert dangling != stream
    fixture.doc.update_stream(fixture.content_xref, dangling)
    result = prepare_plan(
        fixture.doc,
        fixture.page,
        target_text=SOURCE,
        replacement_text=REPLACEMENT,
        expected_origin=expected_origin,
        target_bbox=None,
        registry=DocumentFontRegistry(fixture.doc),
        max_tier=1,
    )
    fixture.doc.close()
    assert isinstance(result, PreparedEdit), result


@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"second_resource": "F_ALT"}, "alias resource"),
        ({"second_resource": "F_CLONE", "second_clone_font": True}, "cloned dict"),
        (
            {
                "second_resource": "F_CLONE",
                "second_clone_font": True,
                "second_clone_width": 1500,
            },
            "metric clone",
        ),
        ({"second_rise": 2.0 * FONTSIZE}, "raised twin"),
        ({"second_dy": -7.2, "second_rise": 7.2}, "rise-cancelled baseline"),
    ],
)
def test_commit_pipeline_never_leaves_a_twin_visible(kwargs, label) -> None:
    """Through the REAL engine: prepare + commit, not prepare_plan alone.

    Every one of these shapes reaches ``CommitStatus.COMMITTED`` under a
    gate that trusts resource names, font xrefs, or a rise-translated
    candidate core — and leaves a pixel-identical ghost behind.
    """
    fixture, expected_origin = _build_second_show_doc(offset=1.2, **kwargs)
    before = fixture.content_bytes()
    before_digest = hashlib.sha256(before).hexdigest()
    assert before.count(b"Tj") == 2
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    prepared = engine.prepare(
        fixture.page,
        target_text=SOURCE,
        replacement_text=REPLACEMENT,
        expected_origin=expected_origin,
        target_bbox=None,
    )
    assert isinstance(prepared, PlanRejection), (label, prepared)
    assert prepared.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    after = fixture.content_bytes()
    assert hashlib.sha256(after).hexdigest() == before_digest
    assert fixture.page.get_text().count(SOURCE) == 2
    fixture.doc.close()


@pytest.mark.parametrize(
    ("matrix", "label"),
    [
        ("0.001 0 0 1 72.5 700", "anisotropic, x scaled down 1000x"),
        ("1000 0 0 1 72.5 700", "anisotropic, x scaled up 1000x"),
        ("1 0 3 1 72.5 700", "sheared"),
        ("0.7071 0.7071 -0.7071 0.7071 72.5 700", "rotated 45 degrees"),
    ],
)
def test_reach_bound_holds_under_exotic_matrices(matrix: str, label: str) -> None:
    """``_painter_reach`` divides the page-relevant span by the mapped length
    of ONE text-space unit along +x — the only direction whose extent is
    unknown.  The core's y extent is mapped exactly, so anisotropy, shear and
    rotation are all carried by the mapping itself and the bound stays sound.
    """
    result = _plan_with_second_show(
        offset=0.0, second_dangling=True, second_matrix=matrix
    )
    assert isinstance(result, PlanRejection), (label, result)
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


@pytest.mark.parametrize(
    ("second_rise", "second_matrix"),
    [
        (100.0, "1 0 1 1 200 700"),
        (100.0, "1 0 3 1 400 700"),
        (50.0, "1 0 5 1 300 700"),
    ],
)
def test_sheared_large_rise_pads_the_unproven_reach_on_both_x_ends(
    second_rise: float, second_matrix: str
) -> None:
    """The unknown x extent and the rise envelope interact through shear.

    Without the ``|y| * |v| / |u|`` cross-term, the positive-x-only Tj reach
    begins at x=0 and this candidate appears horizontally disjoint.
    """
    result = _plan_with_second_show(
        offset=0.0,
        second_dangling=True,
        second_rise=second_rise,
        second_matrix=second_matrix,
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


@pytest.mark.parametrize(
    ("matrix", "label"),
    [
        ("1 0 3 1 472 400", "sheared, far off the target line"),
        ("0.001 0 0 1 71.5 660", "anisotropic, one line down"),
    ],
)
def test_reach_bound_still_admits_provably_disjoint_exotic_twins(
    matrix: str, label: str
) -> None:
    """The bound must not collapse into "reject every unprovable twin"."""
    result = _plan_with_second_show(
        offset=0.0, second_dangling=True, second_matrix=matrix
    )
    assert isinstance(result, PreparedEdit), (label, result)
