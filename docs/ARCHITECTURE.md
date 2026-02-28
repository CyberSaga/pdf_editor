# 專案架構（MVC）

## 1. 整體架構

本專案採用 **Model–View–Controller（MVC）** 模式，職責分離如下：

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│   model = PDFModel()   view = PDFView()   controller = PDFController(model, view) │
│   view.controller = controller   view.show()                     │
└─────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐           ┌───────────────┐           ┌───────────────┐
│     Model     │           │  Controller   │           │     View     │
│ (pdf_model.py)│◄──────────│(pdf_controller│──────────►│ (pdf_view.py)│
│               │  呼叫 API  │     .py)      │  訊號/槽   │               │
│ • PDF 資料    │           │ • 協調 M/V    │           │ • 工具列/面板 │
│ • 文字塊索引  │           │ • 業務流程    │           │ • 畫布/縮圖   │
│ • Undo/Redo   │           │ • 錯誤處理    │           │ • 設定/對話框 │
└───────────────┘           └───────────────┘           └───────────────┘
        │                           │                           │
        │                   ┌───────┴───────┐                   │
        │                   │ edit_commands │                   │
        └──────────────────►│ (Command 模式) │◄──────────────────┘
                            │ EditTextCommand, SnapshotCommand, CommandManager
                            └───────────────┘
