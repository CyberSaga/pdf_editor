# -*- coding: utf-8 -*-
"""Targeted overlap-edit regression tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.edit_commands import EditTextCommand
from model.pdf_model import PDFModel


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_pdf_exact_overlap(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(120, 140, 320, 180)
    page.insert_textbox(rect, "BOTTOM_KEEP", fontsize=14, fontname="helv", color=(0, 0, 0))
    page.insert_textbox(rect, "TOP_EDIT", fontsize=14, fontname="helv", color=(1, 0, 0))
    doc.save(path)
    doc.close()


def _make_pdf_partial_overlap(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(110, 240, 285, 280),
        "LEFT_KEEP",
        fontsize=12,
        fontname="helv",
        color=(0, 0, 0),
    )
    page.insert_textbox(
        fitz.Rect(210, 250, 380, 290),
        "RIGHT_EDIT",
        fontsize=12,
        fontname="helv",
        color=(0.2, 0.0, 0.7),
    )
    doc.save(path)
    doc.close()


def _make_pdf_vertical_overlap(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    point = fitz.Point(280, 560)
    page.insert_text(point, "VERT_KEEP", fontsize=14, fontname="helv", color=(0, 0, 0), rotate=90)
    page.insert_text(point, "VERT_EDIT", fontsize=14, fontname="helv", color=(1, 0, 0), rotate=90)
    doc.save(path)
    doc.close()


def _assert_contains(page_text: str, token: str) -> None:
    assert _norm(token) in _norm(page_text), (
        f"missing token: {token!r}; page_text={page_text!r}"
    )


def _first_span_with(model: PDFModel, page_idx: int, token: str):
    model.ensure_page_index_built(page_idx + 1)
    probe = _norm(token)
    for span in model.block_manager.get_spans(page_idx):
        if probe in _norm(span.text):
            return span
    return None


def _center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def test_exact_overlap_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "exact_overlap.pdf"
        _make_pdf_exact_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target = _first_span_with(model, 0, "TOP_EDIT")
            assert target is not None

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="TOP_EDIT_DONE",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "BOTTOM_KEEP")
            _assert_contains(page_text, "TOP_EDIT_DONE")
        finally:
            model.close()


def test_partial_overlap_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "partial_overlap.pdf"
        _make_pdf_partial_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            target = _first_span_with(model, 0, "RIGHT_EDIT")
            assert target is not None

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="RIGHT_DONE",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "LEFT_KEEP")
            _assert_contains(page_text, "RIGHT_DONE")
        finally:
            model.close()


def test_overlap_undo_redo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "undo_redo_overlap.pdf"
        _make_pdf_exact_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            target = _first_span_with(model, 0, "TOP_EDIT")
            assert target is not None

            snapshot = model._capture_page_snapshot(0)
            cmd = EditTextCommand(
                model=model,
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="TOP_CMD_EDIT",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                vertical_shift_left=True,
                page_snapshot_bytes=snapshot,
                old_block_id=target.span_id,
                old_block_text=target.text,
                new_rect=None,
                target_span_id=target.span_id,
            )
            model.command_manager.execute(cmd)

            t1 = model.doc[0].get_text("text")
            _assert_contains(t1, "BOTTOM_KEEP")
            _assert_contains(t1, "TOP_CMD_EDIT")

            model.command_manager.undo()
            t2 = model.doc[0].get_text("text")
            _assert_contains(t2, "BOTTOM_KEEP")
            _assert_contains(t2, "TOP_EDIT")

            model.command_manager.redo()
            t3 = model.doc[0].get_text("text")
            _assert_contains(t3, "BOTTOM_KEEP")
            _assert_contains(t3, "TOP_CMD_EDIT")
        finally:
            model.close()


def test_vertical_overlap_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "vertical_overlap.pdf"
        _make_pdf_vertical_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            target = _first_span_with(model, 0, "VERT_EDIT")
            assert target is not None

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="VERT_DONE",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "VERT_KEEP")
            _assert_contains(page_text, "VERT_DONE")
        finally:
            model.close()


def test_overlap_replay_with_unavailable_font_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "font_fallback_overlap.pdf"
        _make_pdf_exact_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            spans = model.block_manager.get_spans(0)
            assert len(spans) >= 2

            keep_span = _first_span_with(model, 0, "BOTTOM_KEEP")
            target = _first_span_with(model, 0, "TOP_EDIT")
            assert keep_span is not None and target is not None

            # Simulate extracted embedded/subset font names that are not directly insertable.
            keep_span.font = "ABCDEF+NoSuchEmbeddedFont-Regular"

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="TOP_EDIT_FALLBACK",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "BOTTOM_KEEP")
            _assert_contains(page_text, "TOP_EDIT_FALLBACK")
        finally:
            model.close()


if __name__ == "__main__":
    test_exact_overlap_edit()
    test_partial_overlap_edit()
    test_overlap_undo_redo()
    test_vertical_overlap_edit()
    test_overlap_replay_with_unavailable_font_fallback()
    print("PASS: overlap text edit regression suite")
