# 功能清單（依模組對照）

以下為目前視覺化 PDF 編輯器已實作之功能，並標註對應的 **Model**、**Controller**、**View** 實作位置。

---

## 0. 多分頁管理（Multi-Tab）

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **Session 註冊表** | `session_ids + sessions_by_id + active_session_id`，每個 session 持有獨立 doc/index/undo/pending_edits；浮水印等工具狀態由 `model.tools.*` 依 session 管理 | 以 active session 為唯一目標分派所有編輯與儲存操作 | 文件分頁列 `QTabBar` 顯示所有開啟檔案 |
| **切換分頁** | `activate_session_by_index()` | `on_tab_changed(index)`：切換 active session，恢復該分頁的頁碼/縮放/搜尋狀態，重新啟動分批載入 | 點選文件分頁列觸發 `sig_tab_changed` |
| **關閉分頁** | `close_session(session_id)` | `on_tab_close_requested(index)`：未儲存檢查（儲存/放棄/取消）後關閉，最後一頁關閉時重置空白 UI | 分頁關閉按鈕觸發 `sig_tab_close_requested` |
| **防 stale 批次載入** | 無（Controller 層保護） | `_schedule_thumbnail_batch/_schedule_scene_batch/_schedule_index_batch` 全部帶 `session_id + generation` 驗證 | 切換分頁後不會被舊分頁背景批次覆寫畫面 |

---

## 1. 檔案操作

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **開啟 PDF** | `open_pdf(path, password, append=True)`，已開啟路徑會 focus existing | `open_pdf(path)` | 頂部「檔案」→「開啟」→ 檔案對話框 → `sig_open_pdf` |
| **儲存** | `save_as(new_path)`（存回原檔時可 incremental） | `save()`（使用 `saved_path`） | 頂部「檔案」→「儲存」、快捷鍵 Ctrl+S → `sig_save` |
| **另存新檔** | `save_as(new_path)` | `save_as(path)` | 頂部「檔案」→「另存新檔」→ 檔案對話框 → `sig_save_as` |

- 密碼保護 PDF：`open_pdf` 支援 `password` 參數；必要時由 View/Controller 彈出密碼輸入。
- 儲存時會呼叫 `apply_pending_redactions()` 做 content stream 清理，並支援增量更新（存回原檔且支援時）。

---

## 2. 頁面操作

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **刪除頁** | `delete_pages(pages)` | `delete_pages(pages)`，結構性操作以 `SnapshotCommand` 記錄 | 頂部「頁面」→「刪除頁」→ 輸入頁碼 → `sig_delete_pages` |
| **旋轉頁** | `rotate_pages(pages, degrees)` | `rotate_pages`，以 `SnapshotCommand` 記錄 | 頂部「頁面」→「旋轉頁」或右鍵選單「旋轉頁面」→ `sig_rotate_pages` |
| **匯出頁** | `export_pages(pages, output_path, as_image)` | `export_pages(pages, path, as_image)` | 頂部「頁面」→「匯出頁」→ 選擇路徑與格式 → `sig_export_pages` |
| **插入空白頁** | `insert_blank_page(position)` | `insert_blank_page(position)`，以 `SnapshotCommand` 記錄 | 頂部「頁面」→「插入空白頁」→ 輸入位置 → `sig_insert_blank_page` |
| **從檔案插入頁** | `insert_pages_from_file(source_file, source_pages, position)` | `insert_pages_from_file(...)`，以 `SnapshotCommand` 記錄 | 頂部「頁面」→「從檔案插入頁」→ 選檔與頁碼 → `sig_insert_pages_from_file` |

---

## 3. 列印（單一視窗 + 右側預覽）

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **開啟列印視窗** | `build_print_snapshot()`（輸出可列印快照） | `print_document()` 建立快照、開啟 `UnifiedPrintDialog`、送出列印 | 頂部「檔案」→「列印」、快捷鍵 Ctrl+P |
| **列印參數設定** | `PrintJobOptions`（含 `paper_size`/`orientation`/`scale_mode` 等） | 讀取對話窗結果後呼叫 `print_dispatcher.print_pdf_file(...)` | 單一對話窗左側完成全部設定 |
| **頁碼解析（共用）** | `page_selection.resolve_page_indices(...)` | `dispatcher.resolve_page_indices_for_count/file(...)` | 預覽與實際列印共用同一頁碼結果 |
| **即時預覽** | `PDFRenderer.iter_page_images(...)` | 透過 dispatcher 提供頁面集合 | 右側大預覽 + 頁碼清單 + 上下頁切換 + 滾輪切頁 |
| **縮放/紙張一致性** | `layout.compute_target_draw_rect(...)` | `qt_bridge` 與預覽共用 layout 計算 | 降低「預覽與實際輸出」差異 |
| **視覺與預設** | 無 | 無 | `PPI` 預設 300；「列印」白底、「取消」灰底 |

---

