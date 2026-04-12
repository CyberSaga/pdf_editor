from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPoint

import view.pdf_view as pdf_view


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeItem:
    pass


class _FakeViewport:
    def mapToGlobal(self, pos: QPoint) -> QPoint:
        return pos


class _FakeThumbnailList:
    def __init__(self, item: _FakeItem | None, row: int) -> None:
        self._item = item
        self._row = row
        self.current_row = None
        self._viewport = _FakeViewport()

    def itemAt(self, pos: QPoint):
        _ = pos
        return self._item

    def row(self, item: _FakeItem) -> int:
        return self._row if item is self._item else -1

    def setCurrentRow(self, row: int) -> None:
        self.current_row = row

    def viewport(self) -> _FakeViewport:
        return self._viewport


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.total_pages = 5
    view.sig_delete_pages = _FakeSignal()
    view.sig_rotate_pages = _FakeSignal()
    view.sig_export_pages = _FakeSignal()
    view.sig_insert_blank_page = _FakeSignal()
    view.sig_insert_pages_from_file = _FakeSignal()
    return view


def test_thumbnail_context_menu_exposes_page_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _make_view()
    item = _FakeItem()
    view.thumbnail_list = _FakeThumbnailList(item, 2)
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

    pdf_view.PDFView._show_thumbnail_context_menu(view, QPoint(10, 12))

    assert view.thumbnail_list.current_row == 2
    assert "刪除此頁" in labels
    assert "向右旋轉 90°" in labels
    assert "向左旋轉 90°" in labels
    assert "匯出此頁..." in labels
    assert "在此頁之前插入空白頁" in labels
    assert "在此頁之後插入空白頁" in labels
    assert "在此頁之前插入其他 PDF 頁面..." in labels
    assert "在此頁之後插入其他 PDF 頁面..." in labels


def test_delete_rotate_and_insert_helpers_emit_page_specific_signals() -> None:
    view = _make_view()

    pdf_view.PDFView._delete_specific_pages(view, [3])
    pdf_view.PDFView._rotate_specific_pages(view, [3], 90)
    pdf_view.PDFView._insert_blank_page_at(view, 3)

    assert view.sig_delete_pages.calls == [([3],)]
    assert view.sig_rotate_pages.calls == [([3], 90)]
    assert view.sig_insert_blank_page.calls == [(3,)]


def test_export_specific_pages_defaults_to_pdf_when_filter_is_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _make_view()
    monkeypatch.setattr(
        pdf_view.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("out/report", "PDF (*.pdf)"),
    )

    pdf_view.PDFView._export_specific_pages(view, [2])

    assert view.sig_export_pages.calls == [([2], "out/report.pdf", False, 300, "png")]


def test_insert_pages_from_file_at_uses_given_position(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    view = _make_view()
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    class _FakeSourceDoc:
        def __len__(self) -> int:
            return 4

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        pdf_view.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source_path), "PDF (*.pdf)"),
    )
    monkeypatch.setattr(pdf_view, "fitz", type("FitzModule", (), {"open": staticmethod(lambda path: _FakeSourceDoc())}))
    monkeypatch.setattr(pdf_view.QInputDialog, "getText", lambda *args, **kwargs: ("1,3-4", True))
    monkeypatch.setattr(pdf_view, "parse_pages", lambda text, total: [1, 3, 4])

    pdf_view.PDFView._insert_pages_from_file_at(view, 6)

    assert view.sig_insert_pages_from_file.calls == [((str(source_path)), [1, 3, 4], 6)]
