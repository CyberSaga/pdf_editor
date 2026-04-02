# Week 1 Acrobat-Parity Fixes — Implementation Plan

## Context

Cross-comparison GUI testing (2026-03-31) against Adobe Acrobat identified 9 UX gaps that explain why the PDF editor feels less polished than Acrobat. This plan implements the 5 highest-leverage fixes from Week 1 of `docs/plans/acrobat_parity_improvement_plan_2026_03_31.md`. The goal is to close the most visible discoverability and data-safety gaps within one sprint.

**Reference reports:**
- `docs/reports/cross_comparison_ux_2026_03_31.md` — observed differences
- `docs/plans/acrobat_parity_improvement_plan_2026_03_31.md` — full plan
- `docs/reports/commit_5784849_audit_report_2026_03_31.md` — remaining bugs

**Branch:** `codex/text-editing-function-by-iterating-repeatedly`

---

## What We're Building (5 fixes)

| Fix | Priority | File(s) | Effort |
|-----|----------|---------|--------|
| 1. Persistent block outlines in edit mode | CRITICAL | `view/pdf_view.py` | Medium |
| 2. IBeam cursor over editable text | MODERATE | `view/pdf_view.py` | Trivial |
| 3. Cmd+Shift+Z redo alias | LOW | `view/pdf_view.py` | Trivial |
| 4. Remove +4.0pt padding (position drift) | LOW | `model/pdf_model.py` | Trivial |
| 5. Mode switch auto-commit (not discard) | HIGH | `view/text_editing.py` | Small |

---

## Fix 1 — Persistent Block Outlines in Edit Mode

**Problem:** Entering `edit_text` mode reveals nothing. Users must hover to discover editable blocks. Acrobat outlines all text blocks immediately on entering "Edit PDF" mode.

**Approach:** When `edit_text` mode is entered, draw a `QGraphicsRectItem` outline around every text block on all currently-rendered pages. Update when page renders change. Remove on mode exit.

### Implementation

**File:** `view/pdf_view.py`

**Step 1 — Add storage in `__init__` (near `_hover_highlight_item` init):**

> **Design review:** Use `dict` keyed by `(page_idx, block_idx)` instead of a plain `list`. This enables O(1) lookup to hide/show a specific block's outline on hover and on active-edit open, without iterating all items.

```python
# Maps (page_idx, block_idx) → QGraphicsRectItem for O(1) hover hide/show
self._block_outline_items: dict[tuple[int, int], QGraphicsRectItem] = {}
# Track which block is currently hidden by hover so we can restore it
self._hover_hidden_outline_key: tuple[int, int] | None = None
```

**Step 2 — Add `_draw_all_block_outlines()` and `_clear_all_block_outlines()` methods (near `_update_hover_highlight`, ~line 3416):**

**Performance:** Only draw outlines for currently-visible pages. Use existing `visible_page_range()` (line 2725) which already computes viewport-visible page indices efficiently. This avoids creating thousands of graphics items for large documents.

```python
def _draw_all_block_outlines(self) -> None:
    """Draw persistent dim outlines around text blocks on visible pages only (performance-safe)."""
    self._clear_all_block_outlines()
    if not hasattr(self, 'controller') or not self.controller.model.doc:
        return
    rs = self._render_scale if self._render_scale > 0 else 1.0
    start_page, end_page = self.visible_page_range(prefetch=1)  # +1 page buffer
    pen = QPen(QColor(100, 149, 237, 120), 1.0, Qt.DashLine)   # cornflower blue, dashed
    brush = QBrush(Qt.NoBrush)
    for page_idx in range(start_page, end_page + 1):
        page_num = page_idx + 1   # model uses 1-based
        try:
            self.controller.model.ensure_page_index_built(page_num)
            blocks = self.controller.model.block_manager.get_blocks(page_num)
        except Exception:
            continue
        y0 = (self.page_y_positions[page_idx]
              if (self.continuous_pages and page_idx < len(self.page_y_positions))
              else 0.0)
        for block_idx, block in enumerate(blocks):
            try:
                br = block.rect   # fitz.Rect: x0, y0, x1, y1
                scene_rect = QRectF(br.x0 * rs, y0 + br.y0 * rs,
                                    br.width * rs, br.height * rs)
                item = self.scene.addRect(scene_rect, pen, brush)
                item.setZValue(8)   # below hover highlight (z=10), above page image
                self._block_outline_items[(page_idx, block_idx)] = item
            except Exception:
                continue

def _clear_all_block_outlines(self) -> None:
    for item in self._block_outline_items.values():
        try:
            self.scene.removeItem(item)
        except Exception:
            pass
    self._block_outline_items.clear()
    self._hover_hidden_outline_key = None
```

