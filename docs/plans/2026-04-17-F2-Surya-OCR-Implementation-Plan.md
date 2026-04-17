# F2-Surya-OCR-Implementation-Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Surya-based OCR workflow that turns scanned PDF pages into searchable/selectable text by inserting invisible text at the detected bboxes — without disturbing the rasterized page appearance. First slice supports English / Traditional Chinese / Simplified Chinese / Japanese, page-range input (default: current page; option: whole document), optional install, and cancellable progress UI.

**Architecture:** Extend the existing `OcrTool` (`model/tools/ocr_tool.py`) with a Surya backend that returns `{page_num: [(bbox, text, confidence), ...]}`. Controller orchestrates a `QThread`-based `_OcrWorker` (modeled on `_PrintSubmissionWorker`) that (1) rasterizes selected pages via the existing `render_page_pixmap`, (2) calls the tool, (3) marshals results back to the main thread, where the model inserts invisible text using the **existing** `_insert_textbox_visual_content` path with a new `invisible=True` flag that sets PDF text-rendering mode 3. Block index rebuild is already triggered by the insert path, so search/selection light up automatically.

**Tech Stack:** PyMuPDF (`fitz`) for rasterization + text insertion, Surya (`surya-ocr`) for detection + recognition, PySide6 (`QThread`, `QProgressDialog`), numpy, pytest.

**Scope guardrails (explicit non-goals):**
- No multi-provider OCR abstraction; Surya is the only backend. Keep the tool boundary minimal but not generic.
- No document-wide re-flow / text replacement; we only add an invisible layer.
- No automatic model downloads at app start; models lazy-load on first OCR call.
- No per-word confidence UI; confidence is logged, not shown.
- No layout preservation beyond bbox placement (no columns/tables/headers recognition).

---

## Context

The app currently ships a stub `OcrTool` that calls `pytesseract` and returns plain strings with no bboxes (`model/tools/ocr_tool.py:14-47`). That API cannot produce a searchable layer. Meanwhile, the model already has a proven invisible-text-friendly insertion path (`_insert_textbox_visual_content`, `model/pdf_model.py:1821-1921`) that maps visual rects → page rects and calls `page.insert_htmlbox`, and triggers `TextBlockManager.rebuild_page` on insert (line 2119). This gives us exactly the hook we need: if we can (a) drive Surya in a worker thread, (b) convert its pixel bboxes to page-space rects, and (c) insert the text with `render_mode=3` (invisible), OCR output becomes first-class searchable/selectable text without any new index plumbing.

Worker pattern, progress UI, and cancellation hooks already exist in the print/optimize paths (`controller/pdf_controller.py:120-204, 250-270, 319-355`) and should be reused, not reinvented.

---

## Critical files

- Modify: `model/tools/ocr_tool.py` — replace Tesseract stub with Surya backend; add availability check; return `{page_num: [OcrSpan(bbox_visual, text, confidence), ...]}`.
- Create: `model/tools/ocr_types.py` — `OcrSpan` dataclass, `OcrLanguage` enum, `OcrAvailability` result.
- Modify: `model/pdf_model.py:1821-1921` — `_insert_textbox_visual_content` gains `invisible: bool = False` kwarg; when true, wraps the HTML in a span with `color: transparent` AND sets `page.insert_htmlbox(..., opacity=0)` or uses a direct `page.insert_text(point, text, render_mode=3, fontsize=fitted)` branch. (Decide at implementation time based on which keeps selection bounds correct — `insert_text` with render_mode 3 is the standard searchable-PDF approach; prefer it and fall back to htmlbox only if font metrics break.)
- Add: `model.apply_ocr_spans(session_id, page_num, spans: list[OcrSpan])` — loops and calls the invisible insert, then triggers a single `block_manager.rebuild_page` at the end (not one per span).
- Modify: `controller/pdf_controller.py` — add `_OcrWorker` + `_OcrBridge` (mirror `_PrintSubmissionWorker`/`_PrintWorkerBridge`); add `start_ocr(page_nums: list[int], languages: list[str])`; wire progress dialog with cancel.
- Create: `view/dialogs/ocr.py` — `OcrDialog` with (a) radio: current page / whole document / custom page list, (b) page-list text field (e.g. `"1, 3-5, 9"`), (c) language multi-select checklist (English / 繁中 / 简中 / 日本語), (d) OK / Cancel.
- Modify: the menu/toolbar module to add a "工具 → OCR 辨識…" action; disable with tooltip if Surya unavailable.
- Modify: `requirements-optional.txt` (create if absent) — add `surya-ocr` + `numpy` constraint.
- Tests:
  - `test_scripts/test_ocr_types.py` — dataclass round-trips, page-range parser (`"1,3-5"` → `[1,3,4,5]`, dedupe, clamp).
  - `test_scripts/test_ocr_tool_surya.py` — Surya call mocked; verify pixmap→numpy conversion, bbox scaling, language-code mapping.
  - `test_scripts/test_ocr_model_insert.py` — real fixture PDF; feed fake spans; assert the page afterward yields those strings from `get_text`/search and that subsequent pixmap is visually unchanged (pixel hash equal to pre-insert within tolerance).
  - `test_scripts/test_ocr_controller_flow.py` — worker lifecycle, progress signals, cancellation flips a flag the worker respects.
  - `test_scripts/test_ocr_dialog.py` — dialog parses `"1,3-5,9"`, respects current-page default, emits expected request.

