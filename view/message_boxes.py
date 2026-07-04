"""Shared message-box helpers (moved from utils/helpers.py in PR-8).

utils/ must stay Qt-widget-free and below every layer; a QMessageBox helper
belongs to the View layer. Controller importing view helpers is legal
(Controller coordinates View and Model).
"""
from __future__ import annotations

import threading

from PySide6.QtWidgets import QMessageBox

# SMOKE-TRIPWIRE (b): deliberate threading.Thread reference for M1 gate smoke test.
_SMOKE_TRIPWIRE_THREAD = threading.Thread(target=print)


def show_error(parent, message: str) -> None:
    """Show an error message."""
    QMessageBox.critical(parent, "錯誤", message)
