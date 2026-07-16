"""Theme tokens, the global QSS builder, and the status-bar theme switcher.

Translates the selected blocks of ``docs/design/colors.css`` into a single
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

Token note: ``accent_line`` / ``hover_strong`` / ``shadow`` are brand colours
lifted verbatim from ``colors.css`` (``--color-accent-line``,
``--color-hover-strong``, and the ``--shadow-*`` hue). They were documented in
the palette but never plumbed into the QSS; they back focus rings, tab hover,
and chrome elevation (``QGraphicsDropShadowEffect``) without introducing any new
hue. Qt QSS has no ``box-shadow`` and no CSS transitions, so "smooth feedback"
here means crisp, well-differentiated ``:hover`` / ``:pressed`` / ``:focus``
states, and real drop shadows are applied in code via :func:`shadow_color`.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.theme_ids import DEFAULT_THEME_ID, VALID_THEME_IDS

# Token name -> hex/rgba value, translated from the alpine-snow block of
# docs/design/colors.css.
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
    "accent_line": "#b9aee2",
    "hover": "rgba(40,28,72,0.06)",
    "hover_strong": "rgba(40,28,72,0.10)",
    "pressed": "rgba(40,28,72,0.14)",
    "highlight": "#f0d670",
    "paper": "#ffffff",
    "shadow": "rgba(40,28,72,0.18)",
}

# Light, low visual burden — translated from the meadow-lupine block.
# bg / sunken are the theme's meadow-green chrome (per 2026-06-14 request): the
# background surfaces now share the green hue of the surface/border family
# instead of the original cool-lavender "alpine sky". The Lupine accent stays
# indigo (the theme's signature).
MEADOW_LUPINE: dict[str, str] = {
    "bg": "#e6ecdd",
    "surface": "#f5f7f2",
    "sunken": "#d9e1cc",
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
    "accent_line": "#bcaee4",
    "hover": "rgba(40,28,72,0.06)",
    "hover_strong": "rgba(40,28,72,0.10)",
    "pressed": "rgba(40,28,72,0.14)",
    "highlight": "#f0d670",
    "paper": "#ffffff",
    "shadow": "rgba(40,28,72,0.18)",
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
    "accent_line": "rgba(155,143,192,0.32)",
    "hover": "rgba(255,255,255,0.04)",
    "hover_strong": "rgba(255,255,255,0.07)",
    "pressed": "rgba(255,255,255,0.12)",
    "highlight": "#e6c62c",
    "paper": "#f1efe8",
    "shadow": "rgba(0,0,0,0.55)",
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
    "accent_line": "#8ec8e6",
    "hover": "rgba(3,105,161,0.06)",
    "hover_strong": "rgba(3,105,161,0.10)",
    "pressed": "rgba(3,105,161,0.14)",
    "highlight": "#67e8f9",
    "paper": "#ffffff",
    "shadow": "rgba(12,48,82,0.20)",
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

# Fail fast on drift: the registry's ids must match the canonical valid-id set
# that utils.preferences also validates against. Without this, adding a theme
# here but not to utils.theme_ids (or vice-versa) would surface as a late
# ValueError when a user selects the new theme.
if set(THEME_REGISTRY) != VALID_THEME_IDS:
    raise RuntimeError(
        "THEME_REGISTRY ids "
        f"{sorted(THEME_REGISTRY)} do not match utils.theme_ids.VALID_THEME_IDS "
        f"{sorted(VALID_THEME_IDS)}"
    )

_DEFAULT_THEME = DEFAULT_THEME_ID


def build_qss(theme_name: str = _DEFAULT_THEME) -> str:
    """Return the complete application QSS for the named theme.

    Unknown names fall back to the default (Alpine Snow) theme.

    The stylesheet is applied once at the ``QApplication`` level. Every rule is
    object-name-scoped where it could otherwise leak across tab widgets
    (``#ribbonTabs`` / ``#sidebarTabs`` / ``#documentTabBar``). Interactive
    surfaces carry explicit ``:hover`` / ``:pressed`` / ``:focus`` states because
    QSS cannot animate transitions — differentiation has to be static.
    """
    t = (THEME_REGISTRY.get(theme_name) or THEME_REGISTRY[_DEFAULT_THEME]).tokens
    return f"""
        QMainWindow {{ background: {t["bg"]}; }}

        /* Default foreground so dark themes do not keep the OS's dark text on
           dark chrome (QSS does not inherit the platform palette's text role). */
        QWidget {{ color: {t["fg"]}; }}
        QLabel, QGroupBox, QPushButton, QCheckBox, QRadioButton,
        QLineEdit, QComboBox, QListWidget, QToolButton {{ color: {t["fg"]}; }}

        /* Tooltips are top-level popups; theme them so they match the chrome. */
        QToolTip {{
            background: {t["elev"]};
            color: {t["fg"]};
            border: 1px solid {t["line_strong"]};
            padding: 5px 8px;
            border-radius: 6px;
        }}

        QGroupBox {{
            border: 1px solid {t["line"]};
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 4px;
            color: {t["fg_muted"]};
        }}

        /* Give buttons a themed surface; the global QWidget colour sets the
           label, so without this they keep the native light grey background
           (unreadable light-on-light text would appear under dark themes). */
        QPushButton {{
            border-radius: 6px;
            padding: 6px 14px;
            border: 1px solid {t["line"]};
            background: {t["elev"]};
            min-height: 16px;
        }}
        QPushButton:hover {{ background: {t["surface"]}; border-color: {t["line_strong"]}; }}
        QPushButton:pressed {{ background: {t["sunken"]}; }}
        QPushButton:focus {{ border: 1px solid {t["accent"]}; }}
        QPushButton:disabled {{ color: {t["fg_subtle"]}; border-color: {t["line_soft"]}; }}
        /* The default dialog button (OK / 確定) reads as the primary action. */
        QPushButton:default {{
            background: {t["accent"]};
            color: {t["accent_fg"]};
            border: 1px solid {t["accent"]};
        }}
        QPushButton:default:hover {{ background: {t["accent"]}; border-color: {t["accent_line"]}; }}
        QPushButton:default:disabled {{
            background: {t["sunken"]};
            color: {t["fg_subtle"]};
            border-color: {t["line_soft"]};
        }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
        QTextEdit, QPlainTextEdit {{
            border-radius: 6px;
            padding: 4px 8px;
            border: 1px solid {t["line"]};
            background: {t["elev"]};
            color: {t["fg"]};
            selection-background-color: {t["accent"]};
            selection-color: {t["accent_fg"]};
        }}
        QLineEdit:hover, QComboBox:hover, QSpinBox:hover,
        QDoubleSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {{
            border-color: {t["line_strong"]};
        }}
        /* Focus ring: recolour the existing 1px border to the accent so keyboard
           users get a visible indicator with no layout shift (no width change). */
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {t["accent"]}; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        /* Combo-box popup list (otherwise a native light list under dark themes). */
        QComboBox QAbstractItemView {{
            background: {t["elev"]};
            color: {t["fg"]};
            border: 1px solid {t["line"]};
            selection-background-color: {t["accent"]};
            selection-color: {t["accent_fg"]};
            outline: none;
        }}

        /* Check / radio indicators: native ones nearly vanish under dark themes.
           Checked = accent fill (no glyph asset needed). */
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid {t["line_strong"]};
            background: {t["elev"]};
        }}
        QCheckBox::indicator {{ border-radius: 4px; }}
        QRadioButton::indicator {{ border-radius: 9px; }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
            border-color: {t["accent"]};
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background: {t["accent"]};
            border-color: {t["accent"]};
        }}
        QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
            background: {t["sunken"]};
            border-color: {t["line_soft"]};
        }}

        /* Modal dialogs (print, export, OCR, watermark, …). Applying the QSS at
           the QApplication level reaches these automatically; the explicit rule
           keeps their surface themed even when shown before the main window. */
        QDialog {{ background: {t["bg"]}; color: {t["fg"]}; }}

        /* Context menus are top-level QMenus (not children of any styled widget),
           so they only pick up theme colours from an application-level stylesheet. */
        QMenu {{
            background: {t["elev"]};
            color: {t["fg"]};
            border: 1px solid {t["line"]};
            padding: 4px;
        }}
        QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {t["accent"]}; color: {t["accent_fg"]}; }}
        QMenu::separator {{ height: 1px; background: {t["line"]}; margin: 4px 8px; }}

        /* Disabled text must dim, not vanish, against the themed surface. */
        QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled,
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
        QDoubleSpinBox:disabled, QGroupBox:disabled {{ color: {t["fg_subtle"]}; }}

        /* Slim, themed scrollbars (the native ones clash with the chrome). */
        QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0px; }}
        QScrollBar::handle:vertical {{
            background: {t["line_strong"]};
            min-height: 28px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {t["fg_subtle"]}; }}
        QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0px; }}
        QScrollBar::handle:horizontal {{
            background: {t["line_strong"]};
            min-width: 28px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {t["fg_subtle"]}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        /* Splitter divider between the panels and the canvas. */
        QSplitter::handle {{ background: {t["line_soft"]}; }}
        QSplitter::handle:horizontal {{ width: 6px; }}
        QSplitter::handle:vertical {{ height: 6px; }}
        QSplitter::handle:hover {{ background: {t["accent_line"]}; }}

        /* Status bar (hosts the theme switcher) — keep its chrome themed so the
           permanent-widget chips stay legible under dark themes. */
        QStatusBar {{ background: {t["surface"]}; color: {t["fg"]}; border-top: 1px solid {t["line"]}; }}
        QStatusBar::item {{ border: none; }}

        /* Left / right side panels. */
        QWidget#leftPanel, QWidget#rightPanel {{ background: {t["surface"]}; }}
        QLabel#rightPanelTitle {{
            font-weight: 600;
            padding: 8px 10px;
            color: {t["fg"]};
            border-bottom: 1px solid {t["line"]};
        }}
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
        QTabWidget#sidebarTabs QTabBar::tab:hover {{
            background: {t["accent_soft"]};
            color: {t["fg"]};
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
            outline: none;
        }}
        QListWidget::item:hover {{ background: {t["hover"]}; }}
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
            padding: 5px 12px;
            margin-right: 2px;
            background: transparent;
            color: {t["fg_muted"]};
            border-radius: 4px;
        }}
        QTabWidget#ribbonTabs QTabBar::tab:hover {{
            background: {t["hover_strong"]};
            color: {t["fg"]};
        }}
        QTabWidget#ribbonTabs QTabBar::tab:selected {{
            background: {t["accent"]};
            color: {t["accent_fg"]};
            border-radius: 4px;
        }}

        /* Tool toolbars. */
        QToolBar {{ spacing: 4px; padding: 2px 0; border: none; }}
        QToolBar::separator {{ background: {t["line"]}; width: 1px; height: 1px; margin: 4px 4px; }}
        QToolButton {{
            min-width: 52px;
            padding: 4px 8px;
            border-radius: 6px;
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
        QTabBar#documentTabBar::tab:hover {{
            background: {t["surface"]};
            color: {t["fg"]};
        }}
        QTabBar#documentTabBar::tab:selected {{
            background: {t["elev"]};
            color: {t["fg"]};
            border-color: {t["line_strong"]};
        }}
        QToolButton#documentTabCloseButton {{
            min-width: 20px;
            max-width: 20px;
            min-height: 20px;
            max-height: 20px;
            padding: 0;
            margin: 0;
            border: none;
            border-radius: 4px;
            background: transparent;
            color: {t["fg_muted"]};
            font-size: 16px;
            font-weight: 600;
        }}
        QToolButton#documentTabCloseButton[active="true"] {{
            color: {t["fg"]};
        }}
        QToolButton#documentTabCloseButton:hover {{
            background: {t["pressed"]};
            color: {t["fg"]};
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

    def _parse_qcolor(value: str) -> QColor:
        """Parse a token value (``#hex`` or ``rgba(r,g,b,a)``) into a QColor.

        QColor's string constructor accepts hex/named colours but not the
        ``rgba(...)`` float-alpha form used by the interaction/shadow tokens, so
        that form is parsed explicitly.
        """
        text = value.strip()
        if text.startswith("rgba(") and text.endswith(")"):
            parts = [p.strip() for p in text[5:-1].split(",")]
            if len(parts) == 4:
                r, g, b = (int(float(parts[i])) for i in range(3))
                alpha = int(round(float(parts[3]) * 255))
                return QColor(r, g, b, alpha)
        color = QColor(text)
        return color if color.isValid() else QColor(0, 0, 0, 90)

    def shadow_color(theme_name: str = _DEFAULT_THEME) -> QColor:
        """Return the drop-shadow :class:`QColor` for ``theme_name``.

        Used by :class:`QGraphicsDropShadowEffect` to elevate the top chrome.
        The hue is the ``shadow`` brand token (from the ``--shadow-*`` colours in
        ``docs/design/colors.css``). Unknown names fall back to the default.
        """
        meta = THEME_REGISTRY.get(theme_name) or THEME_REGISTRY[_DEFAULT_THEME]
        return _parse_qcolor(meta.tokens["shadow"])

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
