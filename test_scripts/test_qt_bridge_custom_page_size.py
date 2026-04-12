from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPageLayout

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing import qt_bridge as qtb
from src.printing.base_driver import PrintJobOptions


class _LayoutPrinter:
    def __init__(self) -> None:
        self._layout = QPageLayout()

    def pageLayout(self):
        return self._layout

    def setPageLayout(self, layout) -> None:
        self._layout = layout


def test_set_page_layout_keeps_landscape_custom_pages_landscape() -> None:
    printer = _LayoutPrinter()

    qtb._set_page_layout(
        printer,
        QRectF(0.0, 0.0, 1190.5, 841.9),
        PrintJobOptions(paper_size="auto", orientation="auto"),
    )

    rect = printer.pageLayout().fullRectPoints()
    assert rect.width() > rect.height()
