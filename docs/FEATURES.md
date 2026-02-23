# 功能清單（依模組對照）

以下為目前視覺化 PDF 編輯器已實作之功能，並標註對應的 **Model**、**Controller**、**View** 實作位置。

---

## 1. 檔案操作

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **開啟 PDF** | `open_pdf(path, password)` | `open_pdf(path)` | 工具列「開啟」→ 檔案對話框 → `sig_open_pdf` |
| **儲存** | `save_as(new_path)`（存回原檔時可 incremental） | `save()`（使用 `saved_path`） | 工具列「儲存」、快捷鍵 Ctrl+S → `sig_save` |
| **另存新檔** | `save_as(new_path)` | `save_as(path)` | 工具列「另存」→ 檔案對話框 → `sig_save_as` |

- 密碼保護 PDF：`open_pdf` 支援 `password` 參數；必要時由 View/Controller 彈出密碼輸入。
- 儲存時會呼叫 `apply_pending_redactions()` 做 content stream 清理，並支援增量更新（存回原檔且支援時）。

---

## 2. 頁面操作

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **刪除頁** | `delete_pages(pages)` | `delete_pages(pages)`，結構性操作以 `SnapshotCommand` 記錄 | 工具列「刪除頁」→ 輸入頁碼 → `sig_delete_pages` |
| **旋轉頁** | `rotate_pages(pages, degrees)` | `rotate_pages`，以 `SnapshotCommand` 記錄 | 工具列「旋轉頁」或右鍵選單「旋轉頁面」→ `sig_rotate_pages` |
| **匯出頁** | `export_pages(pages, output_path, as_image)` | `export_pages(pages, path, as_image)` | 工具列「匯出頁」→ 選擇路徑與格式 → `sig_export_pages` |
| **插入空白頁** | `insert_blank_page(position)` | `insert_blank_page(position)`，以 `SnapshotCommand` 記錄 | 工具列「插入空白頁」→ 輸入位置 → `sig_insert_blank_page` |
| **從檔案插入頁** | `insert_pages_from_file(source_file, source_pages, position)` | `insert_pages_from_file(...)`，以 `SnapshotCommand` 記錄 | 工具列「從檔案插入頁」→ 選檔與頁碼 → `sig_insert_pages_from_file` |

---

## 3. 檢視與導航

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **縮圖** | 無（由 Controller 用 Model 取得頁面 pixmap） | `_update_thumbnails()`、`_rebuild_continuous_scene()` | 工具列「縮圖」、左側縮圖面板；點縮圖 → `sig_page_changed` |
| **瀏覽模式** | 無 | `_update_mode('browse')` | 工具列「瀏覽」→ `sig_mode_changed` |
| **縮放** | 無 | `change_scale(page_idx, scale)` | 主畫布縮放 → `sig_scale_changed` |
| **連續捲動** | 無 | 依目前頁與 scale 重建場景 | View 管理 `QGraphicsView` 與 `QGraphicsScene`，捲動時可請求重繪 |

---

## 4. 文字編輯

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **編輯文字** | `edit_text(page_num, rect, new_text, font, size, color, original_text, vertical_shift_left)`；內含 redaction + 三策略插入（htmlbox / 擴寬 / textbox）+ 驗證與索引更新 | 擷取頁面快照、建立 `EditTextCommand`、`command_manager.execute(cmd)`、更新畫面與 Undo/Redo 狀態 | 工具列「編輯文字」、F2 → `edit_text` 模式；框選後彈出編輯器，送出 → `sig_edit_text` |
| **復原** | `command_manager.undo()` | `undo()`，依指令類型刷新畫布/縮圖 | 工具列「復原」、Ctrl+Z → `sig_undo` |
| **重做** | `command_manager.redo()` | `redo()`，同上 | 工具列「重做」、Ctrl+Y → `sig_redo` |

- 文字塊由 `TextBlockManager` 管理；編輯後只更新該 block，不重建整份索引。
- 垂直文字、CJK、自動換行、ligature 正規化等均在 Model 內處理。

---

## 5. 搜尋

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **搜尋文字** | `search_text(query)` 回傳 `List[Tuple[page_num, text, rect]]` | `search_text(query)`，將結果交給 View 顯示 | 工具列「搜尋」、Ctrl+F → 搜尋面板；輸入後 `sig_search`，結果列表點擊 → `sig_jump_to_result` |
| **跳至結果** | 無 | `jump_to_result(page_num, rect)`：換頁並在畫布上高亮該矩形 | View 接收並顯示對應頁與高亮 |

---

