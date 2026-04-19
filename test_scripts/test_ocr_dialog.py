from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox

from model.tools.ocr_types import OcrLanguage, OcrRequest
from utils.preferences import UserPreferences
from view.dialogs.ocr import OcrDialog


class _FakeStore:
    def __init__(self, initial: dict | None = None) -> None:
        self._data = dict(initial or {})

    def value(self, key, default=None, type=None):  # noqa: A002
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value


def _make_prefs(**overrides) -> UserPreferences:
    prefs = UserPreferences(store=_FakeStore())
    device = overrides.get("device")
    if device:
        prefs.set_ocr_device(device)
    langs = overrides.get("languages")
    if langs:
        prefs.set_ocr_languages(langs)
    return prefs


def test_dialog_defaults_to_current_page(qapp):
    dialog = OcrDialog(total_pages=10, current_page=3, preferences=_make_prefs())
    assert dialog.current_page_radio.isChecked()
    assert not dialog.custom_range_edit.isEnabled()
    dialog.deleteLater()


def test_dialog_switching_to_custom_enables_range_edit(qapp):
    dialog = OcrDialog(total_pages=10, current_page=3, preferences=_make_prefs())
    dialog.custom_radio.setChecked(True)
    qapp.processEvents()
    assert dialog.custom_range_edit.isEnabled()
    dialog.deleteLater()


def test_dialog_custom_range_with_multi_lang_produces_request(qapp):
    dialog = OcrDialog(total_pages=10, current_page=3, preferences=_make_prefs())
    dialog.custom_radio.setChecked(True)
    dialog.custom_range_edit.setText("1,3-5,9")
    dialog.set_language_checked(OcrLanguage.ENGLISH.value, True)
    dialog.set_language_checked(OcrLanguage.TRAD_CHINESE.value, True)
    qapp.processEvents()

    dialog.accept()
    request = dialog.get_request()
    assert isinstance(request, OcrRequest)
    assert request.page_indices == (0, 2, 3, 4, 8)
    assert set(request.languages) == {"en", "zh-Hant"}


def test_dialog_current_page_option_returns_current_index(qapp):
    dialog = OcrDialog(total_pages=10, current_page=7, preferences=_make_prefs(languages=["en"]))
    dialog.accept()
    request = dialog.get_request()
    assert request is not None
    assert request.page_indices == (6,)  # 0-based


def test_dialog_whole_document_returns_all_pages(qapp):
    dialog = OcrDialog(total_pages=4, current_page=1, preferences=_make_prefs(languages=["en"]))
    dialog.all_radio.setChecked(True)
    qapp.processEvents()
    dialog.accept()
    request = dialog.get_request()
    assert request is not None
    assert request.page_indices == (0, 1, 2, 3)


def test_dialog_invalid_range_disables_ok(qapp):
    dialog = OcrDialog(total_pages=10, current_page=1, preferences=_make_prefs(languages=["en"]))
    dialog.custom_radio.setChecked(True)
    dialog.custom_range_edit.setText("abc")
    qapp.processEvents()
    ok_button = dialog.button_box.button(QDialogButtonBox.Ok)
    assert not ok_button.isEnabled()
    assert dialog.validation_label.text() != ""


def test_dialog_validation_clears_when_range_fixed(qapp):
    dialog = OcrDialog(total_pages=10, current_page=1, preferences=_make_prefs(languages=["en"]))
    dialog.custom_radio.setChecked(True)
    dialog.custom_range_edit.setText("abc")
    qapp.processEvents()
    ok_button = dialog.button_box.button(QDialogButtonBox.Ok)
    assert not ok_button.isEnabled()

    dialog.custom_range_edit.setText("1,3")
    qapp.processEvents()
    assert ok_button.isEnabled()
    assert dialog.validation_label.text() == ""


def test_dialog_reject_returns_none(qapp):
    dialog = OcrDialog(total_pages=10, current_page=1, preferences=_make_prefs(languages=["en"]))
    dialog.reject()
    assert dialog.get_request() is None


def test_dialog_no_languages_selected_disables_ok(qapp):
    dialog = OcrDialog(total_pages=10, current_page=1, preferences=_make_prefs(languages=["en"]))
    dialog.set_language_checked("en", False)
    qapp.processEvents()
    ok_button = dialog.button_box.button(QDialogButtonBox.Ok)
    assert not ok_button.isEnabled()


def test_dialog_seeds_device_from_preferences(qapp):
    prefs = _make_prefs(device="cuda", languages=["en"])
    dialog = OcrDialog(total_pages=10, current_page=1, preferences=prefs)
    assert dialog.device_combo.currentData() in ("auto", "cuda")


def test_dialog_persists_device_choice_to_preferences(qapp):
    store = _FakeStore()
    prefs = UserPreferences(store=store)
    prefs.set_ocr_languages(["en"])
    dialog = OcrDialog(total_pages=10, current_page=1, preferences=prefs)
    # Select a different device.
    cuda_index = dialog.device_combo.findData("cuda")
    assert cuda_index >= 0
    dialog.device_combo.setCurrentIndex(cuda_index)
    qapp.processEvents()
    dialog.accept()
    _ = dialog.get_request()
    assert prefs.get_ocr_device() in ("auto", "cuda")


def test_dialog_request_carries_device(qapp):
    prefs = _make_prefs(device="cpu", languages=["en"])
    dialog = OcrDialog(total_pages=5, current_page=1, preferences=prefs)
    dialog.accept()
    request = dialog.get_request()
    assert request is not None
    assert request.device == "cpu"


def test_dialog_pre_checks_languages_from_preferences(qapp):
    prefs = _make_prefs(languages=["zh-Hant", "ja"])
    dialog = OcrDialog(total_pages=5, current_page=1, preferences=prefs)
    assert not dialog.is_language_checked("en")
    assert dialog.is_language_checked("zh-Hant")
    assert dialog.is_language_checked("ja")


def test_dialog_disables_cuda_and_mps_when_unavailable(qapp, monkeypatch):
    import view.dialogs.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "_is_device_available", lambda d: d in ("auto", "cpu"))

    dialog = ocr_mod.OcrDialog(total_pages=3, current_page=1, preferences=_make_prefs(languages=["en"]))
    model = dialog.device_combo.model()
    cuda_idx = dialog.device_combo.findData("cuda")
    mps_idx = dialog.device_combo.findData("mps")
    assert cuda_idx >= 0
    assert mps_idx >= 0
    assert not model.item(cuda_idx).isEnabled()
    assert not model.item(mps_idx).isEnabled()
    assert model.item(dialog.device_combo.findData("cpu")).isEnabled()
    assert model.item(dialog.device_combo.findData("auto")).isEnabled()
    dialog.deleteLater()


def test_dialog_default_falls_back_when_stored_pref_unavailable(qapp, monkeypatch):
    """If saved preference is CUDA but CUDA is unavailable, dialog selects auto."""
    import view.dialogs.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "_is_device_available", lambda d: d in ("auto", "cpu"))
    prefs = _make_prefs(device="cuda", languages=["en"])
    dialog = ocr_mod.OcrDialog(total_pages=3, current_page=1, preferences=prefs)
    assert dialog.device_combo.currentData() == "auto"
    dialog.deleteLater()
