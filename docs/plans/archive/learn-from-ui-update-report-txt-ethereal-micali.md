# Plan: Rebuild UI Theme System (Clean Restart from 24c9dba)

## Context

The previous implementation of the three-theme system went through multiple review/fix cycles before getting right. This plan restarts from commit `24c9dba` ("Add appearance design and function icons") and implements the full feature correctly from the start, incorporating every lesson captured in `ui-update-report.txt`.

**Why restart:** The accumulated patches left the codebase hard to read, with several findings still open (parentless context menus, signal definition missing, etc.). A clean implementation from the known-good base is cleaner than more patches.

---

## Key Decisions (from lessons learned)

| Lesson | Decision |
|--------|----------|
| Themes must match colors.css | Registry: exactly `alpine-snow`, `meadow-lupine`, `ink-porcelain` |
| Nine squares per row (wrong) | One square per chip (bg color), accent ring = active state |
| Startup overwrote QSS | Apply theme **once** on startup; remove all trailing hardcoded `setStyleSheet` blocks |
| Context menus are top-level QMenu → miss widget-level QSS | Apply stylesheet at **QApplication level**, not PDFView level |
| Dialog theming broken | QApplication-level QSS reaches all dialogs automatically |
| Canvas / doc tabs kept light inline styles | Remove `graphics_view.setStyleSheet(...)` and `document_tab_bar.setStyleSheet(...)` entirely |
| Ribbon QSS leaked onto sidebar | Scope all ribbon rules to `QTabWidget#ribbonTabs` |
| Text colors missing in dark theme | Add `color: {fg}` for every widget that gets a background change |
| 60px toolbar clipped text-beside-icon | Raise `_toolbar_container` to **92px**; use `ToolButtonTextBesideIcon` + 24px icons |

---

## Token Values (source of truth: `appearance_design/colors.css` + plan)

Four themes total. The first three are already defined in `colors.css`; Glimmering Glacier is new and will be appended to that file.

### ALPINE_SNOW
```python
{"bg": "#f0ecfa", "surface": "#fafafc", "sunken": "#e2dcf2", "elev": "#ffffff",
 "line": "#ddd6ec", "line_strong": "#b7add0", "line_soft": "#ebe5f6",
 "fg": "#0f172a", "fg_muted": "#3a4358", "fg_subtle": "#6b7280",
 "accent": "#4338ca", "accent_fg": "#ffffff", "accent_soft": "#e0dbf3",
 "hover": "rgba(40,28,72,0.06)", "pressed": "rgba(40,28,72,0.14)",
 "highlight": "#f0d670", "paper": "#ffffff"}
```

### MEADOW_LUPINE
```python
{"bg": "#eae6f3", "surface": "#f5f7f2", "sunken": "#dbd6e9", "elev": "#fdfdf8",
 "line": "#d4d7cf", "line_strong": "#a4ab9d", "line_soft": "#e2e5dd",
 "fg": "#0f172a", "fg_muted": "#3a4358", "fg_subtle": "#697282",
 "accent": "#4338ca", "accent_fg": "#ffffff", "accent_soft": "#e2dcf3",
 "hover": "rgba(40,28,72,0.06)", "pressed": "rgba(40,28,72,0.14)",
 "highlight": "#f0d670", "paper": "#ffffff"}
```

### INK_PORCELAIN
```python
{"bg": "#18171c", "surface": "#232228", "sunken": "#101015", "elev": "#2a2931",
 "line": "#2b2a33", "line_strong": "#403e49", "line_soft": "#211f26",
 "fg": "#e8e7eb", "fg_muted": "#a39fad", "fg_subtle": "#6f6c78",
 "accent": "#9b8fc0", "accent_fg": "#0d0c12", "accent_soft": "rgba(155,143,192,0.13)",
 "hover": "rgba(255,255,255,0.04)", "pressed": "rgba(255,255,255,0.12)",
 "highlight": "#e6c62c", "paper": "#f1efe8"}
```

### GLIMMERING_GLACIER (new — light, icy cerulean; append to colors.css as block 03)
```python
{"bg": "#e8f4fb", "surface": "#f4fafd", "sunken": "#d6ecf5", "elev": "#ffffff",
 "line": "#b8d9ee", "line_strong": "#7db9d8", "line_soft": "#daeef7",
 "fg": "#0c1a2e", "fg_muted": "#2d4a64", "fg_subtle": "#5d7a8e",
 "accent": "#0369a1", "accent_fg": "#ffffff", "accent_soft": "#cce6f7",
 "hover": "rgba(3,105,161,0.06)", "pressed": "rgba(3,105,161,0.14)",
 "highlight": "#67e8f9", "paper": "#ffffff"}
```

