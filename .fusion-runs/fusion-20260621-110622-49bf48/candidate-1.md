### Analysis of Defect A: `set[bytes]` Budget Undercounts Equal Distinct Resident Buffers

*   **Status**: **Verified**
*   **Exact Lines**: `model/edit_commands.py` (lines 643-652):
    ```python
            seen: set[bytes] = set()
            total = 0
            for cmd in self._undo_stack:
                for chunk in cmd._snapshot_chunks():
                    if chunk not in seen:
                        seen.add(chunk)
                        total += len(chunk)
    ```
*   **Trigger**: Multiple commands in the undo stack contain separate, distinct `bytes` buffer allocations (non-adjacent in memory) that happen to contain identical byte sequences (e.g., reverting to a prior document state).
*   **Causality**: A Python `set` of `bytes` deduplicates elements by content equality (`__eq__` and `__hash__`) rather than object identity (`id()`). If two distinct `bytes` instances containing identical data reside in the undo stack, they are treated as a single element by `seen.add(chunk)`. Consequently, `total` only counts the size of one buffer, even though both separate allocations remain fully resident in memory.
*   **Severity**: **Medium** (causes the command manager to underestimate its true memory footprint, delaying the pruning of the undo stack and leading to unexpected memory usage/bloat).
*   **Confidence**: **High**

---

### Analysis of Defect B: Thumbnail Signals Omit Session ID & Generation Collision After Tab Switch

*   **Status**: **Verified**
*   **Exact Lines**: 
    *   `controller/thumbnail_coordinator.py` (lines 53-54, signal declarations):
        ```python
        batch_ready = Signal(int, int, list)  # gen, start_index, list[QImage]
        finished = Signal(int)  # gen
        ```
    *   `controller/thumbnail_coordinator.py` (lines 227-238, receiver slot):
        ```python
        @Slot(int, int, list)
        def _on_batch_ready(self, gen: int, start_index: int, images) -> None:
            sid = self._session_id
            if sid is None or self._c.model.get_active_session_id() != sid:
                return
            if self._c._thumb_gen_by_session.get(sid) != gen:
                return
            pixmaps = [QPixmap.fromImage(img) for img in images]
            self._c.view.update_thumbnail_batch(start_index, pixmaps)
```
*   **Trigger**: A tab switch occurs while an asynchronous thumbnail worker is still executing on the background thread. The newly active session has its own generation token (e.g., `gen = 1`) that happens to match the generation token of the old, running background worker (e.g., `gen = 1`).
*   **Causality**: 
    1. The worker's `batch_ready` signal does not convey the originating `session_id`.
    2. When the tab switches, `try_start` calls `self.cancel()` which calls `thread.quit()`, but the thread running the worker loop does not terminate instantly. `try_start` then overwrites `self._session_id` to the *new* session's ID.
    3. The old running worker finishes a batch and emits `batch_ready(gen=1, ...)`.
    4. `_on_batch_ready` is invoked. It reads the updated `self._session_id` (the new session). The active session matches this new ID.
    5. It checks if the new session's generation equals the signal's `gen`. Because generations start/increment independently per session, both are `1`, causing the validation check to pass.
    6. The old session's thumbnails are rendered and painted onto the new session's thumbnail container, causing visual corruption.
*   **Severity**: **High** (causes silent visual corruption and race conditions where incorrect thumbnails are shown on the wrong tabs).
*   **Confidence**: **High**