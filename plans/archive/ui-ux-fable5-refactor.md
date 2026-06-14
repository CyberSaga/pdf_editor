# Plan — UI/UX Fable-5 Refactor

**Branch:** `feat/ui-ux-fable5-refactor`
**Date started:** 2026-06-14

## Goal

Comprehensively raise the UI/UX polish of the app to a "Fable-5" quality bar —
visual hierarchy, spacing/alignment consistency, negative space, component
grouping, elevation (drop shadows), and modern interactive state feedback
(hover / active / focus) — **without** changing icons or the brand color palette.

## Hard constraints (from the request)

1. **Icon lockdown.** No change to icon assets, file paths, or icon variables.
   `view/icons.py`, `ACTION_ICON_MAP`, and `appearance_design/function_icons/`
   are untouched. Layout/size/padding/alignment of icon *containers* may change.
2. **Color palette preservation.** Keep the existing brand identity. Only wire up
   colors that already exist in `appearance_design/colors.css` (the documented
   brand tokens that were never plumbed into the QSS) and apply minor
   readability contrast tweaks. **No new hues.**

## Design grounding (ui-ux-pro-max + Fable-5 frontend-design)

- Visible focus rings are **Critical** for keyboard users (never remove an
  outline without a replacement).
- Hover feedback on every interactive surface; pressed/checked states distinct.
- Body/contrast ≥ 4.5:1.
- Micro-interaction feel via crisp, distinct states.
- **Qt reality:** QSS has *no* CSS transitions/animations. "Smooth feedback" =
  well-differentiated static `:hover` / `:pressed` / `:focus` states. True drop
  shadows require `QGraphicsDropShadowEffect` (QSS `box-shadow` does not exist).

## Affected modules

- `view/theme.py` — token dicts (+3 brand keys) and the `build_qss()` QSS body
  (the single source of truth, applied once at the QApplication level). Add a
  Qt-guarded `shadow_color(theme_id)` helper.
- `view/pdf_view.py` — (a) give the right-panel "屬性" title an object name and
  drop its inline stylesheet so it is themed via QSS; (b) apply a theme-aware
  `QGraphicsDropShadowEffect` to the top toolbar container, re-applied on theme
  switch via `apply_theme`.
- `test_scripts/test_theme_and_icons.py` — red-light tests for the new tokens
  and QSS features.
- Docs: `docs/ARCHITECTURE.md` (theming section), `docs/PITFALLS.md` (Qt QSS
  gotchas), `TODOS.md`.

## New brand tokens (all from colors.css — not new colors)

| token          | source in colors.css        | used for                         |
|----------------|-----------------------------|----------------------------------|
| `accent_line`  | `--color-accent-line`       | focus rings, splitter hover      |
| `hover_strong` | `--color-hover-strong`      | tab :hover overlay               |
| `shadow`       | `--shadow-*` base hue       | `QGraphicsDropShadowEffect` color|

## QSS additions (all scoped; no unscoped `QTabBar::tab` / `QTabWidget::pane`)

- Focus states: `:focus` border→accent on QLineEdit/QComboBox/QSpinBox/
  QTextEdit/QPushButton/QCheckBox/QRadioButton (color-only change → no layout shift).
- Hover states for ribbon / sidebar / document tabs (none today).
- `QScrollBar` (vertical + horizontal): thin, rounded, themed handle, no arrows.
- `QSplitter::handle`: themed 1px divider, hover → accent_line.
- `QToolTip`: themed surface + border.
- `QMenu::item` padding + `QMenu::separator`.
- `QListWidget::item` padding + `:hover`.
- `QCheckBox::indicator` / `QRadioButton::indicator`: themed (checked → accent).
- `QPushButton:default`: accent (primary affordance for dialog OK buttons).
- `QGroupBox::title` placement/color; `#rightPanelTitle` section header.
- `QToolBar::separator` themed.

## Invariants kept green (existing tests / contracts)

- Adaptive toolbar metrics untouched (68/28 icon-only ↔ 100/32 text-under-icon,
  5 toolbars). `_update_toolbar_style` / `_recompute_ribbon_text_min_width` /
  `_apply_toolbar_icons` not modified.
- `QPushButton` rule keeps `background: {elev}`; `QStatusBar` keeps
  `background: {surface}` (asserted by `test_native_controls_themed`).
- No unscoped tab rules (`test_ribbon_rules_are_scoped`).
- QSS applied once at QApplication level; no per-widget color stylesheets.
- `graphics_view` / `document_tab_bar` keep empty inline stylesheets.

## Step list

1. [x] Read architecture/pitfalls/todos, theme.py, icons.py, colors.css, view
   construction, test contract. Branch + baseline (56 theme tests green, ruff clean).
2. [x] Red-light: 28 tests added, shown failing.
3. [x] Implement theme.py (tokens + build_qss + shadow_color).
4. [x] Implement view.py (rightPanelTitle + chrome shadow).
5. [x] Green: 81 theme tests; ruff clean; QSS 0 parse-warnings × 4 themes.
6. [x] Adversarial review (5 lenses): icons/colors/architecture/qss-correctness
   clean; qt-runtime lens blocked by session limit (self-verified offscreen).
   Acted on the one low finding: shadow alpha pinned to documented --shadow-lg.
7. [x] Full suite: 1354 passed / 20 skipped / 0 failed.
8. [x] Docs updated (ARCHITECTURE §2.5 / PITFALLS / TODOS); plan archived.

## Outcome

Completed 2026-06-14. Both hard constraints upheld (icons + `appearance_design/`
byte-identical; all colours trace to colors.css / existing token dicts). Net:
3 source/test files + 3 docs changed. Key architectural decision recorded in
`docs/ARCHITECTURE.md` §2.5 (drop shadows are a `QGraphicsDropShadowEffect`, not
QSS; brand tokens `accent_line`/`hover_strong`/`shadow` now plumbed).

## Open questions / decisions

- Drop shadow on the toolbar container only (most reliable elevation cue; avoids
  interaction with the heavy QGraphicsView). Re-applied on theme switch.
- Focus rings skipped on QToolButton to avoid ribbon width churn (actions have
  shortcuts; rings go on form controls + push buttons).
- Functional inline stylesheets left intact (annotation color swatches, toast,
  fullscreen overlay X, watermark/ocr/audit dialog widgets) — feature logic.
