# PDF Editor (PySide6 + PyMuPDF)

PDF editor desktop app written in Python with a Qt UI. It provides
page management, annotations, text editing (via redaction + reinsert),
watermarks, search, and optional OCR.

This document follows the structure of `PDF4QT-README.md`.

## 2. LEGAL ISSUES

No license is declared in this repository. If you need licensing
information, add a `LICENSE` file and update this section.

## 3. FEATURES

Key features:

- [x] open/save PDFs (incremental save supported)
- [x] page operations (delete/rotate/export/insert/merge)
- [x] text editing (redaction + reinsert; preserves existing annotations)
- [x] search & jump to results
- [x] annotations (rect/highlight/free-text) and visibility toggle
- [x] watermarks (persisted inside PDF metadata)
- [x] printing pipeline with preview/layout options
- [x] optional OCR via Tesseract
- [x] undo/redo via command system

Detailed feature flow and responsibilities are described in:
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`

## 4. THIRD PARTY LIBRARIES

- PySide6 (Qt UI)
- PyMuPDF (fitz)
- Pillow
- pytesseract (optional OCR)

## 6. INSTALLING

### Windows (end users)

If you have a packaged build, download it and run:

```
dist\main.exe
```

### Windows (development)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_clean.txt
```

### Optional printing backends

```
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

### OCR dependency

If you use OCR features, install Tesseract OCR on the machine and make
sure `tesseract` is on PATH.

## 7. RUNNING

```
python main.py
```

## 8. PACKAGING (Windows)

Packaging notes (including the PyMuPDF/PyInstaller workaround) are in:

- `docs/PACKAGING.md`

Build command:

```
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

Output:

```
dist\main.exe
```

## 9. DISCLAIMER

This software is provided "as is", without warranty of any kind.