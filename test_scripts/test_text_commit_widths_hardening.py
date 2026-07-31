"""Review-driven hardening of the /Widths advance source.

Three defects found by independent review of the /Widths change, each pinned
here before it was fixed:

* **Glyph coverage was bypassed for width-only capabilities.**  ``/Widths``
  proves an *advance*, not a *glyph*.  A subset font routinely declares widths
  across its whole ``[FirstChar, LastChar]`` range while carrying only a
  handful of outlines, so trusting the table as glyph evidence lets Tier 0
  commit text that renders as tofu.  V0a-V0e cannot catch it either: raster
  identity is asserted *outside* a 2pt halo around the target, so a tofu box
  inside the edit region is invisible to verification.  The plan requires
  "replacement glyphs exist in the source font encoding" as its own gate.
* **A dangling ``/Widths`` reference crashed classification.**  The unguarded
  ``xref_object`` raised ``RuntimeError`` out through ``engine.prepare`` and
  through the per-keystroke preview worker, where the pre-change code had
  returned a clean rejection.
* **The advance tolerance silently absorbed a full width unit.**  With
  face-derived floats ``1e-3 * size`` absorbed rounding; with ``/Widths`` one
  table unit *is* ``size/1000``, so the smallest representable difference
  landed exactly on the ``>`` boundary and float representation decided the
  outcome -- committing a measured 0.600pt shift at size 600.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)


def _doc(
    *,
    basefont: str = "ArialMT",
    target: str = "AB",
    font_size: float = 12.0,
    widths: dict[int, float] | None = None,
    widths_src: str | None = None,
    first_char: int = 32,
    last_char: int = 126,
    symbolic: bool | str = False,
    encoding: str = "WinAnsiEncoding",
    indirect_char_range: bool = False,
) -> fitz.Document:
    """One page, one literal-Tj stream, one unembedded simple font."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref,
        f"BT /F1 {font_size:g} Tf 72 700 Td (".encode()
        + target.encode()
        + b") Tj ET",
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")

    if widths_src is None:
        table = [(widths or {}).get(c, 500.0) for c in range(first_char, last_char + 1)]
        widths_src = "[" + " ".join(f"{w:g}" for w in table) + "]"
    descriptor = ""
    if symbolic == "decoy":
        # A string value that contains "/Flags" ahead of the real key: a
        # regex over the serialised descriptor matches inside the string.
        descriptor = (
            " /FontDescriptor << /Type /FontDescriptor "
            "/FontFamily (/Flags 0) /Flags 4 >>"
        )
    elif symbolic == "inline_indirect_flags":
        flags_xref = doc.get_new_xref()
        while flags_xref & 4:
            flags_xref = doc.get_new_xref()
        doc.update_object(flags_xref, "4")
        descriptor = (
            f" /FontDescriptor << /Type /FontDescriptor "
            f"/Flags {flags_xref} 0 R >>"
        )
    elif symbolic == "indirect_flags":
        # Force an object number WITHOUT bit 3 set. A reader that pattern
        # matches the raw descriptor text captures the xref number instead of
        # the flag value, and would otherwise be rescued at random by whichever
        # number the allocator happened to hand out.
        flags_xref = doc.get_new_xref()
        while flags_xref & 4:
            flags_xref = doc.get_new_xref()
        doc.update_object(flags_xref, "4")
        descriptor_xref = doc.get_new_xref()
        doc.update_object(
            descriptor_xref,
            f"<< /Type /FontDescriptor /FontName /{basefont} "
            f"/Flags {flags_xref} 0 R >>",
        )
        descriptor = f" /FontDescriptor {descriptor_xref} 0 R"
    elif symbolic == "direct":
        # A descriptor stored inline rather than as an indirect object.
        descriptor = (
            f" /FontDescriptor << /Type /FontDescriptor "
            f"/FontName /{basefont} /Flags 4 >>"
        )
    elif symbolic:
        descriptor_xref = doc.get_new_xref()
        doc.update_object(
            descriptor_xref,
            f"<< /Type /FontDescriptor /FontName /{basefont} /Flags 4 >>",
        )
        descriptor = f" /FontDescriptor {descriptor_xref} 0 R"
    first_src, last_src = str(first_char), str(last_char)
    if indirect_char_range:
        fc_xref = doc.get_new_xref()
        doc.update_object(fc_xref, str(first_char))
        lc_xref = doc.get_new_xref()
        doc.update_object(lc_xref, str(last_char))
        first_src, last_src = f"{fc_xref} 0 R", f"{lc_xref} 0 R"
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /TrueType "
        f"/BaseFont /{basefont} /Encoding /{encoding} "
        f"/FirstChar {first_src} /LastChar {last_src} /Widths {widths_src}"
        f"{descriptor} >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _plan(doc: fitz.Document, target: str, replacement: str):
    page = doc[0]
    return prepare_tier0_plan(
        doc,
        page,
        target_text=target,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )


