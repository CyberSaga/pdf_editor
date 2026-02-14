# PDF 文字編輯技術說明

本文檔參考 [Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF) 和 [Apache PDFBox](https://github.com/apache/pdfbox) 等專案，說明如何在 PDF 上編輯文字。

## 目錄
1. [PDF 文字編輯的基本原理](#pdf-文字編輯的基本原理)
2. [Stirling-PDF 的實現方式](#stirling-pdf-的實現方式)
3. [Apache PDFBox 的實現方式](#apache-pdfbox-的實現方式)
4. [PyMuPDF 的實現方式（當前專案）](#pymupdf-的實現方式當前專案)
5. [改進建議與替代方案](#改進建議與替代方案)

---

## PDF 文字編輯的基本原理

### 重要概念

PDF 格式的本質是**繪圖指令的集合**，而非流動的文字（如 Word）。這意味著：

1. **PDF 不是「可編輯」格式**：PDF 中的文字是通過座標定位繪製的，沒有內建的「文字物件」概念
2. **編輯 = 覆蓋 + 重繪**：要修改現有文字，通常需要：
   - 定位原文字的座標範圍
   - 用背景色覆蓋原文字（或使用 Redaction）
   - 在相同位置重新繪製新文字

### 常見的編輯策略

| 策略 | 優點 | 缺點 | 適用場景 |
|------|------|------|----------|
| **覆蓋重繪** | 簡單直接 | 可能留下痕跡 | 簡單文字替換 |
| **Redaction（遮蓋）** | 徹底清除原內容 | 需要重新排版 | 敏感資訊處理 |
| **內容流插入** | 不影響原內容 | 可能造成層疊 | 添加註解、標記 |
| **頁面重建** | 完全控制 | 複雜度高 | 複雜排版需求 |

---

## Stirling-PDF 的實現方式

### 技術架構

Stirling-PDF 是一個全功能的 PDF 編輯平台，採用以下技術棧：

- **前端**：PDF.js（渲染）+ PDF-LIB.js（編輯）+ Joxit（互動）
- **後端**：Java Spring Boot + Apache PDFBox（核心處理）
- **字體**：Liberation Fonts（確保跨平台一致性）

### 文字編輯功能

1. **視覺化編輯**
   - 使用 PDF.js 在瀏覽器中渲染 PDF
   - 透過 PDF-LIB.js 提供互動式編輯介面
   - 支援直接點擊文字進行修改

2. **自動化處理**
   - **文字遮蓋（Redaction）**：自動尋找並遮蓋敏感文字
   - **OCR 識別**：使用 OCRMyPDF 將掃描圖像轉為可編輯文字
   - **內容比較**：比較兩個 PDF 的文字差異

3. **後端處理流程**（基於 PDFBox）
   ```java
   // 簡化的 Stirling-PDF 文字編輯流程
   PDDocument document = PDDocument.load(inputFile);
   PDPage page = document.getPage(pageIndex);
   
   // 1. 定位原文字區域
   PDFTextStripper stripper = new PDFTextStripper();
   String text = stripper.getText(document);
   
   // 2. 使用 Redaction 清除原文字
   // （實際實現更複雜，涉及座標計算）
   
   // 3. 重新繪製新文字
   PDPageContentStream contentStream = 
       new PDPageContentStream(document, page, APPEND, true);
   contentStream.beginText();
   contentStream.setFont(font, fontSize);
   contentStream.newLineAtOffset(x, y);
   contentStream.showText(newText);
   contentStream.endText();
   contentStream.close();
   
   document.save(outputFile);
   ```

### 關鍵技術點

- **字體處理**：內建 Liberation Fonts 確保文字渲染一致性
- **座標系統**：PDF 使用點（point）作為單位，1 點 = 1/72 英寸
- **內容流（Content Streams）**：PDF 頁面由一系列繪圖指令組成

---

## Apache PDFBox 的實現方式

### 基本文字添加

```java
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.common.PDRectangle;

// 開啟現有 PDF
PDDocument document = PDDocument.load(new File("input.pdf"));
PDPage page = document.getPage(0);

// 在頁面上添加文字
try (PDPageContentStream contentStream = new PDPageContentStream(
        document, page, 
        PDPageContentStream.AppendMode.APPEND,  // 追加模式
        true,  // 壓縮
        true   // 重置變換矩陣
)) {
    contentStream.beginText();
    contentStream.setFont(PDType1Font.HELVETICA_BOLD, 12);
    contentStream.newLineAtOffset(100, 700);  // 座標 (x, y)
    contentStream.showText("這是新加入的文字");
    contentStream.endText();
}

document.save("output.pdf");
document.close();
```

### 文字替換（覆蓋方式）

```java
// 1. 定位原文字
PDFTextStripper stripper = new PDFTextStripper();
stripper.setStartPage(1);
stripper.setEndPage(1);
String text = stripper.getText(document);

// 2. 獲取文字位置（需要更複雜的解析）
// PDFBox 不直接提供文字座標，需要使用 PDFTextStripperByArea 或自定義解析

// 3. 覆蓋原文字（繪製白色矩形）
PDPageContentStream contentStream = new PDPageContentStream(
    document, page, APPEND, true, true);
contentStream.setNonStrokingColor(Color.WHITE);
contentStream.addRect(x, y, width, height);
contentStream.fill();

// 4. 繪製新文字
contentStream.setNonStrokingColor(Color.BLACK);
contentStream.beginText();
contentStream.setFont(font, fontSize);
contentStream.newLineAtOffset(x, y);
contentStream.showText(newText);
contentStream.endText();
contentStream.close();
```

### 使用 Redaction 清除文字

```java
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotation;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotationRedaction;

// 創建 Redaction 註解
PDAnnotationRedaction redaction = new PDAnnotationRedaction();
PDRectangle rect = new PDRectangle(x, y, width, height);
redaction.setRectangle(rect);
redaction.setOverlayColor(Color.WHITE);  // 覆蓋顏色

page.getAnnotations().add(redaction);

// 應用 Redaction（清除原內容）
PDDocumentCatalog catalog = document.getDocumentCatalog();
PDAcroForm acroForm = catalog.getAcroForm();
if (acroForm != null) {
    acroForm.flatten(null);  // 扁平化表單
}
```

### 進階排版：pdfbox-layout

對於需要自動換行、段落對齊等複雜排版，可以使用 `pdfbox-layout` 擴充：

```java
import com.tom_roush.pdfbox.util.PDFBoxResourceLoader;
import org.apache.pdfbox.pdmodel.PDDocument;
import technology.tabula.extractors.SpreadsheetExtractionAlgorithm;

// 使用 pdfbox-layout 進行段落排版
Paragraph paragraph = new Paragraph();
paragraph.addText("這是一段很長的文字，", 12, PDType1Font.HELVETICA);
paragraph.addText("會自動換行。", 12, PDType1Font.HELVETICA_BOLD);

// 設定對齊方式
paragraph.setAlignment(HorizontalAlignment.CENTER);
paragraph.setMargin(50, 50, 50, 50);

// 繪製到頁面
paragraph.draw(contentStream, new Position(100, 700), 400);
```

---

## PyMuPDF 的實現方式（當前專案）

### 當前實現分析

您的專案使用 PyMuPDF（fitz），目前的 `edit_text` 方法採用了以下策略：

1. **頁面克隆**：創建頁面快照以避免直接修改
2. **Redaction 清除**：使用 `add_redact_annot` 和 `apply_redactions` 清除原文字
3. **HTML 插入**：使用 `insert_htmlbox` 進行精細排版（支援中英文混合）
4. **驗證機制**：通過文字相似度驗證插入是否成功

### 優點

- ✅ 支援中英文混合排版
- ✅ 使用 Redaction 確保原內容被徹底清除
- ✅ 有驗證機制確保插入成功
- ✅ 在快照上操作，失敗可回滾

### 可能的改進方向

#### 1. 使用 `insert_textbox` 作為替代方案

`insert_textbox` 是 PyMuPDF 提供的另一個文字插入方法，可能更適合簡單場景：

```python
def edit_text_simple(self, page_num: int, rect: fitz.Rect, new_text: str, 
                     font: str = "helv", size: int = 12, color: tuple = (0.0, 0.0, 0.0)):
    """使用 insert_textbox 的簡化版本"""
    page = self.doc[page_num - 1]
    
    # 1. 清除原文字
    page.add_redact_annot(rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    
    # 2. 插入新文字
    rc = page.insert_textbox(
        rect,
        new_text,
        fontname=font,
        fontsize=size,
        color=color,
        align=fitz.TEXT_ALIGN_LEFT
    )
    
    if rc < 0:
        raise RuntimeError(f"文字插入失敗，返回值: {rc}")
    
    page.update()
    self._save_state()
```

**注意**：`insert_textbox` 對中文支援可能不如 `insert_htmlbox`，需要測試。

#### 2. 直接使用 `insert_text`（最簡單）

對於不需要複雜排版的場景：

```python
def edit_text_direct(self, page_num: int, point: fitz.Point, new_text: str,
                     font: str = "helv", size: int = 12, color: tuple = (0.0, 0.0, 0.0)):
    """直接插入文字（不處理原文字清除）"""
    page = self.doc[page_num - 1]
    
    page.insert_text(
        point,
        new_text,
        fontname=font,
        fontsize=size,
        color=color
    )
    
    page.update()
    self._save_state()
```

#### 3. 改進 HTML 轉換邏輯

當前 `_convert_text_to_html` 方法可以進一步優化，支援更多字體和樣式：

```python
def _convert_text_to_html_enhanced(self, text: str, font_size: int, 
                                   color: tuple, font_family: str = None) -> str:
    """增強的 HTML 轉換，支援更多字體選項"""
    html_parts = []
    
    # 支援更多字體映射
    font_map = {
        "helv": "helv",
        "times": "times",
        "courier": "courier",
        "china-ts": "cjk",
        "china-s": "cjk",
        "china-t": "cjk"
    }
    
    css_font = font_map.get(font_family, "helv")
    
    # 處理文字內容
    pattern = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff]+|[a-zA-Z0-9]+| +|\n)')
    parts = pattern.findall(text)
    
    for part in parts:
        if part == '\n':
            html_parts.append('<br>')
        elif part.isspace():
            html_parts.append('&nbsp;' * len(part))
        elif re.match(r'[\u4e00-\u9fff\u3040-\u30ff]+', part):
            html_parts.append(f'<span class="cjk">{part}</span>')
        else:
            html_parts.append(f'<span class="helv">{part}</span>')
    
    return "".join(html_parts)
```

#### 4. 參考 PDFBox 的座標計算方式

PDFBox 使用精確的座標計算來定位文字。在 PyMuPDF 中，可以改進文字定位：

```python
def get_precise_text_bounds(self, page_num: int, search_text: str) -> List[fitz.Rect]:
    """精確定位文字位置（類似 PDFBox 的 PDFTextStripperByArea）"""
    page = self.doc[page_num - 1]
    text_instances = page.search_for(search_text)
    
    # 獲取每個實例的精確邊界
    bounds = []
    for inst in text_instances:
        # 獲取該區域的文字塊以計算精確邊界
        words = page.get_text("words", clip=inst)
        if words:
            x0 = min(word[0] for word in words)
            y0 = min(word[1] for word in words)
            x1 = max(word[2] for word in words)
            y1 = max(word[3] for word in words)
            bounds.append(fitz.Rect(x0, y0, x1, y1))
        else:
            bounds.append(inst)
    
    return bounds
```

---

## 改進建議與替代方案

### 1. 性能優化

當前實現每次編輯都會克隆整個頁面，對於大型 PDF 可能較慢。可以考慮：

- **增量更新**：只處理受影響的內容流
- **批量操作**：累積多個編輯後一次性應用
- **記憶體優化**：使用 `garbage=0` 參數（您已經在使用）

### 2. 錯誤處理增強

```python
def edit_text_with_fallback(self, page_num: int, rect: fitz.Rect, new_text: str, 
                            font: str = "helv", size: int = 12, color: tuple = (0.0, 0.0, 0.0)):
    """帶有降級策略的文字編輯"""
    try:
        # 首先嘗試 HTML 方式（支援複雜排版）
        self.edit_text(page_num, rect, new_text, font, size, color)
    except Exception as html_error:
        logger.warning(f"HTML 插入失敗，嘗試簡單方式: {html_error}")
        try:
            # 降級到 insert_textbox
            self.edit_text_simple(page_num, rect, new_text, font, size, color)
        except Exception as simple_error:
            logger.error(f"簡單插入也失敗: {simple_error}")
            # 最後降級到直接插入（不清除原文字）
            point = fitz.Point(rect.x0, rect.y0)
            self.edit_text_direct(page_num, point, new_text, font, size, color)
```

### 3. 字體管理

參考 Stirling-PDF 的字體管理策略：

```python
class FontManager:
    """字體管理器，確保字體可用性"""
    
    FONT_MAP = {
        "helv": "helv",  # Helvetica
        "times": "times",  # Times-Roman
        "courier": "courier",  # Courier
        "china-ts": "china-ts",  # 繁體中文
        "china-s": "china-s",  # 簡體中文
    }
    
    @classmethod
    def get_available_font(cls, preferred: str) -> str:
        """獲取可用字體，如果首選字體不可用則返回備用"""
        # PyMuPDF 內建字體通常都可用
        return cls.FONT_MAP.get(preferred, "helv")
    
    @classmethod
    def validate_font(cls, font_name: str) -> bool:
        """驗證字體是否可用"""
        try:
            # 嘗試創建一個測試頁面來驗證字體
            test_doc = fitz.open()
            test_page = test_doc.new_page()
            test_page.insert_text((0, 0), "test", fontname=font_name)
            test_doc.close()
            return True
        except:
            return False
```

### 4. 參考其他 Python PDF 庫

除了 PyMuPDF，還可以參考：

- **pdf-lib**（JavaScript，但概念可參考）：提供更現代的 API
- **ReportLab**：適合生成 PDF，但編輯功能有限
- **PyPDF2/PyPDF4**：輕量級，但功能較少

---

## 總結

### 技術對比

| 特性 | Stirling-PDF | Apache PDFBox | PyMuPDF（當前） |
|------|--------------|---------------|-----------------|
| **語言** | Java | Java | Python |
| **編輯方式** | Redaction + 重繪 | Redaction + ContentStream | Redaction + HTMLBox |
| **中文支援** | ✅ 良好 | ⚠️ 需額外配置 | ✅ 良好 |
| **排版能力** | ✅ 強（pdfbox-layout） | ⚠️ 需擴充 | ✅ 強（HTML） |
| **性能** | ✅ 優秀 | ✅ 優秀 | ✅ 優秀 |
| **易用性** | ✅ 高（Web UI） | ⚠️ 需編程 | ✅ 高（Python API） |

### 建議

1. **保持當前實現**：您的 `edit_text` 方法已經相當完善，特別是對中英文混合的支援
2. **添加降級策略**：當 HTML 插入失敗時，自動降級到簡單方法
3. **優化性能**：考慮批量操作和增量更新
4. **增強字體管理**：參考 Stirling-PDF 的字體處理方式

### 參考資源

- [Stirling-PDF GitHub](https://github.com/Stirling-Tools/Stirling-PDF)
- [Apache PDFBox 官方文檔](https://pdfbox.apache.org/)
- [PyMuPDF 文檔](https://pymupdf.readthedocs.io/)
- [PDF 格式規範（ISO 32000）](https://www.iso.org/standard/51502.html)

---

*最後更新：2024年*
