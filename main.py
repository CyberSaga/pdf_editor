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
    from PySide6.QtCore import QTimer

    checkpoint = _log_startup_checkpoint(logger, "qt_imported", checkpoint)

    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController

    checkpoint = _log_startup_checkpoint(logger, "mvc_imported", checkpoint)

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], *cli_args])
    checkpoint = _log_startup_checkpoint(logger, "qapplication_created", checkpoint)

    model = PDFModel()
    checkpoint = _log_startup_checkpoint(logger, "model_created", checkpoint)

    view = PDFView(defer_heavy_panels=True)
    checkpoint = _log_startup_checkpoint(logger, "view_created", checkpoint)

    controller = PDFController(model, view)
    checkpoint = _log_startup_checkpoint(logger, "controller_created", checkpoint)

    checkpoint_state = {"value": checkpoint}
    controller_attached = {"done": False}

    def _log_view_lifecycle(label: str) -> None:
        checkpoint_state["value"] = _log_startup_checkpoint(
            logger,
            label,
            checkpoint_state["value"],
        )

    def _attach_controller_to_view() -> None:
        if controller_attached["done"]:
            return
        view.controller = controller
        controller_attached["done"] = True

    view.set_startup_checkpoint_logger(_log_view_lifecycle)

    # Split pre-show work into Qt polish vs native window creation so slow cold
    # starts can be attributed to widget/style preparation or platform handles.
    view.ensurePolished()
    checkpoint = _log_startup_checkpoint(logger, "view_polished", checkpoint)

    _ = view.winId()
    checkpoint = _log_startup_checkpoint(logger, "view_native_window_created", checkpoint)

    view.show()
    checkpoint = checkpoint_state["value"]
    checkpoint = _log_startup_checkpoint(logger, "view_shown", checkpoint)

    if cli_args:
        _attach_controller_to_view()
        # Opening a document immediately needs the real sidebar/inspector widgets.
        view.ensure_heavy_panels_initialized()
    else:
        # Leave PDFView detached during the first empty-window show path, then
        # attach the controller on the first queued tick after the window is visible.
        QTimer.singleShot(0, _attach_controller_to_view)

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
