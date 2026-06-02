"""Security patch P3 (finding F4 + Linux lp/lpstat): absolute subprocess paths.

External binaries must be launched via an absolute path, not a bare image name
resolved through the OS search order (CWE-426/427 binary planting).

Scope note: ``LinuxPrinterDriver._submit_via_lp`` is intentionally NOT asserted
here. The pre-existing test ``test_linux_driver_overrides.py`` pins its argv to
the bare ``"lp"`` token, and the work boundary forbids editing current tests, so
that one call site is left as-is and documented in implementation-notes.md. The
two ``lpstat`` call sites and the Windows ``rundll32`` site have no such pin.
"""

from __future__ import annotations

import os

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
