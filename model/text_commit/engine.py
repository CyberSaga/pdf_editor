"""TieredCommitEngine: scratch-first prepare, stale-checked commit.

``prepare`` classifies the edit and proves the candidate on a scratch copy
of the document — the live document is never touched during preparation.
``commit`` revalidates the page fingerprint, applies exactly one validated
PatchSet, re-verifies on the live document, and reverts on any failure.

Tier 1 (Task 11 Slice 1, ``max_tier=1``) is flag-gated opt-in: transplant+
kern candidates get the same scratch-first prepare -> live commit -> verify
-> revert pipeline as Tier 0, dispatched by ``prepared.tier``.
"""
from __future__ import annotations

import logging

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.dto import (
    CommitOutcome,
    CommitStatus,
    CommitTier,
    FontOutcome,
    FontResourceAction,
    RejectReason,
)
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
    build_tier1_font_outcome,
)
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_plan
from model.text_commit.verify import (
    VerificationFailure,
    capture_page_state,
    growth_zone_is_uniform,
    verify_tier0_commit,
    verify_tier1_commit,
)

logger = logging.getLogger(__name__)


def _rejection_outcome(
    status: CommitStatus, reason: str, detail: str, *, tier: int = 0
) -> CommitOutcome:
    return CommitOutcome(
        status=status,
        tier=None,
        fallback_chain=(f"tier{tier}:{reason}",),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=detail,
        allows_external_reflow=False,
    )


