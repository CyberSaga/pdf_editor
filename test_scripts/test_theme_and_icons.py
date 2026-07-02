"""Tests for the theme registry, QSS builder, icon loader, and theme switcher.

Token / registry / build_qss / icon-map tests need no QApplication. Widget and
PDFView tests use the session-scoped ``qapp`` fixture from conftest.py.

Each test maps to a concrete finding from the prior review history (noted inline).
"""

from __future__ import annotations

import pytest

from utils.preferences import UserPreferences
from utils.theme_ids import VALID_THEME_IDS
from view.theme import (
    ALPINE_SNOW,
    GLIMMERING_GLACIER,
    INK_PORCELAIN,
    MEADOW_LUPINE,
    THEME_REGISTRY,
    ThemeMeta,
    build_qss,
)

# The 20 token keys every palette must define for build_qss().
# accent_line / hover_strong / shadow are brand tokens lifted verbatim from
# docs/design/colors.css (they were documented there but never plumbed
# into the QSS); they back focus rings, tab hover, and chrome elevation.
_TOKEN_KEYS = {
    "bg", "surface", "sunken", "elev",
    "line", "line_strong", "line_soft",
    "fg", "fg_muted", "fg_subtle",
    "accent", "accent_fg", "accent_soft", "accent_line",
    "hover", "hover_strong", "pressed", "highlight", "paper",
    "shadow",
}

_EXPECTED_IDS = {"alpine-snow", "meadow-lupine", "ink-porcelain", "glimmering-glacier"}

_ALL_THEMES = ["alpine-snow", "meadow-lupine", "ink-porcelain", "glimmering-glacier"]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# --------------------------------------------------------------------------- #
# Token dicts / registry
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "tokens", [ALPINE_SNOW, MEADOW_LUPINE, INK_PORCELAIN, GLIMMERING_GLACIER]
)
def test_token_dicts_all_keys(tokens):
    # All 17 required keys present in each of the 4 theme dicts.
    assert set(tokens) == _TOKEN_KEYS


def test_token_accent_values():
    # Spot-check accents so a wrong/duplicated palette is caught.
    assert ALPINE_SNOW["accent"] == "#4338ca"
    assert GLIMMERING_GLACIER["accent"] == "#0369a1"
    assert INK_PORCELAIN["accent"] == "#9b8fc0"


def test_registry_ids_exact():
    # finding: wrong themes in registry.
    assert set(THEME_REGISTRY.keys()) == _EXPECTED_IDS


def test_registry_matches_canonical_valid_ids():
    # finding #2: the registry and the preference validator must share one
    # source of truth (utils.theme_ids) so they can never drift. view.theme
    # raises at import if this is violated; assert it here too.
    assert set(THEME_REGISTRY.keys()) == set(VALID_THEME_IDS)


def test_swatch_is_bg_color():
    # finding: nine squares per mode — the chip swatch is the single bg colour.
    for meta in THEME_REGISTRY.values():
        assert isinstance(meta, ThemeMeta)
        assert meta.swatch == meta.tokens["bg"]


def test_registry_meta_id_matches_key():
    for theme_id, meta in THEME_REGISTRY.items():
        assert meta.id == theme_id


# --------------------------------------------------------------------------- #
# build_qss
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_build_qss_all_themes_contain_colors(theme_id):
    qss = build_qss(theme_id)
    tokens = THEME_REGISTRY[theme_id].tokens
    assert tokens["bg"] in qss
    assert tokens["accent"] in qss
    assert tokens["fg"] in qss


def test_build_qss_unknown_falls_back_to_alpine_snow():
    # finding: unknown name handling.
    assert build_qss("unknown") == build_qss("alpine-snow")


def test_build_qss_default_is_alpine_snow():
    assert build_qss() == build_qss("alpine-snow")


def test_ribbon_rules_are_scoped():
    # finding: P2 ribbon QSS leaked onto the sidebar — ribbon rules must be
    # scoped to #ribbonTabs, never a bare unscoped QTabWidget::pane / QTabBar::tab.
    qss = build_qss()
    assert "QTabWidget#ribbonTabs" in qss
    for line in qss.splitlines():
        stripped = line.strip()
        if stripped.startswith("QTabWidget::pane") or stripped.startswith("QTabBar::tab"):
            pytest.fail(f"unscoped tab rule leaks to all tab widgets: {stripped!r}")


def test_sidebar_rules_present():
    # finding: sidebar uncoordinated.
    assert "QTabWidget#sidebarTabs" in build_qss()