Reuse:
- Worker/bridge template at `controller/pdf_controller.py:120-204`.
- Progress dialog helper pattern at `controller/pdf_controller.py:319-355`.
- `ToolManager.render_page_pixmap` for rasterization (`model/tools/manager.py:57-78`).
- `_insert_textbox_visual_content` rect conversion logic — extract the visual→unrotated helper if reusable; otherwise call the method with the new kwarg.
- `TextBlockManager.rebuild_page` — already the canonical post-structural-op refresh.

---

## Tasks

### Task 1: OCR types + page-range parser

**Files:**
- Create: `model/tools/ocr_types.py`
- Test: `test_scripts/test_ocr_types.py`

**Step 1 — Red test:**
- `OcrSpan(bbox=(x0,y0,x1,y1), text="hi", confidence=0.98)` constructs.
- `OcrLanguage.SURYA_CODE[OcrLanguage.TRAD_CHINESE] == "zh-Hant"` (exact code per Surya docs — verify at implementation time).
- `parse_page_range("1,3-5,9", total_pages=10) == [0, 2, 3, 4, 8]` (returns 0-based indices).
- `parse_page_range("", total_pages=10, default_current=4) == [4]` (default current-page fallback).
- `parse_page_range("all", total_pages=10) == list(range(10))`.
- Invalid input (`"abc"`, `"3-1"`, `"0"`) raises `ValueError` with a human-readable message.

**Step 2:** Run → FAIL.

**Step 3:** Implement `OcrSpan` dataclass, `OcrLanguage` enum with Surya code map, and `parse_page_range`. Keep Qt-free.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(ocr): add OcrSpan, OcrLanguage, and page-range parser`.

---

### Task 2: Surya availability probe + tool rewrite (Surya mocked)

**Files:**
- Modify: `model/tools/ocr_tool.py`
- Test: `test_scripts/test_ocr_tool_surya.py`

**Step 1 — Red test (Surya mocked):**
- Monkeypatch `importlib.import_module("surya")` to raise `ImportError`; assert `OcrTool.availability()` returns `OcrAvailability(available=False, reason="surya not installed")`.
- Monkeypatch a fake Surya module providing `DetectionPredictor` and `RecognitionPredictor` whose outputs are predictable; assert `OcrTool.ocr_pages([0], languages=["en"])` returns `{0: [OcrSpan(...)]}` with bboxes in **visual page coordinates** (not raster pixels) — i.e., scaled by `1/render_scale`.
- Assert language list is forwarded unchanged to the recognition predictor.
- Assert a bogus language code raises `ValueError` before any Surya call.

**Step 2:** Run → FAIL.

**Step 3:** Implement:
- `availability()` — import check + model-cache-exists check (warn but still `available=True` if cache missing; lazy download is Surya's default).
- `ocr_pages(page_nums, languages, render_scale=2.0, on_progress=None)`:
  1. For each page: `pix = tools.render_page_pixmap(page_num, scale=render_scale, annots=False, purpose="ocr")`.
  2. `arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)`; if `pix.n == 4`, drop alpha.
  3. Call Surya detector → recognizer (predictors are module-level singletons cached on first call to avoid ~10s reload per page).
  4. Map Surya pixel bboxes → visual page coords: `x_page = x_px / render_scale`, same for y.
  5. Emit `on_progress(page_num, done_count, total)` after each page.
  6. Return dict.

**Step 4:** Run → PASS (mocked).

**Step 5:** Commit: `feat(ocr): Surya backend replaces Tesseract stub`.

---

### Task 3: Model-side invisible text insertion

**Files:**
- Modify: `model/pdf_model.py` (extend `_insert_textbox_visual_content` or add `_insert_invisible_text_span`)
- Add: `model.apply_ocr_spans(session_id, page_num, spans)`
- Test: `test_scripts/test_ocr_model_insert.py`

**Step 1 — Red test (real fixture):**
- Open `test_files/<scan-like>.pdf` (or synthesize a page with only an image: `fitz` new doc, insert a rendered image, no text).
- Pre-insert pixel hash = hash of `page.get_pixmap(dpi=150).samples`.
- Call `model.apply_ocr_spans(session_id, 0, [OcrSpan((50,50,200,80), "hello world", 0.99)])`.
- Assert `"hello world" in page.get_text()`.
- Assert `model.search("hello", session_id)` finds the page.
- Assert post-insert pixel hash equals pre-insert (±tolerance for antialiased edges — use per-pixel L1 distance < 2% of pixels differing).
- Assert `TextBlockManager` marks the page indexed (not stale) after the call.

**Step 2:** Run → FAIL.

**Step 3:** Implement via `page.insert_text(point, text, fontsize=size_to_fit_bbox_height, render_mode=3, fontname="helv")`. For CJK, choose a CJK-capable font fitz ships with (`"china-t"` / `"china-s"` / `"japan"` built-ins, or embed via `page.insert_font`). Size the font so the string fits within the bbox width (binary search or metric-based fit). `apply_ocr_spans` batches all spans then calls `block_manager.rebuild_page` once at the end.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(model): apply_ocr_spans inserts invisible searchable text`.

