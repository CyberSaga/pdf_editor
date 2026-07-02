# 2026-07-02 `docs/to_Update.md` Test-Plan Acceptance Criteria

Source: `docs/to_Update.md`  
Audience: implementation agents and review agents  
Format: test-plan-first acceptance criteria. Each requirement is complete only when the listed checks pass or the implementation report explicitly documents an approved deferral.

## Global Acceptance Rules

- Every item below must have either automated coverage, a repeatable manual verification script, or both.
- GUI behavior must be verified on Windows, because this project targets Windows desktop workflows.
- All changed behavior must preserve existing PDF open/edit/save, undo/redo, tab, and print workflows unless an item explicitly changes them.
- Performance claims must report the test machine, input fixture, measurement method, baseline if available, and after-change result.
- Visual-layout claims must include screenshots or an explicit manual signoff note with viewport size, zoom level, and relevant UI state.
- Any new persistent user data, such as history, must avoid storing passwords, temporary paths, or unsaved document contents.
- A pass criterion is valid only if another agent can decide pass/fail from a screenshot, file output, UI state, logged value, or measured number. Words such as "usable", "clear", "reasonable", or "graceful" must be paired with the exact observable behavior expected.

## Required Fixtures

- `test_files\MIC-VB-HVAC-DWG-0001 空調系統設計圖說20260528-Bb版.pdf` or an equivalent complex Acrobat/AutoCAD-style vector PDF with many page objects.
- A small multi-page PDF for fast UI regression checks.
- A PDF with mixed portrait/landscape pages for print centering and page operations.
- A PDF containing selectable text with numeric strings such as `123456`, `A-123.45`, and `2026/07/02`.
- A PDF with existing textboxes, rectangles, and annotations created by the app.
- At least one installed physical or virtual Windows printer where driver defaults can be changed independently from the app dialog.

## AC-FIX-01 - 全部工作流程加速

Requirement: 將所有工作流程都加速，包含開啟視窗時間與開啟檔案時間。

Test setup:
- Use a clean app start after reboot or process termination.
- Use the small multi-page PDF and the complex vector PDF.
- Record baseline timings before the change if a baseline build is available.

Test steps:
- Measure cold app launch to visible, responsive main window.
- Measure warm app launch to visible, responsive main window.
- Measure file-open time from open request to first page rendered and UI responsive.
- Measure tab switch, page navigation, zoom, thumbnail generation, and save/close responsiveness for representative files.

Pass criteria:
- No measured workflow regresses by more than 10 percent compared with baseline unless the report explains a justified trade-off.
- At least one of these measured paths improves by 15 percent or more against baseline: cold launch, warm launch, small PDF first render, complex PDF first render.
- During any measured operation, the app must repaint at least once every `500 ms`, show progress or a busy indicator within `1 s` for operations longer than `2 s`, and avoid the Windows "Not Responding" state.
- Performance tests are documented in the implementation report with exact commands or manual timing procedure.

Regression checks:
- Existing unit tests and GUI smoke tests still pass.
- A smoke test must open a PDF, add one text annotation or textbox, save to a new file, reopen that file, verify the edit exists, and close without an exception or unsaved-change prompt for the saved file.

## AC-FIX-02 - 複雜向量 PDF 載入速度

Requirement: 開啟物件很多、由 Acrobat/AutoCAD-style PDF 產生的 extremely complex vector/page content 檔案時，載入要更快。

Test setup:
- Use `test_files\MIC-VB-HVAC-DWG-0001 空調系統設計圖說20260528-Bb版.pdf` or equivalent.
- Use a repeatable timing harness or documented manual stopwatch procedure.

Test steps:
- Open the complex fixture from a closed app.
- Open the same fixture into an already-running app.
- Navigate to at least 5 pages that contain dense vector content.
- Zoom in/out and verify delayed rendering does not block the whole UI.

Pass criteria:
- Time from open request to first rendered page improves by at least 15 percent against baseline, or the implementation report must name the remaining bottleneck and include profiler/timing evidence for why it cannot be reduced in this iteration.
- First rendered page appears before full-document thumbnail generation or full-page analysis completes.
- For loads longer than `3 s`, the app shows progress or busy state within `1 s`.
- While the complex file is loading, clicking the window close button or switching to an already-open tab is processed within `2 s`.
- After closing the complex file and waiting `10 s`, process memory remains no more than `150 MB` above the pre-open baseline.

