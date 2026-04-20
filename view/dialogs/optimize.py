from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from model.pdf_model import PDFModel
from model.pdf_optimizer import PdfOptimizeOptions
from utils.helpers import show_error

from .audit import PdfAuditReportDialog


class OptimizePdfDialog(QDialog):
    def __init__(self, parent=None, audit_provider=None):
        super().__init__(parent)
        self.audit_provider = audit_provider
        self._applying_preset = False
        self.setWindowTitle("優化 PDF")
        self.resize(560, 680)
        self._build_ui()
        self._apply_preset("平衡")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("設定:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["快速", "平衡", "極致壓縮", "自訂"])
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        header.addWidget(self.preset_combo, 1)
        self.audit_button = QPushButton("審計空間使用報告")
        self.audit_button.setEnabled(self.audit_provider is not None)
        self.audit_button.clicked.connect(self._show_audit_report)
        header.addWidget(self.audit_button)
        layout.addLayout(header)

        self.info_label = QLabel("相容性: 保留現有")
        layout.addWidget(self.info_label)

        self.images_group = QGroupBox("圖像")
        images_layout = QFormLayout(self.images_group)
        self.images_checkbox = QCheckBox("啟用圖像最佳化")
        self.images_checkbox.setChecked(True)
        images_layout.addRow(self.images_checkbox)
        self.image_target_dpi_combo = QComboBox()
        self.image_target_dpi_combo.addItems(["72", "96", "110", "150", "220"])
        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.addWidget(self.image_target_dpi_combo)
        self.image_target_dpi_suffix = QLabel("dpi")
        target_row.addWidget(self.image_target_dpi_suffix)
        target_row.addStretch(1)
        images_layout.addRow("降採樣到", target_row)
        self.image_threshold_dpi_combo = QComboBox()
        self.image_threshold_dpi_combo.addItems(["144", "165", "225", "300"])
        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        threshold_row.addWidget(self.image_threshold_dpi_combo)
        self.image_threshold_dpi_suffix = QLabel("dpi")
        threshold_row.addWidget(self.image_threshold_dpi_suffix)
        threshold_row.addStretch(1)
        images_layout.addRow("當圖像超過", threshold_row)
        quality_row = QVBoxLayout()
        quality_row.setContentsMargins(0, 0, 0, 0)
        self.image_quality_slider = QSlider(Qt.Horizontal)
        self.image_quality_slider.setRange(0, 100)
        self.image_quality_slider.setSingleStep(5)
        self.image_quality_slider.setPageStep(10)
        self.image_quality_label = QLabel()
        quality_row.addWidget(self.image_quality_slider)
        quality_row.addWidget(self.image_quality_label)
        images_layout.addRow("JPEG 品質", quality_row)
        self.color_images_checkbox = QCheckBox("彩色圖像")
        self.gray_images_checkbox = QCheckBox("灰階圖像")
        self.bitonal_images_checkbox = QCheckBox("黑白圖像")
        for checkbox in (self.color_images_checkbox, self.gray_images_checkbox, self.bitonal_images_checkbox):
            checkbox.setChecked(True)
            images_layout.addRow(checkbox)
        layout.addWidget(self.images_group)

        self.fonts_group = QGroupBox("字體")
        fonts_layout = QVBoxLayout(self.fonts_group)
        self.fonts_checkbox = QCheckBox("啟用字體最佳化")
        self.fonts_checkbox.setChecked(True)
        self.font_subset_checkbox = QCheckBox("合併 / 子集化字體")
        self.font_subset_checkbox.setChecked(True)
        fonts_layout.addWidget(self.fonts_checkbox)
        fonts_layout.addWidget(self.font_subset_checkbox)
        layout.addWidget(self.fonts_group)

        self.user_data_group = QGroupBox("忽略用戶資料")
        user_data_layout = QVBoxLayout(self.user_data_group)
        self.metadata_checkbox = QCheckBox("移除檔案資訊和詮釋資料")
        self.xml_metadata_checkbox = QCheckBox("移除 XML 詮釋資料")
        user_data_layout.addWidget(self.metadata_checkbox)
        user_data_layout.addWidget(self.xml_metadata_checkbox)
        layout.addWidget(self.user_data_group)

        self.cleanup_group = QGroupBox("清除")
        cleanup_layout = QVBoxLayout(self.cleanup_group)
        self.cleanup_checkbox = QCheckBox("優化頁面內容")
        self.cleanup_checkbox.setChecked(True)
        self.deflate_streams_checkbox = QCheckBox("使用 Flate 模式對資料流進行編碼")
        self.deflate_images_checkbox = QCheckBox("壓縮圖片資料流")
        self.deflate_fonts_checkbox = QCheckBox("壓縮字體資料流")
        self.object_streams_checkbox = QCheckBox("使用物件串流")
        self.linearize_checkbox = QCheckBox("最佳化快速網頁檢視")
        for checkbox in (
            self.deflate_streams_checkbox,
            self.deflate_images_checkbox,
            self.deflate_fonts_checkbox,
            self.object_streams_checkbox,
        ):
            checkbox.setChecked(True)
        cleanup_layout.addWidget(self.cleanup_checkbox)
        cleanup_layout.addWidget(self.deflate_streams_checkbox)
        cleanup_layout.addWidget(self.deflate_images_checkbox)
        cleanup_layout.addWidget(self.deflate_fonts_checkbox)
        cleanup_layout.addWidget(self.object_streams_checkbox)
        cleanup_layout.addWidget(self.linearize_checkbox)
        layout.addWidget(self.cleanup_group)

        self._custom_controls = [
            self.images_checkbox,
            self.image_target_dpi_combo,
            self.image_threshold_dpi_combo,
            self.image_quality_slider,
            self.color_images_checkbox,
            self.gray_images_checkbox,
            self.bitonal_images_checkbox,
            self.fonts_checkbox,
            self.font_subset_checkbox,
            self.metadata_checkbox,
            self.xml_metadata_checkbox,
            self.cleanup_checkbox,
            self.deflate_streams_checkbox,
            self.deflate_images_checkbox,
            self.deflate_fonts_checkbox,
            self.object_streams_checkbox,
            self.linearize_checkbox,
        ]
        for control in self._custom_controls:
            if isinstance(control, QComboBox):
                control.currentTextChanged.connect(self._mark_custom)
            elif isinstance(control, QSlider):
                control.valueChanged.connect(self._mark_custom)
            else:
                control.toggled.connect(self._mark_custom)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("確定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_audit_report(self) -> None:
        if self.audit_provider is None:
            return
        try:
            report = self.audit_provider()
        except Exception as exc:
            show_error(self, f"審計空間使用報告失敗: {exc}")
            return
        PdfAuditReportDialog(report, self).exec()

    def _quality_value(self) -> int:
        return int(self.image_quality_slider.value())

    def _quality_label_from_value(self, value: int) -> str:
        if value <= 25:
            return "最低"
        if value <= 40:
            return "低"
        if value <= 60:
            return "中等"
        if value <= 78:
            return "高"
        return "最大"

    def _refresh_quality_label(self) -> None:
        value = self._quality_value()
        self.image_quality_label.setText(f"{self._quality_label_from_value(value)} ({value})")

    def _apply_preset(self, preset: str) -> None:
        options = PDFModel.preset_optimize_options(preset)
        self._applying_preset = True
        try:
            self.preset_combo.setCurrentText(options.preset)
            self.images_checkbox.setChecked(options.optimize_images)
            self.image_target_dpi_combo.setCurrentText(str(options.image_dpi_target))
            self.image_threshold_dpi_combo.setCurrentText(str(options.image_dpi_threshold))
            self.image_quality_slider.setValue(options.image_jpeg_quality)
            self._refresh_quality_label()
            self.color_images_checkbox.setChecked(options.optimize_color_images)
            self.gray_images_checkbox.setChecked(options.optimize_gray_images)
            self.bitonal_images_checkbox.setChecked(options.optimize_bitonal_images)
            self.fonts_checkbox.setChecked(options.optimize_fonts)
            self.font_subset_checkbox.setChecked(options.subset_fonts)
            self.metadata_checkbox.setChecked(options.remove_metadata)
            self.xml_metadata_checkbox.setChecked(options.remove_xml_metadata)
            self.cleanup_checkbox.setChecked(options.content_cleanup)
            self.deflate_streams_checkbox.setChecked(options.deflate_streams)
            self.deflate_images_checkbox.setChecked(options.deflate_images)
            self.deflate_fonts_checkbox.setChecked(options.deflate_fonts)
            self.object_streams_checkbox.setChecked(options.use_object_streams)
            self.linearize_checkbox.setChecked(options.linearize)
        finally:
            self._applying_preset = False

    def _on_preset_changed(self, preset: str) -> None:
        if self._applying_preset or preset == "自訂":
            return
        self._apply_preset(preset)

    def _mark_custom(self, *_args) -> None:
        if self._applying_preset:
            return
        self._refresh_quality_label()
        self._applying_preset = True
        try:
            self.preset_combo.setCurrentText("自訂")
        finally:
            self._applying_preset = False

    def get_options(self) -> PdfOptimizeOptions:
        return PdfOptimizeOptions(
            preset=self.preset_combo.currentText(),
            optimize_images=self.images_checkbox.isChecked(),
            image_dpi_target=int(self.image_target_dpi_combo.currentText()),
            image_dpi_threshold=int(self.image_threshold_dpi_combo.currentText()),
            image_jpeg_quality=self._quality_value(),
            optimize_color_images=self.color_images_checkbox.isChecked(),
            optimize_gray_images=self.gray_images_checkbox.isChecked(),
            optimize_bitonal_images=self.bitonal_images_checkbox.isChecked(),
            optimize_fonts=self.fonts_checkbox.isChecked(),
            subset_fonts=self.font_subset_checkbox.isChecked(),
            remove_metadata=self.metadata_checkbox.isChecked(),
            remove_xml_metadata=self.xml_metadata_checkbox.isChecked(),
            content_cleanup=self.cleanup_checkbox.isChecked(),
            deflate_streams=self.deflate_streams_checkbox.isChecked(),
            deflate_images=self.deflate_images_checkbox.isChecked(),
            deflate_fonts=self.deflate_fonts_checkbox.isChecked(),
            use_object_streams=self.object_streams_checkbox.isChecked(),
            linearize=self.linearize_checkbox.isChecked(),
            garbage_level=4 if self.preset_combo.currentText() == "極致壓縮" else 2 if self.preset_combo.currentText() == "快速" else 3,
            compression_effort=9 if self.preset_combo.currentText() == "極致壓縮" else 3 if self.preset_combo.currentText() == "快速" else 6,
        )
