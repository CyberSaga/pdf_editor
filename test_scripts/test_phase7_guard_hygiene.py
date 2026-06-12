"""Phase 7 — guard funnel completion, optimizer objstms, wheel zoom, IPC hygiene."""

from __future__ import annotations

from unittest.mock import MagicMock

import fitz
import pytest


def test_render_page_pixmap_rejects_page_zero():
    """render_page_pixmap(page_num=0) must raise, not silently render doc[-1]."""
    from model.tools.manager import ToolManager

    model = MagicMock()
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.new_page(width=100, height=100)
    model.doc = doc
    model.get_active_session_id = MagicMock(return_value="sid")

    tm = ToolManager.__new__(ToolManager)
    tm._model = model
    tm._extensions = []

    with pytest.raises(ValueError):
        tm.render_page_pixmap(0)
    doc.close()


def test_render_page_pixmap_rejects_page_beyond_count():
    """render_page_pixmap(page_num > len(doc)) must raise."""
    from model.tools.manager import ToolManager

    model = MagicMock()
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    model.doc = doc
    model.get_active_session_id = MagicMock(return_value="sid")

    tm = ToolManager.__new__(ToolManager)
    tm._model = model
    tm._extensions = []

    with pytest.raises(ValueError):
        tm.render_page_pixmap(2)
    doc.close()


def test_wheel_zoom_no_overshoot_at_max():
    """At max zoom, wheel up should not visually overshoot past the cap."""
    from view.pdf_view import _MAX_VIEW_ZOOM, PDFView

    view = PDFView.__new__(PDFView)
    view.scale = _MAX_VIEW_ZOOM - 0.01
    view.text_editor = None

    transforms_applied: list[float] = []

    class _FakeGraphicsView:
        _t = 1.0

        def transform(self):
            from PySide6.QtGui import QTransform
            return QTransform()

        def setTransform(self, t):
            transforms_applied.append(t.m11())

    class _FakeTimer:
        def start(self, ms):
            pass

    view.graphics_view = _FakeGraphicsView()
    view._zoom_debounce_timer = _FakeTimer()

    class _FakeEvent:
        def modifiers(self):
            from PySide6.QtCore import Qt
            return Qt.ControlModifier

        def angleDelta(self):
            class _D:
                def y(self):
                    return 120
            return _D()

        def accept(self):
            pass

    view._wheel_event(_FakeEvent())

    assert view.scale == _MAX_VIEW_ZOOM
    assert transforms_applied, "transform must be applied"
    eff = transforms_applied[0]
    assert eff <= 1.05, (
        f"effective factor {eff} overshoots — should be ~{_MAX_VIEW_ZOOM / (_MAX_VIEW_ZOOM - 0.01):.4f}"
    )


def test_ipc_dash_prefix_not_skipped():
    """Tokens starting with '-' must NOT be silently skipped — they must
    fail validation if they don't resolve to a .pdf file."""
    from utils.single_instance import _forwarded_argv_is_acceptable

    assert _forwarded_argv_is_acceptable(["-malicious"]) is False, (
        "dash-prefixed tokens must be rejected, not skipped"
    )


def test_optimize_capabilities_object_streams_native(monkeypatch):
    """Object streams should be marked as natively available (no pikepdf needed)."""
    import model.pdf_optimizer as opt_mod
    from model.pdf_optimizer import optimize_capabilities

    monkeypatch.setattr(opt_mod, "_pikepdf", lambda: None)
    caps = optimize_capabilities()
    assert caps["object_streams"] is True, (
        "object_streams should be True even without pikepdf (native PyMuPDF use_objstms=1)"
    )
    assert caps["linearize"] is False, "linearize still needs pikepdf"


def test_fast_save_kwargs_passes_objstms_from_options():
    """fast_save_kwargs must set use_objstms=1 when options.use_object_streams is True."""
    from model.pdf_optimizer import PdfOptimizeOptions, fast_save_kwargs

    opts = PdfOptimizeOptions(use_object_streams=True)
    kwargs = fast_save_kwargs(opts)
    assert kwargs["use_objstms"] == 1, (
        f"use_objstms should be 1 when use_object_streams=True, got {kwargs['use_objstms']}"
    )


def test_requires_post_save_packaging_objstms_false():
    """Object streams don't require pikepdf post-save — only linearize does."""
    from model.pdf_optimizer import PdfOptimizeOptions, requires_post_save_packaging

    opts = PdfOptimizeOptions(use_object_streams=True, linearize=False)
    assert requires_post_save_packaging(opts) is False, (
        "use_object_streams alone should NOT require post-save packaging"
    )

    opts_lin = PdfOptimizeOptions(use_object_streams=False, linearize=True)
    assert requires_post_save_packaging(opts_lin) is True
