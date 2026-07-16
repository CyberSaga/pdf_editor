# Manual verification checklist

## M3.2 — Platform and printing

### Print placement

- [ ] Open a portrait PDF and print to PDF.
- [ ] Confirm content is centered on the **physical paper**, not merely inside the printable area.
- [ ] Repeat with a landscape page.
- [ ] If available, repeat using a physical printer with asymmetric hardware margins.
- [ ] Confirm left/right and top/bottom free margins appear balanced.

### Cold-start print precedence

1. Fully terminate the editor and its print helper processes.
2. Configure printer defaults to:
   - Portrait
   - Simplex
   - Grayscale
   - A4
3. Start the editor fresh and select conflicting application options:
   - Landscape
   - Duplex
   - Color
   - A3 or another available paper size
4. Print the first job.

Verify:

- [ ] Every setting explicitly changed in the application wins.
- [ ] Untouched driver-specific settings remain inherited.
- [ ] The second print in the same process produces the same settings.
- [ ] Canceling the print dialog does not persist partially changed settings.

### Existing-instance foreground handoff

- [ ] Start the editor and minimize or obscure it.
- [ ] Double-click a PDF in File Explorer.
- [ ] Confirm the existing process is reused.
- [ ] Confirm the document opens exactly once.
- [ ] Confirm the existing window restores, raises, and receives focus.

### Application icon surfaces

Check both source-run and packaged modes where available:

- [ ] Window title bar.
- [ ] Windows taskbar.
- [ ] Alt+Tab switcher.
- [ ] Executable icon in File Explorer.
- [ ] Temporarily make the configured icon unavailable and confirm startup remains nonfatal with one warning.

The File Explorer executable-resource icon remains dependent on the distribution/PyInstaller packaging track.

---

## M3.3 — Page structure

The primary thumbnail drag behavior was already accepted during this session, but the final regression pass should cover:

- [ ] Drag the first page downward.
- [ ] Drag a middle page to the first position.
- [ ] Drag a page to the final position.
- [ ] Hover near the top/bottom during a drag and confirm thumbnail auto-scroll.
- [ ] Confirm the thumbnail count never decreases during a move.
- [ ] Undo and redo every direction.
- [ ] Save, close, and reopen; confirm the reordered page sequence persists.
- [ ] Delete or rotate a page after reordering and confirm the visible post-move page is targeted.

### Delete-all placeholder

- [ ] Delete every page after confirming the warning.
- [ ] Confirm exactly one blank page remains.
- [ ] Undo and redo.
- [ ] Insert/import a real page and confirm the placeholder disappears.
- [ ] Save and reopen the delete-all result.

---

## M3.4 — Shell and tabs

### Responsive shell

- [ ] Resize the window to 720×520 at 100% display scale.
- [ ] Confirm both sidebars collapse below the compact-width threshold.
- [ ] Confirm the central canvas remains usable without overlapping controls.
- [ ] Expand the window and confirm only previously visible sidebars return.
- [ ] Repeat in light and dark themes; capture screenshots if desired.

### Tab controls

- [ ] Confirm every tab has a visible 20×20 close button.
- [ ] Confirm active/inactive and hover styling is clear.
- [ ] Close a clean tab.
- [ ] Close a dirty tab and exercise Save, Discard, and Cancel.
- [ ] Confirm `Ctrl+W` uses the same close pipeline.

### Reveal in folder

- [ ] Right-click a saved tab and select `開啟檔案所在位置`.
- [ ] Test a path containing spaces and Unicode.
- [ ] If available, test a network/UNC path.
- [ ] Confirm the exact file is selected in Explorer.
- [ ] Confirm the action is disabled for unsaved or missing files.

### Page-navigation keys

With canvas focus:

- [ ] PgUp/PgDn navigate by page.
- [ ] Home navigates to the first page.
- [ ] End navigates to the final page.
- [ ] Boundary presses do not produce invalid page numbers.
- [ ] The same keys remain available to text inputs and inline editors.

### Recent files

