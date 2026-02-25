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

- **Model**：持有 PDF 文件（`fitz.Document`）、文字塊索引（`TextBlockManager`）、編輯歷史（`CommandManager`），不依賴 UI。
- **View**：負責所有 UI（工具列、縮圖、主畫布、右側繪製設定、對話框），透過 **Qt Signal** 把使用者操作往外送。
- **Controller**：訂閱 View 的訊號，呼叫 Model API，再驅動 View 更新（例如換頁、重繪、更新 Undo/Redo 按鈕狀態）。

## 2. 模組職責

### 2.1 Model 層

| 檔案 | 職責 |
|------|------|
| `model/pdf_model.py` | PDF 開檔/存檔、文字編輯（edit_text）、頁面操作（刪除/旋轉/插入）、註解/螢光筆/矩形、搜尋、OCR、浮水印、快照與還原 |
| `model/text_block.py` | `TextBlock` 資料結構、`TextBlockManager` 建立與維護頁面文字塊索引（build_index、find_by_rect、update_block、rebuild_page） |
| `model/edit_commands.py` | Command 模式：`EditCommand` 抽象、`EditTextCommand`（頁面快照 undo/redo）、`SnapshotCommand`（整份文件快照）、`CommandManager`（undo/redo 堆疊） |

### 2.2 Controller 層

| 檔案 | 職責 |
|------|------|
| `controller/pdf_controller.py` | 連接 View 訊號與 Model 方法；處理開檔/儲存/另存、刪除頁/旋轉頁/匯出頁、插入空白頁/從檔案插入頁、編輯文字、搜尋/跳轉、OCR、Undo/Redo、註解、浮水印、快照、顯示模式切換與縮圖/場景重建 |

### 2.3 View 層

| 檔案 | 職責 |
|------|------|
| `view/pdf_view.py` | 主視窗（QMainWindow，最小 1280×800，標題「視覺化 PDF 編輯器」）；頂部工具列（QTabWidget：檔案/常用/編輯/頁面/轉換，各分頁內 QToolBar；右側固定區：頁 X/Y、縮放選單、適應畫面、↺復原/↻重做）；中央 QSplitter（左 260px 左側欄 QTabWidget：縮圖/搜尋/註解列表/浮水印列表、中央 QGraphicsView 連續捲動畫布、右 280px「屬性」QStackedWidget 依模式顯示頁面資訊/矩形設定/螢光筆顏色/文字設定）；底部 QStatusBar；搜尋 Ctrl+F、Esc 關閉搜尋；右鍵選單；發出各類 Signal 給 Controller |

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
2. 使用者在畫布上框選文字區域 → View 取得場景座標，換算成 PDF 座標，透過 `sig_edit_text` 送出（page, rect, new_text, font, size, color, original_text 等）。
3. Controller 收到 `sig_edit_text`：
   - 呼叫 `model._capture_page_snapshot(page_idx)` 擷取頁面快照；
   - 建立 `EditTextCommand`，再呼叫 `model.command_manager.execute(cmd)`；
   - `EditTextCommand.execute()` 內部呼叫 `model.edit_text(...)` 完成 redaction + 插入新文字 + 更新索引；
   - 呼叫 `show_page(page_idx)` 更新畫面並更新 Undo/Redo 按鈕狀態。
4. 若使用者點「復原」→ View 發出 `sig_undo` → Controller 呼叫 `model.command_manager.undo()`，再依指令類型刷新畫布/縮圖。

## 4. 依賴關係

- **Model** 僅依賴：`fitz`、`text_block`、`edit_commands`，以及標準庫 / pytesseract / PIL 等，**不依賴 View 或 Controller**。
- **Controller** 依賴 Model 與 View 的介面（訊號與公開方法），不直接操作 Qt 元件內部。
- **View** 依賴 PySide6 與 `utils.helpers`，透過 `controller` 引用呼叫少數 Controller 方法（若需由 View 主動觸發的邏輯），主要單向透過 Signal 通知 Controller。

此架構利於單元測試（Model 可獨立測試）、替換 UI（View 可重寫而保持訊號契約）以及維護業務邏輯集中於 Controller 與 Model。

