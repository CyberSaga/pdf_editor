# Implementation Report — Audit Remediation Phases 1–7 (2026-06-12)

## Executive Summary

Completed remediation of 15 confirmed/plausible findings from two code reviews (Codex adversarial + `/code-review xhigh`) across 7 ordered phases. All findings resolved, test suite green (1302 passed, 0 failures), production regressions eliminated, and architectural safeguards established via chokepoint guards and snapshot isolation.

**Commits:**
- `4d0d6ea` — Phases 1–2: Search/print workers snapshot isolation, watermark double-stamp fix
- `0f49673` — Phase 3: OCR worker snapshot isolation + gen-tokened signals
- `065bb62` — Phases 4–7: Thumbnail invalidation, undo budget floor+dedup, QSS padding, render clamp module, page bounds guard, wheel zoom, IPC hygiene, native objstms
- `c74b98a` — Deferred items documented in TODOS.md

## Phase-by-Phase Details

### Phase 1 — Search worker snapshot isolation (Finding #2, #6, #7, #10)

**Problem:** Search worker read the live `fitz.Document` while 11 controller mutation paths (highlight, rect, edit text, move/rotate/delete/resize objects, image, textbox, annotation, OCR page_done) never cancelled it. Concurrent mutations could cause crashes, stale hits, or wrong-doc pollution.

**Solution:**
- New `PDFModel.capture_worker_snapshot_bytes()` serializes document bytes with `encryption=fitz.PDF_ENCRYPT_NONE` (safe; bytes never leave process) on GUI thread before worker launch
- `search_text()` captures snapshot before `thread.start()`, worker opens a private doc from snapshot bytes in `_SearchWorker.run()`
- `_cancel_search()` is non-blocking (bumps gen token, calls `thread.quit()`, no `thread.wait()`); overlapping workers are safe
- Lifecycle fix: tab-switch now resets session `search_state` when dropping in-flight worker (never persists partial hits)
- Lifecycle fix: fullscreen-enter drops late gen signals and resets search state before UI clear
- Quadratic rendering: `append_search_results(hits)` incremental, `display_search_results()` called once per search

**Files changed:** `controller/pdf_controller.py`, `model/pdf_model.py`, `model/tools/search_tool.py`, `view/pdf_view.py`

**Tests:** `test_scripts/test_search_worker_flow.py`, `test_scripts/test_multi_tab_plan.py`

---

### Phase 2 — Print snapshot + watermark double-stamp fix (Finding #1, #8)

**Problem:**
1. Print submission read live doc while worker spooled (second concurrent doc reader)
2. Watermark overlay was stamped twice: once by `WatermarkTool.needs_page_overlay` during render, once by helper subprocess

**Solution:**
1. `_start_print_submission()` captures print bytes on GUI thread before `thread.start()`; worker receives bytes instead of live doc and writes directly to disk (I/O stays off GUI thread)
2. `WatermarkTool.needs_page_overlay()` returns `False` for `purpose == "print"` — helper subprocess is the only stamping path for prints

**Files changed:** `controller/pdf_controller.py`, `model/tools/manager.py`, `model/pdf_model.py`, `model/tools/watermark_tool.py`

**Tests:** `test_scripts/test_print_snapshot_path.py`, `test_scripts/test_print_controller_flow.py`

---

### Phase 3 — OCR worker snapshot isolation (Cleanup A5)

**Problem:** OCR worker mutations were not isolated; `page_done` signals could mutate the wrong active document if tabs switched mid-OCR.

**Solution:**
- `_OcrWorker` now receives snapshot bytes (reuses Phase 1 helper), opens private doc
- `OcrTool.ocr_pages()` gains optional `doc=` override for render-context override
- Add `_ocr_gen` gen-token mirroring search; capture `_ocr_session_id` at `start_ocr`
- `_on_ocr_page_done()` checks: active session matches captured id (else warn + drop)
- Non-blocking OCR cancellation from session-switch/close chokepoints
- GC-safe release: `thread.finished` → identity-guarded release (no ref-nulling footgun)

**Files changed:** `controller/pdf_controller.py`, `model/tools/ocr_tool.py`, `model/pdf_model.py`

