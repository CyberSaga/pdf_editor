"""Qt print bridge: send rendered pages into OS spooler via QPrinter."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

from .base_driver import PrintJobOptions, PrintJobResult
from .errors import PrintJobSubmissionError
from .layout import (
    compute_target_draw_rect,
    match_standard_paper_size,
    resolve_orientation,
    resolve_paper_size_points,
)
from .pdf_renderer import PDFRenderer, RenderedPage

_APP_INSTANCE = None

# Standard paper-size keys → driver-recognised named QPageSize constants. Named
# sizes survive the trip through Windows/macOS/CUPS drivers; a custom QSizeF does
# not (drivers snap it to their default tray size), so we prefer named here.
_NAMED_Q_PAGE_SIZES = {
    "a0": QPageSize.A0,
    "a1": QPageSize.A1,
    "a2": QPageSize.A2,
    "a3": QPageSize.A3,
    "a4": QPageSize.A4,
    "a5": QPageSize.A5,
    "a6": QPageSize.A6,
    "b4": QPageSize.B4,
    "b5": QPageSize.B5,
    "letter": QPageSize.Letter,
    "legal": QPageSize.Legal,
    "tabloid": QPageSize.Tabloid,
    "executive": QPageSize.Executive,
}


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


def _to_paper_source(source: str) -> QPrinter.PaperSource:
    value = (source or "").strip().lower()
    if value in ("", "auto"):
        return QPrinter.PaperSource.Auto
    if value == "manual":
        return QPrinter.PaperSource.Manual
    if value == "lower":
        return QPrinter.PaperSource.Lower
    if value == "middle":
        return QPrinter.PaperSource.Middle
    if value == "upper":
        return QPrinter.PaperSource.Upper
    if value == "envelope":
        return QPrinter.PaperSource.Envelope
    if value == "cassette":
        return QPrinter.PaperSource.Cassette
    if value == "tractor":
        return QPrinter.PaperSource.Tractor
    if value == "smallformat":
        return QPrinter.PaperSource.SmallFormat
    if value == "largeformat":
        return QPrinter.PaperSource.LargeFormat
    if value == "largecapacity":
        return QPrinter.PaperSource.LargeCapacity

    # Windows DMBIN_* tray codes.
    try:
        code = int(value)
    except ValueError:
        code = -1
    mapping = {
        1: QPrinter.PaperSource.Upper,
        2: QPrinter.PaperSource.Lower,
        3: QPrinter.PaperSource.Middle,
        4: QPrinter.PaperSource.Manual,
        5: QPrinter.PaperSource.Envelope,
        14: QPrinter.PaperSource.Cassette,
        15: QPrinter.PaperSource.FormSource,
    }
    return mapping.get(code, QPrinter.PaperSource.CustomSource)


def _to_q_orientation(orientation: str) -> QPageLayout.Orientation:
    return QPageLayout.Landscape if orientation == "landscape" else QPageLayout.Portrait


def _to_q_page_size(
    paper_size: str,
    source_rect: QRectF,
) -> QPageSize:
    paper = (paper_size or "auto").strip().lower()

    # Explicit paper choice always wins over the source page dimensions.
    if paper != "auto" and paper in _NAMED_Q_PAGE_SIZES:
        return QPageSize(_NAMED_Q_PAGE_SIZES[paper])

    # Auto: if the source matches a standard size, use the driver-recognised
    # named constant so the print spooler doesn't snap it to its default tray.
    if paper == "auto":
        matched = match_standard_paper_size(source_rect.width(), source_rect.height())
        if matched is not None and matched in _NAMED_Q_PAGE_SIZES:
            return QPageSize(_NAMED_Q_PAGE_SIZES[matched])

    width_pt, height_pt = resolve_paper_size_points(
        paper_size,
        source_rect.width(),
        source_rect.height(),
    )
    # Qt expects the custom base size in portrait order and applies the
    # requested orientation separately; passing already-landscape dimensions
    # here causes custom PDF output pages to flip back to portrait.
    if width_pt > height_pt:
        width_pt, height_pt = height_pt, width_pt
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
    # Contract: callers pass already-normalized options (raster_print_pdf normalizes
    # at the public boundary), so this internal helper does not re-normalize.
    printer.setDocName(options.job_name)
    printer.setResolution(options.dpi)
    printer.setCopyCount(options.copies)
    printer.setCollateCopies(options.collate)
    if "duplex" in options.override_fields:
        printer.setDuplex(_to_duplex_mode(options.duplex))
    # Keep tray choice in system/native properties unless explicitly overridden.
    if (options.paper_tray or "").strip().lower() not in ("", "auto"):
        printer.setPaperSource(_to_paper_source(options.paper_tray))
    if "color_mode" in options.override_fields:
        if options.color_mode == "grayscale":
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
    page_indices: list[int],
    options: PrintJobOptions,
    renderer: PDFRenderer | None = None,
) -> PrintJobResult:
    """Render PDF pages and draw them to QPrinter (OS spooler).

    Public boundary: ``options`` may be raw — it is normalized here once and the
    normalized copy is handed to the internal helpers.

    Per-page ``_set_page_layout`` below is honoured by Qt's PDF writer (mixed-media
    PDF export). On the Windows GDI spooler mid-job layout changes are ignored, so
    callers that need cross-media variation pre-split into uniform groups (see
    win_driver._raster_split_or_direct); within a single group these calls just
    re-assert the one shared layout, which is harmless.
    """
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
    if renderer is None:
        from model.color_profile import safe_to_fitz_colorspace

        requested = (normalized.extra_options or {}).get("render_colorspace") if hasattr(normalized, "extra_options") else None
        renderer = PDFRenderer(colorspace=safe_to_fitz_colorspace(requested))
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
            _set_page_layout(printer, _fitz_rect_to_qrectf(rendered.page_rect), normalized)
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
