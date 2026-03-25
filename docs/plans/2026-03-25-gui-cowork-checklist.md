# Track A/B GUI Follow-up Checklist

These items require GUI interaction or event-timing verification and should be exercised with Claude Cowork.

## Still GUI-driven

1. `view/pdf_view.py` no-edit finalize ghost text
   - Repro: double-click a text block, change nothing, click outside.
   - Expect: no redraw/reinsert side effect, text count and extracted text stay unchanged.

2. `view/pdf_view.py` highlight / rect annotation scale mismatch
   - Repro: zoom to a non-100% scale, draw a highlight or rectangle over known text.
   - Expect: saved annotation aligns with the rendered text, not a stale zoom factor.

3. `view/pdf_view.py` cross-page drag in continuous mode
   - Repro: open continuous pages, drag a text editor from page 1 into page 2.
   - Expect: landing position uses the destination page origin, not the original page index.

4. `view/pdf_view.py` stale editor scale during zoom debounce
   - Repro: zoom with mouse wheel, immediately double-click text before rerender completes.
   - Expect: editor preview rect matches the final inserted position.

5. `view/pdf_view.py` undo/redo shortcut reachability
   - Repro: edit text, close the editor, press `Ctrl+Z` and `Ctrl+Y`.
   - Expect: undo/redo fire reliably even if focus does not return to the exact child widget.

6. `view/pdf_view.py` double-finalize race
   - Repro: rapid click-away / app focus change while an editor is open.
   - Expect: finalize runs once, with no duplicate edits or rollback noise.

7. `view/pdf_view.py` sub-pixel drag threshold
   - Repro: drag a text editor by a very small visible amount.
   - Expect: intentional small moves are preserved instead of being treated as no-op.

8. `controller/pdf_controller.py` viewport restore jump
   - Repro: edit text, let the page rerender, scroll immediately after save.
   - Expect: post-render restore does not yank the viewport back after the user scrolls.

9. `view/pdf_view.py` page counter on scroll
   - Repro: scroll through a multi-page document in continuous mode.
   - Expect: page counter updates with the visible page.

## Already covered by Python-side tests

- Move-only run edits should relocate without rollback.
- Move-only paragraph edits should preserve per-run colors.
- Protected span verification should report missing span IDs.
