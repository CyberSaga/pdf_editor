from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication, QDialog


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _pump_events(ms: int = 100) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


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


def test_merge_session_keeps_current_entry_locked_and_appends_new_files() -> None:
    from model.merge_session import MergeSessionModel

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")

    session.add_files(
        [
            str(Path("C:/tmp/B.pdf")),
            str(Path("C:/tmp/C.pdf")),
        ]
    )

    assert [entry.display_name for entry in session.entries] == [
        "Current.pdf",
        "B.pdf",
        "C.pdf",
    ]
    assert session.entries[0].locked is True
    assert session.remove_selected([0]) == []


def test_start_merge_pdfs_seeds_dialog_with_current_document(mvc, monkeypatch, tmp_path: Path) -> None:
    _model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["alpha"])
    controller.open_pdf(str(current))
    _pump_events(100)

    observed: dict[str, list[str]] = {}
    import view.pdf_view as pdf_view_module

    def fake_exec(self) -> int:
        observed["entries"] = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        return QDialog.Rejected

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", fake_exec)

    controller.start_merge_pdfs()

    assert observed["entries"] == ["Current.pdf"]


def test_merge_ordered_sources_into_current_replaces_active_document_in_list_order(
    mvc,
    tmp_path: Path,
) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    controller.open_pdf(str(current))
    _pump_events(100)

    controller.merge_ordered_sources_into_current(
        [
            {"source_kind": "file", "path": str(extra)},
            {"source_kind": "current"},
        ]
    )

    assert len(model.doc) == 2
    first_text = model.doc[0].get_text("text")
    second_text = model.doc[1].get_text("text")
    assert "extra page" in first_text
    assert "current page" in second_text
    assert model.has_unsaved_changes() is True


def test_merge_dialog_appends_picker_results_and_deletes_only_unlocked_rows(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    dialog = MergePdfDialog(session)

    picks = iter(
        [
            ([str(Path("C:/tmp/B.pdf")), str(Path("C:/tmp/C.pdf"))], "PDF (*.pdf)"),
            ([str(Path("C:/tmp/D.pdf"))], "PDF (*.pdf)"),
        ]
    )
    monkeypatch.setattr("view.pdf_view.QFileDialog.getOpenFileNames", lambda *args, **kwargs: next(picks))

    dialog._select_files()
    dialog._select_files()

    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "B.pdf",
        "C.pdf",
        "D.pdf",
    ]

    dialog.file_list.setCurrentRow(0)
    dialog._delete_selected()
    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "B.pdf",
        "C.pdf",
        "D.pdf",
    ]

    dialog.file_list.setCurrentRow(2)
    dialog._delete_selected()
    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "B.pdf",
        "D.pdf",
    ]
    assert dialog.confirm_button.isEnabled() is True


def test_save_ordered_sources_as_new_opens_merged_result_as_new_tab(mvc, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    out_path = tmp_path / "Merged.pdf"

    controller.open_pdf(str(current))
    _pump_events(100)

    controller.save_ordered_sources_as_new(
        [
            {"source_kind": "current"},
            {"source_kind": "file", "path": str(extra)},
        ],
        str(out_path),
    )
    _pump_events(100)

    assert out_path.exists() is True
    assert len(model.session_ids) == 2
    assert model.get_active_session_id() is not None
    merged_text = "".join(model.doc[i].get_text("text") for i in range(len(model.doc)))
    assert "current page" in merged_text
    assert "extra page" in merged_text


def test_resolve_merge_file_retries_password_and_skips_on_cancel(mvc, monkeypatch) -> None:
    _model, view, controller = mvc
    prompts = iter(["wrong", None])
    monkeypatch.setattr(view, "ask_pdf_password", lambda path: next(prompts))

    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *_args: errors.append(_args[-1]))

    attempts: list[str | None] = []

    def fake_open_merge_source(path: str, password: str | None = None):
        attempts.append(password)
        if password is None:
            raise RuntimeError("document closed or encrypted — 需要密碼")
        if password == "wrong":
            raise RuntimeError("PDF 密碼驗證失敗（authenticate 回傳 0）: locked.pdf")
        return {"path": path, "password": password}

    monkeypatch.setattr(controller.model, "open_merge_source", fake_open_merge_source, raising=False)

    result = controller._resolve_merge_file({"source_kind": "file", "path": "locked.pdf"})

    assert result is None
    assert attempts == [None, "wrong"]
    assert any("密碼錯誤" in msg for msg in errors)


