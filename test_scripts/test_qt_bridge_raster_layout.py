from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing import qt_bridge as qtb
from src.printing.base_driver import PrintJobOptions


class _FakePrinter:
    HighResolution = 1
    PdfFormat = 2

    def __init__(self, mode) -> None:
        _ = mode
        self.new_page_calls = 0
        self._layout = object()

    def setOutputFormat(self, fmt) -> None:
        _ = fmt

    def setOutputFileName(self, path) -> None:
        _ = path

    def setPrinterName(self, name) -> None:
        _ = name

    def pageLayout(self):
        return self._layout

    def setPageLayout(self, layout) -> None:
        self._layout = layout

    def newPage(self) -> None:
        self.new_page_calls += 1


class _FakePainter:
    def begin(self, printer) -> bool:
        _ = printer
        return True

    def end(self) -> None:
        return None


class _FakeRenderer:
    def iter_page_images(self, pdf_path: str, page_indices: list[int], dpi: int):
        _ = (pdf_path, dpi)
        for _idx in page_indices:
            yield SimpleNamespace(
                page_rect=SimpleNamespace(width=200.0, height=300.0),
                image=None,
            )


def test_raster_print_updates_layout_per_page_when_source_pages_differ(monkeypatch) -> None:
    layout_calls: list[tuple[object, object, object]] = []

    monkeypatch.setattr(qtb, "_ensure_qapplication", lambda: None)
    monkeypatch.setattr(qtb, "QPrinter", _FakePrinter)
    monkeypatch.setattr(qtb, "QPainter", _FakePainter)
    monkeypatch.setattr(qtb, "_apply_printer_options", lambda printer, options: None)
    monkeypatch.setattr(qtb, "_draw_page_image", lambda painter, printer, rendered, options: None)

    def _record_layout(printer, page_rect, options) -> None:
        layout_calls.append((printer, page_rect, options))

    monkeypatch.setattr(qtb, "_set_page_layout", _record_layout)

    options = PrintJobOptions(
        printer_name="Printer A",
        dpi=300,
        paper_size="auto",
        orientation="auto",
    )
    result = qtb.raster_print_pdf(
        pdf_path="dummy.pdf",
        page_indices=[0, 1, 2],
        options=options,
        renderer=SimpleNamespace(
            iter_page_images=lambda _pdf_path, _page_indices, _dpi: iter(
                [
                    SimpleNamespace(page_rect=SimpleNamespace(width=200.0, height=300.0), image=None),
                    SimpleNamespace(page_rect=SimpleNamespace(width=300.0, height=200.0), image=None),
                    SimpleNamespace(page_rect=SimpleNamespace(width=420.0, height=300.0), image=None),
                ]
            )
        ),
    )

    assert result.success is True
    assert len(layout_calls) == 3


def test_raster_print_applies_layout_for_single_auto_page(monkeypatch) -> None:
    layout_calls: list[tuple[object, object, object]] = []

    monkeypatch.setattr(qtb, "_ensure_qapplication", lambda: None)
    monkeypatch.setattr(qtb, "QPrinter", _FakePrinter)
    monkeypatch.setattr(qtb, "QPainter", _FakePainter)
    monkeypatch.setattr(qtb, "_apply_printer_options", lambda printer, options: None)
    monkeypatch.setattr(qtb, "_draw_page_image", lambda painter, printer, rendered, options: None)
    monkeypatch.setattr(qtb, "_set_page_layout", lambda printer, page_rect, options: layout_calls.append((printer, page_rect, options)))

    result = qtb.raster_print_pdf(
        pdf_path="dummy.pdf",
        page_indices=[0],
        options=PrintJobOptions(printer_name="Printer A", dpi=300),
        renderer=_FakeRenderer(),
    )

    assert result.success is True
    assert len(layout_calls) == 1