---

## Files to Create / Modify

### 0. `appearance_design/colors.css` (append)
Append a complete block for Glimmering Glacier (`data-theme="glimmering-glacier"`) in the same format as the existing three blocks, using the token values above. Include all `--color-*`, `--shadow-*`, and `--swatch-*` custom properties. Mark it as block `03`.

### 1. `view/icons.py` (create)
- `ICON_DIR`: path to `appearance_design/function_icons/`
- `ACTION_ICON_MAP`: dict of 31 Traditional-Chinese action labels → PNG filenames
- `load_icon(label, size=24)`: loads PNG, smooth-scales to `size`, returns `QIcon` (null on missing)
- Wrap Qt imports in `try/except ImportError` for headless test compatibility

### 2. `view/theme.py` (create)
```
ALPINE_SNOW, MEADOW_LUPINE, INK_PORCELAIN, GLIMMERING_GLACIER   # token dicts
ThemeMeta(id, label, tokens, swatch)         # frozen dataclass; swatch = tokens["bg"]
THEME_REGISTRY: dict[str, ThemeMeta]        # insertion order = display order
_DEFAULT_THEME = "alpine-snow"
build_qss(theme_name=_DEFAULT_THEME) -> str  # falls back to alpine-snow on unknown name
_ThemeChip(QFrame)                           # 16px square (bg color) + 2px accent ring when active
ThemeSwitcherWidget(QWidget)                 # row of chips, emits theme_selected = Signal(str)
```

**`build_qss` must cover** (rule → token mapping):
- `QWidget { color: fg }` — global foreground baseline
- `QMainWindow { background: bg }`, `QDialog { background: bg; color: fg }`
- `QGroupBox { border: 1px solid line; }`, `QGroupBox#colorProfileCard { border-top/bottom: line }`
- `QPushButton { background: elev; color: fg; border: 1px solid line }` + hover/pressed/disabled states
- `QStatusBar { background: surface; color: fg }` + `QStatusBar::item { border: none }`
- `QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit { background: elev; color: fg; border: 1px solid line }`
- `QComboBox QAbstractItemView { background: elev; color: fg }`
- `QMenu { background: elev; color: fg; border: 1px solid line }` + `QMenu::item:selected { background: accent; color: accent_fg }`
- `QListWidget { background: surface; color: fg }` + `::item:selected { background: accent; color: accent_fg }`
- `QToolButton { color: fg }` + hover/checked states
- `QGraphicsView { background: sunken; border: none }`
- `QWidget#dropHost[dragActive="true"] { background: accent_soft; border: 2px dashed accent }`
- **Scoped ribbon** — `QTabWidget#ribbonTabs::pane { ... }`, `QTabWidget#ribbonTabs QTabBar::tab { ... }`, `QTabWidget#ribbonTabs QTabBar::tab:selected { background: accent; color: accent_fg }`
- **Scoped document tab bar** — `QTabBar#documentTabBar { ... }`, `QTabBar#documentTabBar::tab { ... }`, `::tab:selected`
- **Scoped sidebar** — `QTabWidget#sidebarTabs { background: surface }`, `QTabWidget#sidebarTabs QTabBar::tab { ... }`, `::tab:selected { background: accent; color: accent_fg }`
- `QWidget#rightPanel, QWidget#leftPanel { background: surface }`
- Wrap Qt imports in `try/except ImportError`

### 3. `utils/preferences.py` (add to existing)
```python
_THEME_KEY = "ui/theme"
_THEME_DEFAULT = "alpine-snow"
# Must stay in sync with THEME_REGISTRY manually (no view import — layer rule)
_VALID_THEME_IDS = frozenset({"alpine-snow", "meadow-lupine", "ink-porcelain", "glimmering-glacier"})

def get_theme(self) -> str   # validates; falls back to _THEME_DEFAULT
def set_theme(self, name: str) -> None  # raises ValueError for unknown names
```

### 4. `view/pdf_view.py` (modify)

**Add imports:**
```python
from view.theme import build_qss, ThemeSwitcherWidget
from view.icons import load_icon
from utils.preferences import UserPreferences
```

**Add class-level signal** (after `shell_ready = Signal()`):
```python
sig_theme_selected = Signal(str)
```

**In `__init__` (after `super().__init__()` setup, before other UI):**
```python
self._prefs = UserPreferences()
self._initial_theme = self._prefs.get_theme()
QApplication.instance().setStyleSheet(build_qss(self._initial_theme))
```

