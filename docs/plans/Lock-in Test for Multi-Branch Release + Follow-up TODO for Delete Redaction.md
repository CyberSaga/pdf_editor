# Lock-in Test for Multi-Branch Release + Follow-up TODO for Delete Redaction

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a regression test that exercises the real drag-release path used for single-object moves in `objects` mode (the `_object_drag_preview_rects`-populated branch), and file a follow-up TODO to address `delete_object`'s use of `PDF_REDACT_IMAGE_REMOVE`.

**Architecture:** Extend the existing `test_object_manipulation_gui.py` sibling test with a variant that populates `_object_drag_preview_rects` (not `None`) so the multi-branch release code at `view/pdf_view.py:3565-3619` is exercised end-to-end. File-based follow-up goes into `TODOS.md`.

**Tech Stack:** pytest, PySide6 (offscreen), fitz (PyMuPDF), existing test helpers in `test_scripts/test_object_manipulation_gui.py`.

---

## Context

A bug surfaced in manual GUI testing: in `objects` mode, the blue selection overlay did not follow a moved image after release until the user clicked again. Root cause: the mouse-press path in `view/pdf_view.py:2451-2453` always populates `_object_drag_start_doc_rects` as a dict (even for single selection), so live drag and release take the "multi" branch at `pdf_view.py:2612-2623` and `pdf_view.py:3565-3586`. The committed fix at `c099b28` only updated the single-select release branch (`pdf_view.py:3588-3619`) and the browse-mode branch, leaving the real-world path unguarded.

An uncommitted fix now:
- Live drag (`pdf_view.py:~2623`): when a single selection exists, mirrors `preview_rects[sel_id]` into `_object_drag_preview_rect` and calls `_update_object_selection_visuals`.
- Release (`pdf_view.py:~3583`): after emitting `BatchMoveObjectsRequest`, rebuilds each `_selected_object_infos[id]`, updates `_selected_object_info` if matched, rebases `_object_drag_start_doc_rects`, and refreshes visuals.

The existing test `test_objects_mode_move_release_rebases_selected_object_info_immediately` (`test_object_manipulation_gui.py:335`) explicitly sets `_object_drag_preview_rects = None`, so it only covers the already-working single-select branch. We need a sibling test that forces the multi branch to protect the fix against regression.

Separately, `model/pdf_model.py:2208-2209` still runs `page.add_redact_annot(old_rect); page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)` on app-image delete — inconsistent with the new overlap-safe move/rotate path. The original plan flagged this as out-of-scope; we now formally capture it as a follow-up.

---

## Task 1: Add multi-branch release regression test

**Files:**
- Modify: `test_scripts/test_object_manipulation_gui.py` (append after line 381)

**Step 1: Write the failing test**

Append this function directly after `test_objects_mode_move_release_rebases_selected_object_info_immediately`:

```python
def test_objects_mode_move_release_rebases_when_preview_rects_populated(monkeypatch) -> None:
    """Real production path: press populates _object_drag_start_doc_rects as a dict
    (see pdf_view.py:2451), so drag-release takes the multi-branch at pdf_view.py:~3565.
    That branch must still rebase _selected_object_info, _selected_object_infos,
    _object_drag_start_doc_rects, and refresh visuals for a single selection."""
    view = _make_view()
    view.current_mode = "objects"

    original_bbox = fitz.Rect(20, 20, 120, 80)
    new_bbox = fitz.Rect(50, 50, 150, 110)

    hit = _make_object_hit(kind="image", supports_rotate=False)
    view._selected_object_info = hit
    view._selected_object_infos = {hit.object_id: hit}
    view._selected_object_page_idx = 0

    # Mid-drag state as produced by the real press + move code paths:
    view._object_drag_active = True
    view._object_drag_pending = False
    view._object_drag_start_doc_rect = fitz.Rect(original_bbox)
    view._object_drag_preview_rect = fitz.Rect(new_bbox)
    view._object_drag_start_doc_rects = {hit.object_id: fitz.Rect(original_bbox)}
    view._object_drag_preview_rects = {hit.object_id: fitz.Rect(new_bbox)}

    move_signal = _FakeSignal()
    view.sig_move_object = move_signal
    visuals_calls: list[object] = []
    view._update_object_selection_visuals = lambda rect=None: visuals_calls.append(rect)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    # A BatchMoveObjectsRequest must have been emitted once.
    assert len(move_signal.emitted) == 1

    # _selected_object_info must reflect the new rect immediately.
    updated = view._selected_object_info
    assert updated is not None, "_selected_object_info was cleared after move"
    assert abs(updated.bbox.x0 - new_bbox.x0) < 0.5
    assert abs(updated.bbox.y0 - new_bbox.y0) < 0.5
    assert abs(updated.bbox.x1 - new_bbox.x1) < 0.5
    assert abs(updated.bbox.y1 - new_bbox.y1) < 0.5

    # _selected_object_infos entry rebased too.
    infos_entry = view._selected_object_infos[hit.object_id]
    assert abs(infos_entry.bbox.x0 - new_bbox.x0) < 0.5
    assert abs(infos_entry.bbox.y1 - new_bbox.y1) < 0.5

    # Drag-start rects rebased so the next drag starts from the new position.
    rebased = view._object_drag_start_doc_rects[hit.object_id]
    assert abs(rebased.x0 - new_bbox.x0) < 0.5
    assert abs(rebased.y1 - new_bbox.y1) < 0.5

    # Visuals were refreshed on the new rect.
    assert len(visuals_calls) >= 1, "_update_object_selection_visuals not called after multi-branch move"

    # Preview-rects dict cleared so stale data doesn't leak into the next drag.
    assert getattr(view, "_object_drag_preview_rects", None) is None
```

