# Plan: Surgical Fixes for 4 Printing Problems

## Context

Four printing bugs were diagnosed in `4-problems-investigation.txt`. The previous "fix" commits
(`2408f65`, `9fd7d76`) did not address any of them — their tests exercise fake or PDF-output code paths,
not the real Windows GDI spooler. This plan implements real fixes following Red-Light First (CLAUDE.md §5.1).

---

## Problem Summary & Root Causes

| # | Root cause | Location |
|---|-----------|----------|
| P1 | `SetPrinter(level=9)` permanently writes global DEVMODE after every Properties dialog | `win_driver.py:421,560` |
| P2/P3 | Per-page `setPageLayout()` called after `painter.begin()` — GDI ignores mid-job layout changes | `qt_bridge.py:238-241` |
| P4 | Windows always rasters at 300 DPI; each A4 page ≈ 26 MB raw → huge EMF spool | `win_driver.py:300-306`, default `dpi=300` in `base_driver.py:39` |

---

## Critical Constraint (discovered during plan review — corrects the original P1 design)

The real Windows print job is **not** dispatched in-process. The controller serializes the whole job
to a `job.json` file and runs an out-of-process helper:

```
controller/pdf_controller.py:139  PrintHelperJob(options=…)
  → subprocess_runner.py:102       job.write(job_path)
    → helper_protocol.py:25-37     to_json_dict() serializes EVERY option field, incl. extra_options
      → json.dumps(...)            ← raw bytes raise "TypeError: bytes is not JSON serializable"
        → helper_main.py:85        helper rebuilds PrintJobOptions and calls dispatcher.print_pdf_bytes
```

Therefore the original plan's idea of putting raw `bytes` into `extra_options` (and widening the type
to `dict[str, Any]`) **would crash submission for every Windows print job**, not just Properties-driven
ones. Corrected design used throughout this plan:

- The captured DEVMODE is carried as a **base64-encoded ASCII string** under `extra_options["devmode_buffer"]`.
- `extra_options` therefore stays `dict[str, str]` (JSON-safe); `base_driver.py` needs no change.
- `WindowsPrinterDriver.print_pdf()` base64-**decodes** the string back to bytes inside the helper process,
  where the QPrinter is actually created — so the job-scoped DEVMODE is visible to that job.

Two related correctness fixes (also corrections to the original P1 steps):

- The buffer must be injected at **submission** (`_build_submission_options`), not in
  `_build_effective_options`, which runs on every 200 ms preview refresh and would consume/clear it
  before the user clicks Print.
