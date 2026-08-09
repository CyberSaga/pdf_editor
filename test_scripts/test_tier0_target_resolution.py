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
    _Tier0Target,
    _tier0_target_from_resolve,
)
from model.text_block import TextBlockManager  # noqa: E402
from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import SourceSpanBinding, bind_source_text  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402

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


def _ops_doc(ops: str) -> fitz.Document:
    """Same xref-surgery construction as :func:`_line_doc`, raw operator string.

    ``/Resources`` carries ``/F1`` Helvetica and ``/F2`` Helvetica-Bold so
    multi-operator / multi-font-run fixtures (style-split lines, TJ arrays)
    can be built directly without escaping through ``_line_doc``'s one-Tj-
    per-line shape.
    """
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    page = doc[0]
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, ops.encode("latin-1"))
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font1_xref = doc.get_new_xref()
    doc.update_object(
        font1_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    font2_xref = doc.get_new_xref()
    doc.update_object(
        font2_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /Font << /F1 {font1_xref} 0 R /F2 {font2_xref} 0 R >> >>",
    )
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
        self._tiered_commit_engine = TieredCommitEngine(doc)

    def get_tiered_commit_engine(self) -> TieredCommitEngine:
        return self._tiered_commit_engine


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


def _line_doc_rotated(rotation: int, *lines: str) -> fitz.Document:
    """Same construction as ``_line_doc``, ``/Rotate``d and reserialized."""
    doc = _line_doc(*lines)
    doc[0].set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return fitz.open("pdf", data)


def _pixmap_ink_bbox(page: fitz.Page) -> fitz.Rect:
    pix = page.get_pixmap(dpi=72)
    samples = bytes(pix.samples)
    n = pix.n
    minx = miny = 1e9
    maxx = maxy = -1
    for y in range(pix.height):
        for x in range(pix.width):
            if samples[(y * pix.width + x) * n] < 200:
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
    assert maxx >= 0, "fixture: no dark pixmap pixels found"
    return fitz.Rect(minx, miny, maxx, maxy)


@pytest.mark.parametrize("rotation", [90, 270])
def test_shape_single_run_target_bbox_is_visual_space_on_rotated_page(
    rotation,
) -> None:
    """Production-path ``target.bbox``/``origin`` must be VISUAL (pixmap) space.

    ``_tier0_target_from_resolve`` derives ``origin``/``bbox`` straight from
    the block index's ``EditableSpan`` geometry, which comes from
    ``page.get_text('dict')``. PyMuPDF keeps that extraction in *unrotated*
    page space on both axes (see
    ``test_text_commit_replay.py::test_bind_origin_page_follows_page_rotate``
    and the annot-geometry entry in ``docs/PITFALLS.md`` for the same
    quirk). But ``prepared.target_bbox_page`` is compared pixel-for-pixel
    against ``page.get_pixmap()`` output by ``model.text_commit.verify``
    (V0c/V0d halo math), which IS visual space. Left unconverted, the
    derived bbox lands in the wrong region of a rotated page's pixmap.
    """
    doc = _line_doc_rotated(rotation, "Total")
    try:
        page = doc[0]
        assert page.rotation == rotation
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1, "fixture must produce exactly one word run"
        result = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id})
        )
        assert result is not None
        bbox = fitz.Rect(result.bbox)

        oracle = _pixmap_ink_bbox(page)

        # Tight containment against the real pixmap ink -- not the mirrored,
        # unrotated rectangle a dict-space (unconverted) derivation would
        # produce.
        margin = 3.0
        assert bbox.x0 <= oracle.x0 + margin, (bbox, oracle)
        assert bbox.y0 <= oracle.y0 + margin, (bbox, oracle)
        assert bbox.x1 >= oracle.x1 - margin, (bbox, oracle)
        assert bbox.y1 >= oracle.y1 - margin, (bbox, oracle)
        # Orientation sanity: "Total" is horizontal ink in unrotated space;
        # at /Rotate 90/270 it must render -- and therefore bound -- vertically.
        assert (bbox.y1 - bbox.y0) > (bbox.x1 - bbox.x0), bbox
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_full_tiered_commit_succeeds_on_rotated_page(rotation) -> None:
    """End-to-end: a Tier 0 commit on a ``/Rotate`` page must actually verify.

    Regression guard for the visual-space conversion above: if any verify
    step still compares dict-space geometry against ``target_bbox_page``
    (now visual space) or vice versa, this is where it would surface as a
    spurious rejection rather than as a silently-wrong number in an
    isolated unit test.
    """
    # Helvetica digits share widths, so this replacement is advance-neutral
    # (the same reasoning REPLACEMENT/SINGLE_SPACE rely on above) -- the
    # point of this fixture is the rotation conversion, not advance proof.
    doc = _line_doc_rotated(rotation, "12345")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1

        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "54321",
            _resolve_result(model, {runs[0].span_id}),
            None,
            None,
        )
        assert reason is None, reason
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED, outcome
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
        # covers_line firewall: a single member run that is not the whole
        # line must keep its OWN run text, never the recovered whole-line
        # dict quote -- substituting the whole line there would bind the
        # whole-line operator and rewrite text the user never selected.
        mid_run = runs[1]
        mid_target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {mid_run.span_id})
        )
        assert mid_target is not None
        assert mid_target.text == mid_run.text
        assert mid_target.text != "Price is 100"
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
    """An extractor-synthesized target that cannot bind must not claim a
    plain NO_MATCH.

    ``[(Price is) -500 (100)] TJ`` extracts (via ``page.get_text("dict")``)
    as ``'Price is 100'`` -- MuPDF materialises the ``-500`` kern advance as
    a real space character -- while the content stream decodes to
    ``b'Price is100'`` (no space byte at all). ``bind_source_text``'s
    byte-equality test therefore fails even against the recovered VERBATIM
    dict-line quote (F7 in the Task 11 Slice 2 design). Before the fix that
    surfaced as ``NO_MATCH`` — byte-identical to the refusal for text that
    is genuinely not on the page, which is why this whole failure class was
    invisible to every corpus number. The engine's own reconstruction (here,
    the extractor's synthesized space) must be named as the suspect instead.
    """
    doc = _ops_doc("BT /F1 12 Tf 72 700 Td [(Price is) -500 (100)] TJ ET")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 3, "fixture must split into three word runs"
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        # Precondition: the extracted line quote carries a space the stream
        # never contained.
        assert target[0] == "Price is 100"
        assert target.source_kind == "dict_line"
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
            "a target assembled by joining word runs (or an extractor's "
            "synthesized whitespace) must not report the same reason as a "
            "target that is genuinely absent from the page"
        )
        assert "whitespace" in result.detail
        # Live-document safety: nothing mutated on a refusal path.
        before = doc.xref_length()
        stream_before = doc.xref_stream(doc[0].get_contents()[0])
        assert doc.xref_length() == before
        assert doc.xref_stream(doc[0].get_contents()[0]) == stream_before
    finally:
        doc.close()


