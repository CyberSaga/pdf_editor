from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402
import pytest  # noqa: E402

from model.headless_merge import headless_merge  # noqa: E402


def _make_pdf(path: Path, text: str, *, pages: int = 1) -> None:
    doc = fitz.open()
    for page_index in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((36, 72), f"{text}-{page_index}")
    doc.save(path)
    doc.close()


def test_headless_merge_combines_inputs(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    merged = tmp_path / "merged.pdf"
    _make_pdf(first, "alpha", pages=2)
    _make_pdf(second, "beta", pages=1)

    headless_merge([str(first), str(second)], str(merged))

    assert merged.exists()
    merged_doc = fitz.open(merged)
    try:
        assert merged_doc.page_count == 3
        assert "alpha-0" in merged_doc[0].get_text("text")
    finally:
        merged_doc.close()


def test_headless_merge_rejects_empty_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        headless_merge([], str(tmp_path / "merged.pdf"))


def test_headless_merge_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        headless_merge([str(tmp_path / "missing.pdf")], str(tmp_path / "merged.pdf"))


def test_headless_merge_rejects_missing_output_directory(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    _make_pdf(first, "alpha")

    with pytest.raises(FileNotFoundError):
        headless_merge([str(first)], str(tmp_path / "missing" / "merged.pdf"))
