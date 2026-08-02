"""Red-light tests: Tier 0 advance comes from the PDF's own /Widths array.

For a *simple* (non-CID) PDF font, /Widths is the layout contract: a
conforming viewer computes the horizontal advance of code ``c`` as
``Widths[c - FirstChar] / 1000 * font_size`` and does **not** consult the
embedded font program's metrics.  The engine previously measured advance
with ``FontCapability.face.text_length()``, which

* refused every unembedded non-base-14 font outright (no face resolvable
  => ``FONT_FACE_UNAVAILABLE``), even though its /Widths table carried
  the full advance contract, and
* on a machine where a *system* face happened to resolve, proved
  equal-advance against that face's metrics rather than the document's
  declared widths — the wrong number whenever the two disagree.

The discriminating tests here deliberately declare widths that contradict
the real typeface (uniform 1000, or a widened digit) and pin the accepted
/ rejected outcome to *those* widths.  They cannot pass by accident via a
resolved system face, and they are machine-independent: the Helvetica
fixtures always resolve a base-14 face, so acceptance there is explicable
only by /Widths winning over an available face.

Fixtures use the same raw xref surgery as
``test_text_commit_tier0._tier0_doc`` / ``test_text_commit_structural_gates
._stream_doc``, and plan with ``expected_origin=None, target_bbox=None`` so
the assertions never depend on MuPDF's own rendering/substitution of an
unembedded font.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import (  # noqa: E402
    DocumentFontRegistry,
    FontCapability,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)

TARGET = "Price 2024"
SAME_LEN = "Price 2025"  # same length: advance-neutral under uniform widths
WIDE_W = "Price 2W24"  # helv 'W' >> '0'; uniform /Widths makes it neutral
LONGER = "Price 20245"  # one glyph more: never advance-neutral
OUT_OF_RANGE = "Price 202~"  # '~' == 0x7E, above a LastChar of 'z'

_ARIAL = ("ArialMT", "TrueType")  # unembedded, non-base-14: no face resolves
_HELV = ("Helvetica", "Type1")  # base-14: a real face IS available


# ------------------------------------------------------------------ fixtures


def _widths_src(
    first_char: int,
    last_char: int,
    default: float,
    overrides: dict[str, float] | None = None,
) -> str:
    """A PDF array source string covering ``[first_char, last_char]``."""
    values = [default] * (last_char - first_char + 1)
    for char, width in (overrides or {}).items():
        values[ord(char) - first_char] = width
    return "[" + " ".join(f"{v:g}" for v in values) + "]"


def _widths_doc(
    *,
    basefont_subtype: tuple[str, str] = _ARIAL,
    encoding: str = "WinAnsiEncoding",
    first_char: int = 32,
    last_char: int = 126,
    default: float = 1000.0,
    overrides: dict[str, float] | None = None,
    widths_src: str | None = None,
    indirect_widths: bool = False,
    include_widths: bool = True,
    missing_width: float | None = None,
    target: str = TARGET,
) -> fitz.Document:
    """One page, one raw literal-Tj stream, one simple font with /Widths."""
    basefont, subtype = basefont_subtype
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref,
        b"BT /F1 12 Tf 72 700 Td (" + target.encode() + b") Tj ET",
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")

    entries = [
        "/Type /Font",
        f"/Subtype /{subtype}",
        f"/BaseFont /{basefont}",
        f"/Encoding /{encoding}",
    ]
    if include_widths:
        source = (
            widths_src
            if widths_src is not None
            else _widths_src(first_char, last_char, default, overrides)
        )
        if indirect_widths:
            widths_xref = doc.get_new_xref()
            doc.update_object(widths_xref, source)
            source = f"{widths_xref} 0 R"
        entries += [
            f"/FirstChar {first_char}",
            f"/LastChar {last_char}",
            f"/Widths {source}",
        ]
    if missing_width is not None:
        descriptor_xref = doc.get_new_xref()
        doc.update_object(
            descriptor_xref,
            f"<< /Type /FontDescriptor /FontName /{basefont} "
            f"/Flags 32 /MissingWidth {missing_width:g} >>",
        )
        entries.append(f"/FontDescriptor {descriptor_xref} 0 R")

    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, "<< " + " ".join(entries) + " >>")
    doc.xref_set_key(
        page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>"
    )
    return doc


def _capability(doc: fitz.Document) -> FontCapability:
    capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
    assert capability is not None, "fixture must expose /F1 on the page"
    return capability


def _sole_capability(doc: fitz.Document) -> FontCapability:
    """The page's only font capability, whatever resource name it carries."""
    capabilities = DocumentFontRegistry(doc).page_capabilities(doc[0])
    assert len(capabilities) == 1, f"expected one font, got {list(capabilities)}"
    return next(iter(capabilities.values()))


