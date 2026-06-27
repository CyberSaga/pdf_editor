"""Auto-repair of a damaged XREF table when a PDF is opened.

Mission: 開檔自動修復 XREF 表. PyMuPDF rebuilds a broken cross-reference table when
it opens a damaged PDF (``doc.is_repaired``). On open the editor round-trips that
document in memory so the active document carries a clean, internally-consistent
xref; healthy files are left untouched (still file-backed, no needless rewrite).
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_model import PDFModel  # noqa: E402


def _valid_pdf_bytes() -> bytes:
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 60), f"xref-repair-page-{i}", fontsize=14, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def _corrupt_startxref(data: bytes) -> bytes:
    # Point the final startxref offset at a bogus location so the xref table
    # cannot be read there and MuPDF must rebuild it on open.
    return re.sub(rb"startxref\s+\d+", b"startxref\n9999999", data, count=1)


def _encrypted_pdf_bytes(*, user_pw: str, owner_pw: str = "owner-secret") -> bytes:
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 60), f"secret-page-{i}", fontsize=14, fontname="helv")
    data = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=owner_pw, user_pw=user_pw
    )
    doc.close()
    return data


def _is_encrypted(doc: fitz.Document) -> bool:
    return bool((doc.metadata or {}).get("encryption"))


def _assert_live_doc_encrypted_and_usable(
    model: PDFModel, *, context: str, canary: str = "secret-page-0"
) -> None:
    """The live doc kept its encryption (in memory) and is still authenticated +
    readable after ``context`` (e.g. "periodic GC"). ``is_encrypted`` flips to
    False once the round-tripped handle is re-authenticated, which is the
    live-usable signal."""
    assert _is_encrypted(model.doc), (
        f"{context} silently stripped encryption from the live document"
    )
    assert not model.doc.is_encrypted  # re-authenticated, still usable
    assert canary in model.doc[0].get_text("text")


def _assert_disk_pdf_keeps_password(
    path: str,
    *,
    needs_pass_msg: str,
    pw: str = "user-pw",
    canary: str = "secret-page-0",
    expect_repaired: bool | None = None,
) -> None:
    """Reopen a saved file from disk and assert the password survived: it still
    needs a password, accepts the original one, content is intact, and
    (optionally) the xref was rewritten clean (``expect_repaired``)."""
    reopened = fitz.open(str(path))
    try:
        assert reopened.needs_pass, needs_pass_msg
        assert reopened.authenticate(pw) in (2, 4, 6), (
            "saved file no longer accepts the original password"
        )
        if expect_repaired is not None:
            assert bool(getattr(reopened, "is_repaired", False)) is expect_repaired
        assert canary in reopened[0].get_text("text")
    finally:
        reopened.close()


def test_open_damaged_pdf_auto_repairs_in_memory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken.pdf"
        broken.write_bytes(_corrupt_startxref(_valid_pdf_bytes()))

        # Sanity: the corrupted file must actually trigger MuPDF's repair path.
        probe = fitz.open(str(broken))
        assert bool(getattr(probe, "is_repaired", False)) is True, (
            "test fixture did not produce a repairable xref"
        )
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(broken))

            # The active document must have been repaired in memory: a clean
            # xref (not flagged as repaired) and a memory-backed handle (the
            # round-trip drops the original file name).
            assert model.doc is not None
            assert bool(getattr(model.doc, "is_repaired", False)) is False, (
                "damaged document was not auto-repaired on open"
            )
            # Memory-backed (round-tripped) handle, not the original damaged
            # file. PyMuPDF reports a stream doc's name as "" (<=1.25) or the
            # filetype "pdf" (1.27+, from fitz.open("pdf", bytes)); both prove the
            # round-trip produced a fresh in-memory doc. The is_repaired==False
            # check above already proves the xref was rebuilt; this guards that
            # the handle is no longer bound to the on-disk damaged file.
            assert model.doc.name in ("", "pdf"), (
                "repaired document should be memory-backed (round-tripped); got "
                f"name {model.doc.name!r}"
            )

            # Content and structure are preserved through the repair.
            assert model.doc.page_count == 2
            assert "xref-repair-page-0" in model.doc[0].get_text("text")
        finally:
            model.close()


def test_open_damaged_encrypted_pdf_keeps_encryption() -> None:
    # Regression guard: auto-repair must NOT strip encryption. Round-tripping an
    # authenticated encrypted doc through tobytes() emits a *decrypted* PDF, so a
    # later save-back would silently drop the password. A damaged+encrypted file
    # must skip the in-memory round-trip and stay encrypted (MuPDF's repaired doc
    # is still usable; a later full save with encryption=KEEP preserves it).
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken-encrypted.pdf"
        broken.write_bytes(_corrupt_startxref(_encrypted_pdf_bytes(user_pw="user-pw")))

        # Sanity: the fixture is both encrypted and triggers MuPDF's repair path.
        probe = fitz.open(str(broken))
        assert probe.needs_pass  # int 1 from PyMuPDF
        assert bool(getattr(probe, "is_repaired", False)) is True, (
            "test fixture did not produce a repairable xref"
        )
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(broken), password="user-pw")

            assert model.doc is not None
            # Encryption must survive the open (in-memory half of the guarantee).
            assert _is_encrypted(model.doc), (
                "auto-repair stripped encryption from a damaged encrypted PDF"
            )
            # Encrypted docs skip the in-memory round-trip, so the handle stays
            # file-backed; a later full save (encryption=KEEP) keeps the password.
            assert model.doc.name != "", (
                "encrypted document must not be round-tripped to a memory handle"
            )
            assert model.doc.page_count == 2
            assert "secret-page-0" in model.doc[0].get_text("text")

            # The real, end-to-end guarantee: saving back to disk must NOT strip
            # the password. A repaired doc full-rewrites (no incremental save), so
            # the full-save path must pass encryption=KEEP.
            model.save_as(str(broken))

            # ...and the LIVE editing session must survive that save. Preserving
            # encryption means the reopen-after-save handle is locked until it is
            # re-authenticated with the session password; without that, the
            # in-editor document goes dead (no render/extract/edit).
            #
            # NB: needs_pass stays 1 on an encrypted file even after a successful
            # authenticate() — it reports "this file has a password", not "locked
            # right now". The live-authenticated signal is is_encrypted flipping
            # to False; the real guarantee is that content is readable again.
            assert not model.doc.is_encrypted, (
                "live document not re-authenticated after encrypted save-back"
            )
            assert "secret-page-0" in model.doc[0].get_text("text"), (
                "live document unusable after encrypted save-back"
            )
        finally:
            model.close()

        # Password survived the save-back, and the rewrite produced a clean xref.
        _assert_disk_pdf_keeps_password(
            str(broken),
            needs_pass_msg="save-back stripped the user password",
            expect_repaired=False,
        )


def test_open_damaged_owner_only_pdf_keeps_encryption() -> None:
    # Owner-password-only PDFs open without a password (needs_pass / is_encrypted
    # are both False), so the flag-based checks miss them; only the metadata
    # encryption string survives. The round-trip would still strip the owner
    # restrictions, so this case must also be skipped.
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken-owner-only.pdf"
        broken.write_bytes(_corrupt_startxref(_encrypted_pdf_bytes(user_pw="")))

        probe = fitz.open(str(broken))
        assert not probe.needs_pass  # empty user password → opens freely
        assert bool(getattr(probe, "is_repaired", False)) is True
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(broken))

            assert model.doc is not None
            assert _is_encrypted(model.doc), (
                "auto-repair stripped owner-only encryption from a damaged PDF"
            )
            assert model.doc.name != "", (
                "owner-encrypted document must not be round-tripped to memory"
            )
            assert model.doc.page_count == 2

            # Save-back must preserve the owner encryption (no password to enter,
            # but the encryption dict / restrictions must survive the rewrite).
            model.save_as(str(broken))

            # Owner-only PDFs reopen without a password, so the live session
            # stays usable — assert it explicitly so this path is covered too.
            assert model.doc.page_count == 2
            assert model.doc[0].get_text("text") is not None
        finally:
            model.close()

        reopened = fitz.open(str(broken))
        try:
            assert _is_encrypted(reopened), (
                "save-back stripped owner-only encryption"
            )
            assert bool(getattr(reopened, "is_repaired", False)) is False
        finally:
            reopened.close()


def test_encrypted_doc_survives_periodic_light_cleanup() -> None:
    # Periodic edit maintenance is page-local only; secure full GC now belongs at
    # persistence.  The maintenance pass must leave the authenticated handle intact.
    with tempfile.TemporaryDirectory() as tmp:
        enc = Path(tmp) / "enc.pdf"
        enc.write_bytes(_encrypted_pdf_bytes(user_pw="user-pw"))

        model = PDFModel()
        try:
            model.open_pdf(str(enc), password="user-pw")
            assert _is_encrypted(model.doc)

            model.edit_count = 20
            model._maybe_garbage_collect()

            _assert_live_doc_encrypted_and_usable(model, context="periodic cleanup")
        finally:
            model.close()


def test_encrypted_doc_survives_in_memory_repair() -> None:
    # _repair_active_doc_in_memory is an error-recovery fallback (failed textbox
    # edit / snapshot capture on a damaged doc). It round-trips the live doc
    # through tobytes() and must preserve encryption like the GC path, or an
    # encrypted+damaged doc loses its password on the next save during recovery.
    with tempfile.TemporaryDirectory() as tmp:
        enc = Path(tmp) / "enc.pdf"
        enc.write_bytes(_encrypted_pdf_bytes(user_pw="user-pw"))

        model = PDFModel()
        try:
            model.open_pdf(str(enc), password="user-pw")
            assert _is_encrypted(model.doc)

            assert model._repair_active_doc_in_memory() is True
            _assert_live_doc_encrypted_and_usable(model, context="in-memory repair")
        finally:
            model.close()


def test_encrypted_doc_survives_doc_level_snapshot_restore() -> None:
    # Doc-level snapshots (_capture_doc_snapshot / _restore_doc_from_snapshot) back
    # the undo/redo of structural ops. Restore *replaces* self.doc with
    # fitz.open(snapshot_bytes); if the snapshot was captured decrypted (save
    # defaults to encryption=NONE) the live doc becomes decrypted after an undo,
    # dropping the password on the next save. The capture must serialize with
    # encryption=KEEP and the restore must re-authenticate the reopened handle.
    # (Page-level snapshots mutate the still-encrypted live doc in place and are
    # tracked separately — they do not replace the live handle.)
    with tempfile.TemporaryDirectory() as tmp:
        enc = Path(tmp) / "enc.pdf"
        enc.write_bytes(_encrypted_pdf_bytes(user_pw="user-pw"))

        model = PDFModel()
        try:
            model.open_pdf(str(enc), password="user-pw")
            assert _is_encrypted(model.doc)

            # Simulate a SnapshotCommand undo: capture the whole doc, then restore.
            snapshot = model._capture_doc_snapshot()
            model.replace_active_document_from_snapshot(snapshot, affected_pages=[1])

            _assert_live_doc_encrypted_and_usable(
                model, context="doc-level snapshot restore"
            )

            # End-to-end: a save after the undo must keep the password.
            model.save_as(str(enc))
        finally:
            model.close()

        _assert_disk_pdf_keeps_password(
            str(enc),
            needs_pass_msg="save after a doc-level undo stripped the password",
        )


def test_live_doc_roundtrips_preserve_encryption() -> None:
    """Structural guard (generalized in R2.2 to all of ``model/``): every
    serialization of the **live** document must pass ``encryption=`` (KEEP).
    ``tobytes`` and ``save`` both default to ``encryption=NONE``, which silently
    decrypts — ``tobytes`` strips the password in memory; an incremental ``save``
    with the default even *raises* ("Can't do incremental writes when changing
    encryption"), degrading every encrypted save-back to a full rewrite. Live-doc
    round-trips funnel through ``_roundtrip_live_doc`` / ``_save_doc`` (both inject
    ``encryption=KEEP``); this AST scan is the backstop that catches the next
    *direct* live-doc serialization bypassing those funnels.

    R2.2 widened the scan from ``pdf_model.py`` alone to **every** ``model/``
    module and from the ``self.doc`` receiver to all three live-doc access
    patterns — ``self.doc``, ``model.doc`` (free-function modules taking
    ``model: PDFModel``), and ``self._model.doc`` (ToolManager) — so the guard
    does not go blind when ``edit_text``/object-ops leave ``pdf_model.py`` in R3.
    Generic receivers (``tmp_doc``/``new_doc``/``working_doc``/a bare ``doc``
    parameter) serialize *non-live* copies and are not checked.

    Decrypt-sink allowlist — the only live-doc serializations permitted without
    ``encryption=KEEP`` (each a deliberate, reviewed exception):
      - ``pdf_model.capture_worker_snapshot_bytes`` — explicit ``PDF_ENCRYPT_NONE``,
        an in-memory worker snapshot that never replaces the live handle.
      - ``pdf_optimizer.current_document_size_bytes`` — ``len(...tobytes())``; the
        bytes are measured then discarded.
      - ``pdf_optimizer.build_working_doc_for_optimized_copy`` — builds the
        optimize working copy. **KNOWN GAP (tracked for R5):** for an *encrypted*
        source this decrypts the live doc into the optimized copy (另存為最佳化的
        副本 strips the password). Allowlisted so the guard is green; the fix is a
        product decision (refuse vs preserve-encryption).

    Strengthening (R2.2): an explicit ``encryption=PDF_ENCRYPT_NONE`` on a live-doc
    serialization is allowed only on the allowlist — presence of an ``encryption=``
    keyword is not by itself sufficient.
    """
    import ast

    live_receivers = {"self.doc", "model.doc", "self._model.doc"}
    allowlist = {
        ("pdf_model.py", "capture_worker_snapshot_bytes"),
        # External print handoff is deliberately decrypted in memory because
        # the print worker re-applies source encryption before writing its
        # helper input.  Unlike the generic snapshot, this path uses garbage=4
        # whenever destructive edits have latched secure persistence.
        ("pdf_model.py", "capture_print_snapshot_bytes"),
        ("pdf_optimizer.py", "current_document_size_bytes"),
        ("pdf_optimizer.py", "build_working_doc_for_optimized_copy"),
    }

    def _receiver_str(node: ast.AST) -> str:
        parts: list[str] = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        parts.append(cur.id if isinstance(cur, ast.Name) else "?")
        return ".".join(reversed(parts))

    def _is_encrypt_none(node: ast.AST) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "PDF_ENCRYPT_NONE") or (
            isinstance(node, ast.Name) and node.id == "PDF_ENCRYPT_NONE"
        )

    offenders: list[str] = []

    class _LiveDocVisitor(ast.NodeVisitor):
        def __init__(self, rel: str) -> None:
            self.rel = rel
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr in {"tobytes", "save"}
                and _receiver_str(f.value) in live_receivers
            ):
                func = self.stack[-1] if self.stack else "<module>"
                if (self.rel, func) not in allowlist:
                    enc = next((k for k in node.keywords if k.arg == "encryption"), None)
                    if enc is None or _is_encrypt_none(enc.value):
                        why = "missing encryption=" if enc is None else "explicit PDF_ENCRYPT_NONE"
                        offenders.append(
                            f"{self.rel}:{node.lineno} {_receiver_str(f.value)}.{f.attr}() "
                            f"{why} (in {func})"
                        )
            self.generic_visit(node)

    model_root = REPO_ROOT / "model"
    for path in sorted(model_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(model_root).as_posix()
        # utf-8-sig: some modules carry a UTF-8 BOM; plain utf-8 would leave a
        # U+FEFF that makes ast.parse raise instead of scanning.
        _LiveDocVisitor(rel).visit(ast.parse(path.read_text(encoding="utf-8-sig")))

    assert not offenders, (
        "Live-doc serialization that may silently decrypt the active document — "
        "pass encryption=fitz.PDF_ENCRYPT_KEEP, route through _roundtrip_live_doc/"
        "_save_doc, or add a reviewed decrypt-sink allowlist entry. Offenders: "
        f"{offenders}"
    )


def test_healthy_encrypted_save_back_uses_incremental_and_keeps_password() -> None:
    # The common real-world path the encryption=KEEP sweep originally missed:
    # open a *healthy* (undamaged) encrypted PDF, edit nothing, save back to the
    # same path. can_save_incrementally() is True, so save_as takes the
    # incremental branch — which must pass encryption=KEEP. Without it PyMuPDF
    # raises "Can't do incremental writes when changing encryption" (default
    # encryption=NONE), the editor catches it and falls back to a full rewrite
    # (slow + a misleading WARNING on every encrypted save), even though the
    # password still survives via that fallback. This test asserts the incremental
    # path actually succeeds (no fallback) AND the password survives end-to-end.
    with tempfile.TemporaryDirectory() as tmp:
        enc = Path(tmp) / "enc.pdf"
        enc.write_bytes(_encrypted_pdf_bytes(user_pw="user-pw"))

        model = PDFModel()
        try:
            model.open_pdf(str(enc), password="user-pw")
            assert _is_encrypted(model.doc)
            # Precondition: this file CAN save incrementally, so the branch under
            # test is exercised rather than skipped.
            assert model.doc.can_save_incrementally(), (
                "fixture cannot save incrementally; test would not cover the branch"
            )

            # Spy: a true incremental save must NOT fall back to a full rewrite.
            fell_back: list[str] = []
            original_full_save = model._full_save_to_path

            def _spy(path: str):
                fell_back.append(path)
                return original_full_save(path)

            model._full_save_to_path = _spy  # type: ignore[method-assign]

            model.save_as(str(enc))

            assert fell_back == [], (
                "healthy encrypted save-back fell back to a full rewrite instead "
                "of a true incremental save (incremental branch missing "
                "encryption=KEEP)"
            )
            # Live session stays usable; incremental keeps the same authenticated
            # handle (no close/reopen), so is_encrypted stays False.
            assert not model.doc.is_encrypted, (
                "live document unusable after incremental encrypted save-back"
            )
            assert "secret-page-0" in model.doc[0].get_text("text")
        finally:
            model.close()

        # On-disk: the password survived the incremental save-back.
        _assert_disk_pdf_keeps_password(
            str(enc),
            needs_pass_msg="incremental save-back stripped the password",
        )


def test_open_healthy_pdf_is_left_file_backed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        healthy = Path(tmp) / "healthy.pdf"
        healthy.write_bytes(_valid_pdf_bytes())

        # Sanity: a clean file does not trigger MuPDF's repair path.
        probe = fitz.open(str(healthy))
        assert bool(getattr(probe, "is_repaired", False)) is False
        probe.close()

        model = PDFModel()
        try:
            model.open_pdf(str(healthy))

            # A healthy file must NOT be round-tripped: it stays file-backed so
            # incremental save-to-original keeps working and open stays cheap.
            assert model.doc is not None
            assert bool(getattr(model.doc, "is_repaired", False)) is False
            assert Path(model.doc.name).resolve() == healthy.resolve(), (
                "healthy document should remain file-backed (no needless rewrite)"
            )
            assert model.doc.page_count == 2
        finally:
            model.close()
