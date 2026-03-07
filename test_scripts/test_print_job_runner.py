# -*- coding: utf-8 -*-
"""Subprocess print-job execution regressions."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrintJobOptions, PrintJobResult
from src.printing.print_job_runner import run_print_job_request, serialize_print_options


def _make_single_page_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_run_print_job_request_applies_watermarks_before_dispatch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        input_pdf = Path(tmp) / "input.pdf"
        request_path = Path(tmp) / "request.json"
        _make_single_page_pdf(input_pdf, "base text")

        request_path.write_text(
            json.dumps(
                {
                    "input_pdf_path": str(input_pdf),
                    "watermarks": [
                        {
                            "id": "wm-1",
                            "pages": [1],
                            "text": "CONFIDENTIAL",
                            "angle": 0,
                            "opacity": 0.4,
                            "font_size": 18,
                            "color": [0.5, 0.5, 0.5],
                            "font": "helv",
                            "offset_x": 0,
                            "offset_y": 0,
                            "line_spacing": 1.3,
                        }
                    ],
                    "options": serialize_print_options(
                        PrintJobOptions(
                            printer_name="Printer A",
                            job_name="runner test",
                        )
                    ),
                }
            ),
            encoding="utf-8",
        )

        progress_messages: list[str] = []

        class _FakeDispatcher:
            def print_pdf_file(self, pdf_path: str, options: PrintJobOptions) -> PrintJobResult:
                assert options.printer_name == "Printer A"
                doc = fitz.open(pdf_path)
                try:
                    text = doc[0].get_text()
                finally:
                    doc.close()
                assert "CONFIDENTIAL" in text
                return PrintJobResult(
                    success=True,
                    route="external-process",
                    message=f"Submitted {Path(pdf_path).name} to printer.",
                )

        result = run_print_job_request(
            request_path,
            dispatcher=_FakeDispatcher(),
            progress_cb=progress_messages.append,
        )

        assert progress_messages == [
            "正在準備列印內容，請稍候...",
            "正在送出列印工作，請稍候...",
        ]
        assert result.success is True
        assert result.route == "external-process"
