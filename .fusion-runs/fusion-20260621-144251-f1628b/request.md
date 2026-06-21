# Trusted Task

Senior code review of the supplied R5 commit-range diff. Find only concrete defects introduced by this range in correctness, security, resource lifecycle, performance, architecture, or regression behavior. Pay special attention to encrypted PDF permission/password semantics, plaintext-at-rest guarantees, process environment leakage/inheritance, QThread/QProcess races and cleanup, optimize-copy encryption preservation, and wheel/sdist guard validity. For every candidate, statically trace the trigger and cite exact changed file/line. Reject pre-existing issues, intentional behavior, style/nits, and claims below 80/100 confidence. Return a concise ranked list with reproduction steps; explicitly say no findings if none survive.

# Untrusted Context

--- BEGIN UNTRUSTED STDIN ---
diff --git a/.gitignore b/.gitignore
index ec176ae..7916b41 100644
--- a/.gitignore
+++ b/.gitignore
@@ -43,29 +43,31 @@ memory
 
 
 # Local Claude settings and generated vision outputs
 .claude/settings.local.json
 reflow/_vision_output/
 
 # Security scan outputs (regenerate via the scanner; not source)
 bandit-report.json
 semgrep-report.json
 security-scan-review.txt
 
 # Generated HTML/CSS renderings of the markdown docs (keep only the .md sources)
 TODOS.html
 implementation-notes.html
 weakness_patch*.html
 docs/readable-markdown.css
 
 # macOS
 .DS_Store
 
-# Packaging artifacts (editable install creates cybersaga_pdf.egg-info/)
+# Packaging artifacts (editable install creates cybersaga_pdf.egg-info/;
+# setuptools/`pip wheel` create build/ in the project root ? incl. the R5.4 guard test)
 *.egg-info/
 dist/
+build/
 
 # Coverage artifacts (R0.5 pytest-cov; regenerate via --cov, floor lives in refactor-state.md)
 .coverage
 .coverage.*
 coverage*.json
 htmlcov/
diff --git a/controller/print_coordinator.py b/controller/print_coordinator.py
index c7fd673..2300ce3 100644
--- a/controller/print_coordinator.py
+++ b/controller/print_coordinator.py
@@ -1,108 +1,143 @@
 """Print submission coordinator (R3.2 god-module decomposition seam).
 
 Owns the print runtime: the `_PrintSubmissionWorker`/`_PrintWorkerBridge` QObjects, the
 `PrintJobRequest` payload, the `PrintDispatcher`, the `PrintSubprocessRunner` lifecycle,
 the progress dialog, and the stall/terminate state machine ? all previously on
 `PDFController`. The controller keeps thin `print_document`/`_has_active_print_submission`
 delegates plus the model-coupled `_render_print_preview_image` and the app-lifecycle hooks
 (`handle_app_close`/`_fullscreen_is_blocked`), and re-exports
 `_PrintSubmissionWorker`/`_PrintWorkerBridge`/`PrintJobRequest`.
 
 Extracted verbatim from `pdf_controller.py` (only controller-owned reads rewritten to
 `self._c.<attr>`, and `_has_active_print_submission()` -> `has_active_job()`) so the
 behavior ? signal wiring, QThread + subprocess lifecycle, the GUI-thread
 `capture_worker_snapshot_bytes` handoff (name unchanged; the R5.1 fix is deferred), the
 stall/terminate transitions, and progress-dialog ownership ? is byte-identical.
 """
 
 from __future__ import annotations
 
+import io
 import logging
 import tempfile
 import uuid
 from dataclasses import dataclass
 from dataclasses import replace as dataclass_replace
 from pathlib import Path
 from typing import TYPE_CHECKING
 
+import fitz
 from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
 from PySide6.QtWidgets import QDialog, QMessageBox, QProgressDialog
 
 from src.printing import PrintDispatcher, PrintHelperTerminatedError, PrintingError
 from src.printing.helper_protocol import PrintHelperJob
 from src.printing.messages import (
     PRINT_CLOSING_MESSAGE,
     PRINT_PREPARING_MESSAGE,
     PRINT_STALLED_MESSAGE,
     PRINT_STATUS_MESSAGE,
     PRINT_SUBMITTING_MESSAGE,
     PRINT_TERMINATE_BUTTON_TEXT,
     PRINT_TERMINATING_MESSAGE,
 )
 from src.printing.print_dialog import UnifiedPrintDialog
 from src.printing.subprocess_runner import PrintSubprocessRunner
 from utils.helpers import show_error
 
 if TYPE_CHECKING:
     from controller.pdf_controller import PDFController
 
 logger = logging.getLogger(__name__)
 
 
 @dataclass(frozen=True)
 class PrintJobRequest:
     pdf_bytes: bytes
     watermarks: list[dict]
     options: object
     job_id: str
     work_dir: str
+    # R5.1: when the source is password-protected, the captured bytes are decrypted
+    # (capture_worker_snapshot_bytes uses PDF_ENCRYPT_NONE). The worker re-encrypts the
+    # on-disk temp with this password so no plaintext copy lands at rest; the password
+    # itself travels to the helper out-of-band (process env), never in this payload.
+    password: str | None = None
 
 
 class _PrintSubmissionWorker(QObject):
     progress = Signal(str)
     prepared = Signal(object)
     failed = Signal(object)
     finished = Signal()
 
     def __init__(self, request: PrintJobRequest) -> None:
         super().__init__()
         self._request = request
 
     def run(self) -> None:
         try:
             self.progress.emit(PRINT_PREPARING_MESSAGE)
             input_pdf_path = Path(self._request.work_dir) / "input.pdf"
