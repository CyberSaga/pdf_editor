# 遇到的錯誤與解決方法

---
## 9. UI 佈局與縮放（視覺化 PDF 編輯器）

### 9.1 頂部工具列過窄，工具名稱被截斷

**問題：**  
頂部 Tab 工具列（檔案/常用/編輯/頁面/轉換）與各分頁內按鈕文字被裁切，無法完整顯示。

**原因：**  
工具列高度固定 48px、標籤與按鈕未設最小寬度與不省略，且右側固定區過寬壓縮了 Tab 區。

**有效解法（已實作）：**  
- 頂部容器改為 `setFixedHeight(60)`，避免佈局依子元件 sizeHint 再拉高。  
- Tab 標籤：`setElideMode(Qt.ElideNone)`、`min-width: 52px`、`padding: 5px 10px`，tabBar `setMinimumHeight(26)`。  
- 各分頁 QToolBar：`setToolButtonStyle(Qt.ToolButtonTextOnly)`，按鈕 `min-width: 52px`、`padding: 4px 8px`。  
- 右側固定區 `setMaximumWidth(420)`，避免壓縮左側 Tab。

**檔案：** `view/pdf_view.py`

### 9.2 頂部工具列過高、留白過多

**問題：**  
提高高度後整列過高，與文字大小不成比例。

**原因：**  
僅設 `setMinimumHeight(80)`，佈局可繼續變高；內距也偏大。

**有效解法（已實作）：**  
依字型與內距估算（約 9–10pt、標籤列 ~26px、工具列 ~26px、邊距 8px），改為 `setFixedHeight(60)`，並縮小標籤/按鈕 padding（如 5px 10px、4px 8px），使高度固定且緊湊。

**檔案：** `view/pdf_view.py`

### 9.3 右上角縮放比例選單過窄，數字被裁切

**問題：**  
縮放下拉選單（如 100%、200%）寬度不足，數字無法完整顯示。

**有效解法（已實作）：**  
對 `zoom_combo` 設定 `setMinimumWidth(88)`（或至少 72），讓百分比文字完整顯示。

**檔案：** `view/pdf_view.py`

### 9.4 縮放只影響單頁；右上角縮放選單永遠顯示 100%

**問題：**  
(1) 從下拉選單改縮放時，只有單頁被重繪，其他頁維持原比例。  
(2) 不論實際縮放倍率為何，右上角縮放選單與狀態列始終顯示 100%。

**原因：**  
- Controller 的 `change_scale(page_idx, scale)` 只呼叫 `display_page(page_idx, qpix)`，在連續模式下只更新一頁，未以新 scale 重建全部頁面。  
- 未設定 `view.scale = scale`，`_update_page_counter()` 讀到的仍是 1.0，故選單與狀態列顯示 100%。

**有效解法（已實作）：**  
在 `change_scale` 內：  
1. 先設 `self.view.scale = scale`。  
2. 若 `self.view.continuous_pages` 為 True，改為呼叫 `_rebuild_continuous_scene(page_idx)`，以 `view.scale` 重繪所有頁面。  
3. 否則維持單頁 `display_page`，並呼叫 `view._update_page_counter()` 與 `view._update_status_bar()`。  
如此所有頁面等齊縮放，且右上角選單與狀態列會顯示正確比例。

**檔案：** `controller/pdf_controller.py`

### 9.5 右上角「重做」按鈕被擠出或隱藏

**問題：**  
右上角區塊（頁 X/Y、縮放、適應畫面、復原、重做）中「重做」看不到；加大右側間距（如 200px）仍無效。

**原因：**  
- 右側區塊 `setMaximumWidth(320)` 過小，內部 QToolBar 空間不足，觸發溢出選單（»），「重做」被收進選單。  
- `right_layout` 中的 `addWidget(QWidget(), 1)` 佔滿剩餘空間，QToolBar 只得到最小寬度。  
- QToolBar 未設最小寬度，空間不足時只顯示溢出按鈕。

**有效解法（已實作）：**  
1. 放寬右側區塊：`setMaximumWidth(420)`。  
2. 移除 `right_layout` 中的 stretch（`addWidget(QWidget(), 1)`），避免把工具列擠成僅顯示溢出。  
3. 對「復原/重做」所在之 `toolbar_right` 設定 `setMinimumWidth(100)`，確保兩顆按鈕都顯示。  
右側僅保留 `addSpacing(12)` 作為留白即可。

