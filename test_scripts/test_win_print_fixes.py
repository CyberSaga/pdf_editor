"""Red-Light tests for the four Windows printing fixes (P1–P4).

These exercise the *real* Windows driver paths the previous "fix" commits never
touched:

- P1  printer preferences must not be permanently mutated: ``open_printer_properties``
      must NOT call ``SetPrinter(level=9)`` and must hand the captured DEVMODE back
      as a base64 string; the driver applies it job-scoped (set → print → restore);
      the base64 string survives the JSON ``job.json`` boundary used by the helper
      subprocess, and the print dialog injects it only at submission.
- P2/P3 a mixed paper-size / orientation PDF must split into one spooler job per
      contiguous layout group (per-page media is otherwise ignored by GDI).
- P4  the Windows raster path must cap effective DPI at 150 to keep the EMF spool
      small, while leaving lower DPIs untouched.

Plan: docs/plans/2026-06-01-plan-surgical-fixes-for-eager-biscuit.md
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import types
from pathlib import Path
from unittest import mock

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import src.printing.platforms.win_driver as wd  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.printing.base_driver import (  # noqa: E402
    PrinterDevice,
    PrintJobOptions,
    PrintJobResult,
)
from src.printing.helper_protocol import PrintHelperJob  # noqa: E402
from src.printing.print_dialog import UnifiedPrintDialog  # noqa: E402


class PyFakeHandle(int):
    """Handle whose type name starts with 'Py' so the ctypes path is selected."""


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_single_page_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "win print fixes", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _ok_result(*_args, **_kwargs) -> PrintJobResult:
    return PrintJobResult(success=True, route="test", message="ok")


# ---------------------------------------------------------------------------
# P1 — Printer preferences must not be permanently mutated
# ---------------------------------------------------------------------------


def _install_ctypes_dialog(monkeypatch, *, dialog_result: int = 1):
    """Patch the ctypes/win32print surface so the Properties dialog 'returns OK'."""
    set_printer_spy = mock.Mock(return_value=1)
    win32_setprinter_spy = mock.Mock(return_value=1)
    buffer_size = ctypes.sizeof(wd._PUBLIC_DEVMODEW) + 64

    fake_win32 = types.SimpleNamespace(
        OpenPrinter=lambda name: PyFakeHandle(7),
        ClosePrinter=lambda handle: None,
        GetPrinter=lambda handle, level: {},
        DeviceCapabilities=lambda *a, **k: [],
        SetPrinter=win32_setprinter_spy,
        DC_BINS=0,
        DC_BINNAMES=0,
    )
    # 1) buffer-size query, 2) DM_OUT_BUFFER init, 3) the dialog itself (IDOK == 1)
    docprops = mock.Mock(side_effect=[buffer_size, 0, dialog_result])

    monkeypatch.setattr(wd, "win32print", fake_win32)
    monkeypatch.setattr(wd, "_DOCUMENT_PROPERTIES_W", docprops)
    monkeypatch.setattr(wd, "_SET_PRINTER_W", set_printer_spy)
    return set_printer_spy, win32_setprinter_spy, buffer_size


def test_open_printer_properties_does_not_call_setprinter(monkeypatch) -> None:
    set_printer_spy, win32_setprinter_spy, _ = _install_ctypes_dialog(monkeypatch)

    driver = wd.WindowsPrinterDriver()
    result = driver.open_printer_properties("FakePrinter")

    assert isinstance(result, dict)
    assert set_printer_spy.called is False, "ctypes SetPrinterW(level=9) must not run"
    assert win32_setprinter_spy.called is False, "win32print.SetPrinter(level=9) must not run"


def test_open_printer_properties_returns_base64_devmode(monkeypatch) -> None:
    _, _, buffer_size = _install_ctypes_dialog(monkeypatch)

    driver = wd.WindowsPrinterDriver()
    result = driver.open_printer_properties("FakePrinter")

    buf = result.get("devmode_buffer")
    assert isinstance(buf, str) and buf, "devmode_buffer must be a non-empty base64 str"
    decoded = base64.b64decode(buf)
    assert len(decoded) == buffer_size, "base64 must round-trip to the captured DEVMODE bytes"


def test_print_pdf_applies_devmode_job_scoped_and_restores(monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "one.pdf"
    _make_single_page_pdf(pdf)

    original = b"ORIGINAL-DEVMODE" + bytes(80)
    job_bytes = b"JOB-DEVMODE-XYZ" + bytes(40)
    job_b64 = base64.b64encode(job_bytes).decode("ascii")

    events: list[tuple[str, bytes | None]] = []

    def fake_docprops(_hwnd, _handle, _name, out_buf, in_buf, mode):
        if out_buf is None and in_buf is None:
            return len(original)  # size query
        if out_buf is not None and (mode & wd._DM_OUT_BUFFER):
            ctypes.memmove(out_buf, original, len(original))
        return 1

    def fake_persist(_self, _handle, devmode_buffer, _printer_name):
        events.append(("persist", bytes(devmode_buffer)))

    def fake_raster(_pdf_path, _pages, _opts):
        events.append(("raster", None))
        return PrintJobResult(success=True, route="test", message="ok")

    fake_win32 = types.SimpleNamespace(
        OpenPrinter=lambda name: PyFakeHandle(3),
        ClosePrinter=lambda handle: None,
    )
    monkeypatch.setattr(wd, "win32print", fake_win32)
    monkeypatch.setattr(wd, "_DOCUMENT_PROPERTIES_W", fake_docprops)
    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)
    monkeypatch.setattr(
        wd.WindowsPrinterDriver, "_persist_devmode_buffer_user_defaults", fake_persist
    )

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter",
        paper_size="a4",
        orientation="portrait",
        extra_options={"devmode_buffer": job_b64},
    )
    result = driver.print_pdf(str(pdf), [0], options)

    assert result.success
    assert [name for name, _ in events] == ["persist", "raster", "persist"], (
        "DEVMODE must be applied before the job and restored after it"
    )
    assert events[0][1] == job_bytes, "job DEVMODE must be applied first"
    assert events[2][1] == original, "original DEVMODE must be restored last"


def test_devmode_buffer_injected_at_submission_survives_preview_and_json(tmp_path) -> None:
    _ensure_app()
    pdf = tmp_path / "s.pdf"
    _make_single_page_pdf(pdf)
    b64 = base64.b64encode(b"\x01\x02\x03DEVMODE\x00\x10").decode("ascii")

    dispatcher = _FakeDispatcher(props_result={"devmode_buffer": b64, "duplex": "long"})
    dialog = UnifiedPrintDialog(
        parent=None,
        dispatcher=dispatcher,
        printers=[PrinterDevice(name="Printer A", is_default=True, status="ready")],
        pdf_path=str(pdf),
        total_pages=1,
        current_page=1,
        job_name="job",
    )
    try:
        dialog.printer_properties_btn.click()

        # Preview refreshes call _build_effective_options() repeatedly — they must
        # NOT consume or clear the pending buffer.
        dialog._build_effective_options()
        dialog._build_effective_options()

        submission = dialog._build_submission_options()
        assert submission.extra_options.get("devmode_buffer") == b64

        # The base64 string must survive the helper-subprocess JSON boundary.
        job = PrintHelperJob(
            job_id="j",
            input_pdf_path=str(pdf),
            watermarks=[],
            options=submission,
        )
        raw = json.dumps(job.to_json_dict())  # must NOT raise
        restored = PrintHelperJob.from_json_dict(json.loads(raw))
        assert restored.options.extra_options.get("devmode_buffer") == b64

        # Consumed exactly once: a second submission has no stale buffer.
        again = dialog._build_submission_options()
        assert "devmode_buffer" not in again.extra_options
    finally:
        dialog.close()


def test_devmode_buffer_cleared_when_printer_switches(tmp_path) -> None:
    _ensure_app()
    pdf = tmp_path / "s.pdf"
    _make_single_page_pdf(pdf)
    b64 = base64.b64encode(b"DEVMODE-A").decode("ascii")

    dispatcher = _FakeDispatcher(props_result={"devmode_buffer": b64})
    dialog = UnifiedPrintDialog(
        parent=None,
        dispatcher=dispatcher,
        printers=[
            PrinterDevice(name="Printer A", is_default=True, status="ready"),
            PrinterDevice(name="Printer B", is_default=False, status="ready"),
        ],
        pdf_path=str(pdf),
        total_pages=1,
        current_page=1,
        job_name="job",
    )
    try:
        dialog.printer_properties_btn.click()
        assert dialog._pending_devmode_buffer == b64  # captured for Printer A

        idx = dialog.printer_combo.findData("Printer B")
        assert idx >= 0
        dialog.printer_combo.setCurrentIndex(idx)

        assert dialog._pending_devmode_buffer is None  # printer-specific → cleared
        submission = dialog._build_submission_options()
        assert "devmode_buffer" not in submission.extra_options
    finally:
        dialog.close()


# ---------------------------------------------------------------------------
# P2/P3 — per-page media: mixed-layout PDF splits into one job per group
# ---------------------------------------------------------------------------


def test_mixed_layout_pdf_splits_into_two_jobs(tmp_path, monkeypatch) -> None:
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # page 0: A4 portrait
    doc.new_page(width=1190.55, height=841.89)  # page 1: A3 landscape
    doc.save(pdf)
    doc.close()

    calls: list[tuple[list[int], str, str]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append((list(pages), opts.paper_size, opts.orientation))
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter", paper_size="auto", orientation="auto"
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert len(calls) == 2, "mixed paper/orientation must split into 2 spooler jobs"
    assert calls[0] == ([0], "a4", "portrait")
    assert calls[1] == ([1], "a3", "landscape")


def test_uniform_layout_pdf_stays_single_job(tmp_path, monkeypatch) -> None:
    pdf = tmp_path / "uniform.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)
    doc.new_page(width=595.28, height=841.89)
    doc.save(pdf)
    doc.close()

    calls: list[list[int]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append(list(pages))
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter", paper_size="auto", orientation="auto"
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert calls == [[0, 1]], "a uniform-layout document must remain a single job"


# ---------------------------------------------------------------------------
# P4 — Windows raster path caps DPI at 150 (but keeps lower DPIs)
# ---------------------------------------------------------------------------


def test_windows_caps_raster_dpi_at_150_but_keeps_lower(tmp_path, monkeypatch) -> None:
    pdf = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)
    doc.save(pdf)
    doc.close()

    captured: dict[str, int] = {}

    def fake_raster(_pdf_path, _pages, opts):
        captured["dpi"] = opts.dpi
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)
    driver = wd.WindowsPrinterDriver()

    driver.print_pdf(
        str(pdf),
        [0],
        PrintJobOptions(
            printer_name="FakePrinter", dpi=300, paper_size="a4", orientation="portrait"
        ),
    )
    assert captured["dpi"] == 150, "300 DPI must be capped to 150 on the Windows spooler path"

    driver.print_pdf(
        str(pdf),
        [0],
        PrintJobOptions(
            printer_name="FakePrinter", dpi=96, paper_size="a4", orientation="portrait"
        ),
    )
    assert captured["dpi"] == 96, "a DPI below the cap must be left untouched"


def test_pdf_output_path_is_not_split_or_capped(tmp_path, monkeypatch) -> None:
    """Preservation guarantee: virtual-printer PDF output keeps single-pass, full DPI."""
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # A4 portrait
    doc.new_page(width=1190.55, height=841.89)  # A3 landscape
    doc.save(pdf)
    doc.close()

    calls: list[tuple[list[int], int]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append((list(pages), opts.dpi))
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)
    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter",
        dpi=300,
        paper_size="auto",
        orientation="auto",
        output_pdf_path=str(tmp_path / "out.pdf"),
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert calls == [([0, 1], 300)], "PDF output must stay one full-DPI pass (no split, no cap)"


class _FakeDispatcher:
    """Minimal dispatcher stand-in for print-dialog tests."""

    def __init__(self, props_result: dict | None = None) -> None:
        self._props_result = props_result or {}
        self.printer_preferences: dict[str, object] = {}

    def get_default_printer(self) -> str | None:
        return "Printer A"

    def resolve_page_indices_for_count(self, total_pages: int, options) -> list[int]:
        _ = options
        return [0] if total_pages > 0 else []

    def supports_printer_properties_dialog(self) -> bool:
        return True

    def open_printer_properties(self, printer_name: str):
        _ = printer_name
        return dict(self._props_result)  # copy: callers pop devmode_buffer

    def get_printer_preferences(self, printer_name: str) -> dict[str, object]:
        _ = printer_name
        return dict(self.printer_preferences)