# ------------------------------------------------ 1. glyph coverage (Codex P1)


def test_subset_font_without_a_face_cannot_prove_glyphs_from_widths():
    """A subset font's /Widths range is not its glyph set.

    ``ABCDEF+ArialMT`` has no embedded program here and no face resolves, so
    nothing in the document can attest that the replacement's glyphs exist.
    ``/Widths`` covering the code proves only that the code has an advance.
    Committing anyway would paint tofu inside the one region V0a-V0e does not
    inspect.
    """
    doc = _doc(basefont="ABCDEF+ArialMT", target="AB")
    capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
    assert capability is not None
    assert capability.face is None, "fixture must have no face to interrogate"

    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PlanRejection), (
        f"subset font with no face must not be trusted for glyphs: {result}"
    )
    doc.close()


def test_unembedded_full_font_without_a_face_still_plans():
    """The widening must survive the fix.

    A non-subset unembedded font is rendered through a viewer-substituted
    complete face, and Tier 0 restricts replacements to printable ASCII, which
    any substitute covers.  That is the population the /Widths work exists to
    unlock, so it must keep working.
    """
    doc = _doc(basefont="ArialMT", target="AB")
    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PreparedEdit), result
    doc.close()


def test_unrecognised_unembedded_family_cannot_prove_glyphs():
    """Absence of a subset prefix is not glyph evidence.

    An unembedded font with an unfamiliar name may be symbolic or sparse — a
    barcode, icon, or dingbat face.  On a machine where it *is* installed the
    viewer uses the real font, not a substitute, so a positive ``/Widths``
    entry for an ASCII code it never draws renders ``.notdef``.  Only a closed
    set of standard full-ASCII text families is safe to assume.
    """
    doc = _doc(basefont="AcmeBarcode-Regular", target="AB")
    capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
    assert capability is not None
    assert capability.face is None, "fixture must have no face to interrogate"

    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PlanRejection), (
        f"unrecognised unembedded family must not be trusted for glyphs: {result}"
    )
    doc.close()


def test_symbolic_flagged_font_cannot_prove_glyphs():
    """A /FontDescriptor that declares Symbolic refuses even a known family.

    The document itself is saying the font does not use the standard Latin
    character set, so its ASCII widths prove nothing about ASCII glyphs.
    """
    doc = _doc(basefont="ArialMT", target="AB", symbolic=True)
    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PlanRejection), (
        f"symbolic-flagged font must not be trusted for glyphs: {result}"
    )
    doc.close()


def test_symbolic_flag_in_a_direct_descriptor_is_also_honoured():
    """``/FontDescriptor`` may be an inline dict, not only an indirect ref.

    Reading only the indirect form silently skips the flag and re-opens the
    tofu path for exactly the fonts the check exists to catch.
    """
    doc = _doc(basefont="ArialMT", target="AB", symbolic="direct")
    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PlanRejection), (
        f"inline symbolic descriptor must be honoured: {result}"
    )
    doc.close()


def test_symbolic_flag_behind_an_indirect_reference_is_resolved():
    """``/Flags`` may itself be an indirect reference.

    Pattern-matching the raw descriptor text then reads the *xref number*
    rather than the flag value, so a symbolic font whose object number happens
    to lack bit 3 is attested as ASCII-complete.
    """
    doc = _doc(basefont="ArialMT", target="AB", symbolic="indirect_flags")
    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PlanRejection), (
        f"indirect /Flags must be dereferenced before testing Symbolic: {result}"
    )
    doc.close()


