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
