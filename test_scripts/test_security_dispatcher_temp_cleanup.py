"""Security patch P5 (finding F5 / bandit B110): temp-unlink error visibility.

Originally: ``PrintDispatcher.print_pdf_bytes`` wrote the document to a temp file and
removed it in a ``finally``; a bare ``except Exception: pass`` there masked cleanup
failures (a leftover temp PDF holding document content). The failure had to be logged at
debug, while still not propagating (cleanup must not mask the result).

R5-01 moved that temp. The dispatcher no longer writes one at all — it hands bytes to
``PrinterDriver.print_pdf_from_bytes``. The only remaining temp-writing code is the
**base-driver fallback** for drivers that understand paths but not bytes. The P5 contract
therefore moves with it, and the dispatcher gains a stronger assertion: it must create no
temp whatsoever.

See ``plans/r5-01-fileless-print.md``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import pytest

from src.printing.base_driver import PrinterDriver, PrintJobOptions, PrintJobResult
from src.printing.dispatcher import PrintDispatcher


class _PathOnlyDriver(PrinterDriver):
    """A driver that only implements the path API, so it uses the base-class fallback."""

    def __init__(self) -> None:
        self.path_calls: list[str] = []

    @property
    def name(self) -> str:
        return "path-only"

    def list_printers(self):
        return []

    def get_default_printer(self):
        return None

    def get_printer_status(self, _printer_name: str) -> str:
        return "ready"

    def print_pdf(self, pdf_path, _page_indices, _options) -> PrintJobResult:
        self.path_calls.append(str(pdf_path))
        return PrintJobResult(success=True, route="test", message="ok")


# ── P5, relocated: the base-driver fallback must log, not swallow, unlink failures ──


def test_base_driver_temp_fallback_logs_unlink_failure_at_debug(monkeypatch, caplog) -> None:
    driver = _PathOnlyDriver()
    leaked: list[Path] = []

    def _boom(self, *args, **kwargs):
        leaked.append(Path(self))
        raise PermissionError("temp file is locked")

    monkeypatch.setattr("src.printing.base_driver.Path.unlink", _boom)

    try:
        with caplog.at_level(logging.DEBUG, logger="src.printing.base_driver"):
            result = driver.print_pdf_from_bytes(
                b"%PDF-1.4\n%%EOF\n", [0], PrintJobOptions().normalized()
            )

        # The cleanup failure must NOT propagate; the real result is returned.
        assert result.success
        assert driver.path_calls, "the fallback must still reach the path API"
        # And it must be observable at debug level rather than silently swallowed.
        debug_msgs = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.DEBUG and rec.name == "src.printing.base_driver"
        ]
        assert any("temp" in m.lower() for m in debug_msgs), debug_msgs
    finally:
        # Remove the temp file the patched unlink refused to delete.
        for path in leaked:
            try:
                os.unlink(path)
            except OSError:
                pass


# ── R5-01: the dispatcher itself must never create a temp ────────────────────


def test_dispatcher_print_pdf_bytes_creates_no_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    class _BytesDriver(_PathOnlyDriver):
        def print_pdf_from_bytes(self, pdf_bytes, page_indices, options) -> PrintJobResult:
            return PrintJobResult(success=True, route="bytes", message="ok")

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("dispatcher must not create a temp file (R5-01)")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", _forbidden)

    dispatcher = PrintDispatcher(driver=_BytesDriver())
    result = dispatcher.print_pdf_bytes(pdf_bytes, PrintJobOptions())
    assert result.success and result.route == "bytes"
