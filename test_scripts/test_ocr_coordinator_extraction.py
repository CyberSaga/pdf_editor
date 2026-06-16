"""R3.2/OCR: the async OCR subsystem must live in controller/ocr_coordinator.py.

Contract guard for the second controller async coordinator (mirrors
test_search_coordinator_extraction.py): the worker/bridge QObjects and the OCR
orchestration (thread/worker/bridge/gen/session/progress-dialog state + slots) live
on OcrCoordinator; PDFController keeps thin start_ocr/cancel_ocr delegates and
re-exports _OcrWorker/_OcrBridge so existing imports stay valid.
"""

from __future__ import annotations

from controller.ocr_coordinator import (
    OcrCoordinator,
    _OcrBridge,
    _OcrWorker,
)

# Re-export contract: worker/bridge must remain importable from pdf_controller too,
# because test_ocr_controller_flow.py and external callers import them from there.
from controller.pdf_controller import _OcrBridge as ReexportBridge
from controller.pdf_controller import _OcrWorker as ReexportWorker


def test_worker_bridge_reexported_from_controller() -> None:
    assert ReexportWorker is _OcrWorker
    assert ReexportBridge is _OcrBridge


def test_coordinator_owns_ocr_runtime_state() -> None:
    class _FakeController:
        pass

    oc = OcrCoordinator(_FakeController())
    for attr in (
        "_ocr_progress_dialog",
        "_ocr_thread",
        "_ocr_worker",
        "_ocr_worker_bridge",
        "_ocr_gen",
        "_ocr_session_id",
    ):
        assert hasattr(oc, attr), attr
    assert oc._ocr_gen == 0
    assert oc._ocr_thread is None
    assert oc._ocr_session_id is None


def test_coordinator_exposes_facade_methods() -> None:
    class _FakeController:
        pass

    oc = OcrCoordinator(_FakeController())
    for name in (
        "start_ocr",
        "cancel_ocr",
        "connect_bridge",
        "_release_ocr_thread",
        "_show_ocr_progress_dialog",
        "_on_ocr_progress",
        "_on_ocr_status",
        "_on_ocr_page_done",
        "_on_ocr_failed",
        "_on_ocr_thread_finished",
    ):
        assert callable(getattr(oc, name)), name


def test_availability_probe_stays_on_controller() -> None:
    # Per the 3-model design (Codex dissent upheld): _refresh_ocr_availability is a
    # UI-availability probe, not worker runtime — it stays on PDFController.
    from controller.pdf_controller import PDFController

    assert hasattr(PDFController, "_refresh_ocr_availability")
    assert not hasattr(OcrCoordinator, "refresh_availability")
    # The public OCR facades remain on the controller (sig_start_ocr wires to them).
    assert callable(PDFController.start_ocr)
    assert callable(PDFController.cancel_ocr)
