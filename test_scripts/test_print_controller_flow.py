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
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import controller.pdf_controller as pdf_controller_module
from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from src.printing.base_driver import PrinterDevice, PrintJobOptions, PrintJobResult
from src.printing.errors import PrintHelperTerminatedError
from src.printing.messages import (
    PRINT_CLOSING_MESSAGE,
    PRINT_STALLED_MESSAGE,
    PRINT_STATUS_MESSAGE,
    PRINT_SUBMITTING_MESSAGE,
    PRINT_TERMINATE_BUTTON_TEXT,
)
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
        raise AssertionError(f"print_pdf_bytes should not run in these controller tests: {len(pdf_bytes)}, {options}")


class _CancelDialog:
    instances: list[_CancelDialog] = []

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
    instances: list[_AcceptDialog] = []

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
        self.cancel_button_text = ""
        self.cancel_callback = None

    def setWindowTitle(self, _title: str) -> None:
        return None

    def setWindowModality(self, _modality) -> None:
        return None

    def setCancelButton(self, _button) -> None:
        return None

    def setCancelButtonText(self, text: str) -> None:
        self.cancel_button_text = text

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

    @property
    def canceled(self):
        class _SignalProxy:
            def __init__(self, outer) -> None:
                self._outer = outer

            def connect(self, callback) -> None:
                self._outer.cancel_callback = callback

        return _SignalProxy(self)


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


def test_print_document_runs_in_background_and_defers_close_until_helper_finishes(monkeypatch) -> None:
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
        capture_started = threading.Event()
        allow_capture_finish = threading.Event()
        runner_started = threading.Event()
        progress_thread_ids: list[int] = []
        runner_thread_ids: list[int] = []

        class _FakeRunner(QObject):
            progress = Signal(str)
            stalled = Signal()
            succeeded = Signal(object)
            failed = Signal(object)
            finished = Signal()
            raw_message = Signal(str)

            instances: list[_FakeRunner] = []

            def __init__(self, job, *_args, **_kwargs) -> None:
                super().__init__()
                self.job = job
                runner_thread_ids.append(threading.get_ident())
                self.started = False
                self.terminated = False
                self.__class__.instances.append(self)

            def start(self) -> None:
                self.started = True
                runner_started.set()
                self.progress.emit(PRINT_SUBMITTING_MESSAGE)

            def terminate(self) -> None:
                self.terminated = True

        def _blocking_capture_print_input_pdf_bytes() -> bytes:
            capture_started.set()
            assert threading.get_ident() != main_thread_id
            assert allow_capture_finish.wait(2.0), "worker thread never received release for PDF capture"
            return b"%PDF-1.4 captured input"

        try:
            controller.print_dispatcher = _FakePrintDispatcher()
            monkeypatch.setattr(model, "capture_print_input_pdf_bytes", _blocking_capture_print_input_pdf_bytes)
            monkeypatch.setattr(pdf_controller_module, "UnifiedPrintDialog", _AcceptDialog)
            monkeypatch.setattr(pdf_controller_module, "QProgressDialog", _FakeProgressDialog, raising=False)
            monkeypatch.setattr(pdf_controller_module, "PrintSubprocessRunner", _FakeRunner, raising=False)
            monkeypatch.setattr(pdf_controller_module, "show_error", lambda _parent, message: errors.append(message))
            original_update_print_progress_dialog = controller._update_print_progress_dialog
            monkeypatch.setattr(
                controller,
                "_update_print_progress_dialog",
                lambda label_text: (
                    progress_thread_ids.append(threading.get_ident()),
                    original_update_print_progress_dialog(label_text),
                )[-1],
            )
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
            assert view.status_bar.currentMessage() == PRINT_STATUS_MESSAGE
            assert _pump_until(app, capture_started.is_set), "PDF capture never started"

            close_event = _FakeCloseEvent()
            controller.handle_app_close(close_event)
            assert close_event.ignored is True
            assert close_event.accepted is False
            assert view.status_bar.currentMessage() == PRINT_CLOSING_MESSAGE
            assert view.isVisible() is True

            allow_capture_finish.set()
            assert _pump_until(app, runner_started.is_set), "print helper runner never started"
            runner = _FakeRunner.instances[-1]
            assert runner.started is True
            assert runner_thread_ids == [main_thread_id]
            assert _pump_until(app, lambda: controller._print_thread is None), "preparation worker thread never finished"
            assert progress_thread_ids
            assert all(thread_id == main_thread_id for thread_id in progress_thread_ids)

            controller._on_print_submission_succeeded(
                PrintJobResult(
                    success=True,
                    route="print-helper",
                    message="Submitted 1 page(s) to printer.",
                    job_id="job-1",
                )
            )
            controller._on_print_runner_finished()
            assert _pump_until(app, lambda: not view.isVisible()), "view did not auto-close after print completion"

            assert errors == []
            assert info_calls == []
            assert controller._print_progress_dialog is None
            assert view.status_bar.currentMessage() == baseline_status
        finally:
            allow_capture_finish.set()
            _AcceptDialog.instances.clear()
            _FakeRunner.instances.clear()
            if view.isVisible():
                view.close()
            model.close()


