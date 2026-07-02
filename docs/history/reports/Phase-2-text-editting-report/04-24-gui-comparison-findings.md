# Phase 2 GUI Comparison — Findings (2026-04-24)

Comparison of our editor vs Adobe Acrobat Pro on `veraPDF(PDF-A驗證工具).pdf`, both in text-edit mode. Interaction performed via scripted Win32 (SetCursorPos + mouse_event) and screenshot capture.

## Finding 1 — Oversized inline editor / visible grey mask rectangle

**Severity:** High (visible visual artifact, obvious vs Acrobat)

**Repro (x2 distinct clicks, consistent result):**
- Click 1 at screen (900,400) landed on line `而使用在檔案歸檔的標準即是 PDF/A(Archive)，這種格式標準能確保`. Editor opened with the text at the top and **~300px of solid grey background below**, versus a real line height of ~45px. Grey area ≈ 6× the text height. Screenshot: `evidence_oversized_editor_1.png`.
- Click 2 at (800,440) landed on line `電子檔案經過數十年，依然能正常讀取及開啟，而且文件呈現格式與`. Same pattern — one line of text, then a large grey rectangle extending to the next paragraph boundary. Screenshot: `evidence_oversized_editor_2.png`.

**Contrast with block-outline rendering (not active editor):**
Other blocks on the same page show tight dashed outlines (~50px tall, hugging the text). The oversizing only appears when the block is opened as the active inline editor.

**Likely root cause (code-level):**
`_compute_editor_proxy_layout` at `view/text_editing.py:244` sets `height_px = round(scaled_rect.height)` straight from the target's scene-coord rect. When the resolver returns a paragraph-sized rect (mode=paragraph) but the actual rendered text occupies only one line, the editor proxy is sized to the paragraph rect and the scene mask item fills that same oversized area, producing the grey void.

Phase 2 Task 4 declared this path "✅ Fixed in Task 2" on the evidence that `_editing_initial_size` became float — but that only fixed the font-size rounding. The height inflation from paragraph rect was not touched, and no red-light test covers it.

**Proposed fix direction:**
- Either tighten the resolver's returned rect to the actual content-bbox when resolution is paragraph-mode, or
- Clamp editor height to `n_lines * line_height` inside `_compute_editor_proxy_layout` using span metadata on `rect`.
- Add a red-light regression test that opens an editor on a paragraph block whose rendered content is one line, and asserts `editor_height_px ≈ line_height` (not `paragraph_height`).

## Finding 2 — Mask color visibly differs from page background

**Severity:** Medium (cosmetic, but breaks the "invisible mask" illusion)

The mask rectangle is a detectably darker grey than the surrounding page (which is pure white in this PDF). The mask color is sampled via `_sample_page_mask_color` / `_average_image_rect_color`, which averages scene pixels in the target rect — for a rect that straddles text + whitespace the average is grey. Acrobat's equivalent edit box shows a clean white background matching the page.

**Proposed fix direction:** Sample the mask color from a strip of *whitespace adjacent* to the rect (e.g., the margin to the left of the text), not the rect interior which contains text pixels.

## What was verified as NOT broken

- Block outlines on non-active text are tight to content.
- Clicking a line opens the editor with the correct text content at the correct anchor position.
- Escape cleanly discards the edit without layout shift.
- No crash, no freeze, no hang under scripted interaction.

## Artifacts

- `evidence_oversized_editor_1.png` — first repro
- `evidence_oversized_editor_2.png` — second repro, different line
