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
    controller._thumb_gen_by_session = {}
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
    assert gen == controller._thumb_gen_by_session["sid-1"]


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
    gen_first = controller._thumb_gen_by_session["sid-1"]
    controller._invalidate_thumbnails([4])
    gen_second = controller._thumb_gen_by_session["sid-1"]

    # The thumb generation is the cancellation token: bumping it twice makes the
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
    controller._invalidate_thumbnails = MagicMock()

    controller.delete_pages([2])

    controller._invalidate_thumbnails.assert_called_once_with([2])


def test_invalidate_thumbnails_called_from_refresh_after_command_structural(qapp):
    controller = _build_minimal_controller()
    controller.view.current_page = 0
    controller.view.capture_viewport_anchor = MagicMock(return_value=None)
    controller._rebuild_continuous_scene = MagicMock()
    controller.load_annotations = MagicMock()
    controller._schedule_stale_index_drain = MagicMock()
    controller._invalidate_thumbnails = MagicMock()

    cmd = MagicMock()
    cmd.is_structural = True
    cmd.affected_pages = [4, 6]

    controller._refresh_after_command(cmd)

    controller._invalidate_thumbnails.assert_called_once_with([4, 6])


def test_invalidate_thumbnails_count_unchanged_skips_set_placeholders(qapp):
    """When page count hasn't changed and affected pages are known, prior
    thumbnails should be preserved (set_thumbnail_placeholders not called)."""
    controller = _build_minimal_controller(page_count=20)
    # Simulate that the thumbnail list already has 20 items (count unchanged).
    controller.view.thumbnail_list = MagicMock()
    controller.view.thumbnail_list.count = MagicMock(return_value=20)

    batched: list[tuple] = []
    controller._schedule_thumbnail_batch = lambda *args, **kwargs: batched.append(args)

    controller._invalidate_thumbnails([5, 8])
    _pump_until(lambda: bool(batched), qapp)

    # MUST NOT call set_thumbnail_placeholders — that clears all rows.
    controller.view.set_thumbnail_placeholders.assert_not_called()
    assert batched, "batch must still be scheduled"


def test_invalidate_thumbnails_count_unchanged_renders_only_affected_rows(qapp):
    """Rotate one page of a 2000-page doc should render ~1 page, not 2000."""
    controller = _build_minimal_controller(page_count=2000)
    controller.view.thumbnail_list = MagicMock()
    controller.view.thumbnail_list.count = MagicMock(return_value=2000)

    batched: list[tuple] = []
    controller._schedule_thumbnail_batch = lambda *args, **kwargs: batched.append((args, kwargs))

    controller._invalidate_thumbnails([500])
    _pump_until(lambda: bool(batched), qapp)

    assert batched
    # The batch should have a bounded end, not go to 2000.
    args = batched[0][0]
    # args: (start, sid, gen, end_limit) — end_limit must be present and < 2000.
    assert len(args) >= 4, "expected end_limit parameter in batch schedule"
    end_limit = args[3]
    assert end_limit <= 501, f"end_limit {end_limit} should cover only affected pages, not all 2000"


def test_invalidate_thumbnails_does_not_bump_load_gen(qapp):
    """Thumbnail invalidation must use a dedicated thumb gen counter, not
    bump the load gen (which would cancel viewport-anchor restore and the
    open-background fallback timer)."""
    controller = _build_minimal_controller(page_count=10)
    controller.view.thumbnail_list = MagicMock()
    controller.view.thumbnail_list.count = MagicMock(return_value=10)
    controller._schedule_thumbnail_batch = MagicMock()

    # Seed load gen so we can detect a bump.
    controller._load_gen_by_session["sid-1"] = 42

    controller._invalidate_thumbnails([3])

    assert controller._load_gen_by_session["sid-1"] == 42, (
        "_invalidate_thumbnails must NOT bump _load_gen_by_session"
    )


def test_invalidate_thumbnails_count_changed_still_resets_placeholders(qapp):
    """When page count changed (insert/delete), set_thumbnail_placeholders
    must still be called to resize the widget."""
    controller = _build_minimal_controller(page_count=12)
    # List has 10 items but doc now has 12 — count changed.
    controller.view.thumbnail_list = MagicMock()
    controller.view.thumbnail_list.count = MagicMock(return_value=10)
    controller._schedule_thumbnail_batch = MagicMock()

    controller._invalidate_thumbnails([11])

    controller.view.set_thumbnail_placeholders.assert_called_once_with(12)
