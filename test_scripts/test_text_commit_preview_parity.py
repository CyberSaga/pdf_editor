"""WS-C red-light tests for preview verdict parity and session identity."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import controller.pdf_controller as pdf_controller_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from model.edit_requests import StyleOverrides  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import _attempt_tiered_commit  # noqa: E402
from model.text_block import EditableSpan  # noqa: E402
from model.text_commit.dto import RejectReason, TextCommitSettings  # noqa: E402
from model.text_commit.plan import PreparedEdit  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)


TARGET = "iii"
GROWTH_REPLACEMENT = "MMM"

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


def _stream_doc(
    stream: bytes, *, width: float = 595.0, height: float = 842.0
) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(
        page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>"
    )
    return doc


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"{probe!r} not found")


def _request(doc: fitz.Document, replacement: str = GROWTH_REPLACEMENT):
    span = _span(doc[0], TARGET)
    bbox = tuple(float(value) for value in span["bbox"])
    origin = tuple(float(value) for value in span["origin"])
    return PlanPreviewRequest(
        session_key="preview-parity",
        generation=1,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=origin,
        target_bbox=bbox,
        clip_rect=bbox,
        render_scale=1.0,
    )


@pytest.mark.parametrize(
    ("stream", "width", "height", "expected_reason"),
    (
        (
            b"BT /F1 12 Tf 72 120 Td (iii) Tj ET "
            b"0 0 0 rg 70 0 130 200 re f",
            595.0,
            842.0,
            RejectReason.GROWTH_REGION_NOT_BLANK,
        ),
        (
            b"BT /F1 12 Tf 175 120 Td (iii) Tj ET",
            200.0,
            200.0,
            "growth_outside_page",
        ),
    ),
)
def test_preview_refuses_candidates_that_prepare_rejects(
    stream: bytes,
    width: float,
    height: float,
    expected_reason: str,
) -> None:
    doc = _stream_doc(stream, width=width, height=height)
    try:
        session = open_preview_session(
            doc, 0, "preview-parity", max_tier=1
        )
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        result = renderer.render(_request(doc))
        renderer.close()

        assert result.plan_token is None
        assert result.png_bytes == b""
        assert result.reject_reason == expected_reason
    finally:
        doc.close()


def test_preview_returns_verified_candidate_for_model_session_cache() -> None:
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj ET")
    model = PDFModel(
        text_commit_settings=TextCommitSettings(
            engine="tiered", preview="plan", max_tier=0
        )
    )
    model.doc = doc
    try:
        session = open_preview_session(doc, 0, "cache-session")
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        result = renderer.render(_request(doc, replacement="iij"))
        renderer.close()

        assert result.plan_token is not None
        assert isinstance(result.prepared, PreparedEdit)

        model.cache_verified_candidate(result.plan_token, result.prepared)
        engine = model.get_tiered_commit_engine()
        assert engine is model.get_tiered_commit_engine()
        assert engine.get_verified_candidate(result.plan_token) is result.prepared

        def fail_prepare(*_args, **_kwargs):
            raise AssertionError("preview candidate must bypass prepare()")

        engine.prepare = fail_prepare  # type: ignore[method-assign]
        span = _span(doc[0], TARGET)
        editable = EditableSpan(
            span_id="preview-target",
            page_idx=0,
            block_idx=0,
            line_idx=0,
            span_idx=0,
            bbox=fitz.Rect(span["bbox"]),
            origin=fitz.Point(*span["origin"]),
            text=TARGET,
            font="Helvetica",
            size=float(span["size"]),
            color=(0.0, 0.0, 0.0),
            dir_vec=(1.0, 0.0),
            rotation=0,
        )
        resolve_result = SimpleNamespace(
            overlap_cluster=[editable],
            target_member_span_ids={editable.span_id},
        )
        outcome, reason = _attempt_tiered_commit(
            model,
            doc[0],
            0,
            "iij",
            resolve_result,
            None,
            None,
            plan_token=result.plan_token,
        )
        assert reason is None
        assert outcome is not None
        assert outcome.status.value == "committed"
        assert "iij" in doc[0].get_text()
    finally:
        model.close()
        if not doc.is_closed:
            doc.close()


def test_controller_forwards_style_and_geometry_intent_to_preview() -> None:
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj ET")
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = doc
    controller.model.text_commit_settings = TextCommitSettings(
        engine="tiered", preview="plan"
    )
    controller.model.pending_edits = []
    controller.view = MagicMock()
    controller._text_commit_preview_coordinator = MagicMock()
    controller._plan_preview_session_key = None
    controller._plan_preview_target = None
    origin = tuple(_span(doc[0], TARGET)["origin"])
    bbox = tuple(_span(doc[0], TARGET)["bbox"])

    original_derive = pdf_controller_module.derive_tier0_preview_target
    pdf_controller_module.derive_tier0_preview_target = (
        lambda *_args, **_kwargs: (TARGET, origin, bbox)
    )
    try:
        style = StyleOverrides(font_family="courier", font_size=14.0)
        geometry = (70.0, 690.0, 180.0, 720.0)
        controller.on_text_edit_plan_preview_request(
            {
                "session_key": "style-geometry",
                "page_idx": 0,
                "rect": bbox,
                "original_text": TARGET,
                "target_span_id": None,
                "target_mode": "run",
                "replacement_text": "iij",
                "generation": 1,
                "clip_rect": bbox,
                "render_scale": 1.0,
                "style_overrides": style,
                "new_rect": geometry,
            }
        )
        request_kwargs = (
            controller._text_commit_preview_coordinator.request.call_args.kwargs
        )
        assert request_kwargs["style_overrides"] == style
        assert request_kwargs["new_rect"] == geometry
    finally:
        pdf_controller_module.derive_tier0_preview_target = original_derive
        doc.close()
