# Drag-and-Drop PDF Open Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users drag local PDF files onto the app window to open them, including multi-file drops, silent ignore of non-PDF sources, and safe shell-first startup handling.

**Architecture:** Keep drag-and-drop intake inside `PDFView`. Validate drag hover cheaply, queue valid paths when the controller is not yet attached, and reuse the existing `sig_open_pdf -> PDFController.open_pdf(path)` pipeline for the actual open. `main.py` only drains queued drops after controller activation so empty-launch shell startup cannot lose early drops.

**Tech Stack:** Python, PySide6, pytest

---

## Flow Diagram

```text
Explorer / shell drag
        |
        v
PDFView.dragEnterEvent / dragMoveEvent
        |
        +--> no URLs / non-local / folder / non-.pdf
        |        -> ignore silently
        |        -> clear any drop affordance
        |
        `--> at least one local .pdf
                 -> accept proposed action
                 -> show a light drop affordance

dropEvent
   |
   +--> controller attached?
   |       |
   |       +--> yes: emit sig_open_pdf(path) for each valid path in order
   |       |
   |       `--> no: queue paths in view
   |                |
   |                `--> shell_ready -> attach controller -> flush queue
   |
   `--> controller.open_pdf(path)
             |
             +--> already open -> switch existing tab
             +--> encrypted -> ask password
             +--> open succeeds -> append tab
             `--> open fails -> existing error path
```

## Step 0: Scope Guard

### What already exists

- `C:\Users\jiang\Documents\python programs\pdf_editor\main.py:30-46` already has a shell-first attach path that can safely flush queued drops after `shell_ready`.
- `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py:798-845` already exposes `sig_open_pdf` and the shell-ready signal.
- `C:\Users\jiang\Documents\python programs\pdf_editor\controller\pdf_controller.py:510-552` already owns the real open flow, including duplicate-open handling and password retries.

### Minimum change

- Touch only the view, startup wiring, tests, and user-facing docs.
- Do not introduce a second open-file pipeline.
- Do not add a drag-drop service or background worker.
- Keep invalid drops silent, as agreed in design.

### Complexity check

- Target 4 to 5 touched files.
- If the implementation starts needing new classes or a second intake subsystem, stop and collapse back into the existing `open_pdf(path)` flow.

## Task 1: Capture shell-first drop queuing with a failing startup test

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_main_startup_behavior.py`
- Modify later: `C:\Users\jiang\Documents\python programs\pdf_editor\main.py`

**Step 1: Write the failing test**

Add a regression that starts the app with `main_module.run(argv=[], start_event_loop=False)`, synthesizes a drop of one local PDF before controller attachment, then processes the event loop and asserts the PDF was opened after `shell_ready` attaches the controller.

Use `QMimeData`, `QUrl.fromLocalFile(...)`, and a `QDropEvent` or `QDragEnterEvent` routed through `QApplication.sendEvent(...)` so the test exercises the real widget path instead of a helper.

```python
def test_empty_launch_buffers_dropped_pdf_paths_until_controller_attaches(monkeypatch, tmp_path):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_main_startup_behavior.py -k "drop or shell_ready" -v`

Expected: FAIL because the current app has no drag/drop intake path and no pre-attach queue.

**Step 3: Commit**

Do not commit yet. Continue once the failure is confirmed.

## Task 2: Capture drop filtering and ordering with failing view tests

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py`
- Modify later: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Write the failing tests**

Add two targeted regressions:

```python
def test_drag_drop_opens_multiple_local_pdfs_in_order(mvc, tmp_path):
    ...

def test_drag_drop_ignores_non_pdf_folder_and_remote_urls(mvc, tmp_path):
    ...
```

The first test should feed a mix of local PDFs and assert they open in the same order they were dropped.

The second test should include a folder path, a non-PDF file, and a remote URL, then assert the app silently ignores them and only opens local PDFs.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest test_scripts/test_multi_tab_plan.py -k "drag_drop" -v`

Expected: FAIL because `PDFView` does not yet accept drops or filter URLs.

