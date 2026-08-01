"""Direct tests for ``_tier0_target_from_resolve`` (plan Task 11 prereq D5).

This stage sits *above* the Tier 0 planner: it turns the editor's resolved
member spans into the ``(text, origin, bbox)`` triple that
``bind_source_text`` then matches byte-for-byte against the content stream
(``inspect.py:233``).  Until this module existed it had **zero** direct
tests — the only test contact stubbed its wrapper out
(``test_text_commit_preview_contract.py:508``) — so every failure here was
invisible to both the suite and the corpus audits, which classify *shows*
rather than *edits*.

Two distinct families live here, and they are validated differently:

* **Shape rules** (``test_shape_*``) characterize behaviour that is already
  correct: which member sets map to a whole-operator patch and which must
  return ``None``.  They pass on arrival, so — following the Task 10a
  precedent — each is validated by *mutation* instead of by a Red run: the
  guard it claims to pin is neutered and the test must fail.  The
  mutation-sensitivity result for each is recorded in TODOS.md.
* **The reconstruction contract** (``test_reconstruction_*``) pins the
  cross-module demand D5 names: the ``" ".join`` at ``pdf_text_edit.py:1223``
  must produce something ``bind_source_text`` can match, *or* the refusal
  must say that the engine's own reconstruction is the suspect.  Word runs
  are ``.strip()``-ed when parsed (``text_block_parsing.py:_finalize``), so
  source whitespace is destroyed and cannot be rejoined; the Red case is a
  multi-space source that silently returned ``NO_MATCH``, indistinguishable
  from a target that is genuinely absent from the page.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model import pdf_text_edit  # noqa: E402
from model.pdf_text_edit import (  # noqa: E402
    _attempt_tiered_commit,
    _classify_tier0_candidate,
    _EditTextResolveResult,
    _tier0_target_from_resolve,
)
from model.text_block import TextBlockManager  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import SourceSpanBinding, bind_source_text  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402

# Helvetica digits share a width, so this pair is advance-neutral and cannot
# fail Tier 0 for a reason unrelated to the stage under test.
SINGLE_SPACE = "Price 2024"
REPLACEMENT = "Price 2025"


def _line_doc(*lines: str) -> fitz.Document:
    """One page, one ``Tj`` per line, /F1 = Helvetica at a known origin.

    Built by xref surgery rather than ``insert_text`` so the *exact* bytes
    inside the string operand are controlled by the test — the whole point
    of the reconstruction cases is that source whitespace survives into the
    content stream verbatim.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    ops = []
    for idx, text in enumerate(lines):
        escaped = (
            text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        )
        ops.append(f"BT /F1 12 Tf 72 {700 - idx * 40} Td ({escaped}) Tj ET")
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, "\n".join(ops).encode("latin-1"))
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    # Round-trip: MuPDF's text extractor needs a fully serialized file before
    # the rawdict parse that produces the word runs will see this page.
    reopened = fitz.open("pdf", doc.tobytes())
    doc.close()
    return reopened


class _StubModel:
    """The three attributes this stage touches, over a real document.

    Deliberately not a ``PDFModel``: constructing one drags in session and
    index lifecycle that would make these tests about something else.  The
    *document* and the *block index* are real (CLAUDE.md 5.2 — do not mock
    the PyMuPDF document), only the model shell is stubbed.
    """

    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc
        self.password = None
        self.pending_edits: list[dict] = []
        self.text_target_mode = "run"
        self.block_manager = TextBlockManager()
        self.block_manager.build_index(doc)


def _resolve_result(model: _StubModel, member_span_ids: set[str]):
    """A resolve result carrying exactly ``member_span_ids`` as the target.

    Every field ``_tier0_target_from_resolve`` reads is real (the runs come
    from the block index over the real page); the rest of the dataclass is
    filled with values this stage never inspects.
    """
    runs = model.block_manager.get_runs(0)
    members = [r for r in runs if r.span_id in member_span_ids]
    blocks = model.block_manager.get_blocks(0)
    return _EditTextResolveResult(
        target_span=members[0] if members else (runs[0] if runs else None),
        resolved_target_span_id=next(iter(member_span_ids), ""),
        effective_target_mode="run",
        target_member_span_ids=set(member_span_ids),
        overlap_cluster=list(runs),
        protected_spans=[],
        target=blocks[0] if blocks else None,
        resolved_font="helv",
        rotation=0,
        is_vertical=False,
        insert_rotate=0,
        redact_rect=fitz.Rect(0, 0, 1, 1),
    )


