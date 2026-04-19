from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from model.tools.ocr_types import (
    OcrDevice,
    OcrLanguage,
    OcrRequest,
    parse_page_range,
)
from model.tools.ocr_tool import _is_device_available
from utils.preferences import UserPreferences

logger = logging.getLogger(__name__)


_LANGUAGE_LABELS: list[tuple[OcrLanguage, str]] = [
    (OcrLanguage.ENGLISH, "English"),
    (OcrLanguage.TRAD_CHINESE, "繁體中文"),
    (OcrLanguage.SIMP_CHINESE, "简体中文"),
    (OcrLanguage.JAPANESE, "日本語"),
]

_DEVICE_LABELS: list[tuple[str, str]] = [
    (OcrDevice.AUTO.value, "自動 (優先使用 GPU)"),
    (OcrDevice.CUDA.value, "GPU (CUDA)"),
    (OcrDevice.MPS.value, "GPU (Apple Silicon / MPS)"),
    (OcrDevice.CPU.value, "CPU"),
]


class OcrDialog(QDialog):
    """Collects OCR options (page scope, languages, device) from the user."""

    def __init__(
        self,
        parent=None,
        total_pages: int = 1,
        current_page: int = 1,
        preferences: UserPreferences | None = None,
    ) -> None:
        super().__init__(parent)
        self._total_pages = max(1, int(total_pages))
        self._current_page = min(max(1, int(current_page)), self._total_pages)
        self._preferences = preferences or UserPreferences()
        self._language_checkboxes: dict[str, QCheckBox] = {}
        self._request: OcrRequest | None = None

        self.setWindowTitle("OCR 文字辨識")
        self._build_ui()
        self._connect_signals()
        self._refresh_validation()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        form = QFormLayout()

        self.current_page_radio = QRadioButton(f"當前頁 ({self._current_page})")
        self.all_radio = QRadioButton(f"整份文件 (1-{self._total_pages})")
        self.custom_radio = QRadioButton("自訂頁面範圍")
        self.current_page_radio.setChecked(True)

        self._scope_group = QButtonGroup(self)
        for btn in (self.current_page_radio, self.all_radio, self.custom_radio):
            self._scope_group.addButton(btn)

        scope_box = QVBoxLayout()
        scope_box.addWidget(self.current_page_radio)
        scope_box.addWidget(self.all_radio)
        scope_box.addWidget(self.custom_radio)
        scope_widget = QWidget()
        scope_widget.setLayout(scope_box)
        form.addRow("頁面範圍:", scope_widget)

        self.custom_range_edit = QLineEdit()
        self.custom_range_edit.setPlaceholderText("例如: 1,3-5,9")
        self.custom_range_edit.setEnabled(False)
        form.addRow("自訂頁碼:", self.custom_range_edit)

        languages_widget = QWidget()
        languages_layout = QVBoxLayout(languages_widget)
        languages_layout.setContentsMargins(0, 0, 0, 0)
        seeded = set(self._preferences.get_ocr_languages())
        for language, label in _LANGUAGE_LABELS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(language.value in seeded)
            self._language_checkboxes[language.value] = checkbox
            languages_layout.addWidget(checkbox)
        form.addRow("辨識語言:", languages_widget)

        self.device_combo = QComboBox()
        combo_model = self.device_combo.model()
        for value, label in _DEVICE_LABELS:
            self.device_combo.addItem(label, value)
            available = _is_device_available(value)
            item = combo_model.item(self.device_combo.count() - 1) if hasattr(combo_model, "item") else None
            if item is not None and not available:
                item.setEnabled(False)
                item.setToolTip("此裝置目前不可用 (torch 不支援)")

        stored = self._preferences.get_ocr_device()
        if not _is_device_available(stored):
            stored = OcrDevice.AUTO.value
        device_idx = self.device_combo.findData(stored)
        if device_idx >= 0:
            self.device_combo.setCurrentIndex(device_idx)
        form.addRow("運算裝置:", self.device_combo)

        main_layout.addLayout(form)

        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: #b00020;")
        self.validation_label.setWordWrap(True)
        main_layout.addWidget(self.validation_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(self.button_box)

    def _connect_signals(self) -> None:
        self.custom_radio.toggled.connect(self._on_scope_changed)
        self.custom_range_edit.textChanged.connect(self._refresh_validation)
        for btn in (self.current_page_radio, self.all_radio, self.custom_radio):
            btn.toggled.connect(self._refresh_validation)
        for checkbox in self._language_checkboxes.values():
            checkbox.toggled.connect(self._refresh_validation)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _on_scope_changed(self, _checked: bool) -> None:
        self.custom_range_edit.setEnabled(self.custom_radio.isChecked())
        self._refresh_validation()

    def _selected_languages(self) -> list[str]:
        return [code for code, checkbox in self._language_checkboxes.items() if checkbox.isChecked()]

    def _resolve_page_indices(self) -> list[int]:
        if self.current_page_radio.isChecked():
            return [self._current_page - 1]
        if self.all_radio.isChecked():
            return list(range(self._total_pages))
        raw = self.custom_range_edit.text()
        return parse_page_range(raw, total_pages=self._total_pages)

    def _refresh_validation(self) -> None:
        message = ""
        try:
            indices = self._resolve_page_indices()
        except ValueError as exc:
            message = str(exc)
            indices = []
        if not message and not indices:
            message = "未選擇任何頁面"
        if not message and not self._selected_languages():
            message = "請至少選擇一種辨識語言"
        self.validation_label.setText(message)
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setEnabled(not message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_language_checked(self, code: str, checked: bool) -> None:
        checkbox = self._language_checkboxes.get(code)
        if checkbox is not None:
            checkbox.setChecked(checked)

    def is_language_checked(self, code: str) -> bool:
        checkbox = self._language_checkboxes.get(code)
        return bool(checkbox and checkbox.isChecked())

    def accept(self) -> None:  # type: ignore[override]
        try:
            indices = self._resolve_page_indices()
        except ValueError as exc:
            self.validation_label.setText(str(exc))
            return
        languages = self._selected_languages()
        if not indices or not languages:
            self.validation_label.setText("請完成頁面與語言設定")
            return
        device = self.device_combo.currentData() or OcrDevice.AUTO.value
        if not _is_device_available(device):
            device = OcrDevice.AUTO.value
        try:
            self._preferences.set_ocr_device(device)
            self._preferences.set_ocr_languages(languages)
        except ValueError:
            logger.exception("Failed to persist OCR preferences")
        self._request = OcrRequest(
            page_indices=tuple(indices),
            languages=tuple(languages),
            device=device,
        )
        super().accept()

    def reject(self) -> None:  # type: ignore[override]
        self._request = None
        super().reject()

    def get_request(self) -> OcrRequest | None:
        return self._request
