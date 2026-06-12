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

Plan: plans/2026-06-01-plan-surgical-fixes-for-eager-biscuit.md
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

import pytest  # noqa: E402

import src.printing.platforms.win_driver as wd  # noqa: E402
import src.printing.qt_bridge as qtb  # noqa: E402
import src.printing.print_dialog as pdlg  # noqa: E402
from PySide6.QtCore import QMarginsF, QRectF  # noqa: E402
from PySide6.QtGui import QPageLayout, QPageSize  # noqa: E402
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo  # noqa: E402
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
        return True  # confirmed write (finding #4)

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


# ---------------------------------------------------------------------------
# Review findings — regression guards for the bugs found in the first patchset
# ---------------------------------------------------------------------------


def test_finding1_explicit_paper_preserved_when_orientation_auto(tmp_path, monkeypatch) -> None:
    """Finding #1: a user-pinned paper size must survive the layout split.

    Pages differ only in orientation; the user fixed paper to 'letter' but left
    orientation 'auto'. Every group must keep 'letter', not the auto-detected size.
    """
    pdf = tmp_path / "mixed_orient.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # portrait
    doc.new_page(width=841.89, height=595.28)  # landscape
    doc.save(pdf)
    doc.close()

    calls: list[tuple[list[int], str, str]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append((list(pages), opts.paper_size, opts.orientation))
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter", paper_size="letter", orientation="auto"
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert [paper for _, paper, _ in calls] == ["letter", "letter"], (
        "explicit paper must survive the split, not be overwritten by auto-detect"
    )
    assert [orient for _, _, orient in calls] == ["portrait", "landscape"], (
        "orientation is still auto-resolved per page"
    )


def test_finding2_collated_multicopy_mixed_layout_uses_document_order(
    tmp_path, monkeypatch
) -> None:
    """Finding #2 (Option A): collated copies loop the whole document in order.

    output for copies=2 collated over [A4, A3] -> A4,A3,A4,A3, each spool job = 1 copy.
    """
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # A4 portrait
    doc.new_page(width=1190.55, height=841.89)  # A3 landscape
    doc.save(pdf)
    doc.close()

    calls: list[tuple[list[int], str, str, int]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append((list(pages), opts.paper_size, opts.orientation, opts.copies))
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter",
        paper_size="auto",
        orientation="auto",
        copies=2,
        collate=True,
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert calls == [
        ([0], "a4", "portrait", 1),
        ([1], "a3", "landscape", 1),
        ([0], "a4", "portrait", 1),
        ([1], "a3", "landscape", 1),
    ], "collated multi-copy must repeat the document in order, 1 copy per group"


def test_finding2_uncollated_multicopy_mixed_layout_groups_copies_per_page(
    tmp_path, monkeypatch
) -> None:
    """Finding #2: uncollated copies stay page-grouped (one pass, copies=N per group)."""
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # A4 portrait
    doc.new_page(width=1190.55, height=841.89)  # A3 landscape
    doc.save(pdf)
    doc.close()

    calls: list[tuple[list[int], str, str, int, bool]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append(
            (list(pages), opts.paper_size, opts.orientation, opts.copies, opts.collate)
        )
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter",
        paper_size="auto",
        orientation="auto",
        copies=2,
        collate=False,
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert calls == [
        ([0], "a4", "portrait", 2, False),
        ([1], "a3", "landscape", 2, False),
    ], "uncollated multi-copy must group copies per page in document order"


def test_finding2_uniform_layout_multicopy_stays_single_job(tmp_path, monkeypatch) -> None:
    """Finding #2: a single layout group must stay one spooler job with copies=N.

    The driver collates a single-media job natively; exploding it into N jobs would
    be a regression (slower, N entries in the queue).
    """
    pdf = tmp_path / "uniform.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)
    doc.new_page(width=595.28, height=841.89)
    doc.save(pdf)
    doc.close()

    calls: list[tuple[list[int], int, bool]] = []

    def fake_raster(_pdf_path, pages, opts):
        calls.append((list(pages), opts.copies, opts.collate))
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter",
        paper_size="auto",
        orientation="auto",
        copies=3,
        collate=True,
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success
    assert calls == [([0, 1], 3, True)], "uniform layout must be one native multi-copy job"


def test_finding3_pending_devmode_survives_recoverable_range_error(
    tmp_path, monkeypatch
) -> None:
    """Finding #3: a recoverable page-range error must not drop the captured DEVMODE."""
    _ensure_app()
    pdf = tmp_path / "s.pdf"
    _make_single_page_pdf(pdf)
    b64 = base64.b64encode(b"DEVMODE-KEEP\x00\x11").decode("ascii")

    class _RangeOnceDispatcher(_FakeDispatcher):
        def __init__(self, props_result):
            super().__init__(props_result)
            self._raise_next = True

        def resolve_page_indices_for_count(self, total_pages, options):
            _ = (total_pages, options)
            if self._raise_next:
                self._raise_next = False
                raise ValueError("頁面範圍無效")
            return [0]

    # Replace the module's QMessageBox name so the warning is a no-op in tests.
    class _SilentMsgBox:
        @staticmethod
        def warning(*_a, **_k):
            return None

    monkeypatch.setattr(pdlg, "QMessageBox", _SilentMsgBox)

    dispatcher = _RangeOnceDispatcher({"devmode_buffer": b64})
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
        assert dialog._pending_devmode_buffer == b64

        dialog.accept()  # first attempt: range raises -> warning -> return
        assert dialog._pending_devmode_buffer == b64, (
            "a recoverable range error must leave the captured DEVMODE intact"
        )
        assert dialog._result is None

        dialog.accept()  # corrected attempt: resolves, buffer consumed exactly once
        assert dialog._result is not None
        assert dialog._result.options.extra_options.get("devmode_buffer") == b64
        assert dialog._pending_devmode_buffer is None
    finally:
        dialog.close()


def test_finding4_denied_apply_skips_restore_and_still_prints(tmp_path, monkeypatch) -> None:
    """Finding #4: if the apply write is denied, no restore is attempted and the job prints."""
    pdf = tmp_path / "one.pdf"
    _make_single_page_pdf(pdf)
    original = b"ORIGINAL" + bytes(80)
    job_b64 = base64.b64encode(b"JOB" + bytes(40)).decode("ascii")

    def fake_docprops(_hwnd, _handle, _name, out_buf, in_buf, mode):
        if out_buf is None and in_buf is None:
            return len(original)  # size query
        if out_buf is not None and (mode & wd._DM_OUT_BUFFER):
            ctypes.memmove(out_buf, original, len(original))
        return 1

    persist_calls: list[bytes] = []

    def fake_persist(_self, _handle, devmode_buffer, _printer_name):
        persist_calls.append(bytes(devmode_buffer))
        return False  # SetPrinterW denied

    raster_calls: list[bool] = []

    def fake_raster(_pdf_path, _pages, _opts):
        raster_calls.append(True)
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
    assert raster_calls == [True], "the job must still print with the current defaults"
    assert len(persist_calls) == 1, (
        "a denied apply must not trigger a restore write (only the apply was attempted)"
    )


def test_finding6_partial_failure_reports_already_spooled(tmp_path, monkeypatch) -> None:
    """Finding #6: a mid-split failure must report the pages already spooled, not imply none."""
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # A4 portrait -> group 1 (succeeds)
    doc.new_page(width=1190.55, height=841.89)  # A3 landscape -> group 2 (fails)
    doc.save(pdf)
    doc.close()

    calls: list[list[int]] = []

    def fake_raster(_pdf_path, pages, _opts):
        calls.append(list(pages))
        if len(calls) == 1:
            return PrintJobResult(success=True, route="test", message="ok")
        return PrintJobResult(success=False, route="test", message="printer offline")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter", paper_size="auto", orientation="auto"
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success is False
    assert len(calls) == 2, "must stop after the failing group"
    assert "already been spooled" in result.message, "must disclose the partial output"
    assert "printer offline" in result.message, "must preserve the underlying cause"


def test_finding6_first_group_failure_returns_plain_result(tmp_path, monkeypatch) -> None:
    """Finding #6: if the first group fails (nothing spooled), return the plain error."""
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)  # A4 portrait
    doc.new_page(width=1190.55, height=841.89)  # A3 landscape
    doc.save(pdf)
    doc.close()

    def fake_raster(_pdf_path, _pages, _opts):
        return PrintJobResult(success=False, route="test", message="printer offline")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter", paper_size="auto", orientation="auto"
    )
    result = driver.print_pdf(str(pdf), [0, 1], options)

    assert result.success is False
    assert result.message == "printer offline", "no partial-output wrapper when nothing spooled"


def test_finding11_malformed_devmode_b64_falls_through_to_split(tmp_path, monkeypatch) -> None:
    """Finding #11: a malformed base64 DEVMODE decodes to b'' and is ignored, not crashed on."""
    pdf = tmp_path / "a4.pdf"
    doc = fitz.open()
    doc.new_page(width=595.28, height=841.89)
    doc.save(pdf)
    doc.close()

    assert wd._decode_devmode_b64("not valid base64 !!!") == b""

    scoped_calls: list[bool] = []
    monkeypatch.setattr(
        wd.WindowsPrinterDriver,
        "_print_with_scoped_devmode",
        lambda *a, **k: scoped_calls.append(True),
    )

    raster_calls: list[bool] = []

    def fake_raster(_pdf_path, _pages, _opts):
        raster_calls.append(True)
        return PrintJobResult(success=True, route="test", message="ok")

    monkeypatch.setattr(wd, "raster_print_pdf", fake_raster)

    driver = wd.WindowsPrinterDriver()
    options = PrintJobOptions(
        printer_name="FakePrinter",
        paper_size="a4",
        orientation="portrait",
        extra_options={"devmode_buffer": "not valid base64 !!!"},
    )
    result = driver.print_pdf(str(pdf), [0], options)

    assert result.success
    assert scoped_calls == [], "a malformed DEVMODE must not enter the scoped-apply path"
    assert raster_calls == [True], "the job still prints via the normal raster path"


def test_finding7_buffer_only_props_do_not_reload_defaults(tmp_path, monkeypatch) -> None:
    """Finding #7: capturing a DEVMODE with no public prefs must not revert dialog fields."""
    _ensure_app()
    pdf = tmp_path / "s.pdf"
    _make_single_page_pdf(pdf)
    b64 = base64.b64encode(b"OPAQUE-DEVMODE\x00\x07").decode("ascii")

    class _CountingDispatcher(_FakeDispatcher):
        def __init__(self, props_result):
            super().__init__(props_result)
            self.prefs_reload_count = 0

        def get_printer_preferences(self, printer_name):
            self.prefs_reload_count += 1
            return dict(self.printer_preferences)

    # props returns ONLY the buffer (no separable public prefs).
    dispatcher = _CountingDispatcher({"devmode_buffer": b64})
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
        before = dispatcher.prefs_reload_count
        dialog.printer_properties_btn.click()

        assert dialog._pending_devmode_buffer == b64, "buffer must be captured"
        assert dispatcher.prefs_reload_count == before, (
            "a captured DEVMODE must not trigger a defaults reload that reverts fields"
        )
    finally:
        dialog.close()


# ---------------------------------------------------------------------------
# Per-page SIZE actually reaching the device (the P3 regression that mocked
# raster_print_pdf could never catch)
# ---------------------------------------------------------------------------


class _WindowsLikePrinter:
    """Mimics the real Windows QPrinter quirk verified against a live driver:
    ``setPageLayout(pageLayout()-copy)`` applies the orientation but silently
    leaves the page SIZE at the printer default; only the dedicated
    ``setPageSize()`` / ``setPageOrientation()`` setters change the media.
    """

    def __init__(self) -> None:
        self._size = QPageSize(QPageSize.A3)  # printer default (e.g. an A3 device)
        self._orientation = QPageLayout.Orientation.Portrait
        self.size_setter_used = False

    def pageLayout(self) -> QPageLayout:
        return QPageLayout(self._size, self._orientation, QMarginsF())

    def setPageLayout(self, layout: QPageLayout) -> bool:
        self._orientation = layout.orientation()  # size deliberately NOT applied
        return True

    def setPageSize(self, size: QPageSize) -> bool:
        self._size = size
        self.size_setter_used = True
        return True

    def setPageOrientation(self, orientation) -> bool:
        self._orientation = orientation
        return True


def test_set_page_layout_actually_applies_page_size() -> None:
    """_set_page_layout must apply the page SIZE via a setter that works on Windows.

    The setPageLayout(pageLayout()-copy) idiom leaves the size at the printer default
    on the real GDI device (orientation switches, size does not) — so a per-page A4
    silently prints on the default A3.
    """
    printer = _WindowsLikePrinter()
    qtb._set_page_layout(
        printer,
        QRectF(0, 0, 595.28, 841.89),
        PrintJobOptions(paper_size="a4", orientation="portrait"),
    )
    assert printer.pageLayout().pageSize().id() == QPageSize.A4, (
        "requested A4 media must actually be applied, not left at the default"
    )
    assert printer.size_setter_used, "must use the dedicated page-size setter"


def test_set_page_layout_applies_size_on_real_printer() -> None:
    """Faithful regression on the real GDI path (skipped without a Windows printer)."""
    if sys.platform != "win32":
        pytest.skip("Windows GDI page-size behaviour")
    _ensure_app()
    infos = [i for i in QPrinterInfo.availablePrinters() if not i.isNull()]
    if not infos:
        pytest.skip("no printers available")
    target = next((i for i in infos if i.isDefault()), infos[0])
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPrinterName(target.printerName())
    supported = {s.id() for s in QPrinterInfo(printer).supportedPageSizes()}
    if QPageSize.A4 not in supported or QPageSize.A3 not in supported:
        pytest.skip("printer does not offer both A4 and A3")

    qtb._set_page_layout(
        printer,
        QRectF(0, 0, 595.28, 841.89),
        PrintJobOptions(paper_size="a4", orientation="portrait"),
    )
    assert printer.pageLayout().pageSize().id() == QPageSize.A4

    qtb._set_page_layout(
        printer,
        QRectF(0, 0, 841.89, 1190.55),
        PrintJobOptions(paper_size="a3", orientation="portrait"),
    )
    assert printer.pageLayout().pageSize().id() == QPageSize.A3