def test_reconstruction_absent_target_still_reports_plain_no_match() -> None:
    """The discriminator must not fire for a genuinely absent target.

    The other half of the distinction: a target with no whitespace at all
    has no reconstruction to blame, so the refusal must stay ``NO_MATCH``.
    Without this the fix could pass its Red test by relabelling *every*
    miss.

    The fixture is a real, still-open gap: ``(To) Tj (tal) Tj`` (two show
    operators, same font, no space) parses to the single run ``'Total'``
    (``_finalize`` merges adjacent same-style, no-gap characters), and the
    recovered dict line quote is also ``'Total'`` -- both by construction
    carry no whitespace, so ``whitespace_reconstructed`` is ``False`` and
    the refusal must stay a plain ``NO_MATCH``: two operators, so no single
    show op carries the whole line and nothing binds.
    """
    doc = _ops_doc("BT /F1 12 Tf 72 700 Td (To) Tj (tal) Tj ET")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1, "adjacent same-style runs merge with no gap"
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id})
        )
        assert target is not None
        assert target.text == "Total"
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


def test_reconstruction_relabel_applies_on_the_live_commit_path_too() -> None:
    """``_attempt_tiered_commit`` re-labels as well, and mutates nothing.

    The helper is called from two sites and the classify-path tests alone
    make it mutation-SENSITIVE, so without this test reverting *this* call
    site to a bare ``prepared.reason`` left the whole suite green (verified
    by mutation).  A shared helper is not evidence that each of its callers
    uses it.
    """
    doc = _ops_doc("BT /F1 12 Tf 72 700 Td [(Price is) -500 (100)] TJ ET")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 3
        before = doc.xref_length()
        stream_before = doc.xref_stream(doc[0].get_contents()[0])

        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "Price is  200",
            _resolve_result(model, {r.span_id for r in runs}),
            None,
            None,
        )
        assert outcome is None
        assert reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
        # The live document is untouched: this is the commit path, so a
        # refusal that had already written would be the worse defect.
        assert doc.xref_length() == before
        assert doc.xref_stream(doc[0].get_contents()[0]) == stream_before
    finally:
        doc.close()