**檔案：** `view/pdf_view.py`

---

## 10. 50 輪水平/垂直文字保留測試：誤刪與修正（2026-02）

以下為使用 `test_files/sample-files-main` 內 PDF 進行水平 50 輪 + 垂直 50 輪文字編輯保留性測試時發現的問題與有效解法。

### 10.1 Push-down 使用 TEXT_PRESERVE_LIGATURES 導致合字字元消失

**問題：**  
編輯換行溢出時，預先推移（push-down）下方文字塊後，部分未被編輯的文字在驗證時被判為「消失」（LOSS），例如 "misfits" 變成 "mits"。

**原因：**  
`_push_down_overlapping_text` 以 `page.get_text("dict", flags=TEXT_PRESERVE_LIGATURES)` 取得 span 文字，span 內含合字（如 `ﬁ`、`ﬀ`）。再用 `insert_text(fontname="helv")` 重新插入時，helv 不支援這些合字 glyph，字元被靜默丟棄，導致 push-down 後文字殘缺。

**有效解法（已實作）：**  
在取得整頁文字結構時**不使用** `TEXT_PRESERVE_LIGATURES`，僅使用 `TEXT_PRESERVE_WHITESPACE`。如此 span 文字中的合字會由 PyMuPDF 展開為一般字元（`ﬁ`→fi、`ﬀ`→ff），再以 `insert_text(helv)` 插入時可正確還原。

**檔案：** `model/pdf_model.py`（`_push_down_overlapping_text` 內 `get_text("dict", ...)` 的 flags）

---

### 10.2 垂直文字 double-redact 誤刪鄰近文字（如水平參考行）

**問題：**  
編輯垂直文字塊後，頁面下方與編輯區 X 範圍重疊的水平文字（例如 "Horizontal reference line at bottom"）的第一個字元 'H' 消失，`get_text("text")` 僅得到 "orizontal reference..."。

**原因：**  
垂直文字路徑原先流程為：在主頁面執行 Strategy A（`insert_htmlbox(insert_rect)`）→ 以 `_binary_shrink_height` 在主頁面量測最小高度 → 再對主頁面執行 `add_redact_annot(insert_rect)` + `apply_redactions()` 清除 Strategy A 的內容 → 最後以 `shrunk_rect` 再插入。其中 `insert_rect` 由 `_vertical_html_rect` 計算，X 範圍會夾緊至頁面邊界（例如 x0=0），因此 `apply_redactions(insert_rect)` 的矩形涵蓋 x∈[0, 54]，誤將 x≈50 處的水平文字一併清除。

**有效解法（已實作）：**  
垂直文字**不再**在主頁面執行「Strategy A + 清除再插入」模式。改為：  
1. 建立臨時文件與臨時頁面，在臨時頁面上執行 `insert_htmlbox(insert_rect)` 與 `_binary_shrink_height`，僅用於量測最小 `shrunk_rect`。  
2. 主頁面只執行**一次** `insert_htmlbox(shrunk_rect)` 正式插入，不再對主頁面做第二次 redact，避免大範圍 `insert_rect` 誤刪鄰近文字。

**檔案：** `model/pdf_model.py`（`edit_text` 內垂直文字分支，Strategy A / binary shrink 邏輯）

---

### 10.3 Push-down 重插時 insert_text(helv) 不支援 €、emoji 等 Unicode

**問題：**  
當被推移的文字塊內含歐元符號 `€`（U+20AC）或其它 helv 不支援的字元時，push-down 後重新插入時該字元被替換（例如 `€` 變成 `·`），導致文字保留性驗證失敗（例如 "currencyrupiaeur(€)-" 無法在頁面文字中找到）。

**原因：**  
`_push_down_overlapping_text` 以 `page.insert_text(..., fontname="helv")` 重新插入每個 span。Helvetica (Type1) 對 U+20AC 等字元無對應 glyph，PyMuPDF 會靜默替換或丟棄，造成內容變更。

