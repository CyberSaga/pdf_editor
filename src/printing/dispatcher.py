"""Print dispatcher and factory entrypoints."""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import Any

from .base_driver import PrinterDevice, PrinterDriver, PrintJobOptions, PrintJobResult
from .errors import PrinterUnavailableError, PrintJobSubmissionError
from .page_selection import resolve_page_indices
from .pdf_renderer import PDFRenderer, PdfSource
from .platforms.linux_driver import LinuxPrinterDriver
from .platforms.mac_driver import MacPrinterDriver
from .platforms.win_driver import WindowsPrinterDriver

logger = logging.getLogger(__name__)


def get_printer_driver() -> PrinterDriver:
    """Factory for platform-specific print driver."""
    system = platform.system().lower()
    if system == "windows":
        return WindowsPrinterDriver()
    if system == "darwin":
        return MacPrinterDriver()
    return LinuxPrinterDriver()


class PrintDispatcher:
    """Facade used by controller/UI for listing and printing."""

    def __init__(
        self,
        driver: PrinterDriver | None = None,
        renderer: PDFRenderer | None = None,
    ):
        self.driver = driver or get_printer_driver()
        self.renderer = renderer or PDFRenderer()

    def list_printers(self) -> list[PrinterDevice]:
        return self.driver.list_printers()

    def get_default_printer(self) -> str | None:
        return self.driver.get_default_printer()

    def get_printer_status(self, printer_name: str) -> str:
        return self.driver.get_printer_status(printer_name)

    def supports_printer_properties_dialog(self) -> bool:
        return bool(self.driver.supports_printer_properties_dialog)

    def open_printer_properties(self, printer_name: str) -> dict[str, Any] | None:
        normalized_name = (printer_name or "").strip()
        if not normalized_name:
            raise PrinterUnavailableError("No printer selected.")
        return self.driver.open_printer_properties(normalized_name)

    def get_printer_preferences(self, printer_name: str) -> dict[str, Any]:
        normalized_name = (printer_name or "").strip()
        if not normalized_name:
            raise PrinterUnavailableError("No printer selected.")
        return self.driver.get_printer_preferences(normalized_name)

    def resolve_page_indices_for_count(self, total_pages: int, options: PrintJobOptions) -> list[int]:
        normalized = options.normalized()
        try:
            page_indices = resolve_page_indices(
                total_pages=total_pages,
                page_ranges=normalized.page_ranges,
                page_subset=normalized.page_subset,
                reverse_order=normalized.reverse_order,
            )
        except ValueError as exc:
            raise PrintJobSubmissionError(
                f"Invalid page range format: {normalized.page_ranges!r}"
            ) from exc
        if not page_indices:
            raise PrintJobSubmissionError("Page range resolved to empty set.")
        return page_indices

    def resolve_page_indices_for_file(self, pdf_path: str, options: PrintJobOptions) -> list[int]:
        page_count = self.renderer.get_page_count(pdf_path)
        return self.resolve_page_indices_for_count(page_count, options)

    def _preflight(
        self, pdf_source: PdfSource, options: PrintJobOptions
    ) -> tuple[PrintJobOptions, list[int]]:
        """Shared validation for both submission entry points.

        Resolves the page selection against the real page count, ensures a virtual
        printer's output directory exists, and rejects an offline/stopped printer
        before anything is handed to the driver.
        """
        normalized = options.normalized()
        page_count = self.renderer.get_page_count(pdf_source)
        page_indices = self.resolve_page_indices_for_count(page_count, normalized)

        if normalized.output_pdf_path:
            target_parent = Path(normalized.output_pdf_path).expanduser().resolve().parent
            if not target_parent.exists():
                target_parent.mkdir(parents=True, exist_ok=True)

        if normalized.printer_name and normalized.output_pdf_path is None:
            status = self.driver.get_printer_status(normalized.printer_name)
            if status in {"offline", "stopped"}:
                raise PrinterUnavailableError(
                    f"Printer '{normalized.printer_name}' status is '{status}'."
                )

        return normalized, page_indices

    def print_pdf_file(self, pdf_path: str, options: PrintJobOptions) -> PrintJobResult:
        normalized, page_indices = self._preflight(pdf_path, options)
        return self.driver.print_pdf(pdf_path, page_indices, normalized)

    def print_pdf_bytes(self, pdf_bytes: bytes, options: PrintJobOptions) -> PrintJobResult:
        """R5-01: hand the bytes straight to the driver — no temp file, ever.

        This used to write a plaintext ``NamedTemporaryFile`` and call
        ``print_pdf_file``. ``capture_print_snapshot_bytes`` always returns
        ``PDF_ENCRYPT_NONE`` bytes, so that temp was a fully decrypted copy of the
        document at rest for the duration of the driver call — recoverable afterwards
        from the filesystem journal. Drivers that genuinely need a path get one from
        ``PrinterDriver.print_pdf_from_bytes``'s default, scoped to their own call.
        """
        normalized, page_indices = self._preflight(pdf_bytes, options)
        return self.driver.print_pdf_from_bytes(pdf_bytes, page_indices, normalized)
