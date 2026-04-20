# UX7-macOS-Native-Menu-Bar-Implementation-Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the app a native-feeling menu bar on macOS that mirrors the existing toolbar actions and places About, Preferences, and Quit in the correct Apple-menu slots via Qt menu roles. Windows/Linux are unchanged — no QMenuBar is added there. Toolbar tabs remain on every platform, including macOS.

**Architecture:** Add a `_build_macos_menu_bar()` method to `PDFView` gated by `platform.system() == "darwin"`. It constructs a `QMenuBar` and adds menu entries that reuse the **same `QAction` instances** already created for the toolbar (no duplicates — one action can appear in both a toolbar and a menu, and triggering from either path fires the same signal). About / Preferences / Quit get `setMenuRole(...)` so Qt relocates them to the Apple menu. A minimal `AboutDialog` and a stub `PreferencesDialog` live under `view/dialogs/`.

**Tech Stack:** PySide6 `QMenuBar`, `QAction.setMenuRole`, `QKeySequence`, `platform.system()`, pytest.

**Scope guardrails (explicit non-goals):**
- No QMenuBar on Windows/Linux.
- No visual redesign; toolbar tabs stay on macOS too.
- No real Preferences content; the dialog is a placeholder so the Cmd+, role lands somewhere.
- No Touch Bar, no macOS services integration, no dock-menu customization.
- No i18n refactor — menu labels use the existing Traditional Chinese strings (plus English Apple-menu items which macOS auto-renders via role hints).
- No change to window-close / app-quit semantics beyond adding an explicit Quit action.

---

## Context

The app has no QMenuBar today — actions live on `QToolBar` tabs built in `view/pdf_view.py:833-959`. A macOS user therefore sees an empty system menu bar and no `Cmd+Q`, `Cmd+,`, or About affordance in the expected places. Qt offers a clean path: create a `QMenuBar`, reuse the existing `QAction` objects, and tag About/Preferences/Quit with menu roles so Qt moves them under the application menu at the OS level. Because we already have platform detection (`src/printing/dispatcher.py:19-26`) and because the toolbar actions are stored on `self._action_*`, we can mirror them into a menu without duplicating logic or diverging behavior.

Outcome: on macOS, keyboard users get `⌘O`, `⌘S`, `⌘Q`, `⌘,`; the Apple menu shows "About PDF Editor" and "Preferences…"; and closing the last window still quits (we do not enable the macOS-style "keep app alive" convention in this slice).

---

## Critical files

- Modify: `view/pdf_view.py` — add `_build_macos_menu_bar()`, call it from `__init__` under `platform.system() == "darwin"`.
- Create: `view/dialogs/about.py` — `AboutDialog(QDialog)` with app name, version (read from a central constant), short copyright, close button.
- Create: `view/dialogs/preferences.py` — `PreferencesDialog(QDialog)` with a single placeholder label "偏好設定（尚未實作）" and a close button. Keep the class name + signal surface future-ready (`sig_preferences_changed`) even if unused now.
- Create: `utils/platform_detect.py` (only if no shared helper exists; otherwise inline `platform.system() == "darwin"`). Provide `is_macos() -> bool` so tests can monkeypatch one place.
- Modify: `main.py` — no change expected unless the macOS-conventional `QApplication.setQuitOnLastWindowClosed(True)` default needs to be made explicit.
- Tests:
  - `test_scripts/test_macos_menu_bar.py` — monkeypatches `is_macos()` to True; asserts the menu bar structure, role assignments, and shortcut keys.
  - `test_scripts/test_macos_menu_bar.py` — second case: `is_macos()` False; assert `view.menuBar().actions()` is empty (no menu bar built).
  - `test_scripts/test_about_dialog.py`, `test_scripts/test_preferences_dialog.py` — construct/close smoke tests.

Reuse:
- Existing `QAction` fields in `PDFView`: `_action_open`, `_action_save`, `_action_save_as`, `_action_print`, `_action_optimize_copy`, `_action_undo`, `_action_redo`, `_action_browse`, `_action_objects`, `_action_fullscreen`, `_action_edit_text`, `_action_add_text`, `_action_rect`, `_action_highlight`, `_action_add_annotation`, plus any image/watermark actions found during implementation.
- The existing `_redo_mac_shortcut` (`view/pdf_view.py:893`) hints that macOS shortcut handling is already partly considered; verify no conflict when `QKeySequence.Redo` is set on the menu action.
- Platform-check pattern from `src/printing/dispatcher.py:21`.

