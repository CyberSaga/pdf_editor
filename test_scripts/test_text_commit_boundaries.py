"""Red-light tests for Tier 0 identity/undo/redo boundaries (plan Task 9).

Covers the plan's explicit boundary doctrine:

* Annotations must survive a Tier 0 commit with their xref, dictionary, and
  appearance stream physically untouched (page_fingerprint alone is not
  proof -- it hashes annot xref+rect only, never the /AP stream, per
  model/text_commit/inspect.py:66-68).
* Signed documents and widget-bearing pages must REJECT a tiered edit --
  never silently degrade to the legacy engine, in strict *or* non-strict
  mode.
* Undo must restore source semantics (and, ideally, source *bytes*) and the
  page's fidelity-protection membership.
* Redo must re-apply the same validated intent, or fail STALE_PLAN with
  zero mutation -- never silently re-route through the legacy engine.

Today's implementation (edit_commands.py) undoes every EditTextCommand via
an unconditional page-snapshot swap (delete_page + insert_pdf) and re-does
by re-running the entire model.edit_text() pipeline from scratch. Both are
missing the tier-aware reversal machinery the plan requires, so most tests
below are the RED light for that gap -- marked inline. Each was run against
the current tree before being written down here (see the task's returned
transcript), so the failures below are measured, not guessed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica
DOWNSTREAM = "Downstream line stays"


def _add_tier0_page(doc: fitz.Document) -> fitz.Page:
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
    return page


def _write_tier0_pdf(path: Path) -> None:
    doc = fitz.open()
    _add_tier0_page(doc)
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


def _make_command(model: PDFModel, probe: str, new_text: str) -> EditTextCommand:
    block = next(
        b for b in model.block_manager.get_blocks(0) if probe in (b.text or "")
    )
    return EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=None,
        old_block_text=block.text,
    )


def _ap_stream_bytes(doc: fitz.Document, annot_xref: int) -> bytes | None:
    """Read the /AP /N appearance stream bytes referenced by an annot xref.

    page_fingerprint deliberately does not cover this (inspect.py:66-68 hashes
    annot xref+rect only), so annotation-*appearance* identity needs its own
    direct check.
    """
    obj = doc.xref_object(annot_xref)
    match = re.search(r"/AP\s*<<[^>]*?/N\s+(\d+)\s+0\s+R", obj)
    if not match:
        return None
    return doc.xref_stream(int(match.group(1)))


# ---------------------------------------------------------------- annotation identity


def test_annotation_identity_preserved_through_tier0_commit(tmp_path):
    """RED -- root cause is NOT the Tier 0 patch primitive itself.

    model/text_commit/patch.py only ever calls ``doc.update_stream`` on the
    target content stream (confirmed directly against TieredCommitEngine in
    isolation: the annotation dict is untouched). The mutation instead comes
    from ``PDFModel._capture_page_snapshot`` (pdf_model.py:3227-3243), which
    ``edit_text`` calls *unconditionally* -- before either engine runs -- to
    capture the undo snapshot: ``tmp_doc.insert_pdf(self.doc, from_page=...,
    to_page=...)``. Measured directly: calling ``insert_pdf`` with a page
    range on a *source* document that has an annotation strips that
    annotation's ``/P`` (parent-page) key on the SOURCE document as a side
    effect (a PyMuPDF behavior, reproduced with no model code involved).
    This is a pre-existing, engine-agnostic defect -- every edit_text() call
    triggers it, Tier 0 or legacy -- made visible here because Task 9 asks
    for full annotation *dictionary* identity through a Tier 0 commit
    specifically. xref, rect, and the /AP appearance stream all survive;
    only the /P back-reference is silently dropped.
    """
    pdf_path = tmp_path / "tier0.pdf"
    doc = fitz.open()
    page = _add_tier0_page(doc)
    page.add_highlight_annot(fitz.Rect(72, 660, 200, 715))
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        page0 = model.doc[0]
        annot_before = next(iter(page0.annots()))
        annot_xref = annot_before.xref
        annot_rect_before = tuple(annot_before.rect)
        annot_object_before = model.doc.xref_object(annot_xref)
        ap_before = _ap_stream_bytes(model.doc, annot_xref)
        assert ap_before  # sanity: fixture actually has an appearance stream

        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        page0_after = model.doc[0]
        annots_after = list(page0_after.annots())
        assert len(annots_after) == 1
        assert annots_after[0].xref == annot_xref
        assert tuple(annots_after[0].rect) == annot_rect_before
        assert model.doc.xref_object(annot_xref) == annot_object_before
        assert _ap_stream_bytes(model.doc, annot_xref) == ap_before
    finally:
        model.close()


# ---------------------------------------------------------------- hard-reject boundary


def test_widget_page_rejects_never_degrades(tmp_path):
    """RED -- the gap this task closes.

    prepare_tier0_plan already refuses a widget-bearing page with
    RejectReason.SIGNED_OR_WIDGET_TARGET (model/text_commit/plan.py:110-114).
    But in the tiered engine's *non-strict* mode (settings.strict=False, the
    default), pdf_text_edit.py's tiered branch (~1471-1505) only hard-rejects
    when settings.strict is True; otherwise it silently falls through to the
    legacy redact+reinsert engine and SUCCEEDS -- exactly the silent-degrade
    the plan forbids for signed/widget targets specifically. Measured today:
    result is EditTextResult.SUCCESS via the legacy path, mutating the page.
    """
    pdf_path = tmp_path / "widget.pdf"
    doc = fitz.open()
    page = _add_tier0_page(doc)
    widget = fitz.Widget()
    widget.field_name = "field1"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(300, 300, 420, 322)
    page.add_widget(widget)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))  # strict=False
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        result = _edit(model, TARGET, REPLACEMENT)

        assert result is not EditTextResult.SUCCESS
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert TARGET in model.doc[0].get_text()
        assert model.pending_edits == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.fallback_chain == (
            f"tier0:{RejectReason.SIGNED_OR_WIDGET_TARGET}",
        )
    finally:
        model.close()


def test_signed_document_rejects_never_degrades(tmp_path):
    """RED -- same gap as the widget case, for a signed document (AcroForm
    /SigFlags > 0). page_has_widgets_or_signatures (inspect.py:75-83) keys
    off doc.get_sigflags() > 0, so a real signature is not required to
    reproduce this."""
    pdf_path = tmp_path / "signed.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)
    acroform_xref = doc.get_new_xref()
    doc.update_object(acroform_xref, "<< /Fields [] /SigFlags 3 >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{acroform_xref} 0 R")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        result = _edit(model, TARGET, REPLACEMENT)

        assert result is not EditTextResult.SUCCESS
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert TARGET in model.doc[0].get_text()
        assert model.pending_edits == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.fallback_chain == (
            f"tier0:{RejectReason.SIGNED_OR_WIDGET_TARGET}",
        )
    finally:
        model.close()


# --------------------------------------------------------------------- undo


def test_undo_restores_source_bytes_annotations_and_protection_state(tmp_path):
    """RED -- EditTextCommand.undo() (edit_commands.py:229-254) unconditionally
    restores via _restore_page_from_snapshot (pdf_model.py:3266-3300:
    insert_pdf + delete_page). That replaces the page's xref and recreates
    its annotations under new object numbers, and never restores
    fidelity_protected_pages membership. A Tier 0 undo should instead replay
    the inverse PatchSet: byte-identical fingerprint, untouched annotation
    xref, and protection membership restored to its pre-commit value.
    """
    pdf_path = tmp_path / "tier0.pdf"
    doc = fitz.open()
    page = _add_tier0_page(doc)
    page.add_highlight_annot(fitz.Rect(72, 660, 200, 715))
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        page0 = model.doc[0]
        pre_commit_fingerprint = page_fingerprint(model.doc, page0)
        annot_xref_before = next(iter(page0.annots())).xref
        assert 0 not in model.fidelity_protected_pages

        cmd = _make_command(model, TARGET, REPLACEMENT)
        model.command_manager.execute(cmd)
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert 0 in model.fidelity_protected_pages

        assert model.command_manager.undo() is True

        assert TARGET in model.doc[0].get_text()
        assert REPLACEMENT not in model.doc[0].get_text()
        assert page_fingerprint(model.doc, model.doc[0]) == pre_commit_fingerprint
        assert 0 not in model.fidelity_protected_pages
        annots_after = list(model.doc[0].annots())
        assert len(annots_after) == 1
        assert annots_after[0].xref == annot_xref_before
    finally:
        model.close()


def test_undo_after_external_change_falls_back_to_snapshot_semantics(tmp_path):
    """PARTIAL RED: today's undo is *always* the snapshot fallback, so text
    SEMANTICS survive drift correctly (that half is a passing
    characterization) -- but fidelity_protected_pages membership is still
    never dropped, which is the plan's required behavior for this exact
    fallback path. Measured: text reverts, but page 0 stays incorrectly
    marked fidelity-protected after undo."""
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        cmd = _make_command(model, TARGET, REPLACEMENT)
        model.command_manager.execute(cmd)
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        # Out-of-band drift on the just-committed page (e.g. another tool
        # or a concurrent maintenance pass), staleing any retained inverse.
        stream_xref = model.doc[0].get_contents()[0]
        stream = model.doc.xref_stream(stream_xref)
        drifted = stream.replace(REPLACEMENT.encode(), b"Price 9999")
        model.doc.update_stream(stream_xref, drifted)

        assert model.command_manager.undo() is True

        text = model.doc[0].get_text()
        assert TARGET in text  # semantics recovered (characterization)
        assert REPLACEMENT not in text
        assert 0 not in model.fidelity_protected_pages  # RED: still protected today
    finally:
        model.close()


# --------------------------------------------------------------------- redo


def test_redo_reapplies_same_validated_intent(tmp_path):
    """RED -- redo (CommandManager.redo -> cmd.execute()) re-runs the entire
    model.edit_text() pipeline from scratch rather than replaying the
    retained forward PatchSet. Measured: the replacement text and TIER0
    outcome do reappear (the pipeline still finds the same eligible target
    on the snapshot-restored page), but the resulting page_fingerprint does
    NOT match the first commit's -- the underlying stream/font xrefs differ
    because undo's snapshot restore reallocated new object numbers. A
    validated-intent redo must reproduce the exact same committed state.
    """
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        cmd = _make_command(model, TARGET, REPLACEMENT)
        model.command_manager.execute(cmd)
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        fingerprint_after_first_commit = page_fingerprint(model.doc, model.doc[0])

        assert model.command_manager.undo() is True
        assert model.command_manager.redo() is True

        text = model.doc[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert (
            page_fingerprint(model.doc, model.doc[0]) == fingerprint_after_first_commit
        )
    finally:
        model.close()


def test_redo_after_external_change_fails_stale_without_mutation(tmp_path):
    """RED -- the core stale-safety requirement.

    Measured against this tree: after undo, an out-of-band drift of the
    committed text (simulating another actor touching the file between undo
    and redo) causes Tier 0 re-preparation to fail with NO_MATCH; in
    non-strict mode (the default) the tiered branch of edit_text() then
    silently falls through to the legacy redact+reinsert engine and
    SUCCEEDS -- mutating the page. redo() consequently returns True (should
    be False), the command is popped off the redo stack (should remain,
    per plan doctrine "fails STALE without partial mutation"), and the
    resulting outcome tier is TIER2_LEGACY (should be a STALE_PLAN
    CommitOutcome with zero mutation).
    """
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        cmd = _make_command(model, TARGET, REPLACEMENT)
        model.command_manager.execute(cmd)
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert model.command_manager.undo() is True
        assert TARGET in model.doc[0].get_text()

        # Out-of-band drift between undo and redo.
        stream_xref = model.doc[0].get_contents()[0]
        stream = model.doc.xref_stream(stream_xref)
        drifted = stream.replace(TARGET.encode(), b"Price 9999")
        model.doc.update_stream(stream_xref, drifted)
        fingerprint_before_redo = page_fingerprint(model.doc, model.doc[0])

        redo_ok = model.command_manager.redo()

        assert redo_ok is False
        assert model.command_manager.can_redo() is True
        assert (
            page_fingerprint(model.doc, model.doc[0]) == fingerprint_before_redo
        )  # zero mutation
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.STALE_PLAN
    finally:
        model.close()
