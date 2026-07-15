from __future__ import annotations

from types import SimpleNamespace

from test_scripts.benchmark_ui_open_render import _wait_for_quality


class _FakeController:
    def __init__(self) -> None:
        self._page_render_quality_by_session = {
            "session-1": {"srgb": {0: "low"}},
        }

    def _page_quality_map(self, session_id: str) -> dict[int, str]:
        return self._page_render_quality_by_session[session_id]["srgb"]


def test_wait_for_quality_reads_active_color_profile_map() -> None:
    startup = {
        "controller": _FakeController(),
        "app": SimpleNamespace(processEvents=lambda: None),
    }

    elapsed_ms = _wait_for_quality(
        startup,
        session_id="session-1",
        page_idx=0,
        quality="low",
        timeout_s=0.01,
    )

    assert elapsed_ms == 0.0
