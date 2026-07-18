# Manual verification checklist

## M3.2 — Platform and printing

### Print placement

- [V] Open a portrait PDF and print to PDF.
- [V] Confirm content is centered on the **physical paper**, not merely inside the printable area.
- [V] Repeat with a landscape page.
- [?] If available, repeat using a physical printer with asymmetric hardware margins. Don't have printer with asymmetric hardware margins
- [V] Confirm left/right and top/bottom free margins appear balanced.

### Cold-start print precedence

Verify:

- [X] Every setting explicitly changed in the application wins. 喜好設定為短編雙面，有改成app的單面了；喜好設定為黑白，app選單色印出來還是黑白；PPI我在app裡設200但印出來我看不出是多少。第二次修復後：長邊雙面沒有依app變單面，黑白也沒有依app變彩色。但有變短編雙面。
- [V] Untouched driver-specific settings remain inherited. 喜好設定為手送紙盤，app沒得選，有保持在手送紙盤。
- [X] The second print in the same process produces the same settings. 對話框沒有記得第一次列印時手動修改的設定，自動重置為系統預設值了。修復後有記得了，且完全關閉視窗後再重開也有變回預設值（非系統喜好設定，可能是app自己的預設值）。
- [V] Canceling the print dialog does not persist partially changed settings. 因上一項有問題，這一項還不能測。前項修復後來測試，成功沒有記憶住被取消的設定了。

### Existing-instance foreground handoff

- [V] Start the editor and minimize or obscure it.
- [V] Double-click a PDF in File Explorer.
- [V] Confirm the existing process is reused.
- [V] Confirm the document opens exactly once.
- [△] Confirm the existing window restores, raises, and receives focus. 從最小化彈出時有focus並接受快捷鍵，但開啟一個新視窗實例時不接受PgUp/PgDn，卻接受F2、F3

### Application icon surfaces

Check both source-run and packaged modes where available:

- [V] Window title bar.
- [V] Windows taskbar.
- [V] Alt+Tab switcher.
- [V] Executable icon in File Explorer.
- [V] Temporarily make the configured icon unavailable and confirm startup remains nonfatal with one warning.

The File Explorer executable-resource icon remains dependent on the distribution/PyInstaller packaging track.

---

## M3.3 — Page structure

The primary thumbnail drag behavior was already accepted during this session, but the final regression pass should cover:

- [V] Drag the first page downward.
- [V] Drag a middle page to the first position.
- [V] Drag a page to the final position.
- [V] Hover near the top/bottom during a drag and confirm thumbnail auto-scroll.
- [V] Confirm the thumbnail count never decreases during a move.
- [V] Undo and redo every direction.
- [V] Save, close, and reopen; confirm the reordered page sequence persists.
- [V] Delete or rotate a page after reordering and confirm the visible post-move page is targeted.

### Delete-all placeholder

- [V] Delete every page after confirming the warning.
- [V] Confirm exactly one blank page remains.
- [V] Undo and redo.
- [V] Insert/import a real page and confirm the placeholder disappears.
- [V] Save and reopen the delete-all result.

---

## M3.4 — Shell and tabs

### Responsive shell

- [V] Resize the window to 720×520 at 100% display scale.
- [V] Confirm both sidebars collapse below the compact-width threshold.
- [V] Confirm the central canvas remains usable without overlapping controls.
- [X] Expand the window and confirm only previously visible sidebars return. both left and right sidebars return no matter they were visible before compacting or not.
- [V] Repeat in light and dark themes; capture screenshots if desired.

### Tab controls

- [V] Confirm every tab has a visible 20×20 close button.
- [V] Confirm active/inactive and hover styling is clear.
- [V] Close a clean tab.
- [V] Close a dirty tab and exercise Save, Discard, and Cancel.
- [V] Confirm `Ctrl+W` uses the same close pipeline.

### Reveal in folder

- [V] Right-click a saved tab and select `開啟檔案所在位置`.
- [V] Test a path containing spaces and Unicode.
- [V] If available, test a network/UNC path.
- [V] Confirm the exact file is selected in Explorer.
- [V] Confirm the action is disabled for unsaved or missing files.

