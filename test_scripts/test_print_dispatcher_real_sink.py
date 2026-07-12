"""R5-01 — regression guard over the *real* dispatcher sink.

Historically ``PrintDispatcher.print_pdf_bytes`` wrote the (decrypted) print bytes to a
``NamedTemporaryFile`` for the driver/spooler and deleted it in a ``finally``. This test
pinned that contract, documenting the plaintext-at-rest window as an acknowledged residual.

The residual is now closed. The dispatcher hands the bytes straight to
``PrinterDriver.print_pdf_from_bytes``; no temp is created on the happy path. This test
drives the real ``print_pdf_bytes`` with a recording driver and pins the *new* contract:

  * the driver receives the exact bytes, in memory;
  * ``print_pdf`` (the path API) is never reached;
  * no temp file is created at any point during the call.

See ``plans/r5-01-fileless-print.md`` and ``docs/PITFALLS.md``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrinterDriver, PrintJobOptions, PrintJobResult  # noqa: E402
from src.printing.dispatcher import PrintDispatcher  # noqa: E402


class _RecordingDriver(PrinterDriver):
    """Captures how the dispatcher reached the driver."""

    def __init__(self) -> None:
        self.seen_bytes: bytes | None = None
        self.seen_pages: list[int] | None = None
        self.path_calls: list[str] = []

    @property
    def name(self) -> str:
        return "recording"

    def list_printers(self):
        return []

    def get_default_printer(self):
        return None

    def get_printer_status(self, _printer_name: str) -> str:
        return "ready"

    def print_pdf(self, pdf_path, _page_indices, _options) -> PrintJobResult:
        self.path_calls.append(str(pdf_path))
        return PrintJobResult(success=True, route="path", message="ok")

    def print_pdf_from_bytes(self, pdf_bytes, page_indices, _options) -> PrintJobResult:
        self.seen_bytes = bytes(pdf_bytes)
        self.seen_pages = list(page_indices)
        return PrintJobResult(success=True, route="bytes", message="ok")


def _one_page_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "print sink probe", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def test_dispatcher_hands_bytes_to_driver_and_creates_no_temp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = _one_page_pdf_bytes()
    driver = _RecordingDriver()
    dispatcher = PrintDispatcher(driver=driver)  # real PDFRenderer

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("dispatcher must not create a temp file (R5-01)")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", _forbidden)

    result = dispatcher.print_pdf_bytes(pdf_bytes, PrintJobOptions(printer_name="Printer A"))

    assert result.success
    assert result.route == "bytes"
    # The driver got the document in memory, byte for byte.
    assert driver.seen_bytes == pdf_bytes
    assert driver.seen_pages == [0]
    # The path API was never reached, so nothing was ever materialised.
    assert driver.path_calls == []


def test_dispatcher_preflight_still_runs_on_the_bytes_path() -> None:
    """Page-range resolution and printer-status checks must survive the fileless switch."""
    from src.printing.errors import PrinterUnavailableError

    class _Offline(_RecordingDriver):
        def get_printer_status(self, _printer_name: str) -> str:
            return "offline"

    dispatcher = PrintDispatcher(driver=_Offline())
    with pytest.raises(PrinterUnavailableError):
        dispatcher.print_pdf_bytes(_one_page_pdf_bytes(), PrintJobOptions(printer_name="Dead"))


def test_path_api_still_works_for_drivers_that_need_a_file(tmp_path: Path) -> None:
    """print_pdf_file is unchanged — external callers (preview dialog) still use it."""
    pdf_path = tmp_path / "src.pdf"
    pdf_path.write_bytes(_one_page_pdf_bytes())

    driver = _RecordingDriver()
    dispatcher = PrintDispatcher(driver=driver)
    result = dispatcher.print_pdf_file(str(pdf_path), PrintJobOptions(printer_name="Printer A"))

    assert result.success and result.route == "path"
    assert driver.path_calls == [str(pdf_path)]
    assert driver.seen_bytes is None
