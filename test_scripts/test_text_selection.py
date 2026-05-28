"""AC-1 — character-level browse-mode text selection.

The legacy selection worked at run/line granularity: any drag highlighted whole
runs. These tests pin the character-level behaviour: the selection is clipped to
the characters between the cursor-start and cursor-end points, the copied text
matches the highlight, and multi-line drags produce a partial first line, full
middle lines and a partial last line.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from model.pdf_model import PDFModel


def _make_text_pdf(path: Path, text: str, *, fontsize: float = 20.0) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((40, 60), text, fontsize=fontsize, fontname="helv")
    doc.save(path)
    doc.close()


def _first_run(model: PDFModel):
    model.ensure_page_index_built(1)
    runs = model.block_manager.get_runs(0)
    assert runs, "expected at least one run"
    return runs[0]


def test_get_chars_in_run_returns_per_character_boxes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chars.pdf"
        _make_text_pdf(path, "HELLO")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            run = _first_run(model)
            chars = model.get_chars_in_run(1, run.span_id)
            assert "".join(c for c, _ in chars).replace(" ", "") == "HELLO"
            # Boxes must be ordered left-to-right and non-degenerate.
            xs = [rect.x0 for _, rect in chars]
            assert xs == sorted(xs)
            assert all(rect.width > 0 for _, rect in chars)
        finally:
            model.close()


def test_same_run_drag_selects_only_character_range() -> None:
    """AC-1b: dragging within a run selects only the chars between the two points,
    not the whole run, and the copied text matches (AC-1e)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "single.pdf"
        _make_text_pdf(path, "ABCDEFGH")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            run = _first_run(model)
            chars = model.get_chars_in_run(1, run.span_id)
            assert len(chars) >= 6
            # Start just left of char index 2 (C), end just right of char index 4 (E).
            start_rect = chars[2][1]
            end_rect = chars[4][1]
            start_pt = fitz.Point(start_rect.x0 + 0.5, (start_rect.y0 + start_rect.y1) / 2)
            end_pt = fitz.Point(end_rect.x1 - 0.5, (end_rect.y0 + end_rect.y1) / 2)

            text, rects = model.get_text_selection_lines(
                1, run.span_id, end_pt, start_pt
            )
            assert text == "CDE", f"expected 'CDE', got {text!r}"
            assert len(rects) == 1
            full_run_width = fitz.Rect(run.bbox).width
            assert rects[0].width < full_run_width * 0.9
        finally:
            model.close()


def test_same_run_drag_is_order_independent() -> None:
    """Dragging right-to-left selects the same characters as left-to-right."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rev.pdf"
        _make_text_pdf(path, "ABCDEFGH")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            run = _first_run(model)
            chars = model.get_chars_in_run(1, run.span_id)
            left = fitz.Point(chars[2][1].x0 + 0.5, (chars[2][1].y0 + chars[2][1].y1) / 2)
            right = fitz.Point(chars[4][1].x1 - 0.5, (chars[4][1].y0 + chars[4][1].y1) / 2)
            # Press at the right end, drag to the left.
            text, _ = model.get_text_selection_lines(1, run.span_id, left, right)
            assert text == "CDE"
        finally:
            model.close()


def test_cross_run_same_line_clips_both_boundaries() -> None:
    """AC-1c: a drag across two runs on the same visual line clips the start run
    and the end run, with one highlight rect for the line."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tworun.pdf"
        doc = fitz.open()
        page = doc.new_page(width=500, height=200)
        page.insert_text((40, 60), "ALPHA", fontsize=20.0, fontname="helv")
        page.insert_text((200, 60), "BETA", fontsize=20.0, fontname="cour")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) == 2
            run_a, run_b = runs[0], runs[1]
            chars_a = model.get_chars_in_run(1, run_a.span_id)
            chars_b = model.get_chars_in_run(1, run_b.span_id)
            assert "".join(c for c, _ in chars_a) == "ALPHA"
            assert "".join(c for c, _ in chars_b) == "BETA"

            # Start inside ALPHA at char 2 (P), end inside BETA after char 1 (E).
            start_pt = fitz.Point(chars_a[2][1].x0 + 0.5, (chars_a[2][1].y0 + chars_a[2][1].y1) / 2)
            end_pt = fitz.Point(chars_b[1][1].x1 - 0.5, (chars_b[1][1].y0 + chars_b[1][1].y1) / 2)

            text, rects = model.get_text_selection_lines(1, run_a.span_id, end_pt, start_pt)
            assert text == "PHABE", f"expected 'PHABE', got {text!r}"
            assert len(rects) == 1
        finally:
            model.close()


