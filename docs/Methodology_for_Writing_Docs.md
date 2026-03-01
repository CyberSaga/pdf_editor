# 文件維護方法（Writing Method）

本文件定義以下檔案的維護邊界、更新時機與寫作規則：

- `docs/README.md`
- `docs/README.zh-TW.md`
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`
- `docs/架構.txt`
- `docs/solutions.md`

---

## 1. 全域原則

1. 單一事實來源（Single Source of Truth）  
   架構事實以 `ARCHITECTURE.md` 為主，功能細節以 `FEATURES.md` 為主；README 只保留摘要。

2. 先改程式，再改文件  
   文件只能描述「目前程式已存在」的行為，不記錄尚未實作的規劃。

3. 中英 README 同步  
   `README.md` 與 `README.zh-TW.md` 章節結構、項目數量、功能清單需同步。

4. 避免在 README 放測試細節  
   測試命令與除錯流程放在其他文件（如 `solutions.md` 或測試文件），README 保持對外簡潔。

5. 固定 UTF-8 編碼  
   所有文件使用 UTF-8，避免繁中亂碼（mojibake）。

6. README 採使用者導向
   README 只回答使用者關心的內容：這是什麼、有哪些功能、怎麼安裝/執行/打包、授權與免責；開發者內部設計移至 `FEATURES.md` / `ARCHITECTURE.md`。

---

## 2. 各文件責任邊界

## 2.1 `docs/README.md`（英文對外摘要）

用途：
- 專案一句話定位、主要功能摘要、安裝/執行/打包入口。

應包含：
- 使用者可見功能與能力（非內部實作細節）。
- 對外依賴（PySide6、PyMuPDF、Pillow、pytesseract）。
- 連到 `FEATURES.md` 與 `ARCHITECTURE.md`。
- 法律/授權與免責資訊。

不應包含：
- 細粒度函式列表或內部 API 名稱（例如 `model.tools.*`、`_update_mode`）。
- MVC 分層、session state、command internals 等開發者資訊。
- 長篇問題追蹤。
- 測試命令清單。

格式：
- 針對每一個 ## 層級的段落，必須編號計數。

---

## 2.2 `docs/README.zh-TW.md`（繁中對外摘要）

用途：
- 與英文 README 同等資訊的繁中版本。

規則：
- 與 `README.md` 章節對齊（標題順序一致）。
- 僅語言轉換，不新增獨立事實。
- 維持 UTF-8，提交前以 UTF-8 方式讀取驗證。

---

## 2.3 `docs/FEATURES.md`（功能層說明）

用途：
- 描述已實作功能、流程與關鍵函式入口。

規則：
- 使用段落式敘述。
- 每節可列「關鍵函式包含 ...」以便追蹤程式入口。
- 功能必須對應到現有 Controller/Model/Tool 呼叫路徑。

---

## 2.4 `docs/ARCHITECTURE.md`（架構層說明）

用途：
- 說明分層責任（Model/Controller/View/Tools/Printing）。
- 說明生命週期流程（open/edit/render/save/close）。

規則：
- 使用 ASCII Art Diagram 繪製專案架構
- 重點放在邊界與責任，不放 UI 使用教學。
- 任何 Breaking API 或工具註冊順序異動，需先更新此檔。

---

## 2.5 `docs/架構.txt`（快速結構地圖）

用途：
- 以樹狀清單快速呈現「目前實際存在」的目錄、核心檔案與模組定位。

規則：
- 使用繁體中文，短句註解，不重複 `ARCHITECTURE.md` 長文。
- 每次文件更新時，`架構.txt` 必須同步檢查並更新，不得跳過（即使本次主要改動不在架構）。
- 「完整」的定義：至少涵蓋 `main.py`、`model/`、`controller/`、`view/`、`src/printing/`、`utils/`、`docs/`、`test_scripts/`，以及其核心檔案清單。
- 只要有新增、刪除、搬移、改名（尤其 `model/tools/*`、`src/printing/*`），必須在同一提交更新 `架構.txt`。
- 更新後需做一致性驗證：`架構.txt` 內容必須與實際檔案樹一致，不可保留已不存在路徑，也不可遺漏新核心模組。

---

## 2.6 `docs/solutions.md`（問題與解法履歷）

用途：
- 記錄「發生過的真實問題」及「最終採用解法」。

規則：
- 新條目一律附：問題、原因、有效解法、涉及檔案。
- 新增內容以「附加到檔尾」為原則，不覆蓋歷史。
- 避免只有結論，需留下可追溯根因。

---

## 2.7 `test_scripts/TEST_SCRIPTS.md`（測試用腳本用途說明）

用途：
- 作為 `test_scripts/` 的單一入口文件，讓使用者快速判斷每個測試檔的用途、執行方式與適用情境。

規則：
- 新增、移除、改名，或改變測試型態（`pytest` / script / hybrid）時，必須同步更新 `TEST_SCRIPTS.md`。
- 必須清楚標示可被 `pytest` 收集的檔案，以及刻意不被收集（例如 `__test__ = False`）的 script runner。
- 若同一檔案同時支援 `pytest` 與 CLI，需在文件內同時提供兩種執行指令。
- 指令應可直接複製執行，並與專案標準測試環境一致（例如 `QT_QPA_PLATFORM=offscreen`、`PYTHONPATH=.`）。
- 若腳本會輸出報告或檔案，需註明預設輸出位置與清理建議。

---

## 3. 什麼情況要更新哪些文件

1. 新增/移除工具 API（例如 annotation/watermark/search/ocr）  
   必改：`ARCHITECTURE.md`、`FEATURES.md`、`架構.txt`、雙 README（摘要層）。

2. 控制流程或狀態同步邏輯變更（例如 session/mode/dirty）  
   必改：`ARCHITECTURE.md`、`FEATURES.md`；有實際事故再加 `solutions.md`。

3. 僅 UI 細節或文案調整  
   優先改：`FEATURES.md`；README 只在對外描述需變更時才改。

4. Bug 修復且有代表性根因  
   必加：`solutions.md`（追加於檔尾）。

5. 專案結構重排（檔案搬移、目錄改名）  
   必改：`架構.txt`、`ARCHITECTURE.md`。

---

## 4. 建議更新流程（SOP）

1. 確認程式已合併且可執行。  
2. 將本輪重要問題追加到 `solutions.md` 檔尾。  
3. 先更新 `ARCHITECTURE.md`（邊界與流程）。  
4. 更新 `FEATURES.md`（功能與函式入口）。  
5. 更新 `架構.txt`（樹狀地圖）。  
6. 同步更新 `README.md` 與 `README.zh-TW.md`（只保留摘要）。  
7. 最後做一致性檢查（名稱、API 路徑、章節對齊、UTF-8）。

---

## 5. 一致性檢查清單（提交前）

- `README.md` 與 `README.zh-TW.md` 的章節與重點是否一致。
- README 是否避免放測試細節。
- `FEATURES.md` 是否仍為段落式且含關鍵函式入口。
- `ARCHITECTURE.md` 是否與目前實作邊界一致（尤其 `model.tools`）。
- `架構.txt` 是否反映目前目錄與模組責任。
- `solutions.md` 新增內容是否為「檔尾追加」且含根因與有效解決方案。
- 所有檔案是否 UTF-8 可正常讀取。
