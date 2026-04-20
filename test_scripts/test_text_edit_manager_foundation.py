from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import view.pdf_view as pdf_view
from view.pdf_view import PDFView
from view.text_editing import MoveTextRequest


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


def test_pdf_view_init_does_not_warn_about_outline_disconnects(qapp):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        view = PDFView()
        try:
            assert hasattr(view, "text_edit_manager")
            assert view.text_edit_manager is not None
        finally:
            view.close()

    disconnect_warnings = [
        warning
        for warning in caught
        if issubclass(warning.category, RuntimeWarning)
        and "Failed to disconnect" in str(warning.message)
    ]
    assert disconnect_warnings == []


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


def test_sig_move_text_emits_move_text_request() -> None:
    view = _make_view()
    original_rect = fitz.Rect(10, 20, 120, 50)
    current_rect = fitz.Rect(16, 12, 126, 42)
    view.text_editor = _FakeProxy(_FakeEditorWidget("moved text", "source text"))
    view._editing_original_rect = fitz.Rect(original_rect)
    view.editing_rect = fitz.Rect(current_rect)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = "source text"
    view._editing_page_idx = 1
    view._editing_origin_page_idx = 0
    view.editing_target_span_id = "span-1"
    view.editing_target_mode = "run"
    view.editing_intent = "edit_existing"

    view._finalize_text_edit_impl()

    assert len(view.sig_move_text_across_pages.calls) == 1
    assert isinstance(view.sig_move_text_across_pages.calls[0][0], MoveTextRequest)


def test_move_text_request_fields_match_session() -> None:
    view = _make_view()
    original_rect = fitz.Rect(10, 20, 120, 50)
    current_rect = fitz.Rect(16, 12, 126, 42)
    view.text_editor = _FakeProxy(_FakeEditorWidget("moved text", "source text"))
    view._editing_original_rect = fitz.Rect(original_rect)
    view.editing_rect = fitz.Rect(current_rect)
    view.editing_font_name = "helv"
    view._editing_initial_font_name = "helv"
    view.editing_color = (0, 0, 0)
    view._editing_initial_size = 12
    view.editing_original_text = "source text"
    view._editing_page_idx = 1
    view._editing_origin_page_idx = 0
    view.editing_target_span_id = "span-1"
    view.editing_target_mode = "run"
    view.editing_intent = "edit_existing"

    view._finalize_text_edit_impl()

    request = view.sig_move_text_across_pages.calls[0][0]
    assert request.source_page == 1
    assert request.destination_page == 2
    assert request.new_text == "moved text"
    assert request.font == "helv"
    assert request.original_text == "source text"
    assert request.target_span_id == "span-1"
    assert request.target_mode == "run"
    assert request.source_rect == original_rect
    assert request.destination_rect == current_rect


def test_controller_accepts_move_text_request() -> None:
    from unittest.mock import MagicMock, patch

    from controller.pdf_controller import PDFController

    mock_view = MagicMock()
    mock_model = MagicMock()
    mock_model.doc = [None, None, None]  # truthy, len() == 3

    controller = PDFController.__new__(PDFController)
    controller.view = mock_view
    controller.model = mock_model

    destination_rect = fitz.Rect(5, 5, 100, 35)
    source_rect = fitz.Rect(10, 20, 120, 50)
    # source_page == destination_page triggers the edit_text reroute path,
    # which lets us verify that MoveTextRequest fields are correctly extracted
    # without wiring up the full cross-page model pipeline.
    request = MoveTextRequest(
        source_page=2,
        source_rect=source_rect,
        destination_page=2,
        destination_rect=destination_rect,
        new_text="hello world",
        font="helv",
        size=12.5,
        color=(0, 0, 0),
        original_text="old text",
        target_span_id="span-1",
        target_mode="run",
    )

    with patch.object(controller, "edit_text") as mock_edit_text:
        controller.move_text_across_pages(request)

    mock_edit_text.assert_called_once()
    call_kwargs = mock_edit_text.call_args
    args, kwargs = call_kwargs
    assert args[0] == 2          # source_page
    assert args[1] == source_rect
    assert args[2] == "hello world"
    assert args[3] == "helv"
    assert args[4] == 12.5
    assert kwargs.get("new_rect") == destination_rect


def test_controller_updates_undo_redo_enabled_state_from_command_manager() -> None:
    from types import SimpleNamespace

    from controller.pdf_controller import PDFController

    controller = PDFController.__new__(PDFController)
    controller.model = SimpleNamespace(
        command_manager=SimpleNamespace(
            can_undo=lambda: True,
            can_redo=lambda: False,
            _undo_stack=[SimpleNamespace(description="編輯文字")],
            _redo_stack=[],
        )
    )
    recorded: list[tuple[bool, bool]] = []
    controller.view = SimpleNamespace(
        update_undo_redo_tooltips=lambda undo_tip, redo_tip: None,
        update_undo_redo_enabled=lambda undo_enabled, redo_enabled: recorded.append(
            (undo_enabled, redo_enabled)
        ),
    )
    controller._refresh_document_tabs = lambda: None

    controller._update_undo_redo_tooltips()

    assert recorded == [(True, False)]


def test_controller_edit_text_shows_error_toast_for_invalid_result() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from controller.pdf_controller import PDFController
    from model.edit_commands import EditTextResult

    class _FakeEditTextCommand:
        def __init__(self, *args, **kwargs) -> None:
            self.result = EditTextResult.TARGET_BLOCK_NOT_FOUND

    controller = PDFController.__new__(PDFController)
    controller.model = SimpleNamespace(
        doc=[object()],
        _capture_page_snapshot=lambda _page_idx: b"snapshot",
        command_manager=SimpleNamespace(execute=lambda cmd: None),
    )
    controller.view = SimpleNamespace(
        capture_viewport_anchor=lambda: None,
        _show_toast=MagicMock(),
    )
    controller.show_page = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()

    with patch("controller.pdf_controller.EditTextCommand", _FakeEditTextCommand):
        controller.edit_text(
            1,
            fitz.Rect(10, 10, 40, 20),
            "new text",
            "helv",
            12,
            (0.0, 0.0, 0.0),
            "old text",
        )

    controller.view._show_toast.assert_called_once()
    controller.show_page.assert_not_called()


def test_edit_text_command_initializes_result_before_execute() -> None:
    from model.edit_commands import EditTextCommand, EditTextResult

    command = EditTextCommand(
        model=SimpleNamespace(),
        page_num=1,
        rect=fitz.Rect(0, 0, 10, 10),
        new_text="hello",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text="old",
        vertical_shift_left=True,
        page_snapshot_bytes=b"snapshot",
        old_block_id="block-1",
        old_block_text="old",
    )

    assert command.result is EditTextResult.SUCCESS


def test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands() -> None:
    from model.edit_commands import EditCommand

    assert EditCommand.execute.__annotations__.get("return") in (None, type(None), "None")


def test_edit_text_command_execute_annotation_is_bool() -> None:
    from model.edit_commands import EditTextCommand

    assert EditTextCommand.execute.__annotations__.get("return") in (bool, "bool")
