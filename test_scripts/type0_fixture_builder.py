"""Synthetic Identity-H/CIDFontType2 fixture builder (Task 12 P0-D).

Builds fully synthetic Type0 pages the P0-D red matrix exercises — nothing
here derives from any real document (plan §10 data policy). The base build
is the one way PyMuPDF can author CJK today (``fitz.TextWriter`` +
``fitz.Font("cjk")``, which embeds Droid Sans Fallback as
Type0/Identity-H/CIDFontType2), followed by two normalizations:

1. The content stream is REPLACED with a hand-authored **single hex ``Tj``
   in the direct page content stream** (TextWriter itself always emits
   ``TJ`` arrays) — verified by the 2026-08-13 spike to extract, replay
   (``operator="Tj"``, ``string_kind="hex"``, byte-exact operand,
   ``origin_reliable=True``), save/reopen, and render, including under
   ``/Rotate 270``.
2. The document is saved and reopened so every fixture is a clean,
   parser-normalized PDF whose xrefs the mutators below can address.

MuPDF's own embedding matches the private corpus's DOMINANT shape (census
2026-08-13, plan §8): ``/W`` present, ``/DW`` absent (spec default 1000),
``/CIDToGIDMap`` absent (spec-implicit Identity), embedded ``FontFile2``.
Mutators then derive every fail-closed variant by xref surgery.

CID facts this builder relies on (spike-verified for PyMuPDF 1.27.x):
- MuPDF assigns CID == GID for its Identity-H embedding, and
  ``fitz.Font.has_glyph(ord(ch))`` returns that GID — so CIDs are computed
  from the face, never parsed out of the ToUnicode CMap.
- ``Document.subset_fonts()`` is native in this PyMuPDF build (no
  fontTools needed) and retains GIDs, so CIDs and content-stream bytes
  stay stable across subsetting.  The subset program's ``cmap`` is
  STRIPPED: ``fitz.Font(fontbuffer=subset).has_glyph`` returns 0 even for
  retained glyphs, so glyph presence in a subset must be proven by
  rendering ink (:func:`render_cid_ink`), never by Unicode lookup.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fitz

# Four full-width CJK chars, each advancing exactly 1.0 em in Droid Sans
# Fallback — so a same-length replacement is an equal-advance (Tier 0)
# candidate and a shorter one is an unequal-advance (Tier 1) candidate.
CJK_TEXT = "你好世界"
REPLACEMENT_EQUAL_ADVANCE = "再見世界"
REPLACEMENT_SHORTER = "你好"
TAIL_TEXT = "後綴"

_PAGE_W = 595.0
_PAGE_H = 842.0

_FONT = fitz.Font("cjk")


def cid_for(char: str) -> int:
    """CID (== GID) of one character in the builder font; 0 = no glyph."""
    return _FONT.has_glyph(ord(char))


def encode_cids(text: str) -> bytes:
    """Identity-H 2-byte big-endian encoding of ``text``'s CIDs."""
    out = bytearray()
    for char in text:
        cid = cid_for(char)
        if cid == 0:
            raise ValueError("builder font has no glyph for a fixture char")
        out += cid.to_bytes(2, "big")
    return bytes(out)


@dataclass
class Type0Fixture:
    """One synthetic Identity-H page plus the xrefs mutators need."""

    doc: fitz.Document
    page_number: int
    resource_name: str
    font_xref: int
    descendant_xref: int
    tounicode_xref: int
    content_xref: int
    text: str
    fontsize: float
    origin: tuple[float, float]
    encoded: bytes
    tail_text: str | None = None
    extra_streams: list[int] = field(default_factory=list)

    @property
    def page(self) -> fitz.Page:
        return self.doc[self.page_number]

    def content_bytes(self) -> bytes:
        return self.doc.xref_stream(self.content_xref) or b""


def _descendant_xref_of(doc: fitz.Document, font_xref: int) -> int:
    kind, value = doc.xref_get_key(font_xref, "DescendantFonts")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]))
    return int(value.strip()[1:].split()[0])


# Authored base documents, keyed by every build parameter.  Authoring embeds
# the full 3.5 MB face; reopening cached bytes is what keeps a ~30-test
# matrix fast.  Mutators never touch the cache: every build reopens a fresh
# document from the cached bytes.
_BASE_CACHE: dict[tuple, bytes] = {}