def test_multi_run_selection_fetches_rawdict_once(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rawdict_once.pdf"
        doc = fitz.open()
        page = doc.new_page(width=500, height=200)
        page.insert_text((40, 60), "ALPHA", fontsize=20.0, fontname="helv")
        page.insert_text((200, 60), "BETA", fontsize=20.0, fontname="cour")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) == 2
            run_a, run_b = runs[0], runs[1]
            chars_a = model.get_chars_in_run(1, run_a.span_id)
            chars_b = model.get_chars_in_run(1, run_b.span_id)
            start_pt = fitz.Point(chars_a[2][1].x0 + 0.5, (chars_a[2][1].y0 + chars_a[2][1].y1) / 2)
            end_pt = fitz.Point(chars_b[1][1].x1 - 0.5, (chars_b[1][1].y0 + chars_b[1][1].y1) / 2)

            real_get_text = fitz.Page.get_text
            calls = {"rawdict": 0}

            def counting_get_text(self, *args, **kwargs):
                option = kwargs.get("option")
                if option is None and args:
                    option = args[0]
                if option == "rawdict":
                    calls["rawdict"] += 1
                return real_get_text(self, *args, **kwargs)

            monkeypatch.setattr(fitz.Page, "get_text", counting_get_text)

            text, _ = model.get_text_selection_lines(1, run_a.span_id, end_pt, start_pt)
            assert text == "PHABE"
            assert calls["rawdict"] == 1
        finally:
            model.close()


def test_multi_line_drag_partial_first_full_middle_partial_last() -> None:
    """AC-1d: across visual lines — partial first, full middle, partial last."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi.pdf"
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        # Three separate lines at distinct y positions.
        page.insert_text((40, 60), "FIRSTLINE", fontsize=20.0, fontname="helv")
        page.insert_text((40, 100), "MIDDLELINE", fontsize=20.0, fontname="helv")
        page.insert_text((40, 140), "LASTLINE", fontsize=20.0, fontname="helv")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) >= 3
            first_run = runs[0]
            last_run = runs[-1]
            first_chars = model.get_chars_in_run(1, first_run.span_id)
            last_chars = model.get_chars_in_run(1, last_run.span_id)

            # Start mid-way through the first line, end mid-way through the last.
            start_pt = fitz.Point(
                first_chars[3][1].x0,
                (first_chars[3][1].y0 + first_chars[3][1].y1) / 2,
            )
            end_pt = fitz.Point(
                last_chars[3][1].x1,
                (last_chars[3][1].y0 + last_chars[3][1].y1) / 2,
            )
            text, rects = model.get_text_selection_lines(
                1, first_run.span_id, end_pt, start_pt
            )
            lines = text.split("\n")
            assert len(lines) == 3, f"expected 3 lines, got {lines!r}"
            # First line is clipped from char 3 → end; last line clipped to char 3.
            assert lines[0] == "STLINE", f"first line: {lines[0]!r}"
            assert lines[1] == "MIDDLELINE", f"middle line: {lines[1]!r}"
            assert lines[2] == "LAST", f"last line: {lines[2]!r}"
            assert len(rects) == 3
        finally:
            model.close()
