"""Post-commit verification for the high-fidelity tiers (V0a–V0e).

Every Tier 0 commit is re-proven, not assumed: stream bytes outside the
declared range, font resources, non-target span geometry, extracted text,
raster identity outside the target halo, and document reopenability.  Any
failure triggers revert in the engine.  Renders at 96 dpi compare exactly
(ε calibration 2026-07-18: zero pixel noise across repeated renders).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, cast

import fitz

from model.text_commit.cid_fonts import PdfRef as CidPdfRef
from model.text_commit.cid_fonts import resolve_descendant as cid_resolve_descendant
from model.text_commit.dto import RejectReason
from model.text_commit.inspect import read_page_streams
from model.text_commit.interpretation import PageInterpretation

if TYPE_CHECKING:
    # Deferred: plan.py imports patch.py (for the Tier 1 composite builder),
    # and patch.py imports this module (for prove_source_resource_reuse), so
    # a runtime import here would close the cycle plan -> patch -> verify ->
    # plan. PreparedEdit is used only in annotations below, and
    # ``from __future__ import annotations`` (this file) makes that safe.
    from model.text_commit.plan import PreparedEdit

logger = logging.getLogger(__name__)

_VERIFY_DPI = 96
_HALO_MARGIN_PT = 2.0
_ORIGIN_TOL_PT = 0.1
_COLOR_TINT_TOLERANCE = 24  # max(rgb) - min(rgb) above this is a color tint, not gray
_SHADING_OPERATOR_RE = re.compile(rb"(?<![A-Za-z])sh(?![A-Za-z])")


@dataclass(frozen=True)
class VerificationFailure:
    reason: str
    detail: str


@dataclass(frozen=True)
class PageState:
    """Everything captured before the patch that verification compares to."""

    streams: tuple[tuple[int, bytes], ...]
    fonts: tuple[tuple, ...]
    annots: tuple[tuple[int, tuple[float, float, float, float]], ...]
    nontarget_origins: tuple[tuple[float, float], ...]
    pixmap_samples: bytes
    pixmap_meta: tuple[int, int, int, int]  # width, height, stride, n
    # Tier 1 ink-growth pre-proof: rawdict character count already occupying
    # the growth zone, captured PRE-EDIT (0 when the prepared edit has no ink
    # growth). Defaulted so every hand-built ``PageState`` in existing tests
    # keeps constructing unchanged.
    growth_zone_glyphs: int = 0
    # V0e's page-count baseline, captured PRE-PATCH. Comparing a post-patch
    # reading against a page_count read on the SAME post-patch document (the
    # pre-fix bug) is a tautology that can never fire; this is the only
    # value V0e may honestly compare against. Defaulted for the same reason
    # as ``growth_zone_glyphs`` above -- the spike helpers in
    # verify_tier1_strategy's test fixtures hand-build ``PageState`` and
    # never reach this comparison.
    page_count: int = 0


def _visual_bbox_to_dict_space(
    page: fitz.Page, bbox: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Convert a VISUAL (pixmap-space) bbox to the space ``get_text`` uses.

    ``target_bbox_page``/``verify_bbox`` are visual space (they must match
    ``page.get_pixmap`` for V0d's raster halo). But ``page.get_text``
    (``dict``/``rawdict``/``clip=``) stays in *unrotated* page space on
    ``/Rotate`` pages regardless (same quirk documented for annot geometry
    in docs/PITFALLS.md). ``page.derotation_matrix`` is the documented
    inverse of ``page.rotation_matrix`` (identity at rotation 0, so this is
    a no-op there) -- this is the read-side half of the same conversion
    ``model.pdf_text_edit._dict_space_to_visual`` does on the write side.
    """
    rect = (fitz.Rect(*bbox) * page.derotation_matrix).normalize()
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def _iter_span_origins(
    rawdict: Mapping[str, object],
) -> tuple[tuple[float, float], ...]:
    origins: list[tuple[float, float]] = []
    blocks = cast(list[dict[str, object]], rawdict["blocks"])
    for block in blocks:
        lines = cast(list[dict[str, object]], block.get("lines", []))
        for line in lines:
            spans = cast(list[dict[str, object]], line["spans"])
            for span in spans:
                ox, oy = cast(tuple[float, float], span["origin"])
                origins.append((ox, oy))
    return tuple(origins)


def _iter_nonspace_chars(
    rawdict: Mapping[str, object],
) -> tuple[tuple[str, float, float, float, float], ...]:
    chars: list[tuple[str, float, float, float, float]] = []
    blocks = cast(list[dict[str, object]], rawdict["blocks"])
    for block in blocks:
        lines = cast(list[dict[str, object]], block.get("lines", []))
        for line in lines:
            spans = cast(list[dict[str, object]], line["spans"])
            for span in spans:
                span_chars = cast(list[dict[str, object]], span["chars"])
                for char in span_chars:
                    value = cast(str, char["c"])
                    if value.isspace():
                        continue
                    x0, y0, x1, y1 = cast(
                        tuple[float, float, float, float], char["bbox"]
                    )
                    chars.append((value, x0, y0, x1, y1))
    return tuple(chars)


