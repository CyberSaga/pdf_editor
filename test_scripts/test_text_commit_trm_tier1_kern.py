"""Task 13 Priority 2 — Tier 1 kern under rotation, red-first (P2-B part 2).

The kern-compensated transplant's scalar is a TEXT-SPACE displacement and
the ``TJ`` adjustment happens in text space too — the rotation is applied
AFTER, by the text matrix and CTM.  Priority 2's job is therefore to PROVE
the existing kern arithmetic still holds under rotation, never to project
the kern onto page axes.

The decisive fixture: a rotated target ``Tj`` immediately followed by a
successor show with NO repositioning operator in between (the builder's
``tail_text``), so the successor's rendered position consumes the target's
advance.  After a kern-compensated commit whose replacement advance
differs, the successor's VISUAL origin must be unchanged in BOTH
coordinates — longer and shorter replacements, on an unrotated page with a
rotated ``Tm`` AND on the census-dominant ``/Rotate 270`` page with the
compensating −90° ``Tm``.

Also pinned here: the spliced bytes outside the plan's range never move,
the source font resource is reused (never re-embedded), save→reopen keeps
the successor origin, prepare is token-deterministic (preview↔commit
identity), the applied patch reverts byte-exactly, a raising live
verifier reverts (rollback), and a rotated Tier 1 commit is an honest
COMMITTED — not a degraded fallback needing P0-C consent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.engine as engine_module  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
    is_real_fallback_commit,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    REPLACEMENT_LONGER,
    REPLACEMENT_SHORTER,
    TAIL_TEXT,
    Type0Fixture,
    build_identity_h_fixture,
    set_text_matrix,
)

ROT90 = (0.0, 1.0, -1.0, 0.0)
ROT270 = (0.0, -1.0, 1.0, 0.0)

# Successor-origin equality tolerance, page-space points.  The kern number
# is serialized at 1e-6 precision (patch.py's %.6f), so any real drift here
# is a geometry bug, not formatting noise; the axis-aligned CONTROL below
# runs the same oracle at the same tolerance to prove it achievable.
_ORIGIN_TOL = 0.05


def _tail_fixture(
    linear: tuple[float, float, float, float] | None,
    *,
    rotate: int = 0,
    origin: tuple[float, float] = (300.0, 400.0),
) -> Type0Fixture:
    """Rotated fixture whose successor show trails the target by a
    kern-only ``[-2000] TJ`` gap (24pt at 12pt size).

    The gap is still pure text-space ADVANCE — no ``Td``/``Tm``
    repositioning — so the successor's rendered origin remains a function
    of the target's consumed advance (the kern oracle), while sitting
    clear of the 12pt growth strip a longer replacement needs proven
    blank (a successor INSIDE the strip is correctly refused by the
    blank-growth gate — that refusal is pinned elsewhere)."""
    fixture = build_identity_h_fixture(
        rotate=rotate, origin=origin, tail_text=TAIL_TEXT
    )
    stream = fixture.content_bytes()
    gapped = stream.replace(b"> Tj <", b"> Tj [-2000] TJ <", 1)
    assert gapped != stream, "fixture must carry the tail show"
    fixture.doc.update_stream(fixture.content_xref, gapped)
    if linear is not None:
        set_text_matrix(fixture, linear)
    return fixture


def _tail_origin(page: fitz.Page) -> tuple[float, float]:
    """Page-space origin of the first successor char — PyMuPDF's own
    layout as the oracle, independent of the code under test."""
    raw = page.get_text("rawdict")
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    if char["c"] == TAIL_TEXT[0]:
                        return (
                            float(char["origin"][0]),
                            float(char["origin"][1]),
                        )
    raise AssertionError("successor char not found on the page")


def _prepare(
    fixture: Type0Fixture, replacement: str
) -> tuple[TieredCommitEngine, PreparedEdit | PlanRejection]:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=replacement,
        expected_origin=None,
    )
    return engine, result


def _assert_prepared(result: PreparedEdit | PlanRejection) -> PreparedEdit:
    assert isinstance(result, PreparedEdit), (
        f"expected a PreparedEdit, got rejection "
        f"{(getattr(result, 'reason', None), getattr(result, 'detail', None))}"
    )
    return result


def _commit_and_assert_successor_fixed(
    fixture: Type0Fixture, replacement: str
) -> tuple[TieredCommitEngine, PreparedEdit]:
    before_bytes = fixture.content_bytes()
    before_origin = _tail_origin(fixture.page)
    engine, result = _prepare(fixture, replacement)
    prepared = _assert_prepared(result)
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        outcome.degraded_reason,
    )
    after_origin = _tail_origin(fixture.page)
    assert after_origin[0] == pytest.approx(before_origin[0], abs=_ORIGIN_TOL)
    assert after_origin[1] == pytest.approx(before_origin[1], abs=_ORIGIN_TOL)
    # The commit is exactly the planned splice: bytes outside the plan's
    # range are untouched.
    replacement_span = prepared.replacement
    expected = (
        before_bytes[: replacement_span.start]
        + replacement_span.replacement_bytes
        + before_bytes[replacement_span.end :]
    )
    assert fixture.content_bytes() == expected
    # Source font resource reused — never re-embedded or substituted.
    assert outcome.font_outcomes[0].action == (
        FontResourceAction.SOURCE_RESOURCE_REUSED
    )
    return engine, prepared


# ==========================================================================
# CONTROL — the same oracle on the axis-aligned Tier 1 path (green today):
# proves the successor-origin tolerance is achievable, so a rotated failure
# is a geometry bug, never an oracle artifact.
# ==========================================================================


def test_axis_aligned_tier1_successor_origin_control() -> None:
    for replacement in (REPLACEMENT_LONGER, REPLACEMENT_SHORTER):
        fixture = _tail_fixture(None, origin=(100.0, 400.0))
        _commit_and_assert_successor_fixed(fixture, replacement)
        fixture.doc.close()


# ==========================================================================
# Rotated Tm on an unrotated page (visual baseline UP)
# ==========================================================================


@pytest.mark.parametrize(
    "replacement",
    [REPLACEMENT_LONGER, REPLACEMENT_SHORTER],
    ids=["longer", "shorter"],
)
def test_rotated_tm_commit_preserves_successor_origin(replacement: str) -> None:
    fixture = _tail_fixture(ROT90)
    engine, prepared = _commit_and_assert_successor_fixed(fixture, replacement)
    if replacement is REPLACEMENT_LONGER:
        assert prepared.has_ink_growth is True
    else:
        assert prepared.has_ink_growth is False
    fixture.doc.close()


def test_rotated_tier1_commit_is_not_a_degraded_fallback() -> None:
    """P0-C pin: a rotated Tier 1 commit is an honest COMMITTED — no
    degraded-consent reprompt may ever attach to it."""
    fixture = _tail_fixture(ROT90)
    engine, result = _prepare(fixture, REPLACEMENT_LONGER)
    prepared = _assert_prepared(result)
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED
    assert is_real_fallback_commit(outcome) is False
    assert outcome.decision_chain == (
        "tier0:rejected:advance_mismatch",
        "tier1:committed",
    )
    assert "tier1_ink_growth" in outcome.warnings
    fixture.doc.close()


# ==========================================================================
# The census-dominant CAD idiom: /Rotate 270 page + compensating −90° Tm
# (visual baseline RIGHT)
# ==========================================================================


@pytest.mark.parametrize(
    "replacement",
    [REPLACEMENT_LONGER, REPLACEMENT_SHORTER],
    ids=["longer", "shorter"],
)
def test_cad_idiom_commit_preserves_successor_origin(replacement: str) -> None:
    fixture = _tail_fixture(ROT270, rotate=270)
    _commit_and_assert_successor_fixed(fixture, replacement)
    fixture.doc.close()


def test_rotated_commit_survives_save_reopen() -> None:
    fixture = _tail_fixture(ROT90)
    before_origin = _tail_origin(fixture.page)
    engine, result = _prepare(fixture, REPLACEMENT_LONGER)
    prepared = _assert_prepared(result)
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    extracted = "".join(reopened[0].get_text().split())
    assert REPLACEMENT_LONGER in extracted
    assert TAIL_TEXT in extracted
    after_origin = _tail_origin(reopened[0])
    assert after_origin[0] == pytest.approx(before_origin[0], abs=_ORIGIN_TOL)
    assert after_origin[1] == pytest.approx(before_origin[1], abs=_ORIGIN_TOL)
    reopened.close()


# ==========================================================================
# The kern scalar stays text-space arithmetic
# ==========================================================================


def test_kern_scalar_is_rotation_invariant_and_serialized_in_text_space() -> None:
    """The SAME text-space advance delta must yield the SAME kern number
    rotated or not — a page-axis projection (negated, swapped, or split
    into components) fails this immediately."""
    axis = _tail_fixture(None, origin=(100.0, 400.0))
    _, axis_result = _prepare(axis, REPLACEMENT_LONGER)
    axis_prepared = _assert_prepared(axis_result)

    rotated = _tail_fixture(ROT90)
    _, rotated_result = _prepare(rotated, REPLACEMENT_LONGER)
    rotated_prepared = _assert_prepared(rotated_result)

    assert rotated_prepared.source_advance == pytest.approx(
        axis_prepared.source_advance
    )
    assert rotated_prepared.replacement_advance == pytest.approx(
        axis_prepared.replacement_advance
    )
    assert rotated_prepared.kern_adjustment == pytest.approx(
        axis_prepared.kern_adjustment
    )
    # And the spliced operator carries exactly that scalar, %.6f, once —
    # ``[<hex> K] TJ`` with K in TEXT space.
    expected_suffix = (
        f" {rotated_prepared.kern_adjustment:.6f}] TJ".encode("ascii")
    )
    assert rotated_prepared.replacement.replacement_bytes.endswith(
        expected_suffix
    ), rotated_prepared.replacement.replacement_bytes
    axis.doc.close()
    rotated.doc.close()


def test_prepared_edit_carries_the_shared_growth_direction_slug() -> None:
    """ONE shared cardinal ``growth_direction`` rides the PreparedEdit (and
    from there every verify probe): the visual baseline direction slug."""
    axis = _tail_fixture(None, origin=(100.0, 400.0))
    _, axis_result = _prepare(axis, REPLACEMENT_LONGER)
    assert _assert_prepared(axis_result).growth_direction == "right"
    axis.doc.close()

    rotated = _tail_fixture(ROT90)
    _, rotated_result = _prepare(rotated, REPLACEMENT_LONGER)
    assert _assert_prepared(rotated_result).growth_direction == "up"
    rotated.doc.close()

    cad = _tail_fixture(ROT270, rotate=270)
    _, cad_result = _prepare(cad, REPLACEMENT_LONGER)
    assert _assert_prepared(cad_result).growth_direction == "right"
    cad.doc.close()


def test_rotated_verify_bbox_grows_along_the_visual_baseline() -> None:
    """90° Tm on an unrotated page runs visually UP: the widened region
    must extend the verify bbox's TOP edge (visual y0), leaving the other
    three edges alone — never ``x1 += growth``."""
    fixture = _tail_fixture(ROT90)
    _, result = _prepare(fixture, REPLACEMENT_LONGER)
    prepared = _assert_prepared(result)
    assert prepared.verify_bbox_page is not None
    target = prepared.target_bbox_page
    verify = prepared.verify_bbox_page
    growth = prepared.replacement_advance - prepared.source_advance
    assert growth > 10.0  # the fixture's +1 em at 12pt
    assert verify[1] == pytest.approx(target[1] - growth, abs=0.1)
    assert verify[0] == pytest.approx(target[0], abs=0.1)
    assert verify[2] == pytest.approx(target[2], abs=0.1)
    assert verify[3] == pytest.approx(target[3], abs=0.1)
    fixture.doc.close()


# ==========================================================================
# Identity, revert, rollback
# ==========================================================================


def test_rotated_prepare_is_token_deterministic() -> None:
    """Preview↔commit identity: byte-identical documents yield the same
    plan token, so the candidate the preview showed IS the one committed."""
    first = _tail_fixture(ROT90)
    _, first_result = _prepare(first, REPLACEMENT_LONGER)
    second = _tail_fixture(ROT90)
    _, second_result = _prepare(second, REPLACEMENT_LONGER)
    assert (
        _assert_prepared(first_result).token
        == _assert_prepared(second_result).token
    )
    first.doc.close()
    second.doc.close()


def test_rotated_applied_patch_reverts_byte_exactly() -> None:
    fixture = _tail_fixture(ROT90)
    before = fixture.content_bytes()
    _, result = _prepare(fixture, REPLACEMENT_LONGER)
    prepared = _assert_prepared(result)
    patchset = PatchSet(
        page_xref=prepared.page_xref,
        replacements=(prepared.replacement,),
        expected_page_fingerprint=prepared.page_fingerprint,
    )
    applied = apply_patchset(fixture.doc, fixture.page, patchset)
    assert fixture.content_bytes() != before
    applied.revert(fixture.doc)
    assert fixture.content_bytes() == before
    fixture.doc.close()


def test_rotated_live_verifier_raise_reverts_the_stream(monkeypatch) -> None:
    fixture = _tail_fixture(ROT90)
    engine, result = _prepare(fixture, REPLACEMENT_LONGER)
    prepared = _assert_prepared(result)
    before = fixture.content_bytes()

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("verifier exploded mid-commit")

    monkeypatch.setattr(engine_module, "verify_tier1_commit", _boom)
    with pytest.raises(RuntimeError):
        engine.commit(prepared)
    assert fixture.content_bytes() == before, (
        "a raising live verifier must leave the stream byte-identical"
    )
    fixture.doc.close()