**After status bar created:**
```python
self._theme_switcher = ThemeSwitcherWidget(active_theme=self._initial_theme, parent=self)
self.status_bar.addPermanentWidget(self._theme_switcher)
self._theme_switcher.theme_selected.connect(self._on_theme_selected)
```

**Remove these inline stylesheets** (replace with object names + global QSS):
- `self.setStyleSheet(...)` hardcoded block (~line 554)
- `self.graphics_view.setStyleSheet(...)` (~line 561)
- `self.document_tab_bar.setStyleSheet(...)` in `_build_document_tabs_bar()`
- `self._toolbar_container.setStyleSheet(...)` and its `setFixedHeight(60)` in `_build_toolbar_tabs()`
- `self.toolbar_tabs.setStyleSheet(...)` in `_build_toolbar_tabs()`
- `toolbar_style` string + each toolbar's `setStyleSheet(toolbar_style)` call
- `self.color_profile_card.setStyleSheet(...)` (replaced by `QGroupBox#colorProfileCard` rule in build_qss)

**Assign object names:**
```python
self.left_sidebar.setObjectName("sidebarTabs")      # QTabWidget (line 351)
self.left_sidebar_widget.setObjectName("leftPanel")  # QWidget (line 358)
self.right_sidebar.setObjectName("rightPanel")       # QWidget (line 373)
# colorProfileCard already set (line 382)
self.toolbar_tabs.setObjectName("ribbonTabs")        # QTabWidget (line 1000)
self.document_tab_bar.setObjectName("documentTabBar")  # QTabBar (line 866)
```

**Toolbar container height and button style** (in `_build_toolbar_tabs`):
```python
self._toolbar_container.setFixedHeight(92)   # was 60
# For each tb_*: Qt.ToolButtonTextBesideIcon + setIconSize(QSize(24, 24))
# Also call _apply_toolbar_icons(tb_*) after building each toolbar
```

**Add methods:**
```python
def _apply_toolbar_icons(self, toolbar: QToolBar) -> None:
    for action in toolbar.actions():
        icon = load_icon(action.text())
        if not icon.isNull():
            action.setIcon(icon)

def _configure_tool_toolbar(self, toolbar: QToolBar) -> None:
    toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    toolbar.setIconSize(QSize(24, 24))

def _on_theme_selected(self, theme_id: str) -> None:
    self.sig_theme_selected.emit(theme_id)

def update_theme_switcher(self, theme_id: str) -> None:
    self._theme_switcher.set_active_theme(theme_id)
```

### 5. `controller/pdf_controller.py` (add)

In `_connect_signals`:
```python
self.view.sig_theme_selected.connect(self.set_theme)
```

New slot:
```python
@Slot(str)
def set_theme(self, name: str) -> None:
    from utils.preferences import UserPreferences
    from view.theme import THEME_REGISTRY, build_qss
    if name not in THEME_REGISTRY:
        return
    UserPreferences().set_theme(name)
    QApplication.instance().setStyleSheet(build_qss(name))
    self.view.update_theme_switcher(name)
```

---

## Test Plan (TDD — RED before GREEN)

Each test maps to a specific finding from the review history.

### `test_scripts/test_theme_and_icons.py`

**Token / registry (no Qt needed):**
- `test_token_dicts_all_keys` — all 17 required keys present in each of the 4 theme dicts
- `test_token_accent_values` — spot-check: alpine-snow accent=`#4338ca`, glimmering-glacier accent=`#0369a1`, ink-porcelain accent=`#9b8fc0`
- `test_registry_ids_exact` — `set(THEME_REGISTRY.keys()) == {"alpine-snow","meadow-lupine","ink-porcelain","glimmering-glacier"}` (finding: wrong themes in registry)
- `test_swatch_is_bg_color` — `ThemeMeta.swatch == tokens["bg"]` for every entry (finding: nine squares per mode)

