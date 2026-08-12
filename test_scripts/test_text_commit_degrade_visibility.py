"""Red-light tests for Task 12 P0-C Phase 1 — degrade visibility in the GUI.

Today a non-strict legacy fallback commit is recorded honestly in the Model
(``CommitStatus.DEGRADED_COMMITTED`` + ``fallback_chain`` on
``model.last_commit_outcome`` / ``EditTextCommand.outcome``) but the GUI
presents it as ordinary success — the Controller never reads the outcome.
These tests pin the Phase 1 contract:

1. A degraded commit surfaces exactly ONE user-visible degrade signal
   (not duplicated across toast / status bar / any other channel).
2. The P0-A resource-guard refusal reason
   ``content_stream_too_large_for_safe_replay`` survives VERBATIM into that
   signal (frozen invariant: never collapsed into ``no_source_match`` /
   ``malformed_stream`` / ``target_reconstruction_unverified``).
3. A normal high-fidelity (Tier 0) commit shows no degrade signal.
4. A strict-mode rejection shows no degrade signal (it is not a commit).
5. The signal's payload and the surrounding INFO+ log records never contain
   document text, replacement text, the filename, or any filesystem path.

Red/pin split (CLAUDE.md §5.1): tests 1, 2 and 5 are the true reds — they
fail until the Controller surfaces the outcome. Tests 3 and 4 are
negative-control pins expected to PASS at Red and are marked inline; they
exist so the green implementation cannot over-notify.

The degrade signal is identified in captured payloads by the reason-chain
marker ``"legacy"`` (every degrade chain ends in the ``legacy`` engine; no
other GUI message on these paths contains that token).

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
from model.edit_commands import EditTextResult  # noqa: E402
from model.edit_requests import EditTextRequest  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from model.text_commit.replay import DEFAULT_MAX_REPLAY_BYTES  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica (Tier 0 fixture pair)
DOWNSTREAM = "Downstream line stays"

# Deliberate literal (not the enum): pins the on-the-wire value end to end.
GUARD_REASON = "content_stream_too_large_for_safe_replay"
# Reasons the frozen invariant forbids the guard refusal to collapse into.
FORBIDDEN_REWRITES = (
    "no_source_match",
    "malformed_stream",
    "verification_failed",
    "target_reconstruction_unverified",
)

# Privacy sentinels (user-frozen): none of these may reach any GUI payload,
# log record, or telemetry line. The path sentinel is exercised through the
# real opened file's name/path, not by writing to C:\private.
SENTINEL_TARGET = "SECRET_TARGET_TEXT"
SENTINEL_REPLACEMENT = "SECRET_REPLACEMENT_TEXT"
SENTINEL_BASENAME = "SECRET-customer-project"

_PATH_CHUNK = b"10 20 m 30 40 l 50 60 70 80 90 100 c S\n"


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
    tiered edit falls back to the legacy engine (degraded commit)."""
    return b"BT /F1 12 Tf 72 700 Td [(" + target.encode() + b")] TJ ET"