def test_start_merge_pdfs_accepts_dialog_and_saves_new_file(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    output = tmp_path / "MergedFromDialog.pdf"
    controller.open_pdf(str(current))
    _pump_events(100)

    import view.pdf_view as pdf_view_module

    def fake_exec(self) -> int:
        self.session_model.add_files([str(extra)])
        self._refresh_file_list()
        self.new_file_radio.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", fake_exec)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    controller.start_merge_pdfs()
    _pump_events(100)

    assert output.exists() is True
    assert len(model.session_ids) == 2
    merged_text = "".join(model.doc[i].get_text("text") for i in range(len(model.doc)))
    assert "current page" in merged_text
    assert "extra page" in merged_text


def test_start_merge_pdfs_passes_controller_resolver_into_dialog(mvc, monkeypatch, tmp_path: Path) -> None:
    _model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    controller.open_pdf(str(current))
    _pump_events(100)

    import view.pdf_view as pdf_view_module

    observed: dict[str, object] = {}
    original_init = pdf_view_module.MergePdfDialog.__init__

    def fake_init(self, session_model, parent=None, file_resolver=None, progress_factory=None):
        observed["resolver"] = file_resolver
        return original_init(
            self,
            session_model,
            parent=parent,
            file_resolver=file_resolver,
            progress_factory=progress_factory,
        )

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "__init__", fake_init)
    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", lambda self: QDialog.Rejected)

    controller.start_merge_pdfs()

    assert observed["resolver"] == controller._resolve_merge_file


def test_merge_dialog_validates_selected_files_before_appending(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    resolved_calls: list[str] = []

    def resolver(entry: dict) -> dict | None:
        path = entry["path"]
        resolved_calls.append(path)
        if path.endswith("bad.pdf"):
            return None
        return {
            "source_kind": "file",
            "path": path,
            "display_name": Path(path).name,
            "password": "pw" if path.endswith("locked.pdf") else None,
        }

    dialog = MergePdfDialog(session, file_resolver=resolver)
    monkeypatch.setattr(
        "view.pdf_view.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: (
            [str(Path("C:/tmp/bad.pdf")), str(Path("C:/tmp/locked.pdf")), str(Path("C:/tmp/ok.pdf"))],
            "PDF (*.pdf)",
        ),
    )

    dialog._select_files()

    assert resolved_calls == [
        str(Path("C:/tmp/bad.pdf")),
        str(Path("C:/tmp/locked.pdf")),
        str(Path("C:/tmp/ok.pdf")),
    ]
    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "locked.pdf",
        "ok.pdf",
    ]


def test_merge_dialog_updates_progress_while_processing_picker_batch(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    progress_values: list[int] = []

    class FakeProgress:
        def __init__(self):
            self.closed = False

        def setValue(self, value: int) -> None:
            progress_values.append(value)

        def wasCanceled(self) -> bool:
            return False

        def show(self) -> None:
            progress_values.append(-1)

        def close(self) -> None:
            self.closed = True
            progress_values.append(-2)

    dialog = MergePdfDialog(
        session,
        file_resolver=lambda entry: {
            "source_kind": "file",
            "path": entry["path"],
            "display_name": Path(entry["path"]).name,
        },
        progress_factory=lambda total: FakeProgress(),
    )
    monkeypatch.setattr(
        "view.pdf_view.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: (
            [str(Path("C:/tmp/one.pdf")), str(Path("C:/tmp/two.pdf"))],
            "PDF (*.pdf)",
        ),
    )

    dialog._select_files()

    assert progress_values == [-1, 0, 1, 2, -2]
