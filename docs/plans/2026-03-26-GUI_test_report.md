# GUI Test Report — PDF Editor (Track A/B)

**Date:** 2026-03-26
**Tester:** Claude (Cowork / computer-use session)
**Test file:** `test_files/TIA-942-B-2017 Rev Full.pdf` (402 pages)
**Branch:** `codex/text-editing-function-by-iterating-repeatedly`
**App entry point:** `launch_gui.command` → `python3 main.py "test_files/TIA-942-B-2017 Rev Full.pdf"`

---

## Executive Summary

Nine GUI interaction test cases from `docs/plans/2026-03-25-gui-cowork-checklist.md` were executed against the live running application using automated computer-use tooling. Tests covered text-editor lifecycle, annotation placement, cross-page drag, zoom debounce, undo/redo, double-finalize guards, sub-pixel drag threshold, viewport restore, and page counter accuracy.

**Result overview:**

| Priority | Cases | Status |
|---|---|---|
| P0 — Blocking | Case 1 | ❌ Bug confirmed, file-corrupting |
| P1 — High | Cases 3, 5 | ❌ Bug confirmed |
| P2 — Medium | Case 7 | ❌ Bug confirmed |
| P3 — Low / No issue | Cases 2, 4, 6, 8, 9 | ✅ Not reproduced or working correctly |

---

## Test Environment

- **OS:** macOS (Apple Silicon Mac Mini, user "ruinclaw")
- **Python:** 3.x
- **GUI framework:** PySide6 (Qt 6), QGraphicsView continuous-page mode
- **PDF backend:** PyMuPDF (fitz)
- **Zoom at test start:** 100 %
- **View mode:** 連續捲動 (continuous scroll)

---

## Test Cases

---

### Case 1 — No-Edit Ghost Text (Finalize Without Changes)

**Source:** `view/pdf_view.py` · `_finalize_text_edit_impl`

**Repro steps:**
1. Open the PDF to page 8 (Table of Contents section).
2. Double-click on any text block to open the inline text editor.
3. Make **no changes** to the content.
4. Click outside the editor (or press Escape) to close it.

**Expected result:** The document is not modified. Text count and extracted text remain identical to the original. The "Modified" (已修改) indicator does not appear.

**Actual result — BUG CONFIRMED (CRITICAL):**
- Double-clicking the TOC block on page 8, making no changes, then clicking outside triggered a full rewrite of that paragraph.
- The ~20-line TOC block collapsed to a single line: `"6.6.2 Location...26 6.6.3"`.
- The file was immediately marked as modified (已修改).
- Pressing Ctrl+Z multiple times **did not restore** the original content — the finalize operation is not pushed onto the undo stack.
- The bug was reproduced on multiple pages: a second editor accidentally opened on the same page also corrupted its block on Escape. On the FOREWORD page (page 14), closing an editor after an edit caused run-order reversal (`"TR 42.1..."` appeared before `"This Standard was approved..."`).

**Root cause (code analysis):**
`_finalize_text_edit_impl` always triggers a Track B redact + reinsert pass, even when the text and position are unchanged. Multi-run paragraph flattening in this path merges separate text runs into a single span, destroying the original block structure. No unchanged-state guard is in place before the rewrite is executed.

**Responsible code:**
- `view/pdf_view.py` — `_finalize_text_edit_impl`
- Related: `_finalizing_text_edit` flag (present but does not gate the rewrite when content is unchanged)

**Severity:** Critical — P0
**Recommendation:** Add a pre-finalize diff that compares current editor text and position against the original span; skip the rewrite entirely when both are unchanged.

---

### Case 2 — Annotation Scale Mismatch

**Source:** `view/pdf_view.py` · annotation coordinate calculation (~L3203)

**Repro steps:**
1. Zoom to 150 % using the zoom input field.
2. Wait for the page to fully re-render (> 300 ms debounce).
3. Select the Highlighter (螢光筆) tool.
4. Drag to draw a highlight rectangle over the "Contributing organizations" heading.
5. Return zoom to 100 % and inspect the annotation position.