def _oversized_stream() -> bytes:
    """Editable text plus vector junk pushing the decoded size over the
    P0-A replay budget: the tiered attempt must refuse with GUARD_REASON."""
    target_bytes = DEFAULT_MAX_REPLAY_BYTES + 65536
    chunks = [b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET\n"]
    junk_repeats = (target_bytes - len(chunks[0])) // len(_PATH_CHUNK) + 1
    chunks.append(_PATH_CHUNK * junk_repeats)
    stream = b"".join(chunks)
    assert len(stream) > DEFAULT_MAX_REPLAY_BYTES
    return stream


def _write_pdf(path: Path, stream: bytes) -> Path:
    doc = fitz.open()
    _add_raw_page(doc, stream)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


# ---------------------------------------------------------------- harness


class _ViewSpy:
    """Records every user-visible payload the Controller pushes at the View."""

    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []  # (message, tone)
        self.status_messages: list[str] = []
        self.degrade_notices: list[str] = []

    def all_payloads(self) -> list[str]:
        return (
            list(self.degrade_notices)
            + [message for message, _tone in self.toasts]
            + list(self.status_messages)
        )

    def degrade_payloads(self) -> list[str]:
        """Every payload carrying the degrade reason-chain marker, across
        ALL channels — the exactly-once assertion counts these."""
        return [m for m in self.all_payloads() if "legacy" in m]


def _spy_view(view: PDFView, monkeypatch: pytest.MonkeyPatch) -> _ViewSpy:
    spy = _ViewSpy()
    monkeypatch.setattr(
        view,
        "_show_toast",
        lambda message, duration_ms=1500, tone="success": spy.toasts.append(
            (str(message), str(tone))
        ),
    )
    monkeypatch.setattr(
        view,
        "set_status_bar_override_message",
        lambda message: spy.status_messages.append(str(message))
        if message
        else None,
    )
    # Does not exist at Red — the recorder stands in for the Phase 1 API so
    # the count is 0 until the Controller actually calls it.
    monkeypatch.setattr(
        view,
        "notify_degraded_commit",
        lambda message: spy.degrade_notices.append(str(message)),
        raising=False,
    )
    return spy


def _launch(
    path: Path, settings: TextCommitSettings, monkeypatch: pytest.MonkeyPatch
) -> tuple[PDFModel, PDFView, PDFController]:
    model = PDFModel(text_commit_settings=settings)
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    # Task 12 P0-C phase 2: every test in this file predates the consent
    # gate and asserts on what happens AFTER a degraded commit -- auto-
    # confirm by default so a real (Qt modal) confirm call never blocks an
    # offscreen test run. Phase 2's own test file exercises decline/pause.
    monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda chain: True)
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


class _FakeCommittedFinalizeResult:
    """Stands in for a real inline-editor finalize result reporting
    COMMITTED, independent of what the Controller's edit actually did --
    the real commit (if any) happens separately via ``_edit_via_signal``;
    this only satisfies ``set_mode()``'s outer
    ``result.outcome == TextEditOutcome.COMMITTED`` gate, so what actually
    determines whether the toast fires is the REAL, unmocked
    ``consume_last_edit_result()`` / ``consume_last_edit_degraded()`` pull
    downstream (Task 12 P0-C phase 2 verification: ``TextEditOutcome.
    COMMITTED`` means only "the finalize signal emitted without raising",
    never "the Controller's edit actually succeeded")."""

    from view.text_editing import TextEditOutcome as _Outcome

    outcome = _Outcome.COMMITTED


class _FakeInlineEditorWidget:
    def widget(self):
        return None


# ---------------------------------------------------------------- tests


