# PDF 編輯器（PySide6 + PyMuPDF）

這是一個以 Python + Qt 開發的桌面 PDF 編輯器。

主要能力：
- 開啟 / 儲存 PDF
- 頁面操作（刪除 / 旋轉 / 插入 / 匯出 / 合併）
- 文字編輯（重疊安全）
- 獨立新增文字模式（新增頁面文字）
- 註解（矩形 / 螢光 / 文字註解）
- 浮水印
- 搜尋與跳轉
- 可選 OCR
- Command-based Undo / Redo

## 授權

目前此倉庫尚未宣告授權條款。
若需要授權資訊，請新增 `LICENSE` 檔案。

## 功能文件

完整功能與流程行為請參考：
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`

修正決策、根因與解法紀錄請參考：
- `docs/solutions.md`

## 第三方套件

- PySide6
- PyMuPDF (fitz)
- Pillow
- pytesseract（選用）

## 安裝

### Windows（開發）

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_clean.txt
```

### 選用列印後端

```text
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

### OCR 依賴

若需 OCR，請安裝 Tesseract OCR，並確保 `tesseract` 在 PATH 中。

## 執行

```text
python main.py
```

## 快捷鍵

- `Ctrl+Z`：復原
- `Ctrl+Y`：重做
- `Ctrl+S`：存檔
- `Ctrl+Shift+S`：另存新檔
- `F2`：編輯文字模式
- `Esc`：優先關閉目前編輯框/對話框（保留工具模式）；若無編輯框且非瀏覽模式則切回瀏覽模式

未儲存變更的關閉提醒支援鍵盤操作：`Y` 儲存、`N` 放棄、`Esc` 取消。

## 測試腳本索引

`test_scripts/TEST_SCRIPTS.md` 是本專案的測試地圖，主要提供：
- 各腳本對應的品質面向（正確性、回歸風險、功能衝突、效能、列印、多分頁隔離）
- 各腳本覆蓋的工作流程（例如新增文字框原子性、重疊編輯、Undo/Redo 邊界、大檔行為）
- 哪些屬於快速 smoke 檢查，哪些屬於深度 / corpus / 壓力驗證
- 會產生報告或輸出檔的腳本與其產出位置
- 發生特定類型問題時，優先應查看哪一組測試

簡單說，它用來說明每支測試腳本的覆蓋範圍與診斷價值，而不只是執行方式。

## 打包（Windows）

```text
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

輸出：

```text
dist\main.exe
```

## 最近更新（2026-03）

- 新增獨立 `add_text` 模式，並提供原子化新增文字框 Undo/Redo。
- 新增旋轉安全的點擊定位（0/90/180/270）新增文字放置。
- 新增 CJK 預設字型策略（新增文字路徑）。
- 將「文字選取粒度」UI 預設改為 `paragraph`，並加上啟動同步。
- 新增工具黏著行為：矩形 / 螢光筆 / 註解操作後維持在原工具。
- 新增工具按鈕 checked 狀態與模式同步；`Esc` 採三段優先規則切換。

細節請見 `docs/FEATURES.md` 與 `docs/solutions.md`。

## 免責

本軟體以「現況」提供，不提供任何明示或默示保證。
