# R5-01 — Fileless Print Path

**Status: DRAFT — awaiting user sign-off before any implementation.**

---

## 1. Goal

Eliminate the transient plaintext temp file that currently lands on disk during
every print job. Today, decrypted PDF bytes are written to a
`NamedTemporaryFile` on disk, handed to the driver as a path, and deleted in a
`finally` block. This creates a window where unencrypted document content is
recoverable from the filesystem (and, on Windows, from the NTFS journal even
after unlink). The fix: pass bytes through memory so no plaintext file is ever
created.

A secondary goal (from the TODOS entry): avoid the duplicate full-document
copies that the current pipeline produces (snapshot bytes → temp file → driver
re-reads the temp file and rasterises from it).

---

## 2. Current behavior (verified against HEAD `758966f`)

### 2.1 The two temp-file sites

**Site A — `PrintDispatcher.print_pdf_bytes`** (`src/printing/dispatcher.py:106-117`).
Called by the helper subprocess after `_build_snapshot_bytes` produces the
print-ready bytes. Writes them to a `NamedTemporaryFile(delete=False,
suffix=".pdf")`, calls `self.print_pdf_file(temp_path, options)`, and unlinks
in a `finally`. This is the direct exposure: plaintext bytes at rest for the
duration of the driver call.

**Site B — `_PrintSubmissionWorker._encode_input_bytes` →
`input_pdf_path.write_bytes`** (`controller/print_coordinator.py:81-82`).
The coordinator's worker thread writes `work_dir/input.pdf` from the captured
snapshot. For password-protected sources this is re-encrypted (R5.1,
`_encode_input_bytes` at line 96-122), but for **unprotected sources** the bytes
are written as-is — plaintext at rest in the temp work dir. The helper reads
this path later.

### 2.2 Full data flow (print button → spooler)

```
User clicks Print
  → PrintCoordinator._start_print_submission (line 260)
    → model.capture_print_snapshot_bytes()            [in-memory, decrypted]
    → QThread: _PrintSubmissionWorker.run()
      → _encode_input_bytes()                         [re-encrypts if password]
      → writes work_dir/input.pdf                     ← SITE B (temp #1)
      → emits prepared(PrintHelperJob)
  → PrintCoordinator._on_print_job_prepared (line 314)
    → PrintSubprocessRunner.start()
      → launches `python -m src.printing.helper_main job.json`
        → helper_main._build_snapshot_bytes()
          → reads input.pdf back into memory
          → decrypts if needed (env password)
          → applies watermarks
        → dispatcher.print_pdf_bytes(snapshot_bytes)
          → NamedTemporaryFile → writes bytes          ← SITE A (temp #2)
          → print_pdf_file(temp_path)
            → driver.print_pdf(temp_path, ...)
              → PDFRenderer.iter_page_images(temp_path) reads file again
              → raster_print_pdf draws pages to QPrinter
          → unlinks temp                               ← finally cleanup
    → SubprocessRunner cleans up work_dir              ← removes temp #1
```

**Copy count for an unprotected document:** snapshot bytes (copy 1) → written to
`input.pdf` (copy 2, disk) → read back by helper (copy 3, memory) → written to
temp (copy 4, disk) → read by renderer (copy 5, memory). Three of these five
stops are redundant.

### 2.3 Who consumes the file path

Every driver's `print_pdf` takes `pdf_path: str`. Downstream consumers:

| Consumer | File | What it does with the path |
|---|---|---|
| `PDFRenderer.iter_page_images` | `pdf_renderer.py:65` | `fitz.open(pdf_path)` → streams page rasters |
| `PDFRenderer.get_page_count` | `pdf_renderer.py:41` | `fitz.open(pdf_path)` → `len(doc)` |
| `LinuxPrinterDriver._submit_via_cups` | `linux_driver.py:171` | `conn.printFile(printer, pdf_path, ...)` — CUPS reads the file directly |
| `LinuxPrinterDriver._submit_via_lp` | `linux_driver.py:208` | `subprocess.run([lp, ..., pdf_path])` — lp reads the file directly |
| `WindowsPrinterDriver._split_by_layout` | `win_driver.py:398` | `fitz.open(pdf_path)` for geometry classification |

The Windows raster path (`raster_print_pdf → iter_page_images`) and the
geometry classifier both use `fitz.open(path)`. These can trivially accept
`fitz.open("pdf", bytes)` instead. **The Linux/macOS CUPS and lp direct-PDF
paths genuinely need a file** — `conn.printFile` and the `lp` CLI both take a
filesystem path. These are the hard cases.

---

## 3. Affected modules

