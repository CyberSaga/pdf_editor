import logging
import sys
from typing import Any

def _configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
    return logging.getLogger(__name__)


def run(argv: list[str] | None = None, start_event_loop: bool = True) -> int | dict[str, Any]:
    cli_args = list(sys.argv[1:] if argv is None else argv)

    _configure_logging()

    from PySide6.QtWidgets import QApplication
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], *cli_args])

    model = PDFModel()
    view = PDFView(defer_heavy_panels=not cli_args)

    controller = PDFController(model, view)
    controller_attached = {"done": False}

    def attach_and_activate_controller() -> None:
        if controller_attached["done"]:
            return
        view.controller = controller
        controller.activate()
        for path in view.drain_pending_open_paths():
            controller.open_pdf(path)
        controller_attached["done"] = True

    if not cli_args:
        view.shell_ready.connect(attach_and_activate_controller)

    view.show()

    if cli_args:
        attach_and_activate_controller()
        view.ensure_heavy_panels_initialized()
        for path in cli_args:
            controller.open_pdf(path)

    if not start_event_loop:
        return {
            "app": app,
            "model": model,
            "view": view,
            "controller": controller,
        }

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
