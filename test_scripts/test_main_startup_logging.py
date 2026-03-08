from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as main_module
from view.pdf_view import PDFView


def test_run_logs_startup_checkpoints(caplog) -> None:
    caplog.set_level(logging.INFO)

    startup = main_module.run(argv=[], start_event_loop=False)

    try:
        log_text = caplog.text
        for expected in (
            "startup: logging_configured",
            "startup: qt_imported",
            "startup: mvc_imported",
            "startup: qapplication_created",
            "startup: model_created",
            "startup: view_created",
            "startup: controller_created",
            "startup: view_polished",
            "startup: view_native_window_created",
            "startup: view_shown",
            "startup: event_loop_ready",
        ):
            assert expected in log_text
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()


def test_run_logs_first_window_lifecycle_markers(caplog) -> None:
    caplog.set_level(logging.INFO)

    startup = main_module.run(argv=[], start_event_loop=False)

    try:
        for _ in range(5):
            startup["app"].processEvents()

        log_text = caplog.text
        for expected in (
            "startup: view_show_event",
            "startup: view_first_event_loop_tick",
        ):
            assert expected in log_text
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()


def test_pdf_view_can_defer_heavy_sidebars_until_after_first_show() -> None:
    startup = main_module.run(argv=[], start_event_loop=False)
    app = startup["app"]
    startup["view"].close()
    startup["model"].close()

    view = PDFView(defer_heavy_panels=True)
    try:
        # The heavy sidebar and inspector trees stay out of the first show path.
        assert view.left_sidebar.count() == 0
        assert view.right_stacked_widget.count() == 1
        assert not hasattr(view, "text_target_mode_combo")

        view.show()
        for _ in range(5):
            app.processEvents()

        # Deferred hydration rebuilds the full editing UI after the window appears.
        assert view.left_sidebar.count() == 4
        assert view.right_stacked_widget.count() == 4
        assert view.text_target_mode_combo.currentData() == "paragraph"
    finally:
        view.close()
        app.quit()
