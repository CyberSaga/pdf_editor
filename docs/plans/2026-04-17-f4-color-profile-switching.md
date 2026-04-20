# F4 Color Profile Switching (View-Only) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the user switch the view/print-preview color profile between **sRGB**, **Grayscale**, and **CMYK-preview** without altering the saved PDF. Affects on-screen rendering (main view, thumbnails, snapshots) and the print-preview pixmap path. Save-as / export-as-PDF output is unchanged.

**Architecture:** Thread a `colorspace` parameter through the render stack (`ToolManager.render_page_pixmap` and `PDFRenderer.iter_page_images`) and store the current choice as a **session-scoped** field on `SessionUIState`. A new toolbar/menu action emits a controller signal that updates the session state and invalidates cached pixmaps. No persistence layer, no ICC files, no document mutation.

**Tech Stack:** PyMuPDF `fitz.csRGB` / `fitz.csGRAY` / `fitz.csCMYK`, PySide6 actions/signals, pytest.

**Scope guardrails (explicit non-goals):**
- No document-level color conversion; nothing is written back into the PDF.
- No custom `.icc` file loading.
- No soft-proofing, no monitor calibration, no gamma controls.
- No `QSettings` / cross-session persistence (preference resets per app launch; fine for a view toggle).

---

## Context

Current rendering is colorspace-implicit: `model/tools/manager.py:57-78` calls `page.get_pixmap(matrix, annots)` with no colorspace argument, and `src/printing/pdf_renderer.py:87` hardcodes `fitz.csRGB`. There is no user control over render colorspace. The user wants a reversible view-mode toggle so grayscale or CMYK-preview can be inspected without touching the file. Keeping it view-only eliminates the hardest risks (page-content corruption, irreversible writes) and ships the useful 80% of F4 in one slice.

---

## Critical files

- Modify: `model/tools/manager.py` — `render_page_pixmap` accepts optional `colorspace` kwarg; forwards to `page.get_pixmap(matrix, annots, colorspace=...)`.
- Modify: `model/pdf_model.py` — `get_page_pixmap`, `get_thumbnail`, `get_page_snapshot`, and image-export (`line 951`) accept/forward `colorspace`. Export image path gets a dedicated kwarg; export PDF path is **not** touched.
- Modify: `controller/pdf_controller.py` — extend `SessionUIState` (line 89-95) with `color_profile: str` (default `"srgb"`); add `set_session_color_profile(profile)` method; invalidate `_page_render_quality_by_session` entries for that session so re-render is forced; re-issue visible-page render.
- Modify: `src/printing/pdf_renderer.py:67-98` — `PDFRenderer.__init__` takes `colorspace`; `iter_page_images` passes it to `dlist.get_pixmap(...)`.
- Modify: `controller/pdf_controller.py` print dispatcher (line 1391-1452) to pass the active session's color profile into `UnifiedPrintDialog` → `PDFRenderer`.
- Modify: `view/pdf_view.py` or the toolbar module (find via grep) — add a three-way action group ("sRGB" / "灰階" / "CMYK 預覽") emitting a new signal `sig_color_profile_changed(profile: str)`.
- Tests:
  - `test_scripts/test_render_colorspace.py` (new) — model/tools level.
  - `test_scripts/test_color_profile_controller.py` (new) — controller state + cache invalidation.
  - `test_scripts/test_color_profile_gui.py` (new) — action group wiring + signal.
  - Extend `test_scripts/test_print_controller_flow.py` to assert print uses the session profile.

Reuse:
- `SessionUIState` dataclass (controller/pdf_controller.py:89).
- Existing render-quality invalidation pattern `_page_render_quality_by_session` (line 245) as the template for forcing re-render on profile change.
- `fitz.csRGB`, `fitz.csGRAY`, `fitz.csCMYK` constants — no new deps.

---

## Tasks

### Task 1: Define profile enum + fitz mapping

**Files:**
- Create: `model/color_profile.py`
- Test: `test_scripts/test_color_profile_enum.py`

**Step 1 — Red test:** Import `ColorProfile` and `to_fitz_colorspace`; assert `to_fitz_colorspace(ColorProfile.SRGB) is fitz.csRGB`, `.GRAY → fitz.csGRAY`, `.CMYK → fitz.csCMYK`; assert unknown string raises `ValueError`; assert `ColorProfile.from_string("srgb")` round-trips.