def _span_origins_from_values(
    page: fitz.Page,
    exclude_bbox: tuple[float, float, float, float],
    origins: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    retained: list[tuple[float, float]] = []
    x0, y0, x1, y1 = _visual_bbox_to_dict_space(page, exclude_bbox)
    for ox, oy in origins:
        if x0 - 1.0 <= ox <= x1 + 1.0 and y0 - 1.0 <= oy <= y1 + 1.0:
            continue  # target's own span (its glyph metrics may change)
        retained.append((round(ox, 1), round(oy, 1)))
    return tuple(sorted(retained))


def _span_origins(
    page: fitz.Page,
    exclude_bbox: tuple[float, float, float, float],
    *,
    rawdict: Mapping[str, object] | None = None,
) -> tuple[tuple[float, float], ...]:
    if rawdict is None:
        rawdict = cast(dict[str, object], page.get_text("rawdict"))
    return _span_origins_from_values(
        page, exclude_bbox, _iter_span_origins(rawdict)
    )


def capture_page_state(
    doc: fitz.Document,
    page: fitz.Page,
    prepared: PreparedEdit,
    *,
    interpretation: PageInterpretation | None = None,
    reuse_rawdict: bool = False,
) -> PageState:
    pixmap = (
        interpretation.pixmap(dpi=_VERIFY_DPI)
        if interpretation is not None
        else page.get_pixmap(dpi=_VERIFY_DPI)
    )
    rawdict: Mapping[str, object] | None = None
    growth_zone_glyphs = 0
    if prepared.has_ink_growth:
        if interpretation is not None:
            rawdict = interpretation.rawdict()
        elif reuse_rawdict:
            rawdict = cast(dict[str, object], page.get_text("rawdict"))
        if rawdict is None:
            growth_zone_glyphs = count_growth_zone_glyphs(
                page,
                target_bbox=prepared.target_bbox_page,
                verify_bbox=prepared.effective_verify_bbox,
            )
        else:
            growth_zone_glyphs = count_growth_zone_glyphs(
                page,
                target_bbox=prepared.target_bbox_page,
                verify_bbox=prepared.effective_verify_bbox,
                rawdict=rawdict,
            )
    if interpretation is not None and rawdict is None:
        rawdict = interpretation.rawdict()
    elif reuse_rawdict and rawdict is None:
        rawdict = cast(dict[str, object], page.get_text("rawdict"))
    return PageState(
        streams=tuple(read_page_streams(doc, page)),
        fonts=tuple(page.get_fonts(full=True)),
        annots=tuple((a.xref, tuple(a.rect)) for a in page.annots()),
        # Always the TARGET box, never the widened one: excluding more
        # origins here would weaken V0c's non-target-geometry proof (a real
        # neighbour span could then move undetected inside the growth band).
        nontarget_origins=_span_origins(
            page, prepared.target_bbox_page, rawdict=rawdict
        ),
        pixmap_samples=bytes(pixmap.samples),
        pixmap_meta=(pixmap.width, pixmap.height, pixmap.stride, pixmap.n),
        growth_zone_glyphs=growth_zone_glyphs,
        page_count=doc.page_count,
    )


def _halo_pixels(
    bbox: tuple[float, float, float, float]
) -> tuple[int, int, int, int]:
    scale = _VERIFY_DPI / 72.0
    x0, y0, x1, y1 = bbox
    return (
        int((x0 - _HALO_MARGIN_PT) * scale),
        int((y0 - _HALO_MARGIN_PT) * scale),
        int((x1 + _HALO_MARGIN_PT) * scale) + 1,
        int((y1 + _HALO_MARGIN_PT) * scale) + 1,
    )


def _first_diff_outside_halo(
    pre: PageState, post: fitz.Pixmap, bbox: tuple[float, float, float, float]
) -> tuple[int, int] | None:
    width, height, stride, n = pre.pixmap_meta
    if (post.width, post.height, post.stride, post.n) != (width, height, stride, n):
        return (-1, -1)
    hx0, hy0, hx1, hy1 = _halo_pixels(bbox)
    pre_samples = pre.pixmap_samples
    post_samples = bytes(post.samples)
    for y in range(height):
        row_pre = pre_samples[y * stride : (y + 1) * stride]
        row_post = post_samples[y * stride : (y + 1) * stride]
        if row_pre == row_post:
            continue
        if not (hy0 <= y <= hy1):
            for x in range(width):
                if row_pre[x * n : (x + 1) * n] != row_post[x * n : (x + 1) * n]:
                    return (x, y)
            continue
        for x in range(width):
            if hx0 <= x <= hx1:
                continue
            if row_pre[x * n : (x + 1) * n] != row_post[x * n : (x + 1) * n]:
                return (x, y)
    return None


def _verify_patch_postconditions(
    doc: fitz.Document,
    page: fitz.Page,
    prepared: PreparedEdit,
    pre_state: PageState,
    *,
    verify_bbox: tuple[float, float, float, float],
    interpretation: PageInterpretation | None = None,
    reopen_probe: bool = True,
    cached_reopen_probe_ok: bool | None = None,
) -> tuple[str, ...] | VerificationFailure:
    """Prove the V0 post-conditions; return the verified-property list.

    ``verify_bbox`` is the region V0c's extraction clip and V0d's raster
    halo are built around -- ``prepared.target_bbox_page`` for Tier 0
    (:func:`verify_tier0_commit`), or the ink-growth-widened box for Tier 1
    (:func:`verify_tier1_commit`).  V0c's ``_span_origins`` comparison stays
    on ``prepared.target_bbox_page`` regardless: it is compared against
    ``pre_state.nontarget_origins``, which :func:`capture_page_state` always
    computes with the (narrower) target box, and widening only one side of
    that comparison would either weaken the proof or spuriously reject an
    honest growth commit.

    ``cached_reopen_probe_ok`` matters only when ``reopen_probe`` is
    ``False`` (the preview scratch path): it is the verdict of a REAL
    ``encryption=KEEP`` round-trip probe run once on the *live* document at
    preview-session open (see ``preview._reopen_probe_verdict``), cached for
    the whole session.  The scratch itself is the DECRYPTED session
    snapshot, so it cannot see a KEEP round-trip failure on an encrypted
    live document at all -- consulting the cached live verdict here is what
    makes this branch an honest certificate instead of a structural-only
    check.  Fail-closed: anything but an explicit ``True`` refuses.
    """
    replacement = prepared.replacement

    # V0a — stream bytes outside the declared range are re-diffed, not assumed.
    post_streams = dict(read_page_streams(doc, page))
    for xref, pre_bytes in pre_state.streams:
        post_bytes = post_streams.get(xref)
        if post_bytes is None:
            return VerificationFailure(
                RejectReason.VERIFICATION_FAILED, f"stream {xref} disappeared"
            )
        if xref != replacement.stream_xref:
            if post_bytes != pre_bytes:
                return VerificationFailure(
                    RejectReason.VERIFICATION_FAILED,
                    f"non-target stream {xref} changed",
                )
            continue
        start, end = replacement.start, replacement.end
        new_len = len(replacement.replacement_bytes)
        if (
            post_bytes[:start] != pre_bytes[:start]
            or post_bytes[start : start + new_len] != replacement.replacement_bytes
            or post_bytes[start + new_len :] != pre_bytes[end:]
        ):
            return VerificationFailure(
                RejectReason.VERIFICATION_FAILED,
                "target stream changed outside the declared range",
            )

    # V0b — font resources and annotations are untouched.
    if tuple(page.get_fonts(full=True)) != pre_state.fonts:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "font resource table changed"
        )
    post_annots = tuple((a.xref, tuple(a.rect)) for a in page.annots())
    if post_annots != pre_state.annots:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "annotations changed"
        )

    # V0c — replacement extractable in the halo, source gone, neighbors fixed.
    halo_rect = fitz.Rect(*verify_bbox) + (
        -_HALO_MARGIN_PT,
        -_HALO_MARGIN_PT,
        _HALO_MARGIN_PT,
        _HALO_MARGIN_PT,
    )
    dict_space_halo_rect = fitz.Rect(*_visual_bbox_to_dict_space(page, tuple(halo_rect)))
    clip_text = (
        interpretation.clipped_text(dict_space_halo_rect)
        if interpretation is not None
        else page.get_text("text", clip=dict_space_halo_rect)
    )
    if prepared.replacement_text not in clip_text.replace("\n", " "):
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED,
            "replacement text not extractable at the target",
        )
    if (
        prepared.original_text not in prepared.replacement_text
        and prepared.original_text in clip_text.replace("\n", " ")
    ):
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "source text still present"
        )
    post_rawdict = interpretation.rawdict() if interpretation is not None else None
    if (
        _span_origins(
            page, prepared.target_bbox_page, rawdict=post_rawdict
        )
        != pre_state.nontarget_origins
    ):
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "non-target span geometry changed"
        )

    # V0d — raster identity outside the halo (exact; calibrated ε = 0).
    post_pixmap = (
        interpretation.pixmap(dpi=_VERIFY_DPI)
        if interpretation is not None
        else page.get_pixmap(dpi=_VERIFY_DPI)
    )
    diff = _first_diff_outside_halo(pre_state, post_pixmap, verify_bbox)
    if diff is not None:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED,
            f"pixels changed outside the target halo at {diff}",
        )

    # V0e — the mutated document still reopens.
    #
    # ``encryption=KEEP`` (never the default, which decrypts): calling
    # ``tobytes()`` with the default encryption directly on a *live*,
    # authenticated, encrypted document handle silently poisons its internal
    # crypt state (a measured PyMuPDF AES quirk -- the same one
    # ``PDFModel._decrypted_snapshot_bytes`` already guards against for
    # worker/print snapshots), so a later ``encryption=KEEP`` save on that
    # same handle would write content streams that no longer decrypt. This
    # probe only needs structural reopenability and the page count, not
    # decrypted content, so a locked reopen is just as good a proof and
    # never touches the live crypt state either way. KEEP is a no-op for
    # unencrypted documents.
    if reopen_probe:
        try:
            reopened = fitz.open(
                "pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
            )
            page_count = reopened.page_count
            reopened.close()
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase) as exc:
            return VerificationFailure(
                RejectReason.VERIFICATION_FAILED, f"document no longer opens: {exc}"
            )
    else:
        # A PlanPreviewRenderer's scratch document was itself opened from the
        # session snapshot.  The only mutation here is a validated in-place
        # content-stream splice, and V0a/V0c/V0d already exercise that stream
        # through extraction and rasterization.  Reusing this open-document
        # certificate avoids a full-document serialization per keystroke;
        # live commit always uses the real round-trip above.  It is NOT a
        # substitute for the KEEP-encryption round trip: that is proven
        # separately, once per session on the live document, and consulted
        # via ``cached_reopen_probe_ok`` immediately below.
        if not getattr(doc, "is_pdf", False):
            return VerificationFailure(
                RejectReason.VERIFICATION_FAILED,
                "session scratch document is not a PDF",
            )
        if cached_reopen_probe_ok is not True:
            return VerificationFailure(
                RejectReason.VERIFICATION_FAILED,
                "document no longer opens: session KEEP-encryption "
                "round-trip probe failed",
            )
        page_count = doc.page_count
    if page_count != pre_state.page_count:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "page count changed on reopen"
        )

    return (
        "stream_identity_outside_range",
        "font_resources_unchanged",
        "annotations_unchanged",
        "replacement_extractable",
        "nontarget_geometry_unchanged",
        "raster_identity_outside_halo",
        "document_reopens",
    )


