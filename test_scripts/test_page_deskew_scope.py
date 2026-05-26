"""Deskew page-scope selection: 全部 / 當前頁 / 自訂.

Mission: 拉正頁面 should let the user pick a scope — all pages, the current page,
or a custom range (e.g. "1,3-5") — instead of only the current page. The toolbar
action resolves the choice (via dialogs) into a page list and emits
``sig_straighten_pages``; the controller straightens every listed page as a single
undoable batch.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QInputDialog

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_view(qapp, total_pages: int, current_page: int):
    from view.pdf_view import PDFView

    view = PDFView()
    view.total_pages = total_pages
    view.current_page = current_page  # 0-based
    return view


def _capture(view):
    captured: list[list[int]] = []
    view.sig_straighten_pages.connect(lambda pages: captured.append(list(pages)))
    return captured


def test_scope_all_emits_every_page(qapp, monkeypatch) -> None:
    view = _make_view(qapp, total_pages=5, current_page=2)
    captured = _capture(view)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("全部", True))
    try:
        view._straighten_current_page()
        assert captured == [[1, 2, 3, 4, 5]]
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_scope_current_emits_only_current_page(qapp, monkeypatch) -> None:
    view = _make_view(qapp, total_pages=5, current_page=2)  # current = page 3
    captured = _capture(view)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("當前頁", True))
    try:
        view._straighten_current_page()
        assert captured == [[3]]
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_scope_custom_parses_range(qapp, monkeypatch) -> None:
    view = _make_view(qapp, total_pages=6, current_page=0)
    captured = _capture(view)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("自訂", True))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1,3-5", True))
    try:
        view._straighten_current_page()
        assert captured == [[1, 3, 4, 5]]
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def test_scope_cancelled_emits_nothing(qapp, monkeypatch) -> None:
    view = _make_view(qapp, total_pages=5, current_page=0)
    captured = _capture(view)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("", False))
    try:
        view._straighten_current_page()
        assert captured == []
    finally:
        view.close()
        view.deleteLater()
        qapp.processEvents()


def _skewed_pdf(path: Path, pages: int, skew_deg: float) -> None:
    doc = fitz.open()
    w, h = 800, 1000
    img = Image.new("L", (w, h), color=255)
    draw = ImageDraw.Draw(img)
    for y in range(80, h - 80, 40):
        draw.rectangle([80, y, w - 80, y + 12], fill=0)
    skewed = img.rotate(skew_deg, resample=Image.BICUBIC, expand=False, fillcolor=255)
    import io

    buf = io.BytesIO()
    skewed.convert("RGB").save(buf, format="PNG")
    png = buf.getvalue()
    for _ in range(pages):
        page = doc.new_page(width=float(w) * 0.75, height=float(h) * 0.75)
        page.insert_image(page.rect, stream=png)
    doc.save(path)
    doc.close()


def test_controller_straightens_batch_as_single_undo(qapp) -> None:
    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skew.pdf"
        _skewed_pdf(path, pages=3, skew_deg=-6.0)

        model = PDFModel()
        view = PDFView()
        controller = PDFController(model, view)
        view.controller = controller
        controller.activate()
        try:
            for _ in range(5):
                qapp.processEvents()
            controller.open_pdf(str(path))
            for _ in range(10):
                qapp.processEvents()

            stack = model.command_manager._undo_stack
            before_len = len(stack)
            # Straighten pages 1 and 3 (page 2 left alone). Explicit angle keeps the
            # controller test deterministic and independent of skew detection.
            controller.straighten_pages([1, 3, 99], angle_degrees=6.0)

            assert model.doc.page_count == 3, "page count must be preserved"
            assert len(stack) == before_len + 1, "batch must record exactly one undo command"
            assert stack[-1].affected_pages == [1, 3], "invalid page 99 must be filtered out"
            assert model.command_manager.undo() is True, "the batch must be undoable"
            assert model.doc.page_count == 3
        finally:
            view.close()
            view.deleteLater()
            model.close()
            qapp.processEvents()
