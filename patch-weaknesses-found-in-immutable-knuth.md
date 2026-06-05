# Security Patch Plan — PDF Editor (findings F1–F9)

## Context

Two-pass security review (`security-investigate.md` + `investigation-review.md`) identified 9 findings against the shipped codebase. The second pass tightened severities and corrected one sub-claim (F1 recursion — not present in code). This plan patches all evidence-backed findings in priority order from `investigation-review.md` without changing any user-visible feature behaviour.

Severity summary after re-assessment: **1 Medium (F1), 3 Low (F2/F4/F6), 3 Informational (F3/F5/F7/F8)**, 1 hygiene gap (F9 overlaps F2).

---

## Patches (ordered by risk×impact)

### P1 — F1: PDF resource guards *(Medium)*
**Files:** `model/pdf_model.py`, `model/tools/ocr_tool.py`  
**Why:** No pre-open size, page-count, or pixmap-pixel limits. Attacker-supplied PDF can OOM/hang the process.

Add three module-level constants in `pdf_model.py`:
```python
_MAX_PDF_BYTES    = 512 * 1024 * 1024   # 512 MB
_MAX_PAGES        = 5_000
_MAX_PIXMAP_PX    = 40_000_000          # 40 MP per rendered page
```

Add two helpers in `pdf_model.py`:
```python
def _guard_before_open(path: Path) -> None:
    if path.stat().st_size > _MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds size limit ({_MAX_PDF_BYTES // 1_048_576} MB)")

def _safe_render_scale(page: fitz.Page, scale: float) -> float:
    w, h = page.rect.width, page.rect.height
    if w * h * scale * scale > _MAX_PIXMAP_PX:
        scale = (_MAX_PIXMAP_PX / max(1.0, w * h)) ** 0.5
    return max(0.1, scale)
```

Apply guards:
- **`pdf_model.py` open path (~line 651):** call `_guard_before_open(src_path)` before `fitz.open`; after open check `if doc.page_count > _MAX_PAGES` and close+raise.
- **OCR render loop (`ocr_tool.py:257`):** replace `scale=render_scale` with `scale=_safe_render_scale(page_obj, render_scale)` — import the helper from `pdf_model` or duplicate as a private in `ocr_tool`.
- **Export raster and straighten raster (`pdf_model.py:~1143`, `~4830`):** wrap any `scale` passed to `get_page_pixmap` / `render_page_pixmap` through `_safe_render_scale`.

**Do NOT add recursion cap** — `_discover_form_nested_invocations` is depth-1 only (confirmed by review); no recursion exists.

**Tests (Red-Light first):**
- Open a synthetic file >`512 MB` → assert `ValueError` raised before `fitz.open`.
- Open a doc with `page_count` patched to `5001` via mock → assert `ValueError`.
- `_safe_render_scale` with a 10 000×10 000 page at scale 2.0 → assert returned scale ≤ `sqrt(40e6 / 1e8)` ≈ 0.632.

---

### P2 — F6: IPC socket user-isolation *(Low)*
**File:** `utils/single_instance.py`  
**Why:** `QLocalServer` created with no `UserAccessOption`; default named-pipe ACL on Windows may allow cross-session connections.

In `_listen_server()` (lines 26–31), add before `server.listen(name)`:
```python
server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
```

`QLocalServer` is already imported at line 10. `SocketOption` is a nested enum in PySide6 ≥ 6.4.

Also add path validation in `_handle_socket_message` after the `isinstance` check (line ~113): filter forwarded argv items so that any item that is an absolute path or ends in a known path separator must exist and have a `.pdf` suffix before `on_message` is called. Simplest form — reject the whole message if any argv item looks like a non-existent or non-`.pdf` file path:
```python
for item in argv:
    p = Path(item)
    if p.is_absolute() and (not p.exists() or p.suffix.lower() != ".pdf"):
        socket.write(b"0\n"); socket.flush(); return
```

**Tests:**
- Assert `_listen_server` creates a server whose `socketOptions()` includes `UserAccessOption`.
- Assert that a message with a non-existent path or a `.txt` path is rejected (socket writes `0\n`).
- Assert that a message with an existing `.pdf` path passes through.