---

### Task 4: OCR dialog

**Files:**
- Create: `view/dialogs/ocr.py`
- Test: `test_scripts/test_ocr_dialog.py`

**Step 1 — Red test:**
- Open dialog with `total_pages=10, current_page=3`; default state: "current page" radio checked, custom-range field disabled.
- Switch to custom-range, enter `"1,3-5,9"`, tick "English" + "繁體中文", click OK → dialog's `result()` returns `OcrRequest(page_indices=[0,2,3,4,8], languages=["en","zh-Hant"])`.
- Invalid range shows inline validation message; OK stays disabled.
- Cancel returns `None`.

**Step 2:** Run → FAIL.

**Step 3:** Implement `OcrDialog(QDialog)` with radio group (current / all / custom), page-range `QLineEdit`, language `QListWidget` with checkboxes, validation label, OK/Cancel. Reuse `parse_page_range` from Task 1.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(view): OCR page-range + language dialog`.

---

### Task 5: Controller worker + progress + cancel

**Files:**
- Modify: `controller/pdf_controller.py` — add `_OcrWorker`, `_OcrBridge`, `start_ocr(request: OcrRequest)`, `_show_ocr_progress_dialog`, `_on_ocr_complete`.
- Test: `test_scripts/test_ocr_controller_flow.py`

**Step 1 — Red test:**
- Spy on `OcrTool.ocr_pages`; call `controller.start_ocr(OcrRequest([0,1], ["en"]))`; assert worker ran on a non-GUI thread (`QThread.currentThread() is not QCoreApplication.instance().thread()` inside the spy's capture), emitted ≥2 progress signals, and on completion `model.apply_ocr_spans` was called once per page with the tool's returned spans.
- Simulate cancel mid-run by calling `controller.cancel_ocr()` after first progress; assert worker stopped before processing page 2, and no `apply_ocr_spans` call happened for page 1 (i.e., results are committed only after full success — OR per-page commit, pick one and test it; **recommend per-page commit** so partial progress survives cancel).
- On Surya unavailable, `start_ocr` must raise / surface an error signal before spawning a thread.

**Step 2:** Run → FAIL.

**Step 3:**
- `_OcrWorker(QObject)`: signals `progress(int,int,str)`, `page_done(int, list)`, `failed(object)`, `finished()`. `run()` loops page_nums, checks `self._cancel_requested` between pages, calls `tool.ocr_pages([p], languages, on_progress=...)`, emits `page_done`. Cancel sets a flag; worker exits at next boundary.
- `_OcrBridge` forwards onto main thread; `page_done` handler calls `model.apply_ocr_spans` (per-page commit) and updates progress dialog.
- Progress dialog: indeterminate for the per-page Surya call, label `"辨識第 {i}/{n} 頁…"`. Cancel button wired to `worker.request_cancel()`.
- Thread lifecycle mirrors `_OptimizePdfCopyWorker` wiring (`controller/pdf_controller.py:250-270`).

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(controller): threaded OCR with cancel and per-page commit`.

