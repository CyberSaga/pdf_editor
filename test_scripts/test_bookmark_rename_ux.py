from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, Qt

from view.pdf_view import PDFView


def test_bookmark_tree_has_custom_context_menu_policy(qapp) -> None:
    view = PDFView()
    try:
        assert view.bookmark_tree.contextMenuPolicy() == Qt.CustomContextMenu
    finally:
        view.close()
        qapp.processEvents()


def test_bookmark_context_menu_offers_rename_and_set_page_actions(qapp) -> None:
    view = PDFView()
    try:
        view.populate_toc([[1, "Root", 1], [1, "Second", 2]])
        item = view.bookmark_tree.topLevelItem(0)
        menu = view._build_bookmark_context_menu(item)
        labels = [action.text() for action in menu.actions()]
        assert "重新命名" in labels
        assert "設定頁碼" in labels
    finally:
        view.close()
        qapp.processEvents()


def test_bookmark_context_menu_rename_action_edits_title_column(qapp) -> None:
    view = PDFView()
    try:
        view.populate_toc([[1, "Root", 1]])
        item = view.bookmark_tree.topLevelItem(0)
        view.bookmark_tree.editItem = MagicMock()
        menu = view._build_bookmark_context_menu(item)
        rename_action = next(action for action in menu.actions() if action.text() == "重新命名")
        rename_action.trigger()
        view.bookmark_tree.editItem.assert_called_once_with(item, 0)
    finally:
        view.close()
        qapp.processEvents()


def test_bookmark_context_menu_set_page_action_edits_page_column(qapp) -> None:
    view = PDFView()
    try:
        view.populate_toc([[1, "Root", 1]])
        item = view.bookmark_tree.topLevelItem(0)
        view.bookmark_tree.editItem = MagicMock()
        menu = view._build_bookmark_context_menu(item)
        page_action = next(action for action in menu.actions() if action.text() == "設定頁碼")
        page_action.trigger()
        view.bookmark_tree.editItem.assert_called_once_with(item, 1)
    finally:
        view.close()
        qapp.processEvents()


def test_show_bookmark_context_menu_selects_item_under_cursor(qapp) -> None:
    view = PDFView()
    try:
        view.populate_toc([[1, "Root", 1], [1, "Second", 2]])
        item = view.bookmark_tree.topLevelItem(1)
        rect = view.bookmark_tree.visualItemRect(item)
        pos = rect.center()

        built_menus: list[object] = []
        original_build = view._build_bookmark_context_menu

        def _capture_and_build(target_item):
            menu = original_build(target_item)
            menu.exec = MagicMock()
            built_menus.append((target_item, menu))
            return menu

        view._build_bookmark_context_menu = _capture_and_build
        view._show_bookmark_context_menu(pos)

        assert view.bookmark_tree.currentItem() is item
        assert built_menus and built_menus[0][0] is item
    finally:
        view.close()
        qapp.processEvents()


def test_show_bookmark_context_menu_noop_when_no_item_at_pos(qapp) -> None:
    view = PDFView()
    try:
        view.populate_toc([[1, "Root", 1]])
        view._show_bookmark_context_menu(QPoint(5000, 5000))
    finally:
        view.close()
        qapp.processEvents()


def test_bookmark_rename_still_reachable_via_double_click_navigation(qapp) -> None:
    """Double-click must still navigate (itemActivated), not be hijacked by the menu."""
    view = PDFView()
    activated: list[int] = []
    view.sig_bookmark_activated.connect(activated.append)
    try:
        view.populate_toc([[1, "Root", 1], [2, "Child", 3]])
        root = view.bookmark_tree.topLevelItem(0)
        child = root.child(0)
        view._on_bookmark_activated(child, 0)
        assert activated == [2]
    finally:
        view.close()
        qapp.processEvents()