- [ ] Open files through the dialog, drag/drop, CLI, and forwarded existing-instance path.
- [ ] Restart the application and confirm MRU persistence.
- [ ] Confirm most-recent-first ordering and canonical deduplication.
- [ ] Confirm the list is limited to ten entries.
- [ ] Delete or move one listed file and confirm it remains visible but disabled.
- [ ] Confirm temporary/print-spool files are not recorded.

---

## M3.5 — Editing tools

### Edge and corner resizing

- [ ] Drag all four corner handles.
- [ ] Drag top, right, bottom, and left midpoint handles.
- [ ] Confirm midpoint handles change only one dimension.
- [ ] Confirm the opposite edge remains fixed.
- [ ] Confirm minimum size is enforced.
- [ ] Confirm Shift locks the aspect ratio for corners only.
- [ ] Repeat at 50%, 100%, and 200% zoom.
- [ ] Undo and redo each resize.

### Rectangle appearance

Create combinations of:

- [ ] Stroke only/no fill.
- [ ] Independent stroke and fill colors.
- [ ] Several border widths, including 0.1 and 20 pt.
- [ ] Different opacity values.
- [ ] Confirm preview and committed appearance match.
- [ ] Save and reopen.
- [ ] Move/resize the reopened rectangle and confirm its appearance remains intact.
- [ ] Undo and redo.

### Underline and strikeout

- [ ] Create underline over single-line text.
- [ ] Create underline over multi-line text.
- [ ] Repeat with strikeout.
- [ ] Confirm selected color and opacity.
- [ ] Undo and redo.
- [ ] Save and reopen; confirm annotations persist.

### Metadata

For an ordinary PDF:

- [ ] Edit title, author, subject, and keywords.
- [ ] Confirm creator, producer, and date fields remain unchanged.
- [ ] Undo and redo.
- [ ] Save and reopen; confirm values persist.

For an encrypted PDF:

- [ ] Repeat the metadata edit.
- [ ] Save and reopen using the expected password.
- [ ] Confirm encryption was not removed.
- [ ] Confirm dirty-tab state clears only after successful save.

---

## M3.6 — Rendering and geometry

Use:

`test_files\MIC-VB-HVAC-DWG-0001 空調系統設計圖說20260528-Bb版.pdf`

### Complex-vector responsiveness

- [ ] Open the fixture from a closed application.
- [ ] Confirm a low-resolution first page appears before thumbnails finish.
- [ ] Open it again in an already-running application.
- [ ] Navigate to at least five dense pages, including around page 25.
- [ ] Zoom in and out repeatedly.
- [ ] Confirm the whole UI no longer freezes during high-quality or prefetch rendering.
- [ ] While rendering, switch to another open tab; confirm input is processed within two seconds.
- [ ] While rendering, close the complex tab/window; confirm input is processed within two seconds.
- [ ] Confirm no stale page from the old tab/profile/zoom appears afterward.
- [ ] After closing and waiting ten seconds, confirm process memory is no more than approximately 150 MB above the pre-open baseline.
- [ ] Compare five sampled pages visually against the previous renderer for missing content.

### Mixed-width page centering

Use or create a PDF with mixed portrait and landscape pages:

- [ ] Confirm every page is horizontally centered in the document column.
- [ ] Repeat after zoom changes.
- [ ] Repeat after window resize.
- [ ] Repeat after sidebar collapse/restore.
- [ ] Repeat after tab switches.
- [ ] Test text selection on a narrow centered page.
- [ ] Test object selection/move/resize.
- [ ] Test rectangle, highlight, underline, and strikeout placement.
- [ ] Open an inline text editor and confirm it aligns with the clicked text.

### Numeric double-click

Confirm exact copied selection for:

- [ ] `123456` → `123456`
- [ ] `123.45` → `123.45`
- [ ] `A-123.45` → `-123.45`
- [ ] `2026/07/02` → `2026/07/02`
- [ ] `ABC123DEF` → `123`
- [ ] `1,234.56` → `1,234.56`
- [ ] `-42` → `-42`
- [ ] Double-clicking ordinary letters falls back without creating a numeric selection.
- [ ] Existing drag selection still works afterward.

---

## M3.7 — Notes and bookmarks

### Compact notes