| Module | Change type |
|---|---|
| `src/printing/dispatcher.py` | Major — new `print_pdf_bytes` that streams bytes, not file |
| `src/printing/pdf_renderer.py` | Medium — accept bytes or path (`fitz.open` from memory) |
| `src/printing/qt_bridge.py` | Medium — `raster_print_pdf` accepts bytes, not just path |
| `src/printing/base_driver.py` | Interface — `print_pdf` gains a bytes overload or new method |
| `src/printing/platforms/win_driver.py` | Medium — thread bytes through split-by-layout |
| `src/printing/platforms/linux_driver.py` | Hard — CUPS/lp need a file; scope the temp to those |
| `src/printing/helper_main.py` | Medium — pipe bytes directly to dispatcher, skip temp |
| `controller/print_coordinator.py` | Medium — skip `input.pdf` disk write; pass bytes to helper |
| `src/printing/subprocess_runner.py` | Potentially medium — bytes-over-stdin instead of file path |
| `src/printing/helper_protocol.py` | Medium — job payload carries bytes or stdin protocol |
| `test_scripts/test_print_dispatcher_real_sink.py` | Rewrite — current test pins the temp-file contract |
| `test_scripts/test_security_dispatcher_temp_cleanup.py` | Rewrite or delete — tests temp cleanup |

---

## 4. Design approach

### 4.1 Core principle: bytes-first, file-on-demand

Invert the current flow. The happy path passes `bytes` through the entire
pipeline in memory. Only the Linux/macOS direct-PDF path (CUPS `printFile` /
`lp` CLI) materialises a file, and it does so as late as possible, in the
narrowest scope possible, with the shortest lifetime possible.

### 4.2 Layer changes (bottom-up)

**PDFRenderer** — add `iter_page_images_from_bytes(pdf_bytes, page_indices, dpi)`
alongside the existing path-based method. Internally: `fitz.open("pdf",
pdf_bytes)`. The path-based method becomes a thin wrapper that reads the file
and delegates.

**PrinterDriver contract** — add `print_pdf_from_bytes(pdf_bytes, page_indices,
options)` as a default-implemented method on `PrinterDriver` (default: write
temp, call `print_pdf`, clean up — i.e. the current behavior, so unchanged
drivers work). Drivers that can go fileless override it.

**WindowsPrinterDriver** — override `print_pdf_from_bytes` to thread bytes
through `_split_by_layout` → `raster_print_pdf` without ever touching disk.
The geometry classifier uses `fitz.open("pdf", bytes)`.

**LinuxPrinterDriver** — for the raster fallback path, override
`print_pdf_from_bytes` the same way (bytes → raster → QPrinter, no file).
For the CUPS/lp direct path, materialise a temp file scoped tightly:
`with NamedTemporaryFile(...) as f: ... conn.printFile(f.name)`. This is the
**only** remaining temp, and it's unavoidable (external tool limitation). For
encrypted sources, re-encrypt the temp.

**PrintDispatcher.print_pdf_bytes** — call
`driver.print_pdf_from_bytes(pdf_bytes, page_indices, options)` directly.
No temp file in the dispatcher.

**helper_main** — `_build_snapshot_bytes` already returns `bytes`. Pipe them
directly to `dispatcher.print_pdf_bytes` (already happens today at line 100).
The remaining change: **don't read from `input.pdf`** — receive bytes via stdin
or shared-memory instead of a file path.

**PrintSubprocessRunner / PrintCoordinator** — instead of writing `input.pdf`
and passing its path via `job.json`, pipe the snapshot bytes to the helper
subprocess via stdin. The `PrintHelperJob` drops `input_pdf_path` in favour of
a `bytes_on_stdin: bool` flag. For encrypted sources, the bytes are
re-encrypted in memory before piping (same as `_encode_input_bytes` today, just
without the disk write).

### 4.3 What about CUPS/lp?

These external tools require a real file. The temp is scoped inside the driver
method, exists only for the duration of the `printFile` / `subprocess.run`
call, and is unlinked in a `finally`. For encrypted sources, the temp is
re-encrypted before write (the driver receives the password via the same
env-var mechanism). This is a strictly smaller exposure than today (one temp
instead of two, driver-scoped instead of dispatcher-scoped).

---

## 5. Step list (PR sequence)

### Step 1 — PDFRenderer bytes-from-memory support

**PR scope:** `PDFRenderer` gains `iter_page_images_from_bytes` and
`get_page_count_from_bytes`. Existing path-based methods unchanged (callers
migrate later). Pure addition, no behavior change.

**Files:** `src/printing/pdf_renderer.py`, new tests in
`test_scripts/test_print_renderer_bytes.py`.

