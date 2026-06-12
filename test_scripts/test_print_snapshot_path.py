"""Phase 3.2 — print snapshot writes directly to a destination path."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from model.pdf_model import PDFModel

SAMPLE_TEXT = "print snapshot path"


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), SAMPLE_TEXT, fontsize=12, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def test_build_print_snapshot_writes_valid_pdf_to_dest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_pdf(pdf_path)
        dest = Path(tmp) / "print_input.pdf"

        m = PDFModel()
        try:
            m.open_pdf(str(pdf_path))
            # Red-light: old signature is build_print_snapshot() -> bytes,
            # so passing a dest raises TypeError.
            result = m.build_print_snapshot(dest)
            assert result is None
            assert dest.exists()
            assert dest.stat().st_size > 0

            out_doc = fitz.open(str(dest))
            try:
                assert len(out_doc) == 1
                assert SAMPLE_TEXT in out_doc[0].get_text("text")
            finally:
                out_doc.close()
        finally:
            m.close()


def test_build_print_snapshot_overlay_path_writes_to_dest(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_pdf(pdf_path)
        dest = Path(tmp) / "print_input_overlay.pdf"

        m = PDFModel()
        try:
            m.open_pdf(str(pdf_path))

            overlay_calls: list[int] = []

            def _needs_overlay(session_id: str, page_num: int, purpose: str) -> bool:
                return purpose == "print"

            def _apply_overlay(session_id: str, page_num: int, page, purpose: str) -> None:
                overlay_calls.append(page_num)

            monkeypatch.setattr(m.tools.watermark, "needs_page_overlay", _needs_overlay)
            monkeypatch.setattr(m.tools.watermark, "apply_page_overlay", _apply_overlay)

            result = m.build_print_snapshot(dest)
            assert result is None
            assert dest.exists()
            assert overlay_calls == [1], "overlay should run once for the single page"

            out_doc = fitz.open(str(dest))
            try:
                assert len(out_doc) == 1
                assert SAMPLE_TEXT in out_doc[0].get_text("text")
            finally:
                out_doc.close()
        finally:
            m.close()


def test_watermark_needs_page_overlay_skips_print_purpose() -> None:
    m = PDFModel()
    try:
        m.tools.watermark._watermarks_by_session["sid"] = [{"id": "wm-1", "pages": [1], "text": "stamp"}]
        # Red-light: print path should not request GUI overlay stamping even when a watermark exists.
        assert m.tools.watermark.needs_page_overlay("sid", 1, "print") is False
    finally:
        m.close()
