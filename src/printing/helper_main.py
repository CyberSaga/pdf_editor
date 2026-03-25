"""Helper subprocess entrypoint for Windows print submission."""

from __future__ import annotations

import io
import json
import sys
import threading
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


def _start_heartbeat(
    *,
    job_id: str,
    interval_ms: int,
    emit_event: Callable[[dict], None],
) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    interval_seconds = max(0.1, float(interval_ms) / 1000.0)

    def _heartbeat_loop() -> None:
        while not stop_event.wait(interval_seconds):
            emit_event(encode_helper_event(job_id, "heartbeat", ""))

    thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    thread.start()
    return stop_event, thread


def run_print_helper(
    job_path: str,
    *,
    dispatcher: PrintDispatcher | None = None,
    emit: Callable[[dict], None] | None = None,
) -> int:
    emit_event = emit or _stdout_emit
    job = PrintHelperJob.read(job_path)
    dispatcher = dispatcher or PrintDispatcher()
    heartbeat_stop: threading.Event | None = None
    heartbeat_thread: threading.Thread | None = None

    try:
        emit_event(encode_helper_event(job.job_id, "started", PRINT_HELPER_STARTED_MESSAGE))
        emit_event(encode_helper_event(job.job_id, "progress", PRINT_PREPARING_MESSAGE))
        heartbeat_stop, heartbeat_thread = _start_heartbeat(
            job_id=job.job_id,
            interval_ms=job.heartbeat_interval_ms,
            emit_event=emit_event,
        )
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
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1.0)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        sys.stderr.write("usage: python -m src.printing.helper_main <job-file>\n")
        return 2
    return run_print_helper(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
