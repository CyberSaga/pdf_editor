"""WS-C red-light tests for preview verdict parity and session identity."""
from __future__ import annotations

import sys
from dataclasses import replace
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
from model.pdf_text_edit import (  # noqa: E402
    _attempt_tiered_commit,
    _classify_tier0_candidate,
    _Tier0Target,
    derive_tier0_preview_target,
)
from model.text_block import EditableSpan  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    FontOutcome,
    FontResourceAction,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_tier0_plan  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)

import model.text_commit.preview as preview_module  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
)


TARGET = "iii"
GROWTH_REPLACEMENT = "MMM"
TAIL_SPACES = " " * 12
TAIL_WORD = "tail"
TAIL_FULL = TAIL_SPACES + TAIL_WORD
WORLD = "world"

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


def _composite_doc() -> fitz.Document:
    """Tier-1-eligible fixture: ``iii`` -> ``MMM`` grows into a proven-blank
    zone (same shape as ``test_text_commit_tier1_slice1.py``'s fixture)."""
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"/F1 9 Tf (" + TAIL_FULL.encode() + b") Tj "
        b"0 -20 Td /F1 12 Tf (" + WORLD.encode() + b") Tj ET"
    )
    return _stream_doc(stream)


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
            RejectReason.GROWTH_OUTSIDE_PAGE,
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
        lambda *_args, **_kwargs: _Tier0Target(TARGET, origin, bbox, 1)
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


def test_controller_forwards_reprojected_replacement_text_to_preview() -> None:
    """The controller must forward ``target.replacement_for(...)``, not the
    raw keystroke text, to the preview coordinator -- or a ``dict_line``
    preview would raster a candidate the commit path would never write
    (preview/commit token parity, Task 11 Slice 2 design R6/mandatory
    parity)."""
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (Price is  100) Tj ET")
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

    dict_line_target = _Tier0Target(
        "Price is  100", (72.0, 142.0), (72.0, 129.0, 130.0, 146.0), 3, "dict_line"
    )
    original_derive = pdf_controller_module.derive_tier0_preview_target
    pdf_controller_module.derive_tier0_preview_target = (
        lambda *_args, **_kwargs: dict_line_target
    )
    try:
        controller.on_text_edit_plan_preview_request(
            {
                "session_key": "reproject",
                "page_idx": 0,
                "rect": (72.0, 129.0, 130.0, 146.0),
                "original_text": "Price is  100",
                "target_span_id": None,
                "target_mode": "run",
                # The inline editor shows the COLLAPSED (single-space) form.
                "replacement_text": "Price is 200",
                "generation": 1,
                "clip_rect": (72.0, 129.0, 130.0, 146.0),
                "render_scale": 1.0,
            }
        )
        request_kwargs = (
            controller._text_commit_preview_coordinator.request.call_args.kwargs
        )
        # Re-projected: the source's own double space is restored, matching
        # exactly what ``_attempt_tiered_commit`` would later write.
        assert request_kwargs["replacement_text"] == "Price is  200"
        assert request_kwargs["target_text"] == "Price is  100"
    finally:
        pdf_controller_module.derive_tier0_preview_target = original_derive
        doc.close()


# ============================================================ Task 11 F3


def test_scratch_page_count_check_fires_on_a_real_mismatch() -> None:
    """HOLE 1's tautology, pinned directly on ``_verify_patch_postconditions``.

    Before the fix, the scratch (``reopen_probe=False``) V0e branch did
    ``page_count = doc.page_count`` then compared it to ``doc.page_count``
    read again on the SAME call -- always equal, so a genuine page-count
    change could never be caught.  The only honest comparison is against
    the PRE-PATCH baseline ``capture_page_state`` records.
    """
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj ET")
    try:
        page = doc[0]
        registry = DocumentFontRegistry(doc)
        prepared = prepare_tier0_plan(
            doc,
            page,
            target_text=TARGET,
            replacement_text="iij",
            expected_origin=None,
            target_bbox=None,
            registry=registry,
        )
        assert isinstance(prepared, PreparedEdit), prepared

        pre_state = capture_page_state(doc, page, prepared)
        assert pre_state.page_count == doc.page_count
        # A pre-state that (falsely) claims a different pre-patch page
        # count than the document actually has -- exactly what a real
        # reopen that lost/gained a page would produce.
        tampered_pre_state = replace(pre_state, page_count=pre_state.page_count + 1)

        patchset = PatchSet(
            page_xref=prepared.page_xref,
            replacements=(prepared.replacement,),
            expected_page_fingerprint=prepared.page_fingerprint,
        )
        applied = apply_patchset(doc, page, patchset)
        try:
            result = verify_tier0_commit(
                doc,
                page,
                prepared,
                tampered_pre_state,
                reopen_probe=False,
                cached_reopen_probe_ok=True,
            )
        finally:
            applied.revert(doc)

        assert isinstance(result, VerificationFailure), (
            "the tautological check can never fire -- pin the real one"
        )
        assert result.reason == RejectReason.VERIFICATION_FAILED
        assert "page count" in result.detail
    finally:
        doc.close()


