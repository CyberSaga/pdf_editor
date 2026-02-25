"""Print dispatcher and factory entrypoints."""

from __future__ import annotations

import platform
import tempfile
from pathlib import Path
from typing import List, Optional

from .base_driver import PrintJobOptions, PrintJobResult, PrinterDevice, PrinterDriver
from .errors import PrintJobSubmissionError, PrinterUnavailableError
from .pdf_renderer import PDFRenderer
from .platforms.linux_driver import LinuxPrinterDriver
from .platforms.mac_driver import MacPrinterDriver
from .platforms.win_driver import WindowsPrinterDriver


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
        driver: Optional[PrinterDriver] = None,
        renderer: Optional[PDFRenderer] = None,
    ):
        self.driver = driver or get_printer_driver()
        self.renderer = renderer or PDFRenderer()

    def list_printers(self) -> List[PrinterDevice]:
        return self.driver.list_printers()

    def get_default_printer(self) -> Optional[str]:
        return self.driver.get_default_printer()

    def get_printer_status(self, printer_name: str) -> str:
        return self.driver.get_printer_status(printer_name)

    def _resolve_pages(self, pdf_path: str, page_ranges: str | None) -> List[int]:
        page_count = self.renderer.get_page_count(pdf_path)
        try:
            page_indices = self.renderer.parse_page_ranges(page_ranges, page_count)
        except ValueError as exc:
            raise PrintJobSubmissionError(
                f"Invalid page range format: {page_ranges!r}"
            ) from exc
        if not page_indices:
            raise PrintJobSubmissionError("Page range resolved to empty set.")
        return page_indices

    def print_pdf_file(self, pdf_path: str, options: PrintJobOptions) -> PrintJobResult:
        normalized = options.normalized()
        page_indices = self._resolve_pages(pdf_path, normalized.page_ranges)

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

        return self.driver.print_pdf(pdf_path, page_indices, normalized)

    def print_pdf_bytes(self, pdf_bytes: bytes, options: PrintJobOptions) -> PrintJobResult:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        try:
            return self.print_pdf_file(temp_path, options)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