### Page-navigation keys

With canvas focus:

- [V] PgUp/PgDn navigate by page.
- [X] Home navigates to the first page. No move. Fixed once still doesn't move.
- [X] End navigates to the final page. No move. Same.
- [V] Boundary presses do not produce invalid page numbers.
- [V] The same keys remain available to text inputs and inline editors.

### Recent files

- [V] Open files through the dialog, drag/drop, CLI, and forwarded existing-instance path.
- [V] Restart the application and confirm MRU persistence.
- [V] Confirm most-recent-first ordering and canonical deduplication.
- [V] Confirm the list is limited to ten entries.
- [V] Delete or move one listed file and confirm it remains visible but disabled.
- [V] Confirm temporary/print-spool files are not recorded.

---

## M3.5 — Editing tools

### Edge and corner resizing

- [V] Drag all four corner handles.
- [V] Drag top, right, bottom, and left midpoint handles.
- [V] Confirm midpoint handles change only one dimension.
- [V] Confirm the opposite edge remains fixed.
- [V] Confirm minimum size is enforced.
- [X] Confirm Shift locks the aspect ratio for corners only. Shift not locking.
- [V] Repeat at 50%, 100%, and 200% zoom.
- [X] Undo and redo each resize. Resize doesn't go into undo/redo sequence. But it isn't expected to so no more move.

### Rectangle appearance

Create combinations of:

- [V] Stroke only/no fill.
- [X] Independent stroke and fill colors. Can't fill colors.
- [X] Several border widths, including 0.1 and 20 pt. No place to pick border widths.
- [X] Different opacity values. No place to set rect opacity values.
- [V] Confirm preview and committed appearance match. preview rect and committed rect matches.
- [V] Save and reopen.
- [V] Move/resize the reopened rectangle and confirm its appearance remains intact.
- [V] Undo and redo.

### Underline and strikeout

- [△] Create underline over single-line text. Drawn as cursor moves. But cause page to jump to other place. Still jump.
- [X] Create underline over multi-line text. Only drawn on Y-axis where mouseup. Only mousemove's path would be drawn.
- [X] Repeat with strikeout. Didn't.
- [X] Confirm selected color and opacity. Keeped as yellow with certain opacity. No place to set.
- [V] Undo and redo.
- [V] Save and reopen; confirm annotations persist.

### Metadata

For an ordinary PDF:

- [V] Edit title, author, subject, and keywords.
- [V] Confirm creator, producer, and date fields remain unchanged. Unchanged. But doesn't see date field.
- [V] Undo and redo.
- [V] Save and reopen; confirm values persist.

For an encrypted PDF:

- [V] Repeat the metadata edit.
- [X] Save and reopen using the expected password. When reopen it didn't ask for password, but only open a file with all pages blank.
- [X] Confirm encryption was not removed.
- [V] Confirm dirty-tab state clears only after successful save.

---

## M3.6 — Rendering and geometry

Use:

`test_files\MIC-VB-HVAC-DWG-0001 空調系統設計圖說20260528-Bb版.pdf`

### Complex-vector responsiveness

- [V] Open the fixture from a closed application.
- [V] Confirm a low-resolution first page appears before thumbnails finish.
- [V] Open it again in an already-running application.
- [V] Navigate to at least five dense pages, including around page 25.
- [X] Zoom in and out repeatedly. So slow.
- [X] Confirm the whole UI no longer freezes during high-quality or prefetch rendering. Freeze on each operation.
- [X] While rendering, switch to another open tab; confirm input is processed within two seconds. Only to get frozen.
- [X] While rendering, close the complex tab/window; confirm input is processed within two seconds. Only to get frozen.
- [V] Confirm no stale page from the old tab/profile/zoom appears afterward.
- [X] After closing and waiting ten seconds, confirm process memory is no more than approximately 150 MB above the pre-open baseline. 開著"test_files\MIC-VB-HVAC-DWG-0001 空調系統設計圖說20260528-Bb版.pdf"時記憶體固定佔用 500 ~ 700 MB 之間，關掉該分頁立刻降到 460 MB，接著就停在 460 ~ 480 MB 之間。
- [X] Compare five sampled pages visually against the previous renderer for missing content. PDF-XChange Editor 基本上佔用 670 ~ 750 MB 之間，但操作流暢多了。關閉分頁後基礎程式佔用 150 MB。而且 PDF-XChange Editor 的顏色鮮明對比清晰多了。

