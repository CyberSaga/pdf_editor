"""Red-light tests for Task 12 Step 7 cleanup — ``CommitOutcome.decision_chain``.

Today a successful tiered commit records ``fallback_chain=()`` (correct — a
successful escalation is not a fidelity degrade) but that throws away HOW the
tier was chosen: a Tier 1 commit is only ever reached by a Tier 0
``advance_mismatch`` refusal (``plan._TIER1_ESCALATION_REASONS``), yet the
outcome stored in history is indistinguishable from a world where Tier 1 was
tried first.  The cleanup contract pinned here:

1. ``decision_chain`` on ``CommitOutcome`` records the tier decision trail for
   successful tiered commits — ``("tier0:committed",)`` for a direct Tier 0
   commit, ``("tier0:rejected:advance_mismatch", "tier1:committed")`` for an
   escalated Tier 1 commit.
2. ``fallback_chain`` stays ``()`` on those same successful commits (reserved
   for true degrades) — the new field must not leak into it.
3. Legacy outcomes and engine failure outcomes keep ``decision_chain == ()``:
   failure attribution stays where it already lives (``fallback_chain``), and
   the shipped-default legacy path is untouched.
4. The P0-C degrade gate (``is_real_fallback_commit``) keeps reading
   ``fallback_chain`` only — a populated ``decision_chain`` never makes an
   outcome notifiable.

Chain entries are reason codes only — never document text, font names, file
names, or paths (data policy, plan §10).  All fixtures synthetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import (  # noqa: E402
    CommitOutcome,
    CommitStatus,
    CommitTier,
    is_real_fallback_commit,
    legacy_commit_outcome,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PreparedEdit  # noqa: E402

# Independent literal constants (house style): the pins must break if the
# production spelling drifts, so none of these are imported from the enum.
TIER0_COMMITTED_CHAIN = ("tier0:committed",)
TIER1_ESCALATED_CHAIN = ("tier0:rejected:advance_mismatch", "tier1:committed")

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica: stays on Tier 0

GROWTH_TARGET = "iii"
GROWTH_REPLACEMENT = "MMM"  # helv M=833 vs i=222: real growth, Tier 1 territory
TAIL_FULL = " " * 12 + "tail"
WORLD = "world"

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


# ---------------------------------------------------------------- fixtures


def _stream_doc(stream: bytes) -> fitz.Document:
    """One page whose only content is ``stream``, with /F1 = Helvetica."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _tier0_doc() -> fitz.Document:
    return _stream_doc(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (Downstream line stays) Tj ET"
    )


def _escalation_doc() -> fitz.Document:
    """The Slice 1 composite shape: ``iii`` followed on the same baseline by a
    same-font successor whose origin consumes ``iii``'s advance (the
    compensation oracle), so a growing replacement fails Tier 0 with
    ``advance_mismatch`` and escalates to the kern-compensated transplant."""
    return _stream_doc(
        b"BT /F1 12 Tf 72 700 Td (" + GROWTH_TARGET.encode() + b") Tj "
        b"/F1 9 Tf (" + TAIL_FULL.encode() + b") Tj "
        b"0 -20 Td /F1 12 Tf (" + WORLD.encode() + b") Tj ET"
    )


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _engine_commit(
    doc: fitz.Document, target: str, replacement: str, *, max_tier: int
) -> tuple[TieredCommitEngine, PreparedEdit, CommitOutcome]:
    page = doc[0]
    span = _span(page, target)
    engine = TieredCommitEngine(doc, max_tier=max_tier)
    prepared = engine.prepare(
        page,
        target_text=target,
        replacement_text=replacement,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared, PreparedEdit), prepared
    outcome = engine.commit(prepared)
    return engine, prepared, outcome


# -------------------------------------------------------------------- pins


def test_tier0_commit_records_decision_chain():
    doc = _tier0_doc()
    try:
        _engine, prepared, outcome = _engine_commit(
            doc, TARGET, REPLACEMENT, max_tier=0
        )
        assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert outcome.status is CommitStatus.COMMITTED
        assert outcome.decision_chain == TIER0_COMMITTED_CHAIN
        # Contract 2: the trail must not leak into the degrade channel.
        assert outcome.fallback_chain == ()
    finally:
        doc.close()


def test_escalated_tier1_commit_records_full_decision_chain():
    doc = _escalation_doc()
    try:
        _engine, prepared, outcome = _engine_commit(
            doc, GROWTH_TARGET, GROWTH_REPLACEMENT, max_tier=1
        )
        # Sanity: this really is the escalated path, not Tier 0 accepting.
        assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        assert outcome.status is CommitStatus.COMMITTED
        assert outcome.decision_chain == TIER1_ESCALATED_CHAIN
        assert outcome.fallback_chain == ()
    finally:
        doc.close()


def test_stale_commit_failure_leaves_decision_chain_empty():
    """Failure attribution stays in ``fallback_chain`` exactly as before;
    ``decision_chain`` is a successful-commit trail, empty on rejection."""
    doc = _tier0_doc()
    try:
        page = doc[0]
        span = _span(page, TARGET)
        engine = TieredCommitEngine(doc, max_tier=0)
        prepared = engine.prepare(
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=tuple(span["origin"]),
            target_bbox=tuple(span["bbox"]),
        )
        assert isinstance(prepared, PreparedEdit), prepared
        # Mutate the live stream after prepare: the commit must go stale.
        content_xref = page.get_contents()[0]
        doc.update_stream(
            content_xref, doc.xref_stream(content_xref) + b" 1 0 0 1 0 0 cm "
        )
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.STALE_PLAN
        assert outcome.decision_chain == ()
        assert outcome.fallback_chain != ()  # existing attribution untouched
    finally:
        doc.close()


def test_legacy_outcome_keeps_decision_chain_empty():
    outcome = legacy_commit_outcome()
    assert outcome.decision_chain == ()
    assert outcome.fallback_chain == ("legacy",)  # unchanged baseline


def test_degrade_gate_reads_fallback_chain_not_decision_chain():
    """P0-C isolation: a populated decision_chain must never flip
    ``is_real_fallback_commit`` — the two chains answer different questions."""
    baseline = CommitOutcome(
        status=CommitStatus.DEGRADED_COMMITTED,
        tier=CommitTier.TIER2_LEGACY,
        fallback_chain=("legacy",),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=None,
        allows_external_reflow=True,
        decision_chain=TIER1_ESCALATED_CHAIN,
    )
    assert is_real_fallback_commit(baseline) is False

    real_degrade = CommitOutcome(
        status=CommitStatus.DEGRADED_COMMITTED,
        tier=CommitTier.TIER2_LEGACY,
        fallback_chain=("tier0:advance_mismatch", "legacy"),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=None,
        allows_external_reflow=True,
        decision_chain=(),
    )
    assert is_real_fallback_commit(real_degrade) is True