**有效解法（已實作）：**  
在 `_push_down_overlapping_text` 的「批次 Insert」步驟中，改為使用 `page.insert_htmlbox(rect, html, css=css)` 取代 `insert_text`。HTML/CSS 渲染可完整支援 Unicode（含 `€`、emoji）；對每個 span 依 `origin`、`size`、`color` 估算小矩形並組出對應的 `<span style="color:...">` 與 CSS font-size，再呼叫 `insert_htmlbox`。若 `insert_htmlbox` 失敗，再回退為 `insert_text(helv)` 以維持不崩潰。

**檔案：** `model/pdf_model.py`（`_push_down_overlapping_text` 內步驟 6 批次 Insert）

---

## 11. 文字編輯框：點擊游標定位與拖曳移動（2026-02）

### 11.1 點擊文字框內會跳離編輯模式

**問題：**  
在 `edit_text` 模式下，點擊文字框內欲移動游標時，編輯框會失去焦點並結束編輯，無法在框內定位游標。

**原因：**  
`_mouse_press` 未區分「框內點擊」與「框外點擊」，一律將事件轉發或觸發 `_finalize_text_edit`，導致框內點擊也被視為結束編輯。

**有效解法（已實作）：**  
在 `_mouse_press` 中檢查點擊是否落在已開啟的 `text_editor` 邊界內；若在框內，進入 `_drag_pending` 狀態，暫不呼叫 `_finalize_text_edit`，等 `_mouse_release` 或 `_mouse_move` 再決定是游標定位（點擊）或拖曳移動。

**檔案：** `view/pdf_view.py`

---

### 11.2 focusOutEvent 遞迴呼叫風險

**問題：**  
`removeItem(text_editor)` 可能觸發 `focusOutEvent`，進而再次呼叫 `_finalize_text_edit`，造成遞迴或未預期行為。

**原因：**  
`self.text_editor` 在 `removeItem` 之後才設為 `None`，`focusOutEvent` 觸發時仍可進入 `_finalize_text_edit` 分支。

**有效解法（已實作）：**  
在 `_finalize_text_edit` 中，先將 `self.text_editor = None`，再呼叫 `removeItem(proxy_to_remove)`，避免 `focusOutEvent` 遞迴進入。

**檔案：** `view/pdf_view.py`

---

### 11.3 拖曳與編輯的文字塊判定邏輯不一致

**問題：**  
拖曳時判定「同一組文字框」的邏輯與編輯時不同；拖曳需先開啟編輯框才能移動，點擊即放開應直接開始編輯，按住拖曳應直接移動。

**原因：**  
原先設計為：有編輯框時才能拖曳；點擊新文字塊會立即開啟編輯框，無法區分「點擊編輯」與「按住拖曳」。

**有效解法（已實作）：**  
統一使用 `get_text_info_at_point` 判定文字塊。無論有無編輯框，點擊文字塊時先進入 `_drag_pending`，不立即開啟編輯框；放開（無移動）→ 開啟編輯框；拖曳（>5px）→ 建立編輯框並進入 `_drag_active` 移動。編輯框內點擊同理：放開→游標定位，拖曳→移動框。

**檔案：** `view/pdf_view.py`

---

### 11.4 文字可移動到其他頁面

**問題：**  
拖曳文字框時可能超出當前頁面邊界，甚至視覺上進入其他頁面區域。

**原因：**  
未限制編輯框的場景座標範圍。

**有效解法（已實作）：**  
新增 `_clamp_editor_pos_to_page(x, y, page_idx)`，將編輯框左上角限制在指定頁面的邊界內；`_mouse_move` 中所有拖曳更新皆呼叫此函數，確保只能在同一頁面內移動。

**檔案：** `view/pdf_view.py`

---

### 11.5 test_drag_move: PDFModel 無 open 方法

**問題：**  
`test_drag_move.py` 呼叫 `model.open(filepath)` 導致 `AttributeError: 'PDFModel' object has no attribute 'open'`。

**原因：**  
正確方法名為 `open_pdf`。

**有效解法（已實作）：**  
將 `model.open(...)` 改為 `model.open_pdf(...)`。

**檔案：** `test_scripts/test_drag_move.py`

---

### 11.6 test_drag_move: Unicode 合字導致文字驗證失敗

**問題：**  
測試 C（Moved Block Not Lost）失敗：`insert_htmlbox` 可能產生合字（如 `fi`→`ﬁ`），`_norm` 未處理，導致驗證時找不到對應文字。

