# -*- coding: utf-8 -*-
"""Regression tests for char-level run reconstruction from rawdict."""

from __future__ import annotations

from pathlib import Path
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.edit_commands import EditTextCommand
from model.pdf_model import PDFModel


def _norm(s: str) -> str:
    return "".join((s or "").split()).lower()


def test_runs_merge_micro_spans_on_test_file_1() -> None:
    model = PDFModel()
    try:
        model.open_pdf("test_files/1.pdf")
        model.ensure_page_index_built(1)
        runs = model.block_manager.get_runs(0)
        texts = [_norm(r.text) for r in runs if (r.text or "").strip()]

        assert "young" in texts, f"expected merged token 'young', got {texts}"
        assert "the" in texts, f"expected merged token 'the', got {texts}"
        assert "y" not in texts, f"unexpected micro-token 'y' still present: {texts}"
        assert "oung" not in texts, f"unexpected micro-token 'oung' still present: {texts}"
    finally:
        model.close()


def test_hit_and_edit_use_reconstructed_run() -> None:
    model = PDFModel()
    try:
        model.open_pdf("test_files/1.pdf")
        model.ensure_page_index_built(1)
        runs = model.block_manager.get_runs(0)
        target = next((r for r in runs if _norm(r.text) == "young"), None)
        assert target is not None, "cannot locate merged run 'young'"

        center = fitz.Point(
            (target.bbox.x0 + target.bbox.x1) / 2.0,
            (target.bbox.y0 + target.bbox.y1) / 2.0,
        )
        hit = model.get_text_info_at_point(1, center)
        assert hit is not None
        assert _norm(hit.target_text) == "young", f"hit mismatch: {hit.target_text!r}"

        model.edit_text(
            page_num=1,
            rect=fitz.Rect(target.bbox),
            new_text="older",
            font=target.font,
            size=max(8, int(round(target.size))),
            color=target.color,
            original_text=target.text,
            target_span_id=target.span_id,
        )

        page_text = _norm(model.doc[0].get_text("text"))
        assert "older" in page_text, f"missing edited token in page text: {page_text!r}"
    finally:
        model.close()


def test_paragraph_mode_hit_and_redo_stability() -> None:
    model = PDFModel()
    try:
        model.open_pdf("test_files/1.pdf")
        model.ensure_page_index_built(1)
        model.set_text_target_mode("paragraph")

        runs = model.block_manager.get_runs(0)
        target = next((r for r in runs if _norm(r.text) == "young"), None)
        assert target is not None, "cannot locate anchor run 'young'"

        center = fitz.Point(
            (target.bbox.x0 + target.bbox.x1) / 2.0,
            (target.bbox.y0 + target.bbox.y1) / 2.0,
        )
        hit = model.get_text_info_at_point(1, center)
        assert hit is not None
        assert hit.target_mode == "paragraph"
        assert "young" in _norm(hit.target_text), f"paragraph hit text missing anchor token: {hit.target_text!r}"

        snapshot = model._capture_page_snapshot(0)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(hit.target_bbox),
            new_text="when i was older",
            font=hit.font,
            size=max(8, int(round(hit.size))),
            color=hit.color,
            original_text=hit.target_text,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=hit.target_span_id,
            old_block_text=hit.target_text,
            new_rect=None,
            target_span_id=hit.target_span_id,
            target_mode=hit.target_mode,
        )
        model.command_manager.execute(cmd)
        page_after_edit = _norm(model.doc[0].get_text("text"))
        assert "wheniwasolder" in page_after_edit, f"paragraph edit missing: {page_after_edit!r}"

        model.command_manager.undo()
        page_after_undo = _norm(model.doc[0].get_text("text"))
        assert "young" in page_after_undo, f"undo should recover original paragraph: {page_after_undo!r}"

        # Switch global mode to prove redo still replays paragraph scope from command payload.
        model.set_text_target_mode("run")
        model.command_manager.redo()
        page_after_redo = _norm(model.doc[0].get_text("text"))
        assert "wheniwasolder" in page_after_redo, f"redo should preserve paragraph mode semantics: {page_after_redo!r}"
    finally:
        model.close()


