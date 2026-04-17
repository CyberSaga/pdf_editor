import sys
import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QListView, QMenu

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from view.pdf_view import PDFView


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for t in texts:
        page = doc.new_page()
        page.insert_text((72, 72), t, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _make_pdf_with_font(path: Path, text: str, font: str, size: int = 12) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=size, fontname=font)
    doc.save(path)
    doc.close()
    return path


def _make_landscape_pdf(path: Path, pages: int = 2) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=842, height=595)
        page.insert_text((72, 72), f"landscape {i+1}", fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _norm(text: str) -> str:
    return "".join((text or "").lower().split())


def _pump_events(ms: int = 250) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _send_drop(widget, urls: list[QUrl]) -> None:
    mime = QMimeData()
    mime.setUrls(urls)
    pos = widget.rect().center()
    drag_enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, drag_enter)
    drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, drop)


def _trigger_fullscreen(view: PDFView) -> None:
    action = getattr(view, "_action_fullscreen", None)
    assert action is not None, "fullscreen action missing"
    action.trigger()
    _pump_events(220)


def _assert_mode_checked(view: PDFView, expected_mode: str) -> None:
    action_map = {
        "browse": view._action_browse,
        "edit_text": view._action_edit_text,
        "add_text": view._action_add_text,
        "rect": view._action_rect,
        "highlight": view._action_highlight,
        "add_annotation": view._action_add_annotation,
    }
    for mode, action in action_map.items():
        assert action.isChecked() == (mode == expected_mode), f"mode checked mismatch: {mode}"


def _make_dirty(model: PDFModel) -> None:
    if not model.doc:
        return
    model.tools.watermark.add_watermark([1], "dirty", 45, 0.3, 18, (0.7, 0.7, 0.7), "helv")


def _edit_first_run(controller: PDFController, new_text: str) -> None:
    model = controller.model
    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]
    controller.edit_text(
        1,
        fitz.Rect(run.bbox),
        new_text,
        run.font,
        int(max(1, round(run.size))),
        tuple(run.color),
        run.text,
        True,
        None,
        run.span_id,
        "run",
    )


def _open_inline_editor_for_first_run(model: PDFModel, view: PDFView) -> tuple:
    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)

    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None
    return run, viewport


def _load_pdf_and_open_inline_editor(
    controller: PDFController,
    model: PDFModel,
    view: PDFView,
    path: Path,
    *,
    mode: str = "edit_text",
) -> tuple:
    view.show()
    view.activateWindow()
    _pump_events(120)
    controller.open_pdf(str(path))
    _pump_events(350)
    view.set_mode(mode)
    _pump_events(60)
    return _open_inline_editor_for_first_run(model, view)


def _click_outside_active_editor(view: PDFView, viewport) -> None:
    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    outside_pos = view.graphics_view.mapFromScene(editor_scene_rect.bottomRight() + QPoint(40, 40))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, outside_pos)
    _pump_events(220)


def _active_shortcut_target(view: PDFView):
    app = QApplication.instance()
    assert app is not None
    view.show()
    view.activateWindow()
    if app.focusWidget() is None:
        view._focus_page_canvas()
    _pump_events(120)
    return app.focusWidget() or view.graphics_view


class _FakeEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def mvc(monkeypatch, qapp):
    # Suppress modal info dialogs used by controller helper paths.
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    yield model, view, controller
    model.close()
    view.close()
    _pump_events(50)


def test_01_open_two_and_switch_tabs(mvc, tmp_path):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["alpha page"])
    b = _make_pdf(tmp_path / "B.pdf", ["beta page", "beta page 2"])
    controller.open_pdf(str(a))
    controller.open_pdf(str(b))
    _pump_events(250)
    assert len(model.session_ids) == 2
    assert view.document_tab_bar.count() == 2
    controller.on_tab_changed(0)
    _pump_events(100)
    assert len(model.doc) == 1
    controller.on_tab_changed(1)
    _pump_events(100)
    assert len(model.doc) == 2


def test_02_duplicate_open_focus_existing(mvc, tmp_path):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["dup check"])
    controller.open_pdf(str(a))
    sid_first = model.get_active_session_id()
    controller.open_pdf(str(a))
    assert len(model.session_ids) == 1
    assert model.get_active_session_id() == sid_first


def test_drag_drop_opens_multiple_local_pdfs_in_order(mvc, tmp_path):
    model, view, controller = mvc
    first = _make_pdf(tmp_path / "drop_a.pdf", ["A"])
    second = _make_pdf(tmp_path / "drop_b.pdf", ["B"])

    controller.activate()
    view.show()
    _pump_events(100)

    _send_drop(
        view,
        [QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))],
    )
    _pump_events(250)

    assert len(model.session_ids) == 2
    assert [Path(model.get_session_meta(sid)["path"]).name for sid in model.session_ids] == ["drop_a.pdf", "drop_b.pdf"]
    assert model.get_active_session_id() == model.session_ids[-1]


def test_drag_drop_ignores_non_pdf_folder_and_remote_urls(mvc, tmp_path):
    model, view, controller = mvc
    valid = _make_pdf(tmp_path / "valid.pdf", ["valid"])
    folder = tmp_path / "folder"
    folder.mkdir()
    non_pdf = tmp_path / "notes.txt"
    non_pdf.write_text("not a pdf", encoding="utf-8")

    controller.activate()
    view.show()
    _pump_events(100)

    _send_drop(
        view,
        [
            QUrl.fromLocalFile(str(folder)),
            QUrl.fromLocalFile(str(non_pdf)),
            QUrl("https://example.com/remote.pdf"),
            QUrl.fromLocalFile(str(valid)),
        ],
    )
    _pump_events(250)

    assert len(model.session_ids) == 1
    active_path = model.get_session_meta(model.get_active_session_id())["path"]
    assert Path(active_path).name == "valid.pdf"


def test_drag_drop_multiple_pdfs_never_calls_merge_paths(
    monkeypatch: pytest.MonkeyPatch,
    mvc,
    tmp_path,
) -> None:
    model, view, controller = mvc
    first = _make_pdf(tmp_path / "drop_a.pdf", ["A"])
    second = _make_pdf(tmp_path / "drop_b.pdf", ["B"])

    def _fail_merge(*_args, **_kwargs):
        raise AssertionError("drag-drop must not call merge flows")

    monkeypatch.setattr(PDFController, "merge_ordered_sources_into_current", _fail_merge)
    monkeypatch.setattr(PDFController, "save_ordered_sources_as_new", _fail_merge)

    controller.activate()
    view.show()
    _pump_events(100)

    _send_drop(
        view,
        [QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))],
    )
    _pump_events(250)

    assert len(model.session_ids) == 2
    assert [Path(model.get_session_meta(sid)["path"]).name for sid in model.session_ids] == ["drop_a.pdf", "drop_b.pdf"]
    assert model.get_active_session_id() == model.session_ids[-1]


