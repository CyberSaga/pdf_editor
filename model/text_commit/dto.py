"""Immutable DTOs shared across the text-commit engine.

Qt-free by construction (model layer). View-facing request/report types
live in ``model/edit_requests.py``; these are engine-internal contracts.
"""
from __future__ import annotations

from dataclasses import dataclass


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
