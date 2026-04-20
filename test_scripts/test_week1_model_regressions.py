from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel
from model.text_block import EditableSpan, TextBlockManager


def _make_wrapped_paragraph_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(72, 72, 180, 150),
        "The data center shall serve the public every day for local residents.",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path, garbage=0)
    doc.close()


def _make_stacked_blocks_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(72, 96, 220, 132),
        "Hello World",
        fontsize=12,
        fontname="helv",
    )
    page.insert_textbox(
        fitz.Rect(72, 150, 260, 186),
        "Neighbor block stays put",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path, garbage=0)
    doc.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    model.ensure_page_index_built(page_idx + 1)
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None


def test_fallback_hit_detection_space_joins_wrapped_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wrapped.pdf"
        _make_wrapped_paragraph_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            raw = model.doc[0].get_text("dict", flags=0)["blocks"]
            target_block = next(
                block for block in raw
                if block.get("type") == 0 and len(block.get("lines", [])) >= 2
            )
            first_line, second_line = target_block["lines"][:2]
            between_y = (float(first_line["bbox"][3]) + float(second_line["bbox"][1])) / 2.0
            probe = fitz.Point(float(target_block["bbox"][0]) + 4.0, between_y)

            hit = model.get_text_info_at_point(1, probe)

            assert hit is not None
            assert "\n" not in hit.target_text
            assert "data center shall serve the public" in " ".join(hit.target_text.split()).lower()
        finally:
            model.close()


def test_build_paragraphs_space_joins_lines() -> None:
    manager = TextBlockManager()
    runs = [
        EditableSpan(
            span_id="run-1",
            page_idx=0,
            block_idx=0,
            line_idx=0,
            span_idx=0,
            bbox=fitz.Rect(10, 10, 80, 22),
            origin=fitz.Point(10, 20),
            text="serve the",
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            dir_vec=(1.0, 0.0),
            rotation=0,
        ),
        EditableSpan(
            span_id="run-2",
            page_idx=0,
            block_idx=0,
            line_idx=1,
            span_idx=0,
            bbox=fitz.Rect(10, 26, 70, 38),
            origin=fitz.Point(10, 36),
            text="public",
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            dir_vec=(1.0, 0.0),
            rotation=0,
        ),
    ]

    paragraphs = manager._build_paragraphs(0, runs)

    assert len(paragraphs) == 1
    assert paragraphs[0].text == "serve the public"


def test_same_height_edit_does_not_push_neighbor_block_down() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "same_height.pdf"
        _make_stacked_blocks_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target = _find_block(model, 0, "Hello World")
            neighbor = _find_block(model, 0, "Neighbor block stays put")
            assert target is not None
            assert neighbor is not None
            before_neighbor_y0 = float(neighbor.layout_rect.y0)

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.layout_rect),
                new_text="Hello World",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
            )

            model.block_manager.rebuild_page(0, model.doc)
            neighbor_after = _find_block(model, 0, "Neighbor block stays put")
            assert neighbor_after is not None
            assert abs(float(neighbor_after.layout_rect.y0) - before_neighbor_y0) < 1.0
        finally:
            model.close()


def test_longer_edit_keeps_original_top_anchor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "longer_edit.pdf"
        _make_stacked_blocks_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target = _find_block(model, 0, "Hello World")
            assert target is not None
            original_rect = fitz.Rect(target.layout_rect)

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.layout_rect),
                new_text="Hello World with additional wording to exercise height growth safely",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
            )

            model.block_manager.rebuild_page(0, model.doc)
            updated = _find_block(model, 0, "additional wording")
            assert updated is not None
            assert abs(float(updated.layout_rect.x0) - float(original_rect.x0)) < 2.0
            assert abs(float(updated.layout_rect.y0) - float(original_rect.y0)) < 5.0
        finally:
            model.close()