def test_paragraph_drag_without_text_change_with_overlap() -> None:
    model = PDFModel()
    try:
        model.open_pdf("test_files/1.pdf")
        model.ensure_page_index_built(1)
        model.set_text_target_mode("paragraph")

        runs = model.block_manager.get_runs(0)
        anchor = next((r for r in runs if _norm(r.text) == "program"), None)
        assert anchor is not None, "cannot locate paragraph anchor run"

        center = fitz.Point(
            (anchor.bbox.x0 + anchor.bbox.x1) / 2.0,
            (anchor.bbox.y0 + anchor.bbox.y1) / 2.0,
        )
        hit = model.get_text_info_at_point(1, center)
        assert hit is not None and hit.target_mode == "paragraph"

        moved_rect = fitz.Rect(
            hit.target_bbox.x0,
            hit.target_bbox.y0 + 80,
            hit.target_bbox.x1,
            min(model.doc[0].rect.y1 - 5, hit.target_bbox.y1 + 80),
        )
        model.edit_text(
            page_num=1,
            rect=fitz.Rect(hit.target_bbox),
            new_text=hit.target_text,
            font=hit.font,
            size=max(8, int(round(hit.size))),
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode=hit.target_mode,
            new_rect=moved_rect,
        )

        page_text = _norm(model.doc[0].get_text("text"))
        assert "program" in page_text, f"missing paragraph text after drag edit: {page_text!r}"
        assert "favorite" in page_text, f"missing paragraph tail after drag edit: {page_text!r}"
    finally:
        model.close()


def test_paragraph_drag_twice_with_stale_span_id() -> None:
    model = PDFModel()
    try:
        model.open_pdf("test_files/1.pdf")
        model.ensure_page_index_built(1)
        model.set_text_target_mode("paragraph")

        runs = model.block_manager.get_runs(0)
        anchor = next((r for r in runs if _norm(r.text) == "program"), None)
        assert anchor is not None, "cannot locate paragraph anchor run"

        center = fitz.Point(
            (anchor.bbox.x0 + anchor.bbox.x1) / 2.0,
            (anchor.bbox.y0 + anchor.bbox.y1) / 2.0,
        )
        hit = model.get_text_info_at_point(1, center)
        assert hit is not None and hit.target_mode == "paragraph"

        moved_down = fitz.Rect(
            hit.target_bbox.x0,
            hit.target_bbox.y0 + 80,
            hit.target_bbox.x1,
            min(model.doc[0].rect.y1 - 5, hit.target_bbox.y1 + 80),
        )
        moved_up = fitz.Rect(
            hit.target_bbox.x0,
            max(model.doc[0].rect.y0, hit.target_bbox.y0 - 80),
            hit.target_bbox.x1,
            hit.target_bbox.y1 - 80,
        )

        # 1) First drag with paragraph payload.
        model.edit_text(
            page_num=1,
            rect=fitz.Rect(hit.target_bbox),
            new_text=hit.target_text,
            font=hit.font,
            size=max(8, int(round(hit.size))),
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode=hit.target_mode,
            new_rect=moved_down,
        )

        # 2) Reuse the same (now stale) target_span_id and drag back.
        model.edit_text(
            page_num=1,
            rect=fitz.Rect(hit.target_bbox),
            new_text=hit.target_text,
            font=hit.font,
            size=max(8, int(round(hit.size))),
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode=hit.target_mode,
            new_rect=moved_up,
        )

        page_text = _norm(model.doc[0].get_text("text"))
        assert "program" in page_text, f"missing paragraph text after second drag: {page_text!r}"
        assert "favorite" in page_text, f"missing paragraph tail after second drag: {page_text!r}"
    finally:
        model.close()


if __name__ == "__main__":
    test_runs_merge_micro_spans_on_test_file_1()
    test_hit_and_edit_use_reconstructed_run()
    test_paragraph_mode_hit_and_redo_stability()
    test_paragraph_drag_without_text_change_with_overlap()
    test_paragraph_drag_twice_with_stale_span_id()
    print("PASS: char-run reconstruction regression suite")
