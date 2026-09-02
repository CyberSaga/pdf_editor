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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from fitz import mupdf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import CidCapabilityFailure  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.marked_content import (  # noqa: E402
    CLASS_OC_LAYER_HIDDEN,
    CLASS_OC_OCMD,
    classify_wrappers,
)
from model.text_commit.pdf_lexer import (  # noqa: E402
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    lex_content_stream,
)
from model.text_commit.replay import (  # noqa: E402
    PageReplay,
    ShowOp,
    replay_page_streams,
)
from scripts.painter_geometry import (  # noqa: E402
    OVERLAP_EPSILON,
    SAME_BASELINE_EPSILON,
    GeometryUnavailable,
    Matrix,
    OutlineOracle,
    Point,
    Rect,
    matrix_concat,
    place_text_rect,
    rect_is_empty,
    rect_union,
    rect_within,
    rects_overlap,
    render_mode_ladder,
    scale_units_to_text,
    strict_overlap_depths,
    transform_point,
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


# ------------------------------------------------------------- events

MISSING_WINDOW_REASONS = ("tr_clip", "ocg_or_absent", "decode_unsupported", "unknown")

EVENT_REASONS = (
    MISSING_WINDOW_REASONS
    + PREDICTION_SLUGS
    + (
        "multiple_windows",
        "oracle_disagreement",
        "oracle_unavailable",
        "vertical_writing",
        "fz_text_shared",
        "target_unproven",
        "conservative_overlap",
        "no_event",
    )
)

RENDER_MODE_KEYS = tuple(f"render_mode.{mode}" for mode in range(8)) + ("render_mode.other",)

EVIDENCE_COUNTER_KEYS = (
    (
        "shows",
        "events_exact",
        "events_conservative",
        "events_ambiguous",
        "events_unavailable",
        "glyphs_traced",
        "glyphs_attributed",
        "unattributed_glyphs",
        "oracle_disagreement",
        "oracle_unavailable",
        "verdict_invariant_ambiguity",
        "multiple_windows",
        "form_xobject_pages",
        "font_has_fpgm_prep",
    )
    + tuple(f"missing_window.{reason}" for reason in MISSING_WINDOW_REASONS)
    + RENDER_MODE_KEYS
)

ORIGIN_TOLERANCE_PER_POINT = 1e-3
ORACLE_TOLERANCE = 0.02
PAINT_KINDS = ("fill", "stroke")


@dataclass(frozen=True)
class GlyphPaint:
    """One glyph of one show, as painted (page space, derotated)."""

    index: int
    cid: int
    gid: int
    origin: Point
    bounds: Rect | None  # O1; None = empty outline (paints nothing)
    bounds_o2_lower: Rect | None
    bounds_o2_upper: Rect | None
    quality: str  # "exact" | "ambiguous" | "unavailable"

    @property
    def empty(self) -> bool:
        return self.bounds is None


@dataclass(frozen=True)
class PainterEvent:
    """What one ShowOp provably painted."""

    seq: int
    stream_xref: int
    op_start: int
    operator: str
    render_mode: int
    font_xref: int | None
    glyphs: tuple[GlyphPaint, ...]
    proof_quality: str  # PROOF_QUALITIES
    reason: str | None  # EVENT_REASONS
    seqnos: tuple[int, ...]
    conservative_rect: Rect | None
    paints: bool
    origin: Point  # page space, first glyph (or predicted) origin
    baseline_dir: Point  # unit vector along the baseline, page space

    def glyph_union(self) -> Rect | None:
        rects = [glyph.bounds for glyph in self.glyphs if glyph.bounds is not None]
        if not rects:
            return None
        return rect_union(rects)

    def ink_rects(self) -> tuple[Rect, ...]:
        """Rects that bound every ink this event can put on the page."""
        if not self.paints:
            return ()
        if self.proof_quality == "conservative":
            return () if self.conservative_rect is None else (self.conservative_rect,)
        return tuple(glyph.bounds for glyph in self.glyphs if glyph.bounds is not None)


@dataclass
class PagePainterEvidence:
    """One page's joined painter events plus closed-slug diagnostics."""

    base_matrix: Matrix
    rotation: int
    events: dict[tuple[int, int], PainterEvent]
    counters: Counter[str]
    unattributed_glyphs: int
    unattributed_rects: tuple[Rect, ...]
    builds: int = 1
    _interp: DerotatedPage | None = field(default=None, repr=False)

    def event_for(self, show: ShowOp) -> PainterEvent | None:
        return self.events.get((show.stream_xref, show.op_start))

    def release(self) -> None:
        if self._interp is not None:
            self._interp.release()
            self._interp = None


OracleCache = dict[int, "OutlineOracle | None"]


def _oracle_for(
    doc: fitz.Document, font_xref: int, cache: OracleCache, counters: Counter[str]
) -> OutlineOracle | None:
    if font_xref in cache:
        return cache[font_xref]
    oracle: OutlineOracle | None = None
    program = embedded_program(doc, font_xref)
    if program is not None:
        try:
            oracle = OutlineOracle(program)
        except GeometryUnavailable:
            oracle = None
    if oracle is not None and oracle.hinted:
        counters["font_has_fpgm_prep"] += 1
    cache[font_xref] = oracle
    return oracle


def _primary_kind(render_mode: int) -> str | None:
    if render_mode in (0, 2, 4, 6):
        return "fill"
    if render_mode in (1, 5):
        return "stroke"
    if render_mode == 3:
        return "ignore"
    return None  # 7 and anything else paints nothing the devices count


def _baseline_dir(show: ShowOp, base: Matrix) -> Point:
    full = matrix_concat(matrix_concat(show.tm, show.ctm), base)
    dx, dy = full[0], full[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0.0:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _window_matches(
    glyphs: tuple[TraceGlyph, ...],
    consumed: list[bool],
    start: int,
    kind: str,
    expected: list[tuple[int, Point]],
    tolerance: float,
) -> bool:
    seqno = glyphs[start].seqno
    for offset, (gid, origin) in enumerate(expected):
        glyph = glyphs[start + offset]
        if (
            consumed[start + offset]
            or glyph.kind != kind
            or glyph.seqno != seqno
            or glyph.gid != gid
            or abs(glyph.origin[0] - origin[0]) > tolerance
            or abs(glyph.origin[1] - origin[1]) > tolerance
        ):
            return False
    return True


def _find_windows(
    glyphs: tuple[TraceGlyph, ...],
    consumed: list[bool],
    cursor: int,
    kind: str,
    expected: list[tuple[int, Point]],
    tolerance: float,
    limit: int = 2,
) -> list[int]:
    n = len(expected)
    first_gid = expected[0][0]
    found: list[int] = []
    for start in range(cursor, len(glyphs) - n + 1):
        if glyphs[start].gid != first_gid or consumed[start]:
            continue
        if _window_matches(glyphs, consumed, start, kind, expected, tolerance):
            found.append(start)
            if len(found) >= limit:
                break
    return found


def _same_window_bounds(
    glyphs: tuple[TraceGlyph, ...], starts: list[int], length: int
) -> bool:
    reference = [glyphs[starts[0] + i].bounds for i in range(length)]
    for start in starts[1:]:
        for i in range(length):
            other = glyphs[start + i].bounds
            ref = reference[i]
            if (ref is None) != (other is None):
                return False
            if ref is not None and other is not None and not (
                rect_within(ref, other, 1e-6) and rect_within(other, ref, 1e-6)
            ):
                return False
    return True


def build_page_painter_evidence(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    registry: DocumentFontRegistry,
    replay: PageReplay | None = None,
    capabilities: dict[str, FontCapability] | None = None,
    oracles: OracleCache | None = None,
    wrapper_classes: dict[int, str] | None = None,
) -> PagePainterEvidence:
    """Join every replayed show of ``page`` to the glyphs MuPDF painted.

    One derotated display list, one glyph-device run and one bbox-device
    run per call (``builds == 1``).  Window search on ``(gid, origin)``
    forward from the previous match; never text equality.  Every failure
    is a closed slug on the event; nothing raises past this function
    except programming errors.
    """
    counters: Counter[str] = Counter()
    streams = read_page_streams(doc, page)
    stream_bytes = dict(streams)
    if replay is None:
        replay = replay_page_streams(streams, max_decoded_bytes=None)
    if capabilities is None:
        capabilities = registry.page_capabilities(page)
    if oracles is None:
        oracles = {}
    if wrapper_classes is None:
        wrapper_classes = classify_wrappers(doc, page, replay)
    interp = derotated_page(page)
    glyphs = run_glyph_device(interp)
    bboxlog = run_bboxlog(interp)
    base = interp.base_matrix
    if replay.has_xobject_invocation:
        counters["form_xobject_pages"] += 1
    counters["glyphs_traced"] += len(glyphs)
    consumed = [False] * len(glyphs)
    cursor = 0
    events: dict[tuple[int, int], PainterEvent] = {}

    def _emit(event: PainterEvent) -> None:
        events[(event.stream_xref, event.op_start)] = event
        counters[f"events_{event.proof_quality}"] += 1

    for show in replay.shows:
        counters["shows"] += 1
        mode = show.render_mode
        counters[f"render_mode.{mode}" if 0 <= mode <= 7 else "render_mode.other"] += 1
        capability = capabilities.get(show.font_resource or "")
        font_xref = capability.font_xref if capability is not None else None
        common = {
            "seq": show.seq,
            "stream_xref": show.stream_xref,
            "op_start": show.op_start,
            "operator": show.operator,
            "render_mode": mode,
            "font_xref": font_xref,
            "baseline_dir": _baseline_dir(show, base),
        }
        predicted_origin = transform_point(show.origin_user, base)

        def _fail(quality: str, reason: str, seqnos: tuple[int, ...] = ()) -> None:
            _emit(
                PainterEvent(
                    glyphs=(),
                    proof_quality=quality,
                    reason=reason,
                    seqnos=seqnos,
                    conservative_rect=None,
                    paints=True,
                    origin=predicted_origin,
                    **common,  # type: ignore[arg-type]
                )
            )

        items = tj_items(stream_bytes.get(show.stream_xref, b""), show)
        predicted = predict_glyphs(show, capability, items)
        if predicted.slug is not None:
            _fail("unavailable", predicted.slug)
            continue
        ladder = render_mode_ladder(mode)
        kind = _primary_kind(mode)
        if kind is None:
            counters["missing_window.tr_clip"] += 1
            _fail("ambiguous", "tr_clip")
            continue
        if not predicted.glyphs:
            _emit(
                PainterEvent(
                    glyphs=(),
                    proof_quality="exact",
                    reason=None,
                    seqnos=(),
                    conservative_rect=None,
                    paints=False,
                    origin=predicted_origin,
                    **common,  # type: ignore[arg-type]
                )
            )
            continue
        # A show under a hidden (or unresolved OCMD) optional-content wrapper
        # paints nothing the devices see; searching would let it steal an
        # identical later show's window (measured, commit 3).
        if any(
            wrapper_classes.get(wrapper_id) in (CLASS_OC_LAYER_HIDDEN, CLASS_OC_OCMD)
            for wrapper_id in show.mc_stack
        ):
            counters["missing_window.ocg_or_absent"] += 1
            _fail("ambiguous", "ocg_or_absent")
            continue
        expected = [
            (glyph.gid, transform_point(glyph.origin_user, base))
            for glyph in predicted.glyphs
        ]
        tolerance = ORIGIN_TOLERANCE_PER_POINT * max(abs(show.font_size), 1.0)
        windows = _find_windows(glyphs, consumed, cursor, kind, expected, tolerance)
        if not windows:
            reason = "ocg_or_absent" if show.mc_depth > 0 or show.mc_stack else "unknown"
            counters[f"missing_window.{reason}"] += 1
            _fail("ambiguous", reason)
            continue
        start = windows[0]
        n = len(expected)
        seqnos = [glyphs[start].seqno]
        for i in range(n):
            consumed[start + i] = True
        cursor = start + n
        counters["glyphs_attributed"] += n
        # Tr 2 / 6: the same fz_text is emitted again as a stroke.
        if mode in (2, 6):
            stroke_windows = _find_windows(
                glyphs, consumed, cursor, "stroke", expected, tolerance, limit=1
            )
            if stroke_windows and glyphs[stroke_windows[0]].seqno == seqnos[0] + 1:
                for i in range(n):
                    consumed[stroke_windows[0] + i] = True
                cursor = stroke_windows[0] + n
                seqnos.append(seqnos[0] + 1)
                counters["glyphs_attributed"] += n
        if len(windows) > 1:
            counters["multiple_windows"] += 1
            if _same_window_bounds(glyphs, windows, n):
                counters["verdict_invariant_ambiguity"] += 1
            _fail("ambiguous", "multiple_windows", tuple(seqnos))
            continue
        window = glyphs[start : start + n]
        if any(glyph.wmode != 0 for glyph in window):
            _fail("unavailable", "vertical_writing", tuple(seqnos))
            continue
        oracle = _oracle_for(doc, font_xref, oracles, counters) if font_xref else None
        th = show.hscale / 100.0
        paints: list[GlyphPaint] = []
        glyph_quality = "exact"
        for guess, traced in zip(predicted.glyphs, window):
            lower: Rect | None = None
            upper: Rect | None = None
            quality = "exact"
            if oracle is None:
                quality = "unavailable"
            else:
                try:
                    units = oracle.bounds(guess.gid)
                except GeometryUnavailable:
                    units = None
                if units is None:
                    quality = "unavailable"
                else:
                    if units.lower is not None and units.upper is not None:
                        lower = place_text_rect(
                            scale_units_to_text(units.lower, oracle.units_per_em, show.font_size, th),
                            guess.cursor_x,
                            show.rise,
                            show.tm,
                            show.ctm,
                            base,
                        )
                        upper = place_text_rect(
                            scale_units_to_text(units.upper, oracle.units_per_em, show.font_size, th),
                            guess.cursor_x,
                            show.rise,
                            show.tm,
                            show.ctm,
                            base,
                        )
                    # A degenerate placement (Tz 0, Tfs 0, singular Tm) paints
                    # nothing on every route: both oracles report "empty".
                    if lower is not None and rect_is_empty(lower):
                        lower = upper = None
                    o1 = traced.bounds
                    if (o1 is None) != (lower is None):
                        quality = "ambiguous"
                    elif o1 is not None and lower is not None and upper is not None:
                        if not (
                            rect_within(lower, o1, ORACLE_TOLERANCE)
                            and rect_within(o1, upper, ORACLE_TOLERANCE)
                        ):
                            quality = "ambiguous"
            if quality == "ambiguous":
                counters["oracle_disagreement"] += 1
                glyph_quality = "ambiguous"
            elif quality == "unavailable":
                counters["oracle_unavailable"] += 1
                if glyph_quality == "exact":
                    glyph_quality = "unavailable"
            paints.append(
                GlyphPaint(
                    index=guess.index,
                    cid=guess.cid,
                    gid=guess.gid,
                    origin=traced.origin,
                    bounds=traced.bounds,
                    bounds_o2_lower=lower,
                    bounds_o2_upper=upper,
                    quality=quality,
                )
            )
        origin = window[0].origin
        # Per-fz_text checks against the bbox device.
        entry_codes = [
            bboxlog[seqno][0] if 0 <= seqno < len(bboxlog) else None for seqno in seqnos
        ]
        fz_text_glyphs = sum(1 for glyph in glyphs if glyph.seqno == seqnos[0])
        shared = fz_text_glyphs != n
        if ladder == "exact":
            if glyph_quality == "ambiguous":
                _fail("ambiguous", "oracle_disagreement", tuple(seqnos))
                continue
            if glyph_quality == "unavailable":
                _fail("unavailable", "oracle_unavailable", tuple(seqnos))
                continue
            _emit(
                PainterEvent(
                    glyphs=tuple(paints),
                    proof_quality="exact",
                    reason=None,
                    seqnos=tuple(seqnos),
                    conservative_rect=None,
                    paints=any(not glyph.empty for glyph in paints),
                    origin=origin,
                    **common,  # type: ignore[arg-type]
                )
            )
        elif ladder == "stroke":
            expected_codes = ["fill-text", "stroke-text"] if mode == 2 else ["stroke-text"]
            if shared or entry_codes != expected_codes:
                _fail("ambiguous", "fz_text_shared", tuple(seqnos))
                continue
            rect = rect_union([bboxlog[seqno][1] for seqno in seqnos])
            union = rect_union([glyph.bounds for glyph in paints if glyph.bounds is not None])
            if not rect_is_empty(union) and not rect_within(union, rect, 0.0):
                _fail("ambiguous", "oracle_disagreement", tuple(seqnos))
                continue
            _emit(
                PainterEvent(
                    glyphs=tuple(paints),
                    proof_quality="conservative",
                    reason=None,
                    seqnos=tuple(seqnos),
                    conservative_rect=rect,
                    paints=True,
                    origin=origin,
                    **common,  # type: ignore[arg-type]
                )
            )
        elif ladder == "invisible":
            if entry_codes != ["ignore-text"] or any(g.kind != "ignore" for g in window):
                _fail("ambiguous", "unknown", tuple(seqnos))
                continue
            _emit(
                PainterEvent(
                    glyphs=tuple(paints),
                    proof_quality="exact",
                    reason=None,
                    seqnos=tuple(seqnos),
                    conservative_rect=None,
                    paints=False,
                    origin=origin,
                    **common,  # type: ignore[arg-type]
                )
            )
        else:  # clip modes 4-6: glyphs consumed above, verdict stays ambiguous
            counters["missing_window.tr_clip"] += 1
            _fail("ambiguous", "tr_clip", tuple(seqnos))

    unattributed = [
        glyph
        for glyph, used in zip(glyphs, consumed)
        if not used and glyph.kind in PAINT_KINDS and glyph.bounds is not None
    ]
    counters["unattributed_glyphs"] += len(unattributed)
    return PagePainterEvidence(
        base_matrix=base,
        rotation=interp.rotation,
        events=events,
        counters=counters,
        unattributed_glyphs=len(unattributed),
        unattributed_rects=tuple(glyph.bounds for glyph in unattributed if glyph.bounds),
        builds=1,
        _interp=interp,
    )


# ------------------------------------------------------------- verdict

VERDICT_KINDS = (
    "exact_safe",
    "exact_overlap_same_baseline",
    "exact_overlap_cross_baseline",
    "ambiguous",
    "unavailable",
    "error",
)

_VERDICT_RANK = {
    "exact_overlap_same_baseline": 0,
    "exact_overlap_cross_baseline": 1,
    "ambiguous": 2,
    "unavailable": 3,
    "exact_safe": 4,
}


@dataclass(frozen=True)
class ExactVerdict:
    kind: str  # VERDICT_KINDS
    reason: str | None
    twin_seq: int | None
    target_unproven: bool
    twin_ink_in_target_bbox: bool
    twin_kinds: tuple[str, ...]


def _pairwise_overlap(first: tuple[Rect, ...], second: tuple[Rect, ...]) -> bool:
    if not first or not second:
        return False
    union_a = rect_union(list(first))
    union_b = rect_union(list(second))
    depth_x, depth_y = strict_overlap_depths(union_a, union_b)
    if depth_x <= OVERLAP_EPSILON or depth_y <= OVERLAP_EPSILON:
        return False  # aggregate prefilter: provably apart on one axis
    return any(rects_overlap(a, b) for a in first for b in second)


def _same_baseline(target: PainterEvent, twin: PainterEvent) -> bool:
    dx, dy = target.baseline_dir
    ex, ey = twin.baseline_dir
    if abs(dx * ey - dy * ex) > 1e-6:
        return False
    vx = twin.origin[0] - target.origin[0]
    vy = twin.origin[1] - target.origin[1]
    return abs(dx * vy - dy * vx) <= SAME_BASELINE_EPSILON


def exact_duplicate_painter_verdict(
    evidence: PagePainterEvidence,
    target: ShowOp,
    twins: tuple[ShowOp, ...],
    *,
    target_bbox_page: Rect | None = None,
) -> ExactVerdict:
    """The exact arm of the duplicate-painter question for one target.

    Overlap > ambiguous > unavailable > safe across twins; the target's own
    per-glyph old-ink quads are the region (plan §4.5); never a verdict
    from an ambiguous join or an oracle disagreement.
    """
    target_event = evidence.event_for(target)
    if (
        target_event is None
        or target_event.proof_quality != "exact"
        or not target_event.paints
    ):
        quality = "unavailable" if (
            target_event is not None and target_event.proof_quality == "unavailable"
        ) else "ambiguous"
        reason = target_event.reason if target_event is not None else "no_event"
        return ExactVerdict(
            kind=quality,
            reason=reason or "target_unproven",
            twin_seq=None,
            target_unproven=True,
            twin_ink_in_target_bbox=False,
            twin_kinds=(),
        )
    target_rects = target_event.ink_rects()
    decided: list[tuple[str, str | None, int]] = []
    in_bbox = False
    for twin in twins:
        event = evidence.event_for(twin)
        if event is None:
            decided.append(("unavailable", "no_event", twin.seq))
            continue
        if target_bbox_page is not None and _pairwise_overlap(
            event.ink_rects(), (target_bbox_page,)
        ):
            in_bbox = True
        if event.proof_quality == "unavailable":
            decided.append(("unavailable", event.reason, twin.seq))
            continue
        if event.proof_quality == "ambiguous":
            decided.append(("ambiguous", event.reason, twin.seq))
            continue
        if not event.paints:
            decided.append(("exact_safe", None, twin.seq))
            continue
        overlaps = _pairwise_overlap(target_rects, event.ink_rects())
        if event.proof_quality == "conservative":
            decided.append(
                ("ambiguous", "conservative_overlap", twin.seq)
                if overlaps
                else ("exact_safe", None, twin.seq)
            )
            continue
        if not overlaps:
            decided.append(("exact_safe", None, twin.seq))
            continue
        kind = (
            "exact_overlap_same_baseline"
            if _same_baseline(target_event, event)
            else "exact_overlap_cross_baseline"
        )
        decided.append((kind, None, twin.seq))
    if not decided:
        return ExactVerdict("exact_safe", None, None, False, in_bbox, ())
    decided.sort(key=lambda row: _VERDICT_RANK[row[0]])
    kind, reason, seq = decided[0]
    return ExactVerdict(
        kind=kind,
        reason=reason,
        twin_seq=seq,
        target_unproven=False,
        twin_ink_in_target_bbox=in_bbox,
        twin_kinds=tuple(row[0] for row in decided),
    )
