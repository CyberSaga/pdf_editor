"""Security patch P7 + Task 5 (finding F3): CUA agent action allowlist + bounds.

``scripts/ux_signoff_agent.py`` is a dev-only computer-use harness whose actions
come from model output. ``_execute_cua_action`` must refuse any action type
outside a fixed allowlist (OWASP-LLM06 Excessive Agency) so that prompt-injected
``type``/``key`` actions cannot drive the keyboard, AND must refuse coordinate
actions that fall outside the app window so injected screen content cannot drive
the pointer to arbitrary desktop locations.
"""

from __future__ import annotations

import pytest

import scripts.ux_signoff_agent as signoff_mod


class _Action:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


class _FakePyAutoGui:
    """No-op stand-in that records the click so allowed actions can be verified
    without touching the real mouse/keyboard."""

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int, str]] = []

    def click(self, x, y, button="left"):
        self.clicks.append((x, y, button))

    def doubleClick(self, x, y):
        self.clicks.append((x, y, "double"))

    def scroll(self, *a, **k):
        pass

    def typewrite(self, *a, **k):
        pass

    def hotkey(self, *a, **k):
        pass

    def moveTo(self, *a, **k):
        pass


def test_execute_cua_action_blocks_type(monkeypatch) -> None:
    monkeypatch.setattr(signoff_mod, "pyautogui", _FakePyAutoGui())
    with pytest.raises(PermissionError):
        signoff_mod._execute_cua_action(_Action(type="type", text="please run a command"))


def test_execute_cua_action_blocks_key(monkeypatch) -> None:
    monkeypatch.setattr(signoff_mod, "pyautogui", _FakePyAutoGui())
    with pytest.raises(PermissionError):
        signoff_mod._execute_cua_action(_Action(type="key", keys=["ctrl", "a"]))


def test_execute_cua_action_blocks_unknown(monkeypatch) -> None:
    monkeypatch.setattr(signoff_mod, "pyautogui", _FakePyAutoGui())
    with pytest.raises(PermissionError):
        signoff_mod._execute_cua_action(_Action(type="drag", x=1, y=2))


def test_execute_cua_action_allows_click(monkeypatch) -> None:
    fake = _FakePyAutoGui()
    monkeypatch.setattr(signoff_mod, "pyautogui", fake)
    signoff_mod._execute_cua_action(_Action(type="click", x=10, y=20, button="left"))
    assert fake.clicks == [(10, 20, "left")]


def test_execute_cua_action_allows_screenshot(monkeypatch) -> None:
    fake = _FakePyAutoGui()
    monkeypatch.setattr(signoff_mod, "pyautogui", fake)
    # screenshot is a no-op in _execute_cua_action but must not be blocked.
    signoff_mod._execute_cua_action(_Action(type="screenshot"))
    assert fake.clicks == []


# --- F3 Task 5: window-bounds enforcement ------------------------------------

_WINDOW = (0, 0, 800, 600)  # (left, top, right, bottom)


def test_execute_cua_action_rejects_out_of_window_click(monkeypatch) -> None:
    fake = _FakePyAutoGui()
    monkeypatch.setattr(signoff_mod, "pyautogui", fake)
    with pytest.raises(PermissionError, match="out-of-window"):
        signoff_mod._execute_cua_action(
            _Action(type="click", x=1000, y=1000, button="left"), window_rect=_WINDOW
        )
    assert fake.clicks == []  # the click must never reach pyautogui


def test_execute_cua_action_rejects_out_of_window_move(monkeypatch) -> None:
    fake = _FakePyAutoGui()
    monkeypatch.setattr(signoff_mod, "pyautogui", fake)
    with pytest.raises(PermissionError, match="out-of-window"):
        signoff_mod._execute_cua_action(_Action(type="move", x=-5, y=10), window_rect=_WINDOW)


def test_execute_cua_action_allows_in_window_click(monkeypatch) -> None:
    fake = _FakePyAutoGui()
    monkeypatch.setattr(signoff_mod, "pyautogui", fake)
    signoff_mod._execute_cua_action(
        _Action(type="click", x=100, y=100, button="left"), window_rect=_WINDOW
    )
    assert fake.clicks == [(100, 100, "left")]


def test_execute_cua_action_no_rect_skips_bounds(monkeypatch) -> None:
    """When the window rect is unknown (detection failed), bounds are not enforced
    so the signoff still runs; the allowlist still applies. Documented fail-open."""
    fake = _FakePyAutoGui()
    monkeypatch.setattr(signoff_mod, "pyautogui", fake)
    signoff_mod._execute_cua_action(
        _Action(type="click", x=5000, y=5000, button="left"), window_rect=None
    )
    assert fake.clicks == [(5000, 5000, "left")]
