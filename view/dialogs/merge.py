from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


class MergePdfDialog(QDialog):
    def __init__(self, session_model, parent=None, file_resolver=None, progress_factory=None):
        super().__init__(parent)
        self.session_model = session_model
        self.file_resolver = file_resolver
        self.progress_factory = progress_factory or self._create_progress_dialog
        self.setWindowTitle("合併 PDF")
        self._build_ui()
        self._refresh_file_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        mode_row = QHBoxLayout()
        self.new_file_radio = QRadioButton("建立新檔")
        self.merge_current_radio = QRadioButton("合併到目前檔案")
        self.new_file_radio.setChecked(True)
        mode_row.addWidget(self.new_file_radio)
        mode_row.addWidget(self.merge_current_radio)
        layout.addLayout(mode_row)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.file_list.setDefaultDropAction(Qt.MoveAction)
        self.file_list.model().rowsMoved.connect(self._sync_session_model_from_file_list)
        layout.addWidget(self.file_list)

        button_row = QHBoxLayout()
        self.select_button = QPushButton("選擇檔案")
        self.select_button.clicked.connect(self._select_files)
        self.delete_button = QPushButton("刪除檔案")
        self.delete_button.clicked.connect(self._delete_selected)
        button_row.addWidget(self.select_button)
        button_row.addWidget(self.delete_button)
        layout.addLayout(button_row)

        self.confirm_button = QPushButton("確認合併")
        self.confirm_button.clicked.connect(self.accept)
        layout.addWidget(self.confirm_button)
        self._update_buttons()

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        for entry in self.session_model.entries:
            item = QListWidgetItem(entry.display_name)
            item.setData(Qt.UserRole, entry.entry_id)
            item.setData(Qt.UserRole + 1, entry)
            self.file_list.addItem(item)
        self._update_buttons()

    def _select_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇要合併的 PDF", "", "PDF (*.pdf)")
        if not paths:
            return

        self._sync_session_model_from_file_list()
        resolved_entries: list[dict] = []
        progress = self.progress_factory(len(paths))
        progress.show()
        progress.setValue(0)
        try:
            for index, path in enumerate(paths, start=1):
                if progress.wasCanceled():
                    break
                if self.file_resolver is None:
                    resolved_entries.append(
                        {
                            "source_kind": "file",
                            "path": path,
                            "display_name": Path(path).name,
                        }
                    )
                else:
                    resolved = self.file_resolver({"source_kind": "file", "path": path})
                    if resolved is not None:
                        resolved_entries.append(resolved)
                progress.setValue(index)
                QApplication.processEvents()
        finally:
            progress.close()

        self.session_model.add_resolved_files(resolved_entries)
        self._refresh_file_list()

    def _delete_selected(self) -> None:
        self._sync_session_model_from_file_list()
        entry_ids: list[str] = []
        for item in self.file_list.selectedItems():
            entry_id = item.data(Qt.UserRole)
            if entry_id:
                entry_ids.append(entry_id)
        if not entry_ids:
            return
        self.session_model.remove_entries(entry_ids)
        self._refresh_file_list()

    def _sync_session_model_from_file_list(self, *_args) -> None:
        entry_ids: list[str] = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            entry_id = item.data(Qt.UserRole)
            if entry_id:
                entry_ids.append(entry_id)
        self.session_model.set_order(entry_ids)

    def _update_buttons(self) -> None:
        self.confirm_button.setEnabled(self.session_model.can_confirm)

    def selected_mode(self) -> str:
        return "merge_current" if self.merge_current_radio.isChecked() else "new_file"

    def ordered_entries(self) -> list:
        entries: list = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            entry = item.data(Qt.UserRole + 1)
            if entry is not None:
                entries.append(entry)
        return entries

    def _create_progress_dialog(self, total: int) -> QProgressDialog:
        progress = QProgressDialog("處理選取的 PDF...", "取消", 0, max(0, total), self)
        progress.setWindowTitle("加入合併清單")
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        return progress