**Step 2:** Run → FAIL.

**Step 3:** Implement `ColorProfile` (`Enum` with values `"srgb"`, `"gray"`, `"cmyk"`) and the two helpers. Keep it Qt-free.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(model): add ColorProfile enum for view-only color switching`.

---

### Task 2: Thread colorspace through ToolManager render path

**Files:**
- Modify: `model/tools/manager.py:57-78`
- Test: `test_scripts/test_render_colorspace.py`

**Step 1 — Red test:** Open a fixture PDF, render a page via `render_page_pixmap(page_num=0, scale=1.0, annots=False, purpose="view", colorspace=fitz.csGRAY)`; assert the returned pixmap's `colorspace.n == 1` (grayscale). Same test with default call (no kwarg) → `colorspace.n == 3` (RGB).

**Step 2:** Run → FAIL.

**Step 3:** Add optional `colorspace: fitz.Colorspace | None = None` kwarg; when provided, pass to `page.get_pixmap(matrix=..., annots=..., colorspace=colorspace)`. Default None preserves current behavior.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(tools): ToolManager render_page_pixmap accepts colorspace`.

---

### Task 3: Expose colorspace via PDFModel render entry points

**Files:**
- Modify: `model/pdf_model.py` (`get_page_pixmap` ~1177, `get_thumbnail` ~1185, `get_page_snapshot` ~1180)
- Test: extend `test_render_colorspace.py`

**Step 1 — Red test:** `model.get_page_pixmap(session_id, page=0, colorspace=fitz.csCMYK)` returns pixmap with `.colorspace.n == 4`. Same for `get_thumbnail` and `get_page_snapshot`.

**Step 2:** Run → FAIL.

**Step 3:** Add `colorspace=None` passthrough to all three methods; forward to `tools.render_page_pixmap`. Do NOT touch PDF export (`line 980 insert_pdf` path) or save paths.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(model): forward colorspace kwarg through render entry points`.

---

### Task 4: SessionUIState + controller state change

**Files:**
- Modify: `controller/pdf_controller.py` (`SessionUIState` lines 89-95, add setter + invalidation)
- Test: `test_scripts/test_color_profile_controller.py`

**Step 1 — Red test:**
- Create controller with a session; assert default `session.ui_state.color_profile == "srgb"`.
- Call `controller.set_session_color_profile(session_id, "gray")`; assert state updated.
- Assert `_page_render_quality_by_session[session_id]` is cleared (forces re-render at new colorspace).
- Assert controller emits `sig_visible_render_requested` (or equivalent existing re-render signal — check actual name during implementation) after the change.
- Unknown profile raises `ValueError`.

**Step 2:** Run → FAIL.

**Step 3:** Add `color_profile: str = "srgb"` field to `SessionUIState`. Implement `set_session_color_profile(session_id, profile)`: validate via `ColorProfile.from_string`, update state, clear quality cache for that session, schedule a re-render via the existing coalesced visible-render path. Ensure render requests downstream pull `session.ui_state.color_profile` and map through `to_fitz_colorspace` before calling model render methods.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(controller): session color profile with cache invalidation`.

---

### Task 5: Wire existing render dispatches to honor session profile

**Files:**
- Modify: the controller render-dispatch sites that call `model.get_page_pixmap` / `get_thumbnail` / `get_page_snapshot` (locate via grep during implementation).
- Test: extend `test_color_profile_controller.py` with a spy on `tools.render_page_pixmap` verifying the `colorspace` kwarg matches the session's current profile.

**Step 1 — Red test:** Set session profile to `"cmyk"`, trigger visible-page render; assert spy received `colorspace=fitz.csCMYK`.

**Step 2:** Run → FAIL.

**Step 3:** At each dispatch site, resolve the session's `color_profile` → `fitz.Colorspace` and pass through. Keep default-None callers working for any non-session-bound renders.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(controller): render dispatches honor session color profile`.

---

### Task 6: Print preview honors session profile

**Files:**
- Modify: `src/printing/pdf_renderer.py:67-98` — `PDFRenderer.__init__(self, ..., colorspace=fitz.csRGB)`; `iter_page_images` uses `self._colorspace` instead of hardcoded `fitz.csRGB`.
- Modify: `controller/pdf_controller.py:1391-1452` print dispatcher — resolve session profile, pass to `UnifiedPrintDialog` → `PDFRenderer`.
- Test: extend `test_scripts/test_print_controller_flow.py` with a case asserting that when session profile is `"gray"`, the constructed `PDFRenderer` receives `fitz.csGRAY`.

