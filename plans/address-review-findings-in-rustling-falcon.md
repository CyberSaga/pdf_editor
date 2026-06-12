# Plan: Address 2-Round Audit Findings (2026-06-10)

## Context

Two-round audit (codebase audit + defensive-programming review) produced 15 items across 6
phases. This plan addresses them in dependency order:

> gate (Phase 0) → visible bug (1) → chokepoint guards (2) → memory budgets (3) →
> UI-thread responsiveness (4) → hygiene (5)

Each phase is independently shippable with one atomic commit.

**Execution model per phase:**
1. Claude Sonnet 4.6 (high) writes a scoped sub-plan for that phase.
2. Fable 5 (high) implements all changes and makes one atomic commit.
3. Run `pytest test_scripts` before advancing to the next phase.

---

## Phase 0 — Restore the Gate

**Goal:** Eliminate 7 order-dependent failures in `test_no_jump_editor_geometry.py`
(42.91% pixel diff vs 1% threshold; same file passes in isolation).

**Root cause:** `_install_rawdict_text_compat()` (pdf_model.py:151) patches
`fitz.Page.get_text` at module-import time. `test_tool_extensions.py` then calls it
again *and* uses `monkeypatch.setattr` on the same method. When the full suite runs in
alphabetical order the monkeypatch leaks into later tests and corrupts render fidelity.

**Steps:**
1. Confirm polluter: run `pytest test_scripts --stepwise` or half-split (split suite
   before/after `test_tool_extensions.py`) to pin exact file.
2. Fix isolation: add a session-scoped `conftest.py` autouse fixture that captures the
   original `fitz.Page.get_text` *before* any test runs and restores it after any test
   that replaces it. The sentinel in pdf_model.py:121–123 prevents double-install on
   model import; the fixture closes the monkeypatch escape hatch.
3. Verify the existing sentinel (`_pdf_editor_rawdict_text_compat`) is still checked so
   repeated `_install_rawdict_text_compat()` calls are idempotent.

**Critical files:**
- `model/pdf_model.py:113–151` (`_install_rawdict_text_compat`, sentinel)
- `test_scripts/test_tool_extensions.py` (re-calls the compat installer)
- `test_scripts/test_text_selection.py` (monkeypatches get_text)
- `test_scripts/conftest.py` (create/update autouse fixture)

**Gate:** `pytest test_scripts` → 0 failures (was 7).

---

## Phase 1 — Linearize Capability Gate + Error Wrapping

**Goal:** Fix the screenshot bug
`"最佳化 PDF 失敗: 最佳化 PDF 失敗: code=4: Linearisation is no longer supported"`.

**Root cause (from exploration):**
- `pdf_optimizer.py:769`: when pikepdf absent AND linearize requested, falls back to
  `working_doc.save(linear=int(bool(options.linearize)))` — PyMuPDF 1.24+ removed this
  option, so it always raises code=4. The fallback is dead code.
- `pdf_optimizer.py:844`: wraps exception as `RuntimeError("最佳化 PDF 失敗: {e}")`.
- `controller/pdf_controller.py:1325`: adds the prefix again →
  `"最佳化 PDF 失敗: 最佳化 PDF 失敗: …"`.

**Changes:**

1.1 `model/pdf_optimizer.py`
- Add `optimize_capabilities() -> dict[str, bool]` (pattern: line 3200 of pdf_model.py
  `_can_use_parallel_image_rewrite`). Returns `{"linearize": bool, "object_streams": bool}`
  keyed by `_pikepdf() is not None`.
- Delete the `pikepdf-absent` fallback block at lines 769–781. Replace with an early
  domain error: `raise PdfOptimizeError("linearize requires pikepdf")` before any work.
- Remove the `RuntimeError(f"最佳化 PDF 失敗: {e}")` wrap at line 844 — model raises bare
  domain exception only.

1.2 `model/pdf_model.py`
- Add thin delegation wrapper `optimize_capabilities() -> dict[str, bool]` (mirrors
  `_can_use_parallel_image_rewrite` at line 3200).

1.3 `view/dialogs/optimize.py:120`
- Receive capabilities dict (passed from controller on dialog construction); disable
  `linearize_checkbox` with a tooltip when `capabilities["linearize"]` is False.

1.4 `controller/pdf_controller.py:1325`
- Keep `"最佳化 PDF 失敗: %s"` (lazy `%s`, not f-string); model no longer adds the prefix.

1.5 Environment: `pip install pikepdf` into `.venv`; add to dependency spec (pre-empts
Phase 5.1).

