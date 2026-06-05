"""Security patch P3 (finding F4 + Linux lp/lpstat): absolute subprocess paths.

External binaries must be launched via an absolute path, not a bare image name
resolved through the OS search order (CWE-426/427 binary planting).

Covers all three POSIX/Windows call sites: ``rundll32`` (Windows printer
properties), the two ``lpstat`` sites (Linux discovery), and ``_submit_via_lp``
(Linux direct print). The ``_submit_via_lp`` hardening was completed as an
authorized follow-up; the one pinned assertion in ``test_linux_driver_overrides``
was updated in lockstep to expect the absolute path.
"""

from __future__ import annotations

import os

from src.printing.base_driver import PrintJobOptions
from src.printing.platforms import linux_driver, win_driver
from src.printing.platforms.linux_driver import LinuxPrinterDriver
from src.printing.platforms.win_driver import WindowsPrinterDriver


def test_win_rundll32_uses_absolute_system32_path(monkeypatch) -> None:
    captured: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, *a, **k):
            captured.append(list(args))

    monkeypatch.setattr(win_driver, "win32print", None)
    monkeypatch.setattr(
        WindowsPrinterDriver,
        "supports_printer_properties_dialog",
        property(lambda self: True),
    )
    monkeypatch.setattr(win_driver.subprocess, "Popen", _FakePopen)

    driver = WindowsPrinterDriver()
    monkeypatch.setattr(driver, "get_printer_preferences", lambda name: {})

    driver.open_printer_properties("FakePrinter")

    assert captured, "rundll32 Popen was not invoked"
    argv0 = captured[0][0]
    assert os.path.isabs(argv0), f"argv[0] must be absolute, got {argv0!r}"
    assert argv0.lower().endswith(os.path.join("system32", "rundll32.exe").lower())
    # The remaining tokens are unchanged.
    assert captured[0][1:] == ["printui.dll,PrintUIEntry", "/e", "/n", "FakePrinter"]


def test_linux_get_default_printer_uses_absolute_lpstat_path(monkeypatch) -> None:
    driver = LinuxPrinterDriver()
    captured: list[list[str]] = []

    monkeypatch.setattr(driver, "_cups_connection", lambda: None)
    monkeypatch.setattr(
        linux_driver.shutil,
        "which",
        lambda name: "/usr/bin/lpstat" if name == "lpstat" else None,
    )

    def _fake_run(cmd, capture_output, text, check):
        _ = (capture_output, text, check)
        captured.append(list(cmd))

        class _Result:
            stdout = "system default destination: HP_LaserJet"

        return _Result()

    monkeypatch.setattr(linux_driver.subprocess, "run", _fake_run)

    result = driver.get_default_printer()

    assert captured == [["/usr/bin/lpstat", "-d"]]
    assert result == "HP_LaserJet"


def test_linux_list_printers_uses_absolute_lpstat_path(monkeypatch) -> None:
    driver = LinuxPrinterDriver()
    captured: list[list[str]] = []

    monkeypatch.setattr(driver, "_cups_connection", lambda: None)
    monkeypatch.setattr(driver, "get_default_printer", lambda: None)
    monkeypatch.setattr(
        linux_driver.shutil,
        "which",
        lambda name: "/usr/bin/lpstat" if name == "lpstat" else None,
    )

    def _fake_run(cmd, capture_output, text, check):
        _ = (capture_output, text, check)
        captured.append(list(cmd))

        class _Result:
            stdout = "printerA accepting requests\nprinterB accepting requests"

        return _Result()

    monkeypatch.setattr(linux_driver.subprocess, "run", _fake_run)

    devices = driver.list_printers()

    assert captured == [["/usr/bin/lpstat", "-a"]]
    assert [device.name for device in devices] == ["printerA", "printerB"]


def test_linux_submit_via_lp_uses_absolute_lp_path(monkeypatch, tmp_path) -> None:
    driver = LinuxPrinterDriver()
    captured: list[list[str]] = []

    monkeypatch.setattr(
        linux_driver.shutil,
        "which",
        lambda name: "/usr/bin/lp" if name == "lp" else None,
    )

    def _fake_run(cmd, capture_output, text, check):
        _ = (capture_output, text, check)
        captured.append(list(cmd))

        class _Result:
            stdout = "request id is printer-789"

        return _Result()

    monkeypatch.setattr(linux_driver.subprocess, "run", _fake_run)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    result = driver._submit_via_lp(
        str(pdf_path),
        PrintJobOptions(printer_name="Printer A", copies=1),
    )

    assert result.success is True
    assert captured, "lp subprocess.run was not invoked"
    argv0 = captured[0][0]
    assert os.path.isabs(argv0), f"argv[0] must be absolute, got {argv0!r}"
    assert argv0 == "/usr/bin/lp"
