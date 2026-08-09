"""Red-light tests for Task 11 Slice 1 -- Tier 1 transplant+kern (plan
``plans/2026-08-09-task11-slice1-by-fable.md``).

Where Tier 0 refuses ``ADVANCE_MISMATCH``, Tier 1 splices
``[(new) K] TJ`` at the source ``Tj`` operator's whole byte range
(``show.op_start:show.op_end``), where the kern number ``K`` compensates
the advance delta so every following show provably keeps its origin.
NOTHING of Slice 1 is implemented yet -- every test below is expected to
fail (ImportError, TypeError, AttributeError, or a plain assertion) for a
missing-feature reason, never a broken fixture.

Field/function names below follow the ADJUDICATED design (plan.md
"Adjudicated design" section), which overrides the raw designer output
where the two disagree -- most importantly: ``PreparedEdit.growth_bbox_page``
(not ``declared_bbox_page``), a scalar ``new_advance > old_advance`` growth
predicate, and ``growth_zone_is_uniform(page, growth_bbox) -> bool`` (not
``check_growth_zone_blank(samples, meta, ...)``; renamed from
``growth_zone_is_blank`` after review -- the raster proof is uniformity,
not blankness, and the verified-property string says so honestly).

Gate placement (which API each test calls):

* ``font_size<=0``, the shared-content-stream guard, the growth-direction
  guard, and the page-boundary guard all live INSIDE ``prepare_plan`` (the
  planner) -- tested by calling ``prepare_plan`` directly.
* The growth-zone blankness proof is NOT in the planner (adjudication
  item 4): it runs in the three CALLERS -- ``engine.prepare`` (scratch),
  ``engine.commit`` (live), and ``PlanPreviewRenderer.render`` (preview
  scratch) -- so it is tested through ``TieredCommitEngine.prepare`` and
  the preview renderer, never through ``prepare_plan`` alone.

Most fixtures use a synthetic Helvetica /F1 whose /Widths declares a
uniform 600/1000 em for every printable ASCII code, so text-space advance
is exact arithmetic (``0.6 * font_size * len(text)``) rather than a
face-metric approximation -- this is what makes the kern-value and
growth-bbox assertions exact numbers instead of loose bounds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.engine as engine_module  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    page_fingerprint,
    read_page_streams,
    replay_page,
)
from model.text_commit.patch import (  # noqa: E402
    apply_patchset,
    build_advance_preserving_erase,
    build_reversal_patchset,
    build_transplant_replacement,
)
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.replay import ShowOp  # noqa: E402
from model.text_commit.verify import VerificationFailure, _region_is_uniform  # noqa: E402

# ------------------------------------------------------------- shared fixtures

_CHAR_WIDTH = 600.0  # /1000 em -- uniform across the whole printable range
_FIRST_CHAR = 32
_LAST_CHAR = 126
_CHAR_ADVANCE_AT_12PT = _CHAR_WIDTH / 1000.0 * 12.0  # 7.2pt/char at size 12


def _uniform_font_xref(doc: fitz.Document) -> int:
    """A Type1 Helvetica whose /Widths declares 600/1000 em for every code
    in [32, 126]. Text-space advance is then exactly
    ``0.6 * font_size * len(text)``, independent of which letters are used,
    so kern-value/growth-bbox assertions are exact arithmetic rather than
    face-metric approximations (and, for the font_size=0 gate test, string
    width is exactly 0.0 by table arithmetic, never a face-resolver guess).
    """
    count = _LAST_CHAR - _FIRST_CHAR + 1
    widths_src = "[" + " ".join(f"{_CHAR_WIDTH:g}" for _ in range(count)) + "]"
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        f"/Encoding /WinAnsiEncoding /FirstChar {_FIRST_CHAR} "
        f"/LastChar {_LAST_CHAR} /Widths {widths_src} >>",
    )
    return font_xref


def _uniform_doc(stream: bytes, *, width: float = 595.0, height: float = 842.0) -> fitz.Document:
    """One page, ``stream`` as its sole content, /F1 = uniform-width Helvetica."""
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = _uniform_font_xref(doc)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _chained_shows_doc() -> fitz.Document:
    """Three bare ``Tj`` shows in ONE BT/ET, NO positioning operator
    (Td/TD/Tm/T*) between them: "AAA" (the Tier 1 target), "     B" (5
    blank-rendering leading spaces -- the growth buffer -- then a single
    'B' marker), "C" (a single 'C' marker). Growth of up to 36pt (5 *
    7.2pt/space at size 12) lands in genuinely blank page space, which the
    tests using this fixture assert directly before exercising any claim.
    """
    stream = b"BT /F1 12 Tf 72 700 Td (AAA) Tj (     B) Tj (C) Tj ET"
    return _uniform_doc(stream)


def _first_char_origin(page: fitz.Page, char: str) -> tuple[float, float]:
    """Page-space origin of the first glyph matching single character ``char``.

    Per-CHARACTER origin, not the span origin: MuPDF coalesces adjacent
    same-style shows with no repositioning between them into ONE rawdict
    span, so a span-level origin lookup would silently return show 1's
    origin for every later show and stay insensitive to a kern sign flip.
    """
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    if ch["c"] == char:
                        return tuple(ch["origin"])
    raise AssertionError(f"character {char!r} not found on page")


def _pixmap_samples(page: fitz.Page) -> tuple[bytes, tuple[int, int, int, int]]:
    pixmap = page.get_pixmap(dpi=96)
    return bytes(pixmap.samples), (pixmap.width, pixmap.height, pixmap.stride, pixmap.n)


def _prepare(engine: TieredCommitEngine, page: fitz.Page, target: str, replacement: str, **kwargs):
    """``engine.prepare`` with the fallback-bbox idiom: ``expected_origin``/
    ``target_bbox`` both ``None`` so ``target_bbox_page`` is the PINNED
    fallback formula (``test_text_commit_structural_gates.py``), which
    every growth-arithmetic assertion in this file depends on. A caller-
    supplied bbox from a merged rawdict span would silently change what a
    growth-zone/kern assertion measures.
    """
    kwargs.setdefault("expected_origin", None)
    kwargs.setdefault("target_bbox", None)
    return engine.prepare(page, target_text=target, replacement_text=replacement, **kwargs)


def _synthetic_show(operator: str) -> tuple[bytes, ShowOp]:
    """A minimal, self-consistent ``ShowOp`` with the given operator.

    ``font_size``/``hscale`` are both nonzero so patch.py's PRE-EXISTING
    zero-guard (patch.py:176, "cannot compensate advance under zero font
    size or horizontal scale") cannot fire and hand the operator-guard
    tests a false green for the wrong reason.
    """
    stream_bytes = b"(AB) " + operator.encode("ascii")
    show = ShowOp(
        seq=0,
        operator=operator,
        stream_xref=1,
        op_start=0,
        op_end=len(stream_bytes),
        string_start=0,
        string_end=4,
        string_kind="literal",
        array_item_count=1,
        decoded_bytes=b"AB",
        font_resource="F1",
        font_size=12.0,
        tm=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        ctm=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        trm_uniform_scale=1.0,
        origin_user=(72.0, 700.0),
        origin_reliable=True,
        char_spacing=0.0,
        word_spacing=0.0,
        hscale=100.0,
        leading=0.0,
        rise=0.0,
        render_mode=0,
        in_bt=True,
        gs_depth=0,
        mc_depth=0,
    )
    return stream_bytes, show


STRICT_TARGET = "Price 2024"
STRICT_REPLACEMENT = "Price 2024 Extended"  # much wider: advance mismatch


def _add_strict_mode_page(doc: fitz.Document) -> fitz.Page:
    """Tier-0-eligible page (mirrors ``test_text_commit_persistence.
    _add_tier0_page``) whose growth zone -- blank space to the right of
    TARGET on its own line, page width 595 -- has ample room for a Tier 1
    transplant to compensate into."""
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 72 700 Td (" + STRICT_TARGET.encode() + b") Tj ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return page


# ------------------------------------------------------------- operator guards
#
# D9: build_advance_preserving_erase / build_transplant_replacement must
# raise ValueError unless show.operator == "Tj". Today NEITHER function
# checks show.operator at all, so calling them with "'" or '"' just
# SUCCEEDS -- pytest.raises reports "DID NOT RAISE", which is the correct
# Red for "no operator guard exists yet".


def test_operator_guard_advance_preserving_erase_refuses_prime():
    stream_bytes, show = _synthetic_show("'")
    with pytest.raises(ValueError, match="refused"):
        build_advance_preserving_erase(stream_bytes, show, consumed_advance=12.0)


def test_operator_guard_advance_preserving_erase_refuses_double_quote():
    stream_bytes, show = _synthetic_show('"')
    with pytest.raises(ValueError, match="refused"):
        build_advance_preserving_erase(stream_bytes, show, consumed_advance=12.0)


def test_operator_guard_transplant_replacement_refuses_prime():
    stream_bytes, show = _synthetic_show("'")
    with pytest.raises(ValueError, match="refused"):
        build_transplant_replacement(stream_bytes, show, b"[(X) 0.000000] TJ")


def test_operator_guard_transplant_replacement_refuses_double_quote():
    stream_bytes, show = _synthetic_show('"')
    with pytest.raises(ValueError, match="refused"):
        build_transplant_replacement(stream_bytes, show, b"[(X) 0.000000] TJ")


# ------------------------------------------------------- shared-content-stream


def test_shared_content_stream_refuses_both_tiers():
    """D10: a content stream referenced by more than one page's /Contents
    must refuse in the COMMON path, for both tiers. Red test uses an
    advance-MATCHING replacement ("AAA" -> "BBB", both 3 chars) so the
    guard is not masked by ADVANCE_MISMATCH -- deleting the guard would let
    this exact call succeed as a normal Tier 0 PreparedEdit.
    """
    doc = fitz.open()
    stream = b"BT /F1 12 Tf 72 700 Td (AAA) Tj ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    font_xref = _uniform_font_xref(doc)

    page1 = doc.new_page(width=595, height=842)
    doc.xref_set_key(page1.xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page1.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    page2 = doc.new_page(width=595, height=842)
    doc.xref_set_key(page2.xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page2.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")

    page1 = doc[0]
    assert page1.get_contents() == doc[1].get_contents(), "fixture: stream must be genuinely shared"

    registry = DocumentFontRegistry(doc)
    # existing-plumbing check: today's planner has no shared-stream guard,
    # so the advance-matching replacement plans cleanly -- the latent
    # Tier 0 hole D10 closes.
    baseline = prepare_tier0_plan(
        doc, page1,
        target_text="AAA", replacement_text="BBB",
        expected_origin=None, target_bbox=None, registry=registry,
    )
    assert isinstance(baseline, PreparedEdit), (
        f"fixture check: shared-stream page must still plan today: {baseline}"
    )

    from model.text_commit.plan import prepare_plan  # Slice 1: not implemented yet

    reason_code = getattr(RejectReason, "SHARED_CONTENT_STREAM", None)
    assert reason_code is not None, "RejectReason.SHARED_CONTENT_STREAM not defined yet"

    for max_tier in (0, 1):
        rejection = prepare_plan(
            doc, page1, max_tier=max_tier,
            target_text="AAA", replacement_text="BBB",
            expected_origin=None, target_bbox=None, registry=registry,
        )
        assert isinstance(rejection, PlanRejection), (max_tier, rejection)
        assert rejection.reason == reason_code
    doc.close()


# --------------------------------------------------------------- growth admission


def test_growth_zone_not_blank_refuses():
    """Growth-zone blankness proof lives in the CALLERS (engine.prepare),
    not in prepare_plan -- tested through TieredCommitEngine.prepare.
    "A" and "B" are two separate Tj shows glued together with no gap, so
    ANY growth of "A" immediately collides with "B"'s ink.
    """
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (A) Tj (B) Tj ET")
    page = doc[0]

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "A", "AAAA")
    assert isinstance(baseline, PlanRejection), baseline
    assert baseline.reason == RejectReason.ADVANCE_MISMATCH

    # existing-plumbing check: the growth zone really is occupied by "B"
    # ink pre-edit -- (79.2,130.0,100.8,146.2) is
    # target_bbox_page.x1 .. target_bbox_page.x1 + (new_advance-old_advance)
    # for old_advance=7.2 ("A"), new_advance=28.8 ("AAAA"), scale=1.
    samples, meta = _pixmap_samples(page)
    growth_zone = (79.2, 130.0, 100.8, 146.2)
    assert _region_is_uniform(samples, meta, growth_zone) is False, (
        "fixture check: the growth zone must contain B's ink pre-edit"
    )

    reason_code = getattr(RejectReason, "GROWTH_EXCEEDS_BLANK_REGION", None)
    assert reason_code is not None, "RejectReason.GROWTH_EXCEEDS_BLANK_REGION not defined yet"
    rejection = _prepare(engine, page, "A", "AAAA", max_tier=1)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == reason_code
    doc.close()


def test_growth_past_page_boundary_refuses():
    """The page-boundary check is inside prepare_plan's own Tier 1
    assembly (design step 7). Fixture: a narrow (60x100) otherwise-blank
    page, so the on-page portion of the growth zone stays blank and only
    the boundary gate can fire (adjudication item 6).
    """
    doc = _uniform_doc(b"BT /F1 12 Tf 10 50 Td (A) Tj ET", width=60.0, height=100.0)
    page = doc[0]
    assert page.rect.x1 == pytest.approx(60.0)

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "A", "A" * 15)
    assert isinstance(baseline, PlanRejection), baseline
    assert baseline.reason == RejectReason.ADVANCE_MISMATCH

    # existing-plumbing check: the on-page portion of the growth zone
    # (17.2..60.0, clipped to page.rect.x1) is genuinely blank -- an
    # otherwise-empty page -- so only the boundary gate can explain a
    # refusal here.
    samples, meta = _pixmap_samples(page)
    on_page_growth_zone = (17.2, 38.0, 60.0, 54.2)
    assert _region_is_uniform(samples, meta, on_page_growth_zone) is True, (
        "fixture check: the on-page growth-zone band must be blank"
    )

    from model.text_commit.plan import prepare_plan  # Slice 1: not implemented yet

    registry = DocumentFontRegistry(doc)
    reason_code = getattr(RejectReason, "GROWTH_PAST_PAGE_BOUNDARY", None)
    assert reason_code is not None, "RejectReason.GROWTH_PAST_PAGE_BOUNDARY not defined yet"
    rejection = prepare_plan(
        doc, page, max_tier=1,
        target_text="A", replacement_text="A" * 15,
        expected_origin=None, target_bbox=None, registry=registry,
    )
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == reason_code
    doc.close()


def test_growth_direction_unproven_refuses_rotated_page():
    """The growth-direction guard is inside prepare_plan (design step 2):
    growth (new_advance > old_advance) on a page whose transformation
    matrix is not a plain +x mapping (b != 0, or a <= 0) cannot trust the
    bbox-in-page-space formula, so it must refuse rather than mislocate the
    growth zone. Shrink is unaffected (not exercised here). The /Rotate 0
    control is a pure prepare_plan-level check (blankness never runs in
    prepare_plan), so it must return a PreparedEdit, not a rejection.
    """
    from model.text_commit.plan import prepare_plan  # Slice 1: not implemented yet

    rotated = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AA) Tj ET")
    rotated[0].set_rotation(90)
    rotated_page = rotated[0]  # re-fetch: transformation_matrix is read at page load
    # PyMuPDF 1.27.1's transformation_matrix property returns the UNROTATED
    # flip matrix whenever rotation % 360 != 0 (its own source hardcodes
    # Matrix(1, 0, 0, -1, 0, cropbox.height) on that branch — adjudicated
    # 2026-08-09, see PITFALLS), so the matrix can never witness the rotation
    # here.  The fixture property that matters is the rotation itself, which
    # is also what the production guard reads.
    assert rotated_page.rotation % 360 != 0, (
        "fixture check: the page must be genuinely rotated"
    )

    registry = DocumentFontRegistry(rotated)
    reason_code = getattr(RejectReason, "GROWTH_DIRECTION_UNPROVEN", None)
    assert reason_code is not None, "RejectReason.GROWTH_DIRECTION_UNPROVEN not defined yet"
    rejection = prepare_plan(
        rotated, rotated_page, max_tier=1,
        target_text="AA", replacement_text="AAAAAA",
        expected_origin=None, target_bbox=None, registry=registry,
    )
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == reason_code
    rotated.close()

    flat = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AA) Tj ET")
    flat_page = flat[0]
    matrix_flat = flat_page.transformation_matrix
    assert abs(matrix_flat.b) <= 1e-6 and matrix_flat.a > 0, (
        "fixture check: an unrotated page must be a plain +x mapping"
    )
    control = prepare_plan(
        flat, flat_page, max_tier=1,
        target_text="AA", replacement_text="AAAAAA",
        expected_origin=None, target_bbox=None, registry=DocumentFontRegistry(flat),
    )
    assert isinstance(control, PreparedEdit), control
    flat.close()


# ------------------------------------------------------------------ font_size


def test_font_size_zero_refused():
    """Refuter defect 2: nothing gated font_size<=0 before the kern
    computation divides by ``font_size * hscale``. Fixture keeps ONLY
    font_size off-nominal (Tc=1 creates a real, nonzero Tc-driven advance
    delta between "AA" and "AAA" even though the width table contributes
    exactly 0.0 at size 0 -- pure table arithmetic, no face-metric
    assumption). Common path: both max_tier values must refuse the same way.
    """
    from model.text_commit.plan import prepare_plan  # Slice 1: not implemented yet

    doc = _uniform_doc(b"BT /F1 0 Tf 1 Tc 72 700 Td (AA) Tj ET")
    page = doc[0]
    show = replay_page(doc, page).shows[0]
    assert show.font_size == 0.0
    assert show.char_spacing == 1.0
    assert show.font_resource == "F1"  # passes the "no font selected" gate
    assert (show.render_mode, show.rise, show.hscale) == (0, 0.0, 100.0)
    assert show.mc_depth == 0

    registry = DocumentFontRegistry(doc)
    # existing-plumbing check: today, with no font_size gate at all, Tier 0
    # measures a real (Tc-driven) advance delta at font_size 0 and refuses
    # on ADVANCE_MISMATCH -- it never divides by font_size, so it does not
    # crash. Only the NEW gate (both tiers) is supposed to catch this
    # earlier, with a font_size-specific reason.
    baseline = prepare_tier0_plan(
        doc, page,
        target_text="AA", replacement_text="AAA",
        expected_origin=None, target_bbox=None, registry=registry,
    )
    assert isinstance(baseline, PlanRejection), baseline
    assert baseline.reason == RejectReason.ADVANCE_MISMATCH

    for max_tier in (0, 1):
        rejection = prepare_plan(
            doc, page, max_tier=max_tier,
            target_text="AA", replacement_text="AAA",
            expected_origin=None, target_bbox=None, registry=registry,
        )
        assert isinstance(rejection, PlanRejection), (max_tier, rejection)
        assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
        assert "font_size" in rejection.detail
    doc.close()


# ------------------------------------------------------------- kern / origins


def test_tier1_kern_compensates_advance_delta():
    """(a) replacement extractable, (b) TJ array with the replacement
    literal + a kern number, (c) kern == -100000*(old-new)/(fs*hscale)
    formatted .6f, (d) splice range is op_start:op_end, not string_start:
    string_end.
    """
    doc = _chained_shows_doc()
    page = doc[0]
    show = replay_page(doc, page).shows[0]
    assert show.decoded_bytes == b"AAA"
    # op_end reaches past " Tj", strictly wider than the string-only range --
    # the fixture property (d) depends on: splice at op_start:op_end, not
    # string_start:string_end.
    assert show.op_end > show.string_end

    old_advance = 3 * _CHAR_ADVANCE_AT_12PT  # 21.6pt
    new_advance = 5 * _CHAR_ADVANCE_AT_12PT  # 36.0pt
    expected_kern = -100_000.0 * (old_advance - new_advance) / (show.font_size * show.hscale)
    assert expected_kern == pytest.approx(1200.0)

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.tier == 1
    assert prepared.old_advance == pytest.approx(old_advance)
    assert prepared.new_advance == pytest.approx(new_advance)
    assert prepared.kern_value == pytest.approx(expected_kern)
    assert prepared.replacement.start == show.op_start
    assert prepared.replacement.end == show.op_end
    # target_bbox_page fallback formula (structural_gates.py-pinned):
    # origin (72,142), page_size=12 -> (72, 130.0, 93.6, 146.2).
    assert prepared.target_bbox_page == pytest.approx((72.0, 130.0, 93.6, 146.2), abs=0.01)
    assert prepared.growth_bbox_page == pytest.approx((93.6, 130.0, 108.0, 146.2), abs=0.01)

    expected_bytes = b"[(AAAAA) " + f"{expected_kern:.6f}".encode("ascii") + b"] TJ"
    assert prepared.replacement.replacement_bytes == expected_bytes

    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    stream_after = doc.xref_stream(prepared.stream_xref)
    assert expected_bytes in stream_after
    assert "AAAAA" in doc[0].get_text()
    doc.close()


def test_tier1_preserves_subsequent_show_origins():
    """The headline claim: every following show provably keeps its origin.
    Fixture property pinned first (adjudication item 6): exactly three
    shows, no positioning operator between them (origin_reliable is False
    for shows 1 and 2 -- that IS "no Td/Tm/T* ran before this show").
    """
    doc = _chained_shows_doc()
    page = doc[0]

    replay = replay_page(doc, page)
    assert not replay.malformed
    assert len(replay.shows) == 3
    assert [s.decoded_bytes for s in replay.shows] == [b"AAA", b"     B", b"C"]
    assert replay.shows[0].origin_reliable is True
    assert replay.shows[1].origin_reliable is False, "fixture: no positioning op before show 2"
    assert replay.shows[2].origin_reliable is False, "fixture: no positioning op before show 3"

    b_before = _first_char_origin(page, "B")
    c_before = _first_char_origin(page, "C")

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome

    page = doc[0]
    b_after = _first_char_origin(page, "B")
    c_after = _first_char_origin(page, "C")
    assert b_after[0] == pytest.approx(b_before[0], abs=0.1)
    assert b_after[1] == pytest.approx(b_before[1], abs=0.1)
    assert c_after[0] == pytest.approx(c_before[0], abs=0.1)
    assert c_after[1] == pytest.approx(c_before[1], abs=0.1)

    # persistent text state after the replaced op is unchanged -- reflowed
    # by kern math alone, never by a Tc/Tw/Tz/Tf/Tr/Ts side channel.
    replay_after = replay_page(doc, page)
    show_b, show_c = replay_after.shows[1], replay_after.shows[2]
    for show in (show_b, show_c):
        assert (show.char_spacing, show.word_spacing, show.hscale) == (0.0, 0.0, 100.0)
        assert (show.font_size, show.render_mode, show.rise) == (12.0, 0, 0.0)
    doc.close()


def test_tier1_shrink_no_growth_claim():
    """Adjudication addition: a SHORTER replacement commits at tier 1
    without claiming growth evidence. Disjoint letters (AAAAA -> BB) so
    V0c's "original not in replacement" / "replacement extractable" checks
    do not interact via an accidental substring relationship.
    """
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AAAAA) Tj ET")
    page = doc[0]

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAAAA", "BB")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    prepared = _prepare(engine, page, "AAAAA", "BB", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.tier == 1
    assert prepared.new_advance < prepared.old_advance
    assert prepared.growth_bbox_page is None, "a shrink must not claim a growth zone"

    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert "growth_zone_proven_uniform" not in outcome.verified_properties
    text = doc[0].get_text()
    assert "BB" in text
    assert "AAAAA" not in text
    doc.close()


# ------------------------------------------------------------------- preview


def test_tier1_preview_token_equals_commit_token():
    doc = _chained_shows_doc()
    page = doc[0]

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    session = open_preview_session(doc, 0, "sess-1", max_tier=1)
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    request = PlanPreviewRequest(
        session_key="sess-1", generation=1,
        target_text="AAA", replacement_text="AAAAA",
        expected_origin=None, target_bbox=None,
        clip_rect=(0.0, 0.0, 595.0, 842.0), render_scale=1.0,
    )
    preview = renderer.render(request)
    renderer.close()
    assert preview.reject_reason is None, preview.reject_reason
    assert preview.plan_token is not None
    assert getattr(preview, "tier", None) == 1

    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.token == preview.plan_token
    doc.close()


def test_preview_growth_refusal_parity():
    """Adjudication addition: when the growth zone is occupied, the
    preview renderer AND engine.prepare refuse with the same reason code.
    Reuses the zero-gap "A"/"B" collision fixture (distinct from the
    preview-token-equality fixture, which needs an ADMITTED growth zone).
    """
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (A) Tj (B) Tj ET")
    page = doc[0]

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "A", "AAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    reason_code = getattr(RejectReason, "GROWTH_EXCEEDS_BLANK_REGION", None)
    assert reason_code is not None, "RejectReason.GROWTH_EXCEEDS_BLANK_REGION not defined yet"

    rejection = _prepare(engine, page, "A", "AAAA", max_tier=1)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == reason_code

    session = open_preview_session(doc, 0, "sess-1", max_tier=1)
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    request = PlanPreviewRequest(
        session_key="sess-1", generation=1,
        target_text="A", replacement_text="AAAA",
        expected_origin=None, target_bbox=None,
        clip_rect=(0.0, 0.0, 595.0, 842.0), render_scale=1.0,
    )
    preview = renderer.render(request)
    renderer.close()
    assert preview.reject_reason == reason_code
    assert preview.plan_token is None
    doc.close()


# ------------------------------------------------- undo / forced failure / outcome


def test_tier1_undo_restores_byte_identical_streams():
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AAA) Tj ET")
    page = doc[0]
    pre_streams = tuple(read_page_streams(doc, page))
    pre_fingerprint = page_fingerprint(doc, page)

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert "AAAAA" in doc[0].get_text()

    result = build_reversal_patchset(doc, doc[0], pre_streams, pre_fingerprint)
    assert result is not None
    _forward, inverse = result
    apply_patchset(doc, doc[0], inverse)

    post_streams = dict(read_page_streams(doc, doc[0]))
    for xref, data in pre_streams:
        assert post_streams[xref] == data
    text = doc[0].get_text()
    assert "AAA" in text and "AAAAA" not in text
    doc.close()


def test_tier1_forced_verification_failure_reverts(monkeypatch):
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AAA) Tj ET")
    page = doc[0]

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), (
        f"got {prepared!r}: engine.prepare does not accept max_tier yet (Slice 1 pending)"
    )
    assert getattr(prepared, "tier", 0) == 1

    stream_xref = doc[0].get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)

    def _fail_tier1(*_args, **_kwargs):
        return VerificationFailure(reason=RejectReason.VERIFICATION_FAILED, detail="injected")

    monkeypatch.setattr(engine_module, "verify_tier1_commit", _fail_tier1, raising=False)
    outcome = engine.commit(prepared)

    assert outcome.status is CommitStatus.FAILED, outcome
    assert doc.xref_stream(stream_xref) == stream_before
    assert "AAA" in doc[0].get_text()
    assert "AAAAA" not in doc[0].get_text()
    doc.close()


def test_tier1_outcome_reports_honest_tier_and_fallback():
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AAA) Tj ET")
    page = doc[0]

    engine = TieredCommitEngine(doc)
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    assert outcome.fallback_chain == ("tier0:advance_mismatch",)
    assert "compensated_transplant_kern" in outcome.warnings
    assert len(outcome.font_outcomes) == 1
    assert outcome.font_outcomes[0].action == FontResourceAction.SOURCE_RESOURCE_REUSED
    assert outcome.allows_external_reflow is False
    # This fixture grows (AAA -> AAAAA), so the growth-admission evidence
    # must be claimed -- and under its honest post-review name.
    assert "growth_zone_proven_uniform" in outcome.verified_properties
    doc.close()


# --------------------------------------------------------------- strict mode


def test_tier1_strict_mode_admits(tmp_path):
    pdf_path = tmp_path / "tier1_strict.pdf"
    doc = fitz.open()
    _add_strict_mode_page(doc)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", strict=True, max_tier=1)
    )
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    try:
        block = next(
            b for b in model.block_manager.get_blocks(0) if STRICT_TARGET in (b.text or "")
        )
        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), STRICT_REPLACEMENT, original_text=block.text,
        )
        assert result is EditTextResult.SUCCESS, (
            f"got {result!r}: settings.max_tier is not threaded through "
            "_attempt_tiered_commit / engine.prepare yet (Slice 1 pending)"
        )
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    finally:
        model.close()

    # backward-compat contrast: max_tier=0 strict still rejects the same edit.
    model0 = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", strict=True, max_tier=0)
    )
    model0.open_pdf(str(pdf_path))
    model0.ensure_page_index_built(1)
    try:
        block0 = next(
            b for b in model0.block_manager.get_blocks(0) if STRICT_TARGET in (b.text or "")
        )
        result0 = model0.edit_text(
            1, fitz.Rect(block0.layout_rect), STRICT_REPLACEMENT, original_text=block0.text,
        )
        assert result0 is EditTextResult.REJECTED_STRICT
    finally:
        model0.close()


# ------------------------------------------------------ backward-compat pin


def test_max_tier_0_byte_identical_advance_mismatch():
    """Backward-compat pin: the refactored ``prepare_plan(max_tier=0, ...)``
    must be BYTE-IDENTICAL (reason and detail) to today's
    ``prepare_tier0_plan`` -- equality of the frozen ``PlanRejection``, not
    just a substring pin, so a detail-string drift during the refactor is
    also caught.
    """
    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AAA) Tj ET")
    page = doc[0]
    registry = DocumentFontRegistry(doc)
    kwargs = dict(
        target_text="AAA", replacement_text="AAAA",  # growth: clean ADVANCE_MISMATCH
        expected_origin=None, target_bbox=None, registry=registry,
    )
    baseline = prepare_tier0_plan(doc, page, **kwargs)
    assert isinstance(baseline, PlanRejection), baseline
    assert baseline.reason == RejectReason.ADVANCE_MISMATCH
    assert "consumed advance would change by" in baseline.detail
    assert "Tier 0 must preserve it exactly" in baseline.detail

    from model.text_commit.plan import prepare_plan  # Slice 1: not implemented yet

    refactored = prepare_plan(doc, page, max_tier=0, **kwargs)
    assert refactored == baseline, "prepare_plan(max_tier=0) must be byte-identical to prepare_tier0_plan"
    doc.close()


# ------------------------------------------------------------------ composite


def test_tier1_composite_transplant_kern(monkeypatch):
    """The anchor composite test (plan.md "The composite Red test"): the
    whole Slice 1 candidate exercised end to end on one fixture --
    replacement renders and is kern-compensated, every later show retains
    its origin, persistent text state is unchanged, the exact splice range
    + stream digest are checked, preview parity holds, undo is byte-exact,
    a forced verification failure reverts everything, the outcome is
    honest, and the committed document reopens with the edit intact.
    """
    doc = _chained_shows_doc()
    page = doc[0]
    pre_streams = tuple(read_page_streams(doc, page))
    pre_fingerprint = page_fingerprint(doc, page)

    show = replay_page(doc, page).shows[0]
    assert show.decoded_bytes == b"AAA"
    old_advance = 3 * _CHAR_ADVANCE_AT_12PT
    new_advance = 5 * _CHAR_ADVANCE_AT_12PT
    expected_kern = -100_000.0 * (old_advance - new_advance) / (show.font_size * show.hscale)

    b_before = _first_char_origin(page, "B")
    c_before = _first_char_origin(page, "C")

    engine = TieredCommitEngine(doc)
    # existing-plumbing check: today's Tier 0 path refuses this edit.
    baseline = _prepare(engine, page, "AAA", "AAAAA")
    assert isinstance(baseline, PlanRejection) and baseline.reason == RejectReason.ADVANCE_MISMATCH

    # prepare the Tier 1 candidate; exact splice range pinned.
    prepared = _prepare(engine, page, "AAA", "AAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.tier == 1
    assert prepared.replacement.start == show.op_start
    assert prepared.replacement.end == show.op_end
    stream_before = doc.xref_stream(prepared.stream_xref)

    # preview token == commit-prepare token.
    session = open_preview_session(doc, 0, "sess-1", max_tier=1)
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    preview = renderer.render(PlanPreviewRequest(
        session_key="sess-1", generation=1,
        target_text="AAA", replacement_text="AAAAA",
        expected_origin=None, target_bbox=None,
        clip_rect=(0.0, 0.0, 595.0, 842.0), render_scale=1.0,
    ))
    renderer.close()
    assert preview.reject_reason is None, preview.reject_reason
    assert preview.plan_token == prepared.token

    # forced verification failure reverts everything, no side effects.
    def _fail_tier1(*_args, **_kwargs):
        return VerificationFailure(reason=RejectReason.VERIFICATION_FAILED, detail="injected")

    monkeypatch.setattr(engine_module, "verify_tier1_commit", _fail_tier1, raising=False)
    failed_outcome = engine.commit(prepared)
    monkeypatch.undo()
    assert failed_outcome.status is CommitStatus.FAILED, failed_outcome
    assert doc.xref_stream(prepared.stream_xref) == stream_before
    assert "AAA" in doc[0].get_text() and "AAAAA" not in doc[0].get_text()

    # the real commit: honest tier/fallback/warnings/font_outcomes.
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    assert outcome.fallback_chain == ("tier0:advance_mismatch",)
    assert "compensated_transplant_kern" in outcome.warnings
    assert len(outcome.font_outcomes) == 1
    assert outcome.font_outcomes[0].action == FontResourceAction.SOURCE_RESOURCE_REUSED
    assert outcome.allows_external_reflow is False
    assert outcome.verified_properties

    # replacement renders, kern splice landed exactly at op_start:op_end.
    stream_after = doc.xref_stream(prepared.stream_xref)
    expected_bytes = b"[(AAAAA) " + f"{expected_kern:.6f}".encode("ascii") + b"] TJ"
    assert expected_bytes in stream_after
    assert "AAAAA" in doc[0].get_text()

    # every later show retains its origin; persistent text state after the
    # op is unchanged.
    page = doc[0]
    b_after = _first_char_origin(page, "B")
    c_after = _first_char_origin(page, "C")
    assert b_after[0] == pytest.approx(b_before[0], abs=0.1)
    assert b_after[1] == pytest.approx(b_before[1], abs=0.1)
    assert c_after[0] == pytest.approx(c_before[0], abs=0.1)
    assert c_after[1] == pytest.approx(c_before[1], abs=0.1)
    replay_after = replay_page(doc, page)
    show_b = replay_after.shows[1]
    assert (show_b.char_spacing, show_b.word_spacing, show_b.hscale) == (0.0, 0.0, 100.0)
    assert (show_b.font_size, show_b.render_mode, show_b.rise) == (12.0, 0, 0.0)

    # the committed document reopens and the replacement persists.
    reopened = fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
    try:
        assert "AAAAA" in reopened[0].get_text()
    finally:
        reopened.close()

    # undo restores byte-identical streams.
    result = build_reversal_patchset(doc, doc[0], pre_streams, pre_fingerprint)
    assert result is not None
    _forward, inverse = result
    apply_patchset(doc, doc[0], inverse)
    post_streams = dict(read_page_streams(doc, doc[0]))
    for xref, data in pre_streams:
        assert post_streams[xref] == data
    assert "AAA" in doc[0].get_text() and "AAAAA" not in doc[0].get_text()

    doc.close()


# ------------------------------------------------- live growth re-check


def test_tier1_live_growth_recheck_catches_scratch_live_divergence():
    """``engine.commit`` re-proves growth-zone uniformity on the LIVE page
    (review mutation-gap 1): ``page_fingerprint`` covers annotation
    xref+rect but NOT annotation appearance-stream *content*, so rewriting
    an existing annotation's appearance between ``prepare()`` and
    ``commit()`` leaves the fingerprint identical -- the stale-plan gate
    cannot fire -- while inking the live growth zone. Deleting the live
    re-check in ``engine.commit`` turns this test Red: the commit would
    paint the replacement into occupied space.
    """
    from model.text_commit.inspect import page_fingerprint

    doc = _uniform_doc(b"BT /F1 12 Tf 72 700 Td (AA) Tj ET")
    page = doc[0]
    # Pre-existing annotation overlapping where the growth zone will land
    # ("AA" -> "AAAAAA": x in [86.4, 115.2] page space), with its
    # appearance blanked BEFORE prepare so the scratch proof passes.
    annot_rect = fitz.Rect(90, 132, 110, 144)
    annot = page.add_rect_annot(annot_rect)
    kind, value = doc.xref_get_key(annot.xref, "AP/N")
    assert kind == "xref", (kind, value)
    ap_xref = int(value.split()[0])
    doc.update_stream(ap_xref, b" ")

    engine = TieredCommitEngine(doc)
    prepared = _prepare(engine, page, "AA", "AAAAAA", max_tier=1)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.growth_bbox_page is not None
    assert fitz.Rect(prepared.growth_bbox_page).intersects(annot_rect), (
        "fixture check: the annotation must overlap the growth zone"
    )

    # Divergence: ink the appearance. Same annot xref, same rect -- the
    # fingerprint cannot see it (proved below), so only the live re-check
    # stands between this ink and the splice.
    doc.update_stream(ap_xref, b"0 0 0 rg 0 0 999 999 re f")
    assert page_fingerprint(doc, page) == prepared.page_fingerprint, (
        "fixture check: the appearance rewrite must be fingerprint-invisible"
    )

    pre_streams = {xref: doc.xref_stream(xref) for xref in page.get_contents()}
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.FAILED, outcome
    assert outcome.fallback_chain == (
        f"tier1:{RejectReason.GROWTH_EXCEEDS_BLANK_REGION}",
    )
    post_streams = {xref: doc.xref_stream(xref) for xref in page.get_contents()}
    assert post_streams == pre_streams, "refused commit must mutate nothing"
    doc.close()


# ------------------------------------------------- command-level tier1 undo


def test_tier1_command_undo_replays_byte_exact_reversal(tmp_path):
    """Command-level undo for a Tier 1 commit replays the retained inverse
    PatchSet -- byte-identical page fingerprint afterwards -- instead of
    falling through to the lossier page-snapshot path (review follow-up:
    the reversal capture in ``EditTextCommand.execute`` now admits
    ``TIER1_REBUILD_WITH_VALIDATED_FACE`` alongside Tier 0). Deleting that
    admission turns this Red at the fingerprint assert: the snapshot
    fallback restores via ``insert_pdf``+``delete_page``, which
    re-serializes the page under new object numbers.
    """
    from model.edit_commands import EditTextCommand
    from model.text_commit.inspect import page_fingerprint

    pdf_path = tmp_path / "tier1_undo.pdf"
    doc = fitz.open()
    _add_strict_mode_page(doc)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", max_tier=1)
    )
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    try:
        pre_fingerprint = page_fingerprint(model.doc, model.doc[0])
        block = next(
            b
            for b in model.block_manager.get_blocks(0)
            if STRICT_TARGET in (b.text or "")
        )
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=STRICT_REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
        )
        model.command_manager.execute(cmd)
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE

        assert model.command_manager.undo() is True
        assert page_fingerprint(model.doc, model.doc[0]) == pre_fingerprint, (
            "tier1 undo must replay the byte-exact inverse PatchSet, not the "
            "page-snapshot fallback"
        )
        text = model.doc[0].get_text()
        assert STRICT_TARGET in text
        assert STRICT_REPLACEMENT not in text
    finally:
        model.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
