# F3 Shell-Integration APIs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose the in-app command-line surface (multi-open, headless merge, single-instance forwarding) so a future Windows "Open with" / "Send to" entry can invoke the editor — without modifying the user's registry, file associations, or any OS settings.

**Architecture:** Add an `argparse` front end in `main.py`. For single-instance, use `QLocalServer` / `QLocalSocket` (cross-platform, already in PySide6) keyed on a per-user server name; a second invocation serializes argv as JSON, sends it to the running server, and exits. The running instance deserializes and calls the existing `PDFController.open_pdf` / merge helpers. `--merge` reuses `merge_ordered_sources_into_current`-style logic via a new headless helper in `model/merge_session.py` (or a thin wrapper) that uses `fitz` directly, bypassing the UI dialog.

**Tech Stack:** Python 3.9+, PySide6 (`QLocalServer`, `QLocalSocket`), PyMuPDF (`fitz`), argparse, pytest.

**Scope guardrails (explicit non-goals):**
- No registry edits, no `HKCU\Software\Classes` writes, no `ftype/assoc`, no shell extension DLL, no Explorer preview handler.
- No installer/uninstaller scripts for shell verbs.
- macOS Finder integration and `.app` Info.plist changes are out of scope.
- The supplied `docs/plans/2026-04-10-shell-integration.md` had those pieces; this plan deliberately drops them.

---

## Context

The user wants F3 reduced to "just open the APIs — don't change my computer's settings." Today:
- `main.py` lines 53–57 already loop `cli_args` and call `controller.open_pdf(path)` — multi-file open technically works but has no argparse, no `--help`, no flags, no error reporting contract.
- `PDFController.open_pdf` (controller/pdf_controller.py:794) and `merge_ordered_sources_into_current` / `save_ordered_sources_as_new` (lines 838+) exist but merge is UI-dialog-only.
- No single-instance IPC exists — every invocation spawns a fresh `QApplication`, so Explorer "Open with" on two files in sequence would create two windows instead of two tabs.

Outcome: after this plan, `pdf_editor a.pdf b.pdf` opens both as tabs in the existing window (or starts a new one if none is running), and `pdf_editor --merge OUT.pdf a.pdf b.pdf` runs headless and exits 0 on success.

---

## Critical files

- Modify: `main.py` (argparse, single-instance client/server bootstrap).
- Create: `utils/single_instance.py` (QLocalServer wrapper + argv JSON protocol).
- Create: `model/headless_merge.py` (CLI-callable merge that uses `fitz` directly; no Qt widgets).
- Modify: `controller/pdf_controller.py` — add a small `handle_forwarded_cli(args: list[str])` method that routes forwarded argv (open files; no merge in forwarded path — merge stays headless in the child process).
- Tests:
  - `test_scripts/test_cli_argparse.py` (new)
  - `test_scripts/test_headless_merge.py` (new)
  - `test_scripts/test_single_instance_forwarding.py` (new)

Reuse:
- `PDFController.open_pdf` (controller/pdf_controller.py:794)
- Existing merge plumbing in `model/merge_session.py` as the reference for page ordering semantics (but headless path uses `fitz.open` + `insert_pdf` directly to avoid Qt).

---

## Tasks

### Task 1: argparse front end with positional file paths

**Files:**
- Modify: `main.py` (replace raw `cli_args` loop with argparse)
- Test: `test_scripts/test_cli_argparse.py` (create)

**Step 1 — Red test:** Write a test that imports a new `main.parse_cli(argv)` function and asserts:
- `parse_cli(["a.pdf", "b.pdf"]).files == ["a.pdf", "b.pdf"]`
- `parse_cli(["a.pdf"]).merge_output is None`
- `parse_cli(["--merge", "out.pdf", "a.pdf", "b.pdf"]).merge_output == "out.pdf"` and `.files == ["a.pdf", "b.pdf"]`
- `parse_cli(["--merge", "out.pdf"])` raises `SystemExit` (needs ≥1 input file).

