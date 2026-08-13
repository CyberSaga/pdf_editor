"""Red-light tests for the per-xref font registry (plan Task 4).

Fonts resolve by (generation, resource owner, resource name, font xref) —
never by subset-stripped basename.  Every unusable font carries an
explicit rejection; there is no silent Helvetica fallback anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import (  # noqa: E402
    DocumentFontRegistry,
    resolve_system_face,
)
from scripts.build_fidelity_corpus import (  # noqa: E402
    _build_differences_encoding,
    _build_type3_font,
)


@pytest.fixture()
def base14_doc():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    yield doc
    doc.close()


@pytest.fixture()
def embedded_doc():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    writer = fitz.TextWriter(page.rect)
    writer.append((72, 100), "Alpha embedded", font=fitz.Font("helv"), fontsize=12)
    writer.write_text(page)
    yield doc
    doc.close()


def _register_font_resource(
    doc: fitz.Document, page: fitz.Page, name: str, font_xref: int
) -> None:
    """Add /Font <name> to the page resources, resolving indirect dicts."""
    owner, path = page.xref, "Resources/Font"
    kind, value = doc.xref_get_key(page.xref, "Resources")
    if kind == "xref":
        owner, path = int(value.split()[0]), "Font"
        fkind, fvalue = doc.xref_get_key(owner, "Font")
        if fkind == "xref":
            owner, path = int(fvalue.split()[0]), ""
    key = f"{path}/{name}" if path else name
    doc.xref_set_key(owner, key, f"{font_xref} 0 R")


def test_same_basename_different_xrefs_stay_distinct(embedded_doc):
    doc = embedded_doc
    page = doc[0]
    entries = page.get_fonts(full=True)
    assert len(entries) == 1
    src_xref = entries[0][0]

    copy_xref = doc.get_new_xref()
    doc.update_object(copy_xref, "<<>>")
    doc.xref_copy(src_xref, copy_xref)
    _register_font_resource(doc, page, "FCopy", copy_xref)

    registry = DocumentFontRegistry(doc)
    caps = registry.page_capabilities(page)
    assert len(caps) == 2
    by_name = {cap.resource_name: cap for cap in caps.values()}
    original = next(c for c in by_name.values() if c.font_xref == src_xref)
    copied = by_name["FCopy"]
    assert copied.font_xref == copy_xref
    assert copied.font_xref != original.font_xref
    assert copied.basefont == original.basefont  # same basename, distinct identity


def test_embedded_type0_carries_no_face_and_gates_on_descendant(embedded_doc):
    """Task 12 P0-D contract update (was: Type0 extracts a fitz face).

    Type0 fonts no longer load a face at all: glyph presence is proven
    GID-level from the embedded program (subset cmaps are stripped, so a
    face's Unicode lookups are worthless there — docs/PITFALLS.md), and
    the helv TextWriter embedding lands as a CIDFontType0 descendant,
    which the v1 slice fail-closes with its own stable code.
    """
    registry = DocumentFontRegistry(embedded_doc)
    caps = registry.page_capabilities(embedded_doc[0])
    cap = next(iter(caps.values()))
    assert cap.embedded
    assert cap.subtype == "Type0"
    assert cap.face is None
    assert cap.face_source == "none"
    assert cap.cid is None
    assert cap.tier0_reject_reason == "type0_descendant_unsupported"


def test_base14_unembedded_resolves_named_metrics_face(base14_doc):
    registry = DocumentFontRegistry(base14_doc)
    cap = next(iter(registry.page_capabilities(base14_doc[0]).values()))
    assert not cap.embedded
    assert cap.face is not None
    assert cap.face_source == "base14"
    assert cap.supports_simple_encoding
    assert cap.tier0_reject_reason is None


def test_metric_agreement_with_rawdict_span(base14_doc):
    page = base14_doc[0]
    registry = DocumentFontRegistry(base14_doc)
    cap = next(iter(registry.page_capabilities(page).values()))

    span = page.get_text("rawdict")["blocks"][0]["lines"][0]["spans"][0]
    observed_width = span["bbox"][2] - span["bbox"][0]
    assert cap.face is not None
    predicted = cap.face.text_length("Hello World", fontsize=span["size"])
    assert predicted == pytest.approx(observed_width, rel=0.02)


def test_missing_replacement_glyphs_reported(base14_doc):
    registry = DocumentFontRegistry(base14_doc)
    cap = next(iter(registry.page_capabilities(base14_doc[0]).values()))
    assert cap.missing_glyphs("Hello") == ""
    assert "中" in cap.missing_glyphs("Hi中")


def test_type3_font_rejected_without_helvetica_fallback():
    doc = _build_type3_font()
    registry = DocumentFontRegistry(doc)
    caps = registry.page_capabilities(doc[0])
    cap = next(iter(caps.values()))
    assert cap.subtype == "Type3"
    assert cap.tier0_reject_reason == RejectReason.FONT_TYPE3
    assert cap.face is None  # never silently helv
    doc.close()


def test_identity_h_never_supports_simple_encoding(embedded_doc):
    """Identity-H is not a SIMPLE encoding — that half of the old pin
    stands forever. The old second half (a blanket
    ``FONT_UNSUPPORTED_ENCODING``) died with Task 12 P0-D: Type0 fonts now
    gate through the CID evidence chain and report per-gate ``type0_*``
    codes (this helv fixture: an out-of-scope CIDFontType0 descendant).
    """
    registry = DocumentFontRegistry(embedded_doc)
    cap = next(iter(registry.page_capabilities(embedded_doc[0]).values()))
    assert cap.encoding.startswith("Identity")
    assert not cap.supports_simple_encoding
    assert cap.encode_simple("Alpha") is None
    assert cap.tier0_reject_reason == "type0_descendant_unsupported"


def test_custom_differences_encoding_rejected():
    doc = _build_differences_encoding()
    registry = DocumentFontRegistry(doc)
    caps = registry.page_capabilities(doc[0])
    cap = next(iter(caps.values()))
    assert cap.tier0_reject_reason == RejectReason.FONT_CUSTOM_DIFFERENCES
    doc.close()


def test_encode_simple_is_strict_ascii(base14_doc):
    registry = DocumentFontRegistry(base14_doc)
    cap = next(iter(registry.page_capabilities(base14_doc[0]).values()))
    assert cap.encode_simple("Hello!") == b"Hello!"
    assert cap.encode_simple("Héllo") is None  # non-ASCII: v1 refuses
    assert cap.encode_simple("tab\there") is None  # control chars refuse


def test_encode_simple_refuses_non_simple_fonts(embedded_doc):
    registry = DocumentFontRegistry(embedded_doc)
    cap = next(iter(registry.page_capabilities(embedded_doc[0]).values()))
    assert cap.encode_simple("Hello") is None


def test_resolve_system_face_never_defaults_to_helvetica():
    assert resolve_system_face("NoSuchFontFamily-Bold") is None


def test_registry_caches_per_generation(base14_doc):
    registry = DocumentFontRegistry(base14_doc)
    page = base14_doc[0]
    cap_a = registry.capability(page, next(iter(registry.page_capabilities(page))))
    cap_b = registry.capability(page, cap_a.resource_name)
    assert cap_a is cap_b  # cached
    registry.bump_generation()
    cap_c = registry.capability(page, cap_a.resource_name)
    assert cap_c is not cap_a  # generation invalidates the cache
