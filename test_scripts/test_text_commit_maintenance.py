"""Red-light tests for the clean_contents maintenance policy (plan Task 7).

A fidelity-protected page (one that received a Tier 0 commit) must never
be passed through ``clean_contents`` — not by the interactive maintenance
pass and not by save preparation.  Legacy content rewrites go through one
chokepoint (``mark_page_content_dirty``) which queues the cleanup AND
revokes the page's protection, defining how legacy-edited and
Tier-0-edited pages coexist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.text_commit.dto import RejectReason, TextCommitSettings  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"


def _write_two_page_pdf(path: Path) -> None:
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Some page text", fontsize=12.0, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def _write_tier0_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (Downstream line stays) Tj ET"
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


def _open(path: Path, settings: TextCommitSettings | None = None) -> PDFModel:
    model = PDFModel(text_commit_settings=settings or TextCommitSettings())
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _edit(model: PDFModel, probe: str, new_text: str) -> EditTextResult:
    block = next(
        b for b in model.block_manager.get_blocks(0) if probe in (b.text or "")
    )
    return model.edit_text(
        1, fitz.Rect(block.layout_rect), new_text, original_text=block.text
    )


def test_mark_page_content_dirty_queues_and_revokes_protection(tmp_path):
    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        model.fidelity_protected_pages.add(0)
        model.mark_page_content_dirty(0, fitz.Rect(10, 10, 100, 100))
        assert 0 not in model.fidelity_protected_pages
        assert model.pending_edits == [
            {"page_idx": 0, "rect": fitz.Rect(10, 10, 100, 100)}
        ]
    finally:
        model.close()


def test_apply_pending_redactions_skips_fidelity_protected_pages(
    tmp_path, monkeypatch
):
    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        cleaned: list[int] = []
        real_clean = fitz.Page.clean_contents

        def _spy(self, *args, **kwargs):
            cleaned.append(self.number)
            return real_clean(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "clean_contents", _spy)

        # belt-and-braces state: a protected page somehow carries a pending
        # entry — the maintenance pass must still refuse to clean it
        model.pending_edits.append({"page_idx": 0, "rect": fitz.Rect(0, 0, 5, 5)})
        model.pending_edits.append({"page_idx": 1, "rect": fitz.Rect(0, 0, 5, 5)})
        model.fidelity_protected_pages.add(0)

        model.apply_pending_redactions()

        assert cleaned == [1]
        # the protected page's entry survives; the cleaned page's is consumed
        assert [e["page_idx"] for e in model.pending_edits] == [0]
    finally:
        model.close()


def test_save_preparation_respects_protection(tmp_path, monkeypatch):
    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        cleaned: list[int] = []
        real_clean = fitz.Page.clean_contents

        def _spy(self, *args, **kwargs):
            cleaned.append(self.number)
            return real_clean(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "clean_contents", _spy)
        model.pending_edits.append({"page_idx": 0, "rect": fitz.Rect(0, 0, 5, 5)})
        model.pending_edits.append({"page_idx": 1, "rect": fitz.Rect(0, 0, 5, 5)})
        model.fidelity_protected_pages.add(1)

        model.save_as(str(tmp_path / "saved.pdf"))
        assert cleaned == [0]
    finally:
        model.close()


def test_pending_maintenance_blocks_tier0_on_that_page(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        # a legacy rewrite is already queued for this page
        model.mark_page_content_dirty(0, fitz.Rect(0, 0, 10, 10))

        result = _edit(model, TARGET, REPLACEMENT)
        assert result is EditTextResult.SUCCESS  # legacy fallback commits
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.fallback_chain[0] == (
            f"tier0:{RejectReason.PENDING_MAINTENANCE}"
        )
        assert 0 not in model.fidelity_protected_pages
    finally:
        model.close()


def test_legacy_edit_on_protected_page_drops_protection(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        assert 0 in model.fidelity_protected_pages

        # a later legacy-only edit (advance mismatch rejects Tier 0) rewrites
        # the page and must revoke its byte-fidelity protection
        assert (
            _edit(model, REPLACEMENT, "Price 2W25") is EditTextResult.SUCCESS
        )
        assert 0 not in model.fidelity_protected_pages
        assert [e["page_idx"] for e in model.pending_edits] == [0]
    finally:
        model.close()
