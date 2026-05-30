"""Theme tokens, the global QSS builder, and the status-bar theme switcher.

Translates the selected blocks of ``appearance_design/colors.css`` into a single
QSS string that is applied **once at the QApplication level** (so top-level
QMenu context menus and modal QDialogs inherit it, not just the main window),
and exposes a persistent switcher widget for the status-bar corner.

Four modes are offered, matching the four blocks documented in colors.css:

    alpine-snow        高山雪 Alpine Snow        light · classic Lupine (default)
    meadow-lupine      草甸魯冰 Meadow Lupine     light · low visual burden
    ink-porcelain      墨瓷 Ink Porcelain        dark  · low visual burden
    glimmering-glacier 冰川微光 Glimmering Glacier light · icy cerulean

The switcher previews each theme with its ``bg`` tone (one square per chip) so the
light modes stay distinguishable even when they share an accent, and rings the
active chip with ``accent``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Token name -> hex/rgba value, translated from the alpine-snow block of
# appearance_design/colors.css.
ALPINE_SNOW: dict[str, str] = {
    "bg": "#f0ecfa",
    "surface": "#fafafc",
    "sunken": "#e2dcf2",
    "elev": "#ffffff",
    "line": "#ddd6ec",
    "line_strong": "#b7add0",
    "line_soft": "#ebe5f6",
    "fg": "#0f172a",
    "fg_muted": "#3a4358",
    "fg_subtle": "#6b7280",
    "accent": "#4338ca",
    "accent_fg": "#ffffff",
    "accent_soft": "#e0dbf3",
    "hover": "rgba(40,28,72,0.06)",
    "pressed": "rgba(40,28,72,0.14)",
    "highlight": "#f0d670",
    "paper": "#ffffff",
}

# Light, low visual burden — translated from the meadow-lupine block.
MEADOW_LUPINE: dict[str, str] = {
    "bg": "#eae6f3",
    "surface": "#f5f7f2",
    "sunken": "#dbd6e9",
    "elev": "#fdfdf8",
    "line": "#d4d7cf",
    "line_strong": "#a4ab9d",
    "line_soft": "#e2e5dd",
    "fg": "#0f172a",
    "fg_muted": "#3a4358",
    "fg_subtle": "#697282",
    "accent": "#4338ca",
    "accent_fg": "#ffffff",
    "accent_soft": "#e2dcf3",
    "hover": "rgba(40,28,72,0.06)",
    "pressed": "rgba(40,28,72,0.14)",
    "highlight": "#f0d670",
    "paper": "#ffffff",
}

# Dark, low visual burden — translated from the ink-porcelain block.
INK_PORCELAIN: dict[str, str] = {
    "bg": "#18171c",
    "surface": "#232228",
    "sunken": "#101015",
    "elev": "#2a2931",
    "line": "#2b2a33",
    "line_strong": "#403e49",
    "line_soft": "#211f26",
    "fg": "#e8e7eb",
    "fg_muted": "#a39fad",
    "fg_subtle": "#6f6c78",
    "accent": "#9b8fc0",
    "accent_fg": "#0d0c12",
    "accent_soft": "rgba(155,143,192,0.13)",
    "hover": "rgba(255,255,255,0.04)",
    "pressed": "rgba(255,255,255,0.12)",
    "highlight": "#e6c62c",
    "paper": "#f1efe8",
}

# Light, icy cerulean — translated from the glimmering-glacier block.
GLIMMERING_GLACIER: dict[str, str] = {
    "bg": "#e8f4fb",
    "surface": "#f4fafd",
    "sunken": "#d6ecf5",
    "elev": "#ffffff",
    "line": "#b8d9ee",
    "line_strong": "#7db9d8",
    "line_soft": "#daeef7",
    "fg": "#0c1a2e",
    "fg_muted": "#2d4a64",
    "fg_subtle": "#5d7a8e",
    "accent": "#0369a1",
    "accent_fg": "#ffffff",
    "accent_soft": "#cce6f7",
    "hover": "rgba(3,105,161,0.06)",
    "pressed": "rgba(3,105,161,0.14)",
    "highlight": "#67e8f9",
    "paper": "#ffffff",
}


@dataclass(frozen=True)
class ThemeMeta:
    """Static metadata for one selectable theme."""

    id: str
    label: str
    tokens: dict[str, str]
    swatch: str  # single representative colour for the switcher chip


def _meta(theme_id: str, label: str, tokens: dict[str, str]) -> ThemeMeta:
    # Use bg as the representative swatch: some light modes share the same
    # accent, so bg keeps every chip visually distinguishable.
    return ThemeMeta(id=theme_id, label=label, tokens=tokens, swatch=tokens["bg"])


# Insertion order is the on-screen order of the switcher chips.
THEME_REGISTRY: dict[str, ThemeMeta] = {
    "alpine-snow": _meta("alpine-snow", "高山雪 Alpine Snow", ALPINE_SNOW),
    "meadow-lupine": _meta("meadow-lupine", "草甸魯冰 Meadow Lupine", MEADOW_LUPINE),
    "ink-porcelain": _meta("ink-porcelain", "墨瓷 Ink Porcelain", INK_PORCELAIN),
    "glimmering-glacier": _meta(
        "glimmering-glacier", "冰川微光 Glimmering Glacier", GLIMMERING_GLACIER
    ),
}

_DEFAULT_THEME = "alpine-snow"


def build_qss(theme_name: str = _DEFAULT_THEME) -> str:
    """Return the complete application QSS for the named theme.

    Unknown names fall back to the default (Alpine Snow) theme.
    """
    t = (THEME_REGISTRY.get(theme_name) or THEME_REGISTRY[_DEFAULT_THEME]).tokens
    return f"""
        QMainWindow {{ background: {t["bg"]}; }}

        /* Default foreground so dark themes do not keep the OS's dark text on
           dark chrome (QSS does not inherit the platform palette's text role). */
        QWidget {{ color: {t["fg"]}; }}
        QLabel, QGroupBox, QPushButton, QCheckBox, QRadioButton,
        QLineEdit, QComboBox, QListWidget, QToolButton {{ color: {t["fg"]}; }}

        QGroupBox {{
            border: 1px solid {t["line"]};
            border-radius: 8px;
            margin-top: 8px;
            padding-top: 8px;
        }}

        /* Give buttons a themed surface; the global QWidget colour sets the
           label, so without this they keep the native light grey background
           (unreadable light-on-light text would appear under dark themes). */
        QPushButton {{
            border-radius: 6px;
            padding: 6px 12px;
            border: 1px solid {t["line"]};
            background: {t["elev"]};
        }}
        QPushButton:hover {{ background: {t["surface"]}; border-color: {t["line_strong"]}; }}
        QPushButton:pressed {{ background: {t["sunken"]}; }}
        QPushButton:disabled {{ color: {t["fg_subtle"]}; border-color: {t["line_soft"]}; }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
        QTextEdit, QPlainTextEdit {{
            border-radius: 6px;
            padding: 4px 8px;
            border: 1px solid {t["line"]};
            background: {t["elev"]};
            color: {t["fg"]};
        }}
        /* Combo-box popup list (otherwise a native light list under dark themes). */
        QComboBox QAbstractItemView {{
            background: {t["elev"]};
            color: {t["fg"]};
            border: 1px solid {t["line"]};
            selection-background-color: {t["accent"]};
            selection-color: {t["accent_fg"]};
        }}

        /* Modal dialogs (print, export, OCR, watermark, …). Applying the QSS at
           the QApplication level reaches these automatically; the explicit rule
           keeps their surface themed even when shown before the main window. */
        QDialog {{ background: {t["bg"]}; color: {t["fg"]}; }}

        /* Context menus are top-level QMenus (not children of any styled widget),
           so they only pick up theme colours from an application-level stylesheet. */
        QMenu {{ background: {t["elev"]}; color: {t["fg"]}; border: 1px solid {t["line"]}; }}
        QMenu::item:selected {{ background: {t["accent"]}; color: {t["accent_fg"]}; }}

        /* Disabled text must dim, not vanish, against the themed surface. */
        QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled,
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
        QDoubleSpinBox:disabled, QGroupBox:disabled {{ color: {t["fg_subtle"]}; }}

        /* Status bar (hosts the theme switcher) — keep its chrome themed so the
           permanent-widget chips stay legible under dark themes. */
        QStatusBar {{ background: {t["surface"]}; color: {t["fg"]}; }}
        QStatusBar::item {{ border: none; }}

        /* Left / right side panels. */
        QWidget#leftPanel, QWidget#rightPanel {{ background: {t["surface"]}; }}
        QWidget#colorProfileCard {{
            border-top: 1px solid {t["line"]};
            border-bottom: 1px solid {t["line"]};
        }}

        /* Left sidebar tab widget (縮圖 / 搜尋 / 註解列表 / 浮水印列表).
           Scoped to #sidebarTabs so it never clashes with the ribbon's tabs. */
        QTabWidget#sidebarTabs::pane {{
            border: 1px solid {t["line"]};
            background: {t["surface"]};
        }}
        QTabWidget#sidebarTabs QTabBar::tab {{
            padding: 5px 10px;
            margin-right: 2px;
            border: 1px solid {t["line"]};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            background: {t["sunken"]};
            color: {t["fg_muted"]};
        }}
        QTabWidget#sidebarTabs QTabBar::tab:selected {{
            background: {t["accent"]};
            color: {t["accent_fg"]};
        }}

        /* Sidebar lists (thumbnails / search / annotation / watermark). */
        QListWidget {{
            background: {t["elev"]};
            color: {t["fg"]};
            border: 1px solid {t["line"]};
        }}
        QListWidget::item:selected {{
            background: {t["accent"]};
            color: {t["accent_fg"]};
        }}

        /* Top toolbar container. */
        QFrame#toolbar {{
            background: {t["surface"]};
            border-bottom: 1px solid {t["line"]};
        }}

        /* Ribbon-style tab widget that hosts the tool toolbars.
           Scoped to #ribbonTabs so these rules do not leak onto the left
           sidebar's QTabWidget (縮圖 / 搜尋 / 註解列表 / 浮水印列表). */
        QTabWidget#ribbonTabs::pane {{ border: none; background: transparent; top: 0px; }}
        QTabWidget#ribbonTabs QTabBar::tab {{
            min-width: 52px;
            padding: 5px 10px;
            margin-right: 2px;
            background: transparent;
            color: {t["fg_muted"]};
        }}
        QTabWidget#ribbonTabs QTabBar::tab:selected {{
            background: {t["accent"]};
            color: {t["accent_fg"]};
            border-radius: 4px;
        }}

        /* Tool toolbars. */
        QToolBar {{ spacing: 4px; padding: 2px 0; }}
        QToolButton {{
            min-width: 52px;
            padding: 4px 8px;
            border-radius: 4px;
            color: {t["fg"]};
        }}
        QToolButton:hover {{ background: {t["hover"]}; }}
        QToolButton:pressed {{ background: {t["pressed"]}; }}
        QToolButton:checked {{ background: {t["accent"]}; color: {t["accent_fg"]}; }}

        /* Canvas well behind the pages. */
        QGraphicsView {{ background: {t["sunken"]}; border: none; }}

        /* Drag-and-drop affordance. */
        QWidget#dropHost[dragActive="true"] {{
            background: {t["accent_soft"]};
            border: 2px dashed {t["accent"]};
        }}

        /* Document-level tab bar (multiple open PDFs). */
        QTabBar#documentTabBar {{
            background: {t["surface"]};
            border-bottom: 1px solid {t["line"]};
            padding: 2px 6px;
        }}
        QTabBar#documentTabBar::tab {{
            min-width: 120px;
            max-width: 280px;
            padding: 6px 10px;
            margin-right: 2px;
            border: 1px solid {t["line"]};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            background: {t["sunken"]};
            color: {t["fg_muted"]};
        }}
        QTabBar#documentTabBar::tab:selected {{
            background: {t["elev"]};
            color: {t["fg"]};
            border-color: {t["line_strong"]};
        }}
    """


# Qt widgets are optional at import time so token-only tests (and any headless
# tooling) can import this module without a QApplication.
try:
    from PySide6.QtCore import QRectF, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget
except ImportError:  # pragma: no cover - exercised only in headless token tests
    pass
else:

    class _ThemeChip(QFrame):
        """A clickable preview of one theme: a single colour square + accent ring."""

        _SIZE = 16  # side length of the colour square, px
        _PAD = 4  # padding around the square (room for the active ring), px

        clicked = Signal()

        def __init__(self, meta: ThemeMeta, active: bool = False, parent=None) -> None:
            super().__init__(parent)
            self._meta = meta
            self._active = active
            self.setToolTip(meta.label)
            self.setCursor(Qt.PointingHandCursor)
            side = self._PAD * 2 + self._SIZE
            self.setFixedSize(QSize(side, side))

        def set_active(self, active: bool) -> None:
            if active != self._active:
                self._active = active
                self.update()

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            rect = QRectF(self._PAD, self._PAD, self._SIZE, self._SIZE)
            painter.setPen(QPen(QColor(self._meta.tokens["line_strong"]), 1))
            painter.setBrush(QColor(self._meta.swatch))
            painter.drawRoundedRect(rect, 3, 3)
            if self._active:
                # accent_soft may be rgba(); the accent token is always hex.
                painter.setPen(QPen(QColor(self._meta.tokens["accent"]), 2))
                painter.setBrush(Qt.NoBrush)
                ring = QRectF(1, 1, self.width() - 2, self.height() - 2)
                painter.drawRoundedRect(ring, 5, 5)
            painter.end()

        def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
            if event.button() == Qt.LeftButton:
                self.clicked.emit()
            super().mousePressEvent(event)

    class ThemeSwitcherWidget(QWidget):
        """A persistent row of single-square theme chips for the status bar corner."""

        theme_selected = Signal(str)

        def __init__(self, active_theme: str = _DEFAULT_THEME, parent=None) -> None:
            super().__init__(parent)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4, 0, 4, 0)
            layout.setSpacing(4)
            self._chips: dict[str, _ThemeChip] = {}
            for theme_id, meta in THEME_REGISTRY.items():
                chip = _ThemeChip(meta, active=(theme_id == active_theme), parent=self)
                chip.clicked.connect(lambda tid=theme_id: self.theme_selected.emit(tid))
                layout.addWidget(chip)
                self._chips[theme_id] = chip

        def set_active_theme(self, theme_id: str) -> None:
            for tid, chip in self._chips.items():
                chip.set_active(tid == theme_id)