def test_03_edit_in_a_undo_in_b_isolated(mvc, tmp_path):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["original text A"])
    b = _make_pdf(tmp_path / "B.pdf", ["original text B"])
    controller.open_pdf(str(a))
    sid_a = model.get_active_session_id()
    controller.open_pdf(str(b))
    sid_b = model.get_active_session_id()
    controller.on_tab_changed(0)  # A
    _edit_first_run(controller, "edited_A_token")
    assert "edited_a_token" in _norm(model.doc[0].get_text("text"))
    controller.on_tab_changed(1)  # B
    controller.undo()  # no-op on B
    controller.on_tab_changed(0)  # back to A
    assert "edited_a_token" in _norm(model.doc[0].get_text("text"))
    assert sid_a != sid_b


def test_04_structural_undo_redo_isolated(mvc, tmp_path, monkeypatch):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["p1", "p2"])
    b = _make_pdf(tmp_path / "B.pdf", ["q1", "q2"])
    controller.open_pdf(str(a))
    controller.open_pdf(str(b))
    controller.on_tab_changed(0)  # A
    a_pages_before = len(model.doc)
    controller.insert_blank_page(2)
    assert len(model.doc) == a_pages_before + 1
    controller.on_tab_changed(1)  # B
    b_pages_before = len(model.doc)
    controller.undo()
    assert len(model.doc) == b_pages_before
    controller.on_tab_changed(0)  # A
    controller.undo()
    assert len(model.doc) == a_pages_before
    controller.redo()
    assert len(model.doc) == a_pages_before + 1


def test_04b_structural_actions_schedule_stale_index_drain(mvc, tmp_path, monkeypatch):
    model, _, controller = mvc
    path = _make_pdf(tmp_path / "A.pdf", ["alpha", "beta", "gamma"])
    controller.open_pdf(str(path))
    for page_num in (1, 2):
        model.ensure_page_index_built(page_num)

    scheduled: list[str] = []
    monkeypatch.setattr(controller, "_schedule_stale_index_drain", lambda: scheduled.append("scheduled"))

    controller.insert_blank_page(2)

    assert scheduled == ["scheduled"]


def test_04c_structural_metadata_uses_actual_blank_insert_position(mvc, tmp_path):
    model, _, controller = mvc
    path = _make_pdf(tmp_path / "A.pdf", ["alpha", "beta", "gamma"])
    controller.open_pdf(str(path))

    controller.insert_blank_page(99)

    cmd = model.command_manager._undo_stack[-1]
    assert cmd.affected_pages == [4]


def test_04d_structural_metadata_uses_actual_import_insert_positions(mvc, tmp_path):
    model, _, controller = mvc
    base = _make_pdf(tmp_path / "A.pdf", ["alpha", "beta", "gamma"])
    source = _make_pdf(tmp_path / "B.pdf", ["imported"])
    controller.open_pdf(str(base))

    controller.insert_pages_from_file(str(source), [0, 1], 2)

    cmd = model.command_manager._undo_stack[-1]
    assert cmd.affected_pages == [2]


def test_04e_structural_metadata_uses_actual_deleted_pages(mvc, tmp_path):
    model, _, controller = mvc
    path = _make_pdf(tmp_path / "A.pdf", ["alpha", "beta", "gamma"])
    controller.open_pdf(str(path))

    controller.delete_pages([0, -1, 2, 2, 99])

    cmd = model.command_manager._undo_stack[-1]
    assert cmd.affected_pages == [2]


def test_05_search_state_restored_per_tab(mvc, tmp_path):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["alpha-key"])
    b = _make_pdf(tmp_path / "B.pdf", ["beta-key"])
    controller.open_pdf(str(a))
    controller.search_text("alpha")
    assert view.search_input.text() == ""
    view.search_input.setText("alpha")
    controller.on_tab_changed(0)
    controller.open_pdf(str(b))
    view.search_input.setText("beta")
    controller.search_text("beta")
    controller.on_tab_changed(0)  # A
    assert view.search_input.text() == "alpha"
    assert any("alpha" in (ctx or "").lower() for _, ctx, _ in view.current_search_results)
    controller.on_tab_changed(1)  # B
    assert view.search_input.text() == "beta"
    assert any("beta" in (ctx or "").lower() for _, ctx, _ in view.current_search_results)


def test_06_rapid_switch_has_no_stale_async_render(mvc, tmp_path):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", [f"A{i}" for i in range(6)])
    b = _make_pdf(tmp_path / "B.pdf", ["B only"])
    controller.open_pdf(str(a))
    controller.open_pdf(str(b))
    for _ in range(6):
        controller.on_tab_changed(0)
        controller.on_tab_changed(1)
    _pump_events(1200)
    assert len(model.doc) == 1
    assert view.thumbnail_list.count() == 1
    assert len(view.page_items) <= 1


def test_06a_thumbnail_list_enforces_single_column_layout(mvc):
    _, view, _ = mvc
    assert view.thumbnail_list.viewMode() == QListView.IconMode
    assert view.thumbnail_list.flow() == QListView.TopToBottom
    assert not view.thumbnail_list.isWrapping()


def test_06b_thumbnail_click_navigation_with_single_column(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "thumb_nav.pdf", ["p1", "p2", "p3"])
    controller.open_pdf(str(path))
    _pump_events(400)
    assert view.thumbnail_list.count() == 3
    item = view.thumbnail_list.item(2)
    assert item is not None
    view._on_thumbnail_clicked(item)
    _pump_events(80)
    assert view.current_page == 2
    assert view.thumbnail_list.currentRow() == 2


def test_06c_thumbnail_layout_fills_sidebar_width_and_has_spacing(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "thumb_layout_width.pdf", ["p1", "p2", "p3", "p4", "p5"])
    controller.open_pdf(str(path))
    _pump_events(500)
    viewport_w = view.thumbnail_list.viewport().width()
    assert viewport_w > 0
    assert view.thumbnail_list.spacing() == 1
    assert view.thumbnail_list.gridSize().width() >= int(viewport_w * 0.88)
    assert view.thumbnail_list.iconSize().width() >= int(viewport_w * 0.75)


def test_06d_thumbnail_list_auto_scrolls_with_page_scroll(mvc, tmp_path):
    _, view, controller = mvc
    pages = [f"p{i}" for i in range(1, 21)]
    path = _make_pdf(tmp_path / "thumb_follow_scroll.pdf", pages)
    controller.open_pdf(str(path))
    _pump_events(1500)
    thumb_sb = view.thumbnail_list.verticalScrollBar()
    canvas_sb = view.graphics_view.verticalScrollBar()
    assert thumb_sb.maximum() > 0
    assert canvas_sb.maximum() > 0
    canvas_sb.setValue(canvas_sb.maximum())
    _pump_events(180)
    assert view.current_page > 0
    assert view.thumbnail_list.currentRow() == view.current_page
    assert thumb_sb.value() > 0