**Tests:** `test_scripts/test_ocr_controller_flow.py`

---

### Phase 4 — Thumbnail invalidation optimizations (Finding #4, #14)

**Problem:**
1. Invalidation blanked all rows via `set_thumbnail_placeholders(clear())` even on count-unchanged ops (rotate, straighten), forcing re-render of unaffected pages
2. Thumbnail gen bumps cancelled unrelated background work (viewport-anchor restore, open-background fallback)
3. Cross-page text move didn't invalidate destination page

**Solution:**
1. New `_thumb_gen_by_session` counter decouples thumbnail refresh from `_load_gen_by_session`
2. Count-unchanged path skips `set_thumbnail_placeholders`, schedules bounded batch via `end_limit` covering only affected rows
3. Count-changed path keeps full placeholder reset + forward chain
4. `move_text_across_pages` invalidates both src and dst on success and rollback

**Files changed:** `controller/pdf_controller.py`, `view/pdf_view.py`, test suite updates

**Tests:** `test_scripts/test_thumbnail_async.py` (5 new tests), `test_scripts/test_cross_page_text_move.py` (updated)

---

### Phase 5 — Undo byte budget fixes (Finding #5)

**Problem:**
1. Trim loop could evict all commands including the newest (if it exceeded budget alone), making `can_undo()` incorrectly return False
2. Dedup'd bytes counted double: `curr._before_bytes = prev._after_bytes` (shared object) counted as two separate bytes in budget

**Solution:**
1. Trim floor: `while len(self._undo_stack) > 1 and total > budget` — newest command always survives with warning
2. `_snapshot_chunks()` returns actual bytes objects; `_unique_byte_total()` deduplicates via `id(chunk)` so shared aliases count once
3. Restores effective full 512 MiB budget for dedup'd stacks

**Files changed:** `model/edit_commands.py`

**Tests:** `test_scripts/test_undo_memory_budget.py` (2 new tests: oversized-survive, dedup-unique-count)

---

### Phase 6 — QSS padding cascade fix + preview render clamp (Finding #3, #11a)

**Problem:**
1. QSS theme rule `QTextEdit { padding: 4px 8px; }` cascaded back into inline editor even when it had its own stylesheet, shifting glyphs in themed sessions
2. Preview render needed to clamp pixmap size like other raster paths but view layer couldn't import from model (layer violation)

**Solution:**
1. `_build_text_editor_stylesheet()` adds `padding: 0px; margin: 0px;` to defeat cascade
2. New `utils/render_limits.py` module (legal: view→utils) with `safe_render_scale()` and `_MAX_PIXMAP_PX = 40_000_000`
3. `model/pdf_model.py` re-exports from utils (no call-site churn)
4. `view/text_editing.py` clamps preview `get_pixmap` via `safe_render_scale()`

**Files changed:** `utils/render_limits.py` (new), `model/pdf_model.py`, `view/pdf_view.py`, `view/text_editing.py`

**Tests:** `test_scripts/test_text_editor_theme_padding.py` (3 new tests)

---

### Phase 7 — Guards + optimizer + hygiene (Finding #9, #11b, #12, #13, #15)

**Problems & Fixes:**

