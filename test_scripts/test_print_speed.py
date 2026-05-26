"""AC-9a — print spool throughput.

A 10-page A4 PDF at 300 DPI must be fully rastered and spooled within 20 s.
We spool to a PDF output target (route ``qt-raster->pdf``) so the test needs no
physical printer; this exercises the same render + QPainter→QPrinter path used
for hardware spooling, which is the slow part the review flagged.

AC-9b (progress visible) and AC-9c (no UI freeze) are covered structurally: the
controller runs submission on a QThread worker with progress signals
(see controller/pdf_controller.py::_PrintSubmissionWorker) and the actual spool
runs in an out-of-process helper.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import fitz

from src.printing.base_driver import PrintJobOptions
from src.printing.qt_bridge import raster_print_pdf

_SPOOL_BUDGET_SEC = 20.0


def _make_a4_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595.28, height=841.89)  # A4 portrait
        page.insert_text((72, 72), f"Page {i + 1} " + "lorem ipsum " * 40, fontsize=11.0)
    doc.save(path)
    doc.close()


def test_ten_page_a4_300dpi_spools_within_budget() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.pdf"
        out = Path(tmp) / "out.pdf"
        _make_a4_pdf(src, pages=10)

        options = PrintJobOptions(
            dpi=300,
            paper_size="auto",
            orientation="auto",
            output_pdf_path=str(out),
            job_name="speed_test",
        )

        start = time.perf_counter()
        result = raster_print_pdf(str(src), list(range(10)), options)
        elapsed = time.perf_counter() - start

        assert result.success is True
        assert out.exists() and out.stat().st_size > 0
        assert elapsed < _SPOOL_BUDGET_SEC, (
            f"10-page A4 @300 DPI took {elapsed:.1f}s, budget is {_SPOOL_BUDGET_SEC:.0f}s"
        )
