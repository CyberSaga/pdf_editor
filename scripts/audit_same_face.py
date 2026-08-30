#!/usr/bin/env python3
"""Read-only same-face proof census for embedded Type0 TrueType programs.

The report is aggregate-only: it never emits document text, font names,
candidate filenames, or paths. Documents are identified positionally.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_type0_census import (  # noqa: E402
    _deref,
    _desc_key,
    _dict_key_raw,
    _first_ref,
    _resolve_descendant,
    _resolve_indirect_elements,
    _w_tokens,
)
from scripts.type0_vocabulary import CANDIDATE_FONT_FILES  # noqa: E402

try:
    from fontTools.ttLib import TTCollection, TTFont
except ImportError:  # pragma: no cover - exercised by monkeypatch in CI
    TTCollection = TTFont = None  # type: ignore[assignment,misc]


_PROOF_CLASSES = (
    "A_same_gid_exact",
    "A_same_gid_exact_shared_program",
    "A_outline_same_bytes_differ",
    "B_renumbered_matchable",
    "face_unproven",
    "face_ambiguous",
    "embedding_restricted",
    "cff_out_of_scope",
    "program_unreadable",
)
_HEURISTICS = (
    "numglyphs_vs_maxcid",
    "max_cid_source",
    "subset_tag",
)
_RESTRICTED_FSTYPE = 0x0002 | 0x0004 | 0x0100 | 0x0200
_SUBSET_TAG = re.compile(r"^/[A-Z]{6}\+")


def _font_from_bytes(program: bytes) -> Any:
    if TTFont is None:
        raise ImportError("fontTools is unavailable")
    return TTFont(io.BytesIO(program), lazy=False)


def _compiled_glyph(font: Any, gid: int) -> bytes:
    glyf = font["glyf"]
    return glyf[font.getGlyphName(gid)].compile(glyf)


def _outline_signature(
    font: Any,
    gid: int,
    *,
    normalize_components: bool = False,
    seen: frozenset[int] = frozenset(),
) -> tuple[object, ...]:
    glyf = font["glyf"]
    glyph = glyf[font.getGlyphName(gid)]
    glyph.expand(glyf)
    if glyph.isComposite():
        if gid in seen:
            raise ValueError("cyclic composite glyph")
        components = []
        for component in glyph.components:
            component_gid = font.getGlyphID(component.glyphName)
            _, transform = component.getComponentInfo()
            identity: object = component_gid
            if normalize_components:
                identity = _outline_signature(
                    font,
                    component_gid,
                    normalize_components=True,
                    seen=seen | {gid},
                )
            components.append((identity, tuple(transform)))
        return ("composite", tuple(components))
    coordinates, end_points, flags = glyph.getCoordinates(glyf)
    return (
        "simple",
        tuple(tuple(point) for point in coordinates),
        tuple(end_points),
        tuple(flags),
    )


def _active_gids(font: Any) -> list[int]:
    return [
        gid
        for gid in range(font["maxp"].numGlyphs)
        if _compiled_glyph(font, gid)
    ]


def _component_closed_gids(font: Any, active: list[int]) -> list[int]:
    """Include every component reachable from an active composite glyph."""
    closed = set(active)
    pending = list(active)
    glyf = font["glyf"]
    while pending:
        gid = pending.pop()
        glyph = glyf[font.getGlyphName(gid)]
        glyph.expand(glyf)
        if not glyph.isComposite():
            continue
        for component in glyph.components:
            component_gid = font.getGlyphID(component.glyphName)
            if component_gid not in closed:
                closed.add(component_gid)
                pending.append(component_gid)
    return sorted(closed)


def _metrics(font: Any, gid: int) -> tuple[int, int]:
    return tuple(font["hmtx"][font.getGlyphName(gid)])  # type: ignore[return-value]


def _embedding_allowed(font: Any) -> bool:
    try:
        fs_type = int(font["OS/2"].fsType)
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
    return fs_type in (0x0000, 0x0008) and not fs_type & _RESTRICTED_FSTYPE


def _renumbered_inventory(font: Any) -> Counter[tuple[object, ...]]:
    cached = getattr(font, "_same_face_outline_inventory", None)
    if cached is not None:
        return cached
    inventory: Counter[tuple[object, ...]] = Counter(
        (
            _outline_signature(font, gid, normalize_components=True),
            _metrics(font, gid),
        )
        for gid in _active_gids(font)
    )
    setattr(font, "_same_face_outline_inventory", inventory)
    return inventory


def _proof_against(
    embedded: Any,
    candidate: Any,
    *,
    active: list[int] | None = None,
) -> str | None:
    for table in ("head", "maxp", "glyf", "hmtx"):
        if table not in embedded or table not in candidate:
            return None
    if embedded["head"].unitsPerEm != candidate["head"].unitsPerEm:
        return None

    if active is None:
        active = _active_gids(embedded)
    if not active:
        return None
    compared = _component_closed_gids(embedded, active)
    same_gid = candidate["maxp"].numGlyphs > max(compared)
    exact = same_gid
    outlines_equal = same_gid
    if same_gid:
        for gid in compared:
            if _metrics(embedded, gid) != _metrics(candidate, gid):
                exact = outlines_equal = False
                break
            embedded_bytes = _compiled_glyph(embedded, gid)
            candidate_bytes = _compiled_glyph(candidate, gid)
            if embedded_bytes != candidate_bytes:
                exact = False
                if _outline_signature(embedded, gid) != _outline_signature(
                    candidate, gid
                ):
                    outlines_equal = False
                    break
    if exact:
        return "A_same_gid_exact"
    if outlines_equal:
        return "A_outline_same_bytes_differ"

    required = Counter(
        (
            _outline_signature(embedded, gid, normalize_components=True),
            _metrics(embedded, gid),
        )
        for gid in active
    )
    available = _renumbered_inventory(candidate)
    if all(available[key] >= count for key, count in required.items()):
        return "B_renumbered_matchable"
    return None


def _normalize_candidates(candidates: list[bytes | Any]) -> list[Any]:
    normalized: list[Any] = []
    for candidate in candidates:
        if isinstance(candidate, (bytes, bytearray)):
            try:
                normalized.append(_font_from_bytes(bytes(candidate)))
            except Exception:  # noqa: BLE001 - hostile font input
                continue
        else:
            normalized.append(candidate)
    return normalized


def _raw_table(font: Any, tag: str) -> bytes:
    reader = getattr(font, "reader", None)
    if reader is not None:
        return bytes(reader[tag])
    return bytes(font.getTableData(tag))


def _share_exact_program(matches: list[tuple[str, Any]]) -> bool:
    if not matches or any(match != "A_same_gid_exact" for match, _ in matches):
        return False
    first = matches[0][1]
    try:
        signature = (
            int(first["head"].unitsPerEm),
            int(first["maxp"].numGlyphs),
            *(_raw_table(first, tag) for tag in ("glyf", "loca", "hmtx")),
        )
        return all(
            (
                int(candidate["head"].unitsPerEm),
                int(candidate["maxp"].numGlyphs),
                *(
                    _raw_table(candidate, tag)
                    for tag in ("glyf", "loca", "hmtx")
                ),
            )
            == signature
            for _, candidate in matches[1:]
        )
    except Exception:  # noqa: BLE001 - hostile candidate table data
        return False


def _classify_font_details(
    embedded: Any,
    candidates: list[Any],
    *,
    active: list[int] | None = None,
) -> tuple[str, tuple[Any, ...] | None]:
    if active is None:
        active = _active_gids(embedded)
    allowed_matches: list[tuple[str, Any]] = []
    restricted_matches = 0
    for candidate in candidates:
        try:
            match = _proof_against(embedded, candidate, active=active)
        except Exception:  # noqa: BLE001 - corrupt candidate face
            continue
        if match is None:
            continue
        if _embedding_allowed(candidate):
            allowed_matches.append((match, candidate))
        else:
            restricted_matches += 1
    if len(allowed_matches) >= 2:
        if _share_exact_program(allowed_matches):
            return (
                "A_same_gid_exact_shared_program",
                tuple(candidate for _, candidate in allowed_matches),
            )
        return "face_ambiguous", None
    if len(allowed_matches) == 1:
        match, candidate = allowed_matches[0]
        return match, (candidate,) if match == "A_same_gid_exact" else None
    if restricted_matches:
        return "embedding_restricted", None
    return "face_unproven", None


def _classify_font(embedded: Any, candidates: list[Any]) -> str:
    return _classify_font_details(embedded, candidates)[0]


def classify_program(embedded_program: bytes, candidate_programs: list[bytes]) -> str:
    """Classify one embedded TrueType program against candidate programs."""
    try:
        embedded = _font_from_bytes(embedded_program)
        if "glyf" not in embedded or embedded_program[:4] == b"OTTO":
            return "cff_out_of_scope"
        active = _active_gids(embedded)
        return _classify_font_details(
            embedded,
            _normalize_candidates(candidate_programs),
            active=active,
        )[0]
    except Exception:  # noqa: BLE001 - explicit unreadable bucket
        return "program_unreadable"


def _type0_fonts(doc: fitz.Document) -> list[int]:
    subtype_by_xref: dict[int, str] = {}
    for page_index in range(doc.page_count):
        for entry in doc[page_index].get_fonts(full=True):
            xref = int(entry[0])
            if xref > 0:
                subtype_by_xref.setdefault(xref, entry[2])
    return sorted(
        xref for xref, subtype in subtype_by_xref.items() if subtype == "Type0"
    )


def _descendant_subtype(descendant_body: str | None) -> str | None:
    if descendant_body is None:
        return None
    value = _dict_key_raw(descendant_body, "Subtype")
    return value.lstrip("/") if value else None


def _font_program(doc: fitz.Document, font_xref: int) -> bytes | None:
    try:
        return doc.extract_font(font_xref)[3]
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None


def _font_program_kind(
    doc: fitz.Document,
    descendant_xref: int | None,
    descendant_body: str | None,
) -> str:
    if descendant_xref is not None:
        for key, bucket in (
            ("FontFile3", "fontfile3"),
            ("FontFile2", "fontfile2"),
        ):
            kind, _ = doc.xref_get_key(
                descendant_xref, f"FontDescriptor/{key}"
            )
            if kind != "null":
                return bucket
        return "none"
    if descendant_body is None:
        return "none"
    fd_kind, fd_value = _desc_key(doc, None, descendant_body, "FontDescriptor")
    fd_body = _deref(doc, fd_kind, fd_value)
    if fd_body is None:
        return "none"
    if _dict_key_raw(fd_body, "FontFile3") is not None:
        return "fontfile3"
    if _dict_key_raw(fd_body, "FontFile2") is not None:
        return "fontfile2"
    return "none"


def _max_cid_from_w(doc: fitz.Document, kind: str, value: str) -> int | None:
    body = _deref(doc, kind, value)
    if body is None:
        return None
    tokens = _resolve_indirect_elements(doc, _w_tokens(body.strip()))
    if tokens is None or len(tokens) < 2 or tokens[0] != "[" or tokens[-1] != "]":
        return None
    maximum = -1
    i, end = 1, len(tokens) - 1
    try:
        while i < end:
            first = int(tokens[i])
            i += 1
            if i >= end:
                return None
            if tokens[i] == "[":
                i += 1
                count = 0
                while i < end and tokens[i] != "]":
                    float(tokens[i])
                    count += 1
                    i += 1
                if i >= end or count == 0:
                    return None
                maximum = max(maximum, first + count - 1)
                i += 1
            else:
                last = int(tokens[i])
                i += 1
                if i >= end or last < first:
                    return None
                float(tokens[i])
                i += 1
                maximum = max(maximum, last)
    except ValueError:
        return None
    return maximum if maximum >= 0 else None


def _max_cid(
    doc: fitz.Document,
    descendant_xref: int | None,
    descendant_body: str | None,
) -> tuple[int | None, str]:
    kind, value = _desc_key(doc, descendant_xref, descendant_body, "W")
    if kind != "null":
        maximum = _max_cid_from_w(doc, kind, value)
        if maximum is not None:
            return maximum, "w_array"
    kind, value = _desc_key(
        doc, descendant_xref, descendant_body, "CIDToGIDMap"
    )
    if kind == "xref":
        target = _first_ref(value)
        if target is not None:
            try:
                stream = doc.xref_stream(target)
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                stream = None
            if stream and len(stream) % 2 == 0:
                return len(stream) // 2 - 1, "cidtogid_length"
    return None, "none"


def _subset_tag(
    doc: fitz.Document,
    descendant_xref: int | None,
    descendant_body: str | None,
) -> str:
    if descendant_xref is not None:
        kind, value = doc.xref_get_key(
            descendant_xref, "FontDescriptor/FontName"
        )
        if kind != "name":
            return "fontname_unreadable"
        return "present" if _SUBSET_TAG.match(value) else "absent"
    if descendant_body is None:
        return "fontname_unreadable"
    fd_kind, fd_value = _desc_key(doc, None, descendant_body, "FontDescriptor")
    fd_body = _deref(doc, fd_kind, fd_value)
    if fd_body is None:
        return "fontname_unreadable"
    value = _dict_key_raw(fd_body, "FontName")
    if value is None:
        return "fontname_unreadable"
    return "present" if _SUBSET_TAG.match(value) else "absent"


def _analyze_document(
    doc: fitz.Document, candidate_programs: list[bytes | Any]
) -> tuple[dict[str, object], dict[int, tuple[Any, ...]]]:
    candidates = _normalize_candidates(candidate_programs)
    proof_classes: Counter[str] = Counter()
    a_family_faces: dict[int, tuple[Any, ...]] = {}
    heuristics: dict[str, Counter[str]] = {
        name: Counter() for name in _HEURISTICS
    }
    type0_fonts = _type0_fonts(doc)
    for font_xref in type0_fonts:
        desc_xref, desc_body = _resolve_descendant(doc, font_xref)
        subtype = _descendant_subtype(desc_body)
        program_kind = _font_program_kind(doc, desc_xref, desc_body)
        program = _font_program(doc, font_xref)
        embedded = None
        if (
            subtype == "CIDFontType0"
            or program_kind == "fontfile3"
            or (program or b"")[:4] == b"OTTO"
        ):
            proof = "cff_out_of_scope"
        elif program_kind != "fontfile2" or program is None:
            proof = "program_unreadable"
        else:
            try:
                embedded = _font_from_bytes(program)
                if "glyf" not in embedded:
                    proof = "cff_out_of_scope"
                else:
                    active = _active_gids(embedded)
                    proof, matching_face = _classify_font_details(
                        embedded, candidates, active=active
                    )
                    if matching_face is not None:
                        a_family_faces[font_xref] = matching_face
            except Exception:  # noqa: BLE001 - explicit unreadable bucket
                proof = "program_unreadable"
        proof_classes[proof] += 1

        maximum, source = _max_cid(doc, desc_xref, desc_body)
        heuristics["max_cid_source"][source] += 1
        if maximum is None or embedded is None:
            relation = "max_cid_unknown"
        else:
            num_glyphs = int(embedded["maxp"].numGlyphs)
            if num_glyphs == maximum + 1:
                relation = "eq_plus_one"
            elif num_glyphs > maximum + 1:
                relation = "gt"
            else:
                relation = "le"
        heuristics["numglyphs_vs_maxcid"][relation] += 1
        heuristics["subset_tag"][_subset_tag(doc, desc_xref, desc_body)] += 1

    return ({
        "fonts_type0": len(type0_fonts),
        "proof_classes": dict(sorted(proof_classes.items())),
        "heuristics": {
            name: dict(sorted(values.items()))
            for name, values in heuristics.items()
        },
    }, a_family_faces)


def census_document(
    doc: fitz.Document, candidate_programs: list[bytes | Any]
) -> dict[str, object]:
    """Aggregate same-face proof and labelled heuristics for one document."""
    return _analyze_document(doc, candidate_programs)[0]


def a_family_faces(
    doc: fitz.Document, candidate_programs: list[bytes | Any]
) -> dict[int, tuple[Any, ...]]:
    """Allowed exact-program face tuples by xref; identities stay in memory."""
    return _analyze_document(doc, candidate_programs)[1]


def candidate_supplier_for_faces(
    faces_by_xref: dict[int, tuple[Any, ...] | None],
) -> Callable[[int, str], bool]:
    """Require every proven face to map a character to one non-empty GID."""
    cmap_cache: dict[int, dict[int, str]] = {}
    supply_cache: dict[tuple[int, str], bool] = {}

    def supplies(font_xref: int, char: str) -> bool:
        key = (font_xref, char)
        cached = supply_cache.get(key)
        if cached is not None:
            return cached
        faces = faces_by_xref.get(font_xref)
        if not faces:
            return False
        gids: list[int] = []
        supplied = True
        for face in faces:
            cmap = cmap_cache.setdefault(id(face), face.getBestCmap() or {})
            name = cmap.get(ord(char))
            if name is None:
                supplied = False
                break
            try:
                gid = face.getGlyphID(name)
                if not _compiled_glyph(face, gid):
                    supplied = False
                    break
                gids.append(gid)
            except Exception:  # noqa: BLE001 - corrupt candidate cmap
                supplied = False
                break
        supplied = supplied and len(set(gids)) == 1
        supply_cache[key] = supplied
        return supplied

    return supplies


def load_candidate_faces() -> list[Any]:
    faces: list[Any] = []
    if TTFont is None or TTCollection is None:
        return faces
    for path in CANDIDATE_FONT_FILES:
        if not path.is_file():
            continue
        try:
            if path.suffix.lower() in (".ttc", ".otc"):
                faces.extend(TTCollection(str(path), lazy=False).fonts)
            else:
                faces.append(TTFont(str(path), lazy=False))
        except Exception:  # noqa: BLE001 - unreadable system font candidate
            continue
    return faces


def _merge(rows: list[dict[str, object]]) -> dict[str, object]:
    proofs: Counter[str] = Counter()
    heuristics = {name: Counter() for name in _HEURISTICS}
    for row in rows:
        proofs.update(row["proof_classes"])  # type: ignore[arg-type]
        for name in _HEURISTICS:
            heuristics[name].update(row["heuristics"][name])  # type: ignore[index]
    return {
        "documents": len(rows),
        "fonts_type0": sum(int(row["fonts_type0"]) for row in rows),
        "proof_classes": dict(sorted(proofs.items())),
        "heuristics": {
            name: dict(sorted(values.items()))
            for name, values in heuristics.items()
        },
    }


def _collect_paths(arguments: list[str], recursive: bool) -> list[Path]:
    paths: list[Path] = []
    for argument in arguments:
        path = Path(argument)
        if path.is_dir():
            paths.extend(sorted(path.glob("**/*.pdf" if recursive else "*.pdf")))
        else:
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    if TTFont is None or TTCollection is None:
        print(json.dumps({"status": "fonttools_absent"}))
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args(argv)
    fitz.TOOLS.mupdf_display_errors(False)
    candidates = load_candidate_faces()
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
            try:
                rows.append(census_document(doc, candidates))
            except Exception:  # noqa: BLE001 - isolate hostile documents
                skipped += 1
        finally:
            doc.close()
    report = {
        "candidate_faces_loaded": len(candidates),
        "per_document": {f"doc_{i}": row for i, row in enumerate(rows)},
        "combined": _merge(rows),
        "skipped_unopenable_or_encrypted": skipped,
    }
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
