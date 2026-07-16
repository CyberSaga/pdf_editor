from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QTabBar, QToolButton

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from view.pdf_view import PDFView


def _pump_events(ms: int = 180) -> None:
    app = QApplication.instance()
    assert app is not None
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_small_shell_collapses_sidebars_and_preserves_canvas(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    try:
        view.show()
        view.resize(1280, 800)
        _pump_events()
        assert view.left_sidebar_widget.isVisible()
        assert view.right_sidebar.isVisible()

        view.resize(720, 520)
        _pump_events()

        assert view.minimumSize() == QSize(720, 520)
        assert view.size().width() == 720
        assert view.size().height() == 520
        assert not view.left_sidebar_widget.isVisible()
        assert not view.right_sidebar.isVisible()
        viewport = view.graphics_view.viewport().size()
        assert viewport.width() >= 360
        assert viewport.height() >= 300
    finally:
        view.close()
        qapp.processEvents()


def test_restoring_shell_width_restores_previously_visible_sidebars(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    try:
        view.show()
        view.resize(1280, 800)
        _pump_events()
        view.resize(720, 520)
        _pump_events()
        assert not view.left_sidebar_widget.isVisible()
        assert not view.right_sidebar.isVisible()

        view.resize(1280, 800)
        _pump_events()

        assert view.left_sidebar_widget.isVisible()
        assert view.right_sidebar.isVisible()
        sizes = view.main_splitter.sizes()
        assert sizes[0] >= 200
        assert sizes[2] >= 240
    finally:
        view.close()
        qapp.processEvents()


def test_splitter_allows_sidebar_children_to_collapse(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    try:
        assert view.main_splitter.childrenCollapsible() is True
        assert view.main_splitter.isCollapsible(0) is True
        assert view.main_splitter.isCollapsible(2) is True
    finally:
        view.close()
        qapp.processEvents()


def _tabs() -> list[dict[str, object]]:
    return [
        {"id": "session-a", "display_name": "Alpha.pdf", "path": "C:/docs/Alpha.pdf", "dirty": False},
        {"id": "session-b", "display_name": "Beta.pdf", "path": "C:/docs/Beta.pdf", "dirty": True},
    ]


def _close_button(view: PDFView, index: int) -> QToolButton:
    widget = view.document_tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
    assert isinstance(widget, QToolButton)
    return widget


def test_document_tabs_use_explicit_always_visible_close_buttons(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    try:
        view.set_document_tabs(_tabs(), 0)
        first = _close_button(view, 0)
        second = _close_button(view, 1)

        assert view.document_tab_bar.tabsClosable() is False
        for button in (first, second):
            assert button.text() == "×"
            assert button.size() == QSize(20, 20)
            assert button.isVisibleTo(view.document_tab_bar)
            assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert first.property("active") is True
        assert second.property("active") is False

        view.document_tab_bar.setCurrentIndex(1)
        _pump_events(40)
        assert first.property("active") is False
        assert second.property("active") is True
    finally:
        view.close()
        qapp.processEvents()


def test_document_tab_close_button_delegates_to_existing_close_signal(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    emitted: list[int] = []
    view.sig_tab_close_requested.connect(emitted.append)
    try:
        view.set_document_tabs(_tabs(), 0)

        _close_button(view, 1).click()

        assert emitted == [1]
        assert view.document_tab_bar.count() == 2
    finally:
        view.close()
        qapp.processEvents()


def test_saved_tab_context_menu_emits_reveal_request_by_session_id(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    emitted: list[str] = []
    view.sig_reveal_document_requested.connect(emitted.append)
    tabs = _tabs()
    tabs[0]["reveal_available"] = True
    try:
        view.set_document_tabs(tabs, 0)
        menu = view._build_document_tab_context_menu(0)
        action = next(action for action in menu.actions() if action.text() == "開啟檔案所在位置")

        assert action.isEnabled()
        action.trigger()
        assert emitted == ["session-a"]
    finally:
        view.close()
        qapp.processEvents()


def test_unsaved_or_missing_tab_disables_reveal_action(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    tabs = _tabs()
    tabs[0]["reveal_available"] = False
    tabs[1]["path"] = None
    tabs[1]["reveal_available"] = False
    try:
        view.set_document_tabs(tabs, 0)
        for index in range(2):
            menu = view._build_document_tab_context_menu(index)
            action = next(action for action in menu.actions() if action.text() == "開啟檔案所在位置")
            assert not action.isEnabled()
    finally:
        view.close()
        qapp.processEvents()


def test_canvas_navigation_keys_emit_bounded_page_targets(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    emitted: list[int] = []
    view.sig_page_changed.connect(emitted.append)
    try:
        view.show()
        view.total_pages = 5
        view.current_page = 2
        view.graphics_view.viewport().setFocus()

        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_PageDown)
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_PageUp)
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Home)
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_End)

        assert emitted == [3, 1, 0, 4]

        emitted.clear()
        view.current_page = 0
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_PageUp)
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_Home)
        view.current_page = 4
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_PageDown)
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_End)
        assert emitted == []
    finally:
        view.close()
        qapp.processEvents()


