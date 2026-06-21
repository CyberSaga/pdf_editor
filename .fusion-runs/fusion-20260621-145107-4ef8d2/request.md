# Trusted Task

Review this R5 changed-lines-only diff for concrete introduced correctness/security/resource/packaging bugs. Trace encrypted PDF access-control semantics, failure atomicity, password lifetime/inheritance, process/thread cleanup, and guard false negatives. Reject nits, pre-existing issues, and confidence below 80. Give exact file/line, trigger, impact, fix, and reproduction.

# Untrusted Context

--- BEGIN UNTRUSTED STDIN ---
diff --git a/controller/print_coordinator.py b/controller/print_coordinator.py
index c7fd673..2300ce3 100644
--- a/controller/print_coordinator.py
+++ b/controller/print_coordinator.py
@@ -19,0 +20 @@ from __future__ import annotations
+import io
@@ -27,0 +29 @@ from typing import TYPE_CHECKING
+import fitz
@@ -58,0 +61,5 @@ class PrintJobRequest:
+    # R5.1: when the source is password-protected, the captured bytes are decrypted
+    # (capture_worker_snapshot_bytes uses PDF_ENCRYPT_NONE). The worker re-encrypts the
+    # on-disk temp with this password so no plaintext copy lands at rest; the password
+    # itself travels to the helper out-of-band (process env), never in this payload.
+    password: str | None = None
@@ -75 +82 @@ class _PrintSubmissionWorker(QObject):
-            input_pdf_path.write_bytes(self._request.pdf_bytes)
+            input_pdf_path.write_bytes(self._encode_input_bytes())
@@ -88,0 +96,28 @@ class _PrintSubmissionWorker(QObject):
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
@@ -134,0 +170,3 @@ class PrintCoordinator:
+        # R5.1: session password for an encrypted in-flight job, handed to the helper
+        # via the subprocess environment (never job.json). Cleared once the job is idle.
+        self._print_password: str | None = None
@@ -235,0 +274,5 @@ class PrintCoordinator:
+        # R5.1: capture_worker_snapshot_bytes decrypts; if the source needs a password,
+        # carry it so the worker re-encrypts the on-disk temp and the helper can re-auth.
+        doc = getattr(self._c.model, "doc", None)
+        password = self._c.model.password if doc is not None and getattr(doc, "needs_pass", False) else None
+        self._print_password = password
@@ -241,0 +285 @@ class PrintCoordinator:
+            password=password,
@@ -261 +305,6 @@ class PrintCoordinator:
-        return PrintSubprocessRunner(job, work_dir=work_dir, parent=self._c.view)
+        return PrintSubprocessRunner(
+            job,
+            work_dir=work_dir,
+            parent=self._c.view,
+            helper_password=self._print_password,
+        )
@@ -333,0 +383,2 @@ class PrintCoordinator:
+        # R5.1: drop the in-flight session password once no job references it.
+        self._print_password = None
diff --git a/model/pdf_optimizer.py b/model/pdf_optimizer.py
index 6971c79..dde3492 100644
--- a/model/pdf_optimizer.py
+++ b/model/pdf_optimizer.py
@@ -801,0 +802,60 @@ def save_optimized_working_doc(
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
@@ -834,0 +895,3 @@ def save_optimized_copy(
+        # R5.5: an encrypted source is rebuilt from decrypted bytes above; re-apply the
+        # session password so the optimized copy stays password-protected (no-op otherwise).
+        reapply_source_encryption(model, new_path)
diff --git a/src/printing/helper_main.py b/src/printing/helper_main.py
index cea1814..5c020dc 100644
--- a/src/printing/helper_main.py
+++ b/src/printing/helper_main.py
@@ -6,0 +7 @@ import json
+import os
@@ -16,0 +18 @@ from .dispatcher import PrintDispatcher
+from .errors import PrintingError
@@ -25 +27,3 @@ from .messages import (
-def _build_snapshot_bytes(pdf_path: str, watermarks: list[dict]) -> bytes:
+def _build_snapshot_bytes(
+    pdf_path: str, watermarks: list[dict], password: str | None = None
+) -> bytes:
@@ -27,3 +30,0 @@ def _build_snapshot_bytes(pdf_path: str, watermarks: list[dict]) -> bytes:
-    if not watermarks:
-        return pdf_bytes
-
@@ -32 +33,11 @@ def _build_snapshot_bytes(pdf_path: str, watermarks: list[dict]) -> bytes:
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
@@ -83 +94,5 @@ def run_print_helper(
-        snapshot_bytes = _build_snapshot_bytes(job.input_pdf_path, job.watermarks)
+        snapshot_bytes = _build_snapshot_bytes(
+            job.input_pdf_path,
+            job.watermarks,
+            password=os.environ.get("PDF_EDITOR_PRINT_PASSWORD"),
+        )
diff --git a/src/printing/subprocess_runner.py b/src/printing/subprocess_runner.py
index fb7a904..d4b1783 100644
--- a/src/printing/subprocess_runner.py
+++ b/src/printing/subprocess_runner.py
@@ -42,0 +43 @@ class PrintSubprocessRunner(QObject):
+        helper_password: str | None = None,
@@ -48,0 +50,3 @@ class PrintSubprocessRunner(QObject):
+        # R5.1: handed to the helper via the process environment (in-memory, not job.json)
+        # so it can re-authenticate an encrypted input.pdf for rasterization.
+        self._helper_password = helper_password
@@ -79,0 +84,2 @@ class PrintSubprocessRunner(QObject):
+        if self._helper_password:
+            env["PDF_EDITOR_PRINT_PASSWORD"] = self._helper_password
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
