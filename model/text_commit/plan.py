"""Tier 0 capability classification: narrow by design, never guessing.

The only edit that classifies as Tier 0 in v1: one unambiguous run bound
to one complete literal-string ``Tj`` on the direct page stream, simple
Latin encoding with a verified reverse encoder, fill render mode, no
rise/scaling/marked-content dependency, no style or geometry override,
and a replacement whose consumed advance equals the source advance.
Every failed gate returns a stable :class:`RejectReason` code.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.dto import RejectReason, StreamReplacement
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.inspect import (
    BindingFailure,
    SourceSpanBinding,
    bind_source_text,
    page_fingerprint,
    page_has_widgets_or_signatures,
)
from model.text_commit.pdf_lexer import encode_literal_string

logger = logging.getLogger(__name__)

# Advance equality tolerance, relative to font size.  Both sides are measured
# from the same source, so genuinely width-neutral replacements agree to float
# precision and this only absorbs rounding.
#
# The two sources need different tolerances, and the difference is not
# cosmetic.  A /Widths advance is exact rational arithmetic — integer table
# units scaled by the font size — and one table unit is *exactly*
# ``_ADVANCE_TOL_PER_PT * size``.  Reusing the face tolerance there would put
# the smallest representable width difference precisely on the ``>`` boundary,
# leaving float representation to decide accept/reject: measured
# non-monotonic (size 12 accepted a 0.012pt shift, size 72 refused 0.072pt,
# size 600 accepted 0.600pt).  Absorbing a whole unit of the document's own
# width table is not "rounding", so widths get a float-noise tolerance.
_ADVANCE_TOL_PER_PT = 1e-3  # face-derived: absorbs the face's own float error
_ADVANCE_TOL_PER_PT_EXACT = 1e-9  # /Widths: exact arithmetic, noise only


@dataclass(frozen=True)
class PreparedEdit:
    """An immutable, verified-on-scratch Tier 0 candidate."""

    token: str
    page_xref: int
    stream_xref: int
    replacement: StreamReplacement
    binding: SourceSpanBinding
    original_text: str
    replacement_text: str
    font_resource: str
    font_xref: int
    font_size: float
    target_bbox_page: tuple[float, float, float, float]
    page_fingerprint: str


@dataclass(frozen=True)
class PlanRejection:
    reason: str  # a RejectReason constant
    detail: str


def _advance(
    capability: FontCapability, text: str, size: float, tc: float, tw: float
) -> float:
    """Advance ``text`` consumes, in points, including Tc/Tw contributions.

    The string width comes from the font's own /Widths table when it
    declares one — that, not the font program, is what a viewer advances by
    for a simple font — and from the resolved face otherwise.  Callers must
    have established that the advance is provable; an unprovable code has no
    defensible width and Tier 0 refuses rather than invent one.
    """
    width = capability.string_width(text, size)
    if width is None:
        raise ValueError("advance is not provable for this font and text")
    return width + tc * len(text) + tw * text.count(" ")


def prepare_tier0_plan(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None = None,
    new_rect: object | None = None,
    page_has_pending_maintenance: bool = False,
) -> PreparedEdit | PlanRejection:
    """Classify and build the Tier 0 candidate, or reject with a reason."""
    if replacement_text == target_text:
        return PlanRejection(RejectReason.NO_CHANGE, "replacement equals source")
    if not replacement_text:
        return PlanRejection(
            RejectReason.EMPTY_REPLACEMENT, "deletion is not a Tier 0 operation"
        )
    if "\n" in replacement_text or "\r" in replacement_text:
        return PlanRejection(
            RejectReason.MULTILINE_REPLACEMENT,
            "line-count changes require paragraph layout (Tier 1+)",
        )
    if style_overrides is not None and style_overrides.changed:
        return PlanRejection(
            RejectReason.STYLE_OVERRIDE_PRESENT,
            "explicit user restyle cannot reuse the source show op unchanged",
        )
    if new_rect is not None:
        return PlanRejection(
            RejectReason.GEOMETRY_OVERRIDE_PRESENT,
            "user-dragged geometry requires re-layout (Tier 1+)",
        )
    if page_has_pending_maintenance:
        return PlanRejection(
            RejectReason.PENDING_MAINTENANCE,
            "page has pending legacy cleanup that may run clean_contents",
        )
    if page_has_widgets_or_signatures(doc, page):
        return PlanRejection(
            RejectReason.SIGNED_OR_WIDGET_TARGET,
            "form widgets or signatures present; high-fidelity edit refused",
        )

    binding = bind_source_text(
        doc, page, target_text=target_text, expected_origin=expected_origin
    )
    if isinstance(binding, BindingFailure):
        return PlanRejection(binding.reason, binding.detail)

    show = binding.show
    if show.operator != "Tj" or show.string_kind != "literal":
        return PlanRejection(
            RejectReason.NOT_SINGLE_LITERAL_TJ,
            f"target is a {show.string_kind} {show.operator}; v1 patches only "
            "complete literal-string Tj operators",
        )
    if show.render_mode != 0 or show.rise != 0.0 or show.hscale != 100.0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"render_mode={show.render_mode} rise={show.rise} "
            f"hscale={show.hscale}",
        )
    if show.mc_depth != 0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "target is inside a marked-content sequence",
        )

    if show.font_resource is None:
        return PlanRejection(
            RejectReason.FONT_FACE_UNAVAILABLE, "no font selected at the show op"
        )
    capability = registry.capability(page, show.font_resource)
    if capability is None:
        return PlanRejection(
            RejectReason.FONT_FACE_UNAVAILABLE,
            f"font resource /{show.font_resource} not resolvable on this page",
        )
    if capability.tier0_reject_reason is not None:
        return PlanRejection(
            capability.tier0_reject_reason,
            f"font /{show.font_resource} ({capability.basefont})",
        )

    # Verify the reverse encoder against the *source* bytes before trusting
    # it for the replacement (the make-or-break sanity check).
    source_encoded = capability.encode_simple(target_text)
    if source_encoded is None or source_encoded != show.decoded_bytes:
        return PlanRejection(
            RejectReason.ENCODING_FAILED,
            "reverse encoder does not reproduce the source string bytes",
        )
    replacement_encoded = capability.encode_simple(replacement_text)
    if replacement_encoded is None:
        return PlanRejection(
            RejectReason.ENCODING_FAILED,
            "replacement contains characters outside the verified simple "
            "encoding or the font's glyph set",
        )

    # Both strings must be measurable before either is measured: a code with
    # no usable /Widths entry (out of [FirstChar, LastChar], or declared
    # zero) has no advance the document proves, and /MissingWidth is never
    # substituted for it.  Counts only — never the characters themselves.
    uncovered = capability.uncovered_codes(target_text) or capability.uncovered_codes(
        replacement_text
    )
    if uncovered:
        return PlanRejection(
            RejectReason.FONT_WIDTHS_INCOMPLETE,
            f"font /{show.font_resource} ({capability.basefont}) declares no "
            f"usable /Widths entry for {len(uncovered)} character code(s)",
        )

    old_advance = _advance(
        capability, target_text, show.font_size, show.char_spacing, show.word_spacing
    )
    new_advance = _advance(
        capability,
        replacement_text,
        show.font_size,
        show.char_spacing,
        show.word_spacing,
    )
    if capability.advance_source == "widths":
        tolerance = max(_ADVANCE_TOL_PER_PT_EXACT * show.font_size, 1e-9)
    else:
        tolerance = max(_ADVANCE_TOL_PER_PT * show.font_size, 1e-4)
    if abs(new_advance - old_advance) > tolerance:
        return PlanRejection(
            RejectReason.ADVANCE_MISMATCH,
            f"consumed advance would change by {new_advance - old_advance:+.3f}pt; "
            "Tier 0 must preserve it exactly",
        )

    streams = dict(
        (xref, doc.xref_stream(xref) or b"") for xref in page.get_contents()
    )
    stream_bytes = streams[show.stream_xref]
    expected = stream_bytes[show.string_start : show.string_end]
    replacement = StreamReplacement(
        stream_xref=show.stream_xref,
        start=show.string_start,
        end=show.string_end,
        expected_bytes=expected,
        replacement_bytes=encode_literal_string(replacement_encoded),
        expected_stream_digest=binding.stream_digest,
    )

    fingerprint = page_fingerprint(doc, page)
    if target_bbox is None:
        origin = binding.origin_page
        target_bbox = (
            origin[0],
            origin[1] - show.font_size,
            origin[0] + old_advance,
            origin[1] + 0.35 * show.font_size,
        )

    token = hashlib.sha256(
        "|".join(
            (
                fingerprint,
                str(replacement.stream_xref),
                str(replacement.start),
                str(replacement.end),
                replacement.replacement_bytes.hex(),
            )
        ).encode("ascii")
    ).hexdigest()

    return PreparedEdit(
        token=token,
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        replacement=replacement,
        binding=binding,
        original_text=target_text,
        replacement_text=replacement_text,
        font_resource=show.font_resource,
        font_xref=capability.font_xref,
        font_size=show.font_size,
        target_bbox_page=tuple(float(v) for v in target_bbox),  # type: ignore[arg-type]
        page_fingerprint=fingerprint,
    )
