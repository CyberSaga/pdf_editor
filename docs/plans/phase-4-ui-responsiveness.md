# Phase 4 — UI-Thread Responsiveness: Implementation Plan

**Status:** IMPLEMENTED 2026-06-10 (red-light first; full gate green: 1281 passed /
21 skipped). Items: 4.1 async thumbnails (H-3), 4.2 search worker (M-1), 4.3 overlay
cache → **DEFERRED** (rationale at end; recorded in TODOS.md).

**Decisions / deviations recorded during implementation:**

1. `_next_load_gen` verified — exists exactly as named (controller:463); reused as-is.
2. **Worker signals carry a generation token** (`hits_found(gen, page, hits)`,
   `failed(gen, exc)`, `finished(gen)`) instead of the plan's bare signatures:
   search is cancel-and-restart, and queued cross-thread emissions already posted
   to the GUI event queue are still delivered after cancel — without the token,
   stale hits from the previous query would corrupt the new accumulation.
3. **Controller refs released on `thread.finished`** (`_release_search_thread`,
   identity-checked), not on `worker.finished`: clearing the Python QThread wrapper
   while the thread still ran caused a hard process crash (no traceback) in
   `test_controller_search_text_is_async` — GC destroyed the C++ QThread mid-run.
4. `_cancel_search()` additionally waits (`thread.quit()` + `wait(2000)`) and is
   also called at session-lifecycle boundaries (`_switch_to_session_id`,
   `on_tab_close_requested`, `open_pdf`): the worker resolves `model.doc`
   dynamically, so a tab switch/close swaps or closes the document under it.
5. `test_cross_page_text_move.py` restore-path assertion flipped from
   `assert thumb_calls` to `assert not thumb_calls` (text moves no longer refresh
   thumbnails — that was the point of removing the 2 call sites).
6. `test_multi_tab_plan.py::test_05_search_state_restored_per_tab` now pumps the
   event loop until results land (`_pump_until_search_results`) — it relied on
   synchronous search completing before the tab switch captured UI state.
7. `SearchTool.search_text` body now delegates to `search_page` per page —
   byte-identical result shape, no duplicated context extraction.

---

## 4.1 Thumbnails through the batch scheduler

### Verified current behavior

- `_update_thumbnails` (controller:2637–2641): renders ALL pages synchronously, then
  `view.update_thumbnails(thumbs)` which CLEARS the QListWidget and rebuilds.
- `_schedule_thumbnail_batch` (2643–2659): cancellation token = `session_id` +
  `load_gen` (checks `_load_gen_by_session.get(session_id) != gen` per tick); updates
  icons BY ROW INDEX via `view.update_thumbnail_batch(start, thumbs)` (requires items
  to already exist); chains via `QTimer.singleShot(THUMB_BATCH_INTERVAL_MS, ...)`.
- Item count is pre-established by `view.set_thumbnail_placeholders(total)` (used in
  `_render_active_session`, line 998). **Critical:** after delete/insert the widget has
  the OLD count — must call `set_thumbnail_placeholders(new_count)` before batching;
  `update_thumbnail_batch` silently `break`s on out-of-range rows.

### Verified call sites (9)

| Line | Context | affected pages available |
|---|---|---|
| 1155 | merge_ordered_sources_into_current | full doc → None |
| 1734 | delete_pages | `actual_deleted_pages` |
| 1756 | rotate_pages | `actual_rotated_pages` |
| 1794 | straighten_pages | `straightened` |
| 2315 | move_text_across_pages success | non-structural → REMOVE call |
| 2327 | move_text_across_pages restore | non-structural → REMOVE call |
| 2584 | _refresh_after_command (undo/redo structural) | `cmd.affected_pages` |
| 2935 | insert_blank_page | `actual_inserted_pages` |
| 2969 | insert_pages_from_file | `actual_inserted_pages` |

(`set_session_color_profile` at 590 already uses the batch path — no change.)

### New helper

```python
def _invalidate_thumbnails(self, affected: list[int] | None = None) -> None:
    """Schedule an async thumbnail batch from the earliest affected page."""
    sid = self.model.get_active_session_id()
    if not sid or not self.model.doc:
        return
    n = len(self.model.doc)
    # Resize widget item count BEFORE batching (insert/delete changed it).
    self.view.set_thumbnail_placeholders(n)
    start = max(0, min(affected) - 2) if affected else 0  # one page before first affected
    gen = self._next_load_gen(sid)  # cancels any in-flight batch chain
    QTimer.singleShot(0, lambda s=sid, g=gen, st=start: self._schedule_thumbnail_batch(st, s, g))
```

(Verify `_next_load_gen` exists with that name — read how open bumps the generation;
use the same mechanism.)

- Replace the 7 structural call sites per the table; REMOVE the 2 move-text calls.
- KEEP `_update_thumbnails` as a deprecated shim (docstring: no longer called by
  production code) — `test_cross_page_text_move.py:48,211` stubs it by name.
- Races: double bump of load_gen makes earlier chains exit at their gen check — same
  pattern as document open.

## 4.2 Search on a worker thread

