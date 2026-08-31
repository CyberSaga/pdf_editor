"""Tier 0/1 capability classification: narrow by design, never guessing.

Tier 0: one unambiguous run bound to one complete single-string ``Tj``
(literal or hex) on the direct page stream, simple Latin encoding with a
verified reverse encoder, fill render mode, no rise, a positive finite
horizontal scale, no marked-content dependency, a text matrix that is at most a uniform positive
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
from model.text_commit.cid_fonts import CidCapabilityFailure
from model.text_commit.dto import CommitTier, RejectReason, StreamReplacement
from model.text_commit.evidence import ReplayEvidenceCache, resolve_replay
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.inspect import (
    BindingFailure,
    SourceSpanBinding,
    bind_source_text,
    capture_page_streams,
    find_pages_sharing_content_stream,
    page_fingerprint,
    page_has_widgets_or_signatures,
)
from model.text_commit.marked_content import admit_show_wrappers
from model.text_commit.patch import build_kern_compensated_transplant, kern_for_displacement
from model.text_commit.pdf_lexer import encode_hex_string, encode_literal_string
from model.text_commit.replay import ShowOp
from model.text_commit.transforms import (
    admission_verdict,
    combined_linear,
    map_text_quad_to_visual,
)

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
_GROWTH_OUTSIDE_PAGE_REASON = RejectReason.GROWTH_OUTSIDE_PAGE
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
    # Tier 1 background-majority sampling uses this flag-immune metric quad.
    # It is a pure derivation of token-bound inputs (the fingerprint determines
    # the show transform; source_advance is already in the token), so folding
    # it into the token would add no candidate identity.
    background_bbox_page: tuple[float, float, float, float] | None = None
    source_advance: float = 0.0
    replacement_advance: float = 0.0
    kern_adjustment: float = 0.0
    style_overrides: StyleOverrides | None = None
    geometry_intent: tuple[float, float, float, float] | None = None
    # Task 13 P2: the admitted show's cardinal visual baseline direction
    # ("right"/"left"/"up"/"down"), bound into the plan token (review F5:
    # verify does NOT read this field — it re-derives the grown edge from
    # target/verify bbox geometry, which agrees by construction because
    # ``_grown_verify_bbox`` extends exactly the edge this slug names).
    # Defaulted so pre-P2 hand-built PreparedEdits stay valid; None also
    # marks the axis path (replay-uniform shows, including admitted
    # boundary residuals the shape checks would refuse).
    growth_direction: str | None = None

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
    style_overrides: StyleOverrides | None
    geometry_intent: tuple[float, float, float, float] | None
    # "literal" (simple fonts) or "hex" (Identity-H CID operands): decides
    # how ``replacement_encoded`` is serialized into the spliced operator.
    operand_kind: str
    # Task 13 P2: the admitted show's cardinal visual baseline direction
    # (transforms.admission_verdict) — the ONE direction every growth
    # probe shares.
    trm_direction: str | None = None


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


def _page_visual_matrix(page: fitz.Page) -> fitz.Matrix:
    """User-space → pixmap/visual-space matrix.

    ``page.transformation_matrix`` covers the cropbox y-flip and /UserUnit
    but deliberately omits /Rotate in PyMuPDF 1.27; ``page.rotation_matrix``
    supplies the /Rotate term. Their product matches ``page.get_pixmap``
    coordinates used by verification halos.
    """
    return page.transformation_matrix * page.rotation_matrix


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
    style_overrides: StyleOverrides | None = None,
    geometry_intent: tuple[float, float, float, float] | None = None,
    growth_direction: str | None = None,
) -> str:
    """Content-derived plan token shared by every tier and by preview.

    Preimage includes full candidate semantics: page fingerprint, splice
    coordinates, replacement bytes, target/verify bboxes, advance pair,
    kern adjustment, font identity, style intent, and geometry intent. Two
    candidates that differ in any property always produce different tokens.
    """
    bbox_str = ",".join(f"{v:.6f}" for v in target_bbox) if target_bbox else ""
    vbbox_str = ",".join(f"{v:.6f}" for v in verify_bbox) if verify_bbox else ""
    style_str = (
        "|".join(
            (
                style_overrides.font_family or "",
                ""
                if style_overrides.font_size is None
                else f"{style_overrides.font_size:.6f}",
                ""
                if style_overrides.color is None
                else ",".join(
                    f"{value:.6f}" for value in style_overrides.color
                ),
            )
        )
        if style_overrides is not None and style_overrides.changed
        else ""
    )
    geometry_str = (
        ",".join(f"{value:.6f}" for value in geometry_intent)
        if geometry_intent is not None
        else ""
    )
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
                style_str,
                geometry_str,
                growth_direction or "",
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
    evidence_cache: ReplayEvidenceCache | None = None,
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

    # P3-B: the ONE decoded stream read of this prepare.  Placed after
    # the cheap early gates on purpose -- early rejects keep paying zero
    # stream reads.  The snapshot's fresh-bytes key is the lookup-time
    # pull-validation; a digest match reuses the retained production
    # PageReplay (Shape A), a mismatch replays and replaces the slot.
    # Refused/malformed replays never produce evidence to store.
    snapshot = capture_page_streams(doc, page)
    if not snapshot.streams:
        # Review F4: preserve the pre-P3-B surface verbatim -- bind's
        # empty-streams gate, reached with zero replay work and nothing
        # stored (empty-page evidence must never evict a valid entry).
        return PlanRejection(
            RejectReason.NO_MATCH, "page has no content streams"
        )
    cached = (
        evidence_cache.lookup(snapshot.key)
        if evidence_cache is not None
        else None
    )
    resolved = resolve_replay(snapshot, cached)
    if (
        evidence_cache is not None
        and resolved.evidence is not None
        and not resolved.from_cache
    ):
        evidence_cache.store(resolved.evidence)

    binding = bind_source_text(
        doc,
        page,
        target_text=target_text,
        expected_origin=expected_origin,
        registry=registry,
        resolved=resolved,
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
    if show.render_mode != 0 or show.rise != 0.0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"render_mode={show.render_mode} rise={show.rise}",
        )
    # Tz does not participate in the admitted TRM shape, and verification
    # re-derives growth direction from bbox geometry; the planner is the only
    # defense against a zero/negative/non-finite horizontal scale.
    if not math.isfinite(show.hscale) or show.hscale <= 0.0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"hscale={show.hscale} is not a positive finite horizontal scale",
        )
    # Task 13 P1: the blanket "inside a marked-content sequence" refusal
    # is replaced by the taxonomy admission — a stack of default-visible
    # pure /OC layer wrappers is provably splice-inert (proof obligations
    # 1-5, test_text_commit_mc_admission.py); everything else keeps a
    # fail-closed refusal with its own stable MC_* code.
    mc_rejection = admit_show_wrappers(
        doc,
        page,
        show,
        wrappers=binding.mc_wrappers,
        emc_underflows=binding.mc_emc_underflows,
    )
    if mc_rejection is not None:
        return PlanRejection(mc_rejection.reason, mc_rejection.detail)

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
        if capability.subtype == "Type0":
            # Code-only detail (§10 privacy): the type0_* gates never
            # surface the basefont name — a subset-tagged basename can
            # identify a private document's producer pipeline.
            return PlanRejection(
                capability.tier0_reject_reason,
                capability.tier0_reject_detail
                or "type0 evidence gate refused this font resource",
            )
        return PlanRejection(
            capability.tier0_reject_reason,
            f"font /{show.font_resource} ({capability.basefont})",
        )

    if capability.cid is not None:
        # ---- Task 12 P0-D: the Identity-H/CIDFontType2 codec path ----
        # The locked v1 scope is single HEX Tj: a literal-string spelling
        # of a Type0 operand is spec-legal but stays out of scope rather
        # than silently widening it (post-review pin, wf_1757a5fb-8e9).
        # Detail stays code-only (§10 privacy).
        if show.string_kind != "hex":
            return PlanRejection(
                RejectReason.NOT_SINGLE_LITERAL_TJ,
                "type0 v1 scope admits only single HEX-string Tj operands",
            )
        cid = capability.cid
        # Source-reproduction proof (binding already ran it; re-proven here
        # because the capability may have been rebuilt since, and this
        # plan's evidence must be the one the splice is built from).
        reproduced = cid.encode_first_wins(target_text)
        if isinstance(reproduced, CidCapabilityFailure):
            return PlanRejection(reproduced.reason, reproduced.detail)
        if reproduced != show.decoded_bytes:
            return PlanRejection(
                RejectReason.TYPE0_SOURCE_BYTES_NOT_REPRODUCED,
                "deterministic reverse encoding does not reproduce the "
                "source show operand bytes",
            )
        source_cids = tuple(
            int.from_bytes(show.decoded_bytes[i : i + 2], "big")
            for i in range(0, len(show.decoded_bytes), 2)
        )
        strict = cid.encode_strict(replacement_text)
        if isinstance(strict, CidCapabilityFailure):
            return PlanRejection(strict.reason, strict.detail)
        replacement_cids = strict
        # GID + glyph-repertoire gates for EVERY cid the edit touches:
        # source first (broken map evidence for glyphs already on the page
        # is broken evidence, full stop), then the replacement.
        glyph_failure = cid.glyph_gate(source_cids, target_text) or cid.glyph_gate(
            replacement_cids, replacement_text
        )
        if glyph_failure is not None:
            return PlanRejection(glyph_failure.reason, glyph_failure.detail)

        source_encoded = show.decoded_bytes
        replacement_encoded = cid.encode_cids(replacement_cids)
        old_advance = cid.advance_points(
            source_cids, show.font_size, show.char_spacing
        )
        new_advance = cid.advance_points(
            replacement_cids, show.font_size, show.char_spacing
        )
        # /W and /DW are exact rational arithmetic, same as simple /Widths.
        tolerance = max(_ADVANCE_TOL_PER_PT_EXACT * show.font_size, 1e-9)
        operand_kind = "hex"
    else:
        # Verify the reverse encoder against the *source* bytes before trusting
        # it for the replacement (the make-or-break sanity check).
        source_encoded_simple = capability.encode_simple(target_text)
        if source_encoded_simple is None or source_encoded_simple != show.decoded_bytes:
            return PlanRejection(
                RejectReason.ENCODING_FAILED,
                "reverse encoder does not reproduce the source string bytes",
            )
        source_encoded = source_encoded_simple
        replacement_encoded_simple = capability.encode_simple(replacement_text)
        if replacement_encoded_simple is None:
            return PlanRejection(
                RejectReason.ENCODING_FAILED,
                "replacement contains characters outside the verified simple "
                "encoding or the font's glyph set",
            )
        replacement_encoded = replacement_encoded_simple

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
        operand_kind = "literal"

    streams = dict(snapshot.streams)
    stream_bytes = streams[show.stream_xref]

    fingerprint = page_fingerprint(doc, page, streams=snapshot.streams)
    # Task 13 P2: the show's cardinal visual baseline direction — it is
    # recomputed (cheap, pure) rather than threaded through the binding.
    # Usually an admission (binding proved it); the exception is a bound
    # replay-uniform show whose boundary residuals the relative shape
    # checks would refuse (review F2) — its direction is None and it
    # rides the axis path exactly as before P2.
    trm_direction = admission_verdict(page, show.tm, show.ctm).direction
    if target_bbox is None:
        # ``old_advance``/``font_size`` are text space.  Build the metric
        # quad IN TEXT SPACE (advance along the baseline, ascent toward
        # the ascender; below-baseline ≈ 0.35·size, above ≈ 1.0·size) and
        # map it through the show's full ``Tm × CTM`` and then
        # ``transformation_matrix × rotation_matrix`` — never a user-space
        # ``+x`` assumption.  PyMuPDF's ``transformation_matrix`` alone
        # does NOT include /Rotate — without the rotation term a /Rotate
        # 90/270 page keeps a horizontal halo while pixmap ink runs
        # vertically (V0d false-reject / false-accept risk).  For the
        # axis-aligned idiom this reproduces the historical halo exactly.
        th = show.hscale / 100.0
        target_bbox = map_text_quad_to_visual(
            page,
            show.tm,
            show.ctm,
            (
                0.0,
                -0.35 * show.font_size,
                old_advance * th,
                show.font_size,
            ),
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
        style_overrides=style_overrides,
        geometry_intent=(
            tuple(float(value) for value in new_rect)
            if new_rect is not None
            else None
        ),
        operand_kind=operand_kind,
        trm_direction=trm_direction,
    )


def _build_tier0(
    classified: _ClassifiedTarget, page: fitz.Page
) -> PreparedEdit | PlanRejection:
    """The advance-equality gate, plus the string-range splice and token."""
    show = classified.show
    # _classify_common already refused a None font_resource
    # (FONT_FACE_UNAVAILABLE); this is a type narrowing, not a new check.
    assert show.font_resource is not None
    # Raw-vs-raw advance equality is scale-invariant: the same positive Th
    # multiplies both sides, so the existing tolerance floors stay meaningful.
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
        replacement_bytes=(
            encode_hex_string(classified.replacement_encoded)
            if classified.operand_kind == "hex"
            else encode_literal_string(classified.replacement_encoded)
        ),
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
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
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
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
    )


def _grown_verify_bbox(
    page: fitz.Page,
    show: ShowOp,
    target_bbox_page: tuple[float, float, float, float],
    growth_advance: float,
) -> tuple[float, float, float, float]:
    """``target_bbox_page`` widened FORWARD along the show's transformed
    baseline by ``growth_advance`` effective-displacement points, mapped through the
    full page→visual matrix so /Rotate and /UserUnit are handled correctly
    by construction (same matrix as the fallback ``target_bbox`` in
    :func:`_classify_common`).

    The forward direction comes from the combined ``Tm × CTM`` baseline
    vector — never a user-space ``+x`` assumption.  The admitted family is
    quarter-turn only, so the user-space baseline is axis-aligned and the
    caller box's CROSS extent is preserved exactly (the growth strip
    inherits the target's own thickness, not the metric quad's).

    Returns ``target_bbox_page`` UNCHANGED (no round trip, no float noise)
    when there is no growth: callers rely on exact equality to decide
    ``PreparedEdit.has_ink_growth``.
    """
    if growth_advance <= 0.0:
        return target_bbox_page
    linear = combined_linear(show.tm, show.ctm)
    norm = math.hypot(linear[0], linear[1])
    if norm <= 0.0 or not math.isfinite(norm):
        # Unreachable for admitted shows (the binding gate refused these);
        # fail toward the historical axis assumption rather than crash.
        norm = 1.0
    ux = linear[0] / norm
    uy = linear[1] / norm
    growth_user = growth_advance * norm
    visual = _page_visual_matrix(page)
    user = fitz.Rect(*target_bbox_page) * ~visual
    if abs(ux) >= abs(uy):
        if ux >= 0.0:
            user.x1 = user.x1 + growth_user
        else:
            user.x0 = user.x0 - growth_user
    else:
        if uy >= 0.0:
            user.y1 = user.y1 + growth_user
        else:
            user.y0 = user.y0 - growth_user
    mapped = user * visual
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
    th = show.hscale / 100.0
    growth = max(
        0.0, classified.replacement_advance - classified.source_advance
    ) * th
    verify_bbox_page = _grown_verify_bbox(
        page, show, classified.target_bbox_page, growth
    )
    background_bbox_page = map_text_quad_to_visual(
        page,
        show.tm,
        show.ctm,
        (
            0.0,
            -0.35 * show.font_size,
            classified.source_advance * th,
            show.font_size,
        ),
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
        string_kind=classified.operand_kind,
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
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
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
        background_bbox_page=background_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        kern_adjustment=kern,
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
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
    evidence_cache: ReplayEvidenceCache | None = None,
) -> PreparedEdit | PlanRejection:
    """Classify once; try Tier 0, escalate to Tier 1 only on ADVANCE_MISMATCH.

    The single product both preview and commit consume, so a Tier 1
    candidate's token is automatically identical on both paths. Tier 0
    always runs first and always wins when it accepts.

    ``evidence_cache`` (P3-B) opts into session-scoped replay reuse --
    the preview keystroke loop passes its renderer-owned single-slot
    cache; every other caller stays ephemeral by default.
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
        evidence_cache=evidence_cache,
    )
    if isinstance(classified, PlanRejection):
        return classified

    tier0_result = _build_tier0(classified, page)
    if isinstance(tier0_result, PreparedEdit):
        return tier0_result
    if max_tier < 1 or tier0_result.reason not in _TIER1_ESCALATION_REASONS:
        return tier0_result
    return _build_tier1(classified, page)