**Step 1 — Red test:** Spy on `PDFRenderer.__init__`; trigger print from a session with `color_profile="gray"`; assert `colorspace` arg is `fitz.csGRAY`.

**Step 2:** Run → FAIL.

**Step 3:** Add `colorspace` kwarg to `PDFRenderer`; thread session profile through the print dispatcher and `UnifiedPrintDialog` constructor. Keep `fitz.csRGB` as the default so non-UI callers are unaffected.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(print): print preview honors session color profile`.

---

### Task 7: View action group

**Files:**
- Modify: toolbar/menu module (likely `view/pdf_view.py` or a dedicated actions module — locate during implementation).
- Test: `test_scripts/test_color_profile_gui.py`

**Step 1 — Red test:**
- Build view; assert three exclusive `QAction`s exist: "sRGB", "灰階", "CMYK 預覽".
- Toggling "灰階" emits `sig_color_profile_changed("gray")`.
- Only one action is checked at a time.
- Default checked action corresponds to current session's `color_profile`.

**Step 2:** Run → FAIL.

**Step 3:** Add the action group under a "檢視 → 色彩設定檔" submenu (reuse existing menu scaffolding). Signal name: `sig_color_profile_changed(str)`. Wire controller to call `set_session_color_profile` on that signal.

**Step 4:** Run → PASS.

**Step 5:** Commit: `feat(view): color profile action group under view menu`.

---

### Task 8: Docs + tracker

**Files:**
- Modify: `docs/ARCHITECTURE.md` — add one paragraph to the rendering section noting the session-scoped `color_profile` and that it is view-only.
- Modify: `docs/PITFALLS.md` — entry if `page.get_pixmap(colorspace=fitz.csCMYK)` surfaces any fitz quirk during implementation (e.g., needs `alpha=False`).
- Modify: `TODOS.md`, `docs/plans/2026-04-10-backlog-checklist.md`, `docs/plans/2026-04-09-backlog-execution-order.md` — F4 row: status `done-implement` for view-only slice; leave a note that export-level conversion is deliberately deferred.

**Commit:** `docs: record F4 view-only color profile slice`.

---

## Verification (end-to-end)

1. `ruff check .` — zero new violations.
2. `pytest -q test_scripts/test_color_profile_enum.py test_scripts/test_render_colorspace.py test_scripts/test_color_profile_controller.py test_scripts/test_color_profile_gui.py` — green.
3. `pytest -q test_scripts/test_print_controller_flow.py` — green (extended case passes).
4. Full regression: `pytest -q` — no regressions.
5. Manual on `test_files/2.pdf`:
   - Switch to "灰階" → main view + thumbnails become grayscale; save-as produces a PDF whose re-opened pages are still full color (proves view-only).
   - Switch to "CMYK 預覽" → main view re-renders; print preview also reflects CMYK sampling.
   - Switch back to "sRGB" → view and thumbnails return to color; no visible artifacts from cache.
6. Startup benchmark (`benchmark_ui_open_render.py --path test_files/2024_ASHRAE_content.pdf`) — still within B4 numbers (no regression from the extra kwarg plumbing).

---

## Open questions / notes

- `page.get_pixmap(colorspace=fitz.csCMYK)` returns a 4-channel pixmap; Qt `QImage` needs correct format mapping. Check `_pixmap_to_qimage` in `src/printing/pdf_renderer.py:45-48` — may need a CMYK → RGB conversion before display (use `fitz.Pixmap(fitz.csRGB, cmyk_pix)` as the display-time bridge). If so, the CMYK path is a "CMYK-sampled but RGB-displayed" preview; note this honestly in the UI tooltip.
- Thumbnails re-render only on explicit invalidation; Task 4's cache clear must cover the thumbnail quality map too — verify by asserting thumbnail pixmap colorspace after profile change in Task 5's test.
- If the session's rendered pixmap cache is keyed only by `(page, scale, quality)`, adding `color_profile` to the key is cleaner than clearing on every switch. Decide during Task 4 based on actual cache-key structure; prefer key extension over cache-wipe for perf.