def test_document_tabbar_rules_present():
    # finding: document tabs stayed light.
    assert "QTabBar#documentTabBar" in build_qss()


def test_panel_rules_present():
    # finding: sidebar / panels uncoordinated.
    qss = build_qss()
    assert "QWidget#rightPanel" in qss
    assert "QWidget#leftPanel" in qss


def test_dark_theme_has_foreground():
    # finding: dark theme had no text colours.
    assert "color: #e8e7eb" in build_qss("ink-porcelain")


@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_all_themes_pair_bg_and_fg(theme_id):
    # finding: global fg without paired bg — every theme must emit both a
    # background and a colour rule for QWidget-family chrome.
    qss = build_qss(theme_id)
    assert "background:" in qss
    assert "color:" in qss


@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_dialog_themed(theme_id):
    # finding: dialogs stayed native / light.
    qss = build_qss(theme_id)
    dialog_rule = qss.split("QDialog {")[1].split("}")[0]
    assert "background:" in dialog_rule


@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_native_controls_themed(theme_id):
    # finding: QPushButton / QStatusBar unreadable in dark.
    qss = build_qss(theme_id)
    tokens = THEME_REGISTRY[theme_id].tokens
    push_button_rule = qss.split("QPushButton {")[1].split("}")[0]
    assert f"background: {tokens['elev']}" in push_button_rule
    status_bar_rule = qss.split("QStatusBar {")[1].split("}")[0]
    assert f"background: {tokens['surface']}" in status_bar_rule


def test_qmenu_rules_present():
    # finding: parentless context menus unthemed.
    assert "QMenu" in build_qss()


# --------------------------------------------------------------------------- #
# Fable-5 refactor: new brand tokens + modern interactive QSS
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_new_brand_tokens_present(theme_id):
    # accent_line / hover_strong / shadow must be defined for every theme so
    # focus rings, tab hover, and elevation render under all four palettes.
    tokens = THEME_REGISTRY[theme_id].tokens
    assert tokens["accent_line"]
    assert tokens["hover_strong"]
    assert tokens["shadow"]


def test_meadow_bg_matches_meadow_green_hue():
    # User request (2026-06-14): Meadow Lupine's background surfaces must share
    # the theme's meadow-green hue, not the cool lavender "alpine sky" they
    # shipped with. The bg (chrome) and sunken (canvas well) must read green
    # (green channel dominant), and bg must differ from Alpine's lavender chrome.
    for key in ("bg", "sunken"):
        r, g, b = _hex_to_rgb(MEADOW_LUPINE[key])
        assert g >= r and g > b, (
            f"meadow {key} should be green-dominant, got {MEADOW_LUPINE[key]}"
        )
    assert MEADOW_LUPINE["bg"] != ALPINE_SNOW["bg"]
    # The Lupine accent stays purple — only the background hue changed.
    assert MEADOW_LUPINE["accent"] == "#4338ca"


def test_accent_line_values_from_colors_css():
    # Lifted verbatim from --color-accent-line in docs/design/colors.css
    # (palette preservation: no invented hues).
    assert ALPINE_SNOW["accent_line"] == "#b9aee2"
    assert GLIMMERING_GLACIER["accent_line"] == "#8ec8e6"


@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_focus_states_present(theme_id):
    # finding (a11y, Critical): keyboard users need a visible focus indicator.
    qss = build_qss(theme_id)
    assert ":focus" in qss
    tokens = THEME_REGISTRY[theme_id].tokens
    # The focus ring recolours the border to the accent (color-only → no shift).
    assert f"border: 1px solid {tokens['accent']}" in qss


@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_scrollbar_rules_present(theme_id):
    qss = build_qss(theme_id)
    assert "QScrollBar:vertical" in qss
    assert "QScrollBar:horizontal" in qss
    assert "QScrollBar::handle" in qss


def test_splitter_handle_themed():
    assert "QSplitter::handle" in build_qss()


def test_tooltip_themed():
    qss = build_qss()
    tooltip_rule = qss.split("QToolTip {")[1].split("}")[0]
    assert "background:" in tooltip_rule
    assert "border" in tooltip_rule


def test_tab_hover_states_present_and_scoped():
    # Every tab family gains a :hover affordance, and it must stay scoped to its
    # object name (the unscoped-leak guard in test_ribbon_rules_are_scoped also
    # covers this, but assert the positive case here too).
    qss = build_qss()
    assert "QTabWidget#ribbonTabs QTabBar::tab:hover" in qss
    assert "QTabWidget#sidebarTabs QTabBar::tab:hover" in qss
    assert "QTabBar#documentTabBar::tab:hover" in qss