**Critical files:**
- `model/pdf_optimizer.py:763–784,844`
- `model/pdf_model.py:3200` (capability pattern to replicate)
- `view/dialogs/optimize.py:120`
- `controller/pdf_controller.py:1325`

**Gate:** `pytest test_scripts -k optimize`; linearize checkbox greys out when pikepdf
absent.

---

## Phase 2 — Chokepoint Guards (OOM / Logic-Bypass)

Six items sharing one pattern: guard once at the chokepoint, not per call-site.

**2.1 Central render-scale clamp**
- `model/tools/manager.py:71`: import `_safe_render_scale` from `model.pdf_model`;
  call `scale = _safe_render_scale(page, scale)` before `fitz.Matrix(scale, scale)`.
  Every consumer (view, thumbnails, print preview) now inherits the cap.
- `controller/pdf_controller.py:784–788 (_render_scale_for_quality)`: no change needed
  once manager owns the clamp.

**2.2 One shared zoom-limit constant**
- `view/pdf_view.py`: define `_MAX_VIEW_ZOOM = 4.0` and `_MIN_VIEW_ZOOM = 0.1`.
- Apply to wheel zoom line 2677 (`self.scale = max(_MIN_VIEW_ZOOM, min(_MAX_VIEW_ZOOM, self.scale * factor))`),
  pinch line 3601 (already clamps 0.1–4.0 — replace magic literals with constants),
  zoom combo line 1351 (already clamps 10–400% — keep but use the same float constants).

**2.3 Foreign-document open guard**
- `model/pdf_model.py`: extract `_guard_before_open(path)` (line 94) into a richer
  `_guard_foreign_doc(path: Path) -> fitz.Document` that: checks size (`_MAX_PDF_BYTES`),
  opens with `fitz.open`, checks page count (`_MAX_PAGES`), handles encrypted docs.
- Route `insert_pages_from_file:1383` and `headless_merge.py:24` through
  `_guard_foreign_doc`.
- Add post-merge invariant: assert `len(self.doc) + len(source) <= _MAX_PAGES` before
  insert.
- Replace per-page `insert_pdf` loop in `insert_pages_from_file` with one
  `insert_pdf(from_page, to_page)` call for contiguous runs.

**2.4 Page-number validation helper for annotation tool**
- `model/tools/annotation_tool.py`: extract the guard already in `add_annotation:68`
  (`if not self._model.doc or page_num < 1 or page_num > len(self._model.doc): raise ValueError`) 
  into `_require_page(page_num) -> fitz.Page`.
- Call it in `add_highlight:31` and `add_rect:47`.

**2.5 Watermark sanitization chokepoint**
- `model/tools/watermark_tool.py:_coerce_wm`:
  - Add `import math` at top of file.
  - Replace `result["color"] = tuple(wm["color"])` with validation: must be len==3,
    all values `math.isfinite`, clamped `[0.0, 1.0]`.
  - Add `_finite(v, lo, hi, default)` helper using `math.isfinite`; apply to
    `offset_x`, `offset_y`, `line_spacing` with bounds `(-10000, 10000)` and `(0.8, 3.0)`.
  - Funnel `add_watermark` and `update_watermark` through `_coerce_wm` so all three
    entry points share one policy.

**2.6 Single-instance argv filter**
- `utils/single_instance.py:_forwarded_argv_is_acceptable:103`: resolve ALL tokens
  (not just absolute) via `Path(item).resolve()` before the `.pdf`/`.exists()` check.
  Relative tokens currently pass unchecked; resolving first closes the bypass.

**Critical files:**
- `model/tools/manager.py:71`
- `view/pdf_view.py:2677,3601,1351`
- `model/pdf_model.py:94` (`_guard_before_open` → `_guard_foreign_doc`)
- `model/headless_merge.py:24`
- `model/tools/annotation_tool.py:31,47,67`
- `model/tools/watermark_tool.py:27–54,113–208`
- `utils/single_instance.py:99–114`

**Gate:** `pytest test_scripts`; confirm opening a PDF with page 0 raises ValueError.

---

## Phase 3 — Memory Budgets

**3.1 Undo snapshot byte budget + dedup**
- `model/edit_commands.py`:
  - Add `MAX_UNDO_STACK_BYTES = 512 * 1024 * 1024` alongside `MAX_UNDO_STACK_SIZE = 100`.
  - Add `_byte_size(self) -> int` to `SnapshotCommand`: `len(before_bytes) + len(after_bytes)`.
  - In the undo stack manager (wherever `MAX_UNDO_STACK_SIZE` eviction happens): evict
    oldest when `sum(cmd._byte_size() for cmd in stack) > MAX_UNDO_STACK_BYTES`.
  - Adjacent dedup: when command N is pushed, if `stack[-1].after_bytes is stack[-1].after_bytes == new_cmd.before_bytes` (identity or equality), share the bytes object — Python's immutable bytes can be shared with no copy.

