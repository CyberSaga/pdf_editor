# 視覺化 PDF 編輯器 — 文件索引

本目錄為專案架構、功能說明與測試報告。

| 文件 | 說明 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 專案架構（MVC）、模組職責與資料流 |
| [FEATURES.md](FEATURES.md) | 功能清單與對應的 Model / Controller / View |

## 專案概覽

- **技術棧**：Python 3.9+、PySide6（Qt）、PyMuPDF（fitz）、Pillow、pytesseract（OCR 選用）
- **架構**：MVC（Model–View–Controller），訊號/槽連接 View 與 Controller
- **入口**：`main.py` 建立 `PDFModel`、`PDFView`、`PDFController` 並綁定
- **UI 佈局**：三欄式（左側欄 260px：縮圖/搜尋/註解/浮水印；中央畫布；右側屬性 280px）；頂部 Tab 工具列（檔案/常用/編輯/頁面/轉換）與右側固定區（頁碼、縮放、適應畫面、復原/重做）；詳見專案根目錄 `UI Specification.md`

## 依賴與安裝

```bash
pip install -r requirements.txt
# Printing Backends: Vary between different Platforms
pip install -r optional-requirements.txt
```

- OCR 功能需本機安裝 Tesseract；未安裝時 OCR 可能失敗，其餘功能不受影響。

## 快速導覽

- **啟動程式**：`python main.py`
- **核心模組**：`model/pdf_model.py`、`controller/pdf_controller.py`、`view/pdf_view.py`
- **輔助**：`model/text_block.py`（文字塊索引）、`model/edit_commands.py`（Undo/Redo）、`utils/helpers.py`（工具函式）

## 列印功能更新（2026-02）

- 列印流程已改為單一對話視窗，不再使用三段式 `QInputDialog`。
- 同一視窗內可完成設定：印表機、紙張、方向、雙面、彩色/黑白、PPI、份數、頁面範圍、奇偶頁、反向、縮放。
- 右側提供即時預覽（大預覽 + 頁碼清單 + 上下頁切換）。
- 預覽區支援滑鼠滾輪切頁：上滾上一頁、下滾下一頁。
- `PPI` 預設值為 `300`。
- 按鈕樣式：`列印` 白底、`取消` 灰底。

相關檔案：
- `src/printing/print_dialog.py`
- `src/printing/layout.py`
- `src/printing/page_selection.py`
- `controller/pdf_controller.py`

## 測試

- **功能與衝突**：`python test_scripts/test_feature_conflict.py`（使用 test_files 內 PDF）
- **深度壓力**：`python test_scripts/test_deep.py --quick`
- **全量三層**(1.能否正常開啟檔案、2.能否正確建立索引、3.能否編輯文字塊)：`python test_scripts/test_all_pdfs.py`（掃描 test_files 下所有 PDF）
