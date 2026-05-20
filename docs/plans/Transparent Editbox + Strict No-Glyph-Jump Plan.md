# Transparent Editbox + Strict No-Glyph-Jump Plan

## Summary

Implement and lock a hybrid editing visual contract that keeps the editbox transparent, hides underlying PDF glyphs
during editing, and enforces a strict <= 1% glyph-size/position deviation rule through deterministic, tamper-evident
acceptance gates across a multi-DPI matrix.

## Implementation Changes

1. Runtime visual contract (view/text_editing.py)

- Keep QTextEdit chrome transparent (background: transparent, no autofill on editor/viewport, no border).
- Keep scene mask as the only underlay that hides original page text while editing; enforce mask/editor z-order (mask <
editor) every refresh.
- Preserve hybrid paint policy:
- text == original: paint frozen first-frame capture (pixel-faithful open/restore state).
- text != original: paint preview generated through the same MuPDF/CSS path as commit.
- Preview invalid/blank fallback: frozen frame + native glyph fallback with transparent background.
- Ensure mask refresh is triggered on every geometry-affecting state change: create, drag/move, zoom/rerender, font/
size/color changes, page reassignment.

2. Strict metric model + tests (test_scripts/test_no_jump_editor_geometry.py)

- Add normalized metrics for every fidelity check:
- glyph_height_px from reference ink bbox.
- norm_dx = abs(dx_px) / glyph_height_px, same for dy, dw, dh.
- font_scale_error = abs(observed_em_px - expected_em_px) / expected_em_px.
- Expand matrix coverage:
- Render scales: 0.67, 1.0, 1.5, 2.0, 3.0, 4.0.
- Logical DPI: 96, 120, 144, 192, 300.
- Rotations: 0, 90, 180, 270.
- Font cases: helv, cjk, unknown_font.
- Add missing scenario families:
- Paragraph-mode reopen cycles.
- Save → close → reopen file → edit same target.
- Cross-page move + reopen parity.
- Keep and extend negative controls (intentional geometry/font/rotation faults must fail).

3. Gate hardening (scripts/verify_no_jump.py)

- Update hardcoded required case set to include the expanded DPI/scale/rotation/mode matrix.
- Enforce exact case-set equality and minimum coverage invariants in verifier (not only test module).
- Raise reopen-cycle baseline to strict mode default 20 and assert minimum >=20 for gate runs.
- Validate new normalized metric keys from test artifacts and reject artifacts missing strict metrics.
- Keep two-run freshness checks, manifest match checks, signoff hash verification, and post-suite artifact rehash.

## Public Interfaces / Contracts

1. No end-user UI/API behavior changes; this is a rendering-fidelity hardening.
2. Test artifact schema change: metrics JSON must include normalized fidelity keys (glyph_height_px, normalized drift,
 font-scale error).
 3# Transparent Editbox + Strict No-Glyph-Jump Plan

## Summary

Implement and enforce a strict visual contract for text editing:

1. Editbox chrome is transparent.
2. Original page text under the editor is hidden by an opaque scene mask.
3. Unchanged text state uses frozen first-frame raster (pixel-faithful to pre-click PDF).
4. Mutated text state uses preview rendering aligned with commit rendering.
5. Acceptance gates fail if glyph geometry or scale diverges by more than 1% (normalized), across a strict DPI/scale/
 rotation matrix.

## Implementation Changes

1. Runtime contract hardening in view/text_editing.py.
2. Keep transparent editor behavior (background: transparent, no autofill) and preserve mask-under-editor z-order (mask
 < editor).
3. Keep paint policy explicit and invariant-based:
4. text == original: draw frozen frame.
5. text != original: draw preview-rendered frame.
6. Preview fail-safe: frozen frame + native text only as emergency fallback.
7. Refresh/reposition mask on all editor-geometry-affecting events (open, drag, zoom rerender, cross-page movement,
 font/size change).
