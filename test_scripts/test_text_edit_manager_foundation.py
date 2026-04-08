from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import view.pdf_view as pdf_view
from model.edit_requests import MoveTextRequest
from view.pdf_view import PDFView


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
    from model.edit_requests import EditTextRequest

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
    rerouted_request = mock_edit_text.call_args.args[0]
    assert isinstance(rerouted_request, EditTextRequest)
    assert rerouted_request.page == 2
    assert rerouted_request.rect == source_rect
    assert rerouted_request.new_text == "hello world"
    assert rerouted_request.font == "helv"
    assert rerouted_request.size == 12.5
    assert rerouted_request.new_rect == destination_rect
    assert rerouted_request.target_span_id == "span-1"
    assert rerouted_request.target_mode == "run"


def test_edit_text_request_importable_from_model() -> None:
    from model.edit_requests import EditTextRequest, MoveTextRequest

    assert EditTextRequest.__name__ == "EditTextRequest"
    assert MoveTextRequest.__name__ == "MoveTextRequest"


def test_edit_text_command_from_request_fields() -> None:
    from model.edit_commands import EditTextCommand
    from model.edit_requests import EditTextRequest

    request = EditTextRequest(
        page=2,
        rect=fitz.Rect(10, 20, 120, 50),
        new_text="updated text",
        font="helv",
        size=12.5,
        color=(0.1, 0.2, 0.3),
        original_text="old text",
        vertical_shift_left=False,
        new_rect=fitz.Rect(14, 24, 124, 54),
        target_span_id="span-1",
        target_mode="paragraph",
    )
    def reflow_fn() -> None:
        return None

    command = EditTextCommand.from_request(
        model=SimpleNamespace(),
        request=request,
        page_snapshot_bytes=b"snapshot",
        old_block_id="block-1",
        old_block_text="old text",
        reflow_fn=reflow_fn,
    )

    assert command._page_num == request.page
    assert command._rect == request.rect
    assert command._new_text == request.new_text
    assert command._font == request.font
    assert command._size == request.size
    assert command._color == request.color
    assert command._original_text == request.original_text
    assert command._vertical_shift_left is request.vertical_shift_left
    assert command._new_rect == request.new_rect
    assert command._target_span_id == request.target_span_id
    assert command._target_mode == request.target_mode
    assert command._page_snapshot_bytes == b"snapshot"
    assert command._old_block_id == "block-1"
    assert command._old_block_text == "old text"
    assert command._reflow_fn is reflow_fn
    assert command._request is request


def test_edit_text_command_from_request_execute() -> None:
    from model.edit_commands import EditTextCommand, EditTextResult
    from model.edit_requests import EditTextRequest

    captured: list[tuple[tuple, dict]] = []

    class _Model:
        def edit_text(self, *args, **kwargs):
            captured.append((args, kwargs))
            return EditTextResult.SUCCESS

    request = EditTextRequest(
        page=1,
        rect=fitz.Rect(1, 2, 30, 40),
        new_text="new text",
        font="courier",
        size=10.5,
        color=(0.0, 0.0, 0.0),
        original_text="old text",
        vertical_shift_left=True,
        new_rect=fitz.Rect(3, 4, 32, 42),
        target_span_id="span-9",
        target_mode="run",
    )
    reflow_calls: list[str] = []
    command = EditTextCommand.from_request(
        model=_Model(),
        request=request,
        page_snapshot_bytes=b"snapshot",
        old_block_id="block-9",
        old_block_text="old text",
        reflow_fn=lambda: reflow_calls.append("called"),
    )

    assert command.execute() is True
    assert captured == [
        (
            (
                1,
                fitz.Rect(1, 2, 30, 40),
                "new text",
                "courier",
                10.5,
                (0.0, 0.0, 0.0),
                "old text",
                True,
            ),
            {
                "new_rect": fitz.Rect(3, 4, 32, 42),
                "target_span_id": "span-9",
                "target_mode": "run",
            },
        )
    ]
    assert reflow_calls == ["called"]


