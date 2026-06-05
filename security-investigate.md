I'll conduct a thorough defensive security review of this PDF editor project. Let me start by mapping the codebase structure and reading the key files.

Let me search for the high-risk security sinks across the source code (excluding the venv and dependencies).

Let me read the core application files most relevant to security: entry point, printing subprocess, OCR, single-instance, and helpers.

Now let me read the OCR tool, single-instance, helpers, Windows driver subprocess, and headless merge.

Let me examine the watermark embedding (potential deserialization), the Windows driver subprocess, requirements, and README.

Let me read the requirements, README, watermark rendering, and the controller's file-handling methods.

Let me look at the file dialog flows and save/export sinks in the controller and view, plus the PDF model's open/save.

Let me check the Linux print driver subprocess, drag-and-drop handling, Pillow decompression-bomb settings, and the controller's open/forward flows.

Let me examine the drag-and-drop path extraction and the controller's `open_pdf`/forwarded-path handling.

Let me read the controller's `open_pdf`, the model's open/load logic, and the optimizer image-transcode worker (decompression-bomb surface).

Let me check the optimizer's parallel image worker (multiprocessing/pickle surface) and the controller's print temp-dir setup.

Let me check for hardcoded secrets, the PyInstaller/build setup, run.bat, and the agent scripts (LLM/CUA surface).

Let me quickly characterize the agent/LLM surface in the dev scripts and confirm whether they touch the shipped app.

Let me confirm how the Windows driver submits the actual print job (to rule out shell-based printing) and check the page-range parser for integer-DoS.

I've completed a thorough read of the attack surface (entry points, file I/O, subprocess, OCR/ML, IPC, printing, and dependencies). No code was modified. Here is the complete vulnerability report.

---

# Defensive Security Code Review — CyberSaga/pdf_editor

**Scope reviewed:** `main.py`, `controller/`, `model/`, `model/tools/`, `src/printing/` (incl. `platforms/`), `utils/`, `view/` (I/O paths), `scripts/` (dev harness), `requirements.txt`, `optional-requirements.txt`, CLAUDE.md, CODEINDEX.md.
**Method:** Sink-first grep sweep (subprocess/eval/pickle/yaml/ctypes/import/tempfile/file-write) → data-flow tracing from UI/drag-drop/CLI/IPC/OCR/print to the underlying file & process sinks → per-sink validation review.

## Executive Summary

This is a **local desktop application with no listening network service, no `eval`/`exec`, no `pickle`/`yaml`/`marshal` of untrusted data, no `shell=True`, and no string-concatenated commands.** All subprocess calls use argument-vector form, and all persisted metadata (watermarks, print jobs) uses JSON, not Python serialization. File save/export paths are operator-chosen through native dialogs. **I found no Critical or High remotely-exploitable RCE.** Per your instruction, I am not inflating severities.

The realistic risk concentrates in two places: (1) **untrusted-PDF resource exhaustion / native-parser exposure** because the app feeds attacker-supplied PDFs straight into PyMuPDF/Pillow with no size, page, or dimension guards, and (2) **dependency hygiene** — every dependency is an unpinned lower bound (`>=`), including image/PDF parsers with a CVE history (Pillow, PyMuPDF/MuPDF). A separate, clearly-scoped **dev-only computer-use agent** (`scripts/ux_signoff_agent.py`) executes unbounded model-proposed desktop actions and is the one genuine AI/agent surface.

Severity tally: **0 Critical, 0 High, 4 Medium, 5 Low, 1 Informational.**

---

## 1. Attack Surface Inventory

| # | Entry point | Location | Trust | Reaches sink |
|---|---|---|---|---|
| A1 | CLI args `files`, `--merge OUTPUT` | `main.py:14-39` | operator | `fitz.open`, `merged.save` |
| A2 | Drag-and-drop URLs | `view/pdf_view.py:624-709` | **untrusted file content** | `model.open_pdf` → `fitz.open` |
| A3 | File-open dialog | `view/pdf_view.py:4490-4506` | **untrusted file content** | `fitz.open` |
| A4 | Single-instance IPC (`{"argv":[...]}`) | `utils/single_instance.py:93-208` | local peer (no auth) | `controller.open_pdf` |
| A5 | Merge / insert sources | `controller/pdf_controller.py:1084-1260`, `model/headless_merge.py` | **untrusted** | `insert_pdf`, `save` |
| A6 | Export pages → PDF/image | `model/pdf_model.py:1113-1174` | operator path / untrusted content | `pix.save`, `pix.pil_save`, `new_doc.save` |
| A7 | Save / Save-as / optimize | `model/pdf_model.py:4692-4919`, `model/pdf_optimizer.py:751-808` | operator path | temp + `os.replace`/`shutil.move` |
| A8 | OCR | `model/tools/ocr_tool.py` | untrusted page raster + remote weights | surya/torch, `importlib` |
| A9 | Watermark embed/load | `model/tools/watermark_tool.py:177-213` | **untrusted embedded JSON** | `json.loads`, `insert_text` |
| A10 | Print pipeline (helper subprocess) | `src/printing/*`, `controller/pdf_controller.py:122-149,1579-1628` | operator + untrusted PDF bytes | `QProcess`, `subprocess.Popen`, CUPS/`lp` |
| A11 | Printer-properties dialog (Windows) | `src/printing/platforms/win_driver.py:862` | operator | `subprocess.Popen(["rundll32.exe", …])` |
| A12 | Dev computer-use agent | `scripts/ux_signoff_agent.py` | model output → desktop | `pyautogui` actions |