**原因：**  
`_norm` 僅處理空白字元，未將合字字元展開為一般字元。

**有效解法（已實作）：**  
在 `_norm` 中加入 `_LIGATURE_MAP`（如 `\ufb01`→`fi`、`\ufb02`→`fl` 等），在標準化前先替換合字。

**檔案：** `test_scripts/test_drag_move.py`

---

### 11.7 new_rect 超出頁面時 clamp 產生無效矩形

**問題：**  
當 `new_rect` 完全在頁面外（例如 y0 > 頁高）時，clamp 後可能產生 `y0 > y1` 或 `x0 > x1` 的無效矩形，導致 `insert_htmlbox` 失敗。

**原因：**  
`_clamp` 邏輯未檢查 clamp 後的空矩形或反轉矩形。

**有效解法（已實作）：**  
在 `edit_text` 中，若 `clamped_new` 為空、無限或寬度過小，則 `logger.warning` 並退回使用原始 `target.layout_rect` 插入。

**檔案：** `model/pdf_model.py`

---

## 12. 觸控板縮放：文字模糊與編輯點擊錯位（2026-02）

### 12.1 縮放後文字變模糊

**問題：**  
以觸控板（或 Ctrl+滾輪）縮放頁面後，畫面中的文字變得模糊。

**原因：**  
`_wheel_event` 僅對 `QGraphicsView` 套用 view transform（視圖矩陣縮放），讓既有 bitmap pixmap 被拉伸/縮小，從未以新解析度重新渲染 PDF 頁面；Qt 僅做雙線性插值，導致模糊。

**有效解法（已實作）：**  
1. 在 view 新增 `_render_scale`，記錄目前場景內 pixmap 實際渲染時使用的 scale；`self.scale` 代表「期望的總縮放」，可能因 wheel 超前於重渲。  
2. 新增 debounce timer（300ms）：wheel 停止後 300ms 再觸發重渲，避免連續滾動時每幀都重渲。  
3. 新增 signal `sig_request_rerender`；Controller 連接後在 `_on_request_rerender` 呼叫 `_rebuild_continuous_scene(current_page)`，以當前 `view.scale` 重新渲染所有頁面。  
4. 在 `display_all_pages_continuous` 重建場景後：設 `_render_scale = self.scale`，並呼叫 `graphics_view.setTransform(QTransform())` 將 view transform 重設為 identity（scale 已烘焙進 pixmap）。

**檔案：** `view/pdf_view.py`、`controller/pdf_controller.py`

---

### 12.2 縮放後編輯模式點擊文字位置無法觸發編輯框

**問題：**  
進入編輯模式後，在縮放過的頁面上點擊文字位置，無法觸發編輯文字框；或點擊位置與實際文字塊對應錯誤。

**原因：**  
座標轉換時除以 `self.scale`（view 的總縮放），但場景座標實際為「PDF 點 × 實際渲染 scale」（即 `_render_scale`）。縮放後 `self.scale` 已更新而 pixmap 尚未重渲時，`self.scale ≠ _render_scale`，導致 `doc_x = scene_x / self.scale` 錯誤（雙重除算或除錯倍率）。

**有效解法（已實作）：**  
所有「場景座標 → PDF 座標」或「PDF 座標 → 場景座標」的換算一律使用 `_render_scale`，不再使用 `self.scale`：  
- `_scene_pos_to_page_and_doc_point`：`doc_x = scene_x / _render_scale`（及 y、y0 同理）。  
- `_update_hover_highlight`：將 `doc_rect` 轉為場景矩形時乘以 `_render_scale`。  
- `_create_text_editor`：`scaled_width`、`scaled_rect` 使用 `_render_scale`。  
- `_clamp_editor_pos_to_page`：頁面寬高與邊界計算使用 `_render_scale`。  
- `_mouse_release` 拖曳結束時，proxy 位置轉回 PDF 座標使用 `_render_scale`。  
並以 `rs = self._render_scale if self._render_scale > 0 else 1.0` 防呆。

**檔案：** `view/pdf_view.py`

---

## 13. 註解與浮水印相關（2026-02）

### 13.1 編輯文字後 FreeText / Highlight 註解消失