def test_06e_landscape_thumbnail_does_not_create_tall_blank_cell(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_landscape_pdf(tmp_path / "thumb_landscape.pdf", pages=3)
    controller.open_pdf(str(path))
    _pump_events(500)
    icon_size = view.thumbnail_list.iconSize()
    grid_size = view.thumbnail_list.gridSize()
    assert icon_size.width() > 0 and icon_size.height() > 0
    assert icon_size.height() <= int(icon_size.width() * 0.9)
    assert grid_size.height() <= icon_size.height() + 36


def test_06f_thumbnail_layout_caps_width_and_centers_in_wide_sidebar(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "thumb_wide_sidebar.pdf", ["p1", "p2", "p3"])
    view.resize(1600, 900)
    view.show()
    controller.open_pdf(str(path))
    _pump_events(500)
    view._apply_sidebar_sizes(left_width=380, right_width=280)
    _pump_events(120)
    view._update_thumbnail_layout_metrics()
    _pump_events(120)

    margins = view.thumbnail_list.viewportMargins()
    assert margins.left() > 0
    assert margins.left() == margins.right()
    assert view.thumbnail_list.gridSize().width() <= 280


def test_07_close_modified_tab_cancel_keeps_tab(mvc, tmp_path, monkeypatch):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["A"])
    b = _make_pdf(tmp_path / "B.pdf", ["B"])
    controller.open_pdf(str(a))
    controller.open_pdf(str(b))
    controller.on_tab_changed(0)
    _make_dirty(model)
    before = len(model.session_ids)
    monkeypatch.setattr(controller, "_confirm_close_session", lambda sid: False)
    controller.on_tab_close_requested(0)
    assert len(model.session_ids) == before


def test_08_close_modified_tab_save_then_close(mvc, tmp_path, monkeypatch):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["A"])
    b = _make_pdf(tmp_path / "B.pdf", ["B"])
    save_target = tmp_path / "A_saved.pdf"
    controller.open_pdf(str(a))
    controller.open_pdf(str(b))
    controller.on_tab_changed(0)
    _make_dirty(model)

    def _confirm_and_save(sid: str) -> bool:
        model.save_session_as(sid, str(save_target))
        return True

    monkeypatch.setattr(controller, "_confirm_close_session", _confirm_and_save)
    controller.on_tab_close_requested(0)
    assert save_target.exists()
    assert len(model.session_ids) == 1


def test_09_app_close_cancel_and_save_all_paths(mvc, monkeypatch, tmp_path):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["A"])
    b = _make_pdf(tmp_path / "B.pdf", ["B"])
    controller.open_pdf(str(a))
    _make_dirty(model)
    controller.open_pdf(str(b))
    _make_dirty(model)
    dirty = set(model.get_dirty_session_ids())
    assert dirty

    class FakeBox:
        AcceptRole = 0
        DestructiveRole = 1
        RejectRole = 2
        Warning = 0
        mode = "cancel"

        def __init__(self, *args, **kwargs):
            self._buttons = []

        def setWindowTitle(self, *_): pass
        def setText(self, *_): pass
        def setInformativeText(self, *_): pass
        def setDefaultButton(self, *_): pass
        def setIcon(self, *_): pass

        def addButton(self, _label, _role):
            token = object()
            self._buttons.append(token)
            return token

        def exec(self): pass

        def clickedButton(self):
            # order: save_all, discard_all, cancel
            if self.mode == "save":
                return self._buttons[0]
            if self.mode == "discard":
                return self._buttons[1]
            return self._buttons[2]

    import controller.pdf_controller as ctrl_module
    monkeypatch.setattr(ctrl_module, "QMessageBox", FakeBox)
    monkeypatch.setattr(controller, "_attach_yes_no_shortcuts", lambda *a, **k: None)

    ev_cancel = _FakeEvent()
    FakeBox.mode = "cancel"
    controller.handle_app_close(ev_cancel)
    assert ev_cancel.ignored and not ev_cancel.accepted

    saved_calls: list[str] = []
    monkeypatch.setattr(controller, "_save_session_for_close", lambda sid: saved_calls.append(sid) or True)
    ev_save = _FakeEvent()
    FakeBox.mode = "save"
    controller.handle_app_close(ev_save)
    assert ev_save.accepted and not ev_save.ignored
    assert set(saved_calls) == dirty


def test_10_save_as_path_collision_blocked(mvc, tmp_path, monkeypatch):
    model, _, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["A"])
    b = _make_pdf(tmp_path / "B.pdf", ["B"])
    controller.open_pdf(str(a))
    sid_a = model.get_active_session_id()
    controller.open_pdf(str(b))
    sid_b = model.get_active_session_id()

    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda _view, msg: errors.append(str(msg)))
    controller.save_as(str(a))
    assert sid_a != sid_b
    assert errors
    assert any("已在其他分頁開啟" in e for e in errors)


def test_10a_active_session_updates_view_save_as_default_path(mvc, tmp_path):
    _, view, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["A"])
    b = _make_pdf(tmp_path / "B.pdf", ["B"])

    controller.open_pdf(str(a))
    _pump_events(250)
    assert view._save_as_default_path == str(a)

    controller.open_pdf(str(b))
    _pump_events(250)
    assert view._save_as_default_path == str(b)

    out = tmp_path / "B-copy.pdf"
    controller.save_as(str(out))
    _pump_events(120)
    assert view._save_as_default_path == str(out)


def test_11_close_last_tab_resets_ui(mvc, tmp_path, monkeypatch):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["A"])
    controller.open_pdf(str(a))
    monkeypatch.setattr(controller, "_confirm_close_session", lambda sid: True)
    controller.on_tab_close_requested(0)
    assert not model.session_ids
    assert model.get_active_session_id() is None
    assert view.total_pages == 0
    assert view.thumbnail_list.count() == 0
    assert not view.document_tab_bar.isVisible()


def test_12_cli_style_multi_open_loop(mvc, tmp_path):
    model, _, controller = mvc
    files = [
        _make_pdf(tmp_path / "C1.pdf", ["c1"]),
        _make_pdf(tmp_path / "C2.pdf", ["c2"]),
        _make_pdf(tmp_path / "C3.pdf", ["c3"]),
    ]
    for p in files:
        controller.open_pdf(str(p))
    assert len(model.session_ids) == 3
    active = model.get_active_session_id()
    assert active == model.session_ids[-1]


def test_13_ctrl_tab_switches_to_right_tab(mvc, tmp_path):
    model, view, controller = mvc
    files = [
        _make_pdf(tmp_path / "T1.pdf", ["t1"]),
        _make_pdf(tmp_path / "T2.pdf", ["t2"]),
        _make_pdf(tmp_path / "T3.pdf", ["t3"]),
    ]
    for p in files:
        controller.open_pdf(str(p))
    assert view.document_tab_bar.currentIndex() == 2
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Tab, Qt.ControlModifier)
    _pump_events(50)
    assert view.document_tab_bar.currentIndex() == 0
    assert model.get_active_session_id() == model.session_ids[0]


def test_14_ctrl_shift_tab_switches_to_left_tab(mvc, tmp_path):
    model, view, controller = mvc
    files = [
        _make_pdf(tmp_path / "L1.pdf", ["l1"]),
        _make_pdf(tmp_path / "L2.pdf", ["l2"]),
        _make_pdf(tmp_path / "L3.pdf", ["l3"]),
    ]
    for p in files:
        controller.open_pdf(str(p))
    controller.on_tab_changed(0)
    assert view.document_tab_bar.currentIndex() == 0
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Tab, Qt.ControlModifier | Qt.ShiftModifier)
    _pump_events(50)
    assert view.document_tab_bar.currentIndex() == 2
    assert model.get_active_session_id() == model.session_ids[2]


