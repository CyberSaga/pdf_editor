from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPoint, QMimeData, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
import fitz
import main as main_module
from view.pdf_view import PDFView


def _send_drop(widget, paths: list[Path]) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    pos = widget.rect().center()
    drag_enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, drag_enter)
    drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, drop)


def _make_pdf(path: Path, page_count: int = 8) -> Path:
    doc = fitz.open()
    try:
        for index in range(page_count):
            page = doc.new_page(width=595, height=842)
            page.insert_text(
                (72, 100),
                f"Page {index + 1} / {page_count}",
                fontsize=12,
                fontname="helv",
            )
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _cleanup_startup(startup: dict) -> None:
    startup["view"].close()
    model = startup.get("model")
    if model is not None:
        model.close()
    startup["app"].quit()


def test_empty_launch_keeps_backend_detached_until_document_request() -> None:
    startup = main_module.run(argv=[], start_event_loop=False)

    try:
        assert startup["view"].controller is None
        assert startup["controller"] is None
        assert startup["model"] is None

        for _ in range(5):
            startup["app"].processEvents()

        assert startup["view"].controller is None
        assert startup["controller"] is None
        assert startup["model"] is None
    finally:
        _cleanup_startup(startup)


def test_cli_open_path_keeps_controller_attached_before_opening_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[bool, bool]] = []

    from controller.pdf_controller import PDFController

    def fake_open_pdf(self, path: str) -> None:
        observed.append((self.is_active, self.view.controller is self))

    monkeypatch.setattr(PDFController, "open_pdf", fake_open_pdf)

    startup = main_module.run(argv=["dummy.pdf"], start_event_loop=False)
    try:
        assert observed == [(True, True)]
        assert startup["view"].controller is startup["controller"]
        assert startup["controller"].is_active
    finally:
        _cleanup_startup(startup)


def test_pdf_view_emits_shell_ready_before_lazy_panel_hydration() -> None:
    startup = main_module.run(argv=[], start_event_loop=False)
    app = startup["app"]
    startup["view"].close()
    if startup["model"] is not None:
        startup["model"].close()

    view = PDFView(defer_heavy_panels=True)
    observed: list[tuple[int, int, bool]] = []
    try:
        assert view.left_sidebar.count() == 0
        assert view.right_stacked_widget.count() == 1
        assert not hasattr(view, "text_target_mode_combo")

        view.shell_ready.connect(
            lambda: observed.append(
                (
                    view.left_sidebar.count(),
                    view.right_stacked_widget.count(),
                    hasattr(view, "text_target_mode_combo"),
                )
            )
        )

        view.show()
        for _ in range(5):
            app.processEvents()

        assert observed == [(0, 1, False)]
        assert view.left_sidebar.count() == 0
        assert view.right_stacked_widget.count() == 1
        assert not hasattr(view, "text_target_mode_combo")
    finally:
        view.close()
        app.quit()


def test_empty_launch_keeps_heavy_panels_lazy_until_pdf_open(
    tmp_path: Path,
) -> None:
    startup = main_module.run(argv=[], start_event_loop=False)
    pdf_path = _make_pdf(tmp_path / "lazy-hydration.pdf", page_count=3)

    try:
        for _ in range(5):
            startup["app"].processEvents()

        assert startup["view"].controller is None
        assert startup["controller"] is None
        assert startup["view"].left_sidebar.count() == 0
        assert startup["view"].right_stacked_widget.count() == 1
        assert not hasattr(startup["view"], "text_target_mode_combo")

        startup["view"]._queue_or_open_paths([str(pdf_path)])
        for _ in range(5):
            startup["app"].processEvents()

        assert startup["view"].controller is startup["controller"]
        assert startup["controller"] is not None
        assert startup["view"].left_sidebar.count() == 4
        assert startup["view"].right_stacked_widget.count() == 4
        assert startup["view"].text_target_mode_combo.currentData() == "paragraph"
    finally:
        _cleanup_startup(startup)


def test_lazy_shell_hydrates_panels_when_user_opens_search_tab() -> None:
    startup = main_module.run(argv=[], start_event_loop=False)
    try:
        for _ in range(5):
            startup["app"].processEvents()

        view = startup["view"]
        assert startup["controller"] is None
        assert view.left_sidebar.count() == 0
        assert not hasattr(view, "search_input")

        view._show_search_tab()

        assert view.left_sidebar.count() == 4
        assert view.left_sidebar.currentIndex() == 1
        assert hasattr(view, "search_input")
    finally:
        _cleanup_startup(startup)


def test_empty_launch_buffers_dropped_pdf_paths_until_controller_attaches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[str] = []

    from controller.pdf_controller import PDFController

    def fake_open_pdf(self, path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(PDFController, "open_pdf", fake_open_pdf)

    startup = main_module.run(argv=[], start_event_loop=False)
    path = tmp_path / "dropped.pdf"
    path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    try:
        assert startup["view"].controller is None
        assert startup["controller"] is None
        _send_drop(startup["view"], [path])

        for _ in range(5):
            startup["app"].processEvents()

        assert startup["view"].controller is startup["controller"]
        assert startup["controller"].is_active
        assert opened == [str(path)]
    finally:
        _cleanup_startup(startup)


def test_cli_open_builds_placeholder_geometry_before_background_rasterization(
    tmp_path: Path,
) -> None:
    pdf_path = _make_pdf(tmp_path / "placeholder-scene.pdf", page_count=12)

    startup = main_module.run(argv=[str(pdf_path)], start_event_loop=False)
    try:
        view = startup["view"]
        assert view.total_pages == 12
        assert len(view.page_items) == 12
        assert len(view.page_y_positions) == 12
        assert len(view.page_heights) == 12
        assert view.graphics_view.sceneRect().height() > 0
    finally:
        _cleanup_startup(startup)


def test_cli_open_defers_annotation_and_watermark_sidebar_scans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf_path = _make_pdf(tmp_path / "deferred-sidebars.pdf", page_count=4)
    observed: list[str] = []

    from controller.pdf_controller import PDFController

    original_annotations = PDFController.load_annotations
    original_watermarks = PDFController.load_watermarks

    def track_annotations(self) -> None:
        observed.append("annotations")
        return original_annotations(self)

    def track_watermarks(self) -> None:
        observed.append("watermarks")
        return original_watermarks(self)

    monkeypatch.setattr(PDFController, "load_annotations", track_annotations)
    monkeypatch.setattr(PDFController, "load_watermarks", track_watermarks)

    startup = main_module.run(argv=[str(pdf_path)], start_event_loop=False)
    try:
        assert observed == []
        startup["app"].processEvents()
        assert observed
    finally:
        _cleanup_startup(startup)


def test_change_scale_does_not_rerender_every_page_in_continuous_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf_path = _make_pdf(tmp_path / "zoom-window.pdf", page_count=10)
    startup = main_module.run(argv=[str(pdf_path)], start_event_loop=False)
    controller = startup["controller"]
    model = startup["model"]
    app = startup["app"]

    try:
        app.processEvents()

        calls: list[tuple[int, float]] = []
        original = model.get_page_pixmap

        def tracked_get_page_pixmap(page_num: int, scale: float = 1.0):
            calls.append((page_num, scale))
            return original(page_num, scale)

        monkeypatch.setattr(model, "get_page_pixmap", tracked_get_page_pixmap)

        controller.change_scale(0, 1.25)

        assert len(calls) < len(model.doc)
    finally:
        _cleanup_startup(startup)
