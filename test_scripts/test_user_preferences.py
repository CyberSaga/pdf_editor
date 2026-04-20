from __future__ import annotations

import pytest

from utils.preferences import UserPreferences


class _FakeStore:
    def __init__(self, initial: dict | None = None) -> None:
        self._data: dict[str, object] = dict(initial or {})

    def value(self, key: str, default=None, type=None):  # noqa: A002 - QSettings API
        return self._data.get(key, default)

    def setValue(self, key: str, value) -> None:
        self._data[key] = value


def test_default_ocr_device_is_auto():
    prefs = UserPreferences(store=_FakeStore())
    assert prefs.get_ocr_device() == "auto"


def test_set_then_get_ocr_device_round_trips():
    prefs = UserPreferences(store=_FakeStore())
    prefs.set_ocr_device("cuda")
    assert prefs.get_ocr_device() == "cuda"


def test_set_ocr_device_persists_in_store():
    store = _FakeStore()
    prefs = UserPreferences(store=store)
    prefs.set_ocr_device("cpu")
    other = UserPreferences(store=store)
    assert other.get_ocr_device() == "cpu"


def test_set_ocr_device_rejects_unknown_value():
    prefs = UserPreferences(store=_FakeStore())
    with pytest.raises(ValueError):
        prefs.set_ocr_device("quantum")


def test_get_ocr_device_recovers_from_corrupt_value():
    prefs = UserPreferences(store=_FakeStore({"ocr/device": "garbage"}))
    assert prefs.get_ocr_device() == "auto"


def test_default_ocr_languages_is_english():
    prefs = UserPreferences(store=_FakeStore())
    assert prefs.get_ocr_languages() == ["en"]


def test_set_ocr_languages_stores_list():
    prefs = UserPreferences(store=_FakeStore())
    prefs.set_ocr_languages(["en", "zh-Hant"])
    assert prefs.get_ocr_languages() == ["en", "zh-Hant"]


def test_set_ocr_languages_rejects_unknown_code():
    prefs = UserPreferences(store=_FakeStore())
    with pytest.raises(ValueError):
        prefs.set_ocr_languages(["en", "klingon"])


def test_set_ocr_languages_rejects_empty_list():
    prefs = UserPreferences(store=_FakeStore())
    with pytest.raises(ValueError):
        prefs.set_ocr_languages([])
