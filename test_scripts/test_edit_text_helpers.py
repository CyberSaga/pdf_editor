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
