"""Red-light matrix for positive finite horizontal-scale admission."""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, CommitTier, RejectReason  # noqa: E402
from model.text_commit.inspect import replay_page  # noqa: E402
from model.text_commit.patch import kern_for_displacement  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PreparedEdit  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    CJK_TEXT,
    REPLACEMENT_EQUAL_ADVANCE,
    REPLACEMENT_LONGER,
    REPLACEMENT_SHORTER,
    TAIL_TEXT,
    Type0Fixture,
    build_identity_h_fixture,
    encode_cids,
)


def _scaled_fixture(hscale: float, *, rotate: int = 0) -> Type0Fixture:
    fixture = build_identity_h_fixture(rotate=rotate, tail_text=TAIL_TEXT)
    stream = fixture.content_bytes()
    marker = b" Tm <"
    assert marker in stream
    fixture.doc.update_stream(
        fixture.content_xref,
        stream.replace(marker, f" Tm {hscale:g} Tz <".encode(), 1),
    )
    # Keep the successor on the same text line (so compensation is observable)
    # but put its visible glyphs beyond the one-em positive growth zone.
    stream = fixture.content_bytes()
    tail_operand = f" <{encode_cids(TAIL_TEXT).hex().upper()}> Tj".encode()
    assert tail_operand in stream
    fixture.doc.update_stream(
        fixture.content_xref,
        stream.replace(
            tail_operand,
            f" [-2000 <{encode_cids(TAIL_TEXT).hex().upper()}>] TJ".encode(),
            1,
        ),
    )
    return fixture


def _tail_origins(page: fitz.Page) -> tuple[tuple[float, float], ...]:
    origins = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    if char["c"] in TAIL_TEXT:
                        origins.append(
                            tuple(round(float(v), 3) for v in char["origin"])
                        )
    return tuple(origins)


def _prepare(
    fixture: Type0Fixture, replacement: str, *, target_bbox=None
) -> tuple[TieredCommitEngine, PreparedEdit]:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    prepared = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=target_bbox,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    return engine, prepared


