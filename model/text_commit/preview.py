"""Exact plan-backed preview for Tier 0/Tier 1 candidates (Qt-free).

The preview renders the *same* prepared plan that a later commit would
apply: ``prepare_plan`` runs on a scratch document opened from a
snapshot taken once per edit session, the validated patch is spliced in,
the clip region is rasterized, and the patch is reverted.  Because the
plan token is content-derived (page fingerprint + splice bytes), the
preview's token equals the committed plan's token whenever the document
is unchanged in between — that equality is the exactness guarantee.

Performance contract: ``open_preview_session`` is the only place a
document snapshot is taken; ``PlanPreviewRenderer`` opens exactly one
scratch document per session and reuses it for every keystroke.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.dto import RejectReason
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import page_fingerprint, scan_shared_streams
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
)
from model.text_commit.plan import PlanRejection, prepare_plan
from model.text_commit.verify import growth_zone_is_uniform

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreviewSessionInput:
    """One cached scratch input per edit session — never one per keystroke."""

    session_key: str
    page_number: int
    snapshot_bytes: bytes
    page_fingerprint: str
    page_has_pending_maintenance: bool = False
    max_tier: int = 0  # session-stable, from model.text_commit_settings.max_tier


@dataclass(frozen=True)
class PlanPreviewRequest:
    """One keystroke's preview work item (immutable, Qt-free)."""

    session_key: str
    generation: int
    target_text: str
    replacement_text: str
    expected_origin: tuple[float, float] | None
    target_bbox: tuple[float, float, float, float] | None
    clip_rect: tuple[float, float, float, float]
    render_scale: float
    style_overrides: StyleOverrides | None = None


@dataclass(frozen=True)
class PlanPreviewResult:
    """Raster DTO returned to the GUI thread.

    ``plan_token`` is set exactly when the candidate is Tier 0 (or, at
    ``session.max_tier=1``, Tier 1) eligible; ``reject_reason`` carries the
    sanitized RejectReason code otherwise (the caller falls back to the
    legacy CSS preview without claiming exactness).
    """

    session_key: str
    generation: int
    plan_token: str | None
    reject_reason: str | None
    png_bytes: bytes
    clip_rect: tuple[float, float, float, float]
    render_scale: float
    tier: int = 0


def _session_snapshot_bytes(
    doc: fitz.Document, password: str | None
) -> bytes | None:
    """Decrypted, xref-stable bytes for the scratch copy — or ``None``.

    Never calls ``tobytes()`` with the default (decrypting) encryption on the
    live handle.  On an *encrypted* document that silently poisons the
    handle's internal crypt state (a PyMuPDF AES quirk), so the user's next
    ``encryption=KEEP`` save writes content streams that no longer decrypt —
    reported as success, discovered as blank pages on reopen.  Take an
    ``encryption=KEEP`` snapshot instead and decrypt a throwaway clone, whose
    crypt state nobody depends on.  ``KEEP`` is a no-op for unencrypted
    documents, so one path covers both.

    Returns ``None`` (never raises) when an encrypted document's clone cannot
    be re-authenticated; the caller degrades to the legacy preview rather
    than claiming exactness.
    """
    keep_bytes = doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
    clone = fitz.open("pdf", keep_bytes)
    try:
        if not clone.needs_pass:
            return keep_bytes
        if password is None or clone.authenticate(password) == 0:
            return None
        return clone.tobytes(
            garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE
        )
    finally:
        clone.close()


def open_preview_session(
    doc: fitz.Document,
    page_number: int,
    session_key: str,
    *,
    password: str | None = None,
    page_has_pending_maintenance: bool = False,
    max_tier: int = 0,
) -> PreviewSessionInput | None:
    """Snapshot the document once for a whole edit session.

    ``tobytes()`` preserves xref numbering and decoded stream bytes, so
    plans prepared on the scratch copy are byte-valid on the live document.

    Returns ``None`` when an encrypted document cannot be snapshotted
    without its password — the live handle is left untouched either way.
    """
    page = doc[page_number]
    snapshot_bytes = _session_snapshot_bytes(doc, password)
    if snapshot_bytes is None:
        return None
    return PreviewSessionInput(
        session_key=session_key,
        page_number=page_number,
        snapshot_bytes=snapshot_bytes,
        page_fingerprint=page_fingerprint(doc, page),
        page_has_pending_maintenance=page_has_pending_maintenance,
        max_tier=max_tier,
    )