def test_standard_encoding_quote_slots_are_not_assumed_ascii():
    """StandardEncoding disagrees with ASCII at 0x27 and 0x60.

    ``encode_simple`` admits Standard, WinAnsi and MacRoman on the premise
    that printable ASCII maps identically in all three.  It does not:
    StandardEncoding selects ``quoteright`` at 0x27 and ``quoteleft`` at
    0x60, where WinAnsi has ``quotesingle`` and ``grave``.  Committing the
    byte anyway paints a curly quote where a straight one was typed.
    """
    doc = _doc(basefont="ArialMT", target="AB", encoding="StandardEncoding")
    result = _plan(doc, "AB", "A'")
    assert isinstance(result, PlanRejection), (
        f"0x27 under StandardEncoding is not the ASCII apostrophe: {result}"
    )
    doc.close()


def test_indirect_first_and_last_char_are_resolved():
    """Scalar dictionary values may be indirect too.

    Treating an indirect ``/FirstChar`` as malformed refuses a perfectly
    valid width table, in a reader that already dereferences an indirect
    ``/Widths`` array.
    """
    doc = _doc(basefont="ArialMT", target="AB", indirect_char_range=True)
    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PreparedEdit), (
        f"indirect /FirstChar//LastChar is valid PDF: {result}"
    )
    doc.close()


def test_oversized_widths_array_is_rejected_without_building_it():
    """A simple font declares at most 256 widths; refuse before converting.

    Capability classification runs in the per-keystroke preview path, so a
    hostile or corrupt array must not be tokenised in full first.
    """
    doc = _doc(widths_src="[" + " ".join(["500"] * 100_000) + "]")
    capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
    assert capability is not None
    assert capability.tier0_reject_reason == RejectReason.FONT_WIDTHS_INCOMPLETE
    assert capability.widths is None or len(capability.widths) <= 256
    doc.close()


def test_page_fingerprint_covers_the_width_table():
    """Editing /Widths must invalidate a prepared plan.

    ``page.get_fonts(full=True)`` returns the same metadata tuple whether or
    not the width table changed, so a fingerprint built only from it would
    call a plan fresh while the advance it was measured against has moved.
    """
    doc = _doc(basefont="ArialMT", target="AB")
    page = doc[0]
    before = page_fingerprint(doc, page)

    font_xref = next(
        int(e[0]) for e in page.get_fonts(full=True) if e[4] == "F1"
    )
    widths = "[" + " ".join(["999"] * (126 - 32 + 1)) + "]"
    doc.xref_set_key(font_xref, "Widths", widths)

    assert page_fingerprint(doc, page) != before, (
        "a changed /Widths table must change the page fingerprint"
    )
    doc.close()


def test_page_fingerprint_covers_indirect_font_dependencies():
    """Every indirect object capability classification reads must be hashed.

    Following ``/Widths`` alone is not enough: ``/FirstChar``, ``/LastChar``,
    ``/Encoding`` and the ``/FontDescriptor`` (whose ``/Flags`` carries the
    glyph-repertoire attestation) may each be an indirect object whose
    *content* changes while the reference in the font dictionary stays
    byte-identical.  Editing ``/FirstChar`` re-maps every code to a different
    width, so a plan prepared beforehand is measured under other semantics.
    """
    doc = _doc(basefont="ArialMT", target="AB", indirect_char_range=True)
    page = doc[0]
    before = page_fingerprint(doc, page)

    font_xref = next(int(e[0]) for e in page.get_fonts(full=True) if e[4] == "F1")
    kind, value = doc.xref_get_key(font_xref, "FirstChar")
    assert kind == "xref", "fixture must store /FirstChar indirectly"
    doc.update_object(int(value.split()[0]), "33")

    assert page_fingerprint(doc, page) != before, (
        "a changed indirect /FirstChar must change the page fingerprint"
    )
    doc.close()


