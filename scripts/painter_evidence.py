"""Painter-event evidence for the P4-B2 spike: devices, re-lex, cursor replay.

Builds, per page, the evidence the exact duplicate-painter arm consumes
(``plans/task15-p4b2-exact-painter-geometry-spike.md`` §4):

- :func:`derotated_page` — one derotated ``DisplayList`` plus the base
  matrix captured INSIDE the rotation-0 window (R8: ``transformation_matrix``
  drops the CropBox origin and UserUnit on rotated pages);
- :func:`run_glyph_device` — O1: per-glyph outline bounds from a custom
  ``FzDevice2`` calling ``fz_bound_glyph(span.font(), gid, trm)``, with the
  texttrace-compatible ``seqno`` so bboxlog entries line up;
- :func:`run_bboxlog` / :func:`run_texttrace` — O3 and the reference trace,
  both over the SAME display list (R1);
- :func:`tj_items` — per-item re-lex of a ``TJ`` operand from the show's own
  byte range (replay drops the kern numbers);
- :func:`predict_glyphs` — Identity-H cursor replay: where the painter's own
  text state puts every glyph origin.  Declared widths move the cursor
  only; nothing here bounds ink.

Read-only: the census page object is never touched (callers pass their own
document); the derotation window writes ``set_rotation`` on rotated pages
exactly as ``model/text_commit/interpretation.py`` does, and restores it.
"""
from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
from fitz import mupdf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import CidCapabilityFailure  # noqa: E402
from model.text_commit.fonts import FontCapability  # noqa: E402
from model.text_commit.pdf_lexer import (  # noqa: E402
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    lex_content_stream,
)
from model.text_commit.replay import ShowOp  # noqa: E402
from scripts.painter_geometry import (  # noqa: E402
    Matrix,
    Point,
    Rect,
    matrix_concat,
)

logger = logging.getLogger(__name__)

PREDICTION_SLUGS = (
    "no_cid_capability",
    "tj_relex_failed",
    "odd_byte_count",
    "gid_unresolved",
    "text_state_unusable",
)

TEXT_KINDS = {0: "fill", 1: "stroke", 3: "ignore"}


# ------------------------------------------------------- derotated page


@dataclass
class DerotatedPage:
    """One page's derotated display list and the matrices to read it."""

    page: fitz.Page | None
    text_list: fitz.DisplayList | None
    base_matrix: Matrix
    rotation: int
    rect: Rect
    bound_page_y1: float

    def release(self) -> None:
        self.text_list = None
        self.page = None


def derotated_page(page: fitz.Page) -> DerotatedPage:
    """Build the derotated ``DisplayList`` (annotations excluded) and
    capture the base matrix inside the rotation-0 window."""
    rotation = page.rotation

    def _capture() -> tuple[fitz.DisplayList, Matrix, Rect, float]:
        text_list = page.get_displaylist(annots=False)
        base = tuple(float(value) for value in page.transformation_matrix)
        rect = tuple(float(value) for value in page.rect)
        prect = mupdf.fz_bound_page(page.this)
        return text_list, base, rect, float(prect.y1)  # type: ignore[return-value]

    if rotation == 0:
        text_list, base, rect, y1 = _capture()
    else:
        page.set_rotation(0)
        try:
            text_list, base, rect, y1 = _capture()
        finally:
            page.set_rotation(rotation)
    return DerotatedPage(
        page=page,
        text_list=text_list,
        base_matrix=base,
        rotation=rotation,
        rect=rect,
        bound_page_y1=y1,
    )


def _run(interp: DerotatedPage, device: object) -> None:
    assert interp.text_list is not None, "released interpretation"
    try:
        mupdf.fz_run_display_list(
            interp.text_list.this,
            device,
            mupdf.FzMatrix(),
            mupdf.FzRect(mupdf.FzRect.Fixed_INFINITE),
            mupdf.FzCookie(),
        )
    finally:
        mupdf.fz_close_device(device)


# ------------------------------------------------------------ O1 device


@dataclass(frozen=True)
class TraceGlyph:
    """One painted glyph as MuPDF sees it (derotated page space)."""

    seqno: int  # texttrace/bboxlog sequence number of its fz_text
    kind: str  # "fill" | "stroke" | "ignore"
    gid: int
    ucs: int
    origin_user: Point  # display-list space (PDF user space)
    origin: Point  # page space (through the device ctm)
    bounds: Rect | None  # fz_bound_glyph placed by trm × ctm; None if degenerate
    wmode: int
    span_index: int  # index of the span within its fz_text
    item_index: int  # index of the item within its span


