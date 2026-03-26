# PDF Editor 文字編輯 UX 測試報告
**測試日期：** 2026-03-26
**測試版本：** latest commit (0326.md 修復後)
**測試 PDF：** TIA-942-B-2017 Rev Full.pdf (402 頁)
**測試人員：** Claude (自動化手動操作測試)

---

## 一、測試環境

| 項目 | 說明 |
|------|------|
| GUI 框架 | PySide6 (Qt 6) |
| PDF 引擎 | PyMuPDF (fitz) |
| 作業系統 | macOS (RuinClaw-MacMini) |
| 啟動方式 | `python /Users/ruinclaw/Documents/pdf_editor/main.py` |

---

## 二、測試結果總覽

| 測試項目 | 結果 | 說明 |
|---------|------|------|
| GUI 啟動 | ✅ 正常 | 視窗標題「視覺化 PDF 編輯器」，工具列完整 |
| 開啟 PDF | ✅ 正常 | 402 頁 PDF 正確載入，縮圖顯示正常 |
| 進入 edit_text 模式 | ✅ 正常 | 點擊「編輯文字」按鈕啟動，文字塊 hover 高亮顯示 |
| 點擊文字塊開啟 editor | ✅ 正常 | 單擊文字塊後，透明 QTextEdit overlay 出現，藍色虛線框明顯 |
| 文字輸入 | ✅ 正常 | 游標正確定位，字元輸入無延遲 |
| 點擊外部提交 | ✅ 正常 | 點擊 editor 外部區域正確提交修改，PDF 即時更新 |
| 點擊空白區域不誤觸 | ✅ 正常 | 在無文字的空白區域點擊不會觸發新 editor |
| Escape 放棄編輯 | ✅ 正常（單獨使用時） | 單獨按 Escape 可正確放棄，不提交修改 |
| Escape 放棄拖曳 | ✅ 正常 | 拖曳後 Escape 正確放棄，文字框回到原位 |
| 拖曳文字框 | ✅ 正常 | 超過拖曳閾值後進入拖曳模式，位置更新流暢 |
| **Ctrl+Z 行內復原** | ❌ **BUG** | 轉發給主視窗 undo，未還原編輯中的字元 |
| **Escape 在 Ctrl+Z 後失效** | ❌ **BUG** | Ctrl+Z 觸發 focus-out，editor 被提前提交，Escape 已來不及放棄 |
| **主視窗 Undo 無法復原文字編輯** | ⚠️ 待確認 | 提交後按 Ctrl+Z，undo 按鈕仍灰色，text edit 不在 undo stack 中 |

---

## 三、詳細發現

### 3.1 ✅ 正常運作項目

**行內 Editor 架構**
- 採用透明 `QGraphicsProxyWidget(QTextEdit)` 覆蓋在 PDF 頁面上，藍色 1.5px 虛線邊框清晰可見
- 字型、字級、顏色從 PDF 原始資料繼承，視覺預覽接近最終渲染結果
- 文字塊擷取粒度可設定（段落/行/詞），flex 設計合理

**Escape 放棄行為（單獨使用）**
測試步驟：開啟 editor → 輸入 "X" → 立即按 Escape
結果：✅ "X" 被放棄，PDF 未修改
程式碼路徑正確：`_editor_key_press` → `_handle_escape()` → `_discard_text_edit_once = True` → `_finalize_text_edit_impl()` 早返回

**拖曳文字框**
- 拖曳閾值（`_should_start_editor_drag`）防止意外移動
- 拖曳期間顯示 `ClosedHandCursor`，視覺回饋清晰
- 拖曳後 Escape 正確放棄位置變更

---

### 3.2 ❌ BUG #1：Ctrl+Z 在 editor 焦點中轉發給主視窗 Undo

**重現步驟：**
1. 進入 edit_text 模式，點擊文字塊開啟 editor
2. 輸入 "TEST"
3. 按 Ctrl+Z（想要逐字元復原）

**實際行為：**
`_EditorShortcutForwarder.eventFilter` 攔截 Ctrl+Z，呼叫 `_action_undo.trigger()`（主視窗 undo），"TEST" 四個字元仍留在 editor 中。

**程式碼位置：** `view/pdf_view.py`，`_EditorShortcutForwarder` class，第 47–82 行：
```python
if event.key() == Qt.Key_Z and not (modifiers & Qt.ShiftModifier):
    return self._trigger("_action_undo")   # ← 轉給主視窗，非 QTextEdit 行內 undo
```

**Acrobat 行為：**
Acrobat 中，Ctrl+Z 在文字編輯狀態下會逐字元復原已輸入的文字；提交後 Ctrl+Z 才是 PDF 層級的 undo。

