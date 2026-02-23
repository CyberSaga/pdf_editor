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

## 依賴與安裝

```bash
pip install -r requirements.txt
```

- OCR 功能需本機安裝 Tesseract；未安裝時 OCR 可能失敗，其餘功能不受影響。

## 快速導覽

- **啟動程式**：`python main.py`
- **核心模組**：`model/pdf_model.py`、`controller/pdf_controller.py`、`view/pdf_view.py`
- **輔助**：`model/text_block.py`（文字塊索引）、`model/edit_commands.py`（Undo/Redo）、`utils/helpers.py`（工具函式）

## 測試

- **功能與衝突**：`python test_scripts/test_feature_conflict.py`（使用 test_files 內 PDF）
- **深度壓力**：`python test_scripts/test_deep.py --quick`
- **全量三層**(1.能否正常開啟檔案、2.能否正確建立索引、3.能否編輯文字塊)：`python test_scripts/test_all_pdfs.py`（掃描 test_files 下所有 PDF）