-            input_pdf_path.write_bytes(self._request.pdf_bytes)
+            input_pdf_path.write_bytes(self._encode_input_bytes())
             self.prepared.emit(
                 PrintHelperJob(
                     job_id=self._request.job_id,
                     input_pdf_path=str(input_pdf_path),
                     watermarks=self._request.watermarks,
                     options=self._request.options,
                 )
             )
         except Exception as exc:
             self.failed.emit(exc)
         finally:
             self.finished.emit()
 
+    def _encode_input_bytes(self) -> bytes:
+        """Bytes to write to ``work_dir/input.pdf``.
+
+        For an unprotected source this is the captured snapshot verbatim. For a
+        password-protected source the captured bytes are *decrypted*
+        (``capture_worker_snapshot_bytes`` uses ``PDF_ENCRYPT_NONE``), so we re-encrypt
+        with the session password before the disk write ? the temp must never be a
+        plaintext copy of a protected PDF (R5.1). Runs on the worker thread; the save
+        targets a freshly opened in-memory handle, never the live model document.
+        """
+        pdf_bytes = self._request.pdf_bytes
+        password = self._request.password
+        if not password:
+            return pdf_bytes
+        src = fitz.open("pdf", pdf_bytes)
+        try:
+            buffer = io.BytesIO()
+            src.save(
+                buffer,
+                encryption=fitz.PDF_ENCRYPT_AES_256,
+                owner_pw=password,
+                user_pw=password,
+                garbage=0,
+            )
+            return buffer.getvalue()
+        finally:
+            src.close()
+
 
 class _PrintWorkerBridge(QObject):
     """Marshals worker-thread callbacks back onto the GUI thread."""
 
     progress = Signal(str)
     prepared = Signal(object)
     failed = Signal(object)
     thread_finished = Signal()
 
     @Slot(str)
     def forward_progress(self, message: str) -> None:
         self.progress.emit(message)
 
     @Slot(object)
     def forward_prepared(self, job) -> None:
         self.prepared.emit(job)
 
     @Slot(object)
     def forward_failed(self, exc) -> None:
         self.failed.emit(exc)
@@ -115,40 +150,43 @@ class _PrintWorkerBridge(QObject):
 class PrintCoordinator:
     """Owns the print runtime for one PDFController.
 
     The controller holds exactly one of these (`self._print_coordinator`) and delegates
     `print_document` + `_has_active_print_submission` to it. The coordinator reaches back
     through `self._c` for the controller-owned model/view/session helpers and the
     `_render_print_preview_image` preview callback, which stay on PDFController.
     """
 
     def __init__(self, controller: PDFController) -> None:
         self._c = controller
         self.print_dispatcher: PrintDispatcher | None = None
         self._print_dialog = None
         self._print_progress_dialog: QProgressDialog | None = None
         self._print_thread: QThread | None = None
         self._print_worker: _PrintSubmissionWorker | None = None
         self._print_runner: PrintSubprocessRunner | None = None
         self._print_worker_bridge: _PrintWorkerBridge | None = None
         self._print_close_pending = False
         self._print_stalled = False
+        # R5.1: session password for an encrypted in-flight job, handed to the helper
+        # via the subprocess environment (never job.json). Cleared once the job is idle.
+        self._print_password: str | None = None
 
     def connect_bridge(self) -> None:
         """Lazy-init the GUI-thread bridge + dispatcher (from PDFController.activate())."""
         if self._print_worker_bridge is None:
             self._print_worker_bridge = _PrintWorkerBridge(self._c.view)
             self._print_worker_bridge.progress.connect(self._update_print_progress_dialog)
             self._print_worker_bridge.prepared.connect(self._on_print_job_prepared)
             self._print_worker_bridge.failed.connect(self._on_print_submission_failed)
             self._print_worker_bridge.thread_finished.connect(self._on_print_thread_finished)
         if self.print_dispatcher is None:
             self.print_dispatcher = PrintDispatcher()
 
     def has_active_job(self) -> bool:
         return self._print_thread is not None or self._print_runner is not None
 
     def begin_close_pending(self) -> None:
         """Mark an app-close as pending while a print job is in flight (from handle_app_close)."""
         self._print_close_pending = True
         self._update_print_close_pending_ui()
 
@@ -216,66 +254,77 @@ class PrintCoordinator:
     def _enable_print_terminate_option(self) -> None:
         if self._print_progress_dialog is None:
             return
         if hasattr(self._print_progress_dialog, "setCancelButtonText"):
             self._print_progress_dialog.setCancelButtonText(PRINT_TERMINATE_BUTTON_TEXT)
 
     def _start_print_submission(self, options) -> None:
         self._c.activate()
         bridge = self._print_worker_bridge
         if bridge is None:
             raise RuntimeError("Print worker bridge is not initialized")
         session_id = self._c.model.get_active_session_id()
         work_dir = tempfile.mkdtemp(prefix="pdf_editor_print_")
         normalized_options = options.normalized() if hasattr(options, "normalized") else options
         if session_id and hasattr(normalized_options, "extra_options"):
             profile = self._c._resolve_session_profile(session_id, sync_view=True)
             extra = {**(getattr(normalized_options, "extra_options", {}) or {}), "render_colorspace": profile}
             normalized_options = dataclass_replace(normalized_options, extra_options=extra)
 
         pdf_bytes = self._c.capture_worker_snapshot_bytes()
