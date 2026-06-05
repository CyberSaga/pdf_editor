"""Windows print driver implementation."""

from __future__ import annotations

import base64
import binascii
import ctypes
import dataclasses
import logging
import os
import shutil
import subprocess
import zlib
from ctypes import wintypes
from typing import Any

import fitz
from PySide6.QtPrintSupport import QPrinterInfo

from ..base_driver import PrinterDevice, PrinterDriver, PrintJobOptions, PrintJobResult
from ..errors import PrinterUnavailableError, PrintJobSubmissionError
from ..layout import match_standard_paper_size, resolve_orientation
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

# Launch system tools by absolute path so a planted ``rundll32.exe`` earlier on
# the process search order cannot be executed instead (CWE-426/CWE-427).
_RUNDLL32 = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "rundll32.exe"
)

_CCHDEVICENAME = 32
_CCHFORMNAME = 32

# Windows rasterises every page to a full-resolution bitmap into the GDI/EMF
# spool; at 300 DPI an A4 page is ~26 MB raw, which despools slowly. Cap the
# effective raster DPI for the real spooler path (P4). This ceiling composes with
# the cross-platform floor in PrintJobOptions.normalized() (dpi = max(72, dpi)),
# so the effective Windows spooler range is [72, _WIN_MAX_RASTER_DPI].
_WIN_MAX_RASTER_DPI: int = 150

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


def _decode_devmode_b64(value: str) -> bytes:
    """Decode a base64 DEVMODE string back to raw bytes; return b'' if malformed."""
    try:
        return base64.b64decode(value)
    except (ValueError, binascii.Error):
        return b""


