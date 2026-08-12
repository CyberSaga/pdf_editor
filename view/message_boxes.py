"""Shared message-box helpers (moved from utils/helpers.py in PR-8).

utils/ must stay Qt-widget-free and below every layer; a QMessageBox helper
belongs to the View layer. Controller importing view helpers is legal
(Controller coordinates View and Model).
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def show_error(parent, message: str) -> None:
    """Show an error message."""
    QMessageBox.critical(parent, "錯誤", message)


def confirm_degraded_fallback(parent, message: str) -> bool:
    """Ask the user to confirm a legacy-fidelity fallback commit before it
    happens. Defaults to No (Esc/close = decline, never a silent proceed)."""
    result = QMessageBox.question(
        parent,
        "確認降級提交",
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes
