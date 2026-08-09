"""Tier 0/1 capability classification: narrow by design, never guessing.

Tier 0 (v1): one unambiguous run bound to one complete single-string ``Tj``
(literal or hex) on the direct page stream, simple Latin encoding with a
verified reverse encoder, fill render mode, no rise/horizontal-scaling/
marked-content dependency, a text matrix that is at most a uniform positive
scale, no style or geometry override, and a replacement whose consumed
advance equals the source advance exactly. Every failed gate returns a
stable :class:`RejectReason` code.

Tier 1 (Task 11 Slice 1) relaxes only the equal-advance requirement: where
Tier 0 would refuse ``ADVANCE_MISMATCH``, the whole source ``Tj`` operator is
replaced with ``[(new) K] TJ`` at its exact byte range, where the kern number
``K`` absorbs the advance delta.  Every other Tier 0 gate still applies, plus
two admission checks that close latent Tier 0 holes (font_size<=0, a shared
content stream) and three Tier-1-only geometry gates (growth direction,
page boundary; growth *blankness* is proved by the callers, not here -- see
``verify.growth_zone_is_uniform``).

:func:`prepare_tier0_plan` is the frozen legacy entry point: its behavior for
every input is unchanged, byte-for-byte, from before Slice 1 -- existing
callers and tests see it exactly as before, INCLUDING for the two new
common-path gates, which it never applies. :func:`prepare_plan` is the new,
``max_tier``-parameterized entry point (0 or 1) that both applies the new
gates and, at ``max_tier=1``, continues past an advance mismatch into Tier 1
assembly. The two share one classification body (:func:`_classify`) for
everything but that difference, so there is no duplicated replay/bind.
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.dto import RejectReason, StreamReplacement
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.inspect import (
    BindingFailure,
    SourceSpanBinding,
    bind_source_text,
    scan_shared_streams,
    page_fingerprint,
    page_has_widgets_or_signatures,
)
from model.text_commit.patch import build_transplant_replacement
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

# TJ kern displacement below this magnitude formats as "-0.000000" for a
# negative float that rounds to zero, which differs byte-for-byte from
# "0.000000" and would make the content-derived token direction-sensitive
# for no reason -- normalized to a plain 0.0 before formatting (plan.md
# adjudication 3).


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
    # Tier 1 (Task 11 Slice 1) additions; safe defaults keep every Tier 0
    # candidate (and every pre-Slice-1 caller) unchanged.
    tier: int = 0
    tier0_fallback_reason: str | None = None
    # None means no growth (a shrink, or Tier 0): the declared region for
    # halo/extraction is target_bbox_page alone. Non-None is the growth-only
    # band; declared region is then target_bbox_page UNION growth_bbox_page.
    growth_bbox_page: tuple[float, float, float, float] | None = None
    kern_value: float | None = None
    old_advance: float | None = None
    new_advance: float | None = None


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


def _classify(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    max_tier: int,
    slice1_gates: bool,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None = None,
    new_rect: object | None = None,
    page_has_pending_maintenance: bool = False,
    shared_stream_xrefs: frozenset[int] | None = None,
) -> PreparedEdit | PlanRejection:
    """Shared classification body for :func:`prepare_tier0_plan` (frozen,
    ``slice1_gates=False``) and :func:`prepare_plan` (``slice1_gates=True``).

    ``slice1_gates`` gates ONLY the two new common-path checks (font_size<=0,
    shared content stream) — the two frozen behavioral pins in
    ``test_text_commit_tier1_transplant.py`` (``test_font_size_zero_refused``,
    ``test_shared_content_stream_refuses_both_tiers``) each call BOTH
    ``prepare_tier0_plan`` (must still succeed / still just ADVANCE_MISMATCH,
    i.e. today's behavior) and ``prepare_plan(max_tier=0, ...)`` (must hit the
    new gate) on the SAME fixture, which is only satisfiable if the two entry
    points diverge on exactly these two checks and nothing else — see
    plan.md's Task 11 Slice 1 dispute note. Everything else in this function
    is identical for both entry points.
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
    if slice1_gates and show.font_size <= 0.0:
        # Tier 1's kern divides by font_size (see the kern computation
        # below); font_size<=0 is refused here, in the common text-state
        # cluster, rather than left to surface as a ZeroDivisionError deeper
        # in Tier 1 assembly (plan.md adjudication 2).
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"font_size={show.font_size} cannot be zero or negative",
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

    if slice1_gates:
        shared = (
            shared_stream_xrefs
            if shared_stream_xrefs is not None
            else scan_shared_streams(doc)
        )
        if show.stream_xref in shared:
            # A stream referenced by more than one page's /Contents: splicing
            # it would silently edit sibling pages too, and V0-style
            # verification only ever looks at the edited page (plan.md D10).
            # Applies to both tiers, ahead of the advance gate -- an
            # advance-matching Tier 0 replacement is just as unsafe here as a
            # Tier 1 one.
            return PlanRejection(
                RejectReason.SHARED_CONTENT_STREAM,
                f"stream {show.stream_xref} is referenced by multiple pages",
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

    # Text-space -> page-space scale, hoisted so both the fallback target
    # bbox (below, needed by Tier 0 *and* Tier 1) and the Tier 1 growth bbox
    # read the same value -- no local recomputation anywhere (plan.md
    # adjudication 1, fixing the refuter's NameError/scope defect).
    trm_scale = show.trm_uniform_scale if show.trm_uniform_scale is not None else 1.0
    page_matrix = page.transformation_matrix
    scale = trm_scale * math.hypot(page_matrix.a, page_matrix.b)

    def _fallback_target_bbox() -> tuple[float, float, float, float]:
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
        if target_bbox is not None:
            return tuple(float(v) for v in target_bbox)  # type: ignore[return-value]
        page_size = show.font_size * scale
        origin = binding.origin_page
        return (
            origin[0],
            origin[1] - page_size,
            origin[0] + old_advance * scale,
            origin[1] + 0.35 * page_size,
        )

    if abs(new_advance - old_advance) <= tolerance:
        # ---------------------------------------------------- Tier 0 assembly
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
        target_bbox_page = _fallback_target_bbox()
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
            target_bbox_page=target_bbox_page,
            page_fingerprint=fingerprint,
        )

    if max_tier == 0:
        return PlanRejection(
            RejectReason.ADVANCE_MISMATCH,
            f"consumed advance would change by {new_advance - old_advance:+.3f}pt; "
            "Tier 0 must preserve it exactly",
        )

    # ---------------------------------------------------------- Tier 1 assembly
    #
    # [(new) K] TJ transplant at the source op's whole byte range (op_start:
    # op_end, not just the string operand): K absorbs the advance delta so
    # every later show on the page keeps its origin (plan.md D3).
    target_bbox_page = _fallback_target_bbox()
    growth_bbox_page: tuple[float, float, float, float] | None = None
    if new_advance > old_advance:
        # Growth direction guard: the bbox formula above assumes text
        # advance maps to +x in page space, which only holds for a plain
        # (unrotated, unskewed, unreflected) page matrix. /Rotate 90/180/270
        # and skew all fail it -- refuse rather than mislocate the growth
        # zone (plan.md region_and_growth). Shrink never reaches here:
        # declared_bbox == target_bbox_page regardless of page matrix.
        #
        # page.transformation_matrix does NOT reflect /Rotate on the
        # installed PyMuPDF (its own property body substitutes the
        # UNROTATED flip matrix whenever page.rotation != 0 -- verified
        # against the running binary, not merely documented behavior), so
        # rotation is checked directly too; matches the established
        # pattern at pdf_content_ops.py:554 (matrix skew check ALONGSIDE
        # an explicit ``rotation % 360`` check, same reason).
        if (
            page.rotation % 360 != 0
            or abs(page_matrix.b) > 1e-6
            or page_matrix.a <= 0
        ):
            return PlanRejection(
                RejectReason.GROWTH_DIRECTION_UNPROVEN,
                f"page matrix a={page_matrix.a:.4f} b={page_matrix.b:.4f}; "
                "growth direction not provably +x in page space",
            )
        tb = target_bbox_page
        growth_bbox_page = (
            tb[2],
            tb[1],
            tb[2] + (new_advance - old_advance) * scale,
            tb[3],
        )
        page_rect = page.rect
        # Only the growth extension claims NEW page territory: x0/y0/y1 are
        # the source's own extent, already on the page -- a near-edge
        # fallback bbox can legitimately poke past the top margin, and
        # refusing on that would false-reject purely horizontal growth.
        # Growth is provably +x here (direction guard above), so the only
        # boundary that matters is the right edge.
        if growth_bbox_page[2] > page_rect.x1:
            return PlanRejection(
                RejectReason.GROWTH_PAST_PAGE_BOUNDARY,
                f"growth extends to x={growth_bbox_page[2]:.2f}, past the "
                f"page boundary x1={page_rect.x1:.2f}",
            )

    # K = -100000*(old-new)/(font_size*hscale) displaces the TJ position by
    # -K/1000 * Tfs * Th/100 (PDF spec 9.4.3); old_advance/new_advance are
    # hscale-UNSCALED, so this formula is only correct because the hscale==
    # 100 gate above holds -- relaxing that gate would need
    # -1000*(old-new)/font_size on hscale-scaled advances instead.
    # K is always material here: Tier 1 assembly is only entered once
    # |old-new| exceeded the Tier 0 tolerance (>= 1e-9 * font_size), so
    # |K| >= ~1e-6 and there is no -0.0 formatting case to normalize.
    kern = -100_000.0 * (old_advance - new_advance) / (show.font_size * show.hscale)
    new_op_bytes = (
        b"["
        + encode_literal_string(replacement_encoded)
        + b" "
        + f"{kern:.6f}".encode("ascii")
        + b"] TJ"
    )
    replacement = build_transplant_replacement(stream_bytes, show, new_op_bytes)

    fingerprint = page_fingerprint(doc, page)
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
        target_bbox_page=target_bbox_page,
        page_fingerprint=fingerprint,
        tier=1,
        tier0_fallback_reason=RejectReason.ADVANCE_MISMATCH,
        growth_bbox_page=growth_bbox_page,
        kern_value=kern,
        old_advance=old_advance,
        new_advance=new_advance,
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
    """Classify and build the Tier 0 candidate, or reject with a reason.

    Frozen entry point: behavior for every input is unchanged from before
    Task 11 Slice 1, including the two Slice-1 common-path gates (font_size,
    shared content stream), which this wrapper never applies. Use
    :func:`prepare_plan` for Slice-1-aware classification.
    """
    return _classify(
        doc,
        page,
        max_tier=0,
        slice1_gates=False,
        target_text=target_text,
        replacement_text=replacement_text,
        expected_origin=expected_origin,
        target_bbox=target_bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
        page_has_pending_maintenance=page_has_pending_maintenance,
    )


def prepare_plan(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    max_tier: int,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None = None,
    new_rect: object | None = None,
    page_has_pending_maintenance: bool = False,
    shared_stream_xrefs: frozenset[int] | None = None,
) -> PreparedEdit | PlanRejection:
    """Classify and build a Tier 0 or Tier 1 (``max_tier=1``) candidate.

    At ``max_tier=0`` this is byte-identical to :func:`prepare_tier0_plan`
    EXCEPT for the two new common-path gates (font_size<=0, shared content
    stream), which apply here and never in the frozen wrapper -- see
    :func:`_classify`.

    ``shared_stream_xrefs`` lets a session-scoped caller (the preview
    renderer, whose scratch document never changes page structure) supply
    the :func:`~model.text_commit.inspect.scan_shared_streams` result once
    per session instead of paying the O(page_count) scan on every
    keystroke; ``None`` scans here.
    """
    return _classify(
        doc,
        page,
        max_tier=max_tier,
        slice1_gates=True,
        target_text=target_text,
        replacement_text=replacement_text,
        expected_origin=expected_origin,
        target_bbox=target_bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
        page_has_pending_maintenance=page_has_pending_maintenance,
        shared_stream_xrefs=shared_stream_xrefs,
    )