8. Add internal assertion helpers for scene-mask coverage and z-order invariants.
9. Strict metrics + case expansion in test_scripts/test_no_jump_editor_geometry.py.
10. Add normalized glyph metrics:
11. glyph_size_error_pct = abs(observed - expected) / expected.
12. geometry_error_pct for x/y/w/h against reference glyph bbox.
13. Tighten/replace fixed-pixel-only checks with normalized <= 1% checks.
14. Expand matrix coverage:
15. Render scales: 0.67, 1.0, 1.5, 2.0, 3.0, 4.0.
16. Logical DPI: 96, 120, 144, 192, 300.
17. Font cases: helv, cjk, unknown_font.
18. Rotations: 0, 90, 180, 270.
19. Add missing scenario tests:
20. Paragraph-mode reopen cycle stability.
21. Save-close-reopen-file then edit same target stability.
22. Cross-page move then reopen/edit stability.
23. 20-cycle reopen stress (NO_JUMP_REOPEN_CYCLES default 20).
24. Preserve and extend negative controls (intentional +2px shift, wrong font-size feed, mask-disable simulation) that
 must fail.
25. Gate/spec hardening in scripts/verify_no_jump.py.
26. Mirror full strict case set in verifier hardcoded expected IDs.
27. Enforce exact-case-set equality (missing/extra/duplicate all fail).
28. Enforce matrix invariants (minimum scales, DPIs, rotations, font families).
29. Raise reopen minimum to 20 cycles in gate default.
30. Require strict metric keys in artifact metrics.json and reject runs missing them.
31. Keep double-run isolation, artifact freshness checks, signoff hash binding, and post-suite rehash checks.

## Public Interfaces / Contracts

1. No end-user UI/API surface change.
2. Test artifact schema (test_artifacts/no_jump/*/metrics.json) is extended with normalized strict keys, including:
3. geometry_error_pct_x, geometry_error_pct_y, geometry_error_pct_w, geometry_error_pct_h.
4. glyph_size_error_pct.
5. render_scale, logical_dpi, rotation, target_mode, run_id.
6. Gate contract updates:
7. verify_no_jump.py required case IDs and invariants are expanded.
8. NO_JUMP_REOPEN_CYCLES default becomes 20 (lower values only by explicit override in non-gate local runs).

## Strict Acceptance Criteria

1. AC-01 Transparent editor: active editor widget and viewport have no opaque fill; stylesheet/background checks pass.
2. AC-02 Hidden underlay glyphs: mask item must fully cover editor scene rect (<=0.5px edge tolerance), be opaque, and
 remain below editor z-order.
3. AC-03 Open-state fidelity: on click-to-edit (unchanged text), changed pixels in editor region <=1% versus pre-click
 reference.
4. AC-04 Restore fidelity: type-then-delete back to original returns to <=1% changed pixels versus open-state reference.
5. AC-05 Glyph geometry strictness: normalized geometry errors (x,y,w,h) each <=1% in every matrix case.
6. AC-06 Glyph scale strictness: glyph_size_error_pct <= 1% in every matrix case.
7. AC-07 Rotation strictness: AC-03..AC-06 pass for rotations 0, 90, 180, 270.
8. AC-08 Font/fallback strictness: AC-03..AC-06 pass for helv, cjk, and fallback/unknown font cases.
9. AC-09 Session durability: 20 reopen cycles keep geometry/scale within strict thresholds in run mode and paragraph
 mode.
10. AC-10 Persistence durability: save-close-reopen-file then edit same target still passes strict thresholds.
11. AC-11 Negative controls: intentionally broken paths must fail the strict gate (proves gate sensitivity).
12. AC-12 Reproducibility: two isolated gate runs produce identical manifests and fresh artifacts; tamper-evident
 signoff hashes remain stable after full-suite execution.

## Test Plan

1. Targeted strict suite:
2. python -m pytest test_scripts/test_no_jump_editor_geometry.py -q
3. GUI transparency/mask regressions:
4. python -m pytest test_scripts/test_text_editing_gui_regressions.py -k "transparent or mask" -q
5. Full strict gate:
6. python scripts/verify_no_jump.py
7. Gate passes only when AC-01..AC-12 all hold and verifier exits 0.

## Assumptions and Defaults

1. “Any DPI” is implemented as strict matrix coverage plus normalized metrics; mathematical proof for every possible DPI
 is not finite-testable.
2. Unchanged-text pixel fidelity relies on frozen first-frame rendering; this is intentional and required for <=1%
 guarantee.
3. Quantization noise is handled by normalized metrics and high-scale coverage rather than relaxing thresholds.
4. Existing architecture (transparent editor + scene mask + frozen/open branch + preview/mutated branch) remains the
 baseline, not replaced.