class _GlyphBoundsDevice(mupdf.FzDevice2):
    """Records per-glyph outline bounds for every text drawing call.

    Increments ``seqno`` on exactly the calls ``JM_new_texttrace_device`` and
    ``JM_new_bbox_device`` count, so ``seqno`` indexes the bboxlog entry of
    the same ``fz_text``.  Clip-text hooks are deliberately NOT registered:
    neither reference device counts them.
    """

    def __init__(self, out: list[TraceGlyph]) -> None:
        super().__init__()
        self.out = out
        self.seqno = 0
        self.use_virtual_fill_path()
        self.use_virtual_stroke_path()
        self.use_virtual_fill_text()
        self.use_virtual_stroke_text()
        self.use_virtual_ignore_text()
        self.use_virtual_fill_shade()
        self.use_virtual_fill_image()
        self.use_virtual_fill_image_mask()

    def _text(self, kind: str, text: object, ctm: object) -> None:
        ctm_ = mupdf.FzMatrix(ctm)
        span = text.head  # type: ignore[attr-defined]
        span_index = 0
        while span:
            wrapped = mupdf.FzTextSpan(span)
            trm = wrapped.trm()
            font = wrapped.font()
            wmode = int(wrapped.m_internal.wmode)
            for item_index in range(wrapped.m_internal.len):
                item = wrapped.items(item_index)
                gid = int(item.gid)
                if gid < 0:
                    # Continuation item (multi-codepoint ToUnicode): no glyph.
                    continue
                placed = mupdf.FzMatrix(trm.a, trm.b, trm.c, trm.d, item.x, item.y)
                glyph_rect = mupdf.fz_transform_rect(
                    mupdf.fz_bound_glyph(font, gid, placed), ctm_
                )
                origin = mupdf.fz_transform_point(
                    mupdf.fz_make_point(item.x, item.y), ctm_
                )
                bounds: Rect | None = (
                    float(glyph_rect.x0),
                    float(glyph_rect.y0),
                    float(glyph_rect.x1),
                    float(glyph_rect.y1),
                )
                assert bounds is not None
                if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    bounds = None
                self.out.append(
                    TraceGlyph(
                        seqno=self.seqno,
                        kind=kind,
                        gid=gid,
                        ucs=int(item.ucs),
                        origin_user=(float(item.x), float(item.y)),
                        origin=(float(origin.x), float(origin.y)),
                        bounds=bounds,
                        wmode=wmode,
                        span_index=span_index,
                        item_index=item_index,
                    )
                )
            span = span.next
            span_index += 1
        self.seqno += 1

    # Hook signatures follow ``JM_new_bbox_device_Device`` (ctx first).
    def fill_text(self, ctx, text, ctm, *args):  # type: ignore[no-untyped-def]
        self._text("fill", text, ctm)

    def stroke_text(self, ctx, text, stroke, ctm, *args):  # type: ignore[no-untyped-def]
        self._text("stroke", text, ctm)

    def ignore_text(self, ctx, text, ctm):  # type: ignore[no-untyped-def]
        self._text("ignore", text, ctm)

    def fill_path(self, ctx, *args):  # type: ignore[no-untyped-def]
        self.seqno += 1

    def stroke_path(self, ctx, *args):  # type: ignore[no-untyped-def]
        self.seqno += 1

    def fill_shade(self, ctx, *args):  # type: ignore[no-untyped-def]
        self.seqno += 1

    def fill_image(self, ctx, *args):  # type: ignore[no-untyped-def]
        self.seqno += 1

    def fill_image_mask(self, ctx, *args):  # type: ignore[no-untyped-def]
        self.seqno += 1


def run_glyph_device(interp: DerotatedPage) -> tuple[TraceGlyph, ...]:
    out: list[TraceGlyph] = []
    _run(interp, _GlyphBoundsDevice(out))
    return tuple(out)


def run_bboxlog(interp: DerotatedPage) -> tuple[tuple[str, Rect], ...]:
    """``Page.get_bboxlog()`` semantics over the derotated list (no layer
    labels: ``inc_layers=False`` keeps OCG names out of the evidence)."""
    rc: list = []
    _run(interp, fitz.JM_new_bbox_device(rc, False))
    return tuple(
        (str(code), tuple(float(value) for value in rect))  # type: ignore[misc]
        for code, rect in rc
    )


def run_texttrace(interp: DerotatedPage) -> list[dict]:
    """``Page.get_texttrace()`` semantics over the derotated list."""
    rc: list[dict] = []
    device = fitz.extra.JM_new_texttrace_device(rc)
    device.ptm = mupdf.FzMatrix(1, 0, 0, -1, 0, interp.bound_page_y1)
    _run(interp, device)
    return rc


# --------------------------------------------------------------- TJ re-lex


@dataclass(frozen=True)
class TjItem:
    kind: str  # "string" | "kern"
    value: bytes | float


