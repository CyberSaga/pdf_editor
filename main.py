from __future__ import annotations

import argparse
import logging
import sys
from typing import Any


def _configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
    return logging.getLogger(__name__)


def parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="pdf_editor")
    parser.add_argument("files", nargs="*", help="PDF files to open")
    parser.add_argument("--merge", dest="merge_output", metavar="OUTPUT", help="Merge inputs into OUTPUT and exit")
    args = parser.parse_args(cli_args)
    if args.merge_output and not args.files:
        parser.error("--merge requires at least one input file")
    return args


def run_merge_and_exit(args: argparse.Namespace) -> int:
    from model.headless_merge import headless_merge

    headless_merge(args.files, args.merge_output)
    return 0


def run(argv: list[str] | None = None, start_event_loop: bool = True) -> int | dict[str, Any]:
    args = parse_cli(argv)
    cli_args = list(args.files)

    _configure_logging()

    if args.merge_output:
        return run_merge_and_exit(args)

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
        "single_instance_server": None,
    }

    def attach_and_activate_controller() -> Any:
        controller = startup_ctx["controller"]
        if controller is not None:
            return controller
        from controller.pdf_controller import PDFController
        from model.pdf_model import PDFModel

        model = PDFModel()
        controller = PDFController(model, view)
        view.controller = controller
        controller.activate()
        startup_ctx["model"] = model
        startup_ctx["controller"] = controller
        for path in view.drain_pending_open_paths():
            controller.open_pdf(path)
        return controller

    def handle_forwarded_paths(paths: list[str]) -> None:
        controller = startup_ctx["controller"]
        if controller is not None:
            controller.handle_forwarded_cli(paths)
            return
        if paths:
            view._queue_or_open_paths(paths)
        if view.isMinimized():
            view.showNormal()
        view.raise_()
        view.activateWindow()

    view.sig_backend_bootstrap_requested.connect(attach_and_activate_controller)

    if start_event_loop:
        from utils.single_instance import send_to_running_instance, try_become_server

        server = try_become_server(handle_forwarded_paths)
        if server is None:
            forwarded = send_to_running_instance(cli_args)
            return 0 if forwarded else 1
        startup_ctx["single_instance_server"] = server

    view.show()

    if cli_args:
        attach_and_activate_controller()
        view.ensure_heavy_panels_initialized()
        for path in cli_args:
            startup_ctx["controller"].open_pdf(path)
    if not start_event_loop:
        return startup_ctx

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