**Step 3 — Call in `set_mode()` at line 2136–2137 (edit_text branch):**
```python
elif mode == 'edit_text':
    self.right_stacked_widget.setCurrentWidget(self.text_card)
    self._draw_all_block_outlines()   # ← ADD THIS
```

**Step 4 — Clear on mode exit in `set_mode()` at existing line 2111–2112:**
```python
if mode != 'edit_text':
    self._clear_hover_highlight()
    self._clear_all_block_outlines()   # ← ADD THIS
```

**Step 5 — Refresh on scroll AND zoom.**

> **Design review finding:** `sig_viewport_changed` is emitted only by `_on_scroll_changed` (scroll, line 2531). Zoom triggers `_rebuild_continuous_scene_scaled` which calls `scroll_to_page(..., emit_viewport_changed=False)` — zoom does NOT fire `sig_viewport_changed`. Also connect `sig_scale_changed` (line 831) to catch zoom events.

```python
# In set_mode(), edit_text branch:
elif mode == 'edit_text':
    self.right_stacked_widget.setCurrentWidget(self.text_card)
    self._draw_all_block_outlines()
    try:
        self.sig_viewport_changed.connect(self._draw_all_block_outlines)
    except Exception:
        pass
    try:
        self.sig_scale_changed.connect(self._draw_all_block_outlines)
    except Exception:
        pass

# In set_mode(), mode-exit branch (line 2111):
if mode != 'edit_text':
    self._clear_hover_highlight()
    self._clear_all_block_outlines()
    try:
        self.sig_viewport_changed.disconnect(self._draw_all_block_outlines)
    except Exception:
        pass
    try:
        self.sig_scale_changed.disconnect(self._draw_all_block_outlines)
    except Exception:
        pass
```

**Step 6 — Hover hide/show (design review addition):**

On hover, hide the dim outline for the hovered block and show only the solid hover highlight. On hover exit, restore the dim outline. This matches Acrobat's single-outline-at-a-time behavior and avoids double-border artifacts.

In `_update_hover_highlight()`, after the existing block detection logic, add:
```python
# Restore previously hidden outline (if any)
if self._hover_hidden_outline_key is not None:
    prev = self._block_outline_items.get(self._hover_hidden_outline_key)
    if prev is not None:
        prev.setVisible(True)
    self._hover_hidden_outline_key = None

# Hide the outline for the currently hovered block
if hit_block_key is not None:   # (page_idx, block_idx) of the hovered block
    outline = self._block_outline_items.get(hit_block_key)
    if outline is not None:
        outline.setVisible(False)
        self._hover_hidden_outline_key = hit_block_key
```

> **Implementation note:** The hover handler must resolve the hovered block to its `(page_idx, block_idx)` key. The existing `get_text_info_at_point` returns a block rect; the implementer should match it against the block list index to get `block_idx`.

**Step 7 — Active-editing block outline hiding (design review addition):**

When `create_text_editor()` is called for a specific block, hide that block's dim outline (the QTextEdit widget IS the visual container during editing). Restore on finalize.

In the edit-open call site (around line 3484–3490):
```python
# Hide dim outline for the block being edited
if self._active_outline_key is not None:
    outline = self._block_outline_items.get(self._active_outline_key)
    if outline is not None:
        outline.setVisible(False)
```

