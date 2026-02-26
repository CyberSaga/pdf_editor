# PDF 編輯器（PySide6 + PyMuPDF）

本專案是以 Python + Qt（PySide6）撰寫的桌面 PDF 編輯器，提供頁面管理、
註解、文字編輯（遮罩重寫）、浮水印、搜尋與可選的 OCR 功能。

此文件格式比照 `PDF4QT-README.md`。

## 2. 法律聲明

目前此專案未宣告授權條款。如需授權資訊，請新增 `LICENSE` 檔並更新本節。

## 3. 功能

主要功能如下：

- [x] 開啟/儲存 PDF（支援增量儲存）
- [x] 頁面操作（刪除/旋轉/匯出/插入/合併）
- [x] 文字編輯（遮罩 + 重插；保留既有註解）
- [x] 搜尋與跳轉
- [x] 註解（矩形/螢光/自由文字）與顯示切換
- [x] 浮水印（寫入 PDF 內部資料）
- [x] 列印流程（預覽/版面配置）
- [x] 選用 OCR（Tesseract）
- [x] Undo/Redo（指令系統）
- [x] 大 PDF：首頁快速顯示；縮圖與連續捲動於背景分批載入；場景載完後可捲動與點縮圖跳頁（索引於場景完成後再建）

詳細流程與責任分工請參考：
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`

## 4. 第三方函式庫

- PySide6（Qt UI）
- PyMuPDF（fitz）
- Pillow
- pytesseract（選用 OCR）

## 6. 安裝

### Windows（一般使用者）

若已有打包版本，下載後直接執行：

```
dist\main.exe
```

### Windows（開發環境）

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_clean.txt
```

### 選用列印後端

```
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

### OCR 依賴

若需 OCR，請先安裝 Tesseract OCR，並確保 `tesseract` 在 PATH 中。

## 7. 執行

```
python main.py
```

## 8. Windows 打包

打包說明（含 PyMuPDF/PyInstaller 的 workaround）請見：

- `docs/PACKAGING.md`

打包指令：

```
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

輸出：

```
dist\main.exe
```

## 9. 免責聲明

本軟體以「現況」提供，不包含任何明示或暗示擔保。