## 4. 檢視與導航

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **縮圖** | 無（由 Controller 用 Model 取得頁面 pixmap） | 開檔：`set_thumbnail_placeholders(n)` 後以 QTimer 分批 `_schedule_thumbnail_batch`；結構變更後 `_update_thumbnails()`、`_rebuild_continuous_scene()` | 頂部「常用」→「縮圖」、左側縮圖分頁；點縮圖 → `sig_page_changed`；`update_thumbnail_batch(start_index, pixmaps)` 分批更新圖示 |
| **瀏覽模式** | 無 | `_update_mode('browse')` | 頂部「常用」→「瀏覽模式」→ `sig_mode_changed` |
| **縮放** | 無 | `change_scale(page_idx, scale)`：設定 `view.scale`，連續模式時 `_rebuild_continuous_scene` 所有頁面等齊重繪 | 右上角縮放選單（100% 等）→ `sig_scale_changed`；Ctrl+滾輪縮放後 debounce 觸發 `sig_request_rerender`；選單與狀態列會同步顯示當前比例 |
| **連續捲動** | 無 | 開檔：首頁以低解析度預覽後，QTimer 分批 `_schedule_scene_batch` 建立連續場景；場景載完後才啟動 `_schedule_index_batch`；結構變更後 `_rebuild_continuous_scene` | View：`display_all_pages_continuous` / `append_pages_continuous` 建立/追加頁面；**每次更新場景 rect 後呼叫 `graphics_view.setSceneRect(scene.sceneRect())`**，確保捲軸與可見區域對應整份文件，捲動與點縮圖跳頁可用 |
| **適應畫面** | 無 | 無 | 右上角「適應畫面」→ `fitInView` 目前頁面（連續模式不會縮到顯示全部頁） |

- **大 PDF 開檔效能**：開檔時先顯示首頁低解析度預覽（`FIRST_PAGE_PREVIEW_SCALE`），左側縮圖為佔位（頁 1…n），再以 QTimer 分批載入縮圖與連續場景（縮圖每批 10 頁、場景每批 3 頁），**文字塊索引延後至場景載完後**才分批建立，避免 main thread 長時間阻塞；使用者可較快開始操作，捲動與點縮圖跳頁在場景載入後即可使用；若點選的頁尚未載入則捲動至最後已載入頁。

---

## 5. 文字編輯

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **編輯文字** | `edit_text(page_num, rect, new_text, font, size, color, original_text, vertical_shift_left, new_rect=None, target_span_id=None, target_mode=None)`；內含 redaction + 三策略插入（htmlbox / 擴寬 / textbox）+ 驗證與索引更新 | 擷取頁面快照、建立 `EditTextCommand`（包含 `target_span_id` / `target_mode`）、`command_manager.execute(cmd)`、更新畫面與 Undo/Redo 狀態 | 頂部「編輯」→「編輯文字」、F2 → `edit_text` 模式；框選後彈出編輯器，送出 → `sig_edit_text`（含 `target_span_id` / `target_mode`） |
| **復原** | `command_manager.undo()` | `undo()`，依指令類型刷新畫布/縮圖 | 頂部「常用」或右上角「↺ 復原」、Ctrl+Z → `sig_undo` |
| **重做** | `command_manager.redo()` | `redo()`，同上 | 頂部「常用」或右上角「↻ 重做」、Ctrl+Y → `sig_redo` |

- 文字塊由 `TextBlockManager` 管理；編輯後只更新該 block，不重建整份索引。
- 垂直文字、CJK、自動換行、ligature 正規化等均在 Model 內處理。
- 編輯目標以 `target_span_id`（span-level identity）定位，避免重疊文字在同一位置/區域時被一起清除。
- 支援 `target_mode=run|paragraph` 的混合定位：`run` 偏向精準；`paragraph` 偏向整段一起重排（避免把單字切成多個 textbox）。
- 文字抽取採用 rawdict 的 char-level reconstruction（以字元重建 runs/paragraph），降低「young 被拆成 y / oung」等不合理分割。
- 若目標與其他文字重疊：會建立 overlap cluster，對 cluster 做 redaction，並重播（replay）非目標文字；若驗證失敗會以 page snapshot 回滾。

---

## 6. 搜尋

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **搜尋文字** | `model.tools.search.search_text(query)` 回傳 `List[Tuple[page_num, text, rect]]`（僅作用於 active session） | `search_text(query)`，將結果交給 View 顯示並寫回該 session 的搜尋 UI state | 頂部「常用」→「搜尋」或 Ctrl+F → 左側「搜尋」分頁；輸入後 `sig_search`，結果列表點擊 → `sig_jump_to_result`；Esc 關閉搜尋 |
| **跳至結果** | 無 | `jump_to_result(page_num, rect)`：換頁並在畫布上高亮該矩形 | View 接收並顯示對應頁與高亮 |

---