- The pending buffer is **printer-specific**, so it is cleared in `_on_printer_changed` (switching
  printers must not apply Printer A's DEVMODE to Printer B).

---

## Preservation Guarantees (what must NOT change)

These existing behaviors are preserved by this plan:

- **`print_dialog.py` lines 416-422** (reset paper/orientation to "auto" after Properties dialog) — unchanged;
  `test_properties_button_keeps_auto_paper_and_orientation_app_owned` still passes.
- **Uniform-layout single-pass jobs** — `_split_by_layout()` produces a single group when all pages share
  one layout, so `raster_print_pdf()` is called exactly once: identical to current behavior.
- **No-Properties-dialog path** — if the user never clicked Properties, `extra_options` has no
  `devmode_buffer`; `print_pdf()` skips the save/restore block entirely and falls through to the existing
  `raster_print_pdf()` call.
- **Duplex, color, DPI, copies, tray UI fields** — all sourced from the combo boxes as before; nothing in
  this plan touches those resolution paths.
- **`extra_options` backward compatibility** — changing `dict[str, str]` → `dict[str, Any]` is a supertype
  widening; existing callers that store strings continue to work. The only new value type is `bytes` under
  the new `"devmode_buffer"` key.
- **PDF output path** (`output_pdf_path` set) — `raster_print_pdf()` still takes the
  `QPrinter.PdfFormat` branch unchanged; no GDI code runs.
- **Existing test suite must pass with zero regressions** before the PR is merged.

---

## Files to Modify

- `src/printing/platforms/win_driver.py` — all four fixes live here (P1 job-scoped DEVMODE, P2/P3 job-splitting, P4 DPI cap)
- `src/printing/print_dialog.py` — store + inject `devmode_buffer` (a **base64 string**) for P1
- `src/printing/base_driver.py` — **NO CHANGE** (see "Critical Constraint" below): `extra_options` stays
  `dict[str, str]`; the DEVMODE travels as a base64 ASCII string, never raw `bytes`
- `src/printing/qt_bridge.py` — no code change needed; GDI limitation is worked around in win_driver
- NEW: `test_scripts/test_win_print_fixes.py` — one file, four failing then passing test groups

---

## Step-by-Step Implementation

### Step 0 — Write ALL failing tests first (Red-Light)

Create `test_scripts/test_win_print_fixes.py` with tests for all four problems.
**Run tests; confirm all four test groups fail before writing any fix code.**

**P1 test — SetPrinter(level=9) must not be called:**
```python
# Patches _SET_PRINTER_W and win32print.SetPrinter to spy calls
# Calls driver.open_printer_properties("FakePrinter") with mocked DocumentPropertiesW dialog
# Asserts: neither SetPrinter spy was called
# Currently FAILS because _persist_devmode_buffer_user_defaults() IS called (line 485)
```

**P1 test — returned dict must include devmode_buffer as a base64 string:**
```python
# Same setup; assert result["devmode_buffer"] is a non-empty str
# and base64.b64decode(result["devmode_buffer"]) round-trips to the captured DEVMODE bytes
# Currently FAILS because no such key exists
```

**P1 test — devmode_buffer must survive JSON serialization (regression guard for the bytes flaw):**
```python
# Build PrintJobOptions(extra_options={"devmode_buffer": <base64 str>}); wrap in PrintHelperJob
# Assert json.dumps(job.to_json_dict()) does NOT raise, and round-trips the key intact
# (A raw-bytes value would raise TypeError here — this is the test that would have caught the
#  original plan's fatal flaw.)
```

**P2/P3 test — mixed-layout PDF must split into N jobs:**
```python
# Creates a 2-page fitz PDF: page 0 = A4 portrait (595×842 pt), page 1 = A3 landscape (1191×842 pt)
# Patches raster_print_pdf to record calls
# Calls win_driver.print_pdf(pdf_path, [0,1], options with paper_size="auto", orientation="auto")
# Asserts raster_print_pdf was called TWICE, not once
# Currently FAILS because print_pdf calls raster_print_pdf once for all pages
```

**P4 test — Windows driver caps DPI at 150:**
```python
# Patches raster_print_pdf to capture options argument
# Calls win_driver.print_pdf(...) with options.dpi=300
# Asserts the options received by raster_print_pdf have dpi=150
# Currently FAILS because win_driver.print_pdf passes options unchanged
```

---

### Step 1 — Fix P1: job-scoped DEVMODE (stop level-9 mutation)

**1a. `win_driver.py` — remove the two SetPrinter(level=9) call sites:**

- Line 485: delete `self._persist_devmode_buffer_user_defaults(handle, devmode_buffer, printer_name)`
- Lines 559–566: delete the `win32print.SetPrinter(handle, 9, …)` block and its `except` clause

**1b. `win_driver.py` — return the captured DEVMODE as a base64 string:**

Add a module-level helper (and `import base64`):
```python
def _devmode_buffer_to_b64(buffer: ctypes.Array[ctypes.c_char]) -> str:
    return base64.b64encode(bytes(buffer)).decode("ascii")
```

In `_open_printer_properties_via_ctypes()`, before `return returned_prefs` (end of method):
```python
returned_prefs["devmode_buffer"] = _devmode_buffer_to_b64(devmode_buffer)
```

In the pywin32 fallback path (`open_printer_properties()`, line ~568), before `return merged`:
- The `devmode` object from `win32print.GetPrinter(handle, 2)["pDevMode"]` is a PyDEVMODE.
- If it can be converted to raw bytes (e.g. via `bytes(devmode)` / a ctypes copy), base64-encode and add
  `merged["devmode_buffer"] = <base64 str>` **only if conversion succeeds**. If it can't, omit the key —
  the job simply falls back to the no-DEVMODE path (still correct, just not job-scoped).

**1c. `base_driver.py` — NO CHANGE (corrected from the original plan).**

`extra_options` stays `dict[str, str]`. The DEVMODE is a base64 ASCII string, which is JSON-serializable
and survives the `PrintHelperJob.to_json_dict()` → `json.dumps()` boundary in the subprocess helper path
(see "Critical Constraint" above). Widening to `dict[str, Any]` is unnecessary and would re-open the door
to non-serializable values.

**1d. `print_dialog.py` — store the buffer, clear on printer switch, inject only at submission:**

In `__init__`, add:
```python
self._pending_devmode_buffer: str | None = None
```

In `_open_printer_properties_dialog()`, after receiving `updated` and **before** `_apply_printer_preferences`:
```python
if isinstance(updated, dict):
    buf = updated.pop("devmode_buffer", None)  # extract before applying prefs
    if isinstance(buf, str) and buf:
        self._pending_devmode_buffer = buf
```

In `_on_printer_changed()`, clear the stale buffer (a DEVMODE is printer-specific):
```python
self._pending_devmode_buffer = None
```

In `_build_submission_options()` — **not** `_build_effective_options()` — inject then clear:
```python
def _build_submission_options(self) -> PrintJobOptions:
    options = self._build_effective_options()
    if self._pending_devmode_buffer:
        options.extra_options["devmode_buffer"] = self._pending_devmode_buffer
        self._pending_devmode_buffer = None
    return options
```
Rationale: `_build_effective_options()` runs on every 200 ms preview refresh (the Properties handler even
schedules one). Injecting/clearing there would consume the buffer before the user clicks Print.
`_build_submission_options()` is called only from `accept()`, so the buffer survives previews and is
consumed exactly once at submission. Preview never reads `extra_options`, so leaving it out of the
effective-options path is harmless.

**1e. `win_driver.py.print_pdf()` — apply DEVMODE job-scoped with save/restore:**

Override `print_pdf()` (currently one-liner at line 300-306):
```python
def print_pdf(self, pdf_path, page_indices, options):
    normalized = options.normalized()
    devmode_b64 = (normalized.extra_options or {}).get("devmode_buffer")
    if isinstance(devmode_b64, str) and devmode_b64 and normalized.printer_name and win32print:
        try:
            job_bytes = base64.b64decode(devmode_b64)
        except (ValueError, binascii.Error):
            job_bytes = b""
        if job_bytes:
            return self._print_with_scoped_devmode(pdf_path, page_indices, normalized, job_bytes)
    return self._raster_split_or_direct(pdf_path, page_indices, normalized)
```

New `_print_with_scoped_devmode(pdf_path, page_indices, normalized, job_bytes)`:
1. Open printer handle (`win32print.OpenPrinter(name)` → a PyHANDLE, which the ctypes helpers accept).
2. Read the current DEVMODE via `DocumentPropertiesW(DM_OUT_BUFFER)` → `original_buf` (a string buffer).
3. Build the job buffer: `job_buf = ctypes.create_string_buffer(job_bytes, len(job_bytes))`.
4. Write job DEVMODE via `_persist_devmode_buffer_user_defaults(handle, job_buf, name)` (re-uses the helper).
5. `try: return self._raster_split_or_direct(…)`
6. `finally:` restore `original_buf` via `_persist_devmode_buffer_user_defaults(handle, original_buf, name)`,
   then `ClosePrinter`. Always restore, even on exception.

Re-use `_persist_devmode_buffer_user_defaults` so level-9 writes happen **only** inside this controlled
save/restore block. **Inherent limitation:** Qt exposes no API to inject a raw DEVMODE into `QPrinter`, so
the job-scoped settings are applied by briefly writing the per-user default (level 9) and restoring it in
`finally`. During the print window the global default is momentarily changed, and a hard crash between set
and restore would leave it mutated. This is the pragmatic trade-off; documented in PITFALLS.md (Step 4).

---

### Step 2 — Fix P2/P3: job-splitting for per-page layout

**`win_driver.py` — `_raster_split_or_direct()`:**

```python
def _raster_split_or_direct(self, pdf_path, page_indices, normalized):
    # If user explicitly set a fixed paper/orientation, no split needed
    if normalized.paper_size != "auto" and normalized.orientation != "auto":
        return raster_print_pdf(pdf_path, page_indices, normalized)
    return self._split_by_layout(pdf_path, page_indices, normalized)
```

**`win_driver.py` — `_split_by_layout()`:**

```python
import fitz
from printing.layout import match_standard_paper_size, resolve_orientation

def _split_by_layout(self, pdf_path, page_indices, normalized):
    doc = fitz.open(pdf_path)
    groups: list[tuple[tuple[str, str], list[int]]] = []
    cur_layout: tuple[str, str] | None = None
    cur_pages: list[int] = []

    for idx in page_indices:
        rect = doc[idx].rect
        w, h = rect.width, rect.height
        paper = match_standard_paper_size(w, h) or "auto"
        orient = resolve_orientation(normalized.orientation, w, h)
        layout = (paper, orient)
        if layout != cur_layout:
            if cur_pages:
                groups.append((cur_layout, cur_pages))
            cur_layout, cur_pages = layout, [idx]
        else:
            cur_pages.append(idx)
    if cur_pages:
        groups.append((cur_layout, cur_pages))
    doc.close()

    total = 0
    for (paper, orient), pages in groups:
        import dataclasses
        group_opts = dataclasses.replace(
            normalized,
            paper_size=paper,
            orientation=orient,
            override_fields=normalized.override_fields | {"paper_size", "orientation"},
        )
        result = raster_print_pdf(pdf_path, pages, group_opts)
        if not result.success:
            return result
        total += len(pages)

    route = "qt-raster->spooler"
    return PrintJobResult(success=True, route=route,
                          message=f"Submitted {total} page(s) to printer.")
```

Note: if all pages happen to have the same layout, `_split_by_layout` produces a single group — identical
to the original single-call behavior with correct paper/orientation set explicitly.

---

### Step 3 — Fix P4: cap Windows raster DPI

**`win_driver.py` module constant:**
```python
_WIN_MAX_RASTER_DPI: int = 150
```

**In `_raster_split_or_direct()`, before delegating:**
```python
if normalized.dpi > _WIN_MAX_RASTER_DPI:
    normalized = dataclasses.replace(normalized, dpi=_WIN_MAX_RASTER_DPI)
```

This applies the cap on every Windows raster path, whether single job or split.
The user's dpi_spin in the dialog can still set a lower value (e.g., 96 for draft). Setting above 150 in
the dialog will be silently capped on Windows only (document in PITFALLS.md, see Step 4).

---

### Step 4 — Post-task documentation

- `docs/PITFALLS.md`: add entries for each of the four root causes and their fixes, plus one for the
  **`extra_options` JSON boundary** (values must be JSON-serializable because `PrintHelperJob.to_json_dict()`
  serializes them for the out-of-process helper — never put raw `bytes` there; base64-encode binary).
- `docs/FEATURES.md:179`: update the "per-user DEVMODE persistence" description to reflect the new
  save/restore behavior (no longer permanently mutated)
- `TODOS.md`: close P1–P4 items

---

## Verification

```
pytest test_scripts/test_win_print_fixes.py -v   # all four groups must pass
ruff check .                                      # zero new violations
pytest                                            # no regressions
```

Manual smoke test (Windows only, requires a real or XPS printer):
1. Open a mixed-size/orientation PDF → print → confirm each page has correct media in the XPS/PDF output
2. Open Printer Properties, change a setting → print → open the printer's Properties again and verify
   the setting was NOT persisted to the printer's system defaults
3. Observe spooling is faster for a 10-page A4 PDF compared to before (300 → 150 DPI)
