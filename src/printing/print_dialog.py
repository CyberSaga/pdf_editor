"""Unified print dialog with settings + preview in one window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtGui import QPageSize
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .base_driver import PrintJobOptions, PrinterDevice
from .dispatcher import PrintDispatcher
from .errors import PrintingError
from .layout import (
    compute_target_draw_rect,
    resolve_orientation,
    resolve_paper_size_points,
)
from .pdf_renderer import PDFRenderer


@dataclass(slots=True)
class UnifiedPrintDialogResult:
    options: PrintJobOptions
    page_indices: List[int]


class UnifiedPrintDialog(QDialog):
    def __init__(
        self,
        parent,
        dispatcher: PrintDispatcher,
        printers: List[PrinterDevice],
        pdf_path: str,
        total_pages: int,
        current_page: int,
        job_name: str,
    ) -> None:
        super().__init__(parent)
        self.dispatcher = dispatcher
        self.printers = printers
        self.pdf_path = pdf_path
        self.total_pages = max(0, int(total_pages))
        self.current_page = max(1, min(int(current_page), max(1, total_pages)))
        self.job_name = job_name
        self.renderer = PDFRenderer()

        self._printer_map: Dict[str, PrinterDevice] = {p.name: p for p in printers}
        self._page_indices: List[int] = []
        self._preview_cache: Dict[tuple[int, int], QImage] = {}
        self._result: Optional[UnifiedPrintDialogResult] = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.setWindowTitle("列印")
        self.setMinimumSize(1180, 760)
        self._build_ui()
        self._load_printers()
        self._wire_signals()
        self._schedule_preview_refresh()

    def result_data(self) -> Optional[UnifiedPrintDialogResult]:
        return self._result

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if watched is self.preview_label:
            if event.type() == QEvent.Resize:
                self._render_preview()
            elif event.type() == QEvent.Wheel:
                delta = event.angleDelta().y()
                if delta > 0:
                    self._go_prev_page()
                elif delta < 0:
                    self._go_next_page()
                return True
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(10)
        splitter.addWidget(left)

        printer_box = QGroupBox("印表機")
        printer_form = QFormLayout(printer_box)
        self.printer_combo = QComboBox()
        self.printer_status_label = QLabel("-")
        self.printer_capability_label = QLabel("")
        self.printer_capability_label.setWordWrap(True)
        printer_form.addRow("名稱", self.printer_combo)
        printer_form.addRow("狀態", self.printer_status_label)
        printer_form.addRow("能力", self.printer_capability_label)
        left_layout.addWidget(printer_box)

        setting_box = QGroupBox("列印設定")
        setting_form = QFormLayout(setting_box)
        self.paper_combo = QComboBox()
        self.paper_combo.addItem("Auto", "auto")
        self.paper_combo.addItem("A4", "a4")
        self.paper_combo.addItem("Letter", "letter")
        self.paper_combo.addItem("Legal", "legal")

        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("自動", "auto")
        self.orientation_combo.addItem("直向", "portrait")
        self.orientation_combo.addItem("橫向", "landscape")

        self.duplex_combo = QComboBox()
        self.duplex_combo.addItem("單面", "none")
        self.duplex_combo.addItem("長邊雙面", "long")
        self.duplex_combo.addItem("短邊雙面", "short")

        self.color_combo = QComboBox()
        self.color_combo.addItem("彩色", "color")
        self.color_combo.addItem("黑白", "grayscale")

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setValue(300)

        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 99)
        self.copies_spin.setValue(1)
        self.collate_cb = QCheckBox("逐份列印")
        self.collate_cb.setChecked(True)

        setting_form.addRow("紙張", self.paper_combo)
        setting_form.addRow("方向", self.orientation_combo)
        setting_form.addRow("雙面", self.duplex_combo)
        setting_form.addRow("色彩", self.color_combo)
        setting_form.addRow("PPI", self.dpi_spin)
        setting_form.addRow("份數", self.copies_spin)
        setting_form.addRow("", self.collate_cb)
        left_layout.addWidget(setting_box)

        page_box = QGroupBox("頁面範圍")
        page_form = QFormLayout(page_box)
        self.range_mode_combo = QComboBox()
        self.range_mode_combo.addItem("全部", "all")
        self.range_mode_combo.addItem("目前頁", "current")
        self.range_mode_combo.addItem("自訂", "custom")
        self.custom_range_edit = QLineEdit()
        self.custom_range_edit.setPlaceholderText("例如 1,3,5-8")
        self.custom_range_edit.setEnabled(False)

        self.page_subset_combo = QComboBox()
        self.page_subset_combo.addItem("全部", "all")
        self.page_subset_combo.addItem("奇數頁", "odd")
        self.page_subset_combo.addItem("偶數頁", "even")
        self.reverse_cb = QCheckBox("反向列印")

        page_form.addRow("範圍", self.range_mode_combo)
        page_form.addRow("頁碼", self.custom_range_edit)
        page_form.addRow("子集合", self.page_subset_combo)
        page_form.addRow("", self.reverse_cb)
        left_layout.addWidget(page_box)

        scale_box = QGroupBox("縮放")
        scale_form = QFormLayout(scale_box)
        self.scale_mode_combo = QComboBox()
        self.scale_mode_combo.addItem("符合紙張", "fit")
        self.scale_mode_combo.addItem("實際大小", "actual")
        self.scale_mode_combo.addItem("自訂百分比", "custom")
        self.scale_percent_spin = QSpinBox()
        self.scale_percent_spin.setRange(25, 400)
        self.scale_percent_spin.setValue(100)
        self.scale_percent_spin.setSuffix("%")
        self.scale_percent_spin.setEnabled(False)

        scale_form.addRow("模式", self.scale_mode_combo)
        scale_form.addRow("百分比", self.scale_percent_spin)
        left_layout.addWidget(scale_box)
        left_layout.addStretch(1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("列印")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.button(QDialogButtonBox.Ok).setStyleSheet(
            "QPushButton { background: #ffffff; color: #111827; border: 1px solid #9ca3af; padding: 6px 12px; }"
        )
        btn_box.button(QDialogButtonBox.Cancel).setStyleSheet(
            "QPushButton { background: #d1d5db; color: #111827; border: 1px solid #9ca3af; padding: 6px 12px; }"
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        left_layout.addWidget(btn_box)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)
        splitter.addWidget(right)

        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("上一頁")
        self.next_btn = QPushButton("下一頁")
        self.page_info_label = QLabel("-")
        self.page_info_label.setAlignment(Qt.AlignCenter)
        nav_row.addWidget(self.prev_btn)
        nav_row.addWidget(self.next_btn)
        nav_row.addWidget(self.page_info_label, 1)
        right_layout.addLayout(nav_row)

        body_row = QHBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(540, 660)
        self.preview_label.setStyleSheet(
            "QLabel { background: #d1d5db; border: 1px solid #9ca3af; }"
        )
        self.preview_label.installEventFilter(self)

        self.page_list = QListWidget()
        self.page_list.setMinimumWidth(110)
        self.page_list.setMaximumWidth(140)
        body_row.addWidget(self.preview_label, 1)
        body_row.addWidget(self.page_list)
        right_layout.addLayout(body_row, 1)

        self.preview_message_label = QLabel("")
        self.preview_message_label.setWordWrap(True)
        self.preview_message_label.setStyleSheet("color: #991b1b;")
        right_layout.addWidget(self.preview_message_label)

        splitter.setSizes([430, 740])

    def _load_printers(self) -> None:
        default_name = self.dispatcher.get_default_printer()
        default_index = 0
        for idx, printer in enumerate(self.printers):
            self.printer_combo.addItem(printer.name, printer.name)
            if printer.name == default_name or printer.is_default:
                default_index = idx
        if self.printer_combo.count() > 0:
            self.printer_combo.setCurrentIndex(default_index)
            self._on_printer_changed()

    def _wire_signals(self) -> None:
        self.printer_combo.currentIndexChanged.connect(self._on_printer_changed)
        self.range_mode_combo.currentIndexChanged.connect(self._on_range_mode_changed)
        self.scale_mode_combo.currentIndexChanged.connect(self._on_scale_mode_changed)
        self.page_list.currentRowChanged.connect(self._on_preview_row_changed)
        self.prev_btn.clicked.connect(self._go_prev_page)
        self.next_btn.clicked.connect(self._go_next_page)

        widgets = [
            self.paper_combo,
            self.orientation_combo,
            self.duplex_combo,
            self.color_combo,
            self.dpi_spin,
            self.copies_spin,
            self.collate_cb,
            self.range_mode_combo,
            self.custom_range_edit,
            self.page_subset_combo,
            self.reverse_cb,
            self.scale_mode_combo,
            self.scale_percent_spin,
        ]
        for widget in widgets:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._schedule_preview_refresh)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._schedule_preview_refresh)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._schedule_preview_refresh)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._schedule_preview_refresh)

    def _on_printer_changed(self) -> None:
        name = self.printer_combo.currentData()
        if not name:
            self.printer_status_label.setText("-")
            self.printer_capability_label.setText("")
            return
        printer = self._printer_map.get(name)
        self.printer_status_label.setText(printer.status if printer else "unknown")
        self._sync_printer_capabilities(name)
        self._schedule_preview_refresh()

    def _sync_printer_capabilities(self, printer_name: str) -> None:
        info = None
        for item in QPrinterInfo.availablePrinters():
            if item.printerName() == printer_name:
                info = item
                break
        if info is None:
            self.printer_capability_label.setText("無法取得詳細能力，使用通用設定。")
            return

        resolutions = sorted(set(int(r) for r in info.supportedResolutions() if int(r) >= 72))

        supported = ["a4", "letter", "legal"]
        page_sizes = {size.id() for size in info.supportedPageSizes()}
        available = ["auto"]
        # Filter to known paper names if printer reports them.
        if any(size_id == QPageSize.A4 for size_id in page_sizes):
            available.append("a4")
        if any(size_id == QPageSize.Letter for size_id in page_sizes):
            available.append("letter")
        if any(size_id == QPageSize.Legal for size_id in page_sizes):
            available.append("legal")
        if len(available) == 1:
            available.extend(supported)

        selected = self.paper_combo.currentData()
        self.paper_combo.blockSignals(True)
        self.paper_combo.clear()
        self.paper_combo.addItem("Auto", "auto")
        if "a4" in available:
            self.paper_combo.addItem("A4", "a4")
        if "letter" in available:
            self.paper_combo.addItem("Letter", "letter")
        if "legal" in available:
            self.paper_combo.addItem("Legal", "legal")
        idx = self.paper_combo.findData(selected)
        if idx < 0:
            idx = self.paper_combo.findData("auto")
        self.paper_combo.setCurrentIndex(max(0, idx))
        self.paper_combo.blockSignals(False)

        dpi_hint = ", ".join(str(r) for r in resolutions[:6]) if resolutions else "unknown"
        self.printer_capability_label.setText(f"支援解析度: {dpi_hint}")

    def _on_range_mode_changed(self) -> None:
        custom_enabled = self.range_mode_combo.currentData() == "custom"
        self.custom_range_edit.setEnabled(custom_enabled)
        self._schedule_preview_refresh()

    def _on_scale_mode_changed(self) -> None:
        self.scale_percent_spin.setEnabled(self.scale_mode_combo.currentData() == "custom")
        self._schedule_preview_refresh()

    def _go_prev_page(self) -> None:
        if self.page_list.count() <= 0:
            return
        next_row = max(0, self.page_list.currentRow() - 1)
        self.page_list.setCurrentRow(next_row)

    def _go_next_page(self) -> None:
        if self.page_list.count() <= 0:
            return
        next_row = min(self.page_list.count() - 1, self.page_list.currentRow() + 1)
        self.page_list.setCurrentRow(next_row)

    def _on_preview_row_changed(self, row: int) -> None:
        if row < 0:
            return
        self._render_preview()

    def _schedule_preview_refresh(self) -> None:
        self._preview_timer.start()

    def _build_options(self) -> PrintJobOptions:
        range_mode = self.range_mode_combo.currentData()
        if range_mode == "all":
            page_ranges = None
        elif range_mode == "current":
            page_ranges = str(self.current_page)
        else:
            page_ranges = self.custom_range_edit.text().strip()
            if not page_ranges:
                raise ValueError("自訂頁碼不可為空。")

        scale_mode = self.scale_mode_combo.currentData()
        options = PrintJobOptions(
            printer_name=self.printer_combo.currentData(),
            page_ranges=page_ranges,
            copies=self.copies_spin.value(),
            collate=self.collate_cb.isChecked(),
            dpi=self.dpi_spin.value(),
            fit_to_page=(scale_mode == "fit"),
            color_mode=self.color_combo.currentData(),
            duplex=self.duplex_combo.currentData(),
            job_name=self.job_name,
            transport="raster",
            paper_size=self.paper_combo.currentData(),
            orientation=self.orientation_combo.currentData(),
            scale_mode=scale_mode,
            scale_percent=self.scale_percent_spin.value(),
            page_subset=self.page_subset_combo.currentData(),
            reverse_order=self.reverse_cb.isChecked(),
        )
        return options.normalized()

    def _refresh_preview(self) -> None:
        try:
            options = self._build_options()
            page_indices = self.dispatcher.resolve_page_indices_for_count(
                self.total_pages, options
            )
        except ValueError as exc:
            self._show_preview_error(str(exc))
            return
        except PrintingError as exc:
            self._show_preview_error(str(exc))
            return

        previous_page = None
        row = self.page_list.currentRow()
        if 0 <= row < self.page_list.count():
            previous_page = self.page_list.item(row).data(Qt.UserRole)

        self._page_indices = page_indices
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for idx in page_indices:
            item = QListWidgetItem(f"{idx + 1}")
            item.setData(Qt.UserRole, idx)
            self.page_list.addItem(item)
        self.page_list.blockSignals(False)

        select_row = 0
        if previous_page in page_indices:
            select_row = page_indices.index(previous_page)
        self.page_list.setCurrentRow(select_row)
        self.preview_message_label.setText("")
        self._render_preview()

    def _show_preview_error(self, message: str) -> None:
        self._page_indices = []
        self.page_list.blockSignals(True)
        self.page_list.clear()
        self.page_list.blockSignals(False)
        self.page_info_label.setText("預覽不可用")
        self.preview_label.setPixmap(QPixmap())
        self.preview_message_label.setText(message)

    def _render_preview(self) -> None:
        if not self._page_indices:
            return
        row = self.page_list.currentRow()
        if row < 0:
            row = 0
            self.page_list.setCurrentRow(0)
        if row >= len(self._page_indices):
            row = len(self._page_indices) - 1

        page_index = self._page_indices[row]
        dpi = self.dpi_spin.value()
        cache_key = (page_index, dpi)
        image = self._preview_cache.get(cache_key)
        if image is None:
            pages = self.renderer.iter_page_images(self.pdf_path, [page_index], dpi)
            try:
                rendered = next(pages)
            except StopIteration:
                self._show_preview_error("無法渲染預覽頁面。")
                return
            image = rendered.image
            self._preview_cache[cache_key] = image
            while len(self._preview_cache) > 24:
                self._preview_cache.pop(next(iter(self._preview_cache)))

        options = self._build_options()
        pixmap = self._compose_preview_pixmap(image, options)
        self.preview_label.setPixmap(pixmap)
        self.page_info_label.setText(
            f"第 {page_index + 1} 頁 / 共 {self.total_pages} 頁（本次列印 {len(self._page_indices)} 頁）"
        )
        self.prev_btn.setEnabled(row > 0)
        self.next_btn.setEnabled(row < len(self._page_indices) - 1)

    def _compose_preview_pixmap(self, image: QImage, options: PrintJobOptions) -> QPixmap:
        width = max(420, self.preview_label.width() - 16)
        height = max(580, self.preview_label.height() - 16)
        canvas = QImage(width, height, QImage.Format_ARGB32)
        canvas.fill(QColor(170, 170, 170))

        paper_w, paper_h = resolve_paper_size_points(
            options.paper_size,
            float(image.width()),
            float(image.height()),
        )
        orientation = resolve_orientation(options.orientation, paper_w, paper_h)
        if orientation == "landscape" and paper_h > paper_w:
            paper_w, paper_h = paper_h, paper_w
        if orientation == "portrait" and paper_w > paper_h:
            paper_w, paper_h = paper_h, paper_w

        paper_x, paper_y, paper_draw_w, paper_draw_h = compute_target_draw_rect(
            target_width=width - 20,
            target_height=height - 20,
            source_width=paper_w,
            source_height=paper_h,
            scale_mode="fit",
            scale_percent=100,
            fit_to_page=True,
        )
        paper_x += 10
        paper_y += 10

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(paper_x, paper_y, paper_draw_w, paper_draw_h, QColor(255, 255, 255))
        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.drawRect(paper_x, paper_y, paper_draw_w, paper_draw_h)

        draw_x, draw_y, draw_w, draw_h = compute_target_draw_rect(
            target_width=paper_draw_w,
            target_height=paper_draw_h,
            source_width=image.width(),
            source_height=image.height(),
            scale_mode=options.scale_mode,
            scale_percent=options.scale_percent,
            fit_to_page=options.fit_to_page,
        )
        painter.drawImage(
            QRectF(paper_x + draw_x, paper_y + draw_y, draw_w, draw_h),
            image,
        )
        painter.end()

        return QPixmap.fromImage(canvas)

    def accept(self) -> None:  # noqa: D401
        try:
            options = self._build_options()
            page_indices = self.dispatcher.resolve_page_indices_for_count(
                self.total_pages, options
            )
        except (ValueError, PrintingError) as exc:
            QMessageBox.warning(self, "列印設定錯誤", str(exc))
            return

        self._result = UnifiedPrintDialogResult(options=options, page_indices=page_indices)
        super().accept()
