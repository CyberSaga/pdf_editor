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


@pytest.fixture(autouse=True)
def _reset_app_stylesheet():
    """Restore QApplication stylesheet to its pre-test state after each test.

    Tests that call view.apply_initial_theme() / app.setStyleSheet(...) leave a
    global stylesheet active; leaked QSS gives QTextEdit subclasses padding that
    shifts pixel-diff comparisons in later rendering tests.
    """
    app = QApplication.instance()
    before_stylesheet = app.styleSheet() if app is not None else ""
    yield
    if app is not None:
        current_app = QApplication.instance()
        if current_app is not None and current_app.styleSheet() != before_stylesheet:
            current_app.setStyleSheet(before_stylesheet)


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
