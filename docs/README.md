# PDF Editor (PySide6 + PyMuPDF)

Desktop PDF editor written in Python with a Qt UI.

## 1. Core Capabilities

- Open and save PDFs
- Page operations: delete, rotate, insert, export, merge
- Text editing with overlap-safe behavior
- Dedicated add-text mode
- Text properties commit/discard controls (`套用` / `取消`) with focus-safe inline editing
- Expanded CJK font options with optional Windows font embedding (`Microsoft JhengHei`, `PMingLiU`, `DFKai-SB`)
- Annotations: rectangle, highlight, free-text note
- Watermarks
- Search and jump
- Optional OCR
- Undo/redo via command history

## 2. Documentation Map

- Feature behavior: `docs/FEATURES.md`
- Architecture and boundaries: `docs/ARCHITECTURE.md`
- Issue history and fixes: `docs/solutions.md`
- Test script index: `test_scripts/TEST_SCRIPTS.md`

## 3. Requirements

- Python 3.10+
- Windows (primary development environment)

Third-party libraries used in this project:
- PySide6
- PyMuPDF (`fitz`)
- Pillow
- pytesseract (optional)

## 4. Install

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Optional dependencies:

```text
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

OCR note: install Tesseract OCR and ensure `tesseract` is available on PATH.

## 5. Run

```text
python main.py
```

## 6. Package (Windows)

```text
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

Output:

```text
dist\main.exe
```

## 7. Keyboard Shortcuts

- `Ctrl+O`: Open PDF
- `Ctrl+P`: Open print dialog
- `Ctrl+Z`: Undo
- `Ctrl+Y`: Redo
- `Ctrl+S`: Save
- `Ctrl+Shift+S`: Save As
- `F2`: Enter text edit mode
- `Esc`: Close active editor/dialog first; if none and not in browse mode, switch to browse mode

Close prompts for unsaved changes support:
- `Y`: Save
- `N`: Discard
- `Esc`: Cancel

## 8. Legal

No license is currently declared in this repository.
Add a `LICENSE` file if licensing terms are required.

## 9. Disclaimer

This software is provided "as is", without warranty of any kind.