**修復建議：**
當 editor 開啟時，Ctrl+Z 應優先呼叫 `editor.undo()`（QTextEdit 行內 undo），而非轉發主視窗。可在 `_EditorShortcutForwarder` 加判斷：
```python
# 若 editor 有行內 undo history → 讓 QTextEdit 自己處理
if editor.document().isUndoAvailable():
    return False   # 不攔截，讓 QTextEdit 的原生 Ctrl+Z 處理
return self._trigger("_action_undo")  # 否則才轉發主視窗
```

---

### 3.3 ❌ BUG #2：Ctrl+Z 觸發 focus-out，導致 editor 被提前提交，Escape 失效

**重現步驟：**
1. 進入 editor，輸入 "TEST"
2. 按 Ctrl+Z（預期放棄輸入）
3. 按 Escape（預期放棄整個 edit）

**實際行為：**
Ctrl+Z 轉發至主視窗 undo 時，可能觸發 PDF view 重渲或焦點短暫轉移：
- `_on_app_focus_changed` 觸發 → `_schedule_finalize_on_focus_change` → 40ms timer
- Timer 到期時 `_finalize_if_focus_outside_edit_context()` 呼叫 `_finalize_text_edit()` **未設 `_discard_text_edit_once`**
- "TEST" 被提交進 PDF
- 到 Escape 時，editor 已關閉，Escape 只是切換 mode，無法再放棄

**關鍵程式碼：** `_finalize_if_focus_outside_edit_context`（第 2186 行）：
```python
self._finalize_text_edit()   # ← 無 discard flag，直接提交
```

**修復建議：**
在 `_finalize_if_focus_outside_edit_context` 中，若焦點是因為主視窗 action 觸發而非使用者意圖離開 editor，應延遲或跳過 finalize；或在 Ctrl+Z 轉發時暫時保持 editor 焦點。

---

### 3.4 ⚠️ Undo Stack 異常（待進一步確認）

文字編輯提交後，主視窗「復原」按鈕仍為灰色（undo stack 空），文件標記「已修改」但無法 undo 文字修改。
可能原因：
- `sig_edit_text` 信號未正確加入 undo stack
- 或 Ctrl+Z 的 4 次觸發消耗了 undo 操作後立即 redo，造成 stack 為空

---

## 四、UX 與 Acrobat 對比評分

| UX 維度 | 評分 | 說明 |
|---------|------|------|
| 進入編輯流暢度 | 8/10 | 單擊文字塊即開啟 editor，反應迅速；唯 TOC 粒度選「整段」時選取範圍略大 |
| 視覺回饋 | 7/10 | 透明 editor + 藍色虛線邊框清晰；但 cursor 在小字級（8-10pt）100% 縮放下難以辨識 |
| 字型繼承 | 8/10 | 字型/字色自動從 PDF span 繼承，Acrobat 同款體驗 |
| Escape 放棄 | 7/10 | 單獨使用正常；與 Ctrl+Z 混用後失效（見 BUG #2） |
| Ctrl+Z 復原 | 3/10 | 不符合 Acrobat 行為；在 editor 中無法逐字元 undo |
| 拖曳重定位 | 8/10 | 拖曳閾值設計合理，拖曳流暢，Escape 正確放棄 |
| 空白區域防誤觸 | 9/10 | 優異；空白區域不觸發 editor |
| 提交後即時更新 | 8/10 | PDF 內容即時重渲，無閃爍 |
| **整體評分** | **6.8/10** | 核心流程可用，Ctrl+Z / Undo 行為是主要 gap |

---

## 五、Priority 修復建議

| 優先級 | 項目 | 描述 |
|--------|------|------|
| P0 | Ctrl+Z 行為修正 | editor 焦點中 Ctrl+Z 應先 undo 行內輸入（`editor.undo()`），不轉發主視窗 |
| P0 | Focus-out 提前提交問題 | `_finalize_if_focus_outside_edit_context` 加保護，避免主視窗 action 觸發 focus-out 時提前提交 |
| P1 | Undo stack 驗證 | 確認文字 edit 提交後是否正確加入 undo stack；`sig_edit_text` → controller 路徑需 end-to-end 驗證 |
| P2 | 小字級游標可見性 | 100% 縮放下 8-10pt 文字的游標難以辨識，可在 editor stylesheet 加 `caret-color` 或加粗 |

---

## 六、結論

0326.md 所描述的修復項目（inline edit 穩定性、no-op 比較正規化、drag handling 改進、Ctrl+S/Z/Y 快捷鍵轉發）已大部分實作到位。核心編輯流程（點擊→輸入→提交）運作流暢，拖曳重定位和 Escape 放棄基本正確。

**主要未達 Acrobat 等級的差距**在於 Ctrl+Z 語意：Acrobat 在 editor 開啟狀態中 Ctrl+Z 是行內逐字 undo，不是 PDF 層級 undo。目前設計將 Ctrl+Z 直接轉發主視窗，不僅語意錯誤，還會觸發 focus-out 競爭條件，導致 Escape discard 在混用時失效。修正此問題後，整體 UX 可達 Acrobat 8/10 水準。