def test_checkbox_indicator_themed():
    assert "QCheckBox::indicator" in build_qss()
    assert "QRadioButton::indicator" in build_qss()


def test_primary_default_button_uses_accent():
    # The default dialog button (OK/確定) reads as primary via the accent.
    qss = build_qss()
    default_rule = qss.split("QPushButton:default {")[1].split("}")[0]
    tokens = THEME_REGISTRY["alpine-snow"].tokens
    assert tokens["accent"] in default_rule


def test_native_controls_still_themed_after_refactor():
    # Regression guard: the refactor must not drop the elev/surface anchors that
    # test_native_controls_themed relies on (re-asserted independently here).
    for theme_id in _ALL_THEMES:
        qss = build_qss(theme_id)
        tokens = THEME_REGISTRY[theme_id].tokens
        assert f"background: {tokens['elev']}" in qss.split("QPushButton {")[1]
        assert f"background: {tokens['surface']}" in qss.split("QStatusBar {")[1]


@pytest.mark.parametrize("theme_id", _ALL_THEMES)
def test_shadow_color_helper_returns_qcolor(qapp, theme_id):
    from PySide6.QtGui import QColor

    from view.theme import shadow_color

    color = shadow_color(theme_id)
    assert isinstance(color, QColor)
    assert color.isValid()
    # A drop shadow must have some opacity to be visible.
    assert color.alpha() > 0


def test_shadow_color_unknown_falls_back(qapp):
    from view.theme import shadow_color

    assert shadow_color("__nope__").isValid()


def test_right_panel_title_themed_in_qss(qapp):
    # The 屬性 section header is themed via #rightPanelTitle (no inline colour
    # stylesheet on the label).
    from view.pdf_view import PDFView

    assert "#rightPanelTitle" in build_qss()
    view = PDFView()
    try:
        assert view._right_panel_title.styleSheet() == ""
        assert view._right_panel_title.objectName() == "rightPanelTitle"
    finally:
        view.deleteLater()


def test_combobox_dropdown_themed():
    # finding: combo dropdowns stayed light.
    assert "QComboBox QAbstractItemView" in build_qss()


def test_dark_dialog_renders_dark(qapp):
    # Concrete contrast check: a QDialog with the dark theme's QSS paints a dark
    # surface (not the native light background) behind its child widgets.
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

    dlg = QDialog()
    dlg.setStyleSheet(build_qss("ink-porcelain"))
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("列印設定"))
    dlg.resize(160, 80)
    dlg.ensurePolished()
    image = QImage(dlg.size(), QImage.Format_ARGB32)
    dlg.render(image)
    corner = image.pixelColor(3, 3)  # dialog surface, away from text
    try:
        assert corner.red() < 90 and corner.green() < 90 and corner.blue() < 90
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# Icon loader
# --------------------------------------------------------------------------- #
def test_action_icon_map_covers_core_actions():
    from view.icons import ACTION_ICON_MAP, ICON_DIR

    # Exact count: an exact assertion still catches a *dropped* icon. It went
    # stale (32 -> 33) when the Fable-5 ribbon commit grew the map and left the
    # literal behind; pair the count with the membership invariant below so a
    # silent additive/subtractive drift cannot pass unnoticed.
    assert len(ACTION_ICON_MAP) == 33
    for label in ("開啟", "瀏覽模式", "拉正頁面", "OCR（文字辨識）"):
        assert label in ACTION_ICON_MAP
        assert ACTION_ICON_MAP[label].endswith(".png")
    # Membership invariant: every mapped label resolves to a non-empty PNG on
    # disk, so a renamed or removed asset fails here even when the count holds.
    for label, filename in ACTION_ICON_MAP.items():
        assert filename.endswith(".png"), f"{label!r} maps to non-PNG {filename!r}"
        asset = ICON_DIR / filename
        assert asset.is_file(), f"{label!r} -> {filename!r} missing on disk"
        assert asset.stat().st_size > 0, f"{label!r} -> {filename!r} is empty"


def test_load_icon_unknown_label_returns_null(qapp):
    from view.icons import load_icon

    assert load_icon("__no_such_action__").isNull()


def test_load_icon_known_label_returns_icon(qapp):
    from view.icons import load_icon

    icon = load_icon("開啟")
    assert not icon.isNull()


def test_load_icon_straighten_page(qapp):
    # The 拉正頁面 toolbar action must resolve to its committed PNG so the button
    # renders icon-beside-text rather than text-only.
    from view.icons import load_icon

    icon = load_icon("拉正頁面")
    assert not icon.isNull()