Regression checks:
- Text selection, object hit testing, thumbnails, and save/export still work on normal PDFs.
- For 5 sampled pages, screenshot comparison against baseline shows no missing page content; any intentional render difference must be listed by page number and visible region.

## AC-FIX-03 - 列印對話框選項必須覆寫印表機喜好設定

Requirement: 新開機後開啟新的視窗實例時，使用者在列印對話框中點選的選項必須被實際列印使用，不能仍依印表機屬性內的喜好設定覆寫。

Test setup:
- Configure printer driver defaults to one set of values, such as portrait, simplex, grayscale, A4.
- In the app print dialog, choose conflicting values, such as landscape, duplex, color, A3 or fit mode where available.

Test steps:
- Reboot or fully terminate app and helper processes.
- Open a PDF in a fresh app instance.
- Open print dialog and change app-side print options.
- Print to a physical printer or print-to-PDF target that records job settings.

Pass criteria:
- Touched app-side fields take precedence over driver defaults for the current job.
- Untouched driver-specific settings remain inherited from printer properties.
- Behavior matches the touched-precedence model described in `docs/README.zh-TW.md`.
- For the first print job after reboot, each app-touched setting in the test matrix appears in the print target's recorded job settings; repeat the same print without reboot and confirm the same recorded values.

Regression checks:
- Printer native properties dialog still synchronizes supported settings back to the app dialog.
- Canceling print does not persist partial or unintended option changes.

## AC-FIX-04 - Windows 工作列與檔案總管圖示

Requirement: 工作列及檔案總管顯示的圖示必須是 `%SystemRoot%\System32\pdf_editor_icon(reiya).ico` or the resolved packaged equivalent.

Test setup:
- Build or run the Windows app in the same mode users receive.
- Ensure Windows icon cache does not hide stale results, or document cache reset if needed.

Test steps:
- Launch the app and inspect the title bar, taskbar button, and Alt+Tab icon.
- Inspect the executable in File Explorer.
- Inspect associated PDF file icon if the installer/file association flow is part of the delivery.

Pass criteria:
- The title bar, taskbar, Alt+Tab switcher, and File Explorer executable icon all display `%SystemRoot%\System32\pdf_editor_icon(reiya).ico` or a byte-identical packaged copy.
- Source-run mode and packaged-executable mode both resolve the icon path without a missing-file exception.
- A screenshot or manual verification note confirms that no Qt, Python, PyInstaller, or generic executable icon appears in those four locations.

Regression checks:
- If the configured icon file is temporarily unavailable, the app starts successfully and logs one warning containing the missing icon path.
- Existing theme/action icons are unaffected.

## AC-MOD-01 - 視窗可更小且可斜線縮放

Requirement: 視窗實例可更彈性地縮得更小，並可用角落斜線縮放。

Test steps:
- Resize the main window from each edge and each corner.
- Attempt to shrink the outer window to `720 x 520` logical pixels at Windows display scale 100 percent.
- At the minimum size, open a PDF page in fit-width or fit-page mode and capture a screenshot.
- At the minimum size, verify the left thumbnail/sidebar and right properties/sidebar are hidden or collapsed and do not consume horizontal document-reading space.
- Restore the window, then resize from each corner diagonally by at least `120 px` in both axes.

Pass criteria:
- The main window can be resized to `720 x 520` logical pixels or smaller on a 100 percent scaled Windows desktop.
- At the minimum size, the central document viewport remains visible and is at least `360 px` wide and `300 px` tall after tabs/toolbars/status bars are laid out.
- At the minimum size, both sidebars are hidden/collapsed; no thumbnail list, tool panel, or sidebar strip is visible inside the shrunken window.
- At the minimum size, the open PDF page content is readable in the central viewport: fit-width or fit-page mode shows page content, not only blank margins or clipped chrome.
- Corner drag changes both window width and height during the same drag gesture; after a `120 px` diagonal drag, both dimensions change by at least `80 px`.
- No toolbar button, tab close button, document viewport, or status/progress text overlaps another visible control in the minimum-size screenshot.

Regression checks:
- Restoring/maximizing the window makes sidebars available again through their normal toggles.
- Saved window geometry never restores below `720 x 520` logical pixels or outside the visible desktop work area.

