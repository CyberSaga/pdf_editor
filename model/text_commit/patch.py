"""Reversible low-level PatchSet application for the text-commit engine.

The only mutation primitive of the high-fidelity tiers: validate the page
fingerprint, splice the declared byte ranges (which re-checks per-stream
digests and expected bytes), and update the stream objects in place.  The
returned handle can revert everything from the captured prior bytes.

Forbidden here by design: redaction, ``clean_contents``, annotation
save/recreate, and any neighbor rewriting.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

import fitz

from model.text_commit.dto import StreamReplacement
from model.text_commit.inspect import page_fingerprint
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


__all__ = [
    "AppliedPatch",
    "PatchSet",
    "SpliceError",
    "StalePlanError",
    "apply_patchset",
]
