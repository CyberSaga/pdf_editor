from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402


def _process_events(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _first_non_empty_span(doc: fitz.Document, page_idx: int = 0) -> dict | None:
    for block in doc[page_idx].get_text("rawdict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if (span.get("text") or "").strip():
                    return span
    return None


def _editor_viewport_rect(view: PDFView):
    proxy = view.text_editor.graphicsProxyWidget()
    scene_rect = proxy.sceneBoundingRect()
    corners = [
        view.graphics_view.mapFromScene(QPointF(scene_rect.left(), scene_rect.top())),
        view.graphics_view.mapFromScene(QPointF(scene_rect.right(), scene_rect.top())),
        view.graphics_view.mapFromScene(QPointF(scene_rect.right(), scene_rect.bottom())),
        view.graphics_view.mapFromScene(QPointF(scene_rect.left(), scene_rect.bottom())),
    ]
    xs = [point.x() for point in corners]
    ys = [point.y() for point in corners]
    x0, y0 = min(xs), min(ys)
    x1, y1 = max(xs), max(ys)
    from PySide6.QtCore import QRect

    return QRect(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))


def _crop(image: QImage, rect) -> QImage:
    x = max(0, rect.x())
    y = max(0, rect.y())
    width = min(image.width() - x, rect.width())
    height = min(image.height() - y, rect.height())
    if width <= 0 or height <= 0:
        blank = QImage(1, 1, QImage.Format_RGBA8888)
        blank.fill(0x00FFFFFF)
        return blank
    return image.copy(x, y, width, height)


def _changed_pixel_pct(before: QImage, after: QImage) -> float:
    width = min(before.width(), after.width())
    height = min(before.height(), after.height())
    if width <= 0 or height <= 0:
        return 1.0
    changed = 0
    for y in range(height):
        for x in range(width):
            b = before.pixelColor(x, y)
            a = after.pixelColor(x, y)
            delta = (
                abs(b.red() - a.red())
                + abs(b.green() - a.green())
                + abs(b.blue() - a.blue())
                + abs(b.alpha() - a.alpha())
            )
            if delta > 20:
                changed += 1
    return changed / (width * height)


def _diff_image(before: QImage, after: QImage) -> QImage:
    width = min(before.width(), after.width())
    height = min(before.height(), after.height())
    diff = QImage(max(1, width), max(1, height), QImage.Format_ARGB32)
    diff.fill(0xFFFFFFFF)
    for y in range(height):
        for x in range(width):
            b = before.pixelColor(x, y)
            a = after.pixelColor(x, y)
            delta = (
                abs(b.red() - a.red())
                + abs(b.green() - a.green())
                + abs(b.blue() - a.blue())
                + abs(b.alpha() - a.alpha())
            )
            if delta > 20:
                diff.setPixelColor(x, y, QColor(255, 0, 0, 255))
    return diff


def _capture_editor_crop(view: PDFView) -> tuple[QImage, object]:
    full = view.graphics_view.viewport().grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    editor_rect = _editor_viewport_rect(view)
    return _crop(full, editor_rect), editor_rect


def run(pdf_path: Path, output_dir: Path, wait_seconds: float) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    print(f"[visual] opening {pdf_path.name}", flush=True)

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    view.show()
    _process_events(app, 0.5)

    controller.open_pdf(str(pdf_path))
    _process_events(app, wait_seconds)
    if not model.doc:
        print("[visual] FAIL: model did not open document", flush=True)
        return 2

    print(f"[visual] opened pages={model.doc.page_count}", flush=True)
    view.set_mode("edit_text")
    _process_events(app, 0.5)
    model.ensure_page_index_built(1)
    span = _first_non_empty_span(model.doc, 0)
    if span is None:
        print("[visual] SKIP: no non-empty span on page 1", flush=True)
        return 0

    bbox = fitz.Rect(span["bbox"])
    render_scale = view._render_scale if view._render_scale > 0 else 1.0
    page_y = view.page_y_positions[0] if (view.continuous_pages and view.page_y_positions) else 0.0
    scene_x = bbox.x0 * render_scale + (bbox.width * render_scale) / 2.0
    scene_y = page_y + bbox.y0 * render_scale + (bbox.height * render_scale) / 2.0
    viewport_point = view.graphics_view.mapFromScene(QPointF(scene_x, scene_y))
    click_pos = QPoint(int(viewport_point.x()), int(viewport_point.y()))

    before_full = view.graphics_view.viewport().grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    print(f"[visual] clicking span at {click_pos.x()},{click_pos.y()}", flush=True)
    QTest.mousePress(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    _process_events(app, 0.1)
    QTest.mouseRelease(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    _process_events(app, 1.0)

    if view.text_editor is None:
        print("[visual] FAIL: editor did not open", flush=True)
        return 3

    after_crop, editor_rect = _capture_editor_crop(view)
    before_crop = _crop(before_full, editor_rect)
    before_crop.save(str(output_dir / "before_editor.png"))
    after_crop.save(str(output_dir / "after_editor.png"))
    _diff_image(before_crop, after_crop).save(str(output_dir / "diff_editor.png"))

    editor = view.text_editor.widget()
    original_text = editor.toPlainText()
    editor.setPlainText("")
    _process_events(app, 0.4)
    during_empty_crop, during_empty_rect = _capture_editor_crop(view)
    during_empty_crop.save(str(output_dir / "during_empty_editor.png"))
    _diff_image(after_crop, during_empty_crop).save(str(output_dir / "diff_open_to_empty.png"))

    editor.setPlainText("EDITING")
    _process_events(app, 1.0)
    during_crop, during_rect = _capture_editor_crop(view)
    during_crop.save(str(output_dir / "during_editor.png"))
    _diff_image(after_crop, during_crop).save(str(output_dir / "diff_open_to_during.png"))
    editor.setPlainText(original_text)
    _process_events(app, 0.4)
    restored_crop, restored_rect = _capture_editor_crop(view)
    restored_crop.save(str(output_dir / "restored_editor.png"))
    _diff_image(after_crop, restored_crop).save(str(output_dir / "diff_open_to_restored.png"))

    metrics = {
        "pdf": pdf_path.name,
        "pages": model.doc.page_count,
        "span_text": span.get("text", ""),
        "span_bbox": list(bbox),
        "editor_rect": [editor_rect.x(), editor_rect.y(), editor_rect.width(), editor_rect.height()],
        "during_empty_rect": [
            during_empty_rect.x(),
            during_empty_rect.y(),
            during_empty_rect.width(),
            during_empty_rect.height(),
        ],
        "during_rect": [during_rect.x(), during_rect.y(), during_rect.width(), during_rect.height()],
        "restored_rect": [restored_rect.x(), restored_rect.y(), restored_rect.width(), restored_rect.height()],
        "open_changed_px_pct": _changed_pixel_pct(before_crop, after_crop),
        "during_empty_changed_px_pct_vs_open": _changed_pixel_pct(after_crop, during_empty_crop),
        "during_changed_px_pct_vs_open": _changed_pixel_pct(after_crop, during_crop),
        "restored_changed_px_pct_vs_open": _changed_pixel_pct(after_crop, restored_crop),
        "during_preview_valid": bool(getattr(editor, "_mutated_preview_is_valid", False)),
        "mask_debug": editor.property("mask_debug_metrics") or {},
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"[visual] open_changed_px_pct={metrics['open_changed_px_pct']:.6f}", flush=True)
    print(
        f"[visual] during_empty_changed_px_pct_vs_open={metrics['during_empty_changed_px_pct_vs_open']:.6f}",
        flush=True,
    )
    print(
        f"[visual] during_changed_px_pct_vs_open={metrics['during_changed_px_pct_vs_open']:.6f}",
        flush=True,
    )
    print(
        f"[visual] restored_changed_px_pct_vs_open={metrics['restored_changed_px_pct_vs_open']:.6f}",
        flush=True,
    )
    print(f"[visual] mask_debug={metrics['mask_debug']}", flush=True)

    view._finalize_text_edit()
    _process_events(app, 0.2)
    try:
        model.close_all_sessions()
    except Exception:
        pass
    view.close()
    view.deleteLater()
    _process_events(app, 0.2)
    app.quit()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=float, default=2.0)
    args = parser.parse_args()
    return run(args.pdf.resolve(), args.output_dir.resolve(), args.wait_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
