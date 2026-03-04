# -*- coding: utf-8 -*-
"""Regression tests for print dialog native printer properties button."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys

import fitz
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrinterDevice
from src.printing.print_dialog import UnifiedPrintDialog


class _FakeDispatcher:
    def __init__(self, supports_properties: bool) -> None:
        self._supports_properties = supports_properties
        self.opened_for: list[str] = []
        self.printer_preferences: dict[str, object] = {}

    def get_default_printer(self) -> str | None:
        return "Printer A"

    def resolve_page_indices_for_count(self, total_pages: int, options) -> list[int]:
        _ = options
        if total_pages <= 0:
            return []
        return [0]

    def supports_printer_properties_dialog(self) -> bool:
        return self._supports_properties

    def open_printer_properties(self, printer_name: str) -> dict[str, object]:
        self.opened_for.append(printer_name)
        return dict(self.printer_preferences)

    def get_printer_preferences(self, printer_name: str) -> dict[str, object]:
        _ = printer_name
        return dict(self.printer_preferences)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_single_page_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "print dialog test", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_properties_button_calls_dispatcher_when_supported() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=True)
        printers = [PrinterDevice(name="Printer A", is_default=True, status="ready")]

        dialog = UnifiedPrintDialog(
            parent=None,
            dispatcher=dispatcher,
            printers=printers,
            pdf_path=str(pdf_path),
            total_pages=1,
            current_page=1,
            job_name="test_job",
        )
        try:
            assert dialog.printer_properties_btn.isEnabled()
            dialog.printer_properties_btn.click()
            assert dispatcher.opened_for == ["Printer A"]
        finally:
            dialog.close()


def test_properties_button_disabled_when_not_supported() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=False)
        printers = [PrinterDevice(name="Printer A", is_default=True, status="ready")]

        dialog = UnifiedPrintDialog(
            parent=None,
            dispatcher=dispatcher,
            printers=printers,
            pdf_path=str(pdf_path),
            total_pages=1,
            current_page=1,
            job_name="test_job",
        )
        try:
            assert not dialog.printer_properties_btn.isEnabled()
            dialog.printer_properties_btn.click()
            assert dispatcher.opened_for == []
        finally:
            dialog.close()


def test_properties_button_syncs_dialog_fields_from_system_preferences() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=True)
        dispatcher.printer_preferences = {
            "paper_size": "letter",
            "orientation": "landscape",
            "duplex": "long",
            "color_mode": "grayscale",
            "dpi": 600,
            "copies": 3,
        }
        printers = [PrinterDevice(name="Printer A", is_default=True, status="ready")]

        dialog = UnifiedPrintDialog(
            parent=None,
            dispatcher=dispatcher,
            printers=printers,
            pdf_path=str(pdf_path),
            total_pages=1,
            current_page=1,
            job_name="test_job",
        )
        try:
            dialog.printer_properties_btn.click()
            assert dialog.paper_combo.currentData() == "letter"
            assert dialog.orientation_combo.currentData() == "landscape"
            assert dialog.duplex_combo.currentData() == "long"
            assert dialog.color_combo.currentData() == "grayscale"
            assert dialog.dpi_spin.value() == 600
            assert dialog.copies_spin.value() == 3
        finally:
            dialog.close()
