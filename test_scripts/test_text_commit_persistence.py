"""Red-light tests for Tier 0 persistence across save/reopen paths (plan Task 9).

Boundary doctrine pinned throughout this file: a Tier 0 commit promises
supported *live-commit* semantics and tested save/reopen *content* survival
-- it never promises whole-file byte or xref identity after a full save or
garbage collection (``page_fingerprint``/plan tokens hash xref numbers and
are legitimately invalidated by ``garbage=4`` rewrites). "Unchanged" is
always proven via ``model.text_commit.inspect.page_fingerprint`` or a direct
xref/stream comparison -- never whole-file ``tobytes()``/``read_bytes()``
equality, because the trailer ``/ID`` is never byte-stable (see PITFALLS).
The one legitimate whole-file assertion is that ``save_as`` to a *different*
path leaves the original on-disk file's bytes untouched.

Most tests below are CHARACTERIZATION tests: they pin save-chokepoint
behavior (``PDFModel._save_doc`` / ``save_as`` / ``_full_save_to_path`` /
``_atomic_full_save``, all funneling through ``encryption=PDF_ENCRYPT_KEEP``)
that already works today and are expected to PASS at Red -- each is marked
inline. The encrypted-document tests are the exception: they demonstrate a
real, currently-uncaught defect (see the docstring on each) and are expected
to FAIL at Red, same as everything in test_text_commit_boundaries.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import CommitTier, TextCommitSettings  # noqa: E402
from model.text_commit.inspect import page_fingerprint  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica
DOWNSTREAM = "Downstream line stays"


def _add_tier0_page(doc: fitz.Document) -> fitz.Page:
    """Append a raw literal-Tj page (the Tier 0 eligible fixture) to ``doc``."""
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


def _open(
    path: Path, settings: TextCommitSettings, password: str | None = None
) -> PDFModel:
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path), password=password)
    model.ensure_page_index_built(1)
    return model


def _edit(model: PDFModel, probe: str, new_text: str, page_num: int = 1, **kwargs):
    page_idx = page_num - 1
    block = next(
        b for b in model.block_manager.get_blocks(page_idx) if probe in (b.text or "")
    )
    return model.edit_text(
        page_num,
        fitz.Rect(block.layout_rect),
        new_text,
        original_text=block.text,
        **kwargs,
    )


# ---------------------------------------------------------------- unencrypted


def test_tier0_commit_survives_incremental_save_and_reopen(tmp_path):
    """CHARACTERIZATION (passes today): a Tier 0 patch is a plain
    ``doc.update_stream`` on an existing object, so ``can_save_incrementally``
    stays true; ``save_as`` back to the original path takes the incremental
    branch (save_as, pdf_model.py:3688-3704) and the original bytes remain a
    verbatim prefix of the saved file."""
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    original_bytes = pdf_path.read_bytes()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        fingerprint_after_commit = page_fingerprint(model.doc, model.doc[0])

        assert model.doc.can_save_incrementally()
        model.save_as(str(pdf_path))
    finally:
        model.close()

    saved_bytes = pdf_path.read_bytes()
    assert len(saved_bytes) > len(original_bytes)
    assert saved_bytes[: len(original_bytes)] == original_bytes  # incremental prefix

    reopened = fitz.open(str(pdf_path))
    try:
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert DOWNSTREAM in text
    finally:
        reopened.close()

    # A fresh session's fingerprint of the reopened page matches the
    # in-session post-commit fingerprint: xref numbers and decoded stream
    # bytes both survived the incremental round-trip untouched.
    model2 = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert page_fingerprint(model2.doc, model2.doc[0]) == fingerprint_after_commit
    finally:
        model2.close()


def test_tier0_commit_survives_full_save_and_reopen(tmp_path):
    """CHARACTERIZATION (passes today) + explicit doctrine pin: forcing the
    ``secure_save_required`` atomic ``garbage=4`` rewrite (pdf_model.py:3114
    -3163) renumbers xrefs, so ``page_fingerprint`` identity is explicitly
    NOT asserted here -- only that the edit and the annotation survive the
    rewrite semantically."""
    pdf_path = tmp_path / "tier0.pdf"
    doc = fitz.open()
    page = _add_tier0_page(doc)
    page.add_highlight_annot(fitz.Rect(72, 660, 200, 715))
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        model.secure_save_required = True  # force the atomic garbage=4 path
        model.save_as(str(pdf_path))

        text = model.doc[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert DOWNSTREAM in text
        assert len(list(model.doc[0].annots())) == 1
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert len(list(reopened[0].annots())) == 1
    finally:
        reopened.close()


def test_save_as_new_path_preserves_edit_and_leaves_original_untouched(tmp_path):
    """CHARACTERIZATION (passes today): the one legitimate whole-file byte
    assertion in this suite -- saving to a brand-new path is a plain
    ``_save_doc`` call on the still-open original handle, so the original
    file on disk is never touched."""
    original_path = tmp_path / "original.pdf"
    new_path = tmp_path / "saved_copy.pdf"
    _write_tier0_pdf(original_path)
    original_bytes_before = original_path.read_bytes()

    model = _open(original_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        model.save_as(str(new_path))
    finally:
        model.close()

    assert original_path.read_bytes() == original_bytes_before

    reopened = fitz.open(str(new_path))
    try:
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
    finally:
        reopened.close()


def test_legacy_edit_then_tier0_edit_both_persist(tmp_path):
    """CHARACTERIZATION (passes today): apply_pending_redactions (pdf_model.py
    :3360-3386) cleans the legacy-edited page's pending entry through
    clean_contents at save time but skips the fidelity-protected Tier 0 page
    entirely -- both edits, and the Tier 0 page's downstream text, survive
    reopen."""
    pdf_path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)  # page 1 (1-based): Tier 0 eligible
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 100), "Legacy Text Here", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        model.ensure_page_index_built(2)
        result_legacy = _edit(
            model, "Legacy Text Here", "Legacy Text Changed", page_num=2
        )
        assert result_legacy is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
        assert any(e["page_idx"] == 1 for e in model.pending_edits)
        assert 1 not in model.fidelity_protected_pages

        result_tier0 = _edit(model, TARGET, REPLACEMENT, page_num=1)
        assert result_tier0 is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert 0 in model.fidelity_protected_pages

        model.save_as(str(pdf_path))
        # page 1's pending legacy entry was cleaned; page 0 was never queued
        assert model.pending_edits == []
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        assert "Legacy Text Changed" in reopened[1].get_text()
        text0 = reopened[0].get_text()
        assert REPLACEMENT in text0
        assert TARGET not in text0
        assert DOWNSTREAM in text0
    finally:
        reopened.close()


def test_reopen_after_save_allows_fresh_tier0_edit(tmp_path):
    """CHARACTERIZATION (passes today): plan tokens/fingerprints are legitimately
    session-local -- a brand-new PDFModel session over the saved file can
    prepare and commit an independent Tier 0 edit with no cross-session
    leakage of stale state."""
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        model.save_as(str(pdf_path))
    finally:
        model.close()

    model2 = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        # "Downstream line static" is advance-neutral vs DOWNSTREAM in Helvetica
        # (both text_length to 120.696pt @ 12pt) -- keeps this edit Tier 0 eligible.
        result = _edit(model2, DOWNSTREAM, "Downstream line static")
        assert result is EditTextResult.SUCCESS
        assert model2.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        text = model2.doc[0].get_text()
        assert "Downstream line static" in text
        assert REPLACEMENT in text  # first session's edit still present
    finally:
        model2.close()


# ------------------------------------------------------------------ encrypted


def test_encrypted_doc_tier0_commit_and_save_keeps_encryption(tmp_path):
    """RED -- real defect, not a missing-feature gap.

    ``TieredCommitEngine.prepare`` (model/text_commit/engine.py:95) proves
    every candidate on a scratch copy via
    ``fitz.open("pdf", self._doc.tobytes())`` -- called with the *default*
    ``encryption`` argument (``NONE``) directly on the *live*, authenticated
    document handle. This is precisely the operation
    ``test_worker_snapshot_before_edit_does_not_corrupt_later_encrypted_save``
    (test_scripts/test_secure_persistence.py) already documents as a known
    PyMuPDF 1.27.1 AES-256 quirk: calling ``tobytes(encryption=NONE)`` on the
    live handle silently poisons its internal crypt state, so a *later*
    ``encryption=KEEP`` save on that same handle produces a file that no
    longer decrypts -- even though the save reports success. Reproduced
    directly against fitz (no model involved) alongside this suite; every
    Tier 0 *attempt* on an encrypted document (not just successful commits)
    triggers it, because ``prepare()`` always builds the scratch copy before
    classification is even known. The fix belongs in engine.py: build the
    scratch copy the same way ``capture_worker_snapshot_bytes`` does --
    from an isolated clone, never ``self._doc`` directly.
    """
    pdf_path = tmp_path / "enc.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)
    doc.save(
        str(pdf_path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"), password="user-secret")
    try:
        result = _edit(model, TARGET, REPLACEMENT)
        assert result is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert REPLACEMENT in model.doc[0].get_text()  # live session still fine

        model.save_as(str(pdf_path))
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        assert reopened.needs_pass  # encryption must survive the save
        assert reopened.authenticate("user-secret") != 0
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
    finally:
        reopened.close()


def test_encrypted_full_save_back_reauthenticates_live_session(tmp_path):
    """RED -- same defect as above, via the ``secure_save_required`` atomic
    full-save chokepoint (_atomic_full_save, pdf_model.py:3114-3163) instead
    of the incremental path: the live doc handle's crypt state is poisoned by
    ``TieredCommitEngine.prepare``'s scratch copy before the save ever runs,
    so the *reopened* live session comes back unable to decrypt content
    regardless of which save chokepoint is used."""
    pdf_path = tmp_path / "enc_full.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)
    doc.save(
        str(pdf_path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"), password="user-secret")
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        model.secure_save_required = True  # force the full/atomic rewrite path
        model.save_as(str(pdf_path))

        # live session must still be able to render/extract after the
        # encrypted save-back (per _reopen_doc_after_save's contract)
        assert REPLACEMENT in model.doc[0].get_text()

        model.ensure_page_index_built(1)
        result = _edit(model, DOWNSTREAM, "Downstream line static")  # advance-neutral
        assert result is EditTextResult.SUCCESS
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        assert reopened.needs_pass
        assert reopened.authenticate("user-secret") != 0
        assert REPLACEMENT in reopened[0].get_text()
    finally:
        reopened.close()