**Step 3: Commit**

Do not commit yet. Continue once the failures are confirmed.

## Task 3: Implement view drag/drop intake, queueing, and lightweight affordance

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py`

**Step 1: Write minimal implementation**

Add a small, explicit intake path inside `PDFView`:

```python
self.setAcceptDrops(True)
self._pending_open_paths = []

def _extract_dropped_pdf_paths(self, mime_data) -> list[str]:
    ...

def _queue_or_open_paths(self, paths: list[str]) -> None:
    ...

def drain_pending_open_paths(self) -> list[str]:
    ...
```

Implement `dragEnterEvent`, `dragMoveEvent`, `dragLeaveEvent`, and `dropEvent` so they:

- accept only local `.pdf` URLs
- ignore folders, remote URLs, and non-PDF files silently
- toggle a light drop affordance with a transient Qt property or equivalent styling flag
- preserve the dropped order exactly
- queue valid paths when `self.controller` is not attached yet
- emit `sig_open_pdf` immediately for attached controllers

Do not move the open logic into a new service or controller layer.

**Step 2: Run targeted tests to verify they pass**

Run: `python -m pytest test_scripts/test_main_startup_behavior.py test_scripts/test_multi_tab_plan.py -k "drop or drag_drop or shell_ready" -v`

Expected: PASS for the new drag-drop regressions once the view intake path exists.

**Step 3: Commit**

```bash
git add "C:\Users\jiang\Documents\python programs\pdf_editor\view\pdf_view.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_main_startup_behavior.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_multi_tab_plan.py"
git commit -m "feat: add drag-drop pdf intake"
```

## Task 4: Wire shell-ready flush in startup without changing CLI open behavior

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\main.py`

**Step 1: Write minimal implementation**

After `controller.activate()` runs inside `attach_and_activate_controller()`, drain any queued paths from the view and call `controller.open_pdf(path)` for each one in order.

Keep the CLI-open path unchanged:

- controller attaches first
- heavy panels are initialized
- `controller.open_pdf(path)` still opens argv paths synchronously

This keeps the empty-launch shell safe without adding another open-file path.

**Step 2: Run focused startup tests to verify they pass**

Run: `python -m pytest test_scripts/test_main_startup_behavior.py -v`

Expected: PASS, including the new pre-attach drop queue test.

**Step 3: Commit**

```bash
git add "C:\Users\jiang\Documents\python programs\pdf_editor\main.py" "C:\Users\jiang\Documents\python programs\pdf_editor\test_scripts\test_main_startup_behavior.py"
git commit -m "fix: flush queued drag-drop opens on startup"
```

## Task 5: Update docs and remove stale backlog entry

**Files:**
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\docs\FEATURES.md`
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\docs\ARCHITECTURE.md`
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\docs\README.md`
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\docs\README.zh-TW.md`
- Modify: `C:\Users\jiang\Documents\python programs\pdf_editor\docs\to_Update.md`

**Step 1: Update the docs**

Document that:

- dragging local PDF files onto the editor opens them
- multiple dropped PDFs open in order
- folders, remote URLs, and non-PDF files are silently ignored
- shell-first startup can queue early drops until the controller attaches

Also remove or mark complete the stale backlog item in `docs/to_Update.md` that asks for this feature.

**Step 2: Run the final regression slice**

Run: `python -m pytest test_scripts/test_main_startup_behavior.py test_scripts/test_multi_tab_plan.py -v`

Expected: PASS.

**Step 3: Commit**

```bash
git add "C:\Users\jiang\Documents\python programs\pdf_editor\docs\FEATURES.md" "C:\Users\jiang\Documents\python programs\pdf_editor\docs\ARCHITECTURE.md" "C:\Users\jiang\Documents\python programs\pdf_editor\docs\README.md" "C:\Users\jiang\Documents\python programs\pdf_editor\docs\README.zh-TW.md" "C:\Users\jiang\Documents\python programs\pdf_editor\docs\to_Update.md"
git commit -m "docs: add drag-drop pdf open behavior"
```
