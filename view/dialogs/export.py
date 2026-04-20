from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from utils.helpers import parse_pages


class ExportPagesDialog(QDialog):
    _DPI_OPTIONS = [72, 96, 144, 300, 400, 600, 1200, 2400]

    def __init__(self, parent=None, total_pages: int = 1, current_page: int = 1):
        super().__init__(parent)
        self.total_pages = max(1, total_pages)
        self.current_page = min(max(1, current_page), self.total_pages)
        self.setWindowTitle("匯出頁面")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.current_page_radio = QRadioButton("當前頁")
        self.selected_pages_radio = QRadioButton("指定頁面")
        self.current_page_radio.setChecked(True)
        self.current_page_radio.toggled.connect(self._on_scope_changed)

        scope_row = QHBoxLayout()
        scope_row.addWidget(self.current_page_radio)
        scope_row.addWidget(self.selected_pages_radio)
        scope_row.addStretch(1)
        scope_widget = QWidget()
        scope_widget.setLayout(scope_row)
        form_layout.addRow("頁面範圍:", scope_widget)

        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText("例如: 1,3-5")
        self.pages_edit.setEnabled(False)

        self.page_count_label = QLabel(f"/ {self.total_pages}")
        self.page_count_label.setWordWrap(False)
        self.page_count_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        fm = QFontMetrics(self.page_count_label.font())
        # Reserve enough width so the inline counter text is not clipped on narrow layouts.
        min_width = max(
            fm.horizontalAdvance(self.page_count_label.text()),
            fm.horizontalAdvance("總頁數: 99999"),
        ) + 12
        self.page_count_label.setMinimumWidth(min_width)

        page_row = QHBoxLayout()
        page_row.addWidget(self.pages_edit, 1)
        page_row.addWidget(
            self.page_count_label,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        page_widget = QWidget()
        page_widget.setLayout(page_row)
        form_layout.addRow("指定頁面:", page_widget)

        self.dpi_combo = QComboBox()
        for dpi in self._DPI_OPTIONS:
            self.dpi_combo.addItem(str(dpi), dpi)
        dpi_idx = self.dpi_combo.findData(300)
        self.dpi_combo.setCurrentIndex(dpi_idx if dpi_idx >= 0 else 0)
        form_layout.addRow("DPI:", self.dpi_combo)

        self.output_combo = QComboBox()
        self.output_combo.addItem("PDF", False)
        self.output_combo.addItem("影像", True)
        form_layout.addRow("匯出格式:", self.output_combo)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_scope_changed(self, checked: bool):
        self.pages_edit.setEnabled(not checked)

    def get_values(self) -> tuple[list[int], int, bool]:
        if self.current_page_radio.isChecked():
            pages = [self.current_page]
        else:
            pages_text = self.pages_edit.text().strip()
            if not pages_text:
                raise ValueError("請輸入指定頁面頁碼")
            try:
                pages = parse_pages(pages_text, self.total_pages)
            except ValueError as exc:
                raise ValueError("頁碼格式錯誤，請使用例如 1,3-5") from exc
            if not pages:
                raise ValueError(f"頁碼必須在 1 到 {self.total_pages} 之間")

        dpi = int(self.dpi_combo.currentData())
        as_image = bool(self.output_combo.currentData())
        return pages, dpi, as_image