+        # R5.1: capture_worker_snapshot_bytes decrypts; if the source needs a password,
+        # carry it so the worker re-encrypts the on-disk temp and the helper can re-auth.
+        doc = getattr(self._c.model, "doc", None)
+        password = self._c.model.password if doc is not None and getattr(doc, "needs_pass", False) else None
+        self._print_password = password
         request = PrintJobRequest(
             pdf_bytes=pdf_bytes,
             watermarks=self._c.model.get_print_watermarks(),
             options=normalized_options,
             job_id=str(uuid.uuid4()),
             work_dir=work_dir,
+            password=password,
         )
         thread = QThread(self._c.view)
         worker = _PrintSubmissionWorker(request)
         worker.moveToThread(thread)
         thread.started.connect(worker.run)
         worker.progress.connect(bridge.forward_progress)
         worker.prepared.connect(bridge.forward_prepared)
         worker.failed.connect(bridge.forward_failed)
         worker.finished.connect(thread.quit)
         worker.finished.connect(worker.deleteLater)
         thread.finished.connect(bridge.notify_thread_finished)
         thread.finished.connect(thread.deleteLater)
         self._print_thread = thread
         self._print_worker = worker
         self._print_stalled = False
         thread.start()
 
     def _create_print_runner(self, job: PrintHelperJob) -> PrintSubprocessRunner:
         work_dir = str(Path(job.input_pdf_path).parent)
