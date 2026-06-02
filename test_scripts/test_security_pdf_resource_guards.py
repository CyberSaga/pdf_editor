"""Security patch P1 (finding F1): PDF resource guards.

Untrusted PDFs are parsed/rasterized with no bound on file size, page count, or
page dimensions, allowing memory/CPU exhaustion (CWE-400 / CWE-409). These tests
cover the two helpers (`_guard_before_open`, `_safe_render_scale`) directly and
the two `open_pdf` guards via integration with the real parser (constants are
monkeypatched down so a tiny real PDF trips them — no giant fixtures needed).
"""

from __future__ import annotations

import math

import fitz
import pytest

import model.pdf_model as pdf_model
from model.pdf_model import PDFModel, _guard_before_open, _safe_render_scale


# --- _guard_before_open -----------------------------------------------------

class _FakeStat:
    def __init__(self, size: int) -> None:
        self.st_size = size


class _FakePath:
    def __init__(self, size: int) -> None:
        self._size = size

    def stat(self) -> _FakeStat:
        return _FakeStat(self._size)


def test_guard_before_open_rejects_oversize() -> None:
    with pytest.raises(ValueError):
        _guard_before_open(_FakePath(pdf_model._MAX_PDF_BYTES + 1))


def test_guard_before_open_allows_normal_size() -> None:
    # Returns None without raising.
    assert _guard_before_open(_FakePath(1024)) is None


# --- _safe_render_scale -----------------------------------------------------

class _FakeRect:
    def __init__(self, w: float, h: float) -> None:
        self.width = w
        self.height = h


class _FakePage:
    def __init__(self, w: float, h: float) -> None:
        self.rect = _FakeRect(w, h)


def test_safe_render_scale_clamps_huge_page() -> None:
    # 10000x10000 at scale 2.0 -> 4e8 px, way over the cap. Expected ceiling is
    # sqrt(40e6 / 1e8) ~= 0.632.
    out = _safe_render_scale(_FakePage(10_000, 10_000), 2.0)
    expected_ceiling = math.sqrt(pdf_model._MAX_PIXMAP_PX / 1e8)
    assert out <= expected_ceiling + 1e-9
    assert out > 0.1  # not floored for this size


def test_safe_render_scale_leaves_normal_page_untouched() -> None:
    # A4 at scale 2.0 -> ~2M px, well under the cap; scale must be unchanged.
    assert _safe_render_scale(_FakePage(595, 842), 2.0) == 2.0


def test_safe_render_scale_floors_at_min() -> None:
    # An extreme page bottoms out at the 0.1 floor (documented tradeoff).
    assert _safe_render_scale(_FakePage(1_000_000, 1_000_000), 2.0) == 0.1


# --- open_pdf integration ---------------------------------------------------

def _make_pdf(path, pages: int = 1):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return path


def test_open_pdf_rejects_oversize_before_parsing(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path / "tiny.pdf")
    # Force the size guard to trip on a tiny real file, and prove fitz.open is
    # never reached (the guard fires first).
    monkeypatch.setattr(pdf_model, "_MAX_PDF_BYTES", 0)
    opened: list[str] = []
    real_open = fitz.open

    def _tracking_open(*args, **kwargs):
        opened.append("open")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(pdf_model.fitz, "open", _tracking_open)

    model = PDFModel()
    try:
        with pytest.raises(Exception) as exc:
            model.open_pdf(str(pdf))
        assert "size limit" in str(exc.value)
        assert opened == []  # parser never invoked
        assert model.get_active_session_id() is None
    finally:
        model.close()


def test_open_pdf_rejects_excess_page_count(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path / "tiny.pdf", pages=1)
    monkeypatch.setattr(pdf_model, "_MAX_PAGES", 0)  # 1-page doc now exceeds

    model = PDFModel()
    try:
        with pytest.raises(Exception) as exc:
            model.open_pdf(str(pdf))
        assert "page limit" in str(exc.value)
        assert model.get_active_session_id() is None
    finally:
        model.close()


def test_open_pdf_allows_normal_document(tmp_path) -> None:
    # Regression guard: a normal small PDF still opens under default limits.
    pdf = _make_pdf(tmp_path / "ok.pdf", pages=3)
    model = PDFModel()
    try:
        sid = model.open_pdf(str(pdf))
        assert sid
        assert model.get_active_session_id() == sid
        assert len(model.doc) == 3
    finally:
        model.close()