def test_reconstruction_reason_code_is_stable() -> None:
    """The reason string is a telemetry contract (dto.py docstring)."""
    assert (
        RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
        == "target_reconstruction_unverified"
    )
    # Re-exported through the module the editor actually imports.
    assert (
        pdf_text_edit.RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
        == "target_reconstruction_unverified"
    )


# --------------------------------------------------------------------------
# Task 11 Slice 2 — verbatim dict-line recovery (D5 follow-up)
#
# The reconstruction tests above prove the engine correctly REFUSES when it
# cannot prove its target text.  These prove it can go further: recover the
# verbatim source line from ``page.get_text("dict")`` when a runtime
# content-and-geometry proof binds it to the exact runs resolved, so a
# source gap that is not exactly one space (F1/F2) or a padded operand (F2)
# no longer needs to be refused at all.
# --------------------------------------------------------------------------


def test_f1_inner_multi_space_recovers_and_commits() -> None:
    """Headline case: a two-space inner gap recovers, binds, and commits."""
    doc = _line_doc("Price is  100")  # two spaces in the source operand
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 3, "fixture must split into three word runs"
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        assert target.text == "Price is  100"
        assert target.source_kind == "dict_line"
        assert target.joined_runs == 3

        binding = bind_source_text(
            doc, doc[0], target_text=target.text, expected_origin=target.origin
        )
        assert isinstance(binding, SourceSpanBinding), (
            f"recovered target should bind, got "
            f"{getattr(binding, 'reason', type(binding).__name__)}"
        )
        assert binding.show.decoded_bytes == b"Price is  100"

        # User types the COLLAPSED form (Level A) -- what the inline editor
        # showed -- and the engine must re-project the source's own double
        # space onto the replacement.
        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "Price is 200",
            _resolve_result(model, {r.span_id for r in runs}),
            None,
            None,
        )
        assert reason is None, reason
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED, outcome
        stream = doc.xref_stream(doc[0].get_contents()[0])
        assert b"(Price is  200)" in stream, stream
        assert b"(Price is  100)" not in stream, stream
    finally:
        doc.close()


def test_f2_leading_trailing_padding_recovers_and_commits() -> None:
    """A padded single-run operand recovers the dict-line origin, not the
    stripped run's own origin -- the assertion that fails hardest today."""
    doc = _line_doc("  12345  ")
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1, "fixture must parse to a single stripped run"
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id})
        )
        assert target is not None
        assert target.text == "  12345  "
        assert target.joined_runs == 1
        assert target.source_kind == "dict_line"
        # Dict origin (no padding advance), NOT the run's stripped origin.
        assert target.origin[0] == pytest.approx(72.0)
        assert target.origin[0] != pytest.approx(float(runs[0].origin.x))
        assert target.bbox[0] <= 72.01

        binding = bind_source_text(
            doc, doc[0], target_text=target.text, expected_origin=target.origin
        )
        assert isinstance(binding, SourceSpanBinding)

        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "54321",
            _resolve_result(model, {runs[0].span_id}),
            None,
            None,
        )
        assert reason is None, reason
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED, outcome
        stream = doc.xref_stream(doc[0].get_contents()[0])
        assert b"(  54321  )" in stream, stream
        assert b"(  12345  )" not in stream, stream
    finally:
        doc.close()


def test_f3_multi_span_line_recovers_but_still_refuses() -> None:
    """One line, two operators (style break): recovery proves the quote,
    but no single show op carries the whole line, so it must still refuse
    -- and must not mutate the document while refusing."""
    doc = _ops_doc(
        "BT /F1 12 Tf 72 700 Td (Price is  ) Tj /F2 12 Tf (100) Tj ET"
    )
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 3
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        assert target.text == "Price is  100"
        assert target.source_kind == "dict_line"

        before = doc.xref_length()
        stream_before = doc.xref_stream(doc[0].get_contents()[0])
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
        assert result.reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED

        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "Price is  200",
            _resolve_result(model, {r.span_id for r in runs}),
            None,
            None,
        )
        assert outcome is None
        assert reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
        assert doc.xref_length() == before
        assert doc.xref_stream(doc[0].get_contents()[0]) == stream_before
    finally:
        doc.close()


