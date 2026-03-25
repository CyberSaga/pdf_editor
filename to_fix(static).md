# PDF Editor — To Fix

## 專案目標
把 PDF 文字編輯做得更接近 Acrobat 的體驗：不要誤刪鄰近內容、不要 silent-fail、不要編輯框和落點跳動，且新文字要盡量維持原本樣式與閱讀順序。

---

## GUI 測試結果（靜態啟動確認）
- GUI 可正常啟動（python3 main.py 啟動無 crash）
- `@dataclass(slots=True)` → `@dataclass` 已於上一輪修正（base_driver.py, pdf_renderer.py, helper_protocol.py, print_dialog.py）
- 無法透過 computer use 直接操作 GUI，以下測試結果來自程式碼審查

---

## 已知 Bug — 確認狀態（來自上一輪 code review）

### HIGH Severity

**#1 — _render_scale vs self.scale desync（縮放時編輯框位置漂移）**
- 狀態：**仍存在**
- 位置：`src/` 內座標轉換相關檔案，annotation rect 計算（約 line 3203-3204）
- 問題：editor overlay 計算 rect 時混用 `self.scale`（目標縮放值）與 `_render_scale`（實際渲染縮放值），滾輪 debounce 期間兩值不同步，導致編輯框位置漂移

**#6 — Drag cross-page Y-offset 計算錯誤**
- 狀態：**仍存在**
- 位置：drag-move 處理約 line 2784
- 問題：`page_idx` 在拖曳開始時固定為起始頁，跨頁拖曳時 Y-offset clamping 仍以起始頁為基準，導致落點計算錯誤

**#8 — Zoom 時 _render_scale 未更新**
- 狀態：**與 #1 同源，仍存在**
- 問題：zoom 動作期間 `_render_scale` 未即時跟隨 `self.scale`，任何在此期間開啟的編輯器都會用錯誤的縮放比例計算座標

### MEDIUM Severity

**#2 — Sub-pixel 0.5pt threshold 導致細微移動被忽略**
- 狀態：**需確認**（`position_changed` 函式的閾值邏輯）
- 問題：drag 移動距離小於 0.5pt 時 `position_changed` 回傳 False，移動被 silent drop

**#3 — Double-finalize race condition**
- 狀態：**部分緩解，仍有風險**
- 位置：`_on_editor_focus_out`（line 2159）、`_on_app_focus_changed`（line 2154）→ 都呼叫 `_schedule_finalize_on_focus_change()`
- 問題：有 re-entrancy guard（line 3422），但 QTimer 排程的 finalize 仍可能在 guard 清除後被第二個事件觸發，造成 duplicate finalize

**#4 — Viewport restore dual-timer 問題**
- 狀態：**無法確認（程式碼中未找到雙 timer 模式）**
- 備注：上一輪 review 提到此問題，但本輪靜態審查未找到對應的 `QTimer.singleShot(0) + QTimer.singleShot(180)` 雙重呼叫，可能已修或邏輯不同

**#5 — 多色段落顏色繼承丟失**
- 狀態：**仍存在**
- 位置：paragraph 模式重建邏輯，約 line 749、763
- 問題：用 `most_common(1)` 取得段落「主色」後存入 `EditableParagraph`，放棄了 per-run 的顏色資訊；儲存時所有 run 都套用同一顏色，多色段落顏色遭到覆蓋

**#7 — Position-only drag silent rollback**
- 狀態：**仍存在**
- 位置：約 line 3190
- 問題：若拖曳前後文字內容相同（只改位置），`editing_rect` 更新但無 verification；在某些路徑下可能觸發 verification failure → silent rollback，使用者看不到任何反饋

**#9 — _replay_protected_spans 失敗 silent rollback**
- 狀態：**仍存在**
- 位置：約 line 2160-2223
- 問題：多個失敗點（HTML 解析、font candidate、htmlbox）僅 DEBUG log，最終 validation 回傳 False 後只顯示 generic error message，不告知使用者是哪個 span 失敗、也不提供回復選項

---

## 新發現問題（本輪程式碼審查）

### HIGH

**#10 — Drag 跨頁時 page_idx 未動態更新**
- 位置：drag-move 事件處理
- 問題：拖曳過程中 `page_idx` 不隨滑鼠位置動態計算，導致拖到下一頁時 Y 座標轉換仍以上一頁的 page origin 為基準，文字落點偏移

### MEDIUM

**#11 — EditableParagraph 顏色模型不完整**
- 位置：model/text_block.py 或 EditableParagraph 定義
- 問題：`EditableParagraph` 只儲存 dominant color 而非 `List[RunColor]`，導致整個編輯流程缺乏 per-run 顏色支援的基礎資料結構

**#12 — _replay_protected_spans 無 user-facing 錯誤詳情**
- 位置：約 line 2160-2223
- 問題：失敗訊息過於籠統，使用者無法得知是哪段 protected span 出問題，也無法手動重試或忽略特定 span

### LOW

**#13 — 除錯 log 過多導致效能潛在問題**
- 位置：多處 DEBUG 級別 logging
- 問題：production 使用時大量 DEBUG log 可能拖慢 render loop，建議加條件開關

---

## 建議修復優先順序

1. **[HIGH] 統一座標轉換基準（Bug #1, #8, #10）**
   在 editor 建立與 drag-move 時，統一以 `_render_scale` 作為唯一的座標基準；zoom 結束前 lock editor 建立；drag 過程中動態計算當前頁 `page_idx`

2. **[HIGH] 修正跨頁拖曳 page_idx 動態更新（Bug #6, #10）**
   在 `mouseMoveEvent` 中根據滑鼠 Y 坐標即時計算所在頁，更新 Y-offset

3. **[MEDIUM] 修正多色段落顏色保留（Bug #5, #11）**
   `EditableParagraph` 改為儲存 `List[Tuple[str, QColor]]`（per-run 顏色），rebuild 時逐 run 套用

4. **[MEDIUM] 統一 focus-out finalize 入口（Bug #3）**
   `_on_editor_focus_out` 和 `_on_app_focus_changed` 合併為單一 `_request_finalize()` 入口，用 flag 確保只執行一次

5. **[MEDIUM] Position-only drag 驗證改善（Bug #7）**
   位置變更的驗證應獨立於內容驗證，避免因文字相同而 silent rollback；position change 應直接接受

6. **[MEDIUM] _replay_protected_spans 錯誤提示改善（Bug #9, #12）**
   失敗時顯示具體 span 識別資訊（位置、原文字），並提供「略過此 span 繼續」選項

7. **[LOW] Sub-pixel threshold 調整（Bug #2）**
   評估是否把 0.5pt 閾值改為 0（或移除），避免 fine-grained 拖曳被忽略

---

## 待辦測試場景（修復後驗證用）

- [ ] Scenario 1: 拖曳文字方塊到頁面不同位置，落點與預覽一致
- [ ] Scenario 2: 跨頁拖曳，Y 座標正確
- [ ] Scenario 3: Ctrl+滾輪縮放後，文字方塊不漂移
- [ ] Scenario 4: 雙擊進入編輯 → 修改文字 → 點擊外部，正確儲存，無 double-finalize
- [ ] Scenario 5: 含多色文字的段落，編輯後各 run 顏色保留

---

*最後更新：2026-03-25（基於靜態程式碼審查 + 上一輪 GUI 測試結果）*
