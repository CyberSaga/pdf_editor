# Startup Speed: Defer Heavy Imports Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate 55 MB of cold-boot disk reads that make the first launch after a reboot take 17 seconds instead of the expected ~4 seconds.

**Architecture:** Two module-level imports load native DLLs unnecessarily at startup; both are deferred to first use with the project's existing lazy-import pattern (function-body `import` statements for numpy; PEP 562 module `__getattr__` for the dialog re-exports).

**Tech Stack:** Python 3.10, PySide6, PyMuPDF; no new dependencies.

---

## Context

Cold-boot profiling (timer script on a freshly rebooted machine) shows `view.pdf_view` takes **5.74 s** of a 15.2 s total launch just for the import phase — because two dependency chains drag 55 MB of native DLLs off a cold disk:

| Chain | DLL size | Pulled in by |
|-------|----------|-------------|
| numpy (24 MB) | `numpy.libs/*.dll` × 2 | `view/text_editing.py:9` — `import numpy as np` at module top-level |
| PIL + pikepdf + lxml (31 MB) | `_imaging.pyd`, `_core.pyd`, `etree.pyd` | `view/pdf_view.py:225` — `from view.dialogs import (...)` → `model.pdf_optimizer` |

Neither is needed for the empty shell — numpy is only used when the user edits text, and the dialog classes are only instantiated when the user opens a dialog. Both are already treated as optional/deferred in the rest of the codebase (`model/pdf_model.py:4927`, `model/tools/ocr_tool.py:206`).

Warm-cache launches are fast (2.3 s) because the OS has already mapped these DLLs. Cold-boot exposed the hidden cost.

---

## Task 1 — Write the failing test

**Files:**
- Create: `test_scripts/test_startup_heavy_imports.py`

**Step 1: Write the test**

```python
"""Startup heavy-import guard.

Imports view.pdf_view in a clean subprocess and asserts that numpy, PIL,
pikepdf, and lxml are NOT loaded as a side effect.  These 55 MB of native
DLLs must remain deferred until first actual use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import sys, json, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"{root}")
import view.pdf_view  # noqa: F401 — side-effect import under test
heavy = [m for m in sys.modules if m.startswith(("numpy", "PIL", "pikepdf", "lxml"))]
print(json.dumps(sorted(heavy)))
""".format(root=str(ROOT).replace("\\", "\\\\"))


def _run_probe() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Probe failed:\n{result.stderr}"
    return json.loads(result.stdout.strip())


def test_numpy_not_loaded_at_pdf_view_import():
    """numpy must not appear in sys.modules after importing view.pdf_view."""
    loaded = _run_probe()
    numpy_mods = [m for m in loaded if m.startswith("numpy")]
    assert numpy_mods == [], (
        f"numpy loaded at startup (should be deferred to first text-edit use): {numpy_mods}"
    )


def test_pil_pikepdf_lxml_not_loaded_at_pdf_view_import():
    """PIL, pikepdf, and lxml must not appear in sys.modules after importing view.pdf_view."""
    loaded = _run_probe()
    heavy = [m for m in loaded if m.startswith(("PIL", "pikepdf", "lxml"))]
    assert heavy == [], (
        f"Heavy dialog deps loaded at startup (should be deferred to first dialog open): {heavy}"
    )
```

**Step 2: Run the test — confirm RED**

```
python -m pytest test_scripts/test_startup_heavy_imports.py -v
```

Expected output (both tests FAIL):
```
FAILED test_startup_heavy_imports.py::test_numpy_not_loaded_at_pdf_view_import
FAILED test_startup_heavy_imports.py::test_pil_pikepdf_lxml_not_loaded_at_pdf_view_import
```

**Do not proceed until both tests fail.**

---

## Task 2 — Defer numpy in `view/text_editing.py`

**Files:**
- Modify: `view/text_editing.py`

**Step 1: Remove the module-level numpy import (lines 7–11)**

Delete exactly these lines from the file:
```python
try:
    import numpy as np
except ImportError:
    np = None
```

**Step 2: Add a function-local import to each of the 5 numpy-using functions**

Each function already has an `if np is not None:` branch. Add the try/except at the **top of the function body**, before any other code in the function. The five functions and their insertion points:

**`_qimage_mean_rgb`** — insert after the function signature line (`def _qimage_mean_rgb(...):`):
```python
    try:
        import numpy as np
    except ImportError:
        np = None
```

**`_qimage_ring_mean_rgb`** — same pattern, after its `def` line.

**`_blend_patch_towards_rgb`** — same pattern, after its `def` line.

**`_mask_leak_ratio`** — same pattern, after its `def` line.

**`PreviewBackedInlineTextEditor._mutated_preview_has_visible_ink`** — same pattern, after its `def` line (this is a method, so indented 4 + 4 = 8 spaces).

The existing `if np is not None:` guards and the pure-Python fallback branches are **unchanged**.

**Step 3: Run ruff**

```
python -m ruff check view/text_editing.py
```

Expected: zero violations.

---

## Task 3 — Defer dialog re-exports in `view/pdf_view.py`

**Files:**
- Modify: `view/pdf_view.py`

**Step 1: Remove the eager re-export block (lines 223–234)**

