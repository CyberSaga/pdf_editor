# Security Policy

## Supported Versions

CyberSagaPDF is currently maintained on the `main` branch. Security fixes are
applied to the latest public version unless otherwise noted.

## Reporting a Vulnerability

If you find a vulnerability, please open a GitHub issue with a clear description,
impact, affected workflow, and reproduction steps. If the issue involves
sensitive details, avoid posting exploit payloads or private documents publicly.

Useful reports include:

- A minimal PDF or workflow that reproduces the issue, if it can be shared
- The operating system and Python version
- The installed dependency set (`requirements.txt`, `optional-requirements.txt`,
  or `ocr-requirements.txt`)
- Whether the issue affects opening, saving, OCR, printing, optimization, export,
  temporary files, or document editing

## Security Scope

Relevant security areas include:

- PDF parsing and manipulation through PyMuPDF
- Local file handling, save-as behavior, exports, and overwrite prompts
- Temporary-file creation and cleanup
- Image processing and PDF optimization
- OCR integration and its isolated dependency tradeoffs
- Printing workflows and helper subprocess behavior
- Handling of untrusted PDF inputs
- Dependency safety for PySide6, PyMuPDF, Pillow, numpy, OCR tooling, and optional
  packaging dependencies

## Maintainer Authorization

This repository is maintained by the primary maintainer under the CyberSaga
GitHub account, which is authorized to administer and scan this repository.