**Deserialization:** none unsafe — `json` only (watermark, print job, IPC). No pickle/yaml/marshal/shelve/joblib on untrusted data. `multiprocessing` (optimizer) pickles only trusted primitives (xref ints, image bytes, settings dict).
**Dynamic import:** `importlib.import_module` only with **hardcoded** module names (`"surya"`, `"torch"`, `"surya.detection"`) — not attacker-controlled. Safe.
**Secrets:** none hardcoded. `OPENAI_API_KEY` read from env in the dev agent only.

---

## 2. Findings (sorted by Exploitability × Impact × Exposure)

---

### [F1] Untrusted PDFs parsed/rasterized with no resource limits (DoS; native-parser exposure)
**Severity:** Medium **Confidence:** Medium-High
**CWE/OWASP:** CWE-400 (Uncontrolled Resource Consumption), CWE-409 (Decompression Bomb), CWE-674 (Uncontrolled Recursion); OWASP A05.
**Affected files/lines:**
- `view/pdf_view.py:624-640` (drag-drop → open), `main.py:47,104-108` (CLI), `controller/pdf_controller.py:1026-1068` (`open_pdf`)
- `model/pdf_model.py:651` (`fitz.open(str(src_path))` — no size/page guard)
- `model/tools/ocr_tool.py:257-267` (renders every selected page at `OCR_RENDER_SCALE = 2.0`)
- `model/pdf_model.py:4830` (straighten rasterizes at scale 2.0), `4769-4778`
- `model/pdf_content_ops.py:284-487` (`discover_native_image_invocations` / `_discover_form_nested_invocations` recurse over nested form XObjects)

**Attack surface:** Any opened PDF (drag-drop, CLI, dialog, merge, IPC).
**Exploitability:** Low effort — deliver a PDF and have the user open it (the normal flow). No auth needed.
**Exploitability context (high-level):** A document declaring an enormous page box, a very high page count, deeply nested form XObjects, or oversized embedded images forces large pixmap allocations during render/OCR/straighten/optimize, or deep recursion during native-image discovery. The result is memory/CPU exhaustion, UI hang, or process crash. Because the page count and `MediaBox` are taken from the file with no upper bound, the cost scales with attacker-chosen values.
**Root cause:** No pre-open validation of file size, page count, or page dimensions; render scale and image transcoding are applied to all pages unconditionally; the form-recursion walker has no depth cap.
**Impact:** Local denial of service (hang/crash/OOM), potential data loss of unsaved edits. Combined with **F9**, feeding untrusted PDFs directly into the native MuPDF/Pillow parsers turns any unpatched parser memory-corruption CVE into a code-execution path.
**Partial existing mitigation:** Pillow's default `MAX_IMAGE_PIXELS` decompression-bomb guard is **not** disabled anywhere (verified — no `MAX_IMAGE_PIXELS` override), so the Pillow path raises on >178 MP images. The `fitz` pixmap path has no equivalent guard.
**Remediation:**
- Before `fitz.open`, stat the file and reject/confirm above a threshold; after open, cap `doc.page_count` and per-page `rect` area before rendering.
- Clamp render pixmap dimensions (cap `scale * max(width,height)`), and cap total pixels per pixmap.
- Add a recursion-depth limit / visited-set to `_discover_form_nested_invocations`.
- Run open/OCR/optimize in the worker threads they already use, with a memory watchdog and user-cancellable progress.

**Minimum remediation example:**
```python
MAX_PDF_BYTES = 512 * 1024 * 1024
MAX_PAGES = 5000
MAX_PIXMAP_PIXELS = 40_000_000  # ~ 40 MP per rendered page

def _guard_before_open(path: Path) -> None:
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds size limit")

def _safe_scale(page, scale: float) -> float:
    w, h = page.rect.width, page.rect.height
    if w * h * scale * scale > MAX_PIXMAP_PIXELS:
        scale = (MAX_PIXMAP_PIXELS / max(1.0, w * h)) ** 0.5
    return max(0.1, scale)
```
**Suggested test cases:** open a 100k-page synthetic PDF (assert graceful reject/cancel, no OOM); page with `MediaBox` 1e6×1e6 (assert clamped scale); nested-form recursion bomb (assert depth-capped, no `RecursionError`); confirm Pillow bomb guard still active in optimize path.
**Manual verification required:** Real-world memory ceiling on the target Windows hardware; whether OCR on a single huge page already OOMs before any cap.

