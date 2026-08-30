#!/usr/bin/env python3
"""Synthetic-only Task 14 Type0 mutation-premise matrix.

The report contains closed keys with bool/int/slug leaves only. No document
paths, fixture text, font names, xrefs, or object bodies are emitted.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.text_commit.cid_fonts import (  # noqa: E402
    PdfRef,
    compute_cid_evidence_digest,
    parse_pdf_value,
    parse_truetype_glyph_program,
    resolve_descendant,
    serialize_pdf_value,
)
from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.patch import build_reversal_patchset  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    Type0Fixture,
    build_identity_h_fixture,
    cid_for,
    document_object_snapshot,
    embedded_font_buffer,
    fontfile2_xref,
    inline_descendant,
    render_cid_ink,
    write_minimal_tounicode,
)

_EXISTING = "\u4f60"
_SECOND = "\u597d"
_MISSING = "\u5716"


def _full_program() -> bytes:
    fixture = build_identity_h_fixture(text=_EXISTING, subset=False)
    try:
        return embedded_font_buffer(fixture)
    finally:
        fixture.doc.close()


def _subset_fixture(*, text: str = _EXISTING) -> Type0Fixture:
    fixture = build_identity_h_fixture(text=text, subset=True)
    mappings = [(cid_for(char), char) for char in dict.fromkeys(text + _MISSING)]
    write_minimal_tounicode(fixture, mappings)
    return fixture


def _reopen_fixture(fixture: Type0Fixture, data: bytes) -> Type0Fixture:
    reopened = fitz.open(stream=data, filetype="pdf")
    return replace(fixture, doc=reopened, extra_streams=list(fixture.extra_streams))


def _descriptor_xref(fixture: Type0Fixture) -> int:
    kind, value = fixture.doc.xref_get_key(
        fixture.descendant_xref, "FontDescriptor"
    )
    if kind != "xref":
        raise ValueError("synthetic descriptor is not indirect")
    return int(value.split()[0])


def _install_program(
    fixture: Type0Fixture,
    program: bytes,
    *,
    new_xref: bool = False,
) -> int:
    doc = fixture.doc
    if new_xref:
        target = doc.get_new_xref()
        doc.update_object(target, "<<>>")
        doc.update_stream(target, program, compress=0)
        doc.xref_set_key(target, "Length1", str(len(program)))
        doc.xref_set_key(
            _descriptor_xref(fixture), "FontFile2", f"{target} 0 R"
        )
        return target
    target = fontfile2_xref(fixture)
    doc.update_stream(target, program, compress=0)
    doc.xref_set_key(target, "Length1", str(len(program)))
    return target


def _pixmap_samples(fixture: Type0Fixture, *, dpi: int = 96) -> tuple[bytes, int]:
    pixmap = fixture.page.get_pixmap(dpi=dpi, alpha=False)
    return bytes(pixmap.samples), pixmap.n


def probe_p1_cache_visibility() -> dict[str, bool]:
    program = _full_program()
    missing_cid = cid_for(_MISSING)

    inplace = _subset_fixture()
    try:
        before = render_cid_ink(inplace, missing_cid)
        _install_program(inplace, program)
        inplace_visible = before == 0 and render_cid_ink(inplace, missing_cid) > 0
        fitz.TOOLS.store_shrink(100)
        store_visible = before == 0 and render_cid_ink(inplace, missing_cid) > 0
    finally:
        inplace.doc.close()

    repointed = _subset_fixture()
    try:
        before = render_cid_ink(repointed, missing_cid)
        _install_program(repointed, program, new_xref=True)
        new_xref_visible = before == 0 and render_cid_ink(repointed, missing_cid) > 0
    finally:
        repointed.doc.close()

    source = _subset_fixture()
    try:
        before = render_cid_ink(source, missing_cid)
        _install_program(source, program)
        data = source.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        reopened = _reopen_fixture(source, data)
        try:
            reopen_visible = before == 0 and render_cid_ink(reopened, missing_cid) > 0
        finally:
            reopened.doc.close()
    finally:
        source.doc.close()

    return {
        "inplace_visible": inplace_visible,
        "store_shrink_visible": store_visible,
        "new_xref_visible": new_xref_visible,
        "reopen_visible": reopen_visible,
    }


def _array_path_result(fixture: Type0Fixture) -> str:
    try:
        fixture.doc.xref_set_key(
            fixture.font_xref, "DescendantFonts/0/DW", "500"
        )
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return "raised"
    _, descendant = resolve_descendant(fixture.doc, fixture.font_xref)
    if descendant is None:
        kind, value = fixture.doc.xref_get_key(
            fixture.font_xref, "DescendantFonts"
        )
        if kind not in ("array", "xref"):
            return "array_destroyed"
        return "placeholder_planted" if "null" in value else "array_destroyed"
    return "ok_value_set" if descendant.get("DW") == 500 else "placeholder_planted"


def probe_p2_array_path() -> dict[str, str]:
    results: list[str] = []
    for inline in (False, True):
        fixture = _subset_fixture()
        try:
            if inline:
                inline_descendant(fixture)
            results.append(_array_path_result(fixture))
        finally:
            fixture.doc.close()
    for slug in ("raised", "array_destroyed", "placeholder_planted"):
        if slug in results:
            return {"slug": slug}
    return {"slug": "ok_value_set"}


def _rewrite_width(fixture: Type0Fixture, cid: int) -> bool:
    doc = fixture.doc
    kind, serialized = doc.xref_get_key(fixture.font_xref, "DescendantFonts")
    if kind == "xref":
        array_xref = int(serialized.split()[0])
        serialized = doc.xref_object(array_xref)
    parsed = parse_pdf_value(serialized)
    if not isinstance(parsed, list) or not parsed:
        return False
    first = parsed[0]
    if isinstance(first, PdfRef):
        descendant = parse_pdf_value(doc.xref_object(first.xref))
        if not isinstance(descendant, dict):
            return False
        descendant["W"] = [cid, [1000]]
        doc.update_object(first.xref, serialize_pdf_value(descendant))
    elif isinstance(first, dict):
        first["W"] = [cid, [1000]]
        doc.xref_set_key(
            fixture.font_xref,
            "DescendantFonts",
            serialize_pdf_value(parsed),
        )
    else:
        return False
    _, readback = resolve_descendant(doc, fixture.font_xref)
    return readback is not None and readback.get("W") == [cid, [1000]]


def _snapshot_diff_count(before: tuple, after: tuple) -> int:
    before_by_xref = {row[0]: row[1:] for row in before}
    after_by_xref = {row[0]: row[1:] for row in after}
    return sum(
        before_by_xref.get(xref) != after_by_xref.get(xref)
        for xref in set(before_by_xref) | set(after_by_xref)
    )


def probe_p3_descendant_rewrite() -> dict[str, bool | int]:
    missing_cid = cid_for(_MISSING)
    indirect = _subset_fixture()
    try:
        before_snapshot = document_object_snapshot(indirect.doc)
        before_fingerprint = page_fingerprint(indirect.doc, indirect.page)
        indirect_ok = _rewrite_width(indirect, missing_cid)
        after_snapshot = document_object_snapshot(indirect.doc)
        fingerprint_changed = (
            page_fingerprint(indirect.doc, indirect.page) != before_fingerprint
        )
        diff_count = _snapshot_diff_count(before_snapshot, after_snapshot)
    finally:
        indirect.doc.close()

    inline = _subset_fixture()
    try:
        inline_descendant(inline)
        inline_ok = _rewrite_width(inline, missing_cid)
    finally:
        inline.doc.close()
    return {
        "width_readback_ok_indirect": indirect_ok,
        "width_readback_ok_inline": inline_ok,
        "fingerprint_changed": fingerprint_changed,
        "snapshot_diff_xrefs_count": diff_count,
    }


def probe_p4_keep_reopen() -> dict[str, bool | str]:
    fixture = _subset_fixture()
    program = _full_program()
    missing_gid = cid_for(_MISSING)
    try:
        ff_xref = _install_program(fixture, program)
        data = fixture.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        reopened = _reopen_fixture(fixture, data)
        try:
            stored = reopened.doc.xref_stream(ff_xref) or b""
            glyphs = parse_truetype_glyph_program(stored)
            readable = (
                glyphs is not None
                and (glyphs.glyph_data_length(missing_gid) or 0) > 0
            )
            render_ok = render_cid_ink(reopened, missing_gid) > 0
            kind, length = reopened.doc.xref_get_key(ff_xref, "Length1")
            length_ok = kind == "int" and int(length) == len(program)
            try:
                from fontTools.ttLib import TTFont
            except ImportError:
                fonttools: bool | str = "fonttools_absent"
            else:
                try:
                    TTFont(io.BytesIO(stored), lazy=False)
                except Exception:  # noqa: BLE001 - probe result
                    fonttools = False
                else:
                    fonttools = True
        finally:
            reopened.doc.close()
    finally:
        fixture.doc.close()
    return {
        "mupdf_readable_after_keep_reopen": readable,
        "render_ink_after_reopen": render_ok,
        "fonttools_loads": fonttools,
        "length1_updated": length_ok,
    }


def probe_p5_existing_raster() -> dict[str, bool | int]:
    fixture = _subset_fixture()
    try:
        before, channels = _pixmap_samples(fixture)
        _install_program(fixture, _full_program())
        data = fixture.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        reopened = _reopen_fixture(fixture, data)
        try:
            after, after_channels = _pixmap_samples(reopened)
        finally:
            reopened.doc.close()
    finally:
        fixture.doc.close()
    if channels != after_channels:
        differing = max(len(before) // channels, len(after) // after_channels)
    else:
        differing = sum(
            before[index : index + channels] != after[index : index + channels]
            for index in range(0, min(len(before), len(after)), channels)
        )
        differing += abs(len(before) - len(after)) // channels
    return {"raster_identical": before == after, "differing_pixels": differing}


def probe_p6_multiobject_revert() -> dict[str, bool]:
    fixture = _subset_fixture()
    doc = fixture.doc
    ff_xref = fontfile2_xref(fixture)
    desc_xref = fixture.descendant_xref
    try:
        original_decoded = doc.xref_stream(ff_xref) or b""
        original_raw = doc.xref_stream_raw(ff_xref) or b""
        original_ff_object = doc.xref_object(ff_xref)
        original_desc_object = doc.xref_object(desc_xref)
        original_fingerprint = page_fingerprint(doc, fixture.page)

        _install_program(fixture, _full_program())
        _rewrite_width(fixture, cid_for(_MISSING))

        doc.update_object(desc_xref, original_desc_object)
        doc.update_stream(ff_xref, original_decoded, compress=0)
        doc.update_object(ff_xref, original_ff_object)

        decoded_identity = (doc.xref_stream(ff_xref) or b"") == original_decoded
        raw_identity = (doc.xref_stream_raw(ff_xref) or b"") == original_raw
        object_identity = (
            doc.xref_object(desc_xref) == original_desc_object
            and doc.xref_object(ff_xref) == original_ff_object
        )
        fingerprint_restored = (
            page_fingerprint(doc, fixture.page) == original_fingerprint
        )
    finally:
        doc.close()
    return {
        "decoded_identity": decoded_identity,
        "raw_identity": raw_identity,
        "object_identity": object_identity,
        "fingerprint_restored": fingerprint_restored,
    }


def _add_shared_font_page(fixture: Type0Fixture) -> fitz.Page:
    doc = fixture.doc
    page = doc.new_page(width=fixture.page.rect.width, height=fixture.page.rect.height)
    kind, resources = doc.xref_get_key(fixture.page.xref, "Resources")
    if kind not in ("dict", "xref"):
        raise ValueError("synthetic page resources are unreadable")
    doc.xref_set_key(page.xref, "Resources", resources)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    body = (
        f"BT /{fixture.resource_name} {fixture.fontsize:g} Tf "
        f"1 0 0 1 {fixture.origin[0]:g} {fixture.origin[1]:g} Tm "
        f"<{cid_for(_EXISTING):04X}> Tj ET"
    ).encode("ascii")
    doc.update_stream(content_xref, body, compress=0)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    return doc[page.number]


def probe_p7_shared_font_stale() -> dict[str, bool]:
    fixture = _subset_fixture(text=_EXISTING + _SECOND)
    doc = fixture.doc
    try:
        page = _add_shared_font_page(fixture)
        engine = TieredCommitEngine(doc, max_tier=1)
        prepared = engine.prepare(
            page,
            target_text=_EXISTING,
            replacement_text=_SECOND,
            expected_origin=None,
        )
        if isinstance(prepared, PlanRejection):
            return {
                "status_stale_plan": False,
                "snapshot_unchanged_by_commit_attempt": False,
                "capability_digest_changed": False,
            }
        before_digest = compute_cid_evidence_digest(doc, fixture.font_xref)
        _install_program(fixture, _full_program())
        after_digest = compute_cid_evidence_digest(doc, fixture.font_xref)
        before_commit = document_object_snapshot(doc)
        outcome = engine.commit(prepared)
        after_commit = document_object_snapshot(doc)
        return {
            "status_stale_plan": outcome.status is CommitStatus.STALE_PLAN,
            "snapshot_unchanged_by_commit_attempt": before_commit == after_commit,
            "capability_digest_changed": before_digest != after_digest,
        }
    finally:
        doc.close()


def probe_p8_encrypted_keep() -> dict[str, bool]:
    password = "fixture-password"
    fixture = _subset_fixture()
    try:
        encrypted_bytes = fixture.doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password,
        )
    finally:
        fixture.doc.close()
    encrypted = _reopen_fixture(fixture, encrypted_bytes)
    try:
        initially_needs_pass = bool(encrypted.doc.needs_pass)
        authenticated = bool(encrypted.doc.authenticate(password))
        if not authenticated:
            return {
                "needs_pass_after_keep_save": False,
                "render_ink_after_reauth": False,
                "tobytes_keep_roundtrip_ok": False,
            }
        _install_program(encrypted, _full_program())
        kept = encrypted.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        encrypted.doc.close()
    reopened = _reopen_fixture(encrypted, kept)
    try:
        needs_pass = bool(reopened.doc.needs_pass)
        reauthenticated = bool(reopened.doc.authenticate(password))
        render_ok = reauthenticated and render_cid_ink(
            reopened, cid_for(_MISSING)
        ) > 0
        try:
            second = reopened.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
            check = fitz.open(stream=second, filetype="pdf")
            try:
                roundtrip_ok = bool(check.needs_pass) and bool(
                    check.authenticate(password)
                )
            finally:
                check.close()
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            roundtrip_ok = False
    finally:
        reopened.doc.close()
    return {
        "needs_pass_after_keep_save": initially_needs_pass and needs_pass,
        "render_ink_after_reauth": bool(render_ok),
        "tobytes_keep_roundtrip_ok": roundtrip_ok,
    }


class _BlockManager:
    def rebuild_page(self, _page_index: int, _doc: fitz.Document) -> None:
        return None


class _CommandModel:
    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc
        self.last_commit_outcome: Any = None
        self.fidelity_protected_pages: set[int] = set()
        self.block_manager = _BlockManager()


def probe_p9_prior_undo() -> dict[str, bool]:
    fixture = _subset_fixture(text=_EXISTING + _SECOND)
    doc = fixture.doc
    try:
        page = fixture.page
        pre_streams = tuple(read_page_streams(doc, page))
        pre_fingerprint = page_fingerprint(doc, page, streams=pre_streams)
        engine = TieredCommitEngine(doc, max_tier=1)
        prepared = engine.prepare(
            page,
            target_text=_EXISTING + _SECOND,
            replacement_text=_SECOND + _EXISTING,
            expected_origin=None,
        )
        if isinstance(prepared, PlanRejection):
            return {
                "undo_refused_stale": False,
                "doc_unchanged_by_refused_undo": False,
            }
        outcome = engine.commit(prepared)
        reversal = build_reversal_patchset(
            doc, fixture.page, pre_streams, pre_fingerprint
        )
        if outcome.status is not CommitStatus.COMMITTED or reversal is None:
            return {
                "undo_refused_stale": False,
                "doc_unchanged_by_refused_undo": False,
            }
        model = _CommandModel(doc)
        command = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(60, 680, 180, 720),
            new_text=_SECOND + _EXISTING,
            font="fixture",
            size=12.0,
            color=(0, 0, 0),
            original_text=_EXISTING + _SECOND,
            vertical_shift_left=False,
            page_snapshot_bytes=b"",
            old_block_id=None,
            old_block_text=_EXISTING + _SECOND,
        )
        command._tier0_forward_patchset, command._tier0_inverse_patchset = reversal
        command._tier0_active = True
        command._executed = True
        _install_program(fixture, _full_program())
        before_undo = document_object_snapshot(doc)
        command_logger = logging.getLogger("model.edit_commands")
        was_disabled = command_logger.disabled
        command_logger.disabled = True
        try:
            undo_result = command.undo()
        finally:
            command_logger.disabled = was_disabled
        after_undo = document_object_snapshot(doc)
        return {
            "undo_refused_stale": (
                undo_result is False and command.result is EditTextResult.STALE_UNDO
            ),
            "doc_unchanged_by_refused_undo": before_undo == after_undo,
        }
    finally:
        doc.close()


def run_all() -> dict[str, dict[str, object]]:
    return {
        "P1": probe_p1_cache_visibility(),
        "P2": probe_p2_array_path(),
        "P3": probe_p3_descendant_rewrite(),
        "P4": probe_p4_keep_reopen(),
        "P5": probe_p5_existing_raster(),
        "P6": probe_p6_multiobject_revert(),
        "P7": probe_p7_shared_font_stale(),
        "P8": probe_p8_encrypted_keep(),
        "P9": probe_p9_prior_undo(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run_all(), indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
