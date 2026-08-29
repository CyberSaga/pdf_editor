"""RED: the model's public text-geometry surface speaks VISUAL (displayed) space.

Every rect/point the view exchanges with the model is in ``page.rect`` /
``page.get_pixmap()`` space (the scene is that space times the render
scale).  The block index is built from ``page.get_text("dict"/"rawdict")``,
which PyMuPDF reports in UNROTATED page space (docs/PITFALLS.md, "get_text
geometry is UNROTATED page space").  On a ``/Rotate 0`` page the two spaces
coincide, so nothing here can be observed there; every assertion below is
therefore run on quarter-turn (and 180) pages against a *pixmap ink* oracle,
never against ``rotation_matrix`` arithmetic (the fix would otherwise be its
own oracle).

Fixture shape mirrors the P3-D manual smoke fixture: one Helvetica ``Tj`` on
a 612x792 page, then ``/Rotate``.  The digits-only word keeps the ink centre
inside a single run and makes the commit replacement advance-neutral.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import EditTextResult, derive_tier0_preview_target  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, TextCommitSettings  # noqa: E402

WORD = "2024"
REPLACEMENT = "2025"  # Helvetica digits share one advance: Tier 0 eligible


def _write_rotated_pdf(path: Path, rotation: int, text: str = WORD, *, td_y: int = 672) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    # PDF user space is y-up: 672 from the bottom == 120 pt from the top in
    # the (unrotated) dict space PyMuPDF reports.
    doc.update_stream(content_xref, f"BT /F1 12 Tf 72 {td_y} Td ({text}) Tj ET".encode("latin-1"))
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    page.set_rotation(rotation)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _ink_bbox(page: fitz.Page) -> fitz.Rect:
    """Dark-pixel bounds of the rendered page at 72 dpi == visual points."""
    pix = page.get_pixmap(dpi=72)
    samples = bytes(pix.samples)
    n = pix.n
    xs: list[int] = []
    ys: list[int] = []
    for y in range(pix.height):
        row = y * pix.width
        for x in range(pix.width):
            if samples[(row + x) * n] < 200:
                xs.append(x)
                ys.append(y)
    assert xs, "fixture: no dark pixels rendered"
    return fitz.Rect(min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _centre(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _assert_tight(rect: fitz.Rect, ink: fitz.Rect, margin: float = 4.0) -> None:
    """``rect`` must cover ``ink`` and not exceed it by more than ``margin``."""
    assert rect.x0 <= ink.x0 + 1.0 and rect.y0 <= ink.y0 + 1.0, (rect, ink)
    assert rect.x1 >= ink.x1 - 1.0 and rect.y1 >= ink.y1 - 1.0, (rect, ink)
    assert rect.x0 >= ink.x0 - margin and rect.y0 >= ink.y0 - margin, (rect, ink)
    assert rect.x1 <= ink.x1 + margin and rect.y1 <= ink.y1 + margin, (rect, ink)


@pytest.fixture()
def rotated_model(tmp_path, request):
    rotation = request.param
    path = _write_rotated_pdf(tmp_path / f"rot{rotation}.pdf", rotation)
    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", preview="plan", max_tier=0)
    )
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    assert model.doc[0].rotation == rotation
    try:
        yield model, rotation
    finally:
        model.close()


QUARTER = [90, 270]
ALL = [0, 90, 180, 270]


# ----------------------------------------------------------------- hit-test


@pytest.mark.parametrize("rotated_model", ALL, indirect=True)
def test_hit_test_accepts_visual_point_and_returns_visual_bbox(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    hit = model.get_text_info_at_point(1, _centre(ink), allow_fallback=False)

    assert hit is not None, f"visual ink centre {_centre(ink)} must hit the run"
    assert WORD in hit.target_text
    assert _centre(ink) in fitz.Rect(hit.target_bbox)
    _assert_tight(fitz.Rect(hit.target_bbox), ink)


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_hit_test_no_longer_accepts_unrotated_space_points(rotated_model) -> None:
    """Mutation pin: the OLD contract (dict-space point) must now miss."""
    model, _rotation = rotated_model
    dict_bbox = fitz.Rect(model.block_manager.get_runs(0)[0].bbox)
    ink = _ink_bbox(model.doc[0])
    assert _centre(dict_bbox) not in ink, "fixture: dict centre must lie off the ink"

    assert model.get_text_info_at_point(1, _centre(dict_bbox), allow_fallback=False) is None


@pytest.mark.parametrize("rotated_model", ALL, indirect=True)
def test_hit_rotation_is_the_on_screen_glyph_rotation(rotated_model) -> None:
    """Horizontal source text on a /Rotate page reads rotated on screen."""
    model, rotation = rotated_model
    hit = model.get_text_info_at_point(1, _centre(_ink_bbox(model.doc[0])), allow_fallback=False)
    assert hit is not None
    assert int(hit.rotation) == rotation


# ------------------------------------------------------------ outline source


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
@pytest.mark.parametrize("mode", ["run", "paragraph"])
def test_text_targets_for_outlines_are_visual(rotated_model, mode) -> None:
    model, rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    targets = model.get_text_targets(0, mode, blocks_fallback=True)

    assert targets, "one target expected"
    rects = [fitz.Rect(getattr(t, "bbox", None) or getattr(t, "rect")) for t in targets]
    assert any(_centre(ink) in r for r in rects), (rects, ink)
    _assert_tight(rects[0], ink)
    assert int(targets[0].rotation) == rotation
    blocks = model.get_text_blocks(0)
    assert blocks and _centre(ink) in fitz.Rect(blocks[0].rect)


# ------------------------------------------------------ selection surfaces


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_char_context_rects_are_visual(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])
    point = _centre(ink)

    context = model.get_char_context_at_point(1, point)

    assert context is not None, "visual ink centre must resolve a glyph"
    text, hit_index, rects = context
    assert text == WORD
    assert point in fitz.Rect(rects[hit_index])
    union = fitz.Rect(rects[0])
    for r in rects[1:]:
        union.include_rect(r)
    _assert_tight(union, ink)


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_selection_snapshot_and_lines_are_visual(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])
    around = fitz.Rect(ink.x0 - 2, ink.y0 - 2, ink.x1 + 2, ink.y1 + 2)

    text, bounds = model.get_text_selection_snapshot(1, around)
    assert WORD in text
    assert bounds is not None
    _assert_tight(fitz.Rect(bounds), ink)
    assert WORD in model.get_text_in_rect(1, around)

    hit = model.get_text_info_at_point(1, _centre(ink), allow_fallback=False)
    assert hit is not None
    lines_text, line_rects = model.get_text_selection_lines(
        1,
        hit.target_span_id,
        fitz.Point(ink.x1 - 0.5, ink.y1 - 0.5),
        start_point=fitz.Point(ink.x0 + 0.5, ink.y0 + 0.5),
    )
    assert WORD in lines_text
    assert line_rects
    union = fitz.Rect(line_rects[0])
    for r in line_rects[1:]:
        union.include_rect(r)
    _assert_tight(union, ink)

    from_run_text, from_run_bounds = model.get_text_selection_snapshot_from_run(
        1, hit.target_span_id, fitz.Point(ink.x1 - 0.5, ink.y1 - 0.5)
    )
    assert WORD in from_run_text
    assert from_run_bounds is not None and _centre(ink) in fitz.Rect(from_run_bounds)


# ------------------------------------------------------------- write side


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_edit_text_from_visual_hit_commits_at_tier0(rotated_model) -> None:
    """The smoke gate: a click-derived edit on a rotated page is plan-backed."""
    model, _rotation = rotated_model
    ink_before = _ink_bbox(model.doc[0])
    hit = model.get_text_info_at_point(1, _centre(ink_before), allow_fallback=False)
    assert hit is not None

    result = model.edit_text(
        1,
        fitz.Rect(hit.target_bbox),
        REPLACEMENT,
        font=hit.font,
        size=float(hit.size),
        color=tuple(hit.color),
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
    )

    assert result is EditTextResult.SUCCESS, result
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH, outcome
    assert outcome.fallback_chain == (), outcome
    assert REPLACEMENT in model.doc[0].get_text("text")
    ink_after = _ink_bbox(model.doc[0])
    assert abs(ink_after.x0 - ink_before.x0) <= 3 and abs(ink_after.y0 - ink_before.y0) <= 3


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_edit_text_resolves_a_visual_rect_without_span_id(rotated_model) -> None:
    """``rect`` alone (no span id) must find the run: the write side derotates."""
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    result = model.edit_text(
        1,
        fitz.Rect(ink),
        REPLACEMENT,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=WORD,
        target_span_id=None,
        target_mode="run",
    )

    assert result is EditTextResult.SUCCESS, result
    assert REPLACEMENT in model.doc[0].get_text("text")


@pytest.mark.parametrize("rotation", QUARTER)
def test_legacy_edit_keeps_place_when_source_sits_near_the_unrotated_bottom(
    tmp_path, rotation
) -> None:
    """The legacy engine's page-bounds clamps must use the UNROTATED page
    bounds: on a quarter-turn page ``page.rect`` has swapped dimensions, so a
    run whose unrotated y exceeds the displayed height was clamped into a
    degenerate insert rect and re-inserted at the page origin.

    ``new_rect`` (the unchanged displayed bbox) forces the htmlbox path,
    which is the one that clamps; the fast ``insert_text`` path does not."""
    path = _write_rotated_pdf(tmp_path / f"legacy{rotation}.pdf", rotation, td_y=100)
    model = PDFModel()  # default settings: legacy engine
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        ink_before = _ink_bbox(model.doc[0])
        hit = model.get_text_info_at_point(1, _centre(ink_before), allow_fallback=False)
        assert hit is not None

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=fitz.Rect(hit.target_bbox),
        )

        assert result is EditTextResult.SUCCESS, result
        assert REPLACEMENT in model.doc[0].get_text("text")
        ink_after = _ink_bbox(model.doc[0])
        assert abs(ink_after.x0 - ink_before.x0) <= 6 and abs(ink_after.y0 - ink_before.y0) <= 6, (
            ink_before,
            ink_after,
        )
    finally:
        model.close()


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_preview_target_derives_from_visual_rect_without_span_id(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    target = derive_tier0_preview_target(
        model,
        page_num=1,
        rect=fitz.Rect(ink),
        original_text=WORD,
        target_span_id=None,
        target_mode="run",
    )

    assert target is not None
    assert target.text == WORD
    _assert_tight(fitz.Rect(target.bbox), ink)
