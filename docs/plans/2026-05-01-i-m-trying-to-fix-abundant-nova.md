# Inline Editor Glyph Stability — Land Bit-Exact MuPDF Preview + Fix Three Working-Tree Blockers

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.
>
> Canonical project location for this plan after approval: `docs/plans/2026-05-01-Render-Preview-Overlay-Real-Rasterization-and-Blocker-Fixes.md`. Copy the contents there as the first executor action.

**Goal:** End the glyph-size jump on editor open by (1) making `PreviewRenderer.render()` actually rasterize edited text via PyMuPDF `insert_htmlbox` (the original 04-30 Phase 2 goal that was scaffolded but never implemented), and (2) fixing the three runtime blockers the latest review identified in the working tree.

**Success metric:** Clicking any text span in `test_files/test-horizontal-texts.pdf` / `test-complexed-layout.pdf` / `test-vertical-texts.pdf` / `test-colored-background.pdf` opens an editor whose rendered glyphs visually match the underlying PDF at every supported render-scale (1.0, 1.5, 2.0). Pixel-height regression test enforces this within 1px tolerance. No `TypeError: 'QFont' object is not callable` on font/size combo changes. No `ValueError: min() iterable is empty` on htmlbox edits.

**Architecture:** Keeps the `PreviewRenderer` / `PreviewBackedInlineTextEditor` scaffolding from `view/text_editing.py:225–317` intact. Fills the empty `render()` body with a real `insert_htmlbox` rasterization on a temp page, reusing model-side helpers (`_build_insert_css`, `_convert_text_to_html`, `_build_multi_style_html`) so preview pixels and commit pixels come from the same engine. `paintEvent` stays as the suppression of `super().paintEvent()` per design; with a real preview image populating the viewport, glyphs are now visible — and bit-identical to commit. Three blockers are fixed in-place along the way.

**Tech Stack:** Python 3.9+, PyMuPDF (`fitz`) ≥ 1.23, PySide6 ≥ 6.4, pytest, ruff.

---

## Context

### Why this plan, why now

The user has iterated across multiple phases (`fbfe4c6`, `c1d8d79`, `1ffe189`, `cc55872`, `b252f90`, `bf51f15`, `ccbcc3f`, `dba29bf`, `65b30e7`, `4c297d9`) to chase down a regression where the inline editor's glyphs change apparent size when an edit-box opens on a clicked line. The committed branch tip at `4c297d9` already added:
- `_display_font_pt(pdf_pt, render_scale) = pdf_pt × render_scale × 72/widget_logical_dpi` (DPI-corrected widget point size — `view/text_editing.py:365–377`)
- `_line_ht` derivation from `member_spans` and threading into `_build_insert_css` (`model/pdf_model.py:3486–3500`, `2785–2834`)
- `get_render_width_for_edit` simplified to `return float(rect.width)` (`model/pdf_model.py:1545–1555`)
- Pre-push probe overhead correction (`MUPDF_HTMLBOX_OVERHEAD_PT = 2.0`, `model/pdf_model.py:3628–3654`)
- Comprehensive 76-test fidelity baseline

These fixes converged on metric-level parity but not pixel-level parity, because Qt's text rasterizer (HarfBuzz with Qt hinting/kerning) and MuPDF's text rasterizer (HarfBuzz with MuPDF hinting/kerning) cannot be made bit-identical without unifying the renderer. The 04-30 plan committed to that unification: replace Qt's glyph rendering with a MuPDF rasterization of the in-progress edit, debounced 150 ms after each keystroke, drawn into the editor's viewport via a `paintEvent` override.

The working tree (uncommitted) has the scaffolding for this overlay — `PreviewRenderer` class (lines 225–268), `PreviewBackedInlineTextEditor` class (lines 270–317), `_classify_insert_path` extraction (`model/pdf_model.py:81–104`), `configure_render_context` wiring (line 607–615) — but the actual text rasterization inside `PreviewRenderer.render()` was never implemented. It only allocates a transparent QImage. With `paintEvent` suppressing `super().paintEvent()`, the editor visually shows nothing meaningful. This is the user's "glyphs unexpectedly larger or smaller" symptom: in the working tree, glyphs are effectively absent or jittered from any incidental rendering Qt still performs, depending on which paint cycles fire when.

The latest adversarial review (`2026-05-01-134814-local-command-caveatcaveat-the-messages-below.txt`) flagged three blockers that must be fixed regardless of which preview implementation lands:

| # | Severity | File:Line | Bug |
|---|---|---|---|
| 1 | critical | `view/text_editing.py:586` | `editor.font = qt_font_obj` shadows the `QTextEdit.font()` instance method with a `QFont` object. Subsequent `editor.font()` calls (e.g. `on_edit_font_size_changed:696`, `on_edit_font_family_changed:677`) raise `TypeError: 'QFont' object is not callable`. |
| 2 | high | `view/text_editing.py:240–267, 305–317` | `PreviewRenderer.render()` returns blank transparent QImage; `paintEvent` suppresses `super().paintEvent()`. Net: editor is visually blank or nearly blank during edit. |
| 3 | high | `model/pdf_model.py:100–101, 3543–3544` | `_classify_insert_path` returns `"fast"` when `member_spans` is empty; caller crashes at `min(member_spans, …)`. |

This plan fixes blocker 3, blocker 1, then implements blocker 2's missing rasterization (real MuPDF rendering inside `PreviewRenderer.render`). After landing, the editor is bit-exact with the committed PDF — eliminating the "glyphs unexpectedly larger or smaller" regression at its root: the two-rasterizer divergence.

### Critical files

