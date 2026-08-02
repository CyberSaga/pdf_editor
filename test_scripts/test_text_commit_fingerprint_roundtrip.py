"""``page_fingerprint`` must survive a ``tobytes(KEEP)`` round trip.

``TieredCommitEngine.prepare`` proves every Tier 0 candidate on a *scratch*
copy built by ``_build_scratch_copy`` -> ``doc.tobytes(encryption=KEEP)`` +
``fitz.open("pdf", ...)``.  ``prepare_tier0_plan`` measures
``page_fingerprint`` on the LIVE document and ``apply_patchset`` re-measures
it on the SCRATCH clone, so the two must agree for any candidate to survive.

They used to not.  MuPDF re-serializes every object the first time a
disk-loaded document is written, reordering each object dictionary's
top-level keys (same keys, same values, different order; a second round
trip is idempotent).  ``_update_font_dependencies`` used to fold
``doc.xref_object(...)`` *strings* into the digest, so that reordering alone
flipped the fingerprint -- while the page's content-stream bytes, its
``get_fonts(full=True)`` tuples, its annot/widget geometry and even its page
xref are all byte-identical across the same round trip.  Fixed by hashing
``_canonical_object_digest``'s order-independent ``xref_get_keys``/
``xref_get_key`` view of each object instead of the raw serialized string.

Status of this module (originally written Red-Light-First; the fix has
since landed):

* ``test_page_fingerprint_survives_keep_encryption_round_trip`` was the RED
  test and is green now that ``_update_font_dependencies`` folds an
  order-independent, canonical digest of each object's keys
  (``xref_get_keys``/``xref_get_key``, the structured API ``plan.py``'s
  ``_indirect_target`` already uses) instead of the ``xref_object()`` string.
* ``test_page_fingerprint_detects_font_dependency_mutation`` passed before
  the fix and must keep passing: it is the guard that stops the fix from
  turning the font-dependency digest into a rubber stamp.
* ``test_tiered_prepare_accepts_a_real_tier0_candidate`` was
  ``xfail(strict=True)`` (the convention ``test_text_commit_characterization.py``
  uses for "intended behaviour, blocked until the fix lands") and is now a
  plain passing test -- the fix landing is exactly what flipped it to XPASS,
  which was the signal to drop the marker.

The fixture is the real, gitignored ``test_files/test-large-file.pdf``: the
bug only reproduces on a document MuPDF loaded from disk and has never been
observed on a freshly synthesised in-memory one.  No document text is
hard-coded here -- the Tier 0 target is discovered by a bounded, deterministic
scan through the production planner itself.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    _FONT_DEPENDENCY_KEYS,
    _origin_in_page_space,
    page_fingerprint,
    read_page_streams,
)
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)
from model.text_commit.replay import replay_page_streams  # noqa: E402

LARGE_PDF = ROOT / "test_files" / "test-large-file.pdf"

# Bounded so the scan stays a test, not a corpus run.  The first Tier 0
# candidate on this fixture is found well inside it (measured: page 13,
# ~0.3s); the scan is a deterministic first-N walk, never random.
_PAGE_CAP = 24
_MIN_TARGET_LEN = 5

pytestmark = pytest.mark.skipif(
    not LARGE_PDF.exists(),
    reason="test_files/ is gitignored; this bug only reproduces on a real "
    "disk-loaded document",
)


@dataclass(frozen=True)
class _Tier0Candidate:
    """A target the production planner already accepts, minus the scratch proof."""

    page_number: int
    target_text: str
    replacement_text: str
    expected_origin: tuple[float, float]


def _swap_first_distinct_pair(text: str) -> str | None:
    """An anagram of ``text`` produced by swapping one adjacent unequal pair.

    Advance-neutral by construction and independent of the width table: the
    multiset of character codes, the length, and the space count are all
    preserved, so ``prepare_tier0_plan``'s ADVANCE_MISMATCH gate compares two
    identical sums even under the exact (1e-9) /Widths tolerance.  Returns
    ``None`` for a run of one repeated character, whose only anagram is
    itself (which would trip NO_CHANGE instead).
    """
    for index in range(len(text) - 1):
        if text[index] != text[index + 1]:
            return text[:index] + text[index + 1] + text[index] + text[index + 2 :]
    return None


def _find_tier0_candidate(doc: fitz.Document) -> _Tier0Candidate | None:
    """First target on the first ``_PAGE_CAP`` pages the planner accepts.

    Eligibility is decided by ``prepare_tier0_plan`` itself -- the production
    classifier -- not by a re-implementation of its gates, so a candidate
    returned here has provably cleared every structural, font, encoding and
    advance check.  The only thing left between it and a ``PreparedEdit`` from
    ``TieredCommitEngine.prepare`` is the scratch-copy proof.  Discovering the
    target instead of hard-coding it also keeps corpus text out of the repo.
    """
    registry = DocumentFontRegistry(doc)
    for page_number in range(min(doc.page_count, _PAGE_CAP)):
        page = doc[page_number]
        replay = replay_page_streams(read_page_streams(doc, page))
        if replay.malformed:
            continue
        for show in replay.shows:
            if show.operator != "Tj" or show.string_kind not in ("literal", "hex"):
                continue
            try:
                target_text = show.decoded_bytes.decode("latin-1")
            except UnicodeDecodeError:
                continue
            if len(target_text) < _MIN_TARGET_LEN or not target_text.isprintable():
                continue
            replacement_text = _swap_first_distinct_pair(target_text)
            if replacement_text is None or replacement_text == target_text:
                continue
            origin = _origin_in_page_space(page, show)
            plan = prepare_tier0_plan(
                doc,
                page,
                target_text=target_text,
                replacement_text=replacement_text,
                expected_origin=origin,
                target_bbox=None,
                registry=registry,
            )
            if isinstance(plan, PreparedEdit):
                return _Tier0Candidate(
                    page_number=page_number,
                    target_text=target_text,
                    replacement_text=replacement_text,
                    expected_origin=origin,
                )
    return None


def _font_declaring(doc: fitz.Document, page: fitz.Page, key: str) -> int | None:
    """xref of the first font on ``page`` that declares ``key`` directly."""
    for entry in page.get_fonts(full=True):
        font_xref = int(entry[0])
        if key in doc.xref_get_keys(font_xref):
            return font_xref
    return None


def test_page_fingerprint_survives_keep_encryption_round_trip():
    """The scratch clone's fingerprint must equal the live document's.

    Asserts the *inputs* first: page xref, decoded content-stream bytes and
    the ``get_fonts(full=True)`` metadata tuples are all identical across the
    round trip, which pins the drift on the one remaining fingerprint input --
    the ``xref_object()`` strings ``_update_font_dependencies`` folds in.
    """
    doc = fitz.open(str(LARGE_PDF))
    try:
        page = doc[0]
        live_fingerprint = page_fingerprint(doc, page)
        live_streams = tuple(read_page_streams(doc, page))
        live_fonts = tuple(page.get_fonts(full=True))
        live_annots = tuple((a.xref, tuple(a.rect)) for a in page.annots())

        clone = fitz.open(
            "pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        )
        try:
            clone_page = clone[0]

            assert clone_page.xref == page.xref, (
                "page xref changed across the round trip; the plan's page "
                "identity would be stale for an unrelated reason"
            )
            assert tuple(read_page_streams(clone, clone_page)) == live_streams, (
                "content-stream bytes changed across the round trip"
            )
            assert tuple(clone_page.get_fonts(full=True)) == live_fonts, (
                "font resource table changed across the round trip"
            )
            assert (
                tuple((a.xref, tuple(a.rect)) for a in clone_page.annots())
                == live_annots
            ), "annotation identity/geometry changed across the round trip"

            assert page_fingerprint(clone, clone_page) == live_fingerprint, (
                "page fingerprint is not stable across tobytes(KEEP) + reopen, "
                "so every Tier 0 candidate proven on a scratch copy is "
                "rejected as stale"
            )
        finally:
            clone.close()
    finally:
        doc.close()


def test_page_fingerprint_detects_font_dependency_mutation():
    """A genuine change to a folded font dependency must flip the digest.

    ``/FirstChar`` is one of ``_FONT_DEPENDENCY_KEYS`` (it is the code range
    that indexes ``/Widths``, so changing it changes what the document says
    every glyph advances by) and -- unlike ``/BaseFont`` -- it does *not*
    appear in ``page.get_fonts(full=True)``.  Asserting the metadata tuple is
    unchanged while the fingerprint moves proves the detection came from the
    font-object digest itself, which is exactly the part the round-trip fix
    rewrites.  Passes today; it exists to stop the fix from becoming a rubber
    stamp.
    """
    assert "FirstChar" in _FONT_DEPENDENCY_KEYS

    doc = fitz.open(str(LARGE_PDF))
    try:
        page = doc[0]
        font_xref = _font_declaring(doc, page, "FirstChar")
        assert font_xref is not None, "fixture has no page-0 font declaring /FirstChar"
        kind, value = doc.xref_get_key(font_xref, "FirstChar")
        assert kind == "int"

        before_fingerprint = page_fingerprint(doc, page)
        before_fonts = tuple(page.get_fonts(full=True))

        doc.xref_set_key(font_xref, "FirstChar", str(int(value) + 1))

        assert tuple(page.get_fonts(full=True)) == before_fonts, (
            "precondition: the font metadata tuple must be blind to this "
            "mutation, or the test would pass without reading the font object"
        )
        assert doc.xref_get_key(font_xref, "FirstChar") == (
            "int",
            str(int(value) + 1),
        ), "the mutation did not take effect"
        assert page_fingerprint(doc, page) != before_fingerprint, (
            "page fingerprint ignored a real change to a folded font "
            "dependency; a plan measured under the old width table would "
            "still count as fresh"
        )
    finally:
        doc.close()


def test_tiered_prepare_accepts_a_real_tier0_candidate():
    """A candidate the planner accepts must survive the scratch proof too.

    ``prepare`` differs from ``prepare_tier0_plan`` only by that proof, so a
    rejection here is the scratch path refusing a candidate every production
    gate already passed.  Also asserts the live document is left untouched --
    preparation is required to be non-mutating.
    """
    doc = fitz.open(str(LARGE_PDF))
    try:
        candidate = _find_tier0_candidate(doc)
        if candidate is None:
            pytest.skip(
                f"no Tier 0 candidate in the first {_PAGE_CAP} pages of this fixture"
            )
        page = doc[candidate.page_number]
        streams_before = tuple(read_page_streams(doc, page))
        fingerprint_before = page_fingerprint(doc, page)

        engine = TieredCommitEngine(doc)
        result = engine.prepare(
            page,
            target_text=candidate.target_text,
            replacement_text=candidate.replacement_text,
            expected_origin=candidate.expected_origin,
        )

        assert tuple(read_page_streams(doc, page)) == streams_before, (
            "prepare() mutated the live document's content streams"
        )
        assert page_fingerprint(doc, page) == fingerprint_before, (
            "prepare() disturbed the live page"
        )
        assert not isinstance(result, PlanRejection), (
            f"prepare() rejected a planner-accepted Tier 0 candidate: "
            f"{result.reason if isinstance(result, PlanRejection) else ''} | "
            f"{result.detail if isinstance(result, PlanRejection) else ''}"
        )
        assert isinstance(result, PreparedEdit)
        assert result.page_xref == page.xref
        assert result.replacement_text == candidate.replacement_text
        assert result.original_text == candidate.target_text
        assert result.page_fingerprint == fingerprint_before
    finally:
        doc.close()
