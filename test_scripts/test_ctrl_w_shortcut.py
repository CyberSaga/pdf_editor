from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from view.pdf_view import PDFView


def _ctrl_w_shortcuts(view: PDFView) -> list[QShortcut]:
    return [
        shortcut
        for shortcut in view.findChildren(QShortcut)
        if shortcut.key().matches(QKeySequence("Ctrl+W")) == QKeySequence.ExactMatch
    ]


def test_ctrl_w_requests_close_for_current_tab(qapp) -> None:
    view = PDFView()
    requested: list[int] = []
    view.sig_tab_close_requested.connect(requested.append)
    try:
        view.set_document_tabs(
            [
                {"id": "one", "display_name": "one.pdf"},
                {"id": "two", "display_name": "two.pdf"},
            ],
            active_index=1,
        )

        shortcuts = _ctrl_w_shortcuts(view)
        assert len(shortcuts) == 1
        assert shortcuts[0].context() == Qt.ShortcutContext.WidgetWithChildrenShortcut

        shortcuts[0].activated.emit()

        assert requested == [1]
    finally:
        view.close()
        view.deleteLater()


def test_ctrl_w_is_noop_with_no_document_tabs(qapp) -> None:
    view = PDFView()
    requested: list[int] = []
    view.sig_tab_close_requested.connect(requested.append)
    try:
        shortcuts = _ctrl_w_shortcuts(view)
        assert len(shortcuts) == 1

        shortcuts[0].activated.emit()

        assert requested == []
    finally:
        view.close()
        view.deleteLater()
