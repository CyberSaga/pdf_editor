from __future__ import annotations

import fitz
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class _NoteDragBar(QFrame):
    def __init__(self, owner: FloatingNote) -> None:
        super().__init__(owner)
        self._owner = owner
        self._press_global: QPoint | None = None
        self._start_pos: QPoint | None = None
        self.setStyleSheet("background-color: #d0d0d0; border: 1px solid #a0a0a0;")
        self.setCursor(Qt.OpenHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.addWidget(QLabel("註解", self))
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_pos = self._owner.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_global is not None and self._start_pos is not None:
            delta = event.globalPosition().toPoint() - self._press_global
            self._owner.move(self._start_pos + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_global = None
        self._start_pos = None
        event.accept()


class FloatingNote(QWidget):
    save_requested = Signal(int, int, str)
    delete_requested = Signal(int, int)
    marker_move_requested = Signal(int, int, object)

    def __init__(self, annotation: dict, parent: QWidget) -> None:
        super().__init__(parent, Qt.Widget | Qt.FramelessWindowHint)
        self._page_num = int(annotation["page_num"])
        self._xref = int(annotation["xref"])
        self._marker_rect = fitz.Rect(annotation["rect"])
        self.setObjectName("floatingNote")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(260, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(2)
        self.drag_bar = _NoteDragBar(self)
        layout.addWidget(self.drag_bar)
        self.editor = QTextEdit(self)
        self.editor.setPlainText(str(annotation.get("text", "")))
        layout.addWidget(self.editor, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton("儲存", self)
        self.delete_button = QPushButton("刪除", self)
        self.close_button = QPushButton("關閉", self)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.save_button.clicked.connect(self._emit_save)
        self.delete_button.clicked.connect(self._emit_delete)
        self.close_button.clicked.connect(self.close)

    def _emit_delete(self) -> None:
        self.delete_requested.emit(self._page_num, self._xref)
        self.close()

    def _emit_save(self) -> None:
        self.save_requested.emit(
            self._page_num,
            self._xref,
            self.editor.toPlainText(),
        )

    def request_marker_move(self, rect: fitz.Rect) -> None:
        self._marker_rect = fitz.Rect(rect)
        self.marker_move_requested.emit(
            self._page_num,
            self._xref,
            fitz.Rect(rect),
        )
