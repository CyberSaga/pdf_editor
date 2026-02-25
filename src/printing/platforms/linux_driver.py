"""Linux CUPS/lp print driver implementation."""

from __future__ import annotations

import shutil
import subprocess
from typing import Dict, List, Optional

from PySide6.QtPrintSupport import QPrinterInfo

from ..base_driver import PrintJobOptions, PrintJobResult, PrinterDevice, PrinterDriver
from ..errors import PrintJobSubmissionError, PrinterUnavailableError
from ..qt_bridge import raster_print_pdf

try:
    import cups  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cups = None


class LinuxPrinterDriver(PrinterDriver):
    """Linux driver with CUPS direct path and lp fallback."""

    @property
    def name(self) -> str:
        return "linux_cups"

    @property
    def supports_direct_pdf(self) -> bool:
        return cups is not None or shutil.which("lp") is not None

    def _cups_connection(self):
        if cups is None:
            return None
        try:
            return cups.Connection()
        except Exception:
            return None

    def list_printers(self) -> List[PrinterDevice]:
        default_name = self.get_default_printer()
        devices: List[PrinterDevice] = []

        conn = self._cups_connection()
        if conn is not None:
            for name, info in conn.getPrinters().items():
                state = int(info.get("printer-state", 0))
                status = "ready" if state in (3, 4) else "stopped"
                devices.append(
                    PrinterDevice(
                        name=name,
                        is_default=(name == default_name),
                        status=status,
                        raw=info,
                    )
                )
            return devices

        if shutil.which("lpstat"):
            try:
                proc = subprocess.run(
                    ["lpstat", "-a"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in proc.stdout.splitlines():
                    parts = line.strip().split()
                    if not parts:
                        continue
                    name = parts[0]
                    devices.append(
                        PrinterDevice(
                            name=name,
                            is_default=(name == default_name),
                            status="unknown",
                        )
                    )
                return devices
            except Exception:
                pass

        # Last fallback: Qt printer info.
        for name in QPrinterInfo.availablePrinterNames():
            devices.append(
                PrinterDevice(
                    name=name,
                    is_default=(name == default_name),
                    status="unknown",
                )
            )
        return devices

    def get_default_printer(self) -> Optional[str]:
        conn = self._cups_connection()
        if conn is not None:
            try:
                return conn.getDefault() or None
            except Exception:
                return None

        if shutil.which("lpstat"):
            try:
                proc = subprocess.run(
                    ["lpstat", "-d"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                # sample: "system default destination: HP_LaserJet"
                text = proc.stdout.strip()
                if ":" in text:
                    return text.split(":", 1)[1].strip() or None
            except Exception:
                pass

        default = QPrinterInfo.defaultPrinter()
        if default.isNull():
            return None
        return default.printerName()

    def get_printer_status(self, printer_name: str) -> str:
        conn = self._cups_connection()
        if conn is not None:
            try:
                info = conn.getPrinters().get(printer_name, {})
                state = int(info.get("printer-state", 0))
                if state == 3:
                    return "ready"
                if state == 4:
                    return "printing"
                if state == 5:
                    return "stopped"
            except Exception:
                pass
        return "unknown"

    @staticmethod
    def _to_cups_options(options: PrintJobOptions) -> Dict[str, str]:
        cups_options: Dict[str, str] = {}
        if options.page_ranges:
            cups_options["page-ranges"] = options.page_ranges
        cups_options["copies"] = str(options.copies)
        cups_options["collate"] = "true" if options.collate else "false"
        if options.fit_to_page:
            cups_options["fit-to-page"] = "true"
        if options.color_mode == "grayscale":
            cups_options["print-color-mode"] = "monochrome"
            cups_options["ColorModel"] = "Gray"
        else:
            cups_options["print-color-mode"] = "color"
        if options.duplex == "long":
            cups_options["sides"] = "two-sided-long-edge"
        elif options.duplex == "short":
            cups_options["sides"] = "two-sided-short-edge"
        for key, value in options.extra_options.items():
            cups_options[str(key)] = str(value)
        return cups_options

    def _submit_via_cups(self, pdf_path: str, options: PrintJobOptions) -> PrintJobResult:
        conn = self._cups_connection()
        if conn is None:
            raise PrintJobSubmissionError("CUPS connection unavailable.")
        printer_name = options.printer_name or conn.getDefault()
        if not printer_name:
            raise PrinterUnavailableError("No printer selected and no default printer.")

        job_id = conn.printFile(
            printer_name,
            pdf_path,
            options.job_name,
            self._to_cups_options(options),
        )
        return PrintJobResult(
            success=True,
            route="cups-direct-pdf",
            message=f"Submitted print job to CUPS printer '{printer_name}'.",
            job_id=str(job_id),
        )

    def _submit_via_lp(self, pdf_path: str, options: PrintJobOptions) -> PrintJobResult:
        if shutil.which("lp") is None:
            raise PrintJobSubmissionError("lp command unavailable.")

        cmd = ["lp", "-n", str(options.copies)]
        printer_name = options.printer_name or self.get_default_printer()
        if printer_name:
            cmd.extend(["-d", printer_name])
        if options.page_ranges:
            cmd.extend(["-P", options.page_ranges])
        if options.fit_to_page:
            cmd.extend(["-o", "fit-to-page"])
        if options.duplex == "long":
            cmd.extend(["-o", "sides=two-sided-long-edge"])
        elif options.duplex == "short":
            cmd.extend(["-o", "sides=two-sided-short-edge"])
        if options.color_mode == "grayscale":
            cmd.extend(["-o", "ColorModel=Gray"])
        cmd.append(pdf_path)

        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = (proc.stdout or "").strip()
        return PrintJobResult(
            success=True,
            route="lp-direct-pdf",
            message=out or "Submitted print job via lp.",
        )

    def print_pdf(
        self,
        pdf_path: str,
        page_indices: List[int],
        options: PrintJobOptions,
    ) -> PrintJobResult:
        normalized = options.normalized()
        requires_exact_page_order = (
            normalized.page_subset != "all" or normalized.reverse_order
        )
        requires_custom_scaling = normalized.scale_mode == "custom"
        direct_path_allowed = (
            normalized.transport in ("auto", "direct_pdf")
            and normalized.output_pdf_path is None
            and not requires_exact_page_order
            and not requires_custom_scaling
        )

        if direct_path_allowed and self.supports_direct_pdf:
            try:
                if self._cups_connection() is not None:
                    return self._submit_via_cups(pdf_path, normalized)
                if shutil.which("lp") is not None:
                    return self._submit_via_lp(pdf_path, normalized)
            except Exception as exc:
                if normalized.transport == "direct_pdf":
                    raise PrintJobSubmissionError(
                        f"Direct print failed: {exc}"
                    ) from exc

        # Fallback route: reliable raster stream into Qt print backend.
        return raster_print_pdf(pdf_path, page_indices, normalized)
