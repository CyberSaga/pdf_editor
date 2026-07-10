"""R5.1 → R5-01 — the print path must not write a decrypted PDF to disk.

`capture_print_snapshot_bytes()` returns DECRYPTED bytes (`PDF_ENCRYPT_NONE`) on every
branch, and the print worker used to write them to ``work_dir/input.pdf``.

* **R5.1 (superseded)** patched the *encrypted-source* case: the worker re-encrypted the
  temp with the session password, which then had to travel to the helper out-of-band (the
  QProcess environment) so it could authenticate and rasterise. Unprotected sources still
  left a plaintext copy at rest.
* **R5-01 (this suite)** removes the file. The document is streamed to the helper's stdin,
  so nothing lands on disk for *either* source kind — and because the piped bytes are
  already plaintext, no password needs to reach the child's environment at all.

These tests pin the stronger contract. The helper's password support survives only on the
protocol-v1 ``input_pdf_path`` branch, which production no longer uses.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from controller.print_coordinator import PrintJobRequest, _PrintSubmissionWorker
from src.printing.base_driver import PrintJobOptions


def _decrypted_bytes(text: str = "confidential") -> bytes:
    """Bytes as capture_print_snapshot_bytes would hand them: decrypted, in-memory."""
    doc = fitz.open()
    doc.new_page(width=200, height=200).insert_text((20, 40), text, fontsize=12, fontname="helv")
    try:
        return doc.tobytes()
    finally:
        doc.close()


def _make_encrypted_input(path: Path, password: str = "secret") -> None:
    doc = fitz.open()
    doc.new_page(width=200, height=200).insert_text((20, 40), "secret", fontsize=12, fontname="helv")
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=password,
        user_pw=password,
        permissions=-1,
    )
    doc.close()


def _run_worker(work_dir: Path, payload: bytes):
    request = PrintJobRequest(
        pdf_bytes=payload,
        watermarks=[],
        options=PrintJobOptions(),
        job_id="job-1",
        work_dir=str(work_dir),
    )
    captured: dict = {}

    class _Bridge:
        def forward_prepared(self, job) -> None:
            captured["job"] = job

    bridge = _Bridge()  # held: a GC'd slot owner would silently drop the signal
    worker = _PrintSubmissionWorker(request)
    worker.prepared.connect(bridge.forward_prepared)
    worker.run()
    return captured["job"]


# ── the at-rest leak is gone: the worker writes nothing ─────────────────────


def test_worker_writes_no_file_for_encrypted_source(tmp_path: Path) -> None:
    """The R5.1 case. There is no temp left to encrypt, because there is no temp."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    payload = _decrypted_bytes()

    job = _run_worker(work_dir, payload)

    assert list(work_dir.iterdir()) == [], (
        f"the print worker must write nothing to work_dir, found {list(work_dir.iterdir())}"
    )
    assert not (work_dir / "input.pdf").exists()
    assert job.input_pdf_path is None
    assert job.pdf_bytes == payload, "the document travels in memory, not on disk"


def test_worker_writes_no_file_for_unprotected_source(tmp_path: Path) -> None:
    """The case R5.1 never covered: an unprotected source used to leave plaintext at rest."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    payload = _decrypted_bytes()

    job = _run_worker(work_dir, payload)

    assert list(work_dir.iterdir()) == []
    assert job.pdf_bytes == payload


def test_job_request_has_no_password_field() -> None:
    """The session password is no longer captured: nothing on disk needs protecting."""
    assert "password" not in PrintJobRequest.__dataclass_fields__


def test_document_bytes_never_serialized_into_job_json(tmp_path: Path) -> None:
    """job.json carries options + watermarks only — never the document, never a password."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    job = _run_worker(work_dir, _decrypted_bytes("topsecret-content"))

    payload = job.to_json_dict()
    assert "pdf_bytes" not in payload
    assert "input_pdf_path" not in payload
    assert "topsecret-content" not in str(payload)

    job.write(tmp_path / "job.json")
    raw = (tmp_path / "job.json").read_bytes()
    assert b"%PDF" not in raw
    assert b"topsecret-content" not in raw


def test_job_repr_does_not_leak_document_bytes(tmp_path: Path) -> None:
    """A traceback or log line must not spill the decrypted document."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    job = _run_worker(work_dir, _decrypted_bytes())
    assert "pdf_bytes" not in repr(job)


# ── the helper receives renderable bytes ────────────────────────────────────


def test_helper_passes_through_decrypted_stdin_bytes() -> None:
    """The fileless transport hands the printer exactly what it was given."""
    from src.printing.helper_main import _build_snapshot_bytes

    payload = _decrypted_bytes()
    out = _build_snapshot_bytes(payload, [], password=None)
    assert out == payload, "no watermarks, no encryption: bytes pass through verbatim"


def test_helper_decrypts_encrypted_bytes_with_password(tmp_path: Path) -> None:
    """Protocol-v1 file branch: an encrypted input still authenticates in memory."""
    from src.printing.helper_main import _build_snapshot_bytes

    enc = tmp_path / "input.pdf"
    _make_encrypted_input(enc, password="secret")

    out = _build_snapshot_bytes(enc.read_bytes(), [], password="secret")
    doc = fitz.open("pdf", out)
    try:
        assert not doc.needs_pass, "helper must hand the printer decrypted, renderable bytes"
    finally:
        doc.close()


def test_helper_raises_on_encrypted_bytes_without_password(tmp_path: Path) -> None:
    from src.printing.helper_main import _build_snapshot_bytes

    enc = tmp_path / "input.pdf"
    _make_encrypted_input(enc, password="secret")

    with pytest.raises(Exception):
        _build_snapshot_bytes(enc.read_bytes(), [], password=None)
