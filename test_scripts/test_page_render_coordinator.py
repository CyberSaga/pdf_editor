from __future__ import annotations

from unittest.mock import MagicMock

import fitz
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage, QPixmap

from controller.page_render_coordinator import (
    PageRenderCoordinator,
    PageRenderIdentity,
    PageRenderRequest,
    _PageRenderWorker,
)
from controller.pdf_controller import PDFController


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=240, height=160)
    page.insert_text((30, 60), "worker render", fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data


def _identity(**overrides) -> PageRenderIdentity:
    values = {
        "token": "token-1",
        "session_id": "sid-1",
        "generation": 7,
        "revision": 3,
        "page_index": 0,
        "quality": "high",
        "rendered_scale": 1.25,
        "target_scale": 1.25,
        "color_profile": "srgb",
        "device_pixel_ratio": 2.0,
    }
    values.update(overrides)
    return PageRenderIdentity(**values)


def _minimal_controller() -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = MagicMock()
    controller.model.doc.__len__ = lambda _self=None: 4
    controller.model.get_active_session_id.return_value = "sid-1"
    controller.view = MagicMock()
    controller.view.scale = 1.25
    controller.view.continuous_pages = True
    controller._render_gen_by_session = {"sid-1": 7}
    controller._render_revision_by_session = {"sid-1": 3}
    controller._render_batch_pending_by_session = {"sid-1": True}
    controller._page_render_quality_by_session = {"sid-1": {"srgb": {0: "low"}}}
    controller._render_cache = {}
    controller._render_cache_total_bytes = 0
    controller._worker_snapshot_cache = None
    controller._session_ui_state = {}
    controller._color_profile_for_session = MagicMock(return_value="srgb")
    controller._render_device_pixel_ratio = MagicMock(return_value=2.0)
    controller._page_render_coordinator = MagicMock()
    controller._thumbnail_coordinator = MagicMock()
    controller._thumbnail_resume_pending_by_session = set()
    controller.capture_worker_snapshot_bytes = MagicMock(return_value=_pdf_bytes())
    controller.get_watermarks = MagicMock(return_value=[])
    return controller


def test_worker_renders_snapshot_to_qimage_without_qpixmap() -> None:
    request = PageRenderRequest(identity=_identity(), snapshot_bytes=_pdf_bytes())
    images: list[tuple[PageRenderIdentity, QImage]] = []
    failures: list[Exception] = []
    finished: list[bool] = []
    worker = _PageRenderWorker(request)
    worker.rendered.connect(lambda identity, image: images.append((identity, image)))
    worker.failed.connect(lambda _identity, exc: failures.append(exc))
    worker.finished.connect(lambda _identity, succeeded: finished.append(succeeded))

    worker.run()

    assert failures == []
    assert finished == [True]
    assert len(images) == 1
    identity, image = images[0]
    assert identity == request.identity
    assert isinstance(image, QImage)
    assert not isinstance(image, QPixmap)
    assert image.width() >= 240
    assert image.height() >= 160


def test_coordinator_keeps_one_active_worker_and_only_latest_pending_request(monkeypatch) -> None:
    coordinator = PageRenderCoordinator(
        result_consumer=lambda *_args: None,
        failure_consumer=lambda *_args: None,
        identity_matches=lambda _identity: True,
    )
    started: list[PageRenderRequest] = []

    def fake_start(request: PageRenderRequest) -> None:
        started.append(request)
        coordinator._active = request

    monkeypatch.setattr(coordinator, "_start_worker", fake_start)
    monkeypatch.setattr(coordinator, "_cancel_active", MagicMock())

    coordinator.request(
        session_id="sid-1",
        generation=1,
        revision=0,
        page_index=0,
        quality="high",
        rendered_scale=1.0,
        target_scale=1.0,
        color_profile="srgb",
        device_pixel_ratio=1.0,
        snapshot_bytes=b"first",
    )
    coordinator.request(
        session_id="sid-1",
        generation=2,
        revision=0,
        page_index=1,
        quality="high",
        rendered_scale=1.0,
        target_scale=1.0,
        color_profile="srgb",
        device_pixel_ratio=1.0,
        snapshot_bytes=b"second",
    )
    coordinator.request(
        session_id="sid-1",
        generation=3,
        revision=0,
        page_index=2,
        quality="low",
        rendered_scale=0.5,
        target_scale=1.0,
        color_profile="srgb",
        device_pixel_ratio=1.0,
        snapshot_bytes=b"latest",
    )

    assert len(started) == 1
    assert coordinator._pending is not None
    assert coordinator._pending.identity.page_index == 2
    assert coordinator._pending.snapshot_bytes == b"latest"
    assert coordinator._cancel_active.call_count == 2


def test_controller_dispatches_high_render_without_inline_model_raster() -> None:
    controller = _minimal_controller()
    controller.model.get_page_pixmap.side_effect = AssertionError("GUI-thread raster")

    dispatched = controller._dispatch_page_render_request("sid-1", 0, "high", 7)

    assert dispatched is True
    controller.model.get_page_pixmap.assert_not_called()
    controller.capture_worker_snapshot_bytes.assert_called_once_with()
    kwargs = controller._page_render_coordinator.request.call_args.kwargs
    assert kwargs["session_id"] == "sid-1"
    assert kwargs["generation"] == 7
    assert kwargs["revision"] == 3
    assert kwargs["page_index"] == 0
    assert kwargs["quality"] == "high"
    assert kwargs["rendered_scale"] == 1.25
    assert kwargs["target_scale"] == 1.25
    assert kwargs["color_profile"] == "srgb"
    assert kwargs["device_pixel_ratio"] == 2.0


def test_prefetch_low_render_is_dispatched_instead_of_blocking_gui() -> None:
    controller = _minimal_controller()
    controller.model.get_page_pixmap.side_effect = AssertionError("prefetch rendered inline")
    controller._visible_render_targets = MagicMock(return_value=([0], [0, 1]))
    controller._page_render_quality_by_session["sid-1"]["srgb"] = {0: "high"}

    controller._process_visible_render_batch("sid-1", 7)

    controller.model.get_page_pixmap.assert_not_called()
    kwargs = controller._page_render_coordinator.request.call_args.kwargs
    assert kwargs["page_index"] == 1
    assert kwargs["quality"] == "low"
    assert kwargs["device_pixel_ratio"] == 1.0


def test_identity_rejects_every_stale_render_dimension() -> None:
    controller = _minimal_controller()
    current = _identity()

    assert controller._page_render_identity_matches(current) is True
    mismatches = (
        _identity(token="other"),
        _identity(session_id="sid-2"),
        _identity(generation=8),
        _identity(revision=4),
        _identity(page_index=9),
        _identity(rendered_scale=1.5),
        _identity(target_scale=1.5),
        _identity(color_profile="gray"),
        _identity(device_pixel_ratio=1.0),
    )
    controller._page_render_coordinator.active_token = "token-1"
    for stale in mismatches:
        assert controller._page_render_identity_matches(stale) is False


def test_accepted_worker_image_preserves_dpr_cache_and_scene_update(qapp) -> None:
    controller = _minimal_controller()
    controller._page_render_coordinator.active_token = "token-1"
    controller._store_cached_render = MagicMock()
    controller._maybe_start_background_loading_after_render = MagicMock()
    controller._render_batch_pending_by_session["sid-1"] = False
    image = QImage(600, 400, QImage.Format_RGB888)

    controller._consume_page_render_image(_identity(), image)

    stored = controller._store_cached_render.call_args.args
    pixmap = stored[5]
    assert isinstance(pixmap, QPixmap)
    assert pixmap.devicePixelRatio() == 2.0
    assert stored[:5] == ("sid-1", "srgb", 0, 1.25, "high")
    assert stored[6] == 2.0
    controller.view.update_page_in_scene_scaled.assert_called_once_with(0, pixmap, 1.25, 1.25)
    assert controller._page_quality_map("sid-1", "srgb")[0] == "high"


def test_worker_failure_keeps_low_preview_and_stops_batch() -> None:
    controller = _minimal_controller()
    controller._page_render_coordinator.active_token = "token-1"
    controller._page_render_quality_by_session["sid-1"]["srgb"] = {0: "low"}

    controller._on_page_render_failed(_identity(), RuntimeError("raster failed"))

    assert controller._page_quality_map("sid-1", "srgb")[0] == "low"
    assert controller._render_batch_pending_by_session["sid-1"] is False
    controller.view.update_page_in_scene_scaled.assert_not_called()
    controller.model.get_page_pixmap.assert_not_called()


def test_foreground_render_pauses_then_resumes_thumbnail_batch() -> None:
    controller = _minimal_controller()
    controller._thumb_gen_by_session = {"sid-1": 5}
    controller._thumbnail_coordinator.has_active_job = True
    controller._schedule_thumbnail_batch = MagicMock()

    controller._pause_thumbnails_for_visible_render("sid-1")

    controller._thumbnail_coordinator.cancel.assert_called_once_with("sid-1")
    assert "sid-1" in controller._thumbnail_resume_pending_by_session

    controller._resume_thumbnails_after_visible_render("sid-1", 7)
    assert "sid-1" not in controller._thumbnail_resume_pending_by_session
    controller._schedule_thumbnail_batch.assert_called_once_with(0, "sid-1", 5)


def test_watermarked_session_keeps_overlay_aware_sync_path() -> None:
    controller = _minimal_controller()
    controller.get_watermarks.return_value = [{"type": "text", "text": "DRAFT"}]

    assert controller._dispatch_page_render_request("sid-1", 0, "high", 7) is False
    controller._page_render_coordinator.request.assert_not_called()
    controller.capture_worker_snapshot_bytes.assert_not_called()


def test_dispatch_returns_before_next_event_loop_turn(qapp) -> None:
    controller = _minimal_controller()
    turns: list[str] = []
    QTimer.singleShot(0, lambda: turns.append("event-loop-ran"))

    assert controller._dispatch_page_render_request("sid-1", 0, "high", 7) is True
    assert turns == []
    qapp.processEvents()

    assert turns == ["event-loop-ran"]
    controller.model.get_page_pixmap.assert_not_called()


def test_live_worker_keeps_qt_event_loop_responsive(qapp) -> None:
    rendered: list[QImage] = []
    heartbeat: list[bool] = []
    coordinator = PageRenderCoordinator(
        result_consumer=lambda _identity, image: rendered.append(image),
        failure_consumer=lambda _identity, exc: (_ for _ in ()).throw(exc),
        identity_matches=lambda _identity: True,
    )
    coordinator.request(
        session_id="sid-live",
        generation=1,
        revision=0,
        page_index=0,
        quality="high",
        rendered_scale=1.0,
        target_scale=1.0,
        color_profile="srgb",
        device_pixel_ratio=1.0,
        snapshot_bytes=_pdf_bytes(),
    )
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    loop = QEventLoop()

    def poll() -> None:
        if rendered and heartbeat:
            loop.quit()
        else:
            QTimer.singleShot(5, poll)

    QTimer.singleShot(0, poll)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()

    assert heartbeat == [True]
    assert len(rendered) == 1
    assert coordinator.wait_for_done(1000) is True


def test_cancel_page_render_invalidates_generation_and_pending_batch() -> None:
    controller = _minimal_controller()

    controller._cancel_page_render_for_session("sid-1")

    assert controller._render_gen_by_session["sid-1"] == 8
    assert controller._render_batch_pending_by_session["sid-1"] is False
    controller._page_render_coordinator.cancel.assert_called_once_with("sid-1")