def _author_base(
    text: str,
    fontsize: float,
    origin: tuple[float, float],
    rotate: int,
    subset: bool,
    tail_text: str | None,
    pad_stream_to: int | None,
) -> bytes:
    key = (text, fontsize, origin, rotate, subset, tail_text, pad_stream_to)
    cached = _BASE_CACHE.get(key)
    if cached is not None:
        return cached

    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    writer = fitz.TextWriter(page.rect)
    writer.append(origin, text + (tail_text or ""), font=_FONT, fontsize=fontsize)
    writer.write_text(page)
    if subset:
        doc.subset_fonts()

    resource_name = page.get_fonts(full=True)[0][4]
    operand = encode_cids(text).hex().upper()
    stream = (
        f"BT /{resource_name} {fontsize:g} Tf "
        f"1 0 0 1 {origin[0]:g} {origin[1]:g} Tm <{operand}> Tj"
    )
    if tail_text is not None:
        stream += f" <{encode_cids(tail_text).hex().upper()}> Tj"
    stream += " ET"
    stream_bytes = stream.encode("ascii")
    if pad_stream_to is not None and len(stream_bytes) < pad_stream_to:
        stream_bytes += b" " * (pad_stream_to - len(stream_bytes))
    doc.update_stream(page.get_contents()[0], stream_bytes)
    if rotate:
        page.set_rotation(rotate)

    data = doc.tobytes()
    doc.close()
    _BASE_CACHE[key] = data
    return data


def build_identity_h_fixture(
    text: str = CJK_TEXT,
    *,
    fontsize: float = 12.0,
    origin: tuple[float, float] = (72.0, 700.0),
    rotate: int = 0,
    subset: bool = False,
    tail_text: str | None = None,
    pad_stream_to: int | None = None,
) -> Type0Fixture:
    """Build one synthetic Identity-H single-hex-``Tj`` page.

    ``subset=True`` runs ``Document.subset_fonts()`` BEFORE the stream
    rewrite, so the embedded program keeps outlines only for ``text``'s
    (and ``tail_text``'s) glyphs — the genuine "replacement glyph absent
    from the subset" shape.  ``tail_text`` appends a second hex ``Tj``
    with no positioning operator in between, so its rendered position
    consumes the target's advance (the following-glyph oracle).
    ``pad_stream_to`` pads the content stream with trailing whitespace to
    at least that many bytes (replay-budget fixtures).
    """
    data = _author_base(
        text, fontsize, origin, rotate, subset, tail_text, pad_stream_to
    )
    reopened = fitz.open(stream=data, filetype="pdf")
    page = reopened[0]
    font_xref = page.get_fonts(full=True)[0][0]
    descendant_xref = _descendant_xref_of(reopened, font_xref)
    _, tounicode_value = reopened.xref_get_key(font_xref, "ToUnicode")
    return Type0Fixture(
        doc=reopened,
        page_number=0,
        resource_name=page.get_fonts(full=True)[0][4],
        font_xref=font_xref,
        descendant_xref=descendant_xref,
        tounicode_xref=int(tounicode_value.split()[0]),
        content_xref=page.get_contents()[0],
        text=text,
        fontsize=fontsize,
        origin=origin,
        encoded=encode_cids(text),
        tail_text=tail_text,
    )


# --------------------------------------------------------------- mutators

def _utf16be_hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def write_tounicode_cmap(fixture: Type0Fixture, inner: str) -> None:
    """Replace the ToUnicode stream with a CMap wrapping ``inner`` verbatim.

    ``inner`` supplies the bfchar/bfrange blocks; the wrapper contributes
    the CMap boilerplate and codespace range.  Lets fixtures author any
    spec-legal (or deliberately hostile) mapping shape, e.g. the
    array-destination ``bfrange`` form of PDF 32000-1 §9.10.3.
    """
    body = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CMapName /Adobe-Identity-UCS def\n"
        "/CMapType 2 def\n"
        "1 begincodespacerange\n"
        "<0000> <FFFF>\n"
        "endcodespacerange\n"
        f"{inner}\n"
        "endcmap\nend\nend"
    )
    fixture.doc.update_stream(fixture.tounicode_xref, body.encode("ascii"))


