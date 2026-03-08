from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import pdfview_startup_probe


@pytest.mark.parametrize("with_controller", [False, True])
def test_pdfview_probe_logs_startup_markers(caplog, with_controller: bool) -> None:
    caplog.set_level(logging.INFO)

    startup = pdfview_startup_probe.run(
        start_event_loop=False,
        with_controller=with_controller,
    )
    try:
        for _ in range(5):
            startup["app"].processEvents()

        log_text = caplog.text
        expected = [
            "pdfview_probe: logging_configured",
            "pdfview_probe: qt_imported",
            "pdfview_probe: model_created",
            "pdfview_probe: view_created",
            "pdfview_probe: view_polished",
            "pdfview_probe: view_native_window_created",
            "pdfview_probe: view_show_event",
            "pdfview_probe: view_shown",
            "pdfview_probe: event_loop_ready",
            "pdfview_probe: view_first_event_loop_tick",
            "pdfview_probe: view_first_paint",
        ]
        if with_controller:
            expected.insert(4, "pdfview_probe: controller_created")
        for marker in expected:
            assert marker in log_text
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()


def test_pdfview_probe_can_build_controller_without_attaching_to_view(caplog) -> None:
    caplog.set_level(logging.INFO)

    startup = pdfview_startup_probe.run(
        start_event_loop=False,
        with_controller=True,
        attach_controller_to_view=False,
    )
    try:
        assert startup["controller"] is not None
        assert startup["view"].controller is None
        assert "pdfview_probe: controller_created" in caplog.text
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()


def test_pdfview_probe_script_runs_without_event_loop() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "test_scripts" / "pdfview_startup_probe.py"), "--no-event-loop"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = proc.stdout + proc.stderr
    assert "pdfview_probe: view_native_window_created" in text
    assert "pdfview_probe: view_show_event" in text


def test_pdfview_probe_script_supports_detached_controller() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "test_scripts" / "pdfview_startup_probe.py"),
            "--with-controller",
            "--detach-controller",
            "--no-event-loop",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "pdfview_probe: controller_created" in (proc.stdout + proc.stderr)
