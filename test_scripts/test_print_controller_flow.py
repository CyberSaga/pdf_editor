# -*- coding: utf-8 -*-
"""Controller-level print flow regressions."""

from __future__ import annotations

import json
import os
import sys
import tempfile
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
from src.printing.base_driver import PrintJobOptions, PrinterDevice
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


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeQProcess:
    instances: list["_FakeQProcess"] = []

    class ProcessError:
        FailedToStart = 0

    class ExitStatus:
        NormalExit = 0
        CrashExit = 1

    def __init__(self, _parent=None) -> None:
        self.program = None
        self.arguments: list[str] = []
        self.started = False
        self._stdout_chunks: list[bytes] = []
        self._stderr_chunks: list[bytes] = []
        self.readyReadStandardOutput = _FakeSignal()
        self.readyReadStandardError = _FakeSignal()
        self.finished = _FakeSignal()
        self.errorOccurred = _FakeSignal()
        self.__class__.instances.append(self)

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = list(arguments)

    def start(self) -> None:
        self.started = True

    def readAllStandardOutput(self):
        payload = b"".join(self._stdout_chunks)
        self._stdout_chunks.clear()
        return payload

    def readAllStandardError(self):
        payload = b"".join(self._stderr_chunks)
        self._stderr_chunks.clear()
        return payload

    def push_stdout(self, payload: dict) -> None:
        self._stdout_chunks.append((json.dumps(payload) + "\n").encode("utf-8"))
        self.readyReadStandardOutput.emit()

    def push_stderr(self, text: str) -> None:
        self._stderr_chunks.append(text.encode("utf-8"))
        self.readyReadStandardError.emit()

    def finish(self, exit_code: int = 0, exit_status: int = 0) -> None:
        self.finished.emit(exit_code, exit_status)

    def deleteLater(self) -> None:
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
            raise AssertionError("capture_print_input_pdf_bytes should not run before the user accepts printing")

        monkeypatch.setattr(model, "capture_print_input_pdf_bytes", _unexpected_snapshot)
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


def test_print_document_launches_external_process_without_blocking_ui(monkeypatch) -> None:
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        _make_single_page_pdf(pdf_path)

        model = PDFModel()
        view = PDFView()
        controller = PDFController(model, view)
        view.controller = controller
        controller.print_dispatcher = _FakePrintDispatcher()
        model.open_pdf(str(pdf_path))

        info_calls: list[tuple[str, str]] = []

        def _snapshot_with_visible_progress() -> bytes:
            progress = getattr(controller, "_print_progress_dialog", None)
            assert progress is not None, "progress dialog should exist before snapshot build"
            assert progress.isVisible(), "progress dialog should be visible while snapshot is building"
            return b"%PDF-1.4 test payload"

        monkeypatch.setattr(model, "capture_print_input_pdf_bytes", _snapshot_with_visible_progress)
        monkeypatch.setattr(pdf_controller_module, "UnifiedPrintDialog", _AcceptDialog)
        monkeypatch.setattr(pdf_controller_module, "QProgressDialog", _FakeProgressDialog)
        monkeypatch.setattr(pdf_controller_module, "QProcess", _FakeQProcess)
        monkeypatch.setattr(pdf_controller_module, "show_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            pdf_controller_module.QMessageBox,
            "information",
            lambda _parent, title, message: info_calls.append((title, message)),
        )

        try:
            started_at = time.perf_counter()
            controller.print_document()
            elapsed = time.perf_counter() - started_at

            assert elapsed < 0.5, f"print_document blocked UI for {elapsed:.3f}s"
            assert controller._print_progress_dialog is not None
            assert controller._print_progress_dialog.isVisible()
            assert info_calls == []

            deadline = time.time() + 1.0
            while time.time() < deadline and not _FakeQProcess.instances:
                app.processEvents()
                time.sleep(0.01)

            assert _FakeQProcess.instances, "external print process was never launched"
            process = _FakeQProcess.instances[-1]
            assert process.started is True
            assert process.program == sys.executable
            assert process.arguments[:2] == ["-m", "src.printing.print_job_runner"]

            process.push_stdout({"type": "progress", "message": "正在送出列印工作，請稍候..."})
            app.processEvents()
            assert controller._print_progress_dialog.label_text == "正在送出列印工作，請稍候..."

            process.push_stdout(
                {
                    "type": "result",
                    "success": True,
                    "route": "external-process",
                    "message": "Submitted 1 page(s) to printer.",
                    "job_id": "job-1",
                }
            )
            process.finish(0, _FakeQProcess.ExitStatus.NormalExit)
            app.processEvents()

            assert info_calls == [("??", info_calls[0][1])]
            assert controller._print_progress_dialog is None
        finally:
            _AcceptDialog.instances.clear()
            _FakeQProcess.instances.clear()
            view.close()
            model.close()
