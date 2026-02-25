"""Windows print driver implementation."""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtPrintSupport import QPrinterInfo

from ..base_driver import PrintJobOptions, PrintJobResult, PrinterDevice, PrinterDriver
from ..qt_bridge import raster_print_pdf

try:
    import win32print  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    win32print = None


_WIN32_STATUS_MAP: Dict[int, str] = {
    0x00000080: "offline",
    0x00000020: "out_of_paper",
    0x00000040: "paper_jam",
    0x00000004: "deleting",
    0x00000002: "error",
    0x00000001: "paused",
    0x00001000: "toner_low",
}


class WindowsPrinterDriver(PrinterDriver):
    """Windows bridge; rendering path uses Qt->Win32 spooler."""

    @property
    def name(self) -> str:
        return "windows_qt_gdi"

    def list_printers(self) -> List[PrinterDevice]:
        default_name = self.get_default_printer()
        devices: List[PrinterDevice] = []

        if win32print is not None:
            flags = (
                win32print.PRINTER_ENUM_LOCAL
                | win32print.PRINTER_ENUM_CONNECTIONS
            )
            for item in win32print.EnumPrinters(flags):
                printer_name = item[2]
                devices.append(
                    PrinterDevice(
                        name=printer_name,
                        is_default=(printer_name == default_name),
                        status=self.get_printer_status(printer_name),
                    )
                )
            return devices

        # Fallback path without pywin32.
        for printer_name in QPrinterInfo.availablePrinterNames():
            devices.append(
                PrinterDevice(
                    name=printer_name,
                    is_default=(printer_name == default_name),
                    status="unknown",
                )
            )
        return devices

    def get_default_printer(self) -> Optional[str]:
        if win32print is not None:
            try:
                return str(win32print.GetDefaultPrinter())
            except Exception:
                return None
        default = QPrinterInfo.defaultPrinter()
        if default.isNull():
            return None
        return default.printerName()

    def get_printer_status(self, printer_name: str) -> str:
        if win32print is None:
            return "unknown"
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(handle, 2)
            status_code = int(info.get("Status", 0))
            if status_code == 0:
                return "ready"
            for bit, text in _WIN32_STATUS_MAP.items():
                if status_code & bit:
                    return text
            return "busy"
        except Exception:
            return "unknown"
        finally:
            if handle is not None:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    pass

    def print_pdf(
        self,
        pdf_path: str,
        page_indices: List[int],
        options: PrintJobOptions,
    ) -> PrintJobResult:
        # Qt print path on Windows still goes through system print spooler.
        return raster_print_pdf(pdf_path, page_indices, options)

