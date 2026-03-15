# 文件撰寫方法 (Methodology for Writing Docs)

本專案的文件刻意維持「少但精」，要求高訊噪比。此文件定義：

- 哪些文件是「權威/必須維護」(canonical)
- 各文件的責任範圍
- 如何更新文件，確保與程式行為一致

必須維護的權威文件：

- `docs/README.md`
- `docs/README.zh-TW.md`
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`
- `docs/架構.txt`
- `docs/solutions.md`
- `test_scripts/TEST_SCRIPTS.md`

此檔案為繁體中文版本。英文版請見：

- `docs/Methodology_for_Writing_Docs.md`

---

## 1. 原則

1. 單一事實來源 (Single Source of Truth)
   - 架構與資料流細節：`docs/ARCHITECTURE.md`
   - 使用者可見行為：`docs/FEATURES.md`
   - README：入口與導覽 (是什麼、怎麼跑、要看哪裡)

2. 「目前怎麼運作」優先於「原本打算怎麼做」
   - 文件必須反映現況，特別是儲存/最佳化流程、執行緒/背景工作、失敗模式。
   - 只要改了行為，請在同一個變更集一起更新文件。

3. 讓快速路徑保持快速
   - README 不要變成設計文件；詳細內容改放 `docs/FEATURES.md` / `docs/ARCHITECTURE.md`，README 用連結導流。

4. 一律 UTF-8
   - 所有文件皆使用 UTF-8。
   - 若終端機顯示亂碼 (mojibake)，先當作「顯示/編碼」問題處理，不要直接判定檔案壞掉。

5. 允許使用圖表 (能減少文字就用)
   - `docs/ARCHITECTURE.md` 可使用 Mermaid 圖描述工作流程/管線。
   - Mermaid 節點標籤要短；若標籤含括號或標點，請用引號包住。

---

## 2. 各文件的責任範圍

### 2.1 `docs/README.md`

應包含：

- 這個 app 是什麼、給誰用
- 最小可用的執行/開發方式
- 指向 `docs/FEATURES.md` 與 `docs/ARCHITECTURE.md` 的連結

避免：

- 深入實作細節 (放到 `docs/ARCHITECTURE.md`)
- 大量疑難排解 (用 `docs/solutions.md`)

### 2.2 `docs/README.zh-TW.md`

需與 `docs/README.md` 保持一致，但允許針對 zh-TW 讀者做語氣與用詞調整。

### 2.3 `docs/FEATURES.md`

目的：描述「使用者看到的行為」與「限制」(使用者能做什麼、會發生什麼)。

應包含：

- 工作流程層級的行為 (例如「一定另存最佳化副本，不覆寫原檔」)
- 預設值與預設集 (presets) 的名稱與意義
- UX 期望 (例如「背景執行」、「完成後以新分頁開啟」)

避免：

- 不必要的 class/method 名稱
- 深入資料流 (放到 `docs/ARCHITECTURE.md`)

### 2.4 `docs/ARCHITECTURE.md`

目的：描述系統如何切分模組、以及資料如何流動。

應包含：

- 模組邊界 (Model/Controller/View/Tools/Printing)
- 關鍵管線 (open/edit/render/save/close; optimize-copy; audit scan)
- 效能護欄 (哪些不能跑 UI thread、哪些必須 cache、哪些要暫停)
- 圖表：
  - ASCII 圖可接受
  - 非平凡流程建議用 Mermaid

新增流程圖時：

- 放在該章節旁邊，不要把所有圖集中在文件最上面
- 在圖旁邊寫清楚關鍵不變條件 (例如「絕不修改 live document」)

### 2.5 `docs/架構.txt`

目的：給貢獻者快速掃描的「資料夾/檔案地圖」(純文字，易於瀏覽)。

應包含：

- 檔案/資料夾清單與「各自放什麼」
- 指向 `docs/ARCHITECTURE.md` 的權威章節連結/提示

避免：

- 重複完整架構解釋
- 重複功能語意 (改用連結)

### 2.6 `docs/solutions.md`

目的：營運/維運知識庫，回答「X 壞了怎麼辦」。

應包含：

- 症狀、根因、實際修復步驟
- 已知環境/設定的坑

避免：

- 沒有可執行動作的設計理念

### 2.7 `test_scripts/TEST_SCRIPTS.md`

目的：測試/基準/驗證腳本的索引與執行方式。

應包含：

- 每個腳本驗證什麼 (workflow, integrity, benchmark)
- headless 跑法 (Qt env vars)、預期時間、輸出位置

---

## 3. 功能文件放置規則

請用下列「路由」讓讀者快速找到資訊：

1. 新 UI 入口 (選單、對話框、新流程)
   - `docs/FEATURES.md`：描述使用者看到什麼
   - `docs/ARCHITECTURE.md`：描述 controller/model 管線與執行緒

2. 大檔/效能敏感流程 (例如 PDF 最佳化)
   - `docs/ARCHITECTURE.md` 必須包含：
     - 管線圖
     - 哪些工作跑在 UI thread 之外
     - cache 語意 (cache 什麼、活多久、何時失效)
     - 任何「暫停背景工作」規則

3. 不支援的控制項 / 與其他工具不完全相容
   - 用獨立文件列清單與理由 (例如 `docs/unsupported-optimizer.md`)
   - 從 `docs/FEATURES.md` 連結過去 (不要在 README 重複整份清單)

4. 新增腳本 (benchmark, validator)
   - 加到 `test_scripts/TEST_SCRIPTS.md`
   - 若腳本是功能契約的一部分，從 `docs/ARCHITECTURE.md` 連結過去

---

## 4. 文件更新循環 (PDCA)

1. Plan
   - 先明確本次「程式」要改什麼，並列出受影響的文件清單
   - 決定哪份文件是本次改動的權威來源 (通常是 `docs/FEATURES.md` 或 `docs/ARCHITECTURE.md`)
2. Do
   - 先完成程式改動
   - 在同一個變更集內更新文件，讓文件描述追上實際行為 (避免文件領跑程式)
3. Check
   - 跑最小必要驗證
   - 檢查文件描述是否與 UI 行為一致
4. Act
   - 若使用者仍會困惑，把細節移到正確文件層級 (README -> FEATURES/ARCHITECTURE -> solutions)

---

## 5. 快速檢查清單

- [ ] 使用者可見行為有變：更新 `docs/FEATURES.md`
- [ ] 管線/執行緒/cache 有變：更新 `docs/ARCHITECTURE.md` (流程複雜就加圖)
- [ ] 資料夾/入口點有變：更新 `docs/架構.txt`
- [ ] 新增或變更腳本：更新 `test_scripts/TEST_SCRIPTS.md`
- [ ] 文件可在 GitHub 正常顯示，且為 UTF-8
