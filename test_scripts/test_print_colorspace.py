from __future__ import annotations

import fitz
import pytest

from src.printing.base_driver import PrintJobOptions
from src.printing.errors import PrintJobSubmissionError
from src.printing.qt_bridge import raster_print_pdf


def test_raster_print_pdf_uses_render_colorspace_from_extra_options(monkeypatch) -> None:
    import src.printing.qt_bridge as qt_bridge_module

    observed: dict[str, object] = {}

    class _FakeRenderer:
        def __init__(self, displaylist_cache_size: int = 24, colorspace: fitz.Colorspace = fitz.csRGB):
            observed["colorspace"] = colorspace

        def iter_page_images(self, _pdf_path: str, _page_indices: list[int], _dpi: int):
            return iter(())

    class _FakePrinter:
        HighResolution = 1
        PdfFormat = 2

        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def setOutputFormat(self, *_args, **_kwargs) -> None:
            return None

        def setOutputFileName(self, *_args, **_kwargs) -> None:
            return None

        def setPrinterName(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(qt_bridge_module, "PDFRenderer", _FakeRenderer)
    monkeypatch.setattr(qt_bridge_module, "QPrinter", _FakePrinter)
    monkeypatch.setattr(qt_bridge_module, "_ensure_qapplication", lambda: None)
    monkeypatch.setattr(qt_bridge_module, "_apply_printer_options", lambda *_args, **_kwargs: None)

    options = PrintJobOptions(
        printer_name="Printer A",
        extra_options={"render_colorspace": "gray"},
    )

    with pytest.raises(PrintJobSubmissionError):
        raster_print_pdf("ignored.pdf", [0], options)

    assert observed["colorspace"] is fitz.csGRAY
