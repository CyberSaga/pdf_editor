# -*- coding: utf-8 -*-
"""Subprocess runner lifecycle tests."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrintJobOptions
from src.printing.errors import PrintHelperTerminatedError
from src.printing.helper_protocol import PrintHelperJob
from src.printing.subprocess_runner import PrintSubprocessRunner


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


class _FakeProcess(QObject):
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)

    instances: list["_FakeProcess"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        super().__init__()
        self.program = None
        self.arguments = None
        self.working_directory = None
        self.process_environment: dict[str, str] | None = None
        self._state = QProcess.ProcessState.NotRunning
        self._stdout = bytearray()
        self._stderr = bytearray()
        self.killed = False
        self.__class__.instances.append(self)

    def start(self, program: str, arguments: list[str]) -> None:
        self.program = program
        self.arguments = arguments
        self._state = QProcess.ProcessState.Running

    def state(self):
        return self._state

    def setWorkingDirectory(self, path: str) -> None:
        self.working_directory = path

    def setProcessEnvironment(self, env: QProcessEnvironment) -> None:
        self.process_environment = {key: env.value(key) for key in env.keys()}

    def kill(self) -> None:
        self.killed = True
        self._state = QProcess.ProcessState.NotRunning

    def readAllStandardOutput(self):
        data = bytes(self._stdout)
        self._stdout.clear()
        return data

    def readAllStandardError(self):
        data = bytes(self._stderr)
        self._stderr.clear()
        return data

    def push_stdout_event(self, payload: dict) -> None:
        self._stdout.extend((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self.readyReadStandardOutput.emit()

    def push_stderr_text(self, text: str) -> None:
        self._stderr.extend(text.encode("utf-8"))
        self.readyReadStandardError.emit()

    def emit_finished(self, exit_code: int = 0) -> None:
        self._state = QProcess.ProcessState.NotRunning
        self.finished.emit(exit_code, QProcess.ExitStatus.NormalExit)


def test_runner_emits_stalled_after_silence(tmp_path: Path) -> None:
    app = _ensure_app()
    job = PrintHelperJob(
        job_id="job-1",
        input_pdf_path=str(tmp_path / "input.pdf"),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A"),
    )

    stalled: list[bool] = []
    runner = PrintSubprocessRunner(
        job,
        process_factory=_FakeProcess,
        stall_timeout_ms=30,
        stall_check_interval_ms=10,
    )
    runner.stalled.connect(lambda: stalled.append(True))

    runner.start()

    assert _pump_until(app, lambda: bool(stalled)), "runner never emitted stalled"


def test_runner_maps_terminated_process_to_helper_terminated_error(tmp_path: Path) -> None:
    app = _ensure_app()
    job = PrintHelperJob(
        job_id="job-2",
        input_pdf_path=str(tmp_path / "input.pdf"),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A"),
    )

    failures: list[Exception] = []
    runner = PrintSubprocessRunner(
        job,
        process_factory=_FakeProcess,
        stall_timeout_ms=1000,
        stall_check_interval_ms=50,
    )
    runner.failed.connect(failures.append)

    runner.start()
    process = _FakeProcess.instances[-1]
    runner.terminate()
    process.emit_finished(exit_code=1)

    assert _pump_until(app, lambda: bool(failures)), "runner never emitted failure after termination"
    assert isinstance(failures[-1], PrintHelperTerminatedError)


def test_runner_logs_startup_error_and_uses_sys_executable(tmp_path: Path) -> None:
    app = _ensure_app()
    job = PrintHelperJob(
        job_id="job-3",
        input_pdf_path=str(tmp_path / "input.pdf"),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A"),
    )

    failures: list[Exception] = []
    runner = PrintSubprocessRunner(
        job,
        process_factory=_FakeProcess,
        stall_timeout_ms=1000,
        stall_check_interval_ms=50,
    )
    runner.failed.connect(failures.append)

    runner.start()
    process = _FakeProcess.instances[-1]
    assert process.program == sys.executable
    assert process.arguments is not None
    assert process.arguments[:2] == ["-m", "src.printing.helper_main"]
    assert process.working_directory == str(REPO_ROOT)
    assert process.process_environment is not None
    py_path = process.process_environment.get("PYTHONPATH", "")
    assert str(REPO_ROOT) in py_path.split(os.pathsep)

    process.push_stderr_text("failed to start helper")
    process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)

    assert _pump_until(app, lambda: bool(failures)), "runner never emitted startup failure"
    assert "failed to start helper" in str(failures[-1])


def test_runner_heartbeat_events_prevent_false_stall(tmp_path: Path) -> None:
    app = _ensure_app()
    job = PrintHelperJob(
        job_id="job-4",
        input_pdf_path=str(tmp_path / "input.pdf"),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A"),
    )

    stalled: list[bool] = []
    succeeded: list[object] = []
    runner = PrintSubprocessRunner(
        job,
        process_factory=_FakeProcess,
        stall_timeout_ms=40,
        stall_check_interval_ms=10,
    )
    runner.stalled.connect(lambda: stalled.append(True))
    runner.succeeded.connect(lambda payload: succeeded.append(payload))

    runner.start()
    process = _FakeProcess.instances[-1]
    for _ in range(4):
        process.push_stdout_event({"job_id": job.job_id, "event": "heartbeat", "message": ""})
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()

    assert stalled == []

    process.push_stdout_event(
        {
            "job_id": job.job_id,
            "event": "succeeded",
            "message": "done",
            "route": "test",
            "result_job_id": "spool-4",
        }
    )
    process.emit_finished(0)
    assert _pump_until(app, lambda: bool(succeeded)), "runner never emitted succeeded event"
    assert stalled == []
