# Session Report — Week 1 Acrobat-Parity Fixes
**Date:** 2026-04-01
**Branch:** `codex/text-editing-function-by-iterating-repeatedly`
**PR:** https://github.com/CyberSaga/pdf_editor/pull/6
**Tests:** 32 passed, 0 failures

---

## Context

Cross-comparison GUI testing (2026-03-31) against Adobe Acrobat identified 9 UX gaps. This session implemented and shipped the 5 highest-leverage Week 1 fixes from the plan reviewed by CEO + Eng + Design.

**Plan file:** `~/.claude/plans/shimmying-cooking-flurry.md`
**Reference docs:**
- `docs/reports/cross_comparison_ux_2026_03_31.md` — observed gaps
- `docs/plans/acrobat_parity_improvement_plan_2026_03_31.md` — full backlog
- `docs/reports/commit_5784849_audit_report_2026_03_31.md` — remaining bugs

---

## Fixes Implemented

### Fix 1 — Persistent block outlines in edit_text mode `[CRITICAL]`
**File:** `view/pdf_view.py`
**New methods:** `_draw_all_block_outlines()`, `_clear_all_block_outlines()`, `_schedule_outline_redraw()`
**New state:** `_block_outline_items: dict[(page_idx, block_idx) → QGraphicsRectItem]`, `_hover_hidden_outline_key`, `_active_outline_key`, `_outline_redraw_timer`

Draws cornflower-blue dashed outlines (QPen, `QColor(100,149,237,120)`, `Qt.DashLine`, z=8) around all visible text blocks immediately on entering `edit_text` mode. Behavior:
- **Scroll/zoom refresh:** Connected to `sig_viewport_changed` and `sig_scale_changed` via `_schedule_outline_redraw` (80ms debounce timer) — collapses rapid scroll ticks into one redraw.
- **Hover:** Dim outline for the hovered block is hidden; restored when mouse moves away. Tracked via `_hover_hidden_outline_key`.
- **Active edit:** When `_create_text_editor()` opens a block, that block's dim outline is hidden (the editor widget is the visual boundary). Restored by `finalize_text_edit_impl()`. Tracked via `_active_outline_key`.
- **Mode exit:** `_clear_all_block_outlines()` removes all items; signals disconnected; `_outline_redraw_timer` stopped.
- **Signal guard:** `_prev_mode != 'edit_text'` guard in `set_mode()` prevents double-connection when `_start_text_edit_from_hit()` re-enters `edit_text` while already in that mode.

### Fix 2 — IBeam cursor over editable text `[MODERATE]`
**File:** `view/pdf_view.py` — `_update_hover_highlight()`

Shows `Qt.IBeamCursor` when hovering over text blocks in `edit_text` mode. Guard: `_text_edit_drag_state == TextEditDragState.IDLE` so `ClosedHandCursor` is not overridden during block drags. `Qt.ArrowCursor` restored when hover leaves the block.

### Fix 3 — Cmd+Shift+Z redo alias `[LOW]`
**File:** `view/pdf_view.py` — `__init__()`

```python
self._redo_mac_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
self._redo_mac_shortcut.activated.connect(self.sig_redo.emit)
```

Added alongside the existing `Ctrl+Y` binding. Matches macOS standard redo convention.

### Fix 4 — Remove +4.0pt height padding `[LOW]`
**File:** `model/pdf_model.py` — lines 2649 and 2786

Removed two `+ 4.0` additions in the text-layout probe path that caused cumulative visual drift after repeated edits of the same block. Both locations now compute exact height from `_probe_used_h` / `text_used_height` without padding.

### Fix 5 — Mode-switch auto-commit instead of silent discard `[HIGH]`
**File:** `view/text_editing.py` — `finalize_text_edit_impl()`

`TextEditFinalizeReason.MODE_SWITCH` removed from the discard set — falls through to the commit path (same as `CLICK_AWAY`). `ESCAPE` and `CANCEL_BUTTON` retain explicit discard behavior. `CLOSE_DOCUMENT` retains discard (document gone).