-        return PrintSubprocessRunner(job, work_dir=work_dir, parent=self._c.view)
+        return PrintSubprocessRunner(
+            job,
+            work_dir=work_dir,
+            parent=self._c.view,
+            helper_password=self._print_password,
+        )
 
     def _on_print_job_prepared(self, job: PrintHelperJob) -> None:
         self._update_print_progress_dialog(PRINT_SUBMITTING_MESSAGE)
         runner = self._create_print_runner(job)
         runner.progress.connect(self._update_print_progress_dialog)
         runner.stalled.connect(self._on_print_submission_stalled)
         runner.succeeded.connect(self._on_print_submission_succeeded)
         runner.failed.connect(self._on_print_submission_failed)
         runner.finished.connect(self._on_print_runner_finished)
         self._print_runner = runner
         runner.start()
 
     def _on_print_submission_succeeded(self, result) -> None:
         route = result.route if hasattr(result, "route") else ""
         message = result.message if hasattr(result, "message") else str(result)
         self._finalize_print_submission()
         if self._print_close_pending:
             return
         QMessageBox.information(
             self._c.view,
@@ -314,40 +363,42 @@ class PrintCoordinator:
         logger.error(f"?????????: {exc}")
         if not self._print_close_pending:
             show_error(self._c.view, f"?????????: {exc}")
 
     def _finalize_print_submission(self) -> None:
         self._hide_print_progress_dialog()
 
     def _on_print_thread_finished(self) -> None:
         self._print_thread = None
         self._print_worker = None
         self._complete_active_print_submission_if_idle()
 
     def _on_print_runner_finished(self) -> None:
         self._print_runner = None
         self._complete_active_print_submission_if_idle()
 
     def _complete_active_print_submission_if_idle(self) -> None:
         if self.has_active_job():
             return
         self._print_stalled = False
+        # R5.1: drop the in-flight session password once no job references it.
+        self._print_password = None
         if not self._print_close_pending:
             self._set_print_ui_busy(False)
             return
         self._print_close_pending = False
         self._set_print_ui_busy(False)
         self._c.view.close()
 
     def print_document(self):
         """????????????? + ??????"""
         if not self._c.model.doc:
             show_error(self._c.view, "?????? PDF ??")
             return
 
         self._c.activate()
         if self.has_active_job():
             self._set_print_status_message(PRINT_STATUS_MESSAGE)
             return
 
         if self._print_dialog is not None and self._print_dialog.isVisible():
             self._print_dialog.raise_()
diff --git a/model/pdf_optimizer.py b/model/pdf_optimizer.py
index 6971c79..dde3492 100644
--- a/model/pdf_optimizer.py
+++ b/model/pdf_optimizer.py
@@ -782,73 +782,136 @@ def postprocess_optimized_pdf_with_pikepdf(
             except OSError:
                 pass
 
 
 def save_optimized_working_doc(
     model: PDFModel,
     working_doc: fitz.Document,
     temp_save: Path,
     options: PdfOptimizeOptions,
 ) -> None:
     if model._requires_post_save_packaging(options) and _pikepdf() is None:
         raise PdfOptimizeError(
             "?????? pikepdf????? linearize ????"
             "??? pip install pikepdf ?????????????????????"
         )
     working_doc.save(str(temp_save), **model._fast_save_kwargs(options))
     if model._requires_post_save_packaging(options):
         model._postprocess_optimized_pdf_with_pikepdf(temp_save, options)
 
 
+def _encryption_method_for(encryption_meta: str) -> int:
+    """Map a PyMuPDF ``metadata['encryption']`` string to a save-time method const.
+
+    Defaults to AES-256 for unrecognised strings ? re-encrypting never *weakens* the
+    protection below the strongest standard, so an unknown method falls back up, not down.
+    """
+    enc = (encryption_meta or "").upper()
+    if "AES" in enc:
+        return fitz.PDF_ENCRYPT_AES_128 if "128" in enc else fitz.PDF_ENCRYPT_AES_256
+    if "RC4" in enc or " V1" in enc or " V2" in enc or "40-BIT" in enc:
+        return fitz.PDF_ENCRYPT_RC4_40 if "40" in enc else fitz.PDF_ENCRYPT_RC4_128
+    return fitz.PDF_ENCRYPT_AES_256
+
+
+def reapply_source_encryption(model: PDFModel, output_path: str) -> None:
+    """Re-encrypt an optimized copy so an encrypted source stays password-protected.
+
+    The optimize pipeline rebuilds the working doc from the *decrypted* live-doc bytes
+    (``build_working_doc_for_optimized_copy`` -> ``tobytes`` for the encrypted/needs_pass
+    case), so without this the optimized copy of a password-protected PDF would be written
+    unprotected (R5.5). We re-apply the session password captured at open and the live
+    doc's effective permission bits. Only one password is retained in memory, so the
+    owner/user split collapses (``owner_pw == user_pw``); the confidentiality invariant ?
+    the copy needs the same password to open ? is preserved.
+
+    No-op for unprotected sources. Owner-password-only PDFs open with ``needs_pass`` False
+    (no password barrier at open) and are intentionally left unencrypted, matching how the
+    live session already treats them.
+
+    The save operates on a freshly reopened handle of the *optimized output file*, never
+    on ``model.doc`` (the live doc), so it does not cross the encryption AST guard.
+    """
+    doc = model.doc
+    if doc is None or not getattr(doc, "needs_pass", False):
+        return
+    password = model.password
+    if not password:
+        # A needs_pass document cannot have been opened/authenticated without a
+        # password, so this is unreachable in practice. Refuse loudly rather than
+        # emit a silently unprotected copy.
+        raise PdfOptimizeError("???????????????????")
+    metadata = doc.metadata or {}
+    method = _encryption_method_for(metadata.get("encryption", ""))
+    permissions = int(getattr(doc, "permissions", -1))
+    out = Path(output_path)
+    temp_enc = out.with_name(f".{out.stem}_enc_{uuid.uuid4().hex}.pdf")
+    reopened = fitz.open(output_path)
+    try:
+        reopened.save(
+            str(temp_enc),
+            encryption=method,
+            owner_pw=password,
+            user_pw=password,
+            permissions=permissions,
+        )
+    finally:
+        reopened.close()
+    os.replace(str(temp_enc), output_path)
+
+
 def save_optimized_copy(
     model: PDFModel,
     new_path: str,
     options: PdfOptimizeOptions | None = None,
 ) -> PdfOptimizationResult:
     if not model.doc:
         raise RuntimeError("??????? PDF")
 
     active_sid = model.get_active_session_id()
     canonical_new = model._canonicalize_path(new_path)
     current_meta = model.get_session_meta(active_sid) if active_sid else None
     current_canonical = model._canonicalize_path(current_meta["path"]) if current_meta and current_meta.get("path") else None
     existing_sid = model._path_to_session_id.get(canonical_new)
     if existing_sid is not None or (current_canonical and canonical_new == current_canonical):
         raise RuntimeError("????????????????????????????")
 
     resolved_options = model._normalize_optimize_options(options or model.preset_optimize_options("??"))
     optimize_source_path = model._resolve_file_backed_optimize_source(active_sid)
     original_bytes = model._current_document_size_bytes(active_sid)
     working_doc = model._build_working_doc_for_optimized_copy(active_sid)
     image_usage = collect_image_usage(working_doc) if resolved_options.optimize_images else {}
     temp_save = Path(model.temp_dir.name) / f"optimized_{uuid.uuid4()}.pdf"
     try:
         model._apply_optimize_options(
             working_doc,
             resolved_options,
             source_path=optimize_source_path,
             original_bytes=original_bytes,
             image_usage=image_usage,
         )
         model._save_optimized_working_doc(working_doc, temp_save, resolved_options)
         Path(new_path).parent.mkdir(parents=True, exist_ok=True)
         shutil.move(str(temp_save), new_path)
+        # R5.5: an encrypted source is rebuilt from decrypted bytes above; re-apply the
+        # session password so the optimized copy stays password-protected (no-op otherwise).
+        reapply_source_encryption(model, new_path)
         optimized_bytes = Path(new_path).stat().st_size
         bytes_saved = max(0, original_bytes - optimized_bytes)
         summary: list[str] = [resolved_options.preset]
         if resolved_options.optimize_images:
             summary.append(f"?? {resolved_options.image_dpi_target}dpi / JPEG {resolved_options.image_jpeg_quality}")
         if resolved_options.subset_fonts:
             summary.append("?????")
         if resolved_options.remove_metadata or resolved_options.remove_xml_metadata:
             summary.append("?? metadata")
         return PdfOptimizationResult(
             output_path=str(new_path),
             original_bytes=original_bytes,
             optimized_bytes=optimized_bytes,
             bytes_saved=bytes_saved,
             percent_saved=(bytes_saved / original_bytes * 100.0) if original_bytes else 0.0,
             applied_preset=resolved_options.preset,
             applied_summary=summary,
         )
     except PdfOptimizeError:
         if temp_save.exists():
diff --git a/src/printing/helper_main.py b/src/printing/helper_main.py
index cea1814..5c020dc 100644
--- a/src/printing/helper_main.py
+++ b/src/printing/helper_main.py
@@ -1,52 +1,63 @@
 """Helper subprocess entrypoint for Windows print submission."""
 
 from __future__ import annotations
 
 import io
 import json
+import os
 import sys
 import threading
 from collections.abc import Callable
 from pathlib import Path
 
 import fitz
 
 from model.tools.watermark_tool import WatermarkTool
 
 from .dispatcher import PrintDispatcher
+from .errors import PrintingError
 from .helper_protocol import PrintHelperJob, encode_helper_event
 from .messages import (
     PRINT_HELPER_STARTED_MESSAGE,
     PRINT_PREPARING_MESSAGE,
     PRINT_SUBMITTING_MESSAGE,
 )
 
 
-def _build_snapshot_bytes(pdf_path: str, watermarks: list[dict]) -> bytes:
+def _build_snapshot_bytes(
+    pdf_path: str, watermarks: list[dict], password: str | None = None
+) -> bytes:
     pdf_bytes = Path(pdf_path).read_bytes()
-    if not watermarks:
-        return pdf_bytes
-
     doc = fitz.open("pdf", pdf_bytes)
     try:
-        WatermarkTool.apply_watermarks_to_document(doc, watermarks)
+        if doc.needs_pass:
+            # R5.1: input.pdf is written encrypted; authenticate in-memory so the
+            # printer receives rasterizable (decrypted) bytes. The decryption never
+            # touches disk ? only this in-process save below produces the print bytes.
+            if not password or doc.authenticate(password) == 0:
+                raise PrintingError("???????????????????")
+        elif not watermarks:
+            # Unencrypted, no overlays: hand the captured bytes back verbatim (unchanged).
+            return pdf_bytes
+        if watermarks:
+            WatermarkTool.apply_watermarks_to_document(doc, watermarks)
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
@@ -63,41 +74,45 @@ def _start_heartbeat(
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
-        snapshot_bytes = _build_snapshot_bytes(job.input_pdf_path, job.watermarks)
+        snapshot_bytes = _build_snapshot_bytes(
+            job.input_pdf_path,
+            job.watermarks,
+            password=os.environ.get("PDF_EDITOR_PRINT_PASSWORD"),
+        )
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
diff --git a/src/printing/subprocess_runner.py b/src/printing/subprocess_runner.py
index fb7a904..d4b1783 100644
--- a/src/printing/subprocess_runner.py
+++ b/src/printing/subprocess_runner.py
@@ -23,77 +23,83 @@ logger = logging.getLogger(__name__)
 class PrintSubprocessRunner(QObject):
     """Launch and monitor the helper subprocess."""
 
     progress = Signal(str)
     stalled = Signal()
     succeeded = Signal(object)
     failed = Signal(object)
     finished = Signal()
 
     def __init__(
         self,
         job: PrintHelperJob,
         *,
         process_factory=None,
         python_executable: str | None = None,
         work_dir: str | None = None,
         stall_timeout_ms: int = 30000,
         stall_check_interval_ms: int = 500,
         monotonic: Callable[[], float] = time.monotonic,
         parent: QObject | None = None,
+        helper_password: str | None = None,
     ) -> None:
         super().__init__(parent)
         self.job = job
         self._process_factory = process_factory or QProcess
         self._python_executable = python_executable or sys.executable
         self._provided_work_dir = work_dir
+        # R5.1: handed to the helper via the process environment (in-memory, not job.json)
+        # so it can re-authenticate an encrypted input.pdf for rasterization.
+        self._helper_password = helper_password
         self._owned_temp_dir: tempfile.TemporaryDirectory[str] | None = None
         self._process: QProcess | None = None
         self._stdout_buffer = ""
         self._stderr_buffer = ""
         self._stall_timeout_ms = max(1, int(stall_timeout_ms))
         # Injectable clock: defaults to the real monotonic clock in production;
         # tests pass a controllable fake so stall detection is wall-clock
         # independent (and therefore deterministic under load).
         self._monotonic = monotonic
         self._last_activity = self._monotonic()
         self._termination_requested = False
         self._terminal_event_seen = False
         self._stall_reported = False
         self._finish_handled = False
         self._watchdog = QTimer(self)
         self._watchdog.setInterval(int(stall_check_interval_ms))
         self._watchdog.timeout.connect(self._check_stall)
 
     def _detect_project_root(self) -> Path:
         if getattr(sys, "frozen", False):
             return Path(sys.executable).resolve().parent
         return Path(__file__).resolve().parents[2]
 
     def _build_helper_env(self, project_root: Path) -> dict[str, str]:
         env = dict(os.environ)
         root = str(project_root)
         existing = env.get("PYTHONPATH", "")
         parts = [part for part in existing.split(os.pathsep) if part]
         if root not in parts:
             parts.insert(0, root)
         env["PYTHONPATH"] = os.pathsep.join(parts)
+        if self._helper_password:
+            env["PDF_EDITOR_PRINT_PASSWORD"] = self._helper_password
         return env
 
     def _configure_process_context(
         self,
         process: QProcess,
         *,
         project_root: Path,
         env: dict[str, str],
     ) -> None:
         set_cwd = getattr(process, "setWorkingDirectory", None)
         if callable(set_cwd):
             set_cwd(str(project_root))
         set_env = getattr(process, "setProcessEnvironment", None)
         if callable(set_env):
             process_env = QProcessEnvironment()
             for key, value in env.items():
                 if isinstance(value, str):
                     process_env.insert(key, value)
             set_env(process_env)
 
diff --git a/test_scripts/test_pdf_optimize_workflow.py b/test_scripts/test_pdf_optimize_workflow.py
index eb3edd8..8523987 100644
--- a/test_scripts/test_pdf_optimize_workflow.py
+++ b/test_scripts/test_pdf_optimize_workflow.py
@@ -53,40 +53,55 @@ def _make_pdf_with_many_images(path: Path, image_count: int = 4) -> Path:
     for index in range(image_count):
         image = Image.new("RGB", (48, 48), color=((20 + index * 30) % 255, 120, 220))
         buf = io.BytesIO()
         image.save(buf, format="PNG")
         payload = buf.getvalue()
         page = doc.new_page()
         page.insert_text((72, 72), f"image page {index + 1}", fontsize=12, fontname="helv")
         page.insert_image(fitz.Rect(72, 100, 220, 248), stream=payload)
     doc.save(path)
     doc.close()
     return path
 
 
 def _large_pdf_path(name: str) -> Path:
     path = REPO_ROOT / "test_files" / name
     if not path.exists():
         pytest.skip(f"missing large test PDF: {path}")
     return path
 
 
+def _make_encrypted_pdf(path: Path, user_pw: str, owner_pw: str = "ownerpw") -> Path:
+    doc = fitz.open()
+    page = doc.new_page()
+    page.insert_text((72, 72), "confidential content", fontsize=12, fontname="helv")
+    doc.save(
+        str(path),
+        encryption=fitz.PDF_ENCRYPT_AES_256,
+        owner_pw=owner_pw,
+        user_pw=user_pw,
+        permissions=int(fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY),
+    )
+    doc.close()
+    return path
+
+
 def _pump_events(ms: int = 100) -> None:
     app = QApplication.instance()
     assert app is not None
     end = time.time() + ms / 1000.0
     while time.time() < end:
         app.processEvents()
         time.sleep(0.01)
 
 
 def _wait_until(predicate, timeout_ms: int = 1000) -> bool:
     app = QApplication.instance()
     assert app is not None
     end = time.time() + timeout_ms / 1000.0
     while time.time() < end:
         app.processEvents()
         if predicate():
             return True
         time.sleep(0.01)
     app.processEvents()
     return bool(predicate())
@@ -181,40 +196,82 @@ def test_save_optimized_copy_uses_working_doc_and_preserves_live_doc(tmp_path: P
     source = _make_pdf_with_image(tmp_path / "source.pdf")
     output = tmp_path / "optimized.pdf"
 
     model = PDFModel()
     try:
         model.open_pdf(str(source))
         before_bytes = model.doc.tobytes(no_new_id=1)
 
         result = model.save_optimized_copy(str(output), PdfOptimizeOptions())
 
         after_bytes = model.doc.tobytes(no_new_id=1)
 
         assert output.exists() is True
         assert result.output_path == str(output)
         assert result.optimized_bytes > 0
         assert before_bytes == after_bytes
     finally:
         model.close()
 
 
+def test_save_optimized_copy_preserves_encryption(tmp_path: Path) -> None:
+    """R5.5: optimizing an encrypted PDF must not silently drop password protection.
+
+    Before the fix, the working doc is rebuilt from decrypted ``tobytes`` and saved
+    without encryption, so ????????? of a password-protected PDF produced an
+    unprotected copy. Option A re-applies the session password to the optimized output.
+    """
+    from model.pdf_model import PDFModel
+
+    source = _make_encrypted_pdf(tmp_path / "encrypted-source.pdf", user_pw="secret")
+    output = tmp_path / "encrypted-optimized.pdf"
+
+    model = PDFModel()
+    try:
+        model.open_pdf(str(source), password="secret")
+        model.save_optimized_copy(str(output), model.preset_optimize_options("??"))
+
+        # Fresh handle rejects the wrong password (still locked).
+        wrong = fitz.open(str(output))
+        try:
+            assert wrong.needs_pass, (
+                "optimized copy of an encrypted PDF must remain password-protected"
+            )
+            assert wrong.authenticate("wrong-password") == 0, (
+                "optimized copy must reject an incorrect password"
+            )
+        finally:
+            wrong.close()
+
+        # Fresh handle opens with the original password.
+        reopened = fitz.open(str(output))
+        try:
+            assert reopened.needs_pass
+            assert reopened.authenticate("secret") != 0, (
+                "optimized copy must open with the original password"
+            )
+        finally:
+            reopened.close()
+    finally:
+        model.close()
+
+
 def test_save_optimized_copy_avoids_live_doc_tobytes_for_clean_session(
     tmp_path: Path, monkeypatch
 ) -> None:
     from model.pdf_model import PDFModel, PdfOptimizeOptions
 
     source = _make_pdf_with_image(tmp_path / "clean-source.pdf")
     output = tmp_path / "clean-optimized.pdf"
 
     model = PDFModel()
     try:
         model.open_pdf(str(source))
         original_tobytes = fitz.Document.tobytes
 
         def guarded_tobytes(self, *args, **kwargs):
             if self is model.doc:
                 raise AssertionError("clean file-backed optimize should not serialize the live document")
             return original_tobytes(self, *args, **kwargs)
 
         monkeypatch.setattr(fitz.Document, "tobytes", guarded_tobytes)
 
diff --git a/test_scripts/test_print_encrypted_input.py b/test_scripts/test_print_encrypted_input.py
new file mode 100644
index 0000000..a2f1d31
--- /dev/null
+++ b/test_scripts/test_print_encrypted_input.py
@@ -0,0 +1,163 @@
+"""R5.1 ? the print path must not write a fully decrypted PDF to disk.
+
+`capture_worker_snapshot_bytes()` returns DECRYPTED bytes (PDF_ENCRYPT_NONE), and the
+print worker previously wrote them verbatim to ``work_dir/input.pdf`` ? leaving a fully
+decrypted copy of a password-protected PDF at rest. Option A: the worker re-encrypts the
+temp with the session password before writing, and the password reaches the helper via the
+QProcess *environment* (never job.json / disk); the helper authenticates in-memory so it
+can still rasterize and print.
+"""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+import fitz
+import pytest
+
+from controller.print_coordinator import PrintJobRequest, _PrintSubmissionWorker
+from src.printing.base_driver import PrintJobOptions
+
+
+def _decrypted_bytes(text: str = "confidential") -> bytes:
+    """Bytes as capture_worker_snapshot_bytes would hand them: decrypted, in-memory."""
+    doc = fitz.open()
+    doc.new_page(width=200, height=200).insert_text((20, 40), text, fontsize=12, fontname="helv")
+    try:
+        return doc.tobytes()
+    finally:
+        doc.close()
+
+
+def _make_encrypted_input(path: Path, password: str = "secret") -> None:
+    doc = fitz.open()
+    doc.new_page(width=200, height=200).insert_text((20, 40), "secret", fontsize=12, fontname="helv")
+    doc.save(
+        str(path),
+        encryption=fitz.PDF_ENCRYPT_AES_256,
+        owner_pw=password,
+        user_pw=password,
+        permissions=-1,
+    )
+    doc.close()
+
+
+# ?? the at-rest leak: worker must encrypt the temp ??????????????????????????
+
+
+def test_worker_writes_encrypted_input_when_password_present(tmp_path: Path) -> None:
+    work_dir = tmp_path / "wd"
+    work_dir.mkdir()
+    request = PrintJobRequest(
+        pdf_bytes=_decrypted_bytes(),
+        watermarks=[],
+        options=PrintJobOptions(),
+        job_id="job-1",
+        work_dir=str(work_dir),
+        password="secret",
+    )
+    worker = _PrintSubmissionWorker(request)
+    worker.run()
+
+    input_pdf = work_dir / "input.pdf"
+    assert input_pdf.exists()
+    written = fitz.open(str(input_pdf))
+    try:
+        assert written.needs_pass, (
+            "encrypted print must NOT leave a decrypted PDF at rest in work_dir/input.pdf"
+        )
+        assert written.authenticate("secret") != 0, (
+            "the on-disk temp must open with the session password"
+        )
+    finally:
+        written.close()
+
+
+def test_worker_writes_plain_input_when_no_password(tmp_path: Path) -> None:
+    """Unencrypted print path is unchanged: no password -> plain temp (byte-for-byte)."""
+    work_dir = tmp_path / "wd"
+    work_dir.mkdir()
+    payload = _decrypted_bytes()
+    request = PrintJobRequest(
+        pdf_bytes=payload,
+        watermarks=[],
+        options=PrintJobOptions(),
+        job_id="job-2",
+        work_dir=str(work_dir),
+        password=None,
+    )
+    _PrintSubmissionWorker(request).run()
+
+    input_pdf = work_dir / "input.pdf"
+    assert input_pdf.read_bytes() == payload
+    written = fitz.open(str(input_pdf))
+    try:
+        assert not written.needs_pass
+    finally:
+        written.close()
+
+
+def test_password_never_serialized_into_job_json(tmp_path: Path) -> None:
+    """The password must travel out-of-band: it must not land in the on-disk job payload."""
+    work_dir = tmp_path / "wd"
+    work_dir.mkdir()
+    request = PrintJobRequest(
+        pdf_bytes=_decrypted_bytes(),
+        watermarks=[],
+        options=PrintJobOptions(),
+        job_id="job-3",
+        work_dir=str(work_dir),
+        password="topsecret",
+    )
+    captured: dict = {}
+
+    class _Bridge:
+        def forward_prepared(self, job) -> None:
+            captured["job"] = job
+
+    bridge = _Bridge()  # held: a GC'd slot owner would silently drop the signal
+    worker = _PrintSubmissionWorker(request)
+    worker.prepared.connect(bridge.forward_prepared)
+    worker.run()
+
+    job = captured["job"]
+    assert "topsecret" not in str(job.to_json_dict()), "password must not be in job.json"
+    assert "topsecret" not in str(job.metadata)
+
+
+# ?? the helper must authenticate in-memory so the printer gets renderable bytes ??
+
+
+def test_helper_decrypts_encrypted_input_with_password(tmp_path: Path) -> None:
+    from src.printing.helper_main import _build_snapshot_bytes
+
+    enc = tmp_path / "input.pdf"
+    _make_encrypted_input(enc, password="secret")
+
+    out = _build_snapshot_bytes(str(enc), [], password="secret")
+    doc = fitz.open("pdf", out)
+    try:
+        assert not doc.needs_pass, "helper must hand the printer decrypted, renderable bytes"
+    finally:
+        doc.close()
+
+
+def test_helper_raises_on_encrypted_input_without_password(tmp_path: Path) -> None:
+    from src.printing.helper_main import _build_snapshot_bytes
+
+    enc = tmp_path / "input.pdf"
+    _make_encrypted_input(enc, password="secret")
+
+    with pytest.raises(Exception):
+        _build_snapshot_bytes(str(enc), [], password=None)
+
+
+def test_helper_unencrypted_input_unchanged(tmp_path: Path) -> None:
+    """No-watermark, unencrypted input still returns the raw bytes verbatim."""
+    from src.printing.helper_main import _build_snapshot_bytes
+
+    plain = tmp_path / "input.pdf"
+    plain.write_bytes(_decrypted_bytes())
+
+    out = _build_snapshot_bytes(str(plain), [], password=None)
+    assert out == plain.read_bytes()
diff --git a/test_scripts/test_security_packaging.py b/test_scripts/test_security_packaging.py
new file mode 100644
index 0000000..557bd38
--- /dev/null
+++ b/test_scripts/test_security_packaging.py
@@ -0,0 +1,121 @@
+"""R5.4 ? packaging guard: dev/test/CUA trees must never ship in a built artifact.
+
+`scripts/` is a real package (`scripts/__init__.py` exists) and holds the CUA sign-off
+harness that drives the real keyboard/mouse via pyautogui ? it must never be distributed.
+`test_scripts/` is not a package (no leak into the wheel) but would ride along in an sdist
+without the MANIFEST prunes.
+
+Two governing mechanisms, guarded here:
+  * wheel  -> `[tool.setuptools.packages.find].include` allow-list in pyproject.toml
+  * sdist  -> `prune` directives in MANIFEST.in
+
+The teeth of the real-build guard were verified out-of-band: adding `scripts*` to the
+discovery allow-list leaks 10 `scripts/` members into the wheel, which `_offending_members`
+flags. See refactor-state.md (R5.4) for the experiment.
+"""
+
+from __future__ import annotations
+
+import shutil
+import subprocess
+import sys
+import zipfile
+from pathlib import Path
+
+import pytest
+
+REPO_ROOT = Path(__file__).resolve().parents[1]
+
+# Prefixes that must never appear in a distributable artifact's member list.
+_DEV_TREES = ("scripts/", "test_scripts/")
+
+
+def _offending_members(names: list[str]) -> list[str]:
+    return sorted(n for n in names if n.startswith(_DEV_TREES))
+
+
+def _load_pyproject() -> dict:
+    try:
+        import tomllib  # Python 3.11+
+    except ModuleNotFoundError:
+        try:
+            import tomli as tomllib  # type: ignore[no-redef]
+        except ModuleNotFoundError:
+            pytest.skip("no TOML parser (tomllib/tomli) available")
+    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
+
+
+# ?? the predicate has teeth (the negative case the guards rely on) ???????????
+
+
+def test_offending_predicate_flags_dev_trees() -> None:
+    names = [
+        "model/pdf_model.py",
+        "scripts/__init__.py",
+        "controller/pdf_controller.py",
+        "test_scripts/test_x.py",
+        "src/printing/helper_main.py",
+    ]
+    assert _offending_members(names) == ["scripts/__init__.py", "test_scripts/test_x.py"]
+
+
+# ?? wheel discovery is an allow-list (omission excludes scripts/test_scripts) ?
+
+
+def test_pyproject_wheel_discovery_is_allowlist() -> None:
+    data = _load_pyproject()
+    include = data["tool"]["setuptools"]["packages"]["find"]["include"]
+    assert isinstance(include, list) and include, "packages.find.include must be a non-empty allow-list"
+    # No discovery pattern may match a dev/test tree.
+    for pattern in include:
+        head = pattern.rstrip("*").rstrip(".")
+        assert not head.startswith(("scripts", "test_scripts", "docs")), (
+            f"discovery pattern {pattern!r} would ship a dev/test tree"
+        )
+    # The production packages must still be discoverable (guards an over-prune regression).
+    assert any(p.startswith("controller") for p in include)
+    assert any(p.startswith("model") for p in include)
+
+
+# ?? sdist prunes the dev/test/doc trees ??????????????????????????????????????
+
+
+def test_manifest_prunes_dev_trees() -> None:
+    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
+    pruned = {line.split(None, 1)[1].strip().rstrip("/") for line in manifest if line.strip().startswith("prune ")}
+    assert "scripts" in pruned, "MANIFEST.in must `prune scripts` (the CUA harness)"
+    assert "test_scripts" in pruned, "MANIFEST.in must `prune test_scripts`"
+
+
+# ?? real artifact: build the wheel and assert no dev tree shipped ????????????
+
+
+def test_built_wheel_excludes_dev_trees(tmp_path: Path) -> None:
+    """Best-effort real build. Skips (does not fail) if the build backend/network
+    is unavailable, so an offline runner degrades to the hermetic config guards above."""
+    try:
+        result = subprocess.run(
+            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(tmp_path)],
+            cwd=str(REPO_ROOT),
+            capture_output=True,
+            text=True,
+            timeout=300,
+        )
+    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - env dependent
+        pytest.skip(f"wheel build could not run: {exc}")
+
+    # setuptools writes build/ into the project root (gitignored); keep the tree tidy.
+    shutil.rmtree(REPO_ROOT / "build", ignore_errors=True)
+
+    if result.returncode != 0:
+        pytest.skip(f"wheel build unavailable (rc={result.returncode}): {result.stderr.strip()[-300:]}")
+
+    wheels = list(tmp_path.glob("*.whl"))
+    assert wheels, "pip wheel reported success but produced no .whl"
+    with zipfile.ZipFile(wheels[0]) as zf:
+        names = zf.namelist()
+
+    offending = _offending_members(names)
+    assert not offending, f"dev/test trees leaked into the built wheel: {offending}"
+    # Sanity: the production packages are actually present.
+    assert any(n.startswith("model/") for n in names), "wheel is missing the model package"

--- END UNTRUSTED STDIN ---