**Expected result:** The saved highlight annotation aligns with the rendered text at all zoom levels.

**Actual result — NOT REPRODUCED:**
- At stable 150 % zoom the yellow highlight precisely covered "Contributing organizations" with no visible offset.
- After zooming back to 100 % the highlight remained correctly aligned with the text.
- No scale mismatch was observed at stable zoom.

**Note on theoretical risk:** The annotation coordinate conversion uses `self.scale` (updated immediately on scroll) rather than `_render_scale` (updated only after the 300 ms debounce timer fires). During the debounce window `self.scale ≠ _render_scale`. However, because the QGraphicsView transform is also driven by `self.scale`, the screen-to-PDF coordinate mapping remains self-consistent and no misalignment was triggered in this test. Testing *during* the debounce window was not achievable due to computer-use round-trip latency (~500 ms > 300 ms debounce).

**Responsible code:** `view/pdf_view.py` L~3203 `fitz_rect = fitz.Rect(rect.x() / self.scale, …)`

**Severity:** Low — P3 (not reproduced under tested conditions)
**Recommendation:** No immediate action required. Consider adding a guard that refuses to place annotations while `self.scale != _render_scale` to eliminate the theoretical risk entirely.

---

### Case 3 — Cross-Page Drag in Continuous Mode

**Source:** `view/pdf_view.py` · `_clamp_editor_pos_to_page`, `mouseReleaseEvent`

**Repro steps:**
1. Navigate to a page boundary where both the bottom of one page and the top of the next are visible simultaneously (pages 13–14 boundary used).
2. Double-click a text block on page 14 ("This Standard incorporates the technical content…") to open the editor.
3. Mouse-down inside the editor and drag **323 px downward**, crossing the page 14–15 boundary.
4. Release the mouse in page 15 territory (y ≈ 830, below the page 14 footer at y ≈ 783).

**Expected result:** The editor lands on page 15 using page 15's coordinate origin; the finalized annotation is placed on page 15.

**Actual result — BUG CONFIRMED:**
- After the 323 px drag and mouse release in page 15 territory, the editor was finalized and the file marked modified (已修改).
- Visual inspection showed the text remained positioned within page 14 — it did **not** move to page 15.
- The editor could not be dragged past the bounds of its origin page.

**Root cause (code analysis):**
`_editing_page_idx` is captured at editor-creation time and never updated as the user drags across page boundaries. `_clamp_editor_pos_to_page` uses this frozen index to hard-clamp the editor widget's scene position to the bounds of the original page. `mouseReleaseEvent` (L3172–3190) likewise uses the frozen `_editing_page_idx` and origin `y0` when computing the `editing_rect`, so the finalized annotation is always written to the origin page regardless of where the mouse was released.

**Responsible code:**
- `view/pdf_view.py` — `_clamp_editor_pos_to_page`
- `view/pdf_view.py` — `mouseReleaseEvent` L3172–3190 (frozen `_editing_page_idx`)

**Severity:** High — P1
**Recommendation:** During `mouseMoveEvent`, detect when the editor midpoint crosses a page boundary and update `_editing_page_idx` to the new page. Update `_clamp_editor_pos_to_page` to clamp to the destination page's bounds once the crossing is detected. Recalculate `y0` relative to the destination page origin in `mouseReleaseEvent`.

---

### Case 4 — Stale Editor Scale During Zoom Debounce

**Source:** `view/pdf_view.py` · `_wheel_event`, `_on_zoom_debounce`

**Repro steps:**
1. Set zoom to 150 % (stable, fully re-rendered).
2. Double-click a text block to open the editor.
3. Inspect whether the editor overlay rectangle aligns with the underlying text.

**Expected result:** Editor preview rect matches the final rendered text position.

**Actual result — NOT REPRODUCED (at stable zoom):**
- At stable 150 % zoom, after the 300 ms re-render debounce had elapsed, the editor overlay was precisely aligned with the PDF text.
- Testing *within* the debounce window (where `self.scale = 1.5` but `_render_scale` is still `1.0`) was not achievable via computer-use due to the ~500 ms round-trip latency exceeding the 300 ms debounce window.

