from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as main_module
from view.pdf_view import PDFView


def test_empty_launch_defers_controller_attachment_until_first_event_loop_tick() -> None:
    startup = main_module.run(argv=[], start_event_loop=False)

    try:
        assert startup["view"].controller is None
        assert not startup["controller"].is_active

        for _ in range(5):
            startup["app"].processEvents()

        assert startup["view"].controller is startup["controller"]
        assert startup["controller"].is_active
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()


def test_cli_open_path_keeps_controller_attached_before_opening_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[bool, bool]] = []

    from controller.pdf_controller import PDFController

    def fake_open_pdf(self, path: str) -> None:
        observed.append((self.is_active, self.view.controller is self))

    monkeypatch.setattr(PDFController, "open_pdf", fake_open_pdf)

    startup = main_module.run(argv=["dummy.pdf"], start_event_loop=False)
    try:
        assert observed == [(True, True)]
        assert startup["view"].controller is startup["controller"]
        assert startup["controller"].is_active
    finally:
        startup["view"].close()
        startup["model"].close()
        startup["app"].quit()


def test_pdf_view_emits_shell_ready_after_deferred_hydration() -> None:
    startup = main_module.run(argv=[], start_event_loop=False)
    app = startup["app"]
    startup["view"].close()
    startup["model"].close()

    view = PDFView(defer_heavy_panels=True)
    observed: list[tuple[int, int, str]] = []
    try:
        assert view.left_sidebar.count() == 0
        assert view.right_stacked_widget.count() == 1
        assert not hasattr(view, "text_target_mode_combo")

        view.shell_ready.connect(
            lambda: observed.append(
                (
                    view.left_sidebar.count(),
                    view.right_stacked_widget.count(),
                    view.text_target_mode_combo.currentData(),
                )
            )
        )

        view.show()
        for _ in range(5):
            app.processEvents()

        assert observed == [(4, 4, "paragraph")]
        assert view.left_sidebar.count() == 4
        assert view.right_stacked_widget.count() == 4
        assert view.text_target_mode_combo.currentData() == "paragraph"
    finally:
        view.close()
        app.quit()