def _plan(
    doc: fitz.Document, replacement: str, target: str = TARGET
) -> PreparedEdit | PlanRejection:
    """Plan, asserting the planner left the live document untouched."""
    page = doc[0]
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()
    result = prepare_tier0_plan(
        doc,
        page,
        target_text=target,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )
    assert page_fingerprint(doc, page) == fingerprint_before  # read-only
    assert doc.xref_length() == xrefs_before
    return result


def _assert_rejects(
    doc: fitz.Document, replacement: str, reason: str, target: str = TARGET
) -> PlanRejection:
    rejection = _plan(doc, replacement, target=target)
    assert isinstance(rejection, PlanRejection), f"expected refusal, got {rejection}"
    assert rejection.reason == reason, rejection
    return rejection


# ------------------------------------- the unembedded font that was refused


def test_unembedded_simple_font_with_complete_widths_plans_tier0():
    """The 76.6% cohort: no face resolves, but /Widths carries the contract."""
    doc = _widths_doc()
    capability = _capability(doc)

    # The fixture really is the refused profile: unembedded, non-base-14,
    # so no face resolves on any machine — yet it is now Tier 0 usable.
    assert capability.basefont == "ArialMT"
    assert capability.subtype == "TrueType"
    assert capability.embedded is False
    assert capability.face is None
    assert capability.face_source == "none"  # never pretends a face exists
    assert capability.advance_source == "widths"
    assert capability.supports_simple_encoding is True
    assert capability.tier0_reject_reason is None

    prepared = _plan(doc, SAME_LEN)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.replacement.expected_bytes == b"(" + TARGET.encode() + b")"
    assert prepared.replacement.replacement_bytes == b"(" + SAME_LEN.encode() + b")"
    assert prepared.font_xref == capability.font_xref
    assert prepared.token
    doc.close()


def test_indirect_widths_array_is_resolved():
    """/Widths may be an indirect reference, not just an inline array."""
    doc = _widths_doc(indirect_widths=True)
    capability = _capability(doc)
    assert capability.advance_source == "widths"
    assert capability.tier0_reject_reason is None

    prepared = _plan(doc, SAME_LEN)
    assert isinstance(prepared, PreparedEdit), prepared
    doc.close()


# ------------------------------- /Widths beats an *available* face (the proof)


def test_advance_follows_widths_not_the_resolved_face_when_widths_permit():
    """Declared widths make a helv-mismatched replacement advance-neutral.

    ``test_text_commit_tier0`` pins ``Price 2W24`` as ADVANCE_MISMATCH for a
    Helvetica font with no /Widths, because helv's 'W' is far wider than a
    digit.  The identical replacement against the identical basefont must be
    ACCEPTED here purely because this font declares every code 1000/1000.
    A base-14 face is available and would still say mismatch, so acceptance
    is explicable only by /Widths overriding it.
    """
    doc = _widths_doc(basefont_subtype=_HELV, default=1000.0)
    capability = _capability(doc)
    assert capability.face is not None, "a base-14 face must be available"
    assert capability.face_source == "base14"  # face_source stays about faces
    assert capability.advance_source == "widths"  # ...advance does not

    # The face genuinely disagrees: this is what makes the test discriminating.
    assert capability.face.text_length(WIDE_W, fontsize=12.0) != (
        capability.face.text_length(TARGET, fontsize=12.0)
    )

    prepared = _plan(doc, WIDE_W)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.replacement.replacement_bytes == b"(" + WIDE_W.encode() + b")"
    doc.close()