---

### P3 — F4: Absolute subprocess binary paths *(Low)*
**Files:** `src/printing/platforms/win_driver.py`, `src/printing/platforms/linux_driver.py`

**win_driver.py (~line 862):** replace bare `"rundll32.exe"` with:
```python
import os
_rundll32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "rundll32.exe")
# ...
subprocess.Popen([_rundll32, "printui.dll,PrintUIEntry", "/e", "/n", normalized_name])
```
Place the constant at module level so it evaluates once.

**linux_driver.py (5 sites):** `shutil.which(...)` is currently used only as a boolean guard; the actual `subprocess.run` calls still pass the bare tool name. Fix each guarded site to capture and reuse the absolute path:

| Approx line | Tool | Current pattern | Fix |
|---|---|---|---|
| 58–65 | `lpstat` | `if shutil.which("lpstat"):` → `subprocess.run(["lpstat", …])` | `_lps = shutil.which("lpstat"); if not _lps: …; subprocess.run([_lps, …])` |
| 101–108 | `lpstat` | same | same |
| 183–203 | `lp` | `if shutil.which("lp") is None: raise; … cmd = ["lp", …]` | capture `lp_path = shutil.which("lp")`; use `lp_path` in `cmd` init |
| 237 (if lp) | `lp` | presence check only | same capture pattern |

Also fix any `lpoptions` call following the same pattern.

**Tests:**
- Unit test `open_printer_properties` on Windows: mock `subprocess.Popen`, assert `call_args[0][0][0]` ends with `System32\\rundll32.exe`.
- Unit test linux `list_printers`: mock `shutil.which` returning `/usr/bin/lpstat`, mock `subprocess.run`; assert `run` was called with `["/usr/bin/lpstat", …]` not `["lpstat", …]`.

---

### P4 — F8: Watermark JSON coercion on load *(Informational)*
**File:** `model/tools/watermark_tool.py`  
**Why:** Loaded watermark dicts have no type/range validation; oversized or maltyped fields reach rendering.

Add private helper `_coerce_wm` before `_load_watermarks_from_doc`:
```python
_WM_TEXT_MAX = 5_000
_WM_PAGES_MAX = 10_000

def _coerce_wm(wm: dict) -> dict | None:
    try:
        result: dict = {
            "id": str(wm["id"]),
            "pages": [int(p) for p in wm["pages"]][:_WM_PAGES_MAX],
        }
        for key, default in (("text", ""), ("font", ""), ("font_color_name", "")):
            result[key] = str(wm.get(key, default))
        result["text"] = result["text"][:_WM_TEXT_MAX]
        result["angle"] = float(wm.get("angle", 0)) % 360
        result["font_size"] = max(1.0, min(float(wm.get("font_size", 48)), 1000.0))
        result["opacity"] = max(0.0, min(float(wm.get("opacity", 0.5)), 1.0))
        for k in ("offset_x", "offset_y", "line_spacing"):
            if k in wm:
                result[k] = float(wm[k])
        if "color" in wm:
            result["color"] = tuple(wm["color"])
        return result
    except (KeyError, TypeError, ValueError):
        return None
```

In `_load_watermarks_from_doc`, replace the current append loop with:
```python
for wm in data:
    coerced = _coerce_wm(wm)
    if coerced is not None:
        loaded.append(coerced)
```

**Tests:**
- Pass dict with `font_size=1e9` → assert clamped to 1000.0.
- Pass dict with `text="x" * 10_000` → assert truncated to 5000 chars.
- Pass dict with wrong types (`"pages": "all"`) → assert returns `None` (dropped).
- Pass valid dict → assert passes through unchanged.

---

### P5 — F5: Temp-unlink error visibility *(Informational)*
**File:** `src/printing/dispatcher.py`  
**Why:** Silent `except Exception: pass` on temp file unlink masks cleanup failures (F5 + bandit B110).

Change the bare `except Exception: pass` in the `finally` block (lines 111–114) to log at debug:
```python
except Exception as exc:
    logger.debug("Failed to remove print temp file %s: %s", temp_path, exc)
```

Add `logger = logging.getLogger(__name__)` at module level if not already present.