def test_15_ctrl_tab_on_toolbar_does_not_switch_toolbar_tabs(mvc, tmp_path):
    model, view, controller = mvc
    files = [
        _make_pdf(tmp_path / "K1.pdf", ["k1"]),
        _make_pdf(tmp_path / "K2.pdf", ["k2"]),
        _make_pdf(tmp_path / "K3.pdf", ["k3"]),
    ]
    for p in files:
        controller.open_pdf(str(p))
    view.toolbar_tabs.setCurrentIndex(1)
    assert view.toolbar_tabs.currentIndex() == 1
    assert view.document_tab_bar.currentIndex() == 2
    QTest.keyClick(view.toolbar_tabs.tabBar(), Qt.Key_Tab, Qt.ControlModifier)
    _pump_events(50)
    assert view.toolbar_tabs.currentIndex() == 1
    assert view.document_tab_bar.currentIndex() == 0
    assert model.get_active_session_id() == model.session_ids[0]


def test_16_ctrl_shift_tab_on_sidebar_does_not_switch_sidebar_tabs(mvc, tmp_path):
    model, view, controller = mvc
    files = [
        _make_pdf(tmp_path / "S1.pdf", ["s1"]),
        _make_pdf(tmp_path / "S2.pdf", ["s2"]),
        _make_pdf(tmp_path / "S3.pdf", ["s3"]),
    ]
    for p in files:
        controller.open_pdf(str(p))
    controller.on_tab_changed(0)
    view.left_sidebar.setCurrentIndex(1)
    assert view.left_sidebar.currentIndex() == 1
    assert view.document_tab_bar.currentIndex() == 0
    QTest.keyClick(view.left_sidebar.tabBar(), Qt.Key_Tab, Qt.ControlModifier | Qt.ShiftModifier)
    _pump_events(50)
    assert view.left_sidebar.currentIndex() == 1
    assert view.document_tab_bar.currentIndex() == 2
    assert model.get_active_session_id() == model.session_ids[2]


def test_17_fit_to_view_syncs_zoom_state_to_current_page_fit_scale(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fit_current_page.pdf", ["p1", "p2", "p3", "p4"])
    controller.open_pdf(str(path))
    _pump_events(1200)
    assert len(view.page_items) >= 4

    controller.change_page(2)
    _pump_events(100)
    controller.change_scale(view.current_page, 1.6)
    _pump_events(100)
    expected_scale = view.compute_contain_scale_for_page(view.current_page)
    assert expected_scale != pytest.approx(1.6, rel=1e-3)
    view._fit_to_view()
    _pump_events(50)

    viewport_center = view.graphics_view.viewport().rect().center()
    scene_center = view.graphics_view.mapToScene(viewport_center)
    current_center = view.page_items[view.current_page].sceneBoundingRect().center()
    full_scene_center = view.scene.sceneRect().center()

    assert view.scale == pytest.approx(expected_scale, rel=1e-3)
    assert view.zoom_combo.currentText() == f"{int(round(expected_scale * 100))}%"
    assert abs(scene_center.y() - current_center.y()) < 20
    assert abs(scene_center.y() - full_scene_center.y()) > 100


def test_17b_zoom_combo_keeps_only_default_options(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "zoom_combo_defaults.pdf", ["zoom"])
    controller.open_pdf(str(path))
    _pump_events(300)

    defaults = [view.zoom_combo.itemText(i) for i in range(view.zoom_combo.count())]
    assert defaults == ["50%", "75%", "100%", "125%", "150%", "200%"]

    controller.change_scale(view.current_page, 1.33)
    _pump_events(50)

    assert view.zoom_combo.currentText() == "133%"
    assert [view.zoom_combo.itemText(i) for i in range(view.zoom_combo.count())] == defaults


def test_18_mode_checked_state_sync_and_restore(mvc, tmp_path):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "M1.pdf", ["m1"])
    b = _make_pdf(tmp_path / "M2.pdf", ["m2"])
    controller.open_pdf(str(a))
    _pump_events(200)
    view.set_mode("highlight")
    _assert_mode_checked(view, "highlight")
    controller.open_pdf(str(b))
    _pump_events(200)
    controller.on_tab_changed(0)
    _pump_events(100)
    assert view.current_mode == "highlight"
    _assert_mode_checked(view, "highlight")
    controller.on_tab_changed(1)
    _pump_events(100)
    assert view.current_mode == "highlight"
    _assert_mode_checked(view, "highlight")


def test_19_escape_with_editor_closes_editor_but_keeps_mode(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "esc_editor.pdf", ["esc editor"])
    controller.open_pdf(str(path))
    _pump_events(300)
    view.set_mode("add_text")
    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport.rect().center())
    _pump_events(80)
    assert view.text_editor is not None
    QTest.keyClick(view.text_editor.widget(), Qt.Key_Escape)
    _pump_events(120)
    assert view.text_editor is None
    assert view.current_mode == "add_text"
    _assert_mode_checked(view, "add_text")


def test_19a_inline_existing_text_escape_discards_changes(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "esc_inline_edit.pdf", ["inline edit seed"])
    run, _ = _load_pdf_and_open_inline_editor(controller, model, view, path)
    before_undo = model.command_manager.undo_count

    QTest.keyClicks(view.text_editor.widget(), " TEST")
    _pump_events(80)
    assert "TEST" in view.text_editor.widget().toPlainText()

    QTest.keyClick(view.text_editor.widget(), Qt.Key_Escape)
    _pump_events(180)

    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo
    assert _norm(run.text) in _norm(model.doc[0].get_text("text"))


def test_19aa_inline_existing_text_ctrl_z_undoes_locally(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "ctrlz_inline_local.pdf", ["local undo seed"])
    _, _ = _load_pdf_and_open_inline_editor(controller, model, view, path)
    original_editor_text = view.text_editor.widget().toPlainText()
    before_undo = model.command_manager.undo_count
    before_redo = model.command_manager.redo_count

    QTest.keyClick(view.text_editor.widget(), Qt.Key_End)
    _pump_events(40)
    QTest.keyClicks(view.text_editor.widget(), "X")
    _pump_events(80)
    assert view.text_editor.widget().toPlainText().endswith("X")

    QTest.keyClick(view.text_editor.widget(), Qt.Key_Z, Qt.ControlModifier)
    _pump_events(180)

    assert view.text_editor is not None
    assert _norm(view.text_editor.widget().toPlainText()) == _norm(original_editor_text)
    assert model.command_manager.undo_count == before_undo
    assert model.command_manager.redo_count == before_redo


def test_19aaa_inline_existing_text_ctrl_z_on_real_multicolor_pdf_keeps_document_undo_idle(mvc):
    model, view, controller = mvc
    path = Path(__file__).resolve().parents[1] / "test_files" / "2.pdf"
    if not path.exists():
        pytest.skip("test_files/2.pdf is not available")

    _, _ = _load_pdf_and_open_inline_editor(controller, model, view, path)
    original_editor_text = view.text_editor.widget().toPlainText()
    before_undo = model.command_manager.undo_count
    before_redo = model.command_manager.redo_count

    QTest.keyClick(view.text_editor.widget(), Qt.Key_End)
    _pump_events(40)
    QTest.keyClicks(view.text_editor.widget(), "X")
    _pump_events(80)
    assert view.text_editor.widget().toPlainText().endswith("X")

    QTest.keyClick(view.text_editor.widget(), Qt.Key_Z, Qt.ControlModifier)
    _pump_events(180)

    assert view.text_editor is not None
    assert _norm(view.text_editor.widget().toPlainText()) == _norm(original_editor_text)
    assert model.command_manager.undo_count == before_undo
    assert model.command_manager.redo_count == before_redo