def _devmode_buffer_to_b64(buffer: ctypes.Array[ctypes.c_char]) -> str:
    """Encode a raw DEVMODE ctypes buffer as base64 so it survives JSON serialization."""
    return base64.b64encode(bytes(buffer)).decode("ascii")


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
        # normalized() is idempotent and applied at each public boundary; raster
        # helpers below receive an already-normalized copy and need not redo it.
        normalized = options.normalized()
        devmode_b64 = (normalized.extra_options or {}).get("devmode_buffer")
        if (
            isinstance(devmode_b64, str)
            and devmode_b64
            and normalized.printer_name
            and not normalized.output_pdf_path
            and win32print is not None
        ):
            job_bytes = _decode_devmode_b64(devmode_b64)
            if job_bytes:
                return self._print_with_scoped_devmode(
                    pdf_path, page_indices, normalized, job_bytes
                )
        return self._raster_split_or_direct(pdf_path, page_indices, normalized)

    def _raster_split_or_direct(
        self,
        pdf_path: str,
        page_indices: list[int],
        normalized: PrintJobOptions,
    ) -> PrintJobResult:
        # Virtual-printer PDF output: Qt's PDF writer honours per-page layout and
        # there is no spooler bloat, so keep the original single-pass, full-DPI path.
        if normalized.output_pdf_path:
            return raster_print_pdf(pdf_path, page_indices, normalized)

        # P4: cap effective raster DPI so the GDI/EMF spool stays small.
        if normalized.dpi > _WIN_MAX_RASTER_DPI:
            normalized = dataclasses.replace(normalized, dpi=_WIN_MAX_RASTER_DPI)

        # Division of responsibility (resolves the apparent qt_bridge/win_driver
        # contradiction): qt_bridge.raster_print_pdf sets the page layout per page,
        # which is honoured by Qt's PDF writer and is correct within a *single* media
        # group. The GDI spooler, however, ignores mid-job setPageLayout changes, so
        # cross-media variation is handled *here* by splitting into one spooler job
        # per uniform layout group. A fixed paper + orientation is already uniform and
        # prints as one job; "auto" on either axis means each page may need its own
        # media, so we split (P2/P3).
        if normalized.paper_size != "auto" and normalized.orientation != "auto":
            return raster_print_pdf(pdf_path, page_indices, normalized)
        return self._split_by_layout(pdf_path, page_indices, normalized)

    def _split_by_layout(
        self,
        pdf_path: str,
        page_indices: list[int],
        normalized: PrintJobOptions,
    ) -> PrintJobResult:
        # An explicitly chosen paper size must be honoured for every page; only the
        # "auto" axis is derived per page. resolve_orientation already returns an
        # explicit orientation choice unchanged, so leaving paper fixed here lets the
        # user pin paper while still auto-rotating per page (finding #1).
        explicit_paper = normalized.paper_size if normalized.paper_size != "auto" else None
        # This is a lightweight geometry-only pass (fitz.open parses the xref, it does
        # not render). The per-group renderer re-opens the document for rasterising;
        # the two concerns are kept separate deliberately. Classifying every page up
        # front also means a malformed PDF fails here, before anything is spooled.
        doc = fitz.open(pdf_path)
        try:
            groups: list[tuple[tuple[str, str], list[int]]] = []
            cur_layout: tuple[str, str] | None = None
            cur_pages: list[int] = []
            for idx in page_indices:
                rect = doc[idx].rect
                width, height = float(rect.width), float(rect.height)
                if explicit_paper is not None:
                    paper = explicit_paper
                else:
                    paper = match_standard_paper_size(width, height) or "auto"
                orient = resolve_orientation(normalized.orientation, width, height)
                layout = (paper, orient)
                if layout != cur_layout:
                    if cur_pages and cur_layout is not None:
                        groups.append((cur_layout, cur_pages))
                    cur_layout, cur_pages = layout, [idx]
                else:
                    cur_pages.append(idx)
            if cur_pages and cur_layout is not None:
                groups.append((cur_layout, cur_pages))
        finally:
            doc.close()

        return self._print_layout_groups(pdf_path, groups, normalized)

    def _print_layout_groups(
        self,
        pdf_path: str,
        groups: list[tuple[tuple[str, str], list[int]]],
        normalized: PrintJobOptions,
    ) -> PrintJobResult:
        # Each layout group is necessarily its own spooler job (GDI cannot switch
        # media mid-job), so multi-copy ordering must be coordinated here (finding #2):
        #   * single group   -> one job; the driver collates copies natively.
        #   * collated, N>1   -> loop whole-document copies, 1 copy per group, so the
        #                        output is p0,p1,p0,p1,... (document copy ordering).
        #   * uncollated, N>1 -> one pass, copies=N per group in document order, so the
        #                        output is p0,p0,p1,p1,... (page-grouped copies).
        # A single physically-collated set spanning paper sizes is not possible on GDI.
        copies = max(1, int(normalized.copies))
        collate = bool(normalized.collate)
        if len(groups) <= 1 or copies == 1:
            passes, per_group_copies, group_collate = 1, copies, collate
        elif collate:
            passes, per_group_copies, group_collate = copies, 1, False
        else:
            passes, per_group_copies, group_collate = 1, copies, False

        page_total = sum(len(pages) for _layout, pages in groups)
        # Each group is a separate spooler job, so the overall job is NOT atomic: once
        # a group is spooled it cannot be recalled. If a later group fails we surface
        # how many pages were already spooled rather than implying nothing printed
        # (finding #6). The up-front classification above keeps PDF-parse failures from
        # ever reaching this loop.
        spooled = 0
        for _ in range(passes):
            for (paper, orient), pages in groups:
                group_opts = dataclasses.replace(
                    normalized,
                    paper_size=paper,
                    orientation=orient,
                    copies=per_group_copies,
                    collate=group_collate,
                )
                result = raster_print_pdf(pdf_path, pages, group_opts)
                if not result.success:
                    if spooled > 0:
                        return PrintJobResult(
                            success=False,
                            route="qt-raster->spooler",
                            message=(
                                f"Print failed after {spooled} page(s) had already been "
                                f"spooled as separate per-layout jobs (mixed-media jobs "
                                f"cannot be rolled back): {result.message}"
                            ),
                        )
                    return result
                spooled += len(pages)

        return PrintJobResult(
            success=True,
            route="qt-raster->spooler",
            message=f"Submitted {page_total} page(s) to printer.",
        )

    def _print_with_scoped_devmode(
        self,
        pdf_path: str,
        page_indices: list[int],
        normalized: PrintJobOptions,
        job_bytes: bytes,
    ) -> PrintJobResult:
        """Apply the captured DEVMODE for this job only, then restore the previous one.

        Qt exposes no API to inject a raw DEVMODE into a ``QPrinter``, so the job's
        settings are applied by briefly writing the per-user default (level 9) and
        restoring it afterwards. This keeps printing once from permanently mutating
        the printer's defaults (P1).

        Note (finding #8): the DEVMODE also carries paper size / orientation, but the
        app owns those — the layout split below sets them per page via QPrinter, which
        overrides the DEVMODE's values. The DEVMODE is therefore the carrier for the
        *other* dialog choices (colour, duplex, tray) and any opaque driver-private
        fields; its paper/orientation are intentionally superseded.
        """
        if win32print is None or _DOCUMENT_PROPERTIES_W is None:
            return self._raster_split_or_direct(pdf_path, page_indices, normalized)

        printer_name = normalized.printer_name or ""
        handle = None
        original_buf: ctypes.Array[ctypes.c_char] | None = None
        applied = False
        try:
            handle = win32print.OpenPrinter(printer_name)
            size = int(_DOCUMENT_PROPERTIES_W(0, int(handle), printer_name, None, None, 0))
            if size > 0:
                # Capture the current default first: we only apply the job DEVMODE if
                # we have something to restore, so a successful apply can always be
                # undone (finding #4).
                original_buf = ctypes.create_string_buffer(size)
                _DOCUMENT_PROPERTIES_W(
                    0, int(handle), printer_name, original_buf, None, _DM_OUT_BUFFER
                )
                job_buf = ctypes.create_string_buffer(job_bytes, len(job_bytes))
                # applied is True only on a *confirmed* write: if SetPrinterW is denied
                # the defaults are unchanged, so we must not attempt a restore.
                applied = self._persist_devmode_buffer_user_defaults(
                    handle, job_buf, printer_name
                )
                if not applied:
                    logger.warning(
                        "Job-scoped DEVMODE could not be applied for '%s'; "
                        "printing with the printer's current defaults.",
                        printer_name,
                    )
            else:
                logger.info(
                    "Could not read current DEVMODE for '%s'; printing with current defaults.",
                    printer_name,
                )
        except Exception as exc:
            applied = False
            logger.info(
                "Job-scoped DEVMODE setup failed for '%s'; printing with current defaults: %s",
                printer_name,
                exc,
            )

        try:
            return self._raster_split_or_direct(pdf_path, page_indices, normalized)
        finally:
            if applied and original_buf is not None and handle is not None:
                # Surface a failed restore instead of swallowing it: a silent failure
                # leaves the captured DEVMODE as the persistent per-user default — the
                # very P1 mutation this path exists to prevent (finding #4).
                restored = False
                try:
                    restored = self._persist_devmode_buffer_user_defaults(
                        handle, original_buf, printer_name
                    )
                except Exception as exc:
                    logger.warning(
                        "Error restoring printer default DEVMODE for '%s': %s",
                        printer_name,
                        exc,
                    )
                if not restored:
                    logger.warning(
                        "Printer default DEVMODE for '%s' may remain modified: the "
                        "job-scoped restore did not confirm success.",
                        printer_name,
                    )
            if handle is not None:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    pass

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
    ) -> bool:
        """Write a DEVMODE as the level-9 default; return True only on a confirmed write.

        Used solely inside the job-scoped save/restore block: the caller relies on the
        boolean to decide whether a restore is owed and whether it succeeded (finding #4).
        """
        if _SET_PRINTER_W is None:
            return False
        info9 = _PRINTER_INFO_9(
            pDevMode=ctypes.cast(devmode_buffer, wintypes.LPVOID),
        )
        ok = bool(_SET_PRINTER_W(int(handle), 9, ctypes.byref(info9), 0))
        if ok:
            return True
        err = ctypes.get_last_error()
        logger.info(
            "SetPrinterW(level=9) skipped/denied for '%s' (non-fatal): %s",
            printer_name,
            err,
        )
        return False

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

        after_public_prefs = _buffer_to_preferences(devmode_buffer)
        after_private_crc = _buffer_private_crc32(devmode_buffer)
        returned_prefs = dict(after_public_prefs)
        if after_private_crc != before_private_crc and after_public_prefs == before_public_prefs:
            returned_prefs["opaque_fields"] = ["color_mode", "paper_tray"]
        # Job-scoped (P1): hand the captured DEVMODE back to the caller instead of
        # writing it as the per-user default via SetPrinter(level=9). Base64 keeps it
        # JSON-safe across the helper-subprocess job.json boundary.
        returned_prefs["devmode_buffer"] = _devmode_buffer_to_b64(devmode_buffer)
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
                merged = self._collect_printer_preferences(handle, normalized_name)
                for key, value in self._devmode_to_preferences(devmode).items():
                    merged.setdefault(key, value)
                # Finding #5: on this pywin32-only fallback (reached when the ctypes
                # winspool API is unavailable) the user's choices live in a PyDEVMODE,
                # which has no buffer protocol — there is no reliable way to serialise
                # it to raw bytes, and a fresh ctypes read would only return the
                # unchanged stored default, not the dialog's edits. So we deliberately
                # omit `devmode_buffer` here and carry the *public* fields (paper,
                # orientation, duplex, colour, tray) via `merged`, which the dialog
                # applies through the normal option combos. Only opaque driver-private
                # settings are lost on this rare path; log it so it is not silent.
                logger.info(
                    "Printer properties for '%s' resolved via the pywin32 fallback; "
                    "applying public DEVMODE fields only (opaque settings not job-scoped).",
                    normalized_name,
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
                [_RUNDLL32, "printui.dll,PrintUIEntry", "/e", "/n", normalized_name],
            )
            return self.get_printer_preferences(normalized_name)
        except Exception as exc:
            raise PrintJobSubmissionError(
                f"Failed to open printer properties for '{normalized_name}': {exc}"
            ) from exc
