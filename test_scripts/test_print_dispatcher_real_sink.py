"""R5-01 — regression guard over the *real* dispatcher temp-file sink.

``PrintDispatcher.print_pdf_bytes`` writes the (decrypted) print bytes to a
``NamedTemporaryFile`` for the driver/spooler, then deletes it in a ``finally``.
The R5.1 suite asserted only that the *helper* output is decrypted and mocked the
dispatcher, so it never inspected this real sink — the review (R5-01) flagged that gap.

This test drives the real ``print_pdf_bytes`` with a recording driver and pins both halves
of the current contract:
  * the plaintext temp DOES exist (and carries the bytes) *during* the driver call — this
    is the acknowledged residual exposure; fully removing it needs a fileless / password-
    aware raster path (deferred — see docs/PITFALLS.md and TODOS R5-01);
  * the temp is gone once the call returns — the guaranteed-deletion behavior must not
    regress (e.g. back to ``delete=False`` with no ``finally`` unlink).
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrintJobOptions, PrintJobResult  # noqa: E402
from src.printing.dispatcher import PrintDispatcher  # noqa: E402


class _RecordingDriver:
    """Captures the temp path the dispatcher hands the driver, mid-call."""

    def __init__(self) -> None:
        self.seen_path: str | None = None
        self.existed_during_call: bool | None = None
        self.content_during_call: bytes = b""

    def get_printer_status(self, _printer_name: str) -> str:
        return "ready"

    def print_pdf(self, pdf_path: str, _page_indices, _options) -> PrintJobResult:
        self.seen_path = pdf_path
        path = Path(pdf_path)
        self.existed_during_call = path.exists()
        self.content_during_call = path.read_bytes() if path.exists() else b""
        return PrintJobResult(success=True, route="test", message="ok")


def _one_page_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "print sink probe", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def test_dispatcher_temp_exists_during_driver_then_deleted_after() -> None:
    pdf_bytes = _one_page_pdf_bytes()
    driver = _RecordingDriver()
    dispatcher = PrintDispatcher(driver=driver)  # real PDFRenderer

    result = dispatcher.print_pdf_bytes(pdf_bytes, PrintJobOptions(printer_name="Printer A"))

    assert result.success
    # Acknowledged residual: the plaintext temp existed and carried the bytes during the call.
    assert driver.existed_during_call is True
    assert driver.content_during_call == pdf_bytes
    # Guaranteed: the temp is deleted once print_pdf_bytes returns (no plaintext at rest).
    assert driver.seen_path is not None
    assert not Path(driver.seen_path).exists(), (
        "dispatcher must delete the print temp file after the driver call (R5-01)"
    )