In `finalize_text_edit_impl()` (after the editor is removed):
```python
# Restore dim outline for the just-finished block
if self._active_outline_key is not None:
    outline = self._block_outline_items.get(self._active_outline_key)
    if outline is not None:
        outline.setVisible(True)
    self._active_outline_key = None
```

Add `self._active_outline_key: tuple[int, int] | None = None` to `__init__`.

> **Existing APIs used:**
> - `visible_page_range(prefetch)` — `view/pdf_view.py:2725`
> - `controller.model.ensure_page_index_built(page_num)` — per `docs/ARCHITECTURE.md`
> - `controller.model.block_manager.get_blocks(page_num)` — `model/text_block.py:284`, returns `list[TextBlock]` with `block.rect: fitz.Rect`
> - `sig_viewport_changed` — `view/pdf_view.py:832`, emitted on scroll
> - `sig_scale_changed` — `view/pdf_view.py:831`, emitted on zoom

---

## Fix 2 — IBeam Cursor Over Editable Text in Edit Mode

**Problem:** `edit_text` mode uses Arrow cursor everywhere. Acrobat shows IBeam over text blocks. Users don't know they can click to type.

**File:** `view/pdf_view.py` — `_update_hover_highlight()` (~line 3424)

**Change:** Add cursor update inside the existing hover check:
```python
# In _update_hover_highlight(), after line 3423 (info = controller.get_text_info_at_point):
if info:
    # ... existing rect code ...
    # Only set IBeam if not currently dragging a block (drag uses ClosedHandCursor)
    if self._text_edit_drag_state == TextEditDragState.IDLE:   # ← guard
        self.graphics_view.viewport().setCursor(Qt.IBeamCursor)   # ← ADD
else:
    self._clear_hover_highlight()
    self.graphics_view.viewport().setCursor(Qt.ArrowCursor)   # ← ADD
```

> **Design review:** Line 2957 sets `ClosedHandCursor` during block drag. Without the `IDLE` guard above, IBeam would override the drag cursor during the drag gesture, giving the user incorrect visual feedback. The guard is essential.

Also restore Arrow cursor in `_clear_hover_highlight()`:
```python
def _clear_hover_highlight(self):
    # ... existing code to remove item ...
    self.graphics_view.viewport().setCursor(Qt.ArrowCursor)   # ← ADD if not already there
```

---

## Fix 3 — Cmd+Shift+Z Redo Alias (macOS Standard)

**Problem:** Redo is `Cmd+Y` (Windows convention). macOS standard is `Cmd+Shift+Z`.

**File:** `view/pdf_view.py` — line 1529

**Current:**
```python
self._action_redo.setShortcut(QKeySequence("Ctrl+Y"))
```

**Change:** Keep `Ctrl+Y` and add second shortcut via `QShortcut`:
```python
self._action_redo.setShortcut(QKeySequence("Ctrl+Y"))
# Add macOS-standard alias (Ctrl = Cmd on macOS in Qt)
self._redo_mac_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
self._redo_mac_shortcut.activated.connect(self.sig_redo.emit)
```

---

## Fix 4 — Remove +4.0pt Padding (Position Drift)

**Problem:** Every edit commit adds 4pt to the text block's computed height, causing cumulative visual drift after repeated edits of the same block.

**File:** `model/pdf_model.py`

**Location 1 — line 2649:**
```python
# Before:
_probe_y1 = insert_rect.y0 + _probe_used_h + 4.0
# After:
_probe_y1 = insert_rect.y0 + _probe_used_h
```

**Location 2 — line 2786:**
```python
# Before:
computed_y1 = new_layout_rect.y0 + text_used_height + 4.0
# After:
computed_y1 = new_layout_rect.y0 + text_used_height
```

> **Risk note:** The 4.0pt may have been added as a workaround for text clipping at the bottom of the rect. After removing, test that text doesn't get clipped. If clipping occurs in practice, add `+ 1.0` (1pt safety margin instead of 4pt) to reduce drift while preventing clipping.

---

## Fix 5 — Mode Switch Auto-Commit (Not Silent Discard)

