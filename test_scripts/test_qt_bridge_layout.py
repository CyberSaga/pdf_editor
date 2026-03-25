# -*- coding: utf-8 -*-
"""Regression tests for Qt bridge page-layout and override behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrintJobOptions
from src.printing import qt_bridge as qtb


class _FakePrinter:
    HighResolution = 1
    PdfFormat = 2

    def __init__(self, mode) -> None:
        _ = mode
        self.new_page_calls = 0

    def setOutputFormat(self, fmt) -> None:
        _ = fmt

    def setOutputFileName(self, path) -> None:
        _ = path

    def setPrinterName(self, name) -> None:
        _ = name

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


def test_raster_print_sets_layout_once_before_print_loop(monkeypatch) -> None:
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
        override_fields={"paper_size", "orientation"},
    )
    result = qtb.raster_print_pdf(
        pdf_path="dummy.pdf",
        page_indices=[0, 1, 2],
        options=options,
        renderer=_FakeRenderer(),
    )

    assert result.success is True
    assert len(layout_calls) == 1


def test_raster_print_skips_layout_when_not_overridden(monkeypatch) -> None:
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
    assert layout_calls == []


def test_apply_printer_options_keeps_system_tray_when_auto(monkeypatch) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.paper_source_calls: list[object] = []
            self.duplex_calls: list[object] = []
            self.color_mode_calls: list[object] = []

        def setDocName(self, value) -> None:
            _ = value

        def setResolution(self, value) -> None:
            _ = value

        def setCopyCount(self, value) -> None:
            _ = value

        def setCollateCopies(self, value) -> None:
            _ = value

        def setDuplex(self, value) -> None:
            self.duplex_calls.append(value)

        def setPaperSource(self, value) -> None:
            self.paper_source_calls.append(value)

        def setColorMode(self, value) -> None:
            self.color_mode_calls.append(value)

    monkeypatch.setattr(qtb, "_to_duplex_mode", lambda _duplex: "duplex")
    monkeypatch.setattr(qtb, "_to_paper_source", lambda _source: "paper_source")
    monkeypatch.setattr(qtb, "QPrinter", SimpleNamespace(GrayScale="gray", Color="color"))

    printer_auto = _Recorder()
    qtb._apply_printer_options(printer_auto, PrintJobOptions(paper_tray="auto"))
    assert printer_auto.paper_source_calls == []

    printer_explicit = _Recorder()
    qtb._apply_printer_options(
        printer_explicit,
        PrintJobOptions(
            paper_tray="2",
            override_fields={"duplex", "color_mode"},
        ),
    )
    assert printer_explicit.paper_source_calls == ["paper_source"]
    assert printer_auto.duplex_calls == []
    assert printer_auto.color_mode_calls == []
    assert printer_explicit.duplex_calls == ["duplex"]
    assert printer_explicit.color_mode_calls == ["color"]


def test_apply_printer_options_sets_hardware_only_when_overridden(monkeypatch) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.duplex_calls: list[object] = []
            self.color_mode_calls: list[object] = []

        def setDocName(self, value) -> None:
            _ = value

        def setResolution(self, value) -> None:
            _ = value

        def setCopyCount(self, value) -> None:
            _ = value

        def setCollateCopies(self, value) -> None:
            _ = value

        def setDuplex(self, value) -> None:
            self.duplex_calls.append(value)

        def setPaperSource(self, value) -> None:
            _ = value

        def setColorMode(self, value) -> None:
            self.color_mode_calls.append(value)

    monkeypatch.setattr(qtb, "_to_duplex_mode", lambda _duplex: "duplex")
    monkeypatch.setattr(qtb, "QPrinter", SimpleNamespace(GrayScale="gray", Color="color"))

    untouched = _Recorder()
    qtb._apply_printer_options(
        untouched,
        PrintJobOptions(duplex="long", color_mode="grayscale"),
    )
    assert untouched.duplex_calls == []
    assert untouched.color_mode_calls == []

    overridden = _Recorder()
    qtb._apply_printer_options(
        overridden,
        PrintJobOptions(
            duplex="long",
            color_mode="grayscale",
            override_fields={"duplex", "color_mode"},
        ),
    )
    assert overridden.duplex_calls == ["duplex"]
    assert overridden.color_mode_calls == ["gray"]