## AC-MOD-02 - 縮圖置中並隨側欄縮放

Requirement: 縮圖在縮圖列表內置中，且隨左側邊欄縮放而縮放大小；縮圖與側邊欄間留白不可過大。

Test steps:
- Open a multi-page PDF.
- Resize the left sidebar across its allowed width range.
- Toggle thumbnails/sidebar visibility.
- Inspect pages with portrait and landscape aspect ratios.

Pass criteria:
- Thumbnail pixmaps are horizontally centered in the list.
- When sidebar width changes by at least `100 px`, thumbnail image width changes in the same direction by at least `40 px`, unless it has reached the documented min/max thumbnail size.
- Thumbnail image width is clamped to a documented minimum and maximum; the implementation report must state those two values.
- Horizontal padding from thumbnail image edge to sidebar content edge is symmetric within `8 px`.
- At the narrowest allowed sidebar width, horizontal padding on each side is no more than `24 px`.
- Page labels, selection highlight, and drag/reorder affordances remain centered on the same thumbnail column; their horizontal centers differ from the thumbnail image center by no more than `8 px`.

Regression checks:
- Thumbnail generation remains lazy/cached enough to avoid UI stalls.
- High-DPI displays render thumbnails sharply.

## AC-MOD-03 - 文件閱讀區置中

Requirement: 文件在文件閱讀區置中。

Test steps:
- Open PDFs with portrait, landscape, and mixed page sizes.
- Test fit-width, fit-page, custom zoom, sidebar shown/hidden, and window resize.
- Scroll horizontally/vertically where applicable.

Pass criteria:
- Visible page content is centered in the available reading viewport when content is smaller than the viewport.
- When page content is smaller than the viewport, left and right blank margins differ by no more than `8 px`; top and bottom blank margins differ by no more than `8 px` when vertical centering applies.
- When page content is larger than the viewport, the initial horizontal scroll position is `0` or centered according to the documented zoom mode; it must not show more than `24 px` of blank margin before page content while clipping page content on the opposite side.
- Centering updates after zoom, sidebar resize, tab switch, and page navigation.

Regression checks:
- Text selection, object selection, annotation placement, and coordinate mapping remain accurate after centering.

## AC-MOD-04 - 列印預設文件置中於紙張

Requirement: 列印時預設文件在紙張置中。

Test setup:
- Use pages with content boxes smaller than paper and pages with mismatched aspect ratios.

Test steps:
- Open print preview/default print settings without changing alignment options.
- Print to PDF or inspect generated raster/page placement.

Pass criteria:
- Default print layout centers page content on the selected paper.
- Centering works for portrait and landscape pages.
- In print-to-PDF or preview output, left and right margins around the source page image differ by no more than `2 mm`; top and bottom margins differ by no more than `2 mm` when the selected scaling mode leaves free space.
- If the user selects a non-default scaling or alignment option, the output follows that option and the implementation report lists the exact option tested.

Regression checks:
- Auto paper size and orientation behavior remain correct.
- Print margins do not clip content unexpectedly.

## AC-MOD-05 - 分頁關閉按鈕常時可見

Requirement: 分頁標籤上的關閉按鈕處必須明確、常時顯示可見的打叉符號。

Test steps:
- Open one tab, multiple tabs, active/inactive tabs, long file names, and narrow window widths.
- Move mouse on/off tabs.
- Test light and dark themes if available.

Pass criteria:
- Each closable tab shows a visible close `X` without requiring hover.
- The close `X` is visible in active and inactive tabs before hover, with foreground/background contrast ratio at least `3:1`.
- The close target hit rectangle is at least `20 x 20` logical pixels.
- Long tab titles elide without covering the close button.
- Active and inactive tabs differ by at least one non-hover visual state: background color, border, or text weight; screenshot evidence must show both states.

Regression checks:
- Clicking close still triggers unsaved-change handling.
- Middle-click/keyboard close behavior, if present, remains unchanged.

## AC-MOD-06 - 文字框可拖曳邊緣縮放

Requirement: 文字框可拖曳邊緣做縮放。

Test setup:
- Create and edit app-owned textboxes on multiple pages.

Test steps:
- Select a textbox.
- Drag each edge and corner handle.
- Resize at multiple zoom levels and after page rotation if supported.
- Undo and redo resize operations.
- Record font size, textbox bounding rectangle, and rendered glyph height before and after each resize.