def test_page_navigation_keys_remain_owned_by_text_inputs(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    emitted: list[int] = []
    view.sig_page_changed.connect(emitted.append)
    edit = QLineEdit(view)
    try:
        view.show()
        view.total_pages = 5
        view.current_page = 2
        edit.show()
        edit.setFocus()

        QTest.keyClick(edit, Qt.Key_Home)
        QTest.keyClick(edit, Qt.Key_End)
        QTest.keyClick(edit, Qt.Key_PageUp)
        QTest.keyClick(edit, Qt.Key_PageDown)

        assert emitted == []
    finally:
        view.close()
        qapp.processEvents()


def test_recent_files_menu_marks_missing_entries_and_opens_available_paths(qapp) -> None:
    view = PDFView(defer_heavy_panels=True)
    emitted: list[str] = []
    view.sig_open_pdf.connect(emitted.append)
    try:
        view.set_recent_files(
            [
                {"path": r"C:\docs\available.pdf", "display_name": "available.pdf", "available": True},
                {"path": r"C:\docs\missing.pdf", "display_name": "missing.pdf", "available": False},
            ]
        )
        actions = view._recent_files_menu.actions()

        assert actions[0].isEnabled()
        assert not actions[1].isEnabled()
        assert "不存在" in actions[1].text()
        actions[0].trigger()
        assert emitted == [r"C:\docs\available.pdf"]
    finally:
        view.close()
        qapp.processEvents()


class _RecordingPreferences:
    def __init__(self) -> None:
        self.added: list[str] = []

    def get_recent_files(self) -> list[str]:
        return list(reversed(self.added))

    def add_recent_file(self, path: str) -> bool:
        self.added.append(str(path))
        return True


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "shell tab ux")
    doc.save(path)
    doc.close()
    return path


def test_controller_records_recent_file_only_after_successful_open(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import controller.pdf_controller as controller_module

    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    prefs = _RecordingPreferences()
    controller._prefs = prefs
    view.controller = controller
    monkeypatch.setattr(controller_module, "show_error", lambda *_args, **_kwargs: None)
    try:
        controller.activate()
        valid = _make_pdf(tmp_path / "successful.pdf")
        controller.open_pdf(str(valid))
        controller.open_pdf(str(tmp_path / "missing.pdf"))

        assert prefs.added == [str(valid)]
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_controller_resolves_reveal_request_from_session_metadata(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import controller.pdf_controller as controller_module

    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    controller._prefs = _RecordingPreferences()
    view.controller = controller
    revealed: list[str] = []
    monkeypatch.setattr(
        controller_module,
        "reveal_in_file_manager",
        lambda path: revealed.append(path) or True,
    )
    try:
        controller.activate()
        path = _make_pdf(tmp_path / "reveal me.pdf")
        controller.open_pdf(str(path))
        session_id = model.get_active_session_id()
        assert session_id is not None

        view.sig_reveal_document_requested.emit(session_id)

        assert revealed == [str(path)]
    finally:
        model.close()
        view.close()
        qapp.processEvents()
