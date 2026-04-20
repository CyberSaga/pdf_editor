from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

import fitz
import pytest

from controller.pdf_controller import PDFController, SessionUIState


def _make_controller():
    sid = "sid-1"
    controller = PDFController.__new__(PDFController)
    controller.model = SimpleNamespace(doc=object(), get_active_session_id=lambda: sid)
    controller.view = SimpleNamespace(
        continuous_pages=True,
        current_page=0,
        page_items=[object()],
        scale=1.0,
    )
    controller._session_ui_state = {sid: SessionUIState()}
    controller._page_render_quality_by_session = {sid: {"srgb": {0: "high"}}}
    controller._load_gen_by_session = {}
    controller._render_cache = OrderedDict()
    controller._render_cache_total_bytes = 0

    scheduled: list[tuple[str, int | None]] = []
    thumb_batches: list[tuple[int, str, int]] = []

    controller._schedule_visible_render = lambda session_id, immediate_page_idx=None: scheduled.append(
        (session_id, immediate_page_idx)
    )
    controller._schedule_thumbnail_batch = lambda start, session_id, gen: thumb_batches.append((start, session_id, gen))
    controller.show_page = lambda _page_idx: None
    return controller, sid, scheduled, thumb_batches


def test_default_session_color_profile_is_srgb() -> None:
    controller, sid, _scheduled, _thumbs = _make_controller()
    assert controller._get_ui_state(sid).color_profile == "srgb"


def test_set_session_color_profile_updates_state_and_triggers_render_and_thumbs() -> None:
    controller, sid, scheduled, thumb_batches = _make_controller()
    controller.set_session_color_profile(sid, "gray")
    assert controller._get_ui_state(sid).color_profile == "gray"
    assert controller._page_render_quality_by_session[sid]["gray"] == {}
    assert scheduled == [(sid, 0)]
    assert thumb_batches
    assert thumb_batches[0][0] == 0
    assert thumb_batches[0][1] == sid


def test_set_session_color_profile_rejects_unknown_profile() -> None:
    controller, sid, _scheduled, _thumbs = _make_controller()
    with pytest.raises(ValueError):
        controller.set_session_color_profile(sid, "nope")


def test_visible_render_dispatch_passes_session_colorspace(monkeypatch) -> None:
    import controller.pdf_controller as controller_module

    sid = "sid-1"
    observed: dict[str, object] = {}

    class _Doc:
        def __len__(self) -> int:
            return 1

    model = SimpleNamespace(
        doc=_Doc(),
        get_active_session_id=lambda: sid,
        get_page_pixmap=lambda _page_num, _scale, *, colorspace=None: observed.setdefault("colorspace", colorspace)
        or object(),
    )

    view = SimpleNamespace(
        scale=1.0,
        continuous_pages=True,
        page_items=[object()],
        update_page_in_scene_scaled=lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(controller_module, "pixmap_to_qpixmap", lambda _pix: object())

    controller = PDFController.__new__(PDFController)
    controller.model = model
    controller.view = view
    controller._session_ui_state = {sid: SessionUIState(color_profile="cmyk")}
    controller._page_render_quality_by_session = {sid: {}}
    controller._maybe_start_background_loading_after_render = lambda *_args, **_kwargs: None
    controller._get_cached_render = lambda *_args, **_kwargs: None
    controller._store_cached_render = lambda *_args, **_kwargs: None

    assert controller._render_page_into_scene(sid, 0, "low") is True
    assert observed["colorspace"] is fitz.csCMYK

