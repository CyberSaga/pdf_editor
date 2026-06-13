from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import controller.pdf_controller as pdf_controller  # noqa: E402
import view.pdf_view as pdf_view  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


def test_controller_resolve_insert_source_prompts_and_retries_password(monkeypatch) -> None:
    prompts: list[str] = []
    errors: list[str] = []

    class _FakeModel:
        def __init__(self) -> None:
            self.passwords: list[str | None] = []

        def open_insert_source(self, path: str, password: str | None = None) -> dict:
            self.passwords.append(password)
            if password is None:
                raise RuntimeError("document closed or encrypted — 需要密碼")
            if password == "wrong":
                raise RuntimeError("PDF 密碼驗證失敗（authenticate 回傳 0）")
            return {"path": path, "display_name": Path(path).name, "page_count": 3, "password": password}

    class _FakeView:
        def __init__(self) -> None:
            self._passwords = iter(["wrong", "secret"])

        def ask_pdf_password(self, path: str) -> str | None:
            prompts.append(path)
            return next(self._passwords)

    monkeypatch.setattr(pdf_controller, "show_error", lambda _view, message: errors.append(message))

    controller = pdf_controller.PDFController.__new__(pdf_controller.PDFController)
    controller.model = _FakeModel()
    controller.view = _FakeView()

    resolved = pdf_controller.PDFController.resolve_insert_source_file(controller, "locked.pdf")

    assert resolved == {
        "path": "locked.pdf",
        "display_name": "locked.pdf",
        "page_count": 3,
        "password": "secret",
    }
    assert controller.model.passwords == [None, "wrong", "secret"]
    assert prompts == ["locked.pdf", "locked.pdf"]
    assert errors == ["密碼錯誤，請重試。"]


def test_controller_resolve_insert_source_cancel_returns_none() -> None:
    class _FakeModel:
        def open_insert_source(self, path: str, password: str | None = None) -> dict:
            raise RuntimeError("document closed or encrypted — 需要密碼")

    class _FakeView:
        def ask_pdf_password(self, path: str) -> str | None:
            return None

    controller = pdf_controller.PDFController.__new__(pdf_controller.PDFController)
    controller.model = _FakeModel()
    controller.view = _FakeView()

    assert pdf_controller.PDFController.resolve_insert_source_file(controller, "locked.pdf") is None


def test_view_insert_pages_from_file_at_uses_controller_resolver(monkeypatch, tmp_path) -> None:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.total_pages = 5
    view.sig_insert_pages_from_file = _FakeSignal()
    source_path = tmp_path / "locked.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")

    resolved = {"path": str(source_path), "page_count": 4, "password": "secret"}
    view.controller = SimpleNamespace(resolve_insert_source_file=lambda path: resolved)

    monkeypatch.setattr(
        pdf_view.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source_path), "PDF (*.pdf)"),
    )
    monkeypatch.setattr(pdf_view.QInputDialog, "getText", lambda *args, **kwargs: ("1,3-4", True))
    monkeypatch.setattr(pdf_view, "parse_pages", lambda text, total: [1, 3, 4])

    pdf_view.PDFView._insert_pages_from_file_at(view, 6)

    assert view.sig_insert_pages_from_file.calls == [(str(source_path), [1, 3, 4], 6, "secret")]


def test_view_insert_pages_from_file_cancelled_resolver_emits_nothing(monkeypatch, tmp_path) -> None:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.total_pages = 5
    view.sig_insert_pages_from_file = _FakeSignal()
    source_path = tmp_path / "locked.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")
    view.controller = SimpleNamespace(resolve_insert_source_file=lambda path: None)
    prompted: list[str] = []

    monkeypatch.setattr(
        pdf_view.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source_path), "PDF (*.pdf)"),
    )
    monkeypatch.setattr(pdf_view.QInputDialog, "getText", lambda *args, **kwargs: prompted.append("prompt") or ("1", True))

    pdf_view.PDFView._insert_pages_from_file_at(view, 2)

    assert view.sig_insert_pages_from_file.calls == []
    assert prompted == []