---

## Tasks

### Task 1: Platform helper + About/Preferences dialog stubs

**Files:**
- Create: `utils/platform_detect.py` (or confirm existing module to extend).
- Create: `view/dialogs/about.py`, `view/dialogs/preferences.py`.
- Test: `test_scripts/test_about_dialog.py`, `test_scripts/test_preferences_dialog.py`.

**Step 1 — Red test:**
- `is_macos()` returns `True` when `platform.system()` is monkeypatched to `"Darwin"`, False otherwise.
- `AboutDialog(parent=None).windowTitle()` is non-empty; contains the app name.
- `AboutDialog` shows a version string matching the central `APP_VERSION` constant (expose one in `utils/platform_detect.py` or a new `utils/app_metadata.py`).
- `PreferencesDialog(parent=None)` constructs and has a "關閉" close button that emits `accepted`.

**Step 2:** Run → FAIL.

**Step 3:** Implement the helper + two minimal `QDialog` subclasses. `AboutDialog` uses `QLabel` + `QDialogButtonBox(Close)`. `PreferencesDialog` same shape with a placeholder label.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(view): add is_macos helper, About + Preferences dialog stubs`.

---

### Task 2: macOS menu bar builder (structure + roles)

**Files:**
- Modify: `view/pdf_view.py` — add `_build_macos_menu_bar(self)` and call site.
- Test: `test_scripts/test_macos_menu_bar.py`.

**Step 1 — Red test:** (monkeypatch `is_macos` → True before constructing `PDFView`)
- `view.menuBar()` has top-level menus titled `"檔案"`, `"編輯"`, `"檢視"`, `"視窗"`, `"說明"` (or whatever final set — test will enforce chosen strings).
- File menu contains actions whose `text()` matches `_action_open.text()`, `_action_save.text()`, `_action_save_as.text()`, `_action_print.text()`, plus a Quit action with `menuRole() == QAction.QuitRole` and shortcut `QKeySequence.Quit` (`⌘Q`).
- Edit menu contains `_action_undo` (`⌘Z`), `_action_redo` (`⇧⌘Z`), and the text/object actions.
- Help menu (or app menu) contains an About action with `menuRole() == QAction.AboutRole` and a Preferences action with `menuRole() == QAction.PreferencesRole` (shortcut `⌘,`).
- Every action placed in the menu is **the same object** as the corresponding toolbar action (`id(menu_action) == id(view._action_open)` for the ones that mirror toolbar actions).
- Triggering `view._action_open.trigger()` still fires the toolbar-connected slot (sanity check that reuse did not re-wire).

**Second red test case:** `is_macos` → False; `view.menuBar().actions()` is empty; `view._action_open` still exists and works.

**Step 2:** Run → FAIL.

**Step 3:** Implement `_build_macos_menu_bar`:
- Guard on `is_macos()` at the call site inside `__init__` (after toolbar tabs are built so actions exist).
- `mb = self.menuBar()`.
- File menu: `addAction(self._action_open)`, save, save-as, print, optimize-copy, `addSeparator()`, then a new `quit_action = QAction("結束", self); quit_action.setMenuRole(QAction.QuitRole); quit_action.setShortcut(QKeySequence.Quit); quit_action.triggered.connect(self.close)`.
- Edit menu: undo, redo, copy/paste (if actions exist), then text/annotate actions.
- View menu: browse, objects, fullscreen, plus any view actions found.
- Window menu: at minimum a "最小化" action with `QKeySequence("Ctrl+M")` (Qt translates to ⌘M) hooked to `self.showMinimized`.
- Help menu: About action (`AboutRole`), Preferences action (`PreferencesRole`, shortcut `QKeySequence.Preferences` which maps to ⌘,). About opens `AboutDialog(self).exec()`; Preferences opens `PreferencesDialog(self).exec()`.
- Qt will hoist the role-tagged actions into the Apple menu automatically — no extra code needed.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(view): macOS-only menu bar mirrors toolbar actions with menu roles`.

---

### Task 3: Keyboard-shortcut audit on macOS

**Files:**
- Modify: `view/pdf_view.py` — set standard sequences on the shared actions using `QKeySequence.StandardKey` constants *only if not already set*. Do not hardcode `"Ctrl+..."` strings for the macOS path since Qt remaps `Ctrl` to `Meta` (⌘) automatically; prefer `QKeySequence.Open`, `QKeySequence.Save`, `QKeySequence.SaveAs`, `QKeySequence.Print`, `QKeySequence.Undo`, `QKeySequence.Redo`, `QKeySequence.FullScreen`, `QKeySequence.Quit`, `QKeySequence.Preferences`.
- Test: extend `test_macos_menu_bar.py` — assert each action's primary shortcut matches the expected `QKeySequence.StandardKey` on macOS.

