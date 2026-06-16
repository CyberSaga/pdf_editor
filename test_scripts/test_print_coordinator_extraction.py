"""R3.2/print: the async print subsystem must live in controller/print_coordinator.py.

Contract guard for the third (largest) controller async coordinator. The worker/bridge
QObjects + PrintJobRequest and the print orchestration (thread/worker/runner/bridge/
dialog + stall-terminate state) move onto PrintCoordinator; PDFController keeps thin
print_document/_has_active_print_submission delegates and the model-coupled/app-lifecycle
methods (_render_print_preview_image, handle_app_close, _fullscreen_is_blocked), and
re-exports _PrintSubmissionWorker/_PrintWorkerBridge/PrintJobRequest.
"""

from __future__ import annotations

# RED before extraction: this module does not exist yet (hard ImportError on collect).
from controller.print_coordinator import (
    PrintCoordinator,
    PrintJobRequest,
    _PrintSubmissionWorker,
    _PrintWorkerBridge,
)

# Re-export contract: worker/bridge/request must remain importable from pdf_controller.
from controller.pdf_controller import PrintJobRequest as ReexportRequest
from controller.pdf_controller import _PrintSubmissionWorker as ReexportWorker
from controller.pdf_controller import _PrintWorkerBridge as ReexportBridge


def test_worker_bridge_request_reexported_from_controller() -> None:
    assert ReexportWorker is _PrintSubmissionWorker
    assert ReexportBridge is _PrintWorkerBridge
    assert ReexportRequest is PrintJobRequest


def test_coordinator_owns_print_runtime_state() -> None:
    class _FakeController:
        pass

    pc = PrintCoordinator(_FakeController())
    for attr in (
        "_print_dialog",
        "_print_progress_dialog",
        "_print_thread",
        "_print_worker",
        "_print_runner",
        "_print_worker_bridge",
        "_print_close_pending",
        "_print_stalled",
    ):
        assert hasattr(pc, attr), attr


def test_coordinator_exposes_facade_methods() -> None:
    class _FakeController:
        pass

    pc = PrintCoordinator(_FakeController())
    for name in (
        "print_document",
        "connect_bridge",
        "has_active_job",
        "_start_print_submission",
        "_create_print_runner",
        "_on_print_job_prepared",
        "_on_print_submission_failed",
        "_on_print_thread_finished",
        "_terminate_active_print_submission",
    ):
        assert callable(getattr(pc, name)), name


def test_controller_keeps_facades_and_lifecycle_hooks() -> None:
    from controller.pdf_controller import PDFController

    # Public/facade entry points stay on the controller.
    assert callable(PDFController.print_document)
    assert callable(PDFController._has_active_print_submission)
    # Model-coupled preview + app-lifecycle hooks intentionally stay on the controller.
    assert callable(PDFController._render_print_preview_image)
    assert callable(PDFController.handle_app_close)
