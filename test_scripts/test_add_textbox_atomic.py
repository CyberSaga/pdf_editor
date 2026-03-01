# -*- coding: utf-8 -*-
"""Regression tests for add_text textbox mode backend behavior."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.edit_commands import AddTextboxCommand
from model.pdf_model import PDFModel


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_pdf(path: Path, rotation: int = 0, with_seed: bool = False) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.set_rotation(rotation)
    if with_seed:
        page.insert_text(fitz.Point(40, 40), "KEEP_ORIGINAL", fontsize=12, fontname="helv", color=(0, 0, 0))
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 12, 12), 0)
        pix.clear_with(180)
        page.insert_image(fitz.Rect(220, 30, 260, 70), pixmap=pix)
        annot = page.add_rect_annot(fitz.Rect(40, 80, 110, 120))
        annot.update()
    doc.save(path)
    doc.close()


def _first_span_bbox_contains(page: fitz.Page, token: str) -> fitz.Rect | None:
    probe = _norm(token)
    data = page.get_text("dict", flags=0)
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if probe in _norm(text):
                    return fitz.Rect(span["bbox"])
    return None


def test_add_textbox_rotation_anchor_visual_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for rot in (0, 90, 180, 270):
            path = Path(tmp) / f"rot_{rot}.pdf"
            _make_pdf(path, rotation=rot, with_seed=False)

            model = PDFModel()
            try:
                model.open_pdf(str(path))
                visual_rect = fitz.Rect(70, 58, 190, 116)
                token = f"ROT{rot}"
                model.add_textbox(
                    page_num=1,
                    visual_rect=visual_rect,
                    text=token,
                    font="",
                    size=18,
                    color=(0, 0, 0),
                )

                page = model.doc[0]
                span_bbox = _first_span_bbox_contains(page, token)
                assert span_bbox is not None, f"missing inserted token on rotation={rot}"
                visual_bbox = span_bbox * page.rotation_matrix

                # Anchor should map close to visual click-top-left regardless of page rotation.
                assert abs(visual_bbox.x0 - visual_rect.x0) <= 8.0, (rot, visual_bbox, visual_rect)
                assert abs(visual_bbox.y0 - visual_rect.y0) <= 20.0, (rot, visual_bbox, visual_rect)
            finally:
                model.close()


def test_add_textbox_default_font_supports_cjk() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cjk.pdf"
        _make_pdf(path, rotation=0, with_seed=False)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            token = "中文測試ABC"
            model.add_textbox(
                page_num=1,
                visual_rect=fitz.Rect(30, 60, 210, 120),
                text=token,
                font="",  # force default path
                size=16,
                color=(0, 0, 0),
            )
            page_text = model.doc[0].get_text("text")
            assert _norm(token) in _norm(page_text), page_text
        finally:
            model.close()


def test_add_textbox_atomic_undo_redo_boundaries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "atomic.pdf"
        _make_pdf(path, rotation=0, with_seed=False)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            before_a = model._capture_page_snapshot_strict(0)
            cmd_a = AddTextboxCommand(
                model=model,
                page_num=1,
                visual_rect=fitz.Rect(20, 40, 180, 90),
                text="TOKEN_A",
                font="cjk",
                size=14,
                color=(0, 0, 0),
                before_page_snapshot_bytes=before_a,
            )
            model.command_manager.execute(cmd_a)

            before_b = model._capture_page_snapshot_strict(0)
            cmd_b = AddTextboxCommand(
                model=model,
                page_num=1,
                visual_rect=fitz.Rect(20, 110, 180, 160),
                text="TOKEN_B",
                font="cjk",
                size=14,
                color=(0, 0, 0),
                before_page_snapshot_bytes=before_b,
            )
            model.command_manager.execute(cmd_b)

            t0 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t0 and "token_b" in t0

            model.command_manager.undo()
            t1 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t1 and "token_b" not in t1

            model.command_manager.undo()
            t2 = _norm(model.doc[0].get_text("text"))
            assert "token_a" not in t2 and "token_b" not in t2

            model.command_manager.redo()
            t3 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t3 and "token_b" not in t3

            model.command_manager.redo()
            t4 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t4 and "token_b" in t4
        finally:
            model.close()


def test_add_textbox_undo_keeps_other_page_objects() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nondestructive.pdf"
        _make_pdf(path, rotation=0, with_seed=True)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            before_text = _norm(page.get_text("text"))
            before_image_count = len(page.get_images(full=True))
            before_annots = len(list(page.annots() or []))

            before = model._capture_page_snapshot_strict(0)
            cmd = AddTextboxCommand(
                model=model,
                page_num=1,
                visual_rect=fitz.Rect(30, 160, 200, 210),
                text="NEW_INSERT",
                font="cjk",
                size=14,
                color=(0, 0, 0),
                before_page_snapshot_bytes=before,
            )
            model.command_manager.execute(cmd)
            model.command_manager.undo()

            page_after = model.doc[0]
            after_text = _norm(page_after.get_text("text"))
            after_image_count = len(page_after.get_images(full=True))
            after_annots = len(list(page_after.annots() or []))

            assert "keep_original" in after_text
            assert before_text == after_text
            assert before_image_count == after_image_count
            assert before_annots == after_annots
        finally:
            model.close()


def test_add_textbox_immediately_editable_by_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "editable_immediately.pdf"
        _make_pdf(path, rotation=0, with_seed=False)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            token = "NOW_EDITABLE"
            visual_rect = fitz.Rect(40, 72, 240, 132)
            model.add_textbox(
                page_num=1,
                visual_rect=visual_rect,
                text=token,
                font="cjk",
                size=16,
                color=(0, 0, 0),
            )

            # Click near the first line start in visual coordinates.
            hit = model.get_text_info_at_point(1, fitz.Point(visual_rect.x0 + 4, visual_rect.y0 + 18))
            assert hit is not None, "inserted text not hit-detectable immediately"
            assert "now_editable" in _norm(hit.target_text), hit.target_text
        finally:
            model.close()