def test_19ab_inline_existing_text_ctrl_z_after_commit_undoes_document(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "ctrlz_inline_commit.pdf", ["commit undo seed"])
    run, viewport = _load_pdf_and_open_inline_editor(controller, model, view, path)
    before_undo = model.command_manager.undo_count
    before_redo = model.command_manager.redo_count

    QTest.keyClick(view.text_editor.widget(), Qt.Key_End)
    _pump_events(40)
    QTest.keyClicks(view.text_editor.widget(), "X")
    _pump_events(80)

    _click_outside_active_editor(view, viewport)

    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo + 1
    assert model.command_manager.redo_count == before_redo
    assert _norm("commit undo seedx") in _norm(model.doc[0].get_text("text"))

    shortcut_target = _active_shortcut_target(view)
    QTest.keyClick(shortcut_target, Qt.Key_Z, Qt.ControlModifier)
    _pump_events(220)

    assert model.command_manager.redo_count == before_redo + 1
    assert _norm(run.text) in _norm(model.doc[0].get_text("text"))

    shortcut_target = _active_shortcut_target(view)
    QTest.keyClick(shortcut_target, Qt.Key_Y, Qt.ControlModifier)
    _pump_events(220)

    assert model.command_manager.undo_count == before_undo + 1
    assert model.command_manager.redo_count == before_redo
    assert _norm("commit undo seedx") in _norm(model.doc[0].get_text("text"))


def test_19ac_inline_existing_text_cross_page_move_roundtrips_via_document_undo_redo(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "cross_page_gui_move.pdf", ["MOVE_ME", "KEEP_PAGE_TWO"])
    run, viewport = _load_pdf_and_open_inline_editor(controller, model, view, path)
    before_undo = model.command_manager.undo_count
    before_redo = model.command_manager.redo_count

    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    start = view.graphics_view.mapFromScene(editor_scene_rect.center())
    rs = view._render_scale if view._render_scale > 0 else 1.0
    dest_scene = QPoint(
        int(editor_scene_rect.center().x()),
        int(view.page_y_positions[1] + (72 * rs)),
    )
    end = view.graphics_view.mapFromScene(dest_scene)

    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    _pump_events(40)
    QTest.mouseMove(viewport, end, 20)
    _pump_events(120)
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
    _pump_events(180)

    assert view.text_editor is not None
    assert getattr(view, "_editing_page_idx", 0) == 1

    QTest.mouseClick(view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center())
    _pump_events(250)

    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo + 1
    assert model.command_manager.redo_count == before_redo
    assert "move_me" not in _norm(model.doc[0].get_text("text"))
    assert "move_me" in _norm(model.doc[1].get_text("text"))
    assert "keep_page_two" in _norm(model.doc[1].get_text("text"))

    shortcut_target = _active_shortcut_target(view)
    QTest.keyClick(shortcut_target, Qt.Key_Z, Qt.ControlModifier)
    _pump_events(220)

    assert model.command_manager.redo_count == before_redo + 1
    assert "move_me" in _norm(model.doc[0].get_text("text"))
    assert "move_me" not in _norm(model.doc[1].get_text("text"))
    assert "keep_page_two" in _norm(model.doc[1].get_text("text"))

    shortcut_target = _active_shortcut_target(view)
    QTest.keyClick(shortcut_target, Qt.Key_Y, Qt.ControlModifier)
    _pump_events(220)

    assert model.command_manager.undo_count == before_undo + 1
    assert model.command_manager.redo_count == before_redo
    assert "move_me" not in _norm(model.doc[0].get_text("text"))
    assert "move_me" in _norm(model.doc[1].get_text("text"))
    assert "keep_page_two" in _norm(model.doc[1].get_text("text"))


def test_19b_font_size_menu_keeps_editor_and_outside_focus_finalizes_editor(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "font_size_editor_focus.pdf", ["font size editor"])
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("edit_text")
    _pump_events(60)

    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)

    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)

    assert view.text_editor is not None
    QTest.mouseClick(view.text_size, Qt.LeftButton, Qt.NoModifier, view.text_size.rect().center())
    _pump_events(120)
    assert view.text_editor is not None

    view.text_size.setCurrentText("18")
    _pump_events(120)
    assert view.text_editor is not None
    assert view.text_editor.widget().font().pointSize() == 18

    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    outside_pos = view.graphics_view.mapFromScene(editor_scene_rect.bottomRight() + QPoint(40, 40))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, outside_pos)
    _pump_events(180)
    assert view.text_editor is None


def test_19c_edit_font_change_commits_without_text_change(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "edit_font_change.pdf", ["font-change token"])
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("edit_text")
    _pump_events(60)

    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)

    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None

    before_undo = model.command_manager.undo_count

    # Change font only via text-panel selector; keep text content unchanged.
    serif_idx = view.text_font.findData("tiro")
    assert serif_idx >= 0
    view.text_font.setCurrentIndex(serif_idx)
    _pump_events(140)
    assert view.text_editor is not None
    assert getattr(view, "editing_font_name", "") == "tiro"

    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    outside_pos = view.graphics_view.mapFromScene(editor_scene_rect.bottomRight() + QPoint(40, 40))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, outside_pos)
    _pump_events(220)
    assert view.text_editor is None

    assert model.command_manager.undo_count == before_undo + 1
    last_cmd = model.command_manager._undo_stack[-1]
    assert getattr(last_cmd, "_font", None) == "tiro"
    assert _norm("font-change token") in _norm(model.doc[0].get_text("text"))


def test_19d_text_apply_commits_and_cancel_discards(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "text_apply_cancel.pdf", ["apply cancel token"])
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("edit_text")
    _pump_events(60)

    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)
    viewport = view.graphics_view.viewport()

    before_undo = model.command_manager.undo_count

    # Cancel path: change style in editor, then cancel should close without commit.
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None
    mono_idx = view.text_font.findData("cour")
    assert mono_idx >= 0
    view.text_font.setCurrentIndex(mono_idx)
    _pump_events(80)
    QTest.mouseClick(view.text_cancel_btn, Qt.LeftButton, Qt.NoModifier, view.text_cancel_btn.rect().center())
    _pump_events(150)
    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo

    # Apply path: same style change, then apply should commit and close editor.
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None
    view.text_font.setCurrentIndex(mono_idx)
    _pump_events(80)
    QTest.mouseClick(view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center())
    _pump_events(180)
    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo + 1