def tj_items(stream: bytes, show: ShowOp) -> tuple[TjItem, ...] | None:
    """The show's operand as ordered string/kern items, re-lexed from the
    show's own byte range in ``stream``; ``None`` when the range does not
    reproduce the ShowOp's recorded operand (integrity failure)."""
    if not (0 <= show.string_start < show.string_end <= len(stream)):
        return None
    operand = stream[show.string_start : show.string_end]
    tokens = list(lex_content_stream(operand))
    items: list[TjItem] = []
    if show.operator == "TJ":
        if not tokens or tokens[0].kind is not TokenKind.ARRAY_OPEN:
            return None
        if tokens[-1].kind is not TokenKind.ARRAY_CLOSE:
            return None
        body = tokens[1:-1]
    else:
        body = tokens
    for token in body:
        raw = operand[token.start : token.end]
        if token.kind is TokenKind.WHITESPACE or token.kind is TokenKind.COMMENT:
            continue
        if token.kind is TokenKind.NUMBER:
            if show.operator != "TJ":
                return None
            try:
                items.append(TjItem("kern", float(raw)))
            except ValueError:
                return None
        elif token.kind is TokenKind.STRING:
            items.append(TjItem("string", decode_literal_string(raw)))
        elif token.kind is TokenKind.HEXSTRING:
            items.append(TjItem("string", decode_hex_string(raw)))
        else:
            return None
    strings = [item for item in items if item.kind == "string"]
    if len(strings) != show.array_item_count:
        return None
    if b"".join(item.value for item in strings) != show.decoded_bytes:  # type: ignore[misc]
        return None
    return tuple(items)


# ----------------------------------------------------------- cursor replay


@dataclass(frozen=True)
class PredictedGlyph:
    index: int
    cid: int
    gid: int
    cursor_x: float  # text space, Th applied, relative to the show origin
    origin_user: Point  # PDF user space (rise applied, like ShowOp.origin_user)


@dataclass(frozen=True)
class PredictedShow:
    glyphs: tuple[PredictedGlyph, ...]
    slug: str | None  # one of PREDICTION_SLUGS when the prediction is unusable


def predict_glyphs(
    show: ShowOp,
    capability: FontCapability | None,
    items: tuple[TjItem, ...] | None,
) -> PredictedShow:
    """Identity-H cursor replay for one show.

    ``tx = (w0/1000 · Tfs + Tc) · Th`` per glyph (PDF 32000-1 §9.4.4; ``Tw``
    never applies to 2-byte codes), TJ kerns ``−n/1000 · Tfs · Th``.  The
    glyph origin in text space is ``(cursor_x, Ts)``; in user space it is
    ``origin_user + cursor_x · (a, b)`` of ``Tm × CTM``.
    """
    if capability is None or capability.cid is None:
        return PredictedShow((), "no_cid_capability")
    if items is None:
        return PredictedShow((), "tj_relex_failed")
    size = show.font_size
    th = show.hscale / 100.0
    if not (math.isfinite(size) and math.isfinite(th) and math.isfinite(show.char_spacing)):
        return PredictedShow((), "text_state_unusable")
    cid_capability = capability.cid
    tm_ctm = matrix_concat(show.tm, show.ctm)
    if not all(math.isfinite(value) for value in tm_ctm):
        return PredictedShow((), "text_state_unusable")
    ax, bx = tm_ctm[0], tm_ctm[1]
    ox, oy = show.origin_user
    cursor = 0.0
    glyphs: list[PredictedGlyph] = []
    for item in items:
        if item.kind == "kern":
            cursor -= float(item.value) / 1000.0 * size * th  # type: ignore[arg-type]
            continue
        data = item.value
        assert isinstance(data, bytes)
        if len(data) % 2:
            return PredictedShow((), "odd_byte_count")
        for offset in range(0, len(data), 2):
            cid = int.from_bytes(data[offset : offset + 2], "big")
            gid = cid_capability.gid_for(cid)
            if isinstance(gid, CidCapabilityFailure):
                return PredictedShow((), "gid_unresolved")
            glyphs.append(
                PredictedGlyph(
                    index=len(glyphs),
                    cid=cid,
                    gid=gid,
                    cursor_x=cursor,
                    origin_user=(ox + cursor * ax, oy + cursor * bx),
                )
            )
            width = cid_capability.width_of_cid(cid)
            cursor += (width / 1000.0 * size + show.char_spacing) * th
    return PredictedShow(tuple(glyphs), None)


# ---------------------------------------------------------- font program


def embedded_program(doc: fitz.Document, font_xref: int) -> bytes | None:
    """The embedded font program bytes of ``font_xref`` (FontFile2 for the
    Identity-H/CIDFontType2 population), or ``None``.  The basefont name
    PyMuPDF returns alongside is dropped here (§10 privacy)."""
    try:
        _, _, _, buffer = doc.extract_font(font_xref)
    except (RuntimeError, ValueError, TypeError, mupdf.FzErrorBase):
        return None
    if not buffer:
        return None
    return bytes(buffer)

