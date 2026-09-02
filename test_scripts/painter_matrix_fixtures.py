"""Fixture mutators and raster oracles for the P4-B2 painter-geometry spike.

Everything here builds on :mod:`test_scripts.type0_fixture_builder` and the
two-painter page of ``test_text_commit_duplicate_painter_gate``.  Nothing
derives from a real document; nothing is written to disk.

The raster oracle (O4 in the spike plan) is the one ground truth every
other geometry oracle is measured against: two single-painter renders of
the same page, each with the OTHER painter switched to ``3 Tr`` (invisible,
still advancing), intersected pixel-wise at 8x (576 dpi).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_scripts.type0_fixture_builder import Type0Fixture  # noqa: E402

RASTER_SCALE = 8  # 576 dpi: one device pixel is 1/8 pt
INK_THRESHOLD = 128  # grey level below which a pixel counts as ink


@dataclass(frozen=True)
class InkMask:
    """One rendered clip as a packed ink bitmap (1 = ink)."""

    clip: tuple[float, float, float, float]
    width: int
    height: int
    bits: int

    @property
    def ink_pixels(self) -> int:
        return bin(self.bits).count("1")

    def overlap_pixels(self, other: InkMask) -> int:
        assert (self.width, self.height, self.clip) == (
            other.width,
            other.height,
            other.clip,
        ), "ink masks must share a clip"
        return bin(self.bits & other.bits).count("1")

    def bbox_pt(self) -> tuple[float, float, float, float] | None:
        """Axis-aligned bounds of the ink in page points, or ``None``."""
        if not self.bits:
            return None
        width = self.width
        total = width * self.height
        packed = self.bits.to_bytes(total, "big")
        xs: list[int] = []
        ys: list[int] = []
        for y in range(self.height):
            row = packed[y * width : (y + 1) * width]
            if not any(row):
                continue
            ys.append(y)
            xs.append(row.index(1))
            xs.append(width - 1 - row[::-1].index(1))
        x0, y0 = self.clip[0], self.clip[1]
        return (
            x0 + min(xs) / RASTER_SCALE,
            y0 + min(ys) / RASTER_SCALE,
            x0 + (max(xs) + 1) / RASTER_SCALE,
            y0 + (max(ys) + 1) / RASTER_SCALE,
        )


def render_ink_mask(
    page: fitz.Page, clip: tuple[float, float, float, float]
) -> InkMask:
    """Render ``clip`` of ``page`` at :data:`RASTER_SCALE` into an ink mask.

    Anti-aliasing stays at PyMuPDF's default (8 bits); the plan records
    the level so containment tolerances stay honest.
    """
    rect = fitz.Rect(*clip)
    pix = page.get_pixmap(
        matrix=fitz.Matrix(RASTER_SCALE, RASTER_SCALE),
        clip=rect,
        colorspace=fitz.csGRAY,
        alpha=False,
    )
    samples = pix.samples
    table = bytes(1 if value < INK_THRESHOLD else 0 for value in range(256))
    packed = samples.translate(table)
    return InkMask(
        clip=clip,
        width=pix.width,
        height=pix.height,
        bits=int.from_bytes(packed, "big"),
    )


def _with_stream(
    fixture: Type0Fixture, stream: bytes, clip: tuple[float, float, float, float]
) -> InkMask:
    original = fixture.content_bytes()
    fixture.doc.update_stream(fixture.content_xref, stream)
    try:
        return render_ink_mask(fixture.page, clip)
    finally:
        fixture.doc.update_stream(fixture.content_xref, original)


def two_painter_clip(
    fixture: Type0Fixture, *, pad: float = 80.0
) -> tuple[float, float, float, float]:
    """A page-space clip around the first painter wide enough for a twin
    placed within ``pad`` points of it on either side."""
    height = fixture.page.rect.height
    ox, oy = fixture.origin
    x0 = max(0.0, ox - pad)
    x1 = min(fixture.page.rect.width, ox + pad + len(fixture.text) * fixture.fontsize)
    y_page = height - oy
    return (x0, max(0.0, y_page - 3 * fixture.fontsize), x1, min(height, y_page + 2 * fixture.fontsize))


def single_painter_masks(
    fixture: Type0Fixture,
    *,
    clip: tuple[float, float, float, float] | None = None,
) -> tuple[InkMask, InkMask]:
    """Ink of painter 1 alone and painter 2 alone on a two-painter page.

    The page must have the ``_build_second_show_doc`` shape: one ``BT``,
    the first ``Tj`` followed by ``/<resource>`` for the second painter.
    The hidden painter is wrapped in ``3 Tr`` so its text state (and any
    cursor advance) still executes exactly as in the two-painter page.
    """
    stream = fixture.content_bytes()
    marker = b"> Tj /"
    assert stream.count(marker) == 1, "not a two-painter page"
    assert stream.count(b"BT ") == 1, "expected a single BT"
    clip = clip or two_painter_clip(fixture)
    first_only = stream.replace(marker, b"> Tj 3 Tr /", 1)
    second_only = stream.replace(b"BT ", b"BT 3 Tr ", 1).replace(
        marker, b"> Tj 0 Tr /", 1
    )
    return _with_stream(fixture, first_only, clip), _with_stream(
        fixture, second_only, clip
    )


def painters_overlap_pixels(fixture: Type0Fixture) -> int:
    """Pixels where painter 1's ink and painter 2's ink coincide."""
    first, second = single_painter_masks(fixture)
    return first.overlap_pixels(second)