---

### [F2] Unpinned dependency floors include image/PDF parsers with known CVEs (supply chain)
**Severity:** Medium **Confidence:** Medium
**CWE/OWASP:** CWE-1104 / CWE-1395 (Vulnerable/Outdated Components), CWE-494 (download w/o integrity check for ML weights); OWASP A06.
**Affected files/lines:** `requirements.txt:4-5`, `optional-requirements.txt:7-16`.
```
PySide6>=6.4   PyMuPDF>=1.23          # no upper bound, no lockfile
Pillow>=9.0    surya-ocr>=0.6  torch>=2.1   pywin32>=306  pycups>=2.0.4  pytest>=7.0
```
**Attack surface:** Build/install time + runtime parsing of untrusted images/PDFs.
**Exploitability:** Indirect — depends on which version resolves at install time. `Pillow>=9.0` permits installing releases with fixed-but-historical CVEs (e.g., `ImageMath.eval` code execution CVE-2023-50447, buffer overflow CVE-2024-28219, CVE-2023-44271 DoS). `PyMuPDF>=1.23` permits MuPDF builds with subsequently-patched native parser bugs. No hashes/lockfile → non-reproducible builds.
**Root cause:** Lower-bound-only constraints with no lockfile, no upper bound, no CI dependency audit.
**Impact:** A vulnerable transitive build combined with **F1** (untrusted PDF/image input) can escalate from DoS to memory corruption / code execution inside the native parser. `surya-ocr`/`torch` additionally pull a large ML stack and fetch model weights from a remote hub at first run with no pinned revision/hash (integrity gap).
**Remediation:**
- Generate a hash-pinned lockfile (`pip-compile --generate-hashes` / `uv lock`); raise floors to patched releases (e.g., `Pillow>=10.3`, current `PyMuPDF`).
- Add `pip-audit` (and optionally `safety`) to CI; fail on known advisories.
- For OCR, pin the surya model revision and pre-fetch/verify weights from a trusted, hash-checked mirror; document an offline-install path.
**Minimum remediation example:**
```
# requirements.txt (pinned + audited in CI)
PySide6==6.8.1
PyMuPDF==1.24.10
# optional-requirements.txt
Pillow==11.0.0
surya-ocr==0.6.13
torch==2.4.1
```
**Suggested test cases:** CI job runs `pip-audit -r requirements.txt -r optional-requirements.txt` and fails on findings; reproducible-build check that two clean installs resolve identical versions.
**Manual verification required:** Exact versions currently resolved in the `.venv` and in the PyInstaller bundle; whether surya weights are bundled or downloaded at runtime.

---

### [F3] Dev computer-use agent executes unbounded model-proposed desktop actions (prompt-injection → excessive agency)
**Severity:** Medium (mechanism) — **Low exposure (dev-only, fixed inputs)** **Confidence:** High (mechanism)
**CWE/OWASP:** CWE-77/CWE-94-adjacent, OWASP-LLM01 (Prompt Injection), OWASP-LLM06/LLM08 (Excessive Agency).
**Affected files/lines:** `scripts/ux_signoff_agent.py:198-217` (`_execute_cua_action` runs `pyautogui` click/type/key/scroll with no allowlist, bounds, or confirmation), `:280-405` (`_run_agent_on_pdf` screenshot→model→action loop), `:47-52` (`REFERENCE_PDFS`, `MODEL="gpt-5.4"`).
**Attack surface:** Screenshots of the app rendering PDF content are sent to the model; the model's returned `computer_call` actions are executed against the **real desktop**.
**Exploitability:** Requires running the dev harness with `OPENAI_API_KEY`. In its shipped form it only targets fixed test PDFs, so exposure is low. If the script were pointed at attacker-controlled PDFs, indirect prompt injection through rendered/OCR'd page content could steer mouse/keyboard.
**Exploitability context (high-level):** Page content that the model "reads" from a screenshot can act as instructions; because actions execute with no human gate or coordinate sandbox, a successful injection translates model output into arbitrary local UI manipulation.
**Root cause:** No action allowlist, no bounds/sandbox, no human confirmation, and the input (screen showing document content) is partly untrusted.
**Impact:** Local UI/keyboard/mouse manipulation in the operator's session during a dev run. Not part of the shipped editor.
**Remediation:** Treat as a privileged automation harness: restrict to a dedicated VM/disposable session, constrain `pyautogui` to the app window's geometry, gate destructive action types, never run against untrusted PDFs, and keep `OPENAI_API_KEY` out of shared environments.
**Minimum remediation example:**
```python
ALLOWED = {"click", "double_click", "scroll", "move", "screenshot"}
def _execute_cua_action(action, window_rect):
    if getattr(action, "type", None) not in ALLOWED:
        raise PermissionError(f"blocked CUA action: {action.type}")
    if hasattr(action, "x") and not window_rect.contains(action.x, action.y):
        raise PermissionError("action outside app window")
```
**Suggested test cases:** feed a PDF containing overt "type the following command" injection text, assert no out-of-window or `type`/`key` actions execute.
**Manual verification required:** Confirm this script is excluded from any PyInstaller bundle and never wired into the shipped app.

