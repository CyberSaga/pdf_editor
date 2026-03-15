from __future__ import annotations

import io
import os
import sys
import time
import shutil
from pathlib import Path

import fitz
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LARGE_PDF_NAMES = (
    "TIA-942-B-2017 Rev Full.pdf",
    "2024_ASHRAE_content.pdf",
)


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _make_pdf_with_image(path: Path) -> Path:
    image = Image.new("RGB", (24, 24), color=(220, 20, 60))
    buf = io.BytesIO()
    image.save(buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "audit sample", fontsize=12, fontname="helv")
    page.insert_image(fitz.Rect(72, 100, 160, 188), stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


def _large_pdf_path(name: str) -> Path:
    path = REPO_ROOT / "test_files" / name
    if not path.exists():
        pytest.skip(f"missing large test PDF: {path}")
    return path


def _pump_events(ms: int = 100) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _wait_until(predicate, timeout_ms: int = 1000) -> bool:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def mvc(monkeypatch, qapp):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)

    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    yield model, view, controller
    model.close()
    view.close()
    _pump_events(50)


def test_optimize_dialog_defaults_to_balanced_and_switches_to_custom(qapp) -> None:
    from view.pdf_view import OptimizePdfDialog

    dialog = OptimizePdfDialog()

    assert dialog.preset_combo.currentText() == "平衡"
    assert dialog.image_target_dpi_suffix.text() == "dpi"
    assert dialog.image_threshold_dpi_suffix.text() == "dpi"
    assert dialog.image_quality_slider.value() == 60

    dialog.metadata_checkbox.setChecked(not dialog.metadata_checkbox.isChecked())

    assert dialog.preset_combo.currentText() == "自訂"


def test_file_tab_exposes_optimize_copy_action(mvc) -> None:
    _model, view, _controller = mvc

    action = getattr(view, "_action_optimize_copy", None)

    assert action is not None
    assert action.text() == "另存為最佳化的副本"


def test_save_optimized_copy_uses_working_doc_and_preserves_live_doc(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf_with_image(tmp_path / "source.pdf")
    output = tmp_path / "optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        before_bytes = model.doc.tobytes(no_new_id=1)

        result = model.save_optimized_copy(str(output), PdfOptimizeOptions())

        after_bytes = model.doc.tobytes(no_new_id=1)

        assert output.exists() is True
        assert result.output_path == str(output)
        assert result.optimized_bytes > 0
        assert before_bytes == after_bytes
    finally:
        model.close()


def test_save_optimized_copy_avoids_live_doc_tobytes_for_clean_session(
    tmp_path: Path, monkeypatch
) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf_with_image(tmp_path / "clean-source.pdf")
    output = tmp_path / "clean-optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        original_tobytes = fitz.Document.tobytes

        def guarded_tobytes(self, *args, **kwargs):
            if self is model.doc:
                raise AssertionError("clean file-backed optimize should not serialize the live document")
            return original_tobytes(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Document, "tobytes", guarded_tobytes)

        result = model.save_optimized_copy(str(output), PdfOptimizeOptions())

        assert output.exists() is True
        assert result.output_path == str(output)
        assert result.optimized_bytes > 0
    finally:
        model.close()


@pytest.mark.parametrize("preset_name", ["快速", "平衡", "極致壓縮"])
def test_save_optimized_copy_accepts_all_presets(tmp_path: Path, preset_name: str) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / f"{preset_name}-source.pdf")
    output = tmp_path / f"{preset_name}-optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options(preset_name))

        assert output.exists() is True
        assert result.output_path == str(output)
        assert result.optimized_bytes > 0
        assert result.applied_preset == preset_name
    finally:
        model.close()


