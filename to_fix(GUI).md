# PDF Editor — To Fix

> **專案目標**：把 PDF 文字編輯做得更接近 Acrobat 的體驗：不要誤刪鄰近內容、不要 silent-fail、不要編輯框和落點跳動，且新文字要盡量維持原本樣式與閱讀順序。

**分析日期**：2026-03-25
**分析方式**：完整靜態程式碼審查 + GUI 實機操作測試（TIA-942-B-2017 Rev Full.pdf，150% 縮放）
**測試檔案**：`test_files/TIA-942-B-2017 Rev Full.pdf`

---

## 目前狀態摘要

| 狀態 | 數量 |
|------|------|
| CRITICAL severity（GUI 實測發現） | 1 |
| HIGH severity（靜態分析 + GUI 確認） | 5 |
| MEDIUM severity（仍存在） | 8 |
| LOW severity | 2 |
| 已修復 | 1（@dataclass slots=True） |
| **總計待修復** | **16** |

---

## ⚠️ GUI 實機測試發現（2026-03-25，TIA-942-B-2017）

> 測試環境：mac，150% 縮放，「組織文字」模式，TIA-942-B-2017 Rev Full.pdf

### G1 — 【CRITICAL】單擊文字塊後點別處，**即使沒有編輯**也觸發 finalize → ghost text

**這是目前最嚴重的 Bug，直接導致「誤刪鄰近內容」的核心問題。**

- **觸發方式**（穩定重現）：
  1. 切換到「編輯 > 組織文字」模式
  2. 點擊任意段落文字塊（只是選取，未修改任何文字）
  3. 點擊頁面其他空白位置（觸發 focus-out finalize）

- **觀察到的結果**：
  - 頁面 2 的 blocks：83 → **84**，spans：376 → **383**（空操作多出 7 個 span）
  - 原始段落的部分 spans 殘留為小字 ghost text，浮在重建文字之間
  - 狀態列顯示「已修改 *」（文件被標記為有改動）

- **Terminal 確認**：
  ```
  overlap_redaction page=2 protected_count=0 redact_rect=Rect(36.0, 85.24...)
  換行預估溢出 29.3pt；預先推...
  _push_down_overlapping_text
  page 2: 84 blocks, 383 spans
  編輯文字成功：頁面 2, block...
  edit_transaction rollback_flag=False duration_ms=75.6
  ```

- **根本原因**：`_finalize_text_edit_impl` 未在提交前確認文字是否實際被修改，導致「無改動但仍執行 edit_transaction」。`redact_rect` 清除區域未完整涵蓋所有原始 spans，殘留 spans 成為 ghost text。

- **修復方向**：finalize 入口加入「dirty 檢查」：
  ```python
  if not self._editor_is_dirty():
      self._close_editor_without_save()
      return
  ```

---

### G2 — 【HIGH】150% 縮放下選取疊加層向下偏移 ~3–5px（Bug #1/#8 視覺確認）

- **觸發方式**：縮放到 150%，在「組織文字」模式下點擊文字塊
- **觀察**：選取框（inverted text overlay）與原始 PDF 文字有明顯位移，形成雙重文字視覺（見下圖）
- **確認**：此為靜態分析 Bug #1 的 GUI 直接確認

---

### G3 — 【MEDIUM】Ctrl+Z 無效，復原必須用工具列「復原」按鈕

- **觸發方式**：任何編輯操作後按 Ctrl+Z
- **觀察**：無 terminal 輸出，未觸發 undo，文件仍顯示「已修改」
- **工具列「↺ 復原」**：可正常 undo（terminal 輸出 `EditTextCommand.undo()`, 頁面恢復 83 blocks）
- **修復方向**：確認 QShortcut("Ctrl+Z") 是否正確綁定到 CommandManager.undo()

---

### G4 — 【LOW】頁碼計數器不即時更新

- **觀察**：捲動到頁 2（NOTICE 頁）後，工具列仍顯示「1 / 402」，未更新為「2 / 402」
- **嚴重度**：LOW — 視覺 UX 問題，不影響核心功能

---

## HIGH Severity

### #1 — `_render_scale` vs `self.scale` desync：annotation 座標落點錯位

- **位置**：`view/pdf_view.py` 第 3203–3204 行
- **問題**：高亮/矩形工具繪製完成後，將螢幕座標轉換為 PDF 座標時使用 `self.scale`（目標縮放值），而非 `self._render_scale`（當前實際渲染縮放值）。Wheel 縮放的 debounce 期間兩者不同步，導致繪製的 annotation 落點偏離視覺位置。