def test_preview_refuses_when_cached_session_reopen_probe_failed(monkeypatch) -> None:
    """HOLE 1: preview must consult the session-cached live V0e verdict.

    The scratch is the DECRYPTED session snapshot, so a KEEP round-trip
    failure on the live (e.g. encrypted) document is structurally invisible
    to it.  ``open_preview_session`` must run that probe once, on the live
    document, and ``PlanPreviewRenderer.render`` must refuse the candidate
    with the live V0e reason when the cached verdict is a failure -- even
    though every scratch-only check would otherwise pass.
    """
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj ET")
    try:
        monkeypatch.setattr(
            preview_module, "_reopen_probe_verdict", lambda _doc: False
        )
        session = open_preview_session(doc, 0, "preview-reopen-probe")
        assert session is not None
        assert session.reopen_probe_ok is False

        renderer = PlanPreviewRenderer(session)
        result = renderer.render(_request(doc, replacement="iij"))
        renderer.close()

        assert result.plan_token is None
        assert result.png_bytes == b""
        assert result.reject_reason == RejectReason.VERIFICATION_FAILED
    finally:
        doc.close()


def test_preview_reproves_tier1_font_resource_before_declaring_verified(
    monkeypatch,
) -> None:
    """HOLE 2: preview must re-run the Tier 1 font-resource proof.

    ``engine.prepare``/``.commit`` both call ``build_tier1_font_outcome`` and
    reject ``FONT_RESOURCE_NOT_PROVEN`` when the resource reuse cannot be
    proven; ``PlanPreviewRenderer.render`` skipped that call entirely, so a
    Tier 1 candidate whose font-resource reuse fails previewed green.
    """
    doc = _composite_doc()
    try:
        session = open_preview_session(doc, 0, "preview-tier1-font", max_tier=1)
        assert session is not None
        renderer = PlanPreviewRenderer(session)

        def _not_proven(*_args, **_kwargs) -> FontOutcome:
            return FontOutcome(
                resource_name="F1",
                source_font_xref=0,
                written_font_xref=0,
                action=FontResourceAction.LEGACY_BASE14_SUBSTITUTED,
            )

        monkeypatch.setattr(preview_module, "build_tier1_font_outcome", _not_proven)

        span = _span(doc[0], TARGET)
        request = PlanPreviewRequest(
            session_key="preview-tier1-font",
            generation=1,
            target_text=TARGET,
            replacement_text=GROWTH_REPLACEMENT,
            expected_origin=tuple(float(v) for v in span["origin"]),
            target_bbox=tuple(float(v) for v in span["bbox"]),
            clip_rect=tuple(float(v) for v in span["bbox"]),
            render_scale=1.0,
        )
        result = renderer.render(request)
        renderer.close()

        assert result.plan_token is None
        assert result.png_bytes == b""
        assert result.reject_reason == RejectReason.FONT_RESOURCE_NOT_PROVEN
    finally:
        doc.close()