**Step 2: Run the test to verify it passes with the uncommitted fix in place**

Run: `python -m pytest -q test_scripts/test_object_manipulation_gui.py::test_objects_mode_move_release_rebases_when_preview_rects_populated -v`

Expected: PASS (because the uncommitted `view/pdf_view.py` fix already covers this path).

**Step 3: Prove the test is a real regression guard**

Temporarily revert the uncommitted fix block (lines ~3583-3615 in `view/pdf_view.py`, the block guarded by `if moves:` that now rebases state) to just `self.sig_move_object.emit(...)` + `event.accept()`, re-run the test, and confirm it FAILS. Then restore the fix.

Expected failure output: assertion on `_selected_object_info` bbox (`x0` still 20, not 50) or `_update_object_selection_visuals not called`.

**Step 4: Run the full object-manipulation suite for no regressions**

Run: `python -m pytest -q test_scripts/test_object_manipulation_gui.py test_scripts/test_object_resize.py test_scripts/test_image_objects_model.py`

Expected: all pass.

**Step 5: Commit**

```bash
git add test_scripts/test_object_manipulation_gui.py view/pdf_view.py
git commit -m "test: lock in multi-branch release rebasing for single-object drag"
```

(Note: include `view/pdf_view.py` in the same commit because the uncommitted fix and its regression test belong together.)

---

## Task 2: File follow-up for delete's IMAGE_REMOVE redaction

**Files:**
- Modify: `TODOS.md`

**Step 1: Append a follow-up entry**

Append (or insert under the appropriate priority heading) to `TODOS.md`:

```markdown
- [ ] **Delete app-image: drop `PDF_REDACT_IMAGE_REMOVE`** (`model/pdf_model.py:2204-2213`)
  - Move/rotate were converted in commit `c099b28` to rewrite placements via
    `_rewrite_native_image_matrix`, preserving overlapping neighbors.
  - Delete still calls `page.add_redact_annot(old_rect); page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)`,
    which can remove overlapping neighbor images and is inconsistent with the new behavior.
  - Approach: reuse `_find_app_image_invocation` + a native-image "remove invocation" helper
    (parallel to `_remove_native_image_invocation` at `model/pdf_model.py:2196`) so only the
    targeted placement is stripped.
  - Add regression: two overlapping app-images, delete one, assert the other survives
    (mirror `test_move_overlapping_app_images_both_survive` in `test_scripts/test_image_objects_model.py:180`).
```

**Step 2: Commit**

```bash
git add TODOS.md
git commit -m "docs: track overlap-safe delete follow-up for app images"
```

---

## Verification

End-to-end checks after both tasks:

1. `python -m pytest -q test_scripts/test_object_manipulation_gui.py test_scripts/test_object_resize.py test_scripts/test_image_objects_model.py` — all green.
2. `ruff check test_scripts/test_object_manipulation_gui.py TODOS.md` — zero new violations (TODOS.md is not linted; ruff only applies to the test file).
3. Manual sanity (optional): run the app, drag an image in `objects` mode, confirm the blue selection box follows the image immediately on release (already verified by user).
4. `git log --oneline -2` shows the test-lock-in commit and the TODOS follow-up commit.

## Critical Files

- `view/pdf_view.py:3565-3619` — multi-branch release path being protected.
- `view/pdf_view.py:2612-2630` — live drag mirror that feeds into this path.
- `test_scripts/test_object_manipulation_gui.py:335-381` — existing sibling test; new test sits directly below.
- `model/pdf_model.py:2204-2213` — delete redaction site referenced by the follow-up.
- `TODOS.md` — where the follow-up is recorded.
