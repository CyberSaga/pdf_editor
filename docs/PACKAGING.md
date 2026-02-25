# Packaging (Windows exe)

This project can be packaged into a Windows `.exe` using PyInstaller.

## Known issue: PyMuPDF + disassembly

PyInstaller's modulegraph uses Python's `dis` module to scan bytecode. Some
auto-generated SWIG wrappers (notably `pymupdf.mupdf`) can trigger a
`dis` bug on Python 3.10 that raises:

```
IndexError: tuple index out of range
```

This blocks analysis. The workaround used here is a tiny patch in
`PyInstaller/lib/modulegraph/util.py` to catch `IndexError` during
instruction iteration and skip scanning that code object.

Patch applied to the venv's PyInstaller:

```
.venv\Lib\site-packages\PyInstaller\lib\modulegraph\util.py
```

Change summary:
- Wrap `dis.get_instructions(...)` in `try/except IndexError`
- On error, emit `None` and return early

If you recreate the venv, re-apply this patch.

## Build steps (onefile, windowed)

Create venv and install dependencies:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_clean.txt
.venv\Scripts\python -m pip install pyinstaller
```

Build:

```
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed main.py
```

Output:

```
dist\main.exe
```

## Notes

- `requirements.txt` contains non-UTF8 characters and may fail to parse on
  some Windows locales. Use `requirements_clean.txt` for packaging.
- If using OCR (`pytesseract`), the target machine still needs Tesseract
  OCR installed; it is not bundled into the exe.
