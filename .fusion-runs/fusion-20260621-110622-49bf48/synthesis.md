**Findings**

1. `model/edit_commands.py:643-652` verifies A.
   Trigger: `_undo_stack` contains two distinct resident `bytes` objects with identical contents.
   Causality: the new `seen: set[bytes]` dedupes by value, not identity, so `if chunk not in seen` counts only the first equal-content buffer even though both allocations remain resident. This undercounts the undo memory budget and delays eviction.
   Severity: Medium. It can become serious with large PDFs, but OOM is an extrapolation beyond this diff.
   Confidence: High.

2. `controller/thumbnail_coordinator.py:53-54`, `controller/thumbnail_coordinator.py:204`, `controller/thumbnail_coordinator.py:228-239` verify B.
   Trigger: an old async thumbnail worker has a late or queued `batch_ready` after a tab switch/new async rebuild, and the new session’s per-session generation equals the old worker’s `gen`.
   Causality: worker signals carry `gen` but not `session_id`; `try_start()` overwrites `self._session_id` with the new session; `_on_batch_ready()` validates against that mutable coordinator state plus `_thumb_gen_by_session[sid]`. Since generations are per-session, a collision lets stale thumbnails from the old session paint into the active tab.
   Severity: High.
   Confidence: High.

3. `controller/thumbnail_coordinator.py:214-224` is an additional likely defect.
   Trigger: `cancel()` during an in-flight worker, such as tab switch or starting a replacement async thumbnail rebuild.
   Causality: it clears `self._worker` and `self._thread` before `thread.finished`, despite the file’s own lifecycle rule that refs should be dropped only after thread completion. If those are the last Python references while the worker object still has worker-thread affinity or queued signals, PySide/Qt lifetime behavior can become unsafe.
   Severity: Medium-High.
   Confidence: Medium, because exact crashability depends on PySide ownership/deferred-delete behavior.

Rejected: style/comment concerns, threshold choices, and the claimed `QImage` lifetime crash. The `QImage` issue depends on `pixmap_to_qimage()` internals outside this compact diff, so it is only a follow-up check, not a proven changed-line defect.