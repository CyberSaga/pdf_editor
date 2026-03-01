# PDF 編輯器（PySide6 + PyMuPDF）

這是一個以 Python + Qt 開發的桌面 PDF 編輯器。

## 主要能力

- 開啟與儲存 PDF
- 頁面操作：刪除、旋轉、插入、匯出、合併
- 重疊安全的文字編輯
- 獨立新增文字模式
- 文字屬性可用 `套用/取消` 明確提交或捨棄，且字體/字級選單不會誤關閉編輯框
- 擴充 CJK 字體選項，支援 `Microsoft JhengHei`、`PMingLiU`、`DFKai-SB`（可用時嵌入字型）
- 註解：矩形、螢光、文字註解
- 浮水印
- 搜尋與跳轉
- 可選 OCR
- 透過命令歷史支援 Undo/Redo

## 文件地圖

- 功能行為：`docs/FEATURES.md`
- 架構與邊界：`docs/ARCHITECTURE.md`
- 問題歷程與修正：`docs/solutions.md`
- 測試腳本索引：`test_scripts/TEST_SCRIPTS.md`

## 環境需求

- Python 3.10+
- Windows（主要開發環境）

本專案使用的第三方套件：
- PySide6
- PyMuPDF (`fitz`)
- Pillow
- pytesseract（選用）

## 安裝

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

選用相依套件：

```text
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

OCR 說明：請安裝 Tesseract OCR，並確保 `tesseract` 可由 PATH 找到。

## 執行

```text
python main.py
```

## 打包（Windows）

```text
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

輸出：

```text
dist\main.exe
```

## 快捷鍵

- `Ctrl+O`：開啟 PDF
- `Ctrl+P`：開啟列印對話框
- `Ctrl+Z`：復原
- `Ctrl+Y`：重做
- `Ctrl+S`：存檔
- `Ctrl+Shift+S`：另存新檔
- `F2`：進入文字編輯模式
- `Esc`：優先關閉目前編輯框/對話框；若無且非瀏覽模式則切回瀏覽模式

未儲存變更的關閉提醒支援：
- `Y`：儲存
- `N`：放棄
- `Esc`：取消

## 授權

目前此倉庫尚未宣告授權條款。
若需要授權資訊，請新增 `LICENSE` 檔案。

## 免責

本軟體以「現況」提供，不提供任何明示或默示保證。
