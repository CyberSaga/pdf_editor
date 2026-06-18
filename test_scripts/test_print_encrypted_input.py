"""R5.1 — the print path must not write a fully decrypted PDF to disk.

`capture_worker_snapshot_bytes()` returns DECRYPTED bytes (PDF_ENCRYPT_NONE), and the
print worker previously wrote them verbatim to ``work_dir/input.pdf`` — leaving a fully
decrypted copy of a password-protected PDF at rest. Option A: the worker re-encrypts the
temp with the session password before writing, and the password reaches the helper via the
QProcess *environment* (never job.json / disk); the helper authenticates in-memory so it
can still rasterize and print.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from controller.print_coordinator import PrintJobRequest, _PrintSubmissionWorker
from src.printing.base_driver import PrintJobOptions


def _decrypted_bytes(text: str = "confidential") -> bytes:
    """Bytes as capture_worker_snapshot_bytes would hand them: decrypted, in-memory."""
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


# ── the at-rest leak: worker must encrypt the temp ──────────────────────────


def test_worker_writes_encrypted_input_when_password_present(tmp_path: Path) -> None:
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    request = PrintJobRequest(
        pdf_bytes=_decrypted_bytes(),
        watermarks=[],
        options=PrintJobOptions(),
        job_id="job-1",
        work_dir=str(work_dir),
        password="secret",
    )
    worker = _PrintSubmissionWorker(request)
    worker.run()

    input_pdf = work_dir / "input.pdf"
    assert input_pdf.exists()
    written = fitz.open(str(input_pdf))
    try:
        assert written.needs_pass, (
            "encrypted print must NOT leave a decrypted PDF at rest in work_dir/input.pdf"
        )
        assert written.authenticate("secret") != 0, (
            "the on-disk temp must open with the session password"
        )
    finally:
        written.close()


def test_worker_writes_plain_input_when_no_password(tmp_path: Path) -> None:
    """Unencrypted print path is unchanged: no password -> plain temp (byte-for-byte)."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    payload = _decrypted_bytes()
    request = PrintJobRequest(
        pdf_bytes=payload,
        watermarks=[],
        options=PrintJobOptions(),
        job_id="job-2",
        work_dir=str(work_dir),
        password=None,
    )
    _PrintSubmissionWorker(request).run()

    input_pdf = work_dir / "input.pdf"
    assert input_pdf.read_bytes() == payload
    written = fitz.open(str(input_pdf))
    try:
        assert not written.needs_pass
    finally:
        written.close()


def test_password_never_serialized_into_job_json(tmp_path: Path) -> None:
    """The password must travel out-of-band: it must not land in the on-disk job payload."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    request = PrintJobRequest(
        pdf_bytes=_decrypted_bytes(),
        watermarks=[],
        options=PrintJobOptions(),
        job_id="job-3",
        work_dir=str(work_dir),
        password="topsecret",
    )
    captured: dict = {}

    class _Bridge:
        def forward_prepared(self, job) -> None:
            captured["job"] = job

    bridge = _Bridge()  # held: a GC'd slot owner would silently drop the signal
    worker = _PrintSubmissionWorker(request)
    worker.prepared.connect(bridge.forward_prepared)
    worker.run()

    job = captured["job"]
    assert "topsecret" not in str(job.to_json_dict()), "password must not be in job.json"
    assert "topsecret" not in str(job.metadata)


# ── the helper must authenticate in-memory so the printer gets renderable bytes ──


def test_helper_decrypts_encrypted_input_with_password(tmp_path: Path) -> None:
    from src.printing.helper_main import _build_snapshot_bytes

    enc = tmp_path / "input.pdf"
    _make_encrypted_input(enc, password="secret")

    out = _build_snapshot_bytes(str(enc), [], password="secret")
    doc = fitz.open("pdf", out)
    try:
        assert not doc.needs_pass, "helper must hand the printer decrypted, renderable bytes"
    finally:
        doc.close()


def test_helper_raises_on_encrypted_input_without_password(tmp_path: Path) -> None:
    from src.printing.helper_main import _build_snapshot_bytes

    enc = tmp_path / "input.pdf"
    _make_encrypted_input(enc, password="secret")

    with pytest.raises(Exception):
        _build_snapshot_bytes(str(enc), [], password=None)


def test_helper_unencrypted_input_unchanged(tmp_path: Path) -> None:
    """No-watermark, unencrypted input still returns the raw bytes verbatim."""
    from src.printing.helper_main import _build_snapshot_bytes

    plain = tmp_path / "input.pdf"
    plain.write_bytes(_decrypted_bytes())

    out = _build_snapshot_bytes(str(plain), [], password=None)
    assert out == plain.read_bytes()
