# Plan: Hard "No-Jump" Acceptance Gate for Inline Text Editor

## Context

When a user clicks a line of text in the PDF viewer, the inline editor
(`PreviewBackedInlineTextEditor`) opens with its `PreviewRenderer` preview.
Users see glyphs change size at that moment — a "jump" between the original
PDF rendering and the editor's first frame.

Recent commits landed real MuPDF rasterization in `PreviewRenderer.render()`
(commit b97dd62) and fixed several geometry/DPI bugs. However the only
regression guard for glyph size is `test_inline_editor_glyph_height_matches_
pdf_at_render_scale_2x` with **20% tolerance** — far too loose to catch the
sub-1% pixel jump the user wants eliminated.

This plan creates a Codex `/goal` that drives a hard, evidence-backed "no
jump" validation suite with negative-control and required artifacts, then
invokes Codex against it.

---

## Phase 1 — Write the Codex goal file

Create `docs/plans/goal-no-jump-editor-geometry.md` with the following
content (verbatim goal for Codex):

```
# Goal: No-Jump Inline Editor — Hard Acceptance Gate

## Problem
Clicking to edit text causes a visible glyph-size jump between the original
PDF frame and the first inline-editor frame.

## Completion rule
Complete ONLY when AC 1–7 all pass, artifact files are produced, and the
negative-control test FAILS as expected. If any gate is unmet, continue
iterating. NEVER assert completion until all gates are satisfied.

## Acceptance Criteria

### AC 1 — Editor-open geometry match
For every test case (see matrix below), measure the inline editor's actual
screen geometry vs the expected PDF glyph bbox in screen space.
Pass thresholds (all must hold):
  |x drift|    <= 0.5 px
  |y drift|    <= 0.5 px
  |width drift| <= 1.0 px
  |height drift| <= 1.0 px
  font_size_ratio (editor_px / pdf_px) in [0.99, 1.01]
  line_height_ratio in [0.99, 1.01]

### AC 2 — No perceptible frame jump
Between the reference PDF crop (before click) and the PreviewRenderer output
(first editor frame):
  changed_pixels / total_pixels <= 0.01  (< 1%)
  no single-region translation or scale "pop" > 1 px

### AC 3 — Matrix coverage (all combinations must pass AC 1 and AC 2)
  render_scale: 0.67, 1.0, 2.0   (= zoom 67%, 100%, 200%)
  simulated DPR: 1.0, 2.0         (mock _widget_logical_dpi() → 96, 192)
  font cases: "helv" (embedded Latin), "cjk" (CJK), "unknown_font" (fallback)
  rotated text: rotation=90 (one case)
  Total: 3 × 2 × 3 + 1 = 19 test cases minimum

### AC 4 — Negative-control test (proves suite can fail)
Inject a known-bad offset or scale into the geometry pipeline:
  Case A: add +2 px to the x position returned by _compute_editor_proxy_layout
  Case B: multiply font_size by 1.03 before passing to PreviewRenderer
For each injected case, the relevant AC 1 or AC 2 assertion MUST fail.
If either negative-control test PASSES, the suite is not a valid gate —
fix the test so it correctly detects the injected error before proceeding.

### AC 5 — Artifacts for every "fixed" claim
Each test run saves to test_artifacts/no_jump/<test_id>/:
  before_<test_id>.png   — reference PDF crop at that region
  after_<test_id>.png    — PreviewRenderer output for that case
  diff_<test_id>.png     — pixel overlay diff (highlight deltas in red)
  metrics_<test_id>.json — {x_drift, y_drift, w_drift, h_drift,
                             font_size_ratio, line_height_ratio,
                             changed_px_pct, render_scale, dpi, font_case}
No artifacts = the test is not accepted, regardless of pass/fail.

### AC 6 — Manual UX signoff
Run the app on test_files/test-colored-background.pdf and
test_files/test-complexed-layout.pdf. Click 10 representative text lines
each. Record: zero visible jump observed. Any pop fails even if numerics pass.
Document the result in test_artifacts/no_jump/manual_signoff.md.

### AC 7 — Stability gate
Run `pytest test_scripts/test_no_jump_editor_geometry.py` twice consecutively
with zero failures or flakes. Report both run outputs.

---

## Implementation steps

### Step 1 — Geometry helpers (unit-testable, no Qt required)
In test_scripts/test_no_jump_editor_geometry.py (or a shared helper):

  measure_expected_screen_rect(pdf_bbox, render_scale, page_y_offset)
    → fitz.Rect  (= pdf_bbox * render_scale, y shifted by page_y_offset)

  measure_editor_screen_rect(pdf_bbox, render_scale, page_y_offset,
                              rotation, pdf_font_size, content_height_px)
    → dict  (calls _compute_editor_proxy_layout, returns x/y/w/h)

  compute_geometry_deltas(expected, actual) → dict

  font_size_ratio(pdf_size, render_scale, logical_dpi)
    → float  (= _display_font_pt(pdf_size, rs) * logical_dpi / 72
                / (pdf_size * rs))
    Must be in [0.99, 1.01] for all rs in {0.67, 1.0, 2.0}.

Source locations:
  view/text_editing.py:434  _display_font_pt()
  view/text_editing.py:473  _compute_editor_proxy_layout()
  view/text_editing.py:423  _widget_logical_dpi()

### Step 2 — Geometry parametrized tests (AC 1, AC 3)
Use pytest.mark.parametrize over the matrix from AC 3.
Mock _widget_logical_dpi() to return 96.0 (DPR=1) or 192.0 (DPR=2).
For rotation=90 test, verify width/height are swapped correctly and pos_x
is shifted by height_px (per _compute_editor_proxy_layout lines 488-493).

### Step 3 — Pixel diff test (AC 2, AC 3)
For each font case at each render_scale:
  1. Build a tiny synthetic PDF page with one text span (same approach as the
     existing test at test_text_editing_fidelity_suite.py:306).
  2. Render the page via page.get_pixmap(matrix=fitz.Matrix(rs, rs)) → ref_img.
  3. Run PreviewRenderer.render(..., rect_pt=span_rect, render_scale=rs)
     → preview_img.
  4. Align: ref_img and preview_img should be the same pixel dimensions.
  5. Compare: for each pixel, mark as "changed" if |L_ref - L_preview| > 10
     (lightness threshold to ignore JPEG-style rounding).
  6. changed_pct = changed_count / (w * h)
  7. Assert changed_pct <= 0.01.
  Save before/after/diff images per AC 5.

Key: PreviewRenderer creates its own temp page (width=rect_pt.width,
height=rect_pt.height) and inserts the same htmlbox — this mirrors exactly
what the commit will do. The reference is the same page.get_pixmap call.
Both use the same MuPDF engine path, so divergence > 1% indicates a bug
in css/html construction or rect alignment.

### Step 4 — Negative-control tests (AC 4)
Parametrize with @pytest.mark.parametrize("inject_bad", [True, False]).
When inject_bad=True:
  Case A: patch _compute_editor_proxy_layout to add +2.0 to returned pos_x.
  Case B: patch PreviewRenderer.render to multiply font_size arg by 1.03.
Use monkeypatch or a thin wrapper.
Assert that when inject_bad=True, the relevant AC 1 / AC 2 test FAILS
(catch AssertionError with pytest.raises).
When inject_bad=False, the test passes normally (the real good-path case).

### Step 5 — Artifact directory and JSON writer
Create test_artifacts/no_jump/ if absent.
Helper save_artifacts(test_id, before_img, after_img, metrics_dict):
  - Save before/after as PNG via QImage.save(path)
  - Compute diff: create QImage same size, paint red at changed pixels
  - Save diff as PNG
  - Write metrics as JSON

### Step 6 — Tighten existing test
In test_text_editing_fidelity_suite.py:356, change:
  tolerance = max(3, int(0.20 * ref_ink_h))
to:
  tolerance = max(2, int(0.01 * ref_ink_h))
This is not optional — the existing 20% guard is superseded by AC 2.
If this tightening causes the existing test to fail, that is a real bug to fix,
not a reason to revert the tolerance.

### Step 7 — Documentation + TODOS
After all AC pass:
  Update TODOS.md: add "Done — no-jump acceptance gate (AC 1-7)" entry.
  Update docs/PITFALLS.md: add entry for DPR-scaling divergence if discovered.
  Update docs/ARCHITECTURE.md §10 if PreviewRenderer contract changed.
```

