"""Regression tests for Qt bridge layout, override gating, and pure print-layout helpers.

Covers Phase 1 Items 1–3:
  Item 1 — override_fields gates which QPrinter setters fire (prefs not mutated on print).
  Item 2 — auto-rotate: _set_page_layout is called per page with each page's own rect.
  Item 3 — paper size from source: auto + named paper both produce correct QPageLayout.

Also absorbs the pure-function checks previously in test_print_dialog_logic.py
(resolve_page_indices, compute_target_draw_rect, PrintJobOptions.normalized).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPageLayout

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing import qt_bridge as qtb
from src.printing.base_driver import PrintJobOptions
from src.printing.layout import compute_target_draw_rect
from src.printing.page_selection import resolve_page_indices


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


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


class _LayoutPrinter:
    """Thin QPrinter stand-in backed by a real QPageLayout for orientation checks."""

    def __init__(self) -> None:
        self._layout = QPageLayout()

    def pageLayout(self):
        return self._layout

    def setPageLayout(self, layout) -> None:
        self._layout = layout


class _FakePainter:
    def begin(self, printer) -> bool:
        _ = printer
        return True

    def end(self) -> None:
        return None


class _UniformRenderer:
    """Yields identical portrait pages — used when page geometry doesn't matter."""

    def iter_page_images(self, pdf_path: str, page_indices: list[int], dpi: int):
        _ = (pdf_path, dpi)
        for _ in page_indices:
            yield SimpleNamespace(
                page_rect=SimpleNamespace(width=200.0, height=300.0),
                image=None,
            )


# ---------------------------------------------------------------------------
# Item 2 — auto-rotate: layout is applied per page with each page's own rect
# ---------------------------------------------------------------------------


def test_raster_print_per_page_layout_receives_correct_rects(monkeypatch) -> None:
    """_set_page_layout fires once per page and receives each page's actual rect."""
    layout_rects: list[tuple[float, float]] = []

    monkeypatch.setattr(qtb, "_ensure_qapplication", lambda: None)
    monkeypatch.setattr(qtb, "QPrinter", _FakePrinter)
    monkeypatch.setattr(qtb, "QPainter", _FakePainter)
    monkeypatch.setattr(qtb, "_apply_printer_options", lambda p, o: None)
    monkeypatch.setattr(qtb, "_draw_page_image", lambda pa, pr, r, o: None)
    monkeypatch.setattr(
        qtb,
        "_set_page_layout",
        lambda printer, page_rect, options: layout_rects.append(
            (page_rect.width(), page_rect.height())
        ),
    )

    result = qtb.raster_print_pdf(
        pdf_path="dummy.pdf",
        page_indices=[0, 1, 2],
        options=PrintJobOptions(printer_name="Printer A", dpi=300, paper_size="auto", orientation="auto"),
        renderer=SimpleNamespace(
            iter_page_images=lambda _pdf, _idx, _dpi: iter([
                SimpleNamespace(page_rect=SimpleNamespace(width=200.0, height=300.0), image=None),
                SimpleNamespace(page_rect=SimpleNamespace(width=300.0, height=200.0), image=None),
                SimpleNamespace(page_rect=SimpleNamespace(width=420.0, height=300.0), image=None),
            ])
        ),
    )

    assert result.success is True
    # Each page's own dimensions — not the first page's dims repeated.
    assert layout_rects == [(200.0, 300.0), (300.0, 200.0), (420.0, 300.0)]