def test_non_strict_legacy_fallback_surfaces_degraded_status_once(
    qapp, tmp_path, monkeypatch
):
    """RED: the Model records DEGRADED_COMMITTED with a tier0→legacy chain,
    and the GUI must surface exactly ONE degrade signal for it."""
    pdf_path = _write_pdf(tmp_path / "tj_array.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None, "edit did not reach a commit outcome"
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain[-1] == "legacy"
        assert outcome.fallback_chain[0].startswith("tier0:")

        payloads = spy.degrade_payloads()
        assert len(payloads) == 1, (
            f"expected exactly one degrade signal, got {len(payloads)}: "
            f"{payloads!r} (all payloads: {spy.all_payloads()!r})"
        )
        notice = payloads[0]
        assert "tier0:" in notice
        assert "legacy" in notice
        # The plain-success toast must not accompany a degraded commit.
        assert all("文字已儲存" not in message for message, _tone in spy.toasts)
    finally:
        _teardown(model, view, qapp)


def test_resource_guard_fallback_surfaces_exact_refusal_reason(
    qapp, tmp_path, monkeypatch
):
    """RED: the P0-A refusal reason must reach the user VERBATIM.

    Model-level propagation is already pinned (P0-A); this test extends the
    frozen invariant one hop further: PlanRejection → fallback_chain → the
    user-visible degrade payload, with none of the forbidden rewrites."""
    pdf_path = _write_pdf(tmp_path / "oversized.pdf", _oversized_stream())
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain == (f"tier0:{GUARD_REASON}", "legacy")

        payloads = spy.degrade_payloads()
        assert len(payloads) == 1, (
            f"expected exactly one degrade signal, got {len(payloads)}: "
            f"{payloads!r}"
        )
        notice = payloads[0]
        assert GUARD_REASON in notice, (
            f"refusal reason not surfaced verbatim; payload: {notice!r}"
        )
        for rewritten in FORBIDDEN_REWRITES:
            assert rewritten not in notice
    finally:
        _teardown(model, view, qapp)


def test_normal_high_fidelity_commit_does_not_surface_degraded_status(
    qapp, tmp_path, monkeypatch
):
    """Negative-control pin (expected to PASS at Red): a lossless Tier 0
    commit is ordinary success — no degrade signal on any channel."""
    pdf_path = _write_pdf(tmp_path / "tier0.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        assert spy.degrade_payloads() == []
        assert spy.degrade_notices == []
    finally:
        _teardown(model, view, qapp)


def test_strict_rejection_does_not_surface_degraded_commit(
    qapp, tmp_path, monkeypatch
):
    """Negative-control pin (expected to PASS at Red): strict mode fails
    closed — REJECTED_STRICT feedback, zero mutation, and no degrade signal
    (nothing was committed, so nothing may claim to be)."""
    pdf_path = _write_pdf(tmp_path / "strict.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered", strict=True), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.REJECTED

        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert spy.degrade_payloads() == []
        assert spy.degrade_notices == []
        # The existing strict feedback stays: exactly one error-tone message.
        strict_messages = [
            message for message, tone in spy.toasts if "嚴格模式" in message
        ]
        assert len(strict_messages) == 1
    finally:
        _teardown(model, view, qapp)


def test_degraded_notice_payload_excludes_text_filename_and_path(
    qapp, tmp_path, monkeypatch, caplog
):
    """RED: the degrade signal must exist (count == 1) AND carry reason codes
    only — no document text, no replacement text, no filename, no path — and
    the INFO+ log records emitted during the edit obey the same contract."""
    pdf_path = _write_pdf(
        tmp_path / f"{SENTINEL_BASENAME}.pdf", _tj_array_stream(SENTINEL_TARGET)
    )
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        with caplog.at_level(logging.INFO):
            _edit_via_signal(model, view, SENTINEL_TARGET, SENTINEL_REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED

        payloads = spy.degrade_payloads()
        assert len(payloads) == 1, (
            f"expected exactly one degrade signal, got {len(payloads)}: "
            f"{payloads!r}"
        )

        sentinels = (
            SENTINEL_TARGET,
            SENTINEL_REPLACEMENT,
            SENTINEL_BASENAME,
            str(pdf_path),
        )
        for payload in spy.all_payloads():
            for sentinel in sentinels:
                assert sentinel not in payload, (
                    f"sentinel {sentinel!r} leaked into GUI payload {payload!r}"
                )
        for record in caplog.records:
            message = record.getMessage()
            for sentinel in sentinels:
                assert sentinel not in message, (
                    f"sentinel {sentinel!r} leaked into log record from "
                    f"{record.name}: {message!r}"
                )
    finally:
        _teardown(model, view, qapp)


def test_commit_stage_failure_surfaces_stable_code_not_detail(
    qapp, tmp_path, monkeypatch, caplog
):
    """RED (verification F2): a COMMIT-stage failure (after a successful
    prepare) carries a free-form ``detail`` string — raw exception text,
    pixel coordinates, resource names. The fallback chain, the GUI payload
    and the controller's notice log must carry the STABLE reason code, never
    the detail (the engine's own diagnostic warning may keep it)."""
    pdf_path = _write_pdf(tmp_path / "commit_fail.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)

        import model.text_commit.engine as engine_module
        from model.text_commit.verify import VerificationFailure

        detail_sentinel = "document no longer opens: SECRET_MUPDF_DETAIL"
        real_verify = engine_module.verify_tier0_commit

        def _fail_live_only(doc, page, prepared, pre_state):
            # prepare() proves the candidate on a SCRATCH copy with the same
            # verify function — let that succeed so the failure genuinely
            # happens at the live COMMIT stage (the free-form-detail path).
            if doc is model.doc:
                return VerificationFailure(
                    reason=RejectReason.VERIFICATION_FAILED,
                    detail=detail_sentinel,
                )
            return real_verify(doc, page, prepared, pre_state)

        monkeypatch.setattr(
            engine_module, "verify_tier0_commit", _fail_live_only
        )
        with caplog.at_level(logging.INFO):
            _edit_via_signal(model, view, TARGET, REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain == (
            f"tier0:{RejectReason.VERIFICATION_FAILED}",
            "legacy",
        )

        payloads = spy.degrade_payloads()
        assert len(payloads) == 1
        assert RejectReason.VERIFICATION_FAILED in payloads[0]
        for payload in spy.all_payloads():
            assert "SECRET_MUPDF_DETAIL" not in payload, (
                f"free-form commit-failure detail leaked into GUI payload: "
                f"{payload!r}"
            )
        for record in caplog.records:
            if record.name.startswith("controller."):
                assert "SECRET_MUPDF_DETAIL" not in record.getMessage()
    finally:
        _teardown(model, view, qapp)


def test_real_view_notify_degraded_commit_fires_one_warning_toast(qapp):
    """RED (verification F6): every other test in this file monkeypatches
    away ``PDFView.notify_degraded_commit`` / ``_show_toast`` before
    asserting — the REAL production View method never executes under test,
    so a mutation that double-toasts, drops the warning tone, or silently
    deletes the method entirely would leave the whole suite green. This
    test exercises the unmodified View method directly."""
    from PySide6.QtWidgets import QLabel

    view = PDFView(defer_heavy_panels=True)
    try:
        created: list[QLabel] = []
        original_new = QLabel.__init__

        def _tracking_init(self, *args, **kwargs):
            original_new(self, *args, **kwargs)
            created.append(self)

        import unittest.mock as mock

        with mock.patch.object(QLabel, "__init__", _tracking_init):
            view.notify_degraded_commit("tier0:not_single_literal_tj → legacy")

        assert len(created) == 1, (
            f"expected exactly one toast QLabel, got {len(created)}"
        )
        toast = created[0]
        assert toast.text() == "tier0:not_single_literal_tj → legacy"
        style = toast.styleSheet()
        assert "180,40,40" not in style  # not the error-tone background
        assert "40,40,40" not in style  # not the success-tone background
    finally:
        view.close()
        qapp.processEvents()


def test_default_legacy_engine_shows_no_degrade_notice(
    qapp, tmp_path, monkeypatch
):
    """RED (verification F1): under shipped defaults (``engine="legacy"``)
    EVERY successful edit is recorded DEGRADED_COMMITTED with chain
    ``("legacy",)`` — that is today's baseline behavior, not a failed
    high-fidelity attempt. Surfacing it would turn every default-config edit
    into a warning and permanently suppress the success toast before rollout
    ever flips the default ("Defaults untouched — acceptance, not rollout").
    The notice fires only for a fallback FROM an attempted higher tier."""
    pdf_path = _write_pdf(tmp_path / "default_legacy.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain == ("legacy",)

        assert spy.degrade_payloads() == []
        assert spy.degrade_notices == []
        # The success toast path must stay intact for default-config edits.
        assert controller.consume_last_edit_degraded() is False
    finally:
        _teardown(model, view, qapp)


def test_cross_page_move_surfaces_source_degrade(qapp, tmp_path, monkeypatch):
    """RED (verification F4): a cross-page move deletes the source text via
    ``model.edit_text`` directly, bypassing ``controller.edit_text`` — under
    the tiered engine that deletion falls back to legacy (degraded commit)
    and today produces ZERO degrade signals, violating the exactly-once
    invariant (zero is not one)."""
    # A single-token target (no internal space) lands in exactly one
    # `EditableSpan` -- `block_manager` tokenizes runs at word boundaries --
    # so its span id can be supplied directly, bypassing an unrelated
    # pre-existing gap in the ambiguous-candidate ranking path
    # (`PDFModel._normalize_text_for_compare` does not exist; out of scope
    # for this P0-C notice-surfacing fix).
    move_target = "PriceToken"
    doc = fitz.open()
    _add_raw_page(doc, _tj_array_stream(move_target))
    _add_raw_page(doc, _tier0_stream())
    pdf_path = tmp_path / "cross_move.pdf"
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        # Guard against a genuine defect in this same code path turning a
        # test failure into a hung modal dialog (QMessageBox.critical blocks
        # the event loop with no user present in an offscreen test run).
        import controller.pdf_controller as controller_module

        monkeypatch.setattr(
            controller_module,
            "show_error",
            lambda parent, message: (_ for _ in ()).throw(
                AssertionError(f"unexpected show_error: {message!r}")
            ),
        )
        model.ensure_page_index_built(1)
        source_span = next(
            s
            for s in model.block_manager.get_spans(0)
            if move_target in (s.text or "")
        )
        from model.edit_requests import MoveTextRequest

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

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED

        payloads = spy.degrade_payloads()
        assert len(payloads) == 1, (
            f"expected exactly one degrade signal for the move's source "
            f"deletion, got {len(payloads)}: {payloads!r}"
        )
        assert "tier0:" in payloads[0]
        # The move counts as the latest edit for toast suppression too.
        assert controller.consume_last_edit_degraded() is True
    finally:
        _teardown(model, view, qapp)


def test_stale_degrade_flag_does_not_survive_add_textbox(
    qapp, tmp_path, monkeypatch
):
    """RED (verification F5): an unconsumed degraded flag from an earlier
    edit must not outlive a later ADD-TEXTBOX commit (which bypasses
    controller.edit_text) — otherwise the add's mode-switch success toast
    is wrongly suppressed."""
    pdf_path = _write_pdf(tmp_path / "flag_add.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        _spy_view(view, monkeypatch)
        # Degraded edit whose flag nobody consumes (e.g. FOCUS_OUTSIDE).
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        # A clean add-textbox commit follows.
        controller.add_textbox(
            1, fitz.Rect(72, 500, 300, 540), "brand new box",
            font="helv", size=12.0, color=(0.0, 0.0, 0.0),
        )
        assert controller.consume_last_edit_degraded() is False
    finally:
        _teardown(model, view, qapp)


# ------------------------------------------------- suppression-flag pins
# Characterization pins written against the green implementation (marked per
# §5.1): they freeze the flag lifecycle that makes the exactly-once contract
# hold across the View's mode-switch success toast.


def test_degrade_flag_is_consumed_exactly_once(qapp, tmp_path, monkeypatch):
    """PIN: after a degraded commit the Controller reports degraded=True to
    exactly one consumer; the second pull sees False (one degraded edit can
    suppress at most one success toast)."""
    pdf_path = _write_pdf(tmp_path / "flag_once.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        _spy_view(view, monkeypatch)
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        assert controller.consume_last_edit_degraded() is True
        assert controller.consume_last_edit_degraded() is False
    finally:
        _teardown(model, view, qapp)


def test_stale_degrade_flag_never_outlives_a_newer_edit(
    qapp, tmp_path, monkeypatch
):
    """PIN: an unconsumed degraded flag from edit N must not suppress the
    success toast of a later high-fidelity edit N+1 — every edit attempt
    resets the flag before committing."""
    doc = fitz.open()
    _add_raw_page(doc, _tj_array_stream(TARGET))
    _add_raw_page(doc, _tier0_stream())
    pdf_path = tmp_path / "flag_stale.pdf"
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        _spy_view(view, monkeypatch)
        # Edit 1 (page 1, TJ array): degraded; its flag is never consumed.
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        # Edit 2 (page 2, literal Tj): lossless Tier 0.
        _edit_via_signal(model, view, TARGET, REPLACEMENT, page_num=2)
        assert model.last_commit_outcome is not None
        assert model.last_commit_outcome.status is CommitStatus.COMMITTED
        assert controller.consume_last_edit_degraded() is False
    finally:
        _teardown(model, view, qapp)


def test_mode_switch_success_toast_suppressed_for_degraded_commit(
    qapp, tmp_path, monkeypatch
):
    """PIN: the View's mode-switch finalize path pulls the Controller flag —
    a degraded commit gets no plain 文字已儲存 toast, and a LATER, REAL
    non-degraded commit still gets one (flags were consumed, not latched).

    Updated for Task 12 P0-C phase 2 verification: the second half now
    performs an actual second edit (page 2, clean Tier 0) instead of
    re-mocking the same COMMITTED finalize result with no real commit
    behind it — under the fixed gating (``consume_last_edit_result()``
    must return SUCCESS, not just "some finalize reported COMMITTED"), a
    second call with no genuine commit in between would correctly show no
    toast, which would have made the old form of this test wrong under the
    corrected semantics, not a real regression."""
    doc = fitz.open()
    _add_raw_page(doc, _tj_array_stream(TARGET))  # page 1: degrades
    _add_raw_page(doc, _tier0_stream())  # page 2: clean Tier 0
    pdf_path = tmp_path / "mode_switch.pdf"
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)

        monkeypatch.setattr(view, "text_editor", _FakeInlineEditorWidget(), raising=False)
        monkeypatch.setattr(
            view,
            "_finalize_text_edit",
            lambda _reason: _FakeCommittedFinalizeResult(),
            raising=False,
        )

        # Degraded edit, then the finalize that would normally toast success.
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        view.set_mode("browse")
        assert all("文字已儲存" not in message for message, _tone in spy.toasts)

        # A REAL, non-degraded edit follows -- the toast reappears because
        # THIS commit genuinely succeeded, not because of latched state.
        monkeypatch.setattr(view, "text_editor", _FakeInlineEditorWidget(), raising=False)
        _edit_via_signal(model, view, TARGET, REPLACEMENT, page_num=2)
        view.set_mode("browse")
        saved_toasts = [m for m, _t in spy.toasts if "文字已儲存" in m]
        assert len(saved_toasts) == 1
    finally:
        _teardown(model, view, qapp)


# ------------------------------------------------- toast-correctness (P0-C phase 2)
# The View's mode-switch success toast previously gated only on
# ``TextEditOutcome.COMMITTED``, which the finalize path sets whenever the
# ``sig_edit_text``/``sig_move_text_across_pages`` emit itself doesn't raise
# -- it never inspected the Controller's actual ``EditTextResult``. A
# consent-flow decline (``FALLBACK_DECLINED``) is zero-mutation by design;
# showing "文字已儲存" for it (or for a pre-existing REJECTED_STRICT /
# TARGET_BLOCK_NOT_FOUND) would contradict the whole point of asking. These
# tests pin the fix: the toast requires a real, pulled
# ``EditTextResult.SUCCESS``, not just "some finalize reported COMMITTED".


def test_fallback_declined_does_not_show_saved_toast(qapp, tmp_path, monkeypatch):
    """RED: declining the P0-C phase 2 consent prompt is zero mutation --
    the mode-switch finalize must not show 文字已儲存 for it."""
    pdf_path = _write_pdf(tmp_path / "declined_toast.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered"), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda chain: False)
        monkeypatch.setattr(view, "text_editor", _FakeInlineEditorWidget(), raising=False)
        monkeypatch.setattr(
            view,
            "_finalize_text_edit",
            lambda _reason: _FakeCommittedFinalizeResult(),
            raising=False,
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        view.set_mode("browse")

        assert all("文字已儲存" not in message for message, _tone in spy.toasts)
    finally:
        _teardown(model, view, qapp)


def test_rejected_strict_does_not_show_saved_toast(qapp, tmp_path, monkeypatch):
    """RED: a strict-mode rejection is zero mutation -- the mode-switch
    finalize must not show 文字已儲存 for it (pre-existing gap, promoted to
    a PR #30 blocker per the P0-C phase 2 consent contract)."""
    pdf_path = _write_pdf(tmp_path / "strict_toast.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path, TextCommitSettings(engine="tiered", strict=True), monkeypatch
    )
    try:
        spy = _spy_view(view, monkeypatch)
        monkeypatch.setattr(view, "text_editor", _FakeInlineEditorWidget(), raising=False)
        monkeypatch.setattr(
            view,
            "_finalize_text_edit",
            lambda _reason: _FakeCommittedFinalizeResult(),
            raising=False,
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        view.set_mode("browse")

        assert all("文字已儲存" not in message for message, _tone in spy.toasts)
    finally:
        _teardown(model, view, qapp)


def test_target_not_found_does_not_show_saved_toast(qapp, tmp_path, monkeypatch):
    """RED: a target-resolution failure is zero mutation -- the mode-switch
    finalize must not show 文字已儲存 for it (pre-existing gap, promoted to
    a PR #30 blocker per the P0-C phase 2 consent contract)."""
    pdf_path = _write_pdf(tmp_path / "not_found_toast.pdf", _tier0_stream())
    model, view, controller = _launch(pdf_path, TextCommitSettings(), monkeypatch)
    try:
        spy = _spy_view(view, monkeypatch)
        monkeypatch.setattr(view, "text_editor", _FakeInlineEditorWidget(), raising=False)
        monkeypatch.setattr(
            view,
            "_finalize_text_edit",
            lambda _reason: _FakeCommittedFinalizeResult(),
            raising=False,
        )

        # A rect with no overlapping text block: TARGET_BLOCK_NOT_FOUND.
        request = EditTextRequest(
            page=1,
            rect=fitz.Rect(1, 1, 2, 2),
            new_text="does not matter",
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text="text that is not on the page",
        )
        view.sig_edit_text.emit(request)
        view.set_mode("browse")

        assert all("文字已儲存" not in message for message, _tone in spy.toasts)
    finally:
        _teardown(model, view, qapp)


def test_successful_edit_still_shows_saved_toast_once(qapp, tmp_path, monkeypatch):
    """PIN: the fix above must not regress the ordinary case -- a genuine
    successful commit still shows exactly one 文字已儲存 toast."""
    pdf_path = _write_pdf(tmp_path / "success_toast.pdf", _tier0_stream())
    model, view, controller = _launch(pdf_path, TextCommitSettings(), monkeypatch)
    try:
        spy = _spy_view(view, monkeypatch)
        monkeypatch.setattr(view, "text_editor", _FakeInlineEditorWidget(), raising=False)
        monkeypatch.setattr(
            view,
            "_finalize_text_edit",
            lambda _reason: _FakeCommittedFinalizeResult(),
            raising=False,
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        view.set_mode("browse")

        saved_toasts = [m for m, _t in spy.toasts if "文字已儲存" in m]
        assert len(saved_toasts) == 1
    finally:
        _teardown(model, view, qapp)


def test_real_set_mode_toast_gating_never_fires_for_a_declined_fallback(qapp, tmp_path):
    """RED (production View method, unmonkeypatched ``_show_toast``): every
    other test in this section replaces ``PDFView._show_toast`` with a spy
    before asserting -- the REAL production toast path never executes under
    test, so a mutation that reintroduces the old COMMITTED-only gate would
    leave the whole suite green (same discipline as Phase 1's F6 finding).
    This test exercises the unmodified ``set_mode()`` -> ``_show_toast()``
    path directly: patches only ``QLabel.__init__`` (Qt internals) to track
    real toast creation, never ``PDFView`` itself."""
    from unittest import mock

    from PySide6.QtWidgets import QLabel

    pdf_path = _write_pdf(tmp_path / "real_declined_toast.pdf", _tj_array_stream(TARGET))
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(pdf_path))
    try:
        controller.show_page = lambda _page: None
        controller._invalidate_active_render_state = lambda *a, **k: None
        controller._update_undo_redo_tooltips = lambda: None
        view.capture_viewport_anchor = lambda: None
        controller._confirm_legacy_fallback = lambda chain: False
        view.text_editor = _FakeInlineEditorWidget()
        view._finalize_text_edit = lambda _reason: _FakeCommittedFinalizeResult()

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        created: list[QLabel] = []
        original_new = QLabel.__init__

        def _tracking_init(self, *args, **kwargs):
            original_new(self, *args, **kwargs)
            created.append(self)

        with mock.patch.object(QLabel, "__init__", _tracking_init):
            view.set_mode("browse")

        saved_toasts = [lbl for lbl in created if lbl.text() == "文字已儲存"]
        assert saved_toasts == [], (
            f"expected zero real 文字已儲存 toasts for a declined fallback, "
            f"got {len(saved_toasts)}"
        )
    finally:
        _teardown(model, view, qapp)


def test_stale_last_edit_result_does_not_survive_move_validation_guard(
    qapp, tmp_path, monkeypatch
):
    """RED (adversarial verification finding, high): move_text_across_pages()
    must reset _last_edit_result BEFORE its own early-return validation
    guards (empty new_text, doc not open), not after. Otherwise a stale
    SUCCESS from an EARLIER, unconsumed commit-producing interaction (e.g.
    finalized via APPLY/FOCUS_OUTSIDE, neither of which ever calls
    consume_last_edit_result() -- only set_mode()'s MODE_SWITCH path does)
    survives through the guard and gets misread as THIS interaction's
    outcome, showing 文字已儲存 for a move that mutated nothing."""
    pdf_path = _write_pdf(tmp_path / "stale_move.pdf", _tier0_stream())
    model, view, controller = _launch(pdf_path, TextCommitSettings(), monkeypatch)
    try:
        # The empty-new_text guard calls show_error() -> QMessageBox.critical,
        # a blocking modal with no user present in an offscreen test run
        # (documented pitfall) -- replace it with a non-blocking recorder.
        import controller.pdf_controller as controller_module

        errors: list[str] = []
        monkeypatch.setattr(
            controller_module, "show_error", lambda parent, message: errors.append(message)
        )

        # An earlier edit succeeds and is never consumed -- mirrors any
        # finalize reason other than MODE_SWITCH.
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        assert model.last_commit_outcome is not None

        # A validation-guard failure on a DIFFERENT, later interaction --
        # empty new_text -- must not let the stale SUCCESS leak forward.
        controller.move_text_across_pages(
            source_page=1,
            source_rect=fitz.Rect(0, 0, 1, 1),
            destination_page=1,
            destination_rect=fitz.Rect(0, 0, 1, 1),
            new_text="",
        )
        assert len(errors) == 1  # confirms the guard actually fired

        assert controller.consume_last_edit_result() is not EditTextResult.SUCCESS
    finally:
        _teardown(model, view, qapp)


def test_stale_last_edit_result_does_not_survive_add_textbox_validation_guard(
    qapp, tmp_path, monkeypatch
):
    """RED (adversarial verification finding, medium): add_textbox() has the
    same reset-after-guard gap as move_text_across_pages() -- a stale
    SUCCESS from an earlier, unconsumed commit must not survive its
    doc/page-range validation guard."""
    pdf_path = _write_pdf(tmp_path / "stale_add.pdf", _tier0_stream())
    model, view, controller = _launch(pdf_path, TextCommitSettings(), monkeypatch)
    try:
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        assert model.last_commit_outcome is not None

        # Page out of range: the reachable guard (empty text is already
        # filtered upstream by the View before add_textbox is ever called).
        controller.add_textbox(
            99, fitz.Rect(0, 0, 10, 10), "new text", font="helv", size=12.0, color=(0.0, 0.0, 0.0)
        )

        assert controller.consume_last_edit_result() is not EditTextResult.SUCCESS
    finally:
        _teardown(model, view, qapp)
