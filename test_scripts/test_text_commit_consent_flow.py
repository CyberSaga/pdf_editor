"""Red-light tests for Task 12 P0-C Phase 2 -- pre-commit consent for a
legacy-fidelity fallback.

Phase 1 (``test_text_commit_degrade_visibility.py``) made a
DEGRADED_COMMITTED outcome visible after the fact. Phase 2 pauses BEFORE the
legacy mutation happens: a real tiered->legacy fallback must get explicit
per-edit user consent, and a decline must leave the document, undo stack,
and edit_count byte-for-byte untouched.

Architecture (plan §8 has the full pivot record): a Qt-free callback
(``confirm_fallback: Callable[[tuple[str, ...]], bool] | None``) injected
into ``model.edit_text()``, invoked synchronously at the exact point
today's code already falls through to the legacy engine. A two-pass
Controller-side preflight was considered and rejected: it cannot see a
commit-stage-only failure (prepare succeeds on the scratch copy, live
verification then fails) in time to pause before it, because that
information does not exist until ``engine.commit()`` actually runs, and
running it during a preflight is unsafe on the success branch (double-edit
corruption).

Only ``engine="tiered"``, non-strict, cross-page-move, and the module-level
"redo must not re-prompt" tests need a real, unpatched confirm call site;
every test here supplies its own ``_confirm_legacy_fallback`` stand-in
(never a real Qt modal), so nothing hangs offscreen.

All fixtures are synthetic (data policy, plan §10).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.edit_commands import EditTextCommand  # noqa: E402
from model.edit_requests import EditTextRequest, MoveTextRequest  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica (Tier 0 fixture pair)
DOWNSTREAM = "Downstream line stays"

# Privacy sentinels (user-frozen): none of these may reach the confirm
# payload, its rendered message, or any INFO+ log record.
SENTINEL_TARGET = "SECRET_TARGET_TEXT"
SENTINEL_REPLACEMENT = "SECRET_REPLACEMENT_TEXT"
SENTINEL_BASENAME = "SECRET-customer-project"


# ---------------------------------------------------------------- fixtures


def _add_raw_page(doc: fitz.Document, stream: bytes) -> fitz.Page:
    """Append a page whose content stream is exactly ``stream`` (xref surgery)."""
    page = doc.new_page(width=595, height=842)
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


def _tier0_stream() -> bytes:
    """Single-literal-``Tj`` page: commits losslessly at Tier 0."""
    return (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )


def _tj_array_stream(target: str) -> bytes:
    """Array-``TJ`` page: structurally ineligible for Tier 0, so a non-strict
    tiered edit falls back to the legacy engine (needs consent, Phase 2)."""
    return b"BT /F1 12 Tf 72 700 Td [(" + target.encode() + b")] TJ ET"


def _write_pdf(path: Path, stream: bytes) -> Path:
    doc = fitz.open()
    _add_raw_page(doc, stream)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


class _ConfirmSpy:
    """Records every fallback-consent call and answers configurably.

    ``probe``, when set, runs at call time before the answer is returned --
    lets a test assert on document/model state AT THE MOMENT OF THE ASK,
    proving the callback fires before any mutation.
    """

    def __init__(self, answer: bool = True) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.answer = answer
        self.probe = None

    def __call__(self, chain: tuple[str, ...]) -> bool:
        self.calls.append(chain)
        if self.probe is not None:
            self.probe(chain)
        return self.answer


def _launch(
    path: Path, settings: TextCommitSettings, monkeypatch: pytest.MonkeyPatch
) -> tuple[PDFModel, PDFView, PDFController]:
    model = PDFModel(text_commit_settings=settings)
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    # Keep the harness light: rendering and tooltip refresh are not under test.
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(
        controller,
        "_invalidate_active_render_state",
        lambda *args, **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    monkeypatch.setattr(view, "capture_viewport_anchor", lambda: None)
    return model, view, controller


def _teardown(model: PDFModel, view: PDFView, qapp) -> None:
    model.close()
    view.close()
    qapp.processEvents()


def _edit_via_signal(
    model: PDFModel, view: PDFView, probe: str, new_text: str, page_num: int = 1
) -> None:
    """Drive the edit through the production wiring: the View's
    ``sig_edit_text`` signal into ``PDFController.edit_text``."""
    page_idx = page_num - 1
    model.ensure_page_index_built(page_num)
    block = next(
        b for b in model.block_manager.get_blocks(page_idx) if probe in (b.text or "")
    )
    request = EditTextRequest(
        page=page_num,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
    )
    view.sig_edit_text.emit(request)


# ---------------------------------------------------------------- tests


def test_real_tier_fallback_pauses_before_legacy_mutation(
    qapp, tmp_path, monkeypatch
):
    """RED: the confirm callback must fire BEFORE any legacy mutation -- the
    document, edit_count and last_commit_outcome are still exactly as they
    were pre-edit at the moment the callback is invoked."""
    pdf_path = _write_pdf(tmp_path / "pause.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        edit_count_before = model.edit_count

        spy = _ConfirmSpy(answer=True)

        def _probe(_chain: tuple[str, ...]) -> None:
            assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
            assert model.edit_count == edit_count_before
            assert model.last_commit_outcome is None

        spy.probe = _probe
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert model.edit_count == edit_count_before + 1
    finally:
        _teardown(model, view, qapp)


def test_cancelled_fallback_leaves_document_and_history_byte_unchanged(
    qapp, tmp_path, monkeypatch
):
    """RED: declining the confirm dialog must produce zero mutation -- no
    document bytes changed, no undo entry, no edit_count bump, no outcome."""
    pdf_path = _write_pdf(tmp_path / "cancel.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        edit_count_before = model.edit_count
        undo_count_before = model.command_manager.undo_count

        monkeypatch.setattr(
            controller, "_confirm_legacy_fallback", _ConfirmSpy(answer=False)
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert model.edit_count == edit_count_before
        assert model.command_manager.undo_count == undo_count_before
        assert model.command_manager.has_pending_changes() is False
        assert model.last_commit_outcome is None
    finally:
        _teardown(model, view, qapp)


def test_confirmed_fallback_commits_once_and_notifies_once(
    qapp, tmp_path, monkeypatch
):
    """RED: confirming commits the legacy fallback exactly once, records
    exactly one undo entry, and surfaces exactly one Phase 1 degrade notice
    (the two phases must compose, not double up)."""
    pdf_path = _write_pdf(tmp_path / "confirm.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        degrade_notices: list[str] = []
        monkeypatch.setattr(
            view,
            "notify_degraded_commit",
            lambda message: degrade_notices.append(str(message)),
            raising=False,
        )
        undo_count_before = model.command_manager.undo_count

        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        assert len(degrade_notices) == 1
        assert model.command_manager.undo_count == undo_count_before + 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    finally:
        _teardown(model, view, qapp)


def test_default_legacy_engine_never_requests_consent(qapp, tmp_path, monkeypatch):
    """PIN: under the shipped default (``engine="legacy"``) the confirm
    callback is never called -- every default-config edit proceeds exactly
    as before Phase 2 existed."""
    pdf_path = _write_pdf(tmp_path / "default.pdf", _tier0_stream())
    model, view, controller = _launch(pdf_path, TextCommitSettings(), monkeypatch)
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain == ("legacy",)
    finally:
        _teardown(model, view, qapp)


def test_normal_high_fidelity_commit_never_requests_consent(
    qapp, tmp_path, monkeypatch
):
    """PIN: a lossless Tier 0 commit never asks for consent."""
    pdf_path = _write_pdf(tmp_path / "tier0.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    finally:
        _teardown(model, view, qapp)


def test_strict_rejection_never_requests_consent(qapp, tmp_path, monkeypatch):
    """PIN: strict mode fails closed without ever asking -- REJECTED_STRICT,
    zero mutation, same as Phase 1."""
    pdf_path = _write_pdf(tmp_path / "strict.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered", strict=True), monkeypatch
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == []
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.REJECTED
    finally:
        _teardown(model, view, qapp)


def test_redo_does_not_reprompt_or_repeat_notice(qapp, tmp_path, monkeypatch):
    """RED: the user consented to THIS command's low-fidelity execution
    once; undo/redo replays that same decision, it does not ask again or
    repeat the Phase 1 degrade notice."""
    pdf_path = _write_pdf(tmp_path / "redo.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        degrade_notices: list[str] = []
        monkeypatch.setattr(
            view,
            "notify_degraded_commit",
            lambda message: degrade_notices.append(str(message)),
            raising=False,
        )
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        assert len(spy.calls) == 1
        assert len(degrade_notices) == 1

        controller.undo()
        controller.redo()

        assert len(spy.calls) == 1
        assert len(degrade_notices) == 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    finally:
        _teardown(model, view, qapp)


def test_cross_page_move_cancel_is_atomic_on_both_pages(qapp, tmp_path, monkeypatch):
    """RED: cross-page move's source deletion is the only step that can ever
    need consent (destination add_textbox never degrades) and it is always
    attempted before the destination insert -- a decline must leave BOTH
    pages, the undo stack, and edit_count untouched, and must not raise into
    the generic error handler (no restore needed; nothing changed)."""
    move_target = "PriceToken"
    doc = fitz.open()
    _add_raw_page(doc, _tj_array_stream(move_target))
    _add_raw_page(doc, _tier0_stream())
    pdf_path = tmp_path / "cross_cancel.pdf"
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        import controller.pdf_controller as controller_module

        monkeypatch.setattr(
            controller_module,
            "show_error",
            lambda parent, message: (_ for _ in ()).throw(
                AssertionError(f"unexpected show_error: {message!r}")
            ),
        )
        monkeypatch.setattr(
            controller, "_confirm_legacy_fallback", _ConfirmSpy(answer=False)
        )

        model.ensure_page_index_built(1)
        source_span = next(
            s
            for s in model.block_manager.get_spans(0)
            if move_target in (s.text or "")
        )

        fp_source_before = page_fingerprint(model.doc, model.doc[0])
        fp_dest_before = page_fingerprint(model.doc, model.doc[1])
        undo_count_before = model.command_manager.undo_count
        edit_count_before = model.edit_count

        request = MoveTextRequest(
            source_page=1,
            source_rect=fitz.Rect(source_span.bbox),
            destination_page=2,
            destination_rect=fitz.Rect(72, 500, 300, 540),
            new_text=move_target,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=source_span.text,
            target_span_id=source_span.span_id,
        )
        view.sig_move_text_across_pages.emit(request)

        assert page_fingerprint(model.doc, model.doc[0]) == fp_source_before
        assert page_fingerprint(model.doc, model.doc[1]) == fp_dest_before
        assert model.command_manager.undo_count == undo_count_before
        assert model.edit_count == edit_count_before
    finally:
        _teardown(model, view, qapp)


def test_consent_payload_contains_codes_only_no_text_filename_or_path(
    qapp, tmp_path, monkeypatch, caplog
):
    """RED: the chain handed to the confirm callback, and the message built
    from it, must carry reason codes only -- no document text, replacement
    text, filename, or path -- and neither may the surrounding INFO+ logs."""
    pdf_path = _write_pdf(
        tmp_path / f"{SENTINEL_BASENAME}.pdf", _tj_array_stream(SENTINEL_TARGET)
    )
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        with caplog.at_level(logging.INFO):
            _edit_via_signal(model, view, SENTINEL_TARGET, SENTINEL_REPLACEMENT)

        assert len(spy.calls) == 1
        chain = spy.calls[0]
        message = controller._fallback_confirmation_message(chain)

        sentinels = (
            SENTINEL_TARGET,
            SENTINEL_REPLACEMENT,
            SENTINEL_BASENAME,
            str(pdf_path),
        )
        chain_text = " ".join(chain)
        for sentinel in sentinels:
            assert sentinel not in chain_text, (
                f"sentinel {sentinel!r} leaked into consent chain {chain!r}"
            )
            assert sentinel not in message, (
                f"sentinel {sentinel!r} leaked into confirm message {message!r}"
            )
        for record in caplog.records:
            record_message = record.getMessage()
            for sentinel in sentinels:
                assert sentinel not in record_message, (
                    f"sentinel {sentinel!r} leaked into log record from "
                    f"{record.name}: {record_message!r}"
                )
    finally:
        _teardown(model, view, qapp)


def test_commit_stage_fallback_confirmation_uses_coded_chain_only(
    qapp, tmp_path, monkeypatch, caplog
):
    """RED: a COMMIT-stage failure (prepare succeeds on the scratch copy,
    live verification then fails) is exactly the case a Controller-side
    preflight cannot see -- it must still reach the confirm callback, with
    the stable reason code only, never the free-form ``detail`` string."""
    pdf_path = _write_pdf(tmp_path / "commit_fail.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        import model.text_commit.engine as engine_module
        from model.text_commit.verify import VerificationFailure

        detail_sentinel = "document no longer opens: SECRET_MUPDF_DETAIL"
        real_verify = engine_module.verify_tier0_commit

        def _fail_live_only(doc, page, prepared, pre_state):
            # prepare() proves the candidate on a SCRATCH copy with the same
            # verify function -- let that succeed so the failure genuinely
            # happens at the live COMMIT stage.
            if doc is model.doc:
                return VerificationFailure(
                    reason=RejectReason.VERIFICATION_FAILED,
                    detail=detail_sentinel,
                )
            return real_verify(doc, page, prepared, pre_state)

        monkeypatch.setattr(engine_module, "verify_tier0_commit", _fail_live_only)

        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        with caplog.at_level(logging.INFO):
            _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        chain = spy.calls[0]
        assert chain == (f"tier0:{RejectReason.VERIFICATION_FAILED}", "legacy")
        assert "SECRET_MUPDF_DETAIL" not in " ".join(chain)
        # The engine's own diagnostic warning is allowed to keep the
        # free-form detail (Phase 1 precedent) -- only controller-level
        # (confirm-chain-facing) logs must be reason-codes-only.
        for record in caplog.records:
            if record.name.startswith("controller."):
                assert "SECRET_MUPDF_DETAIL" not in record.getMessage()

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    finally:
        _teardown(model, view, qapp)


def test_real_confirm_degraded_fallback_dialog_returns_user_choice(qapp, monkeypatch):
    """RED: every other test in this file replaces
    ``controller._confirm_legacy_fallback`` before asserting -- the real,
    unmodified View-layer ``confirm_degraded_fallback`` (backed by
    ``QMessageBox.question``) never executes under test, so a mutation that
    inverts Yes/No, drops the message text, or silently no-ops would leave
    the whole suite green. This test exercises the unmodified function
    directly, with only the Qt call itself replaced (never a real modal)."""
    from PySide6.QtWidgets import QMessageBox

    from view.message_boxes import confirm_degraded_fallback

    captured: dict[str, object] = {}

    def _fake_question_yes(parent, title, text, buttons, default):
        captured["text"] = text
        captured["buttons"] = buttons
        captured["default"] = default
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fake_question_yes))
    assert confirm_degraded_fallback(None, "tier0:advance_mismatch → legacy") is True
    assert captured["text"] == "tier0:advance_mismatch → legacy"
    assert captured["default"] == QMessageBox.StandardButton.No

    def _fake_question_no(parent, title, text, buttons, default):
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fake_question_no))
    assert confirm_degraded_fallback(None, "tier0:advance_mismatch → legacy") is False


def test_high_fidelity_commit_does_not_arm_fallback_bypass_for_a_later_execute(
    tmp_path, monkeypatch
):
    """RED (adversarial verification finding, high): a command that commits
    cleanly at Tier 0 -- no fallback ever attempted, confirm_fallback never
    called -- must NOT silently disable asking on a LATER re-execution of
    the SAME command that genuinely needs a fallback. The prior flag design
    set ``_fallback_ever_confirmed = True`` on ANY successful execute(),
    conflating "this command has run once" with "the user was actually
    asked about a fallback and agreed" -- those are different things
    whenever a Tier 0/1 commit has no retained reversal patchset
    (``build_reversal_patchset`` returns ``None`` for any commit touching
    more than one content stream -- documented, not hypothetical) and a
    later redo must re-run the full pipeline from scratch against a page
    whose Tier 0 eligibility may have changed since (e.g. an out-of-band
    mutation like OCR, which bypasses command_manager entirely and so
    never clears a stale redo entry)."""
    pdf_path = _write_pdf(tmp_path / "reprompt.pdf", _tier0_stream())
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        block = next(
            b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or "")
        )
        snapshot = model._capture_page_snapshot(0)

        spy = _ConfirmSpy(answer=True)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=None,
            old_block_text=block.text,
            confirm_fallback=spy,
        )

        assert cmd.execute() is True
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert spy.calls == [], "a clean Tier 0 win must never ask"
        assert cmd._fallback_ever_confirmed is False, (
            "nothing was ever asked or agreed for this command -- the flag "
            "must not arm a future bypass"
        )

        # Simulate the reachable "no retained patchset, re-run from scratch"
        # redo path landing on a page that is no longer Tier 0-eligible for
        # this exact edit (e.g. an out-of-band mutation changed the stream
        # shape). Force classification to fail deterministically rather
        # than fabricating real PDF structure for it.
        cmd._tier0_forward_patchset = None
        cmd._tier0_active = False
        import model.text_commit.plan as plan_module
        from model.text_commit.plan import PlanRejection

        monkeypatch.setattr(
            plan_module,
            "prepare_plan",
            lambda *args, **kwargs: PlanRejection(
                RejectReason.ADVANCE_MISMATCH, "forced for test"
            ),
        )

        assert cmd.execute() is True
        assert len(spy.calls) == 1, (
            "a genuine fallback need on a LATER execute() must still ask, "
            "even though an EARLIER execute() of this same command "
            "succeeded without ever needing to"
        )
    finally:
        model.close()


def test_redo_of_an_actually_confirmed_fallback_still_does_not_reprompt(
    tmp_path, monkeypatch
):
    """PIN: the fix above must not regress the original guarantee -- once a
    real fallback WAS asked and agreed to for this command, a later
    re-execution of the identical command (the common redo case, page
    unchanged) still does not ask again."""
    pdf_path = _write_pdf(tmp_path / "repin.pdf", _tj_array_stream(TARGET))
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        block = next(
            b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or "")
        )
        snapshot = model._capture_page_snapshot(0)

        spy = _ConfirmSpy(answer=True)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=None,
            old_block_text=block.text,
            confirm_fallback=spy,
        )

        assert cmd.execute() is True
        assert cmd.outcome is not None
        assert cmd.outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert len(spy.calls) == 1
        assert cmd._fallback_ever_confirmed is True

        # No retained patchset for a legacy-tier commit -- execute() again
        # re-runs the full pipeline (this is the actual redo path for a
        # legacy-tier command; nothing forced here).
        assert cmd._tier0_forward_patchset is None
        assert cmd.execute() is True
        assert len(spy.calls) == 1, "must not re-ask for the same confirmed decision"
    finally:
        model.close()
