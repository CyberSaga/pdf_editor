from __future__ import annotations

import importlib
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((36, 72), text)
    doc.save(path)
    doc.close()


def test_parse_cli_accepts_positional_files() -> None:
    import main

    args = main.parse_cli(["a.pdf", "b.pdf"])

    assert args.files == ["a.pdf", "b.pdf"]
    assert args.merge_output is None


def test_parse_cli_supports_merge_output() -> None:
    import main

    args = main.parse_cli(["--merge", "out.pdf", "a.pdf", "b.pdf"])

    assert args.merge_output == "out.pdf"
    assert args.files == ["a.pdf", "b.pdf"]


def test_parse_cli_requires_input_for_merge() -> None:
    import main

    with pytest.raises(SystemExit):
        main.parse_cli(["--merge", "out.pdf"])


def test_run_merge_and_exit_is_headless(tmp_path: Path) -> None:
    main = importlib.import_module("main")
    out_path = tmp_path / "merged.pdf"
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    _make_pdf(first, "alpha")
    _make_pdf(second, "beta")

    qtwidgets_loaded_before = "PySide6.QtWidgets" in sys.modules

    exit_code = main.run_merge_and_exit(
        main.parse_cli(["--merge", str(out_path), str(first), str(second)])
    )

    assert exit_code == 0
    assert out_path.exists()
    assert ("PySide6.QtWidgets" in sys.modules) is qtwidgets_loaded_before
