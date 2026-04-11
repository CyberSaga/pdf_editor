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


def _make_two_line_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text(fitz.Point(72, 72), "Alpha Beta Gamma", fontsize=12, fontname="helv")
    page.insert_text(fitz.Point(72, 92), "Delta Epsilon Zeta", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_multi_run_lines_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    rows = [
        (72, ("Alpha", "Beta", "Gamma")),
        (96, ("Delta", "Epsilon", "Zeta")),
        (120, ("Eta", "Theta", "Iota")),
    ]
    x_positions = (72, 132, 222)
    for y, words in rows:
        for x, word in zip(x_positions, words):
            page.insert_text(fitz.Point(x, y), word, fontsize=12, fontname="helv")
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


def test_get_text_in_rect_expands_partial_clip_to_whole_visual_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "two-lines.pdf"
        _make_two_line_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            partial_rect = fitz.Rect(100, 60, 170, 100)

            selected = model.get_text_in_rect(1, partial_rect)

            assert selected == "Alpha Beta Gamma\nDelta Epsilon Zeta"
        finally:
            model.close()


def test_get_text_bounds_expands_partial_clip_to_full_visual_line_bounds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "two-lines.pdf"
        _make_two_line_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            partial_rect = fitz.Rect(100, 60, 170, 100)

            bounds = model.tools.annotation.get_text_bounds(1, partial_rect)

            words = page.get_text("words", sort=True)
            selected_lines = {(int(word[5]), int(word[6])) for word in words if fitz.Rect(word[:4]).intersects(partial_rect)}
            line_words = [word for word in words if (int(word[5]), int(word[6])) in selected_lines]
            expected = fitz.Rect(
                min(word[0] for word in line_words),
                min(word[1] for word in line_words),
                max(word[2] for word in line_words),
                max(word[3] for word in line_words),
            )

            assert bounds == expected
        finally:
            model.close()


def test_run_anchored_selection_uses_partial_boundary_lines_and_full_middle_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi-run-lines.pdf"
        _make_multi_run_lines_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            texts = [run.text.strip() for run in runs if run.text.strip()]
            start_run = next(run for run in runs if run.text.strip() == "Beta")
            end_run = next(run for run in runs if run.text.strip() == "Theta")

            selected_text, bounds = model.get_text_selection_snapshot_from_run(
                1,
                start_run.span_id,
                fitz.Point((end_run.bbox.x0 + end_run.bbox.x1) / 2.0, (end_run.bbox.y0 + end_run.bbox.y1) / 2.0),
            )

            assert texts[:9] == ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota"]
            assert selected_text == "Beta Gamma\nDelta Epsilon Zeta\nEta Theta"
            assert bounds is not None

            selected_runs = [run for run in runs if run.text.strip() in {"Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"}]
            expected = fitz.Rect(selected_runs[0].bbox)
            for run in selected_runs[1:]:
                expected.include_rect(fitz.Rect(run.bbox))
            assert bounds == expected
        finally:
            model.close()


def test_run_anchored_selection_keeps_reading_order_for_backward_drag_same_line() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi-run-lines.pdf"
        _make_multi_run_lines_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            start_run = next(run for run in runs if run.text.strip() == "Gamma")
            end_run = next(run for run in runs if run.text.strip() == "Alpha")

            selected_text, bounds = model.get_text_selection_snapshot_from_run(
                1,
                start_run.span_id,
                fitz.Point((end_run.bbox.x0 + end_run.bbox.x1) / 2.0, (end_run.bbox.y0 + end_run.bbox.y1) / 2.0),
            )

            assert selected_text == "Alpha Beta Gamma"
            assert bounds is not None
        finally:
            model.close()


def test_exact_run_hit_ignores_block_whitespace_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi-run-lines.pdf"
        _make_multi_run_lines_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            point = fitz.Point(180, 67)

            default_hit = model.get_text_info_at_point(1, point)
            exact_hit = model.get_text_info_at_point(1, point, allow_fallback=False)

            assert default_hit is not None
            assert exact_hit is None
        finally:
            model.close()


def test_run_anchored_selection_uses_nearest_run_when_mouseup_is_in_block_whitespace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi-run-lines.pdf"
        _make_multi_run_lines_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            start_run = next(run for run in runs if run.text.strip() == "Beta")

            selected_text, bounds = model.get_text_selection_snapshot_from_run(
                1,
                start_run.span_id,
                fitz.Point(175, 115),
            )

            assert selected_text == "Beta Gamma\nDelta Epsilon Zeta\nEta Theta"
            assert bounds is not None
        finally:
            model.close()
