from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import qt_cold_start_probe


def test_probe_logs_native_window_startup_markers(caplog) -> None:
    caplog.set_level(logging.INFO)

    startup = qt_cold_start_probe.run(start_event_loop=False)

    try:
        for _ in range(5):
            startup["app"].processEvents()

        log_text = caplog.text
        for expected in (
            "probe: logging_configured",
            "probe: qt_imported",
            "probe: qapplication_created",
            "probe: window_created",
            "probe: window_polished",
            "probe: window_native_created",
            "probe: window_show_event",
            "probe: window_shown",
            "probe: event_loop_ready",
            "probe: window_first_event_loop_tick",
            "probe: window_first_paint",
        ):
            assert expected in log_text
    finally:
        startup["window"].close()
        startup["app"].quit()
