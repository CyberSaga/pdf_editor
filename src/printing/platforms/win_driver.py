"""Windows print driver implementation."""

from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import zlib
from ctypes import wintypes
from typing import Any

from PySide6.QtPrintSupport import QPrinterInfo

from ..base_driver import PrinterDevice, PrinterDriver, PrintJobOptions, PrintJobResult
from ..errors import PrinterUnavailableError, PrintJobSubmissionError
from ..qt_bridge import raster_print_pdf

try:
    import win32print  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    win32print = None


_WIN32_STATUS_MAP: dict[int, str] = {
    0x00000080: "offline",
    0x00000020: "out_of_paper",
    0x00000040: "paper_jam",
    0x00000004: "deleting",
    0x00000002: "error",
    0x00000001: "paused",
    0x00001000: "toner_low",
}

_DMPAPER_TO_APP: dict[int, str] = {
    9: "a4",
    1: "letter",
    5: "legal",
}

_DUPLEX_TO_APP: dict[int, str] = {
    1: "none",
    2: "long",
    3: "short",
}

_DMBIN_LABELS: dict[int, str] = {
    1: "Auto",
    2: "Tray 2",
    3: "Tray 3",
    4: "Manual Feed",
    5: "Envelope",
    6: "Manual Envelope",
    7: "Tray 7",
    8: "Tray 8",
    9: "Tray 9",
    10: "Tray 10",
    11: "Tray 11",
    14: "Cassette",
    15: "Form Source",
}

_DM_OUT_BUFFER = 0x0002
_DM_IN_PROMPT = 0x0004
_DM_IN_BUFFER = 0x0008

_CCHDEVICENAME = 32
_CCHFORMNAME = 32

logger = logging.getLogger(__name__)


class _POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DEVMODE_STRUCT1(ctypes.Structure):
    _fields_ = [
        ("dmOrientation", wintypes.SHORT),
        ("dmPaperSize", wintypes.SHORT),
        ("dmPaperLength", wintypes.SHORT),
        ("dmPaperWidth", wintypes.SHORT),
        ("dmScale", wintypes.SHORT),
        ("dmCopies", wintypes.SHORT),
        ("dmDefaultSource", wintypes.SHORT),
        ("dmPrintQuality", wintypes.SHORT),
    ]


class _DEVMODE_UNION1(ctypes.Union):
    _fields_ = [("s", _DEVMODE_STRUCT1), ("dmPosition", _POINTL)]


class _DEVMODE_UNION2(ctypes.Union):
    _fields_ = [("dmDisplayFlags", wintypes.DWORD), ("dmNup", wintypes.DWORD)]


class _PUBLIC_DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * _CCHDEVICENAME),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("u1", _DEVMODE_UNION1),
        ("dmColor", wintypes.SHORT),
        ("dmDuplex", wintypes.SHORT),
        ("dmYResolution", wintypes.SHORT),
        ("dmTTOption", wintypes.SHORT),
        ("dmCollate", wintypes.SHORT),
        ("dmFormName", wintypes.WCHAR * _CCHFORMNAME),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("u2", _DEVMODE_UNION2),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class _PRINTER_INFO_9(ctypes.Structure):
    _fields_ = [("pDevMode", wintypes.LPVOID)]


try:
    _WINSPOOL = ctypes.WinDLL("winspool.drv", use_last_error=True)
    _DOCUMENT_PROPERTIES_W = _WINSPOOL.DocumentPropertiesW
    _DOCUMENT_PROPERTIES_W.argtypes = [
        wintypes.HWND,
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _DOCUMENT_PROPERTIES_W.restype = wintypes.LONG
    _SET_PRINTER_W = _WINSPOOL.SetPrinterW
    _SET_PRINTER_W.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _SET_PRINTER_W.restype = wintypes.BOOL
except Exception:  # pragma: no cover - Windows-only bootstrap
    _DOCUMENT_PROPERTIES_W = None
    _SET_PRINTER_W = None


def _decode_capability_text(value: Any) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "mbcs", "cp950", "latin-1"):
            try:
                return value.decode(encoding).replace("\x00", "").strip()
            except Exception:
                continue
        return ""
    return str(value).replace("\x00", "").strip()


def _map_devmode_values_to_preferences(
    *,
    paper_code: int,
    orientation: int,
    duplex: int,
    paper_tray: int,
    color_mode: int,
    print_quality: int,
    copies: int,
) -> dict[str, Any]:
    prefs: dict[str, Any] = {}
    if paper_code in _DMPAPER_TO_APP:
        prefs["paper_size"] = _DMPAPER_TO_APP[paper_code]
    if orientation == 1:
        prefs["orientation"] = "portrait"
    elif orientation == 2:
        prefs["orientation"] = "landscape"
    if duplex in _DUPLEX_TO_APP:
        prefs["duplex"] = _DUPLEX_TO_APP[duplex]
    if paper_tray > 0:
        prefs["paper_tray"] = str(paper_tray)
    if color_mode == 1:
        prefs["color_mode"] = "grayscale"
    elif color_mode == 2:
        prefs["color_mode"] = "color"
    if print_quality > 0:
        prefs["dpi"] = print_quality
    if copies > 0:
        prefs["copies"] = copies
    return prefs


