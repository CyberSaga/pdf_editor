"""Task 13 Priority 2 — page-geometry staleness closure, red-first (P2-B part 4).

The Priority 2 plan consumes ``/Rotate``, ``/UserUnit``, ``/MediaBox``,
``/CropBox`` and the derived page matrices for every geometric proof, so
the page fingerprint must close over the RESOLVED page geometry: any
prepare→mutate→commit sequence that changes it must die as STALE_PLAN
with zero mutation — including a raw xref mutation that never goes
through a PyMuPDF page API (no page-object reload), and an INHERITED
attribute changed on a ``/Pages`` ancestor rather than the page dict.

Controls pin the closure honest in the other direction: folding resolved
values (not raw dict shape) keeps a direct-vs-inherited ``/Rotate``
canonically equivalent, the fingerprint is stable across a
live→tobytes→reopen round trip, and an unmutated prepare→commit still
commits.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    REPLACEMENT_EQUAL_ADVANCE,
    Type0Fixture,
    build_identity_h_fixture,
    set_text_matrix,
)

ROT90 = (0.0, 1.0, -1.0, 0.0)


def _prepare_with_engine(
    fixture: Type0Fixture,
) -> tuple[TieredCommitEngine, PreparedEdit | PlanRejection]:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    result = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_EQUAL_ADVANCE,
        expected_origin=None,
    )
    return engine, result


def _assert_prepared(result: PreparedEdit | PlanRejection) -> PreparedEdit:
    assert isinstance(result, PreparedEdit), (
        f"expected a PreparedEdit, got rejection "
        f"{(getattr(result, 'reason', None), getattr(result, 'detail', None))}"
    )
    return result


def _assert_stale_and_unmutated(
    fixture: Type0Fixture,
    engine: TieredCommitEngine,
    prepared: PreparedEdit,
    before: bytes,
) -> None:
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN, (
        outcome.status,
        outcome.degraded_reason,
    )
    assert fixture.content_bytes() == before, (
        "a stale plan must not mutate anything"
    )


def _parent_xref(fixture: Type0Fixture) -> int:
    kind, value = fixture.doc.xref_get_key(fixture.page.xref, "Parent")
    assert kind == "xref", (kind, value)
    return int(value.split()[0])


# ==========================================================================
# prepare → mutate geometry → commit must be STALE_PLAN, zero mutation
# ==========================================================================


def test_rotate_mutation_via_page_api_after_prepare_is_stale() -> None:
    fixture = build_identity_h_fixture()
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.page.set_rotation(90)
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


def test_rotate_mutation_via_raw_xref_after_prepare_is_stale() -> None:
    """The adversarial variant: the raw page-dict mutation never goes
    through a PyMuPDF page API, so no live Page object was refreshed —
    the fingerprint must read serialized geometry, not a cached view."""
    fixture = build_identity_h_fixture()
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.doc.xref_set_key(fixture.page.xref, "Rotate", "90")
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


def test_userunit_mutation_after_prepare_is_stale() -> None:
    fixture = build_identity_h_fixture()
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.doc.xref_set_key(fixture.page.xref, "UserUnit", "2")
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


def test_cropbox_mutation_after_prepare_is_stale() -> None:
    fixture = build_identity_h_fixture()
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.doc.xref_set_key(fixture.page.xref, "CropBox", "[0 0 400 500]")
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


def test_mediabox_mutation_after_prepare_is_stale() -> None:
    fixture = build_identity_h_fixture()
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.doc.xref_set_key(fixture.page.xref, "MediaBox", "[0 0 500 700]")
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


def _hoist_rotate_to_parent(fixture: Type0Fixture, rotation: int) -> int:
    """Move the page's /Rotate onto its /Pages parent (inheritance), and
    return the parent xref.  The resolved rotation must be unchanged."""
    parent = _parent_xref(fixture)
    fixture.doc.xref_set_key(fixture.page.xref, "Rotate", "null")
    fixture.doc.xref_set_key(parent, "Rotate", f"{rotation}")
    assert fixture.page.rotation == rotation, (
        "PyMuPDF must resolve the inherited /Rotate for this pin to bite"
    )
    return parent


def test_inherited_rotate_mutation_on_the_pages_ancestor_is_stale() -> None:
    """Inheritable attributes must be folded as RESOLVED values: mutating
    the ANCESTOR (page dict untouched) still changes the page's geometry
    and must go stale."""
    fixture = build_identity_h_fixture(rotate=270)
    parent = _hoist_rotate_to_parent(fixture, 270)
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.doc.xref_set_key(parent, "Rotate", "0")
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


def test_rotated_tm_plan_goes_stale_when_page_rotate_changes() -> None:
    """The P2 candidate's whole geometry proof rides the page rotation —
    a rotated-Tm plan must die stale when /Rotate changes under it."""
    fixture = build_identity_h_fixture(origin=(300.0, 400.0))
    set_text_matrix(fixture, ROT90)
    before = fixture.content_bytes()
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    fixture.page.set_rotation(90)
    _assert_stale_and_unmutated(fixture, engine, prepared, before)
    fixture.doc.close()


# ==========================================================================
# Controls — the closure must fold RESOLVED geometry, canonically
# ==========================================================================


def test_direct_and_inherited_rotate_fingerprints_are_equivalent() -> None:
    """CONTROL (green today, pinned so the geometry fold cannot regress
    it): the fingerprint folds resolved values, never raw dict shape — a
    direct /Rotate 270 and the same value inherited from /Pages must
    fingerprint identically."""
    direct = build_identity_h_fixture(rotate=270)
    inherited = build_identity_h_fixture(rotate=270)
    _hoist_rotate_to_parent(inherited, 270)
    assert page_fingerprint(direct.doc, direct.page) == page_fingerprint(
        inherited.doc, inherited.page
    )
    direct.doc.close()
    inherited.doc.close()


def test_fingerprint_is_stable_across_a_tobytes_reopen_round_trip() -> None:
    """CONTROL (green today): a canonical-equivalent round trip must never
    read as stale — the fold may only use surfaces that serialize stably."""
    fixture = build_identity_h_fixture(rotate=270)
    fixture.doc.xref_set_key(fixture.page.xref, "UserUnit", "2")
    live = page_fingerprint(fixture.doc, fixture.page)
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    assert page_fingerprint(reopened, reopened[0]) == live
    reopened.close()


def test_fingerprint_is_stable_when_userunit_is_spelled_as_a_real() -> None:
    """Review F4 (red-first): ``/UserUnit 2.0`` — an integer value spelled
    as a PDF real — must fingerprint identically live and after a
    tobytes→reopen.  MuPDF re-serializes the token minimally as the int
    ``2``, so a raw ``kind:value`` fold flips ``float:2`` → ``int:2`` on
    the scratch copy and EVERY prepare on such a document would fail its
    scratch-apply forever (fail-closed, but a whole-feature loss)."""
    fixture = build_identity_h_fixture(rotate=270)
    fixture.doc.xref_set_key(fixture.page.xref, "UserUnit", "2.0")
    live = page_fingerprint(fixture.doc, fixture.page)
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    assert page_fingerprint(reopened, reopened[0]) == live
    reopened.close()


def test_unmutated_prepare_commit_still_commits_on_geometry_rich_pages() -> None:
    """CONTROL (green today): the geometry fold must not false-stale an
    honest prepare→commit on a page that HAS nontrivial geometry."""
    fixture = build_identity_h_fixture(rotate=270)
    engine, result = _prepare_with_engine(fixture)
    prepared = _assert_prepared(result)
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        outcome.degraded_reason,
    )
    fixture.doc.close()