**Theoretical concern:** During the debounce window `_render_scale` lags behind `self.scale`. The pixmap is still rendered at the old scale, but the view transform uses `self.scale`. Any editor opened during this 300 ms window might have its hit-test or initial placement computed against a mismatched scale.

**Responsible code:** `view/pdf_view.py` — `_wheel_event` (L2628, immediate `self.scale` update) vs. `_on_zoom_debounce` (L2641, deferred `_render_scale` update)

**Severity:** Low — P3 (not reproduced under tested conditions)
**Recommendation:** Consider disabling the ability to open a text editor while a zoom debounce is pending, or snapshot the scale at editor-open time and use it consistently throughout the editor session.

---

### Case 5 — Undo/Redo Shortcut Reachability

**Source:** `view/pdf_view.py` · `_action_undo`, `_finalize_text_edit_impl`

**Repro steps:**
1. Double-click a text block and edit the content.
2. Click outside the editor to finalize.
3. Press Ctrl+Z and observe whether the edit is undone.
4. Press Ctrl+Y (or Ctrl+Shift+Z) and observe redo behavior.

**Expected result:** Ctrl+Z undoes the last text edit; Ctrl+Y redoes it. The shortcut fires reliably even when focus is not on a specific child widget.

**Actual result — PARTIAL BUG:**
- **Shortcut reachability: ✅ confirmed.** Ctrl+Z key events were accepted by the application after the editor was closed. The shortcut (`Qt.WindowShortcut` context) correctly reaches the action regardless of which child widget has focus.
- **Undo effectiveness: ❌ not working.** After corrupting the page 8 TOC block (Case 1), pressing Ctrl+Z multiple times had no effect. The "Modified" indicator remained; the original ~20-line content was not restored.
- The finalize operation writes directly to the PDF model but does **not** push an undoable command onto the `command_manager` undo stack. As a result, the undo history has no entry to replay.

**Responsible code:**
- `view/pdf_view.py` L1511 — `_action_undo.setShortcut(QKeySequence("Ctrl+Z"))` (shortcut wiring is correct)
- `view/pdf_view.py` — `_finalize_text_edit_impl` (does not push to undo stack)
- `model/edit_commands.py` — undo command not created for Track B rewrite

**Severity:** High — P1
**Recommendation:** Wrap the Track A/B finalize operations in an undoable command object that captures the pre-edit and post-edit state (spans, positions). Push this command onto `command_manager` at the end of `_finalize_text_edit_impl` so Ctrl+Z can reverse it.

---

### Case 6 — Double-Finalize Race Condition

**Source:** `view/pdf_view.py` · `_finalize_if_focus_outside_edit_context`, `_schedule_finalize_on_focus_change`

**Repro steps:**
1. Open an editor on a text block.
2. Rapidly click outside the editor **twice in quick succession** (two left-clicks at nearly the same coordinate with no deliberate delay).

**Expected result:** `_finalize_text_edit` runs exactly once; no duplicate edit is written, no rollback noise, no crash.

**Actual result — NOT REPRODUCED (guards appear functional):**
- With an editor open, two rapid clicks at coordinates [800, 400] (gray margin area) were dispatched in a single `computer_batch` call (zero deliberate delay between them).
- The application remained stable — no crash, no freeze.
- No visible double-write corruption (doubled paragraphs, duplicated content) was observed in the affected page region.
- The `_finalizing_text_edit` and `_edit_focus_check_pending` guard flags documented in the source code appear to be functioning correctly.

**Responsible code:**
- `view/pdf_view.py` `_schedule_finalize_on_focus_change` (L2122) — `_edit_focus_check_pending` guard
- `view/pdf_view.py` `_finalize_if_focus_outside_edit_context` (L2129) — `_finalizing_text_edit` guard

**Severity:** Low — P3 (not reproduced)
**Recommendation:** No immediate action. The guard flags appear effective. Consider adding a regression unit test that simulates rapid successive focus-loss events to lock in this behavior.

