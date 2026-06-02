"""Security patch P7 (finding F3): CUA agent action allowlist.

``scripts/ux_signoff_agent.py`` is a dev-only computer-use harness whose actions
come from model output. ``_execute_cua_action`` must refuse any action type
outside a fixed allowlist (OWASP-LLM06 Excessive Agency) so that prompt-injected
``type``/``key`` actions cannot drive the keyboard.
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
