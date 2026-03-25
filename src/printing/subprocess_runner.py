"""Controller-facing runner for the print helper subprocess."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .base_driver import PrintJobResult
from .errors import PrintHelperTerminatedError, PrintJobSubmissionError
from .helper_protocol import PrintHelperJob, parse_helper_event

logger = logging.getLogger(__name__)


class PrintSubprocessRunner(QObject):
    """Launch and monitor the helper subprocess."""

    progress = Signal(str)
    stalled = Signal()
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        job: PrintHelperJob,
        *,
        process_factory=None,
        python_executable: str | None = None,
        work_dir: str | None = None,
        stall_timeout_ms: int = 30000,
        stall_check_interval_ms: int = 500,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.job = job
        self._process_factory = process_factory or QProcess
        self._python_executable = python_executable or sys.executable
        self._provided_work_dir = work_dir
        self._owned_temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._process: QProcess | None = None
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._stall_timeout_ms = max(1, int(stall_timeout_ms))
        self._last_activity = time.monotonic()
        self._termination_requested = False
        self._terminal_event_seen = False
        self._stall_reported = False
        self._finish_handled = False
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(int(stall_check_interval_ms))
        self._watchdog.timeout.connect(self._check_stall)

    def _detect_project_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _build_helper_env(self, project_root: Path) -> dict[str, str]:
        env = dict(os.environ)
        root = str(project_root)
        existing = env.get("PYTHONPATH", "")
        parts = [part for part in existing.split(os.pathsep) if part]
        if root not in parts:
            parts.insert(0, root)
        env["PYTHONPATH"] = os.pathsep.join(parts)
        return env

    def _configure_process_context(
        self,
        process: QProcess,
        *,
        project_root: Path,
        env: dict[str, str],
    ) -> None:
        set_cwd = getattr(process, "setWorkingDirectory", None)
        if callable(set_cwd):
            set_cwd(str(project_root))
        set_env = getattr(process, "setProcessEnvironment", None)
        if callable(set_env):
            process_env = QProcessEnvironment()
            for key, value in env.items():
                if isinstance(value, str):
                    process_env.insert(key, value)
            set_env(process_env)

    def start(self) -> None:
        if self._process is not None:
            return
        work_dir = self._provided_work_dir
        if work_dir is None:
            self._owned_temp_dir = tempfile.TemporaryDirectory(prefix="print-helper-")
            work_dir = self._owned_temp_dir.name
        job_path = Path(work_dir) / "job.json"
        self.job.write(job_path)

        self._process = self._process_factory()
        self._process.readyReadStandardOutput.connect(self._on_ready_stdout)
        self._process.readyReadStandardError.connect(self._on_ready_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        project_root = self._detect_project_root()
        helper_env = self._build_helper_env(project_root)
        self._configure_process_context(self._process, project_root=project_root, env=helper_env)
        self._last_activity = time.monotonic()
        self._watchdog.start()
        self._process.start(
            self._python_executable,
            ["-m", "src.printing.helper_main", str(job_path)],
        )

    def terminate(self) -> None:
        self._termination_requested = True
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    def _on_ready_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not chunk:
            return
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            raw_line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            payload = parse_helper_event(raw_line)
            self._handle_event(payload)

    def _on_ready_stderr(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        if chunk:
            self._stderr_buffer += chunk

    def _handle_event(self, payload: dict) -> None:
        if payload.get("job_id") != self.job.job_id:
            return
        self._last_activity = time.monotonic()
        event = payload.get("event")
        message = str(payload.get("message", ""))
        if event in {"started", "progress", "heartbeat"}:
            if message:
                self.progress.emit(message)
            return
        if event == "succeeded":
            self._terminal_event_seen = True
            self.succeeded.emit(
                PrintJobResult(
                    success=True,
                    route=str(payload.get("route", "")),
                    message=message,
                    job_id=payload.get("result_job_id"),
                )
            )
            return
        if event == "failed":
            self._terminal_event_seen = True
            self.failed.emit(
                PrintJobSubmissionError(
                    message or str(payload.get("error_type", "print helper failed"))
                )
            )

    def _check_stall(self) -> None:
        if self._process is None or self._terminal_event_seen or self._stall_reported:
            return
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        elapsed_ms = (time.monotonic() - self._last_activity) * 1000.0
        if elapsed_ms < self._stall_timeout_ms:
            return
        self._stall_reported = True
        self.stalled.emit()

    def _on_error(self, error) -> None:
        if self._terminal_event_seen:
            return
        detail = self._stderr_buffer.strip()
        if self._process is not None:
            error_string_method = getattr(self._process, "errorString", None)
            if callable(error_string_method):
                error_string = error_string_method().strip()
                if error_string:
                    detail = f"{detail}\n{error_string}".strip() if detail else error_string
        error_name = getattr(error, "name", None) or str(error)
        message = detail or f"Print helper process error: {error_name}."
        logger.error("Print helper process error (%s): %s", error_name, message)
        self._terminal_event_seen = True
        self.failed.emit(PrintJobSubmissionError(message))

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        if self._finish_handled:
            return
        self._finish_handled = True
        self._watchdog.stop()
        if not self._terminal_event_seen:
            self._terminal_event_seen = True
            if self._termination_requested:
                self.failed.emit(PrintHelperTerminatedError("Print job was terminated by the user."))
            else:
                detail = self._stderr_buffer.strip()
                message = detail or f"Print helper exited with code {exit_code}."
                self.failed.emit(PrintJobSubmissionError(message))
        self._cleanup()
        self.finished.emit()

    def _cleanup(self) -> None:
        self._process = None
        if self._owned_temp_dir is not None:
            self._owned_temp_dir.cleanup()
            self._owned_temp_dir = None
        elif self._provided_work_dir:
            shutil.rmtree(self._provided_work_dir, ignore_errors=True)