def verify_tier0_commit(
    doc: fitz.Document,
    page: fitz.Page,
    prepared: PreparedEdit,
    pre_state: PageState,
    *,
    interpretation: PageInterpretation | None = None,
    reopen_probe: bool = True,
    cached_reopen_probe_ok: bool | None = None,
) -> tuple[str, ...] | VerificationFailure:
    """Prove the V0 post-conditions; return the verified-property list.

    Behaviour-identical wrapper: Tier 0 never grows the target box, so the
    postconditions are always proven around ``target_bbox_page`` itself.
    """
    return _verify_patch_postconditions(
        doc,
        page,
        prepared,
        pre_state,
        verify_bbox=prepared.target_bbox_page,
        interpretation=interpretation,
        reopen_probe=reopen_probe,
        cached_reopen_probe_ok=cached_reopen_probe_ok,
    )


# ================================================== Tier 1 growth machinery
#
# Slice 1's ink growth is admitted only when the growth zone is proven blank
# on the PRE-EDIT rendering by two complementary gates: a rawdict
# character-intersection gate (exact, text-only) and a raster uniformity
# gate (covers non-text ink). See plans/2026-07-18-acrobat-stable-text-
# commit-engine-v2.md and docs/PITFALLS.md for the halo/geometry rationale.

_GROWTH_EDGE_GUARD_PX = 1  # +1px: int() truncation makes the source bbox's
# own edge pixel column straddle the boundary; combined with the 1px AA
# guard already folded into _region_is_uniform's erosion story elsewhere,
# this keeps the growth probe from clipping into the source glyph's own
# anti-aliased edge.