---

### [F4] Windows printer-properties launches `rundll32.exe` by bare name (binary-planting / search-order)
**Severity:** Low **Confidence:** Medium
**CWE/OWASP:** CWE-426 (Untrusted Search Path) / CWE-427 (Uncontrolled Search Path Element).
**Affected files/lines:** `src/printing/platforms/win_driver.py:861-864`
```python
subprocess.Popen(["rundll32.exe", "printui.dll,PrintUIEntry", "/e", "/n", normalized_name])
```
**Attack surface:** "Printer properties" fallback path (operator-triggered).
**Exploitability:** Requires an attacker to have write access to the process's working directory or application install directory (so that a malicious `rundll32.exe` resolves earlier than `System32`). With a default install under `Program Files`, this is not writable by standard users.
**Exploitability context (high-level):** `CreateProcess` with a bare image name searches the application and current directories before `System32` in some launch contexts; an attacker-planted `rundll32.exe` in a writable load path would run with the user's privileges.
**Root cause:** Executable referenced by name, not absolute path; no shell injection (argv form is correct, printer name is a separate token).
**Impact:** Local code execution **only** if a writable directory is on the search path — defense-in-depth.
**Remediation:** Use the absolute path under `%SystemRoot%\System32\rundll32.exe`; ensure the app's CWD is a trusted directory at launch.
**Minimum remediation example:**
```python
import os
rundll = os.path.join(os.environ["SystemRoot"], "System32", "rundll32.exe")
subprocess.Popen([rundll, "printui.dll,PrintUIEntry", "/e", "/n", normalized_name])
```
**Suggested test cases:** unit test asserting the Popen argv[0] is an absolute path under System32.
**Manual verification required:** Whether the packaged app sets a controlled CWD; install-dir ACLs in the shipped MSI/folder. (Linux `lp`/`lpstat`/`lpoptions` are resolved via `shutil.which` → already absolute; no change needed.)

---

### [F5] Temp files holding full document content: default ACL + incomplete cleanup on crash
**Severity:** Low **Confidence:** Medium
**CWE/OWASP:** CWE-377 (Insecure Temporary File) / CWE-459 (Incomplete Cleanup), CWE-200.
**Affected files/lines:**
- `src/printing/dispatcher.py:104-114` — `NamedTemporaryFile(delete=False, suffix=".pdf")` in the system temp dir; unlinked in `finally` but lost on hard kill.
- `controller/pdf_controller.py:1585` (`mkdtemp`) + `:137` (`input.pdf` written) → cleaned by `subprocess_runner._cleanup` (`:218-224`), but residual on crash before cleanup.
- `src/printing/helper_main.py:25-37` (snapshot bytes), `model/pdf_optimizer.py:758-770` temp saves.
**Attack surface:** Local filesystem (system/user temp).
**Exploitability:** Names are randomized (`mkstemp`/`mkdtemp`/`NamedTemporaryFile`) → no predictable-name race or symlink attack on standard configs. The residual risk is (a) sensitive document content left in temp if the process is killed mid-print/mid-optimize, and (b) default ACL inheritance from the temp directory.
**Impact:** A local same-user (or, on misconfigured multi-user temp, another) actor could read leftover PDF content.
**Remediation:** Prefer `delete=True` / context-managed temp for the dispatcher path; on Windows create job temp under a per-user app-data dir with restrictive ACLs; register an `atexit`/signal cleanup for the print work dir.
**Minimum remediation example:**
```python
def print_pdf_bytes(self, pdf_bytes, options):
    with tempfile.TemporaryDirectory(prefix="print-bytes-") as d:
        p = Path(d) / "job.pdf"
        p.write_bytes(pdf_bytes)
        return self.print_pdf_file(str(p), options)  # dir + file auto-removed
```
**Suggested test cases:** kill the helper mid-job, assert no `pdf_editor_print_*` dir survives a subsequent run's cleanup; assert dispatcher temp is gone after success and after exception.
**Manual verification required:** Temp directory ACLs on the deployment host; multi-user/Terminal-Server scenarios.

---