**Tests:**
- Mock `Path.unlink` to raise `PermissionError`; assert no exception propagates and a debug-level log entry is emitted.

---

### P6 — F7: Release logging level *(Informational)*
**File:** `main.py`  
**Why:** `logging.basicConfig(level=logging.DEBUG)` exposes full paths and tracebacks in shipped builds.

In `_configure_logging()`:
```python
import os
_level = logging.DEBUG if os.environ.get("PDF_EDITOR_DEBUG") else logging.WARNING
logging.basicConfig(level=_level, format="%(asctime)s - %(levelname)s - %(message)s")
```

**Tests:**
- With `PDF_EDITOR_DEBUG` unset → assert root logger level is `WARNING`.
- With `PDF_EDITOR_DEBUG=1` → assert root logger level is `DEBUG`.

---

### P7 — F3: CUA agent action allowlist *(Informational/dev-only)*
**File:** `scripts/ux_signoff_agent.py`  
**Why:** `_execute_cua_action` has no action-type allowlist; model output could trigger `type`/`key` actions against untrusted input.

Add at module level:
```python
_ALLOWED_CUA_ACTIONS: frozenset[str] = frozenset({"click", "double_click", "scroll", "move", "screenshot"})
```

At the top of `_execute_cua_action`:
```python
atype = getattr(action, "type", None)
if atype not in _ALLOWED_CUA_ACTIONS:
    raise PermissionError(f"blocked CUA action type: {atype!r}")
```

**Tests:** assert that an action object with `type="type"` raises `PermissionError`; assert `type="click"` does not.

---

### P8 — F2: Raise Pillow floor *(Low/hygiene)*
**File:** `optional-requirements.txt`  
**Why:** `Pillow>=9.0` resolves to releases with 5 live CVEs (pip-audit confirmed).

Change:
```
Pillow>=9.0
```
to:
```
Pillow>=12.1.1
```

Add a comment:
```
# Run: pip-audit -r requirements.txt -r optional-requirements.txt
# to verify no known vulnerabilities in the resolved set.
```

The `surya-ocr`/`transformers` CVEs require researching which `surya-ocr` version pulls `transformers>=5.0.0rc3`. Do not raise the `surya-ocr` floor until that is confirmed — document this as an open item in TODOS.md.

**Tests:** CI integration test (`pip-audit -r optional-requirements.txt`) — note in TODOS.md but do not set up CI infra as part of this patch.

---

## Execution order

1. **P6** (main.py — 2-line change, zero risk) — fastest win
2. **P3** (absolute subprocess paths — mechanical, bounded) — two files
3. **P2** (IPC socket option — one call + path filter)
4. **P4** (watermark coercion — self-contained helper)
5. **P5** (dispatcher log — 1 line)
6. **P7** (CUA allowlist — dev-only, 2 lines)
7. **P1** (PDF resource guards — most surface area, requires careful integration)
8. **P8** (Pillow floor bump — packaging, no code)

Each patch: write failing test → confirm Red → implement → confirm Green → `ruff check .` → `pytest`.

---

## Files modified

| Patch | File(s) |
|---|---|
| P1 | `model/pdf_model.py`, `model/tools/ocr_tool.py` |
| P2 | `utils/single_instance.py` |
| P3 | `src/printing/platforms/win_driver.py`, `src/printing/platforms/linux_driver.py` |
| P4 | `model/tools/watermark_tool.py` |
| P5 | `src/printing/dispatcher.py` |
| P6 | `main.py` |
| P7 | `scripts/ux_signoff_agent.py` |
| P8 | `optional-requirements.txt` |

---

## Verification

After all patches:
1. `ruff check .` — zero new violations
2. `pytest` — no regressions (existing suite green)
3. Manual smoke: open a real PDF, OCR one page, print-dialog (Windows), round-trip watermark save/reload
4. `python -c "import logging; import main; main._configure_logging(); import logging; assert logging.root.level == logging.WARNING"` (no `PDF_EDITOR_DEBUG` set)
5. Confirm `utils/single_instance.py` creates server with `UserAccessOption` via `QLocalServer.socketOptions()` assertion