**Step 2:** Run `pytest test_scripts/test_cli_argparse.py -v` → FAIL (parse_cli missing).

**Step 3:** Implement `parse_cli` in `main.py` with argparse: positional `files` (nargs='*'), `--merge OUTPUT`, `--help` auto. Validate: if `--merge` given, require ≥1 file.

**Step 4:** Rerun tests → PASS.

**Step 5:** Commit: `feat(cli): add argparse front end for file args and --merge`.

---

### Task 2: Headless merge helper

**Files:**
- Create: `model/headless_merge.py`
- Test: `test_scripts/test_headless_merge.py`

**Step 1 — Red test:** Create two tiny fixture PDFs via `fitz` in a tmp dir (or reuse `test_files/2.pdf` + another). Call `headless_merge([a, b], out_path)` and assert: output exists, `fitz.open(out).page_count == page_count(a) + page_count(b)`, and the first page of `out` matches first page of `a` by text content.

**Step 2:** Run → FAIL (module missing).

**Step 3:** Implement `headless_merge(inputs: list[str], output: str) -> None` using `fitz.open()` + `dst.insert_pdf(src)` loop + `dst.save(output)`. Raise `FileNotFoundError` on missing input, `ValueError` on empty input list. No Qt imports.

**Step 4:** Rerun → PASS. Also test missing-input error path.

**Step 5:** Commit: `feat(model): add headless_merge helper for CLI use`.

---

### Task 3: Wire --merge into main entry point

**Files:**
- Modify: `main.py`
- Test: extend `test_scripts/test_cli_argparse.py` with an integration-style test that calls a new `main.run_merge_and_exit(args)` and asserts it produces the merged output file without constructing `QApplication`.

**Step 1 — Red test:** Assert that calling `run_merge_and_exit(parse_cli(["--merge", str(out), str(a), str(b)]))` returns 0 and `out` exists; and that it did NOT import/instantiate PySide6 widgets (check `"PySide6.QtWidgets" not in sys.modules` before the call, and that no QApplication.instance() is created — use `QApplication.instance() is None` after, given test setup).

**Step 2:** Run → FAIL.

**Step 3:** In `main.py`, branch early in `run()`: if `args.merge_output`, call `run_merge_and_exit(args)` which calls `headless_merge(...)` then returns int exit code. Skip all Qt bootstrap in that branch.

**Step 4:** Rerun → PASS.

**Step 5:** Commit: `feat(cli): headless --merge runs without launching UI`.

---

### Task 4: Single-instance server/client

**Files:**
- Create: `utils/single_instance.py`
- Test: `test_scripts/test_single_instance_forwarding.py`