### [F6] Single-instance local IPC opens files with no peer authentication
**Severity:** Low **Confidence:** Medium
**CWE/OWASP:** CWE-306 (Missing Authentication for Critical Function) / CWE-668 (Exposure to Wrong Sphere).
**Affected files/lines:** `utils/single_instance.py:93-122` (`_handle_socket_message` parses `{"argv":[...]}` and calls `on_message`), `:175-208` (sender), `:16-19` (server name `pdf_editor_singleinstance_<user>`); sink `controller/pdf_controller.py:1070-1082` → `open_pdf`.
**Attack surface:** Local `QLocalServer` (named pipe on Windows / Unix socket).
**Exploitability:** A local process able to connect to the pipe can instruct the running instance to open arbitrary local PDF paths. Paths are `Path(...).resolve()`d (`:89-90`) and opened — read+render only; **cannot write, delete, or execute**. Chains into **F1** (force-open a malicious PDF).
**Impact:** Limited — forces the victim instance to open/render a local file.
**Root cause:** No verification of peer identity; default socket options.
**Remediation:** Set `QLocalServer.setSocketOptions(QLocalServer.UserAccessOption)` to restrict the pipe/socket to the current user; optionally include a per-session nonce in the handshake; validate forwarded paths exist and have a `.pdf` suffix before opening.
**Minimum remediation example:**
```python
server = QLocalServer()
server.setSocketOptions(QLocalServer.UserAccessOption)  # before listen()
```
**Suggested test cases:** assert `UserAccessOption` is set; assert forwarded non-`.pdf` / non-existent paths are rejected.
**Manual verification required:** **Default `QLocalServer` pipe ACL on the target Windows build** — whether other sessions/users can connect without `UserAccessOption` (I did not find an options call; flagged in §7).

---

### [F7] DEBUG root logging discloses file paths and error details
**Severity:** Low **Confidence:** High
**CWE/OWASP:** CWE-532 (Sensitive Info in Logs) / CWE-200.
**Affected files/lines:** `main.py:9-11` (`logging.basicConfig(level=logging.DEBUG …)` — no file handler), plus path-bearing debug logs e.g. `model/pdf_model.py:632,680,1124,4714`, `model/tools/ocr_tool.py:271`. (Compliant with CLAUDE.md §3 — `basicConfig` is only in `main.py`.)
**Attack surface:** Console/stderr; any redirected log; a frozen build that attaches a console.
**Exploitability:** Requires local access to the console/redirected output. No log **file** is configured by default, which limits persistence.
**Impact:** Full local file paths (which can reveal usernames/folder structure) and exception strings exposed; OCR/page text is **not** logged in full (good — only counts/page numbers).
**Root cause:** Verbose default level for a shipped desktop app.
**Remediation:** Default to `INFO`/`WARNING` in release builds (env- or build-flag gated); scrub absolute paths to basenames in user-facing/error logs.
**Minimum remediation example:**
```python
level = logging.DEBUG if os.environ.get("PDF_EDITOR_DEBUG") else logging.WARNING
logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")
```
**Suggested test cases:** assert release config logs at ≥INFO; assert error dialogs/logs do not contain absolute home paths.
**Manual verification required:** Whether the PyInstaller build runs with a visible console and/or redirects stderr to a file.

---

### [F8] Embedded watermark JSON from untrusted PDFs re-applied with minimal schema validation
**Severity:** Informational/Low **Confidence:** High
**CWE/OWASP:** CWE-20 (Improper Input Validation).
**Affected files/lines:** `model/tools/watermark_tool.py:177-198` (`_load_watermarks_from_doc` → `json.loads` of embedded file `__pdf_editor_watermarks`, validates only `id`/`pages` presence), values flow to `model/tools/watermark_rendering.py:20-75` (`insert_text`).
**Why this is low:** It is **JSON, not pickle** → no code execution. `font` resolves via `fitz.Font` with a safe fallback (`:47-50`); `color` is sliced to 3 components; opacity/line-spacing are clamped on edit. The residual concerns are pure robustness: unbounded `text` length, untyped numeric fields (`angle`, `font_size`, `offset_*`) read straight from the file, and the embedded blob persists across re-saves.
**Impact:** A crafted embedded blob could create degenerate watermark rendering / oversized text (minor DoS) but not code execution or file access.
**Remediation:** Validate types and clamp numeric ranges on **load** (not just on edit), cap `text` length, and ignore unknown keys.
**Minimum remediation example:**
```python
def _coerce_wm(wm: dict) -> dict | None:
    try:
        return {
            "id": str(wm["id"]),
            "pages": [int(p) for p in wm["pages"]][:10000],
            "text": str(wm.get("text", ""))[:5000],
            "angle": float(wm.get("angle", 0)) % 360,
            "font_size": max(1.0, min(float(wm.get("font_size", 48)), 1000.0)),
            "opacity": max(0.0, min(float(wm.get("opacity", 0.5)), 1.0)),
        }
    except (KeyError, TypeError, ValueError):
        return None
```
**Suggested test cases:** load a PDF whose embedded watermark JSON has wrong types / 1e9 pages / 10 MB text — assert sanitized or dropped, no crash.
**Manual verification required:** None.