@pytest.mark.parametrize("hscale", [80.0, 120.0])
def test_tier0_preserves_scaled_fallback_bbox_stream_and_successor(hscale: float) -> None:
    fixture = _scaled_fixture(hscale)
    before_tail = _tail_origins(fixture.page)
    engine, prepared = _prepare(fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    assert prepared.target_bbox_page[2] - prepared.target_bbox_page[0] == pytest.approx(
        48.0 * hscale / 100.0, abs=0.02
    )

    outcome = engine.commit(prepared)

    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert f"{hscale:g} Tz".encode() in fixture.content_bytes()
    assert _tail_origins(fixture.page) == before_tail
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    assert REPLACEMENT_EQUAL_ADVANCE in "".join(reopened[0].get_text().split())
    reopened.close()


@pytest.mark.parametrize("hscale", [80.0, 120.0])
@pytest.mark.parametrize("replacement", [REPLACEMENT_LONGER, REPLACEMENT_SHORTER])
def test_tier1_kern_is_hscale_free_and_successor_stays_fixed(
    hscale: float, replacement: str
) -> None:
    fixture = _scaled_fixture(hscale)
    before_tail = _tail_origins(fixture.page)
    engine, prepared = _prepare(fixture, replacement)
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    expected_kern = (
        -1000.0
        * (prepared.source_advance - prepared.replacement_advance)
        / prepared.font_size
    )
    assert prepared.kern_adjustment == pytest.approx(expected_kern)
    token = re.search(rb" (-?\d+\.\d{6})\] TJ", prepared.replacement.replacement_bytes)
    assert token is not None
    assert float(token.group(1)) == pytest.approx(expected_kern, abs=5e-7)

    outcome = engine.commit(prepared)

    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert _tail_origins(fixture.page) == before_tail
    fixture.doc.close()


@pytest.mark.parametrize("hscale", [80.0, 120.0])
def test_growth_and_background_baselines_use_effective_displacement(hscale: float) -> None:
    fixture = _scaled_fixture(hscale)
    _, prepared = _prepare(fixture, REPLACEMENT_LONGER)
    th = hscale / 100.0
    assert prepared.effective_verify_bbox[2] - prepared.target_bbox_page[2] == pytest.approx(
        12.0 * th, abs=0.02
    )
    assert prepared.background_bbox_page is not None
    assert prepared.background_bbox_page[2] - prepared.background_bbox_page[0] == pytest.approx(
        prepared.source_advance * th, abs=0.02
    )
    fixture.doc.close()


def test_rotate90_scaled_growth_moves_the_scaled_visual_edge() -> None:
    fixture = _scaled_fixture(80.0, rotate=90)
    _, prepared = _prepare(fixture, REPLACEMENT_LONGER)
    target = prepared.target_bbox_page
    verify = prepared.effective_verify_bbox
    extents = [abs(verify[index] - target[index]) for index in range(4)]
    assert max(extents) == pytest.approx(9.6, abs=0.05)
    assert prepared.growth_direction in {"up", "down", "left", "right"}
    fixture.doc.close()


def test_caller_bbox_is_preserved_without_double_scaling() -> None:
    fixture = _scaled_fixture(80.0)
    caller_bbox = (70.0, 125.0, 130.0, 150.0)
    _, prepared = _prepare(
        fixture, REPLACEMENT_EQUAL_ADVANCE, target_bbox=caller_bbox
    )
    assert prepared.target_bbox_page == caller_bbox
    fixture.doc.close()


@pytest.mark.parametrize(
    ("hscale_token", "fontsize_token"),
    [
        ("0." + "0" * 323 + "5", "12"),  # finite Tz, Th underflows to zero
        ("1" + "0" * 110, "1" + "0" * 200),  # effective advance overflows
    ],
)
def test_derived_horizontal_scale_values_must_remain_finite(
    hscale_token: str, fontsize_token: str
) -> None:
    fixture = build_identity_h_fixture(text=CJK_TEXT)
    stream = fixture.content_bytes()
    marker = b" Tm <"
    stream = stream.replace(b" 12 Tf", f" {fontsize_token} Tf".encode(), 1)
    fixture.doc.update_stream(
        fixture.content_xref,
        stream.replace(marker, f" Tm {hscale_token} Tz <".encode(), 1),
    )
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
        target_bbox=None,
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "effective horizontal scale" in result.detail
    fixture.doc.close()


@pytest.mark.parametrize(
    "target_bbox",
    [
        (float("nan"), 0.0, 10.0, 10.0),
        (0.0, 0.0, float("inf"), 10.0),
    ],
)
def test_nonfinite_target_bbox_is_rejected(target_bbox) -> None:
    fixture = _scaled_fixture(80.0)
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
        target_bbox=target_bbox,
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "target_bbox" in result.detail
    fixture.doc.close()


@pytest.mark.parametrize(
    "target_bbox",
    [
        (70.0, 125.0, 1.4e308, 150.0),
        (70.0, 125.0, 10**400, 150.0),
        (70.0, 125.0, 150.0),
    ],
)
def test_unrenderable_target_bbox_is_a_stable_rejection(target_bbox) -> None:
    fixture = _scaled_fixture(80.0)
    before = fixture.content_bytes()
    engine = TieredCommitEngine(fixture.doc, max_tier=1)

    result = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
        target_bbox=target_bbox,
    )

    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert result.detail == "target_bbox escapes renderable coordinates"
    assert fixture.content_bytes() == before
    fixture.doc.close()


@pytest.mark.parametrize("displacement", [float("nan"), float("inf"), 1e308])
def test_kern_for_displacement_rejects_nonfinite_input_or_result(
    displacement: float,
) -> None:
    fixture = _scaled_fixture(80.0)
    show = replay_page(fixture.doc, fixture.page).shows[0]
    if displacement == 1e308:
        show = dataclasses.replace(show, font_size=1e-308)
    with pytest.raises(ValueError, match="cannot compensate advance"):
        kern_for_displacement(show, displacement)
    fixture.doc.close()


