# PDF 編輯器（PySide6 + PyMuPDF）

以 Python + Qt（PySide6）撰寫的桌面 PDF 編輯器，提供頁面管理、註解、文字編輯
（redaction + 重新插入）、浮水印、搜尋與可選的 OCR 功能。

本文件參考 `PDF4QT-README.md` 的章節結構。

## 2. 法律與授權

此專案目前未宣告授權條款。若需要授權資訊，請新增 `LICENSE` 並更新本節。

## 3. 功能

- [x] 開啟 / 儲存 PDF（支援存回原檔的 incremental save）
- [x] 頁面操作（刪除 / 旋轉 / 匯出 / 插入空白頁 / 從其他 PDF 插入頁面）
- [x] 文字編輯（Overlap-safe：重疊範圍 redaction + replay；支援 run/段落 粒度；保留既有註解）
- [x] 搜尋並跳轉到結果
- [x] 註解（方框 / 螢光筆 / FreeText）與顯示切換
- [x] 浮水印（內嵌於 PDF，重新開啟仍可編輯）
- [x] 列印管線（預覽 / 版面配置）
- [x] 可選 OCR（Tesseract）
- [x] Undo / Redo（Command 系統）
- [x] 大型 PDF：優先顯示第一頁，縮圖與連續捲動背景載入

更詳細的流程與責任分工請見：
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`

## 4. 第三方套件

- PySide6（Qt UI）
- PyMuPDF（fitz）
- Pillow
- pytesseract（選用 OCR）

## 6. 安裝

### Windows（一般使用者）

若使用打包版本：

```text
dist\main.exe
```

### Windows（開發）

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_clean.txt
```

### 可選列印後端

```text
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

### OCR 依賴

若要使用 OCR，請先安裝 Tesseract OCR，並確認 `tesseract` 已加入 PATH。

## 7. 執行

```text
python main.py
```

## 8. 打包（Windows）

打包注意事項（含 PyMuPDF / PyInstaller workaround）請見：

- `docs/PACKAGING.md`

打包指令：

```text
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

輸出：

```text
dist\main.exe
```

## 9. 免責聲明

本軟體以「現狀」提供，不提供任何形式的保證。

## 10. 架構更新（2026-02）

- 工具功能已從 `PDFModel` 拆分為內建擴充，位於 `model/tools/`。
- 目前內建工具：`annotation`、`watermark`、`search`、`ocr`。
- 呼叫方式已改為 `model.tools.<tool>.*`（例如：`model.tools.search.search_text(...)`）。
- OCR 仍為選用功能；缺少依賴時會回傳明確錯誤訊息。