**問題：**  
執行 `edit_text` 後，同一頁面上與編輯區重疊的 FreeText、螢光筆等註解被一併清除。

**原因：**  
`page.apply_redactions()` 會刪除 redact 矩形內的所有內容，包含與該矩形重疊的 annotation（PyMuPDF 預設行為）。

**有效解法（已實作）：**  
在 `edit_text` 內呼叫 `apply_redactions` 前，以 `_save_overlapping_annots(page, redact_rect)` 擷取與 redact 矩形重疊的非 redact 類型註解；`apply_redactions` 後以 `_restore_annots(page, saved)` 還原（支援 FreeText、Highlight、Square、Circle、Underline、Strikeout）。

**檔案：** `model/tools/annotation_tool.py`（`_save_overlapping_annots`、`_restore_annots`）與 `model/pdf_model.py`（`edit_text` 中委派呼叫）

---

### 13.2 壞損 annotation xref 導致 page.annots() 拋錯、edit_text 失敗

**問題：**  
部分 PDF（如 024-annotations/annotated_pdf.pdf）內含無效 xref 的 annotation，迭代 `page.annots()` 時拋出 `AttributeError: 'NoneType' object has no attribute 'm_internal'`，導致 `_save_overlapping_annots` 與整次 `edit_text` 失敗。

**原因：**  
PyMuPDF 在載入損壞或非標準的 annot 時可能回傳 None，未做防呆即存取屬性會崩潰。

**有效解法（已實作）：**  
在 `_save_overlapping_annots` 中：對 `page.annots()` 的呼叫包在 try/except 中，失敗則回傳空列表；對每個 annot 的屬性存取也包在 try/except 中，單一損壞 annot 跳過並記錄 warning，不中斷整次編輯。

**檔案：** `model/tools/annotation_tool.py`（`_save_overlapping_annots`）

---

### 13.3 浮水印重開檔後無法再編輯（get_watermarks() 為空）

**問題：**  
儲存含浮水印的 PDF 後，重新開檔時 `get_watermarks()` 回傳空列表，無法在 UI 中繼續編輯或刪除浮水印。

**原因：**  
浮水印在 `save_as` 時僅繪入 PDF 內容流，`watermark_list` 為 Model 記憶體狀態，未將元數據寫入 PDF，開檔時無從還原。

**有效解法（已實作，方案 B）：**  
儲存時將 `watermark_list` 序列化為 JSON，以 PDF 內嵌檔案（`__pdf_editor_watermarks`）寫入；開檔時在 `open_pdf` 內呼叫 `_load_watermarks_from_doc(self.doc)` 讀取該內嵌檔並還原 `watermark_list`。支援重新開檔後仍可編輯/刪除浮水印。

**檔案：** `model/tools/watermark_tool.py`（`_load_watermarks_from_doc`、`_write_watermarks_embed`）與 `model/pdf_model.py`（`open_pdf`/`save_as` 的工具掛鉤）

---

1. **test_03_multi_tab plan 文字驗證失敗**  
   錯誤：`test_03_edit_in_a_undo_in_b_isolated` 期待 `edited_atoken`，但實際文本為 `edited_a_token`（含底線）。  
   解法：更新測試預期為 `_norm` 轉換後的 `edited_a_token`，避免因字串標準化差異而誤判。

2. **Ctrl+Tab 會切換到工具欄 / 側邊欄標籤**  
   錯誤：新增的文件分頁列與 Qt 預設快捷鍵並存，導致在工具區或左側欄時仍被 `QTabWidget` 內部的 `Ctrl+Tab` 撥弄，非預期切換到其它 UI。  
   解法：  
   - 在 `PDFView` 中建立 `_NoCtrlTabTabBar`，強制攔截 `Ctrl+Tab`/`Ctrl+Shift+Tab`，並呼叫 `PDFView` 提供的 `_cycle_document_tab`。  
   - 將頂部工具欄與左側側邊欄用此自訂 `QTabBar`，並在主窗體內透過 `QShortcut` 及統一 `direction` 解析器只在文件分頁列上切換。  
   - 補上相關 UI 測試來驗證非文件區域的快捷鍵不會影響文件分頁。

