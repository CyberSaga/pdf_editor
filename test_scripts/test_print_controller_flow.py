# -*- coding: utf-8 -*-
"""Controller-level print flow regressions."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import fitz
from PySide6.QtWidgets import QApplication, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import controller.pdf_controller as pdf_controller_module
from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from src.printing.base_driver import PrinterDevice
from view.pdf_view import PDFView


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_single_page_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "controller print flow", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


class _FakePrintDispatcher:
    def list_printers(self):
        return [PrinterDevice(name="Printer A", is_default=True, status="ready")]

    def get_printer_status(self, printer_name: str) -> str:
        _ = printer_name
        return "ready"

    def print_pdf_file(self, pdf_path: str, options):
        raise AssertionError(f"print_pdf_file should not run on dialog cancel: {pdf_path}, {options}")


class _CancelDialog:
    instances: list["_CancelDialog"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self._visible = False
        self.__class__.instances.append(self)

    def isVisible(self) -> bool:
        return self._visible

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:
        return None

    def exec(self) -> int:
        return int(QDialog.DialogCode.Rejected)

    def result_data(self):
        return None


def test_print_document_defers_snapshot_until_user_accepts(monkeypatch) -> None:
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)

        model = PDFModel()
        view = PDFView()
        controller = PDFController(model, view)
        view.controller = controller
        controller.print_dispatcher = _FakePrintDispatcher()
        model.open_pdf(str(pdf_path))

        snapshot_called = False

        def _unexpected_snapshot() -> bytes:
            nonlocal snapshot_called
            snapshot_called = True
            raise AssertionError("build_print_snapshot should not run before the user accepts printing")

        monkeypatch.setattr(model, "build_print_snapshot", _unexpected_snapshot)
        monkeypatch.setattr(pdf_controller_module, "UnifiedPrintDialog", _CancelDialog)

        try:
            controller.print_document()

            assert _CancelDialog.instances, "print dialog should still open"
            dialog = _CancelDialog.instances[-1]
            assert dialog.kwargs["pdf_path"] == ""
            assert callable(dialog.kwargs["preview_page_provider"])
            assert snapshot_called is False
        finally:
            _CancelDialog.instances.clear()
            view.close()
            model.close()
