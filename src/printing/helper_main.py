"""Helper subprocess entrypoint for Windows print submission."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Callable

import fitz

from model.tools.watermark_tool import WatermarkTool

from .dispatcher import PrintDispatcher
from .helper_protocol import PrintHelperJob, encode_helper_event
from .messages import (
    PRINT_HELPER_STARTED_MESSAGE,
    PRINT_PREPARING_MESSAGE,
    PRINT_SUBMITTING_MESSAGE,
)


def _build_snapshot_bytes(pdf_path: str, watermarks: list[dict]) -> bytes:
    pdf_bytes = Path(pdf_path).read_bytes()
    if not watermarks:
        return pdf_bytes

    doc = fitz.open("pdf", pdf_bytes)
    try:
        WatermarkTool.apply_watermarks_to_document(doc, watermarks)
        stream = io.BytesIO()
        doc.save(stream, garbage=0)
        return stream.getvalue()
    finally:
        doc.close()


def _stdout_emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_print_helper(
    job_path: str,
    *,
    dispatcher: PrintDispatcher | None = None,
    emit: Callable[[dict], None] | None = None,
) -> int:
    emit_event = emit or _stdout_emit
    job = PrintHelperJob.read(job_path)
    dispatcher = dispatcher or PrintDispatcher()

    try:
        emit_event(encode_helper_event(job.job_id, "started", PRINT_HELPER_STARTED_MESSAGE))
        emit_event(encode_helper_event(job.job_id, "progress", PRINT_PREPARING_MESSAGE))
        snapshot_bytes = _build_snapshot_bytes(job.input_pdf_path, job.watermarks)
        emit_event(encode_helper_event(job.job_id, "progress", PRINT_SUBMITTING_MESSAGE))
        result = dispatcher.print_pdf_bytes(snapshot_bytes, job.options)
        emit_event(
            encode_helper_event(
                job.job_id,
                "succeeded",
                result.message,
                route=result.route,
                result_job_id=result.job_id,
            )
        )
        return 0
    except Exception as exc:
        emit_event(
            encode_helper_event(
                job.job_id,
                "failed",
                str(exc),
                error_type=exc.__class__.__name__,
            )
        )
        return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        sys.stderr.write("usage: python -m src.printing.helper_main <job-file>\n")
        return 2
    return run_print_helper(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