def test_raster_print_single_auto_page_calls_layout_once(monkeypatch) -> None:
    layout_calls: list = []

    monkeypatch.setattr(qtb, "_ensure_qapplication", lambda: None)
    monkeypatch.setattr(qtb, "QPrinter", _FakePrinter)
    monkeypatch.setattr(qtb, "QPainter", _FakePainter)
    monkeypatch.setattr(qtb, "_apply_printer_options", lambda p, o: None)
    monkeypatch.setattr(qtb, "_draw_page_image", lambda pa, pr, r, o: None)
    monkeypatch.setattr(
        qtb, "_set_page_layout",
        lambda printer, page_rect, options: layout_calls.append((printer, page_rect, options)),
    )

    result = qtb.raster_print_pdf(
        pdf_path="dummy.pdf",
        page_indices=[0],
        options=PrintJobOptions(printer_name="Printer A", dpi=300),
        renderer=_UniformRenderer(),
    )

    assert result.success is True
    assert len(layout_calls) == 1


# ---------------------------------------------------------------------------
# Items 2 & 3 — _set_page_layout: orientation and paper size in QPageLayout
# ---------------------------------------------------------------------------


def test_set_page_layout_landscape_source_produces_landscape_layout() -> None:
    """Auto orientation: landscape source (w>h) → QPageLayout.fullRectPoints w>h."""
    printer = _LayoutPrinter()
    qtb._set_page_layout(
        printer,
        QRectF(0.0, 0.0, 1190.5, 841.9),
        PrintJobOptions(paper_size="auto", orientation="auto"),
    )
    rect = printer.pageLayout().fullRectPoints()
    assert rect.width() > rect.height(), f"expected landscape, got {rect.width()}×{rect.height()}"


def test_set_page_layout_portrait_source_produces_portrait_layout() -> None:
    """Auto orientation: portrait source (h>w) → QPageLayout.fullRectPoints h>w."""
    printer = _LayoutPrinter()
    qtb._set_page_layout(
        printer,
        QRectF(0.0, 0.0, 595.0, 842.0),
        PrintJobOptions(paper_size="auto", orientation="auto"),
    )
    rect = printer.pageLayout().fullRectPoints()
    assert rect.height() > rect.width(), f"expected portrait, got {rect.width()}×{rect.height()}"


def test_set_page_layout_named_a4_portrait_uses_a4_dimensions() -> None:
    """paper_size='a4' ignores source dims and applies A4 page size (~595×842 pt)."""
    printer = _LayoutPrinter()
    qtb._set_page_layout(
        printer,
        QRectF(0.0, 0.0, 100.0, 100.0),
        PrintJobOptions(paper_size="a4", orientation="portrait"),
    )
    rect = printer.pageLayout().fullRectPoints()
    # Portrait: height > width; A4 width ≈ 595 pt (±15 for rounding)
    assert rect.height() > rect.width(), f"expected portrait A4, got {rect.width()}×{rect.height()}"
    assert 580 < rect.width() < 610, f"A4 width out of expected range: {rect.width()}"


# ---------------------------------------------------------------------------
# Item 1 — override gating: QPrinter setters must not fire for untouched fields
# ---------------------------------------------------------------------------


def test_apply_printer_options_skips_tray_when_auto(monkeypatch) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.paper_source_calls: list = []
            self.duplex_calls: list = []
            self.color_mode_calls: list = []

        def setDocName(self, v) -> None: _ = v
        def setResolution(self, v) -> None: _ = v
        def setCopyCount(self, v) -> None: _ = v
        def setCollateCopies(self, v) -> None: _ = v
        def setDuplex(self, v) -> None: self.duplex_calls.append(v)
        def setPaperSource(self, v) -> None: self.paper_source_calls.append(v)
        def setColorMode(self, v) -> None: self.color_mode_calls.append(v)

    monkeypatch.setattr(qtb, "_to_duplex_mode", lambda _d: "duplex")
    monkeypatch.setattr(qtb, "_to_paper_source", lambda _s: "paper_source")
    monkeypatch.setattr(qtb, "QPrinter", SimpleNamespace(GrayScale="gray", Color="color"))

    auto = _Recorder()
    qtb._apply_printer_options(auto, PrintJobOptions(paper_tray="auto"))
    assert auto.paper_source_calls == []

    explicit = _Recorder()
    qtb._apply_printer_options(
        explicit,
        PrintJobOptions(paper_tray="2", override_fields={"duplex", "color_mode"}),
    )
    assert explicit.paper_source_calls == ["paper_source"]
    assert auto.duplex_calls == []
    assert auto.color_mode_calls == []
    assert explicit.duplex_calls == ["duplex"]
    assert explicit.color_mode_calls == ["color"]


