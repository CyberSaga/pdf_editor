"""Immutable DTOs shared across the text-commit engine.

Qt-free by construction (model layer). View-facing request/report types
live in ``model/edit_requests.py``; these are engine-internal contracts.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum

logger = logging.getLogger(__name__)


class RejectReason:
    """Stable reason codes for refusing a high-fidelity mapping or plan.

    These strings are telemetry- and UI-facing contracts: rename only with
    a migration.  A refusal always carries one of these — never a guess.
    """

    MALFORMED_STREAM = "malformed_stream"
    NO_MATCH = "no_source_match"
    AMBIGUOUS_MATCH = "ambiguous_source_match"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    TARGET_IN_FORM_XOBJECT = "target_in_form_xobject"
    UNSUPPORTED_TEXT_STATE = "unsupported_text_state"
    UNTRACKED_ADVANCE = "untracked_advance"
    UNDECODABLE_TARGET = "undecodable_target"
    FONT_TYPE3 = "font_type3"
    FONT_UNSUPPORTED_ENCODING = "font_unsupported_encoding"
    FONT_CUSTOM_DIFFERENCES = "font_custom_differences"
    FONT_FACE_UNAVAILABLE = "font_face_unavailable"
    FONT_WIDTHS_INCOMPLETE = "font_widths_incomplete"
    NOT_SINGLE_LITERAL_TJ = "not_single_literal_tj"
    MULTI_SPAN_TARGET = "multi_span_target"
    # The engine's own target string was assembled by joining word runs and
    # could not be found in the stream.  Distinct from NO_MATCH, which
    # asserts the *document* lacks the text: here the reconstruction is the
    # suspect, because run parsing strips whitespace and cannot reproduce a
    # source gap wider than one space.
    TARGET_RECONSTRUCTION_UNVERIFIED = "target_reconstruction_unverified"
    STYLE_OVERRIDE_PRESENT = "style_override_present"
    GEOMETRY_OVERRIDE_PRESENT = "geometry_override_present"
    MULTILINE_REPLACEMENT = "multiline_replacement"
    EMPTY_REPLACEMENT = "empty_replacement"
    NO_CHANGE = "no_change"
    ADVANCE_MISMATCH = "advance_mismatch"
    ENCODING_FAILED = "encoding_failed"
    SIGNED_OR_WIDGET_TARGET = "signed_or_widget_target"
    PENDING_MAINTENANCE = "pending_page_maintenance"
    VERIFICATION_FAILED = "verification_failed"
    STALE_PLAN = "stale_plan"
    # Task 11 Slice 1 (Tier 1 kern-compensated transplant): each is a NEW
    # name on purpose (Task 10a, TODOS.md:418) -- reusing an existing reason
    # with existing emission sites lets a test survive deletion of its own
    # gate.
    UNSUPPORTED_SHOW_OPERATOR = "unsupported_show_operator"
    SHARED_CONTENT_STREAM = "shared_content_stream"
    GROWTH_REGION_NOT_BLANK = "growth_region_not_blank"
    GROWTH_OUTSIDE_PAGE = "growth_outside_page"
    FONT_RESOURCE_NOT_PROVEN = "font_resource_not_proven"
    # Task 12 P0-A: replay refused to tokenize a page whose decoded content
    # streams exceed the safe-replay budget (the lexer materializes ~0.77
    # tokens per byte).  A resource refusal, not a stream-shape verdict --
    # it must never be collapsed into MALFORMED_STREAM or NO_MATCH.
    CONTENT_STREAM_TOO_LARGE = "content_stream_too_large_for_safe_replay"


class CommitStatus(str, Enum):
    COMMITTED = "committed"
    DEGRADED_COMMITTED = "degraded_committed"
    REJECTED = "rejected"
    STALE_PLAN = "stale_plan"
    FAILED = "failed"


class CommitTier(IntEnum):
    TIER0_LOSSLESS_STREAM_PATCH = 0
    TIER1_REBUILD_WITH_VALIDATED_FACE = 1
    TIER2_LEGACY = 2


# The tiers whose commit is byte-provable and undo-reversible via a single
# validated PatchSet -- as opposed to Tier 2 (legacy redact+reinsert), whose
# undo/redo can only replay a lossier page-level snapshot. Consulted by
# edit_commands.py's reversal-capture gate so a Tier 1 commit gets the same
# high-fidelity undo/redo path as Tier 0.
HIGH_FIDELITY_TIERS: tuple[CommitTier, ...] = (
    CommitTier.TIER0_LOSSLESS_STREAM_PATCH,
    CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE,
)


class FontResourceAction:
    """How the committed text's font resource relates to the source font.

    No substitution is ever silent: every commit reports one of these per
    style run, and anything but SOURCE_RESOURCE_REUSED surfaces in the UI.
    """

    SOURCE_RESOURCE_REUSED = "source_resource_reused"
    VALIDATED_FACE_EMBEDDED = "validated_face_embedded"
    SYSTEM_FACE_SUBSTITUTED = "system_face_substituted"
    LEGACY_BASE14_SUBSTITUTED = "legacy_base14_substituted"


@dataclass(frozen=True)
class FontOutcome:
    resource_name: str
    source_font_xref: int
    written_font_xref: int | None
    action: str  # a FontResourceAction constant
    missing_glyphs: str = ""


@dataclass(frozen=True)
class CommitOutcome:
    """Full, honest record of what one commit did (stored in history)."""

    status: CommitStatus
    tier: CommitTier | None
    fallback_chain: tuple[str, ...]
    warnings: tuple[str, ...]
    font_outcomes: tuple[FontOutcome, ...]
    verified_properties: tuple[str, ...]
    degraded_reason: str | None
    allows_external_reflow: bool


_ENGINE_VALUES = ("legacy", "shadow", "tiered")
_PREVIEW_VALUES = ("legacy", "plan")
_TELEMETRY_VALUES = ("off", "local")


@dataclass(frozen=True)
class TextCommitSettings:
    """Qt-free feature-flag DTO, injected into PDFModel at composition.

    Defaults keep the legacy engine fully in charge; every rollout stage
    is an explicit opt-in via TEXT_COMMIT_* environment variables.
    """

    engine: str = "legacy"
    max_tier: int = 0
    strict: bool = False
    preview: str = "legacy"
    telemetry: str = "off"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> TextCommitSettings:
        """Parse TEXT_COMMIT_* variables; invalid values fall back loudly."""

        def _choice(name: str, valid: tuple[str, ...], default: str) -> str:
            value = env.get(name, default)
            if value not in valid:
                logger.warning("%s=%r invalid; using %r", name, value, default)
                return default
            return value

        def _flag(name: str) -> bool:
            value = env.get(name, "0")
            if value not in ("0", "1"):
                logger.warning("%s=%r invalid; using 0", name, value)
                return False
            return value == "1"

        max_tier_raw = env.get("TEXT_COMMIT_MAX_TIER", "0")
        if max_tier_raw not in ("0", "1"):
            logger.warning(
                "TEXT_COMMIT_MAX_TIER=%r invalid; using 0", max_tier_raw
            )
            max_tier_raw = "0"

        return cls(
            engine=_choice("TEXT_COMMIT_ENGINE", _ENGINE_VALUES, "legacy"),
            max_tier=int(max_tier_raw),
            strict=_flag("TEXT_COMMIT_STRICT"),
            preview=_choice("TEXT_COMMIT_PREVIEW", _PREVIEW_VALUES, "legacy"),
            telemetry=_choice(
                "TEXT_COMMIT_TELEMETRY", _TELEMETRY_VALUES, "off"
            ),
        )


def is_real_fallback_commit(outcome: CommitOutcome | None) -> bool:
    """True when ``outcome`` is a commit that genuinely fell back from an
    attempted higher-fidelity tier to the legacy engine -- as opposed to
    the shipped-default baseline (chain == ``("legacy",)``, which every
    successful edit gets under ``engine="legacy"`` and is not a failed
    fidelity promise). Shared by the Controller's degrade-notice gate
    (``PDFController._is_notifiable_degrade``) and ``EditTextCommand``'s
    redo-reprompt gate (Task 12 P0-C) so the two decisions about the same
    outcome shape can never drift apart."""
    return (
        outcome is not None
        and outcome.status is CommitStatus.DEGRADED_COMMITTED
        and outcome.fallback_chain != ("legacy",)
    )


def legacy_commit_outcome() -> CommitOutcome:
    """Outcome describing a legacy redact+reinsert commit (Tier 2)."""
    return CommitOutcome(
        status=CommitStatus.DEGRADED_COMMITTED,
        tier=CommitTier.TIER2_LEGACY,
        fallback_chain=("legacy",),
        warnings=("legacy_engine_fidelity_untracked",),
        font_outcomes=(),
        verified_properties=("text_similarity",),
        degraded_reason="legacy_redact_reinsert",
        allows_external_reflow=True,
    )


@dataclass(frozen=True)
class StreamReplacement:
    """One byte-range replacement in a decoded content stream.

    ``start``/``end`` are offsets into the *decoded* stream bytes of
    ``stream_xref`` as they were when the plan was prepared.
    ``expected_bytes`` must equal the source slice and
    ``expected_stream_digest`` the SHA-256 of the whole decoded stream at
    apply time, otherwise the splice refuses to run (stale plan).
    """

    stream_xref: int
    start: int
    end: int
    expected_bytes: bytes
    replacement_bytes: bytes
    expected_stream_digest: str