## 7. 繪圖與註解

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **矩形** | `model.tools.annotation.add_rect(page_num, rect, color, fill)` | `add_rect`，以 `SnapshotCommand` 記錄 | 頂部「編輯」→「矩形」→ `rect` 模式；右側「屬性」→ 矩形設定（顏色、透明度）→ 拖曳繪製後 `sig_add_rect` |
| **螢光筆** | `model.tools.annotation.add_highlight(page_num, rect, color)` | `add_highlight`，以 `SnapshotCommand` 記錄 | 頂部「編輯」→「螢光筆」→ `highlight` 模式；右側螢光筆顏色 → 拖曳後 `sig_add_highlight` |
| **新增註解（FreeText）** | `model.tools.annotation.add_annotation(page_num, point, text)` 回傳 xref | `add_annotation(page_idx, doc_point, text)`，以 `SnapshotCommand` 記錄 | 頂部「編輯」→「新增註解」→ `add_annotation` 模式；點擊頁面後輸入文字 → `sig_add_annotation` |
| **註解列表** | `model.tools.annotation.get_all_annotations()` | `load_annotations()` 取得列表並交給 View | 頂部「編輯」→「註解列表」或左側「註解列表」分頁；點選一筆 → `sig_jump_to_annotation` |
| **顯示/隱藏註解** | `model.tools.annotation.toggle_annotations_visibility(visible)` | `toggle_annotations_visibility(visible)` | 工具列「顯示/隱藏註解」勾選 → `sig_toggle_annotations_visibility` |

- 編輯文字時會保留與 redact 區域重疊的 FreeText/Highlight 等註解（`model.tools.annotation` 內 `_save_overlapping_annots` / `_restore_annots`）。

---

## 8. 浮水印

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **添加浮水印** | 由 `model.tools.watermark.add_watermark(...)` 寫入工具狀態（儲存時繪入 PDF 並寫入元數據） | `add_watermark(pages, text, angle, opacity, font_size, color, font, ...)` | 頂部「編輯」→「添加浮水印」→ 浮水印對話框（文字、頁面、角度、透明度、字級、顏色、字型、偏移、行距）→ `sig_add_watermark` |
| **浮水印列表** | `model.tools.watermark.get_watermarks()` | `load_watermarks()` 提供給 View | 頂部「編輯」→「浮水印列表」或左側「浮水印列表」分頁；編輯/刪除 → `sig_update_watermark` / `sig_remove_watermark` |

- **持久化**：儲存時將浮水印元數據寫入 PDF 內嵌檔案（`__pdf_editor_watermarks`），開檔時由 `model.tools.watermark` 還原，重新開檔後仍可編輯/刪除浮水印。

---

## 9. 其他功能

| 功能 | Model | Controller | View（觸發/顯示） |
|------|-------|------------|-------------------|
| **OCR** | `model.tools.ocr.ocr_pages(pages)`（pytesseract + PIL） | `ocr_pages(pages)` | 頂部「轉換」→「OCR（文字辨識）」→ 選擇頁碼 → `sig_ocr` |
| **快照** | 單頁匯出為影像（如 PNG） | `snapshot_page(page_idx)` 存檔 | 頂部「常用」→「快照」→ `sig_snapshot_page` |
| **取得精準文字邊界** | `model.tools.annotation.get_text_bounds(page_num, rough_rect)` | `get_text_bounds(page, rough_rect)` | Controller 在需要時呼叫（例如編輯前輔助框選） |
| **取得頁面 Pixmap** | `get_page_pixmap(page_num, scale)`、縮圖用低解析度 | Controller 用於顯示當前頁與縮圖 | View 透過 Controller 或直接由 Model 取得 pixmap 並轉為 QPixmap 顯示 |

---

## 10. 右側「屬性」面板（動態 Inspector）

右側為 280px 寬的「屬性」面板（QStackedWidget），依目前模式切換內容：

| 模式 | 顯示區塊 | 項目 |
|------|----------|------|
| 無選取/瀏覽 | 頁面資訊 | 尺寸、旋轉等 |
| 矩形 | 矩形設定 | 顏色（預設 #0078D4）、透明度 0–1、套用/取消 |
| 螢光筆 | 螢光筆顏色 | 色塊（預設 #FFFF00） |
| 編輯文字 | 文字設定 | 字型（Source Han Serif TC）、字級（pt）、垂直文字擴展時左移、套用/取消 |

以上設定在 View 中維護，並在送出 `sig_edit_text` / `sig_add_rect` / `sig_add_highlight` 時一併傳給 Controller/Model。註解列表與浮水印列表已移至左側欄分頁。

---

## 11. 小結

- **檔案與頁面**：開啟、儲存、另存、刪除頁、旋轉頁、匯出頁、插入空白頁、從檔案插入頁。
- **檢視**：縮圖（開檔時佔位後分批載入）、瀏覽、縮放、連續捲動（開檔時首頁預覽後分批載入場景，場景與 view rect 同步以支援捲動與縮圖跳頁；索引延後至場景載完）。
- **文字**：編輯文字（含 Undo/Redo）、搜尋與跳轉。
- **繪圖與註解**：矩形、螢光筆、FreeText 註解、註解列表、顯示/隱藏註解。
- **浮水印**：添加、列表、編輯、刪除。
- **其他**：OCR、快照。

所有會改變文件內容的操作，凡支援復原者，皆透過 `edit_commands` 的 Command 與 `CommandManager` 統一 Undo/Redo。

---