def write_minimal_tounicode(
    fixture: Type0Fixture, mappings: list[tuple[int, str]]
) -> None:
    """Replace the ToUnicode CMap with exactly ``mappings`` (order kept).

    Each entry is ``(cid, unicode_text)``; multi-char texts (ligature-style
    one-CID→many-chars) and duplicate Unicode targets are both
    representable — the multichar-exclusion, ambiguity and reproduction
    fixtures rely on that.
    """
    lines = [f"{len(mappings)} beginbfchar"]
    for cid, text in mappings:
        lines.append(f"<{cid:04X}> <{_utf16be_hex(text)}>")
    lines.append("endbfchar")
    write_tounicode_cmap(fixture, "\n".join(lines))


def default_tounicode_mappings(
    fixture: Type0Fixture, extra_text: str = ""
) -> list[tuple[int, str]]:
    """One (cid, char) pair per distinct char of the fixture (plus extras)."""
    chars: list[str] = []
    for char in fixture.text + (fixture.tail_text or "") + extra_text:
        if char not in chars:
            chars.append(char)
    return [(cid_for(char), char) for char in chars]


def strip_tounicode(fixture: Type0Fixture) -> None:
    fixture.doc.xref_set_key(fixture.font_xref, "ToUnicode", "null")


def set_encoding_name(fixture: Type0Fixture, name: str) -> None:
    fixture.doc.xref_set_key(fixture.font_xref, "Encoding", f"/{name}")


def set_encoding_custom_cmap(fixture: Type0Fixture) -> None:
    """Point /Encoding at an embedded CMap stream (out-of-scope form)."""
    cmap_xref = fixture.doc.get_new_xref()
    fixture.doc.update_object(cmap_xref, "<< /Type /CMap >>")
    fixture.doc.update_stream(cmap_xref, b"%custom-cmap-placeholder")
    fixture.doc.xref_set_key(fixture.font_xref, "Encoding", f"{cmap_xref} 0 R")
    fixture.extra_streams.append(cmap_xref)


def set_descendant_subtype(fixture: Type0Fixture, name: str) -> None:
    fixture.doc.xref_set_key(fixture.descendant_xref, "Subtype", f"/{name}")


def identity_cidtogid_bytes(
    count: int, overrides: dict[int, int] | None = None
) -> bytes:
    """A CIDToGIDMap stream mapping cid -> cid for cids < count."""
    table = bytearray()
    for cid in range(count):
        gid = (overrides or {}).get(cid, cid)
        table += gid.to_bytes(2, "big")
    return bytes(table)


def set_cidtogid_stream(fixture: Type0Fixture, table: bytes) -> None:
    map_xref = fixture.doc.get_new_xref()
    fixture.doc.update_object(map_xref, "<<>>")
    fixture.doc.update_stream(map_xref, table)
    fixture.doc.xref_set_key(
        fixture.descendant_xref, "CIDToGIDMap", f"{map_xref} 0 R"
    )
    fixture.extra_streams.append(map_xref)


def set_cidtogid_dangling(fixture: Type0Fixture) -> None:
    """Point /CIDToGIDMap at an object that does not exist."""
    missing = fixture.doc.xref_length() + 50
    fixture.doc.xref_set_key(
        fixture.descendant_xref, "CIDToGIDMap", f"{missing} 0 R"
    )


def set_w_array(fixture: Type0Fixture, w_literal: str) -> None:
    fixture.doc.xref_set_key(fixture.descendant_xref, "W", w_literal)


def w_literal_for(cids: list[int], width: int = 1000) -> str:
    return "[ " + " ".join(f"{cid} [ {width} ]" for cid in cids) + " ]"


def set_dw(fixture: Type0Fixture, literal: str) -> None:
    fixture.doc.xref_set_key(fixture.descendant_xref, "DW", literal)


def remove_w(fixture: Type0Fixture) -> None:
    fixture.doc.xref_set_key(fixture.descendant_xref, "W", "null")