def _line_group(model: _StubModel, index: int) -> list:
    """Runs of the ``index``-th distinct ``(block_idx, line_idx)`` line.

    Grouping on the pair rather than on ``line_idx`` alone matters: two
    ``BT``/``ET`` pairs at different y become two *blocks* that each carry
    ``line_idx == 0``, so filtering on ``line_idx`` would silently return an
    empty second line and make the multi-line test vacuous.
    """
    runs = model.block_manager.get_runs(0)
    keys: list[tuple[int, int]] = []
    for run in runs:
        key = (run.block_idx, run.line_idx)
        if key not in keys:
            keys.append(key)
    wanted = keys[index]
    return [r for r in runs if (r.block_idx, r.line_idx) == wanted]


# --------------------------------------------------------------------------
# Shape rules — characterization, validated by mutation (see module docstring)
# --------------------------------------------------------------------------


def test_shape_single_run_target_resolves() -> None:
    """One member run is a whole-word Tj target: positive control."""
    doc = _line_doc("Total")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1, "fixture must produce exactly one word run"
        result = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id})
        )
        assert result is not None
        text, origin, bbox = result.text, result.origin, result.bbox
        assert text == "Total"
        # One run means nothing was joined, so the text is a quotation of
        # the source rather than a reconstruction.
        assert result.joined_runs == 1
        assert result.whitespace_reconstructed is False
        # The triple is not merely non-None: origin must be the run's own
        # baseline origin and the bbox must cover it, or the planner's
        # evidence checks would be fed values this stage invented.
        assert origin == pytest.approx(
            (float(runs[0].origin.x), float(runs[0].origin.y))
        )
        assert bbox[0] <= origin[0] + 0.01 and bbox[2] >= bbox[0]
    finally:
        doc.close()


def test_shape_full_line_member_set_resolves() -> None:
    """A member set covering every run of one line joins in x order."""
    doc = _line_doc(SINGLE_SPACE)
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 2, "fixture must split into two word runs"
        result = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert result is not None
        text, origin = result.text, result.origin
        assert text == SINGLE_SPACE
        assert result.joined_runs == 2
        assert result.whitespace_reconstructed is True
        # Origin comes from the leftmost run, not from members[0] ordering.
        leftmost = min(runs, key=lambda r: float(r.origin.x))
        assert origin == pytest.approx(
            (float(leftmost.origin.x), float(leftmost.origin.y))
        )
    finally:
        doc.close()


def test_shape_partial_line_selection_is_refused() -> None:
    """A strict subset of a line's runs is a substring patch: unsupported.

    Pins ``pdf_text_edit.py:1214-1221``.  The positive control in the same
    test proves the fixture is otherwise resolvable, so a failure here
    cannot be blamed on the document.
    """
    doc = _line_doc("Price is 100")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        # Three runs so a two-run selection is a genuine strict subset: with
        # only two runs a one-run selection takes the single-member branch
        # instead and never reaches the guard under test.
        assert len(runs) == 3, "fixture must split into three word runs"
        subset = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id, runs[1].span_id})
        )
        assert subset is None, "partial line selection must not resolve"
        # Positive control: the full set on the same page does resolve.
        assert (
            _tier0_target_from_resolve(
                model, 0, _resolve_result(model, {r.span_id for r in runs})
            )
            is not None
        )
    finally:
        doc.close()


