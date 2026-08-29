"""Bounded reuse of one PyMuPDF interpretation of a page state."""
from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import cast

import fitz


@dataclass
class PageInterpretation:
    """Interpretation of one page state.

    Built for the page's current content, used without intervening mutation,
    released before that state is reverted. Methods raise ``RuntimeError``
    after release. :meth:`release` is idempotent and no-throw.
    """

    _page: fitz.Page | None
    _raster_list: fitz.DisplayList | None
    _text_list: fitz.DisplayList | None
    _rawdict_textpage: fitz.TextPage | None = None
    _released: bool = False

    def _active(
        self,
    ) -> tuple[fitz.Page, fitz.DisplayList, fitz.DisplayList]:
        page = self._page
        raster_list = self._raster_list
        text_list = self._text_list
        if self._released or page is None or raster_list is None or text_list is None:
            raise RuntimeError("page interpretation has been released")
        return page, raster_list, text_list

    def pixmap(
        self,
        *,
        dpi: int | float | None = None,
        matrix: fitz.Matrix = fitz.Identity,
        clip: fitz.Rect | tuple[float, float, float, float] | None = None,
    ) -> fitz.Pixmap:
        """Rasterize from the rotation-faithful display list."""
        _, raster_list, _ = self._active()
        if dpi:
            matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pixmap = raster_list.get_pixmap(
            matrix=matrix,
            colorspace=fitz.csRGB,
            alpha=False,
            clip=clip,
        )
        if dpi:
            pixmap.set_dpi(dpi, dpi)
        return pixmap

    def rawdict(self) -> dict[str, object]:
        """Return cropbox-faithful rawdict values from one lazy TextPage."""
        page, _, text_list = self._active()
        textpage = self._rawdict_textpage
        if textpage is None:
            raw_page = text_list.get_textpage(fitz.TEXTFLAGS_RAWDICT)
            textpage = fitz.TextPage(raw_page)
            textpage.parent = weakref.proxy(page)
            self._rawdict_textpage = textpage
        return cast(dict[str, object], page.get_text("rawdict", textpage=textpage))

    def clipped_text(self, clip_dict_space: fitz.Rect) -> str:
        """Extract clip-specific text by replaying the derotated text list."""
        _, _, text_list = self._active()
        options = fitz.mupdf.FzStextOptions()
        options.flags = fitz.TEXTFLAGS_TEXT
        raw_page = fitz.mupdf.FzStextPage(
            fitz.JM_rect_from_py(clip_dict_space)
        )
        device = fitz.mupdf.fz_new_stext_device(raw_page, options)
        try:
            fitz.mupdf.fz_run_display_list(
                text_list.this,
                device,
                fitz.JM_matrix_from_py(fitz.Identity),
                fitz.mupdf.FzRect(fitz.mupdf.FzRect.Fixed_INFINITE),
                fitz.mupdf.FzCookie(),
            )
        finally:
            fitz.mupdf.fz_close_device(device)
        return fitz.TextPage(raw_page).extractText()

    def release(self) -> None:
        """Drop MuPDF wrapper references in dependency order."""
        self._rawdict_textpage = None
        self._text_list = None
        self._raster_list = None
        self._page = None
        self._released = True


def interpret_page(page: fitz.Page) -> PageInterpretation:
    """Build raster- and text-faithful display lists for one page state."""
    old_rotation = page.rotation
    raster_list: fitz.DisplayList | None = None
    text_list: fitz.DisplayList | None = None
    try:
        raster_list = page.get_displaylist(annots=True)
        if old_rotation == 0:
            text_list = raster_list
        else:
            page.set_rotation(0)
            try:
                text_list = page.get_displaylist(annots=True)
            finally:
                page.set_rotation(old_rotation)
    except BaseException:
        text_list = None
        raster_list = None
        raise
    return PageInterpretation(page, raster_list, text_list)
