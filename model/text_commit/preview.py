"""Exact plan-backed preview for Tier 0 candidates (Qt-free).

The preview renders the *same* prepared plan that a later commit would
apply: ``prepare_tier0_plan`` runs on a scratch document opened from a
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
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import page_fingerprint
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
)
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_plan
from model.text_commit.verify import (
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
    verify_tier1_commit,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreviewSessionInput:
    """One cached scratch input per edit session — never one per keystroke."""

    session_key: str
    page_number: int
    snapshot_bytes: bytes
    page_fingerprint: str
    page_has_pending_maintenance: bool = False
    max_tier: int = 0


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
    new_rect: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PlanPreviewResult:
    """Raster DTO returned to the GUI thread.

    ``plan_token`` is set exactly when the candidate is tier-eligible (Tier 0,
    or Tier 1 when the session allows escalation); ``reject_reason`` carries
    the sanitized RejectReason code otherwise (the caller falls back to the
    legacy CSS preview without claiming exactness).

    ``prepared`` is the immutable candidate that passed the same scratch
    verification used by live commit.  The controller transfers it to the
    document-session engine cache before presenting the raster, so a later
    commit can consume the exact candidate identified by ``plan_token``.
    """

    session_key: str
    generation: int
    plan_token: str | None
    reject_reason: str | None
    png_bytes: bytes
    clip_rect: tuple[float, float, float, float]
    render_scale: float
    new_rect: tuple[float, float, float, float] | None = None
    prepared: PreparedEdit | None = None


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

    def _ensure_scratch(self) -> tuple[fitz.Document, DocumentFontRegistry]:
        if self._scratch is None:
            self._scratch = fitz.open("pdf", self._session.snapshot_bytes)
            self._registry = DocumentFontRegistry(self._scratch)
        assert self._registry is not None
        return self._scratch, self._registry

    def render(self, request: PlanPreviewRequest) -> PlanPreviewResult:
        """Prepare, verify, splice, rasterize, revert on the scratch copy."""

        def _rejection(reason: str) -> PlanPreviewResult:
            return PlanPreviewResult(
                session_key=request.session_key,
                generation=request.generation,
                plan_token=None,
                reject_reason=reason,
                png_bytes=b"",
                clip_rect=request.clip_rect,
                render_scale=request.render_scale,
                new_rect=request.new_rect,
            )

        scratch, registry = self._ensure_scratch()
        page = scratch[self._session.page_number]
        plan = prepare_plan(
            scratch,
            page,
            target_text=request.target_text,
            replacement_text=request.replacement_text,
            expected_origin=request.expected_origin,
            target_bbox=request.target_bbox,
            registry=registry,
            style_overrides=request.style_overrides,
            new_rect=request.new_rect,
            page_has_pending_maintenance=self._session.page_has_pending_maintenance,
            max_tier=self._session.max_tier,
        )
        if isinstance(plan, PlanRejection):
            return _rejection(plan.reason)

        patchset = PatchSet(
            page_xref=plan.page_xref,
            replacements=(plan.replacement,),
            expected_page_fingerprint=plan.page_fingerprint,
        )
        pre_state = capture_page_state(scratch, page, plan)
        try:
            applied = apply_patchset(scratch, page, patchset)
        except (StalePlanError, SpliceError) as exc:
            logger.warning("plan preview splice failed: %s", type(exc).__name__)
            return _rejection("preview_splice_failed")
        try:
            verify_fn = (
                verify_tier1_commit
                if plan.tier.value == 1
                else verify_tier0_commit
            )
            verification = verify_fn(
                scratch, page, plan, pre_state, reopen_probe=False
            )
            if isinstance(verification, VerificationFailure):
                logger.info(
                    "preview candidate refuted on scratch: %s (%s)",
                    verification.reason,
                    verification.detail,
                )
                return _rejection(verification.reason)
            scale = float(request.render_scale)
            clip = (
                fitz.Rect(request.clip_rect)
                | fitz.Rect(plan.effective_verify_bbox)
            ) & page.rect
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
            clip_rect=(
                float(clip.x0),
                float(clip.y0),
                float(clip.x1),
                float(clip.y1),
            ),
            render_scale=request.render_scale,
            new_rect=request.new_rect,
            prepared=plan,
        )

    def close(self) -> None:
        if self._scratch is not None:
            self._scratch.close()
            self._scratch = None
            self._registry = None
