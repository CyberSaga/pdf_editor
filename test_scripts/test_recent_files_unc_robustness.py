from __future__ import annotations

import os
from pathlib import Path

import pytest

import utils.single_instance as single_instance_module
from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from utils.preferences import UserPreferences
from view.pdf_view import PDFView

# The confirmed defect: on Python 3.10 / Windows, ``Path.resolve(strict=False)``
# STILL raises ``OSError`` (WinError 53, ERROR_BAD_NETPATH) for an unreachable
# UNC share. We reproduce that platform quirk deterministically by monkeypatching
# ``Path.resolve`` to raise for UNC-shaped paths, so these tests fail the same way
# on any OS. Plain-Python seams only — no ``unittest.mock.patch`` on Qt classes.

_UNC_PATH = r"\\192.168.1.238\share\report.pdf"
_UNC_MARKER = "192.168.1.238"


def _install_unc_resolve_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    original_resolve = Path.resolve

    def resolve_raising_on_unc(self: Path, *args: object, **kwargs: object) -> Path:
        if _UNC_MARKER in str(self):
            raise FileNotFoundError(53, "The network path was not found")
        return original_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", resolve_raising_on_unc)


class _FakeStore:
    def __init__(self, initial: dict | None = None) -> None:
        self._data: dict[str, object] = dict(initial or {})

    def value(self, key: str, default=None, type=None):  # noqa: A002 - QSettings API
        return self._data.get(key, default)

    def setValue(self, key: str, value) -> None:
        self._data[key] = value


class _StubPrefs:
    def __init__(self, recent: list[str]) -> None:
        self._recent = list(recent)

    def get_recent_files(self) -> list[str]:
        return list(self._recent)


# --- (a) chokepoint: canonicalize_recent_path must not raise on OSError --------


def test_canonicalize_recent_path_survives_resolve_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_unc_resolve_bomb(monkeypatch)

    result = UserPreferences.canonicalize_recent_path(_UNC_PATH)

    assert result, "expected a usable canonical path, not an exception"
    assert os.path.isabs(result)
    assert _UNC_MARKER in result
    # Dedup identity must stay stable across repeated canonicalization of the
    # same input, otherwise recent-file dedupe silently breaks.
    again = UserPreferences.canonicalize_recent_path(_UNC_PATH)
    assert UserPreferences._recent_identity(result) == UserPreferences._recent_identity(again)


# --- (b) get_recent_files survives a poisoned store entry ---------------------


def test_get_recent_files_survives_unreachable_unc_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_unc_resolve_bomb(monkeypatch)
    local = str(tmp_path / "local.pdf")
    store = _FakeStore({"files/recent": [_UNC_PATH, _UNC_PATH, local]})
    prefs = UserPreferences(store=store)

    recent = prefs.get_recent_files()  # must not raise

    unc_entries = [p for p in recent if _UNC_MARKER in p]
    assert len(unc_entries) == 1, "UNC entry must be retained and deduplicated"
    assert any(_recent_ident(p) == _recent_ident(local) for p in recent)


def _recent_ident(path: str) -> str:
    return UserPreferences._recent_identity(path)


# --- (c) controller defense-in-depth: one poisoned entry never kills refresh --


def test_refresh_recent_files_degrades_poisoned_entry(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate an entry so poisoned that even the safe ``Path.is_file`` probe
    # blows up (an unreachable UNC can surface as OSError on some stacks). The
    # per-entry guard must degrade it to available=False, never propagate.
    original_is_file = Path.is_file

    def is_file_raising(self: Path) -> bool:
        if _UNC_MARKER in str(self):
            raise OSError(53, "The network path was not found")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file_raising)

    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    controller._prefs = _StubPrefs([_UNC_PATH])
    captured: list[list[dict]] = []
    monkeypatch.setattr(view, "set_recent_files", lambda entries: captured.append(entries))
    try:
        controller._refresh_recent_files()  # must not raise

        assert captured, "updater should have been called"
        entries = captured[-1]
        assert len(entries) == 1
        assert entries[0]["available"] is False
        assert _UNC_MARKER in entries[0]["path"]
    finally:
        model.close()
        view.close()
        qapp.processEvents()


# --- (d) rotation-0 regression: normal local paths are byte-identical ---------


def test_local_path_canonicalization_matches_prior_behavior(tmp_path: Path) -> None:
    local = tmp_path / "doc.pdf"
    local.write_bytes(b"%PDF-1.4\n")
    # The exact expression the original implementation used.
    expected = str(Path(str(local)).expanduser().resolve(strict=False))

    assert UserPreferences.canonicalize_recent_path(str(local)) == expected


# --- single_instance: fail CLOSED on unresolvable tokens (never skip) ---------


def test_normalize_forwarded_argv_rejects_unresolvable_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_unc_resolve_bomb(monkeypatch)
    local = str(tmp_path / "ok.pdf")

    # A single unresolvable token must reject the WHOLE hand-off (fail closed),
    # not be skipped or passed through, and must not crash the forwarding sender.
    assert single_instance_module._normalize_forwarded_argv([local, _UNC_PATH]) is None
    # A fully-resolvable argv still normalizes as before.
    normalized = single_instance_module._normalize_forwarded_argv([local])
    assert normalized == [str(Path(local).resolve())]


def test_forwarded_argv_is_acceptable_rejects_unresolvable_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_unc_resolve_bomb(monkeypatch)
    valid = tmp_path / "real.pdf"
    valid.write_bytes(b"%PDF-1.4\n")

    # Even mixed with a genuinely valid .pdf, one unresolvable token rejects the
    # whole message — proving rejection, not per-token skipping.
    assert single_instance_module._forwarded_argv_is_acceptable([str(valid), _UNC_PATH]) is False