```python
# 現況（錯誤）
fitz_rect = fitz.Rect(rect.x() / self.scale, (rect.y() - y0) / self.scale, ...)

# 應改為
rs = self._render_scale if self._render_scale > 0 else 1.0
fitz_rect = fitz.Rect(rect.x() / rs, (rect.y() - y0) / rs, ...)
```

- **修復方向**：所有螢幕→PDF 座標轉換一律改用 `_render_scale`，與 `self.scale` 脫鉤。

---

### #6 / #15 — 跨頁拖曳 `page_idx` 固定未更新，Y-offset 計算錯誤

- **位置**：`view/pdf_view.py` 第 2784 行（拖曳移動）、第 3182 行（finalize）
- **問題**：拖曳開始時記錄 `_editing_page_idx`（起始頁），拖曳過程中 Y 座標轉換仍以起始頁的 `page_y_positions` 為基準。當用戶把文字從第 N 頁拖到第 N+1 頁時，`page_y_positions` 偏移量算錯，文字最終落點偏離視覺位置。

```python
# 現況（錯誤）—page_idx 固定為起始頁
page_idx = getattr(self, '_editing_page_idx', self.current_page)
new_x, new_y = self._clamp_editor_pos_to_page(raw_x, raw_y, page_idx)

# 應改為—動態更新 page_idx
if self.continuous_pages:
    page_idx = self._scene_y_to_page_index(raw_y)
    self._editing_page_idx = page_idx
new_x, new_y = self._clamp_editor_pos_to_page(raw_x, raw_y, page_idx)
```

- **修復方向**：`mouseMoveEvent` 拖曳路徑中，根據當前滑鼠 Y 座標即時計算 `page_idx`，並更新 `_editing_page_idx`。

---

### #8 — Zoom debounce 期間開啟編輯框，位置和寬度計算用到舊 `_render_scale`

- **位置**：`view/pdf_view.py` 第 3235–3236 行（編輯框初始化）
- **問題**：`_render_scale` 在頁面重新渲染完成後才更新（`_on_request_rerender`）。若用戶在 debounce 期間（wheel 縮放後約 200ms）雙擊開啟編輯框，編輯框的初始位置與寬高使用舊的 `_render_scale`，導致編輯框與文字不對齊。

```python
# 修復方向：編輯框建立前強制同步 scale
rs = self._render_scale if self._render_scale > 0 else max(0.1, float(self.scale))
# 或：zoom 進行中時禁止建立新編輯框
if self._zoom_in_progress:
    return
```

---

### #14 — Highlight / Rect 座標轉換混用 `self.scale`（與 #1 同源，但獨立路徑）

- **位置**：`view/pdf_view.py` 第 3203–3204 行
- **問題**：這是 annotation 工具（高亮、矩形）的座標轉換路徑，與文字編輯框路徑分離，需獨立修復。任何縮放後立即繪製 annotation 均會落點偏移。
- **修復**：同 #1，改用 `_render_scale`。

---

## MEDIUM Severity

### #2 / #18 — `position_changed` 閾值 0.5pt 過大，細微移動 silent drop

- **位置**：`view/pdf_view.py` 第 3451–3452 行
- **問題**：`position_changed` 判斷閾值為 `> 0.5`（PDF points）。在 2× 縮放下，0.5pt ≈ 1 像素；用戶拖曳 1px 以內的微小距離會被靜默忽略，位置更新不寫入。
- **修復**：將閾值從 `0.5` 降至 `0.1`，或改為 `> 0`（完全無閾值）。

```python
# 現況
(abs(current_rect.x0 - original_rect.x0) > 0.5 or ...)
# 建議
(abs(current_rect.x0 - original_rect.x0) > 0.1 or ...)
```

---

### #3 — Double-finalize race condition（focus-out + app focus-changed 競爭）

- **位置**：`view/pdf_view.py` 第 2154 行（`_on_app_focus_changed`）、第 2159 行（`_on_editor_focus_out`）
- **問題**：兩個事件均呼叫 `_schedule_finalize_on_focus_change()`，雖有 `_edit_focus_check_pending` 去重，但 QTimer(40ms) 排程的 finalize 回呼在清除 flag 後、下一事件觸發前仍有短暫視窗，快速操作下仍可能觸發兩次 finalize（第 2 次被 `_finalizing_text_edit` guard 攔截，但編輯狀態可能已部分清除）。
- **修復方向**：合併為單一 finalize 入口，使用一個可重置的 QTimer，而非兩個獨立 timer。

