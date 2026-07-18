from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, Protocol

from utils.app_identity import APP as _APP, LEGACY_APP as _LEGACY_APP, LEGACY_ORG as _LEGACY_ORG, ORG as _ORG
from utils.ocr_types import OcrDevice, OcrLanguage
from utils.theme_ids import DEFAULT_THEME_ID, VALID_THEME_IDS

logger = logging.getLogger(__name__)


class _SettingsLike(Protocol):
    def value(self, key: str, default=None, type=None): ...  # noqa: A002
    def setValue(self, key: str, value) -> None: ...


_OCR_DEVICE_KEY = "ocr/device"
_OCR_LANGS_KEY = "ocr/languages"
_OCR_DEVICE_DEFAULT = OcrDevice.AUTO.value
_OCR_LANGS_DEFAULT = (OcrLanguage.ENGLISH.value,)

_THEME_KEY = "ui/theme"
# Valid ids and the default live in utils.theme_ids — the single source of truth
# shared with view.theme.THEME_REGISTRY (which validates itself against it on
# import). utils/ never imports the view layer (CLAUDE.md §2).
_THEME_DEFAULT = DEFAULT_THEME_ID
_VALID_THEME_IDS = VALID_THEME_IDS

_RECENT_FILES_KEY = "files/recent"
_RECENT_FILES_LIMIT = 10

# Identity strings (_ORG/_APP for the live QSettings store, _LEGACY_* for the
# one-time migration) come from the utils.app_identity leaf — see the import.

_MIGRATE_KEYS = (_OCR_DEVICE_KEY, _OCR_LANGS_KEY, _THEME_KEY)


def _safe_resolve_path(candidate: str) -> str:
    """Canonicalize a filesystem path without letting an unreachable target abort.

    On Python 3.10 / Windows, ``Path.resolve(strict=False)`` STILL raises
    ``OSError`` (WinError 53) for an unreachable UNC share, because
    ``ERROR_BAD_NETPATH`` is missing from ntpath's non-strict allow-list (later
    CPython added it). A stale recent-files entry pointing at a now-dead share
    must not crash activation, so we fall back to a pure-string canonical form.
    ``os.path.abspath``/``expanduser`` touch no filesystem and cannot raise here,
    and they preserve the dedup identity (normcase+normpath) so stale entries
    still deduplicate consistently against their live originals.
    """
    try:
        return str(Path(candidate).expanduser().resolve(strict=False))
    except OSError:
        return os.path.abspath(os.path.expanduser(candidate))


def _make_default_store() -> _SettingsLike:
    from PySide6.QtCore import QSettings

    return QSettings(_ORG, _APP)


def _migrate_legacy_settings(store: _SettingsLike) -> None:
    from PySide6.QtCore import QSettings

    missing = [k for k in _MIGRATE_KEYS if store.value(k) is None]
    if not missing:
        return
    legacy = QSettings(_LEGACY_ORG, _LEGACY_APP)
    migrated = False
    for key in missing:
        val = legacy.value(key)
        if val is not None:
            store.setValue(key, val)
            migrated = True
    if migrated:
        logger.info("Migrated preferences from %s/%s", _LEGACY_ORG, _LEGACY_APP)


class UserPreferences:
    """Thin facade over a QSettings-compatible store for app-wide preferences."""

    def __init__(self, store: _SettingsLike | None = None) -> None:
        is_default = store is None
        self._store = store if store is not None else _make_default_store()
        if is_default:
            _migrate_legacy_settings(self._store)

    def get_ocr_device(self) -> str:
        raw = self._store.value(_OCR_DEVICE_KEY, _OCR_DEVICE_DEFAULT)
        if not isinstance(raw, str):
            return _OCR_DEVICE_DEFAULT
        try:
            return OcrDevice.from_code(raw).value
        except ValueError:
            logger.warning("Stored OCR device %r is invalid, using %s", raw, _OCR_DEVICE_DEFAULT)
            return _OCR_DEVICE_DEFAULT

    def set_ocr_device(self, device: str) -> None:
        normalized = OcrDevice.from_code(device).value
        self._store.setValue(_OCR_DEVICE_KEY, normalized)

    def get_ocr_languages(self) -> list[str]:
        raw = self._store.value(_OCR_LANGS_KEY, list(_OCR_LANGS_DEFAULT))
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",") if part.strip()]
        elif not isinstance(raw, (list, tuple)):
            return list(_OCR_LANGS_DEFAULT)
        result: list[str] = []
        for code in raw:
            if not isinstance(code, str):
                continue
            try:
                result.append(OcrLanguage.from_code(code).value)
            except ValueError:
                logger.warning("Stored OCR language %r is invalid; dropping", code)
        return result or list(_OCR_LANGS_DEFAULT)

    def set_ocr_languages(self, languages: Iterable[str]) -> None:
        codes = [OcrLanguage.from_code(code).value for code in languages]
        if not codes:
            raise ValueError("OCR 語言清單不可為空")
        self._store.setValue(_OCR_LANGS_KEY, codes)

    def get_theme(self) -> str:
        raw = self._store.value(_THEME_KEY, _THEME_DEFAULT)
        if isinstance(raw, str) and raw in _VALID_THEME_IDS:
            return raw
        if raw != _THEME_DEFAULT:
            logger.warning("Stored theme %r is invalid, using %s", raw, _THEME_DEFAULT)
        return _THEME_DEFAULT

    def set_theme(self, name: str) -> None:
        if name not in _VALID_THEME_IDS:
            raise ValueError(f"未知佈景主題：{name!r}")
        self._store.setValue(_THEME_KEY, name)

    @staticmethod
    def canonicalize_recent_path(path: str) -> str:
        candidate = str(path or "").strip()
        if not candidate:
            raise ValueError("最近檔案路徑不可為空")
        return _safe_resolve_path(candidate)

    @staticmethod
    def _recent_identity(path: str) -> str:
        return os.path.normcase(os.path.normpath(path))

    @classmethod
    def _is_temporary_path(cls, path: str) -> bool:
        temp_root = cls.canonicalize_recent_path(tempfile.gettempdir())
        try:
            return os.path.commonpath(
                [cls._recent_identity(path), cls._recent_identity(temp_root)]
            ) == cls._recent_identity(temp_root)
        except ValueError:
            return False

    def get_recent_files(self) -> list[str]:
        raw = self._store.value(_RECENT_FILES_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for value in raw:
            if not isinstance(value, str):
                continue
            try:
                canonical = self.canonicalize_recent_path(value)
            except ValueError:
                continue
            identity = self._recent_identity(canonical)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(canonical)
            if len(result) >= _RECENT_FILES_LIMIT:
                break
        return result

    def add_recent_file(self, path: str) -> bool:
        try:
            canonical = self.canonicalize_recent_path(path)
        except ValueError:
            return False
        if Path(canonical).suffix.casefold() != ".pdf" or self._is_temporary_path(canonical):
            return False
        identity = self._recent_identity(canonical)
        recent = [
            existing
            for existing in self.get_recent_files()
            if self._recent_identity(existing) != identity
        ]
        self._store.setValue(
            _RECENT_FILES_KEY,
            [canonical, *recent][:_RECENT_FILES_LIMIT],
        )
        return True

    def remove_recent_file(self, path: str) -> bool:
        try:
            identity = self._recent_identity(self.canonicalize_recent_path(path))
        except ValueError:
            return False
        recent = self.get_recent_files()
        retained = [
            existing for existing in recent if self._recent_identity(existing) != identity
        ]
        if len(retained) == len(recent):
            return False
        self._store.setValue(_RECENT_FILES_KEY, retained)
        return True
