from PySide6.QtWidgets import (
    QApplication, QColorDialog, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QListWidget, QToolBar, QInputDialog, QMessageBox, QMenu, QFileDialog,
    QListWidgetItem, QWidget, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QDoubleSpinBox, QTextEdit, QGraphicsProxyWidget, QLineEdit, QHBoxLayout,
    QStackedWidget, QDialog, QSpinBox, QDialogButtonBox, QFormLayout,
    QScrollArea, QCheckBox, QTabWidget, QSplitter, QFrame, QSizePolicy, QSlider, QTabBar,
    QStatusBar, QGroupBox
)
from PySide6.QtGui import QPixmap, QIcon, QCursor, QKeySequence, QColor, QFont, QPen, QBrush, QTransform, QAction, QActionGroup, QCloseEvent, QTextOption, QShortcut
from PySide6.QtCore import Qt, Signal, QPointF, QTimer, QRectF, QPoint, QEvent
from typing import List, Tuple, Optional
from utils.helpers import pixmap_to_qpixmap, parse_pages, show_error
import logging
import warnings
import fitz

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _ctrl_tab_direction(key: int, modifiers: Qt.KeyboardModifiers) -> int:
    if not (modifiers & Qt.ControlModifier):
        return 0
    if key == Qt.Key_Backtab:
        return -1
    if key != Qt.Key_Tab:
        return 0
    return -1 if (modifiers & Qt.ShiftModifier) else 1


class _NoCtrlTabTabBar(QTabBar):
    """Disable built-in Ctrl+Tab tab cycling on non-document tab bars."""
    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and _ctrl_tab_direction(event.key(), event.modifiers()):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        direction = _ctrl_tab_direction(event.key(), event.modifiers())
        if direction:
            parent = self.parentWidget()
            while parent is not None and not hasattr(parent, "_cycle_document_tab"):
                parent = parent.parentWidget()
            if parent is not None:
                parent._cycle_document_tab(direction)
            event.accept()
            return
        super().keyPressEvent(event)


class PDFPasswordDialog(QDialog):
    """開啟加密 PDF 時輸入密碼的對話框"""
    def __init__(self, parent=None, file_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("PDF 需要密碼")
        self._file_path = file_path
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        if self._file_path:
            layout.addWidget(QLabel(f"此檔案受密碼保護，請輸入密碼：\n{self._file_path}"))
        else:
            layout.addWidget(QLabel("此 PDF 受密碼保護，請輸入密碼："))
        # 預設明碼顯示；旁邊勾選欄（眼睛符號）可切換為暗碼
        row = QHBoxLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Normal)  # 預設明碼
        self.password_edit.setPlaceholderText("輸入 PDF 密碼")
        row.addWidget(self.password_edit)
        self.hide_password_cb = QCheckBox("👁")  # 眼睛符號，實為勾選欄
        self.hide_password_cb.setToolTip("勾選後以密碼方式隱藏輸入")
        self.hide_password_cb.toggled.connect(self._on_show_hide_toggled)
        row.addWidget(self.hide_password_cb)
        layout.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_show_hide_toggled(self, checked: bool):
        """勾選時改為暗碼，取消勾選時改為明碼。"""
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
        )

    def get_password(self) -> str:
        return self.password_edit.text().strip()


class WatermarkDialog(QDialog):
    """浮水印新增/編輯對話框"""
    def __init__(self, parent=None, total_pages: int = 1, edit_data: dict = None):
        super().__init__(parent)
        self.setWindowTitle("編輯浮水印" if edit_data else "添加浮水印")
        self.edit_data = edit_data
        self.total_pages = max(1, total_pages)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form = QWidget()
        form_layout = QFormLayout(form)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("輸入浮水印文字（可多行，每行換行）")
        self.text_edit.setMaximumHeight(80)
        form_layout.addRow("浮水印文字:", self.text_edit)

        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText(f"如: 1,3-5 或留空套用全部 (1-{self.total_pages})")
        self.pages_edit.setText("全部")
        form_layout.addRow("套用頁面:", self.pages_edit)

        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(-360, 360)
        self.angle_spin.setValue(45)
        self.angle_spin.setSuffix("°")
        form_layout.addRow("旋轉角度:", self.angle_spin)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(0.4)
        form_layout.addRow("透明度:", self.opacity_spin)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 200)
        self.font_size_spin.setValue(48)
        form_layout.addRow("字型大小:", self.font_size_spin)

        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(0.8, 3.0)
        self.line_spacing_spin.setSingleStep(0.1)
        self.line_spacing_spin.setValue(1.3)
        self.line_spacing_spin.setToolTip("行距倍率，相對於字型大小（1.0=緊密，1.3=預設，2.0=寬鬆）")
        form_layout.addRow("行距倍率:", self.line_spacing_spin)

        self.color_btn = QPushButton()
        self.watermark_color = QColor(180, 180, 180)
        self.color_btn.setStyleSheet(f"background-color: rgb(180,180,180);")
        self.color_btn.clicked.connect(self._choose_color)
        form_layout.addRow("顏色:", self.color_btn)

        self.font_combo = QComboBox()
        self.font_combo.addItems(["china-ts", "china-ss", "helv", "cour", "Helvetica"])
        self.font_combo.setCurrentText("china-ts")
        self.font_combo.setToolTip("china-ts 適用繁體中文，china-ss 適用簡體中文")
        form_layout.addRow("字型:", self.font_combo)

        self.offset_x_spin = QDoubleSpinBox()
        self.offset_x_spin.setRange(-500, 500)
        self.offset_x_spin.setSuffix(" pt")
        self.offset_x_spin.setToolTip("正數向右、負數向左")
        form_layout.addRow("水平偏移:", self.offset_x_spin)

        self.offset_y_spin = QDoubleSpinBox()
        self.offset_y_spin.setRange(-500, 500)
        self.offset_y_spin.setSuffix(" pt")
        self.offset_y_spin.setToolTip("正數向下、負數向上")
        form_layout.addRow("垂直偏移:", self.offset_y_spin)

        scroll.setWidget(form)
        layout.addWidget(scroll)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        if self.edit_data:
            self.text_edit.setPlainText(self.edit_data.get("text", ""))
            pages = self.edit_data.get("pages", [])
            self.pages_edit.setText(",".join(str(p) for p in sorted(pages)) if pages else f"1-{self.total_pages}")
            self.angle_spin.setValue(self.edit_data.get("angle", 45))
            self.opacity_spin.setValue(self.edit_data.get("opacity", 0.4))
            self.font_size_spin.setValue(self.edit_data.get("font_size", 48))
            c = self.edit_data.get("color", (0.7, 0.7, 0.7))
            self.watermark_color = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
            self.color_btn.setStyleSheet(f"background-color: rgb({self.watermark_color.red()},{self.watermark_color.green()},{self.watermark_color.blue()});")
            font_name = self.edit_data.get("font", "helv")
            idx = self.font_combo.findText(font_name)
            self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.offset_x_spin.setValue(self.edit_data.get("offset_x", 0))
            self.offset_y_spin.setValue(self.edit_data.get("offset_y", 0))
            self.line_spacing_spin.setValue(self.edit_data.get("line_spacing", 1.3))

    def _choose_color(self):
        c = QColorDialog.getColor(self.watermark_color, self, "選擇浮水印顏色")
        if c.isValid():
            self.watermark_color = c
            self.color_btn.setStyleSheet(f"background-color: rgb({c.red()},{c.green()},{c.blue()});")

    def get_values(self):
        from utils.helpers import parse_pages
        text = self.text_edit.toPlainText().strip()
        pages_str = self.pages_edit.text().strip()
        if not pages_str or pages_str.lower() in ("全部", "all"):
            pages = list(range(1, self.total_pages + 1))
        else:
            try:
                pages = parse_pages(pages_str, self.total_pages)
            except ValueError:
                pages = [1]
        angle = self.angle_spin.value()
        opacity = self.opacity_spin.value()
        font_size = self.font_size_spin.value()
        color = (self.watermark_color.red()/255.0, self.watermark_color.green()/255.0, self.watermark_color.blue()/255.0)
        font = self.font_combo.currentText()
        offset_x = self.offset_x_spin.value()
        offset_y = self.offset_y_spin.value()
        line_spacing = self.line_spacing_spin.value()
        return pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing


