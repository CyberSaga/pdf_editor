"""Red-light spikes for Tier 1 mutation strategies (plan Task 10, steps 1-3).

Three questions, three fixture families, all synthetic (``fitz.open()``):

1. Erase hazard/compensation -- deleting a show operator's raw bytes shifts
   any later show that shares the same text line (no intervening Td/Tm);
   ``patch.build_advance_preserving_erase`` must compensate exactly with a
   kern-only ``TJ``.
2. Append (TextWriter-at-the-end) vs transplant (splice-in-place) as
   candidate Tier 1 mutation strategies: append cannot inherit the source
   op's z-order, clip scope, ExtGState, marked-content (OCG) membership, or
   trailing (unbalanced) graphics state -- transplant inherits all of them
   by construction, because it lands at the exact same byte position.
3. Font-outcome honesty: an extracted-face TextWriter/transplant write can
   never claim ``SOURCE_RESOURCE_REUSED`` -- only a proven, unmodified
   resource binding may claim that; everything else is
   ``VALIDATED_FACE_EMBEDDED`` (or a system/legacy substitution).

None of this enables Tier 1 in the engine; ``TieredCommitEngine`` never
calls any of these helpers. Every helper imported below is a mutation
primitive or a verification reader only -- redaction, ``clean_contents``,
annotation save/recreate, and neighbor rewriting stay exactly as forbidden
as patch.py's module docstring already says.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import (  # noqa: E402
    FontOutcome,
    FontResourceAction,
    StreamReplacement,
)
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.patch import (  # noqa: E402
    AppliedPatch,
    PatchSet,
    apply_patchset,
    build_advance_preserving_erase,
    build_tier1_font_outcome,
    build_transplant_replacement,
)
from model.text_commit.pdf_lexer import encode_literal_string, splice_stream  # noqa: E402
from model.text_commit.plan import _advance  # noqa: E402
from model.text_commit.replay import ShowOp, replay_page_streams  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    PageState,
    StrategyVerdict,
    _first_diff_outside_halo,
    _span_origins,
    prove_source_resource_reuse,
    verify_tier1_strategy,
)

FONT_OBJ_HELV = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)
FONT_OBJ_HELV_BOLD = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
    "/Encoding /WinAnsiEncoding >>"
)
FONT_OBJ_TIRO = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman "
    "/Encoding /WinAnsiEncoding >>"
)

TARGET_TEXT = "SECRET"
REPLACEMENT_TEXT = "PUBLIC"

_PAGE_W = 595.0
_PAGE_H = 842.0
_VERIFY_DPI = 96


# --------------------------------------------------------------- fixture I/O


def _new_content(doc: fitz.Document, page: fitz.Page, stream: bytes) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
    return xref


def _new_font(doc: fitz.Document, font_obj: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, font_obj)
    return xref


def _set_resources(
    doc: fitz.Document, page: fitz.Page, *, font_xref: int, font_name: str,
    extra: str = "",
) -> None:
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /Font << /{font_name} {font_xref} 0 R >> {extra} >>",
    )


def _find_show(doc: fitz.Document, page: fitz.Page, text: str) -> ShowOp:
    streams = read_page_streams(doc, page)
    replay = replay_page_streams(streams)
    assert not replay.malformed
    target = text.encode("latin-1")
    matches = [s for s in replay.shows if s.decoded_bytes == target]
    assert len(matches) == 1, f"expected exactly one show for {text!r}, got {matches}"
    return matches[0]


def _bbox_for_text(
    page: fitz.Page, text: str
) -> tuple[float, float, float, float] | None:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                joined = "".join(c["c"] for c in chars)
                idx = joined.find(text)
                if idx == -1:
                    continue
                sub = chars[idx : idx + len(text)]
                x0 = min(c["bbox"][0] for c in sub)
                y0 = min(c["bbox"][1] for c in sub)
                x1 = max(c["bbox"][2] for c in sub)
                y1 = max(c["bbox"][3] for c in sub)
                return (x0, y0, x1, y1)
    return None


def _bbox_before_marker(
    page: fitz.Page, marker: str
) -> tuple[float, float, float, float] | None:
    """Bbox of every char preceding ``marker`` within its span.

    Robust to PyMuPDF inserting a synthetic space for a large intra-run
    kern gap (e.g. the ``[(ERA)-250(SEME)] TJ`` fixture extracts as
    ``"ERA SEMEKEEPME"``, not ``"ERASEMEKEEPME"``) -- searching for the
    exact source text would miss that inserted character.
    """
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                joined = "".join(c["c"] for c in chars)
                idx = joined.find(marker)
                if idx == -1 or idx == 0:
                    continue
                prefix = chars[:idx]
                x0 = min(c["bbox"][0] for c in prefix)
                y0 = min(c["bbox"][1] for c in prefix)
                x1 = max(c["bbox"][2] for c in prefix)
                y1 = max(c["bbox"][3] for c in prefix)
                return (x0, y0, x1, y1)
    return None


def _first_char_origin(page: fitz.Page, text: str) -> tuple[float, float] | None:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                joined = "".join(c["c"] for c in chars)
                idx = joined.find(text)
                if idx == -1:
                    continue
                return chars[idx]["origin"]
    return None


def _page_space_bbox_from_pdf_rect(
    pdf_rect: tuple[float, float, float, float], page_height: float
) -> tuple[float, float, float, float]:
    """Convert a bottom-up PDF-user-space rect to the top-down "page space"
    convention ``target_bbox``/rawdict origins/pixmaps all use (matching
    ``plan.py``'s ``target_bbox_page``, itself built from
    ``page.transformation_matrix``)."""
    x0, y0, x1, y1 = pdf_rect
    return (x0, page_height - y1, x1, page_height - y0)


def _pixmap_meta(pixmap: fitz.Pixmap) -> tuple[int, int, int, int]:
    return (pixmap.width, pixmap.height, pixmap.stride, pixmap.n)


def _capture_state(
    doc: fitz.Document, page: fitz.Page, exclude_bbox: tuple[float, float, float, float]
) -> PageState:
    pixmap = page.get_pixmap(dpi=_VERIFY_DPI)
    return PageState(
        streams=tuple(read_page_streams(doc, page)),
        fonts=tuple(page.get_fonts(full=True)),
        annots=tuple((a.xref, tuple(a.rect)) for a in page.annots()),
        nontarget_origins=_span_origins(page, exclude_bbox),
        pixmap_samples=bytes(pixmap.samples),
        pixmap_meta=_pixmap_meta(pixmap),
    )


# ============================================================= Step 1: erase


def _tj_fixture_stream() -> bytes:
    return b"BT /F1 12 Tf 72 700 Td (ERASEME) Tj (KEEPME) Tj ET"


def _tj_array_fixture_stream() -> bytes:
    return b"BT /F1 12 Tf 72 700 Td [(ERA)-250(SEME)] TJ (KEEPME) Tj ET"


def _run_erase_case(stream: bytes) -> None:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    _new_content(doc, page, stream)
    _set_resources(doc, page, font_xref=_new_font(doc, FONT_OBJ_HELV), font_name="F1")

    pre_streams = read_page_streams(doc, page)
    stream_xref, current_bytes = pre_streams[0]
    assert current_bytes == stream

    replay = replay_page_streams(pre_streams)
    assert not replay.malformed
    assert len(replay.shows) == 2
    erase_show, keep_show = replay.shows
    assert erase_show.font_resource == "F1"

    pre_keep_origin = _first_char_origin(page, "KEEPME")
    assert pre_keep_origin is not None
    erased_bbox = _bbox_before_marker(page, "KEEPME")
    assert erased_bbox is not None

    # Captured BEFORE either phase mutates anything -- the halo baseline for
    # the eventual (compensated) post-state.
    pre_state = PageState(
        streams=tuple(pre_streams),
        fonts=tuple(page.get_fonts(full=True)),
        annots=tuple((a.xref, tuple(a.rect)) for a in page.annots()),
        nontarget_origins=_span_origins(page, erased_bbox),
        pixmap_samples=bytes(page.get_pixmap(dpi=_VERIFY_DPI).samples),
        pixmap_meta=_pixmap_meta(page.get_pixmap(dpi=_VERIFY_DPI)),
    )

    # ---- Phase A: hazard characterization, existing API only ----
    hazard_slice = current_bytes[erase_show.op_start : erase_show.op_end]
    hazard_replacement = StreamReplacement(
        stream_xref=stream_xref,
        start=erase_show.op_start,
        end=erase_show.op_end,
        expected_bytes=hazard_slice,
        replacement_bytes=b"",
        expected_stream_digest=hashlib.sha256(current_bytes).hexdigest(),
    )
    hazard_bytes = splice_stream(current_bytes, [hazard_replacement])
    doc.update_stream(stream_xref, hazard_bytes)

    hazard_keep_origin = _first_char_origin(page, "KEEPME")
    assert hazard_keep_origin is not None
    assert hazard_keep_origin != pre_keep_origin  # state changed: the hazard is real
    measured_advance = pre_keep_origin[0] - hazard_keep_origin[0]
    assert measured_advance > 1.0, "KEEPME should have visibly shifted left"
    assert abs(hazard_keep_origin[1] - pre_keep_origin[1]) < 0.01  # same baseline

    # Sanity: restoring the exact original bytes restores the exact origin,
    # so any residual delta in Phase B is attributable to the compensation
    # math, not to some other confound.
    doc.update_stream(stream_xref, current_bytes)
    assert _first_char_origin(page, "KEEPME") == pre_keep_origin

    # ---- Phase B: the real gate -- compensated erase via the new helper ----
    pre_fingerprint = page_fingerprint(doc, page)
    erase_replacement = build_advance_preserving_erase(
        current_bytes, erase_show, measured_advance
    )
    assert isinstance(erase_replacement, StreamReplacement)
    assert erase_replacement.stream_xref == stream_xref

    patchset = PatchSet(
        page_xref=page.xref,
        replacements=(erase_replacement,),
        expected_page_fingerprint=pre_fingerprint,
    )
    applied = apply_patchset(doc, page, patchset)
    assert isinstance(applied, AppliedPatch)

    text = page.get_text()
    assert "ERASEME" not in text
    assert "ERA" not in text.replace("KEEPME", "")

    post_keep_origin = _first_char_origin(page, "KEEPME")
    assert post_keep_origin is not None
    assert abs(post_keep_origin[0] - pre_keep_origin[0]) < 0.1
    assert abs(post_keep_origin[1] - pre_keep_origin[1]) < 0.1

    post_pixmap = page.get_pixmap(dpi=_VERIFY_DPI)
    diff = _first_diff_outside_halo(pre_state, post_pixmap, erased_bbox)
    assert diff is None

    applied.revert(doc)
    assert doc.xref_stream(stream_xref) == current_bytes

    doc.close()


def test_deleting_show_op_moves_later_text_then_erase_compensates_exactly():
    _run_erase_case(_tj_fixture_stream())
    _run_erase_case(_tj_array_fixture_stream())


# ============================================== Steps 2-3: append vs transplant


@dataclass
class ZOrderFixture:
    name: str
    doc: fitz.Document
    page: fitz.Page
    stream_xref: int
    font_xref: int
    font_resource: str
    show: ShowOp
    target_bbox: tuple[float, float, float, float]
    expected_append_failure: str | None  # None => only require *some* failure


def _advance_from_show(fx: ZOrderFixture) -> float:
    registry = DocumentFontRegistry(fx.doc)
    capability = registry.capability(fx.page, fx.show.font_resource)
    assert capability is not None
    return _advance(
        capability, TARGET_TEXT, fx.show.font_size, fx.show.char_spacing,
        fx.show.word_spacing,
    )


def _fixture_under_rect() -> ZOrderFixture:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    stream = (
        b"BT /F0 12 Tf 72 694 Td (" + TARGET_TEXT.encode() + b") Tj ET "
        b"1 0 0 rg 70 690 120 20 re f 0 0 0 rg"
    )
    stream_xref = _new_content(doc, page, stream)
    font_xref = _new_font(doc, FONT_OBJ_HELV)
    _set_resources(doc, page, font_xref=font_xref, font_name="F0")
    show = _find_show(doc, page, TARGET_TEXT)
    return ZOrderFixture(
        name="under_rect", doc=doc, page=page, stream_xref=stream_xref,
        font_xref=font_xref, font_resource="F0", show=show,
        target_bbox=_page_space_bbox_from_pdf_rect(
            (70.0, 690.0, 190.0, 710.0), _PAGE_H
        ),
        expected_append_failure="z_order_changed",
    )


def _fixture_clip() -> ZOrderFixture:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    stream = (
        b"q 70 690 120 20 re W n BT /F0 12 Tf 72 694 Td "
        + b"(" + TARGET_TEXT.encode() + b") Tj ET Q"
    )
    stream_xref = _new_content(doc, page, stream)
    font_xref = _new_font(doc, FONT_OBJ_HELV)
    _set_resources(doc, page, font_xref=font_xref, font_name="F0")
    show = _find_show(doc, page, TARGET_TEXT)
    return ZOrderFixture(
        name="clip", doc=doc, page=page, stream_xref=stream_xref,
        font_xref=font_xref, font_resource="F0", show=show,
        target_bbox=_page_space_bbox_from_pdf_rect(
            (70.0, 690.0, 190.0, 710.0), _PAGE_H
        ),
        expected_append_failure=None,  # append structurally escapes the q/Q
    )


def _fixture_transparency() -> ZOrderFixture:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    font_xref = _new_font(doc, FONT_OBJ_HELV)
    gs_xref = doc.get_new_xref()
    doc.update_object(gs_xref, "<< /Type /ExtGState /ca 0.3 /CA 0.3 >>")
    _set_resources(
        doc, page, font_xref=font_xref, font_name="F0",
        extra=f"/ExtGState << /GS0 {gs_xref} 0 R >>",
    )
    stream = (
        b"/GS0 gs BT /F0 12 Tf 72 694 Td (" + TARGET_TEXT.encode() + b") Tj ET"
    )
    stream_xref = _new_content(doc, page, stream)
    show = _find_show(doc, page, TARGET_TEXT)
    bbox = _bbox_for_text(page, TARGET_TEXT)
    assert bbox is not None
    return ZOrderFixture(
        name="transparency", doc=doc, page=page, stream_xref=stream_xref,
        font_xref=font_xref, font_resource="F0", show=show, target_bbox=bbox,
        expected_append_failure=None,  # loose: state may or may not persist forward
    )


def _fixture_ocg() -> ZOrderFixture:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    ocg_xref = doc.add_ocg("Layer1", on=True)
    font_xref = _new_font(doc, FONT_OBJ_HELV)
    _set_resources(
        doc, page, font_xref=font_xref, font_name="F0",
        extra=f"/Properties << /P0 {ocg_xref} 0 R >>",
    )
    stream = (
        b"/OC /P0 BDC BT /F0 12 Tf 72 694 Td (" + TARGET_TEXT.encode()
        + b") Tj ET EMC"
    )
    stream_xref = _new_content(doc, page, stream)
    show = _find_show(doc, page, TARGET_TEXT)
    bbox = _bbox_for_text(page, TARGET_TEXT)
    assert bbox is not None
    return ZOrderFixture(
        name="ocg", doc=doc, page=page, stream_xref=stream_xref,
        font_xref=font_xref, font_resource="F0", show=show, target_bbox=bbox,
        expected_append_failure="ocg_membership_lost",
    )


def _fixture_resource_collision() -> ZOrderFixture:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    stream = b"BT /F0 12 Tf 72 694 Td (" + TARGET_TEXT.encode() + b") Tj ET"
    stream_xref = _new_content(doc, page, stream)
    font_xref = _new_font(doc, FONT_OBJ_TIRO)  # Times-Roman: distinct from append's font
    _set_resources(doc, page, font_xref=font_xref, font_name="F0")
    show = _find_show(doc, page, TARGET_TEXT)
    bbox = _bbox_for_text(page, TARGET_TEXT)
    assert bbox is not None
    return ZOrderFixture(
        name="resource_collision", doc=doc, page=page, stream_xref=stream_xref,
        font_xref=font_xref, font_resource="F0", show=show, target_bbox=bbox,
        expected_append_failure="resource_rebound",
    )


def _fixture_dirty_gs() -> ZOrderFixture:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    stream = (
        b"BT /F0 12 Tf 72 694 Td (" + TARGET_TEXT.encode() + b") Tj ET "
        b"0.8 0 0 rg 2 w"
    )
    stream_xref = _new_content(doc, page, stream)
    font_xref = _new_font(doc, FONT_OBJ_HELV)
    _set_resources(doc, page, font_xref=font_xref, font_name="F0")
    show = _find_show(doc, page, TARGET_TEXT)
    bbox = _bbox_for_text(page, TARGET_TEXT)
    assert bbox is not None
    return ZOrderFixture(
        name="dirty_gs", doc=doc, page=page, stream_xref=stream_xref,
        font_xref=font_xref, font_resource="F0", show=show, target_bbox=bbox,
        expected_append_failure="graphics_state_bleed",
    )


_FIXTURE_BUILDERS = (
    _fixture_under_rect,
    _fixture_clip,
    _fixture_transparency,
    _fixture_ocg,
    _fixture_resource_collision,
    _fixture_dirty_gs,
)


def _apply_append_strategy(fx: ZOrderFixture) -> None:
    """The naive Tier-1 'append' candidate under evaluation.

    Erases the source op (the one already-proven primitive), then draws
    the replacement in a brand-new content stream tacked onto the end of
    the page's content array, in its own throwaway ``q``/``Q`` -- which
    cannot reinstate the source's clip path, cannot re-enter its BDC/EMC
    (OCG) scope, and (deliberately, to characterize the resource-identity
    hazard named in the plan) rebinds the SAME resource name the source
    used to a brand-new font object rather than choosing a free one.
    """
    doc, page = fx.doc, fx.page
    stream_bytes = doc.xref_stream(fx.stream_xref) or b""
    erase = build_advance_preserving_erase(
        stream_bytes, fx.show, _advance_from_show(fx)
    )
    patchset = PatchSet(
        page_xref=page.xref,
        replacements=(erase,),
        expected_page_fingerprint=page_fingerprint(doc, page),
    )
    apply_patchset(doc, page, patchset)

    new_font_xref = _new_font(doc, FONT_OBJ_HELV_BOLD)
    # ``show.origin_user`` is the ORIGINAL show's own PDF-user-space (Td)
    # origin -- the only coordinate that is unambiguous across both the
    # rect-bbox fixtures (whose ``target_bbox`` is page-space, top-down)
    # and the glyph-bbox fixtures (also page-space): reusing it sidesteps
    # any bbox/user-space conversion entirely.
    x0, y0 = fx.show.origin_user
    append_stream = (
        b"q BT /" + fx.font_resource.encode() + b" 12 Tf "
        + f"{x0:.2f} {y0:.2f} Td".encode() + b" "
        + encode_literal_string(REPLACEMENT_TEXT.encode("latin-1"))
        + b" Tj ET Q"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, append_stream)
    contents = [*page.get_contents(), content_xref]
    doc.xref_set_key(
        page.xref, "Contents", "[" + " ".join(f"{c} 0 R" for c in contents) + "]"
    )
    kind, value = doc.xref_get_key(page.xref, "Resources")
    extra = ""
    if kind == "dict" and "/ExtGState" in value:
        gs_start = value.index("/ExtGState")
        extra = value[gs_start : value.rindex(">>")]
    elif kind == "dict" and "/Properties" in value:
        props_start = value.index("/Properties")
        extra = value[props_start : value.rindex(">>")]
    # naive: reuse (rebind) the source's own resource name for the NEW font,
    # with no collision check against the existing binding.
    doc.xref_set_key(
        page.xref, "Resources",
        f"<< /Font << /{fx.font_resource} {new_font_xref} 0 R >> {extra} >>",
    )


def _apply_transplant_strategy(fx: ZOrderFixture) -> None:
    """Splice the replacement op at the SOURCE op's exact byte position."""
    doc, page = fx.doc, fx.page
    stream_bytes = doc.xref_stream(fx.stream_xref) or b""
    new_op = (
        encode_literal_string(REPLACEMENT_TEXT.encode("latin-1")) + b" Tj"
    )
    replacement = build_transplant_replacement(stream_bytes, fx.show, new_op)
    patchset = PatchSet(
        page_xref=page.xref,
        replacements=(replacement,),
        expected_page_fingerprint=page_fingerprint(doc, page),
    )
    apply_patchset(doc, page, patchset)


