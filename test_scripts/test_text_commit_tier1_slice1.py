"""Red-light tests for the Tier 1 Slice 1 kern-compensated transplant.

Slice 1 composes two Task 10 primitives -- ``patch.kern_for_displacement``
(extracted from ``build_advance_preserving_erase``) and
``patch.build_transplant_replacement`` -- into ``"[(new) K] TJ"`` spliced at
the source show op's exact byte range, reached only by escalating a Tier 0
``ADVANCE_MISMATCH``.  Nothing under ``model/`` implements this yet: every
new symbol these tests exercise (``plan.prepare_plan``,
``patch.kern_for_displacement``, ``patch.build_kern_compensated_transplant``,
``patch.UnsupportedShowOperatorError``, ``inspect.
find_pages_sharing_content_stream``, ``verify.verify_tier1_commit`` and its
growth-probe helpers, ``dto.HIGH_FIDELITY_TIERS``, ``PreparedEdit.tier`` and
friends, ``TieredCommitEngine(..., max_tier=...)``) is imported lazily
inside each test body so the module still collects cleanly while every test
fails against current HEAD.

Fixture provenance: the target must be the FIRST show after a
``Td``/``Tm``/``T*``/``BT`` (otherwise ``bind_source_text`` refuses it with
``UNTRACKED_ADVANCE`` before any Slice 1 gate runs -- see
``test_text_commit_structural_gates.py``'s ``origin_reliable`` gate).  All
streams are hand-authored raw content with literal ``Tj``: PyMuPDF's own
``insert_text`` only ever emits hex ``[<...>] TJ`` arrays.
"""
from __future__ import annotations

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
    FontOutcome,
    FontResourceAction,
    RejectReason,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, replay_page  # noqa: E402
from model.text_commit.patch import (  # noqa: E402
    apply_patchset,
    build_reversal_patchset,
    build_transplant_replacement,
)
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_tier0_plan  # noqa: E402

import model.text_commit.dto as dto_module  # noqa: E402
import model.text_commit.engine as engine_module  # noqa: E402
import model.text_commit.inspect as inspect_module  # noqa: E402
import model.text_commit.patch as patch_module  # noqa: E402
import model.text_commit.plan as plan_module  # noqa: E402
import model.text_commit.preview as preview_module  # noqa: E402
import model.text_commit.verify as verify_module  # noqa: E402

TARGET = "iii"
TAIL_SPACES = " " * 12
TAIL_WORD = "tail"
TAIL_FULL = TAIL_SPACES + TAIL_WORD
WORLD = "world"
GROWTH_REPLACEMENT = "MMM"  # helv M=833/1000 vs i=222/1000: ~22pt growth at 12pt
NARROW_REPLACEMENT = "i"  # narrower than "iii": the no-growth escalation control

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


def _add_font(doc: fitz.Document, page: fitz.Page) -> None:
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")


