"""Red-light matrix for V0c's target-local show-operator proof."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, CommitTier, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import replay_page  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
    verify_tier1_commit,
)
from model.text_commit.replay import DEFAULT_MAX_REPLAY_BYTES  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    build_identity_h_fixture,
)

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


def _origins(page: fitz.Page, text: str) -> tuple[tuple[float, float], ...]:
    found: list[tuple[float, float]] = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    if char["c"] in text:
                        found.append(tuple(float(v) for v in char["origin"]))
    return tuple(found)


def _prepare_cjk(source: str, replacement: str) -> tuple[object, TieredCommitEngine, PreparedEdit]:
    fixture = build_identity_h_fixture(text=source, tail_text=source)
    stream = fixture.content_bytes()
    separator = b"> Tj <"
    assert stream.count(separator) == 1
    # Keep the independent neighbor disjoint from the target by a 1pt gap,
    # but still inside V0c's 2pt halo.  An overlapping identical painter is
    # not a legitimate neighbor; plan-time admission rejects it separately.
    neighbor_x = fixture.origin[0] + len(source) * fixture.fontsize + 1.0
    stream = stream.replace(
        separator,
        f"> Tj 1 0 0 1 {neighbor_x:g} {fixture.origin[1]:g} Tm <".encode(),
    )
    fixture.doc.update_stream(fixture.content_xref, stream)
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    expected_origin = _origins(fixture.page, source)[0]
    prepared = engine.prepare(
        fixture.page,
        target_text=source,
        replacement_text=replacement,
        expected_origin=expected_origin,
        target_bbox=None,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    return fixture, engine, prepared


def test_tier0_neighbor_may_legitimately_contain_the_source_text() -> None:
    fixture, engine, prepared = _prepare_cjk("你", "再")
    assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    before = fixture.content_bytes()
    before_replay = replay_page(fixture.doc, fixture.page)

    outcome = engine.commit(prepared)

    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert "target_operator_reproven" in outcome.verified_properties
    after = fixture.content_bytes()
    after_replay = replay_page(fixture.doc, fixture.page)
    assert after[: prepared.replacement.start] == before[: prepared.replacement.start]
    tail_len = len(before) - prepared.replacement.end
    assert after[len(after) - tail_len :] == before[prepared.replacement.end :]
    assert after_replay.shows[1].decoded_bytes == before_replay.shows[1].decoded_bytes
    assert after_replay.shows[1].origin_user == before_replay.shows[1].origin_user
    fixture.doc.close()


def test_tier1_neighbor_may_legitimately_contain_the_source_text() -> None:
    fixture, engine, prepared = _prepare_cjk("你好", "再")
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    before_replay = replay_page(fixture.doc, fixture.page)

    outcome = engine.commit(prepared)

    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert "target_operator_reproven" in outcome.verified_properties
    after_replay = replay_page(fixture.doc, fixture.page)
    assert after_replay.shows[0].operator == "TJ"
    assert after_replay.shows[0].array_item_count == 1
    assert after_replay.shows[1].decoded_bytes == before_replay.shows[1].decoded_bytes
    assert after_replay.shows[1].origin_user == before_replay.shows[1].origin_user
    fixture.doc.close()


def _latin_doc(source: bytes = b"a") -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, b"BT /F1 12 Tf 72 700 Td (" + source + b") Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _latin_plan(
    doc: fitz.Document, *, source: str = "a", replacement: str = "b"
) -> PreparedEdit:
    span = doc[0].get_text("rawdict")["blocks"][0]["lines"][0]["spans"][0]
    prepared = prepare_plan(
        doc,
        doc[0],
        target_text=source,
        replacement_text=replacement,
        expected_origin=tuple(span["origin"]),
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
        max_tier=1,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    return prepared


def _apply_tampered(doc: fitz.Document, prepared: PreparedEdit, payload: bytes) -> tuple[PreparedEdit, object]:
    replacement = dataclasses.replace(
        prepared.replacement,
        replacement_bytes=payload,
    )
    tampered = dataclasses.replace(prepared, replacement=replacement)
    pre_state = capture_page_state(doc, doc[0], tampered)
    apply_patchset(
        doc,
        doc[0],
        PatchSet(
            page_xref=tampered.page_xref,
            replacements=(replacement,),
            expected_page_fingerprint=tampered.page_fingerprint,
        ),
    )
    return tampered, pre_state


def test_tier0_rejects_a_splice_that_is_not_exactly_one_operand() -> None:
    doc = _latin_doc()
    prepared = _latin_plan(doc)
    tampered, pre_state = _apply_tampered(doc, prepared, b"(a)(b)")
    result = verify_tier0_commit(doc, doc[0], tampered, pre_state)
    assert isinstance(result, VerificationFailure), result
    assert result.reason == RejectReason.VERIFICATION_FAILED
    assert "target operator" in result.detail
    doc.close()


def test_tier1_rejects_more_than_one_string_array_item() -> None:
    doc = _latin_doc(b"MM")
    prepared = _latin_plan(doc, source="MM", replacement="i")
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    payload = b"[(x)(y) 0] TJ"
    tampered, pre_state = _apply_tampered(doc, prepared, payload)
    tampered = dataclasses.replace(tampered, replacement_text="xy")
    result = verify_tier1_commit(doc, doc[0], tampered, pre_state)
    assert isinstance(result, VerificationFailure), result
    assert result.reason == RejectReason.VERIFICATION_FAILED
    assert "target operator" in result.detail
    doc.close()


def test_isolated_tier1_replay_refusal_fails_closed(monkeypatch) -> None:
    import model.text_commit.verify as verify_module

    doc = _latin_doc(b"MM")
    prepared = _latin_plan(doc, source="MM", replacement="i")
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    pre_state = capture_page_state(doc, doc[0], prepared)
    apply_patchset(
        doc,
        doc[0],
        PatchSet(
            page_xref=prepared.page_xref,
            replacements=(prepared.replacement,),
            expected_page_fingerprint=prepared.page_fingerprint,
        ),
    )
    replay = replay_page(doc, doc[0])
    refused = dataclasses.replace(replay, shows=(), refusal_reason="forced")

    def _refuse_replay(*args, **kwargs):
        assert args[0] == [
            (prepared.replacement.stream_xref, prepared.replacement.replacement_bytes)
        ]
        assert kwargs["max_decoded_bytes"] == DEFAULT_MAX_REPLAY_BYTES
        return refused

    monkeypatch.setattr(
        verify_module, "replay_page_streams", _refuse_replay, raising=False
    )
    result = verify_tier1_commit(doc, doc[0], prepared, pre_state)
    assert isinstance(result, VerificationFailure), result
    assert result.reason == RejectReason.VERIFICATION_FAILED
    assert "target operator" in result.detail
    doc.close()


def test_operator_proof_never_replays_the_full_patched_stream(monkeypatch) -> None:
    import model.text_commit.verify as verify_module

    doc = _latin_doc(b"MM")
    prepared = _latin_plan(doc, source="MM", replacement="i")
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    pre_state = capture_page_state(doc, doc[0], prepared)
    apply_patchset(
        doc,
        doc[0],
        PatchSet(
            page_xref=prepared.page_xref,
            replacements=(prepared.replacement,),
            expected_page_fingerprint=prepared.page_fingerprint,
        ),
    )
    real_replay = verify_module.replay_page_streams
    calls: list[tuple[list[tuple[int, bytes]], int | None]] = []

    def _record_replay(streams, *, max_decoded_bytes=DEFAULT_MAX_REPLAY_BYTES):
        calls.append((streams, max_decoded_bytes))
        assert streams == [
            (prepared.replacement.stream_xref, prepared.replacement.replacement_bytes)
        ]
        return real_replay(streams, max_decoded_bytes=max_decoded_bytes)

    monkeypatch.setattr(verify_module, "replay_page_streams", _record_replay)
    result = verify_tier1_commit(doc, doc[0], prepared, pre_state)
    assert not isinstance(result, VerificationFailure), result
    assert calls == [
        (
            [(prepared.replacement.stream_xref, prepared.replacement.replacement_bytes)],
            DEFAULT_MAX_REPLAY_BYTES,
        )
    ]
    doc.close()