def test_build_pdf_audit_report_groups_known_categories(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "audit.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        report = model.build_pdf_audit_report()
    finally:
        model.close()

    categories = {item.label: item for item in report.items}
    assert "圖片" in categories
    assert "字體" in categories
    assert "內容串流" in categories
    assert "其他/未分類" in categories
    assert report.total_bytes >= 1
    assert categories["圖片"].bytes_used >= 1
    assert categories["字體"].bytes_used >= 1


def test_build_pdf_audit_report_caches_active_document_results(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "audit-cache.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        calls: list[int] = []
        original_xref_size_bytes = PDFModel._xref_size_bytes

        def counting_xref_size_bytes(doc, xref: int) -> int:
            calls.append(int(xref))
            return original_xref_size_bytes(doc, xref)

        monkeypatch.setattr(PDFModel, "_xref_size_bytes", staticmethod(counting_xref_size_bytes))

        report1 = model.build_pdf_audit_report()
        first_call_count = len(calls)
        report2 = model.build_pdf_audit_report()

        assert first_call_count > 0
        assert len(calls) == first_call_count
        assert report2 == report1

        model.doc[0].insert_text((72, 220), "cache bust", fontsize=12, fontname="helv")
        model.edit_count += 1

        report3 = model.build_pdf_audit_report()

        assert len(calls) > first_call_count
        assert report3.total_bytes >= report2.total_bytes
    finally:
        model.close()


def test_pdf_audit_report_dialog_uses_table_and_stacked_bar(qapp, tmp_path: Path) -> None:
    from model.pdf_model import PDFModel
    from view.pdf_view import PdfAuditReportDialog

    source = _make_pdf_with_image(tmp_path / "audit-dialog.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        report = model.build_pdf_audit_report()
    finally:
        model.close()

    dialog = PdfAuditReportDialog(report)

    assert dialog.table.rowCount() == len(report.items)
    assert dialog.table.columnCount() == 4
    assert dialog.stacked_bar.segment_count() >= 1
    assert dialog.layout().indexOf(dialog.hover_name_label) < dialog.layout().indexOf(dialog.stacked_bar)
    tooltips = dialog.stacked_bar.segment_tooltips()
    meaningful_labels = {item.label for item in report.items if item.bytes_used > 0}
    assert tooltips
    assert all(tip in meaningful_labels for tip in tooltips)
    dialog.stacked_bar.hovered_label_changed.emit(tooltips[0])
    assert tooltips[0] in dialog.hover_name_label.text()


def test_start_optimize_pdf_copy_saves_and_opens_new_tab(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    original_sid = model.get_active_session_id()
    original_meta = model.get_session_meta(original_sid)
    original_page_count = len(model.doc)

    import view.pdf_view as pdf_view_module

    def fake_exec(self) -> int:
        return QDialog.Accepted

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", fake_exec)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    controller.start_optimize_pdf_copy()
    assert _wait_until(lambda: len(model.session_ids) == 2, timeout_ms=1500)

    assert output.exists() is True
    assert len(model.session_ids) == 2
    assert model.get_active_session_id() != original_sid

    controller._switch_to_session_id(original_sid)
    _pump_events(50)
    assert len(model.doc) == original_page_count
    assert model.get_session_meta(original_sid)["path"] == original_meta["path"]


def test_start_optimize_pdf_copy_rejects_current_path_collision(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    controller.open_pdf(str(current))
    _pump_events(120)

    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda _view, msg: errors.append(str(msg)))

    import view.pdf_view as pdf_view_module

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(current), "PDF (*.pdf)")),
    )

    controller.start_optimize_pdf_copy()
    _pump_events(50)

    assert len(model.session_ids) == 1
    assert errors
    assert any("新的輸出路徑" in msg for msg in errors)


def test_start_optimize_pdf_copy_runs_work_in_background(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(path: str, _options):
        time.sleep(0.25)
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=current.stat().st_size,
            optimized_bytes=Path(path).stat().st_size,
            bytes_saved=0,
            percent_saved=0.0,
            applied_preset="平衡",
            applied_summary=["平衡"],
        )

    monkeypatch.setattr(model, "save_optimized_copy", fake_save_optimized_copy)

    start = time.time()
    controller.start_optimize_pdf_copy()
    elapsed = time.time() - start

    assert elapsed < 0.15
    _pump_events(500)
    assert len(model.session_ids) == 2


def test_start_optimize_pdf_copy_completion_message_uses_human_units(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    messages: list[str] = []
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information",
        staticmethod(lambda _parent, _title, text: messages.append(str(text))),
    )
    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(path: str, _options):
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=8 * 1024 * 1024,
            optimized_bytes=3 * 1024 * 1024,
            bytes_saved=5 * 1024 * 1024,
            percent_saved=62.5,
            applied_preset="撟唾﹛",
            applied_summary=["撟唾﹛"],
        )

    monkeypatch.setattr(model, "save_optimized_copy", fake_save_optimized_copy)

    controller.start_optimize_pdf_copy()
    _pump_events(500)

    assert messages
    assert "MB" in messages[-1]


def test_format_size_units_covers_kb_mb_and_gb(mvc) -> None:
    _model, _view, controller = mvc

    assert controller._format_size_units(900) == "900 bytes"
    assert controller._format_size_units(1536) == "1.50 KB (1,536 bytes)"
    assert controller._format_size_units(8 * 1024 * 1024) == "8.00 MB (8,388,608 bytes)"
    assert controller._format_size_units(3 * 1024 * 1024 * 1024) == "3.00 GB (3,221,225,472 bytes)"


@pytest.mark.parametrize("source_name", LARGE_PDF_NAMES)
def test_large_file_optimize_submission_keeps_progress_dialog_responsive(
    mvc, monkeypatch, tmp_path: Path, source_name: str
) -> None:
    model, _view, controller = mvc
    current = _large_pdf_path(source_name)
    output = tmp_path / f"{current.stem}.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(path: str, _options):
        time.sleep(0.35)
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=current.stat().st_size,
            optimized_bytes=max(1, current.stat().st_size - 8 * 1024 * 1024),
            bytes_saved=min(current.stat().st_size - 1, 8 * 1024 * 1024),
            percent_saved=7.0,
            applied_preset="平衡",
            applied_summary=["平衡"],
        )

    monkeypatch.setattr(model, "save_optimized_copy", fake_save_optimized_copy)

    start = time.time()
    controller.start_optimize_pdf_copy()
    elapsed = time.time() - start

    assert elapsed < 0.15
    assert controller._optimize_progress_dialog is not None
    assert controller._optimize_progress_dialog.isVisible()
    assert getattr(controller.view, "_action_optimize_copy").isEnabled() is False
    _pump_events(120)
    assert controller._optimize_progress_dialog is not None
    assert controller._optimize_progress_dialog.isVisible()
    assert _wait_until(lambda: len(model.session_ids) == 2, timeout_ms=2000)


@pytest.mark.parametrize("source_name", LARGE_PDF_NAMES)
def test_large_file_optimized_copy_passes_integrity_validation(tmp_path: Path, source_name: str) -> None:
    from model.pdf_model import PDFModel
    from test_scripts.validate_optimized_pdf import validate_pdf_integrity

    source = _large_pdf_path(source_name)
    output = tmp_path / f"{source.stem}.optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()

    assert output.exists() is True
    assert result.optimized_bytes > 0
    integrity = validate_pdf_integrity(output)
    assert integrity["passed"] is True
    assert integrity["fitz"]["ok"] is True
    assert integrity["pikepdf"]["ok"] is True
    assert integrity["pypdf"]["ok"] is True