def test_shape_multi_line_members_are_refused() -> None:
    """Members spanning two lines need paragraph re-layout (Tier 1+).

    Pins the *behaviour*, not the explicit guard.  Mutation testing found
    that deleting the ``any(...)`` line-identity guard leaves this (and
    every other) test green: ``span_id`` encodes page/block/line in both
    parsers (``text_block_parsing.py`` ``_parse_runs_from_raw_line`` and
    ``_parse_spans``), so a member on another line always carries an id
    that cannot appear in ``first``'s ``line_run_ids`` — the full-line
    set-equality check below it refuses the same input.  With one member
    the ``any(...)`` compares ``first`` to itself and is always ``False``.
    The guard is therefore redundant defence-in-depth, and no test can
    make it SENSITIVE without also deleting the check that subsumes it.
    Recorded rather than papered over; see TODOS.md.
    """
    doc = _line_doc("Alpha", "Beta")
    try:
        model = _StubModel(doc)
        line0 = _line_group(model, 0)
        line1 = _line_group(model, 1)
        # The two Tj ops must land in distinct lines for this fixture to
        # exercise the line-identity guard rather than the full-line rule.
        assert line0 and line1, "fixture must produce runs on two lines"
        assert line0[0].line_idx != line1[0].line_idx or (
            line0[0].block_idx != line1[0].block_idx
        )
        crossing = {line0[0].span_id, line1[0].span_id}
        assert _tier0_target_from_resolve(model, 0, _resolve_result(model, crossing)) is None
        # Positive control: either line alone resolves.
        assert (
            _tier0_target_from_resolve(
                model, 0, _resolve_result(model, {r.span_id for r in line0})
            )
            is not None
        )
    finally:
        doc.close()


def test_shape_empty_member_set_is_refused() -> None:
    """No members at all resolves to nothing. Pins ``pdf_text_edit.py:1204``."""
    doc = _line_doc(SINGLE_SPACE)
    try:
        model = _StubModel(doc)
        assert _tier0_target_from_resolve(model, 0, _resolve_result(model, set())) is None
    finally:
        doc.close()


# --------------------------------------------------------------------------
# MULTI_SPAN_TARGET — first assertions anywhere for this reason code
# --------------------------------------------------------------------------


def test_classify_emits_multi_span_target_for_unresolvable_shape() -> None:
    """``_classify_tier0_candidate`` maps a ``None`` target to a reason.

    Pins ``pdf_text_edit.py:1293-1298``; reason *and* detail substring,
    since a bare reason check would survive the guard returning a
    neighbouring rejection.
    """
    doc = _line_doc("Alpha", "Beta")
    try:
        model = _StubModel(doc)
        crossing = {
            _line_group(model, 0)[0].span_id,
            _line_group(model, 1)[0].span_id,
        }
        result = _classify_tier0_candidate(
            model,
            doc[0],
            0,
            REPLACEMENT,
            _resolve_result(model, crossing),
            None,
            None,
            DocumentFontRegistry(doc),
        )
        assert isinstance(result, PlanRejection)
        assert result.reason == RejectReason.MULTI_SPAN_TARGET
        assert "one whole line or one whole word run" in result.detail
    finally:
        doc.close()


def test_tiered_commit_refuses_unresolvable_shape_without_mutating() -> None:
    """``_attempt_tiered_commit`` refuses, and touches nothing.

    Pins ``pdf_text_edit.py:1362-1364``.  The mutation assertion matters
    more than the reason: this is the live-document path, so a refusal
    that had already written to the page would be a far worse defect than
    a mislabelled one.
    """
    doc = _line_doc("Alpha", "Beta")
    try:
        model = _StubModel(doc)
        before = doc.xref_length()
        stream_before = doc.xref_stream(doc[0].get_contents()[0])
        crossing = {
            _line_group(model, 0)[0].span_id,
            _line_group(model, 1)[0].span_id,
        }
        outcome, reason = _attempt_tiered_commit(
            model, doc[0], 0, REPLACEMENT, _resolve_result(model, crossing), None, None
        )
        assert outcome is None
        assert reason == RejectReason.MULTI_SPAN_TARGET
        assert doc.xref_length() == before
        assert doc.xref_stream(doc[0].get_contents()[0]) == stream_before
    finally:
        doc.close()


# --------------------------------------------------------------------------
# Reconstruction contract — the D5 Red case
# --------------------------------------------------------------------------