def test_19e_cjk_font_change_commits_without_text_change(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf_with_font(tmp_path / "cjk_font_change.pdf", "中文字體測試", "china-ts", 12)
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("edit_text")
    _pump_events(60)

    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)

    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None

    before_undo = model.command_manager.undo_count

    cjk_sans_idx = view.text_font.findData("china-ss")
    assert cjk_sans_idx >= 0
    view.text_font.setCurrentIndex(cjk_sans_idx)
    _pump_events(140)
    assert view.text_editor is not None
    assert getattr(view, "editing_font_name", "") == "china-ss"

    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    outside_pos = view.graphics_view.mapFromScene(editor_scene_rect.bottomRight() + QPoint(40, 40))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, outside_pos)
    _pump_events(220)
    assert view.text_editor is None

    assert model.command_manager.undo_count == before_undo + 1
    last_cmd = model.command_manager._undo_stack[-1]
    assert getattr(last_cmd, "_font", None) == "china-ss"
    assert _norm("中文字體測試") in _norm(model.doc[0].get_text("text"))


def test_19f_convert_text_to_html_uses_cjk_companion_font(mvc):
    model, _, _ = mvc
    html_serif = model._convert_text_to_html("中文ABC", 12, (0.0, 0.0, 0.0), latin_font="tiro")
    html_sans = model._convert_text_to_html("中文ABC", 12, (0.0, 0.0, 0.0), latin_font="helv")
    assert "font-family: china-ts;" in html_serif
    assert "font-family: china-ss;" in html_sans


def test_19f2_custom_cjk_font_generates_embedded_css(mvc):
    model, _, _ = mvc
    sample = "\u5929\u5730ABC"
    html = model._convert_text_to_html(sample, 12, (0.0, 0.0, 0.0), latin_font="dfkai-sb")
    css = model._build_insert_css(12, (0.0, 0.0, 0.0), "dfkai-sb")
    assert "PdfEditorDFKaiSB" in html
    if Path(r"C:\Windows\Fonts\kaiu.ttf").exists():
        assert "@font-face" in css
        assert "PdfEditorDFKaiSB" in css


def test_19g_add_text_cjk_font_selection_commits(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "add_text_cjk_font.pdf", ["seed"])
    controller.open_pdf(str(path))
    _pump_events(300)

    before_undo = model.command_manager.undo_count
    view.set_mode("add_text")
    _pump_events(80)

    cjk_sans_idx = view.text_font.findData("china-ss")
    assert cjk_sans_idx >= 0
    view.text_font.setCurrentIndex(cjk_sans_idx)
    _pump_events(50)

    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport.rect().center())
    _pump_events(180)
    assert view.text_editor is not None

    view.text_editor.widget().setPlainText("新增中文文字框")
    _pump_events(40)
    QTest.mouseClick(view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center())
    _pump_events(250)

    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo + 1
    last_cmd = model.command_manager._undo_stack[-1]
    assert getattr(last_cmd, "_font", None) == "china-ss"
    assert "新增中文文字框" in (model.doc[0].get_text("text") or "")


def test_19h_edit_existing_switch_to_dfkai_commits_font_token(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf_with_font(tmp_path / "edit_cjk_dfkai.pdf", "\u5929\u5730\u7384\u9ec3", "china-ss", 22)
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("edit_text")
    _pump_events(60)

    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)
    viewport = view.graphics_view.viewport()

    before_undo = model.command_manager.undo_count
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None

    idx = view.text_font.findData("dfkai-sb")
    assert idx >= 0
    view.text_font.setCurrentIndex(idx)
    _pump_events(120)
    assert getattr(view, "editing_font_name", "") == "dfkai-sb"

    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    outside_pos = view.graphics_view.mapFromScene(editor_scene_rect.bottomRight() + QPoint(40, 40))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, outside_pos)
    _pump_events(220)

    assert view.text_editor is None
    assert model.command_manager.undo_count == before_undo + 1
    last_cmd = model.command_manager._undo_stack[-1]
    assert getattr(last_cmd, "_font", None) == "dfkai-sb"


def test_19i_custom_windows_cjk_fonts_render_distinct_span_fonts(mvc):
    model, _, _ = mvc
    required = [
        Path(r"C:\Windows\Fonts\msjh.ttc"),
        Path(r"C:\Windows\Fonts\mingliu.ttc"),
        Path(r"C:\Windows\Fonts\kaiu.ttf"),
    ]
    if not all(p.exists() for p in required):
        pytest.skip("Windows CJK font files not available for embedding test")

    rendered_fonts = {}
    for token in ("microsoft jhenghei", "pmingliu", "dfkai-sb"):
        doc = fitz.open()
        page = doc.new_page()
        html = model._convert_text_to_html("\u5929\u5730\u7384\u9ec3", 38, (0.0, 0.0, 0.0), latin_font=token)
        css = model._build_insert_css(38, (0.0, 0.0, 0.0), token)
        page.insert_htmlbox(fitz.Rect(72, 72, 520, 320), html, css=css, rotate=0, scale_low=1)

        first_font = ""
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if (span.get("text") or "").strip():
                        first_font = str(span.get("font") or "")
                        break
                if first_font:
                    break
            if first_font:
                break
        assert first_font, f"no rendered span found for token={token}"
        rendered_fonts[token] = first_font

    assert len(set(rendered_fonts.values())) >= 2, rendered_fonts


def test_19j_font_popup_interaction_can_refocus_editor_without_finalize(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "popup_refocus_editor.pdf", ["popup refocus editor"])
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("edit_text")
    _pump_events(60)

    model.ensure_page_index_built(1)
    runs = [r for r in model.block_manager.get_runs(0) if (r.text or "").strip()]
    assert runs, "no editable run on page 1"
    run = runs[0]

    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    sx = ((run.bbox.x0 + run.bbox.x1) * 0.5) * rs
    sy = y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs
    click_pos = view.graphics_view.mapFromScene(sx, sy)
    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None

    # Interact with real font-size popup (not only programmatic setCurrentText).
    size_combo = view.text_size
    target_row = max(0, size_combo.findText("20"))
    size_combo.showPopup()
    _pump_events(100)
    popup_view = size_combo.view()
    idx = size_combo.model().index(target_row, 0)
    rect = popup_view.visualRect(idx)
    QTest.mouseClick(popup_view.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    _pump_events(140)
    assert view.text_editor is not None

    # Clicking back into editor should not trigger finalize.
    editor_scene_rect = view.text_editor.mapRectToScene(view.text_editor.boundingRect())
    editor_center = view.graphics_view.mapFromScene(editor_scene_rect.center())
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, editor_center)
    _pump_events(180)
    assert view.text_editor is not None

    # Still finalize on outside click.
    outside_pos = view.graphics_view.mapFromScene(editor_scene_rect.bottomRight() + QPoint(40, 40))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, outside_pos)
    _pump_events(220)
    assert view.text_editor is None


def test_20_escape_non_browse_switches_to_browse(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "esc_mode.pdf", ["esc mode"])
    controller.open_pdf(str(path))
    _pump_events(300)
    view.set_mode("highlight")
    _assert_mode_checked(view, "highlight")
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(80)
    assert view.current_mode == "browse"
    _assert_mode_checked(view, "browse")


def test_21_escape_browse_fallback_keeps_existing_sidebar_behavior(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "esc_browse.pdf", ["esc browse"])
    controller.open_pdf(str(path))
    _pump_events(250)
    view.set_mode("browse")
    view.left_sidebar.setCurrentIndex(1)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(80)
    assert view.current_mode == "browse"
    assert view.left_sidebar.currentIndex() == 0


