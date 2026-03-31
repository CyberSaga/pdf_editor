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


def _make_wrapped_pdf(path: Path) -> None:
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


def _make_multicolumn_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 200, 180), "Column one wraps into two lines for testing.", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(320, 72, 520, 180), "Column two stays independent.", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_bullets_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(72, 72, 260, 180),
        "- Alpha item\n- Beta item",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path, garbage=0)
    doc.close()


def test_fallback_extraction_space_joins_wrapped_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wrapped.pdf"
        _make_wrapped_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            raw = model.doc[0].get_text("dict", flags=0)["blocks"]
            block = next(b for b in raw if b.get("type") == 0 and len(b.get("lines", [])) >= 2)
            first_line, second_line = block["lines"][:2]
            probe = fitz.Point(float(block["bbox"][0]) + 4.0, (float(first_line["bbox"][3]) + float(second_line["bbox"][1])) / 2.0)

            hit = model.get_text_info_at_point(1, probe)

            assert hit is not None
            assert "\n" not in hit.target_text
            assert "data center shall serve the public" in " ".join(hit.target_text.split()).lower()
        finally:
            model.close()


def test_paragraph_builder_space_joins_visual_lines() -> None:
    manager = TextBlockManager()
    paragraphs = manager._build_paragraphs(
        0,
        [
            EditableSpan("run-1", 0, 0, 0, 0, fitz.Rect(10, 10, 80, 22), fitz.Point(10, 20), "serve the", "helv", 12.0, (0.0, 0.0, 0.0), (1.0, 0.0), 0),
            EditableSpan("run-2", 0, 0, 1, 0, fitz.Rect(10, 26, 80, 38), fitz.Point(10, 36), "public", "helv", 12.0, (0.0, 0.0, 0.0), (1.0, 0.0), 0),
        ],
    )

    assert len(paragraphs) == 1
    assert paragraphs[0].text == "serve the public"


def test_multicolumn_hit_detection_does_not_merge_columns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "columns.pdf"
        _make_multicolumn_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_text_info_at_point(1, fitz.Point(90, 90))
            assert hit is not None
            assert "column one" in hit.target_text.lower()
            assert "column two" not in hit.target_text.lower()
        finally:
            model.close()


def test_bullet_items_keep_semantic_breaks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bullets.pdf"
        _make_bullets_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            blocks = model.block_manager.get_blocks(0)
            bullet_block = next(block for block in blocks if "Alpha item" in (block.text or ""))
            normalized = "\n".join(part.strip() for part in bullet_block.text.splitlines() if part.strip())
            assert "- Alpha item" in normalized
            assert "- Beta item" in normalized
        finally:
            model.close()