class PlanPreviewRenderer:
    """Render prepared Tier 0 plans on one session-scoped scratch document.

    Not thread-safe: exactly one thread (the preview worker) may call
    ``render``/``close``.  The scratch document is opened lazily so it is
    created in the calling thread, and every render reverts its patch so
    the scratch stays byte-identical to the session snapshot.
    """

    def __init__(self, session: PreviewSessionInput) -> None:
        self._session = session
        self._scratch: fitz.Document | None = None
        self._registry: DocumentFontRegistry | None = None
        self._shared_streams: frozenset[int] | None = None

    def _ensure_scratch(self) -> tuple[fitz.Document, DocumentFontRegistry]:
        if self._scratch is None:
            self._scratch = fitz.open("pdf", self._session.snapshot_bytes)
            self._registry = DocumentFontRegistry(self._scratch)
            # One O(page_count) scan per session, not per keystroke: the
            # scratch document's page structure never changes (every render
            # reverts its patch), so the shared-stream set cannot drift.
            self._shared_streams = scan_shared_streams(self._scratch)
        assert self._registry is not None
        return self._scratch, self._registry

    def render(self, request: PlanPreviewRequest) -> PlanPreviewResult:
        """Prepare, splice, rasterize, revert — all on the scratch copy."""

        def _rejection(reason: str) -> PlanPreviewResult:
            return PlanPreviewResult(
                session_key=request.session_key,
                generation=request.generation,
                plan_token=None,
                reject_reason=reason,
                png_bytes=b"",
                clip_rect=request.clip_rect,
                render_scale=request.render_scale,
            )

        scratch, registry = self._ensure_scratch()
        page = scratch[self._session.page_number]
        plan = prepare_plan(
            scratch,
            page,
            max_tier=self._session.max_tier,
            target_text=request.target_text,
            replacement_text=request.replacement_text,
            expected_origin=request.expected_origin,
            target_bbox=request.target_bbox,
            registry=registry,
            style_overrides=request.style_overrides,
            page_has_pending_maintenance=self._session.page_has_pending_maintenance,
            shared_stream_xrefs=self._shared_streams,
        )
        if isinstance(plan, PlanRejection):
            return _rejection(plan.reason)

        # Growth admission, pre-splice, on this same scratch page: the SAME
        # helper engine.prepare/commit use, so preview and commit agree on
        # the refusal (plan.md D11).
        if plan.growth_bbox_page is not None and not growth_zone_is_uniform(
            page, plan.growth_bbox_page
        ):
            return _rejection(RejectReason.GROWTH_EXCEEDS_BLANK_REGION)

        patchset = PatchSet(
            page_xref=plan.page_xref,
            replacements=(plan.replacement,),
            expected_page_fingerprint=plan.page_fingerprint,
        )
        try:
            applied = apply_patchset(scratch, page, patchset)
        except (StalePlanError, SpliceError) as exc:
            logger.warning("plan preview splice failed: %s", type(exc).__name__)
            return _rejection("preview_splice_failed")
        try:
            scale = float(request.render_scale)
            clip = fitz.Rect(request.clip_rect) & page.rect
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), clip=clip, annots=True
            )
            png_bytes = pixmap.tobytes("png")
        finally:
            applied.revert(scratch)
        return PlanPreviewResult(
            session_key=request.session_key,
            generation=request.generation,
            plan_token=plan.token,
            reject_reason=None,
            png_bytes=png_bytes,
            clip_rect=request.clip_rect,
            render_scale=request.render_scale,
            tier=plan.tier,
        )

    def close(self) -> None:
        if self._scratch is not None:
            self._scratch.close()
            self._scratch = None
            self._registry = None