# --------------------------------------------------------------------------- #
# Theme switcher widget (single square per chip)
# --------------------------------------------------------------------------- #
def test_chip_count_matches_registry(qapp):
    from view.theme import ThemeSwitcherWidget

    switcher = ThemeSwitcherWidget(active_theme="alpine-snow")
    assert len(switcher._chips) == len(THEME_REGISTRY)


def test_chip_single_square(qapp):
    # finding: nine squares per mode — a chip fits exactly one square + padding.
    from view.theme import _ThemeChip

    chip = _ThemeChip(THEME_REGISTRY["meadow-lupine"])
    assert chip.width() == _ThemeChip._PAD * 2 + _ThemeChip._SIZE
    assert chip.height() == _ThemeChip._PAD * 2 + _ThemeChip._SIZE


def test_active_chip_on_init(qapp):
    from view.theme import ThemeSwitcherWidget

    switcher = ThemeSwitcherWidget(active_theme="ink-porcelain")
    assert switcher._chips["ink-porcelain"]._active is True
    for tid, chip in switcher._chips.items():
        if tid != "ink-porcelain":
            assert chip._active is False


def test_theme_selected_signal_emits(qapp):
    from view.theme import ThemeSwitcherWidget

    switcher = ThemeSwitcherWidget(active_theme="alpine-snow")
    received: list[str] = []
    switcher.theme_selected.connect(received.append)
    switcher._chips["glimmering-glacier"].clicked.emit()
    assert received == ["glimmering-glacier"]


def test_set_active_theme_updates_chips(qapp):
    from view.theme import ThemeSwitcherWidget

    switcher = ThemeSwitcherWidget(active_theme="alpine-snow")
    switcher.set_active_theme("ink-porcelain")
    assert switcher._chips["ink-porcelain"]._active is True
    for tid, chip in switcher._chips.items():
        if tid != "ink-porcelain":
            assert chip._active is False


# --------------------------------------------------------------------------- #
# PDFView startup guard (application-level QSS, applied by the composition root)
# --------------------------------------------------------------------------- #
class _FakeStore:
    def __init__(self, initial: dict | None = None) -> None:
        self._data: dict[str, object] = dict(initial or {})

    def value(self, key: str, default=None, type=None):  # noqa: A002 - QSettings API
        return self._data.get(key, default)

    def setValue(self, key: str, value) -> None:
        self._data[key] = value


def test_apply_initial_theme_sets_app_stylesheet(qapp):
    # The saved theme's QSS is applied at the QApplication level (so context
    # menus and dialogs inherit it) — but by apply_initial_theme(), not by the
    # constructor.
    from view.pdf_view import PDFView

    view = PDFView()
    try:
        view.apply_initial_theme()
        assert qapp.styleSheet() == build_qss(view._initial_theme)
        assert "#F8FAFC" not in qapp.styleSheet()  # never the old hardcoded palette
    finally:
        view.deleteLater()


def test_construction_does_not_mutate_global_stylesheet(qapp):
    # finding #3: building a view must not mutate the process-global app
    # stylesheet as a side effect (that leaked UI state across the shared-qapp
    # suite). Only an explicit apply_* call may touch it.
    from view.pdf_view import PDFView

    sentinel = "/* sentinel-theme-marker */"
    qapp.setStyleSheet(sentinel)
    view = PDFView()
    try:
        assert qapp.styleSheet() == sentinel
    finally:
        view.deleteLater()
        qapp.setStyleSheet("")


def test_switcher_applies_theme_without_a_controller(qapp):
    # finding #1: the switcher must work on the empty shell, before any
    # controller is activated — the view applies the theme itself.
    from view.pdf_view import PDFView

    view = PDFView()
    view._prefs = UserPreferences(store=_FakeStore())  # avoid touching real QSettings
    try:
        # Simulate a switcher click: the switcher's signal is wired to apply_theme.
        view._theme_switcher.theme_selected.emit("ink-porcelain")
        assert qapp.styleSheet() == build_qss("ink-porcelain")
        assert view._theme_switcher._chips["ink-porcelain"]._active is True
        assert view._prefs.get_theme() == "ink-porcelain"  # persisted by the view
    finally:
        view.deleteLater()
        qapp.setStyleSheet("")


def test_graphics_view_no_inline_stylesheet(qapp):
    # finding: inline stylesheet blocked the theme on the canvas well.
    from view.pdf_view import PDFView

    view = PDFView()
    try:
        assert view.graphics_view.styleSheet() == ""
    finally:
        view.deleteLater()


