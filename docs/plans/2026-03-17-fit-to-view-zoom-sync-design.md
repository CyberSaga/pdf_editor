# Fit-To-View Zoom Sync Design

**Date:** 2026-03-17

**Goal:** Make the `適應畫面` action update the stored zoom state to the same scale the user actually sees, so later zoom adjustments remain accurate and predictable.

## Problem

- The current `適應畫面` button in `view/pdf_view.py` calls `QGraphicsView.fitInView(...)` directly.
- That changes the visible transform immediately, but it does not update `view.scale`, per-session UI state, or the zoom combo text.
- Later zoom actions continue from the stale stored scale instead of the real on-screen scale.
- The result is a visible jump and inconsistent zoom math after the user presses `適應畫面`.

## Scope

- Keep the `適應畫面` button and its existing user-facing meaning.
- Replace the button's direct `fitInView(...)` zoom behavior with the same contain-scale calculation already used by fullscreen fit.
- Route the action through the normal scale pipeline so one code path owns zoom state.
- Update regression coverage for fit-to-view behavior and zoom-state synchronization.

## Non-Goals

- Do not redesign wheel zoom debounce behavior.
- Do not remove the resize-event `fitInView(...)` fallback used outside the button flow.
- Do not refactor unrelated continuous-scene rendering code in this change.

## Architecture

- `view/pdf_view.py`
  - Keep `_fit_to_view()` as the button entry point.
  - Change `_fit_to_view()` so it computes the current page's contain scale and emits `sig_scale_changed(...)` instead of mutating the `QGraphicsView` transform directly.
  - Continue using `_update_page_counter()` as the single place that reflects `self.scale` into the zoom combo text.
- `controller/pdf_controller.py`
  - Keep `change_scale(...)` as the single source of truth for persisted zoom state.
  - Let `change_scale(...)` continue updating `view.scale`, session UI state, and the continuous-page scene rebuild.
- `test_scripts/test_multi_tab_plan.py`
  - Replace the old test that only asserts viewport centering after direct `fitInView(...)`.
  - Add coverage that the fit action uses the computed contain scale and synchronizes the stored zoom value and displayed percentage.

## Design Decisions

### 1. Remove direct button-driven `fitInView(...)` zoom

- The button should no longer create a second transient zoom mechanism.
- A single zoom source is easier to reason about, easier to test, and avoids stale state.

### 2. Reuse `compute_contain_scale_for_page(...)`

- Fullscreen fit already uses `compute_contain_scale_for_page(...)` plus `change_scale(...)`.
- Reusing that path makes normal fit and fullscreen fit consistent.
- This also keeps the scale derived from the actual rendered page size (`_render_scale`) and viewport size, which is the most accurate available input for the current scene.

### 3. Preserve performance by avoiding double work

- The new flow should not first apply `fitInView(...)` and then trigger a full rebuild.
- The button should compute once and render once through the official zoom path.
- This avoids a temporary transform jump followed by a second redraw.

### 4. Keep the resize fallback untouched

- There is another `fitInView(...)` call in `_resize_event()`.
- That path is not part of the button-triggered bug and may still serve non-continuous or early-scene fallback behavior.
- It should stay out of scope for this targeted fix.

## Expected User Outcome

- Pressing `適應畫面` updates the visible zoom and the recorded zoom to the same value.
- The zoom combo shows the actual fitted percentage after the action completes.
- Any later wheel zoom, manual percentage entry, or other zoom adjustment starts from the correct current scale instead of an old one.

## Error Handling

- If no valid target page rect is available, the fit action should no-op.
- If the computed scale is outside supported bounds, existing scale clamping behavior remains in force through the shared zoom path.

## Testing Strategy

- Verify that triggering fit on a later page targets the current page rather than the full scene.
- Verify that fit updates `view.scale`.
- Verify that fit updates the zoom combo display to the same percentage.
- Verify that the shared controller zoom path is used, preventing state divergence after fit.