**Problem:** Switching modes while editing silently discards typed text. `TextEditFinalizeReason.MODE_SWITCH` maps to `TextEditOutcome.DISCARDED`.

**File:** `view/text_editing.py` — lines 534–547

**Current:**
```python
if reason in {
    TextEditFinalizeReason.CANCEL_BUTTON,
    TextEditFinalizeReason.ESCAPE,
    TextEditFinalizeReason.MODE_SWITCH,    # ← causes silent discard
    TextEditFinalizeReason.CLOSE_DOCUMENT,
}:
    return TextEditFinalizeResult(outcome=TextEditOutcome.DISCARDED, ...)
```

**Change:** Remove `MODE_SWITCH` from the discard set so it falls through to the commit logic (same path as `CLICK_AWAY`):
```python
if reason in {
    TextEditFinalizeReason.CANCEL_BUTTON,
    TextEditFinalizeReason.ESCAPE,
    # MODE_SWITCH removed — falls through to commit
    TextEditFinalizeReason.CLOSE_DOCUMENT,
}:
    return TextEditFinalizeResult(outcome=TextEditOutcome.DISCARDED, ...)
```

> **Edge case:** `CLOSE_DOCUMENT` keeps discard behavior intentionally — when closing, the document is gone. `ESCAPE` and `CANCEL_BUTTON` remain discard since they are explicit user cancellation signals.
>
> **What changes:** Clicking Browse/Rect/Highlight while mid-edit will now commit the edit (same as clicking outside the text block). This matches Acrobat's behavior.

> **Design review — toast is REQUIRED:** Replacing silent discard with silent commit swaps one confusion for another. When a user switches modes, they need to know whether their edit landed. Show a 1.5s "Text edit saved." toast using a `QLabel` overlay positioned bottom-center of the viewport. The toast must appear when `MODE_SWITCH` triggers commit (i.e., when `result.outcome == TextEditOutcome.APPLIED`). This is not optional.

---

## Critical Files

| File | Purpose | Key Lines |
|------|---------|-----------|
| `view/pdf_view.py` | Hover highlight, mode entry, cursor, redo | 1529, 2111–2142, 3416–3449 |
| `view/text_editing.py` | Finalization reason → outcome mapping | 534–547 |
| `model/pdf_model.py` | +4.0pt padding removal | 2649, 2786 |

---

## Implementation Order (minimize re-runs)

1. `model/pdf_model.py` — remove +4.0pt (2 lines, no risk to other fixes)
2. `view/text_editing.py` — remove MODE_SWITCH from discard set (1 line change)
3. `view/pdf_view.py` line 1529 — add Cmd+Shift+Z alias (2 lines)
4. `view/pdf_view.py` `_update_hover_highlight` — add IBeam cursor logic (2 lines)
5. `view/pdf_view.py` — add block outlines (new method + 2 call sites)

---

## Tests Required

Add to `test_scripts/test_text_editing_gui_regressions.py`:

### Test: MODE_SWITCH now commits instead of discarding
```python
def test_mode_switch_commits_edit_not_discards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching modes while editing must auto-commit, not silently discard."""
    from view.text_editing import TextEditFinalizeReason, TextEditOutcome
    view = _make_minimal_view()  # use existing helper
    # Set up a fake editor with changed text
    _setup_fake_editor(view, original_text="Hello", new_text="Hello World")
    result = view.text_edit_manager.finalize_text_edit(TextEditFinalizeReason.MODE_SWITCH)
    assert result is not None
    assert result.outcome != TextEditOutcome.DISCARDED, \
        "MODE_SWITCH must not discard — text edits are lost silently"
    # Outcome should be APPLIED or SKIPPED (no change), never DISCARDED
    assert result.outcome in (TextEditOutcome.APPLIED, TextEditOutcome.SKIPPED)
```