**Tests:** Render a synthesized PDF from bytes, compare page count and image
dimensions against the path-based method on the same PDF. Edge case: empty
bytes, corrupt bytes.

### Step 2 — `raster_print_pdf` bytes overload + Windows/Linux raster path

**PR scope:** `raster_print_pdf` accepts `pdf_source: str | bytes` (path or
bytes). `WindowsPrinterDriver` and `LinuxPrinterDriver` raster paths thread
bytes through without touching disk. `PrinterDriver` base gains
`print_pdf_from_bytes` with a default file-writing fallback.

**Files:** `src/printing/qt_bridge.py`, `src/printing/base_driver.py`,
`src/printing/platforms/win_driver.py`, `src/printing/platforms/linux_driver.py`,
`src/printing/platforms/mac_driver.py`, tests.

**Tests:** Existing `test_qt_bridge_layout.py` extended to exercise the bytes
path. New test: Windows split-by-layout with bytes input (mock raster, verify
no temp created). Linux raster fallback with bytes (same).

**STOP POINT:** After this PR, the raster path is fileless on Windows and
Linux. The CUPS/lp direct path and the coordinator→helper pipeline still use
files. Pause for review — this is the highest-risk change (touches the hot
spooler path).

### Step 3 — Linux CUPS/lp driver-scoped temp

**PR scope:** `LinuxPrinterDriver.print_pdf_from_bytes` — for the CUPS/lp
direct path only, materialises a `NamedTemporaryFile` inside the driver method
(not the dispatcher). Scoped with `with` + `finally` unlink. Re-encrypts if a
password is supplied (new `password` kwarg on `print_pdf_from_bytes`, threaded
from the job).

**Files:** `src/printing/platforms/linux_driver.py`, tests.

**Tests:** Recording-driver test that the temp exists only during `printFile` /
`lp` and is gone after. Test that the temp carries re-encrypted bytes when a
password is provided.

### Step 4 — Dispatcher goes fileless

**PR scope:** `PrintDispatcher.print_pdf_bytes` calls
`driver.print_pdf_from_bytes(pdf_bytes, ...)` instead of writing a temp and
calling `print_pdf_file`. `print_pdf_file` stays for backward compat (external
callers, preview dialog) but the internal bytes path no longer touches it.

**Files:** `src/printing/dispatcher.py`,
`test_scripts/test_security_dispatcher_temp_cleanup.py` (rewritten — the temp
is gone on the happy path; the test now asserts *no* temp is created),
`test_scripts/test_print_dispatcher_real_sink.py` (rewritten — pin the new
fileless contract).

**Tests:** The rewritten sink test uses a recording driver to prove no temp
path is ever created in the bytes path. The old temp-cleanup test is replaced
by a "no temp at all" assertion.

### Step 5 — Coordinator→helper bytes-over-stdin

**PR scope:** The coordinator passes snapshot bytes to the helper subprocess
via stdin instead of writing `work_dir/input.pdf`. The helper reads from stdin
when `input_pdf_path` is absent or a sentinel value. `PrintHelperJob` protocol
updated. `_PrintSubmissionWorker` no longer writes to disk.

**Files:** `controller/print_coordinator.py`, `src/printing/subprocess_runner.py`,
`src/printing/helper_main.py`, `src/printing/helper_protocol.py`, tests.

**Tests:** Helper-main test with bytes piped via a mock stdin. Coordinator
integration test verifying no `input.pdf` is created in the work dir.
Encrypted-source test: bytes are re-encrypted in memory before piping, helper
decrypts from stdin.

**STOP POINT:** After this PR, the full print path is fileless for the raster
route. Only CUPS/lp direct creates a driver-scoped temp. Pause for manual
printer validation: print a multi-page document on a real Windows printer and
a real (or virtual) CUPS printer.

### Step 6 — Cleanup and docs

**PR scope:** Remove dead code paths (if any). Update `docs/PITFALLS.md` with
the new architecture. Update `TODOS.md` to mark R5-01 complete. Regenerate
pitfalls index. Update `docs/ARCHITECTURE.md` printing section.

**Files:** Docs, `TODOS.md`, `docs/PITFALLS.md`, `docs/ARCHITECTURE.md`.

---

## 6. Test strategy

### 6.1 Red-light tests (per CLAUDE.md §5.1)

Each step writes failing tests first. Key red-light scenarios:

- **Step 1:** `test_iter_page_images_from_bytes_matches_path` — fails before
  `iter_page_images_from_bytes` exists (AttributeError).
- **Step 2:** `test_raster_print_no_temp_file_created` — recording driver
  asserts no temp in `tempfile.gettempdir()` during the call; fails while
  `raster_print_pdf` still requires a path.
