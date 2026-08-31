"""Red-light matrix for Tier 1's flag-immune background sampling box."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier1_commit,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    REPLACEMENT_LONGER,
    Type0Fixture,
    append_page_content,
    build_identity_h_fixture,
    install_image_xobject,
    install_shading_form_xobject,
)


def _target_bbox_visual(fixture: Type0Fixture) -> tuple[float, float, float, float]:
    chars = []
    for block in fixture.page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(char["c"] for char in span["chars"])
                if fixture.text in text:
                    start = text.index(fixture.text)
                    chars = span["chars"][start : start + len(fixture.text)]
                    break
    assert chars
    raw = fitz.Rect(
        min(char["bbox"][0] for char in chars),
        min(char["bbox"][1] for char in chars),
        max(char["bbox"][2] for char in chars),
        max(char["bbox"][3] for char in chars),
    )
    visual = raw * fixture.page.rotation_matrix
    return tuple(float(v) for v in visual)


def _prepare(fixture: Type0Fixture) -> PreparedEdit | PlanRejection:
    return TieredCommitEngine(fixture.doc, max_tier=1).prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_LONGER,
        expected_origin=None,
        target_bbox=_target_bbox_visual(fixture),
    )


def _with_small_glyph_heights(value: bool, callback):
    prior = bool(fitz.TOOLS.set_small_glyph_heights())
    try:
        fitz.TOOLS.set_small_glyph_heights(value)
        return callback()
    finally:
        fitz.TOOLS.set_small_glyph_heights(prior)


@pytest.mark.parametrize("small", [True, False], ids=["flag-on", "flag-off"])
def test_dense_cjk_growth_uses_the_same_metric_background_box(small: bool) -> None:
    fixture = build_identity_h_fixture()
    result = _with_small_glyph_heights(small, lambda: _prepare(fixture))
    assert isinstance(result, PreparedEdit), result
    assert result.has_ink_growth is True
    assert result.background_bbox_page is not None
    fixture.doc.close()


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_dense_cjk_metric_background_box_is_rotation_correct(rotate: int) -> None:
    fixture = build_identity_h_fixture(rotate=rotate)
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PreparedEdit), result
    assert result.background_bbox_page is not None
    fixture.doc.close()


@pytest.mark.parametrize("obstacle", ["vector", "image", "shading"])
def test_growth_zone_ink_stays_rejected_with_metric_sampling(obstacle: str) -> None:
    fixture = build_identity_h_fixture()
    if obstacle == "vector":
        append_page_content(fixture, "q 0 0 0 rg 122 690 6 20 re f Q")
    elif obstacle == "image":
        install_image_xobject(fixture, name="ImB", rgb=(0, 0, 0))
        append_page_content(fixture, "q 6 0 0 20 122 690 cm /ImB Do Q")
    else:
        install_shading_form_xobject(
            fixture, name="ShB", bbox=(122.0, 690.0, 128.0, 710.0)
        )
        append_page_content(fixture, "/ShB Do")
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    fixture.doc.close()


def test_ink_at_the_exact_growth_boundary_stays_rejected() -> None:
    fixture = build_identity_h_fixture()
    append_page_content(fixture, "q 0 0 0 rg 120 690 1 20 re f Q")
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    fixture.doc.close()


def test_white_on_white_target_stays_rejected() -> None:
    fixture = build_identity_h_fixture()
    stream = fixture.content_bytes()
    fixture.doc.update_stream(fixture.content_xref, b"1 1 1 rg " + stream)
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    assert "ink is not visible" in result.detail
    fixture.doc.close()


def test_none_background_box_keeps_legacy_target_bbox_sampling() -> None:
    fixture = build_identity_h_fixture()

    def exercise() -> VerificationFailure | tuple[str, ...]:
        prepared = _prepare(fixture)
        assert isinstance(prepared, PreparedEdit), prepared
        legacy = dataclasses.replace(prepared, background_bbox_page=None)
        pre_state = capture_page_state(fixture.doc, fixture.page, legacy)
        apply_patchset(
            fixture.doc,
            fixture.page,
            PatchSet(
                page_xref=legacy.page_xref,
                replacements=(legacy.replacement,),
                expected_page_fingerprint=legacy.page_fingerprint,
            ),
        )
        return verify_tier1_commit(fixture.doc, fixture.page, legacy, pre_state)

    result = _with_small_glyph_heights(True, exercise)
    assert isinstance(result, VerificationFailure), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    assert "no majority background colour" in result.detail
    fixture.doc.close()
