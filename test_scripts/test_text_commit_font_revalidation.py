"""Simple-font capability pull-revalidation (Task 13 correctness slice).

PITFALLS "Simple-font capabilities are served stale within a registry
generation": the cache key is ``(generation, owner, name, xref)`` and only
Type0 hits were digest-revalidated, so an in-place rewrite of a simple
font's /Widths, /Encoding, descriptor or program between two lookups in
one generation served the OLD capability.  Every cache hit must now
re-derive the evidence digest and rebuild on mismatch; an unchanged font
must keep returning the identical cached object (no per-lookup rebuild).
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import (  # noqa: E402
    DocumentFontRegistry,
    FontCapability,
)

_RANGE = (32, 126)


def _widths_src(default: float) -> str:
    first, last = _RANGE
    return "[" + " ".join(f"{default:g}" for _ in range(last - first + 1)) + "]"


def _simple_doc(
    *,
    default_width: float = 600.0,
    indirect_widths: bool = False,
    descriptor: bool = False,
    font_file: bytes | None = None,
) -> tuple[fitz.Document, int]:
    """One page, one unembedded (or fake-embedded) TrueType Arial with /Widths."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, b"BT /F1 12 Tf 72 700 Td (Hello) Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")

    source = _widths_src(default_width)
    if indirect_widths:
        widths_xref = doc.get_new_xref()
        doc.update_object(widths_xref, source)
        source = f"{widths_xref} 0 R"
    entries = [
        "/Type /Font",
        "/Subtype /TrueType",
        "/BaseFont /Arial",
        "/Encoding /WinAnsiEncoding",
        f"/FirstChar {_RANGE[0]}",
        f"/LastChar {_RANGE[1]}",
        f"/Widths {source}",
    ]
    if descriptor or font_file is not None:
        descriptor_entries = [
            "/Type /FontDescriptor",
            "/FontName /Arial",
            "/Flags 32",
        ]
        if font_file is not None:
            ff_xref = doc.get_new_xref()
            doc.update_object(ff_xref, "<<>>")
            doc.update_stream(ff_xref, font_file)
            descriptor_entries.append(f"/FontFile2 {ff_xref} 0 R")
        descriptor_xref = doc.get_new_xref()
        doc.update_object(descriptor_xref, "<< " + " ".join(descriptor_entries) + " >>")
        entries.append(f"/FontDescriptor {descriptor_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, "<< " + " ".join(entries) + " >>")
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc, font_xref


def _lookup(registry: DocumentFontRegistry, doc: fitz.Document) -> FontCapability:
    capability = registry.capability(doc[0], "F1")
    assert capability is not None
    return capability


def _indirect(doc: fitz.Document, xref: int, key: str) -> int:
    kind, value = doc.xref_get_key(xref, key)
    assert kind == "xref", (key, kind, value)
    return int(value.split()[0])


# --- registry behaviour ------------------------------------------------------


def test_unchanged_simple_font_reuses_the_cached_object():
    doc, _ = _simple_doc()
    registry = DocumentFontRegistry(doc)
    first = _lookup(registry, doc)
    assert first.supports_simple_encoding and first.advance_source == "widths"
    second = _lookup(registry, doc)
    assert second is first, "revalidation must not rebuild an unchanged font"
    assert len(registry._cache) == 1


def test_widths_rewrite_at_same_xref_rebuilds_the_capability():
    doc, font_xref = _simple_doc(default_width=600.0)
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.width_of_code(ord("H")) == 600.0
    doc.xref_set_key(font_xref, "Widths", _widths_src(250.0))
    after = _lookup(registry, doc)
    assert after is not before
    assert after.width_of_code(ord("H")) == 250.0
    assert registry.generation == 0, "pull-revalidation must not bump generation"


def test_indirect_widths_target_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc(default_width=600.0, indirect_widths=True)
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    widths_xref = _indirect(doc, font_xref, "Widths")
    doc.update_object(widths_xref, _widths_src(333.0))
    after = _lookup(registry, doc)
    assert after is not before
    assert after.width_of_code(ord("H")) == 333.0


def test_first_char_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc()
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    doc.xref_set_key(font_xref, "FirstChar", "33")  # table length now disagrees
    after = _lookup(registry, doc)
    assert after is not before
    assert after.tier0_reject_reason == RejectReason.FONT_WIDTHS_INCOMPLETE


def test_encoding_differences_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc()
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.tier0_reject_reason is None
    doc.xref_set_key(
        font_xref,
        "Encoding",
        "<< /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [65 /B] >>",
    )
    after = _lookup(registry, doc)
    assert after is not before
    assert after.tier0_reject_reason == RejectReason.FONT_CUSTOM_DIFFERENCES


def test_descriptor_flags_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc(descriptor=True)
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.ascii_repertoire_attested is True
    descriptor_xref = _indirect(doc, font_xref, "FontDescriptor")
    doc.xref_set_key(descriptor_xref, "Flags", "4")  # symbolic bit
    after = _lookup(registry, doc)
    assert after is not before
    assert after.ascii_repertoire_attested is False


def test_font_program_stream_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc(font_file=b"not-a-real-font-v1")
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.embedded is True
    descriptor_xref = _indirect(doc, font_xref, "FontDescriptor")
    ff_xref = _indirect(doc, descriptor_xref, "FontFile2")
    doc.update_stream(ff_xref, b"not-a-real-font-v2")
    after = _lookup(registry, doc)
    assert after is not before


def test_rejected_type0_is_revalidated_too():
    """Same bug class: a Type0 that FAILED the evidence chain has ``cid is
    None`` and was likewise served stale.  Revalidation must key on the
    font's subtype, not on whether the cached capability carries a codec."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.cid is None and before.tier0_reject_reason is not None
    assert _lookup(registry, doc) is before
    doc.xref_set_key(font_xref, "Encoding", "/Identity-V")
    after = _lookup(registry, doc)
    assert after is not before


def test_inline_font_dict_stays_a_stable_rejection():
    """An inline (xref 0) font resource has no readable evidence; the digest
    must be a constant, so the lookup neither raises nor thrashes."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    doc.xref_set_key(
        page.xref,
        "Resources",
        "<< /Font << /F1 << /Type /Font /Subtype /TrueType /BaseFont /Arial >> >> >>",
    )
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.font_xref == 0
    assert before.tier0_reject_reason is not None
    assert _lookup(registry, doc) is before


