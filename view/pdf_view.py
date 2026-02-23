from PySide6.QtWidgets import (
    QColorDialog, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QListWidget, QToolBar, QInputDialog, QMessageBox, QMenu, QDockWidget, QFileDialog,
    QListWidgetItem, QWidget, QVBoxLayout, QPushButton, QLabel, QFontComboBox,
    QComboBox, QDoubleSpinBox, QTextEdit, QGraphicsProxyWidget, QLineEdit, QHBoxLayout,
    QStackedWidget, QDialog, QSpinBox, QDialogButtonBox, QFormLayout,
    QScrollArea, QCheckBox
)
from PySide6.QtGui import QPixmap, QIcon, QCursor, QKeySequence, QColor, QFont, QPen, QBrush, QTransform, QAction, QCloseEvent, QTextOption
from PySide6.QtCore import Qt, Signal, QPointF, QTimer, QRectF, QPoint
from typing import List, Tuple
from utils.helpers import pixmap_to_qpixmap, parse_pages, show_error
import logging
import warnings
import fitz

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
    # --- Existing Signals ---
    sig_open_pdf = Signal(str)
    sig_save_as = Signal(str)
    sig_save = Signal()  # 存回原檔（Ctrl+S，使用增量更新若適用）
    sig_delete_pages = Signal(list)
    sig_rotate_pages = Signal(list, int)
    sig_export_pages = Signal(list, str, bool)
    sig_add_highlight = Signal(int, object, object)
    sig_add_rect = Signal(int, object, object, bool)
    sig_edit_text = Signal(int, object, str, str, int, tuple, str, bool, object)  # ..., new_rect(optional)
    sig_jump_to_result = Signal(int, object)
    sig_search = Signal(str)
    sig_ocr = Signal(list)
    sig_undo = Signal()
    sig_redo = Signal()
    sig_mode_changed = Signal(str)
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
        self.setWindowTitle("視覺化PDF編輯器")
        self.setGeometry(100, 100, 1200, 800)
        self.total_pages = 0
        self.controller = None

        # --- Left Dock (Thumbnails and Search) ---
        self.left_stacked_widget = QStackedWidget()
        self._setup_thumbnail_panel()
        self._setup_search_panel()
        
        self.left_dock = QDockWidget("縮圖", self)
        self.left_dock.setWidget(self.left_stacked_widget)
        self.left_dock.setFixedWidth(200)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)

        # --- Central Graphics View ---
        self.graphics_view = QGraphicsView(self)
        self.scene = QGraphicsScene(self)
        self.graphics_view.setScene(self.scene)
        self.setCentralWidget(self.graphics_view)

        # --- Toolbar ---
        self.toolbar = QToolBar(self)
        self.addToolBar(self.toolbar)
        self._add_toolbar_actions()

        # --- Right Dock (Color Settings, Annotations, Watermarks) ---
        self.right_stacked_widget = QStackedWidget()
        self._setup_color_panel()
        self._setup_annotation_panel()
        self._setup_watermark_panel()

        self.right_dock = QDockWidget("繪製設定", self)
        self.right_dock.setWidget(self.right_stacked_widget)
        self.right_dock.setFixedWidth(200)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)

        # --- State Variables ---
        self.current_mode = 'browse'
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

        self.graphics_view.wheelEvent = self._wheel_event
        self.graphics_view.mousePressEvent = self._mouse_press
        self.graphics_view.mouseMoveEvent = self._mouse_move
        self.graphics_view.mouseReleaseEvent = self._mouse_release
        self.graphics_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.graphics_view.customContextMenuRequested.connect(self._show_context_menu)
        
        self.resizeEvent = self._resize_event
        self.set_mode('browse')
        self._apply_scale()

    def _setup_thumbnail_panel(self):
        self.thumbnail_list = QListWidget(self)
        self.thumbnail_list.setViewMode(QListWidget.IconMode)
        self.thumbnail_list.itemClicked.connect(self._on_thumbnail_clicked)
        self.left_stacked_widget.addWidget(self.thumbnail_list)

    def _setup_search_panel(self):
        self.search_panel = QWidget()
        search_layout = QVBoxLayout(self.search_panel)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("輸入關鍵字後按 Enter")
        self.search_input.returnPressed.connect(self._trigger_search)
        
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("上一個")
        self.prev_btn.clicked.connect(self._navigate_search_previous)
        self.next_btn = QPushButton("下一個")
        self.next_btn.clicked.connect(self._navigate_search_next)
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)

        self.search_status_label = QLabel("請開始搜尋")
        self.search_results_list = QListWidget()
        self.search_results_list.itemClicked.connect(self._on_search_result_clicked)
        
        search_layout.addWidget(self.search_input)
        search_layout.addLayout(nav_layout)
        search_layout.addWidget(self.search_status_label)
        search_layout.addWidget(self.search_results_list)
        self.left_stacked_widget.addWidget(self.search_panel)

    def _setup_color_panel(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        self.rect_color = QColor(255, 0, 0, 255)
        self.rect_color_btn = QPushButton("矩形顏色")
        self.rect_color_btn.setStyleSheet(f"background-color: {self.rect_color.name()};")
        self.rect_color_btn.clicked.connect(self._choose_rect_color)
        self.rect_opacity = QDoubleSpinBox()
        self.rect_opacity.setRange(0.0, 1.0); self.rect_opacity.setSingleStep(0.1); self.rect_opacity.setValue(self.rect_color.alphaF())
        self.rect_opacity.valueChanged.connect(self._update_rect_opacity)
        layout.addWidget(QLabel("矩形設定")); layout.addWidget(self.rect_color_btn); layout.addWidget(QLabel("矩形透明度")); layout.addWidget(self.rect_opacity)

        self.highlight_color = QColor(255, 255, 0, 128)
        self.highlight_color_btn = QPushButton("螢光筆顏色")
        self.highlight_color_btn.setStyleSheet(f"background-color: {self.highlight_color.name()};")
        self.highlight_color_btn.clicked.connect(self._choose_highlight_color)
        layout.addWidget(QLabel("螢光筆設定")); layout.addWidget(self.highlight_color_btn)

        self.text_font = QFontComboBox(); self.text_font.setCurrentFont(QFont("Source Han Serif TC"))
        self.text_size = QComboBox(); self.text_size.addItems([str(i) for i in range(8, 30, 2)]); self.text_size.setCurrentText("12")
        layout.addWidget(QLabel("文字設定")); layout.addWidget(QLabel("字型")); layout.addWidget(self.text_font); layout.addWidget(QLabel("字級大小")); layout.addWidget(self.text_size)
        self.vertical_shift_left_cb = QCheckBox("垂直文字擴展時左移左側文字（關閉則右移右側）")
        self.vertical_shift_left_cb.setChecked(True)
        self.vertical_shift_left_cb.setToolTip("垂直文字編輯擴展時：勾選=左側文字往左移（預設）；不勾選=右側文字往右移")
        layout.addWidget(self.vertical_shift_left_cb)

        layout.addStretch()
        container.setLayout(layout)
        self.right_stacked_widget.addWidget(container)

    def _setup_annotation_panel(self):
        self.annotation_panel = QWidget()
        layout = QVBoxLayout(self.annotation_panel)
        layout.addWidget(QLabel("註解列表"))
        self.annotation_list = QListWidget()
        self.annotation_list.itemClicked.connect(self._on_annotation_selected)
        layout.addWidget(self.annotation_list)
        self.right_stacked_widget.addWidget(self.annotation_panel)

    def _setup_watermark_panel(self):
        """浮水印列表面板"""
        self.watermark_panel = QWidget()
        layout = QVBoxLayout(self.watermark_panel)
        layout.addWidget(QLabel("浮水印列表"))
        self.watermark_list_widget = QListWidget()
        self.watermark_list_widget.itemClicked.connect(self._on_watermark_selected)
        layout.addWidget(self.watermark_list_widget)
        btn_layout = QHBoxLayout()
        self.watermark_edit_btn = QPushButton("編輯")
        self.watermark_edit_btn.clicked.connect(self._edit_selected_watermark)
        self.watermark_remove_btn = QPushButton("移除")
        self.watermark_remove_btn.clicked.connect(self._remove_selected_watermark)
        btn_layout.addWidget(self.watermark_edit_btn)
        btn_layout.addWidget(self.watermark_remove_btn)
        layout.addLayout(btn_layout)
        self.right_stacked_widget.addWidget(self.watermark_panel)

    def _choose_rect_color(self):
        color = QColorDialog.getColor(self.rect_color, self, "選擇矩形顏色")
        if color.isValid():
            color.setAlphaF(self.rect_opacity.value())
            self.rect_color = color
            self.rect_color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _update_rect_opacity(self):
        self.rect_color.setAlphaF(self.rect_opacity.value())

    def _choose_highlight_color(self):
        color = QColorDialog.getColor(self.highlight_color, self, "選擇螢光筆顏色")
        if color.isValid():
            self.highlight_color = color
            self.highlight_color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _add_toolbar_actions(self):
        # File Operations
        action_save = self.toolbar.addAction("儲存", self._save)
        action_save.setShortcut(QKeySequence.Save)  # Ctrl+S
        actions_file = [("開啟", self._open_file), ("另存", self._save_as), ("刪除頁", self._delete_pages), ("旋轉頁", self._rotate_pages), ("匯出頁", self._export_pages)]
        for name, func in actions_file: self.toolbar.addAction(name, func)
        self.toolbar.addSeparator()
        
        # Insert Pages Operations
        self.toolbar.addAction("插入空白頁", self._insert_blank_page)
        self.toolbar.addAction("從檔案插入頁", self._insert_pages_from_file)
        self.toolbar.addSeparator()

        # View/Mode Switching
        actions_mode = [
            ("瀏覽", lambda: self.set_mode('browse')),
            ("縮圖", self._show_thumbnails),
            ("搜尋", self._show_search_panel, QKeySequence.Find)
        ]
        for name, func, *sc in actions_mode:
            action = self.toolbar.addAction(name, func)
            if sc: action.setShortcut(sc[0])
        self.toolbar.addSeparator()

        # Editing Tools
        actions_edit = [
            ("編輯文字", lambda: self.set_mode('edit_text'), Qt.Key_F2),
            ("矩形", lambda: self.set_mode('rect')),
            ("螢光筆", lambda: self.set_mode('highlight')),
        ]
        for name, func, *sc in actions_edit: 
            action = self.toolbar.addAction(name, func)
            if sc: action.setShortcut(QKeySequence(sc[0]))
        self.toolbar.addSeparator()

        # Annotation Tools
        self.toolbar.addAction("新增註解", lambda: self.set_mode('add_annotation'))
        self.toolbar.addAction("註解列表", self._show_annotation_panel)
        self.toolbar.addSeparator()

        # Watermark Tools
        self.toolbar.addAction("添加浮水印", self._show_add_watermark_dialog)
        self.toolbar.addAction("浮水印列表", self._show_watermark_panel)
        toggle_annot_action = QAction("顯示/隱藏註解", self)
        toggle_annot_action.setCheckable(True)
        toggle_annot_action.setChecked(True)
        toggle_annot_action.triggered.connect(self.sig_toggle_annotations_visibility)
        self.toolbar.addAction(toggle_annot_action)
        self.toolbar.addSeparator()

        # Other Tools
        self.toolbar.addAction("OCR", self._ocr_pages)
        self.toolbar.addAction("快照", self._snapshot_page)
        self.toolbar.addSeparator()

        # Undo/Redo（Phase 6：儲存 action 引用以便動態更新 tooltip）
        self._action_undo = self.toolbar.addAction("復原", self.sig_undo.emit)
        self._action_undo.setShortcut(QKeySequence.Undo)
        self._action_undo.setToolTip("復原（無可撤銷操作）")
        self._action_redo = self.toolbar.addAction("重做", self.sig_redo.emit)
        self._action_redo.setShortcut(QKeySequence.Redo)
        self._action_redo.setToolTip("重做（無可重做操作）")

    def set_mode(self, mode: str):
        if self.text_editor: self._finalize_text_edit()
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
        self.sig_mode_changed.emit(mode)
        
        if mode in ['rect', 'highlight', 'add_annotation']:
            self.graphics_view.setDragMode(QGraphicsView.NoDrag)
            self.graphics_view.viewport().setCursor(Qt.CrossCursor)
            if mode in ['rect', 'highlight']:
                self._show_color_panel()
        else:
            self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
            self.graphics_view.viewport().setCursor(Qt.ArrowCursor)

    def update_undo_redo_tooltips(self, undo_tip: str, redo_tip: str) -> None:
        """Phase 6：更新復原/重做按鈕的 tooltip，顯示下一步操作描述。"""
        if hasattr(self, '_action_undo'):
            self._action_undo.setToolTip(undo_tip)
        if hasattr(self, '_action_redo'):
            self._action_redo.setToolTip(redo_tip)

    def update_thumbnails(self, thumbnails: List[QPixmap]):
        self.thumbnail_list.clear()
        for i, pix in enumerate(thumbnails):
            self.thumbnail_list.addItem(QListWidgetItem(QIcon(pix), f"{i+1}"))
        self.total_pages = len(thumbnails)

    def display_all_pages_continuous(self, pixmaps: List[QPixmap]):
        """建立連續頁面場景：所有頁面由上到下排列，可捲動切換。"""
        if self.text_editor:
            self._finalize_text_edit()
        # Phase 5: scene.clear() 會銷毀所有場景物件，必須先重置 hover item 引用，
        #          否則後續 setRect() 會操作已刪除的 C++ 物件，拋出 RuntimeError。
        self._clear_hover_highlight()
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
        self.current_page = 0
        # pixmap 已以 self.scale 渲染完畢 → 更新 _render_scale
        self._render_scale = self.scale
        # view transform 重設為 identity：scale 已烘焙進 pixmap，不需再疊加 view 縮放
        self.graphics_view.setTransform(QTransform())
        self._connect_scroll_handler()
        self.scroll_to_page(0)
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
        """捲動至指定頁面，使該頁置中顯示。"""
        if not self.page_y_positions or not self.page_heights or page_idx < 0 or page_idx >= len(self.page_y_positions):
            return
        self._scroll_block = True
        try:
            y = self.page_y_positions[page_idx]
            h = self.page_heights[page_idx]
            cx = self.scene.sceneRect().width() / 2 if self.scene.sceneRect().width() > 0 else 0
            cy = y + h / 2
            self.graphics_view.centerOn(QPointF(cx, cy))
            self.current_page = page_idx
            self._sync_thumbnail_selection()
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
        self.sig_page_changed.emit(int(item.text()) - 1)

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
                self.set_mode('browse')
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
                        self.editing_font_name = info[2]
                        self.editing_color = info[4]
                        self.editing_original_text = info[1]
                        self._editing_page_idx = page_idx
                        self._pending_text_info = info
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

        if self.current_mode == 'edit_text':
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

            # ── hover 高亮（無編輯框且非拖曳/待定狀態）──
            if not self.text_editor and not self._drag_pending and not self._drag_active:
                if (self._last_hover_scene_pos is None or
                        abs(scene_pos.x() - self._last_hover_scene_pos.x()) > 6 or
                        abs(scene_pos.y() - self._last_hover_scene_pos.y()) > 6):
                    self._last_hover_scene_pos = scene_pos
                    self._update_hover_highlight(scene_pos)

        QGraphicsView.mouseMoveEvent(self.graphics_view, event)

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
                doc_rect: fitz.Rect = info[0]
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
        if self.current_mode == 'edit_text' and event.button() == Qt.LeftButton:
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
        self.set_mode('browse')
        QGraphicsView.mouseReleaseEvent(self.graphics_view, event)

    def _create_text_editor(self, rect: fitz.Rect, text: str, font_name: str, font_size: float, color: tuple = (0,0,0), rotation: int = 0):
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
        if not getattr(self, '_edit_font_size_connected', False):
            self.text_size.currentTextChanged.connect(self._on_edit_font_size_changed)
            self._edit_font_size_connected = True

        self.text_editor = self.scene.addWidget(editor)
        self.text_editor.setPos(pos_x, pos_y)
        editor.focusOutEvent = lambda event: self._finalize_text_edit()
        editor.setFocus()

    def _pdf_font_to_qt(self, font_name: str) -> str:
        """將 PDF 字型名稱映射為 Qt 可用字型，使預覽與渲染外觀相近。"""
        m = {"helv": "Arial", "cour": "Courier New", "times": "Times New Roman", "cjk": "Microsoft JhengHei"}
        return m.get((font_name or "").lower(), font_name or "Arial")

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

    def _finalize_text_edit(self):
        if not self.text_editor or not self.text_editor.widget(): return

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

        original_font = getattr(self, 'editing_font_name', 'helv')
        original_color = getattr(self, 'editing_color', (0,0,0))
        current_size = int(self.text_size.currentText())
        edit_page = getattr(self, '_editing_page_idx', self.current_page)

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
        if hasattr(self, 'editing_font_name'): del self.editing_font_name
        if hasattr(self, 'editing_color'): del self.editing_color
        if hasattr(self, '_editing_page_idx'): del self._editing_page_idx
        if hasattr(self, '_editing_rotation'): del self._editing_rotation

        if (text_changed or position_changed) and original_rect:
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
                    original_font,
                    current_size,
                    original_color,
                    original_text,
                    vsl,
                    new_rect_arg        # 目標新位置（None = 不移動）
                )
            except Exception as e:
                logger.error(f"發送編輯信號時出錯: {e}")

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("旋轉頁面", self._rotate_pages)
        menu.exec_(self.graphics_view.mapToGlobal(pos))

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟PDF", "", "PDF (*.pdf)")
        if path: self.sig_open_pdf.emit(path)

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
        self.left_dock.show()
        self.left_dock.setWindowTitle("搜尋")
        self.left_stacked_widget.setCurrentWidget(self.search_panel)
        self.search_input.setFocus()

    def _show_thumbnails(self):
        self.left_dock.show()
        self.left_dock.setWindowTitle("縮圖")
        self.left_stacked_widget.setCurrentWidget(self.thumbnail_list)

    def _show_color_panel(self):
        self.right_dock.show()
        self.right_dock.setWindowTitle("繪製設定")
        self.right_stacked_widget.setCurrentIndex(0) # Index 0 is color panel

    def _show_annotation_panel(self):
        self.right_dock.show()
        self.right_dock.setWindowTitle("註解列表")
        self.right_stacked_widget.setCurrentIndex(1) # Index 1 is annotation panel

    def _show_watermark_panel(self):
        self.right_dock.show()
        self.right_dock.setWindowTitle("浮水印列表")
        self.right_stacked_widget.setCurrentIndex(2)  # Index 2 is watermark panel
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
        watermarks = self.controller.model.get_watermarks()
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

    def display_search_results(self, results: List[Tuple[int, str, fitz.Rect]]):
        self.current_search_results = results
        self.current_search_index = -1
        self.search_results_list.clear()
        self.search_status_label.setText(f"找到 {len(results)} 個結果")
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
        if self.controller and self.controller.model.has_unsaved_changes():
            # 顯示提醒對話框
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("未儲存的變更")
            msg_box.setText("檔案有未儲存的變更，是否要儲存？")
            msg_box.setInformativeText("如果選擇「放棄變更」，所有變更將會遺失。")
            
            # 添加三個按鈕
            save_btn = msg_box.addButton("先存檔後關閉", QMessageBox.AcceptRole)
            discard_btn = msg_box.addButton("放棄變更直接關閉", QMessageBox.DestructiveRole)
            cancel_btn = msg_box.addButton("取消關閉", QMessageBox.RejectRole)
            
            msg_box.setDefaultButton(cancel_btn)
            msg_box.setIcon(QMessageBox.Warning)
            
            # 顯示對話框並取得用戶選擇
            msg_box.exec()
            
            if msg_box.clickedButton() == save_btn:
                # 先存檔後關閉
                if self.controller.save_and_close():
                    event.accept()  # 允許關閉
                else:
                    event.ignore()  # 取消關閉（例如用戶取消了存檔對話框）
            elif msg_box.clickedButton() == discard_btn:
                # 放棄變更直接關閉
                event.accept()  # 允許關閉
            else:  # cancel_btn 或關閉對話框
                # 取消關閉
                event.ignore()  # 阻止關閉
        else:
            # 沒有未儲存的變更，直接關閉
            event.accept()