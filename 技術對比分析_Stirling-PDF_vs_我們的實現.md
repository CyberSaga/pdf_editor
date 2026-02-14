# 技術對比分析：Stirling-PDF vs 我們的實現

## 概述

本文檔比較 Stirling-PDF 的文字編輯技術與我們當前實現的技術，分析相同點和不同點。

---

## 相同點（Similarities）

### 1. **獨立文字元素管理**

#### Stirling-PDF
- 每個文字元素作為獨立的**群組（group）**進行管理
- 每個群組都有**唯一的 ID**（`groupId`）
- 群組包含文字內容、位置、字體等屬性

#### 我們的實現
- 每個文字方塊作為獨立的**索引項**進行管理
- 每個文字方塊都有**唯一的 block_id**（`page_{page_num}_block_{i}`）
- 索引包含文字內容、位置（rect）、字體、大小、顏色等屬性

**結論**：✅ **相同** - 都使用唯一標識符來管理獨立的文字元素

---

### 2. **頁面狀態隔離**

#### Stirling-PDF
```typescript
useEffect(() => {
  setActiveGroupId(null);
  setEditingGroupId(null);
  setActiveImageId(null);
  setTextScales(new Map());
  measurementKeyRef.current = '';
}, [selectedPage]);
```
- 切換頁面時重設活動群組和編輯狀態
- 保留各頁面的文字內容
- 不同頁面的文字不會相互影響

#### 我們的實現
```python
self.text_block_index = {
    0: [...],  # 第1頁的文字方塊
    1: [...],  # 第2頁的文字方塊
}
```
- 索引按頁面分組存儲
- 編輯時只影響當前頁面的索引
- 不同頁面的文字方塊完全隔離

**結論**：✅ **相同** - 都實現了頁面級別的狀態隔離

---

### 3. **新增文字不影響原有文字**

#### Stirling-PDF
- 新增的文字會創建**新的群組**，與現有群組分開管理
- 原有文字群組的狀態和內容不會因為新增文字而改變
- 同一頁面內的新舊文字可以並存

#### 我們的實現
- 編輯時只更新索引中目標文字方塊的內容
- 其他文字方塊的索引保持不變
- 渲染時從索引讀取所有文字方塊，確保其他方塊不受影響

**結論**：✅ **相同** - 都確保新增/編輯文字時不影響其他文字

---

### 4. **清除文字的機制**

#### Stirling-PDF
```typescript
if (currentText.length === 0) {
  // Already empty - remove the textbox entirely
  onGroupDelete(pageIndex, groupId);
} else {
  // Has text - clear it but keep the textbox
  onGroupEdit(pageIndex, groupId, '');
}
```
- 提供清除文字的功能
- 可以清除文字內容或移除整個文字框

#### 我們的實現
```python
# 清除所有文字塊
for block in blocks:
    if block.get('type') == 0:  # 文字塊
        block_rect = fitz.Rect(block["bbox"])
        temp_page.add_redact_annot(block_rect)
temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
```
- 使用 Redaction 清除文字
- 可以清除特定文字方塊或所有文字

**結論**：✅ **相似** - 都提供清除文字的功能，但實現方式不同

---

## 不同點（Differences）

### 1. **架構層次**

#### Stirling-PDF
- **前端架構**：基於 React + TypeScript
- **渲染層**：使用 PDF.js 在瀏覽器中渲染
- **文字管理**：在前端 JavaScript 中管理文字群組狀態
- **後端處理**：Java Spring Boot + PDFBox 處理 PDF 操作

#### 我們的實現
- **桌面應用**：基於 PySide6 (Qt)
- **渲染層**：使用 PyMuPDF 直接操作 PDF
- **文字管理**：在 Python 後端管理文字方塊索引
- **PDF 操作**：直接使用 PyMuPDF 進行所有操作

**結論**：❌ **完全不同** - Stirling-PDF 是 Web 應用，我們是桌面應用

---

### 2. **文字存儲方式**

