# -*- coding: utf-8 -*-
"""
Focused model-level regressions for Track A/B follow-up fixes.

Coverage:
1. Move-only run edit should relocate text without rollback.
2. Move-only paragraph edit should preserve per-run colors.
3. Missing protected span validation should report span IDs.
"""
import io
import sys
import tempfile
from pathlib import Path

import fitz

# Script-style integration runner; keep out of pytest auto-collection.
__test__ = False

if sys.platform == "win32" and __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel
from model.text_block import EditableSpan


def _norm(model: PDFModel, text: str) -> str:
    return model._normalize_text_for_compare(text)


def _clip_has(model: PDFModel, page: fitz.Page, rect: fitz.Rect, expected: str) -> bool:
    clipped = page.get_text("text", clip=rect)
    return _norm(model, expected) in _norm(model, clipped)


def _make_move_pdf(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Move me exactly", fontsize=12, fontname="helv")
    page.insert_text((72, 220), "Neighbor block", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_multicolor_pdf(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    html = (
        '<p style="font-size:12pt;font-family:Helvetica;">'
        '<span style="color:#cc0000;">Red</span> '
        '<span style="color:#0033cc;">Blue</span>'
        "</p>"
    )
    page.insert_htmlbox(fitz.Rect(72, 72, 240, 120), html, scale_low=0)
    doc.save(path, garbage=0)
    doc.close()


def _find_run(model: PDFModel, page_idx: int, probe: str):
    model.ensure_page_index_built(page_idx + 1)
    for run in model.block_manager.get_runs(page_idx):
        if probe in (run.text or ""):
            return run
    return None


def _run_case(name: str, func) -> bool:
    try:
        func()
        print(f"PASS {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def case_move_only_run() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "move.pdf"
        _make_move_pdf(str(pdf_path))

        model = PDFModel()
        try:
            model.open_pdf(str(pdf_path))
            target_run = _find_run(model, 0, "Move")
            if target_run is None:
                raise AssertionError("target run not found")

            old_rect = fitz.Rect(target_run.bbox)
            new_rect = fitz.Rect(old_rect.x0, old_rect.y0 + 180, old_rect.x1, old_rect.y1 + 180)
            model.edit_text(
                page_num=1,
                rect=old_rect,
                new_text=target_run.text,
                font=target_run.font,
                size=int(target_run.size),
                color=tuple(target_run.color),
                original_text=target_run.text,
                new_rect=new_rect,
                target_span_id=target_run.span_id,
                target_mode="run",
            )

            page = model.doc[0]
            new_probe = fitz.Rect(new_rect.x0 - 5, new_rect.y0 - 5, new_rect.x1 + 5, new_rect.y1 + 10)
            old_probe = fitz.Rect(old_rect.x0 - 2, old_rect.y0 - 2, old_rect.x1 + 2, old_rect.y1 + 6)
            if not _clip_has(model, page, new_probe, target_run.text):
                raise AssertionError("moved text not found near new rect")
            if _clip_has(model, page, old_probe, target_run.text):
                raise AssertionError("old rect still contains moved text")
        finally:
            model.close()


def case_move_only_paragraph_preserves_colors() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "multicolor.pdf"
        _make_multicolor_pdf(str(pdf_path))

        model = PDFModel()
        try:
            model.open_pdf(str(pdf_path))
            red_run = _find_run(model, 0, "Red")
            blue_run = _find_run(model, 0, "Blue")
            if red_run is None or blue_run is None:
                raise AssertionError("colored runs not found before edit")

            para = model.block_manager.find_paragraph_for_run(0, red_run.span_id)
            if para is None:
                raise AssertionError("paragraph target not found")

            old_rect = fitz.Rect(para.bbox)
            new_rect = fitz.Rect(old_rect.x0, old_rect.y0 + 180, old_rect.x1, old_rect.y1 + 180)
            model.edit_text(
                page_num=1,
                rect=old_rect,
                new_text=para.text,
                font=para.font,
                size=int(para.size),
                color=tuple(para.color),
                original_text=para.text,
                new_rect=new_rect,
                target_span_id=red_run.span_id,
                target_mode="paragraph",
            )

            model.block_manager.rebuild_page(0, model.doc)
            moved_runs = [
                run for run in model.block_manager.get_runs(0)
                if fitz.Rect(run.bbox).intersects(new_rect)
            ]
            moved_red = next((run for run in moved_runs if "Red" in (run.text or "")), None)
            moved_blue = next((run for run in moved_runs if "Blue" in (run.text or "")), None)
            if moved_red is None or moved_blue is None:
                raise AssertionError("moved colored runs not found after edit")
            if float(moved_red.color[0]) < 0.6:
                raise AssertionError(f"red component lost: {moved_red.color}")
            if float(moved_blue.color[2]) < 0.6:
                raise AssertionError(f"blue component lost: {moved_blue.color}")
        finally:
            model.close()


def case_missing_protected_span_ids() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "protected.pdf"
        _make_move_pdf(str(pdf_path))

        model = PDFModel()
        try:
            model.open_pdf(str(pdf_path))
            page = model.doc[0]
            spans = [
                EditableSpan(
                    span_id="keep-span",
                    page_idx=0,
                    block_idx=0,
                    line_idx=0,
                    span_idx=0,
                    bbox=fitz.Rect(72, 88, 140, 104),
                    origin=fitz.Point(72, 100),
                    text="Neighbor block",
                    font="helv",
                    size=12.0,
                    color=(0.0, 0.0, 0.0),
                    dir_vec=(1.0, 0.0),
                    rotation=0,
                ),
                EditableSpan(
                    span_id="missing-span",
                    page_idx=0,
                    block_idx=0,
                    line_idx=0,
                    span_idx=1,
                    bbox=fitz.Rect(72, 88, 140, 104),
                    origin=fitz.Point(72, 100),
                    text="definitely missing text",
                    font="helv",
                    size=12.0,
                    color=(0.0, 0.0, 0.0),
                    dir_vec=(1.0, 0.0),
                    rotation=0,
                ),
            ]
            missing = model._missing_protected_span_ids(page, spans)
            if missing != ["missing-span"]:
                raise AssertionError(f"unexpected missing span ids: {missing}")
        finally:
            model.close()


def main() -> int:
    cases = [
        ("move-only-run", case_move_only_run),
        ("move-only-paragraph-colors", case_move_only_paragraph_preserves_colors),
        ("missing-protected-ids", case_missing_protected_span_ids),
    ]
    passed = sum(1 for name, func in cases if _run_case(name, func))
    total = len(cases)
    print(f"\nResult: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
