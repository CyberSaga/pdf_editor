# Fix Inline Editor Glyph Resizing Regression

**Summary**
Fix the real root cause of the glyph-size change when opening the inline editor: the editor initially computes the correct display font size, but `PDFView._sync_text_property_panel_state()` reads that display-scaled Qt size back into the PDF point-size combo box. The combo change handler then treats it as a PDF size and scales it again, shrinking/enlarging the editor glyphs on open.

**Key Changes**
- In `view/pdf_view.py`, change the live-editor branch of `_sync_text_property_panel_state()` so it does not call `_set_text_property_font_and_size(editor_widget.font().family(), editor_widget.font().pointSize())`.
- Keep the property panel state source-of-truth as the PDF-point combo values already set by `TextEditManager.create_text_editor()`.
- Do not change `EditTextRequest.size`, `MoveTextRequest.size`, or model-layer PDF point-size semantics.
- Leave `_display_font_pt()` in `view/text_editing.py` as the display-only conversion path.

**Regression Tests**
- Add a failing test in `test_scripts/test_text_editing_gui_regressions.py` that uses a real `InlineTextEditor` and real `QComboBox` signals, not the fake editor/no-op sync path.
- Test scenario:
  - `render_scale = 1.0`
  - source PDF size `20.0`
  - create editor through `TextEditManager.create_text_editor()`
  - assert `view.text_size.currentText() == "20"`
  - assert editor display font still equals `_display_font_pt(20.0, 1.0)`
  - assert visual ratio `(editor.font().pointSizeF() * logical_dpi / 72) / (20.0 * render_scale)` is about `1.0`
- This test should fail on current `HEAD` with ratio about `0.75` and combo text `"15"`, then pass after the fix.
- Keep existing height/mask/font tests, but do not rely on them as proof of this bug because the current green suite misses the live sync path.

**Verification**
- Run:
  - `python -m pytest test_scripts/test_text_editing_gui_regressions.py::test_live_editor_panel_sync_does_not_rescale_display_font_on_open -q`
  - `python -m pytest test_scripts/test_text_editing_gui_regressions.py -q`
- Optional evidence probe after the fix:
  - open a temp PDF with 20pt Helvetica text
  - create the editor from the real hit target
  - confirm `with_sync` and `no_sync` both report visual ratio near `1.0`

**Assumptions**
- Target branch is current `codex/best-text-editing-ux`.
- The desired behavior is: opening an edit box must not alter visible glyph size before the user changes the font-size control.
- Public APIs and stored PDF sizes remain in PDF points; only the Qt display font uses DPI/render-scale conversion.
