from __future__ import annotations

import logging
import sys
import time
from typing import Any

_PROCESS_START = time.perf_counter()
_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


def _configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG, format=_LOG_FORMAT)
    return logging.getLogger(__name__)


def _log_probe_checkpoint(
    logger: logging.Logger,
    label: str,
    previous_checkpoint: float,
) -> float:
    now = time.perf_counter()
    logger.info(
        "probe: %s total=%.3fs delta=%.3fs",
        label,
        now - _PROCESS_START,
        now - previous_checkpoint,
    )
    return now


def run(start_event_loop: bool = True) -> int | dict[str, Any]:
    logger = _configure_logging()
    checkpoint = _PROCESS_START
    checkpoint = _log_probe_checkpoint(logger, "logging_configured", checkpoint)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMainWindow

    checkpoint = _log_probe_checkpoint(logger, "qt_imported", checkpoint)

    class ProbeWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self._checkpoint_logger = None
            self._markers_seen: set[str] = set()
            self._show_tick_scheduled = False
            self.setWindowTitle("Qt Cold Start Probe")
            self.setMinimumSize(1280, 800)
            self.setGeometry(100, 100, 1280, 800)

        def set_checkpoint_logger(self, callback) -> None:
            self._checkpoint_logger = callback

        def _emit_marker(self, label: str) -> None:
            if label in self._markers_seen:
                return
            self._markers_seen.add(label)
            callback = self._checkpoint_logger
            if callback is not None:
                callback(label)

        def showEvent(self, event) -> None:
            self._emit_marker("window_show_event")
            if not self._show_tick_scheduled:
                self._show_tick_scheduled = True
                QTimer.singleShot(0, lambda: self._emit_marker("window_first_event_loop_tick"))
            super().showEvent(event)

        def paintEvent(self, event) -> None:
            self._emit_marker("window_first_paint")
            super().paintEvent(event)

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    checkpoint = _log_probe_checkpoint(logger, "qapplication_created", checkpoint)

    window = ProbeWindow()
    checkpoint = _log_probe_checkpoint(logger, "window_created", checkpoint)

    checkpoint_state = {"value": checkpoint}

    def _log_window_lifecycle(label: str) -> None:
        checkpoint_state["value"] = _log_probe_checkpoint(
            logger,
            label,
            checkpoint_state["value"],
        )

    window.set_checkpoint_logger(_log_window_lifecycle)

    window.ensurePolished()
    checkpoint = _log_probe_checkpoint(logger, "window_polished", checkpoint)

    _ = window.winId()
    checkpoint = _log_probe_checkpoint(logger, "window_native_created", checkpoint)

    window.show()
    checkpoint = checkpoint_state["value"]
    checkpoint = _log_probe_checkpoint(logger, "window_shown", checkpoint)
    checkpoint = _log_probe_checkpoint(logger, "event_loop_ready", checkpoint)

    if not start_event_loop:
        return {"app": app, "window": window, "checkpoint": checkpoint}

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
