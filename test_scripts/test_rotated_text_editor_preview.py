"""Rotated inline-editor preview must match the frozen-frame orientation.

Mission: 編輯轉向的文字時，文字框裡面的文字也要跟著轉向 (when editing rotated text
the content inside the editor must rotate with it).

The inline editor proxy applies ``setRotation(rotation)`` uniformly, and the
frozen first frame (the real pre-click MuPDF capture) is *counter-rotated to
upright* local space so that, after the proxy rotation, it lands at the source
orientation. The live CSS preview shown once the user types MUST use the same
upright convention. If the preview is rendered already-rotated, the proxy rotates
it a second time and the glyphs flip 90/180 degrees the moment the user types —
the box narrows but the content orientation breaks.

So ``PreviewRenderer.render`` must return UPRIGHT (horizontal) ink for a
narrow-tall rect at rotation 90/270, exactly as it does at rotation 0.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402

from model.pdf_model import PDFModel  # noqa: E402
from view.text_editing import PreviewRenderer  # noqa: E402

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


def _ink_dims(img: QImage) -> tuple[int, int]:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = memoryview(img.constBits())[: img.sizeInBytes()]
    assert np is not None
    arr = np.frombuffer(buf, dtype=np.uint8, count=img.bytesPerLine() * h).reshape(
        h, img.bytesPerLine()
    )
    alpha = arr[:, 3 : 4 * w : 4]
    ys, xs = np.where(alpha > 20)
    if len(xs) == 0:
        return 0, 0
    return int(xs.max() - xs.min()), int(ys.max() - ys.min())


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_preview_glyphs_stay_upright_for_proxy_rotation(rotation: int) -> None:
    model = PDFModel()
    renderer = PreviewRenderer(model=model)
    # Narrow-tall rect: representative of a real rotated/vertical text run. Width
    # is 60pt (not 20) so the upright "ABCDEFG" also fits horizontally at
    # rotation 0: PyMuPDF 1.27's insert_htmlbox renders *nothing* when content
    # overflows at scale_low=1 (1.25 rendered clipped glyphs), so a 20pt-wide box
    # produced zero ink for the unrotated control. 60x120 still exercises the
    # 90/270 wrap-dimension swap while fitting the text at every rotation.
    rect = fitz.Rect(0, 0, 60, 120)

    img = renderer.render(
        text="ABCDEFG",
        font_name="helv",
        font_size=10.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=rect,
        rotation=rotation,
        render_scale=2.0,
        line_height=0.0,
    )
    ink_w, ink_h = _ink_dims(img)
    assert ink_w > 0 and ink_h > 0, "preview produced no ink"
    # Upright glyphs => the line of text reads horizontally => ink is wider than
    # it is tall. The proxy's setRotation applies the visual rotation on top.
    assert ink_w > ink_h, (
        f"rotation={rotation}: preview ink {ink_w}x{ink_h} is not upright; "
        "the proxy rotation would double-rotate it"
    )
