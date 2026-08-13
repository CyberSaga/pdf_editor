#!/usr/bin/env python3
"""Read-only Type0/CID encoding census (Task 12 P0-D scope evidence).

Buckets every Type0 font of the given documents by the evidence P0-D's
gate chain needs: /Encoding form, descendant CIDFont subtype, /ToUnicode
availability, /CIDToGIDMap form, /W and /DW readability, and font-program
embedding. Never mutates anything and never emits document text, font
names, file names, or paths: documents are reported positionally
(``doc_0``, ``doc_1``, ...) in command-line order, and every bucket value
is a closed stable slug. Output is safe to copy into the plan verbatim.

Usage::

    python scripts/audit_type0_census.py <pdf-or-dir> [more...] [--json]

Directories are scanned for ``*.pdf`` (non-recursive; ``--recursive`` walks).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import fitz

# Encoding buckets (closed set).
ENC_IDENTITY_H = "identity_h"
ENC_IDENTITY_V = "identity_v"
ENC_PREDEFINED_NAMED = "predefined_named_cmap"
ENC_EMBEDDED_CUSTOM = "embedded_custom_cmap"
ENC_UNREADABLE = "unreadable"

# Descendant buckets.
DESC_CIDFONTTYPE2 = "cidfonttype2"
DESC_CIDFONTTYPE0 = "cidfonttype0"
DESC_UNREADABLE = "missing_or_unreadable"

# ToUnicode buckets.  Array-destination bfranges (PDF 32000-1 §9.10.3,
# ``<lo> <hi> [<d1> ... <dn>]``) get their own bucket: they are spec-legal
# but outside the P0-D v1 reverse-encoding scope, and a substring grep
# cannot see them (adversarial finding, 2026-08-13).
TU_PARSEABLE = "present_parseable"
TU_ARRAY_DESTINATION = "present_with_array_destinations"
TU_UNPARSEABLE = "present_unparseable_or_empty"
TU_ABSENT = "absent"

# CIDToGIDMap buckets.  Absent is its own bucket rather than folded into
# the /Identity name: the spec default makes them equivalent for a reader,
# but the census must show how often the key is explicit vs implied.
C2G_NAME_IDENTITY = "name_identity"
C2G_ABSENT_IMPLICIT = "absent_implicit_identity"
C2G_STREAM_READABLE = "stream_readable"
C2G_STREAM_UNREADABLE = "stream_unreadable"
C2G_UNREADABLE = "unreadable"

# /W and /DW buckets.  "font_unreadable" keeps a structurally-unreadable
# descendant out of the malformed-width count: those are different losses
# and the descendant facet already tracks the former.
W_READABLE = "readable"
W_MALFORMED = "malformed"
W_ABSENT = "absent"
W_FONT_UNREADABLE = "font_unreadable"
DW_READABLE = "readable"
DW_MALFORMED = "malformed"
DW_ABSENT = "absent_default_1000"
DW_FONT_UNREADABLE = "font_unreadable"

_FACETS = ("encoding", "descendant", "tounicode", "cidtogid", "w", "dw", "embedded")


def _first_ref(value: str) -> int | None:
    try:
        xref = int(value.split()[0])
    except (ValueError, IndexError):
        return None
    return xref if xref > 0 else None


def _deref(doc: fitz.Document, kind: str, value: str) -> str | None:
    """Serialized object body, following one level of indirection."""
    if kind == "xref":
        target = _first_ref(value)
        if target is None:
            return None
        try:
            return doc.xref_object(target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return None
    return value


def _classify_encoding(doc: fitz.Document, font_xref: int) -> str:
    kind, value = doc.xref_get_key(font_xref, "Encoding")
    if kind == "name":
        name = value.lstrip("/")
        if name == "Identity-H":
            return ENC_IDENTITY_H
        if name == "Identity-V":
            return ENC_IDENTITY_V
        return ENC_PREDEFINED_NAMED
    if kind == "xref":
        return ENC_EMBEDDED_CUSTOM
    return ENC_UNREADABLE


def _balanced_dict(body: str) -> str | None:
    """The first balanced ``<< ... >>`` of ``body``, delimiters included."""
    start = body.find("<<")
    if start < 0:
        return None
    depth = 0
    i = start
    while i < len(body) - 1:
        pair = body[i : i + 2]
        if pair == "<<":
            depth += 1
            i += 2
        elif pair == ">>":
            depth -= 1
            i += 2
            if depth == 0:
                return body[start:i]
        else:
            i += 1
    return None


def _dict_key_raw(body: str, key: str) -> str | None:
    """Raw value text following ``/key`` in a serialized dict, else None.

    Census-grade reader for the INLINE descendant form (a real corpus
    shape: AutoCAD emits ``/DescendantFonts [<<...>>]`` with no indirect
    reference).  Nested-dict values are returned balanced; array values up
    to the matching bracket; scalar values up to the next delimiter.
    """
    marker = re.search(rf"/{re.escape(key)}(?![A-Za-z0-9])", body)
    if marker is None:
        return None
    rest = body[marker.end() :].lstrip()
    if rest.startswith("<<"):
        return _balanced_dict(rest)
    if rest.startswith("["):
        depth = 0
        for i, ch in enumerate(rest):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return rest[: i + 1]
        return None
    match = re.match(r"(/[^\s/<>\[\]()]+|\d+\s+\d+\s+R|[-\d.]+)", rest)
    return match.group(1) if match else None


def _resolve_descendant(
    doc: fitz.Document, font_xref: int
) -> tuple[int | None, str | None]:
    """(descendant_xref, serialized_descendant_dict) — either may be None.

    Handles both corpus forms: ``/DescendantFonts [N 0 R]`` (or an indirect
    array) and the inline ``/DescendantFonts [<<...>>]`` dictionary.
    """
    kind, value = doc.xref_get_key(font_xref, "DescendantFonts")
    body = _deref(doc, kind, value)
    if body is None:
        return None, None
    inner = body.strip()
    if inner.startswith("["):
        inner = inner[1:].lstrip()
    if inner.startswith("<<"):
        return None, _balanced_dict(inner)
    target = _first_ref(inner)
    if target is None:
        return None, None
    try:
        return target, doc.xref_object(target)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None, None


def _classify_descendant(descendant_body: str | None) -> str:
    if descendant_body is None:
        return DESC_UNREADABLE
    subtype = _dict_key_raw(descendant_body, "Subtype")
    if subtype == "/CIDFontType2":
        return DESC_CIDFONTTYPE2
    if subtype == "/CIDFontType0":
        return DESC_CIDFONTTYPE0
    return DESC_UNREADABLE


_HEX_TOKEN = re.compile(r"<[0-9A-Fa-f]+>")


def _classify_tounicode(doc: fitz.Document, font_xref: int) -> str:
    """Structural bfchar/bfrange validation — never a substring grep.

    bfchar blocks must hold an even number of hex tokens (src/dst pairs);
    single-destination bfrange blocks a multiple of three.  Any ``[`` in a
    bfrange block is the array-destination form, bucketed separately.
    """
    kind, value = doc.xref_get_key(font_xref, "ToUnicode")
    if kind == "null":
        return TU_ABSENT
    if kind != "xref":
        return TU_UNPARSEABLE
    target = _first_ref(value)
    if target is None:
        return TU_UNPARSEABLE
    try:
        data = doc.xref_stream(target)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return TU_UNPARSEABLE
    if not data:
        return TU_UNPARSEABLE
    text = data.decode("latin-1", errors="replace")
    bfchar_blocks = re.findall(r"beginbfchar(.*?)endbfchar", text, re.DOTALL)
    bfrange_blocks = re.findall(r"beginbfrange(.*?)endbfrange", text, re.DOTALL)
    if not bfchar_blocks and not bfrange_blocks:
        return TU_UNPARSEABLE
    for block in bfrange_blocks:
        if "[" in block:
            return TU_ARRAY_DESTINATION
    for block in bfchar_blocks:
        tokens = _HEX_TOKEN.findall(block)
        if not tokens or len(tokens) % 2:
            return TU_UNPARSEABLE
    for block in bfrange_blocks:
        tokens = _HEX_TOKEN.findall(block)
        if not tokens or len(tokens) % 3:
            return TU_UNPARSEABLE
    return TU_PARSEABLE


def _desc_key(
    doc: fitz.Document,
    descendant_xref: int | None,
    descendant_body: str | None,
    key: str,
) -> tuple[str, str]:
    """``xref_get_key`` semantics over either descendant form."""
    if descendant_xref is not None:
        return doc.xref_get_key(descendant_xref, key)
    if descendant_body is None:
        return ("null", "null")
    raw = _dict_key_raw(descendant_body, key)
    if raw is None:
        return ("null", "null")
    if raw.startswith("/"):
        return ("name", raw)
    if raw.startswith("["):
        return ("array", raw)
    if raw.startswith("<<"):
        return ("dict", raw)
    if re.fullmatch(r"\d+\s+\d+\s+R", raw):
        return ("xref", raw)
    return ("float", raw)


def _classify_cidtogid(
    doc: fitz.Document, descendant_xref: int | None, descendant_body: str | None
) -> str:
    if descendant_xref is None and descendant_body is None:
        return C2G_UNREADABLE
    kind, value = _desc_key(doc, descendant_xref, descendant_body, "CIDToGIDMap")
    if kind == "null":
        return C2G_ABSENT_IMPLICIT
    if kind == "name":
        return C2G_NAME_IDENTITY if value.lstrip("/") == "Identity" else C2G_UNREADABLE
    if kind == "xref":
        target = _first_ref(value)
        if target is None:
            return C2G_STREAM_UNREADABLE
        try:
            data = doc.xref_stream(target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return C2G_STREAM_UNREADABLE
        # A CIDToGIDMap stream is a big-endian uint16 per CID: readable
        # means non-empty with even length (a truncated odd-length map
        # cannot address its final CID).
        if data and len(data) % 2 == 0:
            return C2G_STREAM_READABLE
        return C2G_STREAM_UNREADABLE
    return C2G_UNREADABLE


def _w_tokens(body: str) -> list[str]:
    return body.replace("[", " [ ").replace("]", " ] ").split()


def _resolve_indirect_elements(
    doc: fitz.Document, tokens: list[str]
) -> list[str] | None:
    """Splice one level of ``N G R`` array elements into the token stream.

    PDF 32000-1 §7.3.6 allows any /W element (a number or a width
    sub-array) to be an indirect reference; a flat numeric walk would
    misparse the reference as data.  One level suffices for a census —
    a second-level reference inside the substituted body simply fails the
    numeric walk and buckets as malformed.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if (
            i + 2 < len(tokens)
            and tokens[i + 2] == "R"
            and tokens[i].isdigit()
            and tokens[i + 1].isdigit()
        ):
            try:
                body = doc.xref_object(int(tokens[i]))
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                return None
            out.extend(_w_tokens(body.strip()))
            i += 3
        else:
            out.append(tokens[i])
            i += 1
    return out


def _classify_w(
    doc: fitz.Document, descendant_xref: int | None, descendant_body: str | None
) -> str:
    if descendant_xref is None and descendant_body is None:
        return W_FONT_UNREADABLE
    kind, value = _desc_key(doc, descendant_xref, descendant_body, "W")
    if kind == "null":
        return W_ABSENT
    body = _deref(doc, kind, value)
    if body is None:
        return W_MALFORMED
    raw_tokens = _resolve_indirect_elements(doc, _w_tokens(body.strip()))
    if raw_tokens is None:
        return W_MALFORMED
    tokens = raw_tokens
    if len(tokens) < 2 or tokens[0] != "[" or tokens[-1] != "]":
        return W_MALFORMED
    # Validate the two record forms of PDF 32000-1 9.7.4.3:
    #   c [w1 w2 ...]        and        c_first c_last w
    i, n = 1, len(tokens) - 1
    try:
        while i < n:
            int(tokens[i])  # c or c_first
            i += 1
            if i >= n:
                return W_MALFORMED
            if tokens[i] == "[":
                i += 1
                saw_width = False
                while i < n and tokens[i] != "]":
                    float(tokens[i])
                    saw_width = True
                    i += 1
                if i >= n or not saw_width:
                    return W_MALFORMED
                i += 1  # closing ]
            else:
                int(tokens[i])  # c_last
                i += 1
                if i >= n:
                    return W_MALFORMED
                float(tokens[i])  # w
                i += 1
    except ValueError:
        return W_MALFORMED
    return W_READABLE


def _classify_dw(
    doc: fitz.Document, descendant_xref: int | None, descendant_body: str | None
) -> str:
    if descendant_xref is None and descendant_body is None:
        return DW_FONT_UNREADABLE
    kind, value = _desc_key(doc, descendant_xref, descendant_body, "DW")
    if kind == "null":
        return DW_ABSENT
    if kind in ("int", "float"):
        return DW_READABLE
    body = _deref(doc, kind, value)
    if body is None:
        return DW_MALFORMED
    try:
        float(body.strip())
    except ValueError:
        return DW_MALFORMED
    return DW_READABLE


def _classify_embedded(
    doc: fitz.Document, descendant_xref: int | None, descendant_body: str | None
) -> str:
    if descendant_xref is not None:
        for key in ("FontFile2", "FontFile3", "FontFile"):
            kind, _ = doc.xref_get_key(descendant_xref, f"FontDescriptor/{key}")
            if kind != "null":
                return "yes"
        return "no"
    if descendant_body is None:
        return "no"
    fd_kind, fd_value = _desc_key(doc, None, descendant_body, "FontDescriptor")
    fd_body = _deref(doc, fd_kind, fd_value) if fd_kind in ("xref", "dict") else None
    if fd_body is None:
        return "no"
    for key in ("FontFile2", "FontFile3", "FontFile"):
        if _dict_key_raw(fd_body, key) is not None:
            return "yes"
    return "no"


def census_document(doc: fitz.Document) -> dict[str, object]:
    """Aggregate Type0 buckets for one open document."""
    pages_per_font: Counter[int] = Counter()
    subtype_by_xref: dict[int, str] = {}
    for page_index in range(doc.page_count):
        seen: set[int] = set()
        for entry in doc[page_index].get_fonts(full=True):
            font_xref = int(entry[0])
            subtype_by_xref.setdefault(font_xref, entry[2])
            if font_xref > 0 and font_xref not in seen:
                seen.add(font_xref)
                pages_per_font[font_xref] += 1

    facet_counts: dict[str, Counter[str]] = {facet: Counter() for facet in _FACETS}
    facet_page_weights: dict[str, Counter[str]] = {
        facet: Counter() for facet in _FACETS
    }
    combo_counts: Counter[str] = Counter()

    type0_xrefs = sorted(
        xref for xref, subtype in subtype_by_xref.items()
        if subtype == "Type0" and xref > 0
    )
    for font_xref in type0_xrefs:
        desc_xref, desc_body = _resolve_descendant(doc, font_xref)
        buckets = {
            "encoding": _classify_encoding(doc, font_xref),
            "descendant": _classify_descendant(desc_body),
            "tounicode": _classify_tounicode(doc, font_xref),
            "cidtogid": _classify_cidtogid(doc, desc_xref, desc_body),
            "w": _classify_w(doc, desc_xref, desc_body),
            "dw": _classify_dw(doc, desc_xref, desc_body),
            "embedded": _classify_embedded(doc, desc_xref, desc_body),
        }
        weight = pages_per_font[font_xref]
        for facet, bucket in buckets.items():
            facet_counts[facet][bucket] += 1
            facet_page_weights[facet][bucket] += weight
        combo_counts["|".join(buckets[facet] for facet in _FACETS)] += 1

    return {
        "pages": doc.page_count,
        "fonts_total": len(subtype_by_xref),
        "fonts_type0": len(type0_xrefs),
        "fonts_by_subtype": dict(
            sorted(Counter(subtype_by_xref.values()).items())
        ),
        "type0_facets": {
            facet: dict(sorted(counter.items()))
            for facet, counter in facet_counts.items()
        },
        "type0_facets_page_weighted": {
            facet: dict(sorted(counter.items()))
            for facet, counter in facet_page_weights.items()
        },
        "type0_combos": dict(sorted(combo_counts.items())),
    }


def _merge(rows: list[dict[str, object]]) -> dict[str, object]:
    combined: dict[str, object] = {
        "documents": len(rows),
        "pages": sum(int(row["pages"]) for row in rows),
        "fonts_total": sum(int(row["fonts_total"]) for row in rows),
        "fonts_type0": sum(int(row["fonts_type0"]) for row in rows),
    }
    for section in ("type0_facets", "type0_facets_page_weighted"):
        merged: dict[str, Counter[str]] = {facet: Counter() for facet in _FACETS}
        for row in rows:
            for facet, buckets in row[section].items():  # type: ignore[union-attr]
                merged[facet].update(buckets)
        combined[section] = {
            facet: dict(sorted(counter.items())) for facet, counter in merged.items()
        }
    combos: Counter[str] = Counter()
    for row in rows:
        combos.update(row["type0_combos"])  # type: ignore[arg-type]
    combined["type0_combos"] = dict(sorted(combos.items()))
    return combined


def _collect_paths(arguments: list[str], recursive: bool) -> list[Path]:
    paths: list[Path] = []
    for argument in arguments:
        path = Path(argument)
        if path.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            paths.extend(sorted(path.glob(pattern)))
        else:
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="PDF files or directories")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument(
        "--recursive", action="store_true", help="walk directories recursively"
    )
    args = parser.parse_args(argv)

    # Census runs over deliberately-hostile corpora (veraPDF): keep MuPDF's
    # per-object repair chatter off stdout so --json stays machine-readable.
    fitz.TOOLS.mupdf_display_errors(False)

    rows: list[dict[str, object]] = []
    skipped = 0
    for path in _collect_paths(args.paths, args.recursive):
        try:
            doc = fitz.open(path)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            skipped += 1
            continue
        try:
            if doc.needs_pass:
                skipped += 1
                continue
            # Intentionally broad: a malformed-corpus page may raise from
            # deep inside MuPDF with types outside the fitz error family,
            # and one hostile file must not abort a whole-corpus census.
            try:
                rows.append(census_document(doc))
            except Exception:  # noqa: BLE001
                skipped += 1
        finally:
            doc.close()

    report = {
        # Positional identity only — never a filename or path (§10 data policy).
        "per_document": {f"doc_{i}": row for i, row in enumerate(rows)},
        "combined": _merge(rows),
        "skipped_unopenable_or_encrypted": skipped,
    }
    print(json.dumps(report, indent=None if args.json else 2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
