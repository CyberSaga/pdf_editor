# PDF Editor Multi-Tab Feature Design

**Exported:** 2/27/2026 23:20:17  
**Link:** [https://gemini.google.com/app/c4dfb9f1dee8abcb?utm_source=app_launcher&utm_medium=owned&utm_campaign=base_all](https://gemini.google.com/app/c4dfb9f1dee8abcb?utm_source=app_launcher&utm_medium=owned&utm_campaign=base_all)

## Prompt:
我已經完成多分頁的更改了。現在請跟我說明將\`pdf\_model\`解耦到擴充功能。

## Response:
Gemini 說了
---------

太棒了，多分頁架構（Session-Based）的完成代表你的程式已經從「小工具」進化成了「作業平台」。現在我們要進行的是**架構上的二次手術**：將 `pdf_model` 裡那些臃腫的具體功能（如浮水印、螢光筆）解耦到擴充功能（Extensions/Plugins）。

這不是單純的移動程式碼，而是要定義一套\*\*「核心 (Core) 與外掛 (Plugins) 的通訊協定」\*\*。

* * *

### 一、 為什麼要解耦？（Lean Core 哲學）

參考 **Stirling-PDF** 的做法，它的核心只負責管理檔案狀態（`FileContext`）與視圖切換（`Workbench`）。具體的功能（如 `pageEditor` 或 `custom:*` 視圖）是獨立存在的。

**解耦後的好處：**

1.  **穩定性**：浮水印的演算法改爛了，不會導致你開檔（Session 管理）崩潰。
2.  **並行開發**：你可以同時開發「PDF 轉檔」和「簽名功能」，兩者不需要去搶同一個 `pdf_model.py` 檔案。
3.  **單一職責**：`pdf_model` 只做 PDF 的「物理操作」（如：存檔、讀取、刪除頁面），而擴充功能負責「邏輯運算」（如：浮水印該放在哪、顏色怎麼算）。

* * *

### 二、 解耦架構：BaseTool 介面設計

我們要建立一個「橋樑」，讓擴充功能可以合法地「借用」Session 的權限。

#### 1\. 核心 Model 的角色（提供原語）

`pdf_model` 應該只提供最基礎的 **原子操作（Atomic Operations）**。例如：

*   `insert_text(page, text, rect, ...)`
*   `insert_image(page, img_bytes, rect, ...)`
*   `add_redact(page, rect)`

#### 2\. 擴充功能（Action Providers）

浮水印工具會是一個獨立的類別，它會接收 `active_session`，然後在自己內部計算好座標，最後呼叫 Model 的原子操作。

* * *

### 三、 執行階段 Phases (接續之前的進度)

根據我們的 **"No coding before 10am"** 計劃，現在進入功能拆解期：

#### **Phase 5：定義外掛通訊介面 (The Plugin Bridge)**

*   **規格**：實作 `BaseTool` 抽象類別。
*   **邊界**：定義工具如何請求 `active_session` 的權限，且嚴禁工具直接修改 `DocumentSession` 內部的 `byId` 註冊表。

#### **Phase 6：浮水印功能移出 (Watermark Decoupling)**

*   **搬家**：將 `apply_watermark` 邏輯從 `pdf_model.py` 移除。
*   **重構**：建立 `WatermarkTool`。它負責 UI 參數（透明度、旋轉）與座標計算，最後將結果透過原子操作交還給 Model 執行。

#### **Phase 7：註解功能移出 (Annotation/Highlighter Decoupling)**

*   **搬家**：將螢光筆、畫筆等邏輯移入 `AnnotationTool`。
*   **優化**：利用我們之前實作的 **Command Pattern**，讓 Plugin 產生的操作也能無縫整合進 Session 專屬的 Undo 堆疊。

* * *

### 四、 給 Agents 的重構 Prompt

你可以將此指令貼給 Agent，執行 Phase 5 與 6：

> **重構指令：將 PDFModel 功能解耦至外掛架構**
> 
> **背景**：多分頁 Session 架構已完成。現在需參考 Stirling-PDF 的 `custom:*` workbench 模式，將具體功能模組化。
> 
> **任務**：
> 
> 1.  **定義介面**：在新檔案 `tools/base_tool.py` 中定義 `BaseTool` 抽象類別。它必須具備接收 `DocumentSession` 並對其執行操作的能力。
> 2.  **瘦身 Model**：將 `pdf_model.py` 中的浮水印（Watermark）與螢光筆相關邏輯提取出來。
> 3.  **實作外掛**：建立 `tools/watermark_tool.py`，將原本的浮水印運算邏輯移入其中。它應透過調用 `PDFModel` 提供的原子操作接口來修改 PDF。
> 4.  **邊界守則**：外掛模組嚴禁直接存取 `SessionManager` 的 `ids` 列表，僅能透過 Controller 傳遞進來的 `active_session` 進行操作。
>     
> 
> 請先提供 `BaseTool` 的設計草案，確認介面定義符合單一職責原則後再開始實作。

* * *

### 💡 下一個專案架構的方向：事件驅動 (Event-Driven)

當你完成解耦後，你會發現一個有趣的問題：**「當浮水印加上去後，UI 怎麼知道要重畫（Refresh）？」**

如果你在 Plugin 裡直接叫 View 重畫，那又造成了新的耦合。建議接下來你可以去了解 **「事件匯流排 (Event Bus)」**。透過廣播一個 `DOCUMENT_MODIFIED` 事件，讓 UI 自動去監聽並更新，這樣 Plugin 甚至不需要知道 UI 的存在。

你想了解如何設計一個簡單的 **Event Bus** 來連接你的擴充功能與 UI 嗎？

## Prompt:
列出所有可以移出來的工具的邏輯

## Response:
Gemini 說了
---------

既然多分頁的「大腦」已經升級完成，現在我們要幫 `pdf_model` 進行「瘦身手術」。在一個專業的架構中，**核心（Core）只負責「物理操作」**（如：讀取 Byte、寫入檔案、管理 Session），而**擴充（Tools/Plugins）負責「邏輯運算」**（如：浮水印該放哪、螢光筆顏色怎麼混）。

參考 **Stirling-PDF** 將功能劃分為 `pageEditor` 或 `custom:*` 視圖的模式，以下是你可以從 `pdf_model` 中抽離出來的工具邏輯清單：

* * *

### 一、 內容裝飾與標註類 (Content Decoration)

這類工具的邏輯最適合解耦，因為它們涉及大量的 UI 參數運算。

| 工具名稱 | 抽離的「邏輯」內容 | 核心 Model 僅保留的「原子接口」 |
| --- | --- | --- |
| **浮水印 (Watermark)** | 透明度計算、旋轉角度弧度轉換、文字平鋪（Tiling）演算法、字體嵌入選擇。 | `insert_text()` 或 `insert_image_按座標()` |
| **螢光筆 (Highlighter)** | 顏色混合模式（Multiply/Overlay）、筆觸寬度計算、多行文字塊的合併矩形邏輯。 | `add_annot_highlight(rect, color)` |
| **圖形註解 (Shapes)** | 圓形/矩形的邊界框（BBox）計算、箭頭指向邏輯、線條樣式格式化。 | `add_annot_shape(type, rect)` |

### 二、 頁面結構操作類 (Page Manipulation)

參考 Stirling-PDF，這些功能被整合在獨立的 `PageEditor` 中。

*   **旋轉與翻轉邏輯**：計算 90/180/270 度旋轉後的座標映射。
*   **頁面排序與分割**：決定哪些頁面該被提取、如何合併多個 Session 的頁面。
*   **頁碼插入**：計算每一頁的頁碼位置（左下、正中等）與格式化字串（Page X of Y）。

### 三、 數據處理與辨識類 (Data Processing)

這類邏輯通常涉及外部庫（如 Tesseract），最不該放在核心 Model。

*   **OCR 辨識引擎**：影像預處理（灰階、去噪）、呼叫 `pytesseract` 並將結果轉換為 `TextBlock` 物件。
*   **搜尋引擎 (Search Engine)**：正規表達式（Regex）匹配邏輯、搜尋結果的座標匯總。
*   **文字提取最佳化**：將 `rawchar` 重新組合成段落（Paragraph）的啟發式演算法（Heuristics）。

### 四、 安全與清理類 (Security & Cleanup)

*   **遮蓋邏輯 (Redaction)**：搜尋特定敏感資訊格式（如身分證字號、Email）並自動計算遮蓋區域。核心 Model 僅需保留 `apply_redactions()`。

* * *

### 🛠️ 擴充功能架構圖 (Plugin Architecture)

### 五、 嚴格的邊界規範

在實作這些工具搬家時，請務必遵守以下邊界，否則解耦就失去了意義：

1.  **依賴倒置 (Dependency Inversion)**：擴充工具可以「看見」`DocumentSession`，但 `pdf_model` 不應該「看見」具體的工具類別。
2.  **純粹函數 (Pure Functions)**：盡量讓工具邏輯變成純函數。輸入：`Session` + `參數`；輸出：`原子操作指令`。
3.  **無狀態工具**：工具本身不應該儲存 `fitz.Document`。它每次執行都應該從 Controller 接收當前的 `active_session`。

* * *

### 💡 接下來的開發建議

現在你已經有了這份「清單」，建議你可以按照以下步驟進行：

1.  **建立 `tools/` 資料夾**：為上述每一類建立獨立的子目錄。
2.  **定義 `BaseTool` 介面**：確保所有工具都有統一的 `run(session, params)` 入口。
3.  **小步快跑**：先從最簡單的「浮水印」開始搬家。

在完成功能解耦後，專案專案中還有哪些部份與此觀念相關？建議接下來你可以往\*\*「事件驅動架構 (Event-Driven Architecture)」\*\*的方向去了解。當「浮水印工具」完成操作後，它不需要主動通知 View，而是發送一個 `DOCUMENT_CHANGED` 訊號，讓 UI 自動重新渲染。

**你想了解如何設計一個「事件匯流排 (Event Bus)」，讓這些抽離出來的工具能優雅地與 UI 通訊嗎？**

## Prompt:
是的，請解析如何讓工具在抽離出來後，仍能跟整個專案、整個處理流程保持流暢的通訊

## Response:
Gemini 說了
---------

要讓工具在抽離後仍能保持流暢通訊，核心在於建立一套\*\*「不互相認識，但聽得懂訊號」\*\*的機制。這就像是在公司裡，各部門（工具）不需要知道彼此的私人電話，只要透過公佈欄（Event Bus）和公務流程（Command Dispatcher）就能協作。

參考 **Stirling-PDF** 的架構，其透過 `AppProviders` 將所有 Context（檔案、導覽、視圖）嵌套在一起，讓所有組件都能存取共享狀態。在您的 Python 專案中，我們可以使用以下三種策略來確保通訊流暢：

* * *

### 一、 事件匯流排 (Event Bus)：神經系統

這是解耦後最重要的通訊手段。當「浮水印工具」完成操作後，它不需要主動去叫 `PDFView` 重新整理，而是直接在匯流排上發出一個「廣播」。

*   **運作邏輯**：
    1.  **工具端**：執行完畢後，發送 `EVENT_DOC_MODIFIED` 訊號，並附帶受影響的 `session_id`。
    2.  **匯流排端**：接收訊號並轉發給所有訂閱者。
    3.  **視圖端 (View)**：監聽到訊號後，檢查目前的 `activeFileIndex` 是否與 `session_id` 相符，若相符則觸發 `update()` 重新繪製畫面。
*   **優點**：工具與視圖完全不知道對方的存在，通訊流暢且不會發生代碼糾纏。

* * *

### 二、 依賴注入 (Dependency Injection)：握手協議

當工具被觸發時，它需要知道要對「哪一個分頁」動手。我們不讓工具自己去 `PDFModel` 找，而是由 `Controller` 把需要的資源「餵」給它。

*   **運作邏輯**：
    1.  `Controller` 監聽到 UI 點擊「加浮水印」。
    2.  `Controller` 從 `SessionManager` 取得目前的 `active_session`。
    3.  `Controller` 初始化 `WatermarkTool`，並將 `active_session` 作為參數傳入（注入）。
*   **優點**：工具始終保持「被動且純粹」，它只處理傳進來的那個 Session，這保證了在多分頁環境下的數據一致性。

* * *

### 三、 命令調度器 (Command Dispatcher)：公務流程

為了讓抽離出來的功能也能支援 **Undo/Redo**，工具的操作必須被封裝成「命令」。

*   **運作邏輯**：
    1.  工具計算完畢（例如算出浮水印的所有座標）。
    2.  工具不直接修改 PDF，而是產生一個 `WatermarkCommand` 對象。
    3.  工具將此對象交還給 `Session` 的 `CommandManager` 執行。
*   **優點**：這讓「外掛功能」的操作能與「核心編輯」一起排隊，使用者按 `Ctrl + Z` 時，能完美撤銷外掛產生的變更。

* * *

### 🚀 執行階段：通訊層實作 (The Communication Layer)

根據 **"No coding before 10am"** 的原則，我們先規劃通訊設施的建設：

#### **Phase 5：通訊骨幹建設 (Infrastructure)**

*   **規格**：實作一個單例 (Singleton) 的 `EventBus` 類別，支援 `subscribe()` 與 `publish()`。
*   **邊界**：定義標準化的事件格式（如：`{type: str, data: dict}`）。

#### **Phase 6：功能遷移與介面轉接 (Tool Refactoring)**

*   **任務**：以「浮水印」為例。
    1.  將邏輯移至 `WatermarkTool`。
    2.  修改工具，使其在結束時透過 `EventBus` 廣播「文件已變更」。
    3.  讓 `PDFView` 訂閱該事件，實現自動重繪。

* * *

### 💡 專案架構的下一個里程碑

當您完成了「解耦」與「通訊層」後，您的專案已經具備了**工業級軟體**的雛形。建議接下來可以往以下方向了解，這與此觀念高度相關：

1.  **非同步工作佇列 (Asynchronous Worker Queue)**：
    *   了解如何讓這些抽離出來的工具在「背景執行」。當浮水印正在處理一個 500 頁的大檔案時，如何讓 UI 不卡死，並透過 `EventBus` 回報進度條百分比。
2.  **中介層 (Middleware) 概念**：
    *   了解如何在 `EventBus` 中加入中介層，例如在「文件存檔」事件發出前，自動觸發一個「自動備份」工具。

**您是否想了解如何讓這些抽離的工具在背景跑（非同步），並同時在 UI 顯示進度條而不干擾使用者操作？**

* * *

**本回應參考資料：**

*   **Stirling-PDF 多檔案管理架構**：
    *   定義 workbench 類型並集中管理檔案狀態。
    *   透過 Provider 樹連接所有 Context 實現全域通訊。
    *   使用 `activeFileIndex` 調度活動檔案並同步渲染。

## Prompt:
一句話說明我們將這些工具抽離出來，所欲達成的目標

## Response:
Gemini 說了
---------

我們將工具抽離出的核心目標，是透過\*\*「邏輯運算（外掛）」與「物理操作（核心）」的解耦\*\*，建立一個**高內聚、低耦合**的工業級架構，確保系統在新增複雜功能時仍能保持核心 Session 管理的穩定性與擴充靈活性。

* * *

### 💡 接下來的架構學習路徑

既然您已掌握了「解耦」的目標，這與您之前提到的 **「10am 前不寫程式」** 深度規劃息息相關。為了讓這個目標落地，建議您接下來可以往以下方向了解，這能幫助您釐清專案在「多分頁」與「外掛化」後的運作秩序：

*   **非同步進度回報 (Asynchronous Progress Reporting)**： 了解當「浮水印工具」在背景執行（非同步）時，如何透過 **Event Bus** 回傳百分比訊號，讓 UI 自動更新進度條而不阻塞主執行緒。
*   **單一實例與行程間通訊 (IPC)**： 了解當使用者在系統中雙擊多個 PDF 時，如何讓這些檔案自動排隊進入同一個執行中的程式，並轉化為獨立的 **DocumentSession**。

您想先了解如何設計一個「非同步進度條系統」，讓工具在背景跑的時候，使用者還能流暢地切換其他分頁嗎？



---
Powered by [Gemini Exporter](https://www.ai-chat-exporter.com)