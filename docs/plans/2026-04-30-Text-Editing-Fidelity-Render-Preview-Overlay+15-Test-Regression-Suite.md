# Text Editing Fidelity: Render-Preview Overlay + 15-Test Regression Suite

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Replace the Qt-rendered inline editor visual with a PyMuPDF-rasterized live preview, so glyph appearance is **bit-for-bit identical** across:
1. **Before** — original PDF rendering beneath the editor
2. **During** — what the user sees inside the inline editor box (a `QPixmap` rasterized by the same engine that will commit)
3. **After** — the re-rendered PDF after commit

**Success metric:** A 15-test regression suite covering 15 distinct fidelity dimensions — **all 15 must pass with zero misses** before this work is considered done.

**Branch:** Continue on `codex/best-text-editing-ux`.

**Tech stack:** PyMuPDF (`fitz`), pytest, PySide6, `model/pdf_model.py`, `view/text_editing.py`.

---

## Context

### Why a render-preview overlay

The recent fixes (`c1d8d79`, `1ffe189`, `fbfe4c6`, `cc55872`) improved metric matching between Qt's font rasterizer and MuPDF's, but the two engines remain **fundamentally different rasterizers**. Qt's hinting, kerning, glyph fallback, line-breaking, and HarfBuzz integration do not match MuPDF's pixel-for-pixel — and never can without unifying the renderer.

The render-preview overlay strategy eliminates this by making the editor's *visual layer* a PyMuPDF rasterization of the in-progress edit. Qt is reduced to:
- **Caret position** — drawn manually as a thin scene line.
- **Selection rectangle** — drawn manually as a translucent scene rect.
- **Text model** — `QTextDocument` (cursor, undo/redo, key events) — its rendering output is suppressed.

The pixels you see during edit are produced by the **same** `insert_htmlbox(...)` call that will produce the committed PDF. By construction: **before == during == after**.

### Web research — extracted insights informing this design