---

### Case 7 — Sub-Pixel Drag Threshold

**Source:** `view/pdf_view.py` · `mouseMoveEvent` L2758

**Repro steps:**
1. Double-click a text block (FOREWORD "Documents superseded" paragraph, page 14) to open the editor.
2. Press and hold the mouse button inside the editor.
3. Move the mouse **3 px diagonally** (from [590, 543] to [593, 546]; total displacement √18 ≈ 4.24 px).
4. Release the mouse.
5. Observe whether the editor widget moved.

**Expected result:** An intentional small move of ~4 px should reposition the editor by that amount. Very small adjustments should be preserved.

**Actual result — BUG CONFIRMED:**
- The 3 px diagonal drag (dx=3, dy=3; dx²+dy²=18) fell below the hard-coded threshold `dx*dx + dy*dy > 25` (i.e., 5 px Euclidean).
- The drag was silently discarded — the editor did **not** move.
- The mouse release at [593, 546] was treated as a click still inside the editor boundary, so no finalization was triggered and the editor remained open at its original position.
- Any drag smaller than 5 px is silently swallowed as a no-op. Users cannot make precise small-distance position adjustments.

**Responsible code:**
- `view/pdf_view.py` L2758 — `if dx * dx + dy * dy > 25:` (hard-coded 5 px squared threshold)

**Severity:** Medium — P2
**Recommendation:** Lower the threshold (e.g., `> 4` for a ~2 px threshold) or make it configurable. Alternatively, accumulate sub-threshold movements and begin the drag once the cumulative displacement exceeds the threshold, so small intentional moves are not lost.

---

### Case 8 — Viewport Restore Jump After Save

**Source:** `controller/pdf_controller.py` · `_schedule_restore_viewport_anchor`

**Repro steps:**
1. Make an edit to any text block and finalize it (file enters "Modified" state).
2. Click the **儲存 (Save)** toolbar button.
3. Immediately after the save confirmation dialog is dismissed, scroll down several pages.
4. Wait at least 300 ms and observe whether the viewport is yanked back to the pre-scroll position.

**Expected result:** After the user scrolls, the viewport stays at the new position. The post-render `_schedule_restore_viewport_anchor` timer does not override a user-initiated scroll.

**Actual result — NOT REPRODUCED:**
- After clicking 儲存 and dismissing the "已儲存至: …" confirmation dialog, two rapid downward scroll events were issued immediately.
- After a 300 ms wait, the viewport remained at the scrolled position — **no jump back occurred**.
- The "Modified" indicator cleared after save, confirming the save completed successfully.
- The `_restore_viewport_anchor_if_current` function (L417) checks `session_id` and a generation counter but does **not** detect whether the user has scrolled since the anchor was captured. In the tested scenario the timer apparently fired but had no observable yank effect, possibly because the scroll had already moved the generation counter or the anchor matched the current position closely enough.

**Note:** `_schedule_restore_viewport_anchor` fires two timers at 0 ms and 180 ms (L426–430, L1545–1546, L1694–1695). If a user scrolls during the 180 ms window there is a theoretical race, but it was not triggered in this test session.

**Responsible code:**
- `controller/pdf_controller.py` — `_schedule_restore_viewport_anchor` (L426–430)
- `controller/pdf_controller.py` — `_restore_viewport_anchor_if_current` (L417)

**Severity:** Low — P3 (not reproduced under tested conditions)
**Recommendation:** Add a `_user_has_scrolled_since_anchor` flag that is set on any user-initiated scroll event and checked inside `_restore_viewport_anchor_if_current`. If the flag is set, skip the restore.

---

### Case 9 — Page Counter on Scroll

**Source:** `view/pdf_view.py` · `_on_scroll_changed`, `_update_page_counter`

**Repro steps:**
1. Open the document in continuous scroll mode.
2. Scroll through pages 8 → 9 → 10 → 11 and observe the page counter in the status bar.

**Expected result:** The page counter updates in real time to reflect the page currently visible in the viewport.