def _buffer_to_public_devmode(buffer: ctypes.Array[ctypes.c_char]) -> _PUBLIC_DEVMODEW:
    return _PUBLIC_DEVMODEW.from_buffer_copy(buffer)


def _buffer_to_preferences(buffer: ctypes.Array[ctypes.c_char]) -> dict[str, Any]:
    devmode = _buffer_to_public_devmode(buffer)
    return _map_devmode_values_to_preferences(
        paper_code=int(devmode.u1.s.dmPaperSize),
        orientation=int(devmode.u1.s.dmOrientation),
        duplex=int(devmode.dmDuplex),
        paper_tray=int(devmode.u1.s.dmDefaultSource),
        color_mode=int(devmode.dmColor),
        print_quality=int(devmode.u1.s.dmPrintQuality),
        copies=int(devmode.u1.s.dmCopies),
    )


def _buffer_private_crc32(buffer: ctypes.Array[ctypes.c_char]) -> str:
    raw = ctypes.string_at(ctypes.addressof(buffer), len(buffer))
    devmode = _buffer_to_public_devmode(buffer)
    public_len = max(0, min(len(raw), int(devmode.dmSize)))
    private_len = max(0, min(len(raw) - public_len, int(devmode.dmDriverExtra)))
    private_bytes = raw[public_len:public_len + private_len]
    return f"{zlib.crc32(private_bytes) & 0xFFFFFFFF:08x}"


