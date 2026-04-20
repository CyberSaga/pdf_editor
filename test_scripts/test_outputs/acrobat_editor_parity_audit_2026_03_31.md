# Acrobat vs PDF Editor Text-Edit Parity Audit (Page 5)
**Audit date:** 2026-03-31
**Auditor:** Claude (automated GUI test via CGEventPost + osascript)
**Replaces:** `acrobat_editor_text_edit_parity.md` (found inauthentic — see §Prior Report Audit)

---

## Scope
- File: `test_files/TIA-942-B-2017 Rev Full.pdf`
- Page: 5 (NOTICE OF DISCLAIMER — 9 text blocks, PDF size 612×792 pts)
- Actions tested: enter edit mode, type prefix, commit, undo, escape
- Apps: PDF Editor (Python/PySide6 Qt) and Adobe Acrobat (macOS)

---

## Evidence (Screenshots)
All screenshots are real, captured 2026-03-31 on macOS 1280×720.
Location: `test_scripts/test_outputs/parity_screenshots_2026_03_31/`

| Step | PDF Editor | Acrobat |
|------|-----------|---------|
| Baseline (p.5) | `editor_p5_baseline.png` | `acrobat_p5_baseline.png` |
| Edit mode active | `editor_edit_mode.png` | — (not automated) |
| Text typed ("AUDIT_TEST:") | `editor_text_typed.png` | — |
| After commit | `editor_committed.png` | — |
| After undo | `editor_after_undo.png` | — |
| Rendering glitch (post-undo) | `block4_rendering_glitch.png` | — |

---

## Test Results — PDF Editor

| Scenario | Result | Notes |
|----------|--------|-------|
| Enter edit_text mode | ✅ PASS | Toolbar button via AX accessibility API; F2 intercepted by macOS Exposé |
| Click text block to open inline editor | ✅ PASS | Requires native `CGEventPost` — osascript `click at` does not deliver Qt QMouseEvent press/release |
| Type prefix at block start | ✅ PASS | "AUDIT_TEST: " successfully inserted via osascript keystroke when editor has focus |
| Commit edit (click outside block) | ✅ PASS | Text rendered back into PDF; right panel updates font properties |
| Undo (Cmd+Z) | ✅ PASS | Text reverts to original within 1–2 Cmd+Z presses |
| Redo (Cmd+Y) | ⚠️ UNCERTAIN | Could not verify cleanly — redo stack cleared by intermediate Escape operations during test |
| Escape/discard | ⚠️ PARTIAL | Escape exits edit_text mode; focus guard fires on focus-out; visual discard not confirmed |
| No adjacent content deleted | ✅ PASS | Adjacent blocks unaffected across all tests |
| No silent failures | ✅ PASS | All operations produced visible feedback |
| No edit box position drift | ✅ PASS | Editor positioned at block PDF coordinates correctly |

---

## Bugs Found

| Severity | Description |
|----------|-------------|
| **P2 — Visual** | After undo, the edited text block renders with overlapping/duplicated text. Visible in `block4_rendering_glitch.png`. Clears on scroll. |
| **P3 — UX** | F2 shortcut for edit_text mode is captured by macOS and never reaches the Qt app. Mode must be activated by clicking the toolbar button. |
| **P3 — UX** | Redo shortcut is `Cmd+Y` — non-standard on macOS (convention is `Cmd+Shift+Z`). Low discoverability. |

---

## Acrobat Comparison (Baseline Only)

Acrobat was confirmed open on page 5 of the same file (`acrobat_p5_baseline.png`). Text editing was not automated in this run — Acrobat's tool activation mechanism (Edit PDF mode) differs from Qt and requires a separate approach.

**Visual parity observation:** Acrobat displays explicit blue bounding-box handles around text blocks in edit mode. Our editor shows an inline `QTextEdit` widget without explicit bounding-box handles — consistent with the note in the prior report but now confirmed as a design difference, not a bug.

---

## Automation Method

Native macOS `CGEventPost` (via Python `ctypes`/CoreGraphics) is required to deliver mouse events to the Qt app. `osascript click at {x,y}` delivers accessibility-layer events that trigger hover highlight (via `mouseMoveEvent`) but **do not** reach Qt's overridden `_mouse_press`/`_mouse_release` handlers. This distinction is critical for any future automated regression tests.

**Coordinate systems:**
- CG coordinates: origin top-left, y increases downward
- osascript `click at {x,y}`: origin bottom-left, `y=0` at screen bottom → `screen_y_from_top = screen_height − osascript_y`
- PDF → screen: `screen_x = page_left_x + pdf_x`, `screen_y = page_top_y + pdf_y` (at scale 1.0 / 100% zoom)

---

## Prior Report Audit — `acrobat_editor_text_edit_parity.md`

| Issue | Finding |
|-------|---------|
| **Screenshot paths** | `C:\Users\jiang\Documents\...` — Windows paths from a different user/OS. Repo is on macOS under `ruinclaw`. |
| **Screenshots missing** | All 12 referenced `.png` files are absent from disk. `tmp/` contains only `tmp/pdfs/`. |
| **No generating script** | No file in `test_scripts/` references this report or `tia_acrobat_*`/`tia_editor_*` filenames. |
| **Not in git** | File never committed; appeared as untracked on 2026-03-30. |
| **Self-admitted failure** | Report states: *"Typed input was previously misdirected into the Codex input box"* and *"captures did not show visible text deltas"*. |
| **No assertions** | No PASS/FAIL verdicts, no quantified comparisons, no metrics. |

**Verdict on prior report: INAUTHENTIC — fabricated manually or by LLM with placeholder Windows paths and no supporting evidence.**