Pass criteria:
- Dragging a horizontal edge changes textbox height while keeping textbox width unchanged within `1 px`.
- Dragging a vertical edge changes textbox width while keeping textbox height unchanged within `1 px`.
- Dragging a corner changes both textbox width and height.
- The text inside the textbox is not scaled by the resize operation: font size remains unchanged within `0.1 pt`, and rendered glyph height remains unchanged within `1 px` at the same zoom level.
- Text may reflow, wrap, clip, or reveal more content according to the editor's documented textbox behavior, but it must not be stretched, compressed, or uniformly scaled to fit the new box.
- Text reflow/preview after resizing matches the committed PDF output when reopened at the same zoom level.
- At `50%`, `100%`, and `200%` zoom, the committed textbox rectangle differs from the drag-preview rectangle by no more than `2 px` per edge.
- Undo restores the exact pre-resize textbox rectangle and text layout; redo restores the resized rectangle and text layout.

Regression checks:
- Moving textboxes still works.
- Existing text edit behavior, including empty-text delete intent, remains intact.

## AC-MOD-07 - 字型大小可輸入小數點一位

Requirement: 字型大小除了預設選項外，還可自行輸入到小數點一位。

Test steps:
- Open the font-size control for new text and existing text edit.
- Enter values such as `9.5`, `10.0`, `12.3`.
- Try invalid values such as blank, negative, too small, too large, and more than one decimal place.
- Save, reopen, and inspect the PDF.

Pass criteria:
- Inputs with exactly one decimal place, including `9.5`, `10.0`, and `12.3`, are accepted and displayed back in the control with one decimal place.
- The committed PDF text reports or visually renders the selected font size within `0.1 pt` of the entered value.
- Blank, negative, zero, and more-than-one-decimal inputs do not commit a font-size change; the control restores the last valid value and the app stays open without an exception.
- After save and reopen, the text renders at the selected size within `0.1 pt` or within `1 px` glyph height at the same zoom level.
- Selecting an existing preset still commits that preset value exactly as before.

Regression checks:
- Existing integer font-size tests continue to pass.
- Font menu interactions do not close or commit the editor unexpectedly.

## AC-MOD-08 - 矩形顏色與無填滿邊框粗細

Requirement: 矩形可用調色盤調顏色；無填滿矩形可用數值調整邊框粗細。

Test setup:
- Create filled and no-fill rectangles.

Test steps:
- Change stroke/fill colors using a palette.
- Set no-fill rectangle border widths using numeric values, including decimal if supported.
- Save and reopen the file.
- Undo and redo color and border-width changes.

Pass criteria:
- Palette-selected colors apply to the correct rectangle property.
- No-fill rectangles preserve transparent fill while border width changes.
- Border width input accepts values in the documented allowed range; the implementation report must state the minimum, maximum, and increment.
- Values below minimum, above maximum, blank, or non-numeric do not commit a border-width change and restore the previous valid value.
- Preview and saved/reopened PDF output use the same fill color, stroke color, transparent-fill state, and border width; sampled border width differs by no more than `1 px` at 100 percent zoom.

Regression checks:
- Existing rectangle creation, selection, move, resize, and delete behavior still works.
- Color changes do not affect unrelated annotations or objects.

## AC-MOD-09 - 註解改為標籤與浮動小視窗

Requirement: 新增的註解只是一個標籤；點開後才在現行視窗實例內跳出浮動小視窗顯示註解內容。標籤和浮動視窗都可拖曳移動位置。

Test setup:
- Create new text annotations on multiple pages.

Test steps:
- Add an annotation.
- Verify only a compact label appears initially.
- Click/open the label and inspect the floating note window.
- Drag the label and the floating note window independently.
- Close/reopen the file and verify persisted behavior where supported.

Pass criteria:
- Immediately after creation, only the label/icon is visible on the page; annotation body text is not visible until the label is opened.
- The closed label footprint is no larger than `32 x 32` logical pixels unless the implementation report documents a different fixed label size.
- Clicking the label opens a floating note surface parented to the current main window; Windows taskbar and Alt+Tab do not show a separate app window for the note.
- Dragging the label by at least `50 px` changes the annotation label position by at least `45 px` in the same direction.
- Dragging the floating note by at least `50 px` changes only the popup position; the label position does not move during popup drag.
- The popup remains associated with its annotation and page.
- Annotation content can be edited, saved, reopened, and deleted.

