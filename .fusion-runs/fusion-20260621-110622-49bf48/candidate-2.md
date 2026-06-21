### A) Verification of `set[bytes]` Budget Undercount
*   **Status**: Verified.
*   **Exact Lines**: [model/edit_commands.py:L643-652](file:///model/edit_commands.py#L643-L652)
*   **Trigger**: Changing `seen: set[int] = set()` (tracking object IDs) to `seen: set[bytes] = set()` (tracking content equality).
*   **Causality**: Python compares `bytes` objects by value/content rather than object identity. If the undo stack contains multiple non-adjacent command snapshots that represent identical document states or identical chunks, they will be stored in memory as distinct `bytes` allocations. However, because their byte contents are identical, `chunk not in seen` will evaluate to `False` for all but the first occurrence. The memory calculation will only count the size of one chunk, even though all of them remain resident in `self._undo_stack` and occupy RAM. This undercounts the actual resident memory footprint of the undo stack, allowing it to grow past the configured budget and potentially trigger Out-Of-Memory (OOM) crashes.
*   **Severity**: High
*   **Confidence**: High

---

### B) Verification of Thumbnail Signal/Generation Tab Switch Collision
*   **Status**: Verified.
*   **Exact Lines**: 
    *   [controller/thumbnail_coordinator.py:L53](file:///controller/thumbnail_coordinator.py#L53) (`batch_ready = Signal(int, int, list)`)
    *   [controller/thumbnail_coordinator.py:L228-239](file:///controller/thumbnail_coordinator.py#L228-L239) (`_on_batch_ready` slot)
*   **Trigger**: The `batch_ready` signal emitted by `_ThumbnailWorker` does not include a `session_id` parameter.
*   **Causality**: When a tab switch occurs, `try_start` is invoked for the new session. This updates the coordinator's `self._session_id` to the new session ID and spins up a new worker thread. However, the background thread for the previous session might still be running or have pending `batch_ready` signals queued in the Qt event loop. When the GUI thread processes these stale queued signals, it executes `_on_batch_ready`. Inside `_on_batch_ready`, `self._session_id` is compared, but it has already been updated to the new session. The code checks if the generation number `gen` matches the active session's generation number (`self._c._thumb_gen_by_session.get(sid)`). Since generation counters are session-scoped and start at the same initial value (typically `0` or `1`), these numbers can easily collide after a tab switch. If they collide, the stale thumbnails from the old session are painted onto the new session's view.
*   **Severity**: High
*   **Confidence**: High

---

### Other Severe Defects Found

#### 1. Unsafe Deletion of `_ThumbnailWorker` from GUI Thread (Thread Affinity Violation)
*   **Exact Lines**: [controller/thumbnail_coordinator.py:L188-201](file:///controller/thumbnail_coordinator.py#L188-L201)
*   **Trigger**: `worker.finished.connect(thread.quit)`, `worker.finished.connect(worker.deleteLater)`, and the reference clearing inside `_release`.
*   **Causality**: The `worker` is moved to the background thread via `worker.moveToThread(thread)`. While `worker.deleteLater()` is called to delete it on the background thread's event loop, `thread.quit()` is invoked concurrently. This causes the background thread's event loop to terminate immediately, potentially before the deferred delete event for the `worker` is processed. When the thread finished, `_release` is invoked, setting `self._worker = None`. Because the `worker` has no C++ parent and no remaining Python references, Python GC immediately destroys the wrapper and attempts to delete the C++ `_ThumbnailWorker` object from the GUI thread. Deleting a `QObject` from a thread other than the one it has affinity with violates Qt's thread-safety constraints, leading to runtime warnings (`QObject: Cannot delete object created in a different thread`) and sporadic process crashes.
*   **Severity**: Medium-High
*   **Confidence**: High

#### 2. Potential Memory Corruption / Use-After-Free in `QImage` Conversion
*   **Exact Lines**: [controller/thumbnail_coordinator.py:L104-106](file:///controller/thumbnail_coordinator.py#L104-L106)
*   **Trigger**: Passing local `fitz.Pixmap` (`pix`) to `pixmap_to_qimage(pix)`.
*   **Causality**: In PyMuPDF, `Pixmap.samples` returns a pointer to the raw pixel buffer. If `pixmap_to_qimage` initializes the `QImage` using this buffer without performing a deep copy (e.g., via `QImage(pix.samples, ...)` without calling `.copy()`), the `QImage` objects in the `images` list will only hold a reference to memory owned by the local `pix` object. In `_ThumbnailWorker.run`, `pix` is a local variable that is overwritten at the end of each iteration of the inner loop and freed entirely when the function finishes (via `doc.close()`). Thus, the `QImage` objects sent to the GUI thread will wrap dangling pointers. When the GUI thread attempts to read from them via `QPixmap.fromImage(img)` to paint them, it reads garbage data or crashes with a segmentation fault.
*   **Severity**: High
*   **Confidence**: High