from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_load_app_icon_returns_non_null(qapp):
    """The vendored app icon asset loads into a usable (non-null) QIcon."""
    from view.icons import load_app_icon

    assert not load_app_icon().isNull()


def test_app_icon_propagates_to_main_window(qapp):
    """App-level icon (set in main.py) propagates to PDFView via Qt inheritance."""
    from view.icons import load_app_icon
    from view.pdf_view import PDFView

    qapp.setWindowIcon(load_app_icon())
    view = PDFView()
    try:
        assert not qapp.windowIcon().isNull()
        assert not view.windowIcon().isNull()
    finally:
        view.close()
