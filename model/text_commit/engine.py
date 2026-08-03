"""TieredCommitEngine: scratch-first prepare, stale-checked commit.

``prepare`` classifies the edit and proves the candidate on a scratch copy
of the document — the live document is never touched during preparation.
``commit`` revalidates the page fingerprint, applies exactly one validated
PatchSet, re-verifies on the live document, and reverts on any failure.

Tier 1 (Task 11 Slice 1) is reached only when ``max_tier >= 1`` and Tier 0
refuses with ``ADVANCE_MISMATCH``; the default ``max_tier=0`` keeps every
existing construction on Tier 0 only (the flag-off guarantee).
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
    verify_tier0_commit,
    verify_tier1_commit,
)

logger = logging.getLogger(__name__)


def _rejection_outcome(
    status: CommitStatus,
    reason: str,
    detail: str,
    *,
    chain: tuple[str, ...] | None = None,
) -> CommitOutcome:
    return CommitOutcome(
        status=status,
        tier=None,
        fallback_chain=chain if chain is not None else ("tier0:" + reason,),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=detail,
        allows_external_reflow=False,
    )


def _tier1_chain(reason: str) -> tuple[str, ...]:
    """A Tier 1 commit is only ever reached by escalating a Tier 0
    ``ADVANCE_MISMATCH`` refusal (``plan._TIER1_ESCALATION_REASONS``), so
    every Tier 1 failure honestly reports both stages."""
    return (f"tier0:{RejectReason.ADVANCE_MISMATCH}", f"tier1:{reason}")


class TieredCommitEngine:
    """One engine per open document; owns the font registry."""

    def __init__(
        self, doc: fitz.Document, *, password: str | None = None, max_tier: int = 0
    ) -> None:
        self._doc = doc
        self._password = password
        self._max_tier = max_tier
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
        plan = prepare_plan(
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
            max_tier=self._max_tier,
        )
        if isinstance(plan, PlanRejection):
            return plan

        is_tier1 = plan.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        if is_tier1:
            font_outcome = build_tier1_font_outcome(
                self._doc,
                page,
                resource_name=plan.font_resource,
                source_font_xref=plan.font_xref,
                written_font_xref=plan.font_xref,
            )
            if font_outcome.action != FontResourceAction.SOURCE_RESOURCE_REUSED:
                return PlanRejection(
                    RejectReason.FONT_RESOURCE_NOT_PROVEN,
                    f"resource /{plan.font_resource} reports {font_outcome.action}",
                )

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
            try:
                apply_patchset(scratch, scratch_page, self._patchset(plan))
            except (StalePlanError, SpliceError) as exc:
                return PlanRejection(
                    RejectReason.VERIFICATION_FAILED,
                    f"candidate failed to apply on scratch: {exc}",
                )
            verify_fn = verify_tier1_commit if is_tier1 else verify_tier0_commit
            result = verify_fn(scratch, scratch_page, plan, pre_state)
            if isinstance(result, VerificationFailure):
                logger.info(
                    "tier%s candidate refuted on scratch: %s (%s)",
                    plan.tier.value,
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

        is_tier1 = prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        if is_tier1:
            # Re-proven on the LIVE document: the resource table can change
            # between prepare and commit. Zero mutation on failure -- this
            # runs before apply_patchset.
            font_outcome = build_tier1_font_outcome(
                doc,
                page,
                resource_name=prepared.font_resource,
                source_font_xref=prepared.font_xref,
                written_font_xref=prepared.font_xref,
            )
            if font_outcome.action != FontResourceAction.SOURCE_RESOURCE_REUSED:
                return _rejection_outcome(
                    CommitStatus.FAILED,
                    RejectReason.FONT_RESOURCE_NOT_PROVEN,
                    f"resource /{prepared.font_resource} reports {font_outcome.action}",
                    chain=_tier1_chain(RejectReason.FONT_RESOURCE_NOT_PROVEN),
                )
        else:
            font_outcome = FontOutcome(
                resource_name=prepared.font_resource,
                source_font_xref=prepared.font_xref,
                written_font_xref=prepared.font_xref,
                action=FontResourceAction.SOURCE_RESOURCE_REUSED,
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

        verify_fn = verify_tier1_commit if is_tier1 else verify_tier0_commit
        try:
            result = verify_fn(doc, page, prepared, pre_state)
        except Exception:
            applied.revert(doc)
            logger.exception(
                "tier%s live verifier raised, reverted",
                prepared.tier.value,
            )
            raise
        if isinstance(result, VerificationFailure):
            applied.revert(doc)
            logger.warning(
                "tier%s live verification failed, reverted: %s (%s)",
                prepared.tier.value,
                result.reason,
                result.detail,
            )
            chain = _tier1_chain(result.reason) if is_tier1 else None
            return _rejection_outcome(
                CommitStatus.FAILED, result.reason, result.detail, chain=chain
            )

        self.registry.bump_generation()
        return CommitOutcome(
            status=CommitStatus.COMMITTED,
            tier=prepared.tier,
            fallback_chain=(),
            warnings=("tier1_ink_growth",) if prepared.has_ink_growth else (),
            font_outcomes=(font_outcome,),
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
