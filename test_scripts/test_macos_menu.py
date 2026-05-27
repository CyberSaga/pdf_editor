"""AC-7 — macOS native menu bar.

Validates the menu structure/shortcuts produced for macOS and that the build is
a no-op on Windows/Linux (so those platforms are unaffected). The full Qt menu
bar requires a real macOS host, so we test the menu *spec* (which the builder
consumes) plus the platform guard.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

import view.pdf_view as pdf_view  # noqa: E402


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _view_with_actions() -> pdf_view.PDFView:
    """A PDFView shell with just the ribbon QActions the menu spec reuses."""
    _app()
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    for name in (
        "_action_open", "_action_save", "_action_save_as", "_action_print",
        "_action_undo", "_action_redo", "_action_fullscreen",
    ):
        setattr(view, name, QAction(name))
    return view


def _titles(spec) -> list[str]:
    return [title for title, _ in spec]


def _items(spec, title) -> list:
    for name, items in spec:
        if name == title:
            return items
    return []


def test_build_macos_menu_bar_is_noop_off_darwin(monkeypatch) -> None:
    """AC-7c: on Windows/Linux the menu bar build does nothing."""
    monkeypatch.setattr(pdf_view.sys, "platform", "win32")
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    assert pdf_view.PDFView._build_macos_menu_bar(view) is False

    monkeypatch.setattr(pdf_view.sys, "platform", "linux")
    assert pdf_view.PDFView._build_macos_menu_bar(view) is False


def test_macos_menu_spec_has_expected_menus_and_actions() -> None:
    """AC-7a: App/File/Edit/View/Window/Help with the expected entries."""
    view = _view_with_actions()
    spec = pdf_view.PDFView._macos_menu_spec(view)

    assert _titles(spec) == ["App", "File", "Edit", "View", "Window", "Help"]

    app_texts = [a.text() for a in _items(spec, "App")]
    assert any("About" in t for t in app_texts)
    assert any("Preferences" in t for t in app_texts)
    assert any("Quit" in t for t in app_texts)

    file_actions = _items(spec, "File")
    assert view._action_open in file_actions
    assert view._action_save in file_actions
    assert view._action_print in file_actions

    edit_actions = [a for a in _items(spec, "Edit") if a is not None]
    assert view._action_undo in edit_actions
    assert view._action_redo in edit_actions
    edit_texts = [a.text() for a in edit_actions]
    assert "Copy" in edit_texts
    assert "Paste" in edit_texts

    assert view._action_fullscreen in _items(spec, "View")


def test_macos_menu_uses_native_shortcuts() -> None:
    """AC-7b: Quit/Close/Copy/Paste use macOS standard shortcuts (Cmd-mapped)."""
    view = _view_with_actions()
    spec = pdf_view.PDFView._macos_menu_spec(view)
    by_text = {
        a.text(): a
        for _title, items in spec
        for a in items
        if a is not None
    }
    assert by_text["Quit PDF Editor"].shortcut() == QKeySequence(QKeySequence.StandardKey.Quit)
    assert by_text["Close Tab"].shortcut() == QKeySequence(QKeySequence.StandardKey.Close)
    assert by_text["Copy"].shortcut() == QKeySequence(QKeySequence.StandardKey.Copy)
    assert by_text["Paste"].shortcut() == QKeySequence(QKeySequence.StandardKey.Paste)
    # Close Tab must be wired to a real handler, not a missing attribute.
    assert callable(getattr(pdf_view.PDFView, "_close_current_document_tab", None))


def test_build_macos_menu_bar_assembles_menus_on_darwin(monkeypatch) -> None:
    """AC-7a: the darwin build path actually populates the menu bar."""
    _app()
    monkeypatch.setattr(pdf_view.sys, "platform", "darwin")
    host = QMainWindow()
    try:
        for name in (
            "_action_open", "_action_save", "_action_save_as", "_action_print",
            "_action_undo", "_action_redo", "_action_fullscreen",
        ):
            setattr(host, name, QAction(name, host))
        host._copy_selected_text_to_clipboard = lambda: None
        host._insert_image_object_from_clipboard_at_current_page = lambda: None
        host._close_current_document_tab = lambda: None
        host._macos_menu_spec = pdf_view.PDFView._macos_menu_spec.__get__(host)

        built = pdf_view.PDFView._build_macos_menu_bar(host)
        assert built is True
        menu_titles = [a.text() for a in host.menuBar().actions()]
        for expected in ("App", "File", "Edit", "View", "Window", "Help"):
            assert expected in menu_titles
    finally:
        host.deleteLater()


def test_app_menu_actions_have_macos_roles() -> None:
    """Role tags let Qt relocate About/Preferences/Quit into the app menu."""
    view = _view_with_actions()
    spec = pdf_view.PDFView._macos_menu_spec(view)
    roles = {a.text(): a.menuRole() for a in _items(spec, "App")}
    assert roles["About PDF Editor"] == QAction.MenuRole.AboutRole
    assert roles["Preferences…"] == QAction.MenuRole.PreferencesRole
    assert roles["Quit PDF Editor"] == QAction.MenuRole.QuitRole