- **Step 4:** `test_dispatcher_bytes_path_creates_no_temp` — fails while the
  dispatcher still writes a temp.
- **Step 5:** `test_helper_reads_from_stdin_not_file` — fails while the helper
  still expects `input_pdf_path`.

### 6.2 Regression guards

- All existing print tests must keep passing (the path-based APIs remain).
- `test_print_encrypted_input.py` — must still work (encrypted path).
- `test_print_controller_flow.py` — coordinator flow unchanged from outside.
- `test_win_print_fixes.py` — Windows split-by-layout still works.
- `test_linux_driver_overrides.py` — Linux driver decisions unchanged.

### 6.3 Manual validation (Step 5 stop point)

- Print a multi-page mixed-orientation PDF on a real Windows printer.
- Print a PDF to a virtual CUPS printer (cups-pdf or similar).
- Print an encrypted PDF (password-protected source).
- Verify no orphan temp files remain in `%TEMP%` / `/tmp` after each print.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Memory pressure for large PDFs.** Bytes in memory instead of on disk means the full PDF lives in the process address space. | Medium | Already the case — `capture_print_snapshot_bytes` returns all bytes into memory today. The change removes one disk copy, not an in-memory copy. Net memory impact: neutral. |
| **Subprocess stdin pipe limits.** Windows has a 4 KB default pipe buffer; large PDFs could deadlock if the child doesn't read fast enough. | High | Use `QProcess.write()` in chunks with flow control (wait for `bytesWritten` signal). Or: write to stdin from the worker thread, not the GUI thread. The helper reads all of stdin before processing. Test with a 50+ MB PDF. |
| **CUPS/lp temp file still exists.** The Linux direct path unavoidably writes a temp. | Low | Strictly smaller exposure than today. Scoped inside the driver, not the dispatcher. Document as a known residual in PITFALLS.md. |
| **Breaking the helper subprocess protocol.** Changing from file-path to stdin is a protocol break. | Medium | The helper is internal (not a public API). Version the protocol: if `input_pdf_path` is present in `job.json`, use it; if absent, read stdin. Allows rollback. |
| **Windows GDI spooler regression.** Threading bytes instead of a path through the split-by-layout code path. | Medium | The split-by-layout code only uses `fitz.open(pdf_path)` for geometry classification. `fitz.open("pdf", bytes)` is well-tested in this codebase (used by the model everywhere). The raster path is unchanged — `iter_page_images_from_bytes` is a trivial wrapper. |
| **QPrinter lifecycle.** Qt's `QPrinter` with `HighResolution` may behave differently when the source is no longer a file path. | Low | `QPrinter` never sees the source — it receives `QImage` pages from the renderer. The source format is invisible to it. |

---

## 8. Stop points (explicit sign-off gates)

1. **After Step 2** — raster path is fileless. Review before touching the
   coordinator/helper protocol. This is the "can we ship just this?" checkpoint:
   if the stdin approach (Step 5) proves too risky, Step 2 alone already
   eliminates the dispatcher temp for the Windows raster path (the majority
   case for this app's users).

2. **After Step 5** — full pipeline is fileless (except CUPS/lp residual).
   Manual printer validation required before merging to main.

---

## 9. Out of scope

- **CUPS/lp fileless path.** Would require CUPS to support `printFile` from a
  file descriptor or memory buffer. Not available in the Python `cups` bindings.
  Documented as a known residual.
- **Eliminating the subprocess entirely.** The helper subprocess exists to
  isolate the print spooler from the main process (crash isolation). Removing
  it is a separate architectural decision.
- **Codex F6 (worker decrypted-bytes lifetime).** Separate TODOS item; not
  addressed here.

---

## 10. Open questions (for sign-off discussion)

1. **Stdin vs. shared memory vs. memory-mapped file.** Stdin is the simplest
   cross-platform approach but has pipe-buffer risks on Windows. An alternative:
   a memory-mapped file (still a file, but never plaintext — encrypted in the
   mapping). Or: pass bytes via a named pipe / Unix domain socket. Leaning
   stdin for simplicity — the pipe-buffer risk is manageable with chunked
   writes. What's your preference?

2. **Should Step 2 land as its own PR, or bundle Steps 1+2?** Step 1 is pure
   addition (no behavior change); bundling reduces PR count but makes the diff
   larger. Leaning bundle (the renderer change is small and Step 2 needs it
   immediately).

3. **Re-encryption of the CUPS/lp residual temp.** For encrypted sources, should
   the driver-scoped temp be re-encrypted (matching the current R5.1 behavior)?
   This adds complexity to the driver. Leaning yes — defense in depth; the
   encryption code already exists in `_encode_input_bytes`.