def test_preview_still_succeeds_for_a_genuinely_proven_tier1_candidate() -> None:
    """Regression guard for the FIX 2 gate: an honest Tier 1 candidate (the
    resource genuinely reuses the source font, unmonkeypatched) must still
    preview green -- the new gate must not become a blanket Tier 1 refusal.
    """
    doc = _composite_doc()
    try:
        session = open_preview_session(doc, 0, "preview-tier1-honest", max_tier=1)
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        span = _span(doc[0], TARGET)
        request = PlanPreviewRequest(
            session_key="preview-tier1-honest",
            generation=1,
            target_text=TARGET,
            replacement_text=GROWTH_REPLACEMENT,
            expected_origin=tuple(float(v) for v in span["origin"]),
            target_bbox=tuple(float(v) for v in span["bbox"]),
            clip_rect=tuple(float(v) for v in span["bbox"]),
            render_scale=1.0,
        )
        result = renderer.render(request)
        renderer.close()

        assert result.reject_reason is None
        assert result.plan_token is not None
        assert result.prepared is not None
        assert result.prepared.tier.value == 1
    finally:
        doc.close()


# ================================================ preview/commit reason parity


def test_preview_relabels_reconstruction_no_match_same_as_commit_path() -> None:
    """WS-D: preview must not report a bare ``NO_MATCH`` where the commit
    path (``_classify_tier0_candidate`` via ``_reconstruction_aware_reason``)
    reports ``TARGET_RECONSTRUCTION_UNVERIFIED`` for the identical
    reconstructed target -- two answers for one condition poisons the
    shadow-mode reason counts both paths feed (TODOS.md:433).

    Fixture mirrors ``test_reconstruction_failure_is_distinguishable_from_
    absent_target``: ``[(Price is) -500 (100)] TJ`` extracts as
    ``'Price is 100'`` (a MuPDF-synthesized kern-advance space) while the
    stream decodes to ``b'Price is100'`` -- no show operator carries that
    exact byte string, so a plain ``bind_source_text`` refuses NO_MATCH.
    The commit path already knows to blame the reconstruction; the preview
    path must reach the same verdict when told the target was
    reconstructed.
    """
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td [(Price is) -500 (100)] TJ ET")
    try:
        session = open_preview_session(doc, 0, "preview-reconstruction", max_tier=0)
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        request = PlanPreviewRequest(
            session_key="preview-reconstruction",
            generation=1,
            target_text="Price is 100",
            replacement_text="Price is  200",
            expected_origin=None,
            target_bbox=None,
            clip_rect=(72.0, 690.0, 200.0, 715.0),
            render_scale=1.0,
            whitespace_reconstructed=True,
        )
        result = renderer.render(request)
        renderer.close()

        assert result.plan_token is None
        assert result.reject_reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED, (
            "preview reported "
            f"{result.reject_reason!r} where the commit path for the same "
            "reconstructed target reports "
            "TARGET_RECONSTRUCTION_UNVERIFIED -- the shadow-mode asymmetry "
            "TODOS.md:433 describes"
        )
    finally:
        doc.close()


def test_preview_leaves_genuine_no_match_unrelabeled() -> None:
    """The other half: a target that was NOT reconstructed
    (``whitespace_reconstructed=False``) must keep a plain ``NO_MATCH`` --
    the fix must discriminate, not relabel every miss."""
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj ET")
    try:
        session = open_preview_session(doc, 0, "preview-genuine-miss", max_tier=0)
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        request = PlanPreviewRequest(
            session_key="preview-genuine-miss",
            generation=1,
            target_text="not on the page at all",
            replacement_text="whatever",
            expected_origin=None,
            target_bbox=None,
            clip_rect=(72.0, 690.0, 200.0, 715.0),
            render_scale=1.0,
            whitespace_reconstructed=False,
        )
        result = renderer.render(request)
        renderer.close()

        assert result.plan_token is None
        assert result.reject_reason == RejectReason.NO_MATCH
        assert result.reject_reason != RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
    finally:
        doc.close()


