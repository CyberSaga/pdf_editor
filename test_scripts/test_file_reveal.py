from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from utils import file_reveal


def test_windows_reveal_uses_argument_list_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(file_reveal.sys, "platform", "win32")
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(),
    )
    path = r"C:\文件 資料\report & final.pdf"

    assert file_reveal.reveal_in_file_manager(path) is True
    assert calls == [(["explorer.exe", "/select,", path], {})]


def test_windows_reveal_preserves_network_style_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(file_reveal.sys, "platform", "win32")
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **_kwargs: calls.append(args) or SimpleNamespace(),
    )
    path = r"\\server\shared folder\report.pdf"

    assert file_reveal.reveal_in_file_manager(path) is True
    assert calls[0][-1] == path


def test_reveal_missing_file_returns_false_without_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: False)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("launcher must not run for missing file"),
    )

    assert file_reveal.reveal_in_file_manager(r"C:\missing\document.pdf") is False
