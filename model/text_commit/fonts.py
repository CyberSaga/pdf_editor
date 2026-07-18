"""Per-xref font capability registry for the text-commit engine.

Identity is (document generation, resource owner xref, resource name,
font xref) — never a subset-stripped basename: one document can carry
several same-named subsets with disjoint glyph sets (S1 audit finding).

Every capability is explicit about what face backs it (``face_source``)
and why Tier 0 cannot use it (``tier0_reject_reason``).  There is no
silent Helvetica fallback: an unresolvable font yields ``face=None`` plus
a reason, and :func:`resolve_system_face` returns ``None`` for unknown
families instead of PyMuPDF's default-to-Helvetica behavior.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import fitz

from model.text_commit.dto import RejectReason

logger = logging.getLogger(__name__)

# PDF base-14 basefont -> PyMuPDF builtin alias (metrics-compatible face).
_BASE14_ALIASES: dict[str, str] = {
    "Helvetica": "helv",
    "Helvetica-Bold": "hebo",
    "Helvetica-Oblique": "heit",
    "Helvetica-BoldOblique": "hebi",
    "Times-Roman": "tiro",
    "Times-Bold": "tibo",
    "Times-Italic": "tiit",
    "Times-BoldItalic": "tibi",
    "Courier": "cour",
    "Courier-Bold": "cobo",
    "Courier-Oblique": "coit",
    "Courier-BoldOblique": "cobi",
    "Symbol": "symb",
    "ZapfDingbats": "zadb",
}

_SIMPLE_SUBTYPES = ("Type1", "TrueType")
_SIMPLE_ENCODINGS = (
    "",
    "StandardEncoding",
    "WinAnsiEncoding",
    "MacRomanEncoding",
)


def resolve_system_face(basefont: str) -> fitz.Font | None:
    """Resolve a *named* face without ever defaulting to Helvetica.

    ``fitz.Font(<unknown name>)`` silently returns Helvetica; that silent
    substitution is exactly what the V2 engine forbids, so the resolved
    face's own name must corroborate the request or we return ``None``.
    """
    name = basefont.split("+", 1)[-1]
    try:
        face = fitz.Font(name)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    requested = name.lower().replace("-", "").replace(" ", "")
    resolved = (face.name or "").lower().replace("-", "").replace(" ", "")
    if resolved and (resolved in requested or requested in resolved):
        return face
    return None


@dataclass(frozen=True)
class FontCapability:
    """What the engine may do with one font resource on one page."""

    owner_xref: int
    resource_name: str
    font_xref: int
    basefont: str
    subtype: str
    encoding: str
    embedded: bool
    face: fitz.Font | None
    face_source: str  # "extracted" | "base14" | "system" | "none"
    supports_simple_encoding: bool
    tier0_reject_reason: str | None

    def missing_glyphs(self, text: str) -> str:
        """Characters of ``text`` without a glyph in the resolved face."""
        if self.face is None:
            return text
        return "".join(ch for ch in text if not self.face.has_glyph(ord(ch)))

    def encode_simple(self, text: str) -> bytes | None:
        """Reverse-encode ``text`` for this font's simple encoding.

        v1 is deliberately strict: printable ASCII only, where Standard,
        WinAnsi, and MacRoman encodings all agree byte-for-byte, and only
        for fonts whose encoding class is verified simple.  Anything else
        returns ``None`` (the caller rejects; it never guesses).
        """
        if not self.supports_simple_encoding or self.tier0_reject_reason:
            return None
        if not all(0x20 <= ord(ch) <= 0x7E for ch in text):
            return None
        if self.missing_glyphs(text):
            return None
        return text.encode("ascii")


def _has_custom_differences(doc: fitz.Document, font_xref: int) -> bool:
    kind, value = doc.xref_get_key(font_xref, "Encoding")
    if kind == "xref":
        try:
            target = int(value.split()[0])
        except (ValueError, IndexError):
            return True  # unreadable encoding: treat as unsupported
        return "/Differences" in doc.xref_object(target)
    if kind == "dict":
        return "/Differences" in value
    return False


def _load_extracted_face(
    doc: fitz.Document, font_xref: int
) -> fitz.Font | None:
    try:
        _, _, _, buffer = doc.extract_font(font_xref)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    if not buffer:
        return None
    try:
        return fitz.Font(fontbuffer=buffer)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None


def _build_capability(
    doc: fitz.Document,
    owner_xref: int,
    entry: tuple,
) -> FontCapability:
    font_xref, ext, subtype, basefont, resource_name, encoding = entry[:6]
    embedded = ext not in ("n/a", "")

    face: fitz.Font | None = None
    face_source = "none"
    reject: str | None = None
    simple = False

    if subtype == "Type3":
        reject = RejectReason.FONT_TYPE3
    else:
        if embedded:
            face = _load_extracted_face(doc, font_xref)
            if face is not None:
                face_source = "extracted"
        else:
            alias = _BASE14_ALIASES.get(basefont.split("+", 1)[-1])
            if alias is not None:
                face = fitz.Font(alias)
                face_source = "base14"
            else:
                face = resolve_system_face(basefont)
                if face is not None:
                    face_source = "system"

        if face is None:
            reject = RejectReason.FONT_FACE_UNAVAILABLE
        elif subtype not in _SIMPLE_SUBTYPES or encoding not in _SIMPLE_ENCODINGS:
            reject = RejectReason.FONT_UNSUPPORTED_ENCODING
        elif _has_custom_differences(doc, font_xref):
            reject = RejectReason.FONT_CUSTOM_DIFFERENCES
        else:
            simple = True

    return FontCapability(
        owner_xref=owner_xref,
        resource_name=resource_name,
        font_xref=font_xref,
        basefont=basefont,
        subtype=subtype,
        encoding=encoding,
        embedded=embedded,
        face=face,
        face_source=face_source,
        supports_simple_encoding=simple,
        tier0_reject_reason=reject,
    )


@dataclass
class DocumentFontRegistry:
    """Capability cache keyed by (generation, owner, name, font xref)."""

    doc: fitz.Document
    generation: int = 0
    _cache: dict[tuple[int, int, str, int], FontCapability] = field(
        default_factory=dict, repr=False
    )

    def bump_generation(self) -> None:
        """Invalidate every cached capability (document mutated)."""
        self.generation += 1
        self._cache.clear()

    def page_capabilities(self, page: fitz.Page) -> dict[str, FontCapability]:
        """Capabilities of every font resource visible on ``page``.

        Keyed by resource name; distinct xrefs behind equal basenames stay
        distinct entries (callers must address fonts by resource name).
        """
        capabilities: dict[str, FontCapability] = {}
        for entry in page.get_fonts(full=True):
            owner_xref = int(entry[6]) if len(entry) > 6 and entry[6] else page.xref
            resource_name = entry[4]
            key = (self.generation, owner_xref, resource_name, int(entry[0]))
            cached = self._cache.get(key)
            if cached is None:
                cached = _build_capability(self.doc, owner_xref, entry)
                self._cache[key] = cached
            capabilities[resource_name] = cached
        return capabilities

    def capability(
        self, page: fitz.Page, resource_name: str
    ) -> FontCapability | None:
        return self.page_capabilities(page).get(resource_name)