---

### Task 6: Menu/toolbar entry point + availability gating

**Files:**
- Modify: the toolbar/menu module (locate during implementation).
- Wire: action → `OcrDialog.exec()` → `controller.start_ocr(request)`.
- Tooltip: if `OcrTool.availability().available is False`, disable action and set tooltip to the reason + install hint (`pip install surya-ocr`).
- Test: a small GUI slice asserting the action exists, is disabled when availability is False, and triggers the dialog flow when True (mock the dialog's `exec` to return an `OcrRequest`, spy `controller.start_ocr`).

**Commit:** `feat(view): OCR menu entry, gated on Surya availability`.

---

### Task 7: Optional-extras wiring + docs

**Files:**
- Create/modify: `requirements-optional.txt` — add `surya-ocr`.
- Modify: `README.md` (or `docs/INSTALL.md` if present) — one section on enabling OCR: install command, first-run model download note, CPU/GPU note.
- Modify: `docs/ARCHITECTURE.md` — add a paragraph under ToolManager/OCR describing the worker, the invisible-text convention, and the lazy predictor singletons.
- Modify: `docs/PITFALLS.md` — entries as discovered during Task 2/3 (e.g., CJK font choice for `insert_text` render-mode 3, Surya predictor memory cost, bbox scaling pitfalls).
- Modify: `TODOS.md`, `docs/plans/2026-04-10-backlog-checklist.md`, `docs/plans/2026-04-09-backlog-execution-order.md` — mark F2 slice done-implement; note future slices (table/layout, confidence UI, multi-provider) as deferred.

**Commit:** `docs: record F2 Surya OCR slice`.

---

## Verification (end-to-end)

1. `ruff check .` — zero new violations.
2. `pytest -q test_scripts/test_ocr_types.py test_scripts/test_ocr_tool_surya.py test_scripts/test_ocr_model_insert.py test_scripts/test_ocr_dialog.py test_scripts/test_ocr_controller_flow.py` — all green.
3. Full regression: `pytest -q` — no regressions.
4. Manual with Surya installed (`pip install -r requirements-optional.txt`):
   - Open a scanned PDF (image-only page). Run OCR on current page (English + 繁中). Wait for progress → dialog closes.
   - Use find/search for a word visible on the page — search lands on the correct page and highlight box lines up with the rendered glyphs.
   - Drag-select text across the page — selection snaps to detected lines (browse-mode whole-line behavior from UX6 still applies).
   - Save as new PDF → reopen → OCR text persists; page render is visually unchanged from the original.
   - Run "whole document" mode on a 20-page scan; confirm cancel mid-run stops further pages and keeps already-OCR'd pages committed.
5. Manual without Surya installed: OCR menu item is disabled with tooltip telling user to install `surya-ocr`.
6. Benchmark: OCR on one page of `test_files/2.pdf` should complete without blocking the UI thread (confirm: click around the app during OCR — no freeze).

---

## Open questions / notes

- **CJK font for invisible text:** PyMuPDF built-ins (`"china-t"`, `"china-s"`, `"japan"`) are suitable for render-mode 3 and do not need embedding. If `page.insert_text` with these names fails to find glyphs for rare chars, fall back to embedding a CJK font from the OS, or fall back to `insert_htmlbox` with `opacity=0`.
- **Surya predictor caching:** Initialize `DetectionPredictor` and `RecognitionPredictor` as module-level lazy singletons in `ocr_tool.py` to avoid paying model-load cost per page. First OCR call will be slow; subsequent calls are fast.
- **Per-page commit vs all-at-end commit:** Plan chooses per-page commit for cancel-safety. If atomicity is preferred later, the switch is local to `_OcrBridge.on_page_done`.
- **Render scale:** Start at `scale=2.0` (≈144 DPI). Make it a constant named `OCR_RENDER_SCALE` in `ocr_tool.py` for easy tuning.
- **Threading safety:** `fitz.Document` is not thread-safe for writes. The worker only *reads* pixmaps; all `apply_ocr_spans` calls run on the main thread via the bridge. Do not move the insert call into the worker.
- **Model download policy:** Let Surya download on first run to its default cache. Do not bundle models. Note this clearly in README so the first OCR call's delay isn't surprising.
