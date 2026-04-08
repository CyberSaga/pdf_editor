from __future__ import annotations

import fitz  # PyMuPDF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QMessageBox


def parse_pages(input_str: str, total_pages: int) -> list[int]:
    """解析頁碼輸入，如 '1,3-5' -> [1,3,4,5]"""
    pages = set()
    for part in input_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = map(int, part.split('-'))
            pages.update(range(max(1, start), min(total_pages, end) + 1))
        else:
            page = int(part)
            if 1 <= page <= total_pages:
                pages.add(page)
    return sorted(pages)

def choose_color(parent) -> QColor:
    """顏色選擇對話框"""
    color = QColorDialog.getColor(parent=parent)
    return color if color.isValid() else QColor(255, 255, 0, 128)  # 預設黃色半透明

def show_error(parent, message: str):
    """錯誤彈出"""
    QMessageBox.critical(parent, "錯誤", message)

def pixmap_to_qpixmap(pix: fitz.Pixmap) -> QPixmap:
    """fitz.Pixmap轉QPixmap"""
    from PySide6.QtGui import QImage, QPixmap
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888)
    return QPixmap.fromImage(img)
