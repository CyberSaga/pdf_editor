"""Qt print bridge: send rendered pages into OS spooler via QPrinter."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPageLayout, QPageSize

from .base_driver import PrintJobOptions, PrintJobResult
from .errors import PrintJobSubmissionError
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


def _set_page_layout_from_pdf_rect(printer: QPrinter, page_rect: QRectF) -> None:
    width_pt = max(1.0, page_rect.width())
    height_pt = max(1.0, page_rect.height())
    page_size = QPageSize(QSizeF(width_pt, height_pt), QPageSize.Point, "pdf-source-page")
    orientation = (
        QPageLayout.Landscape if width_pt > height_pt else QPageLayout.Portrait
    )
    layout = printer.pageLayout()
    layout.setOrientation(orientation)
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
    fit_to_page: bool,
) -> None:
    target_rect = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
    image = rendered.image

    if fit_to_page:
        scaled = image.scaled(
            target_rect.size().toSize(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        x = target_rect.x() + (target_rect.width() - scaled.width()) / 2.0
        y = target_rect.y() + (target_rect.height() - scaled.height()) / 2.0
        painter.drawImage(QPointF(x, y), scaled)
    else:
        painter.drawImage(QPointF(target_rect.x(), target_rect.y()), image)


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

    _set_page_layout_from_pdf_rect(printer, _fitz_rect_to_qrectf(first.page_rect))

    painter = QPainter()
    if not painter.begin(printer):
        raise PrintJobSubmissionError(
            f"Cannot start printer context: {normalized.printer_name or 'PDF output'}"
        )

    try:
        _draw_page_image(painter, printer, first, normalized.fit_to_page)
        for rendered in pages_iter:
            _set_page_layout_from_pdf_rect(
                printer,
                _fitz_rect_to_qrectf(rendered.page_rect),
            )
            printer.newPage()
            _draw_page_image(painter, printer, rendered, normalized.fit_to_page)
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
