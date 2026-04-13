"""
test_controller_workers.py — Signal-emission tests for QThread worker objects.

Covers _OptimizePdfCopyWorker and _PrintSubmissionWorker signal invariants:
  - succeeded/failed/finished signals fire correctly for success and exception paths
  - finished always fires (invariant regardless of success or failure)

No existing test file references either worker class (confirmed via grep).
All tests call worker.run() directly (bypassing QThread) for deterministic, fast CI.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from controller.pdf_controller import (
    OptimizePdfCopyRequest,
    PrintJobRequest,
    _OptimizePdfCopyWorker,
    _PrintSubmissionWorker,
)
from model.pdf_model import PDFModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model_with_pdf(tmp_path: Path) -> PDFModel:
    """Return a PDFModel with a one-page PDF open."""
    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_text(
        (72, 100), "worker test content", fontsize=12, fontname="helv"
    )
    pdf_path = tmp_path / "worker_src.pdf"
    pdf_path.write_bytes(doc.tobytes(garbage=0))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    return model


# ---------------------------------------------------------------------------
# _OptimizePdfCopyWorker
# ---------------------------------------------------------------------------


def test_optimize_worker_emits_succeeded_and_finished_on_success(
    tmp_path: Path, qapp
) -> None:
    """On a successful save_optimized_copy the worker must emit succeeded then finished."""
    model = _make_model_with_pdf(tmp_path)
    mock_result = MagicMock(name="PdfOptimizationResult")

    with patch.object(model, "save_optimized_copy", return_value=mock_result):
        request = OptimizePdfCopyRequest(
            output_path=str(tmp_path / "opt.pdf"),
            options=None,
        )
        worker = _OptimizePdfCopyWorker(model, request)

        succeeded: list[object] = []
        failed: list[object] = []
        finished: list[bool] = []
        worker.succeeded.connect(succeeded.append)
        worker.failed.connect(failed.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

    assert succeeded, "succeeded signal must fire on success"
    assert succeeded[0] is mock_result, "succeeded payload must be the optimization result"
    assert not failed, "failed signal must NOT fire on success"
    assert finished, "finished signal must always fire"
    model.close()


def test_optimize_worker_emits_failed_and_finished_on_exception(
    tmp_path: Path, qapp
) -> None:
    """On an exception in save_optimized_copy the worker must emit failed then finished."""
    model = _make_model_with_pdf(tmp_path)
    error = RuntimeError("simulated disk full")

    with patch.object(model, "save_optimized_copy", side_effect=error):
        request = OptimizePdfCopyRequest(
            output_path=str(tmp_path / "opt.pdf"),
            options=None,
        )
        worker = _OptimizePdfCopyWorker(model, request)

        succeeded: list[object] = []
        failed: list[object] = []
        finished: list[bool] = []
        worker.succeeded.connect(succeeded.append)
        worker.failed.connect(failed.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

    assert failed, "failed signal must fire when save_optimized_copy raises"
    assert isinstance(failed[0], RuntimeError), "failed payload must be the exception"
    assert not succeeded, "succeeded signal must NOT fire on exception"
    assert finished, "finished signal must always fire even after exception"
    model.close()


# ---------------------------------------------------------------------------
# _PrintSubmissionWorker
# ---------------------------------------------------------------------------


def test_print_submission_worker_emits_prepared_and_finished_on_success(
    tmp_path: Path, qapp
) -> None:
    """On successful capture_pdf_bytes the worker must emit prepared then finished."""
    minimal_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\nxref\n0 0\ntrailer\n<<>>\nstartxref\n0\n%%EOF"

    request = PrintJobRequest(
        capture_pdf_bytes=lambda: minimal_pdf_bytes,
        watermarks=[],
        options=MagicMock(name="PrintJobOptions"),
        job_id="test-success-job",
        work_dir=str(tmp_path),
    )
    worker = _PrintSubmissionWorker(request)

    prepared: list[object] = []
    failed: list[object] = []
    finished: list[bool] = []
    worker.prepared.connect(prepared.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert prepared, "prepared signal must fire when capture_pdf_bytes succeeds"
    assert not failed, "failed signal must NOT fire on success"
    assert finished, "finished signal must always fire"
    # Verify the input PDF was written to work_dir
    assert (tmp_path / "input.pdf").exists(), "worker must write input.pdf to work_dir"


def test_print_submission_worker_emits_failed_and_finished_on_capture_exception(
    tmp_path: Path, qapp
) -> None:
    """When capture_pdf_bytes raises, the worker must emit failed then finished."""
    def _bad_capture() -> bytes:
        raise RuntimeError("capture failed — model closed")

    request = PrintJobRequest(
        capture_pdf_bytes=_bad_capture,
        watermarks=[],
        options=MagicMock(name="PrintJobOptions"),
        job_id="test-fail-job",
        work_dir=str(tmp_path),
    )
    worker = _PrintSubmissionWorker(request)

    prepared: list[object] = []
    failed: list[object] = []
    finished: list[bool] = []
    worker.prepared.connect(prepared.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert failed, "failed signal must fire when capture_pdf_bytes raises"
    assert isinstance(failed[0], RuntimeError), "failed payload must be the exception"
    assert not prepared, "prepared signal must NOT fire when capture_pdf_bytes raises"
    assert finished, "finished signal must always fire even after exception"
