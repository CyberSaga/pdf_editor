# F4 View‑Only Color Profile Switching — Fixes + UI Placement Revision

## Summary
Ship a correctness + UX cleanup pass for F4 view-only profile switching:
- Fix **GRAY + CMYK pixmap → Qt image** conversion so main view, thumbnails, snapshots, search-jump, and print preview do not corrupt/crash.
- Make profile switching **thumbnail-correct** and **cache-efficient** by keying render caches/quality by `color_profile`.
- Move the control from the “常用” toolbar actions to a **persistent right-sidebar “色彩設定檔” section** (per your preference), keeping `sig_color_profile_changed(str)` + `set_color_profile(...)` semantics.

## Key Implementation Changes
1) **Qt image conversion (P0 fix)**
- Update `utils/helpers.py::pixmap_to_qpixmap` to handle non-RGB pixmaps:
  - If `not pix.alpha` and `pix.colorspace.n in {1, 4}`, convert via `pix = fitz.Pixmap(fitz.csRGB, pix)` before constructing `QImage(..., Format_RGB888)`.
- Update controller print-preview path `controller/pdf_controller.py::_render_print_preview_image` to *stop* constructing `QImage` directly from raw `pix.samples`; instead route through the same safe conversion (either reuse a new `utils.helpers.pixmap_to_qimage` helper, or reuse the updated conversion logic locally).
- Update `src/printing/pdf_renderer.py::_pixmap_to_qimage` to convert **GRAY as well as CMYK** (same rule: `colorspace.n in {1,4}` and no alpha ⇒ bridge to RGB before `QImage`).

2) **Profile-aware render caching + quality tracking (thumb_refresh choice = “Key render caches by profile”)**
- Refactor `PDFController._page_render_quality_by_session` to be profile-aware, e.g.:
  - `dict[session_id][color_profile][page_idx] = "low"|"high"`
- Extend `_render_cache_key(...)` to include `color_profile`:
  - Key becomes `(session_id, color_profile, page_idx, rendered_scale_milli, quality, revision)`.
- Update all read/write sites (`_render_page_into_scene`, `_schedule_visible_render`, `_process_visible_render_batch`, `_render_active_session`, `_rebuild_continuous_scene`, `_bump_render_revision`, etc.) to use the **current session profile’s** quality map + render-cache keys.
- Modify `set_session_color_profile(...)`:
  - Do **not** drop the entire render cache for the session anymore.
  - Ensure the target profile’s quality map exists/cleared as needed, then schedule visible render for current page.

3) **Thumbnail refresh on profile switch (P1 fix)**
- On active-session profile change, explicitly re-trigger thumbnail rendering:
  - Increment/load a fresh `load_gen` and call `_schedule_thumbnail_batch(0, session_id, gen)` (batching keeps UI responsive).
  - Keep existing batching semantics (no full synchronous `_update_thumbnails()` on large docs).

4) **UI placement: right sidebar section**
- Remove the three profile `QAction`s from the “常用” toolbar tab.
- Add a persistent right-sidebar panel (above the stacked inspector cards) titled `色彩設定檔`, implemented as a compact `QComboBox` (or radio group) with:
  - Display: `sRGB`, `灰階`, `CMYK 預覽`
  - Data values: `srgb|gray|cmyk`
- Keep `PDFView.sig_color_profile_changed(str)` and `PDFView.set_color_profile(str)`:
  - `set_color_profile` updates the sidebar control with signals blocked (no emission).
  - User interaction emits `sig_color_profile_changed(profile)` once.
- Controller wiring remains: connect `sig_color_profile_changed` → `set_session_color_profile(active_sid, profile)`.
- On tab/session switch, controller calls `view.set_color_profile(state.color_profile)` to keep UI synced.

5) **Print colorspace wiring cleanup**
- In `src/printing/qt_bridge.py`, replace the duplicated `"gray|grayscale|cmyk"` mapping with `model.color_profile.to_fitz_colorspace(...)` (with a guarded fallback to `fitz.csRGB` on `ValueError`).
- Remove the unused `PrintJobRequest.metadata["render_colorspace"]` plumbing and stop passing metadata into `PrintHelperJob` (keep `extra_options["render_colorspace"]` as the single effective channel).

6) **Safer fallback behavior**
- In `PDFController._fitz_colorspace_for_session`, if state contains an unknown profile:
  - Log a warning and self-heal back to `"srgb"` (update `SessionUIState.color_profile` and call `view.set_color_profile("srgb")` when active), so UI + session state cannot silently diverge.

## Test Plan (add regressions that catch the reported bugs)
- New unit regression: `utils/helpers.py::pixmap_to_qpixmap` accepts GRAY + CMYK pixmaps without exception and preserves dimensions:
  - Build a 1-page temp PDF with `fitz`, render `get_pixmap(colorspace=fitz.csGRAY)` and `fitz.csCMYK`, then call `pixmap_to_qpixmap` and assert `qpix.width()==pix.width` and `qpix.height()==pix.height`.
- New print regression: `PDFRenderer(colorspace=fitz.csGRAY)` + `iter_page_images(...)` yields a `RenderedPage.image` with expected width/height (ensures grayscale conversion path is exercised).
- Update GUI test (`test_color_profile_gui.py`) to assert:
  - Right-sidebar “色彩設定檔” control exists with 3 options.
  - Changing selection emits `sig_color_profile_changed("gray")`.
  - Calling `set_color_profile("cmyk")` updates UI without emitting.
- Update controller tests (`test_color_profile_controller.py`) for the new nested structure of `_page_render_quality_by_session` and profile-aware caching.
- Re-run: `pytest -q` (full suite).
- Lint evidence: run `ruff check` only on touched/added paths (repo currently has no ruff config, so `ruff check .` is not actionable).

## Assumptions / Defaults
- `QImage` construction is standardized to RGB(A) by **always bridging GRAY/CMYK → RGB** before `QImage` (your selected strategy); grayscale still displays as grayscale (monochrome RGB).
- Profile switching remains **view-only**: no PDF mutation, no ICC loading, no persistence across app restarts.
- Right-sidebar control is always available (not mode-specific), and is the single primary UI for profile switching (toolbar actions removed).