#### Stirling-PDF
```typescript
// 文字群組存儲在前端狀態中
const [groupsByPage, setGroupsByPage] = useState<GroupsByPage>({});
// 每個群組包含：
{
  id: string,           // 唯一ID
  text: string,         // 文字內容
  originalText: string, // 原始文字（用於比較）
  x: number,            // X座標
  y: number,            // Y座標
  fontSize: number,     // 字體大小
  fontFamily: string,   // 字體
  color: string,        // 顏色
  // ...
}
```
- **存儲位置**：前端 React 狀態（記憶體中）
- **持久化**：通過 API 發送到後端保存到 PDF
- **同步方式**：前端狀態與 PDF 內容需要同步

#### 我們的實現
```python
# 文字方塊索引存儲在 Python 物件中
self.text_block_index = {
    page_num: [{
        'block_id': str,      # 唯一ID
        'rect': fitz.Rect,    # 位置矩形
        'text': str,          # 文字內容
        'font': str,          # 字體
        'size': float,        # 字體大小
        'color': tuple,       # 顏色
        'block_index': int,   # 原始PDF中的塊索引
    }, ...]
}
```
- **存儲位置**：Python 物件屬性（記憶體中）
- **持久化**：直接寫入 PDF 文件
- **同步方式**：索引與 PDF 內容直接同步（編輯時更新索引，然後渲染）

**結論**：❌ **不同** - 存儲方式和同步機制不同

---

### 3. **編輯策略**

#### Stirling-PDF
```
用戶編輯文字
  ↓
更新前端狀態（React state）
  ↓
通過 API 發送到後端
  ↓
後端使用 PDFBox 處理 PDF
  ↓
返回結果給前端
  ↓
前端更新顯示
```
- **分層處理**：前端管理狀態，後端處理 PDF
- **異步操作**：通過 API 調用進行通信
- **驗證機制**：前端可以驗證編輯結果

#### 我們的實現
```
用戶編輯文字
  ↓
更新索引中的文字內容
  ↓
清除頁面上的所有文字
  ↓
從索引渲染所有文字方塊（HTML）
  ↓
應用更改到PDF
```
- **直接操作**：直接在 Python 中操作 PDF
- **同步操作**：所有操作在單一進程中完成
- **無需驗證**：直接從索引渲染，不需要驗證

**結論**：❌ **不同** - 編輯流程和驗證機制完全不同

---

### 4. **文字渲染方式**

#### Stirling-PDF
- **前端渲染**：使用 PDF.js 在 Canvas 上繪製文字
- **文字定位**：使用座標系統（x, y）定位
- **字體處理**：使用瀏覽器的字體渲染引擎
- **即時預覽**：前端可以即時顯示編輯效果

#### 我們的實現
- **後端渲染**：使用 PyMuPDF 的 `insert_htmlbox` 渲染文字
- **文字定位**：使用矩形（Rect）定位
- **字體處理**：使用 PyMuPDF 的字體渲染引擎
- **渲染時機**：編輯完成後才渲染到 PDF

**結論**：❌ **不同** - 渲染方式和時機不同

---

### 5. **自動縮放處理**

#### Stirling-PDF
```typescript
// Skip groups that are being edited
if (editingGroupId === group.id) {
  return;
}

// Only apply auto-scaling to unchanged text
const hasChanges = group.text !== group.originalText;
if (hasChanges) {
  newScales.set(group.id, 1);
  return;
}
```
- **自動縮放**：根據視窗大小自動調整文字大小
- **保護機制**：跳過正在編輯的文字群組
- **狀態追蹤**：追蹤文字是否被修改過

#### 我們的實現
- **無自動縮放**：文字大小固定，不隨視窗變化
- **固定尺寸**：使用索引中記錄的字體大小
- **手動調整**：用戶可以手動修改字體大小

**結論**：❌ **不同** - Stirling-PDF 有自動縮放，我們沒有

---

### 6. **清除文字的實現**

