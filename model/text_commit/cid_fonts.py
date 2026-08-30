"""Identity-H / CIDFontType2 evidence readers and codec (Task 12 P0-D).

LEAF module by design: imports only ``dto`` (plus fitz/stdlib), so the
planner, binding, font registry, and verifier can all consume ONE set of
parsed evidence without an import cycle (``plan → patch → verify →
inspect → fonts`` must never loop back here).

Everything here is fail-closed and bounded. The corpus facts this module
must honor (plan §8, census 2026-08-13):

- The descendant CIDFont is usually an INLINE dictionary in
  ``/DescendantFonts [<<...>>]`` (256/262 corpus fonts, AutoCAD) — parsed
  with a bounded token-aware object parser, never a regex key search.
- ``/DW`` absent (spec default 1000) and ``/CIDToGIDMap`` absent
  (spec-implicit Identity) are the DOMINANT forms.
- ``/CIDSystemInfo`` carries nonstandard producer strings — never gated on.
- Array-destination ``bfrange`` (PDF 32000-1 §9.10.3) is refused with
  ``type0_tounicode_unparseable``, never strided over.

Reason codes are the P0-D contract pinned by
``test_scripts/test_text_commit_cid_hex_tj.py`` — one stable code per
independent gate, and every detail string is code-only (gate class,
counts, structural state): never document text, font names, file names,
or paths.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from decimal import Decimal

import fitz

from model.text_commit.dto import RejectReason

# ------------------------------------------------------------------ bounds

_MAX_OBJECT_TEXT = 1 << 20  # serialized object bodies fed to the parser
_MAX_TOKENS = 50_000
_MAX_DEPTH = 32
_MAX_TOUNICODE_BYTES = 2 << 20
_MAX_TOUNICODE_RECORDS = 65_536
_MAX_CIDTOGID_BYTES = 65_536 * 2  # one uint16 per addressable CID
_MAX_FONT_PROGRAM_BYTES = 64 << 20
_MAX_W_RECORDS = 65_536

_TWO_BYTE_CODE_LIMIT = 0x10000


@dataclass(frozen=True)
class CidCapabilityFailure:
    """A typed, fail-closed refusal from one evidence gate."""

    reason: str  # a RejectReason type0_* constant
    detail: str  # code-only: gate class / counts / structural state


# ==================================================== bounded object parser
#
# A minimal PDF object-syntax parser for SERIALIZED bodies returned by
# ``xref_get_key``/``xref_object``. Token-aware: a ``/Subtype`` inside a
# string operand or a nested dictionary cannot fool it the way a regex key
# search can. Bounded in text length, token count, and nesting depth.


@dataclass(frozen=True)
class PdfRef:
    xref: int


class PdfParseError(ValueError):
    """Raised on malformed or over-budget serialized object text."""


_TOKEN_RE = re.compile(
    rb"<<|>>|\[|\]|/[^\s/<>\[\](){}%]*|\(|<[0-9A-Fa-f\s]*>"
    rb"|[+-]?\d+\.\d*|[+-]?\.\d+|[+-]?\d+|true|false|null|R"
)


def _tokenize(data: bytes) -> list[bytes]:
    if len(data) > _MAX_OBJECT_TEXT:
        raise PdfParseError("serialized object over the parse budget")
    tokens: list[bytes] = []
    pos = 0
    while pos < len(data):
        ch = data[pos : pos + 1]
        if ch.isspace():
            pos += 1
            continue
        if ch == b"(":
            # Literal string: balanced parens with backslash escapes.
            depth = 1
            end = pos + 1
            while end < len(data) and depth:
                c = data[end : end + 1]
                if c == b"\\":
                    end += 2
                    continue
                if c == b"(":
                    depth += 1
                elif c == b")":
                    depth -= 1
                end += 1
            if depth:
                raise PdfParseError("unterminated literal string")
            tokens.append(data[pos:end])
            pos = end
        else:
            match = _TOKEN_RE.match(data, pos)
            if match is None:
                raise PdfParseError(
                    f"unrecognized object syntax at byte {pos}"
                )
            tokens.append(match.group(0))
            pos = match.end()
        if len(tokens) > _MAX_TOKENS:
            raise PdfParseError("serialized object over the token budget")
    return tokens


def _parse_value(tokens: list[bytes], pos: int, depth: int) -> tuple[object, int]:
    if depth > _MAX_DEPTH:
        raise PdfParseError("object nesting over the depth budget")
    if pos >= len(tokens):
        raise PdfParseError("truncated object")
    token = tokens[pos]
    # An indirect reference is "int int R"; resolve by lookahead.
    if (
        token.lstrip(b"+-").isdigit()
        and pos + 2 < len(tokens)
        and tokens[pos + 1].isdigit()
        and tokens[pos + 2] == b"R"
    ):
        return PdfRef(int(token)), pos + 3
    if token == b"<<":
        result: dict[str, object] = {}
        pos += 1
        while pos < len(tokens) and tokens[pos] != b">>":
            key_token = tokens[pos]
            if not key_token.startswith(b"/"):
                raise PdfParseError("dictionary key is not a name")
            value, pos = _parse_value(tokens, pos + 1, depth + 1)
            key = key_token[1:].decode("latin-1")
            # Duplicate keys are refused outright (Task 13 P1 review
            # round): last-key-wins here vs whichever entry mupdf's
            # lookup returns is a real divergence, and viewer behavior on
            # duplicates is undefined — an object that cannot be read
            # unambiguously is not provable evidence.
            if key in result:
                raise PdfParseError("duplicate dictionary key")
            result[key] = value
        if pos >= len(tokens):
            raise PdfParseError("unterminated dictionary")
        return result, pos + 1
    if token == b"[":
        items: list[object] = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != b"]":
            value, pos = _parse_value(tokens, pos, depth + 1)
            items.append(value)
        if pos >= len(tokens):
            raise PdfParseError("unterminated array")
        return items, pos + 1
    if token.startswith(b"/"):
        return token.decode("latin-1"), pos + 1
    if token.startswith(b"("):
        return token[1:-1], pos + 1
    if token.startswith(b"<"):
        digits = bytes(c for c in token[1:-1] if not bytes((c,)).isspace())
        if len(digits) % 2:
            digits += b"0"
        return bytes.fromhex(digits.decode("ascii")), pos + 1
    if token == b"true":
        return True, pos + 1
    if token == b"false":
        return False, pos + 1
    if token == b"null":
        return None, pos + 1
    if token == b"R":
        raise PdfParseError("stray R outside an indirect reference")
    text = token.decode("latin-1")
    if any(c in text for c in ".eE") and text.lstrip("+-") != "":
        return float(text), pos + 1
    return int(text), pos + 1


def parse_pdf_value(data: bytes | str) -> object:
    """Parse one serialized PDF value (dict/array/scalar), bounded."""
    if isinstance(data, str):
        data = data.encode("latin-1", errors="replace")
    tokens = _tokenize(data)
    value, end = _parse_value(tokens, 0, 0)
    if end != len(tokens):
        raise PdfParseError("trailing tokens after object")
    return value


_PDF_NAME_DELIMITERS = frozenset("()<>[]{}/%")


def _validated_pdf_name(value: str, *, leading_slash: bool) -> str:
    body = value[1:] if leading_slash else value
    if not body or any(
        char.isspace() or char in _PDF_NAME_DELIMITERS for char in body
    ):
        raise ValueError("PDF name contains whitespace or delimiters")
    try:
        body.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError("PDF name is outside the supported byte range") from exc
    return f"/{body}"


def _serialize_pdf_float(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("PDF numbers must be finite")
    text = repr(value)
    if "e" in text.lower():
        text = format(Decimal(text), "f")
    if "." not in text:
        text += ".0"
    return text


def serialize_pdf_value(value: object) -> str:
    """Serialize the bounded parser's supported PDF object-value subset.

    Byte strings always use hexadecimal syntax. The parser deliberately does
    not unescape PDF literal strings, so emitting parenthesized strings would
    not provide a type- and byte-preserving round trip.
    """
    if isinstance(value, dict):
        items: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("PDF dictionary keys must be strings")
            items.append(
                f"{_validated_pdf_name(key, leading_slash=False)} "
                f"{serialize_pdf_value(item)}"
            )
        return "<< " + " ".join(items) + " >>"
    if isinstance(value, list):
        return "[ " + " ".join(serialize_pdf_value(item) for item in value) + " ]"
    if isinstance(value, PdfRef):
        if value.xref <= 0:
            raise ValueError("PDF indirect reference xref must be positive")
        return f"{value.xref} 0 R"
    if isinstance(value, str):
        if not value.startswith("/"):
            raise ValueError("only PDF name strings are serializable")
        return _validated_pdf_name(value, leading_slash=True)
    if isinstance(value, bytes):
        return f"<{value.hex().upper()}>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _serialize_pdf_float(value)
    raise ValueError(f"unsupported PDF value type: {type(value).__name__}")


def canonical_pdf_text(value: object) -> str:
    """Order- and whitespace-independent canonical form for digesting.

    Dict keys sorted; numbers normalized; refs as ``R<xref>``; strings as
    hex. Two serializations of the same object tree (e.g. the live
    document vs a ``tobytes()`` scratch copy that re-ordered an inline
    dictionary's keys) canonicalize identically.
    """
    if isinstance(value, dict):
        inner = ",".join(
            f"/{key}:{canonical_pdf_text(item)}"
            for key, item in sorted(value.items())
        )
        return "<<" + inner + ">>"
    if isinstance(value, list):
        return "[" + ",".join(canonical_pdf_text(item) for item in value) + "]"
    if isinstance(value, PdfRef):
        return f"R{value.xref}"
    if isinstance(value, bytes):
        return "s" + value.hex()
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


# ======================================================= descendant resolve


def resolve_descendant(
    doc: fitz.Document, font_xref: int
) -> tuple[int | None, dict[str, object] | None]:
    """``(descendant_xref, parsed_descendant_dict)`` for either corpus form.

    ``/DescendantFonts [N 0 R]`` (or an indirect array) dereferences to the
    descendant object; the inline ``[<<...>>]`` form parses in place and
    reports ``descendant_xref=None``. ``(None, None)`` means unreadable.
    """
    try:
        kind, value = doc.xref_get_key(font_xref, "DescendantFonts")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None, None
    if kind == "xref":
        try:
            target = int(value.split()[0])
            value = doc.xref_object(target)
        except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
            return None, None
    elif kind != "array":
        return None, None
    try:
        parsed = parse_pdf_value(value)
    except PdfParseError:
        return None, None
    if not isinstance(parsed, list) or not parsed:
        return None, None
    first = parsed[0]
    if isinstance(first, PdfRef):
        try:
            body = doc.xref_object(first.xref)
            inner = parse_pdf_value(body)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
            return None, None
        if not isinstance(inner, dict):
            return None, None
        return first.xref, inner
    if isinstance(first, dict):
        return None, first
    return None, None


def _deref(doc: fitz.Document, value: object) -> object:
    """One level of indirection: a PdfRef resolves to its parsed object."""
    if not isinstance(value, PdfRef):
        return value
    try:
        return parse_pdf_value(doc.xref_object(value.xref))
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
        raise PdfParseError(f"unresolvable indirect object {value.xref}")


# ========================================================= ToUnicode parser

_BFCHAR_BLOCK_RE = re.compile(rb"(\d+)\s+beginbfchar(.*?)endbfchar", re.DOTALL)
_BFRANGE_BLOCK_RE = re.compile(rb"(\d+)\s+beginbfrange(.*?)endbfrange", re.DOTALL)
_HEX_ITEM_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>|(\S)")
# CMap comments run % to end-of-line, and CMap hex strings cannot contain
# % — so a line-based strip is safe and required: a commented-out block is
# NOT evidence (adversarial round wf_a93b4e6c-e0f, F9).
_CMAP_COMMENT_RE = re.compile(rb"%[^\r\n]*")


@dataclass(frozen=True)
class ToUnicodeMap:
    """Parsed CMap records in document order (order is the tiebreak the
    deterministic first-wins reverse encoder relies on)."""

    # ("char", cid, cid, text) | ("range", lo, hi, base_scalar_text)
    records: tuple[tuple[str, int, int, str], ...]

    def decode_cid(self, cid: int) -> str | None:
        """Text of one CID per the FIRST record covering it, else None.

        Multi-char (ligature-style) texts are returned as-is — the caller
        decides whether touching one is a refusal (it is, for v1).
        """
        for kind, lo, hi, text in self.records:
            if lo <= cid <= hi:
                if kind == "char":
                    return text
                return chr(ord(text) + (cid - lo))
        return None

    def cids_for_char(self, char: str) -> tuple[int, ...]:
        """Every CID mapping to exactly ``char``, in document order."""
        matches: list[int] = []
        for kind, lo, hi, text in self.records:
            if kind == "char":
                if text == char and lo not in matches:
                    matches.append(lo)
            else:
                offset = ord(char) - ord(text)
                if 0 <= offset <= hi - lo and (lo + offset) not in matches:
                    matches.append(lo + offset)
        return tuple(matches)


def _hex_items(block: bytes) -> list[bytes] | None:
    """The hex-string operands of one bfchar/bfrange block, or None when
    the block contains anything else (an ``[`` array destination, stray
    tokens, malformed hex)."""
    items: list[bytes] = []
    for match in _HEX_ITEM_RE.finditer(block):
        if match.group(2) is not None:
            return None  # any non-hex-string, non-whitespace content
        # Whitespace inside a hex string is spec-legal; normalize it away
        # before the digit-count checks.
        items.append(b"".join(match.group(1).split()))
    return items


def parse_tounicode_strict(data: bytes) -> ToUnicodeMap | CidCapabilityFailure:
    """The v1 ToUnicode grammar: bfchar + SCALAR-destination bfrange only.

    Everything else fails closed as ``type0_tounicode_unparseable`` —
    notably the array-destination bfrange form, which the legacy parser
    used to stride over while fabricating mappings (adversarial round
    wf_a084d864-566).
    """
    unparseable = RejectReason.TYPE0_TOUNICODE_UNPARSEABLE
    if len(data) > _MAX_TOUNICODE_BYTES:
        return CidCapabilityFailure(
            unparseable, "ToUnicode stream over the parse budget"
        )
    data = _CMAP_COMMENT_RE.sub(b"", data)
    records: list[tuple[str, int, int, str]] = []

    char_blocks = _BFCHAR_BLOCK_RE.findall(data)
    range_blocks = _BFRANGE_BLOCK_RE.findall(data)
    if not char_blocks and not range_blocks:
        return CidCapabilityFailure(
            unparseable, "no bfchar or bfrange records"
        )

    for declared, block in char_blocks:
        items = _hex_items(block)
        if items is None or len(items) % 2:
            return CidCapabilityFailure(
                unparseable, "malformed bfchar block"
            )
        if len(items) // 2 != int(declared):
            return CidCapabilityFailure(
                unparseable, "bfchar record count disagrees with declaration"
            )
        for i in range(0, len(items), 2):
            source, destination = items[i], items[i + 1]
            if len(source) != 4:
                return CidCapabilityFailure(
                    unparseable, "bfchar source code is not 2 bytes"
                )
            text = _decode_utf16be_hex(destination)
            if text is None or not text:
                return CidCapabilityFailure(
                    unparseable, "bfchar destination is not valid UTF-16BE"
                )
            cid = int(source, 16)
            records.append(("char", cid, cid, text))

    for declared, block in range_blocks:
        if b"[" in block:
            return CidCapabilityFailure(
                unparseable,
                "array-destination bfrange is outside the v1 grammar",
            )
        items = _hex_items(block)
        if items is None or len(items) % 3:
            return CidCapabilityFailure(
                unparseable, "malformed bfrange block"
            )
        if len(items) // 3 != int(declared):
            return CidCapabilityFailure(
                unparseable, "bfrange record count disagrees with declaration"
            )
        for i in range(0, len(items), 3):
            lo_hex, hi_hex, destination = items[i], items[i + 1], items[i + 2]
            if len(lo_hex) != 4 or len(hi_hex) != 4:
                return CidCapabilityFailure(
                    unparseable, "bfrange source codes are not 2 bytes"
                )
            lo, hi = int(lo_hex, 16), int(hi_hex, 16)
            if lo > hi:
                return CidCapabilityFailure(
                    unparseable, "bfrange low code exceeds high code"
                )
            text = _decode_utf16be_hex(destination)
            if text is None or len(text) != 1:
                # A range destination must be ONE scalar: ranges increment
                # by Unicode scalar value, and the legacy "bump the last
                # code unit" guess is exactly what v1 forbids.
                return CidCapabilityFailure(
                    unparseable,
                    "bfrange destination is not a single Unicode scalar",
                )
            if ord(text) + (hi - lo) > 0x10FFFF:
                return CidCapabilityFailure(
                    unparseable, "bfrange increments past the Unicode range"
                )
            records.append(("range", lo, hi, text))

    if len(records) > _MAX_TOUNICODE_RECORDS:
        return CidCapabilityFailure(
            unparseable, "ToUnicode record count over the parse budget"
        )
    return ToUnicodeMap(records=tuple(records))


def _decode_utf16be_hex(hex_digits: bytes) -> str | None:
    """Strict UTF-16BE decode of a destination hex string, else None."""
    if not hex_digits or len(hex_digits) % 4:
        return None
    try:
        raw = bytes.fromhex(hex_digits.decode("ascii"))
        return raw.decode("utf-16-be", errors="strict")
    except (ValueError, UnicodeDecodeError):
        return None


# ====================================================== glyph program (TTF)


@dataclass(frozen=True)
class GlyphProgram:
    """GID-level presence evidence read from an embedded TrueType program.

    Unicode lookups (``fitz.Font.has_glyph``) are USELESS for subsets —
    the subsetter strips the cmap — so presence is proven from
    ``maxp``/``head``/``loca``/``glyf`` alone (docs/PITFALLS.md).
    """

    num_glyphs: int
    loca: tuple[int, ...]  # num_glyphs + 1 offsets into glyf
    glyf_length: int

    def glyph_data_length(self, gid: int) -> int | None:
        """Outline byte length, or None when loca proves NOTHING for gid.

        A non-monotonic pair or a range past the end of glyf is corrupt
        evidence, not an outline — callers must refuse, never trust the
        subtraction (adversarial round wf_a93b4e6c-e0f, F4).
        """
        if gid < 0 or gid + 1 >= len(self.loca):
            return None
        start, end = self.loca[gid], self.loca[gid + 1]
        if end < start or end > self.glyf_length:
            return None
        return end - start


def parse_truetype_glyph_program(data: bytes) -> GlyphProgram | None:
    """Parse the sfnt tables presence proof needs; None when unreadable."""
    if not data or len(data) > _MAX_FONT_PROGRAM_BYTES or len(data) < 12:
        return None
    tag = data[:4]
    if tag not in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
        return None  # CFF ('OTTO') and unknown containers carry no glyf
    if tag == b"ttcf":
        if len(data) < 16:
            return None
        offset = int.from_bytes(data[12:16], "big")
        if offset + 12 > len(data):
            return None
        return parse_truetype_glyph_program(data[offset:]) if offset else None

    num_tables = int.from_bytes(data[4:6], "big")
    tables: dict[bytes, tuple[int, int]] = {}
    record_end = 12 + num_tables * 16
    if record_end > len(data):
        return None
    for i in range(num_tables):
        base = 12 + i * 16
        table_tag = data[base : base + 4]
        table_offset = int.from_bytes(data[base + 8 : base + 12], "big")
        table_length = int.from_bytes(data[base + 12 : base + 16], "big")
        tables[table_tag] = (table_offset, table_length)

    def table(table_tag: bytes) -> bytes | None:
        entry = tables.get(table_tag)
        if entry is None:
            return None
        offset, length = entry
        if offset + length > len(data):
            return None
        return data[offset : offset + length]

    maxp = table(b"maxp")
    head = table(b"head")
    loca_raw = table(b"loca")
    glyf = table(b"glyf")
    if maxp is None or len(maxp) < 6 or head is None or len(head) < 52:
        return None
    if loca_raw is None or glyf is None:
        return None
    num_glyphs = int.from_bytes(maxp[4:6], "big")
    long_format = int.from_bytes(head[50:52], "big", signed=False) == 1
    entry_size = 4 if long_format else 2
    if len(loca_raw) < (num_glyphs + 1) * entry_size:
        return None
    offsets = []
    for i in range(num_glyphs + 1):
        raw = loca_raw[i * entry_size : (i + 1) * entry_size]
        value = int.from_bytes(raw, "big")
        offsets.append(value * (1 if long_format else 2))
    return GlyphProgram(
        num_glyphs=num_glyphs, loca=tuple(offsets), glyf_length=len(glyf)
    )


# ============================================================== /W and /DW


def parse_w_records(
    doc: fitz.Document, value: object
) -> tuple[tuple[int, int, tuple[float, ...] | float], ...] | None:
    """The two record forms of PDF 32000-1 §9.7.4.3, one-level indirect.

    Returns ``(c_first, c_last, widths)`` records where ``widths`` is a
    per-CID tuple (bracket form) or a single uniform float (triple form);
    ``None`` means present-but-malformed (never downgraded to absent).
    """
    try:
        value = _deref(doc, value)
    except PdfParseError:
        return None
    if not isinstance(value, list):
        return None
    records: list[tuple[int, int, tuple[float, ...] | float]] = []
    i = 0
    while i < len(value):
        first = value[i]
        # bool is an int subclass — a PDF `true` token must never become
        # CID 1 (adversarial round wf_a93b4e6c-e0f, F8).
        if not isinstance(first, int) or isinstance(first, bool) or first < 0:
            return None
        if i + 1 >= len(value):
            return None
        second = value[i + 1]
        if isinstance(second, PdfRef):
            # A /W ELEMENT that is itself indirect is one level deeper than
            # the staleness closure (page fingerprint + cache digest)
            # follows — refuse rather than read evidence the fingerprint
            # cannot see go stale (adversarial round wf_a93b4e6c-e0f, F2).
            return None
        if isinstance(second, list):
            widths: list[float] = []
            for item in second:
                if not isinstance(item, (int, float)) or isinstance(item, bool):
                    return None
                widths.append(float(item))
            if not widths:
                return None
            records.append((first, first + len(widths) - 1, tuple(widths)))
            i += 2
        else:
            if (
                not isinstance(second, int)
                or isinstance(second, bool)
                or second < first
            ):
                return None
            if i + 2 >= len(value):
                return None
            third = value[i + 2]
            if not isinstance(third, (int, float)) or isinstance(third, bool):
                return None
            records.append((first, second, float(third)))
            i += 3
        if len(records) > _MAX_W_RECORDS:
            return None
    return tuple(records)


# =============================================================== capability


@dataclass(frozen=True)
class IdentityHCidCapability:
    """Everything the tiers may do with one Identity-H/CIDFontType2 font.

    Immutable; every field is document evidence, never inference. CID ==
    2-byte big-endian code (Identity-H). ``evidence_digest`` covers the
    builder-visible evidence values for SAME-DOCUMENT cache revalidation
    (the page fingerprint separately covers cross-serialization staleness).
    """

    font_xref: int
    descendant_xref: int | None  # None == inline descendant form
    tounicode: ToUnicodeMap
    cidtogid_table: bytes | None  # None == Identity (name or implicit)
    w_records: tuple[tuple[int, int, tuple[float, ...] | float], ...]
    default_width: float
    glyphs: GlyphProgram
    evidence_digest: str

    # ------------------------------------------------------------ decode

    def decode_show_bytes(self, data: bytes) -> str | CidCapabilityFailure:
        if len(data) % 2:
            return CidCapabilityFailure(
                RejectReason.TYPE0_SOURCE_BYTES_NOT_REPRODUCED,
                "show operand is not a whole number of 2-byte codes",
            )
        out: list[str] = []
        for i in range(0, len(data), 2):
            cid = int.from_bytes(data[i : i + 2], "big")
            text = self.tounicode.decode_cid(cid)
            if text is None:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_UNICODE_UNMAPPED,
                    "a source code has no ToUnicode mapping",
                )
            if len(text) != 1:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_TOUNICODE_MULTICHAR,
                    "a source code maps to a multi-character cluster, "
                    "which is outside the v1 reversibility scope",
                )
            out.append(text)
        return "".join(out)

    # ------------------------------------------------------------ encode

    def encode_first_wins(self, text: str) -> bytes | CidCapabilityFailure:
        """Deterministic reverse encoding: FIRST mapping in document order.

        Used ONLY for the source-reproduction proof — the result must then
        byte-equal the show operand, so a competing earlier mapping is
        caught by comparison, never trusted.
        """
        out = bytearray()
        for char in text:
            cids = self.tounicode.cids_for_char(char)
            if not cids:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_UNICODE_UNMAPPED,
                    "no CID maps to a character of the bound source text",
                )
            out += cids[0].to_bytes(2, "big")
        return bytes(out)

    def encode_strict(
        self, text: str
    ) -> tuple[int, ...] | CidCapabilityFailure:
        """Replacement encoding: every character must map to EXACTLY one
        CID — zero is unmapped, two or more is ambiguity, both refusals."""
        cids: list[int] = []
        for char in text:
            matches = self.tounicode.cids_for_char(char)
            if not matches:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_UNICODE_UNMAPPED,
                    "no CID maps to a replacement character",
                )
            if len(matches) > 1:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_TOUNICODE_AMBIGUOUS,
                    f"{len(matches)} CIDs map to one replacement character",
                )
            cids.append(matches[0])
        return tuple(cids)

    # ------------------------------------------------------- glyph gates

    def gid_for(self, cid: int) -> int | CidCapabilityFailure:
        if self.cidtogid_table is None:
            return cid  # Identity: explicit name or the spec-implicit default
        index = cid * 2
        if index + 2 > len(self.cidtogid_table):
            return CidCapabilityFailure(
                RejectReason.TYPE0_CID_OUT_OF_MAP_RANGE,
                "a required CID lies beyond the CIDToGIDMap table",
            )
        return int.from_bytes(self.cidtogid_table[index : index + 2], "big")

    def glyph_gate(
        self, cids: tuple[int, ...], text: str
    ) -> CidCapabilityFailure | None:
        """The three distinct GID-stage refusals, in gate-chain order."""
        for cid, char in zip(cids, text):
            gid = self.gid_for(cid)
            if isinstance(gid, CidCapabilityFailure):
                return gid
            if gid == 0:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_GID_ZERO,
                    "the CIDToGIDMap resolves a required CID to .notdef",
                )
            if gid >= self.glyphs.num_glyphs:
                return CidCapabilityFailure(
                    RejectReason.TYPE0_GID_BEYOND_GLYPH_COUNT,
                    "a resolved GID lies beyond the embedded glyph count",
                )
            data_length = self.glyphs.glyph_data_length(gid)
            if data_length is None or (data_length == 0 and not char.isspace()):
                return CidCapabilityFailure(
                    RejectReason.TYPE0_GLYPH_MISSING,
                    "the embedded subset carries no outline for a "
                    "required glyph",
                )
        return None

    # ------------------------------------------------------------ widths

    def width_of_cid(self, cid: int) -> float:
        """Advance in 1/1000 text-space units; /W first match, else /DW.

        Unlike the simple-font /Widths heuristic, a declared zero is
        believed: CID width records legitimately declare zero-advance
        marks, and /DW (default 1000) is the spec's own fallback, not a
        guess.
        """
        for first, last, widths in self.w_records:
            if first <= cid <= last:
                if isinstance(widths, tuple):
                    return widths[cid - first]
                return widths
        return self.default_width

    def advance_points(
        self, cids: tuple[int, ...], size: float, char_spacing: float
    ) -> float:
        """Consumed advance in points. Word spacing never applies: PDF
        32000-1 §9.3.3 applies it only to SINGLE-byte code 32, and
        Identity-H codes are always two bytes."""
        total = sum(self.width_of_cid(cid) for cid in cids)
        return total / 1000.0 * size + char_spacing * len(cids)

    def encode_cids(self, cids: tuple[int, ...]) -> bytes:
        return b"".join(cid.to_bytes(2, "big") for cid in cids)


# ============================================================ construction


def _stream_bytes(doc: fitz.Document, xref: int) -> bytes | None:
    try:
        return doc.xref_stream(xref)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None


def compute_cid_evidence_digest(doc: fitz.Document, font_xref: int) -> str:
    """Digest every builder-visible evidence value the capability read.

    SAME-DOCUMENT identity only — used by the registry cache to refuse a
    stale capability, not by the page fingerprint. Stream evidence is folded
    exactly as the builder consumes it: decoded ``xref_stream()`` bytes via
    :func:`_stream_bytes`. Hashing stored bytes instead would miss direct or
    indirect decoding-metadata rewrites that change the builder's input while
    leaving ``xref_stream_raw()`` byte-identical.
    """
    digest = hashlib.sha256()

    def fold(marker: bytes, payload: bytes | None) -> None:
        digest.update(marker)
        digest.update(b"\x00" if payload is None else payload)
        digest.update(b"\x1e")

    try:
        kind, value = doc.xref_get_key(font_xref, "Encoding")
        fold(b"enc", f"{kind}:{value}".encode("latin-1", "replace"))
        kind, value = doc.xref_get_key(font_xref, "ToUnicode")
        fold(b"tu-ref", f"{kind}:{value}".encode("latin-1", "replace"))
        if kind == "xref":
            try:
                target = int(value.split()[0])
                fold(b"tu", _stream_bytes(doc, target))
            except (ValueError, IndexError):
                fold(b"tu", None)
        descendant_xref, descendant = resolve_descendant(doc, font_xref)
        if descendant is None:
            fold(b"desc", None)
        else:
            fold(b"desc", canonical_pdf_text(descendant).encode("utf-8"))
            # Every indirect target the capability build dereferences must
            # fold here too, or an external write to it revalidates a stale
            # capability (adversarial round wf_a93b4e6c-e0f, F3): /W, /DW,
            # and the descriptor — for BOTH descriptor forms.
            for key in ("W", "DW", "FontDescriptor"):
                value_obj = descendant.get(key)
                if isinstance(value_obj, PdfRef):
                    try:
                        fold(
                            key.encode("ascii"),
                            doc.xref_object(value_obj.xref).encode(
                                "latin-1", "replace"
                            ),
                        )
                    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                        fold(key.encode("ascii"), None)
            cidtogid = descendant.get("CIDToGIDMap")
            if isinstance(cidtogid, PdfRef):
                fold(b"c2g", _stream_bytes(doc, cidtogid.xref))
            descriptor: object = descendant.get("FontDescriptor")
            if isinstance(descriptor, PdfRef):
                try:
                    descriptor = parse_pdf_value(doc.xref_object(descriptor.xref))
                except (
                    RuntimeError,
                    ValueError,
                    fitz.mupdf.FzErrorBase,
                    PdfParseError,
                ):
                    descriptor = None
            if isinstance(descriptor, dict):
                font_file = descriptor.get("FontFile2")
                if isinstance(font_file, PdfRef):
                    fold(b"ff2", _stream_bytes(doc, font_file.xref))
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        fold(b"err", b"unreadable")
    return digest.hexdigest()


def build_identity_h_cid_capability(
    doc: fitz.Document, font_xref: int
) -> IdentityHCidCapability | CidCapabilityFailure:
    """Build the full evidence chain for one Type0 font, fail-closed.

    Gate order matches the funnel: encoding form → descendant subtype →
    embedded program → ToUnicode (missing, then grammar) → CIDToGIDMap →
    /W and /DW. Each refusal carries its own stable reason code.
    """
    if font_xref <= 0:
        return CidCapabilityFailure(
            RejectReason.TYPE0_DESCENDANT_UNSUPPORTED,
            "inline font resource dictionary is not addressable",
        )
    try:
        kind, value = doc.xref_get_key(font_xref, "Encoding")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        kind, value = "null", "null"
    if kind != "name" or value.lstrip("/") != "Identity-H":
        return CidCapabilityFailure(
            RejectReason.TYPE0_ENCODING_UNSUPPORTED,
            "encoding is not the Identity-H name form "
            f"(structural kind: {kind})",
        )

    descendant_xref, descendant = resolve_descendant(doc, font_xref)
    if descendant is None:
        return CidCapabilityFailure(
            RejectReason.TYPE0_DESCENDANT_UNSUPPORTED,
            "descendant CIDFont is missing or unreadable",
        )
    if descendant.get("Subtype") != "/CIDFontType2":
        return CidCapabilityFailure(
            RejectReason.TYPE0_DESCENDANT_UNSUPPORTED,
            "descendant subtype is not CIDFontType2",
        )

    descriptor = descendant.get("FontDescriptor")
    if isinstance(descriptor, PdfRef):
        try:
            descriptor = _deref(doc, descriptor)
        except PdfParseError:
            descriptor = None
    program_data: bytes | None = None
    if isinstance(descriptor, dict):
        font_file = descriptor.get("FontFile2")
        if isinstance(font_file, PdfRef):
            program_data = _stream_bytes(doc, font_file.xref)
    if not program_data:
        return CidCapabilityFailure(
            RejectReason.TYPE0_FONT_NOT_EMBEDDED,
            "descendant declares no readable FontFile2 program",
        )
    glyphs = parse_truetype_glyph_program(program_data)
    if glyphs is None:
        return CidCapabilityFailure(
            RejectReason.TYPE0_GLYPH_MISSING,
            "embedded program's glyph tables are unreadable; no glyph "
            "can be proven present",
        )

    try:
        tu_kind, tu_value = doc.xref_get_key(font_xref, "ToUnicode")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        tu_kind, tu_value = "null", "null"
    if tu_kind == "null":
        return CidCapabilityFailure(
            RejectReason.TYPE0_TOUNICODE_MISSING,
            "font declares no ToUnicode CMap",
        )
    tounicode_bytes: bytes | None = None
    if tu_kind == "xref":
        try:
            tounicode_bytes = _stream_bytes(doc, int(tu_value.split()[0]))
        except (ValueError, IndexError):
            tounicode_bytes = None
    if not tounicode_bytes:
        return CidCapabilityFailure(
            RejectReason.TYPE0_TOUNICODE_UNPARSEABLE,
            "ToUnicode is present but its stream is unreadable or empty",
        )
    tounicode = parse_tounicode_strict(tounicode_bytes)
    if isinstance(tounicode, CidCapabilityFailure):
        return tounicode

    cidtogid_table: bytes | None = None
    cidtogid = descendant.get("CIDToGIDMap")
    if cidtogid is None or cidtogid == "/Identity":
        cidtogid_table = None
    elif isinstance(cidtogid, PdfRef):
        cidtogid_table = _stream_bytes(doc, cidtogid.xref)
        if (
            not cidtogid_table
            or len(cidtogid_table) % 2
            or len(cidtogid_table) > _MAX_CIDTOGID_BYTES
        ):
            return CidCapabilityFailure(
                RejectReason.TYPE0_CIDTOGID_UNREADABLE,
                "CIDToGIDMap stream is missing, odd-length, or over budget",
            )
    else:
        return CidCapabilityFailure(
            RejectReason.TYPE0_CIDTOGID_UNREADABLE,
            "CIDToGIDMap is neither Identity nor a readable stream",
        )

    w_value = descendant.get("W")
    if w_value is None:
        w_records: tuple[tuple[int, int, tuple[float, ...] | float], ...] = ()
    else:
        parsed_w = parse_w_records(doc, w_value)
        if parsed_w is None:
            return CidCapabilityFailure(
                RejectReason.TYPE0_WIDTH_UNPROVABLE,
                "/W is present but malformed; present-but-unusable is "
                "never downgraded to absent",
            )
        w_records = parsed_w

    dw_value = descendant.get("DW")
    if dw_value is None:
        default_width = 1000.0
    else:
        try:
            dw_value = _deref(doc, dw_value)
        except PdfParseError:
            dw_value = None
        if (
            not isinstance(dw_value, (int, float))
            or isinstance(dw_value, bool)
            or not (float(dw_value) == float(dw_value))  # NaN guard
        ):
            return CidCapabilityFailure(
                RejectReason.TYPE0_WIDTH_UNPROVABLE,
                "/DW is present but is not a finite number",
            )
        default_width = float(dw_value)

    return IdentityHCidCapability(
        font_xref=font_xref,
        descendant_xref=descendant_xref,
        tounicode=tounicode,
        cidtogid_table=cidtogid_table,
        w_records=w_records,
        default_width=default_width,
        glyphs=glyphs,
        evidence_digest=compute_cid_evidence_digest(doc, font_xref),
    )