---

### #5 / #11 — 多色段落顏色丟失（`EditableParagraph` 只存主色）

- **位置**：`model/text_block.py` 第 749、763 行（建立），第 132–147 行（資料結構定義）
- **問題**：`EditableParagraph` 只儲存 `color: tuple`（paragraph 最常見色），編輯完成後所有 span 均套用同一顏色，多色段落（如部分紅色強調、藍色連結）顏色遭覆蓋。

```python
# 現況（text_block.py ~line 749）
dominant_color = color_counter.most_common(1)[0][0]
# ...
color=tuple(dominant_color),  # 丟失 per-run 顏色

# 修復方向：EditableParagraph 增加 run_colors 欄位
@dataclass
class EditableParagraph:
    color: tuple        # 保留（向後相容）
    run_colors: list[tuple] = field(default_factory=list)  # 新增：配對 run_ids
```

- **修復步驟**：
  1. `EditableParagraph` 增加 `run_colors: list[tuple]`
  2. 建立時逐 run 收集顏色填入 `run_colors`
  3. 儲存時逐 run 套用對應顏色，而非用段落主色

---

### #7 — Position-only drag：silent rollback，用戶看不到反饋

- **位置**：`view/pdf_view.py` 第 3523–3542 行（`_finalize_text_edit_impl`）
- **問題**：若只移動位置（text/font/size 不變），`sig_edit_text` 會發出，但若後續 model 的 validation 失敗（如字數對不上），整個操作靜默回滾，文字彈回原位，用戶無任何提示。
- **修復方向**：validation 失敗後在 status bar 或對話框顯示具體原因，並保留用戶最後一次移動位置供重試。

---

### #9 / #12 — `_replay_protected_spans` / `_validate_protected_spans` 失敗無用戶反饋

- **位置**：`model/pdf_model.py` 第 2126–2225 行（`_replay_protected_spans`）、第 2218–2225 行（`_validate_protected_spans`）
- **問題**：多個失敗路徑（HTML 解析失敗、字體候選失敗、htmlbox 失敗）只記 `DEBUG` 或 `WARNING` log，不通知用戶。最終 `_validate_protected_spans` 回傳 False 時，整個 `edit_text()` 回滾，用戶看不到：
  - 哪個 span 出問題（span ID）
  - 失敗原因（字體？HTML？）
  - 任何重試或忽略選項

```python
# 現況（僅 log，無用戶反饋）
logger.warning("protected span missing after replay: %s", span.span_id)
return False

# 修復方向
failed_spans.append(span.span_id)
# ...後在 controller 層顯示：
# "以下 span 儲存失敗：[span_id]，建議手動重建或忽略。"
```

---

### #16 — 編輯框 finalize 時 `orig.width/height` 單位混淆

- **位置**：`view/pdf_view.py` 第 3185–3190 行
- **問題**：`orig.width` 已是 PDF 座標（points），但 fallback 值 `100 / rs` 混入了螢幕→PDF 的除法，邏輯不一致。正常路徑下（`orig` 存在）不影響結果，但若 `orig` 為 None（新增文字塊），fallback 尺寸可能算錯。

```python
# 現況
orig_w = orig.width if orig else 100 / rs  # 單位混淆

# 應改為
orig_w = orig.width if orig else 100.0  # fallback 直接用 PDF 座標 points
```

---

### #17 — `_clamp_editor_pos_to_page` 不支援動態 page_idx，跨頁拖曳無法正確 clamp

- **位置**：`view/pdf_view.py` 第 3067–3094 行
- **問題**：函數只接收固定 `page_idx`，無法根據 Y 座標自動判斷應 clamp 到哪一頁。配合 #6 的修復，這裡也需要同步修改。
- **修復方向**：

```python
def _clamp_editor_pos_to_page(self, x, y, page_idx=None):
    if page_idx is None and self.continuous_pages:
        page_idx = self._scene_y_to_page_index(y)
    # ... 其餘邏輯不變
```

---

### #19 — Viewport restore 雙 timer（0ms + 180ms）可能造成視埠跳位

- **位置**：`controller/pdf_controller.py` 第 1545–1546 行
- **問題**：連續兩個 `QTimer.singleShot` 還原視埠，若兩次呼叫之間頁面尺寸已更新，第 2 次 restore 會覆蓋用戶的手動滾動，造成視埠跳位。

