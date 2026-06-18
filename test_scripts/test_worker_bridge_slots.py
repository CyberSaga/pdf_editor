"""R6.1 — characterization tests for the worker->GUI bridge slots.

The async subsystems (print / optimize / OCR) each marshal worker-thread
callbacks back onto the GUI thread through a small ``QObject`` bridge whose
``forward_*`` ``@Slot`` methods simply re-emit a matching ``Signal``. These
slots had **zero** direct test references (census-verified, R6.1) yet they are
exactly where a PySide6 6.9 -> 6.10 ``@Slot`` arity change regresses silently:
a mismatched decorator drops the call and the GUI never updates, with no error.

These tests connect a plain Python receiver to each bridge signal, invoke the
``forward_*`` slot, and assert the signal fired exactly once with the *same*
payload (identity-preserving for object payloads, value-preserving for the
typed int/str OCR signals). They pin the contract, not the transport.

Note: the receiver objects and signal-capturing closures are bound to locals;
an inline throwaway receiver can be GC'd before the emit, silently dropping the
Qt connection (a real bite recorded in PITFALLS for the R5.1 print tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from controller.ocr_coordinator import _OcrBridge  # noqa: E402
from controller.pdf_controller import _OptimizeWorkerBridge  # noqa: E402
from controller.print_coordinator import _PrintWorkerBridge  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_print_bridge_forward_prepared_reemits_same_job(qapp) -> None:
    bridge = _PrintWorkerBridge()
    received: list[object] = []
    bridge.prepared.connect(received.append)

    sentinel = object()
    bridge.forward_prepared(sentinel)

    assert len(received) == 1
    assert received[0] is sentinel


def test_print_bridge_forward_progress_and_failed(qapp) -> None:
    bridge = _PrintWorkerBridge()
    progress: list[str] = []
    failed: list[object] = []
    bridge.progress.connect(progress.append)
    bridge.failed.connect(failed.append)

    bridge.forward_progress("列印中")
    exc = RuntimeError("boom")
    bridge.forward_failed(exc)

    assert progress == ["列印中"]
    assert failed == [exc] and failed[0] is exc


def test_print_bridge_notify_thread_finished_fires_once(qapp) -> None:
    bridge = _PrintWorkerBridge()
    ticks: list[int] = []
    bridge.thread_finished.connect(lambda: ticks.append(1))

    bridge.notify_thread_finished()

    assert ticks == [1]


def test_optimize_bridge_forward_succeeded_reemits_same_result(qapp) -> None:
    bridge = _OptimizeWorkerBridge()
    received: list[object] = []
    bridge.succeeded.connect(received.append)

    result = {"saved_bytes": 123}
    bridge.forward_succeeded(result)

    assert len(received) == 1
    assert received[0] is result


def test_optimize_bridge_forward_failed_reemits_same_exc(qapp) -> None:
    bridge = _OptimizeWorkerBridge()
    failed: list[object] = []
    bridge.failed.connect(failed.append)

    exc = ValueError("nope")
    bridge.forward_failed(exc)

    assert failed == [exc] and failed[0] is exc


def test_ocr_bridge_forward_status_preserves_gen_and_message(qapp) -> None:
    bridge = _OcrBridge()
    received: list[tuple[int, str]] = []
    bridge.status.connect(lambda gen, msg: received.append((gen, msg)))

    bridge.forward_status(7, "辨識中")

    assert received == [(7, "辨識中")]


def test_ocr_bridge_forward_page_done_preserves_payload(qapp) -> None:
    bridge = _OcrBridge()
    received: list[tuple[int, int, object]] = []
    bridge.page_done.connect(lambda gen, page, spans: received.append((gen, page, spans)))

    spans = [{"text": "x"}]
    bridge.forward_page_done(3, 5, spans)

    assert len(received) == 1
    gen, page, payload = received[0]
    assert (gen, page) == (3, 5)
    assert payload is spans


def test_ocr_bridge_forward_progress_preserves_four_ints(qapp) -> None:
    bridge = _OcrBridge()
    received: list[tuple[int, int, int, int]] = []
    bridge.progress.connect(lambda *args: received.append(tuple(args)))

    bridge.forward_progress(1, 2, 3, 4)

    assert received == [(1, 2, 3, 4)]
