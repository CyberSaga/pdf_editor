"""R3.7 hardening — TextSelectionManager scene-item cleanup must survive a
dangling C++ wrapper.

`QGraphicsScene.clear()` destroys the underlying C++ items but leaves the Python
wrappers dangling — calling `.scene()` / `removeItem()` on one then raises
`RuntimeError: Internal C++ object already deleted`. ObjectSelectionManager
guards this with `shiboken6.isValid(item)`; TextSelectionManager historically
relied on a broad `try/except` instead. Both reach a safe outcome, but the guard
path was untested. These characterization tests pin the crash-safe contract for
both text cleanup sites (`_clear_text_selection`, `_clear_text_selection_extra_rects`):
after `scene.clear()` the cleanup must NOT raise and must drop its references.

Teeth: the dangling state is verified real (shiboken6.isValid → False and a bare
`.scene()` call raises) before the cleanup runs, so a regression that removed the
guard and called `removeItem` directly would raise and fail these tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def view(qapp):
    from view.pdf_view import PDFView

    v = PDFView()
    try:
        yield v
    finally:
        v.close()


def _add_rect(view) -> QGraphicsRectItem:
    item = QGraphicsRectItem(QRectF(0, 0, 10, 10))
    view.scene.addItem(item)
    return item


def test_dangling_state_is_real(view) -> None:
    # Guards the guard: confirm scene.clear() actually invalidates the wrapper,
    # otherwise the cleanup tests below would be vacuous.
    item = _add_rect(view)
    assert shiboken6.isValid(item) is True
    view.scene.clear()
    assert shiboken6.isValid(item) is False
    with pytest.raises(RuntimeError):
        item.scene()


def test_clear_text_selection_survives_scene_clear(view) -> None:
    manager = view._ensure_text_selection_manager()
    manager._text_selection_rect_item = _add_rect(view)
    manager._text_selection_extra_rect_items = [_add_rect(view), _add_rect(view)]

    view.scene.clear()  # delete the underlying C++ items -> dangling wrappers

    manager._clear_text_selection()  # must not raise

    assert manager._text_selection_rect_item is None
    assert manager._text_selection_extra_rect_items == []


def test_clear_extra_rects_survives_scene_clear(view) -> None:
    manager = view._ensure_text_selection_manager()
    manager._text_selection_extra_rect_items = [_add_rect(view) for _ in range(3)]

    view.scene.clear()

    manager._clear_text_selection_extra_rects()  # must not raise

    assert manager._text_selection_extra_rect_items == []


def test_clear_removes_live_items_from_scene(view) -> None:
    # The happy path: a still-live selection rect is actually removed from the scene.
    manager = view._ensure_text_selection_manager()
    item = _add_rect(view)
    manager._text_selection_rect_item = item
    assert item.scene() is view.scene

    manager._clear_text_selection()

    assert manager._text_selection_rect_item is None
    assert shiboken6.isValid(item) is False or item.scene() is None
