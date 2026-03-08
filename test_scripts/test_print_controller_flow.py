# -*- coding: utf-8 -*-
"""Controller-level print flow regressions."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import fitz
from PySide6.QtWidgets import QApplication, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import controller.pdf_controller as pdf_controller_module
from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from src.printing.base_driver import PrintJobOptions, PrintJobResult, PrinterDevice
from view.pdf_view import PDFView


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pump_until(app: QApplication, predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


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
        raise AssertionError(f"print_pdf_file should not run in these controller tests: {pdf_path}, {options}")

    def print_pdf_bytes(self, pdf_bytes: bytes, options):
        raise AssertionError(f"print_pdf_bytes should be stubbed by the individual test: {len(pdf_bytes)}, {options}")


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


class _AcceptDialog:
    instances: list["_AcceptDialog"] = []

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
        return int(QDialog.DialogCode.Accepted)

    def result_data(self):
        return SimpleNamespace(
            options=PrintJobOptions(
                printer_name="Printer A",
                job_name="controller print flow",
            )
        )


class _FakeProgressDialog:
    def __init__(self, label_text: str, _cancel_text: str, _minimum: int, _maximum: int, _parent) -> None:
        self.label_text = label_text
        self.visible = False

    def setWindowTitle(self, _title: str) -> None:
        return None

    def setWindowModality(self, _modality) -> None:
        return None

    def setCancelButton(self, _button) -> None:
        return None

    def setMinimumDuration(self, _duration: int) -> None:
        return None

    def setAutoClose(self, _auto_close: bool) -> None:
        return None

    def setAutoReset(self, _auto_reset: bool) -> None:
        return None

    def setLabelText(self, label_text: str) -> None:
        self.label_text = label_text

    def show(self) -> None:
        self.visible = True

    def raise_(self) -> None:
        return None

    def isVisible(self) -> bool:
        return self.visible

    def close(self) -> None:
        self.visible = False

    def deleteLater(self) -> None:
        return None


class _FakeCloseEvent:
    def __init__(self) -> None:
        self.accepted = False
        self.ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


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

        def _unexpected_snapshot(*_args, **_kwargs) -> bytes:
            nonlocal snapshot_called
            snapshot_called = True
            raise AssertionError("print snapshot capture should not run before the user accepts printing")

        monkeypatch.setattr(model, "build_print_snapshot", _unexpected_snapshot)
        monkeypatch.setattr(model, "capture_print_input_pdf_bytes", _unexpected_snapshot, raising=False)
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


def test_print_document_runs_in_background_and_defers_close_until_submission_finishes(monkeypatch) -> None:
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)

        model = PDFModel()
        view = PDFView()
        view.show()
        controller = PDFController(model, view)
        view.controller = controller
        model.open_pdf(str(pdf_path))

        info_calls: list[tuple[str, str]] = []
        errors: list[str] = []
        main_thread_id = threading.get_ident()
        snapshot_started = threading.Event()
        allow_snapshot_finish = threading.Event()
        submit_started = threading.Event()
        allow_submit_finish = threading.Event()
        snapshot_thread_ids: list[int] = []
        submit_thread_ids: list[int] = []

        class _BlockingPrintDispatcher(_FakePrintDispatcher):
            def print_pdf_bytes(self, pdf_bytes: bytes, options) -> PrintJobResult:
                submit_thread_ids.append(threading.get_ident())
                submit_started.set()
                assert threading.get_ident() != main_thread_id
                assert isinstance(pdf_bytes, (bytes, bytearray))
                assert options.printer_name == "Printer A"
                assert allow_submit_finish.wait(2.0), "worker thread never received release for print submission"
                return PrintJobResult(
                    success=True,
                    route="worker-thread",
                    message="Submitted 1 page(s) to printer.",
                    job_id="job-1",
                )

        def _unexpected_build_print_snapshot() -> bytes:
            raise AssertionError("legacy synchronous build_print_snapshot() should not run on the UI thread")

        def _blocking_build_snapshot_from_source(pdf_bytes: bytes, watermarks: list[dict]) -> bytes:
            snapshot_thread_ids.append(threading.get_ident())
            snapshot_started.set()
            assert threading.get_ident() != main_thread_id
            assert isinstance(pdf_bytes, (bytes, bytearray))
            assert isinstance(watermarks, list)
            assert allow_snapshot_finish.wait(2.0), "worker thread never received release for snapshot generation"
            return bytes(pdf_bytes)

        try:
            controller.print_dispatcher = _BlockingPrintDispatcher()
            monkeypatch.setattr(model, "build_print_snapshot", _unexpected_build_print_snapshot)
            monkeypatch.setattr(pdf_controller_module, "UnifiedPrintDialog", _AcceptDialog)
            monkeypatch.setattr(pdf_controller_module, "QProgressDialog", _FakeProgressDialog, raising=False)
            monkeypatch.setattr(pdf_controller_module, "build_print_snapshot_from_source", _blocking_build_snapshot_from_source, raising=False)
            monkeypatch.setattr(pdf_controller_module, "show_error", lambda _parent, message: errors.append(message))
            monkeypatch.setattr(
                pdf_controller_module.QMessageBox,
                "information",
                lambda _parent, title, message: info_calls.append((title, message)),
            )

            baseline_status = view.status_bar.currentMessage()

            started_at = time.perf_counter()
            controller.print_document()
            elapsed = time.perf_counter() - started_at

            assert elapsed < 0.2, f"print_document blocked the UI thread for {elapsed:.3f}s"
            assert controller._print_progress_dialog is not None
            assert controller._print_progress_dialog.isVisible()
            assert view.status_bar.currentMessage() == "列印中..."
            assert _pump_until(app, snapshot_started.is_set), "snapshot worker never started"
            assert snapshot_thread_ids and snapshot_thread_ids[-1] != main_thread_id

            close_event = _FakeCloseEvent()
            controller.handle_app_close(close_event)
            assert close_event.ignored is True
            assert close_event.accepted is False
            assert view.status_bar.currentMessage() == "正在完成最後工作，請稍候..."
            assert view.isVisible() is True

            allow_snapshot_finish.set()
            assert _pump_until(app, submit_started.is_set), "print submission worker never reached dispatcher"
            assert submit_thread_ids and submit_thread_ids[-1] != main_thread_id

            allow_submit_finish.set()
            assert _pump_until(app, lambda: controller._print_thread is None), "print worker thread never finished"
            assert _pump_until(app, lambda: not view.isVisible()), "view did not auto-close after print completion"

            assert errors == []
            assert info_calls == []
            assert controller._print_progress_dialog is None
            assert view.status_bar.currentMessage() == baseline_status
        finally:
            allow_snapshot_finish.set()
            allow_submit_finish.set()
            _AcceptDialog.instances.clear()
            if view.isVisible():
                view.close()
            model.close()