Regression checks:
- Existing PDF annotations remain readable.
- Annotation movement and edits are undo/redo safe where existing command history supports annotations.

## AC-NEW-01 - 刪除頁與旋轉頁支援自訂範圍

Requirement: 刪除頁、旋轉頁的範圍選項多一個「自訂」。

Test steps:
- Open a multi-page PDF.
- Use delete-page dialog with custom ranges: `1`, `2-4`, `1,3,5`, reversed/invalid ranges, and out-of-range pages.
- Use rotate-page dialog with the same custom range forms.

Pass criteria:
- Custom range option appears for both delete and rotate workflows.
- Valid custom ranges affect exactly the requested pages.
- Invalid ranges, including blank, `0`, negative pages, reversed ranges, and pages greater than page count, show a validation message before mutation and leave page count/order/rotation unchanged.
- Page numbers are 1-based in the UI; range `1,3-4` on a 5-page fixture affects original pages 1, 3, and 4 only.

Regression checks:
- Existing all/current/selected range options still work.
- Undo/redo works for delete and rotate custom-range operations.

## AC-NEW-02 - 雙擊 PDF 時既有視窗浮到最上層

Requirement: 當連點兩下打開 PDF 檔時，若已有視窗實例存在，要使該視窗實例浮現到畫面最上層。

Test setup:
- Configure Windows file association to open PDFs with the app.
- Start one app instance and place it behind other windows or minimized.

Test steps:
- Double-click a PDF in File Explorer.
- Repeat with app minimized, behind another app, and on another virtual desktop if applicable.

Pass criteria:
- Existing app instance receives the file-open request within `3 s` of double-click.
- If minimized, the app window is restored within `3 s`.
- After restore/raise, the app window is the foreground window or flashes according to Windows focus-stealing restrictions; the implementation report must state which Windows behavior occurred.
- The requested PDF opens as a tab in the existing instance unless user settings explicitly choose another behavior.

Regression checks:
- Single-instance locking does not lose file paths.
- Opening multiple PDFs quickly does not create duplicate unwanted windows.

## AC-NEW-03 - 分頁可拖曳成新視窗

Requirement: 預設所有檔案在同一視窗實例內開啟，但可將檔案分頁標籤拖曳出來成為新視窗。

Test steps:
- Open at least two PDFs as tabs.
- Drag one tab outside the tab bar/window.
- Verify a new window appears with that document.
- Drag or interact with remaining tabs in the original window.

Pass criteria:
- Dragging a tab out creates a separate app window containing that document.
- Original window remains open with the remaining tab count reduced by exactly one.
- The detached document keeps its current page number, zoom value, dirty/unsaved state, and file path.
- If undo history is intentionally not preserved across detach, the implementation report must state that limitation; otherwise undo after detach must revert the last edit made before detach.
- Closing either window follows unsaved-change prompts correctly.

Regression checks:
- Normal tab reorder within the tab bar still works if supported.
- Double-click file open still defaults to existing-window tabs.

## AC-NEW-04 - 雙擊數字串選取整串數字

Requirement: 在一串數字上連點兩下左鍵，就將整串數字選取起來。

Test setup:
- Use text containing plain integers, decimals, separators, dates, and numbers adjacent to letters.

Test steps:
- Double-click inside `123456`.
- Double-click inside `123.45`.
- Double-click inside `A-123.45`, `2026/07/02`, and `ABC123DEF`.
- Copy the selection.

Pass criteria:
- A contiguous numeric token is selected according to this token rule: digits may include one decimal point, comma thousands separators, slash date separators, and a leading minus sign; letters are not included.
- Selection boundaries are character-accurate, not whole-line.
- Copied text exactly matches the highlighted numeric token.
- Double-click on non-numeric text keeps the existing word-selection behavior documented by the implementation report.

Regression checks:
- Drag selection and existing character-level selection remain accurate.
- Search highlighting is unaffected.

## AC-NEW-05 - 搜尋結果按 Enter 逐筆跳轉

Requirement: 搜尋出結果後，再多按一下 Enter 就直接跳轉到第一個、第二個、後續結果。

Test setup:
- Use a PDF with at least 3 search hits across multiple pages.