1. **Render page bounds (Finding #9, #11b):** `render_page_pixmap(page_num=0)` silently rendered last page instead of raising
   - Fix: `if page_num < 1 or page_num > len(doc): raise ValueError`

2. **Wheel zoom overshoot (Finding #12):** At max zoom, wheel-up visually overshot past 400% cap with snap-back
   - Fix: Use `eff = clamped_scale / old_scale` (effective factor) instead of raw factor; skip transform when `eff == 1.0`

3. **IPC dash-token skip (Finding #13):** Non-dash tokens starting with `-` were silently skipped, allowing malicious args to pass
   - Fix: Delete skip logic; every non-blank token must resolve to an existing `.pdf`

4. **Native PyMuPDF objstms (Finding #15, cleanup):** Object streams were incorrectly gated on pikepdf; native `use_objstms=1` works on both PyMuPDF 1.25.5 and 1.27.1
   - Fix: `optimize_capabilities()` reports `object_streams: True` unconditionally, `fast_save_kwargs()` passes option from config, `requires_post_save_packaging()` only checks linearize

**Files changed:** `model/tools/manager.py`, `view/pdf_view.py`, `utils/single_instance.py`, `model/pdf_optimizer.py`

**Tests:** `test_scripts/test_phase7_guard_hygiene.py` (7 new tests), `test_scripts/test_pdf_optimize_workflow.py` (updated)

---

## Testing & Verification

| Phase | Finding(s) | Red-light Test(s) | Status | Suite Result |
|-------|-----------|------------------|--------|--------------|
| 1 | #2, #6, #7, #10 | `test_search_worker_flow.py` | ✓ Green | 1283 pass |
| 2 | #1, #8 | `test_print_snapshot_path.py` | ✓ Green | 1288 pass |
| 3 | cleanup-A5 | `test_ocr_controller_flow.py` | ✓ Green | 1290 pass |
| 4 | #4, #14 | `test_thumbnail_async.py` | ✓ Green | 1295 pass |
| 5 | #5 | `test_undo_memory_budget.py` | ✓ Green | 1297 pass |
| 6 | #3, #11a | `test_text_editor_theme_padding.py` | ✓ Green | 1300 pass |
| 7 | #9, #11b, #12, #13, #15 | `test_phase7_guard_hygiene.py` | ✓ Green | 1302 pass |

**Full suite:** `python -m pytest test_scripts -q` → 1302 passed, 21 skipped, 0 failures (133.98s)

**Code quality:** `ruff check .` → zero new violations (pre-existing 240-violation baseline unchanged)

---

## Architecture & Docs Updates

**Docs updated:**
- `docs/ARCHITECTURE.md` — New invariant: "background workers never read the live doc; they capture snapshot bytes on the GUI thread"
- `docs/PITFALLS.md` — New entries documenting all seven phases' gotchas, pitfalls, and architectural constraints
- `TODOS.md` — All phases marked complete; four deferred items recorded (snapshot-bytes caching, dedup digest optimization, MVC merge-dialog routing, preset objstms re-enable)

**New test files:**
- `test_scripts/test_text_editor_theme_padding.py` — QSS padding cascade, safe_render_scale clamp tests
- `test_scripts/test_phase7_guard_hygiene.py` — Bounds checks, wheel zoom, IPC, optimizer tests
- `utils/render_limits.py` — Shared pixmap clamp module, exports `safe_render_scale()`, `_MAX_PIXMAP_PX`

---

## Deferred Items

Four non-blocking follow-ups recorded for future work:

1. **Snapshot-bytes caching:** Cache worker snapshot bytes keyed by `_render_revision` so overlapping search/OCR/print requests reuse the same serialization instead of re-calling `tobytes()`

2. **Undo dedup digest optimization:** C-speed `bytes.__eq__` memcmp-on-record optimization for adjacent dedup checks (accepted but deferred; current `id()`-based dedup covers the common case)

3. **MVC routing of merge-dialog page counting:** View-layer `fitz.open()` calls in `pdf_view.py` (merge dialog page-count probe) should route through controller/model utility to respect layer boundaries

4. **Preset objstms re-enable:** Optimizer presets currently leave `use_object_streams=False`; with native support now confirmed, consider enabling by default in balanced/compression presets

---

## Summary

All 15 `/code-review xhigh` findings have been resolved via architectural isolation (snapshot bytes for background workers), guard funnels (bounds checking, render scaling), and hygiene fixes (QSS cascade, wheel zoom, IPC validation, native objstms). The codebase now has:

- **Snapshot isolation:** Background workers (search, OCR, print) read GUI-thread-captured bytes, never live doc
- **Chokepoint guards:** All raster, merge, zoom, annotation, watermark, and IPC entry points guarded against resource exhaustion and bounds errors
- **Gen-tokened cancellation:** Signals carry generation tokens, late arrivals dropped
- **Unified undo:** 512 MiB byte budget, dedup'd bytes counted once, floor prevents accidental false `can_undo()`
- **QSS hygiene:** Inline editor QSS defeats theme cascade
- **Render clamp module:** Legal view→utils import path, all render paths bounded

Working tree clean. All phases committed. Test suite green. Ready for production deployment.