def test_document_tabbar_no_inline_stylesheet(qapp):
    # finding: inline stylesheet blocked the theme on the document tab bar.
    from view.pdf_view import PDFView

    view = PDFView()
    try:
        assert view.document_tab_bar.styleSheet() == ""
    finally:
        view.deleteLater()


def test_toolbar_container_height(qapp):
    from view.pdf_view import PDFView

    view = PDFView()
    try:
        view.resize(800, 600)
        view.show()
        qapp.processEvents()
        view._update_toolbar_style()
        assert view._toolbar_container.maximumHeight() == 68
    finally:
        view.close()
        view.deleteLater()


def test_toolbar_button_style(qapp):
    from PySide6.QtCore import Qt

    from view.pdf_view import PDFView

    view = PDFView()
    try:
        view.resize(800, 600)
        view.show()
        qapp.processEvents()
        view._update_toolbar_style()
        toolbars = view._collect_toolbars()
        assert len(toolbars) == 5
        for toolbar in toolbars:
            assert toolbar.toolButtonStyle() == Qt.ToolButtonIconOnly
    finally:
        view.close()
        view.deleteLater()


def test_toolbar_icon_size(qapp):
    from PySide6.QtCore import QSize

    from view.pdf_view import PDFView

    view = PDFView()
    try:
        view.resize(800, 600)
        view.show()
        qapp.processEvents()
        view._update_toolbar_style()
        for toolbar in view._collect_toolbars():
            assert toolbar.iconSize() == QSize(28, 28)
    finally:
        view.close()
        view.deleteLater()


def test_toolbar_wide_text_under_icon(qapp):
    from PySide6.QtCore import QSize, Qt

    from view.pdf_view import PDFView

    view = PDFView()
    try:
        view.resize(1920, 1080)
        view.show()
        qapp.processEvents()
        view._update_toolbar_style()
        assert view._toolbar_container.maximumHeight() == 100
        for toolbar in view._collect_toolbars():
            assert toolbar.toolButtonStyle() == Qt.ToolButtonTextUnderIcon
            assert toolbar.iconSize() == QSize(32, 32)
    finally:
        view.close()
        view.deleteLater()


def test_toolbar_narrow_icon_only(qapp):
    from PySide6.QtCore import QSize, Qt

    from view.pdf_view import PDFView

    view = PDFView()
    try:
        view.resize(800, 600)
        view.show()
        qapp.processEvents()
        view._update_toolbar_style()
        assert view._toolbar_container.maximumHeight() == 68
        for toolbar in view._collect_toolbars():
            assert toolbar.toolButtonStyle() == Qt.ToolButtonIconOnly
            assert toolbar.iconSize() == QSize(28, 28)
    finally:
        view.close()
        view.deleteLater()


def test_straighten_action_has_icon(qapp):
    # End-to-end wiring: the 拉正頁面 toolbar button must end up with a non-null
    # icon. Guards against the action label and ACTION_ICON_MAP key drifting apart.
    from view.pdf_view import PDFView

    view = PDFView()
    try:
        actions = [
            a
            for tb in view._collect_toolbars()
            for a in tb.actions()
            if a.text() == "拉正頁面"
        ]
        assert actions, "no 拉正頁面 toolbar action found"
        assert not actions[0].icon().isNull()
    finally:
        view.deleteLater()


def test_straighten_action_warns_about_size_growth(qapp):
    from view.pdf_view import PDFView

    view = PDFView()
    try:
        actions = [
            a
            for tb in view._collect_toolbars()
            for a in tb.actions()
            if a.text() == "拉正頁面"
        ]
        assert actions, "no 拉正頁面 toolbar action found"
        tooltip = actions[0].toolTip()
        assert "檔案大小" in tooltip
        assert "影像" in tooltip
        assert "最佳化" in tooltip
        assert "極致壓縮" in tooltip
    finally:
        view.deleteLater()


# ---------------------------------------------------------------------------
# Packaging guard: runtime icon assets must exist on disk
# ---------------------------------------------------------------------------


def test_app_icon_exists():
    from view.icons import APP_ICON_PATH

    assert APP_ICON_PATH.is_file(), f"app icon missing: {APP_ICON_PATH}"


def test_all_mapped_toolbar_icons_exist():
    from view.icons import ACTION_ICON_MAP, ICON_DIR

    assert ICON_DIR.is_dir(), f"icon directory missing: {ICON_DIR}"
    missing = [
        name
        for name in ACTION_ICON_MAP.values()
        if not (ICON_DIR / name).is_file()
    ]
    assert not missing, f"missing icon files: {missing}"
