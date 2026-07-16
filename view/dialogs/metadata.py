from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


class MetadataDialog(QDialog):
    """Edit the user-facing standard PDF metadata fields."""

    def __init__(self, initial: dict[str, object] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文件資訊")
        values = initial or {}
        self.title_edit = QLineEdit(str(values.get("title") or ""))
        self.author_edit = QLineEdit(str(values.get("author") or ""))
        self.subject_edit = QLineEdit(str(values.get("subject") or ""))
        self.keywords_edit = QLineEdit(str(values.get("keywords") or ""))

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("標題", self.title_edit)
        form.addRow("作者", self.author_edit)
        form.addRow("主旨", self.subject_edit)
        form.addRow("關鍵字", self.keywords_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def metadata_values(self) -> dict[str, str]:
        return {
            "title": self.title_edit.text(),
            "author": self.author_edit.text(),
            "subject": self.subject_edit.text(),
            "keywords": self.keywords_edit.text(),
        }
