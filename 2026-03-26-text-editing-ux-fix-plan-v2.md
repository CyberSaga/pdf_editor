# 文字編輯 UX 修復計畫 v2
**日期：** 2026-03-26
**依據：** GUI 手動測試報告 + CEO Review

---

## 問題總覽

| # | 優先級 | 問題 | 影響 |
|---|--------|------|------|
| 1 | P0 | 文字重疊：editor 透明疊在 PDF 文字上，無法閱讀 | 使用者體驗最直觀的障礙 |
| 2 | P0 | Ctrl+Z 在 editor 焦點中轉發給主視窗 Undo，不還原行內輸入 | 與 Acrobat 行為不符 |
| 3 | P0 | Ctrl+Z 觸發 focus-out 競爭條件，editor 被提前提交 | Escape 放棄失效 |
| 4 | P1 | 文字編輯提交後 Undo stack 為空 | 無法復原已提交的修改 |

---

## Phase 1：文字重疊修復（Issue #1）

### 根因
- `_create_text_editor()` 在 line 3331 設定 `background: transparent`
- QTextEdit 作為 QGraphicsProxyWidget 疊在 PDF 頁面 pixmap 上
- 兩份文字同時可見：PDF pixmap 中的原始文字 + QTextEdit 的可編輯文字

### 修復方案（白色遮罩法）

**檔案：** `view/pdf_view.py`

**在 `_create_text_editor()` 中（line 3361 後），新增白色背景矩形：**

```python
# 現有程式碼
self.text_editor = self.scene.addWidget(editor)
self.text_editor.setPos(pos_x, pos_y)

# === 新增：白色遮罩隱藏 PDF 原始文字 ===
from PySide6.QtGui import QColor, QBrush, QPen
bg_rect = self.scene.addRect(
    pos_x, pos_y,
    max(scaled_width, 80),
    max(scaled_rect.height, 40),
    QPen(Qt.NoPen),
    QBrush(QColor(255, 255, 255))   # 純白背景
)
bg_rect.setZValue(self.text_editor.zValue() - 1)  # 在 editor 後、pixmap 前
self._editor_background_rect = bg_rect
```

**在 `_finalize_text_edit_impl()` 中（line 3548 附近，移除 proxy 前），清理遮罩：**

```python
# === 新增：移除白色遮罩 ===
bg_to_remove = getattr(self, '_editor_background_rect', None)
if bg_to_remove is not None:
    if bg_to_remove.scene():
        self.scene.removeItem(bg_to_remove)
    self._editor_background_rect = None

# 現有程式碼
proxy_to_remove = self.text_editor
self.text_editor = None
```

**也需要在拖曳移動時同步遮罩位置：**
在 `_mouse_move` 的拖曳邏輯中（clamp 後更新 editor 位置的地方），加入：

```python
# 同步白色遮罩位置
if hasattr(self, '_editor_background_rect') and self._editor_background_rect:
    self._editor_background_rect.setPos(clamped_x, clamped_y)
```

### 風險
- **低**：純視覺層修改，不影響 PDF 內容或提交邏輯
- 考量：若頁面背景不是白色（如彩色背景 PDF），遮罩會不協調
  - 進階方案：從 pixmap 取樣背景色，動態設定遮罩顏色

---

## Phase 2：Ctrl+Z 行為修正（Issue #2）

### 根因
- `_EditorShortcutForwarder.eventFilter()` 攔截所有 Ctrl+Z
- 無條件呼叫 `_action_undo.trigger()`（主視窗 undo）
- QTextEdit 內建 undo 從未被觸發

### 修復方案

**檔案：** `view/pdf_view.py`，`_EditorShortcutForwarder` class（lines 47-82）

**將原本的：**
```python
if event.key() == Qt.Key_Z and not (modifiers & Qt.ShiftModifier):
    return self._trigger("_action_undo")
if event.key() == Qt.Key_Y:
    return self._trigger("_action_redo")
if event.key() == Qt.Key_Z and (modifiers & Qt.ShiftModifier):
    return self._trigger("_action_redo")
```

**改為：**
```python
# Ctrl+Z：先檢查 editor 行內 undo，無 undo 時才轉發主視窗
if event.key() == Qt.Key_Z and not (modifiers & Qt.ShiftModifier):
    editor = self._view.text_editor
    if editor and editor.widget():
        doc = editor.widget().document()
        if doc.isUndoAvailable():
            editor.widget().undo()
            return True
    return self._trigger("_action_undo")

# Ctrl+Y / Ctrl+Shift+Z：先檢查 editor 行內 redo
if event.key() == Qt.Key_Y or (event.key() == Qt.Key_Z and (modifiers & Qt.ShiftModifier)):
    editor = self._view.text_editor
    if editor and editor.widget():
        doc = editor.widget().document()
        if doc.isRedoAvailable():
            editor.widget().redo()
            return True
    return self._trigger("_action_redo")
```

### 關鍵語意變化
| 場景 | 修復前 | 修復後 |
|------|--------|--------|
| Editor 開啟 + 有輸入 → Ctrl+Z | 轉發主視窗 undo（無效），可能觸發 focus-out | Editor 行內逐字 undo |
| Editor 開啟 + 行內 undo 空 → Ctrl+Z | 轉發主視窗 undo | 轉發主視窗 undo（行為不變） |
| Editor 未開啟 → Ctrl+Z | 轉發主視窗 undo | 轉發主視窗 undo（行為不變） |