def test_advance_follows_widths_not_the_resolved_face_when_widths_refuse():
    """The converse: widths that contradict a face-equal pair must refuse.

    helv digits are all the same width, so ``Price 2024 -> Price 2025`` is
    advance-neutral under face metrics (``test_text_commit_tier0`` accepts
    exactly that).  Declaring '5' wider must flip it to ADVANCE_MISMATCH.
    """
    doc = _widths_doc(
        basefont_subtype=_HELV, default=500.0, overrides={"5": 800.0}
    )
    capability = _capability(doc)
    assert capability.face is not None
    assert capability.advance_source == "widths"
    # Face metrics would accept: the two strings measure equal under helv.
    assert capability.face.text_length(SAME_LEN, fontsize=12.0) == (
        capability.face.text_length(TARGET, fontsize=12.0)
    )

    rejection = _assert_rejects(doc, SAME_LEN, RejectReason.ADVANCE_MISMATCH)
    assert "advance" in rejection.detail
    doc.close()


def test_length_changing_replacement_still_rejects_under_uniform_widths():
    """Uniform widths must not become a licence to change glyph count."""
    doc = _widths_doc(default=1000.0)
    _assert_rejects(doc, LONGER, RejectReason.ADVANCE_MISMATCH)
    doc.close()


# --------------------------------------- incomplete widths: refuse, not guess


def test_replacement_code_above_last_char_refuses_with_stable_reason():
    doc = _widths_doc(first_char=32, last_char=ord("z"))
    capability = _capability(doc)
    assert capability.advance_source == "widths"
    assert capability.uncovered_codes(TARGET) == ""  # source is fully covered
    assert capability.uncovered_codes(OUT_OF_RANGE) == "~"

    _assert_rejects(doc, OUT_OF_RANGE, RejectReason.FONT_WIDTHS_INCOMPLETE)
    doc.close()


def test_source_code_below_first_char_refuses_with_stable_reason():
    """Coverage is proven for the *source* too, not only the replacement."""
    doc = _widths_doc(first_char=ord("0"), last_char=126)
    capability = _capability(doc)
    assert " " in capability.uncovered_codes(TARGET)  # space == 0x20 < '0'

    _assert_rejects(doc, SAME_LEN, RejectReason.FONT_WIDTHS_INCOMPLETE)
    doc.close()


def test_missing_width_is_never_silently_substituted():
    """/MissingWidth must not paper over an out-of-range code."""
    doc = _widths_doc(first_char=32, last_char=ord("z"), missing_width=1000.0)
    _assert_rejects(doc, OUT_OF_RANGE, RejectReason.FONT_WIDTHS_INCOMPLETE)
    doc.close()


def test_widths_array_shorter_than_declared_range_refuses():
    """len(Widths) != LastChar - FirstChar + 1 is a malformed table."""
    doc = _widths_doc(
        first_char=32, last_char=255, widths_src="[" + " ".join(["500"] * 10) + "]"
    )
    capability = _capability(doc)
    assert capability.tier0_reject_reason == RejectReason.FONT_WIDTHS_INCOMPLETE
    assert capability.supports_simple_encoding is False

    _assert_rejects(doc, SAME_LEN, RejectReason.FONT_WIDTHS_INCOMPLETE)
    doc.close()


def test_widths_array_with_indirect_element_refuses():
    """An element that is itself an indirect ref is not a parseable width."""
    doc = _widths_doc(
        first_char=32, last_char=34, widths_src="[500 9 0 R 500]"
    )
    capability = _capability(doc)
    assert capability.tier0_reject_reason == RejectReason.FONT_WIDTHS_INCOMPLETE
    doc.close()