def test_f4_flags0_dict_never_emits_non_text_blocks() -> None:
    """Tripwire: at ``flags=0`` a page with an image block still has NO
    type-1 block in ``get_text("dict")`` -- the block-skip sub-case
    ``_parse_block`` guards against is empty, not merely untested. If a
    PyMuPDF upgrade ever starts emitting type != 0 blocks at ``flags=0``,
    this fails loudly instead of silently misaligning ``block_idx``.
    """
    doc = _line_doc("Price is  100")
    try:
        page = doc[0]
        pix = fitz.Pixmap(fitz.csGRAY, (0, 0, 8, 8), False)
        pix.clear_with(0)
        page.insert_image(fitz.Rect(72, 60, 172, 110), pixmap=pix)
        data = doc.tobytes()
    finally:
        doc.close()
    doc = fitz.open("pdf", data)
    try:
        blocks = doc[0].get_text("dict", flags=0)["blocks"]
        assert all(b.get("type") == 0 for b in blocks), (
            "flags=0 dict emitted a non-text block; block_idx alignment is "
            "no longer safe -- recovery must be re-audited"
        )

        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 3
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        assert target.text == "Price is  100"
        assert target.source_kind == "dict_line"
    finally:
        doc.close()


def test_f5a_identical_line_texts_bind_to_their_own_line() -> None:
    """Two lines with IDENTICAL text: content equality alone cannot
    distinguish them, so this is the only test that fails if the
    implementation ever reaches for ``lines[0]`` instead of
    ``lines[line_idx]``."""
    doc = _ops_doc(
        "BT /F1 12 Tf 72 700 Td (  Total  ) Tj 0 -14 Td (  Total  ) Tj ET"
    )
    try:
        model = _StubModel(doc)
        line0 = _line_group(model, 0)
        line1 = _line_group(model, 1)
        assert line0 and line1
        assert (line0[0].block_idx, line0[0].line_idx) != (
            line1[0].block_idx,
            line1[0].line_idx,
        )

        target0 = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in line0})
        )
        target1 = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in line1})
        )
        assert target0 is not None and target1 is not None
        assert target0.text == "  Total  "
        assert target1.text == "  Total  "
        assert target0.origin == pytest.approx((72.0, 142.0))
        assert target1.origin == pytest.approx((72.0, 156.0))

        binding0 = bind_source_text(
            doc, doc[0], target_text=target0.text, expected_origin=target0.origin
        )
        binding1 = bind_source_text(
            doc, doc[0], target_text=target1.text, expected_origin=target1.origin
        )
        assert isinstance(binding0, SourceSpanBinding)
        assert isinstance(binding1, SourceSpanBinding)
        assert binding0.show.origin_user[1] != binding1.show.origin_user[1]
    finally:
        doc.close()


def test_f5b_distinct_line_texts_resolve_by_content() -> None:
    """Two lines with distinct text: neither target crosses into the
    other's text."""
    doc = _ops_doc(
        "BT /F1 12 Tf 72 700 Td (  Total  ) Tj 0 -14 Td (Price is  100) Tj ET"
    )
    try:
        model = _StubModel(doc)
        line0 = _line_group(model, 0)
        line1 = _line_group(model, 1)
        target0 = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in line0})
        )
        target1 = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in line1})
        )
        assert target0 is not None and target1 is not None
        assert target0.text == "  Total  "
        assert target1.text == "Price is  100"
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_f6_rotated_page_padding_recovers_and_commits(rotation) -> None:
    """Rotated-page control: recovery survives ``/Rotate`` because the dict
    ``dir`` is still ``(1, 0)`` in unrotated space (gate P6 passes)."""
    doc = _line_doc_rotated(rotation, "  12345  ")
    try:
        page = doc[0]
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 1
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {runs[0].span_id})
        )
        assert target is not None
        assert target.text == "  12345  "
        assert target.source_kind == "dict_line"

        bbox = fitz.Rect(target.bbox)
        oracle = _pixmap_ink_bbox(page)
        margin = 3.0
        assert bbox.x0 <= oracle.x0 + margin, (bbox, oracle)
        assert bbox.y0 <= oracle.y0 + margin, (bbox, oracle)
        assert bbox.x1 >= oracle.x1 - margin, (bbox, oracle)
        assert bbox.y1 >= oracle.y1 - margin, (bbox, oracle)
        assert (bbox.y1 - bbox.y0) > (bbox.x1 - bbox.x0), bbox

        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "54321",
            _resolve_result(model, {runs[0].span_id}),
            None,
            None,
        )
        assert reason is None, reason
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED, outcome
        stream = doc.xref_stream(doc[0].get_contents()[0])
        assert b"(  54321  )" in stream, stream
        assert b"(  12345  )" not in stream, stream
    finally:
        doc.close()