def test_append_strategy_verdict_fails_zorder_and_gs_bleed_and_transplant_verdict_passes():
    for build_fixture in _FIXTURE_BUILDERS:
        # -------------------------------------------------------- append
        fx = build_fixture()
        pre_state = _capture_state(fx.doc, fx.page, fx.target_bbox)
        _apply_append_strategy(fx)
        append_verdict = verify_tier1_strategy(
            fx.doc, fx.page, pre_state,
            target_bbox=fx.target_bbox,
            expected_text=REPLACEMENT_TEXT,
            strategy="append",
        )
        assert isinstance(append_verdict, StrategyVerdict), fx.name
        assert append_verdict.passed is False, (fx.name, append_verdict.failures)
        assert append_verdict.failures, (fx.name, "no failure reasons recorded")
        if fx.expected_append_failure is not None:
            assert fx.expected_append_failure in append_verdict.failures, (
                fx.name, append_verdict.failures,
            )
        fx.doc.close()

        # ----------------------------------------------------- transplant
        fx2 = build_fixture()
        pre_state2 = _capture_state(fx2.doc, fx2.page, fx2.target_bbox)
        _apply_transplant_strategy(fx2)
        transplant_verdict = verify_tier1_strategy(
            fx2.doc, fx2.page, pre_state2,
            target_bbox=fx2.target_bbox,
            expected_text=REPLACEMENT_TEXT,
            strategy="transplant",
        )
        assert isinstance(transplant_verdict, StrategyVerdict), fx2.name
        assert transplant_verdict.passed is True, (
            fx2.name, transplant_verdict.failures,
        )
        assert transplant_verdict.evidence, (fx2.name, "no evidence recorded")
        fx2.doc.close()