class TieredCommitEngine:
    """One engine per open document; owns the font registry."""

    def __init__(self, doc: fitz.Document, *, password: str | None = None) -> None:
        self._doc = doc
        self._password = password
        self.registry = DocumentFontRegistry(doc)

    # ------------------------------------------------------------ prepare

    def prepare(
        self,
        page: fitz.Page,
        *,
        target_text: str,
        replacement_text: str,
        expected_origin: tuple[float, float] | None,
        target_bbox: tuple[float, float, float, float] | None = None,
        style_overrides: StyleOverrides | None = None,
        new_rect: object | None = None,
        page_has_pending_maintenance: bool = False,
        max_tier: int = 0,
    ) -> PreparedEdit | PlanRejection:
        """Classify, then prove the candidate on a scratch document."""
        plan = prepare_plan(
            self._doc,
            page,
            max_tier=max_tier,
            target_text=target_text,
            replacement_text=replacement_text,
            expected_origin=expected_origin,
            target_bbox=target_bbox,
            registry=self.registry,
            style_overrides=style_overrides,
            new_rect=new_rect,
            page_has_pending_maintenance=page_has_pending_maintenance,
        )
        if isinstance(plan, PlanRejection):
            return plan

        # Scratch-first proof: tobytes() preserves xref numbering and decoded
        # stream bytes, so the plan's offsets are valid on the copy.
        scratch = self._build_scratch_copy()
        if scratch is None:
            return PlanRejection(
                RejectReason.VERIFICATION_FAILED,
                "could not build an authenticated scratch copy to prove the candidate on",
            )
        try:
            scratch_page = scratch[page.number]
            pre_state = capture_page_state(scratch, scratch_page, plan)
            if plan.growth_bbox_page is not None and not growth_zone_is_uniform(
                scratch_page, plan.growth_bbox_page
            ):
                return PlanRejection(
                    RejectReason.GROWTH_EXCEEDS_BLANK_REGION,
                    "growth zone not visually blank on scratch pre-state",
                )
            try:
                apply_patchset(scratch, scratch_page, self._patchset(plan))
            except (StalePlanError, SpliceError) as exc:
                return PlanRejection(
                    RejectReason.VERIFICATION_FAILED,
                    f"candidate failed to apply on scratch: {exc}",
                )
            verify_fn = verify_tier1_commit if plan.tier >= 1 else verify_tier0_commit
            result = verify_fn(scratch, scratch_page, plan, pre_state)
            if isinstance(result, VerificationFailure):
                logger.info(
                    "tier%s candidate refuted on scratch: %s (%s)",
                    plan.tier,
                    result.reason,
                    result.detail,
                )
                return PlanRejection(result.reason, result.detail)
        finally:
            scratch.close()
        return plan

    # ------------------------------------------------------------- commit

    def commit(self, prepared: PreparedEdit) -> CommitOutcome:
        """Apply the prepared candidate to the live document, verified."""
        doc = self._doc
        try:
            page = doc[self._page_number(prepared.page_xref)]
        except (KeyError, IndexError, ValueError):
            return _rejection_outcome(
                CommitStatus.STALE_PLAN,
                RejectReason.STALE_PLAN,
                "target page no longer exists",
                tier=prepared.tier,
            )

        pre_state = capture_page_state(doc, page, prepared)
        if prepared.growth_bbox_page is not None and not growth_zone_is_uniform(
            page, prepared.growth_bbox_page
        ):
            # Live re-check, not redundant with prepare()'s scratch check:
            # page_fingerprint does not cover annotation appearance-stream
            # content, only xref+rect, so an appearance changed between
            # prepare() and commit() can leave scratch and live fingerprint-
            # identical but raster-different in the growth zone. Nothing has
            # been applied yet, so no revert is needed.
            return _rejection_outcome(
                CommitStatus.FAILED,
                RejectReason.GROWTH_EXCEEDS_BLANK_REGION,
                "growth zone not visually blank on live pre-state",
                tier=prepared.tier,
            )
        try:
            applied = apply_patchset(doc, page, self._patchset(prepared))
        except StalePlanError as exc:
            return _rejection_outcome(
                CommitStatus.STALE_PLAN,
                RejectReason.STALE_PLAN,
                str(exc),
                tier=prepared.tier,
            )
        except SpliceError as exc:
            return _rejection_outcome(
                CommitStatus.STALE_PLAN,
                RejectReason.STALE_PLAN,
                str(exc),
                tier=prepared.tier,
            )

        verify_fn = verify_tier1_commit if prepared.tier >= 1 else verify_tier0_commit
        result = verify_fn(doc, page, prepared, pre_state)
        if isinstance(result, VerificationFailure):
            applied.revert(doc)
            logger.warning(
                "tier%s live verification failed, reverted: %s (%s)",
                prepared.tier,
                result.reason,
                result.detail,
            )
            return _rejection_outcome(
                CommitStatus.FAILED, result.reason, result.detail, tier=prepared.tier
            )

        self.registry.bump_generation()
        if prepared.tier >= 1:
            font_outcome = build_tier1_font_outcome(
                doc,
                page,
                resource_name=prepared.font_resource,
                source_font_xref=prepared.font_xref,
                written_font_xref=prepared.font_xref,
            )
            return CommitOutcome(
                status=CommitStatus.COMMITTED,
                tier=CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE,
                fallback_chain=(f"tier0:{prepared.tier0_fallback_reason}",),
                warnings=("compensated_transplant_kern",),
                font_outcomes=(font_outcome,),
                verified_properties=result,
                degraded_reason=None,
                allows_external_reflow=False,
            )
        return CommitOutcome(
            status=CommitStatus.COMMITTED,
            tier=CommitTier.TIER0_LOSSLESS_STREAM_PATCH,
            fallback_chain=(),
            warnings=(),
            font_outcomes=(
                FontOutcome(
                    resource_name=prepared.font_resource,
                    source_font_xref=prepared.font_xref,
                    written_font_xref=prepared.font_xref,
                    action=FontResourceAction.SOURCE_RESOURCE_REUSED,
                ),
            ),
            verified_properties=result,
            degraded_reason=None,
            allows_external_reflow=False,
        )

    # ------------------------------------------------------------ helpers

    def _build_scratch_copy(self) -> fitz.Document | None:
        """Build a throwaway, content-readable clone of the live document.

        Never calls ``tobytes()`` with the default (decrypting) encryption
        directly on the live handle: on an *encrypted* document that
        silently poisons its crypt state (a measured PyMuPDF AES quirk --
        the same one ``PDFModel._decrypted_snapshot_bytes`` already guards
        against for worker/print snapshots), so a later ``encryption=KEEP``
        save on that same handle would write content streams that no longer
        decrypt, even though the save itself reports success. Route every
        scratch build through an ``encryption=KEEP`` snapshot and
        re-authenticate the throwaway clone instead -- the live handle's
        crypt state is never touched either way. ``KEEP`` is a no-op for
        unencrypted documents, so this is one code path for both cases.

        Returns ``None`` (never raises) when an encrypted document's clone
        cannot be re-authenticated -- callers turn that into a stable
        ``PlanRejection`` rather than letting the failure escape as an
        exception.
        """
        keep_bytes = self._doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        clone = fitz.open("pdf", keep_bytes)
        if clone.needs_pass:
            if self._password is None or clone.authenticate(self._password) == 0:
                clone.close()
                return None
        return clone

    def _patchset(self, prepared: PreparedEdit) -> PatchSet:
        return PatchSet(
            page_xref=prepared.page_xref,
            replacements=(prepared.replacement,),
            expected_page_fingerprint=prepared.page_fingerprint,
        )

    def _page_number(self, page_xref: int) -> int:
        for number in range(self._doc.page_count):
            if self._doc.page_xref(number) == page_xref:
                return number
        raise KeyError(page_xref)
