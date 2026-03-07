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
            "startup: view_shown",
            "startup: event_loop_ready",
        ):
            assert expected in log_text
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()
