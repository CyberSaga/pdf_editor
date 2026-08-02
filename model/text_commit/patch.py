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

from model.text_commit.dto import FontOutcome, FontResourceAction, StreamReplacement
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import page_fingerprint, read_page_streams
from model.text_commit.pdf_lexer import SpliceError, splice_stream
from model.text_commit.replay import ShowOp
from model.text_commit.verify import prove_source_resource_reuse

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


def build_advance_preserving_erase(
    stream_bytes: bytes, show: ShowOp, consumed_advance: float
) -> StreamReplacement:
    """Replace a full show operator with a kern-only ``TJ`` that preserves
    ``consumed_advance``.

    Deleting a show operator's raw bytes removes its text-space advance
    entirely, shifting any later show that shares the same line (no
    intervening ``Td``/``Tm``).  A ``[N] TJ`` adjustment number advances the
    current position by ``-N/1000 * Tfs * Th`` with no glyph drawn and,
    critically, without applying ``Tc``/``Tw`` (those only apply to actual
    glyph shows) -- so ``consumed_advance`` (the source operator's total
    text-space advance, with any ``Tc``/``Tw`` it consumed already folded
    in) is compensated directly from the desired displacement, corrected
    for the source show's own horizontal scaling (``Tz``).

    Carries ``expected_bytes``/``expected_stream_digest`` like every
    :class:`StreamReplacement`, so :func:`~model.text_commit.pdf_lexer.
    splice_stream`'s stale-plan gate still applies.
    """
    if show.font_size == 0.0 or show.hscale == 0.0:
        raise ValueError(
            "cannot compensate advance under zero font size or horizontal scale"
        )
    kern = -100_000.0 * consumed_advance / (show.font_size * show.hscale)
    replacement_bytes = f"[{kern:.6f}] TJ".encode("ascii")
    expected = stream_bytes[show.op_start : show.op_end]
    return StreamReplacement(
        stream_xref=show.stream_xref,
        start=show.op_start,
        end=show.op_end,
        expected_bytes=expected,
        replacement_bytes=replacement_bytes,
        expected_stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
    )


def build_transplant_replacement(
    stream_bytes: bytes, show: ShowOp, new_op_bytes: bytes
) -> StreamReplacement:
    """Splice ``new_op_bytes`` in at the SOURCE operator's exact byte range.

    The transplant candidate strategy: because the replacement lands at the
    identical byte position inside the identical stream, it inherits the
    source op's z-order, ``q``/``Q`` clip scope, ``ExtGState``, and
    ``BDC``/``EMC`` (OCG) nesting by construction -- unlike a TextWriter
    "append", which draws into a brand-new stream tacked onto the end of
    ``/Contents`` and inherits none of it.
    """
    expected = stream_bytes[show.op_start : show.op_end]
    return StreamReplacement(
        stream_xref=show.stream_xref,
        start=show.op_start,
        end=show.op_end,
        expected_bytes=expected,
        replacement_bytes=new_op_bytes,
        expected_stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
    )


def build_tier1_font_outcome(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    resource_name: str,
    source_font_xref: int,
    written_font_xref: int | None,
) -> FontOutcome:
    """The honest Tier-1 font-outcome chokepoint.

    ``SOURCE_RESOURCE_REUSED`` is claimed only when :func:`~model.
    text_commit.verify.prove_source_resource_reuse` affirms the resource
    still resolves to the untouched source font object -- never from face
    identity, byte equality of an extracted font program, or Unicode glyph
    coverage.  Every other case reports an honest substitution: an
    extracted face that had to be re-embedded is ``VALIDATED_FACE_
    EMBEDDED``; a named-system fallback is ``SYSTEM_FACE_SUBSTITUTED``;
    anything else (a base-14 metrics-only fallback, or a face this
    registry cannot resolve at all) is ``LEGACY_BASE14_SUBSTITUTED``.
    """
    if prove_source_resource_reuse(
        doc, page, resource_name=resource_name, source_font_xref=source_font_xref
    ):
        return FontOutcome(
            resource_name=resource_name,
            source_font_xref=source_font_xref,
            written_font_xref=written_font_xref,
            action=FontResourceAction.SOURCE_RESOURCE_REUSED,
        )

    registry = DocumentFontRegistry(doc)
    capability = registry.capability(page, resource_name)
    face_source = capability.face_source if capability is not None else "none"
    if face_source == "extracted":
        action = FontResourceAction.VALIDATED_FACE_EMBEDDED
    elif face_source == "system":
        action = FontResourceAction.SYSTEM_FACE_SUBSTITUTED
    else:
        action = FontResourceAction.LEGACY_BASE14_SUBSTITUTED

    return FontOutcome(
        resource_name=resource_name,
        source_font_xref=source_font_xref,
        written_font_xref=written_font_xref,
        action=action,
    )


__all__ = [
    "AppliedPatch",
    "PatchSet",
    "SpliceError",
    "StalePlanError",
    "apply_patchset",
    "build_advance_preserving_erase",
    "build_reversal_patchset",
    "build_tier1_font_outcome",
    "build_transplant_replacement",
]