---

### [F9] OCR model weights fetched from a remote hub without pinned integrity (runtime supply chain)
**Severity:** Low **Confidence:** Medium *(overlaps F2; listed separately for the integrity angle)*
**CWE/OWASP:** CWE-494 (Download of Code/Data Without Integrity Check).
**Affected files/lines:** `model/tools/ocr_tool.py:136-157` (surya `DetectionPredictor`/`RecognitionPredictor`/`FoundationPredictor` construction — default behavior downloads weights), `optional-requirements.txt:9-10`.
**Exploitability:** Requires the OCR feature to be installed/used and depends on the hub/network trust; weights are not application code but are loaded into torch.
**Impact:** A compromised or substituted model artifact could degrade/poison OCR output or, in pathological loader cases, affect process integrity; also first-use network egress.
**Remediation:** Pin the surya model revision, pre-fetch and hash-verify weights, support a fully offline/bundled model directory, and document an air-gapped install.
**Suggested test cases:** run OCR offline with a pre-staged, hash-checked model dir; assert no network fetch occurs.
**Manual verification required:** Whether weights are bundled in the PyInstaller build or pulled at runtime, and from where.

---

## 3. Top-10 Priority Patch List

1. **F2** — Pin + hash-lock all dependencies; raise `Pillow`/`PyMuPDF` floors to patched releases; add `pip-audit` to CI. *(removes the largest latent RCE amplifier)*
2. **F1** — Add file-size / page-count / pixmap-pixel guards before `fitz.open` and before every render/OCR/optimize raster.
3. **F1** — Add recursion-depth cap to `_discover_form_nested_invocations` (`pdf_content_ops.py`).
4. **F4** — Use absolute `System32\rundll32.exe`; set a controlled CWD at app launch.
5. **F6** — `QLocalServer.setSocketOptions(UserAccessOption)` + validate forwarded paths.
6. **F5** — Context-manage the dispatcher temp PDF; per-user ACL'd print work dir; crash-time cleanup.
7. **F7** — Default release logging to WARNING; scrub absolute paths.
8. **F9** — Pin/verify/bundle OCR model weights; offline path.
9. **F8** — Strict type/range coercion of embedded watermark JSON on load.
10. **F3** — Sandbox/scope the dev computer-use agent; confirm it is excluded from shipped builds.

---

## 4. Threat Model

**Assets:** user PDF documents and unsaved edits; the host filesystem (read scope of the user); the operator's desktop session; OCR/print output; (dev) `OPENAI_API_KEY`.
**Trust boundaries:**
- File content boundary — bytes of any opened/merged/dropped PDF and its embedded blobs are **untrusted** (PyMuPDF, Pillow, watermark JSON, native-image discovery).
- Process boundary — main app ↔ print helper subprocess (`QProcess`, JSON job file in private temp).
- IPC boundary — single-instance `QLocalServer` ↔ local peers (currently unauthenticated).
- External-service boundary — surya/torch model hub (OCR); OpenAI Responses API (dev agent only).
**Attacker capabilities considered:** (a) supplies a malicious PDF the user opens; (b) a local same-user/co-located process connecting to the IPC pipe; (c) an attacker with write access to a directory on the Windows binary search path; (d) for the dev agent, attacker-controlled PDF content influencing model actions.
**Sensitive operations:** `fitz.open`/render/OCR/optimize on untrusted bytes; file save/overwrite/`os.replace`/`shutil.move`; subprocess launches (helper, rundll32, lp/cups); temp file creation; embedded-JSON parse.
**Out of scope / not present:** no network listener, no auth/session/credentials, no DB, no `eval`/`exec`, no untrusted deserialization, no `shell=True`.

---

## 5. Recommended Tool/Scan Commands

```bash
# Dependency CVEs (run against BOTH requirement files and the live venv)
pip-audit -r requirements.txt -r optional-requirements.txt
pip-audit                                   # audits the installed .venv
# Static security lint
bandit -r controller model src utils view main.py -x ./.venv,./test_scripts
# Targeted semgrep
semgrep --config p/python --config p/security-audit \
        --exclude .venv --exclude test_scripts .
# Project's own gates
ruff check .
mypy model/ utils/
pytest -q
# Supply-chain / secrets hygiene
pip install pip-licenses && pip-licenses --format=csv
detect-secrets scan > .secrets.baseline    # confirm no creds (expect clean)
```
Suggested semgrep spot-checks to author: bare-name `subprocess` argv[0] on Windows; `tempfile.NamedTemporaryFile(delete=False)`; `logging.basicConfig(level=DEBUG`; `Image.MAX_IMAGE_PIXELS = None` (assert absent).

---

## 6. Security Regression Test Checklist