def test_22_sticky_highlight_mode_after_draw(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "sticky_highlight.pdf", ["sticky highlight"])
    controller.open_pdf(str(path))
    _pump_events(500)
    view.set_mode("highlight")
    viewport = view.graphics_view.viewport()
    start = viewport.rect().center()
    end = start + QPoint(40, 20)
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(viewport, end, 10)
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
    _pump_events(120)
    assert view.current_mode == "highlight"
    _assert_mode_checked(view, "highlight")
    start2 = start + QPoint(10, 30)
    end2 = start2 + QPoint(30, 18)
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start2)
    QTest.mouseMove(viewport, end2, 10)
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end2)
    _pump_events(120)
    assert view.current_mode == "highlight"
    _assert_mode_checked(view, "highlight")


def test_23_sticky_add_annotation_mode_after_click(mvc, tmp_path, monkeypatch):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "sticky_annot.pdf", ["sticky annot"])
    controller.open_pdf(str(path))
    _pump_events(400)
    monkeypatch.setattr(
        "view.pdf_view.QInputDialog.getMultiLineText",
        staticmethod(lambda *a, **k: ("note", True)),
    )
    view.set_mode("add_annotation")
    viewport = view.graphics_view.viewport()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport.rect().center())
    _pump_events(120)
    assert view.current_mode == "add_annotation"
    _assert_mode_checked(view, "add_annotation")
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport.rect().center() + QPoint(20, 20))
    _pump_events(120)
    assert view.current_mode == "add_annotation"
    _assert_mode_checked(view, "add_annotation")


def test_24_open_existing_file_keeps_current_mode(mvc, tmp_path):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "E1.pdf", ["e1"])
    b = _make_pdf(tmp_path / "E2.pdf", ["e2"])
    controller.open_pdf(str(a))
    sid_a = model.get_active_session_id()
    controller.open_pdf(str(b))
    assert len(model.session_ids) == 2

    view.set_mode("rect")
    _assert_mode_checked(view, "rect")

    controller.open_pdf(str(a))  # duplicate-open should focus existing tab
    _pump_events(120)
    assert model.get_active_session_id() == sid_a
    assert view.current_mode == "rect"
    _assert_mode_checked(view, "rect")


def test_25_close_last_tab_keeps_mode_when_window_stays_open(mvc, tmp_path, monkeypatch):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "Z1.pdf", ["z1"])
    controller.open_pdf(str(a))
    _pump_events(200)

    view.set_mode("add_annotation")
    _assert_mode_checked(view, "add_annotation")

    monkeypatch.setattr(controller, "_confirm_close_session", lambda sid: True)
    controller.on_tab_close_requested(0)
    _pump_events(100)

    assert not model.session_ids
    assert model.get_active_session_id() is None
    assert view.current_mode == "add_annotation"
    _assert_mode_checked(view, "add_annotation")


def test_26_fullscreen_no_document_is_noop(mvc):
    _, view, _ = mvc
    view.show()
    _pump_events(120)

    normal_geometry = view.geometry()
    _trigger_fullscreen(view)

    assert not view.isFullScreen()
    assert view.geometry() == normal_geometry


