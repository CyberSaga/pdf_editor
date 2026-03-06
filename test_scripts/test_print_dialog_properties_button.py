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
            assert dialog.inherited_properties_panel.isHidden()
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
            "paper_tray": "2",
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
            assert not hasattr(dialog, "paper_tray_combo")
            assert dialog._build_options().paper_tray == "auto"
        finally:
            dialog.close()


def test_properties_tray_preferences_are_inherited_without_dialog_field() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=True)
        dispatcher.printer_preferences = {
            "paper_tray": "15",
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
            assert not hasattr(dialog, "paper_tray_combo")
            assert dialog._build_options().paper_tray == "auto"
            assert dialog.inherited_tray_edit.text() == "15"
        finally:
            dialog.close()


def test_inherited_properties_panel_is_collapsed_and_expandable() -> None:
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
            assert dialog.inherited_properties_panel.isHidden()
            dialog.inherited_properties_toggle.click()
            assert not dialog.inherited_properties_panel.isHidden()
            assert dialog.inherited_properties_toggle.text() == "隱藏系統屬性"
            dialog.inherited_properties_toggle.click()
            assert dialog.inherited_properties_panel.isHidden()
            assert dialog.inherited_properties_toggle.text() == "顯示系統屬性"
            assert dialog.inherited_tray_edit.isReadOnly()
        finally:
            dialog.close()


def test_inherited_tray_readonly_shows_label_when_options_available() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=True)
        dispatcher.printer_preferences = {
            "paper_tray": "5",
            "paper_tray_options": [
                {"code": "1", "label": "紙盤1"},
                {"code": "5", "label": "紙盤5(手送紙盤)"},
            ],
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
            assert dialog.inherited_tray_edit.text() == "紙盤5(手送紙盤) (5)"
        finally:
            dialog.close()
