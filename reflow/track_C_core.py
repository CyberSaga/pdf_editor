"""
track_C_core.py — Track C: Non-Destructive Content-Stream Text Editing Engine

Phase 1 (this file): Same-line text replacement for WinAnsi/builtin-font TJ operators.
- Directly edits TJ/Tj operators in the PDF content stream.
- Preserves kerning values, font metrics, and reading order.
- Falls back (via explicit rejection) for Identity-H fonts, Form XObjects,
  ambiguous matches, complex escape sequences, etc.

Phase 2 (future): Displacement of subsequent BT/ET blocks after length-changing edits.
Phase 3 (future): Identity-H (CIDFont) support via CMap/ToUnicode parsing.
"""

from __future__ import annotations

import io
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import fitz

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Compiled regex patterns
# ──────────────────────────────────────────────────────────────────────────────
RE_BT = re.compile(rb'\bBT\b')
RE_ET = re.compile(rb'\bET\b')
RE_TM = re.compile(
    rb'([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+'
    rb'([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+Tm\b'
)
RE_TF = re.compile(rb'/(\S+)\s+([\d.]+(?:\.\d*)?)\s+Tf\b')
RE_DO = re.compile(rb'/(\S+)\s+Do\b')
RE_NUMBER = re.compile(rb'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')

# Builtin fitz font short names (always WinAnsi/latin-1 compatible)
_BUILTIN_FITZ_FONTS = frozenset({
    "helv", "helvetica",
    "cour", "courier",
    "tiro", "times-roman", "times",
    "zadb", "zapfdingbats",
    "symb", "symbol",
})

# PDF whitespace bytes
_PDF_WS = frozenset([0x20, 0x09, 0x0A, 0x0D, 0x00, 0x0C])
# PDF delimiter bytes that follow an operator token
_PDF_DELIMITERS = frozenset([0x20, 0x09, 0x0A, 0x0D, 0x2F, 0x28, 0x3C, 0x5B, 0x25, 0x00])


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TJItem:
    """One item inside a TJ array: a decoded string or a kerning number."""
    kind: str        # "STR" or "KERN"
    value: Any       # str (decoded text) or float (kerning)
    raw_start: int   # byte offset in the full content stream
    raw_end: int     # byte offset end (exclusive)


@dataclass
class TJOp:
    """One [...] TJ operator with its items and metadata."""
    raw_start: int              # byte offset of '[' in stream
    raw_end: int                # byte offset after 'TJ' (exclusive)
    items: list                 # list[TJItem]
    decoded_text: str           # concatenated text from all STR items
    has_complex_escapes: bool = False  # True if any STR item has octal escapes


@dataclass
class BTETBlock:
    """One BT...ET text block with its TJ operators."""
    tm_x: float = 0.0
    tm_y: float = 0.0
    font_name: str = ""
    font_size: float = 12.0
    encoding: str = "unknown"   # "latin-1" | "identity-h" | "unknown"
    tj_ops: list = field(default_factory=list)   # list[TJOp]
    stream_xref: int = 0
    block_start: int = 0        # byte offset of 'BT' in stream
    block_end: int = 0          # byte offset after 'ET'
    all_text: str = ""          # concatenation of all TJOp decoded_text


# ──────────────────────────────────────────────────────────────────────────────
# TrackCEngine
# ──────────────────────────────────────────────────────────────────────────────