**File:** `view/pdf_view.py` — `set_mode()`, new `_show_toast()`

`_show_toast(message, duration_ms=1500)` creates a `QLabel` child of `graphics_view.viewport()`, centered horizontally, 24px from bottom, auto-deleted after `duration_ms` via `QTimer.singleShot`. Called with `"文字已儲存"` when mode-switch triggers a `TextEditOutcome.COMMITTED` result.

---

## Review Findings Fixed

### Pre-landing `/review` — AUTO-FIX
**Signal double-connection bug** in `set_mode()`: `_start_text_edit_from_hit()` calls `set_mode('edit_text')` while already in `edit_text` mode (e.g., user clicks a second block). Without a guard, both `sig_viewport_changed` and `sig_scale_changed` would be connected a second time — causing `_draw_all_block_outlines` to fire 2×, 3×, …N× per scroll/zoom event after N block clicks.

**Fix:** `_prev_mode = self.current_mode` saved before `self.current_mode = mode`, then `if _prev_mode != 'edit_text':` guards the `connect()` calls.

### Pre-landing `/review` — Missing mandatory Eng Review tests
All 4 tests from the Eng Review plan were absent. Added to `test_scripts/test_text_editing_gui_regressions.py`:

| Test | What it guards |
|------|---------------|
| `test_mode_switch_commits_edit_not_discards` | `MODE_SWITCH` → commit, not silent discard |
| `test_escape_still_discards` | `ESCAPE` → still discards (explicit cancel) |
| `test_block_outlines_only_drawn_for_visible_pages` | Only visible pages get outlines (perf guard) |
| `test_cmd_shift_z_fires_redo` | `Ctrl+Shift+Z` shortcut wiring |

### `/simplify` — Scroll debounce
`sig_viewport_changed` fires on every `QScrollBar.valueChanged` tick. `_draw_all_block_outlines` was removing and re-adding 30–90 `QGraphicsRectItem`s per tick with no throttle. Added `_outline_redraw_timer` (80ms single-shot, mirrors `_zoom_debounce_timer` pattern) and `_schedule_outline_redraw(*args)`. Signals now connect to `_schedule_outline_redraw`; mode-entry still calls `_draw_all_block_outlines()` directly for immediate display.

---

## Commits

| SHA | Message | Files |
|-----|---------|-------|
| `6517d27` | feat: Week 1 Acrobat-parity fixes — block outlines, cursor, redo alias, mode-switch commit | `view/pdf_view.py`, `view/text_editing.py`, `model/pdf_model.py`, `test_scripts/test_text_editing_gui_regressions.py`, `controller/pdf_controller.py` |
| `c85561a` | docs: sync ARCHITECTURE and FEATURES with Week 1 Acrobat-parity fixes | `docs/ARCHITECTURE.md`, `docs/FEATURES.md` |
| `244d312` | perf: debounce block outline redraws on scroll (80ms collapse window) | `view/pdf_view.py` |

---

## Files Changed

| File | Changes |
|------|---------|
| `view/pdf_view.py` | Block outlines (new methods + state), toast overlay, IBeam cursor, Cmd+Shift+Z shortcut, `set_mode()` signal management + double-connect guard, scroll debounce |
| `view/text_editing.py` | `MODE_SWITCH` removed from discard set; active outline restore on finalize |
| `model/pdf_model.py` | +4.0pt padding removed at lines 2649 and 2786 |
| `test_scripts/test_text_editing_gui_regressions.py` | 4 new mandatory tests added (+113 lines); total 32 tests |
| `controller/pdf_controller.py` | Whitespace/formatting only, no logic changes |
| `docs/ARCHITECTURE.md` | View section updated: block outlines, IBeam cursor, mode-switch auto-commit |
| `docs/FEATURES.md` | `edit_text` mode description + Cmd+Shift+Z keyboard shortcut |

---

## Current State

All 32 regression tests pass. PR #6 is open against `main`. The branch is ready to merge.

**Remaining backlog (not in this session):** see `docs/plans/acrobat_parity_improvement_plan_2026_03_31.md` for Week 2+ items.
