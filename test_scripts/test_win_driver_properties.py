# -*- coding: utf-8 -*-
"""Regression tests for Windows printer properties sync behavior."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.platforms import win_driver as win_mod


class _FakeDevMode:
    PaperSize = 9
    Orientation = 2
    Duplex = 2
    DefaultSource = 2
    Color = 2
    PrintQuality = 600
    Copies = 1


def _clone_devmode(devmode: object) -> _FakeDevMode:
    clone = _FakeDevMode()
    for name in ("PaperSize", "Orientation", "Duplex", "DefaultSource", "Color", "PrintQuality", "Copies"):
        setattr(clone, name, getattr(devmode, name))
    return clone


class _FakeWin32Print:
    DC_BINS = 6
    DC_BINNAMES = 12
    DM_IN_PROMPT = 0x0004
    DM_IN_BUFFER = 0x0008
    DM_OUT_BUFFER = 0x0002

    def __init__(self) -> None:
        self._devmode = _FakeDevMode()
        self._calls: list[tuple[str, object]] = []

    def OpenPrinter(self, printer_name: str):
        self._calls.append(("OpenPrinter", printer_name))
        return object()

    def ClosePrinter(self, handle) -> None:
        self._calls.append(("ClosePrinter", handle))

    def GetPrinter(self, handle, level: int):
        _ = handle
        self._calls.append(("GetPrinter", level))
        return {"pDevMode": self._devmode, "pPortName": "WSD-PORT"}

    def DocumentProperties(self, hwnd, handle, printer_name, out_devmode, in_devmode, flags):
        _ = (hwnd, handle, printer_name, out_devmode, in_devmode, flags)
        self._calls.append(("DocumentProperties", printer_name))
        return 1

    def SetPrinter(self, handle, level, info, command) -> None:
        _ = (handle, info, command)
        self._calls.append(("SetPrinter", level))
        if int(level) == 9:
            return
        raise RuntimeError("(5, 'SetPrinter', 'Access is denied.')")

    def DeviceCapabilities(self, printer_name, port_name, capability):
        _ = printer_name
        if capability == self.DC_BINS:
            if port_name == "WSD-PORT":
                raise RuntimeError("simulated port mismatch")
            return [1, 2]
        if capability == self.DC_BINNAMES:
            if port_name == "WSD-PORT":
                raise RuntimeError("simulated port mismatch")
            return ["Tray 1", "Tray 2"]
        return []


def test_open_printer_properties_ignores_setprinter_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWin32Print()
    monkeypatch.setattr(win_mod, "win32print", fake)

    driver = win_mod.WindowsPrinterDriver()
    prefs = driver.open_printer_properties("Printer A")

    assert isinstance(prefs, dict)
    assert prefs.get("paper_size") == "a4"
    assert prefs.get("orientation") == "landscape"
    assert prefs.get("duplex") == "long"
    assert prefs.get("paper_tray") == "2"
    assert prefs.get("dpi") == 600
    assert isinstance(prefs.get("paper_tray_options"), list)
    assert len(prefs["paper_tray_options"]) >= 2
    assert ("SetPrinter", 9) in fake._calls


class _FakeWin32PrintLimitedPort(_FakeWin32Print):
    def DeviceCapabilities(self, printer_name, port_name, capability):
        _ = printer_name
        if capability == self.DC_BINS:
            if port_name == "WSD-PORT":
                return [15]
            return [1, 2, 3, 4, 5]
        if capability == self.DC_BINNAMES:
            if port_name == "WSD-PORT":
                return [""]
            return ["Tray 1", "Tray 2", "Tray 3", "Tray 4", "Manual Feed"]
        return []


def test_get_printer_preferences_prefers_richer_tray_list(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWin32PrintLimitedPort()
    monkeypatch.setattr(win_mod, "win32print", fake)

    driver = win_mod.WindowsPrinterDriver()
    prefs = driver.get_printer_preferences("Printer A")

    tray_options = prefs.get("paper_tray_options")
    assert isinstance(tray_options, list)
    assert len(tray_options) == 5
    assert tray_options[-1] == {"code": "5", "label": "Manual Feed"}


class _FakeWin32PrintUserDefaults(_FakeWin32Print):
    def __init__(self) -> None:
        super().__init__()
        self._global_devmode = _FakeDevMode()
        self._user_devmode = _FakeDevMode()
        self._document_color: int | None = 1
        self._persisted_user_color: int | None = None

    def GetPrinter(self, handle, level: int):
        _ = handle
        self._calls.append(("GetPrinter", level))
        if int(level) == 9:
            return {"pDevMode": self._user_devmode}
        if int(level) == 8:
            return {"pDevMode": self._global_devmode}
        return {"pDevMode": self._global_devmode, "pPortName": "WSD-PORT"}

    def DocumentProperties(self, hwnd, handle, printer_name, out_devmode, in_devmode, flags):
        _ = (hwnd, handle, printer_name, in_devmode, flags)
        self._calls.append(("DocumentProperties", printer_name))
        if self._document_color is not None:
            out_devmode.Color = self._document_color
        return 1

    def SetPrinter(self, handle, level, info, command) -> None:
        _ = (handle, command)
        self._calls.append(("SetPrinter", level))
        if int(level) == 9:
            self._user_devmode = _clone_devmode(info["pDevMode"])
            if self._persisted_user_color is not None:
                self._user_devmode.Color = self._persisted_user_color
            return
        raise RuntimeError("(5, 'SetPrinter', 'Access is denied.')")


def test_get_printer_preferences_prefers_user_defaults_for_color_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeWin32PrintUserDefaults()
    fake._global_devmode.Color = 2
    fake._user_devmode.Color = 1
    monkeypatch.setattr(win_mod, "win32print", fake)

    driver = win_mod.WindowsPrinterDriver()
    prefs = driver.get_printer_preferences("Printer A")

    assert prefs.get("color_mode") == "grayscale"


def test_open_printer_properties_reloads_user_defaults_after_color_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeWin32PrintUserDefaults()
    fake._global_devmode.Color = 2
    fake._user_devmode.Color = 2
    fake._document_color = None
    fake._persisted_user_color = 1
    monkeypatch.setattr(win_mod, "win32print", fake)

    driver = win_mod.WindowsPrinterDriver()
    prefs = driver.open_printer_properties("Printer A")

    assert prefs.get("color_mode") == "grayscale"


class _FakeWin32PrintCancel(_FakeWin32Print):
    def DocumentProperties(self, hwnd, handle, printer_name, out_devmode, in_devmode, flags):
        _ = (hwnd, handle, printer_name, out_devmode, in_devmode, flags)
        self._calls.append(("DocumentProperties", printer_name))
        return 2


def test_open_printer_properties_cancel_returns_none_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeWin32PrintCancel()
    monkeypatch.setattr(win_mod, "win32print", fake)

    driver = win_mod.WindowsPrinterDriver()
    prefs = driver.open_printer_properties("Printer A")

    assert prefs is None
    assert ("SetPrinter", 9) not in fake._calls
