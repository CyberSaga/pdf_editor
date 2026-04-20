from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from model.pdf_optimizer import PdfAuditReport


class AuditStackedBar(QWidget):
    hovered_label_changed = Signal(str)
    _COLORS = ["#0EA5E9", "#22C55E", "#F59E0B", "#EF4444", "#64748B", "#A855F7"]

    def __init__(self, report: PdfAuditReport, parent=None):
        super().__init__(parent)
        self._segments: list[QFrame] = []
        self._segment_labels: dict[QFrame, str] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        meaningful = [item for item in report.items if item.bytes_used > 0]
        for index, item in enumerate(meaningful):
            segment = QFrame(self)
            segment.setStyleSheet(
                f"background: {self._COLORS[index % len(self._COLORS)]}; border-radius: 4px;"
            )
            stretch = max(1, int(round(item.percent)))
            layout.addWidget(segment, stretch)
            # Keep hover text minimal so users can quickly identify each object type.
            segment.setToolTip(item.label)
            segment.setMouseTracking(True)
            segment.setAttribute(Qt.WA_Hover, True)
            segment.installEventFilter(self)
            self._segment_labels[segment] = item.label
            self._segments.append(segment)
        self.setMinimumHeight(18)

    def segment_count(self) -> int:
        return len(self._segments)

    def segment_tooltips(self) -> list[str]:
        return [segment.toolTip() for segment in self._segments if segment.toolTip()]

    def _show_segment_name(self, segment: QFrame) -> None:
        label = self._segment_labels.get(segment, "")
        if not label:
            return
        self.hovered_label_changed.emit(label)
        QToolTip.showText(QCursor.pos(), label, segment)

    def eventFilter(self, watched, event):
        if watched in self._segment_labels:
            if event.type() in (QEvent.Enter, QEvent.MouseMove, QEvent.ToolTip):
                self._show_segment_name(watched)
                return event.type() == QEvent.ToolTip
            if event.type() == QEvent.Leave:
                self.hovered_label_changed.emit("")
        return super().eventFilter(watched, event)


class PdfAuditReportDialog(QDialog):
    def __init__(self, report: PdfAuditReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("審計空間使用報告")
        self.resize(620, 460)
        layout = QVBoxLayout(self)

        summary = QLabel(
            f"現用 PDF 版本: {report.pdf_version}\n"
            f"相容性: {report.compatibility}\n"
            f"總大小: {report.total_bytes:,} bytes"
        )
        layout.addWidget(summary)

        self.hover_name_label = QLabel("將游標移到色塊上以查看物件種類")
        layout.addWidget(self.hover_name_label)
        self.stacked_bar = AuditStackedBar(report, self)
        self.stacked_bar.hovered_label_changed.connect(self._on_stacked_bar_hovered)
        layout.addWidget(self.stacked_bar)

        self.table = QTableWidget(len(report.items), 4, self)
        self.table.setHorizontalHeaderLabels(["物件種類", "數量", "Bytes", "百分比"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        for row, item in enumerate(report.items):
            bytes_text = f"{item.bytes_used:,}" if item.bytes_used else "--"
            percent_text = f"{item.percent:.2f}%" if item.bytes_used else "--"
            count_text = str(item.count) if item.count else "--"
            self.table.setItem(row, 0, QTableWidgetItem(item.label))
            self.table.setItem(row, 1, QTableWidgetItem(count_text))
            self.table.setItem(row, 2, QTableWidgetItem(bytes_text))
            self.table.setItem(row, 3, QTableWidgetItem(percent_text))
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).setText("關閉")
        layout.addWidget(buttons)

    def _on_stacked_bar_hovered(self, label: str) -> None:
        if label:
            self.hover_name_label.setText(f"目前: {label}")
            return
        self.hover_name_label.setText("將游標移到色塊上以查看物件種類")