```

- **Model**：採用多分頁 Session Registry（`session_ids + sessions_by_id`），每個分頁封裝 `fitz.Document`、`TextBlockManager`、`CommandManager`、`pending_edits`；工具功能由 `model.tools.ToolManager` 內建擴充（annotation / watermark / search / ocr）提供，Model 核心僅保留文件/會話/編輯/存檔協調。
- **View**：除了既有工具列與主畫布，新增「文件分頁列（QTabBar）」；View 僅發出 `sig_tab_changed/sig_tab_close_requested`，不直接操作 Model 的 session registry。連續模式仍需同步 `graphics_view.setSceneRect` 與場景 rect。
- **Controller**：負責多分頁生命週期（開啟/切換/關閉）與每個 session 的 UI 狀態恢復（頁碼、縮放、搜尋狀態）；開檔與切換皆採首頁預覽 → 分批縮圖/場景 → 分批索引，且所有批次載入都帶 `session_id + generation` 防止跨分頁汙染。

## 2. 模組職責

### 2.1 Model 層

| 檔案 | 職責 |
|------|------|
| `model/pdf_model.py` | 多分頁 Session 管理（open/activate/close/list）、PDF 開檔/存檔、文字編輯（edit_text）、頁面操作（刪除/旋轉/插入）、快照與還原；透過 `tools` 管理器協調工具擴充 |
| `model/text_block.py` | `TextBlock` 資料結構、`TextBlockManager` 建立與維護頁面文字塊索引（build_index、find_by_rect、update_block、rebuild_page） |
| `model/edit_commands.py` | Command 模式：`EditCommand` 抽象、`EditTextCommand`（頁面快照 undo/redo）、`SnapshotCommand`（整份文件快照）、`CommandManager`（undo/redo 堆疊） |
| `model/tools/*.py` | 內建工具擴充：`annotation_tool`（註解/框選輔助）、`watermark_tool`（浮水印狀態/疊加/持久化）、`search_tool`（搜尋）、`ocr_tool`（OCR）；`manager.py` 提供生命周期與渲染/存檔掛鉤 |

### 2.2 Controller 層

| 檔案 | 職責 |
|------|------|
| `controller/pdf_controller.py` | 連接 View 訊號與 Model 方法；處理多分頁開檔/切換/關閉、儲存/另存、刪除頁/旋轉頁/匯出頁、插入空白頁/從檔案插入頁、編輯文字、搜尋/跳轉、OCR、Undo/Redo、註解、浮水印、快照、顯示模式切換與縮圖/場景重建；批次載入採 `session_id + generation` 驗證避免 stale update。 |

### 2.3 View 層

| 檔案 | 職責 |
|------|------|
| `view/pdf_view.py` | 主視窗（QMainWindow，最小 1280×800，標題「視覺化 PDF 編輯器」）；頂部工具列（QTabWidget：檔案/常用/編輯/頁面/轉換，各分頁內 QToolBar）+ 文件分頁列（QTabBar，可切換/關閉）；中央 QSplitter（左 260px 左側欄 QTabWidget：縮圖/搜尋/註解列表/浮水印列表、中央 QGraphicsView 連續捲動畫布、右 280px「屬性」QStackedWidget）；底部 QStatusBar；搜尋 Ctrl+F、Esc 關閉搜尋；右鍵選單；連續模式時 `display_all_pages_continuous` / `append_pages_continuous` 建立/追加頁面後會呼叫 `graphics_view.setSceneRect(scene.sceneRect())`。 |

### 2.4 工具層

| 檔案 | 職責 |
|------|------|
| `utils/helpers.py` | `parse_pages`（頁碼字串解析）、`pixmap_to_qpixmap`（fitz.Pixmap→QPixmap）、`show_error`、`choose_color` |

### 2.5 列印子系統（Printing）

| 檔案 | 職責 |
|------|------|
| `src/printing/print_dialog.py` | 統一列印視窗（左側設定 + 右側預覽），包含頁碼清單、上下頁、滾輪切頁與按鈕樣式。 |
| `src/printing/dispatcher.py` | 跨平台列印調度；提供 `resolve_page_indices_for_count()` / `resolve_page_indices_for_file()`。 |
| `src/printing/page_selection.py` | 共用頁碼計算：`page_ranges + page_subset + reverse_order`。 |
| `src/printing/layout.py` | 共用紙張/方向/縮放定位計算，供預覽與列印共用。 |
| `src/printing/qt_bridge.py` | 將渲染頁面輸出到 `QPrinter`，套用紙張、方向、縮放。 |

列印流程（2026-02 重構）：
1. `controller/pdf_controller.py::print_document()` 先由 model 產生可列印快照。
2. 開啟 `UnifiedPrintDialog`，收集使用者設定與最終頁碼。
3. `PrintDispatcher` 依平台驅動送印；必要時 fallback 到 Qt raster 路徑。
4. 預覽與實際列印共用 `page_selection.py`、`layout.py`，避免結果漂移。

## 3. 資料流（以「編輯文字」為例）

1. 使用者點擊工具列「編輯文字」→ View 切換為 `edit_text` 模式。
2. 使用者在畫布上框選文字區域 → View 取得場景座標，換算成 PDF 座標；同時做 hit-test 取得 `TextHit`（包含 `target_span_id` 與建議 `target_mode`），透過 `sig_edit_text` 送出（page, rect, new_text, font, size, color, original_text, vertical_shift_left, new_rect, target_span_id, target_mode 等）。
3. Controller 收到 `sig_edit_text`：
   - 呼叫 `model._capture_page_snapshot(page_idx)` 擷取頁面快照；
   - 建立 `EditTextCommand`（包含 `target_span_id` / `target_mode`），再呼叫 `model.command_manager.execute(cmd)`；
   - `EditTextCommand.execute()` 內部呼叫 `model.edit_text(...)` 完成 redaction + 插入新文字 + 更新索引；
   - 呼叫 `show_page(page_idx)` 更新畫面並更新 Undo/Redo 按鈕狀態。
4. 若使用者點「復原」→ View 發出 `sig_undo` → Controller 呼叫 `model.command_manager.undo()`，再依指令類型刷新畫布/縮圖。

- `target_span_id` 是 span-level 的穩定識別（格式：`p{page}_b{block}_l{line}_s{span}`），用來避免「同一位置重疊文字」在編輯時被一起清除。
- `target_mode` 用於控制定位/編輯粒度（`run` 或 `paragraph`）；其中 runs/paragraph 由 rawdict 的 char-level reconstruction 建立，降低不合理切分造成的誤選與誤刪。
- `model.edit_text(...)` 會以 `target_span_id` 優先定位目標，建立重疊 cluster，對 cluster 做 redaction，並重播（replay）非目標的 protected spans；若驗證失敗則用 page snapshot 回滾，避免破壞原頁面內容。

## 4. 依賴關係

- **Model** 僅依賴：`fitz`、`text_block`、`edit_commands`、`model.tools`，以及標準庫；OCR 相關第三方依賴由 `ocr_tool` 延遲載入，**不依賴 View 或 Controller**。
- **Controller** 依賴 Model 與 View 的介面（訊號與公開方法），不直接操作 Qt 元件內部。
- **View** 依賴 PySide6 與 `utils.helpers`，透過 `controller` 引用呼叫少數 Controller 方法（若需由 View 主動觸發的邏輯），主要單向透過 Signal 通知 Controller。

此架構利於單元測試（Model 可獨立測試）、替換 UI（View 可重寫而保持訊號契約）以及維護業務邏輯集中於 Controller 與 Model。

