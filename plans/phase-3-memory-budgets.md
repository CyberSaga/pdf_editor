# Phase 3 — Memory Budgets: Implementation Plan

**Status:** DONE (implemented 2026-06-10). Two items: 3.1 undo byte budget + dedup
(H-4), 3.2 print snapshot to temp path (M-6). Red-light confirmed (AttributeError for
`MAX_UNDO_STACK_BYTES`/`_byte_size`, AssertionError for dedup sharing, TypeError ×2 for
the new `build_print_snapshot(dest)` signature) before implementation; focused suite
14/14 green; full gate 1266 passed / 21 skipped / 0 failed.
Decision recorded: `PDFModel.capture_print_input_pdf_bytes` was REMOVED — after the
controller/test updates a repo-wide grep found zero remaining code callers (only
docs/report mentions), so it was dead code exclusive to the print path.

---

## 3.1 Undo snapshot byte budget + dedup (`model/edit_commands.py`)

### Verified current structure

Command classes: `EditCommand` (abstract, line 28), `EditTextCommand` (line 60, one
`_page_snapshot_bytes`), `AddTextboxCommand` (line 223, `_before_page_snapshot_bytes` +
lazy `_after_page_snapshot_bytes | None`), `SnapshotCommand` (line 285, `_before_bytes` +
`_after_bytes` full-doc serializations — the memory-critical class).

`CommandManager` (line 374): `MAX_UNDO_STACK_SIZE = 100` (line 396).
`_trim_undo_stack_if_needed()` (line 551) evicts by COUNT only and decrements
`_saved_stack_size` by the overflow. Push sites that append + trim: `execute()` (424),
`record()` (453), `redo()` (508). `_redo_stack` is cleared on every new execute/record
(verified lines 428–432, 455–459) → byte budget applies to the undo stack only.

Bytes-sharing safety: `bytes` immutable; `_restore_doc_from_snapshot` (pdf_model.py:3272)
does `fitz.open("pdf", snapshot_bytes)` which copies internally. Nothing mutates buffers.

### Changes

1. Constant beside the count cap: `MAX_UNDO_STACK_BYTES = 512 * 1024 * 1024  # 512 MiB`.
2. `_byte_size()` on the base class (default 0, docstring) + overrides:
   - `EditTextCommand`: `len(self._page_snapshot_bytes)`
   - `AddTextboxCommand`: before + (after if not None else 0)
   - `SnapshotCommand`: `len(self._before_bytes) + len(self._after_bytes)`
3. `_trim_undo_stack_if_needed()`: keep count-cap pass, then byte-budget pass — evict
   oldest while `sum(cmd._byte_size())` > budget; decrement `_saved_stack_size` per
   evicted entry (clamp 0); lazy-`%s` debug logs.
4. `_dedup_top_snapshot_pair()` helper: if top two entries are both `SnapshotCommand`
   and `prev._after_bytes is curr._before_bytes` → return; elif `==` → assign
   `curr._before_bytes = prev._after_bytes` (identity share). Call it right after
   `append(cmd)` in ALL THREE push sites (execute/record/redo), before trim.

## 3.2 Print snapshot to temp path

### Verified call graph (differs from the audit's guess!)

- `ToolManager.build_print_snapshot()` (manager.py:91–117) → bytes via io.BytesIO
  (overlay path) or `model._capture_doc_snapshot()` (fast path — ALSO BytesIO,
  pdf_model.py:3138–3140).
- `PDFModel.build_print_snapshot` (pdf_model.py:1531) is a thin wrapper — and is NOT on
  the live print path. The live path is:
  `_start_print_submission` (controller:1529) → `PrintJobRequest(capture_pdf_bytes=
  model.capture_print_input_pdf_bytes, ...)` (1543) → `_PrintSubmissionWorker.run()`
  (controller:132–149, runs on QThread): `pdf_bytes = capture_pdf_bytes();
  input_pdf_path.write_bytes(pdf_bytes)` — THIS is the in-memory peak.
- `dispatcher.print_pdf_bytes` (dispatcher.py:106–117) is only used by the print-helper
  SUBPROCESS (`helper_main._build_snapshot_bytes`) — leave dispatcher.py unchanged.

### Changes

