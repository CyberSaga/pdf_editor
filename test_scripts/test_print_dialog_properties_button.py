# -*- coding: utf-8 -*-
"""Regression tests for print dialog native printer properties button."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import fitz
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrinterDevice
from src.printing.print_dialog import UnifiedPrintDialog


_OPEN_RESULT_UNSET = object()


class _FakeDispatcher:
    def __init__(self, supports_properties: bool) -> None:
        self._supports_properties = supports_properties
        self.opened_for: list[str] = []
        self.printer_preferences: dict[str, object] = {}
        self.printer_preferences_by_name: dict[str, dict[str, object]] = {}
        self.open_printer_properties_result: object = _OPEN_RESULT_UNSET

    def get_default_printer(self) -> str | None:
        return "Printer A"

    def resolve_page_indices_for_count(self, total_pages: int, options) -> list[int]:
        _ = options
        if total_pages <= 0:
            return []
        return [0]

    def supports_printer_properties_dialog(self) -> bool:
        return self._supports_properties

    def open_printer_properties(self, printer_name: str):
        self.opened_for.append(printer_name)
        if self.open_printer_properties_result is not _OPEN_RESULT_UNSET:
            return self.open_printer_properties_result
        if printer_name in self.printer_preferences_by_name:
            return dict(self.printer_preferences_by_name[printer_name])
        return dict(self.printer_preferences)

    def get_printer_preferences(self, printer_name: str) -> dict[str, object]:
        if printer_name in self.printer_preferences_by_name:
            return dict(self.printer_preferences_by_name[printer_name])
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
            effective = dialog._build_effective_options()
            submission = dialog._build_submission_options()
            assert effective.paper_size == "letter"
            assert effective.duplex == "long"
            assert effective.color_mode == "grayscale"
            assert effective.override_fields == set()
            assert submission.override_fields == set()
            assert submission.paper_tray == "auto"
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
            assert dialog._build_submission_options().paper_tray == "auto"
        finally:
            dialog.close()


def test_user_changed_hardware_field_marks_only_that_override() -> None:
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
            duplex_idx = dialog.duplex_combo.findData("short")
            assert duplex_idx >= 0
            dialog.duplex_combo.setCurrentIndex(duplex_idx)

            effective = dialog._build_effective_options()
            submission = dialog._build_submission_options()
            assert effective.paper_size == "letter"
            assert effective.orientation == "landscape"
            assert effective.duplex == "short"
            assert effective.color_mode == "grayscale"
            assert submission.override_fields == {"duplex"}
        finally:
            dialog.close()


def test_opening_properties_resets_touched_overrides() -> None:
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
            color_idx = dialog.color_combo.findData("color")
            assert color_idx >= 0
            dialog.color_combo.setCurrentIndex(color_idx)
            assert dialog._build_submission_options().override_fields == {"color_mode"}

            dispatcher.printer_preferences = {
                "paper_size": "a4",
                "orientation": "portrait",
                "duplex": "none",
                "color_mode": "grayscale",
            }
            dialog.printer_properties_btn.click()

            submission = dialog._build_submission_options()
            assert submission.paper_size == "a4"
            assert submission.orientation == "portrait"
            assert submission.duplex == "none"
            assert submission.color_mode == "grayscale"
            assert submission.override_fields == set()
        finally:
            dialog.close()


def test_properties_cancel_keeps_current_ui_and_touched_state() -> None:
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
        }
        dispatcher.open_printer_properties_result = None
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
            duplex_idx = dialog.duplex_combo.findData("short")
            assert duplex_idx >= 0
            dialog.duplex_combo.setCurrentIndex(duplex_idx)
            assert dialog.color_combo.currentData() == "grayscale"
            assert dialog._build_submission_options().override_fields == {"duplex"}

            dialog.printer_properties_btn.click()

            assert dialog.color_combo.currentData() == "grayscale"
            assert dialog._build_submission_options().override_fields == {"duplex"}
        finally:
            dialog.close()


def test_driver_private_properties_use_system_color_state_in_ui() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=True)
        dispatcher.printer_preferences = {
            "paper_size": "a4",
            "orientation": "portrait",
            "duplex": "long",
            "color_mode": "color",
            "paper_tray": "15",
        }
        dispatcher.open_printer_properties_result = {
            "paper_size": "a4",
            "orientation": "portrait",
            "duplex": "long",
            "color_mode": "color",
            "paper_tray": "15",
            "opaque_fields": ["color_mode", "paper_tray"],
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
            assert dialog.color_combo.currentData() == "system"

            submission = dialog._build_submission_options()
            assert submission.color_mode == "system"
            assert submission.override_fields == set()

            grayscale_idx = dialog.color_combo.findData("grayscale")
            assert grayscale_idx >= 0
            dialog.color_combo.setCurrentIndex(grayscale_idx)

            submission = dialog._build_submission_options()
            assert submission.color_mode == "grayscale"
            assert submission.override_fields == {"color_mode"}
        finally:
            dialog.close()


def test_switching_printers_resets_touched_overrides_and_loads_new_defaults() -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)
        dispatcher = _FakeDispatcher(supports_properties=True)
        dispatcher.printer_preferences_by_name = {
            "Printer A": {
                "paper_size": "letter",
                "orientation": "landscape",
                "duplex": "long",
                "color_mode": "grayscale",
            },
            "Printer B": {
                "paper_size": "a4",
                "orientation": "portrait",
                "duplex": "none",
                "color_mode": "color",
            },
        }
        printers = [
            PrinterDevice(name="Printer A", is_default=True, status="ready"),
            PrinterDevice(name="Printer B", is_default=False, status="ready"),
        ]

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
            paper_idx = dialog.paper_combo.findData("legal")
            assert paper_idx >= 0
            dialog.paper_combo.setCurrentIndex(paper_idx)
            assert dialog._build_submission_options().override_fields == {"paper_size"}

            printer_b_idx = dialog.printer_combo.findData("Printer B")
            assert printer_b_idx >= 0
            dialog.printer_combo.setCurrentIndex(printer_b_idx)

            submission = dialog._build_submission_options()
            assert submission.paper_size == "a4"
            assert submission.orientation == "portrait"
            assert submission.duplex == "none"
            assert submission.color_mode == "color"
            assert submission.override_fields == set()
        finally:
            dialog.close()


def test_preview_errors_are_handled_without_raising_from_ui_path() -> None:
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
            custom_idx = dialog.range_mode_combo.findData("custom")
            assert custom_idx >= 0
            dialog.range_mode_combo.setCurrentIndex(custom_idx)
            dialog.custom_range_edit.setText("")
            dialog._page_indices = [0]

            dialog._safe_render_preview()

            assert dialog.preview_message_label.text()
            assert dialog.page_list.count() == 0
        finally:
            dialog.close()


def test_preview_provider_supports_dialog_without_temp_pdf_path() -> None:
    _ensure_app()
    dispatcher = _FakeDispatcher(supports_properties=False)
    printers = [PrinterDevice(name="Printer A", is_default=True, status="ready")]

    def _preview_provider(page_index: int, dpi: int) -> QImage:
        _ = (page_index, dpi)
        image = QImage(120, 160, QImage.Format_RGB888)
        image.fill(0xFFFFFF)
        return image

    dialog = UnifiedPrintDialog(
        parent=None,
        dispatcher=dispatcher,
        printers=printers,
        pdf_path="",
        total_pages=1,
        current_page=1,
        job_name="test_job",
        preview_page_provider=_preview_provider,
    )
    try:
        dialog._page_indices = [0]
        dialog._safe_render_preview()
        pixmap = dialog.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        assert dialog.preview_message_label.text() == ""
    finally:
        dialog.close()

