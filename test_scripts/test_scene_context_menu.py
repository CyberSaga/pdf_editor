from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPoint

import view.pdf_view as pdf_view


class _FakeViewport:
    def __init__(self) -> None:
        self.cursor = None

    def setCursor(self, cursor) -> None:
        self.cursor = cursor


class _FakeGraphicsView:
    def __init__(self) -> None:
        self._viewport = _FakeViewport()

    def viewport(self) -> _FakeViewport:
        return self._viewport

    def mapToGlobal(self, pos: QPoint) -> QPoint:
        return pos


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.graphics_view = _FakeGraphicsView()
    view.current_mode = "browse"
    view.current_page = 1
    view.total_pages = 5
    view.scale = 1.0
    view._fullscreen_active = False
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._resolve_text_info_for_context_menu_pos = lambda pos: None
    return view


def test_scene_context_menu_includes_richer_browse_actions(monkeypatch) -> None:
    view = _make_view()
    view._selected_text_cached = "selected text"
    view._selected_text_rect_doc = fitz.Rect(10, 10, 40, 20)
    labels: list[str] = []

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions: list[_FakeAction] = []

        def addAction(self, text: str, callback=None):
            _ = callback
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):
            self._actions.append(_FakeAction(""))

        def actions(self):
            return self._actions

        def exec_(self, *args, **kwargs):
            _ = args, kwargs
            labels.extend([action.text() for action in self._actions if action.text()])
            return None

    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    pdf_view.PDFView._show_context_menu(view, QPoint(0, 0))

    assert "Copy Selected Text" in labels
    assert "Select All" in labels
    assert "Fit to View" in labels
    assert "匯出目前頁面..." in labels
    assert "向右旋轉目前頁面 90°" in labels
    assert "向左旋轉目前頁面 90°" in labels
    assert "刪除目前頁面" in labels
    assert "在目前頁面後插入空白頁" in labels
    assert "在目前頁面後插入其他 PDF 頁面..." in labels
    assert "另存PDF" in labels
    assert "列印..." in labels
    assert "另存為最佳化的副本" in labels


def test_scene_context_menu_page_actions_reuse_page_specific_helpers(monkeypatch) -> None:
    view = _make_view()
    recorded: list[tuple[str, object]] = []

    class _FakeAction:
        def __init__(self, text: str, callback) -> None:
            self._text = text
            self._callback = callback

        def text(self) -> str:
            return self._text

        def trigger(self) -> None:
            if self._callback is not None:
                self._callback()

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions: list[_FakeAction] = []

        def addAction(self, text: str, callback=None):
            action = _FakeAction(text, callback)
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec_(self, *args, **kwargs):
            _ = args, kwargs
            for action in self._actions:
                if action.text() in {
                    "匯出目前頁面...",
                    "向右旋轉目前頁面 90°",
                    "刪除目前頁面",
                    "在目前頁面後插入空白頁",
                }:
                    action.trigger()
            return None

    view._export_specific_pages = lambda pages: recorded.append(("export", pages))
    view._rotate_specific_pages = lambda pages, degrees: recorded.append(("rotate", (pages, degrees)))
    view._delete_specific_pages = lambda pages: recorded.append(("delete", pages))
    view._insert_blank_page_at = lambda position: recorded.append(("insert_blank", position))
    view._insert_pages_from_file_at = lambda position: recorded.append(("insert_file", position))
    view._save_as = lambda: recorded.append(("save_as", None))
    view._print_document = lambda: recorded.append(("print", None))
    view._optimize_pdf_copy = lambda: recorded.append(("optimize", None))
    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    pdf_view.PDFView._show_context_menu(view, QPoint(0, 0))

    assert ("export", [2]) in recorded
    assert ("rotate", ([2], 90)) in recorded
    assert ("delete", [2]) in recorded
    assert ("insert_blank", 3) in recorded
