"""TieredCommitEngine: scratch-first prepare, stale-checked commit.

``prepare`` classifies the edit and proves the candidate on a scratch copy
of the document — the live document is never touched during preparation.
``commit`` revalidates the page fingerprint, applies exactly one validated
PatchSet, re-verifies on the live document, and reverts on any failure.

Tier 1 does not exist yet (flag-gated future work); everything that is
not Tier 0 is rejected here and stays with the legacy engine.
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
)
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_tier0_plan
from model.text_commit.verify import (
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
)

logger = logging.getLogger(__name__)


def _rejection_outcome(status: CommitStatus, reason: str, detail: str) -> CommitOutcome:
    return CommitOutcome(
        status=status,
        tier=None,
        fallback_chain=("tier0:" + reason,),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=detail,
        allows_external_reflow=False,
    )


class TieredCommitEngine:
    """One engine per open document; owns the font registry."""

    def __init__(self, doc: fitz.Document) -> None:
        self._doc = doc
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
    ) -> PreparedEdit | PlanRejection:
        """Classify, then prove the candidate on a scratch document."""
        plan = prepare_tier0_plan(
            self._doc,
            page,
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
        scratch = fitz.open("pdf", self._doc.tobytes())
        try:
            scratch_page = scratch[page.number]
            pre_state = capture_page_state(scratch, scratch_page, plan)
            try:
                apply_patchset(scratch, scratch_page, self._patchset(plan))
            except (StalePlanError, SpliceError) as exc:
                return PlanRejection(
                    RejectReason.VERIFICATION_FAILED,
                    f"candidate failed to apply on scratch: {exc}",
                )
            result = verify_tier0_commit(scratch, scratch_page, plan, pre_state)
            if isinstance(result, VerificationFailure):
                logger.info(
                    "tier0 candidate refuted on scratch: %s (%s)",
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
            )

        pre_state = capture_page_state(doc, page, prepared)
        try:
            applied = apply_patchset(doc, page, self._patchset(prepared))
        except StalePlanError as exc:
            return _rejection_outcome(
                CommitStatus.STALE_PLAN, RejectReason.STALE_PLAN, str(exc)
            )
        except SpliceError as exc:
            return _rejection_outcome(
                CommitStatus.STALE_PLAN, RejectReason.STALE_PLAN, str(exc)
            )

        result = verify_tier0_commit(doc, page, prepared, pre_state)
        if isinstance(result, VerificationFailure):
            applied.revert(doc)
            logger.warning(
                "tier0 live verification failed, reverted: %s (%s)",
                result.reason,
                result.detail,
            )
            return _rejection_outcome(
                CommitStatus.FAILED, result.reason, result.detail
            )

        self.registry.bump_generation()
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
