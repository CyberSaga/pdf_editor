# -*- coding: utf-8 -*-
"""Regression tests for Linux driver hardware override handling."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrintJobOptions
from src.printing.platforms.linux_driver import LinuxPrinterDriver


def test_to_cups_options_omits_hardware_defaults_when_not_overridden() -> None:
    options = PrintJobOptions(
        page_ranges="1-3",
        copies=2,
        collate=True,
        fit_to_page=True,
        duplex="long",
        color_mode="grayscale",
    )

    cups_options = LinuxPrinterDriver._to_cups_options(options)

    assert cups_options["page-ranges"] == "1-3"
    assert cups_options["copies"] == "2"
    assert cups_options["collate"] == "true"
    assert cups_options["fit-to-page"] == "true"
    assert "sides" not in cups_options
    assert "print-color-mode" not in cups_options
    assert "ColorModel" not in cups_options


def test_to_cups_options_includes_hardware_defaults_when_overridden() -> None:
    options = PrintJobOptions(
        duplex="long",
        color_mode="grayscale",
        override_fields={"duplex", "color_mode"},
    )

    cups_options = LinuxPrinterDriver._to_cups_options(options)

    assert cups_options["sides"] == "two-sided-long-edge"
    assert cups_options["print-color-mode"] == "monochrome"
    assert cups_options["ColorModel"] == "Gray"


def test_submit_via_lp_omits_hardware_options_when_not_overridden(monkeypatch, tmp_path) -> None:
    driver = LinuxPrinterDriver()
    captured_cmd: list[str] = []

    def _fake_which(name: str):
        return "/usr/bin/lp" if name == "lp" else None

    def _fake_run(cmd, capture_output, text, check):
        _ = (capture_output, text, check)
        captured_cmd.extend(cmd)

        class _Result:
            stdout = "request id is printer-123"

        return _Result()

    monkeypatch.setattr("src.printing.platforms.linux_driver.shutil.which", _fake_which)
    monkeypatch.setattr("src.printing.platforms.linux_driver.subprocess.run", _fake_run)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    result = driver._submit_via_lp(
        str(pdf_path),
        PrintJobOptions(
            printer_name="Printer A",
            page_ranges="2-4",
            copies=3,
            fit_to_page=True,
            duplex="short",
            color_mode="grayscale",
        ),
    )

    assert result.success is True
    assert captured_cmd[:5] == ["lp", "-n", "3", "-d", "Printer A"]
    assert "-P" in captured_cmd
    assert "-o" in captured_cmd
    assert "fit-to-page" in captured_cmd
    assert "sides=two-sided-short-edge" not in captured_cmd
    assert "ColorModel=Gray" not in captured_cmd


def test_submit_via_lp_includes_hardware_options_when_overridden(monkeypatch, tmp_path) -> None:
    driver = LinuxPrinterDriver()
    captured_cmd: list[str] = []

    def _fake_which(name: str):
        return "/usr/bin/lp" if name == "lp" else None

    def _fake_run(cmd, capture_output, text, check):
        _ = (capture_output, text, check)
        captured_cmd.extend(cmd)

        class _Result:
            stdout = "request id is printer-456"

        return _Result()

    monkeypatch.setattr("src.printing.platforms.linux_driver.shutil.which", _fake_which)
    monkeypatch.setattr("src.printing.platforms.linux_driver.subprocess.run", _fake_run)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    result = driver._submit_via_lp(
        str(pdf_path),
        PrintJobOptions(
            printer_name="Printer A",
            duplex="short",
            color_mode="grayscale",
            override_fields={"duplex", "color_mode"},
        ),
    )

    assert result.success is True
    assert "sides=two-sided-short-edge" in captured_cmd
    assert "ColorModel=Gray" in captured_cmd
