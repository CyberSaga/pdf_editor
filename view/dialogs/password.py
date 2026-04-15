from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class PDFPasswordDialog(QDialog):
    """開啟加密 PDF 時輸入密碼的對話框"""

    def __init__(self, parent=None, file_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("PDF 需要密碼")
        self._file_path = file_path
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        if self._file_path:
            layout.addWidget(QLabel(f"此檔案受密碼保護，請輸入密碼：\n{self._file_path}"))
        else:
            layout.addWidget(QLabel("此 PDF 受密碼保護，請輸入密碼："))
        # 預設明碼顯示；旁邊勾選欄（眼睛符號）可切換為暗碼
        row = QHBoxLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Normal)  # 預設明碼
        self.password_edit.setPlaceholderText("輸入 PDF 密碼")
        row.addWidget(self.password_edit)
        self.hide_password_cb = QCheckBox("👁")  # 眼睛符號，實為勾選欄
        self.hide_password_cb.setToolTip("勾選後以密碼方式隱藏輸入")
        self.hide_password_cb.toggled.connect(self._on_show_hide_toggled)
        row.addWidget(self.hide_password_cb)
        layout.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_show_hide_toggled(self, checked: bool):
        """勾選時改為暗碼，取消勾選時改為明碼。"""
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
        )

    def get_password(self) -> str:
        return self.password_edit.text().strip()