3. **「適應畫面」會縮到顯示全部頁面**  
   錯誤：`_fit_to_view` 直接套用 `scene.sceneRect()`，而連續模式的 scene 包含全部頁，結果把視窗縮到最小。  
   解法：改成以當前頁的 `sceneBoundingRect()` 為目標，沒有頁面時才 fallback。這樣單一頁面會被放大以填滿視窗，連續模式也只會對當前頁縮放，再加上新的成功驗證測試。

---

# Solutions (Text Editing / Textboxes)

This section is appended by Codex and only covers textbox/text editing problems solved in this chat.

## 1. Editing One Textbox Clears Other Overlapping Text

Problem:
- Editing a textbox could clear other overlapping text at the same (x, y).

Root cause:
- Targeting/deletion was geometry-based (rect overlap).
- Redaction deletes everything inside the redacted area.

Effective solution (implemented):
- Identity-scoped, transactional overlap-safe edit:
- Build span-level index with stable span_id: p{page}_b{block}_l{line}_s{span}.
- Propagate target_span_id end-to-end (View -> Controller -> Command -> Model).
- In edit_text: resolve by target_span_id, build overlap cluster, redact once, replay protected spans, insert new text, verify; rollback via page snapshot on failure.

## 2. Overlap Edit Error: need font file or buffer

Problem:
- Protected-text replay during overlap edits could raise: need font file or buffer.

Root cause:
- Some extracted font names are not directly usable for insertion.

Effective solution (implemented):
- Make protected replay font-robust:
- Resolve font name, try fallbacks (CJK: china-ts, helv; non-CJK: helv, tiro, cour).
- Last fallback uses insert_htmlbox for better tolerance.

## 3. Bad Textbox Splitting (e.g. young -> y + oung)

Problem:
- Extraction sometimes split text into unreasonable fragments, hurting selection accuracy.

Root cause:
- High-level span boundaries can be unstable (ligatures/kerning/encoding/render order).

Effective solution (implemented):
- Char-level reconstruction from page.get_text('rawdict'):
- Build runs/paragraphs from per-char geometry when available.
- Add hybrid targeting via target_mode=run|paragraph.

## 4. Paragraph Drag Edit Rollback: target_present=False

Problem:
- Dragging a whole paragraph could repeatedly fail verification and rollback (target_present=False).

Root cause:
- Paragraph edits can interleave with protected replay text and extraction artifacts; exact substring checks are brittle.

Effective solution (implemented):
- Paragraph-mode tolerant verification:
- Use full-page normalized checks plus fuzzy metrics (ratios + token coverage) with paragraph-specific thresholds.
- Keep transactional rollback when verification truly fails.

## 5. Undo/Redo Determinism Under Overlap

Problem:
- Rect-based redo could re-target a different overlapped span after rebuild.

Root cause:
- Geometry-only targeting is not deterministic under overlap/extraction ordering changes.

Effective solution (implemented):
- Store target_span_id (and target_mode) in EditTextCommand so redo is deterministic.

---

## 6. Printing Refactor (2026-02): Unified Print Dialog + Preview

### 6.1 Print Dialog Return Code Crash: missing Accepted attribute

Problem:
- Clicking "Print" raised: `'UnifiedPrintDialog' object has no attribute 'Accepted'`.

Root cause:
- Controller compared dialog result via `self._print_dialog.Accepted`, but `Accepted` is not an instance attribute in PySide6.

Effective solution (implemented):
- Compare against Qt enum: `QDialog.DialogCode.Accepted`.

Files:
- `controller/pdf_controller.py`

### 6.2 Printer Capability Probe Crash: QPageSize id int() TypeError

Problem:
- Opening the print dialog could crash with: `TypeError: int() argument must be ... not 'PageSizeId'`.

Root cause:
- Code attempted `int(QPageSize.A4)` and compared to `supportedPageSizes().id()` values (enum mismatch).

Effective solution (implemented):
- Compare enum values directly (e.g. `size_id == QPageSize.A4`) without `int()`.

Files:
- `src/printing/print_dialog.py`

### 6.3 Print Preview vs. Output Drift Risk (Page Selection / Scaling)

Problem:
- High risk: preview showing different pages/scale than actual printed output.

Root cause:
- Separate logic paths for preview and print tend to diverge over time.

Effective solution (implemented):
- Shared logic modules used by both preview and submission:
- `page_selection.resolve_page_indices()` for `page_ranges + odd/even + reverse`.
- `layout.compute_target_draw_rect()` for scaling + centering.

