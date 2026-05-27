from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _ensure_test_file_1_pdf() -> None:
    """Provide a synthetic ``test_files/1.pdf`` when the real fixture is absent.

    ``test_files/`` is gitignored, so on a fresh checkout the small-clean sample
    used by the char-run-reconstruction and core-interaction-audit suites is
    missing and those tests error out. Generate a stand-in that satisfies their
    assertions (per-word runs young/the/program/favorite; line paragraphs incl.
    a "run or not run" control line; no replacement characters). Never overwrite
    a real fixture if one is already present.
    """
    target = ROOT / "test_files" / "1.pdf"
    if target.exists():
        return
    try:
        import fitz
    except Exception:
        return
    target.parent.mkdir(parents=True, exist_ok=True)

    def _words_line(page, y: float, words: list[str], size: float = 12.0) -> None:
        x = 72.0
        for word in words:
            page.insert_text((x, y), word, fontsize=size, fontname="helv")
            x += len(word) * size * 0.62 + size * 0.5

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _words_line(page, 120, ["When", "I", "was", "young", "the", "program", "was", "my", "favorite"])
    _words_line(page, 170, ["this", "is", "a", "run", "or", "not", "run", "control", "line"])
    _words_line(page, 220, ["some", "additional", "filler", "text", "for", "the", "document", "body"])
    doc.save(str(target), garbage=0)
    doc.close()


_ensure_test_file_1_pdf()