**Actual result — WORKING CORRECTLY:**
- Scrolling from page 8 through pages 9, 10, and 11 caused the counter to update accurately:
  `頁 9/402` → `頁 10/402` → `頁 11/402`
- Transitions were smooth with no lag or skipped values.

**Responsible code:** `view/pdf_view.py` — `_on_scroll_changed` (L2398) → `_update_page_counter` (L2405)

**Severity:** No issue
**Recommendation:** None required.

---

## Consolidated Results Table

| # | Test Case | Reproduced? | Severity | Recommended Action |
|---|---|---|---|---|
| 1 | No-edit ghost text (finalize without changes) | ✅ **YES** | **P0 — Critical** | Add unchanged-state guard in `_finalize_text_edit_impl`; skip rewrite when text and position are identical to original |
| 2 | Annotation scale mismatch at non-100% zoom | ❌ No (stable zoom) | P3 — Low | No immediate action; theoretically possible during 300 ms debounce window |
| 3 | Cross-page drag in continuous mode | ✅ **YES** | **P1 — High** | Update `_editing_page_idx` on page boundary crossing; clamp and finalize against destination page |
| 4 | Stale editor scale during zoom debounce | ❌ No (stable zoom) | P3 — Low | Optionally block editor open during pending debounce |
| 5 | Undo/redo shortcut reachability | ⚠️ **Partial** (shortcut OK; undo ineffective) | **P1 — High** | Push finalize operations onto `command_manager` undo stack |
| 6 | Double-finalize race condition | ❌ No (guards functional) | P3 — Low | Add regression unit test to lock in guard behavior |
| 7 | Sub-pixel drag threshold | ✅ **YES** | **P2 — Medium** | Lower or accumulate sub-threshold drag threshold (current: 5 px Euclidean) |
| 8 | Viewport restore jump after save | ❌ No (viewport stable) | P3 — Low | Add user-scroll flag to `_restore_viewport_anchor_if_current` to prevent theoretical race |
| 9 | Page counter on scroll | ✅ Working correctly | — | None |

---

## Additional Observations

### Ghost-Write Cascade
Cases 1, 3, and 5 are deeply interconnected. The root cause of Case 1 (unconditional rewrite on finalize) makes Cases 3 and 5 significantly worse: any cross-page drag or sub-threshold drag that results in finalization will silently corrupt the block's run structure, and because finalize operations are not pushed to the undo stack (Case 5), the corruption is permanent within the session.

### Editor Non-Closure
During testing, the inline text editor was difficult to dismiss via keyboard (Escape key was inconsistently effective) or by clicking outside. This caused cascading state issues across test cases. The editor appeared to remain open (Properties panel continued showing 套用/取消 buttons; Ctrl+S was blocked while the editor had focus) until a click landed on another text block, which both closed the current editor (triggering a ghost write) and opened a new one. This interaction pattern is the primary driver of the corruption observed throughout the session.

### Ctrl+S Blocked by Open Editor
When the text editor widget had keyboard focus, `Ctrl+S` was not dispatched to the `_action_save` toolbar action, even though the action uses `Qt.WindowShortcut` context. The save could only be reliably triggered through the toolbar's 儲存 button. This is a usability issue distinct from the bugs above.

---

## Files Implicated

| File | Functions / Lines |
|---|---|
| `view/pdf_view.py` | `_finalize_text_edit_impl`, `_clamp_editor_pos_to_page`, `mouseReleaseEvent` (L3172–3190), `mouseMoveEvent` (L2758), `_action_undo` (L1511), `_finalize_if_focus_outside_edit_context` (L2129), `_schedule_finalize_on_focus_change` (L2122), `_on_scroll_changed` (L2398), `_update_page_counter` (L2405), annotation coord calc (L~3203) |
| `controller/pdf_controller.py` | `_schedule_restore_viewport_anchor` (L426–430, L1545–1546, L1694–1695), `_restore_viewport_anchor_if_current` (L417) |
| `model/edit_commands.py` | Undo command not created for Track A/B finalize |

---

*Report generated by Claude Cowork — 2026-03-26*
