"""Per-xref font capability registry for the text-commit engine.

Identity is (document generation, resource owner xref, resource name,
font xref) — never a subset-stripped basename: one document can carry
several same-named subsets with disjoint glyph sets (S1 audit finding).

Every capability is explicit about what face backs it (``face_source``),
where its advance measurements come from (``advance_source``), and why
Tier 0 cannot use it (``tier0_reject_reason``).  There is no silent
Helvetica fallback: an unresolvable font yields ``face=None`` plus a
reason, and :func:`resolve_system_face` returns ``None`` for unknown
families instead of PyMuPDF's default-to-Helvetica behavior.

For a *simple* (non-CID) font, /Widths — not the font program — is the
layout contract: a conforming viewer advances by
``Widths[code - FirstChar] / 1000 * font_size`` and never consults the
embedded program's own metrics.  So a capability is measurable whenever
that table is complete, even with no face at all, and when both exist the
table wins: a face resolved by *name* from the host system can disagree
with the document's declared widths, and the document is authoritative.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import fitz

from model.text_commit.cid_fonts import (
    CidCapabilityFailure,
    IdentityHCidCapability,
    build_identity_h_cid_capability,
    compute_cid_evidence_digest,
)
from model.text_commit.dto import RejectReason

# Unembedded families whose printable-ASCII repertoire may be assumed: every
# system either ships the named font complete, or substitutes another complete
# text face.  Deliberately a CLOSED allowlist rather than a heuristic — an
# unrecognised name may be a symbolic, barcode, or icon font, and on a machine
# where THAT font is installed the viewer uses it rather than a substitute, so
# a positive /Widths entry for an unused ASCII code renders .notdef.
_FULL_ASCII_FAMILIES = frozenset(
    {
        "arial",
        "helvetica",
        "courier",
        "couriernew",
        "times",
        "timesroman",
        "timesnewroman",
    }
)

_SYMBOLIC_FLAG = 1 << 2  # PDF 32000-1 Table 123, /Flags bit position 3


def _family_stem(basefont: str) -> str:
    """Normalised family key: subset prefix, style, and foundry suffix removed.

    ``ABCDEF+Arial-BoldMT`` -> ``arial``; ``TimesNewRomanPSMT`` ->
    ``timesnewroman``; ``Arial,Bold`` -> ``arial``.
    """
    stem = re.split(r"[,-]", basefont.split("+", 1)[-1], maxsplit=1)[0].lower()
    for suffix in ("psmt", "ps", "mt"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)]
    return stem


def _scalar_int(doc: fitz.Document, kind: str, value: str) -> int | None:
    """An integer dictionary value, dereferenced when it is indirect.

    PDF permits any scalar to be an indirect reference, so ``/FirstChar 8 0 R``
    is valid; treating it as malformed would refuse a sound width table in a
    reader that already dereferences an indirect ``/Widths`` array.
    """
    if kind == "xref":
        try:
            value = doc.xref_object(int(value.split()[0])).strip()
        except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
            return None
    elif kind not in ("int", "float"):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _is_symbolic(doc: fitz.Document, font_xref: int) -> bool:
    """True when the font's descriptor declares it does not use Latin text.

    An unreadable descriptor counts as symbolic: the point of this check is
    to refuse whenever the document has not affirmatively said otherwise.
    """
    # Structured lookup, never a pattern match over the serialised descriptor.
    # The path form resolves an inline *or* indirect /FontDescriptor and an
    # inline *or* indirect /Flags in one call, and — unlike a regex — cannot
    # be fooled by a string value that happens to contain "/Flags", such as
    # /FontFamily (/Flags 0) sitting ahead of the real key.
    if font_xref <= 0:
        return True  # inline resource dict: nothing readable, so nothing attested
    kind, value = doc.xref_get_key(font_xref, "FontDescriptor/Flags")
    if kind == "null":
        return False  # no descriptor, or none declared: nothing to refuse on
    flags = _scalar_int(doc, kind, value)
    if flags is None:
        return True  # present but unreadable: refuse rather than assume Latin
    return bool(flags & _SYMBOLIC_FLAG)

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

# Codes where the simple encodings do NOT agree with ASCII: StandardEncoding
# selects quoteright at 0x27 and quoteleft at 0x60, against quotesingle and
# grave in WinAnsi/MacRoman.  Only those two encodings may be assumed to
# round-trip these slots; an unnamed (font built-in) encoding is unknown.
_ASCII_QUOTE_SLOTS = frozenset({0x27, 0x60})
_QUOTE_SAFE_ENCODINGS = ("WinAnsiEncoding", "MacRomanEncoding")

# A simple font addresses one byte, so it can declare at most 256 widths.
# Bound tokenisation before conversion: classification runs in the
# per-keystroke preview path, where a hostile array must not be built first.
_MAX_SIMPLE_WIDTHS = 256

# Simple-font /Widths entries are in 1/1000 of a text-space unit.
_WIDTH_SCALE = 1000.0
# Character codes addressable by a simple font's /Widths table.
_MAX_SIMPLE_CODE = 255


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
    # Where an advance measurement comes from.  Deliberately separate from
    # ``face_source``, which stays a statement about the *face* alone: an
    # embedded font can carry both a real extracted face and a /Widths
    # table that overrides it, and conflating the two would misreport one.
    advance_source: str = "none"  # "widths" | "face" | "cid" | "none"
    first_char: int = 0
    widths: tuple[float, ...] | None = None
    # Whether printable-ASCII glyph coverage may be assumed with no face.
    # Separate from the advance question: /Widths proves an advance, never an
    # outline.  See :meth:`missing_glyphs`.
    ascii_repertoire_attested: bool = False
    # Task 12 P0-D: the Identity-H/CIDFontType2 codec, present exactly when
    # this Type0 font passed the full evidence chain (tier0_reject_reason is
    # then None). Simple-font callers never consult it; the planner and
    # binding branch on it explicitly.
    cid: IdentityHCidCapability | None = None
    # Sanitized (code-only) detail for a type0_* rejection — the planner
    # surfaces THIS for Type0 fonts, never the basefont name (§10 privacy).
    tier0_reject_detail: str | None = None
    # Same-document digest of every evidence object the build read (Type0:
    # :func:`compute_cid_evidence_digest`; otherwise
    # :func:`compute_simple_font_evidence_digest`).  The registry re-derives
    # it on EVERY cache hit and rebuilds on mismatch, so an in-place rewrite
    # of /Widths, /Encoding, the descriptor or the program at the same xref
    # can no longer be served stale within one generation.  Provenance, not
    # identity: ``compare=False`` (docs/PITFALLS.md, "Provenance fields on
    # compared dataclasses silently break equality pins").
    evidence_digest: str = field(default="", compare=False, repr=False)

    def width_of_code(self, code: int) -> float | None:
        """Declared advance of one character code, in 1/1000 text-space units.

        ``None`` means the document does not prove an advance for ``code``:
        it falls outside ``[FirstChar, LastChar]``, or its declared width is
        zero.  A zero is treated as unproven rather than believed — real
        producers emit 0 for codes they never used — and /MissingWidth is
        deliberately never substituted, since that would be a guess rather
        than the document's contract.
        """
        if self.widths is None:
            return None
        index = code - self.first_char
        if index < 0 or index >= len(self.widths):
            return None
        width = self.widths[index]
        return width if width > 0.0 else None

    def uncovered_codes(self, text: str) -> str:
        """Characters of ``text`` whose advance /Widths does not prove.

        Empty when this capability does not measure from /Widths at all, so
        callers can apply it unconditionally.
        """
        if self.advance_source != "widths":
            return ""
        return "".join(ch for ch in text if self.width_of_code(ord(ch)) is None)

    def string_width(self, text: str, size: float) -> float | None:
        """Advance of ``text`` at ``size`` in points, or ``None`` if unproven.

        /Widths wins over any resolved face: for a simple font it *is* the
        advance a conforming viewer consumes, whereas a face — above all one
        resolved by name from the host system — is only a guess at the same
        quantity and may disagree.
        """
        if self.advance_source == "widths":
            total = 0.0
            for char in text:
                width = self.width_of_code(ord(char))
                if width is None:
                    return None
                total += width
            return total / _WIDTH_SCALE * size
        if self.face is not None:
            return self.face.text_length(text, fontsize=size)
        return None

    def missing_glyphs(self, text: str) -> str:
        """Characters of ``text`` without a glyph in the resolved face.

        ``/Widths`` cannot stand in for a face here.  A width entry proves the
        code has an *advance*, not that it has an *outline*, and subset fonts
        routinely declare widths across their whole ``[FirstChar, LastChar]``
        range while embedding only the glyphs actually drawn.  Trusting the
        table as glyph evidence would let a replacement commit as tofu —
        inside the target region, which is exactly the area V0a–V0e excludes
        from its raster-identity check (it compares outside a 2pt halo), so
        verification would not catch it either.  The plan requires
        "replacement glyphs exist in the source font encoding" as a gate in
        its own right; advance coverage is the separate :meth:`uncovered_codes`
        check the planner applies alongside this one.

        The one case a document settles without a face is recorded at build
        time as :attr:`ascii_repertoire_attested`: an unembedded, non-subset
        font from a known full-ASCII text family that its own descriptor does
        not flag symbolic.  Absence of a subset prefix alone is *not* enough —
        an unfamiliar unembedded name may be a barcode or icon face, and on a
        machine where that font is installed the viewer uses it rather than a
        substitute.  Anything unattested reports every character missing, so
        the caller refuses rather than guesses.
        """
        if self.face is not None:
            return "".join(ch for ch in text if not self.face.has_glyph(ord(ch)))
        return "" if self.ascii_repertoire_attested else text

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
        # The "all three agree byte-for-byte" premise has exactly two
        # exceptions: StandardEncoding puts quoteright at 0x27 and quoteleft
        # at 0x60, where WinAnsi and MacRoman have quotesingle and grave.
        # An unnamed (font built-in) encoding is likewise unknown there.
        if self.encoding not in _QUOTE_SAFE_ENCODINGS and any(
            ord(ch) in _ASCII_QUOTE_SLOTS for ch in text
        ):
            return None
        if self.missing_glyphs(text):
            return None
        return text.encode("ascii")


def _has_custom_differences(doc: fitz.Document, font_xref: int) -> bool:
    if font_xref <= 0:
        return True  # inline resource dict: unreadable, treat as unsupported
    kind, value = doc.xref_get_key(font_xref, "Encoding")
    if kind == "xref":
        try:
            target = int(value.split()[0])
        except (ValueError, IndexError):
            return True  # unreadable encoding: treat as unsupported
        try:
            return "/Differences" in doc.xref_object(target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return True  # dangling encoding ref: treat as unsupported
    if kind == "dict":
        return "/Differences" in value
    return False


def _read_width_table(
    doc: fitz.Document, font_xref: int
) -> tuple[str, int, tuple[float, ...]]:
    """Read a simple font's /Widths contract.

    Returns ``(status, first_char, widths)`` where ``status`` is:

    ``"absent"``
        no /Widths key — the caller may fall back to a face;
    ``"malformed"``
        /Widths is present but unusable (unreadable reference, non-numeric
        or indirect element, length disagreeing with FirstChar/LastChar).
        Present-but-unusable is never downgraded to "absent": the document
        declared a contract we cannot read, so measuring from a face
        instead would silently substitute a different metric.
    ``"ok"``
        ``widths`` covers ``[first_char, first_char + len(widths) - 1]``.
    """
    empty: tuple[float, ...] = ()
    if font_xref <= 0:
        # A font dictionary stored inline in /Resources: get_fonts reports
        # xref 0 and every xref call against it raises. Nothing is readable,
        # so report no table and let the face path decide.
        return ("absent", 0, empty)
    kind, value = doc.xref_get_key(font_xref, "Widths")
    if kind == "null":
        return ("absent", 0, empty)
    if kind == "xref":
        try:
            target = int(value.split()[0])
        except (ValueError, IndexError):
            return ("malformed", 0, empty)
        try:
            source = doc.xref_object(target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            # A dangling reference MuPDF's repair pass did not resolve. The
            # documented contract is "malformed"; letting this escape would
            # surface a RuntimeError out of engine.prepare and out of the
            # per-keystroke preview worker instead of a stable rejection.
            return ("malformed", 0, empty)
    elif kind == "array":
        source = value
    else:
        return ("malformed", 0, empty)

    first_char_value = _scalar_int(doc, *doc.xref_get_key(font_xref, "FirstChar"))
    last_char_value = _scalar_int(doc, *doc.xref_get_key(font_xref, "LastChar"))
    if first_char_value is None or last_char_value is None:
        return ("malformed", 0, empty)
    first_char, last_char = first_char_value, last_char_value

    text = source.strip()
    if not text.startswith("[") or not text.endswith("]"):
        return ("malformed", 0, empty)
    # Bounded split: stop after 256 fields so an oversized or hostile array is
    # detected without materialising every token. The 257th element (if any)
    # is the unsplit remainder, which is enough to know the array is too long.
    # This runs per keystroke in the preview path.
    tokens = text[1:-1].split(None, _MAX_SIMPLE_WIDTHS)
    if len(tokens) > _MAX_SIMPLE_WIDTHS:
        return ("malformed", 0, empty)
    try:
        # A non-numeric token means an indirect element ("12 0 R"), which
        # this reader deliberately refuses rather than resolving per entry.
        widths = tuple(float(token) for token in tokens)
    except ValueError:
        return ("malformed", 0, empty)

    if first_char < 0 or last_char > _MAX_SIMPLE_CODE or last_char < first_char:
        return ("malformed", 0, empty)
    if len(widths) != last_char - first_char + 1:
        return ("malformed", 0, empty)
    return ("ok", first_char, widths)


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


def _fold_font_object(
    fold: "Callable[[bytes, bytes | None], None]",
    doc: fitz.Document,
    marker: bytes,
    xref: int,
) -> None:
    try:
        fold(marker, doc.xref_object(xref).encode("latin-1", "replace"))
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        fold(marker, None)


def compute_simple_font_evidence_digest(doc: fitz.Document, font_xref: int) -> str:
    """Raw digest of every evidence object a non-Type0 capability build reads.

    SAME-DOCUMENT identity only (raw object text / raw stream bytes are cheap
    but not stable across a save/reopen re-serialization) — consumed by the
    registry cache to refuse a stale capability, never by the page
    fingerprint (``inspect._update_font_dependencies`` is the cross-document
    form).  Enumerated rather than followed generically so the set is
    auditable against :func:`_build_capability`: the font dictionary itself
    (every key), the indirect targets of /Encoding (its /Differences),
    /Widths, /FirstChar, /LastChar and /FontDescriptor, the descriptor's
    /Flags when indirect, and the raw bytes of whichever /FontFile* program
    ``extract_font`` would load.  If the builder starts reading another
    key, it belongs here in the same change.
    """
    digest = hashlib.sha256()

    def fold(marker: bytes, payload: bytes | None) -> None:
        digest.update(marker)
        digest.update(b"\x00" if payload is None else payload)
        digest.update(b"\x1e")

    if font_xref <= 0:
        # Inline resource dict: nothing is readable through an xref, so the
        # build is deterministic and the digest is a constant.
        fold(b"inline", None)
        return digest.hexdigest()
    try:
        for key in sorted(doc.xref_get_keys(font_xref)):
            kind, value = doc.xref_get_key(font_xref, key)
            fold(
                key.encode("utf-8", "replace"),
                f"{kind}:{value}".encode("latin-1", "replace"),
            )
        for key in ("Encoding", "Widths", "FirstChar", "LastChar", "FontDescriptor"):
            kind, value = doc.xref_get_key(font_xref, key)
            if kind != "xref":
                continue
            try:
                target = int(value.split()[0])
            except (ValueError, IndexError):
                fold(key.encode("ascii"), None)
                continue
            _fold_font_object(fold, doc, key.encode("ascii"), target)
        _fold_descriptor_flags(fold, doc, font_xref)
        for program_key in ("FontFile", "FontFile2", "FontFile3"):
            kind, value = doc.xref_get_key(font_xref, f"FontDescriptor/{program_key}")
            if kind != "xref":
                continue
            marker = program_key.encode("ascii")
            try:
                program_xref = int(value.split()[0])
            except (ValueError, IndexError):
                fold(marker, None)
                continue
            # Stream dict AND raw bytes: a /Filter or /DecodeParms rewrite
            # changes what extract_font decodes from unchanged stored bytes.
            _fold_font_object(fold, doc, marker + b"-dict", program_xref)
            try:
                fold(marker, doc.xref_stream_raw(program_xref))
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                fold(marker, None)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        fold(b"unreadable-font", None)
    return digest.hexdigest()


def _fold_descriptor_flags(
    fold: "Callable[[bytes, bytes | None], None]",
    doc: fitz.Document,
    font_xref: int,
) -> None:
    """Fold exactly what :func:`_is_symbolic` reads: the path-resolved
    ``FontDescriptor/Flags`` value and, when indirect, its target object."""
    kind, value = doc.xref_get_key(font_xref, "FontDescriptor/Flags")
    fold(b"flags", f"{kind}:{value}".encode("latin-1", "replace"))
    if kind == "xref":
        try:
            _fold_font_object(fold, doc, b"flags-obj", int(value.split()[0]))
        except (ValueError, IndexError):
            fold(b"flags-obj", None)


def _type3_evidence_digest(doc: fitz.Document, font_xref: int) -> str:
    """A Type3 build reads nothing past the entry fields except
    ``_is_symbolic`` (for ``ascii_repertoire_attested``) — no /Widths, no
    face, no program — so its digest is just that fold."""
    digest = hashlib.sha256()

    def fold(marker: bytes, payload: bytes | None) -> None:
        digest.update(marker)
        digest.update(b"\x00" if payload is None else payload)
        digest.update(b"\x1e")

    if font_xref <= 0:
        fold(b"inline", None)
        return digest.hexdigest()
    try:
        _fold_descriptor_flags(fold, doc, font_xref)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        fold(b"unreadable-font", None)
    return digest.hexdigest()


def compute_font_evidence_digest(doc: fitz.Document, entry: tuple) -> str:
    """The revalidation digest for one ``page.get_fonts(full=True)`` entry.

    Two layers.  The RESOLVED entry fields MuPDF hands the builder (ext,
    subtype, basefont, encoding) fold first: ``_build_capability`` consumes
    those, not the raw dictionary text, and each may sit behind an indirect
    name object (``/BaseFont 8 0 R``, ``/Subtype 9 0 R``, an inline
    ``/Encoding`` dict whose ``/BaseEncoding`` is a reference) that the
    object-level digest sees only as an unchanged ``"xref:8 0 R"`` (review
    F1: a rewrite of the target served a Helvetica-faced capability for a
    font renamed to Wingdings).  Then the per-subtype object closure — keyed
    on the SUBTYPE, not on whether a cached capability carries a CID codec:
    a Type0 that failed its evidence chain has ``cid is None`` and was
    previously served stale exactly like a simple font.
    """
    font_xref, ext, subtype, basefont, _resource_name, encoding = entry[:6]
    font_xref = int(font_xref)
    if subtype == "Type0":
        inner = compute_cid_evidence_digest(doc, font_xref)
    elif subtype == "Type3":
        inner = _type3_evidence_digest(doc, font_xref)
    else:
        inner = compute_simple_font_evidence_digest(doc, font_xref)
    digest = hashlib.sha256()
    for part in (ext, subtype, basefont, encoding, inner):
        digest.update(str(part).encode("utf-8", "replace"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def _build_capability(
    doc: fitz.Document,
    owner_xref: int,
    entry: tuple,
    evidence_digest: str = "",
) -> FontCapability:
    font_xref, ext, subtype, basefont, resource_name, encoding = entry[:6]
    embedded = ext not in ("n/a", "")

    face: fitz.Font | None = None
    face_source = "none"
    reject: str | None = None
    reject_detail: str | None = None
    simple = False
    advance_source = "none"
    first_char = 0
    widths: tuple[float, ...] | None = None
    cid: IdentityHCidCapability | None = None

    if subtype == "Type3":
        # A Type3 /Widths is in glyph space, scaled by /FontMatrix rather
        # than by 1/1000, so it is not read here at all.
        reject = RejectReason.FONT_TYPE3
    elif subtype == "Type0":
        # Task 12 P0-D: the Identity-H/CIDFontType2 evidence chain. No
        # fitz face is loaded — glyph presence is proven GID-level from
        # the embedded program (subset fonts strip the cmap, so Unicode
        # lookups are useless there; docs/PITFALLS.md), and advances come
        # from the descendant's /W and /DW, never from a face.
        cid_result = build_identity_h_cid_capability(doc, font_xref)
        if isinstance(cid_result, CidCapabilityFailure):
            reject = cid_result.reason
            reject_detail = cid_result.detail
        else:
            cid = cid_result
            advance_source = "cid"
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

        # Only a simple font declares /Widths; a Type0 carries /W on its
        # descendant, which is a different contract and is not read here.
        widths_status = "absent"
        if subtype in _SIMPLE_SUBTYPES:
            widths_status, parsed_first, parsed = _read_width_table(doc, font_xref)
            if widths_status == "ok":
                first_char, widths = parsed_first, parsed
                advance_source = "widths"
        if advance_source == "none" and face is not None:
            advance_source = "face"

        if widths_status == "malformed":
            reject = RejectReason.FONT_WIDTHS_INCOMPLETE
        elif advance_source == "none":
            # Neither a width table nor a face: nothing can prove an advance.
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
        advance_source=advance_source,
        first_char=first_char,
        widths=widths,
        ascii_repertoire_attested=(
            not embedded
            and "+" not in basefont
            and _family_stem(basefont) in _FULL_ASCII_FAMILIES
            and not _is_symbolic(doc, font_xref)
        ),
        cid=cid,
        tier0_reject_detail=reject_detail,
        evidence_digest=evidence_digest,
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
            capabilities[entry[4]] = self._resolve(page, entry)
        return capabilities

    def capability(
        self, page: fitz.Page, resource_name: str
    ) -> FontCapability | None:
        """One resource's capability — digesting/building ONLY that entry.

        ``prepare`` resolves capabilities one show-resource at a time; going
        through :meth:`page_capabilities` would revalidate every font on the
        page per lookup, O(K*N) digests per prepare (review F2: 7x on a
        98-font page).  Same answer as ``page_capabilities(page).get(name)``:
        the last entry carrying ``resource_name`` wins, as in the dict.
        """
        match: tuple | None = None
        for entry in page.get_fonts(full=True):
            if entry[4] == resource_name:
                match = entry
        if match is None:
            return None
        return self._resolve(page, match)

    def _resolve(self, page: fitz.Page, entry: tuple) -> FontCapability:
        owner_xref = int(entry[6]) if len(entry) > 6 and entry[6] else page.xref
        key = (self.generation, owner_xref, entry[4], int(entry[0]))
        # Evidence can change while (generation, xref) stays equal — an
        # in-place /Widths or /Encoding rewrite, an external write bypassing
        # the model's mutation hooks.  Pull-revalidate EVERY hit against the
        # raw evidence digest and rebuild on mismatch: Type0 since Task 12
        # P0-D, simple fonts and rejected Type0 since the Task 13
        # revalidation slice (docs/PITFALLS.md, "Simple-font capabilities
        # are served stale ...").  The digest is taken BEFORE the build so a
        # write racing the build is caught by the next lookup rather than
        # attested as current.
        current = compute_font_evidence_digest(self.doc, entry)
        cached = self._cache.get(key)
        if cached is not None and cached.evidence_digest != current:
            cached = None
        if cached is None:
            cached = _build_capability(self.doc, owner_xref, entry, current)
            self._cache[key] = cached
        return cached