### Mixed-width page centering

Use or create a PDF with mixed portrait and landscape pages:

- [V] Confirm every page is horizontally centered in the document column.
- [V] Repeat after zoom changes.
- [V] Repeat after window resize.
- [V] Repeat after sidebar collapse/restore.
- [V] Repeat after tab switches.
- [V] Test text selection on a narrow centered page.
- [V] Test object selection/move/resize.
- [X] Test rectangle, highlight, underline, and strikeout placement. 呈現的位置都會比實際點選的位置往下往右偏移。
- [V] Open an inline text editor and confirm it aligns with the clicked text.

### Numeric double-click

Confirm exact copied selection for:

- [V] `123456` → `123456`
- [V] `123.45` → `123.45`
- [V] `A-123.45` → `-123.45`
- [V] `2026/07/02` → `2026/07/02`
- [V] `ABC123DEF` → `123`
- [V] `1,234.56` → `1,234.56`
- [V] `-42` → `-42`
- [V] Double-clicking ordinary letters falls back without creating a numeric selection.
- [V] Existing drag selection still works afterward.

---

## M3.7 — Notes and bookmarks

Use:

`test_files\test-hierarchy-bookmarks.pdf`

### Compact notes

- [V] Enter Add Annotation mode and create several notes.
- [V] Confirm each new note uses a compact marker rather than a 200×50 body.
- [V] Click a marker in browse mode and confirm the floating editor opens.
- [V] Confirm the popup is parented to the main window and creates no taskbar or Alt+Tab entry.
- [V] Drag the popup at least 50 px and confirm the marker does not move. 但是希望可以抓到註解的那個可點擊區域是可見的
- [V] Drag the marker at least 50 px and confirm its persisted PDF position changes.
- [V] Edit and save note text.
- [V] Close and reopen the note popup; confirm the updated text. 
- [△] Save the PDF, close, and reopen it; confirm marker position and content persist. 會保留。但關閉分頁後，已打開的註解視窗會繼續留在主視窗實例內不會消失。修完會消失了
- [△] Delete a note and undo/redo. 可刪除。但刪除後已打開的註解視窗會繼續留在主視窗實例內不會消失。修完會消失了
- [V] Confirm legacy FreeText annotations remain listed and jumpable but read-only.

### Bookmarks/TOC

Start with a nested TOC:

- [V] Confirm root/child nesting is displayed correctly.
- [V] Activate a bookmark and confirm navigation to the correct page.
- [V] Add a bookmark.
- [X] Rename a bookmark. 沒找到怎麼操作。修完可以了
- [X] Change its page number. 沒找到怎麼操作。修完可以了
- [V] Delete a bookmark.
- [V] Move bookmarks up/down among siblings.
- [V] Insert a page before bookmarked content and confirm targets follow the original content.
- [V] Delete a bookmarked page and confirm the target maps to the nearest surviving page.
- [V] Move a page forward and backward and confirm targets follow it. 可以。但每按一次上移或下移就會取消聚焦該書籤，還要重新點一次太麻煩。
- [V] Delete all pages and confirm every target maps to page 1.
- [V] Undo and redo structural operations.
- [V] Save and reopen; confirm hierarchy and page targets persist. 有保留。但關閉分頁後書籤不會消失，要關閉視窗才會。修完會消失了

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

- [V] Open two ordinary PDFs plus the complex-vector fixture.
- [V] Reorder pages in one tab.
- [V] Add rectangle, underline, note, metadata, and bookmark changes.
- [V] Detach the dirty tab.
- [V] Switch the primary to the complex fixture while the detached window remains open. 會當機。但不管開檔案的當下或開著檔案期間都會（只有視窗當，其他應用程式不受影響）
- [V] Save the detached document to a new path.
- [V] Close both windows independently.
- [ ] Reopen the saved output and verify pages, annotations, metadata, notes, bookmarks, and encryption where applicable.