def test_f8_stale_block_index_never_binds_the_wrong_line() -> None:
    """Fail-closed proof: a block index built against one document snapshot
    (A), consulted while the live document is a DIFFERENT snapshot (B) with
    an extra higher line, must never recover B's unrelated line just
    because the stale index says ``block_idx == 0``."""
    doc_a = _line_doc("Price is  100")
    try:
        data_a = doc_a.tobytes()
    finally:
        doc_a.close()

    # doc B: same page, with an extra higher line prepended to the stream.
    doc_b = fitz.open("pdf", data_a)
    try:
        page = doc_b[0]
        xref = page.get_contents()[0]
        existing = doc_b.xref_stream(xref)
        prefix = b"BT /F1 12 Tf 72 750 Td (Other  Line) Tj ET\n"
        doc_b.update_stream(xref, prefix + existing)
        data_b = doc_b.tobytes()
    finally:
        doc_b.close()

    doc_a = fitz.open("pdf", data_a)  # rebuilt: block_manager indexes THIS
    doc_b = fitz.open("pdf", data_b)  # live doc the model actually reads
    try:
        # Precondition: doc B really did shift block_idx 0 to "Other  Line",
        # so the test cannot go vacuous.
        dict_blocks = doc_b[0].get_text("dict", flags=0)["blocks"]
        assert dict_blocks[0]["lines"][0]["spans"][0]["text"] == "Other  Line"
        assert dict_blocks[1]["lines"][0]["spans"][0]["text"] == "Price is  100"

        model = _StubModel(doc_a)  # block_manager built on A
        model.doc = doc_b  # live doc is B -- no mutation, fully deterministic
        runs = model.block_manager.get_runs(0)
        assert len(runs) == 3

        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        assert target.source_kind == "run_join"
        assert target.text == "Price is 100"
        assert "Other" not in target.text

        result = _classify_tier0_candidate(
            model,
            doc_b[0],
            0,
            "Price is  200",
            _resolve_result(model, {r.span_id for r in runs}),
            None,
            None,
            DocumentFontRegistry(doc_b),
        )
        assert isinstance(result, PlanRejection)
        assert result.reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
    finally:
        doc_a.close()
        doc_b.close()


def test_f8b_content_mismatch_with_aligned_geometry_refuses() -> None:
    """A1/A2 isolated: geometry gates G1-G4 alone do NOT catch every
    wrong-line bind.

    F8 (above) happens to be caught by G1 (the prepended line sits at a
    different baseline than the indexed run). This fixture prepends a
    DIFFERENT-content line at the SAME baseline, starting to the left of
    and wide enough to contain the indexed run's bbox, so G1-G4 all pass
    -- content equality (A1/A2) is the only gate left standing. Mutation-
    verified: deleting ``if not (a1 or a2): return None`` makes this
    fixture recover ``'Something else entirely here'`` as the target text,
    which is exactly the wrong-text catastrophe this stage exists to
    prevent.
    """
    doc_a = _line_doc("Price is  100")
    try:
        data_a = doc_a.tobytes()
    finally:
        doc_a.close()

    doc_b = fitz.open("pdf", data_a)
    try:
        page = doc_b[0]
        xref = page.get_contents()[0]
        existing = doc_b.xref_stream(xref)
        # Same baseline (700 Td == y 142 in dict space), starts left of and
        # extends past the indexed run's own bbox.
        prefix = b"BT /F1 12 Tf 40 700 Td (Something else entirely here) Tj ET\n"
        doc_b.update_stream(xref, prefix + existing)
        data_b = doc_b.tobytes()
    finally:
        doc_b.close()

    doc_a = fitz.open("pdf", data_a)
    doc_b = fitz.open("pdf", data_b)
    try:
        dict_blocks = doc_b[0].get_text("dict", flags=0)["blocks"]
        line0 = dict_blocks[0]["lines"][0]
        # Preconditions: same baseline, and the prepended line's bbox
        # contains the indexed run's bbox -- so G1-G4 cannot be what
        # refuses this fixture; only a content gate can.
        assert line0["spans"][0]["text"] == "Something else entirely here"
        assert line0["spans"][0]["origin"][1] == pytest.approx(142.0)

        model = _StubModel(doc_a)
        model.doc = doc_b
        runs = model.block_manager.get_runs(0)
        assert len(runs) == 3

        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        assert target.source_kind == "run_join"
        assert target.text == "Price is 100"
        assert "Something" not in target.text
    finally:
        doc_a.close()
        doc_b.close()