def test_reconstruction_single_space_target_binds() -> None:
    """Positive control: when the source really has one space, it binds.

    Without this, the multi-space test below could pass for the trivial
    reason that nothing on this fixture ever binds.
    """
    doc = _line_doc(SINGLE_SPACE)
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        result = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert result is not None
        assert result[0] == SINGLE_SPACE
        binding = bind_source_text(
            doc, doc[0], target_text=result[0], expected_origin=None
        )
        assert isinstance(binding, SourceSpanBinding), (
            f"single-space target should bind, got "
            f"{getattr(binding, 'reason', type(binding).__name__)}"
        )
        # It bound to the operator that actually carries the source bytes.
        assert binding.show.decoded_bytes == SINGLE_SPACE.encode("latin-1")
    finally:
        doc.close()


def test_reconstruction_failure_is_distinguishable_from_absent_target() -> None:
    """A run-joined target that cannot bind must not claim a plain NO_MATCH.

    ``_finalize`` (``text_block_parsing.py``) strips each word run, so the
    ``" ".join`` at ``pdf_text_edit.py:1223`` collapses ``"Price is  100"``
    to ``"Price is 100"`` and ``bind_source_text``'s byte-equality test at
    ``inspect.py:233`` fails.  Before the fix that surfaced as
    ``NO_MATCH`` — byte-identical to the refusal for text that is genuinely
    not on the page, which is why this whole failure class was invisible to
    every corpus number.  The engine's own lossy reconstruction must be
    named as the suspect instead.
    """
    doc = _line_doc("Price is  100")  # two spaces in the source operand
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 3, "fixture must split into three word runs"
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        # Precondition: the reconstruction really did lose the second space.
        assert target[0] == "Price is 100"
        assert bind_source_text(
            doc, doc[0], target_text=target[0], expected_origin=None
        ).reason == RejectReason.NO_MATCH

        result = _classify_tier0_candidate(
            model,
            doc[0],
            0,
            "Price is  200",
            _resolve_result(model, {r.span_id for r in runs}),
            None,
            None,
            DocumentFontRegistry(doc),
        )
        assert isinstance(result, PlanRejection)
        assert result.reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED, (
            "a target assembled by joining word runs must not report the same "
            "reason as a target that is genuinely absent from the page"
        )
        assert "whitespace" in result.detail
    finally:
        doc.close()


def test_reconstruction_absent_target_still_reports_plain_no_match() -> None:
    """The discriminator must not fire for a single-run (unjoined) target.

    The other half of the distinction: with no join applied there is no
    reconstruction to blame, so the refusal must stay ``NO_MATCH``.  Without
    this the fix could pass its Red test by relabelling *every* miss.

    The fixture is a real, still-open gap rather than a contrived one: a
    source operand padded with spaces (``"  Total  "``) parses to the single
    stripped run ``"Total"``, so the target genuinely fails byte-equality at
    ``inspect.py:233`` even though only *one* run was involved.  That keeps
    the assertion unconditional — the planner is guaranteed to reach a
    ``NO_MATCH`` rejection here, so this test cannot go vacuous the way a
    fixture whose target binds successfully would.
    """
    doc = _line_doc("  Total  ")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1, "padded source must still parse to one run"
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id})
        )
        assert target is not None
        assert target.text == "Total"  # padding stripped by _finalize
        assert target.joined_runs == 1
        assert target.whitespace_reconstructed is False

        result = _classify_tier0_candidate(
            model,
            doc[0],
            0,
            "Totaz",  # differs from the target, so NO_CHANGE is not hit first
            _resolve_result(model, {runs[0].span_id}),
            None,
            None,
            DocumentFontRegistry(doc),
        )
        assert isinstance(result, PlanRejection)
        assert result.reason == RejectReason.NO_MATCH
        assert result.reason != RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
    finally:
        doc.close()


def test_reconstruction_reason_code_is_stable() -> None:
    """The reason string is a telemetry contract (dto.py docstring)."""
    assert (
        RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
        == "target_reconstruction_unverified"
    )
    assert pdf_text_edit is not None