def test_flags_are_read_as_a_dictionary_key_not_as_text():
    """A string value containing "/Flags" must not be mistaken for the key.

    ``/FontFamily (/Flags 0)`` sits ahead of the real ``/Flags 4``; pattern
    matching the serialised descriptor reads the decoy and attests a symbolic
    font as ASCII-complete.  Dictionary lookup is not fooled.
    """
    doc = _doc(basefont="ArialMT", target="AB", symbolic="decoy")
    result = _plan(doc, "AB", "BA")
    assert isinstance(result, PlanRejection), (
        f"/Flags must be read as a key, not matched in raw text: {result}"
    )
    doc.close()


def test_page_fingerprint_covers_indirect_flags_in_an_inline_descriptor():
    """The two descriptor shapes combine: inline dict, indirect ``/Flags``.

    The glyph-repertoire attestation lives in that object, so changing it
    from nonsymbolic to symbolic must invalidate a prepared plan.
    """
    doc = _doc(basefont="ArialMT", target="AB", symbolic="inline_indirect_flags")
    page = doc[0]
    before = page_fingerprint(doc, page)

    font_xref = next(int(e[0]) for e in page.get_fonts(full=True) if e[4] == "F1")
    kind, value = doc.xref_get_key(font_xref, "FontDescriptor/Flags")
    assert kind == "xref", "fixture must store /Flags indirectly"
    doc.update_object(int(value.split()[0]), "32")

    assert page_fingerprint(doc, page) != before, (
        "a changed indirect /Flags must change the page fingerprint"
    )
    doc.close()


def test_direct_font_resource_dictionary_refuses_instead_of_raising():
    """A font dictionary stored inline in /Resources reports xref 0.

    Every ``xref_get_key``/``xref_object`` call against 0 raises, so the
    readers must refuse rather than let the exception escape capability
    classification and the per-keystroke prepare/preview path.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, b"BT /F1 12 Tf 72 700 Td (AB) Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    widths = "[" + " ".join(["500"] * 95) + "]"
    doc.xref_set_key(
        page.xref,
        "Resources",
        "<< /Font << /F1 << /Type /Font /Subtype /TrueType "
        "/BaseFont /ArialMT /Encoding /WinAnsiEncoding "
        f"/FirstChar 32 /LastChar 126 /Widths {widths} >> >> >>",
    )
    try:
        registry = DocumentFontRegistry(doc)
        capability = registry.capability(doc[0], "F1")  # must not raise
        if capability is not None:
            assert capability.tier0_reject_reason is not None

        result = _plan(doc, "AB", "BA")  # must not raise
        assert isinstance(result, PlanRejection), result
    finally:
        doc.close()


# -------------------------------------------- 2. dangling /Widths (Codex P2)


def test_dangling_widths_reference_refuses_instead_of_raising():
    """An unresolvable /Widths must classify as malformed, never escape.

    The pre-change code returned a clean rejection for this document; the
    regression raised ``RuntimeError`` out through ``engine.prepare`` and the
    per-keystroke preview worker.
    """
    doc = _doc(widths_src="9999 0 R")
    try:
        capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
        assert capability is not None
        assert capability.tier0_reject_reason is not None

        result = _plan(doc, "AB", "BA")
        assert isinstance(result, PlanRejection), result
    finally:
        doc.close()


# ------------------------------------------------------- 3. advance tolerance


def test_one_width_unit_difference_is_not_absorbed_at_large_sizes():
    """One /Widths unit is a real shift, not rounding.

    ``A``->``B`` differs by exactly one table unit; at size 600 that is a
    0.600pt layout shift, which Tier 0 -- whose entire promise is preserved
    advance -- must refuse rather than absorb.
    """
    doc = _doc(target="A", font_size=600.0, widths={ord("A"): 667.0, ord("B"): 668.0})
    result = _plan(doc, "A", "B")
    assert isinstance(result, PlanRejection), (
        f"0.600pt shift must not be absorbed as rounding: {result}"
    )
    assert result.reason == RejectReason.ADVANCE_MISMATCH
    doc.close()


def test_genuinely_equal_widths_still_plan_at_large_sizes():
    """Tightening the tolerance must not reject a truly neutral swap."""
    doc = _doc(target="A", font_size=600.0, widths={ord("A"): 667.0, ord("B"): 667.0})
    result = _plan(doc, "A", "B")
    assert isinstance(result, PreparedEdit), result
    doc.close()