def test_f9_color_split_runs_with_no_whitespace_use_a2_shape() -> None:
    """A2 shape: two show ops of DIFFERENT color and no space between them
    split into two runs whose naive ``" ".join`` inserts a space the source
    never had (``"To tal"``). Recovery's A2 gate (verbatim concatenation)
    rescues this shape via the dict line quote instead.

    Deviation from the approved design's literal fixture: the design's
    ``_ops_doc("... /F1 (To) Tj /F2 12 Tf (tal) Tj ...")`` (font-only
    break) does NOT split into two runs on this PyMuPDF version --
    ``_parse_runs_from_raw_line`` (text_block_parsing.py:448-451) only
    breaks on cross-axis delta, gap, size delta, COLOR change, or kind
    change; font name alone is never compared. Probe-confirmed: that exact
    op string merges into a single run ``'Total'`` (see
    ``test_reconstruction_absent_target_still_reports_plain_no_match``,
    which now uses it). A genuine two-run, no-whitespace split needs a
    trigger the run-splitter actually checks; a fill-color change between
    the two ``Tj`` ops (no font change) is the minimal one.
    """
    doc = _ops_doc(
        "BT /F1 12 Tf 72 700 Td 0 0 0 rg (To) Tj 1 0 0 rg (tal) Tj ET"
    )
    try:
        model = _StubModel(doc)
        runs = _line_group(model, 0)
        assert len(runs) == 2, "color change must split the run"
        assert [r.text for r in sorted(runs, key=lambda r: r.origin.x)] == [
            "To",
            "tal",
        ]
        target = _tier0_target_from_resolve(
            model, 0, _resolve_result(model, {r.span_id for r in runs})
        )
        assert target is not None
        assert target.text == "Total"  # A2, not " ".join -> "To tal"
        assert target.whitespace_reconstructed is False

        result = _classify_tier0_candidate(
            model,
            doc[0],
            0,
            "Value",
            _resolve_result(model, {r.span_id for r in runs}),
            None,
            None,
            DocumentFontRegistry(doc),
        )
        assert isinstance(result, PlanRejection)
        assert result.reason == RejectReason.NO_MATCH
        assert result.reason != RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
    finally:
        doc.close()


def test_f10_replacement_for_reprojects_whitespace() -> None:
    """Pure unit table for :meth:`_Tier0Target.replacement_for` -- no
    document, no bind, no commit; just the string transform."""
    dict_line = lambda text: _Tier0Target(text, (0.0, 0.0), (0.0, 0.0, 1.0, 1.0), 1, "dict_line")  # noqa: E731
    run_join = lambda text: _Tier0Target(text, (0.0, 0.0), (0.0, 0.0, 1.0, 1.0), 1, "run_join")  # noqa: E731

    # Level A: collapsed canonical edit -> source gaps + outer padding restored.
    assert dict_line("Price is  100").replacement_for("Price is 200") == "Price is  200"
    assert dict_line("  Total  ").replacement_for("Sum") == "  Sum  "
    # Level B: restructured edit -> only outer padding restored.
    assert dict_line("  Total  ").replacement_for("Grand Total") == "  Grand Total  "
    assert (
        dict_line("Price is  100").replacement_for("Price is  200")
        == "Price is  200"
    )
    # Empty/whitespace-only edits pass through unchanged (EMPTY_REPLACEMENT).
    assert dict_line("  Total  ").replacement_for("") == ""
    assert dict_line("  Total  ").replacement_for("   ") == "   "
    # run_join targets are untouched (today's behaviour).
    assert run_join("Price is 100").replacement_for("Price is 200") == "Price is 200"
    # Identity: replacement equals target -> caller hits NO_CHANGE.
    assert (
        dict_line("Price is  100").replacement_for("Price is  100")
        == "Price is  100"
    )
    # Editor open/close with no edit: the inline editor shows the COLLAPSED
    # form, so re-projecting it must reproduce the source exactly, or every
    # padded/multi-space line would spuriously rewrite on a no-op edit.
    assert (
        dict_line("Price is  100").replacement_for("Price is 100")
        == "Price is  100"
    )
    assert dict_line("  12345  ").replacement_for("12345") == "  12345  "