def test_apply_printer_options_hardware_setters_gated_by_override_fields(monkeypatch) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.duplex_calls: list = []
            self.color_mode_calls: list = []

        def setDocName(self, v) -> None: _ = v
        def setResolution(self, v) -> None: _ = v
        def setCopyCount(self, v) -> None: _ = v
        def setCollateCopies(self, v) -> None: _ = v
        def setDuplex(self, v) -> None: self.duplex_calls.append(v)
        def setPaperSource(self, v) -> None: _ = v
        def setColorMode(self, v) -> None: self.color_mode_calls.append(v)

    monkeypatch.setattr(qtb, "_to_duplex_mode", lambda _d: "duplex")
    monkeypatch.setattr(qtb, "QPrinter", SimpleNamespace(GrayScale="gray", Color="color"))

    untouched = _Recorder()
    qtb._apply_printer_options(
        untouched,
        PrintJobOptions(duplex="long", color_mode="grayscale"),
    )
    assert untouched.duplex_calls == [], "duplex setter must not fire without override"
    assert untouched.color_mode_calls == [], "color setter must not fire without override"

    overridden = _Recorder()
    qtb._apply_printer_options(
        overridden,
        PrintJobOptions(duplex="long", color_mode="grayscale", override_fields={"duplex", "color_mode"}),
    )
    assert overridden.duplex_calls == ["duplex"]
    assert overridden.color_mode_calls == ["gray"]


# ---------------------------------------------------------------------------
# Pure layout helpers (previously test_print_dialog_logic.py — not a pytest
# file, so pytest never collected it; converted here for active enforcement)
# ---------------------------------------------------------------------------


def test_resolve_page_indices_odd_subset_and_reverse() -> None:
    indices = resolve_page_indices(
        total_pages=10, page_ranges="1,3,5-8", page_subset="odd", reverse_order=False
    )
    assert indices == [0, 2, 4, 6]

    indices_reversed = resolve_page_indices(
        total_pages=10, page_ranges="1,3,5-8", page_subset="odd", reverse_order=True
    )
    assert indices_reversed == [6, 4, 2, 0]


def test_compute_target_draw_rect_fit_actual_custom() -> None:
    fit = compute_target_draw_rect(600, 800, 1200, 600, scale_mode="fit", scale_percent=100)
    assert abs(fit[2] - 600) < 1e-6
    assert abs(fit[3] - 300) < 1e-6

    actual = compute_target_draw_rect(600, 800, 300, 200, scale_mode="actual", scale_percent=100)
    assert abs(actual[2] - 300) < 1e-6
    assert abs(actual[3] - 200) < 1e-6

    custom = compute_target_draw_rect(600, 800, 300, 200, scale_mode="custom", scale_percent=150)
    assert abs(custom[2] - 450) < 1e-6
    assert abs(custom[3] - 300) < 1e-6


def test_print_job_options_normalization_clamps_and_lowercases() -> None:
    opts = PrintJobOptions(
        scale_mode="custom",
        scale_percent=15,
        page_subset="ODD",
        reverse_order=1,
        paper_size="A4",
        orientation="LANDSCAPE",
        override_fields={"Orientation", "duplex", "unknown"},
    ).normalized()
    assert opts.scale_mode == "custom"
    assert opts.scale_percent == 25  # clamped from 15
    assert opts.page_subset == "odd"
    assert opts.reverse_order is True
    assert opts.paper_size == "a4"
    assert opts.orientation == "landscape"
    assert opts.override_fields == {"orientation", "duplex"}  # "unknown" stripped