---

## Phase 2 — Invoke Codex

Run:
```
/goal docs/plans/goal-no-jump-editor-geometry.md
```

Codex must iterate until all AC pass and produce artifacts; it must not
self-declare done before that point.

---

## Critical files

| File | Relevance |
|------|-----------|
| `view/text_editing.py:225–335` | `PreviewRenderer.render()` — rasterization engine |
| `view/text_editing.py:374–386` | `paintEvent` — what user sees on first frame |
| `view/text_editing.py:434–446` | `_display_font_pt()` — DPI→point-size formula |
| `view/text_editing.py:473–499` | `_compute_editor_proxy_layout()` — placement formula |
| `view/text_editing.py:423–431` | `_widget_logical_dpi()` — DPI source |
| `model/pdf_model.py` | `_build_insert_css()`, `_convert_text_to_html()` |
| `test_scripts/test_text_editing_fidelity_suite.py:306–363` | Existing 20%-tolerance test (tighten to 1%) |
| `test_scripts/conftest.py` | `qapp` fixture (offscreen Qt) |
| `test_files/test-colored-background.pdf` | Manual signoff PDF |
| `test_files/test-complexed-layout.pdf` | Manual signoff PDF (CJK) |

---

## Verification

After Codex completes:

1. `pytest test_scripts/test_no_jump_editor_geometry.py -v` — should show all
   parametrized cases green, negative-control cases showing expected failure.
2. Inspect `test_artifacts/no_jump/` — PNG and JSON files present for each case.
3. Verify `test_artifacts/no_jump/manual_signoff.md` exists and records "zero
   visible jump" on both reference PDFs.
4. Run the full suite once more: `pytest test_scripts/` — no regressions.
5. Check `ruff check .` — zero new violations.
