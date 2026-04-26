from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402


@pytest.fixture()
def model_with_pdf(tmp_path: Path):
    """Create a minimal PDF, open in PDFModel, and yield the model."""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    page.insert_text((72, 200), "Original text to edit", fontsize=12.0, fontname="helv")
    page.insert_text((72, 300), "Third block here", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    try:
        yield model
    finally:
        model.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None


def _first_span_id(model: PDFModel, page_idx: int, rect: fitz.Rect) -> str:
    spans = model.block_manager.find_overlapping_runs(page_idx, rect, tol=0.5)
    assert spans
    return spans[0].span_id


def _resolve_target(
    model: PDFModel,
    block,
    *,
    new_text: str,
    font: str = "helv",
    size: float = 12.0,
    color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    original_text: str | None = None,
    new_rect: fitz.Rect | None = None,
    resolved_target_span_id: str | None = None,
    effective_target_mode: str = "paragraph",
):
    page = model.doc[0]
    rect = fitz.Rect(block.layout_rect) if block is not None else fitz.Rect(9000, 9000, 9010, 9010)
    return model._resolve_edit_target(
        page_num=1,
        page_idx=0,
        page=page,
        rect=rect,
        new_text=new_text,
        font=font,
        size=size,
        color=color,
        original_text=original_text if original_text is not None else (block.text if block is not None else None),
        new_rect=new_rect,
        resolved_target_span_id=resolved_target_span_id,
        effective_target_mode=effective_target_mode,
    )


def _resolve_for_apply(model: PDFModel, probe: str, *, new_text: str):
    block = _find_block(model, 0, probe)
    assert block is not None
    status, result = _resolve_target(
        model,
        block,
        new_text=new_text,
        original_text=block.text,
    )
    assert status is EditTextResult.SUCCESS
    assert result is not None
    return block, result


def _apply_insert(model: PDFModel, probe: str, *, new_text: str) -> tuple[fitz.Page, object, fitz.Rect, bytes]:
    _, resolve_result = _resolve_for_apply(model, probe, new_text=new_text)
    page = model.doc[0]
    snapshot = model._capture_page_snapshot(0)
    new_rect = model._apply_redact_insert(
        page=page,
        page_num=1,
        page_idx=0,
        page_rect=page.rect,
        new_text=new_text,
        size=12.0,
        color=(0.0, 0.0, 0.0),
        vertical_shift_left=True,
        new_rect=None,
        snapshot_bytes=snapshot,
        resolve_result=resolve_result,
    )
    return page, resolve_result, new_rect, snapshot


def test_mode_default_no_args(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode=None,
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=None,
    )

    assert effective == "paragraph"


def test_mode_explicit_span_id(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None
    span_id = _first_span_id(model_with_pdf, 0, fitz.Rect(block.layout_rect))

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode=None,
        target_span_id=span_id,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "run"


def test_mode_new_rect_promotes(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None
    new_rect = fitz.Rect(block.layout_rect)
    new_rect.y0 += 20
    new_rect.y1 += 20

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode=None,
        target_span_id=None,
        new_rect=new_rect,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "paragraph"


def test_mode_explicit_paragraph(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode="paragraph",
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "paragraph"


def test_mode_run_auto_promotes(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Original text to edit")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode="run",
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "paragraph"


def test_mode_run_no_promote_subsection(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Original text to edit")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode="run",
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text="Original",
    )

    assert effective == "run"


def test_resolve_target_happy_path(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    status, result = _resolve_target(
        model_with_pdf,
        block,
        new_text="New text",
        original_text=block.text,
    )

    assert status is EditTextResult.SUCCESS
    assert result is not None
    assert result.target_span is not None
    assert result.target.text == block.text


def test_resolve_target_missing_block(model_with_pdf: PDFModel) -> None:
    status, result = _resolve_target(
        model_with_pdf,
        None,
        new_text="New text",
        original_text="Missing block",
    )

    assert status is EditTextResult.TARGET_BLOCK_NOT_FOUND
    assert result is None


def test_resolve_target_no_change(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    status, result = _resolve_target(
        model_with_pdf,
        block,
        new_text=block.text,
        font=block.font,
        size=float(block.size),
        color=tuple(float(c) for c in block.color),
        original_text=block.text,
    )

    assert status is EditTextResult.NO_CHANGE
    assert result is None


def test_resolve_target_by_span_id(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None
    span_id = _first_span_id(model_with_pdf, 0, fitz.Rect(block.layout_rect))

    status, result = _resolve_target(
        model_with_pdf,
        block,
        new_text="Updated via span id",
        original_text=block.text,
        resolved_target_span_id=span_id,
        effective_target_mode="run",
    )

    assert status is EditTextResult.SUCCESS
    assert result is not None
    assert result.resolved_target_span_id == span_id


def test_apply_insert_basic(model_with_pdf: PDFModel) -> None:
    page, _, new_rect, _ = _apply_insert(model_with_pdf, "Hello World", new_text="Goodbye")

    page_text = page.get_text("text")
    assert isinstance(new_rect, fitz.Rect)
    assert "Goodbye" in page_text
    assert "Hello World" not in page_text


def test_apply_insert_empty_deletes(model_with_pdf: PDFModel) -> None:
    page, _, new_rect, _ = _apply_insert(model_with_pdf, "Hello World", new_text="")

    assert isinstance(new_rect, fitz.Rect)
    assert "Hello World" not in page.get_text("text")


def test_apply_insert_preserves_others(model_with_pdf: PDFModel) -> None:
    page, _, _, _ = _apply_insert(model_with_pdf, "Hello World", new_text="Goodbye")

    assert "Third block here" in page.get_text("text")


def test_verify_rebuild_passes(model_with_pdf: PDFModel) -> None:
    page, resolve_result, new_rect, snapshot = _apply_insert(
        model_with_pdf, "Hello World", new_text="Goodbye"
    )

    model_with_pdf._verify_rebuild_edit(
        page=page,
        page_num=1,
        page_idx=0,
        page_rect=page.rect,
        new_text="Goodbye",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        snapshot_bytes=snapshot,
        resolve_result=resolve_result,
        new_layout_rect=new_rect,
    )

    updated_block = _find_block(model_with_pdf, 0, "Goodbye")
    assert updated_block is not None


def test_verify_rebuild_rollback(model_with_pdf: PDFModel) -> None:
    block, resolve_result = _resolve_for_apply(
        model_with_pdf, "Hello World", new_text="Replacement text"
    )
    page = model_with_pdf.doc[0]
    snapshot = model_with_pdf._capture_page_snapshot(0)

    with pytest.raises(RuntimeError, match="verification failed"):
        model_with_pdf._verify_rebuild_edit(
            page=page,
            page_num=1,
            page_idx=0,
            page_rect=page.rect,
            new_text="XYZZY_NONEXISTENT",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            snapshot_bytes=snapshot,
            resolve_result=resolve_result,
            new_layout_rect=fitz.Rect(block.layout_rect),
        )


# ── Phase-2 red-light regressions ───────────────────────────────────────────


def test_phase2_single_line_run_edit_preserves_anchor_without_drag(
    model_with_pdf: PDFModel,
) -> None:
    """Phase-2 symptom 1: run-mode non-drag edits must not drift the anchor."""
    target = _find_block(model_with_pdf, 0, "Hello World")
    assert target is not None
    baseline_x0 = float(target.layout_rect.x0)
    baseline_y0 = float(target.layout_rect.y0)

    result = model_with_pdf.edit_text(
        page_num=1,
        rect=fitz.Rect(target.layout_rect),
        new_text="Hello world!",
        font=target.font,
        size=float(target.size),
        color=tuple(float(c) for c in target.color),
        original_text=target.text,
        target_mode="run",
    )
    assert result is EditTextResult.SUCCESS
    model_with_pdf.block_manager.rebuild_page(0, model_with_pdf.doc)

    edited = _find_block(model_with_pdf, 0, "Hello world!")
    assert edited is not None
    drift_x0 = float(edited.layout_rect.x0) - baseline_x0
    drift_y0 = float(edited.layout_rect.y0) - baseline_y0
    assert abs(drift_x0) < 0.5, f"Anchor drifted x0 by {drift_x0:.3f}pt"
    assert abs(drift_y0) < 0.5, f"Anchor drifted y0 by {drift_y0:.3f}pt"


def test_phase2_edit_text_preserves_fractional_font_size(
    model_with_pdf: PDFModel,
) -> None:
    """Phase-2 symptom 2: fractional font sizes must round-trip through edit_text."""
    target = _find_block(model_with_pdf, 0, "Original text to edit")
    assert target is not None

    result = model_with_pdf.edit_text(
        page_num=1,
        rect=fitz.Rect(target.layout_rect),
        new_text="Fractional edit content",
        font=target.font,
        size=9.5,
        color=tuple(float(c) for c in target.color),
        original_text=target.text,
        target_mode="run",
    )
    assert result is EditTextResult.SUCCESS
    model_with_pdf.block_manager.rebuild_page(0, model_with_pdf.doc)

    edited = _find_block(model_with_pdf, 0, "Fractional edit content")
    assert edited is not None
    observed_size = float(edited.size)
    assert abs(observed_size - 9.5) < 0.1, (
        f"Fractional size collapsed to {observed_size:.3f} (expected ≈9.5)"
    )


# ---------------------------------------------------------------------------
# Text size fidelity — the committed text must not visually grow or shrink
# without an explicit user font-size action.
#
# Two distinct properties are checked:
#   1. font pt size (`hit.size`) — guards against int-truncation regressions
#      (PITFALLS: "PyMuPDF font sizes are floats, not ints")
#   2. visual span height (`hit.target_bbox.height`) — guards against
#      `_build_insert_css` producing a different line_height than the
#      original PDF, which makes the committed block taller/shorter and
#      pushes surrounding text.
# ---------------------------------------------------------------------------


def _make_pdf_at_size(tmp_path: Path, fontsize: float, text: str = "Hello World") -> Path:
    """Create a single-page PDF with one ``insert_text`` block at the given size."""
    pdf_path = tmp_path / f"size_{fontsize}.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), text, fontname="helv", fontsize=fontsize)
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    return pdf_path


def _measure_span_at(model: PDFModel, page_num: int, point: fitz.Point):
    """Return (font_pt_size, bbox_height) for the span under ``point``, or None."""
    model.ensure_page_index_built(page_num)
    hit = model.get_text_info_at_point(page_num, point)
    if hit is None:
        return None
    return float(hit.size), float(hit.target_bbox.height)


@pytest.mark.parametrize("original_size", [12.0, 9.5, 24.0])
def test_edit_preserves_font_size_pt_after_content_change(tmp_path: Path, original_size: float):
    """Font pt size must not change when the user only edits text content.

    Catches integer truncation (9.5pt → 9pt) and any CSS-side rounding the
    re-insert path might introduce.
    """
    pdf_path = _make_pdf_at_size(tmp_path, original_size)
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        probe = fitz.Point(60, 100)
        before = _measure_span_at(model, 1, probe)
        assert before is not None, f"Cannot find span at {probe} for size {original_size}"
        size_before, _ = before

        hit = model.get_text_info_at_point(1, probe)
        assert hit is not None
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text="Hi World",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        assert result is EditTextResult.SUCCESS
        assert _page_contains_text(model, 1, "Hi World"), (
            "Edited content not found after edit_text — test must fail on no-op edits"
        )

        after = _measure_span_at(model, 1, probe)
        assert after is not None, "Span not found after edit"
        size_after, _ = after

        assert abs(size_after - size_before) < 0.5, (
            f"Font pt drifted {size_before:.3f}pt → {size_after:.3f}pt "
            f"(original_size={original_size}) — size must survive a content edit"
        )
    finally:
        model.close()


@pytest.mark.parametrize("original_size", [12.0, 24.0])
def test_edit_preserves_span_bbox_height_after_content_change(
    tmp_path: Path, original_size: float, monkeypatch: pytest.MonkeyPatch
):
    """Visual span height (bbox height) must not change after a content edit.

    The auto-calculated CSS line_height in ``_build_insert_css`` (when no
    explicit value is passed) inflates committed spans relative to the
    original ``insert_text`` layout — this test asserts that does NOT happen.
    """
    pdf_path = _make_pdf_at_size(tmp_path, original_size)
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        probe = fitz.Point(60, 100)
        before = _measure_span_at(model, 1, probe)
        assert before is not None
        _, height_before = before

        # Force the htmlbox insertion path so this test guards line-height fidelity,
        # not the single-line insert_text fast path.
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)

        hit = model.get_text_info_at_point(1, probe)
        assert hit is not None
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text="Hi World",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        assert result is EditTextResult.SUCCESS
        assert _page_contains_text(model, 1, "Hi World"), (
            "Edited content not found after edit_text — no-op edits must fail this test"
        )

        after = _measure_span_at(model, 1, probe)
        assert after is not None
        _, height_after = after

        tolerance = 1.5  # pt
        assert abs(height_after - height_before) <= tolerance, (
            f"Span height drifted {height_before:.2f}pt → {height_after:.2f}pt "
            f"(size={original_size}) — line height must survive a content edit"
        )
    finally:
        model.close()


def test_single_line_edit_does_not_push_unedited_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A single-character edit on one line must not shift unedited text below it.

    Reproduces the user's "push unedited lines away" symptom: editing a heading
    used to inflate the redacted region by ~22pt due to (a) MuPDF's 2pt htmlbox
    rendering overhead and (b) an over-conservative est_height heuristic
    forcing _probe_y1 to base_y1 = y0 + line_count × size × 2 + size × 2.
    With both fixes, the probe trusts its actual measurement and subtracts
    MuPDF's known overhead, so a single-line edit does not trigger push-down.
    """
    pdf_path = tmp_path / "layout.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    # 7.5pt keeps the meaningful-growth threshold at 1.5pt, so MuPDF's fixed
    # ~2pt htmlbox overhead will wrongly trigger push-down if not subtracted.
    page.insert_text((50, 100), "Heading line", fontname="helv", fontsize=7.5)
    # Anchor text below — should NOT shift after the heading edit.
    page.insert_text((50, 200), "Anchor text below", fontname="helv", fontsize=7.5)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        anchor_before = model.get_text_info_at_point(1, fitz.Point(60, 200))
        assert anchor_before is not None
        anchor_y_before = float(anchor_before.target_bbox.y0)

        # Force htmlbox path so the pre-push probe path is actually exercised.
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)

        # Edit the heading
        hit = model.get_text_info_at_point(1, fitz.Point(60, 100))
        assert hit is not None
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=hit.target_text + "X",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        assert result is EditTextResult.SUCCESS
        assert _page_contains_text(model, 1, "HeadingX"), (
            "Heading text did not change — test must fail on no-op edits"
        )

        model.ensure_page_index_built(1)
        anchor_after = model.get_text_info_at_point(1, fitz.Point(60, 200))
        assert anchor_after is not None, "Anchor text disappeared after edit"
        anchor_y_after = float(anchor_after.target_bbox.y0)

        # The anchor must not have moved (small floating-point tolerance only)
        assert abs(anchor_y_after - anchor_y_before) < 1.0, (
            f"Unedited anchor text shifted {anchor_y_before:.3f} → "
            f"{anchor_y_after:.3f} ({anchor_y_after - anchor_y_before:+.3f}pt) "
            f"after a single-line content edit — push-down triggered erroneously"
        )
    finally:
        model.close()


def test_render_width_for_edit_does_not_exceed_rect_width(tmp_path: Path):
    """Inline editor wrap width must match the original text-block width.

    If the editor is wider than the source rect, Qt's font renderer (which has
    slightly different glyph metrics than PyMuPDF) lays text at different visual
    widths and breaks lines at different points than the rendered PDF — this is
    the "break lines once edit box opened" symptom.
    """
    pdf_path = tmp_path / "render_width.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=300)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        test_rect = fitz.Rect(50, 80, 200, 100)  # width = 150pt
        returned_width = model.get_render_width_for_edit(
            page_num=1, rect=test_rect, rotation=0, font_size=12.0
        )
        assert returned_width <= test_rect.width + 0.5, (
            f"Editor width {returned_width:.1f}pt exceeds source rect width "
            f"{test_rect.width:.1f}pt — wrapping will diverge from PDF render"
        )
    finally:
        model.close()


def test_repeated_edits_do_not_accumulate_size_drift(tmp_path: Path):
    """Five consecutive edits on the same span must not amplify any per-edit drift.

    Each commit can introduce a small font-pt or height delta. After five
    rounds, any cumulative drift would exceed tolerance and fail this test.
    """
    pdf_path = _make_pdf_at_size(tmp_path, 12.0)
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        probe = fitz.Point(60, 100)
        before = _measure_span_at(model, 1, probe)
        assert before is not None
        size_before, height_before = before

        for i in range(5):
            model.ensure_page_index_built(1)
            hit = model.get_text_info_at_point(1, probe)
            assert hit is not None, f"Span lost on iteration {i}"
            replacement = f"Edit {i} sentinel"
            result = model.edit_text(
                page_num=1,
                rect=hit.target_bbox,
                new_text=replacement,
                font=hit.font,
                size=hit.size,
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode="run",
            )
            assert result is EditTextResult.SUCCESS, f"edit_text failed on iteration {i}"
            assert _page_contains_text(model, 1, replacement), (
                f"Replacement text missing after iteration {i} — edit did not commit"
            )

        after = _measure_span_at(model, 1, probe)
        assert after is not None, "Span lost after 5 edits"
        size_after, height_after = after

        assert abs(size_after - size_before) < 0.5, (
            f"Font pt drifted {size_before:.3f}pt → {size_after:.3f}pt over 5 edits"
        )
        assert abs(height_after - height_before) <= 2.0, (
            f"Span height drifted {height_before:.2f}pt → {height_after:.2f}pt over 5 edits"
        )
    finally:
        model.close()


# ── Real-PDF regression tests — "larger" and "smaller" symptoms ─────────────

REAL_PDFS_DIR = ROOT / "test_files"


def _find_largest_font_span(model: PDFModel, page_num: int):
    """Return the span with the largest font size on the page (heading proxy)."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    best = None
    seen: set = set()
    for y in range(30, int(page_rect.height) - 10, 15):
        for x in range(20, int(page_rect.width) - 20, 20):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is None or not hit.target_text.strip():
                continue
            if hit.target_span_id in seen:
                continue
            seen.add(hit.target_span_id)
            if best is None or float(hit.size) > float(best.size):
                best = hit
    return best


def _find_any_editable_span(model: PDFModel, page_num: int):
    """Return a span that can be meaningfully edited (non-trivial text)."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    seen: set = set()
    for y in range(30, int(page_rect.height) - 10, 15):
        for x in range(20, int(page_rect.width) - 20, 20):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is None or not hit.target_text.strip():
                continue
            if hit.target_span_id in seen:
                continue
            seen.add(hit.target_span_id)
            # Skip trivially short strings that would look identical with a prefix
            if len(hit.target_text.strip()) >= 2:
                return hit
    return None


def _find_span_with_text(model: PDFModel, page_num: int, needle: str):
    """Return the first span whose extracted text contains ``needle``."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    seen: set = set()
    for y in range(20, int(page_rect.height) - 10, 10):
        for x in range(15, int(page_rect.width) - 15, 12):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is None:
                continue
            if hit.target_span_id in seen:
                continue
            seen.add(hit.target_span_id)
            text = (hit.target_text or "").strip()
            if needle in text:
                return hit
    return None


def _normalized_ws(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def _page_contains_text(model: PDFModel, page_num: int, needle: str) -> bool:
    page_text = model.doc[page_num - 1].get_text("text")
    return _normalized_ws(needle) in _normalized_ws(page_text)


def test_build_insert_css_explicit_tight_line_height_not_clamped():
    """_build_insert_css must honor explicit line_height values below font size.

    Scenario: original PDF has tight leading (e.g. baseline advance 8pt for a 10pt
    font). _apply_redact_insert computes _line_ht=8.0 and passes it explicitly.
    With the bug, line_height = round(max(10, 8), 2) = 10.0 — wrong: committed text
    will be taller than original and surrounding text gets pushed.
    With the fix, explicit positive values bypass the max(size, ...) clamp.
    """
    model = PDFModel()
    model._resolve_add_text_font = lambda hint: "helv"
    model._resolve_cjk_companion_font = lambda font: "helv"
    model._font_face_css_for_token = lambda token: ""

    # Tight leading: line_height (8pt) < size (10pt)
    css = model._build_insert_css(size=10.0, color=(0.0, 0.0, 0.0), font_hint="helv", line_height=8.0)

    assert "line-height: 8.0pt" in css, (
        f"_build_insert_css clamped explicit tight line_height=8.0 up to size=10.0 — "
        f"clamp must only apply to auto-calculated values (line_height<=0). "
        f"CSS produced:\n{css.strip()}"
    )


def test_real_pdf_complexed_layout_edit_does_not_enlarge_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Editing the largest-font heading in test-complexed-layout.pdf must not grow
    the span's vertical extent.

    'Larger' symptom reproducer: _build_insert_css clamped line_height to >= size
    even for explicit tight-leading values, making committed boxes taller than original.
    The screenshots (manual-larger-222213/217/220) show the heading oversized after edit.
    """
    import shutil
    from model.edit_commands import EditTextResult

    pdf_src = REAL_PDFS_DIR / "test-complexed-layout.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")

    pdf_copy = tmp_path / "complexed.pdf"
    shutil.copy2(pdf_src, pdf_copy)

    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        # Target the heading proxy (largest font span) from the reproducer.
        hit = _find_largest_font_span(model, 1)
        assert hit is not None, "Could not find any editable text on page 1"
        height_before = float(hit.target_bbox.height)
        marker = "QFIDLARGE"

        # Force htmlbox path so this integration test actually exercises CSS line-height.
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)

        # Prepend "X" so the edit is a real content change (trailing space gets stripped)
        new_text = f"{marker} {hit.target_text}"
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=new_text,
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        assert result is EditTextResult.SUCCESS, (
            f"edit_text returned {result!r} instead of SUCCESS — edit was not applied"
        )

        model.ensure_page_index_built(1)
        hit_after = _find_span_with_text(model, 1, marker)
        assert hit_after is not None, (
            f"Edited marker {marker!r} not found after edit — did commit fail? "
            f"height_before={height_before:.2f}pt"
        )
        height_after = float(hit_after.target_bbox.height)

        assert height_after <= height_before + 1.5, (
            f"Span height grew {height_before:.2f}pt → {height_after:.2f}pt "
            f"(font={hit.size:.2f}pt, text={hit.target_text[:30]!r}) "
            f"in complexed-layout.pdf — 'larger' symptom: _build_insert_css clamp active"
        )
    finally:
        model.close()


def test_real_pdf_colored_background_edit_does_not_shrink_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Editing text in test-colored-background.pdf must not shrink the span's vertical extent.

    'Smaller' symptom reproducer (manual-smaller-222143/147/151): white text on dark
    background appears more compact after editing. The inline editor already shows
    glyphs smaller than original during editing. After commit text is noticeably smaller.
    """
    import shutil
    from model.edit_commands import EditTextResult

    pdf_src = REAL_PDFS_DIR / "test-colored-background.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")

    pdf_copy = tmp_path / "colored.pdf"
    shutil.copy2(pdf_src, pdf_copy)

    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        hit = _find_any_editable_span(model, 1)
        assert hit is not None, "Could not find any editable text on page 1"
        height_before = float(hit.target_bbox.height)
        marker = "QFIDSMALL"

        # Force htmlbox path so this test measures committed layout behavior.
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)

        new_text = f"{marker} {hit.target_text}"
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=new_text,
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        assert result is EditTextResult.SUCCESS, (
            f"edit_text returned {result!r} instead of SUCCESS — edit was not applied"
        )

        model.ensure_page_index_built(1)
        hit_after = _find_span_with_text(model, 1, marker)
        assert hit_after is not None, (
            f"Edited marker {marker!r} not found after edit — "
            f"height_before={height_before:.2f}pt, text={hit.target_text[:30]!r}"
        )
        height_after = float(hit_after.target_bbox.height)

        assert height_after >= height_before - 1.5, (
            f"Span height shrank {height_before:.2f}pt → {height_after:.2f}pt "
            f"(font={hit.size:.2f}pt, text={hit.target_text[:30]!r}) "
            f"in colored-background.pdf — 'smaller' symptom: _line_ht under-estimated"
        )
    finally:
        model.close()
