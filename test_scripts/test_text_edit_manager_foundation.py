from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from view.pdf_view import PDFView
import view.pdf_view as pdf_view


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeEditorWidget:
    def __init__(self, text: str, original_text: str) -> None:
        self._text = text
        self._original_text = original_text

    def toPlainText(self) -> str:
        return self._text

    def property(self, name: str):
        if name == "original_text":
            return self._original_text
        return None


class _FakeProxy:
    def __init__(self, widget) -> None:
        self._widget = widget

    def widget(self):
        return self._widget

    def scene(self):
        return False


class _FakeCombo:
    def currentText(self) -> str:
        return "12"


class _FakeScene:
    def removeItem(self, item) -> None:
        return None


def _make_view() -> PDFView:
    view = PDFView.__new__(PDFView)
    view.scene = _FakeScene()
    view.text_size = _FakeCombo()
    view.sig_edit_text = _FakeSignal()
    view.sig_move_text_across_pages = _FakeSignal()
    view.current_page = 0
    view._drag_pending = False
    view._drag_active = False
    view._drag_start_scene_pos = None
    view._drag_editor_start_pos = None
    view._pending_text_info = None
    view._edit_focus_check_pending = False
    view._finalizing_text_edit = False
    view._last_text_edit_finalize_result = None
    view._set_edit_focus_guard = lambda enabled: None
    view._set_document_undo_redo_enabled = lambda enabled: None
    view.sig_add_textbox = _FakeSignal()
    return view


def test_pdf_view_exposes_text_edit_manager_on_real_init(qapp):
    view = PDFView()
    try:
        assert hasattr(view, "text_edit_manager")
        assert view.text_edit_manager is not None
    finally:
        view.close()


def test_finalize_emits_typed_edit_request_payload() -> None:
    request_cls = getattr(pdf_view, "EditTextRequest", None)
    assert request_cls is not None

    view = _make_view()
    original_rect = fitz.Rect(10, 20, 120, 50)
    moved_rect = fitz.Rect(14, 30, 124, 60)
    view.text_editor = _FakeProxy(_FakeEditorWidget("same text", "same text"))
    view._editing_original_rect = fitz.Rect(original_rect)
    view.editing_rect = fitz.Rect(moved_rect)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = "same text"
    view.editing_intent = "edit_existing"

    result = view._finalize_text_edit_impl(pdf_view.TextEditFinalizeReason.CLICK_AWAY)

    assert result.outcome is pdf_view.TextEditOutcome.COMMITTED
    assert len(view.sig_edit_text.calls) == 1
    payload = view.sig_edit_text.calls[0][0]
    assert isinstance(payload, request_cls)
    assert payload.new_rect == moved_rect
    assert payload.page == 1