def unembed_font(fixture: Type0Fixture) -> None:
    """Strip the embedded font program (descriptor keeps everything else).

    Nulls the key on the descriptor's own xref: path-based ``xref_set_key``
    cannot null a nested key (it leaves PyMuPDF's placeholder string).
    """
    kind, value = fixture.doc.xref_get_key(
        fixture.descendant_xref, "FontDescriptor"
    )
    assert kind == "xref", "builder fixtures always carry an indirect descriptor"
    descriptor_xref = int(value.split()[0])
    for key in ("FontFile2", "FontFile3", "FontFile"):
        if fixture.doc.xref_get_key(descriptor_xref, key)[0] != "null":
            fixture.doc.xref_set_key(descriptor_xref, key, "null")


def inline_descendant(fixture: Type0Fixture) -> None:
    """Rewrite /DescendantFonts [N 0 R] as an inline dictionary array.

    The census-dominant corpus shape (plan §8, 2026-08-13): the descendant
    CIDFont lives INLINE in the array, with /FontDescriptor and /W still
    indirect. The old descendant object is left orphaned; ``descendant_
    xref`` is set to 0 because the inline dict is no longer addressable —
    descendant mutators must run BEFORE this one.
    """
    body = " ".join(fixture.doc.xref_object(fixture.descendant_xref).split())
    fixture.doc.xref_set_key(
        fixture.font_xref, "DescendantFonts", f"[ {body} ]"
    )
    fixture.descendant_xref = 0


def embedded_font_buffer(fixture: Type0Fixture) -> bytes:
    """The embedded font program bytes (for glyph-repertoire assertions)."""
    _, _, _, buffer = fixture.doc.extract_font(fixture.font_xref)
    return buffer


def document_object_snapshot(doc: fitz.Document) -> tuple:
    """Serialized body (and raw stream) of every object in the document.

    The zero-mutation oracle for rejection paths: unlike ``doc.tobytes()``
    (nondeterministic across calls — trailer /ID churn), per-xref object
    serialization is stable, and it covers the objects the Type0 gates
    actually read (font dict, descendant, ToUnicode, CIDToGIDMap, /W,
    FontDescriptor, FontFile2) — which a content-stream-only comparison
    cannot see.
    """
    rows = []
    for xref in range(1, doc.xref_length()):
        try:
            body: object = doc.xref_object(xref)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            body = "<unreadable>"
        stream: object = None
        try:
            if doc.xref_is_stream(xref):
                stream = doc.xref_stream_raw(xref)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            stream = "<unreadable>"
        rows.append((xref, body, stream))
    return tuple(rows)


def render_cid_ink(fixture: Type0Fixture, cid: int) -> int:
    """Non-white pixels rendered by showing ``cid`` alone at 48pt.

    Dependency-free proof of glyph presence in the EMBEDDED program: a
    subset that dropped the outline renders zero ink even though the CID
    is structurally addressable.  Swaps the content stream in, renders,
    and restores the original stream before returning.
    """
    original = fixture.content_bytes()
    probe = (
        f"BT /{fixture.resource_name} 48 Tf "
        f"1 0 0 1 100 400 Tm <{cid:04X}> Tj ET"
    ).encode("ascii")
    fixture.doc.update_stream(fixture.content_xref, probe)
    try:
        pix = fixture.page.get_pixmap(dpi=72)
        samples = pix.samples
        white = 255
        ink = sum(1 for value in samples if value != white)
    finally:
        fixture.doc.update_stream(fixture.content_xref, original)
    return ink


# ------------------------------------------------------------- validation

def validate_fixture(fixture: Type0Fixture) -> None:
    """Assert the fixture is a well-formed Identity-H single-hex-Tj page.

    Used by the red tests' fixture-sanity checks so a red failure is
    provably "feature missing", never "fixture broken".
    """
    page = fixture.page
    expected = fixture.text + (fixture.tail_text or "")
    extracted = "".join(page.get_text().split())
    assert extracted == "".join(expected.split()), (
        "fixture page must extract its own text back"
    )
    entry = page.get_fonts(full=True)[0]
    assert entry[2] == "Type0"
    kind, value = fixture.doc.xref_get_key(fixture.font_xref, "Encoding")
    assert (kind, value) == ("name", "/Identity-H")
    raw = fixture.content_bytes()
    operand = f"<{fixture.encoded.hex().upper()}>".encode("ascii")
    assert operand in raw, "single hex Tj operand must sit in the raw stream"
    assert raw.count(b" Tj") == (2 if fixture.tail_text else 1)