- [ ] **Malicious PDF corpus** (huge page count, giant MediaBox, image bomb, nested-form recursion bomb, truncated/`is_repaired`) → open/OCR/optimize/print **degrade gracefully** (reject/cancel), no OOM, no `RecursionError`. *(F1)*
- [ ] Pillow decompression-bomb guard remains active in the optimize image path (no `MAX_IMAGE_PIXELS = None`). *(F1)*
- [ ] `pip-audit` job is green; lockfile present; two clean installs are byte-identical. *(F2)*
- [ ] `win_driver` Popen argv[0] is an absolute System32 path. *(F4)*
- [ ] Dispatcher/print temp artifacts are gone after success **and** after forced kill; print work dir is per-user. *(F5)*
- [ ] `QLocalServer` uses `UserAccessOption`; forwarded non-`.pdf`/non-existent paths are rejected. *(F6)*
- [ ] Release build logs at ≥INFO; no absolute home paths in error dialogs/logs. *(F7)*
- [ ] Watermark JSON with wrong types / oversized fields is sanitized or dropped on load. *(F8)*
- [ ] OCR runs offline against a pre-staged, hash-verified model dir with no network fetch. *(F9)*
- [ ] CUA agent: blocked action types and out-of-window coordinates are refused; agent excluded from shipped bundle. *(F3)*

---

## 7. "Insufficient Evidence — Requires Manual Verification"

1. **QLocalServer pipe ACL (Windows).** I found **no** `setSocketOptions(...)` call (`utils/single_instance.py`); whether the default named-pipe security descriptor permits other sessions/users to connect needs runtime confirmation on the target OS build. *(bears on F6 severity)*
2. **PyInstaller packaging.** No `.spec` file exists in-repo; only `run.bat` (`python .\main.py`). DLL-search-order hardening, `--onefile` temp-extraction risks, console visibility, and whether `scripts/ux_signoff_agent.py` / OCR weights are bundled cannot be assessed from the repo. *(bears on F3, F4, F7, F9)*
3. **OCR weight provenance.** Whether surya weights are bundled vs. downloaded at runtime, and from which host/revision. *(F9)*
4. **Exact resolved dependency versions** in `.venv` and any release bundle — required to confirm/deny specific Pillow/MuPDF CVEs. *(F2)*
5. **Windows raw-spooler print path** (`win_driver.print_pdf` → `raster_print_pdf`/`win32print`) was confirmed to use the Qt raster bridge / argv-form, not a shell or PDF-reader "print" verb; I did not exhaustively trace every DEVMODE ctypes branch (`win_driver.py:670-870`) for buffer-handling memory-safety — recommend a focused review/fuzz of the DEVMODE base64/ctypes round-trip.
6. **`資安掃瞄.md`** (untracked, in repo root) appears to be a prior/draft scan; I reviewed independently and did not incorporate it. Confirm whether it should be reconciled with this report.

---

### Notable positives (defensive posture already in place)
- No `shell=True`, no command string concatenation; every subprocess uses argv lists. Linux print tools resolved via `shutil.which` (absolute).
- All persistence/IPC is JSON; **no pickle/yaml/marshal** on untrusted data; `importlib` targets are hardcoded.
- Drag-drop filters to local `.pdf` files (`pdf_view.py:624-640`); save/export paths are operator-chosen via native dialogs; atomic saves via temp + `os.replace`.
- Pillow decompression-bomb default guard left intact; password-protected PDFs handled via `authenticate` with explicit failure paths.
- No hardcoded secrets in application code.

Would you like me to (a) write this report to a file (e.g., `docs/security-review-2026-06-02.md`) and/or (b) turn the Top-10 into `TODOS.md` entries with the corresponding regression tests as failing (Red-Light) stubs per your CLAUDE.md workflow? I won't change anything until you confirm.


I'll run the static scans. Let me start by installing the tools (this can take a few minutes, especially semgrep), then run each scanner.

Tools installed (the conflict warnings are about pre-existing global packages, not our scanners). Now running bandit:

Bandit completed. Let me parse the results and run pip-audit on both requirement files in parallel.

Bandit: **0 High, 0 Medium, 115 Low** in shipped code. The Low categories directly corroborate the manual review (B607 partial-path = F4 `rundll32`; B603/B404 = the subprocess argv calls I cleared as non-injectable). Let me pull the two noteworthy items (B105 hardcoded password, B607 partial-path locations) and continue with pip-audit:

Strong corroboration for the dependency finding (F2): **pip-audit found 7 known CVEs** in the OCR stack — Pillow 10.4.0 (5 CVEs) and transformers 4.57.6 (2 CVEs, pulled transitively by surya-ocr). The core `requirements.txt` resolved clean. The B105 "hardcoded password" is a **false positive** (`if token == "tiro"` — a font-name compare). Now running semgrep (excluding `.venv` so it finishes in reasonable time):

Semgrep works on Windows (single-file scan succeeded with 0 findings). The exit-2 on the full run likely came from a target/parse error on some file while still producing output. Let me check whether the JSON report was written, and if not, re-run the full scan capturing the real error:

