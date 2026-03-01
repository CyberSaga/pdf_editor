import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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


def _norm(text: str) -> str:
    return "".join((text or "").lower().split())


def _pump_events(ms: int = 250) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


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


def test_17_fit_to_view_targets_current_page_not_full_scene(mvc, tmp_path):
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "fit_current_page.pdf", ["p1", "p2", "p3", "p4"])
    controller.open_pdf(str(path))
    _pump_events(1200)
    assert len(view.page_items) >= 4

    controller.change_page(2)
    _pump_events(100)
    view._fit_to_view()
    _pump_events(50)

    viewport_center = view.graphics_view.viewport().rect().center()
    scene_center = view.graphics_view.mapToScene(viewport_center)
    current_center = view.page_items[view.current_page].sceneBoundingRect().center()
    full_scene_center = view.scene.sceneRect().center()

    assert abs(scene_center.y() - current_center.y()) < 20
    assert abs(scene_center.y() - full_scene_center.y()) > 100


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
