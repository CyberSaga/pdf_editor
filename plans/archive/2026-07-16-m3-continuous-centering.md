# M3 Tranche 3.6 — Continuous Centering and Numeric Double-Click

**Status:** Complete 2026-07-16; archived after full M3.6 verification.

## Goal

Center mixed-width pages independently inside the continuous document column and make browse-mode double-click select a complete numeric token without breaking drag selection, text editing, object hit-testing, annotations, or scene/document coordinate round trips.

## Affected modules

- `view/pdf_view.py` — per-page x origins, page geometry helpers, viewport double-click routing, scene/document conversions
- `view/text_selection.py` — pure numeric-boundary helper and selection-state application
- `view/object_selection.py` — object overlay x origin
- `view/text_editing.py` — inline editor x origin and frozen-frame placement
- `model/pdf_model.py` — Qt-free character-at-point context query using the existing run/character index
- `controller/pdf_controller.py` — thin query façade only
- `test_scripts/test_continuous_centering.py` — mixed-page geometry and coordinate round trips
- `test_scripts/test_numeric_token_selection.py` — pure token boundaries plus model/View integration

## Fixed design

- Add `PDFView.page_x_positions`, parallel to `page_y_positions` and `page_heights`.
- `initialize_continuous_placeholders()` computes all scaled page widths first, uses the maximum as the scene column width, and places each page at `(max_width - page_width) / 2`.
- Centralize page origin access with `_page_scene_x(page_idx)` / `_page_scene_y(page_idx)` and document-to-scene helpers. Every continuous-mode scene↔document x conversion subtracts/adds the page x origin.
- Page pixmap replacement never changes item position; low/high worker results inherit the placeholder position.
- Single-page mode retains x origin 0 and its current behavior.
- Numeric expansion is a pure View-local helper. Tokens may contain digits, decimal points, commas, or `/`, plus one leading minus. Leading/trailing separators are trimmed. Letters are boundaries, so `ABC123DEF` selects `123`, while `A-123.45` selects `-123.45`.
- Model exposes only character context at a strict point: full run text, hit character index, and per-character PDF rectangles. It remains Qt-free and delegates to `get_text_info_at_point(..., allow_fallback=False)` plus `get_chars_in_run()`.
- Browse-mode viewport double-click asks the controller façade for character context, applies pure token bounds, stores the selected text/rect in `TextSelectionManager`, and reuses the existing highlight/copy path. Nonnumeric clicks return `False` so existing behavior continues.

## Red-light tests

1. Mixed 300/600/400 pt pages center at x=150/0/100 in a 600 pt scene column.
2. Centering remains correct after scale changes and page pixmap replacement.
3. Scene→document→scene points and rectangles round-trip with page x/y origins.
4. Text selection, object selection, hover outlines, annotation rectangles, and inline editor placement include the page x origin.
5. Pure token cases: `123456`, `123.45`, `A-123.45`, `2026/07/02`, `ABC123DEF`, `1,234.56`, `-42`, separator/non-numeric clicks.
6. Real-PDF character-at-point returns the correct run text/index/rects and rejects blank space.
7. Numeric double-click populates the existing selection/copy state; a nonnumeric double-click is not consumed.

## Steps

1. Add focused tests and capture the failing output.
2. Add page-x state and origin helpers; update placeholder layout and all targeted coordinate sites.
3. Add model/controller character-context query.
4. Add pure numeric bounds and TextSelectionManager selection method; route viewport double-click.
5. Run centering, text selection, object manipulation, annotation, no-jump editor, and rendering regressions.
6. Update architecture/pitfalls/TODO, archive this plan after the whole tranche passes.

## Open questions resolved

- The column centers pages against the widest document page, not the current viewport width. This keeps scene coordinates stable when sidebars/window width change; normal `QGraphicsView` centering handles a viewport wider than the scene.
- Numeric selection is run-local. Tokens split across PDF spans are not merged in M3.6 because cross-run punctuation/reading-order ambiguity would change the text-selection contract.

## Completion evidence

- Red phase: collection failed because `numeric_token_bounds` did not exist.
- Focused centering/numeric tests: 17 passed.
- Text-selection/object/annotation/no-jump geometry regressions: 450 passed, 6 skipped.
- Full M3.6 suite: 1788 passed, 21 skipped in 228.84 s.
- Ruff: all checks passed.
- mypy: success, no issues in 36 source files.
