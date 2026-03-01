# PDF Editor (PySide6 + PyMuPDF)

Desktop PDF editor written in Python with a Qt UI.

Core capabilities include:
- open/save PDFs
- page operations (delete/rotate/insert/export/merge)
- text editing (overlap-safe)
- dedicated add-text mode (new page text insertion)
- annotations (rect/highlight/free-text)
- watermarks
- search and jump
- optional OCR
- undo/redo through command history

## Legal

No license is currently declared in this repository.
Add a `LICENSE` file if licensing terms are required.

## Features

Feature list and workflow-level behavior are maintained in:
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`

Implementation decisions, bug root causes, and fixes are tracked in:
- `docs/solutions.md`

## Third-Party Libraries

- PySide6
- PyMuPDF (fitz)
- Pillow
- pytesseract (optional)

## Install

### Windows (development)

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_clean.txt
```

### Optional printing backends

```text
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

### OCR dependency

Install Tesseract OCR and ensure `tesseract` is available on PATH.

## Run

```text
python main.py
```

## Keyboard Shortcuts

- `Ctrl+Z`: Undo
- `Ctrl+Y`: Redo
- `Ctrl+S`: Save
- `Ctrl+Shift+S`: Save As
- `F2`: Enter text edit mode

Unsaved-change close prompts also support keyboard confirmation: `Y` to save, `N` to discard, `Esc` to cancel.

## Test Scripts Guide

`test_scripts/TEST_SCRIPTS.md` is the testing map for this project. It tells you:
- which quality dimension each script validates (correctness, regression safety, conflict safety, performance, printing, multi-tab isolation)
- which workflows are covered by each script (for example add-text atomicity, overlap editing, undo/redo integrity, large-file behavior)
- which scripts are fast smoke checks vs deep/corpus/stress validation
- which scripts produce artifacts/reports and where those outputs are written
- which script set to look at when diagnosing a specific class of failures

In short, it helps you understand test coverage scope and the diagnostic value of each script before running anything.

## Package (Windows)

Build command:

```text
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

Output:

```text
dist\main.exe
```

## Recent Updates (2026-03)

High-level summary:
- Added dedicated `add_text` mode and atomic add-text undo/redo boundaries.
- Added rotation-safe visual click anchoring for inserted textboxes.
- Switched add-text default font policy to CJK-capable font path.
- Set default text selection granularity in UI to `paragraph` with startup sync.

Details are in `docs/FEATURES.md` and `docs/solutions.md`.

## Disclaimer

This software is provided "as is", without warranty of any kind.