def test_stalled_print_helper_can_be_terminated_without_closing_main_window(monkeypatch) -> None:
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

        errors: list[str] = []
        info_calls: list[tuple[str, str]] = []

        class _FakeRunner(QObject):
            progress = Signal(str)
            stalled = Signal()
            succeeded = Signal(object)
            failed = Signal(object)
            finished = Signal()
            raw_message = Signal(str)

            instances: list[_FakeRunner] = []

            def __init__(self, job, *_args, **_kwargs) -> None:
                super().__init__()
                self.job = job
                self.started = False
                self.terminated = False
                self.__class__.instances.append(self)

            def start(self) -> None:
                self.started = True
                self.progress.emit(PRINT_SUBMITTING_MESSAGE)

            def terminate(self) -> None:
                self.terminated = True

        try:
            controller.print_dispatcher = _FakePrintDispatcher()
            monkeypatch.setattr(pdf_controller_module, "UnifiedPrintDialog", _AcceptDialog)
            monkeypatch.setattr(pdf_controller_module, "QProgressDialog", _FakeProgressDialog, raising=False)
            monkeypatch.setattr(pdf_controller_module, "PrintSubprocessRunner", _FakeRunner, raising=False)
            monkeypatch.setattr(pdf_controller_module, "show_error", lambda _parent, message: errors.append(message))
            monkeypatch.setattr(
                pdf_controller_module.QMessageBox,
                "information",
                lambda _parent, title, message: info_calls.append((title, message)),
            )

            baseline_status = view.status_bar.currentMessage()
            controller.print_document()

            assert _pump_until(app, lambda: bool(_FakeRunner.instances)), "runner was not created"
            runner = _FakeRunner.instances[-1]
            assert runner.started is True

            controller._on_print_submission_stalled()
            app.processEvents()

            assert controller._print_progress_dialog is not None
            assert controller._print_progress_dialog.label_text == PRINT_STALLED_MESSAGE
            assert controller._print_progress_dialog.cancel_button_text == PRINT_TERMINATE_BUTTON_TEXT
            assert view.status_bar.currentMessage() == PRINT_STALLED_MESSAGE

            controller._terminate_active_print_submission()
            assert runner.terminated is True

            controller._on_print_submission_failed(PrintHelperTerminatedError("列印背景工作已終止"))
            controller._on_print_runner_finished()
            assert _pump_until(app, lambda: controller._print_progress_dialog is None), "print UI never cleaned up"

            assert errors == []
            assert info_calls == []
            assert view.isVisible() is True
            assert view.status_bar.currentMessage() == baseline_status
        finally:
            _AcceptDialog.instances.clear()
            _FakeRunner.instances.clear()
            if view.isVisible():
                view.close()
            model.close()


def test_terminate_active_print_submission_handles_reentrant_runner_cleanup(monkeypatch) -> None:
    _ensure_app()
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller

    class _FakeRunner:
        def __init__(self) -> None:
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

    try:
        runner = _FakeRunner()
        controller._print_runner = runner
        monkeypatch.setattr(controller, "_set_print_status_message", lambda _message: None)
        monkeypatch.setattr(
            controller,
            "_update_print_progress_dialog",
            lambda _message: setattr(controller, "_print_runner", None),
        )

        controller._terminate_active_print_submission()

        assert runner.terminated is False
        assert controller._print_runner is None
    finally:
        view.close()
        model.close()