def _stream_doc(stream: bytes) -> fitz.Document:
    """One page whose only content is ``stream``, with /F1 = Helvetica.

    Same xref surgery as ``test_text_commit_structural_gates._stream_doc``.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    _add_font(doc, page)
    return doc


def _stream_doc_with_size(stream: bytes, *, width: float, height: float) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    _add_font(doc, page)
    return doc


def _composite_doc() -> fitz.Document:
    """The corrected Slice 1 composite fixture (fixture_notes in the design).

    ``iii`` is the first show after ``Td`` (origin_reliable); the
    same-line, same-font-selection successor ``tail`` (preceded by 12
    spaces at 9pt, a ~30pt blank gap) consumes ``iii``'s advance with no
    intervening ``Td``/``Tm``/``T*`` -- the compensation oracle; ``world``
    is a second, unrelated baseline; the intervening ``Tf`` forces MuPDF to
    split ``iii``/``tail`` into distinct rawdict spans on both sides of the
    edit.
    """
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"/F1 9 Tf (" + TAIL_FULL.encode() + b") Tj "
        b"0 -20 Td /F1 12 Tf (" + WORLD.encode() + b") Tj ET"
    )
    return _stream_doc(stream)


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _first_char_origin(page: fitz.Page, probe: str) -> tuple[float, float]:
    """Char-level (not span-level) origin of ``probe``'s first occurrence.

    ``tail`` shares a span with its 12 leading spaces (one Tj, one show
    op), so the SPAN origin is the first space's origin, not ``t``'s --
    exactly the distinction the design's compensation oracle depends on.
    """
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                text = "".join(ch["c"] for ch in chars)
                idx = text.find(probe)
                if idx != -1:
                    return tuple(chars[idx]["origin"])
    raise AssertionError(f"{probe!r} not found in rawdict")


def _target_bbox(page: fitz.Page, probe: str) -> tuple[float, float, float, float]:
    """Bbox of just ``probe``'s own characters, char-level not span-level.

    DEVIATION from the design's fixture as originally drafted (recorded per
    the task rules): without an intervening ``Tf``/``Tm``/``T*``, MuPDF
    merges ``probe`` and a same-line successor sharing font state into ONE
    rawdict span (measured directly on this PyMuPDF build), so ``_span(page,
    probe)["bbox"]`` is the WHOLE merged span's bbox, not ``probe``'s own --
    physically wrong as a ``target_bbox`` for the neighbour-growth fixtures
    (``test_growth_into_a_neighbour_word_on_the_same_baseline_is_refused``,
    ``test_growth_over_a_single_narrow_neighbour_glyph_is_refused``), which
    need the TIGHT target box to exercise the growth-zone gates at all. This
    unions only the chars belonging to ``probe``'s first occurrence, exactly
    like ``_first_char_origin`` already has to do char-level for the same
    reason.
    """
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                text = "".join(ch["c"] for ch in chars)
                idx = text.find(probe)
                if idx != -1:
                    sub = chars[idx : idx + len(probe)]
                    return (
                        min(c["bbox"][0] for c in sub),
                        min(c["bbox"][1] for c in sub),
                        max(c["bbox"][2] for c in sub),
                        max(c["bbox"][3] for c in sub),
                    )
    raise AssertionError(f"{probe!r} not found in rawdict")


def _target_show(doc: fitz.Document, target_bytes: bytes = b"iii") -> object:
    replay = replay_page(doc, doc[0])
    assert not replay.malformed
    matches = [s for s in replay.shows if s.decoded_bytes == target_bytes]
    assert len(matches) == 1, f"expected 1 show decoding to {target_bytes!r}"
    return matches[0]


def _prepare_plan_fn():
    """``plan.prepare_plan`` does not exist yet -- the Slice 1 entry point."""
    fn = getattr(plan_module, "prepare_plan", None)
    assert fn is not None, (
        "model.text_commit.plan.prepare_plan is not implemented yet "
        "(Task 11 Slice 1); prepare_tier0_plan + escalation must be composed"
    )
    return fn


# ============================================================== CLAUSE tests


def test_kern_compensated_transplant_candidate_proves_every_slice1_clause():
    """The composite fixture: prepare, preview, forced-failure, commit, undo."""
    doc = _composite_doc()
    page = doc[0]
    registry = DocumentFontRegistry(doc)
    capability = registry.capability(page, "F1")
    assert capability is not None

    show = _target_show(doc)
    assert show.operator == "Tj"
    assert show.origin_reliable is True  # first show after Td

    stream_xref = page.get_contents()[0]
    stream_bytes = doc.xref_stream(stream_xref)
    assert stream_bytes[show.op_start : show.op_end] == b"(iii) Tj"

    source_advance = capability.string_width(TARGET, 12.0)
    replacement_advance = capability.string_width(GROWTH_REPLACEMENT, 12.0)
    assert source_advance is not None and replacement_advance is not None
    assert replacement_advance > source_advance  # growth is real, load-bearing

    tail_origin_before = _first_char_origin(page, "tail")
    world_origin_before = _first_char_origin(page, WORLD)
    pre_edit_shows = replay_page(doc, page).shows

    # ---- CLAUSE 2a: anti-vacuity control (Task 10 Phase-A idiom) ----------
    # A whole-op transplant WITHOUT the kern really does shove the successor
    # right: this is the control that proves the kern is load-bearing, and
    # it exercises only EXISTING patch.py machinery.
    uncompensated = build_transplant_replacement(
        stream_bytes, show, b"(" + GROWTH_REPLACEMENT.encode() + b") Tj"
    )
    spliced = (
        stream_bytes[: uncompensated.start]
        + uncompensated.replacement_bytes
        + stream_bytes[uncompensated.end :]
    )
    doc.update_stream(stream_xref, spliced)
    page = doc[0]
    tail_origin_uncompensated = _first_char_origin(page, "tail")
    assert tail_origin_uncompensated[0] - tail_origin_before[0] > 1.0
    assert tail_origin_uncompensated[1] == pytest.approx(tail_origin_before[1], abs=0.01)
    # restore the exact original bytes
    doc.update_stream(stream_xref, stream_bytes)
    page = doc[0]
    assert _first_char_origin(page, "tail") == tail_origin_before

    # ---- CLAUSE 5/1/2b/3/4/6/7/8: needs the Slice 1 composite builder ------
    prepare_plan = _prepare_plan_fn()

    span = _span(page, TARGET)
    prepared = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=registry,
        max_tier=1,
    )
    assert isinstance(prepared, PreparedEdit), prepared

    # CLAUSE 5: exact op range + digest, not the string range.
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    assert prepared.replacement.stream_xref == show.stream_xref
    assert prepared.replacement.start == show.op_start
    assert prepared.replacement.end == show.op_end
    assert prepared.replacement.expected_bytes == b"(iii) Tj"
    import hashlib

    assert prepared.replacement.expected_stream_digest == hashlib.sha256(
        stream_bytes
    ).hexdigest()
    import re

    assert re.match(
        rb"^\[\(MMM\) -?\d+\.\d{6}\] TJ$", prepared.replacement.replacement_bytes
    )

    kern_for_displacement = patch_module.kern_for_displacement
    build_kern_compensated_transplant = patch_module.build_kern_compensated_transplant
    replacement_encoded = capability.encode_simple(GROWTH_REPLACEMENT)
    independent = build_kern_compensated_transplant(
        stream_bytes,
        show,
        replacement_encoded=replacement_encoded,
        source_advance=source_advance,
        replacement_advance=replacement_advance,
    )
    assert independent.replacement_bytes == prepared.replacement.replacement_bytes

    # CLAUSE 2b: net advance compensated, and the compensation is load-bearing.
    expected_kern = kern_for_displacement(show, source_advance - replacement_advance)
    assert prepared.kern_adjustment == pytest.approx(expected_kern)
    assert prepared.replacement_advance > prepared.source_advance

    # CLAUSE 6: preview and commit share one prepared product.
    baseline_png = page.get_pixmap(
        clip=page.rect, matrix=fitz.Matrix(1.0, 1.0), annots=True
    ).tobytes("png")
    open_preview_session = preview_module.open_preview_session
    session = open_preview_session(doc, 0, "s1", max_tier=1)
    assert session is not None
    renderer = preview_module.PlanPreviewRenderer(session)
    preview_request = preview_module.PlanPreviewRequest(
        session_key="s1",
        generation=1,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        clip_rect=tuple(page.rect),
        render_scale=1.0,
    )
    preview_result = renderer.render(preview_request)
    assert preview_result.plan_token is not None
    assert preview_result.reject_reason is None
    assert preview_result.png_bytes != baseline_png  # the growth must be visible

    engine = TieredCommitEngine(doc, max_tier=1)
    prepared_via_engine = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared_via_engine, PreparedEdit)
    assert preview_result.plan_token == prepared_via_engine.token
    renderer.close()

    # CLAUSE 8: a forced verification failure reverts everything, live.
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()
    real_verify = engine_module.verify_tier1_commit

    def _fail(*args, **kwargs):
        return verify_module.VerificationFailure(
            reason=RejectReason.VERIFICATION_FAILED, detail="injected"
        )

    engine_module.verify_tier1_commit = _fail
    try:
        outcome = engine.commit(prepared_via_engine)
    finally:
        engine_module.verify_tier1_commit = real_verify
    assert outcome.status is CommitStatus.FAILED
    assert doc.xref_stream(stream_xref) == stream_bytes
    assert page_fingerprint(doc, page) == fingerprint_before
    assert doc.xref_length() == xrefs_before
    assert TARGET in doc[0].get_text()

    # CLAUSE 7: capture pre-commit state for the reversal check below.
    from model.text_commit.inspect import read_page_streams

    pre_streams = tuple(read_page_streams(doc, page))
    pre_fingerprint = page_fingerprint(doc, page)

    # CLAUSE 1: real commit.
    outcome = engine.commit(prepared_via_engine)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    assert outcome.font_outcomes[0].action == FontResourceAction.SOURCE_RESOURCE_REUSED
    assert outcome.font_outcomes[0].written_font_xref == outcome.font_outcomes[0].source_font_xref
    assert outcome.warnings == ("tier1_ink_growth",)
    assert "growth_region_blank_pre_edit" in outcome.verified_properties
    assert "raster_identity_outside_halo" in outcome.verified_properties
    assert outcome.allows_external_reflow is False

    page = doc[0]
    clip_text = page.get_text("text", clip=fitz.Rect(*prepared_via_engine.effective_verify_bbox))
    assert GROWTH_REPLACEMENT in clip_text
    assert TARGET not in clip_text

    growth_probe_regions = verify_module.growth_probe_regions
    post_pixmap = page.get_pixmap(dpi=96)
    meta = (post_pixmap.width, post_pixmap.height, post_pixmap.stride, post_pixmap.n)
    regions = growth_probe_regions(
        prepared_via_engine.target_bbox_page, prepared_via_engine.effective_verify_bbox, meta
    )
    samples = bytes(post_pixmap.samples)
    background = samples[0:3]
    found_ink = False
    for x0, y0, x1, y1 in regions:
        for y in range(y0, y1 + 1):
            row = samples[y * meta[2] : (y + 1) * meta[2]]
            for x in range(x0, x1 + 1):
                pixel = row[x * meta[3] : (x + 1) * meta[3]]
                if pixel[:3] != background:
                    found_ink = True
    assert found_ink, "replacement ink must genuinely extend past the source bbox"

    # CLAUSE 3: later shows unmoved (MuPDF rawdict oracle -- the replay does
    # not model advances at all, so it cannot serve as this oracle).
    assert _first_char_origin(page, "tail") == pytest.approx(tail_origin_before, abs=0.1)
    assert _first_char_origin(page, WORLD) == pytest.approx(world_origin_before, abs=0.1)

    # CLAUSE 4: persistent text state unchanged for every later show. Compare
    # against the ORIGINAL (pre-edit) replay captured at the top of this
    # test, matched by decoded bytes (the target's own bytes changed, but
    # every later show's persistent state must not).
    def _persistent_state(s):
        return (
            s.operator, s.font_resource, s.font_size, s.char_spacing,
            s.word_spacing, s.hscale, s.leading, s.rise, s.render_mode,
            s.in_bt, s.gs_depth, s.mc_depth, s.tm, s.ctm,
        )

    post_replay = replay_page(doc, page)
    assert not post_replay.malformed
    pre_later = [s for s in pre_edit_shows if s.decoded_bytes != b"iii"]
    post_later = [s for s in post_replay.shows if s.decoded_bytes != b"MMM"]
    assert len(pre_later) == len(post_later) == 2
    assert len(post_replay.shows) == len(pre_edit_shows)
    for pre_show, post_show in zip(pre_later, post_later):
        assert pre_show.decoded_bytes == post_show.decoded_bytes
        assert _persistent_state(pre_show) == _persistent_state(post_show)

    # CLAUSE 7: undo restores byte-identical bytes.
    reversal = build_reversal_patchset(doc, page, pre_streams, pre_fingerprint)
    assert reversal is not None
    forward, inverse = reversal
    apply_patchset(doc, page, inverse)
    assert doc.xref_stream(stream_xref) == stream_bytes
    assert page_fingerprint(doc, doc[0]) == pre_fingerprint
    apply_patchset(doc, doc[0], forward)
    assert doc.xref_stream(stream_xref) not in (stream_bytes,)
    doc.close()


def test_single_quote_target_is_refused_with_unsupported_show_operator():
    doc = _stream_doc(
        b"BT /F1 12 Tf 72 700 Td 14 TL (" + TARGET.encode() + b") ' ET"
    )
    page = doc[0]
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()

    show = _target_show(doc)
    assert show.operator == "'"
    assert show.decoded_bytes == b"iii"

    registry = DocumentFontRegistry(doc)
    rejection = prepare_tier0_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=NARROW_REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=registry,
    )
    assert isinstance(rejection, PlanRejection)
    new_reason = getattr(RejectReason, "UNSUPPORTED_SHOW_OPERATOR", None)
    assert new_reason is not None, (
        "RejectReason.UNSUPPORTED_SHOW_OPERATOR does not exist yet -- "
        f"today's rejection reason is {rejection.reason!r}"
    )
    assert rejection.reason == new_reason
    assert "T*" in rejection.detail

    prepare_plan = _prepare_plan_fn()
    rejection_tier1 = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=NARROW_REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=registry,
        max_tier=1,
    )
    assert isinstance(rejection_tier1, PlanRejection)
    assert rejection_tier1.reason == new_reason

    UnsupportedShowOperatorError = getattr(
        patch_module, "UnsupportedShowOperatorError", None
    )
    assert UnsupportedShowOperatorError is not None, (
        "patch.UnsupportedShowOperatorError does not exist yet"
    )
    stream_xref = page.get_contents()[0]
    stream_bytes = doc.xref_stream(stream_xref)
    with pytest.raises(UnsupportedShowOperatorError) as excinfo:
        build_transplant_replacement(stream_bytes, show, b"(x) Tj")
    assert excinfo.value.reason == new_reason
    with pytest.raises(UnsupportedShowOperatorError):
        patch_module.build_advance_preserving_erase(stream_bytes, show, 1.0)
    with pytest.raises(UnsupportedShowOperatorError):
        patch_module.build_kern_compensated_transplant(
            stream_bytes,
            show,
            replacement_encoded=b"x",
            source_advance=1.0,
            replacement_advance=1.0,
        )

    assert page_fingerprint(doc, page) == fingerprint_before
    assert doc.xref_length() == xrefs_before
    doc.close()


def test_double_quote_target_is_refused_and_its_spliced_range_would_swallow_tw_tc():
    doc = _stream_doc(
        b"BT /F1 12 Tf 72 700 Td 14 TL 1.5 0.25 ("
        + TARGET.encode()
        + b') " ET'
    )
    page = doc[0]
    stream_xref = page.get_contents()[0]
    stream_bytes = doc.xref_stream(stream_xref)
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()

    show = _target_show(doc)
    assert show.operator == '"'
    # CHARACTERIZATION: the recorded op range starts at the aw operand.
    assert stream_bytes[show.op_start : show.op_end].startswith(b"1.5")

    # Positive control: the state really persists past the double-quote op.
    control_doc = _stream_doc(
        b"BT /F1 12 Tf 72 700 Td 14 TL 1.5 0.25 ("
        + TARGET.encode()
        + b') " (zz) Tj ET'
    )
    control_replay = replay_page(control_doc, control_doc[0])
    zz_show = next(s for s in control_replay.shows if s.decoded_bytes == b"zz")
    assert zz_show.word_spacing == 1.5
    assert zz_show.char_spacing == 0.25
    control_doc.close()

    registry = DocumentFontRegistry(doc)
    rejection = prepare_tier0_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=NARROW_REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=registry,
    )
    assert isinstance(rejection, PlanRejection)
    new_reason = getattr(RejectReason, "UNSUPPORTED_SHOW_OPERATOR", None)
    assert new_reason is not None, (
        "RejectReason.UNSUPPORTED_SHOW_OPERATOR does not exist yet -- "
        f"today's rejection reason is {rejection.reason!r}"
    )
    assert rejection.reason == new_reason
    assert "Tw" in rejection.detail or "aw" in rejection.detail
    assert "Tc" in rejection.detail or "ac" in rejection.detail

    prepare_plan = _prepare_plan_fn()
    rejection_tier1 = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=NARROW_REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=registry,
        max_tier=1,
    )
    assert isinstance(rejection_tier1, PlanRejection)
    assert rejection_tier1.reason == new_reason

    UnsupportedShowOperatorError = getattr(
        patch_module, "UnsupportedShowOperatorError", None
    )
    assert UnsupportedShowOperatorError is not None
    with pytest.raises(UnsupportedShowOperatorError):
        build_transplant_replacement(stream_bytes, show, b"(x) Tj")
    with pytest.raises(UnsupportedShowOperatorError):
        patch_module.build_advance_preserving_erase(stream_bytes, show, 1.0)
    with pytest.raises(UnsupportedShowOperatorError):
        patch_module.build_kern_compensated_transplant(
            stream_bytes,
            show,
            replacement_encoded=b"x",
            source_advance=1.0,
            replacement_advance=1.0,
        )

    assert page_fingerprint(doc, page) == fingerprint_before
    assert doc.xref_length() == xrefs_before
    doc.close()


def test_growth_into_blank_zone_is_accepted_and_widens_the_verified_region():
    doc = _composite_doc()
    page = doc[0]
    registry = DocumentFontRegistry(doc)
    span = _span(page, TARGET)
    prepare_plan = _prepare_plan_fn()

    prepared = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=registry,
        max_tier=1,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.verify_bbox_page[2] > prepared.target_bbox_page[2]
    growth = prepared.replacement_advance - prepared.source_advance
    assert prepared.verify_bbox_page[2] - prepared.target_bbox_page[2] == pytest.approx(
        growth, abs=0.1
    )
    assert prepared.verify_bbox_page[0] == pytest.approx(prepared.target_bbox_page[0])
    assert prepared.verify_bbox_page[1] == pytest.approx(prepared.target_bbox_page[1])
    assert prepared.verify_bbox_page[3] == pytest.approx(prepared.target_bbox_page[3])
    assert prepared.has_ink_growth is True

    growth_probe_regions = verify_module.growth_probe_regions
    post_pixmap = page.get_pixmap(dpi=96)
    meta = (post_pixmap.width, post_pixmap.height, post_pixmap.stride, post_pixmap.n)
    regions = growth_probe_regions(
        prepared.target_bbox_page, prepared.effective_verify_bbox, meta
    )
    assert regions

    count_growth_zone_glyphs = verify_module.count_growth_zone_glyphs
    assert (
        count_growth_zone_glyphs(
            page,
            target_bbox=prepared.target_bbox_page,
            verify_bbox=prepared.effective_verify_bbox,
        )
        == 0
    )

    pre_state = verify_module.capture_page_state(doc, page, prepared)
    # capture_page_state must itself fill PageState.growth_zone_glyphs (the
    # "proven blank PRE-EDIT" wiring) -- not just something callable later.
    assert pre_state.growth_zone_glyphs == 0
    assert (
        verify_module.prove_growth_region_blank(
            pre_state,
            target_bbox=prepared.target_bbox_page,
            verify_bbox=prepared.effective_verify_bbox,
        )
        is None
    )

    engine = TieredCommitEngine(doc, max_tier=1)
    prepared_via_engine = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared_via_engine, PreparedEdit)
    outcome = engine.commit(prepared_via_engine)
    assert outcome.status is CommitStatus.COMMITTED
    assert "growth_region_blank_pre_edit" in outcome.verified_properties

    # No-growth control: a NARROWER replacement never escalates ink growth.
    doc2 = _composite_doc()
    page2 = doc2[0]
    registry2 = DocumentFontRegistry(doc2)
    span2 = _span(page2, TARGET)
    prepared_narrow = prepare_plan(
        doc2,
        page2,
        target_text=TARGET,
        replacement_text=NARROW_REPLACEMENT,
        expected_origin=tuple(span2["origin"]),
        target_bbox=tuple(span2["bbox"]),
        registry=registry2,
        max_tier=1,
    )
    assert isinstance(prepared_narrow, PreparedEdit), prepared_narrow
    assert prepared_narrow.verify_bbox_page == prepared_narrow.target_bbox_page
    assert prepared_narrow.has_ink_growth is False
    doc2.close()
    doc.close()


def test_growth_verify_bbox_outside_page_is_rejected_during_prepare():
    doc = _stream_doc_with_size(
        b"BT /F1 12 Tf 175 120 Td (" + TARGET.encode() + b") Tj ET",
        width=200,
        height=200,
    )
    page = doc[0]
    span = _span(page, TARGET)

    engine = TieredCommitEngine(doc, max_tier=1)
    rejection = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(rejection, PlanRejection)
    new_reason = getattr(RejectReason, "GROWTH_OUTSIDE_PAGE", "growth_outside_page")
    assert rejection.reason == new_reason
    assert "page" in rejection.detail.lower()
    doc.close()


def test_growth_into_filled_vector_region_is_rejected():
    doc = _stream_doc(
        b"BT /F1 12 Tf 72 120 Td (" + TARGET.encode() + b") Tj ET "
        b"0 0 0 rg 70 0 130 200 re f"
    )
    page = doc[0]
    span = _span(page, TARGET)

    engine = TieredCommitEngine(doc, max_tier=1)
    rejection = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(rejection, PlanRejection)
    assert rejection.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    assert rejection.detail.startswith("occupancy:")
    doc.close()


def test_live_commit_reverts_and_reraises_when_verifier_raises():
    doc = _composite_doc()
    page = doc[0]
    span = _span(page, TARGET)
    stream_xref = page.get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)
    fingerprint_before = page_fingerprint(doc, page)

    engine = TieredCommitEngine(doc, max_tier=1)
    prepared = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared, PreparedEdit)
    real_verify = engine_module.verify_tier1_commit

    def _boom(*args, **kwargs):
        raise RuntimeError("injected verifier exception")

    engine_module.verify_tier1_commit = _boom
    try:
        with pytest.raises(RuntimeError, match="injected verifier exception"):
            engine.commit(prepared)
    finally:
        engine_module.verify_tier1_commit = real_verify

    assert doc.xref_stream(stream_xref) == stream_before
    assert page_fingerprint(doc, doc[0]) == fingerprint_before
    assert TARGET in doc[0].get_text()
    doc.close()


def test_growth_into_a_neighbour_word_on_the_same_baseline_is_refused():
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"( " + WORLD.encode() + b") Tj 0 -20 Td (x) Tj ET"
    )
    doc = _stream_doc(stream)
    page = doc[0]
    registry = DocumentFontRegistry(doc)
    span = _span(page, TARGET)
    target_bbox = _target_bbox(page, TARGET)
    fingerprint_before = page_fingerprint(doc, page)
    stream_xref = page.get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)

    engine = TieredCommitEngine(doc, max_tier=1)
    rejection = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=target_bbox,
    )
    assert isinstance(rejection, PlanRejection)
    new_reason = getattr(RejectReason, "GROWTH_REGION_NOT_BLANK", None)
    assert new_reason is not None, "RejectReason.GROWTH_REGION_NOT_BLANK not implemented yet"
    assert rejection.reason == new_reason
    assert rejection.detail.startswith("glyphs:")

    prepare_plan = _prepare_plan_fn()
    prepared_narrow = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=NARROW_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=target_bbox,
        registry=registry,
        max_tier=1,
    )
    assert isinstance(prepared_narrow, PreparedEdit)
    assert prepared_narrow.has_ink_growth is False  # not refused: growth-conditional gate

    # The raster gate would independently refuse too (does not depend on a
    # single gate): probe the same widened zone directly.
    pre_state = verify_module.capture_page_state(doc, page, prepared_narrow)
    growth_amount = 22.0  # ~ helv "iii"->"MMM" widening at 12pt
    wide_verify_bbox = (
        target_bbox[0], target_bbox[1], target_bbox[2] + growth_amount, target_bbox[3],
    )
    assert (
        verify_module.prove_growth_region_blank(
            pre_state, target_bbox=target_bbox, verify_bbox=wide_verify_bbox
        )
        is not None
    )

    assert doc.xref_stream(stream_xref) == stream_before
    assert page_fingerprint(doc, page) == fingerprint_before
    assert TARGET in doc[0].get_text()
    doc.close()


def test_growth_over_a_single_narrow_neighbour_glyph_is_refused():
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"(.) Tj 0 -20 Td (x) Tj ET"
    )
    doc = _stream_doc(stream)
    page = doc[0]
    span = _span(page, TARGET)
    target_bbox = _target_bbox(page, TARGET)
    fingerprint_before = page_fingerprint(doc, page)
    stream_xref = page.get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)

    engine = TieredCommitEngine(doc, max_tier=1)
    rejection = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=target_bbox,
    )
    assert isinstance(rejection, PlanRejection)
    new_reason = getattr(RejectReason, "GROWTH_REGION_NOT_BLANK", None)
    assert new_reason is not None, "RejectReason.GROWTH_REGION_NOT_BLANK not implemented yet"
    assert rejection.reason == new_reason
    assert rejection.detail.startswith("glyphs:")

    count_growth_zone_glyphs = verify_module.count_growth_zone_glyphs
    verify_bbox = (
        target_bbox[0], target_bbox[1], target_bbox[2] + 22.0, target_bbox[3],
    )
    # Even when the *plan* rejects via the _build_tier1 growth check, the
    # character gate can still be exercised directly against the pre-edit
    # page:
    count = count_growth_zone_glyphs(
        page, target_bbox=target_bbox, verify_bbox=verify_bbox
    )
    assert count == 1

    # MUTATION-SENSITIVITY: the raster probe's inner boundary must come from
    # _bbox_pixels(target_bbox)+guard, NOT _halo_pixels(target_bbox) -- the
    # latter would silently admit this fixture (the period sits almost
    # entirely inside the source's own 2pt halo). Pin the probe's first
    # region to start within 2px of the guarded boundary.
    growth_probe_regions = verify_module.growth_probe_regions
    pixmap = page.get_pixmap(dpi=96)
    meta = (pixmap.width, pixmap.height, pixmap.stride, pixmap.n)
    regions = growth_probe_regions(target_bbox, verify_bbox, meta)
    assert regions
    expected_x0 = int(target_bbox[2] * 96 / 72) + 2
    assert abs(regions[0][0] - expected_x0) <= 2

    assert doc.xref_stream(stream_xref) == stream_before
    assert page_fingerprint(doc, page) == fingerprint_before
    doc.close()


def test_content_stream_shared_by_two_pages_is_refused_by_both_tiers():
    doc = fitz.open()
    # ``Page`` wrappers are invalidated by a subsequent ``new_page`` call (a
    # PyMuPDF page-tree quirk), so capture xrefs immediately and re-fetch
    # fresh ``Page`` objects (``doc[i]``) for everything below.
    page0_xref = doc.new_page(width=595, height=842).xref
    page1_xref = doc.new_page(width=595, height=842).xref
    stream = b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page0_xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page1_xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(page0_xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    doc.xref_set_key(page1_xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    page0 = doc[0]
    page1 = doc[1]

    find_pages_sharing_content_stream = getattr(
        inspect_module, "find_pages_sharing_content_stream", None
    )
    assert find_pages_sharing_content_stream is not None, (
        "inspect.find_pages_sharing_content_stream not implemented yet"
    )
    assert find_pages_sharing_content_stream(
        doc, stream_xref=content_xref, page_number=0
    ) == (1,)

    registry = DocumentFontRegistry(doc)
    span = _span(page0, TARGET)
    new_reason = getattr(RejectReason, "SHARED_CONTENT_STREAM", None)
    assert new_reason is not None, "RejectReason.SHARED_CONTENT_STREAM not implemented yet"

    prepare_plan = _prepare_plan_fn()
    fp0_before = page_fingerprint(doc, page0)
    fp1_before = page_fingerprint(doc, page1)
    rejection = prepare_plan(
        doc,
        page0,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=registry,
        max_tier=1,
    )
    assert isinstance(rejection, PlanRejection)
    assert rejection.reason == new_reason
    # Counts-only detail (plan.py:203's privacy convention): a page COUNT,
    # never the other page's xref/number or any document text.
    assert "1" in rejection.detail and "page" in rejection.detail
    assert TARGET not in rejection.detail
    assert str(page1_xref) not in rejection.detail

    rejection_tier0 = prepare_tier0_plan(
        doc,
        page0,
        target_text=TARGET,
        replacement_text="lll",  # helv l==i width: advance-neutral
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=registry,
    )
    assert isinstance(rejection_tier0, PlanRejection)
    assert rejection_tier0.reason == new_reason

    assert page_fingerprint(doc, page0) == fp0_before
    assert page_fingerprint(doc, page1) == fp1_before
    assert doc.xref_stream(content_xref) == stream

    single_doc = _stream_doc(stream)
    single_page = single_doc[0]
    single_registry = DocumentFontRegistry(single_doc)
    single_span = _span(single_page, TARGET)
    control = prepare_plan(
        single_doc,
        single_page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(single_span["origin"]),
        target_bbox=tuple(single_span["bbox"]),
        registry=single_registry,
        max_tier=1,
    )
    assert isinstance(control, PreparedEdit), control
    single_doc.close()
    doc.close()


def test_tier1_refuses_when_source_resource_reuse_is_not_provable(monkeypatch):
    doc = _composite_doc()
    page = doc[0]
    span = _span(page, TARGET)
    stream_xref = page.get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()

    registry = DocumentFontRegistry(doc)
    capability = registry.capability(page, "F1")
    fake_outcome = FontOutcome(
        resource_name="F1",
        source_font_xref=capability.font_xref,
        written_font_xref=capability.font_xref,
        action=FontResourceAction.VALIDATED_FACE_EMBEDDED,
    )
    monkeypatch.setattr(
        engine_module, "build_tier1_font_outcome", lambda *a, **k: fake_outcome
    )

    engine = TieredCommitEngine(doc, max_tier=1)
    rejection = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(rejection, PlanRejection)
    new_reason = getattr(RejectReason, "FONT_RESOURCE_NOT_PROVEN", None)
    assert new_reason is not None, "RejectReason.FONT_RESOURCE_NOT_PROVEN not implemented yet"
    assert rejection.reason == new_reason
    assert "validated_face_embedded" in rejection.detail

    assert page_fingerprint(doc, page) == fingerprint_before
    assert doc.xref_length() == xrefs_before
    assert doc.xref_stream(stream_xref) == stream_before

    monkeypatch.undo()
    prepared = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared, PreparedEdit), prepared
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED
    assert outcome.font_outcomes[0].action == FontResourceAction.SOURCE_RESOURCE_REUSED
    assert outcome.font_outcomes[0].written_font_xref == outcome.font_outcomes[0].source_font_xref
    doc.close()


def test_rawdict_span_bbox_vertical_extent_is_font_metric_not_tight_ink():
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (jjj) Tj 0 -40 Td (ppp) Tj ET"
    )
    doc = _stream_doc(stream)
    page = doc[0]

    span_iii = _span(page, TARGET)
    span_jjj = _span(page, "jjj")
    span_ppp = _span(page, "ppp")
    # Each show sits on its own baseline (0 -40 Td between them), so the
    # ABSOLUTE y0/y1 differ by the Td offset; the invariant under test is
    # that the bbox HEIGHT (ascender-to-descender, font-metric) is the same
    # regardless of 'j'/'p' descenders -- i.e. not tight ink.
    heights = [
        span_iii["bbox"][3] - span_iii["bbox"][1],
        span_jjj["bbox"][3] - span_jjj["bbox"][1],
        span_ppp["bbox"][3] - span_ppp["bbox"][1],
    ]
    assert max(heights) - min(heights) < 0.01

    growth_probe_regions = getattr(verify_module, "growth_probe_regions", None)
    assert growth_probe_regions is not None, (
        "verify.growth_probe_regions not implemented yet -- this test pins "
        "the empirical premise ('growth is horizontal-only by construction') "
        "that its geometry rests on"
    )
    target_bbox = tuple(span_iii["bbox"])
    verify_bbox = (target_bbox[0], target_bbox[1], target_bbox[2] + 20.0, target_bbox[3])
    pixmap = page.get_pixmap(dpi=96)
    meta = (pixmap.width, pixmap.height, pixmap.stride, pixmap.n)
    regions = growth_probe_regions(target_bbox, verify_bbox, meta)
    assert regions
    doc.close()


def test_tier1_undo_replays_the_inverse_patchset_instead_of_a_page_snapshot(tmp_path):
    """Uses the simple two-line fixture, NOT the composite one.

    Measured directly (see design_deviations): ``model.block_manager``
    merges the composite fixture's ``iii``/``tail`` same-line runs into one
    block (``"iii            tail"``), so ``original_text=block.text`` would
    hand the WHOLE merged string to the binder and refuse with
    ``target_reconstruction_unverified`` -- never reaching ``advance_
    mismatch`` at all. This fixture keeps ``iii`` as its own isolated block
    (confirmed: ``fallback_chain == ("tier0:advance_mismatch",)`` under
    ``strict=True`` against current HEAD) and still needs Tier 1 to widen
    into a right-adjacent blank growth zone.
    """
    from model.edit_commands import EditTextCommand
    from model.pdf_model import PDFModel
    from model.text_commit.dto import TextCommitSettings

    pdf_path = tmp_path / "tier1_simple.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (Downstream line stays) Tj ET"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    _add_font(doc, page)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered", max_tier=1))
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    try:
        page0 = model.doc[0]
        annot = page0.add_highlight_annot(fitz.Rect(72, 660, 200, 675))
        annot_xref = annot.xref
        pre_commit_fingerprint = page_fingerprint(model.doc, page0)
        assert 0 not in model.fidelity_protected_pages

        block = next(
            b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or "")
        )
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=GROWTH_REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
        )
        model.command_manager.execute(cmd)
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        assert 0 in model.fidelity_protected_pages

        post_commit_fingerprint = page_fingerprint(model.doc, model.doc[0])

        assert model.command_manager.undo() is True
        assert page_fingerprint(model.doc, model.doc[0]) == pre_commit_fingerprint
        assert 0 not in model.fidelity_protected_pages
        annots_after_undo = list(model.doc[0].annots())
        assert len(annots_after_undo) == 1
        assert annots_after_undo[0].xref == annot_xref

        assert model.command_manager.redo() is True
        assert page_fingerprint(model.doc, model.doc[0]) == post_commit_fingerprint
    finally:
        model.close()


def test_tier0_still_wins_when_it_accepts_at_max_tier_one():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (Price 2024) Tj "
        b"0 -40 Td (Downstream line stays) Tj ET"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    _add_font(doc, page)

    show = _target_show(doc, target_bytes=b"Price 2024")
    registry = DocumentFontRegistry(doc)
    span = _span(page, "Price 2024")
    prepare_plan = _prepare_plan_fn()

    prepared = prepare_plan(
        doc,
        page,
        target_text="Price 2024",
        replacement_text="Price 2025",
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=registry,
        max_tier=1,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    assert prepared.replacement.start == show.string_start
    assert prepared.replacement.end == show.string_end
    assert prepared.replacement.replacement_bytes == b"(Price 2025)"
    assert prepared.kern_adjustment == 0.0

    engine = TieredCommitEngine(doc, max_tier=1)
    prepared_via_engine = engine.prepare(
        page,
        target_text="Price 2024",
        replacement_text="Price 2025",
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared_via_engine, PreparedEdit)
    outcome = engine.commit(prepared_via_engine)
    assert outcome.status is CommitStatus.COMMITTED
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    assert outcome.warnings == ()
    doc.close()


def test_non_escalating_rejections_stay_terminal_and_max_tier_zero_never_reaches_tier1():
    doc = _composite_doc()
    page = doc[0]
    registry = DocumentFontRegistry(doc)
    span = _span(page, TARGET)
    prepare_plan = _prepare_plan_fn()
    fingerprint_before = page_fingerprint(doc, page)

    rejection_default = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=registry,
        max_tier=0,
    )
    assert isinstance(rejection_default, PlanRejection)
    assert rejection_default.reason == RejectReason.ADVANCE_MISMATCH
    assert page_fingerprint(doc, page) == fingerprint_before

    engine_default = TieredCommitEngine(doc)
    result_default = engine_default.prepare(
        page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(result_default, PlanRejection)
    assert result_default.reason == RejectReason.ADVANCE_MISMATCH
    assert page_fingerprint(doc, page) == fingerprint_before
    doc.close()

    mc_doc = _stream_doc(
        b"/P <</MCID 0>> BDC BT /F1 12 Tf 72 700 Td ("
        + TARGET.encode()
        + b") Tj ET EMC"
    )
    mc_page = mc_doc[0]
    mc_registry = DocumentFontRegistry(mc_doc)
    mc_fp_before = page_fingerprint(mc_doc, mc_page)
    mc_rejection = prepare_plan(
        mc_doc,
        mc_page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=mc_registry,
        max_tier=1,
    )
    assert isinstance(mc_rejection, PlanRejection)
    assert mc_rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "marked-content" in mc_rejection.detail
    assert page_fingerprint(mc_doc, mc_page) == mc_fp_before
    mc_doc.close()

    rm_doc = _stream_doc(
        b"BT /F1 12 Tf 3 Tr 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )
    rm_page = rm_doc[0]
    rm_registry = DocumentFontRegistry(rm_doc)
    rm_fp_before = page_fingerprint(rm_doc, rm_page)
    rm_rejection = prepare_plan(
        rm_doc,
        rm_page,
        target_text=TARGET,
        replacement_text=GROWTH_REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=rm_registry,
        max_tier=1,
    )
    assert isinstance(rm_rejection, PlanRejection)
    assert rm_rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "render_mode=3" in rm_rejection.detail
    assert page_fingerprint(rm_doc, rm_page) == rm_fp_before
    rm_doc.close()

    # HIGH_FIDELITY_TIERS should exist for edit_commands.py's reversal gate.
    high_fidelity_tiers = getattr(dto_module, "HIGH_FIDELITY_TIERS", None)
    assert high_fidelity_tiers is not None, "dto.HIGH_FIDELITY_TIERS not implemented yet"
    assert CommitTier.TIER0_LOSSLESS_STREAM_PATCH in high_fidelity_tiers
    assert CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE in high_fidelity_tiers
    assert CommitTier.TIER2_LEGACY not in high_fidelity_tiers