def test_zero_width_in_range_is_not_treated_as_provable():
    """A declared 0 for a printable code is producer sloppiness, not proof.

    Real corpus fonts declare 0 for codes they never used.  Trusting them
    would make this pair 'equal advance' (both sides 9*500 + 0) and accept a
    replacement whose real advance is unknown, so an in-range zero must be
    refused rather than believed.
    """
    doc = _widths_doc(default=500.0, overrides={"4": 0.0, "5": 0.0})
    capability = _capability(doc)
    assert capability.uncovered_codes(TARGET) == "4"
    assert capability.uncovered_codes(SAME_LEN) == "5"

    _assert_rejects(doc, SAME_LEN, RejectReason.FONT_WIDTHS_INCOMPLETE)
    doc.close()


# ------------------------------------------------------- no-regression guards


def test_font_without_widths_still_measures_with_the_face():
    """Absent /Widths, the base-14 face remains the advance source."""
    doc = _widths_doc(basefont_subtype=_HELV, include_widths=False)
    capability = _capability(doc)
    assert capability.face is not None
    assert capability.face_source == "base14"
    assert capability.advance_source == "face"
    assert capability.tier0_reject_reason is None

    prepared = _plan(doc, SAME_LEN)  # helv digits are equal width
    assert isinstance(prepared, PreparedEdit), prepared
    # ...and the face's own verdict still governs the mismatch case.
    doc.close()
    doc = _widths_doc(basefont_subtype=_HELV, include_widths=False)
    _assert_rejects(doc, WIDE_W, RejectReason.ADVANCE_MISMATCH)
    doc.close()


def test_unembedded_font_without_widths_or_face_still_refuses():
    """No face and no /Widths: nothing can prove the advance."""
    doc = _widths_doc(include_widths=False)
    capability = _capability(doc)
    assert capability.face is None
    assert capability.advance_source == "none"
    assert capability.tier0_reject_reason == RejectReason.FONT_FACE_UNAVAILABLE

    _assert_rejects(doc, SAME_LEN, RejectReason.FONT_FACE_UNAVAILABLE)
    doc.close()


def test_embedded_font_still_uses_its_extracted_face():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    writer = fitz.TextWriter(page.rect)
    writer.append((72, 100), "Alpha embedded", font=fitz.Font("helv"), fontsize=12)
    writer.write_text(page)

    capability = _sole_capability(doc)
    assert capability.embedded is True
    assert capability.face is not None
    assert capability.face_source == "extracted"  # unchanged provenance
    assert capability.advance_source == "face"  # a Type0 dict has /W, not /Widths
    doc.close()


def test_type3_still_refuses_even_with_a_widths_array():
    """Type3 /Widths are in glyph space: they must not rescue the font."""
    doc = _widths_doc(basefont_subtype=("MyType3", "Type3"))
    capability = _capability(doc)
    assert capability.subtype == "Type3"
    assert capability.tier0_reject_reason == RejectReason.FONT_TYPE3
    assert capability.face is None
    assert capability.supports_simple_encoding is False
    # /Widths is never even read for Type3: its entries are glyph-space
    # units scaled by /FontMatrix, not 1/1000 text-space units.
    assert capability.advance_source == "none"

    _assert_rejects(doc, SAME_LEN, RejectReason.FONT_TYPE3)
    doc.close()


def test_identity_h_still_refuses_even_with_a_widths_array():
    """CID encodings stay deferred: byte<->code is not the simple mapping."""
    doc = _widths_doc(encoding="Identity-H")
    capability = _capability(doc)
    assert capability.encoding == "Identity-H"
    assert capability.supports_simple_encoding is False
    assert capability.tier0_reject_reason == (
        RejectReason.FONT_UNSUPPORTED_ENCODING
    )

    _assert_rejects(doc, SAME_LEN, RejectReason.FONT_UNSUPPORTED_ENCODING)
    doc.close()
