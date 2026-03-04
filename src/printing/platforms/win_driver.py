"""Windows print driver implementation."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List, Optional

from PySide6.QtPrintSupport import QPrinterInfo

from ..base_driver import PrintJobOptions, PrintJobResult, PrinterDevice, PrinterDriver
from ..errors import PrintJobSubmissionError, PrinterUnavailableError
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

_DMPAPER_TO_APP: Dict[int, str] = {
    9: "a4",
    1: "letter",
    5: "legal",
}

_DUPLEX_TO_APP: Dict[int, str] = {
    1: "none",
    2: "long",
    3: "short",
}


class WindowsPrinterDriver(PrinterDriver):
    """Windows bridge; rendering path uses Qt->Win32 spooler."""

    @property
    def name(self) -> str:
        return "windows_qt_gdi"

    @property
    def supports_printer_properties_dialog(self) -> bool:
        return win32print is not None or shutil.which("rundll32.exe") is not None

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

    def _devmode_to_preferences(self, devmode: Any) -> Dict[str, Any]:
        if devmode is None:
            return {}
        prefs: Dict[str, Any] = {}

        paper_code = int(getattr(devmode, "PaperSize", 0) or 0)
        if paper_code in _DMPAPER_TO_APP:
            prefs["paper_size"] = _DMPAPER_TO_APP[paper_code]

        orientation = int(getattr(devmode, "Orientation", 0) or 0)
        if orientation == 1:
            prefs["orientation"] = "portrait"
        elif orientation == 2:
            prefs["orientation"] = "landscape"

        duplex = int(getattr(devmode, "Duplex", 0) or 0)
        if duplex in _DUPLEX_TO_APP:
            prefs["duplex"] = _DUPLEX_TO_APP[duplex]

        color_mode = int(getattr(devmode, "Color", 0) or 0)
        if color_mode == 1:
            prefs["color_mode"] = "grayscale"
        elif color_mode == 2:
            prefs["color_mode"] = "color"

        print_quality = int(getattr(devmode, "PrintQuality", 0) or 0)
        if print_quality > 0:
            prefs["dpi"] = print_quality

        copies = int(getattr(devmode, "Copies", 0) or 0)
        if copies > 0:
            prefs["copies"] = copies

        return prefs

    def get_printer_preferences(self, printer_name: str) -> Dict[str, Any]:
        if win32print is None:
            return {}
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(handle, 2)
            return self._devmode_to_preferences(info.get("pDevMode"))
        except Exception:
            return {}
        finally:
            if handle is not None:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    pass

    def open_printer_properties(self, printer_name: str) -> Optional[Dict[str, Any]]:
        normalized_name = (printer_name or "").strip()
        if not normalized_name:
            raise PrinterUnavailableError("No printer selected.")
        if not self.supports_printer_properties_dialog:
            raise PrintJobSubmissionError("Native printer properties dialog is unavailable on this system.")

        if win32print is not None:
            handle = None
            try:
                handle = win32print.OpenPrinter(normalized_name)
                info = win32print.GetPrinter(handle, 2)
                devmode = info.get("pDevMode")
                flags = (
                    int(getattr(win32print, "DM_IN_PROMPT", 0x0004))
                    | int(getattr(win32print, "DM_OUT_BUFFER", 0x0002))
                )
                result = win32print.DocumentProperties(
                    0,
                    handle,
                    normalized_name,
                    devmode,
                    devmode,
                    flags,
                )
                if int(result) < 0:
                    raise PrintJobSubmissionError(
                        f"Printer properties dialog returned error code: {result}"
                    )
                return self._devmode_to_preferences(devmode)
            except PrintJobSubmissionError:
                raise
            except Exception as exc:
                raise PrintJobSubmissionError(
                    f"Failed to open printer properties for '{normalized_name}': {exc}"
                ) from exc
            finally:
                if handle is not None:
                    try:
                        win32print.ClosePrinter(handle)
                    except Exception:
                        pass

        try:
            subprocess.Popen(
                ["rundll32.exe", "printui.dll,PrintUIEntry", "/e", "/n", normalized_name],
            )
            return self.get_printer_preferences(normalized_name)
        except Exception as exc:
            raise PrintJobSubmissionError(
                f"Failed to open printer properties for '{normalized_name}': {exc}"
            ) from exc