class PDFView(QMainWindow):
    _VALID_MODES = {"browse", "edit_text", "add_text", "rect", "highlight", "add_annotation"}
    # --- Existing Signals ---
    sig_open_pdf = Signal(str)
    sig_print_requested = Signal()
    sig_save_as = Signal(str)
    sig_save = Signal()  # 存回原檔（Ctrl+S，使用增量更新若適用）
    sig_tab_changed = Signal(int)
    sig_tab_close_requested = Signal(int)
    sig_delete_pages = Signal(list)
    sig_rotate_pages = Signal(list, int)
    sig_export_pages = Signal(list, str, bool)
    sig_add_highlight = Signal(int, object, object)
    sig_add_rect = Signal(int, object, object, bool)
    sig_edit_text = Signal(int, object, str, str, int, tuple, str, bool, object, object, str)  # ..., new_rect(optional), target_span_id(optional), target_mode
    sig_add_textbox = Signal(int, object, str, str, int, tuple)  # page_num, visual_rect, text, font, size, color
    sig_jump_to_result = Signal(int, object)
    sig_search = Signal(str)
    sig_ocr = Signal(list)
    sig_undo = Signal()
    sig_redo = Signal()
    sig_mode_changed = Signal(str)
    sig_text_target_mode_changed = Signal(str)
    sig_page_changed = Signal(int)
    sig_scale_changed = Signal(int, float)

    # --- New Annotation Signals ---
    sig_add_annotation = Signal(int, object, str)  # page_idx, doc_point (fitz.Point), text
    sig_load_annotations = Signal()
    sig_jump_to_annotation = Signal(int) # By xref
    sig_toggle_annotations_visibility = Signal(bool)
    
    # --- Snapshot Signal ---
    sig_snapshot_page = Signal(int)

    # --- Zoom Re-render Signal ---
    sig_request_rerender = Signal()
    
    # --- Insert Pages Signals ---
    sig_insert_blank_page = Signal(int)  # position (1-based)
    sig_insert_pages_from_file = Signal(str, list, int)  # source_file, source_pages, position

    # --- 浮水印 Signals ---
    sig_add_watermark = Signal(list, str, float, float, int, tuple, str, float, float, float)  # pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing
    sig_update_watermark = Signal(str, list, str, float, float, int, tuple, str, float, float, float)  # wm_id, pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing
    sig_remove_watermark = Signal(str)
    sig_load_watermarks = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("視覺化 PDF 編輯器")
        self.setMinimumSize(1280, 800)
        self.setGeometry(100, 100, 1280, 800)
        self.total_pages = 0
        self.controller = None
        self._doc_tab_signal_block = False
        self._mode_actions: dict[str, QAction] = {}
        self._mode_action_group = QActionGroup(self)
        self._mode_action_group.setExclusive(True)

        # --- Central container: top toolbar area + main splitter ---
        central_container = QWidget(self)
        self.setCentralWidget(central_container)
        main_layout = QVBoxLayout(central_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Top Toolbar (ToolbarTabs): 48px height ---
        self._build_toolbar_tabs()
        main_layout.addWidget(self._toolbar_container)
        self._build_document_tabs_bar()
        main_layout.addWidget(self.document_tab_bar)
        self._install_document_tab_shortcuts()

        # --- Main content: QSplitter (Left 260px | Center | Right 280px) ---
        self.main_splitter = QSplitter(Qt.Horizontal)

        # Left sidebar: 260px, QTabWidget (縮圖 / 搜尋 / 註解列表 / 浮水印列表)
        self.left_sidebar = QTabWidget()
        self.left_sidebar.setTabBar(_NoCtrlTabTabBar(self.left_sidebar))
        self.left_sidebar.setMinimumWidth(200)
        self.left_sidebar.setMaximumWidth(400)
        self._setup_left_sidebar()
        self.left_sidebar_widget = QWidget()
        left_sidebar_layout = QVBoxLayout(self.left_sidebar_widget)
        left_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        left_sidebar_layout.addWidget(self.left_sidebar)
        self.main_splitter.addWidget(self.left_sidebar_widget)

        # Center: QGraphicsView (canvas)
        self.graphics_view = QGraphicsView(self)
        self.scene = QGraphicsScene(self)
        self.graphics_view.setScene(self.scene)
        self.main_splitter.addWidget(self.graphics_view)

        # Right sidebar: 280px, "屬性" dynamic inspector
        self.right_sidebar = QWidget()
        right_sidebar_layout = QVBoxLayout(self.right_sidebar)
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_title = QLabel("屬性")
        right_title.setStyleSheet("font-weight: bold; padding: 8px;")
        right_sidebar_layout.addWidget(right_title)
        self.right_stacked_widget = QStackedWidget()
        self._setup_property_inspector()
        right_sidebar_layout.addWidget(self.right_stacked_widget)
        self.right_sidebar.setMinimumWidth(240)
        self.right_sidebar.setMaximumWidth(400)
        self.main_splitter.addWidget(self.right_sidebar)

        # Set splitter sizes: left 260, center flexible, right 280
        self.main_splitter.setSizes([260, 740, 280])  # 1280 total approx
        main_layout.addWidget(self.main_splitter)

        # --- Status Bar ---
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        # --- State Variables ---
        self.current_mode = 'browse'
        self._add_text_default_font_applied = False
        self._add_text_default_pdf_font = "cjk"
        self._add_text_default_color = (0.0, 0.0, 0.0)
        self._add_text_default_size = 12
        self._add_text_default_width_pt = 220.0
        self._add_text_default_height_pt = 56.0
        self.current_page = 0
        self.scale = 1.0
        # 記錄目前場景內 pixmap 實際渲染時所使用的 scale。
        # self.scale 代表「期望的總縮放」，可能因 wheel zoom 超前於重渲；
        # _render_scale 追蹤已實際渲染進場景的 scale，供座標轉換使用。
        self._render_scale: float = 1.0
        # debounce timer：wheel 停止後 300ms 再觸發重渲，避免連續滾動時每幀都重渲
        self._zoom_debounce_timer = QTimer(self)
        self._zoom_debounce_timer.setSingleShot(True)
        self._zoom_debounce_timer.timeout.connect(self._on_zoom_debounce)
        self.drawing_start = None
        self.text_editor: QGraphicsProxyWidget = None
        self.editing_intent = "edit_existing"
        self.editing_rect: fitz.Rect = None
        self._editing_original_rect: fitz.Rect = None  # 編輯開始時的原始 rect，拖曳期間不變
        # 拖曳移動文字框的狀態機
        self._drag_pending: bool = False        # 滑鼠已按下在文字塊，尚未判定點擊或拖曳
        self._drag_active: bool = False         # 正在拖曳中
        self._drag_start_scene_pos = None       # 按下時的場景座標（QPointF）
        self._drag_editor_start_pos = None      # 按下時 proxy widget 的位置（QPointF）
        self._pending_text_info = None          # 待定狀態下存放的文字塊資訊（drag_pending 且無編輯框時）
        self.current_search_results = []
        self.current_search_index = -1
        self._browse_text_cursor_active = False
        self._text_selection_active = False
        self._text_selection_page_idx = None
        self._text_selection_start_scene_pos = None
        self._text_selection_rect_item = None
        self._text_selection_live_doc_rect = None
        self._text_selection_last_scene_pos = None
        self._selected_text_rect_doc = None
        self._selected_text_page_idx = None
        self._selected_text_cached = ""
        # Inline-editor focus lifecycle guards.
        self._edit_focus_guard_connected = False
        self._edit_focus_check_pending = False
        self._finalizing_text_edit = False
        self._discard_text_edit_once = False
        # Phase 5: edit_text 模式下的 hover 文字塊高亮
        self._hover_highlight_item = None       # QGraphicsRectItem | None
        self._last_hover_scene_pos = None       # QPointF | None（節流用）
        
        self.graphics_view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.graphics_view.setTransformationAnchor(QGraphicsView.AnchorViewCenter)

        # 連續捲動模式：所有頁面由上到下連結，滑動 scrollbar 切換頁面
        self.continuous_pages = True
        self.page_items: List[QGraphicsPixmapItem] = []
        self.page_y_positions: List[float] = []
        self.page_heights: List[float] = []
        self._scroll_block = False
        self._scroll_handler_connected = False
        self.PAGE_GAP = 10

        self.graphics_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setMouseTracking(True)
        self.graphics_view.viewport().setMouseTracking(True)
        self.graphics_view.viewport().setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.viewport().installEventFilter(self)

        self.graphics_view.wheelEvent = self._wheel_event
        self.graphics_view.mousePressEvent = self._mouse_press
        self.graphics_view.mouseMoveEvent = self._mouse_move
        self.graphics_view.mouseReleaseEvent = self._mouse_release
        self.graphics_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.graphics_view.customContextMenuRequested.connect(self._show_context_menu)
        
        self.resizeEvent = self._resize_event
        self.set_mode("browse")
        self._apply_scale()
        self._update_status_bar()
        # Fluent-style: light background, rounded corners (spec §10)
        self.setStyleSheet("""
            QMainWindow { background: #F8FAFC; }
            QGroupBox { border: 1px solid #E2E8F0; border-radius: 8px; margin-top: 8px; padding-top: 8px; }
            QPushButton { border-radius: 6px; padding: 6px 12px; }
            QLineEdit, QComboBox { border-radius: 6px; padding: 4px 8px; border: 1px solid #E2E8F0; }
        """)
        self.graphics_view.setStyleSheet("QGraphicsView { background: #F1F5F9; border: none; }")

    def _build_document_tabs_bar(self):
        """Document-level tab bar for multiple open PDFs."""
        self.document_tab_bar = QTabBar(self)
        self.document_tab_bar.setExpanding(False)
        self.document_tab_bar.setMovable(False)
        self.document_tab_bar.setTabsClosable(True)
        self.document_tab_bar.setDocumentMode(True)
        self.document_tab_bar.setElideMode(Qt.ElideMiddle)
        self.document_tab_bar.setStyleSheet("""
            QTabBar {
                background: #FFFFFF;
                border-bottom: 1px solid #E2E8F0;
                padding: 2px 6px;
            }
            QTabBar::tab {
                min-width: 120px;
                max-width: 280px;
                padding: 6px 10px;
                margin-right: 2px;
                border: 1px solid #CBD5E1;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                background: #EEF2F7;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #0F172A;
            }
        """)
        self.document_tab_bar.currentChanged.connect(self._on_document_tab_changed)
        self.document_tab_bar.tabCloseRequested.connect(self._on_document_tab_close_requested)
        self.document_tab_bar.setVisible(False)

    def _install_document_tab_shortcuts(self) -> None:
        """Route Ctrl+Tab and Ctrl+Shift+Tab to document tabs only."""
        self._shortcut_next_doc_tab = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self._shortcut_next_doc_tab.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_next_doc_tab.activated.connect(lambda: self._cycle_document_tab(1))

        self._shortcut_prev_doc_tab = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        self._shortcut_prev_doc_tab.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_prev_doc_tab.activated.connect(lambda: self._cycle_document_tab(-1))

        self._shortcut_prev_doc_tab_back = QShortcut(QKeySequence("Ctrl+Backtab"), self)
        self._shortcut_prev_doc_tab_back.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_prev_doc_tab_back.activated.connect(lambda: self._cycle_document_tab(-1))

        self._shortcut_escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._shortcut_escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_escape.activated.connect(self._on_escape_shortcut)

    def _tab_shortcut_direction(self, key: int, modifiers: Qt.KeyboardModifiers) -> int:
        return _ctrl_tab_direction(key, modifiers)

    def _cycle_document_tab(self, direction: int) -> bool:
        tab_count = self.document_tab_bar.count()
        if tab_count <= 1:
            return False
        current = self.document_tab_bar.currentIndex()
        if current < 0:
            current = 0
        self.document_tab_bar.setCurrentIndex((current + direction) % tab_count)
        return True

    def set_document_tabs(self, tabs: List[dict], active_index: int) -> None:
        self._doc_tab_signal_block = True
        self.document_tab_bar.blockSignals(True)
        try:
            while self.document_tab_bar.count():
                self.document_tab_bar.removeTab(self.document_tab_bar.count() - 1)
            for meta in tabs:
                title = meta.get("display_name") or "未命名"
                if meta.get("dirty"):
                    title = f"{title} *"
                idx = self.document_tab_bar.addTab(title)
                self.document_tab_bar.setTabData(idx, meta.get("id"))
                self.document_tab_bar.setTabToolTip(idx, meta.get("path") or title)
            if tabs:
                idx = active_index if 0 <= active_index < len(tabs) else 0
                self.document_tab_bar.setCurrentIndex(idx)
            self.document_tab_bar.setVisible(bool(tabs))
            self.document_tab_bar.setTabsClosable(bool(tabs))
        finally:
            self.document_tab_bar.blockSignals(False)
            self._doc_tab_signal_block = False

    def clear_document_tabs(self) -> None:
        self.set_document_tabs([], -1)

    def _on_document_tab_changed(self, index: int) -> None:
        if self._doc_tab_signal_block:
            return
        if index >= 0:
            self.sig_tab_changed.emit(index)

    def _on_document_tab_close_requested(self, index: int) -> None:
        if self._doc_tab_signal_block:
            return
        if index >= 0:
            self.sig_tab_close_requested.emit(index)

    def _build_toolbar_tabs(self):
        """Top toolbar: 高度依字型與內距計算 — 標籤列 ~26px + 工具列 ~26px + 邊距 8px ≈ 60px，避免過窄截斷或過高留白。"""
        self._toolbar_container = QFrame()
        # 約 9–10pt 字型行高 ~14–16px，標籤一行 ~26px、工具列一行 ~26px、上下邊距 8px → 60px
        # 固定高度 60px，避免佈局依子元件 sizeHint 分配更多垂直空間導致頂端列過高
        self._toolbar_container.setFixedHeight(60)
        self._toolbar_container.setStyleSheet("QFrame { background: #F1F5F9; border-bottom: 1px solid #E2E8F0; }")
        bar_layout = QHBoxLayout(self._toolbar_container)
        bar_layout.setContentsMargins(6, 4, 6, 4)
        bar_layout.setSpacing(6)

        self.toolbar_tabs = QTabWidget()
        self.toolbar_tabs.setTabBar(_NoCtrlTabTabBar(self.toolbar_tabs))
        self.toolbar_tabs.setDocumentMode(True)
        # 標籤：緊湊內距，不省略文字，最小寬度避免截斷
        self.toolbar_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: transparent; top: 0px; }
            QTabBar::tab { min-width: 52px; padding: 5px 10px; margin-right: 2px; background: transparent; }
            QTabBar::tab:selected { background: #0078D4; color: white; border-radius: 4px; }
        """)
        tab_bar = self.toolbar_tabs.tabBar()
        tab_bar.setElideMode(Qt.ElideNone)
        tab_bar.setMinimumHeight(26)
        # 工具列按鈕：緊湊內距，仍保留 min-width 避免文字截斷
        toolbar_style = (
            "QToolBar { spacing: 4px; padding: 2px 0; } "
            "QToolButton { min-width: 52px; padding: 4px 8px; } "
            "QToolButton:checked { background: #0EA5E9; color: white; border-radius: 4px; }"
        )
        # 檔案
        tab_file = QWidget()
        tb_file = QToolBar()
        tb_file.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb_file.setStyleSheet(toolbar_style)
        self._action_open = tb_file.addAction("開啟", self._open_file)
        self._action_open.setShortcut(QKeySequence("Ctrl+O"))
        self._action_print = tb_file.addAction("列印", self._print_document)
        self._action_print.setShortcut(QKeySequence("Ctrl+P"))
        self._action_save = tb_file.addAction("儲存", self._save)
        self._action_save.setShortcut(QKeySequence("Ctrl+S"))
        self._action_save_as = tb_file.addAction("另存新檔", self._save_as)
        self._action_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        layout_file = QVBoxLayout(tab_file)
        layout_file.setContentsMargins(4, 0, 0, 0)
        layout_file.addWidget(tb_file)
        self.toolbar_tabs.addTab(tab_file, "檔案")
        # 常用
        tab_common = QWidget()
        tb_common = QToolBar()
        tb_common.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb_common.setStyleSheet(toolbar_style)
        self._action_browse = self._make_mode_action("瀏覽模式", "browse")
        tb_common.addAction(self._action_browse)
        self._action_undo = tb_common.addAction("復原", self.sig_undo.emit)
        self._action_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self._action_redo = tb_common.addAction("重做", self.sig_redo.emit)
        self._action_redo.setShortcut(QKeySequence("Ctrl+Y"))
        tb_common.addAction("縮圖", self._show_thumbnails_tab)
        tb_common.addAction("搜尋", self._show_search_tab)
        tb_common.addAction("快照", self._snapshot_page)
        layout_common = QVBoxLayout(tab_common)
        layout_common.setContentsMargins(4, 0, 0, 0)
        layout_common.addWidget(tb_common)
        self.toolbar_tabs.addTab(tab_common, "常用")
        # 編輯
        tab_edit = QWidget()
        tb_edit = QToolBar()
        tb_edit.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb_edit.setStyleSheet(toolbar_style)
        self._action_edit_text = self._make_mode_action("編輯文字", "edit_text")
        tb_edit.addAction(self._action_edit_text)
        self._action_edit_text.setShortcut(QKeySequence(Qt.Key_F2))
        self._action_add_text = self._make_mode_action("新增文字框", "add_text")
        tb_edit.addAction(self._action_add_text)
        self._action_rect = self._make_mode_action("矩形", "rect")
        tb_edit.addAction(self._action_rect)
        self._action_highlight = self._make_mode_action("螢光筆", "highlight")
        tb_edit.addAction(self._action_highlight)
        self._action_add_annotation = self._make_mode_action("新增註解", "add_annotation")
        tb_edit.addAction(self._action_add_annotation)
        tb_edit.addAction("註解列表", self._show_annotations_tab)
        tb_edit.addAction("添加浮水印", self._show_add_watermark_dialog)
        tb_edit.addAction("浮水印列表", self._show_watermarks_tab)
        toggle_annot = QAction("顯示/隱藏註解", self)
        toggle_annot.setCheckable(True)
        toggle_annot.setChecked(True)
        toggle_annot.triggered.connect(self.sig_toggle_annotations_visibility)
        tb_edit.addAction(toggle_annot)
        layout_edit = QVBoxLayout(tab_edit)
        layout_edit.setContentsMargins(4, 0, 0, 0)
        layout_edit.addWidget(tb_edit)
        self.toolbar_tabs.addTab(tab_edit, "編輯")
        # 頁面
        tab_page = QWidget()
        tb_page = QToolBar()
        tb_page.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb_page.setStyleSheet(toolbar_style)
        tb_page.addAction("刪除頁", self._delete_pages)
        tb_page.addAction("旋轉頁", self._rotate_pages)
        tb_page.addAction("匯出頁", self._export_pages)
        tb_page.addAction("插入空白頁", self._insert_blank_page)
        tb_page.addAction("從檔案插入頁", self._insert_pages_from_file)
        layout_page = QVBoxLayout(tab_page)
        layout_page.setContentsMargins(4, 0, 0, 0)
        layout_page.addWidget(tb_page)
        self.toolbar_tabs.addTab(tab_page, "頁面")
        # 轉換
        tab_convert = QWidget()
        tb_convert = QToolBar()
        tb_convert.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb_convert.setStyleSheet(toolbar_style)
        tb_convert.addAction("OCR（文字辨識）", self._ocr_pages)
        layout_convert = QVBoxLayout(tab_convert)
        layout_convert.setContentsMargins(4, 0, 0, 0)
        layout_convert.addWidget(tb_convert)
        self.toolbar_tabs.addTab(tab_convert, "轉換")

        bar_layout.addWidget(self.toolbar_tabs, 1)  # 讓分頁區優先取得水平空間
        # Fixed right section: 頁 X / Y, Zoom, 適應畫面, 復原, 重做
        # 根因 1 排除：放寬上限，避免整區過窄導致 QToolBar 溢出（»）
        right_widget = QWidget()
        right_widget.setMaximumWidth(420)
        right_layout = QHBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.page_counter_label = QLabel("頁 1 / 1")
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setMinimumWidth(88)  # 放寬以完整顯示「100%」「200%」等縮放數字
        for pct in [50, 75, 100, 125, 150, 200]:
            self.zoom_combo.addItem(f"{pct}%")
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_combo_changed)
        fit_btn = QPushButton("適應畫面")
        fit_btn.clicked.connect(self._fit_to_view)
        self._action_undo_right = QAction("↺ 復原", self)
        self._action_undo_right.triggered.connect(self.sig_undo.emit)
        self._action_redo_right = QAction("↻ 重做", self)
        self._action_redo_right.triggered.connect(self.sig_redo.emit)
        right_layout.addWidget(self.page_counter_label)
        right_layout.addWidget(QLabel(" "))
        right_layout.addWidget(self.zoom_combo)
        right_layout.addWidget(fit_btn)
        # 根因 2 排除：移除 stretch，避免佔滿剩餘空間、把 QToolBar 擠成只顯示溢出
        # right_layout.addWidget(QWidget(), 1) 已移除
        toolbar_right = QToolBar()
        toolbar_right.addAction(self._action_undo_right)
        toolbar_right.addAction(self._action_redo_right)
        # 根因 3 排除：確保「復原」「重做」兩顆按鈕都有空間，不進溢出選單
        toolbar_right.setMinimumWidth(100)
        right_layout.addWidget(toolbar_right)
        bar_layout.addWidget(right_widget)
        bar_layout.addSpacing(12)

        self._action_undo.setToolTip("復原（無可撤銷操作）")
        self._action_redo.setToolTip("重做（無可重做操作）")

        # Ensure shortcuts remain active even when the source toolbar tab is hidden.
        for action in (
            self._action_open,
            self._action_print,
            self._action_save,
            self._action_save_as,
            self._action_undo,
            self._action_redo,
            self._action_edit_text,
        ):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)

    def _make_mode_action(self, text: str, mode: str) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        action.triggered.connect(lambda _checked=False, m=mode: self.set_mode(m))
        self._mode_action_group.addAction(action)
        self._mode_actions[mode] = action
        return action

    def _sync_mode_checked_state(self, mode: str) -> None:
        for mode_key, action in self._mode_actions.items():
            previous = action.blockSignals(True)
            action.setChecked(mode_key == mode)
            action.blockSignals(previous)

    def _on_zoom_combo_changed(self, text: str):
        try:
            pct = float(str(text).replace("%", "").strip())
            if 10 <= pct <= 400:
                self.sig_scale_changed.emit(self.current_page, pct / 100.0)
        except ValueError:
            pass

    def _fit_to_view(self):
        target_rect = None
        if self.continuous_pages and self.page_items:
            idx = min(max(self.current_page, 0), len(self.page_items) - 1)
            target_rect = self.page_items[idx].sceneBoundingRect()
        elif self.page_items:
            target_rect = self.page_items[0].sceneBoundingRect()
        elif self.scene.sceneRect().isValid():
            target_rect = self.scene.sceneRect()

        if not target_rect or not target_rect.isValid():
            return

        self.graphics_view.fitInView(target_rect, Qt.KeepAspectRatio)
        self.graphics_view.centerOn(target_rect.center())

    def _show_thumbnails_tab(self):
        self.left_sidebar.setCurrentIndex(0)

    def _show_search_tab(self):
        self.left_sidebar.setCurrentIndex(1)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _show_annotations_tab(self):
        self.left_sidebar.setCurrentIndex(2)

    def _show_watermarks_tab(self):
        self.left_sidebar.setCurrentIndex(3)
        self.sig_load_watermarks.emit()

    def _setup_left_sidebar(self):
        """Left sidebar: QTabWidget with 縮圖 / 搜尋 / 註解列表 / 浮水印列表. 260px."""
        # 縮圖 (default)
        self.thumbnail_list = QListWidget(self)
        self.thumbnail_list.setViewMode(QListWidget.IconMode)
        self.thumbnail_list.itemClicked.connect(self._on_thumbnail_clicked)
        self.left_sidebar.addTab(self.thumbnail_list, "縮圖")

        # 搜尋 (on-demand)
        self.search_panel = QWidget()
        search_layout = QVBoxLayout(self.search_panel)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("輸入文字搜尋...")
        self.search_input.returnPressed.connect(self._trigger_search)
        self.search_status_label = QLabel("找到 0 個結果")
        self.search_results_list = QListWidget()
        self.search_results_list.itemClicked.connect(self._on_search_result_clicked)
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("上一個")
        self.prev_btn.clicked.connect(self._navigate_search_previous)
        self.next_btn = QPushButton("下一個")
        self.next_btn.clicked.connect(self._navigate_search_next)
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_status_label)
        search_layout.addWidget(self.search_results_list)
        search_layout.addLayout(nav_layout)
        self.left_sidebar.addTab(self.search_panel, "搜尋")

        # 註解列表
        self.annotation_panel = QWidget()
        annot_layout = QVBoxLayout(self.annotation_panel)
        self.annotation_list = QListWidget()
        self.annotation_list.itemClicked.connect(self._on_annotation_selected)
        annot_layout.addWidget(self.annotation_list)
        self.left_sidebar.addTab(self.annotation_panel, "註解列表")

        # 浮水印列表
        self.watermark_panel = QWidget()
        wm_layout = QVBoxLayout(self.watermark_panel)
        self.watermark_list_widget = QListWidget()
        self.watermark_list_widget.itemClicked.connect(self._on_watermark_selected)
        wm_layout.addWidget(self.watermark_list_widget)
        btn_layout = QHBoxLayout()
        self.watermark_edit_btn = QPushButton("編輯")
        self.watermark_edit_btn.clicked.connect(self._edit_selected_watermark)
        self.watermark_remove_btn = QPushButton("移除")
        self.watermark_remove_btn.clicked.connect(self._remove_selected_watermark)
        btn_layout.addWidget(self.watermark_edit_btn)
        btn_layout.addWidget(self.watermark_remove_btn)
        wm_layout.addLayout(btn_layout)
        self.left_sidebar.addTab(self.watermark_panel, "浮水印列表")

    def _setup_property_inspector(self):
        """Right sidebar: 屬性 — dynamic inspector by mode (page info / 矩形設定 / 螢光筆顏色 / 文字設定). Apply/Cancel."""
        # Page info (no selection)
        self.page_info_card = QWidget()
        page_layout = QVBoxLayout(self.page_info_card)
        self.page_info_label = QLabel("頁面資訊\n尺寸、旋轉等")
        self.page_info_label.setWordWrap(True)
        page_layout.addWidget(self.page_info_label)
        page_layout.addStretch()
        self.right_stacked_widget.addWidget(self.page_info_card)

        # 矩形設定 (rect mode): Color #0078D4 default, opacity 0-1
        self.rect_card = QWidget()
        rect_layout = QVBoxLayout(self.rect_card)
        rect_layout.addWidget(QLabel("矩形設定"))
        self.rect_color = QColor(0, 120, 212, 255)  # #0078D4
        self.rect_color_btn = QPushButton("矩形顏色")
        self.rect_color_btn.setStyleSheet(f"background-color: #0078D4; color: white;")
        self.rect_color_btn.clicked.connect(self._choose_rect_color)
        rect_layout.addWidget(self.rect_color_btn)
        rect_layout.addWidget(QLabel("透明度"))
        self.rect_opacity = QSlider(Qt.Horizontal)
        self.rect_opacity.setRange(0, 100)
        self.rect_opacity.setValue(100)
        self.rect_opacity.valueChanged.connect(self._update_rect_opacity)
        rect_layout.addWidget(self.rect_opacity)
        self.rect_apply_btn = QPushButton("套用")
        self.rect_cancel_btn = QPushButton("取消")
        rect_layout.addWidget(self.rect_apply_btn)
        rect_layout.addWidget(self.rect_cancel_btn)
        rect_layout.addStretch()
        self.right_stacked_widget.addWidget(self.rect_card)

        # 螢光筆顏色 (#FFFF00)
        self.highlight_card = QWidget()
        hl_layout = QVBoxLayout(self.highlight_card)
        hl_layout.addWidget(QLabel("螢光筆顏色"))
        self.highlight_color = QColor(255, 255, 0, 128)
        self.highlight_color_btn = QPushButton("■ 螢光筆顏色")
        self.highlight_color_btn.setStyleSheet("background-color: #FFFF00;")
        self.highlight_color_btn.clicked.connect(self._choose_highlight_color)
        hl_layout.addWidget(self.highlight_color_btn)
        hl_layout.addStretch()
        self.right_stacked_widget.addWidget(self.highlight_card)

        # 文字設定: Font Source Han Serif TC, size 12pt, checkbox 垂直文字擴展時左移
        self.text_card = QWidget()
        text_layout = QVBoxLayout(self.text_card)
        text_layout.addWidget(QLabel("文字設定"))
        self.text_font = QComboBox()
        self.text_font.addItem("Sans (helv)", "helv")
        self.text_font.addItem("Serif (tiro)", "tiro")
        self.text_font.addItem("Mono (cour)", "cour")
        # Keep distinct CJK choices so CJK text can actually change family.
        self.text_font.addItem("CJK Sans (china-ss)", "china-ss")
        self.text_font.addItem("CJK Serif (china-ts)", "china-ts")
        self.text_font.addItem("CJK Auto (cjk)", "cjk")
        self.text_font.addItem("Microsoft JhengHei", "microsoft jhenghei")
        self.text_font.addItem("PMingLiU", "pmingliu")
        self.text_font.addItem("DFKai-SB", "dfkai-sb")
        self.text_font.setCurrentIndex(0)
        self.text_size = QComboBox()
        self.text_size.addItems([str(i) for i in range(8, 30, 2)])
        self.text_size.setCurrentText("12")
        text_layout.addWidget(QLabel("字型"))
        text_layout.addWidget(self.text_font)
        text_layout.addWidget(QLabel("字級大小 (pt)"))
        text_layout.addWidget(self.text_size)
        self.vertical_shift_left_cb = QCheckBox("垂直文字擴展時左移")
        self.vertical_shift_left_cb.setChecked(True)
        text_layout.addWidget(self.vertical_shift_left_cb)
        self.text_target_mode_combo = QComboBox()
        self.text_target_mode_combo.addItem("詞 / Run（精準）", "run")
        self.text_target_mode_combo.addItem("段落（整段）", "paragraph")
        self.text_target_mode_combo.setCurrentIndex(1)
        self.text_target_mode_combo.currentIndexChanged.connect(self._on_text_target_mode_changed)
        text_layout.addWidget(QLabel("文字選取粒度"))
        text_layout.addWidget(self.text_target_mode_combo)
        self.text_apply_btn = QPushButton("套用")
        self.text_cancel_btn = QPushButton("取消")
        self.text_apply_btn.clicked.connect(self._on_text_apply_clicked)
        self.text_cancel_btn.clicked.connect(self._on_text_cancel_clicked)
        text_layout.addWidget(self.text_apply_btn)
        text_layout.addWidget(self.text_cancel_btn)
        text_layout.addStretch()
        self.right_stacked_widget.addWidget(self.text_card)

    def _choose_rect_color(self):
        color = QColorDialog.getColor(self.rect_color, self, "選擇矩形顏色")
        if color.isValid():
            self.rect_color = color
            self.rect_opacity.setValue(int(color.alphaF() * 100))
            self.rect_color_btn.setStyleSheet(f"background-color: {color.name()}; color: white;")
            self._update_rect_opacity()

    def _update_rect_opacity(self):
        self.rect_color.setAlphaF(self.rect_opacity.value() / 100.0)

    def _choose_highlight_color(self):
        color = QColorDialog.getColor(self.highlight_color, self, "選擇螢光筆顏色")
        if color.isValid():
            self.highlight_color = color
            self.highlight_color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _on_text_target_mode_changed(self):
        combo = getattr(self, "text_target_mode_combo", None)
        if combo is None:
            return
        mode = combo.currentData()
        if mode not in ("run", "paragraph"):
            mode = "run"
        self.sig_text_target_mode_changed.emit(mode)
        # force hover target refresh under new granularity
        self._last_hover_scene_pos = None

    def _on_text_apply_clicked(self):
        # "Apply" commits current inline-editor content/style to the PDF.
        if self.text_editor and self.text_editor.widget():
            self._finalize_text_edit()

    def _on_text_cancel_clicked(self):
        if not self.text_editor or not self.text_editor.widget():
            return
        # One-shot discard flag consumed by _finalize_text_edit_impl.
        self._discard_text_edit_once = True
        self._finalize_text_edit()

    def _update_status_bar(self):
        """更新狀態列：已修改、模式、快捷鍵、頁/縮放；搜尋模式時顯示找到 X 個結果 • 按 Esc 關閉搜尋."""
        scale = getattr(self, "scale", 1.0)
        total = getattr(self, "total_pages", 0)
        cur = getattr(self, "current_page", 0)
        parts = []
        if getattr(self.controller, "model", None) and self.controller.model.has_unsaved_changes():
            parts.append("已修改")
        if getattr(self, "left_sidebar", None) and self.left_sidebar.currentIndex() == 1 and getattr(self, "current_search_results", None) and self.current_search_results:
            parts.append(f"找到 {len(self.current_search_results)} 個結果 • 按 Esc 關閉搜尋")
        parts.append("連續捲動")
        if total > 0:
            parts.append(f"頁面 {cur + 1}/{total}")
        parts.append(f"縮放 {int(scale * 100)}%")
        parts.append("Ctrl+K 快速指令")
        if getattr(self, "status_bar", None):
            self.status_bar.showMessage(" • ".join(parts))

    def set_mode(self, mode: str):
        mode = mode if mode in self._VALID_MODES else "browse"
        if self.text_editor:
            self._finalize_text_edit()
        if self.current_mode == 'browse' and mode != 'browse':
            self._reset_browse_hover_cursor()
            self._clear_text_selection()
        # 切換模式時清除所有拖曳/待定狀態
        self._drag_pending = False
        self._drag_active = False
        self._drag_start_scene_pos = None
        self._drag_editor_start_pos = None
        self._pending_text_info = None
        # Phase 5: 離開 edit_text 模式時清除 hover 高亮
        if mode != 'edit_text':
            self._clear_hover_highlight()
        self.current_mode = mode
        self._sync_mode_checked_state(mode)
        self.sig_mode_changed.emit(mode)
        
        if mode in ['rect', 'highlight', 'add_annotation']:
            self.graphics_view.setDragMode(QGraphicsView.NoDrag)
            self.graphics_view.viewport().setCursor(Qt.CrossCursor)
            if mode == 'rect':
                self.right_stacked_widget.setCurrentWidget(self.rect_card)
            elif mode == 'highlight':
                self.right_stacked_widget.setCurrentWidget(self.highlight_card)
            else:
                self.right_stacked_widget.setCurrentWidget(self.page_info_card)
        elif mode == 'add_text':
            self.graphics_view.setDragMode(QGraphicsView.NoDrag)
            self.graphics_view.viewport().setCursor(Qt.IBeamCursor)
            self.right_stacked_widget.setCurrentWidget(self.text_card)
            if not self._add_text_default_font_applied:
                self._set_text_font_by_pdf(self._add_text_default_pdf_font)
                if self.text_size.findText(str(self._add_text_default_size)) == -1:
                    self.text_size.addItem(str(self._add_text_default_size))
                self.text_size.setCurrentText(str(self._add_text_default_size))
                self._add_text_default_font_applied = True
        elif mode == 'edit_text':
            self.right_stacked_widget.setCurrentWidget(self.text_card)
        else:
            self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
            self._reset_browse_hover_cursor()
            self.right_stacked_widget.setCurrentWidget(self.page_info_card)
        self._update_status_bar()

    def _on_escape_shortcut(self) -> None:
        self._handle_escape()

    def _is_widget_owned_by_main(self, widget: QWidget) -> bool:
        current = widget
        while current is not None:
            if current is self:
                return True
            current = current.parentWidget()
        return False

    def _widget_has_ancestor(self, widget: QWidget, ancestor: QWidget) -> bool:
        # Walk parent chain because combo popups are child widgets under text panel controls.
        if widget is None or ancestor is None:
            return False
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = current.parentWidget()
        return False

    def _is_widget_from_text_combo_popup(self, widget: QWidget) -> bool:
        # QComboBox popup is often a top-level window; match by popup view/window lineage.
        if widget is None:
            return False
        for attr in ("text_font", "text_size", "text_target_mode_combo"):
            combo = getattr(self, attr, None)
            if combo is None:
                continue
            try:
                popup_view = combo.view()
            except Exception:
                popup_view = None
            if popup_view is None:
                continue
            if self._widget_has_ancestor(widget, combo):
                return True
            if self._widget_has_ancestor(widget, popup_view):
                return True
            try:
                if widget.window() is popup_view.window():
                    return True
            except Exception:
                pass
        return False

    def _is_scene_focus_within_editor(self) -> bool:
        # QWidget focus can transiently land on viewport while proxy editor keeps scene focus.
        if not self.text_editor:
            return False
        focus_item = self.scene.focusItem() if self.scene is not None else None
        while focus_item is not None:
            if focus_item is self.text_editor:
                return True
            focus_item = focus_item.parentItem()
        return False

    def _is_focus_within_edit_context(self, widget: QWidget) -> bool:
        # Keep editing alive when focus stays inside editor or right-side text controls.
        if widget is None:
            return False
        if self._is_widget_from_text_combo_popup(widget):
            return True
        editor_widget = self.text_editor.widget() if (self.text_editor and self.text_editor.widget()) else None
        if editor_widget and self._widget_has_ancestor(widget, editor_widget):
            return True
        return self._widget_has_ancestor(widget, self.text_card)

    def _set_edit_focus_guard(self, enabled: bool) -> None:
        # Track app-level focus changes while inline editor is open.
        app = QApplication.instance()
        if app is None:
            self._edit_focus_guard_connected = False
            return
        if enabled and not self._edit_focus_guard_connected:
            app.focusChanged.connect(self._on_app_focus_changed)
            self._edit_focus_guard_connected = True
            return
        if not enabled and self._edit_focus_guard_connected:
            try:
                app.focusChanged.disconnect(self._on_app_focus_changed)
            except (TypeError, RuntimeError):
                pass
            self._edit_focus_guard_connected = False

    def _schedule_finalize_on_focus_change(self) -> None:
        # Defer decision until Qt finishes focus handoff (popup/editor/control transitions).
        if self._edit_focus_check_pending:
            return
        self._edit_focus_check_pending = True
        QTimer.singleShot(40, self._finalize_if_focus_outside_edit_context)

    def _finalize_if_focus_outside_edit_context(self) -> None:
        # Finalize only when focus truly leaves edit context.
        self._edit_focus_check_pending = False
        if self._finalizing_text_edit:
            return
        if not self.text_editor or not self.text_editor.widget():
            return
        app = QApplication.instance()
        focus_widget = app.focusWidget() if app is not None else None
        if self._is_focus_within_edit_context(focus_widget):
            return
        if app is not None:
            active_popup = app.activePopupWidget()
            if self._is_focus_within_edit_context(active_popup):
                return
        if self._is_scene_focus_within_editor():
            return
        self._finalize_text_edit()

    def _on_app_focus_changed(self, _old: QWidget, new: QWidget) -> None:
        # App-level safety net for focus moves that bypass QTextEdit focusOut details.
        if not self.text_editor or not self.text_editor.widget():
            return
        if self._is_focus_within_edit_context(new):
            return
        self._schedule_finalize_on_focus_change()

    def _on_editor_focus_out(self, event, base_handler) -> None:
        # Preserve original QTextEdit behavior, then run guarded finalize logic.
        base_handler(event)
        self._schedule_finalize_on_focus_change()

    def _focus_page_canvas(self) -> None:
        self.graphics_view.setFocus(Qt.ShortcutFocusReason)
        self.graphics_view.viewport().setFocus(Qt.ShortcutFocusReason)

    def _handle_escape(self) -> bool:
        if self.text_editor:
            self._finalize_text_edit()
            self._focus_page_canvas()
            return True

        app = QApplication.instance()
        if app is not None:
            for candidate in (app.activeModalWidget(), app.activePopupWidget()):
                if candidate is not None and self._is_widget_owned_by_main(candidate):
                    if hasattr(candidate, "reject"):
                        candidate.reject()
                    else:
                        candidate.close()
                    self._focus_page_canvas()
                    return True

        if self.current_mode != 'browse':
            self.set_mode('browse')
            self._focus_page_canvas()
            return True

        if self.left_sidebar.currentIndex() == 1:
            self.left_sidebar.setCurrentIndex(0)
            self._update_status_bar()
            return True
        return False

    def update_undo_redo_tooltips(self, undo_tip: str, redo_tip: str) -> None:
        """更新復原/重做按鈕的 tooltip，顯示下一步操作描述。"""
        for action in (getattr(self, '_action_undo', None), getattr(self, '_action_undo_right', None)):
            if action:
                action.setToolTip(undo_tip)
        for action in (getattr(self, '_action_redo', None), getattr(self, '_action_redo_right', None)):
            if action:
                action.setToolTip(redo_tip)

    def _update_page_counter(self):
        n = max(1, self.total_pages)
        cur = min(self.current_page + 1, n)
        self.page_counter_label.setText(f"頁 {cur} / {n}")
        pct = int(round(self.scale * 100))
        text = f"{pct}%"
        if self.zoom_combo.currentText() != text:
            self.zoom_combo.blockSignals(True)
            if self.zoom_combo.findText(text) < 0:
                self.zoom_combo.addItem(text)
            self.zoom_combo.setCurrentText(text)
            self.zoom_combo.blockSignals(False)

    def keyPressEvent(self, event):
        direction = self._tab_shortcut_direction(event.key(), event.modifiers())
        if direction and self._cycle_document_tab(direction):
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            if self._handle_escape():
                event.accept()
                return
        if self.current_mode == 'browse' and event.matches(QKeySequence.Copy):
            if self._copy_selected_text_to_clipboard():
                event.accept()
                return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_F:
            self._show_search_tab()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.graphics_view.viewport() and event.type() == QEvent.Leave:
            if self.current_mode == 'browse':
                self._reset_browse_hover_cursor()
        return super().eventFilter(obj, event)

    def update_thumbnails(self, thumbnails: List[QPixmap]):
        """一次設定全部縮圖（相容舊流程）。"""
        self.thumbnail_list.clear()
        for i, pix in enumerate(thumbnails):
            self.thumbnail_list.addItem(QListWidgetItem(QIcon(pix), f"頁{i+1}"))
        self.total_pages = len(thumbnails)
        self._update_page_counter()
        self._update_status_bar()

    def set_thumbnail_placeholders(self, total: int):
        """僅建立縮圖列表佔位（頁碼），供後續分批更新圖示。"""
        self.thumbnail_list.clear()
        for i in range(total):
            self.thumbnail_list.addItem(QListWidgetItem(f"頁{i+1}"))
        self.total_pages = total
        self._update_page_counter()
        self._update_status_bar()

    def update_thumbnail_batch(self, start_index: int, pixmaps: List[QPixmap]):
        """從 start_index 起更新一批縮圖的圖示。"""
        for i, pix in enumerate(pixmaps):
            row = start_index + i
            if row >= self.thumbnail_list.count():
                break
            item = self.thumbnail_list.item(row)
            if item and not pix.isNull():
                item.setIcon(QIcon(pix))

    def reset_document_view(self) -> None:
        """Reset canvas/sidebar/search state when no document sessions remain."""
        if self.text_editor:
            self._finalize_text_edit()
        self._clear_hover_highlight()
        self._reset_browse_hover_cursor()
        self._clear_text_selection()
        self._disconnect_scroll_handler()
        self.scene.clear()
        self.page_items.clear()
        self.page_y_positions.clear()
        self.page_heights.clear()
        self.thumbnail_list.clear()
        self.total_pages = 0
        self.current_page = 0
        self._render_scale = self.scale if self.scale > 0 else 1.0
        self.clear_search_ui_state()
        self._update_page_counter()
        self._update_status_bar()

    def display_all_pages_continuous(self, pixmaps: List[QPixmap]):
        """建立連續頁面場景：所有頁面由上到下排列，可捲動切換。"""
        if self.text_editor:
            self._finalize_text_edit()
        # Phase 5: scene.clear() 會銷毀所有場景物件，必須先重置 hover item 引用，
        #          否則後續 setRect() 會操作已刪除的 C++ 物件，拋出 RuntimeError。
        self._clear_hover_highlight()
        self._reset_browse_hover_cursor()
        self._clear_text_selection()
        self._disconnect_scroll_handler()
        self.scene.clear()
        self.page_items.clear()
        self.page_y_positions.clear()
        self.page_heights.clear()
        if not pixmaps:
            return
        y = 0.0
        max_w = 0.0
        for i, pix in enumerate(pixmaps):
            if pix.isNull():
                continue
            self.page_y_positions.append(y)
            h = pix.height()
            self.page_heights.append(h)
            item = self.scene.addPixmap(pix)
            item.setPos(0, y)
            self.page_items.append(item)
            max_w = max(max_w, pix.width())
            y += h + self.PAGE_GAP
        self.scene.setSceneRect(0, 0, max(1, max_w), max(1, y))
        # 讓 view 使用與 scene 相同的 sceneRect，否則捲軸與可見區域會卡在開檔時單頁的 rect，無法捲動／跳頁
        self.graphics_view.setSceneRect(self.scene.sceneRect())
        self.current_page = 0
        # pixmap 已以 self.scale 渲染完畢 → 更新 _render_scale
        self._render_scale = self.scale
        # view transform 重設為 identity：scale 已烘焙進 pixmap，不需再疊加 view 縮放
        self.graphics_view.setTransform(QTransform())
        self._connect_scroll_handler()
        self.scroll_to_page(0)
        self._sync_thumbnail_selection()

    def append_pages_continuous(self, pixmaps: List[QPixmap], start_index: int):
        """在連續場景中從 start_index 起追加一批頁面（用於分批載入）。"""
        if not pixmaps:
            return
        if start_index == 0:
            self.display_all_pages_continuous(pixmaps)
            return
        y = self.page_y_positions[-1] + self.page_heights[-1] + self.PAGE_GAP if self.page_y_positions else 0.0
        max_w = self.scene.sceneRect().width() if self.scene.sceneRect().isValid() else 0.0
        for i, pix in enumerate(pixmaps):
            if pix.isNull():
                continue
            self.page_y_positions.append(y)
            h = pix.height()
            self.page_heights.append(h)
            item = self.scene.addPixmap(pix)
            item.setPos(0, y)
            self.page_items.append(item)
            max_w = max(max_w, pix.width())
            y += h + self.PAGE_GAP
        self.scene.setSceneRect(0, 0, max(1, max_w), max(1, y))
        self.graphics_view.setSceneRect(self.scene.sceneRect())
        self._sync_thumbnail_selection()

    def _connect_scroll_handler(self):
        if self._scroll_handler_connected:
            return
        sb = self.graphics_view.verticalScrollBar()
        if sb:
            sb.valueChanged.connect(self._on_scroll_changed)
            self._scroll_handler_connected = True

    def _disconnect_scroll_handler(self):
        if not self._scroll_handler_connected:
            return
        sb = self.graphics_view.verticalScrollBar()
        if sb:
            try:
                sb.valueChanged.disconnect(self._on_scroll_changed)
            except Exception:
                pass
        self._scroll_handler_connected = False

    def _on_scroll_changed(self, value: int):
        if self._scroll_block or not self.page_y_positions:
            return
        vp = self.graphics_view.viewport()
        c = vp.rect().center()
        # viewport 是 view 的子元件，用 mapTo 將視埠座標轉為 view 座標（mapFrom 要求 parent，會報錯）
        p_view = vp.mapTo(self.graphics_view, c)
        center_scene = self.graphics_view.mapToScene(p_view).y()
        idx = self._scene_y_to_page_index(center_scene)
        if idx != self.current_page and 0 <= idx < len(self.page_items):
            self.current_page = idx
            self._sync_thumbnail_selection()

    def _scene_y_to_page_index(self, scene_y: float) -> int:
        """將場景 Y 座標轉為頁碼索引。"""
        if not self.page_y_positions or not self.page_heights:
            return 0
        for i in range(len(self.page_y_positions)):
            end = self.page_y_positions[i] + self.page_heights[i]
            if scene_y < end:
                return i
        return len(self.page_y_positions) - 1

    def _scene_pos_to_page_and_doc_point(self, scene_pos: QPointF) -> Tuple[int, fitz.Point]:
        """將場景座標轉為 (頁索引, 文件座標)。連續模式會扣掉頁頂偏移。
        
        注意：scene 座標 = PDF_points × _render_scale（pixmap 實際渲染 scale），
        與 self.scale（UI 期望縮放）可能不同（wheel debounce 尚未重渲時）。
        """
        rs = self._render_scale if self._render_scale > 0 else 1.0
        if self.continuous_pages and self.page_y_positions and self.page_heights:
            idx = self._scene_y_to_page_index(scene_pos.y())
            y0 = self.page_y_positions[idx]
            doc_y = (scene_pos.y() - y0) / rs
            return idx, fitz.Point(scene_pos.x() / rs, doc_y)
        return self.current_page, fitz.Point(scene_pos.x() / rs, scene_pos.y() / rs)

    def _sync_thumbnail_selection(self):
        """依 current_page 同步縮圖列表選取。"""
        if not self.thumbnail_list.count() or self.current_page < 0:
            return
        row = min(self.current_page, self.thumbnail_list.count() - 1)
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.setCurrentRow(row)
        self.thumbnail_list.blockSignals(False)

    def scroll_to_page(self, page_idx: int):
        """捲動至指定頁面，使該頁置中顯示。若目標頁尚未載入則捲動至最後已載入頁。"""
        if not self.page_y_positions or not self.page_heights:
            return
        n_pos = len(self.page_y_positions)
        if page_idx < 0:
            page_idx = 0
        elif page_idx >= n_pos and n_pos > 0:
            page_idx = n_pos - 1
        self._scroll_block = True
        try:
            y = self.page_y_positions[page_idx]
            h = self.page_heights[page_idx]
            cx = self.scene.sceneRect().width() / 2 if self.scene.sceneRect().width() > 0 else 0
            cy = y + h / 2
            self.graphics_view.centerOn(QPointF(cx, cy))
            self.current_page = page_idx
            self._sync_thumbnail_selection()
            self._update_page_counter()
            self._update_status_bar()
        finally:
            self._scroll_block = False

    def update_page_in_scene(self, page_idx: int, pix: QPixmap):
        """更新連續場景中某一頁的 pixmap。"""
        if page_idx < 0 or page_idx >= len(self.page_items) or pix.isNull():
            return
        self.page_items[page_idx].setPixmap(pix)
        # 若尺寸變了，更新高度記錄（同一 scale 下通常不變）
        h = pix.height()
        if page_idx < len(self.page_heights) and self.page_heights[page_idx] != h:
            self.page_heights[page_idx] = h

    def display_page(self, page_num: int, pix: QPixmap, highlight_rect: fitz.Rect = None):
        if self.text_editor:
            self._finalize_text_edit()
        self._clear_text_selection()
        if not pix.isNull() and self.continuous_pages and self.page_items:
            # 連續模式：update_page_in_scene 不清場景，hover item 仍有效，不需重置
            self.update_page_in_scene(page_num, pix)
            self.scroll_to_page(page_num)
            if highlight_rect:
                if isinstance(highlight_rect, fitz.Quad):
                    bounding_rect = highlight_rect.rect
                else:
                    bounding_rect = highlight_rect
                y0 = self.page_y_positions[page_num] if page_num < len(self.page_y_positions) else 0
                rx = bounding_rect.x0
                ry = y0 + bounding_rect.y0
                rw = bounding_rect.width
                rh = bounding_rect.height
                temp_rect_item = self.scene.addRect(rx, ry, rw, rh, QPen(QColor("red"), 2))
                cx = rx + rw / 2
                cy = ry + rh / 2
                self.graphics_view.centerOn(QPointF(cx, cy))
                QTimer.singleShot(1500, lambda: self.scene.removeItem(temp_rect_item) if temp_rect_item.scene() else None)
            return
        # 單頁模式重建場景：同樣需要先清除 hover item 引用，避免懸空指標
        self._clear_hover_highlight()
        self._reset_browse_hover_cursor()
        self.scene.clear()
        self.page_items.clear()
        self.page_y_positions.clear()
        self.page_heights.clear()
        if pix.isNull():
            return
        self.scene.addPixmap(pix)
        self.current_page = page_num
        self.graphics_view.setSceneRect(self.scene.itemsBoundingRect())
        if highlight_rect:
            if isinstance(highlight_rect, fitz.Quad):
                bounding_rect = highlight_rect.rect
            else:
                bounding_rect = highlight_rect
            temp_rect_item = self.scene.addRect(bounding_rect.x0, bounding_rect.y0, bounding_rect.width, bounding_rect.height, QPen(QColor("red"), 2))
            center_x = (bounding_rect.x0 + bounding_rect.x1) / 2
            center_y = (bounding_rect.y0 + bounding_rect.y1) / 2
            self.graphics_view.centerOn(QPointF(center_x, center_y))
            QTimer.singleShot(1500, lambda: self.scene.removeItem(temp_rect_item) if temp_rect_item.scene() else None)

    def _on_thumbnail_clicked(self, item):
        row = self.thumbnail_list.row(item)
        self.sig_page_changed.emit(row)

    def _on_search_result_clicked(self, item):
        data = item.data(Qt.UserRole)
        row = self.search_results_list.row(item)
        if data:
            self.current_search_index = row
            page_num, rect = data
            self.sig_jump_to_result.emit(page_num, rect)

    def _on_annotation_selected(self, item):
        xref = item.data(Qt.UserRole)
        if xref:
            self.sig_jump_to_annotation.emit(xref)

    def _navigate_search_previous(self):
        if not self.current_search_results: return
        self.current_search_index = (self.current_search_index - 1 + len(self.current_search_results)) % len(self.current_search_results)
        self._jump_to_search_index(self.current_search_index)

    def _navigate_search_next(self):
        if not self.current_search_results: return
        self.current_search_index = (self.current_search_index + 1) % len(self.current_search_results)
        self._jump_to_search_index(self.current_search_index)

    def _jump_to_search_index(self, index: int):
        if 0 <= index < len(self.current_search_results):
            item = self.search_results_list.item(index)
            self.search_results_list.setCurrentItem(item)
            page_num, context, rect = self.current_search_results[index]
            self.sig_jump_to_result.emit(page_num, rect)

    def _wheel_event(self, event):
        if event.modifiers() & Qt.ControlModifier:
            if self.text_editor: self._finalize_text_edit()
            factor = 1.1 if event.angleDelta().y() > 0 else 0.9
            self.scale *= factor
            # 即時套用 view transform，提供流暢的視覺縮放預覽（此時 pixmap 尚未重渲，畫面模糊屬正常）
            self.graphics_view.setTransform(self.graphics_view.transform().scale(factor, factor))
            # debounce：wheel 停止後 300ms 再重渲，避免連續滾動時每幀都重渲
            self._zoom_debounce_timer.start(300)
            event.accept()
        else:
            QGraphicsView.wheelEvent(self.graphics_view, event)

    def _on_zoom_debounce(self):
        """wheel 縮放停止後觸發：重新以當前 self.scale 渲染所有頁面，確保清晰顯示。"""
        self.sig_request_rerender.emit()

    def _mouse_press(self, event):
        scene_pos = self.graphics_view.mapToScene(event.pos())
        if event.button() == Qt.LeftButton:
            if self.current_mode == 'add_annotation':
                text, ok = QInputDialog.getMultiLineText(self, "新增註解", "請輸入註解內容:")
                if ok and text:
                    page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
                    self.sig_add_annotation.emit(page_idx, doc_point, text)
                return

            if self.current_mode == 'browse':
                page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
                try:
                    info = self.controller.get_text_info_at_point(page_idx + 1, doc_point)
                except Exception:
                    info = None
                if info:
                    self._start_text_selection(scene_pos, page_idx)
                    event.accept()
                    return
                if self._selected_text_rect_doc is not None or self._selected_text_cached:
                    self._clear_text_selection()

            if self.current_mode == 'add_text':
                if self.text_editor:
                    editor_scene_rect = self.text_editor.mapRectToScene(self.text_editor.boundingRect())
                    if editor_scene_rect.contains(scene_pos):
                        self._drag_pending = True
                        self._drag_active = False
                        self._pending_text_info = None
                        self._drag_start_scene_pos = scene_pos
                        self._drag_editor_start_pos = self.text_editor.pos()
                        return
                    self._drag_pending = False
                    self._drag_active = False
                    self._pending_text_info = None
                    self._finalize_text_edit()
                    return
                self._create_add_text_editor_at_scene(scene_pos)
                return

            if self.current_mode == 'edit_text':
                # ── 若已有開啟的編輯框 ──
                if self.text_editor:
                    editor_scene_rect = self.text_editor.mapRectToScene(self.text_editor.boundingRect())
                    if editor_scene_rect.contains(scene_pos):
                        # 點擊在編輯框內：進入待定狀態（等 release/move 決定是游標定位還是拖曳）
                        self._drag_pending = True
                        self._drag_active = False
                        self._pending_text_info = None  # 已有編輯框，不需 pending_text_info
                        self._drag_start_scene_pos = scene_pos
                        self._drag_editor_start_pos = self.text_editor.pos()
                        return
                    else:
                        # 點擊在編輯框外：先結束編輯
                        self._drag_pending = False
                        self._drag_active = False
                        self._pending_text_info = None
                        self._finalize_text_edit()
                        # Fall through：繼續判斷是否點到了新文字塊

                # ── 沒有編輯框（或剛結束），查詢點擊位置是否有文字塊 ──
                self._clear_hover_highlight()
                page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
                try:
                    info = self.controller.get_text_info_at_point(page_idx + 1, doc_point)
                    if info:
                        # 存下文字塊資訊，但先不開啟編輯框（等 release 或 drag 決定）
                        self.editing_font_name = info.font
                        self.editing_color = info.color
                        self.editing_original_text = info.target_text
                        self._editing_page_idx = page_idx
                        self._pending_text_info = (
                            info.target_bbox,
                            info.target_text,
                            info.font,
                            info.size,
                            info.color,
                            info.rotation,
                            info.target_span_id,
                            getattr(info, "target_mode", "run"),
                        )
                        self._drag_pending = True
                        self._drag_active = False
                        self._drag_start_scene_pos = scene_pos
                        self._drag_editor_start_pos = None  # 尚無編輯框
                        return
                except Exception as e:
                    logger.error(f"開啟編輯框失敗: {e}")

        if self.current_mode in ['rect', 'highlight']:
            self.drawing_start = scene_pos
        QGraphicsView.mousePressEvent(self.graphics_view, event)

    def _mouse_move(self, event):
        scene_pos = self.graphics_view.mapToScene(event.pos())

        if self.current_mode == 'browse':
            if self._text_selection_active:
                self._update_text_selection(scene_pos)
                event.accept()
                return
            if event.buttons() & Qt.LeftButton:
                self._reset_browse_hover_cursor()
            else:
                self._update_browse_hover_cursor(scene_pos)
        elif self.current_mode in ('edit_text', 'add_text'):
            # ── 待定狀態：判斷是否超過拖曳閾值 ──
            if self._drag_pending and self._drag_start_scene_pos is not None:
                dx = scene_pos.x() - self._drag_start_scene_pos.x()
                dy = scene_pos.y() - self._drag_start_scene_pos.y()
                if dx * dx + dy * dy > 25:  # 超過 5px → 確認為拖曳
                    self._drag_pending = False
                    self._drag_active = True
                    self.graphics_view.viewport().setCursor(Qt.ClosedHandCursor)

                    # 若尚無編輯框（點的是新文字塊），此時才建立並進入拖曳
                    if not self.text_editor and self._pending_text_info:
                        self._create_text_editor(*self._pending_text_info)
                        self._pending_text_info = None
                        # 記錄剛建立的編輯框初始位置，並立即套用當前偏移量
                        self._drag_editor_start_pos = self.text_editor.pos()
                        page_idx = getattr(self, '_editing_page_idx', self.current_page)
                        clamped_x, clamped_y = self._clamp_editor_pos_to_page(
                            self._drag_editor_start_pos.x() + dx,
                            self._drag_editor_start_pos.y() + dy,
                            page_idx
                        )
                        self.text_editor.setPos(clamped_x, clamped_y)
                        return

            # ── 拖曳中：持續更新位置（含頁面邊界限制）──
            if self._drag_active and self.text_editor and self._drag_editor_start_pos is not None:
                dx = scene_pos.x() - self._drag_start_scene_pos.x()
                dy = scene_pos.y() - self._drag_start_scene_pos.y()
                raw_x = self._drag_editor_start_pos.x() + dx
                raw_y = self._drag_editor_start_pos.y() + dy
                page_idx = getattr(self, '_editing_page_idx', self.current_page)
                new_x, new_y = self._clamp_editor_pos_to_page(raw_x, raw_y, page_idx)
                self.text_editor.setPos(new_x, new_y)
                return  # 拖曳中不觸發 ScrollHandDrag

            # ── hover 高亮（僅 edit_text）──
            if self.current_mode == 'edit_text' and not self.text_editor and not self._drag_pending and not self._drag_active:
                if (self._last_hover_scene_pos is None or
                        abs(scene_pos.x() - self._last_hover_scene_pos.x()) > 6 or
                        abs(scene_pos.y() - self._last_hover_scene_pos.y()) > 6):
                    self._last_hover_scene_pos = scene_pos
                    self._update_hover_highlight(scene_pos)

        QGraphicsView.mouseMoveEvent(self.graphics_view, event)

    def _update_browse_hover_cursor(self, scene_pos: QPointF) -> None:
        """In browse mode, use text-selection cursor only on editable text."""
        if self.current_mode != 'browse':
            self._reset_browse_hover_cursor()
            return
        try:
            if not hasattr(self, 'controller') or self.controller is None:
                self._reset_browse_hover_cursor()
                return
            model = getattr(self.controller, "model", None)
            if model is None or not model.doc:
                self._reset_browse_hover_cursor()
                return
            page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
            info = self.controller.get_text_info_at_point(page_idx + 1, doc_point)
            if info:
                if not self._browse_text_cursor_active:
                    self.graphics_view.viewport().setCursor(Qt.IBeamCursor)
                    self._browse_text_cursor_active = True
            else:
                self._reset_browse_hover_cursor()
        except Exception:
            self._reset_browse_hover_cursor()

    def _reset_browse_hover_cursor(self) -> None:
        if self.current_mode == 'browse':
            self.graphics_view.viewport().setCursor(Qt.ArrowCursor)
        self._browse_text_cursor_active = False

    def _get_page_scene_rect(self, page_idx: int) -> QRectF:
        rs = self._render_scale if self._render_scale > 0 else 1.0
        try:
            page = self.controller.model.doc[page_idx]
            page_w_scene = page.rect.width * rs
            page_h_scene = page.rect.height * rs
        except Exception:
            page_w_scene = 595.0 * rs
            page_h_scene = 842.0 * rs
        y0 = self.page_y_positions[page_idx] if (self.continuous_pages and page_idx < len(self.page_y_positions)) else 0.0
        return QRectF(0.0, y0, max(1.0, page_w_scene), max(1.0, page_h_scene))

    def _clamp_scene_point_to_page(self, scene_pos: QPointF, page_idx: int) -> QPointF:
        page_rect = self._get_page_scene_rect(page_idx)
        x = min(max(scene_pos.x(), page_rect.left()), page_rect.right())
        y = min(max(scene_pos.y(), page_rect.top()), page_rect.bottom())
        return QPointF(x, y)

    def _scene_rect_to_doc_rect(self, scene_rect: QRectF, page_idx: int) -> Optional[fitz.Rect]:
        rs = self._render_scale if self._render_scale > 0 else 1.0
        y0 = self.page_y_positions[page_idx] if (self.continuous_pages and page_idx < len(self.page_y_positions)) else 0.0
        x0 = min(scene_rect.left(), scene_rect.right()) / rs
        x1 = max(scene_rect.left(), scene_rect.right()) / rs
        y0_doc = (min(scene_rect.top(), scene_rect.bottom()) - y0) / rs
        y1_doc = (max(scene_rect.top(), scene_rect.bottom()) - y0) / rs
        rect = fitz.Rect(x0, y0_doc, x1, y1_doc)
        try:
            page_rect = self.controller.model.doc[page_idx].rect
            rect = fitz.Rect(
                max(rect.x0, page_rect.x0),
                max(rect.y0, page_rect.y0),
                min(rect.x1, page_rect.x1),
                min(rect.y1, page_rect.y1),
            )
        except Exception:
            pass
        if rect.width <= 0 or rect.height <= 0:
            return None
        return rect

    def _build_add_text_visual_rect(self, page_idx: int, doc_point: fitz.Point) -> fitz.Rect:
        model = getattr(self.controller, "model", None)
        if model is None or not model.doc:
            return fitz.Rect(doc_point.x, doc_point.y, doc_point.x + 1, doc_point.y + 1)
        page = model.doc[page_idx]
        page_rect = fitz.Rect(page.rect)
        w = float(self._add_text_default_width_pt)
        h = float(self._add_text_default_height_pt)
        rect = fitz.Rect(doc_point.x, doc_point.y, doc_point.x + w, doc_point.y + h)
        rect = fitz.Rect(
            max(page_rect.x0, rect.x0),
            max(page_rect.y0, rect.y0),
            min(page_rect.x1, rect.x1),
            min(page_rect.y1, rect.y1),
        )
        if rect.width < 8:
            rect.x1 = min(page_rect.x1, rect.x0 + 8)
        if rect.height < 8:
            rect.y1 = min(page_rect.y1, rect.y0 + 8)
        return rect

    def _create_add_text_editor_at_scene(self, scene_pos: QPointF) -> None:
        if not hasattr(self, "controller") or self.controller is None:
            return
        model = getattr(self.controller, "model", None)
        if model is None or not model.doc:
            return
        page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
        visual_rect = self._build_add_text_visual_rect(page_idx, doc_point)
        font_size = self._add_text_default_size
        try:
            font_size = int(self.text_size.currentText())
        except Exception:
            pass
        selected_pdf_font = self._qt_font_to_pdf(
            str(self.text_font.currentData() or self.text_font.currentText())
        )
        page_rotation = int(model.doc[page_idx].rotation)
        self.editing_font_name = selected_pdf_font
        self.editing_color = self._add_text_default_color
        self.editing_original_text = ""
        self._editing_page_idx = page_idx
        self._create_text_editor(
            visual_rect,
            "",
            selected_pdf_font,
            font_size,
            self._add_text_default_color,
            page_rotation,
            None,
            "run",
            "add_new",
        )

    def _start_text_selection(self, scene_pos: QPointF, page_idx: int) -> None:
        self._clear_hover_highlight()
        self._reset_browse_hover_cursor()
        self._clear_text_selection()
        start_pos = self._clamp_scene_point_to_page(scene_pos, page_idx)
        self._text_selection_active = True
        self._text_selection_page_idx = page_idx
        self._text_selection_start_scene_pos = start_pos
        self._text_selection_live_doc_rect = None
        self._text_selection_last_scene_pos = None
        pen = QPen(QColor(30, 120, 255, 220), 1)
        brush = QBrush(QColor(30, 120, 255, 35))
        rect = QRectF(start_pos, start_pos).normalized()
        self._text_selection_rect_item = self.scene.addRect(rect, pen, brush)
        self._text_selection_rect_item.setZValue(20)
        # Live highlight should only appear after snapping to actual text bounds.
        self._text_selection_rect_item.setVisible(False)

    def _update_text_selection(self, scene_pos: QPointF, force: bool = False) -> None:
        if not self._text_selection_active or self._text_selection_page_idx is None:
            return
        if self._text_selection_start_scene_pos is None or self._text_selection_rect_item is None:
            return
        if not force and self._text_selection_last_scene_pos is not None:
            if (
                abs(scene_pos.x() - self._text_selection_last_scene_pos.x()) < 2.0 and
                abs(scene_pos.y() - self._text_selection_last_scene_pos.y()) < 2.0
            ):
                return
        self._text_selection_last_scene_pos = scene_pos

        end_pos = self._clamp_scene_point_to_page(scene_pos, self._text_selection_page_idx)
        rough_scene_rect = QRectF(self._text_selection_start_scene_pos, end_pos).normalized()
        rough_doc_rect = self._scene_rect_to_doc_rect(rough_scene_rect, self._text_selection_page_idx)
        if rough_doc_rect is None:
            self._text_selection_live_doc_rect = None
            self._text_selection_rect_item.setVisible(False)
            return

        try:
            selected_text = self.controller.get_text_in_rect(self._text_selection_page_idx + 1, rough_doc_rect)
        except Exception:
            selected_text = ""
        if not selected_text.strip():
            self._text_selection_live_doc_rect = None
            self._text_selection_rect_item.setVisible(False)
            return

        precise_doc_rect = fitz.Rect(rough_doc_rect)
        try:
            precise = self.controller.get_text_bounds(self._text_selection_page_idx + 1, rough_doc_rect)
            if precise is not None and precise.width > 0 and precise.height > 0:
                precise_doc_rect = fitz.Rect(precise)
        except Exception:
            pass

        self._text_selection_live_doc_rect = precise_doc_rect
        rs = self._render_scale if self._render_scale > 0 else 1.0
        y0 = self.page_y_positions[self._text_selection_page_idx] if (
            self.continuous_pages and self._text_selection_page_idx < len(self.page_y_positions)
        ) else 0.0
        precise_scene = QRectF(
            precise_doc_rect.x0 * rs,
            y0 + precise_doc_rect.y0 * rs,
            max(1.0, precise_doc_rect.width * rs),
            max(1.0, precise_doc_rect.height * rs),
        )
        self._text_selection_rect_item.setRect(precise_scene)
        self._text_selection_rect_item.setVisible(True)

    def _finalize_text_selection(self, scene_pos: QPointF) -> None:
        if not self._text_selection_active:
            return
        if self._text_selection_start_scene_pos is not None:
            dx = scene_pos.x() - self._text_selection_start_scene_pos.x()
            dy = scene_pos.y() - self._text_selection_start_scene_pos.y()
            if dx * dx + dy * dy < 4.0:
                self._clear_text_selection()
                return

        self._update_text_selection(scene_pos, force=True)
        self._text_selection_active = False
        self._text_selection_start_scene_pos = None
        self._text_selection_last_scene_pos = None
        page_idx = self._text_selection_page_idx
        if page_idx is None or self._text_selection_rect_item is None:
            self._clear_text_selection()
            return
        doc_rect = self._text_selection_live_doc_rect
        if doc_rect is None:
            self._clear_text_selection()
            return
        try:
            selected_text = self.controller.get_text_in_rect(page_idx + 1, doc_rect)
        except Exception:
            selected_text = ""
        if not selected_text.strip():
            self._clear_text_selection()
            return
        self._selected_text_page_idx = page_idx
        self._selected_text_rect_doc = fitz.Rect(doc_rect)
        self._selected_text_cached = selected_text
        rs = self._render_scale if self._render_scale > 0 else 1.0
        y0 = self.page_y_positions[page_idx] if (self.continuous_pages and page_idx < len(self.page_y_positions)) else 0.0
        precise_scene = QRectF(
            doc_rect.x0 * rs,
            y0 + doc_rect.y0 * rs,
            max(1.0, doc_rect.width * rs),
            max(1.0, doc_rect.height * rs),
        )
        self._text_selection_rect_item.setRect(precise_scene)
        self._text_selection_rect_item.setVisible(True)

    def _clear_text_selection(self) -> None:
        self._text_selection_active = False
        self._text_selection_page_idx = None
        self._text_selection_start_scene_pos = None
        self._text_selection_live_doc_rect = None
        self._text_selection_last_scene_pos = None
        self._selected_text_rect_doc = None
        self._selected_text_page_idx = None
        self._selected_text_cached = ""
        if self._text_selection_rect_item is not None:
            try:
                if self._text_selection_rect_item.scene():
                    self.scene.removeItem(self._text_selection_rect_item)
            except Exception:
                pass
            self._text_selection_rect_item = None

    def _copy_selected_text_to_clipboard(self) -> bool:
        text = (self._selected_text_cached or "").strip()
        if not text and self._selected_text_rect_doc is not None and self._selected_text_page_idx is not None:
            try:
                text = self.controller.get_text_in_rect(self._selected_text_page_idx + 1, self._selected_text_rect_doc).strip()
            except Exception:
                text = ""
        if not text:
            return False
        QApplication.clipboard().setText(text)
        self._selected_text_cached = text
        if getattr(self, "status_bar", None):
            self.status_bar.showMessage("Copied selected text", 1500)
        return True

    def _clamp_editor_pos_to_page(self, x: float, y: float, page_idx: int):
        """將編輯框的場景座標（左上角）限制在指定頁面的邊界內，回傳 (x, y)。"""
        rs = self._render_scale if self._render_scale > 0 else 1.0
        try:
            page = self.controller.model.doc[page_idx]
            page_w_scene = page.rect.width * rs
            page_h_scene = page.rect.height * rs
        except Exception:
            page_w_scene = 595 * rs
            page_h_scene = 842 * rs

        page_x0 = 0.0
        page_y0 = (self.page_y_positions[page_idx]
                   if (self.continuous_pages and page_idx < len(self.page_y_positions))
                   else 0.0)
        page_x1 = page_x0 + page_w_scene
        page_y1 = page_y0 + page_h_scene

        # 取得編輯框的視覺尺寸（若尚未建立則用預設值）
        if self.text_editor:
            w = self.text_editor.widget().width()
            h = self.text_editor.widget().height()
        else:
            w, h = 100.0, 30.0

        clamped_x = max(page_x0, min(x, page_x1 - w))
        clamped_y = max(page_y0, min(y, page_y1 - h))
        return clamped_x, clamped_y

    def _update_hover_highlight(self, scene_pos: QPointF) -> None:
        """查詢滑鼠下方的文字塊，以半透明藍框標示可點擊範圍。"""
        try:
            if not hasattr(self, 'controller') or not self.controller.model.doc:
                self._clear_hover_highlight()
                return
            page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
            info = self.controller.get_text_info_at_point(page_idx + 1, doc_point)
            if info:
                doc_rect: fitz.Rect = info.target_bbox
                y0 = (self.page_y_positions[page_idx]
                      if (self.continuous_pages and page_idx < len(self.page_y_positions))
                      else 0.0)
                rs = self._render_scale if self._render_scale > 0 else 1.0
                scene_rect = QRectF(
                    doc_rect.x0 * rs,
                    y0 + doc_rect.y0 * rs,
                    doc_rect.width * rs,
                    doc_rect.height * rs,
                )
                pen = QPen(QColor(30, 120, 255, 200), 2)
                brush = QBrush(QColor(30, 120, 255, 35))
                if self._hover_highlight_item is None:
                    self._hover_highlight_item = self.scene.addRect(scene_rect, pen, brush)
                    self._hover_highlight_item.setZValue(10)   # 浮在頁面圖像上方
                else:
                    self._hover_highlight_item.setRect(scene_rect)
                    self._hover_highlight_item.setPen(pen)
                    self._hover_highlight_item.setBrush(brush)
            else:
                self._clear_hover_highlight()
        except Exception as e:
            logger.debug(f"hover highlight update failed: {e}")
            self._clear_hover_highlight()

    def _clear_hover_highlight(self) -> None:
        """移除 hover 高亮框並重置節流快取。"""
        if self._hover_highlight_item is not None:
            try:
                if self._hover_highlight_item.scene():
                    self.scene.removeItem(self._hover_highlight_item)
            except Exception:
                pass
            self._hover_highlight_item = None
        self._last_hover_scene_pos = None

    def _mouse_release(self, event):
        # ── 拖曳移動文字框的放開處理 ──
        if self.current_mode == 'browse' and event.button() == Qt.LeftButton and self._text_selection_active:
            scene_pos = self.graphics_view.mapToScene(event.pos())
            self._finalize_text_selection(scene_pos)
            event.accept()
            return

        if self.current_mode in ('edit_text', 'add_text') and event.button() == Qt.LeftButton:
            scene_pos = self.graphics_view.mapToScene(event.pos())

            if self._drag_pending:
                self._drag_pending = False
                if self.text_editor:
                    # 已開啟編輯框（點的是框內）→ 定位游標
                    editor = self.text_editor.widget()
                    local_pt = self.text_editor.mapFromScene(scene_pos).toPoint()
                    cursor = editor.cursorForPosition(local_pt)
                    editor.setTextCursor(cursor)
                    editor.setFocus()
                elif self._pending_text_info:
                    # 無編輯框（點的是新文字塊）→ 開啟編輯框
                    try:
                        self._create_text_editor(*self._pending_text_info)
                    except Exception as e:
                        logger.error(f"開啟編輯框失敗: {e}")
                    self._pending_text_info = None
                return

            if self._drag_active:
                # 拖曳結束 → 更新 editing_rect 為新的 PDF 座標（已被 clamp 在頁內）
                self._drag_active = False
                self._pending_text_info = None
                if self.current_mode == 'add_text':
                    self.graphics_view.viewport().setCursor(Qt.IBeamCursor)
                else:
                    self.graphics_view.viewport().setCursor(Qt.ArrowCursor)
                if self.text_editor:
                    proxy_pos = self.text_editor.pos()
                    page_idx = getattr(self, '_editing_page_idx', self.current_page)
                    y0 = self.page_y_positions[page_idx] if (self.continuous_pages and page_idx < len(self.page_y_positions)) else 0
                    orig = self._editing_original_rect
                    rs = self._render_scale if self._render_scale > 0 else 1.0
                    orig_w = orig.width if orig else 100 / rs
                    orig_h = orig.height if orig else 30 / rs
                    new_x0 = proxy_pos.x() / rs
                    new_y0 = (proxy_pos.y() - y0) / rs
                    self.editing_rect = fitz.Rect(new_x0, new_y0, new_x0 + orig_w, new_y0 + orig_h)
                    logger.debug(f"文字框拖曳完成，新 rect={self.editing_rect}")
                return

        if not self.drawing_start or self.current_mode not in ['rect', 'highlight']:
            QGraphicsView.mouseReleaseEvent(self.graphics_view, event)
            return

        end_pos = self.graphics_view.mapToScene(event.pos())
        rect = QRectF(self.drawing_start, end_pos).normalized()
        cy = (rect.top() + rect.bottom()) / 2
        page_idx = self._scene_y_to_page_index(cy) if (self.continuous_pages and self.page_y_positions) else self.current_page
        y0 = self.page_y_positions[page_idx] if (self.continuous_pages and page_idx < len(self.page_y_positions)) else 0
        fitz_rect = fitz.Rect(rect.x() / self.scale, (rect.y() - y0) / self.scale,
                              rect.right() / self.scale, (rect.bottom() - y0) / self.scale)

        if self.current_mode == 'highlight':
            color = self.highlight_color.getRgbF()
            self.sig_add_highlight.emit(page_idx + 1, fitz_rect, color)
        elif self.current_mode == 'rect':
            color = self.rect_color.getRgbF()
            fill = QMessageBox.question(self, "矩形", "是否填滿?") == QMessageBox.Yes
            self.sig_add_rect.emit(page_idx + 1, fitz_rect, color, fill)
        
        self.drawing_start = None
        QGraphicsView.mouseReleaseEvent(self.graphics_view, event)

    def _create_text_editor(
        self,
        rect: fitz.Rect,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple = (0, 0, 0),
        rotation: int = 0,
        target_span_id: str = None,
        target_mode: str = "run",
        editor_intent: str = "edit_existing",
    ):
        """建立文字編輯框，設定寬度與換行以預覽渲染後的排版（與 PDF insert_htmlbox 一致）。"""
        if self.text_editor:
            self._finalize_text_edit()

        page_idx = getattr(self, '_editing_page_idx', self.current_page)
        render_width_pt = self.controller.model.get_render_width_for_edit(page_idx + 1, rect, rotation, font_size)
        rs = self._render_scale if self._render_scale > 0 else 1.0
        scaled_width = int(render_width_pt * rs)
        scaled_rect = rect * rs

        self.editing_rect = rect
        self._editing_original_rect = fitz.Rect(rect)  # 保存原始位置，拖曳時不覆蓋
        y0 = self.page_y_positions[page_idx] if (self.continuous_pages and page_idx < len(self.page_y_positions)) else 0
        pos_x = scaled_rect.x0
        pos_y = y0 + scaled_rect.y0

        editor = QTextEdit(text)
        editor.setProperty("original_text", text)
        self._editing_rotation = rotation
        self.editing_target_span_id = target_span_id
        self.editing_target_mode = target_mode if target_mode in ("run", "paragraph") else "run"
        self.editing_intent = editor_intent if editor_intent in ("edit_existing", "add_new") else "edit_existing"

        qt_font = self._pdf_font_to_qt(font_name)
        editor.setFont(QFont(qt_font, int(font_size)))

        r, g, b = [int(c * 255) for c in color]
        editor.setStyleSheet(f"background-color: rgba(255, 255, 150, 0.8); border: 1px solid blue; color: rgb({r},{g},{b});")

        editor.setFixedWidth(max(scaled_width, 80))
        editor.setMinimumHeight(max(scaled_rect.height, 40))
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapAnywhere)

        size_str = str(round(font_size))
        if self.text_size.findText(size_str) == -1:
            self.text_size.addItem(size_str)
            items = sorted([self.text_size.itemText(i) for i in range(self.text_size.count())], key=int)
            self.text_size.clear()
            self.text_size.addItems(items)
        self.text_size.setCurrentText(size_str)
        normalized_font = self._qt_font_to_pdf(font_name)
        self._set_text_font_by_pdf(normalized_font)
        self._editing_initial_font_name = normalized_font
        self._editing_initial_size = int(round(font_size))
        if not hasattr(self, "editing_font_name"):
            self.editing_font_name = normalized_font
        if not getattr(self, '_edit_font_size_connected', False):
            self.text_size.currentTextChanged.connect(self._on_edit_font_size_changed)
            self._edit_font_size_connected = True
        if not getattr(self, '_edit_font_family_connected', False):
            self.text_font.currentIndexChanged.connect(self._on_edit_font_family_changed)
            self._edit_font_family_connected = True

        self.text_editor = self.scene.addWidget(editor)
        self.text_editor.setPos(pos_x, pos_y)
        # Ensure Esc works even when the embedded QTextEdit has focus inside QGraphicsProxyWidget.
        editor_esc = QShortcut(QKeySequence(Qt.Key_Escape), editor)
        editor_esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        editor_esc.activated.connect(self._on_escape_shortcut)
        editor._escape_shortcut = editor_esc
        original_key_press = editor.keyPressEvent
        def _editor_key_press(event):
            if event.key() == Qt.Key_Escape and self._handle_escape():
                event.accept()
                return
            original_key_press(event)
        editor.keyPressEvent = _editor_key_press
        original_focus_out = editor.focusOutEvent
        def _editor_focus_out(event):
            self._on_editor_focus_out(event, original_focus_out)
        editor.focusOutEvent = _editor_focus_out
        # Activate app-level focus guard only for active inline edit sessions.
        self._set_edit_focus_guard(True)
        editor.setFocus()

    def _pdf_font_to_qt(self, font_name: str) -> str:
        """將 PDF 字型名稱映射為 Qt 可用字型，使預覽與渲染外觀相近。"""
        low = (font_name or "").strip().lower()
        if low in {"microsoft jhenghei", "microsoftjhengheiregular", "msjh"}:
            return "Microsoft JhengHei"
        if low in {"pmingliu", "mingliu"}:
            return "PMingLiU"
        if low in {"dfkai-sb", "dfkaishu-sb-estd-bf", "kaiu"}:
            return "DFKai-SB"
        if low in {"china-ts", "china-t"}:
            return "PMingLiU"
        if low in {"cjk", "china-ss", "china-s"}:
            return "Microsoft JhengHei"
        if low.startswith("cour"):
            return "Courier New"
        if low in {"times", "tiro", "tib", "tiit", "tibo"}:
            return "Times New Roman"
        if low in {"helv", "hebo", "heit"}:
            return "Arial"
        return font_name or "Arial"

    def _set_text_font_by_pdf(self, font_name: str) -> None:
        pdf_font = self._qt_font_to_pdf(font_name)
        idx = self.text_font.findData(pdf_font)
        if idx < 0:
            idx = 0
        self.text_font.blockSignals(True)
        self.text_font.setCurrentIndex(idx)
        self.text_font.blockSignals(False)

    def _qt_font_to_pdf(self, family: str) -> str:
        low = (family or "").strip().lower()
        if low in {"microsoft jhenghei", "microsoftjhenghei", "microsoftjhengheiregular", "msjh"}:
            return "microsoft jhenghei"
        if low in {"pmingliu", "mingliu"}:
            return "pmingliu"
        if low in {"dfkai-sb", "dfkai", "dfkaishu-sb-estd-bf", "kaiu"}:
            return "dfkai-sb"
        if low in {"helv", "hebo", "heit"}:
            return "helv"
        if low in {"cour", "cour-b", "cour-i", "cour-bi"}:
            return "cour"
        if low in {"tiro", "tib", "tiit", "tibo", "times"}:
            return "tiro"
        if low in {"china-ts", "china-t"}:
            return "china-ts"
        if low in {"china-ss", "china-s"}:
            return "china-ss"
        if low in {"cjk"}:
            return "cjk"
        if any(k in low for k in ("pmingliu", "mingliu", "songti", "simsun", "source han serif", "noto serif cjk")):
            return "china-ts"
        if any(k in low for k in ("jhenghei", "yahei", "pingfang", "heiti", "source han sans", "noto sans cjk")):
            return "china-ss"
        if "cjk" in low:
            return "cjk"
        if "courier" in low or "mono" in low:
            return "cour"
        if "serif" in low:
            if any(k in low for k in ("cjk", "han", "song", "ming", "pming", "simsun", "songti")):
                return "china-ts"
            return "tiro"
        if "sans" in low:
            if any(k in low for k in ("cjk", "han", "hei", "jhenghei", "yahei", "pingfang", "noto", "source han")):
                return "china-ss"
            return "helv"
        if "times" in low:
            return "tiro"
        return "helv"

    def _on_edit_font_family_changed(self, *_):
        if not self.text_editor or not self.text_editor.widget():
            return
        editor = self.text_editor.widget()
        selected_pdf_font = self._qt_font_to_pdf(
            str(self.text_font.currentData() or self.text_font.currentText())
        )
        f = editor.font()
        f.setFamily(self._pdf_font_to_qt(selected_pdf_font))
        editor.setFont(f)
        self.editing_font_name = selected_pdf_font
        QTimer.singleShot(
            0,
            lambda: editor.setFocus(Qt.OtherFocusReason)
            if (self.text_editor and self.text_editor.widget() is editor)
            else None,
        )

    def _on_edit_font_size_changed(self, size_str: str):
        """編輯中變更字級時，更新編輯框字型以即時預覽。"""
        if not self.text_editor or not self.text_editor.widget():
            return
        try:
            sz = int(size_str)
        except (ValueError, TypeError):
            return
        editor = self.text_editor.widget()
        f = editor.font()
        f.setPointSize(sz)
        editor.setFont(f)
        # Return caret focus back to editor so user can continue typing immediately.
        QTimer.singleShot(
            0,
            lambda: editor.setFocus(Qt.OtherFocusReason)
            if (self.text_editor and self.text_editor.widget() is editor)
            else None,
        )

    def _finalize_text_edit(self):
        # Re-entrancy-safe wrapper: cleanup is done once even if multiple blur events fire.
        if self._finalizing_text_edit:
            return
        if not self.text_editor or not self.text_editor.widget():
            self._set_edit_focus_guard(False)
            self._edit_focus_check_pending = False
            return
        self._finalizing_text_edit = True
        try:
            self._finalize_text_edit_impl()
        finally:
            self._set_edit_focus_guard(False)
            self._edit_focus_check_pending = False
            self._finalizing_text_edit = False

    def _finalize_text_edit_impl(self):
        if not self.text_editor or not self.text_editor.widget(): return

        # Snapshot editor state before removing proxy widget from the scene.
        # 1. Get all necessary data out of the editor
        editor = self.text_editor.widget()
        new_text = editor.toPlainText()
        original_text_prop = editor.property("original_text")
        text_changed = new_text != original_text_prop

        # 取得原始 rect（用於在 PDF 中找到舊文字塊）與當前 rect（拖曳後的新位置）
        original_rect = self._editing_original_rect  # 編輯開始時的原始位置
        current_rect = self.editing_rect              # 可能已被拖曳更新
        position_changed = (
            original_rect is not None and current_rect is not None and
            (abs(current_rect.x0 - original_rect.x0) > 0.5 or
             abs(current_rect.y0 - original_rect.y0) > 0.5)
        )

        current_font = getattr(self, 'editing_font_name', 'helv')
        initial_font = getattr(self, '_editing_initial_font_name', current_font)
        original_color = getattr(self, 'editing_color', (0,0,0))
        current_size = int(self.text_size.currentText())
        initial_size = int(getattr(self, '_editing_initial_size', current_size))
        font_changed = (str(current_font).lower() != str(initial_font).lower())
        size_changed = current_size != initial_size
        edit_page = getattr(self, '_editing_page_idx', self.current_page)
        edit_intent = getattr(self, 'editing_intent', 'edit_existing')
        discard_changes = bool(getattr(self, "_discard_text_edit_once", False))
        self._discard_text_edit_once = False

        # 重置拖曳狀態
        self._drag_pending = False
        self._drag_active = False
        self._drag_start_scene_pos = None
        self._drag_editor_start_pos = None
        self._pending_text_info = None

        proxy_to_remove = self.text_editor
        self.text_editor = None  # 先清除，防止 focusOutEvent 遞迴呼叫
        if proxy_to_remove.scene():
            self.scene.removeItem(proxy_to_remove)
        self.editing_rect = None
        self._editing_original_rect = None
        if getattr(self, '_edit_font_size_connected', False):
            try:
                self.text_size.currentTextChanged.disconnect(self._on_edit_font_size_changed)
            except (TypeError, RuntimeError):
                pass
            self._edit_font_size_connected = False
        if getattr(self, '_edit_font_family_connected', False):
            try:
                self.text_font.currentIndexChanged.disconnect(self._on_edit_font_family_changed)
            except (TypeError, RuntimeError):
                pass
            self._edit_font_family_connected = False
        if hasattr(self, 'editing_font_name'): del self.editing_font_name
        if hasattr(self, '_editing_initial_font_name'): del self._editing_initial_font_name
        if hasattr(self, '_editing_initial_size'): del self._editing_initial_size
        if hasattr(self, 'editing_color'): del self.editing_color
        if hasattr(self, '_editing_page_idx'): del self._editing_page_idx
        if hasattr(self, '_editing_rotation'): del self._editing_rotation
        target_span_id = getattr(self, 'editing_target_span_id', None)
        if hasattr(self, 'editing_target_span_id'): del self.editing_target_span_id
        target_mode = getattr(self, 'editing_target_mode', 'run')
        if hasattr(self, 'editing_target_mode'): del self.editing_target_mode
        if hasattr(self, 'editing_intent'): del self.editing_intent

        # "Cancel" should close editor and keep document unchanged.
        if discard_changes:
            return

        if edit_intent == 'add_new':
            if new_text.strip() and current_rect is not None:
                try:
                    self.sig_add_textbox.emit(
                        edit_page + 1,
                        current_rect,
                        new_text,
                        current_font or self._add_text_default_pdf_font,
                        current_size,
                        original_color,
                    )
                except Exception as e:
                    logger.error(f"發送新增文字框信號時出錯: {e}")
            return

        if (text_changed or position_changed or font_changed or size_changed) and original_rect:
            try:
                original_text = getattr(self, 'editing_original_text', None)
                vertical_shift_left = getattr(self, 'vertical_shift_left_cb', None)
                vsl = vertical_shift_left.isChecked() if vertical_shift_left else True
                # 若位置有變動，傳入 new_rect；否則傳 None（維持原位）
                new_rect_arg = current_rect if position_changed else None
                self.sig_edit_text.emit(
                    edit_page + 1,
                    original_rect,      # 原始位置（供模型找到舊文字塊）
                    new_text,
                    current_font,
                    current_size,
                    original_color,
                    original_text,
                    vsl,
                    new_rect_arg,       # 目標新位置（None = 不移動）
                    target_span_id,
                    target_mode,
                )
            except Exception as e:
                logger.error(f"發送編輯信號時出錯: {e}")

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        if self.current_mode == 'browse' and (self._selected_text_cached or self._selected_text_rect_doc is not None):
            menu.addAction("Copy Selected Text", self._copy_selected_text_to_clipboard)
            menu.addSeparator()
        menu.addAction("旋轉頁面", self._rotate_pages)
        menu.exec_(self.graphics_view.mapToGlobal(pos))

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟PDF", "", "PDF (*.pdf)")
        if path: self.sig_open_pdf.emit(path)

    def _print_document(self):
        if self.total_pages == 0:
            show_error(self, "沒有可列印的 PDF 文件")
            return
        self.sig_print_requested.emit()

    def ask_pdf_password(self, path: str) -> Optional[str]:
        """開啟加密 PDF 時彈出密碼輸入框，回傳使用者輸入的密碼；若取消則回傳 None。"""
        dlg = PDFPasswordDialog(self, file_path=path)
        if dlg.exec() == QDialog.Accepted:
            return dlg.get_password() or None
        return None

    def _save(self):
        """存回原檔（Ctrl+S），若適用則使用增量更新。"""
        self.sig_save.emit()

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "另存PDF", "", "PDF (*.pdf)")
        if path: self.sig_save_as.emit(path)

    def _delete_pages(self):
        pages, ok = QInputDialog.getText(self, "刪除頁面", "輸入頁碼 (如 1,3-5):")
        if ok and pages:
            try:
                parsed = parse_pages(pages, self.total_pages)
                if parsed: self.sig_delete_pages.emit(parsed)
            except ValueError: show_error(self, "頁碼格式錯誤")

    def _rotate_pages(self):
        pages, ok = QInputDialog.getText(self, "旋轉頁面", "輸入頁碼 (如 1,3-5):")
        if ok and pages:
            degrees, ok = QInputDialog.getInt(self, "旋轉角度", "輸入角度 (90, 180, 270):", 90, 0, 360, 90)
            if ok:
                try:
                    parsed = parse_pages(pages, self.total_pages)
                    if parsed: self.sig_rotate_pages.emit(parsed, degrees)
                except ValueError: show_error(self, "頁碼格式錯誤")

    def _export_pages(self):
        pages, ok = QInputDialog.getText(self, "匯出頁面", "輸入頁碼 (如 1,3-5):")
        if ok and pages:
            as_image = QMessageBox.question(self, "匯出格式", "以影像格式匯出？") == QMessageBox.Yes
            path, _ = QFileDialog.getSaveFileName(self, "匯出頁面", "", "PNG (*.png)" if as_image else "PDF (*.pdf)")
            if path:
                try:
                    parsed = parse_pages(pages, self.total_pages)
                    if parsed: self.sig_export_pages.emit(parsed, path, as_image)
                except ValueError: show_error(self, "頁碼格式錯誤")

    def _show_search_panel(self):
        """Trigger search mode: switch left sidebar to Search tab, focus input (e.g. from Controller)."""
        self.left_sidebar.setCurrentIndex(1)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _show_thumbnails(self):
        self.left_sidebar.setCurrentIndex(0)

    def _show_annotation_panel(self):
        """Toggle annotations panel in left sidebar (e.g. from Controller after add)."""
        self.left_sidebar.setCurrentIndex(2)

    def _show_watermark_panel(self):
        """Toggle watermarks panel in left sidebar."""
        self.left_sidebar.setCurrentIndex(3)
        self.sig_load_watermarks.emit()

    def _show_add_watermark_dialog(self):
        if self.total_pages == 0:
            show_error(self, "請先開啟 PDF 文件")
            return
        dlg = WatermarkDialog(self, self.total_pages)
        if dlg.exec() == QDialog.Accepted:
            pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing = dlg.get_values()
            if text:
                self.sig_add_watermark.emit(pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing)
            else:
                show_error(self, "請輸入浮水印文字")

    def _on_watermark_selected(self, item):
        self._selected_watermark_id = item.data(Qt.UserRole)

    def _edit_selected_watermark(self):
        wm_id = getattr(self, '_selected_watermark_id', None)
        if not wm_id:
            show_error(self, "請先選擇要編輯的浮水印")
            return
        if not self.controller:
            return
        watermarks = self.controller.model.tools.watermark.get_watermarks()
        edit_wm = next((w for w in watermarks if w.get("id") == wm_id), None)
        if not edit_wm:
            return
        dlg = WatermarkDialog(self, self.total_pages, edit_data=edit_wm)
        if dlg.exec() == QDialog.Accepted:
            pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing = dlg.get_values()
            self.sig_update_watermark.emit(wm_id, pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing)

    def _remove_selected_watermark(self):
        wm_id = getattr(self, '_selected_watermark_id', None)
        if not wm_id:
            show_error(self, "請先選擇要移除的浮水印")
            return
        self.sig_remove_watermark.emit(wm_id)

    def populate_watermarks_list(self, watermarks: list):
        self.watermark_list_widget.clear()
        self._selected_watermark_id = None
        for wm in watermarks:
            text_preview = (wm.get("text", "") or "").replace("\n", " ")[:40]
            pages_str = ",".join(str(p) for p in sorted(wm.get("pages", []))[:5])
            if len(wm.get("pages", [])) > 5:
                pages_str += "..."
            item = QListWidgetItem(f"頁 {pages_str}: {text_preview}...")
            item.setData(Qt.UserRole, wm.get("id"))
            self.watermark_list_widget.addItem(item)

    def _trigger_search(self):
        query = self.search_input.text()
        if query:
            self.search_status_label.setText("搜尋中...")
            self.sig_search.emit(query)

    def get_search_ui_state(self) -> dict:
        return {
            "query": self.search_input.text(),
            "results": list(self.current_search_results),
            "index": self.current_search_index,
        }

    def apply_search_ui_state(self, state: Optional[dict]) -> None:
        state = state or {}
        query = state.get("query", "")
        results = list(state.get("results", []))
        idx = int(state.get("index", -1))
        self.search_input.setText(query)
        self.display_search_results(results)
        if 0 <= idx < self.search_results_list.count():
            self.current_search_index = idx
            item = self.search_results_list.item(idx)
            if item:
                self.search_results_list.setCurrentItem(item)

    def clear_search_ui_state(self) -> None:
        self.apply_search_ui_state({"query": "", "results": [], "index": -1})

    def display_search_results(self, results: List[Tuple[int, str, fitz.Rect]]):
        self.current_search_results = results
        self.current_search_index = -1
        self.search_results_list.clear()
        self.search_status_label.setText(f"找到 {len(results)} 個結果")
        self._update_status_bar()
        has_results = bool(results)
        self.prev_btn.setEnabled(has_results)
        self.next_btn.setEnabled(has_results)
        for page_num, context, rect in results:
            item = QListWidgetItem(f"頁 {page_num}: {context[:80]}...")
            item.setData(Qt.UserRole, (page_num, rect))
            self.search_results_list.addItem(item)

    def populate_annotations_list(self, annotations: List[dict]):
        self.annotation_list.clear()
        for annot in annotations:
            item = QListWidgetItem(f"頁 {annot['page_num']+1}: {annot['text'][:30]}...")
            item.setData(Qt.UserRole, annot['xref'])
            self.annotation_list.addItem(item)

    def add_annotation_to_list(self, annotation: dict):
        item = QListWidgetItem(f"頁 {annotation['page_num']+1}: {annotation['text'][:30]}...")
        item.setData(Qt.UserRole, annotation['xref'])
        self.annotation_list.addItem(item)

    def _ocr_pages(self):
        pages, ok = QInputDialog.getText(self, "OCR頁面", "輸入頁碼 (如 1,3-5):")
        if ok and pages:
            try:
                parsed = parse_pages(pages, self.total_pages)
                if parsed: self.sig_ocr.emit(parsed)
            except ValueError: show_error(self, "頁碼格式錯誤")

    def _snapshot_page(self):
        """觸發當前頁面的快照功能"""
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return
        self.sig_snapshot_page.emit(self.current_page)

    def _insert_blank_page(self):
        """插入空白頁面"""
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return
        
        # 詢問插入位置，預設為當前頁面之後
        default_position = self.current_page + 2  # 轉換為 1-based，並插入到當前頁之後
        position, ok = QInputDialog.getInt(
            self,
            "插入空白頁面",
            f"輸入插入位置 (1-{self.total_pages + 1}，1表示第一頁之前):",
            default_position,
            1,
            self.total_pages + 1,
            1
        )
        if ok:
            self.sig_insert_blank_page.emit(position)

    def _insert_pages_from_file(self):
        """從其他檔案插入頁面"""
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return
        
        # 選擇來源PDF檔案
        source_file, _ = QFileDialog.getOpenFileName(
            self,
            "選擇來源PDF檔案",
            "",
            "PDF (*.pdf)"
        )
        if not source_file:
            return
        
        # 開啟來源檔案以獲取總頁數
        try:
            source_doc = fitz.open(source_file)
            source_total_pages = len(source_doc)
            source_doc.close()
        except Exception as e:
            show_error(self, f"無法讀取來源檔案: {e}")
            return
        
        # 詢問要插入的頁碼
        pages_text, ok = QInputDialog.getText(
            self,
            "選擇要插入的頁面",
            f"輸入來源檔案中的頁碼 (如 1,3-5，總頁數: {source_total_pages}):"
        )
        if not ok or not pages_text:
            return
        
        # 解析頁碼
        try:
            source_pages = parse_pages(pages_text, source_total_pages)
            if not source_pages:
                show_error(self, "沒有選擇有效的頁面")
                return
        except ValueError as e:
            show_error(self, f"頁碼格式錯誤: {e}")
            return
        
        # 詢問插入位置
        default_position = self.current_page + 2  # 轉換為 1-based，並插入到當前頁之後
        position, ok = QInputDialog.getInt(
            self,
            "插入位置",
            f"輸入插入位置 (1-{self.total_pages + 1}，1表示第一頁之前):",
            default_position,
            1,
            self.total_pages + 1,
            1
        )
        if ok:
            self.sig_insert_pages_from_file.emit(source_file, source_pages, position)

    def _apply_scale(self):
        transform = QTransform().scale(self.scale, self.scale)
        self.graphics_view.setTransform(transform)
        self._update_page_counter()
        self._update_status_bar()

    def _resize_event(self, event):
        super().resizeEvent(event)
        if not self.scene.sceneRect().isValid():
            return
        if self.continuous_pages and self.page_items:
            # 連續模式：不 fit 整個場景，保留縮放與捲動位置
            return
        self.graphics_view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        if self.scene.items():
            self.graphics_view.centerOn(self.scene.itemsBoundingRect().center())

    def closeEvent(self, event: QCloseEvent):
        """重寫closeEvent以檢查未儲存的變更"""
        if self.controller and hasattr(self.controller, "handle_app_close"):
            self.controller.handle_app_close(event)
            return
        event.accept()
