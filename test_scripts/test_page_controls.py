from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtWidgets import QLineEdit  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.total_pages = 6
    view.current_page = 2
    view.sig_delete_pages = _FakeSignal()
    view.sig_rotate_pages = _FakeSignal()
    view.sig_page_changed = _FakeSignal()
    return view


def test_pages_for_scope_resolves_current_all_odd_even_and_custom(monkeypatch) -> None:
    view = _make_view()

    assert pdf_view.PDFView._pages_for_scope(view, "目前頁") == [3]
    assert pdf_view.PDFView._pages_for_scope(view, "全部") == [1, 2, 3, 4, 5, 6]
    assert pdf_view.PDFView._pages_for_scope(view, "奇數頁") == [1, 3, 5]
    assert pdf_view.PDFView._pages_for_scope(view, "偶數頁") == [2, 4, 6]

    monkeypatch.setattr(pdf_view.QInputDialog, "getText", lambda *args, **kwargs: ("1,3-4", True))
    assert pdf_view.PDFView._pages_for_scope(view, "自訂範圍") == [1, 3, 4]


def test_delete_pages_uses_dialog_scope(monkeypatch) -> None:
    view = _make_view()
    monkeypatch.setattr(
        pdf_view.PDFView,
        "_prompt_delete_page_scope",
        lambda self: self._PAGE_SCOPE_ODD,
        raising=False,
    )

    pdf_view.PDFView._delete_pages(view)

    assert view.sig_delete_pages.calls == [([1, 3, 5],)]


def test_rotate_pages_uses_dialog_angle_and_scope(monkeypatch) -> None:
    view = _make_view()
    monkeypatch.setattr(
        pdf_view.PDFView,
        "_prompt_page_rotation_options",
        lambda self: (180, self._PAGE_SCOPE_ODD),
        raising=False,
    )

    pdf_view.PDFView._rotate_pages(view)

    assert view.sig_rotate_pages.calls == [([1, 3, 5], 180)]


def test_page_number_input_emits_zero_based_page_and_resets_invalid(qapp) -> None:
    view = _make_view()
    view.total_pages = 6
    view.current_page = 1
    view.scale = 1.0
    view.page_number_input = QLineEdit("2")
    view.page_total_label = QLineEdit("/ 6")
    view.zoom_combo = type(
        "Zoom",
        (),
        {
            "currentText": lambda self: "100%",
            "blockSignals": lambda self, value: None,
            "setCurrentText": lambda self, value: None,
        },
    )()

    view.page_number_input.setText("4")
    pdf_view.PDFView._on_page_number_input_return_pressed(view)
    assert view.sig_page_changed.calls == [(3,)]

    view.page_number_input.setText("0")
    pdf_view.PDFView._on_page_number_input_return_pressed(view)
    assert view.sig_page_changed.calls == [(3,)]
    assert view.page_number_input.text() == "2"

    view.page_number_input.setText("abc")
    pdf_view.PDFView._on_page_number_input_return_pressed(view)
    assert view.sig_page_changed.calls == [(3,)]
    assert view.page_number_input.text() == "2"


def test_delete_and_rotate_scope_choices_include_custom_range() -> None:
    assert pdf_view.PDFView._PAGE_SCOPE_CUSTOM in pdf_view.PDFView._PAGE_ROTATION_SCOPE_LABELS


def test_custom_page_scope_rejects_invalid_or_out_of_range_ranges(monkeypatch) -> None:
    view = _make_view()
    errors: list[str] = []
    monkeypatch.setattr(pdf_view, "show_error", lambda _view, message: errors.append(message))

    for raw in ("", "0", "7", "4-2", "1,,3", "abc"):
        monkeypatch.setattr(pdf_view.QInputDialog, "getText", lambda *_args, raw=raw, **_kwargs: (raw, True))
        assert pdf_view.PDFView._pages_for_scope(view, view._PAGE_SCOPE_CUSTOM) is None

    assert len(errors) == 6
