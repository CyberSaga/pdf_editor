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
from model.text_commit.dto import FontResourceAction, RejectReason
from model.text_commit.evidence import ReplayEvidenceCache
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import page_fingerprint
from model.text_commit.interpretation import PageInterpretation, interpret_page
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
    build_tier1_font_outcome,
)
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_plan
from model.text_commit.verify import (
    PreStateBaselineCache,
    VerificationFailure,
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
    # The live V0e KEEP-encryption round-trip probe (see
    # ``_reopen_probe_verdict``), run ONCE on the live document at session
    # open and cached here for every keystroke's ``render`` call.  Defaults
    # to ``False`` (fail-closed): a ``PreviewSessionInput`` built any other
    # way than ``open_preview_session`` must not be silently trusted.
    reopen_probe_ok: bool = False


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
    # True when ``target_text`` is not a verbatim quotation of the content
    # stream -- a run-join or an extractor-synthesized dict-line quote (see
    # ``model.pdf_text_edit._Tier0Target.whitespace_reconstructed``). The
    # controller derives this once per edit session from the same
    # ``_Tier0Target`` the commit path resolves, so a ``NO_MATCH`` here can
    # be relabeled ``TARGET_RECONSTRUCTION_UNVERIFIED`` under exactly the
    # condition the commit path (``_reconstruction_aware_reason``) uses --
    # closing the shadow-mode reason asymmetry (TODOS.md:433). Plain bool,
    # no model-layer type import, to keep this DTO Qt-free and
    # picklable-plain across the QThread worker boundary like its
    # neighbors.
    whitespace_reconstructed: bool = False


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


def _live_keep_round_trip(
    doc: fitz.Document,
) -> tuple[bytes, fitz.Document] | None:
    """The ONE ``encryption=KEEP`` round trip this module performs per
    session open, on the LIVE document -- shared by two consumers so the
    one-``tobytes()``-per-session performance contract
    (``test_open_preview_session_takes_exactly_one_snapshot``) still holds:

    1. Its success/failure IS the live V0e reopen-probe verdict
       (:func:`_reopen_probe_verdict` reads it back off this result) --
       byte-for-byte the same probe ``verify.py``'s live commit runs (same
       ``encryption=KEEP`` call, same exception set).  The scratch handed
       to ``PlanPreviewRenderer`` is the DECRYPTED session snapshot
       (``PDF_ENCRYPT_NONE``), so it cannot see a KEEP round-trip failure
       on an encrypted document at all; this is the only place that
       failure is observable before commit.
    2. Its bytes/clone are exactly what :func:`_session_snapshot_bytes`
       needs to build the session's decrypted scratch -- a second,
       independent ``tobytes(encryption=KEEP)`` call would double the
       per-session serialization cost for no new information.

    Never mutates ``doc``'s crypt state (``KEEP``, same non-poisoning path
    ``TieredCommitEngine._build_scratch_copy`` already uses).  Returns
    ``None`` (never raises) on any KEEP round-trip failure.
    """
    try:
        keep_bytes = doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        clone = fitz.open("pdf", keep_bytes)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    return keep_bytes, clone


def _reopen_probe_verdict(round_trip: tuple[bytes, fitz.Document] | None) -> bool:
    """True exactly when :func:`_live_keep_round_trip` succeeded -- the
    live V0e certificate, cached for the whole session."""
    return round_trip is not None


def _session_snapshot_bytes(
    round_trip: tuple[bytes, fitz.Document] | None, password: str | None
) -> bytes | None:
    """Decrypted, xref-stable bytes for the scratch copy — or ``None``.

    ``round_trip`` is the ALREADY-COMPUTED :func:`_live_keep_round_trip`
    result: this function performs no ``tobytes()`` call of its own on the
    live document.  Never calls ``tobytes()`` with the default (decrypting)
    encryption on the live handle.  On an *encrypted* document that
    silently poisons the handle's internal crypt state (a PyMuPDF AES
    quirk), so the user's next ``encryption=KEEP`` save writes content
    streams that no longer decrypt — reported as success, discovered as
    blank pages on reopen.  Decrypting the already-KEEP-encrypted clone
    instead is safe: its crypt state nobody depends on.  ``KEEP`` is a
    no-op for unencrypted documents, so one path covers both.

    Returns ``None`` (never raises) when the round trip itself already
    failed, or when an encrypted document's clone cannot be
    re-authenticated; the caller degrades to the legacy preview rather
    than claiming exactness.
    """
    if round_trip is None:
        return None
    keep_bytes, clone = round_trip
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
    # The one KEEP round trip this session performs -- feeds BOTH the live
    # V0e reopen-probe verdict (cached for every keystroke's render call)
    # and the scratch snapshot bytes below.
    round_trip = _live_keep_round_trip(doc)
    reopen_probe_ok = _reopen_probe_verdict(round_trip)
    snapshot_bytes = _session_snapshot_bytes(round_trip, password)
    if snapshot_bytes is None:
        return None
    return PreviewSessionInput(
        session_key=session_key,
        page_number=page_number,
        snapshot_bytes=snapshot_bytes,
        page_fingerprint=page_fingerprint(doc, page),
        page_has_pending_maintenance=page_has_pending_maintenance,
        max_tier=max_tier,
        reopen_probe_ok=reopen_probe_ok,
    )


class PlanPreviewRenderer:
    """Render prepared Tier 0 plans on one session-scoped scratch document.

    Not thread-safe: exactly one thread (the preview worker) may call
    ``render``/``close``.  The scratch document is opened lazily so it is
    created in the calling thread, and every render reverts its patch so
    the scratch stays DECODED-byte-identical to the session snapshot (P3-C:
    the reverted content stream's own storage encoding stays permanently
    uncompressed after the first keystroke -- see the ``compress=False``
    comments in ``render`` -- which no reader of this scratch observes).
    """

    def __init__(self, session: PreviewSessionInput) -> None:
        self._session = session
        self._scratch: fitz.Document | None = None
        self._registry: DocumentFontRegistry | None = None
        # P3-B: one single-slot replay-evidence cache per preview session
        # -- the retained Shape A PageReplay for THE scratch page's current
        # content generation.  Reuse is gated by lookup-time
        # pull-validation inside prepare_plan, never by this object's
        # lifetime; close() releases it with the session.
        self._evidence_cache = ReplayEvidenceCache()
        self._pre_state_baseline = PreStateBaselineCache()

    def _ensure_scratch(self) -> tuple[fitz.Document, DocumentFontRegistry]:
        if self._scratch is None:
            self._scratch = fitz.open("pdf", self._session.snapshot_bytes)
            self._registry = DocumentFontRegistry(self._scratch)
        assert self._registry is not None
        return self._scratch, self._registry

    def render(self, request: PlanPreviewRequest) -> PlanPreviewResult:
        """Prepare, verify, splice, rasterize, revert on the scratch copy."""

        def _rejection(reason: str) -> PlanPreviewResult:
            # Mirror the commit path's ``_reconstruction_aware_reason``:
            # a bare NO_MATCH claims the document lacks the text, which is
            # only honest when ``target_text`` is a verbatim quotation. The
            # controller flags a reconstructed target once per session, so
            # the same condition relabels the same way here.
            if (
                reason == RejectReason.NO_MATCH
                and request.whitespace_reconstructed
            ):
                reason = RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
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
            evidence_cache=self._evidence_cache,
        )
        if isinstance(plan, PlanRejection):
            return _rejection(plan.reason)

        is_tier1 = plan.tier.value == 1
        if is_tier1:
            # Re-prove the font-resource reuse on the scratch BEFORE
            # declaring the candidate verified -- the same gate
            # ``TieredCommitEngine.prepare``/``.commit`` run, which
            # ``prepare_plan`` alone does not enforce (Task 11 F3 Hole 2).
            # Zero mutation on failure: this runs before any splice.
            font_outcome = build_tier1_font_outcome(
                scratch,
                page,
                resource_name=plan.font_resource,
                source_font_xref=plan.font_xref,
                written_font_xref=plan.font_xref,
            )
            if font_outcome.action != FontResourceAction.SOURCE_RESOURCE_REUSED:
                logger.info(
                    "preview tier1 candidate refuted on scratch: "
                    "resource /%s reports %s",
                    plan.font_resource,
                    font_outcome.action,
                )
                return _rejection(RejectReason.FONT_RESOURCE_NOT_PROVEN)

        patchset = PatchSet(
            page_xref=plan.page_xref,
            replacements=(plan.replacement,),
            expected_page_fingerprint=plan.page_fingerprint,
        )
        pre_state = self._pre_state_baseline.capture(scratch, page, plan)
        try:
            # P3-C: this scratch is never saved or tobytes()'d -- every
            # splice is reverted before render() returns (below), and
            # close() just drops the handle. Flate compression on the
            # write is therefore pure cost with no reader; disabling it
            # only here (never on the live commit path) is what turns the
            # dominant per-keystroke cost (~75% of render time on dense
            # pages) into a near-zero one. Decoded content, fingerprints,
            # and replay-evidence digests are unaffected either way.
            applied = apply_patchset(scratch, page, patchset, compress=False)
        except (StalePlanError, SpliceError) as exc:
            logger.warning("plan preview splice failed: %s", type(exc).__name__)
            return _rejection("preview_splice_failed")
        post: PageInterpretation | None = None
        try:
            post = interpret_page(page)
            verify_fn = verify_tier1_commit if is_tier1 else verify_tier0_commit
            verification = verify_fn(
                scratch,
                page,
                plan,
                pre_state,
                interpretation=post,
                reopen_probe=False,
                cached_reopen_probe_ok=self._session.reopen_probe_ok,
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
            pixmap = post.pixmap(
                matrix=fitz.Matrix(scale, scale), clip=clip
            )
            png_bytes = pixmap.tobytes("png")
        finally:
            try:
                if post is not None:
                    post.release()
            finally:
                try:
                    applied.revert(scratch, compress=False)  # P3-C: see apply above
                except BaseException:
                    self._pre_state_baseline.clear()
                    raise
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
        self._pre_state_baseline.clear()
        self._evidence_cache.clear()
        if self._scratch is not None:
            self._scratch.close()
            self._scratch = None
            self._registry = None
