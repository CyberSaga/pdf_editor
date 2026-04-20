from __future__ import annotations

import fitz  # PyMuPDF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QMessageBox


def parse_pages(input_str: str, total_pages: int) -> list[int]:
    """Parse a page range string like '1,3-5' -> [1,3,4,5]."""
    pages = set()
    for raw_part in input_str.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            if start > end:
                start, end = end, start
            pages.update(range(max(1, start), min(total_pages, end) + 1))
        else:
            page = int(part)
            if 1 <= page <= total_pages:
                pages.add(page)
    return sorted(pages)


def choose_color(parent) -> QColor:
    """Select a color via a QColorDialog."""
    color = QColorDialog.getColor(parent=parent)
    return color if color.isValid() else QColor(255, 255, 0, 128)


def show_error(parent, message: str) -> None:
    """Show an error message."""
    QMessageBox.critical(parent, "錯誤", message)


def pixmap_to_qimage(pix: fitz.Pixmap):
    """Convert a PyMuPDF pixmap to a detached QImage, bridging GRAY/CMYK safely."""
    from PySide6.QtGui import QImage

    if not pix.alpha and pix.colorspace is not None and pix.colorspace.n in {1, 4}:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def pixmap_to_qpixmap(pix: fitz.Pixmap):
    """Convert a PyMuPDF pixmap into QPixmap (safe for GRAY/CMYK)."""
    from PySide6.QtGui import QPixmap

    return QPixmap.fromImage(pixmap_to_qimage(pix))