def test_controller_edit_text_accepts_request_object() -> None:
    from unittest.mock import MagicMock, patch

    from controller.pdf_controller import PDFController
    from model.edit_commands import EditTextResult
    from model.edit_requests import EditTextRequest

    captured: dict[str, object] = {}

    class _FakeEditTextCommand:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("controller should use EditTextCommand.from_request")

        @classmethod
        def from_request(
            cls,
            model,
            request,
            page_snapshot_bytes,
            old_block_id=None,
            old_block_text=None,
            reflow_fn=None,
        ):
            captured["model"] = model
            captured["request"] = request
            captured["page_snapshot_bytes"] = page_snapshot_bytes
            captured["old_block_id"] = old_block_id
            captured["old_block_text"] = old_block_text
            captured["reflow_fn"] = reflow_fn
            return SimpleNamespace(result=EditTextResult.SUCCESS)

    request = EditTextRequest(
        page=1,
        rect=fitz.Rect(10, 10, 40, 20),
        new_text="new text",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text="old text",
        target_span_id="span-1",
        target_mode="run",
    )
    controller = PDFController.__new__(PDFController)
    controller.model = SimpleNamespace(
        doc=[object()],
        _capture_page_snapshot=lambda _page_idx: b"snapshot",
        command_manager=SimpleNamespace(execute=lambda cmd: None),
    )
    controller.view = SimpleNamespace(capture_viewport_anchor=lambda: None)
    controller.show_page = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()

    with patch("controller.pdf_controller.EditTextCommand", _FakeEditTextCommand):
        controller.edit_text(request)

    assert captured["model"] is controller.model
    assert captured["request"] is request
    assert captured["page_snapshot_bytes"] == b"snapshot"
    assert captured["old_block_id"] == "span-1"
    assert captured["old_block_text"] == "old text"
    assert callable(captured["reflow_fn"])
    controller.show_page.assert_called_once_with(0)
    controller._update_undo_redo_tooltips.assert_called_once()


def test_edit_text_request_none_coercion() -> None:
    from types import ModuleType
    from unittest.mock import MagicMock, patch

    from controller.pdf_controller import PDFController
    from model.edit_commands import EditTextResult
    from model.edit_requests import EditTextRequest

    class _TrackEngine:
        def apply_displacement_only(
            self,
            *,
            doc,
            page_idx,
            edited_rect,
            new_text,
            original_text,
            font,
            size,
            color,
        ):
            assert doc == "doc"
            assert page_idx == 0
            assert edited_rect == fitz.Rect(10, 10, 40, 20)
            assert new_text == ""
            assert original_text == ""
            assert font == "helv"
            assert size == 12.0
            assert color == (0.0, 0.0, 0.0)
            return {"success": True, "plan": object()}

    class _FakeEditTextCommand:
        result = EditTextResult.SUCCESS

        def __init__(self) -> None:
            raise AssertionError("controller should use EditTextCommand.from_request")

        @classmethod
        def from_request(
            cls,
            model,
            request,
            page_snapshot_bytes,
            old_block_id=None,
            old_block_text=None,
            reflow_fn=None,
        ):
            class _Command:
                result = EditTextResult.SUCCESS

                def execute(self_inner):
                    reflow_fn()
                    return True

            return _Command()

    request = EditTextRequest(
        page=1,
        rect=fitz.Rect(10, 10, 40, 20),
        new_text=None,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=None,
    )
    controller = PDFController.__new__(PDFController)
    controller.model = SimpleNamespace(
        doc="doc",
        _capture_page_snapshot=lambda _page_idx: b"snapshot",
        command_manager=SimpleNamespace(execute=lambda cmd: cmd.execute()),
    )
    controller.view = SimpleNamespace(capture_viewport_anchor=lambda: None)
    controller.show_page = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()

    track_b_core = ModuleType("reflow.track_B_core")
    track_b_core.TrackBEngine = _TrackEngine
    track_a_core = ModuleType("reflow.track_A_core")
    track_a_core.TrackAEngine = _TrackEngine

    with (
        patch("controller.pdf_controller.EditTextCommand", _FakeEditTextCommand),
        patch.dict(
            sys.modules,
            {
                "reflow.track_B_core": track_b_core,
                "reflow.track_A_core": track_a_core,
            },
        ),
    ):
        controller.edit_text(request)

    controller.show_page.assert_called_once_with(0)
    controller._update_undo_redo_tooltips.assert_called_once()


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
        @classmethod
        def from_request(cls, *args, **kwargs):
            return SimpleNamespace(result=EditTextResult.TARGET_BLOCK_NOT_FOUND)

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
