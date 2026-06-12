# Phase 0 — Restore the Gate: Fix 7 Order-Dependent Failures

**Goal:** Eliminate 7 order-dependent failures in `test_no_jump_editor_geometry.py`
(~57.86% pixel diff vs 1% threshold when the full suite runs; 377 passed in isolation).

**Status:** Empirically diagnosed — polluter identified and mechanism confirmed
(Sonnet 4.6 deep-plan pass, 2026-06-10). Baseline full-suite run:
`7 failed, 1227 passed, 21 skipped, 1 xfailed in 483s`.

---

## Confirmed Root Cause

### Polluter

`test_scripts/test_main_startup_behavior.py` — **every test in the file** is a polluter.

Each test calls `main_module.run(argv=..., start_event_loop=False)` which:
1. Creates a `PDFView`
2. Calls `view.apply_initial_theme()` → `app.setStyleSheet(build_qss(theme_id))`

The global QSS string (from `view/theme.py:build_qss`) includes a rule like:
```css
QTextEdit, QPlainTextEdit {
    border-radius: 6px;
    padding: 4px 8px;
    border: 1px solid ...;
}
```

The cleanup helper `_cleanup_startup()` calls `startup["app"].quit()` but does **not**
call `app.setStyleSheet("")`. The stylesheet persists in the `QApplication` instance for
all subsequent tests in the same process.

NOTE: the audit's original hypothesis (the `fitz.Page.get_text` rawdict monkey-wrap in
`model/pdf_model.py` leaking via `test_tool_extensions.py`) was tested and **ruled out** —
the failure reproduces with the startup tests alone and does not reproduce with the
tool-extension tests alone.

### Mechanism

`PreviewBackedInlineTextEditor` (extends `InlineTextEditor` extends `QTextEdit`)
explicitly sets zero margins in its `__init__`:
```python
self.setFrameStyle(0)
self.setViewportMargins(0, 0, 0, 0)
self.setContentsMargins(0, 0, 0, 0)
```

When Qt polishes the widget (first `show()`), it applies the active app-level QSS. The
`QTextEdit { padding: 4px 8px }` rule overrides `setViewportMargins()`, adding 4px
top/bottom and 8px left/right to the text area — after the constructor runs. The editor's
text shifts; `editor.grab()` vs the PDF rendering (no padding) diffs ~57.86% instead of <1%.

### Why Only Specific Tests Fail

| Test | Comparison type | Fails? |
|------|----------------|--------|
| `test_click_to_edit_real_geometry_pipeline` | editor rendering vs PDF rendering (absolute) | FAILS |
| `test_click_to_edit_qtest_integration` (3 cases) | editor region vs PDF region (absolute) | FAILS |
| `test_reopen_same_textbox_cycles_do_not_cumulate_shrink` (3 cases) | open-time editor vs PDF rendering (absolute) | FAILS |
| `test_click_to_edit_then_insert_then_delete_stays_stable` | editor vs itself after mutation (relative) | passes |
| `test_click_to_edit_continuous_insertions_then_delete_stays_stable` | editor vs itself (relative) | passes |

The 360 parametrized `test_editor_geometry_matches_pdf_bbox` tests are pure math checks
(no widget rendering) and are unaffected.

---

## Red-Light Evidence (required by CLAUDE.md §5.1)

**Minimal reproducing command:**
```
python -m pytest "test_scripts/test_main_startup_behavior.py::test_empty_launch_keeps_backend_detached_until_document_request" "test_scripts/test_no_jump_editor_geometry.py::test_click_to_edit_real_geometry_pipeline" -v --tb=short -p no:cacheprovider
```

**Observed output:**
```
FAILED test_scripts/test_no_jump_editor_geometry.py::test_click_to_edit_real_geometry_pipeline
AssertionError: Real click-to-edit jump: 57.86% changed pixels > 1%.
  Font='2,Bold', size=60.0, bbox=Rect(554.28..., 270.54..., 1030.25..., 330.54...)
  assert 0.5785991171853997 <= 0.01
1 failed, 1 passed in 0.93s
```

---

## Implementation Steps

### Step 1 — Fix the Polluter: stylesheet cleanup in `_cleanup_startup`

**File:** `test_scripts/test_main_startup_behavior.py`, `_cleanup_startup()` (~line 52)

Add `startup["app"].setStyleSheet("")` before `startup["app"].quit()`:

```python
def _cleanup_startup(startup: dict) -> None:
    startup["view"].close()
    model = startup.get("model")
    if model is not None:
        model.close()
    # Clear the app-level stylesheet set by apply_initial_theme() so it
    # does not leak into later tests that create QTextEdit-derived widgets.
    startup["app"].setStyleSheet("")
    startup["app"].quit()
```

(Mirrors the cleanup pattern already used in `test_theme_and_icons.py` ~lines 320, 338.)

### Step 2 — Defense in depth: make the inline editor QSS-immune

**File:** `view/text_editing.py`, `PreviewBackedInlineTextEditor.__init__()` (~line 744)

Immediately after the existing margin resets, add a widget-level stylesheet (widget QSS
takes precedence over app QSS):

```python
# Override any QApplication-level QSS that adds padding or borders to
# QTextEdit (e.g. the theme stylesheet from view/theme.py). The inline
# editor must always render flush to the PDF page.
self.setStyleSheet("QTextEdit { padding: 0px; border: 0px; margin: 0px; }")
```

This is a production-correctness fix too: a themed app would otherwise shift the inline
editor's glyphs at runtime, not just in tests.

### Step 3 — Belt-and-suspenders: autouse stylesheet-restore fixture

**File:** `test_scripts/conftest.py`

Add a function-scoped autouse fixture that snapshots `app.styleSheet()` before each test
and restores it afterwards if changed:

```python
@pytest.fixture(autouse=True)
def _reset_app_stylesheet():
    """Restore QApplication stylesheet to its pre-test state after each test.

    Tests that call view.apply_initial_theme() / app.setStyleSheet(...) leave a
    global stylesheet active; leaked QSS gives QTextEdit subclasses padding that
    shifts pixel-diff comparisons in later rendering tests.
    """
    app = QApplication.instance()
    before_stylesheet = app.styleSheet() if app is not None else ""
    yield
    if app is not None:
        current_app = QApplication.instance()
        if current_app is not None and current_app.styleSheet() != before_stylesheet:
            current_app.setStyleSheet(before_stylesheet)
```

Integrate with whatever already exists in `conftest.py` (do not clobber existing fixtures;
follow CLAUDE.md standards: `from __future__ import annotations`, no bare except).

---

## Verification

1. Minimal pair (after Step 1): the reproducing command above → `2 passed`.
2. `python -m pytest test_scripts/test_no_jump_editor_geometry.py -q -p no:cacheprovider`
   → 377 passed (same as isolation).
3. Gate: `python -m pytest test_scripts -q -p no:cacheprovider` → 0 failures (was 7).
4. `ruff check .` → zero new violations.

## Post-Implementation Checklist (CLAUDE.md §7)

- [ ] PITFALLS.md entry added (QApplication stylesheet leak — see plan body for entry text)
- [ ] TODOS.md updated (Phase 0 done)
- [ ] One atomic commit
