"""Red-light matrix for positive finite horizontal-scale admission."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, CommitTier  # noqa: E402
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