# ==================================================== Step 3: font honesty


def test_extracted_face_textwriter_outcome_is_validated_face_embedded_not_reuse():
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    courier = fitz.Font("cour")
    source_font_xref = page.insert_font(
        fontname="F1", fontbuffer=courier.buffer, set_simple=True
    )
    stream = b"BT /F1 12 Tf 72 700 Td (SOURCE) Tj ET"
    _new_content(doc, page, stream)

    registry = DocumentFontRegistry(doc)
    capability = registry.capability(page, "F1")
    assert capability is not None
    assert capability.face_source == "extracted"
    assert capability.embedded is True

    # Positive control, taken BEFORE any rebuild happens: the untouched
    # resource genuinely proves reuse -- this is what makes the later
    # refusal meaningful rather than a function that always says no.
    assert (
        prove_source_resource_reuse(
            doc, page, resource_name="F1", source_font_xref=source_font_xref
        )
        is True
    )

    fonts_before = tuple(page.get_fonts(full=True))

    # Simulate the Tier-1 "rebuild with validated face" prototype: the
    # extracted bytes are re-embedded as a NEW font object under a NEW
    # resource name, exactly as a genuine rebuild (not a byte-for-byte
    # reuse) would have to. (``page.insert_font`` deduplicates identical
    # font-program bytes onto the SAME xref -- an empirically confirmed
    # PyMuPDF behavior -- so the new object is created directly, the same
    # way every other fixture in this file authors its resources.)
    _, _, _, extracted_buffer = doc.extract_font(source_font_xref)
    assert extracted_buffer  # sanity: extraction actually produced bytes
    written_font_xref = doc.get_new_xref()
    doc.update_object(written_font_xref, doc.xref_object(source_font_xref))

    kind, value = doc.xref_get_key(page.xref, "Resources")
    assert kind == "xref"
    resources_xref = int(value.split()[0])
    font_kind, font_dict = doc.xref_get_key(resources_xref, "Font")
    assert font_kind == "dict" and font_dict.endswith(">>")
    doc.xref_set_key(
        resources_xref, "Font",
        font_dict[:-2] + f"/F2 {written_font_xref} 0 R>>",
    )

    fonts_after = tuple(page.get_fonts(full=True))
    assert len(fonts_after) == len(fonts_before) + 1
    assert written_font_xref != source_font_xref

    outcome = build_tier1_font_outcome(
        doc, page,
        resource_name="F2",
        source_font_xref=source_font_xref,
        written_font_xref=written_font_xref,
    )
    assert isinstance(outcome, FontOutcome)
    assert outcome.resource_name == "F2"
    assert outcome.source_font_xref == source_font_xref
    assert outcome.written_font_xref == written_font_xref
    assert outcome.action == FontResourceAction.VALIDATED_FACE_EMBEDDED

    # The honesty gate itself: SOURCE_RESOURCE_REUSED is refused here
    # because a fresh font object now sits under this resource name.
    assert (
        prove_source_resource_reuse(
            doc, page, resource_name="F2", source_font_xref=source_font_xref
        )
        is False
    )