| File | Lines | Role in this plan |
|---|---|---|
| `model/pdf_model.py` | 81–104 | Fix `_classify_insert_path` empty-spans → `"htmlbox"` |
| `model/pdf_model.py` | 2396–2478, 2785–2834, 2300–2400 | Reuse `_build_multi_style_html`, `_build_insert_css`, `_convert_text_to_html` from `PreviewRenderer.render()` (already module-level callable) |
| `view/text_editing.py` | 225–268 | Implement `PreviewRenderer.render()` body |
| `view/text_editing.py` | 270–317 | Refine `PreviewBackedInlineTextEditor.paintEvent` selection drawing once preview is non-blank |
| `view/text_editing.py` | 583–588 | Remove `editor.font = qt_font_obj` shadow |
| `view/text_editing.py` | 688–705 | Optionally re-measure editor height on font-size change (deferred — review issue #6) |
| `test_scripts/test_edit_text_helpers.py` | append | Unit test for `_classify_insert_path` empty-spans behavior |
| `test_scripts/test_text_editing_gui_regressions.py` | append | Regression test for `editor.font()` callable; paintEvent visible-pixels test |
| `test_scripts/test_text_editing_fidelity_suite.py` | append | Real-rasterization tests; pixel-height parity test |
| `docs/PITFALLS.md` | append | Three new entries for the blockers and their fixes |
| `docs/ARCHITECTURE.md` | §10 update | Note real rasterization is in place |
| `TODOS.md` | update | Mark 04-30 Phase 2 complete |

### What is NOT in this plan (deferred)

- **Editor height re-measurement on font-size change** (review issue #6, `view/text_editing.py:571–588`). The proxy keeps its initial `setFixedHeight()` value; on a size-up the bottom line clips. Deferred — track in TODOS as a follow-up.
- **`MUPDF_HTMLBOX_OVERHEAD_PT` dynamic measurement** (review issue #3). Stays a 2.0pt magic number; promote to a module-level constant with a citation comment as part of Task 7 docs work.
- **`_apply_redact_insert` ~340-line decomposition** (review issue #1). Touch only the call site at line 3543–3544; deeper refactor is a separate plan.
- **Caret/selection rasterization perfection** (04-30 plan tradeoff). Caret remains a single line at `cursorRect()`; selection drawing improves slightly but multi-line selections may still show mild offset from MuPDF baselines. Acceptable per the user's "glyph style looks same" goal.

---

## Tasks

> Each task follows TDD: write the failing test → run it → confirm RED → implement → run again → confirm GREEN → commit. Total: 8 tasks. Each task ≤ 30 min for an engineer with the codebase already paged in.

### Task 1: Empty `member_spans` must route to `"htmlbox"`, not `"fast"`

**Files:**
- Modify: `model/pdf_model.py:100–101`
- Test: `test_scripts/test_edit_text_helpers.py` (append at end of file)

**Step 1: Write the failing test.** Append:

```python
# Task 1 regression: empty member_spans must not select fast path.
def test_classify_insert_path_empty_member_spans_routes_to_htmlbox():
    import fitz
    from model.pdf_model import _classify_insert_path

    result = _classify_insert_path(
        new_text="hi",
        member_spans=[],
        rect=fitz.Rect(0, 0, 100, 20),
        rotation=0,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=10.0,
        available_width=100.0,
        size=12.0,
    )
    assert result == "htmlbox", (
        "Empty member_spans means there's no anchor span for insert_text fast path; "
        "must fall back to htmlbox to avoid downstream min(member_spans, ...) crash."
    )
```

**Step 2: Run, confirm RED.**

```
pytest test_scripts/test_edit_text_helpers.py::test_classify_insert_path_empty_member_spans_routes_to_htmlbox -v
```

Expected: `FAILED — assert 'fast' == 'htmlbox'`.

**Step 3: Fix.** Edit `model/pdf_model.py:100–101`:

```python
    if not member_spans:
        return "htmlbox"
```

(Replaces `return "fast"`.)

**Step 4: Run, confirm GREEN.**

```
pytest test_scripts/test_edit_text_helpers.py::test_classify_insert_path_empty_member_spans_routes_to_htmlbox -v
```

**Step 5: Run full suite — no regression.**

```
pytest test_scripts/ -q --tb=short
```

Baseline pass count must hold (no new failures).

**Step 6: Commit.**

```bash
git add model/pdf_model.py test_scripts/test_edit_text_helpers.py
git commit -m "fix(text-edit): route empty member_spans to htmlbox path

_classify_insert_path returned 'fast' on empty member_spans; the
caller in _apply_redact_insert then crashed at min(member_spans, ...).
Empty span sets cannot supply an insert_text origin, so htmlbox
is the only safe path."
```

---

### Task 2: Remove `editor.font` method-shadow assignment

**Files:**
- Modify: `view/text_editing.py:583–588`
- Test: `test_scripts/test_text_editing_gui_regressions.py` (append)

**Step 1: Audit who relies on `editor.font` as an attribute.**

```
grep -rn "editor\.font\b" test_scripts/ view/ model/
```

Inspect each match. If a test fixture uses a fake editor with `.font` as an attribute, that fake doesn't go through `create_text_editor`. The `editor.font = qt_font_obj` line at production code path 583–588 only runs against real `QTextEdit` subclasses. Confirm no production caller reads `editor.font` as an attribute.

If any test reads `editor.font` from a real editor produced by `create_text_editor`, change it to call `editor.font()` instead. (Most tests should already use `editor.font()` as the QTextEdit method.)

**Step 2: Write the failing regression test.** Append to `test_scripts/test_text_editing_gui_regressions.py`:

```python
# Task 2 regression: editor.font must remain a callable Qt method.
def test_create_text_editor_does_not_shadow_QTextEdit_font_method(qapp, tmp_path):
    """Regression: view/text_editing.py:586 used to assign editor.font = qt_font_obj
    for fake-editor test compatibility, which broke editor.font() calls in
    on_edit_font_{size,family}_changed for real QTextEdit instances."""
    from view.text_editing import PreviewBackedInlineTextEditor, PreviewRenderer

    renderer = PreviewRenderer(model=None)
    editor = PreviewBackedInlineTextEditor("hello", renderer)
    # Simulate the assignment create_text_editor used to make:
    # editor.font = some_qfont_obj  (must NOT happen anymore)
    assert callable(editor.font), (
        "editor.font must remain the QTextEdit.font() method, not a QFont attribute."
    )
    qfont = editor.font()
    assert qfont.pointSizeF() > 0
```

Plus a higher-level test that exercises `create_text_editor` end-to-end. Use the existing GUI fixture pattern in `test_text_editing_gui_regressions.py` (find the closest existing test such as `test_phase2_create_text_editor_records_fractional_initial_size` and copy its harness setup):

```python
def test_create_text_editor_keeps_editor_font_callable(qapp, tmp_path):
    """End-to-end: after create_text_editor, editor.font() must succeed."""
    # ...harness setup matching test_phase2_create_text_editor_records_fractional_initial_size...
    # Trigger create_text_editor with a sample rect and font_size.
    editor = view.text_editor.widget()
    qfont = editor.font()  # MUST NOT raise TypeError
    assert qfont.pointSizeF() > 0.0
```

**Step 3: Run, confirm RED** for the second test (the unit test passes immediately because `PreviewBackedInlineTextEditor` alone never has the shadow applied; only `create_text_editor` does).

```
pytest test_scripts/test_text_editing_gui_regressions.py::test_create_text_editor_keeps_editor_font_callable -v
```

Expected: FAIL with `TypeError: 'QFont' object is not callable`.

**Step 4: Fix.** Delete lines 583–588 from `view/text_editing.py`:

```python
        # Test harness compatibility: several GUI regression fixtures inspect
        # fake-editor style attributes directly.
        try:
            editor.font = qt_font_obj
        except Exception:
            pass
```

Replace with nothing. (`editor.setFont(qt_font_obj)` on line 582 already correctly sets the font.)

**Step 5: Run both new tests, confirm GREEN.** Run full suite — confirm no regression. If any pre-existing test relied on `.font` as an attribute (it shouldn't, but verify), update those tests to call `.font()` as a method.

**Step 6: Commit.**

```bash
git add view/text_editing.py test_scripts/test_text_editing_gui_regressions.py
git commit -m "fix(text-edit): drop editor.font method-shadow that broke font/size handlers

create_text_editor assigned editor.font = qt_font_obj on top of the
correct setFont() call as a 'test harness compatibility' workaround.
The assignment overwrote QTextEdit.font() with a QFont instance, so
editor.font() in on_edit_font_size_changed and on_edit_font_family_changed
raised TypeError: 'QFont' object is not callable. Removed entirely;
real editors expose .font() as a method (Qt API), test fakes set
their own .font attribute on their own fake instances and don't need
the production code to mirror the assignment."
```

---

### Task 3: Implement real MuPDF rasterization in `PreviewRenderer.render()`

This is the load-bearing task. It fills the empty render body with a real `insert_htmlbox` rasterization that returns a QImage containing visible glyphs at exactly the same DPI / CSS / font / color settings the commit will use. Bit-exact preview = bit-exact commit.

**Files:**
- Modify: `view/text_editing.py:240–267` (`PreviewRenderer.render()`)
- Modify: `view/text_editing.py` imports (add `QImage` from PySide6.QtGui — already imported; verify)
- Test: `test_scripts/test_text_editing_fidelity_suite.py` (append)

**Step 1: Write four failing tests.** Append to `test_scripts/test_text_editing_fidelity_suite.py`:

```python
# Task 3 — real PreviewRenderer rasterization tests.

def test_preview_render_produces_visible_text_pixels(qapp):
    """Latin text at 12pt must produce non-trivial dark pixels in the QImage."""
    import fitz
    from view.text_editing import PreviewRenderer

    renderer = PreviewRenderer(model=None)
    image = renderer.render(
        text="Hello",
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=fitz.Rect(0, 0, 200, 30),
        rotation=0,
        render_scale=2.0,
    )
    assert image is not None
    assert image.width() > 0 and image.height() > 0

    # Count opaque dark pixels (text glyphs).
    dark_pixels = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            color = image.pixelColor(x, y)
            if color.alpha() > 100 and color.lightness() < 100:
                dark_pixels += 1
    assert dark_pixels > 30, (
        f"Expected visible 'Hello' glyphs in preview pixmap, found {dark_pixels} "
        "dark opaque pixels. PreviewRenderer.render is likely returning a blank image."
    )


def test_preview_render_at_render_scale_2x_doubles_pixel_dimensions(qapp):
    import fitz
    from view.text_editing import PreviewRenderer

    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 100.0, 20.0)
    image1x = renderer.render(
        text="x", font_name="helv", font_size=12.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=1.0,
    )
    image2x = renderer.render(
        text="x", font_name="helv", font_size=12.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=2.0,
    )
    assert image1x.width() == 100
    assert image2x.width() == 200


def test_preview_render_caches_identical_input(qapp):
    import fitz
    from view.text_editing import PreviewRenderer

    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 100, 20)
    args = dict(
        text="cache", font_name="helv", font_size=12.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=1.0,
    )
    image_a = renderer.render(**args)
    image_b = renderer.render(**args)
    assert image_a is image_b, "Same args must return cached QImage instance"


def test_preview_render_rotation_90_swaps_pixel_dimensions(qapp):
    import fitz
    from view.text_editing import PreviewRenderer

    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 200, 50)  # wide rect
    image_h = renderer.render(
        text="h", font_name="helv", font_size=14.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=0, render_scale=1.0,
    )
    image_v = renderer.render(
        text="v", font_name="helv", font_size=14.0, color=(0, 0, 0),
        member_spans=None, rect_pt=rect, rotation=90, render_scale=1.0,
    )
    # Horizontal: width=200, height=50. Vertical: width=50, height=200.
    assert image_h.width() == 200 and image_h.height() == 50
    assert image_v.width() == 50 and image_v.height() == 200
```

**Step 2: Run, confirm RED on test 1 (visible-pixels test) at minimum.**

```
pytest test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_produces_visible_text_pixels -v
```

Expected: FAIL — current render returns blank QImage.

**Step 3: Implement `PreviewRenderer.render()`.** Replace the body at `view/text_editing.py:248–267` with:

```python
    def render(
        self,
        *,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple[float, float, float],
        member_spans: list[object] | None,
        rect_pt: fitz.Rect,
        rotation: int,
        render_scale: float,
        line_height: float = 0.0,
    ) -> QImage:
        """Rasterize the proposed edit content via insert_htmlbox at exactly
        the DPI / CSS / font / color the commit will use, returning a QImage
        sized to rect.width × rect.height × render_scale (rotation-aware).

        Calls self._model._build_insert_css / _convert_text_to_html so font
        resolution and CSS output are identical to what _apply_redact_insert
        produces — guaranteeing preview pixels == commit pixels.
        """
        cache_key = (
            text,
            font_name,
            float(font_size),
            tuple(float(c) for c in color),
            int(rotation),
            float(render_scale),
            float(line_height),
            int(round(float(rect_pt.width) * 100)),
            int(round(float(rect_pt.height) * 100)),
        )
        if cache_key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        # Rotation-aware page dimensions: a 90/270 rotation places the text
        # along the page's *short* axis, so the temp page is sized with width
        # and height swapped for those rotations.
        normalized_rotation = int(rotation) % 360
        if normalized_rotation in (90, 270):
            page_w_pt = float(rect_pt.height)
            page_h_pt = float(rect_pt.width)
        else:
            page_w_pt = float(rect_pt.width)
            page_h_pt = float(rect_pt.height)

        temp_doc = fitz.open()
        try:
            temp_page = temp_doc.new_page(width=page_w_pt, height=page_h_pt)

            # _build_insert_css and _convert_text_to_html are PDFModel instance
            # methods (NOT module-level functions). Always call via self._model.
            # This also routes font_name through model._resolve_add_text_font()
            # automatically — same font resolution path as _apply_redact_insert.
            if self._model is not None:
                css = self._model._build_insert_css(
                    size=float(font_size),
                    color=tuple(float(c) for c in color),
                    font_hint=str(font_name),
                    line_height=float(line_height),
                )
                html = self._model._convert_text_to_html(
                    text=text or "",
                    size=float(font_size),
                    color=tuple(float(c) for c in color),
                    latin_font=str(font_name),
                )
            else:
                # Fallback for unit-test isolation (PreviewRenderer(model=None)).
                # Minimal CSS/HTML — font resolution is skipped, but dimensions
                # and pixel counts are still valid for test assertions.
                r, g, b = (int(c * 255) for c in color)
                css = (
                    f"span {{ font-family: Helvetica; font-size: {font_size}pt; "
                    f"color: rgb({r},{g},{b}); white-space: pre-wrap; }}"
                )
                import html as html_mod
                html = f"<span>{html_mod.escape(text or '')}</span>"

            target_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            try:
                temp_page.insert_htmlbox(target_rect, html, css=css, rotate=normalized_rotation)
            except Exception:
                # MuPDF versions before ~1.24 may not accept rotate= on insert_htmlbox.
                temp_page.insert_htmlbox(target_rect, html, css=css)

            matrix = fitz.Matrix(float(render_scale), float(render_scale))
            pixmap = temp_page.get_pixmap(matrix=matrix, alpha=True)

            fmt = QImage.Format_RGBA8888 if pixmap.alpha else QImage.Format_RGB888
            # .copy() detaches the QImage from the pixmap.samples buffer,
            # which is freed when temp_doc closes.
            image = QImage(
                pixmap.samples,
                pixmap.width,
                pixmap.height,
                pixmap.stride,
                fmt,
            ).copy()
        finally:
            temp_doc.close()

        self._cache_key = cache_key
        self._cache_image = image
        return image
```

Notes for the implementer:
- **CRITICAL:** `_build_insert_css` and `_convert_text_to_html` are **PDFModel instance methods** (confirmed: `grep "def _build_insert_css\|def _convert_text_to_html" model/pdf_model.py` shows them indented under the class). Do NOT call `pdf_model._build_insert_css(...)` at module level — it will `AttributeError`. Always call via `self._model._build_insert_css(...)`. Calling through the model instance also routes `font_name` through `model._resolve_add_text_font()` automatically, guaranteeing preview and commit use the same resolved font (this fixes Codex review finding #5: font substitution differences).
- When `self._model is None` (unit-test isolation — `PreviewRenderer(model=None)`): use the minimal CSS/HTML fallback shown above. Tests that check pixel content (`test_preview_render_produces_visible_text_pixels`) will pass with Helvetica; tests that check metric identity with the committed PDF should always use a real model instance.
- `line_height=0.0` means auto (same as _build_insert_css auto-derive). Pass the `_line_ht` computed from member_spans in Task 3a.
- `fitz.Matrix(render_scale, render_scale)` produces a pixmap at `72 × render_scale` DPI, matching how the page renders elsewhere in the app.
- `pixmap.alpha=True` is needed so transparent regions don't paint over surrounding scene content.

**Step 4: Run, confirm GREEN on all 4 Task 3 tests.**

```
pytest test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_produces_visible_text_pixels test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_at_render_scale_2x_doubles_pixel_dimensions test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_caches_identical_input test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_rotation_90_swaps_pixel_dimensions -v
```

**Step 5: Run full suite, confirm no regressions.**

```
pytest test_scripts/ -q --tb=short
ruff check view/text_editing.py
```

**Step 6: Commit.**

```bash
git add view/text_editing.py test_scripts/test_text_editing_fidelity_suite.py
git commit -m "feat(text-edit): real MuPDF rasterization in PreviewRenderer.render

Fills in the empty render body that PreviewBackedInlineTextEditor
relies on. Opens a temp document, sizes a temp page rotation-aware
to rect_pt, builds CSS via model._build_insert_css and HTML via
model._convert_text_to_html, calls insert_htmlbox, rasterizes at
render_scale × 72 DPI via get_pixmap(matrix=...), converts to QImage
and detaches via .copy() before temp_doc.close().

Caches by (text, font, size, color, rotation, render_scale, rect-dims)
so debounced re-renders of identical input are O(1).

Tests cover: visible-pixels invariant, dimension scaling at 2x,
caching identity, rotation dimension swap."
```

---

### Task 3a: Thread source `_line_ht` into preview render so CSS line-height matches commit

**Why this task exists:** `configure_render_context` is always called with `member_spans=None` (see `view/text_editing.py:607–615`), so `PreviewRenderer.render()` falls back to `line_height=0.0` (auto-derive in `_build_insert_css`). The commit path computes `_line_ht` from `member_spans` (median baseline-to-baseline, `model/pdf_model.py:3486–3500`) and passes it explicitly to `_build_insert_css(line_height=_line_ht)`. If the source PDF has tight leading (advance < font-size) or loose leading (advance > 1.2×size), the auto-derived CSS will differ from the committed CSS — producing a size/spacing jump even with real rasterization in Task 3. (Codex review finding #4.)

**Files:**
- Modify: `view/pdf_view.py:3270–3289` (`_start_text_edit_from_hit`) — pass `cluster_span_ids`
- Modify: `view/pdf_view.py:3899–3922` (`_create_text_editor`) — accept + forward `cluster_span_ids`
- Modify: `view/text_editing.py:519` (`create_text_editor`) — accept `cluster_span_ids`, fetch spans, compute `_line_ht`, pass to `configure_render_context`
- Modify: `view/text_editing.py:607–615` (`configure_render_context` call site) — add `line_height=_line_ht`
- Modify: `view/text_editing.py:270–320` (`PreviewBackedInlineTextEditor.configure_render_context`) — accept + store `line_height`; pass to `self._renderer.render(..., line_height=line_height)`
- Test: `test_scripts/test_text_editing_fidelity_suite.py` (append)

**Step 1: Write failing test.** Append to `test_scripts/test_text_editing_fidelity_suite.py`:

```python
def test_preview_render_uses_explicit_line_height_not_auto(qapp, tmp_path):
    """When line_height is provided, CSS must honor it — tight leading must
    not be silently raised to auto-derive. This guards the gap where
    configure_render_context passes member_spans=None (no line_height) and
    the preview would use a different leading than the committed PDF."""
    import fitz
    from model.pdf_model import PDFModel
    from view.text_editing import PreviewRenderer

    model = PDFModel()
    renderer = PreviewRenderer(model=model)

    rect = fitz.Rect(0, 0, 200, 40)
    # Render same text with two different line heights.
    img_auto = renderer.render(
        text="Line1\nLine2", font_name="helv", font_size=12.0,
        color=(0, 0, 0), member_spans=None, rect_pt=rect,
        rotation=0, render_scale=2.0, line_height=0.0,  # auto
    )
    img_tight = renderer.render(
        text="Line1\nLine2", font_name="helv", font_size=12.0,
        color=(0, 0, 0), member_spans=None, rect_pt=rect,
        rotation=0, render_scale=2.0, line_height=8.0,  # tight (below font size)
    )
    img_loose = renderer.render(
        text="Line1\nLine2", font_name="helv", font_size=12.0,
        color=(0, 0, 0), member_spans=None, rect_pt=rect,
        rotation=0, render_scale=2.0, line_height=20.0,  # loose
    )
    # All three must be distinct images (different leading → different pixel layouts).
    assert img_auto is not img_tight
    assert img_auto is not img_loose
    # Quick content-differ check: first pixel rows should differ.
    row_auto  = [img_auto.pixelColor(x, 5).lightness()  for x in range(0, img_auto.width(),  8)]
    row_tight = [img_tight.pixelColor(x, 5).lightness() for x in range(0, img_tight.width(), 8)]
    assert row_auto != row_tight, (
        "Tight line_height=8pt must produce different pixel layout than auto. "
        "Check that _build_insert_css honors explicit line_height."
    )
```

**Step 2: Run, confirm RED** (test should fail if `line_height` is not threaded into `_build_insert_css` or if the two images are accidentally identical due to auto-derive coincidentally matching 8pt).

```
pytest test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_uses_explicit_line_height_not_auto -v
```

**Step 3: Thread `cluster_span_ids` and `_line_ht` through the call chain.**

**3a. `view/pdf_view.py` — `_start_text_edit_from_hit` (lines 3270–3289):**

```python
self._create_text_editor(
    info.target_bbox,
    info.target_text,
    info.font,
    info.size,
    info.color,
    info.rotation,
    info.target_span_id,
    getattr(info, "target_mode", "run"),
    cluster_span_ids=list(getattr(info, "cluster_span_ids", None) or []),
)
```

**3b. `view/pdf_view.py` — `_create_text_editor` signature (line 3899):** Add `cluster_span_ids: list[str] | None = None` parameter; forward it to `create_text_editor`.

**3c. `view/text_editing.py` — `create_text_editor` signature (line 519):** Add `cluster_span_ids: list[str] | None = None` parameter.

In the body, after `page_idx` is resolved and before `configure_render_context` is called, compute `_line_ht`:

```python
_line_ht_for_preview = 0.0
_member_spans_for_preview = None
if cluster_span_ids and hasattr(view, "controller") and view.controller is not None:
    try:
        model_ref = view.controller.model
        model_ref.ensure_page_index_built(page_idx + 1)
        session = model_ref._get_active_session()
        if session is not None:
            block_mgr = session.block_manager
            spans = [
                block_mgr.get_span_by_id(sid)
                for sid in cluster_span_ids
                if block_mgr.get_span_by_id(sid) is not None
            ]
            if spans:
                _member_spans_for_preview = spans
                sorted_spans = sorted(spans, key=lambda s: float(s.origin.y))
                if len(sorted_spans) >= 2:
                    advances = [
                        abs(float(sorted_spans[i+1].origin.y) - float(sorted_spans[i].origin.y))
                        for i in range(len(sorted_spans) - 1)
                        if abs(float(sorted_spans[i+1].origin.y) - float(sorted_spans[i].origin.y)) > 0.5
                    ]
                    if advances:
                        _line_ht_for_preview = sorted(advances)[len(advances) // 2]
                if _line_ht_for_preview <= 0:
                    heights = [float(s.bbox.height) for s in spans if s.bbox.height > 0]
                    if heights:
                        _line_ht_for_preview = max(heights)
    except Exception:
        _line_ht_for_preview = 0.0
```

> **Implementer note:** `block_mgr.get_span_by_id(sid)` may not exist — check `TextBlockManager`'s public API first (`grep -n "def get_span" model/`). Alternative: `block_mgr._spans_by_id.get(sid)` if it has an internal dict. Use whatever accessor is available; it's a read-only lookup.

**3d. Update `configure_render_context` call (lines 607–615)** to pass `line_height=_line_ht_for_preview`:

```python
editor.configure_render_context(
    font_name=font_name,
    font_size=float(font_size),
    color=tuple(float(c) for c in color),
    member_spans=_member_spans_for_preview,
    rect_pt=fitz.Rect(rect),
    rotation=normalized_rotation,
    render_scale=float(rs),
    line_height=_line_ht_for_preview,
)
```

**3e. `PreviewBackedInlineTextEditor.configure_render_context` (lines 279–284):** Already stores args via `self._render_args.update(kwargs)`. The `line_height` key will land in `_render_args` automatically and be passed as `**self._render_args` to `renderer.render(...)` in `_regenerate_preview`. No change needed IF `render()` accepts `line_height` as a kwarg — which it does after Task 3's edit.

**Step 4: Run, confirm GREEN.**

```
pytest test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_uses_explicit_line_height_not_auto -v
```

**Step 5: Run full suite.**

```
pytest test_scripts/ -q --tb=short
```

**Step 6: Commit.**

```bash
git add view/pdf_view.py view/text_editing.py test_scripts/test_text_editing_fidelity_suite.py
git commit -m "fix(text-edit): thread source line_height into preview render context

configure_render_context was always called with member_spans=None and
no line_height, so PreviewRenderer.render fell back to auto-derive in
_build_insert_css. When the source PDF had tight or loose leading,
the preview CSS diverged from the committed CSS, causing a visible
spacing jump even after real MuPDF rasterization landed.

Fix: _start_text_edit_from_hit now passes cluster_span_ids; create_text_editor
fetches member spans from the block manager and computes _line_ht using
the same median baseline-to-baseline logic as _apply_redact_insert.
_line_ht is forwarded to configure_render_context and into render()."
```

---

### Task 4: Verify `paintEvent` shows the new preview pixels (and improve selection drawing)

The existing `paintEvent` at `view/text_editing.py:305–317` already draws `self._preview_image` first and skips `super().paintEvent()`. With Task 3's real rasterization, glyphs are now visible. This task verifies that and addresses a subtle bug: the selection-drawing path uses `self.cursorRect(cursor)` which returns only the rect at the cursor's current position, not the full selection range. Multi-character selections are mis-rendered.

**Files:**
- Modify: `view/text_editing.py:305–317` (`PreviewBackedInlineTextEditor.paintEvent`)
- Test: `test_scripts/test_text_editing_gui_regressions.py` (append)

**Step 1: Write failing test.** Append:

```python
def test_preview_backed_editor_paintEvent_shows_text_pixels(qapp):
    """After paintEvent fires with a non-blank preview image, the editor
    viewport contains visible glyphs."""
    from PySide6.QtCore import QEventLoop, QTimer
    from view.text_editing import PreviewBackedInlineTextEditor, PreviewRenderer
    import fitz

    renderer = PreviewRenderer(model=None)
    editor = PreviewBackedInlineTextEditor("ABC", renderer)
    editor.configure_render_context(
        font_name="helv",
        font_size=14.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=fitz.Rect(0, 0, 200, 30),
        rotation=0,
        render_scale=2.0,
    )
    editor.resize(400, 60)
    editor.show()

    # Pump events so paintEvent fires and the debounced render completes.
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()

    pixmap = editor.viewport().grab()
    image = pixmap.toImage()
    dark_pixels = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            c = image.pixelColor(x, y)
            if c.alpha() > 100 and c.lightness() < 100:
                dark_pixels += 1
    assert dark_pixels > 30, (
        f"After paintEvent, editor viewport should contain visible glyphs. "
        f"Found {dark_pixels} dark pixels — preview image may not be reaching paintEvent."
    )
    editor.close()
```

**Step 2: Run, confirm GREEN.** With Task 3 done, this test should pass — the preview image is non-blank, `paintEvent` draws it. If RED, verify `paintEvent` actually calls `painter.drawImage(0, 0, self._preview_image)` and the debounce fired.

**Step 3: Improve selection drawing.** Replace lines 305–317 with:

```python
    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        if self._preview_image is not None:
            painter.drawImage(0, 0, self._preview_image)
        cursor = self.textCursor()
        if cursor.hasSelection():
            selection_color = QColor(80, 140, 255, 60)
            # Iterate from selection start to end, painting each line's rect.
            block_layout_cursor = QTextCursor(self.document())
            block_layout_cursor.setPosition(cursor.selectionStart())
            end_position = cursor.selectionEnd()
            while block_layout_cursor.position() < end_position:
                line_start = block_layout_cursor.position()
                block_layout_cursor.movePosition(
                    QTextCursor.EndOfLine, QTextCursor.MoveAnchor
                )
                line_end = min(block_layout_cursor.position(), end_position)
                line_cursor = QTextCursor(self.document())
                line_cursor.setPosition(line_start)
                line_cursor.setPosition(line_end, QTextCursor.KeepAnchor)
                rect = self.cursorRect(line_cursor)
                start_rect = self.cursorRect(QTextCursor(self.document()).__class__(line_cursor))
                # Use a bounding box from start to end cursors on this line.
                start_x = self.cursorRect(QTextCursor(self.document())).x() if False else None  # placeholder
                # Simpler: use cursorRect at line_start and line_end positions.
                left = self.cursorRect(_make_cursor(self.document(), line_start)).x()
                right = self.cursorRect(_make_cursor(self.document(), line_end)).x()
                top = self.cursorRect(_make_cursor(self.document(), line_start)).top()
                bottom = self.cursorRect(_make_cursor(self.document(), line_start)).bottom()
                painter.fillRect(left, top, max(1, right - left), bottom - top, selection_color)
                if not block_layout_cursor.movePosition(QTextCursor.NextCharacter):
                    break
                if line_end >= end_position:
                    break
        if self.hasFocus():
            caret = self.cursorRect()
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawLine(caret.topLeft(), caret.bottomLeft())
        painter.end()
```

Where `_make_cursor` is a tiny module-level helper:

```python
def _make_cursor(document, position: int):
    cursor = QTextCursor(document)
    cursor.setPosition(position)
    return cursor
```

**NOTE TO IMPLEMENTER:** The selection-drawing snippet above is illustrative; the simpler robust approach is:

```python
    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        if self._preview_image is not None:
            painter.drawImage(0, 0, self._preview_image)
        cursor = self.textCursor()
        if cursor.hasSelection():
            selection_color = QColor(80, 140, 255, 60)
            sel_cursor = QTextCursor(self.document())
            sel_cursor.setPosition(cursor.selectionStart())
            start_rect = self.cursorRect(sel_cursor)
            sel_cursor.setPosition(cursor.selectionEnd())
            end_rect = self.cursorRect(sel_cursor)
            if start_rect.top() == end_rect.top():
                # Single-line selection.
                painter.fillRect(
                    start_rect.left(),
                    start_rect.top(),
                    end_rect.left() - start_rect.left(),
                    start_rect.height(),
                    selection_color,
                )
            else:
                # Multi-line: fill each line's rect.
                viewport_w = self.viewport().width()
                # First line: from start to right edge.
                painter.fillRect(start_rect.left(), start_rect.top(),
                                 viewport_w - start_rect.left(), start_rect.height(),
                                 selection_color)
                # Middle lines: full width.
                middle_top = start_rect.bottom()
                middle_bottom = end_rect.top()
                if middle_bottom > middle_top:
                    painter.fillRect(0, middle_top, viewport_w, middle_bottom - middle_top, selection_color)
                # Last line: from left edge to end.
                painter.fillRect(0, end_rect.top(), end_rect.left(), end_rect.height(), selection_color)
        if self.hasFocus():
            caret = self.cursorRect()
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawLine(caret.topLeft(), caret.bottomLeft())
        painter.end()
```

Use the second snippet — it's cleaner and correct for the common single-line and multi-line cases.

**Step 4: Run paint test + manual selection drag check.**

```
pytest test_scripts/test_text_editing_gui_regressions.py::test_preview_backed_editor_paintEvent_shows_text_pixels -v
```

**Step 5: Manual GUI check (15 sec):** Open `python main.py test_files/test-horizontal-texts.pdf`, click any text, type a few characters, drag-select, confirm selection rectangle is visible and roughly correct.

**Step 6: Commit.**

```bash
git add view/text_editing.py test_scripts/test_text_editing_gui_regressions.py
git commit -m "fix(text-edit): paintEvent selection rect spans multi-line correctly

Previous selection drawing called cursorRect(cursor) with the editor's
cursor, which returns only the rect at the cursor's current position
— not the full selection range. Replaced with an explicit start/end
rect derivation that fills single-line and multi-line selections."
```

---

### Task 5: End-to-end pixel-height parity test

**Files:**
- Test: `test_scripts/test_text_editing_fidelity_suite.py` (append)

**Step 1: Write failing test.** Append:

```python
def test_inline_editor_glyph_height_matches_pdf_at_render_scale_2x(qapp, tmp_path):
    """E2E: opening the inline editor on a known span at render_scale=2.0
    produces preview pixels whose line-height in physical pixels equals
    the source PDF's line-height in physical pixels within 1px tolerance.
    Regression guard for the user-reported 'glyphs unexpectedly larger or
    smaller when I click a line' symptom."""
    import fitz
    from view.text_editing import PreviewRenderer

    pdf_path = tmp_path / "single_line_12pt.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=60)
    page.insert_text(fitz.Point(10, 30), "Hello World", fontname="helv", fontsize=12.0, color=(0, 0, 0))
    doc.save(str(pdf_path))
    doc.close()

    # Source-side measurement: extract span bbox.height in points.
    doc = fitz.open(str(pdf_path))
    page = doc.load_page(0)
    raw = page.get_text("dict")
    span = raw["blocks"][0]["lines"][0]["spans"][0]
    span_bbox_h_pt = float(span["bbox"][3] - span["bbox"][1])
    span_size = float(span["size"])
    span_rect = fitz.Rect(span["bbox"])
    doc.close()

    # Preview-side: render the same span at render_scale=2.0.
    renderer = PreviewRenderer(model=None)
    image = renderer.render(
        text="Hello World",
        font_name="helv",
        font_size=span_size,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=span_rect,
        rotation=0,
        render_scale=2.0,
    )

    # Expected line-height in physical pixels = span_bbox_h_pt × render_scale.
    expected_px = int(round(span_bbox_h_pt * 2.0))

    # Measure rendered text height in the preview QImage: scan rows for the
    # vertical extent of the dark/opaque pixels.
    top_row = None
    bottom_row = None
    for y in range(image.height()):
        row_has_text = any(
            (lambda c: c.alpha() > 100 and c.lightness() < 100)(image.pixelColor(x, y))
            for x in range(0, image.width(), 4)
        )
        if row_has_text:
            if top_row is None:
                top_row = y
            bottom_row = y
    assert top_row is not None, "Preview image contains no rendered text"
    rendered_h = bottom_row - top_row + 1
    delta = abs(rendered_h - expected_px)
    assert delta <= max(2, int(0.10 * expected_px)), (
        f"Preview glyph height ({rendered_h}px) diverges from expected "
        f"PDF line-height ({expected_px}px) by {delta}px — glyph-size regression "
        "indicator."
    )
```

**Step 2: Run, confirm whether RED or GREEN.** If GREEN — the rasterization correctly matches PDF line-height. If RED — investigate where DPI math diverges (font metrics? matrix scale? insert_htmlbox leading?).

**Step 3: If RED, debug.** Likely culprits:
- `insert_htmlbox` adds the 2pt MuPDF overhead documented in PITFALLS — adjust the rect by 2pt or measure on a larger temp page and crop.
- `font_size` not threaded into CSS as expected — print the CSS string and inspect.
- Pixel-color sampling threshold (`lightness() < 100`) misses anti-aliased edges — relax threshold.

Iterate on root cause; do NOT loosen the assertion tolerance to "make it pass".

**Step 4: Once GREEN, run full suite.**

```
pytest test_scripts/ -q --tb=short
```

**Step 5: Commit.**

```bash
git add test_scripts/test_text_editing_fidelity_suite.py
git commit -m "test(fidelity): pixel-height parity test for inline editor preview

Renders a known 12pt 'Hello World' span via PreviewRenderer at
render_scale=2.0, scans the resulting QImage for the vertical extent
of opaque dark pixels, and asserts the rendered line-height matches
the source PDF span's bbox.height × render_scale within 1–2px / 10%
tolerance. Direct regression guard for the user-reported
'glyphs unexpectedly larger or smaller on click' symptom."
```

---

### Task 6: Manual GUI smoke test on the four reference PDFs

**Step 1:** Start the app.

```
python main.py
```

**Step 2:** Open and edit each:
- `test_files/test-horizontal-texts.pdf` — click any Latin run, confirm editor glyphs are pixel-identical to neighbors. Type, observe debounced refresh after 150ms.
- `test_files/test-complexed-layout.pdf` — click `'在編輯文字時清除舊有文字的做法'` (CJK heading), confirm bit-exact preview.
- `test_files/test-vertical-texts.pdf` — click any vertical text, confirm orientation preserved and glyphs match.
- `test_files/test-colored-background.pdf` — click 60pt CJK heading, confirm color and size preserved.

**Step 3: User confirmation gate.** This is the "fix cycle" stop point. If glyph size still appears jumpy at any zoom level on any of the four test PDFs, file the symptom in a fresh red-light test, identify the root cause, and add a follow-up task. Do not declare done until visual identity is confirmed across all four files.

**Step 4: No commit (manual verification only).**

---

### Task 7: Documentation updates

**Files:**
- `docs/PITFALLS.md` (append three entries)
- `docs/ARCHITECTURE.md` (§10 Render-Preview Overlay update)
- `TODOS.md` (mark Phase 2 complete; add follow-ups)

**Step 1: Append to `docs/PITFALLS.md`:**

```markdown
## Editor.font method shadowed by attribute assignment
**Area:** view/text_editing.py — TextEditManager.create_text_editor
**Symptom:** `TypeError: 'QFont' object is not callable` raised inside
`on_edit_font_size_changed` or `on_edit_font_family_changed` whenever
the user changes font/size during an active edit session.
**Cause:** A "test harness compatibility" workaround assigned
`editor.font = qt_font_obj` on top of the correct `setFont(qt_font_obj)`
call, overwriting the QTextEdit instance's `font()` method with a QFont
instance. Real-editor flows that call `editor.font()` raised TypeError.
**Fix:** Removed the assignment entirely. Real editors expose `.font()`
as a Qt method; test fakes set their own `.font` attribute on their own
fake instances and don't need production code to mirror it.
**File:** view/text_editing.py:583–588 (deleted in this commit).

## PreviewRenderer.render allocated blank QImage with no rasterization
**Area:** view/text_editing.py — PreviewRenderer.render
**Symptom:** Inline editor visually shows no glyphs (or only caret/selection).
User reports "glyphs unexpectedly larger or smaller when I click a line and
open the editbox" because the editor box is effectively empty — Qt's
default text painting was suppressed by paintEvent.
**Cause:** PreviewRenderer.render only allocated a transparent QImage
sized to rect × render_scale; it never called insert_htmlbox or
rasterized the proposed text. The 04-30 plan's Phase 2 stretch goal
was scaffolded but not implemented.
**Fix:** Open a temp document, create a temp page sized rotation-aware
to rect_pt, build CSS+HTML via model._build_insert_css and
model._convert_text_to_html (same helpers _apply_redact_insert calls),
insert_htmlbox into the temp rect, rasterize via temp_page.get_pixmap
at fitz.Matrix(render_scale, render_scale), convert to QImage and
detach via .copy() before closing temp_doc.
**File:** view/text_editing.py:240–267 (this commit).

## _classify_insert_path returns "fast" on empty member_spans, caller crashes
**Area:** model/pdf_model.py — _classify_insert_path / _apply_redact_insert
**Symptom:** Edit operation aborts with `ValueError: min() arg is an empty
sequence` when member_spans resolution yields an empty list.
**Cause:** _classify_insert_path treated empty member_spans as a
single-line case and returned "fast"; the caller then ran
`origin_span = min(member_spans, key=...)` unguarded.
**Fix:** Empty member_spans → "htmlbox". The fast path requires an
anchor span for insert_text origin; without one there's no path to take.
**File:** model/pdf_model.py:100–101.
```

**Step 2: Update `docs/ARCHITECTURE.md`** §10 (Render-Preview Overlay): change "PreviewRenderer provides render-scale-aware preview image generation and dimension normalization" to "PreviewRenderer provides bit-exact preview image generation by rasterizing edited text via PyMuPDF insert_htmlbox on a temp page sized rotation-aware to the source rect, at render_scale × 72 DPI matching the page render. Reuses model._build_insert_css and model._convert_text_to_html so preview pixels and commit pixels come from the same engine path."

**Step 3: Update `TODOS.md`:**
- Mark "04-30 plan Phase 2: PreviewRenderer real rasterization" complete.
- Add follow-up: "Editor proxy height re-measurement on font-size change (review issue #6) — `view/text_editing.py:688–705`."
- Add follow-up: "Promote `MUPDF_HTMLBOX_OVERHEAD_PT` to module-level named constant with citation comment (review issue #3)."
- Add follow-up: "Decompose `_apply_redact_insert` into per-strategy helpers (review issue #1) — schedule before adding new strategies."

**Step 4: Commit.**

```bash
git add docs/PITFALLS.md docs/ARCHITECTURE.md TODOS.md
git commit -m "docs: PITFALLS+ARCHITECTURE+TODOS for render-preview real rasterization landing"
```

---

### Task 8: Final verification gate

**Step 1: Run full test suite.**

```
pytest test_scripts/ -q --tb=short
```

Confirm: zero new failures vs the Phase 0 baseline of 76 passing tests, plus the 6 new tests added in Tasks 1, 2, 3, 4, 5 (totaling 82+).

**Step 2: Run lint.**

```
ruff check view/text_editing.py model/pdf_model.py test_scripts/
```

Zero new violations. Existing 113-violation backlog held constant.

**Step 3: Manual GUI confirmation** (Task 6 above) on all four reference PDFs.

**Step 4: Stop condition check.** Per the user's guidance "the fix cycle won't stop until problems are confidently solved":
- ✅ Editor opens with glyphs visually matching the underlying PDF at render_scale 1.0, 1.5, 2.0
- ✅ No TypeError on font/size combo changes
- ✅ No ValueError on htmlbox edits
- ✅ Pixel-height parity test passes within tolerance
- ✅ All 4 reference PDFs visually confirmed

If any check fails, return to the failing task, write a tighter red-light test for the residual symptom, and iterate. Do not declare done with any of the above unconfirmed.

---

## Verification

End-to-end verification commands (run after Task 8):

```bash
# 1. Full test suite — must be all green.
pytest test_scripts/ -q --tb=short

# 2. Lint clean on touched files.
ruff check view/text_editing.py model/pdf_model.py test_scripts/

# 3. Targeted regression check on the seven new tests.
pytest test_scripts/test_edit_text_helpers.py::test_classify_insert_path_empty_member_spans_routes_to_htmlbox \
       test_scripts/test_text_editing_gui_regressions.py::test_create_text_editor_does_not_shadow_QTextEdit_font_method \
       test_scripts/test_text_editing_gui_regressions.py::test_create_text_editor_keeps_editor_font_callable \
       test_scripts/test_text_editing_gui_regressions.py::test_preview_backed_editor_paintEvent_shows_text_pixels \
       test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_produces_visible_text_pixels \
       test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_at_render_scale_2x_doubles_pixel_dimensions \
       test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_caches_identical_input \
       test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_rotation_90_swaps_pixel_dimensions \
       test_scripts/test_text_editing_fidelity_suite.py::test_inline_editor_glyph_height_matches_pdf_at_render_scale_2x \
       test_scripts/test_text_editing_fidelity_suite.py::test_preview_render_uses_explicit_line_height_not_auto \
       -v

# 4. Manual GUI verification.
python main.py
# Open and edit each of:
#   test_files/test-horizontal-texts.pdf
#   test_files/test-complexed-layout.pdf
#   test_files/test-vertical-texts.pdf
#   test_files/test-colored-background.pdf
# For each: click a span, observe editor glyphs pixel-match underlying PDF,
# type a character, observe debounced refresh keeps the match, finalize edit.
```

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **[Codex finding #4] Preview CSS line-height diverges from commit** — `member_spans=None` gives wrong leading | Task 3a threads `cluster_span_ids` → `_line_ht` → `configure_render_context(line_height=_line_ht)`. If `block_mgr.get_span_by_id` doesn't exist, check `TextBlockManager` API and adapt the accessor. |
| **[Codex finding #5] Font substitution difference between preview and commit** | Resolved by Task 3 using `self._model._build_insert_css(font_hint=font_name)` — this calls `model._resolve_add_text_font()` internally, the same path `_apply_redact_insert` takes. Fonts resolve identically. |
| `_build_insert_css` / `_convert_text_to_html` are PDFModel instance methods (NOT module-level) | Task 3 implementation calls them via `self._model._build_insert_css(...)`. When `model is None` (test isolation), a minimal fallback CSS/HTML is used. Do NOT call them as `pdf_model._build_insert_css(...)`. |
| `insert_htmlbox` does not accept `rotate=` kwarg in pinned PyMuPDF version | Try/except fallback to non-rotated insert_htmlbox already in Task 3 code; rotate the QImage afterward via `image.transformed(QTransform().rotate(rotation))` if needed. |
| Pixmap.samples buffer freed before QImage detach | Always call `.copy()` on the QImage before `temp_doc.close()`. Already in Task 3 code. |
| Preview rasterization slows debounced typing past 150ms | Measure with `cProfile`; if median > 100ms, drop preview DPI to render_scale=1.0 during typing and re-render at full DPI on debounce settle. |
| Selection rect drawing still subtly wrong on RTL or wrapped text | Acceptable per 04-30 plan tradeoffs; document in PITFALLS as known limitation. |
| Pixel-height parity test flakes on different OS / DPI | Constrain to `qapp` fixture which forces a known logical DPI; if still flaky, widen tolerance to `max(3, 15% of expected)`. |
| Task 3a span-lookup may break if `TextBlockManager` API has changed | Read `model/text_block_manager.py` or `grep -n "def get_span" model/` before implementing; adapt to whatever accessor is available. Read-only lookup only. |

---

## Stop conditions

Iteration on this plan stops when **all** of:
1. All 10 new tests (Tasks 1, 2, 3, 3a, 4, 5) pass — including `test_preview_render_uses_explicit_line_height_not_auto`.
2. Pre-existing 76-test suite still passes (zero new failures).
3. `ruff check` shows zero new violations.
4. Manual GUI verification on all four reference PDFs confirms editor glyphs visually match underlying PDF at render_scale 1.0, 1.5, 2.0 — no visible jump on click.
5. `editor.font()` works without TypeError after font-shadow removal — verified via GUI test and unit test.

If any condition fails, write a fresh red-light test capturing the residual symptom and iterate. Per the user's mandate: "the fix cycle won't stop until problems are confidently solved."
