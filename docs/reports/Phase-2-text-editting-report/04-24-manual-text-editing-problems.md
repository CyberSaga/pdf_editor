# Manual Text Editing Problems

Date: 2026-04-24
Branch: `codex/best-text-editing-ux`

## Scope

- Launched the project GUI with `test_files\when I was young I.pdf`.
- Pressed `F2` to enter text edit mode.
- Clicked, double-clicked, selected, and typed into detected text.
- Opened `test_files\1.pdf` in the same GUI and repeated the same text editing flow.

## Problems Observed

1. `F2` has weak mode feedback.
   - First press produced no visible change until the canvas had focus.
   - When edit mode does activate, the main confirmation is dashed boxes around text, not a clear mode state.
   - Evidence: `manual_after_f2.png`, `manual_focus_canvas_after_f2.png`.

2. Text selection granularity is hard to predict.
   - On the rotated PDF, the sentence is split into separate vertical editable runs: `song.`, `to the radio...`, and `when I was young...`.
   - The user must discover which fragment is editable by clicking around; it does not feel like selecting a coherent sentence.
   - Evidence: `manual_focus_canvas_after_f2.png`, `manual_double_click_main_text.png`.

3. Editing rotated text leaves awkward active boxes.
   - Double-clicking a vertical text run creates a tall dashed editor boundary with a cursor at the bottom.
   - Neighboring runs remain outlined, so the active target is visually noisy.
   - Evidence: `manual_double_click_main_text.png`.

4. Typing into rotated text is technically possible, but the result is easy to miss.
   - After typing `abc`, the tab and thumbnail marked the document dirty and the selected run changed, but the edit is small and visually ambiguous in the vertical layout.
   - Evidence: `manual_type_after_clicks.png`.

5. Horizontal text reconstruction can be visually wrong before the user edits anything.
   - In `1.pdf`, entering text mode produced replacement characters in text that originally rendered more cleanly.
   - The smaller line `run or not run` overlaps with the larger paragraph editor instead of occupying a stable separate line or layer.
   - Evidence: `manual_1pdf_opened.png`, `manual_1pdf_after_f2.png`.

6. Paragraph editor bounds are still too broad for the perceived text object.
   - In `1.pdf`, the active paragraph box spans much wider than the actual visible text, making it hard to understand what object will be edited.
   - Evidence: `manual_1pdf_after_f2.png`, `manual_1pdf_double_click_1.png`.

7. Text input focus is not obvious.
   - After selecting a paragraph in `1.pdf`, typing `XYZ` did not visibly insert characters at the expected click location.
   - The UI did not make it clear whether the paragraph box, the canvas, or a non-editable selection had focus.
   - Evidence: `manual_1pdf_type_test.png`.

## Improvement Targets

1. Add a clear edit-mode state indicator after `F2`, including when the canvas did not have focus.
2. Distinguish selectable text-object outlines from the active editor outline.
3. Improve text-run grouping so sentence-level editing feels coherent, especially for rotated text.
4. Keep background underlays opaque enough to cover original glyphs while avoiding sampled grey blocks.
5. Preserve text decoding and font fallback fidelity when entering edit mode.
6. Prevent overlapping text runs from being merged into one confusing editor.
7. Make input focus visible with a cursor, selection highlight, or active-editor affordance before accepting typed text.
