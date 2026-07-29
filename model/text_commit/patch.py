"""Reversible low-level PatchSet application for the text-commit engine.

The only mutation primitive of the high-fidelity tiers: validate the page
fingerprint, splice the declared byte ranges (which re-checks per-stream
digests and expected bytes), and update the stream objects in place.  The
returned handle can revert everything from the captured prior bytes.

Forbidden here by design: redaction, ``clean_contents``, annotation
save/recreate, and any neighbor rewriting.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass

import fitz

from model.text_commit.dto import StreamReplacement
from model.text_commit.inspect import page_fingerprint, read_page_streams
from model.text_commit.pdf_lexer import SpliceError, splice_stream

logger = logging.getLogger(__name__)


class StalePlanError(ValueError):
    """The document changed since the plan was prepared; nothing mutated."""


@dataclass(frozen=True)
class PatchSet:
    page_xref: int
    replacements: tuple[StreamReplacement, ...]
    expected_page_fingerprint: str


@dataclass(frozen=True)
class AppliedPatch:
    """Handle for reverting an applied patch (prior decoded stream bytes)."""

    page_xref: int
    prior_streams: tuple[tuple[int, bytes], ...]

    def revert(self, doc: fitz.Document) -> None:
        for xref, data in self.prior_streams:
            doc.update_stream(xref, data)


def apply_patchset(
    doc: fitz.Document, page: fitz.Page, patchset: PatchSet
) -> AppliedPatch:
    """Validate and apply ``patchset`` to the live document.

    Raises :class:`StalePlanError` (before any mutation) when the page
    fingerprint no longer matches, and :class:`SpliceError` when a stream's
    digest or expected bytes drifted.  All new stream contents are computed
    before the first ``update_stream`` call, so validation failures leave
    the document byte-identical.
    """
    if page.xref != patchset.page_xref:
        raise StalePlanError(
            f"patchset targets page xref {patchset.page_xref}, got {page.xref}"
        )
    fingerprint = page_fingerprint(doc, page)
    if fingerprint != patchset.expected_page_fingerprint:
        raise StalePlanError("page fingerprint changed since the plan was prepared")

    by_stream: dict[int, list[StreamReplacement]] = defaultdict(list)
    for replacement in patchset.replacements:
        by_stream[replacement.stream_xref].append(replacement)

    prior: list[tuple[int, bytes]] = []
    updated: list[tuple[int, bytes]] = []
    for stream_xref, replacements in by_stream.items():
        current = doc.xref_stream(stream_xref) or b""
        new_bytes = splice_stream(current, replacements)  # validates, or raises
        prior.append((stream_xref, current))
        updated.append((stream_xref, new_bytes))

    for stream_xref, new_bytes in updated:
        doc.update_stream(stream_xref, new_bytes)
    logger.debug(
        "apply_patchset: page=%s streams=%s replacements=%s",
        patchset.page_xref,
        [x for x, _ in updated],
        len(patchset.replacements),
    )
    return AppliedPatch(page_xref=patchset.page_xref, prior_streams=tuple(prior))


def build_reversal_patchset(
    doc: fitz.Document,
    page: fitz.Page,
    pre_streams: tuple[tuple[int, bytes], ...],
    pre_fingerprint: str,
) -> tuple[PatchSet, PatchSet] | None:
    """Diff ``pre_streams`` against the page's *current* content streams and
    build a forward/inverse full-stream :class:`PatchSet` pair.

    ``pre_streams`` (as returned by :func:`~model.text_commit.inspect.
    read_page_streams`) must have been captured before the edit that already
    ran; ``pre_fingerprint`` is the page fingerprint at that same moment.
    Command-level undo/redo uses the pair to replay a Tier 0 commit's exact
    validated intent -- ``forward`` reproduces the committed (post-edit)
    state from the pre-edit source state; ``inverse`` reproduces the source
    state from the committed state -- without re-running the classify/
    prepare pipeline, and each side is fingerprint-gated by
    :func:`apply_patchset` exactly like the original commit was.

    Returns ``None`` when the observed diff is not exactly one changed
    stream: Tier 0 only ever patches a single content stream, so anything
    else means this helper cannot faithfully reverse the edit and callers
    must fall back to their own (lossier) undo/redo path instead of
    trusting a guess.
    """
    post_streams = dict(read_page_streams(doc, page))
    pre_map = dict(pre_streams)
    changed = [xref for xref, data in pre_map.items() if post_streams.get(xref) != data]
    if len(changed) != 1 or changed[0] not in post_streams:
        return None

    stream_xref = changed[0]
    pre_bytes = pre_map[stream_xref]
    post_bytes = post_streams[stream_xref]
    post_fingerprint = page_fingerprint(doc, page)

    forward = StreamReplacement(
        stream_xref=stream_xref,
        start=0,
        end=len(pre_bytes),
        expected_bytes=pre_bytes,
        replacement_bytes=post_bytes,
        expected_stream_digest=hashlib.sha256(pre_bytes).hexdigest(),
    )
    inverse = StreamReplacement(
        stream_xref=stream_xref,
        start=0,
        end=len(post_bytes),
        expected_bytes=post_bytes,
        replacement_bytes=pre_bytes,
        expected_stream_digest=hashlib.sha256(post_bytes).hexdigest(),
    )
    forward_patchset = PatchSet(
        page_xref=page.xref, replacements=(forward,), expected_page_fingerprint=pre_fingerprint
    )
    inverse_patchset = PatchSet(
        page_xref=page.xref, replacements=(inverse,), expected_page_fingerprint=post_fingerprint
    )
    return forward_patchset, inverse_patchset


__all__ = [
    "AppliedPatch",
    "PatchSet",
    "SpliceError",
    "StalePlanError",
    "apply_patchset",
    "build_reversal_patchset",
]
