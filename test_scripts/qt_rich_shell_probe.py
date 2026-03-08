from __future__ import annotations

import logging
import sys
import time
from typing import Any

_PROCESS_START = time.perf_counter()
_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


def _configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG, format=_LOG_FORMAT)
    return logging.getLogger(__name__)


def _log_probe_checkpoint(
    logger: logging.Logger,
    label: str,
    previous_checkpoint: float,
) -> float:
    now = time.perf_counter()
    logger.info(
        "rich_probe: %s total=%.3fs delta=%.3fs",
        label,
        now - _PROCESS_START,
        now - previous_checkpoint,
    )
    return now


def run(start_event_loop: bool = True) -> int | dict[str, Any]:
    logger = _configure_logging()
    checkpoint = _PROCESS_START
    checkpoint = _log_probe_checkpoint(logger, "logging_configured", checkpoint)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QGraphicsScene,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QPushButton,
        QSplitter,
        QStackedWidget,
        QStatusBar,
        QTabBar,
        QTabWidget,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )

    checkpoint = _log_probe_checkpoint(logger, "qt_imported", checkpoint)

    class RichShellWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self._checkpoint_logger = None
            self._markers_seen: set[str] = set()
            self._show_tick_scheduled = False

            self.setWindowTitle("Qt Rich Shell Probe")
            self.setMinimumSize(1280, 800)
            self.setGeometry(100, 100, 1280, 800)

            container = QWidget(self)
            self.setCentralWidget(container)
            root_layout = QVBoxLayout(container)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)

            top_container = QFrame()
            top_container.setFixedHeight(60)
            top_container.setStyleSheet("QFrame { background: #F1F5F9; border-bottom: 1px solid #E2E8F0; }")
            top_layout = QHBoxLayout(top_container)
            top_layout.setContentsMargins(6, 4, 6, 4)
            top_layout.setSpacing(6)

            top_tabs = QTabWidget()
            top_tabs.setDocumentMode(True)
            top_tabs.setStyleSheet(
                "QTabWidget::pane { border: none; background: transparent; top: 0px; }"
                "QTabBar::tab { min-width: 52px; padding: 5px 10px; margin-right: 2px; background: transparent; }"
                "QTabBar::tab:selected { background: #0078D4; color: white; border-radius: 4px; }"
            )

            for tab_name in ("File", "Common", "Edit", "Page", "Convert"):
                tab = QWidget()
                tab_layout = QVBoxLayout(tab)
                tab_layout.setContentsMargins(4, 0, 0, 0)
                toolbar = QToolBar()
                toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
                toolbar.addAction("Action A")
                toolbar.addAction("Action B")
                toolbar.addAction("Action C")
                tab_layout.addWidget(toolbar)
                top_tabs.addTab(tab, tab_name)

            right_controls = QWidget()
            right_layout = QHBoxLayout(right_controls)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.addWidget(QLabel("Page 1 / 1"))
            zoom_input = QLineEdit("100%")
            zoom_input.setFixedWidth(88)
            right_layout.addWidget(zoom_input)
            right_layout.addWidget(QPushButton("Fit"))
            top_layout.addWidget(top_tabs, 1)
            top_layout.addWidget(right_controls)
            root_layout.addWidget(top_container)

            doc_tab_bar = QTabBar(self)
            doc_tab_bar.setDocumentMode(True)
            doc_tab_bar.addTab("Untitled")
            root_layout.addWidget(doc_tab_bar)

            splitter = QSplitter(Qt.Horizontal)

            left_tabs = QTabWidget()
            left_tabs.addTab(QListWidget(), "Thumbs")
            left_tabs.addTab(QListWidget(), "Search")
            left_tabs.addTab(QListWidget(), "Notes")
            left_tabs.addTab(QListWidget(), "Watermarks")
            left_tabs.setMinimumWidth(200)
            left_tabs.setMaximumWidth(400)
            splitter.addWidget(left_tabs)

            scene = QGraphicsScene(self)
            view = QGraphicsView(self)
            view.setScene(scene)
            view.setStyleSheet("QGraphicsView { background: #F1F5F9; border: none; }")
            splitter.addWidget(view)

            right_panel = QWidget()
            right_panel_layout = QVBoxLayout(right_panel)
            right_panel_layout.setContentsMargins(0, 0, 0, 0)
            right_panel_layout.addWidget(QLabel("Properties"))
            right_stack = QStackedWidget()
            for label in ("Page Info", "Rect", "Highlight", "Text"):
                card = QWidget()
                card_layout = QVBoxLayout(card)
                card_layout.addWidget(QLabel(label))
                card_layout.addStretch()
                right_stack.addWidget(card)
            right_panel_layout.addWidget(right_stack)
            right_panel.setMinimumWidth(240)
            right_panel.setMaximumWidth(400)
            splitter.addWidget(right_panel)

            splitter.setSizes([260, 740, 280])
            root_layout.addWidget(splitter)

            status = QStatusBar(self)
            status.showMessage("Rich shell probe ready")
            self.setStatusBar(status)

            self.setStyleSheet(
                "QMainWindow { background: #F8FAFC; }"
                "QPushButton { border-radius: 6px; padding: 6px 12px; }"
                "QLineEdit { border-radius: 6px; padding: 4px 8px; border: 1px solid #E2E8F0; }"
            )

        def set_checkpoint_logger(self, callback) -> None:
            self._checkpoint_logger = callback

        def _emit_marker(self, label: str) -> None:
            if label in self._markers_seen:
                return
            self._markers_seen.add(label)
            callback = self._checkpoint_logger
            if callback is not None:
                callback(label)

        def showEvent(self, event) -> None:
            self._emit_marker("window_show_event")
            if not self._show_tick_scheduled:
                self._show_tick_scheduled = True
                QTimer.singleShot(0, lambda: self._emit_marker("window_first_event_loop_tick"))
            super().showEvent(event)

        def paintEvent(self, event) -> None:
            self._emit_marker("window_first_paint")
            super().paintEvent(event)

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    checkpoint = _log_probe_checkpoint(logger, "qapplication_created", checkpoint)

    window = RichShellWindow()
    checkpoint = _log_probe_checkpoint(logger, "window_created", checkpoint)

    checkpoint_state = {"value": checkpoint}

    def _log_window_lifecycle(label: str) -> None:
        checkpoint_state["value"] = _log_probe_checkpoint(
            logger,
            label,
            checkpoint_state["value"],
        )

    window.set_checkpoint_logger(_log_window_lifecycle)

    window.ensurePolished()
    checkpoint = _log_probe_checkpoint(logger, "window_polished", checkpoint)

    _ = window.winId()
    checkpoint = _log_probe_checkpoint(logger, "window_native_created", checkpoint)

    window.show()
    checkpoint = checkpoint_state["value"]
    checkpoint = _log_probe_checkpoint(logger, "window_shown", checkpoint)
    checkpoint = _log_probe_checkpoint(logger, "event_loop_ready", checkpoint)

    if not start_event_loop:
        return {"app": app, "window": window, "checkpoint": checkpoint}

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