1. `ToolManager.build_print_snapshot(self, dest: Path) -> None` (signature change; no
   live bytes callers):
   - fast path (no overlay): `self._model.doc.save(str(dest), garbage=0,
     encryption=fitz.PDF_ENCRYPT_KEEP)`
   - overlay path: build tmp_doc as today, `tmp_doc.save(str(dest), garbage=0)` in
     try/finally close. Remove `import io` from manager.py if unused elsewhere; add
     `from pathlib import Path`.
2. `PDFModel.build_print_snapshot(self, dest: Path) -> None` wrapper updated.
3. `controller/pdf_controller.py`: `PrintJobRequest.capture_pdf_bytes:
   Callable[[], bytes]` → `write_pdf_to: Callable[[Path], None]` (frozen dataclass field
   rename); `_start_print_submission` passes `write_pdf_to=self.model.build_print_snapshot`;
   `_PrintSubmissionWorker.run()` calls `self._request.write_pdf_to(input_pdf_path)`
   instead of capture+write_bytes.
4. Test impact: `test_print_controller_flow.py` — line ~224 guard monkeypatches
   `model.build_print_snapshot` (assert not called before accept — still valid, update
   patch signature); line ~301 background test monkeypatches
   `capture_print_input_pdf_bytes` — must be updated to patch `build_print_snapshot`.
   Check whether `capture_print_input_pdf_bytes` (pdf_model.py:1534–1535) retains any
   callers after the change; if none, keep it (public API) but note it in ARCHITECTURE,
   or remove it if it was only used by the print path (implementer judgement: prefer
   removing dead code if no other references).

## Red-light tests (write FIRST, confirm failure)

New file `test_scripts/test_undo_memory_budget.py`:
- `test_byte_budget_evicts_oldest_snapshot_commands` — monkeypatch
  `CommandManager.MAX_UNDO_STACK_BYTES` small (e.g. 300 KiB), record 3 SnapshotCommands
  of ~160 KiB each (FakeModel with `_restore_doc_from_snapshot`/`refresh_structural_indexes`
  no-ops); assert oldest evicted. FAILS now: count-only trim keeps all.
- `test_adjacent_dedup_shares_bytes_object` — two SnapshotCommands where
  `cmd1.after == cmd2.before` (equal content, distinct objects); after record(),
  assert `stack[-2]._after_bytes is stack[-1]._before_bytes`. FAILS now.
- `test_dedup_does_not_corrupt_undo_redo` — real PDFModel, two structural ops, undo×2 /
  redo×2 round-trip page count.
- `test_byte_size_returns_correct_values` — per-class `_byte_size()` values; base = 0.
  FAILS now: AttributeError.

New file `test_scripts/test_print_snapshot_path.py`:
- `test_build_print_snapshot_writes_valid_pdf_to_dest` — `m.build_print_snapshot(dest)`;
  dest exists, opens with fitz, text preserved. FAILS now: TypeError (old signature
  takes no args).
- `test_build_print_snapshot_overlay_path_writes_to_dest` — monkeypatch one extension's
  `needs_page_overlay` (True for purpose=="print") + no-op `apply_page_overlay`;
  assert dest valid. FAILS now: TypeError.

Regression: `test_unified_undo.py`, `test_snapshot_restore.py`,
`test_print_controller_flow.py`, `test_security_dispatcher_temp_cleanup.py`.

## Verification

```powershell
python -m ruff check model/edit_commands.py model/tools/manager.py model/pdf_model.py controller/pdf_controller.py test_scripts/test_undo_memory_budget.py test_scripts/test_print_snapshot_path.py
python -m pytest test_scripts/test_undo_memory_budget.py test_scripts/test_print_snapshot_path.py test_scripts/test_unified_undo.py test_scripts/test_snapshot_restore.py test_scripts/test_print_controller_flow.py test_scripts/test_security_dispatcher_temp_cleanup.py -v --tb=short
python -m pytest test_scripts -q --tb=line -p no:cacheprovider   # full gate
```

## Docs (same commit)

- PITFALLS: (1) byte-budget eviction must decrement `_saved_stack_size` or
  has_pending_changes drifts; (2) dedup only safe for SnapshotCommand pairs (full-doc,
  immutable bytes); (3) build_print_snapshot signature changed () -> bytes ⇒
  (dest: Path) -> None — callers updated.
- ARCHITECTURE: snapshot API note for `build_print_snapshot(dest)`; byte budget on
  CommandManager.
- TODOS: mark Phase 3 done.

## Commit

`fix(memory): enforce 512 MiB undo byte budget + dedup adjacent snapshots; print snapshot writes to temp path directly` — body per plan; end with
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