def test_27_fullscreen_enter_and_escape_restore_chrome(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_enter_exit.pdf", ["page 1", "page 2"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(500)

    assert not view.isFullScreen()
    assert view._toolbar_container.isVisible()
    assert view.left_sidebar_widget.isVisible()
    assert view.right_sidebar.isVisible()
    assert view.statusBar().isVisible()

    _trigger_fullscreen(view)

    assert view.isFullScreen()
    assert not view._toolbar_container.isVisible()
    assert not view.document_tab_bar.isVisible()
    assert not view.left_sidebar_widget.isVisible()
    assert not view.right_sidebar.isVisible()
    assert not view.statusBar().isVisible()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(220)

    assert not view.isFullScreen()
    assert view._toolbar_container.isVisible()
    assert view.left_sidebar_widget.isVisible()
    assert view.right_sidebar.isVisible()
    assert view.statusBar().isVisible()


def test_28_fullscreen_restores_zoom_scroll_and_dirty_state(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_restore_state.pdf", [f"page {i}" for i in range(1, 7)])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(700)

    controller.change_scale(view.current_page, 1.8)
    _pump_events(300)
    view.scroll_to_page(3)
    _pump_events(120)
    view.graphics_view.verticalScrollBar().setValue(view.graphics_view.verticalScrollBar().value() + 80)
    _pump_events(120)
    _make_dirty(model)

    before_scale = view.scale
    before_vscroll = view.graphics_view.verticalScrollBar().value()
    before_hscroll = view.graphics_view.horizontalScrollBar().value()
    before_page = view.current_page

    _trigger_fullscreen(view)
    assert view.isFullScreen()
    assert view.scale != before_scale

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(260)

    assert not view.isFullScreen()
    assert view.scale == pytest.approx(before_scale)
    assert view.current_page == before_page
    assert view.graphics_view.verticalScrollBar().value() == before_vscroll
    assert view.graphics_view.horizontalScrollBar().value() == before_hscroll
    assert model.has_unsaved_changes()


def test_29_fullscreen_clears_search_and_cancels_editor(mvc, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_clear_state.pdf", ["alpha key", "beta key"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(450)

    controller.search_text("alpha")
    view.search_input.setText("alpha")
    _pump_events(120)
    assert view.current_search_results

    view.set_mode("edit_text")
    _pump_events(80)
    model.ensure_page_index_built(1)
    run = next(r for r in model.block_manager.get_runs(0) if (r.text or "").strip())
    rs = view._render_scale if view._render_scale > 0 else 1.0
    y0 = view.page_y_positions[0] if view.page_y_positions else 0.0
    click_pos = view.graphics_view.mapFromScene(((run.bbox.x0 + run.bbox.x1) * 0.5) * rs, y0 + ((run.bbox.y0 + run.bbox.y1) * 0.5) * rs)
    QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    assert view.text_editor is not None

    _trigger_fullscreen(view)

    assert view.isFullScreen()
    assert view.text_editor is None
    assert view.current_mode == "browse"
    assert view.search_input.text() == ""
    assert not view.current_search_results


def test_30_fullscreen_blocked_while_print_busy_or_modal(mvc, tmp_path, monkeypatch):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_blocked.pdf", ["blocked"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    monkeypatch.setattr(controller, "_has_active_print_submission", lambda: True)
    _trigger_fullscreen(view)
    assert not view.isFullScreen()

    monkeypatch.setattr(controller, "_has_active_print_submission", lambda: False)
    dialog = QDialog(view)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.show()
    _pump_events(120)
    try:
        _trigger_fullscreen(view)
        assert not view.isFullScreen()
    finally:
        dialog.close()
        _pump_events(80)


def test_31_fullscreen_exit_button_stays_visible(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_hover_exit.pdf", ["hover exit"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    _trigger_fullscreen(view)
    assert view.isFullScreen()

    exit_button = getattr(view, "_fullscreen_exit_button", None)
    assert exit_button is not None, "fullscreen exit button missing"
    assert exit_button.isVisible()

    center_widget = view.centralWidget()
    view._update_fullscreen_exit_hover(QPoint(center_widget.width() // 2, 2))
    _pump_events(80)
    assert exit_button.isVisible()

    view._update_fullscreen_exit_hover(QPoint(center_widget.width() // 2, max(30, center_widget.height() // 2)))
    _pump_events(80)
    assert exit_button.isVisible()


def test_32_fullscreen_tab_switch_restores_each_visited_tab_state(mvc, tmp_path):
    model, view, controller = mvc
    a = _make_pdf(tmp_path / "fullscreen_tab_a.pdf", [f"a{i}" for i in range(1, 6)])
    b = _make_pdf(tmp_path / "fullscreen_tab_b.pdf", [f"b{i}" for i in range(1, 6)])
    view.show()
    controller.open_pdf(str(a))
    controller.open_pdf(str(b))
    _pump_events(700)

    controller.on_tab_changed(0)
    _pump_events(250)
    controller.change_scale(view.current_page, 1.6)
    _pump_events(220)
    view.scroll_to_page(2)
    _pump_events(100)
    view.graphics_view.verticalScrollBar().setValue(view.graphics_view.verticalScrollBar().value() + 60)
    _pump_events(100)
    a_scale = view.scale
    a_scroll = view.graphics_view.verticalScrollBar().value()

    controller.on_tab_changed(1)
    _pump_events(250)
    controller.change_scale(view.current_page, 1.25)
    _pump_events(220)
    view.scroll_to_page(3)
    _pump_events(100)
    view.graphics_view.verticalScrollBar().setValue(view.graphics_view.verticalScrollBar().value() + 40)
    _pump_events(100)
    b_scale = view.scale
    b_scroll = view.graphics_view.verticalScrollBar().value()

    _trigger_fullscreen(view)
    assert view.isFullScreen()

    controller.on_tab_changed(0)
    _pump_events(300)
    assert view.isFullScreen()
    assert view.scale != pytest.approx(a_scale)

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(320)

    assert not view.isFullScreen()
    assert model.get_active_session_index() == 0
    assert view.scale == pytest.approx(a_scale)
    assert view.graphics_view.verticalScrollBar().value() == a_scroll

    controller.on_tab_changed(1)
    _pump_events(300)
    assert view.scale == pytest.approx(b_scale)
    assert view.graphics_view.verticalScrollBar().value() == b_scroll


def test_33_fullscreen_from_highlight_mode_cancels_partial_state_and_enters_browse(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_from_highlight.pdf", ["highlight fullscreen"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(350)

    view.set_mode("highlight")
    _pump_events(80)
    viewport = view.graphics_view.viewport()
    start = viewport.rect().center()
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    _pump_events(40)
    assert view.drawing_start is not None

    _trigger_fullscreen(view)

    assert view.isFullScreen()
    assert view.current_mode == "browse"
    assert view.drawing_start is None
    _assert_mode_checked(view, "browse")


def test_34_fullscreen_quick_button_sits_between_fit_and_undo_and_f5_toggles(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_quick_entry.pdf", ["quick entry"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    assert view._action_fullscreen.shortcut().toString() == "F5"
    assert view.fit_view_btn.x() < view.fullscreen_quick_btn.x() < view.toolbar_right.x()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_F5)
    _pump_events(180)
    assert view.isFullScreen()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_F5)
    _pump_events(220)
    assert not view.isFullScreen()


def test_34a_fullscreen_quick_button_has_12px_gap_from_fit_button(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_quick_spacing.pdf", ["quick spacing"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    fit_right = view.fit_view_btn.geometry().right()
    fullscreen_left = view.fullscreen_quick_btn.geometry().left()

    assert fullscreen_left - fit_right - 1 == 12


def test_34b_fullscreen_context_menu_offers_exit_action_and_triggers_toggle(mvc, tmp_path, monkeypatch):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_context_menu.pdf", ["context menu"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)
    _trigger_fullscreen(view)
    assert view.isFullScreen()

    observed: list[str] = []

    def _fake_exec(menu: QMenu, *args, **kwargs):
        labels = [action.text() for action in menu.actions() if action.text()]
        observed.extend(labels)
        for action in menu.actions():
            if action.text() == "離開全螢幕":
                action.trigger()
                break
        return None

    monkeypatch.setattr(QMenu, "exec_", _fake_exec)

    view._show_context_menu(view.graphics_view.viewport().rect().center())
    _pump_events(120)

    assert "離開全螢幕" in observed
    assert not view.isFullScreen()


def test_35_ctrl_alt_l_toggles_left_sidebar_with_focus_and_width_fallback(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "left_sidebar_toggle.pdf", ["page 1"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    baseline_left_width = view.main_splitter.sizes()[0]
    assert view.left_sidebar_widget.isVisible()

    view.graphics_view.viewport().setFocus()
    _pump_events(30)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(100)

    assert not view.left_sidebar_widget.isVisible()
    assert QApplication.focusWidget() in {view.graphics_view, view.graphics_view.viewport()}

    view._left_sidebar_last_width = 36
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(100)

    assert view.left_sidebar_widget.isVisible()
    assert view.main_splitter.sizes()[0] >= max(200, baseline_left_width - 20)
    assert QApplication.focusWidget() is view.left_sidebar.tabBar()


def test_36_ctrl_f_reopens_hidden_left_sidebar_and_focuses_search(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "left_sidebar_search_reopen.pdf", ["alpha beta"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    view.graphics_view.viewport().setFocus()
    _pump_events(30)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(100)
    assert not view.left_sidebar_widget.isVisible()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_F, Qt.ControlModifier)
    _pump_events(100)

    assert view.left_sidebar_widget.isVisible()
    assert view.left_sidebar.currentIndex() == 1
    assert QApplication.focusWidget() is view.search_input


def test_37_ctrl_alt_r_toggles_right_sidebar_with_focus_and_width_fallback(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "right_sidebar_toggle.pdf", ["page 1"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(320)

    baseline_right_width = view.main_splitter.sizes()[2]
    view.set_mode("add_text")
    _pump_events(80)
    assert view.right_sidebar.isVisible()

    view.graphics_view.viewport().setFocus()
    _pump_events(30)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_R, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(100)

    assert not view.right_sidebar.isVisible()
    assert QApplication.focusWidget() in {view.graphics_view, view.graphics_view.viewport()}

    view._right_sidebar_last_width = 36
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_R, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(100)

    assert view.right_sidebar.isVisible()
    assert view.main_splitter.sizes()[2] >= max(240, baseline_right_width - 20)
    assert QApplication.focusWidget() is view.text_font


def test_38_fullscreen_restores_user_hidden_sidebars(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fullscreen_hidden_sidebars.pdf", ["page 1", "page 2"])
    view.show()
    controller.open_pdf(str(path))
    _pump_events(400)

    view.graphics_view.viewport().setFocus()
    _pump_events(30)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_R, Qt.ControlModifier | Qt.AltModifier)
    _pump_events(120)

    assert not view.left_sidebar_widget.isVisible()
    assert not view.right_sidebar.isVisible()

    _trigger_fullscreen(view)
    assert view.isFullScreen()

    QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Escape)
    _pump_events(220)

    assert not view.isFullScreen()
    assert not view.left_sidebar_widget.isVisible()
    assert not view.right_sidebar.isVisible()