- **PyMuPDF `insert_htmlbox` uses HarfBuzz** for shaping with full Unicode support; font face matters because MuPDF substitutes silently when the requested font is unavailable. ([Artifex blog](https://artifex.com/blog/mastering-pdf-text-with-pymupdfs-insert-htmlbox-what-you-need-to-know))
- **Qt `setPointSizeF` is device-independent**; combining with `pixelSize = pointSize × dpi/72` derivation matters only for caret/selection rect math — not for glyph appearance once we suppress Qt's text rendering. ([Qt docs](https://doc.qt.io/qt-6/qfont.html))
- **QGraphicsScene + QGraphicsProxyWidget supports `paintEvent` overrides** cleanly. ([Qt forum](https://forum.qt.io/topic/14826/wysiwyg-text-editor-approach-qgraphicsscene-text-object))
- **Adobe Acrobat's approach** depends on font-installed-on-system parity. The render-preview overlay sidesteps that requirement entirely by rendering with the same engine that commits.

### Tradeoffs (be transparent about them)

| Aspect | Qt-overlay (current) | Render-preview overlay (this plan) |
|---|---|---|
| Glyph appearance | Approximate (DPI-corrected) | **Bit-exact** to commit |
| Caret position math | Native Qt | Custom: derive from `QTextCursor.cursorRect()`; will be slightly offset from MuPDF glyph baselines |
| Selection rendering | Native Qt | Custom: derive from selection cursor rects; same minor offset |
| IME / CJK composition | Native Qt | Native Qt — but composition glyphs render via Qt momentarily until next debounce tick |
| Performance | Free | One MuPDF rasterization per debounce window (~150ms idle after keystroke); cached |
| Implementation cost | Done | ~600–900 lines new + tests |
| Risk of regression | Low | Medium — surface is large |

**The caret/selection minor offsets are accepted** because the user's stated goal is "glyph style looks same"; caret position offsets of <1px do not break that contract.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Scene                                                                │
│                                                                      │
│  ┌────────── QGraphicsProxyWidget (rect = source rect × render_scale)│
│  │                                                                   │
│  │   ┌─── PreviewBackedInlineTextEditor (QTextEdit subclass) ────┐   │
│  │   │                                                            │   │
│  │   │  paintEvent override:                                      │   │
│  │   │    1. drawPixmap(0,0, _preview_qimage)   ← MuPDF render    │   │
│  │   │    2. drawSelectionRects(...)             ← from cursor    │   │
│  │   │    3. drawCaret(...)                      ← from cursor    │   │
│  │   │                                                            │   │
│  │   │  textChanged → debounced (150 ms) → re-render preview     │   │
│  │   │                                                            │   │
│  │   └────────────────────────────────────────────────────────────┘   │
│  │                                                                   │
│  └───────────────────────────────────────────────────────────────────┘
│                                                                      │
│  Underlay: page pixmap (from PDFController)                          │
└──────────────────────────────────────────────────────────────────────┘
```

### Components

#### 1. `PreviewRenderer` (new — `view/text_editing.py`)

```python
class PreviewRenderer:
    def __init__(self) -> None:
        self._cache_key: tuple | None = None
        self._cache_image: QImage | None = None

    def render(
        self,
        *,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple[float, float, float],
        member_spans: list[dict] | None,
        rect_pt: fitz.Rect,
        rotation: int,
        render_scale: float,
    ) -> QImage:
        """Rasterize the proposed edit content via insert_htmlbox at the same
        DPI / settings the commit will use, returning a QImage sized to
        rect_pt.width × rect_pt.height × render_scale (rotation-aware).
        """
        key = (text, font_name, float(font_size), color, int(rotation), float(render_scale), int(rect_pt.width*100), int(rect_pt.height*100))
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        # Open temp doc; build CSS via shared helper; insert_htmlbox; pixmap
        ...
        self._cache_key = key
        self._cache_image = qimage
        return qimage
```

Reuses **existing helpers**:
- `model.pdf_model._build_insert_css(...)` — same CSS as commit
- `model.pdf_model._convert_text_to_html(...)` — same HTML conversion
- `model.pdf_model._build_multi_style_html(...)` — for multi-style preservation
- A new `model.pdf_model._classify_insert_path(text, member_spans, rect)` extracted from `_apply_redact_insert` (returns `"fast" | "htmlbox"`) — used by both preview and commit so they always agree on path selection. Path-selection logic from `_apply_redact_insert` (lines ~3499-3543) is moved here and called by both sides.

#### 2. `PreviewBackedInlineTextEditor` (new — `view/text_editing.py`)

`QTextEdit` subclass. Holds a `QTextDocument` (so cursor/undo/key events still work natively) but suppresses default glyph rendering via `paintEvent` override.

```python
class PreviewBackedInlineTextEditor(QTextEdit):
    focus_out_requested = Signal()

    def __init__(self, text: str, renderer: PreviewRenderer) -> None:
        super().__init__()
        self._renderer = renderer
        self._preview_image: QImage | None = None
        self._render_args: dict = {}
        self._debounce = QTimer(self); self._debounce.setSingleShot(True); self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._regenerate_preview)
        self.setPlainText(text)
        self.textChanged.connect(self._debounce.start)

    def configure_render_context(self, **kwargs) -> None:
        """Called once on creation by create_text_editor with all the
        non-text params (font, size, color, rect, rotation, render_scale)."""
        self._render_args.update(kwargs)
        self._regenerate_preview()

    def _regenerate_preview(self) -> None:
        text = self.toPlainText()
        self._preview_image = self._renderer.render(text=text, **self._render_args)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        if self._preview_image is not None:
            painter.drawImage(0, 0, self._preview_image)
        self._draw_selection(painter)
        self._draw_caret(painter)
        painter.end()
        # Do NOT call super().paintEvent — that's how we suppress Qt glyphs.
```

`_draw_selection` and `_draw_caret` use `QTextCursor.cursorRect()` and selection start/end cursors to paint a thin caret line and translucent selection rects in scene space.

#### 3. Modified `create_text_editor` (in `view/text_editing.py`)

Replace the `InlineTextEditor(text)` instantiation with `PreviewBackedInlineTextEditor(text, self._preview_renderer)`. Call `editor.configure_render_context(...)` with the resolved params.

The existing `_compute_editor_proxy_layout`, `_viewport_editor_height_cap_px`, mask-color sync, font-family combo updates, and undo/redo signal hookups are preserved unchanged.

The Qt font (`qt_font_obj.setPointSizeF(display_font_pt)`) is still set on the editor so caret rect math uses appropriately sized line metrics (not for glyph rendering).

#### 4. Path-selection extraction (`model/pdf_model.py`)

Move the existing path-selection logic from `_apply_redact_insert` (currently at ~3499–3543) into a new module-level function:

```python
def _classify_insert_path(
    *,
    new_text: str,
    member_spans: list[dict],
    rect: fitz.Rect,
    rotation: int,
    preserve_multi_style: bool,
) -> str:
    """Return 'fast' if the insert_text origin-preserving fast path applies;
    'htmlbox' otherwise. Single source of truth for both commit and preview."""
    ...
```

Both `_apply_redact_insert` and `PreviewRenderer.render` call this so preview and commit always pick the same path.

---

## Critical files

| File | Lines | Role |
|------|-------|------|
| `view/text_editing.py` | ~270, ~423–550 | Add `PreviewRenderer`, `PreviewBackedInlineTextEditor`; modify `create_text_editor` |
| `model/pdf_model.py` | ~3388–3543 | Extract `_classify_insert_path`; expose `_build_insert_css`, `_convert_text_to_html`, `_build_multi_style_html` for `PreviewRenderer` (already module-level) |
| `test_scripts/test_edit_text_helpers.py` | append | New tests 1–4, 6–13 (model-level fidelity) |
| `test_scripts/test_text_editing_gui_regressions.py` | append | New tests 5, 14, 15 + fakes for `PreviewRenderer` |
| `test_scripts/conftest.py` | unchanged | Reuse `qapp` fixture |

---

## The 15 fidelity scenarios

Each maps to one test. Tests 5, 14, 15 are reformulated for the render-preview architecture (they assert preview pixmap properties, not Qt widget font properties).

### Group 1 — Font metrics (5 tests)

| # | Test name | Asserts |
|---|-----------|---------|
| 1 | `test_latin_single_line_edit_preserves_font_pt` | 12pt Latin, content edit, post-commit `hit.size` drift < 0.1pt |
| 2 | `test_cjk_single_line_edit_preserves_height` | 14pt CJK, htmlbox path, `hit.target_bbox.height` drift ≤ 1.0pt |
| 3 | `test_fractional_font_pt_round_trips_through_edit` | 9.5pt → 9.5pt (no integer truncation) |
| 4 | `test_repeated_ten_edits_cumulative_drift_under_half_pt` | 10 successive edits, total drift < 0.5pt |
| 5 | `test_preview_pixmap_dimensions_match_render_scale_2x` | At `render_scale=2.0`, `PreviewRenderer.render(...)` returns a `QImage` whose `width()` == `int(round(rect.width × 2.0))` and `height() ≥ int(round(rect.height × 2.0))` (height may exceed if text wraps to more lines). |

### Group 2 — Style preservation (3 tests)

| # | Test name | Asserts |
|---|-----------|---------|
| 6 | `test_bold_flag_preserved_through_edit` | Bold span, edit content; commit retains bold (post-edit `hit.font` includes `Bd`/`Bold`) |
| 7 | `test_italic_flag_preserved_through_edit` | Italic span, edit content; commit retains italic font marker |
| 8 | `test_non_black_color_preserved_through_edit` | RGB (0.8, 0.2, 0.1), edit content; per-channel drift < 0.02 |

### Group 3 — Layout fidelity (4 tests)

| # | Test name | Asserts |
|---|-----------|---------|
| 9 | `test_multi_line_wrap_column_matches_source` | Multi-line span with known wrap point; edit one char on line 2; post-commit line breaks at same character offsets |
| 10 | `test_tight_leading_honored_on_commit` | `line_height = 0.85 × size`; committed bbox.height stays within 0.5pt of original |
| 11 | `test_loose_leading_honored_on_commit` | `line_height = 1.5 × size`; committed bbox.height stays within 0.5pt of original |
| 12 | `test_position_anchor_drift_under_half_pt_at_all_corners` | Edit at 4 page corner regions; `(x0, y0)` drift < 0.5pt for all 4 |

### Group 4 — Edge cases (3 tests)

| # | Test name | Asserts |
|---|-----------|---------|
| 13 | `test_mixed_latin_cjk_span_renders_both_scripts` | Span "ABC 中文 XYZ"; edit; page text contains both Latin and CJK; CSS includes both font-family entries |
| 14 | `test_vertical_rotated_text_edit_preserves_orientation_and_size` | Rotation=90° span, edit; committed text still vertical; preview pixmap dimensions are rotated (height in source-axis); `hit.size` drift < 0.5pt |
| 15 | `test_preview_pixmap_width_equals_source_rect_times_render_scale` | At `render_scale=1.5` and `rect.width=200pt`, `PreviewRenderer.render(...).width() == 300` exactly. No page-margin slack. |

---

## Implementation phases (TDD, with checkpoints)

### Phase 0 — Setup and baseline

- Confirm branch `codex/best-text-editing-ux`
- Run baseline: `pytest test_scripts/ -q --tb=short` — record pass count
- Create scratchpad notes file (not committed) for design notes during implementation

### Phase 1 — Path-selection extraction (foundation)

**Goal:** No behavior change. Just refactor.

1. Read `_apply_redact_insert` (`model/pdf_model.py:3388–3620`) to understand current path-selection conditions.
2. Extract a pure function `_classify_insert_path(...)` that returns `"fast"` or `"htmlbox"`. Both branches in `_apply_redact_insert` consult it.
3. Run full suite — must be green (refactor-only).
4. Commit: `refactor(model): extract _classify_insert_path for shared use by preview and commit`

### Phase 2 — `PreviewRenderer` (no UI yet)

**Goal:** Build the renderer in isolation; unit-test it directly.

1. Add `PreviewRenderer` class to `view/text_editing.py`. Internally it imports `_build_insert_css`, `_convert_text_to_html`, `_build_multi_style_html`, `_classify_insert_path` from `model/pdf_model.py`. (Architecture: this is view → model, which is allowed; model already exposes these as module-level helpers.)
2. Implement `render(...)` with caching.
3. Add tests 5 and 15 (`test_preview_pixmap_dimensions_match_render_scale_2x`, `test_preview_pixmap_width_equals_source_rect_times_render_scale`) — both should pass once `PreviewRenderer.render` is correctly producing QImages.
4. Commit: `feat(text-edit): PreviewRenderer rasterizes proposed edits via insert_htmlbox`

### Phase 3 — `PreviewBackedInlineTextEditor` (UI integration)

**Goal:** Wire the renderer into the live editor.

1. Subclass QTextEdit as `PreviewBackedInlineTextEditor` in `view/text_editing.py`. Implement `paintEvent` override, debounce, `configure_render_context`.
2. Implement `_draw_caret` and `_draw_selection` using `QTextCursor.cursorRect()` and selection cursors.
3. Modify `create_text_editor` to instantiate `PreviewBackedInlineTextEditor` instead of `InlineTextEditor`. Pass `_preview_renderer` (one per `TextEditManager` instance, lazily created).
4. Manual smoke test: open `test_files/test-horizontal-texts.pdf`, click any text, verify the editor shows the rasterized preview (not Qt glyphs).
5. Commit: `feat(text-edit): paint inline editor from MuPDF preview pixmap, suppress Qt glyph rendering`

### Phase 4 — Tests 1–4 (Group 1 font metrics, model-level)

**Goal:** Regression-guard the existing fixes for font size precision and cumulative drift.

For each of tests 1–4:
- Use `_make_pdf_at_size`, `_apply_insert`, `_measure_span_at`, `_page_contains_text` helpers in `test_edit_text_helpers.py`.
- Each test follows: synthetic PDF → probe span → edit → re-probe → assert drift bound.
- Commit per group of 2 tests.

### Phase 5 — Tests 6–8 (Group 2 style preservation)

**Goal:** Regression-guard bold/italic/color end-to-end.

Test 6 (bold) and 7 (italic) require building a synthetic PDF with bold/italic flags. Use `page.insert_text(..., fontname="...", fontfile="...")` with system bold/italic font files (Windows: `arialbd.ttf`, `ariali.ttf`). Verify `hit.flags & 16` (bold) or `hit.flags & 2` (italic) both pre- and post-edit.

If post-edit flags are LOST, fix the propagation:
- In `_apply_redact_insert`, ensure `flags` from the resolved `member_spans[0]` are threaded into `_build_insert_css` as `font-weight: bold` / `font-style: italic`.
- Confirm `_convert_text_to_html` and `_build_multi_style_html` emit those CSS properties.

Test 8 (color): use `insert_text(..., color=(0.8, 0.2, 0.1))`. Edit. Assert `hit.color` channels drift < 0.02.

If color is LOST, fix in `_convert_text_to_html` (color attribute) or `_build_multi_style_html` (per-run color preservation).

Commit per fix.

### Phase 6 — Tests 9–12 (Group 3 layout fidelity)

**Goal:** Pin down line-height, wrapping, position-anchor.

- Test 9 (wrap column): build a multi-line PDF via `insert_htmlbox` with known wrap. Edit one char on line 2. Re-extract; verify line breaks at same character offsets.
- Test 10 (tight leading): build a PDF whose member_spans baseline-to-baseline ≈ 0.85 × size. Verify post-edit `bbox.height` matches original ±0.5pt.
- Test 11 (loose leading): mirror with 1.5× leading.
- Test 12 (corner anchor): build a PDF with text at 4 corners; loop edit each; assert `(x0, y0)` drift < 0.5pt.

If any fail, trace through `_build_insert_css` (line-height computation), `_apply_redact_insert` (anchor preservation), and `get_render_width_for_edit` (rect clamping at edges).

### Phase 7 — Tests 13–15 (Group 4 edge cases)

- Test 13 (mixed Latin+CJK): build PDF via `insert_htmlbox` with multi-script text. Edit. Verify both scripts present post-commit. Inspect the CSS path emitted by `_build_insert_css` to confirm both font-family entries appear.
- Test 14 (vertical/rotated): build PDF with rotation=90° via `insert_htmlbox(rect, html, css=css, rotate=90)`. Edit. Verify post-commit dimensions and orientation. Also assert preview pixmap from `PreviewRenderer.render(rotation=90)` has rotated dimensions (`width × height` swapped).
- Test 15 was implemented in Phase 2.

### Phase 8 — Final verification and cleanup

```bash
pytest test_scripts/ -q --tb=short    # zero new failures vs Phase 0 baseline
ruff check .                          # zero new violations
```

Manual GUI spot-check on `test_files/`:
1. `test-complexed-layout.pdf` — click `'在編輯文字時清除舊有文字的做法'` → edit one char → confirm preview matches commit visually
2. `test-colored-background.pdf` — click 60pt CJK heading → edit → confirm
3. `test-vertical-texts.pdf` — click any vertical text → edit → orientation preserved
4. `test-horizontal-texts.pdf` — click any Latin run → edit → font/size visually identical to neighbors

Update:
- `docs/PITFALLS.md` — add entries for new failure modes discovered during fixes
- `docs/ARCHITECTURE.md` — document the render-preview architecture (Phase 3 introduces a new editor class)
- `docs/solutions.md` — append a section on the architectural shift

### Phase 9 — Final commit

```bash
git add view/text_editing.py model/pdf_model.py test_scripts/ docs/
git commit -m "feat(text-edit): render-preview overlay editor + 15-test fidelity suite

Replaces Qt-rendered inline editor visual with a PyMuPDF-rasterized
live preview, debounced 150ms after each keystroke. Glyph appearance
is now bit-for-bit identical across before-edit / during-edit / after-
commit because all three states use the same insert_htmlbox engine.

Caret and selection are drawn manually from QTextCursor metrics; minor
sub-pixel offsets from MuPDF baselines are accepted as the tradeoff
for glyph-style identity.

Includes a 15-test regression suite covering: font pt size precision,
height stability, fractional sizes, cumulative drift, DPI scaling,
bold/italic/color preservation, multi-line wrap, tight/loose leading,
4-corner position drift, mixed Latin+CJK, vertical edit, and preview
pixmap width identity."
```

---

## Stop conditions

- **Continue iterating** while any of the 15 tests fails. Each failure → trace cause → fix → re-run.
- **Stop work** when:
  - All 15 tests pass
  - Full pre-existing suite still passes (no regressions vs Phase 0 baseline)
  - `ruff check .` is clean
  - Manual GUI spot-check on all 4 sample PDFs confirms before/during/after visual identity

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Caret drifts visibly from MuPDF glyph baselines | Tune `_draw_caret` to align caret X to `cursorRect().x()` and Y to span baseline derived from `member_spans`; tolerate ≤1px offset |
| Preview rasterization is too slow (debounce backlog) | Cache aggressively (only re-render when text or render_scale changes); profile first commit; if >100ms median, reduce DPI for in-edit preview and re-render at full DPI on commit |
| Selection rect misalignment when user click-drags | Acceptable until user complains; document in PITFALLS |
| IME composition glyphs render in Qt momentarily | Acceptable: the next debounce tick refreshes preview with the composed text |
| `_classify_insert_path` extraction breaks an existing edge case in `_apply_redact_insert` | Refactor in Phase 1 with no behavior change; full suite must stay green before Phase 2 begins |
| `insert_htmlbox` rasterization differs subtly from the actual commit due to temp-page coordinate setup | Use a temp page sized to `rect.width × rect.height` exactly, with `rotate=rotation` matching commit; insert at `temp_page.rect`, not at the source rect's page coordinates |

---

## Previously completed (do not redo)

On `codex/best-text-editing-ux`:
- `_line_ht` from `member_spans` and passing to `_build_insert_css` (`fbfe4c6`)
- `_build_insert_css` clamp moved inside auto-calculate branch (`c1d8d79`)
- `get_render_width_for_edit` simplified to `return float(rect.width)` (`1ffe189`)
- Pre-push probe fixed (`cc55872`)
- Dead `int(size)` cast removed (`b252f90`)
- PITFALLS entries (`bf51f15`, `ccbcc3f`, plus mixed-script split / `_needs_cjk_font` / heuristic span-discovery added this session)
- Synthetic monkeypatched htmlbox tests (lines 491–598 in `test_edit_text_helpers.py`) — KEEP as-is
- 76-test baseline passing (Phase 0 reference point)
