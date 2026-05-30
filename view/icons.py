"""Toolbar icon loading and the action-text -> PNG-filename mapping.

Icons live in ``appearance_design/function_icons/`` as 31 numbered PNGs. The
toolbar actions are created with Traditional-Chinese labels, so the mapping is
keyed on that label text and :func:`load_icon` takes a label (not a filename).

Qt imports are wrapped in ``try/except ImportError`` so the pure-Python parts
(:data:`ICON_DIR`, :data:`ACTION_ICON_MAP`) stay importable in a headless test
environment that has no PySide6.
"""

from __future__ import annotations

from pathlib import Path

ICON_DIR: Path = Path(__file__).resolve().parents[1] / "appearance_design" / "function_icons"

# Action label text -> PNG filename (31 ribbon actions).
ACTION_ICON_MAP: dict[str, str] = {
    "開啟": "01_開啟.png",
    "列印": "02_列印.png",
    "儲存": "03_儲存.png",
    "另存新檔": "04_另存新檔.png",
    "另存為最佳化的副本": "05_另存為最佳化的副本.png",
    "瀏覽模式": "06_瀏覽模式.png",
    "操作物件": "07_操作物件.png",
    "復原": "08_復原.png",
    "重做": "09_重做.png",
    "全螢幕": "10_全螢幕.png",
    "縮圖": "11_縮圖.png",
    "搜尋": "12_搜尋.png",
    "快照": "13_快照.png",
    "編輯文字": "14_編輯文字.png",
    "新增文字框": "15_新增文字框.png",
    "矩形": "16_矩形.png",
    "螢光筆": "17_螢光筆.png",
    "新增註解": "18_新增註解.png",
    "插入圖片": "19_插入圖片.png",
    "貼上圖片": "20_貼上圖片.png",
    "註解列表": "21_註解列表.png",
    "添加浮水印": "22_添加浮水印.png",
    "浮水印列表": "23_浮水印列表.png",
    "顯示/隱藏註解": "24_顯示-隱藏註解.png",
    "刪除頁": "25_刪除頁.png",
    "旋轉頁": "26_旋轉頁.png",
    "匯出頁": "27_匯出頁.png",
    "插入空白頁": "28_插入空白頁.png",
    "從檔案插入頁": "29_從檔案插入頁.png",
    "合併PDF": "30_合併PDF.png",
    "OCR（文字辨識）": "31_OCR（文字辨識）.png",
}


# Qt is optional at import time so the map above can be tested headless.
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QPixmap
except ImportError:  # pragma: no cover - exercised only in headless map-only tests
    pass
else:

    def load_icon(label: str, size: int = 24) -> QIcon:
        """Return the ``size``-square :class:`QIcon` for a ribbon action ``label``.

        Looks the label up in :data:`ACTION_ICON_MAP` and loads the matching PNG
        from :data:`ICON_DIR`, smooth-scaled to ``size``. Returns a null
        :class:`QIcon` for an unknown label or a missing/unreadable file so
        callers can assign the result unconditionally.
        """
        filename = ACTION_ICON_MAP.get(label)
        if filename is None:
            return QIcon()
        path = ICON_DIR / filename
        if not path.is_file():
            return QIcon()
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QIcon()
        scaled = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(scaled)
