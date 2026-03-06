"""Windows print driver implementation."""

from __future__ import annotations

import shutil
import subprocess
import logging
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

_DMBIN_LABELS: Dict[int, str] = {
    1: "自動選擇",
    2: "紙盤2",
    3: "紙盤3",
    4: "手送紙盤",
    5: "信封紙盤",
    6: "手送信封",
    7: "紙盤7",
    8: "紙盤8",
    9: "紙盤9",
    10: "紙盤10",
    11: "紙盤11",
    14: "卡匣",
    15: "依表單設定",
}

logger = logging.getLogger(__name__)


def _decode_capability_text(value: Any) -> str:
    """Decode tray names returned by DeviceCapabilities across drivers/locales."""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "mbcs", "cp950", "latin-1"):
            try:
                return value.decode(encoding).replace("\x00", "").strip()
            except Exception:
                continue
        return ""
    return str(value).replace("\x00", "").strip()


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

        paper_tray = int(getattr(devmode, "DefaultSource", 0) or 0)
        if paper_tray > 0:
            prefs["paper_tray"] = str(paper_tray)

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

    def _list_paper_trays(self, printer_name: str, port_name: str) -> List[Dict[str, str]]:
        if win32print is None:
            return []
        ports_to_try: List[Optional[str]] = []
        if port_name:
            ports_to_try.append(port_name)
        ports_to_try.extend(["", None])
        # Driver behavior differs by queue/port. Evaluate all candidates and
        # keep the richest list instead of stopping at the first non-empty one.
        best_options: List[Dict[str, str]] = []
        best_named_count = -1
        best_total_count = -1
        for port in ports_to_try:
            try:
                bins = win32print.DeviceCapabilities(
                    printer_name,
                    port,
                    win32print.DC_BINS,
                )
            except Exception:
                continue
            if not bins:
                continue
            if isinstance(bins, int):
                # Some drivers return count-only for unsupported call patterns.
                continue
            try:
                names = win32print.DeviceCapabilities(
                    printer_name,
                    port,
                    win32print.DC_BINNAMES,
                )
            except Exception:
                names = []
            if isinstance(names, int):
                names = []

            local_seen: set[str] = set()
            local_options: List[Dict[str, str]] = []
            named_count = 0
            for idx, code in enumerate(bins):
                code_int = int(code)
                code_str = str(code_int)
                if code_str in local_seen:
                    continue
                local_seen.add(code_str)
                raw_name = names[idx] if idx < len(names) else ""
                label = _decode_capability_text(raw_name)
                if label:
                    named_count += 1
                else:
                    label = _DMBIN_LABELS.get(code_int, f"紙盤{code_str}")
                local_options.append({"code": code_str, "label": label})

            total_count = len(local_options)
            if total_count <= 0:
                continue
            if (
                total_count > best_total_count
                or (total_count == best_total_count and named_count > best_named_count)
            ):
                best_options = local_options
                best_total_count = total_count
                best_named_count = named_count
        return best_options

    def get_printer_preferences(self, printer_name: str) -> Dict[str, Any]:
        if win32print is None:
            return {}
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(handle, 2)
            prefs = self._devmode_to_preferences(info.get("pDevMode"))
            port_name = str(info.get("pPortName", "") or "")
            tray_options = self._list_paper_trays(printer_name, port_name)
            if tray_options:
                prefs["paper_tray_options"] = tray_options
            return prefs
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
                merged = self.get_printer_preferences(normalized_name)
                merged.update(self._devmode_to_preferences(devmode))
                # Persist per-user defaults (PRINTER_INFO_9) so vendor/private
                # settings selected in properties can be reused by subsequent jobs.
                try:
                    win32print.SetPrinter(handle, 9, {"pDevMode": devmode}, 0)
                except Exception as exc_set:
                    logger.info(
                        "SetPrinter(level=9) skipped/denied for '%s' after properties dialog (non-fatal): %s",
                        normalized_name,
                        exc_set,
                    )
                return merged
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