```python
# 現況
QTimer.singleShot(0, lambda a=anchor: self.view.restore_viewport_anchor(a))
QTimer.singleShot(180, lambda a=anchor: self.view.restore_viewport_anchor(a))

# 建議改為單一 timer + 判斷是否需要重試
QTimer.singleShot(20, lambda a=anchor: self._restore_viewport_with_retry(a))
```

---

## LOW Severity

### #13 — DEBUG log 過多，潛在效能問題

- **位置**：`view/pdf_view.py` 多處（如第 269–272、2829、3109、3185 等行）
- **問題**：渲染迴圈中有大量 `logger.debug()` 呼叫，若 logging level 設為 DEBUG，I/O 可能拖慢 render loop（尤其大型 PDF）。
- **修復方向**：加 `if logger.isEnabledFor(logging.DEBUG):` 條件守衛，或在 production build 移除冗餘 debug 訊息。

---

## 修復優先順序

| 優先度 | Bug ID | 核心問題 | 影響場景 |
|--------|--------|----------|----------|
| **P0** | **G1** | **無改動也觸發 finalize → ghost text（每次單擊都損壞文件）** | **所有文字塊操作** |
| P0 | #1, #14, G2 | 座標轉換混用 scale（選取框 150% 下偏移確認） | 所有縮放狀態下的操作 |
| P0 | #6, #15 | 跨頁拖曳 page_idx 固定 | 連續頁面模式跨頁移動 |
| P1 | #8 | zoom debounce 期間編輯框錯位 | 縮放後立即雙擊 |
| P1 | #5, #11 | 多色段落顏色丟失 | 所有段落含多色 run 的情況 |
| P2 | G3 | Ctrl+Z 無效 | 任何編輯後想快速復原 |
| P2 | #9, #12 | silent-fail 無用戶反饋 | 特殊字體/CJK 文字編輯 |
| P2 | #7 | position-only drag silent rollback | 純移動操作 |
| P3 | #2, #18 | 細微移動 silent drop | 精細定位操作 |
| P3 | #3 | double-finalize race | 快速點擊切換操作 |
| P3 | #16 | fallback 尺寸單位混淆 | 新增文字塊 |
| P3 | #17 | _clamp 不支援動態 page | 與 #6 配套修復 |
| P4 | #19 | viewport 雙 timer 跳位 | 編輯後視埠還原 |
| P4 | G4 | 頁碼計數器不更新 | 多頁捲動瀏覽 |
| P4 | #13 | debug log 效能 | 大型 PDF |

---

## 驗證清單（修復後需測試）

**核心場景（GUI 實測確認有問題，修復後必測）：**
- [ ] **[G1]** 組織文字模式 → 點擊文字塊 → **不做任何修改** → 點擊空白處 → blocks/spans 數量**不增加**，文件狀態**不顯示「已修改」**
- [ ] **[G1]** 組織文字模式 → 點擊文字塊 → 點擊空白處 → **無 ghost text 出現**
- [ ] **[G2]** 縮放到 150% → 點擊文字塊 → 選取框**精確覆蓋**文字，無偏移
- [ ] **[G3]** 任何編輯後按 Ctrl+Z → 成功復原
- [ ] **[G4]** 捲動到第 2 頁 → 頁碼顯示「2 / N」

**其他場景：**
- [ ] 縮放到 150% → 拖曳文字塊 → 落點與視覺位置一致
- [ ] 縮放到 150% → 繪製高亮 → 高亮框精確覆蓋文字
- [ ] 連續頁面模式 → 把第 1 頁文字拖到第 2 頁 → Y 座標正確
- [ ] Wheel 縮放後 100ms 內雙擊文字 → 編輯框位置正確
- [ ] 雙擊多色段落 → 編輯 → 儲存 → 各 run 顏色保留
- [ ] 拖曳移動 < 0.5pt 距離 → 位置有更新
- [ ] 特殊字體 span validation 失敗 → 顯示具體失敗 span ID
- [ ] 拖曳後點空白處 finalize → 無 double-finalize、無 silent rollback
- [ ] 新增文字塊 → 尺寸正確（fallback 路徑）
- [ ] 大型 PDF（TIA-942-B-2017）→ 滾動流暢，無 log 卡頓

---

## 附錄：已修改項目（供參考）

| 問題 | 修復時間 | 修復內容 |
|------|----------|----------|
| `@dataclass(slots=True)` Python 3.9 不相容（原規劃以 Python 3.10 開發） | 2026-03-24 | 改為 `@dataclass`（base_driver.py, pdf_renderer.py, helper_protocol.py, print_dialog.py）|