**3.2 Print snapshot to temp file**
- `model/tools/manager.py:build_print_snapshot`: change to
  `build_print_snapshot(self, dest: Path) -> None`; write directly to `dest` via
  `tmp_doc.save(str(dest), garbage=0)` instead of `io.BytesIO`.
- `src/printing/dispatcher.py:106`: create `NamedTemporaryFile` first, pass its path to
  `build_print_snapshot(dest)`, then hand the path to `print_pdf_file` — eliminates the
  in-memory copy (today bytes live in RAM *and* on disk simultaneously).

**Critical files:**
- `model/edit_commands.py:285,396`
- `model/tools/manager.py:91–117`
- `src/printing/dispatcher.py:106–115`

**Gate:** `pytest test_scripts`; printing smoke test.

---

## Phase 4 — UI-Thread Responsiveness

**4.1 Thumbnails through batch scheduler at all call sites**
- `controller/pdf_controller.py`: introduce helper
  `_invalidate_thumbnails(affected: list[int] | None = None)` that resolves the current
  `session_id` + `load_gen` and calls `_schedule_thumbnail_batch` starting at
  `min(affected) - 1` (or 0 for full rebuild).
- Replace all 9 `_update_thumbnails()` call sites with `_invalidate_thumbnails(...)`.
  For structural ops (delete/rotate/insert), pass the `cmd.affected_pages` range.
- Keep `_update_thumbnails` for any legitimate synchronous path but remove it from
  undo/redo and all interactive call sites.

**4.2 Search on a worker thread**
- Mirror `_OcrWorker/_OcrBridge` pattern (controller/pdf_controller.py:177–295):
  - `_SearchWorker(QObject)`: takes `SearchTool` + `query`; emits `hits_found(int, list)`
    per page (page_num, hits), `finished`, `failed`; checks `_cancel_requested` per
    page iteration (cooperative cancel on new query).
  - `_SearchBridge(QObject)`: forwards all signals across thread boundary.
  - Update `search_text(query)` in controller: cancel any running `_search_thread`,
    start new `QThread + _SearchWorker`; accumulate incremental hits in UI.
- `sig_search` (connected at controller line 419) wires to the new async `search_text`.

**4.3 (Low priority) Overlay render cache**
- `model/tools/manager.py:78–89`: cache the overlaid temp page keyed by
  `(page_num, watermark_revision)` where revision is a counter incremented by any
  watermark mutation. Land only if time allows; not a blocking item.

**Critical files:**
- `controller/pdf_controller.py:2631,2578,1155,1728,1750,1788,2309,2321,2929,2963`
  (all `_update_thumbnails` call sites)
- `controller/pdf_controller.py:2412,419` (search wiring)
- `model/tools/manager.py:78–89` (overlay cache, low)

**Gate:** `pytest test_scripts`; manual search on a 100+-page PDF should not block UI.

---

## Phase 5 — Hygiene / Documentation

**5.1 pyproject.toml reconciliation**
- Create `pyproject.toml` in repo root with `[project]`, `[project.optional-dependencies]`
  (dev group: ruff, mypy, pytest, pikepdf), `[tool.ruff]`, `[tool.mypy]` sections matching
  CLAUDE.md §3.1.
- Verify `pip install -e ".[dev]"` succeeds and `ruff check .` passes.

**5.2 Document cooperative OCR cancellation in PITFALLS**
- Add entry to `docs/PITFALLS.md`:
  ```
  ## Cooperative OCR cancellation: per-page only
  Area: controller/pdf_controller.py _OcrWorker
  Symptom: Cancel appears to hang during a long page
  Cause: request_cancel() is checked between pages, not inside a single fitz call
  Fix: Accepted design. A slow page completes before cancel takes effect.
  File: controller/pdf_controller.py:241-262
  ```

**Critical files:** `pyproject.toml` (create), `docs/PITFALLS.md`

**Gate:** `pip install -e ".[dev]"`; `ruff check .` zero violations.

---

## Verification Commands

```bash
# After every phase:
pytest test_scripts                         # no regressions
ruff check .                                # zero new violations

# Phase 0 target:
pytest test_scripts                         # was 7 failures → 0

# Phase 1 target:
pytest test_scripts -k optimize

# After Phase 5:
pip install -e ".[dev]"
mypy model/ utils/
```