- [ ] Enter Add Annotation mode and create several notes.
- [ ] Confirm each new note uses a compact marker rather than a 200×50 body.
- [ ] Click a marker in browse mode and confirm the floating editor opens.
- [ ] Confirm the popup is parented to the main window and creates no taskbar or Alt+Tab entry.
- [ ] Drag the popup at least 50 px and confirm the marker does not move.
- [ ] Drag the marker at least 50 px and confirm its persisted PDF position changes.
- [ ] Edit and save note text.
- [ ] Close and reopen the note popup; confirm the updated text.
- [ ] Save the PDF, close, and reopen it; confirm marker position and content persist.
- [ ] Delete a note and undo/redo.
- [ ] Confirm legacy FreeText annotations remain listed and jumpable but read-only.

### Bookmarks/TOC

Start with a nested TOC:

- [ ] Confirm root/child nesting is displayed correctly.
- [ ] Activate a bookmark and confirm navigation to the correct page.
- [ ] Add a bookmark.
- [ ] Rename a bookmark.
- [ ] Change its page number.
- [ ] Delete a bookmark.
- [ ] Move bookmarks up/down among siblings.
- [ ] Insert a page before bookmarked content and confirm targets follow the original content.
- [ ] Delete a bookmarked page and confirm the target maps to the nearest surviving page.
- [ ] Move a page forward and backward and confirm targets follow it.
- [ ] Delete all pages and confirm every target maps to page 1.
- [ ] Undo and redo structural operations.
- [ ] Save and reopen; confirm hierarchy and page targets persist.

---

## M3.8 — Detached tabs

This is the primary remaining manual acceptance gate.

### Saved tab

- [V] Open at least two PDFs in the primary window.
- [V] Click a tab without dragging; confirm no detachment.
- [V] Make a short drag; confirm no detachment.
- [X] Drag and release inside the tab bar/window; confirm no detachment. 也會分離視窗，但滿意
- [V] Drag one tab beyond the tab bar/window boundary and release.
- [V] Confirm exactly one secondary window appears.
- [V] Confirm the primary retains every other tab.
- [V] Confirm the transferred tab is removed from the primary only after the secondary is ready.
- [V] Confirm current page, zoom, color profile, source path, and saved path are restored.
- [V] Edit and save in the detached window.
- [V] Close and reopen the result; confirm persistence.

### Dirty tab

- [V] Modify a document without saving.
- [V] Drag the dirty tab into a detached window.
- [V] Confirm the destination still displays dirty state.
- [V] Confirm pre-detach undo history is unavailable, as documented.
- [V] Confirm new edits in the detached window create a new independent undo history.
- [V] Save and confirm dirty state clears through the normal save path.
- [V] Close without saving and confirm the detached window presents its own prompt.
- [V] Confirm the primary window’s close prompts and state are independent.

### Failure and lifecycle checks

- [?] Force or simulate destination creation failure where practical; confirm the source tab remains intact. 看不懂要測什麼、能手動測GUI嗎
- [V] Detach a tab from a secondary window into another window.
- [V] Close one secondary window and confirm other windows remain functional.
- [V] Confirm render, thumbnail, search, OCR, and print workers are not shared across windows. （OCR未測試：Surya未安裝）
- [V] Double-click another PDF in Explorer and confirm single-instance forwarding still targets the primary window. ※ 但將主視窗關閉後，點擊檔案兩下會無法打開任何檔案分頁或視窗，可能是第二視窗沒有升級成主視窗
- [?] Confirm snapshot bytes and passwords never appear in logs, preferences, or error representations. 沒輸出資訊到 console 無從確認

---

## Recommended final smoke sequence

- [ ] Open two ordinary PDFs plus the complex-vector fixture.
- [ ] Reorder pages in one tab.
- [ ] Add rectangle, underline, note, metadata, and bookmark changes.
- [ ] Detach the dirty tab.
- [ ] Switch the primary to the complex fixture while the detached window remains open.
- [ ] Save the detached document to a new path.
- [ ] Close both windows independently.
- [ ] Reopen the saved output and verify pages, annotations, metadata, notes, bookmarks, and encryption where applicable.