# --- digest function ---------------------------------------------------------


def _digest(doc: fitz.Document, font_xref: int) -> str:
    from model.text_commit.fonts import compute_simple_font_evidence_digest

    return compute_simple_font_evidence_digest(doc, font_xref)


def test_digest_is_stable_across_repeated_reads():
    doc, font_xref = _simple_doc(descriptor=True, indirect_widths=True)
    assert _digest(doc, font_xref) == _digest(doc, font_xref)
    assert len(_digest(doc, font_xref)) == 64


def _set(key: str, value: str):
    return lambda d, x: d.xref_set_key(x, key, value)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_set("Widths", _widths_src(1.0)), id="widths"),
        pytest.param(_set("FirstChar", "31"), id="first-char"),
        pytest.param(_set("LastChar", "127"), id="last-char"),
        pytest.param(_set("Encoding", "/MacRomanEncoding"), id="encoding"),
        pytest.param(_set("Subtype", "/Type1"), id="subtype"),
        pytest.param(_set("BaseFont", "/Courier"), id="basefont"),
        pytest.param(
            lambda d, x: d.xref_set_key(
                _indirect(d, x, "FontDescriptor"), "Flags", "4"
            ),
            id="descriptor-flags",
        ),
        pytest.param(
            lambda d, x: d.update_object(_indirect(d, x, "Widths"), _widths_src(2.0)),
            id="indirect-widths-target",
        ),
    ],
)
def test_digest_changes_for_every_evidence_object_the_builder_reads(mutate):
    doc, font_xref = _simple_doc(descriptor=True, indirect_widths=True)
    before = _digest(doc, font_xref)
    mutate(doc, font_xref)
    assert _digest(doc, font_xref) != before


def test_digest_covers_the_encoding_target_object():
    doc, font_xref = _simple_doc()
    encoding_xref = doc.get_new_xref()
    doc.update_object(
        encoding_xref, "<< /Type /Encoding /BaseEncoding /WinAnsiEncoding >>"
    )
    doc.xref_set_key(font_xref, "Encoding", f"{encoding_xref} 0 R")
    before = _digest(doc, font_xref)
    doc.xref_set_key(encoding_xref, "Differences", "[65 /B]")
    assert _digest(doc, font_xref) != before


def test_digest_covers_the_font_program_bytes():
    doc, font_xref = _simple_doc(font_file=b"program-v1")
    before = _digest(doc, font_xref)
    ff_xref = _indirect(doc, _indirect(doc, font_xref, "FontDescriptor"), "FontFile2")
    doc.update_stream(ff_xref, b"program-v2")
    assert _digest(doc, font_xref) != before


