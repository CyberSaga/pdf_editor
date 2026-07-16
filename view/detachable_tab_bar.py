from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QApplication, QTabBar


class DetachableTabBar(QTabBar):
    detach_requested = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pressed_session_id: str | None = None
        self._press_pos: QPoint | None = None
        self._detach_emitted = False

    def mousePressEvent(self, event) -> None:
        index = self.tabAt(event.position().toPoint())
        session_id = self.tabData(index) if index >= 0 else None
        self._pressed_session_id = session_id if isinstance(session_id, str) else None
        self._press_pos = event.position().toPoint()
        self._detach_emitted = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        session_id = self._pressed_session_id
        press_pos = self._press_pos
        release_pos = event.position().toPoint()
        distance = (release_pos - press_pos).manhattanLength() if press_pos is not None else 0
        outside = not self.rect().contains(release_pos)
        if (
            session_id is not None
            and not self._detach_emitted
            and outside
            and distance >= QApplication.startDragDistance()
            and event.button() == Qt.LeftButton
        ):
            self._detach_emitted = True
            self.detach_requested.emit(session_id, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        self._pressed_session_id = None
        self._press_pos = None