Delete exactly these lines:
```python
# Dialog classes have been extracted to view/dialogs/ for maintainability.
# Re-exported here so all existing `from view.pdf_view import ...` call sites continue to work.
from view.dialogs import (  # noqa: E402, F401
    AuditStackedBar,
    ExportPagesDialog,
    MergePdfDialog,
    OcrDialog,
    OptimizePdfDialog,
    PDFPasswordDialog,
    PdfAuditReportDialog,
    WatermarkDialog,
)
```

**Step 2: Replace with a lazy `__getattr__` block at the same location**

Insert in place of the deleted block:
```python
# Dialog classes are loaded lazily (PEP 562 module __getattr__) so PIL/pikepdf/lxml
# don't load at startup. Both attribute access and `from view.pdf_view import Name`
# trigger __getattr__ on first use; the result is cached in globals() afterwards.
_DIALOG_EXPORTS: dict[str, str] = {
    "AuditStackedBar": "view.dialogs.audit",
    "ExportPagesDialog": "view.dialogs.export",
    "MergePdfDialog": "view.dialogs.merge",
    "OcrDialog": "view.dialogs.ocr",
    "OptimizePdfDialog": "view.dialogs.optimize",
    "PDFPasswordDialog": "view.dialogs.password",
    "PdfAuditReportDialog": "view.dialogs.audit",
    "WatermarkDialog": "view.dialogs.watermark",
}


def __getattr__(name: str) -> object:
    if name in _DIALOG_EXPORTS:
        import importlib
        mod = importlib.import_module(_DIALOG_EXPORTS[name])
        obj = getattr(mod, name)
        globals()[name] = obj  # cache so __getattr__ is only called once per name
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Step 3: Run ruff**

```
python -m ruff check view/pdf_view.py
```

Expected: zero violations.

---

## Task 4 — Verify green and measure improvement

**Step 1: Run the new test — confirm GREEN**

```
python -m pytest test_scripts/test_startup_heavy_imports.py -v
```

Expected: both tests PASS.

**Step 2: Check sys.modules manually (quick sanity)**

```
python -c "import sys, os; os.environ['QT_QPA_PLATFORM']='offscreen'; sys.path.insert(0,'.'); import view.pdf_view; heavy=[m for m in sys.modules if m.startswith(('numpy','PIL','pikepdf','lxml'))]; print('Heavy at startup:',heavy or 'none')"
```

Expected output: `Heavy at startup: none`

**Step 3: Run regression suite**

```
python -m pytest test_scripts/test_main_startup_behavior.py test_scripts/test_pdf_optimize_workflow.py test_scripts/test_pdf_merge_workflow.py -v
```

Expected: all pass.

**Step 4: Run mypy (required scope)**

```
python -m mypy model/ utils/ --ignore-missing-imports
```

Expected: no new errors.

**Step 5: Measure cold-start improvement**

Run the timer script (already exists as `C:\Users\jiang\AppData\Local\Temp\pdf_startup_timer2.py`):

```
python "C:\Users\jiang\AppData\Local\Temp\pdf_startup_timer2.py"
```

After a warm run, reboot and run again to compare cold-boot. Target: `view.pdf_view imported` checkpoint drops from 5.74 s to under 1.5 s.

---

## Task 5 — Update docs

**Step 1: Append to `docs/PITFALLS.md`**

```markdown
## Eager module-level imports of optional native deps block cold-boot startup

**Area:** `view/text_editing.py`, `view/pdf_view.py`
**Symptom:** First launch after reboot took 15+ seconds; subsequent launches were fast (2–3 s).
**Cause:** Two module-level import chains loaded 55 MB of native DLLs before the window appeared:
1. `view/text_editing.py` had `try: import numpy as np` at module top — ran the 24 MB numpy load the moment any code imported the module, even before any text editing.
2. `view/pdf_view.py` had `from view.dialogs import (...)` at module level — chained through `model.pdf_optimizer` → PIL + pikepdf (which pulls lxml), 31 MB total.
**Fix:** Moved the `try: import numpy as np / except ImportError: np = None` block inside each of the 5 numpy-using functions. Replaced the eager dialog re-export block in `view/pdf_view.py` with a PEP 562 module-level `__getattr__` that imports from `view.dialogs` on first access and caches names into `globals()`.
**File:** `view/text_editing.py`, `view/pdf_view.py`
**Tests:** `test_scripts/test_startup_heavy_imports.py`
```

**Step 2: Add note to `docs/ARCHITECTURE.md`**

Find the section on the View layer and append a paragraph:

```markdown
**Deferred heavy imports:** `view/text_editing.py` defers `import numpy` to the first call of each numpy-using helper (function-body import, same pattern as `model/pdf_model.py:_render_page_gray_array`). `view/pdf_view.py` re-exports dialog classes via a PEP 562 module `__getattr__` so PIL/pikepdf/lxml (31 MB) only load when a dialog is first opened — after `view.show()`. Both ensure cold-boot DLL reads stay under 30 MB.
```

**Step 3: Commit**

```
git add view/text_editing.py view/pdf_view.py test_scripts/test_startup_heavy_imports.py docs/PITFALLS.md docs/ARCHITECTURE.md
git commit
```

---

## Expected outcome

| Metric | Before | After |
|--------|--------|-------|
| Cold-boot `view.pdf_view` import | 5.74 s | < 1.5 s |
| Cold-boot total to window | ~15 s | ~9–11 s |
| Warm-cache total | 2.3 s | ~1.5 s |
| Modules loaded at `view.pdf_view` import | 407 | ~286 |
| Native DLLs read on cold boot | 55 MB extra | 0 MB extra |
