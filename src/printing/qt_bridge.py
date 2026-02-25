"""Qt print bridge: send rendered pages into OS spooler via QPrinter."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPageLayout, QPageSize

from .base_driver import PrintJobOptions, PrintJobResult
from .errors import PrintJobSubmissionError
from .layout import (
    compute_target_draw_rect,
    resolve_orientation,
    resolve_paper_size_points,
)
from .pdf_renderer import PDFRenderer, RenderedPage

_APP_INSTANCE = None


def _ensure_qapplication() -> None:
    global _APP_INSTANCE
    app = QApplication.instance()
    if app is None:
        _APP_INSTANCE = QApplication([])
    else:
        _APP_INSTANCE = app


def _to_duplex_mode(duplex: str) -> QPrinter.DuplexMode:
    if duplex == "long":
        return QPrinter.DuplexLongSide
    if duplex == "short":
        return QPrinter.DuplexShortSide
    return QPrinter.DuplexNone


def _to_q_orientation(orientation: str) -> QPageLayout.Orientation:
    return QPageLayout.Landscape if orientation == "landscape" else QPageLayout.Portrait


def _to_q_page_size(
    paper_size: str,
    source_rect: QRectF,
) -> QPageSize:
    paper = (paper_size or "auto").lower()
    if paper == "a4":
        return QPageSize(QPageSize.A4)
    if paper == "letter":
        return QPageSize(QPageSize.Letter)
    if paper == "legal":
        return QPageSize(QPageSize.Legal)

    width_pt, height_pt = resolve_paper_size_points(
        paper_size,
        source_rect.width(),
        source_rect.height(),
    )
    return QPageSize(QSizeF(width_pt, height_pt), QPageSize.Point, "pdf-source-page")


def _set_page_layout(
    printer: QPrinter,
    page_rect: QRectF,
    options: PrintJobOptions,
) -> None:
    resolved_orientation = resolve_orientation(
        options.orientation,
        page_rect.width(),
        page_rect.height(),
    )
    page_size = _to_q_page_size(options.paper_size, page_rect)
    layout = printer.pageLayout()
    layout.setOrientation(_to_q_orientation(resolved_orientation))
    layout.setPageSize(page_size)
    printer.setPageLayout(layout)


def _fitz_rect_to_qrectf(page_rect) -> QRectF:
    return QRectF(0.0, 0.0, page_rect.width, page_rect.height)


def _apply_printer_options(printer: QPrinter, options: PrintJobOptions) -> None:
    normalized = options.normalized()
    printer.setDocName(normalized.job_name)
    printer.setResolution(normalized.dpi)
    printer.setCopyCount(normalized.copies)
    printer.setCollateCopies(normalized.collate)
    printer.setDuplex(_to_duplex_mode(normalized.duplex))
    if normalized.color_mode == "grayscale":
        printer.setColorMode(QPrinter.GrayScale)
    else:
        printer.setColorMode(QPrinter.Color)


def _draw_page_image(
    painter: QPainter,
    printer: QPrinter,
    rendered: RenderedPage,
    options: PrintJobOptions,
) -> None:
    target_rect = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
    image = rendered.image
    x, y, width, height = compute_target_draw_rect(
        target_width=target_rect.width(),
        target_height=target_rect.height(),
        source_width=image.width(),
        source_height=image.height(),
        scale_mode=options.scale_mode,
        scale_percent=options.scale_percent,
        fit_to_page=options.fit_to_page,
    )
    draw_rect = QRectF(target_rect.x() + x, target_rect.y() + y, width, height)
    painter.drawImage(draw_rect, image)


def raster_print_pdf(
    pdf_path: str,
    page_indices: List[int],
    options: PrintJobOptions,
    renderer: PDFRenderer | None = None,
) -> PrintJobResult:
    """Render PDF pages and draw them to QPrinter (OS spooler)."""
    if not page_indices:
        raise PrintJobSubmissionError("No pages selected for printing.")

    normalized = options.normalized()
    _ensure_qapplication()

    printer = QPrinter(QPrinter.HighResolution)
    if normalized.output_pdf_path:
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(normalized.output_pdf_path)
    elif normalized.printer_name:
        printer.setPrinterName(normalized.printer_name)

    _apply_printer_options(printer, normalized)
    renderer = renderer or PDFRenderer()
    pages_iter = renderer.iter_page_images(pdf_path, page_indices, normalized.dpi)

    try:
        first = next(pages_iter)
    except StopIteration as exc:
        raise PrintJobSubmissionError("No rendered pages available.") from exc

    _set_page_layout(printer, _fitz_rect_to_qrectf(first.page_rect), normalized)

    painter = QPainter()
    if not painter.begin(printer):
        raise PrintJobSubmissionError(
            f"Cannot start printer context: {normalized.printer_name or 'PDF output'}"
        )

    try:
        _draw_page_image(painter, printer, first, normalized)
        for rendered in pages_iter:
            _set_page_layout(
                printer,
                _fitz_rect_to_qrectf(rendered.page_rect),
                normalized,
            )
            printer.newPage()
            _draw_page_image(painter, printer, rendered, normalized)
    except Exception as exc:
        raise PrintJobSubmissionError(f"Raster print failed: {exc}") from exc
    finally:
        painter.end()

    route = "qt-raster->pdf" if normalized.output_pdf_path else "qt-raster->spooler"
    msg = (
        f"Printed {len(page_indices)} page(s) to {normalized.output_pdf_path}"
        if normalized.output_pdf_path
        else f"Submitted {len(page_indices)} page(s) to printer."
    )
    return PrintJobResult(success=True, route=route, message=msg)
