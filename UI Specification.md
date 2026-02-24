# PDF Editor UI Specification

## 1. Overview
This specification defines the user interface (UI) for a visual PDF editor application developed in Python using PySide6 (or PyQt6 as fallback). The design follows a modern, minimalist Fluent-style aesthetic with a three-column layout: left sidebar for navigation, central canvas for PDF viewing/editing, and right sidebar for contextual properties. The UI emphasizes usability, clarity, and focus on core tasks, adhering to principles like "contextual intelligence" and "on-demand visibility."

### Key Principles
- **Smooth Operation**: Minimize clutter; use tabs, collapsible panels, and contextual displays to reduce cognitive load.
- **Clear Thinking**: Logical grouping of functions; dynamic elements appear only when needed (e.g., search input on activation).
- **Visual Comfort**: Use rounded corners (8px radius), subtle shadows (elevation 2-4), blue accents (#0078D4), light theme background (#F8FAFC), and Source Han Sans TC font for Chinese text. Support dark mode toggle.
- **Full Feature Retention**: All features from FEATURES.md must be implemented (e.g., text editing via F2, Undo/Redo, OCR, annotations).
- **Boundaries**:
  - Platform: Cross-platform (Windows, macOS, Linux), but optimize for Windows 11 aesthetics.
  - Resolution: Responsive to window resizing; minimum size 1280x800px.
  - Accessibility: Support keyboard navigation (e.g., Ctrl+F for search, Esc to close panels); ARIA-like labels for screen readers.
  - Performance: Load times <1s for UI elements; no blocking operations on main thread (use QThread for heavy tasks like OCR).
  - Dependencies: PySide6, Fitz (PyMuPDF for PDF handling), pytesseract for OCR. No external installs beyond these.
  - Exclusions: No mobile support; no cloud integration; no multi-user features.

### Tech Stack
- **Framework**: PySide6 (Qt for Python).
- **PDF Backend**: PyMuPDF (fitz) for core operations.
- **Icons**: Use Fluent UI Icons or Remix Icon set (bundle as resources).
- **Themes**: Light mode default; dark mode via QApplication.setStyle("Fusion") + custom QPalette.
- **Command Palette**: Custom QWidget for Ctrl+K global search/command execution.

## 2. Global Layout Structure
The window uses a QMainWindow with:
- **Title Bar**: Standard OS title bar with app icon (stylized PDF page + magnifying glass) and title "視覺化 PDF 編輯器".
- **Central Widget**: QSplitter (horizontal) for resizable left-center-right panels.
  - Left: Fixed 260px width (collapsible to 0 via button or drag).
  - Center: Flexible (60-70% width), QGraphicsView for PDF canvas.
  - Right: Fixed 280px width (collapsible).
- **Status Bar**: QStatusBar at bottom.
- **Resizing Behavior**: Panels maintain ratios on window resize; center canvas scales PDF content to fit.

Mermaid diagram for reference (as provided in the document):
```
graph TD
    subgraph 視窗整體
        direction TB
        A[標題列] --> B[頂部 Tab 工具列]
        
        B --> C[頁籤切換區域]
        C --> Tab1[檔案: 開啟 儲存 另存]
        C --> Tab2[常用: 瀏覽 復原 重做 縮圖 搜尋 快照]
        C --> Tab3[編輯: 編輯文字 矩形 螢光筆 新增註解 註解列表 添加浮水印 浮水印列表 顯示/隱藏]
        C --> Tab4[頁面: 刪除 旋轉 匯出 插入空白 從檔案插入]
        C --> Tab5[轉換: OCR]
        
        B --> D[固定區域: 頁碼 / 縮放 / 復原重做 / 適應畫面]
        
        B --> 主要內容區
        
        subgraph 主要內容區
            direction LR
            Left[左側欄<br>縮圖 / 搜尋(需時出現) / 註解列表...]
            Left --> Center[主畫布<br>PDF內容 + 浮動工具列]
            Center --> Right[右側屬性<br>上下文 Inspector]
        end
        
        主要內容區 --> E[底部狀態列]
    end

    style Tab3 fill:#dbeafe,stroke:#3b82f6,stroke-width:2px  %% Example active tab
    style D fill:#f1f5f9,stroke:#64748b
```

## 3. Top Toolbar (QTabWidget + QToolBar)
- **Height**: 48px.
- **Structure**: QTabWidget for tabs, with QToolBar inside each tab page.
- **Tabs** (left-aligned, flat style, blue highlight on active):
  1. **檔案** (3 buttons): 開啟 (sig_open_pdf), 儲存 (sig_save), 另存新檔 (sig_save_as).
  2. **常用** (6 buttons): 瀏覽模式 (switch to browse mode), 復原 (sig_undo), 重做 (sig_redo), 縮圖 (toggle left sidebar thumbnails), 搜尋 (trigger search mode), 快照 (sig_snapshot_page).
  3. **編輯** (8 buttons): 編輯文字 (enter edit_text mode, F2 shortcut), 矩形 (enter rect mode), 螢光筆 (enter highlight mode), 新增註解 (enter add_annotation mode), 註解列表 (toggle annotations panel in left sidebar), 添加浮水印 (open watermark dialog), 浮水印列表 (toggle watermarks panel in left sidebar), 顯示/隱藏註解 (sig_toggle_annotations_visibility, checkbox style).
  4. **頁面** (5 buttons): 刪除頁 (sig_delete_pages), 旋轉頁 (sig_rotate_pages), 匯出頁 (sig_export_pages), 插入空白頁 (sig_insert_blank_page), 從檔案插入頁 (sig_insert_pages_from_file).
  5. **轉換** (1 button): OCR（文字辨識） (sig_ocr).
- **Fixed Right Section** (not tab-dependent): Page counter ("頁 X / Y"), Zoom dropdown (e.g., "100% ▼", sig_scale_changed), Fit button (adapt to window), Undo/Redo arrows (if not in current tab).
- **Boundaries**: Max 8 buttons per tab; use icons + labels; keyboard shortcuts (e.g., Ctrl+S for save); no overflow—use ellipsis if needed.
- **Implementation**: Use QAction groups; connect to Controller signals from FEATURES.md.
- **Appearance**:
```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│  視覺化 PDF 編輯器                                                                     -  □  × │
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ 檔案  常用   [編輯]   頁面   轉換                                                               │
│  編輯文字    矩形    螢光筆    新增註解    註解列表    添加浮水印    浮水印列表    顯示/隱藏註解    │
│                                                                                               │
│ 頁 4 / 15     140% ▼   適應畫面    ↺(復原)  ↻(重做)                                            │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```
## 4. Left Sidebar (QTabWidget, 260px wide)
- **Tabs** (icon-based, vertical or top-aligned flat tabs): 縮圖 (default), 搜尋 (on-demand), 註解列表, 浮水印列表.
- **Thumbnails Panel** (default): Grid of page thumbnails (QListWidget); selected page highlighted in blue; click triggers sig_page_changed.
- **Search Panel** (hidden by default):
  - Activated via Ctrl+F or "搜尋" button.
  - Top: QLineEdit for input ("輸入文字搜尋..." placeholder); focus on activation.
  - Below: QListWidget for results ("找到 X 個結果"); each item: "頁 Y: snippet..." with hover states; click jumps to page + highlights rect (sig_jump_to_result).
- **Annotations List**: QListWidget of all annotations; click jumps (sig_jump_to_annotation).
- **Watermarks List**: QListWidget; edit/delete options (sig_update_watermark, sig_remove_watermark).
- **Behavior**: Collapsible (button in splitter); auto-switch to Search on activation; Esc closes expanded panels.
- **Boundaries**: Max 100 items per list; lazy loading for thumbnails; no auto-refresh—update on document change.

## 5. Central Canvas (QGraphicsView)
- **Content**: Render PDF pages via QGraphicsScene; continuous scrolling; page shadows (#E2E8F0 border).
- **Floating Mini-Toolbar**: Appears above page on mode entry (e.g., drawing): Icons for select, text, rect, highlight, annotate; cursor changes accordingly.
- **Interactions**: Zoom (wheel/mouse), pan (drag), selections (rubber band for text/rect).
- **Highlights**: Yellow for search results (#FEF08A); temporary flash on jump.
- **Boundaries**: Support up to 1000 pages; render only visible pages for performance; no direct editing—route to Model via Controller.

## 6. Right Sidebar (QStackedWidget, 280px wide, "屬性" title)
- **Dynamic Inspector**: Card-style sections (subtle borders, icons).
  - No selection: Page info (size, rotation).
  - Rect mode: "矩形設定" - Color picker (#0078D4 default), opacity slider (0-1).
  - Highlight mode: "螢光筆顏色" - Color swatch (#FFFF00 yellow).
  - Text mode: "文字設定" - Font dropdown (Source Han Serif TC default), size (12pt), checkbox "垂直文字擴展時左移".
- **Apply/Cancel**: Buttons at bottom for changes.
- **Boundaries**: Collapsible; max 5 sections; update on selection change (no polling).

## 7. Bottom Status Bar (QStatusBar)
- **Content**: "已修改" indicator, mode (e.g., "連續捲動"), shortcuts (e.g., "Ctrl+K 快速指令"), page/zoom info.
- **Search Mode**: Add "找到 X 個結果 • 按 Esc 關閉搜尋".
- **Boundaries**: Dark text (#334155); no interactive elements except tooltips.

## 8. Dynamic Behaviors
- **Search Activation**:
  - Trigger: Ctrl+F or "搜尋" button.
  - Changes: Left sidebar switches to Search tab; input focuses/selects all; results update live (Model.search_text).
  - Main canvas: Highlight matches; subtle dim if >10 results.
  - Exit: Esc or tab switch; clear highlights.
- **Mode Switches**: Enter drawing/text mode → Show floating toolbar; update right inspector.
- **Undo/Redo**: Refresh canvas/thumbnails on execution.
- **Dark Mode**: Toggle via menu; apply QPalette changes.
- **Command Palette**: Ctrl+K opens overlay QWidget with search for commands (e.g., type "delete page").

## 9. Implementation Guidelines
- **MVC Pattern**: Align with FEATURES.md (Model for data, Controller for logic, View for UI).
- **Signals/Slots**: Use PySide6 signals for all interactions (e.g., sig_edit_text).
- **Resources**: Bundle icons/fonts; use QResource.
- **Error Handling**: Dialogs for file errors; logging to console.
- **Testing Boundaries**: Unit tests for each component (e.g., search returns exact matches); UI tests via pytest-qt.
- **Deployment**: Package as executable via PyInstaller; include dependencies.

## 10. UI Appearance
- Usual
```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│  視覺化 PDF 編輯器                            -  □  ×                                          │
├───────┬─────────────────────────────┬───────────────────────────────────────┬───────────────┐
│ [檔案] 常用 [編輯] 頁面 轉換       │  頁 5 / 18   135% ▼  適應   ↺  ↻      │               │
│ 編輯文字 矩形 螢光筆 新增註解 註解列表 添加浮水印 浮水印列表 顯示/隱藏註解 │               │
├───────┴─────────────────────────────┴───────────────────────────────────────┴───────────────┤
│ 左側欄                               │ 主畫布 (PDF 內容)                     │ 右側屬性面板  │
│ ────────────────────────────────────┼───────────────────────────────────────┼───────────────┤
│ 縮圖                                 │                                       │ 矩形設定      │
│ □ 頁1 [選中]                         │          (顯示中的 PDF 頁面)          │ 顏色 ■■■      │
│ □ 頁2                                │                                       │ 透明度 ─────  │
│ □ 頁3                                │                                       │               │
│ ...                                  │                                       │               │
│                                      │                                       │               │
└──────────────────────────────────────┴───────────────────────────────────────┴───────────────┘
│ 狀態列：頁面 5/18 • 縮放 135% • 連續捲動                                              │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```
- Trigger Search Mode
```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│  視覺化 PDF 編輯器                            -  □  ×                                          │
├───────┬─────────────────────────────┬───────────────────────────────────────┬───────────────┐
│ [檔案] 常用 [編輯] 頁面 轉換       │  頁 5 / 18   135% ▼  適應   ↺  ↻      │               │
│ 編輯文字 矩形 螢光筆 新增註解 註解列表 添加浮水印 浮水印列表 顯示/隱藏註解 │               │
├───────┴─────────────────────────────┴───────────────────────────────────────┴───────────────┤
│ 搜 尋                               │ 主畫布 (PDF 內容)                     │ 右側屬性面板  │
│ ────────────────────────────────────┼───────────────────────────────────────┼───────────────┤
│ [ 輸入文字搜尋... ]  ← 焦點在此       │                                       │ (保持原樣)     │
│ 找到 8 個結果  ▼                     │                                       │               │
│ ▸ 頁1 : program 測試參考 ...         │          program  測試參考 ...         │               │
│   頁1 : program mine ... [高亮顯示]  │            program mine ...           │               │
│   頁2 : program why ...             │                                       │               │
│                                     │               program why ..          │               │
│                                     │          (相關結果在畫布上高亮)         │               │
│   ...                               │                                       │               │
│                                     │                                       │               │
└─────────────────────────────────────┴───────────────────────────────────────┴───────────────┘
│ 狀態列：找到 8 個結果 • 按 Esc 關閉搜尋 • 頁面 5/18                                   │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
This spec ensures a robust, user-friendly implementation. For ambiguities, prioritize docs/FEATURES.md functionality.