**build_qss (no Qt needed):**
- `test_build_qss_all_themes_contain_colors` — parametrize 4 themes; QSS contains that theme's `bg`, `accent`, and `fg` hex values
- `test_build_qss_unknown_falls_back_to_alpine_snow` — `build_qss("unknown")` equals `build_qss("alpine-snow")` (finding: unknown name handling)
- `test_ribbon_rules_are_scoped` — QSS contains `QTabWidget#ribbonTabs` and does NOT contain bare unscoped `QTabWidget::pane` (finding: P2 ribbon leaked onto sidebar)
- `test_sidebar_rules_present` — QSS contains `QTabWidget#sidebarTabs` (finding: sidebar uncoordinated)
- `test_document_tabbar_rules_present` — QSS contains `QTabBar#documentTabBar` (finding: document tabs stayed light)
- `test_panel_rules_present` — QSS contains `QWidget#rightPanel` and `QWidget#leftPanel` (finding: sidebar/panels uncoordinated)
- `test_dark_theme_has_foreground` — ink-porcelain QSS contains `color: #e8e7eb` (finding: dark theme had no text colors)
- `test_all_themes_pair_bg_and_fg` — parametrize 4 themes; QSS contains both `background:` and `color:` rules for `QWidget` (finding: global fg without paired bg)
- `test_dialog_themed` — QSS contains `QDialog` rule with `background` (finding: dialogs stayed native/light)
- `test_native_controls_themed` — QSS contains `QPushButton` background and `QStatusBar` background for all 4 themes (finding: QPushButton/QStatusBar unreadable in dark)
- `test_qmenu_rules_present` — QSS contains `QMenu` rule (finding: parentless context menus unthemed)
- `test_combobox_dropdown_themed` — QSS contains `QComboBox QAbstractItemView` (finding: combo dropdowns stayed light)
- `test_dark_dialog_renders_dark` — render a `QDialog` with ink-porcelain QSS applied; sample center pixel RGB all < 90 (concrete contrast check)

**Widget tests (need qapp):**
- `test_chip_count_matches_registry` — `ThemeSwitcherWidget` creates exactly `len(THEME_REGISTRY)` chips (finding: wrong chip count)
- `test_chip_single_square` — each `_ThemeChip` size fits one square (16+8px padding); NOT sized for three squares (finding: nine squares per mode)
- `test_active_chip_on_init` — chip for initial theme has `_active == True`; others `False` (finding: switcher state mismatch)
- `test_theme_selected_signal_emits` — simulated click on a non-active chip emits `theme_selected` with that theme's id (finding: signal flow)
- `test_set_active_theme_updates_chips` — after `set_active_theme("ink-porcelain")` only the ink-porcelain chip is active (finding: chip ring update)

**PDFView startup guard (needs qapp + headless PDFView):**
- `test_startup_applies_saved_theme` — `PDFView` startup uses `QApplication.instance().styleSheet()` equal to `build_qss(initial_theme)` (finding: startup overwrote saved theme)
- `test_no_hardcoded_light_palette_on_startup` — after startup `#F8FAFC` does NOT appear in app-level stylesheet (finding: hardcoded block overwrote theme)
- `test_graphics_view_no_inline_stylesheet` — `view.graphics_view.styleSheet()` is empty string after init (finding: inline stylesheet blocked theme)
- `test_document_tabbar_no_inline_stylesheet` — `view.document_tab_bar.styleSheet()` is empty string (finding: inline stylesheet blocked theme)
- `test_toolbar_container_height` — `view._toolbar_container.height()` or `maximumHeight()` is 92 (finding: P1 toolbar clipping)
- `test_toolbar_button_style` — all five ribbon toolbars have `toolButtonStyle() == Qt.ToolButtonTextBesideIcon` (finding: P1 text-beside-icon)
- `test_toolbar_icon_size` — each ribbon toolbar `iconSize() == QSize(24, 24)` (finding: icon wiring)

### `test_scripts/test_user_preferences.py`
- Default theme returns `"alpine-snow"`
- Round-trip `set_theme` / `get_theme` for all 4 theme IDs
- Shared store persists theme across instances
- `set_theme("unknown")` raises `ValueError`
- Corrupt stored value falls back to `"alpine-snow"` (finding: pref validation)

---

## Execution Order

1. `git reset --hard 24c9dba` on branch `update-ui`
2. Write all tests → confirm RED
3. Create `view/icons.py` → icon tests GREEN
4. Create `view/theme.py` (tokens + build_qss + registry) → token/QSS tests GREEN
5. Update `utils/preferences.py` → preferences tests GREEN
6. Add `_ThemeChip` + `ThemeSwitcherWidget` to `view/theme.py` → widget tests GREEN
7. Update `view/pdf_view.py` → remove inline styles, add object names, wire switcher, add signal
8. Update `controller/pdf_controller.py` → connect signal, add slot
9. Startup guard test → GREEN
10. `ruff check .` zero new violations; `pytest` full suite passes
11. Eyeball `python main.py` — four chips appear bottom-right; clicking each changes the whole app (toolbar, sidebar, dialogs, context menus); active chip gets accent ring

---

## Verification

```bash
ruff check view/theme.py view/icons.py view/pdf_view.py controller/pdf_controller.py utils/preferences.py
pytest test_scripts/test_theme_and_icons.py test_scripts/test_user_preferences.py -v
pytest  # full suite, confirm no regressions
python main.py  # eyeball: 4 chips in status bar; all themes switch cleanly including dialogs and context menus
```
