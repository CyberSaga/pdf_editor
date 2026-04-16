from __future__ import annotations

import logging
import math
from pathlib import Path

import fitz
from PySide6.QtCore import QBuffer, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QCloseEvent,
    QColor,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPen,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from model.object_requests import (
    BatchDeleteObjectsRequest,
    BatchMoveObjectsRequest,
    DeleteObjectRequest,
    InsertImageObjectRequest,
    MoveObjectRequest,
    ObjectRef,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from utils.helpers import parse_pages, show_error
from view.text_editing import (
    _DEFAULT_EDITOR_MASK_COLOR,
    _EditorShortcutForwarder,  # noqa: F401 — re-exported for tests and legacy imports
    EditTextRequest,  # noqa: F401 — re-exported for controller
    InlineTextEditor,  # noqa: F401 — re-exported for tests and legacy imports
    MoveTextRequest,  # noqa: F401 — re-exported for controller
    TextEditDragState,
    TextEditFinalizeReason,
    TextEditFinalizeResult,
    TextEditGeometryConstants,
    TextEditManager,
    TextEditOutcome,
    TextEditUIConstants,
    ViewportAnchor,
    _average_image_rect_color,
)

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


# Dialog classes have been extracted to view/dialogs/ for maintainability.
# Re-exported here so all existing `from view.pdf_view import ...` call sites continue to work.
from view.dialogs import (  # noqa: E402, F401
    AuditStackedBar,
    ExportPagesDialog,
    MergePdfDialog,
    OptimizePdfDialog,
    PDFPasswordDialog,
    PdfAuditReportDialog,
    WatermarkDialog,
)

class PDFView(QMainWindow):
    _VALID_MODES = {"browse", "edit_text", "text_edit", "objects", "add_text", "rect", "highlight", "add_annotation"}
    # --- Existing Signals ---
    sig_open_pdf = Signal(str)
    sig_print_requested = Signal()
    sig_save_as = Signal(str)
    sig_save = Signal()  # 存回原檔（Ctrl+S，使用增量更新若適用）
    sig_tab_changed = Signal(int)
    sig_tab_close_requested = Signal(int)
    sig_delete_pages = Signal(list)
    sig_rotate_pages = Signal(list, int)
    sig_export_pages = Signal(list, str, bool, int, str)
    sig_add_highlight = Signal(int, object, object)
    sig_add_rect = Signal(int, object, object, bool)
    sig_edit_text = Signal(object)  # EditTextRequest
    sig_move_text_across_pages = Signal(object)  # MoveTextRequest
    sig_add_textbox = Signal(int, object, str, str, int, tuple)  # page_num, visual_rect, text, font, size, color
    sig_add_image_object = Signal(object)  # InsertImageObjectRequest
    sig_move_object = Signal(object)  # MoveObjectRequest
    sig_delete_object = Signal(object)  # DeleteObjectRequest
    sig_rotate_object = Signal(object)  # RotateObjectRequest
    sig_resize_object = Signal(object)  # ResizeObjectRequest
    sig_jump_to_result = Signal(int, object)
    sig_search = Signal(str)
    sig_ocr = Signal(list)
    sig_undo = Signal()
    sig_redo = Signal()
    sig_mode_changed = Signal(str)
    sig_text_target_mode_changed = Signal(str)
    sig_page_changed = Signal(int)
    sig_scale_changed = Signal(int, float)
    sig_viewport_changed = Signal()
    sig_toggle_fullscreen = Signal()

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
    sig_merge_pdfs_requested = Signal()
    sig_optimize_pdf_copy_requested = Signal()
    sig_backend_bootstrap_requested = Signal()

    # --- 浮水印 Signals ---
    sig_add_watermark = Signal(list, str, float, float, int, tuple, str, float, float, float)  # pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing
    sig_update_watermark = Signal(str, list, str, float, float, int, tuple, str, float, float, float)  # wm_id, pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing
    sig_remove_watermark = Signal(str)
    sig_load_watermarks = Signal()
    shell_ready = Signal()

    def __init__(self, defer_heavy_panels: bool = False):
        super().__init__()
        self.setWindowTitle("視覺化 PDF 編輯器")
        self.setMinimumSize(1280, 800)
        self.setGeometry(100, 100, 1280, 800)
        self.setAcceptDrops(True)
        self.total_pages = 0
        self.controller = None
        self._defer_heavy_panels = defer_heavy_panels
        self._heavy_panels_initialized = False
        self._deferred_hydration_scheduled = False
        self._shell_ready_emitted = False
        self._pending_open_paths: list[str] = []
        self._drag_drop_active = False
        self._doc_tab_signal_block = False
        self._mode_actions: dict[str, QAction] = {}
        self._mode_action_group = QActionGroup(self)
        self._mode_action_group.setExclusive(True)
        self._fullscreen_active = False
        self._fullscreen_restore_geometry = QRect()
        self._fullscreen_restore_maximized = False
        self._fullscreen_restore_screen_name = ""
        self._fullscreen_restore_visibility: dict[str, bool] = {}

        # --- Central container: top toolbar area + main splitter ---
        central_container = QWidget(self)
        self.setCentralWidget(central_container)
        central_container.setObjectName("dropHost")
        central_container.setMouseTracking(True)
        central_container.installEventFilter(self)
        main_layout = QVBoxLayout(central_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setMouseTracking(True)
        self.installEventFilter(self)

        # --- Top Toolbar (ToolbarTabs): 48px height ---
        self._build_toolbar_tabs()
        main_layout.addWidget(self._toolbar_container)
        self._build_document_tabs_bar()
        main_layout.addWidget(self.document_tab_bar)
        self._install_document_tab_shortcuts()

        # --- Main content: QSplitter (Left 260px | Center | Right 280px) ---
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setAcceptDrops(True)

        # Left sidebar: 260px, QTabWidget (縮圖 / 搜尋 / 註解列表 / 浮水印列表)
        self.left_sidebar = QTabWidget()
        self.left_sidebar.setTabBar(_NoCtrlTabTabBar(self.left_sidebar))
        self.left_sidebar.setMinimumWidth(200)
        self.left_sidebar.setMaximumWidth(400)
        if not self._defer_heavy_panels:
            self._setup_left_sidebar()
            self._heavy_panels_initialized = True
        self.left_sidebar_widget = QWidget()
        self.left_sidebar_widget.setAcceptDrops(True)
        left_sidebar_layout = QVBoxLayout(self.left_sidebar_widget)
        left_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        left_sidebar_layout.addWidget(self.left_sidebar)
        self.main_splitter.addWidget(self.left_sidebar_widget)

        # Center: QGraphicsView (canvas)
        self.graphics_view = QGraphicsView(self)
        self.graphics_view.setAcceptDrops(True)
        self.scene = QGraphicsScene(self)
        self.graphics_view.setScene(self.scene)
        self.main_splitter.addWidget(self.graphics_view)

        # Right sidebar: 280px, "屬性" dynamic inspector
        self.right_sidebar = QWidget()
        self.right_sidebar.setAcceptDrops(True)
        right_sidebar_layout = QVBoxLayout(self.right_sidebar)
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_title = QLabel("屬性")
        right_title.setStyleSheet("font-weight: bold; padding: 8px;")
        right_sidebar_layout.addWidget(right_title)
        self.right_stacked_widget = QStackedWidget()
        if self._defer_heavy_panels:
            self._setup_property_inspector_placeholder()
        else:
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
        self._status_bar_override_message: str | None = None
        self._build_fullscreen_exit_button()

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
        self._left_sidebar_last_width = 260
        self._right_sidebar_last_width = 280
        # 記錄目前場景內 pixmap 實際渲染時所使用的 scale。
        # self.scale 代表「期望的總縮放」，可能因 wheel zoom 超前於重渲；
        # _render_scale 追蹤已實際渲染進場景的 scale，供座標轉換使用。
        self._render_scale: float = 1.0
        # debounce timer：wheel 停止後 300ms 再觸發重渲，避免連續滾動時每幀都重渲
        self._zoom_debounce_timer = QTimer(self)
        self._zoom_debounce_timer.setSingleShot(True)
        self._zoom_debounce_timer.timeout.connect(self._on_zoom_debounce)
        self._outline_redraw_timer = QTimer(self)
        self._outline_redraw_timer.setSingleShot(True)
        self._outline_redraw_timer.timeout.connect(self._draw_all_block_outlines)
        self.drawing_start = None
        self.text_editor: QGraphicsProxyWidget = None
        self.editing_intent = "edit_existing"
        self.editing_rect: fitz.Rect = None
        self._editing_original_rect: fitz.Rect = None  # 編輯開始時的原始 rect，拖曳期間不變
        # 拖曳移動文字框的狀態機
        self._drag_pending: bool = False        # 滑鼠已按下在文字塊，尚未判定點擊或拖曳
        self._drag_active: bool = False         # 正在拖曳中
        self._text_edit_drag_state = TextEditDragState.IDLE
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
        self._text_selection_live_text = ""
        self._text_selection_last_scene_pos = None
        self._text_selection_start_span_id = None
        self._text_selection_start_hit_info = None
        self._selected_text_rect_doc = None
        self._selected_text_page_idx = None
        self._selected_text_cached = ""
        self._selected_text_hit_info = None
        self._selected_object_info = None
        self._object_selection_rect_item = None
        self._object_rotate_handle_item = None
        self._object_drag_pending = False
        self._object_drag_active = False
        self._object_rotate_pending = False
        self._object_drag_start_scene_pos = None
        self._object_drag_start_doc_rect = None
        self._object_drag_start_doc_rects = None
        self._object_drag_preview_rect = None
        self._object_drag_preview_rects = None
        self._object_drag_page_idx = None
        # Inline-editor focus lifecycle guards.
        self._edit_focus_guard_connected = False
        self._edit_focus_check_pending = False
        self._finalizing_text_edit = False
        self._last_text_edit_finalize_result: TextEditFinalizeResult | None = None
        self.text_edit_manager = TextEditManager(self)
        # Phase 5: edit_text 模式下的 hover 文字塊高亮
        self._hover_highlight_item = None       # QGraphicsRectItem | None
        self._last_hover_scene_pos = None       # QPointF | None（節流用）
        # Block outlines: persistent dim outlines visible while in edit_text mode
        self._block_outline_items: dict = {}    # (page_idx, block_idx) → QGraphicsRectItem
        self._hover_hidden_outline_key = None   # key of outline hidden during hover
        self._active_outline_key = None         # key of outline hidden during active edit

        self.graphics_view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.graphics_view.setTransformationAnchor(QGraphicsView.AnchorViewCenter)

        # 連續捲動模式：所有頁面由上到下連結，滑動 scrollbar 切換頁面
        self.continuous_pages = True
        self.page_items: list[QGraphicsPixmapItem] = []
        self.page_y_positions: list[float] = []
        self.page_heights: list[float] = []
        self._page_base_sizes: list[tuple[float, float]] = []
        self._placeholder_pixmap = QPixmap(1, 1)
        self._placeholder_pixmap.fill(QColor("#FFFFFF"))
        self._thumbnail_layout_updating = False
        self._save_as_default_path = ""
        self._scroll_block = False
        self._scroll_handler_connected = False
        self.PAGE_GAP = 10

        self.graphics_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view.setFocusPolicy(Qt.StrongFocus)
        self.right_sidebar.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setMouseTracking(True)
        self.graphics_view.viewport().setMouseTracking(True)
        self.graphics_view.viewport().setAcceptDrops(True)
        self.graphics_view.viewport().setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.viewport().installEventFilter(self)
        self._configure_drop_targets(central_container)

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
            QWidget#dropHost[dragActive="true"] { background: #EFF6FF; border: 2px dashed #0EA5E9; }
        """)
        self.graphics_view.setStyleSheet("QGraphicsView { background: #F1F5F9; border: none; }")

    def ensure_heavy_panels_initialized(self) -> None:
        if self._heavy_panels_initialized:
            return

        self._setup_left_sidebar()
        while self.right_stacked_widget.count():
            widget = self.right_stacked_widget.widget(0)
            self.right_stacked_widget.removeWidget(widget)
            widget.deleteLater()
        self._setup_property_inspector()
        self._heavy_panels_initialized = True
        self.set_mode(self.current_mode)
        self._update_status_bar()
        if getattr(self, "text_target_mode_combo", None) is not None:
            self._on_text_target_mode_changed()

    def _emit_shell_ready_once(self) -> None:
        if self._shell_ready_emitted:
            return
        self._shell_ready_emitted = True
        self.shell_ready.emit()

    def _configure_drop_targets(self, central_container: QWidget) -> None:
        self._drop_target_widgets = (
            self,
            central_container,
            self._toolbar_container,
            self.document_tab_bar,
            self.main_splitter,
            self.left_sidebar_widget,
            self.left_sidebar,
            self.graphics_view,
            self.graphics_view.viewport(),
            self.right_sidebar,
            self.right_stacked_widget,
        )
        # Avoid installing the same event filter multiple times on the same widget.
        # Some widgets are already filtered elsewhere (for fullscreen hover, etc.).
        self._drop_filter_installed_ids = {
            id(central_container),
            id(self.graphics_view.viewport()),
        }
        for widget in self._drop_target_widgets:
            widget.setAcceptDrops(True)
            if widget is not self and id(widget) not in self._drop_filter_installed_ids:
                widget.installEventFilter(self)
                self._drop_filter_installed_ids.add(id(widget))

    def _extract_dropped_pdf_paths(self, mime_data, require_existing: bool = False) -> list[str]:
        if mime_data is None or not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            if not local_path:
                continue
            path = Path(local_path)
            if path.suffix.lower() != ".pdf":
                continue
            if require_existing and not path.is_file():
                continue
            paths.append(str(path))
        return paths

    def _set_drag_drop_affordance(self, active: bool) -> None:
        if self._drag_drop_active == active:
            return
        self._drag_drop_active = active
        host = self.centralWidget()
        if host is None:
            return
        host.setProperty("dragActive", active)
        host.style().unpolish(host)
        host.style().polish(host)
        host.update()

    def _queue_or_open_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        if self.controller is None or not getattr(self.controller, "is_active", False):
            self._pending_open_paths.extend(paths)
            self.sig_backend_bootstrap_requested.emit()
            return
        for path in paths:
            self.sig_open_pdf.emit(path)

    def drain_pending_open_paths(self) -> list[str]:
        paths = list(self._pending_open_paths)
        self._pending_open_paths.clear()
        return paths

    def _handle_drag_drop_event(self, event) -> bool:
        event_type = event.type()
        if event_type == QEvent.DragLeave:
            self._set_drag_drop_affordance(False)
            event.accept()
            return True

        require_existing = event_type == QEvent.Drop
        paths = self._extract_dropped_pdf_paths(event.mimeData(), require_existing=require_existing)
        if not paths:
            self._set_drag_drop_affordance(False)
            event.ignore()
            return True

        if event_type == QEvent.Drop:
            self._set_drag_drop_affordance(False)
            self._queue_or_open_paths(paths)
        else:
            self._set_drag_drop_affordance(True)
        event.acceptProposedAction()
        return True

    def dragEnterEvent(self, event):
        if self._handle_drag_drop_event(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._handle_drag_drop_event(event):
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        if self._handle_drag_drop_event(event):
            return
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._handle_drag_drop_event(event):
            return
        super().dropEvent(event)

    def _build_fullscreen_exit_button(self) -> None:
        self._fullscreen_exit_button = QToolButton(self)
        self._fullscreen_exit_button.setText("X")
        self._fullscreen_exit_button.setCursor(Qt.PointingHandCursor)
        self._fullscreen_exit_button.setToolTip("離開全螢幕")
        self._fullscreen_exit_button.setFixedSize(40, 32)
        self._fullscreen_exit_button.setStyleSheet(
            "QToolButton { background: rgba(15, 23, 42, 220); color: white; border: none; border-radius: 16px; font-weight: bold; }"
            "QToolButton:hover { background: rgba(30, 41, 59, 235); }"
        )
        self._fullscreen_exit_button.clicked.connect(self.sig_toggle_fullscreen.emit)
        self._fullscreen_exit_button.hide()
        self._update_fullscreen_exit_button_geometry()

    def _update_fullscreen_exit_button_geometry(self) -> None:
        if not hasattr(self, "_fullscreen_exit_button"):
            return
        margin = 12
        width = self._fullscreen_exit_button.width()
        self._fullscreen_exit_button.move(max(margin, self.width() - width - margin), margin)
        self._fullscreen_exit_button.raise_()

    def _set_fullscreen_exit_button_visible(self, visible: bool) -> None:
        if not hasattr(self, "_fullscreen_exit_button"):
            return
        if not self._fullscreen_active:
            self._fullscreen_exit_button.hide()
            return
        self._fullscreen_exit_button.setVisible(bool(visible))
        if visible:
            self._fullscreen_exit_button.raise_()

    def _update_fullscreen_exit_hover(self, pos: QPoint) -> None:
        if not self._fullscreen_active:
            self._set_fullscreen_exit_button_visible(False)
            return
        # Keep the exit affordance visible throughout fullscreen; hover should
        # only refresh its geometry/stacking, not control discoverability.
        self._set_fullscreen_exit_button_visible(True)

    def is_fullscreen_active(self) -> bool:
        return self._fullscreen_active

    def set_fullscreen_action_enabled(self, enabled: bool) -> None:
        action = getattr(self, "_action_fullscreen", None)
        if action is not None:
            action.setEnabled(enabled)

    def current_screen_name(self) -> str:
        handle = self.windowHandle()
        if handle is not None and handle.screen() is not None:
            return handle.screen().name()
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        return screen.name() if screen is not None else ""

    def enter_fullscreen_ui(self) -> None:
        if self._fullscreen_active:
            return
        # Snapshot current window state so exit can restore user layout precisely.
        self._fullscreen_restore_geometry = QRect(self.geometry())
        self._fullscreen_restore_maximized = self.isMaximized()
        self._fullscreen_restore_screen_name = self.current_screen_name()
        self._fullscreen_restore_visibility = {
            "toolbar": self._toolbar_container.isVisible(),
            "document_tabs": self.document_tab_bar.isVisible(),
            "left_sidebar": self.left_sidebar_widget.isVisible(),
            "right_sidebar": self.right_sidebar.isVisible(),
            "status_bar": self.statusBar().isVisible(),
        }
        self._toolbar_container.hide()
        self.document_tab_bar.hide()
        self.left_sidebar_widget.hide()
        self.right_sidebar.hide()
        self.statusBar().hide()
        self._fullscreen_active = True
        self._set_fullscreen_exit_button_visible(True)
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.ActiveWindowFocusReason)
        self.graphics_view.setFocus(Qt.ActiveWindowFocusReason)
        self.graphics_view.viewport().setFocus(Qt.ActiveWindowFocusReason)
        self._update_fullscreen_exit_button_geometry()

    def exit_fullscreen_ui(self) -> None:
        if not self._fullscreen_active:
            return
        # Restore window geometry and chrome visibility captured on entry.
        self._fullscreen_active = False
        self._set_fullscreen_exit_button_visible(False)
        self.showNormal()
        if self._fullscreen_restore_maximized:
            self.showMaximized()
        else:
            if self._fullscreen_restore_geometry.isValid():
                self.setGeometry(self._fullscreen_restore_geometry)
        if self._fullscreen_restore_visibility.get("toolbar", True):
            self._toolbar_container.show()
        if self._fullscreen_restore_visibility.get("document_tabs", False):
            self.document_tab_bar.show()
        if self._fullscreen_restore_visibility.get("left_sidebar", True):
            self.left_sidebar_widget.show()
        if self._fullscreen_restore_visibility.get("right_sidebar", True):
            self.right_sidebar.show()
        if self._fullscreen_restore_visibility.get("status_bar", True):
            self.statusBar().show()
        self._update_fullscreen_exit_button_geometry()

    def capture_viewport_anchor(self) -> ViewportAnchor:
        # Persist exact scrollbars to restore the same visible region.
        return ViewportAnchor(
            page_idx=max(0, self.current_page),
            horizontal_value=self.graphics_view.horizontalScrollBar().value(),
            vertical_value=self.graphics_view.verticalScrollBar().value(),
        )

    def restore_viewport_anchor(self, anchor: ViewportAnchor | None) -> None:
        if anchor is None:
            return
        self.scroll_to_page(max(0, anchor.page_idx))
        self.graphics_view.horizontalScrollBar().setValue(max(0, int(anchor.horizontal_value)))
        self.graphics_view.verticalScrollBar().setValue(max(0, int(anchor.vertical_value)))

    def compute_contain_scale_for_page(self, page_idx: int) -> float:
        if not self.page_items:
            return max(0.1, float(self.scale))
        idx = min(max(0, page_idx), len(self.page_items) - 1)
        rect = self.page_items[idx].sceneBoundingRect()
        rs = self._render_scale if self._render_scale > 0 else max(0.1, float(self.scale))
        width_pt = max(1.0, rect.width() / rs)
        height_pt = max(1.0, rect.height() / rs)
        viewport = self.graphics_view.viewport().rect()
        viewport_width = max(1, viewport.width() - 12)
        viewport_height = max(1, viewport.height() - 12)
        return max(0.1, min(4.0, min(viewport_width / width_pt, viewport_height / height_pt)))

    def cancel_interaction_for_fullscreen(self) -> None:
        # Cancel any in-progress editor or partial gesture before switching to browse+fullscreen.
        if self.text_editor:
            self._finalize_text_edit(TextEditFinalizeReason.MODE_SWITCH)
        self.drawing_start = None
        self._drag_pending = False
        self._drag_active = False
        self._text_edit_drag_state = TextEditDragState.IDLE
        self._drag_start_scene_pos = None
        self._drag_editor_start_pos = None
        self._pending_text_info = None
        self._clear_hover_highlight()
        self._clear_text_selection()

    def _complete_deferred_shell_startup(self) -> None:
        self._emit_shell_ready_once()

    def showEvent(self, event):
        super().showEvent(event)
        if self._shell_ready_emitted:
            return
        if self._defer_heavy_panels:
            if not self._deferred_hydration_scheduled:
                self._deferred_hydration_scheduled = True
                # The shell is visible first; heavy panels hydrate on the next UI turn.
                QTimer.singleShot(0, self._complete_deferred_shell_startup)
            return
        # Non-deferred views still announce readiness after the first show turn.
        QTimer.singleShot(0, self._emit_shell_ready_once)

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
        self._shortcut_escape.setContext(Qt.ShortcutContext.WindowShortcut)
        self._shortcut_escape.activated.connect(self._on_escape_shortcut)

        self._shortcut_toggle_left_sidebar = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        self._shortcut_toggle_left_sidebar.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_toggle_left_sidebar.activated.connect(self.toggle_left_sidebar)

        self._shortcut_toggle_right_sidebar = QShortcut(QKeySequence("Ctrl+Alt+R"), self)
        self._shortcut_toggle_right_sidebar.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_toggle_right_sidebar.activated.connect(self.toggle_right_sidebar)

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

    def set_document_tabs(self, tabs: list[dict], active_index: int) -> None:
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

    def set_save_as_default_path(self, path: str | None) -> None:
        candidate = str(path or "").strip()
        if candidate and not Path(candidate).suffix:
            candidate = f"{candidate}.pdf"
        self._save_as_default_path = candidate

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
        self._action_optimize_copy = tb_file.addAction("另存為最佳化的副本", self._optimize_pdf_copy)
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
        self._action_objects = self._make_mode_action("操作物件", "objects")
        tb_common.addAction(self._action_objects)
        self._action_undo = tb_common.addAction("復原", self.sig_undo.emit)
        self._action_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self._action_redo = tb_common.addAction("重做", self.sig_redo.emit)
        self._action_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self._redo_mac_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._redo_mac_shortcut.activated.connect(self.sig_redo.emit)
        self._action_fullscreen = tb_common.addAction("全螢幕", self.sig_toggle_fullscreen.emit)
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
        tb_edit.addAction(self._action_objects)
        self._action_objects.setShortcut(QKeySequence(Qt.Key_F3))
        self._action_add_text = self._make_mode_action("新增文字框", "add_text")
        tb_edit.addAction(self._action_add_text)
        self._action_rect = self._make_mode_action("矩形", "rect")
        tb_edit.addAction(self._action_rect)
        self._action_highlight = self._make_mode_action("螢光筆", "highlight")
        tb_edit.addAction(self._action_highlight)
        self._action_add_annotation = self._make_mode_action("新增註解", "add_annotation")
        tb_edit.addAction(self._action_add_annotation)
        tb_edit.addAction("插入圖片", self._insert_image_object_from_file_at_current_page)
        tb_edit.addAction("貼上圖片", self._insert_image_object_from_clipboard_at_current_page)
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
        tb_page.addAction("合併PDF", self.sig_merge_pdfs_requested.emit)
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
        right_widget.setMaximumWidth(520)
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
        self.fit_view_btn = QPushButton("適應畫面")
        self.fit_view_btn.clicked.connect(self._fit_to_view)
        self.fullscreen_quick_btn = QPushButton("全螢幕")
        self.fullscreen_quick_btn.clicked.connect(self.sig_toggle_fullscreen.emit)
        self._action_undo_right = QAction("↺ 復原", self)
        self._action_undo_right.triggered.connect(self.sig_undo.emit)
        self._action_redo_right = QAction("↻ 重做", self)
        self._action_redo_right.triggered.connect(self.sig_redo.emit)
        right_layout.addWidget(self.page_counter_label)
        right_layout.addWidget(QLabel(" "))
        right_layout.addWidget(self.zoom_combo)
        right_layout.addWidget(self.fit_view_btn)
        # right_layout already contributes 6px between adjacent items.
        # Use another 6px spacer so the visible gap between these two buttons is 12px total.
        right_layout.addSpacing(6)
        right_layout.addWidget(self.fullscreen_quick_btn)
        # 根因 2 排除：移除 stretch，避免佔滿剩餘空間、把 QToolBar 擠成只顯示溢出
        # right_layout.addWidget(QWidget(), 1) 已移除
        self.toolbar_right = QToolBar()
        self.toolbar_right.addAction(self._action_undo_right)
        self.toolbar_right.addAction(self._action_redo_right)
        # 根因 3 排除：確保「復原」「重做」兩顆按鈕都有空間，不進溢出選單
        self.toolbar_right.setMinimumWidth(100)
        right_layout.addWidget(self.toolbar_right)
        bar_layout.addWidget(right_widget)
        bar_layout.addSpacing(12)

        self._action_undo.setToolTip("復原（無可撤銷操作）")
        self._action_redo.setToolTip("重做（無可重做操作）")
        self._global_undo_enabled = False
        self._global_redo_enabled = False
        self._set_undo_redo_action_state(False, False)

        # Ensure shortcuts remain active even when the source toolbar tab is hidden.
        for action in (
            self._action_open,
            self._action_print,
            self._action_save,
            self._action_save_as,
            self._action_undo,
            self._action_redo,
            self._action_edit_text,
            self._action_objects,
            self._action_fullscreen,
        ):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)
        self._action_undo.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._action_redo.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._action_fullscreen.setShortcut(QKeySequence(Qt.Key_F5))

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
        target_page = self.current_page
        if self.continuous_pages and self.page_items:
            target_page = min(max(self.current_page, 0), len(self.page_items) - 1)
            target_rect = self.page_items[target_page].sceneBoundingRect()
        elif self.page_items:
            target_rect = self.page_items[0].sceneBoundingRect()
            target_page = 0
        elif self.scene.sceneRect().isValid():
            target_rect = self.scene.sceneRect()

        if not target_rect or not target_rect.isValid():
            return

        self.sig_scale_changed.emit(target_page, self.compute_contain_scale_for_page(target_page))

    def _resolve_sidebar_width(self, remembered: int, default_width: int) -> int:
        return default_width if remembered < 50 else remembered

    def _apply_sidebar_sizes(self, *, left_width: int | None = None, right_width: int | None = None) -> None:
        sizes = self.main_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            total = max(self.main_splitter.width(), 1280)
        left = left_width if left_width is not None else (sizes[0] if self.left_sidebar_widget.isVisible() else 0)
        right = right_width if right_width is not None else (sizes[2] if self.right_sidebar.isVisible() else 0)
        center = max(1, total - int(left) - int(right))
        self.main_splitter.setSizes([max(0, int(left)), center, max(0, int(right))])

    def _focus_left_sidebar_target(self) -> None:
        if self.left_sidebar.currentIndex() == 1 and getattr(self, "search_input", None) is not None:
            self.search_input.setFocus(Qt.ShortcutFocusReason)
            self.search_input.selectAll()
            return
        self.left_sidebar.tabBar().setFocus(Qt.ShortcutFocusReason)

    def _focus_right_sidebar_target(self) -> None:
        current = self.right_stacked_widget.currentWidget()
        if current is not None:
            for child in current.findChildren(QWidget):
                if child.focusPolicy() == Qt.NoFocus:
                    continue
                if not child.isEnabled() or not child.isVisibleTo(current):
                    continue
                child.setFocus(Qt.ShortcutFocusReason)
                if child.hasFocus():
                    return
        self.right_sidebar.setFocus(Qt.ShortcutFocusReason)

    def _ensure_left_sidebar_visible(self, *, focus_target: bool = False) -> None:
        if not self.left_sidebar_widget.isVisible():
            self.left_sidebar_widget.show()
            self._apply_sidebar_sizes(
                left_width=self._resolve_sidebar_width(self._left_sidebar_last_width, 260)
            )
        if focus_target:
            self._focus_left_sidebar_target()

    def toggle_left_sidebar(self) -> None:
        if self.left_sidebar_widget.isVisible():
            left_width = self.main_splitter.sizes()[0]
            if left_width >= 50:
                self._left_sidebar_last_width = left_width
            self.left_sidebar_widget.hide()
            self._apply_sidebar_sizes(left_width=0)
            self._focus_page_canvas()
            return
        self.left_sidebar_widget.show()
        self._apply_sidebar_sizes(
            left_width=self._resolve_sidebar_width(self._left_sidebar_last_width, 260)
        )
        self._focus_left_sidebar_target()

    def toggle_right_sidebar(self) -> None:
        if self.right_sidebar.isVisible():
            right_width = self.main_splitter.sizes()[2]
            if right_width >= 50:
                self._right_sidebar_last_width = right_width
            self.right_sidebar.hide()
            self._apply_sidebar_sizes(right_width=0)
            self._focus_page_canvas()
            return
        self.right_sidebar.show()
        self._apply_sidebar_sizes(
            right_width=self._resolve_sidebar_width(self._right_sidebar_last_width, 280)
        )
        self._focus_right_sidebar_target()

    def _show_thumbnails_tab(self):
        self.ensure_heavy_panels_initialized()
        self._ensure_left_sidebar_visible()
        self.left_sidebar.setCurrentIndex(0)

    def _show_search_tab(self):
        self.ensure_heavy_panels_initialized()
        self._ensure_left_sidebar_visible()
        self.left_sidebar.setCurrentIndex(1)
        self.search_input.setFocus(Qt.ShortcutFocusReason)
        self.search_input.selectAll()

    def _show_annotations_tab(self):
        self.ensure_heavy_panels_initialized()
        self._ensure_left_sidebar_visible()
        self.left_sidebar.setCurrentIndex(2)

    def _show_watermarks_tab(self):
        self.ensure_heavy_panels_initialized()
        self._ensure_left_sidebar_visible()
        self.left_sidebar.setCurrentIndex(3)

    def _setup_left_sidebar(self):
        """Left sidebar: QTabWidget with 縮圖 / 搜尋 / 註解列表 / 浮水印列表. 260px."""
        # 縮圖 (default)
        self.thumbnail_list = QListWidget(self)
        self.thumbnail_list.setViewMode(QListWidget.IconMode)
        self.thumbnail_list.setFlow(QListView.TopToBottom)
        self.thumbnail_list.setWrapping(False)
        self.thumbnail_list.setMovement(QListView.Static)
        self.thumbnail_list.setResizeMode(QListView.Adjust)
        self.thumbnail_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbnail_list.viewport().installEventFilter(self)
        self.thumbnail_list.itemClicked.connect(self._on_thumbnail_clicked)
        self.thumbnail_list.customContextMenuRequested.connect(self._show_thumbnail_context_menu)
        self.left_sidebar.addTab(self.thumbnail_list, "縮圖")
        QTimer.singleShot(0, self._update_thumbnail_layout_metrics)

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

    def _setup_property_inspector_placeholder(self):
        self.page_info_card = QWidget()
        page_layout = QVBoxLayout(self.page_info_card)
        self.page_info_label = QLabel("載入屬性面板中...")
        self.page_info_label.setWordWrap(True)
        page_layout.addWidget(self.page_info_label)
        page_layout.addStretch()
        self.right_stacked_widget.addWidget(self.page_info_card)

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
        self.rect_color_btn.setStyleSheet("background-color: #0078D4; color: white;")
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
        self.text_apply_btn.setEnabled(False)
        self.text_cancel_btn.setEnabled(False)
        self.text_apply_btn.clicked.connect(self._on_text_apply_clicked)
        self.text_cancel_btn.clicked.connect(self._on_text_cancel_clicked)
        text_layout.addWidget(self.text_apply_btn)
        text_layout.addWidget(self.text_cancel_btn)
        text_layout.addStretch()
        self.right_stacked_widget.addWidget(self.text_card)
        self._sync_text_property_panel_state()

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
            self._finalize_text_edit(TextEditFinalizeReason.APPLY)

    def _on_text_cancel_clicked(self):
        if not self.text_editor or not self.text_editor.widget():
            return
        self._finalize_text_edit(TextEditFinalizeReason.CANCEL_BUTTON)

    def _set_text_property_actions_enabled(self, enabled: bool) -> None:
        for attr in ("text_apply_btn", "text_cancel_btn"):
            button = getattr(self, attr, None)
            if button is not None and hasattr(button, "setEnabled"):
                button.setEnabled(bool(enabled))

    def _set_text_property_font_and_size(
        self,
        font_name: str | None,
        font_size: float | int | None,
    ) -> None:
        if getattr(self, "text_font", None) is None or getattr(self, "text_size", None) is None:
            return

        if font_name:
            self._set_text_font_by_pdf(str(font_name))

        if font_size is None:
            return

        try:
            size_value = int(round(float(font_size)))
        except (TypeError, ValueError):
            return

        size_str = str(size_value)
        if self.text_size.findText(size_str) == -1:
            self.text_size.addItem(size_str)
        self.text_size.setCurrentText(size_str)

    def _selected_text_has_context(self) -> bool:
        return bool(
            getattr(self, "current_mode", "browse") == "browse"
            and (
                getattr(self, "_selected_text_cached", "")
                or getattr(self, "_selected_text_rect_doc", None) is not None
            )
        )

    def _sync_text_property_panel_state(self) -> None:
        text_card = getattr(self, "text_card", None)
        stacked = getattr(self, "right_stacked_widget", None)
        if text_card is None or stacked is None:
            return

        text_editor = getattr(self, "text_editor", None)
        editor_widget = text_editor.widget() if (text_editor and text_editor.widget()) else None
        has_live_editor = editor_widget is not None
        self._set_text_property_actions_enabled(has_live_editor)

        if has_live_editor:
            font = editor_widget.font() if hasattr(editor_widget, "font") else None
            if font is not None:
                self._set_text_property_font_and_size(font.family(), font.pointSize())
            stacked.setCurrentWidget(text_card)
            return

        current_mode = getattr(self, "current_mode", "browse")

        if current_mode in ("add_text", "edit_text"):
            stacked.setCurrentWidget(text_card)
            return

        if self._selected_text_has_context():
            info = getattr(self, "_selected_text_hit_info", None)
            if info is not None:
                self._set_text_property_font_and_size(
                    getattr(info, "font", None),
                    getattr(info, "size", None),
                )
                target_mode = getattr(info, "target_mode", None)
                combo = getattr(self, "text_target_mode_combo", None)
                if combo is not None and target_mode in ("run", "paragraph"):
                    idx = combo.findData(target_mode)
                    if idx >= 0:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(idx)
                        combo.blockSignals(False)
            stacked.setCurrentWidget(text_card)
            return

        page_info_card = getattr(self, "page_info_card", None)
        if page_info_card is not None:
            stacked.setCurrentWidget(page_info_card)

    def _update_status_bar(self):
        """更新狀態列：已修改、模式、快捷鍵、頁/縮放；搜尋模式時顯示找到 X 個結果 • 按 Esc 關閉搜尋."""
        if getattr(self, "_status_bar_override_message", None):
            self.status_bar.showMessage(self._status_bar_override_message)
            return
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

    def set_status_bar_override_message(self, message: str | None) -> None:
        self._status_bar_override_message = message or None
        self._update_status_bar()

    def _show_toast(self, message: str, duration_ms: int = 1500, tone: str = "success") -> None:
        """Show a brief overlay toast message at the bottom-center of the viewport."""
        toast = QLabel(message, self.graphics_view.viewport())
        toast.setAlignment(Qt.AlignCenter)
        if tone == "error":
            background = "rgba(180,40,40,220)"
        else:
            background = "rgba(40,40,40,200)"
        toast.setStyleSheet(
            f"background-color: {background}; color: white; "
            "border-radius: 6px; padding: 6px 14px; font-size: 13px;"
        )
        toast.adjustSize()
        vp = self.graphics_view.viewport()
        x = (vp.width() - toast.width()) // 2
        y = vp.height() - toast.height() - 24
        toast.move(x, y)
        toast.show()
        QTimer.singleShot(duration_ms, toast.deleteLater)

    def set_mode(self, mode: str):
        mode = mode if mode in self._VALID_MODES else "browse"
        if mode == "text_edit":
            mode = "edit_text"
        if mode != "browse" and not self._heavy_panels_initialized:
            self.ensure_heavy_panels_initialized()
        if self.text_editor:
            result = self._finalize_text_edit(TextEditFinalizeReason.MODE_SWITCH)
            if result is not None and result.outcome == TextEditOutcome.COMMITTED:
                self._show_toast("文字已儲存")
        if self.current_mode == 'browse' and mode != 'browse':
            self._reset_browse_hover_cursor()
            self._clear_text_selection()
            self._clear_object_selection()
        # 切換模式時清除所有拖曳/待定狀態
        self._drag_pending = False
        self._drag_active = False
        self._text_edit_drag_state = TextEditDragState.IDLE
        self._drag_start_scene_pos = None
        self._drag_editor_start_pos = None
        self._pending_text_info = None
        _prev_mode = self.current_mode
        if mode != 'edit_text':
            self._clear_hover_highlight()
            self._clear_all_block_outlines()
            self._outline_redraw_timer.stop()
            if _prev_mode == 'edit_text':
                try:
                    self.sig_viewport_changed.disconnect(self._schedule_outline_redraw)
                except Exception:
                    pass
                try:
                    self.sig_scale_changed.disconnect(self._schedule_outline_redraw)
                except Exception:
                    pass
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
            self._draw_all_block_outlines()
            if _prev_mode != 'edit_text':   # only connect on mode transition, not re-entry
                try:
                    self.sig_viewport_changed.connect(self._schedule_outline_redraw)
                except Exception:
                    pass
                try:
                    self.sig_scale_changed.connect(self._schedule_outline_redraw)
                except Exception:
                    pass
        elif mode == 'objects':
            self.graphics_view.setDragMode(QGraphicsView.NoDrag)
            self.graphics_view.viewport().setCursor(Qt.ArrowCursor)
            self.right_stacked_widget.setCurrentWidget(self.page_info_card)
        else:
            self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
            self._reset_browse_hover_cursor()
            self.right_stacked_widget.setCurrentWidget(self.page_info_card)
        self._sync_text_property_panel_state()
        self._update_status_bar()

    def _on_escape_shortcut(self) -> None:
        self._handle_escape()

    def _set_document_undo_redo_enabled(self, enabled: bool) -> None:
        self._set_undo_redo_action_state(bool(enabled), bool(enabled))

    def _set_undo_redo_action_state(self, undo_enabled: bool, redo_enabled: bool) -> None:
        action_pairs = (
            (getattr(self, "_action_undo", None), undo_enabled),
            (getattr(self, "_action_undo_right", None), undo_enabled),
            (getattr(self, "_action_redo", None), redo_enabled),
            (getattr(self, "_action_redo_right", None), redo_enabled),
        )
        for action, enabled in action_pairs:
            if action is not None and hasattr(action, "setEnabled"):
                action.setEnabled(bool(enabled))

    def _refresh_undo_redo_action_state(self) -> None:
        undo_enabled = bool(getattr(self, "_global_undo_enabled", False))
        redo_enabled = bool(getattr(self, "_global_redo_enabled", False))
        editor_proxy = getattr(self, "text_editor", None)
        editor_widget = editor_proxy.widget() if (editor_proxy and editor_proxy.widget()) else None
        if editor_widget is not None and hasattr(editor_widget, "document"):
            document = editor_widget.document()
            if document is not None:
                undo_enabled = bool(document.isUndoAvailable())
                redo_enabled = bool(document.isRedoAvailable())
        self._set_undo_redo_action_state(undo_enabled, redo_enabled)

    def update_undo_redo_enabled(self, undo_enabled: bool, redo_enabled: bool) -> None:
        self._global_undo_enabled = bool(undo_enabled)
        self._global_redo_enabled = bool(redo_enabled)
        self._refresh_undo_redo_action_state()

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
        self._finalize_text_edit(TextEditFinalizeReason.FOCUS_OUTSIDE)

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
        if self._fullscreen_active:
            self.sig_toggle_fullscreen.emit()
            return True
        if self.text_editor:
            self._finalize_text_edit(TextEditFinalizeReason.ESCAPE)
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
        if self.current_mode in ('browse', 'objects', 'edit_text', 'text_edit') and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._delete_selected_object():
                event.accept()
                return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_F:
            self._show_search_tab()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        drop_targets = getattr(self, "_drop_target_widgets", ())
        if obj in drop_targets and obj is not self and event.type() in (
            QEvent.DragEnter,
            QEvent.DragMove,
            QEvent.DragLeave,
            QEvent.Drop,
        ):
            return self._handle_drag_drop_event(event)
        graphics_view = getattr(self, "graphics_view", None)
        if graphics_view is not None and obj is graphics_view.viewport():
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                if self._handle_escape():
                    event.accept()
                    return True
            if event.type() == QEvent.Leave:
                if self.current_mode == 'browse':
                    self._reset_browse_hover_cursor()
            elif event.type() == QEvent.MouseMove and self._fullscreen_active:
                pos = graphics_view.viewport().mapTo(self, event.position().toPoint())
                self._update_fullscreen_exit_hover(pos)
        if obj is self or obj is self.centralWidget():
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                if self._handle_escape():
                    event.accept()
                    return True
            if event.type() == QEvent.MouseMove and self._fullscreen_active:
                self._update_fullscreen_exit_hover(event.position().toPoint())
        thumb_list = getattr(self, "thumbnail_list", None)
        if thumb_list is not None and obj is thumb_list.viewport() and event.type() == QEvent.Resize:
            self._update_thumbnail_layout_metrics()
        return super().eventFilter(obj, event)

    def _update_thumbnail_layout_metrics(self) -> None:
        if self._thumbnail_layout_updating:
            return
        if not getattr(self, "thumbnail_list", None):
            return
        viewport = self.thumbnail_list.viewport()
        if viewport is None:
            return
        total_w = max(1, self.thumbnail_list.width())
        if total_w <= 1:
            return
        # Root cause note:
        # The visible "gap" between thumbnails was mostly oversized per-item cell height
        # (icon box too tall), not QListWidget spacing itself.
        spacing = 1
        max_item_w = 280
        available_w = max(120, total_w - 12)
        item_w = min(available_w, max_item_w)
        horizontal_margin = max(0, (available_w - item_w) // 2)
        icon_w = max(96, item_w - 18)
        # Match icon box height to actual thumbnail aspect ratio to avoid large blank
        # space inside each cell (especially for landscape pages).
        aspect = self._thumbnail_icon_aspect_ratio()
        icon_h = max(88, int(icon_w * aspect))
        # Reserve only minimal label/padding area below the thumbnail.
        item_h = icon_h + 28
        self._thumbnail_layout_updating = True
        try:
            self.thumbnail_list.setViewportMargins(horizontal_margin, 0, horizontal_margin, 0)
            self.thumbnail_list.setSpacing(spacing)
            self.thumbnail_list.setIconSize(QSize(icon_w, icon_h))
            self.thumbnail_list.setGridSize(QSize(item_w, item_h))
            # Hidden QListWidget instances may keep a stale scrollbar range
            # until a layout pass is forced. Refresh explicitly so tests and
            # offscreen open flows still get correct thumbnail scrolling
            # behavior.
            self.thumbnail_list.doItemsLayout()
            self.thumbnail_list.updateGeometries()
        finally:
            self._thumbnail_layout_updating = False

    def _thumbnail_icon_aspect_ratio(self) -> float:
        """Return representative thumbnail icon height/width ratio."""
        default_ratio = 0.75
        count = self.thumbnail_list.count() if getattr(self, "thumbnail_list", None) else 0
        for i in range(min(count, 8)):
            item = self.thumbnail_list.item(i)
            if item is None:
                continue
            icon = item.icon()
            if icon.isNull():
                continue
            sizes = icon.availableSizes()
            if sizes:
                size = max(sizes, key=lambda s: s.width() * s.height())
                if size.width() > 0 and size.height() > 0:
                    ratio = size.height() / float(size.width())
                    # Clamp to a sane range so one unusual icon does not break layout.
                    return min(1.6, max(0.5, ratio))
            probe = icon.pixmap(QSize(512, 512))
            if not probe.isNull() and probe.width() > 0 and probe.height() > 0:
                ratio = probe.height() / float(probe.width())
                return min(1.6, max(0.5, ratio))
        return default_ratio

    def update_thumbnails(self, thumbnails: list[QPixmap]):
        """一次設定全部縮圖（相容舊流程）。"""
        self.thumbnail_list.clear()
        for i, pix in enumerate(thumbnails):
            self.thumbnail_list.addItem(QListWidgetItem(QIcon(pix), f"頁{i+1}"))
        self._update_thumbnail_layout_metrics()
        self.total_pages = len(thumbnails)
        self._update_page_counter()
        self._update_status_bar()

    def set_thumbnail_placeholders(self, total: int):
        """僅建立縮圖列表佔位（頁碼），供後續分批更新圖示。"""
        self.thumbnail_list.clear()
        for i in range(total):
            self.thumbnail_list.addItem(QListWidgetItem(f"頁{i+1}"))
        self._update_thumbnail_layout_metrics()
        self.total_pages = total
        self._update_page_counter()
        self._update_status_bar()

    def update_thumbnail_batch(self, start_index: int, pixmaps: list[QPixmap]):
        """從 start_index 起更新一批縮圖的圖示。"""
        for i, pix in enumerate(pixmaps):
            row = start_index + i
            if row >= self.thumbnail_list.count():
                break
            item = self.thumbnail_list.item(row)
            if item and not pix.isNull():
                item.setIcon(QIcon(pix))
        self._update_thumbnail_layout_metrics()

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
        self._page_base_sizes.clear()
        thumbnail_list = getattr(self, "thumbnail_list", None)
        if thumbnail_list is not None:
            thumbnail_list.clear()
        self.total_pages = 0
        self.current_page = 0
        self._render_scale = self.scale if self.scale > 0 else 1.0
        self.clear_search_ui_state()
        self._update_page_counter()
        self._update_status_bar()

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
        self._update_page_counter()
        self._update_status_bar()
        self.sig_viewport_changed.emit()

    def _scene_y_to_page_index(self, scene_y: float) -> int:
        """將場景 Y 座標轉為頁碼索引。"""
        if not self.page_y_positions or not self.page_heights:
            return 0
        for i in range(len(self.page_y_positions)):
            end = self.page_y_positions[i] + self.page_heights[i]
            if scene_y < end:
                return i
        return len(self.page_y_positions) - 1

    def _build_text_editor_stylesheet(self, text_rgb: tuple[int, int, int], mask_color: QColor) -> str:
        r, g, b = text_rgb
        return (
            f"QTextEdit {{ background: transparent; "
            f"border: 1.5px dashed rgba(30,120,255,0.75); color: rgb({r},{g},{b}); "
            f"selection-background-color: rgba(30,120,255,0.25); }}"
            f"QTextEdit QScrollBar {{ background: transparent; }}"
        )

    def _iter_outline_targets(self, page_idx: int) -> list[tuple[tuple[int, int], fitz.Rect]]:
        if not hasattr(self, "controller") or not getattr(self.controller.model, "doc", None):
            return []
        model = self.controller.model
        manager = model.block_manager
        mode = (getattr(model, "text_target_mode", "run") or "run").lower()

        targets: list[tuple[tuple[int, int], fitz.Rect]] = []
        if mode == "paragraph":
            for target_idx, para in enumerate(manager.get_paragraphs(page_idx)):
                rect = fitz.Rect(getattr(para, "bbox", fitz.Rect()))
                if not rect.is_empty:
                    targets.append(((page_idx, target_idx), rect))
        else:
            for target_idx, run in enumerate(manager.get_runs(page_idx)):
                rect = fitz.Rect(getattr(run, "bbox", fitz.Rect()))
                if not rect.is_empty:
                    targets.append(((page_idx, target_idx), rect))

        if targets:
            return targets

        for target_idx, block in enumerate(manager.get_blocks(page_idx)):
            rect = fitz.Rect(getattr(block, "rect", fitz.Rect()))
            if not rect.is_empty:
                targets.append(((page_idx, target_idx), rect))
        return targets

    def _ensure_text_edit_manager(self) -> TextEditManager:
        manager = getattr(self, "text_edit_manager", None)
        if manager is None:
            manager = TextEditManager(self)
            self.text_edit_manager = manager
        return manager

    def _current_text_editor_scene_rect(self) -> QRectF | None:
        return self._ensure_text_edit_manager().current_text_editor_scene_rect()

    def _sample_page_mask_color(self, page_idx: int, scene_rect: QRectF) -> QColor:
        if (
            page_idx < 0
            or page_idx >= len(getattr(self, "page_items", []))
            or scene_rect.isEmpty()
        ):
            return QColor(_DEFAULT_EDITOR_MASK_COLOR)
        page_item = self.page_items[page_idx]
        if page_item is None or not hasattr(page_item, "pixmap"):
            return QColor(_DEFAULT_EDITOR_MASK_COLOR)
        pixmap = page_item.pixmap()
        if pixmap is None or pixmap.isNull():
            return QColor(_DEFAULT_EDITOR_MASK_COLOR)
        image = pixmap.toImage()
        item_rect = page_item.sceneBoundingRect()
        if item_rect.isEmpty():
            return QColor(_DEFAULT_EDITOR_MASK_COLOR)

        local_rect = scene_rect.intersected(item_rect)
        if local_rect.isEmpty():
            return QColor(_DEFAULT_EDITOR_MASK_COLOR)

        scale_x = image.width() / max(1.0, item_rect.width())
        scale_y = image.height() / max(1.0, item_rect.height())
        inset_x = min(local_rect.width() * TextEditUIConstants.MASK_SAMPLE_INSET_RATIO, TextEditUIConstants.MASK_SAMPLE_INSET_MAX_PX)
        inset_y = min(local_rect.height() * TextEditUIConstants.MASK_SAMPLE_INSET_RATIO, TextEditUIConstants.MASK_SAMPLE_INSET_MAX_PX)
        sample_rect = local_rect.adjusted(inset_x, inset_y, -inset_x, -inset_y)
        if sample_rect.isEmpty():
            sample_rect = local_rect

        image_rect = QRect(
            max(0, int((sample_rect.left() - item_rect.left()) * scale_x)),
            max(0, int((sample_rect.top() - item_rect.top()) * scale_y)),
            max(1, int(sample_rect.width() * scale_x)),
            max(1, int(sample_rect.height() * scale_y)),
        )
        return _average_image_rect_color(image, image_rect)

    def _refresh_text_editor_mask_color(self) -> None:
        self._ensure_text_edit_manager().refresh_text_editor_mask_color()

    def _should_start_editor_drag(self, dx: float, dy: float) -> bool:
        threshold = TextEditGeometryConstants.DRAG_START_DISTANCE_PX
        return (dx * dx + dy * dy) > (threshold * threshold)

    def _resolve_editor_page_idx_for_drag(self, editor_top_y: float) -> int:
        if not self.continuous_pages or not self.page_y_positions:
            return getattr(self, "_editing_page_idx", self.current_page)
        editor_widget = self.text_editor.widget() if (self.text_editor and self.text_editor.widget()) else None
        editor_height = float(editor_widget.height()) if editor_widget else 0.0
        return self._scene_y_to_page_index(editor_top_y + (editor_height / 2.0))

    def _scene_pos_to_page_and_doc_point(self, scene_pos: QPointF) -> tuple[int, fitz.Point]:
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
        item = self.thumbnail_list.item(row)
        if item is not None:
            self.thumbnail_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self.thumbnail_list.blockSignals(False)

    def scroll_to_page(self, page_idx: int, *, emit_viewport_changed: bool = True):
        """捲動至指定頁面，使該頁置中顯示。"""
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
        if emit_viewport_changed:
            self.sig_viewport_changed.emit()

    def update_page_in_scene(self, page_idx: int, pix: QPixmap):
        """更新連續場景中某一頁的 pixmap。"""
        if page_idx < 0 or page_idx >= len(self.page_items) or pix.isNull():
            return
        self.page_items[page_idx].setPixmap(pix)
        self.page_items[page_idx].setTransform(QTransform())

    def update_page_in_scene_scaled(self, page_idx: int, pix: QPixmap, rendered_scale: float, target_scale: float):
        """更新連續場景中某一頁的 pixmap，必要時以 item transform 放大低解析度預覽。"""
        if page_idx < 0 or page_idx >= len(self.page_items) or pix.isNull():
            return
        self.page_items[page_idx].setPixmap(pix)
        scale_factor = max(0.1, float(target_scale)) / max(0.1, float(rendered_scale))
        self.page_items[page_idx].setTransform(QTransform.fromScale(scale_factor, scale_factor))

    def initialize_continuous_placeholders(
        self,
        page_sizes: list[tuple[float, float]],
        scale: float,
        initial_page_idx: int = 0,
    ) -> None:
        """Create full-document scene geometry immediately using lightweight placeholders."""
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
        self._page_base_sizes = list(page_sizes)
        if not page_sizes:
            return

        y = 0.0
        max_w = 0.0
        target_scale = max(0.1, float(scale))
        for width_pt, height_pt in page_sizes:
            width_scene = max(1.0, float(width_pt) * target_scale)
            height_scene = max(1.0, float(height_pt) * target_scale)
            self.page_y_positions.append(y)
            self.page_heights.append(height_scene)
            item = self.scene.addPixmap(self._placeholder_pixmap)
            item.setPos(0, y)
            item.setTransform(QTransform.fromScale(width_scene, height_scene))
            self.page_items.append(item)
            max_w = max(max_w, width_scene)
            y += height_scene + self.PAGE_GAP

        self.scene.setSceneRect(0, 0, max(1, max_w), max(1, y))
        self.graphics_view.setSceneRect(self.scene.sceneRect())
        self.current_page = min(max(0, initial_page_idx), len(page_sizes) - 1)
        self._render_scale = target_scale
        self.graphics_view.setTransform(QTransform())
        self._connect_scroll_handler()
        self.scroll_to_page(self.current_page, emit_viewport_changed=False)
        self._sync_thumbnail_selection()

    def visible_page_range(self, prefetch: int = 0) -> tuple[int, int]:
        if not self.page_y_positions:
            return (0, -1)
        viewport_rect = self.graphics_view.viewport().rect()
        top_scene = self.graphics_view.mapToScene(viewport_rect.topLeft()).y()
        bottom_scene = self.graphics_view.mapToScene(viewport_rect.bottomLeft()).y()
        start = self._scene_y_to_page_index(top_scene) - max(0, int(prefetch))
        end = self._scene_y_to_page_index(bottom_scene) + max(0, int(prefetch))
        start = max(0, start)
        end = min(len(self.page_y_positions) - 1, end)
        return (start, end)

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

    def _show_thumbnail_context_menu(self, pos) -> None:
        thumbnail_list = getattr(self, "thumbnail_list", None)
        if thumbnail_list is None:
            return
        item = thumbnail_list.itemAt(pos)
        if item is None:
            return
        row = thumbnail_list.row(item)
        if row < 0:
            return
        page_num = row + 1
        thumbnail_list.setCurrentRow(row)

        menu = QMenu()
        menu.addAction("刪除此頁", lambda checked=False, p=page_num: self._delete_specific_pages([p]))
        menu.addSeparator()
        menu.addAction("向右旋轉 90°", lambda checked=False, p=page_num: self._rotate_specific_pages([p], 90))
        menu.addAction("向左旋轉 90°", lambda checked=False, p=page_num: self._rotate_specific_pages([p], 270))
        menu.addSeparator()
        menu.addAction("匯出此頁...", lambda checked=False, p=page_num: self._export_specific_pages([p]))
        menu.addSeparator()
        menu.addAction("在此頁之前插入空白頁", lambda checked=False, p=page_num: self._insert_blank_page_at(p))
        menu.addAction("在此頁之後插入空白頁", lambda checked=False, p=page_num: self._insert_blank_page_at(p + 1))
        menu.addAction(
            "在此頁之前插入其他 PDF 頁面...",
            lambda checked=False, p=page_num: self._insert_pages_from_file_at(p),
        )
        menu.addAction(
            "在此頁之後插入其他 PDF 頁面...",
            lambda checked=False, p=page_num: self._insert_pages_from_file_at(p + 1),
        )
        menu.exec_(thumbnail_list.viewport().mapToGlobal(pos))

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

    def _event_scene_pos(self, event) -> QPointF:
        raw_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        viewport = self.graphics_view.viewport() if getattr(self, "graphics_view", None) is not None else None
        if viewport is not None:
            try:
                raw_pos = viewport.mapFrom(self.graphics_view, raw_pos)
            except Exception:
                pass
        return self.graphics_view.mapToScene(raw_pos)

    def _mouse_press(self, event):
        scene_pos = self._event_scene_pos(event)
        if event.button() == Qt.LeftButton:
            if self.current_mode == 'add_annotation':
                text, ok = QInputDialog.getMultiLineText(self, "新增註解", "請輸入註解內容:")
                if ok and text:
                    page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
                    self.sig_add_annotation.emit(page_idx, doc_point, text)
                return

            # Objects/text editing modes own object manipulation. Browse owns text selection.
            # Keep this early-return path lightweight so tests can exercise mode gating without
            # constructing the full edit-text state machine.
            if self.current_mode in ("objects", "text_edit", "edit_text"):
                if (
                    self._selected_object_info is not None
                    and self._point_hits_object_resize_handle(scene_pos)
                    and getattr(self._selected_object_info, "supports_move", False)
                ):
                    self._clear_text_selection()
                    self._object_resize_pending = True
                    self._object_resize_active = False
                    self._object_resize_start_scene_pos = scene_pos
                    self._object_resize_start_doc_rect = fitz.Rect(self._selected_object_info.bbox)
                    self._object_resize_preview_rect = fitz.Rect(self._selected_object_info.bbox)
                    event.accept()
                    return
                if (
                    self._selected_object_info is not None
                    and self._point_hits_object_rotate_handle(scene_pos)
                    and getattr(self._selected_object_info, "supports_rotate", False)
                ):
                    self._clear_text_selection()
                    self._object_drag_pending = False
                    self._object_drag_active = False
                    self._object_rotate_pending = True
                    self._object_drag_start_scene_pos = scene_pos
                    self._object_drag_start_doc_rect = fitz.Rect(self._selected_object_info.bbox)
                    self._object_drag_preview_rect = fitz.Rect(self._selected_object_info.bbox)
                    self._object_drag_page_idx = max(0, int(self._selected_object_info.page_num) - 1)
                    event.accept()
                    return
                page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
                try:
                    object_info = self.controller.get_object_info_at_point(page_idx + 1, doc_point)
                except Exception:
                    object_info = None
                if object_info is not None:
                    allowed_kinds = ("rect", "image", "native_image") if self.current_mode == "objects" else ("textbox",)
                    if getattr(object_info, "object_kind", None) in allowed_kinds:
                        if not hasattr(self, "_selected_object_infos") or self._selected_object_infos is None:
                            self._selected_object_infos = {}
                        if not hasattr(self, "_selected_object_page_idx"):
                            self._selected_object_page_idx = None

                        additive = False
                        try:
                            additive = bool(getattr(event, "modifiers")() & Qt.ShiftModifier)
                        except Exception:
                            additive = False

                        if self._selected_object_page_idx is not None and int(self._selected_object_page_idx) != int(page_idx):
                            # Same-page only: selecting on a different page resets the set.
                            self._selected_object_infos = {}
                        self._selected_object_page_idx = int(page_idx)

                        object_id = str(getattr(object_info, "object_id", ""))
                        if additive and object_id:
                            if object_id in self._selected_object_infos:
                                self._selected_object_infos.pop(object_id, None)
                            else:
                                self._selected_object_infos[object_id] = object_info
                        else:
                            self._selected_object_infos = {object_id: object_info} if object_id else {}

                        # Selection visuals and handles are single-select only in this tranche.
                        if len(self._selected_object_infos) == 1:
                            self._clear_text_selection()
                            self._select_object(object_info)
                        else:
                            self._clear_text_selection()
                            self._selected_object_info = None
                        self._clear_text_selection()
                        try:
                            self._object_drag_start_doc_rects = {
                                str(info.object_id): fitz.Rect(info.bbox) for info in self._selected_object_infos.values()
                            }
                        except Exception:
                            self._object_drag_start_doc_rects = None
                        self._object_drag_preview_rects = None
                        self._object_drag_pending = not self._point_hits_object_rotate_handle(scene_pos)
                        self._object_drag_active = False
                        self._object_rotate_pending = not self._object_drag_pending
                        self._object_drag_start_scene_pos = scene_pos
                        self._object_drag_start_doc_rect = fitz.Rect(object_info.bbox)
                        self._object_drag_preview_rect = fitz.Rect(object_info.bbox)
                        self._object_drag_page_idx = page_idx
                        event.accept()
                        return

            if self.current_mode == 'browse':
                page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
                try:
                    info = self.controller.get_text_info_at_point(
                        page_idx + 1,
                        doc_point,
                        allow_fallback=False,
                    )
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
                        self._text_edit_drag_state = TextEditDragState.PENDING
                        self._pending_text_info = None
                        self._drag_start_scene_pos = scene_pos
                        self._drag_editor_start_pos = self.text_editor.pos()
                        return
                    self._drag_pending = False
                    self._drag_active = False
                    self._text_edit_drag_state = TextEditDragState.IDLE
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
                        self._text_edit_drag_state = TextEditDragState.PENDING
                        self._pending_text_info = None  # 已有編輯框，不需 pending_text_info
                        self._drag_start_scene_pos = scene_pos
                        self._drag_editor_start_pos = self.text_editor.pos()
                        return
                    else:
                        # 點擊在編輯框外：先結束編輯
                        self._drag_pending = False
                        self._drag_active = False
                        self._text_edit_drag_state = TextEditDragState.IDLE
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
                        self._text_edit_drag_state = TextEditDragState.PENDING
                        self._drag_start_scene_pos = scene_pos
                        self._drag_editor_start_pos = None  # 尚無編輯框
                        return
                except Exception as e:
                    logger.error(f"開啟編輯框失敗: {e}")

        if self.current_mode in ['rect', 'highlight']:
            self.drawing_start = scene_pos
        QGraphicsView.mousePressEvent(self.graphics_view, event)

    def _mouse_move(self, event):
        scene_pos = self._event_scene_pos(event)

        if self.current_mode in ("objects", "text_edit", "edit_text"):
            if getattr(self, "_object_resize_pending", False) and getattr(self, "_object_resize_start_scene_pos", None) is not None:
                dx = scene_pos.x() - self._object_resize_start_scene_pos.x()
                dy = scene_pos.y() - self._object_resize_start_scene_pos.y()
                if (
                    not getattr(self, "_object_resize_active", False)
                    and math.hypot(dx, dy) >= TextEditGeometryConstants.DRAG_START_DISTANCE_PX
                ):
                    self._object_resize_active = True
                if self._object_resize_active and getattr(self, "_object_resize_start_doc_rect", None) is not None:
                    rs = self._render_scale if self._render_scale > 0 else 1.0
                    dx_doc = dx / rs
                    dy_doc = dy / rs
                    start_rect = fitz.Rect(self._object_resize_start_doc_rect)
                    preview = fitz.Rect(
                        start_rect.x0,
                        start_rect.y0,
                        start_rect.x1 + dx_doc,
                        start_rect.y1 + dy_doc,
                    )
                    self._object_resize_preview_rect = preview
                    self._update_object_selection_visuals(preview)
                    event.accept()
                    return
            if getattr(self, "_object_drag_pending", False) and getattr(self, "_object_drag_start_scene_pos", None) is not None:
                dx = scene_pos.x() - self._object_drag_start_scene_pos.x()
                dy = scene_pos.y() - self._object_drag_start_scene_pos.y()
                if math.hypot(dx, dy) >= TextEditGeometryConstants.DRAG_START_DISTANCE_PX:
                    self._object_drag_pending = False
                    self._object_drag_active = True
            if getattr(self, "_object_drag_active", False) and getattr(self, "_object_drag_start_scene_pos", None) is not None:
                rs = self._render_scale if self._render_scale > 0 else 1.0
                dx_doc = (scene_pos.x() - self._object_drag_start_scene_pos.x()) / rs
                dy_doc = (scene_pos.y() - self._object_drag_start_scene_pos.y()) / rs

                start_rects = getattr(self, "_object_drag_start_doc_rects", None)
                if start_rects:
                    preview_rects: dict[str, fitz.Rect] = {}
                    for object_id, rect in start_rects.items():
                        start_rect = fitz.Rect(rect)
                        preview_rects[object_id] = fitz.Rect(
                            start_rect.x0 + dx_doc,
                            start_rect.y0 + dy_doc,
                            start_rect.x1 + dx_doc,
                            start_rect.y1 + dy_doc,
                        )
                    self._object_drag_preview_rects = preview_rects
                elif self._selected_object_info is not None and self._object_drag_start_doc_rect is not None:
                    start_rect = fitz.Rect(self._object_drag_start_doc_rect)
                    preview = fitz.Rect(
                        start_rect.x0 + dx_doc,
                        start_rect.y0 + dy_doc,
                        start_rect.x1 + dx_doc,
                        start_rect.y1 + dy_doc,
                    )
                    self._object_drag_preview_rect = preview
                    self._update_object_selection_visuals(preview)
                event.accept()
                return

        if self.current_mode == 'browse':
            if self._selected_object_info is not None and self._object_drag_pending and self._object_drag_start_scene_pos is not None:
                dx = scene_pos.x() - self._object_drag_start_scene_pos.x()
                dy = scene_pos.y() - self._object_drag_start_scene_pos.y()
                if math.hypot(dx, dy) >= TextEditGeometryConstants.DRAG_START_DISTANCE_PX:
                    self._object_drag_pending = False
                    self._object_drag_active = True
            if self._selected_object_info is not None and self._object_drag_active and self._object_drag_start_doc_rect is not None:
                rs = self._render_scale if self._render_scale > 0 else 1.0
                dx_doc = (scene_pos.x() - self._object_drag_start_scene_pos.x()) / rs
                dy_doc = (scene_pos.y() - self._object_drag_start_scene_pos.y()) / rs
                start_rect = fitz.Rect(self._object_drag_start_doc_rect)
                preview = fitz.Rect(
                    start_rect.x0 + dx_doc,
                    start_rect.y0 + dy_doc,
                    start_rect.x1 + dx_doc,
                    start_rect.y1 + dy_doc,
                )
                try:
                    page_rect = fitz.Rect(self.controller.model.doc[self._object_drag_page_idx].rect)
                    if preview.x0 < page_rect.x0:
                        preview = fitz.Rect(page_rect.x0, preview.y0, page_rect.x0 + start_rect.width, preview.y1)
                    if preview.y0 < page_rect.y0:
                        preview = fitz.Rect(preview.x0, page_rect.y0, preview.x1, page_rect.y0 + start_rect.height)
                    if preview.x1 > page_rect.x1:
                        preview = fitz.Rect(page_rect.x1 - start_rect.width, preview.y0, page_rect.x1, preview.y1)
                    if preview.y1 > page_rect.y1:
                        preview = fitz.Rect(preview.x0, page_rect.y1 - start_rect.height, preview.x1, page_rect.y1)
                except Exception:
                    pass
                self._object_drag_preview_rect = preview
                self._update_object_selection_visuals(preview)
                event.accept()
                return
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
                if self._should_start_editor_drag(dx, dy):
                    self._drag_pending = False
                    self._drag_active = True
                    self._text_edit_drag_state = TextEditDragState.ACTIVE
                    self.graphics_view.viewport().setCursor(Qt.ClosedHandCursor)

                    # 若尚無編輯框（點的是新文字塊），此時才建立並進入拖曳
                    if not self.text_editor and self._pending_text_info:
                        self._create_text_editor(*self._pending_text_info)
                        self._pending_text_info = None
                        # 記錄剛建立的編輯框初始位置，並立即套用當前偏移量
                        self._drag_editor_start_pos = self.text_editor.pos()
                        raw_y = self._drag_editor_start_pos.y() + dy
                        page_idx = self._resolve_editor_page_idx_for_drag(raw_y)
                        self._editing_page_idx = page_idx
                        clamped_x, clamped_y = self._clamp_editor_pos_to_page(
                            self._drag_editor_start_pos.x() + dx,
                            raw_y,
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
                page_idx = self._resolve_editor_page_idx_for_drag(raw_y)
                self._editing_page_idx = page_idx
                new_x, new_y = self._clamp_editor_pos_to_page(raw_x, raw_y, page_idx)
                self.text_editor.setPos(new_x, new_y)
                self._refresh_text_editor_mask_color()
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
            info = self.controller.get_text_info_at_point(
                page_idx + 1,
                doc_point,
                allow_fallback=False,
            )
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

    def _scene_rect_to_doc_rect(self, scene_rect: QRectF, page_idx: int) -> fitz.Rect | None:
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
        try:
            hit_page_idx, doc_point = self._scene_pos_to_page_and_doc_point(start_pos)
            if hit_page_idx != page_idx:
                return
            start_hit = self.controller.get_text_info_at_point(
                page_idx + 1,
                doc_point,
                allow_fallback=False,
            )
        except Exception:
            start_hit = None
        if start_hit is None or not getattr(start_hit, "target_span_id", None):
            return
        self._text_selection_active = True
        self._text_selection_page_idx = page_idx
        self._text_selection_start_scene_pos = start_pos
        self._text_selection_live_doc_rect = None
        self._text_selection_live_text = ""
        self._text_selection_last_scene_pos = None
        self._text_selection_start_span_id = start_hit.target_span_id
        self._text_selection_start_hit_info = start_hit
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
        try:
            end_page_idx, end_doc_point = self._scene_pos_to_page_and_doc_point(end_pos)
        except Exception:
            end_page_idx, end_doc_point = self._text_selection_page_idx, None
        if end_doc_point is None or end_page_idx != self._text_selection_page_idx:
            self._text_selection_live_doc_rect = None
            self._text_selection_live_text = ""
            self._text_selection_rect_item.setVisible(False)
            return

        try:
            selected_text, precise_doc_rect = self.controller.get_text_selection_snapshot_from_run(
                self._text_selection_page_idx + 1,
                self._text_selection_start_span_id,
                end_doc_point,
            )
        except Exception:
            selected_text = ""
            precise_doc_rect = None
        if not selected_text.strip():
            self._text_selection_live_doc_rect = None
            self._text_selection_live_text = ""
            self._text_selection_rect_item.setVisible(False)
            return
        if precise_doc_rect is None or precise_doc_rect.width <= 0 or precise_doc_rect.height <= 0:
            self._text_selection_live_doc_rect = None
            self._text_selection_live_text = ""
            self._text_selection_rect_item.setVisible(False)
            return

        self._text_selection_live_doc_rect = precise_doc_rect
        self._text_selection_live_text = selected_text
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
        selected_text = (getattr(self, "_text_selection_live_text", "") or "").strip()
        if not selected_text.strip():
            self._clear_text_selection()
            return
        self._selected_text_page_idx = page_idx
        self._selected_text_rect_doc = fitz.Rect(doc_rect)
        self._selected_text_cached = selected_text
        self._selected_text_hit_info = getattr(self, "_text_selection_start_hit_info", None)
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
        self._sync_text_property_panel_state()

    def _clear_text_selection(self) -> None:
        self._text_selection_active = False
        self._text_selection_page_idx = None
        self._text_selection_start_scene_pos = None
        self._text_selection_live_doc_rect = None
        self._text_selection_live_text = ""
        self._text_selection_last_scene_pos = None
        self._text_selection_start_span_id = None
        self._text_selection_start_hit_info = None
        self._selected_text_rect_doc = None
        self._selected_text_page_idx = None
        self._selected_text_cached = ""
        self._selected_text_hit_info = None
        if self._text_selection_rect_item is not None:
            try:
                if self._text_selection_rect_item.scene():
                    self.scene.removeItem(self._text_selection_rect_item)
            except Exception:
                pass
            self._text_selection_rect_item = None
        self._sync_text_property_panel_state()

    def _resolve_text_info_for_doc_rect(self, page_idx: int, doc_rect: fitz.Rect):
        controller = getattr(self, "controller", None)
        if controller is None or doc_rect is None:
            return None
        try:
            center = fitz.Point((doc_rect.x0 + doc_rect.x1) / 2.0, (doc_rect.y0 + doc_rect.y1) / 2.0)
            return controller.get_text_info_at_point(page_idx + 1, center)
        except Exception:
            return None

    def _resolve_text_info_for_context_menu_pos(self, pos: QPoint):
        if self.current_mode != "browse":
            return None
        controller = getattr(self, "controller", None)
        graphics_view = getattr(self, "graphics_view", None)
        if controller is None or graphics_view is None:
            return None
        try:
            scene_pos = graphics_view.mapToScene(pos)
            page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
            info = controller.get_text_info_at_point(page_idx + 1, doc_point)
        except Exception:
            return None
        if info is None:
            return None
        return page_idx, info

    def _resolve_object_info_for_context_menu_pos(self, pos: QPoint):
        if self.current_mode not in ("browse", "objects", "edit_text", "text_edit"):
            return None
        controller = getattr(self, "controller", None)
        graphics_view = getattr(self, "graphics_view", None)
        if controller is None or graphics_view is None:
            return None
        try:
            scene_pos = graphics_view.mapToScene(pos)
            page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
            info = controller.get_object_info_at_point(page_idx + 1, doc_point)
        except Exception:
            return None
        if info is None:
            return None
        allowed_kinds = None
        if self.current_mode == "objects":
            allowed_kinds = ("rect", "image")
        elif self.current_mode in ("edit_text", "text_edit"):
            allowed_kinds = ("textbox",)
        if allowed_kinds is not None and getattr(info, "object_kind", None) not in allowed_kinds:
            return None
        return page_idx, info

    def _select_all_text_on_current_page(self) -> bool:
        if self.total_pages <= 0:
            return False
        controller = getattr(self, "controller", None)
        model = getattr(controller, "model", None) if controller is not None else None
        if model is None or not getattr(model, "doc", None):
            return False

        page_idx = min(max(self.current_page, 0), self.total_pages - 1)
        try:
            page_rect = fitz.Rect(model.doc[page_idx].rect)
        except Exception:
            return False

        try:
            selected_text = controller.get_text_in_rect(page_idx + 1, page_rect)
        except Exception:
            selected_text = ""
        if not selected_text.strip():
            return False

        precise_doc_rect = fitz.Rect(page_rect)
        try:
            precise = controller.get_text_bounds(page_idx + 1, page_rect)
            if precise is not None and precise.width > 0 and precise.height > 0:
                precise_doc_rect = fitz.Rect(precise)
        except Exception:
            pass

        self._selected_text_page_idx = page_idx
        self._selected_text_rect_doc = precise_doc_rect
        self._selected_text_cached = selected_text
        self._selected_text_hit_info = self._resolve_text_info_for_doc_rect(page_idx, precise_doc_rect)

        if self._text_selection_rect_item is None and getattr(self, "scene", None) is not None:
            pen = QPen(QColor(30, 120, 255, 200), 2)
            brush = QBrush(QColor(30, 120, 255, 35))
            self._text_selection_rect_item = self.scene.addRect(QRectF(), pen, brush)
            self._text_selection_rect_item.setZValue(11)

        if self._text_selection_rect_item is not None:
            rs = self._render_scale if self._render_scale > 0 else 1.0
            y0 = self.page_y_positions[page_idx] if (
                self.continuous_pages and page_idx < len(self.page_y_positions)
            ) else 0.0
            scene_rect = QRectF(
                precise_doc_rect.x0 * rs,
                y0 + precise_doc_rect.y0 * rs,
                max(1.0, precise_doc_rect.width * rs),
                max(1.0, precise_doc_rect.height * rs),
            )
            self._text_selection_rect_item.setRect(scene_rect)
            self._text_selection_rect_item.setVisible(True)

        self._sync_text_property_panel_state()
        return True

    def _zoom_relative(self, factor: float) -> None:
        try:
            new_scale = float(self.scale) * float(factor)
        except (TypeError, ValueError):
            return
        new_scale = max(0.1, min(4.0, new_scale))
        self.sig_scale_changed.emit(self.current_page, new_scale)

    def _start_text_edit_from_hit(self, page_idx: int, info) -> bool:
        if info is None:
            return False
        try:
            self.set_mode("edit_text")
            self.editing_font_name = info.font
            self.editing_color = info.color
            self.editing_original_text = info.target_text
            self._editing_page_idx = page_idx
            self._create_text_editor(
                info.target_bbox,
                info.target_text,
                info.font,
                info.size,
                info.color,
                info.rotation,
                info.target_span_id,
                getattr(info, "target_mode", "run"),
            )
            return True
        except Exception as exc:
            logger.error("open edit text from context menu failed: %s", exc)
            return False

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

    def _clear_object_selection(self) -> None:
        self._selected_object_info = None
        if hasattr(self, "_selected_object_infos"):
            self._selected_object_infos = {}
        if hasattr(self, "_selected_object_page_idx"):
            self._selected_object_page_idx = None
        self._object_drag_pending = False
        self._object_drag_active = False
        self._object_rotate_pending = False
        self._object_drag_start_scene_pos = None
        self._object_drag_start_doc_rect = None
        self._object_drag_preview_rect = None
        self._object_drag_page_idx = None
        if self._object_selection_rect_item is not None:
            try:
                self.scene.removeItem(self._object_selection_rect_item)
            except Exception:
                pass
            self._object_selection_rect_item = None
        if self._object_rotate_handle_item is not None:
            try:
                self.scene.removeItem(self._object_rotate_handle_item)
            except Exception:
                pass
            self._object_rotate_handle_item = None
        for item in getattr(self, "_object_resize_handle_items", []) or []:
            try:
                self.scene.removeItem(item)
            except Exception:
                pass
        self._object_resize_handle_items = []
        self._object_resize_pending = False
        self._object_resize_active = False
        self._object_resize_start_scene_pos = None
        self._object_resize_start_doc_rect = None
        self._object_resize_preview_rect = None

    def _select_object(self, info) -> None:
        self._selected_object_info = info
        self._update_object_selection_visuals()

    def _update_object_selection_visuals(self, rect: fitz.Rect | None = None) -> None:
        info = getattr(self, "_selected_object_info", None)
        if info is None or getattr(self, "scene", None) is None:
            return
        bbox = fitz.Rect(rect if rect is not None else info.bbox)
        rs = self._render_scale if self._render_scale > 0 else 1.0
        page_idx = max(0, int(info.page_num) - 1)
        y0 = self.page_y_positions[page_idx] if (
            self.continuous_pages and page_idx < len(self.page_y_positions)
        ) else 0.0
        scene_rect = QRectF(
            bbox.x0 * rs,
            y0 + bbox.y0 * rs,
            max(1.0, bbox.width * rs),
            max(1.0, bbox.height * rs),
        )
        pen = QPen(QColor(14, 165, 233, 220), 2)
        brush = QBrush(QColor(14, 165, 233, 30))
        if self._object_selection_rect_item is None:
            self._object_selection_rect_item = self.scene.addRect(scene_rect, pen, brush)
            self._object_selection_rect_item.setZValue(21)
        else:
            self._object_selection_rect_item.setRect(scene_rect)
            self._object_selection_rect_item.setPen(pen)
            self._object_selection_rect_item.setBrush(brush)
        if info.supports_rotate:
            handle_rect = QRectF(scene_rect.right() - 12, scene_rect.top() - 18, 12, 12)
            if self._object_rotate_handle_item is None:
                self._object_rotate_handle_item = self.scene.addEllipse(
                    handle_rect,
                    QPen(QColor(2, 132, 199, 230), 1),
                    QBrush(QColor(56, 189, 248, 220)),
                )
                self._object_rotate_handle_item.setZValue(22)
            else:
                self._object_rotate_handle_item.setRect(handle_rect)
        elif self._object_rotate_handle_item is not None:
            try:
                self.scene.removeItem(self._object_rotate_handle_item)
            except Exception:
                pass
            self._object_rotate_handle_item = None

        # Resize handles: single-select only.
        if getattr(self, "_object_resize_handle_items", None) is None:
            self._object_resize_handle_items = []
        for item in list(self._object_resize_handle_items):
            try:
                self.scene.removeItem(item)
            except Exception:
                pass
        self._object_resize_handle_items = []

        handle_size = 10.0
        half = handle_size / 2.0
        handle_pen = QPen(QColor(2, 132, 199, 230), 1)
        handle_brush = QBrush(QColor(56, 189, 248, 220))
        for hx, hy in (
            (scene_rect.left() - half, scene_rect.top() - half),  # TL
            (scene_rect.right() - half, scene_rect.top() - half),  # TR
            (scene_rect.left() - half, scene_rect.bottom() - half),  # BL
            (scene_rect.right() - half, scene_rect.bottom() - half),  # BR
        ):
            hrect = QRectF(hx, hy, handle_size, handle_size)
            item = self.scene.addRect(hrect, handle_pen, handle_brush)
            try:
                item.setZValue(22)
            except Exception:
                pass
            self._object_resize_handle_items.append(item)

    def _point_hits_object_resize_handle(self, scene_pos: QPointF) -> bool:
        items = getattr(self, "_object_resize_handle_items", None) or []
        for item in items:
            try:
                if item.rect().contains(scene_pos):
                    return True
            except Exception:
                continue
        return False

    def _point_hits_object_rotate_handle(self, scene_pos: QPointF) -> bool:
        if self._object_rotate_handle_item is None:
            return False
        try:
            return self._object_rotate_handle_item.rect().contains(scene_pos)
        except Exception:
            return False

    def _delete_selected_object(self) -> bool:
        infos = getattr(self, "_selected_object_infos", None)
        if infos and len(infos) > 1:
            refs: list[ObjectRef] = []
            for info in infos.values():
                if not getattr(info, "supports_delete", False):
                    continue
                refs.append(
                    ObjectRef(
                        object_id=str(info.object_id),
                        object_kind=str(info.object_kind),
                        page_num=int(info.page_num),
                    )
                )
            if not refs:
                return False
            self.sig_delete_object.emit(BatchDeleteObjectsRequest(objects=refs))
            self._clear_object_selection()
            return True
        info = getattr(self, "_selected_object_info", None)
        if info is None or not getattr(info, "supports_delete", False):
            return False
        self.sig_delete_object.emit(
            DeleteObjectRequest(
                object_id=info.object_id,
                object_kind=info.object_kind,
                page_num=info.page_num,
            )
        )
        self._clear_object_selection()
        return True

    def _rotate_selected_object(self, rotation_delta: int) -> bool:
        info = getattr(self, "_selected_object_info", None)
        if info is None or not getattr(info, "supports_rotate", False):
            return False
        self.sig_rotate_object.emit(
            RotateObjectRequest(
                object_id=info.object_id,
                object_kind=info.object_kind,
                page_num=info.page_num,
                rotation_delta=rotation_delta,
            )
        )
        self._selected_object_info = type(info)(
            object_kind=info.object_kind,
            object_id=info.object_id,
            page_num=info.page_num,
            bbox=fitz.Rect(info.bbox),
            rotation=(int(info.rotation) + int(rotation_delta)) % 360,
            supports_move=info.supports_move,
            supports_delete=info.supports_delete,
            supports_rotate=info.supports_rotate,
        )
        self._update_object_selection_visuals()
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

    def _draw_all_block_outlines(self, *args) -> None:
        """Draw persistent dim outlines around text blocks on visible pages (edit_text mode only)."""
        self._clear_all_block_outlines()
        if not hasattr(self, 'controller') or not self.controller.model.doc:
            return
        rs = self._render_scale if self._render_scale > 0 else 1.0
        try:
            start_page, end_page = self.visible_page_range(prefetch=1)
        except Exception:
            return
        pen = QPen(QColor(100, 149, 237, 120), 1.0, Qt.DashLine)
        brush = QBrush(Qt.NoBrush)
        for page_idx in range(start_page, end_page + 1):
            page_num = page_idx + 1
            try:
                self.controller.model.ensure_page_index_built(page_num)
                outline_targets = self._iter_outline_targets(page_idx)
            except Exception:
                continue
            y0 = (self.page_y_positions[page_idx]
                  if (self.continuous_pages and page_idx < len(self.page_y_positions))
                  else 0.0)
            for outline_key, doc_rect in outline_targets:
                try:
                    scene_rect = QRectF(doc_rect.x0 * rs, y0 + doc_rect.y0 * rs,
                                        doc_rect.width * rs, doc_rect.height * rs)
                    item = self.scene.addRect(scene_rect, pen, brush)
                    item.setZValue(8)
                    self._block_outline_items[outline_key] = item
                except Exception:
                    continue
        # Re-hide outlines for active-editing block (survives redraw)
        if self._active_outline_key is not None:
            outline = self._block_outline_items.get(self._active_outline_key)
            if outline is not None:
                outline.setVisible(False)

    def _clear_all_block_outlines(self) -> None:
        """Remove all persistent block outline items from the scene."""
        for item in self._block_outline_items.values():
            try:
                self.scene.removeItem(item)
            except Exception:
                pass
        self._block_outline_items.clear()
        self._hover_hidden_outline_key = None

    def _schedule_outline_redraw(self, *args) -> None:
        """Debounce outline redraws driven by scroll/zoom signals (80 ms collapse window)."""
        self._outline_redraw_timer.start(80)

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
                # IBeam cursor signals the block is editable (guard: don't override drag cursor)
                if self.current_mode == 'edit_text' and self._text_edit_drag_state == TextEditDragState.IDLE:
                    self.graphics_view.viewport().setCursor(Qt.IBeamCursor)
                # Hide dim outline for hovered block; restore previously hidden one
                if self.current_mode == 'edit_text':
                    try:
                        hit_key = None
                        for outline_key, outline_rect in self._iter_outline_targets(page_idx):
                            if (outline_rect.x0 <= doc_rect.x0 + 1 and outline_rect.y0 <= doc_rect.y0 + 1
                                    and outline_rect.x1 >= doc_rect.x1 - 1 and outline_rect.y1 >= doc_rect.y1 - 1):
                                hit_key = outline_key
                                break
                        if hit_key != self._hover_hidden_outline_key:
                            # Restore previously hidden outline
                            if self._hover_hidden_outline_key is not None:
                                prev = self._block_outline_items.get(self._hover_hidden_outline_key)
                                if prev is not None:
                                    prev.setVisible(True)
                                self._hover_hidden_outline_key = None
                            # Hide new hovered block's outline
                            if hit_key is not None:
                                outline = self._block_outline_items.get(hit_key)
                                if outline is not None:
                                    outline.setVisible(False)
                                self._hover_hidden_outline_key = hit_key
                    except Exception:
                        pass
            else:
                self._clear_hover_highlight()
                if self.current_mode == 'edit_text' and self._text_edit_drag_state == TextEditDragState.IDLE:
                    self.graphics_view.viewport().setCursor(Qt.ArrowCursor)
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
        # Restore any dim outline hidden by hover
        if self._hover_hidden_outline_key is not None:
            prev = self._block_outline_items.get(self._hover_hidden_outline_key)
            if prev is not None:
                try:
                    prev.setVisible(True)
                except Exception:
                    pass
            self._hover_hidden_outline_key = None

    def _mouse_release(self, event):
        # ── 拖曳移動文字框的放開處理 ──
        if self.current_mode in ("objects", "text_edit", "edit_text") and event.button() == Qt.LeftButton:
            if getattr(self, "_object_resize_pending", False):
                preview = getattr(self, "_object_resize_preview_rect", None)
                start_rect = getattr(self, "_object_resize_start_doc_rect", None)
                self._object_resize_pending = False
                active = bool(getattr(self, "_object_resize_active", False))
                self._object_resize_active = False
                if active and preview is not None and start_rect is not None and self._selected_object_info is not None:
                    self.sig_resize_object.emit(
                        ResizeObjectRequest(
                            object_id=self._selected_object_info.object_id,
                            object_kind=self._selected_object_info.object_kind,
                            page_num=self._selected_object_info.page_num,
                            destination_rect=fitz.Rect(preview),
                        )
                    )
                    self._selected_object_info = type(self._selected_object_info)(
                        object_kind=self._selected_object_info.object_kind,
                        object_id=self._selected_object_info.object_id,
                        page_num=self._selected_object_info.page_num,
                        bbox=fitz.Rect(preview),
                        rotation=self._selected_object_info.rotation,
                        supports_move=self._selected_object_info.supports_move,
                        supports_delete=self._selected_object_info.supports_delete,
                        supports_rotate=self._selected_object_info.supports_rotate,
                    )
                    self._update_object_selection_visuals()
                event.accept()
                return
            if getattr(self, "_object_rotate_pending", False):
                self._object_rotate_pending = False
                self._object_drag_pending = False
                if self._selected_object_info is not None:
                    self._rotate_selected_object(90)
                event.accept()
                return

            preview_rects = getattr(self, "_object_drag_preview_rects", None)
            if getattr(self, "_object_drag_active", False) and preview_rects:
                self._object_drag_active = False
                self._object_drag_pending = False
                infos = getattr(self, "_selected_object_infos", None) or {}
                moves: list[MoveObjectRequest] = []
                for object_id, preview in preview_rects.items():
                    info = infos.get(object_id)
                    if info is None or not getattr(info, "supports_move", False):
                        continue
                    moves.append(
                        MoveObjectRequest(
                            object_id=info.object_id,
                            object_kind=info.object_kind,
                            source_page=info.page_num,
                            destination_page=info.page_num,
                            destination_rect=fitz.Rect(preview),
                        )
                    )
                if moves:
                    self.sig_move_object.emit(BatchMoveObjectsRequest(moves=moves))
                event.accept()
                return

            if getattr(self, "_object_drag_active", False) and self._object_drag_preview_rect is not None and self._selected_object_info is not None:
                preview = fitz.Rect(self._object_drag_preview_rect)
                start_rect = fitz.Rect(self._object_drag_start_doc_rect)
                self._object_drag_active = False
                self._object_drag_pending = False
                if any(abs(a - b) > 0.5 for a, b in zip(preview, start_rect)):
                    request = MoveObjectRequest(
                        object_id=self._selected_object_info.object_id,
                        object_kind=self._selected_object_info.object_kind,
                        source_page=self._selected_object_info.page_num,
                        destination_page=self._selected_object_info.page_num,
                        destination_rect=preview,
                    )
                    self.sig_move_object.emit(request)
                event.accept()
                return

            if getattr(self, "_object_drag_pending", False):
                self._object_drag_pending = False
                event.accept()
                return

        if self.current_mode == 'browse' and event.button() == Qt.LeftButton and self._selected_object_info is not None:
            if self._object_rotate_pending:
                self._object_rotate_pending = False
                self._object_drag_pending = False
                self._rotate_selected_object(90)
                event.accept()
                return
            if self._object_drag_active and self._object_drag_preview_rect is not None:
                preview = fitz.Rect(self._object_drag_preview_rect)
                start_rect = fitz.Rect(self._object_drag_start_doc_rect)
                self._object_drag_active = False
                self._object_drag_pending = False
                if any(abs(a - b) > 0.5 for a, b in zip(preview, start_rect)):
                    request = MoveObjectRequest(
                        object_id=self._selected_object_info.object_id,
                        object_kind=self._selected_object_info.object_kind,
                        source_page=self._selected_object_info.page_num,
                        destination_page=self._selected_object_info.page_num,
                        destination_rect=preview,
                    )
                    self.sig_move_object.emit(request)
                    self._selected_object_info = type(self._selected_object_info)(
                        object_kind=self._selected_object_info.object_kind,
                        object_id=self._selected_object_info.object_id,
                        page_num=self._selected_object_info.page_num,
                        bbox=fitz.Rect(preview),
                        rotation=self._selected_object_info.rotation,
                        supports_move=self._selected_object_info.supports_move,
                        supports_delete=self._selected_object_info.supports_delete,
                        supports_rotate=self._selected_object_info.supports_rotate,
                    )
                self._update_object_selection_visuals()
                event.accept()
                return
            if self._object_drag_pending:
                self._object_drag_pending = False
                event.accept()
                return
        if self.current_mode == 'browse' and event.button() == Qt.LeftButton and self._text_selection_active:
            scene_pos = self._event_scene_pos(event)
            self._finalize_text_selection(scene_pos)
            event.accept()
            return

        if self.current_mode in ('edit_text', 'add_text') and event.button() == Qt.LeftButton:
            scene_pos = self._event_scene_pos(event)

            if self._drag_pending:
                self._drag_pending = False
                self._text_edit_drag_state = TextEditDragState.IDLE
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
                self._text_edit_drag_state = TextEditDragState.IDLE
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

        end_pos = self._event_scene_pos(event)
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
        self._ensure_text_edit_manager().create_text_editor(
            rect=rect,
            text=text,
            font_name=font_name,
            font_size=font_size,
            color=color,
            rotation=rotation,
            target_span_id=target_span_id,
            target_mode=target_mode,
            editor_intent=editor_intent,
        )
        # Hide the dim block outline for the block being edited
        try:
            page_idx = getattr(self, '_editing_page_idx', self.current_page)
            for outline_key, outline_rect in self._iter_outline_targets(page_idx):
                if (abs(outline_rect.x0 - rect.x0) < 2 and abs(outline_rect.y0 - rect.y0) < 2
                        and abs(outline_rect.x1 - rect.x1) < 2 and abs(outline_rect.y1 - rect.y1) < 2):
                    self._active_outline_key = outline_key
                    outline = self._block_outline_items.get(self._active_outline_key)
                    if outline is not None:
                        outline.setVisible(False)
                    break
        except Exception:
            pass

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
        self._ensure_text_edit_manager().on_edit_font_family_changed(*_)

    def _on_edit_font_size_changed(self, size_str: str):
        """編輯中變更字級時，更新編輯框字型以即時預覽。"""
        self._ensure_text_edit_manager().on_edit_font_size_changed(size_str)

    def _finalize_text_edit(
        self,
        reason: TextEditFinalizeReason = TextEditFinalizeReason.CLICK_AWAY,
    ) -> TextEditFinalizeResult | None:
        return self._ensure_text_edit_manager().finalize_text_edit(reason)

    def _finalize_text_edit_impl(
        self,
        reason: TextEditFinalizeReason = TextEditFinalizeReason.CLICK_AWAY,
    ) -> TextEditFinalizeResult:
        return self._ensure_text_edit_manager().finalize_text_edit_impl(reason)

    def _show_context_menu(self, pos):
        menu = QMenu()
        object_hit = self._resolve_object_info_for_context_menu_pos(pos)
        text_hit = self._resolve_text_info_for_context_menu_pos(pos)

        selected_text_cached = getattr(self, "_selected_text_cached", "")
        selected_text_rect_doc = getattr(self, "_selected_text_rect_doc", None)
        if self.current_mode == 'browse' and (selected_text_cached or selected_text_rect_doc is not None):
            menu.addAction("Copy Selected Text", self._copy_selected_text_to_clipboard)
        if self.current_mode in ("browse", "objects", "edit_text", "text_edit"):
            if object_hit is not None:
                self._select_object(object_hit)
            selected_object = getattr(self, "_selected_object_info", None)
            if selected_object is not None:
                if getattr(selected_object, "supports_delete", False):
                    menu.addAction("Delete Object", self._delete_selected_object)
                if getattr(selected_object, "supports_rotate", False):
                    menu.addAction("Rotate Object 90°", lambda checked=False: self._rotate_selected_object(90))
                menu.addSeparator()
        if self.current_mode == 'browse':
            menu.addAction("Select All", self._select_all_text_on_current_page)
            if text_hit is not None:
                page_idx, info = text_hit
                menu.addAction(
                    "Edit Text",
                    lambda checked=False, idx=page_idx, hit=info: self._start_text_edit_from_hit(idx, hit),
                )
            menu.addSeparator()
            menu.addAction("Zoom In", lambda: self._zoom_relative(1.1))
            menu.addAction("Zoom Out", lambda: self._zoom_relative(1 / 1.1))
            menu.addAction("Fit to View", self._fit_to_view)
            menu.addSeparator()
            current_page_num = self.current_page + 1
            menu.addAction("匯出目前頁面...", lambda checked=False, p=current_page_num: self._export_specific_pages([p]))
            menu.addAction("向右旋轉目前頁面 90°", lambda checked=False, p=current_page_num: self._rotate_specific_pages([p], 90))
            menu.addAction("向左旋轉目前頁面 90°", lambda checked=False, p=current_page_num: self._rotate_specific_pages([p], 270))
            menu.addAction("刪除目前頁面", lambda checked=False, p=current_page_num: self._delete_specific_pages([p]))
            menu.addAction("在目前頁面後插入空白頁", lambda checked=False, p=current_page_num: self._insert_blank_page_at(p + 1))
            menu.addAction(
                "在目前頁面後插入其他 PDF 頁面...",
                lambda checked=False, p=current_page_num: self._insert_pages_from_file_at(p + 1),
            )
            menu.addSeparator()
        if self.current_mode == "objects":
            target = self._resolve_default_image_insert_target(pos)
            if target is not None:
                page_num, visual_rect = target
                menu.addAction(
                    "插入圖片...",
                    lambda checked=False, p=page_num, r=fitz.Rect(visual_rect): self._insert_image_object_from_file(page_num=p, visual_rect=r),
                )
                menu.addAction(
                    "從剪貼簿貼上圖片",
                    lambda checked=False, p=page_num, r=fitz.Rect(visual_rect): self._insert_image_object_from_clipboard(page_num=p, visual_rect=r),
                )
                menu.addSeparator()
        if self._fullscreen_active:
            menu.addAction("離開全螢幕", self.sig_toggle_fullscreen.emit)
            menu.addSeparator()
        menu.addAction("另存PDF", self._save_as)
        menu.addAction("列印...", self._print_document)
        menu.addAction("另存為最佳化的副本", self._optimize_pdf_copy)
        menu.addSeparator()
        menu.addAction("旋轉頁面", self._rotate_pages)
        global_pos = self.graphics_view.mapToGlobal(pos) if getattr(self, "graphics_view", None) is not None else pos
        menu.exec_(global_pos)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟PDF", "", "PDF (*.pdf)")
        if path:
            self._queue_or_open_paths([path])

    def _print_document(self):
        if self.total_pages == 0:
            show_error(self, "沒有可列印的 PDF 文件")
            return
        self.sig_print_requested.emit()

    def ask_pdf_password(self, path: str) -> str | None:
        """開啟加密 PDF 時彈出密碼輸入框，回傳使用者輸入的密碼；若取消則回傳 None。"""
        dlg = PDFPasswordDialog(self, file_path=path)
        if dlg.exec() == QDialog.Accepted:
            return dlg.get_password() or None
        return None

    def _save(self):
        """存回原檔（Ctrl+S），若適用則使用增量更新。"""
        if self.text_editor and self.text_editor.widget():
            self._finalize_text_edit(TextEditFinalizeReason.SAVE_SHORTCUT)
        self.sig_save.emit()

    def _save_as(self):
        if self.text_editor and self.text_editor.widget():
            self._finalize_text_edit(TextEditFinalizeReason.SAVE_SHORTCUT)
        default_path = getattr(self, "_save_as_default_path", "")
        path, _ = QFileDialog.getSaveFileName(self, "另存PDF", default_path, "PDF (*.pdf)")
        if path:
            self.sig_save_as.emit(path)

    def _optimize_pdf_copy(self):
        if self.total_pages == 0:
            show_error(self, "沒有可最佳化的 PDF")
            return
        self.sig_optimize_pdf_copy_requested.emit()

    def _delete_pages(self):
        pages, ok = QInputDialog.getText(self, "刪除頁面", "輸入頁碼 (如 1,3-5):")
        if ok and pages:
            try:
                parsed = parse_pages(pages, self.total_pages)
                if parsed: self.sig_delete_pages.emit(parsed)
            except ValueError: show_error(self, "頁碼格式錯誤")

    def _delete_specific_pages(self, pages: list[int]) -> None:
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return
        if pages:
            self.sig_delete_pages.emit(sorted(set(int(page) for page in pages)))

    def _rotate_pages(self):
        pages, ok = QInputDialog.getText(self, "旋轉頁面", "輸入頁碼 (如 1,3-5):")
        if ok and pages:
            degrees, ok = QInputDialog.getInt(self, "旋轉角度", "輸入角度 (90, 180, 270):", 90, 0, 360, 90)
            if ok:
                try:
                    parsed = parse_pages(pages, self.total_pages)
                    if parsed: self.sig_rotate_pages.emit(parsed, degrees)
                except ValueError: show_error(self, "頁碼格式錯誤")

    def _rotate_specific_pages(self, pages: list[int], degrees: int) -> None:
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return
        if pages:
            self.sig_rotate_pages.emit(sorted(set(int(page) for page in pages)), degrees)

    @staticmethod
    def _normalize_image_extension(ext: str) -> str:
        ext = ext.lower().lstrip(".")
        if ext in ("jpg", "jpeg"):
            return "jpg"
        if ext == "png":
            return "png"
        if ext in ("tif", "tiff"):
            return "tiff"
        return ""

    def _resolve_image_format(self, path: str, selected_filter: str) -> str:
        lowered = (selected_filter or "").lower()
        # Prefer the file dialog's selected filter; fall back to typed extension.
        if "jpeg" in lowered or "jpg" in lowered:
            return "jpg"
        if "png" in lowered:
            return "png"
        if "tiff" in lowered or "tif" in lowered:
            return "tiff"
        ext = self._normalize_image_extension(Path(path).suffix)
        return ext or "png"

    def _export_pages(self):
        if self.total_pages == 0:
            show_error(self, "沒有可匯出的 PDF")
            return

        dlg = ExportPagesDialog(self, self.total_pages, self.current_page + 1)
        if dlg.exec() != QDialog.Accepted:
            return

        try:
            pages, dpi, as_image = dlg.get_values()
        except ValueError as exc:
            show_error(self, str(exc))
            return

        filters = "JPEG (*.jpg *.jpeg);;PNG (*.png);;TIFF (*.tif *.tiff)" if as_image else "PDF (*.pdf)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "匯出頁面", "", filters)
        if not path:
            return

        image_format = "png"
        if as_image:
            image_format = self._resolve_image_format(path, selected_filter)
            # If users type a basename only, append the resolved image extension.
            if not Path(path).suffix:
                path = f"{path}.{image_format}"
        else:
            if not Path(path).suffix:
                path = f"{path}.pdf"

        self.sig_export_pages.emit(pages, path, as_image, dpi, image_format)

    def _export_specific_pages(self, pages: list[int]) -> None:
        if self.total_pages == 0:
            show_error(self, "沒有可匯出的 PDF")
            return
        if not pages:
            return

        filters = "PDF (*.pdf);;JPEG (*.jpg *.jpeg);;PNG (*.png);;TIFF (*.tif *.tiff)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "匯出頁面", "", filters)
        if not path:
            return

        lowered = (selected_filter or "").lower()
        as_image = "pdf" not in lowered
        image_format = "png"
        if as_image:
            image_format = self._resolve_image_format(path, selected_filter)
            if not Path(path).suffix:
                path = f"{path}.{image_format}"
        else:
            if not Path(path).suffix:
                path = f"{path}.pdf"

        self.sig_export_pages.emit(sorted(set(int(page) for page in pages)), path, as_image, 300, image_format)

    def _show_search_panel(self):
        """Trigger search mode: switch left sidebar to Search tab, focus input (e.g. from Controller)."""
        self.left_sidebar.setCurrentIndex(1)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _show_thumbnails(self):
        self.left_sidebar.setCurrentIndex(0)

    def _show_annotation_panel(self):
        """Toggle annotations panel in left sidebar (e.g. from Controller after add)."""
        self.ensure_heavy_panels_initialized()
        self._ensure_left_sidebar_visible()
        self.left_sidebar.setCurrentIndex(2)

    def _show_watermark_panel(self):
        """Toggle watermarks panel in left sidebar."""
        self.ensure_heavy_panels_initialized()
        self._ensure_left_sidebar_visible()
        self.left_sidebar.setCurrentIndex(3)

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
        if getattr(self, "watermark_list_widget", None) is None:
            return
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

    def apply_search_ui_state(self, state: dict | None) -> None:
        state = state or {}
        query = state.get("query", "")
        results = list(state.get("results", []))
        idx = int(state.get("index", -1))
        if (
            getattr(self, "search_input", None) is None
            or getattr(self, "search_results_list", None) is None
        ):
            self.current_search_results = results
            self.current_search_index = -1
            return
        self.search_input.setText(query)
        self.display_search_results(results)
        if 0 <= idx < self.search_results_list.count():
            self.current_search_index = idx
            item = self.search_results_list.item(idx)
            if item:
                self.search_results_list.setCurrentItem(item)

    def clear_search_ui_state(self) -> None:
        self.apply_search_ui_state({"query": "", "results": [], "index": -1})

    def display_search_results(self, results: list[tuple[int, str, fitz.Rect]]):
        self.current_search_results = results
        self.current_search_index = -1
        if (
            getattr(self, "search_results_list", None) is None
            or getattr(self, "search_status_label", None) is None
            or getattr(self, "prev_btn", None) is None
            or getattr(self, "next_btn", None) is None
        ):
            return
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

    def populate_annotations_list(self, annotations: list[dict]):
        if getattr(self, "annotation_list", None) is None:
            return
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

    def _insert_blank_page_at(self, position: int) -> None:
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return
        bounded = max(1, min(int(position), self.total_pages + 1))
        self.sig_insert_blank_page.emit(bounded)

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

    def _insert_pages_from_file_at(self, position: int) -> None:
        if self.total_pages == 0:
            show_error(self, "沒有開啟的PDF文件")
            return

        source_file, _ = QFileDialog.getOpenFileName(
            self,
            "選擇來源PDF檔案",
            "",
            "PDF (*.pdf)"
        )
        if not source_file:
            return

        try:
            source_doc = fitz.open(source_file)
            source_total_pages = len(source_doc)
            source_doc.close()
        except Exception as e:
            show_error(self, f"無法讀取來源檔案: {e}")
            return

        pages_text, ok = QInputDialog.getText(
            self,
            "選擇要插入的頁面",
            f"輸入來源檔案中的頁碼 (如 1,3-5，總頁數: {source_total_pages}):"
        )
        if not ok or not pages_text:
            return

        try:
            source_pages = parse_pages(pages_text, source_total_pages)
            if not source_pages:
                show_error(self, "沒有選擇有效的頁面")
                return
        except ValueError as e:
            show_error(self, f"頁碼格式錯誤: {e}")
            return

        bounded = max(1, min(int(position), self.total_pages + 1))
        self.sig_insert_pages_from_file.emit(source_file, source_pages, bounded)

    def _clipboard_png_bytes(self) -> bytes | None:
        clipboard = QApplication.clipboard()
        try:
            image = clipboard.image()
        except Exception:
            image = None
        if image is None or getattr(image, "isNull", lambda: True)():
            return None
        buf = QBuffer()
        buf.open(QBuffer.WriteOnly)
        ok = image.save(buf, "PNG")
        if not ok:
            return None
        return bytes(buf.data())

    def _default_image_insert_rect_for_page(self, page_idx: int, center: fitz.Point | None = None) -> fitz.Rect:
        page_rect = fitz.Rect(0.0, 0.0, 595.0, 842.0)
        try:
            model = getattr(getattr(self, "controller", None), "model", None)
            if model is not None and getattr(model, "doc", None):
                page_rect = fitz.Rect(model.doc[page_idx].rect)
        except Exception:
            pass
        width = min(220.0, max(120.0, page_rect.width * 0.28))
        height = width * 0.75
        cx = float(center.x) if center is not None else float((page_rect.x0 + page_rect.x1) / 2.0)
        cy = float(center.y) if center is not None else float((page_rect.y0 + page_rect.y1) / 2.0)
        x0 = cx - (width / 2.0)
        y0 = cy - (height / 2.0)
        x0 = max(page_rect.x0, min(x0, page_rect.x1 - width))
        y0 = max(page_rect.y0, min(y0, page_rect.y1 - height))
        return fitz.Rect(x0, y0, x0 + width, y0 + height)

    def _resolve_default_image_insert_target(self, pos: QPoint) -> tuple[int, fitz.Rect] | None:
        graphics_view = getattr(self, "graphics_view", None)
        if graphics_view is None:
            return None
        try:
            scene_pos = graphics_view.mapToScene(pos)
            page_idx, doc_point = self._scene_pos_to_page_and_doc_point(scene_pos)
            page_idx = max(0, int(page_idx))
            return page_idx + 1, self._default_image_insert_rect_for_page(page_idx, doc_point)
        except Exception:
            page_idx = max(0, int(getattr(self, "current_page", 0)))
            return page_idx + 1, self._default_image_insert_rect_for_page(page_idx)

    def _insert_image_object_from_file_at_current_page(self) -> None:
        page_idx = max(0, int(getattr(self, "current_page", 0)))
        page_num = page_idx + 1
        self._insert_image_object_from_file(
            page_num=page_num,
            visual_rect=self._default_image_insert_rect_for_page(page_idx),
        )

    def _insert_image_object_from_clipboard_at_current_page(self) -> None:
        page_idx = max(0, int(getattr(self, "current_page", 0)))
        page_num = page_idx + 1
        self._insert_image_object_from_clipboard(
            page_num=page_num,
            visual_rect=self._default_image_insert_rect_for_page(page_idx),
        )

    def _insert_image_object_from_file(self, *, page_num: int, visual_rect: fitz.Rect) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "選擇圖片", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not filename:
            return
        try:
            image_bytes = Path(filename).read_bytes()
        except Exception as exc:
            show_error(self, f"無法讀取圖片: {exc}")
            return
        self.sig_add_image_object.emit(
            InsertImageObjectRequest(
                page_num=int(page_num),
                visual_rect=fitz.Rect(visual_rect),
                image_bytes=image_bytes,
                rotation=0,
            )
        )

    def _insert_image_object_from_clipboard(self, *, page_num: int, visual_rect: fitz.Rect) -> None:
        image_bytes = self._clipboard_png_bytes()
        if not image_bytes:
            show_error(self, "剪貼簿沒有可用的圖片")
            return
        self.sig_add_image_object.emit(
            InsertImageObjectRequest(
                page_num=int(page_num),
                visual_rect=fitz.Rect(visual_rect),
                image_bytes=image_bytes,
                rotation=0,
            )
        )

    def _apply_scale(self):
        transform = QTransform().scale(self.scale, self.scale)
        self.graphics_view.setTransform(transform)
        self._update_page_counter()
        self._update_status_bar()

    def _resize_event(self, event):
        super().resizeEvent(event)
        self._update_fullscreen_exit_button_geometry()
        self._update_thumbnail_layout_metrics()
        if not self.scene.sceneRect().isValid():
            if self._fullscreen_active and self.controller and hasattr(self.controller, "handle_fullscreen_view_resized"):
                self.controller.handle_fullscreen_view_resized()
            return
        if self._fullscreen_active and self.controller and hasattr(self.controller, "handle_fullscreen_view_resized"):
            self.controller.handle_fullscreen_view_resized()
            return
        if self.continuous_pages and self.page_items:
            # 連續模式：不 fit 整個場景，保留縮放與捲動位置
            self.sig_viewport_changed.emit()
            return
        self.graphics_view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        if self.scene.items():
            self.graphics_view.centerOn(self.scene.itemsBoundingRect().center())

    def mouseMoveEvent(self, event):
        if self._fullscreen_active:
            self._update_fullscreen_exit_hover(event.position().toPoint())
        super().mouseMoveEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """重寫closeEvent以檢查未儲存的變更"""
        if self.controller and hasattr(self.controller, "handle_app_close"):
            self.controller.handle_app_close(event)
            return
        event.accept()
