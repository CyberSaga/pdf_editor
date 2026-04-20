# Simplify & Fix Report — F4 Color Profile Switching (2026-04-20)

## Overview
Applied consensus fixes from three parallel review agents (Reuse, Quality, Efficiency) against the F4 view-only color profile switching implementation. Also fixed a P0 bug in object selection overlay.

## Code Reuse Fixes

### FIX 1: Eliminate duplicate pixmap-to-qimage conversion
**Files:** `src/printing/pdf_renderer.py`, `utils/helpers.py`

- Removed byte-for-byte duplicate `PDFRenderer._pixmap_to_qimage` static method.
- `pdf_renderer.py` now imports and delegates to `utils.helpers.pixmap_to_qimage`.
- Centralizes GRAY/CMYK→RGB bridge logic in one place; reduces maintenance burden.

### FIX 2: Add safe colorspace converter helper
**Files:** `model/color_profile.py`, `src/printing/qt_bridge.py`

- Added `safe_to_fitz_colorspace(profile, default=fitz.csRGB)` to `model/color_profile.py`.
- `qt_bridge.py::raster_print_pdf` now uses it instead of local try/except + raw fallback.
- Removes `import fitz` from qt_bridge (was only used for `csRGB` fallback).
- Reusable pattern for fallible colorspace conversions elsewhere.

## Code Quality Fixes

### FIX 3: Replace itemData loop with findData
**File:** `view/pdf_view.py::set_color_profile`

- Old: manual loop `for i in range(combo.count()): if str(combo.itemData(i)).strip().lower() == normalized`.
- New: `combo.findData(normalized)` (canonical Qt method).
- Cleaner intent; eliminates hand-rolled string comparison.

### FIX 4: Replace lambda with named method
**File:** `view/pdf_view.py`

- Old: `lambda _idx=0: self.sig_color_profile_changed.emit(...)` (inline lambda noise).
- New: Extracted `_on_color_profile_combo_changed(_index: int)` method.
- Improves debuggability and signal/slot tracing.

### FIX 5: Use dataclasses.replace for immutable mutation
**File:** `controller/pdf_controller.py::_start_print_submission`

- Old: `extra = dict(...); normalized_options.extra_options = extra` (mutates post-normalization).
- New: `dataclass_replace(normalized_options, extra_options={...})` (immutable pattern).
- Makes data flow explicit; avoids hidden mutation side effects.

### FIX 6: Extract normalize-and-warn helper
**File:** `controller/pdf_controller.py`

- Old: 3× copy-paste of normalize + warn-if-unknown pattern in:
  - `_capture_current_ui_state`
  - `_render_active_session`
  - `_start_print_submission`
- New: `_resolve_session_profile(sid, sync_view=False)` helper.
- Replaces 12 lines of boilerplate per site with single call.
- Centralizes healing logic; reduces divergence risk.

### FIX 7: Drop tautological comment
**File:** `model/color_profile.py::to_fitz_colorspace`

- Removed "Defensive; Enum values above should be exhaustive" comment.
- The raise is self-documenting; comment adds no value and rots easily.

## Bug Fixes

### FIX 8: Dead C++ object references in selection overlay (P0)
**File:** `view/pdf_view.py::_update_object_selection_visuals`

- **Bug:** When `scene.clear()` runs (during continuous-mode rebuilds, cache resets), the underlying C++ items are deleted. But Python refs on `self._object_selection_rect_item`, `self._object_rotate_handle_item`, `self._object_resize_handle_items` survive as dangling pointers.
- **Symptom:** Next `_select_object` → `_update_object_selection_visuals` calls `setRect()` on deleted C++ object → `RuntimeError: Internal C++ object already deleted`.
- **Fix:** Added `shiboken6.isValid()` guards at the start of `_update_object_selection_visuals`. Dead refs are dropped and re-created on demand.
- **Why:** `scene.clear()` is called during page rebuild, profile switch thumbnail re-render, and single-page scene rebuild. The C++ deletion is orthogonal to the Python ref lifecycle.

## Test Coverage

All 543 tests pass (no regressions):
```
543 passed, 1 skipped
```

Color-profile specific test suite (15 tests):
- `test_color_profile_enum.py` — 2 tests
- `test_color_profile_controller.py` — 4 tests
- `test_color_profile_gui.py` — 3 tests
- `test_qt_pixmap_colorspaces.py` — 2 tests
- `test_print_colorspace.py` — 2 tests
- `test_render_colorspace.py` — 2 tests

## Lint Status

No new violations introduced. Pre-existing 22 E402/E701 violations remain unchanged.

## Summary Statistics

- **Files touched:** 5 (controller, model, printing, view)
- **Lines added:** 487
- **Lines removed:** 484
- **Net change:** +3 (cleanup operations mostly self-neutral)
- **Complexity:** Reduced through consolidation and helper extraction
- **Maintainability:** Improved; less duplication, clearer intent, centralized fallible conversions

## Next Steps (Post-Archive)

1. Update `docs/ARCHITECTURE.md` if module responsibilities changed (none in this pass).
2. Update `docs/PITFALLS.md` with C++ object lifetime gotcha.
3. Update `TODOS.md` to mark F4 color profile as complete.
