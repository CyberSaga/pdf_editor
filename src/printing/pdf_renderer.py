"""PDF raster renderer for print pipeline."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass

import fitz
from PySide6.QtGui import QImage

from utils.helpers import pixmap_to_qimage

from .errors import RenderingError


@dataclass
class RenderedPage:
    """Rendered page payload for print bridge."""

    page_index: int
    page_rect: fitz.Rect
    image: QImage


class PDFRenderer:
    """
    On-demand PDF renderer.

    Optimization strategy:
    - render one page at a time (streaming, lower memory)
    - cache DisplayList objects (faster repeated render on same pages)
    """

    def __init__(self, displaylist_cache_size: int = 24, colorspace: fitz.Colorspace = fitz.csRGB):
        self.displaylist_cache_size = max(1, int(displaylist_cache_size))
        self._colorspace = colorspace

    @staticmethod
    def get_page_count(pdf_path: str) -> int:
        doc = fitz.open(pdf_path)
        try:
            return len(doc)
        finally:
            doc.close()

    def _get_display_list(
        self,
        page_index: int,
        page: fitz.Page,
        cache: OrderedDict[int, fitz.DisplayList],
    ) -> fitz.DisplayList:
        if page_index in cache:
            dlist = cache.pop(page_index)
            cache[page_index] = dlist
            return dlist

        dlist = page.get_displaylist()
        cache[page_index] = dlist
        while len(cache) > self.displaylist_cache_size:
            cache.popitem(last=False)
        return dlist

    def iter_page_images(
        self,
        pdf_path: str,
        page_indices: list[int],
        dpi: int,
    ) -> Iterator[RenderedPage]:
        """Stream page images in requested order."""
        zoom = float(dpi) / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        doc = fitz.open(pdf_path)
        cache: OrderedDict[int, fitz.DisplayList] = OrderedDict()
        try:
            for page_index in page_indices:
                if page_index < 0 or page_index >= len(doc):
                    raise RenderingError(
                        f"Invalid page index {page_index} for doc with {len(doc)} pages."
                    )
                page = doc[page_index]
                dlist = self._get_display_list(page_index, page, cache)
                pix = dlist.get_pixmap(matrix=matrix, colorspace=self._colorspace, alpha=False)
                yield RenderedPage(
                    page_index=page_index,
                    page_rect=fitz.Rect(page.rect),
                    image=pixmap_to_qimage(pix),
                )
        except Exception as exc:
            if isinstance(exc, RenderingError):
                raise
            raise RenderingError(f"Failed to render PDF pages: {exc}") from exc
        finally:
            doc.close()

    def render_all_to_images(
        self,
        pdf_path: str,
        page_indices: list[int],
        dpi: int,
    ) -> list[RenderedPage]:
        """
        Naive baseline path for benchmarks.

        This eagerly stores all page images in memory and is intentionally
        less memory-efficient than iter_page_images().
        """
        return list(self.iter_page_images(pdf_path, page_indices, dpi))

    @staticmethod
    def parse_page_ranges(page_ranges: str | None, total_pages: int) -> list[int]:
        """Parse page-ranges like '1,3,5-7' into 0-based indices."""
        if total_pages <= 0:
            return []
        if not page_ranges:
            return list(range(total_pages))

        selected = set()
        for raw_part in page_ranges.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                left, right = part.split("-", 1)
                start = int(left.strip())
                end = int(right.strip())
                if start > end:
                    start, end = end, start
                for page_no in range(start, end + 1):
                    if 1 <= page_no <= total_pages:
                        selected.add(page_no - 1)
            else:
                page_no = int(part)
                if 1 <= page_no <= total_pages:
                    selected.add(page_no - 1)

        return sorted(selected)

