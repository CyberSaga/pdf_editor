# CyberSagaPDF (PySide6 + PyMuPDF)

Open-source Python desktop PDF editor with a Qt UI. CyberSagaPDF focuses on
local PDF editing workflows: text editing, page operations, image/object
editing, annotations, OCR integration, PDF optimization, export, and resilient
Windows printing.

## Security Relevance

CyberSagaPDF processes local PDF documents and related assets through PyMuPDF,
PySide6, optional OCR dependencies, temporary files, image handling, printing
workflows, and PDF optimization. PDF files can contain complex structures and
untrusted inputs, so security review matters for parsing behavior, dependency
usage, document handling, temporary-file safety, and desktop workflow
reliability.

The project is publicly maintained under the CyberSaga GitHub account. The
repository owner is authorized to administer and scan this repository.

## Security and CI

The repository includes a GitHub Actions CI workflow for dependency and security
checks. Core and optional Python requirements are audited with `pip-audit`, OCR
dependencies are isolated in `ocr-requirements.txt`, and security-focused
regression tests cover dependency floors and OCR weight handling. The project
also documents supported versions and vulnerability reporting in `SECURITY.md`.

## Core Capabilities

- Open and save PDFs
- Drag one or more local PDF files into the app as separate tabs
- Page operations: delete, rotate, insert, export, merge
- Object editing: move, resize, rotate, and delete rectangles or images
- Text editing with overlap-safe WYSIWYG behavior
- Add-text mode, annotations, watermarks, search, and undo/redo
- File optimization with size-reduction summaries
- Unified export to PDF or images (`JPG`, `PNG`, `TIFF`)
- Optional OCR through a separate dependency set
- Resilient Windows printing through isolated raster submission

## Project Status

This repository is actively maintained by the primary maintainer. The current
public development target is the `main` branch, with Windows as the primary
development environment.

## Documentation

- Feature behavior: `docs/FEATURES.md`
- Architecture and boundaries: `docs/ARCHITECTURE.md`
- Main project README: `docs/README.md`
- Traditional Chinese README: `docs/README.zh-TW.md`
- Security policy: `SECURITY.md`
- Contribution guide: `CONTRIBUTING.md`
- Test script index: `test_scripts/TEST_SCRIPTS.md`

## Requirements

- Python 3.10+
- Windows is the primary supported environment
- PySide6
- PyMuPDF (`fitz`)
- Pillow
- numpy
- Optional OCR stack: `surya-ocr`, `torch`

## Install

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Optional dependencies:

```text
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

OCR dependencies are intentionally separated because they carry different
dependency and security tradeoffs:

```text
.venv\Scripts\python -m pip install -r ocr-requirements.txt
```

## Run

```text
python main.py
```

## Test

```text
.venv\Scripts\python -m pytest test_scripts/
```

For coverage:

```text
.venv\Scripts\python -m pytest test_scripts/ --cov --cov-report=term-missing
```

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3).