class TrackCEngine:
    """
    Track C: Non-destructive content-stream-level text replacement.

    Phase 1: Handles WinAnsi/builtin fonts; single BT/ET block same-line replacement.
    Rejects Identity-H, Form XObjects, ambiguous matches, complex escape sequences.

    Usage::

        engine = TrackCEngine()
        ok, reason = engine.can_handle(page, original_text, new_text, rect)
        if ok:
            result = engine.apply_edit(doc, page_idx, rect, original_text, new_text)
    """

    # ── Low-level string utilities ────────────────────────────────────────────

    @staticmethod
    def _find_paren_end(data: bytes, open_pos: int) -> int:
        """Return the index of the closing ')' matching '(' at open_pos.

        Respects backslash escapes.  Returns len(data)-1 if unterminated.
        """
        i = open_pos + 1
        depth = 1
        while i < len(data):
            c = data[i]
            if c == 0x5C:       # backslash — skip next byte
                i += 2
                continue
            if c == 0x28:       # (
                depth += 1
            elif c == 0x29:     # )
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return max(0, len(data) - 1)

    @staticmethod
    def _decode_paren_string(raw: bytes) -> str:
        """Decode raw bytes (the content *inside* parentheses) to a Python str.

        Handles: \\n \\r \\t \\b \\f \\( \\) \\\\ and octal \\NNN.
        """
        result = []
        i = 0
        while i < len(raw):
            c = raw[i]
            if c == 0x5C:           # backslash
                i += 1
                if i >= len(raw):
                    break
                nc = raw[i]
                ESC = {0x6E: '\n', 0x72: '\r', 0x74: '\t',
                       0x62: '\b', 0x66: '\f',
                       0x28: '(',  0x29: ')', 0x5C: '\\'}
                if nc in ESC:
                    result.append(ESC[nc])
                elif 0x30 <= nc <= 0x37:    # octal
                    octal_str = chr(nc)
                    for _ in range(2):
                        i += 1
                        if i < len(raw) and 0x30 <= raw[i] <= 0x37:
                            octal_str += chr(raw[i])
                        else:
                            i -= 1
                            break
                    result.append(chr(int(octal_str, 8) & 0xFF))
                else:
                    result.append(chr(nc))
            else:
                result.append(chr(c))
            i += 1
        return ''.join(result)

    @staticmethod
    def _has_complex_escapes(raw: bytes) -> bool:
        """Return True if raw bytes (inside parentheses) contain octal escapes."""
        i = 0
        while i < len(raw):
            if raw[i] == 0x5C and i + 1 < len(raw):
                nc = raw[i + 1]
                if 0x30 <= nc <= 0x37:
                    return True
                i += 2
            else:
                i += 1
        return False

    @staticmethod
    def _encode_paren_string(text: str) -> bytes:
        """Encode a Python str as the inner bytes of a PDF parenthesized string.

        Only escapes the minimum needed: ( ) \\.
        Raises ValueError if any character is outside latin-1.
        """
        out = []
        for ch in text:
            cp = ord(ch)
            if cp > 255:
                raise ValueError(
                    f"Character {ch!r} (U+{cp:04X}) is outside latin-1; "
                    "cannot encode for WinAnsi content stream."
                )
            b = cp
            if b == 0x28:           # (
                out += [0x5C, 0x28]
            elif b == 0x29:         # )
                out += [0x5C, 0x29]
            elif b == 0x5C:         # \
                out += [0x5C, 0x5C]
            else:
                out.append(b)
        return bytes(out)

    # ── Content-stream tokenizer ──────────────────────────────────────────────

    def _find_tj_ops_in_range(
        self, stream: bytes, start: int, end: int
    ) -> list:
        """Tokenise stream[start:end] to find all TJ and Tj text-show operators.

        Returns list of 4-tuples (kind, item_start, content_end, op_end):
          kind         : 'TJ' or 'Tj'
          item_start   : position of '[' (TJ) or '(' / '<' (Tj)
          content_end  : position of ']' exclusive (TJ) or after ')' / '>' (Tj)
                         i.e. for TJ use stream[item_start+1 : content_end]
                              for Tj use stream[item_start : content_end]
          op_end       : position just after 'TJ' or 'Tj'
        """
        results = []
        i = start
        while i < end:
            b = stream[i]

            # Skip PDF comments
            if b == 0x25:       # '%'
                while i < end and stream[i] not in (0x0A, 0x0D):
                    i += 1
                continue

            # '(' — either a standalone Tj string or standalone operand
            if b == 0x28:
                str_start = i
                close = self._find_paren_end(stream, i)
                j = close + 1
                while j < end and stream[j] in _PDF_WS:
                    j += 1
                if j + 1 < end and stream[j:j+2] == b'Tj':
                    if j + 2 >= end or stream[j + 2] in _PDF_DELIMITERS:
                        # content_end = close+1 so _decode_tj_items sees '(' at str_start
                        results.append(('Tj', str_start, close + 1, j + 2))
                i = close + 1
                continue

            # '<' — either a standalone hex Tj string or hex operand
            if b == 0x3C:
                str_start = i
                try:
                    close = stream.index(0x3E, i + 1)
                except ValueError:
                    i += 1
                    continue
                if close >= end:
                    i += 1
                    continue
                j = close + 1
                while j < end and stream[j] in _PDF_WS:
                    j += 1
                if j + 1 < end and stream[j:j+2] == b'Tj':
                    if j + 2 >= end or stream[j + 2] in _PDF_DELIMITERS:
                        results.append(('Tj', str_start, close + 1, j + 2))
                i = close + 1
                continue

            # '[' — possible TJ array
            if b == 0x5B:
                array_open = i
                i += 1
                close_bracket = -1
                while i < end:
                    c = stream[i]
                    if c == 0x28:
                        i = self._find_paren_end(stream, i) + 1
                    elif c == 0x3C:
                        try:
                            close = stream.index(0x3E, i + 1)
                            i = close + 1 if close < end else i + 1
                        except ValueError:
                            i += 1
                    elif c == 0x5D:     # ']'
                        close_bracket = i
                        i += 1
                        break
                    else:
                        i += 1

                if close_bracket == -1:
                    continue    # unterminated array

                # Skip whitespace between ']' and operator
                while i < end and stream[i] in _PDF_WS:
                    i += 1

                if i + 1 < end and stream[i:i+2] == b'TJ':
                    if i + 2 >= end or stream[i + 2] in _PDF_DELIMITERS:
                        # content_end = close_bracket so decode reads stream[array_open+1 : close_bracket]
                        results.append(('TJ', array_open, close_bracket, i + 2))
                    i += 2

                continue

            i += 1

        return results

    def _decode_tj_items(
        self, stream: bytes, content_start: int, content_end: int
    ) -> tuple:
        """Parse the inner content of a TJ array into TJItem objects.

        content_start/end are the positions *inside* '[...]' in the full stream.
        Returns (list[TJItem], has_complex_escapes: bool).
        """
        items = []
        has_complex = False
        i = content_start

        while i < content_end:
            b = stream[i]

            if b in _PDF_WS:
                i += 1
                continue

            if b == 0x28:       # '(' — parenthesised string
                close = self._find_paren_end(stream, i)
                raw_inner = stream[i + 1:close]
                if self._has_complex_escapes(raw_inner):
                    has_complex = True
                decoded = self._decode_paren_string(raw_inner)
                items.append(TJItem("STR", decoded, i, close + 1))
                i = close + 1

            elif b == 0x3C:     # '<' — hex string
                try:
                    close = stream.index(0x3E, i + 1)
                except ValueError:
                    i += 1
                    continue
                if close > content_end:
                    i += 1
                    continue
                hex_bytes = stream[i + 1:close]
                try:
                    raw_bytes = bytes.fromhex(hex_bytes.decode('ascii', errors='replace'))
                    decoded = raw_bytes.decode('latin-1', errors='replace')
                except Exception:
                    decoded = ""
                items.append(TJItem("STR", decoded, i, close + 1))
                i = close + 1

            elif (b in (0x2B, 0x2D)                     # + -
                  or (0x30 <= b <= 0x39)                 # 0-9
                  or b == 0x2E):                         # .
                m = RE_NUMBER.match(stream, i)
                if m and m.end() <= content_end:
                    try:
                        val = float(m.group())
                    except ValueError:
                        val = 0.0
                    items.append(TJItem("KERN", val, i, m.end()))
                    i = m.end()
                else:
                    i += 1

            else:
                i += 1

        return items, has_complex

    # ── Font encoding detection ───────────────────────────────────────────────

    def _detect_font_encoding(
        self, doc: fitz.Document, page: fitz.Page, font_name: str
    ) -> str:
        """Return "latin-1", "identity-h", or "unknown" for a font resource name.

        font_name is as it appears after '/' in the Tf operator, e.g. "helv", "F1".
        """
        # Strip leading '/' if present
        font_name = font_name.lstrip("/")
        bare = font_name.split("+")[-1].lower()

        if bare in _BUILTIN_FITZ_FONTS:
            return "latin-1"

        for f in page.get_fonts():
            # Tuple: (xref, ext, type, basefont, name, encoding, referencer)
            if len(f) < 6:
                continue
            xref, _ext, ftype, basefont, fname, fencoding = f[0], f[1], f[2], f[3], f[4], f[5]

            if fname != font_name:
                continue

            # CIDFont / Type0 → always identity-h territory
            if "CIDFont" in ftype or "Type0" in ftype:
                return "identity-h"

            # Check encoding string
            if "Identity-H" in fencoding or "Identity-V" in fencoding:
                return "identity-h"
            if fencoding in (
                "WinAnsiEncoding", "MacRomanEncoding",
                "StandardEncoding", "PDFDocEncoding", "",
            ):
                return "latin-1"

            # Check basefont name
            bare_base = basefont.split("+")[-1].lower()
            if bare_base in _BUILTIN_FITZ_FONTS:
                return "latin-1"

            # Try reading xref directly
            if xref > 0:
                try:
                    enc_val = str(doc.xref_get_key(xref, "Encoding"))
                    if "Identity-H" in enc_val or "Identity-V" in enc_val:
                        return "identity-h"
                    if any(k in enc_val for k in ("WinAnsi", "MacRoman", "Standard")):
                        return "latin-1"
                except Exception:
                    pass

            return "unknown"

        # Not found in page fonts — maybe it's a builtin
        if bare in _BUILTIN_FITZ_FONTS or font_name.lower() in _BUILTIN_FITZ_FONTS:
            return "latin-1"

        return "unknown"

    # ── Block parser ─────────────────────────────────────────────────────────

    def _parse_bt_et_blocks(
        self,
        stream: bytes,
        stream_xref: int,
        doc: fitz.Document,
        page: fitz.Page,
    ) -> list:
        """Parse a content stream into a list of BTETBlock objects."""
        blocks = []

        bt_positions = [m.start() for m in RE_BT.finditer(stream)]
        et_positions = [m.start() for m in RE_ET.finditer(stream)]

        used_et: set = set()
        for bt_pos in bt_positions:
            # Find first ET after this BT
            et_pos = None
            for ep in et_positions:
                if ep > bt_pos and ep not in used_et:
                    et_pos = ep
                    break
            if et_pos is None:
                continue
            used_et.add(et_pos)
            et_end = et_pos + 2     # after "ET"

            # Extract last Tm in this block
            tm_x, tm_y = 0.0, 0.0
            for m in RE_TM.finditer(stream, bt_pos, et_end):
                try:
                    tm_x = float(m.group(5))
                    tm_y = float(m.group(6))
                except (ValueError, IndexError):
                    pass

            # Extract last Tf in this block
            font_name = ""
            font_size = 12.0
            for m in RE_TF.finditer(stream, bt_pos, et_end):
                try:
                    font_name = m.group(1).decode('latin-1', errors='replace')
                    font_size = float(m.group(2))
                except (ValueError, IndexError):
                    pass

            encoding = self._detect_font_encoding(doc, page, font_name)

            # Find all TJ and Tj operators in this block
            tj_positions = self._find_tj_ops_in_range(stream, bt_pos, et_end)
            tj_ops = []
            for (kind, item_start, content_end, op_end) in tj_positions:
                if kind == 'TJ':
                    # TJ: decode stream[item_start+1 : content_end]
                    # (content_end is position of ']')
                    decode_start = item_start + 1
                    decode_end = content_end
                else:
                    # Tj: decode stream[item_start : content_end]
                    # (item_start is '(' or '<'; content_end is exclusive close)
                    decode_start = item_start
                    decode_end = content_end

                items, has_complex = self._decode_tj_items(stream, decode_start, decode_end)
                decoded_text = "".join(it.value for it in items if it.kind == "STR")
                tj_ops.append(TJOp(
                    raw_start=item_start,
                    raw_end=op_end,
                    items=items,
                    decoded_text=decoded_text,
                    has_complex_escapes=has_complex,
                ))

            all_text = "".join(op.decoded_text for op in tj_ops)
            blocks.append(BTETBlock(
                tm_x=tm_x,
                tm_y=tm_y,
                font_name=font_name,
                font_size=font_size,
                encoding=encoding,
                tj_ops=tj_ops,
                stream_xref=stream_xref,
                block_start=bt_pos,
                block_end=et_end,
                all_text=all_text,
            ))

        return blocks

    # ── Span matcher ─────────────────────────────────────────────────────────

    def _match_span_to_block(
        self,
        blocks: list,
        origin_x: float,
        origin_y_pdf: float,
        target_text: str,
        tolerance: float = 3.0,
    ) -> tuple:
        """Find the BTETBlock and TJOp index matching the target position and text.

        Returns (block, tj_index) or (None, -1).
        Tries tolerance=3pt first, then 6pt, then searches all blocks.
        """
        def dist(b: BTETBlock) -> float:
            return math.hypot(b.tm_x - origin_x, b.tm_y - origin_y_pdf)

        # Position-first: try within tolerance
        for tol in (tolerance, tolerance * 2):
            candidates = sorted(
                [b for b in blocks if dist(b) <= tol], key=dist
            )
            for block in candidates:
                for idx, tj_op in enumerate(block.tj_ops):
                    if target_text in tj_op.decoded_text:
                        return block, idx

        # Fallback: ignore position, scan all blocks by distance
        for block in sorted(blocks, key=dist):
            for idx, tj_op in enumerate(block.tj_ops):
                if target_text in tj_op.decoded_text:
                    return block, idx

        return None, -1

    def _count_matching_tj_ops(self, blocks: list, target_text: str) -> int:
        """Count how many individual TJOps across all blocks contain target_text."""
        return sum(
            1
            for b in blocks
            for op in b.tj_ops
            if target_text in op.decoded_text
        )

    # ── Post-edit verification ───────────────────────────────────────────────

    @staticmethod
    def _find_stable_span(page: fitz.Page, exclude_rect: fitz.Rect) -> Optional[str]:
        """Return a short stable text snippet from outside exclude_rect."""
        try:
            td = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for blk in td.get("blocks", []):
                if blk.get("type") != 0:
                    continue
                for line in blk.get("lines", []):
                    for span in line.get("spans", []):
                        bbox = fitz.Rect(span["bbox"])
                        if bbox.intersects(exclude_rect):
                            continue
                        chars = span.get("chars", [])
                        text = (
                            "".join(ch.get("c", "") for ch in chars)
                            or span.get("text", "")
                        ).strip()
                        if len(text) >= 3:
                            return text[:20]
        except Exception:
            pass
        return None

    @staticmethod
    def _verify_edit(
        doc: fitz.Document,
        page_idx: int,
        target_rect: fitz.Rect,
        old_text: str,
        new_text: str,
        stable_text: Optional[str],
    ) -> str:
        """Run 4 post-edit checks. Returns "" on success or a failure reason."""
        page = doc[page_idx]

        # a. New text present in target area
        clip_text = page.get_text("text", clip=target_rect).strip()
        if new_text and new_text not in clip_text:
            return (
                f"verification failed: new text not found in target rect "
                f"(got: {clip_text!r})"
            )

        # b. Old text gone from target area
        if old_text and old_text in clip_text:
            return "verification failed: old text still present in target rect"

        # c. Collateral check: stable span outside target_rect still present
        if stable_text:
            full_text = page.get_text("text")
            if stable_text not in full_text:
                return (
                    f"verification failed: collateral text damaged "
                    f"(lost: {stable_text!r})"
                )

        # d. Stream is still a valid parseable PDF
        try:
            buf = io.BytesIO(doc.tobytes(garbage=0))
            test_doc = fitz.open("pdf", buf)
            test_doc.close()
        except Exception as exc:
            return f"verification failed: stream corrupted ({exc})"

        return ""

    # ── Public API ────────────────────────────────────────────────────────────

    def can_handle(
        self,
        page: fitz.Page,
        target_text: str,
        new_text: str,
        target_rect: fitz.Rect,
    ) -> tuple:
        """Pre-flight check: can Track C handle this edit?

        Returns (True, "") if OK, or (False, reason) where reason is always
        a non-empty descriptive string.  Never returns (False, "").
        """
        doc = page.parent

        # 1. No content stream
        xrefs = page.get_contents()
        if not xrefs:
            return False, "no content stream"

        # 2. New-text character range (fast, before parsing)
        for ch in new_text:
            if ord(ch) > 255:
                return False, "character outside latin-1"

        # Collect all blocks across xrefs
        all_blocks = []
        for xref in xrefs:
            try:
                stream = doc.xref_stream(xref)
            except Exception as exc:
                return False, f"cannot read content stream xref {xref}: {exc}"

            # 3. Form XObject (Do operator) present
            if RE_DO.search(stream):
                return False, "form xobject"

            blocks = self._parse_bt_et_blocks(stream, xref, doc, page)
            all_blocks.extend(blocks)

        # 4. Encoding checks
        for block in all_blocks:
            if block.encoding == "identity-h":
                return False, "identity-h encoding"
            if block.encoding == "unknown":
                return False, "unknown font encoding"

        # 5. Target text not found at all
        match_count = self._count_matching_tj_ops(all_blocks, target_text)
        if match_count == 0:
            return False, "target text not found in stream"

        # 6. Ambiguous: target_text appears in more than one TJ op
        #    (covers both multi-block and same-block-with-Td-displacement cases)
        if match_count > 1:
            return False, "ambiguous match: target text appears in multiple TJ operators"

        # 7. Complex escapes and kern-boundary checks in the matched TJ op
        for block in all_blocks:
            for tj_op in block.tj_ops:
                if target_text not in tj_op.decoded_text:
                    continue
                if tj_op.has_complex_escapes:
                    return False, "complex escape sequence in string"
                # Check whether target_text spans multiple STR items with KERN between them
                str_items = [it for it in tj_op.items if it.kind == "STR"]
                if len(str_items) > 1:
                    fits_single = any(target_text in it.value for it in str_items)
                    if not fits_single:
                        return False, "ambiguous split: target text crosses kern boundary"

        return True, ""

    def apply_edit(
        self,
        doc: fitz.Document,
        page_idx: int,
        target_rect: fitz.Rect,
        target_text: str,
        new_text: str,
        font: str = "",
        size: float = 0.0,
    ) -> dict:
        """Replace target_text with new_text in the content stream.

        Always returns a dict::

            {
              "success": bool,
              "track":   "C",
              "warnings": list[str],
              "reason":  str,          # non-empty on failure
              # on success only:
              "preserved_kerning": True,
              "encoding": str,
              "matched_xref": int,
              "matched_tj_range": (raw_start, raw_end),   # offsets in original stream
            }

        Never raises: all exceptions are caught and returned as success=False.
        """
        base = {"success": False, "track": "C", "warnings": [], "reason": ""}

        try:
            page = doc[page_idx]

            # Pre-flight
            ok, reason = self.can_handle(page, target_text, new_text, target_rect)
            if not ok:
                base["reason"] = reason
                return base

            page_height = page.rect.height
            xrefs = page.get_contents()
            origin_y_pdf = page_height - target_rect.y0

            # Capture a stable reference span for collateral check
            stable_text = self._find_stable_span(page, target_rect)

            # Find the matching block
            matched_block = None
            matched_tj_idx = -1
            matched_stream = None
            matched_xref = 0

            for xref in xrefs:
                stream = doc.xref_stream(xref)
                blocks = self._parse_bt_et_blocks(stream, xref, doc, page)
                block, tj_idx = self._match_span_to_block(
                    blocks, target_rect.x0, origin_y_pdf, target_text
                )
                if block is not None:
                    matched_block = block
                    matched_tj_idx = tj_idx
                    matched_stream = stream
                    matched_xref = xref
                    break

            if matched_block is None:
                base["reason"] = (
                    "span matching failed unexpectedly after can_handle passed"
                )
                return base

            tj_op = matched_block.tj_ops[matched_tj_idx]

            # Find the specific STR item containing target_text
            str_items = [it for it in tj_op.items if it.kind == "STR"]
            target_item = next(
                (it for it in str_items if target_text in it.value), None
            )
            if target_item is None:
                base["reason"] = "STR item lookup failed after can_handle passed"
                return base

            # Build the new string value
            new_value = target_item.value.replace(target_text, new_text, 1)

            # Determine format of the original string (paren vs hex)
            original_raw = matched_stream[target_item.raw_start:target_item.raw_end]
            is_hex = original_raw.startswith(b'<')

            if is_hex:
                try:
                    new_encoded = (
                        b'<'
                        + new_value.encode('latin-1').hex().upper().encode('ascii')
                        + b'>'
                    )
                except (UnicodeEncodeError, ValueError) as exc:
                    base["reason"] = f"hex encode failed: {exc}"
                    return base
            else:
                try:
                    new_encoded = b'(' + self._encode_paren_string(new_value) + b')'
                except (ValueError, UnicodeEncodeError) as exc:
                    base["reason"] = f"paren encode failed: {exc}"
                    return base

            # Splice new bytes into the stream
            rs = target_item.raw_start
            re_ = target_item.raw_end
            new_stream = matched_stream[:rs] + new_encoded + matched_stream[re_:]

            # Write back
            try:
                doc.update_stream(matched_xref, new_stream)
            except Exception as exc:
                base["reason"] = f"update_stream failed: {exc}"
                return base

            # Post-edit verification (4 checks)
            fail_reason = self._verify_edit(
                doc, page_idx, target_rect,
                target_text, new_text, stable_text,
            )
            if fail_reason:
                # Roll back to original stream
                try:
                    doc.update_stream(matched_xref, matched_stream)
                except Exception:
                    pass
                base["reason"] = fail_reason
                return base

            return {
                "success": True,
                "track": "C",
                "warnings": [],
                "reason": "",
                "preserved_kerning": True,
                "encoding": matched_block.encoding,
                "matched_xref": matched_xref,
                "matched_tj_range": (tj_op.raw_start, tj_op.raw_end),
            }

        except Exception as exc:
            logger.exception("TrackCEngine.apply_edit unexpected error: %s", exc)
            base["reason"] = f"unexpected error: {exc}"
            return base
