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
    from view.pdf_view import PDFView

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], *cli_args])

    view = PDFView(defer_heavy_panels=not cli_args)
    startup_ctx: dict[str, Any] = {
        "app": app,
        "model": None,
        "view": view,
        "controller": None,
    }

    def attach_and_activate_controller() -> Any:
        controller = startup_ctx["controller"]
        if controller is not None:
            return controller
        from model.pdf_model import PDFModel
        from controller.pdf_controller import PDFController

        model = PDFModel()
        controller = PDFController(model, view)
        view.controller = controller
        controller.activate()
        startup_ctx["model"] = model
        startup_ctx["controller"] = controller
        for path in view.drain_pending_open_paths():
            controller.open_pdf(path)
        return controller

    view.show()

    if cli_args:
        attach_and_activate_controller()
        view.ensure_heavy_panels_initialized()
        for path in cli_args:
            startup_ctx["controller"].open_pdf(path)
    else:
        view.sig_backend_bootstrap_requested.connect(attach_and_activate_controller)

    if not start_event_loop:
        return startup_ctx

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
