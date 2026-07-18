"""Tests: print dialog remembers user-modified settings between prints."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from src.printing.base_driver import PrinterDevice
from src.printing.print_dialog import UnifiedPrintDialog


class _FakeDispatcher:
    def __init__(self) -> None:
        self.printer_preferences: dict[str, object] = {}

    def get_default_printer(self) -> str | None:
        return "FakePrinter"

    def resolve_page_indices_for_count(self, total_pages, options) -> list[int]:
        return list(range(max(0, total_pages)))

    def supports_printer_properties_dialog(self) -> bool:
        return False

    def get_printer_preferences(self, printer_name: str) -> dict[str, object]:
        return dict(self.printer_preferences)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


_DEFAULT_PRINTERS = [PrinterDevice(name="FakePrinter", is_default=True, status="ready")]


def _make_dialog(dispatcher=None, printers=None, pdf_path="", **kwargs):
    _ensure_app()
    dispatcher = dispatcher or _FakeDispatcher()
    printers = printers or list(_DEFAULT_PRINTERS)
    dlg = UnifiedPrintDialog(
        parent=None,
        dispatcher=dispatcher,
        printers=printers,
        pdf_path=pdf_path,
        total_pages=3,
        current_page=1,
        job_name="test",
        **kwargs,
    )
    return dlg


class TestPrintDialogSettingsPersistence:
    """The dialog must accept a previous_settings dict and restore user-chosen values."""

    def test_dialog_accepts_previous_settings_kwarg(self):
        prev = {
            "copies": 5,
            "dpi": 150,
            "collate": False,
            "duplex": "long",
            "color_mode": "grayscale",
            "scale_mode": "actual",
            "scale_percent": 75,
            "page_subset": "odd",
            "reverse_order": True,
        }
        dlg = _make_dialog(previous_settings=prev)
        assert dlg.copies_spin.value() == 5
        assert dlg.dpi_spin.value() == 150
        assert dlg.collate_cb.isChecked() is False
        assert dlg.duplex_combo.currentData() == "long"
        assert dlg.color_combo.currentData() == "grayscale"
        assert dlg.scale_mode_combo.currentData() == "actual"
        assert dlg.scale_percent_spin.value() == 75
        assert dlg.page_subset_combo.currentData() == "odd"
        assert dlg.reverse_cb.isChecked() is True
        dlg.close()

    def test_dialog_without_previous_settings_uses_defaults(self):
        dlg = _make_dialog()
        assert dlg.copies_spin.value() == 1
        assert dlg.dpi_spin.value() == 300
        assert dlg.collate_cb.isChecked() is True
        dlg.close()

    def test_capture_user_settings_returns_current_values(self):
        dlg = _make_dialog()
        dlg.copies_spin.setValue(3)
        dlg.dpi_spin.setValue(200)
        dlg.collate_cb.setChecked(False)
        captured = dlg.capture_user_settings()
        assert captured["copies"] == 3
        assert captured["dpi"] == 200
        assert captured["collate"] is False
        dlg.close()

    def test_previous_settings_override_printer_preferences(self):
        disp = _FakeDispatcher()
        disp.printer_preferences = {"duplex": "short", "dpi": 600}
        prev = {"duplex": "long", "dpi": 150}
        dlg = _make_dialog(dispatcher=disp, previous_settings=prev)
        assert dlg.duplex_combo.currentData() == "long"
        assert dlg.dpi_spin.value() == 150
        dlg.close()

    def test_previous_settings_win_over_printer_preferences_in_effective_options(self):
        # CRITICAL: restoring a hardware field via _apply_previous_settings must mark
        # it as "touched" (by firing the wired _on_hardware_field_changed handler) so
        # _resolve_hardware_values() actually prefers the restored value over the
        # printer's stored preference. The combo showing the right value is not
        # enough -- _build_effective_options() must resolve to it too.
        disp = _FakeDispatcher()
        disp.printer_preferences = {"duplex": "short"}
        prev = {"duplex": "long"}
        dlg = _make_dialog(dispatcher=disp, previous_settings=prev)
        assert dlg._build_effective_options().duplex == "long"
        dlg.close()

    def test_previous_settings_restoring_custom_scale_enables_percent_spin(self):
        # _apply_previous_settings must run after _wire_signals so that restoring
        # scale_mode="custom" fires _on_scale_mode_changed, which enables the
        # (otherwise disabled-by-default) scale_percent_spin.
        prev = {"scale_mode": "custom", "scale_percent": 75}
        dlg = _make_dialog(previous_settings=prev)
        assert dlg.scale_percent_spin.isEnabled() is True
        dlg.close()

    def test_previous_settings_restores_printer_selection_before_other_fields(self):
        # Restoring the printer selection must happen first: switching printers
        # clears _touched_hardware_fields and reloads that printer's preferences,
        # so if it happened after restoring duplex/color_mode, those restored
        # values would be wiped out.
        printers = [
            PrinterDevice(name="Printer A", is_default=True, status="ready"),
            PrinterDevice(name="Printer B", is_default=False, status="ready"),
        ]
        disp = _FakeDispatcher()
        disp.printer_preferences = {"duplex": "short"}
        prev = {"printer_name": "Printer B", "duplex": "long"}
        dlg = _make_dialog(dispatcher=disp, printers=printers, previous_settings=prev)
        assert dlg.printer_combo.currentData() == "Printer B"
        assert dlg._build_effective_options().duplex == "long"
        dlg.close()

    def test_capture_user_settings_includes_paper_size_and_orientation(self):
        dlg = _make_dialog()
        a4_idx = dlg.paper_combo.findData("a4")
        landscape_idx = dlg.orientation_combo.findData("landscape")
        assert a4_idx >= 0
        assert landscape_idx >= 0
        dlg.paper_combo.setCurrentIndex(a4_idx)
        dlg.orientation_combo.setCurrentIndex(landscape_idx)
        captured = dlg.capture_user_settings()
        assert captured["paper_size"] == "a4"
        assert captured["orientation"] == "landscape"
        dlg.close()

    def test_previous_settings_restores_paper_size_and_orientation(self):
        prev = {"paper_size": "a4", "orientation": "landscape"}
        dlg = _make_dialog(previous_settings=prev)
        assert dlg.paper_combo.currentData() == "a4"
        assert dlg.orientation_combo.currentData() == "landscape"
        dlg.close()


class TestPrintCoordinatorRememberSettings:
    """PrintCoordinator must store settings from a successful print and replay them."""

    def test_coordinator_stores_last_settings_after_print(self):
        from controller.print_coordinator import PrintCoordinator

        mock_ctrl = MagicMock()
        coord = PrintCoordinator(mock_ctrl)
        assert coord._last_print_settings is None
        coord._last_print_settings = {"copies": 7}
        assert coord._last_print_settings == {"copies": 7}
