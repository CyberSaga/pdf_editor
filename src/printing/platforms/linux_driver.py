"""Linux CUPS/lp print driver implementation."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator

from PySide6.QtPrintSupport import QPrinterInfo

from ..base_driver import PrinterDevice, PrinterDriver, PrintJobOptions, PrintJobResult
from ..errors import PrinterUnavailableError, PrintJobSubmissionError
from ..qt_bridge import raster_print_pdf

logger = logging.getLogger(__name__)

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

    def list_printers(self) -> list[PrinterDevice]:
        default_name = self.get_default_printer()
        devices: list[PrinterDevice] = []

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

        lpstat_path = shutil.which("lpstat")
        if lpstat_path:
            try:
                proc = subprocess.run(
                    [lpstat_path, "-a"],
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

    def get_default_printer(self) -> str | None:
        conn = self._cups_connection()
        if conn is not None:
            try:
                return conn.getDefault() or None
            except Exception:
                return None

        lpstat_path = shutil.which("lpstat")
        if lpstat_path:
            try:
                proc = subprocess.run(
                    [lpstat_path, "-d"],
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
    def _to_cups_options(options: PrintJobOptions) -> dict[str, str]:
        cups_options: dict[str, str] = {}
        if options.page_ranges:
            cups_options["page-ranges"] = options.page_ranges
        cups_options["copies"] = str(options.copies)
        cups_options["collate"] = "true" if options.collate else "false"
        if options.fit_to_page:
            cups_options["fit-to-page"] = "true"
        if "color_mode" in options.override_fields:
            if options.color_mode == "grayscale":
                cups_options["print-color-mode"] = "monochrome"
                cups_options["ColorModel"] = "Gray"
            else:
                cups_options["print-color-mode"] = "color"
        if "duplex" in options.override_fields:
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
        # Resolve the lp binary to an absolute path rather than launching the bare
        # image name through the OS search order (CWE-426/427 binary planting, F4).
        lp_path = shutil.which("lp")
        if lp_path is None:
            raise PrintJobSubmissionError("lp command unavailable.")

        cmd = [lp_path, "-n", str(options.copies)]
        printer_name = options.printer_name or self.get_default_printer()
        if printer_name:
            cmd.extend(["-d", printer_name])
        if options.page_ranges:
            cmd.extend(["-P", options.page_ranges])
        if options.fit_to_page:
            cmd.extend(["-o", "fit-to-page"])
        if "duplex" in options.override_fields:
            if options.duplex == "long":
                cmd.extend(["-o", "sides=two-sided-long-edge"])
            elif options.duplex == "short":
                cmd.extend(["-o", "sides=two-sided-short-edge"])
        if "color_mode" in options.override_fields and options.color_mode == "grayscale":
            cmd.extend(["-o", "ColorModel=Gray"])
        cmd.append(pdf_path)

        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = (proc.stdout or "").strip()
        return PrintJobResult(
            success=True,
            route="lp-direct-pdf",
            message=out or "Submitted print job via lp.",
        )

    @staticmethod
    def _direct_path_allowed(normalized: PrintJobOptions) -> bool:
        requires_exact_page_order = (
            normalized.page_subset != "all" or normalized.reverse_order
        )
        requires_custom_scaling = normalized.scale_mode == "custom"
        requires_fixed_layout = bool(
            {"paper_size", "orientation"} & set(normalized.override_fields)
        )
        return (
            normalized.transport in ("auto", "direct_pdf")
            and normalized.output_pdf_path is None
            and not requires_exact_page_order
            and not requires_custom_scaling
            and not requires_fixed_layout
        )

    def _submit_direct(self, pdf_path: str, normalized: PrintJobOptions) -> PrintJobResult | None:
        """Try the CUPS/lp direct-PDF routes. Returns None when neither is available."""
        if self._cups_connection() is not None:
            return self._submit_via_cups(pdf_path, normalized)
        if shutil.which("lp") is not None:
            return self._submit_via_lp(pdf_path, normalized)
        return None

    @staticmethod
    @contextlib.contextmanager
    def _materialized_pdf(pdf_bytes: bytes) -> Iterator[str]:
        """The one documented R5-01 residual: CUPS/lp need a real file.

        ``conn.printFile`` and the ``lp`` CLI hand the path to the CUPS filter chain,
        which must parse and rasterise it — so this temp cannot be encrypted, because
        the consumer needs plaintext. It is minimised instead: created here inside the
        driver (not in the dispatcher), so it exists only across the submission call;
        owner-only (``NamedTemporaryFile`` is 0600 on POSIX); unlinked in ``finally``.

        Windows never reaches this code — its route is fully fileless.
        """
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name
        try:
            yield temp_path
        finally:
            try:
                os.unlink(temp_path)
            except OSError as exc:
                logger.debug("Failed to remove direct-print temp %s: %s", temp_path, exc)

    def print_pdf(
        self,
        pdf_path: str,
        page_indices: list[int],
        options: PrintJobOptions,
    ) -> PrintJobResult:
        normalized = options.normalized()

        if self._direct_path_allowed(normalized) and self.supports_direct_pdf:
            try:
                result = self._submit_direct(pdf_path, normalized)
                if result is not None:
                    return result
            except Exception as exc:
                if normalized.transport == "direct_pdf":
                    raise PrintJobSubmissionError(
                        f"Direct print failed: {exc}"
                    ) from exc

        # Fallback route: reliable raster stream into Qt print backend.
        return raster_print_pdf(pdf_path, page_indices, normalized)

    def print_pdf_from_bytes(
        self,
        pdf_bytes: bytes,
        page_indices: list[int],
        options: PrintJobOptions,
    ) -> PrintJobResult:
        """R5-01: raster route is fileless; only CUPS/lp materialise a scoped temp."""
        normalized = options.normalized()

        if self._direct_path_allowed(normalized) and self.supports_direct_pdf:
            try:
                with self._materialized_pdf(pdf_bytes) as temp_path:
                    result = self._submit_direct(temp_path, normalized)
                    if result is not None:
                        return result
            except Exception as exc:
                if normalized.transport == "direct_pdf":
                    raise PrintJobSubmissionError(
                        f"Direct print failed: {exc}"
                    ) from exc

        # Fallback route: rasterise straight from memory — no file at any point.
        return raster_print_pdf(pdf_bytes, page_indices, normalized)