Test steps:
- Enter a search term and trigger search.
- Press Enter repeatedly while focus remains in the search field or search UI.
- Test Shift+Enter or previous-result shortcut if existing behavior supports it.

Pass criteria:
- Pressing Enter with a changed query runs the search and selects result 1.
- Each subsequent Enter advances by exactly one result in document order.
- After the final result, Enter wraps to result 1 unless the implementation report explicitly chooses no-wrap behavior; whichever behavior is chosen must be consistent for at least 10 Enter presses.
- The current result highlight is visible in the viewport within `500 ms` of pressing Enter.
- If the UI displays result count/current index, it updates within `500 ms` and matches the selected result.

Regression checks:
- Search via buttons/menu still works.
- Enter in unrelated dialogs/text editors is not hijacked by search navigation.

## AC-NEW-06 - 拖曳縮圖調換頁面順序

Requirement: 可拖曳縮圖來調換頁面順序。

Test setup:
- Use a PDF with at least 5 pages, each visually distinct.

Test steps:
- Drag page 1 thumbnail after page 3.
- Drag a middle page to the beginning.
- Attempt invalid drops outside the thumbnail list.
- Save, reopen, and inspect page order.
- Undo and redo reorder if command history supports page operations.

Pass criteria:
- Drag/drop reorder updates document page order exactly.
- After moving page 1 after page 3 in a 5-page fixture, reopened page order is original pages `2,3,1,4,5`.
- Page numbers, thumbnails, current page, and document view all reflect the same new order within `1 s` after drop.
- Saved PDF preserves the new page order.
- Invalid drops do not mutate the document.

Regression checks:
- Thumbnail selection and page navigation still work.
- Delete/rotate page operations target the correct pages after reorder.

## AC-NEW-07 - 分頁右鍵開啟檔案所在位置

Requirement: 在分頁標籤上點右鍵，可以選擇開啟檔案所在位置。

Test steps:
- Open a saved PDF from disk.
- Right-click its tab and choose open file location.
- Repeat for unsaved/new/generated documents if applicable.

Pass criteria:
- Context menu contains the exact label `開啟檔案所在位置` for disk-backed files.
- Selecting it opens File Explorer with the containing folder path equal to the PDF file's parent directory.
- When the OS supports selection, the target file is selected; otherwise the containing folder is opened and the implementation report states the OS limitation.
- For unsaved or nonexistent paths, the menu item is disabled or shows a message that includes the file path and no document state changes.

Regression checks:
- Other tab context actions still work.
- Paths with spaces, Unicode, and network/OneDrive locations are handled.

## AC-NEW-08 - Ctrl+W 關閉當前分頁且保留空視窗

Requirement: 新增快捷鍵 `Ctrl+W` 關閉當前分頁；所有分頁都關閉時，留著空的視窗實例。

Test steps:
- Open multiple tabs and press `Ctrl+W`.
- Open one dirty/unsaved tab and press `Ctrl+W`.
- Close the final tab with `Ctrl+W`.

Pass criteria:
- `Ctrl+W` closes only the active tab.
- Unsaved-change prompt appears before closing dirty documents.
- After the last tab closes, exactly one main window remains open with zero document tabs.
- In the empty state, triggering File > Open or `Ctrl+O` opens a PDF into that same window.

Regression checks:
- Existing close buttons/menu actions share the same close-tab behavior.
- `Ctrl+W` does not close floating note editors or dialogs unless they intentionally handle focus first.

## AC-NEW-09 - 過去開啟檔案歷史紀錄

Requirement: 提供過去開啟過的檔案歷史紀錄。

Test steps:
- Open several PDFs from different folders.
- Restart the app.
- Inspect the recent/history UI.
- Open a recent file from history.
- Delete or move one recent file and attempt to open it from history.

Pass criteria:
- Recently opened files are persisted across app restarts.
- History order is most-recent-first and de-duplicates repeated opens.
- Missing files show a non-crashing message that includes the missing path and leave the history list visible.
- Missing-file entries can be removed by the user or are marked unavailable with a visible disabled state.
- History length is capped at a documented number of entries; the implementation report must state the cap.
- Paths under the app temp directory, print-spool temp directory, or unsaved/generated temporary files are not added to history.

Regression checks:
- Opening files through double-click, file dialog, drag/drop, and single-instance forwarding all update history consistently.
- Private temporary export/build paths are not accidentally recorded.
