### 1. PyMuPDF `save()` File-Like Object API Misuse (Crash)

* **File/Line**: `controller/print_coordinator.py`, lines 112–119 (inside `_encode_input_bytes`).
* **Trigger**: Initiating a print job on any password-protected PDF.
* **Impact**: PyMuPDF's `Document.save()` method only accepts a file path string or a `pathlib.Path` object as its first argument; it does not support Python file-like objects like `io.BytesIO`. Passing `buffer` causes a `TypeError` and crashes the print submission worker thread, preventing the document from being printed.
* **Fix**: Use `src.tobytes()` (or `src.write()`) which returns the saved PDF data directly as a `bytes` object in memory:
  ```python
  def _encode_input_bytes(self) -> bytes:
      pdf_bytes = self._request.pdf_bytes
      password = self._request.password
      if not password:
          return pdf_bytes
      src = fitz.open("pdf", pdf_bytes)
      try:
          return src.tobytes(
              encryption=fitz.PDF_ENCRYPT_AES_256,
              owner_pw=password,
              user_pw=password,
              garbage=0,
          )
      finally:
          src.close()
  ```
* **Reproduction**: 
  1. Open a password-protected PDF in the application.
  2. Request a print submission.
  3. Observe the print submission worker thread crash with a `TypeError` on `src.save()`.

---

### 2. Missing Imports in PDF Optimizer (Crash)

* **File/Line**: `model/pdf_optimizer.py`, lines 846–859 (inside `reapply_source_encryption`).
* **Trigger**: Optimizing a password-protected PDF copy.
* **Impact**: The helper function `reapply_source_encryption` uses `uuid`, `os`, and `Path` (from `pathlib`), but these packages/symbols are not imported in the scope of `model/pdf_optimizer.py`. This will raise a `NameError` and crash the application when trying to save the optimized copy of an encrypted PDF.
* **Fix**: Add the missing imports to the top of `model/pdf_optimizer.py`:
  ```python
  import os
  import uuid
  from pathlib import Path
  ```
* **Reproduction**:
  1. Open a password-protected PDF.
  2. Save an optimized copy of it.
  3. Observe a `NameError: name 'uuid' is not defined` traceback.

---

### 3. Orphaned Temporary Files on Save Failure (Resource Leak)

* **File/Line**: `model/pdf_optimizer.py`, lines 847–859 (inside `reapply_source_encryption`).
* **Trigger**: A failure or exception (e.g., disk full, permission denied) occurring during `reopened.save(str(temp_enc), ...)` or before `os.replace`.
* **Impact**: If `reopened.save` throws an exception, the partially written temporary file at `temp_enc` remains on disk indefinitely, cluttering the user's directory.
* **Fix**: Wrap the temporary file manipulation inside a try-finally block to clean it up in case of failure:
  ```python
  try:
      reopened = fitz.open(output_path)
      try:
          reopened.save(
              str(temp_enc),
              encryption=method,
              owner_pw=password,
              user_pw=password,
              permissions=permissions,
          )
      finally:
          reopened.close()
      os.replace(str(temp_enc), output_path)
  except Exception:
      if temp_enc.exists():
          try:
              temp_enc.unlink()
          except OSError:
              pass
      raise
  ```
* **Reproduction**:
  1. Force `reopened.save` to fail (e.g. by simulating an environment failure or low disk space).
  2. Note that the generated `.pdf_enc_*.pdf` file remains in the directory.