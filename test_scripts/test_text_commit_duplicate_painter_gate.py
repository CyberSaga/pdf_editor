"""Red-light matrix for the plan-time duplicate-source-painter gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    build_identity_h_fixture,
    encode_cids,
)

# Two full-width CJK chars (1.0 em each in the builder font) so
# ``len(SOURCE) * fontsize`` is the exact painted width: the abutting case
# below then shares only an edge with the second painter, not a gap.
SOURCE = "你好"
REPLACEMENT = "再"


def _first_origin(fixture) -> tuple[float, float]:
    span = fixture.page.get_text("rawdict")["blocks"][0]["lines"][0]["spans"][0]
    return tuple(float(value) for value in span["chars"][0]["origin"])


def _plan_with_second_show(
    *,
    offset: float,
    second_text: str = SOURCE,
    second_font_size: float = 12.0,
    second_resource: str | None = None,
) -> PreparedEdit | PlanRejection:
    fixture = build_identity_h_fixture(text=SOURCE)
    stream = fixture.content_bytes()
    marker = b"> Tj ET"
    assert stream.count(marker) == 1
    second_x = fixture.origin[0] + offset
    resource = second_resource or fixture.resource_name
    if second_resource is not None:
        _, resources_value = fixture.doc.xref_get_key(
            fixture.page.xref, "Resources"
        )
        resources_xref = int(resources_value.split()[0])
        fixture.doc.xref_set_key(
            resources_xref,
            f"Font/{second_resource}",
            f"{fixture.font_xref} 0 R",
        )
    second = (
        f"> Tj /{resource} {second_font_size:g} Tf "
        f"1 0 0 1 {second_x:g} {fixture.origin[1]:g} Tm "
        f"<{encode_cids(second_text).hex().upper()}> Tj ET"
    ).encode("ascii")
    fixture.doc.update_stream(fixture.content_xref, stream.replace(marker, second))
    result = prepare_plan(
        fixture.doc,
        fixture.page,
        target_text=SOURCE,
        replacement_text=REPLACEMENT,
        expected_origin=_first_origin(fixture),
        target_bbox=None,
        registry=DocumentFontRegistry(fixture.doc),
        max_tier=1,
    )
    fixture.doc.close()
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


@pytest.mark.parametrize("offset", [len(SOURCE) * 12.0, len(SOURCE) * 12.0 + 1.0])
def test_abutting_or_one_point_gap_duplicate_is_admissible(offset: float) -> None:
    result = _plan_with_second_show(offset=offset)
    assert isinstance(result, PreparedEdit), result


def test_overlapping_different_decoded_bytes_is_admissible() -> None:
    result = _plan_with_second_show(offset=1.2, second_text="末")
    assert isinstance(result, PreparedEdit), result


def test_overlapping_different_font_resource_is_admissible() -> None:
    result = _plan_with_second_show(offset=1.2, second_resource="F_ALT")
    assert isinstance(result, PreparedEdit), result


def test_unplaceable_identical_candidate_fails_closed() -> None:
    result = _plan_with_second_show(offset=20.0, second_font_size=0.0)
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "cannot prove" in result.detail
