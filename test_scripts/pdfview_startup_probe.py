from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

_PROCESS_START = time.perf_counter()
_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
        "pdfview_probe: %s total=%.3fs delta=%.3fs",
        label,
        now - _PROCESS_START,
        now - previous_checkpoint,
    )
    return now


def run(
    *,
    start_event_loop: bool = True,
    with_controller: bool = False,
    attach_controller_to_view: bool = True,
) -> int | dict[str, Any]:
    logger = _configure_logging()
    checkpoint = _PROCESS_START
    checkpoint = _log_probe_checkpoint(logger, "logging_configured", checkpoint)

    from PySide6.QtWidgets import QApplication
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    checkpoint = _log_probe_checkpoint(logger, "qt_imported", checkpoint)

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    checkpoint = _log_probe_checkpoint(logger, "qapplication_created", checkpoint)

    model = PDFModel()
    checkpoint = _log_probe_checkpoint(logger, "model_created", checkpoint)

    view = PDFView(defer_heavy_panels=True)
    checkpoint = _log_probe_checkpoint(logger, "view_created", checkpoint)

    controller = None
    if with_controller:
        from controller.pdf_controller import PDFController

        controller = PDFController(model, view)
        if attach_controller_to_view:
            view.controller = controller
        checkpoint = _log_probe_checkpoint(logger, "controller_created", checkpoint)

    checkpoint_state = {"value": checkpoint}

    def _log_view_lifecycle(label: str) -> None:
        checkpoint_state["value"] = _log_probe_checkpoint(
            logger,
            label,
            checkpoint_state["value"],
        )

    view.set_startup_checkpoint_logger(_log_view_lifecycle)

    view.ensurePolished()
    checkpoint = _log_probe_checkpoint(logger, "view_polished", checkpoint)

    _ = view.winId()
    checkpoint = _log_probe_checkpoint(logger, "view_native_window_created", checkpoint)

    view.show()
    checkpoint = checkpoint_state["value"]
    checkpoint = _log_probe_checkpoint(logger, "view_shown", checkpoint)
    checkpoint = _log_probe_checkpoint(logger, "event_loop_ready", checkpoint)

    if not start_event_loop:
        return {
            "app": app,
            "model": model,
            "view": view,
            "controller": controller,
            "checkpoint": checkpoint,
        }

    return app.exec()


if __name__ == "__main__":
    args = sys.argv[1:]
    with_controller = "--with-controller" in args
    attach_controller_to_view = "--detach-controller" not in args
    start_event_loop = "--no-event-loop" not in args
    result = run(
        with_controller=with_controller,
        attach_controller_to_view=attach_controller_to_view,
        start_event_loop=start_event_loop,
    )
    raise SystemExit(0 if isinstance(result, dict) else result)
