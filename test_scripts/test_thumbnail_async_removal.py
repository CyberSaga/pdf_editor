"""Thumbnail regression coverage retained from the R4 coordinator removal.

R4.3 (commit 60c36fc) offloaded large overlay-free thumbnail rebuilds to a background
``ThumbnailCoordinator``/``_ThumbnailWorker``. The review (R4-01…R4-04) found four
structural defects in that path: a cancelled session's queued batch could paint into the
newly-active tab (the ``batch_ready`` signal carried only ``(gen, start_index, images)``
and ``gen`` collides across sessions), the snapshot capture serialised on the GUI thread,
the decrypted snapshot survived tab close, and the sync fallback left the old worker
running. The replacement design keeps those regressions closed with immutable job identity,
file-backed workers, and a one-page-per-event-turn live fallback.

These tests now pin the replacement coordinator contract:
  1. the coordinator module is importable;
  2. ``_schedule_thumbnail_batch`` delegates without rendering inline;
  3. closing a tab releases that session's decrypted worker-snapshot bytes (R4-03);
  4. a stale generation token still drops late batches (cross-paint guard).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

from controller.pdf_controller import PDFController  # noqa: E402


def test_thumbnail_coordinator_module_available() -> None:
    from controller.thumbnail_coordinator import ThumbnailCoordinator

    assert ThumbnailCoordinator is not None


def test_schedule_thumbnail_batch_delegates_without_inline_render() -> None:

    controller = PDFController.__new__(PDFController)
    model = MagicMock()
    model.doc = MagicMock()
    model.doc.__len__ = lambda self=None: 8
    model.get_active_session_id = MagicMock(return_value="sid-1")
    model.get_thumbnail = MagicMock(return_value=object())
    controller.model = model
    controller.view = MagicMock()
    controller._thumb_gen_by_session = {"sid-1": 0}
    controller._color_profile_for_session = MagicMock(return_value="srgb")

    # A coordinator that, under HEAD, would claim the range and suppress the sync paint.
    coordinator = MagicMock()
    controller._thumbnail_coordinator = coordinator

    controller._schedule_thumbnail_batch(0, "sid-1", 0)

    coordinator.request.assert_called_once_with("sid-1", 0, 0, 8, "srgb")
    model.get_thumbnail.assert_not_called()
    controller.view.update_thumbnail_batch.assert_not_called()


def _close_ready_controller(sid: str = "sid-1") -> tuple[PDFController, dict]:
    """A controller wired with just enough state for ``on_tab_close_requested``."""
    controller = PDFController.__new__(PDFController)
    state = {"closed": False}
    model = MagicMock()
    model.get_session_id_by_index = MagicMock(return_value=sid)
    model.get_active_session_id = MagicMock(side_effect=lambda: None if state["closed"] else sid)
    model.session_has_unsaved_changes = MagicMock(return_value=False)

    def _close(closed_sid):
        state["closed"] = True

    model.close_session = MagicMock(side_effect=_close)
    controller.model = model

    view = MagicMock()
    view.text_editor = None
    controller.view = view

    controller._session_ui_state = {}
    controller._fullscreen_session_snapshots = {}
    controller._load_gen_by_session = {}
    controller._thumb_gen_by_session = {}
    controller._desired_scroll_page = {}
    controller._open_priority_page_by_session = {}
    controller._background_loading_started_by_session = {}
    controller._render_batch_pending_by_session = {}

    controller.cancel_ocr = MagicMock()
    controller._cancel_search = MagicMock()
    controller._thumbnail_coordinator = MagicMock()
    controller._capture_current_ui_state = MagicMock()
    controller._refresh_document_tabs = MagicMock()
    controller._reset_empty_ui = MagicMock()
    return controller, state


def test_close_session_clears_worker_snapshot_cache() -> None:
    """R4-03: closing the tab whose snapshot is cached must release the decrypted bytes.

    The worker-snapshot cache holds a full ``doc.tobytes()`` — plaintext for an encrypted
    document. Leaving it after the session is gone keeps decrypted content alive in memory.
    RED against HEAD: ``on_tab_close_requested`` never invalidates the cache.
    """
    controller, _ = _close_ready_controller("sid-1")
    controller._worker_snapshot_cache = ("sid-1", 1, b"decrypted-bytes")

    controller.on_tab_close_requested(0)

    controller._thumbnail_coordinator.cancel.assert_called_once_with("sid-1")
    assert controller._worker_snapshot_cache is None


def test_close_session_preserves_other_sessions_snapshot_cache() -> None:
    """Multi-tab safety: closing tab A must not drop tab B's cached snapshot."""
    controller, _ = _close_ready_controller("sid-A")
    controller._worker_snapshot_cache = ("sid-B", 3, b"other-tab-bytes")

    controller.on_tab_close_requested(0)

    assert controller._worker_snapshot_cache == ("sid-B", 3, b"other-tab-bytes")


def test_stale_generation_token_drops_late_batch() -> None:
    """Cross-paint guard: a superseded generation must not paint over the new tab.

    Green by construction with the synchronous scheduler (the gen check guards the body);
    pins the contract that R4-01 violated in the async path.
    """
    controller = PDFController.__new__(PDFController)
    model = MagicMock()
    model.doc = MagicMock()
    model.doc.__len__ = lambda self=None: 50
    model.get_active_session_id = MagicMock(return_value="sid-1")
    controller.model = model
    controller.view = MagicMock()
    controller._thumb_gen_by_session = {"sid-1": 5}

    controller._schedule_thumbnail_batch(0, "sid-1", 3)  # stale gen 3 != current 5

    controller.view.update_thumbnail_batch.assert_not_called()