### Verified current behavior

- `sig_search` → `search_text` (controller:2418) → `SearchTool.search_text` synchronous
  full-doc loop (model/tools/search_tool.py), per-hit `get_text(clip=..., sort=True)`.
- `view.display_search_results(results)` (pdf_view.py:4813–4832) clears + rebuilds the
  results list each call → compatible with incremental accumulate-and-replace.
- OCR worker precedent (`_OcrWorker`/`_OcrBridge`, controller ~177–295): live doc access
  from worker thread, per-page cancel flag, bridge forwards signals, deleteLater cleanup.

### Changes

1. `model/tools/search_tool.py`: add `search_page(self, page_num: int, query: str) ->
   list[tuple[int, str, object]]` (bounds-checked; same context extraction as
   search_text). KEEP `search_text` unchanged (test_tool_extensions.py calls it).
2. `controller/pdf_controller.py` after `_OcrBridge`: `_SearchWorker(QObject)` with
   `hits_found = Signal(int, list)`, `finished`, `failed`; ctor takes (tool, query,
   total_pages); `run()` iterates pages 1..N, checks `_cancel_requested` per page,
   emits hits per page with results; `_SearchBridge(QObject)` forwarding all three.
3. Controller `__init__`: `_search_thread/_search_worker/_search_worker_bridge/_search_accumulated_hits`.
   `activate()`: build bridge + connect `_on_search_hits_found`/`_on_search_failed`/`_on_search_thread_finished`.
4. `search_text(query)` rewritten async: `_cancel_search()` first; empty query/no doc →
   `display_search_results([])` + session search_state reset; else accumulate hits per
   page → `display_search_results(list(accumulated))`; on thread finish persist
   `search_state = {"query", "results", "index": -1}` into `_get_ui_state(sid)`.
   Standard lifecycle: `worker.finished→thread.quit`, `worker.finished→worker.deleteLater`,
   `thread.finished→thread.deleteLater`.
5. `_cancel_search()` called at top of every doc-mutating method: delete_pages,
   rotate_pages, straighten_pages, insert_blank_page, insert_pages_from_file,
   merge_ordered_sources_into_current, undo, redo (fitz doc is not safe for concurrent
   read-during-mutation).

IMPORTANT: study how the CURRENT synchronous `search_text` updates the view + session
state and preserve exact result-tuple shape `(page_num, context, rect)` so
`display_search_results` and result-navigation keep working.

## 4.3 Overlay render cache — DEFERRED

Requires revision counters across WatermarkTool AND AnnotationTool plus cache state on
stateless ToolManager; overlay path only active when overlays exist. Non-blocking per
the master plan. Record as TODO.

---

## Red-light tests (write FIRST)

New `test_scripts/test_thumbnail_async.py` (mirror existing controller-test fixtures):
- `test_invalidate_thumbnails_uses_set_placeholders_not_update`
- `test_invalidate_thumbnails_schedules_batch_with_correct_start_affected`
  (affected=[5,3,7] → start index 1)
- `test_invalidate_thumbnails_full_rebuild_starts_at_zero`
- `test_invalidate_thumbnails_cancels_previous_batch` (load_gen bumped twice)
- `test_update_thumbnails_no_longer_called_by_delete_pages`
- `test_invalidate_thumbnails_called_from_refresh_after_command_structural`

New `test_scripts/test_search_worker_flow.py` (mirror `test_ocr_controller_flow.py`
patterns — `_drive_worker`, minimal controller, wait helpers):
- `test_search_worker_emits_hits_found_per_page`
- `test_search_worker_runs_on_non_gui_thread`
- `test_search_worker_respects_cancel`
- `test_search_worker_emits_failed_on_tool_exception`
- `test_search_bridge_forwards_signals`
- `test_controller_search_text_is_async`
- `test_controller_search_text_accumulates_hits`
- `test_controller_search_text_cancel_previous`

In `test_tool_extensions.py`: `test_search_tool_search_page` (hit / no-match / out-of-bounds).

All fail before implementation (methods/classes don't exist; call sites still synchronous).

## Verification

```powershell
python -m pytest test_scripts/test_thumbnail_async.py test_scripts/test_search_worker_flow.py -v --tb=short
python -m pytest test_scripts/test_ocr_controller_flow.py test_scripts/test_tool_extensions.py test_scripts/test_cross_page_text_move.py -q --tb=short
python -m ruff check controller/pdf_controller.py model/tools/search_tool.py
python -m pytest test_scripts -q --tb=line -p no:cacheprovider   # full gate
```

## Docs (same commit)

- PITFALLS: (1) batch scheduler requires pre-set widget item count
  (set_thumbnail_placeholders before batching); (2) search worker must be cancelled
  before any document mutation (fitz not safe for concurrent read/write).
- ARCHITECTURE: thumbnail invalidation flow + search worker/bridge pattern notes.
- TODOS: Phase 4 done; add deferred 4.3 overlay-cache item.

## Commit

`feat(phase-4): async thumbnail batching + search worker (H-3, M-1)` — body per plan;
end with Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