## 6. 繪圖與註解

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **矩形** | `add_rect(page_num, rect, color, fill)` | `add_rect`，以 `SnapshotCommand` 記錄 | 工具列「矩形」→ `rect` 模式；右側「繪製設定」：矩形顏色、透明度 → 拖曳繪製後 `sig_add_rect` |
| **螢光筆** | `add_highlight(page_num, rect, color)` | `add_highlight`，以 `SnapshotCommand` 記錄 | 工具列「螢光筆」→ `highlight` 模式；右側螢光筆顏色 → 拖曳後 `sig_add_highlight` |
| **新增註解（FreeText）** | `add_annotation(page_num, point, text)` 回傳 xref | `add_annotation(page_idx, doc_point, text)`，以 `SnapshotCommand` 記錄 | 工具列「新增註解」→ `add_annotation` 模式；點擊頁面後輸入文字 → `sig_add_annotation` |
| **註解列表** | `get_all_annotations()` | `load_annotations()` 取得列表並交給 View | 工具列「註解列表」→ 顯示註解面板；點選一筆 → `sig_jump_to_annotation` |
| **顯示/隱藏註解** | 無（或由 View 控制繪製時是否畫註解） | `toggle_annotations_visibility(visible)` | 工具列「顯示/隱藏註解」勾選 → `sig_toggle_annotations_visibility` |

- 編輯文字時會保留與 redact 區域重疊的 FreeText/Highlight 等註解（Model 內 `_save_overlapping_annots` / `_restore_annots`）。

---

## 7. 浮水印

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **添加浮水印** | 浮水印參數加入 `watermark_list`（儲存時繪入 PDF 並寫入元數據） | `add_watermark(pages, text, angle, opacity, font_size, color, font, ...)` | 工具列「添加浮水印」→ 浮水印對話框（文字、頁面、角度、透明度、字級、顏色、字型、偏移、行距）→ `sig_add_watermark` |
| **浮水印列表** | `watermark_list`、`get_watermarks()` | `load_watermarks()` 提供給 View | 工具列「浮水印列表」→ 列表面板；編輯/刪除 → `sig_update_watermark` / `sig_remove_watermark` |

- **持久化**：儲存時將浮水印元數據寫入 PDF 內嵌檔案（`__pdf_editor_watermarks`），開檔時還原 `watermark_list`，重新開檔後仍可編輯/刪除浮水印。見 `pdf_model._load_watermarks_from_doc`、`_write_watermarks_embed`。

---

## 8. 其他功能

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **OCR** | `ocr_pages(pages)`（pytesseract + PIL） | `ocr_pages(pages)` | 工具列「OCR」→ 選擇頁碼 → `sig_ocr` |
| **快照** | 單頁匯出為影像（如 PNG） | `snapshot_page(page_idx)` 存檔 | 工具列「快照」→ `sig_snapshot_page` |
| **取得精準文字邊界** | `get_text_bounds(page_num, rough_rect)` | `get_text_bounds(page, rough_rect)` | Controller 在需要時呼叫（例如編輯前輔助框選） |
| **取得頁面 Pixmap** | `get_page_pixmap(page_num, scale)`、縮圖用低解析度 | Controller 用於顯示當前頁與縮圖 | View 透過 Controller 或直接由 Model 取得 pixmap 並轉為 QPixmap 顯示 |

---

## 9. 右側「繪製設定」面板

| 項目 | 說明 | 使用時機 |
|------|------|----------|
| 矩形顏色 | 矩形外框/填滿顏色 | 矩形模式 |
| 矩形透明度 | 矩形透明度 0–1 | 矩形模式 |
| 螢光筆顏色 | 螢光筆顏色 | 螢光筆模式 |
| 字型 | 字型選擇（如 Source Han Serif TC） | 編輯文字模式 |
| 字級大小 | 字級（如 12） | 編輯文字模式 |
| 垂直文字擴展時左移 | 勾選後垂直文字向左擴展 | 編輯文字模式 |

以上設定在 View 中維護，並在送出 `sig_edit_text` / `sig_add_rect` / `sig_add_highlight` 時一併傳給 Controller/Model。

---

## 10. 小結

- **檔案與頁面**：開啟、儲存、另存、刪除頁、旋轉頁、匯出頁、插入空白頁、從檔案插入頁。
- **檢視**：縮圖、瀏覽、縮放、連續捲動。
- **文字**：編輯文字（含 Undo/Redo）、搜尋與跳轉。
- **繪圖與註解**：矩形、螢光筆、FreeText 註解、註解列表、顯示/隱藏註解。
- **浮水印**：添加、列表、編輯、刪除。
- **其他**：OCR、快照。

所有會改變文件內容的操作，凡支援復原者，皆透過 `edit_commands` 的 Command 與 `CommandManager` 統一 Undo/Redo。