def test_kern_for_displacement_rejects_an_overflowing_intermediate() -> None:
    """A finite RESULT is not proof of a correct result: ``font_size * 100``
    overflows to ``inf`` here and the division silently returns ``-0.0``
    where the algebraic value is ``-1e-4``."""
    fixture = _scaled_fixture(80.0)
    show = replay_page(fixture.doc, fixture.page).shows[0]
    show = dataclasses.replace(show, font_size=1e307)
    with pytest.raises(ValueError, match="overflows before the division"):
        kern_for_displacement(show, 1e300)
    fixture.doc.close()


def test_nonfinite_translation_is_rejected_under_a_finite_caller_bbox() -> None:
    """TRM shape admission inspects only the linear coefficients, so a
    non-finite ``Tm`` TRANSLATION must be refused at the planner rather than
    reaching derived Tier-1 geometry through a finite caller bbox."""
    fixture = build_identity_h_fixture(text=CJK_TEXT)
    stream = fixture.content_bytes()
    overflow = b"9" * 400
    patched = stream.replace(b" 72 700 Tm", b" " + overflow + b" 700 Tm", 1)
    assert patched != stream
    fixture.doc.update_stream(fixture.content_xref, patched)
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
        target_bbox=(70.0, 125.0, 130.0, 150.0),
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert result.detail == "text matrix or CTM holds a non-finite value"
    fixture.doc.close()


def test_tier1_derived_geometry_overflow_is_rejected_before_verification() -> None:
    """Every INPUT is finite here — a finite caller bbox, a finite uniform
    ``Tm`` scale, finite advances — but the Tier-1 background/verify boxes
    derived from them overflow.  The planner must refuse with a stable reason
    instead of handing a non-finite extent to the raster sampler."""
    fixture = build_identity_h_fixture(text=CJK_TEXT)
    stream = fixture.content_bytes()
    huge = b"1" + b"0" * 307
    patched = stream.replace(
        b"1 0 0 1 72 700 Tm", huge + b" 0 0 " + huge + b" 72 700 Tm", 1
    )
    assert patched != stream
    fixture.doc.update_stream(fixture.content_xref, patched)
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=REPLACEMENT_LONGER,
        expected_origin=None,
        target_bbox=(70.0, 125.0, 130.0, 150.0),
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    # Pinned exactly: this case must reach the DERIVED-geometry check in
    # ``_build_tier1``, not the earlier matrix or caller-bbox gates.
    assert result.detail == (
        "derived verify or background bbox escapes renderable coordinates"
    )
    fixture.doc.close()


def test_tier1_finite_but_unrenderable_geometry_is_rejected() -> None:
    """Finiteness is not the sampler's precondition.

    ``verify.py``'s ``_bbox_pixels`` does ``int(x * 96 / 72)``, which raises
    ``OverflowError`` for finite coordinates above ~1.348e308.  A tiny
    ``Tz`` decouples the growth strip (which stays a small in-page box) from
    the background quad (whose cross extent is ``font_size`` un-multiplied
    by ``Th``), so every derived coordinate can be finite and still
    unrenderable.  The planner must refuse with a ``RejectReason`` rather
    than let an exception escape ``prepare``.
    """
    fixture = build_identity_h_fixture(text=CJK_TEXT)
    stream = fixture.content_bytes()
    size = b"1" + b"0" * 303  # 1e303
    tiny = b"0." + b"0" * 304 + b"1"  # 1e-305, as a plain PDF real
    patched = re.sub(rb"/F0 [0-9.]+ Tf", b"/F0 " + size + b" Tf", stream, count=1)
    patched = patched.replace(
        b"1 0 0 1 72 700 Tm", b"150000 0 0 150000 72 700 Tm " + tiny + b" Tz", 1
    )
    assert patched != stream
    fixture.doc.update_stream(fixture.content_xref, patched)
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=CJK_TEXT,
        replacement_text=REPLACEMENT_LONGER,
        expected_origin=None,
        target_bbox=(70.0, 125.0, 130.0, 150.0),
    )
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert result.detail == (
        "derived verify or background bbox escapes renderable coordinates"
    )
    fixture.doc.close()
