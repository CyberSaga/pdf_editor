"""Red-light tests for shadow/tiered engine integration (plan Task 7).

Shadow mode classifies every edit and logs sanitized reason codes only —
it must never mutate the document, change history/pending state, or alter
the legacy result.  Tiered mode enters the new engine only for supported
plans; a Tier 0 commit must not touch any legacy machinery (redaction,
push-down, protected replay, pending cleanup, Track A/B reflow).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.pdf_text_edit as pdf_text_edit_module  # noqa: E402
from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitTier,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica
WIDER = "Price 2W24"  # W is wider than a digit: advance mismatch
DOWNSTREAM = "Downstream line stays"


def _write_tier0_pdf(path: Path) -> None:
    """Raw literal-Tj page — the Tier 0 eligible fixture."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()


def _write_base14_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def _open(path: Path, settings: TextCommitSettings) -> PDFModel:
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _edit(model: PDFModel, probe: str, new_text: str, **kwargs) -> EditTextResult:
    block = next(
        b for b in model.block_manager.get_blocks(0) if probe in (b.text or "")
    )
    return model.edit_text(
        1,
        fitz.Rect(block.layout_rect),
        new_text,
        original_text=block.text,
        **kwargs,
    )


# ---------------------------------------------------------------- shadow


def test_shadow_classifies_and_logs_without_affecting_result(tmp_path, caplog):
    pdf_path = tmp_path / "b14.pdf"
    _write_base14_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="shadow"))
    try:
        with caplog.at_level(logging.INFO, logger="model.pdf_text_edit"):
            result = _edit(model, "Hello World", "Hallo World")
        assert result is EditTextResult.SUCCESS
        assert "Hallo World" in model.doc[0].get_text()  # legacy still committed

        shadow_records = [
            r for r in caplog.records if "text_commit_shadow" in r.getMessage()
        ]
        assert len(shadow_records) == 1
        message = shadow_records[0].getMessage()
        # PyMuPDF-authored pages carry [<hex>]TJ: honest tier0 rejection code
        assert RejectReason.NOT_SINGLE_LITERAL_TJ in message
        assert model.last_commit_outcome is not None
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
    finally:
        model.close()


def test_shadow_matches_legacy_side_effects(tmp_path):
    path_a = tmp_path / "legacy.pdf"
    path_b = tmp_path / "shadow.pdf"
    _write_base14_pdf(path_a)
    _write_base14_pdf(path_b)
    legacy = _open(path_a, TextCommitSettings())
    shadow = _open(path_b, TextCommitSettings(engine="shadow"))
    try:
        assert _edit(legacy, "Hello World", "Hallo World") is EditTextResult.SUCCESS
        assert _edit(shadow, "Hello World", "Hallo World") is EditTextResult.SUCCESS
        assert legacy.doc[0].get_text() == shadow.doc[0].get_text()
        assert len(shadow.pending_edits) == len(legacy.pending_edits)
        assert not shadow.fidelity_protected_pages  # shadow never protects
    finally:
        legacy.close()
        shadow.close()


def test_shadow_logs_no_document_text(tmp_path, caplog):
    pdf_path = tmp_path / "b14.pdf"
    _write_base14_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="shadow"))
    try:
        with caplog.at_level(logging.INFO, logger="model.pdf_text_edit"):
            _edit(model, "Hello World", "Hallo World")
        assert any(
            "text_commit_shadow" in r.getMessage() for r in caplog.records
        )  # guards against a vacuous pass with shadow unimplemented
        for record in caplog.records:
            message = record.getMessage()
            assert "Hello" not in message
            assert "Hallo" not in message
    finally:
        model.close()


def test_shadow_engine_error_never_breaks_the_edit(tmp_path, monkeypatch):
    pdf_path = tmp_path / "b14.pdf"
    _write_base14_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="shadow"))
    try:
        def _boom(*args, **kwargs):
            raise RuntimeError("injected shadow failure")

        # Shadow classifies via prepare_plan since Slice 1 (parity with the
        # tiered path's common gates); the containment claim is unchanged.
        monkeypatch.setattr(pdf_text_edit_module, "prepare_plan", _boom)
        result = _edit(model, "Hello World", "Hallo World")
        assert result is EditTextResult.SUCCESS
        assert "Hallo World" in model.doc[0].get_text()
    finally:
        model.close()


