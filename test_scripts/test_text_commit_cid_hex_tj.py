"""Red-light matrix for Task 12 P0-D: CID/Type0 single-hex-``Tj`` slice.

Contract under test (plan §4 P0-D, scope locked §8 2026-08-13):

    Unicode → unique reversible code → valid CID (Identity-H)
    → nonzero in-range GID (/CIDToGIDMap, incl. spec-implicit Identity)
    → glyph present in the embedded subset → advance provable (/W, /DW)
    → equal advance: Tier 0 hex-Tj transplant
    → unequal advance: Tier 1 kern-compensated TJ transplant
    → scratch verify → live commit → save/reopen verify

Every fixture is synthetic (``test_scripts/type0_fixture_builder.py`` —
plan §10 data policy).  RED STATUS (2026-08-13): every test below is
expected to fail against current HEAD — today ``bind_source_text`` refuses
CJK targets at the latin-1 leg (``undecodable_target``) before any Type0
gate can run — with two deliberate exception groups, marked ``PIN`` in
their docstrings (P0-A precedent of red+pin mixes):

- the replay-budget pin (P0-A guard must keep firing for Type0 pages), and
- the fixture-sanity tests, which test the BUILDER, not the feature, so a
  red failure elsewhere is provably "feature missing", never "fixture
  broken".

The ``type0_*`` reason-code constants below ARE the P0-D contract: one
stable code per independent gate, asserted verbatim so the coverage funnel
can attribute losses to the exact layer (ToUnicode / CMap / CIDToGID /
glyph repertoire / width) and so a mutation deleting one gate cannot hide
behind a neighbour's code.  The implementation must adopt these codes.

The matrix was adversarially hardened before commit (2-agent Attack →
Verify, workflow ``wf_a084d864-566``, 7/7 findings confirmed): the GID
stage split into three codes, present-but-unparseable and ligature
ToUnicode shapes and the unmapped-replacement shape gained their own codes
and fixtures, the spec-default-DW positive and the two prepare→mutate→
commit staleness pins were added, and the fail-closed zero-mutation oracle
widened from one content stream to the whole object table.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    is_real_fallback_commit,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.patch import apply_patchset, build_reversal_patchset  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402

import model.text_commit.engine as engine_module  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    CJK_TEXT,
    REPLACEMENT_EQUAL_ADVANCE,
    REPLACEMENT_SHORTER,
    TAIL_TEXT,
    Type0Fixture,
    build_identity_h_fixture,
    cid_for,
    default_tounicode_mappings,
    document_object_snapshot,
    fontfile2_xref,
    identity_cidtogid_bytes,
    indirect_w_xref,
    inline_descendant,
    render_cid_ink,
    set_cidtogid_dangling,
    set_cidtogid_name,
    set_cidtogid_stream,
    set_descendant_subtype,
    set_dw,
    set_encoding_custom_cmap,
    set_encoding_name,
    set_w_array,
    strip_tounicode,
    unembed_font,
    validate_fixture,
    w_literal_for,
    write_bfrange_tounicode,
    write_minimal_tounicode,
    write_tounicode_cmap,
)

# --------------------------------------------------------------------------
# P0-D stable reason codes — THE contract these red tests pin.  One code per
# independent gate; the implementation must emit them verbatim.
# --------------------------------------------------------------------------
TYPE0_ENCODING_UNSUPPORTED = "type0_encoding_unsupported"
TYPE0_DESCENDANT_UNSUPPORTED = "type0_descendant_unsupported"
TYPE0_FONT_NOT_EMBEDDED = "type0_font_not_embedded"
TYPE0_TOUNICODE_MISSING = "type0_tounicode_missing"
TYPE0_TOUNICODE_UNPARSEABLE = "type0_tounicode_unparseable"
TYPE0_TOUNICODE_MULTICHAR = "type0_tounicode_multichar"
TYPE0_TOUNICODE_AMBIGUOUS = "type0_tounicode_ambiguous"
TYPE0_UNICODE_UNMAPPED = "type0_unicode_unmapped"
TYPE0_SOURCE_BYTES_NOT_REPRODUCED = "type0_source_bytes_not_reproduced"
TYPE0_CIDTOGID_UNREADABLE = "type0_cidtogid_unreadable"
TYPE0_CID_OUT_OF_MAP_RANGE = "type0_cid_out_of_map_range"
# The GID resolution stage keeps THREE distinct codes (adversarial round
# wf_a084d864-566, GLYPH-CODE-COLLAPSE): the map resolving to .notdef, the
# map resolving beyond the embedded program, and the subset lacking the
# outline are separate gates — Droid Sans Fallback's .notdef draws no ink,
# so an ink-probe-only implementation would otherwise satisfy all three
# fixtures with the explicit GID checks deleted.
TYPE0_GID_ZERO = "type0_gid_zero"
TYPE0_GID_BEYOND_GLYPH_COUNT = "type0_gid_beyond_glyph_count"
TYPE0_GLYPH_MISSING = "type0_glyph_missing"
TYPE0_WIDTH_UNPROVABLE = "type0_width_unprovable"

_ALL_TYPE0_CODES = frozenset(
    {
        TYPE0_ENCODING_UNSUPPORTED,
        TYPE0_DESCENDANT_UNSUPPORTED,
        TYPE0_FONT_NOT_EMBEDDED,
        TYPE0_TOUNICODE_MISSING,
        TYPE0_TOUNICODE_UNPARSEABLE,
        TYPE0_TOUNICODE_MULTICHAR,
        TYPE0_TOUNICODE_AMBIGUOUS,
        TYPE0_UNICODE_UNMAPPED,
        TYPE0_SOURCE_BYTES_NOT_REPRODUCED,
        TYPE0_CIDTOGID_UNREADABLE,
        TYPE0_CID_OUT_OF_MAP_RANGE,
        TYPE0_GID_ZERO,
        TYPE0_GID_BEYOND_GLYPH_COUNT,
        TYPE0_GLYPH_MISSING,
        TYPE0_WIDTH_UNPROVABLE,
    }
)


def _engine(fixture: Type0Fixture, max_tier: int = 1) -> TieredCommitEngine:
    return TieredCommitEngine(fixture.doc, max_tier=max_tier)


def _prepare(
    engine: TieredCommitEngine, fixture: Type0Fixture, replacement: str
) -> PreparedEdit | PlanRejection:
    return engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=replacement,
        expected_origin=None,
    )


def _commit_committed(
    fixture: Type0Fixture, replacement: str, max_tier: int = 1
):
    """Prepare + commit; assert a clean high-fidelity COMMITTED outcome."""
    engine = _engine(fixture, max_tier=max_tier)
    prepared = _prepare(engine, fixture, replacement)
    assert isinstance(prepared, PreparedEdit), (
        f"expected a PreparedEdit, got rejection "
        f"{(prepared.reason, prepared.detail)}"
    )
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, (
        outcome.status,
        outcome.reason,
        outcome.detail,
    )
    return prepared, outcome


def _assert_fail_closed(
    fixture: Type0Fixture,
    replacement: str,
    expected_reason: str,
    max_tier: int = 1,
) -> PlanRejection:
    """Prepare must reject with ``expected_reason`` and mutate NOTHING.

    Zero-mutation is asserted over every object in the document (the
    Type0 gates read font objects a content-stream comparison cannot
    see — adversarial round wf_a084d864-566, WEAK-ZERO-MUTATION-ORACLE),
    plus the extraction surface.
    """
    before_snapshot = document_object_snapshot(fixture.doc)
    before_text = fixture.page.get_text()
    plan = _prepare(_engine(fixture, max_tier=max_tier), fixture, replacement)
    assert isinstance(plan, PlanRejection), "gate must reject, not prepare"
    assert plan.reason == expected_reason, (plan.reason, plan.detail)
    assert document_object_snapshot(fixture.doc) == before_snapshot, (
        "zero-mutation violated somewhere in the object table"
    )
    assert fixture.page.get_text() == before_text
    return plan


# ==========================================================================
# Fixture sanity (builder tests — these PASS today by design; they exist so
# every red below provably fails on the missing feature, not a broken page)
# ==========================================================================

def test_fixture_sanity_plain_rotated_and_tail() -> None:
    for rotate in (0, 270):
        fixture = build_identity_h_fixture(rotate=rotate, tail_text=TAIL_TEXT)
        validate_fixture(fixture)
        assert fixture.page.rotation == rotate
        pix = fixture.page.get_pixmap(dpi=24)
        assert pix.width > 0 and pix.height > 0
        fixture.doc.close()


def test_fixture_sanity_subset_drops_replacement_glyphs_only() -> None:
    fixture = build_identity_h_fixture(subset=True)
    validate_fixture(fixture)
    # Source glyph retained; replacement glyph genuinely absent from the
    # embedded subset (render-based proof: the subset cmap is stripped, so
    # Unicode-based lookups cannot distinguish the two).
    assert render_cid_ink(fixture, cid_for(CJK_TEXT[0])) > 0
    assert render_cid_ink(fixture, cid_for(REPLACEMENT_EQUAL_ADVANCE[0])) == 0
    fixture.doc.close()


# ==========================================================================
# Positive paths (red: prepare currently rejects at the latin-1 binding leg)
# ==========================================================================

def test_tier0_equal_advance_commits_on_identity_h() -> None:
    fixture = build_identity_h_fixture()
    prepared, outcome = _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    extracted = "".join(fixture.page.get_text().split())
    assert REPLACEMENT_EQUAL_ADVANCE in extracted
    assert CJK_TEXT not in extracted
    fixture.doc.close()


def test_tier1_unequal_advance_commits_compensated_transplant() -> None:
    fixture = build_identity_h_fixture()
    prepared, outcome = _commit_committed(fixture, REPLACEMENT_SHORTER)
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    assert outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    extracted = "".join(fixture.page.get_text().split())
    assert REPLACEMENT_SHORTER in extracted
    fixture.doc.close()


def test_cidtogid_identity_stream_variant_commits() -> None:
    fixture = build_identity_h_fixture()
    set_cidtogid_stream(fixture, identity_cidtogid_bytes(20000))
    _, outcome = _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    fixture.doc.close()


def test_explicit_identity_cidtogid_name_commits() -> None:
    """The census's 6 explicit ``/CIDToGIDMap /Identity`` fonts: the NAME
    form must commit, not just the absent-key implicit default."""
    fixture = build_identity_h_fixture()
    set_cidtogid_name(fixture, "Identity")
    _, outcome = _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    fixture.doc.close()


def test_single_destination_bfrange_tounicode_commits() -> None:
    """Scalar-destination bfrange syntax must be accepted — positive
    coverage must not silently depend on whichever ToUnicode form PyMuPDF
    authors for the base fixture (bfchar)."""
    fixture = build_identity_h_fixture()
    write_bfrange_tounicode(
        fixture,
        default_tounicode_mappings(fixture, extra_text=REPLACEMENT_EQUAL_ADVANCE),
    )
    validate_fixture(fixture)
    _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    fixture.doc.close()


def test_width_proven_from_w_array() -> None:
    fixture = build_identity_h_fixture()
    covered = [cid_for(c) for c in CJK_TEXT + REPLACEMENT_EQUAL_ADVANCE]
    set_w_array(fixture, w_literal_for(sorted(set(covered))))
    _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    fixture.doc.close()


def test_width_of_unlisted_cid_falls_back_to_dw() -> None:
    fixture = build_identity_h_fixture()
    # /W deliberately omits one source CID and one replacement CID; the
    # explicit /DW must prove those advances instead.
    listed = sorted(
        {cid_for(c) for c in CJK_TEXT + REPLACEMENT_EQUAL_ADVANCE}
        - {cid_for(CJK_TEXT[2]), cid_for(REPLACEMENT_EQUAL_ADVANCE[0])}
    )
    set_w_array(fixture, w_literal_for(listed))
    set_dw(fixture, "1000")
    _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    fixture.doc.close()


def test_width_of_unlisted_cid_uses_spec_default_dw_when_absent() -> None:
    """The corpus-DOMINANT width shape (plan §8 finding 2): /W gaps prove
    their advance via the spec default DW=1000 with NO /DW key present —
    first-class, not a fallback (adversarial round wf_a084d864-566,
    DW-DEFAULT-UNPINNED)."""
    fixture = build_identity_h_fixture()
    kind, _ = fixture.doc.xref_get_key(fixture.descendant_xref, "DW")
    assert kind == "null", "base fixture must have NO /DW for this pin"
    listed = sorted(
        {cid_for(c) for c in CJK_TEXT + REPLACEMENT_EQUAL_ADVANCE}
        - {cid_for(CJK_TEXT[2]), cid_for(REPLACEMENT_EQUAL_ADVANCE[0])}
    )
    set_w_array(fixture, w_literal_for(listed))
    _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    fixture.doc.close()


def test_inline_descendant_corpus_shape_commits() -> None:
    """The census-dominant form: descendant CIDFont inline in the array."""
    fixture = build_identity_h_fixture()
    inline_descendant(fixture)
    validate_fixture(fixture)
    _, outcome = _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    fixture.doc.close()


def test_tier0_commits_on_rotate270_page() -> None:
    fixture = build_identity_h_fixture(rotate=270)
    _, outcome = _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    extracted = "".join(fixture.page.get_text().split())
    assert REPLACEMENT_EQUAL_ADVANCE in extracted
    fixture.doc.close()


def test_tier1_commits_on_rotate270_page() -> None:
    fixture = build_identity_h_fixture(rotate=270)
    prepared, _ = _commit_committed(fixture, REPLACEMENT_SHORTER)
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    fixture.doc.close()


# ==========================================================================
# Fail-closed gates (red: each must reject with ITS OWN stable code; today
# all of them surface the pre-P0-D ``undecodable_target`` instead)
# ==========================================================================

def test_missing_tounicode_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    strip_tounicode(fixture)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_TOUNICODE_MISSING
    )
    fixture.doc.close()


def test_ambiguous_reverse_mapping_fails_closed() -> None:
    """A replacement char whose Unicode maps to TWO CIDs must refuse."""
    fixture = build_identity_h_fixture()
    mappings = default_tounicode_mappings(
        fixture, extra_text=REPLACEMENT_EQUAL_ADVANCE
    )
    # Second CID claiming the same Unicode as the replacement-only char 再.
    mappings.append((0x0999, REPLACEMENT_EQUAL_ADVANCE[0]))
    write_minimal_tounicode(fixture, mappings)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_TOUNICODE_AMBIGUOUS
    )
    fixture.doc.close()


def test_source_reverse_encode_must_reproduce_source_bytes() -> None:
    """A source char with a competing earlier/lower CID mapping must refuse.

    decode(source bytes) still yields the target text, but no deterministic
    reverse choice can be trusted: the engine must re-encode the bound text
    and compare byte-for-byte against the show operand, and reject when
    they differ.
    """
    fixture = build_identity_h_fixture()
    mappings = [(0x0001, CJK_TEXT[0])]  # fake CID for 你, listed first + lower
    mappings += default_tounicode_mappings(fixture, extra_text=REPLACEMENT_EQUAL_ADVANCE)
    write_minimal_tounicode(fixture, mappings)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_SOURCE_BYTES_NOT_REPRODUCED
    )
    fixture.doc.close()


def test_array_destination_bfrange_tounicode_fails_closed() -> None:
    """Present-but-unparseable ToUnicode must refuse, never guess.

    The array-destination ``bfrange`` form (PDF 32000-1 §9.10.3) is
    spec-legal but outside the v1 reverse-encoding scope; today's
    ``_parse_tounicode`` silently fabricates garbage mappings from it
    (adversarial round wf_a084d864-566, TOUNICODE-UNPARSEABLE-GAP), which
    is exactly what fail-closed forbids.
    """
    fixture = build_identity_h_fixture()
    cid = cid_for(fixture.text[0])
    write_tounicode_cmap(
        fixture,
        "1 beginbfrange\n"
        f"<{cid:04X}> <{cid + 1:04X}> [<4F60> <597D>]\n"
        "endbfrange",
    )
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_TOUNICODE_UNPARSEABLE
    )
    fixture.doc.close()


def test_ligature_multichar_mapping_fails_closed() -> None:
    """One-CID→many-chars is excluded scope and must refuse by code."""
    fixture = build_identity_h_fixture()
    mappings = default_tounicode_mappings(
        fixture, extra_text=REPLACEMENT_EQUAL_ADVANCE
    )
    # The SOURCE cid for 你 now decodes to a two-char cluster.
    mappings[0] = (mappings[0][0], fixture.text[0] + "a")
    write_minimal_tounicode(fixture, mappings)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_TOUNICODE_MULTICHAR
    )
    fixture.doc.close()


def test_replacement_char_absent_from_reverse_map_fails_closed() -> None:
    """The first gate's most basic shape: no CID exists for a replacement
    char at all (distinct from the glyph-repertoire layer)."""
    fixture = build_identity_h_fixture()
    write_minimal_tounicode(fixture, default_tounicode_mappings(fixture))
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_UNICODE_UNMAPPED
    )
    fixture.doc.close()


def test_cidtogid_dangling_ref_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_cidtogid_dangling(fixture)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_CIDTOGID_UNREADABLE
    )
    fixture.doc.close()


def test_cidtogid_odd_length_stream_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_cidtogid_stream(fixture, identity_cidtogid_bytes(20000)[:-1])
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_CIDTOGID_UNREADABLE
    )
    fixture.doc.close()


def test_cid_beyond_map_range_fails_closed() -> None:
    # Map covers CIDs [0, 1000); every fixture CID is far above it.
    fixture = build_identity_h_fixture()
    set_cidtogid_stream(fixture, identity_cidtogid_bytes(1000))
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_CID_OUT_OF_MAP_RANGE
    )
    fixture.doc.close()


def test_replacement_gid_zero_fails_closed() -> None:
    """The MAP saying .notdef is its own gate — never folded into the
    repertoire code (DSF's .notdef draws no ink, so an ink-probe-only
    implementation must not be able to satisfy this fixture)."""
    fixture = build_identity_h_fixture()
    set_cidtogid_stream(
        fixture,
        identity_cidtogid_bytes(
            20000, overrides={cid_for(REPLACEMENT_EQUAL_ADVANCE[0]): 0}
        ),
    )
    _assert_fail_closed(fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_GID_ZERO)
    fixture.doc.close()


def test_gid_beyond_embedded_glyph_count_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_cidtogid_stream(
        fixture,
        identity_cidtogid_bytes(
            20000, overrides={cid_for(REPLACEMENT_EQUAL_ADVANCE[0]): 60000}
        ),
    )
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_GID_BEYOND_GLYPH_COUNT
    )
    fixture.doc.close()


def test_malformed_w_with_unprovable_dw_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_w_array(fixture, "[ 2014 ]")  # cid with no width — structurally broken
    set_dw(fixture, "[ 1 2 ]")  # present but not a number — unprovable
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_WIDTH_UNPROVABLE
    )
    fixture.doc.close()


def test_identity_v_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_encoding_name(fixture, "Identity-V")
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_ENCODING_UNSUPPORTED
    )
    fixture.doc.close()


def test_custom_embedded_cmap_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_encoding_custom_cmap(fixture)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_ENCODING_UNSUPPORTED
    )
    fixture.doc.close()


def test_cidfonttype0_descendant_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    set_descendant_subtype(fixture, "CIDFontType0")
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_DESCENDANT_UNSUPPORTED
    )
    fixture.doc.close()


def test_unembedded_font_program_fails_closed() -> None:
    fixture = build_identity_h_fixture()
    unembed_font(fixture)
    _assert_fail_closed(
        fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_FONT_NOT_EMBEDDED
    )
    fixture.doc.close()


def test_replacement_glyph_missing_from_subset_fails_closed() -> None:
    """The plan §6 shape: the subset simply never embedded 再/見."""
    fixture = build_identity_h_fixture(subset=True)
    _assert_fail_closed(fixture, REPLACEMENT_EQUAL_ADVANCE, TYPE0_GLYPH_MISSING)
    fixture.doc.close()


def test_replay_budget_guard_still_rejects_oversized_type0_page() -> None:
    """PIN (passes today): P0-D must not bypass the P0-A replay budget.

    An oversized Type0 page keeps rejecting with the ORIGINAL budget
    reason — never a ``type0_*`` code, and never a silently-lifted guard.
    """
    fixture = build_identity_h_fixture(pad_stream_to=5 * 1024 * 1024)
    plan = _prepare(_engine(fixture), fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(plan, PlanRejection)
    assert plan.reason == RejectReason.CONTENT_STREAM_TOO_LARGE
    assert plan.reason not in _ALL_TYPE0_CODES
    fixture.doc.close()


# ==========================================================================
# End-to-end contracts (red: they require a commit that cannot happen yet)
# ==========================================================================

def test_preview_candidate_is_the_committed_candidate() -> None:
    fixture = build_identity_h_fixture()
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    assert engine.get_verified_candidate(prepared.token) is prepared
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED
    fixture.doc.close()


def test_following_glyph_origins_unchanged_for_both_tiers() -> None:
    def tail_origins(fixture: Type0Fixture) -> list[tuple[float, float]]:
        origins = []
        for block in fixture.page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    for char in span["chars"]:
                        if char["c"] in TAIL_TEXT:
                            origins.append(
                                (
                                    round(char["origin"][0], 3),
                                    round(char["origin"][1], 3),
                                )
                            )
        return origins

    for replacement in (REPLACEMENT_EQUAL_ADVANCE, REPLACEMENT_SHORTER):
        fixture = build_identity_h_fixture(tail_text=TAIL_TEXT)
        before = tail_origins(fixture)
        assert len(before) == len(TAIL_TEXT)
        _commit_committed(fixture, replacement)
        assert tail_origins(fixture) == before, (
            f"tail glyphs moved after committing {replacement!r}"
        )
        fixture.doc.close()


def test_stream_bytes_outside_splice_range_unchanged() -> None:
    fixture = build_identity_h_fixture(tail_text=TAIL_TEXT)
    before = fixture.content_bytes()
    operand = f"<{fixture.encoded.hex().upper()}>".encode("ascii")
    start = before.index(operand)
    end = start + len(operand)
    _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    after = fixture.content_bytes()
    assert after[:start] == before[:start], "bytes before the splice changed"
    tail_len = len(before) - end
    assert after[len(after) - tail_len :] == before[end:], (
        "bytes after the splice changed"
    )
    fixture.doc.close()


def test_save_reopen_preserves_edit_extraction_and_font() -> None:
    fixture = build_identity_h_fixture(tail_text=TAIL_TEXT)
    _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    data = fixture.doc.tobytes()
    fixture.doc.close()
    reopened = fitz.open(stream=data, filetype="pdf")
    page = reopened[0]
    extracted = "".join(page.get_text().split())
    assert REPLACEMENT_EQUAL_ADVANCE in extracted
    assert TAIL_TEXT in extracted
    assert CJK_TEXT not in extracted
    entry = page.get_fonts(full=True)[0]
    assert entry[2] == "Type0"
    kind, value = reopened.xref_get_key(entry[0], "Encoding")
    assert (kind, value) == ("name", "/Identity-H")
    reopened.close()


def test_undo_restores_exact_bytes_and_commit_is_not_a_fallback() -> None:
    fixture = build_identity_h_fixture()
    page = fixture.page
    pre_streams = read_page_streams(fixture.doc, page)
    pre_fingerprint = page_fingerprint(fixture.doc, page)
    before = fixture.content_bytes()

    _, outcome = _commit_committed(fixture, REPLACEMENT_EQUAL_ADVANCE)
    # A clean Tier 0/1 CID commit is HIGH fidelity: it must never look like
    # a legacy fallback, so P0-C consent is never armed for it and a redo
    # can never re-prompt.
    assert outcome.status is CommitStatus.COMMITTED
    assert tuple(outcome.fallback_chain) == ()
    assert not is_real_fallback_commit(outcome)

    pair = build_reversal_patchset(fixture.doc, page, pre_streams, pre_fingerprint)
    assert pair is not None
    _, inverse = pair
    apply_patchset(fixture.doc, fixture.page, inverse)
    assert fixture.content_bytes() == before, "undo must be byte-exact"
    fixture.doc.close()


def test_commit_is_stale_after_descendant_w_mutation() -> None:
    """Mutating Type0-load-bearing evidence between prepare and commit
    must invalidate the plan — the fingerprint's dependency enumeration
    must follow /DescendantFonts (adversarial round wf_a084d864-566,
    TYPE0-STALENESS-UNPINNED: today it is simple-font-only and blind to
    the descendant's /W)."""
    fixture = build_identity_h_fixture()
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    before = fixture.content_bytes()
    set_w_array(fixture, "[ 1 [ 500 ] ]")
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN, (
        outcome.status,
        outcome.reason,
    )
    assert fixture.content_bytes() == before, "stale commit must mutate nothing"
    fixture.doc.close()


def test_commit_is_stale_after_tounicode_mutation() -> None:
    fixture = build_identity_h_fixture()
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    before = fixture.content_bytes()
    write_minimal_tounicode(
        fixture,
        default_tounicode_mappings(fixture, extra_text=REPLACEMENT_EQUAL_ADVANCE),
    )
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN, (
        outcome.status,
        outcome.reason,
    )
    assert fixture.content_bytes() == before
    fixture.doc.close()


def test_commit_is_stale_after_cidtogid_stream_mutation() -> None:
    """Every evidence object the codec reads must be staleness-gated —
    the CIDToGIDMap stream included, not only /W and ToUnicode."""
    fixture = build_identity_h_fixture()
    set_cidtogid_stream(fixture, identity_cidtogid_bytes(20000))
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    before = fixture.content_bytes()
    set_cidtogid_stream(fixture, identity_cidtogid_bytes(1000))
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN, (
        outcome.status,
        outcome.reason,
    )
    assert fixture.content_bytes() == before
    fixture.doc.close()


def test_commit_is_stale_after_fontfile2_stream_mutation() -> None:
    """The glyph program itself is width/glyph evidence — swapping the
    embedded FontFile2 bytes after prepare must invalidate the plan."""
    fixture = build_identity_h_fixture()
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    before = fixture.content_bytes()
    program_xref = fontfile2_xref(fixture)
    original = fixture.doc.xref_stream(program_xref) or b""
    fixture.doc.update_stream(program_xref, original + b"\x00")
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN, (
        outcome.status,
        outcome.reason,
    )
    assert fixture.content_bytes() == before
    fixture.doc.close()


def test_commit_is_stale_after_inline_descendant_indirect_w_mutation() -> None:
    """The corpus-dominant inline-descendant form keeps /W as an indirect
    object INSIDE the inline array — mutating that target between prepare
    and commit must invalidate the plan even though the font dict and the
    inline array text are byte-identical."""
    fixture = build_identity_h_fixture()
    inline_descendant(fixture)
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    before = fixture.content_bytes()
    fixture.doc.update_object(indirect_w_xref(fixture), "[ 1 [ 500 ] ]")
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN, (
        outcome.status,
        outcome.reason,
    )
    assert fixture.content_bytes() == before
    fixture.doc.close()


def test_commit_stage_verifier_failure_rolls_back_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from model.text_commit.verify import VerificationFailure

    fixture = build_identity_h_fixture()
    engine = _engine(fixture)
    prepared = _prepare(engine, fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(prepared, PreparedEdit)
    before = fixture.content_bytes()
    before_text = fixture.page.get_text()

    def _always_refute(*args: object, **kwargs: object) -> VerificationFailure:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "forced by test"
        )

    monkeypatch.setattr(engine_module, "verify_tier0_commit", _always_refute)
    monkeypatch.setattr(engine_module, "verify_tier1_commit", _always_refute)
    outcome = engine.commit(prepared)
    assert outcome.status is not CommitStatus.COMMITTED
    assert fixture.content_bytes() == before, "failed commit must revert bytes"
    assert fixture.page.get_text() == before_text
    fixture.doc.close()


def test_type0_rejections_and_outcomes_are_code_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Privacy: no document text and no font name in any observable surface."""
    fixture = build_identity_h_fixture()
    basefont = fixture.page.get_fonts(full=True)[0][3]
    strip_tounicode(fixture)
    with caplog.at_level(logging.DEBUG):
        plan = _prepare(_engine(fixture), fixture, REPLACEMENT_EQUAL_ADVANCE)
    assert isinstance(plan, PlanRejection)
    assert plan.reason == TYPE0_TOUNICODE_MISSING

    forbidden = [CJK_TEXT, REPLACEMENT_EQUAL_ADVANCE, basefont]
    surfaces = [plan.detail or "", plan.reason]
    surfaces += [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("model.text_commit")
    ]
    for surface in surfaces:
        for secret in forbidden:
            assert secret not in surface, (
                "document text / font name leaked into an observable surface"
            )
    fixture.doc.close()
