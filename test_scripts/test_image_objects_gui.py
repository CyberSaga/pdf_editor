from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import view.pdf_view as pdf_view  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


def _make_view() -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.sig_add_image_object = _FakeSignal()
    view.current_page = 0
    view.controller = SimpleNamespace()
    return view


def test_insert_image_from_file_emits_request(monkeypatch, tmp_path) -> None:
    view = _make_view()
    fake_path = tmp_path / "in.png"
    fake_bytes = b"png-bytes"

    monkeypatch.setattr(pdf_view.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(fake_path), ""))
    monkeypatch.setattr(Path, "read_bytes", lambda self: fake_bytes)

    view._insert_image_object_from_file(page_num=1, visual_rect=fitz.Rect(10, 20, 30, 40))

    assert len(view.sig_add_image_object.emitted) == 1
    req = view.sig_add_image_object.emitted[0][0]
    assert req.__class__.__name__ == "InsertImageObjectRequest"
    assert req.page_num == 1
    assert req.image_bytes == fake_bytes


def test_insert_image_from_clipboard_emits_request(monkeypatch) -> None:
    view = _make_view()
    fake_bytes = b"clipboard-png"
    monkeypatch.setattr(pdf_view.PDFView, "_clipboard_png_bytes", lambda self: fake_bytes)

    view._insert_image_object_from_clipboard(page_num=1, visual_rect=fitz.Rect(10, 20, 30, 40))

    assert len(view.sig_add_image_object.emitted) == 1
    req = view.sig_add_image_object.emitted[0][0]
    assert req.__class__.__name__ == "InsertImageObjectRequest"
    assert req.page_num == 1
    assert req.image_bytes == fake_bytes


def test_insert_image_from_file_current_page_uses_default_target(monkeypatch) -> None:
    view = _make_view()
    called = {}

    def _fake_insert(self, *, page_num: int, visual_rect: fitz.Rect) -> None:
        called["page_num"] = page_num
        called["visual_rect"] = fitz.Rect(visual_rect)

    monkeypatch.setattr(pdf_view.PDFView, "_insert_image_object_from_file", _fake_insert)
    monkeypatch.setattr(
        pdf_view.PDFView,
        "_default_image_insert_rect_for_page",
        lambda self, page_idx, center=None: fitz.Rect(5, 6, 55, 36),
    )
    view.current_page = 2

    view._insert_image_object_from_file_at_current_page()

    assert called["page_num"] == 3
    assert called["visual_rect"] == fitz.Rect(5, 6, 55, 36)


def test_insert_image_from_clipboard_current_page_uses_default_target(monkeypatch) -> None:
    view = _make_view()
    called = {}

    def _fake_insert(self, *, page_num: int, visual_rect: fitz.Rect) -> None:
        called["page_num"] = page_num
        called["visual_rect"] = fitz.Rect(visual_rect)

    monkeypatch.setattr(pdf_view.PDFView, "_insert_image_object_from_clipboard", _fake_insert)
    monkeypatch.setattr(
        pdf_view.PDFView,
        "_default_image_insert_rect_for_page",
        lambda self, page_idx, center=None: fitz.Rect(12, 14, 112, 89),
    )
    view.current_page = 1

    view._insert_image_object_from_clipboard_at_current_page()

    assert called["page_num"] == 2
    assert called["visual_rect"] == fitz.Rect(12, 14, 112, 89)