# ---------------------------------------------------------------- tiered


def test_tiered_commits_tier0_without_legacy_machinery(tmp_path, monkeypatch):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        calls: dict[str, int] = {"redact_insert": 0, "push_down": 0, "replay": 0,
                                 "add_redact": 0, "apply_redactions": 0}
        real_apply = pdf_text_edit_module._apply_redact_insert

        def _spy_apply(*a, **k):
            calls["redact_insert"] += 1
            return real_apply(*a, **k)

        monkeypatch.setattr(pdf_text_edit_module, "_apply_redact_insert", _spy_apply)
        monkeypatch.setattr(
            pdf_text_edit_module,
            "_push_down_overlapping_text",
            lambda *a, **k: calls.__setitem__("push_down", calls["push_down"] + 1),
        )
        monkeypatch.setattr(
            pdf_text_edit_module,
            "_replay_protected_spans",
            lambda *a, **k: calls.__setitem__("replay", calls["replay"] + 1),
        )
        real_add_redact = fitz.Page.add_redact_annot
        real_apply_red = fitz.Page.apply_redactions

        def _spy_add(self, *a, **k):
            calls["add_redact"] += 1
            return real_add_redact(self, *a, **k)

        def _spy_apply_red(self, *a, **k):
            calls["apply_redactions"] += 1
            return real_apply_red(self, *a, **k)

        monkeypatch.setattr(fitz.Page, "add_redact_annot", _spy_add)
        monkeypatch.setattr(fitz.Page, "apply_redactions", _spy_apply_red)

        result = _edit(model, TARGET, REPLACEMENT)
        assert result is EditTextResult.SUCCESS

        text = model.doc[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert DOWNSTREAM in text

        assert calls == {
            "redact_insert": 0,
            "push_down": 0,
            "replay": 0,
            "add_redact": 0,
            "apply_redactions": 0,
        }
        assert model.pending_edits == []  # nothing queued for clean_contents
        assert 0 in model.fidelity_protected_pages
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert outcome.allows_external_reflow is False

        # block index was rebuilt so follow-up edits resolve the new text
        assert any(
            REPLACEMENT in (b.text or "") for b in model.block_manager.get_blocks(0)
        )
    finally:
        model.close()


def test_tiered_falls_back_to_legacy_with_reason_chain(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        result = _edit(model, TARGET, WIDER)
        assert result is EditTextResult.SUCCESS  # legacy handled it
        assert WIDER in model.doc[0].get_text()
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.tier is CommitTier.TIER2_LEGACY
        assert outcome.fallback_chain[0] == f"tier0:{RejectReason.ADVANCE_MISMATCH}"
        assert len(model.pending_edits) == 1  # legacy queued its cleanup
        assert 0 not in model.fidelity_protected_pages
    finally:
        model.close()


def test_tiered_strict_rejects_without_mutation(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered", strict=True))
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        result = _edit(model, TARGET, WIDER)
        assert result is EditTextResult.REJECTED_STRICT
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert TARGET in model.doc[0].get_text()
        assert model.pending_edits == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.tier is None
        assert outcome.degraded_reason == RejectReason.ADVANCE_MISMATCH
    finally:
        model.close()


def test_tiered_commit_history_undo_and_no_reflow(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        reflow_calls: list[str] = []
        block = next(
            b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or "")
        )
        command = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
            reflow_fn=lambda: reflow_calls.append("reflow"),
        )
        assert command.execute() is True
        assert command.outcome is not None
        assert command.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert reflow_calls == []  # Track A/B blocked by the outcome

        command.undo()
        assert TARGET in model.doc[0].get_text()
        assert REPLACEMENT not in model.doc[0].get_text()
    finally:
        model.close()