class WindowsPrinterDriver(PrinterDriver):
    """Windows bridge; rendering path uses Qt->Win32 spooler."""

    @property
    def name(self) -> str:
        return "windows_qt_gdi"

    @property
    def supports_printer_properties_dialog(self) -> bool:
        return win32print is not None or shutil.which("rundll32.exe") is not None

    def list_printers(self) -> list[PrinterDevice]:
        default_name = self.get_default_printer()
        devices: list[PrinterDevice] = []

        if win32print is not None:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
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

        for printer_name in QPrinterInfo.availablePrinterNames():
            devices.append(
                PrinterDevice(
                    name=printer_name,
                    is_default=(printer_name == default_name),
                    status="unknown",
                )
            )
        return devices

    def get_default_printer(self) -> str | None:
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
        page_indices: list[int],
        options: PrintJobOptions,
    ) -> PrintJobResult:
        return raster_print_pdf(pdf_path, page_indices, options)

    def _devmode_to_preferences(self, devmode: Any) -> dict[str, Any]:
        if devmode is None:
            return {}
        return _map_devmode_values_to_preferences(
            paper_code=int(getattr(devmode, "PaperSize", 0) or 0),
            orientation=int(getattr(devmode, "Orientation", 0) or 0),
            duplex=int(getattr(devmode, "Duplex", 0) or 0),
            paper_tray=int(getattr(devmode, "DefaultSource", 0) or 0),
            color_mode=int(getattr(devmode, "Color", 0) or 0),
            print_quality=int(getattr(devmode, "PrintQuality", 0) or 0),
            copies=int(getattr(devmode, "Copies", 0) or 0),
        )

    def _list_paper_trays(self, printer_name: str, port_name: str) -> list[dict[str, str]]:
        if win32print is None:
            return []
        ports_to_try: list[str | None] = []
        if port_name:
            ports_to_try.append(port_name)
        ports_to_try.extend(["", None])

        best_options: list[dict[str, str]] = []
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
            if not bins or isinstance(bins, int):
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
            local_options: list[dict[str, str]] = []
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
                    label = _DMBIN_LABELS.get(code_int, f"Tray {code_str}")
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

    def _safe_get_printer_info(self, handle: Any, level: int) -> dict[str, Any]:
        if win32print is None:
            return {}
        try:
            info = win32print.GetPrinter(handle, level)
        except Exception:
            return {}
        return info if isinstance(info, dict) else {}

    def _collect_printer_preferences(self, handle: Any, printer_name: str) -> dict[str, Any]:
        info2 = self._safe_get_printer_info(handle, 2)
        info8 = self._safe_get_printer_info(handle, 8)
        info9 = self._safe_get_printer_info(handle, 9)

        prefs: dict[str, Any] = {}
        for info in (info2, info8, info9):
            prefs.update(self._devmode_to_preferences(info.get("pDevMode")))

        port_name = str(info2.get("pPortName", "") or "")
        tray_options = self._list_paper_trays(printer_name, port_name)
        if tray_options:
            prefs["paper_tray_options"] = tray_options
        return prefs

    def _can_use_ctypes_document_properties(self, handle: Any) -> bool:
        return _DOCUMENT_PROPERTIES_W is not None and type(handle).__name__.startswith("Py")

    def _persist_devmode_buffer_user_defaults(
        self,
        handle: Any,
        devmode_buffer: ctypes.Array[ctypes.c_char],
        printer_name: str,
    ) -> None:
        if _SET_PRINTER_W is None:
            return
        info9 = _PRINTER_INFO_9(
            pDevMode=ctypes.cast(devmode_buffer, wintypes.LPVOID),
        )
        ok = bool(_SET_PRINTER_W(int(handle), 9, ctypes.byref(info9), 0))
        if ok:
            return
        err = ctypes.get_last_error()
        logger.info(
            "SetPrinterW(level=9) skipped/denied for '%s' after properties dialog (non-fatal): %s",
            printer_name,
            err,
        )

    def _open_printer_properties_via_ctypes(
        self,
        handle: Any,
        printer_name: str,
    ) -> dict[str, Any] | None:
        if _DOCUMENT_PROPERTIES_W is None:
            raise PrintJobSubmissionError("DocumentPropertiesW is unavailable.")

        buffer_size = int(_DOCUMENT_PROPERTIES_W(0, int(handle), printer_name, None, None, 0))
        if buffer_size <= 0:
            raise PrintJobSubmissionError(
                f"DocumentPropertiesW returned invalid buffer size: {buffer_size}"
            )

        devmode_buffer = ctypes.create_string_buffer(buffer_size)
        init_result = int(
            _DOCUMENT_PROPERTIES_W(
                0,
                int(handle),
                printer_name,
                devmode_buffer,
                None,
                _DM_OUT_BUFFER,
            )
        )
        if init_result < 0:
            raise PrintJobSubmissionError(
                f"DocumentPropertiesW failed to initialize DEVMODE buffer: {init_result}"
            )

        before_buffer = ctypes.create_string_buffer(
            ctypes.string_at(ctypes.addressof(devmode_buffer), len(devmode_buffer)),
            len(devmode_buffer),
        )
        before_public_prefs = _buffer_to_preferences(before_buffer)
        before_private_crc = _buffer_private_crc32(before_buffer)

        result = int(
            _DOCUMENT_PROPERTIES_W(
                0,
                int(handle),
                printer_name,
                devmode_buffer,
                devmode_buffer,
                _DM_IN_BUFFER | _DM_OUT_BUFFER | _DM_IN_PROMPT,
            )
        )
        if result < 0:
            raise PrintJobSubmissionError(
                f"Printer properties dialog returned error code: {result}"
            )
        if result != 1:
            return None

        self._persist_devmode_buffer_user_defaults(handle, devmode_buffer, printer_name)

        after_public_prefs = _buffer_to_preferences(devmode_buffer)
        after_private_crc = _buffer_private_crc32(devmode_buffer)
        returned_prefs = dict(after_public_prefs)
        if after_private_crc != before_private_crc and after_public_prefs == before_public_prefs:
            returned_prefs["opaque_fields"] = ["color_mode", "paper_tray"]
        return returned_prefs

    def get_printer_preferences(self, printer_name: str) -> dict[str, Any]:
        if win32print is None:
            return {}
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            return self._collect_printer_preferences(handle, printer_name)
        except Exception:
            return {}
        finally:
            if handle is not None:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    pass

    def open_printer_properties(self, printer_name: str) -> dict[str, Any] | None:
        normalized_name = (printer_name or "").strip()
        if not normalized_name:
            raise PrinterUnavailableError("No printer selected.")
        if not self.supports_printer_properties_dialog:
            raise PrintJobSubmissionError("Native printer properties dialog is unavailable on this system.")

        if win32print is not None:
            handle = None
            try:
                handle = win32print.OpenPrinter(normalized_name)

                if self._can_use_ctypes_document_properties(handle):
                    try:
                        dialog_prefs = self._open_printer_properties_via_ctypes(handle, normalized_name)
                    except Exception as exc_ctypes:
                        logger.info(
                            "ctypes DocumentPropertiesW path failed for '%s'; falling back to pywin32 path: %s",
                            normalized_name,
                            exc_ctypes,
                        )
                    else:
                        if dialog_prefs is None:
                            return None
                        merged = self._collect_printer_preferences(handle, normalized_name)
                        merged.update(dialog_prefs)
                        return merged

                info = self._safe_get_printer_info(handle, 2)
                devmode = info.get("pDevMode")
                flags = (
                    int(getattr(win32print, "DM_IN_PROMPT", _DM_IN_PROMPT))
                    | int(getattr(win32print, "DM_IN_BUFFER", _DM_IN_BUFFER))
                    | int(getattr(win32print, "DM_OUT_BUFFER", _DM_OUT_BUFFER))
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
                if int(result) != 1:
                    return None
                try:
                    win32print.SetPrinter(handle, 9, {"pDevMode": devmode}, 0)
                except Exception as exc_set:
                    logger.info(
                        "SetPrinter(level=9) skipped/denied for '%s' after properties dialog (non-fatal): %s",
                        normalized_name,
                        exc_set,
                    )
                merged = self._collect_printer_preferences(handle, normalized_name)
                for key, value in self._devmode_to_preferences(devmode).items():
                    merged.setdefault(key, value)
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
