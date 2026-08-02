"""Red-light spike for Identity-H / CID text (plan Task 10, step 4).

Two characterizations, both against a synthetic CJK page written the only
way PyMuPDF can write CJK today -- ``fitz.TextWriter`` with ``fitz.Font(
"cjk")`` -- which always embeds a Type0/Identity-H font (docs/PITFALLS.md
:1846-1850):

1. Byte-level (latin-1) source binding already refuses CID text outright
   (``bind_source_text`` docstring, inspect.py:146-148) -- this is pinned,
   not news.
2. The actual gap this step names: source encoding must never be *inferred*
   from ``fitz.Font`` Unicode glyph coverage. Evidence must come from the
   font dictionary itself -- ``/Encoding``, the descendant CIDFont's
   ``/CIDToGIDMap``, and a real ``/ToUnicode`` CMap stream -- and a missing
   or unusable leg is a hard rejection, even when the face could plainly
   render every target character.

Nothing here enables CID text in Tier 0 or Tier 1; ``collect_cid_encoding_
evidence`` is a read-only evidence reader, never a writer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    bind_source_text,
    page_fingerprint,
    read_page_streams,
)
from model.text_commit.replay import replay_page_streams  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    CidEncodingEvidence,
    VerificationFailure,
    collect_cid_encoding_evidence,
)

_PAGE_W = 595.0
_PAGE_H = 842.0
CJK_TEXT = "你好世界"


def _write_cjk_page() -> tuple[fitz.Document, fitz.Page, int]:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    font = fitz.Font("cjk")
    tw = fitz.TextWriter(page.rect)
    tw.append((72, 700), CJK_TEXT, font=font)
    tw.write_text(page)
    fonts = page.get_fonts(full=True)
    assert len(fonts) == 1
    font_xref = fonts[0][0]
    return doc, page, font_xref


def _fonts_resource_name(page: fitz.Page) -> str:
    return page.get_fonts(full=True)[0][4]


def test_identity_h_binding_rejects_today_and_evidence_requires_cmap_cid_gid():
    doc, page, font_xref = _write_cjk_page()

    # ---- Phase A: characterize today's byte-level binding refusal ----
    binding = bind_source_text(
        doc, page, target_text=CJK_TEXT, expected_origin=None
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason in (RejectReason.NO_MATCH, RejectReason.UNDECODABLE_TARGET)
    # latin-1 cannot represent CJK at all -- this is the deterministic leg.
    assert binding.reason == RejectReason.UNDECODABLE_TARGET

    # ---- Phase B: the real gate -- CMap/CID/GID evidence, not inference ----
    font_object = doc.xref_object(font_xref)
    assert "/Subtype/Type0" in font_object.replace(" ", "")
    assert "/Encoding/Identity-H" in font_object.replace(" ", "")

    evidence = collect_cid_encoding_evidence(doc, font_xref)
    assert isinstance(evidence, CidEncodingEvidence)
    assert evidence.encoding == "Identity-H"

    kind, tounicode_value = doc.xref_get_key(font_xref, "ToUnicode")
    assert kind == "xref"
    expected_tounicode_xref = int(tounicode_value.split()[0])
    assert evidence.tounicode_xref == expected_tounicode_xref
    tounicode_bytes = doc.xref_stream(evidence.tounicode_xref)
    assert tounicode_bytes is not None
    assert b"beginbfchar" in tounicode_bytes or b"beginbfrange" in tounicode_bytes

    # /CIDToGIDMap absent in this PyMuPDF build => implicit "Identity"
    # default per the PDF spec (CIDFontType2, 9.7.4.3) -- never left blank.
    assert evidence.cid_to_gid == "Identity"

    # The hex ShowOp operand decodes to CIDs; run those CIDs through the
    # evidence's own /ToUnicode mapping and require the EXACT inserted
    # string -- proving the decode came from source CMap evidence, not
    # face coverage.
    streams = read_page_streams(doc, page)
    replay = replay_page_streams(streams)
    assert not replay.malformed
    shows = [s for s in replay.shows if s.font_resource == _fonts_resource_name(page)]
    assert len(shows) == 1
    show = shows[0]
    assert show.operator == "TJ"
    assert len(show.decoded_bytes) == 2 * len(CJK_TEXT)
    cids = [
        int.from_bytes(show.decoded_bytes[i : i + 2], "big")
        for i in range(0, len(show.decoded_bytes), 2)
    ]
    decoded_text = "".join(evidence.decode(cid) or "" for cid in cids)
    assert decoded_text == CJK_TEXT

    doc.close()


def test_missing_tounicode_yields_rejection_not_unicode_coverage_inference():
    doc, page, font_xref = _write_cjk_page()
    doc.xref_set_key(font_xref, "ToUnicode", "null")

    face = fitz.Font("cjk")
    for ch in CJK_TEXT:
        assert face.has_glyph(ord(ch)), (
            "the face DOES cover every target character -- proving the "
            "temptation to infer encoding from glyph coverage exists"
        )

    fingerprint_before = page_fingerprint(doc, page)
    streams_before = read_page_streams(doc, page)

    evidence = collect_cid_encoding_evidence(doc, font_xref)
    assert isinstance(evidence, VerificationFailure)
    assert evidence.reason == RejectReason.FONT_UNSUPPORTED_ENCODING

    # Evidence collection must be read-only: no structural side effects,
    # no matter what it concluded.
    assert page_fingerprint(doc, page) == fingerprint_before
    assert read_page_streams(doc, page) == streams_before

    doc.close()