def test_digest_covers_the_font_program_stream_dict():
    """Raw bytes alone miss a /Filter (or /DecodeParms) rewrite that changes
    what ``extract_font`` decodes from the same stored bytes."""
    doc, font_xref = _simple_doc(font_file=b"program-v1")
    before = _digest(doc, font_xref)
    ff_xref = _indirect(doc, _indirect(doc, font_xref, "FontDescriptor"), "FontFile2")
    doc.xref_set_key(ff_xref, "Filter", "/ASCIIHexDecode")
    assert _digest(doc, font_xref) != before


def test_digest_of_inline_font_is_a_constant():
    doc = fitz.open()
    assert _digest(doc, 0) == _digest(doc, 0)


# --- review F1: MuPDF-resolved entry fields behind indirect name objects ------


def _indirect_name(doc: fitz.Document, font_xref: int, key: str, name: str) -> int:
    """Make ``/<key>`` an indirect reference to a name object (legal PDF)."""
    target = doc.get_new_xref()
    doc.update_object(target, f"/{name}")
    doc.xref_set_key(font_xref, key, f"{target} 0 R")
    return target


def test_indirect_basefont_target_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc()
    target = _indirect_name(doc, font_xref, "BaseFont", "Arial")
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.basefont == "Arial" and before.ascii_repertoire_attested is True
    doc.update_object(target, "/Wingdings-Regular")
    after = _lookup(registry, doc)
    assert after is not before
    assert after.basefont == "Wingdings-Regular"
    assert after.ascii_repertoire_attested is False


def test_indirect_subtype_target_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc()
    target = _indirect_name(doc, font_xref, "Subtype", "TrueType")
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.supports_simple_encoding is True
    doc.update_object(target, "/Type3")
    after = _lookup(registry, doc)
    assert after is not before
    assert after.tier0_reject_reason == RejectReason.FONT_TYPE3


def test_indirect_base_encoding_target_rewrite_rebuilds_the_capability():
    doc, font_xref = _simple_doc()
    target = doc.get_new_xref()
    doc.update_object(target, "/WinAnsiEncoding")
    doc.xref_set_key(
        font_xref, "Encoding", f"<< /Type /Encoding /BaseEncoding {target} 0 R >>"
    )
    registry = DocumentFontRegistry(doc)
    before = _lookup(registry, doc)
    assert before.supports_simple_encoding is True
    doc.update_object(target, "/MacExpertEncoding")
    after = _lookup(registry, doc)
    assert after is not before
    assert after.tier0_reject_reason == RejectReason.FONT_UNSUPPORTED_ENCODING


# --- review F2: a single-resource lookup must not re-digest the whole page ----


def _add_font_copies(doc: fitz.Document, font_xref: int, names: tuple[str, ...]) -> None:
    page = doc[0]
    for name in names:
        copy_xref = doc.get_new_xref()
        doc.update_object(copy_xref, doc.xref_object(font_xref))
        doc.xref_set_key(page.xref, f"Resources/Font/{name}", f"{copy_xref} 0 R")


def test_single_resource_lookup_digests_only_that_resource(monkeypatch):
    """prepare() resolves capabilities one show-resource at a time; on an
    N-font page that must cost one digest per lookup, not N (review F2:
    O(K*N) digests made a 98-font page's prepare 7x slower)."""
    import model.text_commit.fonts as fonts

    doc, font_xref = _simple_doc()
    _add_font_copies(doc, font_xref, ("F2", "F3", "F4"))
    registry = DocumentFontRegistry(doc)
    assert len(registry.page_capabilities(doc[0])) == 4  # warm every slot
    calls: list[str] = []
    real = fonts.compute_font_evidence_digest

    def counting(doc_, entry):
        calls.append(entry[4])
        return real(doc_, entry)

    monkeypatch.setattr(fonts, "compute_font_evidence_digest", counting)
    assert registry.capability(doc[0], "F3") is not None
    assert calls == ["F3"]
    calls.clear()
    assert registry.capability(doc[0], "missing") is None
    assert calls == []


def test_single_resource_lookup_still_revalidates_that_resource():
    doc, font_xref = _simple_doc(default_width=600.0)
    _add_font_copies(doc, font_xref, ("F2",))
    registry = DocumentFontRegistry(doc)
    before = registry.capability(doc[0], "F1")
    assert before is not None and before.width_of_code(ord("H")) == 600.0
    doc.xref_set_key(font_xref, "Widths", _widths_src(250.0))
    after = registry.capability(doc[0], "F1")
    assert after is not None and after is not before
    assert after.width_of_code(ord("H")) == 250.0
    # The untouched sibling keeps its slot and stays a hit.
    sibling = registry.capability(doc[0], "F2")
    assert sibling is not None and sibling is registry.capability(doc[0], "F2")