Design:
- Server name: `pdf_editor_singleinstance_<username>` (use `getpass.getuser()` — per-user so multi-user machines don't collide; no system-wide state).
- `try_become_server(on_message: Callable[[list[str]], None]) -> QLocalServer | None`: attempts `QLocalServer.listen(name)`. If name already taken, tries `QLocalServer.removeServer(name)` only if a probe connect fails (stale socket cleanup), then retries once. Returns server on success, `None` if another instance is live.
- `send_to_running_instance(argv: list[str], timeout_ms: int = 2000) -> bool`: `QLocalSocket.connectToServer(name)`, writes JSON `{"argv": [...]}` + `\n`, waits for ack byte, returns True/False.
- Protocol: newline-delimited JSON. Single message per connection.

**Step 1 — Red tests** (use `QCoreApplication` + `pytest-qt` or manual event loop):
- Spin up a server with a capture list; client sends `["x.pdf"]`; assert capture list received `["x.pdf"]` within 1s.
- Second `try_become_server` call returns `None` while first is alive.
- Stale-socket cleanup: simulate orphan by creating a listener, dropping it without `close()` on Windows — assert second invocation can still claim the name.

**Step 2:** Run → FAIL.

**Step 3:** Implement using `QLocalServer` / `QLocalSocket`. Keep the module Qt-only (no widgets).

**Step 4:** Rerun → PASS.

**Step 5:** Commit: `feat(utils): single-instance QLocalServer forwarding helper`.

---

### Task 5: Wire single-instance into main()

**Files:**
- Modify: `main.py`
- Modify: `controller/pdf_controller.py` — add `handle_forwarded_cli(files: list[str]) -> None` that iterates and calls `open_pdf`, surfacing the main window (`raise_()`, `activateWindow()` on the top-level view).
- Test: extend `test_single_instance_forwarding.py` — integration test that starts the app in-process, forwards argv via the client helper, and asserts `controller.open_pdf` was called with each path (mock or spy).

**Step 1 — Red test:** Spy on `PDFController.handle_forwarded_cli`. Start a controller + server; call `send_to_running_instance(["a.pdf", "b.pdf"])`; assert spy received `["a.pdf", "b.pdf"]`.

**Step 2:** Run → FAIL.

**Step 3:** In `main.run()`, after argparse and after the `--merge` branch, attempt `try_become_server(on_message=controller.handle_forwarded_cli)`. If it returns `None`, call `send_to_running_instance(args.files)` and exit 0. Otherwise proceed with normal app startup, and if `args.files`, open them once the controller is ready (reuse existing bootstrap path).

Implement `handle_forwarded_cli` to marshal the call onto the Qt main thread via `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` or a queued signal — never call `open_pdf` from the server's read callback directly if it's on a worker thread. (QLocalServer emits on main thread by default when the app has an event loop — verify and note in code comment.)

**Step 4:** Rerun → PASS.

**Step 5:** Commit: `feat(main): forward argv to running instance via single-instance server`.

---

### Task 6: Documentation + TODOS bookkeeping

**Files:**
- Modify: `docs/ARCHITECTURE.md` — one paragraph under "Entry point" describing the argparse surface and single-instance flow.
- Modify: `docs/PITFALLS.md` — entry for QLocalServer stale-socket on Windows if encountered.
- Modify: `TODOS.md` — add "Done" entry for F3 open-APIs slice; note that OS-level registration (registry/shell extensions) is explicitly deferred.
- Modify: `docs/plans/2026-04-09-backlog-execution-order.md` — F3 row: mark status `in_progress` → `done-implement` for the "open APIs" slice, add note that shell registration is out of scope per user direction.
- Modify: `docs/plans/2026-04-10-backlog-checklist.md` — tick F3 API slice.

**Step 1:** Edit the four docs.

**Step 2:** Commit: `docs: record F3 open-APIs slice; shell registration deferred`.

---

## Verification (end-to-end)

1. `ruff check .` — zero new violations.
2. `pytest -q test_scripts/test_cli_argparse.py test_scripts/test_headless_merge.py test_scripts/test_single_instance_forwarding.py` — all green.
3. Full suite smoke: `pytest -q` — no regressions.
4. Manual:
   - `python main.py test_files/2.pdf` — opens one tab.
   - In a second terminal while the first is running: `python main.py test_files/another.pdf` — second process exits immediately; a new tab appears in the first window.
   - `python main.py --merge tmp/merged.pdf test_files/2.pdf test_files/another.pdf` — exits 0, `tmp/merged.pdf` exists, page count = sum of inputs, no window ever appears.
   - `python main.py --help` — shows usage.
5. Confirm no registry keys were created: `reg query HKCU\Software\Classes\Applications\pdf_editor.exe` returns "not found" (it should — we never wrote it).

---

## Open questions / notes

- `QLocalServer` name collision across OS users is avoided by suffixing `getpass.getuser()`. Do not use machine-wide names.
- If the forwarded-argv path must later support relative paths from the caller's CWD, the client should resolve to absolute before sending. Add `Path(p).resolve()` in the client before JSON-encoding.
- Headless merge output directory must exist; `headless_merge` should `mkdir(parents=True, exist_ok=True)` on the parent or raise a clear error — pick the latter for least-surprise.
