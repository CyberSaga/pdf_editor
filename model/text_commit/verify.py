"""Post-commit verification for the high-fidelity tiers (V0a–V0e).

Every Tier 0 commit is re-proven, not assumed: stream bytes outside the
declared range, font resources, non-target span geometry, extracted text,
raster identity outside the target halo, and document reopenability.  Any
failure triggers revert in the engine.  Renders at 96 dpi compare exactly
(ε calibration 2026-07-18: zero pixel noise across repeated renders).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import fitz

from model.text_commit.dto import RejectReason
from model.text_commit.inspect import read_page_streams
from model.text_commit.plan import PreparedEdit

logger = logging.getLogger(__name__)

_VERIFY_DPI = 96
_HALO_MARGIN_PT = 2.0
_ORIGIN_TOL_PT = 0.1


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


def _span_origins(
    page: fitz.Page, exclude_bbox: tuple[float, float, float, float]
) -> tuple[tuple[float, float], ...]:
    origins: list[tuple[float, float]] = []
    x0, y0, x1, y1 = exclude_bbox
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                ox, oy = span["origin"]
                if x0 - 1.0 <= ox <= x1 + 1.0 and y0 - 1.0 <= oy <= y1 + 1.0:
                    continue  # target's own span (its glyph metrics may change)
                origins.append((round(ox, 1), round(oy, 1)))
    return tuple(sorted(origins))


def capture_page_state(
    doc: fitz.Document, page: fitz.Page, prepared: PreparedEdit
) -> PageState:
    pixmap = page.get_pixmap(dpi=_VERIFY_DPI)
    return PageState(
        streams=tuple(read_page_streams(doc, page)),
        fonts=tuple(page.get_fonts(full=True)),
        annots=tuple((a.xref, tuple(a.rect)) for a in page.annots()),
        nontarget_origins=_span_origins(page, prepared.target_bbox_page),
        pixmap_samples=bytes(pixmap.samples),
        pixmap_meta=(pixmap.width, pixmap.height, pixmap.stride, pixmap.n),
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


def verify_tier0_commit(
    doc: fitz.Document,
    page: fitz.Page,
    prepared: PreparedEdit,
    pre_state: PageState,
) -> tuple[str, ...] | VerificationFailure:
    """Prove the V0 post-conditions; return the verified-property list."""
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
    halo_rect = fitz.Rect(*prepared.target_bbox_page) + (
        -_HALO_MARGIN_PT,
        -_HALO_MARGIN_PT,
        _HALO_MARGIN_PT,
        _HALO_MARGIN_PT,
    )
    clip_text = page.get_text("text", clip=halo_rect)
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
    if _span_origins(page, prepared.target_bbox_page) != pre_state.nontarget_origins:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, "non-target span geometry changed"
        )

    # V0d — raster identity outside the halo (exact; calibrated ε = 0).
    post_pixmap = page.get_pixmap(dpi=_VERIFY_DPI)
    diff = _first_diff_outside_halo(pre_state, post_pixmap, prepared.target_bbox_page)
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
    try:
        reopened = fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
        page_count = reopened.page_count
        reopened.close()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase) as exc:
        return VerificationFailure(
            RejectReason.VERIFICATION_FAILED, f"document no longer opens: {exc}"
        )
    if page_count != doc.page_count:
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
