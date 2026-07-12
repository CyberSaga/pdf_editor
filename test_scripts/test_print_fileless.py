"""R5-01 — the print path must never write document bytes to disk.

Before this suite the pipeline created **two** plaintext temps per job:

  * ``work_dir/input.pdf``  — ``_PrintSubmissionWorker`` (re-encrypted for password-protected
    sources under R5.1, but written verbatim for unprotected ones);
  * a ``NamedTemporaryFile`` — ``PrintDispatcher.print_pdf_bytes``, plaintext for the driver
    call, unlinked afterwards.

``capture_print_snapshot_bytes`` always returns ``PDF_ENCRYPT_NONE`` bytes, so *both* temps
held a fully decrypted copy of the document, recoverable from the filesystem (and from the
NTFS journal after unlink).

These tests pin the fileless contract end to end: renderer, qt bridge, drivers, dispatcher,
worker, runner and helper. Design: ``plans/r5-01-fileless-print.md`` §11.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

from src.printing.base_driver import PrinterDriver, PrintJobOptions, PrintJobResult
from src.printing.dispatcher import PrintDispatcher
from src.printing.helper_protocol import PrintHelperJob
from src.printing.pdf_renderer import PDFRenderer


def _pdf_bytes(pages: int = 2, text: str = "fileless probe") -> bytes:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page(width=200, height=200).insert_text(
            (20, 40), f"{text} {i}", fontsize=12, fontname="helv"
        )
    try:
        return doc.tobytes()
    finally:
        doc.close()


class _RecordingDriver(PrinterDriver):
    """Real PrinterDriver subclass that records how the dispatcher reached it."""

    def __init__(self) -> None:
        self.bytes_calls: list[int] = []
        self.path_calls: list[str] = []

    @property
    def name(self) -> str:
        return "recording"

    def list_printers(self):
        return []

    def get_default_printer(self):
        return None

    def get_printer_status(self, _printer_name: str) -> str:
        return "ready"

    def print_pdf(self, pdf_path, page_indices, options) -> PrintJobResult:
        self.path_calls.append(str(pdf_path))
        return PrintJobResult(success=True, route="path", message="ok")

    def print_pdf_from_bytes(self, pdf_bytes, page_indices, options) -> PrintJobResult:
        self.bytes_calls.append(len(pdf_bytes))
        return PrintJobResult(success=True, route="bytes", message="ok")


class _Sig:
    """Minimal Qt-signal stand-in for the fake QProcess below."""

    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeProcess:
    """Exactly the QProcess surface PrintSubprocessRunner touches."""

    def __init__(self) -> None:
        self.written = bytearray()
        self.write_channel_closed = False
        self.largest_single_write = 0
        self.started_with: tuple | None = None
        for sig in (
            "readyReadStandardOutput",
            "readyReadStandardError",
            "finished",
            "errorOccurred",
            "bytesWritten",
        ):
            setattr(self, sig, _Sig())

    def start(self, program, args) -> None:
        self.started_with = (program, args)

    def write(self, data: bytes) -> int:
        n = len(data)
        self.largest_single_write = max(self.largest_single_write, n)
        self.written.extend(data)
        # Emulate Qt draining the pipe: acknowledge what was just accepted.
        self.bytesWritten.emit(n)
        return n

    def closeWriteChannel(self) -> None:
        self.write_channel_closed = True

    def state(self):
        return None

    def setWorkingDirectory(self, _d) -> None:
        pass

    def setProcessEnvironment(self, _e) -> None:
        pass


@pytest.fixture
def no_temp_files(monkeypatch: pytest.MonkeyPatch):
    """Make ANY attempt to create a temp file explode, with a readable message."""
    created: list[str] = []

    real_named = tempfile.NamedTemporaryFile
    real_mkstemp = tempfile.mkstemp

    def _boom_named(*args, **kwargs):
        created.append("NamedTemporaryFile")
        raise AssertionError("print path created a NamedTemporaryFile (R5-01)")

    def _boom_mkstemp(*args, **kwargs):
        created.append("mkstemp")
        raise AssertionError("print path created a temp file via mkstemp (R5-01)")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _boom_named)
    monkeypatch.setattr(tempfile, "mkstemp", _boom_mkstemp)
    yield created
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", real_named)
    monkeypatch.setattr(tempfile, "mkstemp", real_mkstemp)


# ── renderer: bytes are a first-class source ────────────────────────────────


def test_renderer_get_page_count_accepts_bytes(tmp_path: Path) -> None:
    data = _pdf_bytes(pages=3)
    path = tmp_path / "probe.pdf"
    path.write_bytes(data)
    assert PDFRenderer.get_page_count(data) == PDFRenderer.get_page_count(str(path)) == 3


def test_renderer_iter_page_images_from_bytes_matches_path(tmp_path: Path, qapp) -> None:
    data = _pdf_bytes(pages=2)
    path = tmp_path / "probe.pdf"
    path.write_bytes(data)
    renderer = PDFRenderer()

    from_bytes = list(renderer.iter_page_images(data, [0, 1], dpi=72))
    from_path = list(renderer.iter_page_images(str(path), [0, 1], dpi=72))

    assert len(from_bytes) == len(from_path) == 2
    for b, p in zip(from_bytes, from_path):
        assert b.page_index == p.page_index
        assert (b.image.width(), b.image.height()) == (p.image.width(), p.image.height())
        assert b.page_rect == p.page_rect


def test_renderer_rejects_corrupt_bytes() -> None:
    from src.printing.errors import RenderingError

    with pytest.raises((RenderingError, Exception)):
        PDFRenderer.get_page_count(b"not a pdf at all")


# ── qt bridge: raster from bytes, no temp ───────────────────────────────────


def test_raster_print_pdf_accepts_bytes(tmp_path: Path, qapp, no_temp_files) -> None:
    from src.printing.qt_bridge import raster_print_pdf

    out = tmp_path / "out.pdf"
    result = raster_print_pdf(
        _pdf_bytes(pages=1),
        [0],
        PrintJobOptions(output_pdf_path=str(out), dpi=72),
    )
    assert result.success
    assert out.exists() and out.stat().st_size > 0


# ── driver contract ─────────────────────────────────────────────────────────


def test_base_driver_default_print_pdf_from_bytes_falls_back_to_path(tmp_path: Path) -> None:
    """A driver that does NOT override keeps working (scoped temp, then cleaned up)."""

    class _PathOnlyDriver(_RecordingDriver):
        print_pdf_from_bytes = PrinterDriver.print_pdf_from_bytes  # type: ignore[assignment]

    driver = _PathOnlyDriver()
    result = driver.print_pdf_from_bytes(_pdf_bytes(1), [0], PrintJobOptions().normalized())
    assert result.success
    assert len(driver.path_calls) == 1
    assert not Path(driver.path_calls[0]).exists(), "the fallback temp must be unlinked"


def test_windows_driver_print_pdf_from_bytes_creates_no_temp(monkeypatch, no_temp_files) -> None:
    from src.printing.platforms import win_driver as win_mod

    seen: dict = {}

    def _fake_raster(pdf_source, page_indices, options, renderer=None):
        seen["source_type"] = type(pdf_source).__name__
        seen["pages"] = list(page_indices)
        return PrintJobResult(success=True, route="qt-raster->spooler", message="ok")

    monkeypatch.setattr(win_mod, "raster_print_pdf", _fake_raster)

    driver = win_mod.WindowsPrinterDriver()
    data = _pdf_bytes(pages=2)
    # paper_size + orientation both explicit => single-group raster, no split pass
    options = PrintJobOptions(printer_name="P", paper_size="a4", orientation="portrait").normalized()
    result = driver.print_pdf_from_bytes(data, [0, 1], options)

    assert result.success
    assert seen["source_type"] == "bytes", "bytes must reach raster_print_pdf unmaterialised"
    assert seen["pages"] == [0, 1]


def test_windows_driver_split_by_layout_classifies_from_bytes(monkeypatch, no_temp_files) -> None:
    """The geometry pass must open the PDF from memory, not from a path."""
    from src.printing.platforms import win_driver as win_mod

    calls: list[str] = []

    def _fake_raster(pdf_source, page_indices, options, renderer=None):
        calls.append(type(pdf_source).__name__)
        return PrintJobResult(success=True, route="qt-raster->spooler", message="ok")

    monkeypatch.setattr(win_mod, "raster_print_pdf", _fake_raster)

    doc = fitz.open()
    doc.new_page(width=595, height=842)  # A4 portrait
    doc.new_page(width=842, height=595)  # A4 landscape -> forces a 2-group split
    data = doc.tobytes()
    doc.close()

    driver = win_mod.WindowsPrinterDriver()
    options = PrintJobOptions(printer_name="P").normalized()  # paper/orientation auto
    result = driver.print_pdf_from_bytes(data, [0, 1], options)

    assert result.success
    assert len(calls) == 2, f"expected one raster job per layout group, got {calls}"
    assert set(calls) == {"bytes"}


def test_linux_driver_raster_fallback_is_fileless(monkeypatch, no_temp_files) -> None:
    from src.printing.platforms import linux_driver as linux_mod

    seen: dict = {}

    def _fake_raster(pdf_source, page_indices, options, renderer=None):
        seen["source_type"] = type(pdf_source).__name__
        return PrintJobResult(success=True, route="qt-raster->spooler", message="ok")

    monkeypatch.setattr(linux_mod, "raster_print_pdf", _fake_raster)
    monkeypatch.setattr(linux_mod.LinuxPrinterDriver, "supports_direct_pdf", property(lambda _s: False))

    driver = linux_mod.LinuxPrinterDriver()
    result = driver.print_pdf_from_bytes(_pdf_bytes(1), [0], PrintJobOptions().normalized())
    assert result.success
    assert seen["source_type"] == "bytes"


def test_linux_driver_cups_temp_is_driver_scoped_and_removed(monkeypatch) -> None:
    """CUPS needs a real, *plaintext* file (its filters must rasterise it).

    That temp is the one accepted residual. It must live only across the printFile call
    and be unlinked afterwards.
    """
    from src.printing.platforms import linux_driver as linux_mod

    observed: dict = {}

    class _Conn:
        def getDefault(self):
            return "cups-printer"

        def printFile(self, printer, path, title, options):
            p = Path(path)
            observed["existed_during_call"] = p.exists()
            observed["content"] = p.read_bytes() if p.exists() else b""
            observed["path"] = path
            return 42

    monkeypatch.setattr(linux_mod.LinuxPrinterDriver, "supports_direct_pdf", property(lambda _s: True))
    monkeypatch.setattr(linux_mod.LinuxPrinterDriver, "_cups_connection", lambda _s: _Conn())

    driver = linux_mod.LinuxPrinterDriver()
    data = _pdf_bytes(1)
    result = driver.print_pdf_from_bytes(data, [0], PrintJobOptions(printer_name="cups-printer").normalized())

    assert result.success and result.route == "cups-direct-pdf"
    assert observed["existed_during_call"] is True
    assert observed["content"] == data, "CUPS must receive readable plaintext, not ciphertext"
    assert not Path(observed["path"]).exists(), "driver-scoped temp must be unlinked in finally"


# ── dispatcher ──────────────────────────────────────────────────────────────


def test_dispatcher_bytes_path_creates_no_temp(no_temp_files) -> None:
    driver = _RecordingDriver()
    dispatcher = PrintDispatcher(driver=driver)  # real PDFRenderer

    data = _pdf_bytes(pages=2)
    result = dispatcher.print_pdf_bytes(data, PrintJobOptions(printer_name="Printer A"))

    assert result.success
    assert driver.bytes_calls == [len(data)], "dispatcher must hand bytes straight to the driver"
    assert driver.path_calls == [], "dispatcher must not materialise a path"


def test_dispatcher_bytes_path_still_resolves_page_ranges(no_temp_files) -> None:
    captured: dict = {}

    class _Driver(_RecordingDriver):
        def print_pdf_from_bytes(self, pdf_bytes, page_indices, options):
            captured["pages"] = list(page_indices)
            return PrintJobResult(success=True, route="bytes", message="ok")

    dispatcher = PrintDispatcher(driver=_Driver())
    dispatcher.print_pdf_bytes(_pdf_bytes(pages=5), PrintJobOptions(page_ranges="2,4"))
    assert captured["pages"] == [1, 3]


def test_dispatcher_bytes_path_rejects_offline_printer(no_temp_files) -> None:
    from src.printing.errors import PrinterUnavailableError

    class _Offline(_RecordingDriver):
        def get_printer_status(self, _printer_name: str) -> str:
            return "offline"

    dispatcher = PrintDispatcher(driver=_Offline())
    with pytest.raises(PrinterUnavailableError):
        dispatcher.print_pdf_bytes(_pdf_bytes(1), PrintJobOptions(printer_name="Dead"))


# ── coordinator worker: no input.pdf ────────────────────────────────────────


def test_print_worker_writes_no_document_file(tmp_path: Path) -> None:
    from controller.print_coordinator import PrintJobRequest, _PrintSubmissionWorker

    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    payload = _pdf_bytes(1)
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

    bridge = _Bridge()
    worker = _PrintSubmissionWorker(request)
    worker.prepared.connect(bridge.forward_prepared)
    worker.run()

    assert list(work_dir.iterdir()) == [], f"work_dir must stay empty, found {list(work_dir.iterdir())}"
    job = captured["job"]
    assert job.input_pdf_path is None, "fileless jobs carry no input path"
    assert job.pdf_bytes == payload


def test_job_json_omits_input_path_and_never_carries_document_bytes(tmp_path: Path) -> None:
    job = PrintHelperJob(
        job_id="j",
        watermarks=[],
        options=PrintJobOptions(),
    )
    payload = job.to_json_dict()
    assert "input_pdf_path" not in payload
    assert PrintHelperJob.from_json_dict(payload).input_pdf_path is None

    job.write(tmp_path / "job.json")
    raw = (tmp_path / "job.json").read_bytes()
    assert b"%PDF" not in raw, "document bytes must never be serialized into job.json"


# ── helper: reads the document from stdin ───────────────────────────────────


def test_helper_reads_document_from_stdin_when_no_input_path(tmp_path: Path) -> None:
    from src.printing.helper_main import run_print_helper

    data = _pdf_bytes(1)
    job = PrintHelperJob(job_id="stdin-job", watermarks=[], options=PrintJobOptions())
    job_path = tmp_path / "job.json"
    job.write(job_path)

    seen: dict = {}

    class _Dispatcher:
        def print_pdf_bytes(self, pdf_bytes, options):
            seen["bytes"] = pdf_bytes
            return PrintJobResult(success=True, route="test", message="ok")

    events: list[dict] = []
    rc = run_print_helper(
        str(job_path),
        dispatcher=_Dispatcher(),
        emit=events.append,
        stdin_reader=lambda: data,
    )

    assert rc == 0, [e for e in events if e["event"] == "failed"]
    assert seen["bytes"] == data
    assert any(e["event"] == "succeeded" for e in events)


def test_helper_still_supports_legacy_input_path(tmp_path: Path) -> None:
    """Protocol v1 fallback stays alive so PR-17 is coordinator-side revertable."""
    from src.printing.helper_main import run_print_helper

    data = _pdf_bytes(1)
    src = tmp_path / "input.pdf"
    src.write_bytes(data)
    job = PrintHelperJob(
        job_id="file-job", watermarks=[], options=PrintJobOptions(), input_pdf_path=str(src)
    )
    job_path = tmp_path / "job.json"
    job.write(job_path)

    seen: dict = {}

    class _Dispatcher:
        def print_pdf_bytes(self, pdf_bytes, options):
            seen["bytes"] = pdf_bytes
            return PrintJobResult(success=True, route="test", message="ok")

    def _no_stdin():
        raise AssertionError("legacy path must not read stdin")

    rc = run_print_helper(
        str(job_path), dispatcher=_Dispatcher(), emit=lambda _e: None, stdin_reader=_no_stdin
    )
    assert rc == 0
    assert seen["bytes"] == data


def test_helper_fails_cleanly_on_empty_stdin(tmp_path: Path) -> None:
    from src.printing.helper_main import run_print_helper

    job = PrintHelperJob(job_id="empty", watermarks=[], options=PrintJobOptions())
    job_path = tmp_path / "job.json"
    job.write(job_path)

    events: list[dict] = []
    rc = run_print_helper(str(job_path), emit=events.append, stdin_reader=lambda: b"")
    assert rc == 1
    assert any(e["event"] == "failed" for e in events)


# ── runner: streams bytes to the child's stdin ──────────────────────────────


def test_runner_streams_document_to_stdin_in_chunks(tmp_path: Path, qapp) -> None:
    from src.printing import subprocess_runner as runner_mod
    from src.printing.subprocess_runner import PrintSubprocessRunner

    payload = b"%PDF-" + b"x" * (3 * runner_mod._STDIN_CHUNK_BYTES) + b"\n%%EOF\n"

    proc = _FakeProcess()
    job = PrintHelperJob(job_id="stream", watermarks=[], options=PrintJobOptions())
    runner = PrintSubprocessRunner(
        job,
        process_factory=lambda: proc,
        work_dir=str(tmp_path),
        pdf_bytes=payload,
    )
    runner.start()

    assert bytes(proc.written) == payload, "the whole document must reach the child's stdin"
    assert proc.write_channel_closed is True, "stdin must be closed so the child sees EOF"
    assert runner._pdf_bytes is None, "runner must drop its reference once streamed"
    # Flow control: never hand Qt more than one chunk at a time, so peak buffer is
    # bounded by the chunk size rather than by the document size.
    assert proc.largest_single_write <= runner_mod._STDIN_CHUNK_BYTES, (
        f"chunked writes expected, saw a {proc.largest_single_write}-byte write"
    )
    assert not (tmp_path / "input.pdf").exists()


def test_runner_writes_job_json_without_document_bytes(tmp_path: Path, qapp) -> None:
    from src.printing.subprocess_runner import PrintSubprocessRunner

    job = PrintHelperJob(job_id="j", watermarks=[], options=PrintJobOptions())
    runner = PrintSubprocessRunner(
        job, process_factory=_FakeProcess, work_dir=str(tmp_path), pdf_bytes=_pdf_bytes(1)
    )
    runner.start()

    raw = (tmp_path / "job.json").read_bytes()
    assert b"%PDF" not in raw
