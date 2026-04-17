**F3 Shell-Integration APIs Manual (CLI + Single-Instance + Headless Merge)**

This feature adds a small command-line interface to the app so you can:
- Open one or more PDFs from the shell
- Forward opens into an already-running window (single-instance behavior)
- Merge PDFs into a new output file without launching the UI (`--merge`)

It intentionally does **not** modify Windows registry / file associations.

---

## 1) Basic: Open PDFs from the shell

From the repo root `C:\Users\jiang\Documents\python programs\pdf_editor`:

```powershell
python main.py test_files\1.pdf
```

Open multiple PDFs:

```powershell
python main.py test_files\1.pdf test_files\2.pdf
```

**Behavior**
- If the app is not running, this starts it and opens the PDFs.
- If the app is already running, the new invocation forwards the file list to the running instance and exits (so you don’t get two windows).

---

## 2) Single-instance forwarding (what to expect)

When you run `python main.py some.pdf` while another instance is open:
- The second process should exit quickly.
- The first window should receive the new files (open them using the normal controller flow).

Notes:
- Single-instance forwarding is **per-user** (it won’t collide across OS users).
- It does not require admin privileges.

---

## 3) Headless merge: `--merge OUTPUT`

Merge multiple PDFs into a single output PDF **without launching UI**:

```powershell
python main.py --merge C:\Temp\merged.pdf test_files\1.pdf test_files\2.pdf
```

**Rules**
- `--merge OUTPUT` requires at least **one** input file after it.
- The **output directory must already exist**.
- Missing inputs or missing output directory cause an error.

**What it does**
- Creates `OUTPUT` as a new PDF with pages appended in the same order as the input list.

---

## 4) Help / usage

```powershell
python main.py --help
```

You should see something like:

- `usage: pdf_editor [-h] [--merge OUTPUT] [files ...]`
- positional `files`: PDF files to open
- `--merge OUTPUT`: merge inputs and exit

---

## 5) Paths and quoting (Windows)

If your path contains spaces, quote it:

```powershell
python main.py "C:\Users\jiang\Documents\python programs\pdf_editor\test_files\2.pdf"
```

For merge output with spaces:

```powershell
python main.py --merge "C:\Temp\merged output.pdf" "C:\path with spaces\a.pdf" "C:\path with spaces\b.pdf"
```

---

## 6) Exit codes (practical meaning)

- `0`: success (opened/forwarded successfully, or merge succeeded)
- `1`: failed to forward to a running instance (rare; usually indicates IPC trouble)

For merge failures (missing input, missing output directory), Python will also return a non-zero exit code.

---

## 7) Troubleshooting

**A second window opens instead of forwarding**
- That means the single-instance handshake didn’t happen (or the app wasn’t considered “running” yet).
- Try launching once and waiting for the UI to fully appear, then run the second command again.

**`--merge` fails because output directory doesn’t exist**
- Create it first:
  ```powershell
  New-Item -ItemType Directory -Force C:\Temp | Out-Null
  ```

**You want Explorer right-click integration**
- This feature deliberately stops short of registry/file-association work. The CLI and forwarding are the foundation; OS integration would be a separate, explicitly-approved phase.

---

## 8) Windows Explorer context-menu registration (HKCU only)

This section explains what to do **when you decide** to register the app into the Windows right-click menu.
It uses **per-user** registry keys under `HKCU` and does not require admin rights.

### 8.1 Choose the command target

You need a stable command that Explorer can run.

Recommended (packaged exe):
- Point the context-menu verb directly at your packaged `pdf_editor.exe` (or `main.exe` from PyInstaller) and pass PDF paths as arguments.

Development (python script):
- You can point at `python.exe` + `main.py`, but it is more fragile because it depends on a working Python environment and current paths.

The examples below use `PDF_EDITOR_EXE` as the executable path you want Explorer to invoke.

### 8.2 Add “Open in PDF Editor” for .pdf (multi-select opens tabs)

Add a verb under the `.pdf` file association:

- Key: `HKCU\Software\Classes\SystemFileAssociations\.pdf\shell\OpenInPdfEditor`
- Values:
  - `(Default)` = `Open in PDF Editor`
  - `MultiSelectModel` = `Player`
- Subkey: `command`
  - `(Default)` = `"C:\Path\To\PDF_EDITOR_EXE" %*`

Notes:
- `%*` lets Explorer pass all selected files as arguments, so your app can open them as multiple tabs.
- `MultiSelectModel=Player` is the standard opt-in to apply the verb to multi-selection.

**Importable .reg template**

Replace `C:\\Path\\To\\PDF_EDITOR_EXE` with your real executable path (double backslashes required in `.reg` files):

```reg
Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.pdf\shell\OpenInPdfEditor]
@="Open in PDF Editor"
"MultiSelectModel"="Player"

[HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.pdf\shell\OpenInPdfEditor\command]
@="\"C:\\Path\\To\\PDF_EDITOR_EXE\" %*"
```

### 8.3 Optional: Add “Merge PDFs…” (explicit merge only)

This registers a second verb that only merges when the user explicitly chooses it.

- Key: `HKCU\Software\Classes\SystemFileAssociations\.pdf\shell\MergePdfs`
- Values:
  - `(Default)` = `Merge PDFs...`
  - `MultiSelectModel` = `Player`
- Subkey: `command`
  - `(Default)` = `"C:\Path\To\PDF_EDITOR_EXE" --merge "C:\Temp\merged.pdf" %*`

Important:
- The output path is hard-coded in the verb command. For a real workflow, this is usually replaced with a small wrapper that prompts for output path, then calls `--merge`.
- The output directory must exist (per the CLI contract).

### 8.4 Remove the verbs (undo)

```reg
Windows Registry Editor Version 5.00

[-HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.pdf\shell\OpenInPdfEditor]
[-HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.pdf\shell\MergePdfs]
```

### 8.5 Safety checklist

- Export the key before experimenting:
  - `reg export "HKCU\Software\Classes\SystemFileAssociations\.pdf\shell" "%TEMP%\pdf_shell_verbs_backup.reg"`
- Prefer `HKCU` over `HKLM` so you never need admin rights.
- Keep merge as an explicit verb only; do not overload drag-drop or the default open path with merge behavior.

---

## 8) Quick verification commands

Headless merge and confirm page count:

```powershell
$out = Join-Path $env:TEMP "merged.pdf"
python main.py --merge $out test_files\1.pdf test_files\2.pdf
python -c "import fitz; d=fitz.open(r'%s'); print(d.page_count)" $out
```

If you want, tell me what your desired “shell integration” surface looks like (context-menu verbs, “Send to”, drag-drop, etc.), and I’ll map it onto the next F3/Future phase without touching registry unless you explicitly approve it.
