"""Tier 0/1 capability classification: narrow by design, never guessing.

Tier 0: one unambiguous run bound to one complete single-string ``Tj``
(literal or hex) on the direct page stream, simple Latin encoding with a
verified reverse encoder, fill render mode, no rise/horizontal-scaling/
marked-content dependency, a text matrix that is at most a uniform positive
scale, no style or geometry override, and a replacement whose consumed
advance equals the source advance exactly.

Tier 1 Slice 1 (``prepare_plan``, escalation only): the SAME classified
candidate, reached only when Tier 0 refuses with ``ADVANCE_MISMATCH`` and
the caller allows ``max_tier >= 1``. Composes ``patch.
build_kern_compensated_transplant`` -- a whole-op ``"[(new) K] TJ"`` splice
whose kern term absorbs an arbitrary advance delta, so ink may grow past the
source bbox under a verified blank-growth-zone proof (``verify.
verify_tier1_commit``).

Every failed gate returns a stable :class:`RejectReason` code.
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.dto import CommitTier, RejectReason, StreamReplacement
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.inspect import (
    BindingFailure,
    SourceSpanBinding,
    bind_source_text,
    find_pages_sharing_content_stream,
    page_fingerprint,
    page_has_widgets_or_signatures,
)
from model.text_commit.patch import build_kern_compensated_transplant, kern_for_displacement
from model.text_commit.pdf_lexer import encode_literal_string
from model.text_commit.replay import ShowOp

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
_GROWTH_OUTSIDE_PAGE_REASON = getattr(
    RejectReason, "GROWTH_OUTSIDE_PAGE", "growth_outside_page"
)
_PAGE_CONTAINMENT_TOL_PT = 1e-3


@dataclass(frozen=True)
class PreparedEdit:
    """An immutable, verified-on-scratch Tier 0 or Tier 1 candidate."""

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
    # Task 11 Slice 1 additions -- all defaulted so the single Tier 0
    # construction site and every existing test/script stays valid.
    tier: CommitTier = CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    # None for Tier 0 (which never grows the target box); the ink-growth-
    # widened box for Tier 1, or exactly ``target_bbox_page`` when a Tier 1
    # candidate has no growth.
    verify_bbox_page: tuple[float, float, float, float] | None = None
    source_advance: float = 0.0
    replacement_advance: float = 0.0
    kern_adjustment: float = 0.0

    @property
    def effective_verify_bbox(self) -> tuple[float, float, float, float]:
        """``verify_bbox_page`` when set, else ``target_bbox_page``."""
        if self.verify_bbox_page is not None:
            return self.verify_bbox_page
        return self.target_bbox_page

    @property
    def has_ink_growth(self) -> bool:
        """True when the verified region is wider than the target box."""
        return (
            self.verify_bbox_page is not None
            and self.verify_bbox_page != self.target_bbox_page
        )


@dataclass(frozen=True)
class PlanRejection:
    reason: str  # a RejectReason constant
    detail: str


@dataclass(frozen=True)
class _ClassifiedTarget:
    """Everything the shared classifier proves before either tier decides.

    Not a public contract: an internal handoff between :func:`_classify_common`
    and :func:`_build_tier0`/:func:`_build_tier1`, both of which reuse it
    without re-parsing or re-binding.
    """

    binding: SourceSpanBinding
    show: ShowOp
    capability: FontCapability
    stream_bytes: bytes
    target_text: str
    replacement_text: str
    source_encoded: bytes
    replacement_encoded: bytes
    source_advance: float
    replacement_advance: float
    advance_tolerance: float
    target_bbox_page: tuple[float, float, float, float]
    fingerprint: str


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


def _content_token(
    fingerprint: str,
    replacement: StreamReplacement,
    *,
    target_bbox: tuple[float, float, float, float] | None = None,
    verify_bbox: tuple[float, float, float, float] | None = None,
    source_advance: float = 0.0,
    replacement_advance: float = 0.0,
    kern_adjustment: float = 0.0,
    font_resource: str = "",
    font_xref: int = 0,
) -> str:
    """Content-derived plan token shared by every tier and by preview.

    Preimage includes full candidate semantics: page fingerprint, splice
    coordinates, replacement bytes, target/verify bboxes, advance pair,
    kern adjustment, and font identity.  Two candidates that differ in
    any property always produce different tokens.
    """
    bbox_str = ",".join(f"{v:.6f}" for v in target_bbox) if target_bbox else ""
    vbbox_str = ",".join(f"{v:.6f}" for v in verify_bbox) if verify_bbox else ""
    return hashlib.sha256(
        "|".join(
            (
                fingerprint,
                str(replacement.stream_xref),
                str(replacement.start),
                str(replacement.end),
                replacement.replacement_bytes.hex(),
                bbox_str,
                vbbox_str,
                f"{source_advance:.6f}",
                f"{replacement_advance:.6f}",
                f"{kern_adjustment:.6f}",
                font_resource,
                str(font_xref),
            )
        ).encode("ascii")
    ).hexdigest()


def _classify_common(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None,
    new_rect: object | None,
    page_has_pending_maintenance: bool,
) -> _ClassifiedTarget | PlanRejection:
    """Classify and bind the candidate; shared by every tier.

    Gate order and every detail string are pinned by
    ``test_text_commit_structural_gates.py`` (19 tests) -- this is
    ``prepare_tier0_plan``'s original body, verbatim, plus two new gates
    (operator, shared-content-stream) inserted before the existing
    ``NOT_SINGLE_LITERAL_TJ`` gate.
    """
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

    # NEW (Task 11 Slice 1): ' and " carry persistent text-state side
    # effects INSIDE their recorded op range that a whole-op splice would
    # silently delete -- refuse both tiers here, in the shared classifier,
    # rather than only at the patch.py mechanism level.
    if show.operator in ("'", '"'):
        if show.operator == "'":
            detail = (
                "target show operator is ' (quote), which folds an implicit "
                "T* line break into its recorded range; a whole-op splice "
                "would delete it"
            )
        else:
            detail = (
                'target show operator is " (double-quote), whose recorded '
                "range includes the aw/ac operands that assign Tw/Tc; a "
                "whole-op splice would silently delete those persistent "
                "state assignments"
            )
        return PlanRejection(RejectReason.UNSUPPORTED_SHOW_OPERATOR, detail)

    # NEW (Task 11 Slice 1): every high-fidelity tier mutates its stream in
    # place, so a stream shared by another page's /Contents would silently
    # rewrite that page too. Tier-independent: covers Tier 0 as well.
    foreign = find_pages_sharing_content_stream(
        doc, stream_xref=show.stream_xref, page_number=page.number
    )
    if foreign:
        return PlanRejection(
            RejectReason.SHARED_CONTENT_STREAM,
            f"content stream is /Contents of {len(foreign)} other page(s)",
        )

    # A hex operand is admitted alongside a literal one: the two encode the
    # same bytes, and the patch below replaces the *whole* operand token
    # (delimiters included) with a freshly encoded literal, so nothing of
    # the source string's spelling survives to matter.  ``TJ`` stays out --
    # its array carries kerns that a replacement would have to compensate.
    if show.operator != "Tj" or show.string_kind not in ("literal", "hex"):
        return PlanRejection(
            RejectReason.NOT_SINGLE_LITERAL_TJ,
            f"target is a {show.string_kind} {show.operator}; v1 patches only "
            "complete single-string Tj operators",
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

    streams = dict(
        (xref, doc.xref_stream(xref) or b"") for xref in page.get_contents()
    )
    stream_bytes = streams[show.stream_xref]

    fingerprint = page_fingerprint(doc, page)
    if target_bbox is None:
        # ``origin_page`` is page space but ``old_advance``/``font_size`` are
        # text space, so *both* scales between the two have to be applied
        # here or the halo is wrong by their product.  Below 1 it *inflates*,
        # and verification only proves raster identity OUTSIDE the halo -- so
        # an inflated one masks corruption instead of catching it; above 1 it
        # shrinks and V0c rejects a valid edit as not extractable.
        #
        # 1. The text matrix.  ``bind_source_text`` already refused any TRM
        #    that is not a uniform positive scale; 1.0 keeps this total
        #    rather than relying on that.
        # 2. The page transform, which MuPDF builds from the cropbox flip,
        #    /Rotate *and* /UserUnit -- at /UserUnit 2 it scales by 2, and
        #    ``origin_page`` went through it while the advance did not.
        #    ``hypot`` of its first row is that scale for every page (the
        #    transform is always a rotation/flip times one uniform factor);
        #    ``abs(a)`` would read 0 at /Rotate 90 and collapse the halo.
        trm_scale = (
            show.trm_uniform_scale if show.trm_uniform_scale is not None else 1.0
        )
        page_matrix = page.transformation_matrix
        scale = trm_scale * math.hypot(page_matrix.a, page_matrix.b)
        page_size = show.font_size * scale
        origin = binding.origin_page
        target_bbox = (
            origin[0],
            origin[1] - page_size,
            origin[0] + old_advance * scale,
            origin[1] + 0.35 * page_size,
        )

    return _ClassifiedTarget(
        binding=binding,
        show=show,
        capability=capability,
        stream_bytes=stream_bytes,
        target_text=target_text,
        replacement_text=replacement_text,
        source_encoded=source_encoded,
        replacement_encoded=replacement_encoded,
        source_advance=old_advance,
        replacement_advance=new_advance,
        advance_tolerance=tolerance,
        target_bbox_page=tuple(float(v) for v in target_bbox),  # type: ignore[arg-type]
        fingerprint=fingerprint,
    )


def _build_tier0(
    classified: _ClassifiedTarget, page: fitz.Page
) -> PreparedEdit | PlanRejection:
    """The advance-equality gate, plus the string-range splice and token."""
    show = classified.show
    # _classify_common already refused a None font_resource
    # (FONT_FACE_UNAVAILABLE); this is a type narrowing, not a new check.
    assert show.font_resource is not None
    if abs(classified.replacement_advance - classified.source_advance) > (
        classified.advance_tolerance
    ):
        return PlanRejection(
            RejectReason.ADVANCE_MISMATCH,
            "consumed advance would change by "
            f"{classified.replacement_advance - classified.source_advance:+.3f}pt; "
            "Tier 0 must preserve it exactly",
        )

    expected = classified.stream_bytes[show.string_start : show.string_end]
    replacement = StreamReplacement(
        stream_xref=show.stream_xref,
        start=show.string_start,
        end=show.string_end,
        expected_bytes=expected,
        replacement_bytes=encode_literal_string(classified.replacement_encoded),
        expected_stream_digest=classified.binding.stream_digest,
    )
    token = _content_token(
        classified.fingerprint,
        replacement,
        target_bbox=classified.target_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
    )
    return PreparedEdit(
        token=token,
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        replacement=replacement,
        binding=classified.binding,
        original_text=classified.target_text,
        replacement_text=classified.replacement_text,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
        font_size=show.font_size,
        target_bbox_page=classified.target_bbox_page,
        page_fingerprint=classified.fingerprint,
    )


def _grown_verify_bbox(
    page: fitz.Page,
    show: ShowOp,
    target_bbox_page: tuple[float, float, float, float],
    growth_advance: float,
) -> tuple[float, float, float, float]:
    """``target_bbox_page`` widened forward by ``growth_advance`` text-space
    points, mapped through the page transform so /Rotate and /UserUnit are
    handled correctly by construction (unlike the axis-aligned fallback-bbox
    formula in :func:`_classify_common`, whose shape defect on rotated pages
    is a separate, not-fixed-here issue).

    Returns ``target_bbox_page`` UNCHANGED (no round trip, no float noise)
    when there is no growth: callers rely on exact equality to decide
    ``PreparedEdit.has_ink_growth``.
    """
    if growth_advance <= 0.0:
        return target_bbox_page
    scale = show.trm_uniform_scale if show.trm_uniform_scale is not None else 1.0
    user = fitz.Rect(*target_bbox_page) * ~page.transformation_matrix
    user.x1 = user.x1 + growth_advance * scale
    mapped = user * page.transformation_matrix
    return (
        min(target_bbox_page[0], float(mapped.x0)),
        min(target_bbox_page[1], float(mapped.y0)),
        max(target_bbox_page[2], float(mapped.x1)),
        max(target_bbox_page[3], float(mapped.y1)),
    )


def _bbox_within_page(
    page: fitz.Page, bbox: tuple[float, float, float, float]
) -> bool:
    page_rect = page.rect
    x0, y0, x1, y1 = bbox
    tol = _PAGE_CONTAINMENT_TOL_PT
    return (
        x0 >= float(page_rect.x0) - tol
        and y0 >= float(page_rect.y0) - tol
        and x1 <= float(page_rect.x1) + tol
        and y1 <= float(page_rect.y1) + tol
    )


def _build_tier1(
    classified: _ClassifiedTarget, page: fitz.Page
) -> PreparedEdit | PlanRejection:
    """The kern-compensated transplant candidate: same op range, wider ink
    admitted only under a verified blank-growth-zone proof (checked later,
    in :func:`~model.text_commit.verify.verify_tier1_commit`, not here)."""
    show = classified.show
    # _classify_common already refused a None font_resource
    # (FONT_FACE_UNAVAILABLE); this is a type narrowing, not a new check.
    assert show.font_resource is not None
    growth = max(
        0.0, classified.replacement_advance - classified.source_advance
    )
    verify_bbox_page = _grown_verify_bbox(
        page, show, classified.target_bbox_page, growth
    )
    if not _bbox_within_page(page, verify_bbox_page):
        return PlanRejection(
            _GROWTH_OUTSIDE_PAGE_REASON,
            "widened verify bbox escapes page bounds",
        )
    kern = kern_for_displacement(
        show, classified.source_advance - classified.replacement_advance
    )
    replacement = build_kern_compensated_transplant(
        classified.stream_bytes,
        show,
        replacement_encoded=classified.replacement_encoded,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
    )
    token = _content_token(
        classified.fingerprint,
        replacement,
        target_bbox=classified.target_bbox_page,
        verify_bbox=verify_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        kern_adjustment=kern,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
    )
    return PreparedEdit(
        token=token,
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        replacement=replacement,
        binding=classified.binding,
        original_text=classified.target_text,
        replacement_text=classified.replacement_text,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
        font_size=show.font_size,
        target_bbox_page=classified.target_bbox_page,
        page_fingerprint=classified.fingerprint,
        tier=CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE,
        verify_bbox_page=verify_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        kern_adjustment=kern,
    )


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
    classified = _classify_common(
        doc,
        page,
        target_text=target_text,
        replacement_text=replacement_text,
        expected_origin=expected_origin,
        target_bbox=target_bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
        page_has_pending_maintenance=page_has_pending_maintenance,
    )
    if isinstance(classified, PlanRejection):
        return classified
    return _build_tier0(classified, page)


# The only Tier 0 refusal Slice 1's composite candidate actually removes: the
# kern term absorbs an arbitrary advance delta while every other property of
# the candidate is identical. Every other reason is terminal for both tiers
# (see plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md).
_TIER1_ESCALATION_REASONS = frozenset({RejectReason.ADVANCE_MISMATCH})


def prepare_plan(
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
    max_tier: int = 0,
) -> PreparedEdit | PlanRejection:
    """Classify once; try Tier 0, escalate to Tier 1 only on ADVANCE_MISMATCH.

    The single product both preview and commit consume, so a Tier 1
    candidate's token is automatically identical on both paths. Tier 0
    always runs first and always wins when it accepts.
    """
    classified = _classify_common(
        doc,
        page,
        target_text=target_text,
        replacement_text=replacement_text,
        expected_origin=expected_origin,
        target_bbox=target_bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
        page_has_pending_maintenance=page_has_pending_maintenance,
    )
    if isinstance(classified, PlanRejection):
        return classified

    tier0_result = _build_tier0(classified, page)
    if isinstance(tier0_result, PreparedEdit):
        return tier0_result
    if max_tier < 1 or tier0_result.reason not in _TIER1_ESCALATION_REASONS:
        return tier0_result
    return _build_tier1(classified, page)