### Test: ESCAPE and CANCEL_BUTTON still discard
```python
def test_escape_still_discards(monkeypatch: pytest.MonkeyPatch) -> None:
    """ESCAPE must still discard — it is an explicit cancel signal."""
    from view.text_editing import TextEditFinalizeReason, TextEditOutcome
    view = _make_minimal_view()
    _setup_fake_editor(view, original_text="Hello", new_text="Hello World")
    result = view.text_edit_manager.finalize_text_edit(TextEditFinalizeReason.ESCAPE)
    assert result is not None
    assert result.outcome == TextEditOutcome.DISCARDED
```

### Test: Block outlines respect visible_page_range
```python
def test_block_outlines_only_drawn_for_visible_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """_draw_all_block_outlines must only draw for visible_page_range, not all pages."""
    view = _make_minimal_view()
    visited_pages = []
    monkeypatch.setattr(
        view, 'visible_page_range', lambda prefetch=0: (3, 5)  # pages 3-5 visible
    )
    # Ensure get_blocks is only called for pages 3-5
    orig_get_blocks = view.controller.model.block_manager.get_blocks
    def tracking_get_blocks(page_num):
        visited_pages.append(page_num)
        return orig_get_blocks(page_num)
    monkeypatch.setattr(view.controller.model.block_manager, 'get_blocks', tracking_get_blocks)
    view._draw_all_block_outlines()
    assert all(p in (4, 5, 6) for p in visited_pages), \
        f"Expected pages 4-6 (1-based), got {visited_pages}"
```

### Test: Cmd+Shift+Z fires redo
```python
def test_cmd_shift_z_fires_redo(qapp) -> None:
    """Cmd+Shift+Z (macOS standard) must trigger redo signal."""
    view = _make_minimal_view()
    redo_count = [0]
    view.sig_redo.connect(lambda: redo_count.__setitem__(0, redo_count[0] + 1))
    # Simulate Ctrl+Shift+Z key press
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    view._redo_mac_shortcut.activated.emit()
    assert redo_count[0] == 1
```

---

## Verification

### Fix 1 (block outlines)
1. Launch editor, open TIA-942 PDF, navigate to page 5
2. Click "編輯文字" toolbar button
3. **Expected:** Dashed cornflower-blue outlines appear around all visible text blocks immediately, without hovering
4. Hover over a block — **Expected:** dim dashed outline DISAPPEARS, replaced by solid blue hover highlight only (no double-border)
5. Move mouse off the block — **Expected:** dim dashed outline RESTORES, solid hover clears
6. Click a block to open editor — **Expected:** that block's dim outline hides (editor widget is the visual boundary)
7. Finish editing — **Expected:** dim outline restores for that block
8. Change zoom level while in edit_text mode — **Expected:** outlines redraw at correct positions
9. Switch to Browse mode — all outlines disappear

### Fix 2 (IBeam cursor)
1. In edit_text mode, hover over a text block
2. **Expected:** Cursor changes to IBeam (only when not dragging)
3. Move mouse to empty page area — **Expected:** cursor returns to Arrow
4. Click-drag a block — **Expected:** cursor stays ClosedHand (IBeam does NOT override drag cursor)

### Fix 3 (Cmd+Shift+Z)
1. Make a text edit, commit
2. Press Cmd+Shift+Z — **Expected:** redo fires (same as Cmd+Y)

### Fix 4 (+4.0pt removal)
1. Edit a text block 5 times (type a character, commit, repeat)
2. **Expected:** Block does not grow visually after each commit
3. Check text is not clipped at bottom

### Fix 5 (mode switch commit)
1. Enter edit_text mode, click a text block, type "HELLO"
2. Click the Browse mode button
3. **Expected:** Edit is committed (text appears in PDF) — NOT discarded silently
4. **Expected:** "Text edit saved." toast appears for 1.5s at bottom-center of viewport
5. Press Cmd+Z — **Expected:** text reverts (proves it went through commit path)

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | DONE | Visible-pages-only for Fix 1 (perf) |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | DONE | +4 tests added; sig_viewport_changed scroll hook added |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | DONE | 4 findings: dict storage for outlines, hover hide/show, zoom via sig_scale_changed, toast required |

**VERDICT:** READY — 3 reviews complete (CEO + Eng + Design). Codex review optional.
