from __future__ import annotations

import logging
from typing import Iterable, Protocol

from model.tools.ocr_types import OcrDevice, OcrLanguage

logger = logging.getLogger(__name__)


class _SettingsLike(Protocol):
    def value(self, key: str, default=None, type=None): ...  # noqa: A002
    def setValue(self, key: str, value) -> None: ...


_OCR_DEVICE_KEY = "ocr/device"
_OCR_LANGS_KEY = "ocr/languages"
_OCR_DEVICE_DEFAULT = OcrDevice.AUTO.value
_OCR_LANGS_DEFAULT = (OcrLanguage.ENGLISH.value,)

_ORG = "pdf_editor"
_APP = "pdf_editor"


def _make_default_store() -> _SettingsLike:
    from PySide6.QtCore import QSettings

    return QSettings(_ORG, _APP)


class UserPreferences:
    """Thin facade over a QSettings-compatible store for app-wide preferences."""

    def __init__(self, store: _SettingsLike | None = None) -> None:
        self._store = store if store is not None else _make_default_store()

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