#### Stirling-PDF
```typescript
if (currentText.length === 0) {
  // Already empty - remove the textbox entirely
  onGroupDelete(pageIndex, groupId);
} else {
  // Has text - clear it but keep the textbox
  onGroupEdit(pageIndex, groupId, '');
}
```
- **兩種模式**：
  - 文字為空：移除整個文字框
  - 文字不為空：清除文字但保留文字框
- **前端操作**：直接操作前端狀態

#### 我們的實現
```python
# 清除所有文字塊
for block in blocks:
    if block.get('type') == 0:  # 文字塊
        block_rect = fitz.Rect(block["bbox"])
        temp_page.add_redact_annot(block_rect)
temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
```
- **Redaction 方式**：使用 PDF Redaction 清除文字
- **批量清除**：清除頁面上所有文字，然後重新渲染
- **後端操作**：直接操作 PDF 內容

**結論**：❌ **不同** - 清除方式和粒度不同

---

### 7. **文字編輯的粒度**

#### Stirling-PDF
- **群組級別**：每個文字群組可以獨立編輯
- **部分編輯**：可以編輯群組中的部分文字
- **即時反饋**：編輯時立即在前端顯示效果

#### 我們的實現
- **方塊級別**：每個文字方塊可以獨立編輯
- **整體替換**：編輯時替換整個文字方塊的內容
- **批量渲染**：編輯完成後重新渲染整個頁面

**結論**：❌ **不同** - 編輯粒度和反饋方式不同

---

## 技術架構對比表

| 特性 | Stirling-PDF | 我們的實現 |
|------|--------------|------------|
| **應用類型** | Web 應用（瀏覽器） | 桌面應用（Qt） |
| **前端技術** | React + TypeScript | PySide6 (Qt) |
| **PDF 庫** | PDF.js (前端) + PDFBox (後端) | PyMuPDF |
| **文字管理** | 前端 React 狀態 | Python 物件索引 |
| **渲染方式** | Canvas 繪製（前端） | HTML 渲染（後端） |
| **編輯策略** | 前端狀態 → API → 後端處理 | 索引更新 → 直接渲染 |
| **同步機制** | 前端狀態與 PDF 同步 | 索引與 PDF 直接同步 |
| **自動縮放** | ✅ 有 | ❌ 無 |
| **即時預覽** | ✅ 有 | ❌ 無 |
| **清除方式** | 前端狀態操作 | PDF Redaction |
| **編輯粒度** | 群組級別，部分編輯 | 方塊級別，整體替換 |

---

## 可以借鑒的技術

### 1. **自動縮放機制**
Stirling-PDF 的自動縮放功能可以根據視窗大小調整文字大小，這對於響應式設計很有用。我們可以考慮實現類似的功能。

### 2. **即時預覽**
Stirling-PDF 在前端提供即時預覽，用戶可以立即看到編輯效果。我們可以在 Qt 中實現類似的預覽功能。

### 3. **部分文字編輯**
Stirling-PDF 支持編輯群組中的部分文字，而不是替換整個文字方塊。這可以提供更細粒度的編輯體驗。

### 4. **狀態追蹤**
Stirling-PDF 追蹤文字是否被修改過（`hasChanges = group.text !== group.originalText`），這對於實現撤銷/重做功能很有用。

---

## 總結

### 相同點
1. ✅ 都使用唯一標識符管理獨立的文字元素
2. ✅ 都實現了頁面級別的狀態隔離
3. ✅ 都確保新增/編輯文字時不影響其他文字
4. ✅ 都提供清除文字的功能

### 不同點
1. ❌ **架構完全不同**：Web 應用 vs 桌面應用
2. ❌ **存儲方式不同**：前端狀態 vs Python 索引
3. ❌ **編輯策略不同**：分層處理 vs 直接操作
4. ❌ **渲染方式不同**：Canvas 繪製 vs HTML 渲染
5. ❌ **功能差異**：自動縮放、即時預覽等

### 建議
雖然架構不同，但 Stirling-PDF 的一些設計理念值得借鑒：
- **狀態追蹤**：追蹤文字是否被修改
- **即時反饋**：提供即時預覽功能
- **細粒度編輯**：支持部分文字編輯

---

*最後更新：2024年*
