"""RED: inline text editing on ``/Rotate`` pages through the real MVC stack.

Reproduces the P3-D manual smoke failure
(docs/history/reports/2026-08-29-p3d-manual-smoke-attempt.md) offscreen:
hover highlight / outlines must land on the visible glyphs, a click on the
visible glyphs must open the editor over them with the on-screen rotation,
an untouched session must not manufacture a style override, the plan-backed
preview must stay available on a rotated editor, and Apply must commit
through the Tier 0 plan path -- never the legacy fallback.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, TextCommitSettings  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402

from test_scripts.test_text_geometry_page_rotation import (  # noqa: E402
    REPLACEMENT,
    WORD,
    _ink_bbox,
    _write_rotated_pdf,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pump_events(ms: int = 250) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class _DeclineFallback:
    """Consent gate stand-in: records every legacy-fallback ask, answers No."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, chain: tuple[str, ...]) -> bool:
        self.calls.append(tuple(chain))
        return False


@pytest.fixture()
def gui(qapp, tmp_path, monkeypatch, request):
    rotation = request.param
    path = _write_rotated_pdf(tmp_path / f"gui_rot{rotation}.pdf", rotation)
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information",
        staticmethod(lambda *a, **k: None),
    )
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", preview="plan", max_tier=0)
    )
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    decline = _DeclineFallback()
    monkeypatch.setattr(controller, "_confirm_legacy_fallback", decline)
    view.resize(1400, 1000)
    view.show()
    view.activateWindow()
    _pump_events(120)
    controller.open_pdf(str(path))
    _pump_events(400)
    view.set_mode("edit_text")
    _pump_events(60)
    assert model.doc[0].rotation == rotation
    try:
        yield model, view, controller, rotation, decline
    finally:
        try:
            controller._end_text_edit_plan_preview_session()
        except Exception:
            pass
        model.close()
        view.close()
        _pump_events(60)


def _ink_scene_rect(view: PDFView, page: fitz.Page):
    ink = _ink_bbox(page)
    rs = view._render_scale if view._render_scale > 0 else 1.0
    x0 = view._page_scene_x(0)
    y0 = view._page_scene_y(0)
    return (
        x0 + ink.x0 * rs,
        y0 + ink.y0 * rs,
        x0 + ink.x1 * rs,
        y0 + ink.y1 * rs,
    )


def _click_ink(view: PDFView, page: fitz.Page):
    sx0, sy0, sx1, sy1 = _ink_scene_rect(view, page)
    centre = QPointF((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)
    view.graphics_view.centerOn(centre)
    _pump_events(60)
    click_pos = view.graphics_view.mapFromScene(centre)
    viewport = view.graphics_view.viewport()
    assert viewport.rect().contains(click_pos), (click_pos, viewport.rect())
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump_events(260)
    return centre


def _assert_scene_rects_overlap(a, b, min_ratio: float = 0.5) -> None:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    assert smaller > 0, (a, b)
    assert inter / smaller >= min_ratio, (a, b, inter / smaller)


# ------------------------------------------------------------------ tests


@pytest.mark.parametrize("gui", [90, 270], indirect=True)
def test_hover_highlight_and_outlines_land_on_visible_glyphs(gui) -> None:
    model, view, _controller, _rotation, _decline = gui
    sx0, sy0, sx1, sy1 = _ink_scene_rect(view, model.doc[0])
    centre = QPointF((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)

    view._update_hover_highlight(centre)
    item = view._hover_highlight_item
    assert item is not None, "hover over the visible glyphs must highlight a run"
    assert item.rect().contains(centre), (item.rect(), centre)

    model.set_text_target_mode("paragraph")
    view._draw_all_block_outlines()
    outlines = [i.rect() for i in view._block_outline_items.values()]
    assert outlines, "paragraph outlines expected"
    assert any(r.contains(centre) for r in outlines), (outlines, centre)


@pytest.mark.parametrize("gui", [90, 270], indirect=True)
def test_click_on_visible_glyphs_opens_editor_over_them_with_screen_rotation(gui) -> None:
    model, view, _controller, rotation, _decline = gui
    ink_scene = _ink_scene_rect(view, model.doc[0])

    _click_ink(view, model.doc[0])

    assert view.text_editor is not None, "click on the visible glyphs must open the editor"
    assert int(view._editing_rotation) == rotation
    proxy = view.text_editor
    r = proxy.mapRectToScene(proxy.boundingRect())
    _assert_scene_rects_overlap((r.left(), r.top(), r.right(), r.bottom()), ink_scene)


@pytest.mark.parametrize("gui", [0], indirect=True)
def test_untouched_session_sends_no_style_override(gui) -> None:
    """Opening the editor maps the source font to a UI alias; that is not a
    user restyle and must not reach the model as one."""
    model, view, _controller, _rotation, decline = gui
    _click_ink(view, model.doc[0])
    assert view.text_editor is not None
    captured: list = []
    view.sig_edit_text.connect(captured.append)

    view.text_editor.widget().setPlainText(REPLACEMENT)
    QTest.mouseClick(
        view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center()
    )
    _pump_events(300)

    assert captured, "Apply must emit the edit request"
    overrides = captured[-1].style_overrides
    assert overrides is None or not overrides.changed, overrides
    assert decline.calls == [], decline.calls
    outcome = model.last_commit_outcome
    assert outcome is not None and outcome.status is CommitStatus.COMMITTED, outcome


@pytest.mark.parametrize("gui", [90, 270], indirect=True)
def test_plan_preview_stays_available_on_rotated_editor(gui) -> None:
    model, view, _controller, rotation, _decline = gui
    _click_ink(view, model.doc[0])
    assert view.text_editor is not None
    editor = view.text_editor.widget()

    assert editor._plan_preview_hook is not None, "rotated editors must keep the exact preview"

    # A visual-space raster (tall for vertical glyphs) must be counter-rotated
    # into the proxy-local frame exactly like the frozen first frame is.
    raster = QImage(10, 30, QImage.Format_RGBA8888)
    raster.fill(QColor(255, 255, 255, 255))
    raster.setPixelColor(0, 0, QColor(255, 0, 0, 255))
    assert editor.apply_plan_preview(editor._plan_generation, raster, "tok") is True
    local = editor._preview_image
    assert local is not None
    assert (local.width(), local.height()) == (30, 10), (local.width(), local.height())
    marker = (29, 0) if rotation == 270 else (0, 9)
    assert local.pixelColor(*marker) == QColor(255, 0, 0, 255), marker


@pytest.mark.parametrize("gui", [270], indirect=True)
def test_apply_on_rotated_page_commits_through_the_plan_path(gui) -> None:
    model, view, _controller, _rotation, decline = gui
    ink_before = _ink_bbox(model.doc[0])
    _click_ink(view, model.doc[0])
    assert view.text_editor is not None

    view.text_editor.widget().setPlainText(REPLACEMENT)
    _pump_events(200)
    QTest.mouseClick(
        view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center()
    )
    _pump_events(400)

    assert view.text_editor is None
    assert decline.calls == [], f"legacy fallback must not be needed: {decline.calls}"
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH, outcome
    assert REPLACEMENT in model.doc[0].get_text("text")
    assert WORD not in model.doc[0].get_text("text")
    ink_after = _ink_bbox(model.doc[0])
    assert abs(ink_after.x0 - ink_before.x0) <= 3 and abs(ink_after.y0 - ink_before.y0) <= 3