Report wasn't written — the whole-tree scan hit a fatal error before output. Let me scope semgrep to the application source directories and capture the result properly:

Let me clean up the scratch stderr files (keeping the two report JSONs) and then summarize:

Static scans complete. Here are the consolidated results.

## Static Scan Results Summary

**Environment:** global Python 3.10.0 (not the project `.venv`). Tools: bandit 1.9.4, pip-audit, semgrep (registry "auto" ruleset).

### 1. bandit — `0 High, 0 Medium, 115 Low` (27,659 LOC, excl. `.venv`/`test_scripts`)

| Test | Count | Sev/Conf | Verdict |
|---|---|---|---|
| B110 `try_except_pass` | 51 | Low/High | Noise — silent exception swallowing; style, not a vuln |
| B603 `subprocess_without_shell_equals_true` | 21 | Low/High | **Not exploitable** — all argv-form, no `shell=True` (confirms manual review) |
| B607 `start_process_with_partial_path` | 12 | Low/High | Mostly dev `git`/`lpstat`; **one app-code hit = `win_driver.py:862 rundll32.exe`** → corroborates **F4** |
| B101 `assert_used` | 12 | Low/High | Asserts in non-test code; minor |
| B112 `try_except_continue` | 10 | Low/High | Noise |
| B404 `import subprocess` | 8 | Low/High | Informational |
| B105 `hardcoded_password_string` | 1 | Low/Med | **FALSE POSITIVE** — `model/pdf_model.py:1986` is `if token == "tiro":` (a font-name compare; var happens to be named `token`) |

No new High/Medium issues; bandit confirms there is **no shell injection and no hardcoded credential** in shipped code.

### 2. pip-audit — the headline result

**`requirements.txt` (core: PySide6, PyMuPDF): `No known vulnerabilities found`** ✅

**`optional-requirements.txt` (OCR stack): `7 known vulnerabilities in 2 packages`** ⚠️
```
pillow        10.4.0   PYSEC-2026-165, CVE-2026-25990, CVE-2026-40192,
                       CVE-2026-42310, CVE-2026-42311   → fix 12.1.1 / 12.2.0
transformers  4.57.6   PYSEC-2025-217, CVE-2026-1839    → fix 5.0.0rc3
```
This is **concrete, live-DB evidence for finding F2**. With `Pillow>=9.0` and `surya-ocr>=0.6` (which transitively pulls `transformers`), the resolver lands on packages carrying 7 CVEs — and the Pillow ones are **image-parsing bugs reachable from untrusted image/OCR input**, which chains directly into **F1**. F2 is no longer "could resolve to vulnerable" — it **does**, today. (`transformers` also confirms the ML supply-chain surface I flagged under F2/F9.)

### 3. semgrep (registry "auto", 290 rules) — `0 findings, 0 errors` on 61 app-source files

Scanning `controller model src utils view main.py` produced **zero findings** — no injection/taint/dangerous-sink patterns in shipped code. (The initial whole-tree `semgrep scan … .` aborted with exit 2 on a non-source file — a binary/PDF under `test_files/` or a bundled skill script; scoping to app source resolved it. The community ruleset is limited without `semgrep login`, so treat 0 findings as "no obvious patterns," not proof of absence.)

---

## How the scans reconcile with the manual report

| Manual finding | Automated corroboration |
|---|---|
| **F2** unpinned deps / CVE exposure (Medium) | **Confirmed & strengthened** — pip-audit: 7 CVEs in pillow + transformers |
| **F4** `rundll32.exe` partial path (Low) | **Confirmed** — bandit B607 at `win_driver.py:862` (and Linux `lpstat`/`lp` share the class) |
| **F1, F3, F5, F6, F7, F8** | Not pattern-detectable by these tools — they are logic/architecture issues (resource limits, IPC auth, agent agency, temp lifecycle), correctly **absent** from bandit/semgrep output, which validates they were findable only by manual data-flow review |
| No shell injection / no hardcoded secrets (positives) | **Confirmed** — bandit B603 all argv-form; B105 is a false positive |

**Net effect on severities:** F2 has the strongest evidence of any finding (live CVEs) and remains **Medium** — arguably the top practical priority alongside F1, because the patched fixes exist (bump Pillow ≥ 12.1.1, re-pin/upgrade the surya→transformers chain, add `pip-audit` to CI). Nothing in the automated results elevates anything to High/Critical, consistent with the manual conclusion.

**Artifacts left in repo root:** `bandit-report.json` (full detail, 130 KB) and `semgrep-report.json` (4.8 KB). Scratch stderr files were removed. Want me to delete these two JSON reports as well, add them to `.gitignore`, or also run `pip-audit` against the actual project `.venv` (it audits the *installed* set, which may differ from what the resolver picked here — e.g., your global env has `pillow 12.1.1` and `surya-ocr 0.17.1`)?