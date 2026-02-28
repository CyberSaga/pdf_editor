# 功能清單

本文件以段落方式整理目前 PDF Editor 的實作能力，並對照目前 MVC 與 `model.tools` 解耦後的行為邊界。

## 0. 多分頁管理（Multi-Tab）

系統採用 session-based 模型，同一個應用程式可同時開啟多份 PDF。每個 session 都有自己的文件物件、頁碼與縮放狀態、Undo/Redo 歷史，以及待套用的編輯內容。Controller 以 active session 為唯一操作目標，分頁切換時會還原該 session 的檢視與搜尋狀態，並透過 `session_id + generation` 機制防止背景批次渲染覆寫到錯誤分頁。關鍵函式包含 `activate_session_by_index()`、`close_session(session_id)`、`on_tab_changed(index)`、`on_tab_close_requested(index)`、`_schedule_thumbnail_batch(...)`、`_schedule_scene_batch(...)`、`_schedule_index_batch(...)`。

## 1. 檔案操作

支援開啟 PDF、儲存與另存新檔。若開啟的路徑已存在於目前 session 集合，Controller 會直接切換到既有分頁而非重複載入。儲存流程會處理 redaction 後續清理，並在可行時採用增量寫回以降低 I/O 成本。對於受密碼保護文件，`open_pdf` 可接收密碼參數並完成驗證。關鍵函式包含 `open_pdf(path, password, append=True)`、`save_as(new_path)`、`save()`、`save_as(path)`。

## 2. 頁面操作

頁面層級功能包含刪除頁、旋轉頁、插入空白頁、由外部 PDF 插入指定頁，以及匯出頁面（PDF 或影像）。這些結構性操作由 `SnapshotCommand` 納入命令系統，因此可與其他可回復操作共同維持一致的 Undo/Redo 行為。關鍵函式包含 `delete_pages(pages)`、`rotate_pages(pages, degrees)`、`insert_blank_page(position)`、`insert_pages_from_file(source_file, source_pages, position)`、`export_pages(pages, output_path, as_image)`。

## 3. 列印與輸出快照

列印流程使用 `build_print_snapshot()` 產生可列印快照，再交由統一列印對話窗與 dispatcher 執行。頁碼選擇、紙張配置與縮放計算在預覽與實際輸出共用同一套邏輯，降低預覽與成品差異。列印子系統位於 `src/printing/`，以維持與編輯流程的邊界清晰。關鍵函式包含 `build_print_snapshot()`、`print_document()`、`print_dispatcher.print_pdf_file(...)`、`page_selection.resolve_page_indices(...)`、`dispatcher.resolve_page_indices_for_count(...)`、`PDFRenderer.iter_page_images(...)`。

## 4. 檢視與導航

檢視層支援縮圖、連續捲動、頁面跳轉、縮放與適應畫面。開檔時採「首頁優先」策略，先顯示低解析度首頁，再以批次方式載入縮圖與連續場景，最後建立文字索引，以縮短可互動等待時間。場景更新後會同步 `sceneRect` 到 `graphics_view`，確保捲軸與可視區域對應正確。關鍵函式包含 `_update_mode('browse')`、`change_scale(page_idx, scale)`、`_rebuild_continuous_scene()`、`set_thumbnail_placeholders(n)`、`display_all_pages_continuous(...)`、`append_pages_continuous(...)`。

## 5. 文字編輯

文字編輯採交易式流程，包含定位目標、redaction、回填與驗證，必要時自動回滾。定位支援 `target_mode=run|paragraph`，並可利用 `target_span_id` 進行精準鎖定，以避免重疊文字誤刪。系統也處理 CJK、垂直文字、換行與 ligature 正規化等情況，並以 char-level reconstruction 提升文字抽取穩定性。關鍵函式包含 `edit_text(page_num, rect, new_text, font, size, color, original_text, vertical_shift_left, new_rect=None, target_span_id=None, target_mode=None)`、`command_manager.execute(cmd)`、`command_manager.undo()`、`command_manager.redo()`、`EditTextCommand`、`SnapshotCommand`。

## 6. 搜尋

全文搜尋功能由 `model.tools.search.search_text(query)` 提供，回傳頁碼、文本與定位矩形。Controller 會保存每個 session 的搜尋 UI 狀態，並在使用者選取結果時跳轉至對應頁面與位置，維持跨分頁的一致體驗。關鍵函式包含 `search_text(query)`、`jump_to_result(page_num, rect)`、`model.tools.search.search_text(query)`。

## 7. 繪圖與註解

註解工具已由 `PDFModel` 解耦至 `model.tools.annotation`，目前支援螢光筆、矩形與 FreeText 註解，並可列出全文件註解與切換顯示/隱藏。文字編輯流程中，若 redaction 區域與既有註解重疊，系統會先暫存再還原重疊註解，避免註解資料意外遺失。關鍵函式包含 `model.tools.annotation.add_rect(...)`、`model.tools.annotation.add_highlight(...)`、`model.tools.annotation.add_annotation(...)`、`model.tools.annotation.get_all_annotations()`、`model.tools.annotation.toggle_annotations_visibility(visible)`、`model.tools.annotation.get_text_bounds(page_num, rough_rect)`、`model.tools.annotation._save_overlapping_annots(...)`、`model.tools.annotation._restore_annots(...)`。

## 8. 浮水印

浮水印邏輯由 `model.tools.watermark` 管理，支援新增、更新、刪除與列表。渲染時可套用於檢視、快照與列印路徑，儲存時會寫入內嵌 metadata，重新開啟文件後仍可還原為可編輯的浮水印項目。浮水印修改狀態由工具層按 session 追蹤，並參與 unsaved changes 判定。關鍵函式包含 `model.tools.watermark.add_watermark(...)`、`model.tools.watermark.get_watermarks()`、`model.tools.watermark.update_watermark(...)`、`model.tools.watermark.remove_watermark(...)`。

## 9. OCR 與其他功能

OCR 功能由 `model.tools.ocr.ocr_pages(pages)` 提供，執行依賴 `pytesseract` 與 `Pillow`，缺少套件或系統 Tesseract 引擎時會回傳明確錯誤訊息。其他常用能力包含單頁快照輸出，以及透過註解工具取得更精準的文字邊界，作為編輯前框選輔助。關鍵函式包含 `model.tools.ocr.ocr_pages(pages)`、`snapshot_page(page_idx)`、`get_page_pixmap(page_num, scale)`、`get_text_bounds(page_num, rough_rect)`。

## 10. 右側屬性面板（Inspector）

右側屬性面板會依當前模式動態切換設定內容。瀏覽模式顯示頁面資訊；矩形模式顯示顏色與透明度；螢光筆模式顯示顏色設定；文字編輯模式顯示字型、字級與垂直文字調整參數。View 負責維護這些 UI 設定，送出操作時再由 Controller 傳遞至 Model 或對應工具。

## 11. API 與責任邊界

工具型功能不再直接掛在 `PDFModel` 公開 API，而是統一從 `model.tools.<tool>.*` 進入。`PDFModel` 專注於 session、文件生命週期、核心編輯與儲存協調；`ToolManager` 負責工具生命週期與渲染/儲存掛勾；各工具類別則管理其專屬狀態與行為，避免模型層持續膨脹。
