from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import qt_rich_shell_probe


def test_rich_probe_logs_shell_startup_markers(caplog) -> None:
    caplog.set_level(logging.INFO)

    startup = qt_rich_shell_probe.run(start_event_loop=False)

    try:
        for _ in range(5):
            startup["app"].processEvents()

        log_text = caplog.text
        for expected in (
            "rich_probe: logging_configured",
            "rich_probe: qt_imported",
            "rich_probe: qapplication_created",
            "rich_probe: window_created",
            "rich_probe: window_polished",
            "rich_probe: window_native_created",
            "rich_probe: window_show_event",
            "rich_probe: window_shown",
            "rich_probe: event_loop_ready",
            "rich_probe: window_first_event_loop_tick",
            "rich_probe: window_first_paint",
        ):
            assert expected in log_text
    finally:
        startup["window"].close()
        startup["app"].quit()