def test_derived_preview_target_and_render_agree_with_commit_classification() -> None:
    """End-to-end: the REAL ``derive_tier0_preview_target`` on the kern-space
    fixture must (a) mark the target reconstructed and (b) drive
    ``PlanPreviewRenderer`` to the identical reason ``_classify_tier0_
    candidate`` (the commit path) returns for the same page/line -- no
    monkeypatched target, no hard-coded flag. Also proves the fix is load
    bearing: forcing ``whitespace_reconstructed=False`` on the same derived
    target reproduces the pre-fix asymmetry (plain NO_MATCH) instead of the
    commit path's verdict.
    """
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td [(Price is) -500 (100)] TJ ET")
    model = PDFModel()
    try:
        model.doc = doc
        model.ensure_page_index_built(1)
        runs = [r for r in model.block_manager.get_runs(0)]
        assert len(runs) == 3, "fixture must split into three word runs"
        line_rect = fitz.Rect()
        for r in runs:
            line_rect |= r.bbox

        target = derive_tier0_preview_target(
            model,
            page_num=1,
            rect=line_rect,
            original_text="Price is 100",
            target_span_id=None,
            target_mode=None,
        )
        assert target is not None
        assert target.source_kind == "dict_line"
        assert target.whitespace_reconstructed is True

        # The commit path's verdict for the identical edit.
        resolve_status, resolve_result = model._resolve_edit_target(
            page_num=1,
            page_idx=0,
            page=doc[0],
            rect=line_rect,
            new_text="Price is  200",
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text="Price is 100",
            new_rect=None,
            resolved_target_span_id=None,
            effective_target_mode="paragraph",
        )
        assert resolve_status.name == "SUCCESS"
        commit_result = _classify_tier0_candidate(
            model,
            doc[0],
            0,
            "Price is  200",
            resolve_result,
            None,
            None,
            DocumentFontRegistry(doc),
        )
        assert commit_result.reason == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED

        session = open_preview_session(doc, 0, "derived-parity", max_tier=0)
        assert session is not None

        # Fixed behaviour: the derived flag reaches the renderer and the
        # preview verdict matches the commit path exactly.
        renderer = PlanPreviewRenderer(session)
        request = PlanPreviewRequest(
            session_key="derived-parity",
            generation=1,
            target_text=target.text,
            replacement_text=target.replacement_for("Price is 200"),
            expected_origin=target.origin,
            target_bbox=target.bbox,
            clip_rect=target.bbox,
            render_scale=1.0,
            whitespace_reconstructed=target.whitespace_reconstructed,
        )
        result = renderer.render(request)
        renderer.close()
        assert result.reject_reason == commit_result.reason

        # Load-bearing check: with the flag forced False (pre-fix shape),
        # the preview reverts to the old, wrong, unrelabeled answer -- proof
        # this test would have failed before the fix.
        renderer2 = PlanPreviewRenderer(session)
        stale_request = replace(request, whitespace_reconstructed=False)
        stale_result = renderer2.render(stale_request)
        renderer2.close()
        assert stale_result.reject_reason == RejectReason.NO_MATCH
        assert stale_result.reject_reason != commit_result.reason
    finally:
        model.close()
        if not doc.is_closed:
            doc.close()


def test_controller_forwards_whitespace_reconstructed_flag_to_preview() -> None:
    """The controller must thread ``target.whitespace_reconstructed`` (derived
    once per session from the ``_Tier0Target`` the resolve pipeline built)
    through to the coordinator's per-keystroke request -- the DTO plumbing
    half of the WS-D fix, mirroring how style/geometry intent is already
    forwarded."""
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td [(Price is) -500 (100)] TJ ET")
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

    reconstructed_target = _Tier0Target(
        "Price is 100", (72.0, 700.0), (72.0, 695.0, 150.0, 712.0), 3, "dict_line"
    )
    original_derive = pdf_controller_module.derive_tier0_preview_target
    pdf_controller_module.derive_tier0_preview_target = (
        lambda *_args, **_kwargs: reconstructed_target
    )
    try:
        controller.on_text_edit_plan_preview_request(
            {
                "session_key": "reconstruction-flag",
                "page_idx": 0,
                "rect": (72.0, 695.0, 150.0, 712.0),
                "original_text": "Price is 100",
                "target_span_id": None,
                "target_mode": "run",
                "replacement_text": "Price is 200",
                "generation": 1,
                "clip_rect": (72.0, 695.0, 150.0, 712.0),
                "render_scale": 1.0,
            }
        )
        request_kwargs = (
            controller._text_commit_preview_coordinator.request.call_args.kwargs
        )
        assert request_kwargs["whitespace_reconstructed"] is True
    finally:
        pdf_controller_module.derive_tier0_preview_target = original_derive
        doc.close()
