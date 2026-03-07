import logging
import sys
import time
from typing import Any

# Capture startup as early as possible before importing heavier GUI/MVC modules.
_PROCESS_START = time.perf_counter()
_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


def _configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG, format=_LOG_FORMAT)
    return logging.getLogger(__name__)


def _log_startup_checkpoint(
    logger: logging.Logger,
    label: str,
    previous_checkpoint: float,
) -> float:
    now = time.perf_counter()
    logger.info(
        "startup: %s total=%.3fs delta=%.3fs",
        label,
        now - _PROCESS_START,
        now - previous_checkpoint,
    )
    return now


def run(argv: list[str] | None = None, start_event_loop: bool = True) -> int | dict[str, Any]:
    cli_args = list(sys.argv[1:] if argv is None else argv)

    logger = _configure_logging()
    checkpoint = _PROCESS_START
    checkpoint = _log_startup_checkpoint(logger, "logging_configured", checkpoint)

    from PySide6.QtWidgets import QApplication

    checkpoint = _log_startup_checkpoint(logger, "qt_imported", checkpoint)

    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController

    checkpoint = _log_startup_checkpoint(logger, "mvc_imported", checkpoint)

    app = QApplication([sys.argv[0], *cli_args])
    checkpoint = _log_startup_checkpoint(logger, "qapplication_created", checkpoint)

    model = PDFModel()
    checkpoint = _log_startup_checkpoint(logger, "model_created", checkpoint)

    view = PDFView()
    checkpoint = _log_startup_checkpoint(logger, "view_created", checkpoint)

    controller = PDFController(model, view)
    view.controller = controller
    checkpoint = _log_startup_checkpoint(logger, "controller_created", checkpoint)

    view.show()
    checkpoint = _log_startup_checkpoint(logger, "view_shown", checkpoint)

    for path in cli_args:
        controller.open_pdf(path)
        checkpoint = _log_startup_checkpoint(logger, f"document_opened path={path}", checkpoint)

    checkpoint = _log_startup_checkpoint(logger, "event_loop_ready", checkpoint)

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
    raise SystemExit(run())