### 風險
- **低**：邏輯清晰，fallback 行為與原本一致
- 確保 `editor.widget().undo()` 不會觸發 focus 變化

---

## Phase 3：Focus-out 競爭條件防禦（Issue #3）

### 根因
- `_finalize_if_focus_outside_edit_context()` 在 focus 離開 editor 時無條件提交
- 任何造成 focus 短暫轉移的操作（如主視窗 action trigger）都可能觸發

### 修復方案（Phase 2 修復後的防禦加固）

**方案 A（推薦）：在 shortcut forwarder 觸發主視窗 action 前後暫停 focus guard**

```python
def _trigger(self, action_name: str, fallback_name: str | None = None) -> bool:
    # === 新增：暫停 focus guard，防止 action trigger 造成的 focus 轉移觸發 finalize ===
    view = self._view
    was_guarded = getattr(view, '_edit_focus_guard_connected', False)
    if was_guarded:
        view._set_edit_focus_guard(False)

    action = getattr(view, action_name, None)
    result = False
    if action is not None and hasattr(action, "trigger"):
        action.trigger()
        result = True
    elif fallback_name:
        fallback = getattr(view, fallback_name, None)
        if callable(fallback):
            fallback()
            result = True

    # === 新增：恢復 focus guard ===
    if was_guarded and view.text_editor:
        view._set_edit_focus_guard(True)

    return result
```

**方案 B（補充）：在 focus-out finalize 時檢查是否剛觸發過 shortcut**

在 `_finalize_if_focus_outside_edit_context()` 中新增時間戳檢查：
```python
# 若 50ms 內有 shortcut forwarding，跳過 finalize
if hasattr(self, '_last_shortcut_forward_ts'):
    if (time.monotonic() - self._last_shortcut_forward_ts) < 0.05:
        return
```

### 風險
- **低**：Phase 2 修復後此問題大幅減輕
- 方案 A 是更安全的通用防禦

---

## Phase 4：Undo Stack 驗證與修復（Issue #4）

### 調查路徑

1. **確認 `sig_edit_text` 信號是否連接：**
   - `controller/pdf_controller.py` 中搜尋 `sig_edit_text.connect`
   - 確認 slot 函式 `edit_text()` 被呼叫

2. **確認 `edit_text()` 是否建立 Command 並加入 stack：**
   - `controller/pdf_controller.py` line 1440-1570
   - 確認 `self.model.command_manager.execute(cmd)` 被呼叫
   - 檢查 `CommandManager.execute()` 是否 `_undo_stack.append(cmd)`

3. **確認 Undo 按鈕 enabled 狀態更新：**
   - 搜尋 `_action_undo.setEnabled` 或 `can_undo`
   - 確認 `_update_undo_redo_tooltips()` 有更新按鈕 enabled

4. **檢查特殊情況：**
   - 是否因 Ctrl+Z 在 editor 中提前觸發了 4 次 undo，消耗掉了 stack？
   - EditTextCommand.execute() 是否有拋出 exception 但被 catch 吞掉？

### 修復策略
- 加入 logging 在 `CommandManager.execute()` 和 `edit_text()` 中
- 確認 `_update_undo_redo_tooltips()` 正確反映 stack 狀態
- 如 stack 運作正常但按鈕不更新，修復 UI 同步

---

## 實作順序

```
Phase 1 (文字重疊) ──┐
                     ├── 可同步進行，互不依賴
Phase 2 (Ctrl+Z)  ──┤
                     │
Phase 3 (focus-out) ─┘── 依賴 Phase 2 完成
                     │
Phase 4 (Undo stack) ── 獨立調查，可與 Phase 1-2 並行
```

**建議開發順序：** Phase 1 → Phase 2 → Phase 3 → Phase 4
- Phase 1 對使用者最直觀、改善最明顯
- Phase 2 + 3 一起修是最有效率的
- Phase 4 需要先調查再修

---

## 驗證計畫

每個 Phase 完成後，執行以下測試：

### Phase 1 驗證
- [ ] 開啟 editor 後，PDF 原始文字被白色遮罩蓋住
- [ ] Editor 關閉後，PDF 原始文字恢復顯示
- [ ] 拖曳 editor 時，遮罩同步移動
- [ ] Escape 放棄後，遮罩正確移除

### Phase 2 驗證
- [ ] Editor 中輸入 "ABCD" → Ctrl+Z × 4 → 全部還原，字元逐一消失
- [ ] Ctrl+Y 正確 redo
- [ ] Editor 中 undo 至空 → 再按 Ctrl+Z → 觸發主視窗 undo

### Phase 3 驗證
- [ ] Editor 中輸入 "TEST" → Ctrl+Z → Editor 仍然開啟（未自動提交）
- [ ] 輸入 "TEST" → Escape → Editor 關閉、"TEST" 被放棄
- [ ] 快速操作：type → Ctrl+Z → Escape → 確認無殘留修改

### Phase 4 驗證
- [ ] 提交文字修改後，Undo 按鈕亮起（非灰色）
- [ ] 點 Undo → 文字恢復原始內容
- [ ] 點 Redo → 修改重新套用