def _clamp_pixels(
    meta: tuple[int, int, int, int], region: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Clamp an already pixel-space ``(x0, y0, x1, y1)`` rectangle to the
    pixmap's bounds, collapsing (never inverting) a rectangle that falls
    entirely outside."""
    width, height, _, _ = meta
    x0, y0, x1, y1 = region
    x0 = max(0, min(x0, width - 1))
    x1 = max(0, min(x1, width - 1))
    y0 = max(0, min(y0, height - 1))
    y1 = max(0, min(y1, height - 1))
    return (x0, y0, max(x0, x1), max(y0, y1))


def _expand_pixels(
    region: tuple[int, int, int, int], px: int
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = region
    return (x0 - px, y0 - px, x1 + px, y1 + px)


def _frame_strips(
    outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
) -> tuple[tuple[int, int, int, int], ...]:
    """The <=4 non-degenerate inclusive-pixel rectangles of ``outer`` minus
    ``inner`` (a donut decomposition): left, right, top, bottom strips, in
    that order, omitting any that collapse to nothing."""
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    cix0 = max(ix0, ox0)
    ciy0 = max(iy0, oy0)
    cix1 = min(ix1, ox1)
    ciy1 = min(iy1, oy1)
    strips: list[tuple[int, int, int, int]] = []
    if cix0 - 1 >= ox0 and oy1 >= oy0:
        strips.append((ox0, oy0, cix0 - 1, oy1))
    if ox1 >= cix1 + 1 and oy1 >= oy0:
        strips.append((cix1 + 1, oy0, ox1, oy1))
    if cix1 >= cix0 and ciy0 - 1 >= oy0:
        strips.append((cix0, oy0, cix1, ciy0 - 1))
    if cix1 >= cix0 and oy1 >= ciy1 + 1:
        strips.append((cix0, ciy1 + 1, cix1, oy1))
    return tuple(strips)


def growth_probe_regions(
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    meta: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], ...]:
    """Pixel-space probe regions a Tier 1 ink-growth commit must prove blank
    pre-edit: ``(V \\ guard(T))`` (new ink can land inside the old halo)
    UNION ``(halo(V) \\ halo(T))`` (pixels V0d's raster gate newly stops
    checking).  Empty when ``target_bbox == verify_bbox`` (no growth).

    ``guard(T)`` is ``T`` expanded by ``1 + _GROWTH_EDGE_GUARD_PX`` pixels
    (never ``halo(T)``): the ~1.5pt band just outside the source bbox is
    where growth ink is actually painted, so a probe boundary borrowed from
    the *occlusion* halo convention would silently admit ink there.
    """
    if tuple(target_bbox) == tuple(verify_bbox):
        return ()
    family_bbox = _frame_strips(
        _bbox_pixels(verify_bbox),
        _expand_pixels(_bbox_pixels(target_bbox), 1 + _GROWTH_EDGE_GUARD_PX),
    )
    family_halo = _frame_strips(_halo_pixels(verify_bbox), _halo_pixels(target_bbox))
    return tuple(_clamp_pixels(meta, region) for region in family_bbox + family_halo)


def _region_is_uniform_pixels(
    samples: bytes,
    meta: tuple[int, int, int, int],
    region: tuple[int, int, int, int],
    erode_px: int = 0,
) -> bool:
    """Pixel-space core of :func:`_region_is_uniform`: true when every pixel
    in the inclusive pixel rectangle ``region`` is the same color, after
    eroding inward by ``erode_px`` on each side."""
    _, _, stride, n = meta
    x0, y0, x1, y1 = region
    ex0, ey0 = x0 + erode_px, y0 + erode_px
    ex1, ey1 = x1 - erode_px, y1 - erode_px
    if ex0 <= ex1 and ey0 <= ey1:
        x0, y0, x1, y1 = ex0, ey0, ex1, ey1
    first: bytes | None = None
    for y in range(y0, y1 + 1):
        row = samples[y * stride : (y + 1) * stride]
        for x in range(x0, x1 + 1):
            pixel = row[x * n : (x + 1) * n]
            if first is None:
                first = pixel
            elif pixel != first:
                return False
    return True


@dataclass(frozen=True)
class _GrowthProbeFailure:
    region: tuple[int, int, int, int]
    detail: str


def _pixel_rgb_at(
    samples: bytes, meta: tuple[int, int, int, int], x: int, y: int
) -> tuple[int, ...]:
    _, _, stride, n = meta
    row = samples[y * stride : (y + 1) * stride]
    pixel = row[x * n : (x + 1) * n]
    channels = min(3, n)
    return tuple(int(component) for component in pixel[:channels])


def _region_matches_reference_color(
    samples: bytes,
    meta: tuple[int, int, int, int],
    region: tuple[int, int, int, int],
    reference_rgb: tuple[int, ...],
) -> bool:
    x0, y0, x1, y1 = region
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if _pixel_rgb_at(samples, meta, x, y) != reference_rgb:
                return False
    return True


_REFERENCE_PROBE_OFFSETS_PT = (2.25, 3.0, 4.0, 5.0, 6.0)


def background_reference_points(
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    meta: tuple[int, int, int, int],
) -> tuple[tuple[int, int], ...]:
    """Candidate background sampling points (pixel space, in probe order).

    Each point is offered together with the implicit 3x3 neighbourhood
    :func:`_uniform_neighborhood_rgb` reads, and that neighbourhood is
    PROVABLY disjoint from ``halo(verify_bbox)`` -- the growth band plus its
    halo, i.e. exactly the region under proof.  Points sit immediately LEFT
    of the target's start, or ABOVE/BELOW the text line within one line's
    leading.  Never at the tail: sampling the "background reference" at
    ``target_bbox[2] + 2.25..5.0pt`` (pre-F1) put it INSIDE the growth band
    for every realistic Tier 1 growth, so a solid-colour band supplied its
    own reference and the colour gate degenerated into a cross-region
    consistency check that a black rectangle passed.

    Returns an empty tuple when the target is flush against the page edges
    on every side -- callers must treat that as REJECT, never as "no
    constraint".
    """
    width, height, _, _ = meta
    scale = _VERIFY_DPI / 72.0
    hx0, hy0, hx1, hy1 = _halo_pixels(verify_bbox)
    x_mid = int(((target_bbox[0] + target_bbox[2]) / 2.0) * scale)
    y_mid = int(((target_bbox[1] + target_bbox[3]) / 2.0) * scale)

    candidates: list[tuple[int, int]] = []
    for offset_pt in _REFERENCE_PROBE_OFFSETS_PT:
        candidates.append(
            (int((target_bbox[0] - _HALO_MARGIN_PT - offset_pt) * scale), y_mid)
        )
    for offset_pt in _REFERENCE_PROBE_OFFSETS_PT:
        candidates.append(
            (x_mid, int((target_bbox[1] - _HALO_MARGIN_PT - offset_pt) * scale))
        )
    for offset_pt in _REFERENCE_PROBE_OFFSETS_PT:
        candidates.append(
            (x_mid, int((target_bbox[3] + _HALO_MARGIN_PT + offset_pt) * scale))
        )

    points: list[tuple[int, int]] = []
    for x, y in candidates:
        if not (1 <= x < width - 1 and 1 <= y < height - 1):
            continue  # the 3x3 neighbourhood would fall off the pixmap
        disjoint = (x + 1 < hx0) or (x - 1 > hx1) or (y + 1 < hy0) or (y - 1 > hy1)
        if not disjoint:
            continue
        if (x, y) not in points:
            points.append((x, y))
    return tuple(points)


def _uniform_neighborhood_rgb(
    samples: bytes, meta: tuple[int, int, int, int], x: int, y: int
) -> tuple[int, ...] | None:
    """The colour of the 3x3 neighbourhood around ``(x, y)``, or ``None``
    when it is not uniform.

    Fail-closed by construction: the pre-F1 version returned the median
    pixel of an ambiguous neighbourhood as an authoritative reference.
    """
    colors = {
        _pixel_rgb_at(samples, meta, x + dx, y + dy)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
    }
    if len(colors) != 1:
        return None
    return next(iter(colors))


def _target_background_rgb(
    pre_state: PageState, target_bbox: tuple[float, float, float, float]
) -> tuple[tuple[int, ...] | None, bool]:
    """``(background_rgb, ink_is_visible)`` read off the target's OWN bbox.

    The background is the strict-majority colour of the target's rendered
    bbox; text never covers half its own font-metric box, so a bbox with no
    majority colour (or one whose majority is 100% -- nothing but that
    colour) is not a surface this proof can reason about.  ``background_rgb``
    is ``None`` in the no-majority case and ``ink_is_visible`` is ``False``
    when the target's own ink cannot be seen against it (the black-on-black
    case: the target is occluded, so the "surface it sits on" is unknowable).
    """
    x0, y0, x1, y1 = _clamped_region(pre_state.pixmap_meta, target_bbox)
    counts: dict[tuple[int, ...], int] = {}
    total = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            rgb = _pixel_rgb_at(pre_state.pixmap_samples, pre_state.pixmap_meta, x, y)
            counts[rgb] = counts.get(rgb, 0) + 1
            total += 1
    if not total:
        return None, False
    background, hits = max(counts.items(), key=lambda item: item[1])
    if hits * 2 <= total:
        return None, False
    return background, hits < total


def _reference_confirms_background(
    pre_state: PageState,
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    background_rgb: tuple[int, ...],
) -> bool:
    """True when at least one sampling point OUTSIDE the growth band and its
    halo carries the target's own background colour -- the proof that the
    surface the target sits on actually extends past the target."""
    for x, y in background_reference_points(
        target_bbox, verify_bbox, pre_state.pixmap_meta
    ):
        rgb = _uniform_neighborhood_rgb(
            pre_state.pixmap_samples, pre_state.pixmap_meta, x, y
        )
        if rgb is not None and rgb == background_rgb:
            return True
    return False


def _growth_zone_rect(
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
) -> fitz.Rect | None:
    """The forward growth strip in visual space, for ANY cardinal growth
    direction (Task 13 P2) — never a ``+x`` assumption.

    The direction is the DOMINANT edge by which ``verify_bbox`` extends
    beyond ``target_bbox``.  It is re-derived here from the two boxes
    alone (review F5: ``PreparedEdit.growth_direction`` is token-bound
    but not threaded into verify); the read agrees with the stored slug
    by construction because plan's ``_grown_verify_bbox`` extends exactly
    the one edge that slug names, and the dominant-edge read is immune to
    sub-point float slivers on the cross edges:

        right → target.x1 … verify.x1      left → verify.x0 … target.x0
        down  → target.y1 … verify.y1      up   → verify.y0 … target.y0
    """
    extents = (
        ("right", verify_bbox[2] - target_bbox[2]),
        ("left", target_bbox[0] - verify_bbox[0]),
        ("down", verify_bbox[3] - target_bbox[3]),
        ("up", target_bbox[1] - verify_bbox[1]),
    )
    direction, amount = max(extents, key=lambda pair: pair[1])
    if amount <= 0.0:
        return None
    cross_y = (
        min(target_bbox[1], verify_bbox[1]),
        max(target_bbox[3], verify_bbox[3]),
    )
    cross_x = (
        min(target_bbox[0], verify_bbox[0]),
        max(target_bbox[2], verify_bbox[2]),
    )
    if direction == "right":
        rect = fitz.Rect(target_bbox[2], cross_y[0], verify_bbox[2], cross_y[1])
    elif direction == "left":
        rect = fitz.Rect(verify_bbox[0], cross_y[0], target_bbox[0], cross_y[1])
    elif direction == "down":
        rect = fitz.Rect(cross_x[0], target_bbox[3], cross_x[1], verify_bbox[3])
    else:
        rect = fitz.Rect(cross_x[0], verify_bbox[1], cross_x[1], target_bbox[1])
    rect.normalize()
    if rect.is_empty:
        return None
    return rect


def _rects_overlap(a: fitz.Rect, b: fitz.Rect, *, tol: float = 1e-3) -> bool:
    a_norm = fitz.Rect(a)
    b_norm = fitz.Rect(b)
    a_norm.normalize()
    b_norm.normalize()
    ix0 = max(float(a_norm.x0), float(b_norm.x0))
    iy0 = max(float(a_norm.y0), float(b_norm.y0))
    ix1 = min(float(a_norm.x1), float(b_norm.x1))
    iy1 = min(float(a_norm.y1), float(b_norm.y1))
    return (ix1 - ix0) > tol and (iy1 - iy0) > tol


def _growth_rect_in_dict_space(page: fitz.Page, growth_rect: fitz.Rect) -> fitz.Rect:
    """``get_drawings``/``get_image_rects`` report UNROTATED page space on
    /Rotate pages (the same quirk as ``get_text``) — intersect there, not
    in the visual space the growth rect lives in (identity at /Rotate 0)."""
    return fitz.Rect(
        _visual_bbox_to_dict_space(
            page,
            (growth_rect.x0, growth_rect.y0, growth_rect.x1, growth_rect.y1),
        )
    )


def _drawings_intersect_growth(page: fitz.Page, growth_rect: fitz.Rect) -> bool | None:
    try:
        drawings = page.get_drawings()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    growth_dict = _growth_rect_in_dict_space(page, growth_rect)
    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is None:
            if drawing.get("items"):
                return None
            continue
        if _rects_overlap(fitz.Rect(rect), growth_dict):
            return True
    return False


def _images_intersect_growth(page: fitz.Page, growth_rect: fitz.Rect) -> bool | None:
    try:
        images = page.get_images(full=True)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    growth_dict = _growth_rect_in_dict_space(page, growth_rect)
    for image in images:
        xref = int(image[0])
        if xref <= 0:
            continue
        try:
            placements = page.get_image_rects(xref)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return None
        for placement in placements:
            if _rects_overlap(fitz.Rect(placement), growth_dict):
                return True
    return False


def _shading_presence(page: fitz.Page, doc: fitz.Document) -> bool | None:
    try:
        streams = read_page_streams(doc, page)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    return any(_SHADING_OPERATOR_RE.search(data) for _, data in streams)


def _occupancy_failure(
    page: fitz.Page,
    doc: fitz.Document,
    growth_rect: fitz.Rect,
    region: tuple[int, int, int, int],
) -> _GrowthProbeFailure | None:
    """The cheap, structural half of the growth proof.

    Blind to anything painted through a Form XObject, a tiling pattern or a
    soft mask -- which is exactly why it is an ADDITIONAL gate and never the
    proof itself; :func:`_growth_probe_failure` always runs the raster
    background proof afterwards.
    """
    drawings_overlap = _drawings_intersect_growth(page, growth_rect)
    if drawings_overlap is None:
        return _GrowthProbeFailure(region, "occupancy: could not inspect vector drawings")
    if drawings_overlap:
        return _GrowthProbeFailure(region, "occupancy: vector drawing intersects growth zone")

    images_overlap = _images_intersect_growth(page, growth_rect)
    if images_overlap is None:
        return _GrowthProbeFailure(region, "occupancy: could not inspect image placement")
    if images_overlap:
        return _GrowthProbeFailure(region, "occupancy: image intersects growth zone")

    shading_present = _shading_presence(page, doc)
    if shading_present is None:
        return _GrowthProbeFailure(region, "occupancy: could not inspect shading operators")
    if shading_present:
        return _GrowthProbeFailure(
            region, "occupancy: shading operator present; bounds are uncertain"
        )
    return None


def _growth_probe_failure(
    pre_state: PageState,
    *,
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    page: fitz.Page | None,
    doc: fitz.Document | None,
) -> _GrowthProbeFailure | None:
    regions = growth_probe_regions(target_bbox, verify_bbox, pre_state.pixmap_meta)
    if not regions:
        return None

    # -- cheap occupancy gates first: they need the live page/doc, and running
    # them ahead of the raster proof keeps their (more specific) detail as the
    # reported cause. When the caller has no page/doc the raster proof below
    # still runs, alone -- it is never gated on them.
    growth_rect = _growth_zone_rect(target_bbox, verify_bbox)
    if growth_rect is not None and page is not None and doc is not None:
        occupancy = _occupancy_failure(page, doc, growth_rect, regions[0])
        if occupancy is not None:
            return occupancy

    # -- the background proof, which STANDS ALONE. Establish what surface the
    # target itself sits on, prove that surface exists outside the growth band
    # too, then require the growth band to be that same surface.
    background_rgb, ink_visible = _target_background_rgb(pre_state, target_bbox)
    if background_rgb is None:
        return _GrowthProbeFailure(
            regions[0],
            "background: the target's own bbox has no majority background colour",
        )
    if not ink_visible:
        return _GrowthProbeFailure(
            regions[0],
            "background: the target's own ink is not visible against its "
            "background, so the surface it sits on cannot be proven",
        )
    if not _reference_confirms_background(
        pre_state, target_bbox, verify_bbox, background_rgb
    ):
        return _GrowthProbeFailure(
            regions[0],
            "background: no sampling point outside the growth band and its "
            "halo carries the target's background colour",
        )

    for region in regions:
        if not _region_is_uniform_pixels(
            pre_state.pixmap_samples, pre_state.pixmap_meta, region, erode_px=0
        ):
            return _GrowthProbeFailure(
                region, f"raster: growth probe region {region} is not uniform pre-edit"
            )
        if not _region_matches_reference_color(
            pre_state.pixmap_samples, pre_state.pixmap_meta, region, background_rgb
        ):
            return _GrowthProbeFailure(
                region,
                f"background: growth probe region {region} is uniform but is "
                "not the target's own background colour",
            )

    return None


def prove_growth_region_blank(
    pre_state: PageState,
    *,
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    page: fitz.Page | None = None,
    doc: fitz.Document | None = None,
) -> tuple[int, int, int, int] | None:
    """The first growth probe region that fails the blankness proof, or
    ``None`` when all probe regions are proven blank.

    The proof is stricter than uniformity: each region must carry the same
    colour as the writable background surface the TARGET sits on, sampled
    only at points provably outside the growth band and its halo.  When
    ``page``/``doc`` are provided the region must additionally be free of
    non-text occupancy (drawings/images) and shading uncertainty -- cheap
    extra gates, not the proof.
    """
    failure = _growth_probe_failure(
        pre_state,
        target_bbox=target_bbox,
        verify_bbox=verify_bbox,
        page=page,
        doc=doc,
    )
    if failure is None:
        return None
    return failure.region


def count_growth_zone_glyphs(
    page: fitz.Page,
    *,
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    rawdict: Mapping[str, object] | None = None,
) -> int:
    """Count of non-whitespace rawdict characters already occupying the
    growth zone -- the forward strip between the target's growth-side edge
    and the verify bbox's, for ANY cardinal growth direction
    (:func:`_growth_zone_rect`).

    A COUNT only, never text: this is the character half of the growth-
    blank proof, exact and size-independent, complementary to the raster
    gate (:func:`prove_growth_region_blank`), which also covers non-text ink.
    Excluding the target's own glyphs char-level (not span-level) matters
    because MuPDF usually merges the target and a same-line successor into
    ONE rawdict span.

    A char counts as the target's own only when it BOTH starts left of the
    target's right edge AND ends at or before it: a foreign wide glyph that
    starts left of ``tx1`` and runs on across the growth band satisfies only
    the first half, and was previously written off as the target's own.  The
    target's own last char ends exactly at ``tx1`` (which is the max of its
    chars' right edges), so it is still excluded.
    """
    if rawdict is None:
        rawdict = cast(dict[str, object], page.get_text("rawdict"))
    return _count_growth_zone_glyphs_from_values(
        page,
        target_bbox=target_bbox,
        verify_bbox=verify_bbox,
        chars=_iter_nonspace_chars(rawdict),
    )


def _count_growth_zone_glyphs_from_values(
    page: fitz.Page,
    *,
    target_bbox: tuple[float, float, float, float],
    verify_bbox: tuple[float, float, float, float],
    chars: tuple[tuple[str, float, float, float, float], ...],
) -> int:
    zone_visual = _growth_zone_rect(target_bbox, verify_bbox)
    if zone_visual is None:
        return 0
    # ``get_text`` bboxes stay in UNROTATED page space on /Rotate pages —
    # convert the zone and target (visual space) instead of every char.
    zone = fitz.Rect(
        _visual_bbox_to_dict_space(
            page, (zone_visual.x0, zone_visual.y0, zone_visual.x1, zone_visual.y1)
        )
    )
    target = fitz.Rect(_visual_bbox_to_dict_space(page, target_bbox))
    # The forward boundary in dict space: the zone edge adjacent to the
    # target (direction-agnostic — whichever cardinal side the shared
    # growth_direction put the strip on ends up adjacent by construction).
    adjacency = (
        ("x+", abs(zone.x0 - target.x1)),
        ("x-", abs(zone.x1 - target.x0)),
        ("y+", abs(zone.y0 - target.y1)),
        ("y-", abs(zone.y1 - target.y0)),
    )
    axis = min(adjacency, key=lambda pair: pair[1])[0]

    def _is_targets_own(bbox: tuple[float, float, float, float]) -> bool:
        # The target's own glyph sits behind the forward boundary (its
        # last char ENDS there); a foreign wide glyph that starts behind
        # the boundary but runs on across the growth band fails the
        # containment half and is counted.
        if axis == "x+":
            return bbox[0] < target.x1 - 0.5 and bbox[2] <= target.x1 + 0.5
        if axis == "x-":
            return bbox[2] > target.x0 + 0.5 and bbox[0] >= target.x0 - 0.5
        if axis == "y+":
            return bbox[1] < target.y1 - 0.5 and bbox[3] <= target.y1 + 0.5
        return bbox[3] > target.y0 + 0.5 and bbox[1] >= target.y0 - 0.5

    count = 0
    for _value, x0, y0, x1, y1 in chars:
        bbox = (x0, y0, x1, y1)
        if _is_targets_own(bbox):
            continue
        if bbox[2] <= zone.x0 or bbox[0] >= zone.x1:
            continue
        if bbox[3] <= zone.y0 or bbox[1] >= zone.y1:
            continue
        count += 1
    return count


def verify_tier1_commit(
    doc: fitz.Document,
    page: fitz.Page,
    prepared: PreparedEdit,
    pre_state: PageState,
    *,
    interpretation: PageInterpretation | None = None,
    reopen_probe: bool = True,
    cached_reopen_probe_ok: bool | None = None,
) -> tuple[str, ...] | VerificationFailure:
    """Tier 1 postconditions: the two growth gates, then V0's, widened.

    Two distinct detail prefixes (``"glyphs: "`` / ``"raster: "``) for the
    same :data:`~model.text_commit.dto.RejectReason.GROWTH_REGION_NOT_BLANK`
    so a test can pin WHICH gate fired -- a shared reason with only one
    emission site can survive deletion of the other gate (Task 10a).
    """
    if prepared.has_ink_growth:
        if pre_state.growth_zone_glyphs > 0:
            return VerificationFailure(
                RejectReason.GROWTH_REGION_NOT_BLANK,
                f"glyphs: {pre_state.growth_zone_glyphs} character(s) "
                "already occupy the growth zone",
            )
        probe_failure = _growth_probe_failure(
            pre_state,
            target_bbox=prepared.target_bbox_page,
            verify_bbox=prepared.effective_verify_bbox,
            page=page,
            doc=doc,
        )
        if probe_failure is not None:
            return VerificationFailure(
                RejectReason.GROWTH_REGION_NOT_BLANK,
                probe_failure.detail,
            )

    result = _verify_patch_postconditions(
        doc,
        page,
        prepared,
        pre_state,
        verify_bbox=prepared.effective_verify_bbox,
        interpretation=interpretation,
        reopen_probe=reopen_probe,
        cached_reopen_probe_ok=cached_reopen_probe_ok,
    )
    if isinstance(result, VerificationFailure):
        return result
    if prepared.has_ink_growth:
        return (*result, "growth_region_blank_pre_edit")
    return result


# ======================================================= Tier 1 spike support
#
# Everything below is read-only spike instrumentation for candidate Tier 1
# mutation strategies (plan Task 10). Nothing here is called by
# ``TieredCommitEngine``; Tier 1 stays flag-off.


@dataclass(frozen=True)
class StrategyVerdict:
    """Structured spike result: an impossible strategy is a recorded FAILED
    verdict (go/no-go input), never a skipped test."""

    strategy: str
    passed: bool
    failures: tuple[str, ...]
    evidence: tuple[str, ...]


def _bbox_pixels(bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    scale = _VERIFY_DPI / 72.0
    x0, y0, x1, y1 = bbox
    return (int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale))


def _clamped_region(
    meta: tuple[int, int, int, int], bbox: tuple[float, float, float, float]
) -> tuple[int, int, int, int]:
    width, height, _, _ = meta
    x0, y0, x1, y1 = _bbox_pixels(bbox)
    x0 = max(0, min(x0, width - 1))
    x1 = max(0, min(x1, width - 1))
    y0 = max(0, min(y0, height - 1))
    y1 = max(0, min(y1, height - 1))
    return (x0, y0, max(x0, x1), max(y0, y1))


_UNIFORM_ERODE_PX = 2  # shrink inward past the rendered edge's own anti-aliasing


def _region_is_uniform(
    samples: bytes,
    meta: tuple[int, int, int, int],
    bbox: tuple[float, float, float, float],
    *,
    erode_px: int = _UNIFORM_ERODE_PX,
) -> bool:
    """True when every pixel in ``bbox`` (tight, no halo) is the same color.

    Used to characterize occlusion: a target fully covered by later opaque
    painting renders as one flat color; a target that becomes visible does
    not. Eroded inward by ``erode_px`` first (default :data:`_UNIFORM_
    ERODE_PX`): a filled rect's own edge is anti-aliased against the page
    background, which would otherwise register as spurious non-uniformity
    having nothing to do with whether the *target* underneath is occluded.
    The Tier 1 growth probe passes ``erode_px=0``: skipping a border of a
    *blankness* probe (as opposed to an occlusion probe) is a false-accept
    hole, not a false-positive-avoidance measure.
    """
    return _region_is_uniform_pixels(
        samples, meta, _clamped_region(meta, bbox), erode_px
    )


def _darkest_pixel(
    samples: bytes,
    meta: tuple[int, int, int, int],
    bbox: tuple[float, float, float, float],
) -> tuple[int, ...] | None:
    """The lowest-luminance (RGB) pixel in ``bbox`` -- the glyph ink itself,
    as opposed to any lighter background/anti-aliasing halo around it."""
    _, _, stride, n = meta
    x0, y0, x1, y1 = _clamped_region(meta, bbox)
    darkest: tuple[int, ...] | None = None
    darkest_lum: float | None = None
    for y in range(y0, y1 + 1):
        row = samples[y * stride : (y + 1) * stride]
        for x in range(x0, x1 + 1):
            pixel = row[x * n : (x + 1) * n]
            channels = tuple(pixel[: min(3, n)])
            lum = sum(channels) / max(1, len(channels))
            if darkest_lum is None or lum < darkest_lum:
                darkest_lum = lum
                darkest = channels
    return darkest


def _has_color_tint(rgb: tuple[int, ...]) -> bool:
    if len(rgb) < 3:
        return False
    return max(rgb) - min(rgb) > _COLOR_TINT_TOLERANCE


def _resource_font_bindings(entries: object) -> dict[str, int]:
    bindings: dict[str, int] = {}
    for entry in entries:  # type: ignore[attr-defined]
        bindings[entry[4]] = int(entry[0])
    return bindings


def _ocg_membership_status(
    doc: fitz.Document, expected_text: str
) -> str:
    """Tri-state OCG membership check for ``expected_text``.

    Returns:
        ``"lost"`` — text survives turning every OCG off (was never scoped).
        ``"preserved"`` — text disappears when OCGs are off (membership holds).
        ``"unknown"`` — probe could not be evaluated (locked/encrypted, or any
        exception). Callers must never record unknown as preserved.

    OCG visibility does not affect a live, already-open page/pixmap or its
    text extraction -- it only takes effect after a ``tobytes()`` + reopen
    round trip, and only for a *second* round trip after ``set_layer`` is
    called on the reopened copy. Nothing here mutates the live ``doc``.
    """
    try:
        probe = fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return "unknown"
    try:
        if probe.needs_pass:
            # Encrypted and no password reaches this probe. Decrypting the
            # live handle to get a readable one would poison its crypt state
            # (see Task 10b KEEP note), so report unknown — not "preserved".
            return "unknown"
        ocgs = probe.get_ocgs()
        if not ocgs:
            return "preserved"
        probe.set_layer(-1, off=list(ocgs.keys()))
        data = probe.tobytes()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return "unknown"
    finally:
        probe.close()
    try:
        reopened = fitz.open("pdf", data)
        text = reopened.load_page(0).get_text()
        reopened.close()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return "unknown"
    return "lost" if expected_text in text else "preserved"


def _ocg_membership_lost(doc: fitz.Document, expected_text: str) -> bool:
    """Deprecated bool wrapper — prefer :func:`_ocg_membership_status`.

    ``True`` only for confirmed loss. ``False`` means preserved *or*
    unknown; do not treat False as proof of preservation.
    """
    return _ocg_membership_status(doc, expected_text) == "lost"


def verify_tier1_strategy(
    doc: fitz.Document,
    page: fitz.Page,
    pre_state: PageState,
    *,
    target_bbox: tuple[float, float, float, float],
    expected_text: str,
    strategy: str,
) -> StrategyVerdict:
    """Characterize one candidate Tier-1 mutation strategy's hazards.

    Not a Tier-0-style single pass/fail gate for one committed edit -- a
    spike instrument that records every hazard the strategy actually
    exhibits on one fixture (z-order, non-target stream/resource mutation,
    OCG membership, graphics-state bleed, extraction), reusing
    :func:`_first_diff_outside_halo`/:func:`_span_origins`/
    :func:`~model.text_commit.inspect.read_page_streams` exactly like
    :func:`verify_tier0_commit` does.  An impossible strategy comes back
    with ``passed=False`` and every failure it triggered -- never a
    skipped test.
    """
    failures: list[str] = []
    evidence: list[str] = []

    # -- non-target stream set: append always introduces a brand-new
    # content stream tacked onto /Contents; transplant never does.
    pre_stream_xrefs = {xref for xref, _ in pre_state.streams}
    post_stream_xrefs = {xref for xref, _ in read_page_streams(doc, page)}
    if post_stream_xrefs == pre_stream_xrefs:
        evidence.append("stream_set_unchanged")
    else:
        failures.append("content_stream_added")

    # -- font resource bindings: a resource name must keep resolving to the
    # same font xref; a naive append that rebinds the source's own resource
    # name to a freshly-embedded font is a resource-identity hazard.
    pre_bindings = _resource_font_bindings(pre_state.fonts)
    post_bindings = _resource_font_bindings(page.get_fonts(full=True))
    rebound = any(
        xref != post_bindings[name]
        for name, xref in pre_bindings.items()
        if name in post_bindings
    )
    if rebound:
        failures.append("resource_rebound")
    else:
        evidence.append("resource_binding_unchanged")

    # -- raster identity outside the declared target region (calibrated
    # ε = 0, same halo convention as V0d).
    post_pixmap = page.get_pixmap(dpi=_VERIFY_DPI)
    post_meta = (post_pixmap.width, post_pixmap.height, post_pixmap.stride, post_pixmap.n)
    post_samples = bytes(post_pixmap.samples)
    if _first_diff_outside_halo(pre_state, post_pixmap, target_bbox) is None:
        evidence.append("raster_identity_outside_halo")
    else:
        failures.append("raster_changed_outside_halo")

    # -- z-order/occlusion: if the target region was fully covered by later
    # opaque painting before the edit (one flat color), it must still be
    # after the edit -- an append that lands after that painting in
    # /Contents order resurfaces the (previously hidden) replacement.
    post_region_occluded: bool | None = None
    if pre_state.pixmap_meta == post_meta:
        pre_uniform = _region_is_uniform(
            pre_state.pixmap_samples, pre_state.pixmap_meta, target_bbox
        )
        post_uniform = _region_is_uniform(post_samples, post_meta, target_bbox)
        if pre_uniform:
            post_region_occluded = post_uniform
        if pre_uniform and not post_uniform:
            failures.append("z_order_changed")
        elif pre_uniform and post_uniform:
            evidence.append("z_order_preserved")

    # -- OCG (marked-content layer) membership (tri-state).
    ocg_status = _ocg_membership_status(doc, expected_text)
    if ocg_status == "lost":
        failures.append("ocg_membership_lost")
    elif ocg_status == "preserved":
        evidence.append("ocg_membership_preserved")
    else:
        evidence.append("ocg_membership_unknown")

    # -- graphics-state bleed: the replacement's own glyph ink should never
    # pick up an untracked fill color left dangling by a prior stream. Only
    # meaningful when the target is actually visible -- a target still
    # fully occluded by later opaque painting (the correct, z-order-
    # preserving outcome) has no ink pixel to sample; the covering paint's
    # own color is not the replacement's ink and must not be mistaken for
    # one.
    if post_region_occluded:
        evidence.append("glyph_ink_not_visible_ignored")
    else:
        darkest = _darkest_pixel(post_samples, post_meta, target_bbox)
        if darkest is not None and _has_color_tint(darkest):
            failures.append("graphics_state_bleed")
        else:
            evidence.append("glyph_ink_uncontaminated")

    # -- extraction, same halo convention as V0c.
    halo_rect = fitz.Rect(*target_bbox) + (
        -_HALO_MARGIN_PT,
        -_HALO_MARGIN_PT,
        _HALO_MARGIN_PT,
        _HALO_MARGIN_PT,
    )
    clip_text = page.get_text("text", clip=halo_rect).replace("\n", " ")
    if expected_text in clip_text:
        evidence.append("replacement_extractable")
    else:
        failures.append("replacement_not_extractable")

    return StrategyVerdict(
        strategy=strategy,
        passed=not failures,
        failures=tuple(failures),
        evidence=tuple(evidence),
    )


def prove_source_resource_reuse(
    doc: fitz.Document, page: fitz.Page, *, resource_name: str, source_font_xref: int
) -> bool:
    """Affirmative, xref-level proof that ``resource_name`` still resolves
    to the untouched source font object.

    The only thing allowed to justify ``SOURCE_RESOURCE_REUSED`` at Tier 1
    -- never inferred from face identity, byte equality of an extracted
    font program, or Unicode glyph coverage.  Any ambiguity (the resource
    is missing, or duplicated) defaults to ``False``.
    """
    matches = [
        entry for entry in page.get_fonts(full=True) if entry[4] == resource_name
    ]
    if len(matches) != 1:
        return False
    return int(matches[0][0]) == source_font_xref


_INDIRECT_REF_RE = re.compile(r"(\d+)\s+\d+\s+R")
_HEX_TOKEN_RE = re.compile(rb"<([0-9A-Fa-f]+)>")


def _first_indirect_ref(value: str) -> int | None:
    match = _INDIRECT_REF_RE.search(value)
    return int(match.group(1)) if match else None


def _hex_to_unicode(hex_digits: bytes) -> str:
    raw = bytes.fromhex(hex_digits.decode("ascii"))
    if len(raw) % 2:
        raw += b"\x00"
    return raw.decode("utf-16-be", errors="replace")


def _parse_tounicode(
    data: bytes,
) -> tuple[tuple[tuple[int, str], ...], tuple[tuple[int, int, str], ...]]:
    """Parse ``beginbfchar``/``beginbfrange`` entries of a /ToUnicode CMap.

    Only the single-destination forms (``<src> <dst>`` and
    ``<lo> <hi> <dst>``) are handled.  A bfrange block containing an
    array destination (``<lo> <hi> [<d1> <d2> ...]``) contributes NO
    mappings at all: striding a flat hex-token walk across one fabricates
    garbage ranges out of the array elements (Task 12 P0-D adversarial
    finding, docs/PITFALLS.md) — skipping the block keeps this legacy
    reader honest, and the strict P0-D grammar lives in
    ``cid_fonts.parse_tounicode_strict``.
    """
    bfchars: list[tuple[int, str]] = []
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.DOTALL):
        tokens = _HEX_TOKEN_RE.findall(block)
        for i in range(0, len(tokens) - 1, 2):
            bfchars.append((int(tokens[i], 16), _hex_to_unicode(tokens[i + 1])))

    bfranges: list[tuple[int, int, str]] = []
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.DOTALL):
        if b"[" in block:
            continue  # array-destination form: refuse, never fabricate
        tokens = _HEX_TOKEN_RE.findall(block)
        for i in range(0, len(tokens) - 2, 3):
            lo = int(tokens[i], 16)
            hi = int(tokens[i + 1], 16)
            bfranges.append((lo, hi, _hex_to_unicode(tokens[i + 2])))

    return tuple(bfchars), tuple(bfranges)


@dataclass(frozen=True)
class CidEncodingEvidence:
    """Read-only proof of a Type0/CID font's encoding.

    Every field is read straight from the font dictionary -- never
    inferred from a loaded face's Unicode glyph coverage.  ``bfchars``/
    ``bfranges`` are the parsed /ToUnicode CMap entries; use :meth:`decode`
    rather than reading them directly.
    """

    font_xref: int
    encoding: str  # e.g. "Identity-H", or an embedded CMap stream's xref
    cid_to_gid: str  # "Identity" (including the implicit default) or a stream xref
    has_widths: bool
    tounicode_xref: int
    bfchars: tuple[tuple[int, str], ...]
    bfranges: tuple[tuple[int, int, str], ...]

    def decode(self, cid: int) -> str | None:
        for code, text in self.bfchars:
            if code == cid:
                return text
        for lo, hi, first in self.bfranges:
            if lo <= cid <= hi and first:
                return first[:-1] + chr(ord(first[-1]) + (cid - lo))
        return None


def collect_cid_encoding_evidence(
    doc: fitz.Document, font_xref: int
) -> CidEncodingEvidence | VerificationFailure:
    """Read-only reader of a Type0/CID font's encoding evidence.

    Reads /Encoding (the Identity-H name or an embedded CMap stream xref),
    the descendant CIDFont's /CIDToGIDMap and /W presence, and a parsed
    /ToUnicode CMap (bfchar/bfrange) -- and nothing else.  Source encoding
    must never be inferred from a face's Unicode glyph coverage: a missing
    or unusable leg (most notably /ToUnicode) is a hard
    :class:`VerificationFailure`, even when the face could plainly render
    every target character.  Never mutates the document.
    """
    subtype_kind, subtype_value = doc.xref_get_key(font_xref, "Subtype")
    if subtype_kind != "name" or subtype_value != "/Type0":
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING,
            f"xref {font_xref} is not a Type0 font",
        )

    encoding_kind, encoding_value = doc.xref_get_key(font_xref, "Encoding")
    if encoding_kind == "name":
        encoding = encoding_value.lstrip("/")
    elif encoding_kind == "xref":
        encoding = encoding_value.split()[0]
    else:
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING, "font has no readable /Encoding"
        )

    # Task 12 P0-D: the descendant may be an indirect ref OR an inline
    # dictionary in the /DescendantFonts array — the inline form is the
    # census-DOMINANT corpus shape (256/262 fonts, AutoCAD; plan §8), so
    # rejecting it as unreadable would blind this reader to almost every
    # real Type0 font. Delegated to cid_fonts' bounded object parser.
    descendant_xref, descendant = cid_resolve_descendant(doc, font_xref)
    if descendant is None:
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING,
            "unreadable /DescendantFonts entry",
        )

    cid_to_gid_value = descendant.get("CIDToGIDMap")
    if isinstance(cid_to_gid_value, str) and cid_to_gid_value.startswith("/"):
        cid_to_gid = cid_to_gid_value.lstrip("/")
    elif isinstance(cid_to_gid_value, CidPdfRef):
        cid_to_gid = str(cid_to_gid_value.xref)
    else:
        cid_to_gid = "Identity"  # PDF spec 9.7.4.3 implicit default; absent != missing

    has_widths = descendant.get("W") is not None

    tounicode_kind, tounicode_value = doc.xref_get_key(font_xref, "ToUnicode")
    if tounicode_kind != "xref":
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING,
            "font has no readable /ToUnicode CMap stream",
        )
    tounicode_xref = _first_indirect_ref(tounicode_value)
    if tounicode_xref is None:
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING,
            "unreadable /ToUnicode reference",
        )
    tounicode_bytes = doc.xref_stream(tounicode_xref)
    if not tounicode_bytes:
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING,
            "/ToUnicode stream is empty or unreadable",
        )
    bfchars, bfranges = _parse_tounicode(tounicode_bytes)
    if not bfchars and not bfranges:
        return VerificationFailure(
            RejectReason.FONT_UNSUPPORTED_ENCODING,
            "/ToUnicode CMap has no bfchar/bfrange entries",
        )

    return CidEncodingEvidence(
        font_xref=font_xref,
        encoding=encoding,
        cid_to_gid=cid_to_gid,
        has_widths=has_widths,
        tounicode_xref=tounicode_xref,
        bfchars=bfchars,
        bfranges=bfranges,
    )