Files:
- `src/printing/page_selection.py`
- `src/printing/layout.py`
- `src/printing/dispatcher.py`
- `src/printing/qt_bridge.py`
- `src/printing/print_dialog.py`

### 6.4 Preview Performance Regression Risk: unbounded image cache

Problem:
- Preview image caching could grow without bound during long sessions (higher memory usage).

Root cause:
- Cache dictionary had no eviction policy.

Effective solution (implemented):
- Add a small cap (24 entries) and evict oldest entries when exceeded.

Files:
- `src/printing/print_dialog.py`

### 6.5 Default PPI unexpectedly changed by printer capability sync

Problem:
- Default PPI (300) could be overridden immediately when selecting a printer.

Root cause:
- Capability sync code "snapped" current DPI to a supported value even when user hadn't chosen anything.

Effective solution (implemented):
- Do not auto-adjust DPI on printer change; keep default 300 unless user explicitly changes it.

Files:
- `src/printing/print_dialog.py`

### 6.6 test_script import failure: ModuleNotFoundError: No module named 'src'

Problem:
- Running `python test_scripts/test_print_dialog_logic.py` failed to import project modules.

Root cause:
- Script didn't add repository root to `sys.path` when launched from `test_scripts/`.

Effective solution (implemented):
- Insert repo root into `sys.path` at runtime (same pattern as existing scripts).

Files:
- `test_scripts/test_print_dialog_logic.py`

---

## 7. Large PDF Open: ~30s Blocked, Cannot Operate

Problem:
- Opening a large PDF (e.g. 39 MB, 402 pages) caused ~30 seconds of no response; user could not operate until about two-thirds of indexes were built.

Root cause:
- Thumbnail, scene, and index batch loading all ran in parallel on the main thread from open. Index building (`ensure_page_index_built` / `rebuild_page`) is CPU-heavy; together with scene batches it saturated the event loop so clicks and scrolls were not processed.

Effective solution (implemented):
- Defer index building until the continuous scene is fully loaded. At open, start only thumbnail and scene timers; when the last scene batch completes (`end >= n`), then call `_schedule_index_batch(0, gen)`. Use smaller batch sizes (e.g. scene 3, thumb 10, index 5) and intervals so the main thread yields more often. Model: do not call `build_index(self.doc)` in `open_pdf`; Controller builds index in batches after scene is done.

Files:
- `controller/pdf_controller.py`
- `model/pdf_model.py`

---

## 8. Cannot Scroll or Jump by Clicking Thumbnails (After Batch Loading)

Problem:
- After the speed fix, user still could not scroll the document or jump to a page by clicking a thumbnail.

Root cause:
- At open, `display_page(0, qpix)` used the single-page branch and called `graphics_view.setSceneRect(scene.itemsBoundingRect())`, locking the view’s scene rect to that one page. Later, `display_all_pages_continuous` and `append_pages_continuous` only updated `scene.setSceneRect(...)` and never updated the view’s scene rect, so the view still treated the scrollable area as the initial single page; scroll bar and visible region did not cover the full document.

Effective solution (implemented):
- After every scene rect update, set the view’s rect to match: in `display_all_pages_continuous` and in `append_pages_continuous` (when appending), call `graphics_view.setSceneRect(scene.sceneRect())`. When the user requests a page that is not yet loaded, clamp to the last loaded page: in `scroll_to_page` clamp `page_idx` to `min(page_idx, len(page_y_positions)-1)` when `page_idx >= n_pos`; in Controller `show_page`, if `page_idx >= len(page_items)` call only `scroll_to_page(n_loaded - 1)` and return (do not call `get_page_pixmap` for the out-of-range page).

Files:
- `view/pdf_view.py`
- `controller/pdf_controller.py`

---

## 附錄：所有問題與有效解法一覽

