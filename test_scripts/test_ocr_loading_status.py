"""The OCR worker must announce the model-loading phase.

Mission #8: after the OCR progress bar appears there is a long idle gap (Surya
model loading) where nothing visible happens. The worker should emit a status
message before page processing so the user knows the app is loading models, not
hung.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from controller.pdf_controller import _OcrWorker  # noqa: E402


class _FakeTool:
    def ocr_pages(self, pages, languages, device, doc=None):
        return {pages[0]: []}


def test_worker_emits_loading_status_before_first_page(qapp=None):
    if QApplication.instance() is None:
        QApplication([])

    worker = _OcrWorker(
        _FakeTool(), page_nums=[1, 2], languages=["en"], device="cpu", doc_bytes=b"snapshot"
    )
    events: list[tuple[str, object]] = []
    worker.status.connect(lambda gen, msg: events.append(("status", msg)))
    worker.progress.connect(lambda gen, p, d, t: events.append(("progress", (p, d, t))))

    worker.run()

    kinds = [kind for kind, _ in events]
    assert "status" in kinds, "worker emitted no loading status"
    # The loading status must come before any per-page progress.
    assert kinds.index("status") < kinds.index("progress"), (
        "loading status must precede page progress"
    )
    status_msg = next(payload for kind, payload in events if kind == "status")
    assert isinstance(status_msg, str) and status_msg.strip()