**Step 1 — Red test:** Assert `view._action_open.shortcut() == QKeySequence(QKeySequence.Open)`, same for save/save-as/print/undo/redo/fullscreen.

**Step 2:** Run → FAIL (current toolbar actions may use raw `"Ctrl+O"` strings or none).

**Step 3:** On macOS only, overwrite with `StandardKey` sequences. Do **not** mutate the non-macOS branch — keeps Windows/Linux shortcuts unchanged. Confirm the existing `_redo_mac_shortcut` override at `view/pdf_view.py:893` is no longer needed once `QKeySequence.Redo` is on `_action_redo`; remove it if redundant.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(view): macOS shortcuts use QKeySequence.StandardKey`.

---

### Task 4: Manual-verification harness

**Files:**
- Create: `tmp/manual_verify_ux7_macos.py` — a short script that constructs `PDFView` with `is_macos` forced True, prints the full menu tree (title → action text → shortcut → menuRole) to stdout, and exits. Useful for review on a Windows dev box without a real Mac.
- Not committed to main test suite; lives under `tmp/` like `tmp/manual_verify_f1_qtest.py`.

**Commit:** `chore: add ux7 menu-structure verification harness`.

---

### Task 5: Docs + tracker

**Files:**
- Modify: `docs/ARCHITECTURE.md` — add a paragraph under the View section describing the macOS-only menu-bar path and the action-reuse contract (one `QAction` appears in both toolbar and menu).
- Modify: `docs/PITFALLS.md` — entry if any gotcha surfaces during Task 2 (e.g. `QAction.setMenuRole` must be set *before* the action is added to a menu; `QKeySequence.Preferences` is platform-dependent).
- Modify: `TODOS.md`, `docs/plans/2026-04-10-backlog-checklist.md`, `docs/plans/2026-04-09-backlog-execution-order.md` — mark UX7 `done-implement`; note deferred items (real Preferences content, Window menu doc list, dock menu).

**Commit:** `docs: record UX7 macOS menu bar slice`.

---

## Verification (end-to-end)

1. `ruff check .` — zero new violations.
2. `pytest -q test_scripts/test_macos_menu_bar.py test_scripts/test_about_dialog.py test_scripts/test_preferences_dialog.py` — green.
3. Full regression: `pytest -q` — no regressions (especially the existing `view/pdf_view.py` GUI suite).
4. Windows sanity (on the dev box):
   - `python main.py` — no menu bar visible. Toolbar unchanged. All existing shortcuts still work.
   - `python tmp/manual_verify_ux7_macos.py` — printed menu tree matches expected structure.
5. macOS manual (when Mac is available):
   - Launch → system menu bar shows "檔案/編輯/檢視/視窗/說明".
   - Apple menu shows "About PDF Editor" and "Preferences…". Cmd+, opens the placeholder dialog.
   - Cmd+O / Cmd+S / Cmd+P fire the same slots as the toolbar buttons.
   - Cmd+Q quits cleanly; unsaved-changes prompt from existing `closeEvent` still fires.

---

## Open questions / notes

- **Preferences role on Qt 6:** `QAction.PreferencesRole` exists; if running on a Qt version where the enum name changed, use `QAction.MenuRole.PreferencesRole`. Confirm in the actual PySide6 version during Task 2.
- **Shared-action ownership:** A `QAction` added to both a toolbar and a menu is fine in Qt; it fires once per trigger regardless of source. If double-triggering is observed, check for an accidental `triggered`-to-`triggered` chain rather than adding duplicate slots.
- **Fullscreen shortcut:** macOS convention is `⌃⌘F`, which `QKeySequence.FullScreen` maps to. If the existing toolbar uses F11, overwriting on macOS is intentional — the Windows/Linux paths keep F11.
- **Window menu document list:** Apple HIG suggests listing open documents in the Window menu. The app currently uses tabs, not multi-window. Deferred — the Window menu ships with only "最小化" for now.
- **Deferred: macOS-keep-alive behavior:** Apple convention is that closing the last window does NOT quit. This plan keeps the current `setQuitOnLastWindowClosed(True)` default to preserve existing behavior and avoid surprising Windows muscle memory when the same code runs in both places. Flagged for a later UX slice.
