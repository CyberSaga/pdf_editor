# PDCA：水平文字編輯超出頁面邊界

## Plan（計畫）

**問題**：編輯水平文字時，文字超出頁面右緣並被裁切。

**根因分析**：
1. `insert_htmlbox` 的字型度量可能使實際渲染超出 rect 右緣
2. 固定 25pt 右邊距對大字級（如 48pt）不足
3. 編輯框預覽與 PDF 渲染的寬度計算不一致

**對策**：
1. 依字級動態計算右邊距：`max(60, min(120, size*2))` pt
2. 水平文字 render 後呼叫 `clip_to_rect(page.rect)` 作為安全網
3. `get_render_width_for_edit` 新增 `font_size` 參數，與 edit_text 一致
4. 修復 `currentTextChanged.disconnect` 的 RuntimeWarning

## Do（執行）

- [x] `model/pdf_model.py`：right_margin_pt 改為依 size 計算
- [x] `model/pdf_model.py`：水平分支結束前加入 `temp_page.clip_to_rect(temp_page.rect)`
- [x] `model/pdf_model.py`：`get_render_width_for_edit` 新增 `font_size` 參數
- [x] `view/pdf_view.py`：傳入 `font_size` 至 `get_render_width_for_edit`
- [x] `view/pdf_view.py`：用 `warnings.catch_warnings` 抑制 disconnect 的 RuntimeWarning

## Check（檢核）

- 執行 `python test_1pdf_horizontal.py`：通過
- 執行 `python test_1pdf_horizontal.py --gui`：通過
- 使用者需以 1.pdf 實際操作驗證：編輯水平文字後文字不超出、不被裁切

## Act（行動）

- 若使用者仍回報超出：可將 `right_margin_pt` 係數由 2.0 調高至 2.5 或 3.0
- 若 `clip_to_rect` 導致意外裁切：可移除該安全網，僅依賴邊距計算
