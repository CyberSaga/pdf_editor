# 視覺化 PDF 編輯器 — 文件索引

本目錄為專案架構與功能說明文件。

| 文件 | 說明 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 專案架構（MVC）、模組職責與資料流 |
| [FEATURES.md](FEATURES.md) | 功能清單與對應的 Model / Controller / View |

## 專案概覽

- **技術棧**：Python 3、PySide6（Qt）、PyMuPDF（fitz）
- **架構**：MVC（Model–View–Controller），訊號/槽連接 View 與 Controller
- **入口**：`main.py` 建立 `PDFModel`、`PDFView`、`PDFController` 並綁定

## 快速導覽

- 啟動程式：`python main.py`
- 核心模組：`model/pdf_model.py`、`controller/pdf_controller.py`、`view/pdf_view.py`
- 輔助：`model/text_block.py`（文字塊索引）、`model/edit_commands.py`（Undo/Redo）、`utils/helpers.py`（工具函式）
