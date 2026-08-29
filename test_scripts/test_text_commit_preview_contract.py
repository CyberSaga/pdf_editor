"""Red-light tests for the exact plan-backed preview (plan Task 8).

Contract: the View only emits a preview request (never opens a PDF, never
calls the Model); a QThread worker owned by the Controller renders the
prepared Tier 0 plan on a cached scratch document and returns raster DTOs;
stale responses are dropped by session/generation/identity.  Identity: the
preview's plan token equals the token of the plan later committed, and a
document mutated between preview and commit yields STALE_PLAN with no
mutation.  Performance: one document snapshot per edit session — never one
per keystroke.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import controller.pdf_controller as pdf_controller_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from controller.text_commit_coordinator import (  # noqa: E402
    PlanPreviewIdentity,
    TextCommitPreviewCoordinator,
)
from model.text_commit.dto import RejectReason, TextCommitSettings  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from model.pdf_text_edit import _Tier0Target  # noqa: E402
from model.text_commit.plan import PreparedEdit  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    PlanPreviewResult,
    PreviewSessionInput,
    open_preview_session,
)
from view.text_editing import PreviewBackedInlineTextEditor  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
WIDER = "Price 2W24"  # W is wider than a digit: advance mismatch
DOWNSTREAM = "Downstream line stays"


def _tier0_doc() -> fitz.Document:
    """Page whose only content is a raw literal-Tj stream (plus a neighbor)."""
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
    return doc


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _target_geometry(doc: fitz.Document) -> tuple[tuple, tuple, tuple]:
    span = _span(doc[0], TARGET)
    origin = tuple(span["origin"])
    bbox = tuple(span["bbox"])
    clip = (bbox[0] - 4.0, bbox[1] - 4.0, bbox[2] + 4.0, bbox[3] + 4.0)
    return origin, bbox, clip


def _request(session_key: str, generation: int, doc: fitz.Document,
             replacement: str = REPLACEMENT) -> PlanPreviewRequest:
    origin, bbox, clip = _target_geometry(doc)
    return PlanPreviewRequest(
        session_key=session_key,
        generation=generation,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=origin,
        target_bbox=bbox,
        clip_rect=clip,
        render_scale=2.0,
    )


def _spin_until(condition, timeout_ms: int = 4000) -> None:
    loop = QEventLoop()

    def poll() -> None:
        if condition():
            loop.quit()
        else:
            QTimer.singleShot(5, poll)

    QTimer.singleShot(0, poll)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


# ------------------------------------------------- session + renderer (model)


def test_open_preview_session_takes_exactly_one_snapshot(monkeypatch):
    doc = _tier0_doc()
    calls: list[int] = []
    original_tobytes = fitz.Document.tobytes

    def counting_tobytes(self, *args, **kwargs):
        calls.append(1)
        return original_tobytes(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "tobytes", counting_tobytes)
    session = open_preview_session(doc, 0, "sess-1")
    assert len(calls) == 1
    assert isinstance(session, PreviewSessionInput)
    assert session.session_key == "sess-1"
    assert session.page_number == 0
    assert len(session.snapshot_bytes) > 0
    assert session.page_fingerprint == page_fingerprint(doc, doc[0])
    doc.close()


def test_renderer_reuses_one_scratch_document_across_keystrokes(monkeypatch):
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")

    open_calls: list[int] = []
    tobytes_calls: list[int] = []
    original_open = fitz.open
    original_tobytes = fitz.Document.tobytes

    def counting_open(*args, **kwargs):
        open_calls.append(1)
        return original_open(*args, **kwargs)

    def counting_tobytes(self, *args, **kwargs):
        tobytes_calls.append(1)
        return original_tobytes(self, *args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)
    monkeypatch.setattr(fitz.Document, "tobytes", counting_tobytes)

    renderer = PlanPreviewRenderer(session)
    tokens: list[str | None] = []
    for generation in range(1, 6):
        replacement = REPLACEMENT if generation % 2 else "Price 2020"
        result = renderer.render(_request("sess-1", generation, doc, replacement))
        assert result.reject_reason is None, result.reject_reason
        tokens.append(result.plan_token)
    renderer.close()

    assert len(open_calls) == 1  # one scratch document for the whole session
    assert len(tobytes_calls) == 0  # never a fresh snapshot per keystroke
    # Reverting after each render restores byte state: identical keystrokes
    # must yield identical plan tokens.
    assert tokens[0] == tokens[2] == tokens[4]
    assert tokens[1] == tokens[3]
    assert tokens[0] != tokens[1]
    doc.close()


def test_render_returns_raster_dto_with_plan_token():
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    request = _request("sess-1", 1, doc)

    renderer = PlanPreviewRenderer(session)
    result = renderer.render(request)
    renderer.close()

    assert isinstance(result, PlanPreviewResult)
    assert result.session_key == "sess-1"
    assert result.generation == 1
    assert result.reject_reason is None
    assert result.plan_token is not None and len(result.plan_token) == 64
    assert result.png_bytes.startswith(b"\x89PNG")
    assert result.clip_rect == request.clip_rect
    assert result.render_scale == request.render_scale

    # The raster shows the *edited* page: it must differ from the unedited
    # baseline of the same clip at the same scale.
    baseline_doc = fitz.open("pdf", session.snapshot_bytes)
    baseline = baseline_doc[0].get_pixmap(
        matrix=fitz.Matrix(2.0, 2.0), clip=fitz.Rect(request.clip_rect)
    ).tobytes("png")
    baseline_doc.close()
    assert result.png_bytes != baseline
    doc.close()


def test_render_rejection_returns_reason_without_raster():
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    renderer = PlanPreviewRenderer(session)
    result = renderer.render(_request("sess-1", 1, doc, replacement=WIDER))
    renderer.close()

    assert result.plan_token is None
    assert result.png_bytes == b""
    assert result.reject_reason == RejectReason.ADVANCE_MISMATCH
    doc.close()


# ------------------------------------------------------------------ identity


def test_preview_token_equals_committed_plan_token():
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    renderer = PlanPreviewRenderer(session)
    preview = renderer.render(_request("sess-1", 1, doc))
    renderer.close()
    assert preview.plan_token is not None

    origin, bbox, _clip = _target_geometry(doc)
    engine = TieredCommitEngine(doc)
    prepared = engine.prepare(
        doc[0],
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=origin,
        target_bbox=bbox,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.token == preview.plan_token

    outcome = engine.commit(prepared)
    assert outcome.status.value == "committed"
    assert REPLACEMENT in doc[0].get_text()
    doc.close()


def test_mutation_between_preview_and_commit_yields_stale_plan_without_mutation():
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    renderer = PlanPreviewRenderer(session)
    preview = renderer.render(_request("sess-1", 1, doc))
    renderer.close()

    origin, bbox, _clip = _target_geometry(doc)
    engine = TieredCommitEngine(doc)
    prepared = engine.prepare(
        doc[0],
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=origin,
        target_bbox=bbox,
    )
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.token == preview.plan_token

    # Someone else mutates the page between preview and commit.
    doc[0].insert_text((72, 400), "interloper", fontsize=10.0, fontname="helv")
    fingerprint_after_mutation = page_fingerprint(doc, doc[0])

    outcome = engine.commit(prepared)
    assert outcome.status.value == "stale_plan"
    assert page_fingerprint(doc, doc[0]) == fingerprint_after_mutation
    assert REPLACEMENT not in doc[0].get_text()
    assert TARGET in doc[0].get_text()
    doc.close()


# ------------------------------------------------------- coordinator (Qt)


def _make_coordinator(consumed: list, failures: list,
                      identity_matches=lambda _identity: True):
    return TextCommitPreviewCoordinator(
        result_consumer=lambda identity, result: consumed.append((identity, result)),
        failure_consumer=lambda identity, exc: failures.append((identity, exc)),
        identity_matches=identity_matches,
    )


def test_coordinator_worker_returns_raster_dto(qapp):
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    consumed: list = []
    failures: list = []
    coordinator = _make_coordinator(consumed, failures)
    coordinator.begin_session(session)
    request = _request("sess-1", 1, doc)
    token = coordinator.request(
        generation=1,
        target_text=request.target_text,
        replacement_text=request.replacement_text,
        expected_origin=request.expected_origin,
        target_bbox=request.target_bbox,
        clip_rect=request.clip_rect,
        render_scale=request.render_scale,
    )
    assert isinstance(token, str) and token

    _spin_until(lambda: bool(consumed or failures))
    assert failures == []
    assert len(consumed) == 1
    identity, result = consumed[0]
    assert isinstance(identity, PlanPreviewIdentity)
    assert identity.session_key == "sess-1"
    assert identity.generation == 1
    assert isinstance(result, PlanPreviewResult)
    assert result.plan_token is not None
    image = QImage.fromData(result.png_bytes, "PNG")
    assert not image.isNull()
    clip = fitz.Rect(request.clip_rect)
    assert abs(image.width() - clip.width * 2.0) <= 2
    assert abs(image.height() - clip.height * 2.0) <= 2
    assert coordinator.wait_for_done(3000) is True
    doc.close()


def test_coordinator_drops_stale_generation_results(qapp):
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    consumed: list = []
    failures: list = []
    coordinator = _make_coordinator(consumed, failures)
    coordinator.begin_session(session)
    request = _request("sess-1", 1, doc)
    common = dict(
        target_text=request.target_text,
        expected_origin=request.expected_origin,
        target_bbox=request.target_bbox,
        clip_rect=request.clip_rect,
        render_scale=request.render_scale,
    )
    coordinator.request(generation=1, replacement_text=REPLACEMENT, **common)
    coordinator.request(generation=2, replacement_text="Price 2020", **common)

    _spin_until(lambda: not coordinator.has_active_job)
    qapp.processEvents()
    assert failures == []
    generations = [identity.generation for identity, _result in consumed]
    assert generations == [2]  # the superseded keystroke never surfaces

    # After end_session the coordinator refuses new work and drops late results.
    coordinator.end_session()
    assert (
        coordinator.request(generation=3, replacement_text=REPLACEMENT, **common)
        is None
    )
    assert coordinator.wait_for_done(3000) is True
    doc.close()


def test_coordinator_identity_gate_drops_mismatched_results(qapp):
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-1")
    consumed: list = []
    failures: list = []
    coordinator = _make_coordinator(
        consumed, failures, identity_matches=lambda _identity: False
    )
    coordinator.begin_session(session)
    request = _request("sess-1", 1, doc)
    coordinator.request(
        generation=1,
        target_text=request.target_text,
        replacement_text=request.replacement_text,
        expected_origin=request.expected_origin,
        target_bbox=request.target_bbox,
        clip_rect=request.clip_rect,
        render_scale=request.render_scale,
    )
    _spin_until(lambda: not coordinator.has_active_job)
    qapp.processEvents()
    assert consumed == []
    assert failures == []
    assert coordinator.wait_for_done(3000) is True
    doc.close()


# ------------------------------------------------------------- view contract


class _NullCssRenderer:
    """Stand-in for the legacy CSS PreviewRenderer: never touches fitz."""

    def render(self, **_kwargs):
        return None


def test_editor_hook_emits_request_only_and_never_opens_a_pdf(qapp, monkeypatch):
    editor = PreviewBackedInlineTextEditor(TARGET, _NullCssRenderer())
    requests: list[tuple[str, int]] = []
    editor.set_plan_preview_hook(
        lambda text, generation: requests.append((text, generation))
    )

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("View must never open a PDF for preview")

    monkeypatch.setattr(fitz, "open", forbidden_open)

    editor.configure_render_context(
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        rect_pt=(70.0, 130.0, 200.0, 150.0),
        rotation=0,
        render_scale=2.0,
        line_height=0.0,
    )
    assert requests == [(TARGET, 1)]

    editor.setPlainText(REPLACEMENT)
    editor._regenerate_preview()  # synchronous stand-in for the debounce
    assert requests[-1] == (REPLACEMENT, 2)
    assert len(requests) >= 2


def test_editor_applies_only_current_generation_plan_raster(qapp):
    editor = PreviewBackedInlineTextEditor(TARGET, _NullCssRenderer())
    editor.set_plan_preview_hook(lambda _text, _generation: None)
    editor.configure_render_context(
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        rect_pt=(70.0, 130.0, 200.0, 150.0),
        rotation=0,
        render_scale=2.0,
        line_height=0.0,
    )
    editor.setPlainText(REPLACEMENT)
    editor._regenerate_preview()  # generation 2 is now current

    stale = QImage(4, 4, QImage.Format_RGBA8888)
    stale.fill(0xFF0000FF)
    editor.apply_plan_preview(1, stale)
    assert editor._plan_preview_active is False
    assert editor._preview_image is not stale

    current = QImage(4, 4, QImage.Format_RGBA8888)
    current.fill(0xFF00FF00)
    editor.apply_plan_preview(2, current)
    assert editor._plan_preview_active is True
    assert editor._preview_image is current

    # The next keystroke invalidates the raster until a fresh one arrives.
    editor.setPlainText("Price 2020")
    editor._regenerate_preview()
    assert editor._plan_preview_active is False


# ------------------------------------------------------- controller wiring


def _minimal_controller(doc: fitz.Document, settings: TextCommitSettings):
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = doc
    controller.model.text_commit_settings = settings
    controller.model.pending_edits = []
    controller.view = MagicMock()
    controller._text_commit_preview_coordinator = MagicMock()
    controller._plan_preview_session_key = None
    controller._plan_preview_target = None
    return controller


def _payload(generation: int, session_key: str = "sess-1") -> dict:
    return {
        "session_key": session_key,
        "page_idx": 0,
        "rect": (70.0, 130.0, 200.0, 150.0),
        "original_text": TARGET,
        "target_span_id": None,
        "target_mode": "run",
        "replacement_text": REPLACEMENT,
        "generation": generation,
        "clip_rect": (70.0, 130.0, 200.0, 150.0),
        "render_scale": 2.0,
    }


def test_controller_caches_session_and_derives_target_once(monkeypatch):
    doc = _tier0_doc()
    origin, bbox, _clip = _target_geometry(doc)
    derive_calls: list = []

    def fake_derive(model, **kwargs):
        derive_calls.append(kwargs)
        return _Tier0Target(TARGET, origin, bbox, 1)

    monkeypatch.setattr(
        pdf_controller_module, "derive_tier0_preview_target", fake_derive
    )
    tobytes_calls: list[int] = []
    original_tobytes = fitz.Document.tobytes

    def counting_tobytes(self, *args, **kwargs):
        tobytes_calls.append(1)
        return original_tobytes(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "tobytes", counting_tobytes)

    controller = _minimal_controller(
        doc, TextCommitSettings(engine="tiered", preview="plan")
    )
    controller.on_text_edit_plan_preview_request(_payload(1))
    controller.on_text_edit_plan_preview_request(_payload(2))

    coordinator = controller._text_commit_preview_coordinator
    assert coordinator.begin_session.call_count == 1
    session = coordinator.begin_session.call_args.args[0]
    assert isinstance(session, PreviewSessionInput)
    assert session.session_key == "sess-1"
    assert len(tobytes_calls) == 1  # one snapshot per edit session
    assert len(derive_calls) == 1  # target derived once per edit session
    assert coordinator.request.call_count == 2
    generations = [
        call.kwargs["generation"] for call in coordinator.request.call_args_list
    ]
    assert generations == [1, 2]
    doc.close()


def test_controller_ignores_requests_when_preview_flag_is_legacy():
    doc = _tier0_doc()
    controller = _minimal_controller(
        doc, TextCommitSettings(engine="tiered", preview="legacy")
    )
    controller.on_text_edit_plan_preview_request(_payload(1))
    coordinator = controller._text_commit_preview_coordinator
    coordinator.begin_session.assert_not_called()
    coordinator.request.assert_not_called()
    doc.close()


def test_controller_routes_result_to_view_as_qimage(qapp):
    doc = _tier0_doc()
    controller = _minimal_controller(
        doc, TextCommitSettings(engine="tiered", preview="plan")
    )
    png = doc[0].get_pixmap(
        matrix=fitz.Matrix(1.0, 1.0), clip=fitz.Rect(70, 130, 90, 150)
    ).tobytes("png")
    identity = PlanPreviewIdentity(token="tok", session_key="sess-1", generation=3)
    result = PlanPreviewResult(
        session_key="sess-1",
        generation=3,
        plan_token="ab" * 32,
        reject_reason=None,
        png_bytes=png,
        clip_rect=(70.0, 130.0, 90.0, 150.0),
        render_scale=1.0,
    )

    controller._consume_plan_preview(identity, result)

    call = controller.view.apply_text_edit_plan_preview.call_args
    assert call.kwargs["session_key"] == "sess-1"
    assert call.kwargs["generation"] == 3
    assert call.kwargs["plan_token"] == "ab" * 32
    assert call.kwargs["reject_reason"] is None
    image = call.kwargs["image"]
    assert isinstance(image, QImage)
    assert not image.isNull()
    doc.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
