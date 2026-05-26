"""High-quality page renders must be rasterized at the display device-pixel ratio.

Mission: 文件檢視起來還得再更清晰一點 (text/images look blurry).

On HiDPI / Windows-scaled displays the viewport has a device-pixel ratio > 1.
If pages are rasterized only at the logical zoom scale, the OS upscales them to
physical pixels and they look blurry. The controller must rasterize HIGH-quality
pages at ``scale x devicePixelRatio`` and tag the pixmap's device-pixel ratio so
Qt draws them at native resolution. LOW-quality previews stay at logical scale.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 60), "clarity", fontsize=18, fontname="helv")
    doc.save(path)
    doc.close()


def test_high_quality_render_uses_device_pixel_ratio(qapp) -> None:
    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clarity.pdf"
        _make_pdf(path)

        model = PDFModel()
        view = PDFView()
        controller = PDFController(model, view)
        view.controller = controller
        controller.activate()
        view.show()
        try:
            for _ in range(10):
                qapp.processEvents()
            controller.open_pdf(str(path))
            for _ in range(20):
                qapp.processEvents()

            # Simulate a 2x HiDPI display.
            controller._render_device_pixel_ratio = lambda: 2.0  # type: ignore[method-assign]
            session_id = model.get_active_session_id()
            target_scale = max(0.1, float(view.scale))
            profile = controller._color_profile_for_session(session_id)

            assert controller._render_page_into_scene(session_id, 0, "high") is True
            hi = controller._get_cached_render(session_id, profile, 0, target_scale, "high", 2.0)
            assert hi is not None, "high-quality render not cached at dpr=2.0"
            assert abs(hi.devicePixelRatio() - 2.0) < 1e-6, (
                f"high-quality pixmap dpr {hi.devicePixelRatio()} != 2.0"
            )
            # Physical pixels must be ~2x the logical width (300pt x scale x 2).
            expected_px = 300.0 * target_scale * 2.0
            assert abs(hi.width() - expected_px) <= 4.0, (
                f"high-quality pixmap width {hi.width()} != ~{expected_px}"
            )

            # Low-quality previews stay at logical resolution (dpr 1.0).
            controller._render_page_into_scene(session_id, 0, "low")
            low_scale = controller._render_scale_for_quality(target_scale, "low")
            low = controller._get_cached_render(session_id, profile, 0, low_scale, "low", 1.0)
            assert low is not None, "low-quality render not cached at dpr=1.0"
            assert abs(low.devicePixelRatio() - 1.0) < 1e-6
        finally:
            view.close()
            view.deleteLater()
            model.close()
            qapp.processEvents()
