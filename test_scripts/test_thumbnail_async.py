"""Phase 4.1 — async thumbnail invalidation through the batch scheduler.

Structural operations must no longer render every thumbnail synchronously via
``_update_thumbnails``; they go through ``_invalidate_thumbnails(affected)``,
which pre-sets the widget item count and schedules the existing
``_schedule_thumbnail_batch`` chain on the next event-loop tick.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QEventLoop, QTimer

from controller.pdf_controller import PDFController


def _pump_until(predicate, qapp, timeout_ms: int = 2000) -> None:
    loop = QEventLoop()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(timeout_ms)

    def _check():
        if predicate():
            loop.quit()
        else:
            QTimer.singleShot(10, _check)

    QTimer.singleShot(0, _check)
    loop.exec()


def _build_minimal_controller(page_count: int = 10):
    """PDFController with mocked model/view; only thumbnail-related state."""
    controller = PDFController.__new__(PDFController)
    model = MagicMock()
    model.doc = MagicMock()
    model.doc.__len__ = lambda self=None: page_count
    model.get_active_session_id = MagicMock(return_value="sid-1")
    controller.model = model
    controller.view = MagicMock()
    controller._load_gen_by_session = {}
    return controller


def test_invalidate_thumbnails_uses_set_placeholders_not_update(qapp):
    controller = _build_minimal_controller(page_count=7)
    scheduled: list[tuple] = []
    controller._schedule_thumbnail_batch = lambda *args: scheduled.append(args)

    controller._invalidate_thumbnails([3])

    controller.view.set_thumbnail_placeholders.assert_called_once_with(7)
    controller.view.update_thumbnails.assert_not_called()


def test_invalidate_thumbnails_schedules_batch_with_correct_start_affected(qapp):
    controller = _build_minimal_controller()
    scheduled: list[tuple] = []
    controller._schedule_thumbnail_batch = lambda *args: scheduled.append(args)

    controller._invalidate_thumbnails([5, 3, 7])
    _pump_until(lambda: bool(scheduled), qapp)

    assert scheduled, "batch was never scheduled (QTimer.singleShot expected)"
    start, session_id, gen = scheduled[0]
    # min(affected)=3 -> one page before the first affected page -> index 1.
    assert start == 1
    assert session_id == "sid-1"
    assert gen == controller._load_gen_by_session["sid-1"]


def test_invalidate_thumbnails_full_rebuild_starts_at_zero(qapp):
    controller = _build_minimal_controller()
    scheduled: list[tuple] = []
    controller._schedule_thumbnail_batch = lambda *args: scheduled.append(args)

    controller._invalidate_thumbnails(None)
    _pump_until(lambda: bool(scheduled), qapp)

    assert scheduled
    assert scheduled[0][0] == 0


def test_invalidate_thumbnails_cancels_previous_batch(qapp):
    controller = _build_minimal_controller()
    scheduled: list[tuple] = []
    controller._schedule_thumbnail_batch = lambda *args: scheduled.append(args)

    controller._invalidate_thumbnails([2])
    gen_first = controller._load_gen_by_session["sid-1"]
    controller._invalidate_thumbnails([4])
    gen_second = controller._load_gen_by_session["sid-1"]

    # The load generation is the cancellation token: bumping it twice makes the
    # first scheduled chain exit at its gen check.
    assert gen_second == gen_first + 1
    _pump_until(lambda: len(scheduled) >= 2, qapp)
    gens = [entry[2] for entry in scheduled]
    assert gen_first in gens
    assert gen_second in gens


def test_update_thumbnails_no_longer_called_by_delete_pages(qapp):
    controller = _build_minimal_controller()
    controller.model.delete_pages = MagicMock(return_value=[2])
    controller.model._capture_doc_snapshot = MagicMock(return_value=b"snap")
    controller.view.current_page = 0
    controller._cancel_search = MagicMock()
    controller._invalidate_active_render_state = MagicMock()
    controller._rebuild_continuous_scene = MagicMock()
    controller._schedule_stale_index_drain = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()
    controller._update_thumbnails = MagicMock()
    controller._invalidate_thumbnails = MagicMock()

    controller.delete_pages([2])

    controller._update_thumbnails.assert_not_called()
    controller._invalidate_thumbnails.assert_called_once_with([2])


def test_invalidate_thumbnails_called_from_refresh_after_command_structural(qapp):
    controller = _build_minimal_controller()
    controller.view.current_page = 0
    controller.view.capture_viewport_anchor = MagicMock(return_value=None)
    controller._rebuild_continuous_scene = MagicMock()
    controller.load_annotations = MagicMock()
    controller._schedule_stale_index_drain = MagicMock()
    controller._update_thumbnails = MagicMock()
    controller._invalidate_thumbnails = MagicMock()

    cmd = MagicMock()
    cmd.is_structural = True
    cmd.affected_pages = [4, 6]

    controller._refresh_after_command(cmd)

    controller._update_thumbnails.assert_not_called()
    controller._invalidate_thumbnails.assert_called_once_with([4, 6])
