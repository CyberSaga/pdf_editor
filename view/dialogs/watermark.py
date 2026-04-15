from __future__ import annotations

from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QColor

from utils.helpers import parse_pages


class WatermarkDialog(QDialog):
    """浮水印新增/編輯對話框"""

    def __init__(self, parent=None, total_pages: int = 1, edit_data: dict = None):
        super().__init__(parent)
        self.setWindowTitle("編輯浮水印" if edit_data else "添加浮水印")
        self.edit_data = edit_data
        self.total_pages = max(1, total_pages)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form = QWidget()
        form_layout = QFormLayout(form)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("輸入浮水印文字（可多行，每行換行）")
        self.text_edit.setMaximumHeight(80)
        form_layout.addRow("浮水印文字:", self.text_edit)

        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText(f"如: 1,3-5 或留空套用全部 (1-{self.total_pages})")
        self.pages_edit.setText("全部")
        form_layout.addRow("套用頁面:", self.pages_edit)

        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(-360, 360)
        self.angle_spin.setValue(45)
        self.angle_spin.setSuffix("°")
        form_layout.addRow("旋轉角度:", self.angle_spin)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(0.4)
        form_layout.addRow("透明度:", self.opacity_spin)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 200)
        self.font_size_spin.setValue(48)
        form_layout.addRow("字型大小:", self.font_size_spin)

        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(0.8, 3.0)
        self.line_spacing_spin.setSingleStep(0.1)
        self.line_spacing_spin.setValue(1.3)
        self.line_spacing_spin.setToolTip("行距倍率，相對於字型大小（1.0=緊密，1.3=預設，2.0=寬鬆）")
        form_layout.addRow("行距倍率:", self.line_spacing_spin)

        self.color_btn = QPushButton()
        self.watermark_color = QColor(180, 180, 180)
        self.color_btn.setStyleSheet("background-color: rgb(180,180,180);")
        self.color_btn.clicked.connect(self._choose_color)
        form_layout.addRow("顏色:", self.color_btn)

        self.font_combo = QComboBox()
        self.font_combo.addItems(["china-ts", "china-ss", "helv", "cour", "Helvetica"])
        self.font_combo.setCurrentText("china-ts")
        self.font_combo.setToolTip("china-ts 適用繁體中文，china-ss 適用簡體中文")
        form_layout.addRow("字型:", self.font_combo)

        self.offset_x_spin = QDoubleSpinBox()
        self.offset_x_spin.setRange(-500, 500)
        self.offset_x_spin.setSuffix(" pt")
        self.offset_x_spin.setToolTip("正數向右、負數向左")
        form_layout.addRow("水平偏移:", self.offset_x_spin)

        self.offset_y_spin = QDoubleSpinBox()
        self.offset_y_spin.setRange(-500, 500)
        self.offset_y_spin.setSuffix(" pt")
        self.offset_y_spin.setToolTip("正數向下、負數向上")
        form_layout.addRow("垂直偏移:", self.offset_y_spin)

        scroll.setWidget(form)
        layout.addWidget(scroll)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        if self.edit_data:
            self.text_edit.setPlainText(self.edit_data.get("text", ""))
            pages = self.edit_data.get("pages", [])
            self.pages_edit.setText(",".join(str(p) for p in sorted(pages)) if pages else f"1-{self.total_pages}")
            self.angle_spin.setValue(self.edit_data.get("angle", 45))
            self.opacity_spin.setValue(self.edit_data.get("opacity", 0.4))
            self.font_size_spin.setValue(self.edit_data.get("font_size", 48))
            c = self.edit_data.get("color", (0.7, 0.7, 0.7))
            self.watermark_color = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
            self.color_btn.setStyleSheet(f"background-color: rgb({self.watermark_color.red()},{self.watermark_color.green()},{self.watermark_color.blue()});")
            font_name = self.edit_data.get("font", "helv")
            idx = self.font_combo.findText(font_name)
            self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.offset_x_spin.setValue(self.edit_data.get("offset_x", 0))
            self.offset_y_spin.setValue(self.edit_data.get("offset_y", 0))
            self.line_spacing_spin.setValue(self.edit_data.get("line_spacing", 1.3))

    def _choose_color(self):
        c = QColorDialog.getColor(self.watermark_color, self, "選擇浮水印顏色")
        if c.isValid():
            self.watermark_color = c
            self.color_btn.setStyleSheet(f"background-color: rgb({c.red()},{c.green()},{c.blue()});")

    def get_values(self):
        text = self.text_edit.toPlainText().strip()
        pages_str = self.pages_edit.text().strip()
        if not pages_str or pages_str.lower() in ("全部", "all"):
            pages = list(range(1, self.total_pages + 1))
        else:
            try:
                pages = parse_pages(pages_str, self.total_pages)
            except ValueError:
                pages = [1]
        angle = self.angle_spin.value()
        opacity = self.opacity_spin.value()
        font_size = self.font_size_spin.value()
        color = (self.watermark_color.red()/255.0, self.watermark_color.green()/255.0, self.watermark_color.blue()/255.0)
        font = self.font_combo.currentText()
        offset_x = self.offset_x_spin.value()
        offset_y = self.offset_y_spin.value()
        line_spacing = self.line_spacing_spin.value()
        return pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing
