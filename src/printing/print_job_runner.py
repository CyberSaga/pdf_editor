from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

import fitz

from model.tools.watermark_rendering import apply_watermarks_to_page

from .base_driver import PrintJobOptions, PrintJobResult
from .dispatcher import PrintDispatcher


def serialize_print_options(options: PrintJobOptions) -> dict:
    normalized = options.normalized()
    payload = asdict(normalized)
    payload["override_fields"] = sorted(payload.get("override_fields", []))
    return payload


def deserialize_print_options(payload: dict) -> PrintJobOptions:
    data = dict(payload or {})
    data["override_fields"] = set(data.get("override_fields", []))
    data["extra_options"] = dict(data.get("extra_options", {}))
    return PrintJobOptions(**data).normalized()


def write_print_job_request(
    base_pdf_bytes: bytes,
    watermarks: list[dict],
    options: PrintJobOptions,
) -> Path:
    job_dir = Path(tempfile.mkdtemp(prefix="pdf_editor_print_job_"))
    input_pdf_path = job_dir / "input.pdf"
    request_path = job_dir / "request.json"

    input_pdf_path.write_bytes(base_pdf_bytes)
    request_path.write_text(
        json.dumps(
            {
                "input_pdf_path": str(input_pdf_path),
                "watermarks": list(watermarks or []),
                "options": serialize_print_options(options),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return request_path


def cleanup_print_job_request(request_path: str | Path | None) -> None:
    if not request_path:
        return
    try:
        shutil.rmtree(Path(request_path).resolve().parent, ignore_errors=True)
    except Exception:
        pass


def _emit_progress(progress_cb: Optional[Callable[[str], None]], message: str) -> None:
    if progress_cb is not None:
        progress_cb(message)


def _build_printable_pdf(input_pdf_path: str, watermarks: list[dict]) -> str:
    base_doc = fitz.open(input_pdf_path)
    tmp_doc = fitz.open()
    temp_output_path = None
    try:
        tmp_doc.insert_pdf(base_doc)
        for wm in watermarks:
            for page_num in wm.get("pages", []):
                if 1 <= page_num <= len(tmp_doc):
                    apply_watermarks_to_page(tmp_doc[page_num - 1], [wm])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            temp_output_path = tmp.name
        tmp_doc.save(temp_output_path, garbage=0)
        return temp_output_path
    finally:
        tmp_doc.close()
        base_doc.close()


def run_print_job_request(
    request_path: str | Path,
    dispatcher: Optional[PrintDispatcher] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> PrintJobResult:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    input_pdf_path = str(request["input_pdf_path"])
    watermarks = list(request.get("watermarks", []))
    options = deserialize_print_options(request.get("options", {}))
    dispatcher = dispatcher or PrintDispatcher()

    printable_pdf_path = input_pdf_path
    cleanup_printable = False
    try:
        _emit_progress(progress_cb, "正在準備列印內容，請稍候...")
        if watermarks:
            printable_pdf_path = _build_printable_pdf(input_pdf_path, watermarks)
            cleanup_printable = True

        _emit_progress(progress_cb, "正在送出列印工作，請稍候...")
        return dispatcher.print_pdf_file(printable_pdf_path, options)
    finally:
        if cleanup_printable:
            try:
                Path(printable_pdf_path).unlink(missing_ok=True)
            except Exception:
                pass


def _stdout_progress(message: str) -> None:
    print(json.dumps({"type": "progress", "message": message}, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print(json.dumps({"type": "error", "message": "Expected one request path argument."}), flush=True)
        return 2

    request_path = args[0]
    try:
        result = run_print_job_request(request_path, progress_cb=_stdout_progress)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "type": "error",
                    "message": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1

    print(
        json.dumps(
            {
                "type": "result",
                "success": result.success,
                "route": result.route,
                "message": result.message,
                "job_id": result.job_id,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