| # | 問題簡述 | 有效解法簡述 |
|---|----------|--------------|
| 9.1 | 頂部工具列過窄、工具名稱被截斷 | 固定高度 60、Tab/按鈕 min-width、右側 setMaximumWidth(420) |
| 9.2 | 頂部工具列過高、留白過多 | setFixedHeight(60)、縮小標籤/按鈕 padding |
| 9.3 | 縮放比例選單過窄、數字被裁切 | zoom_combo setMinimumWidth(88) |
| 9.4 | 縮放只影響單頁、選單永遠 100% | change_scale 先設 view.scale、連續模式 _rebuild_continuous_scene |
| 9.5 | 右上角「重做」按鈕被擠出或隱藏 | 放寬右側、移除 stretch、toolbar_right setMinimumWidth(100) |
| 10.1 | Push-down 合字消失 | get_text("dict") 不用 TEXT_PRESERVE_LIGATURES |
| 10.2 | 垂直文字 double-redact 誤刪水平文字 | 垂直文字改在臨時頁量測，主頁只插入一次 |
| 10.3 | Push-down 不支援 €/emoji | 改用 insert_htmlbox 批次插入受保護 span |
| 11.1 | 點擊框內會跳離編輯 | 框內點擊設 _drag_pending，區分點擊與框外 |
| 11.2 | focusOutEvent 遞迴 | 先設 text_editor=None 再 removeItem |
| 11.3 | 拖曳與編輯判定不一致 | 統一用 get_text_info_at_point，先 _drag_pending 再決定開框/拖曳 |
| 11.4 | 文字可拖到其他頁 | _clamp_editor_pos_to_page 限制在同一頁 |
| 11.5 | test_drag_move 呼叫 model.open | 改為 model.open_pdf |
| 11.6 | 合字導致驗證失敗 | _norm 內加入 _LIGATURE_MAP 展開合字 |
| 11.7 | new_rect clamp 後無效矩形 | 若 clamp 後空/反轉則退回用 layout_rect |
| 12.1 | 縮放後文字模糊 | _render_scale、debounce 重渲、sig_request_rerender、scale 烘焙進 pixmap |
| 12.2 | 縮放後點擊無法觸發編輯 | 座標換算一律用 _render_scale 取代 self.scale |
| 13.1 | edit_text 後註解消失 | _save_overlapping_annots / _restore_annots |
| 13.2 | 壞損 annot xref 導致 annots() 崩潰 | try/except 包住 annots() 與單一 annot 存取 |
| 13.3 | 浮水印重開後不可編輯 | 方案 B：內嵌檔案存/讀 watermark_list JSON |
| 1 | test_03 文字驗證期待與 _norm 結果不一致 | 更新測試預期為標準化後字串 |
| 2 | Ctrl+Tab 切到工具欄/側邊欄 | 自訂 TabBar 攔截、統一在文件分頁上切換 |
| 3 | 「適應畫面」縮到顯示全部頁 | 以當前頁 sceneBoundingRect 為目標 |
| 4.1 | 編輯一文字框清除其他重疊文字 | 以 span_id 定址、overlap cluster、redact 一次、replay 受保護 span |
| 4.2 | 受保護文字 replay：need font file or buffer | 字體 fallback（CJK/非 CJK）+ insert_htmlbox 最後回退 |
| 4.3 | 文字框被不合理切分 | 從 rawdict 字元級重建 run/paragraph，hybrid target_mode |
| 4.4 | 段落拖曳驗證 target_present=False | 段落模式寬鬆驗證（fuzzy + token coverage） |
| 4.5 | Undo/Redo 重做時目標不確定 | EditTextCommand 儲存 target_span_id，redo 依 ID 定址 |
| 6.1 | 列印對話框 Accepted 屬性不存在 | 使用 QDialog.DialogCode.Accepted |
| 6.2 | QPageSize id int() TypeError | 直接比較 enum，不轉 int |
| 6.3 | 預覽與實際輸出頁/縮放不一致 | 共用 page_selection、layout、dispatcher 邏輯 |
| 6.4 | 預覽圖快取無上限 | 快取上限 24 筆、evict 最舊 |
| 6.5 | 預設 PPI 被印表機能力覆寫 | 不隨印表機變更自動調整 DPI |
| 6.6 | test_script 找不到 src 模組 | 將 repo root 加入 sys.path |
| 7 | 大 PDF 開啟約 30s 無回應 | 延後 index 建立、批次載入、縮小 batch 讓出 main thread |
| 8 | 縮放修復後仍無法捲動/點縮圖跳頁 | 更新 view.sceneRect 與 scene 一致、clamp 未載入頁 |
